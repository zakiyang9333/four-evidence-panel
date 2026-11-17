"""面板后端的引擎适配层。

四项证据的真假、高低点、扇线、成本线、止损、目标全部来自 engine.compute()，这里不重新判定任何规则。
本文件只做三件事：
  1. 把数据截到某一天（回放），在截断后的数据上调用引擎，所以结果不可能用到那天之后的数据；
  2. 把引擎在那一天的输出整理成前端要的 JSON（文案沿用 build_dashboard.py）；
  3. 给画线用的展示序列（扇线三条、成本线逐日值、图上标记的位置），公式照抄 engine.py，
     tests/test_panel.py 会核对它们在当天的值和引擎输出一致。
"""
import json
import os
import threading

import numpy as np

import engine as E

ROOT = os.path.dirname(os.path.abspath(__file__))
TICKERS = ('SPCX', 'NVDA', 'QQQ')
P, F = E.VIDEO, E.FIXED
FAN_LEVELS = (0.382, 0.5, 0.618)
NAMES = ('地量见底', '底背离出现', '跌速放缓', '站回成本线')

_lock = threading.Lock()
_cache = {}


def data_dir():
    return os.environ.get('FE_DATA_DIR') or os.path.join(ROOT, 'data')


def csv_path(t):
    return os.path.join(data_dir(), f'{t}.csv')


def fnum(x, nd=6):
    """float -> JSON-safe number (None for NaN/inf)."""
    if x is None:
        return None
    x = float(x)
    return round(x, nd) if np.isfinite(x) else None


def load(t):
    """Bars + full-history display series, cached until the CSV changes on disk."""
    if t not in TICKERS:
        raise KeyError(t)
    path = csv_path(t)
    st = os.stat(path)
    key = (st.st_mtime_ns, st.st_size)
    with _lock:
        hit = _cache.get(t)
        if hit and hit['key'] == key:
            return hit
    B = E.load(path)
    S = E.compute(B)
    hit = dict(key=key, B=B, S=S, idx={d: i for i, d in enumerate(B['d'])})
    with _lock:
        _cache[t] = hit
    return hit


def clear_cache():
    with _lock:
        _cache.clear()


def index_at(B, asof):
    """Last bar on or before `asof` (YYYY-MM-DD). None/'' -> last bar. Never below 1."""
    d = B['d']
    n = len(d)
    if not asof:
        return n - 1
    lo, hi = 0, n          # bisect_right on ISO date strings
    while lo < hi:
        mid = (lo + hi) // 2
        if d[mid] <= asof:
            lo = mid + 1
        else:
            hi = mid
    return max(1, min(n - 1, lo - 1))


def truncate(B, i):
    """Copy of the bars up to and including index i. Nothing after i survives."""
    return dict(d=B['d'][:i + 1], o=B['o'][:i + 1].copy(), h=B['h'][:i + 1].copy(), l=B['l'][:i + 1].copy(),
                c=B['c'][:i + 1].copy(), v=B['v'][:i + 1].copy(), src=B['src'][:i + 1])


# ---------- display series (same formulas as engine.py; verified against it in tests) ----------

def fan_value(H, L, hi, lo, j, r):
    """Fan line through (hi, H) and (lo, L + r*(H-L)), evaluated at bar j. engine.compute uses r = P['fan']."""
    lvl = L + r * (H - L)
    return H + (lvl - H) * (j - hi) / (lo - hi)


def avwap_series(B, anchor, i):
    """Anchored VWAP from bar `anchor` to bar i (typical price (H+L+C)/3), one value per bar."""
    tp = (B['h'][anchor:i + 1] + B['l'][anchor:i + 1] + B['c'][anchor:i + 1]) / 3
    v = B['v'][anchor:i + 1]
    return np.cumsum(tp * v) / np.cumsum(v)


def _e3_bar(B, S, i):
    """Where to put marker 3: first bar of the current run of closes above the fan mid line."""
    hi, lo = int(S['hi_i'][i]), int(S['low_i'][i])
    H, L = S['H'][i], S['L'][i]
    j = i
    while j - 1 > lo and B['c'][j - 1] > fan_value(H, L, hi, lo, j - 1, P['fan']):
        j -= 1
    return j


