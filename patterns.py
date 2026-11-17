"""几种形态的识别：头肩（底）、收敛三角、三驱、五浪推进、大振幅 K 线。给录屏里的各个模型共用。

全部在“工作方向”的价格上找（做空时价格取负，见 qmodel.py）：这里只认“底部”那一种朝向，
做多时找到的是头肩底、向上突破的三角、往下砸的三驱；做空时同一段代码找到的就是头肩顶、向下突破的三角、往上冲的三驱。
只用已经确认的摆动点（houshou.prepare 的 zigzag），外加一个还没确认的极值（pending），所以全部是因果的。
参数全部是估算（录屏没给），写在 EST 里；参考过的开源写法见各个模型文件的 REFS。
"""
import numpy as np

import houshou as hs
import indicators as ind
import qmodel as qm

EST = dict(hs_sym=0.6,        # 头肩：两肩低点相差不超过头部深度的 60%
           hs_time=2.5,       # 头肩：左肩到头、头到右肩，两段的根数相差不超过 2.5 倍（neurotrader888 的写法）
           hs_age=60,         # 头肩：右肩之后最多跟踪 60 根
           tri_min=4,         # 三角：至少 4 个摆动点（两高两低）
           big_atr=2.5,       # 大振幅：当根振幅 ≥ 2.5 个 ATR
           big_look=40)       # 大振幅：只在最近 40 根里找
EST_NOTE = dict(hs_sym='两肩的低点最多相差头部深度的多少', hs_time='左右两半的根数最多相差几倍', hs_age='右肩之后最多跟踪多少根', tri_min='三角最少几个摆动点',
                big_atr='大阴大阳：振幅至少几个 ATR', big_look='大阴大阳只在最近多少根里找')


def atr(P, j):
    a = P['atr'][j]
    return float(a) if np.isfinite(a) else abs(float(P['c'][j])) * 0.03


def line(p1, p2):
    """The straight line through two (bar, price) points, as a function of the bar."""
    (i1, v1), (i2, v2) = p1, p2
    k = (v2 - v1) / (i2 - i1) if i2 != i1 else 0.0
    return lambda t: v1 + k * (t - i1), k


def first_close_above(P, f, a, j):
    """First bar t in (a, j] whose close is above f(t), or None."""
    c = P['c']
    for t in range(a + 1, j + 1):
        if c[t] > f(t):
            return t
    return None


def vol_ratio(P, t, n=5):
    """Volume of bar t divided by the mean of the n bars before it."""
    v = P['v']
    a = max(0, t - n)
    m = float(v[a:t].mean()) if t > a else 0.0
    return float(v[t]) / m if m > 0 else None


def head_shoulders(P, j, look=250, age=None):
    """头肩底（工作方向）：左肩 L1、颈线点 H1、头 L2（最低）、颈线点 H2、右肩 L3。右肩可以是还没确认的低点。
    返回 dict 或 None：points, neck(t)（颈线在第 t 根的值）, depth（头到颈线的距离）, brk（第一根收盘站上颈线的 K 线）, rs_pending。"""
    age = age or EST['hs_age']
    piv = qm.pivots(P, j, max(0, j - look))
    pend = qm.pending(P, j)
    cands = []
    if pend and pend[2] == -1 and len(piv) >= 4 and piv[-1][2] == 1:
        cands.append((piv[-4:] + [pend], True))
    for m in range(len(piv) - 1, max(3, len(piv) - 8), -1):
        if piv[m][2] == -1 and m >= 4:
            cands.append((piv[m - 4:m + 1], False))
    for seq, pending in cands:
        L1, H1, L2, H2, L3 = seq
        if [x[2] for x in seq] != [-1, 1, -1, 1, -1] or j - L3[0] > age:
            continue
        if not (L2[1] < L1[1] and L2[1] < L3[1]):
            continue
        ta, tb = L2[0] - L1[0], max(1, L3[0] - L2[0])
        if max(ta, tb) > EST['hs_time'] * max(1, min(ta, tb)):     # 左右两半在时间上差太多，不像一个头肩
            continue
        neck, k = line((H1[0], H1[1]), (H2[0], H2[1]))
        depth = neck(L2[0]) - L2[1]
        if depth <= 0 or abs(L1[1] - L3[1]) > EST['hs_sym'] * depth or L1[1] >= neck(L1[0]) or L3[1] >= neck(L3[0]):
            continue
        if float(P['l'][L3[0]:j + 1].min()) < L2[1]:          # 右肩之后跌破了头：形态不成立
            continue
        brk = None if pending else first_close_above(P, neck, L3[0], j)
        return dict(L1=L1, H1=H1, L2=L2, H2=H2, L3=L3, neck=neck, slope=k, depth=depth, brk=brk, rs_pending=pending)
    return None


