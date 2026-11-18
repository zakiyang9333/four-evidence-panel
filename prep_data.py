"""Append new daily bars to this folder's data/*.csv. Usage: python3 prep_data.py [--json]

History = the CSVs already in data/ (the cloud project paths this script used to read do not exist on this Mac).
The script only ever APPENDS rows dated after the last stored row. It never rewrites, reorders or fills in
existing rows, and it never invents a bar: every appended row is copied from a named source.

Sources for new dates: the GitHub-hosted mirrors used before, plus Yahoo Finance's daily chart endpoint.
  * a source is only used if it agrees (within 0.5%) with the closes already stored for recent dates;
  * a new date seen by two or more sources is written only if their closes agree within 0.5%, otherwise it is
    NOT written, the error is reported, and appending stops there so the series never gets a hole;
  * a new date seen by one source is written with src=<name>(single) so the UI can flag it;
  * today's bar is ignored until the US session has closed (daily closes only, no intraday data).
Existing single-source rows are not edited; their second-source check goes to data/crosscheck.json instead.
"""
import csv, datetime, io, json, os, sys, urllib.request

try:
    from zoneinfo import ZoneInfo
except ImportError:                      # pragma: no cover  (python < 3.9)
    ZoneInfo = None

ROOT = os.path.dirname(os.path.abspath(__file__))
TICKERS = ('NVDA', 'QQQ', 'SPCX', 'JOBY')
MIRROR = {'NVDA': ['https://raw.githubusercontent.com/wudn9922/my-stock-screener/HEAD/data/NVDA.csv',
                   'https://raw.githubusercontent.com/Stell0/financealerts/HEAD/data/NVDA.csv',
                   'https://raw.githubusercontent.com/yennanliu/finance_data/HEAD/data/prices/nvda.csv'],
          'QQQ': ['https://raw.githubusercontent.com/yennanliu/finance_data/HEAD/data/prices/qqq.csv'],
          'SPCX': [], 'JOBY': []}          # JOBY：GitHub 上的镜像都没有它，只有 Yahoo
YAHOO = {'NVDA': 'NVDA', 'QQQ': 'QQQ', 'SPCX': 'SPCX', 'JOBY': 'JOBY'}
TOL = 0.005            # two closes "agree" when they differ by at most 0.5%
OVERLAP_DAYS = 30      # stored dates a source is checked against before it may append
OVERLAP_MIN = 5        # ... and it must cover at least this many of them
UA = {'User-Agent': 'Mozilla/5.0 (four-evidence-panel)'}


def data_dir():
    return os.environ.get('FE_DATA_DIR') or os.path.join(ROOT, 'data')


def disagree(a, b):
    return abs(a - b) > TOL * min(a, b)


def read(text):
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        r = {k.lower(): v for k, v in r.items() if k}
        try:
            out[r['date'][:10]] = [float(r[k]) for k in ('open', 'high', 'low', 'close', 'volume')]
        except (ValueError, KeyError):
            pass
    return out


