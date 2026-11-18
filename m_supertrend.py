"""超级趋势 10/3 —— Supertrend 的公开算法，按公开描述重写（参照 DaveSkender/Stock.Indicators 的 SuperTrend 说明，Apache-2.0）。因果，未回测。

公开算法：
  中线 = （最高价 + 最低价）÷ 2；上轨 = 中线 + 3 × ATR，下轨 = 中线 − 3 × ATR（ATR 取 10 根，Wilder 平滑）。
  下轨只往上挪不往下挪（除非前一根收盘已经在它下面），上轨只往下挪不往上挪。
  收盘越过前一根的上轨：趋势翻多，超级趋势线换成下轨；收盘跌破前一根的下轨：翻空，换成上轨。那条线就是止损。
清单（按做多一侧写；做空时整张图上下翻过来，原版本来就做两个方向）：
  K1 趋势向上：现在是多头，收盘在超级趋势线上方。
  K2 离线不远：收盘离超级趋势线不超过 1 个 ATR【估算】，走得更远就等它回来。
两项齐了：建仓区 = 现价往下半个 ATR【估算】；止损 = 超级趋势线；第一、第二目标 = 止损距离的 2 倍、4 倍【估算】（原版没有目标价，跟着线走）。
"""
import numpy as np

import qmodel as qm
from qmodel import R

KEY, VERSION, NAME = 'supertrend', 'supertrend-r1', '超级趋势 10/3'
KIND, DEFAULT_SIDE = 'trade', 'long'
DEFAULT_HZ = 60
MIRRORED = ()                     # 两个方向都是原版的规则
TAGS = ('开源规则', '参数含估算')
EXTRA = ('supertrend',)
VIDEO, VIDEO_NOTE = {}, {}
SOURCE = dict(atr_n=10, mult=3.0)
SOURCE_NOTE = dict(atr_n='ATR（每根平均波动多大）算多少根，Wilder 平滑', mult='上下轨离中线几个 ATR')
EST = dict(near_atr=1.0, zone_atr=0.5, t1_r=2.0, t2_r=4.0)
EST_NOTE = dict(near_atr='收盘离线超过几个 ATR 就算追高', zone_atr='建仓区是现价往下几个 ATR', t1_r='第一目标是止损距离的几倍（原版没有目标价）', t2_r='第二目标是止损距离的几倍')
REFS = ('DaveSkender/Stock.Indicators（Apache-2.0）的 SuperTrend 说明：中线 ± 3 × ATR(10)，线只朝一个方向挪',
        'TradingView 内置 Supertrend 的公开写法（ATR 10、倍数 3）')
NOTES = ('没有回测过。照 Supertrend 的公开算法重写，不是原作者的代码。', '原版没有目标价，靠那条线跟着走；这里的两个目标是止损距离的倍数【估算】。',
         '前一百多根 K 线里 ATR 还没稳定，线会比较乱：数据太短的标的（比如刚上市的）参考价值更低。')

