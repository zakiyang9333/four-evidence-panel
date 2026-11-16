"""抄底核心四要素 — causal rule engine v1.0 (supersedes four_evidence.py).
Every value on bar i uses bars <= i. Signals fire on the close, orders fill at the next open.
Parameters marked EST are not stated in the video.
"""
import csv
import numpy as np

VIDEO = dict(
    n_vol=60,       # video: 地量 = 近60日最小量
    fan=0.5,        # video: 扇子中线
    vol_mult=1.5,   # EST: 放量大阳 = volume >= 1.5 x mean of prior 5 days
    stop=0.03,      # video: 止损 最低点下3%
    dd=0.20,        # EST from "跌两成": only hunt for a bottom after a 20% drop
)
FIXED = dict(hi_win=250,    # EST: reference high = highest high of the last 250 bars
             div_gap=5,     # EST: MACD-histogram trough must be >= 5 bars before the price low
             tgt_win=20,    # EST: target = highest high of the 20 bars before the low ("前面涨停")
             max_hold=60,   # EST: time exit after 60 bars
             comm=1.0, slip=0.001, risk_usd=174.0)  # $1/side, 0.1%/side, 0.5% of NAV $34,846


def load(path):
    rows = list(csv.DictReader(open(path)))
    g = lambda k: np.array([float(r[k]) for r in rows])
    return dict(d=[r['date'] for r in rows], o=g('open'), h=g('high'), l=g('low'), c=g('close'), v=g('volume'),
                src=[r.get('src', '') for r in rows])


def ema(x, n):
    k = 2 / (n + 1); out = np.empty_like(x); e = x[0]
    for i, v in enumerate(x):
        e = v * k + e * (1 - k); out[i] = e
    return out


def macd(c):
    dif = ema(c, 12) - ema(c, 26); dea = ema(dif, 9)
    return dif, dea, 2 * (dif - dea)   # 柱 = 2*(DIF-DEA), broker-app convention


def compute(B, P=VIDEO, F=FIXED):
    """Per-bar state arrays. Returns dict of arrays (length n)."""
    o, h, l, c, v = B['o'], B['h'], B['l'], B['c'], B['v']; n = len(c)
    dif, dea, hist = macd(c)
    tp = (h + l + c) / 3
    # 地量 flag: today's volume is the minimum of the last n_vol bars (needs full history)
    low_vol = np.zeros(n, bool)
    for i in range(P['n_vol'] - 1, n):
        low_vol[i] = v[i] <= v[i - P['n_vol'] + 1:i + 1].min()
    vma5_prev = np.full(n, np.nan)
    for i in range(5, n):
        vma5_prev[i] = v[i - 5:i].mean()
    S = {k: np.full(n, np.nan) for k in ('H', 'L', 'fanline', 'avwap', 'stop', 'target', 'dd')}
    S.update({k: np.zeros(n, bool) for k in ('e1', 'e2', 'e3', 'e4', 'dd_ok', 'all4')})
    S.update(hi_i=np.zeros(n, int), low_i=np.zeros(n, int), anchor=np.full(n, -1), hist=hist, dif=dif, dea=dea, low_vol=low_vol)
    for i in range(1, n):
        a0 = max(0, i - F['hi_win'] + 1)
        hi = a0 + int(np.argmax(h[a0:i + 1]))
        lo = hi + int(np.argmin(l[hi:i + 1]))
        H, L = h[hi], l[lo]
        S['hi_i'][i], S['low_i'][i], S['H'][i], S['L'][i] = hi, lo, H, L
        S['dd'][i] = 1 - c[i] / H
        S['dd_ok'][i] = (1 - L / H) >= P['dd']
        S['stop'][i] = L * (1 - P['stop'])
        t0 = max(hi, lo - F['tgt_win'])
        S['target'][i] = h[t0:lo].max() if lo > t0 else np.nan
        # E1: first 地量 day after the high, while price is already down >= dd
        anchor = -1
        for j in range(hi + 1, i + 1):
            if low_vol[j] and c[j] <= H * (1 - P['dd']):
                anchor = j; break
        S['anchor'][i] = anchor; S['e1'][i] = anchor >= 0
        # E2: at the price low, MACD histogram is above its earlier trough
        if lo - hi >= F['div_gap'] + 1:
            S['e2'][i] = hist[lo] > hist[hi:lo - F['div_gap'] + 1].min()
        # E3: close back above the fan line (from the high through level `fan` at the low's bar)
        if lo > hi and i > lo:
            lvl = L + P['fan'] * (H - L)
            S['fanline'][i] = H + (lvl - H) * (i - hi) / (lo - hi)
            S['e3'][i] = c[i] > S['fanline'][i]
        # E4: big-volume up day reclaimed the AVWAP anchored at the 地量 day, and close still above it
        if anchor >= 0:
            pv = np.cumsum(tp[anchor:i + 1] * v[anchor:i + 1]); vv = np.cumsum(v[anchor:i + 1])
            aw = pv / vv; S['avwap'][i] = aw[-1]
            if c[i] > aw[-1]:
                for j in range(max(lo + 1, anchor), i + 1):
                    if c[j] > aw[j - anchor] and c[j] > o[j] and v[j] >= P['vol_mult'] * vma5_prev[j]:
                        S['e4'][i] = True; break
        S['all4'][i] = S['dd_ok'][i] and S['e1'][i] and S['e2'][i] and S['e3'][i] and S['e4'][i]
    return S


def trade_from(B, S, i, F=FIXED):
    """Outcome of entering at open[i+1] on the state of bar i. None if not tradable."""
    o, h, l, c = B['o'], B['h'], B['l'], B['c']; n = len(c)
    if i + 1 >= n: return None
    entry, stop, tgt = o[i + 1], S['stop'][i], S['target'][i]
    if not np.isfinite(stop) or entry <= stop * 1.005: return None
    use_tgt = np.isfinite(tgt) and tgt > entry * 1.02
    risk = entry - stop; ex = None
    for k in range(i + 1, min(n, i + 1 + F['max_hold'])):
        if use_tgt and h[k] >= tgt:
            ex = (k, max(tgt, o[k]) if k > i + 1 else tgt, 'target'); break
        if c[k] < stop:
            if k + 1 < n: ex = (k + 1, o[k + 1], 'stop')
            else: ex = (k, c[k], 'stop(open)')
            break
    if ex is None:
        k = min(n - 1, i + F['max_hold']); ex = (k, c[k], 'time' if k == i + F['max_hold'] else 'open')
    cost_r = 2 * F['slip'] * entry / risk + 2 * F['comm'] / F['risk_usd']
    r = (ex[1] - entry) / risk - cost_r
    return dict(sig=B['d'][i], entry_d=B['d'][i + 1], entry=round(float(entry), 4), stop=round(float(stop), 4),
                target=round(float(tgt), 4) if use_tgt else None, exit_d=B['d'][ex[0]], exit=round(float(ex[1]), 4),
                why=ex[2], r=round(float(r), 3), ret=round(float(ex[1] / entry - 1), 4), bars=ex[0] - i - 1,
                risk_pct=round(float(risk / entry), 4), cost_r=round(float(cost_r), 3), exit_i=ex[0], sig_i=i)


def signals(B, S):
    """Edge-triggered, non-overlapping trades."""
    out = []; busy_until = -1
    for i in range(1, len(B['c']) - 1):
        if S['all4'][i] and not S['all4'][i - 1] and i > busy_until:
            t = trade_from(B, S, i)
            if t: out.append(t); busy_until = t['exit_i']
    return out
