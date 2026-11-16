"""四要素面板后端。标准库 http.server，只监听 127.0.0.1。用 ./start.sh 启动。

GET  /                      单页前端（static/）
GET  /api/meta              标的列表、数据截止日、AI 是否可用、回测摘要、上次刷新结果
GET  /api/bars?ticker=      全历史 K 线 + 成交量均线 + MACD + 地量日 + 单一来源行
GET  /api/state?ticker=&asof=   规则引擎在 asof 收盘的状态（数据截到 asof 再算）
GET  /api/avwap?ticker=&anchor=&asof=   手动锚定 VWAP 画线用
GET  /api/ai/narrate?ticker=&asof=       视频式四问解说的模板版（不调用 API），外加上次 Claude 润色的版本（如果有）
GET  /api/ai/cached?ticker=&asof=        这只标的这一天上次的 Claude 解说（本机保存），以及输入是否变过
GET  /api/live?ticker=      盘中实时价和今天常规时段的未收盘 K 线（只画图，不参与判定）
GET  /api/portfolio         「持仓」页的全部内容（只读 portfolio/ 里的文件）
GET  /api/portfolio/version 持仓文件有没有变（前端每 15 秒问一次，变了才重取）
GET  /api/portfolio/snapshot?name=   某一份 App 快照的原文
POST /api/refresh           运行 prep_data.py（只追加新日期）
POST /api/ai/analyze        Claude 解说（需要环境变量 ANTHROPIC_API_KEY）。盘面和仓位没变时直接返回保存的那一版，
                            不调用 API；带 force 才重新分析
"""
import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import ai_explain
import live
import narrate
import panel
import portfolio

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, 'static')
DEFAULTS = dict(port=8777, ai_model='claude-opus-5-5', ai_effort='medium', ai_max_tokens=16000,
                ai_timeout_s=180, refresh_timeout_s=180, ai_refusal_fallback=True, portfolio_poll_s=15)


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(os.path.join(ROOT, 'config.json'), encoding='utf-8') as f:
            cfg.update({k: v for k, v in json.load(f).items() if not k.startswith('_')})
    except (OSError, ValueError):
        pass
    if os.environ.get('FE_PORT'):
        cfg['port'] = int(os.environ['FE_PORT'])
    if os.environ.get('FE_AI_MODEL'):
        cfg['ai_model'] = os.environ['FE_AI_MODEL']
    return cfg


CFG = load_config()
LIVE = live.LiveFeed(panel.TICKERS, enabled=bool(CFG.get('live_enabled', True)) and os.environ.get('FE_LIVE') != '0')
_refresh_lock = threading.Lock()
_ai_lock = threading.Lock()
_last_refresh = None


