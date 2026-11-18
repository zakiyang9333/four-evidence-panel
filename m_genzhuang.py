"""跟庄 3 号 —— 录屏「跟庄技巧 2.0」里面板上的模型。因果，未回测。两侧的规则不一样（不是镜像）。

面板上那一次（做空 · 中线 60 日）的说明原话：头肩顶跌破颈线，反弹缩量，量山压在头顶，偏空。
录屏最后「记住这 4 条」（原话）：
  ① 4 浪不碰 1 浪顶　跟庄拿
  ② 5 浪到 0.618 + 天量　跑
  ③ 右肩缩量　破颈线　空
  ④ 多单止损 1 浪顶　空单止损右肩
所以两侧各管各的：
  做多（跟庄拿）：K1 一到三浪成立（二浪不破一浪起点，三浪比一浪长）；K2 四浪不碰一浪顶；K3 五浪还没走到 0.618 扩展、也没见天量。
    三项齐了：止损 = 一浪顶下方 1%【估算】；第一目标 = 四浪底 + 0.618 ×（一浪起点到三浪顶）；第二目标 = 1.0 倍【估算】。
    五浪已经到 0.618 扩展而且放出天量：跑（不追）。
  做空（庄出货）：K1 头肩顶收盘跌破颈线；K2 反弹缩量（反弹段均量不到破线那天的一半，借用「破位反抽 3.1」的写法）；K3 量山压在头顶（成交最密的价位在头那一半）。
    三项齐了：止损 = 右肩上方 1%【估算】；第一目标 = 破线后跌到过的最低点；第二目标 = 颈线往下一个头的高度。
"""
import numpy as np

import qmodel as qm
import patterns as pt
from qmodel import R, up, dn, vol_text

KEY, VERSION, NAME = 'genzhuang', 'genzhuang-r1', '跟庄3号'
KIND, DEFAULT_SIDE = 'trade', 'short'
DEFAULT_HZ = 60          # 录屏面板上这个模型用的周期
ASYMMETRIC = True
SIDE_NAME = dict(long='跟庄拿', short='庄出货')
TAGS = ('参数含估算',)
EXTRA = ('pattern',)
VIDEO = dict(ext=0.618, climax=60)
VIDEO_NOTE = dict(ext='五浪看一到三浪那一段的多少倍扩展', climax='天量：最近多少根里最大的量')
EST = dict(stop=0.01, t2_ext=1.0, retest_vol=0.5, zone_atr=0.5)
EST_NOTE = dict(stop='止损放在一浪顶（做多）或右肩（做空）外侧多远', t2_ext='第二目标：几倍的一到三浪', retest_vol='反弹缩量：反弹段均量不超过破线那天的多少',
                zone_atr='建仓区是现价上下几个 ATR')
REFS = ('艾略特三条硬规矩：二浪不破一浪起点、三浪不是最短、四浪不进一浪区间（drstevendev/ElliottWaveAnalyzer 的 WaveRules.py 也是这三条）',
        'ta4j 的艾略特工具：五浪投影常用 0.618 / 1.0 / 1.618 倍，从四浪末端量起', 'neurotrader888/TechnicalAnalysisAutomation（head_shoulders.py：颈线连两个反弹点，止损放右肩）')
NOTES = ('没有回测过。照录屏「记住这 4 条」重写，不是原作者的代码。', '两侧不是镜像：做多看五浪推进，做空看头肩顶出货，和录屏讲的一样。')

