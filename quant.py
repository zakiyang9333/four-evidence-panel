"""「AI 量化」的后端拼装：/api/quant 返回的那一份 JSON。整套系统的主干在这里。

一次分析 = 四步。分析页、对话、模型页、任务页、量化终端看到的都是这同一个结果，不各算各的：
  1. 识别图表结构   structure.py                 支撑/压力、趋势线、斐波那契。描述这张图，和方向无关。
  2. 计算规则信号   MODELS 里选一个               四证（engine.py，不许改）、后手（houshou.py）、破位反抽（breakout.py）
  3. 在图上划线     结构线 + 交易计划线           建仓区上下沿、止损、第一目标、第二目标：三个模型同一种画法
  4. AI 深度解读    narrate.py / ai_explain.py   模板免费；Claude 计费，同一盘面只算一次

五个输入，界面上每个按钮对应一个：
  模型      four | houshou | breakout
  方向      long（做多）| short（做空）。模型没有那一侧的规则时，如实说“用不上”，不硬凑。
  周期      20 | 60 | 120 根：表盘回看多远、结构线回看多远、历史触发往后看多少根。
  持仓      auto（跟随账户，只读）| flat | long | short（后三个是假设，只影响说明文字和交给 AI 的上下文）
  K 线级别  D（日K）| W（周K，由日线合成；四证只按日线判定）

每个模型都交出同一种形状的信号：state（ready 条件齐 / wait 等 / avoid 不追 / na 用不上 / dead 已失效）、清单 checks、
计划 zone/mid/stop/t1/t2/rr。表盘和规则信号是两套独立的东西：表盘描述图表现状，信号是所选模型的清单结果，两者可以不一致。
这里不算规则，只拼装。
"""
import datetime
import json
import os
import threading
import time

import breakout as bo
import chart_score
import qmodel as qm
import m_bubao, m_ertan, m_feidao, m_genzhuang, m_huiben, m_huitou, m_sanfen, m_sanjiao, m_shui, m_yindie   # noqa: E401
import houshou as hs
import panel
import portfolio
import structure

MODELS = (
    dict(key='four', name='四证·抄底 v1.0', version='four-1.0', sides=('long',), tfs=('D',), tested='回测证据不足', origin='录屏里叫「防接飞刀」', group='抄底', kind='trade', default_side='long',
         what='跌够两成之后找底。地量、底背离、跌速放缓、站回成本线，四项在同一根 K 线上同时成立才算信号。',
         checks=['地量见底', '底背离出现', '跌速放缓', '站回成本线'], no_short='四证是抄底规则，只定义了做多一侧：什么时候可以接。做空一侧它什么也不说。',
         no_week='四证只按日线判定，周 K 上不出结论。'),
    dict(key='houshou', name=hs.NAME, version=hs.VERSION, sides=('long', 'short'), tfs=('D', 'W'), tested='未回测', origin='录屏里的「后手·成本线回踩」', group='突破 · 回踩', kind='trade', default_side='long',
         what='不追，等价格回到成本线。三冲之后两段等长的回落、缩量刺破成本线又收回，三项齐了才算。做空一侧是把同一套规则上下翻过来，录屏里没讲。',
         checks=['回到成本线', 'AB=CD', '缩量刺破收回']),
    dict(key='breakout', name=bo.NAME, version=bo.VERSION, sides=('short', 'long'), tfs=('D', 'W'), tested='未回测', group='破位 · 出货', kind='trade', default_side='short',
         origin='录屏「平顶 / 平底 · 卧底战法」里面板上的「破位反抽 3.1」；照那一段的三条要点重写',
         what='跌破一个被踩过多次的支撑位（看收盘，破线那根放量过前 5 根均量 1.5 倍）之后不追，等它弹回破位处、反抽量缩到破线日一半以内、受阻，三项齐了才算。做多一侧是突破回踩。',
         checks=['有效破位', '反抽到位', '缩量受阻']))


def _gen(mod, group, origin, what, checks, sides=('long', 'short'), tfs=('D', 'W')):
    """A registry entry for a model file built on qmodel.py."""
    return dict(key=mod.KEY, name=mod.NAME, version=mod.VERSION, sides=tuple(sides), tfs=tuple(tfs), tested='未回测', group=group, origin=origin, what=what, checks=list(checks), mod=mod,
                kind=getattr(mod, 'KIND', 'trade'), default_side=getattr(mod, 'DEFAULT_SIDE', 'long'), default_hz=getattr(mod, 'DEFAULT_HZ', 20))


MODELS += (
    _gen(m_ertan, '抄底', '录屏「二探不破战法」里面板上的「等二探 v2.1」',
         '大跌后的第一次反弹不追，等它第二次往下探：没破前低、成交量不到前低那天的四成、刺破布林下轨当天收回，三项齐了才算。做空一侧是同一套规则上下翻过来，录屏里没讲。',
         ['二探不破前低', '量缩到四成以内', '刺破下轨收回']),
    _gen(m_feidao, '抄底', '录屏「三驱抄底战法」里面板上的「不接飞刀 v1.3」',
         '连砸三下、每一下都创新低才看：第三下落在扩展 0.5～0.618，价格新低 RSI 不新低，刺破布林下轨又收回。RSI 还趴在 30 下面、贴着下轨口子还在张，都不抄。',
         ['第三下落在扩展 0.5～0.618', '价格新低 RSI 不新低', '收回下轨']),
    _gen(m_sanjiao, '突破 · 回踩', '录屏「三角不追战法」里面板上的「不追半山腰 v2.1」',
         '收敛三角里面不追（上沿、下沿、中间控制点都不碰）。收盘出了三角、突破放量 RSI 过 60、回踩上沿不掉回去，三项齐了才算；目标是三角开口那么高。',
         ['收在三角外', '放量，RSI 过 60', '回踩不进去']),
    _gen(m_sanfen, '突破 · 回踩', '录屏「反梭哈建仓论」里面板上的「三份法 测试07」',
         '钱分三份、一份只买一个位置：0.382 带长下影，0.618 和量山重合，放量收盘站上颈线。面板在第三份（放量站上颈线，头肩底确认）说条件齐了。',
         ['头肩底成形', '放量', '收盘站上颈线']),
    _gen(m_bubao, '破位 · 出货', '录屏「满仓走一遍 · 永不爆仓玩法」里面板上的「不爆仓 3 号」',
         '头肩顶：右肩没过 0.5、趋势还在往下，就分批做空，站回右肩上方离场。附一张加仓表：下单前算好最多亏多少，涨了才加、越加越少，加完止损挪，到目标就卖。',
         ['头肩成形', '右肩没过 0.5', '趋势还在往下']),
    _gen(m_genzhuang, '破位 · 出货', '录屏「跟庄技巧 2.0」里面板上的「跟庄3号」',
         '做多看五浪：四浪不碰一浪顶就跟庄拿，五浪到 0.618 扩展又放天量就跑，止损在一浪顶。做空看出货：头肩顶跌破颈线、反弹缩量、量山压在头顶，止损在右肩。',
         ['五浪 / 头肩顶', '四浪不碰一浪顶 / 反弹缩量', '没到扩展 / 量山压头']),
    _gen(m_huitou, '观察', '录屏「回头战法」里面板上的「等回头」',
         '一根远超 ATR 的大阴大阳之后，看价格回不回得到半山腰、收在成本线（锚定 VWAP）上还是下。线上看多，线下看空。只给观察结论，不给价位。',
         ['振幅远超 ATR', '回到半山腰', '收在成本线上']),
    _gen(m_yindie, '观察', '录屏「不抗单战法」里面板上的「阴跌雷达」',
         '高点逐级下移、反弹一碰均价线就缩回去、下行结构没破：三样都在就说“留意风险”。跌得越慢，套得越深。只给观察结论，不给价位。',
         ['高点逐级下移', '反弹受阻于均价线', '下行结构未破']),
    _gen(m_shui, '观察', '录屏「轻仓过夜战法」里面板上的「睡得着」',
         '假设手里有仓位、止损挂在前低下面：看止损离现价有没有一个 ATR、布林是不是收口、是不是周末前、以前的跳空会不会跳过止损。只给观察结论，不给价位。',
         ['止损在一个 ATR 外', '布林没收口', '不在周末前', '跳空小于止损距离']),
    _gen(m_huiben, '观察', '录屏「回本三看」的五条要点（那一段没打开面板）',
         '熬过一个头肩底终于回本时，看三样：收没收上颈线、在不在成本线上、回踩量缩一半颈线守没守住。到前高或 1.618 放量长上影就卖，收盘跌回颈线下就走。',
         ['收上颈线', '在成本线上面', '回踩量缩一半、不破颈线']),
)
ORDER = ('four', 'ertan', 'feidao', 'houshou', 'sanjiao', 'sanfen', 'breakout', 'bubao', 'genzhuang', 'huitou', 'yindie', 'shui', 'huiben')
MODELS = tuple(sorted(MODELS, key=lambda m: ORDER.index(m['key']) if m['key'] in ORDER else len(ORDER)))
MODEL = {m['key']: m for m in MODELS}
WATCH_SIDE = dict(long='上行', short='下行')


