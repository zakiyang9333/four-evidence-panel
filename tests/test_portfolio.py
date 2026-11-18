"""「持仓」页的验收测试。用法（在 four_evidence 目录下）：  .venv/bin/python tests/test_portfolio.py

对应 APP_ADDENDUM_PORTFOLIO.md 的验收项：
  1. 11-13 09:52 那份 portfolio_state.json：净值、杠铃比例、短 put 义务倍数和指令里写的一致
  2. 和 SPCX 相关的仓位（正股、关联 ETF、期权）四证列都是 SPCX 的状态
  期望的账户数字放在 tests/fixtures/portfolio_2026-11-13/expected.json，和夹具一样只在本机（.gitignore 排除），不写进代码。
  3. 数据时间改成两天前出现过期提示，改回来消失
  4. 删掉 portfolio_state.json：其它页面正常，持仓页显示“没有持仓数据”
  5. 面板开着时改现金，60 秒内页面自动更新
所有改动、删除都发生在临时目录里的副本上，portfolio/ 里的真文件从头到尾不碰。
11-13 那份文件已经被之后的同步覆盖，测试用的是保存在 tests/fixtures/portfolio_2026-11-13/ 的原文副本。
"""
import datetime, hashlib, json, os, re, shutil, sys, tempfile, threading, time, unittest
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'tests'))

import portfolio                # noqa: E402
import four_evidence_check      # noqa: E402
import test_panel as T          # noqa: E402  (Server, http, FakeClaude)

