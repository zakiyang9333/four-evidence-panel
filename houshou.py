#!/usr/bin/env python3
"""后手·成本线回踩 规则引擎 houshou-0.1（APP_ADDENDUM_QUANT_AI.md §3）。日线，因果，未回测。

把 TradingVane 第二段录屏（量化AI | 后手战法 | 量化对抗量化）的五条总结写成代码，只用于观察，不是买卖依据。
用法：
  python3 houshou.py NVDA QQQ SPCX [QQQI] [--json] [--asof YYYY-MM-DD]
                     [--anchor TICKER,YYYY-MM-DD] [--bar TICKER,DATE,O,H,L,C,V] [--refresh]
  --anchor   手动指定成本锚点（横盘第一根）；不给就用 data/houshou_anchor.json 里存的，再没有就自动找【估算】
  --bar      加入/替换一根已核实的最新 K 线，可重复
  --refresh  先运行 prep_data.py（只追加新日期）
  QQQI 没有可用历史，按 QQQ 读（代理）。

- 输入和 engine.load() 一样的日线数组（d, o, h, l, c, v）。engine.py 不动，这里不引用它的规则。
- 全部因果：第 i 根上的任何判断只用 ≤ i 的数据。摆动点要等反向走完阈值才算确认，没确认的那个极值单独标 pending。
- VIDEO 是视频里说了的数；EST 是视频没给、这里自己定的数，全部【估算】，界面上照样标出来。
- 美股没有涨停和 T+1，不做涨停相关逻辑。

注意：面板（quant.py / structure.py / chart_score.py / server.py）引用这个文件的 prepare、compute、evaluate、history、swings、
avwap_series、NAME、EST、EST_NOTE、r2 等接口。2026-11-16 15:47 这个文件被别的线程整份换成过另一套接口，面板因此起不来；
zaki 当天定了以这一份为准（那一份留在 wip_quant/houshou_other_thread_1547.py，它的命令行选项这里都保留了）。
要改接口请先和面板这边对一下，不要整份替换。
"""
import sys, os, json, bisect, subprocess
import numpy as np

VERSION = 'houshou-0.1'
NAME = '后手·成本线回踩 v0.1'
PROXY = {'QQQI': 'QQQ'}

VIDEO = dict(far=0.15,        # 离成本线 >15% 不追
             abcd_tol=0.15,   # 两段跌幅相差 <15%
             dry=0.5,         # 量缩到下跌段一半以下
             stop=0.02)       # 止损 = D 点下方 2%
EST = dict(                   # 以下全部【估算】，视频未给
    zz_min=0.05, zz_atr=2.0,  # 摆动点反转阈值 = max(5%, 2×ATR14/收盘)
    atr_n=14,                 # ATR 的根数
    top_win=250,              # 只在最近 250 根里找这一轮的最高点
    base_min=15, base_band=0.10,  # 横盘 = 起涨前至少 15 根、收盘都在中位数 ±10% 内
    climax_win=60,            # 天量 = 60 根内最大量（和四证的地量对称）
    shadow=0.5,               # 长上影 = 上影 ≥ 整根振幅的一半
    touch=0.02,               # 回到成本线 = 最低价进入 AVWAP 的 −3% ~ +2% 区间
    touch_low=0.03,
    zone=0.01,                # 建仓区 = AVWAP ±1%
    sr_tol=0.01, sr_win=250,  # 支撑/压力触碰容差 1%，回看 250 根
    hist_hold=20)             # 历史触发往后看 20 根：先到目标还是先破止损

EST_NOTE = dict(
    zz_min='摆动点最小反转幅度', zz_atr='摆动点反转幅度的 ATR 倍数', atr_n='ATR 根数', top_win='找本轮最高点的回看根数',
    base_min='横盘最少根数', base_band='横盘收盘价离中位数的最大偏离', climax_win='天量的回看根数', shadow='长上影占整根振幅的比例',
    touch='回到成本线：最低价最多高出成本线', touch_low='回到成本线：最低价最多低于成本线', zone='建仓区离成本线的宽度',
    sr_tol='支撑/压力的触碰容差', sr_win='支撑/压力的回看根数', hist_hold='历史触发往后看的根数')

