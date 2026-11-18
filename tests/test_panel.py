"""验收测试。用法（在 four_evidence 目录下）：  .venv/bin/python tests/test_panel.py

覆盖 APP_BUILD_PROMPT.md 的验收项：
  2. 2026-11-13 的状态与现有看板一致
  3. 回放到历史信号日显示四项齐
  4. 自动画的扇子中线、成本线、止损线数值与 engine.py 输出一致（同时证明回放没有用到未来数据）
  5. 没有 ANTHROPIC_API_KEY 时页面照常可用
以及：刷新数据只追加、不改已有行；密钥不出后端；界面自检（无头 Chrome）。
不访问外网：数据源用假数据，Claude API 用本机的假服务。
"""
import csv, datetime, hashlib, io, json, os, random, shutil, socket, subprocess, sys, tempfile, threading, time, unittest, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.pop('FE_DATA_DIR', None)

import numpy as np          # noqa: E402
import engine as E          # noqa: E402
import panel                # noqa: E402
import prep_data            # noqa: E402

ENGINE_SHA256 = 'c7a715b4763db7cdd1216a7de4c36c08dcbc7dff8ec3e23f7d3e9561b8d026ed'   # engine.py v1.0 as delivered
FAKE_KEY = 'sk-ant-test-THIS-IS-NOT-A-REAL-KEY-0123456789'


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1.0, abs(b))


class EngineUntouched(unittest.TestCase):
    def test_engine_file_is_byte_identical(self):
        with open(os.path.join(ROOT, 'engine.py'), 'rb') as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), ENGINE_SHA256, 'engine.py 被改过')


class Acceptance(unittest.TestCase):
    def test_2_state_on_2026_11_13(self):
        s = panel.state_at('SPCX', '2026-11-13')
        self.assertEqual((s['asof'], s['armed'], s['lit']), ('2026-11-13', True, 2))
        self.assertEqual([e['ok'] for e in s['evidence']], [False, True, True, False])   # 底背离、跌速放缓成立
        self.assertEqual(s['conclusion']['code'], 'missing')
        n = panel.state_at('NVDA', '2026-11-13')
        self.assertEqual((n['armed'], n['lit'], [e['ok'] for e in n['evidence']]), (True, 0, [False] * 4))
        q = panel.state_at('QQQ', '2026-11-13')
        self.assertFalse(q['armed'])
        self.assertEqual(q['conclusion']['code'], 'not_armed')
        self.assertEqual(round(q['drawdown_low']), 15)                                    # 只跌了 15%
        self.assertEqual(q['lit'], 0)

    def test_3_replay_signal_days(self):
        for t, d in (('NVDA', '2025-05-13'), ('QQQ', '2009-03-18')):
            s = panel.state_at(t, d)
            self.assertTrue(s['all4'], (t, d))
            self.assertEqual((s['conclusion']['code'], s['lit']), ('all4', 4))
            self.assertEqual([m['n'] for m in s['marks']], [1, 2, 3, 4])
            self.assertTrue(all(m['date'] <= d for m in s['marks']))

    def test_4_drawn_lines_equal_engine_and_no_lookahead(self):
        """state_at() computes on data cut at the replay day; engine.compute() on the FULL history must give the
        same numbers for that day. That checks the drawing values against the engine and rules out look-ahead."""
        rng = random.Random(20261114)
        for t in panel.TICKERS:
            B = E.load(panel.csv_path(t)); S = E.compute(B); n = len(B['c'])
            picks = {n - 1, B['d'].index('2026-11-13')} | {rng.randrange(1, n) for _ in range(60 if n > 500 else 30)}
            for arr in (np.isfinite(S['avwap']), S['all4'], S['e4']):       # days with a cost line / a signal, on purpose
                idx = [int(k) for k in np.flatnonzero(arr) if k >= 1]
                picks |= set(rng.sample(idx, min(25, len(idx))))
            for d in ('2025-05-13', '2009-03-18'):
                if d in B['d']:
                    picks.add(B['d'].index(d))
            seen = dict(fan=0, avwap=0)
            for i in sorted(picks):
                s = panel.state_at(t, B['d'][i]); tag = (t, B['d'][i])
                self.assertEqual(s['index'], i, tag)
                self.assertEqual([e['ok'] for e in s['evidence']], [bool(S[k][i]) for k in ('e1', 'e2', 'e3', 'e4')], tag)
                self.assertEqual((s['armed'], s['all4']), (bool(S['dd_ok'][i]), bool(S['all4'][i])), tag)
                self.assertTrue(close(s['draw']['stop'], S['stop'][i]), tag)                     # 止损线
                self.assertTrue(close(s['high']['price'], S['H'][i]) and close(s['low']['price'], S['L'][i]), tag)
                self.assertEqual((s['high']['i'], s['low']['i']), (int(S['hi_i'][i]), int(S['low_i'][i])), tag)
                if np.isfinite(S['fanline'][i]):                                               # 扇子中线
                    self.assertTrue(close(s['draw']['fan']['levels']['0.5']['at_asof'], S['fanline'][i]), tag)
                    self.assertTrue(close(s['levels']['fan05'], S['fanline'][i]), tag); seen['fan'] += 1
                else:
                    self.assertIsNone(s['levels']['fan05'], tag)
                if np.isfinite(S['avwap'][i]):                                                 # 成本线
                    self.assertTrue(close(s['draw']['avwap']['values'][-1], S['avwap'][i]), tag)
                    self.assertEqual(s['draw']['avwap']['anchor'], int(S['anchor'][i]), tag)
                    self.assertEqual(len(s['draw']['avwap']['values']), i - int(S['anchor'][i]) + 1, tag); seen['avwap'] += 1
                else:
                    self.assertIsNone(s['draw']['avwap'], tag)
                if np.isfinite(S['target'][i]):
                    self.assertTrue(close(s['levels']['target'], S['target'][i]), tag)
                self.assertEqual(any(m['n'] == 4 for m in s['marks']), bool(S['e4'][i] and S['dd_ok'][i]), tag)
                json.dumps(s, allow_nan=False)
            self.assertGreater(seen['fan'], 5, t)
            if t != 'SPCX':
                self.assertGreater(seen['avwap'], 5, t)

    def test_history_signals_match_engine(self):
        for t in ('NVDA', 'QQQ'):
            B = E.load(panel.csv_path(t)); ref = [q['sig'] for q in E.signals(B, E.compute(B))]
            self.assertEqual([q['sig'] for q in panel.state_at(t)['signals']], ref)
        cut = panel.state_at('NVDA', '2025-05-13')['signals']
        self.assertTrue(all(q['sig'] < '2025-05-13' and q['exit_d'] <= '2025-05-13' for q in cut))   # 回放里看不到之后的事

    def test_bars_payload(self):
        b = panel.bars_payload('NVDA'); n = len(b['d'])
        self.assertTrue(all(len(b[k]) == n for k in ('o', 'h', 'l', 'c', 'v', 'vma5', 'vma10', 'dif', 'dea', 'hist')))
        dif, dea, hist = E.macd(E.load(panel.csv_path('NVDA'))['c'])
        self.assertTrue(close(b['hist'][-1], hist[-1]) and close(hist[-1], 2 * (dif[-1] - dea[-1])))   # 柱 = 2×(DIF−DEA)
        self.assertTrue(close(b['vma5'][-1], sum(b['v'][-5:]) / 5, 1e-4))
        self.assertTrue(b['src'] and all(v and v != 'project' for v in b['src'].values()))      # 只列出不是项目数据的行，并写明来源（单一来源或几家核对过）
        json.dumps(b, allow_nan=False)


