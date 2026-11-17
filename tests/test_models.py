"""公共指标和录屏里各个「战法」模型的测试。运行：.venv/bin/python tests/test_models.py

1. 指标（RSI、KDJ、布林带、ATR、成交量分布、回归趋势）：数值对得上手算；都是因果的（后面加 K 线不改前面的值）。
2. 做空就是把图上下翻过来：指标在翻过来的价格上自动变成镜像（RSI 30 ↔ 70，下轨 ↔ 上轨）。
3. 每个模型：无未来函数；做多做空互为镜像；结果的形状完整；状态只在规定的几种里；条件没齐不给价位；
   触发后收盘越过止损就作废；每个估算参数都有一句说明；规则部分不引用 engine.py。
"""
import importlib, json, os, random, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'tests'))
import numpy as np          # noqa: E402
import houshou as hs        # noqa: E402
import indicators as ind    # noqa: E402
import panel                # noqa: E402
import qmodel as qm         # noqa: E402
import quant                # noqa: E402


def neg(B):
    """The same bars upside down (prices negated, highs and lows swapped)."""
    return dict(d=list(B['d']), o=-np.asarray(B['o'], float), h=-np.asarray(B['l'], float), l=-np.asarray(B['h'], float), c=-np.asarray(B['c'], float), v=np.asarray(B['v'], float))


