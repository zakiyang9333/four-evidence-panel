"""「AI 量化」面板的后端拼装（APP_ADDENDUM_QUANT_AI.md §6）：/api/quant 返回的那一份 JSON。

这里不算规则，只把三样东西拼到一起：结构线（structure.py）、评分表盘（chart_score.py）、所选规则模型的信号
（四证 = engine.py 经 panel.state_at；后手 = houshou.py）。再加上信号卡的六格、编号图例、模板解说和交给 Claude 的事实。
表盘和规则信号是两套独立的东西：表盘描述图表现状，信号是所选模型的清单结果，两者可以不一致。
"""
import json
import os
import threading
import time

import chart_score
import houshou as hs
import panel
import portfolio
import structure

MODELS = (('four', '四证·抄底 v1.0'), ('houshou', hs.NAME))
BANNER = '四证：回测证据不足 ｜ 后手战法：尚未回测 ｜ 仅观察，不构成买卖依据'
EXPLAIN = ['表盘和信号卡是两套独立的东西：表盘描述图表现状，信号卡是所选模型的清单结果。两者可以一个偏空、一个说条件齐了。',
           '「量化 = 战法，对上了」不是独立验证：模型本来就是把那几条规则写成代码，必然一致。',
           '规则是写死的，市场不会照着清单走。清单显示「无结构」「不适用」时，就是这套规则今天用不上，不代表没有机会或没有风险。']
_lock = threading.Lock()
_P = {}


def prepared(t):
    """Bars and the prepared causal pass for one ticker, rebuilt when the data changes."""
    B = panel.load(t)['B']
    key = (len(B['d']), B['d'][-1], float(B['c'][-1]), float(B['v'][-1]))
    if _P.get(t, (None,))[0] != key:
        _P[t] = (key, hs.prepare(B))
    return B, _P[t][1]


# ---------- manual cost anchor (data/houshou_anchor.json: {ticker: date}) ----------

def anchor_path():
    return os.path.join(panel.data_dir(), 'houshou_anchor.json')


def anchors():
    try:
        with open(anchor_path(), encoding='utf-8') as f:
            x = json.load(f)
        return {k: v for k, v in x.items() if isinstance(v, str)} if isinstance(x, dict) else {}
    except (OSError, ValueError):
        return {}


def set_anchor(t, date):
    """date = a trading day of this ticker, or None to go back to the automatic anchor."""
    if t not in panel.TICKERS:
        raise KeyError(t)
    cur = anchors()
    if date:
        if date not in panel.load(t)['B']['d']:
            raise ValueError('这一天不是这只标的的交易日')
        cur[t] = date
    else:
        cur.pop(t, None)
    tmp = anchor_path() + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cur, f, ensure_ascii=False, indent=1)
    os.replace(tmp, anchor_path())
    return cur.get(t)


# ---------- position (read-only, for the 持仓 field and the core-position rule) ----------

def position(t):
    """未持仓 / 持仓 N 股 / 核心仓, from portfolio_state.json. Never written, never sent anywhere."""
    st, err = portfolio.read_state()
    if err:
        return dict(text='没有持仓数据', held=False, core=False)
    qty, core, others = 0, False, 0
    for p in st.get('positions') or []:
        if not isinstance(p, dict) or portfolio.chart_ticker(p) != t:
            continue
        if p.get('type') == 'stock' and p.get('symbol') == t:
            qty += p.get('qty') or 0
            core = core or p.get('side') == 'safe' or '核心' in str(p.get('note') or '')
        else:
            others += 1
    if not qty and not others:
        return dict(text='未持仓', held=False, core=False)
    text = ('核心仓 ' if core else '持仓 ') + (f'{qty:g} 股' if qty else '') + (f'{" + " if qty else ""}相关 {others} 项' if others else '')
    return dict(text=text.strip(), held=True, core=bool(core))


# ---------- signal card (six cells) ----------

def _pct(x, price):
    return None if x is None or not price else round((x / price - 1) * 100, 2)


