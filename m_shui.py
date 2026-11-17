"""睡得着 —— 录屏「轻仓过夜战法」里面板上的模型。观察用，不给价位。因果，未回测。

面板上那一次（上行 · 短线）的结论：继续观察。说明原话：止损留在一个 ATR 外，仍可能出现跳空风险；收盘与中轨的关系可作观察参考。
录屏「轻仓过夜战法 · 四条要点」（原话）：
  ① 观察止损与 ATR 的距离
  ② 布林收口　留意波动
  ③ 周末数据前　关注风险
  ④ 留意跳空和滑点风险
录屏里的道理：止损单要价格到了才触发；隔夜、过周末跳空，价格可能直接跳过止损。

规则（上行一侧，假设手里是多单，止损挂在最近一个摆动低点下面 0.5%【估算】；下行时上下翻过来，假设是空单）：
  K1 止损在一个 ATR 外：现价到止损的距离 ≥ 1 个 ATR。
  K2 布林没收口：布林带(20,2) 没有缩进肯特纳通道（中轨 ± 1.5 个 ATR）里（TTM 的收口写法；收口之后常常要变盘）。
  K3 不在周末 / 假日前：下一个自然日还开盘（周线上不看这一条）。
  K4 跳空小于止损距离：最近 250 根里，不利方向的跳空有 95% 比止损距离小【估算】。
结论：K1 不成立，或者 K3、K4 同时不成立 →「留意风险」；其余 →「继续观察」。收盘在布林中轨上面还是下面，写在说明里。
"""
import datetime

import numpy as np

import panel
import qmodel as qm
import patterns as pt
from qmodel import R, dn

KEY, VERSION, NAME = 'shui', 'shui-r1', '睡得着'
KIND, DEFAULT_SIDE = 'watch', 'long'
DEFAULT_HZ = 20          # 录屏面板上这个模型用的周期
MIRRORED = ('short',)
TAGS = ('观察用',)
EXTRA = ('overnight',)
VIDEO = dict(atr_mult=1.0)
VIDEO_NOTE = dict(atr_mult='止损至少要在几个 ATR 外')
EST = dict(stop=0.005, look=120, kc=1.5, gap_n=250, gap_q=95)
EST_NOTE = dict(stop='止损挂在前一个摆动点外侧多远', look='带宽排位和最近多少根比', kc='收口：布林带缩进中轨 ± 几个 ATR 的肯特纳通道', gap_n='统计跳空的根数', gap_q='跳空取第几百分位')
REFS = ('收口的写法：xgboosted/pandas-ta-classic 的 squeeze（布林带(20,2) 缩进肯特纳通道(20, 1.5×ATR)）', 'kernc/backtesting.py：跳空跳过止损时按开盘价成交，比止损价更差',
        '布林带(20,2)、ATR(14)：indicators.py')
NOTES = ('观察用：假设你手里有仓位、止损挂在前一个摆动点外面，看过夜会不会睡不着。不给价位。', '没有回测过。照录屏的四条要点重写。')