def run_refresh():
    """Run prep_data.py in a child process and return its report."""
    global _last_refresh
    if not _refresh_lock.acquire(blocking=False):
        return 409, dict(ok=False, error='正在刷新，请等它结束。')
    try:
        t0 = time.time()
        try:
            p = subprocess.run([sys.executable, os.path.join(ROOT, 'prep_data.py'), '--json'], cwd=ROOT,
                               capture_output=True, text=True, timeout=int(CFG['refresh_timeout_s']))
        except subprocess.TimeoutExpired:
            return 504, dict(ok=False, error='刷新超时，数据没有改动。')
        try:
            rep = json.loads(p.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return 500, dict(ok=False, error='prep_data.py 运行失败：' + (p.stderr.strip().splitlines() or ['没有输出'])[-1][:300])
        panel.clear_cache()
        out = dict(ok=True, at=time.strftime('%Y-%m-%d %H:%M:%S'), seconds=round(time.time() - t0, 1), tickers={
            t: dict(appended=r.get('appended', []), errors=r.get('errors', []), notes=r.get('notes', []),
                    last=r.get('last'), last_src=r.get('last_src'), sources=r.get('sources', {})) for t, r in rep.items()})
        out['has_error'] = any(r['errors'] for r in out['tickers'].values())
        _last_refresh = out
        return 200, out
    finally:
        _refresh_lock.release()


def meta():
    ok, why = ai_explain.status(CFG)
    return dict(tickers=panel.summary(), timeframe='日线', realtime=False,
                ai=dict(enabled=ok, reason=why, model=CFG['ai_model']),
                backtest=panel.backtest_summary(), last_refresh=_last_refresh, last_refresh_file=panel.last_refresh(),
                portfolio_poll_s=max(5, min(60, int(CFG.get('portfolio_poll_s', 15)))),
                engine=dict(version='v1.0', params=panel.P, fixed={k: panel.F[k] for k in ('hi_win', 'div_gap', 'tgt_win', 'max_hold')}))


def ai_inputs(t, asof):
    """Everything one AI reading is built from, plus a fingerprint of it."""
    state = panel.state_at(t, asof or None)
    B = panel.load(t)['B']
    i = state['index']
    a = max(0, i - 59)
    bars = [[B['d'][j], panel.fnum(B['o'][j], 4), panel.fnum(B['h'][j], 4), panel.fnum(B['l'][j], 4),
             panel.fnum(B['c'][j], 4), int(B['v'][j])] for j in range(a, i + 1)]
    # 仓位是现在的仓位，只在看最新一根时附上；回放历史某天时不附。只发这只标的相关的，不发整份账户。
    pos = portfolio.relevant_positions(t) if state['is_latest'] else None
    bt = panel.backtest_summary()
    facts = narrate.build_facts(t, state['asof'])
    return facts, bars, bt, pos, ai_explain.fingerprint(facts, bars, bt, CFG, pos)


def narration_result(t, facts, bt, narr, source, **extra):
    """One response shape for both the template and the Claude version. The card never goes through Claude."""
    return dict(ok=True, ticker=t, asof=facts['asof'], source=source, narration=narr, card=narrate.card(facts, bt),
                score=facts['score'], armed=facts['armed'], **extra)


def ai_narrate(t, asof):
    """Free, instant template narration, plus the last saved Claude version for this day if there is one."""
    facts, bars, bt, pos, fp = ai_inputs(t, asof)
    res = narration_result(t, facts, bt, narrate.template(facts), 'template')
    rows = ai_cache_read(t, facts['asof'])
    if rows:
        res['polished'] = saved_view(rows[0], facts, bars, bt, pos, fp)
    ok, why = ai_explain.status(CFG)
    res['polish'] = dict(enabled=ok, reason=why, model=CFG['ai_model'], positions=len(pos['positions']) if pos else 0)
    return res


def saved_view(row, facts, bars, bt, pos, fp):
    """A saved Claude reading as it is shown again: marked as saved, told whether the market or the positions changed since,
    and its numbers checked again by today's rules. No API call."""
    old = dict(row, same_input=row.get('fingerprint') == fp, cached=True)
    bad = narrate.bad_numbers(old['narration'], narrate.allowed_numbers(facts, bars, bt, pos))
    old.pop('unverified', None); old.pop('notice', None); old.pop('code', None)
    if bad:
        old.update(unverified=bad[:20], notice=f'有 {len(bad)} 个数字在引擎输出和 K 线数据里找不到（已标黄）：可能是它自己算的，也可能写错了，以图和引擎为准。')
    return old


# ---- 本机保存的 AI 解读（含仓位相关内容，只存在 cache/ai/，不进 git）----
AI_CACHE = os.environ.get('FE_CACHE_DIR') or os.path.join(ROOT, 'cache', 'ai')
AI_KEEP = 5


def _ai_cache_path(t, asof):
    if t not in panel.TICKERS or not (len(asof) == 10 and asof[4] == '-' and asof[7] == '-' and asof.replace('-', '').isdigit()):
        raise KeyError(t)
    return os.path.join(AI_CACHE, f'{t}_{asof}.json')


def ai_cache_read(t, asof):
    try:
        with open(_ai_cache_path(t, asof), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def ai_cache_add(t, asof, entry):
    os.makedirs(AI_CACHE, exist_ok=True)
    rows = ([entry] + ai_cache_read(t, asof))[:AI_KEEP]
    tmp = _ai_cache_path(t, asof) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _ai_cache_path(t, asof))


def ai_cached(t, asof):
    """Last saved Claude reading for this ticker and day, and whether today's input still matches it."""
    state = panel.state_at(t, asof or None)
    rows = ai_cache_read(t, state['asof'])
    if not rows:
        return dict(ok=True, found=False, asof=state['asof'], ticker=t)
    fp = ai_inputs(t, state['asof'])[4]
    return dict(ok=True, found=True, ticker=t, asof=state['asof'], entry=rows[0], same_input=rows[0].get('fingerprint') == fp,
                history=[{k: r.get(k) for k in ('created_at', 'model', 'positions_sent')} for r in rows])


def ai_analyze(body):
    """“让 Claude 润色”。Whatever goes wrong, the answer is still a four-question narration: the template, with a notice."""
    t = body.get('ticker')
    facts, bars, bt, pos, fp = ai_inputs(t, body.get('asof'))
    tmpl = narrate.template(facts)
    if not body.get('force') and not body.get('test_fake_number'):
        # 记忆：盘面和仓位都没变，就把保存的那一版原样给回去，不再调用 Claude。要重新分析得明确带 force。
        rows = ai_cache_read(t, facts['asof'])
        if rows and rows[0].get('fingerprint') == fp:
            return 200, dict(saved_view(rows[0], facts, bars, bt, pos, fp), reused=True)
    if not _ai_lock.acquire(blocking=False):
        return 409, dict(ok=False, error='上一次分析还没结束。')
    try:
        got = ai_explain.polish(facts, bars, bt, CFG, pos)
        if not got.get('ok'):
            return 200, narration_result(t, facts, bt, tmpl, 'template', notice='没能用上 Claude，已改用模板：' + got['error'], code=got.get('code'))
        allowed = narrate.allowed_numbers(facts, bars, bt, pos)
        # Claude 只说在图上标哪一天、哪个位置；价位由这里从 K 线数据里取。直接给的价位必须是输入里有的数。
        narr, why = narrate.normalize(got['raw'], facts, tmpl, narrate.chart_data(t, facts['asof']), {round(a, 2) for a in allowed})
        if narr is None:
            return 200, narration_result(t, facts, bt, tmpl, 'template', notice=f'AI 输出的结构不对（{why}），已改用模板', code='shape')
        if body.get('test_fake_number'):                # 测试开关：往 Claude 的输出里塞一个假数字，看核对能不能拦住
            narr['steps'][0]['say'] += '，目标看到 987.65'
        bad = narrate.bad_numbers(narr, allowed)
        if bad and CFG.get('ai_strict_numbers', False):     # 严格模式：有一个对不上就整段不用
            return 200, narration_result(t, facts, bt, tmpl, 'template', notice='AI 输出含无法核对的数字，已改用模板', code='numbers', unverified=bad[:8])
        res = narration_result(t, facts, bt, narr, 'claude', model=got['model'], positions_sent=len(pos['positions']) if pos else 0,
                               created_at=time.strftime('%Y-%m-%d %H:%M:%S'), fingerprint=fp,
                               tokens_in=got.get('tokens_in'), tokens_out=got.get('tokens_out'))
        if bad:     # 自由分析时 Claude 会自己算数：对不上的不丢弃，标出来让人自己判断
            res.update(unverified=bad[:20], code='numbers',
                       notice=f'有 {len(bad)} 个数字在引擎输出和 K 线数据里找不到（已标黄）：可能是它自己算的，也可能写错了，以图和引擎为准。')
        try:
            ai_cache_add(t, facts['asof'], res)
        except OSError:
            res['cache_error'] = True
        return 200, res
    finally:
        _ai_lock.release()


class Handler(BaseHTTPRequestHandler):
    server_version = 'FourEvidence/1.0'
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):      # request line only; never headers or bodies
        sys.stderr.write('%s %s\n' % (time.strftime('%H:%M:%S'), fmt % args))

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def _local(self):
        """Only this machine's own page may call the API (blocks other web pages from poking localhost)."""
        host = (self.headers.get('Host') or '').split(':')[0]
        if host not in ('localhost', '127.0.0.1'):
            return False
        origin = self.headers.get('Origin')
        if origin:
            return urlparse(origin).hostname in ('localhost', '127.0.0.1')
        return True

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path.startswith('/api/'):
                if not self._local():
                    return self._send(403, dict(ok=False, error='只允许本机访问。'))
                if u.path == '/api/meta':
                    return self._send(200, meta())
                if u.path == '/api/bars':
                    return self._send(200, panel.bars_payload(q.get('ticker', ''), q.get('tf', 'D')))
                if u.path == '/api/live':
                    t = q.get('ticker', '')
                    return self._send(200, LIVE.snapshot(t, panel.load(t)['B']['d'][-1]))
                if u.path == '/api/data/version':
                    return self._send(200, {t: panel.freshness(t) for t in panel.TICKERS})
                if u.path == '/api/ai/narrate':
                    return self._send(200, ai_narrate(q.get('ticker', ''), q.get('asof') or None))
                if u.path == '/api/ai/cached':
                    return self._send(200, ai_cached(q.get('ticker', ''), q.get('asof') or None))
                if u.path == '/api/state':
                    st = panel.state_at(q.get('ticker', ''), q.get('asof') or None)
                    st['card'] = narrate.card_from_state(st, panel.backtest_summary())     # 规则模型卡片：只来自引擎
                    st['ai_saved'] = os.path.exists(_ai_cache_path(st['ticker'], st['asof']))   # 这一天有没有保存过 Claude 解说
                    return self._send(200, st)
                if u.path == '/api/portfolio':
                    return self._send(200, portfolio.payload())
                if u.path == '/api/portfolio/version':
                    st, err = portfolio.read_state()
                    age = None if err else portfolio.age_hours(st.get('asof_taipei'))
                    return self._send(200, dict(version=portfolio.version(), ok=not err,
                                                stale=bool(not err and (age is None or age > portfolio.STALE_HOURS))))
                if u.path == '/api/portfolio/snapshot':
                    txt = portfolio.snapshot_text(q.get('name', ''))
                    if txt is None:
                        return self._send(404, dict(ok=False, error='没有这份快照。'))
                    return self._send(200, dict(ok=True, name=q.get('name'), text=txt))
                if u.path == '/api/avwap':
                    return self._send(200, panel.manual_avwap(q.get('ticker', ''), q.get('anchor', ''), q.get('asof') or None))
                return self._send(404, dict(ok=False, error='没有这个接口。'))
            rel = 'index.html' if u.path in ('/', '') else u.path.lstrip('/')
            if rel.startswith('static/'):
                rel = rel[len('static/'):]
            full = os.path.realpath(os.path.join(STATIC, rel))
            if not full.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(full):
                return self._send(404, b'not found', 'text/plain; charset=utf-8')
            ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
            if ctype.startswith('text/') or ctype in ('application/javascript', 'application/json'):
                ctype += '; charset=utf-8'
            with open(full, 'rb') as f:
                return self._send(200, f.read(), ctype)
        except KeyError:
            return self._send(404, dict(ok=False, error='没有这个标的。'))
        except BrokenPipeError:
            pass
        except Exception as e:      # noqa: BLE001
            return self._send(500, dict(ok=False, error=f'服务端出错：{type(e).__name__}'))

    def do_POST(self):
        u = urlparse(self.path)
        try:
            if not self._local():
                return self._send(403, dict(ok=False, error='只允许本机访问。'))
            if 'application/json' not in (self.headers.get('Content-Type') or ''):
                return self._send(415, dict(ok=False, error='需要 JSON 请求。'))
            n = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(n) or b'{}') if n else {}
            if u.path == '/api/refresh':
                return self._send(*run_refresh())
            if u.path == '/api/ai/analyze':
                return self._send(*ai_analyze(body))
            return self._send(404, dict(ok=False, error='没有这个接口。'))
        except KeyError:
            return self._send(404, dict(ok=False, error='没有这个标的。'))
        except BrokenPipeError:
            pass
        except Exception as e:      # noqa: BLE001
            return self._send(500, dict(ok=False, error=f'服务端出错：{type(e).__name__}'))


