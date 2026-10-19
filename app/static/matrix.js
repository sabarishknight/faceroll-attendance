/* Shared attendance sheet renderer (admin Records + public dashboard). */
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtDate = (d, long) => {
  const x = new Date(d + 'T00:00:00');
  return long ? x.toLocaleDateString('en-IN', {weekday:'short', day:'numeric', month:'short', year:'numeric'})
              : x.toLocaleDateString('en-IN', {day:'numeric', month:'short'}) + '<br><span style="font-weight:500;color:var(--mute);font-size:11px">' + x.toLocaleDateString('en-IN', {weekday:'short'}) + '</span>';
};
const hourLabel = h => { const e = h + 1; return `${h % 12 || 12}-${e % 12 || 12} ${e < 12 ? 'AM' : 'PM'}`; };
const pctClass = p => p == null ? '' : p >= 75 ? 'g' : p >= 50 ? 'y' : 'r';

/* data = response of /matrix ; opts: {filter(fn row)->bool, onSession(id), highlight(id)} */
function renderMatrix(el, data, opts = {}) {
  opts = opts || {};
  if (!data.columns.length) {
    el.innerHTML = '<div class="empty">No classes recorded in this period yet.</div>';
    return;
  }
  const rows = data.rows.filter(r => !opts.filter || opts.filter(r));
  if (!rows.length) { el.innerHTML = '<div class="empty">No students match.</div>'; return; }
  const firstOfDate = new Set(); let idx = 0;
  data.groups.forEach(g => { firstOfDate.add(idx); idx += g.span; });
  let h = '<div class="mxwrap"><table class="mx"><thead><tr><th class="nm" rowspan="2">Student</th><th rowspan="2" style="min-width:64px">%</th>';
  h += data.groups.map(g => `<th class="d" colspan="${g.span}">${fmtDate(g.date, true)}</th>`).join('');
  h += '</tr><tr>';
  h += data.columns.map((c, i) => `<th class="t${opts.onSession ? ' link' : ''}${firstOfDate.has(i) ? ' d' : ''}" data-s="${c.session}">${esc(c.label)}</th>`).join('');
  h += '</tr></thead><tbody>';
  for (const r of rows) {
    h += `<tr class="${opts.highlight && opts.highlight(r) ? 'hl' : ''}"><td class="nm"><b>${esc(r.name)}</b><small>${esc(r.roll || '')}</small></td>`;
    h += `<td class="pc">${r.pct == null ? '-' : `<span class="pct ${pctClass(r.pct)}">${r.pct}%</span>`}</td>`;
    h += r.cells.map((v, i) => `<td class="c ${v ? 'p' : 'a'}${firstOfDate.has(i) ? ' first' : ''}">${v ? '✓' : '✗'}</td>`).join('');
    h += '</tr>';
  }
  h += '</tbody></table></div>';
  el.innerHTML = h;
  if (opts.onSession) el.querySelectorAll('th.t.link').forEach(t => t.onclick = () => opts.onSession(t.dataset.s));
}