def _cells(price, zone, mid, stop, t1, rr, t2_text, core=False, entry_note='中值'):
    f = lambda x: '—' if x is None else f'{x:,.2f}'
    sp = lambda x: '' if x is None else f'{x:+.2f}% · 距现价'
    return [dict(k='price', name='现价', v=f(price), sub='当前图表'),
            dict(k='zone', name='入场区间', v=f'{f(zone[0])} – {f(zone[1])}' if zone else '—', sub=f'{entry_note} {sp(_pct(mid, price))}' if zone and mid else '条件没齐，不给区间'),
            dict(k='stop', name='止损', v='核心仓不适用' if core else f(stop), sub='核心仓没有价格止损' if core else (sp(_pct(stop, price)) + ' · 手动止损' if stop is not None else ''), tone='stop'),
            dict(k='t1', name='第一目标', v=f(t1), sub=sp(_pct(t1, price)), tone='target'),
            dict(k='rr', name='盈亏比', v=f'{rr:.2f} : 1' if rr is not None and not core else '—', sub='按入场中值' if rr is not None and not core else ''),
            dict(k='t2', name='第二目标', v=t2_text, sub='')]


VERDICT_TEXT = {'下后手': '后手条件齐了（未回测）', '等': '等', '不追': '不追', '不追·出货区': '不追 · 出货区', '出货区': '出货区', '还能看': '还能看',
                '不适用': '这套清单用不上', '已失效': '结构已失效'}


def houshou_card(r, pos):
    core = pos['core']
    v = r['verdict']
    if v == '下后手':
        text = '价格回到成本线，两段跌幅相当，缩量刺破后收回，后手清单三项同时成立。这套规则没有回测过，这里只是把清单结果摆出来。'
    elif r['phase'] == '回落中':
        text = f'三冲之后在回落，后手清单 {sum(c["ok"] for c in r["checks"])}/3。' + ('还缺：' + '、'.join(c['name'] for c in r['checks'] if not c['ok']) + '。')
    elif r['phase'] == '拉升中':
        n = len(r['pushes'])
        text = f'还在创新高，已经第 {n} 冲，现价比成本线高 {r["dist_pct"]}%。' + \
               {'不追·出货区': '离成本太远、第三冲缩量、天量长上影，三项全中。', '不追': '离成本线太远，按规则不追。', '出货区': '第三冲缩量又放天量长上影，按规则是出货区。',
                '还能看': '不追清单的条件没有成立。'}[v]
    elif r['phase'] == '已失效':
        text = r['note']
    else:
        text = (r['note'] or '没有找到三冲结构。') + '这套清单今天用不上，不代表没有机会或没有风险。'
    stop = None if core else r['stop']
    return dict(model=hs.NAME, verdict=VERDICT_TEXT.get(v, v), code=v, tags=['做多', '日线', '引擎结果'] + (['全部参数含估算'] if True else []), text=text,
                cells=_cells(r['close'], r['zone'], r['mid'], stop, r['t1'], r['rr'], '视频未说明', core=core and r['zone'] is not None),
                footer='历史数据重放｜未回测｜仅供学习')


def four_card(st):
    cd, sg = st['card'], st['signal']
    zone = cd['entry_zone']
    return dict(model='四证·抄底 v1.0', verdict=cd['verdict'], code=cd['code'], tags=[cd['direction'], cd['horizon'], '引擎结果'], text=st['conclusion']['text'],
                cells=_cells(cd['price'], zone, (zone[0] + zone[1]) / 2 if zone else None, cd['stop'], cd['target'], cd['rr'], '—'), footer=cd['footer'])


# ---------- numbered legend: one plain sentence per kind of mark on the chart ----------

