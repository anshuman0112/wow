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
            ${[['all', 'All'], ['new', 'New'], ['hot', 'Hot'], ['warm', 'Warm'], ['cold', 'Cold'], ['do_not_call', 'Do not call']]
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
                  <td><div class="cell-title">${esc(l.name || '—')}</div>${l.attempts ? `<div class="cell-sub">${l.attempts} call attempt${l.attempts > 1 ? 's' : ''}</div>` : ''}</td>
                  <td class="mono">${esc(l.phone)}</td>
                  <td>${esc(l.location || '—')}</td>
                  <td>${esc(l.budget || '—')}</td>
                  <td>${statusBadge(l.status)}</td>
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
        const n = await addLeads([{ name: f.name?.trim() || null, phone, location: f.location?.trim() || null, source: 'added by hand', extra: {} }]);
        leads = await getLeads();
        toast(n ? 'Lead added' : 'That phone number is already in your leads');
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
      let added;
      try { added = await addLeads(clean); } catch (e) { toast(e.message); go.disabled = false; return; }
      leads = await getLeads();
      toast(`Imported ${added} · ${dupes.length + (clean.length - added)} duplicates · ${invalid.length} without a valid phone`);
      pending = null; draw();
    };
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
