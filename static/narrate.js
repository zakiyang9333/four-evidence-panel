/* 视频式解说：一句定性 → 四问依次出现（量 → MACD → 扇子 → 成本线）→ 大字结论。
   文字来自 /api/ai/narrate（模板版，免费）或 /api/ai/analyze（Claude 润色）。
   哪一问成立、亮不亮，用的是后端按引擎结果填好的 ok，不看文字。全部文字用 textContent 写入，不拼 HTML。 */
window.FENarrate = (() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const STEP_MS = 1000;
  let ctx = null, cur = null, timer = 0, shown = 0, busy = false, seq = 0;

  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

  function init(c) {
    ctx = c;
    $('#aiRun').onclick = run;
    $('#aiPolish').onclick = () => polish(ctx.fake());
    $('#aiSkip').onclick = () => finish();
    $('#narr').addEventListener('click', e => { const li = e.target.closest('.n-step'); if (li && li.classList.contains('show')) pick(Number(li.dataset.k)); });
  }

  function reset() {            // 图表换了标的或日期：这段解说不再对应当前状态
    seq++; clearTimeout(timer); cur = null; shown = 0; busy = false;
    $('#narr').hidden = true; $('#narr').textContent = ''; $('#narrNotice').hidden = true; $('#narrWatch').hidden = true;
    $('#narrMeta').textContent = ''; $('#aiPolish').hidden = true; $('#aiSkip').hidden = true;
    $('#aiRun').textContent = '✦ AI 分析';
    if (ctx) ctx.onReveal(null);
    sync();
  }

  function sync() {             // 按钮可用状态
    const ready = ctx && ctx.ready();
    $('#aiRun').disabled = !ready || busy;
    const p = cur && cur.polish, b = $('#aiPolish');
    if (cur && p) {
      b.hidden = false; b.disabled = busy || !p.enabled || !ready;
      b.textContent = cur.source === 'claude' ? '重新分析（会再次计费）' : '让 Claude 润色（会计费）';
      b.title = p.enabled ? '把引擎事实交给 ' + p.model + ' 重写措辞；数字会逐个核对，结论仍以引擎为准' : p.reason;
    }
    $('#aiHint').textContent = !cur ? '按视频的四问走一遍：量 → MACD → 扇子 → 成本线。先出模板版，不花钱。'
      : (p && !p.enabled ? p.reason : (p && p.positions && cur.source !== 'claude' ? '润色时会附上这只标的相关的 ' + p.positions + ' 个仓位，不发整份账户。' : ''));
  }

  async function run() {        // “AI 分析”：先出模板版（或上次润色过、输入没变的那一版）
    if (busy || !ctx.ready()) return;
    const my = ++seq; busy = true; sync();
    try {
      const r = await ctx.api('/api/ai/narrate?ticker=' + ctx.ticker() + '&asof=' + ctx.asof());
      if (my !== seq) return;
      const use = (r.polished && r.polished.same_input) ? Object.assign({}, r.polished, { polish: r.polish }) : r;
      busy = false; show(use, true);
    } catch (e) { busy = false; ctx.toast('解说没取到：' + e.message, true); sync(); }
  }

  async function polish(fake) { // “让 Claude 润色”
    if (busy || !ctx.ready() || !cur) return;
    const my = ++seq, keep = cur.polish; busy = true; sync();
    const t0 = Date.now(), tick = setInterval(() => { $('#narrMeta').textContent = 'Claude 正在写… ' + Math.round((Date.now() - t0) / 1000) + ' 秒'; }, 500);
    try {
      const r = await ctx.api('/api/ai/analyze', { ticker: ctx.ticker(), asof: ctx.asof(), test_fake_number: !!fake });
      clearInterval(tick);
      if (my !== seq) return;
      busy = false;
      if (r.ok === false) { ctx.toast(r.error || '润色失败', true); show(cur, false); return; }
      r.polish = keep; show(r, true);
    } catch (e) { clearInterval(tick); busy = false; ctx.toast('润色失败：' + e.message, true); show(cur, false); }
  }

  function show(res, animate) {
    clearTimeout(timer); cur = res; shown = 0;
    const n = res.narration, box = $('#narr');
    box.textContent = ''; box.hidden = false;
    box.appendChild(el('div', 'n-hook', n.hook));
    box.appendChild(el('div', 'n-story', n.story));
    const ol = el('ol', 'n-steps');
    const bad = res.unverified || [];
    const mark = (node, text) => {          // 核对不上的数字标黄（只包一层 span，文字仍用 textContent）
      if (!bad.length) { node.textContent = text; return node; }
      const re = new RegExp('(?<![\\d.])(' + bad.map(b => b.replace('.', '\\.')).join('|') + ')(?![\\d.])', 'g');
      let last = 0, m;
      while ((m = re.exec(text))) {
        node.appendChild(document.createTextNode(text.slice(last, m.index)));
        const sp = el('span', 'unv', m[0]); sp.title = '这个数字在引擎输出和 K 线数据里找不到，可能是 Claude 自己算的'; node.appendChild(sp);
        last = m.index + m[0].length;
      }
      node.appendChild(document.createTextNode(text.slice(last)));
      return node;
    };
    box.querySelector('.n-hook').textContent = ''; mark(box.querySelector('.n-hook'), n.hook);
    box.querySelector('.n-story').textContent = ''; mark(box.querySelector('.n-story'), n.story);
    n.steps.forEach((s, k) => {
      const ev = s.evidence >= 1 && s.evidence <= 4 ? s.evidence : 0;
      const li = el('li', 'n-step' + (s.ok ? ' on' : '') + (ev ? '' : ' free')); li.dataset.k = k; li.dataset.ev = ev;
      li.title = ev ? '点一下，在图上看这一项证据对应的位置' : 'Claude 自己选的观察点，不对应四要素里的某一项';
      li.appendChild(el('i', 'tri', ev ? String(ev) : '·'));
      const mid = el('div', 'mid');
      mid.appendChild(el('em', 'q', s.q)); mid.appendChild(mark(el('b', 'say'), s.say)); mid.appendChild(mark(el('span', 'look'), s.look));
      li.appendChild(mid);
      const tone = s.tone || (/证据|站回来|报警/.test(s.sticker) ? 'good' : s.sticker === '不适用' ? 'neutral' : 'bad');
      if (s.sticker) li.appendChild(el('span', 'sticker' + (tone === 'good' ? ' good' : tone === 'neutral' ? ' na' : ''), s.sticker));
      ol.appendChild(li);
    });
    box.appendChild(ol);
    box.appendChild(mark(el('div', 'n-final'), n.final));
    const src = res.source === 'claude'
      ? (res.model || 'Claude') + ' · ' + (res.cached ? '上次分析于 ' : '分析于 ') + (res.created_at || '') + (res.positions_sent ? ' · 附了 ' + res.positions_sent + ' 个仓位' : '') +
        (res.cached && res.same_input === false ? ' · 之后数据或仓位变过，可能过时' : '')
      : '模板版 · 不调用 API';
    $('#narrMeta').textContent = src + ' · ' + res.ticker + ' ' + res.asof;
    const nt = $('#narrNotice'); nt.hidden = !res.notice; nt.textContent = res.notice || '';
    const w = $('#narrWatch'); w.textContent = ''; w.hidden = true;
    w.appendChild(el('div', 'w-title', '下一根 K 线看什么'));
    const ul = el('ul'); n.watch.forEach(x => ul.appendChild(mark(el('li', ''), x))); w.appendChild(ul);
    $('#aiRun').textContent = '↻ 重播';
    if (animate) { $('#aiSkip').hidden = false; ctx.onReveal([]); timer = setTimeout(step, 450); } else finish();
    sync();
  }

  // 已经出现的卡片讲到了四要素里的哪几项：证据条只亮这几项（Claude 可能不按 1–4 的顺序讲，也可能不全讲）
  const revealed = () => [...document.querySelectorAll('#narr .n-step.show')].map(li => Number(li.dataset.ev)).filter(Boolean);
  function step() {
    const items = document.querySelectorAll('#narr .n-step');
    if (shown < items.length) {
      items[shown].classList.add('show'); shown++; ctx.onReveal(revealed());
      timer = setTimeout(step, STEP_MS);
    } else finish();
  }
  function finish() {
    clearTimeout(timer);
    const all = document.querySelectorAll('#narr .n-step');
    all.forEach(li => li.classList.add('show')); shown = all.length;
    const f = $('#narr .n-final'); if (f) f.classList.add('show');
    $('#narrWatch').hidden = !(cur && cur.narration.watch.length);
    $('#aiSkip').hidden = true;
    if (ctx) ctx.onReveal(null);
    sync();
  }
  function pick(k) {
    let ev = 0;
    document.querySelectorAll('#narr .n-step').forEach(li => { const me = Number(li.dataset.k) === k; li.classList.toggle('picked', me); if (me) ev = Number(li.dataset.ev); });
    if (ev) ctx.flash(ev - 1);         // 只有对应四要素某一项的卡片，图上才有固定的位置可以高亮
  }

  return { init, reset, sync, run, polish, current: () => cur, shown: () => shown, finish };
})();
