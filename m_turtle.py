"""海龟突破 20/10 —— GitHub 开源：vn.py 的海龟策略（vnpy/vnpy_ctastrategy 里的 turtle_signal_strategy.py，MIT 许可）。因果，未回测。

原版规则（原版用停止单盘中触发；这里统一按收盘确认）：
  入场：价格突破前 20 根的最高价就做多（跌破前 20 根的最低价就做空）。
  止损：入场价下方 2 个 ATR（ATR 取 20 根）。
  离场：价格跌破前 10 根的最低价（做空时是涨破前 10 根的最高价）。
  加仓：每往有利方向走 0.5 个 ATR 加一份，最多四份（这里只写在说明里，面板不会替你交易）。
清单（按做多一侧写；做空时整张图上下翻过来。原版本来就做两个方向）：
  K1 收盘突破 20 日高点：最近 3 根【估算】里，有一根收盘第一次站到前 20 根最高价上方。
  K2 离突破价不远：现价离突破价不超过 1 个 ATR【估算】，走得更远就等它回来。
  K3 没破离场线：突破之后，收盘没有跌破前 10 根的最低价。
三项齐了：建仓区 = 突破价到它上方 0.5 个 ATR（原版第一份到第二份的距离）；止损 = 突破价下方 2 个 ATR；
第一、第二目标 = 止损距离的 2 倍、4 倍【估算】：原版没有目标价，靠 10 日低点移动离场。
ATR 用面板统一的算法（真实波幅的简单平均）；原版用 Wilder 平滑，数值略有不同。
"""
import numpy as np

import indicators as ind
import patterns as pt
import qmodel as qm
from qmodel import R

KEY, VERSION, NAME = 'turtle', 'turtle-r1', '海龟突破 20/10'
KIND, DEFAULT_SIDE = 'trade', 'long'
DEFAULT_HZ = 60
MIRRORED = ()                     # 两个方向都是原版的规则
TAGS = ('开源规则', '参数含估算')
EXTRA = ('turtle',)
VIDEO, VIDEO_NOTE = {}, {}
SOURCE = dict(entry_n=20, exit_n=10, atr_n=20, stop_atr=2.0, add_atr=0.5)
SOURCE_NOTE = dict(entry_n='突破看前多少根的最高价', exit_n='离场看前多少根的最低价', atr_n='ATR（每根平均波动多大）算多少根', stop_atr='止损放在入场价下方几个 ATR',
                   add_atr='每走出几个 ATR 加一份（只写在说明里）')
EST = dict(fresh=3, chase_atr=1.0, near_atr=1.0, t1_r=2.0, t2_r=4.0)
EST_NOTE = dict(fresh='突破之后几根以内还算“刚突破”', chase_atr='离突破价超过几个 ATR 就算追高', near_atr='离 20 日高点还差几个 ATR 以内，算“快到突破位”',
                t1_r='第一目标是止损距离的几倍（原版没有目标价）', t2_r='第二目标是止损距离的几倍')
REFS = ('vnpy/vnpy_ctastrategy：strategies/turtle_signal_strategy.py（MIT）。入场 20、离场 10、ATR 20、止损 2 个 ATR、每 0.5 个 ATR 加一份',
        '海龟交易法则：Richard Dennis、William Eckhardt 的系统 1（20 日突破、10 日离场）',
        'Brock、Lakonishok、LeBaron（1992）：突破类规则在 1897–1986 年的道指上有效；Sullivan、Timmermann、White（1999）：扣掉数据挖掘之后，1987 年以后的样本外失效')
NOTES = ('没有回测过。照 vn.py 海龟策略（MIT）的规则重写，不是原作者的代码。',
         '原版靠盘中停止单入场、10 日低点移动离场，没有目标价。这里按收盘确认，两个目标是止损距离的倍数【估算】。',
         '公开研究里，这类突破规则扣掉数据挖掘之后样本外不灵，只当一把尺子用。')

