"""收口突破 —— TTM Squeeze 的公开定义（John Carter《Mastering the Trade》：布林带缩进肯特纳通道），突破的写法参考 vn.py 的布林 / 肯特纳通道策略（MIT）。因果，未回测。

公开定义：
  布林带：20 根收盘的均线 ± 2 倍标准差。肯特纳通道：同一条均线 ± 1.5 倍“20 根真实波幅的平均”。
  布林带整条缩进肯特纳通道里面，就叫收口：波动小到少见的程度，往往是一段大行情之前的安静。
清单（按做多一侧写；做空时整张图上下翻过来，原版本来就做两个方向）：
  K1 收口过：最近 10 根【估算】里，有一段连续至少 5 根【估算】的收口。
  K2 收盘突破上沿：收口之后，最近 3 根【估算】里有一根收盘第一次站上收口区间的最高价。
  K3 突破放量：突破那一根的成交量，至少是前 20 根均量的 1.5 倍【估算】。
三项齐了、而且现价离上沿不超过 1 个 ATR【估算】：建仓区 = 上沿到它上方半个 ATR；止损 = 收口区间的中线（收回中线以下就是假突破）；
第一目标 = 上沿往上量一个区间高度；第二目标 = 量两个【估算】。
"""
import numpy as np

import indicators as ind
import patterns as pt
import qmodel as qm
from qmodel import R

KEY, VERSION, NAME = 'squeeze', 'squeeze-r1', '收口突破'
KIND, DEFAULT_SIDE = 'trade', 'long'
DEFAULT_HZ = 20
MIRRORED = ()                     # 两个方向都是原版的规则
TAGS = ('开源规则', '参数含估算')
EXTRA = ('squeeze',)
VIDEO, VIDEO_NOTE = {}, {}
SOURCE = dict(bb_n=20, bb_k=2.0, kc_n=20, kc_k=1.5)
SOURCE_NOTE = dict(bb_n='布林带算多少根', bb_k='布林带上下各几倍标准差', kc_n='肯特纳通道算多少根', kc_k='肯特纳通道上下各几倍平均真实波幅')
EST = dict(min_sq=5, look=10, fresh=3, vol=1.5, vol_n=20, chase_atr=1.0, zone_atr=0.5, t2_mult=2.0)
EST_NOTE = dict(min_sq='收口至少连续几根', look='收口要在最近几根以内', fresh='突破之后几根以内还算“刚突破”', vol='突破那根的量至少是均量的几倍',
                vol_n='均量算多少根', chase_atr='离上沿超过几个 ATR 就算追高', zone_atr='建仓区是上沿往外几个 ATR', t2_mult='第二目标往外量几个区间高度')
REFS = ('John Carter《Mastering the Trade》里的 TTM Squeeze：布林带(20, 2) 缩进肯特纳通道(20, 1.5)',
        'vnpy/vnpy_ctastrategy：strategies/boll_channel_strategy.py、king_keltner_strategy.py（MIT），通道突破的写法',
        'LazyBear 的 Squeeze Momentum 公开说明：肯特纳通道用真实波幅的平均')
NOTES = ('没有回测过。照 TTM Squeeze 的公开定义重写，不是原作者的代码。', 'vn.py 那两个通道策略的参数是按 5 分钟、15 分钟期货调的，这里没照搬，改用 TTM 原版的日线参数。',
         '收口说明的是“要动了”，不说明往哪边动：两个方向都要看。')

