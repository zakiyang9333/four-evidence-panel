"""技术指标：录屏里那套图表软件用到的几样工具，给图上的副图和各个规则模型共用。

全部因果：第 i 根的值只用 ≤ i 的数据。这里只有算术，没有规则；规则在各个模型文件里。
算法取国内软件的通行写法（红涨绿跌那一套）：
- RSI(14)、KDJ(9,3,3) 用 SMA(X, N, 1) 递推平滑（和威尔德平滑是一回事），种子取第一根的值。
- 布林带 BOLL(20,2)：中轨 = 20 根均价，上下轨 = 中轨 ± 2 × 标准差（总体标准差）。
- ATR(14)：真实波幅的 14 根简单平均，和 houshou.prepare() 里的那一份是同一个算法（模型的门槛用的就是它，不能两处不一样）。
- 成交量分布（录屏里叫「固定范围成交量分布」，口语叫“量山”）：把每根 K 线的成交量按它的最高最低价摊平到价格格子里。
- 回归趋势：一段收盘价的最小二乘直线，上下各 2 个残差标准差。
- 斐波那契回撤 / 扩展：纯比例换算。
"""
import numpy as np

RSI_N, KDJ_N, KDJ_M1, KDJ_M2, BOLL_N, BOLL_K, ATR_N = 14, 9, 3, 3, 20, 2.0, 14
FIB_RET = (0.236, 0.382, 0.5, 0.618, 0.786)
FIB_EXT = (0.618, 1.0, 1.272, 1.618)


def _a(x):
    return np.asarray(x, dtype=float)


def sma(x, n):
    """Simple moving average; NaN until n bars exist."""
    x = _a(x)
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        cs = np.concatenate(([0.0], np.cumsum(x)))
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def smooth(x, n, m=1):
    """国内软件的 SMA(X, N, M)：Y = (M·X + (N−M)·Y') / N，种子是第一根。"""
    x = _a(x)
    out = np.empty(len(x))
    y = x[0] if len(x) else 0.0
    for i, v in enumerate(x):
        y = (m * v + (n - m) * y) / n if i else v
        out[i] = y
    return out


def rolling_std(x, n):
    """Population standard deviation over the last n bars; NaN until n bars exist."""
    x = _a(x)
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        c1 = np.concatenate(([0.0], np.cumsum(x)))
        c2 = np.concatenate(([0.0], np.cumsum(x * x)))
        m = (c1[n:] - c1[:-n]) / n
        out[n - 1:] = np.sqrt(np.maximum((c2[n:] - c2[:-n]) / n - m * m, 0.0))
    return out


def rolling_max(x, n):
    x = _a(x)
    return np.array([x[max(0, i - n + 1):i + 1].max() for i in range(len(x))]) if len(x) else x


def rolling_min(x, n):
    x = _a(x)
    return np.array([x[max(0, i - n + 1):i + 1].min() for i in range(len(x))]) if len(x) else x


def rsi(c, n=RSI_N):
    """0–100。第一根没有涨跌，记 50。"""
    c = _a(c)
    if len(c) < 2:
        return np.full(len(c), 50.0)
    d = np.diff(c)
    up, ab = smooth(np.maximum(d, 0.0), n), smooth(np.abs(d), n)
    r = np.where(ab > 0, up / np.where(ab > 0, ab, 1) * 100, 50.0)
    return np.concatenate(([50.0], r))


def kdj(h, l, c, n=KDJ_N, m1=KDJ_M1, m2=KDJ_M2):
    h, l, c = _a(h), _a(l), _a(c)
    hh, ll = rolling_max(h, n), rolling_min(l, n)
    rng = hh - ll
    rsv = np.where(rng > 0, (c - ll) / np.where(rng > 0, rng, 1) * 100, 50.0)
    k = smooth(rsv, m1)
    d = smooth(k, m2)
    return k, d, 3 * k - 2 * d


def boll(c, n=BOLL_N, k=BOLL_K):
    mid, sd = sma(c, n), rolling_std(c, n)
    return mid, mid + k * sd, mid - k * sd


def atr(h, l, c, n=ATR_N):
    h, l, c = _a(h), _a(l), _a(c)
    out = np.full(len(c), np.nan)
    if len(c):
        pc = np.concatenate(([c[0]], c[:-1]))
        tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
        out = sma(tr, n)
    return out


def volume_profile(h, l, v, a, b, bins=24):
    """Volume by price over bars a..b (inclusive): each bar's volume spread evenly between its low and high.
    Returns dict(lo, hi, step, vol=[...bins], poc=price of the fullest bin, poc_share=its share of the volume)."""
    h, l, v = _a(h)[a:b + 1], _a(l)[a:b + 1], _a(v)[a:b + 1]
    lo, hi = float(l.min()), float(h.max())
    if not hi > lo:
        return dict(lo=lo, hi=hi, step=0.0, vol=[float(v.sum())], poc=lo, poc_share=1.0)
    step = (hi - lo) / bins
    out = np.zeros(bins)
    for x, y, w in zip(l, h, v):
        if y <= x:
            out[min(bins - 1, int((x - lo) / step))] += w
            continue
        i0, i1 = int((x - lo) / step), min(bins - 1, int((y - lo) / step))
        for k in range(i0, i1 + 1):
            seg = min(y, lo + (k + 1) * step) - max(x, lo + k * step)
            if seg > 0:
                out[k] += w * seg / (y - x)
    k = int(out.argmax())
    tot = float(out.sum())
    return dict(lo=lo, hi=hi, step=step, vol=[float(x) for x in out], poc=lo + (k + 0.5) * step, poc_share=float(out[k] / tot) if tot else 0.0)


def linreg_channel(c, a, b, k=2.0):
    """Least-squares line through closes a..b and the spread of the closes around it.
    Returns dict(slope per bar, start, end (line values at a and b), sd (std of residuals), k)."""
    y = _a(c)[a:b + 1]
    n = len(y)
    if n < 2:
        v = float(y[0]) if n else 0.0
        return dict(slope=0.0, start=v, end=v, sd=0.0, k=k)
    x = np.arange(n, dtype=float)
    slope, icpt = np.polyfit(x, y, 1)
    res = y - (slope * x + icpt)
    return dict(slope=float(slope), start=float(icpt), end=float(icpt + slope * (n - 1)), sd=float(np.sqrt((res * res).mean())), k=k)


def fib_retrace(start, end, r):
    """The price that gives back fraction r of the move start → end (works for up and down moves)."""
    return end - r * (end - start)


def fib_extend(a, b, c, r):
    """Three-point extension: from C, project r times the move A → B."""
    return c + r * (b - a)