LEARN = dict(
    long=dict(idea_title='“睡得着”在看什么？',
              idea='手里拿着仓位过夜、过周末，最怕醒来价格直接跳过了止损。止损单要价格到了才触发，跳空的时候它拦不住。它看四样：止损离现价有多远，布林带是不是收口了，是不是周末前，以前跳空有多大。',
              idea_note='对应录屏「轻仓过夜战法」。录屏里面板叫「睡得着」。',
              list_title='过夜清单', list='四个问题。止损离现价有一个 ATR 那么远吗？布林带没收口吗？明天照常开盘吗？以前的跳空比止损距离小吗？',
              plan='', none='最近找不到可以挂止损的摆动低点，这套观察用不上。',
              cards=[('g_atr', 'ATR 是什么？', '平均真实波幅：最近十四根 K 线，平均每根从最高到最低晃多大。止损如果离现价还不到一个 ATR，平常晃一晃就可能碰到。', None, 'chart')]),
    short=dict(idea_title='“睡得着”的下行一侧在看什么？',
               idea='把上行那一侧翻过来：假设手里是空单，止损挂在前一个摆动高点上面。它看同样的四样：止损离现价有多远，布林带是不是收口了，是不是周末前，以前往上跳空有多大。',
               idea_note='录屏里用的是上行一侧，这一侧是翻过来用的。',
               list_title='过夜清单', list='四个问题。止损离现价有一个 ATR 那么远吗？布林带没收口吗？明天照常开盘吗？以前的跳空比止损距离小吗？',
               plan='', none='最近找不到可以挂止损的摆动高点，这套观察用不上。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _next_open(date):
    """Is the next calendar day a trading session? (The calendar is known in advance, so this is not looking ahead.)"""
    try:
        day = datetime.date.fromisoformat(date) + datetime.timedelta(days=1)
    except ValueError:
        return True
    return panel.is_session(day)


def _core(P, j):
    d, o, c = P['d'], P['o'], P['c']
    X = qm.ix(P)
    Lg = qm.long(P)
    out = qm.blank(verdict_text='这套观察用不上', phase_text='无结构')
    piv = qm.pivots(P, j, max(0, j - EST['look']))
    lows = [x for x in piv if x[2] == -1]
    if not lows or float(c[j]) <= lows[-1][1]:
        out['note'] = f'找不到在现价{"下" if Lg else "上"}面、可以挂止损的摆动{"低" if Lg else "高"}点。'
        out['text'] = out['note'] + '这套观察今天用不上。'
        return out
    sl = lows[-1]
    stop = dn(sl[1], EST['stop'])
    a = pt.atr(P, j)
    dist = float(c[j]) - stop
    k1 = dist >= VIDEO['atr_mult'] * a
    # 布林收口用 TTM 的写法：布林带(20,2) 整个缩进肯特纳通道（中轨 ± 1.5 × ATR）里面（pandas-ta-classic 的 squeeze）
    sq_on = bool(np.isfinite(X['up'][j]) and X['up'][j] - X['mid'][j] < EST['kc'] * a)
    bw = (X['up'] - X['low']) / np.where(np.abs(X['mid']) > 0, np.abs(X['mid']), 1)
    win = bw[max(0, j - EST['look'] + 1):j + 1]
    win = win[np.isfinite(win)]
    pctl = float((win <= bw[j]).mean()) if np.isfinite(bw[j]) and len(win) else None
    k2 = not sq_on
    weekly = len(d) > 1 and (datetime.date.fromisoformat(d[j]) - datetime.date.fromisoformat(d[j - 1])).days >= 5
    k3 = weekly or _next_open(d[j])
    g0 = max(1, j - EST['gap_n'] + 1)
    gaps = np.maximum(c[g0 - 1:j] - o[g0:j + 1], 0.0) if j >= 1 else np.array([0.0])
    gq = float(np.percentile(gaps, EST['gap_q'])) if len(gaps) else 0.0
    k4 = gq < dist
    mid = X['mid'][j]
    side_mid = None if not np.isfinite(mid) else ('上' if (c[j] > mid) == Lg else '下')
    checks = [qm.check('K1', '止损在一个 ATR 外', k1, f'止损挂在 {R(P, stop)}（前一个摆动{"低" if Lg else "高"}点 {R(P, sl[1])}，{d[sl[0]]}），离现价 {qm.r2(dist)}，是 ATR {qm.r2(a)} 的 {dist / a:.1f} 倍',
                       ask='止损离现价有一个 ATR 那么远吗？', yes='止损在一个 ATR 外', no='止损离得太近', sticker_yes='够远', sticker_no='太近'),
              qm.check('K2', '布林没收口', k2, '布林带宽算不出来' if pctl is None else ('布林带缩进了肯特纳通道（收口了，留意波动）' if sq_on else '布林带比肯特纳通道宽，没收口') +
                       f'；带宽排在最近 {EST["look"]} 根的 {round(pctl * 100)}% 位置',
                       ask='布林带没收口吗？', yes='没收口', no='收口了', sticker_yes='平稳', sticker_no='留意波动'),
              qm.check('K3', '不在周末 / 假日前', k3, '周线上不看这一条' if weekly else f'{d[j]} 之后' + ('第二天照常开盘' if k3 else '要隔一个周末或假日才开盘'),
                       ask='明天照常开盘吗？', yes='明天照常开盘', no='要过周末', sticker_yes='平常日', sticker_no='周末前'),
              qm.check('K4', '跳空小于止损距离', k4, f'最近 {EST["gap_n"]} 根里，不利方向的跳空有 {EST["gap_q"]}% 不超过 {qm.r2(gq)}；止损距离 {qm.r2(dist)}',
                       ask='以前的跳空比止损距离小吗？', yes='跳空比止损小', no='跳空可能跳过止损', sticker_yes='还好', sticker_no='会跳过')]
    shapes = [qm.sh_hl(P, sl[0], stop, 'stop', f'止损参考 {R(P, stop)}', key='stop', dash=[6, 4], w=1.4),
              qm.sh_hl(P, max(0, j - 20), float(c[j]) - a, 'mute', f'一个 ATR 外 {R(P, float(c[j]) - a)}', key='atr1', dash=[2, 4], w=1),
              qm.sh_line(P, max(0, j - 79), X['mid'][max(0, j - 79):j + 1], 'boll', '布林中轨', key='mid', w=1.2)]
    legend = [qm.legend_item('stop', f'紫色虚线是止损参考：挂在前一个摆动{"低" if Lg else "高"}点外面一点。'),
              qm.legend_item('atr1', '灰色细虚线离现价正好一个 ATR：止损在它里面，平常晃一晃就可能碰到。'), qm.legend_item('mid', '浅蓝色的线是布林中轨：最近二十根的平均价。')]
    out.update(phase='过夜前', phase_text='过夜前', list=KEY, checks=checks, shapes=shapes, legend=legend, _ev=sl[0],
               overnight=dict(stop=R(P, stop), dist=qm.r2(dist), atr=qm.r2(a), gap95=qm.r2(gq), weekend=not k3, squeeze=not k2),
               story=f'止损挂在 {R(P, stop)}，离现价 {dist / a:.1f} 个 ATR')
    gap_risk = gq >= 0.5 * dist or not k3
    tail = (f'；收盘在中轨{side_mid}方，可作观察参考。' if side_mid else '。')
    if not k1 or (not k3 and not k4):
        out.update(verdict='留意风险', verdict_text='留意风险', state='risk',
                   text=('止损离现价不到一个 ATR，平常的晃动就可能碰到' if not k1 else '周末前，而且以前的跳空比止损距离还大') + tail)
    else:
        out.update(verdict='继续观察', verdict_text='继续观察', state='watch', text='止损留在一个 ATR 外' + ('，仍可能出现跳空风险' if gap_risk else '') + tail)
    out['next_needs'] = [f'离现价一个 ATR 的位置是 {R(P, float(c[j]) - a)}：止损在它里面，平常的晃动就可能碰到', '周末、数据公布前：录屏说要关注风险，留意跳空和滑点']
    return qm.finish(out)
