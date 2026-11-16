"""盘中实时价（只用来画图，不参与任何判定）。

两个来源都是 Yahoo，不用注册账户：
  1. 推送：wss://streamer.finance.yahoo.com（yfinance 1.8 用的同一个），几秒一笔成交价；
  2. 轮询：/v8/finance/chart?range=1d&interval=1m，拿今天常规时段的开盘、最高、最低、成交量和时段起止，
     每 60 秒校正一次，推送断了时也靠它兜底。

规则：
  * 只在“常规交易时段”里的价格更新那根盘中 K 线；盘前、盘后、夜盘的价格只作为“场外价”显示。
  * 这根 K 线不写进 data/*.csv，不交给 engine.py，不影响证据、侧栏和 AI 解读。
  * 当天的日线一旦被定时任务写进 CSV，这根盘中 K 线就不再显示（以收盘入库的数据为准）。
  * 没人看页面时（10 分钟没有请求）断开推送，不在后台空跑。
"""
import asyncio
import base64
import datetime
import json
import threading
import time
import urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (four-evidence-panel)'}
WS_URL = 'wss://streamer.finance.yahoo.com/?version=2'
REST_EVERY = 60          # 秒：常规时段里多久用轮询校正一次
IDLE_STOP = 600          # 秒：多久没人问就断开推送
HEARTBEAT = 15           # 秒：重发订阅（Yahoo 需要）


def _now():
    return time.time()


def fetch_session(symbol, timeout=15):
    """Today's (or the latest) regular session from Yahoo's 1-minute chart."""
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1m'
    res = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read())['chart']
    if res.get('error'):
        raise RuntimeError(str(res['error']))
    r = res['result'][0]
    m = r['meta']
    reg = (m.get('currentTradingPeriod') or {}).get('regular') or {}
    start, end, off = reg.get('start'), reg.get('end'), reg.get('gmtoffset', m.get('gmtoffset', 0))
    ts = r.get('timestamp') or []
    q = (r.get('indicators') or {}).get('quote', [{}])[0]
    rows = [(t, q['open'][k], q['high'][k], q['low'][k], q['close'][k], q['volume'][k] or 0)
            for k, t in enumerate(ts)
            if start and start <= t < end and None not in (q['open'][k], q['high'][k], q['low'][k], q['close'][k])]
    bar = None
    if rows:
        bar = dict(o=rows[0][1], h=max(x[2] for x in rows), l=min(x[3] for x in rows), c=rows[-1][4],
                   v=sum(x[5] for x in rows))
        # meta 的当日最高、最低、成交量、现价比 1 分钟线更全
        for k, mk in (('h', 'regularMarketDayHigh'), ('l', 'regularMarketDayLow')):
            if isinstance(m.get(mk), (int, float)):
                bar[k] = max(bar[k], m[mk]) if k == 'h' else min(bar[k], m[mk])
        if isinstance(m.get('regularMarketVolume'), (int, float)):
            bar['v'] = max(bar['v'], m['regularMarketVolume'])
        if isinstance(m.get('regularMarketPrice'), (int, float)) and start <= (m.get('regularMarketTime') or 0) <= end + 120:
            bar['c'] = m['regularMarketPrice']
        bar = {k: round(float(x), 4) for k, x in bar.items()}
    date = datetime.datetime.fromtimestamp(start + off, datetime.timezone.utc).strftime('%Y-%m-%d') if start else None
    return dict(date=date, start=start, end=end, gmtoffset=off, bar=bar, prev_close=m.get('chartPreviousClose'),
                price=m.get('regularMarketPrice'), price_time=m.get('regularMarketTime'))


