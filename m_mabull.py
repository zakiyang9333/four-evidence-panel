"""均线多头 + MACD 背离 —— 国内看盘软件里常用的两条规则（均线多头排列、MACD 顶背离），按公开写法重写。因果，未回测。

公开写法：
  均线多头排列：5 日、10 日、20 日、60 日均线从上到下排好（MA5 > MA10 > MA20 > MA60），而且四条都在往上走。
  MACD：快线 12、慢线 26、信号线 9（国内软件的通行参数）。顶背离：价格的高点一个比一个高，MACD 的 DIF 却一个比一个低，说明往上的劲在变小。
清单（按做多一侧写；做空时整张图上下翻过来：空头排列、反弹到 20 日线不过、没有底背离）：
  K1 均线多头排列：四条均线从上到下排好，而且都比 3 根【估算】之前高。
  K2 回踩 20 日线不破：最近 5 根【估算】里，最低价回到 20 日线附近（半个 ATR 以内【估算】），收盘都没跌破它。
  K3 没有 MACD 顶背离：最近两个确认的高点，如果后一个更高，DIF 也要更高。
三项齐了：建仓区 = 20 日线到它上方半个 ATR【估算】；止损 = 这几根回踩的最低价下方 1%【估算】；
第一目标 = 最近 20 根的最高价（前高）；第二目标 = 前高再往上量一段“前高到回踩低点”。
"""
import numpy as np

import patterns as pt
import qmodel as qm
from qmodel import R, dn

KEY, VERSION, NAME = 'mabull', 'mabull-r1', '均线多头 + MACD 背离'
KIND, DEFAULT_SIDE = 'trade', 'long'
DEFAULT_HZ = 60
MIRRORED = ()                     # 多头排列、空头排列都是常用写法
TAGS = ('开源规则', '参数含估算')
EXTRA = ('mabull',)
VIDEO, VIDEO_NOTE = {}, {}
SOURCE = dict(ma1=5, ma2=10, ma3=20, ma4=60, fast=12, slow=26, signal=9)
SOURCE_NOTE = dict(ma1='最短那条均线（日）', ma2='第二条均线（日）', ma3='第三条均线（日），也是回踩看的那一条', ma4='最长那条均线（日）', fast='MACD 快线',
                   slow='MACD 慢线', signal='MACD 信号线')
EST = dict(rise=3, look=5, touch_atr=0.5, zone_atr=0.5, stop=0.01, high_n=20, swing_look=120)
EST_NOTE = dict(rise='均线和几根之前比，看是不是在往上走', look='回踩看最近几根', touch_atr='最低价离 20 日线几个 ATR 以内算回踩到了', zone_atr='建仓区是 20 日线往外几个 ATR',
                stop='止损放在回踩低点外侧多远', high_n='前高看最近几根', swing_look='找背离时往回看多少根')
REFS = ('均线多头排列：国内看盘软件的通行写法（MA5、10、20、60）',
        'MACD 顶背离 / 底背离：国内看盘软件的通行写法（12、26、9），在确认的摆动高点上比较 DIF')
NOTES = ('没有回测过。照国内常用的均线、MACD 写法重写，不是原作者的代码。', '“回踩 20 日线”和“背离”的门槛都是估的【估算】，模型页里一条条列着。',
         '摆动高点要等之后走出一段才确认，所以背离会晚几根才看得到。')

