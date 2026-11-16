"""「当前图表」评分表盘（APP_ADDENDUM_QUANT_AI.md §4）。

视频只给了表盘的样子和五个分项的名字，没有给公式。下面的公式全部是【估算】。
它描述图表现状，不是预测，也不是所选规则模型的结论：两者是独立的两套东西。
每项 −100 ~ +100，综合分 = 五项等权平均后四舍五入。只用 ≤ i 的数据。
"""
import math
import numpy as np
import houshou as hs

EST = dict(ma_fast=20, ma_slow=60, mom_n=20, mom_full=0.20, vol_n=20, atr_n=14, atr_ok=0.02, atr_span=0.04)   # 全部【估算】
BANDS = ((-60, '偏空'), (-20, '中性偏空'), (20, '中性'), (60, '中性偏多'))
NOTE = '综合评分 −100 到 +100 ｜ 描述现状，不是预测 ｜ 公式为估算'


def half_up(x):
    return int(math.copysign(math.floor(abs(x) + 0.5), x))


def label(total):
    if total <= -60:
        return '偏空'
    if total < -20:
        return '中性偏空'
    if total <= 20:
        return '中性'
    if total < 60:
        return '中性偏多'
    return '偏多'


def compute(P, i):
    """P = houshou.prepare(B). Returns dict(total, label, parts=[{name, v, why}], note)."""
    c, v = P['c'], P['v']
    n = i + 1
    parts = []
    f, s = EST['ma_fast'], EST['ma_slow']

    # 趋势：收盘在 MA20 上 +50 否则 −50；MA20 在 MA60 上 +50 否则 −50
    if n >= s:
        m20, m60 = float(c[i - f + 1:i + 1].mean()), float(c[i - s + 1:i + 1].mean())
        a, b = c[i] > m20, m20 > m60
        parts.append(dict(name='趋势', v=(50 if a else -50) + (50 if b else -50),
                          why=('收盘站上 MA20' if a else '收盘跌破 MA20') + '，' + ('MA20 高于 MA60' if b else 'MA20 低于 MA60')))
    elif n >= f:
        a = c[i] > float(c[i - f + 1:i + 1].mean())
        parts.append(dict(name='趋势', v=50 if a else -50, why=('收盘站上 MA20' if a else '收盘跌破 MA20') + f'；不足 {s} 根，没有 MA60'))
    else:
        parts.append(dict(name='趋势', v=0, why=f'不足 {f} 根 K 线，算不出均线'))

    # 动量：近 20 根涨跌幅 ÷ 20%，夹在 ±1 之间
    k = EST['mom_n']
    chg = float(c[i] / c[i - k] - 1) if n > k else None
    if chg is None:
        parts.append(dict(name='动量', v=0, why=f'不足 {k + 1} 根 K 线'))
    else:
        parts.append(dict(name='动量', v=half_up(max(-1.0, min(1.0, chg / EST['mom_full'])) * 100), why=f'近 {k} 根涨跌 {chg * 100:+.1f}%'))

    # 量能：近 20 根均量 ÷ 再前 20 根均量；放量跟着涨加分，放量跟着跌扣分
    w = EST['vol_n']
    if n >= 2 * w and chg is not None:
        r = float(v[i - w + 1:i + 1].mean() / v[i - 2 * w + 1:i - w + 1].mean())
        sign = 1 if chg > 0 else -1 if chg < 0 else 0
        parts.append(dict(name='量能', v=half_up(max(-100.0, min(100.0, (r - 1) * 100)) * sign), why=f'近 {w} 根日量为前期的 {r:.2f} 倍'))
    else:
        parts.append(dict(name='量能', v=0, why=f'不足 {2 * w} 根 K 线'))

    # 波动：ATR14 ÷ 收盘，超过 2% 开始扣分，到 6% 扣满；只扣不加
    atr = P['atr'][i]
    if np.isfinite(atr):
        a = float(atr / c[i])
        parts.append(dict(name='波动', v=-half_up(max(0.0, min(1.0, (a - EST['atr_ok']) / EST['atr_span'])) * 100), why=f'ATR {a * 100:.2f}%'))
    else:
        parts.append(dict(name='波动', v=0, why=f'不足 {EST["atr_n"]} 根 K 线'))

    # 结构：最近两组已确认的摆动点。高点、低点都抬高 +100；都降低 −100；其余 0
    conf, _ = hs.swings(P, i)
    hi = [x['price'] for x in conf if x['kind'] == 'high'][-2:]
    lo = [x['price'] for x in conf if x['kind'] == 'low'][-2:]
    if len(hi) == 2 and len(lo) == 2:
        up, dn = hi[1] > hi[0] and lo[1] > lo[0], hi[1] < hi[0] and lo[1] < lo[0]
        parts.append(dict(name='结构', v=100 if up else -100 if dn else 0, why='结构走强' if up else '结构转弱' if dn else '结构不明'))
    else:
        parts.append(dict(name='结构', v=0, why='已确认的摆动点不够两组，结构不明'))

    total = half_up(sum(p['v'] for p in parts) / len(parts))
    return dict(total=total, label=label(total), parts=parts, note=NOTE, est=EST)
