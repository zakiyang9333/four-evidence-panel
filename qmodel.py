"""规则模型的公共底座：录屏里每一套「战法」对应一个模型文件，它们都靠这里的几样东西，交出同一种形状的结果。

一个模型文件只需要写一个 core(P, j)：在第 j 根 K 线上，这套规则怎么说（只用 ≤ j 的数据）。其余的事这里统一做：
- 做多 / 做空：和 houshou.py 一样，做空时价格取负（最高最低互换）后跑同一段 core，再把结果翻回真实价格。
  指标也在取负后的价格上算，所以 RSI 30 自动变成 RSI 70、布林下轨自动变成上轨，规则代码不用写两遍。
- 触发后收盘越过止损：这个结构作废（settle）。
- 历史触发：把过去每一次“条件齐”数出来，看之后先到目标还是先破止损（history）。
- 图上画什么：模型交一份图形清单（shapes），前端照着画，不认识模型。
- 交给面板的结果：状态 state（ready 条件齐 / wait 等 / avoid 不追 / risk 留意风险 / watch 继续观察 / na 用不上 / dead 已失效）、
  清单 checks、计划价位、一段说明、模板解说的几问、大白话解释。

全部因果；全部只是观察，不是买卖依据。参数里哪些是录屏里说的（VIDEO）、哪些是自己估的（EST），每个模型文件各自写明。
"""
import bisect

import numpy as np

import houshou as hs
import indicators as ind
from houshou import up, dn, rel, r2, pct, vol_text      # noqa: F401  （模型文件从这里拿）

STATES = ('ready', 'wait', 'avoid', 'risk', 'watch', 'na', 'dead')


# ---------- prices in and out of the working direction ----------

def R(P, x):
    """A working-direction price back to a real price, rounded for display (more decimals below 1, e.g. early split-adjusted prices)."""
    return None if x is None else hs.px(P['s'] * x)


def span(P, a, b):
    """Two working-direction prices as real prices, low first."""
    return (R(P, a), R(P, b)) if P['s'] == 1 else (R(P, b), R(P, a))


def long(P):
    return P['s'] == 1


def pick(P, a, b):
    """a on the long side, b on the short side (for words)."""
    return a if P['s'] == 1 else b


# ---------- indicators on the working prices (mirrored automatically on the short side) ----------

def _ema(x, n):
    k = 2 / (n + 1)
    out = np.empty(len(x))
    e = x[0] if len(x) else 0.0
    for i, v in enumerate(x):
        e = v * k + e * (1 - k)
        out[i] = e
    return out


def ix(P):
    """rsi, k, d, j, mid/up/low (布林带), dif/dea/hist (MACD, 柱 = 2×(DIF−DEA)), all on the working prices. Cached on P."""
    if 'ix' not in P:
        c = P['c']
        k, d, j = ind.kdj(P['h'], P['l'], c)
        mid, bu, bl = ind.boll(c)
        dif = _ema(c, 12) - _ema(c, 26) if len(c) else np.array([])
        dea = _ema(dif, 9) if len(c) else np.array([])
        P['ix'] = dict(rsi=ind.rsi(c), k=k, d=d, j=j, mid=mid, up=bu, low=bl, dif=dif, dea=dea, hist=2 * (dif - dea), ma={}, vma={})
    return P['ix']


def ma(P, n):
    X = ix(P)
    if n not in X['ma']:
        X['ma'][n] = ind.sma(P['c'], n)
    return X['ma'][n]


def vma(P, n):
    X = ix(P)
    if n not in X['vma']:
        X['vma'][n] = ind.sma(P['v'], n)
    return X['vma'][n]


def vavg(P, a, b):
    """Mean volume of bars a..b inclusive (None when empty)."""
    return float(P['v'][a:b + 1].mean()) if b >= a else None


# ---------- swing points as seen at bar j ----------

def pivots(P, j, since=0):
    """Confirmed swing points up to bar j, oldest first: [(bar, price, kind)], kind +1 = high, −1 = low (working direction)."""
    k = bisect.bisect_right(P['pat'], j)
    a = bisect.bisect_left(P['pi'], since)
    return [(P['pi'][m], P['pp'][m], P['pk'][m]) for m in range(a, k)]


