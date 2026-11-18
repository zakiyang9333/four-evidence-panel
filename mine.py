"""zaki 自己的本机设定：我的规则、忽略的仓位、提醒、每天自动联网的次数。

全部存在 data/quant/（和盯盘任务同一个目录，不进 git；测试用 FE_TASKS_DIR 指到临时目录），不往外发。
- 我的规则（my_rules.md）：他自己写、自己改。AI 对话回答挂单、止损、要不要调这类问题时，照这里一条条推演。
- 忽略的仓位（pf_ignore.json）：持仓文件由云端线程写、面板只读，所以“忽略这一笔”记在这里，不碰持仓文件。
  被忽略的仓位不进 AI 的上下文、不画到图上，持仓页上灰着显示。
- 提醒（notify.json）：盯盘任务条件齐了、收盘碰到他持仓里的线，发 Mac 通知和/或 iMessage。
  iMessage 走 Apple 的服务，所以发到手机的那条不带任何持仓数字，只说哪只、什么事、打开面板看。
- 自动联网（auto_web.json）：问“为什么跌”这类问题时自动联网查，每天有上限（按次计费）。
"""
import datetime
import json
import os
import re
import subprocess
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
_lock = threading.RLock()


def sdir():
    return os.environ.get('FE_TASKS_DIR') or os.path.join(os.environ.get('FE_DATA_DIR') or os.path.join(ROOT, 'data'), 'quant')


def _read(name, default):
    try:
        with open(os.path.join(sdir(), name), encoding='utf-8') as f:
            x = json.load(f) if name.endswith('.json') else f.read()
        return x if isinstance(x, type(default)) else default
    except (OSError, ValueError):
        return default


def _write(name, data):
    os.makedirs(sdir(), exist_ok=True)
    path = os.path.join(sdir(), name)
    with open(path + '.tmp', 'w', encoding='utf-8') as f:
        if name.endswith('.json'):
            json.dump(data, f, ensure_ascii=False, indent=1)
        else:
            f.write(data)
    os.replace(path + '.tmp', path)


# ---------- 我的规则 ----------

RULES_FILE = 'my_rules.md'
MAX_RULES = 6000
RULES_SEED = """# 我的规则

这是你自己的规则。AI 对话回答挂单、止损、要不要调这类问题时，会照这里一条条推演：现价落在哪、离你的线多远、碰到哪条算触发。改不改由你定。
写成短句，一条一行。没写的情形，它会说“你的规则没写这种情况”，不会替你补。

## 仓位
- 核心仓按估值失效，没有价格止损。
- 战术单：四要素不到 4/4 不开。

## 止损
（还没写）

## 止盈 / 卖出
（还没写）

## 加仓 / 分批
（还没写）
"""


def rules():
    """(text, saved): the rules he wrote, or the starting template if he never saved any."""
    t = _read(RULES_FILE, '')
    return (t, True) if t.strip() else (RULES_SEED, False)


def save_rules(text):
    text = str(text or '').replace('\r\n', '\n').strip()
    if len(text) > MAX_RULES:
        raise ValueError(f'规则太长了（最多 {MAX_RULES} 个字）')
    with _lock:
        _write(RULES_FILE, text + '\n')
    return rules()[0]


# ---------- 忽略的仓位 ----------

IGNORE_FILE = 'pf_ignore.json'


def pos_key(p):
    """A stable name for one position (the file has no ids): symbol, type, strike, expiry, and the broker for other accounts."""
    return '|'.join(str(p.get(k) if p.get(k) is not None else '') for k in ('broker', 'symbol', 'type', 'strike', 'expiry')).strip('|') if isinstance(p, dict) else ''


def ignored():
    return set(x for x in _read(IGNORE_FILE, []) if isinstance(x, str))


def set_ignored(key, on):
    key = str(key or '').strip()
    if not key or len(key) > 200:
        raise ValueError('不认识这一笔仓位')
    with _lock:
        cur = ignored()
        cur.add(key) if on else cur.discard(key)
        _write(IGNORE_FILE, sorted(cur))
    return sorted(cur)


# ---------- 自动联网：每天最多几次 ----------

AUTO_WEB_FILE = 'auto_web.json'
WHY = re.compile(r'为什么|为啥|怎么回事|发生了什么|什么原因|啥原因|原因是|有什么消息|什么消息|消息面|新闻|利好|利空|公告|突发')


def wants_news(text):
    """Does the question ask about a cause or news (the kind of thing only a web search can answer)?"""
    return bool(WHY.search(str(text or '')))


def auto_web_take(cap, today=None):
    """Use one of today's automatic web searches. False when today's cap is used up (or the cap is 0)."""
    today = today or datetime.date.today().isoformat()
    with _lock:
        d = _read(AUTO_WEB_FILE, {})
        n = int(d.get(today) or 0)
        if cap <= 0 or n >= cap:
            return False
        _write(AUTO_WEB_FILE, {today: n + 1})
        return True


def auto_web_used(today=None):
    return int(_read(AUTO_WEB_FILE, {}).get(today or datetime.date.today().isoformat()) or 0)


# ---------- 提醒 ----------

NOTIFY_FILE = 'notify.json'
SENT_FILE = 'notify_sent.json'          # 发过的提醒（按键去重），只留最近的
HANDLE = re.compile(r'^(\+?[0-9][0-9 \-]{5,19}|[^@\s]{1,64}@[^@\s]{1,190})$')


def notify_settings():
    s = _read(NOTIFY_FILE, {})
    return dict(mac=bool(s.get('mac')), imessage=str(s.get('imessage') or ''))


def save_notify(mac=None, imessage=None):
    with _lock:
        s = notify_settings()
        if mac is not None:
            s['mac'] = bool(mac)
        if imessage is not None:
            h = str(imessage).strip()
            if h and not HANDLE.match(h):
                raise ValueError('iMessage 要填手机号（可以带 +86）或 Apple ID 邮箱')
            s['imessage'] = h
        _write(NOTIFY_FILE, s)
    return s


def _osascript(lines, args):
    if os.environ.get('FE_NOTIFY_DRY'):          # 测试：不真的弹、不真的发，写进一个文件让测试核对
        with _lock:
            log = _read('notify_dry.json', [])
            log.append(dict(lines=lines, args=args))
            _write('notify_dry.json', log[-50:])
        return True
    try:
        cmd = ['osascript']
        for ln in ['on run argv'] + lines + ['end run']:
            cmd += ['-e', ln]
        p = subprocess.run(cmd + ['--'] + list(args), capture_output=True, text=True, timeout=20)
        return p.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def send(key, mac_text, phone_text, title='四要素面板', force=False):
    """One reminder. mac_text may carry details (it stays on this Mac); phone_text goes through iMessage, so it must not carry
    any position numbers. key de-duplicates: the same reminder is sent once. Returns which channels went out."""
    s = notify_settings()
    with _lock:
        sent = _read(SENT_FILE, [])
        if not force and key in sent:
            return []
        out = []
        if s['mac'] and _osascript(['display notification (item 1 of argv) with title (item 2 of argv)'], [mac_text, title]):
            out.append('mac')
        if s['imessage'] and _osascript(['tell application "Messages"',
                                         'send (item 1 of argv) to participant (item 2 of argv) of (1st account whose service type = iMessage)',
                                         'end tell'], [title + '：' + phone_text, s['imessage']]):
            out.append('imessage')
        if not force:
            _write(SENT_FILE, (sent + [key])[-500:])
        return out
