"""四证检查 (抄底核心四要素) for limit-price answers. Shared by all threads (zaki 11-14).
Usage:
  python3 -I four_evidence_check.py SPCX NVDA QQQ [--refresh] [--bar TICKER,DATE,O,H,L,C,V] [--json]
  --refresh  rebuild data/*.csv first (prep_data.py: project history + GitHub mirrors)
  --bar      add/replace one latest bar (e.g. a verified App/screenshot close) before computing; repeatable
QQQI has no usable history here: it is read through QQQ (same index, covered-call ETF), labelled 代理.
Output: the block to paste into a 挂单 answer, plus thresholds for the next close. Rules = engine.py v1.0 (frozen)."""
import sys, os, json, subprocess
import numpy as np
ROOT = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, ROOT)
import engine as E
P, F = E.VIDEO, E.FIXED
VERDICT = '回测：证据不足（26 笔，0.435R vs 随机抄底 0.165R，p=0.17），未验证，仅作过滤和价位参考。'

def add_bar(B, spec):
    d, o, h, l, c, v = spec
    vals = dict(o=float(o), h=float(h), l=float(l), c=float(c), v=float(v))
    if B['d'][-1] == d:
        for k, x in vals.items(): B[k][-1] = x
        B['src'][-1] = 'manual'
    elif d > B['d'][-1]:
        B['d'].append(d); B['src'].append('manual')
        for k, x in vals.items(): B[k] = np.append(B[k], x)
    return B

def check(t, bars=()):
    src_t = 'QQQ' if t == 'QQQI' else t
    B = E.load(f'{ROOT}/data/{src_t}.csv')
    for b in bars:
        if b[0] == t or (t == 'QQQI' and b[0] == 'QQQ'): B = add_bar(B, b[1:])
    S = E.compute(B); n = len(B['c']); i = n - 1
    hi, lo, an = int(S['hi_i'][i]), int(S['low_i'][i]), int(S['anchor'][i]); H, L = float(S['H'][i]), float(S['L'][i]); c = float(B['c'][i])
    ev = {k: bool(S[k][i]) for k in ('e1', 'e2', 'e3', 'e4')}; score = sum(ev.values()); armed = bool(S['dd_ok'][i])
    # thresholds for the next close
    vmin59 = float(B['v'][n - P['n_vol'] + 1:].min()) if n >= P['n_vol'] else None
    fan_next = float(H + (L + P['fan'] * (H - L) - H) * (i + 1 - hi) / (lo - hi)) if lo > hi else None
    aw = float(S['avwap'][i]) if np.isfinite(S['avwap'][i]) else None
    trough = float(S['hist'][hi:lo - F['div_gap'] + 1].min()) if lo - hi >= F['div_gap'] + 1 else None
    stop = float(S['stop'][i]); tgt = float(S['target'][i]) if np.isfinite(S['target'][i]) else None
    names = {'e1': '地量见底', 'e2': 'MACD 底背离', 'e3': '跌速放缓', 'e4': '站回成本线'}
    if not armed: state = f'未触发（高点 {H:.2f} 到低点 {L:.2f} 只跌 {(1-L/H)*100:.0f}%，不到 {int(P["dd"]*100)}%）'
    elif score == 4: state = '4/4 四项齐了'
    else: state = f'{score}/4，缺：' + '、'.join(names[k] for k in ev if not ev[k])
    nxt = []
    if armed:
        if not ev['e1'] and vmin59: nxt.append(f'证据1：下一根成交量 ≤ {vmin59/1e6:.1f} 百万股才算地量')
        if not ev['e2']: nxt.append(f'证据2：需再创新低（< {L:.2f}）且当天 MACD 柱高于 {S["hist"][lo]:.2f}' if trough is not None and S['hist'][lo] <= trough else f'证据2：需再创新低（< {L:.2f}）且 MACD 柱不创新低')
        if not ev['e3'] and fan_next: nxt.append(f'证据3：下一根收盘 > {fan_next:.2f}（扇子中线，每天下移约 {abs((L + P["fan"]*(H-L) - H)/(lo-hi)):.2f}）')
        if not ev['e4']: nxt.append(f'证据4：放量阳线收盘 > 成本线 {aw:.2f}' if aw else '证据4：先要有地量日，成本线才起算')
    stale = i - lo > 40
    if t == 'QQQI': scale = None
    zone = [round(aw, 2), round(aw * 1.02, 2)] if aw else None
    out = dict(ticker=t, proxy='QQQ' if t == 'QQQI' else None, asof=B['d'][i], close=round(c, 2), src=B['src'][i], armed=armed, score=score,
               evidence=ev, state=state, high=[B['d'][hi], round(H, 2)], low=[B['d'][lo], round(L, 2)], low_stale=stale,
               stop_line=round(stop, 2), fan05_next=round(fan_next, 2) if fan_next else None, avwap=round(aw, 2) if aw else None,
               build_zone=zone if score == 4 else None, target=round(tgt, 2) if tgt else None, next_close_needs=nxt)
    return out

def text(o):
    t = o['ticker'] + ('（用 QQQ 的K线代理）' if o['proxy'] else '')
    L = [f"【四证检查】{t} · {o['asof']} 收盘 {o['close']}（来源 {o['src']}）：{o['state']}"]
    L.append(f"  高点 {o['high'][1]}（{o['high'][0]}）→ 低点 {o['low'][1]}（{o['low'][0]}）{'，低点已超过 40 根K线，证据偏旧' if o['low_stale'] else ''}")
    lv = [f"止损线 {o['stop_line']}"]
    if o['fan05_next']: lv.append(f"扇子中线（下一根）{o['fan05_next']}")
    lv.append(f"成本线 {o['avwap']}" if o['avwap'] else '成本线未起算')
    if o['target']: lv.append(f"目标参考 {o['target']}")
    L.append('  ' + '；'.join(lv))
    if o['build_zone']: L.append(f"  建仓区 {o['build_zone'][0]}–{o['build_zone'][1]}（成本线到 +2%），先上半仓，止损 {o['stop_line']}")
    for x in o['next_close_needs']: L.append('  · ' + x)
    L.append('  ' + VERDICT)
    return '\n'.join(L)

if __name__ == '__main__':
    a = sys.argv[1:]; bars = []
    if '--refresh' in a: subprocess.run([sys.executable, '-I', f'{ROOT}/prep_data.py'], check=True, stdout=subprocess.DEVNULL)
    while '--bar' in a:
        k = a.index('--bar'); bars.append(a[k + 1].split(',')); del a[k:k + 2]
    tick = [x.upper() for x in a if not x.startswith('--')] or ['SPCX', 'NVDA', 'QQQ']
    res = [check(t, bars) for t in tick]
    if '--json' in a: print(json.dumps(res, ensure_ascii=False, indent=1))
    else: print('\n\n'.join(text(o) for o in res))
