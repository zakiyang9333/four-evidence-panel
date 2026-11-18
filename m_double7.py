"""Connors 双七（Double 7's）—— Larry Connors、Cesar Alvarez《Short Term Trading Strategies That Work》（2008）里的规则，按公开描述重写。因果，未回测。

公开规则（做多一侧）：
  收盘在 200 日均线上方。
  收盘是最近 7 根里最低的收盘：当天收盘进场。
  收盘变成最近 7 根里最高的收盘：当天收盘离场。原版不设价格止损。
做空一侧：没找到 Connors 公开过做空版，这里是把规则上下翻过来用的（收盘在 200 日均线下方、收盘是 7 根里最高）。
清单：
  K1 长期向上：收盘在 200 日均线上方。
  K2 7 日新低：今天的收盘是最近 7 根里最低的。
两项齐了：建仓区 = 现价往下半个 ATR【估算】；第一目标 = 最近 7 根里最高的收盘（原版的离场线）；不设第二目标。
止损：原版没有。这里给一个参考止损 = 现价下方 2.5 个 ATR【估算】。
"""
import numpy as np

import patterns as pt
import qmodel as qm
from qmodel import R

KEY, VERSION, NAME = 'double7', 'double7-r1', 'Connors 双七'
KIND, DEFAULT_SIDE = 'trade', 'long'
DEFAULT_HZ = 20
MIRRORED = ('short',)          # 原版只做多
TAGS = ('开源规则', '原版不设止损', '参数含估算')
EXTRA = ('double7',)
VIDEO, VIDEO_NOTE = {}, {}
SOURCE = dict(ma_trend=200, n=7)
SOURCE_NOTE = dict(ma_trend='只在收盘高于几日均线时做', n='收盘是最近几根里最低就进场，最高就离场')
EST = dict(near_atr=0.5, zone_atr=0.5, stop_atr=2.5)
EST_NOTE = dict(near_atr='离 7 根最低收盘还差几个 ATR 以内，算“快到了”', zone_atr='建仓区是现价往下几个 ATR', stop_atr='参考止损在现价下方几个 ATR（原版不设止损）')
REFS = ('Larry Connors、Cesar Alvarez《Short Term Trading Strategies That Work》（2008）：Double 7\'s（也有转述说出自《High Probability ETF Trading》）',
        'StrategyQuant 的公开检验：SPY 1993–2026 年 333 笔，最大回撤约 12.5%，没扣手续费；7 根窗口含当天，收盘时进出')
NOTES = ('没有回测过。照 Connors 双七规则的公开描述重写，不是原作者的代码。',
         '原版不设价格止损。卡片上的止损是这里加的参考位【估算】，原版的认错方式只有“收到 7 日最高就离场”。',
         '公开检验是各自作者做的，没扣手续费，也没扣掉数据挖掘。只当一把尺子用。')

