#!/usr/bin/env python3
"""2026-11-18 zaki 点头的几项（“黄金不用加，其他可以”）：
- AI 对话看得到他自己的线、估值参考、挂单和点名这只的检查项（只给当前这只，不给账户总数）；
- 「我的规则」：他自己写，对话照着推演；
- 问原因、问新闻时自动联网，每天有上限；
- 忽略这一笔：记在面板自己的清单里，不改持仓文件；
- 提醒：Mac 通知可以带价格，推到手机的那条不带任何持仓数字；
- 加 JOBY（只有 Yahoo 一个来源，每根都标单一来源）。
持仓用的是这里编的一份假数据，不碰真的持仓文件；提醒不真的发（FE_NOTIFY_DRY）。"""
import csv
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from test_panel import Server, http, FakeClaude, FAKE_KEY      # noqa: E402
import panel                # noqa: E402

from http.server import ThreadingHTTPServer      # noqa: E402
import threading            # noqa: E402


def fake_state(**extra_vals):
    """编的持仓：数字都是假的，只为了覆盖每一种字段。"""
    return dict(schema='test', asof_taipei='2026-11-17T20:00:00+08:00', source='测试编的',
                account=dict(broker='测试券商', nav=12345.0, cash=6789.0, buying_power=4321.0,
                             open_orders=[dict(symbol='NVDA PUT（测试）', side='sell', qty=1, limit=9.9, status='open'),
                                          dict(symbol='QQQ', side='buy', qty=2, limit=500.0, status='open')]),
                positions=[dict(symbol='SPCX', type='stock', qty=10, avg_cost=100.0, side='safe', note='核心仓'),
                           dict(symbol='NVDA', type='stock', qty=5, avg_cost=150.0, side='risky'),
                           dict(symbol='JOBY', type='stock', qty=100, avg_cost=6.0, side='risky')],
                other_accounts=[], lines=dict(SPCX_bp_zero_est=80.0, SPCX_minus10pct_buffer=110.0, label='测试估算'),
                valuation_refs=dict(dict(SPCX_V4_base=900.0, SPCX_mos30=40.0), **extra_vals),          # 离现价远：不会碰巧被穿过
                inversion_checklist=[dict(flag=True, item='单一标的超过 1 倍净值', text='SPCX 等效 1.2 倍'),
                                     dict(flag=False, item='给亏损仓加钱', text='QQQ 两张买单')])


class InProcess(unittest.TestCase):
    """在本进程里跑：持仓目录、本机设定目录都换成临时目录。"""

    def setUp(self):
        self.pf, self.st = tempfile.mkdtemp(prefix='fe_mine_pf_'), tempfile.mkdtemp(prefix='fe_mine_st_')
        self.old = {k: os.environ.get(k) for k in ('FE_PORTFOLIO_DIR', 'FE_TASKS_DIR', 'FE_NOTIFY_DRY')}
        os.environ.update(FE_PORTFOLIO_DIR=self.pf, FE_TASKS_DIR=self.st, FE_NOTIFY_DRY='1')
        self.write(fake_state())
        import mine, portfolio, chat, tasks
        self.mine, self.portfolio, self.chat, self.tasks = mine, portfolio, chat, tasks

    def tearDown(self):
        for k, v in self.old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        shutil.rmtree(self.pf, ignore_errors=True); shutil.rmtree(self.st, ignore_errors=True)

    def write(self, st):
        with open(os.path.join(self.pf, 'portfolio_state.json'), 'w', encoding='utf-8') as f:
            json.dump(st, f, ensure_ascii=False)

    def dry(self):
        p = os.path.join(self.st, 'notify_dry.json')
        return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else []


class ChatSeesHisLines(InProcess):
    def test_only_this_ticker_and_nothing_account_wide(self):
        x = self.portfolio.chat_extras('SPCX')
        self.assertEqual([l['name'] for l in x['my_lines']], ['归零线（估算）', '−10% 缓冲线（估算）'])
        self.assertEqual([v['name'] for v in x['valuation_refs']], ['V4 Base', '30% 安全边际价'])
        self.assertEqual(x['open_orders'], [])
        self.assertEqual([c['item'] for c in x['checklist']], ['单一标的超过 1 倍净值'])              # 只要点名 SPCX 的那条
        dump = json.dumps([self.portfolio.chat_extras(t) for t in ('SPCX', 'NVDA', 'QQQ')], ensure_ascii=False)
        for secret in ('12345', '6789', '4321', 'nav', 'cash', 'buying_power', '测试券商'):
            self.assertNotIn(secret, dump)                                                              # 账户总数一样都不给
        self.assertEqual([o['symbol'] for o in self.portfolio.chat_extras('NVDA')['open_orders']], ['NVDA PUT（测试）'])
        self.assertEqual([o['symbol'] for o in self.portfolio.chat_extras('QQQ')['open_orders']], ['QQQ'])

    def test_ignored_position_leaves_ai_and_chart(self):
        key = self.mine.pos_key(dict(symbol='NVDA', type='stock'))
        self.assertIsNotNone(self.portfolio.relevant_positions('NVDA'))
        self.mine.set_ignored(key, True)
        self.assertIsNone(self.portfolio.relevant_positions('NVDA'))                                   # 不交给 AI
        ov = self.portfolio.overlays(json.load(open(os.path.join(self.pf, 'portfolio_state.json'), encoding='utf-8')))
        self.assertNotIn('NVDA', ov)                                                                     # 不画到图上
        rows = {r['symbol']: r for r in self.portfolio.payload()['positions']}
        self.assertTrue(rows['NVDA']['ignored']); self.assertFalse(rows['SPCX']['ignored'])             # 持仓页上还在，灰着
        with open(os.path.join(self.pf, 'portfolio_state.json'), encoding='utf-8') as f:
            self.assertEqual(json.load(f), fake_state())                                                 # 持仓文件一个字没改
        self.mine.set_ignored(key, False)
        self.assertIsNotNone(self.portfolio.relevant_positions('NVDA'))


