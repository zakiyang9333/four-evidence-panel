#!/usr/bin/env python3
"""破位反抽 / 突破回踩 规则引擎 breakout-0.2（面板上叫「破位反抽 3.1」）。因果，未回测。

来历：录屏「平顶 / 平底 · 卧底战法」那一段，面板上用的就是「破位反抽 3.1」（做空 · 短线 20 日）。说明原话：
  跌破后反抽至原支撑下方受阻，反抽缩量，未能收回。价格进入建仓区，按计划分批参与，站回止损线上方离场。
那一段最后「查完要点」三条（原话），0.2 照这三条改过：
  ① 破线看收盘，影线不算
  ② 破线量过前 5 根均量 1.5 倍
  ③ 反抽量缩到破线日一半以内
另外两句：建仓区压在这条线下面，止损也在线上；第二目标“按这一跌再量一遍 1.0”。
这是照录屏重写的，不是原作者的代码；录屏没给的数都标【估算】。

做空 = 破位反抽：
  1. 有效破位：收盘跌破一个被碰过至少 2 次的支撑位，幅度超过 1% 和半个 ATR 里较大的那个（影线不算）。
  2. 反抽到位：破位之后的反弹回到离破位处 1.5%（或 0.4 个 ATR，取大的）以内：原来的支撑变成压力。
  3. 缩量受阻：反弹这一段的均量比下跌那一段小，当根收盘回到破位处下方，而且收在当根振幅的下半截。
  三项齐了才算条件齐。入场区 = 破位处到它下方 1.5%；止损 = 反弹最高点（或破位处，取更高的）上方 2%；
  第一目标 = 破位后跌到过的最低点；第二目标 = 破位处往下量一个箱体高度（等幅）。
做多 = 突破回踩：同一套规则上下翻过来（和 houshou.py 一样，把价格取负后跑同一段代码）。

- 全部因果：第 i 根上的判断只用 ≤ i 的数据；支撑/压力位只用在破位之前已经确认的摆动点。
- 摆动点、ATR、成交量累计都用 houshou.prepare() 的那一份，两套模型看到的是同一张图。
- 只用于观察，不是买卖依据。

参考过的开源实现（2026-11-17 查的，都只是别人的写法，不是验证）：
  TradingSignalBot/tradingview-strategies（收盘越过 0.75×ATR 才算破位、影线不算、12 根内回测）、hanreywt/Screener_Alert（0.25×ATR、放量 1.5 倍、
  回测容差 0.4×ATR）、ascendro-ca/break-and-retest（回测的量要小于破位那根）、neurotrader888/TechnicalAnalysisAutomation（目标 = 形态高度从破位处量出去）。
  这里的 ATR 倍数取它们的中间值。要记住的一点：Screener_Alert 的作者自己报告这类形态样本外是亏的（每笔 −0.27R，763 笔）。
"""
import bisect
import numpy as np

import houshou as hs
from houshou import up, dn, rel, r2, px, pct, vol_text

VERSION = 'breakout-0.2'
NAME = '破位反抽 3.1'
KIND, DEFAULT_SIDE = 'trade', 'short'
VIDEO = dict(brk_vol=1.5, brk_vol_n=5, retest_vol=0.5, t2_ext=1.0)
VIDEO_NOTE = dict(brk_vol='破线那根的量至少是前几根均量的多少倍', brk_vol_n='和前几根的均量比', retest_vol='反抽段的均量不超过破线那天的多少', t2_ext='第二目标：按这一跌再量几遍')
SIDE_NAME = dict(short='破位反抽', long='突破回踩')
SIDES = ('short', 'long')

