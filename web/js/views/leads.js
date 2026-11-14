import { getLeads, addLeads, mode } from '../store.js';
import { readFile, guessMapping, aiMapping, cleanRows } from '../importer.js';
import { esc, icon, fmtDate, interestBadge, statusBadge, demoBanner, toast } from '../ui.js';

const FIELD_OPTS = ['name', 'phone', 'email', 'location', 'budget', 'notes', 'extra'];

export default async function leadsView(el) {
  let leads = await getLeads();
  let filter = 'all', q = '';
  let pending = null; // { file, rows, headers, mapping }

  const draw = () => {
    const shown = leads.filter(l =>
      (filter === 'all' || l.interest === filter || l.status === filter) &&
      (!q || `${l.name} ${l.phone} ${l.location}`.toLowerCase().includes(q)));

    el.innerHTML = `
      ${demoBanner(mode())}
      <div class="page-head">
        <div><h1>Leads</h1><p class="muted">${leads.length} people · new leads are called automatically between 10 AM and 7 PM IST</p></div>
      </div>

      <section class="card" style="margin-bottom:16px">
        <div class="card-head"><div><h2>Import leads</h2><p class="muted small">CSV, Excel (.xlsx / .xls), JSON or SQL INSERT dumps — columns are detected automatically</p></div></div>
        <div class="card-pad">
          ${pending ? mappingPanel(pending) : `
            <label class="dropzone" id="drop">
              ${icon('upload')}
              <div style="margin-top:8px;font-weight:600">Drop a file here or click to browse</div>
              <div class="muted small" style="margin-top:2px">e.g. a sheet with "Customer Name", "Mob No.", "City" works as-is</div>
              <input type="file" id="file" accept=".csv,.xlsx,.xls,.json,.sql,.tsv,.txt,.ods" hidden>
            </label>`}
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
            <thead><tr><th>Name</th><th>Phone</th><th>Location</th><th>Budget</th><th>Status</th><th>Interest</th><th>Callback</th><th>Source</th></tr></thead>
            <tbody>
              ${shown.map(l => `
                <tr>
                  <td><div class="cell-title">${esc(l.name || '—')}</div><div class="cell-sub">${esc(l.id || '')}</div></td>
                  <td class="mono">${esc(l.phone)}</td>
                  <td>${esc(l.location || '—')}</td>
                  <td>${esc(l.budget || '—')}</td>
                  <td>${statusBadge(l.status)}</td>
                  <td>${interestBadge(l.interest)}</td>
                  <td>${esc(l.callback_time || '—')}</td>
                  <td class="cell-sub">${esc(l.source || '—')}<br>${fmtDate(l.created_at)}</td>
                </tr>`).join('') || `<tr><td colspan="8" class="empty">No leads match.</td></tr>`}
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
