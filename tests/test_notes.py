"""「时效与备注」的测试。运行：.venv/bin/python tests/test_notes.py

备注目录是临时目录，不碰 data/notes；不连 Yahoo，不调用真实的 Claude。
要点：备注不进规则引擎；回放只看到那一天以及之前的；联网搜到的东西对不上搜索结果里的链接就丢掉；查过的日子不再查。
"""
import json, os, shutil, sys, tempfile, threading, time, unittest
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'tests'))
TMP = tempfile.mkdtemp(prefix='fe_notes_unit_')
os.environ['FE_NOTES_DIR'] = TMP
import notes                # noqa: E402
import panel                # noqa: E402
from test_panel import Server, http, FakeClaude, FAKE_KEY     # noqa: E402

EVENTS = [dict(date='2026-08-26', kind='earnings', title='财报日'), dict(date='2026-11-17', kind='earnings', title='财报日'),
          dict(date='2026-09-10', kind='dividend', title='除息日，每股派 0.01'), dict(date='bad', kind='earnings', title='x'), dict(date='2026-01-01', kind='ufo', title='x')]
HEADS = [dict(date='2026-11-07', title='周六出的消息', source='某媒体', url='https://example.com/a'),         # 周六 → 记在周一那根
         dict(date='2026-11-05', title='暴跌当天的报道', source='某媒体', url='https://example.com/b')]
HEADS_EN = [dict(date='2026-11-13', title='PPI +6.5% YoY: Highest in Nearly 4 Years', source='Zacks', url='https://example.com/en1'),
            dict(date='2026-11-13', title='Nvidia Rebounds After Huang Exit as Treasury Yields Top 5%', source='24/7 Wall St.', url='https://example.com/en2')]
NOW = time.mktime(time.strptime('2026-11-16 12:00:00', '%Y-%m-%d %H:%M:%S'))


def clean():
    for f in os.listdir(TMP):
        os.unlink(os.path.join(TMP, f))


