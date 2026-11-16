"""K 线上的「时效与备注」：那一天发生过什么（zaki 2026-11-16）。

四种来源，各带来源名和抓取时间：
- event  事件日：财报日、除息日、拆股日。来自 Yahoo Finance，有历史，也有下一次。算“事实”。
- news   新闻标题：每次刷新数据时把 Yahoo 当下给的那几条标题存下来（只存标题、媒体名、链接，不存正文）。
         Yahoo 只给最近十来条，所以存档只能从开始存的那天往后才有，过去的补不回来。
- search Claude 联网搜到的：指定某几天去搜，花钱；每条都必须带着搜索结果里真实出现过的链接，对不上的丢掉。
- manual 你自己写的。

规矩：这些只是备注，不进规则引擎，不改任何证据的判定。回放到某一天时，只给那一天以及之前的备注。
存在本机 data/notes/<代码>.json（手写的内容是你自己的，不进 git）。
用法：python3 notes.py --refresh   （定时任务用：更新三只票的事件日和新闻存档）
"""
import bisect
import datetime
import hashlib
import json
import os
import re
import sys
import threading
import time

import panel

EVENTS_STALE_DAYS = 7           # 事件日历超过这么多天没更新，就标“可能过时”
NEWS_PER_DAY = 12               # 每天最多留几条标题
KINDS = dict(earnings='财报日', dividend='除息日', split='拆股日', news='新闻标题', search='联网搜到的', manual='手写备注')
NAMES = dict(SPCX='Space Exploration Technologies (SpaceX)', NVDA='NVIDIA', QQQ='Invesco QQQ Trust / Nasdaq-100')
_lock = threading.RLock()


def notes_dir():
    return os.environ.get('FE_NOTES_DIR') or os.path.join(panel.data_dir(), 'notes')


def _path(t):
    if t not in panel.TICKERS:
        raise KeyError(t)
    return os.path.join(notes_dir(), t + '.json')


def now_text(now=None):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))


def load(t):
    try:
        with open(_path(t), encoding='utf-8') as f:
            x = json.load(f)
        if isinstance(x, dict):
            x.setdefault('events', dict(fetched_at=None, source=None, items=[]))
            x.setdefault('items', [])
            x.setdefault('searched', {})
            return x
    except (OSError, ValueError):
        pass
    return dict(ticker=t, events=dict(fetched_at=None, source=None, items=[]), items=[], searched={})


def save(t, x):
    os.makedirs(notes_dir(), exist_ok=True)
    tmp = _path(t) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(x, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _path(t))


def _id(*parts):
    return hashlib.sha256('|'.join(str(p) for p in parts).encode('utf-8')).hexdigest()[:12]


def _is_day(s):
    return isinstance(s, str) and bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', s))


# ---------- Yahoo: event days and today's headlines (network; injectable for tests) ----------

def yahoo_events(t):
    """[{date, kind, title}] from Yahoo Finance: past and scheduled earnings days, ex-dividend days, splits."""
    import warnings
    warnings.filterwarnings('ignore')
    import yfinance as yf
    k = yf.Ticker(t)
    out = []
    try:
        ed = k.get_earnings_dates(limit=40)
        for x in (ed.index if ed is not None else []):
            out.append(dict(date=str(x)[:10], kind='earnings', title='财报日'))
    except Exception:       # noqa: BLE001 — ETF 没有财报日，或者 Yahoo 这次没给
        pass
    a = k.actions
    if a is not None and len(a):
        for day, row in a.iterrows():
            d = str(day)[:10]
            div, sp = float(row.get('Dividends', 0) or 0), float(row.get('Stock Splits', 0) or 0)
            if div:
                out.append(dict(date=d, kind='dividend', title=f'除息日，每股派 {div:g}'))
            if sp:
                out.append(dict(date=d, kind='split', title=f'拆股，1 股变 {sp:g} 股'))
    return out


def yahoo_headlines(t):
    """[{date, title, source, url}]: whatever headlines Yahoo lists for this ticker right now (titles and links only)."""
    import warnings
    warnings.filterwarnings('ignore')
    import yfinance as yf
    out = []
    for n in yf.Ticker(t).news or []:
        c = n.get('content') or n
        when = c.get('pubDate') or c.get('displayTime')
        url = ((c.get('canonicalUrl') or {}).get('url') if isinstance(c.get('canonicalUrl'), dict) else None) or \
              ((c.get('clickThroughUrl') or {}).get('url') if isinstance(c.get('clickThroughUrl'), dict) else None)
        prov = (c.get('provider') or {}).get('displayName') if isinstance(c.get('provider'), dict) else None
        if not (c.get('title') and when and url):
            continue
        try:        # 发布时间换成美东的日期：美股按那边的日子算
            from zoneinfo import ZoneInfo
            dt = datetime.datetime.fromisoformat(str(when).replace('Z', '+00:00')).astimezone(ZoneInfo('America/New_York'))
        except ValueError:
            continue
        out.append(dict(date=dt.strftime('%Y-%m-%d'), title=str(c['title']).strip()[:200], source=prov or 'Yahoo Finance', url=url))
    return out