def legend(model, r, lines, core, four=None):
    out, seen = [], {}

    def add(key, text):
        if key not in seen:
            seen[key] = len(out) + 1
            out.append(dict(n=seen[key], key=key, text=text))

    if model == 'houshou' and r.get('anchor'):
        by = '你手动定的' if r['anchor']['by'] == 'manual' else '自动找的'
        add('anchor', f'蓝色竖条是成本锚点（{by}）：从这一天开始，算大家买进来的平均价。')
        add('avwap', '黄线是成本线：从锚点那天起，所有人买进来的平均价。价格离它越远，掉回来的路越长。')
        add('band', '黄线两边的浅色带：大部分成交都落在这条带子里，价格跑出带子就算走远了。')
        if r['pushes']:
            add('push', '带数字的气泡是一次次冲高。气泡里的百分比是这一冲的成交量相当于第一冲的多少：越冲越小，说明跟着冲的人少了。')
        if r.get('abcd') and r['abcd'].get('B'):
            add('abcd', 'A、B、C、D 是回落的两段：A 到 B 是第一段，C 到 D 是第二段。两段跌得差不多长，才算跌到位。')
        if r.get('zone'):
            add('zone', '绿色带是建仓区：成本线上下 1%。清单三项没齐的时候不显示。')
            add('target', '粉色虚线是目标：第三冲的高点。')
            if not core:
                add('stop', '紫色虚线是止损：D 点下面 2%，收盘跌破就认错。券商只有限价单，这条线要自己手动执行。')
    if model == 'four' and four:
        if any(x['id'] == 'four_fan' for x in lines):
            add('four_fan', '青色斜线是扇子中线：从高点到低点这段跌势的一半速度。收盘站到它上面，说明跌得慢下来了。')
        if any(x['id'] == 'four_avwap' for x in lines):
            add('four_avwap', '黄线是成本线：从成交量最小的那天起，大家买进来的平均价。')
        if any(x['id'] == 'four_stop' for x in lines):
            add('four_stop', '紫色虚线是止损：垫在最低点下面一点。')
    if any(x['id'] in ('res', 'sup') for x in lines):
        add('sr', '红色横线是压力，绿色横线是支撑：价格在这个位置来回碰过很多次，碰过几次写在线上。')
    if any(x['kind'] == 'trend' for x in lines):
        add('trend', '斜线是趋势线：把最近两个高点（或两个低点）连起来往右延长，看价格是不是还顺着它走。')
    if any(x['style'] == 'fib' for x in lines):
        add('fib', '灰色细横线是回撤刻度：把这一轮上涨切成几段，看现在退回到了哪一段。')
    for x in lines:
        x['n'] = seen.get(x['id'] if x['id'] in seen else 'sr' if x['id'] in ('res', 'sup') else 'trend' if x['kind'] == 'trend' else 'fib' if x['style'] == 'fib'
                          else 'zone' if x['id'].startswith('zone') else x['id'])
    return out


# ---------- the response ----------

