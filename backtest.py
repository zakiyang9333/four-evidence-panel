"""Backtest of 抄底核心四要素 on NVDA / QQQ / SPCX. Primary test = the video's own parameters (one pre-specified test).
Secondary = 162-cell parameter grid chosen in-sample (first 60% of each ticker's bars) and checked out-of-sample, Bonferroni-adjusted.
Control = "跌多了就买": random entries on bars already >= dd below the 250-day high, same stop/target/time exits and costs.
Output: out/backtest.json"""
import json, itertools, os
import numpy as np
import engine as E
ROOT = os.path.dirname(os.path.abspath(__file__)); TICKERS = ('NVDA', 'QQQ', 'SPCX'); SPLIT = 0.6; NSIM = 5000
rng = np.random.default_rng(20261114)

def stats(tr):
    r = np.array([t['r'] for t in tr])
    if len(r) == 0: return dict(n=0)
    streak = mx = 0
    for x in r:
        streak = streak + 1 if x < 0 else 0; mx = max(mx, streak)
    eq = np.cumsum(r); dd = float((np.maximum.accumulate(np.concatenate([[0], eq])) - np.concatenate([[0], eq])).max())
    return dict(n=int(len(r)), win=round(float((r > 0).mean()), 3), mean_r=round(float(r.mean()), 3), median_r=round(float(np.median(r)), 3),
                total_r=round(float(r.sum()), 2), max_losing_streak=int(mx), max_dd_r=round(dd, 2),
                mean_ret=round(float(np.mean([t['ret'] for t in tr])), 4), mean_bars=round(float(np.mean([t['bars'] for t in tr])), 1),
                mean_cost_r=round(float(np.mean([t['cost_r'] for t in tr])), 3))

def boot_ci(r, n=5000):
    if len(r) < 3: return None
    m = [rng.choice(r, len(r)).mean() for _ in range(n)]
    return [round(float(np.percentile(m, 5)), 3), round(float(np.percentile(m, 95)), 3)]

