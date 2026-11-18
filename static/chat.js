/* AI 对话：一边看图一边问。图表左边的一栏。
   - 回答一个字一个字流出来；整段对话存在本机，关掉再开还能接着聊；左上“历史”能翻以前的对话。
   - 图表数据由后端在它变了的时候自动附上（换标的、换日期、换模型、多了备注），这里只显示“附上了哪张图”。
   - “一键解释”并在这里：程序拼的大白话卡片，作为一条消息放进对话，不花钱；之后可以接着追问。
   模型写的内容一律当作文字处理：自己解析 Markdown 并用 textContent 建节点，不把任何内容当 HTML 插进页面。 */
window.FEChat = (() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const QUICK = ['现在这张图最该看什么？', '今天的结论会被什么推翻？', '止损、目标和盈亏比怎么理解？'];
  let c = null, open = false, conv = null, streaming = false, ctl = null, view = 'chat', chats = [], web = false, paintQueued = false, liveBubble = null, liveMsg = null;

  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const kilo = n => n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n || 0);

  // ---------- 很小的一个 Markdown 解析：只建节点，不拼 HTML ----------
  function inline(parent, text) {
    const re = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\))/g;
    let last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) parent.appendChild(document.createTextNode(text.slice(last, m.index)));
      const t = m[0];
      if (t[0] === '*') parent.appendChild(el('strong', '', t.slice(2, -2)));
      else if (t[0] === '`') parent.appendChild(el('code', '', t.slice(1, -1)));
      else { const k = t.indexOf(']('), a = el('a', '', t.slice(1, k)); a.href = t.slice(k + 2, -1); a.target = '_blank'; a.rel = 'noopener noreferrer'; parent.appendChild(a); }
      last = m.index + t.length;
    }
    if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
  }
  function md(src) {
    const frag = document.createDocumentFragment(), lines = String(src || '').replace(/\r/g, '').split('\n');
    let i = 0, para = [];
    const flush = () => { if (para.length) { const p = el('p'); inline(p, para.join('\n')); frag.appendChild(p); para = []; } };
    const UL = /^\s*[-*•]\s+/, OL = /^\s*\d+[.、)]\s+/, ROW = /^\s*\|.*\|\s*$/, SEP = /^\s*\|[\s:|-]+\|\s*$/;
    const cells = L => L.trim().replace(/^\||\|$/g, '').split('|').map(x => x.trim());
    while (i < lines.length) {
      const L = lines[i];
      let m;
      if (/^\s*```/.test(L)) {
        flush(); const code = []; i++;
        while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++]);
        i++; const pre = el('pre'); pre.appendChild(el('code', '', code.join('\n'))); frag.appendChild(pre); continue;
      }
      if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(L)) { flush(); frag.appendChild(el('hr')); i++; continue; }
      if ((m = /^\s*(#{1,4})\s+(.*)$/.exec(L))) { flush(); const h = el('h' + Math.min(6, m[1].length + 3)); inline(h, m[2]); frag.appendChild(h); i++; continue; }
      if (UL.test(L) || OL.test(L)) {
        flush(); const ord = OL.test(L) && !UL.test(L), R = ord ? OL : UL, list = el(ord ? 'ol' : 'ul');
        while (i < lines.length && R.test(lines[i])) { const li = el('li'); inline(li, lines[i].replace(R, '')); list.appendChild(li); i++; }
        frag.appendChild(list); continue;
      }
      if (ROW.test(L) && i + 1 < lines.length && SEP.test(lines[i + 1])) {
        flush(); const tb = el('table'), hr = el('tr');
        cells(L).forEach(x => { const th = el('th'); inline(th, x); hr.appendChild(th); }); tb.appendChild(hr); i += 2;
        while (i < lines.length && ROW.test(lines[i])) { const tr = el('tr'); cells(lines[i]).forEach(x => { const td = el('td'); inline(td, x); tr.appendChild(td); }); tb.appendChild(tr); i++; }
        const wrap = el('div', 'md-table'); wrap.appendChild(tb); frag.appendChild(wrap); continue;
      }
      if (/^\s*>\s?/.test(L)) { flush(); const q = el('blockquote'), buf = []; while (i < lines.length && /^\s*>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, '')); inline(q, buf.join('\n')); frag.appendChild(q); continue; }
      if (!L.trim()) { flush(); i++; continue; }
      para.push(L); i++;
    }
    flush();
    return frag;
  }

  // ---------- 面板骨架 ----------
  function init(ctx) {
    c = ctx;
    const box = $('#learn'); box.textContent = '';
    const head = el('div', 'chat-head');
    head.appendChild(el('b', '', 'AI 对话'));
    const title = el('span', 'muted'); title.id = 'chatTitle'; head.appendChild(title);
    head.appendChild(el('span', 'spacer'));
    const hb = el('button', '', '历史'); hb.id = 'chatHistBtn'; hb.title = '以前的对话'; hb.onclick = () => (view === 'list' ? showChat() : showList());
    const nb = el('button', '', '＋ 新对话'); nb.id = 'chatNewBtn'; nb.onclick = newChat;
    const xb = el('button', '', '✕'); xb.id = 'chatClose'; xb.title = '回到「分析」页'; xb.onclick = () => toggle(false);
    head.appendChild(hb); head.appendChild(nb); head.appendChild(xb);
    const body = el('div', 'chat-body'); body.id = 'chatBody';
    const quick = el('div', 'chat-quick'); quick.id = 'chatQuick';
    QUICK.forEach(q => { const b = el('button', '', q); b.onclick = () => send(q); quick.appendChild(b); });
    const form = el('form', 'chat-form'); form.id = 'chatForm';
    const ta = el('textarea'); ta.id = 'chatInput'; ta.rows = 2; ta.maxLength = 4000; ta.placeholder = '问点什么。回车发送，Shift + 回车换行';
    const row = el('div', 'chat-row');
    const wl = el('label', 'chat-web'); const wc = el('input'); wc.type = 'checkbox'; wc.id = 'chatWeb'; wc.onchange = () => { web = wc.checked; };
    wl.appendChild(wc); wl.appendChild(document.createTextNode(' 联网搜索')); wl.title = '让它在需要时上网查（按次另外计费）。不开的话，它只知道图表数据和备注里有的';
    const use = el('span', 'muted'); use.id = 'chatUsage';
    const sb = el('button', 'primary', '发送'); sb.id = 'chatSend'; sb.type = 'submit';
    row.appendChild(wl); row.appendChild(use); row.appendChild(el('span', 'spacer')); row.appendChild(sb);
    form.appendChild(ta); form.appendChild(row);
    form.addEventListener('submit', e => { e.preventDefault(); if (streaming) stop(); else { const t = ta.value; if (t.trim()) { ta.value = ''; send(t); } } });
    ta.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); } });
    box.appendChild(head); box.appendChild(body); box.appendChild(quick); box.appendChild(form);
    $('#chatBtn').onclick = () => toggle(!open);
    const q = new URLSearchParams(location.search);
    if (q.get('chatid')) c.store.set('chat.id', q.get('chatid'));       // ?chatid=…：直接打开某一段对话
    if (q.get('chat') === '1') toggle(true);
  }

  /* 对话住在「AI 量化」窗口的「对话」页签里。打开 = 展开窗口并切到这一页；收起 = 回到「分析」页。 */
  let pending = Promise.resolve();
  async function toggle(on) {
    if (on) { c.openSide(); c.setTab('chat'); await pending; }
    else if (c.tab() === 'chat') c.setTab('analyze');
    else shown(false);
  }
  /* 页签被点开或离开时，窗口那边会告诉这里一声 */
  function shown(on) {
    open = !!on;
    $('#learn').hidden = !open;
    $('#chatBtn').classList.toggle('on', open);
    if (!open) return pending;
    pending = (async () => {
      if (!conv) { const id = c.store.get('chat.id', null); if (id) await load(id, true); }
      showChat();
    })();
    return pending;
  }

  async function load(id, quiet) {
    try {
      const r = await c.api('/api/chat/get?id=' + encodeURIComponent(id));
      if (r.ok === false) throw new Error(r.error);
      conv = r.conv; c.store.set('chat.id', conv.id);
    } catch (e) { conv = null; c.store.set('chat.id', null); if (!quiet) c.toast('这段对话打不开：' + e.message, true); }
  }
  function newChat() { if (streaming) return; conv = null; c.store.set('chat.id', null); showChat(); $('#chatInput').focus(); }

  // ---------- 显示 ----------
  function sync() {
    const ok = c.aiEnabled();
    $('#chatTitle').textContent = view === 'list' ? '以前的对话' : (conv ? conv.title : '新对话');
    $('#chatHistBtn').textContent = view === 'list' ? '返回' : '历史';
    $('#chatSend').textContent = streaming ? '停止' : '发送';
    $('#chatSend').classList.toggle('stop', streaming);
    $('#chatInput').disabled = !ok; $('#chatSend').disabled = !ok && !streaming;
    $('#chatInput').placeholder = ok ? '问点什么。回车发送，Shift + 回车换行' : '没有设置 API 密钥，不能提问';
    $('#chatQuick').hidden = view === 'list'; $('#chatForm').hidden = view === 'list';
    [...$('#chatQuick').querySelectorAll('button')].forEach(b => { b.disabled = !ok || streaming; });
    const u = conv && conv.usage;
    $('#chatUsage').textContent = u && u.calls ? '这段对话共 ' + kilo(u.tokens_in + u.cache_read + (u.cache_write || 0)) + ' 入（其中 ' + kilo(u.cache_read) + ' 走缓存）+ ' + kilo(u.tokens_out) + ' 出' : '';
    $('#chatUsage').title = '入 = 发给模型的内容（图表数据和前面的对话），出 = 它写的回答。走缓存的那部分只按原价的很小一部分计费。';
  }

  function learnCards(box, lp) {
    const chip = el('div', 'cx-chip', '一键解释 · ' + lp.ticker + ' ' + lp.asof + ' · ' + lp.model_name + (lp.replay ? ' · 回放' : '') + ' · 程序拼的，没花钱');
    box.appendChild(chip);
    const hl = el('div', 'learn-hl ' + lp.headline.tone);
    hl.appendChild(el('small', '', '今天的一句话')); hl.appendChild(el('b', '', lp.headline.text)); hl.appendChild(el('span', '', lp.headline.sub));
    box.appendChild(hl);
    lp.cards.forEach((k, n) => {
      const a = el('article', 'lcard' + (k.ok === true ? ' yes' : k.ok === false ? ' no' : '')); a.dataset.id = k.id;
      const h = el('h4'); h.appendChild(el('i', '', String(n + 1))); h.appendChild(document.createTextNode(k.title)); a.appendChild(h);
      a.appendChild(el('p', '', k.body));
      if (k.now) { const d = el('div', 'lnow'); d.appendChild(el('span', '', '今天')); d.appendChild(document.createTextNode(k.now)); a.appendChild(d); }
      if (k.items && k.items.length) {
        const ul = el('ul', 'litems');
        k.items.forEach(it => { const li = el('li', it.ok ? 'yes' : 'no'); li.appendChild(el('b', '', (it.ok ? '是 · ' : '否 · ') + it.name)); li.appendChild(el('span', '', it.text)); ul.appendChild(li); });
        a.appendChild(ul);
      }
      if (k.note) a.appendChild(el('p', 'lnote', k.note));
      if (k.spot) { const b = el('button', 'lspot', '指给我看'); b.dataset.spot = k.spot; b.onclick = () => spot(k.spot); a.appendChild(b); }
      box.appendChild(a);
    });
    const g = el('details', 'lgloss'); g.appendChild(el('summary', '', '名词小词典（' + lp.glossary.length + ' 个）'));
    const dl = el('dl'); lp.glossary.forEach(w => { dl.appendChild(el('dt', '', w[0])); dl.appendChild(el('dd', '', w[1])); });
    g.appendChild(dl); box.appendChild(g);
    box.appendChild(el('p', 'lfoot', lp.footer + ' 哪张没看懂，直接在下面问。'));
  }

  function msgNode(m) {
    const w = el('div', 'cmsg ' + (m.role === 'user' ? 'user' : 'ai') + (m.kind === 'explain' ? ' explain' : ''));
    if (m.role === 'user') {
      w.appendChild(el('div', 'bubble', m.text));
      if (m.chip) w.appendChild(el('small', 'cx-note', '已附上 ' + m.chip + ' 的图表数据'));
      return w;
    }
    if (m.kind === 'explain' && m.learn) { learnCards(w, m.learn); return w; }
    const b = el('div', 'bubble md');
    if (m.text) b.appendChild(md(m.text)); else if (m.streaming) b.appendChild(el('span', 'typing', '正在想…'));
    w.appendChild(b);
    const meta = m.meta || {};
    if (meta.sources && meta.sources.length) {
      const s = el('div', 'cx-src'); s.appendChild(el('span', '', '查到的出处：'));
      meta.sources.forEach(x => { if (/^https?:\/\//i.test(x.url)) { const a = el('a', '', x.title || x.url); a.href = x.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; s.appendChild(a); } });
      w.appendChild(s);
    }
    const bits = [];
    if (meta.tokens_in != null) bits.push(kilo(meta.tokens_in + (meta.cache_read || 0) + (meta.cache_write || 0)) + ' 入' + (meta.cache_read ? '（' + kilo(meta.cache_read) + ' 走缓存）' : '') + ' + ' + kilo(meta.tokens_out) + ' 出 token');
    if (meta.searches) bits.push('联网搜了 ' + meta.searches + ' 次');
    if (meta.interrupted || m.interrupted) bits.push('中途停止');
    if (meta.truncated) bits.push('太长被截断');
    if (m.error) bits.push('出错：' + m.error);
    if (bits.length) w.appendChild(el('small', 'cx-note', bits.join(' · ')));
    if (m.streaming) { liveBubble = b; liveMsg = m; }
    return w;
  }

  function showChat(keepScroll) {
    view = 'chat';
    const body = $('#chatBody'), at = body.scrollTop, bottom = body.scrollHeight - body.scrollTop - body.clientHeight < 80;
    body.textContent = ''; liveBubble = null; liveMsg = null;
    if (!conv || !conv.messages.length) {
      const e = el('div', 'chat-empty');
      e.appendChild(el('b', '', '看图的时候，有什么想问的就问'));
      e.appendChild(el('p', '', '它看得到现在这张图：规则引擎的结论、最近 60 根 K 线、表盘、清单、K 线上的备注和当天保存的 AI 解读。换了标的或日期，它会自动拿到新的一份。'));
      e.appendChild(el('p', '', '整段对话有记忆，存在本机，关掉再开还能接着聊。提问会调用 Claude（计费）；前面聊过的内容会走缓存，越往后每一问越便宜。'));
      e.appendChild(el('p', '', '不知道从哪问起，就点下面的几个常见问题。'));
      body.appendChild(e);
    } else conv.messages.forEach(m => body.appendChild(msgNode(m)));
    sync();
    body.scrollTop = keepScroll && !bottom ? at : body.scrollHeight;
  }

  async function showList() {
    view = 'list'; sync();
    const body = $('#chatBody'); body.textContent = '';
    try { chats = (await c.api('/api/chat/list')).chats || []; } catch (e) { chats = []; }
    if (!chats.length) { body.appendChild(el('div', 'chat-empty', '还没有保存过对话。')); return; }
    chats.forEach(x => {
      const row = el('div', 'chat-item' + (conv && conv.id === x.id ? ' on' : ''));
      const b = el('button', 'open'); b.appendChild(el('b', '', x.title)); b.appendChild(el('small', 'muted', String(x.updated || '').slice(5, 16) + (x.ticker ? ' · ' + x.ticker : '') + ' · ' + x.count + ' 条'));
      b.onclick = async () => { await load(x.id); showChat(); };
      const d = el('button', 'del', '删除'); d.title = '删掉这段对话（只删本机的记录）';
      d.onclick = async () => { await c.api('/api/chat/delete', { id: x.id }); if (conv && conv.id === x.id) { conv = null; c.store.set('chat.id', null); } showList(); };
      row.appendChild(b); row.appendChild(d); body.appendChild(row);
    });
  }

  function paint() {            // 流式输出：攒一帧再重画那一个气泡
    if (paintQueued) return;
    paintQueued = true;
    setTimeout(() => {
      paintQueued = false;
      if (!liveBubble || !liveMsg) return;
      const body = $('#chatBody'), bottom = body.scrollHeight - body.scrollTop - body.clientHeight < 90;
      liveBubble.textContent = ''; liveBubble.appendChild(md(liveMsg.text));
      if (bottom) body.scrollTop = body.scrollHeight;
    }, 60);
  }

  // ---------- 发一条 ----------
  async function send(text) {
    text = String(text || '').trim();
    if (streaming || !text) return;
    if (!c.aiEnabled()) { c.toast(c.aiReason() || '没有设置 API 密钥，不能提问。', true); return; }
    if (!c.stateFresh()) { c.toast('图表还在加载，稍等一下再问。', true); return; }
    if (view === 'list') view = 'chat';
    conv = conv || { id: null, title: '新对话', messages: [], usage: null };
    const mine = { role: 'user', text }, ai = { role: 'assistant', text: '', streaming: true };
    conv.messages.push(mine, ai);
    streaming = true; ctl = new AbortController();
    showChat();
    let finished = false;
    const handle = blk => {
      let ev = 'message', data = '';
      blk.split('\n').forEach(l => { if (l.indexOf('event:') === 0) ev = l.slice(6).trim(); else if (l.indexOf('data:') === 0) data += l.slice(5).trim(); });
      let d; try { d = JSON.parse(data); } catch (e) { return; }
      if (ev === 'start') { conv.id = d.id; conv.title = d.title; mine.chip = d.chip; c.store.set('chat.id', d.id); showChat(); }
      else if (ev === 'delta') { ai.text += d.text; if (liveBubble && liveMsg === ai && ai.text.length === d.text.length) liveBubble.textContent = ''; paint(); }
      else if (ev === 'done') { finished = true; conv = d.conv; }
      else if (ev === 'error') { finished = true; if (d.conv) conv = d.conv; c.toast('没答成：' + d.error, true); }
    };
    try {
      const r = await fetch('/api/chat/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: ctl.signal,
        body: JSON.stringify(Object.assign({ id: conv.id, ticker: c.S.ticker, asof: c.asofDate(), text, web }, c.profile())) });
      if ((r.headers.get('Content-Type') || '').indexOf('event-stream') < 0) { const j = await r.json(); throw new Error(j.error || ('HTTP ' + r.status)); }
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = '';
      for (;;) {
        const x = await reader.read();
        if (x.done) break;
        buf += dec.decode(x.value, { stream: true });
        let k;
        while ((k = buf.indexOf('\n\n')) >= 0) { handle(buf.slice(0, k)); buf = buf.slice(k + 2); }
      }
    } catch (e) {
      if (e.name === 'AbortError') ai.interrupted = true;
      else { ai.error = e.message; if (!ai.text) { conv.messages.pop(); conv.messages.pop(); c.toast('没发出去：' + e.message, true); $('#chatInput').value = text; } }
    }
    streaming = false; ctl = null; ai.streaming = false;
    if (!finished && conv && conv.id) { await new Promise(r => setTimeout(r, 500)); await load(conv.id, true); }      // 中途停了：以后端存下的为准
    if (view === 'chat') showChat(true); else sync();
  }
  function stop() { if (ctl) ctl.abort(); }

  // ---------- 一键解释：程序拼的大白话，作为一条消息放进对话 ----------
  async function explain() {
    if (streaming) return;
    if (!c.stateFresh()) { c.toast('图表还在加载，稍等一下。', true); return; }
    try {
      const r = await c.api('/api/chat/explain', Object.assign({ id: conv && conv.id, ticker: c.S.ticker, asof: c.asofDate() }, c.profile()));
      if (r.ok === false) throw new Error(r.error);
      conv = r.conv; c.store.set('chat.id', conv.id);
      showChat();
      const all = $('#chatBody').querySelectorAll('.cmsg.explain'), last = all[all.length - 1];
      if (last) $('#chatBody').scrollTop = last.offsetTop - 6;
    } catch (e) { c.toast('解释没取到：' + e.message, true); }
  }

  // “指给我看”：把这张卡片讲的那样东西在屏幕上圈出来
  /* 窗口里的东西分在几个页签里：先切到那一页，再圈出来 */
  const SIDE = { sig: ['analyze', '#sigCard'], tiles: ['analyze', '#tiles'], gauge: ['analyze', '#qChartCard'], narr: ['analyze', '#narrCard'], qa: ['analyze', '#qaCard'],
    hist: ['models', '#qHist', '#sigList'] };
  function goSide(tab, sels) {
    c.openSide(); c.setTab(tab);
    setTimeout(() => {
      if (sels.some(outline)) c.toast('已切到「' + (tab === 'models' ? '模型' : '分析') + '」页指给你看。看完点「对话」回来。');
      else c.toast('这一块现在没有显示。');
    }, 60);
  }
  function outline(sel) {
    const t = $(sel); if (!t || t.hidden) return false;
    if (t.tagName === 'DETAILS') t.open = true;
    if (t.closest('#side')) t.scrollIntoView({ block: 'center' });
    t.classList.remove('learn-spot'); void t.offsetWidth; t.classList.add('learn-spot');
    setTimeout(() => t.classList.remove('learn-spot'), 2400);
    return true;
  }
  function spot(key) {
    if (/^ev[0-3]$/.test(key)) { outline('#evidence'); c.flashEvidence(Number(key[2])); return; }
    if (key === 'vol' || key === 'macd') return c.flashPane(key);
    if (key === 'banner') return outline('#banner');
    if (key === 'top') return outline('#topbar');
    if (key === 'chart' || key === 'highlow') return outline('#chartwrap');
    if (key === 'bar') { if (!outline('#qBar')) goSide('analyze', ['#sigCard']); return; }
    if (SIDE[key]) goSide(SIDE[key][0], SIDE[key].slice(1));
  }

  const onState = () => { if (open) sync(); };
  return { init, toggle, shown, onState, send, stop, explain, newChat, showList, isOpen: () => open, conv: () => conv, streaming: () => streaming, md, spot };
})();