ROOT = os.path.dirname(os.path.abspath(__file__))


def r2(x):
    return None if x is None or not np.isfinite(x) else round(float(x), 2)


def pct(x, nd=1):
    return None if x is None or not np.isfinite(x) else round(float(x) * 100, nd)


def vol_text(x):
    x = float(x)
    return f'{x / 1e8:.2f} 亿' if x >= 1e8 else f'{x / 1e4:.0f} 万'


# ---------- one causal pass over the bars ----------

def prepare(B):
    """ATR, swing points (zigzag) and running sums. Every value at bar j uses bars ≤ j only."""
    d = list(B['d'])
    o, h, l, c, v = (np.asarray(B[k], dtype=float) for k in 'ohlcv')
    n = len(c)
    N = EST['atr_n']
    atr = np.full(n, np.nan)
    if n:
        pc = np.concatenate(([c[0]], c[:-1]))
        tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
        cs = np.concatenate(([0.0], np.cumsum(tr)))
        if n >= N:
            atr[N - 1:] = (cs[N:] - cs[:-N]) / N
    thr = np.where(np.isfinite(atr), np.maximum(EST['zz_min'], EST['zz_atr'] * atr / np.where(c > 0, c, 1)), EST['zz_min'])

    H, L, T = h.tolist(), l.tolist(), thr.tolist()
    pi, pp, pk, pat = [], [], [], []            # pivot bar, price, kind (+1 high / −1 low), bar where it got confirmed
    pend_k, pend_i = [0] * n, [-1] * n          # the unconfirmed extreme as seen at each bar
    dirn, hi, lo = 0, 0, 0
    for j in range(n):
        if dirn == 0:
            if H[j] > H[hi]: hi = j
            if L[j] < L[lo]: lo = j
            if hi < j and L[j] <= H[hi] * (1 - T[j]):
                pi.append(hi); pp.append(H[hi]); pk.append(1); pat.append(j); dirn = -1
                lo = min(range(hi + 1, j + 1), key=L.__getitem__)
            elif lo < j and H[j] >= L[lo] * (1 + T[j]):
                pi.append(lo); pp.append(L[lo]); pk.append(-1); pat.append(j); dirn = 1
                hi = max(range(lo + 1, j + 1), key=H.__getitem__)
        elif dirn == 1:
            if H[j] > H[hi]:
                hi = j
            elif L[j] <= H[hi] * (1 - T[j]):
                pi.append(hi); pp.append(H[hi]); pk.append(1); pat.append(j); dirn = -1
                lo = min(range(hi + 1, j + 1), key=L.__getitem__)
        else:
            if L[j] < L[lo]:
                lo = j
            elif H[j] >= L[lo] * (1 + T[j]):
                pi.append(lo); pp.append(L[lo]); pk.append(-1); pat.append(j); dirn = 1
                hi = max(range(lo + 1, j + 1), key=H.__getitem__)
        pend_k[j] = dirn
        pend_i[j] = hi if dirn == 1 else lo if dirn == -1 else -1

    tp = (h + l + c) / 3
    z = lambda a: np.concatenate(([0.0], np.cumsum(a)))
    return dict(d=d, o=o, h=h, l=l, c=c, v=v, n=n, atr=atr, thr=thr, pi=pi, pp=pp, pk=pk, pat=pat, pend_k=pend_k, pend_i=pend_i,
                CV=z(v), CTV=z(tp * v), CT2V=z(tp * tp * v), tp=tp, memo={}, base={}, hist={})


def swings(P, i):
    """Confirmed swing points as seen at bar i, oldest first, plus the unconfirmed extreme."""
    k = bisect.bisect_right(P['pat'], i)
    conf = [dict(i=P['pi'][m], date=P['d'][P['pi'][m]], price=r2(P['pp'][m]), kind='high' if P['pk'][m] == 1 else 'low', confirmed=P['d'][P['pat'][m]])
            for m in range(k)]
    pend = None
    if P['n'] and P['pend_k'][i]:
        q = P['pend_i'][i]
        pend = dict(i=q, date=P['d'][q], price=r2(P['h'][q] if P['pend_k'][i] == 1 else P['l'][q]), kind='high' if P['pend_k'][i] == 1 else 'low')
    return conf, pend


