(() => {
  // Every value from a feed goes through esc() before it reaches innerHTML (D-467 finding 8); the feeds passed the
  // schema at the hub first, but the page does not rely on that.
  const D = JSON.parse(document.getElementById('tb-data').textContent);
  const L = D.labels; let lang = D.lang;
  const $ = (id) => document.getElementById(id);
  const t = (k) => (L[lang] && L[lang][k]) || L.en[k] || k;
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const dash = '<span class="small">–</span>';
  const rows = D.rows;
  const num = (v) => typeof v === 'number' && Number.isFinite(v) ? v : 0;
  const maxE = Math.max(1, ...rows.map((r) => num(r.eligible_now)));
  const phases = (r) => Array.isArray(r.phases) && r.phases.length ? r.phases : ['NA'];
  function fill(sel, values) {
    const cur = sel.value; sel.innerHTML = '<option value="">' + esc(t('all')) + '</option>' +
      values.map((v) => '<option value="' + esc(v) + '">' + esc(v) + '</option>').join('');
    sel.value = values.includes(cur) ? cur : '';
  }
  function withheld(w) { return typeof w === 'number' ? String(w) : t('w.' + w); }
  function labels() {
    document.documentElement.lang = lang;
    document.querySelectorAll('[data-l]').forEach((el) => { el.textContent = t(el.dataset.l); });
    $('foot').textContent = t('rounding').replaceAll('{t}', D.threshold);
    fill($('f-cond'), [...new Set(rows.map((r) => String(r.condition)))].sort());
    fill($('f-phase'), [...new Set(rows.flatMap(phases))].map(String).sort());
    fill($('f-site'), [...new Set(rows.map((r) => String(r.site)))].sort());
    $('sites').innerHTML = D.feeds.map((f) => '<span class="chip' + (f.state === 'verified' ? '' : ' bad') + '">' +
      esc(f.site) + ' · ' + esc(t(f.state)) + ' · ' + esc(t('withheld').replaceAll('{t}', D.threshold)) + ': ' +
      esc(withheld(f.withheld)) + '</span>').join('');
  }
  function render() {
    const c = $('f-cond').value, p = $('f-phase').value, s = $('f-site').value, m = Number($('f-min').value || 0);
    const shown = rows.filter((r) => (!c || r.condition === c) && (!s || r.site === s) &&
      (!p || phases(r).includes(p)) && num(r.eligible_now) >= m)
      .sort((a, b) => num(b.eligible_now) - num(a.eligible_now) || String(a.nct_id).localeCompare(String(b.nct_id)));
    $('k-trials').textContent = new Set(rows.map((r) => r.nct_id)).size;
    $('k-ready').textContent = new Set(rows.filter((r) => num(r.eligible_now) > 0).map((r) => r.nct_id)).size;
    $('k-sites').textContent = D.feeds.length;
    $('k-updated').textContent = [...new Set(D.feeds.map((f) => [String(f.period.start), String(f.period.days) + 'd'].join(' +')))].join(', ');
    $('tbody').innerHTML = shown.map((r) => {
      const e = r.eligible_now, w = typeof e === 'number' ? Math.round(120 * e / maxE) : 0;
      const b = r.enrol_12m;
      const band = !b ? dash : (b.low === null ? esc(b.mid) :
        esc(b.low) + '–' + esc(b.high) + ' <span class="sub">(' + esc(b.mid) + ')</span>');
      const nm = Array.isArray(r.not_matched) ? r.not_matched : [];
      const ex = nm.length ? '<ul class="ex">' + nm.map((x) => '<li>' + esc(x.criterion) +
        ' <span class="sub">−' + esc(x.removed) + '</span></li>').join('') + '</ul>' : dash;
      const count = r.status === 'counted'
        ? '<div class="bar"><i style="width:' + w + 'px"></i>' + esc(e) + '</div>'
        : '<span class="small">' + esc(t(['r', r.reason].join('.'))) + '</span>';
      return '<tr><td><a class="nct" href="https://clinicaltrials.gov/study/' + encodeURIComponent(String(r.nct_id)) +
        '" target="_blank" rel="noopener">' + esc(r.nct_id) + '</a><span class="ttl">' + esc(r.title) + '</span>' +
        '<span class="sub">' + esc(r.sponsor || '') + (phases(r).length ? ' · ' + esc(phases(r).join('/')) : '') +
        ' · ' + esc(r.condition) + '</span></td>' +
        '<td>' + esc(r.site) + '</td>' +
        '<td class="num">' + count + '</td>' +
        '<td class="num">' + (r.new_per_month === null || r.new_per_month === undefined ? dash : esc(r.new_per_month)) + '</td>' +
        '<td class="num">' + band + '</td>' +
        '<td class="num">' + esc(r.target_enrollment ?? '–') + '</td>' +
        '<td class="num">' + esc(r.criteria_applied) + ' / ' + esc(r.criteria_total) + '</td><td>' + ex + '</td></tr>';
    }).join('') || '<tr><td colspan="8" class="empty">' + esc(t('none')) + '</td></tr>';
  }
  $('f-lang').value = lang;
  $('f-lang').addEventListener('change', (ev) => { lang = ev.target.value; labels(); render(); });
  ['f-cond', 'f-phase', 'f-site', 'f-min'].forEach((id) => $(id).addEventListener('input', render));
  labels(); render();
})();
