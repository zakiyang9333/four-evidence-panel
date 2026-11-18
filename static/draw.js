/* 左边的画线工具栏，照录屏（TradingVane）的排法：光标；线 / 斐波那契 / 形态 / 仓位与测量四组，每组一个弹出菜单；
   画笔、文字、表情、尺子、放大、磁铁、锁定、隐藏、同步、删除；最下面是收藏。
   这里只管画：点几下、存下来、按 K 线日期和价格画出来。不做任何规则判定，也不下单（多头 / 空头仓位只是画一个盈亏框）。
   原来就有的扇形、水平线、锚定 VWAP、箭头文字仍由 app.js 画（data-tool 名字不变），新工具都在这里。 */
window.FEDraw = (() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  let c = null, hits = {}, stroke = null, emoji = '👍', ruler = null;
  const COL = '#7dd3fc', SEL = '#ffffff', PAT = '#a78bfa', FIB = ['#94a3b8', '#f87171', '#fb923c', '#facc15', '#4ade80', '#2dd4bf', '#60a5fa', '#a78bfa', '#f472b6'];
  const LEGACY = { hline: 1, fan: 1, avwap: 1, arrow: 1 };

  // ---------- 图标（简笔线条，SVG 24×24）----------
  const I = {
    cursor: 'M12 4v16M4 12h16', trend: 'M5 19L19 5M5 19h0M19 5h0', ray: 'M5 19L15 9M15 9l4-4', info: 'M5 19L14 10M15 15h5v4h-5z', ext: 'M3 21L21 3', angle: 'M5 19h14M5 19L17 7M11 19a6 6 0 0 0-1.7-4.3',
    hline: 'M3 12h18', hray: 'M6 12h15M6 10v4', vline: 'M12 3v18', cross: 'M12 3v18M3 12h18', parallel: 'M4 15L15 4M9 20L20 9', regression: 'M4 16L20 8M4 20L20 12M4 12L20 4',
    flat: 'M4 18L18 8M4 8h14', disjoint: 'M4 18L12 6M10 20L20 10', pitchfork: 'M4 20L20 4M8 20L20 8M4 16L16 4', schiff: 'M4 18L20 6M6 20L20 10M4 14L16 4', fib: 'M3 5h18M3 9h18M3 13h18M3 17h18M3 21h18',
    fibext: 'M4 20L10 8L14 14M14 6h7M14 10h7M14 14h7', fibch: 'M4 18L18 4M6 22L22 8M5 20L20 6', fibtime: 'M5 4v16M8 4v16M13 4v16M21 4v16', fan: 'M4 5l16 4M4 5l16 9M4 5l15 14',
    circle: 'M12 12m-8 0a8 8 0 1 0 16 0a8 8 0 1 0-16 0M12 12m-4 0a4 4 0 1 0 8 0a4 4 0 1 0-8 0', spiral: 'M12 12a2 2 0 0 1 2 2a4 4 0 0 1-4 4a6 6 0 0 1-6-6a8 8 0 0 1 8-8', arc: 'M4 20a8 8 0 0 1 16 0M8 20a4 4 0 0 1 8 0',
    wedge: 'M4 12L20 4M4 12L20 20M14 7v10', pitchfan: 'M4 12L20 4M4 12L20 12M4 12L20 20', gannbox: 'M4 4h16v16H4zM4 12h16M12 4v16', gannsq: 'M4 4h16v16H4zM4 4l16 16M20 4L4 20', gannfan: 'M4 20L20 4M4 20L20 12M4 20L12 4M4 20h16',
    xabcd: 'M3 18L7 6L11 14L15 8L20 18', abcd: 'M4 18L9 6L14 12L20 4', hs: 'M3 18L6 11L9 15L12 5L15 15L18 11L21 18', tri: 'M4 6L20 12L4 18z', drives: 'M3 18L6 10L8 14L12 7L14 11L19 4',
    wave: 'M3 18L6 12L8 15L13 6L15 10L20 3', abc: 'M4 6L9 16L13 10L19 20', cycle: 'M5 4v16M10 4v16M15 4v16M20 4v16', tcycle: 'M2 18a5 5 0 0 1 10 0a5 5 0 0 1 10 0', sine: 'M3 12c3-8 6-8 9 0s6 8 9 0',
    long: 'M5 5h14v6H5zM5 11h14v8H5z', short: 'M5 5h14v8H5zM5 13h14v6H5z', forecast: 'M4 18L18 6M18 6h-5M18 6v5', bars: 'M6 6v12M10 9v6M14 5v10M18 8v8', ghost: 'M6 8v8M10 6v8M14 9v8M18 7v6', sector: 'M4 20L20 20A16 16 0 0 0 8 6z',
    avwap: 'M3 15c4-1 5-6 9-6s5 3 9 2', vp: 'M4 4v16M4 7h10M4 11h14M4 15h8M4 19h5', avp: 'M4 12h2M8 6v12M8 8h9M8 12h12M8 16h6', prange: 'M12 4v16M8 4h8M8 20h8', drange: 'M4 12h16M4 8v8M20 8v8', dprange: 'M4 4h16v16H4zM12 7v10M7 12h10',
    brush: 'M4 20c3 0 4-2 5-4l9-11 2 2-11 9c-2 1-4 2-5 4z', text: 'M6 5h12M12 5v14', arrow: 'M5 19L18 6M18 6h-7M18 6v7', emoji: 'M12 12m-8 0a8 8 0 1 0 16 0a8 8 0 1 0-16 0M9 10h0M15 10h0M8.5 14.5a4 4 0 0 0 7 0',
    ruler: 'M3 9h18v6H3zM7 9v3M11 9v3M15 9v3M19 9v3', zoom: 'M10 10m-6 0a6 6 0 1 0 12 0a6 6 0 1 0-12 0M15 15l5 5M10 7v6M7 10h6', magnet: 'M6 4v8a6 6 0 0 0 12 0V4h-4v8a2 2 0 0 1-4 0V4z',
    lock: 'M6 11h12v9H6zM9 11V7a3 3 0 0 1 6 0', eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 12m-3 0a3 3 0 1 0 6 0a3 3 0 1 0-6 0', link: 'M10 14a4 4 0 0 0 6 0l3-3a4 4 0 0 0-6-6l-1 1M14 10a4 4 0 0 0-6 0l-3 3a4 4 0 0 0 6 6l1-1',
    trash: 'M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13', star: 'M12 3l2.6 5.6 6.1.7-4.5 4.2 1.2 6L12 16.6 6.6 19.5l1.2-6L3.3 9.3l6.1-.7z', auto: 'M4 5l16 5M4 5l16 9M4 5l16 13',
  };
  const svg = k => '<svg viewBox="0 0 24 24"><path d="' + (I[k] || I.trend) + '"/></svg>';

  // ---------- 工具清单：名字、点几下、提示、所在的组（和录屏的菜单一一对应）----------
  const G = [
    { id: 'lines', icon: 'trend', label: '线条', sec: [
      ['线', [['trend', '趋势线', 2, 'Alt+T'], ['ray', '射线', 2], ['info', '信息线', 2], ['ext', '延长线', 2], ['angle', '趋势角度', 2], ['hline', '水平线', 1, 'Alt+H'], ['hray', '水平射线', 1, 'Alt+J'],
              ['vline', '垂直线', 1, 'Alt+V'], ['cross', '横线', 1, 'Alt+C']]],
      ['通道', [['parallel', '平行通道', 3], ['regression', '回归趋势', 2], ['flat', '平顶/平底', 3], ['disjoint', '不相交通道', 4]]],
      ['分叉线', [['pitchfork', '分叉线', 3], ['schiff', '希夫干草叉', 3], ['modschiff', '改良希夫干草叉', 3], ['inside', '内部分叉线', 3]]]] },
    { id: 'fibs', icon: 'fib', label: '斐波那契', sec: [
      ['斐波那契', [['fibret', '斐波那契回撤', 2, 'Alt+F'], ['fibext', '斐波那契趋势扩展', 3], ['fibch', '斐波那契通道', 3], ['fibtime', '斐波那契时区', 2], ['fan', '斐波那契速度阻力扇', 2],
                   ['fibtt', '斐波那契趋势时间', 3], ['fibcircle', '斐波那契圈', 2], ['fibspiral', '斐波那契螺旋', 2], ['fibarc', '斐波那契速度阻力弧', 2], ['fibwedge', '斐波那契楔形', 3], ['pitchfan', '倾斜扇形', 3]]],
      ['江恩', [['gannbox', '江恩箱', 2], ['gannfix', '固定江恩正方', 2], ['gannsq', '江恩正方', 2], ['gannfan', '江恩扇', 2]]]] },
    { id: 'patterns', icon: 'xabcd', label: '形态', sec: [
      ['图表形态', [['xabcd', 'XABCD形态', 5], ['cypher', '赛福形态', 5], ['hs', '头肩形态', 7], ['abcd', 'ABCD形态', 4], ['tripat', '三角形态', 4], ['drives', '三驱形态', 7]]],
      ['艾略特波浪', [['ew5', '艾略特脉冲波（1·2·3·4·5）', 6], ['ewabc', '艾略特修正浪（A·B·C）', 4], ['ewtri', '艾略特三角波（A·B·C·D·E）', 6], ['ewwxy', '艾略特双重组合浪（W·X·Y）', 4],
                     ['ewwxyxz', '艾略特三重组合浪（W·X·Y·X·Z）', 6]]],
      ['循环', [['cycle', '循环线', 2], ['tcycle', '时间循环', 2], ['sine', '正弦线', 2]]]] },
    { id: 'measure', icon: 'long', label: '仓位·测量', sec: [
      ['', [['long', '多头仓位', 2], ['short', '空头仓位', 2], ['forecast', '仓位预测', 2], ['bars', 'K线形态', 3], ['ghost', '模拟K线', 2], ['sector', '扇形', 3]]],
      ['基于成交量', [['avwap', '锚定VWAP', 1], ['vp', '固定范围成交量分布图', 2], ['avp', '锚定成交量分布图', 1]]],
      ['测量', [['prange', '价格范围', 2], ['drange', '日期范围', 2], ['dprange', '日期和价格范围', 2]]]] },
  ];
  const TOOLS = {};
  G.forEach(g => g.sec.forEach(s => s[1].forEach(t => { TOOLS[t[0]] = { key: t[0], name: t[1], n: t[2], kbd: t[3] || '', group: g.id }; })));
  Object.assign(TOOLS, { brush: { key: 'brush', name: '画笔', n: 0 }, text: { key: 'text', name: '文字', n: 1, group: 'text' }, arrow: { key: 'arrow', name: '箭头文字', n: 2, group: 'text' },
    emoji: { key: 'emoji', name: '表情', n: 1 }, ruler: { key: 'ruler', name: '尺子', n: 2 }, zoom: { key: 'zoom', name: '放大', n: 2 } });
  const ICON = { modschiff: 'schiff', inside: 'pitchfork', fibtt: 'fibtime', fibcircle: 'circle', fibspiral: 'spiral', fibarc: 'arc', fibwedge: 'wedge', gannfix: 'gannsq', cypher: 'xabcd', tripat: 'tri',
    ew5: 'wave', ewabc: 'abc', ewtri: 'wave', ewwxy: 'abc', ewwxyxz: 'wave' };
  const icon = k => svg(I[k] ? k : ICON[k] || 'trend');
  const ORDER = n => '先点第 1 个点（共 ' + n + ' 个）';
  const has = t => !!TOOLS[t] && !LEGACY[t];

  // ---------- 工具栏 ----------
  function build() {
    const nav = $('#tools'), fav = c.store.get('draw.fav', []), last = c.store.get('draw.last', {});
    const btn = (attrs, ic, label, extra) => '<button ' + attrs + ' title="' + label + '">' + svg(ic) + (extra || '') + '<span>' + label + '</span></button>';
    let h = btn('data-tool="cursor"', 'cursor', '光标') + btn('id="autoBtn"', 'auto', '自动画') + '<hr>';
    G.forEach(g => {
      const cur = TOOLS[last[g.id]] || TOOLS[g.sec[0][1][0][0]];
      h += '<div class="tb-group" data-group="' + g.id + '"><button class="tb-main" data-tool="' + cur.key + '" data-main="' + g.id + '" title="' + cur.name + '">' + icon(cur.key) + '<span>' + esc(short(cur.key)) + '</span></button>' +
        '<button class="tb-more" data-open="' + g.id + '" title="' + g.label + '：展开全部工具">‹</button><div class="tb-menu" data-menu="' + g.id + '" hidden>' +
        g.sec.map(s => (s[0] ? '<div class="tb-sec">' + s[0] + '</div>' : '') + s[1].map(t => '<div class="tb-row"><button class="tb-item" data-tool="' + t[0] + '">' + icon(t[0]) + '<b>' + t[1] + '</b>' +
          (t[3] ? '<kbd>' + t[3] + '</kbd>' : '') + '</button><button class="tb-fav' + (fav.indexOf(t[0]) >= 0 ? ' on' : '') + '" data-fav="' + t[0] + '" title="收藏">☆</button></div>').join('')).join('') + '</div></div>';
    });
    h += btn('data-tool="brush"', 'brush', '画笔') +
      '<div class="tb-group" data-group="text"><button class="tb-main" data-tool="' + (last.text === 'arrow' ? 'arrow' : 'text') + '" data-main="text" title="' + (last.text === 'arrow' ? '箭头文字' : '文字') + '">' +
      svg(last.text === 'arrow' ? 'arrow' : 'text') + '<span>' + (last.text === 'arrow' ? '箭头文字' : '文字') + '</span></button><button class="tb-more" data-open="text" title="文字工具">‹</button>' +
      '<div class="tb-menu" data-menu="text" hidden><div class="tb-sec">文字</div><div class="tb-row"><button class="tb-item" data-tool="text">' + svg('text') + '<b>文字</b></button></div>' +
      '<div class="tb-row"><button class="tb-item" data-tool="arrow">' + svg('arrow') + '<b>箭头文字</b></button></div></div></div>' +
      '<div class="tb-group" data-group="emoji"><button class="tb-main" data-tool="emoji" data-main="emoji" title="表情">' + svg('emoji') + '<span>表情</span></button><button class="tb-more" data-open="emoji" title="选一个表情">‹</button>' +
      '<div class="tb-menu tb-emoji" data-menu="emoji" hidden><div class="tb-sec">表情</div>' + ['👍', '👎', '🔥', '⚠️', '🚀', '📈', '📉', '✅', '❌', '❓', '💰', '🎯', '👀', '🧊', '⭐', '😂'].map(e => '<button class="tb-emo" data-emo="' + e + '">' + e + '</button>').join('') + '</div></div>' +
      '<hr>' + btn('data-tool="ruler"', 'ruler', '尺子') + btn('data-tool="zoom"', 'zoom', '放大') + '<hr>' +
      btn('id="tbMagnet" data-toggle="magnet"', 'magnet', '磁铁') + btn('id="tbLock" data-toggle="lock"', 'lock', '锁定') + btn('id="tbHide" data-toggle="hide"', 'eye', '隐藏') + btn('id="tbSync" data-toggle="sync"', 'link', '同步') +
      '<div class="tb-group" data-group="del"><button class="tb-main" id="delBtn" title="删除选中的画线（先在光标模式下点一下那条线，或按 Delete）">' + svg('trash') + '<span>删除</span></button>' +
      '<button class="tb-more" data-open="del" title="删除选项">‹</button><div class="tb-menu" data-menu="del" hidden><div class="tb-row"><button class="tb-item" id="delSelBtn">' + svg('trash') + '<b>删除选中的画线</b><kbd>Delete</kbd></button></div>' +
      '<div class="tb-row"><button class="tb-item" id="clearBtn">' + svg('trash') + '<b>删除这只标的的全部画线</b></button></div></div></div>' +
      '<span class="tb-spacer"></span>' + btn('id="tbFav"', 'star', '收藏');
    nav.innerHTML = h;
    toggles();
    const bar = document.createElement('div'); bar.id = 'favBar'; bar.hidden = true; $('#chartwrap').appendChild(bar);
    favBar();
  }
  const esc = s => String(s).replace(/[&<>"]/g, x => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[x]));
  const SHORT = { fibret: '斐波回撤', fibext: '斐波扩展', fibch: '斐波通道', fibtime: '斐波时区', fan: '扇形', fibtt: '趋势时间', fibcircle: '斐波圈', fibspiral: '斐波螺旋', fibarc: '阻力弧',
    fibwedge: '斐波楔形', pitchfan: '倾斜扇形', gannfix: '固定江恩', gannsq: '江恩正方', modschiff: '改良叉', schiff: '干草叉', inside: '内部分叉', vp: '范围量山', avp: '锚定量山', avwap: '锚定VWAP',
    dprange: '日期价格', ew5: '脉冲波', ewabc: '修正浪', ewtri: '三角波', ewwxy: '双重组合', ewwxyxz: '三重组合', xabcd: 'XABCD', cypher: '赛福', hs: '头肩', abcd: 'ABCD', tripat: '三角形态',
    drives: '三驱', disjoint: '不相交', flat: '平顶平底', regression: '回归趋势', parallel: '平行通道', hline: '水平线', hray: '水平射线' };
  const short = k => SHORT[k] || (TOOLS[k] ? TOOLS[k].name.slice(0, 4) : k);
  function closeMenus(except) { $$('.tb-menu').forEach(m => { if (m.dataset.menu !== except) m.hidden = true; }); }
  function favBar() {
    const fav = c.store.get('draw.fav', []), bar = $('#favBar'); if (!bar) return;
    bar.innerHTML = fav.length ? fav.filter(k => TOOLS[k]).map(k => '<button data-tool="' + k + '" title="' + TOOLS[k].name + '">' + icon(k) + '</button>').join('') : '<span>还没有收藏。在工具菜单里点 ☆ 收藏常用的工具。</span>';
    bar.hidden = !c.store.get('draw.favOn', false);
    $('#tbFav').classList.toggle('on', !bar.hidden);
  }
  function toggles() {
    const S = c.S;
    [['magnet', '#tbMagnet', '磁铁：画线的点吸到最近那根 K 线的开高低收上'], ['lock', '#tbLock', '锁定：画好的线不能再选中、删除'], ['hide', '#tbHide', '隐藏：先把手动画线全部藏起来'],
      ['sync', '#tbSync', '同步：日线和周线共用同一套手动画线']].forEach(([k, sel, tip]) => {
      const on = !!S.dt[k], b = $(sel); if (!b) return;
      b.classList.toggle('on', on); b.title = tip + (on ? '（开着）' : '（关着）');
    });
  }
  function onBar(e) {
    const t = e.target.closest('button'); if (!t) return;
    if (t.dataset.open) { const m = $('.tb-menu[data-menu="' + t.dataset.open + '"]'); closeMenus(t.dataset.open); m.hidden = !m.hidden; if (!m.hidden) place(m, t); return; }
    if (t.dataset.fav) {
      const fav = c.store.get('draw.fav', []), k = t.dataset.fav, i = fav.indexOf(k);
      if (i >= 0) fav.splice(i, 1); else fav.push(k);
      c.store.set('draw.fav', fav); t.classList.toggle('on', i < 0); favBar(); return;
    }
    if (t.dataset.emo) { emoji = t.dataset.emo; closeMenus(); c.setTool('emoji'); return; }
    if (t.id === 'tbFav') { c.store.set('draw.favOn', !c.store.get('draw.favOn', false)); favBar(); return; }
    if (t.dataset.toggle) {
      const k = t.dataset.toggle; c.S.dt[k] = !c.S.dt[k]; c.store.set('dt', c.S.dt); toggles();
      if (k === 'sync') c.reloadDrawings();
      if (k === 'lock' && c.S.dt.lock) { c.S.selected = -1; }
      c.toast({ magnet: '磁铁', lock: '锁定画线', hide: '隐藏画线', sync: '日线周线同步画线' }[k] + (c.S.dt[k] ? '：开' : '：关')); c.redraw(); return;
    }
    if (t.id === 'delBtn' || t.id === 'delSelBtn') { closeMenus(); c.deleteSelected(); return; }
    if (t.id === 'clearBtn') { closeMenus(); c.clearAll(); return; }
    if (t.dataset.tool) {
      const k = t.dataset.tool, tool = TOOLS[k];
      if (tool && tool.group && t.classList.contains('tb-item')) {     // 从菜单里选了一个：这一组的主按钮换成它（下次直接点）
        const last = c.store.get('draw.last', {}); last[tool.group] = k; c.store.set('draw.last', last);
        const main = $('.tb-main[data-main="' + tool.group + '"]'); if (main) { main.dataset.tool = k; main.title = tool.name; main.innerHTML = icon(k) + '<span>' + esc(short(k)) + '</span>'; }
      }
      closeMenus();
      c.setTool(k === c.S.tool && !t.classList.contains('tb-item') ? 'cursor' : k);
    }
  }
  function place(m, t) {
    const r = t.getBoundingClientRect(), nav = $('#tools').getBoundingClientRect();
    m.style.left = (nav.right + 2) + 'px'; m.style.top = Math.max(4, Math.min(r.top - 8, innerHeight - m.offsetHeight - 8)) + 'px';
  }
  function sync(tool) {        // 光标、主按钮、菜单项上的“正在用”
    $$('#tools [data-tool], #favBar [data-tool]').forEach(b => b.classList.toggle('on', b.dataset.tool === tool));
    $$('#tools .tb-group').forEach(g => g.classList.toggle('on', !!g.querySelector('.tb-main.on, .tb-item.on')));
  }

  // ---------- 点和坐标 ----------
  const S = () => c.S;
  const B = () => c.S.bars;
  function pick(pt) {          // 点击的位置 → {i, p, d}；磁铁开着就吸到这根 K 线的开高低收
    const b = B(), i = Math.max(0, pt.li);
    let p = pt.p;
    if (S().dt.magnet && i <= S().asof) {
      let best = null;
      ['o', 'h', 'l', 'c'].forEach(k => { const y = c.Y(b[k][i]); if (y != null && (best == null || Math.abs(pt.y - y) < best[0])) best = [Math.abs(pt.y - y), b[k][i]]; });
      if (best && best[0] < 30) p = best[1];
    }
    return { i, p, d: b.d[i] || null };
  }
  const XY = q => { const x = c.X(q.i), y = c.Y(q.p); return x == null || y == null ? null : [x, y]; };
  const W = () => c.OV().w, H = () => c.OV().h;
  const pctTxt = (a, b) => (a ? ((b / a - 1) * 100 >= 0 ? '+' : '') + ((b / a - 1) * 100).toFixed(2) + '%' : '');
  const bars = (a, b) => Math.abs(b.i - a.i);

  // ---------- 画图的小工具（顺手记下命中区域，好让光标点中它）----------
  let G2 = null, K = -1;
  function seg(x0, y0, x1, y1, col, w, dash) {
    const g = G2; g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.strokeStyle = col; g.lineWidth = w || 1.5; g.setLineDash(dash || []); g.stroke(); g.setLineDash([]);
    if (K >= 0) (hits[K] = hits[K] || []).push([x0, y0, x1, y1]);
  }
  function poly(pts, col, w, dash, close) { for (let k = 1; k < pts.length; k++) seg(pts[k - 1][0], pts[k - 1][1], pts[k][0], pts[k][1], col, w, dash); if (close && pts.length > 2) seg(pts[pts.length - 1][0], pts[pts.length - 1][1], pts[0][0], pts[0][1], col, w, dash); }
  function fill(pts, col, a) { const g = G2; g.beginPath(); pts.forEach((p, k) => (k ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]))); g.closePath(); g.fillStyle = c.rgba(col, a == null ? 0.12 : a); g.fill(); }
  function dot(x, y, col, r) { const g = G2; g.beginPath(); g.arc(x, y, r || 3.5, 0, Math.PI * 2); g.fillStyle = col; g.fill(); if (K >= 0) (hits[K] = hits[K] || []).push([x, y, x, y]); }
  function tag(text, x, y, col, align) { c.label(text, x, y, col, align); }
  function ring(x, y, rx, ry, col, a0, a1, dash) {
    const g = G2, N = 48, pts = [];
    for (let k = 0; k <= N; k++) { const t = a0 + (a1 - a0) * k / N; pts.push([x + rx * Math.cos(t), y + ry * Math.sin(t)]); }
    poly(pts, col, 1.2, dash);
  }
  function extend(x0, y0, x1, y1, left, right) {      // 把一条线段延长到画布边上
    if (x1 === x0) return [x0, left ? 0 : y0, x1, right ? H() : y1];
    const k = (y1 - y0) / (x1 - x0);
    const xa = left ? 0 : x0, xb = right ? W() : x1;
    return [xa, y0 + k * (xa - x0), xb, y0 + k * (xb - x0)];
  }
  function badge(x, y, text, col) {
    const g = G2; g.font = '700 11px -apple-system,"PingFang SC",sans-serif';
    const w = Math.max(18, g.measureText(text).width + 8);
    g.fillStyle = col; g.beginPath(); g.roundRect ? g.roundRect(x - w / 2, y - 9, w, 18, 9) : g.rect(x - w / 2, y - 9, w, 18); g.fill();
    g.fillStyle = '#0b0e14'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, x, y + 0.5);
    if (K >= 0) (hits[K] = hits[K] || []).push([x, y, x, y]);
  }
  const closes = (a, b) => { const lo = Math.max(0, Math.min(a, b)), hi = Math.min(S().asof, Math.max(a, b)); const out = []; for (let i = lo; i <= hi; i++) out.push([i, B().c[i]]); return out; };

  // ---------- 每种工具怎么画（pts 都是 {i, p}；col 是颜色）----------
  const R = {
    trend: (P, col) => { const [a, b] = P; seg(a[0], a[1], b[0], b[1], col); dot(a[0], a[1], col, 2.5); dot(b[0], b[1], col, 2.5); },
    ray: (P, col) => { const [a, b] = P, e = extend(a[0], a[1], b[0], b[1], false, true); seg(e[0], e[1], e[2], e[3], col); dot(a[0], a[1], col, 2.5); },
    ext: (P, col) => { const [a, b] = P, e = extend(a[0], a[1], b[0], b[1], true, true); seg(e[0], e[1], e[2], e[3], col); },
    info: (P, col, q) => { R.trend(P, col); const [a, b] = q; tag((b.p - a.p >= 0 ? '+' : '') + c.fmtP(b.p - a.p) + '（' + pctTxt(a.p, b.p) + '） · ' + bars(a, b) + ' 根 · ' + angleOf(P) + '°', P[1][0] + 8, P[1][1] - 12, col); },
    angle: (P, col) => { const [a, b] = P; seg(a[0], a[1], b[0], b[1], col); seg(a[0], a[1], a[0] + 60, a[1], col, 1, [4, 3]); const t = Math.atan2(b[1] - a[1], b[0] - a[0]); ring(a[0], a[1], 26, 26, col, Math.min(0, t), Math.max(0, t)); tag(angleOf(P) + '°', a[0] + 32, a[1] + (t < 0 ? -10 : 12), col); },
    hray: (P, col, q) => { const [a] = P; seg(a[0], a[1], W(), a[1], col); dot(a[0], a[1], col, 2.5); tag(c.fmtP(q[0].p), W() - 6, a[1] - 9, col, 'right'); },
    vline: (P, col, q) => { const [a] = P; seg(a[0], 0, a[0], H(), col); tag(q[0].d || '', a[0] + 6, H() - 14, col); },
    cross: (P, col, q) => { const [a] = P; seg(a[0], 0, a[0], H(), col, 1); seg(0, a[1], W(), a[1], col, 1); tag(c.fmtP(q[0].p) + ' · ' + (q[0].d || ''), a[0] + 6, a[1] - 9, col); },
    parallel: (P, col) => { const [a, b, d] = P, off = d[1] - (a[1] + (b[1] - a[1]) * (d[0] - a[0]) / ((b[0] - a[0]) || 1)); seg(a[0], a[1], b[0], b[1], col); seg(a[0], a[1] + off, b[0], b[1] + off, col); seg(a[0], a[1] + off / 2, b[0], b[1] + off / 2, col, 1, [4, 4]); fill([[a[0], a[1]], [b[0], b[1]], [b[0], b[1] + off], [a[0], a[1] + off]], col, 0.08); },
    regression: (P, col, q) => {
      const pts = closes(q[0].i, q[1].i); if (pts.length < 3) return R.trend(P, col);
      const n = pts.length, mx = pts.reduce((s, p) => s + p[0], 0) / n, my = pts.reduce((s, p) => s + p[1], 0) / n;
      let sxy = 0, sxx = 0; pts.forEach(p => { sxy += (p[0] - mx) * (p[1] - my); sxx += (p[0] - mx) * (p[0] - mx); });
      const k = sxx ? sxy / sxx : 0, b0 = my - k * mx, sd = Math.sqrt(pts.reduce((s, p) => s + Math.pow(p[1] - (b0 + k * p[0]), 2), 0) / n);
      const i0 = pts[0][0], i1 = pts[n - 1][0], X0 = c.X(i0), X1 = c.X(i1);
      [[0, 1.6], [2, 1], [-2, 1]].forEach(([m, w]) => { const y0 = c.Y(b0 + k * i0 + m * sd), y1 = c.Y(b0 + k * i1 + m * sd); if (X0 != null && y0 != null && X1 != null && y1 != null) seg(X0, y0, X1, y1, col, w, m ? [5, 4] : []); });
      const ya = c.Y(b0 + k * i0 + 2 * sd), yb = c.Y(b0 + k * i1 + 2 * sd), yc = c.Y(b0 + k * i1 - 2 * sd), yd = c.Y(b0 + k * i0 - 2 * sd);
      if ([X0, X1, ya, yb, yc, yd].every(v => v != null)) fill([[X0, ya], [X1, yb], [X1, yc], [X0, yd]], col, 0.07);
      if (X1 != null) tag('回归趋势 ±2σ · 每根 ' + (k >= 0 ? '+' : '') + c.fmtP(k), X1 + 8, c.Y(b0 + k * i1) - 10, col);
    },
    flat: (P, col) => { const [a, b, d] = P; seg(a[0], a[1], b[0], b[1], col); seg(a[0], d[1], b[0], d[1], col); fill([[a[0], a[1]], [b[0], b[1]], [b[0], d[1]], [a[0], d[1]]], col, 0.08); },
    disjoint: (P, col) => { const [a, b, d, e] = P; seg(a[0], a[1], b[0], b[1], col); seg(d[0], d[1], e[0], e[1], col); fill([[a[0], a[1]], [b[0], b[1]], [e[0], e[1]], [d[0], d[1]]], col, 0.08); },
    pitchfork: (P, col) => fork(P, col, 'std'), schiff: (P, col) => fork(P, col, 'schiff'), modschiff: (P, col) => fork(P, col, 'mod'), inside: (P, col) => fork(P, col, 'inside'),
    fibret: (P, col, q) => {
      const [a, b] = q, x0 = Math.min(P[0][0], P[1][0]);
      [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.618].forEach((r, k) => { const pr = b.p - r * (b.p - a.p), y = c.Y(pr); if (y == null) return; seg(x0, y, W(), y, FIB[k % FIB.length], 1, r === 0 || r === 1 ? [] : [3, 3]); tag(r + ' · ' + c.fmtP(pr), x0 + 4, y - 8, FIB[k % FIB.length]); });
      seg(P[0][0], P[0][1], P[1][0], P[1][1], col, 1, [2, 4]);
    },
    fibext: (P, col, q) => {
      const [a, b, d] = q, x0 = P[2][0]; poly(P, col, 1, [2, 4]);
      [0, 0.382, 0.618, 1, 1.272, 1.618, 2.618].forEach((r, k) => { const pr = d.p + r * (b.p - a.p), y = c.Y(pr); if (y == null) return; seg(x0, y, W(), y, FIB[k % FIB.length], 1, [3, 3]); tag(r + ' · ' + c.fmtP(pr), W() - 6, y - 8, FIB[k % FIB.length], 'right'); });
    },
    fibch: (P, col) => {
      const [a, b, d] = P, off = d[1] - (a[1] + (b[1] - a[1]) * (d[0] - a[0]) / ((b[0] - a[0]) || 1));
      [0, 0.618, 1, 1.618, 2.618].forEach((r, k) => { const e = extend(a[0], a[1] + r * off, b[0], b[1] + r * off, false, true); seg(e[0], e[1], e[2], e[3], FIB[k % FIB.length], 1, r ? [3, 3] : []); tag(String(r), e[2] - 6, e[3] - 8, FIB[k % FIB.length], 'right'); });
    },
    fibtime: (P, col, q) => { const u = q[1].i - q[0].i; if (!u) return; [0, 1, 2, 3, 5, 8, 13, 21, 34].forEach((f, k) => { const x = c.X(q[0].i + f * u); if (x == null || x > W()) return; seg(x, 0, x, H(), FIB[k % FIB.length], 1, [3, 3]); tag(String(f), x + 3, 14, FIB[k % FIB.length]); }); },
    fibtt: (P, col, q) => { const u = q[1].i - q[0].i; poly(P, col, 1, [2, 4]); [0, 0.382, 0.5, 0.618, 1, 1.618, 2.618].forEach((r, k) => { const x = c.X(q[2].i + Math.round(r * u)); if (x == null || x > W()) return; seg(x, 0, x, H(), FIB[k % FIB.length], 1, [3, 3]); tag(String(r), x + 3, 14, FIB[k % FIB.length]); }); },
    fibcircle: (P, col) => { const [a, b] = P, r0 = Math.hypot(b[0] - a[0], b[1] - a[1]); [0.382, 0.618, 1, 1.618, 2.618].forEach((r, k) => ring(a[0], a[1], r0 * r, r0 * r, FIB[k % FIB.length], 0, Math.PI * 2)); seg(a[0], a[1], b[0], b[1], col, 1, [2, 4]); },
    fibspiral: (P, col) => {
      const [a, b] = P, r0 = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1, t0 = Math.atan2(b[1] - a[1], b[0] - a[0]), phi = 1.618033988, out = [];
      for (let k = -160; k <= 160; k++) { const t = k / 40 * Math.PI / 2, r = r0 * Math.pow(phi, t / (Math.PI / 2)); if (r > 4000) break; out.push([a[0] + r * Math.cos(t0 + t), a[1] + r * Math.sin(t0 + t)]); }
      poly(out, col, 1.2);
    },
    fibarc: (P, col) => { const [a, b] = P, r0 = Math.hypot(b[0] - a[0], b[1] - a[1]), up = a[1] < b[1]; [0.382, 0.5, 0.618, 1].forEach((r, k) => ring(b[0], b[1], r0 * r, r0 * r, FIB[k % FIB.length], up ? Math.PI : 0, up ? 2 * Math.PI : Math.PI)); seg(a[0], a[1], b[0], b[1], col, 1, [2, 4]); },
    fibwedge: (P, col) => {
      const [a, b, d] = P, rb = Math.hypot(b[0] - a[0], b[1] - a[1]), t1 = Math.atan2(b[1] - a[1], b[0] - a[0]), t2 = Math.atan2(d[1] - a[1], d[0] - a[0]);
      seg(a[0], a[1], b[0], b[1], col); seg(a[0], a[1], a[0] + rb * Math.cos(t2), a[1] + rb * Math.sin(t2), col);
      [0.236, 0.382, 0.5, 0.618, 0.786, 1].forEach((r, k) => ring(a[0], a[1], rb * r, rb * r, FIB[k % FIB.length], Math.min(t1, t2), Math.max(t1, t2)));
    },
    pitchfan: (P, col) => { const [a, b, d] = P; seg(b[0], b[1], d[0], d[1], col, 1, [2, 4]); [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1].forEach((r, k) => { const x = b[0] + r * (d[0] - b[0]), y = b[1] + r * (d[1] - b[1]), e = extend(a[0], a[1], x, y, false, true); seg(e[0], e[1], e[2], e[3], FIB[k % FIB.length], 1); }); },
    gannbox: (P, col) => gann(P, col, false), gannsq: (P, col) => gann(P, col, true),
    gannfix: (P, col) => { const [a, b] = P, s = Math.abs(b[0] - a[0]) || 40, sy = b[1] < a[1] ? -s : s; gann([a, [a[0] + Math.sign(b[0] - a[0] || 1) * s, a[1] + sy]], col, true); },
    gannfan: (P, col) => {
      const [a, b] = P, dx = b[0] - a[0] || 1, dy = b[1] - a[1];
      [[1, 8], [1, 4], [1, 3], [1, 2], [1, 1], [2, 1], [3, 1], [4, 1], [8, 1]].forEach(([m, n], k) => { const e = extend(a[0], a[1], a[0] + dx, a[1] + dy * m / n, false, true); seg(e[0], e[1], e[2], e[3], FIB[k % FIB.length], 1); tag(m + '×' + n, e[2] - 6, e[3] - 6, FIB[k % FIB.length], 'right'); });
    },
    xabcd: (P, col, q) => harmonic(P, col, q, ['X', 'A', 'B', 'C', 'D']), cypher: (P, col, q) => harmonic(P, col, q, ['X', 'A', 'B', 'C', 'D']),
    hs: (P, col) => {
      poly(P, PAT); ['', '左肩', '', '头', '', '右肩', ''].forEach((t, k) => { if (t && P[k]) badge(P[k][0], P[k][1] - 16, t, PAT); });
      if (P[2] && P[4]) { const e = extend(P[2][0], P[2][1], P[4][0], P[4][1], false, true); seg(e[0], e[1], e[2], e[3], '#fb923c', 1.4); tag('颈线', P[4][0] + 6, P[4][1] + 12, '#fb923c'); }
      if (P.length === 7) fill(P, PAT, 0.07);
    },
    abcd: (P, col, q) => { poly(P, PAT); ['A', 'B', 'C', 'D'].forEach((t, k) => P[k] && badge(P[k][0], P[k][1] - 14, t, PAT)); if (q.length === 4) { tag('BC/AB ' + ratio(q[1], q[2], q[0], q[1]), (P[1][0] + P[2][0]) / 2 + 6, (P[1][1] + P[2][1]) / 2, PAT); tag('CD/BC ' + ratio(q[2], q[3], q[1], q[2]), (P[2][0] + P[3][0]) / 2 + 6, (P[2][1] + P[3][1]) / 2, PAT); } },
    tripat: (P, col) => { poly(P, PAT); ['A', 'B', 'C', 'D'].forEach((t, k) => P[k] && badge(P[k][0], P[k][1] - 14, t, PAT)); if (P.length === 4) { const u = extend(P[0][0], P[0][1], P[2][0], P[2][1], false, true), l = extend(P[1][0], P[1][1], P[3][0], P[3][1], false, true); seg(u[0], u[1], u[2], u[3], '#fde047', 1.2, [5, 4]); seg(l[0], l[1], l[2], l[3], '#fde047', 1.2, [5, 4]); fill(P, PAT, 0.07); } },
    drives: (P, col, q) => { poly(P, PAT); [1, 3, 5].forEach((k, n) => P[k] && badge(P[k][0], P[k][1] - 16, '驱' + (n + 1), PAT)); if (q.length === 7) [[1, 2, 3], [3, 4, 5]].forEach(([x, y, z]) => tag(ratio(q[y], q[z], q[x], q[y]), P[z][0] + 8, P[z][1] + 12, PAT)); },
    ew5: (P) => waves(P, ['0', '(1)', '(2)', '(3)', '(4)', '(5)']), ewabc: (P) => waves(P, ['0', '(A)', '(B)', '(C)']), ewtri: (P) => waves(P, ['0', '(A)', '(B)', '(C)', '(D)', '(E)']),
    ewwxy: (P) => waves(P, ['0', '(W)', '(X)', '(Y)']), ewwxyxz: (P) => waves(P, ['0', '(W)', '(X)', '(Y)', '(X)', '(Z)']),
    cycle: (P, col, q) => { const u = q[1].i - q[0].i; if (!u) return; for (let k = 0; k < 60; k++) { const x = c.X(q[0].i + k * u); if (x == null || x > W()) break; seg(x, 0, x, H(), col, 1, [3, 3]); } },
    tcycle: (P, col, q) => { const u = q[1].i - q[0].i; if (!u) return; for (let k = 0; k < 40; k++) { const xa = c.X(q[0].i + k * u), xb = c.X(q[0].i + (k + 1) * u); if (xa == null || xb == null || xa > W()) break; ring((xa + xb) / 2, P[0][1], Math.abs(xb - xa) / 2, Math.abs(xb - xa) / 2.5, col, Math.PI, 2 * Math.PI); } },
    sine: (P, col) => { const [a, b] = P, half = b[0] - a[0] || 1, amp = (b[1] - a[1]) / 2, mid = (a[1] + b[1]) / 2, out = []; for (let x = Math.min(a[0], 0); x <= W(); x += 3) out.push([x, mid - amp * Math.cos(Math.PI * (x - a[0]) / half)]); poly(out, col, 1.2); },
    long: (P, col, q) => position(P, q, 1), short: (P, col, q) => position(P, q, -1),
    forecast: (P, col, q) => { const [a, b] = P; seg(a[0], a[1], b[0], b[1], col, 1.6); arrowHead(a, b, col); fill([[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]], b[1] < a[1] ? '#22c55e' : '#ef4444', 0.08); tag(pctTxt(q[0].p, q[1].p) + ' · ' + bars(q[0], q[1]) + ' 根后', b[0] + 8, b[1] - 10, col); },
    bars: (P, col, q) => {
      const b = B(), lo = Math.max(0, Math.min(q[0].i, q[1].i)), hi = Math.min(S().asof, Math.max(q[0].i, q[1].i)); if (!q[2]) { boxRange(P, col); return; }
      const shift = q[2].i - lo, dp = q[2].p - b.o[lo], w = Math.max(1, (c.X(1) - c.X(0)) * 0.6);
      for (let i = lo; i <= hi; i++) { const x = c.X(i + shift); if (x == null) continue; const yo = c.Y(b.o[i] + dp), yc = c.Y(b.c[i] + dp), yh = c.Y(b.h[i] + dp), yl = c.Y(b.l[i] + dp); if ([yo, yc, yh, yl].some(v => v == null)) continue;
        const cl = b.c[i] >= b.o[i] ? '#f0484e' : '#1fa391'; seg(x, yh, x, yl, c.rgba(cl, 0.6), 1); G2.fillStyle = c.rgba(cl, 0.45); G2.fillRect(x - w / 2, Math.min(yo, yc), w, Math.max(1, Math.abs(yc - yo))); }
    },
    ghost: (P, col, q) => {
      const [a, b] = q, n = Math.max(2, Math.abs(b.i - a.i)), dir = b.i >= a.i ? 1 : -1, w = Math.max(1, (c.X(1) - c.X(0)) * 0.6), step = (b.p - a.p) / n, wig = Math.abs(step) * 1.5 + Math.abs(a.p) * 0.004;
      for (let k = 0; k < n; k++) { const o = a.p + step * k, cl = o + step + (k % 3 === 1 ? -0.6 : 0.4) * Math.abs(step), x = c.X(a.i + dir * (k + 1)); if (x == null) continue;
        const yo = c.Y(o), yc = c.Y(cl), yh = c.Y(Math.max(o, cl) + wig * 0.5), yl = c.Y(Math.min(o, cl) - wig * 0.5); if ([yo, yc, yh, yl].some(v => v == null)) continue;
        const cc = cl >= o ? '#f0484e' : '#1fa391'; seg(x, yh, x, yl, c.rgba(cc, 0.5), 1); G2.fillStyle = c.rgba(cc, 0.35); G2.fillRect(x - w / 2, Math.min(yo, yc), w, Math.max(1, Math.abs(yc - yo))); }
      tag('模拟K线（不是数据）', P[1][0] + 8, P[1][1] - 10, col);
    },
    sector: (P, col) => { const [a, b, d] = P, r = Math.hypot(b[0] - a[0], b[1] - a[1]), t1 = Math.atan2(b[1] - a[1], b[0] - a[0]), t2 = d ? Math.atan2(d[1] - a[1], d[0] - a[0]) : t1 + 0.6, out = [[a[0], a[1]]];
      for (let k = 0; k <= 32; k++) { const t = t1 + (t2 - t1) * k / 32; out.push([a[0] + r * Math.cos(t), a[1] + r * Math.sin(t)]); } fill(out, col, 0.12); poly(out.concat([[a[0], a[1]]]), col, 1.2); },
    vp: (P, col, q) => profile(q[0].i, q[1].i, P, col), avp: (P, col, q) => profile(q[0].i, S().asof, P, col),
    prange: (P, col, q) => { const [a, b] = P; fill([[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]], col, 0.1); seg((a[0] + b[0]) / 2, a[1], (a[0] + b[0]) / 2, b[1], col, 1.4); arrowHead([(a[0] + b[0]) / 2, a[1]], [(a[0] + b[0]) / 2, b[1]], col);
      tag((q[1].p - q[0].p >= 0 ? '+' : '') + c.fmtP(q[1].p - q[0].p) + '（' + pctTxt(q[0].p, q[1].p) + '）', (a[0] + b[0]) / 2, b[1] + (b[1] < a[1] ? -12 : 14), col, 'center'); },
    drange: (P, col, q) => { const [a, b] = P; fill([[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]], col, 0.1); seg(a[0], (a[1] + b[1]) / 2, b[0], (a[1] + b[1]) / 2, col, 1.4); arrowHead([a[0], (a[1] + b[1]) / 2], [b[0], (a[1] + b[1]) / 2], col);
      tag(bars(q[0], q[1]) + ' 根' + days(q[0], q[1]), (a[0] + b[0]) / 2, Math.max(a[1], b[1]) + 14, col, 'center'); },
    dprange: (P, col, q) => { R.prange(P, col, q); const [a, b] = P; tag(bars(q[0], q[1]) + ' 根' + days(q[0], q[1]), (a[0] + b[0]) / 2, Math.max(a[1], b[1]) + 28, col, 'center'); },
    brush: (P, col) => poly(P, col, 2),
    text: (P, col, q, d) => { const [a] = P; G2.font = '600 13px -apple-system,"PingFang SC",sans-serif'; G2.fillStyle = col === SEL ? SEL : '#fde047'; G2.textAlign = 'left'; G2.textBaseline = 'middle'; G2.fillText(d.text || '', a[0], a[1]); const w = G2.measureText(d.text || '').width; if (K >= 0) (hits[K] = hits[K] || []).push([a[0], a[1], a[0] + w, a[1]]); },
    emoji: (P, col, q, d) => { const [a] = P; G2.font = '22px "Apple Color Emoji",sans-serif'; G2.textAlign = 'center'; G2.textBaseline = 'middle'; G2.fillText(d.emoji || '👍', a[0], a[1]); if (col === SEL) ring(a[0], a[1], 15, 15, SEL, 0, Math.PI * 2); if (K >= 0) (hits[K] = hits[K] || []).push([a[0], a[1], a[0], a[1]]); },
  };
  function angleOf(P) { const [a, b] = P; return (-Math.atan2(b[1] - a[1], b[0] - a[0]) * 180 / Math.PI).toFixed(1); }
  function ratio(p1, p2, p3, p4) { const d1 = Math.abs(p2.p - p1.p), d2 = Math.abs(p4.p - p3.p); return d2 ? (d1 / d2).toFixed(3) : '—'; }
  function days(a, b) { if (!a.d || !b.d) return ''; return ' · ' + Math.round(Math.abs(new Date(b.d) - new Date(a.d)) / 864e5) + ' 天'; }
  function arrowHead(a, b, col) { const t = Math.atan2(b[1] - a[1], b[0] - a[0]), g = G2; g.beginPath(); g.moveTo(b[0], b[1]); g.lineTo(b[0] - 9 * Math.cos(t - 0.4), b[1] - 9 * Math.sin(t - 0.4)); g.lineTo(b[0] - 9 * Math.cos(t + 0.4), b[1] - 9 * Math.sin(t + 0.4)); g.closePath(); g.fillStyle = col; g.fill(); }
  function boxRange(P, col) { const [a, b] = P; if (!b) return; fill([[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]], col, 0.08); poly([[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]], col, 1, [4, 3], true); }
  function fork(P, col, kind) {
    const [a, b, d] = P; if (!d) return seg(a[0], a[1], b[0], b[1], col);
    let o = a; if (kind === 'schiff') o = [a[0], (a[1] + b[1]) / 2]; else if (kind === 'mod') o = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const m = [(b[0] + d[0]) / 2, (b[1] + d[1]) / 2], dx = m[0] - o[0], dy = m[1] - o[1];
    if (kind === 'inside') { const e = extend(m[0], m[1], m[0] + dx, m[1] + dy, false, true); seg(e[0], e[1], e[2], e[3], col); }
    else { const e = extend(o[0], o[1], m[0], m[1], false, true); seg(e[0], e[1], e[2], e[3], col); }
    [b, d].forEach(p => { const e = extend(p[0], p[1], p[0] + dx, p[1] + dy, false, true); seg(e[0], e[1], e[2], e[3], col, 1.2); });
    seg(b[0], b[1], d[0], d[1], col, 1, [3, 3]); seg(a[0], a[1], o[0], o[1], col, 1, [2, 3]);
  }
  function gann(P, col, diag) {
    const [a, b] = P; if (!b) return; const x0 = Math.min(a[0], b[0]), x1 = Math.max(a[0], b[0]), y0 = Math.min(a[1], b[1]), y1 = Math.max(a[1], b[1]);
    poly([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], col, 1.2, [], true);
    [0.25, 0.382, 0.5, 0.618, 0.75].forEach((r, k) => { const x = x0 + r * (x1 - x0), y = y0 + r * (y1 - y0); seg(x, y0, x, y1, FIB[k + 1], 1, [3, 3]); seg(x0, y, x1, y, FIB[k + 1], 1, [3, 3]); });
    if (diag) { seg(x0, y0, x1, y1, col, 1); seg(x0, y1, x1, y0, col, 1); ring((x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2, col, 0, Math.PI * 2, [2, 3]); }
  }
  function harmonic(P, col, q, names) {
    poly(P, PAT); names.forEach((t, k) => P[k] && badge(P[k][0], P[k][1] + (k % 2 ? -14 : 14), t, PAT));
    if (P.length >= 3) fill([P[0], P[1], P[2]], PAT, 0.1);
    if (P.length === 5) { fill([P[2], P[3], P[4]], PAT, 0.1); seg(P[0][0], P[0][1], P[2][0], P[2][1], PAT, 1, [3, 3]); seg(P[2][0], P[2][1], P[4][0], P[4][1], PAT, 1, [3, 3]);
      tag('AB/XA ' + ratio(q[1], q[2], q[0], q[1]), (P[1][0] + P[2][0]) / 2, (P[1][1] + P[2][1]) / 2, PAT, 'center'); tag('AD/XA ' + ratio(q[1], q[4], q[0], q[1]), (P[3][0] + P[4][0]) / 2, (P[3][1] + P[4][1]) / 2 + 12, PAT, 'center'); }
  }
  function waves(P, names) { poly(P, '#93c5fd'); names.forEach((t, k) => { if (!P[k] || !k) return; const up = !P[k + 1] ? P[k][1] < P[k - 1][1] : P[k][1] < P[k + 1][1]; tag(t, P[k][0], P[k][1] + (up ? -12 : 14), '#93c5fd', 'center'); }); }
  function position(P, q, sgn) {
    const [a, b] = P, e = q[0].p, st = q[1].p, risk = (e - st) * sgn;
    const stop = risk > 0 ? st : e - sgn * Math.abs(e - st || e * 0.02), tgt = e + sgn * 2 * Math.abs(e - stop), ye = c.Y(e), ys = c.Y(stop), yt = c.Y(tgt);
    if ([ye, ys, yt].some(v => v == null)) return;
    const x1 = Math.max(b[0], a[0] + 120);
    fill([[a[0], ye], [x1, ye], [x1, yt], [a[0], yt]], '#22c55e', 0.16); fill([[a[0], ye], [x1, ye], [x1, ys], [a[0], ys]], '#ef4444', 0.16);
    seg(a[0], ye, x1, ye, '#e6e8ee', 1.2);
    tag('目标 ' + c.fmtP(tgt) + '（' + pctTxt(e, tgt) + '）', a[0] + 4, yt + (sgn > 0 ? 12 : -10), '#4ade80'); tag('止损 ' + c.fmtP(stop) + '（' + pctTxt(e, stop) + '）', a[0] + 4, ys + (sgn > 0 ? -10 : 12), '#f87171');
    tag((sgn > 0 ? '多头仓位' : '空头仓位') + ' · 进场 ' + c.fmtP(e) + ' · 盈亏比 2.00（只是画框，不会下单）', a[0] + 4, ye - 8, '#e6e8ee');
  }
  function profile(i0, i1, P, col) {
    const b = B(), lo = Math.max(0, Math.min(i0, i1)), hi = Math.min(S().asof, Math.max(i0, i1)); if (hi <= lo) return;
    let pl = Infinity, ph = -Infinity; for (let i = lo; i <= hi; i++) { pl = Math.min(pl, b.l[i]); ph = Math.max(ph, b.h[i]); }
    const N = 24, step = (ph - pl) / N || 1, vol = new Array(N).fill(0);
    for (let i = lo; i <= hi; i++) { const a = b.l[i], z = b.h[i], v = b.v[i]; if (z <= a) { vol[Math.min(N - 1, Math.floor((a - pl) / step))] += v; continue; }
      for (let k = Math.floor((a - pl) / step); k <= Math.min(N - 1, Math.floor((z - pl) / step)); k++) { const s = Math.min(z, pl + (k + 1) * step) - Math.max(a, pl + k * step); if (s > 0) vol[k] += v * s / (z - a); } }
    const mx = Math.max.apply(null, vol) || 1, poc = vol.indexOf(mx), xa = c.X(lo), xb = c.X(hi); if (xa == null || xb == null) return;
    const span = Math.max(40, (xb - xa) * 0.6);
    vol.forEach((v, k) => { const ya = c.Y(pl + k * step), yb = c.Y(pl + (k + 1) * step); if (ya == null || yb == null) return; G2.fillStyle = c.rgba(k === poc ? '#f5a524' : col, k === poc ? 0.55 : 0.28); G2.fillRect(xa, Math.min(ya, yb), span * v / mx, Math.max(1, Math.abs(yb - ya) - 1)); });
    const yp = c.Y(pl + (poc + 0.5) * step); if (yp != null) { seg(xa, yp, xb, yp, '#f5a524', 1, [4, 3]); tag('量山（成交最密）' + c.fmtP(pl + (poc + 0.5) * step), xa + span + 6, yp, '#f5a524'); }
    poly([[xa, 0], [xa, H()]], c.rgba(col, 0.35), 1, [2, 4]); if (i1 !== S().asof) poly([[xb, 0], [xb, H()]], c.rgba(col, 0.35), 1, [2, 4]);
  }

  // ---------- 对外：画一条、预览、点击、命中 ----------
  function render(d, k, sel) {
    const P = (d.pts || []).map(XY); if (P.some(p => !p) && d.type !== 'brush') return;
    G2 = c.g(); K = k; hits[k] = [];
    const f = R[d.type]; if (f) f(P.filter(Boolean), sel ? SEL : (d.color || COL), d.pts, d);
    K = -1;
  }
  function preview() {
    const S0 = S(), t = S0.tool, cur = S0.cur; if (!has(t) || !cur || cur.p == null) return;
    G2 = c.g(); K = -1; G2.globalAlpha = 0.85;
    if (t === 'brush') { if (stroke) R.brush(stroke.map(XY).filter(Boolean), COL); G2.globalAlpha = 1; return; }
    const pts = ((S0.pending && S0.pending.pts) || []).concat([pick(cur)]);
    const P = pts.map(XY);
    if (P.every(Boolean)) {
      if (t === 'zoom') boxRange(P, '#fde047');
      else if (t === 'ruler') { if (P.length === 2) R.dprange(P, '#fde047', pts); }
      else if (t === 'emoji') R.emoji(P, COL, pts, { emoji });
      else if (t === 'text') dot(P[0][0], P[0][1], '#fde047');
      else if (R[t]) R[t](P, COL, pts, {});
    }
    G2.globalAlpha = 1;
  }
  function click(pt) {
    const S0 = S(), t = S0.tool, tool = TOOLS[t], q = pick(pt);
    if (t === 'brush') return;
    const pts = ((S0.pending && S0.pending.pts) || []).concat([q]);
    if (t === 'text') { S0.pending = { pts, textFor: 'text' }; c.askText(pt); return; }
    if (pts.length < tool.n) { S0.pending = { pts }; c.updateHint(); c.redraw(); return; }
    if (t === 'zoom') { const lo = Math.min(pts[0].i, pts[1].i), hi = Math.max(pts[0].i, pts[1].i); if (hi - lo >= 3) c.zoomTo(lo, hi); c.setTool('cursor'); return; }
    if (t === 'ruler') { ruler = pts; c.setTool('cursor'); c.redraw(); return; }
    const d = { type: t, pts };
    if (t === 'emoji') d.emoji = emoji;
    c.addDrawing(d);
  }
  function finishText(v) { const S0 = S(); if (S0.pending && S0.pending.textFor === 'text' && v) c.addDrawing({ type: 'text', pts: S0.pending.pts, text: v }); }
  function hit(k, x, y) {
    return (hits[k] || []).some(([x0, y0, x1, y1]) => {
      const dx = x1 - x0, dy = y1 - y0, l2 = dx * dx + dy * dy, t = l2 ? Math.max(0, Math.min(1, ((x - x0) * dx + (y - y0) * dy) / l2)) : 0;
      return Math.hypot(x - (x0 + t * dx), y - (y0 + t * dy)) < 8;
    });
  }
  function hint() {
    const S0 = S(), t = TOOLS[S0.tool]; if (!t) return '';
    const n = ((S0.pending && S0.pending.pts) || []).length;
    if (S0.tool === 'brush') return '画笔：按住鼠标拖动来画，松开就画好';
    if (S0.tool === 'zoom') return '放大：' + (n ? '再点一下框的另一角' : '先点要放大那一段的一头');
    if (S0.tool === 'ruler') return '尺子：' + (n ? '再点终点，量出涨跌、根数和天数' : '先点起点');
    if (S0.tool === 'text') return '文字：点一下要写字的位置';
    if (S0.tool === 'emoji') return '表情：点一下要放 ' + emoji + ' 的位置';
    return t.name + '：' + (n ? '再点第 ' + (n + 1) + ' 个点（共 ' + t.n + ' 个）' : ORDER(t.n));
  }
  function drawRuler() {
    if (!ruler) return; const P = ruler.map(XY); if (!P.every(Boolean)) return;
    G2 = c.g(); K = -1; R.dprange(P, '#fde047', ruler);
  }

  // ---------- 鼠标（画笔要按住拖动）和快捷键 ----------
  function bindMouse() {
    const ov = $('#overlay');
    ov.addEventListener('mousedown', e => { if (S().tool !== 'brush') return; const pt = c.ptFromEvent(e); stroke = [{ i: pt.li, p: pt.p, d: B().d[pt.li] || null }]; });
    ov.addEventListener('mousemove', e => { if (!stroke) return; const pt = c.ptFromEvent(e), last = stroke[stroke.length - 1]; if (pt.li !== last.i || Math.abs(c.Y(pt.p) - c.Y(last.p)) > 3) stroke.push({ i: pt.li, p: pt.p, d: B().d[pt.li] || null }); c.redraw(); });
    window.addEventListener('mouseup', () => { if (!stroke) return; const s = stroke; stroke = null; if (s.length > 1) c.addDrawing({ type: 'brush', pts: s }); else c.redraw(); });
    ov.addEventListener('click', () => { if (ruler && S().tool === 'cursor') { ruler = null; c.redraw(); } });
    document.addEventListener('keydown', e => {
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
      if (e.key === 'Escape') { closeMenus(); if (ruler) { ruler = null; c.redraw(); } }
      if (!e.altKey) return;
      const k = { KeyT: 'trend', KeyH: 'hline', KeyJ: 'hray', KeyV: 'vline', KeyC: 'cross', KeyF: 'fibret' }[e.code];
      if (k) { e.preventDefault(); c.setTool(k); }
    });
    document.addEventListener('click', e => { if (!e.target.closest('#tools')) closeMenus(); });
  }

  function init(ctx) {
    c = ctx;
    c.S.dt = Object.assign({ magnet: false, lock: false, hide: false, sync: false }, c.store.get('dt', {}));
    build();
    $('#tools').addEventListener('click', onBar);
    $('#chartwrap').addEventListener('click', e => { const b = e.target.closest('#favBar [data-tool]'); if (b) c.setTool(b.dataset.tool === c.S.tool ? 'cursor' : b.dataset.tool); });
    bindMouse();
  }
  const visible = d => !d.pts || !d.pts.length || d.pts[0].i <= S().asof || ['hline', 'hray', 'cross'].indexOf(d.type) >= 0;
  return { init, has, click, preview, render, hit, hint, sync, finishText, drawRuler, visible, tools: TOOLS, groups: G, toggles };
})();
