"""补充指令 3（AI 量化面板 + 后手战法）的验收测试。运行：.venv/bin/python tests/test_houshou.py

1. engine.py 没动（md5 c18b24b6…）。
2. houshou.py 能跑完，连跑两次输出完全相同。
3. 无未来函数：--asof D 的结果和把数据截到 D 再跑的结果逐字段相同（规则、表盘、结构线都比）。
4. 合成数据：横盘 → 三冲且量递减 → 第三冲天量长上影 → AB=CD 回落到成本线 → 缩量刺破收回。
6. 模板解说里的每个数字都能在 /api/quant 里找到；没有 API 密钥时模板照常。
7. 手动锚点：设了之后还在，清除后回到自动。
8. 找不到买入/下单按钮；横幅常驻。核心仓不显示价格止损。

用到的数据目录、持仓目录都是临时目录，不碰 data/ 和 portfolio/。
"""
import csv, datetime, hashlib, json, os, random, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'tests'))
import numpy as np          # noqa: E402
import chart_score          # noqa: E402
import houshou as hs        # noqa: E402
import narrate              # noqa: E402
import panel                # noqa: E402
import structure            # noqa: E402
from test_panel import Server, http     # noqa: E402

ENGINE_MD5 = 'c18b24b681943f366e675c58fe721a85'


def synthetic(last_vol=700.0):
    """横盘 20 根 → 三冲且量递减 → 第三冲天量长上影 → AB=CD 回落到成本线 → 最后一根缩量刺破收回。
    返回 (B, info)。B 点的位置迭代几次，让两段跌幅相等；最后一根按当时的成本线摆位置。"""
    b_close, info = 119.0, {}
    for _ in range(6):
        bars = [[130, 130.4, 129.6, 130, 1000]]

        def seg(c1, n, vol, wig=0.3):
            c0 = bars[-1][3]
            for k in range(1, n + 1):
                c = c0 + (c1 - c0) * k / n
                o = bars[-1][3]
                bars.append([o, max(o, c) + wig, min(o, c) - wig, c, vol])

        seg(100.0, 14, 1000)                              # 之前的下跌
        for k in range(20):                               # 横盘 20 根
            c = 100.3 if k % 2 else 99.7
            bars.append([bars[-1][3], 100.7, 99.3, c, 1000])
        bars[-1][2] = 98.5                                # 横盘最后一根是起涨低点
        seg(112.0, 8, 3000)                               # 第一冲，量最大
        info['p1'] = len(bars) - 1
        seg(105.0, 5, 1000)
        seg(122.0, 11, 2000)                              # 第二冲
        info['p2'] = len(bars) - 1
        seg(114.0, 5, 1000)
        seg(131.0, 11, 1500)                              # 第三冲，量最小
        bars.append([131.0, 137.0, 130.5, 131.5, 9000])   # 最高那根：天量 + 长上影
        info['top'] = len(bars) - 1
        seg(b_close, 6, 2000)                             # A → B
        info['B'] = len(bars) - 1
        seg(129.0, 6, 1200)                               # B → C
        info['C'] = len(bars) - 1
        seg(116.2, 7, 2000)                               # C → D 的前半段
        n = len(bars)
        days, day = [], datetime.date(2020, 1, 1)
        while len(days) < n + 1:
            if day.weekday() < 5:
                days.append(day.isoformat())
            day += datetime.timedelta(days=1)
        arr = np.array(bars, dtype=float)
        tmp = dict(d=days[:n], o=arr[:, 0], h=arr[:, 1], l=arr[:, 2], c=arr[:, 3], v=arr[:, 4])
        r = hs.compute(tmp, with_history=False)           # 这时候的成本线
        av = r['avwap']
        last = [bars[-1][3], bars[-1][3] + 0.3, av * 0.988, av * 1.006, last_vol]   # 刺破成本线又收回
        arr = np.vstack([arr, last])
        B = dict(d=days[:n + 1], o=arr[:, 0], h=arr[:, 1], l=arr[:, 2], c=arr[:, 3], v=arr[:, 4], src=['synthetic'] * (n + 1))
        c_high = arr[info['C'], 1]
        cd = (c_high - last[2]) / c_high
        want = 137.0 * (1 - cd) + 0.3                     # B 的最低价 = A×(1−cd)，收盘再高 0.3
        if abs(want - b_close) < 1e-6:
            break
        b_close = want
    info['last'] = len(B['d']) - 1
    return B, info