def _e4_bar(B, S, i):
    """Where to put marker 4: the big-volume up day the engine's E4 loop stops on (same conditions)."""
    lo, an = int(S['low_i'][i]), int(S['anchor'][i])
    if an < 0:
        return None
    aw = avwap_series(B, an, i)
    for j in range(max(lo + 1, an), i + 1):
        if j < 5:
            continue
        if B['c'][j] > aw[j - an] and B['c'][j] > B['o'][j] and B['v'][j] >= P['vol_mult'] * B['v'][j - 5:j].mean():
            return j
    return None


# ---------- data freshness (US trading calendar) ----------
# NYSE full-day closures. Outside these years the check falls back to plain weekdays and says so.
NYSE_HOLIDAYS = {
    '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07',
    '2026-11-26', '2026-12-25',
    '2027-01-01', '2027-01-18', '2027-02-15', '2027-03-26', '2027-05-31', '2027-06-18', '2027-07-05', '2027-09-06',
    '2027-11-25', '2027-12-24',
}
CALENDAR_YEARS = (2026, 2027)
CLOSE_GRACE_H = 4          # a session counts as "should be in the file" 4 h after the 16:00 New York close


def is_session(day):
    return day.weekday() < 5 and day.isoformat() not in NYSE_HOLIDAYS


def expected_last_session(now=None):
    """Latest US session whose close + grace has passed, as YYYY-MM-DD."""
    import datetime
    from zoneinfo import ZoneInfo
    ny = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(ZoneInfo('America/New_York'))
    day = ny.date()
    if not (is_session(day) and ny.hour >= 16 + CLOSE_GRACE_H):
        day -= datetime.timedelta(days=1)
    while not is_session(day):
        day -= datetime.timedelta(days=1)
    return day.isoformat()


def freshness(t, now=None):
    """Is the stored K-line data up to the latest closed session? Source = the CSV's own last date."""
    import datetime
    last = load(t)['B']['d'][-1]
    exp = expected_last_session(now)
    lag = 0
    day = datetime.date.fromisoformat(last) + datetime.timedelta(days=1)
    end = datetime.date.fromisoformat(exp)
    while day <= end:
        lag += is_session(day)
        day += datetime.timedelta(days=1)
    return dict(last=last, expected=exp, lag_sessions=lag, stale=lag > 0,
                calendar_known=int(exp[:4]) in CALENDAR_YEARS, grace_hours=CLOSE_GRACE_H)


