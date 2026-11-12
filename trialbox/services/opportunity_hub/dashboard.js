(() => {
  const D = JSON.parse(document.getElementById('tb-data').textContent);
  const L = D.labels; let lang = D.lang;
  const $ = (id) => document.getElementById(id);
  const t = (k) => (L[lang] && L[lang][k]) || L.en[k];
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const rows = D.rows;
  const num = (v) => typeof v === 'number' ? v : 0;
  const maxE = Math.max(1, ...rows.map((r) => num(r.eligible_now)));
  function fill(sel, values) {
    const cur = sel.value; sel.innerHTML = '<option value="">' + esc(t('all')) + '</option>' +
      values.map((v) => '<option>' + esc(v) + '</option>').join(''); sel.value = values.includes(cur) ? cur : '';
  }
  function labels() {
    document.documentElement.lang = lang;
    document.querySelectorAll('[data-l]').forEach((el) => { el.textContent = t(el.dataset.l); });
    $('foot').textContent = t('rounding').replaceAll('{t}', D.threshold);
    fill($('f-cond'), [...new Set(rows.map((r) => r.condition))].sort());
    fill($('f-phase'), [...new Set(rows.flatMap((r) => r.phases.length ? r.phases : ['NA']))].sort());
    fill($('f-site'), [...new Set(rows.map((r) => r.site))].sort());
    $('sites').innerHTML = D.feeds.map((f) => '<span class="chip' + (f.verified ? '' : ' bad') + '">' + esc(f.site) +
      ' · ' + esc(f.verified ? t('verified') : t('unverified')) + '</span>').join('');
  }
  function render() {
    const c = $('f-cond').value, p = $('f-phase').value, s = $('f-site').value, m = Number($('f-min').value || 0);
    const shown = rows.filter((r) => (!c || r.condition === c) && (!s || r.site === s) &&
      (!p || (r.phases.length ? r.phases : ['NA']).includes(p)) && num(r.eligible_now) >= m)
      .sort((a, b) => num(b.eligible_now) - num(a.eligible_now) || a.nct_id.localeCompare(b.nct_id));
    $('k-trials').textContent = new Set(rows.map((r) => r.nct_id)).size;
    $('k-ready').textContent = new Set(rows.filter((r) => num(r.eligible_now) > 0).map((r) => r.nct_id)).size;
    $('k-sites').textContent = D.feeds.length;
    $('k-updated').textContent = D.updated;
    $('tbody').innerHTML = shown.map((r) => {
      const e = r.eligible_now, w = typeof e === 'number' ? Math.round(120 * e / maxE) : 0;
      const band = r.enrol_12m ? r.enrol_12m.low + '–' + r.enrol_12m.high + ' <span class="sub">(' + r.enrol_12m.mid + ')</span>' : '<span class="small">–</span>';
      const ex = r.top_exclusions.length ? '<ul class="ex">' + r.top_exclusions.map((x) => '<li>' + esc(x.criterion) +
        ' <span class="sub">−' + esc(x.removed) + '</span></li>').join('') + '</ul>' : '<span class="small">–</span>';
      return '<tr><td><a class="nct" href="https://clinicaltrials.gov/study/' + esc(r.nct_id) + '" target="_blank" rel="noopener">' +
        esc(r.nct_id) + '</a><span class="ttl">' + esc(r.title) + '</span><span class="sub">' + esc(r.sponsor || '') +
        (r.phases.length ? ' · ' + esc(r.phases.join('/')) : '') + ' · ' + esc(r.condition) + '</span></td>' +
        '<td>' + esc(r.site) + '</td>' +
        '<td class="num"><div class="bar"><i style="width:' + w + 'px"></i>' + esc(e) + '</div></td>' +
        '<td class="num">' + (r.new_per_month ?? '<span class="small">–</span>') + '</td>' +
        '<td class="num">' + band + '</td>' +
        '<td class="num">' + esc(r.target_enrollment ?? '–') + '</td>' +
        '<td class="num">' + r.criteria_applied + ' / ' + r.criteria_total + '</td><td>' + ex + '</td></tr>';
    }).join('') || '<tr><td colspan="8" class="empty">' + esc(t('none')) + '</td></tr>';
  }
  $('f-lang').value = lang;
  $('f-lang').addEventListener('change', (ev) => { lang = ev.target.value; labels(); render(); });
  ['f-cond', 'f-phase', 'f-site', 'f-min'].forEach((id) => $(id).addEventListener('input', render));
  labels(); render();
})();
