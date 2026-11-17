"""不追半山腰 v2.1 —— 录屏「三角不追战法」里面板上的模型。因果，未回测。

面板上那一次（做多 · 中线 60 日）的说明原话：收敛三角向上突破，回踩上沿不破，突破当天放量。价格在建仓区内，跌破止损离场。
画面上的字：建仓区就在三角上沿；止损卡在回踩低点下；目标三角开口那么高。
录屏「三角不追战法 · 六条要点」（结尾那页是半透明的，能读到的原话）：
  ① 两条边一连　先认出三角
  ② 上沿不追　下沿不追
  ③ 中间控制点　不碰
  ④ 收在三角外　RSI 过 60
  ⑤ 回踩不进去　再追
  ⑥ 止损回踩低点下　目标三角开口
「艾略特三角波」卡片：五段走满（A-B-C-D-E），顺势冲出。

规则（做多一侧；做空时上下翻过来，就是向下跌出三角）：
  三角：一串摆动点，高点一个比一个低、低点一个比一个高，至少两高两低。还在三角里面时：不追（②③）。
  K1 收在三角外：收盘站到上沿上面；之后收盘又掉回三角里（低于上沿半个 ATR【估算】）就是假突破，作废。
  K2 RSI 过 60，突破当天放量：突破以来 RSI 到过 60 以上；突破那根的量 ≥ 前 5 根均量的 1.5 倍【估算】。
  K3 回踩不进去：突破之后回踩，最低点碰到上沿附近（半个 ATR 以内【估算】），收盘没掉回去。
三项齐了：建仓区 = 上沿到它上方半个 ATR【估算】；止损 = 回踩低点下方 1%【估算】；第一目标 = 突破处 + 三角开口高度；第二目标 = 突破处 + 1.382 倍开口【估算，从面板的数字反推】。
"""
import numpy as np

import qmodel as qm
import patterns as pt
from qmodel import R, dn, vol_text

KEY, VERSION, NAME = 'sanjiao', 'sanjiao-r1', '不追半山腰 v2.1'
KIND, DEFAULT_SIDE = 'trade', 'long'
DEFAULT_HZ = 60          # 录屏面板上这个模型用的周期
MIRRORED = ('short',)
SIDE_NAME = dict(short='做空：向下跌出三角')
TAGS = ('参数含估算',)
EXTRA = ('triangle',)
VIDEO = dict(rsi=60)
VIDEO_NOTE = dict(rsi='突破之后 RSI 要过多少')
EST = dict(vol=1.5, back_atr=0.5, near_atr=0.5, zone_atr=0.5, stop=0.01, t2_mult=1.382, max_age=40)
EST_NOTE = dict(vol='突破当天放量：至少是前 5 根均量的几倍', back_atr='收盘掉回上沿下方几个 ATR 算假突破', near_atr='回踩碰到上沿附近：几个 ATR 以内',
                zone_atr='建仓区是上沿往上几个 ATR', stop='止损放在回踩低点外侧多远', t2_mult='第二目标是几倍三角开口', max_age='突破之后最多跟踪几根')
REFS = ('艾略特三角波（A-B-C-D-E 五段收敛，之后顺势冲出），录屏卡片', '收敛三角：上沿连高点、下沿连低点，两线收敛（patterns.triangle）')
NOTES = ('没有回测过。照录屏的六条要点重写，不是原作者的代码。',)

