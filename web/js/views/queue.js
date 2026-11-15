import { getLeads, callNow, mode } from '../store.js';
import { phoneCalling } from '../config.js';
import { esc, icon, fmtDate, toast, demoBanner } from '../ui.js';

// Call queue: everyone who still needs a call, in one list, with a filter per reason.
//   New              → never called; you call them (free Twilio trial: verified numbers only)
//   Interested again → were not interested, enquired again; top priority, you call them
//   Call-back        → were busy and asked for a time; called AUTOMATICALLY at that time
//   Re-attempt       → rang but nobody picked up; retried AUTOMATICALLY (2 h, next day 11 am, then stop)
const KINDS = {
  re_engaged: { label: 'Interested again', cls: 'b-hot', auto: false },
  callback: { label: 'Call-back requested', cls: 'b-gold', auto: true },
  reattempt: { label: 'Re-attempt', cls: 'b-brand', auto: true },
  new: { label: 'New', cls: '', auto: false },
};
const ORDER = ['re_engaged', 'callback', 'reattempt', 'new'];
const view = { filter: 'all' };

export function queueKind(l) {
  if (l.status === 're_engaged') return 're_engaged';
  if (l.status === 'callback') return 'callback';
  if (l.status === 'no_answer' && l.next_call_at) return 'reattempt';
  if (l.status === 'new') return 'new';
  return null;   // called, do not call, unreachable… not waiting for a call
}

export default async function queueView(el) {
  let leads = await getLeads();
  const realCalls = await phoneCalling();

  const draw = () => {
    const now = Date.now();
    const queue = leads.map(l => ({ ...l, kind: queueKind(l) })).filter(l => l.kind);
    const unreachable = leads.filter(l => l.status === 'no_answer' && !l.next_call_at).length;
    const due = l => l.next_call_at && new Date(l.next_call_at).getTime() <= now;
    const rank = l => (due(l) ? 0 : 1) * 10 + ORDER.indexOf(l.kind);
    const shown = queue.filter(l => view.filter === 'all' || l.kind === view.filter).sort((a, b) =>
      rank(a) - rank(b) || String(a.next_call_at || a.re_engaged_at || a.created_at).localeCompare(String(b.next_call_at || b.re_engaged_at || b.created_at)));
    const count = k => k === 'all' ? queue.length : queue.filter(l => l.kind === k).length;
    const when = l => {
      if (KINDS[l.kind].auto && l.next_call_at) return due(l)
        ? '<b>Due now</b><div class="cell-sub">auto-dial within ~5 min</div>'
        : `Auto: <b>${esc(fmtDate(l.next_call_at))}</b>`;
      return '<span class="muted">Call when ready</span>';
    };
    el.innerHTML = `
      ${demoBanner(mode())}
      <div class="page-head">
        <div><h1>Call queue</h1><p class="muted">Everyone who still needs a call. Call-backs and re-attempts are dialled automatically
          (9 am – 9 pm IST); new and interested-again leads are called when you press <b>Call</b>.</p></div>
      </div>
      <section class="card">
        <div class="toolbar">
          <div class="seg" role="group" aria-label="Filter the call queue">
            ${[['all', 'All'], ...ORDER.map(k => [k, KINDS[k].label])].map(([k, v]) =>
              `<button data-f="${k}" class="${view.filter === k ? 'on' : ''}">${v} · ${count(k)}</button>`).join('')}
          </div>
          <span class="spacer"></span>
          ${unreachable ? `<span class="muted small" title="No answer after 3 tries: not called again automatically">${unreachable} unreachable (stopped after 3 tries)</span>` : ''}
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Name</th><th>Why</th><th>When</th><th>Calls dialled</th><th>Note</th><th></th></tr></thead>
            <tbody>
              ${shown.map(l => `
                <tr>
                  <td><div class="cell-title">${esc(l.name || '—')}</div><div class="cell-sub mono">${esc(l.phone)}</div></td>
                  <td><span class="badge ${KINDS[l.kind].cls}">${KINDS[l.kind].label}</span></td>
                  <td>${when(l)}</td>
                  <td class="mono">${l.attempts || 0}</td>
                  <td class="small">${esc(l.callback_note || (l.kind === 're_engaged' && l.re_engaged_at ? `Came back ${fmtDate(l.re_engaged_at)}` : l.location || ''))}</td>
                  <td><div class="row" style="gap:6px;flex-wrap:nowrap">
                    ${realCalls ? `<button class="btn small" data-call="${esc(l.id)}" ${mode() === 'demo' ? 'disabled' : ''}>${icon('phone')}Call now</button>` : ''}
                    <a class="btn btn-ghost small" href="#/talk/${esc(l.id)}">Web call</a></div></td>
                </tr>`).join('') || `<tr><td colspan="6" class="empty">${queue.length ? 'Nobody in this filter.' : 'Nobody is waiting for a call. 🎉'}</td></tr>`}
            </tbody>
          </table>
        </div>
      </section>`;
    el.querySelectorAll('[data-f]').forEach(b => b.onclick = () => { view.filter = b.dataset.f; draw(); });
    el.querySelectorAll('[data-call]').forEach(b => b.onclick = async () => {
      const lead = leads.find(x => x.id === b.dataset.call);
      if (!window.confirm(`Call ${lead?.name || 'this lead'} now?\n\nThis rings a real phone (free Twilio trial: verified numbers only).`)) return;
      b.disabled = true; b.textContent = 'Starting…';
      try { await callNow(lead.id); toast(`Calling ${lead.name || 'lead'}: their phone will ring in a few seconds`); }
      catch (e) { toast(e.message); }
      leads = await getLeads(); draw();
    });
  };
  draw();
}
