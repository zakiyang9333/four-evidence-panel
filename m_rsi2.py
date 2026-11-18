"""Connors RSI(2) —— Larry Connors、Cesar Alvarez《Short Term Trading Strategies That Work》（2008）里的 2 日 RSI 规则，按公开描述重写。因果，未回测。

公开规则（做多一侧）：
  只在长期上升趋势里做：收盘在 200 日均线上方。
  2 日 RSI 跌到 5 以下，当天收盘进场（Connors 测过：低于 5 比低于 10 好；也有转述用 10）。
  收盘站回 5 日均线上方就离场。原版不设价格止损（作者认为止损会伤害这种短线反弹）。
做空一侧（StockCharts 的转述）：收盘在 200 日均线下方，2 日 RSI 涨到 95 以上，收盘回到 5 日均线下方离场。
清单：
  K1 长期向上：收盘在 200 日均线上方。
  K2 2 日 RSI 超卖：低于 5。
两项齐了：建仓区 = 现价往下半个 ATR【估算】；第一目标 = 5 日均线（原版的离场线）；不设第二目标。
止损：原版没有。这里给一个参考止损 = 现价下方 2.5 个 ATR【估算】，只是让卡片上有个认错的位置。
"""
import numpy as np

import indicators as ind
import patterns as pt
import qmodel as qm
from qmodel import R

KEY, VERSION, NAME = 'rsi2', 'rsi2-r1', 'Connors RSI(2)'
KIND, DEFAULT_SIDE = 'trade', 'long'
DEFAULT_HZ = 20
MIRRORED = ()
TAGS = ('开源规则', '原版不设止损', '参数含估算')
EXTRA = ('rsi2',)
VIDEO, VIDEO_NOTE = {}, {}
SOURCE = dict(rsi_n=2, rsi_buy=5, ma_trend=200, ma_exit=5)
SOURCE_NOTE = dict(rsi_n='RSI 算几根', rsi_buy='2 日 RSI 低于多少算超卖（Connors 测过 5 比 10 好）', ma_trend='只在收盘高于几日均线时做', ma_exit='收盘站回几日均线就离场')
EST = dict(near=15, zone_atr=0.5, stop_atr=2.5)
EST_NOTE = dict(near='2 日 RSI 低于多少算“快超卖了”', zone_atr='建仓区是现价往下几个 ATR', stop_atr='参考止损在现价下方几个 ATR（原版不设止损）')
REFS = ('Larry Connors、Cesar Alvarez《Short Term Trading Strategies That Work》（2008）：2 日 RSI 规则',
        'StockCharts ChartSchool「RSI(2)」：200 日均线定方向，2 日 RSI 低于 5 进场（做空高于 95），站回 5 日均线离场，不设止损',
        'Connors 2008 年在 TradingMarkets 的文章：只在 200 日均线上方做，收盘站上 5 日均线离场',
        'backtrader 公开文档的变体：2 日 RSI 低于 5、收盘高于 100 日均线、RSI 回到 30 离场；黄金日线 2008–2025 年 311 笔（GPL，只照规则）')
NOTES = ('没有回测过。照 Connors 2 日 RSI 规则的公开描述重写，不是原作者的代码。',
         '原版不设价格止损。卡片上的止损是这里加的参考位【估算】，原版的认错方式只有“站回 5 日均线离场”。',
         '公开资料里的回测都是各自作者做的，没有扣掉数据挖掘。只当一把尺子用。')