FIX = os.path.join(ROOT, 'tests', 'fixtures', 'portfolio_2026-11-13')
ASOF = datetime.datetime(2026, 11, 13, 9, 52, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
TAIPEI = datetime.timezone(datetime.timedelta(hours=8))
try:
    with open(os.path.join(FIX, 'expected.json'), encoding='utf-8') as _f:
        X = json.load(_f)
except (OSError, ValueError):
    X = None


def iso(dt):
    return dt.astimezone(TAIPEI).strftime('%Y-%m-%dT%H:%M+08:00')


def digest(d):
    h = hashlib.sha256()
    for n in sorted(os.listdir(d)):
        with open(os.path.join(d, n), 'rb') as f:
            h.update(n.encode()); h.update(f.read())
    return h.hexdigest()


@unittest.skipUnless(X, '没有 11-13 的持仓夹具（只在 zaki 的 Mac 上有）')
class Loader(unittest.TestCase):
    def setUp(self):
        os.environ['FE_PORTFOLIO_DIR'] = FIX
        self.before = digest(FIX)

    def tearDown(self):
        self.assertEqual(digest(FIX), self.before, '持仓文件被改动了')        # 只读
        os.environ.pop('FE_PORTFOLIO_DIR', None)

    def test_1_account_and_barbell(self):
        p = portfolio.payload(ASOF + datetime.timedelta(hours=1))
        self.assertTrue(p['ok'])
        a, b = X['account'], X['barbell']
        self.assertEqual(p['account']['nav'], a['nav'])
        self.assertEqual((p['barbell']['safe_pct'], p['barbell']['risky_pct'], p['barbell']['middle_obligation_x_nav']),
                         (b['safe_pct'], b['risky_pct'], b['middle_obligation_x_nav']))
        self.assertEqual((p['account']['cash'], p['account']['buying_power'], p['account']['option_margin'], len(p['account']['open_orders'])),
                         (a['cash'], a['buying_power'], a['option_margin'], a['open_orders']))
        self.assertEqual(p['asof_taipei'], X['asof_taipei']); self.assertFalse(p['stale'])
        self.assertTrue(p['source'])
        json.dumps(p, allow_nan=False)

    def test_2_four_evidence_column_reads_spcx(self):
        p = portfolio.payload(ASOF)
        by = {r['symbol']: r['check_ticker'] for r in p['positions']}
        self.assertEqual(len(X['spcx_linked']), 5)
        for sym in X['spcx_linked']:
            self.assertEqual(by[sym], 'SPCX', sym)
        for sym in X['no_chart']:
            self.assertIsNone(by[sym])                                          # 没有 K 线数据：显示 —
        for sym, t in X.get('own_chart', {}).items():
            self.assertEqual(by[sym], t, sym)                                   # 2026-11-18 起 JOBY 有了自己的 K 线
        self.assertEqual(p['other_accounts'][0]['check_ticker'], 'NVDA')
        ref = four_evidence_check.check('SPCX')                                 # the column is whatever the script says
        self.assertEqual((p['checks']['SPCX']['score'], p['checks']['SPCX']['armed']), (ref['score'], ref['armed']))
        if ref['asof'] == '2026-11-13':
            self.assertEqual((ref['score'], ref['armed']), (2, True))           # 2/4

    def test_3_stale_after_24_hours(self):
        self.assertFalse(portfolio.payload(ASOF + datetime.timedelta(hours=23))['stale'])
        late = portfolio.payload(ASOF + datetime.timedelta(days=2))
        self.assertTrue(late['stale']); self.assertEqual(round(late['age_hours']), 48)
        self.assertIsNone(portfolio.age_hours('昨天'))

    def test_pnl_is_computed_and_marked_as_estimate(self):
        rows = {r['symbol']: r for r in portfolio.payload(ASOF)['positions']}
        for sym, want, places in X['pnl']:                                      # （现价 − 成本）× 数量，期权 ×100
            self.assertAlmostEqual(rows[sym]['pnl'], want, places=places)
        self.assertTrue(all(r['pnl_est'] for r in rows.values()))

    def test_overlay_lines(self):
        o = portfolio.payload(ASOF)['overlays']
        self.assertEqual([[l['kind'], l['price']] for l in o['SPCX']['lines']], X['overlay_spcx_lines'])
        self.assertTrue(o['SPCX']['lines'][-1]['est'] and '估算' in o['SPCX']['lines'][-1]['label'])
        self.assertEqual(sorted(l['price'] for l in o['SPCX']['valuation']), X['overlay_spcx_valuation'])
        self.assertEqual([[l['kind'], l['price']] for l in o['NVDA']['lines']], X['overlay_nvda_lines'])   # 止盈价只在备注里，没有字段：不画，不从文字里猜
        self.assertNotIn('QQQ', o)

    def test_ai_gets_only_positions_of_the_current_ticker(self):
        r = portfolio.relevant_positions('SPCX', ASOF)
        self.assertEqual([x['symbol'] for x in r['positions']], X['spcx_linked'])
        self.assertTrue(all(x['r_definition'] is None for x in r['positions']))       # 文件没给 R 的定义：不编
        dump = json.dumps(r, ensure_ascii=False)
        for secret in X['never_in_ai_request'] + ['nav', 'cash']:
            self.assertNotIn(secret, dump)
        self.assertEqual([x['symbol'] for x in portfolio.relevant_positions('NVDA', ASOF)['positions']], X['nvda_linked'])
        self.assertIsNone(portfolio.relevant_positions('QQQ', ASOF))

    def test_module_never_opens_files_for_writing(self):
        with open(os.path.join(ROOT, 'portfolio.py'), encoding='utf-8') as f:
            src = f.read()
        self.assertFalse(re.search(r"open\([^)]*,\s*['\"][wax+]", src))
        for word in ('os.remove', 'os.unlink', 'os.rename', 'shutil', 'write('):
            self.assertNotIn(word, src)


class Edge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fe_pf_')
        os.environ['FE_PORTFOLIO_DIR'] = self.tmp

    def tearDown(self):
        os.environ.pop('FE_PORTFOLIO_DIR', None); shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, name, text):
        with open(os.path.join(self.tmp, name), 'w', encoding='utf-8') as f:
            f.write(text)

    def test_4_missing_file(self):
        p = portfolio.payload()
        self.assertEqual((p['ok'], p['code'], p['message']), (False, 'missing', '没有持仓数据'))
        self.assertIsNone(portfolio.relevant_positions('SPCX'))

    def test_half_written_file_is_not_shown_as_data(self):
        self.put('portfolio_state.json', '{"account": {"nav": 1')
        self.assertEqual(portfolio.payload()['code'], 'invalid')

    def test_missing_fields_stay_missing(self):
        self.put('portfolio_state.json', json.dumps({'asof_taipei': iso(datetime.datetime.now(TAIPEI)), 'positions': [{'symbol': 'SPCX', 'type': 'stock'}]}))
        p = portfolio.payload()
        self.assertTrue(p['ok']); self.assertIsNone(p['account']); self.assertIsNone(p['barbell']); self.assertIsNone(p['lines'])
        self.assertIsNone(p['positions'][0]['pnl']); self.assertEqual(p['overlays'], {})

    def test_unreadable_asof_counts_as_stale(self):
        self.put('portfolio_state.json', json.dumps({'asof_taipei': '不知道'}))
        self.assertTrue(portfolio.payload()['stale'])

    def test_snapshots_newest_first_and_no_path_tricks(self):
        self.put('2026-11-12_app.md', '# 旧'); self.put('2026-11-13_app.md', '# 新'); self.put('notes.md', 'x'); self.put('portfolio_state.json', '{}')
        self.assertEqual([s['name'] for s in portfolio.snapshots()], ['2026-11-13_app.md', '2026-11-12_app.md'])
        self.assertEqual(portfolio.snapshot_text('2026-11-13_app.md'), '# 新')
        for bad in ('notes.md', 'portfolio_state.json', '../engine.py', '/etc/hosts', ''):
            self.assertIsNone(portfolio.snapshot_text(bad), bad)

    def test_version_changes_when_a_file_changes(self):
        self.put('portfolio_state.json', '{"account": {"cash": 1}}'); v1 = portfolio.version()
        time.sleep(0.02); self.put('portfolio_state.json', '{"account": {"cash": 2}}'); v2 = portfolio.version()
        self.put('2026-11-13_app.md', '# x'); v3 = portfolio.version()
        os.remove(os.path.join(self.tmp, 'portfolio_state.json')); v4 = portfolio.version()
        self.assertEqual(len({v1, v2, v3, v4}), 4)


