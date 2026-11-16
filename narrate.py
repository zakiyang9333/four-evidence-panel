"""视频式解说（四问）：事实、模板版、Claude 输出的校验。

  build_facts()   把引擎在某一天的输出整理成“输入 JSON”：模板和 Claude 用的是同一份，里面的数字都来自 engine.py。
  template()      不调用 API 的固定句式版本，没有密钥、断网或 Claude 输出不合格时用它。
  card()          “规则模型信号”卡片，数字全部来自引擎，不经过 Claude。
  normalize()     把 Claude 返回的 JSON 套回固定结构：ok / evidence / 四问的名字由引擎覆盖。
  bad_numbers()   把解说里出现的每个数字和输入 JSON 里的数字比对，对不上的列出来（有一个就整段不用）。

这里不判定任何规则：证据真假、结论、价位都取自 engine.compute() 和 panel.state_at()。
“下一根 K 线要看什么”的句式照抄 four_evidence_check.py，测试会核对两者一致。
"""
import datetime
import re

import numpy as np

import engine as E
import panel

P, F = E.VIDEO, E.FIXED
QUESTIONS = ('第一问 量', '第二问 MACD', '第三问 扇子', '第四问 成本线')
STICKERS = ('不抄！', '还不抄', '证据+1', '报警而已', '站回来了', '没得站', '不适用')
GOOD, BAD = ('证据+1', '报警而已', '站回来了'), ('不抄！', '还不抄', '没得站')
FOOT = '规则回测证据不足（{n} 笔，p={p:.2f}），仅供观察'


def r2(x):
    return None if x is None or not np.isfinite(x) else round(float(x), 2)


def md(date):
    """'2026-11-05' -> '11月5日'"""
    d = datetime.date.fromisoformat(date)
    return f'{d.month}月{d.day}日'


def next_close_needs(B, S, i):
    """Thresholds for the next close. Same sentences as four_evidence_check.check(); extra lines when not armed."""
    n = i + 1
    hi, lo = int(S['hi_i'][i]), int(S['low_i'][i])
    H, L = float(S['H'][i]), float(S['L'][i])
    ev = {k: bool(S[k][i]) for k in ('e1', 'e2', 'e3', 'e4')}
    if not bool(S['dd_ok'][i]):
        dd = int(P['dd'] * 100)
        return [f'从高点跌够{dd}%（约{H * (1 - P["dd"]):.2f}）系统才开始找底', '地量要出现在跌够之后，成本线才会起算']
    vmin59 = float(B['v'][n - P['n_vol'] + 1:].min()) if n >= P['n_vol'] else None
    fan_next = float(H + (L + P['fan'] * (H - L) - H) * (i + 1 - hi) / (lo - hi)) if lo > hi else None
    aw = float(S['avwap'][i]) if np.isfinite(S['avwap'][i]) else None
    trough = float(S['hist'][hi:lo - F['div_gap'] + 1].min()) if lo - hi >= F['div_gap'] + 1 else None
    out = []
    if not ev['e1'] and vmin59:
        out.append(f'证据1：下一根成交量 ≤ {vmin59 / 1e6:.1f} 百万股才算地量')
    if not ev['e2']:
        out.append(f'证据2：需再创新低（< {L:.2f}）且当天 MACD 柱高于 {S["hist"][lo]:.2f}' if trough is not None and S['hist'][lo] <= trough
                   else f'证据2：需再创新低（< {L:.2f}）且 MACD 柱不创新低')
    if not ev['e3'] and fan_next:
        out.append(f'证据3：下一根收盘 > {fan_next:.2f}（扇子中线，每天下移约 {abs((L + P["fan"] * (H - L) - H) / (lo - hi)):.2f}）')
    if not ev['e4']:
        out.append(f'证据4：放量阳线收盘 > 成本线 {aw:.2f}' if aw else '证据4：先要有地量日，成本线才起算')
    return out


