"""「AI 量化」窗口第二版的验收测试：做多/做空、破位反抽模型、周期、持仓、周 K、任务页、量化终端。
运行：.venv/bin/python tests/test_quant2.py

1. engine.py 没动；四证没有做空一侧，按了也如实说“用不上”，不硬凑。
2. 后手的做空一侧：合成一段上下翻过来的行情，三项齐；止损 = D 点上方 2%（一分不差），成本线就是真实的锚定 VWAP。
3. 破位反抽（做空）和突破回踩（做多）：合成行情三项齐，入场区、止损、两个目标都能用手算对上。
4. 无未来函数：做空、破位反抽、周 K、三种周期，--asof D 和把数据截到 D 再跑，逐字段相同。
5. 五个输入每一个都真的改变结果：模型、方向、周期、持仓、K 线级别。
6. 保存过的 AI 解读不因为这次改动失效（文件名和指纹的规则不变）。
7. 任务页：盯盘任务新建 / 命中 / 已读 / 暂停 / 删除；新来的 K 线会被补查；分析记录记得下来、清得掉。
8. 量化终端的表和模型库接口。
9. 大白话解释覆盖新模型和做空，句子短，数字都来自面板，不给买卖建议。

用到的数据、持仓、任务目录都是临时目录，不碰 data/ 和 portfolio/。
"""
import datetime, hashlib, json, os, random, shutil, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'tests'))
import numpy as np          # noqa: E402
import breakout as bo       # noqa: E402
import chart_score          # noqa: E402
import houshou as hs        # noqa: E402
import narrate              # noqa: E402
import panel                # noqa: E402
import quant                # noqa: E402
import structure            # noqa: E402
from test_houshou import synthetic, write_csv, ENGINE_MD5      # noqa: E402
from test_panel import Server, http     # noqa: E402


def days(n):
    out, day = [], datetime.date(2020, 1, 1)
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += datetime.timedelta(days=1)
    return out


def bars_dict(rows):
    arr = np.array(rows, dtype=float)
    n = len(rows)
    return dict(d=days(n), o=arr[:, 0], h=arr[:, 1], l=arr[:, 2], c=arr[:, 3], v=arr[:, 4], src=['synthetic'] * n)


def flip(B, k=230.0):
    """Turn a series upside down around k/2 (arithmetic mirror): highs become lows. Volumes stay."""
    return dict(d=list(B['d']), o=k - B['o'], h=k - B['l'], l=k - B['h'], c=k - B['c'], v=B['v'].copy(), src=list(B.get('src') or []))


def synthetic_short(last_vol=700.0):
    """test_houshou.synthetic() 上下翻过来：高位横盘 20 根 → 三探且量递减 → 第三探天量长下影 → 两段等长的反弹弹回成本线 → 最后一根缩量向上刺破成本线又收回。
    用做多那一版的搭法（围绕 115 翻转），B 点的位置迭代几次让两段涨幅相等；最后一根按做空一侧当时的成本线摆位置。"""
    b_close, info = 119.0, {}
    for _ in range(8):
        rows = [[130, 130.4, 129.6, 130, 1000]]

        def seg(c1, n, vol, wig=0.3):
            c0 = rows[-1][3]
            for k in range(1, n + 1):
                c = c0 + (c1 - c0) * k / n
                o = rows[-1][3]
                rows.append([o, max(o, c) + wig, min(o, c) - wig, c, vol])

        seg(100.0, 14, 1000)
        for k in range(20):
            rows.append([rows[-1][3], 100.7, 99.3, 100.3 if k % 2 else 99.7, 1000])
        rows[-1][2] = 98.5
        seg(112.0, 8, 3000); info['p1'] = len(rows) - 1
        seg(105.0, 5, 1000)
        seg(122.0, 11, 2000); info['p2'] = len(rows) - 1
        seg(114.0, 5, 1000)
        seg(131.0, 11, 1500)
        rows.append([131.0, 137.0, 130.5, 131.5, 9000]); info['top'] = len(rows) - 1
        seg(b_close, 6, 2000); info['B'] = len(rows) - 1
        seg(129.0, 6, 1200); info['C'] = len(rows) - 1
        seg(116.2, 7, 2000)
        F = flip(bars_dict(rows))
        av = hs.compute(F, with_history=False, side='short')['avwap']
        prev = float(F['c'][-1])
        last = [prev, av * 1.012, min(prev, av * 0.994) - 0.3, av * 0.994, last_vol]      # 开、高、低、收：盘中涨破成本线，收盘又掉回它下面
        n = len(rows) + 1
        B = dict(d=days(n), src=['synthetic'] * n, **{k: np.append(F[k], x) for k, x in zip('ohlcv', last)})
        c_low = float(F['l'][info['C']])
        cd = (last[1] - c_low) / c_low
        want = 230.0 - 93.0 * (1 + cd) + 0.3            # B 的最高价 = A×(1+cd)：换回做多那一版的坐标
        if abs(want - b_close) < 1e-6:
            break
        b_close = want
    info['last'] = n - 1
    return B, info


def breakdown_rows(last_vol=900.0, last_close=97.2):
    """一个支撑位被踩了两次 → 放量跌破 → 缩量弹回破位处 → 最后一根冲到破位处附近又被压回去。"""
    rows = [[120, 120.4, 119.6, 120, 1000]]

    def seg(c1, n, vol, wig=0.3):
        c0 = rows[-1][3]
        for k in range(1, n + 1):
            c = c0 + (c1 - c0) * k / n
            o = rows[-1][3]
            rows.append([o, max(o, c) + wig, min(o, c) - wig, c, vol])

    seg(100.3, 10, 1000); rows[-1][2] = 100.0           # 第一次踩到 100.0
    seg(112.0, 8, 1000)
    seg(100.8, 8, 1000); rows[-1][2] = 100.5            # 第二次踩到 100.5
    seg(110.0, 7, 1000)                                 # 弹起来：第二个低点得到确认
    seg(101.5, 5, 1500)
    info = dict(pre=len(rows) - 1)
    rows.append([101.5, 101.8, 96.9, 97.2, 4000]); info['brk'] = len(rows) - 1       # 放量，收盘跌破
    seg(92.0, 4, 3000); rows[-1][2] = 91.5; info['low'] = len(rows) - 1               # 破位后最低 91.5
    seg(98.0, 5, 1000)                                  # 缩量反弹
    rows.append([98.0, 100.0, 96.8, last_close, last_vol]); info['last'] = len(rows) - 1      # 冲到 100.0 又被压回去
    return rows, info


