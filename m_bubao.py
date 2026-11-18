"""不爆仓 3 号 —— 录屏「满仓走一遍 · 永不爆仓玩法」里面板上的模型。因果，未回测。

面板上那一次（做空 · 中线 60 日）的说明原话：右肩没过 0.5，趋势还在往下。价格进入建仓区，按区间分批，站回右肩上方离场。
录屏讲的「永不爆仓玩法」四条：① 下单前算好最多亏多少 ② 涨了才加 越加越少 ③ 加完止损往上挪 ④ 到目标就卖。还说了一句：这单最多亏 1%。

规则（做空那一侧是头肩顶；下面按做多那一侧的头肩底写，做空时整张图上下翻过来）：
  K1 头肩成形：左肩、头、右肩三个低点，头最低，两肩差不多高。
  K2 右肩没过 0.5：右肩回落没有吃掉“头到颈线那一段”的一半。
  K3 趋势还在往上（做空时就是还在往下）：20 日均线比 5 根之前更高。
三项齐了：建仓区 = 现价上下半个 ATR【估算】；止损 = 右肩外侧 1%【估算】；第一目标 = 颈线 + 头部深度（头肩的量幅）；第二目标 = 颈线 + 1.618 倍深度【估算】。
加仓表照「永不爆仓玩法」：走过到第一目标的三分之一再加，每次加上一份的一半，加完把止损挪到上一份的成本价【估算】。
"""
import qmodel as qm
import patterns as pt
from qmodel import R, up, dn, pct

KEY, VERSION, NAME = 'bubao', 'bubao-r1', '不爆仓 3 号'
KIND, DEFAULT_SIDE = 'trade', 'short'
DEFAULT_HZ = 60          # 录屏面板上这个模型用的周期
MIRRORED = ('long',)
TAGS = ('参数含估算',)
EXTRA = ('pattern', 'rows')
VIDEO = dict(rs_fib=0.5, risk=0.01)
VIDEO_NOTE = dict(rs_fib='右肩不能越过“头到颈线那一段”的多少', risk='一单最多亏账户的多少（只写在加仓表里，面板不知道你的账户）')
EST = dict(zone_atr=0.5, stop=0.01, t2_mult=1.618, ma=20, ma_lag=5, add_step=1 / 3, add_size=0.5)
EST_NOTE = dict(zone_atr='建仓区是现价上下几个 ATR', stop='止损放在右肩外侧多远', t2_mult='第二目标是颈线外几倍头部深度', ma='看趋势用几日均线',
                ma_lag='均线和几根之前比', add_step='走过到第一目标的几分之一再加一次', add_size='每次加上一份的多少')
REFS = ('neurotrader888/TechnicalAnalysisAutomation（head_shoulders.py：目标 = 颈线 ± 头高）',)
NOTES = ('没有回测过。这是照录屏面板上的说明和「永不爆仓玩法」四条重写的，不是原作者的代码。', '加仓表只是算术：面板不知道你的账户，也不会替你交易。')