def write_csv(path, B):
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['date', 'open', 'high', 'low', 'close', 'volume', 'src'])
        for k in range(len(B['d'])):
            w.writerow([B['d'][k]] + [repr(float(B[x][k])) for x in 'ohlcv'] + ['synthetic'])


class EngineUntouched(unittest.TestCase):
    def test_engine_md5(self):
        with open(os.path.join(ROOT, 'engine.py'), 'rb') as f:
            self.assertEqual(hashlib.md5(f.read()).hexdigest(), ENGINE_MD5)

    def test_estimates_are_in_one_place_and_named(self):
        self.assertEqual(hs.VERSION, 'houshou-0.2')
        self.assertEqual(hs.VIDEO, dict(far=0.15, abcd_tol=0.15, dry=0.5, stop=0.02))
        self.assertEqual(set(hs.EST), set(hs.EST_NOTE))             # 每个估算参数都有一句说明，界面上照着列
        src = open(os.path.join(ROOT, 'houshou.py'), encoding='utf-8').read()
        self.assertNotIn('涨停', src.split('"""')[2])                 # 不做涨停相关逻辑（说明文字里提到不算）
        self.assertNotIn('import engine', src.split('def main')[0])  # 规则部分不引用 engine.py


class Synthetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.B, cls.info = synthetic()

    def test_third_push_bar_is_3_of_3_do_not_chase(self):
        r = hs.compute(self.B, self.info['top'])
        self.assertEqual((r['phase'], r['list'], r['verdict']), ('拉升中', 'chase', '不追·出货区'), r['checks'])
        self.assertEqual([c['ok'] for c in r['checks']], [True, True, True], r['checks'])
        self.assertEqual(len(r['pushes']), 3)
        f = [p['force'] for p in r['pushes']]
        self.assertTrue(f[0] > f[1] > f[2], f)
        self.assertTrue(r['pushes'][2]['pending'])                  # 第三冲当根还没确认，也算
        self.assertEqual(r['anchor']['by'], 'auto')
        self.assertIsNotNone(r['base'])                             # 找到了横盘
        self.assertGreater(r['dist_pct'], 15)

    def test_last_bar_is_3_of_3_houshou(self):
        B, info = self.B, self.info
        r = hs.compute(B)
        self.assertEqual((r['phase'], r['list'], r['verdict']), ('回落中', 'houshou', '下后手'), r['checks'])
        self.assertEqual([c['k'] for c in r['checks'] if c['ok']], ['B1', 'B2', 'B3'], r['checks'])
        d_low = float(B['l'][-1])
        self.assertEqual(r['abcd']['A'], dict(date=B['d'][info['top']], price=137.0))
        self.assertEqual(r['abcd']['D']['date'], B['d'][-1])
        self.assertEqual(r['stop'], round(d_low * 0.98, 2))         # 止损 = D × 0.98
        self.assertEqual(r['t1'], 137.0)                            # 目标 = 第三冲高点
        self.assertAlmostEqual(r['zone'][0], r['avwap'] * 0.99, delta=0.011); self.assertAlmostEqual(r['zone'][1], r['avwap'] * 1.01, delta=0.011)   # 建仓区 = 成本线 ±1%
        self.assertAlmostEqual(r['rr'], round((137.0 - r['avwap']) / (r['avwap'] - r['stop']), 2), delta=0.02)
        start_low = float(B['l'][19 + 15])                         # 横盘最后一根（起涨低点）的最低价 98.5
        self.assertEqual(start_low, 98.5)
        self.assertEqual(r['t2'], round(d_low + 2.0 * (137.0 - start_low), 2))      # 第二目标【估算】= D + 2 ×（第三冲高点 − 起涨低点）
        self.assertIn('估算', r['t2_note']); self.assertEqual(r['side'], 'long')
        self.assertEqual(r['history']['n'], 1)
        self.assertEqual((r['history']['rows'][0]['date'], r['history']['rows'][0]['outcome']), (B['d'][-1], 'open'))
        self.assertIn('未做对照检验', r['history']['note'])

    def test_three_times_the_volume_breaks_b3(self):
        B2, _ = synthetic(last_vol=2100.0)
        r = hs.compute(B2)
        ck = {c['k']: c['ok'] for c in r['checks']}
        self.assertEqual((ck['B1'], ck['B2'], ck['B3'], r['verdict']), (True, True, False, '等'), r['checks'])
        self.assertIsNone(r['zone']); self.assertIsNone(r['stop'])
        self.assertTrue(any('成交量' in x for x in r['next_needs']), r['next_needs'])

    def test_structure_dies_after_a_close_below_the_stop(self):
        B, r0 = dict(self.B), hs.compute(self.B)
        nxt = [float(B['c'][-1]), float(B['c'][-1]) + 0.2, r0['stop'] - 3, r0['stop'] - 2, 2500.0]      # 下一根收在止损下面
        B['d'] = list(B['d']) + ['2021-01-04']
        for k, x in zip('ohlcv', nxt):
            B[k] = np.append(B[k], x)
        r = hs.compute(B)
        self.assertEqual((r['phase'], r['verdict']), ('已失效', '已失效'), r['note'])
        self.assertEqual(r['history']['rows'][0]['outcome'], 'stop')

    def test_manual_anchor_overrides_and_is_ignored_before_its_date(self):
        B, info = self.B, self.info
        day = B['d'][20]
        r = hs.compute(B, anchor_date=day)
        self.assertEqual(r['anchor'], dict(date=day, by='manual', note=''))
        self.assertEqual(hs.compute(B, 10, anchor_date=day)['anchor'], hs.compute(B, 10)['anchor'])     # 回放到锚点之前：不用它

    def test_no_lookahead_on_synthetic(self):
        P = hs.prepare(self.B)
        for i in range(30, len(self.B['d'])):
            cut = {k: self.B[k][:i + 1] for k in ('d', 'o', 'h', 'l', 'c', 'v')}
            self.assertEqual(hs.compute(self.B, i, P=P), hs.compute(cut), self.B['d'][i])


