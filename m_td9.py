"""神奇九转 —— DeMark 的 TD 序列里“九转”那一段（TD Setup），按公开描述重写。因果，未回测。

公开规则（Thomas DeMark《The New Science of Technical Analysis》，Jason Perl《DeMark Indicators》；国内叫“神奇九转”“低九”“高九”）：
  九转（做多一侧叫低九）：先有一次“价格翻转”（某根收盘比 4 根之前高），接着连续 9 根，每根收盘都比 4 根之前的收盘低。
  完善：第 8 或第 9 根的最低价，不高于第 6、第 7 根的最低价（当时没完善，之后哪一根的最低价做到了也算）。
  风险线：九根里最低的那一根，最低价再减去那一根的真实波幅。
  TDST：九根里最高的最高价。价格回到这里，这一段跌势就算走完了。
清单（按做多一侧写；做空时整张图上下翻过来，原版本来就有“高九”）：
  K1 数到 9：最近 3 根【估算】里刚数到第 9 根。
  K2 完善：第 8、9 根（或之后某一根）的最低价不高于第 6、7 根的最低价。
  K3 没破风险线：数到 9 以后，收盘没跌破风险线。
三项齐了：建仓区 = 现价往下半个 ATR【估算】；止损 = 风险线；第一目标 = TDST；不设第二目标。
"""
import numpy as np

import patterns as pt
import qmodel as qm
from qmodel import R

KEY, VERSION, NAME = 'td9', 'td9-r1', '神奇九转'
KIND, DEFAULT_SIDE = 'trade', 'long'
DEFAULT_HZ = 20
MIRRORED = ()                     # 低九、高九都是原版的规则
TAGS = ('开源规则', '参数含估算')
EXTRA = ('td9',)
VIDEO, VIDEO_NOTE = {}, {}
SOURCE = dict(count=9, look=4)
SOURCE_NOTE = dict(count='连续数几根', look='每根和几根之前的收盘比')
EST = dict(fresh=3, near=7, zone_atr=0.5)
EST_NOTE = dict(fresh='数到 9 之后几根以内还算“刚数到”', near='数到几就算“快到 9 了”', zone_atr='建仓区是现价往下几个 ATR')
REFS = ('Thomas DeMark《The New Science of Technical Analysis》（1994）：TD Setup、完善、TDST',
        'Jason Perl《DeMark Indicators》（Bloomberg Press，2008）：风险线 = 九根里最低价减去那一根的真实波幅',
        '国内看盘软件里的“神奇九转”：只数九转这一段，不数后面的 13')
NOTES = ('没有回测过。照 DeMark 九转的公开描述重写，不是原作者的代码。', '九转是逆着趋势找转折的：跌势很猛时，数到 9 之后还可能接着跌。',
         '公开资料里只有卖指标的人做的回测，没找到独立检验过的结果。')

LEARN = dict(
    long=dict(idea_title='“神奇九转”在看什么？',
              idea='它一根一根地数：今天的收盘，比四根之前的低吗？连着九根都低，说明跌了很久，卖的人可能快卖光了。这时候它提醒你留意转折。',
              idea_note='来自 DeMark 的 TD 序列，国内叫“低九”。这里照公开的规则重写。',
              list_title='三项清单', list='三个问题。刚数到第九根了吗？第八、第九根的最低价，压到第六、第七根下面了吗？数完以后，收盘没跌破风险线吗？',
              plan='建仓区在现价往下半个 ATR。止损放在风险线：九根里最低价再往下一点。目标是 TDST：九根里的最高价。',
              none='它要先数到七、八、九。现在连着往下的根数还不够，所以清单空着。',
              cards=[('g_td', '“比四根之前低”是什么意思？', '拿今天的收盘，和往前数第四根的收盘比。今天更低，就数一。明天还更低，就数二。中间断一次，就从头数。', None, 'chart')]),
    short=dict(idea_title='“神奇九转”的做空一侧在看什么？',
               idea='它一根一根地数：今天的收盘，比四根之前的高吗？连着九根都高，说明涨了很久，追的人可能快追不动了。这时候它提醒你留意转折。',
               idea_note='国内叫“高九”。原版本来就有这一侧。',
               list_title='三项清单', list='三个问题。刚数到第九根了吗？第八、第九根的最高价，冲过第六、第七根了吗？数完以后，收盘没涨破风险线吗？',
               plan='建仓区在现价往上半个 ATR。止损放在风险线：九根里最高价再往上一点。目标是 TDST：九根里的最低价。做空是反着来的：止损在上，目标在下。',
               none='它要先数到七、八、九。现在连着往上的根数还不够，所以清单空着。', cards=[]))


