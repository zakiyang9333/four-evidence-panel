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

输出的版式是固定的（界面会把它排成一张张卡片），内容是你的：
- hook：一句话定性现在是什么局面，像视频开场那句大字。
- story：一两句话讲盘面是怎么走到这里的。
- steps：2 到 8 步。每一步：q 是这一步的小标题（你自己起，几个字）；look 写你看到的事实，带上具体的日期和数字；say 写一句口语判断，像视频字幕，短而有力；sticker 是贴在这一步上的几个字的结论（例如“不抄！”“还不抄”“证据+1”“报警而已”“放量了”“有承接”“假突破”，自己起也行）；tone 标这一步对多头是 good、bad 还是 neutral；evidence 写这一步对应四要素里的第几项（1 地量见底，2 底背离，3 跌速放缓，4 站回成本线），和四要素无关就写 0。
- final：一句大字结论。
- watch：接下来几根 K 线要盯什么，写具体的价位或条件。输入里的 next_close_needs 是引擎给的门槛，可以用，也可以加你自己从图上看出来的。

三条边界：
1. 四项证据成立不成立、几比四、能不能入场，以输入里引擎的结果为准。你可以说引擎没覆盖到的东西，可以指出引擎结论的局限（例如低点太旧），但不要把没成立的证据说成成立，也不要给出和引擎相反的入场结论。
2. 数字只用输入里有的，或者能从输入直接算出来的（涨跌幅、两个价位的距离、几根 K 线的均值）。不要编造价格、成交量、日期；你不知道新闻、财报和估值，不要假装知道。
3. 不给具体下单指令，不写“建议买入/卖出”，不建议仓位。

不要用 Markdown。用中文。"""

# 有持仓数据时追加的一段（补充指令 1 的要求）；没有持仓就不加。
PORTFOLIO_RULES = """

输入里还有 positions：使用者在这只标的上的相关仓位（数量、成本、所属侧、备注；r_definition 为空表示没有给出，不要替他定义）。
解说要遵守 zaki 的规则：核心仓按估值失效，没有价格止损；战术单四要素不到 4/4 不开；不给具体下单指令。
仓位和图上价位（成本线、止损线、行权价、扇子中线）的相对位置可以单独讲一步；不评价该不该继续持有，不建议调整仓位。positions_stale 为真时要提醒以券商 App 为准。"""

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


def system_prompt(with_positions):
    return SYSTEM + (PORTFOLIO_RULES if with_positions else '')


def build_input(facts, bars60, backtest, positions=None):
    body = dict(facts)
    body['bars'] = dict(columns=['date', 'open', 'high', 'low', 'close', 'volume'], rows=bars60)
    body['backtest'] = backtest
    if positions:
        body.update(positions)          # positions / positions_asof / positions_stale，只含这只标的相关的仓位
    return json.dumps(body, ensure_ascii=False, separators=(',', ':'))


def fingerprint(facts, bars60, backtest, cfg, positions=None):
    """Hash of exactly what would be sent (model + system prompt + input). Same hash = the saved reading still applies."""
    raw = '\n'.join([cfg['ai_model'], str(cfg.get('ai_effort')), system_prompt(bool(positions)), build_input(facts, bars60, backtest, positions)])
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]


def polish(facts, bars60, backtest, cfg, positions=None):
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
    kw = dict(model=cfg['ai_model'], max_tokens=int(cfg.get('ai_max_tokens', 16000)), system=system_prompt(bool(positions)),
              messages=[{'role': 'user', 'content': build_input(facts, bars60, backtest, positions)}], output_config=out_cfg)

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
                return dict(ok=True, raw=json.loads(text), model=msg.model, attempts=attempt)
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