def pending(P, j):
    """The extreme that is still forming at bar j: (bar, price, kind) or None."""
    k = P['pend_k'][j]
    if not k:
        return None
    q = P['pend_i'][j]
    return (q, float(P['h'][q] if k == 1 else P['l'][q]), k)


def confirmed_at(P, bar):
    """The bar on which the swing point at `bar` got confirmed (None if it is not a confirmed swing point)."""
    m = bisect.bisect_left(P['pi'], bar)
    return P['pat'][m] if m < len(P['pi']) and P['pi'][m] == bar else None


# ---------- a result ----------

def blank(**kw):
    out = dict(phase='无结构', verdict='不适用', state='na', list=None, checks=[], missing=[], next_needs=[], note='', text='', zone=None, mid=None, stop=None, t1=None,
               t2=None, t2_note='', rr=None, shapes=[], legend=[], zone_from=None, cells=None, pre=None, _ev=None, _from=None, _stop=None)
    out.update(kw)
    return out


def check(k, name, ok, why, ask='', yes='', no='', sticker_yes='', sticker_no='等', good=True, draw=None):
    """One line of a checklist. ask / yes / no / sticker_* feed the template narration (the question, what is said either way, the sticker)."""
    return dict(k=k, name=name, ok=bool(ok), why=why, ask=ask or name + '了吗？', yes=yes or name, no=no or '还没' + name, sticker_yes=sticker_yes or name, sticker_no=sticker_no,
                good=bool(good), draw=draw or [])


def plan(P, zlo, zhi, stop, t1, t2=None, t2_note='', t2_none=''):
    """Entry zone, stop and targets from working-direction prices (zlo ≤ zhi, stop below, targets above). Real prices come out."""
    mid = (zlo + zhi) / 2
    stop = min(stop, dn(zlo, 0.005))           # 止损至少在建仓区外面一点：不会出现止损在区间里面的计划
    ok2 = t2 is not None and t1 is not None and t2 > t1
    return dict(zone=list(span(P, zlo, zhi)), mid=R(P, mid), stop=R(P, stop), t1=R(P, t1), t2=R(P, t2) if ok2 else None,
                t2_note=t2_note if ok2 else (t2_none or '第二目标的位置没有超过第一目标，不设'),
                rr=r2((t1 - mid) / (mid - stop)) if t1 is not None and mid > stop and t1 > mid else None, _stop=stop,
                _bad=hs.plan_check(P['s'], mid, stop, t1))      # 价位在显示的位数下分不开：settle() 会把这次“条件齐”收回


def r_plan(zlo, zhi, stop, r1, r2):
    """原版没有目标价的趋势规则（海龟、超级趋势）：两个目标按“止损距离”的倍数量（R 倍数）。
    止损先照 plan() 的做法挪到建仓区外面，再从建仓区中间量，所以第一目标一定在建仓区外面。返回 (zlo, zhi, stop, t1, t2)。"""
    stop = min(stop, dn(zlo, 0.005))
    mid = (zlo + zhi) / 2
    return zlo, zhi, stop, mid + r1 * (mid - stop), mid + r2 * (mid - stop)


def preplan(P, zlo, zhi, stop, t1, t2=None):
    """预案价位：清单还没齐时，假如还差的那几项就在今天收盘成立，计划会落在哪。和 plan() 是同一套公式，只交给 AI 对话（信号卡照旧不给价位）。
    价位在显示的位数下分不开、或者第一目标没有越过入场区，就不给。模型文件只在“还差的那几项以后还可能成立”的时候调用它；
    还在走的那个点（比如二探的低点）要先挪到“刚好让那一项成立”的位置，再传进来。"""
    p = plan(P, zlo, zhi, stop, t1, t2)
    return None if p['_bad'] or p['rr'] is None or t1 <= zhi else {k: p[k] for k in ('zone', 'mid', 'stop', 't1', 't2', 'rr')}


def finish(out):
    out['missing'] = [x['name'] + '：' + x['why'] for x in out['checks'] if not x['ok']]
    return out


# ---------- shapes (the drawing list; dates and real prices) ----------

