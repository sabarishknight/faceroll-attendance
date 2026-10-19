/* Admin app: Take attendance / Records / Students */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const sleep = ms => new Promise(r => setTimeout(r, ms));
const pad = n => String(n).padStart(2, '0');
const todayStr = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
const HOURS = Array.from({length: 15}, (_, i) => i + 6);      // 6 AM .. 8 PM class starts

let CLASSES = [], CID = null, STUDENTS = [], DRAFT = null, RANGE = {from: '', to: ''}, RECVIEW = 'sheet';

function toast(msg, err, ms = 3500) {
  const t = $('#toast'); t.textContent = msg; t.className = 'toast' + (err ? ' err' : ''); t.style.display = 'block';
  clearTimeout(t._t); t._t = setTimeout(() => t.style.display = 'none', ms);
}
async function api(url, opt) {
  let r;
  try { r = await fetch(url, opt); } catch (e) { throw new Error('No connection - check your internet and try again'); }
  let j = null; try { j = await r.json(); } catch (e) { /* not json */ }
  if (r.status === 401 && j && j.login) { showLogin(); throw new Error('Please sign in'); }
  if (!r.ok) { const e = new Error((j && j.error) || `Server error (${r.status})`); e.data = j; e.status = r.status; throw e; }
  return j;
}
const J = (method, url, body) => api(url, {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
const cls = () => CLASSES.find(c => c.id === CID);
const initials = n => (n || '?').trim().split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase();
const slotsText = slots => [...slots].sort((a, b) => a - b).map(hourLabel).join(', ');
const hrsText = n => n === 1 ? '1 hour' : n + ' hours';

/* ------------------------------------------------------------------ login */
function showLogin() { $('#login').style.display = 'grid'; setTimeout(() => $('#pw').focus(), 50); }
$('#pwgo').onclick = async () => {
  try { await J('POST', '/api/login', {password: $('#pw').value}); $('#login').style.display = 'none'; $('#pw').value = ''; boot(); }
  catch (e) { toast(e.message, true); }
};
$('#pw').addEventListener('keydown', e => { if (e.key === 'Enter') $('#pwgo').click(); });

/* ------------------------------------------------------------------ modal */
function openModal(html) { $('#sheet').innerHTML = html; $('#modal').classList.add('on'); }
function closeModal() { $('#modal').classList.remove('on'); }
$('#modal').addEventListener('click', e => { if (e.target.id === 'modal') closeModal(); });

/* ------------------------------------------------------------------- boot */
async function boot() {
  const me = await api('/api/me');
  if (me.login_required && !me.authed) { showLogin(); return; }
  await loadClasses();
  route();
}
async function loadClasses(select) {
  CLASSES = await api('/api/classes');
  const saved = select || localStorage.getItem('cid');
  CID = CLASSES.some(c => c.id === saved) ? saved : CLASSES[0].id;
  localStorage.setItem('cid', CID);
  $('#classSel').innerHTML = CLASSES.map(c => `<option value="${c.id}" ${c.id === CID ? 'selected' : ''}>${esc(c.name)}</option>`).join('') + '<option value="__new">＋ New class…</option>';
}
$('#classSel').onchange = e => {
  if (e.target.value === '__new') { e.target.value = CID; newClassModal(); return; }
  CID = e.target.value; localStorage.setItem('cid', CID); DRAFT = null; STUDENTS = []; route();
};
$('#shareBtn').onclick = shareModal;
$('#setBtn').onclick = () => settingsModal();

async function loadStudents() { STUDENTS = await api(`/api/classes/${CID}/students`); }

/* ----------------------------------------------------------------- router */
window.addEventListener('hashchange', route);
async function route() {
  if (!CID) return;
  const h = location.hash || '#/';
  const tab = h.startsWith('#/records') || h.startsWith('#/session') ? 'records' : h.startsWith('#/students') ? 'students' : 'attend';
  $$('.tab').forEach(t => t.classList.toggle('on', t.dataset.t === tab));
  window.scrollTo(0, 0);
  try {
    if (h.startsWith('#/session/')) await viewSession(h.split('/')[2]);
    else if (tab === 'records') await viewRecords();
    else if (tab === 'students') await viewStudents();
    else await viewAttend();
  } catch (e) { if (e.message !== 'Please sign in') $('#view').innerHTML = `<div class="card empty">${esc(e.message)}</div>`; }
}

/* ================================================================ EDITOR ==
   One component used for "Take attendance" (new) and for editing a saved record. */
function newDraft() {
  const h = new Date().getHours();
  return {id: null, date: todayStr(), slots: HOURS.includes(h) ? [h] : [], base: {}, manual: {}, photos: [], started: false, filter: 'all', q: ''};
}
const NN = d => d.slots.length;
function getMarks(d) {
  const N = NN(d), auto = new Set();
  d.photos.forEach(p => p.state === 'done' && Object.keys(p.matches || {}).forEach(s => auto.add(s)));
  const m = {};
  STUDENTS.forEach(s => {
    m[s.id] = s.id in d.manual ? Math.min(d.manual[s.id], N) : Math.max(Math.min(d.base[s.id] || 0, N), auto.has(s.id) ? N : 0);
  });
  return m;
}
function setSlots(d, slots) {
  const oldN = NN(d), N = slots.length;
  const fix = v => v === 0 ? 0 : (v === oldN ? N : Math.min(v, N));
  for (const k in d.base) d.base[k] = fix(d.base[k]);
  for (const k in d.manual) d.manual[k] = fix(d.manual[k]);
  d.slots = slots;
}

function mountEditor(box, d, mode) {
  const isNew = mode === 'new';
  box.innerHTML = `
  <section class="card">
    <h2>${isNew ? '<span class="num">1</span>' : ''}Class date &amp; time</h2>
    <div class="row" style="margin-top:10px"><div class="field" style="max-width:260px"><label class="lab" style="margin-top:0">Date</label><input type="date" id="dDate"></div></div>
    <div class="lab">Hour(s) of the class <span class="hint" style="font-weight:400">- tap more than one if the class ran longer</span></div>
    <div class="chips" id="dHours"></div>
    <div class="hint" id="dSum" style="margin-top:8px"></div>
  </section>
  <section class="card">
    <h2>${isNew ? '<span class="num">2</span>' : ''}${isNew ? 'Class photos' : 'Photos'}</h2>
    <p class="hint" style="margin:4px 0 0">${isNew ? 'Tip: for the clearest faces, take one row at a time. Add as many photos as you need - everyone found is combined.' : 'You can add more photos to find students that were missed.'}</p>
    <div class="photobtns">
      <label class="bigbtn primary"><input type="file" accept="image/*" capture="environment" hidden id="fCam"><span class="ic">📷</span>Take photo<small>open camera</small></label>
      <label class="bigbtn"><input type="file" accept="image/*" multiple hidden id="fUp"><span class="ic">🖼️</span>Upload photos<small>choose one or many</small></label>
    </div>
    <div class="strip hide" id="dStrip"></div>
    <details id="dView" class="hide" style="margin-top:10px"><summary class="link">View photos with faces marked</summary><div id="dCanv" class="stack" style="margin-top:10px"></div></details>
    ${isNew ? '<div style="margin-top:10px"><button class="link" id="dManual">Skip photos - mark manually</button></div>' : ''}
  </section>
  <section class="card hide" id="dReview">
    <h2>${isNew ? '<span class="num">3</span>' : ''}Review &amp; save</h2>
    <div class="pills" id="dPills" style="margin-top:10px"></div>
    <div class="row" style="margin-top:12px"><input type="text" id="dQ" placeholder="Search name or roll no." style="max-width:340px"></div>
    <div class="hint small" id="dLegend" style="margin:10px 0"></div>
    <div id="dRows"></div>
    <details id="dUnk" class="hide" style="margin-top:14px"><summary class="link" id="dUnkT"></summary><div class="faces" id="dFaces"></div></details>
    <div id="dMsg"></div>
    <div class="savebar">
      <div class="grow"><b id="dSumBar"></b><div class="hint small" id="dSumSub"></div></div>
      <button class="btn primary" id="dSave">${isNew ? 'Save attendance' : 'Save changes'}</button>
    </div>
  </section>
  ${isNew ? '' : '<div style="text-align:center"><button class="btn danger" id="dDelete">Delete this record</button></div>'}`;

  const ed = {box, d, mode};
  $('#dDate', box).value = d.date;
  $('#dDate', box).onchange = e => { d.date = e.target.value; };
  renderHours(ed);
  const upload = async files => { for (const f of files) await addPhoto(ed, f); };
  $('#fCam', box).onchange = e => { const fs = [...e.target.files]; e.target.value = ''; upload(fs); };
  $('#fUp', box).onchange = e => { const fs = [...e.target.files]; e.target.value = ''; upload(fs); };
  if ($('#dManual', box)) $('#dManual', box).onclick = () => { d.started = true; renderAll(ed); $('#dReview', box).scrollIntoView({behavior: 'smooth'}); };
  $('#dQ', box).oninput = e => { d.q = e.target.value.toLowerCase(); renderRows(ed); };
  $('#dRows', box).onclick = e => {
    const b = e.target.closest('[data-k]'); if (!b) return;
    d.manual[b.dataset.sid] = +b.dataset.k; renderRows(ed); renderPills(ed);
  };
  $('#dSave', box).onclick = () => saveEditor(ed);
  if ($('#dDelete', box)) $('#dDelete', box).onclick = async () => {
    if (!confirm('Delete this attendance record? This cannot be undone.')) return;
    await api(`/api/classes/${CID}/sessions/${d.id}`, {method: 'DELETE'}); toast('Record deleted'); location.hash = '#/records';
  };
  $('#dView', box).ontoggle = () => { if ($('#dView', box).open) drawPhotos(ed); };
  renderAll(ed);
  return ed;
}

function renderAll(ed) { renderHours(ed); renderStrip(ed); renderPills(ed); renderRows(ed); renderUnknown(ed); }

function renderHours(ed) {
  const {box, d} = ed;
  $('#dHours', box).innerHTML = HOURS.map(h => `<div class="chip ${d.slots.includes(h) ? 'on' : ''}" data-h="${h}">${hourLabel(h)}</div>`).join('');
  $$('.chip', box).forEach(c => c.onclick = () => {
    const h = +c.dataset.h, s = d.slots.includes(h) ? d.slots.filter(x => x !== h) : [...d.slots, h].sort((a, b) => a - b);
    setSlots(d, s); renderHours(ed); renderPills(ed); renderRows(ed);
  });
  const N = NN(d);
  $('#dSum', box).innerHTML = N ? `<b>${hrsText(N)}</b> selected: ${esc(slotsText(d.slots))}` : '<span style="color:var(--bad)">Pick at least one hour</span>';
}

function renderStrip(ed) {
  const {box, d} = ed;
  const strip = $('#dStrip', box);
  strip.classList.toggle('hide', !d.photos.length);
  strip.innerHTML = d.photos.map((p, i) => `<div class="ph ${p.state === 'busy' ? 'busy' : ''}">
    <img src="${p.thumb || ''}" alt="">${p.state === 'busy' ? '<div class="spin"></div>' : ''}
    <button class="x" data-i="${i}" title="Remove photo">✕</button>
    <div class="cap">${p.state === 'busy' ? 'Scanning carefully… (up to a minute)' : p.state === 'error' ? `<span style="color:var(--bad)">${esc(p.err)}</span>` :
      `${p.faces.length} faces · ${p.pid ? p.faces.filter(f => f.sid).length : Object.keys(p.matches || {}).length} matched${p.low_res ? ' · <span style="color:var(--warn)">low resolution</span>' : ''}`}</div></div>`).join('');
  $$('.x', strip).forEach(b => b.onclick = () => { d.photos.splice(+b.dataset.i, 1); renderAll(ed); });
  $('#dView', box).classList.toggle('hide', !d.photos.some(p => p.state === 'done'));
  if ($('#dView', box).open) drawPhotos(ed);
}

function loadImg(src) { return new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = src; }); }

