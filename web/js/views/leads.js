import { getLeads, addLeads, callNow, mode } from '../store.js';
import { phoneCalling } from '../config.js';
import { readFile, guessMapping, aiMapping, cleanRows, normalisePhone } from '../importer.js';
import { esc, icon, fmtDate, interestBadge, statusBadge, demoBanner, toast } from '../ui.js';
import { verifyPanel, bindVerifyPanel, stopPolling } from './verify-panel.js';

const FIELD_OPTS = ['name', 'phone', 'email', 'location', 'budget', 'notes', 'extra'];

export default async function leadsView(el) {
  let leads = await getLeads();
  const realCalls = await phoneCalling();   // true when the Python backend has a phone line (Twilio bridge / Vapi number)
  let filter = 'all', q = '';
  let pending = null; // { file, rows, headers, mapping }
  let report = null;  // last import result: who was added, who was a duplicate and why

  const draw = () => {
    const shown = leads.filter(l =>
      (filter === 'all' || l.interest === filter || l.status === filter) &&
      (!q || `${l.name} ${l.phone} ${l.location}`.toLowerCase().includes(q)));

    el.innerHTML = `
      ${demoBanner(mode())}
      <div class="page-head">
        <div><h1>Leads</h1><p class="muted">${leads.length} people · press <b>Call phone</b> to have Divya call a lead (nobody is called automatically)</p></div>
      </div>

      ${realCalls && mode() !== 'demo' ? verifyPanel() : ''}
      ${report ? importReport(report) : ''}
      <section class="card" style="margin-bottom:16px">
        <div class="card-head"><div><h2>Import leads</h2><p class="muted small">CSV, Excel (.xlsx / .xls), JSON or SQL INSERT dumps — columns are detected automatically</p></div></div>
        <div class="card-pad">
          ${pending ? mappingPanel(pending) : `
            <label class="dropzone" id="drop">
              ${icon('upload')}
              <div style="margin-top:8px;font-weight:600">Drop a file here or click to browse</div>
              <div class="muted small" style="margin-top:2px">e.g. a sheet with "Customer Name", "Mob No.", "City" works as-is</div>
              <input type="file" id="file" accept=".csv,.xlsx,.xls,.json,.sql,.tsv,.txt,.ods" hidden>
            </label>
            <form class="row" id="add-form" style="margin-top:14px">
              <span class="muted small" style="width:100%">Or add one lead by hand (handy for testing on your own phone):</span>
              <input class="input" name="name" placeholder="Name" maxlength="80" style="flex:1;min-width:140px">
              <input class="input" name="phone" placeholder="Phone, e.g. 98765 43210" required style="flex:1;min-width:160px">
              <input class="input" name="location" placeholder="City (optional)" maxlength="80" style="flex:1;min-width:140px">
              <button class="btn btn-primary" type="submit">Add lead</button>
              <span class="small" id="add-err" style="color:var(--bad);width:100%"></span>
            </form>`}
        </div>
      </section>

      <section class="card">
        <div class="toolbar">
          <div class="seg" role="group" aria-label="Filter leads">
            ${[['all', 'All'], ['new', 'New'], ['re_engaged', 'Interested again'], ['hot', 'Hot'], ['warm', 'Warm'], ['cold', 'Cold'], ['do_not_call', 'Do not call']]
              .map(([k, v]) => `<button data-f="${k}" class="${filter === k ? 'on' : ''}">${v}</button>`).join('')}
          </div>
          <span class="spacer"></span>
          <input class="input" id="q" placeholder="Search name, phone, city" value="${esc(q)}" style="width:240px">
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Name</th><th>Phone</th><th>Location</th><th>Budget</th><th>Status</th><th>Interest</th><th>Callback</th><th>Source</th><th></th></tr></thead>
            <tbody>
              ${shown.map(l => `
                <tr>
                  <td><div class="cell-title">${esc(l.name || '—')}</div>${l.attempts ? `<div class="cell-sub" title="Calls the phone network actually dialled">${l.attempts} call${l.attempts > 1 ? 's' : ''} dialled</div>` : ''}</td>
                  <td class="mono">${esc(l.phone)}</td>
                  <td>${esc(l.location || '—')}</td>
                  <td>${esc(l.budget || '—')}</td>
                  <td>${statusBadge(l.status)}${l.status === 're_engaged' && l.re_engaged_at ? `<div class="cell-sub">came back ${fmtDate(l.re_engaged_at)}</div>` : ''}</td>
                  <td>${interestBadge(l.interest)}</td>
                  <td>${esc(l.callback_time || '—')}</td>
                  <td class="cell-sub">${esc(l.source || '—')}<br>${fmtDate(l.created_at)}</td>
                  <td>${l.status === 'do_not_call'
                    ? '<span class="faint small">Not allowed</span>'
                    : `<div class="row" style="gap:6px;flex-wrap:nowrap">
                        <button class="btn small" data-call="${esc(l.id)}" title="${realCalls ? 'Ring this lead\'s real phone' : 'Start a browser call with Divya, personalised for this lead'}" ${realCalls && (mode() === 'demo' || l.status === 'calling') ? 'disabled' : ''}>${icon('phone')}${realCalls ? (l.status === 'calling' ? 'Calling…' : 'Call phone') : 'Call now'}</button>
                        ${realCalls ? `<a class="btn btn-ghost small" href="#/talk/${esc(l.id)}" title="Talk to Divya in the browser as this lead">Web call</a>` : ''}
                      </div>`}</td>
                </tr>`).join('') || `<tr><td colspan="9" class="empty">No leads match.</td></tr>`}
            </tbody>
          </table>
        </div>
      </section>`;
    bind();
  };

  const bind = () => {
    el.querySelectorAll('[data-f]').forEach(b => b.onclick = () => { filter = b.dataset.f; draw(); });
    const qi = el.querySelector('#q');
    qi.oninput = () => { q = qi.value.toLowerCase(); const pos = qi.selectionStart; draw(); const n = el.querySelector('#q'); n.focus(); n.setSelectionRange(pos, pos); };

    el.querySelectorAll('[data-call]').forEach(b => b.onclick = async () => {
      const lead = leads.find(l => l.id === b.dataset.call);
      // No paid phone line: open a browser call with Divya, personalised for this lead.
      if (!realCalls) { location.hash = `#/talk/${lead.id}`; return; }
      if (!confirmCall(lead)) return;
      b.disabled = true; b.textContent = 'Starting…';
      try { await callNow(lead.id); toast(`Calling ${lead.name || 'lead'} — their phone will ring in a few seconds`); lead.status = 'calling'; }
      catch (e) { toast(e.message); }
      draw();
    });

    const form = el.querySelector('#add-form');
    if (form) form.onsubmit = async e => {
      e.preventDefault();
      const f = Object.fromEntries(new FormData(form));
      const phone = normalisePhone(f.phone);
      const err = el.querySelector('#add-err');
      if (!phone) { err.textContent = 'Enter a valid phone number (10 digits, or with country code like +91…).'; return; }
      err.textContent = '';
      try {
        report = await addLeads([{ name: f.name?.trim() || null, phone, location: f.location?.trim() || null, source: 'added by hand', extra: {} }]);
        leads = await getLeads();
        toast(report.imported ? 'Lead added' : 'That phone number is already a lead — see the summary above');
        if (report.imported) report = null;
        draw();
      } catch (ex) { err.textContent = ex.message; }
    };

    bindVerifyPanel(el, draw, async () => { leads = await getLeads(); });

    const drop = el.querySelector('#drop');
    if (drop) {
      const input = el.querySelector('#file');
      input.onchange = () => input.files[0] && load(input.files[0]);
      drop.ondragover = e => { e.preventDefault(); drop.classList.add('drag'); };
      drop.ondragleave = () => drop.classList.remove('drag');
      drop.ondrop = e => { e.preventDefault(); drop.classList.remove('drag'); e.dataTransfer.files[0] && load(e.dataTransfer.files[0]); };
    }
    el.querySelectorAll('[data-map]').forEach(s => s.onchange = () => { pending.mapping[s.dataset.map] = s.value; draw(); });
    const cancel = el.querySelector('#cancel');
    if (cancel) cancel.onclick = () => { pending = null; draw(); };
    const go = el.querySelector('#import');
    if (go) go.onclick = async () => {
      const { leads: clean, invalid, dupes } = cleanRows(pending.rows, pending.mapping, pending.file);
      go.disabled = true;
      let res;
      try { res = await addLeads(clean); } catch (e) { toast(e.message); go.disabled = false; return; }
      leads = await getLeads();
      const nameCol = Object.keys(pending.mapping).find(c => pending.mapping[c] === 'name');
      report = { ...res, file: pending.file, invalid: invalid.length,
                 in_file: dupes.map(r => (nameCol && r[nameCol]) || 'Unnamed row') };
      toast(`Imported ${res.imported} new lead${res.imported === 1 ? '' : 's'} — see the summary above`);
      pending = null; draw();
    };
    const closeReport = el.querySelector('#close-report');
    if (closeReport) closeReport.onclick = () => { report = null; draw(); };
  };

  const load = async file => {
    try {
      const rows = await readFile(file);
      if (!rows.length) throw new Error('No rows found in this file.');
      const headers = Object.keys(rows[0]);
      const mapping = (await aiMapping(headers, rows)) || guessMapping(headers);
      pending = { file: file.name, rows, headers, mapping };
      draw();
    } catch (e) { toast(e.message); }
  };

  draw();
  return () => stopPolling();
}