LEARN = dict(
    long=dict(idea_title='“海龟突破”在看什么？',
              idea='价格冲过最近二十根 K 线的最高点，说明有人愿意出更高的价。海龟就在这时候跟上，不猜底，也不猜顶。跌破最近十根的最低点，就认错离场。',
              idea_note='来自一套很有名的老规则（海龟交易法则）。这里照 GitHub 上的开源代码重写。',
              list_title='三项清单', list='三个问题。最近三根里，收盘冲过了二十根高点吗？现价离那个突破价还不远吗？突破以后，收盘一直没跌破十根低点吗？',
              plan='建仓区从突破价开始，往上半个 ATR。止损在突破价下面两个 ATR。原版没有目标价，这里按止损距离的两倍、四倍给两个参考位。',
              none='它要等价格冲过最近二十根 K 线的最高点。现在离那里还远，所以清单空着。',
              cards=[('g_atr', 'ATR 是什么？', '它是最近一段时间，每根 K 线平均波动多大。用它定止损：波动大的票，止损放远一点。波动小的票，就放近一点。', None, 'chart')]),
    short=dict(idea_title='“海龟突破”的做空一侧在看什么？',
               idea='价格跌穿最近二十根 K 线的最低点，说明有人急着脱手。海龟就在这时候跟着做空。涨回最近十根的最高点上面，就认错离场。',
               idea_note='原版本来就做两个方向，这一侧也是原版的规则。',
               list_title='三项清单', list='三个问题。最近三根里，收盘跌穿了二十根低点吗？现价离那个跌破价还不远吗？跌破以后，收盘一直没涨回十根高点上面吗？',
               plan='建仓区从跌破价开始，往下半个 ATR。止损在跌破价上面两个 ATR。做空是反着来的：止损在上，目标在下。',
               none='它要等价格跌穿最近二十根 K 线的最低点。现在离那里还远，所以清单空着。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _arrays(P):
    """整段算一次（每个值只用到它之前的 K 线）：前 20 根最高价、前 10 根最低价（都不含当根）、ATR 20、
    到每一根为止最近一次“收盘第一次站上前 20 根最高价”的位置，和最近一次“收盘跌破前 10 根最低价”的位置。"""
    if 'tt' not in P:
        h, l, c = P['h'], P['l'], P['c']
        n, N, X = len(c), SOURCE['entry_n'], SOURCE['exit_n']
        hi, lo = np.full(n, np.nan), np.full(n, np.nan)
        if n > N:
            hi[N:] = np.lib.stride_tricks.sliding_window_view(h, N).max(axis=1)[:n - N]
        if n > X:
            lo[X:] = np.lib.stride_tricks.sliding_window_view(l, X).min(axis=1)[:n - X]
        above = np.zeros(n, bool)
        ok = np.isfinite(hi)
        above[ok] = c[ok] > hi[ok]
        first = above & ~np.concatenate(([False], above[:-1]))
        out = np.zeros(n, bool)
        ok = np.isfinite(lo)
        out[ok] = c[ok] < lo[ok]
        idx = np.arange(n)
        P['tt'] = dict(hi=hi, lo=lo, atr=ind.atr(h, l, c, SOURCE['atr_n']),
                       last=np.maximum.accumulate(np.where(first, idx, -1)) if n else idx, exit=np.maximum.accumulate(np.where(out, idx, -1)) if n else idx)
    return P['tt']


def _core(P, j):
    d, c = P['d'], P['c']
    T = _arrays(P)
    Lg = qm.long(P)
    N, X = SOURCE['entry_n'], SOURCE['exit_n']
    W = dict(hi='高' if Lg else '低', lo='低' if Lg else '高', brk='站上' if Lg else '跌穿', fall='跌破' if Lg else '涨破', side='上方' if Lg else '下方',
             chase='追高' if Lg else '追空')
    out = qm.blank(verdict_text='这套清单用不上', phase_text='无结构')
    if not np.isfinite(T['hi'][j]) or not np.isfinite(T['lo'][j]):
        out['note'] = f'还不到 {N + 1} 根 K 线，算不出前 {N} 根的最{W["hi"]}价。'
        out['text'] = out['note']
        return out
    a = float(T['atr'][j]) if np.isfinite(T['atr'][j]) else pt.atr(P, j)
    cj, hi_now, lo_now = float(c[j]), float(T['hi'][j]), float(T['lo'][j])
    b = int(T['last'][j])
    in_trend = b >= 0 and int(T['exit'][j]) < b          # 最近一次突破之后，收盘还没破过离场线
    fresh = in_trend and j - b < EST['fresh']
    lv = float(T['hi'][b]) if b >= 0 else None             # 突破的那条线：突破当根之前 20 根的最高价
    i0 = max(N, j - 79)
    shapes = [qm.sh_line(P, i0, T['hi'][i0:j + 1], 'level', f'前 {N} 根最{W["hi"]}价', key='entry', w=1.4),
              qm.sh_line(P, i0, T['lo'][i0:j + 1], 'stop', f'前 {X} 根最{W["lo"]}价（离场线）', key='exit', w=1.2, dash=[4, 4])]
    legend = [qm.legend_item('entry', f'橙色线是前 {N} 根 K 线的最{W["hi"]}价。收盘{W["brk"]}它，就是海龟的入场信号。'),
              qm.legend_item('exit', f'紫色虚线是前 {X} 根的最{W["lo"]}价，也就是离场线。收盘{W["fall"]}它，海龟就离场。')]
    if b >= 0 and j - b < 80:
        shapes.append(qm.sh_badge(P, b, float(c[b]), '突', 'level', above=True, key='brk', first=True))
        legend.append(qm.legend_item('brk', f'“突”字是收盘第一次{W["brk"]}那条橙线的那一根。'))
    ref = lv if fresh else hi_now                          # 离哪条线算远近：刚突破看突破价，没突破看现在的 20 根最高价
    k1 = fresh
    k2 = cj - ref <= EST['chase_atr'] * a
    k3 = cj >= lo_now
    why1 = ((f'{d[b]} 收盘 {R(P, c[b])} {W["brk"]}了前 {N} 根的最{W["hi"]}价 {R(P, lv)}，是 {j - b} 根之前' if j > b else
             f'今天收盘 {R(P, cj)} {W["brk"]}了前 {N} 根的最{W["hi"]}价 {R(P, lv)}') if fresh else
            f'上一次突破在 {d[b]}，已经过去 {j - b} 根，不算刚突破' if in_trend else f'收盘 {R(P, cj)} 还没{W["brk"]}前 {N} 根的最{W["hi"]}价 {R(P, hi_now)}')
    why2 = (f'现价{"高出" if cj > ref else "离"}{"突破价" if fresh else "最" + W["hi"] + "价"} {R(P, ref)} {abs(cj - ref) / a:.1f} 个 ATR（ATR {a:.2f}），' +
            ('没超过' if k2 else '超过了') + f' {EST["chase_atr"]:g} 个')
    why3 = f'收盘 {R(P, cj)}，离场线（前 {X} 根最{W["lo"]}价）{R(P, lo_now)}：' + (f'在它{W["side"]}' if k3 else '已经破了')
    checks = [qm.check('K1', f'收盘{W["brk"]} {N} 日最{W["hi"]}价', k1, why1, ask=f'刚{W["brk"]}前 {N} 根的最{W["hi"]}价吗？', yes=f'刚{W["brk"]}', no='不是刚突破', sticker_yes='突破'),
              qm.check('K2', '离突破价不远', k2, why2, ask='现价离突破价还不远吗？', yes='还不远', no='走远了', sticker_yes=f'不{W["chase"]}', sticker_no='不追'),
              qm.check('K3', f'没{W["fall"]}离场线', k3, why3, ask=f'没{W["fall"]}前 {X} 根的最{W["lo"]}价吗？', yes='没破', no='破了', sticker_yes='还在趋势里', sticker_no='离场')]
    out.update(list=KEY, checks=checks, shapes=shapes, legend=legend, _ev=b if fresh else None, _from=b if fresh else None,
               turtle=dict(high=R(P, hi_now), exit=R(P, lo_now), atr=round(a, 4), breakout=dict(date=d[b], level=R(P, lv)) if b >= 0 else None))

    def plan_at(level):
        """海龟的计划：建仓区从突破价往外 0.5 个 ATR，止损在突破价内侧 2 个 ATR，目标是止损距离的倍数【估算】。"""
        return qm.r_plan(level, level + SOURCE['add_atr'] * a, level - SOURCE['stop_atr'] * a, EST['t1_r'], EST['t2_r'])

    if fresh and k2:
        zlo, zhi, stop, t1, t2 = plan_at(lv)
        out.update(qm.plan(P, zlo, zhi, stop, t1, t2, f'止损距离的 {EST["t2_r"]:g} 倍【估算】'))
        out.update(phase='刚突破', phase_text='刚突破', verdict='条件齐', verdict_text='条件齐了（未回测）', state='ready', zone_from=d[b],
                   text=f'收盘{W["brk"]}前 {N} 根的最{W["hi"]}价，离突破价不远，还没{W["fall"]}离场线，三项都成立。这套规则没有回测过，这里只是把清单结果摆出来。')
        out['next_needs'] = [f'收盘{W["fall"]} {R(P, lo_now)}（前 {X} 根最{W["lo"]}价）：海龟离场', f'收盘{W["fall"]}止损 {out["stop"]}：认错']
    elif fresh:
        out.update(phase='刚突破', phase_text='刚突破', verdict='不追', verdict_text=f'突破了，但离突破价太远，不{W["chase"]}', state='avoid',
                   text=f'刚{W["brk"]}前 {N} 根的最{W["hi"]}价，可是现价已经走出去 {abs(cj - lv) / a:.1f} 个 ATR。按规则不追，等它回到突破价附近。',
                   pre=qm.preplan(P, *plan_at(lv)))
        out['next_needs'] = [f'回到 {R(P, lv + EST["chase_atr"] * a)} 以内（突破价 {R(P, lv)} 外 {EST["chase_atr"]:g} 个 ATR）才不算追', f'收盘{W["fall"]} {R(P, lo_now)}：海龟离场']
    elif in_trend and cj > hi_now:
        out.update(phase='突破之后', phase_text='突破之后', verdict='不追', verdict_text='突破过了，还在一路走，不追', state='avoid',
                   text=f'{d[b]} 就突破了，已经过去 {j - b} 根，价格还在创新{W["hi"]}。海龟这时候是拿着，不是新进场：不追。')
        out['next_needs'] = [f'收盘{W["fall"]} {R(P, lo_now)}（前 {X} 根最{W["lo"]}价）：这一段走完', '等下一次突破']
    elif cj >= hi_now - EST['near_atr'] * a:
        n_ok = sum(1 for x in checks if x['ok'])
        out.update(phase='快到突破位', phase_text='快到突破位', verdict='等', verdict_text=f'清单 {n_ok}/3，等突破', state='wait',
                   text=f'现价离前 {N} 根的最{W["hi"]}价 {R(P, hi_now)} 只差 {abs(hi_now - cj) / a:.1f} 个 ATR。收盘{W["brk"]}它才算突破。',
                   pre=qm.preplan(P, *plan_at(hi_now)))
        out['next_needs'] = [f'收盘{W["brk"]} {R(P, hi_now)}（前 {N} 根最{W["hi"]}价）：海龟入场信号', f'收盘{W["fall"]} {R(P, lo_now)}：离场线']
    else:
        out.update(phase='离突破位还远', phase_text='离突破位还远', verdict='不适用', state='na', verdict_text='离突破位还远，这套清单用不上',
                   note=f'现价离前 {N} 根的最{W["hi"]}价 {R(P, hi_now)} 还有 {abs(hi_now - cj) / a:.1f} 个 ATR，海龟只在突破时进场。')
        out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
        out['next_needs'] = [f'收盘{W["brk"]} {R(P, hi_now)}（前 {N} 根最{W["hi"]}价）才算突破']
    return qm.finish(out)