async function addPhoto(ed, file) {
  const {d} = ed;
  const ph = {state: 'busy', thumb: URL.createObjectURL(file), matches: {}, faces: [], w: 0, h: 0, image: null, img: null};
  d.photos.push(ph); d.started = true; renderAll(ed);
  $('#dReview', ed.box).scrollIntoView({behavior: 'smooth', block: 'nearest'});
  try {
    const fd = new FormData(); fd.append('image', file, file.name || 'photo.jpg');
    const r = await api(`/api/classes/${CID}/analyze`, {method: 'POST', body: fd});
    ph.image = r.image; ph.thumb = r.image; ph.w = r.w; ph.h = r.h; ph.faces = r.faces; ph.matches = r.matches; ph.gallery = r.gallery;
    ph.img = await loadImg(r.image); ph.state = 'done'; ph.low_res = r.low_res; ph.src = r.src;
    if (r.low_res) toast(`This photo is only ${r.src[0]}×${r.src[1]} px, so small back-row faces may be missed. Use the original photo from the camera (not a WhatsApp or screenshot copy).`, true, 9000);
    if (!r.gallery) toast('No students have scanned their face yet - share the scan link from the Share button', true, 6000);
  } catch (e) { ph.state = 'error'; ph.err = e.message; }
  renderAll(ed);
}