class LiveFeed:
    """Background thread: Yahoo push stream + 60 s REST correction. Starts on the first request, stops when idle."""

    def __init__(self, symbols, enabled=True):
        self.symbols = list(symbols)
        self.enabled = enabled
        self.lock = threading.Lock()
        self.thread = None
        self.last_request = 0.0
        self.ws_connected = False
        self.ws_error = None
        self.sessions = {}       # symbol -> fetch_session() result (+ 'fetched_at')
        self.ticks = {}          # symbol -> latest tick dict
        self.rest_error = {}

    # ---------- public ----------
    def snapshot(self, symbol, stored_last):
        """What the chart needs for `symbol`. stored_last = last date in data/<symbol>.csv."""
        if not self.enabled:
            return dict(ok=False, ticker=symbol, reason='实时价已在 config.json 里关闭（live_enabled=false）。')
        self.last_request = _now()
        self._ensure_thread()
        if symbol not in self.sessions or _now() - self.sessions[symbol].get('fetched_at', 0) > self._rest_age(symbol):
            self._refresh(symbol)
        with self.lock:
            s = dict(self.sessions.get(symbol) or {})
            tick = dict(self.ticks.get(symbol) or {})
            err = self.rest_error.get(symbol)
        if not s:
            return dict(ok=False, ticker=symbol, reason='暂时拿不到实时价：' + (err or '没有数据'))
        now = _now()
        bar = dict(s['bar']) if s.get('bar') else None
        in_regular = bool(s.get('start') and s['start'] <= now < s['end'])
        # 常规时段里的推送价更新这根 K 线；其它时段的推送价只当场外价
        outside = None
        if tick:
            t = tick['time']
            if s.get('start') and s['start'] <= t < s['end'] and bar is not None:
                bar['c'] = tick['price']
                bar['h'] = max(bar['h'], tick['price'], tick.get('day_high') or tick['price'])
                bar['l'] = min(bar['l'], tick['price'], tick.get('day_low') or tick['price'])
                if tick.get('day_volume'):
                    bar['v'] = max(bar['v'], tick['day_volume'])
            elif s.get('end') and t >= s['end'] or s.get('start') and t < s['start']:
                outside = dict(price=tick['price'], time=t, label='盘前' if s.get('start') and t < s['start'] and t > s['start'] - 6 * 3600 else '盘后 / 夜盘')
        last_price = bar['c'] if bar else s.get('price')
        last_time = max(tick.get('time', 0) if tick and in_regular else 0, s.get('price_time') or 0)
        status = 'regular' if in_regular else ('closed_pending' if bar and s.get('date') and s['date'] > stored_last else 'closed')
        show = bool(bar and s.get('date') and s['date'] > stored_last)
        prev = s.get('prev_close')
        return dict(ok=True, ticker=symbol, session_date=s.get('date'), status=status, show_candle=show, bar=bar,
                    price=last_price, price_time=last_time or None, prev_close=prev,
                    change_pct=round((last_price / prev - 1) * 100, 2) if last_price and prev else None,
                    outside=outside, stored_last=stored_last,
                    source='Yahoo 推送' if self.ws_connected and tick else 'Yahoo 1 分钟线（轮询）',
                    ws_connected=self.ws_connected, regular_start=s.get('start'), regular_end=s.get('end'),
                    fetched_at=s.get('fetched_at'))

    # ---------- internals ----------
    def _rest_age(self, symbol):
        s = self.sessions.get(symbol) or {}
        now = _now()
        if s.get('start') and s['start'] - 600 <= now < s['end'] + 600:
            return REST_EVERY
        return 15 * 60           # 休市时 15 分钟看一眼就够（主要是等下一个时段的起止时间）

    def _refresh(self, symbol):
        try:
            s = fetch_session(symbol)
            s['fetched_at'] = _now()
            with self.lock:
                self.sessions[symbol] = s
                self.rest_error.pop(symbol, None)
        except Exception as e:      # noqa: BLE001
            with self.lock:
                self.rest_error[symbol] = f'{type(e).__name__}'
                if symbol in self.sessions:
                    self.sessions[symbol]['fetched_at'] = _now()   # 别每次请求都重试

    def _ensure_thread(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=lambda: asyncio.run(self._ws_main()), name='live-feed', daemon=True)
        self.thread.start()

    def _on_message(self, raw):
        try:
            from google.protobuf.json_format import MessageToDict
            from yfinance.pricing_pb2 import PricingData
            pd = PricingData()
            pd.ParseFromString(base64.b64decode(json.loads(raw).get('message', '')))
            m = MessageToDict(pd, preserving_proto_field_name=True)
        except Exception:           # noqa: BLE001
            return
        sym, price = m.get('id'), m.get('price')
        if sym not in self.symbols or not isinstance(price, (int, float)):
            return
        tick = dict(price=price, time=int(m.get('time', 0)) / 1000 or _now(), day_high=m.get('day_high'), day_low=m.get('day_low'),
                    day_volume=int(m['day_volume']) if m.get('day_volume') else None)
        with self.lock:
            self.ticks[sym] = tick

    async def _ws_main(self):
        try:
            from websockets.asyncio.client import connect
        except ImportError:
            self.ws_error = '没有安装 websockets'
            return
        backoff = 3
        while _now() - self.last_request < IDLE_STOP:
            try:
                async with connect(WS_URL, open_timeout=15, ping_interval=20) as ws:
                    self.ws_connected, self.ws_error, backoff = True, None, 3
                    await ws.send(json.dumps({'subscribe': self.symbols}))
                    last_sub = _now()
                    while _now() - self.last_request < IDLE_STOP:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=5)
                            self._on_message(raw)
                        except asyncio.TimeoutError:
                            pass
                        if _now() - last_sub > HEARTBEAT:
                            await ws.send(json.dumps({'subscribe': self.symbols}))
                            last_sub = _now()
            except Exception as e:  # noqa: BLE001
                self.ws_error = type(e).__name__
            self.ws_connected = False
            if _now() - self.last_request >= IDLE_STOP:
                break
            await asyncio.sleep(backoff)
            backoff = min(60, backoff * 2)
        self.ws_connected = False
