// Rings a real phone and connects it to Divya — works on a FREE Twilio trial.
//   npm run call -- +916360246901 [Name]
//
// How: Twilio dials the phone from your trial number. When it's answered, Twilio bridges the
// call into Divya's free Vapi SIP line (VAPI_SIP_URI). No Vapi phone-number import needed.
// Trial limits: you can only call numbers verified in Twilio, and Twilio plays a short trial
// message first ("press any key").
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const env = Object.fromEntries(readFileSync(path.join(root, '.env'), 'utf8').split(/\r?\n/)
  .map(l => l.match(/^([A-Z0-9_]+)=(.*)$/)).filter(Boolean).map(m => [m[1], m[2].trim()]));

const to = (process.argv[2] || '').replace(/[^\d+]/g, '');
const name = process.argv[3] || '';
const missing = ['TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_PHONE_NUMBER', 'VAPI_SIP_URI'].filter(k => !env[k]);
if (missing.length) { console.error(`✗ Missing in .env: ${missing.join(', ')}`); process.exit(1); }
if (!/^\+\d{10,15}$/.test(to)) { console.error('Usage: npm run call -- +916360246901 [Name]'); process.exit(1); }

// Trial accounts can't send TwiML inline, so Twilio fetches it from n8n (WF3 "TwiML for Twilio").
if (!env.N8N_PUBLIC_URL) { console.error('✗ N8N_PUBLIC_URL is empty — run npm run tunnel first.'); process.exit(1); }
const twimlUrl = `${env.N8N_PUBLIC_URL}/webhook/twiml-aanya${name ? `?name=${encodeURIComponent(name)}` : ''}`;

const res = await fetch(`https://api.twilio.com/2010-04-01/Accounts/${env.TWILIO_ACCOUNT_SID}/Calls.json`, {
  method: 'POST',
  headers: {
    Authorization: 'Basic ' + Buffer.from(`${env.TWILIO_ACCOUNT_SID}:${env.TWILIO_AUTH_TOKEN}`).toString('base64'),
    'Content-Type': 'application/x-www-form-urlencoded',
  },
  body: new URLSearchParams({ To: to, From: env.TWILIO_PHONE_NUMBER, Url: twimlUrl }),
});
const j = await res.json();
if (!res.ok) {
  console.error(`✗ Twilio refused (${res.status}): ${j.message}`);
  if (j.code === 21219 || /verified/i.test(j.message || '')) console.error('  → Trial accounts can only call verified numbers: Twilio Console → Phone Numbers → Verified Caller IDs.');
  if (j.code === 21215 || /geo|permission/i.test(j.message || '')) console.error('  → Enable India: Twilio Console → Voice → Settings → Geo permissions → tick India.');
  process.exit(1);
}
console.log(`✓ Ringing ${to} now (Twilio call ${j.sid}). Answer, press any key after the trial message, and Divya will speak.`);