def sh_line(P, i0, vals, style, label=None, key=None, w=1.5, dash=None, dy=None):
    d, s = P['d'], P['s']
    pts = [[d[i0 + k], None if v is None or not np.isfinite(v) else round(float(s * v), 4)] for k, v in enumerate(vals)]
    return dict(t='line', pts=pts, style=style, label=label, key=key, w=w, dash=dash, dy=dy)


def sh_band(P, i0, upper, lower, style, alpha=None):
    d, s = P['d'], P['s']
    f = lambda vals: [[d[i0 + k], None if v is None or not np.isfinite(v) else round(float(s * v), 4)] for k, v in enumerate(vals)]
    return dict(t='band', up=f(upper), lo=f(lower), style=style, alpha=alpha)


def sh_seg(P, a, b, style, label=None, key=None, dash=None, extend=False, w=1.5, dy=None):
    """a, b = (bar, working price)."""
    return dict(t='seg', a=[P['d'][a[0]], R(P, a[1])], b=[P['d'][b[0]], R(P, b[1])], style=style, label=label, key=key, dash=dash, extend=extend, w=w, dy=dy)


def sh_hl(P, i1, price, style, label=None, key=None, i2=None, dash=None, w=1.6, dy=None):
    return dict(t='hl', d1=P['d'][i1], d2=None if i2 is None else P['d'][i2], p=R(P, price), style=style, label=label, key=key, dash=dash, w=w, dy=dy)


def sh_box(P, i1, i2, p1, p2, style, label=None, key=None, alpha=None, border=True):
    a, b = span(P, min(p1, p2), max(p1, p2))
    return dict(t='box', d1=P['d'][i1], d2=None if i2 is None else P['d'][i2], p1=a, p2=b, style=style, label=label, key=key, alpha=alpha, border=border)


def sh_badge(P, i, price, text, style, above=True, note=None, key=None, first=False, soft=False, dx=0):
    """above = on the far side of a working-direction high (drawn above the bar on the long side, below it on the short side)."""
    return dict(t='badge', d=P['d'][i], p=R(P, price), text=text, style=style, pos='above' if above == (P['s'] == 1) else 'below', note=note, key=key, first=first, soft=soft, dx=dx)


def sh_dot(P, i, price, style, label=None, key=None, above=True, ring=False):
    return dict(t='dot', d=P['d'][i], p=R(P, price), style=style, label=label, key=key, pos='above' if above == (P['s'] == 1) else 'below', ring=ring)


def sh_text(P, i, price, text, style, above=True, key=None):
    return dict(t='text', d=P['d'][i], p=R(P, price), text=text, style=style, pos='above' if above == (P['s'] == 1) else 'below', key=key)


def sh_vbar(P, i, style, label=None, key=None):
    return dict(t='vbar', d=P['d'][i], style=style, label=label, key=key)


def sh_profile(P, a, b, style='mute', label=None, key=None, bins=24):
    """Volume by price over bars a..b, in real prices."""
    if P['s'] == 1:
        vp = ind.volume_profile(P['h'], P['l'], P['v'], a, b, bins)
    else:
        vp = ind.volume_profile(-P['l'], -P['h'], P['v'], a, b, bins)
    return dict(t='profile', d1=P['d'][a], d2=P['d'][b], lo=round(vp['lo'], 4), step=round(vp['step'], 6), vol=[round(x) for x in vp['vol']], poc=round(vp['poc'], 4),
                style=style, label=label, key=key)


def legend_item(key, text):
    return dict(key=key, text=text)


# ---------- what needs earlier bars: a triggered structure dies when a close goes through its stop ----------

def fine(r):
    """A ready result whose plan can't be shown honestly (houshou.plan_check: entry and stop can't be told apart at the shown decimals,
    or the reward/risk worked out from the shown prices disagrees with the real one) is not a trigger: no 条件齐, no prices, no reward/risk."""
    if r.get('state') != 'ready' or not r.get('_bad'):
        return r
    note = f'清单都成立，但{r["_bad"]}。这一次不算条件齐，也不给价位和盈亏比。'
    r = dict(r)
    r.update(verdict=hs.TOO_FINE, verdict_text='价位太细，不给价位', state='na', zone=None, mid=None, stop=None, t1=None, t2=None, rr=None, cells=None,
             zone_from=None, next_needs=[], note=note, text=note, pre=None, _stop=None)
    return r


