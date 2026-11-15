import { config } from '../config.js';
import { esc, icon, toast } from '../ui.js';

// "Verify a number" (free Twilio trial): a reviewer verifies their own phone in ~30 seconds,
// then Divya can call it. Twilio rings the number and the person types the code shown here.
const state = { stage: 'form', phone: '', code: '', leadId: null, err: '', busy: false };
let poll = null;

export function verifyPanel() {
  const s = state;
  let body;
  if (s.stage === 'code') {
    body = `
      <p>Twilio is calling <b>${esc(s.phone)}</b> now. Answer it and type this code on your keypad:</p>
      <div style="font-size:34px;font-weight:700;letter-spacing:8px;margin:10px 0" class="mono">${esc(s.code)}</div>
      <p class="muted small">Waiting for confirmation… this page updates by itself.</p>
      <button class="btn btn-ghost" data-v="reset">Cancel</button>`;
  } else if (s.stage === 'done') {
    body = `
      <p>✅ <b>${esc(s.phone)}</b> can receive calls from Divya.</p>
      <div class="row" style="gap:8px;margin-top:10px">
        <button class="btn btn-primary" data-v="call" ${s.busy ? 'disabled' : ''}>${icon('phone')}<span>${s.busy ? 'Calling…' : 'Call me now'}</span></button>
        <button class="btn btn-ghost" data-v="reset">Verify another number</button>
      </div>`;
  } else {
    body = `
      <form class="row" id="verify-form" style="gap:8px">
        <input class="input" name="name" placeholder="Your name" maxlength="80" style="flex:1;min-width:140px">
        <input class="input" name="phone" placeholder="Mobile, e.g. 98765 43210" required style="flex:1;min-width:160px">
        <input class="input" name="location" placeholder="City (optional)" maxlength="80" style="flex:1;min-width:120px">
        <button class="btn btn-primary" type="submit" ${s.busy ? 'disabled' : ''}>${s.busy ? 'Starting…' : 'Verify & get a call'}</button>
      </form>`;
  }
  return `
    <section class="card" style="margin-bottom:16px">
      <div class="card-head"><div><h2>Want Divya to call you?</h2>
        <p class="muted small">This demo runs on Twilio's free trial, which can only call verified numbers.
        Verify yours once (about 30 seconds): Twilio rings you and you type a 6-digit code.</p></div></div>
      <div class="card-pad">${body}
        ${s.err ? `<p class="small" style="color:var(--bad);margin-top:8px">${esc(s.err)}</p>` : ''}</div>
    </section>`;
}

export function bindVerifyPanel(el, redraw, onLeadAdded) {
  const s = state;
  const form = el.querySelector('#verify-form');
  if (form) form.onsubmit = async e => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(form));
    s.busy = true; s.err = ''; redraw();
    try {
      const r = await fetch(`${config.apiBaseUrl}/phone/verify`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: f.phone || '', name: f.name || '', location: f.location || '' }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || 'Could not start verification');
      Object.assign(s, { phone: j.phone, leadId: j.lead_id, code: j.code || '', stage: j.verified ? 'done' : 'code' });
      await onLeadAdded();
      if (!j.verified) startPolling(redraw);
    } catch (ex) { s.err = ex.message; }
    s.busy = false; redraw();
  };
  el.querySelectorAll('[data-v]').forEach(b => b.onclick = async () => {
    if (b.dataset.v === 'reset') { stopPolling(); Object.assign(s, { stage: 'form', code: '', err: '' }); redraw(); }
    if (b.dataset.v === 'call') {
      s.busy = true; s.err = ''; redraw();
      try {
        const r = await fetch(`${config.apiBaseUrl}/calls/now`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ lead_id: s.leadId }) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Could not start the call');
        toast('Calling you now. After Twilio\'s trial message, press any key to talk to Divya.');
        await onLeadAdded();
      } catch (ex) { s.err = ex.message; }
      s.busy = false; redraw();
    }
  });
}

function startPolling(redraw) {
  stopPolling();
  const started = Date.now();
  poll = setInterval(async () => {
    if (Date.now() - started > 3 * 60 * 1000) {
      stopPolling(); Object.assign(state, { stage: 'form', err: 'Verification timed out. Please try again.' }); redraw(); return;
    }
    try {
      const j = await (await fetch(`${config.apiBaseUrl}/phone/verify?phone=${encodeURIComponent(state.phone)}`)).json();
      if (j.verified) { stopPolling(); state.stage = 'done'; redraw(); toast('Number verified!'); }
    } catch {}
  }, 3000);
}

export function stopPolling() { if (poll) clearInterval(poll); poll = null; }
