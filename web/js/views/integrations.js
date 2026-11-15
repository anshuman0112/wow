import { config, isLive } from '../config.js';
import { esc, icon, toast, fmtDate } from '../ui.js';

const items = [
  { name: 'Python API (FastAPI)', role: 'Backend: runs phone conversations, saves every call, imports leads (with duplicate checks), verifies numbers', key: 'api', keys: '/api on Vercel · keys in Vercel env vars', url: 'https://vaani-divyasree.vercel.app/api/health' },
  { name: 'Twilio (free trial)', role: "Real phone calls to verified numbers: rings the lead, turns their speech into text, and speaks Divya's replies in the voice chosen on the Voices page. Trial: no call recording.", key: 'phone', keys: 'Account SID + token in backend env vars', url: 'https://twilio.com' },
  { name: 'Groq (free tier)', role: "Divya's brain on phone calls, the AI summary and hot / warm / cold score after each call, and lead column mapping", key: 'groq', keys: 'GROQ_API_KEY in backend env vars', url: 'https://console.groq.com' },
  { name: 'Upstash Redis (free)', role: 'Live phone-call memory and instant zero-token answers to the most-asked questions', key: 'redis', keys: 'REST URL + token in backend env vars', url: 'https://upstash.com' },
  { name: 'Supabase', role: 'Database for leads and calls + recording storage', ok: () => isLive.supabase(), keys: 'URL + publishable key in config.js; secret key only on the backend', url: 'https://supabase.com' },
  { name: 'Vapi', role: 'Browser calls (Talk to Divya): listening, interruptions and recording', ok: () => isLive.vapi(), keys: 'Public key + assistant ID in config.js (locked to this site)', url: 'https://vapi.ai' },
  { name: 'ElevenLabs', role: "Divya's voice on browser calls (Flash v2.5, English + Hindi)", ok: null, keys: 'Used through Vapi', url: 'https://elevenlabs.io' },
  { name: 'Deepgram', role: 'Speech to text on browser calls (nova-3 multi, Hinglish)', ok: null, keys: 'Included through Vapi', url: 'https://deepgram.com' },
];

export default async function integrations(el) {
  let health = null, sources = null;
  try { sources = await (await fetch(`${config.apiBaseUrl}/leads/sources`)).json(); } catch {}
  try { const pc = await (await fetch(`${config.apiBaseUrl}/config`)).json(); if (sources) sources.inbound = pc.inboundNumber; } catch {}
  try { health = await (await fetch(`${config.apiBaseUrl}/health`)).json(); } catch {}
  const c = health?.configured || {};
  const status = i => {
    if (i.key === 'api') return health?.ok ? ['Online', 'b-ok'] : ['Unreachable', 'b-bad'];
    if (i.key === 'phone') return c.phone_line && c.phone_line !== 'none' ? [`Connected · ${c.phone_line}`, 'b-ok'] : ['Not connected', ''];
    if (i.key === 'groq') return c.groq ? ['Connected', 'b-ok'] : ['Not connected', ''];
    if (i.key === 'redis') return health?.redis?.enabled ? [`Connected · ${health.redis.ping_ms} ms`, 'b-ok'] : ['Not connected', ''];
    if (i.ok) return i.ok() ? ['Connected', 'b-ok'] : ['Not connected', ''];
    return ['Via Vapi', 'b-brand'];
  };
  el.innerHTML = `
    <div class="page-head">
      <div><h1>Integrations</h1><p class="muted">Private keys live only in the backend's environment — never in this web page</p></div>
    </div>
    ${sourcesSection(sources)}
    <h2 style="margin:8px 0 12px">Services</h2>
    <div class="grid g-2">
      ${items.map(i => { const st = status(i); return `
        <section class="card card-pad">
          <div class="row"><h2>${esc(i.name)}</h2><span class="spacer"></span><span class="badge ${st[1]}">${esc(st[0])}</span></div>
          <p class="muted" style="margin-top:6px">${esc(i.role)}</p>
          <p class="small faint" style="margin-top:10px">${esc(i.keys)} · <a href="${i.url}" target="_blank" rel="noopener">${esc(i.url.replace('https://', ''))}</a></p>
        </section>`; }).join('')}
    </div>`;
}

// ── Lead sources: every lead lands here automatically and Divya calls it within seconds ──
const SITE = ['localhost', '127.0.0.1'].includes(location.hostname) ? 'https://vaani-divyasree.vercel.app' : location.origin;
const fmtSecs = s => s == null ? '—' : s < 90 ? `${s} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${Math.round(s / 3600)} h`;