function faceCrop(ph, bbox) {
  const [x1, y1, x2, y2] = bbox, w = x2 - x1, h = y2 - y1, m = .25;
  const sx = Math.max(0, x1 - w * m), sy = Math.max(0, y1 - h * m), sw = Math.min(ph.img.width - sx, w * (1 + 2 * m)), sh = Math.min(ph.img.height - sy, h * (1 + 2 * m));
  const c = document.createElement('canvas'); c.width = c.height = 80;
  c.getContext('2d').drawImage(ph.img, sx, sy, sw, sh, 0, 0, 80, 80);
  return c.toDataURL('image/jpeg', .8);
}

function stateOf(m, N) { return !N ? 'none' : m >= N ? 'full' : m > 0 ? 'part' : 'none'; }

function renderPills(ed) {
  const {box, d} = ed;
  $('#dReview', box).classList.toggle('hide', !d.started);
  if (!d.started) return;
  const N = NN(d), marks = getMarks(d);
  let full = 0, late = 0, absent = 0, check = 0;
  STUDENTS.forEach(s => {
    const m = marks[s.id]; if (N && m >= N) full++; else if (m > 0) late++; else absent++;
    if (d.photos.some(p => p.matches && p.matches[s.id] && p.matches[s.id].status === 'check') && !(s.id in d.manual)) check++;
  });
  const f = d.filter;
  $('#dPills', box).innerHTML =
    `<button class="pill btnlike ${f === 'all' ? 'on' : ''}" data-f="all">All ${STUDENTS.length}</button>` +
    `<button class="pill btnlike ok ${f === 'present' ? 'on' : ''}" data-f="present">Present ${full + late}</button>` +
    (N > 1 ? `<button class="pill btnlike warn ${f === 'late' ? 'on' : ''}" data-f="late">Late ${late}</button>` : '') +
    `<button class="pill btnlike bad ${f === 'absent' ? 'on' : ''}" data-f="absent">Absent ${absent}</button>` +
    (check ? `<button class="pill btnlike warn ${f === 'check' ? 'on' : ''}" data-f="check">Please check ${check}</button>` : '');
  $$('#dPills .pill', box).forEach(b => b.onclick = () => { d.filter = b.dataset.f; renderPills(ed); renderRows(ed); });
  $('#dLegend', box).textContent = !N ? 'Pick the class hour above first.' : N === 1 ? 'Tap Present or Absent for each student.' :
    `Tap the number of hours each student attended (${N} = the whole class). Choose ${N - 1} for someone who came 1 hour late.`;
  $('#dSumBar', box).textContent = `${full + late} of ${STUDENTS.length} present`;
  $('#dSumSub', box).textContent = `${fmtDate(d.date, true)} · ${N ? slotsText(d.slots) : 'no hour selected'}`;
}

function renderRows(ed) {
  const {box, d} = ed;
  if (!d.started) return;
  const N = NN(d), marks = getMarks(d);
  if (!STUDENTS.length) { $('#dRows', box).innerHTML = '<div class="empty">No students in this class yet. Add them in the Students tab.</div>'; return; }
  const list = STUDENTS.filter(s => {
    if (d.q && !(s.name.toLowerCase().includes(d.q) || (s.roll || '').toLowerCase().includes(d.q))) return false;
    const m = marks[s.id];
    if (d.filter === 'present') return m > 0;
    if (d.filter === 'absent') return m === 0;
    if (d.filter === 'late') return m > 0 && m < N;
    if (d.filter === 'check') return d.photos.some(p => p.matches && p.matches[s.id] && p.matches[s.id].status === 'check') && !(s.id in d.manual);
    return true;
  });
  $('#dRows', box).innerHTML = list.map(s => {
    const m = marks[s.id], st = stateOf(m, N);
    const chk = d.photos.find(p => p.matches && p.matches[s.id] && p.matches[s.id].status === 'check') && !(s.id in d.manual);
    let seen = '';
    if (chk) {
      const p = d.photos.find(p => p.matches && p.matches[s.id] && p.img);
      const f = p && p.faces.find(f => f.sid === s.id);
      if (f) seen = `<img class="av" src="${faceCrop(p, f.bbox)}" title="Face found in the photo" style="border:2px solid #f59e0b">`;
    }
    let ctl = '';
    if (!N) ctl = '<span class="hint small">pick hour</span>';
    else if (N === 1) ctl = `<div class="step two"><button data-sid="${s.id}" data-k="0" class="${m === 0 ? 'on zero' : ''}">✗ Absent</button><button data-sid="${s.id}" data-k="1" class="${m === 1 ? 'on' : ''}">✓ Present</button></div>`;
    else ctl = '<div class="step">' + Array.from({length: N + 1}, (_, k) => `<button data-sid="${s.id}" data-k="${k}" class="${m === k ? 'on ' + (k === 0 ? 'zero' : k === N ? '' : 'mid') : ''}" title="${k} of ${N} hours">${k}</button>`).join('') + '</div>';
    return `<div class="srow ${st}">
      ${s.thumb ? `<img class="av" src="${s.thumb}" alt="">` : `<div class="av">${esc(initials(s.name))}</div>`}${seen}
      <div class="sinfo"><div class="sname">${esc(s.name)}${chk ? '<span class="badge">Check</span>' : ''}</div><div class="sroll">${esc(s.roll || '')}</div></div>${ctl}</div>`;
  }).join('') || '<div class="empty">Nobody here.</div>';
}