LEARN = dict(
    long=dict(idea_title='“收口突破”在看什么？',
              idea='布林带像一个弹簧。价格安静下来，布林带就越收越窄，缩进另一条更宽的通道里，这叫收口。收口之后放量往上冲出去，它就跟上。',
              idea_note='来自 TTM Squeeze 这个开源指标。这里照公开的定义重写。',
              list_title='三项清单', list='三个问题。最近有没有连着收口好几根？收口之后，收盘冲过了那一段的最高价吗？冲出去的那一根放量了吗？',
              plan='建仓区从收口区间的最高价开始，往上半个 ATR。止损在区间中线：掉回中线以下，就是假突破。目标是往上量一个、两个区间高度。',
              none='它要先看到连着好几根的收口。最近没有，所以清单空着。',
              cards=[('g_sq', '什么是“收口”？', '布林带量的是价格最近晃得多厉害。晃得越小，带子越窄。窄到缩进另一条通道里，就是一段少见的安静。安静之后，常常会有一段大的走势。', None, 'chart')]),
    short=dict(idea_title='“收口突破”的做空一侧在看什么？',
               idea='布林带像一个弹簧。价格安静下来，布林带就越收越窄。收口之后放量往下跌出去，它就跟着做空。',
               idea_note='原版本来就做两个方向，这一侧也是原版的规则。',
               list_title='三项清单', list='三个问题。最近有没有连着收口好几根？收口之后，收盘跌穿了那一段的最低价吗？跌出去的那一根放量了吗？',
               plan='建仓区从收口区间的最低价开始，往下半个 ATR。止损在区间中线。做空是反着来的：止损在上，目标在下。',
               none='它要先看到连着好几根的收口。最近没有，所以清单空着。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _arrays(P):
    """整段算一次（每个值只用到它和它之前的 K 线）：每根是不是收口、这一段收口从哪一根开始、均量。"""
    if 'sq' not in P:
        h, l, c, v = P['h'], P['l'], P['c'], P['v']
        n = len(c)
        mid, bu, bl = ind.boll(c, SOURCE['bb_n'], SOURCE['bb_k'])
        pc = np.concatenate((c[:1], c[:-1]))
        rng = ind.sma(np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc))), SOURCE['kc_n'])
        km = ind.sma(c, SOURCE['kc_n'])
        ku, kl = km + SOURCE['kc_k'] * rng, km - SOURCE['kc_k'] * rng
        on = np.zeros(n, bool)
        ok = np.isfinite(bu) & np.isfinite(ku)
        on[ok] = (bu[ok] < ku[ok]) & (bl[ok] > kl[ok])
        start = np.full(n, -1)
        for t in range(n):
            if on[t]:
                start[t] = start[t - 1] if t and on[t - 1] else t
        P['sq'] = dict(on=on, start=start, vma=ind.sma(v, EST['vol_n']))
    return P['sq']


