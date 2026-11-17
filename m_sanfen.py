"""三份法 测试07 —— 录屏「反梭哈建仓论」里面板上的模型。因果，未回测。

面板上那一次（做多 · 中线 60 日 · 已持仓）的说明原话：放量站上颈线，头肩底确认。
录屏的实验结论（原话）：
  ① 钱分三份　一份只买一个位置
  ② 第一份：回撤到 0.382 附近 + 长下影收回
  ③ 第二份：0.618 和量山重合
  ④ 第三份：放量收盘站上颈线才买
  ⑤ 止损：前两份放 0.786 下　买完第三份挪到颈线下
面板上的画法：建仓区包住破线这一根，止损也在颈线下面，目标落在头肩的量幅。

规则（做多那一侧是头肩底；做空时上下翻过来，录屏没讲）：
  K1 头肩底成形，右肩没跌破 0.786（这一段指“头到颈线”那一段的回撤）。
  K2 放量：站上颈线那一根的成交量 ≥ 前 5 根均量的 1.5 倍（“放量”的倍数录屏这一段没说，借用「破位反抽 3.1」那一段的 1.5 倍）。
  K3 收盘站上颈线（最近 3 根之内站上，现在还在线上）。
三项齐了：建仓区 = 破线那一根的最低到最高；止损 = 颈线下方 1 个 ATR【估算】；第一目标 = 颈线 + 头部深度；第二目标 = 前高（没有更高的前高就用 1.618 倍深度）【估算】。
三份各自有没有出现过，列在“三份建仓表”里。
"""
import numpy as np

import qmodel as qm
import patterns as pt
from qmodel import R, up, dn, vol_text

KEY, VERSION, NAME = 'sanfen', 'sanfen-r1', '三份法 测试07'
KIND, DEFAULT_SIDE = 'trade', 'long'
DEFAULT_HZ = 60          # 录屏面板上这个模型用的周期
MIRRORED = ('short',)
TAGS = ('参数含估算',)
EXTRA = ('pattern', 'rows')
VIDEO = dict(f1=0.382, f2=0.618, f_stop=0.786)
VIDEO_NOTE = dict(f1='第一份：回撤到哪一档附近', f2='第二份：哪一档要和量山重合', f_stop='前两份的止损放在哪一档下面')
EST = dict(vol=1.5, fresh=3, near=0.5, wick=0.5, poc_tol=1.0, stop_atr=1.0, t2_mult=1.618, look_high=120)
EST_NOTE = dict(vol='放量：成交量至少是前 5 根均量的几倍', fresh='站上颈线最多是几根之前', near='“附近”的宽度是几个 ATR', wick='长下影：下影占整根振幅至少多少',
                poc_tol='量山和 0.618 相差几个 ATR 以内算重合', stop_atr='第三份买完后，止损在颈线下方几个 ATR', t2_mult='没有前高时，第二目标是几倍头部深度',
                look_high='找前高的回看根数')
REFS = ('neurotrader888/TechnicalAnalysisAutomation（head_shoulders.py：目标 = 颈线 ± 头高）', '固定范围成交量分布（量山）：indicators.volume_profile')
NOTES = ('没有回测过。这是照录屏的实验结论重写的，不是原作者的代码。', '录屏里三份合计的收益是那一段行情的结果，不代表这套方法以后也这样。')