EST = dict(                   # 全部【估算】
    lv_win=250,               # 找支撑/压力位的回看根数
    lv_tol=0.015,             # 几个摆动点的价格相差 1.5% 以内，算同一个位置
    lv_touch=2,               # 至少被碰过 2 次才算一个位置
    brk=0.01, brk_atr=0.5,    # 有效破位：收盘越过这个位置，幅度超过 max(1%, 0.5×ATR14/收盘)
    vol_n=20,                 # 破位当根的量和前 20 根均量比（只写在说明里，不作为条件）
    max_age=40,               # 破位之后最多跟 40 根，过了就不再算这一次破位
    retest=0.015, retest_atr=0.4,   # 反抽到位：回到离破位处 max(1.5%, 0.4×ATR14/收盘) 以内
    fail=0.02,                # 收盘反向越过破位处 2%：假破位，结构作废
    far=0.08,                 # 还没反抽、离破位处已经超过 8%：不追
    recent=2,                 # 反抽的极值要在最近 3 根之内（当根或前 2 根）
    close_half=0.5,           # 受阻：收在当根振幅靠破位方向的一半以内
    zone=0.015,               # 入场区 = 破位处到它外侧 1.5%
    stop=0.02,                # 止损 = 反抽极值（或破位处，取更远的）外侧 2%
    hist_hold=20)             # 历史触发往后看 20 根：先到目标还是先破止损

EST_NOTE = dict(
    lv_win='找支撑/压力位的回看根数', lv_tol='同一个位置的价格容差', lv_touch='一个位置最少被碰过几次', brk='有效破位：收盘越过的最小幅度', brk_atr='有效破位：越过幅度的 ATR 倍数',
    vol_n='破位当根和前多少根的均量比', max_age='一次破位最多跟踪多少根', retest='反抽到位：离破位处多近（最小值）', retest_atr='反抽到位：容差的 ATR 倍数', fail='假破位：收盘反向越过的幅度',
    far='不追：离破位处多远', recent='反抽极值最多是几根之前', close_half='受阻：收在当根振幅的哪一半',
    zone='入场区的宽度', stop='止损离反抽极值多远', hist_hold='历史触发往后看的根数')

WORDS = dict(
    short=dict(level='支撑位', brk='破位', brk_v='跌破', back='反抽', hold='受阻', beyond='下方', inside='上方', pull='反弹', leg='下跌', far_ext='最低', pull_ext='最高',
               half='下半截', fake='假破位', newext='新低', away='跌', k1='有效破位', k2='反抽到位', k3='缩量受阻'),
    long=dict(level='压力位', brk='突破', brk_v='突破', back='回踩', hold='企稳', beyond='上方', inside='下方', pull='回落', leg='上涨', far_ext='最高', pull_ext='最低',
              half='上半截', fake='假突破', newext='新高', away='涨', k1='有效突破', k2='回踩到位', k3='缩量企稳'))

VERDICT_TEXT = dict(
    short={'条件齐': '破位反抽条件齐了（未回测）', '等受阻': '反抽到位，等受阻', '等反抽': '破位了，等反抽', '不追': '不追空 · 离破位处太远', '等破位': '还没破位',
           '不适用': '这套清单用不上', '已失效': '结构已失效', hs.TOO_FINE: '价位太细，不给价位'},
    long={'条件齐': '突破回踩条件齐了（未回测）', '等受阻': '回踩到位，等企稳', '等反抽': '突破了，等回踩', '不追': '不追多 · 离突破处太远', '等破位': '还没突破',
          '不适用': '这套清单用不上', '已失效': '结构已失效', hs.TOO_FINE: '价位太细，不给价位'})


def _tol(P):
    """Per-bar tolerances: the fixed percentage or a multiple of ATR/close, whichever is larger. Cached on the prepared pass."""
    if 'bo_tol' not in P:
        rel_atr = np.where(np.isfinite(P['atr']), P['atr'] / np.where(P['c'] != 0, np.abs(P['c']), 1), 0.0)
        P['bo_tol'] = (np.maximum(EST['brk'], EST['brk_atr'] * rel_atr), np.maximum(EST['retest'], EST['retest_atr'] * rel_atr))
    return P['bo_tol']


def _beyond(lv, f):
    """The level moved outward by the fraction(s) f (works on arrays, and on the negated prices of the short side)."""
    return lv * (1 + f) if lv >= 0 else lv * (1 - f)