LEARN = dict(
    long=dict(idea_title='“Connors 双七”在看什么？',
              idea='长期在涨的票，收盘跌到最近七根里最低，就进场。等收盘涨到最近七根里最高，就离场。规则只有这么多，原版连止损都不设。',
              idea_note='来自 Larry Connors 的一本书，规则公开、很简单。这里照公开的写法重写。',
              list_title='两项清单', list='两个问题。收盘在两百日均线上面吗（长期在涨）？今天的收盘是最近七根里最低的吗？两个都“是”，才说条件齐了。',
              plan='建仓区在现价往下半个 ATR。第一目标是最近七根里最高的收盘：收到那里，原版就离场。原版不设止损，这里给的止损只是参考。',
              none='它只在长期上涨、又刚收出七根新低的时候出现。今天不是这样，所以清单空着。', cards=[]),
    short=dict(idea_title='“Connors 双七”的做空一侧在看什么？',
               idea='长期在跌的票，收盘涨到最近七根里最高，就做空。等收盘跌到最近七根里最低，就离场。',
               idea_note='原版只做多，这一侧是上下翻过来用的。',
               list_title='两项清单', list='两个问题。收盘在两百日均线下面吗（长期在跌）？今天的收盘是最近七根里最高的吗？',
               plan='建仓区在现价往上半个 ATR。第一目标是最近七根里最低的收盘。原版不设止损，这里给的止损只是参考。做空是反着来的：止损在上，目标在下。',
               none='它只在长期下跌、又刚收出七根新高的时候出现。今天不是这样，所以清单空着。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _core(P, j):
    d, c = P['d'], P['c']
    Lg = qm.long(P)
    n = SOURCE['n']
    W = dict(trend='上方' if Lg else '下方', up='长期在涨' if Lg else '长期在跌', low='最低' if Lg else '最高', high='最高' if Lg else '最低', brk='跌破' if Lg else '涨破')
    out = qm.blank(verdict_text='这套清单用不上', phase_text='无结构')
    mt = qm.ma(P, SOURCE['ma_trend'])
    if not np.isfinite(mt[j]) or j < n:
        out['note'] = f'还不到 {SOURCE["ma_trend"]} 根 K 线，算不出 {SOURCE["ma_trend"]} 日均线。'
        out['text'] = out['note']
        return out
    cj, a = float(c[j]), pt.atr(P, j)
    prev_low = float(np.min(c[j - n + 1:j]))             # 前 6 根里最低的收盘：今天收盘不高于它，就是 7 根新低
    hi7 = float(np.max(c[j - n + 1:j + 1]))              # 最近 7 根里最高的收盘：原版的离场线
    k1, k2 = cj > float(mt[j]), cj <= prev_low
    why1 = f'收盘 {R(P, cj)}，{SOURCE["ma_trend"]} 日均线 {R(P, mt[j])}：' + (f'在它{W["trend"]}' if k1 else f'不在它{W["trend"]}')
    why2 = f'今天收盘 {R(P, cj)}，前 {n - 1} 根里{W["low"]}的收盘 {R(P, prev_low)}：' + (f'是 {n} 根里{W["low"]}的' if k2 else f'还不是 {n} 根里{W["low"]}的')
    checks = [qm.check('K1', f'收盘在 {SOURCE["ma_trend"]} 日线{W["trend"]}', k1, why1, ask=f'{W["up"]}吗（收盘在 {SOURCE["ma_trend"]} 日均线{W["trend"]}）？', yes=W['up'],
                       no=f'不是{W["up"]}', sticker_yes='顺大势'),
              qm.check('K2', f'{n} 日{W["low"]}收盘', k2, why2, ask=f'今天收盘是最近 {n} 根里{W["low"]}的吗？', yes=f'{n} 日{W["low"]}', no=f'还不是{W["low"]}', sticker_yes=f'{n} 日{W["low"]}')]
    i0 = max(SOURCE['ma_trend'], j - 79)
    shapes = [qm.sh_line(P, i0, mt[i0:j + 1], 'level', f'{SOURCE["ma_trend"]} 日均线', key='mat', w=1.4),
              qm.sh_hl(P, j - n + 1, hi7, 'target', f'{n} 根{W["high"]}收盘 {R(P, hi7)}（离场线）', key='hi7', i2=j, dash=[3, 4], w=1.2)]
    legend = [qm.legend_item('mat', f'橙色线是 {SOURCE["ma_trend"]} 日均线：收盘在它{W["trend"]}，才算{W["up"]}。'),
              qm.legend_item('hi7', f'粉色虚线是最近 {n} 根里{W["high"]}的收盘：收到这里，原版就离场。')]
    s = j
    while s > n and c[s - 1] > mt[s - 1] and c[s - 1] <= np.min(c[s - n:s - 1]):     # 这一段连续收出 7 日新低从哪一根开始（同一段只算一次触发）
        s -= 1
    out.update(phase='7 日' + W['low'] if k2 else '平常', phase_text='7 日' + W['low'] if k2 else '平常', list=KEY, checks=checks, shapes=shapes, legend=legend,
               _ev=s if k1 and k2 else None, _from=s if k1 and k2 else None, double7=dict(ma_trend=R(P, mt[j]), low_before=R(P, prev_low), exit_line=R(P, hi7)))
    t2_none = f'原版收到 {n} 根{W["high"]}就离场，不设第二目标'
    if not k1:
        out.update(verdict='不适用', state='na', verdict_text=f'不是{W["up"]}，这套清单用不上',
                   note=f'收盘不在 {SOURCE["ma_trend"]} 日均线{W["trend"]}。原版只在{W["up"]}的票上做。')
        out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
    elif k2:
        out.update(qm.plan(P, cj - EST['zone_atr'] * a, cj, cj - EST['stop_atr'] * a, hi7, t2_none=t2_none))
        out.update(verdict='条件齐', state='ready', verdict_text='条件齐了（未回测）', zone_from=d[s],
                   text=f'{W["up"]}，收盘是最近 {n} 根里{W["low"]}的，两项都成立。原版不设止损，卡片上的止损是参考【估算】。这套规则没有回测过，这里只是把清单结果摆出来。')
        out['next_needs'] = [f'收盘到 {n} 根{W["high"]}（现在是 {R(P, hi7)}）：原版离场', f'收盘{W["brk"]} {SOURCE["ma_trend"]} 日均线 {R(P, mt[j])}：不再是{W["up"]}']
    elif cj - prev_low <= EST['near_atr'] * a:
        hp = prev_low                                         # 假如今天就收在 7 根新低上
        out.update(verdict='等', state='wait', verdict_text=f'离 {n} 日{W["low"]}收盘只差一点，等', pre=qm.preplan(P, hp - EST['zone_atr'] * a, hp, hp - EST['stop_atr'] * a, hi7),
                   text=f'{W["up"]}，收盘离前 {n - 1} 根{W["low"]}的收盘 {R(P, prev_low)} 只差 {abs(cj - prev_low) / a:.1f} 个 ATR。')
        out['next_needs'] = [f'收盘不高于 {R(P, prev_low)}：{n} 日{W["low"]}，条件齐']
    else:
        out.update(verdict='不适用', state='na', verdict_text=f'{W["up"]}，但没收出 {n} 日{W["low"]}，这套清单今天用不上',
                   note=f'收盘离前 {n - 1} 根{W["low"]}的收盘 {R(P, prev_low)} 还有 {abs(cj - prev_low) / a:.1f} 个 ATR。')
        out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
    return qm.finish(out)