LEARN = dict(
    long=dict(idea_title='“Connors RSI(2)”在看什么？',
              idea='长期在涨的票，偶尔会连跌两天，跌得很急。这套规则就在这种“急跌”时进场，赌它很快弹回来。弹回五日均线上面就走，不恋战。',
              idea_note='来自 Larry Connors 的一本书，规则公开、很有名。这里照公开的写法重写。',
              list_title='两项清单', list='两个问题。收盘在两百日均线上面吗（长期在涨）？两天的 RSI 跌到五以下了吗（跌得很急）？两个都“是”，才说条件齐了。',
              plan='建仓区在现价往下半个 ATR。第一目标是五日均线：收盘站回它上面，原版就离场。原版不设止损，这里给的止损只是参考。',
              none='它只在长期上涨、又刚急跌两天的时候出现。今天不是这样，所以清单空着。',
              cards=[('g_rsi2', '两天的 RSI 是什么？', 'RSI 平时看十四天，这里只看两天，所以非常灵敏。跌两天就能掉到五以下，说明短线卖得很急。', None, 'chart')]),
    short=dict(idea_title='“Connors RSI(2)”的做空一侧在看什么？',
               idea='长期在跌的票，偶尔会连涨两天，涨得很急。这一侧就在这种“急涨”时做空，赌它很快掉回来。掉回五日均线下面就走。',
               idea_note='做空的写法来自 StockCharts 的转述：两百日均线下方，两天 RSI 高于九十五。',
               list_title='两项清单', list='两个问题。收盘在两百日均线下面吗（长期在跌）？两天的 RSI 涨到九十五以上了吗（涨得很急）？',
               plan='建仓区在现价往上半个 ATR。第一目标是五日均线。原版不设止损，这里给的止损只是参考。做空是反着来的：止损在上，目标在下。',
               none='它只在长期下跌、又刚急涨两天的时候出现。今天不是这样，所以清单空着。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _rsi(P):
    if 'rsi2' not in P:
        P['rsi2'] = ind.rsi(P['c'], SOURCE['rsi_n'])
    return P['rsi2']


def _core(P, j):
    d, c = P['d'], P['c']
    Lg = qm.long(P)
    W = dict(trend='上方' if Lg else '下方', up='长期在涨' if Lg else '长期在跌', os='超卖' if Lg else '超买', below='低于' if Lg else '高于', back='站回' if Lg else '跌回',
             fall='跌' if Lg else '涨', brk='跌破' if Lg else '涨破')
    out = qm.blank(verdict_text='这套清单用不上', phase_text='无结构')
    rsi, mt, mx = _rsi(P), qm.ma(P, SOURCE['ma_trend']), qm.ma(P, SOURCE['ma_exit'])
    if not (np.isfinite(mt[j]) and np.isfinite(mx[j])):
        out['note'] = f'还不到 {SOURCE["ma_trend"]} 根 K 线，算不出 {SOURCE["ma_trend"]} 日均线。'
        out['text'] = out['note']
        return out
    cj, a, r = float(c[j]), pt.atr(P, j), float(rsi[j])
    thr = SOURCE['rsi_buy']
    show = lambda x: x if Lg else 100.0 - x                  # 做空一侧内部是翻过来算的：显示时换回真实的 RSI
    lim = thr if Lg else 100 - thr
    k1, k2 = cj > float(mt[j]), r < thr
    why1 = f'收盘 {R(P, cj)}，{SOURCE["ma_trend"]} 日均线 {R(P, mt[j])}：' + (f'在它{W["trend"]}' if k1 else f'不在它{W["trend"]}')
    why2 = f'2 日 RSI {show(r):.1f}，' + (f'{W["below"]} {lim:g}' if k2 else f'还没{W["below"]} {lim:g}')
    checks = [qm.check('K1', f'收盘在 {SOURCE["ma_trend"]} 日线{W["trend"]}', k1, why1, ask=f'{W["up"]}吗（收盘在 {SOURCE["ma_trend"]} 日均线{W["trend"]}）？', yes=W['up'],
                       no=f'不是{W["up"]}', sticker_yes='顺大势'),
              qm.check('K2', f'2 日 RSI {W["os"]}', k2, why2, ask=f'2 日 RSI {W["below"]} {lim:g} 了吗？', yes=f'急{W["fall"]}了', no=f'还没急{W["fall"]}', sticker_yes=W['os'])]
    i0 = max(SOURCE['ma_trend'], j - 79)
    shapes = [qm.sh_line(P, i0, mt[i0:j + 1], 'level', f'{SOURCE["ma_trend"]} 日均线', key='mat', w=1.4), qm.sh_line(P, i0, mx[i0:j + 1], 'boll', f'{SOURCE["ma_exit"]} 日均线（离场线）', key='mx', w=1.2)]
    legend = [qm.legend_item('mat', f'橙色线是 {SOURCE["ma_trend"]} 日均线：收盘在它{W["trend"]}，才算{W["up"]}。'),
              qm.legend_item('mx', f'浅蓝色线是 {SOURCE["ma_exit"]} 日均线：收盘{W["back"]}它，原版就离场。')]
    s = j
    while s > 0 and rsi[s - 1] < thr and c[s - 1] > mt[s - 1]:     # 这一段连续超卖从哪一根开始（同一段只算一次触发）
        s -= 1
    out.update(phase='急' + W['fall'] if k2 else '平常', phase_text='急' + W['fall'] if k2 else '平常', list=KEY, checks=checks, shapes=shapes, legend=legend,
               _ev=s if k1 and k2 else None, _from=s if k1 and k2 else None, rsi2=dict(rsi=round(show(r), 1), ma_trend=R(P, mt[j]), exit_line=R(P, mx[j])))
    args = (cj - EST['zone_atr'] * a, cj, cj - EST['stop_atr'] * a, float(mx[j]))
    t2_none = f'原版收盘{W["back"]} {SOURCE["ma_exit"]} 日均线就离场，不设第二目标'
    if not k1:
        out.update(verdict='不适用', state='na', verdict_text=f'不是{W["up"]}，这套清单用不上',
                   note=f'收盘不在 {SOURCE["ma_trend"]} 日均线{W["trend"]}。原版只在{W["up"]}的票上做。')
        out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
    elif k2 and float(mx[j]) <= cj:
        out.update(verdict='不追', state='avoid', verdict_text=f'已经{W["back"]} {SOURCE["ma_exit"]} 日均线，原版这时候是离场',
                   text=f'2 日 RSI 还在{W["os"]}区，可是收盘已经{W["back"]} {SOURCE["ma_exit"]} 日均线。按原版这正是离场的时候，不是进场。')
    elif k2:
        out.update(qm.plan(P, *args, t2_none=t2_none))
        out.update(verdict='条件齐', state='ready', verdict_text='条件齐了（未回测）', zone_from=d[s],
                   text=f'{W["up"]}，2 日 RSI 急{W["fall"]}到 {show(r):.1f}，两项都成立。原版不设止损，卡片上的止损是参考【估算】。这套规则没有回测过，这里只是把清单结果摆出来。')
        out['next_needs'] = [f'收盘{W["back"]} {R(P, mx[j])}（{SOURCE["ma_exit"]} 日均线）：原版离场', f'收盘{W["brk"]} {SOURCE["ma_trend"]} 日均线 {R(P, mt[j])}：不再是{W["up"]}']
    elif r < EST['near']:
        out.update(verdict='等', state='wait', verdict_text=f'快{W["os"]}了，等 2 日 RSI {W["below"]} {lim:g}', pre=qm.preplan(P, *args),
                   text=f'{W["up"]}，2 日 RSI 到了 {show(r):.1f}，再{W["fall"]}一点就{W["below"]} {lim:g}。')
        out['next_needs'] = [f'2 日 RSI {W["below"]} {lim:g}：条件齐']
    else:
        out.update(verdict='不适用', state='na', verdict_text=f'{W["up"]}，但没有急{W["fall"]}，这套清单今天用不上',
                   note=f'2 日 RSI {show(r):.1f}，没有{W["os"]}。')
        out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
    return qm.finish(out)