def _clusters(P, j):
    """Confirmed swing highs (in the working direction) of the last lv_win bars, grouped into levels.
    Returns [(level, [pivot index m, ...])], each with at least lv_touch pivots."""
    pi, pp, pk, pat = P['pi'], P['pp'], P['pk'], P['pat']
    k = bisect.bisect_right(pat, j)
    w0 = max(0, j - EST['lv_win'] + 1)
    pts = sorted((pp[m], m) for m in range(bisect.bisect_left(pi, w0), k) if pk[m] == 1)
    groups = []
    for p, m in pts:
        if groups and p <= up(groups[-1][0][0], EST['lv_tol']):
            groups[-1].append((p, m))
        else:
            groups.append([(p, m)])
    return [(sum(p for p, _ in g) / len(g), [m for _, m in g]) for g in groups if len(g) >= EST['lv_touch']]


def _core(P, j):
    """Everything the rules say at bar j, from bars ≤ j. Prices inside are in the working direction; the result is in real prices."""
    memo = P.setdefault('bo', {})
    if j in memo:
        return memo[j]
    d, o, h, l, c, v = P['d'], P['o'], P['h'], P['l'], P['c'], P['v']
    pi, pat = P['pi'], P['pat']
    s, side = P['s'], P['side']
    W = dict(WORDS[side], avg=P['W']['avg'])
    R = lambda x: px(s * x)
    span = lambda a, b: (R(a), R(b)) if s == 1 else (R(b), R(a))
    out = dict(phase='无结构', verdict='不适用', list=None, checks=[], missing=[], next_needs=[], note='', level=None, brk=None, extreme=None, pull=None,
               box=None, dist_pct=None, zone=None, mid=None, stop=None, t1=None, t2=None, t2_note='', rr=None, _b=None, _ready=False, _stop=None)
    cj = float(c[j])
    levels = _clusters(P, j)
    f_brk, f_ret = _tol(P)

    # 最近的一次有效破位：这个位置的最后一个摆动点确认之后，第一根收盘越过它 brk 以上的 K 线
    best, ahead = None, None
    for lv, ms in levels:
        conf = max(pat[m] for m in ms)
        seg = c[conf + 1:j + 1]
        hit = np.nonzero(seg > _beyond(lv, f_brk[conf + 1:j + 1]))[0]
        if hit.size:
            b = conf + 1 + int(hit[0])
            if j - b <= EST['max_age'] and (best is None or (b, lv) > (best[0], best[1])):
                best = (b, lv, ms)
        elif lv > cj and (ahead is None or lv < ahead[0]):
            ahead = (lv, ms)                       # 还没被越过、离现价最近的那个位置

    if best is None:
        if ahead is None:
            out['note'] = f'最近 {EST["lv_win"]} 根里，现价{W["beyond"]}没有被碰过 {EST["lv_touch"]} 次以上、又还没被{W["brk_v"]}的{W["level"]}，也没有 {EST["max_age"]} 根以内的{W["brk"]}。'
            memo[j] = out
            return out
        lv, ms = ahead
        gap = rel(lv, cj)
        thr = float(_beyond(lv, f_brk[j]))
        out.update(phase='盘整中', verdict='等破位', list='breakout',
                   level=dict(price=R(lv), touches=len(ms), dates=[d[pi[m]] for m in sorted(ms)]),
                   checks=[dict(k='K1', name=W['k1'], ok=False, why=f'收盘 {R(cj)} 离{W["level"]} {R(lv)}（碰过 {len(ms)} 次）还有 {pct(gap)}%，没有{W["brk"]}'),
                           dict(k='K2', name=W['k2'], ok=False, why=f'还没有{W["brk"]}，谈不上{W["back"]}'),
                           dict(k='K3', name=W['k3'], ok=False, why=f'还没有{W["brk"]}，谈不上{W["hold"]}')],
                   next_needs=[f'收盘{W["brk_v"]} {R(thr)}（{W["level"]} {R(lv)} {W["beyond"]} {f_brk[j] * 100:.1f}%）才算有效{W["brk"]}'])
        out['missing'] = [x['name'] + '：' + x['why'] for x in out['checks']]
        memo[j] = out
        return out

    b, lv, ms = best
    first_i = min(pi[m] for m in ms)
    box_far = float(l[first_i:b].min()) if b > first_i else float(l[b])        # 破位之前这一段箱体的另一头
    w0 = max(0, b - VIDEO['brk_vol_n'])
    vref = float(v[w0:b].mean()) if b > w0 else None
    vol_ok = vref is not None and vref > 0 and float(v[b]) >= VIDEO['brk_vol'] * vref
    out.update(list='breakout', _b=b,
               level=dict(price=R(lv), touches=len(ms), dates=[d[pi[m]] for m in sorted(ms)]),
               brk=dict(date=d[b], close=R(c[b]), vol_ratio=round(float(v[b]) / vref, 2) if vref else None),
               box=dict(start=d[first_i], end=d[b], far=R(box_far)), dist_pct=pct(s * rel(cj, lv)))
    k1 = dict(k='K1', name=W['k1'], ok=bool(vol_ok),
              why=f'{d[b]} 收盘 {R(c[b])} {W["brk_v"]}了{W["level"]} {R(lv)}（之前被碰过 {len(ms)} 次；看收盘，影线不算），幅度 {pct(rel(float(c[b]), lv))}%' +
                  (f'；当根成交量是前 {b - w0} 根均量的 {float(v[b]) / vref:.2f} 倍，' + ('过了' if vol_ok else '没过') + f' {VIDEO["brk_vol"]} 倍' if vref else '；量比不了'))

    # 假破位：破位之后有一根收盘反向越过破位处 fail 以上
    bad = np.nonzero(c[b + 1:j + 1] < dn(lv, EST['fail']))[0]
    if bad.size:
        x = b + 1 + int(bad[0])
        out.update(phase='已失效', verdict='已失效', checks=[k1],
                   note=f'{d[b]} {W["brk"]}之后，{d[x]} 收盘 {R(c[x])} 又回到{W["level"]} {R(lv)} {W["inside"]} {int(EST["fail"] * 100)}% 之外，是{W["fake"]}，这个结构作废。')
        memo[j] = out
        return out

    hi_i = b + int(np.argmax(h[b:j + 1]))             # 破位之后走到过的最远处
    far_p = float(h[hi_i])
    out['extreme'] = dict(date=d[hi_i], price=R(far_p))
    dist = rel(cj, lv)
    vb = float(v[b:hi_i + 1].mean())
    if hi_i == j:
        k2ok, pl, pl_i, vp = False, None, None, None
        why2 = f'{W["brk"]}之后今天还在创{W["newext"]}（{R(far_p)}），还没有{W["back"]}'
    else:
        pl_i = hi_i + 1 + int(np.argmin(l[hi_i + 1:j + 1]))
        pl = float(l[pl_i])
        vp = float(v[hi_i + 1:j + 1].mean())
        gap = rel(pl, lv)                             # 反抽的极值离破位处还有多远（负数 = 已经穿回去了）
        k2ok = pl <= up(lv, float(f_ret[j]))
        out['pull'] = dict(date=d[pl_i], price=R(pl))
        why2 = (f'{W["brk"]}后{W["pull"]}的{W["pull_ext"]}点 {R(pl)}（{d[pl_i]}）' +
                (f'离{W["brk"]}处 {R(lv)} 还有 {pct(gap)}%，' if gap > 0 else f'已经碰到{W["brk"]}处 {R(lv)}，') +
                ('到位' if k2ok else f'没到 {f_ret[j] * 100:.1f}% 以内'))
    k2 = dict(k='K2', name=W['k2'], ok=bool(k2ok), why=why2)

    rng = float(h[j] - l[j])
    pos = float(c[j] - l[j]) / rng if rng > 0 else 0.5
    side_ok, half_ok = cj > lv, pos >= EST['close_half']
    dry_ok = vp is not None and vp <= VIDEO['retest_vol'] * float(v[b])
    fresh = pl_i is not None and j - pl_i <= EST['recent']
    k3ok = k1['ok'] and k2ok and side_ok and half_ok and dry_ok and fresh
    if not k2ok:
        why3 = f'{W["back"]}还没到位，谈不上{W["hold"]}'
    else:
        why3 = (f'收盘 {R(cj)} ' + ('在' if side_ok else '不在') + f'{W["brk"]}处 {R(lv)} {W["beyond"]}；' +
                ('收在' if half_ok else '没收在') + f'当根的{W["half"]}；' +
                f'{W["pull"]}段{W["avg"]}量 {vol_text(vp)} 是{W["brk"]}那天 {vol_text(v[b])} 的 {round(vp / float(v[b]) * 100)}%，' + ('缩到一半以内' if dry_ok else '没缩到一半') +
                ('' if fresh else f'；{W["back"]}的{W["pull_ext"]}点是 {j - pl_i} 根之前，隔得太久'))
    k3 = dict(k='K3', name=W['k3'], ok=bool(k3ok), why=why3)
    checks = [k1, k2, k3]

    bad = ''
    if k3ok:            # 三项齐了：先看价位在显示的位数下分不分得开（低价区两位小数会把入场和止损挤成同一个数）
        z1, z2 = lv, up(lv, EST['zone'])
        mid = (z1 + z2) / 2
        stop = dn(min(pl, lv), EST['stop'])
        bad = hs.plan_check(s, mid, stop, far_p)
    need = []
    if k3ok and bad:
        verdict = hs.TOO_FINE
    elif k3ok:
        verdict = '条件齐'
    elif not k1['ok']:
        verdict = '等反抽' if not k2ok else '等受阻'
        need.append(f'{W["brk"]}那根没放量（要过前 {VIDEO["brk_vol_n"]} 根均量的 {VIDEO["brk_vol"]} 倍）：录屏说这样的{W["brk"]}不算数')
    elif k2ok:
        verdict = '等受阻'
        need.append(f'收盘回到 {R(lv)} {W["beyond"]}、收在当根的{W["half"]}，而且{W["pull"]}这一段的均量不超过 {vol_text(VIDEO["retest_vol"] * float(v[b]))}（{W["brk"]}那天的一半）')
    else:
        verdict = '不追' if dist > EST['far'] else '等反抽'
        a_, b_ = span(lv, up(lv, float(f_ret[j])))
        need.append(f'{W["pull"]}要回到 {a_} ~ {b_} 之间（{W["brk"]}处到它{W["beyond"]} {f_ret[j] * 100:.1f}%），才算{W["back"]}到位')
        if dist > EST['far']:
            need.append(f'现价离{W["brk"]}处已经 {pct(dist)}%，超过 {int(EST["far"] * 100)}%：按规则不追，等它{W["back"]}')
    need.append(f'收盘回到 {R(dn(lv, EST["fail"]))} {W["inside"]}（{W["brk"]}处{W["inside"]} {int(EST["fail"] * 100)}%）就是{W["fake"]}，这个结构作废')
    out.update(phase=(W['back'] + '中') if pl_i is not None else (W['brk'] + '后'), verdict=verdict, checks=checks, next_needs=need if not bad else [],
               missing=[x['name'] + '：' + x['why'] for x in checks if not x['ok']], _ready=bool(k3ok and not bad))
    if bad:
        out['note'] = f'清单三项都成立，但{bad}。这一次不算条件齐，也不给价位和盈亏比。'
    if k3ok and not bad:
        t2 = pl + VIDEO['t2_ext'] * (far_p - box_far)          # 按这一跌再量一遍：从反抽点起，再走一次“箱体另一头到破位后极值”那么远
        t2_ok = t2 > far_p
        out.update(zone=list(span(z1, z2)), mid=R(mid), stop=R(stop), t1=R(far_p), t2=R(t2) if t2_ok else None,
                   t2_note='按这一跌再量一遍 1.0' if t2_ok else '再量一遍的位置没有超过第一目标，不设',
                   rr=r2((far_p - mid) / (mid - stop)) if mid > stop and far_p > mid else None, _stop=stop)
    memo[j] = out
    return out


