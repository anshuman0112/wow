// Connects your Twilio number to Divya in Vapi, so she can make real phone calls.
//   npm run twilio
// Needs in .env: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER (e.g. +1415xxxxxxx), VAPI_PRIVATE_KEY.
// Also checks the Twilio account so problems (trial limits, unverified numbers) are explained clearly.
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { execSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const envPath = path.join(root, '.env');
let envText = readFileSync(envPath, 'utf8');
const env = Object.fromEntries(envText.split(/\r?\n/).map(l => l.match(/^([A-Z0-9_]+)=(.*)$/)).filter(Boolean).map(m => [m[1], m[2].trim()]));
const state = existsSync(path.join(root, 'vapi/.state.json')) ? JSON.parse(readFileSync(path.join(root, 'vapi/.state.json'), 'utf8')) : {};

const missing = ['TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_PHONE_NUMBER', 'VAPI_PRIVATE_KEY'].filter(k => !env[k]);
if (missing.length) { console.error(`✗ Missing in .env: ${missing.join(', ')}`); process.exit(1); }
if (!state.assistantId) { console.error('✗ Run `npm run sync` first (creates Divya).'); process.exit(1); }

const sid = env.TWILIO_ACCOUNT_SID, number = env.TWILIO_PHONE_NUMBER.replace(/[^\d+]/g, '');
const tw = async p => {
  const r = await fetch(`https://api.twilio.com/2010-04-01/Accounts/${sid}${p}`, {
    headers: { Authorization: 'Basic ' + Buffer.from(`${sid}:${env.TWILIO_AUTH_TOKEN}`).toString('base64') },
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`Twilio ${r.status}: ${j.message || 'request failed'}`);
  return j;
};

// 1. Check the Twilio account
let account;
try { account = await tw('.json'); } catch (e) { console.error(`✗ ${e.message}\n  Check TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN (Twilio Console → Account Info).`); process.exit(1); }
console.log(`✓ Twilio account OK (${account.type}, ${account.status})`);

const owned = await tw(`/IncomingPhoneNumbers.json?PhoneNumber=${encodeURIComponent(number)}`);
if (!owned.incoming_phone_numbers?.length) {
  console.error(`✗ ${number} is not a number you own in this Twilio account.\n  Twilio Console → Phone Numbers → Manage → Active numbers. Copy it exactly, e.g. +14155551234.`);
  process.exit(1);
}
console.log(`✓ You own ${number}`);

if (account.type === 'Trial') {
  const ids = await tw('/OutgoingCallerIds.json');
  const list = (ids.outgoing_caller_ids || []).map(x => x.phone_number);
  console.log(`! Trial account: Divya can only call these verified numbers: ${list.join(', ') || 'none yet'}`);
  console.log('  Add more: Twilio Console → Phone Numbers → Verified Caller IDs.');
  console.log('  Calling India? Twilio Console → Voice → Settings → Geo permissions → tick India.');
  console.log('  Trial calls start with a short Twilio message; press any key to continue the call.');
}

// 2. Import the number into Vapi (or reuse it if already imported)
const V = 'https://api.vapi.ai';
const vh = { Authorization: `Bearer ${env.VAPI_PRIVATE_KEY}`, 'Content-Type': 'application/json' };
const list = await (await fetch(`${V}/phone-number?limit=100`, { headers: vh })).json();
let phone = Array.isArray(list) ? list.find(p => p.number === number) : null;
const body = { assistantId: state.assistantId, name: 'WOW Voice Agent · Twilio' };
if (phone) {
  const r = await fetch(`${V}/phone-number/${phone.id}`, { method: 'PATCH', headers: vh, body: JSON.stringify(body) });
  if (!r.ok) { console.error('✗ Vapi update failed:', await r.text()); process.exit(1); }
  console.log(`✓ Number already in Vapi, linked to Divya (${phone.id})`);
} else {
  const r = await fetch(`${V}/phone-number`, {
    method: 'POST', headers: vh,
    body: JSON.stringify({ provider: 'twilio', number, twilioAccountSid: sid, twilioAuthToken: env.TWILIO_AUTH_TOKEN, ...body }),
  });
  const j = await r.json();
  if (!r.ok) { console.error('✗ Vapi import failed:', JSON.stringify(j)); process.exit(1); }
  phone = j;
  console.log(`✓ Number imported into Vapi and linked to Divya (${phone.id})`);
}

// 3. Save IDs for n8n's dialer and restart n8n so it sees them
const setVar = (k, v) => { envText = new RegExp(`^${k}=.*$`, 'm').test(envText) ? envText.replace(new RegExp(`^${k}=.*$`, 'm'), `${k}=${v}`) : envText + `\n${k}=${v}\n`; };
setVar('VAPI_PHONE_NUMBER_ID', phone.id);
setVar('VAPI_ASSISTANT_ID', state.assistantId);
writeFileSync(envPath, envText);
console.log('✓ .env updated (VAPI_PHONE_NUMBER_ID, VAPI_ASSISTANT_ID)');
// Switch the dashboard's "Call now" from browser calls to real phone calls
const cfgPath = path.join(root, 'web/js/config.js');
writeFileSync(cfgPath, readFileSync(cfgPath, 'utf8').replace(/phoneCalling: (true|false)/, 'phoneCalling: true'));
console.log('✓ Dashboard "Call now" now rings real phones (run npm run deploy to update the live site)');
try {
  execSync('docker compose up -d --force-recreate', { cwd: root, stdio: 'ignore' });
  execSync('node scripts/n8n_activate.js', { cwd: root, stdio: 'inherit' });
  console.log('\n✓ Done. Use "Call now" on the Leads page, or new leads are auto-called 10 AM–7 PM IST.');
} catch { console.log('! Finish with: npm run n8n:activate'); }