def side_name(M, side):
    """做多 / 做空 for trading models, 上行 / 下行 for the observation ones (as on the recorded panel)."""
    return (WATCH_SIDE if M.get('kind') == 'watch' else SIDE_NAME)[side]
SIDE_NAME = dict(long='做多', short='做空')
HORIZONS = {20: '短线', 60: '中线', 120: '长线'}
SR_WIN = {20: 250, 60: 500, 120: 750}                 # 结构线回看多少根【估算】
POS_MODES = ('auto', 'flat', 'long', 'short')
TF_NAME = dict(D='日K', W='周K')
ADJUST = '拆股已调整'                                  # 数据源只有这一种口径：拆股调整过，分红没有调整
ADJUST_SHORT = '拆股复权'                              # 窗口头部那个小药丸上的写法
BANNER = '四证：回测证据不足 ｜ 后手战法、破位反抽：尚未回测 ｜ 仅观察，不构成买卖依据'
EXPLAIN = ['表盘和信号卡是两套独立的东西：表盘描述图表现状，信号卡是所选模型的清单结果。两者可以一个偏空、一个说条件齐了。',
           '「量化 = 战法，对上了」不是独立验证：模型本来就是把那几条规则写成代码，必然一致。',
           '规则是写死的，市场不会照着清单走。清单显示「无结构」「不适用」时，就是这套规则今天用不上，不代表没有机会或没有风险。']
STATE_TEXT = dict(ready='条件齐', wait='等', avoid='不追', risk='留意风险', watch='继续观察', na='用不上', dead='已失效')
_lock = threading.RLock()
_P = {}


class BadParam(ValueError):
    """A value the panel doesn't know. The server answers 400 and names the parameter and what it can be:
    it never quietly runs another model, horizon, side, bar size or position instead."""

    def __init__(self, name, value, allowed=(), why=''):
        self.name, self.value, self.allowed = name, '' if value is None else str(value), [str(x) for x in allowed]
        super().__init__(f'参数 {name}={self.value or "（空）"} 不认识。' + (why or '') + ('可选：' + '、'.join(self.allowed) + '。' if self.allowed else ''))


def given(x):
    """Was this input actually sent? (missing and empty both mean “use the default”)."""
    return x is not None and str(x).strip() != ''


def norm(model=None, side=None, horizon=None, tf=None, posmode=None):
    """Check the five inputs. A missing one takes its default (side long, horizon 20, bar size D, position auto); a value that is sent
    but not known raises BadParam. The model is required here (the server fills in its default before calling)."""
    if model not in MODEL:
        raise BadParam('model', model, MODEL)
    if not given(side):
        side = 'long'
    elif side not in SIDE_NAME:
        raise BadParam('side', side, SIDE_NAME)
    if not given(horizon):
        horizon = 20
    else:
        try:
            n = int(str(horizon).strip())
        except ValueError:
            raise BadParam('hz', horizon, HORIZONS) from None
        if n not in HORIZONS:
            raise BadParam('hz', horizon, HORIZONS)
        horizon = n
    if not given(tf):
        tf = 'D'
    elif tf not in TF_NAME:
        raise BadParam('tf', tf, TF_NAME)
    if not given(posmode):
        posmode = 'auto'
    elif posmode not in POS_MODES:
        raise BadParam('pos', posmode, POS_MODES)
    return dict(model=model, side=side, horizon=horizon, tf=tf, posmode=posmode)


def variant(model, side='long', horizon=20, tf='D'):
    """A short name for one combination, used for saved readings. The two old ones keep their old names ('' and 'houshou')."""
    return '_'.join(([model] if model != 'four' else []) + (['short'] if side == 'short' else []) + ([f'h{horizon}'] if horizon != 20 else []) + (['W'] if tf == 'W' else []))


def horizon_label(n, tf='D'):
    return f'{HORIZONS[n]} · {n} {"周" if tf == "W" else "日"}'


def bars(t, tf='D'):
    return prepared(t, 'long', tf)[0]


def prepared(t, side='long', tf='D'):
    """Bars and the prepared causal pass for one ticker, direction and bar size; rebuilt when the data changes."""
    B = panel.load(t)['B']
    key = (len(B['d']), B['d'][-1], float(B['c'][-1]), float(B['v'][-1]))
    hit = _P.get((t, side, tf))
    if hit is None or hit[0] != key:
        if tf == 'W':
            wk = _P.get((t, 'long', 'W'))
            B = wk[1] if wk is not None and wk[0] == key else panel.weekly(B)
        hit = _P[(t, side, tf)] = (key, B, hs.prepare(B, side, '周均' if tf == 'W' else '日均'))
    return hit[1], hit[2]


def week_complete(date):
    """Is the week that ends on this bar finished? (No later trading session in the same ISO week.)"""
    day = datetime.date.fromisoformat(date)
    nxt = day + datetime.timedelta(days=1)
    while nxt.isocalendar()[:2] == day.isocalendar()[:2]:
        if panel.is_session(nxt):
            return False
        nxt += datetime.timedelta(days=1)
    return True


# ---------- manual cost anchor (data/houshou_anchor.json: {ticker[:short][:W]: date}) ----------

def anchor_path():
    return os.path.join(panel.data_dir(), 'houshou_anchor.json')


def akey(t, side='long', tf='D'):
    return t + (':short' if side == 'short' else '') + (':W' if tf == 'W' else '')


def anchors():
    try:
        with open(anchor_path(), encoding='utf-8') as f:
            x = json.load(f)
        return {k: v for k, v in x.items() if isinstance(v, str)} if isinstance(x, dict) else {}
    except (OSError, ValueError):
        return {}


def set_anchor(t, date, side='long', tf='D'):
    """date = a bar of this ticker (at this bar size), or None to go back to the automatic anchor."""
    if t not in panel.TICKERS:
        raise KeyError(t)
    a = norm('houshou', side, None, tf, None)          # 不认识的方向或 K 线级别：报错，不悄悄改成做多或日 K
    side, tf = a['side'], a['tf']
    cur = anchors()
    k = akey(t, side, tf)
    if date:
        if date not in bars(t, tf)['d']:
            raise ValueError('这一天不是这只标的的交易日' if tf == 'D' else '这一天不是一根周 K 的日期')
        cur[k] = date
    else:
        cur.pop(k, None)
    tmp = anchor_path() + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cur, f, ensure_ascii=False, indent=1)
    os.replace(tmp, anchor_path())
    return cur.get(k)


