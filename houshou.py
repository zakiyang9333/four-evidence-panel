#!/usr/bin/env python3
"""后手·成本线回踩 规则引擎 houshou-0.2（APP_ADDENDUM_QUANT_AI.md §3）。因果，未回测。做多、做空两侧。

把 TradingVane 第二段录屏（量化AI | 后手战法 | 量化对抗量化）的五条总结写成代码，只用于观察，不是买卖依据。
用法：
  python3 houshou.py NVDA QQQ SPCX [QQQI] [--json] [--asof YYYY-MM-DD] [--side long|short]
                     [--anchor TICKER,YYYY-MM-DD] [--bar TICKER,DATE,O,H,L,C,V] [--refresh]
  --anchor   手动指定成本锚点（横盘第一根）；不给就用 data/houshou_anchor.json 里存的，再没有就自动找【估算】
  --bar      加入/替换一根已核实的最新 K 线，可重复
  --refresh  先运行 prep_data.py（只追加新日期）
  QQQI 没有可用历史，按 QQQ 读（代理）。

- 输入和 engine.load() 一样的日线数组（d, o, h, l, c, v）。engine.py 不动，这里不引用它的规则。
- 全部因果：第 i 根上的任何判断只用 ≤ i 的数据。摆动点要等反向走完阈值才算确认，没确认的那个极值单独标 pending。
- VIDEO 是视频里说了的数；EST 是视频没给、这里自己定的数，全部【估算】，界面上照样标出来。
- 美股没有涨停和 T+1，不做涨停相关逻辑。
- 做空一侧（0.2 新增，视频没讲）：把同一套规则上下翻过来。做法是把价格取负（高低互换）后跑同一段代码，再把结果翻回来，
  所以两侧用的是同一批参数、同一条成本线算法，百分比都相对起点价的绝对值算：做空的止损就是 D 点上方 2%，一分不差。
  做多一侧的每个数字、每句话和 0.1 完全一样。
- 第二目标（0.2 新增）：录屏面板上有这一格，但没说怎么算。这里从 D 点往外量 2 倍这一轮的涨幅【估算】：
  这个倍数是从录屏那一格的数字（+48.71%）和图上的回撤刻度反推的，开源实现里常见的是 1.618 倍，两者都从回踩点起量。

注意：面板（quant.py / structure.py / chart_score.py / server.py）引用这个文件的 prepare、compute、evaluate、history、swings、
avwap_series、NAME、EST、EST_NOTE、r2 等接口。2026-11-16 15:47 这个文件被别的线程整份换成过另一套接口，面板因此起不来；
zaki 当天定了以这一份为准（那一份留在 wip_quant/houshou_other_thread_1547.py，它的命令行选项这里都保留了）。
要改接口请先和面板这边对一下，不要整份替换。
"""
import sys, os, json, bisect, subprocess
import numpy as np

VERSION = 'houshou-0.2'
NAME = '后手·成本线回踩 v0.2'
SIDES = ('long', 'short')
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
    hist_hold=20,             # 历史触发往后看 20 根：先到目标还是先破止损
    t2_ext=2.0)               # 第二目标 = D 点 + 2 ×（第三冲高点 − 起涨低点）：从回踩点再量两倍这一轮的涨幅

EST_NOTE = dict(
    zz_min='摆动点最小反转幅度', zz_atr='摆动点反转幅度的 ATR 倍数', atr_n='ATR 根数', top_win='找本轮最高点的回看根数',
    base_min='横盘最少根数', base_band='横盘收盘价离中位数的最大偏离', climax_win='天量的回看根数', shadow='长上影占整根振幅的比例',
    touch='回到成本线：最低价最多高出成本线', touch_low='回到成本线：最低价最多低于成本线', zone='建仓区离成本线的宽度',
    sr_tol='支撑/压力的触碰容差', sr_win='支撑/压力的回看根数', hist_hold='历史触发往后看的根数',
    t2_ext='第二目标：从 D 点往外量这一轮涨幅的几倍')

ROOT = os.path.dirname(os.path.abspath(__file__))


def r2(x):
    return None if x is None or not np.isfinite(x) else round(float(x), 2)