// After an import: who was added and, for every duplicate phone number, what happened and why.
function importReport(r) {
  const names = list => list.map(x => esc(typeof x === 'string' ? x : x.name)).join(', ');
  const groups = [
    ['re_engaged', 'b-hot', 'Interested again', 'They were called before and were not interested; now they enquired again. Marked "Interested again", so call them.'],
    ['already_contacted', 'b-ok', 'Already contacted — skipped', 'Called before and interested or callback booked. Not added again, so they are not called twice.'],
    ['already_listed', 'b-brand', 'Already in your list — skipped', 'Same phone number is already a lead (not called yet). No second copy added.'],
    ['do_not_call', 'b-bad', 'Do not call — skipped', 'They asked not to be called. Left untouched.'],
    ['in_file', '', 'Duplicate inside this file — skipped', 'Same phone number appears more than once in the file; only the first was used.'],
  ].filter(([k]) => (r[k] || []).length);
  return `
    <section class="card" style="margin-bottom:16px">
      <div class="card-head"><div><h2>Import result${r.file ? ` · ${esc(r.file)}` : ''}</h2>
        <p class="muted small">Duplicates are matched by phone number: the same number is always the same person.</p></div>
        <span class="spacer"></span><button class="btn btn-ghost small" id="close-report">Close</button></div>
      <div class="card-pad stack" style="gap:12px">
        <div><span class="badge b-ok">${r.imported} new</span>
          ${r.new?.length ? `<span class="small muted" style="margin-left:8px">${names(r.new)}</span>` : ''}
          ${r.invalid ? `<span class="badge" style="margin-left:8px">${r.invalid} without a valid phone</span>` : ''}</div>
        ${groups.map(([k, cls, title, why]) => `
          <div><span class="badge ${cls}">${r[k].length} · ${title}</span>
            <div class="small" style="margin-top:4px">${names(r[k])}</div>
            <div class="muted small">${why}</div></div>`).join('')}
        ${groups.length ? '' : '<div class="muted small">No duplicates found.</div>'}
      </div>
    </section>`;
}

