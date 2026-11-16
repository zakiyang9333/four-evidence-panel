/* 视频式解说：一句定性 → 四问依次出现（量 → MACD → 扇子 → 成本线）→ 大字结论。
   文字来自 /api/ai/narrate（模板版，免费）或 /api/ai/analyze（Claude 润色）。
   记忆：Claude 的每次解说都存在本机。切回这只标的这一天、重开面板，直接显示保存的那一版，不再调用 API；
   盘面和仓位没变时想重新分析，要点两次确认。
   哪一问成立、亮不亮，用的是后端按引擎结果填好的 ok，不看文字。全部文字用 textContent 写入，不拼 HTML。 */
window.FENarrate = (() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const STEP_MS = 1000;
  let ctx = null, cur = null, timer = 0, shown = 0, busy = false, seq = 0, armed = 0, tried = '';

  const kilo = n => n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

  function init(c) {
    ctx = c;
    $('#aiRun').onclick = run;
    $('#aiPolish').onclick = () => polish(ctx.fake());
    $('#aiSkip').onclick = () => finish();
    $('#narr').addEventListener('click', e => { const li = e.target.closest('.n-step'); if (li && li.classList.contains('show')) pick(Number(li.dataset.k)); });
  }

  function reset() {            // 图表换了标的或日期：这段解说不再对应当前状态
    seq++; clearTimeout(timer); clearTimeout(armed); armed = 0; tried = ''; cur = null; shown = 0; busy = false;
    $('#narr').hidden = true; $('#narr').textContent = ''; $('#narrNotice').hidden = true; $('#narrWatch').hidden = true;
    $('#narrMeta').textContent = ''; $('#aiPolish').hidden = true; $('#aiSkip').hidden = true; $('#narrSrc').hidden = true;
    $('#aiRun').textContent = '✦ AI 分析';
    if (ctx) { ctx.onReveal(null); ctx.clearFlash(); }
    sync();
  }

  function sync() {             // 按钮可用状态
    const ready = ctx && ctx.ready();
    $('#aiRun').disabled = !ready || busy;
    const p = cur && cur.polish, b = $('#aiPolish');
    b.classList.toggle('arm', !!armed);
    if (cur && p) {
      b.hidden = false; b.disabled = busy || !p.enabled || !ready;
      b.textContent = armed ? '盘面没变，再点一次确认（会再次计费）' : cur.source !== 'claude' ? '让 Claude 润色（会计费）'
        : upToDate() ? '重新分析' : '按新数据重新分析（会计费）';
      b.title = p.enabled ? '把引擎事实交给 ' + p.model + ' 分析；数字会逐个核对，结论仍以引擎为准' : p.reason;
    }
    $('#aiHint').textContent = !cur ? (ctx && ctx.model() === 'houshou' ? '按后手战法的三问走一遍，再看一眼表盘。先出模板版，不花钱。' : '按视频的四问走一遍：量 → MACD → 扇子 → 成本线。先出模板版，不花钱。')
      : p && !p.enabled ? p.reason
      : cur.source === 'claude' ? (upToDate() ? '这一版已存在本机：重播、切换标的、重开面板都不再计费。' : '这一版保存之后，数据或仓位变过。')
      : (p && p.positions ? '润色时会附上这只标的相关的 ' + p.positions + ' 个仓位，不发整份账户。' : '');
  }

  // 现在显示的是 Claude 的解说，而且之后盘面和仓位都没变过
  const upToDate = () => !!cur && cur.source === 'claude' && cur.same_input !== false;

  async function restore() {    // 记忆：这只标的这一天保存过 Claude 的解说，就直接显示（不播动画、不调用 API）
    if (!ctx || cur || busy || !ctx.ready() || !ctx.saved()) return;
    const key = ctx.ticker() + ' ' + ctx.asof();
    if (tried === key) return;
    tried = key;
    const my = seq;
    try {
      const r = await ctx.api('/api/ai/narrate?ticker=' + ctx.ticker() + '&asof=' + ctx.asof() + '&model=' + ctx.model());
      if (my !== seq || cur || busy || !r.polished) return;
      show(Object.assign({}, r.polished, { polish: r.polish }), false);
    } catch (e) { /* 取不到就算了，点“AI 分析”还能再取 */ }
  }

  async function run() {        // “AI 分析”：保存过 Claude 的解说就用它（免费），没有才出模板版
    if (busy || !ctx.ready()) return;
    const my = ++seq; busy = true; sync();
    try {
      const r = await ctx.api('/api/ai/narrate?ticker=' + ctx.ticker() + '&asof=' + ctx.asof() + '&model=' + ctx.model());
      if (my !== seq) return;
      const use = r.polished ? Object.assign({}, r.polished, { polish: r.polish }) : r;
      busy = false; show(use, true);
    } catch (e) { busy = false; ctx.toast('解说没取到：' + e.message, true); sync(); }
  }

  async function polish(fake) { // “让 Claude 润色” / “重新分析”
    if (busy || !ctx.ready() || !cur) return;
    if (upToDate() && !fake && !armed) {     // 盘面没变还要再分析一次：先问一句，5 秒内再点才真的去调用
      armed = setTimeout(() => { armed = 0; sync(); }, 5000); sync(); return;
    }
    const force = cur.source === 'claude';   // 已经有 Claude 的版本还点，才是明确要重新分析；否则后端有保存的就直接给
    clearTimeout(armed); armed = 0;
    const my = ++seq, keep = cur.polish; busy = true; sync();
    const t0 = Date.now(), tick = setInterval(() => { $('#narrMeta').textContent = 'Claude 正在写… ' + Math.round((Date.now() - t0) / 1000) + ' 秒'; }, 500);
    try {
      const r = await ctx.api('/api/ai/analyze', { ticker: ctx.ticker(), asof: ctx.asof(), test_fake_number: !!fake, force, model: ctx.model() });
      clearInterval(tick);
      if (my !== seq) return;
      busy = false;
      if (r.ok === false) { ctx.toast(r.error || '润色失败', true); show(cur, false); return; }
      r.polish = keep; show(r, true);
      if (r.reused) ctx.toast('盘面和仓位都没变，用的是保存的那一版，没有再计费。');
    } catch (e) { clearInterval(tick); busy = false; ctx.toast('润色失败：' + e.message, true); show(cur, false); }
  }

  function show(res, animate) {
    clearTimeout(timer); clearTimeout(armed); armed = 0; cur = res; shown = 0; ctx.clearFlash();
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
      // 模板版的 look 是一行事实，照常显示；Claude 版不显示成段的数字（证据画在图上），老格式里的那段话只放进悬停提示
      const wordy = res.source === 'claude';
      li.title = '点一下，在图上把这一步的证据画出来；再点一次取消' + (wordy && s.look ? '\n\n' + s.look : '');
      li.appendChild(el('i', 'tri', ev ? String(ev) : '·'));
      const mid = el('div', 'mid');
      const lk = mark(el('span', 'look'), s.look || ''); lk.hidden = wordy || !s.look;
      mid.appendChild(el('em', 'q', s.q)); mid.appendChild(mark(el('b', 'say'), s.say)); mid.appendChild(lk);
      if ((s.draw || []).length) mid.appendChild(el('span', 'has-draw', '▶ 图上 ' + s.draw.length + ' 处标记'));
      li.appendChild(mid);
      const tone = s.tone || (/证据|站回来|报警/.test(s.sticker) ? 'good' : s.sticker === '不适用' ? 'neutral' : 'bad');
      if (s.sticker) li.appendChild(el('span', 'sticker' + (tone === 'good' ? ' good' : tone === 'neutral' ? ' na' : ''), s.sticker));
      ol.appendChild(li);
    });
    box.appendChild(ol);
    box.appendChild(mark(el('div', 'n-final'), n.final));
    const src = res.source === 'claude'
      ? (res.model || 'Claude') + ' · ' + (res.cached ? '保存于 ' : '分析于 ') + (res.created_at || '') + (res.positions_sent ? ' · 附了 ' + res.positions_sent + ' 个仓位' : '') +
        (res.tokens_in != null && res.tokens_out != null ? ' · 用了 ' + kilo(res.tokens_in) + ' 入 + ' + kilo(res.tokens_out) + ' 出 token' : '') +
        (res.cached && res.same_input === false ? ' · 之后数据或仓位变过，可能过时' : '')
      : '模板版 · 不调用 API';
    $('#narrMeta').textContent = src + ' · ' + res.ticker + ' ' + res.asof;
    const tag = $('#narrSrc'); tag.hidden = false; tag.textContent = res.source === 'claude' ? 'Claude' : '模板'; tag.className = 'qtag' + (res.source === 'claude' ? ' pos' : '');
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
      highlight(shown - 1, true);          // 卡片一出来，图上同步把这一步的证据画出来
      const n = ((cur.narration.steps[shown - 1] || {}).draw || []).length;
      timer = setTimeout(step, n ? Math.max(STEP_MS, n * 520 + 1100) : STEP_MS);      // 等这一步画完再出下一张
    } else finish(true);
  }
  function finish(keep) {
    clearTimeout(timer);
    const all = document.querySelectorAll('#narr .n-step');
    all.forEach(li => { li.classList.add('show'); if (keep !== true) li.classList.remove('picked'); }); shown = all.length;
    if (keep !== true && ctx) ctx.clearFlash();
    const f = $('#narr .n-final'); if (f) f.classList.add('show');
    $('#narrWatch').hidden = !(cur && cur.narration.watch.length);
    $('#aiSkip').hidden = true;
    if (ctx) ctx.onReveal(null);
    sync();
  }
  function pick(k) { highlight(k, false); }
  /* 在图上画出第 k 步的证据。auto = 解说播放到这一步时自动画；手动点同一张第二次是取消。
     四要素里的某一项有固定位置；Claude 给了画图指令就按指令一笔一笔画；老格式没有指令的，从那段文字里读日期和价位。 */
  function highlight(k, auto) {
    let ev = 0, text = '', on = false;
    document.querySelectorAll('#narr .n-step').forEach(li => {
      const me = Number(li.dataset.k) === k;
      if (me) { on = auto || !li.classList.contains('picked'); ev = Number(li.dataset.ev); text = li.querySelector('.say').textContent + ' ' + li.querySelector('.look').textContent; }
      li.classList.toggle('picked', me && on);
    });
    const s = cur && cur.narration.steps[k];
    ctx.flash(ev ? ev - 1 : null, text, 'step' + k, (s && s.draw) || [], auto);
  }

  return { init, reset, sync, run, restore, polish, show, current: () => cur, shown: () => shown, finish };
})();
