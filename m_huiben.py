"""回本三看 —— 录屏「回本三看」那一段讲的规则（那一段没有打开面板）。观察用，不给价位。因果，未回测。

录屏「回本三看 · 五条要点」（原话）：
  ① 回本那天　先看收没收上颈线
  ② 价格在成本线上面　不急着卖
  ③ 回踩量缩一半　不破颈线　拿
  ④ 到前高或 1.618　放量长上影　卖
  ⑤ 收盘跌回颈线下　回没回本都走
录屏里的故事：在高处买进，接着跌，熬过一个头肩底，终于回本。三样都在，大概率还有一段；也有不灵的时候，所以守着颈线拿。

规则（上行一侧，假设手里是多单；下行时上下翻过来，假设是空单）：
  头肩底 + 成本线（从那一轮的高点算起的锚定 VWAP：高处买进的人平均成本在哪里）。
  K1 收上颈线；K2 价格在成本线上面；K3 回踩量缩一半、不破颈线（回踩段均量 ≤ 站上颈线那天的一半）。
  卖的信号：走到前高或 1.618 扩展（右肩 + 1.618 ×（头到颈线））附近，出现放量长上影（量 ≥ 前 5 根均量 1.5 倍【估算】，上影 ≥ 振幅一半【估算】）。
  走的信号：收盘跌回颈线下。
"""
import numpy as np

import qmodel as qm
import patterns as pt
from qmodel import R, vol_text

KEY, VERSION, NAME = 'huiben', 'huiben-r1', '回本三看'
KIND, DEFAULT_SIDE = 'watch', 'long'
DEFAULT_HZ = 20          # 录屏面板上这个模型用的周期
MIRRORED = ('short',)
TAGS = ('观察用',)
EXTRA = ('pattern',)
VIDEO = dict(pull_vol=0.5, ext=1.618)
VIDEO_NOTE = dict(pull_vol='回踩段的量不超过站上颈线那天的多少', ext='卖的位置：几倍扩展')
EST = dict(age=120, top_look=80, sell_vol=1.5, shadow=0.5)
EST_NOTE = dict(age='头肩底之后最多跟踪几根', top_look='往前多少根找那一轮的高点（成本线的起点）', sell_vol='放量：至少是前 5 根均量的几倍', shadow='长上影：上影占振幅至少多少')
REFS = ('斐波那契趋势扩展（三点法：头、颈线、右肩），录屏卡片', '锚定 VWAP（Brian Shannon）：价在线上，拿得安心')
NOTES = ('观察用：假设你手里有仓位，告诉你这五条现在各是什么状态。不给入场价位。', '没有回测过。照录屏的五条要点重写。')

