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
        steps.append(dict(q=QUESTIONS[k], look=look, say=say, sticker=sticker, tone='good' if sticker in GOOD else 'neutral' if sticker == '不适用' else 'bad',
                          evidence=k + 1, ok=bool(ok)))

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
    # 四项没齐：引擎照样算出止损、前高这些结构位（图上的「自动画」和「依据」里还看得到），但卡片上不把它们当交易价位给出去
    ready = bool(f['all4'])
    tgt = lv['target'] if ready and lv['target_usable'] else None
    return dict(verdict=verdict, code=f['conclusion_code'], direction='做多', horizon=f"日线 · 最长持有 {lv['max_hold_bars']} 根",
                reason=f['conclusion'], price=f['close'], entry_zone=zone, stop=lv['stop'] if ready else None, target=tgt, rr=lv['rr'] if ready else None,
                lines=[['建仓区', '压着成本线' if ready else '条件没齐，不给', aw if ready else None], ['止损', '垫在新低下面' if ready else '条件没齐，不给', lv['stop'] if ready else None],
                       ['目标', '前面高点' if ready else '条件没齐，不给', tgt]],
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
            'type': 'object', 'additionalProperties': False, 'required': ['q', 'say', 'sticker', 'tone', 'evidence', 'draw'],
            'properties': {'q': {'type': 'string'}, 'say': {'type': 'string'}, 'sticker': {'type': 'string'},
                           'tone': {'type': 'string', 'enum': ['good', 'bad', 'neutral']}, 'evidence': {'type': 'integer'},
                           'draw': {'type': 'array', 'items': {
                               'type': 'object', 'additionalProperties': False, 'required': ['type', 'dates', 'at', 'price', 'top', 'bottom', 'label'],
                               'properties': {'type': {'type': 'string', 'enum': ['point', 'path', 'level', 'zone', 'volume', 'macd']},
                                              'dates': {'type': 'array', 'items': {'type': 'string'}},
                                              'at': {'type': 'string', 'enum': ['high', 'low', 'open', 'close']},
                                              'price': {'type': 'number'}, 'top': {'type': 'number'}, 'bottom': {'type': 'number'},
                                              'label': {'type': 'string'}}}}}}},
    },
}
MIN_STEPS, MAX_STEPS = 2, 8
MAX_DRAW = 8


def chart_data(t, asof, bars=None):
    """Bars up to `asof`, for turning Claude's drawing instructions into real chart coordinates.
    bars = the series the reading was made on (weekly bars for a weekly reading); default: the daily bars."""
    full = bars if bars is not None else panel.load(t)['B']
    i = panel.index_at(full, asof)
    return dict(d=full['d'][:i + 1], idx={d: k for k, d in enumerate(full['d'][:i + 1])},
                high=full['h'], low=full['l'], open=full['o'], close=full['c'])


def _day(s, D):
    """'2026-11-05' or '11-05' -> a trading day that exists on or before the reading's date, else None."""
    s = str(s).strip()
    m = re.fullmatch(r'(\d{4})-(\d{1,2})-(\d{1,2})', s)
    if m:
        key = f'{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}'
        return key if key in D['idx'] else None
    m = re.fullmatch(r'(\d{1,2})[-/月](\d{1,2})日?', s)
    if m:
        last = D['d'][-1]
        year, mo, da = int(last[:4]), int(m[1]), int(m[2])
        # 月-日 默认是当年的；只有比这次分析的日期还晚（比如 1 月里说“12-20”）才算去年的，不会把“明天”错当成去年同一天
        y = year if (mo, da) <= (int(last[5:7]), int(last[8:10])) else (year - 1 if mo > int(last[5:7]) else None)
        if y is not None:
            key = f'{y:04d}-{mo:02d}-{da:02d}'
            if key in D['idx']:
                return key
    return None


def resolve_draw(items, D, forms):
    """Claude says WHAT to mark (which days, high or low, which level); the prices are read from the data here.
    Anything that points at a day that does not exist, or a level that is not a real number from the input, is dropped."""
    out = []
    if not isinstance(items, list):
        return out
    lo, hi = float(D['low'][max(0, len(D['d']) - 250):len(D['d'])].min()), float(D['high'][max(0, len(D['d']) - 250):len(D['d'])].max())
    px = lambda day, at: round(float(D[at if at in ('high', 'low', 'open', 'close') else 'close'][D['idx'][day]]), 2)
    for it in items[:MAX_DRAW]:
        if not isinstance(it, dict):
            continue
        typ, at = it.get('type'), it.get('at')
        label = str(it.get('label') or '').strip()[:10]
        days = [d for d in (_day(x, D) for x in (it.get('dates') or [])) if d]
        if typ == 'point' and days:
            for d in days[:6]:
                out.append(dict(type='point', date=d, price=px(d, at), label=label))
        elif typ == 'path' and len(days) >= 2:
            out.append(dict(type='path', points=[dict(date=d, price=px(d, at)) for d in days[:8]], label=label))
        elif typ == 'level':
            p = px(days[0], at) if days else (round(float(it['price']), 2) if isinstance(it.get('price'), (int, float)) and not isinstance(it.get('price'), bool) else None)
            if p is not None and lo * 0.6 <= p <= hi * 1.4 and (days or p in forms):
                out.append(dict(type='level', price=p, label=label))
        elif typ == 'zone' and len(days) >= 2:
            a, b = sorted((D['idx'][days[0]], D['idx'][days[-1]]))
            top = it.get('top') if isinstance(it.get('top'), (int, float)) and it.get('top') else float(D['high'][a:b + 1].max())
            bot = it.get('bottom') if isinstance(it.get('bottom'), (int, float)) and it.get('bottom') else float(D['low'][a:b + 1].min())
            if lo * 0.6 <= bot < top <= hi * 1.4:
                out.append(dict(type='zone', date_from=D['d'][a], date_to=D['d'][b], top=round(float(top), 2), bottom=round(float(bot), 2), label=label))
        elif typ in ('volume', 'macd') and days:
            out.append(dict(type=typ, dates=days[:8], label=label))
    return out


