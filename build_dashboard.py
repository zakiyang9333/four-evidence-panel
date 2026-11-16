"""Build out/state.json and out/dashboard.html (self-contained, no external scripts) from data/*.csv and out/backtest.json.
Usage: python3 build_dashboard.py"""
import json, os, math
import numpy as np
import engine as E
ROOT = os.path.dirname(os.path.abspath(__file__)); TICKERS = ('SPCX', 'NVDA', 'QQQ'); NBARS = 150
P, F = E.VIDEO, E.FIXED

def f2(x): return None if x is None or not np.isfinite(x) else round(float(x), 2)

def ticker_state(t):
    B = E.load(f'{ROOT}/data/{t}.csv'); S = E.compute(B); n = len(B['c']); i = n - 1
    hi, lo, an = int(S['hi_i'][i]), int(S['low_i'][i]), int(S['anchor'][i]); H, L = S['H'][i], S['L'][i]
    c, v = B['c'][i], B['v'][i]; vmin = B['v'][max(0, i - P['n_vol'] + 1):i + 1].min(); full = n >= P['n_vol']
    hist = S['hist']; trough = hist[hi:lo - F['div_gap'] + 1].min() if lo - hi >= F['div_gap'] + 1 else None
    ev = []
    ev.append(dict(k='E1', name='地量见底', ok=bool(S['e1'][i]),
                   text=(f"{B['d'][an]} 出现地量（下跌 ≥{int(P['dd']*100)}% 后的 {P['n_vol']} 日最小量），成本线从这天起算。" if S['e1'][i] else
                         (f"还没有。今天成交量 {v/1e6:.1f} 百万股，{P['n_vol']} 日最小量 {vmin/1e6:.1f} 百万股，今天比它多 {(v/vmin-1)*100:.0f}%。" if full else f"K线不足 {P['n_vol']} 根，无法判断。")
                         + ("" if S['dd_ok'][i] else f" 另外跌幅还没到 {int(P['dd']*100)}%。"))))
    ev.append(dict(k='E2', name='MACD 底背离', ok=bool(S['e2'][i]),
                   text=(f"最低点 {B['d'][lo]}（{L:.2f}）那天 MACD 柱 {hist[lo]:.2f}，高于此前最深的 {trough:.2f}：价格更低，杀跌力度更小。" if S['e2'][i] else
                         (f"没有。最低点 {B['d'][lo]}（{L:.2f}）那天 MACD 柱 {hist[lo]:.2f}，就是这轮最深（此前最深 {trough:.2f}）：价格和力度一起创新低。" if trough is not None else "高点到低点太近，无法比较。"))))
    fl = S['fanline'][i]
    ev.append(dict(k='E3', name='跌速放缓', ok=bool(S['e3'][i]),
                   text=(f"收盘 {c:.2f} 在扇子中线 {fl:.2f} 上方。" if S['e3'][i] else
                         (f"没有。收盘 {c:.2f}，扇子中线 {fl:.2f}，还差 {(fl/c-1)*100:.1f}%。" if np.isfinite(fl) else "今天就是最低点，扇子还没法画。"))))
    aw = S['avwap'][i]
    ev.append(dict(k='E4', name='站回成本线', ok=bool(S['e4'][i]),
                   text=(f"放量阳线已站回成本线 {aw:.2f}，收盘 {c:.2f} 仍在线上。" if S['e4'][i] else
                         (f"没有。成本线 {aw:.2f}，收盘 {c:.2f}（{'在线上，但低点之后还没出现放量阳线站回' if c > aw else '在线下 ' + format((aw/c-1)*100, '.1f') + '%'}）。" if np.isfinite(aw) else "没有地量日，成本线还没起算。"))))
    score = sum(e['ok'] for e in ev); stale = i - lo
    notes = []
    if not S['dd_ok'][i]: notes.append(f"从 250 日高点到最低点只跌了 {(1-L/H)*100:.0f}%，不到 {int(P['dd']*100)}%，系统不找底。")
    if stale > 40 and S['dd_ok'][i]: notes.append(f"最低点在 {stale} 根K线之前（{B['d'][lo]}），基于它的证据偏旧，扇线已经落到很低的位置，参考价值小。")
    if 'single' in B['src'][i]: notes.append(f"最新一根K线（{B['d'][i]}）只有一个数据源，待第二个来源核对。")
    a = max(0, n - NBARS); idx = range(a, n)
    fans = {}
    if lo > hi:
        for r in (0.382, 0.5, 0.618):
            lvl = L + r * (H - L); fans[str(r)] = [f2(H + (lvl - H) * (j - hi) / (lo - hi)) if j >= max(hi, a) else None for j in idx]
    tp = (B['h'] + B['l'] + B['c']) / 3; avw = [None] * len(idx)
    if an >= 0:
        pv = np.cumsum(tp[an:] * B['v'][an:]); vv = np.cumsum(B['v'][an:])
        avw = [f2(pv[j - an] / vv[j - an]) if j >= an else None for j in idx]
    last_sig = [q for q in E.signals(B, S)][-1:] or [None]
    return dict(ticker=t, asof=B['d'][i], close=f2(c), prev_close=f2(B['c'][i - 1]), score=score, armed=bool(S['dd_ok'][i]), all4=bool(S['all4'][i]),
                high=dict(date=B['d'][hi], price=f2(H)), low=dict(date=B['d'][lo], price=f2(L)), drawdown_close=f2((1 - c / H) * 100),
                drawdown_low=f2((1 - L / H) * 100), stop=f2(S['stop'][i]), target=f2(S['target'][i]), avwap=f2(aw), fan05=f2(fl),
                anchor=B['d'][an] if an >= 0 else None, evidence=ev, notes=notes, src=B['src'][i],
                last_signal=None if not last_sig[0] else {k: last_sig[0][k] for k in ('sig', 'entry', 'stop', 'exit_d', 'why', 'r')},
                chart=dict(d=[B['d'][j] for j in idx], o=[f2(B['o'][j]) for j in idx], h=[f2(B['h'][j]) for j in idx], l=[f2(B['l'][j]) for j in idx],
                           c=[f2(B['c'][j]) for j in idx], v=[int(B['v'][j]) for j in idx], hist=[f2(hist[j]) for j in idx],
                           dif=[f2(S['dif'][j]) for j in idx], dea=[f2(S['dea'][j]) for j in idx], lowvol=[bool(S['low_vol'][j]) for j in idx],
                           fans=fans, avwap=avw, hi=hi - a, lo=lo - a, an=an - a if an >= 0 else None))

def main():
    st = dict(generated=os.popen('date -u +%Y-%m-%dT%H:%MZ').read().strip(), params=P, tickers=[ticker_state(t) for t in TICKERS])
    bt = json.load(open(f'{ROOT}/out/backtest.json')); pr = bt['primary']
    st['backtest'] = dict(all=pr['all'], is_=pr['is'], oos=pr['oos'], by_ticker=pr['by_ticker'], buyhold=pr['buyhold'],
                          grid={k: v for k, v in bt['grid'].items() if k != 'all'}, trades=pr['trades'])
    slim = dict(generated=st['generated'], tickers=[{k: v for k, v in t.items() if k != 'chart'} for t in st['tickers']])
    json.dump(slim, open(f'{ROOT}/out/state.json', 'w'), ensure_ascii=False, indent=1)
    html = open(f'{ROOT}/dashboard_template.html').read().replace('/*__DATA__*/null', json.dumps(st, ensure_ascii=False, separators=(',', ':')))
    open(f'{ROOT}/out/dashboard.html', 'w').write(html)
    for t in slim['tickers']: print(t['ticker'], t['asof'], t['close'], f"{t['score']}/4", [e['ok'] for e in t['evidence']], t['notes'])

if __name__ == '__main__':
    main()