def pct(x, nd=1):
    return None if x is None or not np.isfinite(x) else round(float(x) * 100, nd)


def vol_text(x):
    x = float(x)
    return f'{x / 1e8:.2f} 亿' if x >= 1e8 else f'{x / 1e4:.0f} 万'


# ---------- 做多 / 做空：同一段代码，价格取负 ----------
# 做空时内部用的是取负后的价格（原来的最低价变成“最高价”）。下面三个小函数保证百分比永远相对绝对值算，
# 这样取负之后的每一步都是做多那一步的精确镜像；价格为正时，它们和原来的写法逐位相同。

def up(x, t):
    """x 往有利方向挪 t（相对 |x|）。"""
    return x * (1 + t) if x >= 0 else x * (1 - t)


def dn(x, t):
    """x 往不利方向挪 t（相对 |x|）。"""
    return x * (1 - t) if x >= 0 else x * (1 + t)


def rel(a, b):
    """(a − b) / |b|。"""
    return a / b - 1 if b > 0 else 1 - a / b


WORDS = dict(
    long=dict(dir='做多', top='高点', bot='低点', peak='最高点', start='起涨', rise='上涨', fall='下跌', down='跌', push='冲', force='兵力', higher='高',
              above='上方', below='下方', under_w='以下', exceed='超过', shadow='上影', peak_bar='最高那根', bounce='反弹', over='高于', under='低于',
              pierce='跌破', ext='最低', ext_pt='最低点', ext_px='最低价'),
    short=dict(dir='做空', top='低点', bot='高点', peak='最低点', start='起跌', rise='下跌', fall='上涨', down='涨', push='探', force='抛压', higher='低',
               above='下方', below='上方', under_w='以上', exceed='跌过', shadow='下影', peak_bar='最低那根', bounce='回落', over='低于', under='高于',
               pierce='涨破', ext='最高', ext_pt='最高点', ext_px='最高价'))


# ---------- one causal pass over the bars ----------

def prepare(B, side='long', avg='日均'):
    """ATR, swing points (zigzag) and running sums. Every value at bar j uses bars ≤ j only.
    side='short' turns the prices upside down (o, h, l, c → −o, −l, −h, −c); everything after that is the same code.
    avg = how an average over bars is worded in the explanations (日均 on daily bars, 周均 on weekly ones)."""
    if side not in SIDES:
        raise ValueError('side')
    d = list(B['d'])
    o, h, l, c, v = (np.asarray(B[k], dtype=float) for k in 'ohlcv')
    s = 1 if side == 'long' else -1
    if s == -1:
        o, h, l, c = -o, -l, -h, -c
    n = len(c)
    N = EST['atr_n']
    atr = np.full(n, np.nan)
    if n:
        pc = np.concatenate(([c[0]], c[:-1]))
        tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
        cs = np.concatenate(([0.0], np.cumsum(tr)))
        if n >= N:
            atr[N - 1:] = (cs[N:] - cs[:-N]) / N
    thr = np.where(np.isfinite(atr), np.maximum(EST['zz_min'], EST['zz_atr'] * atr / np.where(c != 0, np.abs(c), 1)), EST['zz_min'])

    H, L, T = h.tolist(), l.tolist(), thr.tolist()
    pi, pp, pk, pat = [], [], [], []            # pivot bar, price, kind (+1 high / −1 low), bar where it got confirmed
    pend_k, pend_i = [0] * n, [-1] * n          # the unconfirmed extreme as seen at each bar
    dirn, hi, lo = 0, 0, 0
    for j in range(n):
        if dirn == 0:
            if H[j] > H[hi]: hi = j
            if L[j] < L[lo]: lo = j
            if hi < j and L[j] <= dn(H[hi], T[j]):
                pi.append(hi); pp.append(H[hi]); pk.append(1); pat.append(j); dirn = -1
                lo = min(range(hi + 1, j + 1), key=L.__getitem__)
            elif lo < j and H[j] >= up(L[lo], T[j]):
                pi.append(lo); pp.append(L[lo]); pk.append(-1); pat.append(j); dirn = 1
                hi = max(range(lo + 1, j + 1), key=H.__getitem__)
        elif dirn == 1:
            if H[j] > H[hi]:
                hi = j
            elif L[j] <= dn(H[hi], T[j]):
                pi.append(hi); pp.append(H[hi]); pk.append(1); pat.append(j); dirn = -1
                lo = min(range(hi + 1, j + 1), key=L.__getitem__)
        else:
            if L[j] < L[lo]:
                lo = j
            elif H[j] >= up(L[lo], T[j]):
                pi.append(lo); pp.append(L[lo]); pk.append(-1); pat.append(j); dirn = 1
                hi = max(range(lo + 1, j + 1), key=H.__getitem__)
        pend_k[j] = dirn
        pend_i[j] = hi if dirn == 1 else lo if dirn == -1 else -1

    tp = (h + l + c) / 3
    z = lambda a: np.concatenate(([0.0], np.cumsum(a)))
    return dict(d=d, o=o, h=h, l=l, c=c, v=v, n=n, atr=atr, thr=thr, pi=pi, pp=pp, pk=pk, pat=pat, pend_k=pend_k, pend_i=pend_i,
                CV=z(v), CTV=z(tp * v), CT2V=z(tp * tp * v), tp=tp, memo={}, base={}, hist={}, s=s, side=side, W=dict(WORDS[side], avg=avg))