def refresh(t, events=None, headlines=None, now=None):
    """Update the event calendar and add today's headlines to the archive. Returns a small report; never raises on network trouble."""
    rep = dict(ticker=t, events=None, news_added=0, errors=[])
    with _lock:
        x = load(t)
        try:
            ev = (events or yahoo_events)(t)
            ev = sorted({(e['date'], e['kind'], e['title']) for e in ev if _is_day(e.get('date')) and e.get('kind') in KINDS})
            if ev or events is not None:
                x['events'] = dict(fetched_at=now_text(now), source='Yahoo Finance', items=[dict(date=d, kind=k, title=ti) for d, k, ti in ev])
                rep['events'] = len(ev)
        except Exception as e:      # noqa: BLE001
            rep['errors'].append('事件日没取到：' + type(e).__name__)
        try:
            seen = {i.get('url') for i in x['items'] if i['kind'] == 'news'}
            per = {}
            for i in x['items']:
                if i['kind'] == 'news':
                    per[i['date']] = per.get(i['date'], 0) + 1
            for h in (headlines or yahoo_headlines)(t):
                if not _is_day(h.get('date')) or h['url'] in seen or per.get(h['date'], 0) >= NEWS_PER_DAY:
                    continue
                seen.add(h['url']); per[h['date']] = per.get(h['date'], 0) + 1
                x['items'].append(dict(id=_id('news', h['url']), date=h['date'], kind='news', title=h['title'], source=h['source'], url=h['url'],
                                       fetched_at=now_text(now), by='yahoo'))
                rep['news_added'] += 1
            x.setdefault('news_since', now_text(now)[:10])
        except Exception as e:      # noqa: BLE001
            rep['errors'].append('新闻标题没取到：' + type(e).__name__)
        save(t, x)
    return rep


def refresh_all():
    if os.environ.get('FE_NOTES_OFFLINE') == '1':      # 测试时不连 Yahoo
        return []
    return [refresh(t) for t in panel.TICKERS]


# ---------- manual notes ----------

def add_manual(t, date, text, now=None):
    text = str(text or '').strip()
    if not text:
        raise ValueError('备注是空的')
    if date not in panel.load(t)['B']['d']:
        raise ValueError('这一天不是这只标的的交易日')
    with _lock:
        x = load(t)
        item = dict(id=_id('manual', date, text, time.time()), date=date, kind='manual', title=text[:300], source='你自己写的', url=None,
                    fetched_at=now_text(now), by='manual')
        x['items'].append(item)
        save(t, x)
    return item


def delete(t, item_id):
    with _lock:
        x = load(t)
        n = len(x['items'])
        x['items'] = [i for i in x['items'] if i.get('id') != item_id]
        save(t, x)
        return n - len(x['items'])


# ---------- 英文标题翻成中文（zaki 11-16：备注要是中文的）----------

def pending_translation(t, limit=40):
    """Archived headlines that have no Chinese version yet (newest first). Each headline is translated once and stored."""
    x = load(t)
    rows = [i for i in x['items'] if i['kind'] == 'news' and not i.get('title_zh') and not i.get('zh_failed') and re.search(r'[A-Za-z]{3}', i.get('title') or '')]
    rows.sort(key=lambda i: i['date'], reverse=True)
    return rows[:limit]


def store_translation(t, ids, zh, meta, now=None):
    """Keep a translation only if it lines up with its headline and actually is Chinese; otherwise the English stays (and is not retried)."""
    ok = isinstance(zh, list) and len(zh) == len(ids)
    with _lock:
        x = load(t)
        by = {i['id']: i for i in x['items']}
        done = 0
        for k, item_id in enumerate(ids):
            it = by.get(item_id)
            if it is None:
                continue
            text = str(zh[k]).strip() if ok and isinstance(zh[k], str) else ''
            if text and re.search(r'[\u4e00-\u9fff]', text) and len(text) <= 200:
                it.update(title_zh=text, translated_at=now_text(now), translated_by=meta.get('model'))
                done += 1
            else:
                it['zh_failed'] = True
        save(t, x)
    return done


# ---------- reading ----------

