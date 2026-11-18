"""阴跌雷达 —— 录屏「不抗单战法（阴跌）」里面板上的模型。观察用，不给价位。因果，未回测。

面板上那一次（下行 · 中线）的结论：留意风险。说明原话：高点逐级下移，反弹受阻于均价线，下行结构未破。
画面上：观察区压在均价线上；风险参考在反弹顶上面；“跟我那三样一条不差”。
录屏里的三样：① 站不回均价，别谈回本（均价线 = 从高点算起的锚定 VWAP）② 头顶就是均价线，上影一碰就缩回去 ③ 跌得越慢，套得越深（回归趋势一路向下）。

规则（下行一侧；上行时上下翻过来，就是“阴涨”：低点逐级上移、回调被均价线托住）：
  K1 高点逐级下移：最近三个反弹高点一个比一个低。
  K2 反弹受阻于均价线：最近两次反弹里，至少一次碰到均价线附近（半个 ATR 以内【估算】）又缩回去；今天收盘也在线下。
  K3 下行结构未破：收盘没有站上最近一个反弹高点，最近 40 根的回归趋势还向下【估算】。
三样都在 →「留意风险」；结构破了 → 继续观察。
"""
import numpy as np

import indicators as ind
import qmodel as qm
import patterns as pt
from qmodel import R

KEY, VERSION, NAME = 'yindie', 'yindie-r1', '阴跌雷达'
KIND, DEFAULT_SIDE = 'watch', 'short'
DEFAULT_HZ = 60          # 录屏面板上这个模型用的周期
MIRRORED = ('long',)
TAGS = ('观察用',)
EXTRA = ('radar',)
VIDEO = {}
VIDEO_NOTE = {}
EST = dict(look=160, touch_atr=0.5, reg_n=40)
EST_NOTE = dict(look='找高点和均价线起点的回看根数', touch_atr='碰到均价线附近：几个 ATR 以内', reg_n='回归趋势看最近多少根')
REFS = ('锚定 VWAP（Brian Shannon），录屏卡片：站不回均价，别谈回本', '回归趋势：一段收盘价的最小二乘直线（indicators.linreg_channel）')
NOTES = ('观察用：只告诉你阴跌的样子还在不在，不给价位。', '没有回测过。照录屏面板上的说明和三样证据重写，不是原作者的代码。')