class MyRules(InProcess):
    def test_template_then_his_own_words_go_into_the_prompt(self):
        text, saved = self.mine.rules()
        self.assertFalse(saved); self.assertIn('核心仓按估值失效', text); self.assertIn('（还没写）', text)
        self.mine.save_rules('## 止损\n- 收盘跌破 100 就走')
        self.assertEqual(self.mine.rules(), ('## 止损\n- 收盘跌破 100 就走\n', True))
        sysp = self.chat.system()
        self.assertTrue(sysp.startswith(self.chat.SYSTEM)); self.assertIn('【我的规则】', sysp); self.assertIn('收盘跌破 100 就走', sysp)
        with self.assertRaises(ValueError):
            self.mine.save_rules('x' * 7000)

    def test_prompt_works_through_his_rules_but_gives_no_orders(self):
        for must in ('不说“买”“卖”', '改不改由你定', '你的规则没写这种情况', '我自己的看法', 'f = p − (1 − p) ÷ b', '不要编一个'):
            self.assertIn(must, self.chat.SYSTEM)


class AutoWeb(InProcess):
    def test_why_questions_and_the_daily_cap(self):
        self.assertEqual([self.mine.wants_news(q) for q in ('为什么今天跌了？', '有什么消息吗', '止损在哪？', '黄金见底了吗')], [True, True, False, False])
        self.assertEqual([self.mine.auto_web_take(2, '2026-11-18') for _ in range(3)], [True, True, False])
        self.assertTrue(self.mine.auto_web_take(2, '2026-11-19'))                                     # 第二天重新算
        self.assertFalse(self.mine.auto_web_take(0))


class Reminders(InProcess):
    def test_nothing_goes_out_until_he_turns_it_on(self):
        self.assertEqual(self.mine.send('k0', 'mac', 'phone'), [])
        self.assertEqual(self.dry(), [])

    def test_line_crossing_mac_has_the_price_phone_has_no_numbers(self):
        B = panel.load('NVDA')['B']
        prev, last = float(B['c'][-2]), float(B['c'][-1])
        if prev == last:
            self.skipTest('最后两根收盘一样，没有穿越')
        mid = round((prev + last) / 2, 2)
        self.write(fake_state(NVDA_V4_base=mid))
        with self.assertRaises(ValueError):
            self.mine.save_notify(imessage='不是号码')
        self.mine.save_notify(mac=True, imessage='+86 138 0000 0000')
        hits = self.tasks.line_alerts()
        self.assertEqual([(h['ticker'], h['label']) for h in hits], [('NVDA', '估值参考 V4 Base')])
        sent = self.dry()
        self.assertEqual(len(sent), 2)
        mac_text, phone = sent[0]['args'][0], sent[1]['args'][0]
        self.assertIn(f'{mid:g}', mac_text)                                                               # Mac 通知只在本机：可以带价格
        self.assertNotIn(f'{mid:g}', phone); self.assertNotIn('$', phone); self.assertNotIn('V4', phone)   # 推到手机的：不带持仓数字和线名
        self.assertEqual(sent[1]['args'][1], '+86 138 0000 0000')
        self.tasks.line_alerts()
        self.assertEqual(len(self.dry()), 2)                                                             # 同一条线同一天只提醒一次


class Joby(unittest.TestCase):
    def test_joby_is_a_chart_ticker_from_its_listing_day_and_marked_single_source(self):
        path = os.path.join(ROOT, 'data', 'JOBY.csv')
        if not os.path.exists(path):
            self.skipTest('没有 JOBY 的日线')
        with open(path, newline='') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]['date'], '2021-08-11')                                                  # 合并上市那天起；之前是 SPAC 的价格
        self.assertTrue(all(r['src'].endswith('(single)') for r in rows))                              # 只有 Yahoo 一个来源，每根都标出来
        self.assertIn('JOBY', panel.TICKERS)
        import portfolio, prep_data, quant
        self.assertEqual(portfolio.chart_ticker(dict(symbol='JOBY')), 'JOBY')
        self.assertEqual((prep_data.YAHOO['JOBY'], prep_data.MIRROR['JOBY']), ('JOBY', []))
        q = quant.result('JOBY', 'four', None, 'long', 20, 'D', 'flat')
        self.assertEqual(q['ticker'], 'JOBY')


