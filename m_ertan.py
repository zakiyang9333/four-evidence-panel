"""等二探 v2.1（二探不破战法）规则模型。因果，未回测。对应录屏里面板上的「等二探 v2.1」，这里是照录屏重写的。

录屏最后的五条要点（原话）：
  ① 反弹撞到 0.382 又缩量　不追
  ② 二探低点不破前低
  ③ 二探的量不到前低那天的四成
  ④ 刺破布林下轨　当天收回
  ⑤ 三样齐了试一点　止损放前低下面
面板上那一次的结果：建仓区卡在二探上方，止损压在前低下面，第一目标就是中间那次反弹（B 浪）的高点。
从面板上的数字反推出来的两处（录屏没有明说，标【估算】）：止损 = 前低下方 2%；第二目标 = 前低 + 2 ×（反弹高点 − 前低）。
建仓区的宽度面板上打了码，这里取“二探低点到它上方 1 个 ATR”【估算】。

做法：大跌见低点 A（前低）→ 反弹到 B → 再跌回来的最低点是 C（二探）。
  反弹阶段：反弹够到这一轮跌幅的 0.382、而且反弹的均量比下跌时小 → 不追。
  二探阶段：② C 没破 A；③ 当根成交量 < A 那一根的 40%；④ 当根最低刺破布林下轨、收盘收回 → 三项齐。
做空一侧是同一套规则上下翻过来（二次冲高不过前高），录屏里没讲。
"""
import numpy as np

import qmodel as qm
from qmodel import R, span, up, dn, pct, vol_text

KEY, VERSION, NAME = 'ertan', 'ertan-r1', '等二探 v2.1'
KIND, DEFAULT_SIDE = 'trade', 'long'
DEFAULT_HZ = 60          # 录屏面板上这个模型用的周期
REFS = ('布林带(20,2) 与 RSI(14)：indicators.py', '斐波那契回撤 0.382')
NOTES = ('没有回测过。照录屏「二探不破战法」的五条要点重写，不是原作者的代码。',)
SIDE_NAME = dict(short='做空：等二顶')
MIRRORED = ('short',)
TAGS = ('参数含估算',)
EXTRA = ('prior', 'bounce', 'second', 'fib382')

VIDEO = dict(chase_fib=0.382, vol_ratio=0.4)
VIDEO_NOTE = dict(chase_fib='反弹够到这一轮跌幅的多少，就算撞到线', vol_ratio='二探那天的成交量，不能超过前低那天的多少')
EST = dict(look=250,        # 只在最近 250 根里找前低和反弹
           deep=0.5,        # 回落要吃掉反弹幅度的一半以上，才算“二探”（不然只是反弹途中的小回调）
           stop=0.02,       # 止损 = 前低下方 2%（从面板的数字反推）
           zone_atr=1.0,    # 建仓区 = 二探低点到它上方 1 个 ATR
           t2_mult=2.0)     # 第二目标 = 前低 + 2 ×（反弹高点 − 前低）（从面板的数字反推）
EST_NOTE = dict(look='找前低和反弹的回看根数', deep='回落吃掉反弹幅度的多少才算二探', stop='止损放在前低外侧多远', zone_atr='建仓区的宽度是几个 ATR',
                t2_mult='第二目标：从前低起量几倍的反弹幅度')

LEARN = dict(
    long=dict(
        idea_title='“等二探”在看什么？',
        idea='大跌之后的第一次反弹，常常站不住，还要再跌一次。这套规则不追第一次反弹，等它第二次往下探。第二次没有比第一次跌得更低，卖的人少了很多，当天还被拉了回来，才说条件齐了。',
        idea_note='对应录屏里的「等二探 v2.1」。这里是照录屏讲的规则重写的，不是原作者的代码。',
        list_title='二探清单',
        list='三个问题。第二次探底，守住第一次的低点了吗？这一天的成交量，是不是比第一次见底那天小得多？盘中跌破了布林带下轨，收盘又回到下轨上面了吗？三个都“是”，这套规则才说“条件齐了”。',
        plan='入场区贴在第二次探底的低点上面。止损放在第一次低点的下面一点：连第一次的低点都破了，这个想法就错了。第一目标是中间那次反弹的高点。',
        none='这套清单要先看到一次见底、一次反弹。现在没有这样的走势，所以它既打不了勾，也打不了叉。',
        cards=[('g_boll', '布林带的下轨是什么？', '布林带有三条线。中间是最近二十根的平均价，上下两条是平时波动的边界。价格跌到下边那条的外面，是跌得比平时狠；当天又收回来，是有人接住了。', None, 'chart')]),
    short=dict(
        idea_title='“等二探”的做空一侧在看什么？',
        idea='把做多那套上下翻过来。大涨之后的第一次回落，常常跌不动，还要再冲一次。这套规则不追第一次回落，等它第二次往上冲。第二次没有比第一次冲得更高，买的人少了很多，当天还被压了回来，才说条件齐了。',
        idea_note='做空这一侧录屏里没有讲过，是把同一套规则翻过来用的。',
        list_title='二次冲高清单',
        list='三个问题。第二次冲高，没有超过第一次的高点吗？这一天的成交量，是不是比第一次见顶那天小得多？盘中涨破了布林带上轨，收盘又回到上轨下面了吗？三个都“是”，这套规则才说“条件齐了”。',
        plan='入场区贴在第二次冲高的高点下面。止损放在第一次高点的上面一点：连第一次的高点都过了，这个想法就错了。第一目标是中间那次回落的低点。做空是反着来的：止损在上面，目标在下面。',
        none='这套清单要先看到一次见顶、一次回落。现在没有这样的走势，所以它既打不了勾，也打不了叉。',
        cards=[('g_boll', '布林带的上轨是什么？', '布林带有三条线。中间是最近二十根的平均价，上下两条是平时波动的边界。价格涨到上边那条的外面，是涨得比平时猛；当天又收回来，是有人压住了。', None, 'chart')]))