class Helper(BaseHTTPRequestHandler):
    """Edits the TEMP copy of portfolio_state.json on request from the UI self-test."""
    tmp = None; original = None

    def log_message(self, *a):
        pass

    def do_GET(self):
        do = parse_qs(urlparse(self.path).query).get('do', [''])[0]
        path = os.path.join(Helper.tmp, 'portfolio_state.json'); st = json.loads(Helper.original)
        now = datetime.datetime.now(TAIPEI)
        st['asof_taipei'] = iso(now - datetime.timedelta(hours=1))
        if do == 'stale':
            st['asof_taipei'] = iso(now - datetime.timedelta(days=2))
        if do == 'cash':
            st['account']['cash'] = 12345.67
        if do == 'delete':
            if os.path.exists(path):
                os.remove(path)
        else:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(st, f, ensure_ascii=False)
        out = b'{"ok":true}'
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(out))); self.end_headers(); self.wfile.write(out)


@unittest.skipUnless(X, '没有 11-13 的持仓夹具（只在 zaki 的 Mac 上有）')
class Live(unittest.TestCase):
    """A running panel pointed at a temp copy of the fixture (asof moved to one hour ago so it starts fresh)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='fe_pf_live_')
        for n in os.listdir(FIX):
            shutil.copy(os.path.join(FIX, n), cls.tmp)
        with open(os.path.join(FIX, 'portfolio_state.json'), encoding='utf-8') as f:
            Helper.original = f.read()
        Helper.tmp = cls.tmp
        cls.helper = ThreadingHTTPServer(('127.0.0.1', 0), Helper)
        threading.Thread(target=cls.helper.serve_forever, daemon=True).start()
        cls.hport = cls.helper.server_address[1]
        T.http(cls.hport, '/op?do=fresh')
        cls.fake = ThreadingHTTPServer(('127.0.0.1', 0), T.FakeClaude)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        cls.s = T.Server({'FE_PORTFOLIO_DIR': cls.tmp})
        cls.k = T.Server({'FE_PORTFOLIO_DIR': cls.tmp, 'ANTHROPIC_API_KEY': T.FAKE_KEY, 'ANTHROPIC_BASE_URL': f'http://127.0.0.1:{cls.fake.server_address[1]}'})

    @classmethod
    def tearDownClass(cls):
        cls.s.stop(); cls.k.stop(); cls.helper.shutdown(); cls.fake.shutdown(); shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, path='/api/portfolio'):
        code, body = T.http(self.s.port, path)
        return code, json.loads(body)

    def test_a_api(self):
        T.http(self.hport, '/op?do=fresh')
        code, p = self.get()
        self.assertEqual(code, 200); self.assertTrue(p['ok']); self.assertFalse(p['stale']); self.assertEqual(p['account']['nav'], X['account']['nav'])
        self.assertEqual(self.get('/api/portfolio/snapshot?name=2026-11-13_app.md')[1]['ok'], True)
        self.assertEqual(self.get('/api/portfolio/snapshot?name=../engine.py')[0], 404)
        self.assertEqual(T.http(self.s.port, '/api/portfolio', None, {'Host': 'evil.example'})[0], 403)

    def test_b_change_stale_delete_restore(self):
        v0 = self.get('/api/portfolio/version')[1]
        T.http(self.hport, '/op?do=cash'); v1 = self.get('/api/portfolio/version')[1]
        self.assertNotEqual(v0['version'], v1['version']); self.assertEqual(self.get()[1]['account']['cash'], 12345.67)      # 5
        T.http(self.hport, '/op?do=stale'); self.assertTrue(self.get('/api/portfolio/version')[1]['stale']); self.assertTrue(self.get()[1]['stale'])   # 3
        T.http(self.hport, '/op?do=fresh'); self.assertFalse(self.get()[1]['stale'])
        T.http(self.hport, '/op?do=delete')                                                                                  # 4
        p = self.get()[1]; self.assertEqual((p['ok'], p['message']), (False, '没有持仓数据'))
        self.assertEqual(T.http(self.s.port, '/api/state?ticker=SPCX')[0], 200); self.assertEqual(T.http(self.s.port, '/')[0], 200)
        self.assertEqual(T.http(self.s.port, '/api/bars?ticker=NVDA')[0], 200)
        T.http(self.hport, '/op?do=fresh'); self.assertTrue(self.get()[1]['ok'])

    def test_c_nothing_personal_in_the_server_log(self):
        self.get(); self.get('/api/portfolio/snapshot?name=2026-11-13_app.md')
        log = self.s.output()
        for secret in X['never_in_log']:
            self.assertNotIn(secret, log)

    def test_d_ai_request_carries_only_relevant_positions(self):
        T.http(self.hport, '/op?do=fresh'); T.FakeClaude.seen.clear()
        code, body = T.http(self.k.port, '/api/ai/analyze', {'ticker': 'SPCX'})
        self.assertEqual(code, 200, body); self.assertEqual(json.loads(body)['positions_sent'], 5)
        req = T.FakeClaude.seen[-1][2]; sent = json.loads(req['messages'][0]['content'])
        self.assertIn('核心仓按估值失效，没有价格止损；战术单四要素不到 4/4 不开；不给具体下单指令', req['system'])
        self.assertEqual([x['symbol'] for x in sent['positions']], X['spcx_linked'])
        self.assertEqual({k for x in sent['positions'] for k in x} - {'symbol', 'type', 'qty', 'avg_cost', 'side', 'underlying', 'strike', 'expiry', 'note', 'r_definition'}, set())
        whole = json.dumps(req, ensure_ascii=False)
        for secret in X['never_in_ai_request']:
            self.assertNotIn(secret, whole)                                    # 不发整份账户
        # 回放历史某天：不附仓位，提示词也不加那一段
        T.FakeClaude.seen.clear(); T.http(self.k.port, '/api/ai/analyze', {'ticker': 'SPCX', 'asof': '2026-09-01'})
        req = T.FakeClaude.seen[-1][2]
        self.assertNotIn('positions', json.loads(req['messages'][0]['content'])); self.assertNotIn('zaki', req['system']); self.assertNotIn('__PORTFOLIO__', req['system'])
        # 没有持仓数据：照旧
        T.http(self.hport, '/op?do=delete'); T.FakeClaude.seen.clear(); T.http(self.k.port, '/api/ai/analyze', {'ticker': 'SPCX'})
        self.assertNotIn('positions', json.loads(T.FakeClaude.seen[-1][2]['messages'][0]['content']))
        T.http(self.hport, '/op?do=fresh')

    def test_e_ui_selftest_portfolio_page(self):
        chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        if not os.path.exists(chrome):
            self.skipTest('没有 Google Chrome')
        T.http(self.hport, '/op?do=fresh')
        r = subprocess.run([os.path.join(ROOT, 'tests', 'run_selftest.sh'), str(self.s.port), f'pfhelper={self.hport}'], capture_output=True, text=True, timeout=400)
        res = json.loads(r.stdout.strip().splitlines()[-1])
        failed = [k for k, v in res.get('checks', {}).items() if not v]
        self.assertTrue(res.get('pass'), f"自检失败：{res.get('error')} {failed} {[res.get('info', {}).get(k) for k in failed]}")
        pf = [k for k in res['checks'] if k.startswith('pf_')]
        self.assertGreaterEqual(len(pf), 18, pf)
        self.assertLess(res['info']['pf_update_ms'], 60000)
        self.assertEqual(res['info']['pf']['nav'], X['nav_display'])            # 验收 1：页面上显示的就是这个数


if __name__ == '__main__':
    unittest.main(verbosity=2)
