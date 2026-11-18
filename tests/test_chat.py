"""AI 对话、按天保存的分析记录、切换模型不清空 的测试。运行：.venv/bin/python tests/test_chat.py

对话记录、备注、AI 解读缓存都放临时目录；Claude 用本机的假服务（不花钱、不出网）。
"""
import json, os, shutil, sys, tempfile, threading, unittest
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'tests'))
TMP = tempfile.mkdtemp(prefix='fe_chat_unit_')
os.environ['FE_CHAT_DIR'] = TMP
import chat                 # noqa: E402
from test_panel import Server, http, FakeClaude, FAKE_KEY     # noqa: E402


def events(body):
    out = []
    for blk in body.split('\n\n'):
        ev, data = None, ''
        for line in blk.split('\n'):
            if line.startswith('event:'):
                ev = line[6:].strip()
            elif line.startswith('data:'):
                data += line[5:].strip()
        if ev:
            out.append((ev, json.loads(data)))
    return out


class Store(unittest.TestCase):
    def test_messages_keep_memory_and_attach_chart_data_only_where_it_was_attached(self):
        c = chat.new('NVDA')
        c['messages'] += [dict(role='assistant', kind='explain', text='【一键解释】……'),
                          dict(role='user', text='第 3 张没看懂', context='{"ticker":"NVDA"}', chip='NVDA'),
                          dict(role='assistant', text='意思是……'),
                          dict(role='user', text='那止损呢', context=None)]
        m = chat.api_messages(c)
        self.assertEqual([x['role'] for x in m], ['user', 'assistant', 'user'])                           # 旧的一键解释卡片不发给 AI
        self.assertNotIn('一键解释', json.dumps(m, ensure_ascii=False))
        self.assertEqual([b['text'][:6] for b in m[0]['content']], ['【图表数据】', '第 3 张没'])
        self.assertEqual(len(m[2]['content']), 1)                                                         # 图表没变：第二问不再带
        self.assertEqual(m[2]['content'][-1]['cache_control'], {'type': 'ephemeral'})                     # 到这里为止的内容可缓存
        self.assertNotIn('cache_control', m[0]['content'][-1])
        self.assertNotIn('cache_control', c['messages'][3])                                               # 存档本身不被改动
        pub = chat.public(c)
        self.assertTrue(all('context' not in x for x in pub['messages']))                                 # 页面拿不到那一大段原始数据
        self.assertEqual([(x['role'], x['has_context']) for x in pub['messages']], [('user', True), ('assistant', False), ('user', False)])   # 也看不到旧卡片
        self.assertEqual(c['messages'][0]['kind'], 'explain')                                             # 旧卡片还在文件里，没删

    def test_storage_is_local_and_ids_are_checked(self):
        c = chat.new('QQQ'); c['messages'].append(dict(role='user', text='你好')); c['title'] = chat.title_from('你好')
        chat.save(c)
        self.assertTrue(os.path.exists(os.path.join(TMP, c['id'] + '.json')))
        self.assertEqual(chat.load(c['id'])['messages'][0]['text'], '你好')
        self.assertEqual([x['id'] for x in chat.listing()], [c['id']])
        for bad in ('../../etc/passwd', '', 'zzzzzzzzzzzz', None, c['id'] + '/x'):
            self.assertIsNone(chat.load(bad))
            self.assertFalse(chat.delete(bad))
        self.assertTrue(chat.delete(c['id'])); self.assertEqual(chat.listing(), [])
        long = '这是一个很长很长很长很长很长很长很长很长很长的问题'
        self.assertEqual(chat.title_from(long), long[:22] + '…'); self.assertEqual(chat.title_from('短问题'), '短问题')

    def test_system_prompt_carries_the_house_rules(self):
        for must in ('8 岁', '不说“买”“卖”', '改不改由你定', '直接说不知道', '规则是写死的', '没有被证明管用', '第一句就是结论', '最多三条理由', '不在结尾重复'):
            self.assertIn(must, chat.SYSTEM)
        self.assertIn('核心仓', chat.system())                                                          # 核心仓的规矩在他自己的规则里（起步模板就有）
        self.assertNotIn('一键解释', chat.SYSTEM)


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = ThreadingHTTPServer(('127.0.0.1', 0), FakeClaude)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        cls.s = Server({'ANTHROPIC_API_KEY': FAKE_KEY, 'ANTHROPIC_BASE_URL': f'http://127.0.0.1:{cls.fake.server_address[1]}'})
        cls.nokey = Server()
        cls.old = FakeClaude.reply
        FakeClaude.reply = '先等。**理由**：四个条件只成立了两个。'

    @classmethod
    def tearDownClass(cls):
        FakeClaude.reply = cls.old
        cls.s.stop(); cls.nokey.stop(); cls.fake.shutdown()

    def send(self, **body):
        code, txt = http(self.s.port, '/api/chat/send', body)
        self.assertEqual(code, 200, txt[:200])
        return events(txt)

    def test_conversation_streams_remembers_and_reattaches_chart_data(self):
        n = len(FakeClaude.seen)
        ev = self.send(ticker='NVDA', asof='2025-05-13', model='four', text='现在该怎么看？')
        self.assertEqual([e for e, _ in ev], ['start', 'delta', 'done'])
        cid = ev[0][1]['id']
        self.assertEqual((ev[0][1]['title'], ev[0][1]['chip']), ('现在该怎么看？', 'NVDA 2025-05-13 · 四证·抄底 v1.0'))
        self.assertEqual(ev[1][1]['text'], FakeClaude.reply)
        conv = ev[2][1]['conv']
        self.assertEqual([(m['role'], m['has_context']) for m in conv['messages']], [('user', True), ('assistant', False)])
        self.assertEqual(conv['messages'][1]['text'], FakeClaude.reply)
        self.assertEqual(conv['usage']['calls'], 1)
        sent = FakeClaude.seen[-1][2]
        self.assertEqual(len(FakeClaude.seen), n + 1)
        self.assertIn('8 岁', sent['system'])
        first = sent['messages'][0]['content']
        self.assertTrue(first[0]['text'].startswith('【图表数据】'))
        data = json.loads(first[0]['text'][len('【图表数据】'):])
        self.assertEqual((data['ticker'], data['asof'], data['engine']['all4'], len(data['bars']['rows'])), ('NVDA', '2025-05-13', True, 60))
        self.assertIn('chart_score', data['quant']); self.assertIn('notes', data)
        self.assertNotIn('positions', data)                                 # 回放历史日期时不带仓位
        self.assertEqual(first[-1]['text'], '现在该怎么看？'); self.assertIn('cache_control', first[-1])
        self.assertNotIn('tools', sent)                                     # 没开联网就不带搜索工具

        ev = self.send(id=cid, ticker='NVDA', asof='2025-05-13', model='four', text='那止损在哪？')
        self.assertIsNone(ev[0][1]['chip'])                                 # 图表没变：不再附一份
        sent = FakeClaude.seen[-1][2]
        self.assertEqual([m['role'] for m in sent['messages']], ['user', 'assistant', 'user'])      # 记忆：前面的问答都带着
        self.assertEqual(sent['messages'][1]['content'][0]['text'], FakeClaude.reply)
        self.assertEqual([b['text'] for b in sent['messages'][2]['content']], ['那止损在哪？'])
        self.assertNotIn('cache_control', sent['messages'][0]['content'][-1])                       # 缓存标记只在最后一条上

        ev = self.send(id=cid, ticker='QQQ', asof='', model='houshou', text='换一只看看', web=True)
        self.assertIn('QQQ', ev[0][1]['chip']); self.assertIn('后手', ev[0][1]['chip'])                # 换了标的和模型：带一份新的
        sent = FakeClaude.seen[-1][2]
        self.assertEqual(len(sent['messages']), 5)
        self.assertEqual(json.loads(sent['messages'][4]['content'][0]['text'][len('【图表数据】'):])['ticker'], 'QQQ')
        self.assertEqual(sent['tools'][0]['name'], 'web_search')
        self.assertEqual(len(ev[-1][1]['conv']['messages']), 6)

        got = json.loads(http(self.s.port, f'/api/chat/get?id={cid}')[1])
        self.assertEqual(len(got['conv']['messages']), 6)
        self.assertNotIn('图表数据', json.dumps(got, ensure_ascii=False))     # 原始数据不回传给页面
        self.assertTrue(os.path.exists(os.path.join(self.s.chats, cid + '.json')))
        self.assertFalse(os.path.isdir(os.path.join(ROOT, 'data', 'chats')) and cid + '.json' in os.listdir(os.path.join(ROOT, 'data', 'chats')))
        rows = json.loads(http(self.s.port, '/api/chat/list')[1])['chats']
        self.assertEqual((rows[0]['id'], rows[0]['count'], rows[0]['asks'], rows[0]['title']), (cid, 6, 3, '现在该怎么看？'))
        self.assertGreater(rows[0]['tokens'], 0)                                                          # 用量写在历史列表里，不逐条列
        self.assertTrue(json.loads(http(self.s.port, '/api/chat/delete', {'id': cid})[1])['removed'])
        self.assertFalse(json.loads(http(self.s.port, f'/api/chat/get?id={cid}')[1])['ok'])

    def test_old_cards_are_kept_but_never_shown_listed_or_sent(self):
        """以前「一键解释」放进对话的卡片：文件里留着，页面拿不到、历史里不列、提问时不发给 AI；第一句提问就是标题。"""
        card = dict(role='assistant', kind='explain', text='【一键解释】QQQ 卡片……', learn=dict(cards=[]))
        only = dict(chat.new('QQQ'), id='cccccccccccc', title='一键解释 · QQQ 11-16', messages=[card])
        mixed = dict(chat.new('QQQ'), id='dddddddddddd', title='一键解释 · QQQ 11-17', messages=[card])
        for cv in (only, mixed):
            with open(os.path.join(self.s.chats, cv['id'] + '.json'), 'w', encoding='utf-8') as f:
                json.dump(cv, f, ensure_ascii=False)
        self.assertNotIn('cccccccccccc', [x['id'] for x in json.loads(http(self.s.port, '/api/chat/list')[1])['chats']])     # 只有旧卡片：不进历史
        self.assertEqual(json.loads(http(self.s.port, '/api/chat/get?id=cccccccccccc')[1])['conv']['messages'], [])
        ev = self.send(id='dddddddddddd', ticker='QQQ', asof='', model='four', text='还缺哪一项？')
        self.assertEqual(ev[0][1]['title'], '还缺哪一项？')                                              # 第一句提问就是标题
        sent = FakeClaude.seen[-1][2]
        self.assertEqual([m['role'] for m in sent['messages']], ['user'])
        self.assertNotIn('一键解释', json.dumps(sent, ensure_ascii=False))                                # 旧卡片不发给 AI
        self.assertEqual([m['role'] for m in ev[-1][1]['conv']['messages']], ['user', 'assistant'])      # 页面也看不到
        with open(os.path.join(self.s.chats, 'dddddddddddd.json'), encoding='utf-8') as f:
            self.assertEqual(json.load(f)['messages'][0]['kind'], 'explain')                              # 文件里还在，没删
        self.assertEqual(http(self.s.port, '/api/chat/explain', dict(ticker='QQQ'))[0], 404)               # 往对话里塞卡片的接口已经拿掉

    def test_bad_requests_and_no_key(self):
        self.assertEqual(http(self.s.port, '/api/chat/send', dict(ticker='NVDA', text='  '))[0], 400)
        self.assertEqual(http(self.s.port, '/api/chat/send', dict(ticker='NVDA', text='x' * 4001))[0], 400)
        self.assertEqual(http(self.s.port, '/api/chat/send', dict(ticker='XXXX', text='hi'))[0], 404)
        code, txt = http(self.nokey.port, '/api/chat/send', dict(ticker='NVDA', text='hi'))
        r = json.loads(txt)
        self.assertEqual((code, r['ok'], r['code']), (200, False, 'disabled'))
        self.assertFalse(json.loads(http(self.s.port, '/api/chat/get?id=../../x')[1])['ok'])
        self.assertEqual(http(self.s.port, '/api/chat/send', dict(ticker='NVDA', text='hi'), {'Origin': 'https://example.com'})[0], 403)