class Indicators(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.B = panel.load('QQQ')['B']

    def test_rsi_kdj_boll_atr_values(self):
        c, h, l = self.B['c'][-300:], self.B['h'][-300:], self.B['l'][-300:]
        r = ind.rsi(c)
        d = np.diff(c)
        u = a = None
        want = [50.0]
        for x in d:                                             # 手算：SMA(X, 14, 1) 递推
            u = max(x, 0.0) if u is None else (max(x, 0.0) + 13 * u) / 14
            a = abs(x) if a is None else (abs(x) + 13 * a) / 14
            want.append(u / a * 100 if a > 0 else 50.0)
        self.assertTrue(np.allclose(r, want)); self.assertTrue((r >= 0).all() and (r <= 100).all())
        self.assertTrue(np.allclose(ind.rsi(np.arange(1.0, 40.0))[1:], 100.0)); self.assertTrue(np.allclose(ind.rsi(np.arange(40.0, 1.0, -1))[1:], 0.0))
        k, dd, j = ind.kdj(h, l, c)
        i = 150
        rsv = (c[i] - l[i - 8:i + 1].min()) / (h[i - 8:i + 1].max() - l[i - 8:i + 1].min()) * 100
        self.assertAlmostEqual(k[i], (rsv + 2 * k[i - 1]) / 3); self.assertAlmostEqual(dd[i], (k[i] + 2 * dd[i - 1]) / 3); self.assertAlmostEqual(j[i], 3 * k[i] - 2 * dd[i])
        mid, up, low = ind.boll(c)
        self.assertTrue(np.isnan(mid[18])); self.assertAlmostEqual(mid[i], c[i - 19:i + 1].mean())
        self.assertAlmostEqual(up[i] - mid[i], 2 * c[i - 19:i + 1].std()); self.assertAlmostEqual(mid[i] - low[i], up[i] - mid[i])
        P = hs.prepare(self.B)
        self.assertTrue(np.allclose(ind.atr(self.B['h'], self.B['l'], self.B['c'])[13:], P['atr'][13:]))      # 和模型门槛用的是同一个 ATR

    def test_indicators_are_causal(self):
        c, h, l, v = (self.B[k][-400:] for k in 'chlv')
        for n in (120, 250, 399):
            self.assertTrue(np.allclose(ind.rsi(c[:n + 1]), ind.rsi(c)[:n + 1]))
            self.assertTrue(np.allclose(ind.kdj(h[:n + 1], l[:n + 1], c[:n + 1])[2], ind.kdj(h, l, c)[2][:n + 1]))
            self.assertTrue(np.allclose(ind.boll(c[:n + 1])[1][19:], ind.boll(c)[1][19:n + 1]))

    def test_volume_profile_and_regression(self):
        h, l, v = np.array([10.0, 12.0, 11.0, 11.5]), np.array([9.0, 10.0, 10.5, 10.5]), np.array([100.0, 300.0, 50.0, 250.0])
        vp = ind.volume_profile(h, l, v, 0, 3, bins=6)
        self.assertAlmostEqual(sum(vp['vol']), 700.0); self.assertEqual((vp['lo'], vp['hi']), (9.0, 12.0)); self.assertAlmostEqual(vp['step'], 0.5)
        self.assertEqual(len(vp['vol']), 6)
        self.assertTrue(10.5 <= vp['poc'] <= 11.5, vp)                      # 10.5 ~ 11.5 这一带四根里有三根都在，量最集中
        one = ind.volume_profile(np.array([5.0, 5.0]), np.array([5.0, 5.0]), np.array([10.0, 20.0]), 0, 1)
        self.assertEqual((one['vol'], one['poc']), ([30.0], 5.0))
        y = 3.0 + 0.5 * np.arange(30.0)
        ch = ind.linreg_channel(y, 0, 29)
        self.assertAlmostEqual(ch['slope'], 0.5); self.assertAlmostEqual(ch['start'], 3.0); self.assertAlmostEqual(ch['end'], 17.5); self.assertAlmostEqual(ch['sd'], 0.0, places=6)
        self.assertAlmostEqual(ind.fib_retrace(100.0, 200.0, 0.382), 161.8); self.assertAlmostEqual(ind.fib_retrace(200.0, 100.0, 0.5), 150.0)
        self.assertAlmostEqual(ind.fib_extend(100.0, 150.0, 130.0, 1.0), 180.0); self.assertAlmostEqual(ind.fib_extend(150.0, 100.0, 120.0, 1.618), 120.0 - 80.9)

    def test_short_side_sees_mirrored_indicators(self):
        B = {k: self.B[k][-500:] for k in ('d', 'o', 'h', 'l', 'c', 'v')}
        PL, PS = hs.prepare(B, 'long'), hs.prepare(B, 'short')
        a, b = qm.ix(PL), qm.ix(PS)
        self.assertTrue(np.allclose(a['rsi'], 100 - b['rsi'])); self.assertTrue(np.allclose(a['k'], 100 - b['k'])); self.assertTrue(np.allclose(a['j'], 100 - b['j']))
        self.assertTrue(np.allclose(a['up'][19:], -b['low'][19:])); self.assertTrue(np.allclose(a['low'][19:], -b['up'][19:])); self.assertTrue(np.allclose(a['mid'][19:], -b['mid'][19:]))
        self.assertTrue(np.allclose(a['hist'], -b['hist'])); self.assertTrue(np.allclose(qm.ma(PL, 20)[19:], -qm.ma(PS, 20)[19:]))
        self.assertEqual([(i, k) for i, _, k in qm.pivots(PL, 499)][1:], [(i, -k) for i, _, k in qm.pivots(PS, 499)][1:])     # 摆动点是同一批，高低互换（最开头那一个可能差一步）
        self.assertEqual(qm.span(PS, -5.0, -3.0), (3.0, 5.0)); self.assertEqual(qm.R(PS, -7.123), 7.12)
        self.assertEqual(json.loads(json.dumps(qm.sh_profile(PS, 100, 160)))['d1'], B['d'][100])
        vl, vs = qm.sh_profile(PL, 100, 160), qm.sh_profile(PS, 100, 160)
        self.assertEqual((vl['lo'], vl['poc'], vl['vol']), (vs['lo'], vs['poc'], vs['vol']))       # 成交量分布画出来是同一张图


GENERIC = [m for m in quant.MODELS if m.get('mod')]


class EveryModel(unittest.TestCase):
    """Rules shared by every model built on qmodel.py. A new model file is covered as soon as it is in quant.MODELS."""

    def test_registry_entries_are_complete(self):
        for m in quant.MODELS:
            for k in ('key', 'name', 'version', 'sides', 'tfs', 'tested', 'origin', 'what', 'checks'):
                self.assertTrue(m.get(k), (m.get('key'), k))
        for m in GENERIC:
            mod = m['mod']
            self.assertEqual((mod.KEY, mod.NAME, mod.VERSION), (m['key'], m['name'], m['version']))
            self.assertEqual(set(getattr(mod, 'EST', {})), set(getattr(mod, 'EST_NOTE', {})), m['key'])        # 每个估算参数都有一句说明
            self.assertEqual(set(getattr(mod, 'VIDEO', {})), set(getattr(mod, 'VIDEO_NOTE', {})), m['key'])    # 录屏里说了的数也各有一句
            src = open(os.path.join(ROOT, mod.__name__ + '.py'), encoding='utf-8').read()
            self.assertNotIn('import engine', src, m['key'])
            code = src.split('"""', 2)[2] if src.lstrip().startswith('"""') else src     # 文件开头的说明里会照抄录屏原话，只查代码部分
            self.assertNotIn('买入', code); self.assertNotIn('下单', code)

    def test_shape_states_and_plan(self):
        rnd = random.Random(7)
        for m in GENERIC:
            mod = m['mod']
            for t in panel.TICKERS:
                B = panel.load(t)['B']
                n = len(B['d'])
                for side in m['sides']:
                    P = hs.prepare(B, side)
                    for i in sorted(rnd.sample(range(min(60, n - 1), n), min(40, n - 60))) + [n - 1]:
                        r = qm.settle(P, mod.KEY, mod.core, i)
                        tag = (m['key'], t, side, B['d'][i])
                        self.assertIn(r['state'], qm.STATES, tag)
                        self.assertTrue(r['verdict'] and r.get('verdict_text') and r['phase'], tag)
                        for c in r['checks']:
                            self.assertTrue(c['k'] and c['name'] and c['why'] and c['ask'] and isinstance(c['ok'], bool), tag)
                        if r['state'] == 'ready':
                            self.assertTrue(all(c['ok'] for c in r['checks']), tag)
                            self.assertTrue(r['zone'] and r['stop'] is not None and r['t1'] is not None, tag)
                            lo, hi = r['zone']
                            self.assertLessEqual(lo, hi, tag)
                            if side == 'long':
                                self.assertLess(r['stop'], lo, tag); self.assertGreater(r['t1'], lo, tag)
                            else:
                                self.assertGreater(r['stop'], hi, tag); self.assertLess(r['t1'], hi, tag)
                            if r['t2'] is not None:
                                self.assertTrue(r['t2'] > r['t1'] if side == 'long' else r['t2'] < r['t1'], tag)
                        elif r['state'] not in ('risk', 'watch'):
                            self.assertIsNone(r['zone'], tag)            # 条件没齐，不给价位
                        json.dumps({k: v for k, v in r.items() if not k.startswith('_')}, allow_nan=False)
                        for s in r['shapes']:
                            self.assertIn(s['t'], ('line', 'band', 'seg', 'hl', 'box', 'badge', 'dot', 'text', 'vbar', 'profile'), tag)

    def test_no_lookahead(self):
        rnd = random.Random(11)
        for m in GENERIC:
            mod = m['mod']
            for t in panel.TICKERS:
                D = panel.load(t)['B']
                for tf in m['tfs']:
                    B = panel.weekly(D) if tf == 'W' else D
                    n = len(B['d'])
                    if n < 80:
                        continue
                    for side in m['sides']:
                        P = hs.prepare(B, side)
                        for i in sorted(rnd.sample(range(60, n), 6)):
                            cut = {k: B[k][:i + 1] for k in ('d', 'o', 'h', 'l', 'c', 'v')}
                            a, b = qm.compute(mod, B, i, side, P=P, with_history=False), qm.compute(mod, cut, None, side, with_history=False)
                            self.assertEqual(json.dumps(a, ensure_ascii=False, sort_keys=True), json.dumps(b, ensure_ascii=False, sort_keys=True), (m['key'], t, tf, side, B['d'][i]))

    def test_sides_are_mirrors(self):
        """做空看翻过来的图 = 做多看原图：判断相同，价位只差一个负号。"""
        for m in GENERIC:
            if set(m['sides']) != {'long', 'short'} or getattr(m['mod'], 'ASYMMETRIC', False):      # 跟庄3号两侧本来就是两套规则（录屏如此）
                continue
            mod = m['mod']
            B = panel.load('QQQ')['B']
            B = {k: B[k][-900:] for k in ('d', 'o', 'h', 'l', 'c', 'v')}
            PL, PS = hs.prepare(B, 'long'), hs.prepare(neg(B), 'short')
            for i in range(200, 900, 7):
                a, b = qm.settle(PL, mod.KEY, mod.core, i), qm.settle(PS, mod.KEY, mod.core, i)
                self.assertEqual((a['state'], a['verdict'], [c['ok'] for c in a['checks']], a['rr']), (b['state'], b['verdict'], [c['ok'] for c in b['checks']], b['rr']), (m['key'], i))
                for k in ('mid', 'stop', 't1', 't2'):
                    self.assertEqual(a[k], None if b[k] is None else -b[k], (m['key'], i, k))

    def test_panel_result_for_every_combination(self):
        for m in GENERIC:
            for t in panel.TICKERS:
                for side in ('long', 'short'):
                    for tf in ('D', 'W'):
                        q = quant.result(t, m['key'], None, side, 20, tf)
                        self.assertEqual((q['model_key'], q['side'], q['tf']), (m['key'], side, tf))
                        self.assertEqual(q['side_ok'], side in m['sides']); self.assertEqual(q['tf_ok'], tf in m['tfs'])
                        self.assertEqual(len(q['card']['cells']), 0 if m.get('kind') == 'watch' else 6)          # 观察用的模型没有六格（录屏如此）
                        self.assertEqual(q['side_name'], ({'long': '上行', 'short': '下行'} if m.get('kind') == 'watch' else {'long': '做多', 'short': '做空'})[side])
                        self.assertTrue(all(x.get('n') for x in q['lines']), (m['key'], [x['id'] for x in q['lines'] if not x.get('n')]))
                        tm = quant.template(q)
                        self.assertTrue(tm['hook'] and tm['final'] and len(tm['steps']) >= 2, m['key'])
                        json.dumps(q, ensure_ascii=False, allow_nan=False); json.dumps(quant.facts_for_ai(q), ensure_ascii=False, allow_nan=False)
                        text = json.dumps(q, ensure_ascii=False)
                        self.assertFalse('买入' in text or '卖出' in text or '可以入场' in text, (m['key'], t, side))


class RecordedPanels(unittest.TestCase):
    """录屏面板上读到的东西，和这里的实现对得上。"""

    def test_gauge_rows_reproduce_the_recorded_numbers(self):
        import chart_score as cs
        self.assertEqual([cs.half_up(max(-100, min(100, (r - 1) * cs.EST['vol_k']))) for r in (0.62, 0.78, 0.80, 3.43)], [-23, -13, -12, 100])      # 量能
        self.assertEqual([-cs.half_up(max(0, min(100, (a - 2) * cs.EST['atr_k']))) for a in (3.33, 4.95, 5.39, 6.06)], [-27, -59, -68, -81])     # 波动
        self.assertEqual([cs.half_up(max(-100, min(100, x * cs.EST['mom_k']))) for x in (-14.0, 44.2)], [-84, 100])                               # 动量
        self.assertEqual(cs.EST['struct'], 40)                                                                                                   # 结构：高点抬高、低点抬高 = +40
        P = hs.prepare(panel.load('QQQ')['B'])
        sc = cs.compute(P, P['n'] - 1)
        self.assertIn('涨日量为跌日的', sc['parts'][2]['why'])

    def test_names_kinds_and_directions_match_the_recordings(self):
        want = {'breakout': ('破位反抽 3.1', 'trade', 'short'), 'bubao': ('不爆仓 3 号', 'trade', 'short'), 'sanfen': ('三份法 测试07', 'trade', 'long'),
                'genzhuang': ('跟庄3号', 'trade', 'short'), 'feidao': ('不接飞刀 v1.3', 'trade', 'long'), 'sanjiao': ('不追半山腰 v2.1', 'trade', 'long'),
                'ertan': ('等二探 v2.1', 'trade', 'long'), 'huitou': ('等回头', 'watch', 'long'), 'yindie': ('阴跌雷达', 'watch', 'short'), 'shui': ('睡得着', 'watch', 'long')}
        for k, (name, kind, side) in want.items():
            m = quant.MODEL[k]
            self.assertEqual((m['name'], m['kind'], m['default_side']), (name, kind, side), k)

    def test_every_model_does_something_in_history(self):
        """检测器不是死代码：交易模型在三只票的历史上至少触发过一次；观察模型的结论会变。"""
        for m in GENERIC:
            mod, trig, states = m['mod'], 0, set()
            for t in panel.TICKERS:
                for side in m['sides']:
                    P = quant.prepared(t, side, 'D')[1]
                    trig += qm.history(P, mod.KEY, mod.core, P['n'] - 1, 20)['n']
                    states |= {qm.settle(P, mod.KEY, mod.core, j)['state'] for j in range(max(60, P['n'] - 1500), P['n'], 5)}
            if m['kind'] == 'watch':
                self.assertGreaterEqual(len(states - {'na'}), 2, (m['key'], states))
            else:
                self.assertGreater(trig, 0, m['key'])

    def test_plain_language_cards_for_every_model(self):
        import learn
        for m in GENERIC:
            for side in m['sides']:
                d = learn.build('QQQ', m['key'], None, side)
                self.assertGreaterEqual(len(d['cards']), 10, m['key'])
                text = ' '.join([d['headline']['text'], d['headline']['sub']] + [c['title'] + c['body'] + (c['now'] or '') + (c['note'] or '') for c in d['cards']])
                for c in d['cards']:
                    self.assertLessEqual(max(len(x) for x in c['body'].replace('？', '。').replace('；', '。').split('。')), 60, (m['key'], side, c['id']))
                for bad in ('建议买', '建议卖', '可以买入', '可以做空', '赶紧', '稳赚', '必涨', '必跌'):
                    self.assertNotIn(bad, text, (m['key'], side))


if __name__ == '__main__':
    unittest.main(verbosity=1)
