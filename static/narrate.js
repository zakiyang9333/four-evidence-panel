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
    n.steps.forEach((s, k) => {
      const li = el('li', 'n-step' + (s.ok ? ' on' : '')); li.dataset.k = k; li.title = '点一下，在图上看这一问对应的位置';
      li.appendChild(el('i', 'tri', String(s.evidence)));
      const mid = el('div', 'mid');
      mid.appendChild(el('em', 'q', s.q)); mid.appendChild(el('b', 'say', s.say)); mid.appendChild(el('span', 'look', s.look));
      li.appendChild(mid);
      li.appendChild(el('span', 'sticker' + (/证据|站回来|报警/.test(s.sticker) ? ' good' : s.sticker === '不适用' ? ' na' : ''), s.sticker));
      ol.appendChild(li);
    });
    box.appendChild(ol);
    box.appendChild(el('div', 'n-final', n.final));
    const src = res.source === 'claude'
      ? (res.model || 'Claude') + ' · ' + (res.cached ? '上次分析于 ' : '分析于 ') + (res.created_at || '') + (res.positions_sent ? ' · 附了 ' + res.positions_sent + ' 个仓位' : '') +
        (res.cached && res.same_input === false ? ' · 之后数据或仓位变过，可能过时' : '')
      : '模板版 · 不调用 API';
    $('#narrMeta').textContent = src + ' · ' + res.ticker + ' ' + res.asof;
    const nt = $('#narrNotice'); nt.hidden = !res.notice; nt.textContent = res.notice || '';
    const w = $('#narrWatch'); w.textContent = ''; w.hidden = true;
    w.appendChild(el('div', 'w-title', '下一根 K 线看什么'));
    const ul = el('ul'); n.watch.forEach(x => ul.appendChild(el('li', '', x))); w.appendChild(ul);
    $('#aiRun').textContent = '↻ 重播';
    if (animate) { $('#aiSkip').hidden = false; ctx.onReveal(0); timer = setTimeout(step, 450); } else finish();
    sync();
  }

  function step() {
    const items = document.querySelectorAll('#narr .n-step');
    if (shown < items.length) {
      items[shown].classList.add('show'); shown++; ctx.onReveal(shown);
      timer = setTimeout(step, STEP_MS);
    } else finish();
  }
  function finish() {
    clearTimeout(timer);
    document.querySelectorAll('#narr .n-step').forEach(li => li.classList.add('show')); shown = 4;
    const f = $('#narr .n-final'); if (f) f.classList.add('show');
    $('#narrWatch').hidden = !(cur && cur.narration.watch.length);
    $('#aiSkip').hidden = true;
    if (ctx) ctx.onReveal(null);
    sync();
  }
  function pick(k) {
    document.querySelectorAll('#narr .n-step').forEach(li => li.classList.toggle('picked', Number(li.dataset.k) === k));
    ctx.flash(k);
  }

  return { init, reset, sync, run, polish, current: () => cur, shown: () => shown, finish };
})();
