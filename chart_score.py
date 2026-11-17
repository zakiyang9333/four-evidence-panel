"""「当前图表」评分表盘（APP_ADDENDUM_QUANT_AI.md §4）。

录屏没有讲公式。2026-11-17 那一批录屏的面板上能读到几组「数值 + 依据」，从这些数反推出四个分项的算法（总分怎么合成反推不出来，仍按五项平均【估算】）：
  量能 = (近 20 根上涨日成交量合计 ÷ 下跌日成交量合计 − 1) × 60：0.62 倍 → −23，0.78 倍 → −13，0.80 倍 → −12，3.43 倍 → +100（封顶）。
  波动 = −20 × (ATR% − 2)，只扣不加：ATR 3.33% → −27，4.95% → −59，5.39% → −68，6.06% → −81。
  动量 = 近 20 根涨跌幅（%）× 6：−14.0% → −84，+44.2% → +100（封顶）。
  结构 = 高点、低点都抬高 +40，都降低 −40，其余 0（面板上「高点抬高、低点抬高」是 +40）。
  趋势 = 收盘在 MA20 上方 +50 / 跌破 −50，MA20 高于 MA60 +50 / 低于 −50（录屏里 −100 那一次对得上）。
它描述图表现状，不是预测，也不是所选规则模型的结论：两者是独立的两套东西。
每项 −100 ~ +100，综合分 = 五项等权平均后四舍五入。只用 ≤ i 的数据。
周期（短线 20 / 中线 60 / 长线 120 根）决定回看多远：均线用 N 和 3N，动量和量能看最近 N 根；选 20 时和原来的算法逐位相同。
"""
import math
import numpy as np
import houshou as hs

EST = dict(ma_fast=20, ma_slow=60, mom_n=20, mom_k=6.0, vol_n=20, vol_k=60.0, atr_n=14, atr_ok=0.02, atr_k=20.0, struct=40)   # 从录屏面板上的数反推
BANDS = ((-60, '偏空'), (-20, '中性偏空'), (20, '中性'), (60, '中性偏多'))
NOTE = '综合评分 −100 到 +100 ｜ 描述现状，不是预测 ｜ 分项公式从录屏反推，总分合成为估算'


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


def params(n=20):
    """The look-backs for one horizon. n=20 gives EST unchanged."""
    if n == EST['mom_n']:
        return EST
    return dict(EST, ma_fast=n, ma_slow=3 * n, mom_n=n, vol_n=n, mom_k=round(EST['mom_k'] * math.sqrt(EST['mom_n'] / n), 4))


def compute(P, i, n_bars=20):
    """P = houshou.prepare(B), long side. Returns dict(total, label, parts=[{name, v, why}], note)."""
    EST = params(n_bars)
    c, v = P['c'], P['v']
    n = i + 1
    parts = []
    f, s = EST['ma_fast'], EST['ma_slow']

    # 趋势：收盘在 MA20 上 +50 否则 −50；MA20 在 MA60 上 +50 否则 −50
    if n >= s:
        m20, m60 = float(c[i - f + 1:i + 1].mean()), float(c[i - s + 1:i + 1].mean())
        a, b = c[i] > m20, m20 > m60
        parts.append(dict(name='趋势', v=(50 if a else -50) + (50 if b else -50),
                          why=(f'收盘在 MA{f} 上方' if a else f'收盘跌破 MA{f}') + '，' + (f'MA{f} 高于 MA{s}' if b else f'MA{f} 低于 MA{s}')))
    elif n >= f:
        a = c[i] > float(c[i - f + 1:i + 1].mean())
        parts.append(dict(name='趋势', v=50 if a else -50, why=(f'收盘在 MA{f} 上方' if a else f'收盘跌破 MA{f}') + f'；不足 {s} 根，没有 MA{s}'))
    else:
        parts.append(dict(name='趋势', v=0, why=f'不足 {f} 根 K 线，算不出均线'))

    # 动量：近 20 根涨跌幅 ÷ 20%，夹在 ±1 之间
    k = EST['mom_n']
    chg = float(c[i] / c[i - k] - 1) if n > k else None
    if chg is None:
        parts.append(dict(name='动量', v=0, why=f'不足 {k + 1} 根 K 线'))
    else:
        parts.append(dict(name='动量', v=half_up(max(-100.0, min(100.0, chg * 100 * EST['mom_k']))), why=f'近 {k} 根涨跌 {chg * 100:+.1f}%'))

    # 量能：近 N 根里上涨日的成交量合计 ÷ 下跌日的成交量合计（涨跌按收盘和前一根收盘比）
    w = EST['vol_n']
    if n > w:
        cc, vv = c[i - w:i + 1], v[i - w + 1:i + 1]
        upd = cc[1:] > cc[:-1]
        dnd = cc[1:] < cc[:-1]
        uv, dv = float(vv[upd].sum()), float(vv[dnd].sum())
        if dv > 0:
            r = uv / dv
            parts.append(dict(name='量能', v=half_up(max(-100.0, min(100.0, (r - 1) * EST['vol_k']))), why=f'近 {w} 根涨日量为跌日的 {r:.2f} 倍'))
        else:
            parts.append(dict(name='量能', v=100 if uv > 0 else 0, why=f'近 {w} 根没有下跌日'))
    else:
        parts.append(dict(name='量能', v=0, why=f'不足 {w + 1} 根 K 线'))

    # 波动：ATR14 ÷ 收盘，超过 2% 开始扣分，到 6% 扣满；只扣不加
    atr = P['atr'][i]
    if np.isfinite(atr):
        a = float(atr / c[i])
        parts.append(dict(name='波动', v=-half_up(max(0.0, min(100.0, (a - EST['atr_ok']) * 100 * EST['atr_k']))), why=f'ATR {a * 100:.2f}%'))
    else:
        parts.append(dict(name='波动', v=0, why=f'不足 {EST["atr_n"]} 根 K 线'))

    # 结构：最近两组已确认的摆动点。高点、低点都抬高 +100；都降低 −100；其余 0
    conf, _ = hs.swings(P, i)
    hi = [x['price'] for x in conf if x['kind'] == 'high'][-2:]
    lo = [x['price'] for x in conf if x['kind'] == 'low'][-2:]
    if len(hi) == 2 and len(lo) == 2:
        up, dn = hi[1] > hi[0] and lo[1] > lo[0], hi[1] < hi[0] and lo[1] < lo[0]
        parts.append(dict(name='结构', v=EST['struct'] if up else -EST['struct'] if dn else 0, why='高点抬高、低点抬高' if up else '高点降低、低点降低' if dn else '结构不明'))
    else:
        parts.append(dict(name='结构', v=0, why='已确认的摆动点不够两组，结构不明'))

    total = half_up(sum(p['v'] for p in parts) / len(parts))
    return dict(total=total, label=label(total), parts=parts, note=NOTE, est=EST, n=n_bars)