def build_facts(t, asof=None):
    """The input JSON for one reading. Every number in it comes from the engine run on data cut at `asof`."""
    st = panel.state_at(t, asof)
    full = panel.load(t)['B']
    i = st['index']
    B = panel.truncate(full, i)
    S = E.compute(B)
    n = i + 1
    hi, lo, an = int(S['hi_i'][i]), int(S['low_i'][i]), int(S['anchor'][i])
    H, L, c = float(S['H'][i]), float(S['L'][i]), float(B['c'][i])
    v = float(B['v'][i])
    vmin = float(B['v'][max(0, i - P['n_vol'] + 1):i + 1].min())
    hist = S['hist']
    trough = float(hist[hi:lo - F['div_gap'] + 1].min()) if lo - hi >= F['div_gap'] + 1 else None
    fl, aw = float(S['fanline'][i]), float(S['avwap'][i])
    lit = {e['k'].lower(): e['lit'] for e in st['evidence']}
    oks = {e['k'].lower(): e['ok'] for e in st['evidence']}
    vol = lambda x: dict(shares=int(x), wan=round(x / 1e4), million=round(x / 1e6, 1), yi=round(x / 1e8, 2))
    return dict(
        ticker=t, asof=st['asof'], close=r2(c), prev_close=r2(B['c'][i - 1]), chg_pct=st['chg_pct'],
        armed=st['armed'], all4=st['all4'], score=st['lit'], conclusion=st['conclusion']['title'], conclusion_code=st['conclusion']['code'],
        high=dict(date=B['d'][hi], price=r2(H)), low=dict(date=B['d'][lo], price=r2(L)), low_is_today=lo == i, bars_since_low=i - lo,
        drop_high_to_low_pct=r2((1 - L / H) * 100), close_below_high_pct=r2((1 - c / H) * 100),
        arm_threshold_pct=int(P['dd'] * 100), arm_price=r2(H * (1 - P['dd'])),
        e1=dict(name='地量见底', ok=oks['e1'], lit=lit['e1'], enough_bars=n >= P['n_vol'], window_days=P['n_vol'], volume=vol(v), min_in_window=vol(vmin),
                more_than_min_pct=r2((v / vmin - 1) * 100), anchor_date=B['d'][an] if an >= 0 else None),
        e2=dict(name='底背离', ok=oks['e2'], lit=lit['e2'], low_date=B['d'][lo], low_price=r2(L), macd_hist_at_low=r2(hist[lo]),
                prior_deepest_hist=r2(trough)),
        e3=dict(name='跌速放缓', ok=oks['e3'], lit=lit['e3'], close=r2(c), fan_mid=r2(fl), gap_pct=r2((fl / c - 1) * 100) if np.isfinite(fl) else None),
        e4=dict(name='站回成本线', ok=oks['e4'], lit=lit['e4'], avwap=r2(aw), close=r2(c), close_above_line=bool(np.isfinite(aw) and c > aw),
                gap_pct=r2((aw / c - 1) * 100) if np.isfinite(aw) else None, anchor_date=B['d'][an] if an >= 0 else None),
        levels=dict(stop=r2(S['stop'][i]), stop_pct_below_low=int(P['stop'] * 100), target=st['signal']['target'] and r2(st['signal']['target']),
                    target_usable=st['signal']['target_usable'], rr=st['signal']['rr'], max_hold_bars=F['max_hold']),
        next_close_needs=next_close_needs(B, S, i), notes=st['notes'])


# ---------- template (no API) ----------