LEARN = dict(
    long=dict(idea_title='“均线多头 + MACD 背离”在看什么？',
              idea='四条均线从短到长，从上往下排好，而且都在往上走，叫多头排列。这时候价格回到二十日线附近、没跌破，它才看。再看一眼 MACD，没有顶背离才算。',
              idea_note='国内看盘软件里最常用的两条规则。这里照公开的写法重写。',
              list_title='三项清单', list='三个问题。均线是多头排列吗？最近回到二十日线附近、收盘没跌破吗？最近两个高点，有没有价格更高、MACD 却更低的顶背离？',
              plan='建仓区在二十日线到它上面半个 ATR。止损放在这几根回踩的最低价下面一点。第一目标是最近的前高。',
              none='均线现在不是多头排列，所以这套清单用不上。',
              cards=[('g_div', '什么是顶背离？', '价格又冲出一个更高的高点，可是 MACD 的快线没跟着更高。就像人跑上坡，脚步越来越慢。它提醒你：往上的劲在变小。', None, 'chart')]),
    short=dict(idea_title='“均线多头 + MACD 背离”的做空一侧在看什么？',
               idea='四条均线从短到长，从下往上排好，而且都在往下走，叫空头排列。这时候价格反弹到二十日线附近、没涨过去，它才看。再看一眼 MACD，没有底背离才算。',
               idea_note='空头排列、底背离也是国内软件常用的写法。',
               list_title='三项清单', list='三个问题。均线是空头排列吗？最近反弹到二十日线附近、收盘没涨过去吗？最近两个低点，有没有价格更低、MACD 却更高的底背离？',
               plan='建仓区在二十日线到它下面半个 ATR。止损放在这几根反弹的最高价上面一点。做空是反着来的：止损在上，目标在下。',
               none='均线现在不是空头排列，所以这套清单用不上。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _core(P, j):
    d, h, l, c = P['d'], P['h'], P['l'], P['c']
    Lg = qm.long(P)
    W = dict(align='多头排列' if Lg else '空头排列', up='往上' if Lg else '往下', back='回踩' if Lg else '反弹', fall='跌破' if Lg else '涨过', div='顶背离' if Lg else '底背离',
             hi='高' if Lg else '低', above='上方' if Lg else '下方', prior='前高' if Lg else '前低')
    out = qm.blank(verdict_text='这套清单用不上', phase_text='无结构')
    ns = [SOURCE['ma1'], SOURCE['ma2'], SOURCE['ma3'], SOURCE['ma4']]
    ms = [qm.ma(P, n) for n in ns]
    r = EST['rise']
    if j < ns[-1] + r or not all(np.isfinite(m[j]) and np.isfinite(m[j - r]) for m in ms):
        out['note'] = f'还不到 {ns[-1] + r} 根 K 线，算不出 {ns[-1]} 日均线的走向。'
        out['text'] = out['note']
        return out
    v = [float(m[j]) for m in ms]
    aligned = v[0] > v[1] > v[2] > v[3]
    rising = all(float(m[j]) > float(m[j - r]) for m in ms)
    k1 = aligned and rising
    ma20 = ms[2]
    a, cj = pt.atr(P, j), float(c[j])
    w = list(range(j - EST['look'] + 1, j + 1))
    ti = min(w, key=lambda t: l[t] - ma20[t])                 # 回得最深的那一根
    touch = float(l[ti] - ma20[ti]) <= EST['touch_atr'] * a
    hold = all(c[t] >= ma20[t] for t in w)
    k2 = touch and hold
    X = qm.ix(P)
    piv = [p for p in qm.pivots(P, j, max(0, j - EST['swing_look'])) if p[2] == 1]
    div = len(piv) >= 2 and piv[-1][1] > piv[-2][1] and float(X['dif'][piv[-1][0]]) < float(X['dif'][piv[-2][0]])
    k3 = not div
    names = '、'.join(f'MA{n} {R(P, x)}' for n, x in zip(ns, v))
    why1 = f'{names}：' + (('排好了' if aligned else '没排好') + '，' + ('四条都在' + W['up'] if rising else '不是四条都在' + W['up']))
    why2 = (f'最近 {EST["look"]} 根里，{d[ti]} 的最{"低" if Lg else "高"}价 {R(P, l[ti])}，20 日线 {R(P, ma20[ti])}：' +
            ('回到了它附近' if touch else f'离它还有 {abs(float(l[ti] - ma20[ti])) / a:.1f} 个 ATR') + '；收盘' + ('一直在它' + W['above'] if hold else '有一根' + W['fall'] + '了它'))
    if len(piv) >= 2:
        (i1, p1, _), (i2, p2, _) = piv[-2], piv[-1]
        why3 = (f'最近两个{W["hi"]}点 {R(P, p1)}（{d[i1]}）→ {R(P, p2)}（{d[i2]}），DIF {abs(float(X["dif"][i1])):.2f} → {abs(float(X["dif"][i2])):.2f}：' +
                (W['div'] if div else ('价格没创新' + W['hi'] if p2 <= p1 else 'DIF 也跟着更' + ('高' if Lg else '低'))))
    else:
        why3 = f'最近 {EST["swing_look"]} 根里确认的{W["hi"]}点不到两个，比不了'
    checks = [qm.check('K1', f'均线{W["align"]}', k1, why1, ask=f'均线是{W["align"]}吗？', yes=f'{W["align"]}', no=f'不是{W["align"]}', sticker_yes='顺势'),
              qm.check('K2', f'{W["back"]} 20 日线不破', k2, why2, ask=f'{W["back"]}到 20 日线附近、收盘没{W["fall"]}吗？', yes=f'{W["back"]}不破', no=f'还没{W["back"]}到位' if hold else f'{W["fall"]}了',
                       sticker_yes='有人接' if Lg else '有人压'),
              qm.check('K3', f'没有 MACD {W["div"]}', k3, why3, ask=f'没有 MACD {W["div"]}吗？', yes=f'没有{W["div"]}', no=f'有{W["div"]}', sticker_yes='劲还在', sticker_no='劲变小')]
    i0 = max(ns[-1], j - 79)
    shapes = [qm.sh_line(P, i0, ma20[i0:j + 1], 'boll', 'MA20', key='ma20', w=1.4), qm.sh_line(P, i0, ms[3][i0:j + 1], 'level', 'MA60', key='ma60', w=1.2),
              qm.sh_line(P, i0, ms[0][i0:j + 1], 'mute', 'MA5', w=1), qm.sh_line(P, i0, ms[1][i0:j + 1], 'mute', 'MA10', w=1)]
    legend = [qm.legend_item('ma20', '浅蓝色线是 20 日均线：' + W['back'] + '看的就是它。'), qm.legend_item('ma60', '橙色线是 60 日均线，最长那一条。灰色细线是 5 日、10 日均线。')]
    if div:
        (i1, p1, _), (i2, p2, _) = piv[-2], piv[-1]
        shapes.append(qm.sh_seg(P, (i1, p1), (i2, p2), 'risk', W['div'], key='div', dash=[4, 4]))
        legend.append(qm.legend_item('div', f'红色虚线连着最近两个{W["hi"]}点：价格更{W["hi"]}了，MACD 却没跟上，这就是{W["div"]}。'))
    out.update(list=KEY, checks=checks, shapes=shapes, legend=legend, _ev=ti if k1 else None, _from=w[0] if k1 else None,
               mabull=dict(ma=dict(zip([f'MA{n}' for n in ns], [R(P, x) for x in v])), divergence=bool(div)))
    if not k1:
        out.update(phase='不是' + W['align'], phase_text='不是' + W['align'], verdict='不适用', state='na', verdict_text=f'均线不是{W["align"]}，这套清单用不上',
                   note=f'均线现在不是{W["align"]}（{why1}）。')
        out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
        out['next_needs'] = [f'MA5、10、20、60 从{"上" if Lg else "下"}到{"下" if Lg else "上"}排好，而且都在{W["up"]}走']
        return qm.finish(out)
    hi20 = float(np.max(h[max(0, j - EST['high_n'] + 1):j + 1]))        # 前高（工作方向的最高）
    low_w = float(min(l[t] for t in w))
    z1, z2 = float(ma20[j]), float(ma20[j]) + EST['zone_atr'] * a
    out.update(phase=W['align'], phase_text=W['align'])
    if not k3:
        out.update(verdict='不追', verdict_text=f'有 MACD {W["div"]}，不追', state='avoid',
                   text=f'均线是{W["align"]}，可是最近两个{W["hi"]}点出现了 MACD {W["div"]}：往{W["up"][1]}的劲在变小。按这套规则不追。')
        out['next_needs'] = [f'再出一个更{W["hi"]}的{W["hi"]}点、DIF 也更{"高" if Lg else "低"}，{W["div"]}才算解除']
    elif k2:
        out.update(qm.plan(P, z1, z2, dn(low_w, EST['stop']), hi20, hi20 + (hi20 - low_w), f'{W["prior"]}再往外量一段“{W["prior"]}到{W["back"]}低点”'))
        out.update(verdict='条件齐', verdict_text='条件齐了（未回测）', state='ready', zone_from=d[ti],
                   text=f'均线{W["align"]}，{W["back"]} 20 日线没{W["fall"]}，没有 MACD {W["div"]}，三项都成立。这套规则没有回测过，这里只是把清单结果摆出来。')
        out['next_needs'] = [f'收盘{W["fall"]} 20 日线（{R(P, ma20[j])}）：这一次{W["back"]}不算数', f'均线不再是{W["align"]}：清单用不上']
    else:
        out.update(verdict='等', verdict_text=f'{W["align"]}，等{W["back"]} 20 日线' if hold else f'{W["align"]}，但最近收盘{W["fall"]}了 20 日线，等重新站稳', state='wait',
                   pre=qm.preplan(P, z1, z2, dn(min(low_w, z1), EST['stop']), hi20, hi20 + (hi20 - min(low_w, z1))),
                   text=(f'均线是{W["align"]}，没有 {W["div"]}。现价离 20 日线还有 {abs(cj - float(ma20[j])) / a:.1f} 个 ATR，等它{W["back"]}到附近、收盘不{W["fall"]}。' if hold else
                         f'均线是{W["align"]}，没有 {W["div"]}，可是最近 {EST["look"]} 根里有收盘{W["fall"]}了 20 日线。等它重新站稳、再{W["back"]}不破。'))
        out['next_needs'] = [f'最{"低" if Lg else "高"}价回到 {R(P, float(ma20[j]) + EST["touch_atr"] * a)} 以内（20 日线外 {EST["touch_atr"]:g} 个 ATR），收盘不{W["fall"]} 20 日线']
    return qm.finish(out)
