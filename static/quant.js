/* 「AI 量化」面板（补充指令 3，照 TradingVane 第二段录屏）：模型下拉、四步进度、评分表盘、规则模型信号卡、顶栏清单、
   图上叠加（成本线、锚点、三冲、ABCD、建仓区、止损、目标）和逐条画出的结构线、编号图例、右键设成本锚点。
   全部数字来自 /api/quant（规则代码算的）。这里只负责显示，不算任何规则。文字用 textContent 或先转义再拼。 */
window.FEQuant = (() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const NUM = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮';
  const LINE_MS = 150;          // 划线那一步：每条间隔
  const COL = { res: '#f87171', sup: '#34d399', fib: '#8b93a5', tres: '#fb7185', tsup: '#2dd4bf', zone: '#34d399', stop: '#a78bfa', push: '#a78bfa', abcd: '#2dd4bf', anchor: '#60a5fa' };
  let c = null;
  const Q = { model: 'four', data: null, seq: 0, linesOn: false, shown: 1e9, running: false, off: {}, steps: null, total: null, animUntil: 0 };

  const esc = s => c.esc(s);
  const fresh = () => !!(Q.data && c.stateFresh() && Q.data.ticker === c.S.ticker && Q.data.asof === c.S.state.asof && Q.data.model_key === Q.model);
  const hideFour = () => Q.model === 'houshou';          // 选了后手模型：四证的证据条、自动画的扇子和成本线先收起来，免得两条成本线混在一起
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const num = n => (n && NUM[n - 1]) || '';
  const legendN = key => { const x = fresh() && Q.data.legend.find(l => l.key === key); return x ? x.n : 0; };

  function init(ctx) {
    c = ctx;
    Q.model = c.store.get('qmodel', 'four') === 'houshou' ? 'houshou' : 'four';
    Q.linesOn = !!c.store.get('qlines', false);
    Q.off = c.store.get('qoff', {}) || {};
    const forced = new URLSearchParams(location.search).get('model');
    if (forced === 'houshou' || forced === 'four') Q.model = forced;
    if (new URLSearchParams(location.search).get('qlines') === '1') Q.linesOn = true;
    const sel = $('#qModel');
    [['four', '四证·抄底 v1.0'], ['houshou', '后手·成本线回踩 v0.1']].forEach(m => { const o = document.createElement('option'); o.value = m[0]; o.textContent = m[1]; sel.appendChild(o); });
    sel.value = Q.model;
    sel.onchange = () => setModel(sel.value);
    $('#qRun').onclick = run;
    $('#qExtra').addEventListener('change', e => {
      const id = e.target && e.target.dataset && e.target.dataset.line;
      if (id == null) return;
      if (id === '*') { Q.linesOn = e.target.checked; c.store.set('qlines', Q.linesOn); Q.shown = 1e9; }
      else { Q.off[id] = !e.target.checked; c.store.set('qoff', Q.off); }
      c.redraw();
    });
    $('#qExtra').addEventListener('click', e => { const b = e.target.closest('[data-replay]'); if (b) c.replayTo(b.dataset.replay); });
    $('#chartwrap').addEventListener('contextmenu', onContext);
    document.addEventListener('click', e => { if (!e.target.closest('#qMenu')) $('#qMenu').hidden = true; });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') $('#qMenu').hidden = true; });
    render();
  }

  function setModel(m) {
    Q.model = m === 'houshou' ? 'houshou' : 'four';
    c.store.set('qmodel', Q.model); $('#qModel').value = Q.model;
    Q.data = null; Q.steps = null; Q.total = null;
    c.narr.reset();
    c.modelChanged();
    render(); fetch();
  }

  function reset() { Q.seq++; Q.data = null; Q.steps = null; Q.total = null; Q.running = false; Q.shown = 1e9; $('#qMenu').hidden = true; render(); }

  async function fetch() {
    if (!c.stateFresh()) return;
    const my = ++Q.seq;
    try {
      const r = await c.api('/api/quant?ticker=' + c.S.ticker + '&model=' + Q.model + '&asof=' + c.asofDate());
      if (my !== Q.seq) return;
      if (r.ok === false) throw new Error(r.error);
      Q.data = r; render(); c.redraw(); c.narr.restore();
    } catch (e) { if (my === Q.seq) c.toast('量化面板没取到：' + e.message, true); }
  }
  const onState = () => { if (!fresh()) fetch(); else render(); };

  // ---------- 侧栏 ----------
  function gauge(sc) {
    const th = Math.PI * (1 - (sc.total + 100) / 200), x = 100 + 62 * Math.cos(th), y = 104 - 62 * Math.sin(th);
    const cls = sc.total > 20 ? 'pos' : sc.total < -20 ? 'neg' : 'mid';
    let h = '<div class="q-gauge"><svg viewBox="0 0 200 118" aria-label="综合评分 ' + sc.total + '"><defs><linearGradient id="qg" x1="0" x2="1"><stop offset="0" stop-color="#ef4444"/><stop offset=".5" stop-color="#f5c542"/><stop offset="1" stop-color="#22c55e"/></linearGradient></defs>' +
      '<path d="M 20 104 A 80 80 0 0 1 180 104" fill="none" stroke="url(#qg)" stroke-width="9" stroke-linecap="round"/>' +
      '<line x1="100" y1="104" x2="' + x.toFixed(1) + '" y2="' + y.toFixed(1) + '" stroke="#e6e8ee" stroke-width="3" stroke-linecap="round"/><circle cx="100" cy="104" r="5" fill="#e6e8ee"/></svg>' +
      '<b class="q-total ' + cls + '" id="qTotal">' + (sc.total > 0 ? '+' : '') + sc.total + '</b><span class="q-lab">' + esc(sc.label) + '</span></div><div class="q-parts">';
    sc.parts.forEach(p => {
      const w = Math.min(50, Math.abs(p.v) / 2);
      h += '<div class="q-part"><label>' + esc(p.name) + '</label><div class="q-track"><i class="' + (p.v < 0 ? 'neg' : 'pos') + '" style="width:' + w + '%;' + (p.v < 0 ? 'right:50%' : 'left:50%') + '"></i></div><em class="' + (p.v < 0 ? 'neg' : p.v > 0 ? 'pos' : '') + '">' +
        (p.v > 0 ? '+' : '') + p.v + '</em><small>' + esc(p.why) + '</small></div>';
    });
    return h + '</div><p class="fine q-note">' + esc(sc.note) + '</p>';
  }

  function signalCard(d) {
    const cd = d.card, s = d.signal;
    const cls = s.verdict === '下后手' ? 'all4' : /不追|出货|失效/.test(s.verdict) ? 'missing' : 'not_armed';
    $('#sigCard').innerHTML = '<div class="eng">◎ ' + esc(cd.model) + ' · ' + esc(d.ticker) + ' ' + d.asof + '</div>' +
      '<h3 class="' + cls + '" id="sigVerdict">' + esc(cd.verdict) + '</h3>' +
      '<div class="tags">' + cd.tags.map((t, k) => '<span' + (t === '引擎结果' ? ' class="eng-tag"' : '') + '>' + esc(t) + '</span>').join('') +
      (s.list ? '<span>' + (s.list === 'chase' ? '不追清单 ' : '后手清单 ') + s.checks.filter(x => x.ok).length + '/' + s.checks.length + '</span>' : '') + '</div>' +
      '<p>' + esc(cd.text) + '</p>' +
      (s.checks.length ? '<div class="q-checks">' + s.checks.map(x => '<div class="' + (x.ok ? 'on' : '') + '"><i>' + (x.ok ? '✓' : '·') + '</i><div><b>' + esc(x.name) + '</b><span>' + esc(x.why) + '</span></div></div>').join('') + '</div>' : '') +
      '<p class="fine" id="sigFoot">' + esc(cd.footer) + '</p>';
    $('#tiles').innerHTML = cd.cells.map(x => '<div class="tile ' + (x.tone || '') + (x.v === '—' ? ' off' : '') + '" data-k="' + x.k + '"><label>' + esc(x.name) + '</label><b>' + esc(x.v) + '</b><small>' + esc(x.sub || '') + '</small></div>').join('');
  }

  function bar(d) {
    const el = $('#qBar'), s = d.signal;
    let h = '<b>后手战法</b><i class="sep"></i>';
    if (s.list) {
      h += s.checks.map(x => '<span class="ck' + (x.ok ? ' on' : '') + '" title="' + esc(x.why) + '">' + esc(x.name) + '<u>' + (x.ok ? '✓' : '') + '</u></span>').join('<i class="plus">+</i>');
      h += '<i class="sep"></i><em class="' + (s.verdict === '下后手' ? 'go' : /不追|出货/.test(s.verdict) ? 'no' : '') + '">' + esc(s.verdict === '下后手' ? '下后手（未回测）' : s.verdict_text) + '</em>';
    } else {
      h += '<span class="ck">' + esc(s.phase === '已失效' ? '结构已失效' : '没有三冲结构') + '</span><i class="sep"></i><em>清单用不上</em>';
    }
    el.innerHTML = h; el.hidden = false; el.dataset.phase = s.phase;
  }

  function extra(d) {
    const s = d.signal;
    let h = '';
    if (s.next_needs && s.next_needs.length) h += '<div class="card thin"><div class="w-title">下一根 K 线要看什么（清单的门槛）</div><ul class="q-needs">' + s.next_needs.map(x => '<li>' + esc(x) + '</li>').join('') + '</ul></div>';
    if (d.lines.length) {
      h += '<details class="card thin" id="qLines"' + (Q.linesOn ? ' open' : '') + '><summary>图上划线 ' + d.lines.length + ' 条 <label class="q-all"><input type="checkbox" data-line="*"' + (Q.linesOn ? ' checked' : '') + '> 显示</label></summary><div class="q-lines">' +
        d.lines.map(x => '<label><input type="checkbox" data-line="' + esc(x.id) + '"' + (Q.off[x.id] ? '' : ' checked') + '><span class="sw" style="background:' + (COL[x.style] || c.C[x.style] || '#8b93a5') + '"></span>' +
          esc(num(x.n) + ' ' + x.label) + (x.price != null ? ' · ' + c.fmtP(x.price) : '') + (x.kind === 'auto' ? '（自动画）' : '') + '</label>').join('') + '</div></details>';
    }
    if (d.model_key === 'houshou') {
      const hi = d.history, st = hi.stats || {};
      const OUT = { target: '先到目标', stop: '先破止损', none: '都没到', open: '未了结' };
      h += '<details class="card thin" id="qHist"><summary>历史触发 · ' + esc(hi.note) + '</summary>' +
        (hi.rows.length ? '<table class="q-tab"><tr><th>日期</th><th>建仓中值</th><th>止损</th><th>目标</th><th>之后 ' + hi.hold + ' 根</th></tr>' +
          hi.rows.slice().reverse().map(r => '<tr><td><button data-replay="' + r.date + '">' + r.date + '</button></td><td>' + c.fmtP(r.mid) + '</td><td>' + c.fmtP(r.stop) + '</td><td>' + c.fmtP(r.t1) + '</td><td class="' + r.outcome + '">' + OUT[r.outcome] + (r.bars ? ' · ' + r.bars + ' 根' : '') + '</td></tr>').join('') + '</table>'
          : '<p class="fine">到这一天为止，这只标的的日线上三项从没有同时成立过。</p>') +
        '<p class="fine" id="qStats">回落阶段共 ' + (st.fall || 0) + ' 根 K 线（全部 ' + (st.bars || 0) + ' 根）：回到成本线 ' + (st.B1 || 0) + ' 根，AB=CD ' + (st.B2 || 0) + ' 根，缩量刺破收回 ' + (st.B3 || 0) + ' 根，至少两项同时成立 ' + (st.two_of_three || 0) + ' 根。能看出清单卡在哪一项。</p></details>';
      const P = s.params, pv = P.video, pe = P.est, en = s.est_note || {};
      h += '<details class="card thin" id="qParams"><summary>模型参数（视频原话 4 个，其余全部【估算】）</summary><div class="q-params"><b>视频里说了的</b>' +
        '<span>离成本线超过 ' + pv.far * 100 + '% 不追</span><span>两段跌幅相差不到 ' + pv.abcd_tol * 100 + '%</span><span>量缩到下跌段的 ' + pv.dry * 100 + '% 以下</span><span>止损在 D 点下方 ' + pv.stop * 100 + '%</span>' +
        '<b>视频没给、这里自己定的【估算】</b>' + Object.keys(pe).map(k => '<span>' + esc(en[k] || k) + '：' + pe[k] + '</span>').join('') + '</div></details>';
    }
    h += '<div class="q-explain">' + d.explain.map(x => '<p>' + esc(x) + '</p>').join('') + '</div>';
    $('#qExtra').innerHTML = h;
  }

  function legend(d) {
    const el = $('#qLegend');
    if (!d.legend.length || !c.isDaily()) { el.hidden = true; return; }
    const open = c.store.get('qlegend', true);
    el.innerHTML = '<details' + (open ? ' open' : '') + '><summary>图例 · 图上每种标记是什么（' + d.legend.length + '）</summary><ol>' +
      d.legend.map(l => '<li><i>' + num(l.n) + '</i>' + esc(l.text) + '</li>').join('') + '</ol></details>';
    el.querySelector('details').addEventListener('toggle', e => { c.store.set('qlegend', e.target.open); c.resized(); });
    el.hidden = false;
  }

  function stepsCard() {
    const el = $('#qSteps');
    if (!Q.steps) { el.hidden = true; return; }
    el.hidden = false;
    const sec = ms => ms == null ? '' : ms < 950 ? (ms / 1000).toFixed(ms < 95 ? 2 : 1) + ' 秒' : Math.round(ms / 1000) + ' 秒';
    el.innerHTML = '<div class="q-steps-head"><span class="' + (Q.running ? 'spin' : 'done') + '"></span><b>' + (Q.running ? '正在分析' : '分析完成') + '</b><span class="spacer"></span><span class="muted">' + sec(Q.total) + '</span></div><div class="q-steps">' +
      Q.steps.map(s => '<div class="' + s.state + '"><i>' + (s.state === 'done' ? '✓' : '') + '</i><div><b>' + esc(s.name) + '</b><small>' + esc(s.note || '') + '</small></div><em>' + sec(s.ms) + '</em></div>').join('') + '</div>';
  }

  function render() {
    if (!c) return;
    const ok = fresh(), d = Q.data;
    $('#qRun').disabled = !c.stateFresh() || Q.running;
    $('#qRun').textContent = Q.running ? '正在分析…' : 'AI 分析当前图表';
    $('#evidence').hidden = hideFour();
    stepsCard();
    if (!ok) {
      $('#qBar').hidden = true; $('#qLegend').hidden = true; $('#qLabel').textContent = '';
      if (hideFour() && c.stateFresh()) { $('#sigCard').innerHTML = '<div class="eng">计算中…</div>'; $('#tiles').innerHTML = ''; }
      if (!c.stateFresh()) { $('#qScore').innerHTML = '<div class="muted small">计算中…</div>'; $('#qExtra').innerHTML = ''; }
      return;
    }
    $('#qPos').innerHTML = '持仓 <b>' + esc(d.position.text) + '</b>';
    $('#qLabel').textContent = d.score.label;
    $('#qLabel').className = 'qtag ' + (d.score.total > 20 ? 'pos' : d.score.total < -20 ? 'neg' : '');
    $('#qScore').innerHTML = gauge(d.score);
    if (d.model_key === 'houshou') { signalCard(d); bar(d); } else $('#qBar').hidden = true;
    extra(d); legend(d);
  }

  // ---------- 「AI 分析当前图表」：四步 ----------
  async function run() {
    if (Q.running || !c.stateFresh()) return;
    Q.running = true; Q.total = null;
    const tAll = performance.now(), names = ['识别图表结构', '计算规则信号', '在图上划线', 'AI 深度解读'];
    Q.steps = names.map((n, k) => ({ name: n, state: k === 0 ? 'run' : 'wait', note: '', ms: null }));
    const tick = setInterval(() => { Q.total = performance.now() - tAll; stepsCard(); }, 200);
    const set = (k, o) => { Object.assign(Q.steps[k], o); if (Q.steps[k + 1] && o.state === 'done') Q.steps[k + 1].state = 'run'; Q.total = performance.now() - tAll; stepsCard(); };
    Q.linesOn = true; c.store.set('qlines', true); Q.shown = 0; c.redraw();
    render();
    try {
      await fetch();
      if (!fresh()) throw new Error('这一天的结果没取到');
      const d = Q.data, my = Q.seq;
      await sleep(260); set(0, { state: 'done', note: d.steps[0].note, ms: d.steps[0].ms });
      await sleep(260); set(1, { state: 'done', note: d.steps[1].note, ms: d.steps[1].ms });
      const t3 = performance.now(), ls = d.lines.filter(x => !Q.off[x.id]);
      Q.steps[2].note = d.steps[2].note; stepsCard();
      for (let k = 1; k <= ls.length && my === Q.seq; k++) {
        Q.shown = k; Q.animUntil = performance.now() + LINE_MS;
        if (ls[k - 1].kind === 'auto') c.setAuto(true);      // 四证的扇线、成本线、止损线就是“自动画”那一层
        c.redraw(); await sleep(LINE_MS);
      }
      Q.shown = 1e9;
      set(2, { state: 'done', ms: performance.now() - t3 });
      const t4 = performance.now();
      Q.steps[3].note = '模板或保存过的解读，不计费'; stepsCard();
      await c.narr.run();
      const cur = c.narr.current();
      set(3, { state: 'done', ms: performance.now() - t4, note: cur ? (cur.source === 'claude' ? 'Claude · 保存过的那一版，不再计费' : '模板版 · 要 Claude 解读点下面的按钮') : '没取到' });
    } catch (e) { c.toast('分析没跑完：' + e.message, true); }
    clearInterval(tick);
    Q.running = false; Q.shown = 1e9; Q.total = performance.now() - tAll;
    render(); c.redraw();
  }

  // ---------- 图上 ----------
  function pill(text, y, color) { c.label(text, c.OV().w - 6, y, color, 'right'); }
  function hline(g, x0, price, color, dash, width) {
    const y = c.Y(price); if (y == null) return null;
    g.beginPath(); g.moveTo(Math.max(0, x0), y); g.lineTo(c.OV().w, y); g.strokeStyle = color; g.lineWidth = width || 1.2; g.setLineDash(dash || []); g.stroke(); g.setLineDash([]);
    return y;
  }
  function badge(g, x, y, text, color, r) {
    r = r || 9;
    g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fillStyle = color; g.fill();
    g.fillStyle = '#0b0e14'; g.font = '700 11px -apple-system,sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, x, y + 0.5);
  }
  const I = date => c.S.idx[date];

  function drawOverlay(g, o) {
    const S = c.S, a = I(o.anchor.date), W = c.OV().w, H = c.OV().h, v = o.avwap.v, sd = o.avwap.sd;
    if (a == null) return;
    // 成本线两边的带子（±1σ）
    g.beginPath(); let pen = false;
    for (let k = 0; k < v.length; k++) { const x = c.X(a + k), y = v[k] == null ? null : c.Y(v[k] + sd[k]); if (x == null || y == null) continue; if (pen) g.lineTo(x, y); else g.moveTo(x, y); pen = true; }
    for (let k = v.length - 1; k >= 0; k--) { const x = c.X(a + k), y = v[k] == null ? null : c.Y(v[k] - sd[k]); if (x == null || y == null) continue; g.lineTo(x, y); }
    if (pen) { g.closePath(); g.fillStyle = c.rgba(c.C.vwap, 0.09); g.fill(); }
    c.drawPolyline(a, v, c.C.vwap, 2);
    const xe = c.X(S.asof), ye = c.Y(v[v.length - 1]);
    if (xe != null && ye != null) c.label(num(legendN('avwap')) + ' 成本线 ' + c.fmtP(v[v.length - 1]), xe + 8, ye - 12, c.C.vwap);
    if (xe != null && ye != null && sd[sd.length - 1]) c.label(num(legendN('band')) + ' ±1σ', xe + 8, c.Y(v[v.length - 1] + sd[sd.length - 1]) - 2, c.rgba(c.C.vwap, 0.8));
    // 成本锚点竖条
    const xa = c.X(a);
    if (xa != null) {
      g.fillStyle = c.rgba(COL.anchor, 0.22); g.fillRect(xa - 4, 0, 8, H);
      c.label(num(legendN('anchor')) + ' 成本锚点·' + (o.anchor.by === 'manual' ? '手动' : '自动'), xa + 8, 30, COL.anchor);
    }
    // 三冲：编号气泡，气泡下写这一冲的兵力相当于第一冲的百分之几
    const ps = o.pushes || [], three = ps.some(p => p.slot);        // 够三冲时只给最后三冲编号 1、2、3，更早的冲只留一个小点
    let first = true;
    ps.forEach(p => {
      const x = c.X(I(p.date)), y = c.Y(p.price); if (x == null || y == null) return;
      if (three && !p.slot) { g.beginPath(); g.arc(x, y - 8, 3, 0, Math.PI * 2); g.fillStyle = c.rgba(COL.push, 0.5); g.fill(); return; }
      badge(g, x, y - 16, String(three ? p.slot : p.n), p.pending ? c.rgba(COL.push, 0.55) : COL.push);
      if (p.force_pct != null) c.label('兵力 ' + p.force_pct + '%', x, y - 36, COL.push, 'center');
      if (first) { first = false; c.label(num(legendN('push')), x - 22, y - 16, COL.push, 'center'); }
    });
    // A B C D：两段回落
    const ab = o.abcd;
    if (ab) {
      const P = ['A', 'B', 'C', 'D'].map(k => ab[k] && { k, x: c.X(I(ab[k].date)), y: c.Y(ab[k].price), soft: ab[k].provisional }).filter(p => p && p.x != null && p.y != null);
      for (let k = 1; k < P.length; k++) {
        const leg = P[k - 1].k + P[k].k, eq = leg === 'AB' || leg === 'CD';
        g.beginPath(); g.moveTo(P[k - 1].x, P[k - 1].y); g.lineTo(P[k].x, P[k].y); g.strokeStyle = COL.abcd; g.lineWidth = eq ? 2 : 1; g.setLineDash(eq ? [6, 4] : []); g.stroke(); g.setLineDash([]);
        const t = leg === 'AB' && ab.ab_pct != null ? '−' + ab.ab_pct + '%' : leg === 'CD' && ab.cd_pct != null ? '−' + ab.cd_pct + '%（是第一段的 ' + (ab.cd_pct / ab.ab_pct).toFixed(2) + ' 倍）' : '';
        if (t) c.label(t, (P[k - 1].x + P[k].x) / 2 + 6, (P[k - 1].y + P[k].y) / 2, COL.abcd);
      }
      P.forEach(p => badge(g, p.x + (p.k === 'A' ? 20 : 0), p.y + (p.k === 'A' ? -16 : p.k === 'C' ? -14 : 14), p.k, p.soft ? c.rgba(COL.abcd, 0.5) : COL.abcd, 8));     // A 和第三冲是同一根，往右让一格
      if (P.length > 1) c.label(num(legendN('abcd')), P[1].x + 16, P[1].y + 14, COL.abcd);
    }
    // 三项齐了才有：建仓区、目标、止损，以及右侧的盈亏示意框（照视频：上面是到目标的空间，下面是到止损的空间）
    if (o.zone) {
      const xd = ab && ab.D ? c.X(I(ab.D.date)) : xe, y1 = c.Y(o.zone[1]), y0 = c.Y(o.zone[0]);
      if (xd != null && y1 != null && y0 != null) {
        g.fillStyle = c.rgba(COL.zone, 0.18); g.fillRect(xd, y1, W - xd, Math.max(2, y0 - y1));
        c.label(num(legendN('zone')) + ' 建仓区 ' + c.fmtP(o.zone[0]) + ' – ' + c.fmtP(o.zone[1]), xd + 6, y1 - 10, COL.zone);
      }
      const mid = (o.zone[0] + o.zone[1]) / 2, ym = c.Y(mid), yt = c.Y(o.target), xb = xe != null ? xe + 14 : null;
      if (xb != null && ym != null && yt != null) { g.fillStyle = c.rgba(c.C.up, 0.13); g.fillRect(xb, yt, W - xb, ym - yt); }
      if (o.target != null && xd != null) { hline(g, xd, o.target, c.C.target, [2, 4], 1.4); c.label(num(legendN('target')) + ' 目标 ' + c.fmtP(o.target) + '（第三冲高点）', xd + 6, c.Y(o.target) - 10, c.C.target); }
      if (o.stop != null && xd != null) {
        const ys = c.Y(o.stop);
        if (xb != null && ym != null && ys != null) { g.fillStyle = c.rgba(c.C.down, 0.13); g.fillRect(xb, ym, W - xb, ys - ym); }
        hline(g, xd, o.stop, c.C.stop, [6, 4], 1.4); c.label(num(legendN('stop')) + ' 止损 ' + c.fmtP(o.stop) + '（D 点下 2% · 手动止损）', xd + 6, ys + 12, c.C.stop);
      }
    }
  }

  function drawLines(g, lines) {
    const W = c.OV().w;
    lines.filter(x => !Q.off[x.id]).slice(0, Q.shown).forEach(x => {
      const col = COL[x.style] || '#8b93a5', tag = (num(x.n) ? num(x.n) + ' ' : '');
      if (x.kind === 'level') {
        const x0 = x.span ? c.X(I(x.span.low.date)) : 0;
        const y = hline(g, x0 == null ? 0 : x0, x.price, x.style === 'fib' ? c.rgba(col, 0.55) : col, x.style === 'fib' ? [2, 4] : [5, 4], x.style === 'fib' ? 1 : 1.3);
        if (y != null) pill(tag + x.label + ' · ' + c.fmtP(x.price), y, col);
      } else if (x.kind === 'trend') {
        const i1 = I(x.p1.date), i2 = I(x.p2.date), x1 = c.X(i1), y1 = c.Y(x.p1.price), x2 = c.X(i2), y2 = c.Y(x.p2.price);
        if (x1 == null || x2 == null || y1 == null || y2 == null || x2 === x1) return;
        const yr = y1 + (y2 - y1) * (W - x1) / (x2 - x1);
        g.beginPath(); g.moveTo(x1, y1); g.lineTo(W, yr); g.strokeStyle = col; g.lineWidth = 1.3; g.stroke();
        c.label(tag + x.label, x2 + 10, y2 + (x.style === 'tres' ? -12 : 12), col);
      }
    });
  }

  function draw() {
    if (!fresh() || !c.isDaily()) return;
    const g = c.g(), d = Q.data;
    if (d.overlay && d.model_key === 'houshou') drawOverlay(g, d.overlay);
    if (Q.linesOn) drawLines(g, d.lines);
  }

  // ---------- 右键：手动成本锚点（只在后手模型下）----------
  function onContext(e) {
    if (!c.stateFresh() || !c.isDaily()) return;
    e.preventDefault();
    const pt = c.ptFromEvent(e), i = Math.max(0, Math.min(c.S.asof, pt.li)), date = c.S.bars.d[i], m = $('#qMenu');
    const manual = fresh() && Q.data.signal.anchor && Q.data.signal.anchor.by === 'manual';
    m.textContent = '';
    const add = (text, fn, off) => { const b = document.createElement('button'); b.textContent = text; b.disabled = !!off; b.onclick = () => { m.hidden = true; fn(); }; m.appendChild(b); };
    if (window.FENotes) window.FENotes.menu(date, add);        // 写备注、联网查这一天
    if (Q.model === 'houshou') {
      add('设为成本锚点（' + date + '）', () => anchor(date));
      add('清除手动锚点，回到自动', () => anchor(null), !manual);
    }
    const r = $('#chartwrap').getBoundingClientRect();
    m.style.left = Math.min(e.clientX - r.left, r.width - 220) + 'px'; m.style.top = Math.min(e.clientY - r.top, r.height - 80) + 'px';
    m.hidden = false;
  }
  async function anchor(date) {
    try {
      const r = await c.api('/api/quant/anchor', { ticker: c.S.ticker, date });
      if (r.ok === false) throw new Error(r.error);
      c.toast(date ? '成本锚点设在 ' + date + '（手动）。' : '已清除手动锚点，回到自动。');
      c.narr.reset(); Q.data = null; fetch(); c.refreshState();
    } catch (e) { c.toast('锚点没改成：' + e.message, true); }
  }

  return { init, reset, onState, render, draw, run, setModel, model: () => Q.model, hideFour, fresh, data: () => Q.data, animating: () => Q.running || performance.now() < Q.animUntil, state: () => Q, setAnchor: anchor };
})();
