/* 「一键解释」学习面板：点一下，用大白话把现在屏幕上的每样东西讲一遍。
   内容来自 /api/learn（程序按当天的计算结果拼出来的，不调用 AI，不花钱）。这里只负责显示和“指给我看”。
   文字全部用 textContent 写入，不拼 HTML。 */
window.FELearn = (() => {
  'use strict';
  const $ = s => document.querySelector(s);
  let c = null, open = false, data = null, seq = 0;

  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

  function init(ctx) {
    c = ctx;
    $('#learnBtn').onclick = () => toggle(!open);
    if (new URLSearchParams(location.search).get('learn') === '1') toggle(true);
  }

  function toggle(on) {
    open = !!on;
    $('#learn').hidden = !open;
    $('#learnBtn').classList.toggle('on', open);
    c.resized();
    if (open) { render(); fetch(); }
  }

  async function fetch() {
    if (!open || !c.stateFresh()) return;
    const my = ++seq;
    try {
      const r = await c.api('/api/learn?ticker=' + c.S.ticker + '&model=' + c.model() + '&asof=' + c.asofDate());
      if (my !== seq) return;
      if (r.ok === false) throw new Error(r.error);
      data = r; render();
    } catch (e) { if (my === seq) c.toast('解释没取到：' + e.message, true); }
  }
  const onState = () => { if (open) fetch(); };

  function render() {
    const box = $('#learn'), keep = box.scrollTop;
    box.textContent = '';
    const head = el('div', 'learn-head');
    head.appendChild(el('b', '', '一键解释'));
    head.appendChild(el('span', 'muted', data ? data.ticker + ' ' + data.asof + ' · ' + data.model_name + (data.replay ? ' · 回放' : '') : '正在准备…'));
    const x = el('button', '', '✕'); x.title = '收起'; x.onclick = () => toggle(false);
    head.appendChild(el('span', 'spacer')); head.appendChild(x);
    box.appendChild(head);
    if (!data) return;
    const body = el('div', 'learn-body');
    body.appendChild(el('p', 'learn-lead', '下面把屏幕上的东西从上到下讲一遍。每张卡片先说“这是什么”，再说“今天它是什么情况”。'));
    const hl = el('div', 'learn-hl ' + data.headline.tone);
    hl.appendChild(el('small', '', '今天的一句话'));
    hl.appendChild(el('b', '', data.headline.text));
    hl.appendChild(el('span', '', data.headline.sub));
    body.appendChild(hl);
    data.cards.forEach((k, n) => {
      const a = el('article', 'lcard' + (k.ok === true ? ' yes' : k.ok === false ? ' no' : ''));
      a.dataset.id = k.id;
      const h = el('h4'); h.appendChild(el('i', '', String(n + 1))); h.appendChild(document.createTextNode(k.title));
      a.appendChild(h);
      a.appendChild(el('p', '', k.body));
      if (k.now) { const d = el('div', 'lnow'); d.appendChild(el('span', '', '今天')); d.appendChild(document.createTextNode(k.now)); a.appendChild(d); }
      if (k.items && k.items.length) {
        const ul = el('ul', 'litems');
        k.items.forEach(it => { const li = el('li', it.ok ? 'yes' : 'no'); li.appendChild(el('b', '', (it.ok ? '是 · ' : '否 · ') + it.name)); li.appendChild(el('span', '', it.text)); ul.appendChild(li); });
        a.appendChild(ul);
      }
      if (k.note) a.appendChild(el('p', 'lnote', k.note));
      if (k.spot) { const b = el('button', 'lspot', '指给我看'); b.dataset.spot = k.spot; b.onclick = () => spot(k.spot); a.appendChild(b); }
      body.appendChild(a);
    });
    const g = el('details', 'lgloss');
    g.appendChild(el('summary', '', '名词小词典（' + data.glossary.length + ' 个）'));
    const dl = el('dl');
    data.glossary.forEach(w => { dl.appendChild(el('dt', '', w[0])); dl.appendChild(el('dd', '', w[1])); });
    g.appendChild(dl); body.appendChild(g);
    body.appendChild(el('p', 'lfoot', data.footer));
    box.appendChild(body);
    box.scrollTop = keep;
  }

  // “指给我看”：把这张卡片讲的那样东西在屏幕上圈出来
  const SIDE = { sig: '#sigCard', tiles: '#tiles', gauge: '#qScore', narr: '#narrCard', hist: '#qHist' };
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
    if (key === 'bar') { if (!outline('#qBar')) { c.openSide(); outline('#sigCard'); } return; }
    if (SIDE[key]) { c.openSide(); if (!outline(SIDE[key])) c.toast('这一块现在没有显示。'); }
  }

  return { init, toggle, onState, isOpen: () => open, data: () => data, spot };
})();