LEARN = dict(
    long=dict(idea_title='“超级趋势”在看什么？',
              idea='它在价格下面画一条线，线只往上挪，不往下挪。价格一直在线上面，就算多头。哪天收盘跌到线下面，就算趋势坏了。',
              idea_note='一个很常见的开源指标。这里照公开的算法重写。',
              list_title='两项清单', list='两个问题。现在是多头吗（收盘在线上面）？收盘离那条线还不远吗？离得太远，止损就太宽，等它回来。',
              plan='建仓区在现价往下半个 ATR。止损就是那条线。原版没有目标价，这里按止损距离的两倍、四倍给两个参考位。',
              none='现在是空头，而且离翻多还远，所以这套清单用不上。',
              cards=[('g_st', '那条线为什么只往一个方向挪？', '多头的时候，线只往上挪。价格涨，线跟着抬，就像把止损一路往上拉。价格跌，线不动，等收盘跌破它才认错。', None, 'chart')]),
    short=dict(idea_title='“超级趋势”的做空一侧在看什么？',
               idea='它在价格上面画一条线，线只往下挪，不往上挪。价格一直在线下面，就算空头。哪天收盘涨到线上面，就算趋势变了。',
               idea_note='原版本来就做两个方向，这一侧也是原版的规则。',
               list_title='两项清单', list='两个问题。现在是空头吗（收盘在线下面）？收盘离那条线还不远吗？离得太远，止损就太宽，等它回来。',
               plan='建仓区在现价往上半个 ATR。止损就是那条线。做空是反着来的：止损在上，目标在下。',
               none='现在是多头，而且离翻空还远，所以这套清单用不上。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _wilder_atr(h, l, c, n):
    m = len(c)
    out = np.full(m, np.nan)
    if m < n:
        return out
    pc = np.concatenate((c[:1], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    out[n - 1] = tr[:n].mean()
    for t in range(n, m):
        out[t] = (out[t - 1] * (n - 1) + tr[t]) / n
    return out


def _arrays(P):
    """整段算一次（每个值只用到它和它之前的 K 线）：ATR、上下轨、方向（+1 多头 / −1 空头）、这一段方向从哪一根开始、超级趋势线。"""
    if 'st' not in P:
        h, l, c = P['h'], P['l'], P['c']
        n, m = len(c), SOURCE['mult']
        atr = _wilder_atr(h, l, c, SOURCE['atr_n'])
        mid = (h + l) / 2
        bu, bl = mid + m * atr, mid - m * atr
        fu, fl = np.full(n, np.nan), np.full(n, np.nan)
        dirn, flip = np.zeros(n, int), np.full(n, -1)
        s = SOURCE['atr_n'] - 1
        for t in range(max(s, 0), n):
            if t == s:
                fu[t], fl[t], dirn[t], flip[t] = bu[t], bl[t], 1, t          # 和 TradingView 一样：从多头开始数
                continue
            fl[t] = max(bl[t], fl[t - 1]) if c[t - 1] > fl[t - 1] else bl[t]
            fu[t] = min(bu[t], fu[t - 1]) if c[t - 1] < fu[t - 1] else bu[t]
            if dirn[t - 1] == -1 and c[t] > fu[t - 1]:
                dirn[t] = 1
            elif dirn[t - 1] == 1 and c[t] < fl[t - 1]:
                dirn[t] = -1
            else:
                dirn[t] = dirn[t - 1]
            flip[t] = t if dirn[t] != dirn[t - 1] else flip[t - 1]
        line = np.where(dirn == 1, fl, np.where(dirn == -1, fu, np.nan))
        P['st'] = dict(atr=atr, fu=fu, fl=fl, dir=dirn, flip=flip, line=line)
    return P['st']


def _core(P, j):
    d, c = P['d'], P['c']
    S = _arrays(P)
    Lg = qm.long(P)
    W = dict(up='多头' if Lg else '空头', down='空头' if Lg else '多头', above='上方' if Lg else '下方', below='下方' if Lg else '上方', fall='跌破' if Lg else '涨破',
             turn='翻多' if Lg else '翻空', chase='追高' if Lg else '追空')
    out = qm.blank(verdict_text='这套清单用不上', phase_text='无结构')
    if S['dir'][j] == 0 or not np.isfinite(S['line'][j]) or not np.isfinite(S['atr'][j]):
        out['note'] = f'还不到 {SOURCE["atr_n"]} 根 K 线，算不出超级趋势线。'
        out['text'] = out['note']
        return out
    a, cj, line = float(S['atr'][j]), float(c[j]), float(S['line'][j])
    f = int(S['flip'][j])
    i0 = max(SOURCE['atr_n'] - 1, j - 79)
    seg = lambda want: [S['line'][t] if S['dir'][t] == want else np.nan for t in range(i0, j + 1)]
    shapes = [qm.sh_line(P, i0, seg(1), 'up' if Lg else 'down', f'超级趋势线（{W["up"]}）', key='st', w=1.6),
              qm.sh_line(P, i0, seg(-1), 'down' if Lg else 'up', f'超级趋势线（{W["down"]}）', w=1.6)]
    legend = [qm.legend_item('st', ('红色线' if Lg else '绿色线') + f'是超级趋势线（{W["up"]}）：收盘在它{W["above"]}，那条线就是止损。另一种颜色表示{W["down"]}。')]
    if j - f < 80:
        shapes.append(qm.sh_badge(P, f, float(c[f]), '翻', 'level', above=not (S['dir'][j] == 1), key='flip', first=True))
        legend.append(qm.legend_item('flip', '“翻”字是这一段方向开始的那一根。'))
    up_now = S['dir'][j] == 1
    k1 = bool(up_now)
    gap = (cj - line) / a
    k2 = up_now and gap <= EST['near_atr']
    why1 = (f'{d[f]} 收盘{W["turn"]}，到现在 {j - f} 根，收盘 {R(P, cj)} 在线 {R(P, line)} {W["above"]}' if up_now else
            f'现在是{W["down"]}（从 {d[f]} 开始），线在 {R(P, line)}，收盘越过它才{W["turn"]}')
    why2 = f'收盘离线 {abs(gap):.1f} 个 ATR（ATR {a:.2f}），' + (('没超过' if k2 else '超过了') + f' {EST["near_atr"]:g} 个' if up_now else '现在不是' + W['up'])
    checks = [qm.check('K1', f'趋势向{"上" if Lg else "下"}', k1, why1, ask=f'现在是{W["up"]}吗？', yes=f'是{W["up"]}', no=f'还是{W["down"]}', sticker_yes=W['up'], sticker_no='等'),
              qm.check('K2', '离线不远', k2, why2, ask='收盘离那条线还不远吗？', yes='还不远', no='走远了' if up_now else '谈不上', sticker_yes=f'不{W["chase"]}', sticker_no='等')]
    out.update(list=KEY, checks=checks, shapes=shapes, legend=legend, _ev=f if up_now else None, _from=f if up_now else None,
               supertrend=dict(direction=W['up'] if up_now else W['down'], line=R(P, line), since=d[f], atr=round(a, 4)),
               story=f'{d[f][5:]} 起是{W["up"] if up_now else W["down"]}')
    r_plan = lambda zlo, zhi, stop: qm.r_plan(zlo, zhi, stop, EST['t1_r'], EST['t2_r'])
    if up_now and k2:
        out.update(qm.plan(P, *r_plan(cj - EST['zone_atr'] * a, cj, line), f'止损距离的 {EST["t2_r"]:g} 倍【估算】'))
        out.update(phase=W['up'], phase_text=W['up'], verdict='条件齐', verdict_text='条件齐了（未回测）', state='ready', zone_from=d[f],
                   text=f'现在是{W["up"]}，收盘离超级趋势线不到 {EST["near_atr"]:g} 个 ATR，两项都成立。这套规则没有回测过，这里只是把清单结果摆出来。')
        out['next_needs'] = [f'收盘{W["fall"]} {R(P, line)}（超级趋势线）：趋势坏了']
    elif up_now:
        z = line + EST['near_atr'] * a                      # 回到离线 1 个 ATR 的地方，就不算追了
        out.update(phase=W['up'], phase_text=W['up'], verdict='不追', verdict_text=f'{W["up"]}，但离线太远，不{W["chase"]}', state='avoid',
                   text=f'现在是{W["up"]}，可是收盘离超级趋势线已经 {gap:.1f} 个 ATR，止损太宽。按规则不追，等它回到线附近。',
                   pre=qm.preplan(P, *r_plan(z - EST['zone_atr'] * a, z, line)))
        out['next_needs'] = [f'回到 {R(P, z)} 以内（线外 {EST["near_atr"]:g} 个 ATR）才不算追', f'收盘{W["fall"]} {R(P, line)}：趋势坏了']
    else:
        fu, fl = float(S['fu'][j]), float(S['fl'][j])        # 空头时，收盘越过上轨 fu 就翻多；翻多以后线换成下轨 fl
        if (fu - cj) / a <= EST['near_atr']:
            out.update(phase=W['down'], phase_text=W['down'], verdict='等', verdict_text=f'快{W["turn"]}了，等收盘越过 {R(P, fu)}', state='wait',
                       text=f'现在还是{W["down"]}，收盘离{W["turn"]}的那条线 {R(P, fu)} 只差 {(fu - cj) / a:.1f} 个 ATR。',
                       pre=qm.preplan(P, *r_plan(fu - EST['zone_atr'] * a, fu, fl)))
            out['next_needs'] = [f'收盘越过 {R(P, fu)}：{W["turn"]}，线换到 {R(P, fl)} 附近']
        else:
            out.update(phase=W['down'], phase_text=W['down'], verdict='不适用', state='na', verdict_text=f'现在是{W["down"]}，这套清单用不上',
                       note=f'现在是{W["down"]}，收盘离{W["turn"]}的线 {R(P, fu)} 还有 {(fu - cj) / a:.1f} 个 ATR。')
            out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
            out['next_needs'] = [f'收盘越过 {R(P, fu)} 才{W["turn"]}']
    return qm.finish(out)