class NoLookahead(unittest.TestCase):
    """验收 3：随机 30 个历史日期，--asof D 和把数据截到 D 再跑，逐字段相同。规则、表盘、结构线都比。"""

    def test_asof_equals_truncated(self):
        rnd = random.Random(20261116)
        for t in panel.TICKERS:
            B = panel.load(t)['B']
            P = hs.prepare(B)
            n = len(B['d'])
            for i in sorted(rnd.sample(range(min(80, n - 1), n), 10)):
                cut = panel.truncate(B, i)
                Pc = hs.prepare(cut)
                a, b = hs.compute(B, i, P=P), hs.compute(cut, P=Pc)
                self.assertEqual(a, b, (t, B['d'][i]))
                self.assertEqual(chart_score.compute(P, i), chart_score.compute(Pc, i), (t, B['d'][i]))
                self.assertEqual(structure.lines(P, i, a), structure.lines(Pc, i, b), (t, B['d'][i]))


class CommandLine(unittest.TestCase):
    def run_cli(self, *args):
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'houshou.py')] + list(args), capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_runs_and_is_deterministic(self):
        a, b = self.run_cli('NVDA', 'QQQ', 'SPCX'), self.run_cli('NVDA', 'QQQ', 'SPCX')
        self.assertEqual(a, b)
        for t in ('NVDA', 'QQQ', 'SPCX'):
            self.assertIn(f'【后手检查】{t}', a)
        self.assertIn('未回测', a)
        js = json.loads(self.run_cli('NVDA', '--json', '--asof', '2025-01-06'))
        self.assertEqual((js['NVDA']['asof'], js['NVDA']['phase'], js['NVDA']['model']), ('2025-01-06', '回落中', 'houshou-0.2'))
        self.assertEqual(json.loads(self.run_cli('QQQI', '--json'))['QQQI']['asof'], json.loads(self.run_cli('QQQ', '--json'))['QQQ']['asof'])   # 代理