def run(P):
    res = {}
    for t in TICKERS:
        B = E.load(f'{ROOT}/data/{t}.csv'); S = E.compute(B, P); n = len(B['c']); cut = int(n * SPLIT) if n > 600 else n  # SPCX too short to split
        tr = E.signals(B, S)
        pool = {}
        for i in range(min(300, n // 2), n - 1):
            if S['dd_ok'][i]:
                x = E.trade_from(B, S, i)
                if x: pool[i] = x['r']
        res[t] = dict(B=B, S=S, trades=tr, cut=cut, pool=pool)
    return res

def pvalue(res, part):
    """P(mean R of same-count random 'bought the dip' entries >= strategy mean R)."""
    obs = []; pools = []
    for t in TICKERS:
        x = res[t]; sel = (lambda i: i < x['cut']) if part == 'is' else (lambda i: i >= x['cut']) if part == 'oos' else (lambda i: True)
        tr = [q['r'] for q in x['trades'] if sel(q['sig_i'])]; pl = np.array([r for i, r in x['pool'].items() if sel(i)])
        if tr and len(pl): obs += tr; pools.append((len(tr), pl))
    if not obs: return None
    m = np.mean(obs); sims = np.zeros(NSIM)
    for k, pl in pools: sims += rng.choice(pl, (NSIM, k)).sum(axis=1)
    sims /= len(obs)
    return dict(n=len(obs), mean_r=round(float(m), 3), control_mean_r=round(float(sims.mean()), 3),
                p=round(float((sims >= m).mean()), 4), percentile=round(float((sims < m).mean() * 100), 1))

def part_trades(res, part):
    out = []
    for t in TICKERS:
        x = res[t]
        out += [q for q in x['trades'] if (part == 'all') or (part == 'is') == (q['sig_i'] < x['cut'])]
    return sorted(out, key=lambda q: q['sig'])

def buyhold(res):
    out = {}
    for t in TICKERS:
        B = res[t]['B']; tr = res[t]['trades']; yrs = len(B['c']) / 252
        g = float(np.prod([1 + q['ret'] for q in tr])) if tr else 1.0
        out[t] = dict(years=round(yrs, 1), bh_cagr=round(float((B['c'][-1] / B['c'][0]) ** (1 / yrs) - 1), 4),
                      strat_cagr_full_size=round(g ** (1 / yrs) - 1, 4), time_in_market=round(sum(q['bars'] + 1 for q in tr) / len(B['c']), 3),
                      split_date=B['d'][min(res[t]['cut'], len(B['d']) - 1)])
    return out

def main():
    out = dict(asof={}, fixed=E.FIXED, video_params=E.VIDEO)
    res = run(E.VIDEO)
    for t in TICKERS: out['asof'][t] = dict(last=res[t]['B']['d'][-1], bars=len(res[t]['B']['c']), src=res[t]['B']['src'][-1])
    prim = {}
    for part in ('all', 'is', 'oos'):
        tr = part_trades(res, part); s = stats(tr); s['ci90_mean_r'] = boot_ci(np.array([q['r'] for q in tr])); s['vs_random_dip_buying'] = pvalue(res, part)
        prim[part] = s
    prim['by_ticker'] = {t: dict(stats(res[t]['trades']), pool=len(res[t]['pool']),
                                 control_mean_r=round(float(np.mean(list(res[t]['pool'].values()))), 3) if res[t]['pool'] else None) for t in TICKERS}
    prim['trades'] = {t: [{k: v for k, v in q.items() if k not in ('exit_i', 'sig_i')} for q in res[t]['trades']] for t in TICKERS}
    prim['buyhold'] = buyhold(res)
    out['primary'] = prim
    # secondary: grid, selected in-sample
    grid = []
    for n_vol, fan, vm, st, dd in itertools.product((40, 60, 80), (0.382, 0.5, 0.618), (1.2, 1.5, 2.0), (0.02, 0.03, 0.05), (0.10, 0.20)):
        P = dict(n_vol=n_vol, fan=fan, vol_mult=vm, stop=st, dd=dd); r = run(P)
        a, b = part_trades(r, 'is'), part_trades(r, 'oos')
        grid.append(dict(P=P, is_=stats(a), oos=stats(b), p_is=(pvalue(r, 'is') or {}).get('p'), p_oos=(pvalue(r, 'oos') or {}).get('p')))
    ok = [g for g in grid if g['is_']['n'] >= 8]
    best = max(ok, key=lambda g: g['is_']['mean_r']) if ok else None
    out['grid'] = dict(cells=len(grid), cells_with_8_is_trades=len(ok), best_in_sample=best,
                       bonferroni_p_oos=None if not best or best['p_oos'] is None else min(1.0, round(best['p_oos'] * len(grid), 4)),
                       cells_oos_p_lt_05=sum(1 for g in grid if g['p_oos'] is not None and g['p_oos'] < 0.05),
                       cells_oos_tested=sum(1 for g in grid if g['p_oos'] is not None),
                       oos_mean_r_distribution=[round(float(x), 3) for x in np.percentile([g['oos']['mean_r'] for g in grid if g['oos']['n'] >= 5], [0, 25, 50, 75, 100])],
                       all=[dict(g['P'], is_n=g['is_']['n'], is_mean_r=g['is_'].get('mean_r'), oos_n=g['oos']['n'], oos_mean_r=g['oos'].get('mean_r'), p_oos=g['p_oos']) for g in grid])
    json.dump(out, open(f'{ROOT}/out/backtest.json', 'w'), ensure_ascii=False, indent=1)
    g = out['grid']; print(json.dumps({k: v for k, v in prim.items() if k != 'trades'}, ensure_ascii=False, indent=1)); print(json.dumps({k: v for k, v in g.items() if k != 'all'}, ensure_ascii=False, indent=1))

if __name__ == '__main__':
    main()