# ---------- position (read-only, for the 持仓 field and the core-position rule) ----------

def account_position(t):
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


def position(t, mode='auto'):
    """The 持仓 field. auto = what the account file says. flat / long / short = “suppose I …”: they change the wording and what the AI
    is told, nothing else. core always comes from the account: a core position never gets a price stop, whatever is supposed here."""
    acct = account_position(t)
    mode = mode if mode in POS_MODES else 'auto'
    if mode == 'auto':
        cur = dict(text=acct['text'], held=acct['held'], side='long' if acct['held'] else None, assumed=False)
    else:
        cur = dict(text=dict(flat='未持仓', long='持有多单', short='持有空单')[mode], held=mode != 'flat', side=None if mode == 'flat' else mode, assumed=True)
    cur.update(core=acct['core'], mode=mode, account=acct['text'],
               options=[dict(k='auto', label='跟随账户', sub=acct['text']), dict(k='flat', label='未持仓', sub='假设'),
                        dict(k='long', label='持有多单', sub='假设'), dict(k='short', label='持有空单', sub='假设')])
    return cur


def position_note(pos, side, state, sig, core):
    """One plain sentence for someone who holds (or supposes) a position. Describes; never tells them what to do."""
    if not pos['held']:
        return ''
    who = '账户里有' if not pos['assumed'] else '假设你有'
    mine, look = SIDE_NAME[pos['side']], SIDE_NAME[side]
    if pos['side'] == side:
        if core:
            return f'{who}这只标的的核心仓。核心仓按估值失效，没有价格止损，下面的止损位不适用。'
        if sig.get('stop') is not None:
            return f'{who}{mine[1]}单，看的也是{look}一侧：这套规则认错的位置是 {sig["stop"]:,.2f}（收盘越过它，这个结构就作废），第一目标 {sig["t1"]:,.2f}。'
        return f'{who}{mine[1]}单，看的也是{look}一侧：这套规则今天没有给出价位（{STATE_TEXT[state]}）。'
    if state == 'ready':
        return f'{who}{mine[1]}单，现在看的是{look}一侧，而且这一侧的条件齐了。对{mine[1]}单来说这是规则上的反向提示，不是平仓指令。'
    return f'{who}{mine[1]}单，现在看的是{look}一侧（{STATE_TEXT[state]}）。这一侧的条件没齐，对{mine[1]}单没有新的说法。'


# ---------- signal card (six cells) ----------

def _pct(x, price):
    return None if x is None or not price else round((x / price - 1) * 100, 2)


def fmt_p(x):
    """A price as the page writes it (same as fmtP() in app.js): two decimals from 1 up, four below 1."""
    return '—' if x is None else f'{x:,.2f}' if abs(x) >= 1 else f'{x:.4f}'


def _cells(price, zone, mid, stop, t1, rr, t2, t2_note='', core=False, entry_note='中值'):
    f = fmt_p
    sp = lambda x: '' if x is None else f'{x:+.2f}% · 距现价'
    return [dict(k='price', name='现价', v=f(price), sub='当前图表'),
            dict(k='zone', name='入场区间', v=f'{f(zone[0])} – {f(zone[1])}' if zone else '—', sub=f'{entry_note} {sp(_pct(mid, price))}' if zone and mid else '条件没齐，不给区间'),
            dict(k='stop', name='止损', v='核心仓不适用' if core else f(stop), sub='核心仓没有价格止损' if core else (sp(_pct(stop, price)) + ' · 手动止损' if stop is not None else ''), tone='stop'),
            dict(k='t1', name='第一目标', v=f(t1), sub=sp(_pct(t1, price)), tone='target'),
            dict(k='rr', name='盈亏比', v=f'{rr:.2f} : 1' if rr is not None and not core else '—', sub='按入场中值' if rr is not None and not core else ''),
            dict(k='t2', name='第二目标', v=f(t2), sub=(sp(_pct(t2, price)) + (' · ' + t2_note if t2_note else '')) if t2 is not None else t2_note, tone='target')]


HS_STATE = {'下后手': 'ready', '等': 'wait', '不追': 'avoid', '不追·出货区': 'avoid', '出货区': 'avoid', '还能看': 'wait', '不适用': 'na', '已失效': 'dead',
            hs.TOO_FINE: 'na'}
VERDICT_TEXT = {'下后手': '后手条件齐了（未回测）', '等': '等', '不追': '不追', '不追·出货区': '不追 · 出货区', '出货区': '出货区', '还能看': '还能看',
                '不适用': '这套清单用不上', '已失效': '结构已失效', hs.TOO_FINE: '价位太细，不给价位'}
VERDICT_TEXT_SHORT = {'下后手': '后手做空条件齐了（未回测）', '等': '等', '不追': '不追空', '不追·出货区': '不追空 · 接货区', '出货区': '接货区', '还能看': '还能看',
                      '不适用': '这套清单用不上', '已失效': '结构已失效', hs.TOO_FINE: '价位太细，不给价位'}
HS_PHASE_SHORT = {'拉升中': '下跌中', '回落中': '反弹中'}
BO_STATE = {'条件齐': 'ready', '等受阻': 'wait', '等反抽': 'wait', '不追': 'avoid', '等破位': 'wait', '不适用': 'na', '已失效': 'dead', hs.TOO_FINE: 'na'}
FOOT = '历史数据重放｜未回测｜仅供学习'


def _tags(side, hz, tf, extra=(), M=None):
    watch = bool(M and M.get('kind') == 'watch')
    return [side_name(M or {}, side), HORIZONS[hz] if watch else horizon_label(hz, tf), '引擎结果'] + list(extra)


def houshou_card(r, pos, side='long', hz=20, tf='D'):
    W = hs.WORDS[side]
    v, long = r['verdict'], side == 'long'
    back = '回落' if long else '反弹'
    if v == '下后手':
        text = f'价格回到成本线，两段{W["down"]}幅相当，缩量刺破后收回，后手清单三项同时成立。这套规则没有回测过，这里只是把清单结果摆出来。'
    elif v == hs.TOO_FINE:
        text = r['note']
    elif r['phase'] == '回落中':
        text = f'三{W["push"]}之后在{back}，后手清单 {sum(c["ok"] for c in r["checks"])}/3。' + ('还缺：' + '、'.join(c['name'] for c in r['checks'] if not c['ok']) + '。')
    elif r['phase'] == '拉升中':
        n = len(r['pushes'])
        far = r['dist_pct'] if long else -r['dist_pct']
        text = f'还在创新{W["higher"]}，已经第 {n} {W["push"]}，现价比成本线{W["higher"]} {far}%。' + \
               {'不追·出货区': f'离成本太远、第三{W["push"]}缩量、天量长{W["shadow"]}，三项全中。', '不追': '离成本线太远，按规则不追。',
                '出货区': f'第三{W["push"]}缩量又放天量长{W["shadow"]}，按规则是{"出货区" if long else "接货区"}。', '还能看': '不追清单的条件没有成立。'}[v]
    elif r['phase'] == '已失效':
        text = r['note']
    else:
        text = (r['note'] or f'没有找到三{W["push"]}结构。') + '这套清单今天用不上，不代表没有机会或没有风险。'
    if not long:
        text += '（做空一侧是把后手战法上下翻过来用，录屏里没有讲过。）'
    core = pos['core'] and long
    return dict(model=hs.NAME, verdict=(VERDICT_TEXT if long else VERDICT_TEXT_SHORT).get(v, v), code=v, state=HS_STATE.get(v, 'na'),
                tags=_tags(side, hz, tf, ['全部参数含估算'] + ([] if long else ['镜像规则'])), text=text,
                cells=_cells(r['close'], r['zone'], r['mid'], None if core else r['stop'], r['t1'], r['rr'], r['t2'], r['t2_note'] if r['zone'] else '条件没齐，不给目标',
                             core=core and r['zone'] is not None),
                footer=FOOT)