def normalize(raw, f, tmpl, D=None, forms=None, positive=None, link_evidence=True):
    """Claude's JSON -> cards. Claude chooses what to look at, how many steps and in what order (zaki 11-16: 市场变化多，
    内容要完全自由，只保留模板版那种呈现方式)。What stays with the engine: a step that says it is about evidence 1–4 gets that
    evidence's true/false from the engine, and a sticker that contradicts it is replaced. Returns (narration, None) or (None, reason)."""
    if not isinstance(raw, dict):
        return None, '不是 JSON 对象'
    steps = raw.get('steps')
    if not (isinstance(steps, list) and MIN_STEPS <= len(steps) <= MAX_STEPS and all(isinstance(s, dict) for s in steps)):
        return None, f'步骤数不在 {MIN_STEPS}–{MAX_STEPS} 之间'
    out = dict(steps=[])
    for key in ('hook', 'story', 'final'):
        if not (isinstance(raw.get(key), str) and raw[key].strip()):
            return None, f'缺少 {key}'
        out[key] = raw[key].strip()
    for k, s in enumerate(steps):
        look, say, q = s.get('look'), s.get('say'), s.get('q')
        look = look if isinstance(look, str) else ''             # 新格式不要 look：数字画在图上，不写成一段话
        if not (isinstance(say, str) and say.strip()):
            return None, f'第 {k + 1} 步缺少 say'
        ev = s.get('evidence') if link_evidence and s.get('evidence') in (1, 2, 3, 4) else 0      # 后手模型没有四项证据可对
        sticker = s.get('sticker').strip()[:8] if isinstance(s.get('sticker'), str) and s.get('sticker').strip() else ''
        tone = s.get('tone') if s.get('tone') in ('good', 'bad', 'neutral') else ('good' if sticker in GOOD else 'bad' if sticker in BAD else 'neutral')
        ok = None
        if ev:                                                   # 这一步讲的是四项证据之一：成立与否引擎说了算
            t = tmpl['steps'][ev - 1]
            ok = t['ok']
            if (ok and tone == 'bad') or (not ok and tone == 'good'):
                sticker, tone = t['sticker'], ('good' if ok else 'bad')
        out['steps'].append(dict(q=q.strip()[:20] if isinstance(q, str) and q.strip() else f'第 {k + 1} 步', look=look.strip(), say=say.strip(),
                                 sticker=sticker, tone=tone, evidence=ev, ok=ok,
                                 draw=resolve_draw(s.get('draw'), D, forms or set()) if D else []))
    # 大字结论不能和引擎唱反调
    fin = out['final']
    pos = f['all4'] if positive is None else positive          # 所选规则模型的清单是不是全中（四证 4/4，或后手 3/3）
    if (pos and re.search(r'不抄|未触发|不可|别', fin)) or (not pos and not re.search(r'不抄|未触发|还不|不可|别|不够|再等|等', fin)) or len(fin) > 16:
        out['final'] = tmpl['final']
    watch = raw.get('watch')
    out['watch'] = [w.strip() for w in watch if isinstance(w, str) and w.strip()][:6] if isinstance(watch, list) else []
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
        # 原值、百分比换算，以及成交量换成万 / 百万 / 亿
        for m in (1, 100, 0.01) + ((1e-4, 1e-6, 1e-8) if a >= 1e5 else ()):
            for k in (0, 1, 2):
                forms.add(round(a * m, k))
    # 自由分析时常见的两种现算：两个价位的差、一个价位相对另一个的涨跌幅
    prices = sorted(a for a in allowed if 0 < a < 1e5)
    if len(prices) <= 600:
        for i, a in enumerate(prices):
            for b in prices[i + 1:]:
                d, p = b - a, (b / a - 1) * 100
                q = (1 - a / b) * 100
                for k in (0, 1, 2):
                    forms.add(round(d, k)); forms.add(round(p, k)); forms.add(round(q, k))
    texts = [narr['hook'], narr['story'], narr['final']] + list(narr['watch'])
    for s in narr['steps']:
        texts += [s.get('look') or '', s['say']] + [d.get('label') or '' for d in s.get('draw') or []]
    bad = []
    for t in texts:
        for m in NUM.findall(t.replace(',', '')):
            if round(float(m), 2) not in forms and m not in bad:
                bad.append(m)
    return bad