def bar_date(days, date):
    """The trading day a dated note belongs to: that day, or the next session if the market was closed (weekend news lands on Monday's bar)."""
    k = bisect.bisect_left(days, date)
    return days[k] if k < len(days) else None


def notable_days(t, asof=None, n=5, win=60):
    """Days in the last `win` bars worth asking “what happened?”: the biggest moves and volume spikes, with a plain reason."""
    B = panel.load(t)['B']
    i = panel.index_at(B, asof) if asof else len(B['d']) - 1
    out = []
    for j in range(max(21, i - win + 1), i + 1):
        chg = float(B['c'][j] / B['c'][j - 1] - 1) * 100
        gap = float(B['o'][j] / B['c'][j - 1] - 1) * 100
        vr = float(B['v'][j] / B['v'][j - 20:j].mean())
        score = abs(chg) + abs(gap) + max(0.0, vr - 1) * 2
        why = f"{'涨' if chg >= 0 else '跌'} {abs(chg):.1f}%" + (f"，跳空{'高' if gap > 0 else '低'}开 {abs(gap):.1f}%" if abs(gap) >= 2 else '') + \
              (f'，成交量是前 20 天平均的 {vr:.1f} 倍' if vr >= 1.5 else '')
        out.append(dict(date=B['d'][j], chg_pct=round(chg, 2), gap_pct=round(gap, 2), vol_ratio=round(vr, 2), score=round(score, 2), why=why))
    out.sort(key=lambda r: -r['score'])
    return sorted(out[:n], key=lambda r: r['date'])


def payload(t, asof=None, now=None):
    """Everything the chart shows for this ticker as of `asof`: notes per bar, the next scheduled event, and how fresh each source is."""
    B = panel.load(t)['B']
    days = B['d']
    i = panel.index_at(B, asof) if asof else len(days) - 1
    cut, latest = days[i], i == len(days) - 1
    x = load(t)
    by, n = {}, 0
    for e in x['events']['items']:
        if e['date'] <= cut:
            d = bar_date(days, e['date'])
            if d and d <= cut:
                by.setdefault(d, []).append(dict(e, id=_id('event', e['date'], e['kind'], e['title']), source=x['events']['source'], url=None,
                                                 fetched_at=x['events']['fetched_at'], by='yahoo', fact=True))
    for it in x['items']:
        if it['date'] <= cut:
            d = bar_date(days, it['date'])
            if d and d <= cut:
                by.setdefault(d, []).append(dict(it, fact=False))
                n += 1
    order = dict(earnings=0, split=1, dividend=2, manual=3, search=4, news=5)
    for d in by:
        by[d].sort(key=lambda r: order.get(r['kind'], 9))
    upcoming = None
    if latest:      # 下一次财报：只在看最新一根时给。回放时不给，免得把“后来才知道的日程”带回过去
        today = time.strftime('%Y-%m-%d', time.localtime(now))
        fut = sorted(e['date'] for e in x['events']['items'] if e['kind'] == 'earnings' and e['date'] > cut and e['date'] >= today)
        if fut:
            days_left = (datetime.date.fromisoformat(fut[0]) - datetime.date.fromisoformat(today)).days
            upcoming = dict(date=fut[0], kind='earnings', title='下一次财报', days_left=days_left)
    fa = x['events']['fetched_at']
    age = None
    if fa:
        age = (time.mktime(time.localtime(now)) - time.mktime(time.strptime(fa, '%Y-%m-%d %H:%M:%S'))) / 86400
    # 最后一根 K 线之后的消息（比如今天还没收盘）：没有 K 线可挂，单独列出来。只在看最新一根时给
    pending = sorted((it for it in x['items'] if it['date'] > days[-1]), key=lambda r: (r['date'], r.get('fetched_at') or ''), reverse=True)[:20] if latest else []
    news = [it for it in x['items'] if it['kind'] == 'news' and (it['date'] <= cut or latest)]
    fresh = dict(events_fetched_at=fa, events_source=x['events']['source'], events_stale=bool(fa is None or age > EVENTS_STALE_DAYS),
                 headlines=len(news), headlines_zh=sum(1 for it in news if it.get('title_zh')),
                 untranslated=sum(1 for it in news if not it.get('title_zh') and not it.get('zh_failed') and re.search(r'[A-Za-z]{3}', it.get('title') or '')),
                 events_age_days=None if age is None else round(age, 1), news_since=x.get('news_since'),
                 searched_days=sorted(d for d in x['searched'] if d <= cut), counts=dict(events=sum(1 for v in by.values() for r in v if r['fact']), notes=n))
    return dict(ok=True, ticker=t, asof=cut, is_latest=latest, by_date=by, upcoming=upcoming, freshness=fresh, kinds=KINDS, pending=pending,
                notable=[dict(r, searched=r['date'] in x['searched']) for r in notable_days(t, cut)])


