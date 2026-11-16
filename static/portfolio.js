/* 「持仓」页。只把 /api/portfolio 给的内容画出来：文件里没有的字段显示“—”，不补不猜。
   所有文字先转义再放进页面（持仓文件是另一个进程写的）。 */
window.FEPortfolio = (() => {
  'use strict';
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const isNum = x => typeof x === 'number' && isFinite(x);
  const money = (x, d = 2) => isNum(x) ? x.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }) : '—';
  const qty = x => isNum(x) ? x.toLocaleString('en-US', { maximumFractionDigits: 4 }) : '—';
  const px = x => isNum(x) ? x.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 3 }) : '—';
  const signed = x => isNum(x) ? (x > 0 ? '+' : x < 0 ? '−' : '') + Math.abs(x).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—';
  const EST = '<span class="est">估算</span>';
  const TYPE = { stock: '正股', call: '看涨期权', put: '看跌期权', perp: '永续合约' };
  const SIDE = { safe: '安全', risky: '冒险', middle: '中间' };
  const DIR = { short: '空', long: '多' };
  const LINE = {
    bp_zero_est: '归零线', bp_zero_after_1_more_buyback_est: '再买回 1 张 put 后的归零线', minus10pct_buffer: '−10% 缓冲线',
  };
  const VAL = { V4_base: 'V4 Base', sotp: 'SOTP', V4_bull: 'V4 Bull', mos30: '30% 安全边际价' };
  function lineName(key) {     // 文件里新出现的情景线（如 bp_zero_if_xxx_est）按字段名读出来，不用逐个写死
    const m = /^bp_zero_if_(.+?)(_est)?$/.exec(key);
    return m ? '归零线（情景：' + m[1].replace(/_/g, ' ') + '）' : key.replace(/_est$/, '').replace(/_/g, ' ');
  }
  let snapName = null, snapCache = {}, snapVersion = null, lastHtml = '', opts = {};

  function asofText(s) {
    const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(String(s || ''));
    return m ? m[1] + ' ' + m[2] + ' 台北' : (s ? String(s) : '—');
  }
  function ageText(h) { return !isNum(h) ? '' : h < 48 ? Math.round(h) + ' 小时' : Math.round(h / 24) + ' 天'; }

  function mdToHtml(text) {       // 够用的 Markdown：标题、列表、段落、粗体、行内代码。原文一字不改。
    const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>').replace(/【估算[^】]*】/g, m => '<span class="est">' + m + '</span>');
    let html = '', inList = false;
    String(text).split(/\r?\n/).forEach(line => {
      const h = /^(#{1,6})\s+(.*)$/.exec(line), li = /^\s*[-*]\s+(.*)$/.exec(line);
      if (li) { if (!inList) { html += '<ul>'; inList = true; } html += '<li>' + inline(li[1]) + '</li>'; return; }
      if (inList) { html += '</ul>'; inList = false; }
      if (h) html += '<h' + Math.min(6, h[1].length + 2) + '>' + inline(h[2]) + '</h' + Math.min(6, h[1].length + 2) + '>';
      else if (line.trim()) html += '<p>' + inline(line) + '</p>';
    });
    return html + (inList ? '</ul>' : '');
  }

  function checkCell(pf, t) {
    if (!t) return '<td class="chk none" title="没有这只标的的 K 线数据，做不了四证检查">—</td>';
    const c = (pf.checks || {})[t];
    if (!c) return '<td class="chk none" title="四证检查没有返回结果">' + esc(t) + ' —</td>';
    const txt = c.armed ? c.score + '/4' : '未触发';
    return '<td class="chk"><button class="chk-btn' + (c.armed && c.score === 4 ? ' full' : '') + '" data-goto="' + esc(t) + '" data-score="' + esc(txt) + '" title="' +
      esc(c.state + ' · ' + c.asof + ' 收盘 ' + c.close + (c.low_stale ? ' · 低点偏旧' : '') + ' · 点一下看图') + '"><b>' + esc(t) + '</b> ' + esc(txt) + '</button></td>';
  }

  function account(pf) {
    const a = pf.account;
    if (!a) return '<div class="pf-none">文件里没有账户字段。</div>';
    const orders = Array.isArray(a.open_orders) ? a.open_orders : null;
    const tile = (k, name, val, sub) => '<div class="pf-tile" data-k="' + k + '"><label>' + name + '</label><b>' + val + '</b>' + (sub ? '<small>' + sub + '</small>' : '') + '</div>';
    let h = '<div class="pf-tiles">' + tile('nav', '净值', money(a.nav), esc(a.broker || '')) + tile('cash', '现金', money(a.cash)) +
      tile('buying_power', '购买力', money(a.buying_power)) + tile('option_margin', '期权保证金', money(a.option_margin)) +
      tile('open_orders', '当前挂单', orders ? orders.length + ' 张' : '—') +
      (a.loan_value !== undefined ? tile('loan_value', '存仓可按价值', money(a.loan_value)) : '') +
      (pf.combined_nav_usd !== undefined ? tile('combined', '合并净值（含其它账户）', money(pf.combined_nav_usd, 0)) : '') + '</div>';
    if (orders && orders.length) {
      h += '<ul class="pf-orders">' + orders.map(o => (o && typeof o === 'object')
        ? '<li>' + esc({ sell: '卖出', buy: '买入' }[o.side] || o.side || '') + ' ' + esc(o.symbol || '—') + ' · ' + qty(o.qty) + ' 张/股 · 限价 ' + px(o.limit) + (o.status ? ' · ' + esc(o.status) : '') + '</li>'
        : '<li>' + esc(o) + '</li>').join('') + '</ul>';
    }
    return h;
  }

  function barbell(pf) {
    const b = pf.barbell;
    if (!b) return '<div class="pf-none">文件里没有杠铃字段。</div>';
    const mid = isNum(b.middle_obligation_x_nav) ? b.middle_obligation_x_nav * 100 : null;
    const segs = [['safe', '安全侧', b.safe_pct], ['risky', '冒险侧', b.risky_pct], ['middle', '中间（短 put 义务）', mid]].filter(s => isNum(s[2]) && s[2] > 0);
    const total = segs.reduce((a, s) => a + s[2], 0);
    let h = '<div class="pf-bar" role="img" aria-label="杠铃分布，按净值的百分比">';
    segs.forEach(s => { h += '<div class="seg-' + s[0] + '" style="width:' + (s[2] / total * 100).toFixed(2) + '%" title="' + s[1] + ' ' + Math.round(s[2]) + '% 净值"><span>' + s[1] + ' ' + Math.round(s[2]) + '%</span></div>'; });
    if (total > 100) h += '<i class="one-nav" style="left:' + (100 / total * 100).toFixed(2) + '%"><em>1 倍净值</em></i>';
    h += '</div><div class="pf-bar-legend">' +
      '<span data-k="safe_pct"><i class="sw seg-safe"></i>安全侧 <b>' + (isNum(b.safe_pct) ? b.safe_pct + '%' : '—') + '</b></span>' +
      '<span data-k="risky_pct"><i class="sw seg-risky"></i>冒险侧 <b>' + (isNum(b.risky_pct) ? b.risky_pct + '%' : '—') + '</b></span>' +
      '<span data-k="middle"><i class="sw seg-middle"></i>中间：短 put 义务 <b>' + (isNum(b.middle_obligation_usd) ? '$' + money(b.middle_obligation_usd, 0) : '—') +
      '</b> = <b>' + (isNum(b.middle_obligation_x_nav) ? b.middle_obligation_x_nav + ' 倍净值' : '— 倍净值') + '</b></span></div>';
    if (b.basis) h += '<p class="pf-cap">口径：' + esc(b.basis) + '</p>';
    const e = pf.spcx_equiv_exposure;
    if (e) h += '<p class="pf-cap">SPCX 等效敞口：约 ' + qty(e.shares) + ' 股 ≈ $' + money(e.usd, 0) + ' = ' + (isNum(e.x_nav) ? e.x_nav : '—') + ' 倍净值 ' + (/估算/.test(e.label || '') ? EST : '') + '</p>';
    return h;
  }

  function positions(pf) {
    const rows = pf.positions || [];
    if (!rows.length) return '<div class="pf-none">文件里没有持仓。</div>';
    let h = '<div class="pf-scroll"><table class="pf-table" id="pfPositions"><thead><tr><th>标的</th><th>类型</th><th>数量</th><th>成本</th><th>现价</th><th>浮盈亏</th><th>所属侧</th><th>四证状态</th><th>备注</th></tr></thead><tbody>';
    rows.forEach(p => {
      const cls = isNum(p.pnl) ? (p.pnl >= 0 ? 'pos' : 'neg') : '';
      h += '<tr data-symbol="' + esc(p.symbol) + '"><td><b>' + esc(p.symbol || '—') + '</b>' + (p.underlying && p.underlying !== p.symbol ? '<small>看 ' + esc(p.underlying) + '</small>' : '') + '</td>' +
        '<td>' + esc(TYPE[p.type] || p.type || '—') + '</td><td class="r">' + qty(p.qty) + '</td><td class="r">' + px(p.avg_cost) + '</td>' +
        '<td class="r">' + px(p.last) + (isNum(p.after_hours) ? '<small>盘后 ' + px(p.after_hours) + '</small>' : '') + '</td>' +
        '<td class="r ' + cls + '">' + signed(p.pnl) + (p.pnl_est ? ' ' + EST : '') + '</td>' +
        '<td><span class="side side-' + esc(p.side || '') + '">' + esc(SIDE[p.side] || p.side || '—') + '</span></td>' + checkCell(pf, p.check_ticker) +
        '<td class="note">' + esc(p.note || '') + '</td></tr>';
    });
    h += '</tbody></table></div><p class="pf-cap">浮盈亏文件里没有，这里按（现价 − 成本）× 数量算，期权每张按 100 股，所以标“估算”。四证状态来自 four_evidence_check.py：有 underlying 字段的仓位（期权、关联 ETF）看它的标的。</p>';
    return h;
  }

  function others(pf) {
    const rows = pf.other_accounts || [];
    if (!rows.length) return '';
    let h = '<h3>其它账户</h3><div class="pf-scroll"><table class="pf-table" id="pfOthers"><thead><tr><th>账户</th><th>标的</th><th>类型</th><th>方向</th><th>数量</th><th>开仓价</th><th>杠杆</th><th>钱包</th><th>所属侧</th><th>四证状态</th><th>备注</th></tr></thead><tbody>';
    rows.forEach(p => {
      h += '<tr><td>' + esc(p.broker || '—') + '</td><td><b>' + esc(p.symbol || '—') + '</b></td><td>' + esc(TYPE[p.type] || p.type || '—') + '</td><td>' + esc(DIR[p.side_dir] || p.side_dir || '—') + '</td>' +
        '<td class="r">' + qty(p.qty) + '</td><td class="r">' + px(p.entry) + '</td><td class="r">' + (isNum(p.leverage) ? p.leverage + 'X' : '—') + '</td><td class="r">' + (isNum(p.wallet_usd) ? '$' + money(p.wallet_usd, 1) : '—') + '</td>' +
        '<td><span class="side side-' + esc(p.side || '') + '">' + esc(SIDE[p.side] || p.side || '—') + '</span></td>' + checkCell(pf, p.check_ticker) + '<td class="note">' + esc(p.note || '') + '</td></tr>';
    });
    return h + '</tbody></table></div>';
  }

  function levels(pf) {
    const kv = (obj, names, groupEst) => Object.keys(obj || {}).filter(k => k !== 'label').map(k => {
      const m = /^([A-Z]+)_(.+)$/.exec(k), key = m ? m[2] : k, est = groupEst || /(^|_)est($|_)/.test(k);
      return '<div class="pf-lv" data-k="' + esc(k) + '"><label>' + (m ? esc(m[1]) + ' ' : '') + esc(names[key] || lineName(key)) + (est ? ' ' + EST : '') + '</label><b>' + px(obj[k]) + '</b></div>';
    }).join('');
    let h = '<div class="pf-cols"><div><h3>归零线与缓冲</h3>';
    h += pf.lines ? '<div class="pf-lvs">' + kv(pf.lines, LINE, false) + '</div>' + (pf.lines.label ? '<p class="pf-cap">' + esc(pf.lines.label) + '</p>' : '') : '<div class="pf-none">—</div>';
    h += '</div><div><h3>估值参考</h3>';
    h += pf.valuation_refs ? '<div class="pf-lvs">' + kv(pf.valuation_refs, VAL, false) + '</div>' : '<div class="pf-none">—</div>';
    return h + '</div></div>';
  }

  function checklist(pf) {
    const rows = pf.inversion_checklist || [];
    if (!rows.length) return '<div class="pf-none">文件里没有检查清单。</div>';
    return '<ol class="pf-check" id="pfChecklist">' + rows.map(x => '<li class="' + (x.flag === true ? 'hit' : '') + '"><span class="mark">' + (x.flag === true ? '命中' : x.flag === false ? '未命中' : '—') +
      '</span><b>' + esc(x.item || '—') + '</b><span class="txt">' + esc(x.text || '').replace(/估算/g, EST) + '</span></li>').join('') + '</ol>';
  }

  function snapshotSection(pf) {
    const s = pf.snapshots || [];
    if (!s.length) return '<div class="pf-none">portfolio/ 里没有 App 快照。</div>';
    if (!snapName || !s.some(x => x.name === snapName)) snapName = s[0].name;
    return '<div class="pf-snap-head"><label for="pfSnapSel">历史快照</label><select id="pfSnapSel">' +
      s.map((x, i) => '<option value="' + esc(x.name) + '"' + (x.name === snapName ? ' selected' : '') + '>' + esc(x.date) + (i === 0 ? '（最新）' : '') + ' · ' + esc(x.name) + '</option>').join('') +
      '</select></div><div id="pfSnapBody" class="pf-md"></div>';
  }
  async function loadSnapshot() {
    const body = document.getElementById('pfSnapBody'), name = snapName;
    if (!body || !name) return;
    if (snapCache[name] == null) {
      try { const r = await fetch('/api/portfolio/snapshot?name=' + encodeURIComponent(name)); const j = await r.json(); snapCache[name] = j.ok ? j.text : ''; }
      catch (e) { snapCache[name] = ''; }
    }
    const b = document.getElementById('pfSnapBody');
    if (b && name === snapName) b.innerHTML = snapCache[name] ? mdToHtml(snapCache[name]) : '<div class="pf-none">这份快照读不出来。</div>';
  }

  function render(pf, o) {
    opts = o || opts;
    const root = document.getElementById('pfPage');
    if (!root) return;
    if (!pf) { root.innerHTML = '<div class="pf-wrap"><div class="pf-none">正在读取持仓…</div></div>'; lastHtml = ''; return; }
    if (pf.version !== snapVersion) { snapCache = {}; snapVersion = pf.version; }
    let h = '<div class="pf-wrap">';
    if (!pf.ok) {
      h += '<div class="pf-head"><h1>持仓</h1><span class="chip">只读</span></div><div class="pf-empty" id="pfEmpty"><b>' + esc(pf.message || '没有持仓数据') + '</b>' +
        '<p>' + (pf.code === 'missing' ? '没有找到 portfolio/portfolio_state.json。等云端的持仓分析线程下一次同步；图表页不受影响。' : '图表页不受影响。') + '</p></div>';
      if ((pf.snapshots || []).length) h += '<section><h2>App 快照原文</h2>' + snapshotSection(pf) + '</section>';
    } else {
      if (pf.stale) h += '<div class="pf-stale" id="pfStale">持仓数据已过期，以券商 App 为准' + (isNum(pf.age_hours) ? '（数据时间 ' + esc(asofText(pf.asof_taipei)) + '，已过 ' + ageText(pf.age_hours) + '）' : '（读不出数据时间）') + '</div>';
      h += '<div class="pf-head"><h1>持仓</h1><span class="chip">只读 · 不接券商 · 不下单</span><span id="pfUpdated">持仓更新于 ' + esc(pf.updated_at || '—') + '</span>' +
        '<span id="pfAsof">数据时间 ' + esc(asofText(pf.asof_taipei)) + '</span></div>' +
        '<p class="pf-cap" id="pfSource">来源：' + esc(pf.source || '—') + '</p>' +
        '<section><h2>账户</h2>' + account(pf) + '</section>' +
        '<section><h2>杠铃分布</h2>' + barbell(pf) + '</section>' +
        '<section><h2>持仓表' + (pf.account && pf.account.broker ? ' · ' + esc(pf.account.broker) : '') + '</h2>' + positions(pf) + others(pf) + '</section>' +
        '<section><h2>关键价位</h2>' + levels(pf) + '</section>' +
        '<section><h2>逆向检查清单：如何让本金快速亏掉</h2>' + checklist(pf) + '</section>' +
        '<section><h2>App 快照原文（依据）</h2>' + snapshotSection(pf) + '</section>';
    }
    h += '</div>';
    if (h !== lastHtml) { root.innerHTML = h; lastHtml = h; loadSnapshot(); }
  }

  document.addEventListener('change', e => { if (e.target && e.target.id === 'pfSnapSel') { snapName = e.target.value; lastHtml = ''; loadSnapshot(); } });
  document.addEventListener('click', e => { const b = e.target.closest && e.target.closest('[data-goto]'); if (b && opts.gotoTicker) opts.gotoTicker(b.dataset.goto); });
  return { render, mdToHtml, asofText };
})();