def breakout_card(r, pos, side='short', hz=20, tf='D'):
    W = bo.WORDS[side]
    v, lv = r['verdict'], r['level']
    far = abs(r['dist_pct']) if r['dist_pct'] is not None else None
    if v == '条件齐':
        text = f'{W["brk"]}之后{W["back"]}到了{W["brk"]}处，缩量、{W["hold"]}，清单三项同时成立。这套规则是按通用形态自己写的，没有回测过，这里只是把清单结果摆出来。'
    elif v == '等受阻':
        text = f'{W["back"]}已经到位，还差最后一项「{W["k3"]}」：' + r['checks'][2]['why'] + '。'
    elif v == '等反抽':
        text = f'{r["brk"]["date"]} {W["brk_v"]}了 {lv["price"]} 的{W["level"]}，现价离{W["brk"]}处 {far}%，还没有{W["back"]}到位。'
    elif v == '不追':
        text = f'{W["brk"]}之后已经走出去 {far}%，离{W["brk"]}处太远。按规则不追，等它{W["back"]}。'
    elif v == '等破位':
        text = f'离现价最近的{W["level"]}在 {lv["price"]}（被碰过 {lv["touches"]} 次），收盘还没有{W["brk_v"]}它。没有{W["brk"]}，就没有后面的{W["back"]}。'
    elif v in ('已失效', hs.TOO_FINE):
        text = r['note']
    else:
        text = r['note'] + '这套清单今天用不上，不代表没有机会或没有风险。'
    core = pos['core'] and side == 'long'
    return dict(model=bo.NAME + ('（做多：突破回踩）' if side == 'long' else ''), verdict=r['verdict_text'], code=v, state=BO_STATE.get(v, 'na'),
                tags=_tags(side, hz, tf, ['全部参数为估算']), text=text,
                cells=_cells(r['close'], r['zone'], r['mid'], None if core else r['stop'], r['t1'], r['rr'], r['t2'], r['t2_note'] if r['zone'] else '条件没齐，不给目标',
                             core=core and r['zone'] is not None),
                footer=FOOT)


FOUR_T2 = 0.5          # 四证的第二目标【估算】：这一轮跌幅的一半（和录屏里第二目标贴着 0.5 回撤刻度的位置对得上）


def generic_signal(M, B, P, i, side, hz, tf, pos, core):
    """One model module built on qmodel.py → the same signal / card / overlay / history the hand-written adapters give."""
    mod = M['mod']
    r = qm.compute(mod, B, i, side, P=P, with_history=False)
    hist = qm.history(P, mod.KEY, mod.core, i, hz)
    sig = {k: r[k] for k in ('phase', 'verdict', 'state', 'list', 'missing', 'next_needs', 'note', 'zone', 'mid', 't1', 't2', 'rr')}
    sig.update(checks=[{k: c[k] for k in ('k', 'name', 'ok', 'why')} for c in r['checks']],
               asks=[{k: c[k] for k in ('k', 'ask', 'yes', 'no', 'sticker_yes', 'sticker_no', 'good', 'draw', 'ok', 'why')} for c in r['checks']],
               verdict_text=r.get('verdict_text') or r['verdict'], phase_text=r.get('phase_text') or r['phase'], anchor=None,
               stop=None if core else r['stop'], stop_note='核心仓不适用' if core and r['stop'] is not None else '手动止损',
               t2_note=r['t2_note'] if r['zone'] else '条件没齐，不给目标', hook=r.get('hook'), story=r.get('story'),
               params=r['params'], est_note=getattr(mod, 'EST_NOTE', {}), video_note=getattr(mod, 'VIDEO_NOTE', {}))
    for k in getattr(mod, 'EXTRA', ()):          # 模型自己的几样事实（交给 AI 和模板用），例如前低、颈线、量山的位置
        if r.get(k) is not None:
            sig[k] = r[k]
    watch = M.get('kind') == 'watch'
    cells = [] if watch else (r.get('cells') or _cells(r['close'], r['zone'], r['mid'], None if core else r['stop'], r['t1'], r['rr'], r['t2'], sig['t2_note'], core=core and r['zone'] is not None))
    card = dict(model=mod.NAME + (f"（{mod.SIDE_NAME[side]}）" if getattr(mod, 'SIDE_NAME', None) and mod.SIDE_NAME.get(side) else ''), verdict=sig['verdict_text'], code=r['verdict'],
                state=r['state'], tags=_tags(side, hz, tf, list(getattr(mod, 'TAGS', ('参数含估算',))) + (['镜像规则'] if side in getattr(mod, 'MIRRORED', ()) else []), M),
                text=r['text'] or r['note'], cells=cells, footer=FOOT)
    overlay = dict(kind='shapes', side=side, shapes=r['shapes'], zone=r['zone'], stop=sig['stop'], target=r['t1'], target2=r['t2'], zone_from=r.get('zone_from')) if r['shapes'] or r['zone'] else None
    return sig, card, overlay, hist, r.get('legend') or []


def four_t2(st):
    """第二目标【估算】，面板加的参考位，不是引擎的规则：从最低点往上，收回这一轮跌幅（高点到低点）的一半。不比第一目标高就不设。"""
    sg = st['signal']
    if not sg.get('target_usable') or sg.get('target') is None:
        return None
    t2 = st['low']['price'] + FOUR_T2 * (st['high']['price'] - st['low']['price'])
    return hs.r2(t2) if t2 > sg['target'] else None


def four_card(st, hz=20, pos=None):
    """The six cells for the four-evidence model. Until all four are lit (state ready) every price cell is “—”: the engine still works out
    where the stop and the prior high would be, but those are structure levels, not a plan, and are not shown as one."""
    cd = st['card']
    ready, core = bool(st['all4']), bool(pos and pos['core'])
    zone = cd['entry_zone'] if ready else None
    t2 = four_t2(st) if zone else None
    return dict(model='四证·抄底 v1.0', verdict=cd['verdict'], code=cd['code'], state='ready' if ready else 'wait' if st['armed'] else 'na',
                tags=[cd['direction'], horizon_label(hz), '引擎结果'], text=st['conclusion']['text'],
                cells=_cells(cd['price'], zone, (zone[0] + zone[1]) / 2 if zone else None, None if core or not ready else cd['stop'], cd['target'] if ready else None,
                             cd['rr'] if ready else None, t2,
                             ('跌幅的一半【估算】' if t2 is not None else '跌幅的一半不比第一目标高，不设') if zone else '条件没齐，不给目标', core=core and zone is not None),
                footer=cd['footer'])


def na_card(M, side, hz, tf, price, why, hint):
    return dict(model=M['name'], verdict='这个模型用不上', code='不适用', state='na', tags=_tags(side, hz, tf), text=why + hint,
                cells=_cells(price, None, None, None, None, None, None, ''), footer=FOOT)


# ---------- plan lines: the same five for every model ----------

def plan_lines(sig, core, side):
    out = []
    if sig.get('zone'):
        out.append(dict(id='zone_hi', kind='level', group='model', label='建仓上沿', price=sig['zone'][1], style='zone'))
        out.append(dict(id='zone_lo', kind='level', group='model', label='建仓下沿', price=sig['zone'][0], style='zone'))
        if not core and sig.get('stop') is not None:        # 核心仓没有价格止损：这条线不画
            out.append(dict(id='stop', kind='level', group='model', label='止损（手动止损）', price=sig['stop'], style='stop'))
        if sig.get('t1') is not None:
            out.append(dict(id='t1', kind='level', group='model', label='第一目标', price=sig['t1'], style='target'))
        if sig.get('t2') is not None:
            out.append(dict(id='t2', kind='level', group='model', label='第二目标', price=sig['t2'], style='target2'))
    return out