function sourcesSection(src) {
  if (!src) return '<p class="muted">Could not load lead sources.</p>';
  const c = src.connected || {};
  const card = (name, on, onText, offText, url, body, tests) => `
    <section class="card card-pad">
      <div class="row"><h2>${name}</h2><span class="spacer"></span><span class="badge ${on ? 'b-ok' : 'b-gold'}">${on ? onText : offText}</span></div>
      <p class="muted small" style="margin-top:6px">${body}</p>
      ${url ? `<div class="row small" style="margin-top:8px;gap:6px;flex-wrap:nowrap"><code class="mono" style="overflow:auto;white-space:nowrap;flex:1">${esc(url)}</code>
        <button class="btn btn-ghost small" data-copy="${esc(url)}">Copy</button></div>` : ''}
      <div class="row" style="margin-top:10px;gap:6px">${tests}</div>
    </section>`;
  const test = (key, label) => `<button class="btn small" data-test="${key}">${icon('upload')}Send test lead${label ? ` (${label})` : ''}</button>`;
  return `
    <h2 style="margin:0 0 6px">Lead sources</h2>
    <p class="muted small" style="margin-bottom:12px">New leads from any of these appear in Leads automatically, without duplicates, and Divya calls them within seconds (Settings → New leads, calling hours apply).</p>
    <div class="grid g-2" style="margin-bottom:12px">
      ${card('Website form', true, 'Live', '', `${SITE}/enquire.html`,
        'A ready-made enquiry page for ads and your website. Link to it, or post your own form to the webhook below.',
        `<a class="btn btn-ghost small" href="${SITE}/enquire.html" target="_blank" rel="noopener">Open the form</a>${test('website')}`)}
      ${card('Facebook + Instagram lead ads', c.meta, 'Connected', c.meta_verify_ready ? 'Needs your Meta app' : 'Not set up', `${SITE}/api/leads/meta`,
        'One Meta connection covers both. Set this as the webhook (field: leadgen) in your free Meta app. Steps: docs/LEAD_SOURCES.md.',
        `${test('meta', 'Facebook')}${test('instagram', 'Instagram')}`)}
      ${card('Google Ads lead forms', c.google, 'Key ready', 'Not set up', `${SITE}/api/leads/google`,
        'Paste this URL and your key (GOOGLE_ADS_KEY) into the lead form\'s webhook in Google Ads.', test('google'))}
      ${card('Inbound phone line (24/7)', !!src.inbound, 'Live', 'Not set up', src.inbound || '',
        'Leads can call Divya any time. She answers "Thank you for calling Divyasree Developers…", qualifies them the same way, and the caller is saved as a lead (source: Inbound call). A free Vapi US number; calls use Vapi credit and callers from India pay international rates.', '')}
      ${card('Google Forms, Typeform, any tool', true, 'Live', '', `${SITE}/api/leads/inbound`,
        'Any form or tool that can send JSON {name, phone, location, budget, source}. A ready Google Forms script is in docs/LEAD_SOURCES.md.', '')}
    </div>
    <section class="card" style="margin-bottom:24px">
      <div class="card-head"><h2>Leads by source</h2><span class="muted small">time to first call = from arriving to the phone ringing</span></div>
      <div class="table-wrap"><table>
        <thead><tr><th>Source</th><th>Leads</th><th>Last lead</th><th>Avg time to first call</th></tr></thead>
        <tbody>${(src.by_source || []).map(r => `<tr><td>${esc(r.source)}</td><td class="mono">${r.leads}</td>
          <td>${r.last_lead_at ? fmtDate(r.last_lead_at) : '—'}</td><td class="mono">${fmtSecs(r.avg_seconds_to_first_call)}</td></tr>`).join('')
          || '<tr><td colspan="4" class="empty">No leads yet.</td></tr>'}</tbody>
      </table></div>
    </section>`;
}

document.addEventListener('click', async e => {
  const copy = e.target.closest('[data-copy]');
  if (copy) { try { await navigator.clipboard.writeText(copy.dataset.copy); toast('Copied'); } catch { toast(copy.dataset.copy); } return; }
  const t = e.target.closest('[data-test]');
  if (!t) return;
  let pin = '';
  try { pin = JSON.parse(localStorage.getItem('wow-session') || 'null')?.token ? 'signed-in' : sessionStorage.getItem('wow-admin-pin') || ''; } catch {}
  if (!pin) pin = window.prompt('Admin PIN (same as Settings):') || '';
  if (!pin) return;
  const phone = window.prompt('Phone number for the test lead (a verified number gets a real call):', '+91 90000 00999');
  if (!phone) return;
  t.disabled = true;
  try {
    const r = await fetch(`${config.apiBaseUrl}/leads/test/${t.dataset.test}`, { method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Admin-Pin': pin }, body: JSON.stringify({ phone, name: 'Test Lead' }) });
    const j = await r.json().catch(() => ({}));
    if (r.status === 401) { try { sessionStorage.removeItem('wow-admin-pin'); } catch {} throw new Error('Wrong PIN'); }
    if (!r.ok) throw new Error(j.detail || `Test failed (${r.status})`);
    try { sessionStorage.setItem('wow-admin-pin', pin); } catch {}
    toast(`${j.source}: ${j.new ? 'new lead added' : `duplicate (${j.duplicate})`} · call: ${j.call}${j.reason ? ` (${j.reason.slice(0, 80)})` : ''}`);
  } catch (err) { toast(err.message); }
  t.disabled = false;
});
