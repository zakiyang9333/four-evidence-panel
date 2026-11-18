"""四要素面板后端。标准库 http.server，只监听 127.0.0.1。用 ./start.sh 启动。

GET  /                      单页前端（static/）
GET  /api/meta              标的列表、数据截止日、AI 是否可用、回测摘要、上次刷新结果
GET  /api/bars?ticker=      全历史 K 线 + 成交量均线 + MACD + 地量日 + 单一来源行
GET  /api/state?ticker=&asof=   规则引擎在 asof 收盘的状态（数据截到 asof 再算）
GET  /api/avwap?ticker=&anchor=&asof=   手动锚定 VWAP 画线用
GET  /api/ai/narrate?ticker=&asof=       视频式四问解说的模板版（不调用 API），外加上次 Claude 润色的版本（如果有）
GET  /api/ai/cached?ticker=&asof=        这只标的这一天上次的 Claude 解说（本机保存），以及输入是否变过
GET  /api/live?ticker=      盘中实时价和今天常规时段的未收盘 K 线（只画图，不参与判定）
GET  /api/ai/history?ticker=            按天保存的 AI 解读：哪些天分析过、哪个模型、那天的一句话
GET  /api/chat/list | /api/chat/get?id=   AI 对话的列表和某一段的全部消息（存在本机 data/chats/）
POST /api/chat/send         发一条消息，回答以 server-sent events 流式返回；整段对话的历史每次都带上（这就是记忆）
POST /api/chat/delete       删一段对话（只删本机的记录）。对话里只有问答：以前「一键解释」的卡片留在文件里，不再显示、不再发给 AI
GET  /api/notes?ticker=&asof=           K 线上的备注（事件日、新闻标题、联网搜到的、手写的）和各自的时效
POST /api/notes/manual | /delete | /search   手写一条、删一条、让 Claude 联网查某几天（会计费，查过的不再查）
POST /api/notes/translate   把存档里的英文新闻标题翻成中文并存下来（每条只翻一次）
GET  /api/learn?ticker=&model=&asof=    「一键解释」学习面板：大白话讲这一天屏幕上的每样东西（程序拼的，不调用 AI）
GET  /api/quant?ticker=&model=four|houshou|breakout|…&side=long|short&hz=20|60|120&tf=D|W&pos=auto|flat|long|short&asof=
     不给的参数用默认值（model 默认 houshou，side long，hz 20，tf D，pos auto，asof 最新一根）；给了但不认识的值一律 400，
     写明是哪个参数、可选什么，不会悄悄换成别的模型或周期。asof 是休市日时用它之前最近的一根，回复里 asof_note 写明。
                               「AI 量化」面板：结构线、评分表盘、所选规则模型的信号、历史触发（五个输入见 quant.py 开头）
GET  /api/quant/models         模型库：每个模型的来历、清单、参数（哪些是录屏里说的，哪些是估算）
GET  /api/quant/scan?hz=&tf=[&ticker=&model=&side=]   量化终端的表：每只标的 × 每个模型 × 多空现在的状态
GET  /api/quant/tasks          盯盘任务（顺带把新到的 K 线检查一遍）；POST 新建 / 暂停 / 删除 / 标为已读
GET  /api/quant/runs           分析记录；POST /api/quant/run 记一笔
GET  /terminal                 量化终端页面
POST /api/quant/narrate     这份结果的解说：模板（免费）或 Claude（body.claude 为真）
POST /api/quant/anchor      后手模型的手动成本锚点（存 data/houshou_anchor.json）
GET  /api/portfolio         「持仓」页的全部内容（只读 portfolio/ 里的文件）
GET  /api/portfolio/version 持仓文件有没有变（前端每 15 秒问一次，变了才重取）
GET  /api/portfolio/snapshot?name=   某一份 App 快照的原文
POST /api/refresh           运行 prep_data.py（只追加新日期）
POST /api/ai/analyze        Claude 解说（需要环境变量 ANTHROPIC_API_KEY）。盘面和仓位没变时直接返回保存的那一版，
                            不调用 API；带 force 才重新分析
"""
import datetime
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import ai_explain
import chat
import hashlib
import live
import learn
import mine
import narrate
import notes
import panel
import portfolio
import quant
import tasks

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, 'static')
DEFAULTS = dict(port=8777, ai_model='claude-opus-5-5', ai_effort='medium', ai_max_tokens=16000,
                ai_timeout_s=180, refresh_timeout_s=180, ai_refusal_fallback=True, portfolio_poll_s=15)


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(os.path.join(ROOT, 'config.json'), encoding='utf-8') as f:
            cfg.update({k: v for k, v in json.load(f).items() if not k.startswith('_')})
    except (OSError, ValueError):
        pass
    if os.environ.get('FE_PORT'):
        cfg['port'] = int(os.environ['FE_PORT'])
    if os.environ.get('FE_AI_MODEL'):
        cfg['ai_model'] = os.environ['FE_AI_MODEL']
    return cfg


CFG = load_config()
LIVE = live.LiveFeed(panel.TICKERS, enabled=bool(CFG.get('live_enabled', True)) and os.environ.get('FE_LIVE') != '0')
_refresh_lock = threading.Lock()
_ai_lock = threading.Lock()
_chat_lock = threading.Lock()
_last_refresh = None