LEARN = dict(
    long=dict(idea_title='“三份法”在看什么？',
              idea='它不一次买满，把钱分成三份，每份只在一个位置买。第一份买在回撤到 0.382、留下长下影的地方。第二份买在 0.618 和量山碰在一起的地方。第三份等放量站上颈线才买。',
              idea_note='对应录屏「反梭哈建仓论」。这里是照录屏讲的规则重写的。',
              list_title='第三份的清单', list='面板只在第三份的位置说“条件齐了”。三个问题。头肩底成形了吗？站上颈线那天放量了吗？收盘真的站在颈线上面吗？',
              plan='建仓区包住站上颈线的那一根。止损放在颈线下面。第一目标是颈线再加一个头的深度。前两份的位置和止损，写在下面的三份建仓表里。',
              none='它要先看到一个头肩底。现在没有这样的走势，所以清单空着。',
              cards=[('g_poc', '“量山”是什么？', '把一段时间里每个价位成交了多少股堆起来，像一座侧着放的山。山最高的地方，是最多人买卖过的价位。价格回到这里，常常有人接。', None, 'chart')]),
    short=dict(idea_title='“三份法”的做空一侧在看什么？',
               idea='把做多那套上下翻过来。它找头肩顶，把仓位分成三份。第一份放在反弹到 0.382、留下长上影的地方。第二份放在 0.618 和量山碰在一起的地方。第三份等放量跌破颈线。',
               idea_note='做空这一侧录屏里没有讲过，是把同一套规则翻过来用的。',
               list_title='第三份的清单', list='三个问题。头肩顶成形了吗？跌破颈线那天放量了吗？收盘真的在颈线下面吗？',
               plan='建仓区包住跌破颈线的那一根。止损放在颈线上面。第一目标是颈线再往下一个头的高度。做空是反着来的：止损在上，目标在下。',
               none='它要先看到一个头肩顶。现在没有这样的走势，所以清单空着。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _core(P, j):
    d, o, h, l, c, v = P['d'], P['o'], P['h'], P['l'], P['c'], P['v']
    L = qm.long(P)
    pat, brk_w, neck_side = ('头肩底', '站上', '上面') if L else ('头肩顶', '跌破', '下面')
    out = qm.blank(verdict_text='这套清单用不上', phase_text='无结构')
    hp = pt.head_shoulders(P, j)
    if hp is None:
        out['note'] = f'最近没有成形的{pat}。'
        out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
        return out
    (L1i, L1), (H1i, H1), (L2i, L2), (H2i, H2), (L3i, L3) = [x[:2] for x in (hp['L1'], hp['H1'], hp['L2'], hp['H2'], hp['L3'])]
    neck, depth, b = hp['neck'], hp['depth'], hp['brk']
    a = pt.atr(P, j)
    fib = lambda r: H2 - r * (H2 - L2)                       # 头到颈线这一段的回撤档位（工作方向）
    f1, f2, f786 = fib(VIDEO['f1']), fib(VIDEO['f2']), fib(VIDEO['f_stop'])
    k1 = not hp['rs_pending'] and L3 >= f786
    # 三份建仓表：前两份有没有出现过（只看右肩那一段，第 j 根之前的数据）
    rs = range(H2i + 1, (L3i if not hp['rs_pending'] else j) + 1)
    t1_hit = next((t for t in rs if l[t] <= f1 + EST['near'] * a and (min(o[t], c[t]) - l[t]) >= EST['wick'] * max(h[t] - l[t], 1e-12) and c[t] > f1), None)
    mount = pt.poc(P, L1i, max(L1i, H2i))
    coin = abs(mount - f2) <= EST['poc_tol'] * a
    t2_hit = next((t for t in rs if l[t] <= f2 + EST['near'] * a), None) if coin else None
    vr = pt.vol_ratio(P, b) if b is not None else None
    k2 = vr is not None and vr >= EST['vol']
    k3 = b is not None and j - b < EST['fresh'] and float(c[j]) > neck(j)
    rows = [dict(k='第一份', v=R(P, f1), sub='回撤到 0.382 附近 + 长下影收回：' + (f'{d[t1_hit]} 出现过' if t1_hit is not None else '右肩这一段没出现')),
            dict(k='第二份', v=R(P, f2), sub=f'0.618 和量山（{R(P, mount)}）' + ('重合' if coin else '没重合') + ('，' + d[t2_hit] + ' 碰到过' if t2_hit is not None else '')),
            dict(k='第三份', v=R(P, neck(j)), sub=f'放量收盘{brk_w}颈线：' + (f'{d[b]}，成交量是前 5 根均量的 {vr:.1f} 倍' if b is not None and vr else '还没有')),
            dict(k='止损', v=R(P, f786), sub=f'前两份放在 0.786 {"下" if L else "上"}面；买完第三份挪到颈线{"下" if L else "上"}面')]
    checks = [qm.check('K1', f'{pat}成形', k1, f'头 {R(P, L2)}（{d[L2i]}），右肩 {R(P, L3)}（{d[L3i]}）' + ('，没破 0.786' if k1 else ('，右肩还在走' if hp['rs_pending'] else '，破了 0.786')),
                       ask=f'{pat}成形了吗？', yes=f'{pat}成形了', no='还没成形', sticker_yes='成形了'),
              qm.check('K2', '放量', k2, (f'{brk_w}颈线那天（{d[b]}）成交量 {vol_text(v[b])}，是前 5 根均量的 {vr:.1f} 倍，' + ('够' if k2 else '不够') + f' {EST["vol"]} 倍') if b is not None and vr else f'还没有{brk_w}颈线',
                       ask=f'{brk_w}颈线那天放量了吗？', yes='放量了', no='没放量', sticker_yes='放量'),
              qm.check('K3', f'收盘{brk_w}颈线', k3, (f'{d[b]} 收盘 {R(P, c[b])} {brk_w}颈线 {R(P, neck(b))}，现在收盘 {R(P, c[j])}' + ('，还在线' + neck_side if float(c[j]) > neck(j) else '，又回去了')) if b is not None else f'收盘还没{brk_w}颈线 {R(P, neck(j))}',
                       ask=f'收盘{brk_w}颈线了吗？', yes=f'{brk_w}颈线了', no=f'还没{brk_w}颈线', sticker_yes='确认')]
    shapes = [qm.sh_seg(P, (H1i, H1), (j, neck(j)), 'neck', '颈线', key='neck', w=1.6),
              qm.sh_badge(P, L1i, L1, '左', 'push', above=False, key='hs', first=True), qm.sh_badge(P, L2i, L2, '头', 'push', above=False), qm.sh_badge(P, L3i, L3, '右', 'push', above=False),
              qm.sh_hl(P, H2i, f1, 'fib', f'第一份 0.382 · {R(P, f1)}', key='tranche', dash=[2, 4], w=1), qm.sh_hl(P, H2i, f2, 'fib', f'第二份 0.618 · {R(P, f2)}', dash=[2, 4], w=1),
              qm.sh_hl(P, H2i, f786, 'stop', f'0.786 · {R(P, f786)}', dash=[2, 4], w=1), qm.sh_profile(P, L1i, max(L1i + 1, H2i), label='量山', key='poc')]
    legend = [qm.legend_item('neck', '橙色斜线是颈线。'), qm.legend_item('hs', '“左、头、右”三个圆点是左肩、头、右肩。'),
              qm.legend_item('tranche', '灰色虚线是三份法的位置：0.382 放第一份，0.618 放第二份，0.786 是前两份的止损。'),
              qm.legend_item('poc', '左边伸出来的横条是量山：每个价位成交了多少。最长那一条是最多人买卖过的价位。')]
    out.update(phase='颈线附近', phase_text='颈线附近', list=KEY, checks=checks, shapes=shapes, legend=legend, rows=dict(title='三份建仓表（录屏的实验结论）', rows=rows),
               _ev=L2i, _from=L3i, pattern=dict(left=R(P, L1), head=R(P, L2), right=R(P, L3), neck=R(P, neck(j)), poc=R(P, mount)),
               story=f'{d[L2i][5:]} 是头，{d[L3i][5:]} 是右肩，颈线在 {R(P, neck(j))}')
    if k1 and k2 and k3:
        t1 = neck(b) + depth
        hi = float(np.max(h[max(0, L1i - EST['look_high']):L1i + 1]))
        t2 = hi if hi > t1 else neck(b) + EST['t2_mult'] * depth
        pl = qm.plan(P, float(l[b]), float(h[b]), neck(j) - EST['stop_atr'] * a, t1, t2, '前高' if hi > t1 else '1.618 倍头部深度【估算】')
        out.update(pl)
        out.update(verdict='条件齐', verdict_text='条件齐了（未回测）', state='ready', zone_from=d[b],
                   text=f'放量{brk_w}颈线，{pat}确认。这套规则没有回测过，这里只是把清单结果摆出来。' + ('' if L else '（做空一侧是把规则上下翻过来用的，录屏里没有讲过。）'))
    else:
        n = sum(1 for x in checks if x['ok'])
        stale = b is not None and j - b >= EST['fresh'] and float(c[j]) > neck(j)
        out.update(verdict='等', verdict_text=f'清单 {n}/3，等' if not stale else f'{brk_w}颈线已经过去几天了，不追', state='wait' if not stale else 'avoid',
                   text=f'{pat}在颈线附近，清单 {n}/3。还缺：' + '、'.join(x['name'] for x in checks if not x['ok']) + '。三份建仓表里写着前两份的位置。')
        out['next_needs'] = [f'放量（≥ 前 5 根均量的 {EST["vol"]} 倍）收盘{brk_w}颈线 {R(P, neck(j))}，才是第三份']
    return qm.finish(out)
