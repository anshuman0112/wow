import { config, isLive } from '../config.js';
import { esc } from '../ui.js';

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
  let health = null;
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
    <div class="grid g-2">
      ${items.map(i => { const st = status(i); return `
        <section class="card card-pad">
          <div class="row"><h2>${esc(i.name)}</h2><span class="spacer"></span><span class="badge ${st[1]}">${esc(st[0])}</span></div>
          <p class="muted" style="margin-top:6px">${esc(i.role)}</p>
          <p class="small faint" style="margin-top:10px">${esc(i.keys)} · <a href="${i.url}" target="_blank" rel="noopener">${esc(i.url.replace('https://', ''))}</a></p>
        </section>`; }).join('')}
    </div>`;
}