function renderUnknown(ed) {
  const {box, d} = ed;
  const items = [];
  d.photos.forEach((p, pi) => { if (p.state === 'done' && p.img) p.faces.forEach((f, fi) => { if (!f.sid) items.push({p, pi, fi, f}); }); });
  const det = $('#dUnk', box);
  det.classList.toggle('hide', !items.length);
  if (!items.length) return;
  $('#dUnkT', box).textContent = `Faces not matched to anyone (${items.length}) - tap to assign`;
  const absent = STUDENTS.filter(s => getMarks(d)[s.id] === 0);
  $('#dFaces', box).innerHTML = items.map(it => `<div class="f"><img src="${faceCrop(it.p, it.f.bbox)}" alt="">
    <select data-p="${it.pi}" data-f="${it.fi}"><option value="">Assign to…</option>${absent.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('')}</select></div>`).join('');
  $$('#dFaces select', box).forEach(sel => sel.onchange = () => {
    if (!sel.value) return;
    const f = d.photos[+sel.dataset.p].faces[+sel.dataset.f]; f.sid = sel.value; f.status = 'manual';
    d.manual[sel.value] = NN(d) || 1; renderAll(ed);
  });
}

function drawPhotos(ed) {
  const {box, d} = ed, marks = getMarks(d), N = NN(d), names = Object.fromEntries(STUDENTS.map(s => [s.id, s.name]));
  const wrap = $('#dCanv', box); wrap.innerHTML = '';
  d.photos.forEach(async p => {
    if (p.state !== 'done' && !p.url) return;
    if (!p.img) { try { p.img = await loadImg(p.url); } catch (e) { return; } }
    const c = document.createElement('canvas'); c.className = 'photo'; c.width = p.img.width; c.height = p.img.height; wrap.appendChild(c);
    const x = c.getContext('2d'); x.drawImage(p.img, 0, 0);
    const fs = Math.max(12, Math.round(c.width / 80)), lw = Math.max(2, Math.round(c.width / 600));
    p.faces.forEach(f => {
      const [x1, y1, x2, y2] = f.bbox, m = f.sid ? (marks[f.sid] ?? 0) : 0;
      const col = !f.sid ? '#ef4444' : m >= N ? '#22c55e' : m > 0 ? '#f59e0b' : '#ef4444';
      x.lineWidth = lw; x.strokeStyle = col; x.strokeRect(x1, y1, x2 - x1, y2 - y1);
      if (f.sid && names[f.sid]) {
        const t = names[f.sid].split(' ')[0]; x.font = `700 ${fs}px sans-serif`; const w = x.measureText(t).width + 8;
        x.fillStyle = col; x.fillRect(x1, y1 - fs - 6, w, fs + 6); x.fillStyle = '#fff'; x.fillText(t, x1 + 4, y1 - 5);
      }
    });
  });
}

async function saveEditor(ed) {
  const {d, box, mode} = ed, N = NN(d);
  if (!N) { toast('Pick at least one hour for the class', true); $('#dHours', box).scrollIntoView({behavior: 'smooth'}); return; }
  if (!d.date) { toast('Pick the class date', true); return; }
  if (d.photos.some(p => p.state === 'busy')) { toast('Please wait - photos are still being checked'); return; }
  const marks = getMarks(d);
  const body = {date: d.date, slots: d.slots, marks, photos: d.photos.filter(p => p.state === 'done' || p.pid).map(p => p.pid ? {pid: p.pid} :
    {image: p.image, w: p.w, h: p.h, faces: p.faces.map(f => ({bbox: f.bbox, sid: f.sid, sim: f.sim, status: f.status}))})};
  const btn = $('#dSave', box); btn.disabled = true; btn.textContent = 'Saving…';
  $('#dMsg', box).innerHTML = '';
  try {
    const r = mode === 'new' ? await J('POST', `/api/classes/${CID}/sessions`, body) : await J('PUT', `/api/classes/${CID}/sessions/${d.id}`, body);
    if (mode === 'new') {
      DRAFT = newDraft();
      const present = r.present;
      await viewAttend(`<div class="card" style="border-color:var(--ok-line);background:var(--ok-bg)"><b style="color:var(--ok)">✓ Attendance saved</b>
        <div>${esc(fmtDate(r.date, true))} · ${esc(slotsText(r.slots))} · ${present} of ${STUDENTS.length} present</div>
        <div style="margin-top:8px"><a class="btn sm" href="#/session/${r.id}">View / edit this record</a> <a class="btn sm" href="#/records">All records</a></div></div>`);
      window.scrollTo(0, 0);
    } else { toast('Changes saved ✓'); location.hash = '#/records'; }
  } catch (e) {
    btn.disabled = false; btn.textContent = mode === 'new' ? 'Save attendance' : 'Save changes';
    if (e.status === 409 && e.data && e.data.session_id) {
      $('#dMsg', box).innerHTML = `<div class="card" style="margin-top:12px;border-color:var(--warn-line);background:var(--warn-bg)">${esc(e.message)}<div style="margin-top:8px"><a class="btn sm" href="#/session/${e.data.session_id}">Open that record</a></div></div>`;
    } else toast(e.message, true, 6000);
  }
}

/* ============================================================ ATTENDANCE == */
async function viewAttend(banner) {
  await loadStudents();
  if (!DRAFT) DRAFT = newDraft();
  $('#view').innerHTML = `<div class="stack">${banner || ''}<div class="stack" id="ed"></div></div>`;
  mountEditor($('#ed'), DRAFT, 'new');
}

/* =============================================================== SESSION == */
async function viewSession(id) {
  await loadStudents();
  const s = await api(`/api/classes/${CID}/sessions/${id}`);
  const d = {id, date: s.date, slots: s.slots, base: {...s.marks}, manual: {}, started: true, filter: 'all', q: '',
    photos: s.photos.map(p => ({pid: p.pid, state: 'done', thumb: p.url, url: p.url, w: p.w, h: p.h, faces: p.faces, matches: {}, img: null}))};
  $('#view').innerHTML = `<div class="stack"><div class="row"><a class="btn sm" href="#/records">← Records</a><h2 class="grow">Edit attendance record</h2></div><div class="stack" id="ed"></div></div>`;
  const ed = mountEditor($('#ed'), d, 'edit');
  Promise.all(d.photos.map(async p => { try { p.img = await loadImg(p.url); } catch (e) {} })).then(() => renderAll(ed));
}

