"""NR7 窄幅突破 —— Toby Crabel《Day Trading with Short Term Price Patterns and Opening Range Breakout》（1990）里的 NR7，按公开描述重写。因果，未回测。

公开定义：NR7 = 这一根的振幅（最高价 − 最低价）是最近 7 根里最窄的。波动收得很紧之后，常常跟着一段放开的走势。
交易写法参照 backtrader 公开文档里的 NR7 突破示例（那份代码是 GPL，这里没有照抄代码，只照它写明的规则）：
  前一根是 NR7，今天收盘冲过那一根的最高价，就进场；止损 = 进场价下方 2.5 个 ATR；目标 = 进场价上方 4 个 ATR；5 根还没走出来就离场。
清单（按做多一侧写；做空时整张图上下翻过来，跌穿 NR7 那一根的最低价）：
  K1 前一根是 NR7：振幅是最近 7 根里最窄的。
  K2 收盘突破：今天收盘冲过那一根的最高价。
两项齐了：建仓区 = 现价往下半个 ATR【估算】（不低于那一根的最高价）；止损 = 现价下方 2.5 个 ATR；第一目标 = 现价上方 4 个 ATR；不设第二目标。
"""
import numpy as np

import patterns as pt
import qmodel as qm
from qmodel import R

KEY, VERSION, NAME = 'nr7', 'nr7-r1', 'NR7 窄幅突破'
KIND, DEFAULT_SIDE = 'trade', 'long'
DEFAULT_HZ = 20
MIRRORED = ()
TAGS = ('开源规则', '参数含估算')
EXTRA = ('nr7',)
VIDEO, VIDEO_NOTE = {}, {}
SOURCE = dict(n=7, stop_atr=2.5, target_atr=4.0, hold=5)
SOURCE_NOTE = dict(n='振幅是最近几根里最窄', stop_atr='止损在进场价下方几个 ATR', target_atr='目标在进场价上方几个 ATR', hold='几根没走出来就离场')
EST = dict(zone_atr=0.5)
EST_NOTE = dict(zone_atr='建仓区是现价往下几个 ATR（不低于那一根的最高价）')
REFS = ('Toby Crabel《Day Trading with Short Term Price Patterns and Opening Range Breakout》（1990）：NR7',
        'backtrader 公开文档的 NR7 突破示例：止损 2.5 个 ATR、目标 4 个 ATR、5 根离场（GPL-3.0，只照规则，不抄代码）',
        'StockCharts ChartSchool：Narrow Range Day（NR7）的说明')
NOTES = ('没有回测过。照 NR7 的公开定义和 backtrader 文档写明的规则重写，不是原作者的代码。',
         'backtrader 文档在黄金日线（2008–2025）上的结果：132 笔，胜率 48.48%，最大回撤 49.46%。只当一把尺子用。')

