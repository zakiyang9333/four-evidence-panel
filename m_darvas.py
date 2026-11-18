"""达瓦斯箱形 —— Nicolas Darvas《How I Made $2,000,000 in the Stock Market》（1960）里的箱体法，按公开描述重写。因果，未回测。

公开描述（Bulkowski 的 thepatternsite、ShareScope 教程、therighttrader 等，原书没读到）：
  箱顶：一个 52 周新高之后，接下来 3 根的最高价都没超过它（持平也算超过，要重新数）。
  箱底：箱顶定了以后，之后的一个低点，接下来 3 根的最低价都没跌破它（持平也重新数）。箱顶、箱底都定了，箱子才算成形。
  进场：收盘站上箱顶。离场：收盘跌破箱底。新箱子在更高处形成，止损就跟着抬到新箱底。
  放量：Bulkowski 的写法里没有；therighttrader 要求突破那根的量不低于前 20 根均量，这里照它。
  原版没有目标价，靠一个个往上搬的箱子跟着走。
清单（按做多一侧写；做空时整张图上下翻过来，原书只做多）：
  K1 新高：箱顶是 52 周最高价。
  K2 箱子成形：箱顶之后 3 根没超过，箱底之后 3 根没跌破。
  K3 收盘突破箱顶：最近 3 根【估算】里有一根收盘站上箱顶。
  K4 放量：突破那一根的量不低于前 20 根均量。
四项齐了：建仓区 = 箱顶到它上方半个 ATR【估算】；止损 = 箱底（收盘跌破就离场）；
第一、第二目标 = 止损距离的 2 倍、4 倍【估算】（原版没有目标价）。
"""
import numpy as np

import indicators as ind
import patterns as pt
import qmodel as qm
from qmodel import R

KEY, VERSION, NAME = 'darvas', 'darvas-r1', '达瓦斯箱形'
KIND, DEFAULT_SIDE = 'trade', 'long'
DEFAULT_HZ = 60
MIRRORED = ('short',)          # 原书只做多
TAGS = ('开源规则', '参数含估算')
EXTRA = ('darvas',)
VIDEO, VIDEO_NOTE = {}, {}
SOURCE = dict(confirm=3, look52=252)
SOURCE_NOTE = dict(confirm='箱顶、箱底各要几根不被突破才算定下来', look52='52 周最高价算多少根')
EST = dict(fresh=3, vol=1.0, vol_n=20, chase_atr=1.0, zone_atr=0.5, t1_r=2.0, t2_r=4.0)
EST_NOTE = dict(fresh='突破之后几根以内还算“刚突破”', vol='突破那根的量至少是均量的几倍（照 therighttrader 的写法）', vol_n='均量算多少根',
                chase_atr='离箱顶超过几个 ATR 就算追高', zone_atr='建仓区是箱顶往外几个 ATR', t1_r='第一目标是止损距离的几倍（原版没有目标价）',
                t2_r='第二目标是止损距离的几倍')
REFS = ('Nicolas Darvas《How I Made $2,000,000 in the Stock Market》（1960）：箱体法（原书没读到，照公开描述）',
        'Thomas Bulkowski（thepatternsite.com）：12 个月新高后 3 根更低的高点定箱顶，之后 3 根更高的低点定箱底；收盘突破进场，收盘跌破箱底离场',
        'ShareScope 教程：同样的 3 根规则，新高看 252 根；therighttrader：突破那根的量不低于前 20 根均量')
NOTES = ('没有回测过。照达瓦斯箱体法的公开描述重写，不是原作者的代码。',
         'Bulkowski 自己测过：这套在日线上表现很差，周线上的 ETF 好一些。只当一把尺子用。',
         '原版靠箱子一层层往上搬、止损跟着抬，没有目标价。这里的两个目标是止损距离的倍数【估算】。')

