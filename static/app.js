/* 四要素观察面板前端。
   这里不做任何规则判定：四项证据、高低点、扇线、成本线、止损、目标都来自后端 /api/state（engine.py 的输出）。
   前端只负责画图、画线、回放时截断显示。 */
(() => {
'use strict';
const LW = window.LightweightCharts;
const $ = (s, p = document) => p.querySelector(s);
const $$ = (s, p = document) => [...p.querySelectorAll(s)];
const cssv = k => getComputedStyle(document.documentElement).getPropertyValue(k).trim();
const C = {};
['bg', 'line', 'fg', 'mut', 'up', 'down', 'acc', 'hazard', 'fan', 'vwap', 'stop', 'target', 'lowvol', 'warn'].forEach(k => { C[k] = cssv('--' + k); });
const FAN = ['0.382', '0.5', '0.618'];
const RIGHT_PAD = 28;

const store = {
  get(k, d) { try { const v = localStorage.getItem('fe.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('fe.' + k, JSON.stringify(v)); } catch (e) { /* 存不了就算了 */ } },
};

const S = {
  meta: null, ticker: 'SPCX', bars: null, idx: null, state: null, asof: 0, replayOn: false,
  auto: store.get('auto', true), tool: 'cursor', ind: Object.assign({ vol: true, macd: true, marks: true, pf: false, pfval: false, live: true }, store.get('ind', {})), view: 'chart', pf: null, tf: 'D', live: null,
  sideOpen: store.get('side', true), evFold: store.get('evFold', false),
  drawings: [], selected: -1, pending: null, cur: null, hover: null, rev: 0, seq: 0, avwap: {}, plines: [], reveal: null, flash: null,
};
let chart, candle, liveCandle, ind = { series: [] }, D = {}, ov, ctx, OV = { w: 0, h: 0, dpr: 1 }, lastSig = '';
const rgba = (hex, a) => 'rgba(' + [1, 3, 5].map(k => parseInt(hex.slice(k, k + 2), 16)).join(',') + ',' + a + ')';

// ---------- helpers ----------
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
function fmtP(x) {
  if (x == null || !isFinite(x)) return '—';
  const a = Math.abs(x), d = a >= 1 ? 2 : a >= 0.1 ? 3 : 4;
  return x.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}
const fmtPct = (x, d = 2) => (x == null || !isFinite(x)) ? '—' : (x > 0 ? '+' : x < 0 ? '−' : '') + Math.abs(x).toFixed(d) + '%';
function fmtVol(v) {
  if (v == null) return '—';
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '万';
  return String(Math.round(v));
}
async function api(path, body) {
  const opt = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  let j = null;
  try { j = await r.json(); } catch (e) { /* 非 JSON */ }
  if (!j) throw new Error('服务端没有返回数据（' + r.status + '）');
  j._status = r.status;
  return j;
}
let toastTimer = 0;
function toast(msg, err) {
  const t = $('#toast');
  t.textContent = msg; t.className = err ? 'err' : ''; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, err ? 7000 : 3200);
}
function modal(title, html) { $('#modalTitle').textContent = title; $('#modalBody').innerHTML = html; $('#modal').hidden = false; }
function indexAt(date) {
  const d = S.bars.d; let lo = 0, hi = d.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (d[m] <= date) lo = m + 1; else hi = m; }
  return clamp(lo - 1, 1, d.length - 1);
}
const lastIdx = () => S.bars.d.length - 1;
const asofDate = () => S.bars.d[S.asof];
const stateFresh = () => S.state && S.state.ticker === S.ticker && S.bars && S.state.asof === asofDate();
const isDaily = () => S.tf !== 'W';
const TF_NAME = { D: '日线', W: '周线' };

// ---------- chart ----------
function buildChart() {
  chart = LW.createChart($('#chart'), {
    autoSize: true,
    layout: { background: { type: 'solid', color: C.bg }, textColor: '#9aa3b5', fontSize: 11, attributionLogo: false,
      panes: { separatorColor: C.line, separatorHoverColor: '#3a4152', enableResize: true } },
    grid: { vertLines: { color: '#1b202b' }, horzLines: { color: '#1b202b' } },
    crosshair: { mode: LW.CrosshairMode.Normal },
    rightPriceScale: { borderColor: C.line },
    timeScale: { borderColor: C.line, rightOffset: RIGHT_PAD, minBarSpacing: 0.4, barSpacing: 7 },
    localization: { locale: 'zh-CN', dateFormat: 'yyyy-MM-dd' },
  });
  candle = chart.addSeries(LW.CandlestickSeries, {
    upColor: C.up, downColor: C.down, borderUpColor: C.up, borderDownColor: C.down, wickUpColor: C.up, wickDownColor: C.down,
    priceLineColor: '#7a8396', autoscaleInfoProvider: scaleProvider,
  }, 0);
  // 盘中（未收盘）K 线：单独一层、半透明，不进 S.bars，不交给引擎
  liveCandle = chart.addSeries(LW.CandlestickSeries, {
    upColor: rgba(C.up, 0.28), downColor: rgba(C.down, 0.28), borderUpColor: rgba(C.up, 0.75), borderDownColor: rgba(C.down, 0.75),
    wickUpColor: rgba(C.up, 0.55), wickDownColor: rgba(C.down, 0.55), priceLineStyle: 2, priceLineColor: rgba('#e6e8ee', 0.6),
    title: '盘中', lastValueVisible: true, priceLineVisible: true,
  }, 0);
  chart.subscribeCrosshairMove(p => {
    const i = (p && p.point && p.logical != null) ? Math.round(p.logical) : null;
    S.hover = (i != null && i >= 0 && i <= S.asof) ? i : null;
    renderLegend();
  });
  chart.subscribeClick(p => {
    if (S.tool !== 'cursor' || !p || !p.point) return;
    if (p.point.y > OV.h) return;
    const k = hitTest(p.point.x, p.point.y);
    if (k !== S.selected) { S.selected = k; S.rev++; }
  });
}

function scaleProvider(original) {
  const res = original();
  if (!res || !res.priceRange) return res;
  let lo = res.priceRange.minValue, hi = res.priceRange.maxValue;
  const mn = lo, mx = hi;
  if (S.auto && stateFresh()) {
    const lv = S.state.levels;
    [lv.stop, S.state.signal.target_usable ? lv.target : null, lv.avwap].forEach(v => {
      if (v != null && v > mn * 0.75 && v < mx * 1.25) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    });
  }
  pfLines().forEach(l => { lo = Math.min(lo, l.price); hi = Math.max(hi, l.price); });
  return { priceRange: { minValue: lo, maxValue: hi }, margins: res.margins };
}
/* 持仓叠加线：只是显示，四要素证据的判定不看它们。 */
function pfLines() {
  if (!S.pf || !S.pf.ok || !S.pf.overlays) return [];
  const o = S.pf.overlays[S.ticker];
  return o ? (S.ind.pf ? o.lines : []).concat(S.ind.pfval ? o.valuation : []) : [];
}
const PF_STYLE = { cost: ['#e6e8ee', [8, 4]], strike: ['#fb923c', [4, 3]], zero: ['#ef4444', [10, 3]], entry: ['#e6e8ee', [8, 4]], tp: ['#4ade80', [4, 3]], valuation: ['#94a3b8', [2, 3]] };
function drawPortfolioLines() {
  const placed = [];        // 标签压在自己的线上；几条线挨得近时往右错开，不上下挪
  ctx.font = '11px -apple-system,"PingFang SC",sans-serif';
  pfLines().forEach((l, k) => {
    const y = Y(l.price), st = PF_STYLE[l.kind] || PF_STYLE.cost; if (y == null) return;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(OV.w, y); ctx.strokeStyle = st[0]; ctx.lineWidth = 1.2; ctx.setLineDash(st[1]); ctx.stroke(); ctx.setLineDash([]);
    const text = l.label + ' ' + fmtP(l.price) + (k === 0 && S.pf.stale ? '（持仓数据已过期）' : ''), w = ctx.measureText(text).width + 8;
    let x = 8;
    for (let n = 0; n < 6 && placed.some(r => Math.abs(r.y - y) < 16 && x < r.x + r.w + 10 && x + w + 10 > r.x); n++) x = Math.max.apply(null, placed.filter(r => Math.abs(r.y - y) < 16).map(r => r.x + r.w)) + 14;
    placed.push({ x, y, w });
    ctx.fillStyle = '#12151cee'; ctx.fillRect(x, y - 8, w, 16);
    ctx.fillStyle = st[0]; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(text, x + 4, y + 0.5);
    labelRects.push([x, y, w]);
  });
}
function setView(v) {
  S.view = v === 'portfolio' ? 'portfolio' : 'chart';
  document.body.classList.toggle('view-pf', S.view === 'portfolio');
  $('#pfPage').hidden = S.view !== 'portfolio';
  $$('#viewSeg button').forEach(b => b.classList.toggle('on', b.dataset.view === S.view));
  if (S.view === 'portfolio') { window.FEPortfolio.render(S.pf, { gotoTicker }); pollPortfolio(); }
  if (S.bars) { renderTop(); syncUrl(); }
}
function gotoTicker(t) { setView('chart'); if (t !== S.ticker) setTicker(t); }
function pfCount() {      // 点 AI 分析时会附上几个仓位（只在看最新一根时附）
  if (!S.pf || !S.pf.ok || !S.bars || S.asof < lastIdx()) return 0;
  return (S.pf.positions || []).concat(S.pf.other_accounts || []).filter(p => p.check_ticker === S.ticker).length;
}
async function pollData() {          // 定时任务追加了新日线，或者过了收盘时间数据变旧：自动重取，不用手动刷新页面
  if (!S.bars) return;
  try {
    const v = await api('/api/data/version'), cur = S.bars.freshness || {}, now = v[S.ticker];
    if (!now) return;
    if (now.last !== cur.last || now.stale !== cur.stale || now.expected !== cur.expected) {
      S.meta = await api('/api/meta');
      await setTicker(S.ticker, S.replayOn && S.asof < lastIdx() ? asofDate() : null);
    }
  } catch (e) { /* 下一轮再试 */ }
}
async function pollPortfolio(force) {
  pollData();
  try {
    const v = await api('/api/portfolio/version');
    if (force === true || !S.pf || v.version !== S.pf.version || v.ok !== S.pf.ok || (S.pf.ok && v.stale !== S.pf.stale)) {
      S.pf = await api('/api/portfolio');
      window.FEPortfolio.render(S.pf, { gotoTicker });
      if (S.bars) { renderTop(); renderSide(); candle.applyOptions({ autoscaleInfoProvider: scaleProvider }); }
      S.rev++;
    }
  } catch (e) { /* 下一轮再试 */ }
}

function rebuildIndicators() {
  ind.series.forEach(s => chart.removeSeries(s));
  ind = { series: [] };
  const add = (def, opt, pane) => { const s = chart.addSeries(def, opt, pane); ind.series.push(s); return s; };
  const quiet = { priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false };
  let p = 1;
  if (S.ind.vol) {
    ind.volPane = p;
    ind.vol = add(LW.HistogramSeries, Object.assign({ priceFormat: { type: 'volume' } }, quiet), p);
    ind.vma5 = add(LW.LineSeries, Object.assign({ color: '#e6e8ee', lineWidth: 1 }, quiet), p);
    ind.vma10 = add(LW.LineSeries, Object.assign({ color: C.vwap, lineWidth: 1 }, quiet), p);
    ind.liveVol = add(LW.HistogramSeries, Object.assign({ priceFormat: { type: 'volume' } }, quiet), p);
    p++;
  }
  if (S.ind.macd) {
    ind.macdPane = p;
    ind.hist = add(LW.HistogramSeries, Object.assign({ priceFormat: { type: 'price', precision: 3, minMove: 0.001 } }, quiet), p);
    ind.dif = add(LW.LineSeries, Object.assign({ color: '#e6e8ee', lineWidth: 1 }, quiet), p);
    ind.dea = add(LW.LineSeries, Object.assign({ color: C.vwap, lineWidth: 1 }, quiet), p);
    p++;
  }
  // 录屏里那几样常用工具：布林带画在主图上，RSI、KDJ、ATR 各占一排副图。只是显示，规则判定在后端
  const line = (color, pane, extra) => add(LW.LineSeries, Object.assign({ color, lineWidth: 1 }, quiet, extra || {}), pane);
  const p2 = { priceFormat: { type: 'price', precision: 2, minMove: 0.01 } };
  if (S.ind.boll) { ind.bmid = line('#e6e8ee', 0); ind.bup = line('#7dd3fc', 0); ind.blow = line('#f0abfc', 0); }
  if (S.ind.rsi) {
    ind.rsiPane = p; ind.rsi = line('#c4b5fd', p, p2);
    [30, 50, 70].forEach(v => ind.rsi.createPriceLine({ price: v, color: '#5b6376', lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: '' }));
    p++;
  }
  if (S.ind.kdj) { ind.kdjPane = p; ind.kk = line('#e6e8ee', p, p2); ind.kd = line(C.vwap, p, p2); ind.kj = line('#f472b6', p, p2); p++; }
  if (S.ind.atr) { ind.atrPane = p; ind.atr = line('#7dd3fc', p); p++; }
  chart.panes().forEach((pn, k) => pn.setStretchFactor(k === 0 ? 3.6 : 1));
  $('#indCount').textContent = ['vol', 'macd', 'boll', 'rsi', 'kdj', 'atr'].filter(k => S.ind[k]).length;
  if (S.bars) applyData();
}

function buildData() {
  const b = S.bars, n = b.d.length, low = new Set(b.lowvol);
  const upA = C.up + '99', dnA = C.down + '99';
  D = { candle: new Array(n), vol: new Array(n), vma5: new Array(n), vma10: new Array(n), hist: new Array(n), dif: new Array(n), dea: new Array(n), low };
  for (let i = 0; i < n; i++) {
    const t = b.d[i], up = b.c[i] >= b.o[i];
    D.candle[i] = { time: t, open: b.o[i], high: b.h[i], low: b.l[i], close: b.c[i] };
    D.vol[i] = { time: t, value: b.v[i], color: low.has(i) ? C.lowvol : (up ? upA : dnA) };
    D.vma5[i] = b.vma5[i] == null ? { time: t } : { time: t, value: b.vma5[i] };
    D.vma10[i] = b.vma10[i] == null ? { time: t } : { time: t, value: b.vma10[i] };
    D.hist[i] = { time: t, value: b.hist[i], color: b.hist[i] >= 0 ? C.up : C.down };
    D.dif[i] = { time: t, value: b.dif[i] };
    D.dea[i] = { time: t, value: b.dea[i] };
  }
  const pts = a => (a || []).map((v, i) => (v == null ? { time: b.d[i] } : { time: b.d[i], value: v }));
  ['rsi', 'kdj_k', 'kdj_d', 'kdj_j', 'boll_mid', 'boll_up', 'boll_low', 'atr'].forEach(k => { D[k] = pts(b[k]); });
}

function applyData() {
  const m = S.asof + 1, px = S.bars.c[S.asof];
  const prec = px >= 1 ? 2 : px >= 0.1 ? 3 : 4;
  candle.applyOptions({ priceFormat: { type: 'price', precision: prec, minMove: Math.pow(10, -prec) } });
  candle.setData(D.candle.slice(0, m));
  if (ind.vol) { ind.vol.setData(D.vol.slice(0, m)); ind.vma5.setData(D.vma5.slice(0, m)); ind.vma10.setData(D.vma10.slice(0, m)); }
  if (ind.hist) { ind.hist.setData(D.hist.slice(0, m)); ind.dif.setData(D.dif.slice(0, m)); ind.dea.setData(D.dea.slice(0, m)); }
  if (ind.bmid) { ind.bmid.setData(D.boll_mid.slice(0, m)); ind.bup.setData(D.boll_up.slice(0, m)); ind.blow.setData(D.boll_low.slice(0, m)); }
  if (ind.rsi) ind.rsi.setData(D.rsi.slice(0, m));
  if (ind.kk) { ind.kk.setData(D.kdj_k.slice(0, m)); ind.kd.setData(D.kdj_d.slice(0, m)); ind.kj.setData(D.kdj_j.slice(0, m)); }
  if (ind.atr) ind.atr.setData(D.atr.slice(0, m));
  applyLive();
  S.rev++;
}

// ---------- 盘中实时（只画图：不进 S.bars、不进证据、不进 AI）----------
/* 日线：今天常规时段的那根未收盘 K 线，画在最后一根已入库 K 线的右边。
   周线：本周还没收完，就把已入库的本周部分和今天的盘中合成一根，叠在本周那根上（实色是已确认，半透明是还在长的）。 */
function liveBar() {
  const L = S.live;
  if (!S.ind.live || !L || !L.ok || !L.show_candle || !L.bar || !S.bars || L.ticker !== S.ticker || S.asof < lastIdx()) return null;
  const b = L.bar;
  if (isDaily()) return L.session_date > S.bars.d[lastIdx()] ? { time: L.session_date, open: b.o, high: b.h, low: b.l, close: b.c, volume: b.v } : null;
  const wk = d => { const t = new Date(d + 'T12:00:00Z'), day = (t.getUTCDay() + 6) % 7; t.setUTCDate(t.getUTCDate() - day); return t.toISOString().slice(0, 10); };
  const k = lastIdx(), sb = S.bars;
  if (wk(sb.d[k]) === wk(L.session_date)) {
    return { time: sb.d[k], open: sb.o[k], high: Math.max(sb.h[k], b.h), low: Math.min(sb.l[k], b.l), close: b.c, volume: sb.v[k] + b.v };
  }
  return { time: L.session_date, open: b.o, high: b.h, low: b.l, close: b.c, volume: b.v };
}
function applyLive() {
  if (!liveCandle) return;
  const x = liveBar();
  liveCandle.setData(x ? [{ time: x.time, open: x.open, high: x.high, low: x.low, close: x.close }] : []);
  if (ind.liveVol) ind.liveVol.setData(x ? [{ time: x.time, value: x.volume, color: rgba(x.close >= x.open ? C.up : C.down, 0.3) }] : []);
}
function liveLegend() {
  const L = S.live;
  if (!S.ind.live || !L || !L.ok || L.ticker !== S.ticker) return '';
  const t = L.price_time ? new Date(L.price_time * 1000).toLocaleTimeString('zh-CN', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit' }) : '';
  let h = '';
  if (L.status === 'regular') h = '<span class="live" id="legLive">' + (L.demo ? '演示数据 · ' : '') + '● 盘中 <b>' + fmtP(L.price) + '</b> ' + fmtPct(L.change_pct) + ' · 美东 ' + t + ' · 未收盘，不参与判定</span>';
  else if (L.show_candle) h = '<span class="live" id="legLive">○ ' + L.session_date + ' 已收盘 <b>' + fmtP(L.price) + '</b> · 待入库，入库前不参与判定</span>';
  if (L.outside) h += '<span class="live dim" id="legOutside">' + esc(L.outside.label) + ' ' + fmtP(L.outside.price) + '（不计入 K 线）</span>';
  return h;
}
let liveTimer = 0;
async function pollLive() {
  clearTimeout(liveTimer);
  if (S.liveFrozen) { applyLive(); renderLegend(); return; }     // 自检时用固定的模拟数据
  let wait = 30000;
  if (S.bars && S.ind.live && S.view === 'chart') {
    try {
      const r = await api('/api/live?ticker=' + S.ticker);
      if (S.liveFrozen) return;
      if (r.ticker === S.ticker) { S.live = r; applyLive(); renderLegend(); }
      if (r.status === 'regular') wait = 3000;
    } catch (e) { /* 下一轮再试 */ }
  }
  liveTimer = setTimeout(pollLive, wait);
}

/* 右侧留白：证据条展开时留出它的宽度，让最新的 K 线不被盖住。 */
function rightPad(span) {
  const w = OV.w, need = S.evFold ? 0 : 300;
  if (!need || w < 760) return RIGHT_PAD;
  return clamp(Math.ceil(span * need / (w - need)), RIGHT_PAD, Math.ceil(span * 0.7));
}
function focusView(span) {
  const ts = chart.timeScale();
  if (span == null) span = S.span || 150;
  S.span = span; S.pad = rightPad(span);
  ts.setVisibleLogicalRange({ from: S.asof - span, to: S.asof + S.pad });
  S.viewW = OV.w;
}
function noteSpan() {       // 用户自己缩放后，记住他要看多少根
  const r = chart.timeScale().getVisibleLogicalRange();
  if (r && S.pad != null) S.span = clamp(Math.round(r.to - r.from) - S.pad, 20, 8000);
}

// ---------- overlay (自动画 + 手动画线 + 1–4 三角) ----------
const X = i => chart.timeScale().logicalToCoordinate(i);
const Y = p => candle.priceToCoordinate(p);

function syncOverlay() {
  let ps;
  try { ps = chart.paneSize(0); } catch (e) { return false; }
  const dpr = window.devicePixelRatio || 1;
  if (ps.width !== OV.w || ps.height !== OV.h || dpr !== OV.dpr) {
    OV = { w: ps.width, h: ps.height, dpr };
    ov.width = Math.max(1, Math.round(ps.width * dpr)); ov.height = Math.max(1, Math.round(ps.height * dpr));
    ov.style.width = ps.width + 'px'; ov.style.height = ps.height + 'px';
    return true;
  }
  return false;
}

function loop() { requestAnimationFrame(loop); tick(); }
function tick(force) {
  if (!S.bars || !chart) return;
  const resized = syncOverlay() || force === true;
  if (S.needFocus && OV.w > 80) { S.needFocus = false; focusView(S.span || 150); }
  const a = X(0), b = X(100), y1 = Y(1), y2 = Y(2);
  const sig = [a, b, y1, y2, S.rev, flashAnimating() || window.FEQuant.animating() ? performance.now() : 0].join('|');     // 标记正在一笔一笔画的时候，每帧都重画
  if (resized || sig !== lastSig) { lastSig = sig; draw(); placeLegends(); }
}

function placeLegends() {
  const wrap = $('#chartwrap').getBoundingClientRect(), panes = chart.panes();
  const put = (el, k) => {
    const pn = k != null ? panes[k] : null, h = pn && pn.getHTMLElement ? pn.getHTMLElement() : null;
    if (!h) { el.hidden = true; return; }
    el.hidden = false; el.style.top = (h.getBoundingClientRect().top - wrap.top + 4) + 'px';
  };
  put($('#legVol'), S.ind.vol ? ind.volPane : null);
  put($('#legMacd'), S.ind.macd ? ind.macdPane : null);
  put($('#legRsi'), S.ind.rsi ? ind.rsiPane : null);
  put($('#legKdj'), S.ind.kdj ? ind.kdjPane : null);
  put($('#legAtr'), S.ind.atr ? ind.atrPane : null);
  let sw = 64;
  try { sw = chart.priceScale('right').width(); } catch (e) { /* 用默认 */ }
  $('#evidence').style.right = (sw + 12) + 'px';
}

let labelRects = [];
function label(text, x, y, color, align) {
  ctx.font = '11px -apple-system,"PingFang SC",sans-serif';
  const w = ctx.measureText(text).width + 8;
  const x0 = align === 'right' ? x - w : align === 'center' ? x - w / 2 : x;
  for (let k = 0; k < 5 && labelRects.some(r => x0 < r[0] + r[2] && x0 + w > r[0] && Math.abs(y - r[1]) < 16); k++) y += 17;   // 标签互相让开
  labelRects.push([x0, y, w]);
  ctx.fillStyle = '#12151ccc'; ctx.fillRect(x0, y - 8, w, 16);
  ctx.fillStyle = color; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(text, x0 + 4, y + 0.5);
}

/* 扇子：从 (ai, H) 出发，经过 (bi, L + r·(H−L))，r = 0.382 / 0.5 / 0.618，向右延伸。和 engine.py 的扇线同一条公式。 */
function drawFan(ai, H, bi, L, o) {
  const x0 = X(ai), y0 = Y(H), x1 = X(bi);
  if (x0 == null || y0 == null || x1 == null || x1 <= x0) return;
  const xe = Math.max(OV.w, x1 + 1);
  const ends = FAN.map(r => { const yl = Y(L + Number(r) * (H - L)); return { r, yl, ye: y0 + (yl - y0) * (xe - x0) / (x1 - x0) }; });
  if (ends.some(e => e.yl == null)) return;
  const fills = [C.fan + '2e', '#b9c94a2e'];
  for (let k = 0; k < 2; k++) {
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(xe, ends[k].ye); ctx.lineTo(xe, ends[k + 1].ye); ctx.closePath();
    ctx.fillStyle = fills[k]; ctx.fill();
  }
  ends.forEach(e => {
    const mid = e.r === '0.5';
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(xe, e.ye);
    ctx.strokeStyle = o.color; ctx.lineWidth = mid ? 1.8 : 1; ctx.setLineDash(mid ? [] : [5, 4]); ctx.stroke(); ctx.setLineDash([]);
    label(e.r, x1 + 6, e.yl, o.color);
  });
  const yL = Y(L);
  if (yL != null) { ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, yL); ctx.strokeStyle = o.color + '66'; ctx.lineWidth = 1; ctx.setLineDash([2, 3]); ctx.stroke(); ctx.setLineDash([]); }
  if (o.selected) [[x0, y0], [x1, yL]].forEach(p => { ctx.fillStyle = '#fff'; ctx.fillRect(p[0] - 3, p[1] - 3, 6, 6); });
}

function drawPolyline(start, values, color, width) {
  ctx.beginPath(); let pen = false;
  for (let k = 0; k < values.length; k++) {
    const x = X(start + k), y = values[k] == null ? null : Y(values[k]);
    if (x == null || y == null) { pen = false; continue; }
    if (pen) ctx.lineTo(x, y); else ctx.moveTo(x, y); pen = true;
  }
  ctx.strokeStyle = color; ctx.lineWidth = width; ctx.stroke();
}

function drawHLine(fromX, price, color, text, dash) {
  const y = Y(price); if (y == null) return;
  ctx.beginPath(); ctx.moveTo(Math.max(0, fromX), y); ctx.lineTo(OV.w, y);
  ctx.strokeStyle = color; ctx.lineWidth = 1.4; ctx.setLineDash(dash || []); ctx.stroke(); ctx.setLineDash([]);
  if (text) label(text, Math.max(6, fromX + 6), y - 10, color);
}

function drawArrow(a, b, text, color, selected) {
  const x0 = X(a.i), y0 = Y(a.p), x1 = X(b.i), y1 = Y(b.p);
  if ([x0, y0, x1, y1].some(v => v == null)) return;
  const ang = Math.atan2(y1 - y0, x1 - x0), h = 9;
  ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 1.8;
  ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(x1, y1);
  ctx.lineTo(x1 - h * Math.cos(ang - 0.45), y1 - h * Math.sin(ang - 0.45));
  ctx.lineTo(x1 - h * Math.cos(ang + 0.45), y1 - h * Math.sin(ang + 0.45)); ctx.closePath(); ctx.fill();
  if (text) {
    ctx.font = '600 13px -apple-system,"PingFang SC",sans-serif';
    const w = ctx.measureText(text).width + 10, tx = clamp(x0 - w / 2, 2, OV.w - w - 2), ty = y0 + (y0 > y1 ? 14 : -14);
    ctx.fillStyle = '#12151cdd'; ctx.fillRect(tx, ty - 10, w, 20);
    ctx.fillStyle = color; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(text, tx + 5, ty + 0.5);
  }
  if (selected) [[x0, y0], [x1, y1]].forEach(p => { ctx.fillStyle = '#fff'; ctx.fillRect(p[0] - 3, p[1] - 3, 6, 6); });
}

function drawTriangle(x, yTop, n) {
  const hw = 13, hh = 23;
  ctx.beginPath(); ctx.moveTo(x, yTop); ctx.lineTo(x - hw, yTop + hh); ctx.lineTo(x + hw, yTop + hh); ctx.closePath();
  ctx.fillStyle = C.hazard; ctx.fill(); ctx.strokeStyle = '#141414'; ctx.lineWidth = 1.5; ctx.stroke();
  ctx.fillStyle = '#141414'; ctx.font = '800 12px -apple-system,sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(String(n), x, yTop + 15.5);
}

function drawAuto() {
  const st = S.state, dr = st.draw;
  if (dr.fan) drawFan(dr.fan.hi, dr.fan.H, dr.fan.lo, dr.fan.L, { color: C.fan });
  if (dr.avwap && dr.avwap.values.length) {
    drawPolyline(dr.avwap.anchor, dr.avwap.values, C.vwap, 2);
    const xa = X(dr.avwap.anchor), ya = Y(dr.avwap.values[0]);
    if (xa != null && ya != null) { ctx.beginPath(); ctx.arc(xa, ya, 3.5, 0, Math.PI * 2); ctx.fillStyle = C.vwap; ctx.fill(); }
    const xl = X(S.asof), yl = Y(st.levels.avwap);
    if (xl != null && yl != null) label('成本线 ' + fmtP(st.levels.avwap), xl + 8, yl - 12, C.vwap);
  }
  const xlo = X(dr.low.i);
  if (dr.stop != null && xlo != null) drawHLine(xlo, dr.stop, C.stop, '止损 ' + fmtP(dr.stop) + '（低点下 3%）', [6, 4]);
  if (dr.target != null && xlo != null) drawHLine(xlo, dr.target, C.target, '第一目标 ' + fmtP(dr.target), [2, 4]);
  const xh = X(dr.high.i), yh = Y(dr.high.price), yl2 = Y(dr.low.price);
  if (xh != null && yh != null) label('高点 ' + fmtP(dr.high.price), xh, yh - 12, C.mut, 'center');
  if (xlo != null && yl2 != null && !(st.marks || []).some(m => m.i === dr.low.i && m.side === 'below' && S.ind.marks)) label('低点 ' + fmtP(dr.low.price), xlo, yl2 + 12, C.mut, 'center');
  if (dr.fan && dr.fan.levels['0.5'].at_asof != null) {
    const x = X(S.asof), y = Y(dr.fan.levels['0.5'].at_asof);
    if (x != null && y != null && y > -20 && y < OV.h + 20) { ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fillStyle = C.fan; ctx.fill(); label('中线 ' + fmtP(dr.fan.levels['0.5'].at_asof), x + 8, y + 12, C.fan); }
  }
}

function drawMarks() {
  const used = {};
  (S.state.marks || []).forEach(m => {
    const x = X(m.i), y = Y(m.price); if (x == null || y == null) return;
    const key = m.i + m.side, k = used[key] || 0; used[key] = k + 1;
    drawTriangle(x, m.side === 'below' ? y + 8 + k * 27 : y - 31 - k * 27, m.n);
  });
}

function visible(d) {     // 回放时，锚点在回放日之后的手动画线先藏起来
  if (S.dt && S.dt.hide) return false;                 // 工具栏的“隐藏”开着
  if (window.FEDraw.has(d.type)) return window.FEDraw.visible(d);
  if (d.type === 'hline') return true;
  if (d.type === 'avwap') return d.i <= S.asof;
  return d.a.i <= S.asof;
}
function manualAvwap(d) {
  const key = S.ticker + '|' + d.d + '|' + asofDate(), hit = S.avwap[key];
  if (hit) return hit === 'loading' ? null : hit;
  S.avwap[key] = 'loading';
  api('/api/avwap?ticker=' + S.ticker + '&anchor=' + d.d + '&asof=' + asofDate()).then(j => { S.avwap[key] = j; S.rev++; }).catch(() => { delete S.avwap[key]; });
  return null;
}
function drawManual() {
  S.drawings.forEach((d, k) => {
    if (!visible(d)) return;
    const sel = k === S.selected, col = sel ? '#ffffff' : '#7dd3fc';
    if (window.FEDraw.has(d.type)) window.FEDraw.render(d, k, sel);
    else if (d.type === 'hline') drawHLine(0, d.p, col, fmtP(d.p));
    else if (d.type === 'fan') drawFan(d.a.i, d.a.p, d.b.i, d.b.p, { color: col, selected: sel });
    else if (d.type === 'arrow') drawArrow(d.a, d.b, d.text, sel ? '#ffffff' : '#fde047', sel);
    else if (d.type === 'avwap') {
      const s = manualAvwap(d); if (!s || !s.values.length) return;
      drawPolyline(s.anchor, s.values, sel ? '#ffffff' : '#f0abfc', 1.8);
      const x = X(s.anchor), y = Y(s.values[0]);
      if (x != null && y != null) { ctx.beginPath(); ctx.arc(x, y, 3.5, 0, Math.PI * 2); ctx.fillStyle = '#f0abfc'; ctx.fill(); }
      const xl = X(s.anchor + s.values.length - 1), yl = Y(s.values[s.values.length - 1]);
      if (xl != null && yl != null) label('VWAP ' + fmtP(s.values[s.values.length - 1]) + '（' + d.d.slice(5) + ' 起）', xl + 8, yl - 12, '#f0abfc');
    }
  });
  window.FEDraw.drawRuler();
}
function drawPending() {
  const p = S.pending, c = S.cur;
  if (window.FEDraw.has(S.tool)) { window.FEDraw.preview(); return; }
  if (S.tool === 'cursor' || !c) return;
  ctx.globalAlpha = 0.85;
  if (S.tool === 'hline') drawHLine(0, c.p, '#7dd3fc', fmtP(c.p), [4, 4]);
  else if (S.tool === 'avwap') { const s = snap(c); const x = X(s.i); if (x != null) { ctx.strokeStyle = '#f0abfc'; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, OV.h); ctx.stroke(); ctx.setLineDash([]); label('起算日 ' + s.d, x + 6, 44, '#f0abfc'); } }
  else if (S.tool === 'fan') {
    const s = snap(c);
    if (!p) { const x = X(s.i), y = Y(s.p); if (x != null && y != null) { ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fillStyle = '#7dd3fc'; ctx.fill(); label('高点 ' + fmtP(s.p), x + 8, y - 10, '#7dd3fc'); } }
    else if (s.i > p.a.i) drawFan(p.a.i, p.a.p, s.i, s.p, { color: '#7dd3fc' });
  } else if (S.tool === 'arrow' && p && !p.b) drawArrow(p.a, { i: c.li, p: c.p }, '', '#fde047');
  ctx.globalAlpha = 1;
}

function draw() {
  if (!ctx) return;
  ctx.setTransform(OV.dpr, 0, 0, OV.dpr, 0, 0);
  ctx.clearRect(0, 0, OV.w, OV.h);
  labelRects = [];
  if (!S.bars) return;
  ctx.save(); ctx.beginPath(); ctx.rect(0, 0, OV.w, OV.h); ctx.clip();
  const four = !window.FEQuant.hideFour();      // 选了后手模型时，四证的自动画和 1–4 标记先收起来
  if (stateFresh() && isDaily()) { if (S.auto && four) drawAuto(); }     // 扇子、成本线、标记都是按日线 K 线的位置画的
  window.FEQuant.draw();                          // 「AI 量化」面板的结构线和后手模型的叠加
  window.FENotes.draw();                          // K 线底部的备注标记：那一天发生过什么
  drawPortfolioLines();
  drawManual();
  drawPending();
  drawFlash();
  if (stateFresh() && isDaily() && S.ind.marks && four) drawMarks();
  ctx.restore();
}

// ---------- drawing tools ----------
function ptFromEvent(e) {
  const r = ov.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
  const lg = chart.timeScale().coordinateToLogical(x), p = candle.coordinateToPrice(y);
  return { x, y, li: lg == null ? 0 : Math.round(lg), p };
}
function snap(pt) {      // 吸附到这根 K 线的最高或最低价（14px 以内）
  const b = S.bars, i = clamp(pt.li, 0, S.asof);
  let p = pt.p; const yh = Y(b.h[i]), yl = Y(b.l[i]);
  if (yh != null && Math.abs(pt.y - yh) < 14) p = b.h[i]; else if (yl != null && Math.abs(pt.y - yl) < 14) p = b.l[i];
  return { i, p, d: b.d[i] };
}
const HINTS = { fan: ['扇形：先点高点', '扇形：再点低点（在高点右边）'], avwap: ['锚定 VWAP：点一根 K 线作为起算日'], hline: ['水平线：点一个价位'], arrow: ['箭头：先点起点（文字写在这里）', '箭头：再点要指向的位置'] };
function setTool(t) {
  if (t === 'avwap' && !isDaily()) { toast('周线上不画锚定 VWAP（成本线按日线算），切回日线再用。'); t = 'cursor'; }
  S.tool = t; S.pending = null; S.cur = null; $('#textBox').hidden = true;
  window.FEDraw.sync(t);
  ov.classList.toggle('draw', t !== 'cursor');
  updateHint(); S.rev++;
}
function updateHint() {
  const h = $('#hint');
  if (S.tool === 'cursor') { h.hidden = true; return; }
  const txt = HINTS[S.tool] ? HINTS[S.tool][S.pending ? 1 : 0] : window.FEDraw.hint();
  h.textContent = txt + ' · Esc 取消'; h.hidden = false;
}
// 日线、周线各存一套手动画线；工具栏的“同步”打开后共用日线那一套（点按日期对回 K 线）
const drawKey = () => 'draw.' + S.ticker + (isDaily() || (S.dt && S.dt.sync) ? '' : '.W');
function saveDrawings() { store.set(drawKey(), S.drawings); }
function loadDrawings() {
  const arr = store.get(drawKey(), []);
  const fix = pt => { if (pt && pt.d) pt.i = S.idx[pt.d] != null ? S.idx[pt.d] : indexAt(pt.d); return pt; };
  S.drawings = (Array.isArray(arr) ? arr : []).filter(d => d && d.type).map(d => {
    if (d.type === 'avwap') fix(d); else if (d.pts) d.pts.forEach(fix); else if (d.a) { fix(d.a); fix(d.b); }
    return d;
  });
  S.selected = -1;
}
function addDrawing(d) { S.drawings.push(d); saveDrawings(); S.selected = S.drawings.length - 1; setTool('cursor'); }
function askText(pt) {
  const box = $('#textBox'), inp = $('#textInput');
  box.style.left = clamp(pt.x - 40, 4, OV.w - 200) + 'px'; box.style.top = clamp(pt.y + 12, 4, OV.h - 34) + 'px';
  inp.value = ''; box.hidden = false; inp.focus();
}
function onDrawClick(e) {
  const pt = ptFromEvent(e);
  if (pt.p == null) return;
  if (window.FEDraw.has(S.tool)) return window.FEDraw.click(pt);
  if (S.tool === 'hline') return addDrawing({ type: 'hline', p: pt.p });
  if (S.tool === 'avwap') { const s = snap(pt); return addDrawing({ type: 'avwap', i: s.i, d: s.d }); }
  if (S.tool === 'fan') {
    const s = snap(pt);
    if (!S.pending) { S.pending = { a: s }; updateHint(); S.rev++; return; }
    if (s.i <= S.pending.a.i) return toast('低点要选在高点右边的 K 线上。', true);
    return addDrawing({ type: 'fan', a: S.pending.a, b: s });
  }
  if (S.tool === 'arrow') {
    const q = { i: pt.li, p: pt.p, d: S.bars.d[pt.li] || null };
    if (!S.pending) { S.pending = { a: q }; updateHint(); S.rev++; return; }
    if (S.pending.b) return;
    S.pending.b = q;
    askText(pt);
  }
}
function segDist(px, py, x0, y0, x1, y1) {
  const dx = x1 - x0, dy = y1 - y0, l2 = dx * dx + dy * dy;
  const t = l2 ? clamp(((px - x0) * dx + (py - y0) * dy) / l2, 0, 1) : 0;
  return Math.hypot(px - (x0 + t * dx), py - (y0 + t * dy));
}
function hitTest(x, y) {
  if (S.dt && S.dt.lock) return -1;                    // 锁定：画好的线点不中
  for (let k = S.drawings.length - 1; k >= 0; k--) {
    const d = S.drawings[k]; if (!visible(d)) continue;
    if (window.FEDraw.has(d.type)) { if (window.FEDraw.hit(k, x, y)) return k; }
    else if (d.type === 'hline') { const yy = Y(d.p); if (yy != null && Math.abs(y - yy) < 6) return k; }
    else if (d.type === 'arrow') { const v = [X(d.a.i), Y(d.a.p), X(d.b.i), Y(d.b.p)]; if (v.every(q => q != null) && segDist(x, y, v[0], v[1], v[2], v[3]) < 7) return k; }
    else if (d.type === 'fan') {
      const x0 = X(d.a.i), y0 = Y(d.a.p), x1 = X(d.b.i); if (x0 == null || y0 == null || x1 == null || x1 <= x0) continue;
      for (const r of FAN) { const yl = Y(d.b.p + Number(r) * (d.a.p - d.b.p)); const ye = y0 + (yl - y0) * (OV.w - x0) / (x1 - x0); if (segDist(x, y, x0, y0, OV.w, ye) < 6) return k; }
    } else if (d.type === 'avwap') {
      const s = S.avwap[S.ticker + '|' + d.d + '|' + asofDate()]; if (!s || s === 'loading') continue;
      const lg = chart.timeScale().coordinateToLogical(x), j = Math.round(lg) - s.anchor;
      if (j >= 0 && j < s.values.length) { const yy = Y(s.values[j]); if (yy != null && Math.abs(y - yy) < 7) return k; }
    }
  }
  return -1;
}
function deleteSelected() {
  if (S.dt && S.dt.lock) return toast('画线锁着。先点工具栏的“锁定”解开，再删。');
  if (S.selected < 0) return toast('先在光标模式下点一下要删的手动画线。');
  S.drawings.splice(S.selected, 1); S.selected = -1; saveDrawings(); S.rev++;
}
function clearAll() {
  if (S.dt && S.dt.lock) return toast('画线锁着。先点工具栏的“锁定”解开，再删。');
  if (!S.drawings.length) return toast('没有手动画线。');
  S.drawings = []; S.selected = -1; saveDrawings(); S.rev++; toast('已清空 ' + S.ticker + ' 的手动画线。');
}
function zoomTo(lo, hi) {      // “放大”工具：把框住的那一段铺满图表
  const pad = Math.max(2, Math.round((hi - lo) * 0.05));
  S.needFocus = false;          // 换标的、换周期后还没执行的“回到默认视野”不能再把放大冲掉
  chart.timeScale().setVisibleLogicalRange({ from: lo - pad, to: hi + pad });
  noteSpan();
}

// ---------- state ----------
let stateTimer = 0;
function queueState(now) { clearTimeout(stateTimer); stateTimer = setTimeout(fetchState, now ? 0 : 70); }
async function fetchState() {
  const seq = ++S.seq, t = S.ticker, d = asofDate();
  try {
    const st = await api('/api/state?ticker=' + t + '&asof=' + d);
    if (seq !== S.seq) return;
    if (st.ok === false) throw new Error(st.error);
    S.state = st;
    const nar = window.FENarrate.current();
    if (nar && (nar.ticker !== S.ticker || nar.asof !== st.asof)) window.FENarrate.reset();     // 解说对应的不是这一天了
    renderEvidence(); renderSide(); syncPriceLines();
    window.FENarrate.restore();      // 这一天保存过 Claude 的解说就直接显示，不用再点、不再计费
    window.FEQuant.onState();        // 表盘、规则模型信号、结构线：按这一天重算
    window.FEChat.onState();        // 「一键解释」开着的话，跟着这一天重写
    window.FENotes.onState();        // 备注和时效：只给这一天以及之前的
    candle.applyOptions({ autoscaleInfoProvider: scaleProvider });
    S.rev++;
  } catch (e) { if (seq === S.seq) toast('取状态失败：' + e.message, true); }
}

function syncPriceLines() {
  S.plines.forEach(l => candle.removePriceLine(l)); S.plines = [];
  if (!S.auto || !stateFresh() || !isDaily() || window.FEQuant.hideFour()) return;
  const lv = S.state.levels, add = (price, color, title) => {
    if (price == null) return;
    S.plines.push(candle.createPriceLine({ price, color, lineVisible: false, axisLabelVisible: true, title }));
  };
  add(lv.stop, C.stop, '止损'); add(lv.avwap, C.vwap, '成本线');
  if (S.state.signal.target_usable) add(lv.target, C.target, '目标');
}

async function setTicker(t, date) {
  S.ticker = t; store.set('ticker', t);
  const b = await api('/api/bars?ticker=' + t + '&tf=' + S.tf);
  if (b.ok === false) return toast(b.error, true);
  S.bars = b; S.idx = {}; b.d.forEach((d, i) => { S.idx[d] = i; });
  S.state = null; S.avwap = {}; S.hover = null; S.flash = null; S.spanHome = null;
  window.FENarrate.reset(); window.FEQuant.reset(); window.FENotes.reset();
  if (S.live && S.live.ticker !== t) S.live = null;
  setTimeout(pollLive, 0);
  if (S.tool === 'avwap' && !isDaily()) setTool('cursor');
  buildData();
  S.asof = date ? indexAt(date) : lastIdx();
  S.replayOn = S.asof < lastIdx();
  loadDrawings();
  const rg = $('#rpRange'); rg.max = lastIdx(); rg.value = S.asof;
  $('#rpDate').min = b.d[1]; $('#rpDate').max = b.d[lastIdx()];
  applyData(); S.span = 150; S.needFocus = true; if (OV.w > 80) focusView(150);
  renderTop(); renderReplay(); renderLegend(); renderEvidence(); renderSide(); syncUrl();
  queueState(true);
}

/* K 线级别：顶栏的「日线 / 周线」和「AI 量化」窗口头部的下拉是同一个开关 */
function setTf(v) {
  v = v === 'W' ? 'W' : 'D';
  if (v === S.tf || !S.bars) return;
  S.tf = v;
  setTicker(S.ticker, S.replayOn && S.asof < lastIdx() ? asofDate() : null);
}
/* 回到某只标的、某个级别、某一天（任务和分析记录里点一行）：asof 为空就是最新一根 */
async function goTo(t, tf, asof) {
  if (S.view !== 'chart') setView('chart');
  S.tf = tf === 'W' ? 'W' : 'D';
  await setTicker(t, asof || null);
  if (!asof) setReplay(false);
}
function openSide() { if (!S.sideOpen) { S.sideOpen = true; store.set('side', true); renderTop(); syncUrl(); } }

function setAsof(i, keepView) {
  i = clamp(i, 1, lastIdx());
  if (i === S.asof) return;
  S.asof = i; S.hover = null;
  noteSpan(); applyData(); if (!keepView) focusView();
  renderReplay(); renderLegend(); renderTop(); syncUrl(); queueState();
}
function setReplay(on, date) {
  S.replayOn = on;
  if (!on) setAsof(lastIdx()); else if (date) setAsof(indexAt(date));
  renderReplay(); renderTop(); syncUrl();
}
function syncUrl() {
  const q = new URLSearchParams();
  q.set('t', S.ticker);
  if (!isDaily()) q.set('tf', 'W');
  if (S.replayOn && S.asof < lastIdx()) q.set('asof', asofDate());
  if (!S.sideOpen) q.set('side', '0');
  if (S.view === 'portfolio') q.set('view', 'portfolio');
  if (new URLSearchParams(location.search).get('aifake') === '1') q.set('aifake', '1');
  try { history.replaceState(null, '', '?' + q.toString()); } catch (e) { /* file:// 等场景忽略 */ }
}

// ---------- rendering ----------
function renderTop() {
  const box = $('#tickers'); box.innerHTML = '';
  (S.meta ? S.meta.tickers : []).forEach(t => {
    const b = document.createElement('button');
    b.className = t.ticker === S.ticker ? 'on' : ''; b.setAttribute('role', 'tab');
    const sc = !t.armed ? '未触发' : t.lit + '/4';
    b.innerHTML = '<b>' + esc(t.ticker) + '</b><span class="sc' + (t.armed && t.lit > 0 ? ' hot' : '') + '">' + sc + '</span>';
    b.title = t.ticker + ' · ' + t.asof + ' 收盘 ' + fmtP(t.close) + '（' + fmtPct(t.chg_pct) + '）';
    b.onclick = () => { if (S.view !== 'chart') setView('chart'); if (t.ticker !== S.ticker) setTicker(t.ticker); };
    box.appendChild(b);
  });
  if (!S.bars) return;
  const fr = S.bars.freshness, dd = $('#dataDate'), lrf = S.meta && S.meta.last_refresh_file;
  dd.textContent = '数据截至 ' + (fr ? fr.last : S.bars.d[lastIdx()]) + ' 收盘 · ' + TF_NAME[S.tf] + ' · 非实时';
  dd.className = 'chip chart-only';
  if (fr && fr.stale) {
    dd.className = 'chip chart-only err';
    dd.textContent = '数据未更新：只到 ' + fr.last + '，缺 ' + fr.lag_sessions + ' 个交易日（应到 ' + fr.expected + '）';
  }
  dd.title = '只有收盘后的日线，没有实时行情。' + (lrf ? '上次刷新 ' + String(lrf.at).replace('T', ' ').slice(0, 16) + '（' + (lrf.trigger === 'schedule' ? '定时任务' : '手动') + '）' + (lrf.has_error ? '，有错误' : '') : '还没有刷新记录') +
    (fr && !fr.calendar_known ? '。交易日历只录到 2027 年，之后按工作日估算。' : '');
  $$('#tfSeg [data-tf]').forEach(b => b.classList.toggle('on', b.dataset.tf === S.tf));
  $$('#tools [data-tool=avwap]').forEach(avBtn => { avBtn.disabled = !isDaily(); avBtn.title = isDaily() ? '锚定 VWAP：点一根 K 线作为起算日' : '周线上不画锚定 VWAP（成本线按日线算），切回日线再用'; });
  $('#autoBtn').disabled = !isDaily(); $('#autoBtn').title = isDaily() ? '自动画：按引擎的高点、低点、地量日画出扇子、成本线、止损线' : '周线上不自动画：四要素只按日线判定，切回日线再看';
  const srcN = Object.keys(S.bars.src).length, w = $('#dataWarn'), lr = S.meta && S.meta.last_refresh;
  if (lr && lr.has_error) { w.hidden = false; w.className = 'chip err'; w.textContent = '数据刷新有错误'; w.onclick = () => showRefresh(lr); }
  else if (srcN) {
    const cc = S.bars.crosscheck || {}, rows = Object.keys(S.bars.src).map(i => cc[S.bars.d[Number(i)]]);
    const bad = rows.filter(c => c && !c.ok).length, okN = rows.filter(c => c && c.ok).length;
    w.hidden = false; w.className = bad ? 'chip err' : 'chip warn';
    w.textContent = (S.bars.src[String(lastIdx())] ? '最新 K 线为单一来源' : '有单一来源的行') + ' · ' + srcN + ' 行' +
      (bad ? ' · ' + bad + ' 行核对不一致' : okN === srcN ? ' · 已核对一致' : ' · ' + (srcN - okN) + ' 行未核对');
    w.onclick = showSources;
  } else w.hidden = true;
  const chip = $('#pfChip'), pf = S.pf;
  if (pf && pf.ok) { chip.hidden = false; chip.className = 'chip' + (pf.stale ? ' warn' : ''); chip.textContent = '持仓更新于 ' + String(pf.updated_at || '—').slice(5, 16) + (pf.stale ? ' · 已过期' : ''); chip.onclick = () => setView('portfolio'); }
  else chip.hidden = true;
  $('#replayBtn').classList.toggle('on', S.replayOn);
  $('#autoBtn').classList.toggle('on', S.auto);
  $('#aiBtn').textContent = S.sideOpen ? '✦ AI 量化 ▸' : '✦ AI 量化';
  $('#side').classList.toggle('closed', !S.sideOpen);
}
function showRefreshFile(r) {        // data/last_refresh.json：按钮和定时任务都写
  let h = '<p class="n">' + esc(String(r.at).replace('T', ' ').slice(0, 19)) + ' · ' + (r.trigger === 'schedule' ? '定时任务' : '手动') + ' · 只追加新日期，已有的行不改。</p>';
  Object.keys(r.tickers || {}).forEach(t => {
    const x = r.tickers[t];
    h += '<h4>' + esc(t) + '（截至 ' + esc(x.last || '—') + '）</h4><ul>' +
      (x.appended.length ? '<li class="a">新增 ' + x.appended.map(esc).join('、') + '</li>' : '<li class="n">没有新的日线。</li>') +
      x.errors.map(e => '<li class="e">' + esc(e) + '</li>').join('') + x.notes.map(n => '<li class="n">' + esc(n) + '</li>').join('') + '</ul>';
  });
  modal('上次刷新数据', h);
}
function showSources() {
  const cc = S.bars.crosscheck || {};
  const rows = Object.keys(S.bars.src).map(Number).sort((a, b) => b - a).map(i => {
    const d = S.bars.d[i], c = cc[d];
    const chk = !c ? '<span class="n">还没有第二来源核对（点“刷新数据”会核对）</span>' : c.ok ? '<span class="a">' + esc(c.source) + ' 核对一致（差 ' + c.diff_pct + '%）</span>' : '<span class="e">' + esc(c.source) + ' 收盘 ' + c.close + '，相差 ' + c.diff_pct + '%</span>';
    return '<li>' + d + ' · 收 ' + fmtP(S.bars.c[i]) + ' · 来源 ' + esc(S.bars.src[String(i)]) + ' · ' + chk + '</li>';
  });
  modal(S.ticker + '：只有单一来源的行', '<p class="n">这些行写入时只有一个数据源。原文件里的行不会被改动；第二来源的核对结果单独记在 data/crosscheck.json。</p><ul>' + rows.join('') + '</ul>');
}
function showRefresh(r) {
  let h = '<p class="n">' + esc(r.at) + ' · 用时 ' + r.seconds + ' 秒 · 只追加新日期，已有的行不改。</p>';
  Object.keys(r.tickers).forEach(t => {
    const x = r.tickers[t];
    h += '<h4>' + esc(t) + '（截至 ' + esc(x.last || '—') + '）</h4><ul>';
    h += x.appended.length ? x.appended.map(a => '<li class="a">新增 ' + a.date + ' · 收 ' + a.close + ' · 来源 ' + esc(a.src) + (a.src.indexOf('single') >= 0 ? '（单一来源）' : '') + '</li>').join('') : '<li class="n">没有新的日线。</li>';
    h += x.errors.map(e => '<li class="e">' + esc(e) + '</li>').join('') + x.notes.map(n => '<li class="n">' + esc(n) + '</li>').join('');
    const src = Object.keys(x.sources || {}).map(k => k + (x.sources[k].trusted ? ' ✓' : ' ✗')).join('，');
    if (src) h += '<li class="n">来源：' + esc(src) + '</li>';
    h += '</ul>';
  });
  modal('刷新数据结果', h);
}

function renderLegend() {
  if (!S.bars) return;
  const b = S.bars, i = S.hover != null ? S.hover : S.asof, prev = i > 0 ? b.c[i - 1] : b.o[i];
  const chg = (b.c[i] / prev - 1) * 100, cls = b.c[i] >= prev ? 'up' : 'down', src = b.src[String(i)];
  $('#legend').innerHTML = '<b>' + esc(S.ticker) + '</b><span>' + TF_NAME[S.tf] + '</span><span>' + b.d[i] + '</span>' +
    '<span>开 <b class="' + cls + '">' + fmtP(b.o[i]) + '</b></span><span>高 <b class="' + cls + '">' + fmtP(b.h[i]) + '</b></span>' +
    '<span>低 <b class="' + cls + '">' + fmtP(b.l[i]) + '</b></span><span>收 <b class="' + cls + '">' + fmtP(b.c[i]) + '</b></span>' +
    '<span class="' + cls + '">' + fmtPct(chg) + '</span>' + (src ? '<span class="src">单一来源：' + esc(src) + '</span>' : '') +
    (S.ind.boll && b.boll_mid && b.boll_mid[i] != null ? '<span class="bl"><b>BOLL(20,2)</b> 上轨 ' + fmtP(b.boll_up[i]) + ' 中轨 ' + fmtP(b.boll_mid[i]) + ' 下轨 ' + fmtP(b.boll_low[i]) + '</span>' : '') +
    (S.asof === lastIdx() ? liveLegend() : '');
  const f2 = x => (x == null ? '—' : x.toFixed(2));
  if (b.rsi) $('#legRsi').innerHTML = '<b>RSI(14)</b><span class="k1">' + f2(b.rsi[i]) + '</span><span>参考线 30 / 50 / 70</span>';
  if (b.kdj_k) $('#legKdj').innerHTML = '<b>KDJ(9,3,3)</b><span class="k1">K ' + f2(b.kdj_k[i]) + '</span><span class="k2">D ' + f2(b.kdj_d[i]) + '</span><span class="kj">J ' + f2(b.kdj_j[i]) + '</span>';
  if (b.atr) $('#legAtr').innerHTML = '<b>ATR(14)</b><span class="k1">' + (b.atr[i] == null ? '—' : fmtP(b.atr[i])) + '</span><span>' + (b.atr[i] == null ? '' : '相当于收盘价的 ' + (b.atr[i] / b.c[i] * 100).toFixed(2) + '%') + '</span>';
  $('#legVol').innerHTML = '<b>VOL(5,10)</b><span>成交量 <b>' + fmtVol(b.v[i]) + '</b></span><span class="k1">MA5 ' + fmtVol(b.vma5[i]) + '</span><span class="k2">MA10 ' + fmtVol(b.vma10[i]) + '</span>' +
    (!isDaily() ? '<span>周线不标地量（地量按日线判定）</span>' : D.low && D.low.has(i) ? '<span class="lv">■ 地量日（60 日最小量）</span>' : '<span class="lv">■ 蓝柱 = 地量日</span>');
  $('#legMacd').innerHTML = '<b>MACD(12,26,9)</b><span class="k1">DIF ' + b.dif[i].toFixed(3) + '</span><span class="k2">DEA ' + b.dea[i].toFixed(3) + '</span>' +
    '<span class="' + (b.hist[i] >= 0 ? 'up' : 'down') + '">MACD ' + b.hist[i].toFixed(3) + '</span>';
}

function renderEvidence() {
  const el = $('#evidence'), st = stateFresh() ? S.state : null;
  el.classList.toggle('fold', S.evFold);
  if (!st) { el.innerHTML = '<div class="ev-head"><span class="ev-tag">案件</span><h2>抄底核心四要素</h2><span class="ev-score">证据 …</span></div>'; return; }
  // 解说播放时（S.reveal = 已经出到第几问），证据条跟着一条一条亮；平时 S.reveal 为空，全部按引擎结果显示
  const gate = S.reveal, seen = e => gate == null || gate.indexOf(e.n) >= 0;      // gate = 解说里已经讲到的证据编号
  const litN = gate == null ? st.lit : st.evidence.filter(e => e.lit && seen(e)).length;
  const sub = gate != null ? '解说中…' : !st.armed ? '未触发' : st.all4 ? '四项齐了' : '';
  const fr = st.freshness;
  let h = '<div class="ev-head" title="点一下折叠 / 展开"><span class="ev-tag">案件 · ' + esc(st.ticker) + ' ' + st.asof + '</span><h2>抄底核心四要素</h2>' +
    '<span class="ev-score">证据 ' + litN + '/4' + (sub ? '<small>' + sub + '</small>' : '') + '</span>' +
    (fr && fr.stale ? '<span class="ev-warn" id="evStale">数据只到 ' + fr.last + '，缺 ' + fr.lag_sessions + ' 个交易日，这不是最新状态</span>' : '') +
    (isDaily() ? '' : '<span class="ev-note" id="evTf">按日线 ' + st.asof + ' 收盘判定；周线只看走势</span>') + '</div><ol>';
  st.evidence.forEach(e => {
    const tag = !seen(e) ? '…' : e.lit ? '成立' : (e.ok && !st.armed ? '未触发' : '未成立');
    h += '<li class="' + (e.lit && seen(e) ? 'on' : '') + (seen(e) ? '' : ' wait') + (gate != null && gate.length && e.n === gate[gate.length - 1] ? ' now' : '') + '" title="' + esc(e.text) + '"><i>' + e.n + '</i><div><b>' + esc(e.name) + '</b><em>' + tag + '</em><p>' + esc(e.text) + '</p></div></li>';
  });
  el.innerHTML = h + '</ol>';
}

const WHY = { target: '到目标', stop: '止损', time: '到期', open: '未了结', 'stop(open)': '止损' };
function renderSide() {
  const st = stateFresh() ? S.state : null, ai = S.meta ? S.meta.ai : null;
  $('#sideSub').textContent = (isDaily() ? '日线' : '周线') + ' · 收盘确认 · 历史数据重放' + (S.replayOn && S.bars && S.asof < lastIdx() ? ' · 回放 ' + asofDate() : '');
  if (S.meta && S.meta.backtest) {
    const b = S.meta.backtest;
    $('#btCard').textContent = '结论：' + b.verdict + '。三只标的合计 ' + b.n + ' 笔，平均 ' + b.mean_r + 'R；对照组（跌够 20% 后随便挑一天买）平均 ' + b.control_mean_r + 'R，p = ' + b.p + '，不显著。所以这里只做观察。';
  }
  window.FENarrate.sync();
  if (!st) { $('#sigCard').innerHTML = '<div class="eng">计算中…</div>'; $('#tiles').innerHTML = ''; $('#basisBody').innerHTML = ''; $('#notes').innerHTML = ''; $('#sigList').innerHTML = ''; window.FEQuant.render(); return; }
  const c = st.conclusion, sg = st.signal, cd = st.card || {};
  // 规则模型卡片：全部来自引擎（st.card 由后端填），不经过 Claude
  $('#sigCard').innerHTML = '<div class="eng">◎ 四要素规则引擎 ' + esc(S.meta ? S.meta.engine.version : '') + ' · ' + esc(st.ticker) + ' ' + st.asof + '</div>' +
    '<h3 class="' + c.code + '" id="sigVerdict">' + esc(cd.verdict || c.title) + '</h3>' +
    '<div class="tags"><span>' + esc(cd.direction || '做多') + '</span><span>' + esc(cd.horizon || '日线') + '</span><span>证据 ' + st.lit + '/4</span><span class="eng-tag">引擎结果</span></div>' +
    '<p>' + esc(c.text) + '</p>' +
    '<div class="big3">' + (cd.lines || []).map(l => '<div><b>' + esc(l[0]) + '</b><span>' + esc(l[1]) + '</span><em>' + (l[2] == null ? '—' : fmtP(l[2])) + '</em></div>').join('') + '</div>' +
    (cd.entry_zone ? '<p class="zone">入场区间 ' + fmtP(cd.entry_zone[0]) + ' – ' + fmtP(cd.entry_zone[1]) + '（成本线到 +2%）</p>' : '') +
    '<p class="fine" id="sigFoot">' + esc(cd.footer || '') + '</p>';
  const tile = (cls, name, val, sub) => '<div class="tile ' + cls + '"><label>' + name + '</label><b>' + val + '</b><small>' + sub + '</small></div>';
  let h = tile('', '现价', fmtP(sg.price), st.asof + ' 收盘 · ' + fmtPct(st.chg_pct));
  h += sg.entry_ref != null ? tile('entry w2', '建仓区（成本线附近）', fmtP(sg.entry_ref), '成本线（' + st.levels.anchor_date + ' 地量日起算）· 距现价 ' + fmtPct(sg.entry_ref_pct))
    : tile('entry w2 off', '建仓区（成本线附近）', '—', '还没有地量日，成本线未起算');
  h += tile('stop', '止损', fmtP(sg.stop), '低点 ' + fmtP(st.low.price) + ' 下 3% · ' + fmtPct(sg.stop_pct));
  h += sg.target == null ? tile('target off', '第一目标', '—', '低点前没有可用的高点')
    : sg.target_usable ? tile('target', '第一目标', fmtP(sg.target), '低点前 20 根的最高价 · ' + fmtPct(sg.target_pct))
      : tile('target off', '第一目标', fmtP(sg.target), '不高于现价 2%，不作目标');
  h += sg.rr != null ? tile('', '盈亏比', sg.rr.toFixed(2) + ' : 1', '按当日收盘价估算') : tile('off', '盈亏比', '—', sg.target_usable ? '现价贴近止损，不可算' : '没有可用目标');
  $('#tiles').innerHTML = h;
  let bs = '';
  st.evidence.forEach(e => { bs += '<div class="row ' + (e.lit ? 'on' : '') + '"><i>' + e.n + '</i><div><b>' + esc(e.name) + '</b>：' + esc(e.text) + '</div></div>'; });
  bs += '<div class="kv"><span>高点 <b>' + fmtP(st.high.price) + '</b>（' + st.high.date + '）</span><span>低点 <b>' + fmtP(st.low.price) + '</b>（' + st.low.date + '）</span>' +
    '<span>高点到低点 <b>−' + st.drawdown_low + '%</b></span><span>收盘距高点 <b>−' + st.drawdown_close + '%</b></span>' +
    '<span>扇子中线 <b>' + fmtP(st.levels.fan05) + '</b></span><span>成本线 <b>' + fmtP(st.levels.avwap) + '</b></span></div>';
  $('#basisBody').innerHTML = bs;
  $('#notes').innerHTML = st.notes.map(n => '<div class="note">' + esc(n) + '</div>').join('');
  const list = $('#sigList'); list.innerHTML = '';
  $('#sigCount').textContent = '截至 ' + st.asof + ' 共 ' + st.signals.length + ' 次 · 点一下回放到那天';
  if (!st.signals.length) list.innerHTML = '<div class="empty">到这一天为止没有出现过四项齐的信号。</div>';
  st.signals.slice().reverse().forEach(q => {
    const b = document.createElement('button');
    b.innerHTML = '<span>' + q.sig + '</span><span class="muted">' + (WHY[q.why] || esc(q.why)) + ' · ' + q.bars + ' 根</span><span class="r ' + (q.r >= 0 ? 'pos' : 'neg') + '">' + (q.r >= 0 ? '+' : '') + q.r.toFixed(2) + 'R</span>';
    b.title = '信号日 ' + q.sig + '，次日开盘 ' + q.entry + ' 入场，止损 ' + q.stop + '，' + q.exit_d + ' 以 ' + q.exit + ' 出场';
    b.onclick = () => setReplay(true, q.sig);
    list.appendChild(b);
  });
  window.FEQuant.render();       // 选了后手模型时，信号卡和六格换成后手模型的
}

// ---------- 解说和图的联动 ----------
/* 点哪一问，图上对应的位置闪一下：第一问成交量副图（和地量日），第二问 MACD 副图和低点，第三问扇子中线，第四问成本线。只是高亮，不改任何数据。 */
/* 自由分析的卡片没有固定位置，就从它的文字里读：提到的日期圈出那根 K 线，提到的价位圈在那根 K 线的对应价格上，
   找不到对应 K 线的价位画成横线。只读文字、只画高亮，不改任何数据。 */
function parseCard(text) {
  const b = S.bars, year = Number(asofDate().slice(0, 4)), days = [], spans = [];
  const find = (y, mo, da) => { const i = S.idx[y + '-' + String(mo).padStart(2, '0') + '-' + String(da).padStart(2, '0')]; return i != null && i <= S.asof ? i : null; };
  const dre = /(\d{4})-(\d{1,2})-(\d{1,2})|(?<![\d.\-])(\d{1,2})-(\d{1,2})(?![\d.\-])|(\d{1,2})月(\d{1,2})日/g;
  let m;
  while ((m = dre.exec(text))) {
    let i = null;
    if (m[1]) i = find(+m[1], +m[2], +m[3]);
    else { const mo = +(m[4] || m[6]), da = +(m[5] || m[7]); if (mo >= 1 && mo <= 12 && da >= 1 && da <= 31) { i = find(year, mo, da); if (i == null && mo > Number(asofDate().slice(5, 7))) i = find(year - 1, mo, da); } }     // 月-日默认当年；比今天晚的月份才算去年
    spans.push([m.index, m.index + m[0].length]);
    if (i != null && days.indexOf(i) < 0) days.push(i);
  }
  // 价位：不带单位的数字（带 %、亿、万、根、天… 的不是价位），并且落在近一年的价格范围里
  const from = Math.max(0, S.asof - 250); let lo = Infinity, hi = -Infinity;
  for (let i = from; i <= S.asof; i++) { lo = Math.min(lo, b.l[i]); hi = Math.max(hi, b.h[i]); }
  const nums = [], nre = /(?<![\d.\-A-Za-z=])(\d+(?:\.\d+)?)(?![\d.]|\s*(?:%|％|亿|万|根|天|次|倍|日|月|年|张|股|个|步|项|R\b|X\b|周|分))/g;
  while ((m = nre.exec(text))) {
    const v = +m[1];
    if (spans.some(s => m.index >= s[0] && m.index < s[1]) || v < lo * 0.7 || v > hi * 1.3) continue;
    if (nums.indexOf(v) < 0) nums.push(v);
  }
  const eq = (a, v) => Math.abs(a - v) < 0.006, used = new Set(), rings = [], boxes = [], levels = [];
  const hit = (i, v) => ['h', 'l', 'c', 'o'].some(k => eq(b[k][i], v));
  days.forEach(i => {                                       // 先配这张卡片提到的日期
    let any = false;
    nums.forEach(v => { if (hit(i, v)) { rings.push({ i, p: v }); used.add(v); any = true; } });
    if (!any) boxes.push(i);
  });
  nums.forEach(v => {                                       // 没配上日期的价位：近 120 根里哪根 K 线正好是这个价，就圈哪根；都不是就画横线
    if (used.has(v)) return;
    for (let i = S.asof; i >= Math.max(0, S.asof - 120); i--) if (hit(i, v)) { rings.push({ i, p: v }); return; }
    levels.push(v);
  });
  return { rings: rings.slice(0, 16), boxes: boxes.slice(0, 12), levels: levels.slice(0, 6),
    vol: /成交|换手|放量|缩量|地量|量能|万股|亿股|的量|量在/.test(text), macd: /MACD|背离|DIF|DEA|红柱|绿柱/i.test(text) };
}
/* 点一张卡片：k = 0–3 是四要素里的某一项（有固定位置），k 为空是 Claude 自己选的观察点；text 是卡片上的文字。
   高亮一直留着，再点同一张或换一张才消失。 */
function flashStep(k, text, key, draw, auto) {
  const st = stateFresh() ? S.state : null; if (!st) return;
  if (!auto && key != null && S.flash && S.flash.key === key) { clearFlash(); return; }      // 再点一次：取消
  // 新格式：Claude 给了画图指令（后端已经把价位从数据里取好），就按指令画；老格式或模板版才从文字里读
  const marks = draw && draw.length && isDaily() ? resolveMarks(draw) : null;
  const free = !marks && text && isDaily() ? parseCard(text) : null;
  if (marks) { if (marks.vol && S.ind.vol) flashPane(ind.volPane); if (marks.macd && S.ind.macd) flashPane(ind.macdPane); }
  if (k === 0 || (free && free.vol)) { if (S.ind.vol) flashPane(ind.volPane); else if (k === 0) toast('成交量副图现在是关着的，在“指标”里打开就能看到。'); }
  if (k === 1 || (free && free.macd)) { if (S.ind.macd) flashPane(ind.macdPane); else if (k === 1) toast('MACD 副图现在是关着的，在“指标”里打开就能看到。'); }
  if (!isDaily()) { if (!auto) toast('图上的标记只在日线上画，切回日线再点。'); return; }
  const dr = st.draw;
  if (k === 2 && !dr.fan) toast('这一天扇子还画不了。');
  if (k === 3 && !dr.avwap) toast('还没有地量日，成本线没起算，图上没有可看的线。');
  const idxs = (free ? free.rings.map(r => r.i).concat(free.boxes) : []).concat(marks ? marks.idxs : []);
  if (k === 0 && dr.avwap) idxs.push(dr.avwap.anchor);
  if (k === 1) idxs.push(dr.low.i);
  if (k === 2 && dr.fan) idxs.push(dr.fan.lo);
  if (k === 3 && dr.avwap) idxs.push(dr.avwap.anchor);
  if (!auto && k == null && free && !idxs.length && !free.levels.length && !free.vol && !free.macd) toast('这张卡片没有提到具体的日期或价位，图上没有可以标的位置。');
  if (!auto && k == null && !free && !(marks && marks.items.length)) toast('这张卡片没有可以画在图上的标记。');
  if (idxs.length) {                        // 把图对准这一步讲的那一段：太远就拉开，挤在最近几根就拉近。原来的视野记下来，取消时恢复
    const want = Math.min.apply(null, idxs);
    if (S.spanHome == null) { noteSpan(); S.spanHome = S.span || 150; }
    focusView(clamp(S.asof - want + 14, 36, 400));
  }
  S.flash = { k, free, key, marks, t0: performance.now() };
  S.rev++;
}
function clearFlash() {      // 擦掉图上的标记，视野回到播放前的样子
  if (S.flash) { S.flash = null; S.rev++; }
  if (S.spanHome != null && S.bars) { const h = S.spanHome; S.spanHome = null; focusView(h); }
}
/* 把后端给的标记（日期 + 已经从数据里取好的价位）换成图上的 K 线序号。日期不在当前数据里的丢掉。 */
function resolveMarks(draw) {
  const items = [], idxs = []; let vol = false, macd = false;
  const at = d => { const i = S.idx[d]; return i != null && i <= S.asof ? i : null; };
  draw.forEach(m => {
    if (m.type === 'point') { const i = at(m.date); if (i != null) { items.push({ type: 'point', i, p: m.price, label: m.label }); idxs.push(i); } }
    else if (m.type === 'path') { const pts = (m.points || []).map(q => ({ i: at(q.date), p: q.price })).filter(q => q.i != null); if (pts.length >= 2) { items.push({ type: 'path', pts, label: m.label }); pts.forEach(q => idxs.push(q.i)); } }
    else if (m.type === 'level') items.push({ type: 'level', p: m.price, label: m.label });
    else if (m.type === 'zone') { const a = at(m.date_from), b = at(m.date_to); if (a != null && b != null) { items.push({ type: 'zone', a, b, top: m.top, bottom: m.bottom, label: m.label }); idxs.push(a, b); } }
    else if (m.type === 'volume' || m.type === 'macd') {
      const is = (m.dates || []).map(at).filter(i => i != null); if (!is.length) return;
      items.push({ type: m.type, is, label: m.label }); is.forEach(i => idxs.push(i)); if (m.type === 'volume') vol = true; else macd = true;
    }
  });
  return { items, idxs, vol, macd };
}
const MARK_MS = 520;        // 每个标记画出来用的时间；一个接一个
/* 一笔一笔画：第 n 个标记在 n×MARK_MS 之后开始出现。返回 0–1 的进度。 */
function markProgress(n) { const t = (performance.now() - S.flash.t0) / MARK_MS - n; return t <= 0 ? 0 : t >= 1 ? 1 : 1 - Math.pow(1 - t, 3); }
function drawMarks2() {
  const mk = S.flash && S.flash.marks; if (!mk) return;
  const Yc = C.hazard;
  mk.items.forEach((m, n) => {
    const g = markProgress(n); if (g <= 0) return;
    ctx.save(); ctx.globalAlpha = Math.min(1, g * 1.4);
    if (m.type === 'zone') {
      const x0 = X(m.a), x1 = X(m.b), y0 = Y(m.top), y1 = Y(m.bottom);
      if ([x0, x1, y0, y1].every(v => v != null)) {
        const w = (x1 - x0 + 12) * g;
        ctx.fillStyle = 'rgba(247,198,0,0.16)'; ctx.fillRect(x0 - 6, y0, w, y1 - y0);
        ctx.strokeStyle = Yc; ctx.lineWidth = 1.2; ctx.setLineDash([5, 4]); ctx.strokeRect(x0 - 6, y0, w, y1 - y0); ctx.setLineDash([]);
        if (g > 0.6) label((m.label ? m.label + ' ' : '') + fmtP(m.bottom) + '–' + fmtP(m.top), x0 - 4, y0 - 10, Yc);
      }
    } else if (m.type === 'level') {
      const y = Y(m.p);
      if (y != null) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(OV.w * g, y); ctx.strokeStyle = Yc; ctx.lineWidth = 1.6; ctx.setLineDash([8, 4]); ctx.stroke(); ctx.setLineDash([]);
        if (g > 0.6) label((m.label ? m.label + ' ' : '') + fmtP(m.p), OV.w - 6, y - 10, Yc, 'right');
      }
    } else if (m.type === 'path') {
      const P = m.pts.map(q => [X(q.i), Y(q.p)]); if (P.some(q => q[0] == null || q[1] == null)) { ctx.restore(); return; }
      let total = 0; const seg = []; for (let k = 1; k < P.length; k++) { const d = Math.hypot(P[k][0] - P[k - 1][0], P[k][1] - P[k - 1][1]); seg.push(d); total += d; }
      let left = total * g, end = P[0];
      ctx.beginPath(); ctx.moveTo(P[0][0], P[0][1]);
      for (let k = 1; k < P.length && left > 0; k++) {
        const f = Math.min(1, left / (seg[k - 1] || 1)); end = [P[k - 1][0] + (P[k][0] - P[k - 1][0]) * f, P[k - 1][1] + (P[k][1] - P[k - 1][1]) * f];
        ctx.lineTo(end[0], end[1]); left -= seg[k - 1];
      }
      ctx.strokeStyle = Yc; ctx.lineWidth = 2.6; ctx.shadowColor = Yc; ctx.shadowBlur = 8; ctx.stroke(); ctx.shadowBlur = 0;
      const shownN = Math.max(1, Math.round(1 + (P.length - 1) * g));
      P.slice(0, shownN).forEach((q, k) => { ctx.beginPath(); ctx.arc(q[0], q[1], 5, 0, Math.PI * 2); ctx.fillStyle = Yc; ctx.fill(); label(fmtP(m.pts[k].p), q[0], q[1] + (m.pts[0].p >= m.pts[m.pts.length - 1].p ? -14 : 14), Yc, 'center'); });
      if (g >= 1) {                         // 箭头和这条线的名字
        const a = P[P.length - 2], b = P[P.length - 1], ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
        ctx.beginPath(); ctx.moveTo(b[0] + 12 * Math.cos(ang), b[1] + 12 * Math.sin(ang));
        ctx.lineTo(b[0] - 7 * Math.cos(ang - 1.2), b[1] - 7 * Math.sin(ang - 1.2)); ctx.lineTo(b[0] - 7 * Math.cos(ang + 1.2), b[1] - 7 * Math.sin(ang + 1.2)); ctx.closePath(); ctx.fillStyle = Yc; ctx.fill();
        if (m.label) label(m.label, b[0] + 16, b[1], Yc);
      }
    } else if (m.type === 'point') {
      const x = X(m.i), y = Y(m.p);
      if (x != null && y != null) {
        ctx.beginPath(); ctx.arc(x, y, 22 - 12 * g, 0, Math.PI * 2); ctx.strokeStyle = Yc; ctx.lineWidth = 2.6; ctx.shadowColor = Yc; ctx.shadowBlur = 10; ctx.stroke(); ctx.shadowBlur = 0;
        if (g > 0.6) label((m.label ? m.label + ' ' : '') + fmtP(m.p), x + 14, y, Yc);
      }
    } else {                                // volume / macd：在主图上从那根 K 线往下拉一条引线，数值取自数据
      m.is.forEach(i => {
        const x = X(i), y0 = Y(S.bars.l[i]); if (x == null || y0 == null) return;
        ctx.beginPath(); ctx.moveTo(x, y0 + 4); ctx.lineTo(x, y0 + 4 + (OV.h - y0 - 4) * g); ctx.strokeStyle = Yc; ctx.lineWidth = 1.4; ctx.setLineDash([3, 3]); ctx.stroke(); ctx.setLineDash([]);
        if (g > 0.6) label(m.type === 'volume' ? '量 ' + fmtVol(S.bars.v[i]) : 'MACD ' + S.bars.hist[i].toFixed(2), x, OV.h - 12, Yc, 'center');
      });
      if (g > 0.6 && m.label) { const x = X(m.is[m.is.length - 1]); if (x != null) label(m.label, x + 30, OV.h - 30, Yc); }
    }
    ctx.restore();
  });
}
const flashAnimating = () => !!(S.flash && S.flash.marks && performance.now() - S.flash.t0 < MARK_MS * (S.flash.marks.items.length + 1));
function flashPane(p) {
  const pn = chart.panes()[p], h = pn && pn.getHTMLElement ? pn.getHTMLElement() : null; if (!h) return;
  const wrap = $('#chartwrap').getBoundingClientRect(), r = h.getBoundingClientRect(), d = document.createElement('div');
  d.className = 'pane-flash'; d.style.cssText = 'left:0;top:' + (r.top - wrap.top) + 'px;width:' + OV.w + 'px;height:' + r.height + 'px';
  $('#chartwrap').appendChild(d); setTimeout(() => d.remove(), 1700);
}
function drawFlash() {
  const fl = S.flash, st = S.state; if (!fl || !stateFresh() || !isDaily()) return;
  const dr = st.draw, ring = (i, p) => { const x = X(i), y = Y(p); if (x == null || y == null) return; ctx.beginPath(); ctx.arc(x, y, 13, 0, Math.PI * 2); ctx.strokeStyle = C.hazard; ctx.lineWidth = 3; ctx.stroke(); };
  ctx.save(); ctx.shadowColor = C.hazard; ctx.shadowBlur = 12;
  if (fl.k === 0 && dr.avwap) ring(dr.avwap.anchor, S.bars.l[dr.avwap.anchor]);
  if (fl.k === 1) ring(dr.low.i, dr.low.price);
  if (fl.k === 2 && dr.fan) {
    const x0 = X(dr.fan.hi), y0 = Y(dr.fan.H), x1 = X(dr.fan.lo), y1 = Y(dr.fan.levels['0.5'].at_lo);
    if ([x0, y0, x1, y1].every(v => v != null) && x1 > x0) { ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(OV.w, y0 + (y1 - y0) * (OV.w - x0) / (x1 - x0)); ctx.strokeStyle = C.hazard; ctx.lineWidth = 4; ctx.stroke(); }
  }
  if (fl.k === 3 && dr.avwap) drawPolyline(dr.avwap.anchor, dr.avwap.values, C.hazard, 4);
  ctx.restore();
  drawMarks2();
  const f = fl.free; if (!f) return;
  ctx.save();
  f.levels.forEach(v => {                   // 价位横线
    const y = Y(v); if (y == null) return;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(OV.w, y); ctx.strokeStyle = C.hazard; ctx.lineWidth = 1.5; ctx.setLineDash([7, 4]); ctx.stroke(); ctx.setLineDash([]);
    label(fmtP(v), OV.w - 6, y - 10, C.hazard, 'right');
  });
  const bw = Math.max(9, Math.abs((X(1) || 0) - (X(0) || 0)) * 0.9 + 6);
  f.boxes.forEach(i => {                    // 只提到日期：把整根 K 线框出来
    const x = X(i), y1 = Y(S.bars.h[i]), y2 = Y(S.bars.l[i]); if (x == null || y1 == null || y2 == null) return;
    ctx.strokeStyle = C.hazard; ctx.lineWidth = 2; ctx.strokeRect(x - bw / 2, y1 - 5, bw, y2 - y1 + 10);
    label(S.bars.d[i].slice(5), x, y1 - 16, C.hazard, 'center');
  });
  ctx.shadowColor = C.hazard; ctx.shadowBlur = 8;
  f.rings.forEach(r => {                    // 日期和价位都对得上：圈在那根 K 线的那个价格上
    const x = X(r.i), y = Y(r.p); if (x == null || y == null) return;
    ctx.beginPath(); ctx.arc(x, y, 9, 0, Math.PI * 2); ctx.strokeStyle = C.hazard; ctx.lineWidth = 2.5; ctx.stroke();
  });
  ctx.shadowBlur = 0;
  f.rings.forEach(r => { const x = X(r.i), y = Y(r.p); if (x != null && y != null) label(S.bars.d[r.i].slice(5) + ' ' + fmtP(r.p), x + 12, y, C.hazard); });
  ctx.restore();
}

function renderReplay() {
  const bar = $('#replaybar'); bar.hidden = !S.replayOn;
  if (!S.bars) return;
  $('#rpRange').value = S.asof; $('#rpDate').value = asofDate();
  $('#rpInfo').textContent = S.asof < lastIdx() ? '按 ' + asofDate() + ' 收盘重算 · 之后的数据不参与 · 第 ' + (S.asof + 1) + ' / ' + S.bars.d.length + ' 根' : '已是最新一根（' + asofDate() + '）';
}

async function refreshData() {
  const btn = $('#refreshBtn'); btn.disabled = true; btn.textContent = '刷新中…';
  try {
    const r = await api('/api/refresh', {});
    if (!r.ok) throw new Error(r.error);
    const n = Object.values(r.tickers).reduce((a, x) => a + x.appended.length, 0);
    S.meta = await api('/api/meta');
    await setTicker(S.ticker, S.replayOn && S.asof < lastIdx() ? asofDate() : null);
    const fr = S.bars.freshness;
    if (r.has_error) showRefresh(r);
    else if (fr && fr.stale) toast('数据来源还没有 ' + fr.expected + ' 的日线，这次没能更新到；定时任务会再试，也可以过一会儿再点。', true);
    else toast(n ? '已追加 ' + n + ' 行新日线。' : '没有新的日线，数据已是最新收盘。');
    if (n && !r.has_error) showRefresh(r);
  } catch (e) { toast('刷新失败：' + e.message, true); }
  btn.disabled = false; btn.textContent = '刷新数据';
}

// ---------- wiring ----------
function bind() {
  ov = $('#overlay'); ctx = ov.getContext('2d');
  ov.addEventListener('mousemove', e => { if (S.tool !== 'cursor') { S.cur = ptFromEvent(e); S.rev++; } });
  ov.addEventListener('mouseleave', () => { S.cur = null; S.rev++; });
  ov.addEventListener('click', onDrawClick);
  window.FEDraw.init({       // 左边工具栏：按钮、弹出菜单、新画线工具都在 draw.js
    S, store, X, Y, g: () => ctx, OV: () => OV, label, rgba, fmtP, toast, setTool, updateHint, addDrawing, deleteSelected, clearAll, zoomTo, askText, ptFromEvent,
    redraw: () => { S.rev++; }, reloadDrawings: () => { loadDrawings(); S.rev++; },
  });
  $('#autoBtn').onclick = () => { S.auto = !S.auto; store.set('auto', S.auto); renderTop(); syncPriceLines(); candle.applyOptions({ autoscaleInfoProvider: scaleProvider }); S.rev++; };
  $('#textBox').addEventListener('submit', e => {
    e.preventDefault();
    const v = $('#textInput').value.trim();
    if (S.pending && S.pending.textFor) window.FEDraw.finishText(v);
    else if (S.pending && S.pending.b) addDrawing({ type: 'arrow', a: S.pending.a, b: S.pending.b, text: v });
    $('#textBox').hidden = true;
    if (S.tool !== 'cursor') setTool('cursor');
  });
  $('#indBtn').onclick = e => { e.stopPropagation(); $('#indPop').hidden = !$('#indPop').hidden; };
  document.addEventListener('click', e => { if (!e.target.closest('#indMenu')) $('#indPop').hidden = true; });
  $$('#indPop input').forEach(c => {
    c.checked = !!S.ind[c.dataset.ind];
    c.onchange = () => { S.ind[c.dataset.ind] = c.checked; store.set('ind', S.ind); if (c.dataset.ind === 'live') { applyLive(); renderLegend(); pollLive(); } else if (/^(marks|pf|pfval)$/.test(c.dataset.ind)) { candle.applyOptions({ autoscaleInfoProvider: scaleProvider }); S.rev++; } else { noteSpan(); rebuildIndicators(); focusView(); renderLegend(); } };
  });
  $$('#viewSeg button').forEach(b => { b.onclick = () => setView(b.dataset.view); });
  $$('#tfSeg [data-tf]').forEach(b => { b.onclick = () => setTf(b.dataset.tf); });
  $('#dataDate').onclick = () => { const lrf = S.meta && S.meta.last_refresh_file; if (lrf) showRefreshFile(lrf); };
  $('#replayBtn').onclick = () => setReplay(!S.replayOn);
  $('#rpRange').addEventListener('input', e => setAsof(Number(e.target.value)));
  $('#rpPrev').onclick = () => setAsof(S.asof - 1);
  $('#rpNext').onclick = () => setAsof(S.asof + 1);
  $('#rpDate').addEventListener('change', e => { if (e.target.value) setAsof(indexAt(e.target.value)); });
  $('#rpExit').onclick = () => setReplay(false);
  $('#aiBtn').onclick = () => { S.sideOpen = !S.sideOpen; store.set('side', S.sideOpen); renderTop(); syncUrl(); };
  $('#sideClose').onclick = () => { S.sideOpen = false; store.set('side', false); renderTop(); syncUrl(); };
  window.FENarrate.init({
    api, toast, ticker: () => S.ticker, asof: () => asofDate(), ready: () => !!stateFresh(), flash: flashStep,
    model: () => window.FEQuant.model(), side: () => window.FEQuant.side(), query: () => window.FEQuant.query(), profile: () => window.FEQuant.profile(),
    saved: () => !!(stateFresh() && S.state.ai_saved && S.state.ai_saved.any),      // 任何一个组合今天分析过都算：切换模型或方向不清空
    gotoDay: (d, row) => {          // 解读存档里点一行：回到那一天，模型、方向、周期、级别也换成当时的
      if (row && row.model) window.FEQuant.goTo({ ticker: S.ticker, model: row.model, side: row.side || 'long', horizon: row.horizon || 20, tf: row.tf || 'D' }, d === S.bars.d[lastIdx()] && (row.tf || 'D') === S.tf ? null : d);
      else if (d === S.bars.d[lastIdx()]) setReplay(false); else setReplay(true, d);
    },
    fake: () => new URLSearchParams(location.search).get('aifake') === '1' || store.get('aifake', false),   // 测试开关：往 Claude 输出里塞假数字
    clearFlash,
    onReveal: n => { S.reveal = n; renderEvidence(); },      // 四问出到第几问，证据条就亮到第几条
  });
  window.FEQuant.init({
    api, toast, S, store, esc, fmtP, C, rgba, X, Y, g: () => ctx, OV: () => OV, label, drawPolyline, stateFresh: () => !!stateFresh(), isDaily, asofDate, ptFromEvent,
    redraw: () => { S.rev++; }, resized: () => { setTimeout(() => tick(true), 0); }, replayTo: d => setReplay(true, d), refreshState: () => queueState(true),
    setAuto: on => { if (S.auto !== on) { S.auto = on; store.set('auto', on); renderTop(); syncPriceLines(); S.rev++; } },
    modelChanged: () => { renderEvidence(); renderSide(); syncPriceLines(); S.rev++; window.FEChat.onState(); },
    narr: window.FENarrate, setTf, goto: goTo, openSide,
  });
  window.FENotes.init({
    api, toast, S, esc, X, Y, g: () => ctx, OV: () => OV, label, stateFresh: () => !!stateFresh(), isDaily, asofDate, ptFromEvent,
    redraw: () => { S.rev++; }, narr: window.FENarrate, aiEnabled: () => !!(S.meta && S.meta.ai && S.meta.ai.enabled),
    translateAuto: () => !!(S.meta && S.meta.ai && S.meta.ai.translate_auto),
  });
  window.FEChat.init({
    api, toast, esc, S, stateFresh: () => !!stateFresh(), asofDate, model: () => window.FEQuant.model(), profile: () => window.FEQuant.profile(), resized: () => { setTimeout(() => tick(true), 0); },
    setTab: n => window.FEQuant.setTab(n), tab: () => window.FEQuant.tab(), sideOpen: () => S.sideOpen,
    flashEvidence: k => flashStep(k, '', 'learn' + k, [], false),
    flashPane: which => { const on = which === 'vol' ? S.ind.vol : S.ind.macd; if (on) flashPane(which === 'vol' ? ind.volPane : ind.macdPane); else toast('这排副图现在是关着的，在“指标”里打开就能看到。'); },
    openSide,
    store, aiEnabled: () => !!(S.meta && S.meta.ai && S.meta.ai.enabled), aiReason: () => (S.meta && S.meta.ai && S.meta.ai.reason) || '',
  });
  $('#refreshBtn').onclick = refreshData;
  $('#modalClose').onclick = () => { $('#modal').hidden = true; };
  $('#modal').addEventListener('click', e => { if (e.target.id === 'modal') $('#modal').hidden = true; });
  $('#evidence').addEventListener('click', e => { if (e.target.closest('.ev-head')) { S.evFold = !S.evFold; store.set('evFold', S.evFold); $('#evidence').classList.toggle('fold', S.evFold); noteSpan(); focusView(); } });
  document.addEventListener('keydown', e => {
    const typing = /^(INPUT|TEXTAREA)$/.test(e.target.tagName) && e.target.type !== 'range';
    if (e.key === 'Escape') { $('#modal').hidden = true; if (S.tool !== 'cursor') setTool('cursor'); else if (S.selected >= 0) { S.selected = -1; S.rev++; } return; }
    if (typing) return;
    if ((e.key === 'Delete' || e.key === 'Backspace') && S.selected >= 0) { e.preventDefault(); deleteSelected(); }
    if (S.replayOn && e.target.type !== 'range') { if (e.key === 'ArrowLeft') { e.preventDefault(); setAsof(S.asof - 1); } if (e.key === 'ArrowRight') { e.preventDefault(); setAsof(S.asof + 1); } }
  });
}

async function boot() {
  const q = new URLSearchParams(location.search);
  if (q.get('tf') === 'W') S.tf = 'W';
  if (q.get('side') === '0') S.sideOpen = false; else if (q.get('side') === '1') S.sideOpen = true;
  if (q.get('pf') === '1') S.ind.pf = true;
  buildChart(); bind(); rebuildIndicators(); setView(q.get('view'));
  try {
    S.meta = await api('/api/meta');
    const names = S.meta.tickers.map(t => t.ticker), want = (q.get('t') || store.get('ticker', names[0]) || '').toUpperCase();
    await setTicker(names.indexOf(want) >= 0 ? want : names[0], q.get('asof'));
  } catch (e) { toast('加载失败：' + e.message, true); }
  await pollPortfolio(true);
  setInterval(pollPortfolio, ((S.meta && S.meta.portfolio_poll_s) || 15) * 1000);
  pollLive();
  requestAnimationFrame(loop);
  window.__fe = { S, chart: () => chart, tick: () => tick(true), setView, pollPortfolio, query: q, live: () => liveCandle,
    setLive: r => { S.liveFrozen = true; clearTimeout(liveTimer); S.live = r; applyLive(); renderLegend(); } };     // 调试和自检用
  if (q.get('narr')) {                    // ?narr=1：打开页面就播放解说（截图用）
    const skip = q.get('narr') === 'skip'; if (skip) document.body.classList.add('noanim');
    const fin = () => { if (window.FENarrate.current()) window.FENarrate.finish(); else setTimeout(fin, 100); };
    const pickN = q.get('pick');            // ?narr=skip&pick=2：再点开第 2 张卡片（截图用）
    const pk = () => { const li = document.querySelectorAll('#narr .n-step.show')[Number(pickN) - 1]; if (li) li.click(); else setTimeout(pk, 150); };
    const go = () => { if (stateFresh()) { window.FENarrate.run(); if (skip) fin(); if (pickN) setTimeout(pk, 400); } else setTimeout(go, 100); }; go();
  }
  if (q.get('livedemo') && S.bars) {      // ?livedemo=1：休市时预览盘中 K 线的样子（模拟数据，图例里写明“演示”）
    const d1 = new Date(S.bars.d[lastIdx()] + 'T12:00:00Z'); d1.setUTCDate(d1.getUTCDate() + 3);
    const c0 = S.bars.c[lastIdx()];
    window.__fe.setLive({ ok: true, ticker: S.ticker, status: 'regular', session_date: d1.toISOString().slice(0, 10), show_candle: true, demo: true,
      price: +(c0 * 1.012).toFixed(2), change_pct: 1.2, price_time: Date.now() / 1000, outside: null,
      bar: { o: +(c0 * 1.002).toFixed(2), h: +(c0 * 1.021).toFixed(2), l: +(c0 * 0.994).toFixed(2), c: +(c0 * 1.012).toFixed(2), v: S.bars.v[lastIdx()] * 0.6 } });
  }
  if (q.get('selftest')) { const sc = document.createElement('script'); sc.src = '/static/selftest.js'; document.body.appendChild(sc); }
}
boot();
})();
