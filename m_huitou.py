"""等回头 —— 录屏「回头战法」里面板上的模型。观察用，不给价位。因果，未回测。

面板上那一次（上行 · 短线）的说明原话：模拟行情中，价格回到半山腰并收在成本线上方。结论：回到成本线上。
录屏「回头战法 · 要点」（原话）：
  ① 大阴大阳远超 ATR　波动加剧
  ② 观察是否回到半山腰
  ③ 收在成本线下看空　线上看多
  ④ 观察线外风险　留意后续走势
三张证据：振幅远超 ATR；回到半山腰；收在成本线上。

规则（上行一侧；下行时上下翻过来）：
  K1 振幅远超 ATR：最近 40 根里有一根的振幅 ≥ 2.5 个 ATR【估算】。
  K2 回到半山腰：那一下之前 10 根的最高点，到之后的最低点，这一段的一半（0.5）被价格碰回来过。
  K3 收在成本线上：成本线是从那根大 K 线算起的锚定 VWAP，今天收盘在它上面。
结论：K2、K3 都成立 →「回到成本线上」；收在成本线下 →「收在成本线下」（录屏：线下看空）；其余 → 继续观察。
"""
import numpy as np

import qmodel as qm
import patterns as pt
from qmodel import R

KEY, VERSION, NAME = 'huitou', 'huitou-r1', '等回头'
KIND, DEFAULT_SIDE = 'watch', 'long'
DEFAULT_HZ = 20          # 录屏面板上这个模型用的周期
MIRRORED = ('short',)
TAGS = ('观察用',)
EXTRA = ('move',)
VIDEO = dict(half=0.5)
VIDEO_NOTE = dict(half='半山腰：这一段走过的多少')
EST = dict(big_atr=2.5, look=40, pre=10)
EST_NOTE = dict(big_atr='大阴大阳：振幅至少几个 ATR', look='只在最近多少根里找', pre='往前看几根找那一段的起点')
REFS = ('锚定 VWAP（Brian Shannon），录屏卡片：线上看多，线下看空', '斐波那契回撤 0.5（半山腰）')
NOTES = ('观察用：只告诉你价格和半山腰、成本线的关系，不给入场价位。', '没有回测过。照录屏的四条要点重写，不是原作者的代码。')

