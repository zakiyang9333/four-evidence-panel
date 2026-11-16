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
    ok('banner_text', $('#banner').textContent.trim() === '未验证，仅观察。回测证据不足，不是买入建议。', $('#banner').textContent);
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
    await until(() => N.current() && N.shown() >= 1 && N.shown() < 4, 5000);
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
    out.info.ai = { enabled: S.meta.ai.enabled, polishDisabled: $('#aiPolish').disabled, hidden: $('#aiPolish').hidden, hint: $('#aiHint').textContent };
    ok('polish_button_matches_key', !$('#aiPolish').hidden && (S.meta.ai.enabled ? !$('#aiPolish').disabled : ($('#aiPolish').disabled && /ANTHROPIC_API_KEY/.test($('#aiHint').textContent))), out.info.ai);
    $('#aiRun').click(); await until(() => N.shown() >= 1 && !$('#aiSkip').hidden, 5000); $('#aiSkip').click();
    ok('narr_skip_animation', document.querySelectorAll('#narr .n-step.show').length === 4 && !!$('#narr .n-final.show') && $('#aiSkip').hidden);
    $('#sideClose').click(); const closed = side.classList.contains('closed'); $('#aiBtn').click();
    ok('side_collapsible', closed && !side.classList.contains('closed'));
    const sigBtn = document.querySelector('#sigList button');
    ok('history_signals_listed', !!sigBtn && $('#sigList').getBoundingClientRect().height > 20);

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
    ok('freshness_chip', /数据截至 \d{4}-\d{2}-\d{2} 收盘 · 日线/.test($('#dataDate').textContent) && !$('#evStale'), $('#dataDate').textContent);

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
    ok('data_date_shown', /数据截至 \d{4}-\d{2}-\d{2} 收盘/.test($('#dataDate').textContent) && /非实时/.test($('#dataDate').textContent), $('#dataDate').textContent);
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
    const ext = performance.getEntriesByType('resource').map(e => e.name).filter(u => new URL(u).host !== location.host && !(helper && new URL(u).port === helper));
    ok('no_external_requests', ext.length === 0, ext);
  } catch (e) { out.error = String(e && e.stack || e); }
  out.pass = !out.error && Object.values(out.checks).every(Boolean);
  const pre = document.createElement('pre'); pre.id = 'selftest'; pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
})();