# ---------- numbered legend: one plain sentence per kind of mark on the chart ----------

def legend(model, sig, lines, core, side='long', four=None, extra=None):
    out, seen = [], {}
    long = side == 'long'

    def add(key, text):
        if key not in seen:
            seen[key] = len(out) + 1
            out.append(dict(n=seen[key], key=key, text=text))

    for x in extra or []:             # 模型自己画的东西（图形清单里带 key 的那些），各配一句大白话
        add(x['key'], x['text'])

    if model == 'houshou' and sig.get('anchor'):
        by = '你手动定的' if sig['anchor']['by'] == 'manual' else '自动找的'
        add('anchor', f'蓝色竖条是成本锚点（{by}）：从这一天开始，算大家买进来的平均价。')
        add('avwap', '黄线是成本线：从锚点那天起，所有人买进来的平均价。价格离它越远，' + ('掉回来的路越长。' if long else '弹回来的路越长。'))
        add('band', '黄线两边的浅色带：大部分成交都落在这条带子里，价格跑出带子就算走远了。')
        if sig.get('pushes'):
            add('push', '带数字的气泡是一次次冲高。气泡里的百分比是这一冲的成交量相当于第一冲的多少：越冲越小，说明跟着冲的人少了。' if long else
                '带数字的气泡是一次次往下探。气泡里的百分比是这一探的成交量相当于第一探的多少：越探越小，说明跟着卖的人少了。')
        if sig.get('abcd') and sig['abcd'].get('B'):
            add('abcd', 'A、B、C、D 是回落的两段：A 到 B 是第一段，C 到 D 是第二段。两段跌得差不多长，才算跌到位。' if long else
                'A、B、C、D 是反弹的两段：A 到 B 是第一段，C 到 D 是第二段。两段弹得差不多高，才算弹到位。')
    if model == 'breakout' and sig.get('level'):
        add('bo_level', '橙色横线是破位处：原来的支撑位。跌破之后，它反过来变成压力，价格弹回来常在这里被挡住。' if not long else
            '橙色横线是突破处：原来的压力位。站上去之后，它反过来变成支撑，价格退回来常在这里被托住。')
        if sig.get('box'):
            add('bo_box', '浅色方框是' + ('破位' if not long else '突破') + '之前的箱体：价格在这一段里来回走。箱体有多高，第二目标就往外量多远。')
        if sig.get('brk'):
            add('bo_brk', ('带「破」字的圆点是破位那一根：收盘第一次明显跌到支撑位下面。' if not long else '带「破」字的圆点是突破那一根：收盘第一次明显站到压力位上面。') +
                ('「抽」是之后弹回来的最高点。' if not long else '「踩」是之后退回来的最低点。'))
    if sig.get('zone'):
        add('zone', '绿色带是建仓区：' + ('成本线上下 1%。' if model == 'houshou' else '破位处到它外侧 1.5%。' if model == 'breakout' else '成本线到它上方 2%。' if model == 'four' else '') + '清单没齐的时候不显示。')
        add('target', '粉色虚线是第一目标和第二目标（每个模型怎么算，写在“模型”页）。' if MODEL.get(model, {}).get('mod') else '粉色虚线是目标：第一目标是这一轮走到过的最远处，第二目标是再往外量一段（估算）。')
        if not core:
            add('stop', '紫色虚线是止损：收盘越过它，就是这套规则认错的位置。券商只有限价单，这条线要自己手动执行。')
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
                          else 'zone' if x['id'].startswith('zone') else 'target' if x['id'] in ('t1', 't2') else x['id'])
    return out


# ---------- the response ----------

