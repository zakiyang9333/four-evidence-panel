"""“让 Claude 润色”：把引擎事实交给 Claude，让它按视频的四问结构写解说，只返回 JSON。

Claude 只负责措辞。四项证据的真假、结论、卡片上的价位都由后端按引擎结果填写或覆盖（narrate.normalize），
解说里的每个数字还要和输入逐个比对（narrate.bad_numbers），对不上就整段不用，改用模板版。
密钥只从环境变量 ANTHROPIC_API_KEY 读，只在这个后端进程里用，不写日志、不回传给前端。
"""
import hashlib
import json
import os

import narrate

# 系统提示词。APP_ADDENDUM_AI.md 原来要求固定四问；zaki 11-16 改了主意：市场变化多，Claude 要能自由分析，
# 只保留模板版那种呈现方式（一句定性、一张张短卡片、贴纸、大字结论）。所以这里不再规定讲什么、讲几步、什么顺序。
SYSTEM = """你是一个交易图表解说员，风格像短视频里的盘面复盘：短句、口语、有画面感，每一步先给判断再给理由。

你会收到一份 JSON：规则引擎（抄底核心四要素）在某个收盘日的结果、最近 60 根日 K 线、回测摘要，有时还有使用者的相关仓位。请你自己看这张图，讲出今天最值得讲的东西。讲什么、讲几步、按什么顺序，都由你根据盘面决定：可以是量价关系、K 线形态、缺口、均线和 MACD 的状态、支撑和压力、波动变大还是变小、和前几次下跌的对比、仓位和关键价位的距离，或者任何你在数据里看到的异常。四要素只是其中一个角度，不必每次都四条全讲，也不必只讲它们。每天的盘面不一样，解说也应该不一样。

使用者是盯着 K 线图看的，不想读文字。之前的版本把日期和价格一串串写进卡片，他的原话是“过于啰嗦，无用信息太多，干扰我的思考”。所以这一版的分工是：**你只说判断，证据画在图上**。每一步出现时，界面会把你指定的标记一笔一笔画到 K 线图上（圈出某根 K 线、把几个高点连成线、画一条价位线、涂出一段平台），价格由界面从真实数据里读出来标在图上，你不用、也不要在文字里报数。

输出：
- hook：一句话定性现在是什么局面，像视频开场那句大字。不超过 16 个汉字。
- story：一句话讲盘面怎么走到这里的。不超过 30 个汉字，不罗列价格。
- steps：3 到 6 步，只挑今天最要紧的讲，宁少勿多。每一步：
  - q：小标题，6 个字以内。
  - say：一句口语判断，像视频字幕，不超过 18 个汉字，里面不放数字（最多一个最关键的）。
  - sticker：贴在这一步上的结论，4 个字以内（例如“不抄！”“还不抄”“证据+1”“假突破”“有承接”“过不去”，自己起也行）。
  - tone：这一步对多头是 good、bad 还是 neutral。
  - evidence：对应四要素第几项（1 地量见底，2 底背离，3 跌速放缓，4 站回成本线），无关写 0。
  - draw：这一步要在图上画什么，1 到 5 个标记，这是这一步的证据，必须有。每个标记的字段都要填，用不到的填空数组或 0：
    - type="point"：圈出某几根 K 线的某个位置。dates 填日期（"MM-DD" 或 "YYYY-MM-DD"，必须是输入里有的交易日），at 填 high / low / open / close。
    - type="path"：把几根 K 线的同一个位置按顺序连成一条线，用来表现“高点一个比一个低”“低点在抬高”这类走势。dates 按时间顺序填 2 到 8 个，at 同上。
    - type="level"：一条水平价位线（压力、支撑、行权价、止损、目标）。要么 dates 填一个日期加 at（界面取那根 K 线的价），要么 price 填输入里原样出现过的价位。
    - type="zone"：一段横盘或密集成交区。dates 填起止两个日期；top / bottom 填上下沿，填 0 表示用这段时间的最高最低。
    - type="volume"：指出某几天的成交量（界面会标出当天的量）。dates 填日期。
    - type="macd"：指出某几天的 MACD。dates 填日期。
    - label：标在图上的几个字（6 个字以内，例如“高点1”“假突破”“旧平台”“缺口”），不写价格，价格界面会自己标。
- final：一句大字结论，10 个汉字以内。
- watch：接下来盯什么，最多 3 条，每条不超过 20 个汉字。输入里的 next_close_needs 是引擎给的门槛，可以挑最要紧的用，也可以加你自己从图上看出来的。

三条边界：
1. 四项证据成立不成立、几比四、能不能入场，以输入里引擎的结果为准。你可以说引擎没覆盖到的东西，可以指出引擎结论的局限（例如低点太旧），但不要把没成立的证据说成成立，也不要给出和引擎相反的入场结论。
2. 日期只用输入里有的交易日。文字里万不得已要写数字时，只用输入里有的，或者能从输入直接算出来的。你不知道新闻、财报和估值，不要假装知道。
3. 不给具体下单指令，不写“建议买入/卖出”，不建议仓位。

不要用 Markdown。用中文。"""

