"""「持仓」页的数据层。只读 portfolio/ 里的文件，从不写、不改、不删它们。

portfolio/portfolio_state.json  由云端的持仓分析线程写入，面板只读。
portfolio/*_app.md              App 快照原文，页面底部原样渲染。

约定：
  * 文件里没有的字段，这里不补、不猜，前端显示“—”。唯一的例外是浮盈亏：文件没有这一列，
    按 (现价 − 成本) × 数量（期权每张 100 股）算出来，并标“估算”。
  * 持仓是个人账户信息：不写日志，不出本机；发给 Claude API 的只有当前标的相关的仓位（relevant_positions）。
  * 四证状态调用 four_evidence_check.py --json，本文件不判定任何规则。
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = 'portfolio_state.json'
CHART_TICKERS = ('SPCX', 'NVDA', 'QQQ')          # 有 K 线数据、能做四证检查的标的
STALE_HOURS = 24
VAL_LABELS = {'V4_base': 'V4 Base', 'sotp': 'SOTP', 'V4_bull': 'V4 Bull', 'mos30': '30% 安全边际价'}
TP_KEYS = ('take_profit', 'take_profit_price', 'tp')
R_KEYS = ('r_definition', 'r_def', 'r', 'R')

_lock = threading.Lock()
_check_cache = {}


def pdir():
    return os.environ.get('FE_PORTFOLIO_DIR') or os.path.join(ROOT, 'portfolio')


def num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) != float('inf') else None


def snapshots():
    """Snapshot files, newest first: [{name, date, mtime}]. Date comes from the file name (YYYY-MM-DD_app.md)."""
    out = []
    try:
        names = os.listdir(pdir())
    except OSError:
        return out
    for n in names:
        m = re.match(r'^(\d{4}-\d{2}-\d{2}).*_app\.md$', n)
        if not m:
            continue
        try:
            st = os.stat(os.path.join(pdir(), n))
        except OSError:
            continue
        out.append(dict(name=n, date=m.group(1), mtime=st.st_mtime, _k=(st.st_mtime_ns, st.st_size)))
    out.sort(key=lambda s: (s['date'], s['mtime']), reverse=True)
    return out


def snapshot_text(name):
    """Text of one snapshot. Only names that snapshots() lists are served."""
    if name not in {s['name'] for s in snapshots()}:
        return None
    try:
        with open(os.path.join(pdir(), name), encoding='utf-8') as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def version():
    """Changes whenever the state file or any snapshot is modified, added or removed."""
    parts = []
    try:
        st = os.stat(os.path.join(pdir(), STATE_FILE))
        parts.append((STATE_FILE, st.st_mtime_ns, st.st_size))
    except OSError:
        parts.append((STATE_FILE, None))
    parts += [(s['name'],) + s['_k'] for s in snapshots()]
    return hashlib.sha1(repr(parts).encode()).hexdigest()[:16]


def read_state():
    """(state, error_code). error_code: None | 'missing' | 'invalid'."""
    path = os.path.join(pdir(), STATE_FILE)
    try:
        with open(path, encoding='utf-8') as f:
            st = json.load(f)
    except FileNotFoundError:
        return None, 'missing'
    except (OSError, ValueError):
        return None, 'invalid'          # e.g. read while the sync is still writing: the next check picks it up
    return (st, None) if isinstance(st, dict) else (None, 'invalid')


def age_hours(asof, now=None):
    """Hours since asof_taipei (ISO 8601 with offset). None if it cannot be read."""
    try:
        t = datetime.datetime.fromisoformat(str(asof))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8)))      # the field is Taipei time
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return (now - t).total_seconds() / 3600


def chart_ticker(p):
    """Which K-line the position is read through: its `underlying` field if it has one, else its own symbol."""
    s = str(p.get('underlying') or p.get('symbol') or '').upper().strip()
    if s.endswith('USDT'):
        s = s[:-4]
    return s if s in CHART_TICKERS else None


def four_checks(tickers):
    """{ticker: result of `four_evidence_check.py --json`}. Cached until the data, the script or the engine changes."""
    tickers = sorted(set(tickers))
    if not tickers:
        return {}
    files = ['four_evidence_check.py', 'engine.py'] + [f'data/{t}.csv' for t in tickers]
    try:
        key = (tuple(tickers),) + tuple(os.stat(os.path.join(ROOT, f)).st_mtime_ns for f in files)
    except OSError:
        return {}
    with _lock:
        if _check_cache.get('key') == key:
            return _check_cache['val']
    try:
        p = subprocess.run([sys.executable, '-I', os.path.join(ROOT, 'four_evidence_check.py'), *tickers, '--json'],
                           cwd=ROOT, capture_output=True, text=True, timeout=60)
        res = {o['ticker']: {k: o.get(k) for k in ('ticker', 'asof', 'close', 'armed', 'score', 'state', 'low_stale')}
               for o in json.loads(p.stdout)}
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        return {}
    with _lock:
        _check_cache.update(key=key, val=res)
    return res


def overlays(st):
    """Horizontal lines for the chart, per ticker: {'SPCX': {'lines': [...], 'valuation': [...]}}. Display only."""
    out = {}

    def add(t, group, price, label, kind, est=False):
        if t in CHART_TICKERS and num(price) is not None:
            out.setdefault(t, dict(lines=[], valuation=[]))[group].append(dict(price=price, label=label, kind=kind, est=est))

    for p in st.get('positions') or []:
        if not isinstance(p, dict):
            continue
        sym, typ = str(p.get('symbol') or '').upper(), p.get('type')
        if typ == 'stock':
            add(sym, 'lines', p.get('avg_cost'), f'持仓成本 {sym}', 'cost')
        elif typ == 'put' and (num(p.get('qty')) or 0) < 0:
            k = num(p.get('strike'))
            if k is not None:
                add(str(p.get('underlying') or '').upper(), 'lines', k, f'短 put 行权价 {k:g}（{abs(p["qty"]):g} 张）', 'strike')
    for k, v in (st.get('lines') or {}).items():
        for t in CHART_TICKERS:
            if k == f'{t}_bp_zero_est':
                add(t, 'lines', v, '归零线（估算）', 'zero', True)
    for k, v in (st.get('valuation_refs') or {}).items():
        for t in CHART_TICKERS:
            if k.startswith(t + '_'):
                add(t, 'valuation', v, '估值参考 ' + VAL_LABELS.get(k[len(t) + 1:], k[len(t) + 1:]), 'valuation')
    for a in st.get('other_accounts') or []:
        if not isinstance(a, dict):
            continue
        t = chart_ticker(a)
        who = f"{a.get('broker') or '其它账户'}{'空单' if a.get('side_dir') == 'short' else '多单' if a.get('side_dir') == 'long' else '仓位'}"
        add(t, 'lines', a.get('entry'), who + '开仓价', 'entry')
        for key in TP_KEYS:
            if num(a.get(key)) is not None:
                add(t, 'lines', a[key], who + '止盈价', 'tp')
                break
    return out


def relevant_positions(ticker, now=None):
    """Only the positions tied to `ticker`, for the AI prompt. No account totals. None when there is nothing to send."""
    st, err = read_state()
    if err or ticker not in CHART_TICKERS:
        return None
    rows = []
    for p in st.get('positions') or []:
        if isinstance(p, dict) and chart_ticker(p) == ticker:
            row = {k: p[k] for k in ('symbol', 'type', 'qty', 'avg_cost', 'side', 'underlying', 'strike', 'expiry', 'note') if k in p}
            row['r_definition'] = next((p[k] for k in R_KEYS if k in p), None)      # 文件没给就是 None，不编
            rows.append(row)
    for a in st.get('other_accounts') or []:
        if isinstance(a, dict) and chart_ticker(a) == ticker:
            row = {k: a[k] for k in ('broker', 'symbol', 'type', 'side_dir', 'qty', 'entry', 'leverage', 'side', 'note') if k in a}
            row['r_definition'] = next((a[k] for k in R_KEYS if k in a), None)
            rows.append(row)
    if not rows:
        return None
    age = age_hours(st.get('asof_taipei'), now)
    return dict(positions=rows, positions_asof=st.get('asof_taipei'), positions_stale=bool(age is None or age > STALE_HOURS))


def payload(now=None):
    """Everything the 持仓 page shows."""
    st, err = read_state()
    snaps = [{k: s[k] for k in ('name', 'date')} for s in snapshots()]
    base = dict(version=version(), snapshots=snaps)
    if err == 'missing':
        return dict(base, ok=False, code='missing', message='没有持仓数据')
    if err:
        return dict(base, ok=False, code='invalid', message='portfolio_state.json 读不出来（不是完整的 JSON），等下一次同步。')
    try:
        mtime = os.stat(os.path.join(pdir(), STATE_FILE)).st_mtime
        updated = datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
    except OSError:
        updated = None
    age = age_hours(st.get('asof_taipei'), now)

    def enrich(p, with_pnl):
        if not isinstance(p, dict):
            return None
        row = dict(p, check_ticker=chart_ticker(p))
        if with_pnl:
            given = next((num(p.get(k)) for k in ('pnl', 'unrealized_pnl') if num(p.get(k)) is not None), None)
            q, c, l = num(p.get('qty')), num(p.get('avg_cost')), num(p.get('last'))
            if given is not None:
                row.update(pnl=given, pnl_est=False)
            elif None not in (q, c, l):
                row.update(pnl=round((l - c) * q * (100 if p.get('type') in ('call', 'put') else 1), 2), pnl_est=True)
            else:
                row.update(pnl=None, pnl_est=False)
        return row

    pos = [r for r in (enrich(p, True) for p in st.get('positions') or []) if r]
    other = [r for r in (enrich(p, False) for p in st.get('other_accounts') or []) if r]
    return dict(base, ok=True, updated_at=updated, asof_taipei=st.get('asof_taipei'), age_hours=None if age is None else round(age, 2),
                stale=bool(age is None or age > STALE_HOURS), stale_hours=STALE_HOURS, source=st.get('source'), schema=st.get('schema'),
                account=st.get('account') if isinstance(st.get('account'), dict) else None, positions=pos, other_accounts=other,
                barbell=st.get('barbell') if isinstance(st.get('barbell'), dict) else None,
                lines=st.get('lines') if isinstance(st.get('lines'), dict) else None,
                spcx_equiv_exposure=st.get('spcx_equiv_exposure') if isinstance(st.get('spcx_equiv_exposure'), dict) else None,
                valuation_refs=st.get('valuation_refs') if isinstance(st.get('valuation_refs'), dict) else None,
                inversion_checklist=[x for x in st.get('inversion_checklist') or [] if isinstance(x, dict)],
                checks=four_checks([r['check_ticker'] for r in pos + other if r['check_ticker']]), overlays=overlays(st),
                **({'combined_nav_usd': st['combined_nav_usd']} if 'combined_nav_usd' in st else {}))
