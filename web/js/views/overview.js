import { getLeads, getCalls, mode } from '../store.js';
import { esc, icon, initials, fmtDur, fmtDate, interestBadge, demoBanner } from '../ui.js';

export default async function overview(el) {
  const [leads, calls] = await Promise.all([getLeads(), getCalls()]);
  const count = v => calls.filter(c => c.interest === v).length;
  const hot = count('hot'), warm = count('warm'), cold = count('cold');
  const avg = calls.length ? calls.reduce((s, c) => s + (c.duration_sec || 0), 0) / calls.length : 0;
  const callbacks = calls.filter(c => c.callback_time).length;
  const pending = leads.filter(l => ['new', 'queued', 'no_answer'].includes(l.status)).length;
  const total = Math.max(1, hot + warm + cold);

  el.innerHTML = `
    ${demoBanner(mode())}
    <div class="page-head">
      <div>
        <h1>Overview</h1>
        <p class="muted">Whispers of the Wind · outbound lead qualification by Aanya</p>
      </div>
      <div class="row">
        <a class="btn" href="#/leads">${icon('upload')}Upload leads</a>
        <a class="btn btn-primary" href="#/talk">${icon('mic')}Talk to Aanya</a>
      </div>
    </div>

    <div class="grid g-4">
      ${stat('Leads', leads.length, `${pending} waiting to be called`)}
      ${stat('Calls made', calls.length, `Avg ${fmtDur(avg)} per call`)}
      ${stat('Hot leads', hot, `${Math.round((hot / Math.max(1, calls.length)) * 100)}% of calls`)}
      ${stat('Expert callbacks', callbacks, 'Booked by the agent')}
    </div>

    <div class="grid g-main" style="margin-top:16px">
      <section class="card">
        <div class="card-head"><h2>Recent calls</h2><a class="btn btn-ghost small" href="#/calls">View all ${icon('arrow')}</a></div>
        <div class="list">
          ${calls.slice(0, 6).map(c => `
            <a class="list-item" href="#/calls/${esc(c.id)}">
              <div class="avatar">${initials(c.name)}</div>
              <div style="min-width:0;flex:1">
                <div class="cell-title">${esc(c.name)}</div>
                <div class="cell-sub" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(c.summary)}</div>
              </div>
              <div style="text-align:right">
                ${interestBadge(c.interest)}
                <div class="cell-sub" style="margin-top:4px">${fmtDate(c.started_at)} · ${fmtDur(c.duration_sec)}</div>
              </div>
            </a>`).join('') || '<div class="empty">No calls yet.</div>'}
        </div>
      </section>

      <div class="stack">
        <section class="card card-pad">
          <h2>Lead interest</h2>
          <p class="muted small" style="margin-top:2px">Scored automatically after every call</p>
          <div class="bar" style="margin-top:14px" role="img" aria-label="Hot ${hot}, warm ${warm}, cold ${cold}">
            <span style="width:${hot / total * 100}%;background:var(--hot)"></span>
            <span style="width:${warm / total * 100}%;background:var(--warm)"></span>
            <span style="width:${cold / total * 100}%;background:var(--cold)"></span>
          </div>
          <div class="legend">
            <span><i style="background:var(--hot)"></i>Hot ${hot}</span>
            <span><i style="background:var(--warm)"></i>Warm ${warm}</span>
            <span><i style="background:var(--cold)"></i>Cold ${cold}</span>
          </div>
        </section>

        <section class="card card-pad">
          <h2>How it works</h2>
          <ol class="muted" style="margin:10px 0 0;padding-left:18px;display:flex;flex-direction:column;gap:6px">
            <li><b style="color:var(--ink)">Upload leads</b> — any CSV, Excel, JSON or SQL file.</li>
            <li><b style="color:var(--ink)">Aanya calls</b> them and runs the 4 checkpoints.</li>
            <li><b style="color:var(--ink)">AI scores</b> each call hot, warm or cold.</li>
            <li><b style="color:var(--ink)">Everything is saved</b> — audio, transcript, summary.</li>
            <li><b style="color:var(--ink)">Hot leads</b> get an expert callback.</li>
          </ol>
        </section>
      </div>
    </div>`;
}

const stat = (label, value, hint) => `
  <div class="card card-pad stat">
    <div class="label">${label}</div>
    <div class="value">${value}</div>
    <div class="hint">${hint}</div>
  </div>`;