def run_refresh():
    """Run prep_data.py in a child process and return its report."""
    global _last_refresh
    if not _refresh_lock.acquire(blocking=False):
        return 409, dict(ok=False, error='正在刷新，请等它结束。')
    try:
        t0 = time.time()
        try:
            p = subprocess.run([sys.executable, os.path.join(ROOT, 'prep_data.py'), '--json'], cwd=ROOT,
                               capture_output=True, text=True, timeout=int(CFG['refresh_timeout_s']))
        except subprocess.TimeoutExpired:
            return 504, dict(ok=False, error='刷新超时，数据没有改动。')
        try:
            rep = json.loads(p.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return 500, dict(ok=False, error='prep_data.py 运行失败：' + (p.stderr.strip().splitlines() or ['没有输出'])[-1][:300])
        panel.clear_cache()
        try:        # 顺带更新事件日（财报、除息、拆股）和当天的新闻标题存档；取不到不算刷新失败
            note_rep = notes.refresh_all()
        except Exception as e:      # noqa: BLE001
            note_rep = [dict(errors=['备注没更新：' + type(e).__name__])]
        out = dict(ok=True, at=time.strftime('%Y-%m-%d %H:%M:%S'), seconds=round(time.time() - t0, 1), notes_refresh=note_rep, tickers={
            t: dict(appended=r.get('appended', []), errors=r.get('errors', []), notes=r.get('notes', []),
                    last=r.get('last'), last_src=r.get('last_src'), sources=r.get('sources', {})) for t, r in rep.items()})
        out['has_error'] = any(r['errors'] for r in out['tickers'].values())
        _last_refresh = out
        try:        # 有新 K 线了：把盯盘任务和持仓里的线检查一遍（打开了「提醒」才发通知，发到手机的不带持仓数字）
            out['tasks_unseen'] = tasks.listing()['unseen']
            tasks.line_alerts()
        except Exception:       # noqa: BLE001
            pass
        return 200, out
    finally:
        _refresh_lock.release()


def meta():
    ok, why = ai_explain.status(CFG)
    return dict(tickers=panel.summary(), timeframe='日线', realtime=False,
                ai=dict(enabled=ok, reason=why, model=CFG['ai_model'], translate_auto=bool(CFG.get('ai_translate_auto', True))),
                backtest=panel.backtest_summary(), last_refresh=_last_refresh, last_refresh_file=panel.last_refresh(),
                portfolio_poll_s=max(5, min(60, int(CFG.get('portfolio_poll_s', 15)))),
                quant_models=[dict(key=m['key'], name=m['name'], sides=list(m['sides']), tfs=list(m['tfs']), group=m.get('group', ''), kind=m.get('kind', 'trade'), default_side=m.get('default_side', 'long'), default_hz=m.get('default_hz', 20)) for m in quant.MODELS],
                engine=dict(version='v1.0', params=panel.P, fixed={k: panel.F[k] for k in ('hi_win', 'div_gap', 'tgt_win', 'max_hold')}))


def ai_model(m, default='four'):
    """The model key to use: missing or empty = the default; a key the registry doesn't know = BadParam (400), never another model."""
    if not quant.given(m):
        return default
    if m not in quant.MODEL:
        raise quant.BadParam('model', m, quant.MODEL)
    return m


def prof(src, default_model='four'):
    """The five inputs of one analysis (model, side, horizon, bar size, position mode) from a query string or a JSON body.
    Missing ones take their defaults; values that are sent but unknown raise quant.BadParam, which the handler turns into a 400."""
    return quant.norm(ai_model(src.get('model'), default_model), src.get('side'), src.get('hz', src.get('horizon')), src.get('tf'), src.get('pos', src.get('posmode')))


def bad_request(e):
    """The body of a 400: what was wrong, and for an unknown value which parameter it was and what it can be."""
    out = dict(ok=False, error=str(e) or '请求不对。')
    if isinstance(e, quant.BadParam):
        out.update(param=e.name, value=e.value, allowed=e.allowed)
    return out


def asof_of(src, t=None):
    """The asof date of a request. Missing or empty = the latest bar. Otherwise it must be a real date written YYYY-MM-DD, and not
    before the ticker's second bar (the engine needs two); anything else is BadParam (400), not silently the latest or the first bar.
    A weekend or holiday is fine: the bar before it is used, and the reply's asof says which."""
    a = src.get('asof')
    if not quant.given(a):
        return None
    a = str(a).strip()
    try:
        ok = len(a) == 10 and datetime.date.fromisoformat(a).isoformat() == a
    except ValueError:
        ok = False
    if not ok:
        raise quant.BadParam('asof', a, why='要写成 YYYY-MM-DD 的日期，比如 2026-11-13；不给就是最新一根。')
    if t in panel.TICKERS:
        d = panel.load(t)['B']['d']
        if len(d) > 1 and a < d[1]:
            raise quant.BadParam('asof', a, why=f'早于 {t} 最早能看的一天（{d[1]}，引擎至少要两根 K 线）。')
    return a


def ai_inputs(t, asof, model='four', side='long', horizon=20, tf='D', posmode='auto'):
    """Everything one AI reading is built from, plus a fingerprint of it. Returns a dict."""
    a = quant.norm(ai_model(model), side, horizon, tf, posmode)
    model, side, horizon, tf, posmode = a['model'], a['side'], a['horizon'], a['tf'], a['posmode']
    asof = asof_of(dict(asof=asof), t)
    q = quant.result(t, model, asof or None, side, horizon, tf, posmode)
    state = panel.state_at(t, q['asof'])        # 四证引擎在这一天的状态：周 K 时就是那根周 K 最后一个交易日的状态
    B = quant.bars(t, tf)
    i = q['index']
    k = max(0, i - 59)
    bars = [[B['d'][j], panel.fnum(B['o'][j], 4), panel.fnum(B['h'][j], 4), panel.fnum(B['l'][j], 4),
             panel.fnum(B['c'][j], 4), int(B['v'][j])] for j in range(k, i + 1)]
    # 仓位是现在的仓位，只在看最新一根时附上；回放历史某天时不附。只发这只标的相关的，不发整份账户。
    # 「持仓」选的是假设（未持仓 / 多单 / 空单）时，账户里的真实仓位不发，只把这个假设告诉它。
    pos = portfolio.relevant_positions(t) if q['is_latest'] and posmode == 'auto' else None
    bt = panel.backtest_summary()
    facts = narrate.build_facts(t, state['asof'])
    qf = quant.facts_for_ai(q)
    # 四证·做多·20 日·日 K：指纹和以前一样（表盘和结构线都是从同一批 K 线算出来的，盘面没变它们就没变），保存过的解读继续有效。
    # 后手·做多·20 日·日 K：和以前一样只加清单结果，手动改了成本锚点就算变了。
    # 其余组合：再加上方向、周期、级别、假设的持仓和计划价位，各记各的。
    var = quant.variant(model, side, horizon, tf)
    four = model == 'four' and not q['signal'].get('unsupported')
    if var == '' and posmode == 'auto':
        extra = None
    elif var == 'houshou' and posmode == 'auto':
        extra = dict(model='houshou', signal=qf['rule_signal'])
    else:
        extra = dict(model=model, side=side, horizon=horizon, tf=tf, pos=posmode, signal=qf['rule_signal'], plan=qf['plan'])
    tmpl = narrate.template(facts) if four else quant.template(q)
    ctx = notes.for_ai(t, state['asof'])        # K 线上的备注。不进指纹：盘面没变，保存的解读仍然有效，只是会提示“之后新增了几条备注”
    return dict(facts=facts, bars=bars, bt=bt, pos=pos, q=q, qf=qf, tmpl=tmpl, model=model, variant=var, four=four, prof=a,
                notes=ctx if ctx['notes'] or ctx['next_earnings'] else None,
                positive=facts['all4'] if four else q['signal']['state'] == 'ready',
                allowed=narrate.allowed_numbers(facts, bars, bt, pos, qf, tmpl, ctx),
                fp=ai_explain.fingerprint(facts, bars, bt, CFG, pos, extra))


def narration_result(t, facts, bt, narr, source, **extra):
    """One response shape for both the template and the Claude version. The card never goes through Claude."""
    return dict(ok=True, ticker=t, asof=facts['asof'], source=source, narration=narr, card=narrate.card(facts, bt),
                score=facts['score'], armed=facts['armed'], **extra)


def ai_narrate(t, asof, model='four', side='long', horizon=20, tf='D', posmode='auto'):
    """Free, instant template narration, plus the last saved Claude version for this day and this combination if there is one."""
    x = ai_inputs(t, asof, model, side, horizon, tf, posmode)
    facts, bt, pos = x['facts'], x['bt'], x['pos']
    res = narration_result(t, facts, bt, x['tmpl'], 'template', rule_model=x['model'], variant=x['variant'], profile=x['prof'])
    rows = ai_cache_read(t, x['q']['asof'], x['variant'])
    if rows:
        res['polished'] = saved_view(rows[0], x)
    else:       # 这个组合今天没分析过，但别的组合分析过：把最近的那一份也给出去，切换模型或方向时不至于一片空白
        best = None
        for var in ai_variants(t, x['q']['asof']):
            orows = ai_cache_read(t, x['q']['asof'], var)
            if orows and (best is None or (orows[0].get('created_at') or '') > (best[1][0].get('created_at') or '')):
                best = (var, orows)
        if best:
            o = variant_profile(best[0])
            res['other'] = dict(saved_view(best[1][0], ai_inputs(t, asof, o['model'], o['side'], o['horizon'], o['tf'])), from_other=True, rule_model=o['model'],
                                variant=best[0], profile=o, profile_label=profile_label(o))
    ok, why = ai_explain.status(CFG)
    res['polish'] = dict(enabled=ok, reason=why, model=CFG['ai_model'], positions=len(pos['positions']) if pos else 0)
    return res


def saved_view(row, x):
    """A saved Claude reading as it is shown again: marked as saved, told whether the market or the positions changed since,
    and its numbers checked again by today's rules. No API call."""
    old = dict(row, same_input=row.get('fingerprint') == x['fp'], cached=True,
               notes_since=notes.count_since(row.get('ticker'), row.get('asof'), row.get('created_at')))     # 这份解读生成之后，又新增了几条备注
    bad = narrate.bad_numbers(old['narration'], x['allowed'])
    old.pop('unverified', None); old.pop('notice', None); old.pop('code', None)
    if bad:
        old.update(unverified=bad[:20], notice=f'有 {len(bad)} 个数字在引擎输出和 K 线数据里找不到（已标黄）：可能是它自己算的，也可能写错了，以图和引擎为准。')
    return old


# ---- 本机保存的 AI 解读（含仓位相关内容，只存在 cache/ai/，不进 git）----
AI_CACHE = os.environ.get('FE_CACHE_DIR') or os.path.join(ROOT, 'cache', 'ai')
AI_KEEP = 5


# 组合名 ↔ 模型、方向、周期、级别。模型名从注册表里取：以前写死成 houshou|breakout，第二版新加的 10 个模型对不上，
# 「AI 分析」按钮在这些模型上取解说时被当成“没有这个标的”（404）
VARIANT_RE = re.compile(r'(?:(' + '|'.join(sorted((re.escape(k) for k in quant.MODEL if k != 'four'), key=len, reverse=True)) + r'))?(?:_?(short))?(?:_?h(60|120))?(?:_?(W))?')


def variant_profile(var):
    """'' / 'houshou' / 'breakout_short_h60_W' ... back into model, side, horizon and bar size. None if it is not one of ours."""
    m = VARIANT_RE.fullmatch(var or '')
    if not m:
        return None
    o = dict(model=m.group(1) or 'four', side='short' if m.group(2) else 'long', horizon=int(m.group(3) or 20), tf='W' if m.group(4) else 'D')
    return o if quant.variant(o['model'], o['side'], o['horizon'], o['tf']) == (var or '') else None


def profile_label(o):
    return ' · '.join([quant.MODEL[o['model']]['name'], quant.SIDE_NAME[o['side']], quant.horizon_label(o['horizon'], o['tf'])] + (['周K'] if o['tf'] == 'W' else []))


def _ai_cache_path(t, asof, variant=''):
    """One file per day and combination. variant: '' (四证·做多·20 日·日 K), 'houshou', 'breakout_short', ... (quant.variant);
    the old argument values 'four' and 'houshou' still mean what they meant."""
    variant = '' if variant in (None, 'four') else variant
    if t not in panel.TICKERS or not (len(asof) == 10 and asof[4] == '-' and asof[7] == '-' and asof.replace('-', '').isdigit()) or variant_profile(variant) is None:
        raise KeyError(t)
    return os.path.join(AI_CACHE, f'{t}_{asof}' + ('_' + variant if variant else '') + '.json')      # 每个组合各记各的


def ai_cache_read(t, asof, variant=''):
    try:
        with open(_ai_cache_path(t, asof, variant), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def ai_cache_add(t, asof, entry, variant=''):
    os.makedirs(AI_CACHE, exist_ok=True)
    rows = ([entry] + ai_cache_read(t, asof, variant))[:AI_KEEP]
    tmp = _ai_cache_path(t, asof, variant) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _ai_cache_path(t, asof, variant))


def ai_variants(t, asof=None):
    """Saved readings of one ticker: [(date, variant)] newest first, or just the variants of one day."""
    try:
        names = os.listdir(AI_CACHE)
    except OSError:
        names = []
    out = []
    for n in names:
        m = re.fullmatch(re.escape(t) + r'_(\d{4}-\d{2}-\d{2})(?:_([A-Za-z0-9_]+))?\.json', n)
        if m and variant_profile(m.group(2) or '') is not None and (asof is None or m.group(1) == asof):
            out.append((m.group(1), m.group(2) or ''))
    return [v for _, v in out] if asof is not None else out


MODEL_NAMES = dict({m['key']: m['name'] for m in quant.MODELS}, four='四证·抄底', houshou='后手·成本线回踩', breakout='破位反抽')     # 分析记录里的名字：老三个照旧，其余用注册表里的


def ai_history(t, limit=120):
    """按天保存的 AI 解读：这只标的哪些天分析过、用的哪个模型和方向、那天的一句话。只读本机 cache/ai/。"""
    if t not in panel.TICKERS:
        raise KeyError(t)
    out = []
    for date, var in ai_variants(t):
        rows = ai_cache_read(t, date, var)
        if rows:
            r, o = rows[0], variant_profile(var)
            out.append(dict(date=date, model=o['model'], side=o['side'], horizon=o['horizon'], tf=o['tf'], variant=var,
                            model_name=MODEL_NAMES[o['model']] + ('' if o['side'] == 'long' else ' · 做空') + ('' if o['horizon'] == 20 else f' · {o["horizon"]} 根') + ('' if o['tf'] == 'D' else ' · 周K'),
                            created_at=r.get('created_at'), versions=len(rows),
                            hook=(r.get('narration') or {}).get('hook'), final=(r.get('narration') or {}).get('final'),
                            _mt=os.path.getmtime(_ai_cache_path(t, date, var))))
    out.sort(key=lambda r: (r['date'], r['created_at'] or '', r['_mt']), reverse=True)      # 同一秒存的两份：按文件写入的先后
    for r in out:
        r.pop('_mt')
    return dict(ok=True, ticker=t, days=out[:limit])


def chat_context(t, asof, src):
    """The chart data a chat message carries, and a key that changes when any of it does. src = the page's five inputs (or just a model key)."""
    a = prof(src if isinstance(src, dict) else dict(model=src))
    x = ai_inputs(t, asof, a['model'], a['side'], a['horizon'], a['tf'], a['posmode'])
    f = x['facts']
    rows = ai_cache_read(t, x['q']['asof'], x['variant'])
    for var in ([] if rows else ai_variants(t, x['q']['asof'])):
        rows = rows or ai_cache_read(t, x['q']['asof'], var)
    reading = None
    if rows:
        n = rows[0].get('narration') or {}
        reading = dict(created_at=rows[0].get('created_at'), headline=n.get('hook'), story=n.get('story'), conclusion=n.get('final'),
                       steps=[dict(title=s.get('q'), says=s.get('say'), tag=s.get('sticker')) for s in n.get('steps') or []], watch=n.get('watch'))
    body = dict(ticker=t, asof=x['q']['asof'], is_latest=bool(x['q']['is_latest']), selected_model=x['q']['model_name'], engine=f,
                bars=dict(columns=['date', 'open', 'high', 'low', 'close', 'volume'], rows=x['bars']), backtest=x['bt'], quant=x['qf'],
                notes=x['notes'], saved_ai_reading=reading)
    if x['pos']:
        body.update(x['pos'])           # 只有这只标的相关的仓位，和 AI 解读发的是同一份
    if x['q']['is_latest'] and a['posmode'] == 'auto':
        mx = portfolio.chat_extras(t)   # 他自己的线、估值参考、这只的挂单和点名它的检查项（只给对话，不进 AI 解读的指纹）
        if mx:
            body['mine'] = mx
    text = json.dumps(body, ensure_ascii=False, separators=(',', ':'), default=str)
    key = hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
    q = x['q']
    return text, key, f"{t} {q['asof']} · {q['model_name']}" + ('' if q['side'] == 'long' else ' · 做空') + ('' if q['tf'] == 'D' else ' · 周K')


def model_library():
    """The 模型 page: where each model comes from, what it checks, and every parameter with its source (said in the recording, or estimated)."""
    import breakout as bo
    import houshou as hs
    Pv, Fx = panel.P, panel.F
    four = [dict(name='地量 = 近多少根里成交量最小', v=Pv['n_vol'], src='video'), dict(name='扇子用哪一条线', v=Pv['fan'], src='video'),
            dict(name='止损垫在最低点下面', v=f"{Pv['stop'] * 100:g}%", src='video'), dict(name='先跌够多少才开始找底（“跌两成”）', v=f"{Pv['dd'] * 100:g}%", src='est'),
            dict(name='放量大阳：成交量至少是前 5 天均量的几倍', v=Pv['vol_mult'], src='est'), dict(name='参考高点：近多少根的最高价', v=Fx['hi_win'], src='est'),
            dict(name='底背离：MACD 柱的低点至少早于价格低点多少根', v=Fx['div_gap'], src='est'), dict(name='第一目标：低点前多少根的最高价', v=Fx['tgt_win'], src='est'),
            dict(name='最长持有多少根', v=Fx['max_hold'], src='est'), dict(name='第二目标：收回这一轮跌幅的多少（面板加的参考位）', v=quant.FOUR_T2, src='est')]
    hv = hs.VIDEO
    hou = [dict(name='离成本线超过多少就不追', v=f"{hv['far'] * 100:g}%", src='video'), dict(name='两段跌幅相差不到多少算等长', v=f"{hv['abcd_tol'] * 100:g}%", src='video'),
           dict(name='缩量：量缩到下跌段的多少以下', v=f"{hv['dry'] * 100:g}%", src='video'), dict(name='止损放在 D 点外侧', v=f"{hv['stop'] * 100:g}%", src='video')] + \
          [dict(name=hs.EST_NOTE.get(k, k), v=v, src='est') for k, v in hs.EST.items()]
    brk = [dict(name=bo.VIDEO_NOTE.get(k, k), v=v, src='video') for k, v in bo.VIDEO.items()] + [dict(name=bo.EST_NOTE.get(k, k), v=v, src='est') for k, v in bo.EST.items()]
    notes_ = dict(four=['回测结论：' + str((panel.backtest_summary() or {}).get('verdict', '证据不足')) + '。所以这里只做观察。', '规则在 engine.py 里，这个文件不许改；面板只负责把它的结果摆出来。'],
                  houshou=['没有回测过。照录屏「后手战法」的五条总结重写，不是原作者的代码。'] + quant.houshou_sample_notes() +
                          ['做空一侧是把同一套规则上下翻过来（价格取负后跑同一段代码），录屏里没有讲过。', '第二目标是从录屏那一格的数字反推的，录屏没有明说算法。'],
                  breakout=['录屏「卧底战法」那一段给了三条要点（破线看收盘、破线量过前 5 根均量 1.5 倍、反抽量缩到破线日一半以内），0.2 照这三条改过。这是重写的，不是原作者的代码。',
                            '没有回测过。查过的开源实现里，有一位作者自己报告这类形态样本外是亏的（每笔 −0.27R，763 笔）。', '破位和反抽的容差按波动率（ATR）放缩，倍数取几份开源实现的中间值。'])
    refs = dict(breakout=['TradingSignalBot/tradingview-strategies（MIT）', 'hanreywt/Screener_Alert', 'ascendro-ca/break-and-retest', 'neurotrader888/TechnicalAnalysisAutomation（MIT）'],
                houshou=['karthikcyadav98/fib-extension-paper（第二目标从回踩点量）', 's-kust/anchored_vwaps（锚定 VWAP 的算法）'], four=[])
    def generic(m):          # 建在 qmodel.py 上的模型：参数、说明、参考都写在各自的模型文件里
        mod = m['mod']
        ps = [dict(name=getattr(mod, 'VIDEO_NOTE', {}).get(k, k), v=v, src='video') for k, v in getattr(mod, 'VIDEO', {}).items()] + \
             [dict(name=getattr(mod, 'EST_NOTE', {}).get(k, k), v=v, src='est') for k, v in getattr(mod, 'EST', {}).items()]
        note = list(getattr(mod, 'NOTES', ())) or ['没有回测过。这一版是照录屏讲的规则重写的，不是原作者的代码；录屏里没给的数都标了估算。']
        return ps, note, list(getattr(mod, 'REFS', ()))

    def pack(m):
        ps, note, ref = generic(m) if m.get('mod') else (dict(four=four, houshou=hou, breakout=brk)[m['key']], notes_[m['key']], refs[m['key']])
        return dict({k: m[k] for k in ('key', 'name', 'version', 'tested', 'origin', 'what', 'checks')}, sides=list(m['sides']), tfs=list(m['tfs']), group=m.get('group', ''), kind=m.get('kind', 'trade'),
                    params=ps, notes=note, refs=ref)

    return dict(ok=True, models=[pack(m) for m in quant.MODELS],
                side_names=quant.SIDE_NAME, horizons=[dict(n=n, label=quant.horizon_label(n)) for n in quant.HORIZONS], adjust=quant.ADJUST)


def quant_scan(q):
    """量化终端的表。给了 ticker / model / side 就只算那一格，否则算全部（3 只 × 3 个模型 × 多空）。"""
    a = quant.norm('four', q.get('side'), q.get('hz', q.get('horizon')), q.get('tf'), 'flat')      # 不认识的 side / hz / tf：400
    ts = [q['ticker']] if q.get('ticker') else list(panel.TICKERS)
    ms = [ai_model(q['model'])] if quant.given(q.get('model')) else [m['key'] for m in quant.MODELS]
    sides = [a['side']] if quant.given(q.get('side')) else ['long', 'short']
    if any(t not in panel.TICKERS for t in ts):
        raise KeyError(ts[0])
    cells = [quant.scan_cell(t, m, s, a['horizon'], a['tf']) for t in ts for m in ms for s in sides]
    return dict(ok=True, horizon=a['horizon'], horizon_label=quant.horizon_label(a['horizon'], a['tf']), tf=a['tf'], cells=cells,
                models=[dict(key=m['key'], name=m['name'], tested=m['tested'], group=m.get('group', ''), kind=m.get('kind', 'trade')) for m in quant.MODELS], tickers=list(panel.TICKERS), banner=quant.BANNER)


def ai_cached(t, asof):
    """Last saved Claude reading for this ticker and day, and whether today's input still matches it."""
    state = panel.state_at(t, asof or None)
    rows = ai_cache_read(t, state['asof'])
    if not rows:
        return dict(ok=True, found=False, asof=state['asof'], ticker=t)
    fp = ai_inputs(t, state['asof'])['fp']
    return dict(ok=True, found=True, ticker=t, asof=state['asof'], entry=rows[0], same_input=rows[0].get('fingerprint') == fp,
                history=[{k: r.get(k) for k in ('created_at', 'model', 'positions_sent')} for r in rows])


def ai_analyze(body):
    """“让 Claude 润色”。Whatever goes wrong, the answer is still a four-question narration: the template, with a notice."""
    t = body.get('ticker')
    a = prof(body)
    x = ai_inputs(t, body.get('asof'), a['model'], a['side'], a['horizon'], a['tf'], a['posmode'])
    facts, bars, bt, pos, fp, tmpl, model, var = x['facts'], x['bars'], x['bt'], x['pos'], x['fp'], x['tmpl'], x['model'], x['variant']
    asof = x['q']['asof']
    if not body.get('force') and not body.get('test_fake_number'):
        # 记忆：盘面和仓位都没变，就把保存的那一版原样给回去，不再调用 Claude。要重新分析得明确带 force。
        rows = ai_cache_read(t, asof, var)
        if rows and rows[0].get('fingerprint') == fp:
            return 200, dict(saved_view(rows[0], x), reused=True)
    if not _ai_lock.acquire(blocking=False):
        return 409, dict(ok=False, error='上一次分析还没结束。')
    try:
        got = ai_explain.polish(facts, bars, bt, CFG, pos, x['qf'], x['notes'])
        if not got.get('ok'):
            return 200, narration_result(t, facts, bt, tmpl, 'template', notice='没能用上 Claude，已改用模板：' + got['error'], code=got.get('code'), rule_model=model)
        allowed = x['allowed']
        # Claude 只说在图上标哪一天、哪个位置；价位由这里从 K 线数据里取。直接给的价位必须是输入里有的数。
        narr, why = narrate.normalize(got['raw'], facts, tmpl, narrate.chart_data(t, asof, quant.bars(t, a['tf'])), {round(n, 2) for n in allowed},
                                      positive=x['positive'], link_evidence=x['four'])
        if narr is None:
            return 200, narration_result(t, facts, bt, tmpl, 'template', notice=f'AI 输出的结构不对（{why}），已改用模板', code='shape', rule_model=model)
        if body.get('test_fake_number'):                # 测试开关：往 Claude 的输出里塞一个假数字，看核对能不能拦住
            narr['steps'][0]['say'] += '，目标看到 987.65'
        bad = narrate.bad_numbers(narr, allowed)
        if bad and CFG.get('ai_strict_numbers', False):     # 严格模式：有一个对不上就整段不用
            return 200, narration_result(t, facts, bt, tmpl, 'template', notice='AI 输出含无法核对的数字，已改用模板', code='numbers', unverified=bad[:8], rule_model=model)
        res = narration_result(t, facts, bt, narr, 'claude', model=got['model'], rule_model=model, variant=var, profile=a, positions_sent=len(pos['positions']) if pos else 0,
                               created_at=time.strftime('%Y-%m-%d %H:%M:%S'), fingerprint=fp,
                               tokens_in=got.get('tokens_in'), tokens_out=got.get('tokens_out'),
                               notes_used=len(x['notes']['notes']) if x['notes'] else 0)
        if bad:     # 自由分析时 Claude 会自己算数：对不上的不丢弃，标出来让人自己判断
            res.update(unverified=bad[:20], code='numbers',
                       notice=f'有 {len(bad)} 个数字在引擎输出和 K 线数据里找不到（已标黄）：可能是它自己算的，也可能写错了，以图和引擎为准。')
        try:
            ai_cache_add(t, asof, res, var)
        except OSError:
            res['cache_error'] = True
        return 200, res
    finally:
        _ai_lock.release()


def notes_search(body):
    """Claude 联网查“那几天发生过什么”。花钱，所以查过的日子记下来，不带 force 不再查第二遍。"""
    t = body.get('ticker', '')
    p = notes.payload(t, body.get('asof') or None)
    done = set(notes.load(t)['searched'])
    want = body.get('dates')
    if want:
        days = set(panel.load(t)['B']['d'])
        rows = [dict(date=d, why=next((r['why'] for r in p['notable'] if r['date'] == d), '')) for d in want if d in days and d <= p['asof']][:6]
    else:
        rows = [r for r in p['notable']]
    if not body.get('force'):
        rows = [r for r in rows if r['date'] not in done]
    if not rows:
        return 200, dict(ok=True, searched=[], added=0, dropped=0, skipped=True, message='这些天都查过了，没有再查（也没有再计费）。', notes=notes.payload(t, body.get('asof') or None))
    if not _ai_lock.acquire(blocking=False):
        return 409, dict(ok=False, error='上一次 AI 请求还没结束。')
    try:
        got = ai_explain.search_days(notes.NAMES.get(t, t), t, rows, CFG)
        if not got.get('ok'):
            return 200, dict(ok=False, error=got['error'], code=got.get('code'))
        dates = [r['date'] for r in rows]
        try:        # 原始返回留一份在本机（cache/ 不进 git）：核对规则丢了什么、为什么丢，事后查得到
            os.makedirs(os.path.join(AI_CACHE, 'search'), exist_ok=True)
            with open(os.path.join(AI_CACHE, 'search', f'{t}_{time.strftime("%Y%m%d_%H%M%S")}.json'), 'w', encoding='utf-8') as f:
                json.dump(dict(ticker=t, dates=dates, message=got['message']), f, ensure_ascii=False, indent=1)
        except OSError:
            pass
        kept, dropped, searches = notes.verify_search(got['message'], dates)
        added = notes.store_search(t, dates, kept, dict(model=got['model'], tokens_in=got['tokens_in'], tokens_out=got['tokens_out'], searches=searches))
        return 200, dict(ok=True, searched=dates, added=added, kept=len(kept), dropped=dropped, searches=searches, model=got['model'],
                         tokens_in=got['tokens_in'], tokens_out=got['tokens_out'], notes=notes.payload(t, body.get('asof') or None))
    finally:
        _ai_lock.release()


def notes_translate(body):
    """把这只标的还没有中文的新闻标题翻一遍，存下来。每条只翻一次；没有要翻的就什么都不调用。"""
    t = body.get('ticker', '')
    rows = notes.pending_translation(t)
    if not rows:
        return 200, dict(ok=True, translated=0, skipped=True, notes=notes.payload(t, body.get('asof') or None))
    if not _ai_lock.acquire(blocking=False):
        return 409, dict(ok=False, error='上一次 AI 请求还没结束。')
    try:
        got = ai_explain.translate_titles([r['title'] for r in rows], CFG)
        if not got.get('ok'):
            return 200, dict(ok=False, error=got['error'], code=got.get('code'))
        done = notes.store_translation(t, [r['id'] for r in rows], got['zh'], dict(model=got['model']))
        return 200, dict(ok=True, translated=done, asked=len(rows), model=got['model'], tokens_in=got['tokens_in'], tokens_out=got['tokens_out'],
                         notes=notes.payload(t, body.get('asof') or None))
    finally:
        _ai_lock.release()


class Handler(BaseHTTPRequestHandler):
    server_version = 'FourEvidence/1.0'
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):      # request line only; never headers or bodies
        sys.stderr.write('%s %s\n' % (time.strftime('%H:%M:%S'), fmt % args))

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def _local(self):
        """Only this machine's own page may call the API (blocks other web pages from poking localhost)."""
        host = (self.headers.get('Host') or '').split(':')[0]
        if host not in ('localhost', '127.0.0.1'):
            return False
        origin = self.headers.get('Origin')
        if origin:
            return urlparse(origin).hostname in ('localhost', '127.0.0.1')
        return True

    def _sse(self, event, data):
        self.wfile.write(('event: %s\ndata: %s\n\n' % (event, json.dumps(data, ensure_ascii=False, separators=(',', ':')))).encode('utf-8'))
        self.wfile.flush()

    def _chat_send(self, body):
        """One chat turn, streamed to the page as server-sent events: start, delta..., then done or error.
        The user's message is saved before the call and the reply after it, so nothing is lost if the page goes away mid-answer."""
        t, text = body.get('ticker', ''), str(body.get('text') or '').strip()
        if t not in panel.TICKERS:
            raise KeyError(t)
        if not text:
            raise ValueError('问题是空的')
        if len(text) > chat.MAX_TEXT:
            raise ValueError(f'这条太长了（最多 {chat.MAX_TEXT} 个字），分几条问')
        ok, why = ai_explain.status(CFG)
        if not ok:
            return self._send(200, dict(ok=False, error=why, code='disabled'))
        if not _chat_lock.acquire(blocking=False):
            return self._send(409, dict(ok=False, error='上一条还没答完。'))
        try:
            conv = chat.load(body.get('id') or '') or chat.new(t)
            ctx, key, chip = chat_context(t, body.get('asof') or None, body)
            # 联网：他勾了就查；没勾、但问的是原因或新闻（“为什么跌”），自动查，每天有上限（按次计费）
            web, auto_web = bool(body.get('web')), False
            if not web and mine.wants_news(text) and mine.auto_web_take(int(CFG.get('ai_chat_auto_web_daily', 3))):
                web = auto_web = True
            attach = key != conv.get('ctx_key')        # 图表数据变了（换了标的、日期、模型，或多了备注）才再带一份
            if not any(m['role'] == 'user' for m in conv['messages']):        # 第一句提问就是这段对话的标题
                conv['title'] = chat.title_from(text)
            conv['messages'].append(dict(role='user', at=chat.now_text(), text=text, context=ctx if attach else None, chip=chip if attach else None))
            conv.update(ctx_key=key, ticker=t)
            chat.save(conv)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True
            acc, info, err = [], None, None
            try:
                self._sse('start', dict(id=conv['id'], title=conv['title'], chip=chip if attach else None))
                for kind, val in ai_explain.chat_stream(chat.system(), chat.api_messages(conv), CFG, web=web):
                    if kind == 'delta':
                        acc.append(val)
                        self._sse('delta', dict(text=val))
                    elif kind == 'done':
                        info = val
                    else:
                        err = val
            except (BrokenPipeError, ConnectionError):      # 页面那头点了“停止”或者关掉了：把已经说出来的部分存下
                err = '已停止'
            reply = ''.join(acc)
            if reply.strip():
                meta = dict(info or {}, interrupted=info is None, auto_web=auto_web)
                conv['messages'].append(dict(role='assistant', at=chat.now_text(), text=reply, meta=meta))
                u = conv.setdefault('usage', dict(tokens_in=0, tokens_out=0, cache_read=0, calls=0))
                if info:
                    u['tokens_in'] += info['tokens_in']; u['tokens_out'] += info['tokens_out']; u['cache_read'] += info.get('cache_read', 0); u['calls'] += 1
                    u['cache_write'] = u.get('cache_write', 0) + info.get('cache_write', 0)
            chat.save(conv)
            try:
                if err and err != '已停止':
                    self._sse('error', dict(error=err, conv=chat.public(conv)))
                elif not err:
                    self._sse('done', dict(conv=chat.public(conv)))
            except (BrokenPipeError, ConnectionError):
                pass
        finally:
            _chat_lock.release()

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path.startswith('/api/'):
                if not self._local():
                    return self._send(403, dict(ok=False, error='只允许本机访问。'))
                if u.path == '/api/meta':
                    return self._send(200, meta())
                if u.path == '/api/bars':
                    return self._send(200, panel.bars_payload(q.get('ticker', ''), q.get('tf', 'D')))
                if u.path == '/api/live':
                    t = q.get('ticker', '')
                    return self._send(200, LIVE.snapshot(t, panel.load(t)['B']['d'][-1]))
                if u.path == '/api/data/version':
                    return self._send(200, {t: panel.freshness(t) for t in panel.TICKERS})
                if u.path == '/api/ai/narrate':
                    a = prof(q)
                    return self._send(200, ai_narrate(q.get('ticker', ''), asof_of(q, q.get('ticker')), a['model'], a['side'], a['horizon'], a['tf'], a['posmode']))
                if u.path == '/api/notes':        # K 线上的备注：事件日、新闻标题、联网搜到的、手写的，以及各自的时效
                    return self._send(200, notes.payload(q.get('ticker', ''), asof_of(q, q.get('ticker'))))
                if u.path == '/api/learn':        # 「一键解释」：把这一天的结果讲成大白话，不调用 AI
                    a = prof(q)
                    return self._send(200, learn.build(q.get('ticker', ''), a['model'], asof_of(q, q.get('ticker')), a['side'], a['horizon'], a['tf']))
                if u.path == '/api/quant':
                    t, a = q.get('ticker', ''), prof(q, 'houshou')
                    asof = asof_of(q, t)
                    r = quant.result(t, a['model'], asof, a['side'], a['horizon'], a['tf'], a['posmode'])
                    if asof and r['asof'] != asof:          # 休市日或周 K 中间的日子：用的是之前最近的一根，写明
                        r.update(asof_requested=asof, asof_note=f'{asof} 没有{"" if a["tf"] == "D" else "周 "}K 线（休市、在最新一根之后，或在一周中间），用的是它之前最近的一根：{r["asof"]}。')
                    return self._send(200, r)
                if u.path == '/api/quant/models':
                    return self._send(200, model_library())
                if u.path == '/api/quant/scan':
                    return self._send(200, quant_scan(q))
                if u.path == '/api/quant/tasks':
                    return self._send(200, tasks.listing(force=q.get('force') == '1'))
                if u.path == '/api/quant/runs':
                    return self._send(200, tasks.runs(ticker=q.get('ticker') or None))
                if u.path == '/api/ai/history':
                    return self._send(200, ai_history(q.get('ticker', '')))
                if u.path == '/api/chat/list':
                    return self._send(200, dict(ok=True, chats=chat.listing()))
                if u.path == '/api/chat/get':
                    conv = chat.load(q.get('id', ''))
                    return self._send(200, dict(ok=True, conv=chat.public(conv)) if conv else dict(ok=False, error='没有这段对话。'))
                if u.path == '/api/ai/cached':
                    return self._send(200, ai_cached(q.get('ticker', ''), asof_of(q, q.get('ticker'))))
                if u.path == '/api/state':
                    st = panel.state_at(q.get('ticker', ''), asof_of(q, q.get('ticker')))
                    st['card'] = narrate.card_from_state(st, panel.backtest_summary())     # 规则模型卡片：只来自引擎
                    saved = ai_variants(st['ticker'], st['asof'])       # 这一天保存过 Claude 解说的组合：切换模型或方向不清空
                    st['ai_saved'] = dict(four='' in saved, houshou='houshou' in saved, any=bool(saved), variants=saved)
                    return self._send(200, st)
                if u.path == '/api/portfolio':
                    return self._send(200, portfolio.payload())
                if u.path == '/api/rules':                 # 我的规则（他自己写的，AI 对话照着推演）
                    text, saved = mine.rules()
                    return self._send(200, dict(ok=True, text=text, saved=saved))
                if u.path == '/api/notify':                # 提醒的设定，和今天自动联网用了几次
                    return self._send(200, dict(ok=True, settings=mine.notify_settings(), auto_web_used=mine.auto_web_used(),
                                                auto_web_daily=int(CFG.get('ai_chat_auto_web_daily', 3))))
                if u.path == '/api/portfolio/version':
                    st, err = portfolio.read_state()
                    age = None if err else portfolio.age_hours(st.get('asof_taipei'))
                    return self._send(200, dict(version=portfolio.version(), ok=not err,
                                                stale=bool(not err and (age is None or age > portfolio.STALE_HOURS))))
                if u.path == '/api/portfolio/snapshot':
                    txt = portfolio.snapshot_text(q.get('name', ''))
                    if txt is None:
                        return self._send(404, dict(ok=False, error='没有这份快照。'))
                    return self._send(200, dict(ok=True, name=q.get('name'), text=txt))
                if u.path == '/api/avwap':
                    return self._send(200, panel.manual_avwap(q.get('ticker', ''), q.get('anchor', ''), asof_of(q, q.get('ticker'))))
                return self._send(404, dict(ok=False, error='没有这个接口。'))
            rel = 'index.html' if u.path in ('/', '') else 'terminal.html' if u.path == '/terminal' else u.path.lstrip('/')
            if rel.startswith('static/'):
                rel = rel[len('static/'):]
            full = os.path.realpath(os.path.join(STATIC, rel))
            if not full.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(full):
                return self._send(404, b'not found', 'text/plain; charset=utf-8')
            ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
            if ctype.startswith('text/') or ctype in ('application/javascript', 'application/json'):
                ctype += '; charset=utf-8'
            with open(full, 'rb') as f:
                return self._send(200, f.read(), ctype)
        except KeyError:
            return self._send(404, dict(ok=False, error='没有这个标的。'))
        except ValueError as e:     # 参数不对（quant.BadParam 写明是哪个参数、可选什么）：400，不悄悄换成别的
            return self._send(400, bad_request(e))
        except BrokenPipeError:
            pass
        except Exception as e:      # noqa: BLE001
            return self._send(500, dict(ok=False, error=f'服务端出错：{type(e).__name__}'))

    def do_POST(self):
        u = urlparse(self.path)
        try:
            if not self._local():
                return self._send(403, dict(ok=False, error='只允许本机访问。'))
            if 'application/json' not in (self.headers.get('Content-Type') or ''):
                return self._send(415, dict(ok=False, error='需要 JSON 请求。'))
            n = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(n) or b'{}') if n else {}
            if u.path == '/api/refresh':
                return self._send(*run_refresh())
            if u.path == '/api/ai/analyze':
                return self._send(*ai_analyze(body))
            if u.path == '/api/quant/narrate':        # 补充指令 3 的接口名：claude 为真才调用 Claude，否则给模板和保存过的那一版
                if body.get('claude'):
                    return self._send(*ai_analyze(body))
                a = prof(body, 'houshou')
                return self._send(200, ai_narrate(body.get('ticker', ''), body.get('asof') or None, a['model'], a['side'], a['horizon'], a['tf'], a['posmode']))
            if u.path == '/api/chat/send':
                return self._chat_send(body)
            if u.path == '/api/chat/delete':
                return self._send(200, dict(ok=True, removed=chat.delete(body.get('id', ''))))
            if u.path == '/api/notes/manual':
                t = body.get('ticker', '')
                item = notes.add_manual(t, body.get('date', ''), body.get('text', ''))
                return self._send(200, dict(ok=True, item=item, notes=notes.payload(t, body.get('asof') or None)))
            if u.path == '/api/notes/delete':
                t = body.get('ticker', '')
                return self._send(200, dict(ok=True, removed=notes.delete(t, body.get('id', '')), notes=notes.payload(t, body.get('asof') or None)))
            if u.path == '/api/notes/search':
                return self._send(*notes_search(body))
            if u.path == '/api/notes/translate':
                return self._send(*notes_translate(body))
            if u.path == '/api/quant/anchor':         # 手动成本锚点：date 为空就是清除，回到自动
                t = body.get('ticker', '')
                return self._send(200, dict(ok=True, ticker=t, anchor=quant.set_anchor(t, body.get('date') or None, body.get('side'), body.get('tf'))))
            if u.path == '/api/quant/tasks':          # 盯盘任务：新建、暂停/继续、删除、标为已读
                op = body.get('op')
                if op == 'add':
                    tasks.add(body)
                elif op in ('pause', 'resume', 'delete', 'seen'):
                    tasks.update(body.get('id') or None, enabled=dict(pause=False, resume=True).get(op), delete=op == 'delete', seen=op == 'seen')
                else:
                    raise ValueError('不认识的操作。')
                return self._send(200, tasks.listing(force=op == 'resume'))
            if u.path == '/api/rules':
                return self._send(200, dict(ok=True, text=mine.save_rules(body.get('text'))))
            if u.path == '/api/portfolio/ignore':      # 忽略这一笔：记在 data/quant/，不碰持仓文件
                return self._send(200, dict(ok=True, ignored=mine.set_ignored(body.get('key'), bool(body.get('ignore', True)))))
            if u.path == '/api/notify':
                return self._send(200, dict(ok=True, settings=mine.save_notify(body.get('mac'), body.get('imessage'))))
            if u.path == '/api/notify/test':           # 他点「发一条测试」才发
                went = mine.send('test', '这是一条测试提醒：盯盘任务条件齐了、收盘碰到你的线时，会这样提醒你。', '这是一条测试提醒，收到就说明能推到手机。', force=True)
                return self._send(200, dict(ok=True, sent=went))
            if u.path == '/api/quant/run':            # 分析记录：点一次「AI 分析当前图表」记一行
                return self._send(200, dict(ok=True, run=tasks.log_run(body, body.get('ai'))))
            if u.path == '/api/quant/runs/clear':
                return self._send(200, dict(ok=tasks.clear_runs()))
            return self._send(404, dict(ok=False, error='没有这个接口。'))
        except KeyError:
            return self._send(404, dict(ok=False, error='没有这个标的。'))
        except ValueError as e:
            return self._send(400, bad_request(e))
        except BrokenPipeError:
            pass
        except Exception as e:      # noqa: BLE001
            return self._send(500, dict(ok=False, error=f'服务端出错：{type(e).__name__}'))