// Real calls ring a real phone — always confirm first.
function confirmCall(lead) {
  return window.confirm(`Call ${lead?.name || 'this lead'} at ${lead?.phone} now?\n\nThis rings a real phone (free Twilio trial: verified numbers only).`);
}

function mappingPanel(p) {
  const preview = cleanRows(p.rows, p.mapping, p.file);
  const hasPhone = Object.values(p.mapping).includes('phone');
  return `
    <div class="row" style="margin-bottom:12px">
      <span class="badge b-brand">${icon('file', 13)} ${esc(p.file)}</span>
      <span class="muted small">${p.rows.length} rows · ${preview.leads.length} ready · ${preview.dupes.length} duplicates · ${preview.invalid.length} invalid phone</span>
    </div>
    <p class="muted small" style="margin-bottom:8px">Detected column mapping — change anything that looks wrong:</p>
    <div class="table-wrap" style="border:1px solid var(--border);border-radius:10px">
      <table>
        <thead><tr><th>Column in your file</th><th>Example value</th><th>Saved as</th></tr></thead>
        <tbody>
          ${p.headers.map(h => `
            <tr>
              <td class="cell-title">${esc(h)}</td>
              <td class="muted">${esc(String(p.rows.find(r => r[h])?.[h] ?? '').slice(0, 40))}</td>
              <td><select class="input" data-map="${esc(h)}">${FIELD_OPTS.map(o => `<option value="${o}" ${p.mapping[h] === o ? 'selected' : ''}>${o === 'extra' ? 'keep as extra info' : o}</option>`).join('')}</select></td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>
    ${hasPhone ? '' : '<p class="small" style="color:var(--bad);margin-top:10px">Map one column to "phone" — leads need a number to be called.</p>'}
    <div class="row" style="margin-top:14px">
      <button class="btn btn-primary" id="import" ${hasPhone && preview.leads.length ? '' : 'disabled'}>Import ${preview.leads.length} leads</button>
      <button class="btn" id="cancel">Cancel</button>
    </div>`;
}