def evaluate(P, j):
    """_core plus: once a break has triggered (条件齐) and price then closed beyond that trigger's stop, the structure is dead."""
    r = dict(_core(P, j))
    if r['_b'] is not None and r['phase'] != '已失效':
        W = WORDS[P['side']]
        for q in range(r['_b'] + 1, j):
            rq = _core(P, q)
            if rq['_b'] == r['_b'] and rq['_ready']:
                x = next((x for x in range(q + 1, j + 1) if P['c'][x] < rq['_stop']), None)
                if x is not None:
                    r.update(phase='已失效', verdict='已失效', zone=None, mid=None, stop=None, t1=None, t2=None, rr=None, next_needs=[], _ready=False,
                             note=f'{P["d"][q]} 条件齐过一次，{P["d"][x]} 收盘越过了当时的止损 {px(P["s"] * rq["_stop"])}，这个结构作废。')
                break
    return r


def history(P, i, hold=None):
    """Every past trigger (the first 条件齐 bar of each break) and what came first in the next `hold` bars, seen from bar i."""
    st = P.setdefault('bo_hist', dict(upto=-1, rows=[], seen=set(), brk=[], k2=[], k3=[]))
    for j in range(st['upto'] + 1, i + 1):
        r = evaluate(P, j)
        if r['_b'] is not None and r['phase'] != '已失效':
            st['brk'].append(j)
            if len(r['checks']) > 1 and r['checks'][1]['ok']:
                st['k2'].append(j)
        if r['_ready'] and r['_b'] not in st['seen']:
            st['seen'].add(r['_b'])
            st['rows'].append((j, r['mid'], r['stop'], r['t1'], r['level']['price'], r['brk']['date'], r['rr']))
            st['k3'].append(j)
    st['upto'] = max(st['upto'], i)
    rows, hold, s = [], hold or EST['hist_hold'], P['s']
    for j, mid, stop, t1, lv, bdate, rr in st['rows']:
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
        rows.append(dict(date=P['d'][j], mid=mid, stop=stop, t1=t1, rr=rr, level=lv, break_date=bdate, outcome=res,
                         outcome_date=P['d'][when] if when is not None else None, bars=(when - j) if when is not None else None))
    cnt = lambda k: bisect.bisect_right(st[k], i)
    rrs = sorted(r['rr'] for r in rows if r['rr'] is not None)
    return dict(n=len(rows), rows=rows, hold=hold, note='样本数 %d，未做对照检验' % len(rows), rr_median=r2(rrs[len(rrs) // 2]) if rrs else None,
                stats=dict(bars=i + 1, after_break=cnt('brk'), K2=cnt('k2'), K3=cnt('k3')))


def compute(B, i=None, side='short', with_history=True, P=None, hold=None):
    """The public result at bar i (default: the last bar), in real prices."""
    P = P or hs.prepare(B, side)
    i = P['n'] - 1 if i is None else int(i)
    r = evaluate(P, i)
    res = {k: x for k, x in r.items() if not k.startswith('_')}
    res.update(model=VERSION, name=NAME, side=P['side'], side_name=SIDE_NAME[P['side']], asof=P['d'][i], index=i, close=r2(P['s'] * P['c'][i]),
               verdict_text=VERDICT_TEXT[P['side']][r['verdict']], params=dict(est=EST))
    if with_history:
        res['history'] = history(P, i, hold)
    return res


if __name__ == '__main__':
    import json, os, sys
    sys.path.insert(0, hs.ROOT)
    import engine as E
    a = sys.argv[1:]
    side = 'long' if '--side' in a and a[a.index('--side') + 1] == 'long' else 'short'
    for t in [x.upper() for x in a if not x.startswith('--') and x not in ('long', 'short')] or ['NVDA', 'QQQ', 'SPCX']:
        r = compute(E.load(os.path.join(os.environ.get('FE_DATA_DIR') or os.path.join(hs.ROOT, 'data'), t + '.csv')), side=side)
        print(f'【{SIDE_NAME[side]}】{t} · {r["asof"]} 收盘 {r["close"]}：{r["phase"]} → {r["verdict_text"]}  [{NAME}]')
        for x in r['checks']:
            print(f'    [{"x" if x["ok"] else " "}] {x["k"]} {x["name"]}：{x["why"]}')
        if r['zone']:
            print(f'  入场区 {r["zone"][0]} ~ {r["zone"][1]}；止损 {r["stop"]}；第一目标 {r["t1"]}；第二目标 {r["t2"]}（{r["t2_note"]}）；盈亏比 {r["rr"]}')
        for x in r['next_needs']:
            print('  · 下一根：' + x)
        if r['note']:
            print('  · ' + r['note'])
        print(f'  历史触发 {r["history"]["n"]} 次（{r["history"]["note"]}）：' + json.dumps(r['history']['stats'], ensure_ascii=False))
