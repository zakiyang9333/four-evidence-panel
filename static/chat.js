/* AI 对话：一边看图一边问。住在「AI 量化」窗口的「对话」页签里。
   2026-11-18 按 zaki 的意思重做（“AI 问答窗口存在大量无用信息”）：
   - 页面上只有对话：你问、它答。程序拼的说明卡片（以前的「一键解释」）不进对话：旧卡片留在文件里，不显示、不发给 AI、不进历史。
   - 顶上一行写明它在看哪张图（标的、日期、模型、日 K / 周 K）。图在对话中途换过，才在那一问前面画一条分隔线，不在每条消息下面重复。
   - 开场的三个问题跟着这张图走（条件齐 / 还差几项 / 用不上 / 观察模型各不相同），问出第一句就收起来。
   - 不逐条列 token。整段对话问了几次、用了多少，写在「历史」列表里那一行。
   - 「联网查」只管下一问：发出去就自动关掉，回答下面列出处。
   - 回答一个字一个字流出来；整段对话存在本机，关掉再开还能接着聊。
   模型写的内容一律当作文字处理：自己解析 Markdown 并用 textContent 建节点，不把任何内容当 HTML 插进页面。 */
window.FEChat = (() => {
  'use strict';
  const $ = s => document.querySelector(s);
  let c = null, open = false, conv = null, streaming = false, ctl = null, view = 'chat', chats = [], web = false, paintQueued = false, liveBubble = null, liveMsg = null;

  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const kilo = n => n >= 10000 ? (n / 10000).toFixed(1) + ' 万' : n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n || 0);
  const asks = cv => cv ? cv.messages.filter(m => m.role === 'user').length : 0;

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

  // ---------- 它在看哪张图；开场问题跟着这张图走 ----------
  const quant = () => { const d = window.FEQuant && window.FEQuant.data && window.FEQuant.data(); return d && d.ticker === c.S.ticker ? d : null; };
  function ctxText() {
    const d = quant(), day = c.asofDate ? c.asofDate() : '';
    const parts = [c.S.ticker, day ? day.slice(5) : ''];
    if (d) parts.push(d.model_name + (d.side === 'short' ? ' · ' + d.side_name : ''));
    parts.push(c.S.tf === 'W' ? '周K' : '日K');
    return '它在看：' + parts.filter(Boolean).join(' · ') + (d && d.is_latest === false ? '（回放到这一天）' : '');
  }
  function starters() {
    const d = quant(), s = d && d.signal;
    if (!s) return ['现在这张图最该看什么？', '今天的结论会被什么推翻？', '最近的关键价位在哪？'];
    if (d.kind === 'watch') return ['现在是什么状态？', '什么变化会改变这个判断？', '该盯哪个价位？'];
    if (s.unsupported || s.state === 'na') return ['为什么今天用不上这套清单？', '现在这张图最该看什么？', '换哪个模型更合适？'];
    if (s.state === 'ready') return ['这次条件齐在哪几处？', '止损和目标为什么放在那里？', '什么情况下这次作废？'];
    if (s.state === 'dead') return ['这个结构为什么失效了？', '接下来该看哪个位置？', '现在这张图最该看什么？'];
    if (s.state === 'avoid') return ['为什么说不追？', '等回到哪里才能再看？', '什么情况下这个判断作废？'];
    const miss = (s.checks || []).filter(x => !x.ok).length;
    return [miss === 1 ? '还缺的那一项是什么？' : miss ? '还缺的 ' + miss + ' 项是什么？' : '还差什么？', '差的那几项离成立还有多远？', '什么情况下这个判断作废？'];
  }
  function renderTop() {
    $('#chatCtx').textContent = ctxText();
    const q = $('#chatQuick'), want = view === 'chat' && !asks(conv) && !streaming;
    q.hidden = !want;
    if (!want) return;
    const list = starters(), ok = c.aiEnabled();
    if (q.dataset.k !== list.join('|')) {
      q.textContent = ''; q.dataset.k = list.join('|');
      list.forEach(t => { const b = el('button', '', t); b.onclick = () => send(t); q.appendChild(b); });
    }
    [...q.querySelectorAll('button')].forEach(b => { b.disabled = !ok; });
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
    const rb = el('button', '', '我的规则'); rb.id = 'chatRulesBtn'; rb.title = '你自己的规则：问挂单、止损、要不要调时，它照这里一条条推演'; rb.onclick = editRules;
    const xb = el('button', '', '✕'); xb.id = 'chatClose'; xb.title = '回到「分析」页'; xb.onclick = () => toggle(false);
    head.appendChild(rb); head.appendChild(hb); head.appendChild(nb); head.appendChild(xb);
    const cx = el('div', 'chat-ctx'); cx.id = 'chatCtx'; cx.title = '提问时，它拿到的是这张图的数据。换了标的、日期或模型，下一问会自动带上新的一份';
    const body = el('div', 'chat-body'); body.id = 'chatBody';
    const quick = el('div', 'chat-quick'); quick.id = 'chatQuick';
    const form = el('form', 'chat-form'); form.id = 'chatForm';
    const ta = el('textarea'); ta.id = 'chatInput'; ta.rows = 2; ta.maxLength = 4000;
    const row = el('div', 'chat-row');
    const wl = el('label', 'chat-web'); const wc = el('input'); wc.type = 'checkbox'; wc.id = 'chatWeb'; wc.onchange = () => { web = wc.checked; };
    wl.appendChild(wc); wl.appendChild(document.createTextNode(' 联网查（只管下一问）'));
    wl.title = '勾上以后，下一问它可以上网查（按次另外计费），回答下面列出处。问完自动关掉。不勾的话，它只知道图表数据和备注里有的';
    const sb = el('button', 'primary', '发送'); sb.id = 'chatSend'; sb.type = 'submit';
    row.appendChild(wl); row.appendChild(el('span', 'spacer')); row.appendChild(sb);
    form.appendChild(ta); form.appendChild(row);
    form.addEventListener('submit', e => { e.preventDefault(); if (streaming) stop(); else { const t = ta.value; if (t.trim()) { ta.value = ''; send(t); } } });
    ta.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); } });
    box.appendChild(head); box.appendChild(cx); box.appendChild(body); box.appendChild(quick); box.appendChild(form);
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
  /* 页签被点开或离开时，窗口那边会告诉这里一声。上一段对话里一句提问都没有（只有旧卡片），就从新对话开始 */
  function shown(on) {
    open = !!on;
    $('#learn').hidden = !open;
    $('#chatBtn').classList.toggle('on', open);
    if (!open) return pending;
    pending = (async () => {
      if (!conv) { const id = c.store.get('chat.id', null); if (id) await load(id, true); }
      if (conv && !asks(conv)) { conv = null; c.store.set('chat.id', null); }
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
    $('#chatTitle').textContent = view === 'list' ? '以前的对话' : '';
    $('#chatHistBtn').textContent = view === 'list' ? '返回' : '历史';
    $('#chatSend').textContent = streaming ? '停止' : '发送';
    $('#chatSend').classList.toggle('stop', streaming);
    $('#chatInput').disabled = !ok; $('#chatSend').disabled = !ok && !streaming;
    $('#chatInput').placeholder = ok ? '问点什么。回车发送，Shift + 回车换行（调用 Claude，按用量计费）' : '没有设置 API 密钥，不能提问';
    $('#chatForm').hidden = view === 'list'; $('#chatCtx').hidden = view === 'list';
    renderTop();
  }

  function msgNode(m) {
    const w = el('div', 'cmsg ' + (m.role === 'user' ? 'user' : 'ai'));
    if (m.role === 'user') { w.appendChild(el('div', 'bubble', m.text)); return w; }
    const b = el('div', 'bubble md');
    if (m.text) b.appendChild(md(m.text)); else if (m.streaming) b.appendChild(el('span', 'typing', '正在想…'));
    w.appendChild(b);
    const meta = m.meta || {};
    if (meta.sources && meta.sources.length) {
      const s = el('div', 'cx-src'); s.appendChild(el('span', '', (meta.auto_web ? '自动联网' : '联网') + '查到的出处：'));
      meta.sources.forEach(x => { if (/^https?:\/\//i.test(x.url)) { const a = el('a', '', x.title || x.url); a.href = x.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; s.appendChild(a); } });
      w.appendChild(s);
    }
    const bits = [];               // 只留读的人用得上的：答到一半停了、太长被截断、出错、自动联网了却没查到出处
    if (meta.auto_web && !(meta.sources && meta.sources.length)) bits.push('自动联网查过，没找到能用的出处');
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
    if (!conv || !asks(conv)) {
      body.appendChild(el('div', 'chat-empty', '有什么想问这张图的，直接问。'));
    } else {
      let first = true;
      conv.messages.forEach(m => {
        if (m.kind === 'explain') return;            // 旧的「一键解释」卡片：不进对话
        if (m.role === 'user') {
          if (m.chip && !first) body.appendChild(el('div', 'cx-div', '换到 ' + m.chip));      // 图在对话中途换过：画一条分隔线
          first = false;
        }
        body.appendChild(msgNode(m));
      });
    }
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
      const b = el('button', 'open'); b.appendChild(el('b', '', x.title));
      b.appendChild(el('small', 'muted', String(x.updated || '').slice(5, 16) + (x.ticker ? ' · ' + x.ticker : '') + ' · ' + (x.asks || 0) + ' 问' + (x.tokens ? ' · 用了约 ' + kilo(x.tokens) + ' token' : '')));
      b.title = '用量 = 发给模型的内容（图表数据和前面的对话）加上它写的回答。前面聊过的部分走缓存，只按原价的一小部分计费';
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
    const mine = { role: 'user', text }, ai = { role: 'assistant', text: '', streaming: true }, useWeb = web;
    web = false; $('#chatWeb').checked = false;         // 联网查只管这一问：发出去就关掉
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
        body: JSON.stringify(Object.assign({ id: conv.id, ticker: c.S.ticker, asof: c.asofDate(), text, web: useWeb }, c.profile())) });
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

  // ---------- 我的规则：他自己写、自己改；对话回答挂单、止损这类问题时照着推演 ----------
  async function editRules() {
    let r;
    try { r = await c.api('/api/rules'); if (r.ok === false) throw new Error(r.error); } catch (e) { c.toast('规则没取到：' + e.message, true); return; }
    $('#modalTitle').textContent = '我的规则';
    const body = $('#modalBody'); body.textContent = '';
    body.appendChild(el('p', 'fine', '写成短句，一条一行。问挂单、止损、要不要调时，AI 照这里推演：现价落在哪、离你的线多远、碰到哪条算触发；改不改由你定。没写的情形，它会说你的规则没写。'));
    const ta = el('textarea', 'rules-edit'); ta.id = 'rulesText'; ta.rows = 16; ta.maxLength = 6000; ta.value = r.text; body.appendChild(ta);
    const row = el('div', 'chat-row'), save = el('button', 'primary', '保存'); save.id = 'rulesSave';
    row.appendChild(el('span', 'muted', r.saved ? '' : '这是起步的模板，保存之后才算数')); row.appendChild(el('span', 'spacer')); row.appendChild(save); body.appendChild(row);
    save.onclick = async () => {
      try { const x = await c.api('/api/rules', { text: ta.value }); if (x.ok === false) throw new Error(x.error); $('#modal').hidden = true; c.toast('规则存好了：下一问起照新的推演。'); }
      catch (e) { c.toast('没存成：' + e.message, true); }
    };
    $('#modal').hidden = false; ta.focus();
  }

  const onState = () => { if (open) renderTop(); };      // 换了标的、日期、模型：顶上那一行和开场问题跟着变
  return { init, toggle, shown, onState, send, stop, newChat, showList, editRules, isOpen: () => open, conv: () => conv, streaming: () => streaming, md, starters, ctxText };
})();