def _w(P):
    L = qm.long(P)
    return dict(low='低' if L else '高', lowpt='低点' if L else '高点', prior='前低' if L else '前高', fall='回落' if L else '冲高', bounce='反弹' if L else '回落', drop='下跌' if L else '上涨',
                probe='二探' if L else '二次冲高', band='下轨' if L else '上轨', pierce='刺破' if L else '涨破', brk='跌破' if L else '涨过', ext='最低' if L else '最高',
                under='下方' if L else '上方', over='上方' if L else '下方', avg=P['W']['avg'])


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _core(P, j):
    d, h, l, c, v = P['d'], P['h'], P['l'], P['c'], P['v']
    W, X = _w(P), qm.ix(P)
    piv, pend = qm.pivots(P, j, max(0, j - EST['look'])), qm.pending(P, j)
    out = qm.blank(verdict_text='这套清单用不上', phase_text='无结构')
    if len(piv) < 2 or pend is None:
        out['note'] = f'最近 {EST["look"]} 根里还没有“见{W["low"]}、{W["bounce"]}”这样的走势，谈不上{W["probe"]}。'
        out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
        return out
    last = piv[-1]
    cj = float(c[j])

    if last[2] == -1 and pend[2] == 1:                     # ---- 前低已经确认，正在反弹：看要不要“不追” ----
        Ai, Ap = last[0], last[1]
        H0 = piv[-2] if piv[-2][2] == 1 else None
        shapes = [qm.sh_hl(P, Ai, Ap, 'level', f'{W["prior"]} {R(P, Ap)}', key='prior'), qm.sh_badge(P, Ai, Ap, 'A', 'abcd', above=False, key='abc', first=True)]
        legend = [qm.legend_item('prior', _leg_prior(P)), qm.legend_item('abc', _leg_abc(P))]
        k_no = lambda n, name: qm.check(n, name, False, f'还在{W["bounce"]}，{W["probe"]}还没开始', ask=_ASK(P)[n], yes='', no=f'{W["probe"]}还没开始')
        checks = [k_no('K1', f'{W["probe"]}不破{W["prior"]}'), k_no('K2', '量缩到四成以内'), k_no('K3', f'{W["pierce"]}{W["band"]}收回')]
        out.update(phase='反弹中', phase_text=f'{W["bounce"]}中', list='ertan', checks=checks, shapes=shapes, legend=legend, prior=dict(date=d[Ai], price=R(P, Ap)), _ev=Ai, _from=Ai)
        chase = False
        if H0 is not None:
            f382 = Ap + VIDEO['chase_fib'] * (H0[1] - Ap)
            hit = pend[1] >= f382
            vb, vd = qm.vavg(P, Ai + 1, j), qm.vavg(P, H0[0] + 1, Ai)
            dry = vb is not None and vd is not None and vb < vd
            chase = hit and dry
            out['fib382'] = R(P, f382)
            shapes.append(qm.sh_hl(P, H0[0], f382, 'fib', f'0.382 · {R(P, f382)}', key='fib382', dash=[2, 4], w=1))
            legend.append(qm.legend_item('fib382', f'灰色虚线是 0.382 线：这一轮{W["drop"]}收回了不到四成的位置。{W["bounce"]}常在这里{"被挡住" if qm.long(P) else "被托住"}。'))
            why = (f'{W["bounce"]}到过 {R(P, pend[1])}，' + ('已经够到' if hit else '还没到') + f' 0.382 线 {R(P, f382)}；' +
                   (f'{W["bounce"]}段{W["avg"]}量 {vol_text(vb)}，是{W["drop"]}段 {vol_text(vd)} 的 {round(vb / vd * 100)}%，' + ('缩量' if dry else '没缩量') if vb and vd else '量还比不了'))
        else:
            why = f'{W["prior"]}之前没有可比的{W["drop"]}段，0.382 线画不出来'
        if chase:
            out.update(verdict='不追', verdict_text=qm.pick(P, '不追 · 反弹撞线又缩量', '不追空 · 回落撞线又缩量'), state='avoid',
                       note=why + '。', text=f'{W["bounce"]}撞到 0.382 线，成交量却在缩小：按规则不追，等它{W["probe"]}。' + why + '。')
        else:
            out.update(verdict='等二探', verdict_text=f'等{W["probe"]}', state='wait', note=why + '。',
                       text=f'{d[Ai]} 见了{W["prior"]} {R(P, Ap)}，现在是第一次{W["bounce"]}。这套规则不追{W["bounce"]}，等它再{W["fall"]}一次。' + why + '。')
        out['next_needs'] = [f'等{W["bounce"]}走完、再{W["fall"]}回来。{W["probe"]}的{W["lowpt"]}不能{W["brk"]} {R(P, Ap)}']
        return qm.finish(out)

    if not (last[2] == 1 and piv[-2][2] == -1 and pend[2] == -1):
        out['note'] = f'现在的走势不是“见{W["low"]}、{W["bounce"]}、再{W["fall"]}”，这套清单用不上。'
        out['text'] = out['note'] + '不代表没有机会或没有风险。'
        return out

    # ---- 反弹高点 B 已经确认，正在第二次往下：二探清单 ----
    (Ai, Ap, _), (Bi, Bp, _) = piv[-2], last
    Ci, Cp = pend[0], pend[1]
    band = float(X['low'][j]) if np.isfinite(X['low'][j]) else None
    deep = Cp <= Ap + EST['deep'] * (Bp - Ap)
    k1 = Cp >= Ap and deep
    vA = float(v[Ai])
    k2 = float(v[j]) < VIDEO['vol_ratio'] * vA
    k3 = band is not None and float(l[j]) < band and cj > band
    why1 = (f'这次{W["fall"]}的{W["lowpt"]} {R(P, Cp)}（{d[Ci]}）' + ('没有' if Cp >= Ap else '已经') + f'{W["brk"]}{W["prior"]} {R(P, Ap)}（{d[Ai]}）' +
            ('' if deep or Cp < Ap else f'；但只吃掉了{W["bounce"]}幅度的 {round((Bp - Cp) / (Bp - Ap) * 100)}%，还不算{W["probe"]}'))
    why2 = f'今天成交量 {vol_text(v[j])}，是{W["prior"]}那天 {vol_text(vA)} 的 {round(float(v[j]) / vA * 100)}%，' + ('不到四成' if k2 else '没缩到四成以内')
    why3 = ('布林带还算不出来（不足 20 根）' if band is None else
            f'今天{W["ext"]} {R(P, l[j])}，布林{W["band"]} {R(P, band)}，收盘 {R(P, cj)}：' +
            (f'盘中{W["pierce"]}{W["band"]}，收盘收回' if k3 else f'盘中没有{W["pierce"]}{W["band"]}' if float(l[j]) >= band else f'收盘还在{W["band"]}{W["under"]}，没收回'))
    A = _ASK(P)
    pt = lambda i, p, lab: dict(type='point', date=d[i], price=R(P, p), label=lab)
    checks = [qm.check('K1', f'{W["probe"]}不破{W["prior"]}', k1, why1, ask=A['K1'], yes=f'没破{W["prior"]}', no=f'破了{W["prior"]}' if Cp < Ap else f'还不算{W["probe"]}', sticker_yes='守住了',
                       draw=[dict(type='level', price=R(P, Ap), label=W['prior']), pt(Ci, Cp, W['probe'])]),
              qm.check('K2', '量缩到四成以内', k2, why2, ask=A['K2'], yes='量缩下来了', no='量还没缩下来', sticker_yes='缩量了', draw=[dict(type='volume', dates=[d[Ai], d[j]], label='两天的量')]),
              qm.check('K3', f'{W["pierce"]}{W["band"]}收回', k3, why3, ask=A['K3'], yes=f'{W["pierce"]}{W["band"]}又收回', no='还没有刺破收回', sticker_yes='有人接' if qm.long(P) else '有人压',
                       draw=[pt(j, l[j], '今天' + W['ext'])])]
    n0 = max(Ai, j - 79)
    shapes = [qm.sh_hl(P, Ai, Ap, 'level', f'{W["prior"]} {R(P, Ap)}', key='prior'),
              qm.sh_line(P, n0, X['low'][n0:j + 1], 'boll', f'布林{W["band"]}', key='boll', w=1.2),
              qm.sh_seg(P, (Ai, Ap), (Bi, Bp), 'abcd', dash=[6, 4]), qm.sh_seg(P, (Bi, Bp), (Ci, Cp), 'abcd', dash=[6, 4]),
              qm.sh_badge(P, Ai, Ap, 'A', 'abcd', above=False, key='abc', first=True), qm.sh_badge(P, Bi, Bp, 'B', 'abcd', above=True), qm.sh_badge(P, Ci, Cp, 'C', 'abcd', above=False, soft=True)]
    legend = [qm.legend_item('prior', _leg_prior(P)), qm.legend_item('abc', _leg_abc(P)),
              qm.legend_item('boll', f'浅蓝色的线是布林带{W["band"]}：平时波动的{"下" if qm.long(P) else "上"}边界。盘中{W["pierce"]}它、收盘又回来，说明有人{"接" if qm.long(P) else "压"}。')]
    out.update(phase='二探中', phase_text=f'{W["probe"]}中', list='ertan', checks=checks, shapes=shapes, legend=legend, _ev=Ai, _from=Bi,
               prior=dict(date=d[Ai], price=R(P, Ap)), bounce=dict(date=d[Bi], price=R(P, Bp)), second=dict(date=d[Ci], price=R(P, Cp)),
               story=f'{d[Ai][5:]} 见{W["prior"]} {R(P, Ap)}，{W["bounce"]}到 {R(P, Bp)}，现在第二次{W["fall"]}')
    if Cp < Ap:
        out.update(verdict='破前低', verdict_text=f'{W["brk"]}了{W["prior"]}，{W["probe"]}不成立', state='na', note=why1 + '。',
                   text=f'这次{W["fall"]}已经{W["brk"]}了{W["prior"]} {R(P, Ap)}。{W["probe"]}的前提没了，这套清单用不上。')
        return qm.finish(out)
    need = []
    if not k1:
        need.append(f'{W["fall"]}要过 {R(P, Ap + EST["deep"] * (Bp - Ap))}（吃掉{W["bounce"]}的一半），而且不{W["brk"]} {R(P, Ap)}，才算{W["probe"]}')
    if not k2:
        need.append(f'成交量要小于 {vol_text(VIDEO["vol_ratio"] * vA)}（{W["prior"]}那天的四成）')
    if not k3 and band is not None:
        need.append(f'盘中{W["pierce"]}布林{W["band"]}（现在在 {R(P, band)}），收盘再回到它{W["over"]}')
    need.append(f'收盘{W["brk"]} {R(P, Ap)}（{W["prior"]}）：{W["probe"]}不成立')
    out['next_needs'] = need
    if k1 and k2 and k3:
        atr = float(P['atr'][j]) if np.isfinite(P['atr'][j]) else abs(Cp) * 0.03
        pl = qm.plan(P, Cp, Cp + EST['zone_atr'] * atr, dn(Ap, EST['stop']), Bp, Ap + EST['t2_mult'] * (Bp - Ap), '前低起量 2 倍反弹幅度【估算】' if qm.long(P) else '前高起量 2 倍回落幅度【估算】')
        out.update(pl)
        out.update(verdict='条件齐', verdict_text=qm.pick(P, '二探条件齐了（未回测）', '二次冲高条件齐了（未回测）'), state='ready', zone_from=d[Ci],
                   text=(f'第二次{"探底" if qm.long(P) else "冲高"}没{"破" if qm.long(P) else "过"}{W["prior"]}，量能萎缩，{W["pierce"]}布林{W["band"]}当天收回，三项同时成立。这套规则没有回测过，这里只是把清单结果摆出来。' +
                         ('' if qm.long(P) else '（做空一侧是把规则上下翻过来用，录屏里没有讲过。）')))
    else:
        n = sum(1 for x in checks if x['ok'])
        out.update(verdict='等', verdict_text=f'{W["probe"]}中，清单 {n}/3', state='wait',
                   text=f'正在第二次{W["fall"]}，清单 {n}/3。还缺：' + '、'.join(x['name'] for x in checks if not x['ok']) + '。')
    return qm.finish(out)


def _ASK(P):
    W = _w(P)
    return dict(K1=f'{W["probe"]}守住{W["prior"]}了吗？', K2='量缩到四成以内了吗？', K3=f'{W["pierce"]}{W["band"]}又收回了吗？')


def _leg_prior(P):
    return ('橙色横线是前低：上一次跌到的最低点。第二次探底不能比它更低。' if qm.long(P) else '橙色横线是前高：上一次涨到的最高点。第二次冲高不能比它更高。')


def _leg_abc(P):
    return ('A、B、C 三个点：A 是前低，B 是中间反弹的高点，C 是第二次探底的低点。' if qm.long(P) else 'A、B、C 三个点：A 是前高，B 是中间回落的低点，C 是第二次冲高的高点。')
