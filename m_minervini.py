"""Minervini 趋势模板 —— Mark Minervini《Trade Like a Stock Market Wizard》（2013）里的 8 条趋势模板，按公开描述重写。观察用，不给价位。因果，未回测。

公开的 8 条（做多一侧）：
  ① 价格在 150 日、200 日均线上方；② 150 日均线在 200 日均线上方；③ 200 日均线至少往上走了 1 个月（最好 4–5 个月）；
  ④ 50 日均线在 150 日、200 日均线上方；⑤ 价格在 50 日均线上方；⑥ 价格比 52 周最低价高至少 30%；
  ⑦ 价格离 52 周最高价不超过 25%；⑧ 相对强度排名至少 70（要和其他股票横着比，单只票算不了，这里不用）。
它是“这只票像不像一只强势股”的检查，不是买点：作者自己的进场点另有一套（VCP 突破），这里不做。
清单（按“上行”一侧写；“下行”是同一套规则上下翻过来，看弱势股的样子）：
  K1 均线排好：收盘 > 50 日 > 150 日 > 200 日均线（①②④⑤）。
  K2 200 日均线往上：比 21 根（约 1 个月）之前高（③）。
  K3 离一年低点够远：收盘比 52 周最低价高至少 30%（⑥）。
  K4 离一年高点够近：收盘不低于 52 周最高价的 75%（⑦）。
四项都中 →「继续观察」（强势股的样子）；之前四项都中、最近 10 根【估算】里模板破了 →「留意风险」。
"""
import numpy as np

import indicators as ind
import qmodel as qm
from qmodel import R

KEY, VERSION, NAME = 'minervini', 'minervini-r1', 'Minervini 趋势模板'
KIND, DEFAULT_SIDE = 'watch', 'long'
DEFAULT_HZ = 120
MIRRORED = ()
TAGS = ('观察用', '开源规则')
EXTRA = ('template',)
VIDEO, VIDEO_NOTE = {}, {}
SOURCE = dict(ma1=50, ma2=150, ma3=200, rise=21, low_mult=1.30, high_mult=0.75, look52=252, rs=70)
SOURCE_NOTE = dict(ma1='短的那条均线（日）', ma2='中间那条均线（日）', ma3='长的那条均线（日）', rise='200 日均线和几根之前比（约 1 个月）',
                   low_mult='收盘至少是 52 周最低价的几倍', high_mult='收盘至少是 52 周最高价的几倍', look52='52 周算多少根',
                   rs='相对强度排名至少多少（要和其他股票横着比，单只票算不了，这里不用）')
EST = dict(break_look=10)
EST_NOTE = dict(break_look='四项都中之后，几根以内模板破了算“刚破”')
REFS = ('Mark Minervini《Trade Like a Stock Market Wizard》（2013）：Trend Template 8 条',
        'StreetAlpha 的公开检验：美股 2018–2025 年 16,897 次信号，满足模板就买、20 天后卖，只比平均股票多 0.09%，胜率 52.1%：几乎没有优势')
NOTES = ('观察用：只告诉你这只票像不像强势股，不给价位。', '没有回测过。照 Minervini 趋势模板的公开描述重写，不是原作者的代码。',
         '第 8 条（相对强度排名）要和其他股票横着比，单只票算不了，这里没用。', '有的转述把第 6 条写成高出 25%，这里照常见的 30%。')

