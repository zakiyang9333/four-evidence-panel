/* 界面自检。只在地址带 ?selftest=1 时加载，由 tests/test_panel.py 用无头 Chrome 运行。
   它像用户一样点按钮、拖回放、画线，把结果写进 <pre id="selftest">。不改任何数据文件。 */
(async () => {
  const fe = window.__fe, S = fe.S, $ = s => document.querySelector(s);
  const out = { checks: {}, info: {} };
  const ok = (name, cond, detail) => { out.checks[name] = !!cond; if (!cond) out.info[name] = detail === undefined ? null : detail; };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  async function until(fn, ms = 6000) { const t0 = Date.now(); while (Date.now() - t0 < ms) { try { if (fn()) return true; } catch (e) { /* 再等 */ } await sleep(40); } return false; }
  const fresh = () => S.state && S.state.ticker === S.ticker && S.state.index === S.asof;
  const frame = async () => { await sleep(60); fe.tick(); await sleep(20); fe.tick(); };   // 无头模式下动画帧不一定跑，直接驱动一次重画
  const ov = $('#overlay'), ch = fe.chart(), candle = ch.panes()[0].getSeries()[0];
  const evt = (i, p) => { const r = ov.getBoundingClientRect(); return { clientX: r.left + ch.timeScale().logicalToCoordinate(i), clientY: r.top + candle.priceToCoordinate(p), bubbles: true }; };
  const click = (i, p) => { ov.dispatchEvent(new MouseEvent('mousemove', evt(i, p))); ov.dispatchEvent(new MouseEvent('click', evt(i, p))); };
  const alphaAt = (i, p) => { const d = window.devicePixelRatio || 1, x = Math.round(ch.timeScale().logicalToCoordinate(i) * d), y = Math.round(candle.priceToCoordinate(p) * d); const px = ov.getContext('2d').getImageData(x - 12, y - 1, 25, 3).data; let m = 0; for (let k = 3; k < px.length; k += 4) m = Math.max(m, px[k]); return m; };   // 虚线有空隙，取一小块里最不透明的点
  async function pick(t) { [...document.querySelectorAll('#tickers button')].find(b => b.textContent.indexOf(t) === 0).click(); await until(() => S.ticker === t && S.bars && S.bars.ticker === t && fresh()); await frame(); }
  async function replayTo(date) { if (!S.replayOn) $('#replayBtn').click(); const d = $('#rpDate'); d.value = date; d.dispatchEvent(new Event('change', { bubbles: true })); await until(() => S.bars.d[S.asof] === date && fresh()); await frame(); }
  const lit = () => document.querySelectorAll('#evidence li.on').length;
  const snapshot = () => ({ asof: S.state.asof, title: S.state.conclusion.title, lit: S.state.lit, on: lit(), score: $('#evidence .ev-score').textContent, side: $('#sigCard h3').textContent, ok: S.state.evidence.map(e => e.ok) });

  try {
    await until(() => S.bars && fresh()); await frame();
    try { localStorage.clear(); } catch (e) { /* 忽略 */ }

    // 固定提示：常驻，不能关
    ok('banner_text', $('#banner').textContent.trim() === '四证：回测证据不足 ｜ 后手战法、破位反抽：尚未回测 ｜ 仅观察，不构成买卖依据', $('#banner').textContent);
    ok('banner_not_closable', !$('#banner button') && !$('#banner [role=button]') && getComputedStyle($('#banner')).display !== 'none');

    // 三只标的都能切换；2026-11-13 的状态
    for (const t of ['SPCX', 'NVDA', 'QQQ']) { await pick(t); await replayTo('2026-11-13'); out.info['s_' + t] = snapshot(); }
    const a = out.info;
    ok('spcx_1113_2of4', a.s_SPCX.lit === 2 && a.s_SPCX.on === 2 && a.s_SPCX.ok.join() === 'false,true,true,false' && /证据 2\/4/.test(a.s_SPCX.score), a.s_SPCX);
    ok('nvda_1113_0of4', a.s_NVDA.lit === 0 && a.s_NVDA.on === 0 && a.s_NVDA.title === '还缺 4 项' && /证据 0\/4/.test(a.s_NVDA.score), a.s_NVDA);
    ok('qqq_1113_not_armed', a.s_QQQ.title === '未触发' && a.s_QQQ.on === 0 && /未触发/.test(a.s_QQQ.score) && /15%/.test(S.state.conclusion.text), a.s_QQQ);

    // 回放：历史信号日
    await replayTo('2009-03-18'); out.info.qqq_2009 = snapshot();
    ok('qqq_20090318_all4', out.info.qqq_2009.title === '四项齐了' && out.info.qqq_2009.on === 4 && out.info.qqq_2009.side === '可以入场（仅观察）', out.info.qqq_2009);
    ok('replay_truncates_chart', candle.data().length === S.asof + 1 && candle.data()[candle.data().length - 1].time === '2009-03-18', candle.data().length);
    ok('replay_bar_visible', !$('#replaybar').hidden && /2009-03-18/.test($('#rpInfo').textContent));
    await pick('NVDA'); await replayTo('2025-05-13'); out.info.nvda_2025 = snapshot();
    ok('nvda_20250513_all4', out.info.nvda_2025.title === '四项齐了' && out.info.nvda_2025.on === 4, out.info.nvda_2025);
    ok('marks_1_to_4', S.state.marks.map(m => m.n).join() === '1,2,3,4', S.state.marks);

    // 自动画：画在图上的就是引擎给的数
    const st = S.state, dr = st.draw;
    ok('auto_numbers_from_state', dr.fan.levels['0.5'].at_asof === st.levels.fan05 && dr.stop === st.levels.stop && dr.avwap.values[dr.avwap.values.length - 1] === st.levels.avwap,
      [dr.fan.levels['0.5'].at_asof, st.levels.fan05, dr.stop, st.levels.stop]);
    const pxOn = [alphaAt(S.asof - 2, dr.fan.H + (dr.fan.levels['0.5'].at_lo - dr.fan.H) * (S.asof - 2 - dr.fan.hi) / (dr.fan.lo - dr.fan.hi)), alphaAt(S.asof - 1, dr.stop), alphaAt(dr.avwap.anchor + 2, dr.avwap.values[2])];
    ok('auto_layer_drawn', pxOn.every(v => v > 0), pxOn);
    const marksBox = document.querySelector('[data-ind=marks]'); marksBox.click();
    $('#autoBtn').click(); await frame();
    const pxOff = [alphaAt(S.asof - 1, dr.stop), alphaAt(dr.avwap.anchor + 2, dr.avwap.values[2])];
    ok('auto_toggle_off_clears', pxOff.every(v => v === 0) && !$('#autoBtn').classList.contains('on'), pxOff);
    $('#autoBtn').click(); marksBox.click(); await frame();
    ok('auto_toggle_on_again', alphaAt(S.asof - 1, dr.stop) > 0 && $('#autoBtn').classList.contains('on'));

    // 手动画线
    const b = S.bars, hi = dr.fan.hi, lo = dr.fan.lo;
    $('[data-tool=fan]').click(); const h1 = $('#hint').textContent; click(hi, b.h[hi]); const h2 = $('#hint').textContent; click(lo, b.l[lo]);
    const f = S.drawings[0];
    ok('tool_fan', f && f.type === 'fan' && f.a.i === hi && f.b.i === lo && f.a.p === b.h[hi] && f.b.p === b.l[lo] && S.tool === 'cursor' && /高点/.test(h1) && /低点/.test(h2), f);
    $('[data-tool=hline]').click(); click(S.asof - 30, 120);
    ok('tool_hline', S.drawings[1] && S.drawings[1].type === 'hline' && Math.abs(S.drawings[1].p - 120) < 0.5, S.drawings[1]);
    $('[data-tool=avwap]').click(); click(dr.avwap.anchor, b.l[dr.avwap.anchor]); await frame();
    const key = S.ticker + '|' + b.d[dr.avwap.anchor] + '|' + b.d[S.asof];
    await until(() => S.avwap[key] && S.avwap[key] !== 'loading'); await frame();
    const mv = S.avwap[key] && S.avwap[key].values;
    ok('tool_avwap_same_as_cost_line', S.drawings[2] && S.drawings[2].type === 'avwap' && mv && mv.length === dr.avwap.values.length && mv[mv.length - 1] === st.levels.avwap, [mv && mv.slice(-1), st.levels.avwap]);
    $('[data-tool=arrow]').click(); click(S.asof - 40, 150); click(S.asof - 25, 135);
    const boxShown = !$('#textBox').hidden; $('#textInput').value = '测试标注';
    $('#textBox').dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    ok('tool_arrow_text', boxShown && S.drawings[3] && S.drawings[3].type === 'arrow' && S.drawings[3].text === '测试标注', S.drawings[3]);
    let saved = []; try { saved = JSON.parse(localStorage.getItem('fe.draw.NVDA') || '[]'); } catch (e) { /* 忽略 */ }
    ok('drawings_saved', saved.length === 4, saved.length);
    $('#delBtn').click();
    ok('delete_selected', S.drawings.length === 3 && S.drawings.every(d => d.type !== 'arrow'), S.drawings.map(d => d.type));
    $('[data-tool=fan]').click(); document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    ok('esc_cancels_tool', S.tool === 'cursor' && $('#hint').hidden);
    $('#clearBtn').click();
    ok('clear_all', S.drawings.length === 0);

    // 指标开关
    const panes0 = ch.panes().length; const macd = document.querySelector('[data-ind=macd]'); macd.click(); await frame();
    const panes1 = ch.panes().length; macd.click(); await frame();
    ok('indicator_toggle', panes0 === 3 && panes1 === 2 && ch.panes().length === 3, [panes0, panes1, ch.panes().length]);
    ok('legend_ohlc', ['开', '高', '低', '收'].every(k => $('#legend').textContent.indexOf(k) >= 0) && /MA5/.test($('#legVol').textContent) && /DIF/.test($('#legMacd').textContent), $('#legend').textContent);
    ok('lowvol_bars_marked', S.bars.lowvol.length > 0);

    // 侧栏：可收起；没有密钥时按钮置灰并提示（有密钥时只记录状态）
    const side = $('#side'); if (side.classList.contains('closed')) $('#aiBtn').click();
    ok('side_open', !side.classList.contains('closed'));
    ok('side_tiles', ['现价', '建仓区', '止损', '第一目标', '盈亏比'].every(k => $('#tiles').textContent.indexOf(k) >= 0), $('#tiles').textContent);
    // 视频式解说：模板版不需要密钥。四问依次出现，证据条同步亮灯，最后出大字结论和“下一根看什么”
    const N = window.FENarrate;
    ok('rule_card_from_engine', $('#sigVerdict').textContent === S.state.card.verdict && /证据不足（\d+ 笔，p=0\.\d+）/.test($('#sigFoot').textContent) && document.querySelectorAll('#sigCard .big3 div').length === 3, $('#sigCard').textContent);
    ok('narr_button_free', !$('#aiRun').disabled && $('#narr').hidden);
    $('#aiRun').click();
    await until(() => N.current() && N.shown() >= 1 && N.shown() < 4 && S.reveal, 5000);
    const midShown = document.querySelectorAll('#narr .n-step.show').length, midScore = $('#evidence .ev-score').textContent, midWait = document.querySelectorAll('#evidence li.wait').length;
    ok('narr_steps_appear_one_by_one', midShown >= 1 && midShown < 4 && midWait === 4 - midShown && /解说中/.test(midScore) && !$('#aiSkip').hidden, [midShown, midWait, midScore]);
    await until(() => $('#narr .n-final.show'), 8000);
    const nar = N.current(), steps = [...document.querySelectorAll('#narr .n-step.show')];
    out.info.narr = { source: nar.source, hook: $('#narr .n-hook').textContent, final: $('#narr .n-final').textContent, stickers: steps.map(li => li.querySelector('.sticker').textContent), on: steps.filter(li => li.classList.contains('on')).length };
    ok('narr_four_questions', steps.length === 4 && nar.source === 'template' && out.info.narr.hook.length > 0 && steps.every(li => li.querySelector('.say').textContent && li.querySelector('.look').textContent) &&
      ['第一问 量', '第二问 MACD', '第三问 扇子', '第四问 成本线'].every((q, k) => steps[k].querySelector('.q').textContent === q), out.info.narr);
    ok('narr_matches_engine', out.info.narr.on === S.state.lit && nar.narration.steps.every((s, k) => s.ok === S.state.evidence[k].lit) && /4\/4/.test(out.info.narr.final), out.info.narr);
    ok('narr_evidence_strip_synced_after', lit() === S.state.lit && !document.querySelector('#evidence li.wait') && $('#aiSkip').hidden);
    ok('narr_watch_and_meta', $('#narrWatch').hidden === (nar.narration.watch.length === 0) && /模板版/.test($('#narrMeta').textContent) && $('#narrNotice').hidden);
    steps[2].click(); const fl2 = S.flash && S.flash.k; steps[0].click(); await sleep(60);
    ok('narr_click_highlights_chart', fl2 === 2 && S.flash && S.flash.k === 0 && !!document.querySelector('.pane-flash') && steps[0].classList.contains('picked'), [fl2, S.flash]);
    steps[0].click();
    ok('narr_click_again_clears', !S.flash && !steps[0].classList.contains('picked'));
    // 自由分析的卡片（不对应四要素）：按文字里提到的日期和价位在图上标出来
    const bb = S.bars, i1 = S.asof - 6, i2 = S.asof - 15, lvl = Math.round((bb.h[S.asof] + 7.77) * 100) / 100;
    N.show({ ok: true, source: 'claude', ticker: S.ticker, asof: bb.d[S.asof], model: 'selftest', polish: nar.polish, narration: { hook: '自检', story: '自检',
      steps: [{ q: '自己选的角度', say: '这里有个坑', look: bb.d[i1].slice(5) + ' 最低 ' + bb.l[i1] + '，' + bb.d[i2].slice(5) + ' 那天放量 3.5 亿股，上方压力 ' + lvl + '，涨了 16%', sticker: '有承接', tone: 'good', evidence: 0, ok: null },
        { q: '没有数字的一步', say: '就是感觉', look: '整体偏弱', sticker: '', tone: 'neutral', evidence: 0, ok: null },
        { q: '新格式', say: '高点在下台阶', sticker: '下台阶', tone: 'bad', evidence: 0, ok: null, draw: [
          { type: 'path', points: [{ date: bb.d[i2], price: bb.h[i2] }, { date: bb.d[i1], price: bb.h[i1] }], label: '下台阶' },
          { type: 'point', date: bb.d[i1], price: bb.l[i1], label: '坑' },
          { type: 'level', price: lvl, label: '压力' },
          { type: 'zone', date_from: bb.d[i2], date_to: bb.d[i1], top: bb.h[i2], bottom: bb.l[i1], label: '平台' },
          { type: 'volume', dates: [bb.d[i2]], label: '放量' },
          { type: 'point', date: '2099-01-01', price: 1, label: '不存在' }] }], final: '还不抄', watch: [] } }, false);
    await frame();
    const fs = [...document.querySelectorAll('#narr .n-step.show')]; fs[0].click(); await frame();
    const ff = S.flash && S.flash.free;
    out.info.free = ff && { rings: ff.rings, boxes: ff.boxes, levels: ff.levels, vol: ff.vol };
    ok('free_card_marks_dates_and_prices', ff && ff.rings.length === 1 && ff.rings[0].i === i1 && ff.rings[0].p === bb.l[i1] && ff.boxes.join() === String(i2) && ff.levels.join() === String(lvl) && ff.vol === true, out.info.free);
    ok('free_card_drawn_on_chart', alphaAt(i1, bb.l[i1] ) > 0 && alphaAt(S.asof - 20, lvl) > 0 && fs[0].classList.contains('picked') && fs[0].classList.contains('free'), [alphaAt(i1, bb.l[i1]), alphaAt(S.asof - 20, lvl)]);
    fs[1].click(); await frame();
    ok('free_card_without_numbers_says_so', S.flash && S.flash.free.rings.length === 0 && /没有提到具体的日期或价位/.test($('#toast').textContent));
    // 新格式：卡片上没有成段的数字，证据按画图指令一笔一笔画在图上
    ok('claude_card_has_no_wall_of_numbers', fs.every(li => li.querySelector('.look').hidden) && /图上 6 处标记/.test(fs[2].textContent), fs[2].textContent);
    fs[2].click(); await frame();
    const mk = S.flash && S.flash.marks;
    out.info.marks = mk && { types: mk.items.map(x => x.type), early: alphaAt(i1, bb.l[i1]) };
    ok('draw_instructions_resolved', mk && mk.items.map(x => x.type).join() === 'path,point,level,zone,volume' && mk.vol === true && !S.flash.free, out.info.marks);
    ok('draw_is_animated', alphaAt(S.asof - 20, lvl) === 0, alphaAt(S.asof - 20, lvl));        // 第三个标记（价位线）刚点下去时还没开始画
    await sleep(4000); await frame();
    ok('draw_finished_on_chart', alphaAt(i1, bb.l[i1]) > 0 && alphaAt(S.asof - 20, lvl) > 0 && alphaAt(i2, bb.h[i2]) > 0, [alphaAt(i1, bb.l[i1]), alphaAt(S.asof - 20, lvl), alphaAt(i2, bb.h[i2])]);
    // 记忆：已有 Claude 的解说、盘面没变时点“重新分析”，第一下只是问一句，不调用 API（这里只点一下，不会计费）
    const kept = N.current(); N.polish(false); await frame();
    ok('reanalyze_asks_before_spending', N.current() === kept && /再点一次确认/.test($('#aiPolish').textContent) && $('#aiPolish').classList.contains('arm') && /已存在本机/.test($('#aiHint').textContent) === S.meta.ai.enabled,
      [$('#aiPolish').textContent, $('#aiHint').textContent]);
    N.reset(); await frame();
    ok('narr_reset_clears_highlight', !S.flash && $('#narr').hidden && !$('#aiPolish').classList.contains('arm'));
    $('#aiRun').click(); await until(() => $('#narr .n-final.show'), 9000);
    out.info.ai = { enabled: S.meta.ai.enabled, polishDisabled: $('#aiPolish').disabled, hidden: $('#aiPolish').hidden, hint: $('#aiHint').textContent };
    ok('polish_button_matches_key', !$('#aiPolish').hidden && (S.meta.ai.enabled ? !$('#aiPolish').disabled : ($('#aiPolish').disabled && /ANTHROPIC_API_KEY/.test($('#aiHint').textContent))), out.info.ai);
    $('#aiRun').click(); await until(() => N.shown() >= 1 && !$('#aiSkip').hidden, 5000); $('#aiSkip').click();
    ok('narr_skip_animation', document.querySelectorAll('#narr .n-step.show').length === 4 && !!$('#narr .n-final.show') && $('#aiSkip').hidden);
    $('#sideClose').click(); const closed = side.classList.contains('closed'); $('#aiBtn').click();
    ok('side_collapsible', closed && !side.classList.contains('closed'));
    window.FEQuant.setTab('models'); await frame();          // 四证的历史信号、依据、回测现在在「模型」页签里
    const sigBtn = document.querySelector('#sigList button');
    ok('history_signals_listed', !!sigBtn && $('#sigList').getBoundingClientRect().height > 20 && !$('#fourDetail').hidden && $('#qPaneAnalyze').hidden);
    window.FEQuant.setTab('analyze'); await frame();

    // 周线：只看走势；四要素仍按日线判定，不画扇子、不打标记
    // 回放停在周中（2025-05-13 周二）时，周线停在上一个完整的周末，证据按那一天的日线收盘判定
    const day = S.bars, asofD = S.bars.d[S.asof];
    document.querySelector('#tfSeg [data-tf=W]').click();
    await until(() => S.tf === 'W' && S.bars.tf === 'W' && S.state && S.state.asof === S.bars.d[S.asof]); await frame();
    const wd = S.bars.d[S.asof], di = day.d.indexOf(wd);
    out.info.weekly = { n: S.bars.d.length, asof: wd, lit: lit(), stateLit: S.state.lit };
    ok('weekly_bars', S.bars.d.length < day.d.length / 4 && candle.data().length === S.asof + 1 && di >= 0 && S.bars.c[S.asof] === day.c[di] && wd <= asofD, out.info.weekly);
    ok('weekly_evidence_from_daily', lit() === S.state.lit && S.state.asof === wd && !!$('#evTf') && /按日线/.test($('#evTf').textContent), out.info.weekly);
    ok('weekly_no_auto_layer', alphaAt(S.asof - 1, dr.stop) === 0 && $('#autoBtn').disabled && $('[data-tool=avwap]').disabled, out.info.weekly);
    ok('weekly_url', /tf=W/.test(location.search));
    document.querySelector('#tfSeg [data-tf=D]').click();
    await until(() => S.tf === 'D' && S.bars.tf === 'D' && fresh()); await frame();
    ok('weekly_back_to_daily', S.bars.d.length === day.d.length && S.bars.d[S.asof] === wd && !$('#evTf') && !$('[data-tool=avwap]').disabled);
    await replayTo('2025-05-13');
    // 真实数据当天可能还没更新到位（来源晚出、某只票缺一根）：那时芯片应当如实写“数据未更新”，这同样算对。过期显示本身在 Freshness 测试里用受控数据单独测
    const staleNow = /数据未更新：只到 \d{4}-\d{2}-\d{2}，缺 \d+ 个交易日/.test($('#dataDate').textContent);
    ok('freshness_chip', staleNow || (/数据截至 \d{4}-\d{2}-\d{2} 收盘 · 日线/.test($('#dataDate').textContent) && !$('#evStale')), $('#dataDate').textContent);

    // 盘中实时：用模拟的盘中数据（美股收盘时也能测）。只多一根半透明 K 线和一行图例，别的都不变
    await replayTo(S.bars.d[S.bars.d.length - 1]); $('#rpExit').click(); await until(() => S.asof === S.bars.d.length - 1 && fresh()); await frame();
    const rect = el => { const r = $(el).getBoundingClientRect(); return [r.left, r.top, r.width, r.height].map(Math.round).join(); };
    const lay0 = ['#evidence', '#side', '#tools', '#topbar', '#chart'].map(rect).join('|'), st0 = JSON.stringify(S.state), bars0 = S.bars.d.length, cnt0 = candle.data().length;
    const last = S.bars.d[S.bars.d.length - 1], d1 = new Date(last + 'T12:00:00Z'); d1.setUTCDate(d1.getUTCDate() + 3);
    const sd = d1.toISOString().slice(0, 10), c0 = S.bars.c[S.asof];
    fe.setLive({ ok: true, ticker: S.ticker, status: 'regular', session_date: sd, show_candle: true, price: c0 * 1.01, change_pct: 1, price_time: Date.now() / 1000,
      bar: { o: c0, h: c0 * 1.02, l: c0 * 0.99, c: c0 * 1.01, v: 1e6 }, outside: null });
    await frame();
    const lv = fe.live().data(), lopt = fe.live().options();
    out.info.live = { lv, up: lopt.upColor, solid: candle.options().upColor };
    ok('live_candle_separate_layer', lv.length === 1 && lv[0].time === sd && candle.data().length === cnt0 && S.bars.d.length === bars0, out.info.live);
    ok('live_candle_translucent', /rgba\(.*,0\.2\d?\)/.test(lopt.upColor) && !/rgba/.test(candle.options().upColor), out.info.live);
    ok('live_does_not_touch_analysis', JSON.stringify(S.state) === st0 && lit() === S.state.lit);
    ok('live_layout_unchanged', ['#evidence', '#side', '#tools', '#topbar', '#chart'].map(rect).join('|') === lay0);
    ok('live_legend', !!$('#legLive') && /未收盘，不参与判定/.test($('#legLive').textContent), $('#legend').textContent);
    await replayTo(S.bars.d[S.bars.d.length - 3]);
    ok('live_hidden_in_replay', fe.live().data().length === 0 && !$('#legLive'));
    $('#rpExit').click(); await until(() => S.asof === S.bars.d.length - 1 && fresh()); await frame();
    const liveBox = document.querySelector('[data-ind=live]'); liveBox.click(); await frame();
    ok('live_toggle_off', fe.live().data().length === 0 && !$('#legLive')); liveBox.click(); await frame();
    ok('live_toggle_on', fe.live().data().length === 1);
    fe.setLive(null); await frame();
    await replayTo('2025-05-13');

    // 回到最新
    $('#rpExit').click(); await until(() => S.asof === S.bars.d.length - 1 && fresh());
    ok('replay_exit', $('#replaybar').hidden && S.asof === S.bars.d.length - 1);
    ok('data_date_shown', /数据未更新：只到 \d{4}-\d{2}-\d{2}/.test($('#dataDate').textContent) || (/数据截至 \d{4}-\d{2}-\d{2} 收盘/.test($('#dataDate').textContent) && /非实时/.test($('#dataDate').textContent)), $('#dataDate').textContent);
    // ---- 持仓页（只在测试给了 pfhelper 时跑：测试用一个本机小服务去改临时目录里的持仓文件，真文件不碰）----
    const helper = fe.query.get('pfhelper');       // 地址栏会被页面改写，所以读启动时的查询串
    if (helper) {
      const op = name => fetch('http://127.0.0.1:' + helper + '/op?do=' + name).then(r => r.json());
      const tileText = k => { const el = document.querySelector('.pf-tile[data-k=' + k + '] b'); return el ? el.textContent : null; };
      const money = x => x.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      document.querySelector('#viewSeg [data-view=portfolio]').click();
      await until(() => S.pf && S.pf.ok && !$('#pfPage').hidden && tileText('nav'), 20000);
      const pf = S.pf;
      out.info.pf = { nav: tileText('nav'), safe: $('[data-k=safe_pct] b').textContent, risky: $('[data-k=risky_pct] b').textContent, middle: $('[data-k=middle]').textContent, updated: $('#pfUpdated').textContent };
      ok('pf_page_shown', !$('#pfPage').hidden && getComputedStyle($('#refreshBtn')).display === 'none');
      ok('pf_account_tiles', tileText('nav') === money(pf.account.nav) && tileText('cash') === money(pf.account.cash) && tileText('buying_power') === money(pf.account.buying_power) &&
        tileText('option_margin') === money(pf.account.option_margin) && tileText('open_orders') === pf.account.open_orders.length + ' 张', out.info.pf);
      ok('pf_barbell', out.info.pf.safe === pf.barbell.safe_pct + '%' && out.info.pf.risky === pf.barbell.risky_pct + '%' && out.info.pf.middle.indexOf(pf.barbell.middle_obligation_x_nav + ' 倍净值') >= 0 &&
        document.querySelectorAll('.pf-bar > div').length === 3, out.info.pf);
      const rows = [...document.querySelectorAll('#pfPositions tbody tr')];
      const scoreOf = sym => { const r = rows.find(x => x.dataset.symbol === sym), b = r && r.querySelector('.chk-btn'); return b ? b.textContent.trim() : (r ? r.querySelector('td.chk').textContent.trim() : null); };
      const spcx = pf.checks.SPCX, want = 'SPCX ' + (spcx.armed ? spcx.score + '/4' : '未触发');
      out.info.pf_scores = pf.positions.map(p => [p.symbol, scoreOf(p.symbol)]);
      ok('pf_positions_rows', rows.length === pf.positions.length && document.querySelectorAll('#pfOthers tbody tr').length === pf.other_accounts.length, rows.length);
      const noChart = pf.positions.filter(p => !p.check_ticker);
      ok('pf_four_evidence_column', pf.positions.filter(p => p.check_ticker === 'SPCX').length === 5 && pf.positions.filter(p => p.check_ticker === 'SPCX').every(p => scoreOf(p.symbol) === want) &&
        noChart.length > 0 && noChart.every(p => scoreOf(p.symbol) === '—'), out.info.pf_scores);
      ok('pf_estimate_tags', document.querySelectorAll('#pfPositions .est').length === pf.positions.length && !!document.querySelector('.pf-lv[data-k=SPCX_bp_zero_est] .est') && !document.querySelector('.pf-lv[data-k=SPCX_minus10pct_buffer] .est'));
      ok('pf_checklist_hits', document.querySelectorAll('#pfChecklist li').length === pf.inversion_checklist.length && document.querySelectorAll('#pfChecklist li.hit').length === pf.inversion_checklist.filter(x => x.flag).length);
      ok('pf_updated_and_asof', /持仓更新于 \d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test($('#pfUpdated').textContent) && /台北/.test($('#pfAsof').textContent), $('#pfUpdated').textContent);
      await until(() => $('#pfSnapBody') && $('#pfSnapBody').textContent.length > 50, 8000);
      ok('pf_snapshot_rendered', $('#pfSnapBody').textContent.length > 50 && $('#pfSnapSel').options.length === pf.snapshots.length && $('#pfSnapSel').value === pf.snapshots[0].name, $('#pfSnapSel') && $('#pfSnapSel').value);
      ok('pf_fresh_no_banner', !$('#pfStale'));
      // 过期提示：数据时间改成两天前 → 出现；改回来 → 消失
      await op('stale'); const gotStale = await until(() => !!$('#pfStale'), 60000);
      ok('pf_stale_banner_appears', gotStale && /持仓数据已过期，以券商 App 为准/.test($('#pfStale').textContent) && /已过期/.test($('#pfChip').textContent));
      await op('fresh'); ok('pf_stale_banner_clears', await until(() => !$('#pfStale'), 60000));
      // 自动更新：改现金 → 60 秒内页面自己变；再改回来
      const cash0 = tileText('cash'), t0 = Date.now();
      await op('cash'); const gotCash = await until(() => tileText('cash') === '12,345.67', 60000);
      out.info.pf_update_ms = Date.now() - t0;
      ok('pf_auto_update_within_60s', gotCash && out.info.pf_update_ms < 60000, out.info.pf_update_ms);
      await op('cash_back'); ok('pf_auto_update_back', await until(() => tileText('cash') === cash0, 60000), tileText('cash'));
      // 删掉文件：持仓页显示“没有持仓数据”，图表页照常
      await op('delete'); const gotEmpty = await until(() => $('#pfEmpty') && /没有持仓数据/.test($('#pfEmpty').textContent), 60000);
      ok('pf_missing_message', gotEmpty && $('#pfChip').hidden);
      document.querySelector('#viewSeg [data-view=chart]').click(); await pick('SPCX');
      ok('pf_missing_chart_still_works', $('#pfPage').hidden && fresh() && candle.data().length === S.bars.d.length && lit() === S.state.lit);
      await op('restore'); await until(() => S.pf && S.pf.ok, 60000);
      // K 线叠加：打开开关才画；只是画线，证据不变
      const litBefore = lit(), cost = S.pf.overlays.SPCX.lines.find(l => l.kind === 'cost').price;
      const pxAt = p => { const d = window.devicePixelRatio || 1, y = Math.round(candle.priceToCoordinate(p) * d); const a = ov.getContext('2d').getImageData(Math.round(ov.width * 0.6), y - 1, 30, 3).data; let m = 0; for (let k = 3; k < a.length; k += 4) m = Math.max(m, a[k]); return m; };
      await frame(); const off = S.ind.pf;
      const box = document.querySelector('[data-ind=pf]'); box.click(); await frame();
      const on = pxAt(cost); box.click(); await frame();
      ok('pf_overlay_toggle', off === false && on > 0 && lit() === litBefore && S.state.lit === litBefore, [off, on]);
      const kinds = S.pf.overlays.SPCX.lines.map(l => l.kind);
      ok('pf_overlay_lines', kinds[0] === 'cost' && kinds.indexOf('zero') >= 0 && S.pf.overlays.SPCX.lines.find(l => l.kind === 'zero').est === true &&
        S.pf.overlays.SPCX.valuation.length > 0 && document.querySelector('[data-ind=pfval]').checked === false, kinds);
    }
    // 「AI 量化」面板（补充指令 3）：表盘、模型切换、后手清单条、四步、划线、编号图例
    {
      const QF = window.FEQuant, NA = window.FENarrate;
      await pick('NVDA'); await until(() => QF.fresh(), 8000);
      ok('quant_gauge', QF.fresh() && /^[+-]?\d+$/.test($('#qTotal').textContent) && document.querySelectorAll('#qScore .q-part').length === 5 && $('#qLabel').textContent === QF.data().score.label, $('#qScore').textContent);
      const sel = $('#qModel'); sel.value = 'houshou'; sel.dispatchEvent(new Event('change', { bubbles: true }));
      await until(() => QF.fresh() && QF.model() === 'houshou', 8000); await frame();
      const qd = QF.data();
      ok('quant_houshou_bar', !$('#qBar').hidden && /后手战法/.test($('#qBar').textContent) && $('#evidence').hidden && /后手·成本线回踩/.test($('#sigCard').textContent) &&
        document.querySelectorAll('#tiles .tile').length === 6 && /第二目标/.test($('#tiles').textContent) && /未回测/.test($('#sigFoot').textContent), $('#qBar').textContent);
      ok('quant_legend_numbered', !$('#qLegend').hidden && document.querySelectorAll('#qLegend li').length === qd.legend.length && qd.legend.length >= 3, qd.legend.length);
      ok('quant_no_order_buttons', ![...document.querySelectorAll('button')].some(b => /买入|下单|卖出/.test(b.textContent)) && !$('#qShort').disabled && !$('#qLong').disabled && /尚未回测/.test($('#banner').textContent));
      $('#qRun').click(); await until(() => !QF.state().running && QF.state().steps && QF.state().steps.every(s => s.state === 'done'), 20000); await frame();
      const stp = QF.state().steps || [];
      ok('quant_four_steps', stp.length === 4 && stp.every(s => s.state === 'done' && s.ms != null) && new RegExp('共 ' + qd.lines.length + ' 条').test(stp[2].note) && !!NA.current() && /模板|Claude/.test($('#narrSrc').textContent), stp);
      // 显示设置：每条线一个开关；动画快慢、图例都能改
      $('#qSetBtn').click(); await frame();
      ok('quant_lines_listed', !$('#qSetPop').hidden && document.querySelectorAll('#qLines .q-lines input').length === qd.lines.length && QF.state().linesOn === true);
      document.querySelector('#qSetPop [data-speed=fast]').click(); await frame();
      const lg = document.querySelector('#qSetPop [data-set=legend]'); lg.checked = false; lg.dispatchEvent(new Event('change', { bubbles: true })); await frame();
      const legendOff = $('#qLegend').hidden; lg.checked = true; lg.dispatchEvent(new Event('change', { bubbles: true })); await frame();
      ok('quant_settings_work', QF.state().speed === 'fast' && legendOff && !$('#qLegend').hidden, [QF.state().speed, legendOff]);
      document.querySelector('#qSetPop [data-speed=normal]').click(); document.body.click(); await frame();
      // 窗口头部：放宽 / 恢复；量化终端按钮带着现在的周期和级别打开
      $('#qExpand').click(); const wide = $('#side').classList.contains('wide'); $('#qExpand').click();
      ok('quant_expand_toggles', wide && !$('#side').classList.contains('wide') && $('#qSetPop').hidden);
      const open0 = window.open; let termUrl = ''; window.open = u => { termUrl = u; return null; }; $('#qTerm').click(); window.open = open0;
      ok('quant_terminal_button', /^\/terminal\?hz=20&tf=D$/.test(termUrl), termUrl);
      // 四个页签：每次只显示一页
      const panes = () => [...document.querySelectorAll('#side [data-pane]')].filter(p => !p.hidden).map(p => p.dataset.pane).join();
      const tabSeen = [];
      for (const t of ['models', 'tasks', 'chat', 'analyze']) { document.querySelector('#qTabs [data-qtab=' + t + ']').click(); await frame(); tabSeen.push(panes() + (document.querySelector('#qTabs .on').dataset.qtab === t ? '' : '!')); }
      ok('quant_tabs_switch', tabSeen.join('|') === 'models|tasks|chat|analyze' && $('#learn').hidden, tabSeen);
      // 模型页签：三张模型卡，每张写明来历和参数；现在选的模型有历史触发表和参数表
      QF.setTab('models'); await until(() => QF.state().lib && document.querySelectorAll('#qModelCards .mcard').length === QF.state().lib.models.length && $('#qParams') && $('#qHist') && document.querySelector('#qModelCards button.m-side'), 8000);
      const nModels = QF.state().lib ? QF.state().lib.models.length : 0;
      const sideBtns = QF.state().lib ? QF.state().lib.models.reduce((a, m) => a + (m.tfs.indexOf('D') >= 0 ? m.sides.length : 0), 0) : -1;
      ok('quant_params_marked_estimate', /估算/.test($('#qParams').textContent) && /样本数/.test($('#qHist').textContent) && /录屏/.test($('#qModelCards').textContent) && $('#fourDetail').hidden);
      ok('quant_model_cards', nModels >= 13 && document.querySelectorAll('#qModelCards .mcard').length === nModels && document.querySelector('#qModelCards .mcard.on').dataset.model === 'houshou' &&
        /没有这一侧的规则/.test(document.querySelector('#qModelCards .mcard[data-model=four]').textContent) && document.querySelectorAll('#qModelCards button.m-side').length === sideBtns,
        [nModels, document.querySelectorAll('#qModelCards button.m-side').length, sideBtns]);
      ok('quant_model_dropdown_grouped', document.querySelectorAll('#qModel optgroup').length >= 4 && document.querySelectorAll('#qModel option').length === nModels &&
        !!document.querySelector('#qModel option[value=yindie]'), document.querySelectorAll('#qModel option').length);
      document.querySelector('#qModelCards .mcard[data-model=breakout] button.m-side[data-side=short]').click();     // 在模型页里点「破位反抽 · 做空」
      await until(() => QF.fresh() && QF.model() === 'breakout' && QF.side() === 'short' && QF.tab() === 'analyze', 8000); await frame();
      const bd = QF.data();
      ok('quant_short_side_runs', bd.side === 'short' && bd.side_ok && $('#qShort').classList.contains('on') && !$('#qLong').classList.contains('on') && /做空/.test($('#sigCard .chip-dir').textContent) &&
        /破位反抽/.test($('#sigCard').textContent) && document.querySelectorAll('#tiles .tile').length === 6 && $('#evidence').hidden && $('#qModel').value === 'breakout', $('#sigCard').textContent);
      // 做多 / 做空两个按钮：点哪个算哪一侧，结果跟着换
      $('#qLong').click(); await until(() => QF.fresh() && QF.side() === 'long', 8000); await frame();
      const ld = QF.data();
      ok('quant_long_button_switches_back', ld.side === 'long' && ld.variant !== bd.variant && $('#qLong').classList.contains('on') && !$('#qShort').classList.contains('on') && /做多/.test($('#sigCard .chip-dir').textContent) &&
        /突破回踩/.test($('#sigCard').textContent + $('#qBar').textContent), [ld.variant, bd.variant, $('#sigCard').textContent.slice(0, 60)]);
      // 周期：换成 60，表盘的回看、标签、历史往后看的根数都跟着变
      const hz = $('#qHz'); hz.value = '60'; hz.dispatchEvent(new Event('change', { bubbles: true })); await until(() => QF.fresh() && QF.data().horizon.n === 60, 8000); await frame();
      ok('quant_horizon_changes_result', /MA180/.test($('#qScore').textContent) && /中线 · 60 日/.test($('#sigCard .chip-hz').textContent) && QF.data().history.hold === 60, $('#qScore').textContent.slice(0, 80));
      hz.value = '20'; hz.dispatchEvent(new Event('change', { bubbles: true })); await until(() => QF.fresh() && QF.data().horizon.n === 20, 8000);
      // 持仓：假设持有多单，只多一句说明，清单和价位不变
      const ps = $('#qPos'); ps.value = 'short'; ps.dispatchEvent(new Event('change', { bubbles: true })); await until(() => QF.fresh() && QF.data().position.mode === 'short', 8000); await frame();
      ok('quant_position_changes_words', !$('#qPosNote').hidden && /假设你有空单/.test($('#qPosNote').textContent) && JSON.stringify(QF.data().signal.checks) === JSON.stringify(ld.signal.checks), $('#qPosNote').textContent);
      ps.value = 'auto'; ps.dispatchEvent(new Event('change', { bubbles: true })); await until(() => QF.fresh() && QF.data().position.mode === 'auto', 8000); await frame();
      ok('quant_position_back_to_account', $('#qPosNote').hidden);
      // K 线级别：窗口头部的下拉和顶栏的「日线 / 周线」是同一个开关；破位反抽能在周 K 上跑
      $('#qTfBtn').click(); await frame(); const tfPop = !$('#qTfPop').hidden;
      document.querySelector('#qTfPop [data-qtf=W]').click(); await until(() => S.tf === 'W' && QF.fresh() && QF.data().tf === 'W', 10000); await frame();
      ok('quant_weekly_pill', tfPop && $('#qTfPop').hidden && /周K/.test($('#qTfText').textContent) && QF.data().tf_ok && /20 周/.test($('#qHz').selectedOptions[0].textContent) &&
        document.querySelector('#tfSeg [data-tf=W]').classList.contains('on') && /周K/.test($('#qWeekNote').textContent), $('#qTfText').textContent);
      $('#qTfBtn').click(); await frame(); document.querySelector('#qTfPop [data-qtf=D]').click(); await until(() => S.tf === 'D' && QF.fresh() && QF.data().tf === 'D', 10000); await frame();
      // 四证没有做空一侧：按了做空，如实说用不上，并给出“换用”按钮；点一下就换过去
      sel.value = 'four'; sel.dispatchEvent(new Event('change', { bubbles: true })); await until(() => QF.fresh() && QF.model() === 'four', 8000); await frame();
      $('#qShort').click(); await until(() => QF.fresh() && QF.side() === 'short', 8000); await frame();
      const na = QF.data(), useBtn = document.querySelector('#sigCard .sig-use [data-use=houshou]');
      ok('quant_four_short_says_so', na.side_ok === false && na.signal.unsupported === 'side' && /只定义了做多一侧/.test($('#sigCard').textContent) && !!useBtn && $('#evidence').hidden &&
        [...document.querySelectorAll('#tiles .tile b')].slice(1).every(b => b.textContent === '—'), $('#sigCard').textContent);
      useBtn.click(); await until(() => QF.fresh() && QF.model() === 'houshou' && QF.side() === 'short', 8000); await frame();
      ok('quant_suggested_model_takes_over', QF.data().side_ok && /后手战法 · 做空/.test($('#qBar').textContent) && /镜像规则/.test($('#sigCard').textContent), $('#qBar').textContent);
      // 任务页签：把现在的组合加入盯盘，暂停、删除；刚才那次分析留了一行记录，点它能回去
      QF.setTab('tasks'); await until(() => $('#qTaskNew') && !$('#qTaskNew').disabled && document.querySelector('#qRunList .run-row'), 8000);
      const runs0 = document.querySelectorAll('#qRunList .run-row').length;
      $('#qTaskNew').click(); await until(() => document.querySelector('#qTaskList .task'), 8000);
      const tk = QF.state().tasks.tasks[0];
      ok('quant_task_added', tk.ticker === 'NVDA' && tk.model === 'houshou' && tk.side === 'short' && !!tk.last && $('#qTaskNew').disabled && /后手·成本线回踩/.test($('#qTaskList').textContent), tk);
      document.querySelector('#qTaskList [data-task=pause]').click(); await until(() => QF.state().tasks.tasks[0].enabled === false, 6000);
      const paused = !!document.querySelector('#qTaskList .task.paused');
      document.querySelector('#qTaskList [data-task=delete]').click(); await until(() => QF.state().tasks.tasks.length === 0, 6000);
      ok('quant_task_pause_and_delete', paused && !document.querySelector('#qTaskList .task') && !$('#qTaskNew').disabled);
      document.querySelector('#qRunList .run-row').click(); await until(() => QF.fresh() && QF.model() === 'houshou' && QF.side() === 'long' && QF.tab() === 'analyze', 8000); await frame();
      ok('quant_run_log_restores', runs0 >= 1 && QF.side() === 'long' && $('#qLong').classList.contains('on') && S.ticker === 'NVDA', runs0);
      sel.value = 'four'; sel.dispatchEvent(new Event('change', { bubbles: true })); await until(() => QF.fresh() && QF.model() === 'four' && QF.side() === 'long', 8000); await frame();
      ok('quant_back_to_four', $('#qBar').hidden && !$('#evidence').hidden && lit() === S.state.lit && /四要素规则引擎/.test($('#sigCard').textContent) && document.querySelectorAll('#tiles .tile').length === 6 &&
        /第二目标/.test($('#tiles').textContent) && /做多/.test($('#sigCard .chip-dir').textContent));
      await pick('SPCX');
    }
    // 「时效与备注」：侧栏的时效卡片；手写一条备注，图底部出现标记；删掉后消失
    {
      const NF = window.FENotes;
      await pick('NVDA'); await until(() => NF.fresh(), 8000);
      ok('notes_freshness_card', /K 线数据/.test($('#noteCard').textContent) && /事件日历/.test($('#noteCard').textContent) && /新闻存档/.test($('#noteCard').textContent) &&
        document.querySelectorAll('#noteCard .fr-days li').length === 5 && !!$('#noteSearch') && $('#noteSearch').disabled === !(S.meta.ai.enabled && NF.data().notable.some(r => !r.searched)), $('#noteCard').textContent);
      const day = S.bars.d[S.asof - 3], dpr = window.devicePixelRatio || 1;
      const markAt = () => { const x = Math.round(ch.timeScale().logicalToCoordinate(S.asof - 3) * dpr), y = Math.round((ov.height / dpr - 11) * dpr); const px = ov.getContext('2d').getImageData(x - 3, y - 3, 7, 7).data; let a = 0; for (let k = 3; k < px.length; k += 4) a += px[k]; return a; };
      await frame(); const before = markAt();
      NF.openDay(day);
      const inp = $('#modalBody .note-form input'); inp.value = '自检写的一条';
      $('#modalBody .note-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      const added = await until(() => NF.data() && (NF.data().by_date[day] || []).some(r => r.title === '自检写的一条'), 8000); await frame();
      ok('notes_manual_note_marks_the_bar', added && before === 0 && markAt() > 0 && /自检写的一条/.test($('#modalBody').textContent) && lit() === S.state.lit, [added, before, markAt()]);
      // 解说卡片在图上标到这一天时，把这天的备注带在卡片上
      window.FENarrate.show({ ok: true, source: 'claude', ticker: S.ticker, asof: S.state.asof, model: 'selftest', polish: { enabled: false, reason: '', model: 'x' }, narration: { hook: '自检', story: '自检', final: '还不抄', watch: [],
        steps: [{ q: '那天', say: '这天有事', sticker: '', tone: 'neutral', evidence: 0, ok: null, draw: [{ type: 'point', date: day, price: S.bars.l[S.asof - 3], label: '坑' }] },
          { q: '别的', say: '这步也标了同一天', sticker: '', tone: 'neutral', evidence: 0, ok: null, draw: [{ type: 'volume', dates: [day], label: '量' }] }] } }, false);
      await frame();
      const nn = [...document.querySelectorAll('#narr .n-step')].map(li => (li.querySelector('.n-notes') || {}).textContent || '');
      ok('notes_shown_on_ai_card_once', /自检写的一条/.test(nn[0]) && nn[1] === '' && /AI 解读/.test($('#noteCard').textContent), nn);      // 同一条备注不在两张卡片上重复
      // 原始的新闻标题不上卡片（又长又杂），事件日和联网搜到的概括才上
      const real = NF.data(), mix = JSON.parse(JSON.stringify(real));
      mix.by_date[day] = [{ id: 'n1', kind: 'news', title: 'S&P 500, Dow, Nasdaq End Lower Amid Turmoil', title_zh: '标普、道指、纳指收跌', source: 'X', fact: false }, { id: 'e1', kind: 'earnings', title: '财报日', fact: true },
        { id: 's1', kind: 'search', title: '财报后下调指引', fact: false }];
      NF._use(mix);
      const fd = NF.forDraw([{ type: 'point', date: day, price: 1 }]).map(r => r.text);
      ok('notes_no_raw_headlines_on_cards', fd.length === 2 && /财报日/.test(fd[0]) && /财报后下调指引/.test(fd[1]) && !fd.some(t => /S&P/.test(t)), fd);
      const lines = [...document.querySelectorAll('#narr .n-notes span')];
      ok('notes_on_cards_are_one_line_each', lines.length > 0 && lines.every(sp => getComputedStyle(sp).whiteSpace === 'nowrap' && sp.title === sp.textContent), lines.length);
      NF.openDay(day);       // 英文标题有中文翻译时显示中文，原文留在下面
      const mt = $('#modalBody').textContent;
      ok('notes_headlines_shown_in_chinese', /标普、道指、纳指收跌/.test(mt) && /原文：S&P 500/.test(mt) && mt.indexOf('标普') < mt.indexOf('原文：S&P'), mt.slice(0, 160));
      NF._use(real); NF.openDay(day);
      window.FENarrate.reset();
      const row = [...document.querySelectorAll('#modalBody .note-row')].find(r => /自检写的一条/.test(r.textContent));
      if (row) row.querySelector('button').click();
      const gone = await until(() => NF.data() && !(NF.data().by_date[day] || []).some(r => r.title === '自检写的一条'), 8000); await frame();
      ok('notes_delete_clears_the_mark', gone && markAt() === 0, [gone, markAt()]);
      $('#modalClose').click();
      await pick('SPCX');
    }
    // AI 对话（一键解释并在里面）：点一下出大白话解释，作为一条消息留在对话里；对话存档、能新建、能翻历史
    {
      const CF = window.FEChat, QF = window.FEQuant;
      ok('chat_closed_by_default', $('#learn').hidden && !CF.isOpen());
      $('#learnBtn').click(); await until(() => CF.conv() && CF.conv().messages.length === 1 && document.querySelector('#learn .lcard'), 8000);
      const cv = CF.conv(), lp = cv.messages[0].learn, cards = [...document.querySelectorAll('#learn .lcard')];
      ok('explain_lands_in_chat_as_cards', !$('#learn').hidden && cv.messages[0].kind === 'explain' && cards.length === lp.cards.length && cards.length >= 12 && !!$('#learn .learn-hl b').textContent &&
        cards.every(a => a.querySelector('h4').textContent.length > 3 && a.querySelector('p').textContent.length > 20) && /没花钱/.test($('#learn .cx-chip').textContent), cards.length);
      ok('explain_says_today', document.querySelectorAll('#learn .lnow').length >= 8 && new RegExp(S.state.asof).test($('#learn').textContent));
      ok('chat_chart_still_there', candle.data().length === S.bars.d.length && $('#chart').getBoundingClientRect().width > 300, $('#chart').getBoundingClientRect().width);
      document.querySelector('#learn .lcard[data-id=banner] .lspot').click();
      ok('explain_points_at_things', $('#banner').classList.contains('learn-spot'));
      document.querySelector('#learn .lcard[data-id=e1] .lspot').click(); await frame();
      ok('explain_points_at_evidence', $('#evidence').classList.contains('learn-spot') && S.flash && S.flash.k === 0, S.flash && S.flash.k);
      ok('explain_no_advice', !/建议买|建议卖|可以买入|赶紧/.test($('#learn').textContent) && /不告诉你该买还是该卖/.test($('#learn').textContent));
      // 换一只票再点一次：新的解释接在同一段对话后面，前一条不动
      await pick('QQQ'); $('#chatExplain').click();
      await until(() => CF.conv() && CF.conv().messages.length === 2, 8000);
      const chips = [...document.querySelectorAll('#learn .cx-chip')].map(x => x.textContent);
      ok('explain_appends_not_rewrites', chips.length === 2 && /SPCX|NVDA/.test(chips[0]) && /QQQ/.test(chips[1]) && CF.conv().id === cv.id, chips);
      // 提问：没有密钥时输入框关着并说明原因；有密钥时能打字（真正的问答在后端测试里对着假服务跑）
      ok('chat_input_matches_key', $('#chatInput').disabled === !S.meta.ai.enabled && (S.meta.ai.enabled || /没有设置 API 密钥/.test($('#chatInput').placeholder)) && !$('#chatExplain').disabled, $('#chatInput').placeholder);
      // Markdown 只建节点：加粗、列表、表格、链接；脚本标签当普通文字
      const fr = document.createElement('div'); fr.appendChild(CF.md('**结论**：先等\n\n- 第一条\n- 第二条\n\n| 项 | 值 |\n|---|---|\n| 止损 | 144.34 |\n\n<script>window.__x=1</script> [出处](https://example.com/a)'));
      ok('chat_markdown_is_safe', !!fr.querySelector('strong') && fr.querySelectorAll('li').length === 2 && fr.querySelectorAll('td').length === 2 && !fr.querySelector('script') && window.__x === undefined &&
        fr.querySelector('a').getAttribute('href') === 'https://example.com/a' && fr.querySelector('a').rel === 'noopener noreferrer', fr.innerHTML.slice(0, 200));
      // 历史和新对话
      $('#chatHistBtn').click(); await until(() => document.querySelector('#learn .chat-item'), 6000);
      ok('chat_history_lists_saved', document.querySelectorAll('#learn .chat-item').length >= 1 && /一键解释/.test($('#learn .chat-item b').textContent) && $('#chatForm').hidden);
      $('#chatNewBtn').click(); await frame();
      ok('chat_new_is_empty', !CF.conv() && !!$('#learn .chat-empty') && !$('#chatForm').hidden);
      $('#chatHistBtn').click(); await until(() => document.querySelector('#learn .chat-item .open'), 6000);
      document.querySelector('#learn .chat-item .open').click(); await until(() => CF.conv() && CF.conv().id === cv.id && document.querySelectorAll('#learn .cx-chip').length === 2, 6000);
      ok('chat_reopens_with_memory', CF.conv().messages.length === 2 && document.querySelectorAll('#learn .lcard').length >= 24);
      $('#chatClose').click();
      ok('chat_closes', $('#learn').hidden && !CF.isOpen());
      // 切换模型不清空 AI 解读：另一个模型下分析过的那一份留在原处
      await pick('SPCX');
    }
    const ext = performance.getEntriesByType('resource').map(e => e.name).filter(u => new URL(u).host !== location.host && !(helper && new URL(u).port === helper));
    ok('no_external_requests', ext.length === 0, ext);
  } catch (e) { out.error = String(e && e.stack || e); }
  out.pass = !out.error && Object.values(out.checks).every(Boolean);
  const pre = document.createElement('pre'); pre.id = 'selftest'; pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
})();