/* ================================================================ RECORDS == */
function presetRange(kind) {
  const t = new Date(), iso = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  if (kind === 'month') RANGE = {from: iso(new Date(t.getFullYear(), t.getMonth(), 1)), to: iso(t)};
  else if (kind === '30') { const f = new Date(t); f.setDate(f.getDate() - 29); RANGE = {from: iso(f), to: iso(t)}; }
  else RANGE = {from: '', to: ''};
}
const qs = () => { const p = new URLSearchParams(); if (RANGE.from) p.set('from', RANGE.from); if (RANGE.to) p.set('to', RANGE.to); const s = p.toString(); return s ? '?' + s : ''; };

async function viewRecords() {
  $('#view').innerHTML = `<div class="stack">
    <section class="card">
      <div class="row">
        <div class="field"><label class="lab" style="margin-top:0">From</label><input type="date" id="rFrom" value="${RANGE.from}"></div>
        <div class="field"><label class="lab" style="margin-top:0">To</label><input type="date" id="rTo" value="${RANGE.to}"></div>
      </div>
      <div class="row" style="margin-top:10px">
        <button class="pill btnlike" data-p="all">All dates</button><button class="pill btnlike" data-p="month">This month</button><button class="pill btnlike" data-p="30">Last 30 days</button>
        <span class="grow"></span>
        <button class="btn primary" id="rExport">⬇ Export to Excel</button>
      </div>
    </section>
    <div class="tiles" id="rTiles"></div>
    <div class="row"><div class="seg"><button data-v="sheet" class="${RECVIEW === 'sheet' ? 'on' : ''}">Attendance sheet</button><button data-v="list" class="${RECVIEW === 'list' ? 'on' : ''}">Classes taken</button></div>
      <span class="hint small" id="rHint"></span></div>
    <div id="rBody"></div></div>`;
  const reload = () => viewRecordsData();
  $('#rFrom').onchange = e => { RANGE.from = e.target.value; reload(); };
  $('#rTo').onchange = e => { RANGE.to = e.target.value; reload(); };
  $$('[data-p]').forEach(b => b.onclick = () => { presetRange(b.dataset.p); $('#rFrom').value = RANGE.from; $('#rTo').value = RANGE.to; reload(); });
  $$('.seg [data-v]').forEach(b => b.onclick = () => { RECVIEW = b.dataset.v; $$('.seg [data-v]').forEach(x => x.classList.toggle('on', x === b)); viewRecordsData(); });
  $('#rExport').onclick = () => { location.href = `/api/classes/${CID}/export.xlsx${qs()}`; };
  await viewRecordsData();
}
async function viewRecordsData() {
  const m = await api(`/api/classes/${CID}/matrix${qs()}`);
  const s = m.summary;
  $('#rTiles').innerHTML = `<div class="tile"><b>${s.sessions}</b><span>Classes taken</span></div><div class="tile"><b>${s.hours}</b><span>Class hours</span></div>
    <div class="tile"><b>${s.avg == null ? '-' : s.avg + '%'}</b><span>Average attendance</span></div><div class="tile"><b>${s.below75}</b><span>Students below 75%</span></div>`;
  if (RECVIEW === 'sheet') {
    $('#rHint').textContent = 'Scroll sideways to see all days. Tap a time heading to open that class.';
    renderMatrix($('#rBody'), m, {onSession: id => location.hash = '#/session/' + id});
  } else {
    $('#rHint').textContent = '';
    const list = (await api(`/api/classes/${CID}/sessions`)).filter(x => (!RANGE.from || x.date >= RANGE.from) && (!RANGE.to || x.date <= RANGE.to)).reverse();
    $('#rBody').innerHTML = list.length ? list.map(x => `<div class="sess" data-id="${x.id}"><div class="grow"><div class="dt">${esc(fmtDate(x.date, true))}</div>
      <div class="hint small">${esc(slotsText(x.slots))} · ${hrsText(x.slots.length)}</div></div>
      <div class="cnt">${x.present}/${x.total}<small>present</small></div><span style="color:var(--accent);font-weight:700">Open ›</span></div>`).join('')
      : '<div class="card empty">No classes recorded in this period.</div>';
    $$('.sess').forEach(r => r.onclick = () => location.hash = '#/session/' + r.dataset.id);
  }
}

/* =============================================================== STUDENTS == */
let ADD = {tab: 'paste', rows: []};

function parsePasted(text) {
  let lines = text.replace(/\r/g, '').split('\n').map(l => l.trim()).filter(Boolean);
  let rows = lines.map(l => l.includes('\t') ? l.split('\t') : l.includes(',') ? l.split(',') : l.includes(';') ? l.split(';') :
    (m => m ? [m[1], m[2]] : [l, ''])(l.match(/^(.*\S)\s+(\S*\d\S*)$/))).map(r => r.map(c => c.trim()));
  const head = (rows[0] || []).join(' ').toLowerCase();
  let ni = 0, ri = 1;
  if (/name|roll|reg/.test(head) && !rows[0].some(c => /^\d+$/.test(c))) {
    rows[0].forEach((c, i) => { const l = c.toLowerCase(); if (l.includes('name')) ni = i; else if (/roll|reg|\bid\b|\bno\b/.test(l)) ri = i; });
    rows = rows.slice(1);
  } else {
    const sample = rows.slice(0, 10), isNum = c => /\d/.test(c || '') && !/[A-Za-z]{3,}/.test(c || '');
    if (sample.length && sample.filter(r => isNum(r[0]) && /[A-Za-z]{3,}/.test(r[1] || '')).length >= sample.length * .6) { ni = 1; ri = 0; }
  }
  return rows.map(r => ({name: (r[ni] || '').trim(), roll: (r[ri] || '').trim()})).filter(r => r.name);
}

