/* 量化终端：每只标的 × 每个模型 × 做多/做空，现在各是什么状态。数据全部来自 /api/quant/scan（和「AI 量化」窗口同一段代码）。
   这里只显示，不算任何规则；不接券商，不做交易。文字用 textContent 写入。 */
(() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const q = new URLSearchParams(location.search);
  const HZ = [20, 60, 120], HZ_NAME = { 20: '短线', 60: '中线', 120: '长线' };
  const T = { hz: HZ.indexOf(Number(q.get('hz'))) >= 0 ? Number(q.get('hz')) : 20, tf: q.get('tf') === 'W' ? 'W' : 'D', cells: [], models: [], tickers: [], seq: 0, loading: false };
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const fmt = x => x == null ? '—' : Number(x).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const sideName = s => (s === 'short' ? '做空' : '做多');
  let toastTimer = 0;
  function toast(msg) { const t = $('#toast'); t.textContent = msg; t.className = 'err'; t.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 6000); }

  function controls() {
    const box = $('#tHz'); box.textContent = '';
    HZ.forEach(n => { const b = el('button', n === T.hz ? 'on' : '', HZ_NAME[n] + ' · ' + n + (T.tf === 'W' ? ' 周' : ' 日')); b.onclick = () => { if (T.hz !== n) { T.hz = n; load(); } }; box.appendChild(b); });
    document.querySelectorAll('#tTf button').forEach(b => { b.classList.toggle('on', b.dataset.tf === T.tf); b.onclick = () => { if (T.tf !== b.dataset.tf) { T.tf = b.dataset.tf; load(); } }; });
    try { history.replaceState(null, '', '?hz=' + T.hz + '&tf=' + T.tf); } catch (e) { /* 忽略 */ }
  }

  /* 回到图表并切到这一格的组合：从面板打开的就让原来那个窗口跳过去，否则在这个窗口里打开 */
  function open(c) {
    const url = '/?t=' + c.ticker + '&model=' + c.model + '&dir=' + c.side + '&hz=' + T.hz + (T.tf === 'W' ? '&tf=W' : '') + '&side=1&qtab=analyze';
    try { if (window.opener && !window.opener.closed) { window.opener.location.href = url; window.opener.focus(); return; } } catch (e) { /* 打不开原窗口就在这里开 */ }
    location.href = url;
  }

  function cellNode(c) {
    if (!c) return el('div', 'cell wait-load', '计算中…');
    if (!c.supported) { const d = el('div', 'cell off', '这个模型没有' + (T.tf === 'W' && c.model === 'four' && c.side === 'long' ? '周 K 上' : sideName(c.side) + '一侧') + '的规则'); return d; }
    const b = el('button', 'cell ' + c.state);
    b.title = '回到图表，看 ' + c.ticker + ' 的这个组合';
    b.appendChild(el('b', '', c.verdict));
    b.appendChild(el('small', '', (c.phase ? c.phase + ' · ' : '') + (c.of ? '清单 ' + c.ok + '/' + c.of : '没有清单')));
    if (c.zone) b.appendChild(el('span', 'plan', '入场 ' + fmt(c.zone[0]) + ' – ' + fmt(c.zone[1]) + ' · 止损 ' + fmt(c.stop) + ' · 目标 ' + fmt(c.t1) + (c.rr != null ? ' · 盈亏比 ' + c.rr.toFixed(2) : '')));
    const h = c.history;
    b.appendChild(el('small', '', h && h.n ? '历史 ' + h.n + ' 次：先到目标 ' + h.target + '，先破止损 ' + h.stop + '，其余 ' + h.none + (h.rr_median != null ? ' · 盈亏比中位 ' + h.rr_median.toFixed(2) : '') : '历史上没出现过'));
    b.onclick = () => open(c);
    return b;
  }

  function render() {
    const g = $('#tGrid'); g.textContent = '';
    const find = (t, m, s) => T.cells.find(c => c.ticker === t && c.model === m && c.side === s);
    // 一行一个模型（按类别分段），一列一只标的的一个方向：模型多了也排得下
    const h1 = el('tr'); h1.appendChild(el('th', '', '模型'));
    T.tickers.forEach(t => {
      const any = T.cells.find(c => c.ticker === t), th = el('th', 'grp', t); th.colSpan = 2;
      th.appendChild(el('small', 'tk-sub', any ? any.asof + ' 收 ' + fmt(any.price) + ' · 表盘 ' + (any.score > 0 ? '+' : '') + any.score + ' ' + any.score_label : '计算中…'));
      h1.appendChild(th);
    });
    const h2 = el('tr'); h2.appendChild(el('th', '', ''));
    T.tickers.forEach(() => { h2.appendChild(el('th', '', '↗ 做多')); h2.appendChild(el('th', '', '↘ 做空')); });
    g.appendChild(h1); g.appendChild(h2);
    let group = null;
    T.models.forEach(m => {
      if ((m.group || '') !== group) {
        group = m.group || '';
        if (group) { const gr = el('tr'), gd = el('td', 'grp-row', group + '类'); gd.colSpan = 1 + T.tickers.length * 2; gr.appendChild(gd); g.appendChild(gr); }
      }
      const tr = el('tr'), td = el('td', 'tk');
      td.appendChild(el('b', '', m.name)); td.appendChild(el('small', '', m.tested));
      tr.appendChild(td);
      T.tickers.forEach(t => ['long', 'short'].forEach(s => { const c = el('td'); c.appendChild(T.cells.some(x => x.ticker === t) ? cellNode(find(t, m.key, s)) : el('div', 'cell wait-load', '计算中…')); tr.appendChild(c); }));
      g.appendChild(tr);
    });
    // 历史触发汇总：每个模型、每个方向，所有标的加起来
    const sum = $('#tSum'); sum.textContent = '';
    const head = el('tr'); ['模型', '方向', '出现次数', '先到第一目标', '先越过止损', '到期 / 两头都没到', '往后看', '盈亏比（中位）'].forEach(x => head.appendChild(el('th', '', x))); sum.appendChild(head);
    T.models.forEach(m => ['long', 'short'].forEach(s => {
      const cs = T.cells.filter(c => c.model === m.key && c.side === s && c.supported);
      if (!cs.length) return;
      const n = cs.reduce((a, c) => a + c.history.n, 0), tg = cs.reduce((a, c) => a + c.history.target, 0), st = cs.reduce((a, c) => a + c.history.stop, 0), no = cs.reduce((a, c) => a + c.history.none, 0);
      const tr = el('tr');
      const rr = cs.map(c => c.history.rr_median).filter(x => x != null).sort((a, b) => a - b);
      [m.name, sideName(s), n, tg, st, no, (cs[0].history.hold || T.hz) + ' 根', rr.length ? rr[Math.floor(rr.length / 2)].toFixed(2) + ' : 1' : m.key === 'four' ? '按引擎的出场规则' : '—']
        .forEach((x, k) => { const td = el('td', k === 3 ? 'pos' : k === 4 ? 'neg' : '', String(x)); tr.appendChild(td); });
      sum.appendChild(tr);
    }));
    const a = T.cells[0];
    $('#tAsof').textContent = a ? '数据截至 ' + T.cells.map(c => c.asof).sort().pop() + ' 收盘 · ' + (T.tf === 'W' ? '周K' : '日K') : '加载中…';
  }

  async function load() {
    const my = ++T.seq;
    T.cells = []; T.loading = true; controls(); render();
    try {
      const meta = await (await fetch('/api/meta')).json();
      T.tickers = meta.tickers.map(t => t.ticker);
      for (const t of T.tickers) {                 // 一只一只取：先算完的先显示
        const r = await (await fetch('/api/quant/scan?ticker=' + t + '&hz=' + T.hz + '&tf=' + T.tf)).json();
        if (my !== T.seq) return;
        if (r.ok === false) throw new Error(r.error);
        T.models = r.models; T.cells = T.cells.concat(r.cells); render();
      }
    } catch (e) { if (my === T.seq) toast('没取到：' + e.message); }
    T.loading = false;
  }

  $('#tReload').onclick = load;
  $('#tBack').onclick = () => { try { if (window.opener && !window.opener.closed) { window.opener.focus(); window.close(); return; } } catch (e) { /* 忽略 */ } location.href = '/'; };
  load();
  window.__term = { T, load };
})();