def template(f):
    e1, e2, e3, e4 = f['e1'], f['e2'], f['e3'], f['e4']
    steps = []

    def step(k, look, say, sticker, ok):
        steps.append(dict(q=QUESTIONS[k], look=look, say=say, sticker=sticker, evidence=k + 1, ok=bool(ok)))

    # 第一问 量
    if e1['ok']:
        step(0, f"{md(e1['anchor_date'])}成交量缩到{e1['window_days']}日最小，这天算地量日", '量缩到头了，地量到了', '证据+1' if e1['lit'] else '不适用', e1['lit'])
    elif not e1['enough_bars']:
        step(0, f"K线不足{e1['window_days']}根，没法比地量", '样本太短，这一问先放着', '不适用', False)
    else:
        vs = lambda x: f"{x['yi']}亿股" if x['shares'] >= 1e8 else f"{x['wan']}万股"
        step(0, f"当天{vs(e1['volume'])}，比{e1['window_days']}日最小量{vs(e1['min_in_window'])}多{round(e1['more_than_min_pct'])}%",
             '量没缩下去，还有人在卖', '不抄！', False)
    # 第二问 MACD
    if e2['prior_deepest_hist'] is None:
        step(1, '高点到低点太近，MACD没法前后比', '还比不出背离', '不适用', False)
    elif e2['ok']:
        step(1, f"{md(e2['low_date'])}低点那天绿柱{e2['macd_hist_at_low']}，比之前最深的{e2['prior_deepest_hist']}短",
             '价格新低，力度没跟着新低', '报警而已' if e2['lit'] else '不适用', e2['lit'])
    else:
        step(1, f"{md(e2['low_date'])}低点那天绿柱{e2['macd_hist_at_low']}，比之前最深的{e2['prior_deepest_hist']}还长",
             '价格新低，力度也新低，空头还在砍', '不抄！', False)
    # 第三问 扇子
    if e3['fan_mid'] is None:
        step(2, '今天就是最低点，扇子还画不了', '还在往下掉，速度没法量', '不适用', False)
    elif e3['ok']:
        step(2, f"收盘{e3['close']}，站在扇子中线{e3['fan_mid']}上面", '下坡变缓了，中线踩过去了', '证据+1' if e3['lit'] else '不适用', e3['lit'])
    else:
        step(2, f"收盘{e3['close']}，扇子中线{e3['fan_mid']}还压在头顶", '下坡没变缓，跌速一点没减', '还不抄', False)
    # 第四问 成本线
    if e4['avwap'] is None:
        step(3, '没有地量日，成本线还没起算', '连成本线都没有，谈不上站回', '没得站', False)
    elif e4['ok']:
        step(3, f"放量阳线站回成本线{e4['avwap']}，收盘{e4['close']}还在线上", '放量大阳站回来了', '站回来了' if e4['lit'] else '不适用', e4['lit'])
    elif e4['close_above_line']:
        step(3, f"收盘{e4['close']}在成本线{e4['avwap']}上面，但低点后还没出现放量阳线", '站是站上了，缺一根放量大阳', '还不抄', False)
    else:
        step(3, f"成本线{e4['avwap']}，收盘{e4['close']}还在线下", '还被按在成本线下面', '还不抄', False)

    drop = round(f['drop_high_to_low_pct'])
    if not f['armed']:
        hook, final = f"停，跌了{drop}%还不叫跌多了", '未触发，不抄'
    elif f['all4']:
        hook, final = '四样齐了，按规则是信号', '4/4，四样齐了'
    else:
        hook, final = f"停，证据才{f['score']}/4，别急着抄", f"{f['score']}/4，还不抄"
    tail = '今天又创新低' if f['low_is_today'] else ('之后反弹' if f['close'] > f['low']['price'] else '还趴在低位')
    story = f"{md(f['high']['date'])}见顶{f['high']['price']}，一路回落，{md(f['low']['date'])}探到{f['low']['price']}，{tail}"
    return dict(hook=hook, story=story, steps=steps, final=final, watch=list(f['next_close_needs']))


def card(f, backtest=None):
    """规则模型信号卡片：全部来自引擎，不经过 Claude。"""
    lv = f['levels']
    verdict = '可以入场（仅观察）' if f['all4'] else ('不可入场' if f['armed'] else '未触发')
    aw = f['e4']['avwap']
    zone = [aw, round(aw * 1.02, 2)] if (f['all4'] and aw) else None        # four_evidence_check.py：成本线到 +2%，只在 4/4 时给
    foot = FOOT.format(n=backtest['n'], p=backtest['p']) if backtest else '规则回测证据不足，仅供观察'
    return dict(verdict=verdict, code=f['conclusion_code'], direction='做多', horizon=f"日线 · 最长持有 {lv['max_hold_bars']} 根",
                reason=f['conclusion'], price=f['close'], entry_zone=zone, stop=lv['stop'],
                target=lv['target'] if lv['target_usable'] else None, rr=lv['rr'],
                lines=[['建仓区', '压着成本线', aw], ['止损', '垫在新低下面', lv['stop']], ['目标', '前面高点', lv['target'] if lv['target_usable'] else None]],
                footer=foot)


def card_from_state(st, backtest=None):
    """Same card, built straight from panel.state_at() (no second engine run): used by /api/state."""
    sg = st['signal']
    return card(dict(all4=st['all4'], armed=st['armed'], conclusion=st['conclusion']['title'], conclusion_code=st['conclusion']['code'],
                     close=r2(st['close']), e4=dict(avwap=r2(st['levels']['avwap'])),
                     levels=dict(stop=r2(sg['stop']), target=r2(sg['target']), target_usable=sg['target_usable'], rr=sg['rr'],
                                 max_hold_bars=F['max_hold'])), backtest)