def main():
    """Start on the configured port. When started by hand (no FE_PORT), a busy port is skipped: the next free one
    up to +30 is used and printed, so the panel runs on any machine. launchd always passes FE_PORT (fixed port)."""
    port = int(CFG['port'])
    fixed = bool(os.environ.get('FE_PORT'))
    srv = None
    for p in ([port] if fixed else range(port, port + 31)):
        try:
            srv = ThreadingHTTPServer(('127.0.0.1', p), Handler)
            port = p
            break
        except OSError as e:
            err = e
    if srv is None:
        sys.exit(f'端口 {port} 起不来（{err}）。可能已有别的程序在用，换一个试试：FE_PORT=8800 ./start.sh' if fixed
                 else f'{port}–{port + 30} 的端口都被占用了，换一个范围试试：FE_PORT=9800 ./start.sh')
    if port != int(CFG['port']):
        print(f'端口 {CFG["port"]} 被别的程序占用，改用 {port}。', flush=True)
    ok, why = ai_explain.status(CFG)
    url = f'http://localhost:{port}'
    print(f'四要素面板已启动：{url}', flush=True)
    print(f'AI 解读：{"可用，模型 " + CFG["ai_model"] if ok else "不可用。" + why}', flush=True)
    def warm():         # 先把数据读进来；再把后手在全部样本上的触发次数算好（模型页要用，第一次要算几秒）
        for t in panel.TICKERS:
            panel.load(t)
        try:
            quant.houshou_sample()
        except Exception:       # noqa: BLE001
            pass
    threading.Thread(target=warm, daemon=True).start()

    def watch():        # 每 10 分钟看一眼：有新 K 线了（定时刷新是另一个进程做的），就把盯盘任务和线的提醒过一遍
        seen = None
        time.sleep(60)
        while True:
            try:
                key = tuple(panel.load(t)['B']['d'][-1] for t in panel.TICKERS)
                if key != seen:
                    tasks.listing(check=True)
                    tasks.line_alerts()
                    seen = key
            except Exception:       # noqa: BLE001  检查失败下一轮再来，不影响面板
                pass
            time.sleep(600)
    threading.Thread(target=watch, daemon=True).start()
    if os.environ.get('FE_OPEN') == '1':                  # ./start.sh 在终端里运行时自动打开浏览器
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止。')


if __name__ == '__main__':
    main()