def settle(P, key, core, j):
    """core(P, j) plus the one thing that needs earlier results. core must memoise itself (use memo())."""
    r = fine(dict(core(P, j)))
    ev = r.get('_ev')
    if ev is None or r['state'] == 'dead':
        return r
    start = r['_from'] if r.get('_from') is not None else max(0, j - 60)
    for q in range(max(0, start), j):
        rq = fine(core(P, q))
        if rq.get('_ev') == ev and rq['state'] == 'ready' and rq.get('_stop') is not None:
            x = next((x for x in range(q + 1, j + 1) if P['c'][x] < rq['_stop']), None)
            if x is not None:
                r.update(phase='已失效', verdict='已失效', state='dead', zone=None, mid=None, stop=None, t1=None, t2=None, rr=None, next_needs=[], zone_from=None, pre=None,
                         note=f'{P["d"][q]} 条件齐过一次，{P["d"][x]} 收盘越过了当时的止损 {R(P, rq["_stop"])}，这个结构作废。')
                r['text'] = r['note']
            break
    return r


def memo(P, key, j, build):
    """Per-bar cache for a model's core on one prepared pass."""
    m = P.setdefault('m_' + key, {})
    if j not in m:
        m[j] = build()
    return m[j]


# ---------- history: every past trigger and what came first afterwards ----------

def history(P, key, core, i, hold=20):
    st = P.setdefault('h_' + key, dict(upto=-1, rows=[], seen=set(), ok={}, live=[]))
    for j in range(st['upto'] + 1, i + 1):
        r = settle(P, key, core, j)
        if r['checks']:
            st['live'].append(j)
        for c in r['checks']:
            if c['ok']:
                st['ok'].setdefault(c['k'], []).append(j)
        if r['state'] == 'ready' and r.get('_ev') is not None and r['_ev'] not in st['seen'] and r.get('stop') is not None and r.get('t1') is not None:
            st['seen'].add(r['_ev'])
            st['rows'].append((j, r['mid'], r['stop'], r['t1'], r['rr']))
    st['upto'] = max(st['upto'], i)
    rows, s = [], P['s']
    for j, mid, stop, t1, rr in st['rows']:
        if j > i:
            break
        res, when = None, None
        for x in range(j + 1, min(j + hold, i) + 1):
            if P['c'][x] < s * stop:
                res, when = 'stop', x
                break
            if P['h'][x] >= s * t1:
                res, when = 'target', x
                break
        if res is None:
            res = 'none' if j + hold <= i else 'open'
        rows.append(dict(date=P['d'][j], mid=mid, stop=stop, t1=t1, rr=rr, outcome=res, outcome_date=P['d'][when] if when is not None else None,
                         bars=(when - j) if when is not None else None))
    cnt = lambda xs: bisect.bisect_right(xs, i)
    rrs = sorted(r['rr'] for r in rows if r['rr'] is not None)
    return dict(n=len(rows), rows=rows, hold=hold, note='样本数 %d，未做对照检验' % len(rows), rr_median=r2(rrs[len(rrs) // 2]) if rrs else None,
                stats=dict(bars=i + 1, live=cnt(st['live']), checks={k: cnt(v) for k, v in st['ok'].items()}))


def compute(mod, B, i=None, side='long', P=None, with_history=True, hold=None):
    """The public result of a model module at bar i (default: the last bar), in real prices."""
    P = P or hs.prepare(B, side)
    i = P['n'] - 1 if i is None else int(i)
    r = settle(P, mod.KEY, mod.core, i)
    res = {k: v for k, v in r.items() if not k.startswith('_')}
    res.update(model=mod.VERSION, name=mod.NAME, side=P['side'], asof=P['d'][i], index=i, close=r2(P['s'] * P['c'][i]),
               params=dict(video=getattr(mod, 'VIDEO', {}), est=getattr(mod, 'EST', {}), **({'source': mod.SOURCE} if getattr(mod, 'SOURCE', None) else {})))   # source：开源原版里的数
    if with_history:
        res['history'] = history(P, mod.KEY, mod.core, i, hold or 20)
    return res