# 有持仓数据时追加的一段（补充指令 1 的要求）；没有持仓就不加。
PORTFOLIO_RULES = """

输入里还有 positions：使用者在这只标的上的相关仓位（数量、成本、所属侧、备注；r_definition 为空表示没有给出，不要替他定义）。
解说要遵守 zaki 的规则：核心仓按估值失效，没有价格止损；战术单四要素不到 4/4 不开；不给具体下单指令。
仓位和图上价位（成本线、止损线、行权价、扇子中线）的相对位置可以单独讲一步；不评价该不该继续持有，不建议调整仓位。positions_stale 为真时要提醒以券商 App 为准。"""

# 有「AI 量化」面板的结果时追加的一段（补充指令 3）。zaki 11-16：“写死的规则未必能赶上千变万化的市场”。
QUANT_RULES = """

输入里还有 quant：这是「AI 量化」面板上已经显示的三样东西，都是代码算出来的。
- chart_score：当前图表评分（−100 到 +100）和五个分项。公式是估算的，只描述图表现状，不是预测。
- rule_signal：使用者选的规则模型（selected_model）的清单结果。四证·抄底就是上面那套。后手·成本线回踩是另一套：先找成本锚点（横盘第一根）算成本线，数三次冲高和每一冲的成交量；拉升时看“离成本线太远、第三冲缩量、天量长上影”这张不追清单，回落时看“回到成本线、两段跌幅相当（AB=CD）、缩量刺破收回”这张后手清单。这套模型没有回测过，很多参数是估算的。
- structure_lines：面板画在图上的支撑、压力、趋势线和斐波那契回撤价位。
表盘和规则信号是两套独立的东西，可以不一致，不用硬凑成一个说法。

最要紧的一条：规则清单是写死的，市场不会照着清单走。清单显示“无结构”“不适用”，或者你看到清单明显跟不上眼前的走势（比如它数出来的冲、锚点、两段回落和图上真正要紧的结构对不上），就直接说这套规则今天用不上、为什么用不上，然后讲你自己从 K 线里看到的结构。不要为了配合清单硬套三冲和 ABCD。清单里每一项成立不成立、阶段、结论是引擎结果，你不能改写，但可以评价它适不适用、漏看了什么。

选的是后手模型时，steps 里的 evidence 一律写 0。后手清单三项全中时，结论最多说“条件齐了（未回测）”，不要说成可以入场；有核心仓时不要给价格止损。"""

# 有「时效与备注」时追加的一段（zaki 11-16：想知道当时发生过什么）。
NOTES_RULES = """

输入里还有 context：K 线上的备注，告诉你某一天发生过什么。
- notes：每条有日期、类别、内容、来源。fact 为真的是事件日（财报日、除息日、拆股日），可以当事实用；其余是媒体标题、联网搜到的摘要或使用者自己写的备注，只代表“有人这么说”。
- next_earnings：下一次财报日和还有几天。财报临近时，要在解说里提一句，因为它会让眼前的形态随时作废。
- coverage、news_archive_since、days_searched_online：说明哪些日子有记录。
用法：某一步讲到的那几根 K 线如果有备注，就把它带上，说清是哪天、哪一类（例如“这天是财报日”“这天有报道说……”）。没有备注的日子，你不知道那天发生了什么：直接说不知道，不要猜原因，更不要编新闻。备注不改变规则引擎的任何结论。"""

FALLBACK_BETA = 'server-side-fallback-2026-07-01'


def status(cfg):
    """(enabled, reason). Never returns or logs the key itself."""
    if not os.environ.get('ANTHROPIC_API_KEY', '').strip():
        return False, '没有设置 ANTHROPIC_API_KEY，不能让 Claude 润色；模板版解说照常可用。'
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, '没有安装 anthropic SDK（重新运行 ./start.sh 会自动安装），不能让 Claude 润色。'
    return True, ''


def system_prompt(with_positions, with_quant=False, with_notes=False):
    return SYSTEM + (QUANT_RULES if with_quant else '') + (NOTES_RULES if with_notes else '') + (PORTFOLIO_RULES if with_positions else '')


