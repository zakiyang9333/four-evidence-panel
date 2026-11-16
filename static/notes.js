/* 「时效与备注」：K 线底部的小标记告诉你那一天发生过什么（财报日、除息、拆股、新闻标题、联网搜到的、你自己写的），
   侧栏的卡片告诉你每样信息有多新。数据来自 /api/notes。备注只是备注，不进规则引擎。
   文字全部用 textContent 写入；链接只接受 http(s)。 */
window.FENotes = (() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const KIND = { earnings: ['财', '#fb923c'], split: ['拆', '#f472b6'], dividend: ['息', '#34d399'], manual: ['记', '#f7c600'], search: ['搜', '#a78bfa'], news: ['闻', '#60a5fa'] };
  const STRIP = 24;             // 主图底部这么高的一条是备注区
  let c = null, data = null, seq = 0, busy = false;

  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const fresh = () => !!(data && c.stateFresh() && data.ticker === c.S.ticker && data.asof === c.S.state.asof);
  const safeUrl = u => (typeof u === 'string' && /^https?:\/\//i.test(u)) ? u : null;
  const md = d => d.slice(5);

  function init(ctx) {
    c = ctx;
    const w = $('#chartwrap');
    w.addEventListener('mousemove', onMove);
    w.addEventListener('mouseleave', () => { $('#noteTip').hidden = true; });
    w.addEventListener('click', onClick);
    render();
  }
  function reset() { seq++; data = null; $('#noteTip').hidden = true; render(); }

  async function fetch() {
    if (!c.stateFresh()) return;
    const my = ++seq;
    try {
      const r = await c.api('/api/notes?ticker=' + c.S.ticker + '&asof=' + c.asofDate());
      if (my !== seq) return;
      if (r.ok === false) throw new Error(r.error);
      use(r);
    } catch (e) { if (my === seq) c.toast('备注没取到：' + e.message, true); }
  }
  function use(r) { data = r; render(); c.redraw(); if (c.narr.renotes) c.narr.renotes(); }
  const onState = () => { if (!fresh()) fetch(); else render(); };

  // ---------- 图上：每根有备注的 K 线，底部一个小方块 ----------
  function draw() {
    if (!fresh() || !c.isDaily()) return;
    const g = c.g(), H = c.OV().h, W = c.OV().w, S = c.S;
    g.font = '700 10px -apple-system,"PingFang SC",sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
    let lastX = -99;
    Object.keys(data.by_date).sort().forEach(d => {
      const i = S.idx[d], x = i == null ? null : c.X(i);
      if (x == null || x < 6 || x > W - 6) return;
      const rows = data.by_date[d], k = KIND[rows[0].kind] || KIND.news;
      if (x - lastX < 13 && rows[0].kind === 'news') return;       // 太挤时，纯新闻的先让一让
      lastX = x;
      g.fillStyle = k[1]; g.beginPath(); g.roundRect(x - 6.5, H - 18, 13, 13, 3); g.fill();
      g.fillStyle = '#0b0e14'; g.fillText(k[0], x, H - 11);
      if (rows.length > 1) { g.fillStyle = k[1]; g.beginPath(); g.arc(x + 7, H - 18, 3, 0, Math.PI * 2); g.fill(); }
    });
    const up = data.upcoming;
    if (up) c.label('下次财报 ' + md(up.date) + (up.days_left <= 0 ? ' · 今天' : up.days_left === 1 ? ' · 明天' : ' · 还有 ' + up.days_left + ' 天'), W - 6, H - 34, KIND.earnings[1], 'right');
  }

  function barAt(e) {
    if (!fresh() || !c.isDaily()) return null;
    const pt = c.ptFromEvent(e), H = c.OV().h;
    if (pt.y < H - STRIP || pt.y > H) return null;
    const d = c.S.bars.d[pt.li];
    return d && data.by_date[d] ? { date: d, rows: data.by_date[d], pt } : null;
  }
  function onMove(e) {
    const tip = $('#noteTip'), hit = barAt(e);
    if (!hit) { tip.hidden = true; return; }
    tip.textContent = '';
    tip.appendChild(el('b', '', hit.date));
    hit.rows.slice(0, 6).forEach(r => {
      const row = el('div', 'nt-row');
      const tag = el('i', '', data.kinds[r.kind] || r.kind); tag.style.background = (KIND[r.kind] || KIND.news)[1];
      row.appendChild(tag); row.appendChild(el('span', '', r.title + (r.source && !r.fact ? '（' + r.source + '）' : '')));
      tip.appendChild(row);
    });
    if (hit.rows.length > 6) tip.appendChild(el('div', 'muted', '还有 ' + (hit.rows.length - 6) + ' 条，点一下看全部'));
    const r = $('#chartwrap').getBoundingClientRect();
    tip.hidden = false;
    tip.style.left = Math.max(6, Math.min(e.clientX - r.left - 140, r.width - 300)) + 'px';
    tip.style.top = Math.max(6, e.clientY - r.top - tip.offsetHeight - 14) + 'px';
  }
  function onClick(e) {
    if (c.S.tool !== 'cursor') return;
    const hit = barAt(e);
    if (hit) openDay(hit.date);
  }

  // ---------- 某一天的全部备注（弹窗）：能点链接、删除、再写一条 ----------
  function openDay(date) {
    $('#noteTip').hidden = true;
    const rows = (fresh() && data.by_date[date]) || [];
    $('#modalTitle').textContent = c.S.ticker + ' ' + date + ' 这天发生过什么';
    const body = $('#modalBody'); body.textContent = '';
    if (!rows.length) body.appendChild(el('p', 'muted', '这一天没有备注。没有备注不等于没事发生：新闻存档是从开始存的那天才有的。'));
    rows.forEach(r => {
      const d = el('div', 'note-row');
      const tag = el('i', '', data.kinds[r.kind] || r.kind); tag.style.background = (KIND[r.kind] || KIND.news)[1];
      d.appendChild(tag);
      const mid = el('div', 'mid');
      mid.appendChild(el('b', '', r.title));
      const src = el('small', 'muted', (r.fact ? '事实 · ' : r.kind === 'manual' ? '' : '媒体或搜索的说法 · ') + (r.source || '') + (r.date !== date ? ' · 发生在 ' + r.date + '（休市，记在下一个交易日）' : '') + ' · 记于 ' + String(r.fetched_at || '').slice(0, 16));
      mid.appendChild(src);
      const u = safeUrl(r.url);
      if (u) { const a = el('a', '', '打开原文'); a.href = u; a.target = '_blank'; a.rel = 'noopener noreferrer'; mid.appendChild(a); }
      d.appendChild(mid);
      if (!r.fact) { const x = el('button', '', '删除'); x.onclick = () => post('/api/notes/delete', { id: r.id }, () => openDay(date)); d.appendChild(x); }
      body.appendChild(d);
    });
    const f = el('form', 'note-form');
    const inp = el('input'); inp.maxLength = 300; inp.placeholder = '自己写一句：这天发生了什么'; inp.autocomplete = 'off';
    const ok = el('button', 'primary', '记下来'); ok.type = 'submit';
    f.appendChild(inp); f.appendChild(ok);
    f.addEventListener('submit', e => { e.preventDefault(); if (inp.value.trim()) post('/api/notes/manual', { date, text: inp.value.trim() }, () => openDay(date)); });
    body.appendChild(f);
    const done = data.freshness.searched_days.indexOf(date) >= 0;
    const s = el('button', 'note-search', done ? '这一天查过了。再查一次（会再次计费）' : '让 Claude 联网查这一天（会计费，查过的不再查）');
    s.disabled = busy || !c.aiEnabled();
    s.onclick = () => search([date], () => openDay(date), done);
    body.appendChild(s);
    $('#modal').hidden = false;
    setTimeout(() => inp.focus(), 30);
  }

  async function post(path, body, then) {
    try {
      const r = await c.api(path, Object.assign({ ticker: c.S.ticker, asof: c.asofDate() }, body));
      if (r.ok === false) throw new Error(r.error);
      if (r.notes) use(r.notes);
      if (then) then(r);
      return r;
    } catch (e) { c.toast('没成功：' + e.message, true); return null; }
  }

  async function search(dates, then, force) {
    if (busy) return;
    busy = true; render();
    c.toast('Claude 正在联网查' + (dates ? ' ' + dates.join('、') : '最近的异常日') + '，大约要半分钟…');
    const r = await post('/api/notes/search', { dates: dates || null, force: !!force });
    busy = false; render();
    if (!r) return;
    if (r.skipped) c.toast(r.message);
    else c.toast('查了 ' + r.searched.length + ' 天，记下 ' + r.added + ' 条' + (r.dropped ? '，另有 ' + r.dropped + ' 条因为对不上搜索结果里的链接被丢掉' : '') + '。用了 ' + r.tokens_in + ' 入 + ' + r.tokens_out + ' 出 token，搜索 ' + r.searches + ' 次。');
    if (then) then(r);
  }

  // ---------- 侧栏：时效与备注 ----------
  function render() {
    const box = $('#noteCard'); if (!box) return;
    box.textContent = '';
    if (!c || !fresh()) { box.appendChild(el('div', 'muted small', '计算中…')); return; }
    const f = data.freshness, nar = c.narr.current();
    const row = (k, v, cls) => { const d = el('div', 'fr-row' + (cls ? ' ' + cls : '')); d.appendChild(el('label', '', k)); d.appendChild(el('span', '', v)); box.appendChild(d); return d; };
    row('K 线数据', '截至 ' + data.asof + ' 收盘' + (data.is_latest ? '' : '（回放：之后的事一概不算）'));
    if (nar && nar.source === 'claude') {
      const stale = nar.same_input === false, more = nar.notes_since || 0;
      row('AI 解读', '生成于 ' + String(nar.created_at || '').slice(0, 16) + (stale ? ' · 之后数据或仓位变过' : '') + (more ? ' · 之后新增 ' + more + ' 条备注，它没看到' : '') +
        (nar.notes_used != null ? ' · 当时带了 ' + nar.notes_used + ' 条备注' : ' · 当时没有备注可看'), stale || more ? 'warn' : '');
    } else row('AI 解读', nar ? '现在显示的是模板版，不含新闻' : '还没有');
    row('事件日历', f.events_fetched_at ? (f.events_source + '，更新于 ' + f.events_fetched_at.slice(0, 16) + (f.events_stale ? ' · 超过 7 天没更新，可能过时' : '')) : '还没取过，点一次“刷新数据”', f.events_stale ? 'warn' : '');
    row('新闻存档', f.news_since ? '从 ' + f.news_since + ' 起每次刷新存一批标题；更早的日子只有联网查过或手写的才有' : '还没开始存');
    if (data.upcoming) row('下次财报', data.upcoming.date + (data.upcoming.days_left <= 0 ? '（今天）' : data.upcoming.days_left === 1 ? '（明天）' : '（还有 ' + data.upcoming.days_left + ' 天）') + '：临近财报，眼前的形态随时可能作废', 'hot');
    const todo = data.notable.filter(r => !r.searched);
    box.appendChild(el('div', 'fr-sub', '最近 60 根里动静最大的几天'));
    const ul = el('ul', 'fr-days');
    data.notable.forEach(r => {
      const li = el('li'); const b = el('button', '', md(r.date)); b.title = '看这一天的备注'; b.onclick = () => openDay(r.date);
      li.appendChild(b); li.appendChild(el('span', '', r.why));
      const n = (data.by_date[r.date] || []).length;
      li.appendChild(el('em', n ? 'has' : r.searched ? '' : 'todo', n ? n + ' 条备注' : r.searched ? '查过，没找到' : '原因未知'));
      ul.appendChild(li);
    });
    box.appendChild(ul);
    const s = el('button', 'note-search', busy ? 'Claude 正在联网查…' : todo.length ? '让 Claude 联网查这 ' + todo.length + ' 天发生了什么（会计费）' : '这几天都查过了');
    s.id = 'noteSearch'; s.disabled = busy || !todo.length || !c.aiEnabled();
    s.title = c.aiEnabled() ? '每条结果都必须带着搜索结果里真实出现过的链接，对不上的会被丢掉。查过的日子不再查第二遍。' : '没有设置 API 密钥，不能联网查';
    s.onclick = () => search(null);
    box.appendChild(s);
    box.appendChild(el('p', 'fine', '图底部的小方块：财 = 财报日，息 = 除息，拆 = 拆股，闻 = 新闻标题，搜 = 联网搜到的，记 = 你写的。右键某根 K 线可以写备注。备注不参与任何规则判定。'));
  }

  /* 解说卡片：这一步在图上标了哪几天，那几天有什么值得带一句的备注。
     只带三种：事件日（财报、除息、拆股）、你自己写的、联网搜到并核对过链接的中文概括。
     原始的新闻标题不带：它们又长又杂、多半是英文的大盘消息，放在卡片上只会干扰（zaki 11-16：“AI分析出现无用信息”）。
     想看标题，图底部的小方块上悬停或点开就有。 */
  function forDraw(draw) {
    if (!fresh() || !draw || !draw.length) return [];
    const days = new Set();
    draw.forEach(d => {
      if (d.date) days.add(d.date);
      (d.points || []).forEach(p => days.add(p.date));
      (d.dates || []).forEach(x => days.add(x));
      if (d.date_from && d.date_to) Object.keys(data.by_date).forEach(x => { if (x >= d.date_from && x <= d.date_to) days.add(x); });
    });
    const out = [];
    [...days].sort().forEach(d => (data.by_date[d] || []).forEach(r => {
      if (!(r.fact || r.kind === 'manual' || r.kind === 'search')) return;
      out.push({ id: r.id, date: d, fact: !!r.fact, text: md(d) + ' ' + (r.kind === 'manual' ? '你记的：' : '') + r.title });
    }));
    return out;
  }

  function menu(date, add) {      // 图上右键菜单里的两项
    add('写备注（' + date + '）', () => openDay(date));
    add('让 Claude 联网查这一天（会计费）', () => search([date], () => openDay(date)), busy || !c.aiEnabled());
  }

  return { init, reset, onState, draw, render, menu, forDraw, openDay, search, data: () => data, fresh, _use: use };
})();