class Store(unittest.TestCase):
    def setUp(self):
        clean()
        self.rep = notes.refresh('NVDA', events=lambda t: EVENTS, headlines=lambda t: HEADS, now=NOW)

    def test_refresh_keeps_valid_rows_with_source_and_time(self):
        self.assertEqual((self.rep['events'], self.rep['news_added'], self.rep['errors']), (3, 2, []))
        x = notes.load('NVDA')
        self.assertEqual((x['events']['source'], x['events']['fetched_at'], x['news_since']), ('Yahoo Finance', '2026-11-16 12:00:00', '2026-11-16'))
        self.assertTrue(all(i['url'] and i['source'] and i['fetched_at'] for i in x['items']))
        again = notes.refresh('NVDA', events=lambda t: EVENTS, headlines=lambda t: HEADS, now=NOW + 60)
        self.assertEqual(again['news_added'], 0)                    # 同一条标题不存两遍
        self.assertEqual(len(notes.load('NVDA')['items']), 2)

    def test_network_trouble_is_reported_not_raised(self):
        def boom(t):
            raise OSError('no network')
        rep = notes.refresh('NVDA', events=boom, headlines=boom, now=NOW)
        self.assertEqual(len(rep['errors']), 2)
        self.assertEqual(len(notes.load('NVDA')['events']['items']), 3)       # 原来的还在

    def test_payload_maps_to_bars_and_marks_facts(self):
        p = notes.payload('NVDA', now=NOW)
        self.assertEqual([r['kind'] for r in p['by_date']['2026-08-26']], ['earnings'])
        self.assertTrue(p['by_date']['2026-08-26'][0]['fact'])
        self.assertEqual(p['by_date']['2026-11-09'][0]['title'], '周六出的消息')        # 休市日的消息记在下一个交易日
        self.assertFalse(p['by_date']['2026-11-09'][0]['fact'])
        self.assertEqual((p['upcoming']['date'], p['upcoming']['days_left']), ('2026-11-17', 1))
        self.assertEqual(p['freshness']['events_stale'], False)
        self.assertEqual(p['freshness']['counts'], dict(events=2, notes=2))
        self.assertEqual(len(p['notable']), 5)
        self.assertTrue(all(r['why'] and not r['searched'] for r in p['notable']))

    def test_replay_sees_only_that_day_and_before(self):
        p = notes.payload('NVDA', '2026-09-01', now=NOW)
        self.assertEqual(sorted(p['by_date']), ['2026-08-26'])
        self.assertIsNone(p['upcoming'])                             # 回放时不给“下一次财报”：那是后来才知道的日程
        self.assertTrue(all(r['date'] <= '2026-09-01' for r in p['notable']))
        self.assertEqual(notes.for_ai('NVDA', '2026-09-01')['next_earnings'], None)

    def test_stale_gate(self):
        p = notes.payload('NVDA', now=NOW + 8 * 86400)
        self.assertTrue(p['freshness']['events_stale']); self.assertGreater(p['freshness']['events_age_days'], 7)
        clean()
        self.assertTrue(notes.payload('NVDA', now=NOW)['freshness']['events_stale'])      # 从没取过也算过时
        self.assertIsNone(notes.payload('NVDA', now=NOW)['freshness']['news_since'])

    def test_manual_notes(self):
        it = notes.add_manual('NVDA', '2026-11-05', '  财报不及预期，盘后大跌  ', now=NOW + 5)
        self.assertEqual((it['kind'], it['title'], it['source']), ('manual', '财报不及预期，盘后大跌', '你自己写的'))
        rows = notes.payload('NVDA', now=NOW)['by_date']['2026-11-05']
        self.assertEqual([r['kind'] for r in rows], ['manual', 'news'])                   # 手写的排在标题前面
        self.assertEqual(notes.count_since('NVDA', None, '2026-11-16 12:00:01'), 1)
        self.assertEqual(notes.count_since('NVDA', None, '2026-11-16 12:00:10'), 0)
        with self.assertRaises(ValueError):
            notes.add_manual('NVDA', '2026-11-07', '周六不是交易日')
        with self.assertRaises(ValueError):
            notes.add_manual('NVDA', '2026-11-05', '   ')
        with self.assertRaises(KeyError):
            notes.add_manual('XXXX', '2026-11-05', 'x')
        self.assertEqual(notes.delete('NVDA', it['id']), 1)
        self.assertEqual(notes.delete('NVDA', it['id']), 0)

    def test_what_the_ai_is_told(self):
        a = notes.for_ai('NVDA', None)
        self.assertEqual({r['date'] for r in a['notes']}, {'2026-08-26', '2026-09-10', '2026-11-05', '2026-11-09'})
        self.assertEqual([r['fact'] for r in a['notes'] if r['date'] == '2026-08-26'], [True])
        self.assertIn('没有备注不等于那天没事发生', a['coverage'])
        self.assertEqual(a['news_archive_since'], '2026-11-16')

    def test_headlines_are_translated_once_and_kept_with_the_original(self):
        notes.refresh('NVDA', events=lambda t: EVENTS, headlines=lambda t: HEADS_EN, now=NOW)
        rows = notes.pending_translation('NVDA')
        self.assertEqual([r['title'][:3] for r in rows], ['PPI', 'Nvi'])                  # 中文标题不用翻，只挑英文的
        self.assertEqual(notes.payload('NVDA', now=NOW)['freshness']['untranslated'], 2)
        done = notes.store_translation('NVDA', [r['id'] for r in rows], ['PPI 同比上涨 6.5%，近 4 年最高', 'not chinese'], dict(model='m'), now=NOW)
        self.assertEqual(done, 1)                                                         # 第二条不是中文：不收，保持英文
        p = notes.payload('NVDA', now=NOW)
        got = {r['title']: r.get('title_zh') for r in p['by_date']['2026-11-13']}
        self.assertEqual(got, {'PPI +6.5% YoY: Highest in Nearly 4 Years': 'PPI 同比上涨 6.5%，近 4 年最高', 'Nvidia Rebounds After Huang Exit as Treasury Yields Top 5%': None})
        self.assertEqual((p['freshness']['headlines_zh'], p['freshness']['untranslated']), (1, 0))   # 翻失败的那条不反复重试
        self.assertEqual(notes.pending_translation('NVDA'), [])
        late = [dict(date='2026-11-16', title='News after the last bar', source='X', url='https://example.com/late')]
        notes.refresh('NVDA', events=lambda t: EVENTS, headlines=lambda t: late, now=NOW)
        p2 = notes.payload('NVDA', now=NOW)
        self.assertEqual([r['title'] for r in p2['pending']], ['News after the last bar'])       # 最后一根 K 线之后的消息：单独列出，不丢
        self.assertNotIn('2026-11-16', p2['by_date']); self.assertEqual(p2['freshness']['untranslated'], 1)
        self.assertEqual(notes.payload('NVDA', '2026-11-12', now=NOW)['pending'], [])            # 回放时不给
        notes.delete('NVDA', notes.pending_translation('NVDA')[0]['id'])
        self.assertIn('PPI 同比上涨 6.5%，近 4 年最高', [n['text'] for n in notes.for_ai('NVDA', None)['notes']])   # 交给 AI 的也是中文
        clean(); notes.refresh('NVDA', events=lambda t: EVENTS, headlines=lambda t: HEADS_EN, now=NOW)
        rows = notes.pending_translation('NVDA')
        self.assertEqual(notes.store_translation('NVDA', [r['id'] for r in rows], ['只有一条'], dict(model='m')), 0)     # 条数对不上：一条都不收
        self.assertTrue(all(not r.get('title_zh') for r in notes.payload('NVDA', now=NOW)['by_date']['2026-11-13']))

    def test_notes_never_touch_the_engine(self):
        before = panel.state_at('NVDA')
        notes.add_manual('NVDA', '2026-11-13', '随便写一条', now=NOW)
        after = panel.state_at('NVDA')
        self.assertEqual((before['evidence'], before['conclusion'], before['levels']), (after['evidence'], after['conclusion'], after['levels']))