def result(t, model='houshou', asof=None, side='long', horizon=20, tf='D', posmode='auto'):
    a = norm(model, side, horizon, tf, posmode)
    model, side, hz, tf, posmode = a['model'], a['side'], a['horizon'], a['tf'], a['posmode']
    M = MODEL[model]
    with _lock:
        t0 = time.perf_counter()
        if tf == 'D':
            st = panel.state_at(t, asof or None)
            i, asof_d, is_latest, price = st['index'], st['asof'], st['is_latest'], hs.r2(st['close'])
            B, PL = prepared(t, 'long', 'D')
        else:
            st = None
            if t not in panel.TICKERS:
                raise KeyError(t)
            B, PL = prepared(t, 'long', 'W')
            i = panel.index_at(B, asof or None)
            asof_d, is_latest, price = B['d'][i], i == len(B['d']) - 1, hs.r2(B['c'][i])
        pos = position(t, posmode)
        side_ok, tf_ok = side in M['sides'], tf in M['tfs']
        core = pos['core'] and side == 'long'
        hsr = hs.compute(B, i, anchors().get(akey(t, 'long', tf)), with_history=False, P=PL)       # 做多一侧的结构：斐波那契用它的起涨低点和最高点
        lines, n_struct = structure.lines(PL, i, hsr, None, win=SR_WIN[hz])
        t1 = time.perf_counter()
        score = chart_score.compute(PL, i, hz)
        overlay, hist = None, dict(n=0, rows=[], note='', hold=hz)
        if not side_ok or not tf_ok:
            why = M.get('no_short', '这个模型没有做空一侧的规则。') if not side_ok else M.get('no_week', '这个模型只按日线判定。')
            alt = [m for m in MODELS if side in m['sides'] and tf in m['tfs']]
            hint = ('要看' + SIDE_NAME[side] + ('、周 K' if tf == 'W' else '') + '，可以换用：' + '、'.join(m['name'] for m in alt) + '。') if alt else ''
            sig = dict(state='na', phase='不适用', phase_text='不适用', verdict='不适用', verdict_text='这个模型用不上', list=None, checks=[], missing=[], next_needs=[],
                       note=why, anchor=None, zone=None, mid=None, stop=None, stop_note='', t1=None, t2=None, t2_note='', rr=None,
                       unsupported='side' if not side_ok else 'tf', suggest=[m['key'] for m in alt])
            card = na_card(M, side, hz, tf, price, why, hint)
            if M.get('kind') == 'watch':
                card['cells'] = []
            name, version = M['name'], M['version']
        elif model == 'houshou':
            P = PL if side == 'long' else prepared(t, 'short', tf)[1]
            r = hsr if side == 'long' else hs.compute(B, i, anchors().get(akey(t, side, tf)), with_history=False, P=P)
            am = P['d'].index(r['anchor']['date']) if r['anchor'] and r['anchor']['by'] == 'manual' else None
            hist = hs.history(P, i, am, hz)
            sig = {k: r[k] for k in ('phase', 'verdict', 'list', 'checks', 'missing', 'next_needs', 'note', 'anchor', 'avwap', 'sd', 'dist_pct',
                                     'pushes', 'abcd', 'zone', 'mid', 't1', 'rr', 'start_low', 'top', 'base')}
            sig.update(stop=None if core else r['stop'], stop_note='核心仓不适用' if core and r['stop'] is not None else '手动止损',
                       t2=r['t2'], t2_note=r['t2_note'] if r['zone'] else '条件没齐，不给目标',
                       verdict_text=(VERDICT_TEXT if side == 'long' else VERDICT_TEXT_SHORT).get(r['verdict'], r['verdict']),
                       state=HS_STATE.get(r['verdict'], 'na'), phase_text=r['phase'] if side == 'long' else HS_PHASE_SHORT.get(r['phase'], r['phase']),
                       params=r['params'], est_note=hs.EST_NOTE)
            card = houshou_card(r, pos, side, hz, tf)
            if r['anchor']:
                overlay = dict(kind='houshou', side=side, anchor=r['anchor'], avwap=hs.avwap_series(P, r['anchor_index'], i), pushes=r['pushes'], abcd=r['abcd'],
                               zone=r['zone'], stop=sig['stop'], target=r['t1'], target2=r['t2'], base=r['base'])
            name, version = hs.NAME, hs.VERSION
        elif model == 'breakout':
            P = PL if side == 'long' else prepared(t, 'short', tf)[1]
            r = bo.compute(B, i, side, with_history=False, P=P)
            hist = bo.history(P, i, hz)
            sig = {k: r[k] for k in ('phase', 'verdict', 'verdict_text', 'list', 'checks', 'missing', 'next_needs', 'note', 'level', 'brk', 'extreme', 'pull', 'box',
                                     'dist_pct', 'zone', 'mid', 't1', 't2', 'rr')}
            sig.update(stop=None if core else r['stop'], stop_note='核心仓不适用' if core and r['stop'] is not None else '手动止损',
                       t2_note=r['t2_note'] if r['zone'] else '条件没齐，不给目标', state=BO_STATE.get(r['verdict'], 'na'), phase_text=r['phase'], anchor=None,
                       params=r['params'], est_note=bo.EST_NOTE)
            card = breakout_card(r, pos, side, hz, tf)
            if r['level']:
                overlay = dict(kind='breakout', side=side, level=r['level'], brk=r['brk'], extreme=r['extreme'], pull=r['pull'], box=r['box'],
                               zone=r['zone'], stop=sig['stop'], target=r['t1'], target2=r['t2'])
            name, version = bo.NAME, bo.VERSION
        elif M.get('mod'):
            P = PL if side == 'long' else prepared(t, 'short', tf)[1]
            sig, card, overlay, hist, model_legend = generic_signal(M, B, P, i, side, hz, tf, pos, core)
            name, version = M['name'], M['version']
        else:
            st['card'] = __import__('narrate').card_from_state(st, panel.backtest_summary())
            sg = st['signal']
            ready = bool(st['all4'])          # 四项没齐：引擎照样算出止损、前高这些结构位，但它们不是交易价位，这里一律给 null
            zone = st['card']['entry_zone'] if ready else None
            sig = dict(phase='已触发' if st['armed'] else '未触发', phase_text='已触发' if st['armed'] else '未触发', verdict=st['conclusion']['title'],
                       verdict_text=st['card']['verdict'], list='four', state='ready' if ready else 'wait' if st['armed'] else 'na',
                       checks=[dict(k=e['k'], name=e['name'], ok=bool(e['lit']), why=e['text']) for e in st['evidence']],
                       missing=list(st['conclusion']['missing']), next_needs=[], note=st['conclusion']['text'],
                       anchor=dict(date=st['levels']['anchor_date'], by='auto', note='地量日') if st['levels']['anchor_date'] else None,
                       zone=zone, mid=hs.px((zone[0] + zone[1]) / 2) if zone else None, stop=hs.px(sg['stop']) if ready else None,
                       stop_note='规则止损' if ready else '条件没齐，不给止损',
                       t1=hs.px(sg['target']) if ready and sg['target_usable'] else None, t2=four_t2(st) if zone else None,
                       t2_note='跌幅的一半【估算】' if zone else '条件没齐，不给目标', rr=sg['rr'] if ready else None)
            why = [x['why'] for x in st['signals']]
            hist = dict(n=len(why), rows=[], note='四证的历史信号见「模型」页', hold=panel.F['max_hold'],
                        outcomes=dict(target=sum(1 for x in why if x == 'target'), stop=sum(1 for x in why if x.startswith('stop')),
                                      none=sum(1 for x in why if x != 'target' and not x.startswith('stop'))))
            card, name, version = four_card(st, hz, pos), '四证·抄底 v1.0', 'four-1.0'
            lines += [x for x in structure.four_lines(PL, st) if ready or x['id'] != 'four_stop']     # 没齐：扇线、成本线照画，止损线不当价位给出去
            # 四证自己的止损、成本线、第一目标由「自动画」那一层画；这里只补第二目标这一条参考线
            if sig['t2'] is not None:
                lines.append(dict(id='t2', kind='level', group='model', label='第二目标', price=sig['t2'], style='target2'))
        if model != 'four':
            lines += plan_lines(sig, core, side)
        sig.update(side=side, side_name=side_name(M, side))
        # 「到这一天为止从没触发」和「全部样本上从没触发」是两回事：只有看最新一根时，才能说后一句（回放到过去时不提之后的事）
        hist['scope'] = '全部样本' if is_latest else '到这一天为止'
        hist['never'] = bool(is_latest and side_ok and tf_ok and not hist['n'])
        t2 = time.perf_counter()
        leg = legend(model, sig, lines, core, side, st if model == 'four' else None, model_legend if M.get('mod') and side_ok and tf_ok else None)
        week = None
        if tf == 'W':
            done = week_complete(asof_d)
            week = dict(complete=done, note='' if done else f'这一周还没收完（数据到 {asof_d}）。周 K 上的结论要等这一周最后一个交易日收盘才算数，现在是暂时的。')
        ms = lambda x, y: max(1, round((y - x) * 1000))
        steps = [dict(name='识别图表结构', ms=ms(t0, t1), note=f'{n_struct} 条结构线'),
                 dict(name='计算规则信号', ms=ms(t1, t2), note=sig['verdict_text']),
                 dict(name='在图上划线', ms=None, note=f'共 {len(lines)} 条，逐条画出'),
                 dict(name='AI 深度解读', ms=None, note='')]
        watch = M.get('kind') == 'watch'
        return dict(ok=True, ticker=t, asof=asof_d, index=i, is_latest=is_latest, price=price, model=version, model_key=model, model_name=name, kind=M.get('kind', 'trade'),
                    models=[dict(key=m['key'], name=m['name'], sides=list(m['sides']), tfs=list(m['tfs'])) for m in MODELS],
                    side=side, side_name=side_name(M, side), side_ok=side_ok, tf=tf, tf_name=TF_NAME[tf], tf_ok=tf_ok, adjust=ADJUST, adjust_short=ADJUST_SHORT, week=week,
                    horizon=dict(n=hz, label=HORIZONS[hz] if watch else horizon_label(hz, tf), options=[dict(n=n, label=HORIZONS[n] if watch else horizon_label(n, tf)) for n in HORIZONS]),
                    variant=variant(model, side, hz, tf), steps=steps, score=score, signal=sig, card=card, lines=lines,
                    overlay=overlay, history=hist, legend=leg, position=pos, position_note=position_note(pos, side, sig['state'], sig, core),
                    explain=EXPLAIN, banner=BANNER,
                    direction=dict(long='long' in M['sides'], short='short' in M['sides'], short_note='' if 'short' in M['sides'] else M.get('no_short', '')),
                    timeframe='日线' if tf == 'D' else '周线')


_HS_SAMPLE = {}


def houshou_sample():
    """后手清单在每只标的、每个方向的全部日线上触发过几次、各项单独成立过多少根（自动锚点，和面板默认一样）。数据变了才重算。"""
    out = []
    with _lock:
        for t in panel.TICKERS:
            for side in hs.SIDES:
                _, P = prepared(t, side, 'D')
                key = (P['n'], P['d'][-1])
                hit = _HS_SAMPLE.get((t, side))
                if hit is None or hit[0] != key:
                    h = hs.history(P, P['n'] - 1)
                    hit = _HS_SAMPLE[(t, side)] = (key, dict(ticker=t, side=side, n=h['n'], bars=P['n'], first=P['d'][0], last=P['d'][-1], stats=h['stats']))
                out.append(hit[1])
    return out


