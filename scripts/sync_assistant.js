// Builds the system prompt from the campaign data and creates/updates the Vapi assistant.
//
//   node scripts/sync_assistant.js --dry-run   → only writes docs/system_prompt.md (no keys needed)
//   node scripts/sync_assistant.js             → also creates/updates the assistant in Vapi
//
// Reads keys from .env (see .env.example). Saves created IDs in vapi/.state.json.
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { facts, pronunciation, pinnedVoices as voices } from '../web/js/campaign-data.js';
import { buildAssistant, leadAnalysisOutput, parseLlm } from '../vapi/assistant.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dryRun = process.argv.includes('--dry-run');
const VAPI = 'https://api.vapi.ai';

// --- 1. Load .env without extra dependencies ------------------------------
async function loadEnv() {
  const file = path.join(root, '.env');
  if (!existsSync(file)) return {};
  const env = {};
  for (const line of (await readFile(file, 'utf8')).split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (m) env[m[1]] = m[2].replace(/^["']|["']$/g, '');
  }
  return env;
}

// --- 2. Render the system prompt -------------------------------------------
export async function renderPrompt() {
  const template = await readFile(path.join(root, 'prompts/system_prompt.template.md'), 'utf8');
  const factsText = 'Facts marked [web] come from public listings: for times and distances say "about" or "approximately".\n\n' +
    facts.map(g => `## ${g.group}\n` + g.items.map(f => `- ${f.k}: ${f.v}${f.src === 'web' ? ' [web]' : ''}`).join('\n')).join('\n\n');
  const pron = pronunciation.map(p => `- ${p.term} → "${p.say}"`).join('\n');
  return template.replace('[[FACTS]]', factsText).replace('[[PRONUNCIATION]]', pron);
}

// --- 3. Vapi API helper ----------------------------------------------------
async function vapi(method, url, key, body) {
  const res = await fetch(VAPI + url, {
    method,
    headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`Vapi ${method} ${url} failed (${res.status}): ${text}`);
  return text ? JSON.parse(text) : {};
}

async function main() {
  const systemPrompt = await renderPrompt();
  await mkdir(path.join(root, 'docs'), { recursive: true });
  await writeFile(path.join(root, 'docs/system_prompt.md'), systemPrompt);
  const approxTokens = Math.round(systemPrompt.length / 4);
  console.log(`✓ System prompt written to docs/system_prompt.md (~${approxTokens} tokens)`);
  if (dryRun) return;

  const env = await loadEnv();
  for (const k of ['VAPI_PRIVATE_KEY']) {
    if (!env[k]) throw new Error(`Missing ${k} in .env — copy .env.example to .env and fill it in.`);
  }
  const stateFile = path.join(root, 'vapi/.state.json');
  const state = existsSync(stateFile) ? JSON.parse(await readFile(stateFile, 'utf8')) : {};

  // Structured output (lead analysis)
  if (state.structuredOutputId) {
    await vapi('PATCH', `/structured-output/${state.structuredOutputId}`, env.VAPI_PRIVATE_KEY, leadAnalysisOutput);
    console.log('✓ Updated structured output', state.structuredOutputId);
  } else {
    const so = await vapi('POST', '/structured-output', env.VAPI_PRIVATE_KEY, leadAnalysisOutput);
    state.structuredOutputId = so.id;
    console.log('✓ Created structured output', so.id);
  }

  // Assistant
  const assistant = buildAssistant({
    systemPrompt,
    voiceId: env.ELEVENLABS_VOICE_ID || voices[0].id,
    serverUrl: env.N8N_VAPI_WEBHOOK_URL,
    structuredOutputId: state.structuredOutputId,
    llm: parseLlm(env.VAPI_LLM || undefined),
  });
  console.log(`  brain: ${assistant.model.provider}/${assistant.model.model} · voice: ${assistant.voice.voiceId}`);
  if (state.assistantId) {
    await vapi('PATCH', `/assistant/${state.assistantId}`, env.VAPI_PRIVATE_KEY, assistant);
    console.log('✓ Updated assistant', state.assistantId);
  } else {
    const a = await vapi('POST', '/assistant', env.VAPI_PRIVATE_KEY, assistant);
    state.assistantId = a.id;
    console.log('✓ Created assistant', a.id);
  }
  await writeFile(stateFile, JSON.stringify(state, null, 2));

  // Write the public key + assistant ID into the web app so "Talk to Divya" goes live.
  const cfgPath = path.join(root, 'web/js/config.js');
  let cfg = await readFile(cfgPath, 'utf8');
  cfg = cfg.replace(/vapiAssistantId: '[^']*'/, `vapiAssistantId: '${state.assistantId}'`);
  if (env.VAPI_PUBLIC_KEY) cfg = cfg.replace(/vapiPublicKey: '[^']*'/, `vapiPublicKey: '${env.VAPI_PUBLIC_KEY}'`);
  await writeFile(cfgPath, cfg);
  console.log(`✓ web/js/config.js updated${env.VAPI_PUBLIC_KEY ? '' : ' (add VAPI_PUBLIC_KEY to .env and re-run to enable browser calls)'}`);
  if (!env.N8N_VAPI_WEBHOOK_URL) console.log('\n! N8N_VAPI_WEBHOOK_URL is empty — calls work, but nothing is saved to Supabase until n8n is connected. Re-run after setting it.');
}

// Run only when executed directly (not when another script imports renderPrompt).
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(e => { console.error('✗', e.message); process.exit(1); });
}