LEARN = dict(
    long=dict(idea_title='“不追半山腰”在看什么？',
              idea='价格越走越窄，高点一次比一次低，低点一次比一次高，画出来是个三角。在三角里面追，追在上沿、下沿、中间都容易被打脸。它等价格收到三角外面，再回踩上沿不掉回去，才说条件齐了。',
              idea_note='对应录屏「三角不追战法」。录屏里面板叫「不追半山腰 v2.1」。',
              list_title='三角清单', list='三个问题。收盘站到三角外面了吗？突破那天放量了吗，RSI 过了 60 吗？回踩上沿，没有掉回三角里吗？三个都“是”，才说条件齐了。',
              plan='建仓区就在三角上沿。止损卡在回踩的低点下面。目标是三角开口那么高：从突破的地方往上量一个开口。',
              none='它要先看到一个收敛三角。现在没有这样的走势，所以清单空着。', cards=[]),
    short=dict(idea_title='“不追半山腰”的做空一侧在看什么？',
               idea='把做多那套上下翻过来。价格越走越窄，画出一个三角。它等价格收到三角下面，再反抽到下沿不回去，才说条件齐了。',
               idea_note='做空这一侧录屏里没有讲过，是把同一套规则翻过来用的。',
               list_title='三角清单', list='三个问题。收盘跌到三角外面了吗？跌破那天放量了吗？反抽下沿，没有回到三角里吗？',
               plan='建仓区就在三角下沿。止损卡在反抽的高点上面。目标是从跌破的地方往下量一个开口。做空是反着来的：止损在上，目标在下。',
               none='它要先看到一个收敛三角。现在没有这样的走势，所以清单空着。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _core(P, j):
    d, h, l, c, v = P['d'], P['h'], P['l'], P['c'], P['v']
    X = qm.ix(P)
    Lg = qm.long(P)
    edge, brk_v, back_w = ('上沿', '站到', '回踩') if Lg else ('下沿', '跌到', '反抽')
    out = qm.blank(verdict_text='这套清单用不上', phase_text='无结构')
    tr = pt.triangle(P, j)
    if tr is None:
        out['note'] = '最近没有收敛三角（高点一次比一次低、低点一次比一次高，至少两高两低）。'
        out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
        return out
    up_, lo_, H, b, f0, last = tr['upper'], tr['lower'], tr['height'], tr['brk'], tr['first'], tr['last']
    a = pt.atr(P, j)
    hi0, lo0 = tr['highs'][0], tr['lows'][0]
    shapes = [qm.sh_seg(P, (hi0[0], hi0[1]), (j, up_(j)), 'tri', '三角' + ('上沿' if Lg else '下沿'), key='tri', w=1.6),
              qm.sh_seg(P, (lo0[0], lo0[1]), (j, lo_(j)), 'tri', None, w=1.2, dash=[5, 4])]
    for n, x in enumerate(tr['pts']):
        shapes.append(qm.sh_badge(P, x[0], x[1], 'ABCDEF'[n], 'tri', above=x[2] == 1))
    mount = pt.poc(P, f0, last)
    shapes.append(qm.sh_hl(P, f0, mount, 'mute', f'中间控制点 {R(P, mount)}', key='poc', i2=last, dash=[2, 3], w=1))
    legend = [qm.legend_item('tri', '黄色的两条线就是三角的两条边：高点连成一条，低点连成一条，越收越窄。字母是转折点。'),
              qm.legend_item('poc', '灰色短虚线是三角中间的控制点：这一段里成交最多的价位。录屏说这里不碰。')]
    out.update(list=KEY, shapes=shapes, legend=legend, _ev=f0, _from=last, triangle=dict(height=qm.r2(H), edge=R(P, up_(j)), poc=R(P, mount), points=len(tr['pts'])))
    if b is None:
        inside = float(c[j]) >= lo_(j)
        out.update(phase='三角里', phase_text='三角里面', verdict='不追', state='avoid' if inside else 'na',
                   verdict_text='三角里面：上沿不追、下沿不追、中间不碰' if inside else ('跌破下沿是陷阱' if Lg else '涨破上沿是陷阱'),
                   text=(f'价格还在三角里面（{edge} {R(P, up_(j))}）。按规则在里面不追：上沿不追，下沿不追，中间的控制点不碰。等收盘{brk_v}三角外面。') if inside else
                   ('价格从另一边掉出了三角。录屏说这一边是陷阱，这套清单不做。'))
        out['next_needs'] = [f'收盘{brk_v}{edge} {R(P, up_(j))} 外面，才算出了三角']
        return qm.finish(out)
    if j - b > EST['max_age']:
        out.update(phase='过期', phase_text='突破太久了', verdict='不适用', state='na', verdict_text='突破已经过去太久', text=f'{d[b]} 就出了三角，已经过去 {j - b} 根，这一段不再跟踪。')
        return qm.finish(out)
    fail = next((t for t in range(b + 1, j + 1) if c[t] < up_(t) - EST['back_atr'] * a), None)
    if fail is not None:
        out.update(phase='假突破', phase_text='假突破', verdict='已失效', state='dead', verdict_text='掉回三角里，假突破',
                   text=f'{d[b]} 出了三角，{d[fail]} 收盘又掉回{edge}里面，是假突破，这个结构作废。')
        return qm.finish(out)
    vr = pt.vol_ratio(P, b)
    rsi = X['rsi']
    rmax = float(np.max(rsi[b:j + 1]))
    k2 = vr is not None and vr >= EST['vol'] and rmax >= VIDEO['rsi']
    ri = b + 1 + int(np.argmin(l[b + 1:j + 1])) if j > b else None
    k3 = ri is not None and l[ri] <= up_(ri) + EST['near_atr'] * a
    checks = [qm.check('K1', '收在三角外', True, f'{d[b]} 收盘 {R(P, c[b])} {brk_v}了{edge} {R(P, up_(b))} 外面，之后没掉回去', ask='收在三角外了吗？', yes='收出三角了', sticker_yes='出来了'),
              qm.check('K2', f'放量，RSI 过 {VIDEO["rsi"]}', k2, (f'突破那天成交量是前 5 根均量的 {vr:.1f} 倍；' if vr else '突破那天的量比不了；') +
                       (f'突破以来 RSI 最高 {rmax:.1f}' if Lg else f'突破以来 RSI 最低 {100 - rmax:.1f}（做空一侧看 40 下面）') + ('，够了' if k2 else '，不够'),
                       ask='突破放量、RSI 也过线了吗？', yes='放量又过线', no='量或 RSI 不够', sticker_yes='有劲'),
              qm.check('K3', f'{back_w}不进去', k3, (f'{back_w}最{"低" if Lg else "高"}到 {R(P, l[ri])}（{d[ri]}），{edge}那天在 {R(P, up_(ri))}：' + ('碰到了，没掉回去' if k3 else '还没回到' + edge + '附近')) if ri is not None else f'突破之后还没{back_w}',
                       ask=f'{back_w}{edge}没掉回去吗？', yes=f'{back_w}没进去', no=f'还没{back_w}', sticker_yes='站稳了')]
    out.update(phase='突破后', phase_text='出了三角', checks=checks, story=f'{d[b][5:]} 收出三角，开口 {qm.r2(abs(H))}')
    if k2 and k3:
        t1 = up_(b) + H
        out.update(qm.plan(P, up_(j), up_(j) + EST['zone_atr'] * a, min(dn(float(l[ri]), EST['stop']), dn(up_(j), EST['stop'])), t1, up_(b) + EST['t2_mult'] * H, '1.382 倍开口【估算】'))
        out.update(verdict='条件齐', verdict_text='条件齐了（未回测）', state='ready', zone_from=d[b],
                   text=f'收敛三角向{"上" if Lg else "下"}突破，{back_w}{edge}不破，突破当天放量。价格在建仓区内，{"跌破" if Lg else "涨破"}止损离场。这套规则没有回测过，这里只是把清单结果摆出来。')
    else:
        n = sum(1 for x in checks if x['ok'])
        far = float(c[j]) > up_(j) + 2 * a and not k3
        out.update(verdict='等' if not far else '不追', verdict_text=(f'清单 {n}/3，等{back_w}' if not far else f'离{edge}太远，不追，等{back_w}'), state='wait' if not far else 'avoid',
                   text=f'已经收出三角，清单 {n}/3。还缺：' + '、'.join(x['name'] for x in checks if not x['ok']) + '。录屏说：回踩不进去，再追。')
    out['next_needs'] = [f'{back_w}到{edge} {R(P, up_(j))} 附近不掉回去', f'收盘掉回{edge}里面（{R(P, up_(j) - EST["back_atr"] * a)} 外侧）：假突破，作废']
    return qm.finish(out)