class Score(unittest.TestCase):
    def test_formula_and_bands(self):
        self.assertEqual([chart_score.label(x) for x in (-100, -60, -59, -27, -21, -20, 0, 20, 21, 59, 60)],
                         ['偏空', '偏空', '中性偏空', '中性偏空', '中性偏空', '中性', '中性', '中性', '中性偏多', '中性偏多', '偏多'])
        B = panel.load('NVDA')['B']
        P = hs.prepare(B)
        i = len(B['d']) - 1
        s = chart_score.compute(P, i)
        self.assertEqual([p['name'] for p in s['parts']], ['趋势', '动量', '量能', '波动', '结构'])
        self.assertTrue(all(-100 <= p['v'] <= 100 for p in s['parts']))
        self.assertEqual(s['total'], chart_score.half_up(sum(p['v'] for p in s['parts']) / 5))
        c = B['c']
        chg = c[i] / c[i - 20] - 1
        self.assertEqual(s['parts'][1]['v'], chart_score.half_up(max(-1, min(1, chg / 0.2)) * 100))
        self.assertIn('估算', s['note'])


class Api(unittest.TestCase):
    """用临时数据目录起服务：NVDA 换成合成数据（最后一根是 3/3），其余两只是真数据的副本。"""

    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.mkdtemp(prefix='fe_hsdata_')
        for t in ('SPCX', 'QQQ'):
            shutil.copy(os.path.join(ROOT, 'data', t + '.csv'), cls.data)
        cls.B, cls.info = synthetic()
        write_csv(os.path.join(cls.data, 'NVDA.csv'), cls.B)
        cls.pf = tempfile.mkdtemp(prefix='fe_hspf_')
        cls.s = Server(dict(FE_DATA_DIR=cls.data, FE_PORTFOLIO_DIR=cls.pf))

    @classmethod
    def tearDownClass(cls):
        cls.s.stop()
        shutil.rmtree(cls.data, ignore_errors=True); shutil.rmtree(cls.pf, ignore_errors=True)

    def q(self, t='NVDA', model='houshou', asof=''):
        code, body = http(self.s.port, f'/api/quant?ticker={t}&model={model}&asof={asof}')
        self.assertEqual(code, 200, body)
        return json.loads(body)

    def test_shape_and_three_of_three(self):
        d = self.q()
        self.assertEqual((d['model'], d['model_key'], d['asof']), ('houshou-0.2', 'houshou', self.B['d'][-1]))
        self.assertEqual([s['name'] for s in d['steps']], ['识别图表结构', '计算规则信号', '在图上划线', 'AI 深度解读'])
        self.assertRegex(d['steps'][0]['note'], r'^\d+ 条结构线$')
        self.assertEqual(d['steps'][2]['note'], f'共 {len(d["lines"])} 条，逐条画出')      # 条数是真的，不写死
        s = d['signal']
        self.assertEqual((s['phase'], s['verdict'], s['verdict_text']), ('回落中', '下后手', '后手条件齐了（未回测）'))
        self.assertEqual([c['k'] for c in s['checks']], ['B1', 'B2', 'B3'])
        ids = [x['id'] for x in d['lines']]
        for want in ('zone_hi', 'zone_lo', 'stop', 't1', 't2', 'fib_0.5', 'fib_0.618'):
            self.assertIn(want, ids)
        self.assertEqual(next(x for x in d['lines'] if x['id'] == 'stop')['label'], '止损（手动止损）')
        cells = {c['k']: c for c in d['card']['cells']}
        self.assertEqual(list(cells), ['price', 'zone', 'stop', 't1', 'rr', 't2'])
        self.assertEqual(cells['t2']['v'], f"{s['t2']:,.2f}"); self.assertIn('估算', cells['t2']['sub'])     # 第二目标有数，而且写明是估算
        self.assertIn('手动止损', cells['stop']['sub'])
        self.assertIn('未回测', d['card']['footer'])
        self.assertFalse('买入' in json.dumps(d, ensure_ascii=False))
        self.assertEqual(d['overlay']['target'], 137.0)
        self.assertEqual(len(d['overlay']['avwap']['v']), len(d['overlay']['avwap']['d']))
        self.assertEqual(sorted(x['n'] for x in d['legend']), list(range(1, len(d['legend']) + 1)))
        self.assertTrue(all(x.get('n') for x in d['lines']), [x for x in d['lines'] if not x.get('n')])      # 每条线都有图例编号
        self.assertIn('尚未回测', d['banner'])
        self.assertEqual(len(d['score']['parts']), 5)
        self.assertEqual(d['direction'], dict(long=True, short=True, short_note=''))      # 后手两侧都有规则
        self.assertEqual((d['side'], d['side_ok'], d['tf'], d['horizon']['n'], d['signal']['state']), ('long', True, 'D', 20, 'ready'))

    def test_replay_recomputes_everything(self):
        top = self.q(asof=self.B['d'][self.info['top']])
        self.assertEqual((top['signal']['phase'], top['signal']['verdict'], top['signal']['list']), ('拉升中', '不追·出货区', 'chase'))
        self.assertIsNone(top['signal']['zone'])
        self.assertNotIn('stop', [x['id'] for x in top['lines']])
        self.assertEqual(top['history']['n'], 0)                    # 那一天还看不到后面的触发

    def test_four_model_uses_engine_result(self):
        d = self.q('QQQ', 'four')
        st = json.loads(http(self.s.port, '/api/state?ticker=QQQ')[1])
        self.assertEqual(d['model_key'], 'four')
        self.assertEqual([c['ok'] for c in d['signal']['checks']], [e['lit'] for e in st['evidence']])
        self.assertEqual(d['signal']['verdict'], st['conclusion']['title'])
        self.assertIsNone(d['overlay'])
        self.assertEqual(self.q('QQQ', 'houshou')['score'], d['score'])     # 表盘和选哪个模型无关
        self.assertEqual(http(self.s.port, '/api/quant?ticker=XXXX')[0], 404)

    def test_template_numbers_all_come_from_the_panel(self):
        for t, asof in (('NVDA', ''), ('NVDA', self.B['d'][self.info['top']]), ('QQQ', ''), ('QQQ', '2016-05-16'), ('SPCX', '')):
            code, body = http(self.s.port, '/api/quant/narrate', dict(ticker=t, model='houshou', asof=asof))
            self.assertEqual(code, 200, body)
            r = json.loads(body)
            self.assertEqual((r['source'], r['rule_model']), ('template', 'houshou'))       # 没有密钥：模板照常
            d = self.q(t, asof=asof)
            allowed = narrate.allowed_numbers(d['signal'], d['score'], d['lines'], d['asof'], d['price'], d['history'])
            self.assertEqual(narrate.bad_numbers(r['narration'], allowed), [], (t, asof, r['narration']))
            self.assertGreaterEqual(len(r['narration']['steps']), 2)
        nv = json.loads(http(self.s.port, '/api/quant/narrate', dict(ticker='NVDA', model='houshou'))[1])['narration']
        self.assertEqual([s['q'] for s in nv['steps'][:3]], ['回到成本线没有？', '两段跌得一样长吗？', '缩量刺破收回了吗？'])
        self.assertEqual([s['sticker'] for s in nv['steps'][:3]], ['到位了', '到位了', '有人接'])
        self.assertIn('未回测', nv['final'])
        top = json.loads(http(self.s.port, '/api/quant/narrate', dict(ticker='NVDA', model='houshou', asof=self.B['d'][self.info['top']]))[1])['narration']
        self.assertEqual([s['q'] for s in top['steps'][:3]], ['离成本多远？', '第几冲、兵还跟不跟？', '天量是抢筹还是出货？'])
        self.assertEqual([s['sticker'] for s in top['steps'][:3]], ['不追！', '不追！', '出货区'])
        code, body = http(self.s.port, '/api/quant/narrate', dict(ticker='NVDA', model='houshou', claude=True))
        r = json.loads(body)
        self.assertEqual((r['source'], r['code']), ('template', 'disabled'))                # 要 Claude 但没有密钥：退回模板并说明

    def test_manual_anchor_persists_and_clears(self):
        auto = self.q()['signal']['anchor']
        day = self.B['d'][22]
        code, body = http(self.s.port, '/api/quant/anchor', dict(ticker='NVDA', date=day))
        self.assertEqual((code, json.loads(body)['anchor']), (200, day))
        with open(os.path.join(self.data, 'houshou_anchor.json'), encoding='utf-8') as f:
            self.assertEqual(json.load(f), {'NVDA': day})           # 按代码存日期
        self.assertFalse(os.path.exists(os.path.join(ROOT, 'data', 'houshou_anchor.json.tmp')))
        got = self.q()['signal']['anchor']
        self.assertEqual((got['date'], got['by']), (day, 'manual'))
        self.assertIn('你手动定的', self.q()['legend'][0]['text'])
        self.assertEqual(http(self.s.port, '/api/quant/anchor', dict(ticker='NVDA', date='2020-01-04'))[0], 400)   # 不是交易日
        self.assertEqual(self.q()['signal']['anchor']['date'], day)
        http(self.s.port, '/api/quant/anchor', dict(ticker='NVDA', date=None))
        self.assertEqual(self.q()['signal']['anchor'], auto)        # 清除后回到自动
        with open(os.path.join(self.data, 'houshou_anchor.json'), encoding='utf-8') as f:
            self.assertEqual(json.load(f), {})

    def test_core_position_never_gets_the_price_stop(self):
        p0 = self.q()['position']
        self.assertEqual((p0['text'], p0['held'], p0['core'], p0['mode'], p0['assumed']), ('没有持仓数据', False, False, 'auto', False))
        state = dict(asof_taipei='2026-11-16 11:10', positions=[dict(symbol='NVDA', type='stock', qty=10, avg_cost=100.0, side='safe', note='核心仓')])
        path = os.path.join(self.pf, 'portfolio_state.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)
        try:
            d = self.q()
            self.assertTrue(d['position']['core']); self.assertIn('核心仓', d['position']['text'])
            self.assertIsNone(d['signal']['stop']); self.assertEqual(d['signal']['stop_note'], '核心仓不适用')
            self.assertNotIn('stop', [x['id'] for x in d['lines']])
            self.assertIsNone(d['overlay']['stop'])
            cells = {c['k']: c for c in d['card']['cells']}
            self.assertEqual((cells['stop']['v'], cells['rr']['v']), ('核心仓不适用', '—'))
            self.assertNotIn('stop', [x['key'] for x in d['legend']])
            state['positions'][0].update(side='risky', note='')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False)
            d = self.q()
            self.assertFalse(d['position']['core']); self.assertEqual(d['position']['text'], '持仓 10 股')
            self.assertIsNotNone(d['signal']['stop'])
        finally:
            os.unlink(path)

    def test_page_has_banner_and_no_order_buttons(self):
        import re
        page = http(self.s.port, '/')[1]
        self.assertIn('四证：回测证据不足 ｜ 后手战法、破位反抽：尚未回测 ｜ 仅观察，不构成买卖依据', page)
        self.assertIsNone(re.search(r'<button[^>]*>[^<]*(买入|下单|卖出)', page))
        js = http(self.s.port, '/static/quant.js')[1]
        self.assertNotIn('买入', js); self.assertNotIn('下单', js)
        self.assertIn('手动止损', json.dumps(self.q()['lines'], ensure_ascii=False))     # 止损线旁写着“手动止损”
        for bid in ('qLong', 'qShort'):                                # 做多、做空两个按钮都能点
            tag = re.search(r'<button id="%s"[^>]*>' % bid, page).group(0)
            self.assertNotIn('disabled', tag)


if __name__ == '__main__':
    unittest.main(verbosity=1)