def swings(P, i):
    """Confirmed swing points as seen at bar i, oldest first, plus the unconfirmed extreme."""
    k = bisect.bisect_right(P['pat'], i)
    s = P['s']
    conf = [dict(i=P['pi'][m], date=P['d'][P['pi'][m]], price=r2(s * P['pp'][m]), kind='high' if P['pk'][m] * s == 1 else 'low', confirmed=P['d'][P['pat'][m]])
            for m in range(k)]
    pend = None
    if P['n'] and P['pend_k'][i]:
        q = P['pend_i'][i]
        pend = dict(i=q, date=P['d'][q], price=r2(s * (P['h'][q] if P['pend_k'][i] == 1 else P['l'][q])), kind='high' if P['pend_k'][i] * s == 1 else 'low')
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
    return dict(d=P['d'][a:j + 1], v=f(P['s'] * m), sd=f(sd))


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
        if (hi > lo * lim) if lo > 0 else (lo < hi * lim):           # 再往前加只会更宽，不可能再满足
            break
        k = len(srt)
        if s <= L0 and k >= EST['base_min']:
            med = srt[k // 2] if k % 2 else (srt[k // 2 - 1] + srt[k // 2]) / 2
            if lo >= dn(med, band) and hi <= up(med, band):
                best = s
    P['base'][key] = best
    return best


# ---------- the rules at one bar ----------

def _core(P, j, am):
    """Everything the rules say at bar j, from bars ≤ j. am = index of a manual cost anchor, or None.
    Inside, prices are in the working direction (negated on the short side). Whatever goes into the result passes through R(),
    so the result is always in real prices; the words come from P['W'] (做多 and 做空 read differently)."""
    memo = P['memo'].setdefault(am, {})
    if j in memo:
        return memo[j]
    d, o, h, l, c, v = P['d'], P['o'], P['h'], P['l'], P['c'], P['v']
    pi, pp, pk, pat = P['pi'], P['pp'], P['pk'], P['pat']
    s, W = P['s'], P['W']
    R = lambda x: r2(s * x)
    span = lambda a, b: (R(a), R(b)) if s == 1 else (R(b), R(a))       # 两个价位，按真实价格从小到大
    k = bisect.bisect_right(pat, j)                    # 到第 j 根为止已确认的摆动点个数
    win0 = max(0, j - EST['top_win'] + 1) if am is None else am
    out = dict(phase='无结构', verdict='不适用', list=None, checks=[], missing=[], next_needs=[], note='', anchor=None, avwap=None, sd=None,
               dist_pct=None, pushes=[], abcd=None, zone=None, mid=None, stop=None, t1=None, t2=None, rr=None, base=None, start_low=None, top=None,
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
        out['note'] = f'最近 {EST["top_win"]} 根里没有已确认的{W["top"]}，谈不上三{W["push"]}。' if am is None else f'手动锚点之后还没有出现{W["top"]}。'
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
        out['note'] = f'{W["peak"]}之前没有可用的{W["start"]}段。'
        memo[j] = out
        return out
    out['start_low'] = dict(date=d[L0], price=R(l[L0]))
    out['top'] = dict(date=d[Ti], price=R(Tp), pending=Tm is None)

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
    pushes = [dict(n=x + 1, date=d[raw[x][0]], price=R(raw[x][1]), from_low=d[raw[x][2]], force=round(force[x]), pending=raw[x][3],
                   force_pct=round(force[x] / f0 * 100) if x in use and f0 else None, slot=use.index(x) + 1 if x in use and len(use) == 3 else None)
              for x in range(len(raw))]
    out['pushes'] = pushes

    # 成本锚点：手动的优先；否则找包含起涨低点、在第一冲之前结束的最长横盘段，锚点是它的第一根
    if am is not None:
        a, by, note = am, 'manual', ''
    else:
        best = None
        for e in range(L0, raw[0][0]):
            b0 = _base(P, L0, e)
            if b0 is not None and (best is None or e - b0 > best[1] - best[0]):
                best = (b0, e)
        if best:
            a, by, note = best[0], 'auto', f'横盘 {best[1] - best[0] + 1} 根（{d[best[0]]} 至 {d[best[1]]}），锚在第一根'
            out['base'] = dict(start=d[best[0]], end=d[best[1]], bars=best[1] - best[0] + 1)
        else:
            a, by, note = L0, 'auto', f'未找到横盘，用{W["start"]}{W["bot"]}代替【估算】'
    av, sd = avwap(P, a, j)
    cj, far = float(c[j]), VIDEO['far']
    dist = rel(cj, av)                                 # 朝着这一轮的方向，离成本线走出去了多远
    out.update(anchor=dict(date=d[a], by=by, note=note), avwap=R(av), sd=r2(sd), dist_pct=pct(s * dist))

    npush = len(raw)
    if Tm is None:      # ---- 拉升中：不追清单 ----
        a1 = dist > far
        checks = [dict(k='A1', name='离成本太远', ok=bool(a1),
                       why=f'收盘 {R(cj)} 比成本线 {R(av)} {W["higher"]} {pct(dist)}%，' + ('超过' if a1 else '没到') + f' {int(far * 100)}%')]
        if npush >= 3:
            f1, f2, f3 = (force[x] for x in use)
            a2 = f1 > f2 > f3
            bar = raw[use[2]][0]
            rng = float(h[bar] - l[bar])
            sh = float(h[bar] - max(o[bar], c[bar])) / rng if rng > 0 else 0.0
            w0 = max(0, bar - EST['climax_win'] + 1)
            climax = bool(v[bar] >= v[w0:bar + 1].max())
            a3 = climax and sh >= EST['shadow']
            checks.append(dict(k='A2', name=f'{W["push"]}第三次', ok=bool(a2),
                               why=f'已经是第 {npush} {W["push"]}。最近三{W["push"]}的{W["force"]}（{W["rise"]}段{W["avg"]}量）{vol_text(f1)} → {vol_text(f2)} → {vol_text(f3)}，' +
                                   ('一次比一次少' if a2 else '不是一次比一次少')))
            checks.append(dict(k='A3', name=f'天量长{W["shadow"]}', ok=bool(a3),
                               why=f'{W["peak_bar"]}（{d[bar]}）成交量 {vol_text(v[bar])}，' + (f'是近 {EST["climax_win"]} 根最大' if climax else f'不是近 {EST["climax_win"]} 根最大') +
                                   f'；{W["shadow"]}占整根 {round(sh * 100)}%，' + ('够长' if sh >= EST['shadow'] else f'不到 {int(EST["shadow"] * 100)}%')))
        else:
            a2 = a3 = False
            checks.append(dict(k='A2', name=f'{W["push"]}第三次', ok=False, why=f'才第 {npush} {W["push"]}，还没到第三{W["push"]}'))
            checks.append(dict(k='A3', name=f'天量长{W["shadow"]}', ok=False, why=f'还没有第三{W["push"]}，谈不上'))
        verdict = '不追·出货区' if a1 and a2 and a3 else '不追' if a1 else '出货区' if a2 and a3 else '还能看'
        need = []
        if a1:
            need.append(f'收盘回到 {R(up(av, far))} {W["under_w"]}（成本线{W["above"]} {int(far * 100)}%），才不算离成本太远')
        else:
            need.append(f'收盘{W["exceed"]} {R(up(av, far))}（成本线{W["above"]} {int(far * 100)}%）就算离成本太远，不追')
        out.update(phase='拉升中', verdict=verdict, list='chase', checks=checks, next_needs=need,
                   missing=[x['name'] + '：' + x['why'] for x in checks if not x['ok']])
        memo[j] = out
        return out

    if npush < 3:       # ---- 最高点已经确认，但这一轮不够三冲 ----
        out['note'] = f'这一轮{W["rise"]}到 {d[Ti]} 的{W["top"]}只有 {npush} {W["push"]}，不是三{W["push"]}结构，后手清单不适用。'
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
    pts = dict(A=dict(date=d[Ti], price=R(Ap)), B=None, C=None, D=None, ab_pct=None, cd_pct=None)
    down = list(range(Ti + 1, (pi[Bm] if Bm is not None else j) + 1))       # 下跌段的 K 线
    Di = None
    if Bm is None:
        Di = Ti + 1 + int(np.argmin(l[Ti + 1:j + 1]))
        pts['D'] = dict(date=d[Di], price=R(l[Di]), provisional=True)
    else:
        pts['B'] = dict(date=d[pi[Bm]], price=R(pp[Bm]))
        pts['ab_pct'] = pct((Ap - pp[Bm]) / abs(Ap))
        if Cm is not None:
            Ci = pi[Cm]
            Di = Ci + 1 + int(np.argmin(l[Ci + 1:j + 1]))
            pts['C'] = dict(date=d[Ci], price=R(pp[Cm]))
            pts['D'] = dict(date=d[Di], price=R(l[Di]), is_today=Di == j)
            pts['cd_pct'] = pct((pp[Cm] - float(l[Di])) / abs(pp[Cm]))
            down += list(range(Ci + 1, Di + 1))
    zlo, zhi = dn(av, EST['touch_low']), up(av, EST['touch'])
    tl, th = int(EST['touch_low'] * 100), int(EST['touch'] * 100)
    band = f'−{tl}% ~ +{th}%' if s == 1 else f'−{th}% ~ +{tl}%'
    z_a, z_b = span(zlo, zhi)
    if Di is None:
        b1, why1 = False, f'B 点之后还在{W["bounce"]}，第二段{W["fall"]}没开始；成本线在 {R(av)}'
    else:
        Dl = float(l[Di])
        b1 = zlo <= Dl <= zhi
        why1 = (f'这段{W["fall"]}的{W["ext_pt"]} {R(Dl)}（{d[Di]}）' + ('落在' if b1 else W['over'] if Dl > zhi else W['under']) +
                f'成本线 {R(av)} 的 {band} 区间（{z_a} ~ {z_b}）')
    if Bm is None:
        b2, why2 = False, f'第一段{W["fall"]}还没走完（B 点没确认），比不了两段'
    elif Cm is None:
        b2, why2 = False, f'第一段{W["down"]}了 {pts["ab_pct"]}%，{W["bounce"]}还没走完（C 点没确认），第二段没开始'
    else:
        ab, cd = (Ap - pp[Bm]) / abs(Ap), (pp[Cm] - float(l[Di])) / abs(pp[Cm])
        b2 = abs(cd / ab - 1) < VIDEO['abcd_tol']
        why2 = f'第一段{W["down"]} {pct(ab)}%，第二段{W["down"]} {pct(cd)}%，' + ('相差不到' if b2 else '相差超过') + f' {int(VIDEO["abcd_tol"] * 100)}%'
    legs = [x for x in down if x != j]
    base_v = float(v[legs].mean()) if legs else None
    pierce = bool(l[j] < av and cj > av)
    dry = base_v is not None and float(v[j]) <= VIDEO['dry'] * base_v
    b3 = pierce and dry
    why3 = ((f'盘中{W["pierce"]}成本线又收回' if pierce else f'收盘在成本线{W["below"]}，没收回' if cj <= av else f'盘中没有{W["pierce"]}成本线') +
            f'（{W["ext"]} {R(l[j])}，收 {R(cj)}，线 {R(av)}）；' +
            (f'成交量 {vol_text(v[j])}，是{W["fall"]}段{W["avg"]} {vol_text(base_v)} 的 {round(float(v[j]) / base_v * 100)}%，' + ('缩到一半以下' if dry else '没缩到一半') if base_v
             else f'{W["fall"]}段还没有可比的成交量'))
    checks = [dict(k='B1', name='回到成本线', ok=bool(b1), why=why1), dict(k='B2', name='AB=CD', ok=bool(b2), why=why2),
              dict(k='B3', name='缩量刺破收回', ok=bool(b3), why=why3)]
    need = []
    if not b1:
        need.append(f'{W["ext_px"]}要落到 {z_a} ~ {z_b} 之间（按现在的成本线，会随成交略微移动）')
    if not b2 and Bm is not None and Cm is not None:
        ab = (Ap - pp[Bm]) / abs(Ap)
        e_a, e_b = span(dn(pp[Cm], ab * (1 + VIDEO['abcd_tol'])), dn(pp[Cm], ab * (1 - VIDEO['abcd_tol'])))
        need.append(f'第二段的{W["ext_pt"]}要在 {e_a} ~ {e_b} 之间，两段才算等长')
    if not b3:
        need.append(f'盘中{W["pierce"]} {R(av)} 又收回到它{W["above"]}' + (f'，而且成交量不超过 {vol_text(VIDEO["dry"] * base_v)}' if base_v else ''))
    all3 = b1 and b2 and b3
    out.update(phase='回落中', verdict='下后手' if all3 else '等', list='houshou', checks=checks, abcd=pts, next_needs=need,
               missing=[x['name'] + '：' + x['why'] for x in checks if not x['ok']], _A=Ti, _Aat=pat[Tm], _all3=bool(all3))
    if all3:
        z1, z2, stop = dn(av, EST['zone']), up(av, EST['zone']), dn(float(l[Di]), VIDEO['stop'])
        t2 = float(l[Di]) + EST['t2_ext'] * (Ap - float(l[L0]))          # 第二目标【估算】：从 D 点再量 2 倍这一轮（起涨低点到第三冲高点）的幅度
        out.update(zone=list(span(z1, z2)), mid=R(av), stop=R(stop), t1=R(Ap), t2=R(t2), rr=r2((Ap - av) / (av - stop)) if av > stop else None)
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
                    r.update(phase='已失效', verdict='已失效', zone=None, mid=None, stop=None, t1=None, t2=None, rr=None, next_needs=[],
                             note=f'{P["d"][q]} 条件齐过一次，{P["d"][broke]} 收盘{P["W"]["pierce"]}了当时的止损 {r2(P["s"] * rq["_stop"])}，这个结构作废。')
                break
    return r


def history(P, i, am=None, hold=None):
    """Replay the same code bar by bar: every past 3/3, and what came first in the next `hold` bars (seen from bar i, no later data)."""
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
            st['rows'].append((j, r['mid'], r['stop'], r['t1'], r['abcd']['A']['date'], r['rr']))
    st['upto'] = max(st['upto'], i)
    rows, hold, s = [], hold or EST['hist_hold'], P['s']
    for j, mid, stop, t1, adate, rr in st['rows']:
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
        rows.append(dict(date=P['d'][j], mid=mid, stop=stop, t1=t1, rr=rr, top_date=adate, outcome=res, outcome_date=P['d'][when] if when is not None else None,
                         bars=(when - j) if when is not None else None))
    cnt = lambda k: bisect.bisect_right(st[k], i)
    return dict(n=len(rows), rows=rows, hold=hold, note='样本数 %d，未做对照检验' % len(rows),
                stats=dict(bars=i + 1, fall=cnt('fall'), B1=cnt('B1'), B2=cnt('B2'), B3=cnt('B3'), two_of_three=cnt('two')))


def compute(B, i=None, anchor_date=None, with_history=True, P=None, side='long', hold=None):
    """The public result at bar i (default: the last bar), in real prices for either side.
    anchor_date = manual cost anchor (ignored on dates before it). side is only used when P is not given."""
    P = P or prepare(B, side)
    n = P['n']
    i = n - 1 if i is None else int(i)
    am = None
    if anchor_date and anchor_date in P['d']:
        am = P['d'].index(anchor_date)
        if am > i:
            am = None
    r = evaluate(P, i, am)
    res = {k: x for k, x in r.items() if not k.startswith('_')}
    res.update(model=VERSION, name=NAME, side=P['side'], asof=P['d'][i], index=i, close=r2(P['s'] * P['c'][i]), t2_note='从 D 点量 2 倍这一轮的幅度【估算】',
               params=dict(video=VIDEO, est=EST), anchor_index=P['d'].index(r['anchor']['date']) if r['anchor'] else None)
    if with_history:
        res['history'] = history(P, i, am, hold)
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
    short = r.get('side') == 'short'
    W = WORDS['short' if short else 'long']
    L = [f'【后手检查】{t}{"（代理 " + px + "）" if px else ""} · {r["asof"]} 收盘 {r["close"]}：{r["phase"]} → {r["verdict"]}  [{NAME}{" · 做空（镜像规则）" if short else ""}]']
    if r['anchor']:
        L.append(f'  成本线（锚定 VWAP，锚 {r["anchor"]["date"]}，{"手动" if r["anchor"]["by"] == "manual" else "自动"}' +
                 (f'，{r["anchor"]["note"]}' if r['anchor']['note'] else '') + f'）{r["avwap"]}，现价离它 {r["dist_pct"]:+}%；不追线 {r2(r["avwap"] * (1 - VIDEO["far"] if short else 1 + VIDEO["far"]))}')
    if r['pushes']:
        L.append(('  下探：' if short else '  冲高：') + '；'.join(f'第{p["n"]}{W["push"]} {p["date"]} {p["price"]}' + ('（未确认）' if p['pending'] else '') + f'（{W["force"]} {vol_text(p["force"])}）' for p in r['pushes'][-3:]))
    if r['list']:
        L.append('  ' + ('不追清单' if r['list'] == 'chase' else '后手清单') + f' {sum(c["ok"] for c in r["checks"])}/{len(r["checks"])}')
        for c in r['checks']:
            L.append(f'    [{"x" if c["ok"] else " "}] {c["k"]} {c["name"]}：{c["why"]}')
    if r['zone']:
        L.append(f'  建仓区 {r["zone"][0]} ~ {r["zone"][1]}；止损（D 点{"上" if short else "下"} 2%，手动）{r["stop"]}；第一目标 {r["t1"]}；盈亏比 {r["rr"]}；第二目标 {r["t2"]}（{r["t2_note"]}）')
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
    bars_add, manual, asof, side = [], {}, None, 'long'
    if '--refresh' in a:
        a.remove('--refresh')
        subprocess.run([sys.executable, '-I', os.path.join(ROOT, 'prep_data.py')], check=True, stdout=subprocess.DEVNULL)
    while '--bar' in a:
        k = a.index('--bar'); bars_add.append(a[k + 1].split(',')); del a[k:k + 2]
    while '--anchor' in a:
        k = a.index('--anchor'); t, dt = a[k + 1].split(','); manual[t.upper()] = dt; del a[k:k + 2]
    if '--asof' in a:
        k = a.index('--asof'); asof = a[k + 1]; del a[k:k + 2]
    if '--side' in a:
        k = a.index('--side'); side = 'short' if a[k + 1] == 'short' else 'long'; del a[k:k + 2]
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
        out[t] = compute(B, i, anchors.get(src + (':short' if side == 'short' else '')), side=side)
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print('\n\n'.join(text_block(t, r) if 'error' not in r else f'{t}  {r["error"]}' for t, r in out.items()))


if __name__ == '__main__':
    main(sys.argv[1:])
