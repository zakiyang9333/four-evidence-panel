"""「任务」页的后端：盯盘任务和分析记录。全部存在本机 data/quant/（不进 git），不往外发任何东西。

- 盯盘任务：选一只标的、一个模型、一个方向（外加周期和 K 线级别），程序在每次有新 K 线之后替你把这套清单看一眼。
  清单在某一根 K 线上齐了，就在任务页记一笔并亮红点。它只是提醒：不下单，也不替你做决定。
  任务页里打开了「提醒」，还会发一条 Mac 通知和/或 iMessage（mine.send；发到手机的那条不带持仓数字）。
- 线的提醒（line_alerts）：收盘价穿过他持仓里的线（成本、短 put 行权价、归零线、估值参考），同样发一条。
  检查是按收盘后的 K 线做的，和分析页点出来的结果是同一段代码（quant.result），不会出现两边说法不一样。
- 分析记录：每点一次「AI 分析当前图表」记一行（哪只、哪一天、哪个模型、哪个方向、当时的结论和表盘），点一行能回到那一刻。
"""
import json
import os
import secrets
import threading
import time

import mine
import panel
import quant

MAX_TASKS, MAX_RUNS, MAX_HITS, CATCH_UP = 30, 300, 20, 15
_lock = threading.RLock()


def tasks_dir():
    return os.environ.get('FE_TASKS_DIR') or os.path.join(panel.data_dir(), 'quant')


def now_text():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _read(name, default):
    try:
        with open(os.path.join(tasks_dir(), name), encoding='utf-8') as f:
            x = json.load(f)
        return x if isinstance(x, type(default)) else default
    except (OSError, ValueError):
        return default