# ---------- checking what Claude wrote ----------

SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['hook', 'story', 'steps', 'final', 'watch'],
    'properties': {
        'hook': {'type': 'string'}, 'story': {'type': 'string'}, 'final': {'type': 'string'},
        'watch': {'type': 'array', 'items': {'type': 'string'}},
        'steps': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['q', 'look', 'say', 'sticker', 'evidence', 'ok'],
            'properties': {'q': {'type': 'string'}, 'look': {'type': 'string'}, 'say': {'type': 'string'},
                           'sticker': {'type': 'string', 'enum': list(STICKERS)}, 'evidence': {'type': 'integer'}, 'ok': {'type': 'boolean'}}}},
    },
}


def normalize(raw, f, tmpl):
    """Claude's JSON -> the fixed structure. Returns (narration, None) or (None, reason)."""
    if not isinstance(raw, dict):
        return None, '不是 JSON 对象'
    steps = raw.get('steps')
    if not (isinstance(steps, list) and len(steps) == 4 and all(isinstance(s, dict) for s in steps)):
        return None, '四问不是 4 条'
    out = dict(steps=[])
    for key in ('hook', 'story', 'final'):
        if not (isinstance(raw.get(key), str) and raw[key].strip()):
            return None, f'缺少 {key}'
        out[key] = raw[key].strip()
    for k, s in enumerate(steps):
        t = tmpl['steps'][k]
        look, say = s.get('look'), s.get('say')
        if not (isinstance(look, str) and look.strip() and isinstance(say, str) and say.strip()):
            return None, f'第 {k + 1} 问缺少 look 或 say'
        sticker = s.get('sticker')
        ok = t['ok']                                             # 引擎说了算
        if sticker not in STICKERS or (ok and sticker in BAD) or (not ok and sticker in GOOD):
            sticker = t['sticker']
        out['steps'].append(dict(q=QUESTIONS[k], look=look.strip(), say=say.strip() if len(say.strip()) <= 40 else t['say'],
                                 sticker=sticker, evidence=k + 1, ok=ok))
    # 大字结论不能和引擎唱反调
    fin = out['final']
    if (f['all4'] and re.search(r'不抄|未触发|不可|别', fin)) or (not f['all4'] and not re.search(r'不抄|未触发|还不|不可|别|不够|再等|等', fin)) or len(fin) > 16:
        out['final'] = tmpl['final']
    watch = raw.get('watch')
    out['watch'] = [w.strip() for w in watch if isinstance(w, str) and w.strip()][:4] if isinstance(watch, list) else []
    if not out['watch']:
        out['watch'] = list(tmpl['watch'])
    return out, None


NUM = re.compile(r'\d+(?:\.\d+)?')
ALWAYS = {0, 1, 2, 3, 4, P['n_vol'], int(P['dd'] * 100), int(P['stop'] * 100), F['hi_win'], F['tgt_win'], F['max_hold'], F['div_gap'],
          12, 26, 9, P['vol_mult'], 0.382, 0.5, 0.618, 100}


def allowed_numbers(*objs):
    """Every number that appears anywhere in the input: numeric fields, digits inside strings, date parts."""
    out = set(ALWAYS)

    def walk(x):
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            out.add(abs(float(x)))
        elif isinstance(x, str):
            for m in NUM.findall(x.replace(',', '')):
                out.add(float(m))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
    for o in objs:
        walk(o)
    return out


def bad_numbers(narr, allowed):
    """Numbers in the narration that cannot be traced to the input (after rounding to 0–2 decimals or a ×100 / ÷100 percent conversion)."""
    forms = set()
    for a in allowed:
        for m in (1, 100, 0.01):
            for k in (0, 1, 2):
                forms.add(round(a * m, k))
    texts = [narr['hook'], narr['story'], narr['final']] + list(narr['watch'])
    for s in narr['steps']:
        texts += [s['look'], s['say']]
    bad = []
    for t in texts:
        for m in NUM.findall(t.replace(',', '')):
            if round(float(m), 2) not in forms and m not in bad:
                bad.append(m)
    return bad
