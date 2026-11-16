"""结构线：「识别图表结构」这一步（APP_ADDENDUM_QUANT_AI.md §5）。

水平支撑/压力、趋势线、斐波那契回撤。全部从已确认的摆动点和 ≤ i 的 K 线算出来，容差和回看根数是【估算】（houshou.EST）。
返回 lines: [{id, kind, label, price | p1+p2, style}]，前端逐条画，每条带开关。
"""
import houshou as hs

FIB = (0.236, 0.382, 0.5, 0.618, 0.786)


def support_resistance(P, i):
    """Cluster confirmed swing points of the last sr_win bars within sr_tol; count touches (≥3 bars apart).
    Returns (resistance, support): the most-touched level above and below the close, or None."""
    tol, win = hs.EST['sr_tol'], hs.EST['sr_win']
    w0 = max(0, i - win + 1)
    conf, _ = hs.swings(P, i)
    prices = sorted(x['price'] for x in conf if x['i'] >= w0)
    clusters = []
    for p in prices:
        if clusters and p <= clusters[-1][0] * (1 + tol):
            clusters[-1].append(p)
        else:
            clusters.append([p])
    h, l, close = P['h'], P['l'], float(P['c'][i])
    levels = []
    for cl in clusters:
        lv = sum(cl) / len(cl)
        lo, hi = lv * (1 - tol), lv * (1 + tol)
        n, last = 0, -10
        for j in range(w0, i + 1):
            if (lo <= h[j] <= hi or lo <= l[j] <= hi) and j - last >= 3:
                n += 1
                last = j
        levels.append((lv, n))
    pick = lambda xs: max(xs, key=lambda x: (x[1], -abs(x[0] - close))) if xs else None
    return pick([x for x in levels if x[0] > close]), pick([x for x in levels if x[0] < close])


def lines(P, i, hsr, model='houshou', four=None, core=False):
    """hsr = houshou.compute(...) at bar i (its start low and top give the main advance for the Fibonacci levels).
    four = panel.state_at(...) when the model is the four-evidence one. core = this ticker is held as a core position."""
    d = P['d']
    out = []
    res, sup = support_resistance(P, i)
    if res:
        out.append(dict(id='res', kind='level', group='structure', label=f'压力·{res[1]} 次', price=hs.r2(res[0]), style='res'))
    if sup:
        out.append(dict(id='sup', kind='level', group='structure', label=f'支撑·{sup[1]} 次', price=hs.r2(sup[0]), style='sup'))
    conf, _ = hs.swings(P, i)
    for kind, key, style in (('high', 'tl_res', 'tres'), ('low', 'tl_sup', 'tsup')):
        pts = [x for x in conf if x['kind'] == kind][-2:]
        if len(pts) == 2:
            up = pts[1]['price'] > pts[0]['price']
            name = ('上升' if up else '下降') + ('压力线' if kind == 'high' else '支撑线')
            out.append(dict(id=key, kind='trend', group='structure', label=name, style=style,
                            p1=dict(date=pts[0]['date'], price=pts[0]['price']), p2=dict(date=pts[1]['date'], price=pts[1]['price'])))
    if hsr.get('start_low') and hsr.get('top'):
        lo, hi = hsr['start_low']['price'], hsr['top']['price']
        if hi > lo:
            for r in FIB:
                out.append(dict(id=f'fib_{r}', kind='level', group='structure', label=str(r), price=hs.r2(hi - r * (hi - lo)), style='fib',
                                span=dict(low=hsr['start_low'], high=dict(date=hsr['top']['date'], price=hi))))
    n_struct = len(out)
    if model == 'houshou':
        if hsr.get('zone'):
            out.append(dict(id='zone_hi', kind='level', group='model', label='建仓上沿', price=hsr['zone'][1], style='zone'))
            out.append(dict(id='zone_lo', kind='level', group='model', label='建仓下沿', price=hsr['zone'][0], style='zone'))
            if not core:        # 核心仓没有价格止损：D 点下 2% 这条线不画
                out.append(dict(id='stop', kind='level', group='model', label='止损（手动止损）', price=hsr['stop'], style='stop'))
    elif four:
        dr, lv = four['draw'], four['levels']
        if dr.get('fan') and lv.get('fan05') is not None and four['index'] > dr['fan']['lo']:
            out.append(dict(id='four_fan', kind='auto', group='model', label='0.5 扇线', style='fan',
                            p1=dict(date=d[dr['fan']['hi']], price=dr['fan']['H']), p2=dict(date=four['asof'], price=lv['fan05'])))
        if dr.get('avwap'):
            out.append(dict(id='four_avwap', kind='auto', group='model', label='锚定 VWAP', style='vwap', price=lv.get('avwap')))
        if lv.get('stop') is not None:
            out.append(dict(id='four_stop', kind='auto', group='model', label='止损线', style='stop', price=hs.r2(lv['stop'])))
    return out, n_struct