def http_get(url, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read().decode()


def fetch_mirror(url):
    return read(http_get(url))


def fetch_yahoo(symbol, start):
    """Daily bars from Yahoo's chart endpoint from `start` (YYYY-MM-DD) on. Unadjusted OHLC (close, not adjclose)."""
    p1 = int(datetime.datetime.strptime(start, '%Y-%m-%d').replace(tzinfo=datetime.timezone.utc).timestamp())
    p2 = int(datetime.datetime.now(datetime.timezone.utc).timestamp()) + 86400
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={p1}&period2={p2}&interval=1d'
    res = json.loads(http_get(url, 30))['chart']
    if res.get('error'):
        raise RuntimeError(str(res['error']))
    x = res['result'][0]
    off = x['meta'].get('gmtoffset', 0)
    q = x['indicators']['quote'][0]
    out = {}
    for k, ts in enumerate(x.get('timestamp') or []):
        row = [q[f][k] for f in ('open', 'high', 'low', 'close', 'volume')]
        if any(v is None for v in row):
            continue
        d = datetime.datetime.fromtimestamp(ts + off, datetime.timezone.utc).strftime('%Y-%m-%d')
        out[d] = [round(float(v), 4) for v in row[:4]] + [float(row[4])]
    return out


def bar_complete(d, now=None):
    """True when the daily bar for date d is final: the US cash session for that date has closed."""
    if ZoneInfo is None:
        return d < datetime.date.today().isoformat()
    now = now or datetime.datetime.now(ZoneInfo('America/New_York'))
    today = now.strftime('%Y-%m-%d')
    return d < today or (d == today and (now.hour, now.minute) >= (16, 30))


def gather(t, start):
    """[(name, {date: ohlcv})], notes. One entry per source that answered."""
    out, notes = [], []
    for u in MIRROR[t]:
        name = u.split('/')[3]
        try:
            out.append((name, fetch_mirror(u)))
        except Exception as e:
            notes.append(f'镜像 {name} 取数失败：{type(e).__name__}: {e}')
    if YAHOO.get(t):
        try:
            out.append(('yahoo', fetch_yahoo(YAHOO[t], start)))
        except Exception as e:
            notes.append(f'Yahoo 取数失败：{type(e).__name__}: {e}')
    return out, notes


def update_ticker(t, sources=None, now=None):
    path = os.path.join(data_dir(), f'{t}.csv')
    with open(path, newline='') as f:
        raw = f.read()
    rows = list(csv.DictReader(io.StringIO(raw)))
    cur = {r['date']: float(r['close']) for r in rows}
    src = {r['date']: r.get('src', '') for r in rows}
    dates = sorted(cur)
    last = dates[-1]
    recent = dates[-OVERLAP_DAYS:]
    rep = dict(bars=len(dates), first=dates[0], last=last, last_src=src[last], appended=[], errors=[], notes=[], sources={})
    if sources is None:
        sources, notes = gather(t, recent[0])
        rep['notes'] += notes

    # 1. a source must agree with what is already stored before it is allowed to add anything
    trusted = []
    for name, m in sources:
        both = [d for d in recent if d in m]
        bad = [d for d in both if disagree(m[d][3], cur[d])]
        info = dict(rows=len(m), last=max(m) if m else None, overlap=len(both), trusted=False)
        if bad:
            rep['errors'].append(f'来源 {name} 与已存收盘价不一致（{", ".join(bad[:5])}{" 等" if len(bad) > 5 else ""}），本次不采用它。')
        elif len(both) < OVERLAP_MIN:
            rep['notes'].append(f'来源 {name} 与已存数据重叠不足 {OVERLAP_MIN} 天，无法核对，本次不采用它。')
        else:
            info['trusted'] = True
            trusted.append((name, m))
        rep['sources'][name] = info

    # 2. second-source check of stored single-source rows (side file; the CSV rows stay as they are)
    check = {}
    for d in dates:
        if '(single)' not in src[d]:
            continue
        own = src[d].split('(')[0]
        others = [(n, m[d][3]) for n, m in sources if n != own and d in m]
        if others:
            n2, c2 = others[0]
            ok = not disagree(c2, cur[d])
            check[d] = dict(source=n2, close=c2, stored=cur[d], diff_pct=round((c2 / cur[d] - 1) * 100, 3), ok=ok)
            if not ok:
                rep['errors'].append(f'{d} 是单一来源的行，{n2} 的收盘 {c2} 与已存的 {cur[d]} 相差超过 0.5%。')
    rep['crosscheck'] = check

    # 3. append new, completed dates
    lines = []
    new_dates = sorted({d for _, m in trusted for d in m if d > last and bar_complete(d, now)})
    for d in new_dates:
        have = [(n, m[d]) for n, m in trusted if d in m]
        cl = [v[3] for _, v in have]
        if len(have) > 1 and disagree(max(cl), min(cl)):
            rep['errors'].append(f'{d}：来源收盘价不一致（' + '，'.join(f'{n} {v[3]}' for n, v in have)
                                 + '），相差超过 0.5%，这一天和之后的日期都没有写入。')
            break
        tag = '+'.join(n for n, _ in have) + ('(single)' if len(have) == 1 else '')
        buf = io.StringIO()
        csv.writer(buf).writerow([d] + [round(x, 6) for x in have[0][1]] + [tag])
        lines.append(buf.getvalue())
        rep['appended'].append(dict(date=d, close=have[0][1][3], src=tag))
    if lines:
        with open(path, 'a', newline='') as f:          # append only: bytes already in the file are not touched
            if raw and not raw.endswith('\n'):
                f.write('\r\n')
            f.write(''.join(lines))
        rep['bars'] += len(lines)
        rep['last'] = rep['appended'][-1]['date']
        rep['last_src'] = rep['appended'][-1]['src']
    return rep


def main(as_json=False):
    rep = {}
    for t in TICKERS:
        try:
            rep[t] = update_ticker(t)
        except Exception as e:
            rep[t] = dict(appended=[], errors=[f'刷新失败：{type(e).__name__}: {e}'], notes=[], sources={}, crosscheck={})
    cc_path = os.path.join(data_dir(), 'crosscheck.json')
    try:
        try:
            with open(cc_path, encoding='utf-8') as f:
                cc = json.load(f)
        except (OSError, ValueError):
            cc = {}
        for t in TICKERS:                       # keep earlier checks when a source is unreachable this time
            cc.setdefault(t, {}).update(rep[t].get('crosscheck', {}))
        with open(cc_path, 'w', encoding='utf-8') as f:
            json.dump(cc, f, ensure_ascii=False, indent=1)
    except OSError as e:
        rep[TICKERS[0]]['notes'].append(f'crosscheck.json 写入失败：{e}')
    # 这次刷新的结果，给面板显示“上次刷新”用（按钮和定时任务都会写）
    summary = dict(at=datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                   trigger=os.environ.get('FE_REFRESH_TRIGGER', 'manual'),
                   has_error=any(rep[t].get('errors') for t in TICKERS),
                   tickers={t: dict(last=rep[t].get('last'), appended=[a['date'] for a in rep[t].get('appended', [])],
                                    errors=rep[t].get('errors', []), notes=rep[t].get('notes', [])) for t in TICKERS})
    try:
        tmp = os.path.join(data_dir(), '.last_refresh.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=1)
        os.replace(tmp, os.path.join(data_dir(), 'last_refresh.json'))
    except OSError:
        pass
    if as_json:
        print(json.dumps(rep, ensure_ascii=False))
    else:
        for t in TICKERS:
            r = rep[t]
            print(t, {k: r.get(k) for k in ('bars', 'first', 'last', 'last_src')}, '新增', [a['date'] for a in r['appended']],
                  '错误', r['errors'], '提示', r['notes'])
    return rep


if __name__ == '__main__':
    main('--json' in sys.argv)