LEARN = dict(
    short=dict(idea_title='“阴跌雷达”在看什么？',
               idea='暴跌会让人害怕，阴跌只会让人等。每天跌一点，扛着扛着就腰斩了。它盯三样：高点是不是一个比一个低，反弹是不是一碰均价线就缩回去，往下的趋势有没有被打破。',
               idea_note='对应录屏「不抗单战法」。录屏里面板叫「阴跌雷达」，用的是“下行”。',
               list_title='阴跌清单', list='三个问题。反弹的高点一个比一个低吗？反弹一碰均价线就缩回去吗？往下的趋势还没被打破吗？三样都在，它就说“留意风险”。',
               plan='', none='最近看不出高点一个比一个低，这套观察用不上。',
               cards=[('g_reg', '回归趋势是什么？', '把最近四十根的收盘价，用一把尺子尽量贴着画一条直线。线往下斜，就是整体在往下走。跌得越慢，这条线越平，越容易让人以为快到底了。', None, 'chart')]),
    long=dict(idea_title='“阴跌雷达”的上行一侧在看什么？',
              idea='把下行那一侧上下翻过来。它看价格是不是在一点一点往上磨：低点一个比一个高，回调一碰均价线就被托住。对手里有空单的人，这是要留意的风险。',
              idea_note='录屏里用的是下行一侧，这一侧是翻过来用的。',
              list_title='慢涨清单', list='三个问题。回调的低点一个比一个高吗？回调一碰均价线就被托住吗？往上的趋势还没被打破吗？',
              plan='', none='最近看不出低点一个比一个高，这套观察用不上。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _core(P, j):
    d, h, l, c = P['d'], P['h'], P['l'], P['c']
    Lg = qm.long(P)
    W = dict(hi='低点' if Lg else '高点', step='上移' if Lg else '下移', rally='回调' if Lg else '反弹', under='上' if Lg else '下', over='下' if Lg else '上',
             trend='上行' if Lg else '下行')
    out = qm.blank(verdict_text='这套观察用不上', phase_text='无结构')
    w0 = max(0, j - EST['look'])
    piv = qm.pivots(P, j, w0)
    lows = [x for x in piv if x[2] == -1]
    if len(lows) < 3:
        out['note'] = f'最近 {EST["look"]} 根里{W["rally"]}的{W["hi"]}不够三个，看不出逐级{W["step"]}。'
        out['text'] = out['note'] + '这套观察今天用不上。'
        return out
    p1, p2, p3 = lows[-3:]
    anc = w0 + int(np.argmin(l[w0:p1[0] + 1]))
    vw = (P['CTV'][anc + 1:j + 2] - P['CTV'][anc]) / np.where(P['CV'][anc + 1:j + 2] - P['CV'][anc] > 0, P['CV'][anc + 1:j + 2] - P['CV'][anc], np.nan)
    av = float(vw[-1])
    k1 = p1[1] < p2[1] < p3[1]
    near = lambda x: x[1] <= vw[x[0] - anc] + EST['touch_atr'] * pt.atr(P, x[0]) and c[x[0]] > vw[x[0] - anc]
    touched = [x for x in (p2, p3) if near(x)]
    k2 = bool(touched) and float(c[j]) > av
    reg = ind.linreg_channel(c, max(0, j - EST['reg_n'] + 1), j)
    k3 = float(c[j]) > p3[1] and reg['slope'] > 0
    checks = [qm.check('K1', f'{W["hi"]}逐级{W["step"]}', k1, f'最近三次{W["rally"]}的{W["hi"]}：{R(P, p1[1])} → {R(P, p2[1])} → {R(P, p3[1])}' + ('，一个比一个' + ('高' if Lg else '低') if k1 else '，不是一路' + W['step']),
                       ask=f'{W["hi"]}一个比一个{"高" if Lg else "低"}吗？', yes=f'{W["hi"]}逐级{W["step"]}', no=f'没有逐级{W["step"]}', sticker_yes=f'逐级{W["step"]}'),
              qm.check('K2', f'{W["rally"]}受阻于均价线', k2, (f'{"、".join(d[x[0]] for x in touched)} 那次{W["rally"]}碰到均价线又缩回去；' if touched else f'最近两次{W["rally"]}都没碰到均价线；') +
                       f'均价线现在 {R(P, av)}，收盘在线{W["under"] if float(c[j]) > av else W["over"]}', ask=f'{W["rally"]}一碰均价线就缩回去吗？', yes='一碰就缩回去', no='没受阻', sticker_yes='受阻'),
              qm.check('K3', f'{W["trend"]}结构未破', k3, f'收盘 {R(P, c[j])}，最近一次{W["rally"]}的{W["hi"]} {R(P, p3[1])}；回归趋势每根 {"+" if (reg["slope"] > 0) == Lg else "−"}{abs(reg["slope"]):.3f}' +
                       ('，结构还在' if k3 else '，结构破了'), ask=f'{W["trend"]}结构还在吗？', yes='结构还在', no='结构破了', sticker_yes='没破')]
    n0 = max(0, j - EST['reg_n'] + 1)
    shapes = [qm.sh_line(P, anc, vw, 'vwap', '均价线', key='vwap', w=1.8),
              qm.sh_hl(P, max(anc, j - 30), av, 'zone', f'观察区 · 均价线 {R(P, av)}', key='watch', dash=[6, 4], w=1.2),
              qm.sh_hl(P, p3[0], p3[1], 'risk', f'风险参考 · {W["rally"]}{"底" if Lg else "顶"} {R(P, p3[1])}', key='risk', dash=[3, 4], w=1.2),
              qm.sh_seg(P, (n0, reg['start']), (j, reg['end']), 'wave', '回归趋势', key='reg', dash=[5, 4]),
              qm.sh_badge(P, p1[0], p1[1], '1', 'push', above=False, key='steps', first=True), qm.sh_badge(P, p2[0], p2[1], '2', 'push', above=False), qm.sh_badge(P, p3[0], p3[1], '3', 'push', above=False)]
    legend = [qm.legend_item('vwap', f'黄线是均价线：从{"最低点" if Lg else "最高点"}算起，大家买进来的平均价。'),
              qm.legend_item('watch', '绿色虚线是观察区，压在均价线上。'), qm.legend_item('risk', f'红色虚线是风险参考：最近一次{W["rally"]}的{"底" if Lg else "顶"}。'),
              qm.legend_item('reg', '浅蓝色虚线是回归趋势：最近四十根收盘价的方向。'), qm.legend_item('steps', f'1、2、3 是最近三次{W["rally"]}的{W["hi"]}。')]
    out.update(phase='观察中', phase_text='观察中', list=KEY, checks=checks, shapes=shapes, legend=legend, _ev=anc,
               radar=dict(cost=R(P, av), risk_ref=R(P, p3[1]), slope=round(float(reg['slope']), 4)), story=f'从 {d[anc]} 的{"低点" if Lg else "高点"}算起的均价线在 {R(P, av)}')
    if k1 and k2 and k3:
        out.update(verdict='留意风险', verdict_text='留意风险', state='risk',
                   text=f'{W["hi"]}逐级{W["step"]}，{W["rally"]}受阻于均价线，{W["trend"]}结构未破。' + ('跌得越慢，套得越深。' if not Lg else '对手里有空单的人，这是要留意的风险。'))
    else:
        n = sum(1 for x in checks if x['ok'])
        out.update(verdict='继续观察', verdict_text='继续观察', state='watch', text=f'三样里有 {n} 样。还缺：' + '、'.join(x['name'] for x in checks if not x['ok']) + '。')
    out['next_needs'] = [f'收盘{"跌破" if Lg else "站上"}风险参考 {R(P, p3[1])}：{W["trend"]}结构破了', f'收盘回到均价线 {R(P, av)} {W["over"]}面：均价线不再压着']
    return qm.finish(out)