class RefreshAppendOnly(unittest.TestCase):
    """prep_data.update_ticker with fake sources (no network)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fe_test_')
        os.environ['FE_DATA_DIR'] = self.tmp
        with open(os.path.join(ROOT, 'data', 'NVDA.csv'), newline='') as f:
            self.full = f.read()
        lines = self.full.splitlines(keepends=True)
        self.kept = ''.join(lines[:-3])                       # pretend the last three days are not stored yet
        with open(os.path.join(self.tmp, 'NVDA.csv'), 'w', newline='') as f:
            f.write(self.kept)
        self.truth = prep_data.read(self.full)
        self.new = sorted(self.truth)[-3:]
        self.late = datetime.datetime(2026, 12, 1, 20, 0)     # any time well after those sessions closed

    def tearDown(self):
        os.environ.pop('FE_DATA_DIR', None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stored(self):
        with open(os.path.join(self.tmp, 'NVDA.csv'), newline='') as f:
            return f.read()

    def src(self, **patch):
        m = {d: list(v) for d, v in self.truth.items() if d >= sorted(self.truth)[-60]}
        for d, c in patch.items():
            m[d.replace('_', '-')][3] = c
        return m

    def test_two_sources_agree_appends_and_keeps_existing_bytes(self):
        rep = prep_data.update_ticker('NVDA', [('a', self.src()), ('b', self.src())], self.late)
        self.assertEqual([x['date'] for x in rep['appended']], self.new)
        self.assertEqual(rep['errors'], [])
        out = self.stored()
        self.assertTrue(out.startswith(self.kept), '已有的行被改动了')
        tail = list(csv.reader(io.StringIO(out[len(self.kept):])))
        self.assertEqual([r[0] for r in tail], self.new)
        self.assertTrue(all(r[6] == 'a+b' for r in tail))
        self.assertTrue(all(float(r[4]) == self.truth[r[0]][3] for r in tail))
        self.assertEqual(prep_data.update_ticker('NVDA', [('a', self.src()), ('b', self.src())], self.late)['appended'], [])   # idempotent

    def test_disagreement_over_half_percent_is_not_written(self):
        bad = self.new[1]
        rep = prep_data.update_ticker('NVDA', [('a', self.src()), ('b', self.src(**{bad: self.truth[bad][3] * 1.006}))], self.late)
        self.assertEqual([x['date'] for x in rep['appended']], self.new[:1])     # stops at the bad day: no hole in the series
        self.assertTrue(any(bad in e and '0.5%' in e for e in rep['errors']), rep['errors'])
        self.assertNotIn(bad, self.stored()); self.assertNotIn(self.new[2], self.stored())
        self.assertTrue(self.stored().startswith(self.kept))

    def test_within_half_percent_is_written(self):
        d = self.new[0]
        rep = prep_data.update_ticker('NVDA', [('a', self.src()), ('b', self.src(**{d: self.truth[d][3] * 1.004}))], self.late)
        self.assertEqual(len(rep['appended']), 3)

    def test_single_source_is_flagged(self):
        rep = prep_data.update_ticker('NVDA', [('a', self.src())], self.late)
        self.assertTrue(all(x['src'] == 'a(single)' for x in rep['appended']) and len(rep['appended']) == 3)
        self.assertTrue(self.stored().rstrip().endswith('a(single)'))

    def test_source_that_contradicts_stored_history_is_not_used(self):
        old = sorted(self.truth)[-10]
        rep = prep_data.update_ticker('NVDA', [('liar', self.src(**{old: self.truth[old][3] * 1.05}))], self.late)
        self.assertEqual(rep['appended'], [])
        self.assertTrue(any('liar' in e for e in rep['errors']))
        self.assertEqual(self.stored(), self.kept)

    def test_unfinished_session_is_ignored(self):
        from zoneinfo import ZoneInfo
        ny = ZoneInfo('America/New_York')
        y, m, d = map(int, self.new[2].split('-'))
        during = datetime.datetime(y, m, d, 11, 0, tzinfo=ny); after = datetime.datetime(y, m, d, 16, 45, tzinfo=ny)
        rep = prep_data.update_ticker('NVDA', [('a', self.src()), ('b', self.src())], during)
        self.assertEqual([x['date'] for x in rep['appended']], self.new[:2])     # 盘中那根不写
        rep = prep_data.update_ticker('NVDA', [('a', self.src()), ('b', self.src())], after)
        self.assertEqual([x['date'] for x in rep['appended']], self.new[2:])

    def test_no_source_means_no_change_and_no_made_up_rows(self):
        rep = prep_data.update_ticker('NVDA', [], self.late)
        self.assertEqual(rep['appended'], []); self.assertEqual(self.stored(), self.kept)

    def test_existing_single_rows_get_a_side_check_not_an_edit(self):
        lines = self.full.splitlines(keepends=True)
        # 存到最后一条「别的来源」的单一来源行为止（yahoo 自己的单一来源行，没法再拿 yahoo 交叉核对）
        k = max(n for n, ln in enumerate(lines) if '(single)' in ln and not ln.rstrip().split(',')[-1].startswith('yahoo'))
        upto = ''.join(lines[:k + 1])
        with open(os.path.join(self.tmp, 'NVDA.csv'), 'w', newline='') as f:
            f.write(upto)                                        # last stored row is yennanliu(single)
        last = lines[k].split(',')[0]
        rep = prep_data.update_ticker('NVDA', [('yahoo', self.src())], self.late)
        self.assertEqual(self.stored()[:len(upto)], upto)        # 已有的行一个字都不改
        self.assertTrue(rep['crosscheck'][last]['ok']); self.assertEqual(rep['crosscheck'][last]['source'], 'yahoo')


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); return s.getsockname()[1]


def http(port, path, body=None, headers=None):
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=None if body is None else json.dumps(body).encode(),
                                 headers=dict({'Content-Type': 'application/json'} if body is not None else {}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


class Server:
    def __init__(self, env=None):
        self.port = free_port()
        self.log = tempfile.NamedTemporaryFile('w+', suffix='.log', delete=False)
        e = {k: v for k, v in os.environ.items() if not k.startswith('ANTHROPIC_') and k not in ('FE_DATA_DIR', 'FE_PORTFOLIO_DIR')}
        self.empty = tempfile.mkdtemp(prefix='fe_nopf_')      # 默认给一个空的持仓目录：测试不读真的持仓文件
        self.cache = tempfile.mkdtemp(prefix='fe_aicache_')   # AI 解读也存到临时目录，不碰 cache/ai
        self.notes = tempfile.mkdtemp(prefix='fe_notes_')     # 备注也存到临时目录，不碰 data/notes，不连 Yahoo
        self.chats = tempfile.mkdtemp(prefix='fe_chats_')     # 对话记录同样放临时目录
        self.tasks = tempfile.mkdtemp(prefix='fe_tasks_')     # 盯盘任务和分析记录也放临时目录，不碰 data/quant
        e.update(FE_PORT=str(self.port), FE_PORTFOLIO_DIR=self.empty, FE_CACHE_DIR=self.cache, FE_LIVE='0', FE_NOTES_DIR=self.notes, FE_NOTES_OFFLINE='1',
                 FE_CHAT_DIR=self.chats, FE_TASKS_DIR=self.tasks)   # 测试不连 Yahoo
        e.update(env or {})
        self.p = subprocess.Popen([sys.executable, os.path.join(ROOT, 'server.py')], cwd=ROOT, env=e, stdout=self.log, stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                if http(self.port, '/api/meta')[0] == 200:
                    return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError('server did not start')

    def output(self):
        self.log.flush()
        with open(self.log.name) as f:
            return f.read()

    def stop(self):
        self.p.terminate(); self.p.wait(10); self.log.close(); os.unlink(self.log.name)
        shutil.rmtree(self.empty, ignore_errors=True); shutil.rmtree(self.cache, ignore_errors=True); shutil.rmtree(self.notes, ignore_errors=True); shutil.rmtree(self.chats, ignore_errors=True)
        shutil.rmtree(self.tasks, ignore_errors=True)


class NoKey(unittest.TestCase):
    """验收 5：没有 ANTHROPIC_API_KEY 时页面仍能正常使用。"""

    @classmethod
    def setUpClass(cls):
        cls.s = Server()

    @classmethod
    def tearDownClass(cls):
        cls.s.stop()

    def test_everything_but_ai_works(self):
        p = self.s.port
        code, body = http(p, '/api/meta'); m = json.loads(body)
        self.assertEqual(code, 200); self.assertFalse(m['ai']['enabled']); self.assertIn('ANTHROPIC_API_KEY', m['ai']['reason'])
        self.assertEqual([t['ticker'] for t in m['tickers']], list(panel.TICKERS))       # 数据目录里有日线的那几只（2026-11-18 起有 JOBY）
        for t in ('SPCX', 'NVDA', 'QQQ'):
            self.assertEqual(http(p, f'/api/bars?ticker={t}')[0], 200)
            self.assertEqual(json.loads(http(p, f'/api/state?ticker={t}&asof=2026-11-13')[1])['asof'], '2026-11-13')
        code, body = http(p, '/'); self.assertEqual(code, 200); self.assertIn('四证：回测证据不足 ｜ 后手战法、破位反抽：尚未回测 ｜ 仅观察，不构成买卖依据', body)
        self.assertEqual(http(p, '/static/app.js')[0], 200)
        self.assertEqual(http(p, '/static/vendor/lightweight-charts.standalone.production.js')[0], 200)
        # 没有密钥：模板版解说照常工作；点“润色”也只是退回模板并说明原因
        code, body = http(p, '/api/ai/analyze', {'ticker': 'NVDA'}); res = json.loads(body)
        self.assertEqual((code, res['source']), (200, 'template')); self.assertIn('ANTHROPIC_API_KEY', res['notice'])
        q = json.loads(http(p, '/api/ai/narrate?ticker=QQQ&asof=2026-11-13')[1])
        self.assertEqual((q['source'], q['polish']['enabled']), ('template', False))
        n = q['narration']
        self.assertIn('15%', n['hook']); self.assertEqual(n['final'], '未触发，不抄')
        self.assertEqual([s['sticker'] for s in n['steps']], ['不抄！', '不抄！', '还不抄', '没得站'])
        self.assertEqual([s['ok'] for s in n['steps']], [False] * 4)
        self.assertIn('762.86', n['story']); self.assertIn('647.05', n['story']); self.assertIn('610.29', n['watch'][0])
        self.assertIn('679.89', n['steps'][2]['look']); self.assertIn('689.16', n['steps'][2]['look']); self.assertIn('-12.44', n['steps'][1]['look'])
        self.assertEqual(q['card']['verdict'], '未触发'); self.assertEqual(q['card']['footer'], '规则回测证据不足（26 笔，p=0.17），仅供观察')
        self.assertEqual(http(p, '/api/state?ticker=XXXX')[0], 404)
        self.assertEqual(http(p, '/../server.py')[0], 404)

    def test_only_local_pages_may_call_the_api(self):
        p = self.s.port
        self.assertEqual(http(p, '/api/refresh', {}, {'Origin': 'https://example.com'})[0], 403)
        self.assertEqual(http(p, '/api/meta', None, {'Host': 'evil.example'})[0], 403)

    def test_page_has_no_cdn_references(self):
        for f in ('index.html', 'app.js', 'app.css'):
            with open(os.path.join(ROOT, 'static', f), encoding='utf-8') as fh:
                txt = fh.read()
            self.assertNotIn('https://', txt.replace('https://www.apache.org', ''), f)
            self.assertNotIn('ANTHROPIC_API_KEY=', txt, f)

    def test_learn_panel_explains_in_plain_words_from_engine_numbers(self):
        """「一键解释」：程序拼的大白话，每个数字都来自引擎，不给买卖建议，没有密钥也能用。"""
        import quant
        for t, m, asof in (('QQQ', 'four', ''), ('NVDA', 'four', '2025-05-13'), ('SPCX', 'four', ''), ('NVDA', 'houshou', '2025-01-06'),
                           ('NVDA', 'houshou', '2013-06-19'), ('QQQ', 'houshou', '')):
            code, body = http(self.s.port, f'/api/learn?ticker={t}&model={m}&asof={asof}')
            self.assertEqual(code, 200, body[:200])
            d = json.loads(body)
            self.assertEqual((d['ticker'], d['model_key']), (t, m))
            self.assertGreaterEqual(len(d['cards']), 12)
            texts = [d['headline']['text'], d['headline']['sub'], d['footer']]
            for c in d['cards']:
                self.assertTrue(len(c['title']) > 3 and len(c['body']) > 20, c['id'])
                self.assertLessEqual(max(len(x) for x in c['body'].replace('？', '。').replace('；', '。').split('。')), 60, c['id'])   # 短句
                texts += [c['title'], c['body'], c['now'] or '', c['note'] or ''] + [i['name'] + i['text'] for i in c['items']]
            text = ' '.join(texts)
            for bad in ('建议买', '建议卖', '可以买入', '赶紧', '稳赚', '必涨'):
                self.assertNotIn(bad, text)
            self.assertIn('不告诉你该买还是该卖', text)
            st = panel.state_at(t, asof or None)
            q = json.loads(http(self.s.port, f'/api/quant?ticker={t}&model={m}&asof={asof}')[1])
            import narrate
            import engine as E
            hist = float(E.compute(panel.load(t)['B'])['hist'][st['index']])      # MACD 卡片上写的柱子值，也是引擎算的
            allowed = narrate.allowed_numbers(st, narrate.build_facts(t, st['asof']), q['signal'], q['score'], q['lines'], q['history'], panel.backtest_summary(), 8, 15, 5,
                                              round(hist, 2))
            self.assertEqual(narrate.bad_numbers(dict(hook=text, story='', final='', watch=[], steps=[]), allowed), [], (t, m, asof))
        four = json.loads(http(self.s.port, '/api/learn?ticker=NVDA&model=four&asof=2025-05-13')[1])
        self.assertEqual(four['headline']['tone'], 'go'); self.assertIn('不说“该买”', four['headline']['sub'])
        self.assertEqual([c['ok'] for c in four['cards'] if c['id'] in ('e1', 'e2', 'e3', 'e4')], [True] * 4)
        self.assertEqual(http(self.s.port, '/api/learn?ticker=XXXX')[0], 404)

    def test_ui_selftest_in_headless_chrome(self):
        chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        if not os.path.exists(chrome):
            self.skipTest('没有 Google Chrome')
        # 对话页的存档：一段只有旧的「一键解释」卡片（不该出现在历史里），一段是真的问答、中途换过一次图（自检会打开它）
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        card = dict(role='assistant', kind='explain', text='【一键解释】……', learn=dict(cards=[]))
        convs = [dict(id='aaaaaaaaaaaa', title='一键解释 · QQQ 11-16', created=now, updated=now, ticker='QQQ', messages=[card], usage=dict(tokens_in=0, tokens_out=0, cache_read=0, calls=0)),
                 dict(id='bbbbbbbbbbbb', title='还缺哪一项？', created=now, updated=now, ticker='NVDA', ctx_key='x', usage=dict(tokens_in=1200, tokens_out=700, cache_read=9800, cache_write=9000, calls=2),
                      messages=[card, dict(role='user', text='还缺哪一项？', chip='SPCX 2026-11-16 · 四证·抄底 v1.0', context='{}'),
                                dict(role='assistant', text='还缺两项：**地量**和**站回成本线**。', meta=dict(tokens_in=600, tokens_out=300, cache_read=0, cache_write=9000)),
                                dict(role='user', text='换成 NVDA 呢？', chip='NVDA 2026-11-16 · 四证·抄底 v1.0', context='{}'),
                                dict(role='assistant', text='NVDA 也差两项。', meta=dict(tokens_in=600, tokens_out=400, cache_read=9800, searches=1, sources=[dict(title='例子', url='https://example.com/n')]))])]
        for cv in convs:
            with open(os.path.join(self.s.chats, cv['id'] + '.json'), 'w', encoding='utf-8') as f:
                json.dump(cv, f, ensure_ascii=False)
        r = subprocess.run([os.path.join(ROOT, 'tests', 'run_selftest.sh'), str(self.s.port), 'chatseed=1'], capture_output=True, text=True, timeout=240)
        res = json.loads(r.stdout.strip().splitlines()[-1])
        failed = [k for k, v in res.get('checks', {}).items() if not v]
        self.assertTrue(res.get('pass'), f"自检失败：{res.get('error')} {failed} {[res.get('info', {}).get(k) for k in failed]}")
        self.assertGreaterEqual(len(res['checks']), 30)


GOOD_REPLY = dict(hook='停，先别急着抄', story='冲高之后一路回落，中间夹着几次反弹',
                  steps=[dict(q='缺口没补', look='前面留了一个向下的缺口', say='缺口还压在头上', sticker='有压力', tone='bad', evidence=0,
                              draw=[dict(type='point', dates=['05-12'], at='low', price=0, top=0, bottom=0, label='坑'),
                                    dict(type='path', dates=['2025-05-08', '05-09', '05-12'], at='high', price=0, top=0, bottom=0, label='抬高'),
                                    dict(type='level', dates=[], at='close', price=123456.78, top=0, bottom=0, label='编的价位'),
                                    dict(type='point', dates=['2031-01-01', '05-14'], at='high', price=0, top=0, bottom=0, label='不存在的日子'),
                                    dict(type='zone', dates=['05-01', '05-08'], at='close', price=0, top=0, bottom=0, label='平台'),
                                    dict(type='volume', dates=['05-12'], at='close', price=0, top=0, bottom=0, label='放量')]),
                         dict(q='成本线', look='收盘在成本线上面', say='可这里说没站回', sticker='没站回', tone='bad', evidence=4),
                         dict(q='量', look='量缩到了窗口里最小', say='地量到了', sticker='缩量了', tone='good', evidence=1)],
                  final='还不抄', watch=['等下一根收盘再看'])


class FakeClaude(BaseHTTPRequestHandler):
    seen = []            # (path, headers, body)
    reject_fallbacks = False
    reply = GOOD_REPLY   # dict -> sent as JSON text; str -> sent as is (to test broken output)

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)))
        FakeClaude.seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body))
        if FakeClaude.reject_fallbacks and 'fallbacks' in body:
            out = json.dumps({'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'fallbacks: Extra inputs are not permitted'}}).encode()
            self.send_response(400); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(out))); self.end_headers(); self.wfile.write(out); return
        ev = [('message_start', {'type': 'message_start', 'message': {'id': 'msg_test', 'type': 'message', 'role': 'assistant', 'model': body['model'],
                                                                      'content': [], 'stop_reason': None, 'stop_sequence': None,
                                                                      'usage': {'input_tokens': 10, 'output_tokens': 1}}}),
              ('content_block_start', {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}}),
              ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': FakeClaude.reply if isinstance(FakeClaude.reply, str) else json.dumps(FakeClaude.reply, ensure_ascii=False)}}),
              ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
              ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn', 'stop_sequence': None}, 'usage': {'output_tokens': 12}}),
              ('message_stop', {'type': 'message_stop'})]
        out = ''.join(f'event: {n}\ndata: {json.dumps(d, ensure_ascii=False)}\n\n' for n, d in ev).encode()
        self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.send_header('Content-Length', str(len(out))); self.end_headers(); self.wfile.write(out)


class WithKey(unittest.TestCase):
    """AI 解读的整条链路，对着本机的假 Claude 服务跑（不花钱、不出网）。真实 API 需要有密钥后手动点一次确认。"""

    @classmethod
    def setUpClass(cls):
        cls.fake = ThreadingHTTPServer(('127.0.0.1', 0), FakeClaude)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        cls.s = Server({'ANTHROPIC_API_KEY': FAKE_KEY, 'ANTHROPIC_BASE_URL': f'http://127.0.0.1:{cls.fake.server_address[1]}'})

    @classmethod
    def tearDownClass(cls):
        cls.s.stop(); cls.fake.shutdown()

    def call(self):
        FakeClaude.seen.clear()
        return http(self.s.port, '/api/ai/analyze', {'ticker': 'NVDA', 'asof': '2025-05-13', 'force': True})    # 每个用例都要真的调用一次

    def test_request_shape_and_key_stays_in_backend(self):
        FakeClaude.reject_fallbacks = False
        meta = http(self.s.port, '/api/meta')[1]
        self.assertTrue(json.loads(meta)['ai']['enabled'])
        code, body = self.call(); res = json.loads(body)
        self.assertEqual(code, 200, body); self.assertEqual(res['source'], 'claude'); n = res['narration']
        # 内容是 Claude 的：讲几步、讲什么、什么顺序、小标题、贴纸，都原样保留
        self.assertEqual((n['hook'], len(n['steps'])), ('停，先别急着抄', 3))
        self.assertEqual([s['q'] for s in n['steps']], ['缺口没补', '成本线', '量'])
        self.assertEqual((n['steps'][0]['evidence'], n['steps'][0]['ok'], n['steps'][0]['sticker']), (0, None, '有压力'))   # 和四要素无关的一步
        self.assertEqual((n['steps'][2]['ok'], n['steps'][2]['sticker']), (True, '缩量了'))
        # 画图指令：Claude 只说标哪一天的哪个位置，价位是后端从 K 线数据里取的；编的价位、不存在或回放日之后的日子都被丢掉
        B = E.load(panel.csv_path('NVDA')); at = lambda d, k: round(float(B[k][B['d'].index(d)]), 2)
        dr = n['steps'][0]['draw']
        self.assertEqual([m['type'] for m in dr], ['point', 'path', 'zone', 'volume'])
        self.assertEqual(dr[0], dict(type='point', date='2025-05-12', price=at('2025-05-12', 'l'), label='坑'))
        self.assertEqual(dr[1]['points'], [dict(date=d, price=at(d, 'h')) for d in ('2025-05-08', '2025-05-09', '2025-05-12')])
        a, b = B['d'].index('2025-05-01'), B['d'].index('2025-05-08')
        self.assertEqual((dr[2]['date_from'], dr[2]['date_to'], dr[2]['top'], dr[2]['bottom']),
                         ('2025-05-01', '2025-05-08', round(float(B['h'][a:b + 1].max()), 2), round(float(B['l'][a:b + 1].min()), 2)))
        self.assertEqual(dr[3], dict(type='volume', dates=['2025-05-12'], label='放量'))
        self.assertEqual(n['steps'][1]['draw'], [])
        # 引擎说了算的只有两处：这一天是 4/4，所以“成本线没站回”的贴纸被换掉，大字结论“还不抄”被换掉
        self.assertEqual((n['steps'][1]['ok'], n['steps'][1]['sticker'], n['steps'][1]['tone']), (True, '站回来了', 'good'))
        self.assertEqual(n['final'], '4/4，四样齐了'); self.assertEqual(res['card']['verdict'], '可以入场（仅观察）')
        path, headers, req = FakeClaude.seen[-1]
        sent = headers.get('x-api-key') or headers.get('authorization', '').replace('Bearer ', '')
        self.assertEqual(sent, FAKE_KEY)                                          # the key goes to the API ...
        for text in (meta, body, self.s.output(), http(self.s.port, '/')[1], http(self.s.port, '/static/app.js')[1]):
            self.assertNotIn(FAKE_KEY, text)                                      # ... and nowhere else
        self.assertEqual(req['model'], json.loads(meta)['ai']['model'])
        self.assertIn('以输入里引擎的结果为准', req['system']); self.assertIn('不给具体下单指令', req['system'])
        self.assertIn('都由你根据盘面决定', req['system']); self.assertNotIn('按固定顺序', req['system'])       # 内容自由，不再固定四问
        self.assertTrue(req['system'].startswith('你是一个交易图表解说员'))
        self.assertTrue(req.get('stream'))
        self.assertEqual(req['output_config']['format']['type'], 'json_schema')     # 只允许按结构输出 JSON
        self.assertNotIn('thinking', req); self.assertNotIn('temperature', req)
        payload = json.loads(req['messages'][0]['content'])
        self.assertEqual(len(payload['bars']['rows']), 60)                        # 最近 60 根
        self.assertEqual(payload['bars']['rows'][-1][0], '2025-05-13')            # 不含回放日之后的 K 线
        self.assertEqual(payload['conclusion_code'], 'all4')
        self.assertEqual([payload[k]['ok'] for k in ('e1', 'e2', 'e3', 'e4')], [True] * 4)
        self.assertIn('next_close_needs', payload); self.assertNotIn('signals', payload)

    def test_unverifiable_number_is_flagged_not_dropped(self):
        """Free analysis: Claude may compute its own numbers. Ones that cannot be traced are flagged for the reader."""
        bad = json.loads(json.dumps(GOOD_REPLY)); bad['steps'][2]['look'] = '收盘站上 123456.78'
        FakeClaude.reply = bad
        try:
            res = json.loads(self.call()[1])
        finally:
            FakeClaude.reply = GOOD_REPLY
        self.assertEqual((res['source'], res['code'], res['unverified']), ('claude', 'numbers', ['123456.78']))
        self.assertIn('找不到', res['notice']); self.assertEqual(res['narration']['steps'][2]['look'], '收盘站上 123456.78')
        # 测试开关：往正常输出里塞一个假数字，同样被标出来
        res = json.loads(http(self.s.port, '/api/ai/analyze', {'ticker': 'NVDA', 'asof': '2025-05-13', 'test_fake_number': True})[1])
        self.assertEqual(res['unverified'], ['987.65']); self.assertIn('找不到', res['notice'])

    def test_broken_json_is_retried_once_then_template(self):
        FakeClaude.reply = '这不是 JSON'
        try:
            code, body = self.call(); res = json.loads(body)
        finally:
            FakeClaude.reply = GOOD_REPLY
        self.assertEqual((code, res['source'], res['code']), (200, 'template', 'parse'))
        self.assertEqual(len(FakeClaude.seen), 2)                                   # 重试了一次
        self.assertIn('已改用模板', res['notice'])

    def test_falls_back_to_plain_request_when_fallback_option_is_rejected(self):
        FakeClaude.reject_fallbacks = True
        try:
            code, body = self.call()
        finally:
            FakeClaude.reject_fallbacks = False
        self.assertEqual(code, 200, body)
        self.assertEqual(['fallbacks' in r[2] for r in FakeClaude.seen], [True, False])

    def test_reading_is_saved_locally_and_shown_again_without_a_new_call(self):
        code, body = http(self.s.port, '/api/ai/analyze', {'ticker': 'QQQ', 'asof': '2009-03-18'})
        self.assertEqual(code, 200, body)
        n = len(FakeClaude.seen)
        res = json.loads(http(self.s.port, '/api/ai/cached?ticker=QQQ&asof=2009-03-18')[1])
        self.assertEqual(len(FakeClaude.seen), n)                                   # 读缓存不调用 API
        self.assertTrue(res['found'] and res['same_input'])
        self.assertEqual(res['entry']['narration']['hook'], '停，先别急着抄')
        nar = json.loads(http(self.s.port, '/api/ai/narrate?ticker=QQQ&asof=2009-03-18')[1])
        self.assertEqual((nar['source'], nar['polished']['source'], nar['polished']['same_input']), ('template', 'claude', True))
        self.assertEqual(len(FakeClaude.seen), n)
        self.assertTrue(os.path.exists(os.path.join(self.s.cache, 'QQQ_2009-03-18.json')))
        self.assertFalse(os.path.exists(os.path.join(ROOT, 'cache', 'ai', 'QQQ_2009-03-18.json')))
        self.assertFalse(json.loads(http(self.s.port, '/api/ai/cached?ticker=QQQ&asof=2009-03-19')[1])['found'])
        # 记忆：盘面没变再点分析，给回保存的那一版，不调用 API；明确带 force 才重新分析
        again = json.loads(http(self.s.port, '/api/ai/analyze', {'ticker': 'QQQ', 'asof': '2009-03-18'})[1])
        self.assertEqual(len(FakeClaude.seen), n)
        self.assertEqual((again['reused'], again['cached'], again['same_input'], again['source']), (True, True, True, 'claude'))
        self.assertEqual(again['narration'], res['entry']['narration'])
        forced = json.loads(http(self.s.port, '/api/ai/analyze', {'ticker': 'QQQ', 'asof': '2009-03-18', 'force': True})[1])
        self.assertEqual(len(FakeClaude.seen), n + 1)
        self.assertNotIn('reused', forced)
        # 状态里带着“这一天有没有保存过”，前端据此决定要不要直接显示
        self.assertEqual(json.loads(http(self.s.port, '/api/state?ticker=QQQ&asof=2009-03-18')[1])['ai_saved'], {'four': True, 'houshou': False, 'any': True, 'variants': ['']})   # 每个组合各记各的
        self.assertEqual(json.loads(http(self.s.port, '/api/state?ticker=QQQ&asof=2009-03-19')[1])['ai_saved'], {'four': False, 'houshou': False, 'any': False, 'variants': []})
        self.assertEqual(http(self.s.port, '/api/ai/cached?ticker=XXXX&asof=2009-03-18')[0], 404)

    def test_houshou_model_gets_its_own_reading_and_memory(self):
        """后手模型：Claude 拿到面板的结果（表盘、清单、结构线），解读按模型分开保存，互不覆盖；四证那份的记忆不受影响。"""
        four = json.loads(http(self.s.port, '/api/ai/analyze', {'ticker': 'QQQ', 'asof': '2016-05-16'})[1])
        n = len(FakeClaude.seen)
        res = json.loads(http(self.s.port, '/api/ai/analyze', {'ticker': 'QQQ', 'asof': '2016-05-16', 'model': 'houshou'})[1])
        self.assertEqual(len(FakeClaude.seen), n + 1)
        self.assertEqual((res['source'], res['rule_model'], four['rule_model']), ('claude', 'houshou', 'four'))
        self.assertTrue(all(st['evidence'] == 0 for st in res['narration']['steps']))        # 后手模型没有四项证据可对
        sent = json.loads(FakeClaude.seen[-1][2]['messages'][0]['content'])
        self.assertEqual(sent['quant']['selected_model'], '后手·成本线回踩 v0.2')
        self.assertEqual(sent['quant']['rule_signal']['phase'], '回落中')
        self.assertIn('写死的', FakeClaude.seen[-1][2]['system'])                             # 提示词里说了：清单跟不上走势时直接说
        self.assertTrue(os.path.exists(os.path.join(self.s.cache, 'QQQ_2016-05-16_houshou.json')))
        again = json.loads(http(self.s.port, '/api/ai/analyze', {'ticker': 'QQQ', 'asof': '2016-05-16', 'model': 'houshou'})[1])
        self.assertEqual((len(FakeClaude.seen), again['reused']), (n + 1, True))             # 记忆照样有效
        sv = json.loads(http(self.s.port, '/api/state?ticker=QQQ&asof=2016-05-16')[1])['ai_saved']
        self.assertEqual((sv['four'], sv['houshou'], sv['any'], sorted(sv['variants'])), (True, True, True, ['', 'houshou']))
        nar = json.loads(http(self.s.port, '/api/ai/narrate?ticker=QQQ&asof=2016-05-16&model=four')[1])
        self.assertEqual((nar['polished']['rule_model'], nar['polished']['same_input']), ('four', True))

    def test_fingerprint_follows_market_and_positions_only(self):
        """同一盘面、同一批仓位 = 同一份解读。换模型、改提示词、仓位文件重新同步、过了几天，都不算变。"""
        import ai_explain, narrate
        f = narrate.build_facts('SPCX', '2026-11-13'); bars = [['2026-11-13', 1, 1, 1, 1, 1]]; cfg = dict(ai_model='m1', ai_effort='medium')
        pos = dict(positions=[dict(symbol='SPCX', qty=1)], positions_asof='x', positions_stale=False)
        a = ai_explain.fingerprint(f, bars, None, cfg)
        self.assertEqual(a, ai_explain.fingerprint(f, bars, None, cfg))
        self.assertEqual(a, ai_explain.fingerprint(f, bars, None, dict(cfg, ai_model='m2', ai_effort='high')))
        self.assertEqual(a, ai_explain.fingerprint(dict(f, notes=['K 线数据只到 2026-11-13，还差 2 个交易日没更新。']), bars, None, cfg))
        self.assertNotEqual(a, ai_explain.fingerprint(f, [['2026-11-13', 1, 1, 1, 2, 1]], None, cfg))
        self.assertNotEqual(a, ai_explain.fingerprint(dict(f, close=f['close'] + 1), bars, None, cfg))
        b = ai_explain.fingerprint(f, bars, None, cfg, pos)
        self.assertNotEqual(a, b)
        self.assertEqual(b, ai_explain.fingerprint(f, bars, None, cfg, dict(pos, positions_asof='y', positions_stale=True)))
        self.assertNotEqual(b, ai_explain.fingerprint(f, bars, None, cfg, dict(pos, positions=[dict(symbol='SPCX', qty=2)])))


class Freshness(unittest.TestCase):
    """数据过期判定：按美股交易日历（含假日），收盘 4 小时后才要求数据到当天。"""

    def at(self, s):
        import datetime
        from zoneinfo import ZoneInfo
        return datetime.datetime.fromisoformat(s).replace(tzinfo=ZoneInfo('America/New_York'))

    def test_expected_last_session(self):
        cases = {'2026-11-14 10:00': '2026-11-13',     # Saturday
                 '2026-11-16 19:59': '2026-11-13',     # Monday, close + 4h not yet passed
                 '2026-11-16 20:00': '2026-11-16',
                 '2026-11-26 22:00': '2026-11-25',     # Thanksgiving
                 '2026-12-28 09:00': '2026-12-24',     # Christmas Friday + weekend
                 '2027-04-05 21:00': '2027-04-05'}
        for now, want in cases.items():
            self.assertEqual(panel.expected_last_session(self.at(now)), want, now)

    def test_lag_counts_sessions_not_days(self):
        # 不写死日期：真实数据每天往后长。取现在的最后一根，再找它之后的下一个交易日
        last = panel.load('SPCX')['B']['d'][-1]
        nxt = datetime.date.fromisoformat(last) + datetime.timedelta(days=1)
        while not panel.is_session(nxt):
            nxt += datetime.timedelta(days=1)
        f = panel.freshness('SPCX', self.at(f'{nxt} 21:00'))             # 下一个交易日收盘很久之后：差一根，算过期
        self.assertEqual((f['last'], f['expected'], f['lag_sessions'], f['stale']), (last, str(nxt), 1, True))
        f = panel.freshness('SPCX', self.at(f'{nxt} 12:00'))             # 下一个交易日盘中：那根还没收盘，不算过期
        self.assertFalse(f['stale']); self.assertTrue(f['calendar_known'])
        self.assertFalse(panel.freshness('SPCX', self.at('2028-03-01 12:00'))['calendar_known'])

    def test_stale_server_shows_it_everywhere(self):
        """A copy of the data with the last three SPCX rows removed: the page must say it is out of date."""
        tmp = tempfile.mkdtemp(prefix='fe_stale_')
        try:
            for f in os.listdir(os.path.join(ROOT, 'data')):
                if os.path.isfile(os.path.join(ROOT, 'data', f)):       # data/notes 是目录（K 线备注），不用带
                    shutil.copy(os.path.join(ROOT, 'data', f), tmp)
            with open(os.path.join(tmp, 'SPCX.csv'), newline='') as f:
                lines = f.read().splitlines(keepends=True)
            with open(os.path.join(tmp, 'SPCX.csv'), 'w', newline='') as f:
                f.write(''.join(lines[:-3]))
            s = Server({'FE_DATA_DIR': tmp})
            try:
                st = json.loads(http(s.port, '/api/state?ticker=SPCX')[1])
                self.assertTrue(st['freshness']['stale']); self.assertGreaterEqual(st['freshness']['lag_sessions'], 3)
                self.assertIn('不是最新状态', st['notes'][0])
                self.assertTrue(json.loads(http(s.port, '/api/data/version')[1])['SPCX']['stale'])
                chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
                if os.path.exists(chrome):
                    prof = tempfile.mkdtemp(prefix='fe_chrome_')
                    dom = subprocess.run([chrome, '--headless=new', '--disable-gpu', '--no-first-run', f'--user-data-dir={prof}', '--window-size=1600,960',
                                          '--virtual-time-budget=9000', '--dump-dom', f'http://localhost:{s.port}/?t=SPCX'], capture_output=True, text=True, timeout=120).stdout
                    shutil.rmtree(prof, ignore_errors=True)
                    self.assertIn('id="evStale"', dom)
                    self.assertIn('数据未更新：只到', dom)
            finally:
                s.stop()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Narration(unittest.TestCase):
    """视频式解说的模板版和核对逻辑（不调用 API）。"""

    def test_spcx_two_of_four(self):
        import narrate
        n = narrate.template(narrate.build_facts('SPCX', '2026-11-13'))
        self.assertEqual([s['sticker'] for s in n['steps']], ['不抄！', '报警而已', '证据+1', '没得站'])
        self.assertEqual([s['ok'] for s in n['steps']], [False, True, True, False]); self.assertEqual(n['final'], '2/4，还不抄')

    def test_every_template_number_traces_to_the_engine(self):
        import narrate
        rng = random.Random(7)
        for t in panel.TICKERS:
            B = E.load(panel.csv_path(t)); S = E.compute(B)
            picks = {len(B['d']) - 1} | {rng.randrange(60, len(B['d'])) for _ in range(25)} | {int(k) for k in np.flatnonzero(S['all4'])[:8]}
            for i in sorted(picks):
                f = narrate.build_facts(t, B['d'][i]); n = narrate.template(f)
                self.assertEqual(narrate.bad_numbers(n, narrate.allowed_numbers(f)), [], (t, B['d'][i], n))
                self.assertEqual([s['ok'] for s in n['steps']], [bool(S[k][i] and S['dd_ok'][i]) for k in ('e1', 'e2', 'e3', 'e4')])
                self.assertTrue(all(s['sticker'] in narrate.STICKERS for s in n['steps']))

    def test_watch_lines_equal_four_evidence_check(self):
        import narrate, four_evidence_check
        for t in panel.TICKERS:
            f = narrate.build_facts(t)
            if f['armed']:
                self.assertEqual(f['next_close_needs'], four_evidence_check.check(t)['next_close_needs'], t)

    def test_fake_number_is_caught(self):
        import narrate
        f = narrate.build_facts('QQQ', '2026-11-13'); n = narrate.template(f)
        n['steps'][0]['look'] += '，目标 987.65'
        self.assertEqual(narrate.bad_numbers(n, narrate.allowed_numbers(f)), ['987.65'])

    def test_claude_cannot_change_the_verdict(self):
        import narrate
        f = narrate.build_facts('QQQ', '2026-11-13'); tm = narrate.template(f)
        raw = dict(GOOD_REPLY, final='可以抄了', steps=[dict(look='看', say='说', sticker='证据+1', evidence=1, ok=True)] * 4)
        n, why = narrate.normalize(raw, f, tm)
        self.assertIsNone(why); self.assertEqual(n['final'], '未触发，不抄')
        self.assertEqual([s['ok'] for s in n['steps']], [False] * 4); self.assertNotIn('证据+1', [s['sticker'] for s in n['steps']])
        self.assertEqual(narrate.normalize(dict(raw, steps=raw['steps'][:1]), f, tm)[0], None)          # 至少两步
        self.assertEqual(narrate.normalize(dict(raw, steps=raw['steps'] * 3), f, tm)[0], None)          # 至多八步
        free = dict(GOOD_REPLY, final='还不抄', steps=[dict(q='缺口', look='看', say='说', sticker='假突破', tone='bad', evidence=0)] * 6)
        n, why = narrate.normalize(free, f, tm)                                                         # 六步、全是引擎没覆盖的角度：原样接受
        self.assertEqual((len(n['steps']), n['steps'][0]['sticker'], n['steps'][0]['ok'], n['final']), (6, '假突破', None, '还不抄'))


class LiveLayer(unittest.TestCase):
    """盘中实时价：只画图。这里不连网，直接往 LiveFeed 里塞时段和成交价。"""

    def feed(self, now, bar=True, tick=None, date='2026-11-16'):
        import live
        f = live.LiveFeed(['SPCX'])
        f._ensure_thread = lambda: None                       # no websocket in tests
        start, end = 1_000_000, 1_000_000 + 23400
        f.sessions['SPCX'] = dict(date=date, start=start, end=end, gmtoffset=-18000, prev_close=139.11, price=140.0, price_time=start + 60,
                                  bar=dict(o=140.0, h=141.0, l=139.5, c=140.5, v=1000.0) if bar else None, fetched_at=10 ** 12)
        if tick:
            f.ticks['SPCX'] = tick
        self._real = live._now
        live._now = lambda: start + now
        self.addCleanup(lambda: setattr(live, '_now', self._real))
        return f, start, end

    def test_regular_session_tick_extends_the_bar(self):
        f, start, end = self.feed(3600, tick=dict(price=142.2, time=1_000_000 + 3590, day_high=None, day_low=None, day_volume=5000))
        s = f.snapshot('SPCX', '2026-11-13')
        self.assertEqual((s['status'], s['show_candle'], s['session_date']), ('regular', True, '2026-11-16'))
        self.assertEqual((s['bar']['o'], s['bar']['h'], s['bar']['l'], s['bar']['c'], s['bar']['v']), (140.0, 142.2, 139.5, 142.2, 5000))
        self.assertEqual(s['price'], 142.2); self.assertIsNone(s['outside'])

    def test_after_hours_tick_never_touches_the_bar(self):
        f, start, end = self.feed(23400 + 3600, tick=dict(price=150.0, time=1_000_000 + 23400 + 3500, day_high=None, day_low=None, day_volume=None))
        s = f.snapshot('SPCX', '2026-11-13')
        self.assertEqual((s['status'], s['bar']['c'], s['bar']['h']), ('closed_pending', 140.5, 141.0))     # 盘后价不计入 K 线
        self.assertEqual(s['outside']['price'], 150.0); self.assertTrue(s['show_candle'])

    def test_candle_disappears_once_the_day_is_stored(self):
        f, start, end = self.feed(23400 + 3600)
        s = f.snapshot('SPCX', '2026-11-16')                  # 当天的日线已经入库
        self.assertEqual((s['status'], s['show_candle']), ('closed', False))

    def test_disabled_and_no_data(self):
        import live
        self.assertFalse(live.LiveFeed(['SPCX'], enabled=False).snapshot('SPCX', '2026-11-13')['ok'])
        f, _, _ = self.feed(100, bar=False)
        self.assertFalse(f.snapshot('SPCX', '2026-11-13')['show_candle'])

    def test_live_module_never_writes_data_or_calls_the_engine(self):
        with open(os.path.join(ROOT, 'live.py'), encoding='utf-8') as f:
            src = f.read()
        code = '\n'.join(l for l in src.split('"""')[2].splitlines() if not l.strip().startswith('#'))     # skip the module docstring
        for word in ('import engine', 'import panel', "open(", '.csv', 'prep_data'):
            self.assertNotIn(word, code, word)

    def test_state_is_identical_with_live_on_or_off(self):
        """The rule state comes only from data/*.csv: a server with live disabled gives the same state as panel.state_at."""
        s = Server()
        try:
            self.assertFalse(json.loads(http(s.port, '/api/live?ticker=SPCX')[1])['ok'])
            a = json.loads(http(s.port, '/api/state?ticker=SPCX&asof=2026-11-13')[1])
            b = panel.state_at('SPCX', '2026-11-13')
            self.assertEqual(a['evidence'], b['evidence']); self.assertEqual(a['levels'], json.loads(json.dumps(b['levels'])))
        finally:
            s.stop()


