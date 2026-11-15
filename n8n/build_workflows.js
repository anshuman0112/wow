// Generates the four importable n8n workflows into n8n/workflows/*.json
//   node n8n/build_workflows.js
import { writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { workflow, webhook, schedule, code, ifTrue, wait, respond, http, SUPA, VAPI, GROQ } from './lib.js';

const at_respondXml = (name, col, row) => {
  const n = respond(name, '', col, row);
  n.parameters = {
    respondWith: 'text',
    responseBody: "={{ '<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Dial><Sip>' + $env.VAPI_SIP_URI + '?X-Lead-Id=' + ($json.query?.lead || '') + '</Sip></Dial></Response>' }}",
    options: { responseHeaders: { entries: [{ name: 'Content-Type', value: 'text/xml' }] } },
  };
  return n;
};
const out = path.join(path.dirname(fileURLToPath(import.meta.url)), 'workflows');
const SB = '={{ $env.SUPABASE_URL }}';
const json = expr => `={{ JSON.stringify(${expr}) }}`;

// ─────────────────────────────────────────────────────────────────────────────
// WF4 · End-of-call save: Vapi report → Supabase (call row, recording, lead) → hot alert
// ─────────────────────────────────────────────────────────────────────────────
const wf4 = workflow('WF4 · End-of-call save (Vapi → Supabase)', [
  webhook('Vapi events', 'vapi-events', 0, 0),
  ifTrue('Is end-of-call report?', "={{ $json.body?.message?.type === 'end-of-call-report' }}", 1, 0),
  wait('Wait for AI analysis', 8, 2, 0),
  http('Fetch full call from Vapi', {
    url: "=https://api.vapi.ai/call/{{ $('Vapi events').first().json.body.message.call.id }}",
    headers: VAPI, continueOnFail: true,
  }, 3, 0),
  code('Build call row', String.raw`
// Combine the webhook report with the freshly fetched call (which has the AI analysis attached).
const msg = $('Vapi events').first().json.body.message;
const fetched = $input.first().json || {};
const call = fetched.id ? fetched : (msg.call || {});
const art = { ...(msg.artifact || {}), ...(fetched.artifact || {}) };

// AI analysis (Vapi Structured Output named "Lead Qualification")
const outputs = Object.values(art.structuredOutputs || {});
const q = (outputs.find(o => o && o.name === 'Lead Qualification') || {}).result || {};

// Conversation: keep only Aanya ("bot") and the lead ("user")
const messages = (art.messages || msg.messages || [])
  .filter(m => ['bot', 'assistant', 'user'].includes(m.role))
  .map(m => ({ role: m.role === 'user' ? 'user' : 'assistant', text: m.message || m.content || '', t: m.secondsFromStart }));
const aiLines = messages.filter(m => m.role === 'assistant').map(m => m.text).join('\n');
const transcript = art.transcript || messages.map(m => (m.role === 'user' ? 'Lead: ' : 'Aanya: ') + m.text).join('\n');

// Vapi recordings live in a private bucket; only the presigned links (valid ~30 min) can be downloaded.
const recordingUrl = art.presignedMonoUrl || art.presignedStereoUrl || art.recordingUrl || art.recording?.mono?.combinedUrl || msg.recordingUrl || null;
const startedAt = msg.startedAt || call.startedAt || null;
const endedAt = msg.endedAt || call.endedAt || null;
const duration = msg.durationSeconds ?? (startedAt && endedAt ? (new Date(endedAt) - new Date(startedAt)) / 1000 : null);
const vars = call.assistantOverrides?.variableValues || {};
// Phone calls carry the lead in call.metadata; browser calls started from a lead carry it in the overrides.
const leadId = call.metadata?.lead_id || call.assistantOverrides?.metadata?.lead_id || vars.lead_id || null;
const ext = (recordingUrl || '').split('?')[0].split('.').pop() || 'wav';
const id = call.id || msg.call?.id;

const row = {
  vapi_call_id: id,
  lead_id: /^[0-9a-f-]{36}$/i.test(leadId || '') ? leadId : null,
  name: call.customer?.name || vars.name || null,
  phone: call.customer?.number || null,
  call_type: call.type || null,
  started_at: startedAt,
  ended_at: endedAt,
  duration_sec: duration,
  ended_reason: msg.endedReason || call.endedReason || null,
  cost_usd: msg.cost ?? call.cost ?? null,
  recording_url: null,            // set below to a long-lived Supabase playback link
  transcript,
  ai_lines: aiLines,
  messages,
  summary: q.summary || msg.analysis?.summary || art.summary || null,
  interest: ['hot', 'warm', 'cold'].includes(q.interest) ? q.interest : null,
  intent: q.intent || null,
  geography_fit: q.geography_fit || null,
  budget_fit: q.budget_fit || null,
  timeline_fit: q.timeline_fit || null,
  sentiment_start: q.sentiment_start || null,
  sentiment_end: q.sentiment_end || null,
  language: q.language || null,
  callback_time: q.callback_time || null,
  do_not_call: q.do_not_call === true,
  analysis: q,
  raw: msg,
};
// Never overwrite saved data with blanks (e.g. if the Vapi fetch failed): drop empty fields.
const isEmpty = v => v === null || v === undefined || v === '' ||
  (Array.isArray(v) && v.length === 0) || (typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length === 0);
for (const k of Object.keys(row)) if (isEmpty(row[k])) delete row[k];
if (!fetched.id && !msg.artifact) delete row.do_not_call;
return [{ json: { row, lead_id: row.lead_id || null, phone: row.phone || null, recordingUrl, storagePath: id + '.' + ext } }];
`, 4, 0),
  http('Save call to Supabase', {
    method: 'POST', url: `${SB}/rest/v1/calls?on_conflict=vapi_call_id`,
    headers: { ...SUPA, Prefer: 'resolution=merge-duplicates,return=minimal' },
    body: json('$json.row'),
  }, 5, 0),

  // Branch A: update the lead's status / interest
  code('Prepare lead update', String.raw`
const b = $('Build call row').first().json;
const r = b.row;
if (!b.lead_id && !b.phone) return [];          // browser demo call: no lead to update
const reason = r.ended_reason || '';
const noAnswer = ['did-not-answer', 'customer-busy', 'voicemail', 'failed-to-connect', 'no-answer'].some(x => reason.includes(x));
const patch = {
  status: r.do_not_call ? 'do_not_call' : (noAnswer ? 'no_answer' : 'called'),
  last_called_at: r.ended_at || new Date().toISOString(),
};
if (!noAnswer && r.interest) patch.interest = r.interest;
if (!noAnswer && r.callback_time) patch.callback_time = r.callback_time;
const filter = b.lead_id ? 'id=eq.' + b.lead_id : 'phone=eq.' + encodeURIComponent(b.phone);
return [{ json: { filter, patch } }];
`, 6, 0),
  http('Update lead', {
    method: 'PATCH', url: `${SB}/rest/v1/leads?{{ $json.filter }}`,
    headers: { ...SUPA, Prefer: 'return=minimal' }, body: json('$json.patch'),
  }, 7, 0),

  // Branch B: copy the recording into Supabase Storage
  ifTrue('Has recording?', "={{ !!$('Build call row').first().json.recordingUrl }}", 6, 1),
  http('Download recording', { url: "={{ $('Build call row').first().json.recordingUrl }}", fileOut: true, continueOnFail: true, timeoutMs: 180000 }, 7, 1),
  http('Upload to Storage', {
    method: 'POST', url: `${SB}/storage/v1/object/recordings/{{ $('Build call row').first().json.storagePath }}`,
    headers: { apikey: SUPA.apikey, Authorization: SUPA.Authorization, 'x-upsert': 'true' },
    binaryIn: 'data', continueOnFail: true, timeoutMs: 180000,
  }, 8, 1),
  http('Create playback link', {
    method: 'POST', url: `${SB}/storage/v1/object/sign/recordings/{{ $('Build call row').first().json.storagePath }}`,
    headers: SUPA, body: '={{ JSON.stringify({ expiresIn: 31536000 }) }}',   // 1 year
    continueOnFail: true,
  }, 9, 1),
  http('Save storage path', {
    method: 'PATCH', url: `${SB}/rest/v1/calls?vapi_call_id=eq.{{ $('Build call row').first().json.row.vapi_call_id }}`,
    headers: { ...SUPA, Prefer: 'return=minimal' },
    body: "={{ JSON.stringify({ storage_path: 'recordings/' + $('Build call row').first().json.storagePath, recording_url: $json.signedURL ? $env.SUPABASE_URL + '/storage/v1' + $json.signedURL : null }) }}",
    continueOnFail: true,
  }, 10, 1),

  // Branch C: alert on hot leads (Telegram, optional)
  ifTrue('Is hot lead?', "={{ $('Build call row').first().json.row.interest === 'hot' && !!$env.TELEGRAM_BOT_TOKEN }}", 6, 2),
  http('Send Telegram alert', {
    method: 'POST', url: '=https://api.telegram.org/bot{{ $env.TELEGRAM_BOT_TOKEN }}/sendMessage',
    headers: { 'Content-Type': 'application/json' },
    body: "={{ JSON.stringify({ chat_id: $env.TELEGRAM_CHAT_ID, text: '🔥 Hot lead: ' + ($('Build call row').first().json.row.name || 'Web caller') + '\\nCallback: ' + ($('Build call row').first().json.row.callback_time || '—') + '\\n\\n' + ($('Build call row').first().json.row.summary || '') }) }}",
    continueOnFail: true,
  }, 7, 2),
], [
  ['Vapi events', 'Is end-of-call report?'],
  ['Is end-of-call report?', 'Wait for AI analysis', 0],
  ['Wait for AI analysis', 'Fetch full call from Vapi'],
  ['Fetch full call from Vapi', 'Build call row'],
  ['Build call row', 'Save call to Supabase'],
  ['Save call to Supabase', 'Prepare lead update'],
  ['Save call to Supabase', 'Has recording?'],
  ['Save call to Supabase', 'Is hot lead?'],
  ['Prepare lead update', 'Update lead'],
  ['Has recording?', 'Download recording', 0],
  ['Download recording', 'Upload to Storage'],
  ['Upload to Storage', 'Create playback link'],
  ['Create playback link', 'Save storage path'],
  ['Is hot lead?', 'Send Telegram alert', 0],
], { active: true, id: 'iCvnbx7Iy6Ix63Va' });

// ─────────────────────────────────────────────────────────────────────────────
// WF2 · Lead import: (a) AI column mapping, (b) clean + save leads
// ─────────────────────────────────────────────────────────────────────────────
const wf2 = workflow('WF2 · Lead import (any file → leads)', [
  webhook('Mapping request', 'lead-map', 0, 0, { respond: 'responseNode' }),
  code('Build mapping prompt', String.raw`
const { headers = [], sample = [] } = $input.first().json.body || {};
const system = 'You map spreadsheet columns to a CRM lead schema. Fields: name, phone, email, location, budget, notes. ' +
  'Use "extra" for anything else. Each field may be used at most once, except "extra". Reply with JSON only: {"mapping": {"<column>": "<field>"}}.';
const user = 'Columns: ' + JSON.stringify(headers) + '\nSample rows: ' + JSON.stringify(sample.slice(0, 5));
return [{ json: { headers, messages: [{ role: 'system', content: system }, { role: 'user', content: user }] } }];
`, 1, 0),
  http('Ask Groq for mapping', {
    method: 'POST', url: 'https://api.groq.com/openai/v1/chat/completions', headers: GROQ,
    body: "={{ JSON.stringify({ model: 'openai/gpt-oss-120b', reasoning_effort: 'low', temperature: 0, response_format: { type: 'json_object' }, messages: $json.messages }) }}",
    continueOnFail: true,
  }, 2, 0),
  code('Read mapping', String.raw`
const allowed = ['name', 'phone', 'email', 'location', 'budget', 'notes', 'extra'];
const headers = $('Build mapping prompt').first().json.headers;
let mapping = null;
try {
  const parsed = JSON.parse($input.first().json.choices[0].message.content).mapping || {};
  mapping = {};
  for (const h of headers) mapping[h] = allowed.includes(parsed[h]) ? parsed[h] : 'extra';
} catch (e) { mapping = null; }          // browser falls back to keyword matching
return [{ json: { mapping } }];
`, 3, 0),
  respond('Return mapping', '={{ JSON.stringify({ mapping: $json.mapping }) }}', 4, 0),

  webhook('Import request', 'lead-import', 0, 1, { respond: 'responseNode' }),
  code('Clean leads', String.raw`
// Server-side safety net: normalise phones, drop invalid rows, dedupe, whitelist fields.
const rows = ($input.first().json.body || {}).leads || [];
const norm = raw => {
  let p = String(raw || '').replace(/[^\d+]/g, '');
  if (p.startsWith('00')) p = '+' + p.slice(2);
  if (!p.startsWith('+')) {
    if (p.length === 10) p = '+91' + p;
    else if (p.length === 12 && p.startsWith('91')) p = '+' + p;
    else if (p.length === 11 && p.startsWith('0')) p = '+91' + p.slice(1);
  }
  return /^\+\d{10,15}$/.test(p) ? p : null;
};
const seen = new Set();
const leads = [];
for (const r of rows) {
  const phone = norm(r.phone);
  if (!phone || seen.has(phone)) continue;
  seen.add(phone);
  leads.push({
    phone,
    name: r.name ? String(r.name).slice(0, 120) : null,
    email: r.email || null, location: r.location || null, budget: r.budget || null,
    notes: r.notes || null, source: r.source || 'upload',
    extra: r.extra && typeof r.extra === 'object' ? r.extra : {},
    campaign_id: 'divyasree-wow',
  });
}
return [{ json: { leads, received: rows.length } }];
`, 1, 1),
  http('Save new leads', {
    method: 'POST', url: `${SB}/rest/v1/leads?on_conflict=phone`,
    headers: { ...SUPA, Prefer: 'resolution=ignore-duplicates,return=representation' },
    body: json('$json.leads'),
  }, 2, 1),
  code('Count imported', String.raw`
const imported = $input.all().filter(i => i.json && i.json.id).length;
const received = $('Clean leads').first().json.received;
return [{ json: { imported, received, skipped: received - imported } }];
`, 3, 1),
  respond('Return result', '={{ JSON.stringify($json) }}', 4, 1),
], [
  ['Mapping request', 'Build mapping prompt'],
  ['Build mapping prompt', 'Ask Groq for mapping'],
  ['Ask Groq for mapping', 'Read mapping'],
  ['Read mapping', 'Return mapping'],
  ['Import request', 'Clean leads'],
  ['Clean leads', 'Save new leads'],
  ['Save new leads', 'Count imported'],
  ['Count imported', 'Return result'],
], { active: true, id: 'MYXhLGo8hP9VnaPJ' });
wf2.nodes.find(n => n.name === 'Save new leads').alwaysOutputData = true;

// ─────────────────────────────────────────────────────────────────────────────
// WF3 · Auto-dialer: every 5 min (10 AM–7 PM IST) call new / no-answer leads via Vapi + Twilio
// ─────────────────────────────────────────────────────────────────────────────
const wf3 = workflow('WF3 · Auto-dialer + Call now (Vapi + Twilio)', [
  schedule('Every 5 minutes', 5, 0, 0),

  // Twilio asks this URL what to do when the lead answers → connect them to Aanya's SIP line.
  webhook('TwiML for Twilio', 'twiml-aanya', 0, 2, { respond: 'responseNode' }),
  at_respondXml('Reply: connect to Aanya', 1, 2),

  // "Call now" button on the dashboard → call one lead immediately (any time of day)
  webhook('Call now request', 'call-now', 0, 1),
  code('Check lead id', String.raw`
const id = ($input.first().json.body || {}).lead_id || '';
if (!/^[0-9a-f-]{36}$/i.test(id)) throw new Error('Send {"lead_id": "<uuid>"}');
if (!$env.VAPI_PHONE_NUMBER_ID && !($env.TWILIO_ACCOUNT_SID && $env.TWILIO_AUTH_TOKEN && $env.VAPI_SIP_URI)) throw new Error('No phone line: add Twilio keys to .env (free bridge) or run npm run twilio');
return [{ json: { id } }];
`, 1, 1),
  http('Get that lead', {
    url: `${SB}/rest/v1/leads?select=id,name,phone,location,attempts,status&id=eq.{{ $json.id }}&status=neq.do_not_call`,
    headers: SUPA,
  }, 2, 1),
  code('Calling hours check', String.raw`
const hour = Number(new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', hour12: false }).format(new Date()));
if (hour < 10 || hour >= 19) return [];               // only call 10:00–18:59 IST
if (!$env.VAPI_PHONE_NUMBER_ID && !($env.TWILIO_ACCOUNT_SID && $env.TWILIO_AUTH_TOKEN && $env.VAPI_SIP_URI)) {
  throw new Error('No phone line: add Twilio keys to .env (free bridge) or run npm run twilio.');
}
return [{ json: { hour } }];
`, 1, 0),
  http('Get leads to call', {
    url: `${SB}/rest/v1/leads?select=id,name,phone,location,attempts&status=in.(new,no_answer)&attempts=lt.2&order=created_at.asc&limit={{ $env.DIALER_BATCH || 2 }}`,
    headers: SUPA,
  }, 2, 0),
  http('Mark as calling', {
    method: 'PATCH', url: `${SB}/rest/v1/leads?id=eq.{{ $json.id }}`,
    headers: { ...SUPA, Prefer: 'return=representation' },
    body: "={{ JSON.stringify({ status: 'calling', attempts: ($json.attempts || 0) + 1, last_called_at: new Date().toISOString() }) }}",
  }, 3, 0),
  ifTrue('Use free Twilio bridge?', '={{ !$env.VAPI_PHONE_NUMBER_ID }}', 4, 1),
  http('Ring via Twilio bridge', {
    method: 'POST', url: '=https://api.twilio.com/2010-04-01/Accounts/{{ $env.TWILIO_ACCOUNT_SID }}/Calls.json',
    headers: { Authorization: "={{ 'Basic ' + ($env.TWILIO_ACCOUNT_SID + ':' + $env.TWILIO_AUTH_TOKEN).base64Encode() }}" },
    form: {
      To: '={{ $json.phone }}',
      From: '={{ $env.TWILIO_PHONE_NUMBER }}',
      // Trial accounts can't send TwiML inline, so Twilio fetches it from our n8n webhook.
      Url: "={{ $env.N8N_PUBLIC_URL + '/webhook/twiml-aanya?lead=' + $json.id }}",
    },
    continueOnFail: true,
  }, 5, 1),
  http('Start Vapi phone call', {
    method: 'POST', url: 'https://api.vapi.ai/call', headers: VAPI,
    body: "={{ JSON.stringify({ assistantId: $env.VAPI_ASSISTANT_ID, phoneNumberId: $env.VAPI_PHONE_NUMBER_ID, customer: { number: $json.phone, name: $json.name || undefined }, assistantOverrides: { variableValues: { name: ($json.name || '').split(' ')[0], location: $json.location || '' } }, metadata: { lead_id: $json.id, campaign_id: 'divyasree-wow' } }) }}",
    continueOnFail: true,
  }, 5, 0),
  ifTrue('Call failed to start?', '={{ !!$json.error }}', 6, 0),
  http('Mark as no answer', {
    method: 'PATCH', url: `${SB}/rest/v1/leads?id=eq.{{ $('Mark as calling').item.json.id }}`,
    headers: { ...SUPA, Prefer: 'return=minimal' },
    body: "={{ JSON.stringify({ status: 'no_answer' }) }}",
  }, 7, 0),
], [
  ['Every 5 minutes', 'Calling hours check'],
  ['Calling hours check', 'Get leads to call'],
  ['Get leads to call', 'Mark as calling'],
  ['TwiML for Twilio', 'Reply: connect to Aanya'],
  ['Call now request', 'Check lead id'],
  ['Check lead id', 'Get that lead'],
  ['Get that lead', 'Mark as calling'],
  ['Mark as calling', 'Use free Twilio bridge?'],
  ['Use free Twilio bridge?', 'Ring via Twilio bridge', 0],
  ['Use free Twilio bridge?', 'Start Vapi phone call', 1],
  ['Ring via Twilio bridge', 'Call failed to start?'],
  ['Start Vapi phone call', 'Call failed to start?'],
  ['Call failed to start?', 'Mark as no answer', 0],
], { active: false, id: '8VpOqJuNDWQenrOf' });   // turn on only after Twilio is connected

// ─────────────────────────────────────────────────────────────────────────────
// WF1 · Knowledge builder: any business text → clean fact sheet (for reusing Vaani with a new client)
// ─────────────────────────────────────────────────────────────────────────────
const wf1 = workflow('WF1 · Knowledge builder (document → fact sheet)', [
  webhook('Knowledge request', 'knowledge-build', 0, 0, { respond: 'responseNode' }),
  code('Build extraction prompt', String.raw`
const { text = '', campaign_id = 'divyasree-wow' } = $input.first().json.body || {};
if (text.length < 50) throw new Error('Send the document text in the "text" field.');
const system = 'You turn a business document into a fact sheet for a phone sales agent. ' +
  'Copy facts exactly as written; never add, infer, round or guess anything. ' +
  'Group into sections such as Overview, Pricing, Location, Nearby, Amenities, Timeline, FAQs (skip empty ones). ' +
  'Reply with JSON only: {"sections":[{"title":"...","facts":["..."]}]}';
return [{ json: { campaign_id, messages: [{ role: 'system', content: system }, { role: 'user', content: text.slice(0, 60000) }] } }];
`, 1, 0),
  http('Ask Groq to extract facts', {
    method: 'POST', url: 'https://api.groq.com/openai/v1/chat/completions', headers: GROQ,
    body: "={{ JSON.stringify({ model: 'openai/gpt-oss-120b', reasoning_effort: 'low', temperature: 0, response_format: { type: 'json_object' }, messages: $json.messages }) }}",
  }, 2, 0),
  code('Format fact sheet', String.raw`
const { sections = [] } = JSON.parse($input.first().json.choices[0].message.content);
const facts_md = sections.map(s => '## ' + s.title + '\n' + s.facts.map(f => '- ' + f).join('\n')).join('\n\n');
return [{ json: { campaign_id: $('Build extraction prompt').first().json.campaign_id, facts_md, sections } }];
`, 3, 0),
  http('Save to campaign', {
    method: 'PATCH', url: `${SB}/rest/v1/campaigns?id=eq.{{ $json.campaign_id }}`,
    headers: { ...SUPA, Prefer: 'return=minimal' }, body: '={{ JSON.stringify({ facts_md: $json.facts_md }) }}',
  }, 4, 0),
  respond('Return fact sheet', "={{ JSON.stringify({ facts_md: $('Format fact sheet').first().json.facts_md, sections: $('Format fact sheet').first().json.sections }) }}", 5, 0),
], [
  ['Knowledge request', 'Build extraction prompt'],
  ['Build extraction prompt', 'Ask Groq to extract facts'],
  ['Ask Groq to extract facts', 'Format fact sheet'],
  ['Format fact sheet', 'Save to campaign'],
  ['Save to campaign', 'Return fact sheet'],
], { active: true, id: 'cHYHmxqY3LTVWwa5' });

await mkdir(out, { recursive: true });
const files = { 'wf1_knowledge_builder.json': wf1, 'wf2_lead_import.json': wf2, 'wf3_auto_dialer.json': wf3, 'wf4_end_of_call.json': wf4 };
for (const [f, wf] of Object.entries(files)) {
  await writeFile(path.join(out, f), JSON.stringify(wf, null, 2));
  console.log(`✓ n8n/workflows/${f}  (${wf.nodes.length} nodes)`);
}