def triangle(P, j, look=250):
    """收敛三角（工作方向，向上突破那一种）：一串交替的摆动点，高点一个比一个低、低点一个比一个高，至少 tri_min 个。
    上沿连第一个和最后一个高点，下沿连第一个和最后一个低点。返回 dict 或 None：pts, upper(t), lower(t), height（开口高度）, last（最后一个摆动点的 K 线）, brk。"""
    piv = qm.pivots(P, j, max(0, j - look))
    for e in range(len(piv) - 1, max(-1, len(piv) - 6), -1):
        for k in (6, 5, 4):
            if k < EST['tri_min'] or e - k + 1 < 0:
                continue
            seq = piv[e - k + 1:e + 1]
            hi = [x for x in seq if x[2] == 1]
            lo = [x for x in seq if x[2] == -1]
            if len(hi) < 2 or len(lo) < 2:
                continue
            if any(b[1] >= a[1] for a, b in zip(hi, hi[1:])) or any(b[1] <= a[1] for a, b in zip(lo, lo[1:])):
                continue
            up, ku = line((hi[0][0], hi[0][1]), (hi[-1][0], hi[-1][1]))
            dn_, kd = line((lo[0][0], lo[0][1]), (lo[-1][0], lo[-1][1]))
            if ku >= kd:
                continue
            first = seq[0][0]
            height = up(first) - dn_(first)
            if height <= 0:
                continue
            last = seq[-1][0]
            return dict(pts=seq, highs=hi, lows=lo, upper=up, lower=dn_, height=height, first=first, last=last, brk=first_close_above(P, up, last, j))
    return None


def three_drives(P, j, look=250):
    """三驱（工作方向，往下砸三下那一种）：低点 D1 > D2 > D3，中间夹着反弹高点 R1、R2。D3 可以是还没确认的低点。
    返回 dict 或 None：D1, R1, D2, R2, D3（各是 (bar, price, kind)）, d3_pending。"""
    piv = qm.pivots(P, j, max(0, j - look))
    pend = qm.pending(P, j)
    if pend and pend[2] == -1 and len(piv) >= 4 and piv[-1][2] == 1:
        seq, pending = piv[-4:] + [pend], True
    elif pend and pend[2] == 1 and len(piv) >= 5 and piv[-1][2] == -1:
        seq, pending = piv[-5:], False
    else:
        return None
    D1, R1, D2, R2, D3 = seq
    if [x[2] for x in seq] != [-1, 1, -1, 1, -1] or not (D1[1] > D2[1] > D3[1]):
        return None
    return dict(D1=D1, R1=R1, D2=D2, R2=R2, D3=D3, d3_pending=pending)


def impulse(P, j, look=250):
    """五浪推进（工作方向，往上那一种）：P0 起点（低）、P1 一浪顶、P2 二浪底、P3 三浪顶、P4 四浪底，现在在五浪里（还没确认的高点）。
    艾略特的三条硬规矩：二浪不破一浪起点，三浪不是最短（和一浪比），四浪不碰一浪顶（这一条单独判断，不在这里过滤）。返回 dict 或 None。"""
    piv = qm.pivots(P, j, max(0, j - look))
    pend = qm.pending(P, j)
    if not (pend and pend[2] == 1 and len(piv) >= 5 and piv[-1][2] == -1):
        return None
    P0, P1, P2, P3, P4 = piv[-5:]
    if [x[2] for x in (P0, P1, P2, P3, P4)] != [-1, 1, -1, 1, -1]:
        return None
    if not (P2[1] > P0[1] and P3[1] > P1[1] and (P3[1] - P2[1]) >= (P1[1] - P0[1])):
        return None
    return dict(P0=P0, P1=P1, P2=P2, P3=P3, P4=P4, P5=pend)


def big_bar(P, j, k=None, look=None):
    """最近 look 根里振幅最大、而且 ≥ k 个 ATR 的那根 K 线（ATR 用它前一根的值），没有就 None。返回 (bar, 振幅是 ATR 的几倍)。"""
    k, look = k or EST['big_atr'], look or EST['big_look']
    h, l, a = P['h'], P['l'], P['atr']
    best = None
    for t in range(max(1, j - look + 1), j + 1):
        ref = a[t - 1]
        if not np.isfinite(ref) or ref <= 0:
            continue
        m = float(h[t] - l[t]) / float(ref)
        if m >= k and (best is None or m > best[1]):
            best = (t, m)
    return best


def poc(P, a, b, bins=24):
    """成交量分布（量山）最厚的那个价位，工作方向。"""
    return ind.volume_profile(P['h'], P['l'], P['v'], a, b, bins)['poc']


def avwap(P, a, j):
    return hs.avwap(P, a, j)[0]