class EngineUntouched(unittest.TestCase):
    def test_engine_md5(self):
        with open(os.path.join(ROOT, 'engine.py'), 'rb') as f:
            self.assertEqual(hashlib.md5(f.read()).hexdigest(), ENGINE_MD5)

    def test_registry_is_consistent(self):
        self.assertEqual([m['key'] for m in quant.MODELS], ['four', 'ertan', 'feidao', 'houshou', 'sanjiao', 'sanfen', 'breakout', 'bubao', 'genzhuang', 'huitou', 'yindie', 'shui', 'huiben'])
        self.assertEqual(quant.MODEL['four']['sides'], ('long',))            # 四证只有抄底一侧：规则不许改，也不替它编做空的
        self.assertEqual(set(quant.MODEL['houshou']['sides']), {'long', 'short'})
        self.assertEqual(set(quant.MODEL['breakout']['sides']), {'long', 'short'})
        self.assertEqual(set(bo.EST), set(bo.EST_NOTE)); self.assertEqual(set(hs.EST), set(hs.EST_NOTE))      # 每个估算参数都有一句说明
        self.assertEqual(set(hs.WORDS['long']), set(hs.WORDS['short'])); self.assertEqual(set(bo.WORDS['long']), set(bo.WORDS['short']))
        for m in quant.MODELS:
            self.assertIn(m['tested'], ('回测证据不足', '未回测'))
        src = open(os.path.join(ROOT, 'breakout.py'), encoding='utf-8').read()
        self.assertNotIn('import engine', src.split("if __name__")[0])        # 规则部分不引用 engine.py