LEARN = dict(
    long=dict(idea_title='“跟庄 3 号”的做多一侧在看什么？',
              idea='它把一段上涨数成五浪。一浪是庄家先试一试，三浪是真拉。四浪回调没碰到一浪的顶，说明庄还在，就跟着拿。五浪冲到扩展位还放出天量，就是庄在出货，该跑了。',
              idea_note='对应录屏「跟庄技巧 2.0」的第 ①②④ 条。',
              list_title='跟庄清单', list='三个问题。一到三浪数得出来吗？四浪没碰一浪顶吗？五浪还没到扩展位、也没见天量吗？三个都“是”，才说条件齐了。',
              plan='止损放在一浪顶下面：四浪跌进一浪的地盘，就说明数错了。第一目标是五浪的 0.618 扩展位。', none='最近数不出一段五浪推进，清单空着。', cards=[]),
    short=dict(idea_title='“跟庄 3 号”的做空一侧在看什么？',
               idea='它找庄家出货的样子：先是一个头肩顶。跌破颈线以后，反弹的时候没什么量，说明没人愿意接。成交最密的那座量山，压在头顶上面，上面全是等着解套的人。',
               idea_note='对应录屏「跟庄技巧 2.0」的第 ③④ 条，录屏里面板用的就是这一侧。',
               list_title='出货清单', list='三个问题。头肩顶跌破颈线了吗？之后的反弹缩量了吗？量山压在头那一带吗？三个都“是”，才说条件齐了。',
               plan='止损放在右肩上面。第一目标是破线以后跌到过的最低点。第二目标是颈线再往下一个头的高度。做空是反着来的：止损在上，目标在下。',
               none='最近没有跌破颈线的头肩顶，清单空着。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _long(P, j) if qm.long(P) else _short(P, j))


def _long(P, j):
    d, h, v = P['d'], P['h'], P['v']
    out = qm.blank(verdict_text='这套清单用不上', phase_text='无结构')
    w = pt.impulse(P, j)
    if w is None:
        out['note'] = '最近数不出“一浪、二浪、三浪、四浪，现在在五浪里”这样的走势。'
        out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
        return out
    (i0, p0), (i1, p1), (i2, p2), (i3, p3), (i4, p4) = [x[:2] for x in (w['P0'], w['P1'], w['P2'], w['P3'], w['P4'])]
    ext = p4 + VIDEO['ext'] * (p3 - p0)
    top = float(np.max(h[i4:j + 1]))
    w0 = max(0, j - VIDEO['climax'] + 1)
    climax_bar = next((t for t in range(i4 + 1, j + 1) if h[t] >= ext and v[t] >= v[max(0, t - VIDEO['climax'] + 1):t + 1].max()), None)
    k2 = p4 > p1
    k3 = climax_bar is None and top < ext
    checks = [qm.check('K1', '一到三浪成立', True, f'一浪 {R(P, p0)}→{R(P, p1)}，二浪回到 {R(P, p2)} 没破起点，三浪冲到 {R(P, p3)}，比一浪长', ask='一到三浪数得出来吗？', yes='数得出来', sticker_yes='三浪真拉'),
              qm.check('K2', '4 浪不碰 1 浪顶', k2, f'四浪低点 {R(P, p4)}（{d[i4]}），一浪顶 {R(P, p1)}：' + ('没碰到' if k2 else '碰到了，先认错'), ask='四浪没碰一浪顶吗？', yes='四浪没碰一浪顶', no='四浪碰了一浪顶', sticker_yes='跟庄拿', sticker_no='认错'),
              qm.check('K3', '5 浪未到 0.618 + 天量', k3, f'0.618 扩展位 {R(P, ext)}，五浪最高到过 {R(P, top)}' + ('，在那里放出了天量' if climax_bar is not None else '，没见天量' if top >= ext else '，还没到'),
                       ask='五浪还没到出货的位置吗？', yes='还没到', no='到了还放天量', sticker_yes='还能拿', sticker_no='跑')]
    shapes = [qm.sh_seg(P, (i0, p0), (i1, p1), 'wave'), qm.sh_seg(P, (i1, p1), (i2, p2), 'wave'), qm.sh_seg(P, (i2, p2), (i3, p3), 'wave'), qm.sh_seg(P, (i3, p3), (i4, p4), 'wave'),
              qm.sh_badge(P, i1, p1, '1', 'wave', key='wave', first=True), qm.sh_badge(P, i2, p2, '2', 'wave', above=False), qm.sh_badge(P, i3, p3, '3', 'wave'), qm.sh_badge(P, i4, p4, '4', 'wave', above=False),
              qm.sh_hl(P, i1, p1, 'level', f'1 浪顶 {R(P, p1)}', key='w1top'), qm.sh_hl(P, i4, ext, 'target', f'0.618 扩展 {R(P, ext)}', key='ext', dash=[3, 4])]
    legend = [qm.legend_item('wave', '浅蓝色折线和数字 1–4 是数出来的浪：1、3 往上冲，2、4 往回调。'), qm.legend_item('w1top', '橙色横线是一浪的顶：四浪回调不该碰到它。'),
              qm.legend_item('ext', '粉色虚线是五浪的 0.618 扩展位：走到这里还放天量，就是该跑的地方。')]
    out.update(phase='五浪中', phase_text='五浪中', list=KEY, checks=checks, shapes=shapes, legend=legend, _ev=i1, _from=i4,
               pattern=dict(w0=R(P, p0), w1=R(P, p1), w2=R(P, p2), w3=R(P, p3), w4=R(P, p4), ext=R(P, ext)), story=f'一浪顶 {R(P, p1)}，四浪底 {R(P, p4)}，现在在五浪')
    cj = float(P['c'][j])
    if climax_bar is not None:
        out.update(verdict='跑', verdict_text='五浪到 0.618 + 天量：跑', state='avoid', text=f'{d[climax_bar]} 五浪走到 0.618 扩展位 {R(P, ext)}，还放出了天量。按规则这是庄在出货，不跟了。')
    elif not k2:
        out.update(verdict='认错', verdict_text='四浪碰了一浪顶，先认错', state='na', text='四浪跌进了一浪的地盘，这一段数浪数错了。按规则先认错，清单不再适用。')
    elif top >= ext:            # 五浪到过扩展位（今天收回到下面也算）：清单第三项不成立，和“到了扩展位”一样不追
        out.update(verdict='不追', verdict_text='到了扩展位，不追', state='avoid',
                   text=f'五浪已经到过 0.618 扩展位 {R(P, ext)}（最高 {R(P, top)}），没见天量，也不再追。' if cj < ext else f'价格已经到 0.618 扩展位 {R(P, ext)}，没见天量，也不再追。')
    else:
        a = pt.atr(P, j)
        out.update(qm.plan(P, cj - EST['zone_atr'] * a, cj + EST['zone_atr'] * a, dn(p1, EST['stop']), ext, p4 + EST['t2_ext'] * (p3 - p0), '1.0 倍一到三浪【估算】'))
        out.update(verdict='条件齐', verdict_text='跟庄拿（未回测）', state='ready', zone_from=d[i4],
                   text='四浪没碰一浪顶，五浪还没到扩展位，跟庄拿。多单止损放一浪顶。这套规则没有回测过，这里只是把清单结果摆出来。')
    out['next_needs'] = [f'收盘跌回一浪顶 {R(P, p1)} 下面：数错了，认错', f'五浪到 {R(P, ext)} 附近放天量：跑']
    return qm.finish(out)


def _short(P, j):
    d, h, l, c, v = P['d'], P['h'], P['l'], P['c'], P['v']
    out = qm.blank(verdict_text='这套清单用不上', phase_text='无结构')
    hp = pt.head_shoulders(P, j)
    if hp is None or hp['brk'] is None:
        out['note'] = '最近没有跌破颈线的头肩顶。' if hp is None else f'头肩顶成形了，收盘还没跌破颈线 {R(P, hp["neck"](j))}。'
        out['text'] = out['note'] + '这套清单今天还用不上。'
        out['state'] = 'na' if hp is None else 'wait'
        if hp is not None:
            out.update(verdict='等', verdict_text='等跌破颈线')
        return out
    (L1i, L1), (H1i, H1), (L2i, L2), (H2i, H2), (L3i, L3) = [x[:2] for x in (hp['L1'], hp['H1'], hp['L2'], hp['H2'], hp['L3'])]
    neck, depth, b = hp['neck'], hp['depth'], hp['brk']
    xi = b + int(np.argmax(h[b:j + 1]))                      # 破线之后走到过的最远处（工作方向的最高）
    far = float(h[xi])
    vb = float(v[b])
    vp = float(v[xi + 1:j + 1].mean()) if j > xi else None
    k2 = vp is not None and vp <= EST['retest_vol'] * vb
    mount = pt.poc(P, L1i, j)
    k3 = mount <= L2 + 0.5 * (neck(L2i) - L2)
    back = float(c[j]) <= neck(j)
    checks = [qm.check('K1', '头肩顶跌破颈线', not back, f'{d[b]} 收盘 {R(P, c[b])} 跌破颈线 {R(P, neck(b))}' + ('，现在又回到颈线上面了' if back else ''), ask='头肩顶跌破颈线了吗？', yes='跌破了', no='又回去了', sticker_yes='破了'),
              qm.check('K2', '反弹缩量', k2, (f'破线后反弹段均量 {vol_text(vp)}，是破线那天 {vol_text(vb)} 的 {round(vp / vb * 100)}%，' + ('缩到一半以内' if k2 else '没缩到一半')) if vp is not None else '破线之后还没有反弹',
                       ask='反弹缩量了吗？', yes='反弹没量', no='反弹有量', sticker_yes='没人接'),
              qm.check('K3', '量山压在头顶', k3, f'成交最密的价位在 {R(P, mount)}，' + ('在头那一半' if k3 else '不在头那一半') + f'（头 {R(P, L2)}，颈线 {R(P, neck(L2i))}）', ask='量山压在头顶吗？', yes='量山压在头顶', no='量山不在头顶', sticker_yes='有人等解套')]
    shapes = [qm.sh_seg(P, (H1i, H1), (j, neck(j)), 'neck', '颈线', key='neck', w=1.6),
              qm.sh_badge(P, L1i, L1, '左', 'push', above=False, key='hs', first=True), qm.sh_badge(P, L2i, L2, '头', 'push', above=False), qm.sh_badge(P, L3i, L3, '右', 'push', above=False),
              qm.sh_profile(P, L1i, j, label='量山', key='poc'), qm.sh_badge(P, b, float(c[b]), '破', 'level', above=True)]
    legend = [qm.legend_item('neck', '橙色斜线是颈线：把头两边回落的低点连起来。'), qm.legend_item('hs', '“左、头、右”三个圆点是左肩、头、右肩。'),
              qm.legend_item('poc', '左边伸出来的横条是量山。最长那一条压在头那一带，上面全是等着解套的人。')]
    out.update(phase='破线后', phase_text='跌破颈线后', list=KEY, checks=checks, shapes=shapes, legend=legend, _ev=L2i, _from=b,
               pattern=dict(left=R(P, L1), head=R(P, L2), right=R(P, L3), neck=R(P, neck(j)), poc=R(P, mount)), story=f'{d[b][5:]} 跌破颈线 {R(P, neck(b))}')
    cj = float(c[j])
    if all(x['ok'] for x in checks):
        a = pt.atr(P, j)
        pl = qm.plan(P, cj - EST['zone_atr'] * a, cj + EST['zone_atr'] * a, dn(L3, EST['stop']), far if far > cj + EST['zone_atr'] * a * 0 else neck(b) + 0.5 * depth,
                     neck(b) + depth, '颈线往下一个头的高度')
        out.update(pl)
        out.update(verdict='条件齐', verdict_text='庄出货，条件齐了（未回测）', state='ready', zone_from=d[xi],
                   text='头肩顶跌破颈线，反弹缩量，量山压在头顶，偏空。空单止损放右肩上面。这套规则没有回测过，这里只是把清单结果摆出来。')
    else:
        n = sum(1 for x in checks if x['ok'])
        out.update(verdict='等', verdict_text=f'清单 {n}/3，等', state='wait', text='跌破颈线以后还在看。还缺：' + '、'.join(x['name'] for x in checks if not x['ok']) + '。')
    out['next_needs'] = [f'收盘回到右肩 {R(P, L3)} 上面：这个头肩顶作废', f'收盘站回颈线 {R(P, neck(j))} 上面：跌破是假的']
    return qm.finish(out)