class Weekly(unittest.TestCase):
    def test_aggregation(self):
        B = E.load(panel.csv_path('NVDA')); W = panel.weekly(B)
        self.assertEqual(sum(W['v']), sum(B['v']))
        self.assertEqual(W['d'][-1], B['d'][-1]); self.assertEqual(W['c'][-1], B['c'][-1])
        k = W['d'].index('2025-05-16'); a = B['d'].index('2025-05-12'); b = B['d'].index('2025-05-16')
        self.assertEqual((W['o'][k], W['h'][k], W['l'][k], W['c'][k]), (B['o'][a], B['h'][a:b + 1].max(), B['l'][a:b + 1].min(), B['c'][b]))
        self.assertTrue(all(x < y for x, y in zip(W['d'], W['d'][1:])))

    def test_no_lookahead_when_sliced(self):
        """Weekly bars built from data cut at a date equal the full weekly series cut at that date."""
        B = E.load(panel.csv_path('QQQ'))
        full = panel.weekly(B)
        for d in ('2009-03-13', '2020-03-20', '2025-05-16'):
            i = B['d'].index(d); part = panel.weekly(panel.truncate(B, i)); k = full['d'].index(d)
            self.assertEqual(part['d'], full['d'][:k + 1])
            self.assertTrue(np.allclose(part['c'], full['c'][:k + 1]) and np.allclose(part['v'], full['v'][:k + 1]))

    def test_payload(self):
        b = panel.bars_payload('SPCX', 'W')
        self.assertEqual((b['tf'], b['lowvol']), ('W', []))
        self.assertLess(len(b['d']), len(panel.bars_payload('SPCX')['d']))
        dif, dea, hist = E.macd(panel.weekly(E.load(panel.csv_path('SPCX')))['c'])
        self.assertAlmostEqual(b['hist'][-1], hist[-1], places=5)
        json.dumps(b, allow_nan=False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
