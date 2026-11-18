#!/usr/bin/env python3
"""「预案价位」（2026-11-18）：清单还没齐时，AI 对话里多给一行“假如还差的那几项就在今天收盘成立，计划大约落在哪”。运行：.venv/bin/python tests/test_preplan.py

锁住这几件事：
1. 预案和条件齐时是同一套公式：同一段行情只有最后一根的量不同（缩量那一项不成立），预案的价位照条件齐时的算法算（后手、破位反抽各一条）。
2. 预案只在“等”“不追”的时候有；条件齐了、已失效、观察用的模型、用不上的时候都没有。信号卡、图上的线照旧不给价位。
3. 以后不可能再成立的那一项没成立（比如破位那根没放量），不给预案；还在走的点按“刚好到位”的价算，并写明按什么算的。
4. 核心仓：预案也不给止损和盈亏比。
5. 预案只进 AI 对话：不进 AI 解读的输入，也不进它的指纹（facts_for_ai 里没有它）。
6. 对话的系统提示写明预案怎么说：固定开头「预案（条件齐了才算数）」，不能说成现在可以进场。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

# 进程内直接调 quant 的那几组：用真实日线的副本、空的持仓目录（不读真的持仓文件）
DATA = tempfile.mkdtemp(prefix='fe_pre_data_')
for _t in ('SPCX', 'NVDA', 'QQQ', 'JOBY'):
    if os.path.exists(os.path.join(ROOT, 'data', _t + '.csv')):
        shutil.copy(os.path.join(ROOT, 'data', _t + '.csv'), DATA)
EMPTY_PF = tempfile.mkdtemp(prefix='fe_pre_pf_')
TASKS = tempfile.mkdtemp(prefix='fe_pre_tasks_')

from test_panel import Server, http, FakeClaude, FAKE_KEY       # noqa: E402  （它在导入时会清掉 FE_DATA_DIR，所以下面再设）
from test_houshou import synthetic, write_csv                   # noqa: E402
from test_quant2 import breakdown_rows, bars_dict               # noqa: E402

os.environ.update(FE_DATA_DIR=DATA, FE_PORTFOLIO_DIR=EMPTY_PF, FE_TASKS_DIR=TASKS)
import breakout as bo       # noqa: E402
import chat                 # noqa: E402
import houshou as hs        # noqa: E402
import panel                # noqa: E402
import qmodel as qm         # noqa: E402
import quant                # noqa: E402

PLAN = ('zone', 'mid', 'stop', 't1', 't2', 'rr')


def events(body):
    """The /api/chat/send stream as [(event, data)] (same reader as test_chat.py)."""
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


class Formula(unittest.TestCase):
    """同一套公式：和条件齐时给的计划逐项对得上。"""

    def test_houshou_wait_gets_the_ready_formula(self):
        B, info = synthetic(last_vol=2100.0)                    # 量放大三倍：缩量那一项不成立，前两项成立
        r = hs.compute(B)
        self.assertEqual(([c['ok'] for c in r['checks']], r['verdict']), ([True, True, False], '等'), r['checks'])
        self.assertIsNone(r['zone'])                            # 信号本身照旧不给价位
        p = r['pre']
        d_low, av = float(B['l'][-1]), r['avwap']
        self.assertEqual(p['stop'], round(d_low * 0.98, 2))     # 止损 = D × 0.98（D 点就是最后一根）
        self.assertEqual(p['t1'], 137.0)                        # 第一目标 = 第三冲高点
        self.assertEqual(p['t2'], round(d_low + 2.0 * (137.0 - 98.5), 2))      # 第二目标 = D + 2 ×（第三冲高点 − 起涨低点）
        self.assertAlmostEqual(p['zone'][0], av * 0.99, delta=0.011); self.assertAlmostEqual(p['zone'][1], av * 1.01, delta=0.011)
        self.assertEqual(p['mid'], av)
        self.assertAlmostEqual(p['rr'], (137.0 - av) / (av - p['stop']), delta=0.02)
        self.assertEqual((p['d_point'], p['d_now']), (round(d_low, 2), True))
        ready = hs.compute(synthetic()[0])                      # 同一段行情、缩量：条件齐，计划是同一套算法
        self.assertEqual(ready['verdict'], '下后手'); self.assertIsNone(ready['pre'])
        self.assertEqual((ready['stop'], ready['t1'], ready['t2']), (p['stop'], p['t1'], p['t2']))

    def test_breakout_wait_gets_exactly_the_ready_plan(self):
        ready = bo.compute(bars_dict(breakdown_rows()[0]), side='short')
        wait = bo.compute(bars_dict(breakdown_rows(last_vol=30000.0)[0]), side='short')      # 只差反抽那一段的量：价位一个都不变
        self.assertEqual((ready['verdict'], wait['verdict']), ('条件齐', '等受阻'))
        self.assertIsNone(ready['pre']); self.assertIsNone(wait['zone'])
        self.assertEqual({k: wait['pre'][k] for k in PLAN}, {k: ready[k] for k in PLAN})

    def test_generic_preplan_is_plan(self):
        P = dict(s=1)
        self.assertEqual(qm.preplan(P, 100.0, 102.0, 95.0, 110.0, 120.0), dict(zone=[100.0, 102.0], mid=101.0, stop=95.0, t1=110.0, t2=120.0, rr=1.5))
        self.assertIsNone(qm.preplan(P, 100.0, 102.0, 95.0, 101.5))                     # 第一目标没越过入场区：不算一份计划
        self.assertIsNone(qm.preplan(P, 0.0001, 0.00011, 0.00009, 0.0002))              # 价位在显示的位数下分不开
        S = dict(s=-1)                                                                  # 做空一侧：工作价格取负，出来是真实价格
        self.assertEqual(qm.preplan(S, -102.0, -100.0, -105.0, -90.0), dict(zone=[100.0, 102.0], mid=101.0, stop=105.0, t1=90.0, t2=None, rr=2.75))

    def test_four_uses_engine_levels_only(self):
        st = dict(armed=True, all4=False, levels=dict(avwap=10.0), signal=dict(stop=8.0, target=12.0, target_usable=True, rr=99.0))
        self.assertEqual(quant.four_pre(st), dict(zone=[10.0, 10.2], mid=10.1, stop=8.0, t1=12.0, t2=None, rr=0.9))    # 盈亏比按入场区中间算，不用引擎按收盘算的那个
        self.assertIsNone(quant.four_pre(dict(st, signal=dict(st['signal'], target=10.2))))   # 目标没高出入场价 2%：和引擎同一道护栏
        self.assertIsNone(quant.four_pre(dict(st, signal=dict(st['signal'], target_usable=False))))
        self.assertIsNone(quant.four_pre(dict(st, armed=False)))                              # 还没跌够：没有四证这回事
        self.assertIsNone(quant.four_pre(dict(st, all4=True)))                                # 齐了：卡片上就有真的计划


class WhenThereIsNone(unittest.TestCase):
    def test_breakout_cases(self):
        rows, info = breakdown_rows()
        r = bo.compute(bars_dict(rows), info['low'], side='short')         # 破位后还在创新低，离得太远：不追，但等它反抽的预案有
        self.assertEqual(r['verdict'], '不追')
        self.assertIsNotNone(r['pre']); self.assertEqual(r['pre']['t1'], 91.5)
        self.assertAlmostEqual(r['pre']['stop'], 100.25 * 1.02, delta=0.011)      # 反抽还没回来：按刚好到位算，止损落在破位处外 2%
        weak = [list(x) for x in rows]
        weak[info['brk']][4] = 1000.0                                      # 破位那根没放量：录屏说这样的破位不算数，以后也不会齐
        r = bo.compute(bars_dict(weak), side='short')
        self.assertFalse(r['checks'][0]['ok']); self.assertIn(r['verdict'], ('等受阻', '等反抽'))
        self.assertIsNone(r['pre'])
        fake = rows + [[97.2, 103.2, 97.0, 102.9, 1500]]                    # 假破位：已失效
        self.assertEqual(bo.compute(bars_dict(fake), side='short')['verdict'], '已失效')
        self.assertIsNone(bo.compute(bars_dict(fake), side='short')['pre'])
        self.assertIsNone(bo.compute(bars_dict(rows), info['pre'], side='short')['pre'])        # 还没破位：没有可算的

    def test_quant_wrapper(self):
        p = dict(zone=[1.0, 2.0], mid=1.5, stop=0.5, t1=3.0, t2=None, rr=1.5, basis='按 X 算')
        self.assertIsNone(quant.preplan('ready', p, False)); self.assertIsNone(quant.preplan('dead', p, False))
        self.assertIsNone(quant.preplan('watch', p, False)); self.assertIsNone(quant.preplan('wait', None, False))
        w = quant.preplan('wait', p, False)
        self.assertEqual((w['stop'], w['rr'], w['basis']), (0.5, 1.5, '按 X 算')); self.assertIn('条件齐了才算数', w['note'])
        c = quant.preplan('avoid', p, True)                                # 核心仓：不给止损和盈亏比
        self.assertEqual((c['stop'], c['rr']), (None, None)); self.assertIn('核心仓', c['stop_note'])


class LiveData(unittest.TestCase):
    """真实日线（副本）上每只标的、每个模型、两侧，最新一根和往前隔一段取几天：预案只在等 / 不追时有，价位方向对，信号卡照旧不给价位。"""

    def test_invariants(self):
        found = 0
        for t in panel.TICKERS:
            n = len(quant.bars(t, 'D')['d'])
            dates = [None] + [quant.bars(t, 'D')['d'][n - 1 - k * 23] for k in range(1, 8)]
            for m in quant.MODELS:
                for side in m['sides']:
                    for asof in (dates if m.get('kind') != 'watch' else dates[:1]):
                        q = quant.result(t, m['key'], asof, side, quant.MODEL[m['key']].get('default_hz') or 20, 'D', 'flat')
                        p, st, where = q['preplan'], q['signal']['state'], (t, q['asof'], m['key'], side)
                        if q['kind'] == 'watch' or st not in ('wait', 'avoid'):
                            self.assertIsNone(p, where)
                        if not p:
                            continue
                        found += 1
                        self.assertIsNone(q['signal']['zone'], where)
                        cells = {c['k']: c['v'] for c in q['card']['cells']}
                        self.assertEqual([cells[k] for k in ('zone', 'stop', 't1', 'rr')], ['—'] * 4, where)      # 信号卡照旧
                        self.assertFalse([x for x in q['lines'] if x['id'] in ('zone_hi', 'zone_lo', 'stop', 't1', 't2')], where)
                        lo, hi = p['zone']
                        self.assertLessEqual(lo, hi, where)
                        self.assertGreater(p['rr'], 0, where)
                        if side == 'long':
                            self.assertLess(p['stop'], lo, where); self.assertGreater(p['t1'], hi, where)
                        else:
                            self.assertGreater(p['stop'], hi, where); self.assertLess(p['t1'], lo, where)
                        self.assertIn('条件齐了才算数', p['note'])
                        self.assertNotIn('preplan', json.dumps(quant.facts_for_ai(q), ensure_ascii=False), where)    # 不进 AI 解读（也就不进指纹）
        self.assertGreater(found, 0)


class Api(unittest.TestCase):
    """服务跑在临时目录：NVDA 换成后手“等”的合成行情（缩量那一项不成立），对着本机的假 Claude。"""

    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.mkdtemp(prefix='fe_pre_api_')
        for t in ('SPCX', 'QQQ'):
            shutil.copy(os.path.join(ROOT, 'data', t + '.csv'), cls.data)
        cls.B, _ = synthetic(last_vol=2100.0)
        write_csv(os.path.join(cls.data, 'NVDA.csv'), cls.B)
        cls.pf = tempfile.mkdtemp(prefix='fe_pre_apipf_')
        cls.fake = ThreadingHTTPServer(('127.0.0.1', 0), FakeClaude)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        cls.s = Server(dict(FE_DATA_DIR=cls.data, FE_PORTFOLIO_DIR=cls.pf, ANTHROPIC_API_KEY=FAKE_KEY, ANTHROPIC_BASE_URL=f'http://127.0.0.1:{cls.fake.server_address[1]}'))
        cls.old = FakeClaude.reply

    @classmethod
    def tearDownClass(cls):
        FakeClaude.reply = cls.old
        cls.s.stop(); cls.fake.shutdown()
        shutil.rmtree(cls.data, ignore_errors=True); shutil.rmtree(cls.pf, ignore_errors=True)

    def q(self):
        code, body = http(self.s.port, '/api/quant?ticker=NVDA&model=houshou')
        self.assertEqual(code, 200, body)
        return json.loads(body)

    def test_card_stays_blank_and_chat_gets_the_preplan(self):
        d = self.q()
        self.assertEqual((d['signal']['state'], d['signal']['verdict']), ('wait', '等'))
        p = d['preplan']
        self.assertEqual(p['t1'], 137.0); self.assertIn('就是现在的 D 点', p['basis']); self.assertIn('条件齐了才算数', p['note'])
        cells = {c['k']: c['v'] for c in d['card']['cells']}
        self.assertEqual([cells[k] for k in ('zone', 'stop', 't1', 'rr')], ['—'] * 4)
        self.assertNotIn('stop', [x['id'] for x in d['lines']]); self.assertIsNone(d['overlay']['zone'])

        FakeClaude.reply = '先等。还差缩量那一项。'
        code, body = http(self.s.port, '/api/chat/send', dict(ticker='NVDA', asof='', model='houshou', text='价位在哪？'))
        self.assertEqual(code, 200, body[:200]); self.assertEqual(events(body)[-1][0], 'done')
        sent = FakeClaude.seen[-1][2]
        ctx = json.loads(sent['messages'][-1]['content'][0]['text'][len('【图表数据】'):])
        self.assertEqual(ctx['quant']['preplan'], p)                         # 对话拿到的就是这一份
        self.assertNotIn('zone', ctx['quant']['plan'])                       # 计划价位照旧是空的
        self.assertIn('预案（条件齐了才算数）', sent['system'])

        FakeClaude.seen.clear()
        http(self.s.port, '/api/ai/analyze', dict(ticker='NVDA', model='houshou', force=True))      # AI 解读：输入里没有预案
        self.assertTrue(FakeClaude.seen)
        self.assertNotIn('preplan', json.dumps(FakeClaude.seen[-1][2], ensure_ascii=False))

    def test_core_position_gets_no_stop_in_the_preplan(self):
        state = dict(asof_taipei='2026-11-16 11:10', positions=[dict(symbol='NVDA', type='stock', qty=10, avg_cost=100.0, side='safe', note='核心仓')])
        path = os.path.join(self.pf, 'portfolio_state.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)
        try:
            p = self.q()['preplan']
            self.assertEqual((p['stop'], p['rr']), (None, None)); self.assertIn('核心仓', p['stop_note'])
            self.assertEqual(p['t1'], 137.0)
        finally:
            os.unlink(path)


class Prompt(unittest.TestCase):
    def test_system_prompt_says_how_to_use_it(self):
        for must in ('quant.preplan', '预案（条件齐了才算数）', '不能把预案说成现在可以进场', '不要把它填进上面那张表'):
            self.assertIn(must, chat.SYSTEM)


def tearDownModule():
    for d in (DATA, EMPTY_PF, TASKS):
        shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