def for_ai(t, asof, bars=60):
    """What the AI reading is told: notes of the last `bars` bars (date, kind, title, source), the next earnings day, and what is NOT known."""
    p = payload(t, asof)
    days = panel.load(t)['B']['d']
    i = days.index(p['asof'])
    lo = days[max(0, i - bars + 1)]
    rows = [dict(date=d, kind=KINDS.get(r['kind'], r['kind']), text=r.get('title_zh') or r['title'], source=r.get('source'), fact=bool(r.get('fact')))
            for d in sorted(p['by_date']) if d >= lo for r in p['by_date'][d]][-40:]
    f = p['freshness']
    return dict(notes=rows, next_earnings=p['upcoming'], events_updated=f['events_fetched_at'], events_may_be_stale=f['events_stale'],
                news_archive_since=f['news_since'], days_searched_online=f['searched_days'],
                coverage='事件日（财报、除息、拆股）有完整历史；新闻标题只从 news_archive_since 那天起才有存档；其余日子只有联网搜过或手写过的才有备注。没有备注不等于那天没事发生。')


def count_since(t, asof, since_text):
    """How many notes were added after `since_text` (a reading's creation time) for bars up to `asof`."""
    if not since_text:
        return 0
    x = load(t)
    cut = panel.load(t)['B']['d'][panel.index_at(panel.load(t)['B'], asof)] if asof else '9999'
    return sum(1 for it in x['items'] if it['date'] <= cut and (it.get('fetched_at') or '') > since_text)


# ---------- Claude web search results: checked before they are stored ----------

def _urls(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == 'url' and isinstance(v, str):
                out.add(_norm(v))
            else:
                _urls(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _urls(v, out)


def _norm(u):
    u = re.sub(r'[#?].*$', '', str(u).strip())
    return re.sub(r'^https?://(www\.)?', '', u).rstrip('/').lower()


def verify_search(message, dates):
    """Keep only what the search actually returned. `message` = the API response as a dict.
    An item survives only if its link appears among the links in the web-search result blocks or citations of this same response
    (so a link Claude merely wrote in its answer does not count), its date is one of the asked days (±3 days), and it has a summary.
    Returns (kept items, number dropped, number of searches run)."""
    seen = set()
    text, searches = '', 0
    for blk in message.get('content') or []:
        if not isinstance(blk, dict):
            continue
        if blk.get('type') == 'text':
            text += blk.get('text') or ''
            _urls(blk.get('citations') or [], seen)
        else:
            if blk.get('type') == 'server_tool_use' and blk.get('name') == 'web_search':
                searches += 1
            _urls(blk.get('content'), seen)
    m = re.search(r'\{[\s\S]*\}', text)
    try:
        raw = json.loads(m.group(0)) if m else {}
    except ValueError:
        raw = {}
    kept, dropped = [], 0
    asked = [datetime.date.fromisoformat(d) for d in dates]
    for it in raw.get('items') or []:
        if not isinstance(it, dict):
            dropped += 1
            continue
        d, what, url = it.get('date'), str(it.get('what') or '').strip(), str(it.get('url') or '').strip()
        ok = _is_day(d) and what and url and _norm(url) in seen
        if ok:
            dd = datetime.date.fromisoformat(d)
            ok = any(abs((dd - a).days) <= 3 for a in asked)
        if not ok:
            dropped += 1
            continue
        kept.append(dict(date=d, title=what[:160], source=str(it.get('source') or '').strip()[:60] or _norm(url).split('/')[0], url=url))
    return kept, dropped, searches


def store_search(t, dates, kept, meta, now=None):
    with _lock:
        x = load(t)
        have = {i.get('url') for i in x['items'] if i['kind'] == 'search'}
        added = 0
        for it in kept:
            if it['url'] in have:
                continue
            have.add(it['url'])
            x['items'].append(dict(id=_id('search', it['url']), date=it['date'], kind='search', title=it['title'], source=it['source'], url=it['url'],
                                   fetched_at=now_text(now), by='claude_search'))
            added += 1
        for d in dates:
            x['searched'][d] = dict(at=now_text(now), found=sum(1 for it in kept if it['date'] == d), **meta)
        save(t, x)
    return added


if __name__ == '__main__':
    if '--refresh' in sys.argv:
        for r in refresh_all():
            print(json.dumps(r, ensure_ascii=False))
    else:
        print(__doc__)
