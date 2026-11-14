import { isLive } from '../config.js';
import { esc } from '../ui.js';

const items = [
  { name: 'Vapi', role: 'Runs the live voice call (listening, interruptions, recording, analysis)', ok: () => isLive.vapi(), keys: 'Public key + assistant ID in config.js', url: 'https://vapi.ai' },
  { name: 'Groq', role: 'The brain — Llama 3.3 70B, free tier, very low latency', ok: null, keys: 'Paste the API key in Vapi → Providers', url: 'https://console.groq.com' },
  { name: 'ElevenLabs', role: "Aanya's voice — Flash v2.5, English + Hindi", ok: null, keys: 'Paste the API key in Vapi → Providers', url: 'https://elevenlabs.io' },
  { name: 'Deepgram', role: 'Speech to text (nova-3 multi, Hinglish)', ok: null, keys: 'Included through Vapi', url: 'https://deepgram.com' },
  { name: 'Supabase', role: 'Database for leads and calls + recording storage', ok: () => isLive.supabase(), keys: 'URL + anon key in config.js', url: 'https://supabase.com' },
  { name: 'n8n', role: 'Automations: lead import, auto-dialer, end-of-call save, alerts', ok: () => isLive.n8n(), keys: 'Webhook base URL (ngrok) in config.js', url: 'https://n8n.io' },
  { name: 'Twilio', role: 'Phone line for real outbound calls', ok: null, keys: 'Imported into Vapi → Phone numbers', url: 'https://twilio.com' },
];

export default async function integrations(el) {
  el.innerHTML = `
    <div class="page-head">
      <div><h1>Integrations</h1><p class="muted">Private keys live in Vapi, n8n and .env — never in this web page</p></div>
    </div>
    <div class="grid g-2">
      ${items.map(i => {
        const st = i.ok ? (i.ok() ? ['Connected', 'b-ok'] : ['Not connected', '']) : ['Configured in Vapi', 'b-brand'];
        return `
        <section class="card card-pad">
          <div class="row"><h2>${esc(i.name)}</h2><span class="spacer"></span><span class="badge ${st[1]}">${st[0]}</span></div>
          <p class="muted" style="margin-top:6px">${esc(i.role)}</p>
          <p class="small faint" style="margin-top:10px">${esc(i.keys)} · <a href="${i.url}" target="_blank" rel="noopener">${esc(i.url.replace('https://', ''))}</a></p>
        </section>`;
      }).join('')}
    </div>`;
}