def message(text, results, cites=()):
    return dict(content=[
        dict(type='server_tool_use', id='s1', name='web_search', input=dict(query='q')),
        dict(type='web_search_tool_result', tool_use_id='s1', content=[dict(type='web_search_result', url=u, title='t', encrypted_content='x') for u in results]),
        dict(type='text', text=text, citations=[dict(type='web_search_result_location', url=u, title='t', cited_text='c') for u in cites])])


class Verify(unittest.TestCase):
    """联网搜到的东西：只留搜索结果里真实出现过链接的那几条。"""

    def test_keeps_only_items_backed_by_a_returned_link(self):
        txt = '查到了：' + json.dumps(dict(items=[
            dict(date='2026-11-05', what='财报后下调指引', source='路透', url='https://www.reuters.com/a/?utm=1'),       # 链接在结果里（规范化后相同）
            dict(date='2026-11-05', what='模型自己编的', source='某报', url='https://made-up.example/x'),              # 结果里没有 → 丢
            dict(date='2026-11-06', what='引用里出现的链接', source='彭博', url='https://bloomberg.com/b'),            # 只在引用里 → 留
            dict(date='2026-10-01', what='日期差太远', source='路透', url='https://reuters.com/a'),                    # 不在问的那几天附近 → 丢
            dict(date='2026-11-05', what='', source='路透', url='https://reuters.com/a'), 'not a dict']), ensure_ascii=False)
        kept, dropped, searches = notes.verify_search(message(txt, ['https://reuters.com/a'], ['https://www.bloomberg.com/b/']), ['2026-11-05'])
        self.assertEqual([k['title'] for k in kept], ['财报后下调指引', '引用里出现的链接'])
        self.assertEqual((dropped, searches), (4, 1))

    def test_errors_and_garbage_yield_nothing(self):
        err = dict(content=[dict(type='web_search_tool_result', tool_use_id='s', content=dict(type='web_search_tool_result_error', error_code='max_uses_exceeded')),
                            dict(type='text', text='{"items": [{"date": "2026-11-05", "what": "x", "source": "s", "url": "https://a.example/1"}]}')])
        self.assertEqual(notes.verify_search(err, ['2026-11-05']), ([], 1, 0))
        self.assertEqual(notes.verify_search(dict(content=[dict(type='text', text='没有找到可靠的报道。')]), ['2026-11-05']), ([], 0, 0))
        self.assertEqual(notes.verify_search(dict(content=[dict(type='text', text='{"items": [')]), ['2026-11-05']), ([], 0, 0))

    def test_stored_once_and_days_marked_searched(self):
        clean()
        kept = [dict(date='2026-11-05', title='财报后下调指引', source='路透', url='https://reuters.com/a')]
        meta = dict(model='m', tokens_in=1, tokens_out=2, searches=1)
        self.assertEqual(notes.store_search('NVDA', ['2026-11-05', '2026-11-09'], kept, meta, now=NOW), 1)
        self.assertEqual(notes.store_search('NVDA', ['2026-11-05'], kept, meta, now=NOW), 0)          # 同一条不存两遍
        p = notes.payload('NVDA', now=NOW)
        self.assertEqual([r['kind'] for r in p['by_date']['2026-11-05']], ['search'])
        self.assertEqual(p['freshness']['searched_days'], ['2026-11-05', '2026-11-09'])               # 没找到东西的那天也记作查过
        self.assertEqual({r['date']: r['searched'] for r in p['notable'] if r['date'] in ('2026-11-05', '2026-11-09')}, {'2026-11-05': True, '2026-11-09': True})


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = ThreadingHTTPServer(('127.0.0.1', 0), FakeClaude)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        cls.s = Server({'ANTHROPIC_API_KEY': FAKE_KEY, 'ANTHROPIC_BASE_URL': f'http://127.0.0.1:{cls.fake.server_address[1]}'})
        cls.nokey = Server()
        os.environ['FE_NOTES_DIR'] = cls.s.notes
        notes.refresh('NVDA', events=lambda t: EVENTS, headlines=lambda t: HEADS, now=NOW)

    @classmethod
    def tearDownClass(cls):
        cls.s.stop(); cls.nokey.stop(); cls.fake.shutdown()
        os.environ['FE_NOTES_DIR'] = TMP

    def post(self, path, body, s=None):
        code, txt = http((s or self.s).port, path, body)
        return code, json.loads(txt)

    def test_read_write_delete(self):
        p = json.loads(http(self.s.port, '/api/notes?ticker=NVDA')[1])
        self.assertTrue(p['ok'] and '2026-08-26' in p['by_date'] and p['kinds']['earnings'] == '财报日')
        code, r = self.post('/api/notes/manual', dict(ticker='NVDA', date='2026-11-13', text='自己写的一条'))
        self.assertEqual(code, 200); self.assertIn('自己写的一条', [x['title'] for x in r['notes']['by_date']['2026-11-13']])
        self.assertEqual(self.post('/api/notes/manual', dict(ticker='NVDA', date='2026-11-14', text='周六'))[0], 400)
        self.assertEqual(self.post('/api/notes/manual', dict(ticker='XXXX', date='2026-11-13', text='x'))[0], 404)
        code, r = self.post('/api/notes/delete', dict(ticker='NVDA', id=r['item']['id']))
        self.assertEqual((code, r['removed']), (200, 1))
        self.assertNotIn('自己写的一条', [x['title'] for x in r['notes']['by_date'].get('2026-11-13', [])])
        self.assertEqual(json.loads(http(self.s.port, '/api/notes?ticker=NVDA&asof=2026-09-01')[1])['upcoming'], None)
        self.assertFalse(os.path.exists(os.path.join(ROOT, 'data', 'notes', 'NVDA.json.tmp')))

    def test_search_without_key_explains_and_charges_nothing(self):
        code, r = self.post('/api/notes/search', dict(ticker='NVDA'), self.nokey)
        self.assertEqual((code, r['ok'], r['code']), (200, False, 'disabled'))
        self.assertIn('ANTHROPIC_API_KEY', r['error'])

    def test_search_drops_unbacked_items_and_never_repeats(self):
        """假 Claude 的回答里没有任何搜索结果块：它写的条目一条都不该被存下来；查过的日子记下，下次不再调用。"""
        old = FakeClaude.reply
        FakeClaude.reply = dict(items=[dict(date='2026-11-05', what='编出来的新闻', source='某报', url='https://made-up.example/x')])
        try:
            n = len(FakeClaude.seen)
            code, r = self.post('/api/notes/search', dict(ticker='NVDA', dates=['2026-11-05']))
            self.assertEqual((code, r['ok']), (200, True), r)
            self.assertEqual((r['searched'], r['added'], r['dropped']), (['2026-11-05'], 0, 1))
            self.assertEqual(len(FakeClaude.seen), n + 1)
            sent = FakeClaude.seen[-1][2]
            self.assertEqual(sent['tools'][0]['name'], 'web_search'); self.assertTrue(sent['tools'][0]['type'].startswith('web_search_'))
            self.assertIn('2026-11-05', sent['messages'][0]['content']); self.assertIn('NVIDIA', sent['messages'][0]['content'])
            self.assertIn('不要猜', sent['system'])
            self.assertNotIn('positions', json.dumps(sent, ensure_ascii=False))               # 搜索请求里不带任何持仓
            code, r = self.post('/api/notes/search', dict(ticker='NVDA', dates=['2026-11-05']))
            self.assertEqual((r['skipped'], r['added'], len(FakeClaude.seen)), (True, 0, n + 1))  # 查过了：不再调用，不再计费
            self.assertIn('2026-11-05', r['notes']['freshness']['searched_days'])
        finally:
            FakeClaude.reply = old

    def test_translate_endpoint_translates_once(self):
        notes.refresh('QQQ', events=lambda t: [], headlines=lambda t: HEADS_EN, now=NOW)
        code, r = self.post('/api/notes/translate', dict(ticker='QQQ'), self.nokey)
        self.assertEqual((code, r['ok'], r.get('translated')), (200, True, 0))            # 没密钥的那台服务用的是另一个备注目录：没有要翻的
        old = FakeClaude.reply
        FakeClaude.reply = dict(zh=['PPI 同比上涨 6.5%，近 4 年最高', '黄仁勋离任后英伟达反弹，美债收益率突破 5%'])
        try:
            n = len(FakeClaude.seen)
            code, r = self.post('/api/notes/translate', dict(ticker='QQQ'))
            self.assertEqual((code, r['ok'], r['translated'], r['asked']), (200, True, 2, 2), r)
            sent = FakeClaude.seen[-1][2]
            self.assertEqual(json.loads(sent['messages'][0]['content'])['titles'], [h['title'] for h in HEADS_EN])
            self.assertIn('简体中文', sent['system'])
            self.assertEqual(sorted(x['title_zh'] for x in r['notes']['by_date']['2026-11-13']), sorted(FakeClaude.reply['zh']))
            self.assertEqual(r['notes']['freshness']['untranslated'], 0)
            code, r = self.post('/api/notes/translate', dict(ticker='QQQ'))
            self.assertEqual((r['skipped'], r['translated'], len(FakeClaude.seen)), (True, 0, n + 1))    # 翻过了：不再调用
        finally:
            FakeClaude.reply = old

    def test_ai_reading_gets_the_notes_and_freshness(self):
        code, r = self.post('/api/ai/analyze', dict(ticker='NVDA', force=True))
        self.assertEqual((code, r['source']), (200, 'claude'), r.get('notice'))
        sent = FakeClaude.seen[-1][2]
        body = json.loads(sent['messages'][0]['content'])
        self.assertEqual(body['context']['next_earnings']['date'], '2026-11-17')
        self.assertTrue(any(n['date'] == '2026-08-26' and n['fact'] for n in body['context']['notes']))
        self.assertIn('不要猜原因', sent['system'])
        self.assertGreaterEqual(r['notes_used'], 3)
        fp = r['fingerprint']
        self.post('/api/notes/manual', dict(ticker='NVDA', date='2026-11-13', text='解读生成之后才写的'))
        nar = json.loads(http(self.s.port, '/api/ai/narrate?ticker=NVDA')[1])['polished']
        self.assertEqual((nar['fingerprint'], nar['same_input']), (fp, True))                 # 加备注不让保存的解读作废（不会要你再花钱）
        self.assertGreaterEqual(nar['notes_since'], 0)


if __name__ == '__main__':
    try:
        unittest.main(verbosity=1)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
