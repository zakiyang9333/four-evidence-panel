"""「一键解释」学习面板的内容（zaki 2026-11-16：系统对普通投资者有点难懂，要一个 8 岁小孩也能看懂的解释，但笔风是成年人的）。

写法：每张卡片先用一两句大白话讲“这是什么”，再讲“今天它是什么情况”。短句，生活里的比方，不用没解释过的术语，不装可爱。
内容全部来自规则代码已经算好的结果（panel.state_at、narrate.build_facts、quant.result），这里只负责把它讲成人话：
不算任何规则，不调用 API，不花钱。不给买卖建议。
"""
import numpy as np

import engine as E
import narrate
import panel
import quant

P, F = E.VIDEO, E.FIXED


def _vol(x):
    return f"{x['yi']} 亿股" if x['shares'] >= 1e8 else f"{x['wan']} 万股"


def _card(cid, title, body, now=None, note=None, spot=None, ok=None, items=None):
    return dict(id=cid, title=title, body=body, now=now, note=note, spot=spot, ok=ok, items=items or [])


ASK = dict(A1='离成本线是不是太远了？', A2='是不是第三次冲、人还越来越少？', A3='最高那天是不是天量加长上影？',
           B1='跌回成本线附近了吗？', B2='两段下跌差不多长吗？', B3='缩量刺破后收回来了吗？')


def _four(st, f):
    """抄底核心四要素：先跌够，再看四个条件。"""
    out = []
    dd = int(P['dd'] * 100)
    out.append(_card(
        'armed', '这套规则什么时候才开始看？',
        f'先得跌得够多。好比商场打到八折以下才值得去看一眼：从最近一年的最高点算起，至少跌掉 {dd}%，系统才开始找“底”。没跌够，后面四个条件成不成立都不算数。',
        f"最高点是 {st['high']['date']} 的 {narrate.r2(st['high']['price'])}，之后最深跌到 {narrate.r2(st['low']['price'])}（{st['low']['date']}），跌了 {st['drawdown_low']}%。" +
        ('够了，系统在找底。' if st['armed'] else f'还不到 {dd}%，系统今天不找底。'), spot='highlow', ok=bool(st['armed'])))
    tail = '' if st['armed'] else f'不过还没跌够 {dd}%，这一条先不算数。'
    e1, e2, e3, e4 = f['e1'], f['e2'], f['e3'], f['e4']

    if e1['ok']:
        now = f"成立。{e1['anchor_date']} 那天的成交量是 {e1['window_days']} 天里最小的。" + tail
    elif not e1['enough_bars']:
        now = f"现在比不了：K 线还不够 {e1['window_days']} 根。"
    else:
        now = f"没成立。今天换手 {_vol(e1['volume'])}，比 {e1['window_days']} 天里最少的那天（{_vol(e1['min_in_window'])}）还多 {round(e1['more_than_min_pct'])}%：想卖的人还没卖完。"
    out.append(_card('e1', '第 1 个条件：地量见底',
                     f"意思是“想卖的人卖得差不多了”。菜市场快收摊时，吆喝声会越来越小。成交量缩到最近 {e1['window_days']} 天里最小，说明急着卖的人基本走光了。图下面蓝色的柱子就是这种日子。",
                     now, spot='ev0', ok=bool(e1['ok'])))

    if e2['prior_deepest_hist'] is None:
        now = '现在比不了：最高点和最低点离得太近，前后没法比。'
    elif e2['ok']:
        now = f"成立。{e2['low_date']} 最低点那天，力气柱是 {e2['macd_hist_at_low']}，比之前最深的 {e2['prior_deepest_hist']} 短。" + tail
    else:
        now = f"没成立。{e2['low_date']} 最低点那天，力气柱是 {e2['macd_hist_at_low']}，比之前最深的 {e2['prior_deepest_hist']} 还长：往下的力气还在加大。"
    out.append(_card('e2', '第 2 个条件：底背离',
                     '价格又创了新低，但往下的力气没有跟着创新低。像一个往坡下滚的球：位置更低了，速度却慢了下来。它只是一个提醒，不代表已经到底。',
                     now, spot='ev1', ok=bool(e2['ok'])))

    if e3['fan_mid'] is None:
        now = '今天就是最低点，扇子还画不出来。'
    elif e3['ok']:
        now = f"成立。收盘 {e3['close']}，站在扇子中线 {e3['fan_mid']} 上面。" + tail
    else:
        now = f"没成立。收盘 {e3['close']}，还在扇子中线 {e3['fan_mid']} 下面：下坡还没变缓。"
    out.append(_card('e3', '第 3 个条件：跌速放缓',
                     '从最高点到最低点连一条线，就是这段下跌的“坡度”。图上那把青色的扇子，中间那根是“坡度减半”的线。收盘价站到它上面，说明下坡变缓了，像滑梯从陡变平。',
                     now, spot='ev2', ok=bool(e3['ok'])))

    if e4['avwap'] is None:
        now = '还没有成本线：要先出现地量日，才知道从哪一天算起。'
    elif e4['ok']:
        now = f"成立。出现过放量的大阳线，收盘 {e4['close']} 在成本线 {e4['avwap']} 上面。" + tail
    elif e4['close_above_line']:
        now = f"差一步。收盘 {e4['close']} 已经在成本线 {e4['avwap']} 上面，但还没出现那根带着大成交量的阳线。"
    else:
        now = f"没成立。成本线在 {e4['avwap']}，收盘 {e4['close']} 还在它下面。"
    out.append(_card('e4', '第 4 个条件：站回成本线',
                     '图上的黄线叫“成本线”：从成交量最小的那天算起，大家买进来的平均价。价格在它下面，这段时间进场的人多数在亏钱；带着大成交量涨回它上面，说明有人愿意出更高的价钱接手。',
                     now, spot='ev3', ok=bool(e4['ok'])))

    c = st['conclusion']
    if not st['armed']:
        now = f"{c['title']}。跌幅没到 {dd}%，系统不找底，四个条件都不计分。"
    elif st['all4']:
        now = '四个条件同时成立。按这套规则，这算一个信号。'
    else:
        now = f"{st['score']} 个成立，还缺 {len(c['missing'])} 个（{'、'.join(c['missing'])}）。按这套规则：不动。"
    out.append(_card('verdict', '所以，今天的结论是什么？',
                     '四个条件要在同一天全部成立，才是这套规则说的“信号”。少一个都不算。',
                     now, note='就算四个全中，这套规则也没有被证明管用（见最上面那行黄字）。所以这里只说“条件齐了”，不说“该买”。', spot='sig', ok=bool(st['all4'])))

    sg = st['signal']
    stop, tgt = narrate.r2(sg['stop']), narrate.r2(sg['target'])
    now = f"止损在 {stop}，比现价低 {abs(sg['stop_pct'])}%。" if sg.get('stop_pct') is not None else ''
    if sg['target_usable']:
        now += f"目标在 {tgt}，比现价高 {sg['target_pct']}%。"
    else:
        now += '眼下没有可用的目标（前面的高点离现价太近，或者还没有）。'
    if sg['rr'] is not None:
        now += f"盈亏比 {sg['rr']} : 1，意思是：看错了亏 1 块，看对了大约赚 {sg['rr']} 块。"
    out.append(_card('levels', '止损、目标、盈亏比是什么？',
                     '止损：事先想好的认错价，跌到这里说明看错了，不再硬扛。目标：前面的一个高点，涨到那里先算走完一段。盈亏比：可能赚的那段距离，除以可能亏的那段距离。',
                     now, note='盈亏比只是两段距离的比，不是赢的可能性。', spot='tiles'))
    return out


