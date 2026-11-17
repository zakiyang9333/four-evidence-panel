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

import panel

MAX_TEXT = 4000

SYSTEM = """你是「四要素观察面板」里的 AI 助手。使用者一边看 K 线图，一边问你问题。你像一个懂行、有耐心的朋友那样回答。

你会看到的东西：
- 用户的消息前面有时带一段【图表数据】。那是面板在那一刻用代码算好的结果：规则引擎的结论、最近 60 根日线、评分表盘、所选规则模型的清单、图上的结构线、K 线上的备注（财报日、新闻、联网搜到的、他手写的）、当天保存的 AI 解读，有时还有他在这只标的上的相关仓位。对话里可能出现好几段（他换了标的或日期），回答关于“现在这张图”的问题时，以最近的一段为准。
- 有时对话里有一条【一键解释】：那是面板用程序拼出来的大白话说明，一张张带编号的卡片。他如果问“第几张没看懂”，指的就是它。

怎么回答：
- 先给结论，再给理由。短句。一般三到六句话就够；他要你展开、要对比、要一步步讲的时候再写长。
- 说人话：8 岁小孩也能听懂，但语气是对成年人说话，不装可爱。术语第一次出现时顺手解释一句，能用生活里的比方就用。
- 可以用 Markdown（加粗、列表、表格），只在它确实让内容更好读的时候用。
- 数字只用图表数据里有的，或者能从里面直接算出来的；算的时候说清楚是怎么算的。日期只用数据里有的交易日。
- 和这张图无关的一般性问题（指标是什么意思、某种形态怎么看、风险怎么控制）也照常回答。

几条边界：
1. 规则引擎的结论（哪一项成立、几比几、算不算信号）是代码算的，你不能改。你可以解释它、指出它的局限。规则是写死的，市场不会照着清单走：清单明显跟不上眼前走势时，直接说。
2. 新闻和原因：你只知道备注里写了的。没有备注的日子，你不知道那天发生了什么，直接说不知道，不要猜。如果这次请求开了联网搜索，可以去查，查到的要说明出处。
3. 不给具体的买卖指令，不替他决定仓位。有仓位数据时遵守他的规则：核心仓按估值失效，没有价格止损；战术单四要素不到 4/4 不开。可以帮他把利弊和要看的条件摆清楚，决定由他自己做。
4. 这些规则没有被证明管用（四要素回测证据不足，后手战法没回测过）。他问“该不该买”时，要把这一点说在前面。

用中文回答。"""


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


def listing(limit=60):
    out = []
    try:
        names = os.listdir(chat_dir())
    except OSError:
        return out
    for n in names:
        if n.endswith('.json'):
            c = load(n[:-5])
            if c and c['messages']:
                out.append(dict(id=c['id'], title=c.get('title') or '新对话', updated=c.get('updated'), created=c.get('created'), ticker=c.get('ticker'),
                                count=len(c['messages'])))
    out.sort(key=lambda r: r['updated'] or '', reverse=True)
    return out[:limit]


def title_from(text):
    s = re.sub(r'\s+', ' ', str(text)).strip()
    return (s[:22] + '…') if len(s) > 22 else (s or '新对话')


def explain_text(lp):
    """The one-click explanation as plain text, so later questions can refer to it (“第 3 张卡片”)."""
    L = [f"【一键解释】{lp['ticker']} {lp['asof']} · {lp['model_name']}（程序按当天的计算结果拼的，不是 AI 写的）",
         f"今天的一句话：{lp['headline']['text']}。{lp['headline']['sub']}"]
    for n, c in enumerate(lp['cards'], 1):
        L.append(f"{n}. {c['title']}\n{c['body']}" + (f"\n今天：{c['now']}" if c.get('now') else '') +
                 ''.join(f"\n- {'是' if i['ok'] else '否'}，{i['name']} {i['text']}" for i in c.get('items') or []) + (f"\n注意：{c['note']}" if c.get('note') else ''))
    return '\n\n'.join(L)


def api_messages(conv):
    """The stored conversation as the API wants it. Chart data rides in front of the user message it was attached to; a run of
    assistant messages (an explanation followed by nothing, or two explanations) is merged so roles alternate."""
    out = []
    for m in conv['messages']:
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
            if not out:         # 对话不能以助手开头：一键解释是他点出来的，补一句他的话
                out.append(dict(role='user', content=[dict(type='text', text='（我点了“一键解释”。）')]))
            if out[-1]['role'] == 'assistant':
                out[-1]['content'][0]['text'] += '\n\n' + text
            else:
                out.append(dict(role='assistant', content=[dict(type='text', text=text)]))
    if out and out[-1]['role'] == 'user':       # 到这里为止的全部内容都可以缓存：下一问只为新增的部分付全价
        out[-1]['content'][-1] = dict(out[-1]['content'][-1], cache_control=dict(type='ephemeral'))
    return out


def public(conv):
    """What the page gets: everything except the raw chart data attached to user messages (it only needs to know one was attached)."""
    msgs = []
    for m in conv['messages']:
        x = {k: v for k, v in m.items() if k != 'context'}
        x['has_context'] = bool(m.get('context'))
        msgs.append(x)
    return dict(id=conv['id'], title=conv.get('title'), created=conv.get('created'), updated=conv.get('updated'), ticker=conv.get('ticker'),
                usage=conv.get('usage'), messages=msgs)