LEARN = dict(
    long=dict(idea_title='“等回头”在看什么？',
              idea='一根特别长的 K 线，比平时晃得猛得多，常常把止损扫掉。它不急着判断，先看两件事。价格能不能回到这一段的一半，也就是半山腰。收盘能不能站在成本线上面。',
              idea_note='对应录屏「回头战法」。录屏里面板叫「等回头」，用的是“上行”。',
              list_title='回头清单', list='三个问题。最近有没有一根振幅远超平时的大 K 线？价格回到半山腰了吗？收盘在成本线上面吗？两个都在上面，叫“回到成本线上”。',
              plan='', none='最近没有特别长的 K 线，这套观察用不上。',
              cards=[('g_avwap', '成本线（锚定 VWAP）是什么？', '从那根大 K 线开始，把每一笔成交的价格按成交量平均一下。它就是这些天里大家买进来的平均价。价格在它上面，这些人大多赚钱；在下面，大多亏钱。', None, 'chart')]),
    short=dict(idea_title='“等回头”的下行一侧在看什么？',
               idea='把上行那一侧上下翻过来。一根特别长的 K 线把价格猛地拉上去。它先看价格会不会回到这一段的一半，再看收盘是不是掉到成本线下面。',
               idea_note='录屏里用的是上行一侧，这一侧是翻过来用的。',
               list_title='回头清单', list='三个问题。最近有没有一根振幅远超平时的大 K 线？价格回到半山腰了吗？收盘在成本线下面吗？',
               plan='', none='最近没有特别长的 K 线，这套观察用不上。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _core(P, j):
    d, h, l, c = P['d'], P['h'], P['l'], P['c']
    Lg = qm.long(P)
    on, off = ('上', '下') if Lg else ('下', '上')
    out = qm.blank(verdict_text='这套观察用不上', phase_text='无结构')
    bb = pt.big_bar(P, j, EST['big_atr'], EST['look'])
    if bb is None:
        out['note'] = f'最近 {EST["look"]} 根里没有振幅超过 {EST["big_atr"]} 个 ATR 的大阴大阳。'
        out['text'] = out['note'] + '这套观察今天用不上。'
        return out
    t, m = bb
    a0 = max(0, t - EST['pre'])
    Ai = a0 + int(np.argmax(h[a0:t + 1]))
    Bi = t + int(np.argmin(l[t:j + 1]))
    A, B = float(h[Ai]), float(l[Bi])
    half = B + VIDEO['half'] * (A - B)
    back = Bi < j and float(np.max(h[Bi + 1:j + 1])) >= half
    av = pt.avwap(P, t, j)
    above = float(c[j]) > av
    checks = [qm.check('K1', '振幅远超 ATR', True, f'{d[t]} 那根振幅是平时（ATR）的 {m:.1f} 倍，波动加剧', ask='有没有一根远超平时的大 K 线？', yes='有，波动加剧', sticker_yes='波动大'),
              qm.check('K2', '回到半山腰', back, f'这一段从 {R(P, A)} 到 {R(P, B)}，半山腰在 {R(P, half)}：' + ('碰回来过' if back else '还没回到'), ask='回到半山腰了吗？', yes='回到半山腰了', no='还没回到半山腰',
                       sticker_yes='回头了', draw=[dict(type='level', price=R(P, half), label='半山腰')]),
              qm.check('K3', f'收在成本线{on}', above, f'成本线（从 {d[t]} 算起的锚定 VWAP）在 {R(P, av)}，今天收盘 {R(P, c[j])}：' + (f'在线{on}' if above else f'在线{off}'),
                       ask=f'收在成本线{on}吗？', yes=f'在成本线{on}', no=f'在成本线{off}', sticker_yes=f'线{on}', sticker_no=f'线{off}')]
    vw = hs_series(P, t, j)
    shapes = [qm.sh_line(P, t, vw, 'vwap', '成本线', key='vwap', w=1.8), qm.sh_hl(P, Ai, half, 'fib', f'半山腰 {R(P, half)}', key='half', dash=[4, 4], w=1.2),
              qm.sh_dot(P, t, float(h[t]), 'warn', f'振幅 {m:.1f}×ATR', key='big', ring=True)]
    legend = [qm.legend_item('vwap', '黄线是成本线：从那根大 K 线算起，大家买进来的平均价。线上看多，线下看空。'),
              qm.legend_item('half', '灰色虚线是半山腰：这一段走过的一半。'), qm.legend_item('big', '带圈的点是那根振幅远超平时的大 K 线。')]
    out.update(phase='大 K 线之后', phase_text='大 K 线之后', list=KEY, checks=checks, shapes=shapes, legend=legend, _ev=t,
               move=dict(big=d[t], atr_mult=round(m, 1), start=R(P, A), end=R(P, B), half=R(P, half), cost=R(P, av)), story=f'{d[t][5:]} 一根振幅 {m:.1f} 倍 ATR 的大 K 线')
    if back and above:
        out.update(verdict='回到成本线', verdict_text='回到成本线上' if Lg else '回到成本线下', state='watch',
                   text=f'价格回到半山腰，并收在成本线{on}方。录屏说：线{on}看{"多" if Lg else "空"}。还要留意线外的风险，看后面怎么走。')
    elif not above:
        out.update(verdict='线外', verdict_text=f'收在成本线{off}', state='risk',
                   text=f'收盘在成本线{off}面（{R(P, av)}）。录屏说：线{off}看{"空" if Lg else "多"}。' + ('已经回到过半山腰，但没站住。' if back else '也还没回到半山腰。'))
    else:
        out.update(verdict='继续观察', verdict_text='继续观察', state='watch', text=f'收在成本线{on}面，但还没回到半山腰 {R(P, half)}。继续看。')
    out['next_needs'] = [f'碰回半山腰 {R(P, half)}', f'收盘守在成本线 {R(P, av)} {on}面']
    return qm.finish(out)


def hs_series(P, a, j):
    """The anchored VWAP from bar a to bar j, in working prices (for qm.sh_line)."""
    w = P['CV'][a + 1:j + 2] - P['CV'][a]
    w = np.where(w > 0, w, np.nan)
    return (P['CTV'][a + 1:j + 2] - P['CTV'][a]) / w