def _houshou(q):
    """后手·成本线回踩：按阶段讲。"""
    s = q['signal']
    v = s['params']['video']
    out = [_card('h_idea', '“后手战法”在看什么？',
                 '它的想法是：不跟着追涨，等它涨完、跌回来再说。所以它盯三样东西：大家的平均成本在哪里，往上冲了几次，每次冲的时候跟着的人多不多。',
                 {'拉升中': '还在往上冲，所以看的是“该不该追”。', '回落中': '冲完了，正在往回跌，所以看的是“跌到位了没有”。',
                  '已失效': '这一轮的条件曾经齐过，后来跌破了止损，这个结构作废了。'}.get(s['phase'], '没有找到它要的那种走势，这套清单用不上。'))]
    if s.get('anchor'):
        up = s['dist_pct'] >= 0
        out.append(_card('h_cost', '黄线（成本线）和蓝色竖条（成本锚点）',
                         '黄线是成本线：从蓝色竖条那天起，所有人买进来的平均价。价格离它越远，掉回来的路就越长。蓝色竖条叫成本锚点，程序会自己去找“横着走了很久、然后起涨”的第一天；找得不对，可以在图上点右键自己定。',
                         f"成本线在 {s['avwap']}，收盘比它{'高' if up else '低'} {abs(s['dist_pct'])}%。锚点是 {s['anchor']['date']}（{'你手动定的' if s['anchor']['by'] == 'manual' else '程序自己找的'}）。",
                         note='程序找锚点的办法是估出来的，视频里没有给具体算法。', spot='chart'))
    ps = s.get('pushes') or []
    if ps:
        three = [p for p in ps if p.get('slot')]
        now = f'这一轮目前数到第 {len(ps)} 冲。'
        if three:
            now += '最近三冲的兵力，以第一冲为 100%：' + ' → '.join(f"{p['force_pct']}%" for p in three) + '。'
        out.append(_card('h_push', '“冲”和“兵力”是什么？',
                         '每创一次新高、再回落一截，算一“冲”，图上用带数字的紫色气泡标出来。“兵力”是这一冲上涨途中平均每天的成交量。一冲比一冲少，就是价格还在涨、跟着冲的人却越来越少。',
                         now, spot='chart'))
    items = [dict(name=ASK.get(c['k'], c['name']), ok=bool(c['ok']), text=c['why'] + '。') for c in s['checks']]
    if s['list'] == 'chase':
        out.append(_card('h_chase', '不追清单：正在往上冲时看',
                         f"三个问题。离成本线是不是太远（超过 {int(v['far'] * 100)}%）？是不是已经冲到第三次，而且跟的人一次比一次少？最高那天是不是成交量特别大，却被打回来、留下一根长长的上影线？答“是”的越多，越不该追。",
                         f"{sum(c['ok'] for c in s['checks'])} 个“是”。", spot='bar', ok=any(c['ok'] for c in s['checks']), items=items))
    elif s['list'] == 'houshou':
        n = sum(c['ok'] for c in s['checks'])
        out.append(_card('h_back', '后手清单：涨完跌回来时看',
                         '三个问题。跌回成本线附近了吗？两段下跌是不是差不多长（说明跌得有节奏，不是失控）？有没有这样一天：成交量很小，盘中跌破成本线，收盘又站了回来（没人肯卖了，还有人接）？三个都“是”，这套规则才说“条件齐了”。',
                         f'{n} 个“是”。' + ('三个都齐了。' if n == 3 else '还没齐。'), spot='bar', ok=n == 3, items=items))
    else:
        out.append(_card('h_none', '为什么今天说“清单用不上”？',
                         '这套清单只认一种走势：连冲三次，再跌回来。现在的走势不是这个样子，所以它既打不了勾，也打不了叉。',
                         (s.get('note') or '没有找到三冲结构。'), note='用不上不等于安全，也不等于没机会。只是这把尺子量不了今天。', spot='bar'))
    if s.get('zone'):
        now = f"建仓区 {s['zone'][0]} 到 {s['zone'][1]}（成本线上下 1%）。目标 {s['t1']}，就是第三冲的最高点。"
        now += '你把它当核心仓拿着，核心仓不用价格止损，所以止损那一格是空的。' if s['stop'] is None else f"止损 {s['stop']}，在这轮最低点下面 {int(v['stop'] * 100)}%。盈亏比 {s['rr']} : 1。"
        out.append(_card('h_levels', '建仓区、止损、目标', '三项都“是”的时候，面板才把这几个价位摆出来：打算在哪一带买、错了在哪里认、对了先看到哪里。券商只有限价单，止损要自己手动执行。',
                         now, note='第二目标视频里没说怎么算，所以那一格空着。', spot='tiles'))
    h = q['history']
    st = h.get('stats') or {}
    now = f"在这只票的日线上，三项同时成立的日子一共 {h['n']} 天。"
    if st.get('fall'):
        now += f"往回跌的 {st['fall']} 天里：跌回成本线 {st['B1']} 天，两段等长 {st['B2']} 天，缩量刺破收回 {st['B3']} 天。"
    out.append(_card('h_hist', '这套规则以前灵不灵？', '不知道。它还没有拿历史行情演习过（这叫“回测”）。下面的次数只是告诉你它多久才出现一次，不代表出现了就会赚。', now,
                     note='参数里只有 4 个数是视频里说的，其余都是我们估的，面板“模型参数”里一条条列着。', spot='hist'))
    return out