def houshou_sample_notes():
    """模型页上的几句：后手在全部样本上触发过几次、卡在哪一项。都是现算的，数据变了说法跟着变。"""
    S = houshou_sample()
    last, names = max(x['last'] for x in S), '、'.join(panel.TICKERS)
    hit = [x for x in S if x['n']]
    if hit:
        lines = [f'在 {names} 现有的全部日线上（截至 {last}），后手清单三项同时成立过：' + '、'.join(f'{x["ticker"]} {SIDE_NAME[x["side"]]} {x["n"]} 次' for x in hit) + '。']
    else:
        lines = [f'在 {names} 现有的全部日线上（做多、做空都算，截至 {last}），后手清单一次都没有三项同时成立过：条件齐 0 次。'
                 '这和信号卡上的「这套清单用不上」不是一回事：那一句只说今天，这一句说的是全部历史。']
    tot = {k: sum(x['stats'].get(k, 0) for x in S) for k in ('fall', 'B1', 'B2', 'B3', 'two_of_three')}
    lines.append(f'这几只标的、两个方向合计：三冲之后的回落（做空是三探之后的反弹）共 {tot["fall"]} 根 K 线，其中回到成本线 {tot["B1"]} 根、AB=CD {tot["B2"]} 根、'
                 f'缩量刺破收回 {tot["B3"]} 根，至少两项同时成立 {tot["two_of_three"]} 根。')
    if not hit and tot['fall'] and tot['B3'] < min(tot['B1'], tot['B2']):
        lines.append('最难过的是第三项「缩量刺破收回」：同一天要盘中刺破成本线又收回，成交量还要缩到下跌段的一半以下（一半是录屏原话的数）。'
                     '这几只标的的日线上，前两项成立的那些天，这两件事从没凑到同一天。规则没有为了让它出信号而放宽。')
    bare = [x for x in S if x['side'] == 'long' and not any(y['stats'].get('fall') for y in S if y['ticker'] == x['ticker'])]
    if bare:
        lines.append('、'.join(x['ticker'] for x in bare) + ' 的日线还太短（' + ('只有 %d 根' % bare[0]['bars'] if len(bare) == 1 else '、'.join(f'{x["ticker"]} 只有 {x["bars"]} 根' for x in bare)) +
                     '），两个方向都还没走出过三冲（三探）之后的回撤，清单轮不到。')
    lines.append('能触发的路径用合成 K 线锁在测试里（做多、做空各一条）：以后改代码要是让它在合成数据上也触发不了，测试会失败。')
    return lines


def scan_cell(t, model, side, horizon=20, tf='D', asof=None):
    """One cell of the terminal's table: the state of one model on one ticker and direction, without the drawing data."""
    q = result(t, model, asof, side, horizon, tf, 'flat')
    s = q['signal']
    return dict(ticker=t, model=model, side=side, asof=q['asof'], price=q['price'], state=s['state'], verdict=s['verdict_text'], phase=s.get('phase_text'),
                ok=sum(1 for c in s['checks'] if c['ok']), of=len(s['checks']), zone=s.get('zone'), stop=s.get('stop'), t1=s.get('t1'), t2=s.get('t2'), rr=s.get('rr'),
                score=q['score']['total'], score_label=q['score']['label'], supported=q['side_ok'] and q['tf_ok'],
                history=dict(q['history'].get('outcomes') or dict(
                    target=sum(1 for r in q['history']['rows'] if r['outcome'] == 'target'), stop=sum(1 for r in q['history']['rows'] if r['outcome'] == 'stop'),
                    none=sum(1 for r in q['history']['rows'] if r['outcome'] in ('none', 'open'))), n=q['history']['n'], hold=q['history'].get('hold'),
                    rr_median=q['history'].get('rr_median')))


# ---------- template narration (no API) ----------

def _draw_level(price, label):
    return dict(type='level', price=price, label=label)


def _score_step(q):
    sc = q['score']
    return dict(q='图表现状', look='；'.join(f'{p["name"]} {p["v"]:+d}（{p["why"]}）' for p in sc['parts']), say=f'表盘 {sc["total"]:+d}，{sc["label"]}', sticker=sc['label'],
                tone='good' if sc['total'] > 20 else 'bad' if sc['total'] < -20 else 'neutral', evidence=0, ok=False, draw=[])


def template(q):
    """The questions of the selected model for the current phase, in the same card format as the four-evidence narration."""
    if q['signal'].get('unsupported'):
        s = q['signal']
        return dict(hook='这个模型用不上', story=s['note'],
                    steps=[dict(q='这套规则用得上吗？', look=s['note'], say='这个方向没有规则' if s['unsupported'] == 'side' else '这个级别没有规则', sticker='不适用', tone='neutral',
                                evidence=0, ok=False, draw=[]), _score_step(q)],
                    final='清单不适用，只看图', watch=[])
    if q['signal'].get('asks') is not None:
        return _template_generic(q)
    return _template_breakout(q) if q['model_key'] == 'breakout' else _template_houshou(q)


def _template_generic(q):
    """Models built on qmodel.py: one card per checklist line, in the words the model file gives."""
    s = q['signal']
    steps = []
    for c in s['asks']:
        ok = c['ok']
        steps.append(dict(q=c['ask'], look=c['why'], say=c['yes'] if ok else c['no'], sticker=c['sticker_yes'] if ok else c['sticker_no'],
                          tone=('good' if ok else 'neutral') if c['good'] else ('bad' if ok else 'good'), evidence=0, ok=bool(ok), draw=[d for d in c['draw'] if d]))
    if not steps:
        steps.append(dict(q='这套规则用得上吗？', look=s['note'], say='今天没有它要的那种走势', sticker='不适用', tone='neutral', evidence=0, ok=False, draw=[]))
    steps.append(_score_step(q))
    n = sum(1 for c in s['checks'] if c['ok'])
    final = s['verdict_text'] if s['state'] != 'wait' or not s['checks'] else f'清单 {n}/{len(s["checks"])}，等'
    return dict(hook=s.get('hook') or s['verdict_text'], story=s.get('story') or s['note'] or q['card']['text'], steps=steps, final=final, watch=list(s['next_needs'])[:3])