def build_input(facts, bars60, backtest, positions=None, quant=None, notes=None):
    body = dict(facts)
    if notes:
        body['context'] = notes         # K 线上的备注：事件日、新闻标题、联网搜到的、手写的
    if quant:
        body['quant'] = quant           # 表盘、所选模型的清单结果、结构线：面板上已经显示的那些
    body['bars'] = dict(columns=['date', 'open', 'high', 'low', 'close', 'volume'], rows=bars60)
    body['backtest'] = backtest
    if positions:
        body.update(positions)          # positions / positions_asof / positions_stale，只含这只标的相关的仓位
    return json.dumps(body, ensure_ascii=False, separators=(',', ':'))


def fingerprint(facts, bars60, backtest, cfg=None, positions=None, extra=None):
    """Hash of what a reading is about: the engine facts, the bars, the backtest summary and the relevant positions.
    Same hash = the saved reading still applies, so no new call is needed.
    Deliberately not in it: the model and the prompt wording (a reading of the same market stays a reading of it),
    when the positions file was last synced, and the notes (one of them counts days since the last bar)."""
    f = {k: v for k, v in facts.items() if k != 'notes'}
    rows = (positions or {}).get('positions') or []
    parts = [f, bars60, backtest, rows] + ([extra] if extra is not None else [])    # extra：后手模型的清单结果（含手动锚点）；四证不传，指纹和以前一样
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)
    return 'd2-' + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]


def polish(facts, bars60, backtest, cfg, positions=None, quant=None, notes=None):
    """Ask Claude for the JSON narration. Returns dict(ok, raw | error, model). Raises nothing."""
    ok, why = status(cfg)
    if not ok:
        return dict(ok=False, error=why, code='disabled')
    import anthropic
    key = os.environ['ANTHROPIC_API_KEY'].strip()
    scrub = lambda s: str(s).replace(key, '***')
    client = anthropic.Anthropic(api_key=key, timeout=float(cfg.get('ai_timeout_s', 180)), max_retries=2)
    out_cfg = {'format': {'type': 'json_schema', 'schema': narrate.SCHEMA}}       # 只允许按这个结构输出 JSON
    if cfg.get('ai_effort'):
        out_cfg['effort'] = cfg['ai_effort']
    kw = dict(model=cfg['ai_model'], max_tokens=int(cfg.get('ai_max_tokens', 16000)), system=system_prompt(bool(positions), bool(quant), bool(notes)),
              messages=[{'role': 'user', 'content': build_input(facts, bars60, backtest, positions, quant, notes)}], output_config=out_cfg)

    def run(with_fallback):
        if with_fallback:   # if the model declines, the API re-runs the request on its default fallback model
            cm = client.beta.messages.stream(betas=[FALLBACK_BETA], fallbacks='default', **kw)
        else:
            cm = client.messages.stream(**kw)
        with cm as stream:
            return stream.get_final_message()

    def once():
        try:
            return run(bool(cfg.get('ai_refusal_fallback', True)))
        except anthropic.BadRequestError:
            if not cfg.get('ai_refusal_fallback', True):
                raise
            return run(False)       # the fallback option is not accepted for this model/account: plain request

    try:
        for attempt in (1, 2):      # 解析失败重试一次
            msg = once()
            if msg.stop_reason == 'refusal':
                return dict(ok=False, code='refusal', error='模型拒绝了这次请求。')
            text = ''.join(b.text for b in msg.content if b.type == 'text').strip()
            try:
                u = getattr(msg, 'usage', None)
                return dict(ok=True, raw=json.loads(text), model=msg.model, attempts=attempt,
                            tokens_in=getattr(u, 'input_tokens', None), tokens_out=getattr(u, 'output_tokens', None))
            except ValueError:
                continue
        return dict(ok=False, code='parse', error='Claude 两次返回的都不是合法 JSON。')
    except anthropic.AuthenticationError:
        return dict(ok=False, code='auth', error='API 密钥无效或已失效（401）。在控制台复制一个有效的密钥，再运行一次 start_with_key.sh。')
    except anthropic.PermissionDeniedError as e:
        return dict(ok=False, code='permission', error=scrub(f'这个密钥没有权限使用模型 {cfg["ai_model"]}（403）：{e.message}'))
    except anthropic.NotFoundError:
        return dict(ok=False, code='model', error=f'找不到模型 {cfg["ai_model"]}（404）。请改 config.json 里的 ai_model。')
    except anthropic.RateLimitError:
        return dict(ok=False, code='rate', error='请求太频繁或额度用完（429），稍后再试。')
    except anthropic.BadRequestError as e:
        return dict(ok=False, code='bad_request', error=scrub(f'请求被拒绝（400）：{e.message}'))
    except anthropic.APIStatusError as e:
        return dict(ok=False, code='api', error=scrub(f'Claude API 返回错误（{e.status_code}），稍后再试。'))
    except anthropic.APIConnectionError:
        return dict(ok=False, code='network', error='连不上 Claude API，请检查网络。')