LEARN = dict(
    long=dict(idea_title='“达瓦斯箱形”在看什么？',
              idea='强势股创了一年新高，常会歇一歇，在一个箱子里上下晃。箱顶是之后三天没被超过的新高，箱底是之后三天没被跌破的低点。收盘冲出箱顶，就跟上。',
              idea_note='来自达瓦斯 1960 年的一本书。这里照公开的规则重写。',
              list_title='四项清单', list='四个问题。箱顶是一年里的最高价吗？箱子成形了吗？收盘冲出箱顶了吗？冲出去那一根的量，不比平常少吗？',
              plan='建仓区从箱顶开始，往上半个 ATR。收盘跌破箱底就离场。原版没有目标价，这里按止损距离的两倍、四倍给两个参考位。',
              none='它要先看到一年新高之后成形的箱子。现在没有，所以清单空着。',
              cards=[('g_box', '箱子是怎么定的？', '价格创出一年新高，接着三天都没再超过，这就是箱顶。之后的低点，三天没被跌破，就是箱底。', None, 'chart')]),
    short=dict(idea_title='“达瓦斯箱形”的做空一侧在看什么？',
               idea='把做多那一侧上下翻过来。弱势股跌一段会歇一歇，在箱子里晃。收盘跌穿箱底，就跟着做空。',
               idea_note='原书只做多。这一侧是把规则上下翻过来用的。',
               list_title='四项清单', list='四个问题。箱底是一年里的最低价吗？箱子成形了吗？收盘跌穿箱底了吗？跌出去那一根的量，不比平常少吗？',
               plan='建仓区从箱底开始，往下半个 ATR。收盘涨回箱顶上面就离场。做空是反着来的：止损在上，目标在下。',
               none='它要先看到一年新低之后成形的箱子。现在没有，所以清单空着。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _boxes(P):
    """从头往后走一遍（每一根只用到它和它之前的 K 线），记下每一根收盘时：箱子走到哪一步（0 找箱顶 / 1 找箱底 / 2 成形）、箱顶箱底和它们在哪一根，
    以及收盘突破了哪个成形的箱子。"""
    if 'dv' not in P:
        h, l, c, v = P['h'], P['l'], P['c'], P['v']
        n, K = len(c), SOURCE['confirm']
        st = np.zeros(n, int)
        top, bot = np.full(n, np.nan), np.full(n, np.nan)
        tb, bb = np.full(n, -1), np.full(n, -1)
        bk = dict()                                # 突破那一根 → (箱顶, 箱底, 箱顶那一根, 箱底那一根)
        s, T, ti, cnt, B, bi, bc = 0, -np.inf, -1, 0, np.inf, -1, 0
        for t in range(n):
            if s == 2:
                if c[t] > T:                                  # 收盘突破箱顶：记下这个箱子，从这一根起找下一个箱子
                    bk[t] = (T, B, ti, bi)
                    s, T, ti, cnt = 0, h[t], t, 0
                elif c[t] < B:                                # 收盘跌破箱底：箱子破了，重新找
                    s, T, ti, cnt = 0, h[t], t, 0
            elif s == 0:
                if h[t] >= T:                                 # 持平也算超过：重新数
                    T, ti, cnt = h[t], t, 0
                else:
                    cnt += 1
                    if cnt >= K:                              # 箱顶定了：箱顶之后最低的那一根先当箱底
                        k = ti + 1 + int(np.argmin(l[ti + 1:t + 1]))
                        s, B, bi, bc = 1, l[k], k, t - k
                        if bc >= K:
                            s = 2
            else:
                if h[t] >= T:                                 # 箱底还没定，价格又碰到或超过了箱顶：重新找箱顶
                    s, T, ti, cnt = 0, h[t], t, 0
                elif l[t] <= B:                               # 持平也重新数
                    B, bi, bc = l[t], t, 0
                else:
                    bc += 1
                    if bc >= K:
                        s = 2
            st[t] = s
            top[t], tb[t] = (T, ti) if s >= 1 else (np.nan, -1)
            bot[t], bb[t] = (B, bi) if s >= 1 else (np.nan, -1)
        idx = np.arange(n)
        flag = np.zeros(n, bool)
        flag[list(bk)] = True
        hi52 = ind.rolling_max(h, SOURCE['look52']) if hasattr(ind, 'rolling_max') else None
        P['dv'] = dict(st=st, top=top, bot=bot, tb=tb, bb=bb, bk=bk, last=np.maximum.accumulate(np.where(flag, idx, -1)) if n else idx, hi52=hi52,
                       vma=ind.sma(v, EST['vol_n']))
    return P['dv']


def _core(P, j):
    d, h, l, c, v = P['d'], P['h'], P['l'], P['c'], P['v']
    Lg = qm.long(P)
    D = _boxes(P)
    K = SOURCE['confirm']
    W = dict(top='箱顶' if Lg else '箱底', bot='箱底' if Lg else '箱顶', hi='最高' if Lg else '最低', brk='站上' if Lg else '跌穿', fall='跌回' if Lg else '涨回',
             strong='强势' if Lg else '弱势', chase='追高' if Lg else '追空', under='下方' if Lg else '上方', out='跌破' if Lg else '涨破')
    out = qm.blank(verdict_text='这套清单用不上', phase_text='无结构')
    a, cj = pt.atr(P, j), float(c[j])
    b = int(D['last'][j])
    fresh = b >= 0 and j - b < EST['fresh']
    if fresh:
        T, B, ti, bi = D['bk'][b]
    elif D['st'][j] == 2:
        T, B, ti, bi = float(D['top'][j]), float(D['bot'][j]), int(D['tb'][j]), int(D['bb'][j])
    else:
        out['note'] = '现在没有成形的箱子：' + ('箱顶定了，箱底还在找。' if D['st'][j] == 1 else f'还在找箱顶（一个高点连续 {K} 根没被超过）。')
        out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
        return out
    hi52 = float(D['hi52'][ti]) if D['hi52'] is not None and np.isfinite(D['hi52'][ti]) else float(np.max(h[max(0, ti - SOURCE['look52'] + 1):ti + 1]))
    k1 = T >= hi52 - 1e-9 * max(1.0, abs(hi52))           # 箱顶就是 52 周最高价（新高）
    vm = float(D['vma'][b - 1]) if fresh and b > 0 and np.isfinite(D['vma'][b - 1]) else None
    k3 = fresh
    k4 = fresh and vm is not None and float(v[b]) >= EST['vol'] * vm
    why1 = f'{W["top"]} {R(P, T)}（{d[ti]}），当时的 52 周{W["hi"]}价 {R(P, hi52)}：' + ('箱顶就是 52 周新' + W['hi'][1] if k1 else f'不是新{W["hi"][1]}，差 {abs(hi52 - T) / abs(hi52) * 100:.1f}%')
    why2 = f'{W["top"]} {R(P, T)}（{d[ti]}，之后 {K} 根没超过），{W["bot"]} {R(P, B)}（{d[bi]}，之后 {K} 根没跌破）'
    why3 = (f'{d[b]} 收盘 {R(P, c[b])} {W["brk"]}了{W["top"]} {R(P, T)}' + ('' if b == j else f'，是 {j - b} 根之前')) if fresh else f'收盘还在箱子里，没{W["brk"]}{W["top"]} {R(P, T)}'
    why4 = (f'突破那根成交量 {qm.vol_text(v[b])}，是前 {EST["vol_n"]} 根均量的 {float(v[b]) / vm:.1f} 倍，' + ('不比均量少' if k4 else '比均量少')) if fresh and vm else '还没有突破，谈不上量'
    checks = [qm.check('K1', f'52 周新{W["hi"][1]}', k1, why1, ask=f'{W["top"]}是一年里的{W["hi"]}价吗？', yes=f'是新{W["hi"][1]}', no=f'不是新{W["hi"][1]}', sticker_yes=W['strong']),
              qm.check('K2', '箱子成形', True, why2, ask='箱子成形了吗？', yes='成形了', no='还没成形', sticker_yes='箱子'),
              qm.check('K3', f'收盘突破{W["top"]}', k3, why3, ask=f'收盘{W["brk"]}{W["top"]}了吗？', yes=f'{W["brk"]}了', no='还在箱子里', sticker_yes='出箱'),
              qm.check('K4', '突破不缩量', k4, why4, ask='冲出去那一根的量，不比平常少吗？', yes='量够', no='量少', sticker_yes='有人跟')]
    e = b if fresh else j
    shapes = [qm.sh_box(P, ti, e, B, T, 'zone', '箱子', key='box', alpha=0.10), qm.sh_hl(P, ti, T, 'level', f'{W["top"]} {R(P, T)}', key='top', i2=j, w=1.3),
              qm.sh_hl(P, bi, B, 'stop', f'{W["bot"]} {R(P, B)}', key='bot', i2=j, dash=[4, 4], w=1.2)]
    legend = [qm.legend_item('box', '浅色方框是达瓦斯箱子：价格歇脚时上下晃的范围。'), qm.legend_item('top', f'橙色线是{W["top"]}：收盘{W["brk"]}它就是出箱。'),
              qm.legend_item('bot', f'紫色虚线是{W["bot"]}：收盘{W["out"]}它就离场。')]
    if fresh:
        shapes.append(qm.sh_badge(P, b, float(c[b]), '出', 'level', above=True, key='brk', first=True))
        legend.append(qm.legend_item('brk', f'“出”字是收盘第一次{W["brk"]}{W["top"]}的那一根。'))
    out.update(phase='出箱' if fresh else '箱子里', phase_text='出箱' if fresh else '箱子里', list=KEY, checks=checks, shapes=shapes, legend=legend,
               _ev=ti if fresh else None, _from=b if fresh else None, story=f'{d[ti][5:]} 定{W["top"]} {R(P, T)}，{d[bi][5:]} 定{W["bot"]} {R(P, B)}',
               darvas=dict(top=R(P, T), bottom=R(P, B), top_date=d[ti], bottom_date=d[bi], high52=R(P, hi52), breakout=d[b] if fresh else None))
    args = qm.r_plan(T, T + EST['zone_atr'] * a, B, EST['t1_r'], EST['t2_r'])          # 止损就是箱底：收盘跌破它离场
    t2_note = f'止损距离的 {EST["t2_r"]:g} 倍【估算】'
    exit_line = f'收盘{W["out"]} {R(P, B)}（{W["bot"]}）：离场'
    if not fresh:
        if not k1:
            out.update(verdict='不适用', state='na', verdict_text=f'有箱子，但箱顶不是 52 周新{W["hi"][1]}', note=f'{W["top"]}不是 52 周新{W["hi"][1]}。原版只做刚创新{W["hi"][1]}的{W["strong"]}股。')
            out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
        else:
            n_ok = sum(1 for x in checks if x['ok'])
            out.update(verdict='等', state='wait', verdict_text=f'箱子成形了，清单 {n_ok}/4，等出箱', pre=qm.preplan(P, *args),
                       text=f'创了新{W["hi"][1]}的{W["strong"]}股在箱子里歇脚：{W["top"]} {R(P, T)}，{W["bot"]} {R(P, B)}。收盘{W["brk"]}{W["top"]}、量不比平常少，才算出箱。')
            out['next_needs'] = [f'收盘{W["brk"]} {R(P, T)}（{W["top"]}），成交量不低于前 {EST["vol_n"]} 根均量', exit_line + '（箱子破了）']
    elif not k1:
        out.update(verdict='不追', state='avoid', verdict_text=f'出箱了，但箱顶不是 52 周新{W["hi"][1]}', text=f'收盘{W["brk"]}了{W["top"]}，可是这个箱顶不是 52 周新{W["hi"][1]}。原版只做{W["strong"]}股。')
    elif not k4:
        out.update(verdict='不追', state='avoid', verdict_text='出箱那根的量比平常少，不算', text=f'收盘{W["brk"]}了{W["top"]}，可是那一根的量比前 {EST["vol_n"]} 根均量还少。按这里的写法不算。')
        out['next_needs'] = [exit_line]
    elif abs(cj - T) > EST['chase_atr'] * a:
        out.update(verdict='不追', state='avoid', verdict_text=f'出箱了，但离{W["top"]}太远，不{W["chase"]}', pre=qm.preplan(P, *args),
                   text=f'收盘{W["brk"]}了{W["top"]}，可是现价离{W["top"]}已经 {abs(cj - T) / a:.1f} 个 ATR。按这里的写法不追，等它回到{W["top"]}附近。')
        out['next_needs'] = [f'回到 {R(P, T + EST["chase_atr"] * a)} 以内才不算追', exit_line]
    else:
        out.update(qm.plan(P, *args, t2_note))
        out.update(verdict='条件齐', state='ready', verdict_text='条件齐了（未回测）', zone_from=d[b],
                   text=f'52 周新{W["hi"][1]}之后的箱子，收盘{W["brk"]}了{W["top"]}，量不比平常少，四项都成立。这套规则没有回测过，这里只是把清单结果摆出来。')
        out['next_needs'] = [exit_line, '新箱子在更高处形成以后，原版把止损抬到新箱底']
    return qm.finish(out)