def core(P, j):
    return qm.memo(P, KEY, j, lambda: _core(P, j))


def _arrays(P):
    """整段数一次（每个值只用到它之前的 K 线）：每根的九转计数、到每一根为止最近一次数到 9 的位置、每根的真实波幅。"""
    if 'td9' not in P:
        h, l, c = P['h'], P['l'], P['c']
        n, k = len(c), SOURCE['look']
        cnt = np.zeros(n, int)
        for t in range(k + 1, n):
            if c[t] < c[t - k]:
                cnt[t] = cnt[t - 1] + 1 if cnt[t - 1] > 0 else (1 if c[t - 1] > c[t - 1 - k] else 0)     # 第一根之前要先有一次价格翻转
        idx = np.arange(n)
        pc = np.concatenate((c[:1], c[:-1]))
        P['td9'] = dict(cnt=cnt, last9=np.maximum.accumulate(np.where(cnt == SOURCE['count'], idx, -1)) if n else idx,
                        tr=np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc))))
    return P['td9']


def _core(P, j):
    d, h, l, c = P['d'], P['h'], P['l'], P['c']
    T = _arrays(P)
    Lg = qm.long(P)
    W = dict(nine='低九' if Lg else '高九', lower='低' if Lg else '高', low='最低' if Lg else '最高', high='最高' if Lg else '最低', fall='跌破' if Lg else '涨破',
             press='压到' if Lg else '冲过', under='下面' if Lg else '上面')
    out = qm.blank(verdict_text='这套清单用不上', phase_text='无结构')
    n9, k = SOURCE['count'], SOURCE['look']
    cj, a = float(c[j]), pt.atr(P, j)
    s9 = int(T['last9'][j])
    if s9 >= 0 and j - s9 < EST['fresh']:
        bars = list(range(s9 - n9 + 1, s9 + 1))
        lowk = min(bars, key=lambda t: l[t])                    # 九根里最低的那一根
        risk = float(l[lowk] - T['tr'][lowk])
        tdst = float(max(h[t] for t in bars))
        need = min(float(l[s9 - 3]), float(l[s9 - 2]))           # 第 6、7 根的最低价
        pb = next((t for t in range(s9 - 1, j + 1) if l[t] <= need), None)
        k1, k2 = True, pb is not None
        k3 = all(c[t] >= risk for t in range(s9, j + 1))
        why1 = f'{d[s9]} 数到第 9 根：连续 9 根收盘都比 4 根之前{W["lower"]}' + ('' if s9 == j else f'，是 {j - s9} 根之前')
        why2 = (f'第 6、7 根的{W["low"]}价 {R(P, need)}；' + (f'{d[pb]} 的{W["low"]}价 {R(P, l[pb])} {W["press"]}了它' if k2 else f'第 8、9 根都没{W["press"]}它，还没完善'))
        why3 = f'风险线 {R(P, risk)}（九根里{W["low"]}价 {R(P, l[lowk])}，再加上那一根的真实波幅）；收盘 {R(P, cj)}' + ('，没破' if k3 else '，已经破了')
        checks = [qm.check('K1', '数到 9', k1, why1, ask='刚数到第 9 根了吗？', yes='数到 9 了', no='还没数到 9', sticker_yes=W['nine']),
                  qm.check('K2', '完善', k2, why2, ask=f'第 8、9 根{W["press"]}第 6、7 根了吗？', yes='完善了', no='还没完善', sticker_yes='完善'),
                  qm.check('K3', f'没{W["fall"]}风险线', k3, why3, ask=f'数完以后没{W["fall"]}风险线吗？', yes='没破', no='破了', sticker_yes='还算数', sticker_no='作废')]
        shapes = [qm.sh_text(P, t, float(l[t]), str(t - bars[0] + 1), 'push', above=False, key='count' if t == bars[0] else None) for t in bars]
        shapes += [qm.sh_hl(P, bars[0], tdst, 'target', f'TDST {R(P, tdst)}', key='tdst', dash=[3, 4]), qm.sh_hl(P, lowk, risk, 'stop', f'风险线 {R(P, risk)}', key='risk', dash=[4, 4])]
        legend = [qm.legend_item('count', f'紫色数字是九转的计数：每根收盘都比 4 根之前{W["lower"]}，连着数到 9。'),
                  qm.legend_item('tdst', f'粉色虚线是 TDST：九根里的{W["high"]}价。回到这里，这一段就算走完了。'),
                  qm.legend_item('risk', f'紫色虚线是风险线：九根里{W["low"]}价再往外一根真实波幅。收盘{W["fall"]}它，这一组九转作废。')]
        out.update(phase='数到 9', phase_text='数到 9', list=KEY, checks=checks, shapes=shapes, legend=legend, _ev=s9, _from=s9,
                   td9=dict(nine_date=d[s9], tdst=R(P, tdst), risk=R(P, risk), perfected=d[pb] if k2 else None), story=f'{d[bars[0]][5:]} 到 {d[s9][5:]} 数满九根')
        args = (cj - EST['zone_atr'] * a, cj, risk, tdst)
        if not k3:
            out.update(verdict='已失效', verdict_text=f'{W["fall"]}了风险线，这一组九转作废', state='dead',
                       text=f'数到 9 以后，收盘{W["fall"]}了风险线 {R(P, risk)}。这一组九转作废。')
        elif tdst <= cj:
            out.update(verdict='不追', verdict_text='已经回到 TDST，不追', state='avoid', text=f'价格已经回到 TDST {R(P, tdst)}，这一段转折走完了，不追。')
        elif k2:
            out.update(qm.plan(P, *args, t2_none='九转只看到 TDST，不设第二目标'))
            out.update(verdict='条件齐', verdict_text=f'{W["nine"]}完善（未回测）', state='ready', zone_from=d[s9],
                       text=f'连续 9 根收盘都比 4 根之前{W["lower"]}，第 8、9 根完善，收盘没破风险线，三项都成立。这套规则没有回测过，这里只是把清单结果摆出来。')
        else:
            out.update(verdict='等', verdict_text='数到 9 了，等完善', state='wait', pre=qm.preplan(P, *args),
                       text=f'已经数到 9，但第 8、9 根的{W["low"]}价还没{W["press"]}第 6、7 根。之后哪一根做到了也算完善。')
        out['next_needs'] = ([] if k2 else [f'哪一根的{W["low"]}价{W["press"]} {R(P, need)}（第 6、7 根的{W["low"]}价）就算完善']) + \
            [f'收盘{W["fall"]} {R(P, risk)}（风险线）：这一组九转作废', f'回到 {R(P, tdst)}（TDST）：这一段走完']
        return qm.finish(out)
    m = int(T['cnt'][j])
    if m >= EST['near']:
        bars = list(range(j - m + 1, j + 1))
        shapes = [qm.sh_text(P, t, float(l[t]), str(t - bars[0] + 1), 'push', above=False, key='count' if t == bars[0] else None) for t in bars]
        checks = [qm.check('K1', '数到 9', False, f'已经连续 {m} 根收盘比 4 根之前{W["lower"]}，还差 {n9 - m} 根', ask='刚数到第 9 根了吗？', yes='数到 9 了', no=f'才数到 {m}',
                           sticker_yes=W['nine'])]
        out.update(phase=f'数到 {m}', phase_text=f'数到 {m}', list=KEY, checks=checks, shapes=shapes, verdict='等', verdict_text=f'数到 {m}，等第 9 根', state='wait',
                   legend=[qm.legend_item('count', f'紫色数字是九转的计数：每根收盘都比 4 根之前{W["lower"]}，连着数到 9。')],
                   text=f'已经连续 {m} 根收盘比 4 根之前{W["lower"]}。再数 {n9 - m} 根到 9，才看完善和风险线。',
                   next_needs=[f'再有 {n9 - m} 根收盘比 4 根之前{W["lower"]}，就数到 9', '中间断一根就从头数'])
        return qm.finish(out)
    out['note'] = f'现在连续往{"下" if Lg else "上"}的根数是 {m}，离 9 还远。'
    out['text'] = out['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
    return out
