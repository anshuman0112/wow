import { getCalls, getCall, mode } from '../store.js';
import { esc, icon, fmtDur, fmtDate, interestBadge, moodBadge, demoBanner } from '../ui.js';

// Kept between visits, so opening a call and coming back keeps your dates, filter and sort.
const view = { filter: 'all', from: '', to: '', sort: 'new', preset: 'all' };

// Calendar day of a call in India time (YYYY-MM-DD), so "today" means today in IST.
const istDay = iso => iso ? new Date(iso).toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' }) : '';
const shift = (day, n) => { const d = new Date(`${day}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const PRESETS = [['today', 'Today'], ['yesterday', 'Yesterday'], ['7d', 'Last 7 days'], ['month', 'This month'], ['all', 'All time']];

function presetRange(p) {
  const today = istDay(new Date().toISOString());
  return { today: [today, today], yesterday: [shift(today, -1), shift(today, -1)], '7d': [shift(today, -6), today],
           month: [`${today.slice(0, 8)}01`, today], all: ['', ''] }[p];
}

const fmtDay = d => new Date(`${d}T12:00:00Z`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });

export default async function callsView(el, [openId]) {
  const calls = await getCalls();

  const draw = () => {
    const inRange = calls.filter(c => {
      const d = istDay(c.started_at);
      return (!view.from || d >= view.from) && (!view.to || d <= view.to);
    });
    const count = k => k === 'all' ? inRange.length : inRange.filter(c => c.interest === k).length;
    const shown = inRange.filter(c => view.filter === 'all' || c.interest === view.filter)
      .sort((a, b) => (view.sort === 'new' ? -1 : 1) * String(a.started_at || '').localeCompare(String(b.started_at || '')));
    const rangeLabel = !view.from && !view.to ? 'all time'
      : view.from === view.to ? fmtDay(view.from) : `${view.from ? fmtDay(view.from) : 'the start'} – ${view.to ? fmtDay(view.to) : 'today'}`;
    const tile = (k, label, cls) => `
      <button class="card card-pad stat" data-f="${k}" style="text-align:left;cursor:pointer;font:inherit;color:inherit;${view.filter === k ? 'outline:2px solid var(--brand, #8a6d3b)' : ''}">
        <div class="label">${label}</div><div class="value">${count(k)}</div>
        <div class="hint">${k === 'all' ? rangeLabel : `${Math.round((count(k) / Math.max(1, count('all'))) * 100)}% of calls`}${cls ? '' : ''}</div>
      </button>`;
    el.innerHTML = `
      ${demoBanner(mode())}
      <div class="page-head">
        <div><h1>Calls</h1><p class="muted">Every call is transcribed, summarised and scored · browser calls are also recorded</p></div>
      </div>
      <section class="card card-pad" style="margin-bottom:16px">
        <div class="row" style="gap:12px">
          <div class="seg" role="group" aria-label="Quick date range">
            ${PRESETS.map(([k, v]) => `<button data-p="${k}" class="${view.preset === k ? 'on' : ''}">${v}</button>`).join('')}
          </div>
          <label class="small muted row" style="gap:6px">From <input class="input" type="date" id="from" value="${esc(view.from)}"></label>
          <label class="small muted row" style="gap:6px">To <input class="input" type="date" id="to" value="${esc(view.to)}"></label>
          <span class="spacer"></span>
          <label class="small muted row" style="gap:6px">Sort
            <select class="input" id="sort">
              <option value="new" ${view.sort === 'new' ? 'selected' : ''}>Newest first</option>
              <option value="old" ${view.sort === 'old' ? 'selected' : ''}>Oldest first</option>
            </select></label>
        </div>
      </section>
      <div class="grid g-4" style="margin-bottom:16px">
        ${tile('all', 'Total calls')}${tile('hot', '🔥 Hot')}${tile('warm', 'Warm')}${tile('cold', 'Cold')}
      </div>
      <section class="card">
        <div class="toolbar">
          <b>${view.filter === 'all' ? 'All calls' : `${view.filter[0].toUpperCase()}${view.filter.slice(1)} calls`}</b>
          <span class="muted small">${shown.length} shown · ${rangeLabel}</span>
          ${view.filter !== 'all' || view.from || view.to ? '<span class="spacer"></span><button class="btn btn-ghost small" id="reset">Show everything</button>' : ''}
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Lead</th><th>When</th><th>Duration</th><th>Language</th><th>Mood</th><th>Score</th><th>Interest</th><th>Callback</th></tr></thead>
            <tbody>
              ${shown.map(c => `
                <tr class="clickable" data-id="${esc(c.id)}" tabindex="0">
                  <td><div class="cell-title">${esc(c.name)}</div><div class="cell-sub">${esc(c.scenario || c.ended_reason || '')}</div></td>
                  <td>${fmtDate(c.started_at)}</td>
                  <td class="mono">${fmtDur(c.duration_sec)}</td>
                  <td>${esc(c.language || '—')}</td>
                  <td>${moodBadge(c.sentiment_end)}</td>
                  <td class="mono">${c.score ?? '—'}</td>
                  <td>${interestBadge(c.interest)}</td>
                  <td>${esc(c.callback_time || '—')}</td>
                </tr>`).join('') || `<tr><td colspan="8" class="empty">${calls.length ? 'No calls match these dates and filter.' : 'No calls yet.'}</td></tr>`}
            </tbody>
          </table>
        </div>
      </section>`;
    el.querySelectorAll('[data-f]').forEach(b => b.onclick = () => { view.filter = view.filter === b.dataset.f ? 'all' : b.dataset.f; draw(); });
    el.querySelectorAll('[data-p]').forEach(b => b.onclick = () => {
      [view.from, view.to] = presetRange(b.dataset.p); view.preset = b.dataset.p; draw();
    });
    const setDate = (key, value) => {
      view[key] = value; view.preset = '';
      if (view.from && view.to && view.from > view.to) [view.from, view.to] = [view.to, view.from];   // swap if reversed
      draw();
    };
    el.querySelector('#from').onchange = e => setDate('from', e.target.value);
    el.querySelector('#to').onchange = e => setDate('to', e.target.value);
    el.querySelector('#sort').onchange = e => { view.sort = e.target.value; draw(); };
    const reset = el.querySelector('#reset');
    if (reset) reset.onclick = () => { Object.assign(view, { filter: 'all', from: '', to: '', preset: 'all' }); draw(); };
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

// The hand-back for the sales team: score with reasons (and the lead's own words), objections, who decides, next step.
const DECIDER = { self: 'Decides alone', spouse: 'Decides with spouse', family: 'Decides with family', someone_else: 'Someone else decides', unknown: 'Not known' };
function profileCard(c) {
  if (c.score == null) return '';
  const rows = c.score_breakdown || [];
  return `
    <section class="card card-pad">
      <div class="row"><h3>Lead profile</h3><span class="spacer"></span>
        <span class="mono" style="font-size:22px;font-weight:650">${c.score}<span class="muted small">/100</span></span> ${interestBadge(c.interest)}</div>
      <div class="stack" style="gap:6px;margin-top:10px">
        ${rows.map(r => `
          <div class="row small" style="gap:8px;flex-wrap:nowrap;align-items:flex-start">
            <span class="mono" style="min-width:44px;color:${r.points > 0 ? 'var(--ok, #2f7d4f)' : r.points < 0 ? 'var(--bad, #b3261e)' : 'var(--muted)'}">${r.points > 0 ? '+' : ''}${r.points}${r.max ? `/${r.max}` : ''}</span>
            <span style="flex:1"><b>${esc(r.label)}</b>${r.evidence ? ` <span class="muted">· “${esc(r.evidence)}”</span>` : r.detail ? ` <span class="muted">· ${esc(r.detail)}</span>` : ''}</span>
          </div>`).join('')}
      </div>
      <div class="grid g-2" style="margin-top:14px;gap:10px">
        <div><div class="muted small">Decision maker</div><b>${esc(DECIDER[c.decision_maker] || c.decision_maker || '—')}</b></div>
        <div><div class="muted small">Objections</div>${(c.objections || []).length ? `<ul style="margin:2px 0 0 16px;padding:0">${c.objections.map(o => `<li>${esc(o)}</li>`).join('')}</ul>` : '<b>None raised</b>'}</div>
      </div>
      ${c.next_action ? `<div class="banner" style="margin:14px 0 0">${icon('arrow')}<span><b>Next action:</b> ${esc(c.next_action)}</span></div>` : ''}
    </section>`;
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
        ${profileCard(c)}
        <section class="card card-pad">
          <h3>Recording</h3>
          ${c.recording_url
            ? `<audio controls preload="none" src="${esc(c.recording_url)}" style="width:100%;margin-top:10px"></audio>`
            : c.call_type === 'twilioPhoneCall'
              ? `<p class="muted small" style="margin-top:6px">Phone calls on the free Twilio trial can't be recorded (Twilio blocks recording on trial accounts), so the full transcript is below. Browser calls from <b>Talk to Divya</b> are recorded and play here.</p>`
              : `<p class="muted small" style="margin-top:6px">${mode() === 'demo' ? 'Sample call — no audio.' : 'No recording was saved for this call.'} Recorded calls play here (stored in Supabase Storage).</p>`}
        </section>

        <section class="card card-pad">
          <h3>AI summary</h3>
          <p style="margin-top:6px">${esc(c.summary || '—')}</p>
          <div class="row small muted" style="margin-top:12px">
            Mood: ${moodBadge(c.sentiment_start)} ${icon('arrow', 14)} ${moodBadge(c.sentiment_end)}
            <span class="spacer"></span>
            Expert callback: <b style="color:var(--ink)">${esc(c.callback_time || 'Not booked')}</b>
          </div>
          ${c.call_back_at ? `<div class="banner" style="margin:12px 0 0">${icon('phone')}<span>Lead was busy: Divya will call back automatically on <b>${esc(fmtDate(c.call_back_at))}</b>.</span></div>` : ''}
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
              <div class="msg ${m.role}"><span class="who">${m.role === 'assistant' ? 'Divya' : esc(c.name)}</span>${esc(m.text)}</div>`).join('')}
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