def build(t, model='four', asof=None):
    st = panel.state_at(t, asof or None)
    f = narrate.build_facts(t, st['asof'])
    q = quant.result(t, model if model in ('four', 'houshou') else 'four', st['asof'])
    bt = panel.backtest_summary()
    B = panel.truncate(panel.load(t)['B'], st['index'])
    hist = float(E.compute(B)['hist'][st['index']])
    up = st['chg_pct'] >= 0
    replay = not st['is_latest']
    dd = int(P['dd'] * 100)

    # 一句话
    s = q['signal']
    if model == 'houshou':
        if s['list'] == 'houshou':
            n = sum(c['ok'] for c in s['checks'])
            head = dict(tone='go' if n == 3 else 'wait', text='后手清单三项都“是”：条件齐了（这套规则没演习过）' if n == 3 else f'冲完了，正在往回跌。后手清单 {n} 个“是”，还要等',
                        sub='“条件齐了”只是清单的结果，不是让你买。' if n == 3 else '还缺：' + '、'.join(c['name'] for c in s['checks'] if not c['ok']) + '。')
        elif s['list'] == 'chase':
            bad = [c['name'] for c in s['checks'] if c['ok']]
            head = dict(tone='stop' if bad else 'wait', text='还在往上冲。按这套规则：不追' if '不追' in s['verdict'] else '还在往上冲，不追清单暂时没亮',
                        sub=('亮了的：' + '、'.join(bad) + '。') if bad else '三个“别追”的理由今天都不成立，但这不等于该追。')
        else:
            head = dict(tone='na', text='后手战法这套清单，今天用不上', sub='它要先看到“连冲三次再跌回来”的走势，现在没有。用不上不等于安全，也不等于没机会。')
    elif not st['armed']:
        head = dict(tone='na', text='还没到“找底”的时候', sub=f"从高点最多只跌了 {st['drawdown_low']}%，这套规则要跌够 {dd}% 才开始看。")
    elif st['all4']:
        head = dict(tone='go', text='四个条件今天都成立：条件齐了', sub='按这套规则这算一个信号。但规则本身没被证明管用，所以只说“条件齐了”，不说“该买”。')
    else:
        head = dict(tone='wait', text=f"四个条件只成立了 {st['score']} 个。按规则：不动", sub='还缺：' + '、'.join(st['conclusion']['missing']) + '。')

    cards = [
        _card('what', '这个面板是干什么的？',
              '它把“什么时候才算跌到位”的几套规则写成了程序，每天收盘后自动对一遍，把结果摆给你看。它不替你下单，也不告诉你该买还是该卖。',
              f"现在看的是 {t}，用的是 {st['asof']} 收盘后的数据。" + ('你正在回放历史：这一天之后发生的事，它一概不知道。' if replay else ''), spot='top'),
        _card('banner', '最上面那行黄字，为什么一直挂着？',
              f"因为这些规则没有被证明管用。“回测”就是拿过去的行情演习一遍。四要素这套规则演习下来一共出手 {bt['n']} 次，平均每次赚到的是所冒风险的 {bt['mean_r']} 倍；"
              f"而大跌之后闭着眼睛随便挑一天买，平均也有 {bt['control_mean_r']} 倍。差距不够大，分不清是规则有用，还是运气好。",
              '所以每个结论旁边都写着“仅观察”。后手战法连演习都还没做过。', spot='banner'),
        _card('candles', '这张图怎么看？',
              '每一根小柱子是一天。红色是这天涨了，绿色是跌了。柱子粗的部分，是开盘到收盘走了多远；上下的细线，是这天到过的最高和最低。',
              f"最后一根是 {st['asof']}：收在 {narrate.r2(st['close'])}，比前一天{'涨' if up else '跌'}了 {abs(st['chg_pct'])}%。", spot='chart'),
        _card('volume', '图下面第一排柱子是什么？',
              f"成交量：这一天一共换手了多少股。柱子高，是买卖的人多、看法分歧大；柱子矮，是大家都不太想动。蓝色的柱子，是最近 {f['e1']['window_days']} 天里成交最少的日子。",
              f"换手 {_vol(f['e1']['volume'])}。", spot='vol'),
        _card('macd', '第二排柱子（MACD）是什么？',
              '可以把它当成一块“力气表”。柱子在中线上方，是往上的力气占上风；在下方，是往下的力气占上风；柱子越长，力气越大。它只是把价格走得快慢换了一种画法，并不会提前知道明天。',
              f"柱子在中线{'上' if hist >= 0 else '下'}方（{narrate.r2(hist)}），往{'上' if hist >= 0 else '下'}的力气占上风。", spot='macd'),
    ]
    cards += _houshou(q) if model == 'houshou' else _four(st, f)

    sc = q['score']
    worst = min(sc['parts'], key=lambda p: p['v'])
    best = max(sc['parts'], key=lambda p: p['v'])
    now = f"{sc['total']} 分，{sc['label']}。"
    if worst['v'] < 0:
        now += f"拖分最多的是“{worst['name']}”（{worst['why']}）。"
    if best['v'] > 0:
        now += f"加分最多的是“{best['name']}”（{best['why']}）。"
    cards.append(_card('gauge', '那个表盘是什么？',
                       '像一张体检表，给现在这张图打个分：−100 最弱，+100 最强。它看五样。方向，叫趋势。最近涨跌有多快，叫动量。成交量是变多还是变少，叫量能。每天晃得厉不厉害，叫波动。高点和低点是在抬高还是降低，叫结构。',
                       now, note='它只描述现在的样子，不预测明天，也和上面的清单没有关系：表盘偏弱、清单却说“条件齐了”，是可能同时出现的。打分公式是我们自己估的。', spot='gauge'))
    res = next((x for x in q['lines'] if x['id'] == 'res'), None)
    sup = next((x for x in q['lines'] if x['id'] == 'sup'), None)
    if res or sup:
        now = ''
        if res:
            now += f"现价上方，被反复碰到最多的位置是 {res['price']}（{res['label'].replace('压力·', '碰过 ')}）。"
        if sup:
            now += f"下方是 {sup['price']}（{sup['label'].replace('支撑·', '碰过 ')}）。"
        cards.append(_card('lines', '图上那些横线和斜线是什么？',
                           '点了“AI 分析当前图表”之后，图上会画出几种线。红色横线是压力，绿色横线是支撑：价格在这个位置来回碰过很多次，像天花板和地板。斜线是趋势线：把最近两个高点（或两个低点）连起来往右延长。灰色细线是回撤刻度：把这一轮上涨切成几段，看现在退回到了哪一段。',
                           now, note='这些线只是把过去的价格位置标出来，价格没有义务在线上停住。', spot='chart'))
    cards.append(_card('ai', '“AI 深度解读”是什么？',
                       '把上面这些结果交给 Claude，让它像解说员一样把今天的图讲一遍。它可以讲规则没覆盖到的东西，也会在规则跟不上走势的时候直接说出来；但规则算出来的结论，它改不了。',
                       '模板版不花钱。让 Claude 讲要付一点接口费用，同一天、同一张图只收一次，之后再看都是保存好的那一版。', spot='narr'))
    cards.append(_card('live', '最右边那根颜色很淡的蜡烛是什么？',
                       '开盘时间里，它是今天还没走完的行情。颜色淡，是因为它还会变。这个面板的所有判断只认收盘后的数据，这一根不算数。', None, spot='chart'))
    cards.append(_card('not', '这个面板不做什么？',
                       '不连券商，不下单，不保证赚钱。它回答的是“规则今天怎么说”，不是“你今天该怎么做”。真要做决定，它只是其中一条参考。', None))

    glossary = [
        ['K 线', '一根柱子代表一天，画出这天的开盘、收盘、最高、最低四个价。'],
        ['收盘价', '一天交易结束时的最后一个价格。这个面板只认它。'],
        ['成交量', '这一天一共有多少股换了手。'],
        ['地量', '最近一段时间里成交最少的一天：想卖的人差不多卖完了。'],
        ['MACD', '把价格涨跌的快慢画成柱子的一种指标，可以当“力气表”看。'],
        ['背离', '价格创了新低，力气却没有创新低。两者不同步。'],
        ['成本线', '从某一天起，所有人买进来的平均价（按成交量加权）。英文叫锚定 VWAP。'],
        ['扇子', '从最高点出发画的几条斜线，用来量下跌的坡度有没有变缓。'],
        ['止损', '事先定好的认错价。'],
        ['盈亏比', '可能赚的距离除以可能亏的距离。'],
        ['回测', '拿过去的行情把规则演习一遍，看它以前表现如何。'],
        ['回放', '把图退回到过去某一天，看当时规则会怎么说。那天之后的数据一律不用。'],
        ['支撑 / 压力', '价格反复碰到又弹回去的位置：在下面的叫支撑，在上面的叫压力。'],
        ['ATR', '最近平均每天上下晃动的幅度。'],
        ['均线（MA20、MA60）', '最近 20 天、60 天收盘价的平均数，用来看大方向。'],
    ]
    return dict(ok=True, ticker=t, asof=st['asof'], model_key=q['model_key'], model_name=q['model_name'], replay=replay, headline=head, cards=cards,
                glossary=glossary, footer='以上解释由程序按当天的计算结果自动拼出来，不调用 AI，不花钱。仅供学习，不构成买卖依据。')