def result(t, model='houshou', asof=None):
    if model not in dict(MODELS):
        raise ValueError('没有这个模型')
    with _lock:
        st = panel.state_at(t, asof or None)
        i = st['index']
        pos = position(t)
        t0 = time.perf_counter()
        B, P = prepared(t)
        hsr = hs.compute(B, i, anchors().get(t), with_history=False, P=P)
        lines, n_struct = structure.lines(P, i, hsr, model, st if model == 'four' else None, core=pos['core'])
        t1 = time.perf_counter()
        score = chart_score.compute(P, i)
        if model == 'houshou':
            hist = hs.history(P, i, P['d'].index(hsr['anchor']['date']) if hsr['anchor'] and hsr['anchor']['by'] == 'manual' else None)
            sig = {k: hsr[k] for k in ('phase', 'verdict', 'list', 'checks', 'missing', 'next_needs', 'note', 'anchor', 'avwap', 'sd', 'dist_pct',
                                       'pushes', 'abcd', 'zone', 'mid', 't1', 'rr', 'start_low', 'top', 'base')}
            sig.update(stop=None if pos['core'] else hsr['stop'], stop_note='核心仓不适用' if pos['core'] and hsr['stop'] is not None else '手动止损',
                       t2=None, t2_note='视频未说明', verdict_text=VERDICT_TEXT.get(hsr['verdict'], hsr['verdict']), params=hsr['params'],
                       est_note=hs.EST_NOTE)
            card = houshou_card(hsr, pos)
            overlay = None
            if hsr['anchor']:
                overlay = dict(anchor=hsr['anchor'], avwap=hs.avwap_series(P, hsr['anchor_index'], i), pushes=hsr['pushes'], abcd=hsr['abcd'],
                               zone=hsr['zone'], stop=sig['stop'], target=hsr['t1'], base=hsr['base'])
            name, version = hs.NAME, hs.VERSION
        else:
            st['card'] = __import__('narrate').card_from_state(st, panel.backtest_summary())
            sg = st['signal']
            sig = dict(phase='已触发' if st['armed'] else '未触发', verdict=st['conclusion']['title'], verdict_text=st['card']['verdict'], list='four',
                       checks=[dict(k=e['k'], name=e['name'], ok=bool(e['lit']), why=e['text']) for e in st['evidence']],
                       missing=list(st['conclusion']['missing']), next_needs=[], note=st['conclusion']['text'],
                       anchor=dict(date=st['levels']['anchor_date'], by='auto', note='地量日') if st['levels']['anchor_date'] else None,
                       zone=st['card']['entry_zone'], stop=hs.r2(sg['stop']), stop_note='规则止损', t1=hs.r2(sg['target']) if sg['target_usable'] else None,
                       t2=None, t2_note='—', rr=sg['rr'])
            hist = dict(n=len(st['signals']), rows=[], note='四证的历史信号见下方「历史信号」')
            card, overlay, name, version = four_card(st), None, '四证·抄底 v1.0', 'four-1.0'
        t2 = time.perf_counter()
        leg = legend(model, hsr, lines, pos['core'], st if model == 'four' else None)
        ms = lambda a, b: max(1, round((b - a) * 1000))
        steps = [dict(name='识别图表结构', ms=ms(t0, t1), note=f'{n_struct} 条结构线'),
                 dict(name='计算规则信号', ms=ms(t1, t2), note=sig['verdict_text']),
                 dict(name='在图上划线', ms=None, note=f'共 {len(lines)} 条，逐条画出'),
                 dict(name='AI 深度解读', ms=None, note='')]
        return dict(ok=True, ticker=t, asof=st['asof'], index=i, is_latest=st['is_latest'], price=hs.r2(st['close']), model=version, model_key=model, model_name=name,
                    models=[dict(key=k, name=n) for k, n in MODELS], steps=steps, score=score, signal=sig, card=card, lines=lines,
                    overlay=overlay, history=hist, legend=leg, position=pos, explain=EXPLAIN, banner=BANNER,
                    direction=dict(long=True, short=False, short_note='没有做空规则'), timeframe='日线')


# ---------- template narration for the 后手 model (no API) ----------

def _draw_level(price, label):
    return dict(type='level', price=price, label=label)