def avwap(P, a, j):
    """Volume-weighted average of the typical price from bar a to bar j, and its volume-weighted standard deviation."""
    w = P['CV'][j + 1] - P['CV'][a]
    if w <= 0:
        return float(P['tp'][j]), 0.0
    m = (P['CTV'][j + 1] - P['CTV'][a]) / w
    var = (P['CT2V'][j + 1] - P['CT2V'][a]) / w - m * m
    return float(m), float(np.sqrt(max(var, 0.0)))


def avwap_series(P, a, j):
    """The cost line and its ±1σ band from the anchor to bar j, for drawing."""
    w = P['CV'][a + 1:j + 2] - P['CV'][a]
    w = np.where(w > 0, w, np.nan)
    m = (P['CTV'][a + 1:j + 2] - P['CTV'][a]) / w
    sd = np.sqrt(np.maximum((P['CT2V'][a + 1:j + 2] - P['CT2V'][a]) / w - m * m, 0))
    f = lambda x: [None if not np.isfinite(y) else round(float(y), 4) for y in x]
    return dict(d=P['d'][a:j + 1], v=f(m), sd=f(sd))


def _base(P, L0, e):
    """Start of the longest sideways stretch that ends at bar e and contains the lift-off low L0, or None.
    Sideways = at least base_min bars whose closes all sit within ±base_band of their median."""
    key = (L0, e)
    if key in P['base']:
        return P['base'][key]
    c, band, lim = P['c'], EST['base_band'], (1 + EST['base_band']) / (1 - EST['base_band'])
    srt, best = [], None
    lo = hi = float(c[e])
    for s in range(e, max(-1, e - EST['top_win']), -1):
        x = float(c[s])
        bisect.insort(srt, x)
        lo, hi = min(lo, x), max(hi, x)
        if hi > lo * lim:           # 再往前加只会更宽，不可能再满足
            break
        k = len(srt)
        if s <= L0 and k >= EST['base_min']:
            med = srt[k // 2] if k % 2 else (srt[k // 2 - 1] + srt[k // 2]) / 2
            if lo >= med * (1 - band) and hi <= med * (1 + band):
                best = s
    P['base'][key] = best
    return best


# ---------- the rules at one bar ----------

def _core(P, j, am):
    """Everything the rules say at bar j, from bars ≤ j. am = index of a manual cost anchor, or None."""
    memo = P['memo'].setdefault(am, {})
    if j in memo:
        return memo[j]
    d, o, h, l, c, v = P['d'], P['o'], P['h'], P['l'], P['c'], P['v']
    pi, pp, pk, pat = P['pi'], P['pp'], P['pk'], P['pat']
    k = bisect.bisect_right(pat, j)                    # 到第 j 根为止已确认的摆动点个数
    win0 = max(0, j - EST['top_win'] + 1) if am is None else am
    out = dict(phase='无结构', verdict='不适用', list=None, checks=[], missing=[], next_needs=[], note='', anchor=None, avwap=None, sd=None,
               dist_pct=None, pushes=[], abcd=None, zone=None, mid=None, stop=None, t1=None, rr=None, base=None, start_low=None, top=None,
               _A=None, _Aat=None, _all3=False)

    # 这一轮的最高点：窗口里最高的已确认高点，或者还没确认、但已经更高的那个高点
    T = None
    for m in range(k - 1, -1, -1):
        if pi[m] < win0:
            break
        if pk[m] == 1 and (T is None or pp[m] > T[1]):
            T = (pi[m], pp[m], m)
    if P['pend_k'][j] == 1 and P['pend_i'][j] >= win0:
        q = P['pend_i'][j]
        if T is None or h[q] >= T[1]:
            T = (q, float(h[q]), None)
    if T is None:
        out['note'] = '最近 %d 根里没有已确认的高点，谈不上三冲。' % EST['top_win'] if am is None else '手动锚点之后还没有出现高点。'
        memo[j] = out
        return out
    Ti, Tp, Tm = T
    end = Tm if Tm is not None else k                  # 最高点之前的摆动点是 [0, end)

    # 起涨低点：从最高点往回走，低点一个比一个低就继续，遇到更高的低点就停
    cur = None
    for m in range(end - 1, -1, -1):
        if pk[m] != -1:
            continue
        if pi[m] < win0:
            break
        if cur is None or pp[m] < pp[cur]:
            cur = m
        else:
            break
    if cur is not None:
        L0 = pi[cur]
    elif Ti > win0:
        L0 = win0 + int(np.argmin(l[win0:Ti]))
    else:
        out['note'] = '最高点之前没有可用的起涨段。'
        memo[j] = out
        return out
    out['start_low'] = dict(date=d[L0], price=r2(l[L0]))
    out['top'] = dict(date=d[Ti], price=r2(Tp), pending=Tm is None)

    # 冲：起涨之后依次创新高的高点。每一冲的兵力 = 这一冲上涨段（前一个低点到高点，不含高点当根）的平均成交量
    raw, run = [], -np.inf
    for m in range((cur + 1) if cur is not None else bisect.bisect_right(pi, L0), end + (1 if Tm is not None else 0)):
        if pk[m] == 1 and pi[m] > L0 and pp[m] > run:
            run = pp[m]
            lowi = pi[m - 1] if m > 0 and pk[m - 1] == -1 and pi[m - 1] >= L0 else L0
            raw.append((pi[m], pp[m], lowi, False))
    if Tm is None:
        lowi = pi[k - 1] if k > 0 and pk[k - 1] == -1 and pi[k - 1] >= L0 else L0
        raw.append((Ti, Tp, lowi, True))
    force = [float(v[a:b].mean()) if b > a else float(v[b]) for b, _, a, _ in raw]
    use = list(range(len(raw)))[-3:]                   # 超过三冲时看最后三冲【估算】
    f0 = force[use[0]] if use else None
    pushes = [dict(n=x + 1, date=d[raw[x][0]], price=r2(raw[x][1]), from_low=d[raw[x][2]], force=round(force[x]), pending=raw[x][3],
                   force_pct=round(force[x] / f0 * 100) if x in use and f0 else None, slot=use.index(x) + 1 if x in use and len(use) == 3 else None)
              for x in range(len(raw))]
    out['pushes'] = pushes

    # 成本锚点：手动的优先；否则找包含起涨低点、在第一冲之前结束的最长横盘段，锚点是它的第一根
    if am is not None:
        a, by, note = am, 'manual', ''
    else:
        best = None
        for e in range(L0, raw[0][0]):
            s = _base(P, L0, e)
            if s is not None and (best is None or e - s > best[1] - best[0]):
                best = (s, e)
        if best:
            a, by, note = best[0], 'auto', f'横盘 {best[1] - best[0] + 1} 根（{d[best[0]]} 至 {d[best[1]]}），锚在第一根'
            out['base'] = dict(start=d[best[0]], end=d[best[1]], bars=best[1] - best[0] + 1)
        else:
            a, by, note = L0, 'auto', '未找到横盘，用起涨低点代替【估算】'
    av, sd = avwap(P, a, j)
    dist = float(c[j]) / av - 1
    out.update(anchor=dict(date=d[a], by=by, note=note), avwap=r2(av), sd=r2(sd), dist_pct=pct(dist))

    cj, far = float(c[j]), VIDEO['far']
    npush = len(raw)
    if Tm is None:      # ---- 拉升中：不追清单 ----
        a1 = dist > far
        checks = [dict(k='A1', name='离成本太远', ok=bool(a1),
                       why=f'收盘 {r2(cj)} 比成本线 {r2(av)} 高 {pct(dist)}%，' + ('超过' if a1 else '没到') + f' {int(far * 100)}%')]
        if npush >= 3:
            f1, f2, f3 = (force[x] for x in use)
            a2 = f1 > f2 > f3
            bar = raw[use[2]][0]
            rng = float(h[bar] - l[bar])
            sh = float(h[bar] - max(o[bar], c[bar])) / rng if rng > 0 else 0.0
            w0 = max(0, bar - EST['climax_win'] + 1)
            climax = bool(v[bar] >= v[w0:bar + 1].max())
            a3 = climax and sh >= EST['shadow']
            checks.append(dict(k='A2', name='冲第三次', ok=bool(a2),
                               why=f'已经是第 {npush} 冲。最近三冲的兵力（上涨段日均量）{vol_text(f1)} → {vol_text(f2)} → {vol_text(f3)}，' +
                                   ('一次比一次少' if a2 else '不是一次比一次少')))
            checks.append(dict(k='A3', name='天量长上影', ok=bool(a3),
                               why=f'最高那根（{d[bar]}）成交量 {vol_text(v[bar])}，' + (f'是近 {EST["climax_win"]} 根最大' if climax else f'不是近 {EST["climax_win"]} 根最大') +
                                   f'；上影占整根 {round(sh * 100)}%，' + ('够长' if sh >= EST['shadow'] else f'不到 {int(EST["shadow"] * 100)}%')))
        else:
            a2 = a3 = False
            checks.append(dict(k='A2', name='冲第三次', ok=False, why=f'才第 {npush} 冲，还没到第三冲'))
            checks.append(dict(k='A3', name='天量长上影', ok=False, why='还没有第三冲，谈不上'))
        verdict = '不追·出货区' if a1 and a2 and a3 else '不追' if a1 else '出货区' if a2 and a3 else '还能看'
        need = []
        if a1:
            need.append(f'收盘回到 {r2(av * (1 + far))} 以下（成本线上方 {int(far * 100)}%），才不算离成本太远')
        else:
            need.append(f'收盘超过 {r2(av * (1 + far))}（成本线上方 {int(far * 100)}%）就算离成本太远，不追')
        out.update(phase='拉升中', verdict=verdict, list='chase', checks=checks, next_needs=need,
                   missing=[x['name'] + '：' + x['why'] for x in checks if not x['ok']])
        memo[j] = out
        return out

    if npush < 3:       # ---- 最高点已经确认，但这一轮不够三冲 ----
        out['note'] = f'这一轮上涨到 {d[Ti]} 的高点只有 {npush} 冲，不是三冲结构，后手清单不适用。'
        memo[j] = out
        return out

    # ---- 回落中：后手清单。A = 第三冲高点，B = 其后第一个确认低点，C = B 之后最高的确认高点，D = C 之后的最低点（可以是当根）----
    Bm = Cm = None
    for m in range(Tm + 1, k):
        if pk[m] == -1 and Bm is None:
            Bm = m
        elif pk[m] == 1 and Bm is not None and (Cm is None or pp[m] > pp[Cm]):
            Cm = m
    Ap = float(Tp)
    pts = dict(A=dict(date=d[Ti], price=r2(Ap)), B=None, C=None, D=None, ab_pct=None, cd_pct=None)
    down = list(range(Ti + 1, (pi[Bm] if Bm is not None else j) + 1))       # 下跌段的 K 线
    Di = None
    if Bm is None:
        Di = Ti + 1 + int(np.argmin(l[Ti + 1:j + 1]))
        pts['D'] = dict(date=d[Di], price=r2(l[Di]), provisional=True)
    else:
        pts['B'] = dict(date=d[pi[Bm]], price=r2(pp[Bm]))
        pts['ab_pct'] = pct((Ap - pp[Bm]) / Ap)
        if Cm is not None:
            Ci = pi[Cm]
            Di = Ci + 1 + int(np.argmin(l[Ci + 1:j + 1]))
            pts['C'] = dict(date=d[Ci], price=r2(pp[Cm]))
            pts['D'] = dict(date=d[Di], price=r2(l[Di]), is_today=Di == j)
            pts['cd_pct'] = pct((pp[Cm] - float(l[Di])) / pp[Cm])
            down += list(range(Ci + 1, Di + 1))
    zlo, zhi = av * (1 - EST['touch_low']), av * (1 + EST['touch'])
    if Di is None:
        b1, why1 = False, f'B 点之后还在反弹，第二段下跌没开始；成本线在 {r2(av)}'
    else:
        Dl = float(l[Di])
        b1 = zlo <= Dl <= zhi
        why1 = (f'这段下跌的最低点 {r2(Dl)}（{d[Di]}）' + ('落在' if b1 else '高于' if Dl > zhi else '低于') +
                f'成本线 {r2(av)} 的 −{int(EST["touch_low"] * 100)}% ~ +{int(EST["touch"] * 100)}% 区间（{r2(zlo)} ~ {r2(zhi)}）')
    if Bm is None:
        b2, why2 = False, '第一段下跌还没走完（B 点没确认），比不了两段'
    elif Cm is None:
        b2, why2 = False, f'第一段跌了 {pts["ab_pct"]}%，反弹还没走完（C 点没确认），第二段没开始'
    else:
        ab, cd = (Ap - pp[Bm]) / Ap, (pp[Cm] - float(l[Di])) / pp[Cm]
        b2 = abs(cd / ab - 1) < VIDEO['abcd_tol']
        why2 = f'第一段跌 {pct(ab)}%，第二段跌 {pct(cd)}%，' + ('相差不到' if b2 else '相差超过') + f' {int(VIDEO["abcd_tol"] * 100)}%'
    legs = [x for x in down if x != j]
    base_v = float(v[legs].mean()) if legs else None
    pierce = bool(l[j] < av and cj > av)
    dry = base_v is not None and float(v[j]) <= VIDEO['dry'] * base_v
    b3 = pierce and dry
    why3 = (('盘中跌破成本线又收回' if pierce else '收盘在成本线下方，没收回' if cj <= av else '盘中没有跌破成本线') + f'（最低 {r2(l[j])}，收 {r2(cj)}，线 {r2(av)}）；' +
            (f'成交量 {vol_text(v[j])}，是下跌段日均 {vol_text(base_v)} 的 {round(float(v[j]) / base_v * 100)}%，' + ('缩到一半以下' if dry else '没缩到一半') if base_v else '下跌段还没有可比的成交量'))
    checks = [dict(k='B1', name='回到成本线', ok=bool(b1), why=why1), dict(k='B2', name='AB=CD', ok=bool(b2), why=why2),
              dict(k='B3', name='缩量刺破收回', ok=bool(b3), why=why3)]
    need = []
    if not b1:
        need.append(f'最低价要落到 {r2(zlo)} ~ {r2(zhi)} 之间（按现在的成本线，会随成交略微移动）')
    if not b2 and Bm is not None and Cm is not None:
        ab = (Ap - pp[Bm]) / Ap
        need.append(f'第二段的最低点要在 {r2(pp[Cm] * (1 - ab * (1 + VIDEO["abcd_tol"])))} ~ {r2(pp[Cm] * (1 - ab * (1 - VIDEO["abcd_tol"])))} 之间，两段才算等长')
    if not b3:
        need.append(f'盘中跌破 {r2(av)} 又收回到它上方' + (f'，而且成交量不超过 {vol_text(VIDEO["dry"] * base_v)}' if base_v else ''))
    all3 = b1 and b2 and b3
    out.update(phase='回落中', verdict='下后手' if all3 else '等', list='houshou', checks=checks, abcd=pts, next_needs=need,
               missing=[x['name'] + '：' + x['why'] for x in checks if not x['ok']], _A=Ti, _Aat=pat[Tm], _all3=bool(all3))
    if all3:
        z1, z2, stop = av * (1 - EST['zone']), av * (1 + EST['zone']), float(l[Di]) * (1 - VIDEO['stop'])
        out.update(zone=[r2(z1), r2(z2)], mid=r2(av), stop=r2(stop), t1=r2(Ap), rr=r2((Ap - av) / (av - stop)) if av > stop else None)
        out['_stop'] = stop
    memo[j] = out
    return out


def _am_at(am, j):
    return am if am is not None and j >= am else None


def evaluate(P, j, am=None):
    """_core plus the one thing that needs earlier bars' results: a structure that already triggered and then closed below its stop is dead."""
    r = dict(_core(P, j, _am_at(am, j)))
    if r['phase'] == '回落中':
        for q in range(r['_Aat'], j):
            rq = _core(P, q, _am_at(am, q))
            if rq['_A'] == r['_A'] and rq['_all3']:
                broke = next((x for x in range(q + 1, j + 1) if P['c'][x] < rq['_stop']), None)
                if broke is not None:
                    r.update(phase='已失效', verdict='已失效', zone=None, mid=None, stop=None, t1=None, rr=None, next_needs=[],
                             note=f'{P["d"][q]} 条件齐过一次，{P["d"][broke]} 收盘跌破了当时的止损 {r2(rq["_stop"])}，这个结构作废。')
                break
    return r


def history(P, i, am=None):
    """Replay the same code bar by bar: every past 3/3, and what came first in the next hist_hold bars (seen from bar i, no later data)."""
    st = P['hist'].setdefault(am, dict(upto=-1, rows=[], fall=[], B1=[], B2=[], B3=[], two=[]))
    for j in range(st['upto'] + 1, i + 1):
        r = evaluate(P, j, am)
        if r['list'] == 'houshou':          # 回落中或已失效：记下每一项单独成立过多少根，3/3 是 0 的时候能看出卡在哪一项
            st['fall'].append(j)
            oks = [x['k'] for x in r['checks'] if x['ok']]
            for x in oks:
                st[x].append(j)
            if len(oks) >= 2:
                st['two'].append(j)
        if r['phase'] == '回落中' and r['verdict'] == '下后手':
            st['rows'].append((j, r['mid'], r['stop'], r['t1'], r['abcd']['A']['date']))
    st['upto'] = max(st['upto'], i)
    rows, hold = [], EST['hist_hold']
    for j, mid, stop, t1, adate in st['rows']:
        if j > i:
            break
        res, when = None, None
        for x in range(j + 1, min(j + hold, i) + 1):
            if P['c'][x] < stop:
                res, when = 'stop', x
                break
            if P['h'][x] >= t1:
                res, when = 'target', x
                break
        if res is None:
            res = 'none' if j + hold <= i else 'open'
        rows.append(dict(date=P['d'][j], mid=mid, stop=stop, t1=t1, top_date=adate, outcome=res, outcome_date=P['d'][when] if when is not None else None,
                         bars=(when - j) if when is not None else None))
    cnt = lambda k: bisect.bisect_right(st[k], i)
    return dict(n=len(rows), rows=rows, hold=hold, note='样本数 %d，未做对照检验' % len(rows),
                stats=dict(bars=i + 1, fall=cnt('fall'), B1=cnt('B1'), B2=cnt('B2'), B3=cnt('B3'), two_of_three=cnt('two')))


def compute(B, i=None, anchor_date=None, with_history=True, P=None):
    """The public result at bar i (default: the last bar). anchor_date = manual cost anchor (ignored on dates before it)."""
    P = P or prepare(B)
    n = P['n']
    i = n - 1 if i is None else int(i)
    am = None
    if anchor_date and anchor_date in P['d']:
        am = P['d'].index(anchor_date)
        if am > i:
            am = None
    r = evaluate(P, i, am)
    res = {k: x for k, x in r.items() if not k.startswith('_')}
    res.update(model=VERSION, name=NAME, asof=P['d'][i], index=i, close=r2(P['c'][i]), t2=None, t2_note='视频未说明',
               params=dict(video=VIDEO, est=EST), anchor_index=P['d'].index(r['anchor']['date']) if r['anchor'] else None)
    if with_history:
        res['history'] = history(P, i, am)
    return res


# ---------- command line ----------

def read_anchors():
    try:
        with open(os.path.join(os.environ.get('FE_DATA_DIR') or os.path.join(ROOT, 'data'), 'houshou_anchor.json'), encoding='utf-8') as f:
            x = json.load(f)
        return x if isinstance(x, dict) else {}
    except (OSError, ValueError):
        return {}


def text_block(t, r):
    px = PROXY.get(t)
    L = [f'【后手检查】{t}{"（代理 " + px + "）" if px else ""} · {r["asof"]} 收盘 {r["close"]}：{r["phase"]} → {r["verdict"]}  [{NAME}]']
    if r['anchor']:
        L.append(f'  成本线（锚定 VWAP，锚 {r["anchor"]["date"]}，{"手动" if r["anchor"]["by"] == "manual" else "自动"}' +
                 (f'，{r["anchor"]["note"]}' if r['anchor']['note'] else '') + f'）{r["avwap"]}，现价离它 {r["dist_pct"]:+}%；不追线 {r2(r["avwap"] * (1 + VIDEO["far"]))}')
    if r['pushes']:
        L.append('  冲高：' + '；'.join(f'第{p["n"]}冲 {p["date"]} {p["price"]}' + ('（未确认）' if p['pending'] else '') + f'（兵力 {vol_text(p["force"])}）' for p in r['pushes'][-3:]))
    if r['list']:
        L.append('  ' + ('不追清单' if r['list'] == 'chase' else '后手清单') + f' {sum(c["ok"] for c in r["checks"])}/{len(r["checks"])}')
        for c in r['checks']:
            L.append(f'    [{"x" if c["ok"] else " "}] {c["k"]} {c["name"]}：{c["why"]}')
    if r['zone']:
        L.append(f'  建仓区 {r["zone"][0]} ~ {r["zone"][1]}；止损（D 点下 2%，手动）{r["stop"]}；第一目标 {r["t1"]}；盈亏比 {r["rr"]}；第二目标：视频未说明')
    for x in r['next_needs']:
        L.append('  · 下一根：' + x)
    if r['note']:
        L.append('  · ' + r['note'])
    h = r.get('history')
    if h:
        L.append(f'  历史触发 {h["n"]} 次（{h["note"]}）')
    L.append('  未回测，仅作描述和价位参考；不解锁战术单（战术买单仍看四证 4/4）。止损不适用于核心仓。')
    return '\n'.join(L)


def add_bar(B, spec):
    """Add or replace one verified latest bar: (date, o, h, l, c, v). Bars on or after that date are dropped first."""
    dt = spec[0]
    keep = [k for k, x in enumerate(B['d']) if x < dt]
    out = dict(B)
    out['d'] = [B['d'][k] for k in keep] + [dt]
    for key, x in zip('ohlcv', spec[1:6]):
        out[key] = np.append(np.asarray(B[key], dtype=float)[keep], float(x))
    if 'src' in B:
        out['src'] = [B['src'][k] for k in keep] + ['manual']
    return out


def main(argv):
    sys.path.insert(0, ROOT)
    import engine as E
    a = list(argv)
    bars_add, manual, asof = [], {}, None
    if '--refresh' in a:
        a.remove('--refresh')
        subprocess.run([sys.executable, '-I', os.path.join(ROOT, 'prep_data.py')], check=True, stdout=subprocess.DEVNULL)
    while '--bar' in a:
        k = a.index('--bar'); bars_add.append(a[k + 1].split(',')); del a[k:k + 2]
    while '--anchor' in a:
        k = a.index('--anchor'); t, dt = a[k + 1].split(','); manual[t.upper()] = dt; del a[k:k + 2]
    if '--asof' in a:
        k = a.index('--asof'); asof = a[k + 1]; del a[k:k + 2]
    as_json = '--json' in a
    tickers = [x.upper() for x in a if not x.startswith('--')] or ['NVDA', 'QQQ', 'SPCX']
    anchors = dict(read_anchors(), **manual)
    ddir = os.environ.get('FE_DATA_DIR') or os.path.join(ROOT, 'data')
    out = {}
    for t in tickers:
        src = PROXY.get(t, t)
        B = E.load(os.path.join(ddir, src + '.csv'))
        for b in bars_add:
            if b[0].upper() == src:
                B = add_bar(B, b[1:])
        i = None
        if asof:
            i = bisect.bisect_right(list(B['d']), asof) - 1
            if i < 0:
                out[t] = dict(error='这一天之前没有数据')
                continue
        out[t] = compute(B, i, anchors.get(src))
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print('\n\n'.join(text_block(t, r) if 'error' not in r else f'{t}  {r["error"]}' for t, r in out.items()))


if __name__ == '__main__':
    main(sys.argv[1:])
