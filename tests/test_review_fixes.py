#!/usr/bin/env python3
"""独立验收（2026-11-18）提出的几处问题，各有一组测试锁住：

1. 四证没齐（state 不是 ready）时，接口和信号卡都不给建仓区、止损、目标、盈亏比。
2. 后手在三只标的的全部日线上一次都没触发过：说法要如实、要和「今天用不上」分开；合成 K 线上做多、做空各有一条能触发的路径。
3. 价位在显示的位数下分不开（低价区）时不给「条件齐」、不给盈亏比；用显示出来的价格重算的盈亏比和给出的对得上。
4. 不认识的查询参数一律 400，写明是哪个参数；不会悄悄换成后手、20 日、做多、日 K 或最新一根。
5. 复刻模型（包括四个观察模型和后手）都写明「不是原作者的代码」；四证不写这一句。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

import breakout as bo       # noqa: E402
import houshou as hs        # noqa: E402
import quant                # noqa: E402
import panel                # noqa: E402
from test_panel import Server, http                         # noqa: E402
from test_houshou import synthetic, write_csv               # noqa: E402
from test_quant2 import synthetic_short, breakdown_rows, bars_dict      # noqa: E402

TICKERS = ('SPCX', 'NVDA', 'QQQ')         # 验收时点名的三只；JOBY 2026-11-18 才加，单独测在 test_mine.py
PRICE_KEYS = ('zone', 'mid', 'stop', 't1', 't2', 'rr')


def live_data_dir():
    """三只标的现在的日线，复制一份到临时目录（测试期间数据刷新也不影响）。"""
    d = tempfile.mkdtemp(prefix='fe_review_')
    for t in TICKERS:
        shutil.copy(os.path.join(ROOT, 'data', t + '.csv'), d)
    return d


class LiveServer(unittest.TestCase):
    """跑在真实数据（的副本）上的接口测试。"""

    @classmethod
    def setUpClass(cls):
        cls.data = live_data_dir()
        cls.s = Server(dict(FE_DATA_DIR=cls.data))

    @classmethod
    def tearDownClass(cls):
        cls.s.stop()
        shutil.rmtree(cls.data, ignore_errors=True)

    def get(self, path, code=200):
        c, body = http(self.s.port, path)
        self.assertEqual(c, code, body[:300])
        return json.loads(body) if body.startswith('{') else body

    def post(self, path, body, code=200):
        c, txt = http(self.s.port, path, body)
        self.assertEqual(c, code, txt[:300])
        return json.loads(txt)


class FourNotReadyHasNoPrices(LiveServer):
    """1. 验收里复现的几天：SPCX / NVDA / QQQ 在 2026-11-13，SPCX 在 2026-11-16，四证都没齐。"""

    CASES = [(t, '2026-11-13') for t in TICKERS] + [('SPCX', '2026-11-16')]

    def test_quant_api_gives_null_prices_and_dash_cells(self):
        for t, d in self.CASES:
            q = self.get(f'/api/quant?ticker={t}&model=four&side=long&asof={d}')
            s = q['signal']
            self.assertNotEqual(s['state'], 'ready', (t, d))
            self.assertEqual({k: s[k] for k in PRICE_KEYS}, dict.fromkeys(PRICE_KEYS), (t, d))
            cells = {c['k']: c['v'] for c in q['card']['cells']}
            self.assertNotEqual(cells.pop('price'), '—')
            self.assertEqual(set(cells.values()), {'—'}, (t, d, cells))
            self.assertNotIn('four_stop', [x['id'] for x in q['lines']], (t, d))          # 止损线也不当价位给出去
            keys = [x['key'] for x in q['legend']]
            self.assertNotIn('stop', keys); self.assertNotIn('four_stop', keys)

    def test_state_card_has_no_trade_levels_but_engine_output_is_untouched(self):
        for t, d in self.CASES:
            st = self.get(f'/api/state?ticker={t}&asof={d}')
            self.assertFalse(st['all4'])
            cd = st['card']
            self.assertEqual((cd['entry_zone'], cd['stop'], cd['target'], cd['rr']), (None, None, None, None), (t, d))
            self.assertEqual([x[2] for x in cd['lines']], [None, None, None], (t, d))
            self.assertIsNotNone(st['signal']['stop'])              # 引擎原样的输出（结构位）还在：图上的自动画和「依据」要用

    def test_four_still_gives_prices_when_all_four_are_lit(self):
        q = self.get('/api/quant?ticker=NVDA&model=four&side=long&asof=2025-05-13')
        s = q['signal']
        self.assertEqual(s['state'], 'ready', s['verdict_text'])
        self.assertTrue(all(s[k] is not None for k in ('zone', 'mid', 'stop')), s)       # 这一天引擎判定前高不够当目标，所以没有第一目标和盈亏比（引擎原样）
        self.assertNotIn('—', [c['v'] for c in q['card']['cells'] if c['k'] in ('zone', 'stop')])


class HoushouNeverTriggeredOnRealData(LiveServer):
    """2. 在真实数据上：触发次数照实数（不写死 0），说法和数出来的一致，并且和「今天用不上」分开。"""

    def test_notes_match_the_counted_history(self):
        S = quant.houshou_sample()          # 进程内用的是 data/ 下的数据，和临时目录里的副本相同
        self.assertEqual({(x['ticker'], x['side']) for x in S}, {(t, s) for t in panel.TICKERS for s in ('long', 'short')})
        lib = self.get('/api/quant/models')
        hou = next(m for m in lib['models'] if m['key'] == 'houshou')
        text = ' '.join(hou['notes'])
        self.assertIn('不是原作者的代码', text)
        if sum(x['n'] for x in S) == 0:
            self.assertIn('一次都没有三项同时成立过', text)
            self.assertIn('不是一回事', text)
        else:
            self.assertIn('三项同时成立过', text)

    def test_latest_bar_says_whole_sample_and_replay_does_not(self):
        for t in ('NVDA', 'QQQ'):
            for side in ('long', 'short'):
                q = self.get(f'/api/quant?ticker={t}&model=houshou&side={side}')
                h = q['history']
                self.assertEqual(h['scope'], '全部样本')
                self.assertEqual(h['never'], h['n'] == 0, (t, side))
                old = self.get(f'/api/quant?ticker={t}&model=houshou&side={side}&asof=2015-06-01')
                self.assertEqual((old['history']['scope'], old['history']['never']), ('到这一天为止', False))      # 回放到过去：不提之后的事


class HoushouSyntheticTriggers(unittest.TestCase):
    """2. 合成 K 线：做多、做空各一条三项齐的路径，而且历史触发也数得到它（以后改坏了这里会失败）。"""

    def test_long_and_short_both_trigger_and_are_counted(self):
        for B, side in ((synthetic()[0], 'long'), (synthetic_short()[0], 'short')):
            r = hs.compute(B, side=side)
            self.assertEqual(r['verdict'], '下后手', (side, r['checks']))
            self.assertEqual([c['ok'] for c in r['checks']], [True, True, True], side)
            self.assertEqual(r['history']['n'], 1, side)
            self.assertTrue(all(r[k] is not None for k in ('zone', 'mid', 'stop', 't1', 'rr')), side)


class PricesMustBeTellableApart(unittest.TestCase):
    """3. 价位在显示的位数下分不开就不给条件齐；给出来的盈亏比，用显示的价格重算也对得上。"""

    def test_plan_check_rules(self):
        self.assertEqual(hs.plan_check(1, 105.0, 100.0, 115.0), '')
        self.assertIn('分母', hs.plan_check(1, 100.0, 100.0, 110.0))
        self.assertIn('分不开', hs.plan_check(1, 0.040012, 0.040004, 0.05))          # 四位小数下都是 0.0400
        self.assertIn('分不开', hs.plan_check(-1, -0.040004, -0.040012, -0.03))     # 做空一侧（价格取负）一样
        self.assertIn('相差', hs.plan_check(1, 2.624, 2.596, 3.5))                  # 显示 2.62 / 2.60 → 盈亏比 44 对 31
        self.assertEqual(hs.px(0.123456), 0.1235); self.assertEqual(hs.px(12.3456), 12.35)

    def test_breakdown_at_normal_prices_triggers_but_not_at_a_tenth_of_a_cent(self):
        rows, info = breakdown_rows()
        B = bars_dict(rows)
        r = bo.compute(B, side='short')
        self.assertEqual(r['verdict'], '条件齐', r['checks'])
        tiny = dict(B, o=B['o'] * 1e-5, h=B['h'] * 1e-5, l=B['l'] * 1e-5, c=B['c'] * 1e-5)        # 同一张图，价格缩到 0.001 左右
        t = bo.compute(tiny, side='short')
        self.assertEqual([c['ok'] for c in t['checks']], [True, True, True], t['checks'])          # 形态照样成立
        self.assertEqual(t['verdict'], hs.TOO_FINE)                                                   # 但价位分不开：不算条件齐
        self.assertEqual({k: t[k] for k in PRICE_KEYS}, dict.fromkeys(PRICE_KEYS))
        self.assertEqual(t['history']['n'], 0)
        self.assertIn('分不开', t['note'])

    def test_every_trigger_on_real_data_is_self_consistent(self):
        """三只标的 × 每个交易模型 × 两个方向：历史上每一次触发，用显示出来的价格重算盈亏比，和给出的相差不超过 5%（外加 0.01 的取整）。"""
        checked = 0
        for t in TICKERS:
            for m in quant.MODELS:
                if m.get('kind') == 'watch' or m['key'] == 'four':
                    continue
                for side in m['sides']:
                    q = quant.result(t, m['key'], None, side, 20, 'D', 'flat')
                    for r in q['history']['rows']:
                        mid, stop, t1, rr = r['mid'], r['stop'], r['t1'], r['rr']
                        risk = (mid - stop) if side == 'long' else (stop - mid)
                        self.assertGreater(risk, 0, (m['key'], t, side, r['date'], mid, stop))       # 入场和止损分得开
                        if rr is None:
                            continue
                        rd = ((t1 - mid) if side == 'long' else (mid - t1)) / risk
                        self.assertLessEqual(abs(rd - rr), 0.05 * rr + 0.01, (m['key'], t, side, r['date'], mid, stop, t1, rr, rd))
                        checked += 1
        self.assertGreater(checked, 100)

    def test_the_three_low_price_cases_from_the_review(self):
        """验收里点名的三条：两位小数下 mid == stop。现在 1 以下显示四位小数，要么分得开、对得上，要么不算触发。"""
        for side, day in (('short', '1999-05-04'), ('long', '1999-08-24'), ('long', '2013-05-14')):
            q = quant.result('NVDA', 'breakout', day, side, 20, 'D', 'flat')
            s = q['signal']
            if s['state'] == 'ready':
                self.assertNotEqual(s['mid'], s['stop'], (side, day))
                risk = (s['mid'] - s['stop']) if side == 'long' else (s['stop'] - s['mid'])
                rd = ((s['t1'] - s['mid']) if side == 'long' else (s['mid'] - s['t1'])) / risk
                self.assertLessEqual(abs(rd - s['rr']), 0.05 * s['rr'] + 0.01, (side, day, s))
            else:
                self.assertIsNone(s['rr'], (side, day))


class BadParamsAre400(LiveServer):
    """4. 不认识的值：400，写明参数名和可选值；不给的参数才用默认值。"""

    def test_unknown_values_on_api_quant(self):
        for qs, name in (('model=xxx', 'model'), ('model=houshou&hz=7', 'hz'), ('model=houshou&side=up', 'side'), ('model=houshou&tf=M', 'tf'),
                         ('model=houshou&tf=Q', 'tf'), ('model=houshou&asof=not-a-date', 'asof'), ('model=houshou&asof=2026-13-40', 'asof'),
                         ('model=houshou&pos=core', 'pos'), ('model=houshou&asof=1990-01-01', 'asof')):
            r = self.get('/api/quant?ticker=NVDA&' + qs, 400)
            self.assertEqual((r['ok'], r['param']), (False, name), qs)
            self.assertIn(name, r['error'])

    def test_missing_values_still_take_the_defaults(self):
        q = self.get('/api/quant?ticker=NVDA')
        self.assertEqual((q['model_key'], q['side'], q['horizon']['n'], q['tf'], q['position']['mode']), ('houshou', 'long', 20, 'D', 'auto'))
        self.assertNotIn('asof_note', q)

    def test_a_weekend_uses_the_bar_before_and_says_so(self):
        q = self.get('/api/quant?ticker=NVDA&model=four&asof=2026-11-15')         # 星期天：用星期五 11-13 那一根，并且写明
        self.assertEqual((q['asof'], q['asof_requested']), ('2026-11-13', '2026-11-15'))
        self.assertIn('2026-11-13', q['asof_note'])
        self.assertNotIn('asof_note', self.get('/api/quant?ticker=NVDA&model=four&asof=2026-11-13'))

    def test_other_endpoints_use_the_same_rules(self):
        self.assertEqual(self.get('/api/quant/scan?ticker=NVDA&side=up', 400)['param'], 'side')
        self.assertEqual(self.get('/api/quant/scan?ticker=NVDA&model=xxx', 400)['param'], 'model')
        self.assertEqual(self.get('/api/ai/narrate?ticker=NVDA&model=xxx', 400)['param'], 'model')
        self.assertEqual(self.get('/api/state?ticker=NVDA&asof=yesterday', 400)['param'], 'asof')
        self.assertEqual(self.post('/api/quant/narrate', dict(ticker='NVDA', model='nope'), 400)['param'], 'model')
        self.assertEqual(self.post('/api/quant/anchor', dict(ticker='NVDA', side='up', date=None), 400)['param'], 'side')

    def test_existing_red_lines_are_unchanged(self):
        self.assertEqual(http(self.s.port, '/api/quant?ticker=XXXX&model=four')[0], 404)
        self.assertEqual(http(self.s.port, '/../server.py')[0], 404)
        self.assertEqual(http(self.s.port, '/api/meta', None, {'Host': 'evil.example'})[0], 403)
        self.assertEqual(http(self.s.port, '/api/refresh', {}, {'Origin': 'https://example.com'})[0], 403)


class EveryModelNarrates(LiveServer):
    """「AI 分析」按钮：13 个模型都要取得到解说。以前组合名的正则只认 houshou / breakout，第二版新加的 10 个模型一点就 404。"""

    def test_every_combination_name_round_trips(self):
        import server
        for m in quant.MODELS:
            for side in ('long', 'short'):
                for hz in quant.HORIZONS:
                    for tf in ('D', 'W'):
                        v = quant.variant(m['key'], side, hz, tf)
                        self.assertEqual(server.variant_profile(v), dict(model=m['key'], side=side, horizon=hz, tf=tf), v)
        self.assertEqual(set(server.MODEL_NAMES), set(quant.MODEL))          # 分析记录里每个模型都有名字

    def test_ai_analysis_button_works_on_every_model(self):
        for m in quant.MODELS:
            side, hz = m.get('default_side', 'long'), m.get('default_hz', 20)
            r = self.get(f'/api/ai/narrate?ticker=QQQ&asof=2026-11-17&model={m["key"]}&side={side}&hz={hz}&tf=D&pos=auto')
            self.assertEqual((r['ok'], r['source']), (True, 'template'), m['key'])
            self.assertGreaterEqual(len(r['narration']['steps']), 2, m['key'])
        self.assertTrue(self.get('/api/ai/history?ticker=QQQ')['ok'])


class Disclaimers(unittest.TestCase):
    """5. 复刻的模型都写明「不是原作者的代码」；四证不是复刻的，不写这一句。"""

    def test_copied_models_say_so_and_four_does_not(self):
        import server
        lib = server.model_library()
        for m in lib['models']:
            text = ' '.join(m['notes'])
            if m['key'] == 'four':
                self.assertNotIn('不是原作者', text); self.assertIn('回测', text)
            else:
                self.assertIn('不是原作者的代码', text, m['key'])
        self.assertIn('不是原作者的代码', hs.__doc__)


if __name__ == '__main__':
    unittest.main(verbosity=1)