LEARN = dict(
    long=dict(idea_title='“不爆仓 3 号”在看什么？',
              idea='它找头肩底：中间跌得最深，两边浅一点。右肩没怎么往回跌、均线还在往上，它才说条件齐了。它把加仓的规矩也一起写好：先算最多亏多少，赚了才加，越加越少。',
              idea_note='录屏里用的是做空那一侧（头肩顶）。这一侧是上下翻过来用的。',
              list_title='三项清单', list='三个问题。头肩底成形了吗？右肩往回跌没超过一半吗？均线还在往上吗？三个都“是”，才说条件齐了。',
              plan='建仓区在现价附近。止损放在右肩下面一点。第一目标是颈线再加一个头的深度。下面的加仓表写着：走到哪里才加，加多少，止损挪到哪里。',
              none='它要先看到一个头肩底。现在没有这样的走势，所以清单空着。', cards=[]),
    short=dict(idea_title='“不爆仓 3 号”在看什么？',
               idea='它找头肩顶：中间冲得最高，两边矮一点。右肩反弹没过一半、趋势还在往下，它才说条件齐了。它把加仓的规矩也一起写好：先算最多亏多少，赚了才加，越加越少。',
               idea_note='录屏里面板用的就是这一侧（做空）。',
               list_title='三项清单', list='三个问题。头肩顶成形了吗？右肩反弹没超过一半吗？均线还在往下吗？三个都“是”，才说条件齐了。',
               plan='建仓区在现价附近。止损放在右肩上面一点。第一目标是颈线再往下一个头的高度。做空是反着来的：止损在上，目标在下。',
               none='它要先看到一个头肩顶。现在没有这样的走势，所以清单空着。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _w(P):
    L = qm.long(P)
    return dict(pat='头肩底' if L else '头肩顶', rs_move='回落' if L else '反弹', trend='往上' if L else '往下', side='下面' if L else '上面')


def _core(P, j):
    d, c = P['d'], P['c']
    W = _w(P)
    out = qm.blank(verdict_text='这套清单用不上', phase_text='无结构')
    h = pt.head_shoulders(P, j)
    if h is None or h['rs_pending']:
        out['note'] = f'最近没有成形的{W["pat"]}（左肩、头、右肩三个点，头在最外面，两肩差不多高）。'
        out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
        return out
    (L1i, L1), (H1i, H1), (L2i, L2), (H2i, H2), (L3i, L3) = [x[:2] for x in (h['L1'], h['H1'], h['L2'], h['H2'], h['L3'])]
    neck, depth = h['neck'], h['depth']
    cj = float(c[j])
    half = L2 + VIDEO['rs_fib'] * (H2 - L2)
    k2 = L3 >= half
    ma = qm.ma(P, EST['ma'])
    k3 = j >= EST['ma_lag'] and float(ma[j]) > float(ma[j - EST['ma_lag']]) if ma[j] == ma[j] else False
    rs_pct = round((H2 - L3) / (H2 - L2) * 100) if H2 > L2 else None
    checks = [qm.check('K1', f'{W["pat"]}成形', True, f'左肩 {R(P, L1)}（{d[L1i]}）、头 {R(P, L2)}（{d[L2i]}）、右肩 {R(P, L3)}（{d[L3i]}）；颈线现在在 {R(P, neck(j))}',
                       ask=f'{W["pat"]}成形了吗？', yes=f'{W["pat"]}成形了', no='还没成形', sticker_yes='成形了'),
              qm.check('K2', '右肩没过 0.5', k2, f'右肩{W["rs_move"]}吃掉了“头到颈线那一段”的 {rs_pct}%，' + ('没过一半' if k2 else '过了一半') + f'（0.5 线在 {R(P, half)}）',
                       ask='右肩没过 0.5 吗？', yes='右肩没过 0.5', no='右肩过了 0.5', sticker_yes='没过一半', draw=[dict(type='level', price=R(P, half), label='0.5')]),
              qm.check('K3', f'趋势还在{W["trend"]}', k3, f'MA{EST["ma"]} 现在 {R(P, ma[j])}，{EST["ma_lag"]} 根之前 {R(P, ma[j - EST["ma_lag"]])}，' + (f'还在{W["trend"]}' if k3 else f'不再{W["trend"]}'),
                       ask=f'趋势还在{W["trend"]}吗？', yes=f'还在{W["trend"]}', no='趋势停了', sticker_yes='顺势')]
    shapes = [qm.sh_seg(P, (H1i, H1), (j, neck(j)), 'neck', '颈线', key='neck', w=1.6),
              qm.sh_badge(P, L1i, L1, '左', 'push', above=False, key='hs', first=True), qm.sh_badge(P, L2i, L2, '头', 'push', above=False),
              qm.sh_badge(P, L3i, L3, '右', 'push', above=False), qm.sh_hl(P, L2i, half, 'fib', f'0.5 · {R(P, half)}', key='half', dash=[2, 4], w=1)]
    legend = [qm.legend_item('neck', '橙色斜线是颈线：把两次反弹的高点连起来。' if qm.long(P) else '橙色斜线是颈线：把两次回落的低点连起来。'),
              qm.legend_item('hs', '“左、头、右”三个圆点就是左肩、头、右肩。'),
              qm.legend_item('half', '灰色虚线是 0.5 线：头到颈线那一段的一半。右肩不该越过它。')]
    out.update(phase='右肩之后', phase_text='右肩之后', list=KEY, checks=checks, shapes=shapes, legend=legend, _ev=L2i, _from=L3i,
               pattern=dict(left=R(P, L1), head=R(P, L2), right=R(P, L3), neck=R(P, neck(j)), depth=qm.r2(depth)),
               story=f'{d[L2i][5:]} 是头，{d[L3i][5:]} 是右肩，颈线在 {R(P, neck(j))}')
    t1 = neck(j) + depth
    if all(x['ok'] for x in checks) and cj < t1:
        a = pt.atr(P, j)
        pl = qm.plan(P, cj - EST['zone_atr'] * a, cj + EST['zone_atr'] * a, dn(L3, EST['stop']), t1, neck(j) + EST['t2_mult'] * depth, '颈线外 1.618 倍头部深度【估算】')
        out.update(pl)
        mid, stop = cj, dn(L3, EST['stop'])
        a1, a2 = mid + EST['add_step'] * (t1 - mid), mid + 2 * EST['add_step'] * (t1 - mid)
        out['rows'] = dict(title='加仓表（永不爆仓玩法 · 只是算术）', rows=[
            dict(k='第 1 份', v=R(P, mid), sub=f'止损 {R(P, stop)}。进场前先算好：亏到这里，这一单最多亏账户的 1%'),
            dict(k='第 2 份', v=R(P, a1), sub=f'走到这里才加（涨了才加），量是第 1 份的一半；加完止损挪到 {R(P, mid)}'),
            dict(k='第 3 份', v=R(P, a2), sub=f'再走到这里才加，量是第 2 份的一半；加完止损挪到 {R(P, a1)}'),
            dict(k='全部离场', v=R(P, t1), sub='到第一目标就卖（到目标就卖）')])
        out.update(verdict='条件齐', verdict_text=qm.pick(P, '条件齐了（未回测）', '条件齐了（未回测）'), state='ready', zone_from=d[L3i],
                   text=f'右肩没过 0.5，趋势还在{W["trend"]}。价格进入建仓区，按区间分批，站回右肩{W["side"]}离场。这套规则没有回测过，这里只是把清单结果摆出来。')
    else:
        n = sum(1 for x in checks if x['ok'])
        far = cj >= t1
        out.update(verdict='等' if not far else '不追', verdict_text=f'清单 {n}/3，等' if not far else '已经走到第一目标附近，不追', state='wait' if not far else 'avoid',
                   text=(f'{W["pat"]}已经成形，清单 {n}/3。还缺：' + '、'.join(x['name'] for x in checks if not x['ok']) + '。') if not far else f'价格已经走到第一目标 {R(P, t1)} 附近，这一段不追。')
        out['next_needs'] = ([f'右肩不能越过 {R(P, half)}（0.5 线）'] if not k2 else []) + ([f'MA{EST["ma"]} 要重新{W["trend"]}'] if not k3 else [])
        if k2 and not far:      # 预案（只给 AI 对话）：右肩已经走完，过了 0.5 就不会再条件齐，不给
            a = pt.atr(P, j)
            out['pre'] = qm.preplan(P, cj - EST['zone_atr'] * a, cj + EST['zone_atr'] * a, dn(L3, EST['stop']), t1, neck(j) + EST['t2_mult'] * depth)
    out['next_needs'] = out['next_needs'] + [f'收盘越过右肩 {R(P, L3)}：这个{W["pat"]}作废']
    return qm.finish(out)
