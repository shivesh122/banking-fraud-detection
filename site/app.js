/* Fraud Detection Centre dashboard. Data: data/dashboard.json, model: model/model.json (scored by scorer.js). */
(() => {
  'use strict';

  const C = { red: '#f43f5e', amber: '#fbbf24', green: '#34d399', blue: '#60a5fa', violet: '#a78bfa', slate: '#64748b', grid: '#1c2842' };
  const CATEGORIES = ['Grocery', 'Restaurants', 'Fuel', 'E-commerce', 'Utilities', 'Pharmacy', 'Travel', 'Electronics', 'Jewellery', 'Gift Cards', 'Gaming & Crypto', 'ATM', 'Transfers'];
  const TYPE_LABEL = { account_takeover: 'Account takeover', card_testing: 'Card testing', cloned_card: 'Cloned card', compromised_merchant: 'Compromised merchant' };
  const FEATURE_LABEL = {
    anomaly_score: 'Isolation Forest anomaly score', is_online: 'Online channel', log_amount: 'Transaction amount',
    amount_ratio: 'Amount vs usual spend', amount_24h_ratio: '24 h spend vs usual', txn_count_1h: 'Transactions in past hour',
    txn_count_24h: 'Transactions in past 24 h', log_mins_since_last: 'Time since last transaction', hour: 'Hour of day',
    is_night: 'Night-time', distance_home_km: 'Distance from home', speed_kmh: 'Implied travel speed', is_new_device: 'New device',
    is_new_merchant: 'New merchant', is_upi: 'UPI channel', is_atm: 'ATM channel', is_pos: 'Card present (POS)',
    is_high_risk_category: 'High-risk category', is_international: 'International', account_age_days: 'Account age',
  };

  // ---------- format ----------
  const nf = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
  const inr = (v) => {
    const a = Math.abs(v || 0);
    if (a >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
    if (a >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
    if (a >= 1e3) return `₹${(v / 1e3).toFixed(1)}K`;
    return `₹${nf.format(v || 0)}`;
  };
  const inrFull = (v) => `₹${new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(v)}`;
  const num = (v) => nf.format(v || 0);
  const pct = (v, d = 1) => `${(100 * v).toFixed(d)}%`;
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const parseDay = d3.timeParse('%Y-%m-%d');
  const probColor = (p) => (p >= 0.7 ? C.red : p >= 0.4 ? C.amber : C.green);

  // ---------- tooltip & chart registry ----------
  const tip = document.getElementById('tip');
  function showTip(html, e) {
    tip.innerHTML = html;
    tip.style.opacity = 1;
    const r = tip.getBoundingClientRect();
    let x = e.clientX + 14;
    let y = e.clientY + 14;
    if (x + r.width > innerWidth - 8) x = e.clientX - r.width - 14;
    if (y + r.height > innerHeight - 8) y = e.clientY - r.height - 14;
    tip.style.left = `${x}px`;
    tip.style.top = `${y}px`;
  }
  const hideTip = () => { tip.style.opacity = 0; };
  const charts = new Map();
  const visible = (el) => el && el.offsetParent !== null;
  function register(id, fn) {
    charts.set(id, fn);
    const el = document.getElementById(id);
    if (visible(el)) fn(el);
  }
  const renderVisible = () => charts.forEach((fn, id) => { const el = document.getElementById(id); if (visible(el)) fn(el); });
  let rt;
  addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(renderVisible, 150); });

  function frame(el, m) {
    el.innerHTML = '';
    const width = Math.max(el.clientWidth, 260);
    const height = el.clientHeight || 270;
    const svg = d3.select(el).append('svg').attr('viewBox', `0 0 ${width} ${height}`);
    const g = svg.append('g').attr('transform', `translate(${m.left},${m.top})`);
    return { svg, g, w: width - m.left - m.right, h: height - m.top - m.bottom };
  }
  function legend(svg, items, x, y) {
    const lg = svg.append('g').attr('class', 'legend').attr('transform', `translate(${x},${y})`);
    let off = 0;
    items.forEach((it) => {
      const gi = lg.append('g').attr('transform', `translate(${off},0)`);
      if (it.line) gi.append('line').attr('x2', 16).attr('stroke', it.color).attr('stroke-width', 2.5).attr('stroke-dasharray', it.dash || null);
      else gi.append('rect').attr('y', -6).attr('width', 12).attr('height', 12).attr('rx', 3).attr('fill', it.color);
      gi.append('text').attr('x', it.line ? 21 : 17).attr('y', 4).text(it.label);
      off += (it.line ? 26 : 22) + it.label.length * 6.3 + 14;
    });
  }

  // ---------- charts ----------
  function dailyChart(el, rows) {
    const data = rows.map((d) => ({ ...d, dt: parseDay(d.date) }));
    const m = { top: 30, right: 12, bottom: 28, left: 36 };
    const { svg, g, w, h } = frame(el, m);
    const x = d3.scaleBand().domain(data.map((d) => d.date)).range([0, w]).padding(0.2);
    const y = d3.scaleLinear().domain([0, d3.max(data, (d) => Math.max(d.alerts, d.frauds)) * 1.15 || 1]).nice().range([h, 0]);
    g.append('g').attr('class', 'grid-line').call(d3.axisLeft(y).ticks(5).tickSize(-w).tickFormat(''));
    const every = Math.ceil(data.length / 8);
    g.append('g').attr('class', 'axis').attr('transform', `translate(0,${h})`)
      .call(d3.axisBottom(x).tickValues(x.domain().filter((_, i) => i % every === 0)).tickFormat((d) => d3.timeFormat('%d %b')(parseDay(d))));
    g.append('g').attr('class', 'axis').call(d3.axisLeft(y).ticks(5));
    g.selectAll('rect.a').data(data).join('rect').attr('class', 'a').attr('x', (d) => x(d.date)).attr('width', x.bandwidth())
      .attr('y', (d) => y(d.alerts)).attr('height', (d) => h - y(d.alerts)).attr('rx', 2).attr('fill', C.blue).attr('opacity', 0.35);
    g.selectAll('rect.t').data(data).join('rect').attr('class', 't').attr('x', (d) => x(d.date)).attr('width', x.bandwidth())
      .attr('y', (d) => y(d.true_alerts)).attr('height', (d) => h - y(d.true_alerts)).attr('rx', 2).attr('fill', C.red);
    g.append('path').datum(data).attr('fill', 'none').attr('stroke', C.amber).attr('stroke-width', 2)
      .attr('d', d3.line().x((d) => x(d.date) + x.bandwidth() / 2).y((d) => y(d.frauds)).curve(d3.curveMonotoneX));
    g.selectAll('rect.h').data(data).join('rect').attr('x', (d) => x(d.date)).attr('width', x.step()).attr('height', h).attr('fill', 'transparent')
      .on('mousemove', (e, d) => showTip(`<b>${d3.timeFormat('%a %d %b')(d.dt)}</b><br>${num(d.transactions)} transactions<br>Alerts: ${d.alerts} (${d.true_alerts} confirmed fraud)<br>Fraud transactions: ${d.frauds}<br>Fraud amount caught: ${inr(d.caught_amount)} of ${inr(d.fraud_amount)}`, e))
      .on('mouseleave', hideTip);
    legend(svg, [{ label: 'Alerts raised', color: 'rgba(96,165,250,.45)' }, { label: 'Alerts that were fraud', color: C.red }, { label: 'All fraud transactions', color: C.amber, line: true }], m.left, 12);
  }

  function hbar(el, data, { value, label, color, format, tip: tipFn, max, left = 150 }) {
    const m = { top: 4, right: 58, bottom: 22, left };
    el.style.height = `${Math.max(150, data.length * 30 + 36)}px`;
    const { g, w, h } = frame(el, m);
    const y = d3.scaleBand().domain(data.map(label)).range([0, h]).padding(0.28);
    const x = d3.scaleLinear().domain([0, max ?? (d3.max(data, value) * 1.05 || 1)]).nice().range([0, w]);
    g.append('g').attr('class', 'grid-line').attr('transform', `translate(0,${h})`).call(d3.axisBottom(x).ticks(4).tickSize(-h).tickFormat(''));
    g.append('g').attr('class', 'axis').attr('transform', `translate(0,${h})`).call(d3.axisBottom(x).ticks(4).tickFormat(format));
    g.append('g').attr('class', 'axis').call(d3.axisLeft(y).tickSize(0).tickPadding(8)).select('.domain').remove();
    g.selectAll('rect').data(data).join('rect').attr('y', (d) => y(label(d))).attr('height', y.bandwidth()).attr('width', (d) => x(value(d)))
      .attr('rx', 4).attr('fill', color).on('mousemove', (e, d) => tipFn && showTip(tipFn(d), e)).on('mouseleave', hideTip);
    g.selectAll('text.v').data(data).join('text').attr('class', 'v').attr('x', (d) => x(value(d)) + 6).attr('y', (d) => y(label(d)) + y.bandwidth() / 2 + 4)
      .attr('font-size', 11.5).attr('font-weight', 600).attr('fill', '#c3cde0').text((d) => format(value(d)));
  }

  function hourChart(el, rows) {
    const m = { top: 10, right: 8, bottom: 26, left: 40 };
    const { g, w, h } = frame(el, m);
    const x = d3.scaleBand().domain(rows.map((d) => d.hour)).range([0, w]).padding(0.15);
    const y = d3.scaleLinear().domain([0, d3.max(rows, (d) => d.fraud_rate_pct) * 1.15]).nice().range([h, 0]);
    g.append('g').attr('class', 'grid-line').call(d3.axisLeft(y).ticks(4).tickSize(-w).tickFormat(''));
    g.append('g').attr('class', 'axis').attr('transform', `translate(0,${h})`).call(d3.axisBottom(x).tickValues([0, 3, 6, 9, 12, 15, 18, 21]).tickFormat((d) => `${d}h`));
    g.append('g').attr('class', 'axis').call(d3.axisLeft(y).ticks(4).tickFormat((v) => `${v}%`));
    g.selectAll('rect').data(rows).join('rect').attr('x', (d) => x(d.hour)).attr('width', x.bandwidth()).attr('y', (d) => y(d.fraud_rate_pct))
      .attr('height', (d) => h - y(d.fraud_rate_pct)).attr('rx', 3).attr('fill', (d) => (d.hour < 6 || d.hour >= 23 ? C.red : C.violet))
      .on('mousemove', (e, d) => showTip(`<b>${String(d.hour).padStart(2, '0')}:00–${String(d.hour).padStart(2, '0')}:59</b><br>Fraud rate: ${d.fraud_rate_pct.toFixed(2)}%<br>${num(d.frauds)} frauds in ${num(d.transactions)} transactions`, e))
      .on('mouseleave', hideTip);
  }

  function curveChart(el, series, kind) {
    const m = { top: 30, right: 16, bottom: 38, left: 46 };
    const { svg, g, w, h } = frame(el, m);
    const [kx, ky] = kind === 'roc' ? ['fpr', 'tpr'] : ['recall', 'precision'];
    const x = d3.scaleLinear().domain([0, 1]).range([0, w]);
    const y = d3.scaleLinear().domain([0, 1]).range([h, 0]);
    g.append('g').attr('class', 'grid-line').call(d3.axisLeft(y).ticks(5).tickSize(-w).tickFormat(''));
    g.append('g').attr('class', 'axis').attr('transform', `translate(0,${h})`).call(d3.axisBottom(x).ticks(5).tickFormat(d3.format('.0%')));
    g.append('g').attr('class', 'axis').call(d3.axisLeft(y).ticks(5).tickFormat(d3.format('.0%')));
    g.append('text').attr('class', 'legend').attr('x', w / 2).attr('y', h + 32).attr('text-anchor', 'middle').text(kind === 'roc' ? 'False positive rate' : 'Recall (fraud caught)');
    g.append('text').attr('class', 'legend').attr('transform', `translate(-36,${h / 2}) rotate(-90)`).attr('text-anchor', 'middle').text(kind === 'roc' ? 'True positive rate' : 'Precision (alerts that are fraud)');
    if (kind === 'roc') g.append('line').attr('x1', 0).attr('y1', h).attr('x2', w).attr('y2', 0).attr('stroke', C.slate).attr('stroke-dasharray', '4 4');
    series.forEach((s) => {
      g.append('path').datum(s.points).attr('fill', 'none').attr('stroke', s.color).attr('stroke-width', s.width || 2).attr('stroke-dasharray', s.dash || null)
        .attr('d', d3.line().x((d) => x(d[kx])).y((d) => y(d[ky])).curve(d3.curveLinear));
    });
    legend(svg, series.map((s) => ({ label: s.label, color: s.color, line: true, dash: s.dash })), m.left, 12);
  }

  function gauge(p, thr) {
    const W = 280;
    const H = 160;
    const r = 110;
    const cx = W / 2;
    const cy = 135;
    const arc = d3.arc().innerRadius(r - 20).outerRadius(r).cornerRadius(6);
    const ang = (v) => -Math.PI / 2 + Math.PI * v;
    const parts = [
      arc({ startAngle: ang(0), endAngle: ang(1) }),
      arc({ startAngle: ang(0), endAngle: ang(Math.max(p, 0.004)) }),
    ];
    const tx = cx + (r + 8) * Math.sin(ang(thr));
    const ty = cy - (r + 8) * Math.cos(ang(thr));
    return `<svg class="gauge" viewBox="0 0 ${W} ${H}">
      <g transform="translate(${cx},${cy})"><path d="${parts[0]}" fill="#1d2a46"/><path d="${parts[1]}" fill="${probColor(p)}"/></g>
      <line x1="${cx + (r - 26) * Math.sin(ang(thr))}" y1="${cy - (r - 26) * Math.cos(ang(thr))}" x2="${tx}" y2="${ty}" stroke="#e6ecf7" stroke-width="2"/>
      <text x="${tx}" y="${ty - 6}" fill="#8b9ab8" font-size="10.5" text-anchor="middle">threshold</text>
      <text x="${cx}" y="${cy - 22}" fill="#e6ecf7" font-size="34" font-weight="700" text-anchor="middle">${(p * 100).toFixed(1)}%</text>
      <text x="${cx}" y="${cy - 2}" fill="#8b9ab8" font-size="12" text-anchor="middle">fraud probability</text></svg>`;
  }

  // ---------- table ----------
  function table(el, cols, rows, { onClick, rowClass } = {}) {
    if (!rows.length) { el.innerHTML = '<p class="muted" style="text-align:center;padding:24px">No alerts match the filters.</p>'; return; }
    el.innerHTML = `<table><thead><tr>${cols.map((c) => `<th class="${c.num ? 'num' : ''}">${c.label}</th>`).join('')}</tr></thead><tbody>${rows.map((r, i) =>
      `<tr data-i="${i}" class="${onClick ? 'clickable' : ''} ${rowClass ? rowClass(r) : ''}">${cols.map((c) => `<td class="${c.num ? 'num' : ''}">${c.render ? c.render(r) : esc(r[c.key])}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
    if (onClick) el.querySelectorAll('tbody tr').forEach((tr) => tr.addEventListener('click', () => {
      el.querySelectorAll('tr.sel').forEach((x) => x.classList.remove('sel'));
      tr.classList.add('sel');
      onClick(rows[+tr.dataset.i]);
    }));
  }
  const probBar = (p) => `<span class="prob"><span class="track"><span class="fill" style="width:${p * 100}%;background:${probColor(p)}"></span></span>${(p * 100).toFixed(1)}%</span>`;

  // ---------- pages ----------
  function renderOverview(D) {
    const k = D.kpis;
    const s = D.meta.split;
    document.getElementById('period').textContent = `Performance on the ${k.days}-day test period (${d3.timeFormat('%d %b')(parseDay(s.test_start))} – ${d3.timeFormat('%d %b %Y')(parseDay(s.end))}); the model never saw these transactions during training.`;
    const cards = [
      ['Fraud amount caught', inr(k.fraud_amount_caught), `${pct(k.amount_recall, 0)} of ${inr(k.fraud_amount)} attempted`, C.green],
      ['Fraud transactions caught (recall)', pct(k.recall), `${k.true_alerts} of ${k.frauds} fraud transactions`, C.red],
      ['Alert precision', pct(k.precision), `${k.true_alerts} of ${num(k.alerts)} alerts were fraud`, C.amber],
      ['Net savings', inr(k.net_savings), `after ₹${D.meta.assumptions.review_cost}/alert review cost`, C.green],
      ['Alerts per day', k.alerts_per_day.toFixed(1), `from ${num(Math.round(k.transactions / k.days))} transactions a day`, C.blue],
      ['False positive rate', pct(k.fpr, 2), 'genuine customers interrupted', C.violet],
      ['ROC-AUC · PR-AUC', `${k.roc_auc.toFixed(3)} · ${k.pr_auc.toFixed(3)}`, 'ranking quality on unseen data', C.blue],
      ['Fraud rate', `${k.fraud_rate_pct.toFixed(2)}%`, `${num(k.transactions)} transactions monitored`, C.red],
    ];
    document.getElementById('kpis').innerHTML = cards.map(([l, v, n, c]) => `<div class="kpi" style="--c:${c}"><div class="label"><i></i>${l}</div><div class="value">${v}</div><div class="note">${n}</div></div>`).join('');
    register('ch-daily', (el) => dailyChart(el, D.daily));
    register('ch-types', (el) => hbar(el, D.model.recall_by_type, {
      value: (d) => d.recall, label: (d) => TYPE_LABEL[d.fraud_type] || d.fraud_type, color: (d) => (d.recall >= 0.8 ? C.green : d.recall >= 0.5 ? C.amber : C.red),
      format: (v) => `${Math.round(v * 100)}%`, max: 1, left: 140,
      tip: (d) => `<b>${TYPE_LABEL[d.fraud_type]}</b><br>${d.caught} of ${d.frauds} transactions caught<br>Fraud amount: ${inr(d.amount)}`,
    }));
    const cats = D.by_category.filter((d) => d.frauds > 0);
    register('ch-cat', (el) => hbar(el, cats, {
      value: (d) => d.fraud_amount, label: (d) => d.name, color: C.red, format: inr, left: 112,
      tip: (d) => `<b>${esc(d.name)}</b><br>${d.frauds} fraud transactions (${d.fraud_rate_pct}%)<br>Fraud amount: ${inr(d.fraud_amount)}<br>Caught: ${d.caught}`,
    }));
    register('ch-channel', (el) => hbar(el, D.by_channel, {
      value: (d) => d.fraud_rate_pct, label: (d) => d.name, color: C.violet, format: (v) => `${v.toFixed(2)}%`, left: 64,
      tip: (d) => `<b>${esc(d.name)}</b><br>Fraud rate ${d.fraud_rate_pct}% · ${d.frauds} frauds<br>Caught ${d.caught} (${d.recall == null ? '—' : pct(d.recall, 0)})`,
    }));
    register('ch-hour', (el) => hourChart(el, D.hourly));
  }

  let fillScorer = () => {};
  function renderAlerts(D) {
    const A = D.alerts;
    const fill = (id, vals) => vals.forEach((v) => document.getElementById(id).insertAdjacentHTML('beforeend', `<option>${esc(v)}</option>`));
    fill('f-ch', [...new Set(A.map((a) => a.channel))].sort());
    fill('f-cat', [...new Set(A.map((a) => a.category))].sort());
    const detail = document.getElementById('detail');
    function showDetail(a) {
      detail.innerHTML = `
        <div class="card-h"><h3 class="mono">${esc(a.txn_id)}</h3>${a.confirmed_fraud ? '<span class="pill fraud">Confirmed fraud</span>' : '<span class="pill legit">False positive</span>'}</div>
        <p class="muted" style="margin:0">${esc(a.time)} · ${esc(a.customer_id)} (${esc(a.segment)}, ${esc(a.home_city)})</p>
        ${gauge(a.probability, D.model.threshold)}
        <h3 style="font-size:13px;margin-top:6px">Why it was flagged</h3>
        <ul class="reasons">${(a.reasons.length ? a.reasons : ['Unusual combination of features (anomaly score)']).map((r) => `<li>${esc(r)}</li>`).join('')}</ul>
        <dl class="kv">
          <dt>Amount</dt><dd>${inrFull(a.amount)}</dd>
          <dt>Usual spend</dt><dd>${inrFull(a.usual_amount)}</dd>
          <dt>Merchant</dt><dd>${esc(a.category)} · ${esc(a.channel)}</dd>
          <dt>Location</dt><dd>${esc(a.txn_city)}</dd>
          <dt>Anomaly score</dt><dd>${a.anomaly.toFixed(3)}</dd>
          ${a.fraud_type ? `<dt>Fraud pattern</dt><dd>${esc(TYPE_LABEL[a.fraud_type] || a.fraud_type)}</dd>` : ''}
        </dl>
        <button class="btn ghost" id="rescore">Re-score this transaction live →</button>`;
      document.getElementById('rescore').addEventListener('click', () => fillScorer({ ...a.inputs, amount: a.amount, channel: a.channel, category: a.category }, true));
    }
    const cols = [
      { label: 'Transaction', render: (a) => `<span class="mono">${esc(a.txn_id)}</span><div class="sub2">${esc(a.time)}</div>` },
      { label: 'Customer', render: (a) => `${esc(a.customer_id)}<div class="sub2">${esc(a.home_city)}</div>` },
      { label: 'Merchant', render: (a) => `${esc(a.category)}<div class="sub2">${esc(a.channel)} · ${esc(a.txn_city)}</div>` },
      { label: 'Amount', num: true, render: (a) => `${inrFull(a.amount)}<div class="sub2">usual ${inr(a.usual_amount)}</div>` },
      { label: 'Fraud probability', render: (a) => probBar(a.probability) },
      { label: 'Top reason', render: (a) => `<span class="sub2" style="color:#c3cde0">${esc(a.reasons[0] || 'Anomalous pattern')}</span>` },
      { label: 'Outcome', render: (a) => (a.confirmed_fraud ? '<span class="pill fraud">Fraud</span>' : '<span class="pill legit">Genuine</span>') },
    ];
    function apply() {
      const ch = document.getElementById('f-ch').value;
      const cat = document.getElementById('f-cat').value;
      const out = document.getElementById('f-out').value;
      const q = document.getElementById('f-q').value.trim().toLowerCase();
      const rows = A.filter((a) => (!ch || a.channel === ch) && (!cat || a.category === cat)
        && (!out || (out === 'fraud') === a.confirmed_fraud) && (!q || `${a.txn_id} ${a.customer_id} ${a.txn_city} ${a.home_city}`.toLowerCase().includes(q)));
      const tp = rows.filter((a) => a.confirmed_fraud).length;
      document.getElementById('alert-count').textContent = `${rows.length} alerts · ${tp} confirmed fraud · ${rows.length - tp} false positives`;
      table(document.getElementById('tbl-alerts'), cols, rows, { onClick: showDetail });
      if (rows.length) { showDetail(rows[0]); document.querySelector('#tbl-alerts tbody tr')?.classList.add('sel'); }
    }
    ['f-ch', 'f-cat', 'f-out'].forEach((id) => document.getElementById(id).addEventListener('change', apply));
    document.getElementById('f-q').addEventListener('input', apply);
    apply();
  }

  function renderModel(D) {
    const M = D.model;
    const s = D.meta.split;
    document.getElementById('split-info').textContent = `Trained on ${num(s.train_rows)} transactions (${s.train_frauds} fraud) · tested on the next ${num(s.test_rows)} (${s.test_frauds} fraud)`;
    table(document.getElementById('tbl-models'), [
      { label: 'Model', render: (r, i) => `${esc(r.model)}${r.model.includes('final') ? ' <span class="pill final">Deployed</span>' : ''}` },
      { label: 'ROC-AUC', num: true, render: (r) => r.roc_auc.toFixed(3) },
      { label: 'PR-AUC', num: true, render: (r) => r.pr_auc.toFixed(3) },
      { label: 'Precision', num: true, render: (r) => pct(r.precision) },
      { label: 'Recall', num: true, render: (r) => pct(r.recall) },
      { label: 'Alerts', num: true, render: (r) => num(r.alerts) },
      { label: 'Fraud ₹ caught', num: true, render: (r) => inr(r.fraud_amount_caught) },
      { label: 'Net savings', num: true, render: (r) => `<b style="color:${r.net_savings >= 0 ? C.green : C.red}">${inr(r.net_savings)}</b>` },
    ], M.comparison);

    const a = D.meta.assumptions;
    document.getElementById('thr-assump').textContent = `Net savings = ${Math.round(a.recovery_rate * 100)}% of fraud ₹ caught − ₹${a.review_cost} per alert reviewed`;
    const slider = document.getElementById('thr');
    const T = M.threshold_table;
    function update() {
      const t = +slider.value;
      const r = T.reduce((best, x) => (Math.abs(x.threshold - t) < Math.abs(best.threshold - t) ? x : best), T[0]);
      document.getElementById('thr-val').textContent = r.threshold.toFixed(2);
      document.getElementById('thr-stats').innerHTML = `
        <div><b>${pct(r.recall)}</b>fraud caught</div><div><b>${pct(r.precision)}</b>alert precision</div><div><b>${num(r.alerts)}</b>alerts</div>
        <div><b>${inr(r.fraud_amount_caught)}</b>fraud ₹ caught</div><div><b>${inr(r.fraud_amount_missed)}</b>fraud ₹ missed</div>
        <div><b style="color:${r.net_savings >= 0 ? C.green : C.red}">${inr(r.net_savings)}</b>net savings</div>`;
      document.getElementById('confusion').innerHTML = `
        <div></div><div class="h">Fraud</div><div class="h">Genuine</div>
        <div class="h" style="writing-mode:vertical-rl;transform:rotate(180deg)">Alert</div><div class="c tp">${num(r.tp)}<small>caught</small></div><div class="c fp">${num(r.fp)}<small>false alarms</small></div>
        <div class="h" style="writing-mode:vertical-rl;transform:rotate(180deg)">No alert</div><div class="c fn">${num(r.fn)}<small>missed</small></div><div class="c tn">${num(r.tn)}<small>approved</small></div>`;
    }
    slider.value = M.threshold.toFixed(2);
    slider.addEventListener('input', update);
    update();

    register('ch-roc', (el) => curveChart(el, [
      { points: M.roc.final, color: C.red, label: `Deployed model (AUC ${M.comparison[3].roc_auc.toFixed(3)})`, width: 2.5 },
      { points: M.roc.iforest, color: C.blue, label: `Isolation Forest only (${M.comparison[1].roc_auc.toFixed(3)})`, dash: '5 4' },
    ], 'roc'));
    register('ch-pr', (el) => curveChart(el, [
      { points: M.pr.final, color: C.red, label: `Deployed model (AP ${M.comparison[3].pr_auc.toFixed(3)})`, width: 2.5 },
      { points: M.pr.iforest, color: C.blue, label: `Isolation Forest only (${M.comparison[1].pr_auc.toFixed(3)})`, dash: '5 4' },
    ], 'pr'));
    const imp = M.importance.filter((d) => d.importance > 0.0005).slice(0, 12);
    register('ch-imp', (el) => hbar(el, imp, {
      value: (d) => d.importance, label: (d) => FEATURE_LABEL[d.feature] || d.feature, color: (d) => (d.feature === 'anomaly_score' ? C.red : C.violet),
      format: (v) => v.toFixed(3), left: 200, tip: (d) => `<b>${FEATURE_LABEL[d.feature] || d.feature}</b><br>PR-AUC drops by ${d.importance.toFixed(3)} when shuffled`,
    }));
  }

  function renderScore(D, model) {
    const form = document.getElementById('score-form');
    const sel = form.elements.category;
    CATEGORIES.forEach((c) => sel.insertAdjacentHTML('beforeend', `<option>${esc(c)}</option>`));
    const PRESETS = {
      'Everyday grocery': { amount: 860, usual_amount: 1100, channel: 'UPI', category: 'Grocery', hour: 18, mins_since_last: 1440, txn_count_1h: 0, txn_count_24h: 1, spent_24h: 450, distance_home_km: 0, distance_last_km: 0, account_age_days: 1600 },
      'Account takeover': { amount: 18500, usual_amount: 1300, channel: 'Online', category: 'Electronics', hour: 2, mins_since_last: 12, txn_count_1h: 2, txn_count_24h: 2, spent_24h: 21000, distance_home_km: 0, distance_last_km: 0, account_age_days: 900, new_device: true, new_merchant: true },
      'Card testing': { amount: 18, usual_amount: 1200, channel: 'Online', category: 'E-commerce', hour: 21, mins_since_last: 2, txn_count_1h: 5, txn_count_24h: 5, spent_24h: 140, distance_home_km: 0, distance_last_km: 0, account_age_days: 2100, new_device: true, new_merchant: true },
      'Cloned card at ATM': { amount: 20000, usual_amount: 1500, channel: 'ATM', category: 'ATM', hour: 14, mins_since_last: 45, txn_count_1h: 1, txn_count_24h: 3, spent_24h: 2200, distance_home_km: 1150, distance_last_km: 1150, account_age_days: 3000, new_merchant: true },
      'Big TV purchase in store': { amount: 45000, usual_amount: 1500, channel: 'POS', category: 'Electronics', hour: 15, mins_since_last: 2000, txn_count_1h: 0, txn_count_24h: 0, spent_24h: 0, distance_home_km: 0, distance_last_km: 0, account_age_days: 2000, new_merchant: true },
      'Holiday spend': { amount: 1650, usual_amount: 1100, channel: 'POS', category: 'Restaurants', hour: 20, mins_since_last: 240, txn_count_1h: 0, txn_count_24h: 2, spent_24h: 2100, distance_home_km: 1150, distance_last_km: 5, account_age_days: 2500 },
    };
    const presetsEl = document.getElementById('presets');
    presetsEl.innerHTML = Object.keys(PRESETS).map((k) => `<button type="button" data-p="${esc(k)}">${esc(k)}</button>`).join('');
    const result = document.getElementById('result');

    function setForm(v) {
      ['amount', 'usual_amount', 'channel', 'category', 'hour', 'mins_since_last', 'txn_count_1h', 'txn_count_24h', 'spent_24h', 'distance_home_km', 'distance_last_km', 'account_age_days']
        .forEach((k) => { if (v[k] !== undefined) form.elements[k].value = v[k]; });
      ['new_device', 'new_merchant', 'international'].forEach((k) => { form.elements[k].checked = !!v[k]; });
    }
    function readForm() {
      const o = {};
      ['amount', 'usual_amount', 'channel', 'category', 'hour', 'mins_since_last', 'txn_count_1h', 'txn_count_24h', 'spent_24h', 'distance_home_km', 'distance_last_km', 'account_age_days']
        .forEach((k) => { o[k] = form.elements[k].value; });
      ['new_device', 'new_merchant', 'international'].forEach((k) => { o[k] = form.elements[k].checked; });
      return o;
    }
    function run() {
      const t0 = performance.now();
      const r = FraudScorer.score(model, readForm());
      const ms = performance.now() - t0;
      const alert = r.is_alert;
      result.innerHTML = `
        ${gauge(r.fraud_probability, model.threshold)}
        <div class="verdict ${alert ? 'alert' : 'ok'}">${alert ? '⚠ Hold & send to analyst' : '✔ Approve'}</div>
        <p class="muted" style="text-align:center;margin:0">Alert threshold ${(model.threshold * 100).toFixed(1)}% · scored in ${ms.toFixed(1)} ms in your browser</p>
        <div class="meta"><div><b>${r.anomaly_score.toFixed(3)}</b>anomaly score</div><div><b>${r.features.amount_ratio.toFixed(1)}×</b>usual amount</div><div><b>${Math.round(r.features.speed_kmh)} km/h</b>implied speed</div></div>
        <h3 style="font-size:13px;margin-top:10px">Risk signals</h3>
        <ul class="reasons">${r.reasons.length ? r.reasons.map((x) => `<li>${esc(x.text)}</li>`).join('') : '<li class="ok">No individual red flags; behaviour matches the customer’s usual pattern</li>'}</ul>
        <p class="muted" style="font-size:12px;margin:0">Isolation Forest (${model.isolation_forest.trees.length} trees) → Gradient Boosting (${model.gbm.trees.length} trees), exported from scikit-learn and evaluated client-side.</p>`;
    }
    presetsEl.addEventListener('click', (e) => {
      const b = e.target.closest('button[data-p]');
      if (!b) return;
      presetsEl.querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b));
      setForm({ new_device: false, new_merchant: false, international: false, ...PRESETS[b.dataset.p] });
      run();
    });
    form.addEventListener('submit', (e) => { e.preventDefault(); presetsEl.querySelectorAll('button').forEach((x) => x.classList.remove('on')); run(); });
    fillScorer = (v, go) => {
      setForm({ new_device: false, new_merchant: false, international: false, ...v });
      presetsEl.querySelectorAll('button').forEach((x) => x.classList.remove('on'));
      if (go) goTab('score');
      run();
    };
    presetsEl.querySelector('button[data-p="Account takeover"]').click();
  }

  function renderPipeline(D) {
    const P = D.pipeline;
    document.getElementById('pipe-meta').textContent = `Built ${new Date(D.meta.generated_at).toLocaleString('en-IN')} · model trained in ${D.meta.train_seconds}s`;
    const steps = [
      ['1 · Ingest', 'Transactions', `${num(P.clean.source_rows)} card, UPI, ATM & online payments for ${num(D.meta.customers)} customers`],
      ['2 · Features', '19 behavioural signals', 'Amount vs history, velocity, time since last, distance & travel speed, new device / merchant'],
      ['3 · Anomaly', 'Isolation Forest', 'Unsupervised: scores how unusual each transaction is, no labels needed'],
      ['4 · Classify', 'Gradient Boosting', 'Supervised on confirmed fraud, uses features + anomaly score'],
      ['5 · Decide', 'Cost-based threshold', 'Maximises fraud ₹ saved minus analyst review cost'],
      ['6 · Serve', 'SQL + dashboard', 'Star schema for Power BI, alert queue & live scoring in the browser'],
    ];
    document.getElementById('flow').innerHTML = steps.map(([n, t, d], i) => `${i ? '<div class="arrow">→</div>' : ''}<div class="step"><div class="n">${n}</div><h3>${t}</h3><p>${d}</p></div>`).join('');
    table(document.getElementById('tbl-rows'), [
      { label: 'Table', render: (r) => `<span class="mono">${esc(r.t)}</span>` },
      { label: 'Rows', num: true, render: (r) => num(r.n) },
    ], Object.entries(P.rows_loaded).map(([t, n]) => ({ t, n })));
    document.getElementById('qc').innerHTML = P.quality_checks.map((c) => `<li class="${c.passed ? '' : 'fail'}">${c.passed ? '✔' : '✖'} ${esc(c.check)}</li>`).join('');
  }

  // ---------- tabs ----------
  const buttons = document.querySelectorAll('.tabs button');
  function goTab(name, push = true) {
    buttons.forEach((b) => b.setAttribute('aria-selected', String(b.dataset.tab === name)));
    document.querySelectorAll('.page').forEach((p) => { p.hidden = p.id !== `tab-${name}`; });
    if (push) history.replaceState(null, '', `#${name}`);
    hideTip();
    renderVisible();
    scrollTo({ top: 0 });
  }
  buttons.forEach((b) => b.addEventListener('click', () => goTab(b.dataset.tab)));

  Promise.all([fetch('data/dashboard.json').then((r) => r.json()), fetch('model/model.json').then((r) => r.json())])
    .then(([D, model]) => {
      document.getElementById('asof').textContent = `Data as of ${d3.timeFormat('%d %b %Y')(parseDay(D.meta.data_as_of))} · ${num(D.meta.customers)} customers · ${num(D.meta.merchants)} merchants`;
      renderOverview(D);
      renderAlerts(D);
      renderModel(D);
      renderScore(D, model);
      renderPipeline(D);
      const initial = location.hash.slice(1);
      goTab([...buttons].some((b) => b.dataset.tab === initial) ? initial : 'overview', false);
      document.body.dataset.ready = 'true';
    })
    .catch((err) => {
      document.getElementById('app').innerHTML = `<div class="card">Could not load data (${esc(err.message)}). Run <code>python build.py</code> first.</div>`;
      console.error(err);
    });
})();