LEARN = dict(
    long=dict(idea_title='“NR7 窄幅突破”在看什么？',
              idea='有时候一根 K 线特别短，是最近七根里最窄的。这说明多空都在等。第二天收盘冲过那根短 K 线的最高点，它就跟上。',
              idea_note='来自 Toby Crabel 的一本老书。止损、目标照公开的示例代码写的规则。',
              list_title='两项清单', list='两个问题。昨天那根是最近七根里最窄的吗？今天收盘冲过了它的最高点吗？两个都“是”，才说条件齐了。',
              plan='止损在现价下面两个半 ATR。目标在现价上面四个 ATR。五根 K 线还没走出来，原版就离场。',
              none='它要先看到一根特别窄的 K 线，第二天再冲出去。今天不是这样，所以清单空着。',
              cards=[('g_nr7', '“振幅”是什么？', '一根 K 线的最高价减最低价，就是它这一天走了多宽。越窄，说明这一天越安静。', None, 'chart')]),
    short=dict(idea_title='“NR7 窄幅突破”的做空一侧在看什么？',
               idea='有时候一根 K 线特别短，是最近七根里最窄的。第二天收盘跌穿那根短 K 线的最低点，这一侧就跟着做空。',
               idea_note='同一套规则上下翻过来用。',
               list_title='两项清单', list='两个问题。昨天那根是最近七根里最窄的吗？今天收盘跌穿了它的最低点吗？',
               plan='止损在现价上面两个半 ATR。目标在现价下面四个 ATR。做空是反着来的：止损在上，目标在下。',
               none='它要先看到一根特别窄的 K 线，第二天再跌出去。今天不是这样，所以清单空着。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _nr(P):
    """每一根是不是 NR7：振幅比前 6 根都窄（整段算一次，只用到它和它之前的 K 线）。"""
    if 'nr7' not in P:
        rng = P['h'] - P['l']
        n, k = len(rng), SOURCE['n']
        nr = np.zeros(n, bool)
        if n >= k:
            prev = np.lib.stride_tricks.sliding_window_view(rng, k - 1).min(axis=1)       # 窗口 i 是第 i 到 i+5 根
            nr[k - 1:] = rng[k - 1:] < prev[:n - k + 1]
        P['nr7'] = nr
    return P['nr7']


def _core(P, j):
    d, h, l, c = P['d'], P['h'], P['l'], P['c']
    Lg = qm.long(P)
    k = SOURCE['n']
    W = dict(hi='最高' if Lg else '最低', brk='冲过' if Lg else '跌穿', up='往上' if Lg else '往下')
    out = qm.blank(verdict_text='这套清单用不上', phase_text='无结构')
    if j < k:
        out['note'] = f'还不到 {k} 根 K 线，比不出最窄的一根。'
        out['text'] = out['note']
        return out
    nr = _nr(P)
    cj, a = float(c[j]), pt.atr(P, j)
    r = j - 1
    k1 = bool(nr[r])
    k2 = k1 and cj > float(h[r])
    rng = lambda t: float(h[t] - l[t])
    why1 = (f'{d[r]} 的振幅 {abs(rng(r)):.2f}，' + (f'是最近 {k} 根里最窄的' if k1 else f'不是最近 {k} 根里最窄的（最窄是 {min(abs(rng(t)) for t in range(r - k + 1, r + 1)):.2f}）'))
    why2 = (f'今天收盘 {R(P, cj)}，那一根的{W["hi"]}价 {R(P, h[r])}：' + (f'{W["brk"]}了' if k2 else f'还没{W["brk"]}')) if k1 else '前一根不是 NR7，谈不上突破'
    checks = [qm.check('K1', f'前一根是 NR{k}', k1, why1, ask=f'昨天那根是最近 {k} 根里最窄的吗？', yes='是最窄的', no='不是最窄的', sticker_yes='很安静'),
              qm.check('K2', '收盘突破', k2, why2, ask=f'今天收盘{W["brk"]}它的{W["hi"]}价了吗？', yes=f'{W["brk"]}了', no=f'没{W["brk"]}', sticker_yes='冲出去了')]
    shapes, legend = [], []
    for t in (r, j):
        if nr[t]:
            shapes.append(qm.sh_box(P, t, t, float(l[t]), float(h[t]), 'zone', 'NR7', key='nr' if not shapes else None, alpha=0.18))
    if shapes:
        legend.append(qm.legend_item('nr', f'浅色小方框是 NR7：振幅是最近 {k} 根里最窄的那一根。'))
    out.update(phase='NR7 之后' if k1 else ('今天是 NR7' if nr[j] else '平常'), phase_text='NR7 之后' if k1 else ('今天是 NR7' if nr[j] else '平常'), list=KEY, checks=checks,
               shapes=shapes, legend=legend, _ev=r if k2 else None, _from=r if k2 else None,
               nr7=dict(nr7_today=bool(nr[j]), nr7_yesterday=k1, level=R(P, h[r]) if k1 else (R(P, h[j]) if nr[j] else None)))
    if k2:
        zlo = max(float(h[r]), cj - EST['zone_atr'] * a)
        out.update(qm.plan(P, zlo, cj, cj - SOURCE['stop_atr'] * a, cj + SOURCE['target_atr'] * a, t2_none=f'原版 {SOURCE["hold"]} 根没走出来就离场，不设第二目标'))
        out.update(verdict='条件齐', state='ready', verdict_text='条件齐了（未回测）', zone_from=d[r],
                   text=f'{d[r]} 那一根是最近 {k} 根里最窄的，今天收盘{W["brk"]}了它的{W["hi"]}价，两项都成立。这套规则没有回测过，这里只是把清单结果摆出来。')
        out['next_needs'] = [f'{SOURCE["hold"]} 根之内没到目标，原版就离场', f'收盘到止损 {out["stop"]}：认错']
    elif nr[j]:
        lv = float(h[j])
        out.update(verdict='等', state='wait', verdict_text=f'今天是 NR{k}，等明天收盘{W["brk"]} {R(P, lv)}',
                   pre=qm.preplan(P, lv, lv + EST['zone_atr'] * a, lv - SOURCE['stop_atr'] * a, lv + SOURCE['target_atr'] * a),
                   text=f'今天的振幅是最近 {k} 根里最窄的。明天收盘{W["brk"]}今天的{W["hi"]}价 {R(P, lv)}，才算突破。')
        out['next_needs'] = [f'明天收盘{W["brk"]} {R(P, lv)}：条件齐', '明天没突破，这一根就作废']
    else:
        out.update(verdict='不适用', state='na', verdict_text='没有 NR7，这套清单今天用不上',
                   note=f'前一根和今天都不是最近 {k} 根里最窄的。' if not k1 else f'昨天是 NR{k}，可是今天收盘没{W["brk"]}它的{W["hi"]}价，这一次作废。')
        out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
    return qm.finish(out)
