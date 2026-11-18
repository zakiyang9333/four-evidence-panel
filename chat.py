"""AI 对话：一边看图一边问（zaki 2026-11-17：要有记忆，尽量接近 ChatGPT；一键解释并进对话框）。

- 每个对话存成本机的一个 JSON 文件（data/chats/，不进 git）。接口本身不记事，所以每次都把这段对话到目前为止的全部消息
  一起发过去，这就是“记忆”。关掉面板、隔天再打开，接着聊的还是同一段。
- 图表数据（引擎结论、最近 60 根日线、表盘、清单、备注、当天保存的 AI 解读、这只标的相关的仓位）只在它变了的时候
  附在用户的那条消息前面：换了标的、换了日期、换了模型或者多了备注，下一条消息才会再带一份新的。
- 一键解释是程序拼的（learn.py），不调用 AI、不花钱；它作为一条助手消息存进对话，之后可以接着追问“第 3 张没看懂”。
- 历史只往后加，不改前面的内容：这样前面的部分能被接口缓存，后面的每一问都便宜很多。
"""
import json
import os
import re
import secrets
import time

import mine
import panel

MAX_TEXT = 4000

SYSTEM = """你是「四要素观察面板」里的 AI 助手。使用者一边看 K 线图，一边问你问题。你像一个懂行、有耐心的朋友那样回答。

你会看到的东西：
- 用户的消息前面有时带一段【图表数据】。那是面板在那一刻用代码算好的结果：规则引擎的结论、最近 60 根日线、评分表盘、所选规则模型的清单、图上的结构线、K 线上的备注（财报日、新闻、联网搜到的、他手写的）、当天保存的 AI 解读，有时还有他在这只标的上的相关仓位。对话里可能出现好几段（他换了标的或日期），回答关于“现在这张图”的问题时，以最近的一段为准。
- 图表数据的 quant.setup 写着他现在选的方向（做多或做空）、周期、K 线级别和持仓（可能只是他的假设）。方向是做空时，清单是所选模型做空一侧的；模型没有这一侧的规则时会写明“用不上”，照实说，不要替它编。quant.plan 是清单齐了才有的计划价位，第二目标是估算的。
- quant.preplan 是预案价位：清单还没齐时，假如还差的那几项就在今天收盘成立，计划大约落在哪里。它和清单齐了时用的是同一套公式，但不是信号，条件齐了才算数；哪天齐了，价位按那天的数重算，会挪。basis 写着它是按什么假设算的。asked 里的每一项也可能带 preplan，用法一样。没有 preplan，就是这次给不出预案（还差的那一项以后不会再成立，或者入场区要等某一根 K 线出来才知道）。
- 看最新一根、持仓选“跟随账户”时，图表数据里可能有 mine：他自己的线（my_lines，比如归零线、−10% 缓冲线，都是估算）、估值参考（valuation_refs）、这只标的上的挂单（open_orders）、他检查清单里点名这只的几条（checklist）。只有这一只的，不是整个账户。
- 系统提示最后附着【我的规则】：他自己写的规则，随时会改。
- 图表数据里可能有 asked：他这一问点名的模型或标的（和屏幕上选的不是同一个时），面板用同一段代码现算的结果。回答这一问以它为准，不要拿对话前面旧的那份。

怎么回答：
- 第一句就是结论，直接回答他问的那件事。后面最多三条理由，每条一句；用到数字时只给最关键的一两个。
- 他说“展开”、要对比、要一步步讲的时候，再写长。
- 问价位（“价位在哪”“入场、止损、目标是多少”）时，先给一张表：入场区、止损、第一目标、第二目标、作废线（收盘越过就作废的那条）。有数就写数，并写明是哪个模型、哪一天的；模型没给的写“没齐，不给”。表下面只写一句：还差哪一项。不要在表前面绕。
- 清单没齐、但有 preplan 时，表下面再加一行，固定这样开头：“预案（条件齐了才算数）：入场区 …、止损 …、第一目标 …”，有第二目标、盈亏比就接着写，basis 有内容就用一句话带上。不能把预案说成现在可以进场，也不要把它填进上面那张表。他没问价位、只问“现在怎么样”时，结论后面也可以带这一行。
- 不复述他的问题，不客套，不在结尾重复“不构成投资建议”“仅供参考”之类的话：面板上已经写着了。
- 说人话：8 岁小孩也能听懂，但语气是对成年人说话，不装可爱。术语第一次出现时顺手解释一句。
- 能不用 Markdown 就不用；几条理由可以写成 1. 2. 3.。不用标题；表格只在他要对比的时候用。
- 数字只用图表数据里有的，或者能从里面直接算出来的；日期只用数据里有的交易日。
- 和这张图无关的一般性问题（指标是什么意思、某种形态怎么看）也照常回答，一样短。

几条边界：
1. 规则引擎的结论（哪一项成立、几比几、算不算信号）是代码算的，你不能改。你可以解释它、指出它的局限。规则是写死的，市场不会照着清单走：清单明显跟不上眼前走势时，直接说。
2. 新闻和原因：你只知道备注里写了的。没有备注的日子，你不知道那天发生了什么，直接说不知道，不要猜。如果这次请求开了联网搜索（他勾了，或者问的是原因、新闻时自动开的），可以去查，查到的要说明出处。
3. 不发指令、不替他做决定：不说“买”“卖”“加仓”“减仓”“把挂单改到某个价”这类话，也不替他定仓位。他问挂单、止损、要不要调、到没到线时，照【我的规则】一条条推演：现价在哪；他的挂单和线（mine 里的）各在哪、离现价多远（写出百分比）；他的规则怎么说、碰到哪条算触发。最后一句写“改不改由你定”。规则里没写的情形，就说“你的规则没写这种情况”，不要替他补。
4. 可以有你自己的看法：在规则的结论之外，可以另起一句“我自己的看法：偏多 / 偏空 / 看不清（三选一）……”，后面只跟一个最关键的价位和一条理由。不用“多半”“可能”“或许”这类含糊的词；真看不清就直说看不清。标明这不是规则，理由只用图表数据和备注里有的。
5. 凯利公式：他给了胜率和赔率时，可以算凯利比例和半凯利：f = p − (1 − p) ÷ b（p 是胜率，b 是赢一次赚的 ÷ 输一次亏的），把算式写出来；同时提醒胜率得他自己给，这里的规则都没回测过。他没给胜率时，不要编一个。
6. 这些规则没有被证明管用（四要素回测证据不足，后手战法没回测过）。他问“该不该买”时，要把这一点说在前面，然后照第 3 条推演。

用中文回答。"""