LEARN = dict(
    long=dict(idea_title='“Minervini 趋势模板”在看什么？',
              idea='它不找买点，只检查一只票像不像强势股。均线从短到长排好，长均线在往上走，价格离一年低点很远、离一年高点很近，就是强势股的样子。',
              idea_note='来自 Mark Minervini 的一本书。这里照公开的条件重写，第八条要横着比别的股票，单只票算不了。',
              list_title='四项检查', list='四个问题。均线从短到长排好了吗？两百日均线在往上走吗？价格比一年最低价高三成以上吗？价格离一年最高价不到两成五吗？',
              plan='', none='这只票现在一点也不像强势股，这套检查用不上。', cards=[]),
    short=dict(idea_title='“Minervini 趋势模板”的下行一侧在看什么？',
               idea='把上行那一侧上下翻过来，看一只票像不像弱势股：均线从短到长倒着排，长均线在往下走，价格离一年高点很远、离一年低点很近。',
               idea_note='原书只看强势股。这一侧是把条件上下翻过来用的。',
               list_title='四项检查', list='四个问题。均线倒着排好了吗？两百日均线在往下走吗？价格比一年最高价低三成以上吗？价格离一年最低价很近吗？',
               plan='', none='这只票现在一点也不像弱势股，这套检查用不上。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _arrays(P):
    if 'mv' not in P:
        h, l = P['h'], P['l']
        P['mv'] = dict(hi=ind.rolling_max(h, SOURCE['look52']), lo=ind.rolling_min(l, SOURCE['look52']))
    return P['mv']


def _all4(P, t):
    """第 t 根的四项检查：(四项各成不成立, 用到的数)。数不够时返回 None。"""
    c = P['c']
    m1, m2, m3 = qm.ma(P, SOURCE['ma1']), qm.ma(P, SOURCE['ma2']), qm.ma(P, SOURCE['ma3'])
    A = _arrays(P)
    r = SOURCE['rise']
    if t < max(r, SOURCE['look52'] - 1) or not all(np.isfinite(x) for x in (m1[t], m2[t], m3[t], m3[t - r], A['hi'][t], A['lo'][t])):      # 52 周高低要满一年才算
        return None
    ct, hi, lo = float(c[t]), float(A['hi'][t]), float(A['lo'][t])
    k1 = ct > m1[t] > m2[t] > m3[t]
    k2 = m3[t] > m3[t - r]
    k3 = ct - lo >= (SOURCE['low_mult'] - 1) * abs(lo)                 # 比一年最低价高至少 30%（做空一侧翻过来同样成立）
    k4 = hi - ct <= (1 - SOURCE['high_mult']) * abs(hi)                # 离一年最高价不超过 25%
    return (bool(k1), bool(k2), bool(k3), bool(k4)), dict(c=ct, m1=float(m1[t]), m2=float(m2[t]), m3=float(m3[t]), m3r=float(m3[t - r]), hi=hi, lo=lo)


def _core(P, j):
    d = P['d']
    Lg = qm.long(P)
    W = dict(strong='强势' if Lg else '弱势', order='从上到下' if Lg else '从下到上', up='往上' if Lg else '往下', low='最低' if Lg else '最高', high='最高' if Lg else '最低',
             above='高' if Lg else '低', fall='跌破' if Lg else '涨过')
    out = qm.blank(verdict_text='这套检查用不上', phase_text='无结构')
    got = _all4(P, j)
    if got is None:
        out['note'] = f'还不到 {SOURCE["look52"]} 根 K 线，算不出 52 周高低和 200 日均线的走向。'
        out['text'] = out['note']
        return out
    (k1, k2, k3, k4), x = got
    n = sum((k1, k2, k3, k4))
    pct_low = abs(x['c'] - x['lo']) / abs(x['lo']) * 100
    pct_high = abs(x['hi'] - x['c']) / abs(x['hi']) * 100
    checks = [qm.check('K1', '均线排好', k1, f'收盘 {R(P, x["c"])}、MA50 {R(P, x["m1"])}、MA150 {R(P, x["m2"])}、MA200 {R(P, x["m3"])}：' + ('排好了' if k1 else '没排好'),
                       ask=f'收盘和 50、150、200 日均线{W["order"]}排好了吗？', yes='排好了', no='没排好', sticker_yes='顺势'),
              qm.check('K2', f'200 日均线{W["up"]}', k2, f'MA200 现在 {R(P, x["m3"])}，{SOURCE["rise"]} 根之前 {R(P, x["m3r"])}：' + (f'在{W["up"]}走' if k2 else f'不在{W["up"]}走'),
                       ask=f'200 日均线在{W["up"]}走吗？', yes=f'在{W["up"]}', no=f'没{W["up"]}', sticker_yes='大势'),
              qm.check('K3', f'离一年{W["low"]}够远', k3, f'52 周{W["low"]}价 {R(P, x["lo"])}，收盘离它 {pct_low:.0f}%：' + ('够' if k3 else '不够') + ' 30%',
                       ask=f'收盘离一年{W["low"]}价有 30% 以上吗？', yes='够远', no='不够远', sticker_yes='走出来了'),
              qm.check('K4', f'离一年{W["high"]}够近', k4, f'52 周{W["high"]}价 {R(P, x["hi"])}，收盘离它 {pct_high:.0f}%：' + ('在' if k4 else '超过') + ' 25% 以内',
                       ask=f'收盘离一年{W["high"]}价在 25% 以内吗？', yes='够近', no='太远', sticker_yes='贴着高点' if Lg else '贴着低点')]
    i0 = max(SOURCE['ma3'], j - 79)
    shapes = [qm.sh_line(P, i0, qm.ma(P, SOURCE['ma1'])[i0:j + 1], 'boll', 'MA50', key='mas', w=1.2), qm.sh_line(P, i0, qm.ma(P, SOURCE['ma2'])[i0:j + 1], 'mute', 'MA150', w=1),
              qm.sh_line(P, i0, qm.ma(P, SOURCE['ma3'])[i0:j + 1], 'level', 'MA200', w=1.3)]
    legend = [qm.legend_item('mas', '浅蓝色是 50 日均线，灰色是 150 日，橙色是 200 日。强势股的样子，是价格在最上面，均线从短到长往下排。' if Lg else
                             '浅蓝色是 50 日均线，灰色是 150 日，橙色是 200 日。弱势股的样子，是价格在最下面，均线从短到长往上排。')]
    out.update(phase='观察中', phase_text='观察中', list=KEY, checks=checks, shapes=shapes, legend=legend, _ev=None,
               template=dict(passed=n, of=4, high52=R(P, x['hi']), low52=R(P, x['lo']), ma50=R(P, x['m1']), ma200=R(P, x['m3'])))
    def full(t):
        g = _all4(P, t)
        return g is not None and all(g[0])
    recent = next((t for t in range(j - 1, max(SOURCE['rise'] - 1, j - EST['break_look'] - 1), -1) if full(t)), None)     # 最近 10 根里还是四项都中的那一根
    if n == 4:
        out.update(verdict='继续观察', verdict_text=f'趋势模板 4/4：{W["strong"]}股的样子（不是买点）', state='watch',
                   text=f'四项检查都中，这只票现在是{W["strong"]}股的样子。模板只是筛选，不是买点。')
    elif recent is not None:
        out.update(verdict='留意风险', verdict_text='模板刚破：留意风险', state='risk',
                   text=f'{d[recent]} 还是四项都中，现在只剩 {n} 项。还缺：' + '、'.join(x['name'] for x in checks if not x['ok']) + '。')
    elif n >= 2:
        out.update(verdict='继续观察', verdict_text=f'趋势模板 {n}/4，继续观察', state='watch',
                   text=f'四项检查中了 {n} 项。还缺：' + '、'.join(x['name'] for x in checks if not x['ok']) + '。')
    else:
        out.update(verdict='不适用', verdict_text=f'不像{W["strong"]}股，这套检查用不上', state='na',
                   note=f'四项检查只中了 {n} 项。')
        out['text'] = out['note'] + '用不上不等于安全，也不等于没机会。'
    out['next_needs'] = [f'收盘{W["fall"]} 50 日均线 {R(P, x["m1"])}：模板第一项先破'] if k1 else [f'收盘回到 50 日均线 {R(P, x["m1"])} {"上" if Lg else "下"}面，均线{W["order"]}排好']
    return qm.finish(out)