class Api(unittest.TestCase):
    """接口：规则、忽略、提醒的设定和测试、对话里的自动联网和他的线。持仓是编的，提醒不真的发。"""

    @classmethod
    def setUpClass(cls):
        cls.fake = ThreadingHTTPServer(('127.0.0.1', 0), FakeClaude)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        cls.pf = tempfile.mkdtemp(prefix='fe_mine_api_pf_')
        with open(os.path.join(cls.pf, 'portfolio_state.json'), 'w', encoding='utf-8') as f:
            json.dump(fake_state(), f, ensure_ascii=False)
        cls.s = Server({'ANTHROPIC_API_KEY': FAKE_KEY, 'ANTHROPIC_BASE_URL': f'http://127.0.0.1:{cls.fake.server_address[1]}',
                        'FE_PORTFOLIO_DIR': cls.pf, 'FE_NOTIFY_DRY': '1'})
        cls.old = FakeClaude.reply
        FakeClaude.reply = '先说结论：还没到你的线。'

    @classmethod
    def tearDownClass(cls):
        FakeClaude.reply = cls.old
        cls.s.stop(); cls.fake.shutdown()
        shutil.rmtree(cls.pf, ignore_errors=True)

    def post(self, path, body, code=200):
        c, txt = http(self.s.port, path, body)
        self.assertEqual(c, code, txt[:300])
        return json.loads(txt) if txt.startswith('{') else txt

    def get(self, path):
        return json.loads(http(self.s.port, path)[1])

    def send(self, **body):
        code, txt = http(self.s.port, '/api/chat/send', body)
        self.assertEqual(code, 200, txt[:200])
        return [json.loads(x.split('data:', 1)[1]) for x in txt.split('\n\n') if 'event: done' in x]

    def test_rules_endpoints(self):
        self.post('/api/rules', dict(text='- 跌破成本 10% 减半'))                                       # 起步模板的情形在 MyRules 里测
        r = self.get('/api/rules')
        self.assertEqual((r['ok'], r['saved'], r['text']), (True, True, '- 跌破成本 10% 减半\n'))
        self.post('/api/rules', dict(text='x' * 7000), 400)

    def test_chat_gets_his_lines_and_rules_and_looks_up_why_questions(self):
        self.post('/api/rules', dict(text='- 收盘跌破归零线就复盘'))
        n = len(FakeClaude.seen)
        done = self.send(ticker='SPCX', asof='', model='four', text='止损在哪？')
        req = FakeClaude.seen[-1][2]
        self.assertEqual(len(FakeClaude.seen), n + 1)
        self.assertIn('收盘跌破归零线就复盘', req['system'])                                              # 他的规则在系统提示里
        ctx = req['messages'][0]['content'][0]['text']
        self.assertIn('"mine"', ctx); self.assertIn('归零线（估算）', ctx); self.assertIn('30% 安全边际价', ctx)
        for secret in ('12345', '6789', 'buying_power', '测试券商'):
            self.assertNotIn(secret, ctx)
        self.assertNotIn('tools', req)                                                                   # 普通问题：不联网
        self.assertFalse(done[-1]['conv']['messages'][-1]['meta'].get('auto_web'))
        cid = done[-1]['conv']['id']
        for k in range(3):                                                                               # 问原因：自动联网，每天 3 次
            done = self.send(id=cid, ticker='SPCX', asof='', model='four', text=f'为什么今天跌了？（{k}）')
            self.assertEqual(FakeClaude.seen[-1][2]['tools'][0]['name'], 'web_search')
            self.assertTrue(done[-1]['conv']['messages'][-1]['meta']['auto_web'])
        self.send(id=cid, ticker='SPCX', asof='', model='four', text='为什么又跌了？')
        self.assertNotIn('tools', FakeClaude.seen[-1][2])                                               # 今天的 3 次用完了
        self.assertEqual(self.get('/api/notify')['auto_web_used'], 3)

    def test_ignore_and_notify_endpoints(self):
        rows = {r['symbol']: r for r in self.get('/api/portfolio')['positions']}
        self.post('/api/portfolio/ignore', dict(key=rows['JOBY']['key'], ignore=True))
        rows = {r['symbol']: r for r in self.get('/api/portfolio')['positions']}
        self.assertTrue(rows['JOBY']['ignored'])
        self.post('/api/portfolio/ignore', dict(key='', ignore=True), 400)
        self.assertEqual(self.post('/api/notify/test', {})['sent'], [])                                 # 没打开：什么都不发
        self.post('/api/notify', dict(mac=True, imessage='nope nope'), 400)
        s = self.post('/api/notify', dict(mac=True, imessage='someone@example.com'))['settings']
        self.assertEqual(s, dict(mac=True, imessage='someone@example.com'))
        self.assertEqual(self.post('/api/notify/test', {})['sent'], ['mac', 'imessage'])
        with open(os.path.join(self.s.tasks, 'notify_dry.json'), encoding='utf-8') as f:
            self.assertEqual(len(json.load(f)), 2)


if __name__ == '__main__':
    unittest.main(verbosity=1)