def _core(P, j):
    d, h, l, c, v = P['d'], P['h'], P['l'], P['c'], P['v']
    S = _arrays(P)
    Lg = qm.long(P)
    W = dict(hi='最高' if Lg else '最低', lo='最低' if Lg else '最高', edge='上沿' if Lg else '下沿', brk='站上' if Lg else '跌穿', fall='跌回' if Lg else '涨回',
             under='以下' if Lg else '以上', chase='追高' if Lg else '追空')
    out = qm.blank(verdict_text='这套清单用不上', phase_text='无结构')
    e = next((t for t in range(j, max(-1, j - EST['look'] - 1), -1) if S['on'][t]), None)      # 最近一根收口
    if e is None:
        out['note'] = f'最近 {EST["look"]} 根里没有收口（布林带没缩进肯特纳通道里）。'
        out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
        return out
    s0 = int(S['start'][e])
    if e - s0 + 1 < EST['min_sq']:
        out['note'] = f'{d[s0]} 起收口了 {e - s0 + 1} 根，不到 {EST["min_sq"]} 根，算不上一段收口。'
        out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
        return out
    e2 = e if e < j else j - 1                               # 还在收口时，区间不含今天这一根
    hi, lo = float(np.max(h[s0:e2 + 1])), float(np.min(l[s0:e2 + 1]))
    H, half = hi - lo, (hi + lo) / 2
    a, cj = pt.atr(P, j), float(c[j])
    b = next((t for t in range(e2 + 1, j + 1) if c[t] > hi), None)                         # 收盘第一次站上区间上沿
    k1 = True
    k2 = b is not None and j - b < EST['fresh']
    vm = float(S['vma'][b - 1]) if b is not None and b > 0 and np.isfinite(S['vma'][b - 1]) else None
    k3 = b is not None and vm is not None and float(v[b]) >= EST['vol'] * vm
    fake = b is not None and any(c[t] < half for t in range(b, j + 1))
    why1 = f'{d[s0]} 到 {d[e]} 连续收口 {e - s0 + 1} 根；收口区间 {R(P, lo) if Lg else R(P, hi)} ~ {R(P, hi) if Lg else R(P, lo)}'
    why2 = (f'{d[b]} 收盘 {R(P, c[b])} {W["brk"]}了区间{W["edge"]} {R(P, hi)}' + ('' if b == j else f'，是 {j - b} 根之前') if b is not None else
            f'收盘还没{W["brk"]}区间{W["edge"]} {R(P, hi)}')
    why3 = (f'突破那根成交量 {qm.vol_text(v[b])}，是前 {EST["vol_n"]} 根均量的 {float(v[b]) / vm:.1f} 倍，' + ('够' if k3 else '不够') + f' {EST["vol"]:g} 倍'
            if b is not None and vm else '还没有突破，谈不上放量')
    checks = [qm.check('K1', '收口过', k1, why1, ask='最近有没有连着收口好几根？', yes='收口过', no='没有收口', sticker_yes='弹簧压紧了'),
              qm.check('K2', f'收盘突破{W["edge"]}', k2, why2, ask=f'收盘{W["brk"]}收口区间的{W["edge"]}了吗？', yes='突破了', no='还没突破', sticker_yes='冲出去了'),
              qm.check('K3', '突破放量', k3, why3, ask='冲出去的那一根放量了吗？', yes='放量了', no='没放量', sticker_yes='有人跟')]
    shapes = [qm.sh_box(P, s0, e2, lo, hi, 'zone', '收口区间', key='sq', alpha=0.12),
              qm.sh_hl(P, s0, half, 'fib', f'区间中线 {R(P, half)}', key='half', i2=j, dash=[2, 4], w=1)]
    legend = [qm.legend_item('sq', '浅色方框是收口区间：布林带缩进肯特纳通道里的那几根。越收越窄，往往是大行情之前的安静。'),
              qm.legend_item('half', f'灰色虚线是区间中线。突破之后收盘{W["fall"]}它{W["under"]}，就是假突破。')]
    if b is not None:
        shapes.append(qm.sh_badge(P, b, float(c[b]), '突', 'level', above=True, key='brk', first=True))
        legend.append(qm.legend_item('brk', f'“突”字是收盘第一次{W["brk"]}方框{W["edge"]}的那一根。'))
    out.update(phase='收口之后' if b is None else '突破之后', phase_text='收口之后' if b is None else '突破之后', list=KEY, checks=checks, shapes=shapes, legend=legend,
               _ev=s0, _from=b if b is not None else s0, story=f'{d[s0][5:]} 起收口 {e - s0 + 1} 根',
               squeeze=dict(start=d[s0], end=d[e], high=R(P, hi), low=R(P, lo), height=round(H, 4), breakout=d[b] if b is not None else None, still_on=bool(S['on'][j])))
    args = (hi, hi + EST['zone_atr'] * a, half, hi + H, hi + EST['t2_mult'] * H)
    t2_note = f'往外量 {EST["t2_mult"]:g} 个区间高度【估算】'
    if b is None:
        out.update(verdict='等', verdict_text='收口了，等突破', state='wait', pre=qm.preplan(P, *args),
                   text=f'{d[s0]} 起收口了 {e - s0 + 1} 根，还没突破。收盘{W["brk"]} {R(P, hi)} 而且放量，才算。')
        out['next_needs'] = [f'收盘{W["brk"]} {R(P, hi)}（收口区间{W["edge"]}），而且成交量过前 {EST["vol_n"]} 根均量的 {EST["vol"]:g} 倍']
    elif fake:
        out.update(phase='假突破', phase_text='假突破', verdict='已失效', verdict_text='突破后又掉回区间中线，假突破', state='dead',
                   text=f'{d[b]} 突破之后，收盘又{W["fall"]}区间中线 {R(P, half)}{W["under"]}，是假突破，这个结构作废。')
    elif not k3:
        out.update(verdict='不追', verdict_text='突破那根没放量，不算', state='avoid',
                   text=f'{d[b]} 收盘突破了区间{W["edge"]}，可是那一根没放量。没量的突破不算，按规则不追。')
        out['next_needs'] = [f'收盘{W["fall"]} {R(P, half)}（区间中线）{W["under"]}：假突破']
    elif not k2:
        out.update(verdict='不追', verdict_text='突破已经过去几根了，不追', state='avoid',
                   text=f'{d[b]} 就放量突破了，已经过去 {j - b} 根。这一段走出来了，按规则不追。')
        out['next_needs'] = [f'收盘{W["fall"]} {R(P, half)}（区间中线）{W["under"]}：假突破']
    elif cj - hi > EST['chase_atr'] * a:
        out.update(verdict='不追', verdict_text=f'放量突破了，但离{W["edge"]}太远，不{W["chase"]}', state='avoid', pre=qm.preplan(P, *args),
                   text=f'放量突破了收口区间，可是现价离{W["edge"]}已经 {(cj - hi) / a:.1f} 个 ATR。按规则不追，等它回到{W["edge"]}附近。')
        out['next_needs'] = [f'回到 {R(P, hi + EST["chase_atr"] * a)} 以内才不算追', f'收盘{W["fall"]} {R(P, half)}（区间中线）{W["under"]}：假突破']
    else:
        out.update(qm.plan(P, *args, t2_note))
        out.update(verdict='条件齐', verdict_text='条件齐了（未回测）', state='ready', zone_from=d[b],
                   text=f'收口 {e - s0 + 1} 根之后，放量收盘{W["brk"]}区间{W["edge"]}，三项都成立。这套规则没有回测过，这里只是把清单结果摆出来。')
        out['next_needs'] = [f'收盘{W["fall"]} {R(P, half)}（区间中线）{W["under"]}：假突破，认错']
    return qm.finish(out)