def template(q):
    """The three questions of the 后手 model for the current phase, in the same card format as the four-evidence narration."""
    s = q['signal']
    ck = {c['k']: c for c in s['checks']}
    steps = []

    def step(question, c, say_ok, say_no, st_ok, st_no, good_when_ok, draw):
        ok = c['ok']
        steps.append(dict(q=question, look=c['why'], say=say_ok if ok else say_no, sticker=st_ok if ok else st_no,
                          tone=('good' if ok else 'bad') if good_when_ok else ('bad' if ok else 'good'), evidence=0, ok=bool(ok), draw=[d for d in draw if d]))

    cost = _draw_level(s['avwap'], '成本线') if s.get('avwap') else None
    if s['phase'] == '拉升中':
        ps = s['pushes']
        top = ps[-1] if ps else None
        step('离成本多远？', ck['A1'], '离成本线太远了', '离成本线还不算远', '不追！', '还能看', False,
             [cost, dict(type='point', date=q['asof'], price=q['price'], label='现价')])
        step('第几冲、兵还跟不跟？', ck['A2'], '第三冲了，兵越冲越少', '兵还跟得上，或者还没到第三冲', '不追！', '还能看', False,
             [dict(type='point', date=p['date'], price=p['price'], label=f'第{p["n"]}冲') for p in ps[-3:]] + [dict(type='volume', dates=[p['date'] for p in ps[-3:]], label='每一冲的量')])
        step('天量是抢筹还是出货？', ck['A3'], '天量加长上影，是出货', '没有天量长上影', '出货区', '还能看', False,
             [dict(type='point', date=top['date'], price=top['price'], label='最高那根'), dict(type='volume', dates=[top['date']], label='这天的量')] if top else [])
        hook = {'不追·出货区': '三项全中，别追', '不追': '离成本太远，别追', '出货区': '第三冲见天量，小心', '还能看': '还在冲，没到不追的份上'}[s['verdict']]
        story = f'从 {s["anchor"]["date"][5:]} 的成本锚点起涨，已经第 {len(ps)} 冲'
        final = s['verdict_text']
    elif s['phase'] == '回落中':
        ab = s['abcd']
        path = [ab[k] for k in ('A', 'B', 'C', 'D') if ab.get(k)]
        step('回到成本线没有？', ck['B1'], '跌回成本线了', '还没回到成本线', '到位了', '等', True,
             [cost, dict(type='point', date=ab['D']['date'], price=ab['D']['price'], label='D') if ab.get('D') else None])
        step('两段跌得一样长吗？', ck['B2'], '两段差不多长', '两段还不一样长', '到位了', '等', True,
             [dict(type='path', points=[dict(date=p['date'], price=p['price']) for p in path], label='两段回落')] if len(path) >= 2 else [])
        step('缩量刺破收回了吗？', ck['B3'], '缩量刺破又收回，有人接', '还没有缩量刺破收回', '有人接', '等', True,
             [cost, dict(type='volume', dates=[q['asof']], label='今天的量')])
        n = sum(c['ok'] for c in s['checks'])
        hook = '三项齐了（未回测）' if n == 3 else f'后手清单 {n}/3，等'
        story = f'{ab["A"]["date"][5:]} 第三冲见顶 {ab["A"]["price"]}，之后往成本线回落'
        final = '下后手（未回测）' if n == 3 else '条件没齐，等'
    else:
        hook = '这套清单今天用不上' if s['phase'] == '无结构' else '这个结构作废了'
        story = s['note'] or '没有找到三冲结构'
        steps.append(dict(q='这套规则用得上吗？', look=s['note'], say='没有三冲，清单用不上' if s['phase'] == '无结构' else '触发过又跌破止损', sticker='不适用', tone='neutral',
                          evidence=0, ok=False, draw=[dict(type='point', date=p['date'], price=p['price'], label=f'第{p["n"]}冲') for p in s.get('pushes') or []]))
        if s.get('avwap'):
            far = s['dist_pct']
            steps.append(dict(q='离成本线多远？', look=f'成本线 {s["avwap"]}，现价离它 {far}%', say='在成本线上方' if far > 0 else '在成本线下方', sticker='仅参考', tone='neutral',
                              evidence=0, ok=False, draw=[cost, dict(type='point', date=q['asof'], price=q['price'], label='现价')]))
        final = '清单不适用，只看图'
    sc = q['score']
    steps.append(dict(q='图表现状', look='；'.join(f'{p["name"]} {p["v"]:+d}（{p["why"]}）' for p in sc['parts']), say=f'表盘 {sc["total"]:+d}，{sc["label"]}', sticker=sc['label'],
                      tone='good' if sc['total'] > 20 else 'bad' if sc['total'] < -20 else 'neutral', evidence=0, ok=False, draw=[]))
    return dict(hook=hook, story=story, steps=steps, final=final, watch=list(s['next_needs'])[:3])


def facts_for_ai(q):
    """What Claude is told about the panel: the score, the selected model's checklist result and the structure levels. Numbers only from here."""
    s = q['signal']
    keep = ('phase', 'verdict', 'verdict_text', 'checks', 'missing', 'next_needs', 'note', 'anchor', 'avwap', 'dist_pct', 'pushes', 'abcd', 'zone', 'stop',
            'stop_note', 't1', 'rr')
    return dict(selected_model=q['model_name'], model_backtested=False if q['model_key'] == 'houshou' else '证据不足',
                chart_score=dict(total=q['score']['total'], label=q['score']['label'], parts=q['score']['parts']),
                rule_signal={k: s[k] for k in keep if k in s},
                structure_lines=[{k: x[k] for k in ('label', 'price', 'p1', 'p2') if k in x} for x in q['lines']],
                history_triggers=q['history']['n'], history_stats=q['history'].get('stats'))
