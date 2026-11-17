"""不接飞刀 v1.3 —— 录屏「三驱抄底战法」里面板上的模型。因果，未回测。

面板上那一次（做多 · 中线 60 日）的说明原话：第三次探底出现底背离，收回布林下轨，三项条件满足。价格进入建仓区，跌破止损离场。
录屏「三驱抄底战法 · 五条要点」（原话）：
  ① RSI 在 30 下面趴着　不抄
  ② 贴着布林下轨　口子还在张　不抄
  ③ 等第三下　落在扩展 0.5～0.618
  ④ 价格新低 RSI 不新低　收回下轨再买
  ⑤ 止损放长下影下面　目标看反弹高点
「三驱形态」卡片：连砸三下、每一下都创新低，中间夹着两次反弹；第一目标 = 第二次反弹的高点，第二目标 = 第一次反弹的高点；跌出第四下，形态失效。

规则（做多一侧；做空时整张图上下翻过来，录屏没讲）：
  K1 第三下落在扩展 0.5～0.618：从第二次反弹的高点往下，量出第二下长度的 0.5～0.618 倍，第三下的低点落在这一带（前后放宽半个 ATR【估算】），而且创了新低。
  K2 价格新低，RSI 不新低：第三下那天的 RSI 比第二下那天高。
  K3 收回下轨：最近 3 根里刺破过布林下轨，今天收盘回到下轨上面，RSI 也回到 30 上面。
  “不抄”的两种情况单独判断：RSI 还在 30 下面；或者收盘还贴着下轨、布林口子还在张开。
三项齐了：建仓区 = 现价往下半个 ATR【估算】；止损 = 第三下低点（长下影）下方 1%【估算】；第一目标 = 第二次反弹高点；第二目标 = 第一次反弹高点。
"""
import numpy as np

import qmodel as qm
import patterns as pt
from qmodel import R, dn

KEY, VERSION, NAME = 'feidao', 'feidao-r1', '不接飞刀 v1.3'
KIND, DEFAULT_SIDE = 'trade', 'long'
DEFAULT_HZ = 60          # 录屏面板上这个模型用的周期
MIRRORED = ('short',)
SIDE_NAME = dict(short='做空：三驱见顶')
TAGS = ('参数含估算',)
EXTRA = ('drives',)
VIDEO = dict(ext_lo=0.5, ext_hi=0.618, rsi_floor=30)
VIDEO_NOTE = dict(ext_lo='第三下落点：第二下长度的最少几倍', ext_hi='第三下落点：第二下长度的最多几倍', rsi_floor='RSI 在这条线下面趴着，不抄')
EST = dict(tol_atr=0.5, pierce_n=3, width_n=3, zone_atr=0.5, stop=0.01)
EST_NOTE = dict(tol_atr='第三下落点前后放宽几个 ATR', pierce_n='最近几根里刺破过下轨就算', width_n='布林口子和几根之前比，看是不是还在张开', zone_atr='建仓区是现价往下几个 ATR',
                stop='止损放在第三下低点外侧多远')
REFS = ('三驱形态：Larry Pesavento《斐波那契比例与形态识别》（1997），录屏卡片里的出处', 'wickra-lib/wickra three_drives.rs：每一驱比前一段回撤长 1.13～1.75 倍（这里按录屏用 0.5～0.618）',
        'RSI 背离：在价格的两个低点上读 RSI（kieran-mackle/AutoTrader 的写法）', 'RSI(14) 和布林带(20,2) 用国内软件的通行算法（indicators.py）')
NOTES = ('没有回测过。照录屏的五条要点和「三驱形态」卡片重写，不是原作者的代码。',)

