/* 「AI 量化」窗口（照录屏的版式）：窗口头部（K 线级别、量化终端、显示设置、放宽、收起）、四个页签（分析 / 对话 / 模型 / 任务）、
   分析卡（模型、周期、持仓、做多 / 做空、大按钮）、四步进度、当前图表表盘、规则模型信号卡和六格、图上的叠加和逐条画出的线、编号图例、右键设成本锚点。
   五个输入（模型、方向、周期、持仓、K 线级别）每一个都会跟着请求发到后端重算：这里只负责显示，不算任何规则。
   全部数字来自 /api/quant（规则代码算的）。文字用 textContent 或先转义再拼。 */
window.FEQuant = (() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const NUM = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮';
  const SPEED = { fast: 60, normal: 150, slow: 320 };          // 划线那一步：每条间隔（毫秒）
  const COL = { res: '#f87171', sup: '#34d399', fib: '#8b93a5', tres: '#fb7185', tsup: '#2dd4bf', zone: '#34d399', stop: '#a78bfa', push: '#a78bfa', abcd: '#2dd4bf', anchor: '#60a5fa',
    target: '#f472b6', target2: '#f9a8d4', level: '#fb923c' };
  const MODELS = [['four', '四证·抄底 v1.0'], ['houshou', '后手·成本线回踩 v0.2'], ['breakout', '破位反抽 v0.1']];
  const HZ = [20, 60, 120], HZ_NAME = { 20: '短线', 60: '中线', 120: '长线' };
  const POS = ['auto', 'flat', 'long', 'short'], POS_NAME = { auto: '跟随账户', flat: '未持仓（假设）', long: '持有多单（假设）', short: '持有空单（假设）' };
  const TABS = ['analyze', 'chat', 'models', 'tasks'];
  const STATE_CLS = { ready: 'ready', wait: 'wait', avoid: 'avoid', na: 'na', dead: 'dead' };
  const ARROW = { long: '<svg viewBox="0 0 24 24"><path d="M4 16l6-6 4 4 6-7M15 7h5v5"/></svg>', short: '<svg viewBox="0 0 24 24"><path d="M4 8l6 6 4-4 6 7M15 17h5v-5"/></svg>' };
  const CLOCK = '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/></svg>';
  let c = null;
  const Q = { model: 'four', side: 'long', hz: 20, pos: 'auto', tab: 'analyze', wide: false, data: null, seq: 0, linesOn: false, shown: 1e9, running: false, off: {}, steps: null, total: null,
    animUntil: 0, speed: 'normal', autoScroll: true, legendOn: true, lib: null, scan: null, scanKey: '', tasks: null, tasksAt: 0, runs: null, ranOnce: false,
    auto: false, autoRes: null, autoSeq: 0 };
  /* 「自动匹配」：模型下拉最上面那一项。选上以后，点做多 / 做空就按现在的走势挑这一侧的模型（后端 /api/quant/auto 用模型自己的判定排序），
     图上换成排第一的那个，上面列出这一侧认得出这段走势的全部模型。只是挑着看，不会替你交易 */
  const AUTO = '__auto';

  const esc = s => c.esc(s);
  const tf = () => c.S.tf === 'W' ? 'W' : 'D';
  const profile = () => ({ model: Q.model, side: Q.side, hz: Q.hz, tf: tf(), pos: Q.pos });
  const query = () => '&model=' + Q.model + '&side=' + Q.side + '&hz=' + Q.hz + '&tf=' + tf() + '&pos=' + Q.pos;
  const fresh = () => !!(Q.data && c.stateFresh() && Q.data.ticker === c.S.ticker && Q.data.asof === c.asofDate() && Q.data.model_key === Q.model && Q.data.side === Q.side &&
    Q.data.horizon.n === Q.hz && Q.data.tf === tf() && Q.data.position.mode === Q.pos);
  /* 四证自己的证据条、自动画的扇子和成本线，只在「四证 · 做多」时显示：换了模型或方向就先收起来，免得两套东西混在一张图上 */
  const hideFour = () => Q.model !== 'four' || Q.side !== 'long';
  const fourOwn = () => fresh() && Q.data.model_key === 'four' && !Q.data.signal.unsupported;       // 信号卡由 app.js 按引擎输出画的那种情况
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const num = n => (n && NUM[n - 1]) || '';
  const legendN = key => { const x = fresh() && Q.data.legend.find(l => l.key === key); return x ? x.n : 0; };
  const kindOf = k => (MODELS.find(x => x[0] === k) || [])[3] || 'trade';
  const watch = () => kindOf(Q.model) === 'watch';            // 观察用的模型（等回头、阴跌雷达、睡得着、回本三看）：按钮叫上行 / 下行，没有六格
  const hzLabel = n => watch() ? HZ_NAME[n] : HZ_NAME[n] + ' · ' + n + (tf() === 'W' ? ' 周' : ' 日');
  const modelName = k => { const m = (Q.data && Q.data.models || []).find(x => x.key === k) || (Q.lib && Q.lib.models.find(x => x.key === k)); return m ? m.name : (MODELS.find(x => x[0] === k) || ['', k])[1]; };

  function init(ctx) {
    c = ctx;
    const g = (k, d) => c.store.get(k, d), q = new URLSearchParams(location.search);
    Q.model = typeof g('qmodel', 'four') === 'string' ? g('qmodel', 'four') : 'four';        // 认不认识这个模型，等模型库到了再核对（syncModels）
    Q.side = g('qside', 'long') === 'short' ? 'short' : 'long';
    Q.hz = HZ.indexOf(g('qhz', 20)) >= 0 ? g('qhz', 20) : 20;
    Q.pos = POS.indexOf(g('qpos', 'auto')) >= 0 ? g('qpos', 'auto') : 'auto';
    Q.tab = TABS.indexOf(g('qtab', 'analyze')) >= 0 && g('qtab', 'analyze') !== 'chat' ? g('qtab', 'analyze') : 'analyze';
    Q.wide = !!g('qwide', false); Q.linesOn = !!g('qlines', false); Q.off = g('qoff', {}) || {};
    Q.auto = g('qauto', false) === true;
    if (q.get('qauto') === '1') Q.auto = true;
    Q.speed = SPEED[g('qspeed', 'normal')] ? g('qspeed', 'normal') : 'normal'; Q.autoScroll = g('qscroll', true) !== false; Q.legendOn = g('qlegendOn', true) !== false;
    if (q.get('model') && /^[a-z0-9_]{2,24}$/.test(q.get('model'))) Q.model = q.get('model');      // 网址参数：截图和自检用
    if (q.get('dir') === 'short' || q.get('dir') === 'long') Q.side = q.get('dir');             // 方向用 dir：side 这个参数名已经被“窗口开没开”占了
    if (HZ.indexOf(Number(q.get('hz'))) >= 0) Q.hz = Number(q.get('hz'));
    if (POS.indexOf(q.get('pos')) >= 0) Q.pos = q.get('pos');
    if (TABS.indexOf(q.get('qtab')) >= 0) Q.tab = q.get('qtab');
    if (q.get('qlines') === '1') Q.linesOn = true;
    if (q.get('qwide') === '1') Q.wide = true;

    const fill = (sel, rows, val) => { sel.textContent = ''; rows.forEach(r => { const o = document.createElement('option'); o.value = r[0]; o.textContent = r[1]; sel.appendChild(o); }); sel.value = val; };
    fill($('#qModel'), MODELS, Q.model); fill($('#qHz'), HZ.map(n => [n, hzLabel(n)]), Q.hz); fill($('#qPos'), POS.map(k => [k, POS_NAME[k]]), Q.pos);
    $('#qModel').onchange = e => {
      const v = e.target.value;           // 先记下选的是哪个：退出自动匹配时 chrome() 会把下拉重设成当前模型
      if (v === AUTO) setAuto(true); else { setAuto(false); setModel(v); }
    };
    $('#qHz').onchange = e => set({ hz: Number(e.target.value) });
    $('#qPos').onchange = e => set({ pos: e.target.value });
    $$('#qDir button').forEach(b => { b.onclick = () => (Q.auto ? autoRun(b.dataset.side) : set({ side: b.dataset.side })); });
    $('#qAuto').addEventListener('click', e => {
      const b = e.target.closest('[data-auto-use]');
      if (b) { use(b.dataset.autoUse, Q.autoRes ? Q.autoRes.side : Q.side, null, true); return; }
      if (e.target.closest('#qAutoAsk')) askCombined();
    });
    $('#qRun').onclick = run;
    $$('#qTabs [data-qtab]').forEach(b => { b.onclick = () => setTab(b.dataset.qtab); });
    menu('#qTfBtn', '#qTfPop'); menu('#qSetBtn', '#qSetPop', settingsPop);
    $$('#qTfPop [data-qtf]').forEach(b => { b.onclick = () => { $('#qTfPop').hidden = true; c.setTf(b.dataset.qtf); }; });
    $('#qTerm').onclick = () => window.open('/terminal?hz=' + Q.hz + '&tf=' + tf(), 'fe-terminal');
    $('#qExpand').onclick = () => { Q.wide = !Q.wide; c.store.set('qwide', Q.wide); chrome(); c.resized(); };
    $('#qSetPop').addEventListener('change', onSetting);
    $('#qSetPop').addEventListener('click', e => { const b = e.target.closest('[data-speed]'); if (b) { Q.speed = b.dataset.speed; c.store.set('qspeed', Q.speed); settingsPop(); } });
    $('#sigCard').addEventListener('click', e => { const b = e.target.closest('[data-use]'); if (b) use(b.dataset.use, b.dataset.side, b.dataset.qtf); });
    $('#qPaneModels').addEventListener('click', e => {
      const b = e.target.closest('[data-use]'); if (b) { use(b.dataset.use, b.dataset.side); setTab('analyze'); return; }
      const r = e.target.closest('[data-replay]'); if (r) { c.replayTo(r.dataset.replay); setTab('analyze'); }
    });
    $('#qPaneTasks').addEventListener('click', onTaskClick);
    $('#chartwrap').addEventListener('contextmenu', onContext);
    document.addEventListener('click', e => { if (!e.target.closest('#qMenu')) $('#qMenu').hidden = true; });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') { $('#qMenu').hidden = true; $('#qTfPop').hidden = true; $('#qSetPop').hidden = true; } });
    chrome(); setTab(Q.tab, true); render();
    loadTasks(true);
  }

  function menu(btn, pop, before) {
    $(btn).onclick = e => { e.stopPropagation(); const p = $(pop), was = p.hidden; $$('#side .pop').forEach(x => { x.hidden = true; }); if (was) { if (before) before(); p.hidden = false; } };
    document.addEventListener('click', e => { if (!e.target.closest(pop) && !e.target.closest(btn)) $(pop).hidden = true; });
  }

  /* 模型下拉的内容以后端的模型库为准（按类别分组）；存着的模型后端不认识了，就回到四证 */
  let modelSig = '';
  function syncModels() {
    const list = c.S.meta && c.S.meta.quant_models;
    if (!list || !list.length) return;
    const sig = list.map(m => m.key + m.name + (m.group || '')).join('|');
    if (sig !== modelSig) {
      modelSig = sig;
      MODELS.length = 0; list.forEach(m => MODELS.push([m.key, m.name, m.group || '', m.kind || 'trade', m.default_side || 'long', m.default_hz || 20, m.sides || ['long']]));
      const sel = $('#qModel'); sel.textContent = '';
      const ao = document.createElement('option'); ao.value = AUTO; ao.textContent = '自动匹配（按走势选模型）'; sel.appendChild(ao);
      const groups = [];
      list.forEach(m => { if (groups.indexOf(m.group || '') < 0) groups.push(m.group || ''); });
      groups.forEach(gname => {
        const box = gname ? document.createElement('optgroup') : sel;
        if (gname) { box.label = gname; sel.appendChild(box); }
        list.filter(m => (m.group || '') === gname).forEach(m => { const o = document.createElement('option'); o.value = m.key; o.textContent = m.name; box.appendChild(o); });
      });
    }
    if (!MODELS.some(m => m[0] === Q.model)) { Q.model = 'four'; c.store.set('qmodel', Q.model); }
    $('#qModel').value = Q.auto ? AUTO : Q.model;
  }

  /* 窗口头部和分析卡上那些跟着输入变的文字 */
  function chrome() {
    syncModels();
    $('#side').classList.toggle('wide', Q.wide);
    $('#qExpand').classList.toggle('on', Q.wide); $('#qExpand').title = Q.wide ? '恢复窗口宽度' : '放宽窗口';
    const W = tf() === 'W', adj = (Q.data && Q.data.adjust) || '拆股已调整';
    $('#qTfText').textContent = ((Q.data && Q.data.adjust_short) || '拆股复权') + ' · ' + (W ? '周K' : '日K');
    $$('#qTfPop [data-qtf]').forEach(b => b.classList.toggle('on', b.dataset.qtf === tf()));
    $('#qChartSub').textContent = (W ? '周线' : '日线') + ' · ' + adj + ' · 历史数据重放';
    $('#qModel').value = Q.auto ? AUTO : Q.model; $('#qPos').value = Q.pos;
    const hz = $('#qHz'); [...hz.options].forEach(o => { o.textContent = hzLabel(Number(o.value)); }); hz.value = String(Q.hz);
    $$('#qDir button').forEach(b => {
      b.classList.toggle('on', b.dataset.side === Q.side); b.setAttribute('aria-pressed', b.dataset.side === Q.side ? 'true' : 'false');
      const lab = watch() ? (b.dataset.side === 'long' ? '上行' : '下行') : (b.dataset.side === 'long' ? '做多' : '做空');
      if (b.lastChild && b.lastChild.nodeType === 3) b.lastChild.textContent = lab; else b.appendChild(document.createTextNode(lab));
      b.title = Q.auto ? (b.dataset.side === 'long' ? '做多：按现在的走势，挑做多一侧认得出这段走势的模型来看' : '做空：按现在的走势，挑做空一侧认得出这段走势的模型来看。只是换一个方向分析，不会替你交易')
        : watch() ? (b.dataset.side === 'long' ? '上行：看往上那一侧的情形（观察用，不给价位）' : '下行：看往下那一侧的情形（观察用，不给价位）')
        : (b.dataset.side === 'long' ? '做多：用这个模型做多一侧的规则来看' : '做空：用这个模型做空一侧的规则来看。只是换一个方向分析，不会替你交易');
    });
    $('#side').classList.toggle('q-watch', watch());
    const acct = Q.data && Q.data.position ? Q.data.position.account : '';
    const o0 = $('#qPos').options[0]; if (o0) o0.textContent = acct ? acct + '（账户）' : POS_NAME.auto;
    document.body.classList.toggle('q-short', Q.side === 'short');
  }

  /* 改任何一个输入：存下来、清掉旧结果、按新的输入重取。AI 解读那一栏跟着换成这个组合保存过的那一份 */
  function set(o) {
    if (o.model && o.model !== Q.model) {          // 换模型：方向和周期跟着换成录屏里这个模型用的那一套（可以再改）
      const M = MODELS.find(x => x[0] === o.model) || [];
      o = Object.assign({}, o, !o.side && M[4] ? { side: M[4] } : {}, !o.hz && M[5] ? { hz: M[5] } : {});
    }
    let changed = false;
    ['model', 'side', 'hz', 'pos'].forEach(k => { if (o[k] != null && o[k] !== Q[k]) { Q[k] = o[k]; c.store.set('q' + k, Q[k]); changed = true; } });
    if (!changed) return;
    Q.data = null; Q.steps = null; Q.total = null;
    c.narr.reset(); chrome(); c.modelChanged(); render(); fetch();
    if (Q.tab === 'models') loadScan(); if (Q.tab === 'tasks') renderTasks();
  }
  function setModel(m) { set({ model: MODELS.some(x => x[0] === m) ? m : 'four' }); }
  const modelGroup = k => (MODELS.find(x => x[0] === k) || [])[2] || '';
  /* 换成另一个模型（可以顺带指定方向、K 线级别）：信号卡上“换用”按钮和模型页都走这里 */
  function use(model, side, qtf, keepAuto) {
    if (!keepAuto && Q.auto) setAuto(false);          // 自己点了某个模型：退出自动匹配
    if (qtf && qtf !== tf()) c.setTf(qtf);
    set({ model: model || Q.model, side: side || Q.side, hz: keepAuto ? Q.hz : undefined });
    if (keepAuto) renderAuto();
  }

  // ---------- 自动匹配 ----------
  const sideOk = (k, s) => ((MODELS.find(x => x[0] === k) || [])[6] || []).indexOf(s) >= 0;
  const autoKey = side => c.S.ticker + '|' + c.asofDate() + '|' + tf() + '|' + side;
  const autoFresh = () => !!(Q.autoRes && Q.autoRes._key === autoKey(Q.side));
  function setAuto(on) {
    on = !!on;
    if (on === Q.auto) { if (on) autoRun(Q.side); return; }
    Q.auto = on; c.store.set('qauto', on);
    if (!on) { Q.autoSeq++; Q.autoRes = null; }
    chrome(); renderAuto();
    if (on) autoRun(Q.side);
  }
  /* 点做多 / 做空：后端把这一侧每个模型在这一根上算一遍、排好序；图上换成排第一的。一个都认不出来，就留在原来的模型（它没有这一侧就换一个有的） */
  async function autoRun(side) {
    side = side === 'short' ? 'short' : 'long';
    if (!c.stateFresh()) { if (side !== Q.side) set({ side }); return; }          // 图表还没到：先记下方向，到了再挑（onState）
    const my = ++Q.autoSeq, key = autoKey(side);
    if (!Q.autoRes || Q.autoRes._key !== key) { $('#qAuto').hidden = false; $('#qAuto').innerHTML = '<div class="muted small">正在按走势挑' + (side === 'long' ? '做多' : '做空') + '一侧的模型…</div>'; }
    try {
      const r = await c.api('/api/quant/auto?ticker=' + c.S.ticker + '&side=' + side + '&hz=' + Q.hz + '&tf=' + tf() + '&pos=' + Q.pos + '&asof=' + c.asofDate());
      if (my !== Q.autoSeq || !Q.auto) return;
      if (r.ok === false) throw new Error(r.error);
      r._key = key; Q.autoRes = r;
      const model = r.pick || (sideOk(Q.model, side) ? Q.model : (MODELS.find(x => (x[6] || []).indexOf(side) >= 0 && x[3] !== 'watch') || [Q.model])[0]);
      const before = Q.model + '|' + Q.side;
      set({ model, side, hz: Q.hz });
      if (Q.model + '|' + Q.side === before && !fresh()) fetch();
      renderAuto();
    } catch (e) { if (my === Q.autoSeq) { c.toast('自动匹配没取到：' + e.message, true); Q.autoRes = null; renderAuto(); } }
  }
  function renderAuto() {
    const el = $('#qAuto'), r = Q.autoRes;
    if (!Q.auto) { el.hidden = true; el.innerHTML = ''; return; }
    el.hidden = false;
    if (!r) { if (!el.innerHTML) el.innerHTML = '<div class="muted small">自动匹配：点「做多」或「做空」，按现在的走势挑这一侧的模型。</div>'; return; }
    const P = x => (x == null ? '—' : c.fmtP(x));
    const px = x => {
      const p = x.plan || x.preplan;
      return p ? '<small class="q-auto-px">' + (x.plan ? '计划' : '预案（条件齐了才算数）') + '：入场 ' + P(p.zone[0]) + '–' + P(p.zone[1]) + (p.stop != null ? ' · 止损 ' + P(p.stop) : '') +
        (p.t1 != null ? ' · 第一目标 ' + P(p.t1) : '') + '</small>' : '';
    };
    let h = '<div class="w-title">自动匹配 · ' + esc(r.side_name) + ' · ' + esc(r.ticker) + ' ' + esc(r.asof) + '</div>' +
      '<p class="q-auto-trend">走势：<b>' + esc(r.trend.label) + '</b>（' + (r.trend.total > 0 ? '+' : '') + r.trend.total + '）' + (r.trend.why ? '，' + esc(r.trend.why) : '') + '</p>';
    if (r.matched.length) {
      h += '<div class="q-auto-sub">认得出这段走势的模型（' + r.matched.length + ' 个），排在前面的离条件齐更近。图上画的是 <b>' + esc(modelName(Q.model)) + '</b>，点别的一行换着看。</div><div class="q-auto-list">' +
        r.matched.map((x, i) => '<button class="q-auto-row ' + (STATE_CLS[x.state] || 'na') + (x.key === Q.model ? ' cur' : '') + '" data-auto-use="' + esc(x.key) + '" title="图上换成这个模型">' +
          '<i>' + num(i + 1) + '</i><span class="q-auto-name">' + esc(x.name) + '</span><em>' + esc(x.state_text) + (x.of ? ' · 清单 ' + x.ok + '/' + x.of : '') + '</em>' + px(x) + '</button>').join('') + '</div>';
    } else {
      h += '<p class="muted small">这一侧没有模型认得出现在的走势，每个模型都说“用不上”。图上留着原来的模型。</p>';
    }
    if (r.watch.length) h += '<p class="q-auto-watch">观察提示：' + r.watch.map(x => esc(x.name) + ' ' + esc(x.state_text) + (x.of ? '（' + x.ok + '/' + x.of + '）' : '')).join('；') + '</p>';
    if (r.unused.length) h += '<details class="q-auto-unused"><summary>用不上（' + r.unused.length + ' 个）</summary>' + r.unused.map(x => esc(x.name) + '：' + esc(x.verdict)).join('<br>') + '</details>';
    if (r.matched.length) h += '<div class="q-auto-actions"><button id="qAutoAsk" title="把这几个模型现在的结果交给 AI 对话，综合起来看。会调用 Claude，按用量计费">✦ 让 AI 综合看这几个模型</button><small>会调用 Claude，按用量计费</small></div>';
    el.innerHTML = h + '<p class="fine">' + esc(r.note) + '</p>';
  }
  function askCombined() {
    const r = Q.autoRes;
    if (!r || !r.matched.length || !window.FEChat) return;
    const list = r.matched.map(x => x.name + '（' + x.state_text + (x.of ? ' ' + x.ok + '/' + x.of : '') + '）').join('、');
    setTab('chat');
    window.FEChat.send(r.side_name + '一侧，按走势匹配到这几个模型：' + list + '。把它们综合起来看，现在怎么样？');
  }

  function reset() { Q.seq++; Q.data = null; Q.steps = null; Q.total = null; Q.running = false; Q.shown = 1e9; $('#qMenu').hidden = true; chrome(); render(); loadTasks(); }

  async function fetch() {
    if (!c.stateFresh()) return;
    const my = ++Q.seq;
    try {
      const r = await c.api('/api/quant?ticker=' + c.S.ticker + query() + '&asof=' + c.asofDate());
      if (my !== Q.seq) return;
      if (r.ok === false) throw new Error(r.error);
      Q.data = r; chrome(); render(); c.redraw(); c.narr.restore();
      if (window.FEChat) window.FEChat.onState();         // 对话页顶上那一行（它在看哪张图）和开场问题跟着这一份结果变
    } catch (e) { if (my === Q.seq) c.toast('量化面板没取到：' + e.message, true); }
  }
  const onState = () => {
    if (Q.auto && c.stateFresh() && !autoFresh()) autoRun(Q.side);        // 自动匹配：换了标的、日期或 K 线级别，就按新的走势再挑一次
    else if (!fresh()) fetch(); else render();
    if (Q.tab === 'models') loadScan();
  };

  // ---------- 页签 ----------
  function setTab(name, quiet) {
    Q.tab = TABS.indexOf(name) >= 0 ? name : 'analyze';
    if (!quiet) c.store.set('qtab', Q.tab);
    $$('#qTabs [data-qtab]').forEach(b => { b.classList.toggle('on', b.dataset.qtab === Q.tab); b.setAttribute('aria-selected', b.dataset.qtab === Q.tab ? 'true' : 'false'); });
    $$('#side [data-pane]').forEach(p => { p.hidden = p.dataset.pane !== Q.tab; });
    if (window.FEChat && window.FEChat.shown) window.FEChat.shown(Q.tab === 'chat');
    if (Q.tab === 'models') { loadLib(); loadScan(); renderModels(); }
    if (Q.tab === 'tasks') { loadTasks(true); loadRuns(); }
  }

  // ---------- 分析页 ----------
  function gauge(sc) {
    const th = Math.PI * (1 - (sc.total + 100) / 200), x = 100 + 62 * Math.cos(th), y = 104 - 62 * Math.sin(th);
    const cls = sc.total > 20 ? 'pos' : sc.total < -20 ? 'neg' : 'mid';
    let h = '<div class="q-gauge"><svg viewBox="0 0 200 118" aria-label="综合评分 ' + sc.total + '"><defs><linearGradient id="qg" x1="0" x2="1"><stop offset="0" stop-color="#ef4444"/><stop offset=".5" stop-color="#f5c542"/><stop offset="1" stop-color="#22c55e"/></linearGradient></defs>' +
      '<path d="M 20 104 A 80 80 0 0 1 180 104" fill="none" stroke="url(#qg)" stroke-width="9" stroke-linecap="round"/>' +
      '<line x1="100" y1="104" x2="' + x.toFixed(1) + '" y2="' + y.toFixed(1) + '" stroke="#e6e8ee" stroke-width="3" stroke-linecap="round"/><circle cx="100" cy="104" r="5" fill="#e6e8ee"/></svg>' +
      '<b class="q-total ' + cls + '" id="qTotal">' + (sc.total > 0 ? '+' : '') + sc.total + '</b><span class="q-lab">' + esc(sc.label) + '</span><small class="q-range">综合评分 · −100 到 +100</small></div><div class="q-parts">';
    sc.parts.forEach(p => {
      const w = Math.min(50, Math.abs(p.v) / 2);
      h += '<div class="q-part"><label>' + esc(p.name) + '</label><div class="q-track"><i class="' + (p.v < 0 ? 'neg' : 'pos') + '" style="width:' + w + '%;' + (p.v < 0 ? 'right:50%' : 'left:50%') + '"></i></div><em class="' + (p.v < 0 ? 'neg' : p.v > 0 ? 'pos' : '') + '">' +
        (p.v > 0 ? '+' : '') + p.v + '</em><small>' + esc(p.why) + '</small></div>';
    });
    return h + '</div><p class="fine q-note">' + esc(sc.note) + '</p>';
  }

  const chips = d => '<span class="chip-dir ' + d.side + '">' + ARROW[d.side] + esc(d.side_name) + '</span><span class="chip-hz">' + CLOCK + esc(d.horizon.label) + '</span>';

  function signalCard(d) {
    const cd = d.card, s = d.signal;
    let h = '<div class="eng">◎ ' + esc(cd.model) + ' · ' + esc(d.ticker) + ' ' + d.asof + '</div>' +
      '<h3 class="' + (STATE_CLS[s.state] || 'na') + '" id="sigVerdict">' + esc(cd.verdict) + '</h3>' +
      '<div class="tags">' + chips(d) + cd.tags.slice(2).map(t => '<span' + (t === '引擎结果' ? ' class="eng-tag"' : '') + '>' + esc(t) + '</span>').join('') +
      (s.checks.length ? '<span>清单 ' + s.checks.filter(x => x.ok).length + '/' + s.checks.length + '</span>' : '') + '</div>' +
      '<p>' + esc(cd.text) + '</p>';
    if (s.unsupported && s.suggest && s.suggest.length) {
      h += '<div class="sig-use">' + s.suggest.map(k => '<button data-use="' + esc(k) + '">换用「' + esc(modelName(k)) + '」</button>').join('') +
        (s.unsupported === 'side' ? '<button data-use="' + esc(d.model_key) + '" data-side="long">回到做多</button>' : '<button data-use="' + esc(d.model_key) + '" data-qtf="D">回到日K</button>') + '</div>';
    }
    if (s.checks.length) h += '<div class="q-checks">' + s.checks.map(x => '<div class="' + (x.ok ? 'on' : '') + '"><i>' + (x.ok ? '✓' : '·') + '</i><div><b>' + esc(x.name) + '</b><span>' + esc(x.why) + '</span></div></div>').join('') + '</div>';
    $('#sigCard').innerHTML = h + '<p class="fine" id="sigFoot">' + esc(cd.footer) + '</p>';
    $('#tiles').innerHTML = cd.cells.map(x => '<div class="tile ' + (x.tone || '') + (x.v === '—' ? ' off' : '') + (String(x.v).length > 9 && x.k !== 'zone' ? ' sm' : '') + '" data-k="' + x.k + '"><label>' + esc(x.name) + '</label><b>' + esc(x.v) + '</b><small>' + esc(x.sub || '') + '</small></div>').join('');
  }

  /* 四证的信号卡由 app.js 按引擎输出画；这里只把标签换成录屏的样式（方向、周期），再补上第六格“第二目标” */
  function fourExtras(d) {
    const tg = $('#sigCard .tags'), s = d.signal;
    if (tg && !tg.dataset.q) { tg.dataset.q = '1'; tg.innerHTML = chips(d) + '<span>证据 ' + s.checks.filter(x => x.ok).length + '/4</span><span class="eng-tag">引擎结果</span>'; }
    const t2 = d.card.cells.find(x => x.k === 't2'), box = $('#tiles');
    if (t2 && box && !box.querySelector('[data-k=t2]')) {
      box.insertAdjacentHTML('beforeend', '<div class="tile target' + (t2.v === '—' ? ' off' : '') + '" data-k="t2"><label>第二目标</label><b>' + esc(t2.v) + '</b><small>' + esc(t2.sub || '') + '</small></div>');
    }
  }

  function bar(d) {
    const el = $('#qBar'), s = d.signal;
    if (d.model_key === 'four' || s.unsupported) { el.hidden = true; return; }
    const title = d.model_key === 'houshou' ? (d.side === 'long' ? '后手战法' : '后手战法 · 做空') : d.model_key === 'breakout' ? (d.side === 'short' ? '破位反抽' : '突破回踩')
      : d.model_name.replace(/\s*v[\d.]+$/, '') + (d.side === 'short' ? ' · 做空' : '');
    let h = '<b>' + title + '</b><i class="sep"></i>';
    if (s.checks.length) {
      h += s.checks.map(x => '<span class="ck' + (x.ok ? ' on' : '') + '" title="' + esc(x.why) + '">' + esc(x.name) + '<u>' + (x.ok ? '✓' : '') + '</u></span>').join('<i class="plus">+</i>');
      h += '<i class="sep"></i><em class="' + (s.state === 'ready' ? 'go' : s.state === 'avoid' || s.state === 'dead' ? 'no' : '') + '">' + esc(s.verdict === '下后手' ? (d.side === 'long' ? '下后手（未回测）' : '下后手做空（未回测）') : s.verdict_text) + '</em>';
    } else {
      h += '<span class="ck">' + esc(s.state === 'dead' ? '结构已失效' : d.model_key === 'houshou' ? (d.side === 'long' ? '没有三冲结构' : '没有三探结构') : '没有这种结构') + '</span><i class="sep"></i><em>清单用不上</em>';
    }
    el.innerHTML = h; el.hidden = false; el.dataset.phase = s.phase;
  }

  function extra(d) {
    const s = d.signal;
    let h = '';
    if (s.next_needs && s.next_needs.length) h += '<div class="card thin"><div class="w-title">下一根 K 线要看什么（清单的门槛）</div><ul class="q-needs">' + s.next_needs.map(x => '<li>' + esc(x) + '</li>').join('') + '</ul></div>';
    h += '<div class="q-explain">' + d.explain.map(x => '<p>' + esc(x) + '</p>').join('') + '</div>';
    if (s.rows && s.rows.rows && s.rows.rows.length) {           // 加仓表（不爆仓 3 号）/ 三份建仓表（三份法）：只是算术，不会替你交易
      h = '<div class="card thin q-rows" id="qRows"><div class="w-title">' + esc(s.rows.title) + '</div><table class="q-tab">' +
        s.rows.rows.map(r => '<tr><th>' + esc(r.k) + '</th><td class="v">' + (r.v == null ? '—' : c.fmtP(r.v)) + '</td><td>' + esc(r.sub || '') + '</td></tr>').join('') + '</table></div>' + h;
    }
    $('#qExtra').innerHTML = h;
    const pn = $('#qPosNote'); pn.hidden = !d.position_note; pn.textContent = d.position_note || '';
    $('#qWeekNote').textContent = d.week ? (d.week.complete ? '周K · 这一周已收完' : '周K · 这一周还没收完，结论是暂时的') : '';
  }

  function legend(d) {
    const el = $('#qLegend');
    if (!d.legend.length || !Q.legendOn) { el.hidden = true; return; }
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
    $('#qRun').innerHTML = Q.running ? '正在分析…<i class="spin"></i>' : '✦ AI 分析当前图表';
    $('#qRun').classList.toggle('busy', Q.running);
    $('#qHint').textContent = Q.running || Q.steps ? '结构 → 规则信号 → 划线 → AI 深度解读，步骤见下方。' : '结构分析与规则信号均基于历史数据重放，仅供研究学习。';
    $('#evidence').hidden = hideFour();
    $('#fourDetail').hidden = Q.model !== 'four';
    stepsCard(); renderAuto();
    if (!ok) {
      $('#qBar').hidden = true; $('#qLegend').hidden = true; $('#qLabel').textContent = '';
      if (hideFour() && c.stateFresh()) { $('#sigCard').innerHTML = '<div class="eng">计算中…</div>'; $('#tiles').innerHTML = ''; }
      if (!c.stateFresh()) { $('#qScore').innerHTML = '<div class="muted small">计算中…</div>'; $('#qExtra').innerHTML = ''; $('#qPosNote').hidden = true; }
      return;
    }
    $('#qLabel').textContent = d.score.label;
    $('#qLabel').className = 'qtag ' + (d.score.total > 20 ? 'pos' : d.score.total < -20 ? 'neg' : '');
    $('#qScore').innerHTML = gauge(d.score);
    if (fourOwn()) fourExtras(d); else signalCard(d);
    bar(d); extra(d); legend(d);
    if (Q.tab === 'models') renderModels();
    if (Q.tab === 'tasks') renderTasks();
    if (!$('#qSetPop').hidden) settingsPop();
  }

  // ---------- 显示设置 ----------
  function settingsPop() {
    const d = fresh() ? Q.data : null;
    let h = '<div class="pop-title">图上划线</div><label><input type="checkbox" data-set="lines"' + (Q.linesOn ? ' checked' : '') + '> 显示结构线（支撑、压力、趋势线、回撤刻度）</label>';
    h += '<div id="qLines"><div class="q-lines">' + (d ? d.lines.map(x => '<label><input type="checkbox" data-line="' + esc(x.id) + '"' + (Q.off[x.id] ? '' : ' checked') + '><span class="sw" style="background:' + (COL[x.style] || c.C[x.style] || '#8b93a5') + '"></span>' +
      esc(num(x.n) + ' ' + x.label) + (x.price != null ? ' · ' + c.fmtP(x.price) : '') + (x.kind === 'auto' ? '（自动画）' : '') + '</label>').join('') : '<span class="muted small">还没有结果</span>') + '</div></div>';
    h += '<div class="pop-title">划线动画</div><div class="seg mini">' + [['fast', '快'], ['normal', '正常'], ['slow', '慢']].map(x => '<button data-speed="' + x[0] + '"' + (Q.speed === x[0] ? ' class="on"' : '') + '>' + x[1] + '</button>').join('') + '</div>';
    h += '<div class="pop-title">其他</div><label><input type="checkbox" data-set="scroll"' + (Q.autoScroll ? ' checked' : '') + '> 分析完自动滚到信号卡</label>' +
      '<label><input type="checkbox" data-set="legend"' + (Q.legendOn ? ' checked' : '') + '> 图下面的编号图例</label>';
    $('#qSetPop').innerHTML = h;
  }
  function onSetting(e) {
    const t = e.target, k = t.dataset && t.dataset.set, id = t.dataset && t.dataset.line;
    if (k === 'lines') { Q.linesOn = t.checked; c.store.set('qlines', Q.linesOn); Q.shown = 1e9; }
    else if (k === 'scroll') { Q.autoScroll = t.checked; c.store.set('qscroll', Q.autoScroll); }
    else if (k === 'legend') { Q.legendOn = t.checked; c.store.set('qlegendOn', Q.legendOn); if (fresh()) legend(Q.data); else $('#qLegend').hidden = true; c.resized(); }
    else if (id != null) { Q.off[id] = !t.checked; c.store.set('qoff', Q.off); }
    c.redraw();
  }

  // ---------- 「AI 分析当前图表」：四步 ----------
  async function run() {
    if (Q.running || !c.stateFresh()) return;
    if (Q.tab !== 'analyze') setTab('analyze');
    Q.running = true; Q.total = null;
    const tAll = performance.now(), names = ['识别图表结构', '计算规则信号', '在图上划线', 'AI 深度解读'], gap = SPEED[Q.speed];
    Q.steps = names.map((n, k) => ({ name: n, state: k === 0 ? 'run' : 'wait', note: '', ms: null }));
    const tick = setInterval(() => { Q.total = performance.now() - tAll; stepsCard(); }, 200);
    const step = (k, o) => { Object.assign(Q.steps[k], o); if (Q.steps[k + 1] && o.state === 'done') Q.steps[k + 1].state = 'run'; Q.total = performance.now() - tAll; stepsCard(); };
    Q.linesOn = true; c.store.set('qlines', true); Q.shown = 0; c.redraw();
    render();
    let aiSrc = null;
    try {
      await fetch();
      if (!fresh()) throw new Error('这一天的结果没取到');
      const d = Q.data, my = Q.seq;
      await sleep(260); step(0, { state: 'done', note: d.steps[0].note, ms: d.steps[0].ms });
      await sleep(260); step(1, { state: 'done', note: d.steps[1].note, ms: d.steps[1].ms });
      const t3 = performance.now(), ls = d.lines.filter(x => !Q.off[x.id]);
      Q.steps[2].note = d.steps[2].note; stepsCard();
      for (let k = 1; k <= ls.length && my === Q.seq; k++) {
        Q.shown = k; Q.animUntil = performance.now() + gap;
        if (ls[k - 1].kind === 'auto') c.setAuto(true);      // 四证的扇线、成本线、止损线就是“自动画”那一层
        c.redraw(); await sleep(gap);
      }
      Q.shown = 1e9;
      step(2, { state: 'done', ms: performance.now() - t3 });
      if (Q.autoScroll) $('#narrCard').scrollIntoView({ block: 'start', behavior: 'smooth' });     // 第四步的解说动画要看得见
      const t4 = performance.now();
      Q.steps[3].note = '模板或保存过的解读，不计费'; stepsCard();
      await c.narr.run();
      const cur = c.narr.current();
      aiSrc = cur ? (cur.source === 'claude' ? 'saved' : 'template') : null;
      step(3, { state: 'done', ms: performance.now() - t4, note: cur ? (cur.source === 'claude' ? 'Claude · 保存过的那一版，不再计费' : '模板版 · 要 Claude 解读点下面的按钮') : '没取到' });
      Q.ranOnce = true;
      c.api('/api/quant/run', Object.assign({ ticker: c.S.ticker, asof: c.asofDate(), ai: aiSrc }, profile())).then(() => { Q.runs = null; if (Q.tab === 'tasks') loadRuns(); }).catch(() => {});      // 记一笔分析记录；记不上不影响分析
    } catch (e) { c.toast('分析没跑完：' + e.message, true); }
    clearInterval(tick);
    Q.running = false; Q.shown = 1e9; Q.total = performance.now() - tAll;
    render(); c.redraw();
  }

  // ---------- 模型页 ----------
  async function loadLib() {
    if (Q.lib) return;
    try { const r = await c.api('/api/quant/models'); if (r.ok === false) throw new Error(r.error); Q.lib = r; renderModels(); } catch (e) { c.toast('模型库没取到：' + e.message, true); }
  }
  async function loadScan() {
    if (!c.S.bars) return;
    const key = [c.S.ticker, Q.hz, tf(), c.S.bars.d[c.S.bars.d.length - 1]].join('|');
    if (Q.scanKey === key) return;
    Q.scanKey = key; Q.scan = null; renderModels();
    try {
      const r = await c.api('/api/quant/scan?ticker=' + c.S.ticker + '&hz=' + Q.hz + '&tf=' + tf());
      if (r.ok === false) throw new Error(r.error);
      if (Q.scanKey === key) { Q.scan = r.cells; renderModels(); }
    } catch (e) { if (Q.scanKey === key) Q.scanKey = ''; }
  }
  function renderModels() {
    if (!c || Q.tab !== 'models') return;
    const L = Q.lib, box = $('#qModelCards');
    $('#qModelName').textContent = modelName(Q.model) + ' · ' + (Q.side === 'short' ? '做空' : '做多');
    if (!L) { box.innerHTML = '<div class="muted small">加载中…</div>'; return; }
    const cell = (k, s) => (Q.scan || []).find(x => x.model === k && x.side === s);
    const openSet = new Set($$('#qModelCards details[open]').map(x => x.dataset.k));
    box.innerHTML = L.models.map(m => {
      const on = m.key === Q.model;
      const sides = ['long', 'short'].map(s => {
        const has = m.sides.indexOf(s) >= 0, x = cell(m.key, s), tfok = m.tfs.indexOf(tf()) >= 0;
        if (!has) return '<span class="m-side off">' + ARROW[s] + (s === 'long' ? '做多' : '做空') + ' · 没有这一侧的规则</span>';
        if (!tfok) return '<span class="m-side off">' + ARROW[s] + (s === 'long' ? '做多' : '做空') + ' · 不看周 K</span>';
        return '<button class="m-side ' + (x ? x.state : '') + (on && s === Q.side ? ' cur' : '') + '" data-use="' + m.key + '" data-side="' + s + '" title="用这个模型的这一侧去分析">' + ARROW[s] + (s === 'long' ? '做多' : '做空') +
          ' · ' + esc(x ? x.verdict + (x.of ? '（' + x.ok + '/' + x.of + '）' : '') : '计算中…') + '</button>';
      }).join('');
      const params = m.params.map(p => '<tr><td>' + esc(p.name) + '</td><td>' + esc(String(p.v)) + '</td><td><i class="src ' + p.src + '">' + (p.src === 'video' ? '录屏' : p.src === 'source' ? '原版' : '估算') + '</i></td></tr>').join('');
      return '<div class="card mcard' + (on ? ' on' : '') + '" data-model="' + m.key + '"><div class="m-head"><b>' + esc(m.name) + '</b><span class="m-badge">' + esc(m.tested) + '</span><span class="spacer"></span>' +
        (on ? '<span class="m-cur">正在用</span>' : '<button data-use="' + m.key + '" data-side="' + (m.sides.indexOf(Q.side) >= 0 ? Q.side : m.sides[0]) + '">用这个模型</button>') + '</div>' +
        '<p class="m-what">' + esc(m.what) + '</p><div class="m-sides">' + sides + '</div>' +
        '<details data-k="' + m.key + '"' + (openSet.has(m.key) ? ' open' : '') + '><summary>来历、清单和参数（' + m.params.length + ' 个，' + m.params.filter(p => p.src === 'est').length + ' 个是估算）</summary>' +
        '<p class="fine">来历：' + esc(m.origin) + '</p><div class="m-checks">' + m.checks.map((x, k) => '<span>' + (k + 1) + ' ' + esc(x) + '</span>').join('') + '</div>' +
        '<table class="q-tab m-params">' + params + '</table>' + m.notes.map(n => '<p class="fine">· ' + esc(n) + '</p>').join('') +
        (m.refs.length ? '<p class="fine">参考过的开源实现：' + m.refs.map(esc).join('；') + '。都只是别人的写法，不是验证。</p>' : '') + '</details></div>';
    }).join('');
    detail();
  }
  /* 现在选的模型：历史触发和这一次用到的参数。四证的依据、历史信号、回测在 #fourDetail（app.js 画的） */
  function detail() {
    const box = $('#qModelDetail'), d = fresh() ? Q.data : null;
    if (!d || d.model_key === 'four') { box.innerHTML = d && d.signal.unsupported ? '<div class="card thin fine">' + esc(d.signal.note) + '</div>' : ''; return; }
    if (d.signal.unsupported) { box.innerHTML = '<div class="card thin fine">' + esc(d.signal.note) + '</div>'; return; }
    const hi = d.history, st = hi.stats || {}, OUT = { target: '先到目标', stop: '先破止损', none: '都没到', open: '未了结' };
    const stat = d.model_key === 'houshou'
      ? '回落阶段共 ' + (st.fall || 0) + ' 根 K 线（全部 ' + (st.bars || 0) + ' 根）：回到成本线 ' + (st.B1 || 0) + ' 根，AB=CD ' + (st.B2 || 0) + ' 根，缩量刺破收回 ' + (st.B3 || 0) + ' 根，至少两项同时成立 ' + (st.two_of_three || 0) + ' 根。能看出清单卡在哪一项。'
      : '破位（或突破）之后被跟踪的 K 线共 ' + (st.after_break || 0) + ' 根（全部 ' + (st.bars || 0) + ' 根）：其中反抽到位 ' + (st.K2 || 0) + ' 根，三项齐 ' + (st.K3 || 0) + ' 次。';
    let h = '<details class="card thin" id="qHist" open><summary>历史触发 · ' + esc(hi.note) + '</summary>' +
      (hi.rows.length ? '<table class="q-tab"><tr><th>日期</th><th>入场中值</th><th>止损</th><th>目标</th><th>盈亏比</th><th>之后 ' + hi.hold + ' 根</th></tr>' +
        hi.rows.slice().reverse().slice(0, 60).map(r => '<tr><td><button data-replay="' + r.date + '">' + r.date + '</button></td><td>' + c.fmtP(r.mid) + '</td><td>' + c.fmtP(r.stop) + '</td><td>' + c.fmtP(r.t1) + '</td><td>' + (r.rr != null ? r.rr.toFixed(2) : '—') + '</td><td class="' + r.outcome + '">' + OUT[r.outcome] + (r.bars ? ' · ' + r.bars + ' 根' : '') + '</td></tr>').join('') + '</table>' +
        (hi.rows.length > 60 ? '<p class="fine">只列最近 60 次，一共 ' + hi.rows.length + ' 次。</p>' : '')
        : hi.never   // 看最新一根时：说的是全部历史；回放到过去时只说到那一天为止（不提之后的事）
          ? '<p class="fine q-never"><b>全部样本上一次都没触发过。</b>这只标的全部 ' + (st.bars || 0) + ' 根' + (d.tf === 'W' ? '周' : '日') + ' K（' + esc((c.S.bars && c.S.bars.d[0]) || '') + ' 至 ' + d.asof +
            '）里，这个方向上清单从没有同时成立过。这和信号卡上的「' + esc(d.signal.verdict_text) + '」不是一回事：信号卡只说今天，这一句说的是全部历史。</p>'
          : '<p class="fine">到这一天为止，这只标的在这个方向上，清单从没有同时成立过。</p>') +
      '<p class="fine" id="qStats">' + stat + '</p>' +
      (hi.rr_median != null ? '<p class="fine">这些触发的盈亏比，中间那一个是 ' + hi.rr_median.toFixed(2) + ' : 1。' + (hi.rr_median < 1 ? '目标比止损近，所以“先到目标”的次数多，并不说明能赚：赢一次赚的，不够亏一次赔的。' : '') + '</p>' : '') +
      '<p class="fine">没有扣手续费和滑点，也没有和“随便挑一天”对照过：这不是回测，只是把出现过的次数数一遍。</p></details>';
    const P = d.signal.params, en = d.signal.est_note || {}, vn = d.signal.video_note || {}, sn = d.signal.source_note || {};
    if (P) {
      const nv = P.video ? Object.keys(P.video).length : 0, ns = P.source ? Object.keys(P.source).length : 0;
      const list = (o, notes) => Object.keys(o).map(k => '<span>' + esc(notes[k] || k) + '：' + esc(String(o[k])) + '</span>').join('');
      h += '<details class="card thin" id="qParams"><summary>这一次用到的参数（' + (nv ? '录屏原话 ' + nv + ' 个，' : '') + (ns ? '开源原版 ' + ns + ' 个，' : '') + '其余全部【估算】）</summary><div class="q-params">';
      if (nv && d.model_key === 'houshou') h += '<b>录屏里说了的</b><span>离成本线超过 ' + P.video.far * 100 + '% 不追</span><span>两段幅度相差不到 ' + P.video.abcd_tol * 100 + '%</span><span>量缩到前一段的 ' + P.video.dry * 100 + '% 以下</span><span>止损在 D 点外侧 ' + P.video.stop * 100 + '%</span>';
      else if (nv) h += '<b>录屏里说了的</b>' + list(P.video, vn);
      if (ns) h += '<b>开源原版里的</b>' + list(P.source, sn);
      h += '<b>' + (ns ? '原版没给' : '录屏没给') + '、这里自己定的【估算】</b>' + list(P.est, en) + '</div></details>';
    }
    box.innerHTML = h;
  }

  // ---------- 任务页 ----------
  async function loadTasks(force) {
    if (!force && Date.now() - Q.tasksAt < 60000) return;
    Q.tasksAt = Date.now();
    try { const r = await c.api('/api/quant/tasks'); if (r.ok === false) throw new Error(r.error); Q.tasks = r; dot(); renderTasks(); } catch (e) { /* 下一次再取 */ }
  }
  async function loadRuns() {
    try { const r = await c.api('/api/quant/runs'); if (r.ok === false) throw new Error(r.error); Q.runs = r; renderTasks(); } catch (e) { /* 下一次再取 */ }
  }
  const dot = () => { const n = Q.tasks ? Q.tasks.unseen : 0, el = $('#qTaskDot'); el.hidden = !n; el.textContent = n > 9 ? '9+' : String(n || ''); };
  const label = o => o.ticker + ' · ' + modelName(o.model) + ' · ' + (o.side === 'short' ? '做空' : '做多') + ' · ' + HZ_NAME[o.horizon || o.hz] + ' ' + (o.horizon || o.hz) + (o.tf === 'W' ? ' 周 · 周K' : ' 日');
  function renderTasks() {
    if (!c || Q.tab !== 'tasks') return;
    const cur = Object.assign({ ticker: c.S.ticker, horizon: Q.hz }, profile()), d = fresh() ? Q.data : null;
    const bad = d && (!d.side_ok || !d.tf_ok), have = Q.tasks && Q.tasks.tasks.some(t => t.ticker === cur.ticker && t.model === cur.model && t.side === cur.side && t.horizon === cur.horizon && t.tf === cur.tf);
    $('#qTaskAdd').innerHTML = '<div class="t-cur"><small>现在的组合</small><b>' + esc(label(cur)) + '</b></div>' +
      '<button id="qTaskNew" class="primary"' + (bad || have ? ' disabled' : '') + '>＋ 加入盯盘</button>' +
      '<p class="fine">' + (bad ? '这个模型没有这个方向（或这个级别）的规则，盯不了。' : have ? '这个组合已经在盯了。' : '每次有新的收盘 K 线，程序会把这套清单重看一遍；齐了就在这里记一笔，并在「任务」上亮红点。只是提醒，不会替你交易；打开下面的「提醒」，还会发 Mac 通知或推到手机。') + '</p>';
    const T = Q.tasks, box = $('#qTaskList');
    if (!T) box.innerHTML = '<div class="muted small">加载中…</div>';
    else if (!T.tasks.length) box.innerHTML = '<div class="card thin empty">还没有盯盘任务。先在「分析」页选好模型和方向，再回来点上面的按钮。</div>';
    else {
      box.innerHTML = '<div class="t-bar"><button data-task="check">立即检查</button>' + (T.unseen ? '<button data-task="seen">全部标为已读（' + T.unseen + '）</button>' : '') + '<span class="spacer"></span><span class="muted small">' + T.tasks.length + ' / ' + T.limit + '</span></div>' +
        T.tasks.map(t => {
          const L = t.last || {}, hits = t.hits || [];
          return '<div class="card thin task' + (t.enabled === false ? ' paused' : '') + '" data-id="' + t.id + '"><div class="t-head"><b>' + esc(label(t)) + '</b><span class="spacer"></span>' +
            '<button data-task="' + (t.enabled === false ? 'resume' : 'pause') + '" title="' + (t.enabled === false ? '继续盯' : '先不盯') + '">' + (t.enabled === false ? '继续' : '暂停') + '</button><button data-task="delete" title="删除这个任务">删除</button></div>' +
            '<div class="t-now"><span class="m-side ' + (L.state || '') + '">' + esc(L.verdict || (t.error ? '这次没算出来' : '还没检查')) + (L.of ? '（' + L.ok + '/' + L.of + '）' : '') + '</span>' +
            '<small>' + (t.enabled === false ? '已暂停' : '检查到 ' + esc(t.checked_asof || '—') + ' 收盘') + '</small><button data-task="open">去看</button></div>' +
            (hits.length ? '<div class="t-hits">' + hits.map(h => '<button data-task="hit" data-asof="' + h.asof + '" class="' + (h.seen ? '' : 'new') + '" title="回到这一天看当时的清单和价位">' + h.asof + ' 条件齐</button>').join('') + '</div>' : '') + '</div>';
        }).join('');
    }
    renderNotify();
    const R = Q.runs, rl = $('#qRunList');
    $('#qRunCount').textContent = R ? '共 ' + R.total + ' 次 · 点一行回到那一刻' : '';
    if (!R) rl.innerHTML = '<div class="muted small">加载中…</div>';
    else if (!R.runs.length) rl.innerHTML = '<div class="empty">还没有记录。每点一次「AI 分析当前图表」，这里记一行。</div>';
    else rl.innerHTML = R.runs.map((r, k) => '<button class="run-row" data-run="' + k + '"><span>' + esc(String(r.at).slice(5, 16)) + '</span><b>' + esc(label(r)) + '</b><i class="m-side ' + r.state + '">' + esc(r.verdict) + '</i>' +
      '<small>' + esc(r.asof) + ' 收盘 ' + c.fmtP(r.price) + ' · 表盘 ' + (r.score > 0 ? '+' : '') + r.score + ' ' + esc(r.score_label) + (r.ai ? ' · ' + ({ template: '模板解读', saved: 'Claude 存档', claude: 'Claude' }[r.ai] || '') : '') + '</small></button>').join('') +
      '<button class="run-clear" data-task="clear">清空记录</button>';
  }
  /* 提醒：Mac 通知（只在这台电脑上，可以带价格）和 iMessage（推到手机，只说哪只、什么事，不带持仓数字） */
  async function renderNotify(reload) {
    const box = $('#qNotify');
    if (!box) return;
    if (!Q.notify || reload) { try { Q.notify = await c.api('/api/notify'); } catch (e) { Q.notify = null; } }
    const N = Q.notify;
    if (!N || N.ok === false) { box.innerHTML = '<div class="muted small">提醒的设定没取到。</div>'; return; }
    const s = N.settings;
    box.innerHTML = '<label class="n-row"><input type="checkbox" id="nMac"' + (s.mac ? ' checked' : '') + '> Mac 通知（只在这台电脑上，可以带价格）</label>' +
      '<label class="n-row">推到手机（iMessage）<input id="nIm" placeholder="手机号或 Apple ID" value="' + esc(s.imessage) + '" autocomplete="off"></label>' +
      '<div class="n-row"><button id="nSave" class="primary">保存</button><button id="nTest"' + (s.mac || s.imessage ? '' : ' disabled') + '>发一条测试</button></div>' +
      '<p class="fine">盯盘任务条件齐了、收盘碰到你持仓里的线（成本、行权价、归零线、估值参考）时各提醒一次。发到手机的那条只说哪只、什么事，不带任何持仓数字。' +
      'iMessage 第一次发的时候，Mac 会问能不能让面板控制「信息」，点允许。</p>' +
      '<p class="fine">AI 对话里问“为什么跌”这类问题，会自动联网查：今天用了 ' + N.auto_web_used + ' / ' + N.auto_web_daily + ' 次（按次计费）。</p>';
    $('#nSave').onclick = async () => {
      try { const r = await c.api('/api/notify', { mac: $('#nMac').checked, imessage: $('#nIm').value }); if (r.ok === false) throw new Error(r.error); c.toast('提醒的设定存好了。'); renderNotify(true); }
      catch (e) { c.toast('没存成：' + e.message, true); }
    };
    $('#nTest').onclick = async () => {
      try { const r = await c.api('/api/notify/test', {}); if (r.ok === false) throw new Error(r.error); c.toast(r.sent.length ? '发出去了：' + r.sent.map(x => x === 'mac' ? 'Mac 通知' : 'iMessage').join('、') + '。' : '没发出去：先打开 Mac 通知或填好 iMessage，再保存。', !r.sent.length); }
      catch (e) { c.toast('没发出去：' + e.message, true); }
    };
  }
  async function taskOp(body) {
    try { const r = await c.api('/api/quant/tasks', body); if (r.ok === false) throw new Error(r.error); Q.tasks = r; Q.tasksAt = Date.now(); dot(); renderTasks(); return true; } catch (e) { c.toast('没办成：' + e.message, true); return false; }
  }
  /* 回到某个组合（和某一天）：任务、命中记录、分析记录都走这里 */
  function goTo(o, asof) {
    Q.model = o.model; Q.side = o.side; Q.hz = o.horizon || o.hz || 20; if (o.pos) Q.pos = o.pos;
    ['model', 'side', 'hz', 'pos'].forEach(k => c.store.set('q' + k, Q[k]));
    Q.data = null; Q.steps = null; c.narr.reset(); chrome(); c.modelChanged();
    setTab('analyze'); c.goto(o.ticker, o.tf || 'D', asof || null);
  }
  async function onTaskClick(e) {
    const b = e.target.closest('button'); if (!b) return;
    if (b.id === 'qTaskNew') { if (await taskOp(Object.assign({ op: 'add', ticker: c.S.ticker }, profile()))) c.toast('已加入盯盘。有新 K 线时会自动检查。'); return; }
    if (b.dataset.run != null) { const r = Q.runs.runs[Number(b.dataset.run)]; if (r) goTo(r, r.asof); return; }
    const op = b.dataset.task, card = b.closest('.task'), id = card && card.dataset.id, t = id && Q.tasks.tasks.find(x => x.id === id);
    if (op === 'check') { b.disabled = true; b.textContent = '检查中…'; Q.tasksAt = 0; try { const r = await c.api('/api/quant/tasks?force=1'); Q.tasks = r; dot(); c.toast('检查完了：' + (r.unseen ? '有 ' + r.unseen + ' 条新的“条件齐”。' : '没有新的“条件齐”。')); } catch (err) { c.toast('没检查成：' + err.message, true); } renderTasks(); }
    else if (op === 'seen') taskOp({ op: 'seen' });
    else if (op === 'clear') { try { await c.api('/api/quant/runs/clear', {}); Q.runs = { ok: true, runs: [], total: 0 }; renderTasks(); } catch (err) { c.toast('没清成：' + err.message, true); } }
    else if (t && (op === 'pause' || op === 'resume' || op === 'delete')) taskOp({ op, id });
    else if (t && op === 'open') goTo(t, null);
    else if (t && op === 'hit') { taskOp({ op: 'seen', id }); goTo(t, b.dataset.asof); }
  }

  // ---------- 图上 ----------
  function hline(g, x0, price, color, dash, width) {
    const y = c.Y(price); if (y == null) return null;
    g.beginPath(); g.moveTo(Math.max(0, x0), y); g.lineTo(c.OV().w, y); g.strokeStyle = color; g.lineWidth = width || 1.2; g.setLineDash(dash || []); g.stroke(); g.setLineDash([]);
    return y;
  }
  function badge(g, x, y, text, color, r) {
    r = r || 9;
    g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fillStyle = color; g.fill();
    g.fillStyle = '#0b0e14'; g.font = '700 11px -apple-system,"PingFang SC",sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, x, y + 0.5);
  }
  const I = date => c.S.idx[date];

  /* 条件齐了才有：建仓区的色带，以及右边的盈亏示意框（一块是到目标的空间，一块是到止损的空间）。线和标签由 drawLines 统一画 */
  function planBand(g, o, x0) {
    if (!o.zone) return;
    const W = c.OV().w, y1 = c.Y(o.zone[1]), y0 = c.Y(o.zone[0]), xe = c.X(c.S.asof);
    if (x0 != null && y1 != null && y0 != null) { g.fillStyle = c.rgba(COL.zone, 0.18); g.fillRect(x0, y1, W - x0, Math.max(2, y0 - y1)); }
    const ym = c.Y((o.zone[0] + o.zone[1]) / 2), yt = c.Y(o.target), xb = xe != null ? xe + 14 : null;
    if (xb == null || ym == null) return;
    if (yt != null) { g.fillStyle = c.rgba(c.C.up, 0.13); g.fillRect(xb, Math.min(yt, ym), W - xb, Math.abs(ym - yt)); }
    const ys = o.stop != null ? c.Y(o.stop) : null;
    if (ys != null) { g.fillStyle = c.rgba(c.C.down, 0.13); g.fillRect(xb, Math.min(ys, ym), W - xb, Math.abs(ys - ym)); }
  }

  function drawHoushou(g, o) {
    const S = c.S, a = I(o.anchor.date), H = c.OV().h, v = o.avwap.v, sd = o.avwap.sd, up = o.side !== 'short', k1 = up ? -1 : 1;
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
    // 三冲（做空是三探）：编号气泡，气泡旁写这一冲的成交量相当于第一冲的百分之几。做多画在高点上面，做空画在低点下面
    const ps = o.pushes || [], three = ps.some(p => p.slot), fname = up ? '兵力 ' : '抛压 ';        // 够三冲时只给最后三冲编号 1、2、3，更早的只留一个小点
    let first = true;
    ps.forEach(p => {
      const x = c.X(I(p.date)), y = c.Y(p.price); if (x == null || y == null) return;
      if (three && !p.slot) { g.beginPath(); g.arc(x, y + 8 * k1, 3, 0, Math.PI * 2); g.fillStyle = c.rgba(COL.push, 0.5); g.fill(); return; }
      badge(g, x, y + 16 * k1, String(three ? p.slot : p.n), p.pending ? c.rgba(COL.push, 0.55) : COL.push);
      if (p.force_pct != null) c.label(fname + p.force_pct + '%', x, y + 36 * k1, COL.push, 'center');
      if (first) { first = false; c.label(num(legendN('push')), x - 22, y + 16 * k1, COL.push, 'center'); }
    });
    // A B C D：两段回落（做空是两段反弹）
    const ab = o.abcd;
    if (ab) {
      const P = ['A', 'B', 'C', 'D'].map(k => ab[k] && { k, x: c.X(I(ab[k].date)), y: c.Y(ab[k].price), soft: ab[k].provisional }).filter(p => p && p.x != null && p.y != null);
      const sign = up ? '−' : '+';
      for (let k = 1; k < P.length; k++) {
        const leg = P[k - 1].k + P[k].k, eq = leg === 'AB' || leg === 'CD';
        g.beginPath(); g.moveTo(P[k - 1].x, P[k - 1].y); g.lineTo(P[k].x, P[k].y); g.strokeStyle = COL.abcd; g.lineWidth = eq ? 2 : 1; g.setLineDash(eq ? [6, 4] : []); g.stroke(); g.setLineDash([]);
        const t = leg === 'AB' && ab.ab_pct != null ? sign + ab.ab_pct + '%' : leg === 'CD' && ab.cd_pct != null ? sign + ab.cd_pct + '%（是第一段的 ' + (ab.cd_pct / ab.ab_pct).toFixed(2) + ' 倍）' : '';
        if (t) c.label(t, (P[k - 1].x + P[k].x) / 2 + 6, (P[k - 1].y + P[k].y) / 2, COL.abcd);
      }
      P.forEach(p => badge(g, p.x + (p.k === 'A' ? 20 : 0), p.y + (p.k === 'A' ? 16 : p.k === 'C' ? 14 : -14) * k1, p.k, p.soft ? c.rgba(COL.abcd, 0.5) : COL.abcd, 8));     // A 和第三冲是同一根，往右让一格
      if (P.length > 1) c.label(num(legendN('abcd')), P[1].x + 16, P[1].y - 14 * k1, COL.abcd);
    }
    planBand(g, o, ab && ab.D ? c.X(I(ab.D.date)) : xe);
  }

  function drawBreakout(g, o) {
    const W = c.OV().w, short = o.side === 'short', lv = o.level.price, y = c.Y(lv), k1 = short ? 1 : -1;
    const brkWord = short ? '破位处' : '突破处';
    // 破位前的箱体
    if (o.box) {
      const x1 = c.X(I(o.box.start)), x2 = c.X(I(o.box.end)), yf = c.Y(o.box.far);
      if (x1 != null && x2 != null && y != null && yf != null) {
        g.fillStyle = c.rgba(COL.level, 0.07); g.fillRect(x1, Math.min(y, yf), x2 - x1, Math.abs(yf - y));
        g.strokeStyle = c.rgba(COL.level, 0.35); g.lineWidth = 1; g.setLineDash([3, 3]); g.strokeRect(x1, Math.min(y, yf), x2 - x1, Math.abs(yf - y)); g.setLineDash([]);
        c.label(num(legendN('bo_box')) + ' 箱体', x1 + 6, Math.min(y, yf) + 10, c.rgba(COL.level, 0.9));
      }
    }
    // 破位处：从第一次碰到它那天画到最右边
    const t0 = o.level.dates && o.level.dates.length ? c.X(I(o.level.dates[0])) : 0;
    if (y != null) {
      g.beginPath(); g.moveTo(Math.max(0, t0 == null ? 0 : t0), y); g.lineTo(W, y); g.strokeStyle = COL.level; g.lineWidth = 1.8; g.stroke();
      (o.level.dates || []).forEach(dt => { const x = c.X(I(dt)); if (x != null) { g.beginPath(); g.arc(x, y, 3.5, 0, Math.PI * 2); g.fillStyle = COL.level; g.fill(); } });
      c.label(num(legendN('bo_level')) + ' ' + brkWord + ' ' + c.fmtP(lv) + '（碰过 ' + o.level.touches + ' 次）', Math.max(8, (t0 || 0) + 8), y - 11 * k1, COL.level);
    }
    if (o.brk) { const x = c.X(I(o.brk.date)), yy = c.Y(o.brk.close); if (x != null && yy != null) { badge(g, x, yy + 18 * k1, '破', COL.level, 9); c.label(num(legendN('bo_brk')), x - 20, yy + 18 * k1, COL.level, 'center'); } }
    if (o.extreme) { const x = c.X(I(o.extreme.date)), yy = c.Y(o.extreme.price); if (x != null && yy != null) c.label((short ? '破位后最低 ' : '突破后最高 ') + c.fmtP(o.extreme.price), x + 8, yy + 12 * k1, c.C.target); }
    if (o.pull) { const x = c.X(I(o.pull.date)), yy = c.Y(o.pull.price); if (x != null && yy != null) badge(g, x, yy - 16 * k1, short ? '抽' : '踩', COL.abcd, 9); }
    planBand(g, o, o.pull ? c.X(I(o.pull.date)) : c.X(c.S.asof));
  }

  /* 通用画法：后端按一套固定的“图形清单”告诉这里在哪一天、哪个价位画什么（线、带子、线段、方框、圆点、文字、竖条、成交量分布），
     这里照着画，不认识模型。新加一个模型不用在这里添代码。日期一律是 K 线的日期，价位一律是真实价格。 */
  const INK = { vwap: '#f5c542', anchor: '#60a5fa', push: '#a78bfa', abcd: '#2dd4bf', level: '#fb923c', neck: '#fb923c', boll: '#7dd3fc', ma: '#e6e8ee', up: '#f0484e', down: '#1fa391',
    fib: '#8b93a5', warn: '#f5a524', note: '#e6e8ee', target: '#f472b6', stop: '#a78bfa', zone: '#34d399', wave: '#93c5fd', tri: '#fde047', risk: '#f87171', mute: '#6b7385' };
  const ink = s => INK[s] || COL[s] || '#8b93a5';
  function drawShapes(g, o) {
    const W = c.OV().w, H = c.OV().h;
    const XY = p => { const i = I(p[0]); if (i == null) return null; const x = c.X(i), y = c.Y(p[1]); return x == null || y == null ? null : [x, y]; };
    const tag = s => (s.key && legendN(s.key) ? num(legendN(s.key)) + ' ' : '');
    (o.shapes || []).forEach(s => {
      const col = ink(s.style), a = s.alpha == null ? 1 : s.alpha;
      if (s.t === 'line') {
        g.beginPath(); let pen = false, last = null;
        s.pts.forEach(p => { const q = p[1] == null ? null : XY(p); if (!q) { pen = false; return; } if (pen) g.lineTo(q[0], q[1]); else g.moveTo(q[0], q[1]); pen = true; last = q; });
        g.strokeStyle = c.rgba(col, a); g.lineWidth = s.w || 1.5; g.setLineDash(s.dash || []); g.stroke(); g.setLineDash([]);
        if (s.label && last) c.label(tag(s) + s.label, last[0] + 8, last[1] + (s.dy || -12), col);
      } else if (s.t === 'band') {
        const up = s.up.map(p => (p[1] == null ? null : XY(p))).filter(Boolean), lo = s.lo.map(p => (p[1] == null ? null : XY(p))).filter(Boolean);
        if (up.length > 1 && lo.length > 1) {
          g.beginPath(); up.forEach((q, k) => (k ? g.lineTo(q[0], q[1]) : g.moveTo(q[0], q[1]))); lo.slice().reverse().forEach(q => g.lineTo(q[0], q[1])); g.closePath();
          g.fillStyle = c.rgba(col, s.alpha == null ? 0.09 : s.alpha); g.fill();
        }
      } else if (s.t === 'seg') {
        const p = XY(s.a), q = XY(s.b); if (!p || !q) return;
        let x2 = q[0], y2 = q[1];
        if (s.extend && q[0] !== p[0]) { x2 = W; y2 = p[1] + (q[1] - p[1]) * (W - p[0]) / (q[0] - p[0]); }
        g.beginPath(); g.moveTo(p[0], p[1]); g.lineTo(x2, y2); g.strokeStyle = c.rgba(col, a); g.lineWidth = s.w || 1.5; g.setLineDash(s.dash || []); g.stroke(); g.setLineDash([]);
        if (s.label) c.label(tag(s) + s.label, (p[0] + q[0]) / 2 + 6, (p[1] + q[1]) / 2 + (s.dy || -10), col);
      } else if (s.t === 'hl') {                          // 一段水平线：从某一天画到另一天，或者画到最右边
        const i1 = I(s.d1), x1 = i1 == null ? 0 : c.X(i1), y = c.Y(s.p), x2 = s.d2 ? c.X(I(s.d2)) : W;
        if (y == null || x1 == null || x2 == null) return;
        g.beginPath(); g.moveTo(x1, y); g.lineTo(x2, y); g.strokeStyle = c.rgba(col, a); g.lineWidth = s.w || 1.6; g.setLineDash(s.dash || []); g.stroke(); g.setLineDash([]);
        if (s.label) c.label(tag(s) + s.label, Math.max(8, x1 + 8), y + (s.dy || -11), col);
      } else if (s.t === 'box') {
        const i1 = I(s.d1), i2 = s.d2 ? I(s.d2) : null, x1 = i1 == null ? null : c.X(i1), x2 = i2 == null ? W : c.X(i2), y1 = c.Y(s.p1), y2 = c.Y(s.p2);
        if (x1 == null || x2 == null || y1 == null || y2 == null) return;
        g.fillStyle = c.rgba(col, s.alpha == null ? 0.08 : s.alpha); g.fillRect(x1, Math.min(y1, y2), x2 - x1, Math.abs(y2 - y1));
        if (s.border !== false) { g.strokeStyle = c.rgba(col, 0.4); g.lineWidth = 1; g.setLineDash([3, 3]); g.strokeRect(x1, Math.min(y1, y2), x2 - x1, Math.abs(y2 - y1)); g.setLineDash([]); }
        if (s.label) c.label(tag(s) + s.label, x1 + 6, Math.min(y1, y2) + 10, c.rgba(col, 0.95));
      } else if (s.t === 'badge') {
        const q = XY([s.d, s.p]); if (!q) return;
        const dy = (s.pos === 'below' ? 1 : -1) * (s.off || 16);
        badge(g, q[0] + (s.dx || 0), q[1] + dy, s.text, s.soft ? c.rgba(col, 0.55) : col, s.r || 9);
        if (s.note) c.label(s.note, q[0] + (s.dx || 0), q[1] + dy + (s.pos === 'below' ? 20 : -20), col, 'center');
        if (s.key && legendN(s.key) && s.first) c.label(num(legendN(s.key)), q[0] - 22 + (s.dx || 0), q[1] + dy, col, 'center');
      } else if (s.t === 'dot') {
        const q = XY([s.d, s.p]); if (!q) return;
        g.beginPath(); g.arc(q[0], q[1], s.r || 4, 0, Math.PI * 2); g.fillStyle = c.rgba(col, a); g.fill();
        if (s.ring) { g.beginPath(); g.arc(q[0], q[1], (s.r || 4) + 5, 0, Math.PI * 2); g.strokeStyle = col; g.lineWidth = 1.5; g.stroke(); }
        if (s.label) c.label(tag(s) + s.label, q[0] + 9, q[1] + (s.pos === 'below' ? 13 : -12), col);
      } else if (s.t === 'text') {
        const q = XY([s.d, s.p]); if (!q) return;
        c.label(tag(s) + s.text, q[0] + (s.dx == null ? 8 : s.dx), q[1] + (s.pos === 'below' ? 13 : -12), col, s.align || 'left');
      } else if (s.t === 'vbar') {
        const i = I(s.d), x = i == null ? null : c.X(i); if (x == null) return;
        g.fillStyle = c.rgba(col, 0.22); g.fillRect(x - 4, 0, 8, H);
        if (s.label) c.label(tag(s) + s.label, x + 8, 30, col);
      } else if (s.t === 'profile') {                     // 成交量分布：从 d1 那根往右伸出去的一排横条，最长的那一条（量最大的价位）单独上色
        const i1 = I(s.d1), i2 = I(s.d2), x1 = i1 == null ? null : c.X(i1), x2 = i2 == null ? null : c.X(i2); if (x1 == null || x2 == null) return;
        const mx = Math.max.apply(null, s.vol) || 1, span = (x2 - x1) * 0.55;
        s.vol.forEach((v, k) => {
          const ya = c.Y(s.lo + k * s.step), yb = c.Y(s.lo + (k + 1) * s.step); if (ya == null || yb == null) return;
          const top = Math.min(ya, yb), hgt = Math.max(1, Math.abs(yb - ya) - 1), on = s.poc != null && s.poc >= s.lo + k * s.step && s.poc < s.lo + (k + 1) * s.step;
          g.fillStyle = c.rgba(on ? ink('warn') : col, on ? 0.55 : 0.28); g.fillRect(x1, top, span * v / mx, hgt);
        });
        if (s.label) { const y = c.Y(s.poc); if (y != null) c.label(tag(s) + s.label, x1 + span + 6, y, ink('warn')); }
      }
    });
    planBand(g, o, o.zone_from ? c.X(I(o.zone_from)) : c.X(c.S.asof));
  }

  /* 逐条画线。横线的标签贴在右边缘；挨得太近的标签上下错开（照录屏：一排标签叠着排，不互相盖住） */
  function drawLines(g, lines) {
    const W = c.OV().w, H = c.OV().h, tags = [];
    const from = Math.max(0, c.S.asof - 45);
    lines.filter(x => !Q.off[x.id]).slice(0, Q.shown).forEach(x => {
      if (x.group !== 'model' && !Q.linesOn) return;
      const col = COL[x.style] || c.C[x.style] || '#8b93a5', tag = (num(x.n) ? num(x.n) + ' ' : '');
      if (x.kind === 'level') {
        const x0 = x.span ? c.X(I(x.span.low.date)) : x.group === 'model' ? c.X(from) : 0;
        const fib = x.style === 'fib', plan = x.group === 'model';
        const y = hline(g, x0 == null ? 0 : x0, x.price, fib ? c.rgba(col, 0.55) : col, fib ? [2, 4] : plan ? (x.style === 'zone' ? [8, 4] : [3, 4]) : [5, 4], fib ? 1 : plan ? 1.5 : 1.3);
        if (y != null && y > -8 && y < H + 8) tags.push({ y, text: tag + x.label + ' · ' + c.fmtP(x.price), col });
      } else if (x.kind === 'trend') {
        const i1 = I(x.p1.date), i2 = I(x.p2.date), x1 = c.X(i1), y1 = c.Y(x.p1.price), x2 = c.X(i2), y2 = c.Y(x.p2.price);
        if (x1 == null || x2 == null || y1 == null || y2 == null || x2 === x1) return;
        const yr = y1 + (y2 - y1) * (W - x1) / (x2 - x1);
        g.beginPath(); g.moveTo(x1, y1); g.lineTo(W, yr); g.strokeStyle = col; g.lineWidth = 1.3; g.stroke();
        c.label(tag + x.label, x2 + 10, y2 + (x.style === 'tres' ? -12 : 12), col);
      }
    });
    tags.sort((a, b) => a.y - b.y);
    let last = -1e9;
    tags.forEach(t => {
      const y = Math.max(t.y, last + 15); last = y;
      if (Math.abs(y - t.y) > 1) { g.beginPath(); g.moveTo(W - 4, t.y); g.lineTo(W - 12, y); g.strokeStyle = c.rgba(t.col, 0.5); g.lineWidth = 1; g.stroke(); }
      c.label(t.text, W - 6, y, t.col, 'right');
    });
  }

  function draw() {
    if (!fresh()) return;
    const g = c.g(), d = Q.data;
    if (d.overlay && d.overlay.kind === 'houshou') drawHoushou(g, d.overlay);
    if (d.overlay && d.overlay.kind === 'breakout') drawBreakout(g, d.overlay);
    if (d.overlay && d.overlay.kind === 'shapes') drawShapes(g, d.overlay);
    drawLines(g, d.lines);
  }

  // ---------- 右键：写备注、手动成本锚点（只在后手模型下）----------
  function onContext(e) {
    if (!c.stateFresh()) return;
    e.preventDefault();
    const pt = c.ptFromEvent(e), i = Math.max(0, Math.min(c.S.asof, pt.li)), date = c.S.bars.d[i], m = $('#qMenu');
    const manual = fresh() && Q.data.signal.anchor && Q.data.signal.anchor.by === 'manual';
    m.textContent = '';
    const add = (text, fn, off) => { const b = document.createElement('button'); b.textContent = text; b.disabled = !!off; b.onclick = () => { m.hidden = true; fn(); }; m.appendChild(b); };
    if (window.FENotes && c.isDaily()) window.FENotes.menu(date, add);        // 写备注、联网查这一天（备注按交易日记）
    if (Q.model === 'houshou') {
      add('设为成本锚点（' + date + (Q.side === 'short' ? ' · 做空一侧' : '') + '）', () => anchor(date));
      add('清除手动锚点，回到自动', () => anchor(null), !manual);
    }
    if (!m.children.length) return;
    const r = $('#chartwrap').getBoundingClientRect();
    m.style.left = Math.min(e.clientX - r.left, r.width - 220) + 'px'; m.style.top = Math.min(e.clientY - r.top, r.height - 80) + 'px';
    m.hidden = false;
  }
  async function anchor(date) {
    try {
      const r = await c.api('/api/quant/anchor', { ticker: c.S.ticker, date, side: Q.side, tf: tf() });
      if (r.ok === false) throw new Error(r.error);
      c.toast(date ? '成本锚点设在 ' + date + '（手动）。' : '已清除手动锚点，回到自动。');
      c.narr.reset(); Q.data = null; fetch(); c.refreshState();
    } catch (e) { c.toast('锚点没改成：' + e.message, true); }
  }

  return { init, reset, onState, render, draw, run, setModel, set, use, setTab, goTo, profile, query, chrome, model: () => Q.model, side: () => Q.side, tab: () => Q.tab, hideFour, fresh, data: () => Q.data,
    animating: () => Q.running || performance.now() < Q.animUntil, state: () => Q, setAnchor: anchor, loadTasks, loadRuns, setAuto, autoRun,
    auto: () => ({ on: Q.auto, res: Q.autoRes }) };
})();