def _template_houshou(q):
    s = q['signal']
    long = q.get('side', 'long') == 'long'
    W = hs.WORDS['long' if long else 'short']
    ck = {c['k']: c for c in s['checks']}
    steps = []

    def step(question, c, say_ok, say_no, st_ok, st_no, good_when_ok, draw):
        ok = c['ok']
        steps.append(dict(q=question, look=c['why'], say=say_ok if ok else say_no, sticker=st_ok if ok else st_no,
                          tone=('good' if ok else 'bad') if good_when_ok else ('bad' if ok else 'good'), evidence=0, ok=bool(ok), draw=[d for d in draw if d]))

    cost = _draw_level(s['avwap'], '成本线') if s.get('avwap') else None
    zone_name = '出货区' if long else '接货区'
    if s['phase'] == '拉升中':
        ps = s['pushes']
        top = ps[-1] if ps else None
        step('离成本多远？', ck['A1'], '离成本线太远了', '离成本线还不算远', '不追！', '还能看', False,
             [cost, dict(type='point', date=q['asof'], price=q['price'], label='现价')])
        step(f'第几{W["push"]}、兵还跟不跟？' if long else f'第几{W["push"]}、抛压还在不在？', ck['A2'],
             f'第三{W["push"]}了，兵越冲越少' if long else f'第三{W["push"]}了，抛压一次比一次小', '兵还跟得上，或者还没到第三冲' if long else '抛压还在，或者还没到第三探', '不追！', '还能看', False,
             [dict(type='point', date=p['date'], price=p['price'], label=f'第{p["n"]}{W["push"]}') for p in ps[-3:]] + [dict(type='volume', dates=[p['date'] for p in ps[-3:]], label=f'每一{W["push"]}的量')])
        step('天量是抢筹还是出货？' if long else '天量是砸盘还是有人接？', ck['A3'], f'天量加长{W["shadow"]}，是{"出货" if long else "有人接"}', f'没有天量长{W["shadow"]}', zone_name, '还能看', False,
             [dict(type='point', date=top['date'], price=top['price'], label=W['peak_bar']), dict(type='volume', dates=[top['date']], label='这天的量')] if top else [])
        hook = {'不追·出货区': '三项全中，别追', '不追': '离成本太远，别追', '出货区': f'第三{W["push"]}见天量，小心', '还能看': f'还在{W["push"]}，没到不追的份上'}[s['verdict']]
        story = f'从 {s["anchor"]["date"][5:]} 的成本锚点{W["start"]}，已经第 {len(ps)} {W["push"]}'
        final = s['verdict_text']
    elif s['phase'] == '回落中':
        ab = s['abcd']
        path = [ab[k] for k in ('A', 'B', 'C', 'D') if ab.get(k)]
        step('回到成本线没有？', ck['B1'], f'{"跌" if long else "弹"}回成本线了', '还没回到成本线', '到位了', '等', True,
             [cost, dict(type='point', date=ab['D']['date'], price=ab['D']['price'], label='D') if ab.get('D') else None])
        step(f'两段{W["down"]}得一样长吗？', ck['B2'], '两段差不多长', '两段还不一样长', '到位了', '等', True,
             [dict(type='path', points=[dict(date=p['date'], price=p['price']) for p in path], label='两段回落' if long else '两段反弹')] if len(path) >= 2 else [])
        step('缩量刺破收回了吗？', ck['B3'], '缩量刺破又收回，' + ('有人接' if long else '有人压'), '还没有缩量刺破收回', '有人接' if long else '有人压', '等', True,
             [cost, dict(type='volume', dates=[q['asof']], label='今天的量')])
        n = sum(c['ok'] for c in s['checks'])
        hook = '三项齐了（未回测）' if n == 3 else f'后手清单 {n}/3，等'
        story = f'{ab["A"]["date"][5:]} 第三{W["push"]}见{"顶" if long else "底"} {ab["A"]["price"]}，之后往成本线{"回落" if long else "反弹"}'
        final = ('下后手（未回测）' if long else '下后手做空（未回测）') if n == 3 else '条件没齐，等'
    else:
        hook = '这套清单今天用不上' if s['phase'] == '无结构' else '这个结构作废了'
        story = s['note'] or f'没有找到三{W["push"]}结构'
        steps.append(dict(q='这套规则用得上吗？', look=s['note'], say=f'没有三{W["push"]}，清单用不上' if s['phase'] == '无结构' else '触发过又越过了止损', sticker='不适用', tone='neutral',
                          evidence=0, ok=False, draw=[dict(type='point', date=p['date'], price=p['price'], label=f'第{p["n"]}{W["push"]}') for p in s.get('pushes') or []]))
        if s.get('avwap'):
            far = s['dist_pct']
            steps.append(dict(q='离成本线多远？', look=f'成本线 {s["avwap"]}，现价离它 {far}%', say='在成本线上方' if far > 0 else '在成本线下方', sticker='仅参考', tone='neutral',
                              evidence=0, ok=False, draw=[cost, dict(type='point', date=q['asof'], price=q['price'], label='现价')]))
        final = '清单不适用，只看图'
    steps.append(_score_step(q))
    return dict(hook=hook, story=story, steps=steps, final=final, watch=list(s['next_needs'])[:3])


def _template_breakout(q):
    s = q['signal']
    W = bo.WORDS[q.get('side', 'short')]
    steps = []
    lv = s.get('level')
    line = _draw_level(lv['price'], W['level']) if lv else None
    if s['checks']:
        k1, k2, k3 = (s['checks'] + [None, None])[:3]
        steps.append(dict(q=f'{W["brk"]}了吗？', look=k1['why'], say=f'{W["brk"]}了' if k1['ok'] else f'还没{W["brk"]}', sticker=W['brk'] if k1['ok'] else '等', tone='neutral',
                          evidence=0, ok=bool(k1['ok']),
                          draw=[x for x in (line, dict(type='point', date=s['brk']['date'], price=s['brk']['close'], label=W['brk'] + '那根') if s.get('brk') else None) if x]))
        if k2:
            steps.append(dict(q=f'{W["back"]}到位了吗？', look=k2['why'], say=f'{W["back"]}到位了' if k2['ok'] else f'还没{W["back"]}到位', sticker='到位了' if k2['ok'] else '等',
                              tone='good' if k2['ok'] else 'neutral', evidence=0, ok=bool(k2['ok']),
                              draw=[x for x in (line, dict(type='point', date=s['pull']['date'], price=s['pull']['price'], label=W['back']) if s.get('pull') else None) if x]))
        if k3:
            steps.append(dict(q=f'缩量、{W["hold"]}了吗？', look=k3['why'], say=f'缩量{W["hold"]}' if k3['ok'] else f'还没{W["hold"]}', sticker=W['hold'] if k3['ok'] else '等',
                              tone='good' if k3['ok'] else 'neutral', evidence=0, ok=bool(k3['ok']), draw=[x for x in (line, dict(type='volume', dates=[q['asof']], label='今天的量')) if x]))
        n = sum(c['ok'] for c in s['checks'])
        hook = '三项齐了（未回测）' if s['state'] == 'ready' else s['verdict_text']
        story = (f'{s["brk"]["date"][5:]} {W["brk_v"]} {lv["price"]} 的{W["level"]}' if s.get('brk') else f'最近的{W["level"]}在 {lv["price"]}，还没{W["brk"]}')
        final = s['verdict_text'] if s['state'] != 'wait' else f'清单 {n}/{len(s["checks"])}，等'
    else:
        hook, story, final = '这套清单今天用不上', s['note'], '清单不适用，只看图'
        steps.append(dict(q='这套规则用得上吗？', look=s['note'], say=f'没有{W["brk"]}，清单用不上', sticker='不适用', tone='neutral', evidence=0, ok=False, draw=[]))
    steps.append(_score_step(q))
    return dict(hook=hook, story=story, steps=steps, final=final, watch=list(s['next_needs'])[:3])


def facts_for_ai(q):
    """What Claude is told about the panel: the score, the selected model's checklist result and the structure levels. Numbers only from here.
    rule_signal keeps exactly the fields it always had (saved readings are matched against it); what is new goes into setup and plan."""
    s = q['signal']
    keep = ('phase', 'verdict', 'verdict_text', 'checks', 'missing', 'next_needs', 'note', 'anchor', 'avwap', 'dist_pct', 'pushes', 'abcd', 'zone', 'stop',
            'stop_note', 't1', 'rr')
    out = dict(selected_model=q['model_name'], model_backtested=False if q['model_key'] != 'four' else '证据不足',
               chart_score=dict(total=q['score']['total'], label=q['score']['label'], parts=q['score']['parts']),
               rule_signal={k: s[k] for k in keep if k in s},
               structure_lines=[{k: x[k] for k in ('label', 'price', 'p1', 'p2') if k in x} for x in q['lines']],
               history_triggers=q['history']['n'], history_stats=q['history'].get('stats'))
    out['setup'] = dict(direction=q['side_name'], model_kind='观察用（不给价位）' if q.get('kind') == 'watch' else '交易规则', horizon=q['horizon']['label'], bars=q['tf_name'], rule_state=STATE_TEXT[s['state']],
                        position=q['position']['text'] + ('（假设）' if q['position']['assumed'] else ''))
    out['plan'] = {k: s.get(k) for k in ('zone', 'mid', 'stop', 't1', 't2', 't2_note', 'rr') if s.get(k) is not None}
    for k in ('level', 'brk', 'extreme', 'pull', 'box', 'unsupported') + tuple(getattr(MODEL[q['model_key']].get('mod'), 'EXTRA', ())):
        if s.get(k):
            out['rule_signal'][k] = s[k]
    if q['position_note']:
        out['setup']['position_note'] = q['position_note']
    if q.get('week') and not q['week']['complete']:
        out['setup']['week_note'] = q['week']['note']
    return out