def _write(name, data):
    os.makedirs(tasks_dir(), exist_ok=True)
    path = os.path.join(tasks_dir(), name)
    with open(path + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(path + '.tmp', path)


def _label(a, tf=None):
    return f"{a['ticker']} · {quant.MODEL[a['model']]['name']} · {quant.SIDE_NAME[a['side']]} · {quant.horizon_label(a['horizon'], a['tf'])} · {quant.TF_NAME[a['tf']]}"


def _clean(src):
    """ticker + the analysis inputs of a task or a run, validated. Raises KeyError for an unknown ticker, ValueError for an unknown model."""
    t = src.get('ticker', '')
    if t not in panel.TICKERS:
        raise KeyError(t)
    a = quant.norm(src.get('model'), src.get('side'), src.get('hz', src.get('horizon')), src.get('tf'), 'flat')
    return dict(ticker=t, model=a['model'], side=a['side'], horizon=a['horizon'], tf=a['tf'])


# ---------- watch tasks ----------

def _check(task, force=False):
    """Bring one task up to date: evaluate every bar that arrived since it was last checked (at most CATCH_UP of them)."""
    d = quant.bars(task['ticker'], task['tf'])['d']
    last = task.get('checked_asof')
    if not force and last == d[-1]:
        return False
    todo = [x for x in d[-CATCH_UP:] if last is None or x > last] or [d[-1]]
    if last is None:
        todo = todo[-1:]                    # 新建的任务从现在开始看，不翻旧账
    for asof in todo:
        cell = quant.scan_cell(task['ticker'], task['model'], task['side'], task['horizon'], task['tf'], asof)
        if cell['state'] == 'ready' and not any(h['asof'] == asof for h in task['hits']):
            task['hits'].insert(0, dict(asof=asof, verdict=cell['verdict'], price=cell['price'], zone=cell['zone'], stop=cell['stop'], t1=cell['t1'], t2=cell['t2'],
                                        rr=cell['rr'], found_at=now_text(), seen=False))
            del task['hits'][MAX_HITS:]
            # 提醒（他在任务页打开了才发）：Mac 通知可以带细节；推到手机的那条只说哪只、什么事，不带任何持仓数字
            mine.send(f"task:{task['id']}:{asof}", f"{task['label']}：{cell['verdict']}（{asof} 收盘，现价 {cell['price']}）",
                      f"{task['ticker']} 盯盘任务条件齐了（{asof} 收盘），打开面板看")
    task.update(checked_asof=d[-1], checked_at=now_text(),
                last=dict(asof=cell['asof'], state=cell['state'], verdict=cell['verdict'], ok=cell['ok'], of=cell['of'], price=cell['price'], supported=cell['supported']))
    return True


def line_alerts():
    """收盘价穿过他持仓里的线（成本、短 put 行权价、归零线、估值参考）时提醒一次（同一条线同一天只提醒一次）。
    只比日线最后两根收盘。返回这一次发现的穿越（不管有没有打开提醒）。"""
    import portfolio
    st, err = portfolio.read_state()
    if err:
        return []
    out = []
    for t, ov in portfolio.overlays(st).items():
        B = panel.load(t)['B']
        if len(B['c']) < 2:
            continue
        prev, last, day = float(B['c'][-2]), float(B['c'][-1]), B['d'][-1]
        for ln in ov['lines'] + ov['valuation']:
            L = float(ln['price'])
            if (prev - L) * (last - L) < 0 or (last == L != prev):
                way = '跌破' if last < prev else '站上'
                out.append(dict(ticker=t, date=day, label=ln['label'], way=way))
                mine.send(f"line:{t}:{ln['label']}:{day}", f"{t} {day} 收盘 {last:.2f}，{way}了你的「{ln['label']}」{L:g}",
                          f"{t} {day} 收盘碰到了你持仓里的一条线，打开面板看")
    return out


def listing(check=True, force=False):
    with _lock:
        rows = _read('tasks.json', [])
        changed = False
        if check:
            for task in rows:
                if task.get('enabled', True):
                    try:
                        changed = _check(task, force) or changed
                    except Exception as e:      # noqa: BLE001  一个任务算不出来，不连累别的
                        task['error'] = type(e).__name__
                        changed = True
                    else:
                        if task.pop('error', None):
                            changed = True
        if changed:
            _write('tasks.json', rows)
        unseen = sum(1 for t in rows for h in t['hits'] if not h.get('seen'))
        return dict(ok=True, tasks=rows, unseen=unseen, limit=MAX_TASKS)


def add(src):
    with _lock:
        a = _clean(src)
        M = quant.MODEL[a['model']]
        if a['side'] not in M['sides']:
            raise ValueError(M.get('no_short', '这个模型没有这个方向的规则，盯不了。'))
        if a['tf'] not in M['tfs']:
            raise ValueError(M.get('no_week', '这个模型不看这个级别的 K 线，盯不了。'))
        rows = _read('tasks.json', [])
        if any(all(t[k] == a[k] for k in a) for t in rows):
            raise ValueError('这个盯盘任务已经有了。')
        if len(rows) >= MAX_TASKS:
            raise ValueError(f'最多 {MAX_TASKS} 个盯盘任务，先删掉几个。')
        task = dict(a, id=secrets.token_hex(4), label=_label(a), created=now_text(), enabled=True, hits=[], checked_asof=None)
        _check(task)
        rows.insert(0, task)
        _write('tasks.json', rows)
        return task


def update(tid, enabled=None, delete=False, seen=False):
    """Pause / resume / delete one task, or mark its hits as seen (tid None = mark everything seen)."""
    with _lock:
        rows = _read('tasks.json', [])
        hit = False
        for t in list(rows):
            if tid is not None and t['id'] != tid:
                continue
            hit = True
            if delete:
                rows.remove(t)
                continue
            if enabled is not None:
                t['enabled'] = bool(enabled)
            if seen:
                for h in t['hits']:
                    h['seen'] = True
        if hit:
            _write('tasks.json', rows)
        return hit


# ---------- run log ----------

def log_run(src, ai=None):
    """One line per press of 「AI 分析当前图表」. The verdict is computed here, not taken from the page."""
    with _lock:
        a = _clean(src)
        pos = src.get('pos') if src.get('pos') in quant.POS_MODES else 'auto'
        q = quant.result(a['ticker'], a['model'], src.get('asof') or None, a['side'], a['horizon'], a['tf'], pos)
        row = dict(a, id=secrets.token_hex(4), at=now_text(), asof=q['asof'], pos=pos, label=_label(a), state=q['signal']['state'], verdict=q['signal']['verdict_text'],
                   price=q['price'], score=q['score']['total'], score_label=q['score']['label'], lines=len(q['lines']), ai=ai if ai in ('template', 'claude', 'saved') else None)
        rows = [row] + _read('runs.json', [])
        _write('runs.json', rows[:MAX_RUNS])
        return row


def runs(limit=60, ticker=None):
    rows = _read('runs.json', [])
    if ticker:
        rows = [r for r in rows if r.get('ticker') == ticker]
    return dict(ok=True, runs=rows[:limit], total=len(rows))


def clear_runs():
    with _lock:
        _write('runs.json', [])
        return True