async function viewStudents() {
  await loadStudents();
  const others = CLASSES.filter(c => c.id !== CID);
  const scanned = STUDENTS.filter(s => s.scanned).length;
  $('#view').innerHTML = `<div class="stack">
    <section class="card">
      <h2>${esc(cls().name)}</h2><div class="hint" style="margin:2px 0 12px">${STUDENTS.length} students · ${scanned} face scans done${STUDENTS.length - scanned ? ` · <b style="color:var(--warn)">${STUDENTS.length - scanned} still to scan</b>` : ''}</div>
      <button class="btn primary" id="sShare" style="width:100%">Share face-scan link with students</button>
    </section>
    <section class="card">
      <h2>Add students</h2>
      <div class="seg full" style="margin-top:10px"><button data-t="paste" class="on">Paste from Excel</button><button data-t="file">Upload file</button><button data-t="one">Add one</button></div>
      <div id="aBody" style="margin-top:12px"></div>
      <div id="aPrev"></div>
    </section>
    ${others.length ? `<section class="card"><h2>Copy students from another class</h2><p class="hint" style="margin:4px 0 0">Copies names, roll numbers and face scans. Changes you make here will not affect the other class.</p>
      <div class="row" style="margin-top:10px"><select id="cpSrc" style="max-width:300px">${others.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select>
      <label class="row small"><input type="checkbox" id="cpFaces" checked> include face scans</label><button class="btn" id="cpGo">Copy students</button></div></section>` : ''}
    <section class="card"><h2>Student list</h2>
      <div id="sList" style="margin-top:6px"></div>
      ${STUDENTS.length ? '' : '<div class="empty">No students yet. Paste or upload your class list above.</div>'}
    </section>
    <section class="card"><h2>Class settings</h2><p class="hint" style="margin:4px 0 10px">Rename the class, matching strictness, reset scans, import old scans, change password, delete the class.</p>
      <button class="btn" id="sSet">⚙ Edit class &amp; settings</button></section></div>`;
  renderStudentRows();
  $('#sShare').onclick = shareModal;
  $$('.seg [data-t]').forEach(b => b.onclick = () => { ADD.tab = b.dataset.t; ADD.rows = []; $$('.seg [data-t]').forEach(x => x.classList.toggle('on', x === b)); renderAddTab(); });
  renderAddTab();
  if ($('#cpGo')) $('#cpGo').onclick = async () => {
    try { const r = await J('POST', `/api/classes/${CID}/copy-from`, {source: $('#cpSrc').value, with_faces: $('#cpFaces').checked}); toast(`${r.copied} students copied ✓`); viewStudents(); }
    catch (e) { toast(e.message, true); }
  };
  $('#sSet').onclick = () => settingsModal();
}

function renderStudentRows() {
  $('#sList').innerHTML = STUDENTS.map(s => `<div class="strow" data-id="${s.id}">
    <input class="ri" type="text" data-f="roll" value="${esc(s.roll)}" placeholder="Roll" aria-label="Roll number"><input class="ni" type="text" data-f="name" value="${esc(s.name)}" aria-label="Name">
    <div class="meta">${s.scanned ? `${s.thumb ? `<img class="av" style="width:34px;height:34px" src="${s.thumb}">` : ''}<span class="tag ok">Face scanned</span>` : '<span class="tag no">Not scanned yet</span>'}
    <span class="grow"></span><label class="btn sm" title="Set this student's face from ordinary photos (ID card, selfies)">📷 ${s.scanned ? 'Add' : 'From'} photo<input type="file" accept="image/*" multiple hidden data-a="photo"></label>${s.scanned ? '<button class="btn sm" data-a="clear" title="Remove the saved face so the student can scan again">Reset scan</button>' : ''}<button class="btn sm danger" data-a="del">Remove</button></div></div>`).join('');
  $$('#sList input[data-a=photo]').forEach(inp => inp.onchange = async () => {
    const id = inp.closest('.strow').dataset.id, fs = [...inp.files]; inp.value = ''; if (!fs.length) return;
    const fd = new FormData(); fs.forEach(f => fd.append('image', f));
    toast('Reading face from photo…', false, 20000);
    try { const r = await api(`/api/classes/${CID}/students/${id}/face-photos`, {method: 'POST', body: fd}); toast(r.warning || 'Face saved ✓', !!r.warning, r.warning ? 7000 : 2500); viewStudents(); }
    catch (e) { toast(e.message, true, 6000); }
  });
  $$('#sList input[data-f]').forEach(i => i.onchange = async () => {
    const id = i.closest('.strow').dataset.id;
    try { await J('PATCH', `/api/classes/${CID}/students/${id}`, {[i.dataset.f]: i.value}); toast('Saved ✓', false, 1200); const s = STUDENTS.find(x => x.id === id); s[i.dataset.f] = i.value; }
    catch (e) { toast(e.message, true); }
  });
  $$('#sList button[data-a]').forEach(b => b.onclick = async () => {
    const tr = b.closest('.strow'), id = tr.dataset.id, nm = STUDENTS.find(x => x.id === id).name;
    if (b.dataset.a === 'del') { if (!confirm(`Remove ${nm} from this class?`)) return; await api(`/api/classes/${CID}/students/${id}`, {method: 'DELETE'}); }
    else { if (!confirm(`Reset ${nm}'s face scan? They will need to scan again.`)) return; await J('POST', `/api/classes/${CID}/students/${id}/clear-face`); }
    viewStudents();
  });
}

function renderAddTab() {
  const b = $('#aBody'); $('#aPrev').innerHTML = '';
  if (ADD.tab === 'paste') {
    b.innerHTML = `<p class="hint" style="margin:0 0 8px">Copy two columns from Excel - <b>Name</b> then <b>Roll number</b> - and paste below. Up to 500 rows at once.</p>
      <textarea id="aTxt" placeholder="Aisha Khan&#9;1&#10;Rahul Verma&#9;2&#10;…"></textarea>`;
    $('#aTxt').oninput = e => { ADD.rows = parsePasted(e.target.value); renderPreview(); };
  } else if (ADD.tab === 'file') {
    b.innerHTML = `<p class="hint" style="margin:0 0 8px">Upload an Excel (.xlsx) or .csv file with a Name column and a Roll No column. <a href="/api/students-template.xlsx">Download the template</a></p>
      <input type="file" id="aFile" accept=".xlsx,.xlsm,.csv,text/csv">`;
    $('#aFile').onchange = async e => {
      const f = e.target.files[0]; if (!f) return;
      const fd = new FormData(); fd.append('file', f);
      try { const r = await api(`/api/classes/${CID}/students/parse-file`, {method: 'POST', body: fd}); ADD.rows = r.rows; renderPreview(); } catch (er) { toast(er.message, true, 6000); }
    };
  } else {
    b.innerHTML = `<div class="row"><div class="field"><input type="text" id="o1" placeholder="Name"></div><div class="field" style="max-width:150px"><input type="text" id="o2" placeholder="Roll no."></div><button class="btn primary" id="oGo">Add</button></div>`;
    const go = async () => {
      const name = $('#o1').value.trim(); if (!name) { toast('Enter the name', true); return; }
      await J('POST', `/api/classes/${CID}/students`, {rows: [{name, roll: $('#o2').value.trim()}]}); toast('Student added ✓'); viewStudents();
    };
    $('#oGo').onclick = go; $('#o2').addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
  }
}
function renderPreview() {
  const p = $('#aPrev'), rows = ADD.rows;
  if (!rows.length) { p.innerHTML = ''; return; }
  p.innerHTML = `<div style="margin-top:14px"><b>${rows.length} students found</b> <span class="hint small">- check them, fix anything wrong, then add</span>
    <div style="max-height:320px;overflow:auto;margin-top:8px"><table class="plain"><thead><tr><th style="width:36px">#</th><th>Name</th><th style="width:110px">Roll no.</th><th style="width:44px"></th></tr></thead><tbody>
    ${rows.map((r, i) => `<tr><td class="hint">${i + 1}</td><td><input type="text" data-i="${i}" data-f="name" value="${esc(r.name)}"></td><td><input type="text" data-i="${i}" data-f="roll" value="${esc(r.roll)}"></td><td><button class="link" data-x="${i}" style="color:var(--bad)">✕</button></td></tr>`).join('')}
    </tbody></table></div>
    <div class="row" style="margin-top:10px"><button class="btn primary" id="aGo">Add ${rows.length} students</button><button class="btn" id="aClr">Clear</button>
    <span class="hint small">Roll numbers already in the class are updated, not duplicated.</span></div></div>`;
  $$('#aPrev input').forEach(i => i.oninput = () => { rows[+i.dataset.i][i.dataset.f] = i.value; });
  $$('#aPrev [data-x]').forEach(b => b.onclick = () => { rows.splice(+b.dataset.x, 1); renderPreview(); });
  $('#aClr').onclick = () => { ADD.rows = []; renderAddTab(); };
  $('#aGo').onclick = async () => {
    const r = await J('POST', `/api/classes/${CID}/students`, {rows: rows.filter(x => x.name.trim())});
    toast(`${r.added} added${r.updated ? `, ${r.updated} updated` : ''} ✓`); ADD.rows = []; viewStudents();
  };
}

/* ============================================================ CLASS SETTINGS == */
const SENS_TXT = {strict: 'Strict - fewest wrong matches, you check more faces', balanced: 'Balanced (recommended)', lenient: 'Lenient - finds more people, check the orange ones'};
function settingsModal(msg) {
  const c = cls(), sens = c.sens || 'balanced';
  openModal(`<div class="stack"><div class="row"><h2 class="grow">Class settings</h2><button class="link" onclick="closeModal()">Close</button></div>
    <div><label class="lab" style="margin-top:0">Class / subject name</label>
      <div class="row"><input type="text" id="stName" value="${esc(c.name)}" style="flex:1;min-width:180px"><button class="btn primary" id="stRen">Save name</button></div></div>
    <div><label class="lab" style="margin-top:0">Face matching</label>
      <div class="seg" id="stSens">${Object.keys(SENS_TXT).map(k => `<button data-s="${k}" class="${k === sens ? 'on' : ''}">${k[0].toUpperCase() + k.slice(1)}</button>`).join('')}</div>
      <p class="hint small" id="stSensT" style="margin:6px 0 0">${SENS_TXT[sens]}</p></div>
    <hr style="border:0;border-top:1px solid var(--line);width:100%">
    <div><b>Students &amp; face scans</b>
      <div class="row" style="margin-top:8px"><a class="btn sm" href="/api/classes/${CID}/students.xlsx">⬇ Download student list</a>
      <button class="btn sm" id="stOld">🔍 Find &amp; import old scans</button>
      <button class="btn sm" id="stClr">Reset all face scans</button></div>
      <div id="stLegacy" style="margin-top:10px"></div></div>
    <hr style="border:0;border-top:1px solid var(--line);width:100%">
    <div><b>Password</b>
      <div class="row" style="margin-top:8px"><input type="password" id="pwOld" placeholder="Current password" style="flex:1;min-width:140px"><input type="password" id="pwNew" placeholder="New password" style="flex:1;min-width:140px"><button class="btn sm" id="pwGo">Change</button></div></div>
    <hr style="border:0;border-top:1px solid var(--line);width:100%">
    <div class="row"><button class="btn danger" id="stDel">Delete this class…</button><span class="grow"></span><button class="link" id="stOut" style="color:var(--bad)">Log out</button></div>
    ${msg ? `<div class="hint">${esc(msg)}</div>` : ''}</div>`);
  $('#stRen').onclick = async () => {
    const n = $('#stName').value.trim(); if (!n) { toast('Enter a name', true); return; }
    try { await J('PATCH', `/api/classes/${CID}`, {name: n}); await loadClasses(CID); toast('Class renamed ✓'); settingsModal(); route(); } catch (e) { toast(e.message, true); }
  };
  $$('#stSens button').forEach(b => b.onclick = async () => {
    try { await J('PATCH', `/api/classes/${CID}`, {sens: b.dataset.s}); c.sens = b.dataset.s; $$('#stSens button').forEach(x => x.classList.toggle('on', x === b)); $('#stSensT').textContent = SENS_TXT[b.dataset.s]; toast('Saved ✓', false, 1200); }
    catch (e) { toast(e.message, true); }
  });
  $('#stClr').onclick = async () => {
    if (!confirm('Delete EVERY student face scan in this class? Names stay, but everyone must scan again.')) return;
    const r = await J('POST', `/api/classes/${CID}/clear-faces`); toast(`${r.cleared} scans reset`); settingsModal(); route();
  };
  $('#stOld').onclick = async () => {
    const box = $('#stLegacy'); box.innerHTML = '<span class="hint">Searching the database…</span>';
    try {
      const r = await api('/api/legacy');
      if (!r.groups.length) { box.innerHTML = '<div class="hint">No older face scans were found in the database.</div>'; return; }
      box.innerHTML = r.groups.map((g, i) => `<div class="card" style="padding:12px;margin-top:8px"><b>${g.docs} scanned students</b> <span class="hint small">(${esc(g.path)})</span>
        <div class="hint small">${g.names.map(esc).join(', ')}${g.docs > g.names.length ? '…' : ''}</div><button class="btn sm primary" data-i="${i}" style="margin-top:8px">Import into “${esc(c.name)}”</button></div>`).join('');
      $$('#stLegacy [data-i]').forEach(b => b.onclick = async () => {
        b.disabled = true; b.textContent = 'Importing…';
        try { const x = await J('POST', `/api/classes/${CID}/legacy-import`, {path: r.groups[+b.dataset.i].path}); toast(`${x.created} students added, ${x.updated} updated ✓`); closeModal(); location.hash = '#/students'; route(); }
        catch (e) { toast(e.message, true); b.disabled = false; b.textContent = 'Retry'; }
      });
    } catch (e) { box.innerHTML = `<div class="hint" style="color:var(--bad)">${esc(e.message)}</div>`; }
  };
  $('#pwGo').onclick = async () => {
    try { await J('POST', '/api/password', {old: $('#pwOld').value, new: $('#pwNew').value}); $('#pwOld').value = $('#pwNew').value = ''; toast('Password changed ✓'); } catch (e) { toast(e.message, true); }
  };
  $('#stDel').onclick = async () => {
    if (CLASSES.length <= 1) { toast('Add another class first - you need at least one.', true, 5000); return; }
    const typed = prompt(`This permanently deletes "${c.name}" with all its students, face scans and attendance records.\n\nType DELETE to confirm:`);
    if (typed !== 'DELETE') return;
    try { await api(`/api/classes/${CID}`, {method: 'DELETE'}); localStorage.removeItem('cid'); DRAFT = null; closeModal(); await loadClasses(); toast('Class deleted'); location.hash = '#/'; route(); } catch (e) { toast(e.message, true); }
  };
  $('#stOut').onclick = async () => { await J('POST', '/api/logout'); location.reload(); };
}

/* ======================================================== SHARE + NEW CLASS == */
const EXPIRY = [[1, '1 hour'], [5, '5 hours'], [48, '2 days'], [120, '5 days']];
function shareModal() {
  let hours = 5;
  openModal(`<div class="stack"><div class="row"><h2 class="grow">Share with students</h2><button class="link" onclick="closeModal()">Close</button></div>
    <div><b>1 · Face-scan link</b><p class="hint" style="margin:4px 0 8px">Students open it on their phone, pick their name from the list and scan their face. It stops working after the time you choose.</p>
      <div class="seg" id="exp">${EXPIRY.map(([h, t]) => `<button data-h="${h}" class="${h === hours ? 'on' : ''}">${t}</button>`).join('')}</div>
      <div style="margin-top:10px"><button class="btn primary" id="mkLink">Create link</button></div>
      <div id="lnk" class="hide" style="margin-top:10px"><input type="text" id="lnkUrl" readonly>
        <div class="row" style="margin-top:8px"><button class="btn sm" id="lnkCopy">Copy link</button><a class="btn sm" id="lnkWa" target="_blank">WhatsApp</a><span class="hint small" id="lnkExp"></span></div></div></div>
    <hr style="border:0;border-top:1px solid var(--line);width:100%">
    <div><b>2 · Attendance dashboard link</b><p class="hint" style="margin:4px 0 8px">Students see class attendance and can look up their own name or roll number. No login. This link never expires.</p>
      <input type="text" id="dashUrl" readonly value="${location.origin}/dashboard">
      <div class="row" style="margin-top:8px"><button class="btn sm" id="dashCopy">Copy link</button><a class="btn sm" href="/dashboard" target="_blank">Open</a></div></div>
    <hr style="border:0;border-top:1px solid var(--line);width:100%"><button class="link" id="logoutBtn" style="color:var(--bad)">Log out</button></div>`);
  $('#logoutBtn').onclick = async () => { await J('POST', '/api/logout'); location.reload(); };
  $$('#exp button').forEach(b => b.onclick = () => { hours = +b.dataset.h; $$('#exp button').forEach(x => x.classList.toggle('on', x === b)); });
  const copy = async t => { try { await navigator.clipboard.writeText(t); } catch (e) { const i = document.createElement('input'); i.value = t; document.body.appendChild(i); i.select(); document.execCommand('copy'); i.remove(); } toast('Link copied ✓'); };
  $('#mkLink').onclick = async () => {
    const r = await J('POST', '/api/invite', {cid: CID, hours}), url = `${location.origin}/join/${r.token}`;
    $('#lnk').classList.remove('hide'); $('#lnkUrl').value = url;
    $('#lnkWa').href = 'https://wa.me/?text=' + encodeURIComponent(`Please scan your face for attendance (takes 15 seconds, use your phone camera): ${url}`);
    $('#lnkExp').textContent = 'Works for ' + EXPIRY.find(e => e[0] === hours)[1];
    $('#lnkCopy').onclick = () => copy(url);
  };
  $('#dashCopy').onclick = () => copy($('#dashUrl').value);
}

function newClassModal() {
  const others = CLASSES;
  openModal(`<div class="stack"><div class="row"><h2 class="grow">New class</h2><button class="link" onclick="closeModal()">Cancel</button></div>
    <div><label class="lab" style="margin-top:0">Class / subject name</label><input type="text" id="ncName" placeholder="e.g. Time Series Analysis"></div>
    <div><label class="lab" style="margin-top:0">Students</label><select id="ncFrom"><option value="">Start empty - I'll add students later</option>
      ${others.map(c => `<option value="${c.id}">Same students as: ${esc(c.name)}</option>`).join('')}</select>
      <label class="row small hide" id="ncFacesRow" style="margin-top:8px"><input type="checkbox" id="ncFaces" checked> also copy their face scans (no need to scan again)</label>
      <p class="hint small" style="margin:8px 0 0">Copied students are independent - changing them here never changes the other class.</p></div>
    <button class="btn primary" id="ncGo">Create class</button></div>`);
  $('#ncFrom').onchange = e => $('#ncFacesRow').classList.toggle('hide', !e.target.value);
  $('#ncGo').onclick = async () => {
    const name = $('#ncName').value.trim(); if (!name) { toast('Enter a class name', true); return; }
    const r = await J('POST', '/api/classes', {name, copy_from: $('#ncFrom').value || null, with_faces: $('#ncFaces').checked});
    closeModal(); DRAFT = null; await loadClasses(r.id); toast(`Class created${r.copied ? ` with ${r.copied} students` : ''} ✓`);
    location.hash = r.copied ? '#/' : '#/students'; route();
  };
}

boot();
