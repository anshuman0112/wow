import { getCalls, getCall, mode } from '../store.js';
import { esc, icon, fmtDur, fmtDate, interestBadge, moodBadge, demoBanner } from '../ui.js';

export default async function callsView(el, [openId]) {
  const calls = await getCalls();
  let filter = 'all';

  const draw = () => {
    const shown = calls.filter(c => filter === 'all' || c.interest === filter);
    el.innerHTML = `
      ${demoBanner(mode())}
      <div class="page-head">
        <div><h1>Calls</h1><p class="muted">Every call is recorded, transcribed, summarised and scored</p></div>
      </div>
      <section class="card">
        <div class="toolbar">
          <div class="seg" role="group" aria-label="Filter calls">
            ${[['all', 'All'], ['hot', 'Hot'], ['warm', 'Warm'], ['cold', 'Cold']].map(([k, v]) => `<button data-f="${k}" class="${filter === k ? 'on' : ''}">${v}</button>`).join('')}
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Lead</th><th>When</th><th>Duration</th><th>Language</th><th>Mood</th><th>Interest</th><th>Callback</th></tr></thead>
            <tbody>
              ${shown.map(c => `
                <tr class="clickable" data-id="${esc(c.id)}" tabindex="0">
                  <td><div class="cell-title">${esc(c.name)}</div><div class="cell-sub">${esc(c.scenario || c.ended_reason || '')}</div></td>
                  <td>${fmtDate(c.started_at)}</td>
                  <td class="mono">${fmtDur(c.duration_sec)}</td>
                  <td>${esc(c.language || '—')}</td>
                  <td>${moodBadge(c.sentiment_end)}</td>
                  <td>${interestBadge(c.interest)}</td>
                  <td>${esc(c.callback_time || '—')}</td>
                </tr>`).join('') || '<tr><td colspan="7" class="empty">No calls yet.</td></tr>'}
            </tbody>
          </table>
        </div>
      </section>`;
    el.querySelectorAll('[data-f]').forEach(b => b.onclick = () => { filter = b.dataset.f; draw(); });
    el.querySelectorAll('tr[data-id]').forEach(tr => {
      const open = () => { location.hash = `#/calls/${tr.dataset.id}`; };
      tr.onclick = open;
      tr.onkeydown = e => { if (e.key === 'Enter') open(); };
    });
  };

  draw();
  if (openId) {
    const call = await getCall(openId);
    if (call) return openDrawer(call);
  }
}

function openDrawer(c) {
  const bg = document.createElement('div');
  bg.className = 'drawer-bg';
  bg.innerHTML = `
    <aside class="drawer" role="dialog" aria-modal="true" aria-label="Call details">
      <div class="drawer-head">
        <div style="flex:1;min-width:0">
          <h2>${esc(c.name)}</h2>
          <div class="cell-sub">${fmtDate(c.started_at)} · ${fmtDur(c.duration_sec)} · ${esc(c.language || '')}${c.cost_usd ? ` · $${Number(c.cost_usd).toFixed(2)}` : ''}</div>
        </div>
        ${interestBadge(c.interest)}
        <button class="btn btn-ghost" id="close" aria-label="Close">${icon('x')}</button>
      </div>
      <div class="drawer-body">
        <section class="card card-pad">
          <h3>Recording</h3>
          ${c.recording_url
            ? `<audio controls preload="none" src="${esc(c.recording_url)}" style="width:100%;margin-top:10px"></audio>`
            : `<p class="muted small" style="margin-top:6px">Sample call — no audio. Real calls show a player here (stored in Supabase Storage).</p>`}
        </section>

        <section class="card card-pad">
          <h3>AI summary</h3>
          <p style="margin-top:6px">${esc(c.summary || '—')}</p>
          <div class="row small muted" style="margin-top:12px">
            Mood: ${moodBadge(c.sentiment_start)} ${icon('arrow', 14)} ${moodBadge(c.sentiment_end)}
            <span class="spacer"></span>
            Expert callback: <b style="color:var(--ink)">${esc(c.callback_time || 'Not booked')}</b>
          </div>
        </section>

        <section class="card card-pad">
          <h3>The 4 checkpoints</h3>
          <div class="checkpoints" style="margin-top:10px">
            ${['intent', 'geography', 'budget', 'timeline'].map(k => `
              <div class="cp-box"><div class="k">${k}</div><div class="v">${esc(c.checkpoints?.[k] || '—')}</div></div>`).join('')}
          </div>
        </section>

        <section class="card">
          <div class="card-head"><h3>Full conversation</h3><span class="muted small">${c.messages?.length || 0} turns</span></div>
          <div class="transcript">
            ${(c.messages || []).map(m => `
              <div class="msg ${m.role}"><span class="who">${m.role === 'assistant' ? 'Aanya' : esc(c.name)}</span>${esc(m.text)}</div>`).join('')}
          </div>
        </section>
      </div>
    </aside>`;
  document.body.appendChild(bg);
  const close = () => { bg.remove(); document.removeEventListener('keydown', onKey); if (location.hash.split('/').length > 2) history.replaceState(null, '', '#/calls'); };
  const onKey = e => { if (e.key === 'Escape') close(); };
  bg.addEventListener('click', e => { if (e.target === bg) close(); });
  bg.querySelector('#close').onclick = close;
  document.addEventListener('keydown', onKey);
  bg.querySelector('#close').focus();
  return close;
}