class HoushouShort(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.B, cls.info = synthetic_short()

    def test_third_push_down_is_do_not_chase(self):
        r = hs.compute(self.B, self.info['top'], side='short')
        self.assertEqual((r['side'], r['phase'], r['list'], r['verdict']), ('short', '拉升中', 'chase', '不追·出货区'), r['checks'])
        self.assertEqual([c['ok'] for c in r['checks']], [True, True, True], r['checks'])
        self.assertEqual([c['name'] for c in r['checks']], ['离成本太远', '探第三次', '天量长下影'])
        self.assertLess(r['dist_pct'], -15)                         # 真实价格：在成本线下方 15% 以上
        self.assertEqual(r['pushes'][-1]['price'], 93.0)            # 第三探的最低点
        f = [p['force'] for p in r['pushes']]
        self.assertTrue(f[0] > f[1] > f[2], f)
        self.assertIn('低', r['checks'][0]['why']); self.assertIn('下影', r['checks'][2]['why'])

    def test_last_bar_is_3_of_3_on_the_short_side(self):
        B, info = self.B, self.info
        r = hs.compute(B, side='short')
        self.assertEqual((r['phase'], r['list'], r['verdict']), ('回落中', 'houshou', '下后手'), r['checks'])
        self.assertEqual([c['k'] for c in r['checks'] if c['ok']], ['B1', 'B2', 'B3'], r['checks'])
        d_high = float(B['h'][-1])
        self.assertEqual(r['abcd']['A'], dict(date=B['d'][info['top']], price=93.0))
        self.assertEqual(r['abcd']['D']['date'], B['d'][-1])
        self.assertEqual(r['stop'], round(d_high * 1.02, 2))        # 做空的止损 = D × 1.02，不是 1.0204
        self.assertEqual(r['t1'], 93.0)                             # 第一目标 = 第三探的低点
        a = B['d'].index(r['anchor']['date'])                       # 成本线就是真实价格的锚定 VWAP：这里独立再算一遍
        tp = (B['h'] + B['l'] + B['c']) / 3
        av = float((tp[a:] * B['v'][a:]).sum() / B['v'][a:].sum())
        self.assertAlmostEqual(r['avwap'], av, delta=0.006)
        self.assertAlmostEqual(r['zone'][0], av * 0.99, delta=0.011); self.assertAlmostEqual(r['zone'][1], av * 1.01, delta=0.011)
        self.assertLess(r['t1'], r['zone'][0]); self.assertGreater(r['stop'], r['zone'][1])      # 目标在下，止损在上
        self.assertAlmostEqual(r['rr'], (av - 93.0) / (r['stop'] - av), delta=0.02)
        start_high = float(B['h'][34])                              # 高位横盘最后一根（起跌高点）
        self.assertEqual(start_high, 131.5)
        self.assertEqual(r['t2'], round(d_high - 2.0 * (start_high - 93.0), 2))
        self.assertIn('涨破', r['checks'][2]['why']); self.assertIn('最高', r['checks'][2]['why'])
        self.assertEqual((r['history']['n'], r['history']['rows'][0]['outcome']), (1, 'open'))

    def test_volume_and_stop_rules_mirror_the_long_side(self):
        B2, _ = synthetic_short(last_vol=2100.0)                    # 量放大三倍：缩量那一项不成立
        r = hs.compute(B2, side='short')
        ck = {c['k']: c['ok'] for c in r['checks']}
        self.assertEqual((ck['B1'], ck['B2'], ck['B3'], r['verdict']), (True, True, False, '等'), r['checks'])
        self.assertIsNone(r['zone']); self.assertIsNone(r['t2'])
        r0 = hs.compute(self.B, side='short')
        c0 = float(self.B['c'][-1])
        nxt = dict(self.B)                                          # 下一根收在止损上面：结构作废
        nxt['d'] = self.B['d'] + days(len(self.B['d']) + 1)[-1:]
        for k, x in zip('ohlcv', [c0, r0['stop'] + 3, c0 - 0.2, r0['stop'] + 2, 2500.0]):
            nxt[k] = np.append(self.B[k], x)
        dead = hs.compute(nxt, side='short')
        self.assertEqual((dead['phase'], dead['verdict']), ('已失效', '已失效'), dead['note'])
        self.assertIn('涨破', dead['note']); self.assertIsNone(dead['zone'])

    def test_the_two_sides_are_exact_mirrors(self):
        """把一段行情上下翻过来（价格取负），做空看到的就是原来做多看到的：每个判断相同，每个价位只差一个负号。"""
        Bl, _ = synthetic()
        neg = dict(d=list(Bl['d']), o=-Bl['o'], h=-Bl['l'], l=-Bl['h'], c=-Bl['c'], v=Bl['v'])
        PL, PS = hs.prepare(Bl, 'long'), hs.prepare(neg, 'short')
        for i in range(0, len(Bl['d'])):
            a, b = hs.evaluate(PL, i), hs.evaluate(PS, i)
            self.assertEqual((a['phase'], a['verdict'], a['rr'], [c['ok'] for c in a['checks']]), (b['phase'], b['verdict'], b['rr'], [c['ok'] for c in b['checks']]), i)
            for k in ('avwap', 'mid', 'stop', 't1', 't2'):
                self.assertEqual(a[k], None if b[k] is None else -b[k], (i, k))

    def test_long_side_of_the_short_series_is_not_a_signal(self):
        r = hs.compute(self.B, side='long')
        self.assertNotEqual(r['verdict'], '下后手')


class Breakout(unittest.TestCase):
    def test_breakdown_and_retest_is_3_of_3_short(self):
        rows, info = breakdown_rows()
        B = bars_dict(rows)
        r = bo.compute(B, side='short')
        self.assertEqual((r['verdict'], r['verdict_text'], r['side_name']), ('条件齐', '破位反抽条件齐了（未回测）', '破位反抽'), r['checks'])
        self.assertEqual([c['name'] for c in r['checks']], ['有效破位', '反抽到位', '缩量受阻'])
        self.assertEqual([c['ok'] for c in r['checks']], [True, True, True], r['checks'])
        lv = r['level']
        self.assertEqual((lv['price'], lv['touches']), (100.25, 2))                 # 两次踩到 100.0 和 100.5，取平均
        self.assertEqual(r['brk']['date'], B['d'][info['brk']])
        self.assertEqual(r['extreme'], dict(date=B['d'][info['low']], price=91.5))
        self.assertEqual(r['pull'], dict(date=B['d'][-1], price=100.0))
        self.assertEqual(r['zone'], [round(100.25 * 0.985, 2), 100.25])             # 入场区：破位处到它下方 1.5%
        self.assertEqual(r['mid'], round((100.25 * 0.985 + 100.25) / 2, 2))
        self.assertAlmostEqual(r['stop'], 100.25 * 1.02, delta=0.011)               # 止损：反抽高点和破位处里较高的那个，再往上 2%
        self.assertEqual(r['t1'], 91.5)                                             # 第一目标：破位后的最低点
        box_top = max(x[1] for x in rows[10:info['brk']])                           # 第一次踩到支撑之后、破位之前的最高价
        self.assertEqual(r['box']['far'], round(box_top, 2))
        self.assertEqual(r['t2'], round(r['pull']['price'] - (box_top - r['extreme']['price']), 2))     # 第二目标：按这一跌再量一遍 1.0（从反抽点起，再走一次箱顶到破位后最低那么远）
        self.assertAlmostEqual(r['rr'], (r['mid'] - 91.5) / (r['stop'] - r['mid']), delta=0.02)
        self.assertLess(r['t2'], r['t1']); self.assertGreater(r['stop'], r['zone'][1])
        self.assertEqual((r['history']['n'], r['history']['rows'][0]['outcome']), (1, 'open'))

    def test_each_check_can_fail_on_its_own(self):
        r = bo.compute(bars_dict(breakdown_rows(last_vol=30000.0)[0]), side='short')     # 反弹这一段的均量比下跌那一段还大：不算缩量
        self.assertEqual(([c['ok'] for c in r['checks']], r['verdict']), ([True, True, False], '等受阻'), r['checks'])
        self.assertIsNone(r['zone']); self.assertIn('没缩到一半', r['checks'][2]['why'])
        r = bo.compute(bars_dict(breakdown_rows(last_close=99.6)[0]), side='short')      # 收在当根上半截：没被压回去
        self.assertEqual(r['verdict'], '等受阻'); self.assertIn('没收在', r['checks'][2]['why'])
        rows, info = breakdown_rows()
        r = bo.compute(bars_dict(rows), info['low'], side='short')                       # 破位后还在创新低：没有反抽
        self.assertEqual(([c['ok'] for c in r['checks']], r['verdict']), ([True, False, False], '不追'), r['checks'])       # 而且已经离破位处 8% 以上
        r = bo.compute(bars_dict(rows), info['brk'], side='short')
        self.assertEqual(r['verdict'], '等反抽')
        r = bo.compute(bars_dict(rows), info['pre'], side='short')                       # 还没破位
        self.assertEqual((r['verdict'], r['phase']), ('等破位', '盘整中'))
        self.assertIn('才算有效破位', r['next_needs'][0])
        fake = rows + [[97.2, 103.2, 97.0, 102.9, 1500]]                                 # 收盘回到破位处上方 2% 之外：假破位
        r = bo.compute(bars_dict(fake), side='short')
        self.assertEqual(r['verdict'], '已失效'); self.assertIn('假破位', r['note'])
        r = bo.compute(bars_dict(rows[:20]), side='short')                               # 只有一次触碰：没有这种结构
        self.assertEqual((r['verdict'], r['checks']), ('不适用', []))

    def test_breakout_and_retest_long_is_the_mirror(self):
        rows, info = breakdown_rows()
        B = flip(bars_dict(rows), 200.0)                            # 上下翻过来：压力位 99.75 被突破后回踩
        r = bo.compute(B, side='long')
        self.assertEqual((r['verdict'], r['verdict_text'], r['side_name']), ('条件齐', '突破回踩条件齐了（未回测）', '突破回踩'), r['checks'])
        self.assertEqual([c['name'] for c in r['checks']], ['有效突破', '回踩到位', '缩量企稳'])
        self.assertEqual(r['level']['price'], 99.75)
        self.assertEqual(r['zone'], [99.75, round(99.75 * 1.015, 2)])
        self.assertAlmostEqual(r['stop'], 99.75 * 0.98, delta=0.011)                # 回踩低点和突破处里较低的那个，再往下 2%
        self.assertEqual(r['t1'], 108.5)
        self.assertGreater(r['t2'], r['t1']); self.assertLess(r['stop'], r['zone'][0])
        self.assertEqual(bo.compute(B, side='short')['verdict'] == '条件齐', False)      # 同一段行情，做空一侧不是信号

    def test_stop_after_trigger_kills_the_structure(self):
        rows, _ = breakdown_rows()
        r0 = bo.compute(bars_dict(rows), side='short')
        nxt = rows + [[97.2, r0['stop'] - 0.2, 97.0, 101.9, 1500]]                       # 没到 2% 的假破位线，但收盘… 低于止损：结构还活着
        self.assertNotEqual(bo.compute(bars_dict(nxt), side='short')['verdict'], '已失效')


class NoLookahead(unittest.TestCase):
    """随机历史日期：--asof D 和把数据截到 D 再跑，逐字段相同。做空、破位反抽、周 K、三种周期都比。"""

    def test_asof_equals_truncated(self):
        rnd = random.Random(20261117)
        for t in panel.TICKERS:
            D = panel.load(t)['B']
            for tf in ('D', 'W'):
                B = panel.weekly(D) if tf == 'W' else D
                n = len(B['d'])
                if n < 60:
                    continue
                picks = sorted(rnd.sample(range(50, n), 5))
                for side in ('long', 'short'):
                    P = hs.prepare(B, side)
                    for i in picks:
                        cut = {k: B[k][:i + 1] for k in ('d', 'o', 'h', 'l', 'c', 'v')}
                        Pc = hs.prepare(cut, side)
                        self.assertEqual(hs.compute(B, i, P=P, with_history=False), hs.compute(cut, P=Pc, with_history=False), (t, tf, side, B['d'][i]))
                        self.assertEqual(bo.compute(B, i, side, P=P), bo.compute(cut, side=side, P=Pc), (t, tf, side, B['d'][i]))
                        if side == 'long':
                            for hz in (20, 60, 120):
                                self.assertEqual(chart_score.compute(P, i, hz), chart_score.compute(Pc, i, hz), (t, tf, hz))
                            a = hs.compute(B, i, P=P, with_history=False)
                            self.assertEqual(structure.lines(P, i, a, None, win=500), structure.lines(Pc, i, hs.compute(cut, P=Pc, with_history=False), None, win=500))

    def test_weekly_bars_only_contain_their_own_week(self):
        D = panel.load('QQQ')['B']
        W = panel.weekly(D)
        i = len(W['d']) - 30
        a, b = D['d'].index(W['d'][i - 1]) + 1, D['d'].index(W['d'][i]) + 1
        self.assertEqual((float(W['h'][i]), float(W['l'][i]), float(W['c'][i])), (float(D['h'][a:b].max()), float(D['l'][a:b].min()), float(D['c'][b - 1])))
        self.assertTrue(quant.week_complete('2026-11-13')); self.assertFalse(quant.week_complete('2026-11-11'))     # 周五收完了，周三没有


class Api(unittest.TestCase):
    """/api/quant 和它周围的接口，跑在合成数据上（NVDA 换成后手三项齐的那一段）。"""

    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.mkdtemp(prefix='fe_q2data_')
        shutil.copy(os.path.join(ROOT, 'data', 'QQQ.csv'), cls.data)
        cls.B, cls.info = synthetic()
        write_csv(os.path.join(cls.data, 'NVDA.csv'), cls.B)
        cls.S = bars_dict(breakdown_rows()[0])
        write_csv(os.path.join(cls.data, 'SPCX.csv'), cls.S)        # SPCX 换成破位反抽三项齐的那一段
        cls.pf = tempfile.mkdtemp(prefix='fe_q2pf_')
        cls.s = Server(dict(FE_DATA_DIR=cls.data, FE_PORTFOLIO_DIR=cls.pf))

    @classmethod
    def tearDownClass(cls):
        cls.s.stop()
        shutil.rmtree(cls.data, ignore_errors=True); shutil.rmtree(cls.pf, ignore_errors=True)

    def get(self, path, code=200):
        c, body = http(self.s.port, path)
        self.assertEqual(c, code, body[:300])
        return json.loads(body)

    def post(self, path, body, code=200):
        c, txt = http(self.s.port, path, body)
        self.assertEqual(c, code, txt[:300])
        return json.loads(txt)

    def q(self, t='NVDA', **kw):
        return self.get('/api/quant?ticker=' + t + ''.join(f'&{k}={v}' for k, v in kw.items()))

    def test_direction_buttons_change_the_result(self):
        """做多 / 做空：同一只标的、同一个模型，两侧是两份不同的结果；计划价位的上下关系跟着翻。"""
        lo, sh = self.q(model='houshou', side='long'), self.q(model='houshou', side='short')
        self.assertEqual((lo['side'], lo['side_name'], lo['signal']['state']), ('long', '做多', 'ready'))
        self.assertEqual((sh['side'], sh['side_name'], sh['side_ok']), ('short', '做空', True))
        self.assertNotEqual(lo['signal']['verdict_text'], sh['signal']['verdict_text'])
        self.assertNotEqual(lo['variant'], sh['variant']); self.assertEqual((lo['variant'], sh['variant']), ('houshou', 'houshou_short'))
        self.assertEqual(sh['card']['tags'][0], '做空'); self.assertIn('镜像规则', sh['card']['tags'])
        s = self.q('SPCX', model='breakout', side='short')
        sig = s['signal']
        self.assertEqual((sig['state'], sig['verdict_text']), ('ready', '破位反抽条件齐了（未回测）'))
        self.assertTrue(sig['t2'] < sig['t1'] < sig['zone'][0] < sig['zone'][1] < sig['stop'])     # 做空：目标在下，止损在上
        ids = [x['id'] for x in s['lines']]
        for want in ('zone_hi', 'zone_lo', 'stop', 't1', 't2'):
            self.assertIn(want, ids)
        cells = {c['k']: c for c in s['card']['cells']}
        self.assertEqual(list(cells), ['price', 'zone', 'stop', 't1', 'rr', 't2'])
        self.assertTrue(cells['stop']['sub'].startswith('+')); self.assertTrue(cells['t1']['sub'].startswith('-'))      # 距现价：止损是正的，目标是负的
        self.assertEqual(s['overlay']['kind'], 'breakout'); self.assertEqual(s['overlay']['side'], 'short')
        self.assertTrue(all(x.get('n') for x in s['lines']), [x for x in s['lines'] if not x.get('n')])
        lg = self.q('SPCX', model='breakout', side='long')
        self.assertNotEqual(lg['signal']['state'], 'ready'); self.assertEqual(lg['card']['tags'][0], '做多')
        self.assertFalse('买入' in json.dumps(s, ensure_ascii=False) or '卖出' in json.dumps(s, ensure_ascii=False))

    def test_four_has_no_short_side_and_says_so(self):
        d = self.q('QQQ', model='four', side='short')
        self.assertEqual((d['side_ok'], d['signal']['state'], d['signal']['unsupported'], d['signal']['checks']), (False, 'na', 'side', []))
        self.assertIn('只定义了做多一侧', d['card']['text'])
        self.assertTrue({'houshou', 'breakout'} <= set(d['signal']['suggest']))
        self.assertTrue(all('short' in quant.MODEL[k]['sides'] and 'D' in quant.MODEL[k]['tfs'] for k in d['signal']['suggest']))      # 只推荐真有做空规则的模型
        self.assertEqual([c['v'] for c in d['card']['cells']][1:], ['—'] * 5)      # 不给任何价位
        self.assertIsNone(d['overlay']); self.assertEqual([x for x in d['lines'] if x['group'] == 'model'], [])
        self.assertEqual(d['direction'], dict(long=True, short=False, short_note=quant.MODEL['four']['no_short']))
        ok = self.q('QQQ', model='four', side='long')
        st = self.get('/api/state?ticker=QQQ')
        self.assertEqual((ok['side_ok'], [c['ok'] for c in ok['signal']['checks']]), (True, [e['lit'] for e in st['evidence']]))    # 做多一侧照旧是引擎的结果
        wk = self.q('QQQ', model='four', tf='W')
        self.assertEqual((wk['tf_ok'], wk['signal']['unsupported']), (False, 'tf')); self.assertIn('只按日线', wk['card']['text'])

    def test_horizon_changes_score_structure_and_history_window(self):
        a, b, c = (self.q('QQQ', model='breakout', side='short', hz=n) for n in (20, 60, 120))
        self.assertEqual([x['horizon']['label'] for x in (a, b, c)], ['短线 · 20 日', '中线 · 60 日', '长线 · 120 日'])
        self.assertEqual([x['history']['hold'] for x in (a, b, c)], [20, 60, 120])
        self.assertIn('MA20', a['score']['parts'][0]['why']); self.assertIn('MA60', b['score']['parts'][0]['why']); self.assertIn('MA120', c['score']['parts'][0]['why'])
        self.assertIn('近 60 根', b['score']['parts'][1]['why'])
        self.assertEqual(a['signal']['checks'], b['signal']['checks'])             # 清单本身不随周期变：规则是同一套
        bad = self.get('/api/quant?ticker=QQQ&model=breakout&side=short&hz=7', 400)                   # 不认识的值：400，写明可选什么（以前悄悄变成 20）
        self.assertEqual((bad['param'], bad['value'], bad['allowed']), ('hz', '7', ['20', '60', '120']))
        self.assertEqual(a['card']['tags'][1], '短线 · 20 日'); self.assertEqual(b['card']['tags'][1], '中线 · 60 日')

    def test_position_modes_only_change_words(self):
        base = self.q(model='houshou')
        self.assertEqual((base['position']['mode'], base['position']['assumed'], base['position_note']), ('auto', False, ''))
        self.assertEqual([o['k'] for o in base['position']['options']], ['auto', 'flat', 'long', 'short'])
        lg, sh = self.q(model='houshou', pos='long'), self.q(model='houshou', pos='short')
        self.assertEqual((lg['position']['text'], lg['position']['assumed'], lg['position']['side']), ('持有多单', True, 'long'))
        self.assertIn('假设你有多单', lg['position_note']); self.assertIn(f"{lg['signal']['stop']:,.2f}", lg['position_note'])
        self.assertIn('反向提示', sh['position_note']); self.assertNotIn('平仓吧', sh['position_note'])
        for k in ('checks', 'zone', 'stop', 't1', 't2', 'rr', 'verdict'):
            self.assertEqual(lg['signal'][k], base['signal'][k], k); self.assertEqual(sh['signal'][k], base['signal'][k], k)
        self.assertEqual(lg['score'], base['score'])
        # 账户里是核心仓：不管假设什么，做多一侧都不给价格止损；做空一侧的止损不受影响
        path = os.path.join(self.pf, 'portfolio_state.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(dict(asof_taipei='2026-11-16 11:10', positions=[dict(symbol='NVDA', type='stock', qty=10, avg_cost=100.0, side='safe', note='核心仓')]), f, ensure_ascii=False)
        try:
            for pos in ('auto', 'flat', 'long', 'short'):
                d = self.q(model='houshou', pos=pos)
                self.assertTrue(d['position']['core']); self.assertIsNone(d['signal']['stop'], pos)
                self.assertNotIn('stop', [x['id'] for x in d['lines']], pos)
                self.assertEqual({c['k']: c['v'] for c in d['card']['cells']}['stop'], '核心仓不适用', pos)
            self.assertIn('核心仓', self.q(model='houshou', pos='auto')['position_note'])
        finally:
            os.unlink(path)

    def test_weekly_bars_run_the_models_that_support_them(self):
        d = self.q('QQQ', model='breakout', side='long', tf='W')
        W = panel.weekly(panel.load('QQQ')['B'])
        self.assertEqual((d['tf'], d['tf_ok'], d['tf_name'], d['asof'], d['timeframe']), ('W', True, '周K', W['d'][-1], '周线'))
        self.assertEqual(d['horizon']['label'], '短线 · 20 周')
        self.assertEqual(d['week']['complete'], quant.week_complete(W['d'][-1]))
        old = self.q('QQQ', model='breakout', side='long', tf='W', asof=W['d'][-40])
        self.assertEqual((old['asof'], old['is_latest'], old['week']['complete']), (W['d'][-40], False, True))
        self.assertNotEqual(d['score'], self.q('QQQ', model='breakout', side='long')['score'])      # 周 K 和日 K 是两张图

    def test_saved_readings_keep_their_names_and_fingerprints(self):
        """文件名：四证·做多·20 日·日 K 还是 T_日期.json，后手还是 T_日期_houshou.json；别的组合各有各的名字，互不覆盖。"""
        import server
        self.assertEqual([quant.variant(*a) for a in (('four',), ('houshou',), ('breakout', 'short'), ('houshou', 'short', 60, 'W'), ('four', 'long', 120))],
                         ['', 'houshou', 'breakout_short', 'houshou_short_h60_W', 'h120'])
        for v in ('', 'houshou', 'breakout_short', 'houshou_short_h60_W', 'h120', 'breakout_h120_W'):
            o = server.variant_profile(v)
            self.assertEqual(quant.variant(o['model'], o['side'], o['horizon'], o['tf']), v)
        self.assertIsNone(server.variant_profile('../../etc')); self.assertIsNone(server.variant_profile('houshou_long'))
        self.assertTrue(server._ai_cache_path('QQQ', '2026-11-13', '').endswith('QQQ_2026-11-13.json'))
        self.assertTrue(server._ai_cache_path('QQQ', '2026-11-13', 'houshou').endswith('QQQ_2026-11-13_houshou.json'))
        self.assertTrue(server._ai_cache_path('QQQ', '2026-11-13', 'four').endswith('QQQ_2026-11-13.json'))
        with self.assertRaises(KeyError):
            server._ai_cache_path('QQQ', '2026-11-13', '../x')
        # 指纹：默认组合不带方向、周期这些新字段（和改动前算法相同）；非默认组合各不相同
        fps = {k: server.ai_inputs('QQQ', '2016-05-16', *k)['fp'] for k in (('four',), ('houshou',), ('houshou', 'short'), ('breakout', 'short'), ('breakout', 'short', 60),
                                                                           ('four', 'long', 20, 'D', 'flat'))}
        self.assertEqual(len(set(fps.values())), len(fps))
        x = server.ai_inputs('QQQ', '2016-05-16', 'houshou')
        import ai_explain
        self.assertEqual(x['fp'], ai_explain.fingerprint(x['facts'], x['bars'], x['bt'], server.CFG, x['pos'], dict(model='houshou', signal=x['qf']['rule_signal'])))
        y = server.ai_inputs('QQQ', '2016-05-16', 'four')
        self.assertEqual(y['fp'], ai_explain.fingerprint(y['facts'], y['bars'], y['bt'], server.CFG, y['pos'], None))
        self.assertNotIn('t2', x['qf']['rule_signal']); self.assertIn('direction', x['qf']['setup'])

    def test_template_narration_for_every_model_and_side(self):
        for t, kw in (('SPCX', dict(model='breakout', side='short')), ('SPCX', dict(model='breakout', side='long')), ('NVDA', dict(model='houshou', side='short')),
                      ('QQQ', dict(model='four', side='short')), ('QQQ', dict(model='breakout', side='short', tf='W')), ('NVDA', dict(model='houshou', side='long', hz=60))):
            r = self.post('/api/quant/narrate', dict(ticker=t, **kw))
            self.assertEqual((r['source'], r['rule_model']), ('template', kw['model']))
            d = self.q(t, **kw)
            self.assertEqual(r['variant'], d['variant'])
            allowed = narrate.allowed_numbers(d['signal'], d['score'], d['lines'], d['asof'], d['price'], d['history'])
            self.assertEqual(narrate.bad_numbers(r['narration'], allowed), [], (t, kw, r['narration']))
            self.assertGreaterEqual(len(r['narration']['steps']), 2)
        nv = self.post('/api/quant/narrate', dict(ticker='SPCX', model='breakout', side='short'))['narration']
        self.assertEqual([s['q'] for s in nv['steps'][:3]], ['破位了吗？', '反抽到位了吗？', '缩量、受阻了吗？'])
        self.assertIn('未回测', nv['hook'] + nv['final'])
        self.assertNotIn('可以入场', json.dumps(nv, ensure_ascii=False))

    def test_tasks_watch_and_run_log(self):
        T = self.get('/api/quant/tasks')
        self.assertEqual((T['tasks'], T['unseen']), ([], 0))
        T = self.post('/api/quant/tasks', dict(op='add', ticker='SPCX', model='breakout', side='short', hz=20, tf='D'))
        task = T['tasks'][0]
        self.assertEqual((task['ticker'], task['model'], task['side'], task['horizon'], task['tf'], task['enabled']), ('SPCX', 'breakout', 'short', 20, 'D', True))
        self.assertEqual((task['last']['state'], task['checked_asof'], len(task['hits']), T['unseen']), ('ready', self.S['d'][-1], 1, 1))     # 现在就是条件齐：记一笔
        self.assertEqual(task['hits'][0]['asof'], self.S['d'][-1])
        self.assertIn('这个盯盘任务已经有了', self.post('/api/quant/tasks', dict(op='add', ticker='SPCX', model='breakout', side='short'), 400)['error'])
        self.assertIn('只定义了做多一侧', self.post('/api/quant/tasks', dict(op='add', ticker='QQQ', model='four', side='short'), 400)['error'])
        self.post('/api/quant/tasks', dict(op='add', ticker='XXXX', model='four'), 404)
        self.post('/api/quant/tasks', dict(op='nonsense'), 400)
        T = self.post('/api/quant/tasks', dict(op='seen', id=task['id']))
        self.assertEqual((T['unseen'], T['tasks'][0]['hits'][0]['seen']), (0, True))
        T = self.post('/api/quant/tasks', dict(op='pause', id=task['id']))
        self.assertFalse(T['tasks'][0]['enabled'])
        T = self.post('/api/quant/tasks', dict(op='resume', id=task['id']))
        self.assertTrue(T['tasks'][0]['enabled']); self.assertEqual(len(T['tasks'][0]['hits']), 1)      # 同一天不重复记
        T = self.post('/api/quant/tasks', dict(op='delete', id=task['id']))
        self.assertEqual(T['tasks'], [])
        self.assertFalse(os.path.exists(os.path.join(ROOT, 'data', 'quant', 'tasks.json.tmp')))
        # 分析记录
        r = self.post('/api/quant/run', dict(ticker='NVDA', model='houshou', side='long', hz=20, tf='D', pos='flat', ai='template'))['run']
        self.assertEqual((r['ticker'], r['state'], r['verdict'], r['asof'], r['ai'], r['pos']), ('NVDA', 'ready', '后手条件齐了（未回测）', self.B['d'][-1], 'template', 'flat'))
        self.post('/api/quant/run', dict(ticker='SPCX', model='breakout', side='short', asof=self.S['d'][-3]))
        R = self.get('/api/quant/runs')
        self.assertEqual((R['total'], R['runs'][0]['ticker'], R['runs'][0]['asof'], R['runs'][1]['ticker']), (2, 'SPCX', self.S['d'][-3], 'NVDA'))
        self.assertEqual(self.get('/api/quant/runs?ticker=NVDA')['total'], 1)
        self.post('/api/quant/runs/clear', {})
        self.assertEqual(self.get('/api/quant/runs')['total'], 0)

    def test_terminal_scan_and_model_library(self):
        S = self.get('/api/quant/scan')
        self.assertEqual(len(S['cells']), 3 * len(quant.MODELS) * 2)
        cell = {(c['ticker'], c['model'], c['side']): c for c in S['cells']}
        self.assertEqual((cell[('NVDA', 'houshou', 'long')]['state'], cell[('SPCX', 'breakout', 'short')]['state']), ('ready', 'ready'))
        self.assertFalse(cell[('QQQ', 'four', 'short')]['supported']); self.assertTrue(cell[('QQQ', 'four', 'long')]['supported'])
        c = cell[('SPCX', 'breakout', 'short')]
        self.assertEqual((c['ok'], c['of'], c['history']['n']), (3, 3, 1)); self.assertIsNotNone(c['zone'])
        one = self.get('/api/quant/scan?ticker=NVDA&model=houshou&side=long&hz=60')
        self.assertEqual((len(one['cells']), one['horizon'], one['cells'][0]['history']['hold']), (1, 60, 60))
        self.assertEqual(self.get('/api/quant/scan?tf=W')['tf'], 'W')
        http(self.s.port, '/api/quant/scan?ticker=XXXX')
        L = self.get('/api/quant/models')
        self.assertEqual([m['key'] for m in L['models']], ['four', 'ertan', 'feidao', 'houshou', 'sanjiao', 'sanfen', 'breakout', 'bubao', 'genzhuang', 'huitou', 'yindie', 'shui', 'huiben'])
        for m in L['models']:
            self.assertTrue(m['params'] and m['notes'] and m['what'] and m['origin'], m['key'])
            self.assertTrue(all(p['src'] in ('video', 'est') for p in m['params']))
        self.assertEqual(sum(1 for p in next(m for m in L['models'] if m['key'] == 'houshou')['params'] if p['src'] == 'video'), 4)      # 后手：录屏里说了的只有 4 个
        bo_ = next(m for m in L['models'] if m['key'] == 'breakout')
        self.assertEqual(sum(1 for p in bo_['params'] if p['src'] == 'video'), 4)                    # 破位反抽 3.1：录屏给了 4 个数（1.5 倍、前 5 根、一半、1.0）
        self.assertIn('破位反抽 3.1', bo_['origin']); self.assertEqual(bo_['name'], '破位反抽 3.1')
        self.assertEqual({m['kind'] for m in L['models'] if m['key'] in ('huitou', 'yindie', 'shui', 'huiben')}, {'watch'})
        page = http(self.s.port, '/terminal')
        self.assertEqual(page[0], 200); self.assertIn('量化终端', page[1])
        import re
        self.assertIsNone(re.search(r'<button[^>]*>[^<]*(买入|下单|卖出)', page[1]))

    def test_learn_cards_cover_the_new_models_and_the_short_side(self):
        for t, kw in (('SPCX', dict(model='breakout', side='short')), ('SPCX', dict(model='breakout', side='long')), ('NVDA', dict(model='houshou', side='short')),
                      ('QQQ', dict(model='four', side='short')), ('QQQ', dict(model='breakout', side='short', hz=60)), ('QQQ', dict(model='houshou', side='long', tf='W'))):
            qs = ''.join(f'&{k}={v}' for k, v in kw.items())
            d = self.get('/api/learn?ticker=' + t + qs)
            self.assertEqual((d['ticker'], d['model_key'], d['side']), (t, kw['model'], kw['side']))
            self.assertGreaterEqual(len(d['cards']), 12)
            ids = [c['id'] for c in d['cards']]
            for want in ('c_side', 'c_horizon', 'c_pos'):
                self.assertIn(want, ids)
            texts = [d['headline']['text'], d['headline']['sub'], d['footer']]
            for c in d['cards']:
                self.assertTrue(len(c['title']) > 3 and len(c['body']) > 20, c['id'])
                self.assertLessEqual(max(len(x) for x in c['body'].replace('？', '。').replace('；', '。').split('。')), 60, c['id'])   # 短句
                texts += [c['title'], c['body'], c['now'] or '', c['note'] or ''] + [i['name'] + i['text'] for i in c['items']]
            text = ' '.join(texts)
            for bad in ('建议买', '建议卖', '可以买入', '可以做空', '赶紧', '稳赚', '必涨', '必跌'):
                self.assertNotIn(bad, text)
            self.assertIn('不告诉你该买还是该卖', text); self.assertIn('不会替你下单', text)
            q = self.q(t, **kw)
            st = panel.state_at(t, None) if False else self.get(f'/api/state?ticker={t}&asof={q["asof"]}')
            import server
            os.environ['FE_DATA_DIR'] = self.data
            try:
                panel.clear_cache()
                allowed = narrate.allowed_numbers(st, narrate.build_facts(t, st['asof']), q['signal'], q['score'], q['lines'], q['history'], q['horizon'], q['position'],
                                                  panel.backtest_summary(), 8, 15, 5, 100)
            finally:
                os.environ.pop('FE_DATA_DIR', None); panel.clear_cache()
            self.assertEqual(narrate.bad_numbers(dict(hook=text, story='', final='', watch=[], steps=[]), allowed), [], (t, kw))
        sh = self.get('/api/learn?ticker=QQQ&model=four&side=short')
        self.assertEqual(sh['headline']['tone'], 'na'); self.assertIn('u_none', [c['id'] for c in sh['cards']])


class TasksCatchUp(unittest.TestCase):
    """新来的 K 线会被补查：建任务时还没齐，后来补进一根齐了的 K 线，任务要在那一根上记一笔。"""

    def setUp(self):
        self.data, self.tasks = tempfile.mkdtemp(prefix='fe_q2tdata_'), tempfile.mkdtemp(prefix='fe_q2tasks_')
        self.pf = tempfile.mkdtemp(prefix='fe_q2tpf_')
        os.environ.update(FE_DATA_DIR=self.data, FE_TASKS_DIR=self.tasks, FE_PORTFOLIO_DIR=self.pf)
        for t in ('QQQ', 'SPCX'):
            shutil.copy(os.path.join(ROOT, 'data', t + '.csv'), self.data)
        self.rows, _ = breakdown_rows()
        write_csv(os.path.join(self.data, 'NVDA.csv'), bars_dict(self.rows[:-1]))      # 先不放最后那一根
        panel.clear_cache(); quant._P.clear()

    def tearDown(self):
        for k in ('FE_DATA_DIR', 'FE_TASKS_DIR', 'FE_PORTFOLIO_DIR'):
            os.environ.pop(k, None)
        panel.clear_cache(); quant._P.clear()
        for d in (self.data, self.tasks, self.pf):
            shutil.rmtree(d, ignore_errors=True)

    def test_new_bar_is_checked_and_hit_recorded_once(self):
        import tasks
        task = tasks.add(dict(ticker='NVDA', model='breakout', side='short'))
        self.assertEqual((task['last']['state'], task['hits']), ('wait', []))
        self.assertEqual(tasks.listing()['unseen'], 0)
        full = bars_dict(self.rows)
        write_csv(os.path.join(self.data, 'NVDA.csv'), full)                             # 新 K 线到了
        panel.clear_cache()
        T = tasks.listing()
        self.assertEqual((T['unseen'], T['tasks'][0]['checked_asof'], T['tasks'][0]['last']['state']), (1, full['d'][-1], 'ready'))
        self.assertEqual([h['asof'] for h in T['tasks'][0]['hits']], [full['d'][-1]])
        self.assertEqual(tasks.listing(force=True)['tasks'][0]['hits'], T['tasks'][0]['hits'])      # 再查一遍不重复记
        tasks.update(None, seen=True)
        self.assertEqual(tasks.listing()['unseen'], 0)
        with open(os.path.join(self.tasks, 'tasks.json'), encoding='utf-8') as f:
            self.assertEqual(len(json.load(f)), 1)                                       # 存在临时目录里，不是 data/quant
        self.assertTrue(tasks.update(task['id'], delete=True)); self.assertEqual(tasks.listing()['tasks'], [])


if __name__ == '__main__':
    unittest.main(verbosity=1)