class ReadingsByDay(unittest.TestCase):
    """AI 解读按天保存；切换模型时，另一个模型下分析过的那一份不消失。"""

    @classmethod
    def setUpClass(cls):
        cls.fake = ThreadingHTTPServer(('127.0.0.1', 0), FakeClaude)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        cls.s = Server({'ANTHROPIC_API_KEY': FAKE_KEY, 'ANTHROPIC_BASE_URL': f'http://127.0.0.1:{cls.fake.server_address[1]}'})

    @classmethod
    def tearDownClass(cls):
        cls.s.stop(); cls.fake.shutdown()

    def test_history_lists_days_and_other_model_reading_stays_visible(self):
        get = lambda path: json.loads(http(self.s.port, path)[1])
        self.assertEqual(get('/api/ai/history?ticker=QQQ')['days'], [])
        http(self.s.port, '/api/ai/analyze', {'ticker': 'QQQ', 'asof': '2016-05-16'})                    # 四证模型下分析一次
        http(self.s.port, '/api/ai/analyze', {'ticker': 'QQQ', 'asof': '2009-03-18'})
        n = len(FakeClaude.seen)
        nar = get('/api/ai/narrate?ticker=QQQ&asof=2016-05-16&model=houshou')                            # 切到后手：今天这个模型没分析过
        self.assertNotIn('polished', nar)
        self.assertEqual((nar['other']['from_other'], nar['other']['rule_model'], nar['other']['source']), (True, 'four', 'claude'))
        self.assertEqual(nar['other']['narration']['hook'], '停，先别急着抄')
        self.assertEqual(len(FakeClaude.seen), n)                                                        # 只是把保存的那份拿出来，不调用
        self.assertEqual(get('/api/state?ticker=QQQ&asof=2016-05-16')['ai_saved'], {'four': True, 'houshou': False, 'any': True, 'variants': ['']})
        http(self.s.port, '/api/ai/analyze', {'ticker': 'QQQ', 'asof': '2016-05-16', 'model': 'houshou'})
        nar = get('/api/ai/narrate?ticker=QQQ&asof=2016-05-16&model=houshou')
        self.assertIn('polished', nar); self.assertNotIn('other', nar)                                   # 这个模型有了自己的，就用自己的
        days = get('/api/ai/history?ticker=QQQ')['days']
        self.assertEqual([(d['date'], d['model']) for d in days], [('2016-05-16', 'houshou'), ('2016-05-16', 'four'), ('2009-03-18', 'four')])
        self.assertTrue(all(d['hook'] and d['created_at'] and d['versions'] >= 1 for d in days))
        self.assertEqual(get('/api/ai/history?ticker=NVDA')['days'], [])
        self.assertEqual(http(self.s.port, '/api/ai/history?ticker=XXXX')[0], 404)


if __name__ == '__main__':
    try:
        unittest.main(verbosity=1)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