def main():
    """Start on the configured port. When started by hand (no FE_PORT), a busy port is skipped: the next free one
    up to +30 is used and printed, so the panel runs on any machine. launchd always passes FE_PORT (fixed port)."""
    port = int(CFG['port'])
    fixed = bool(os.environ.get('FE_PORT'))
    srv = None
    for p in ([port] if fixed else range(port, port + 31)):
        try:
            srv = ThreadingHTTPServer(('127.0.0.1', p), Handler)
            port = p
            break
        except OSError as e:
            err = e
    if srv is None:
        sys.exit(f'端口 {port} 起不来（{err}）。可能已有别的程序在用，换一个试试：FE_PORT=8800 ./start.sh' if fixed
                 else f'{port}–{port + 30} 的端口都被占用了，换一个范围试试：FE_PORT=9800 ./start.sh')
    if port != int(CFG['port']):
        print(f'端口 {CFG["port"]} 被别的程序占用，改用 {port}。', flush=True)
    ok, why = ai_explain.status(CFG)
    url = f'http://localhost:{port}'
    print(f'四要素面板已启动：{url}', flush=True)
    print(f'AI 解读：{"可用，模型 " + CFG["ai_model"] if ok else "不可用。" + why}', flush=True)
    threading.Thread(target=lambda: [panel.load(t) for t in panel.TICKERS], daemon=True).start()
    if os.environ.get('FE_OPEN') == '1':                  # ./start.sh 在终端里运行时自动打开浏览器
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止。')


if __name__ == '__main__':
    main()