def last_refresh():
    """Result of the last data refresh (button or scheduled job), written by prep_data.py."""
    try:
        with open(os.path.join(data_dir(), 'last_refresh.json'), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---------- weekly bars (display only: the four-evidence rules are judged on daily bars) ----------

def weekly(B):
    """Aggregate daily bars into ISO weeks. Each weekly bar is dated by its last trading day and contains
    only days up to that date, so slicing weekly bars at a date never uses later days."""
    import datetime
    keys = [datetime.date.fromisoformat(d).isocalendar()[:2] for d in B['d']]
    starts = [k for k in range(len(keys)) if k == 0 or keys[k] != keys[k - 1]]
    ends = starts[1:] + [len(keys)]
    W = dict(d=[], o=[], h=[], l=[], c=[], v=[], src=[])
    for a, b in zip(starts, ends):
        W['d'].append(B['d'][b - 1]); W['o'].append(B['o'][a]); W['h'].append(B['h'][a:b].max())
        W['l'].append(B['l'][a:b].min()); W['c'].append(B['c'][b - 1]); W['v'].append(B['v'][a:b].sum())
        single = [s for s in B['src'][a:b] if 'single' in s]
        W['src'].append(f'{len(single)} 天单一来源' if single else 'project')
    for k in ('o', 'h', 'l', 'c', 'v'):
        W[k] = np.array(W[k], dtype=float)
    return W


# ---------- payloads ----------

def bars_payload(t, tf='D'):
    """Everything the chart needs, for the whole history. Indicators are causal, so the front end may slice.
    tf='W' gives weekly bars with their own MACD and volume averages; no 地量 marks (that rule is daily)."""
    hit = load(t)
    B, S = hit['B'], hit['S']
    if tf == 'W':
        B = weekly(B)
        dif, dea, hist = E.macd(B['c'])
        lowvol = []
    else:
        tf = 'D'
        dif, dea, hist = S['dif'], S['dea'], S['hist']
        lowvol = [i for i in range(len(B['v'])) if S['low_vol'][i]]
    v = B['v']
    n = len(v)

    def sma(k):
        out = [None] * n
        cs = np.concatenate([[0.0], np.cumsum(v)])
        for i in range(k - 1, n):
            out[i] = fnum((cs[i + 1] - cs[i + 1 - k]) / k, 2)
        return out

    r = lambda a, nd=6: [fnum(x, nd) for x in a]
    import indicators as ind            # 副图用的指标：只是显示，四要素的判定不看它们
    kk, kd, kj = ind.kdj(B['h'], B['l'], B['c'])
    bm, bu, bl = ind.boll(B['c'])
    return dict(ticker=t, tf=tf, d=B['d'], o=r(B['o']), h=r(B['h']), l=r(B['l']), c=r(B['c']), v=[int(x) for x in v],
                vma5=sma(5), vma10=sma(10), dif=r(dif), dea=r(dea), hist=r(hist), lowvol=lowvol,
                rsi=r(ind.rsi(B['c']), 2), kdj_k=r(kk, 2), kdj_d=r(kd, 2), kdj_j=r(kj, 2), boll_mid=r(bm, 4), boll_up=r(bu, 4), boll_low=r(bl, 4),
                atr=r(ind.atr(B['h'], B['l'], B['c']), 4),
                src={str(i): s for i, s in enumerate(B['src']) if s != 'project'},
                crosscheck=crosscheck(t), freshness=freshness(t),
                params=dict(n_vol=P['n_vol'], dd=P['dd'], stop=P['stop'], fan=P['fan'],
                            vol_mult=P['vol_mult'], hi_win=F['hi_win'], tgt_win=F['tgt_win']))


def crosscheck(t):
    """Second-source check of single-source rows, written by prep_data.py. Read-only here."""
    try:
        with open(os.path.join(data_dir(), 'crosscheck.json'), encoding='utf-8') as f:
            return json.load(f).get(t, {})
    except (OSError, ValueError):
        return {}


def state_at(t, asof=None):
    """State of the rule model at the close of `asof`, computed on data truncated to that day."""
    full = load(t)['B']
    i = index_at(full, asof)
    B = truncate(full, i)
    S = E.compute(B)
    n = i + 1
    d, o, h, l, c, v = B['d'], B['o'], B['h'], B['l'], B['c'], B['v']
    hi, lo, an = int(S['hi_i'][i]), int(S['low_i'][i]), int(S['anchor'][i])
    H, L = float(S['H'][i]), float(S['L'][i])
    hist = S['hist']
    armed, all4 = bool(S['dd_ok'][i]), bool(S['all4'][i])
    oks = [bool(S[k][i]) for k in ('e1', 'e2', 'e3', 'e4')]
    ddp = int(P['dd'] * 100)

    # --- evidence text (wording follows build_dashboard.py) ---
    vmin = v[max(0, i - P['n_vol'] + 1):i + 1].min()
    enough = n >= P['n_vol']
    trough = float(hist[hi:lo - F['div_gap'] + 1].min()) if lo - hi >= F['div_gap'] + 1 else None
    fl, aw = float(S['fanline'][i]), float(S['avwap'][i])
    texts = []
    if oks[0]:
        texts.append(f"{d[an]} 出现地量（下跌 ≥{ddp}% 后的 {P['n_vol']} 日最小量），成本线从这天起算。")
    else:
        s = (f"还没有。当日成交量 {v[i]/1e6:.1f} 百万股，{P['n_vol']} 日最小量 {vmin/1e6:.1f} 百万股，当日比它多 {(v[i]/vmin-1)*100:.0f}%。"
             if enough else f"K线不足 {P['n_vol']} 根，无法判断。")
        texts.append(s + ("" if armed else f" 另外跌幅还没到 {ddp}%。"))
    if oks[1]:
        texts.append(f"最低点 {d[lo]}（{L:.2f}）那天 MACD 柱 {hist[lo]:.2f}，高于此前最深的 {trough:.2f}：价格更低，杀跌力度更小。")
    elif trough is not None:
        texts.append(f"没有。最低点 {d[lo]}（{L:.2f}）那天 MACD 柱 {hist[lo]:.2f}，就是这轮最深（此前最深 {trough:.2f}）：价格和力度一起创新低。")
    else:
        texts.append("高点到低点太近，无法比较。")
    if oks[2]:
        texts.append(f"收盘 {c[i]:.2f} 在扇子中线 {fl:.2f} 上方。")
    elif np.isfinite(fl):
        texts.append(f"没有。收盘 {c[i]:.2f}，扇子中线 {fl:.2f}，还差 {(fl/c[i]-1)*100:.1f}%。")
    else:
        texts.append("当日就是最低点，扇子还没法画。")
    if oks[3]:
        texts.append(f"放量阳线已站回成本线 {aw:.2f}，收盘 {c[i]:.2f} 仍在线上。")
    elif np.isfinite(aw):
        where = '在线上，但低点之后还没出现放量阳线站回' if c[i] > aw else '在线下 ' + format((aw / c[i] - 1) * 100, '.1f') + '%'
        texts.append(f"没有。成本线 {aw:.2f}，收盘 {c[i]:.2f}（{where}）。")
    else:
        texts.append("没有地量日，成本线还没起算。")
    evidence = [dict(k=f'E{k+1}', n=k + 1, name=NAMES[k], ok=oks[k], lit=oks[k] and armed, text=texts[k]) for k in range(4)]
    score = sum(oks)

    # --- conclusion (the engine decides; this only words it) ---
    dd_low = (1 - L / H) * 100
    missing = [NAMES[k] for k in range(4) if not oks[k]]
    if not armed:
        concl = dict(code='not_armed', title='未触发',
                     text=f"从 {F['hi_win']} 日高点最多跌了 {dd_low:.0f}%，没到 {ddp}% 的门槛，系统不找底。")
    elif all4:
        concl = dict(code='all4', title='四项齐了',
                     text="四项证据在这个收盘同时成立，按视频规则这是信号。回测证据不足，仅作观察，不是买入建议。")
    else:
        concl = dict(code='missing', title=f"还缺 {len(missing)} 项",
                     text=f"{score}/4，还缺：{'、'.join(missing)}。按视频规则：不抄底。")
    concl['missing'] = missing

    # --- levels and the sidebar numbers (plain arithmetic on engine outputs, priced at this close) ---
    stop, tgt = float(S['stop'][i]), float(S['target'][i])
    price = float(c[i])
    pct = lambda x: fnum((x / price - 1) * 100, 2) if np.isfinite(x) else None
    tradable = np.isfinite(stop) and price > stop * 1.005          # same guard as engine.trade_from, with close for entry
    tgt_ok = np.isfinite(tgt) and tgt > price * 1.02               # same guard as engine.trade_from
    rr = fnum((tgt - price) / (price - stop), 2) if (tradable and tgt_ok) else None
    signal = dict(price=fnum(price), entry_ref=fnum(aw), entry_ref_pct=pct(aw), stop=fnum(stop), stop_pct=pct(stop),
                  target=fnum(tgt), target_pct=pct(tgt), target_usable=bool(tgt_ok), rr=rr)

    # --- drawing data for the "自动画" layer ---
    fan = None
    if lo > hi:
        fan = dict(hi=hi, lo=lo, H=fnum(H), L=fnum(L), levels={
            str(r): dict(at_lo=fnum(L + r * (H - L)), at_asof=fnum(fan_value(H, L, hi, lo, i, r)) if i > lo else None)
            for r in FAN_LEVELS})
    avw = None
    if an >= 0:
        avw = dict(anchor=an, anchor_date=d[an], values=[fnum(x) for x in avwap_series(B, an, i)])
    draw = dict(fan=fan, avwap=avw, stop=fnum(stop), target=fnum(tgt) if tgt_ok else None,
                high=dict(i=hi, price=fnum(H)), low=dict(i=lo, price=fnum(L)))

    # --- 1..4 triangles, only for evidence that is lit ---
    marks = []
    if evidence[0]['lit']:
        marks.append(dict(n=1, i=an, date=d[an], price=fnum(l[an]), side='below'))
    if evidence[1]['lit']:
        marks.append(dict(n=2, i=lo, date=d[lo], price=fnum(L), side='below'))
    if evidence[2]['lit']:
        j = _e3_bar(B, S, i)
        marks.append(dict(n=3, i=j, date=d[j], price=fnum(h[j]), side='above'))
    if evidence[3]['lit']:
        j = _e4_bar(B, S, i)
        if j is not None:
            marks.append(dict(n=4, i=j, date=d[j], price=fnum(h[j]), side='above'))

    notes = []
    stale = i - lo
    if stale > 40 and armed:
        notes.append(f"最低点在 {stale} 根K线之前（{d[lo]}），基于它的证据偏旧，扇线已经落到很低的位置，参考价值小。")
    if 'single' in B['src'][i]:
        cc = crosscheck(t).get(d[i])
        if cc and cc.get('ok'):
            notes.append(f"这根K线（{d[i]}）写入时只有一个数据源；之后用 {cc['source']} 核对过，收盘价一致。")
        elif cc:
            notes.append(f"这根K线（{d[i]}）只有一个数据源，而且 {cc['source']} 的收盘价与它相差 {cc['diff_pct']}%，数据存疑。")
        else:
            notes.append(f"这根K线（{d[i]}）只有一个数据源，待第二个来源核对。")
    is_latest = i == len(full['d']) - 1
    fresh = freshness(t) if is_latest else None
    if fresh and fresh['stale']:
        notes.insert(0, f"K 线数据只到 {fresh['last']}，最近一个已收盘的交易日是 {fresh['expected']}，还差 {fresh['lag_sessions']} 个交易日没更新。"
                        f"这里的证据是按 {fresh['last']} 收盘判定的，不是最新状态。")

    sig = [{k: q[k] for k in ('sig', 'entry_d', 'entry', 'stop', 'target', 'exit_d', 'exit', 'why', 'r', 'bars')}
           for q in E.signals(B, S)]
    return dict(ticker=t, asof=d[i], index=i, n_total=len(full['d']), is_latest=is_latest, freshness=fresh,
                close=fnum(price), prev_close=fnum(c[i - 1]), chg_pct=fnum((price / c[i - 1] - 1) * 100, 2),
                armed=armed, all4=all4, score=score, lit=score if armed else 0, conclusion=concl, evidence=evidence,
                high=dict(i=hi, date=d[hi], price=fnum(H)), low=dict(i=lo, date=d[lo], price=fnum(L)),
                drawdown_close=fnum((1 - price / H) * 100, 2), drawdown_low=fnum(dd_low, 2),
                levels=dict(stop=fnum(stop), target=fnum(tgt), avwap=fnum(aw), fan05=fnum(fl),
                            anchor_i=an if an >= 0 else None, anchor_date=d[an] if an >= 0 else None),
                signal=signal, draw=draw, marks=marks, notes=notes, src=B['src'][i], single='single' in B['src'][i],
                signals=sig)


def manual_avwap(t, anchor, asof=None):
    """Anchored VWAP for a hand-placed anchor (drawing tool). Same formula as the cost line."""
    full = load(t)['B']
    i = index_at(full, asof)
    a = index_at(full, anchor)
    if a > i:
        return dict(anchor=a, anchor_date=full['d'][a], values=[])
    return dict(anchor=a, anchor_date=full['d'][a], values=[fnum(x) for x in avwap_series(full, a, i)])


def summary():
    """One line per ticker for the tabs."""
    out = []
    for t in TICKERS:
        s = state_at(t)
        hit = load(t)
        out.append(dict(ticker=t, asof=s['asof'], bars=len(hit['B']['d']), first=hit['B']['d'][0], close=s['close'],
                        chg_pct=s['chg_pct'], armed=s['armed'], all4=s['all4'], score=s['score'], lit=s['lit'],
                        src=s['src'], single=s['single'], freshness=s['freshness'],
                        single_rows=sum(1 for x in hit['B']['src'] if 'single' in x)))
    return out


def backtest_summary():
    try:
        with open(os.path.join(ROOT, 'out', 'backtest.json'), encoding='utf-8') as f:
            a = json.load(f)['primary']['all']
        vs = a['vs_random_dip_buying']
        return dict(n=a['n'], win=a['win'], mean_r=a['mean_r'], control_mean_r=vs['control_mean_r'], p=vs['p'],
                    verdict='证据不足')
    except (OSError, ValueError, KeyError):
        return None