def system():
    """The system prompt with his own rules (mine.rules) appended at the end: changing the rules only changes this tail."""
    return SYSTEM + '\n\n【我的规则】（他自己写的，随时会改。推演时一条条引用；没写的情形就说没写）\n' + mine.rules()[0].strip()


def chat_dir():
    return os.environ.get('FE_CHAT_DIR') or os.path.join(panel.data_dir(), 'chats')


def now_text():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _path(cid):
    if not (isinstance(cid, str) and re.fullmatch(r'[a-f0-9]{12}', cid)):
        raise KeyError('chat')
    return os.path.join(chat_dir(), cid + '.json')


def new(ticker=None):
    return dict(id=secrets.token_hex(6), title='新对话', created=now_text(), updated=now_text(), ticker=ticker, ctx_key=None, messages=[],
                usage=dict(tokens_in=0, tokens_out=0, cache_read=0, calls=0))


def load(cid):
    try:
        with open(_path(cid), encoding='utf-8') as f:
            x = json.load(f)
        return x if isinstance(x, dict) and isinstance(x.get('messages'), list) else None
    except (OSError, ValueError, KeyError):
        return None


def save(conv):
    os.makedirs(chat_dir(), exist_ok=True)
    conv['updated'] = now_text()
    tmp = _path(conv['id']) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(conv, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _path(conv['id']))
    return conv


def delete(cid):
    try:
        os.unlink(_path(cid))
        return True
    except (OSError, KeyError):
        return False


def is_card(m):
    """An old 一键解释 message: program-built cards, not part of the conversation. Kept in the file, never shown, never sent."""
    return m.get('kind') == 'explain'


def listing(limit=60):
    """Saved conversations, newest first. Ones with no question in them (only old 一键解释 cards) are left out of the list, not deleted."""
    out = []
    try:
        names = os.listdir(chat_dir())
    except OSError:
        return out
    for n in names:
        if n.endswith('.json'):
            c = load(n[:-5])
            asks = sum(1 for m in c['messages'] if m['role'] == 'user') if c else 0
            if asks:
                u = c.get('usage') or {}
                out.append(dict(id=c['id'], title=c.get('title') or '新对话', updated=c.get('updated'), created=c.get('created'), ticker=c.get('ticker'),
                                count=sum(1 for m in c['messages'] if not is_card(m)), asks=asks,
                                tokens=sum(int(u.get(k) or 0) for k in ('tokens_in', 'tokens_out', 'cache_read', 'cache_write'))))
    out.sort(key=lambda r: r['updated'] or '', reverse=True)
    return out[:limit]


def title_from(text):
    s = re.sub(r'\s+', ' ', str(text)).strip()
    return (s[:22] + '…') if len(s) > 22 else (s or '新对话')


def api_messages(conv):
    """The stored conversation as the API wants it. Chart data rides in front of the user message it was attached to. Old 一键解释
    cards are skipped (they are not part of the conversation); a run of assistant messages is merged so roles alternate."""
    out = []
    for m in conv['messages']:
        if is_card(m):
            continue
        if m['role'] == 'user':
            blocks = []
            if m.get('context'):
                blocks.append(dict(type='text', text='【图表数据】' + m['context']))
            blocks.append(dict(type='text', text=m['text']))
            if out and out[-1]['role'] == 'user':
                out[-1]['content'] += blocks
            else:
                out.append(dict(role='user', content=blocks))
        else:
            text = m.get('text') or ''
            if not text.strip():
                continue
            if not out:         # 对话不能以助手开头（存档出了岔子才会这样）：补一句占位的话
                out.append(dict(role='user', content=[dict(type='text', text='（接着聊。）')]))
            if out[-1]['role'] == 'assistant':
                out[-1]['content'][0]['text'] += '\n\n' + text
            else:
                out.append(dict(role='assistant', content=[dict(type='text', text=text)]))
    if out and out[-1]['role'] == 'user':       # 到这里为止的全部内容都可以缓存：下一问只为新增的部分付全价
        out[-1]['content'][-1] = dict(out[-1]['content'][-1], cache_control=dict(type='ephemeral'))
    return out


def public(conv):
    """What the page gets: the conversation only (old 一键解释 cards stay in the file but are not sent), and no raw chart data
    attached to user messages (it only needs to know one was attached)."""
    msgs = []
    for m in conv['messages']:
        if is_card(m):
            continue
        x = {k: v for k, v in m.items() if k != 'context'}
        x['has_context'] = bool(m.get('context'))
        msgs.append(x)
    return dict(id=conv['id'], title=conv.get('title'), created=conv.get('created'), updated=conv.get('updated'), ticker=conv.get('ticker'),
                usage=conv.get('usage'), messages=msgs)