LEARN = dict(
    long=dict(idea_title='“不接飞刀”在看什么？',
              idea='跌的时候去接，像伸手接一把往下掉的刀。这套规则等它连砸三下，每一下都创新低，中间弹两次。砸满三下、第三下没什么劲了，才看能不能接。',
              idea_note='对应录屏「三驱抄底战法」。录屏里面板叫「不接飞刀 v1.3」。',
              list_title='三驱清单', list='三个问题。第三下落在量出来的那一带了吗？价格创了新低，RSI 却没有吗？刺破布林下轨以后，收盘又收回来了吗？三个都“是”，才说条件齐了。',
              plan='止损放在第三下那根长下影的下面：再破新低就认错。第一目标是第二次反弹的高点，第二目标是第一次反弹的高点。',
              none='它要先看到连砸三下的走势。现在没有，所以清单空着。',
              cards=[('g_rsi', 'RSI 是什么？', '它把最近十四根 K 线里涨的力气和跌的力气比一比，变成 0 到 100 的一个数。掉到 30 下面，是跌得很猛。价格创新低、它却没创新低，叫“底背离”。', None, 'chart')]),
    short=dict(idea_title='“不接飞刀”的做空一侧在看什么？',
               idea='把做多那套上下翻过来。它等价格连冲三下，每一下都创新高，中间回落两次。冲满三下、第三下没什么劲了，才看能不能做空。',
               idea_note='做空这一侧录屏里没有讲过，是把同一套规则翻过来用的。',
               list_title='三驱见顶清单', list='三个问题。第三下落在量出来的那一带了吗？价格创了新高，RSI 却没有吗？刺破布林上轨以后，收盘又收回来了吗？',
               plan='止损放在第三下那根长上影的上面。第一目标是第二次回落的低点，第二目标是第一次回落的低点。做空是反着来的：止损在上，目标在下。',
               none='它要先看到连冲三下的走势。现在没有，所以清单空着。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _core(P, j):
    d, l, c = P['d'], P['l'], P['c']
    X = qm.ix(P)
    Lg = qm.long(P)
    W = dict(down='砸' if Lg else '冲', low='低' if Lg else '高', band='下轨' if Lg else '上轨', bounce='反弹' if Lg else '回落', pierce='刺破' if Lg else '涨破',
             rsi_bad=f'RSI 在 30 下面趴着' if Lg else 'RSI 在 70 上面顶着')
    out = qm.blank(verdict_text='这套清单用不上', phase_text='无结构')
    td = pt.three_drives(P, j)
    if td is None:
        out['note'] = f'最近不是“连{W["down"]}三下、每一下都创新{W["low"]}”的走势。'
        out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
        return out
    (d1i, D1), (r1i, R1), (d2i, D2), (r2i, R2), (d3i, D3) = [x[:2] for x in (td['D1'], td['R1'], td['D2'], td['R2'], td['D3'])]
    a = pt.atr(P, j)
    leg2 = R1 - D2
    z_lo, z_hi = R2 - VIDEO['ext_hi'] * leg2, R2 - VIDEO['ext_lo'] * leg2
    k1 = z_lo - EST['tol_atr'] * a <= D3 <= z_hi + EST['tol_atr'] * a and D3 < D2
    rsi = X['rsi']
    rv = lambda x: float(x) if Lg else 100.0 - float(x)       # 显示用真实价格的 RSI（做空一侧内部算的是翻过来的）
    k2 = float(rsi[d3i]) > float(rsi[d2i])
    lowb = X['low']
    ok_band = np.isfinite(lowb[j])
    pierced = ok_band and any(np.isfinite(lowb[t]) and l[t] < lowb[t] for t in range(max(0, j - EST['pierce_n'] + 1), j + 1))
    k3 = bool(ok_band and pierced and c[j] > lowb[j] and rsi[j] >= VIDEO['rsi_floor'])
    width = X['up'] - X['low']
    widening = ok_band and j >= EST['width_n'] and np.isfinite(width[j - EST['width_n']]) and width[j] > width[j - EST['width_n']]
    hug = ok_band and c[j] <= lowb[j] + 0.1 * a and widening
    z_a, z_b = qm.span(P, z_lo, z_hi)
    checks = [qm.check('K1', '第三下落在扩展 0.5～0.618', k1, f'第三下{W["low"]}点 {R(P, D3)}（{d[d3i]}），扩展 0.5～0.618 那一带是 {z_a} ~ {z_b}' +
                       ('，落在里面' if k1 else ('，没创新' + W['low'] if D3 >= D2 else '，没落在里面')), ask='第三下落到位了吗？', yes='第三下到位了', no='第三下还没到位', sticker_yes='砸到位'),
              qm.check('K2', f'价格新{W["low"]} RSI 不新{W["low"]}', k2, f'第二下那天 RSI {rv(rsi[d2i]):.1f}，第三下那天 {rv(rsi[d3i]):.1f}：' + ('RSI 没跟着创新' + W['low'] if k2 else 'RSI 也跟着创新' + W['low']),
                       ask='RSI 背离了吗？', yes='背离了', no='没背离', sticker_yes='没劲了'),
              qm.check('K3', f'收回{W["band"]}', k3, ('布林带还算不出来' if not ok_band else f'今天收盘 {R(P, c[j])}，布林{W["band"]} {R(P, lowb[j])}，RSI {rv(rsi[j]):.1f}：' +
                       ('刺破后收回来了' if k3 else '没刺破' if not pierced else '还没收回来' if c[j] <= lowb[j] else 'RSI 还没回到 30 上面' if Lg else 'RSI 还没回到 70 下面')),
                       ask=f'收回{W["band"]}了吗？', yes=f'收回{W["band"]}了', no=f'还没收回{W["band"]}', sticker_yes='收回来了')]
    shapes = [qm.sh_seg(P, (d1i, D1), (r1i, R1), 'abcd', dash=[6, 4]), qm.sh_seg(P, (r1i, R1), (d2i, D2), 'abcd', dash=[6, 4]),
              qm.sh_seg(P, (d2i, D2), (r2i, R2), 'abcd', dash=[6, 4]), qm.sh_seg(P, (r2i, R2), (d3i, D3), 'abcd', dash=[6, 4]),
              qm.sh_badge(P, d1i, D1, '1', 'push', above=False, key='drive', first=True), qm.sh_badge(P, d2i, D2, '2', 'push', above=False),
              qm.sh_badge(P, d3i, D3, '3', 'push', above=False, soft=td['d3_pending']),
              qm.sh_box(P, r2i, j, z_lo, z_hi, 'zone', '扩展 0.5～0.618', key='ext', alpha=0.10),
              qm.sh_line(P, max(0, j - 79), lowb[max(0, j - 79):j + 1], 'boll', f'布林{W["band"]}', key='boll', w=1.2)]
    legend = [qm.legend_item('drive', f'紫色的 1、2、3 是连着{W["down"]}的三下，每一下都比前一下更{"低" if Lg else "高"}。'),
              qm.legend_item('ext', '浅绿色方框是量出来的第三下落点：第二下长度的 0.5～0.618 倍。'),
              qm.legend_item('boll', f'浅蓝色的线是布林{W["band"]}。刺破它、收盘又回来，是有人{"接" if Lg else "压"}了。')]
    out.update(phase='第三下', phase_text='第三下', list=KEY, checks=checks, shapes=shapes, legend=legend, _ev=d2i, _from=d3i,
               drives=dict(d1=R(P, D1), r1=R(P, R1), d2=R(P, D2), r2=R(P, R2), d3=R(P, D3)), story=f'{d[d1i][5:]}、{d[d2i][5:]}、{d[d3i][5:]} 连{W["down"]}三下')
    if float(rsi[j]) < VIDEO['rsi_floor']:
        out.update(verdict='不抄', verdict_text=f'{W["rsi_bad"]}，不抄' if Lg else f'{W["rsi_bad"]}，不追空', state='avoid', text=f'RSI 现在 {rv(rsi[j]):.1f}，按规则这时候不碰。')
    elif hug:
        out.update(verdict='不抄', verdict_text=f'贴着布林{W["band"]}、口子还在张，' + ('不抄' if Lg else '不追空'), state='avoid', text=f'收盘还贴着布林{W["band"]}，布林带的口子还在张开，按规则不碰。')
    elif k1 and k2 and k3:
        out.update(qm.plan(P, float(c[j]) - EST['zone_atr'] * a, float(c[j]), dn(D3, EST['stop']), R2, R1, f'第一次{W["bounce"]}的{"高" if Lg else "低"}点'))
        out.update(verdict='条件齐', verdict_text='条件齐了（未回测）', state='ready', zone_from=d[d3i],
                   text=f'第三次探{"底" if Lg else "顶"}出现{"底" if Lg else "顶"}背离，收回布林{W["band"]}，三项条件满足。价格进入建仓区，{"跌破" if Lg else "涨破"}止损离场。这套规则没有回测过，这里只是把清单结果摆出来。')
    else:
        n = sum(1 for x in checks if x['ok'])
        out.update(verdict='等', verdict_text=f'清单 {n}/3，等第三下', state='wait', text=f'已经{W["down"]}了三下，清单 {n}/3。还缺：' + '、'.join(x['name'] for x in checks if not x['ok']) + '。')
    out['next_needs'] = [f'第三下要落在 {z_a} ~ {z_b} 一带（前后放宽半个 ATR）', f'收盘{"跌破" if Lg else "涨破"} {R(P, D3)} 再创新{W["low"]}：跌出第四下，形态失效']
    return qm.finish(out)