LEARN = dict(
    long=dict(idea_title='“回本三看”在看什么？',
              idea='在高处买进，接着跌，熬了很久终于回本。这时候最想卖，它先看三样：收盘站上颈线了没有，价格在成本线上面没有，回踩的时候量缩了、颈线守住了没有。三样都在，大概率还有一段。',
              idea_note='对应录屏「回本三看」。那一段录屏没有打开面板，这里照它的五条要点写。',
              list_title='三看清单', list='三个问题。收盘站上颈线了吗？价格在成本线上面吗？回踩的量缩到一半、没跌破颈线吗？',
              plan='', none='最近没有成形的头肩底，这套观察用不上。', cards=[]),
    short=dict(idea_title='“回本三看”的下行一侧在看什么？',
               idea='把上行那一侧翻过来：假设手里是空单，在低处做空以后被套，终于回本。它看三样：收盘跌破颈线了没有，价格在成本线下面没有，反抽的时候量缩了、颈线守住了没有。',
               idea_note='录屏里讲的是上行一侧，这一侧是翻过来用的。',
               list_title='三看清单', list='三个问题。收盘跌破颈线了吗？价格在成本线下面吗？反抽的量缩到一半、没涨回颈线上面吗？',
               plan='', none='最近没有成形的头肩顶，这套观察用不上。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _core(P, j):
    d, o, h, l, c, v = P['d'], P['o'], P['h'], P['l'], P['c'], P['v']
    Lg = qm.long(P)
    W = dict(pat='头肩底' if Lg else '头肩顶', up='站上' if Lg else '跌破', back='回踩' if Lg else '反抽', on='上' if Lg else '下', fall='跌回' if Lg else '涨回',
             shadow='上影' if Lg else '下影')
    out = qm.blank(verdict_text='这套观察用不上', phase_text='无结构')
    hp = pt.head_shoulders(P, j, age=EST['age'])
    if hp is None or hp['rs_pending']:
        out['note'] = f'最近没有成形的{W["pat"]}。'
        out['text'] = out['note'] + '这套观察今天用不上。'
        return out
    (L1i, L1), (H1i, H1), (L2i, L2), (H2i, H2), (L3i, L3) = [x[:2] for x in (hp['L1'], hp['H1'], hp['L2'], hp['H2'], hp['L3'])]
    neck, b = hp['neck'], hp['brk']
    t0 = max(0, L1i - EST['top_look'])
    anc = t0 + int(np.argmax(h[t0:L1i + 1]))
    top = float(h[anc])
    av = pt.avwap(P, anc, j)
    ext = L3 + VIDEO['ext'] * (H2 - L2)
    k1 = b is not None
    k2 = float(c[j]) > av
    fell = next((t for t in range(b + 1, j + 1) if c[t] < neck(t)), None) if k1 else None
    k3, why3 = False, f'还没{W["up"]}颈线'
    sell = None
    if k1:
        xi = b + int(np.argmax(h[b:j + 1]))
        vp = float(v[xi + 1:j + 1].mean()) if j > xi else None
        k3 = vp is not None and vp <= VIDEO['pull_vol'] * float(v[b]) and fell is None
        why3 = (f'{W["back"]}段均量 {vol_text(vp)}，是{W["up"]}颈线那天 {vol_text(v[b])} 的 {round(vp / float(v[b]) * 100)}%' + ('，缩到一半以内' if vp <= VIDEO['pull_vol'] * float(v[b]) else '，没缩到一半') +
                ('，颈线守住了' if fell is None else '，颈线没守住')) if vp is not None else f'{W["up"]}颈线以后还没{W["back"]}'
        lvl = min(top, ext)
        for t in range(b + 1, j + 1):
            rng = float(h[t] - l[t])
            vr = pt.vol_ratio(P, t)
            if h[t] >= lvl and rng > 0 and (float(h[t]) - max(float(o[t]), float(c[t]))) / rng >= EST['shadow'] and vr is not None and vr >= EST['sell_vol']:
                sell = t
    checks = [qm.check('K1', f'收{"上" if Lg else "下"}颈线', k1, f'{d[b]} 收盘 {R(P, c[b])} {W["up"]}颈线 {R(P, neck(b))}' if k1 else f'颈线现在在 {R(P, neck(j))}，收盘还没{W["up"]}',
                       ask=f'收盘{W["up"]}颈线了吗？', yes=f'{W["up"]}颈线了', no=f'还没{W["up"]}颈线', sticker_yes='回本了'),
              qm.check('K2', f'在成本线{W["on"]}面', k2, f'成本线（从 {d[anc]} 那一轮的{"高" if Lg else "低"}点 {R(P, top)} 算起）在 {R(P, av)}，收盘 {R(P, c[j])}',
                       ask=f'价格在成本线{W["on"]}面吗？', yes=f'在成本线{W["on"]}面', no=f'在成本线{"下" if Lg else "上"}面', sticker_yes='拿得安心'),
              qm.check('K3', f'{W["back"]}量缩一半、不破颈线', k3, why3, ask=f'{W["back"]}量缩了、颈线守住了吗？', yes='量缩了，颈线守住了', no='还没看到', sticker_yes='拿')]
    shapes = [qm.sh_seg(P, (H1i, H1), (j, neck(j)), 'neck', '颈线', key='neck', w=1.6),
              qm.sh_badge(P, L1i, L1, '左', 'push', above=False, key='hs', first=True), qm.sh_badge(P, L2i, L2, '头', 'push', above=False), qm.sh_badge(P, L3i, L3, '右', 'push', above=False),
              qm.sh_hl(P, max(anc, j - 60), av, 'vwap', f'成本线 {R(P, av)}', key='cost', w=1.6),
              qm.sh_hl(P, anc, top, 'target', f'前{"高" if Lg else "低"} {R(P, top)}', key='sell', dash=[3, 4], w=1.2), qm.sh_hl(P, L3i, ext, 'target2', f'1.618 · {R(P, ext)}', dash=[3, 4], w=1.2)]
    legend = [qm.legend_item('neck', '橙色斜线是颈线。'), qm.legend_item('hs', '“左、头、右”三个圆点是左肩、头、右肩。'),
              qm.legend_item('cost', f'黄线是成本线：从那一轮的{"高" if Lg else "低"}点算起，那时候进场的人平均成本在这里。'),
              qm.legend_item('sell', f'粉色虚线是前{"高" if Lg else "低"}和 1.618 扩展：走到这里放量又留长{W["shadow"]}，录屏说卖。')]
    out.update(phase='回本后' if k1 else '颈线下', phase_text='回本后' if k1 else '颈线附近', list=KEY, checks=checks, shapes=shapes, legend=legend, _ev=L2i,
               pattern=dict(neck=R(P, neck(j)), cost=R(P, av), prior=R(P, top), ext=R(P, ext)), story=f'{d[L2i][5:]} 是头，颈线在 {R(P, neck(j))}')
    if fell is not None:
        out.update(verdict='走', verdict_text=f'收盘{W["fall"]}颈线{"下" if Lg else "上"}：回没回本都走', state='risk',
                   text=f'{d[fell]} 收盘{W["fall"]}颈线{"下" if Lg else "上"}面。录屏的第五条：回没回本都走。')
    elif sell is not None:
        out.update(verdict='卖', verdict_text=f'到前{"高" if Lg else "低"}（或 1.618）放量长{W["shadow"]}：卖', state='risk',
                   text=f'{d[sell]} 走到前{"高" if Lg else "低"}或 1.618 一带，放量又留下长{W["shadow"]}。录屏的第四条：这里卖。')
    elif k1 and k2 and k3:
        out.update(verdict='拿着', verdict_text='三样都在：拿着，守颈线', state='watch', text='收上了颈线，价格在成本线上面，回踩量缩了、颈线守住了。三样都在，大概率还有一段；也有不灵的时候，所以守着颈线拿。')
    elif k1 and k2:
        out.update(verdict='拿着', verdict_text=f'拿着，等{W["back"]}看量', state='watch', text=f'收上了颈线，价格在成本线上面，不急着卖。还要看{W["back"]}的时候量缩不缩、颈线守不守得住。')
    else:
        n = sum(1 for x in checks if x['ok'])
        out.update(verdict='等', verdict_text=f'三看 {n}/3', state='wait', text='还缺：' + '、'.join(x['name'] for x in checks if not x['ok']) + '。')
    out['next_needs'] = [f'收盘{W["fall"]}颈线 {R(P, neck(j))} {"下" if Lg else "上"}面：回没回本都走', f'走到 {R(P, min(top, ext))} 一带放量长{W["shadow"]}：卖']
    return qm.finish(out)