# ---------- Claude 联网搜：某几天发生过什么 ----------

SEARCH_SYSTEM = """你在帮一个看 K 线图的人查“那几天发生过什么”。用联网搜索，只报搜索结果里确实有的东西。

每个日期最多给 3 条和这只标的股价直接相关、由可靠媒体或公司公告报道过的事（财报、指引、重大合同、监管、高管变动、行业或宏观的大消息）。
搜不到就不给，不要猜，不要拿常识或推测来凑；宁可空着。

最后只输出一个 JSON 对象，不要别的文字：
{"items": [{"date": "YYYY-MM-DD", "what": "用你自己的话写一句中文概括，不超过 40 个字，不照抄原标题", "source": "媒体或机构名", "url": "搜索结果里这条的原始链接"}]}
date 写事情发生或被报道的美东日期。url 必须是搜索结果里出现过的链接，原样照抄。"""


def search_days(name, ticker, rows, cfg):
    """One web-search request for a few days. rows = [{date, why}]. Returns dict(ok, message (the response as a dict) | error, model, tokens)."""
    ok, why = status(cfg)
    if not ok:
        return dict(ok=False, error=why, code='disabled')
    import anthropic
    key = os.environ['ANTHROPIC_API_KEY'].strip()
    scrub = lambda s: str(s).replace(key, '***')
    client = anthropic.Anthropic(api_key=key, timeout=float(cfg.get('ai_timeout_s', 180)), max_retries=1)
    ask = (f'标的：{name}（代码 {ticker}，美股）。请查下面这些交易日前后发生过什么：\n' +
           '\n'.join(f"- {r['date']}：当天{r.get('why') or '走势异常'}" for r in rows))
    # 用基础版搜索工具（web_search_20250305）而不是带“动态筛选”的 20260209：后者会先写代码去筛搜索结果，
    # 2026-11-16 实测在次数上限内把代码跑崩了（Server tool use limit exceeded during code execution），最后交了空列表。
    # 基础版把搜索结果直接给模型读，结果块里的链接也正好用来核对。要换回去改 config.json 的 ai_search_tool。
    tools = [{'type': cfg.get('ai_search_tool', 'web_search_20250305'), 'name': 'web_search', 'max_uses': int(cfg.get('ai_search_max_uses', 1 + 2 * len(rows)))}]
    kw = dict(model=cfg['ai_model'], max_tokens=int(cfg.get('ai_search_max_tokens', 12000)), system=SEARCH_SYSTEM, tools=tools,
              output_config={'effort': cfg.get('ai_search_effort', 'low')})
    messages = [{'role': 'user', 'content': ask}]
    try:
        tin = tout = 0
        for _ in range(4):          # 服务器端的搜索循环到上限会停在 pause_turn：把这一轮原样送回去，它接着做
            with client.messages.stream(messages=messages, **kw) as stream:
                msg = stream.get_final_message()
            u = getattr(msg, 'usage', None)
            tin += getattr(u, 'input_tokens', 0) or 0
            tout += getattr(u, 'output_tokens', 0) or 0
            if msg.stop_reason != 'pause_turn':
                break
            messages = [{'role': 'user', 'content': ask}, {'role': 'assistant', 'content': msg.content}]
        if msg.stop_reason == 'refusal':
            return dict(ok=False, code='refusal', error='模型拒绝了这次搜索。')
        return dict(ok=True, message=msg.model_dump(mode='json'), model=msg.model, tokens_in=tin, tokens_out=tout)
    except anthropic.AuthenticationError:
        return dict(ok=False, code='auth', error='API 密钥无效（401）。')
    except anthropic.RateLimitError:
        return dict(ok=False, code='rate', error='请求太频繁或额度用完了（429），稍后再试。')
    except anthropic.APIStatusError as e:
        return dict(ok=False, code='api', error=f'接口报错（{e.status_code}）：{scrub(getattr(e, "message", ""))[:200]}')
    except anthropic.APIConnectionError:
        return dict(ok=False, code='network', error='连不上 Anthropic 的接口，检查网络或代理。')
    except Exception as e:      # noqa: BLE001
        return dict(ok=False, code='error', error=f'搜索失败：{type(e).__name__}')

