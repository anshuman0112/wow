// Exports the full system message (plus first message, pronunciation dictionary and voice/model
// settings) to docs/System_Prompt.pdf — the deliverable the assignment asks for.
//   npm run pdf
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { marked } from 'marked';
import { renderPrompt } from './sync_assistant.js';
import { buildAssistant } from '../vapi/assistant.js';
import { pronunciation, pinnedVoices, campaign } from '../web/js/campaign-data.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const esc = s => String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

const prompt = await renderPrompt();
const a = buildAssistant({ systemPrompt: prompt, voiceId: pinnedVoices[0].id });
const date = new Date().toLocaleDateString('en-IN', { day: 'numeric', month: 'long', year: 'numeric' });

const html = `<!doctype html><html><head><meta charset="utf-8"><title>System Prompt · Aanya</title>
<style>
  @page { size: A4; margin: 18mm 16mm; }
  body { font: 10.5pt/1.55 "Segoe UI", Arial, sans-serif; color: #1b1f1d; }
  h1 { font-size: 22pt; margin: 0 0 4px; color: #1f5f4a; }
  h2 { font-size: 13pt; color: #1f5f4a; border-bottom: 1px solid #d9e6df; padding-bottom: 4px; margin: 22px 0 8px; break-after: avoid; }
  h3 { font-size: 11pt; margin: 14px 0 4px; }
  .sub { color: #5d635f; margin-bottom: 14px; }
  .meta { display: grid; grid-template-columns: 150px 1fr; gap: 4px 12px; background: #f4f8f6; border: 1px solid #d9e6df; border-radius: 8px; padding: 12px 14px; }
  .meta b { color: #5d635f; font-weight: 600; }
  table { border-collapse: collapse; width: 100%; margin: 6px 0; }
  th, td { border: 1px solid #dfe3e0; padding: 5px 8px; text-align: left; vertical-align: top; }
  th { background: #f4f8f6; }
  .first { background: #f4f8f6; border-left: 3px solid #1f5f4a; padding: 10px 12px; margin: 6px 0; }
  .prompt { border: 1px solid #dfe3e0; border-radius: 8px; padding: 6px 16px 10px; }
  .prompt h1 { font-size: 11.5pt; color: #1f5f4a; margin: 16px 0 4px; letter-spacing: .02em; }
  .prompt h2 { font-size: 10.5pt; border: 0; margin: 10px 0 2px; color: #1b1f1d; }
  .prompt ul, .prompt ol { margin: 4px 0 6px; padding-left: 20px; }
  .prompt p { margin: 4px 0; }
  code { font-family: Consolas, monospace; font-size: 9.5pt; background: #f1f3f2; padding: 0 3px; border-radius: 3px; }
  .note { color: #5d635f; font-size: 9.5pt; }
  .page-break { break-before: page; }
</style></head><body>
<h1>System Prompt — Aanya</h1>
<div class="sub">AI Voice Agent for Divyasree "Whispers of the Wind" · Vaani · ${esc(date)}</div>

<div class="meta">
  <b>Agent</b><span>${esc(campaign.persona.name)}, a ${esc(campaign.persona.role)} (outbound lead qualification)</span>
  <b>Goal</b><span>${esc(campaign.goal)}, in a 2–3 minute call</span>
  <b>Platform</b><span>Vapi</span>
  <b>LLM</b><span>${esc(a.model.provider)} · ${esc(a.model.model)} · temperature ${a.model.temperature} · max ${a.model.maxTokens} tokens/turn</span>
  <b>Speech to text</b><span>Deepgram ${esc(a.transcriber.model)} · language "${esc(a.transcriber.language)}" (English + Hindi code-switching)</span>
  <b>Voice</b><span>ElevenLabs ${esc(a.voice.model)} · ${esc(pinnedVoices.map((v, i) => i === 0 ? `${v.name} (default)` : v.name).join(', '))} · stability ${a.voice.stability}, similarity ${a.voice.similarityBoost}</span>
  <b>Turn-taking</b><span>Waits ${a.startSpeakingPlan.waitSeconds}s with smart endpointing; stops speaking as soon as the lead says ${a.stopSpeakingPlan.numWords} word (barge-in)</span>
  <b>Call limits</b><span>Silence timeout ${a.silenceTimeoutSeconds}s · max ${a.maxDurationSeconds / 60} min · voicemail message set · endCall tool</span>
</div>

<h2>1. First message (spoken when the call connects)</h2>
<div class="first">${esc(a.firstMessage)}</div>
<p class="note"><code>{{ name }}</code> is filled in per call with the lead's first name, or "there" if unknown.</p>

<h2>2. Pronunciation dictionary</h2>
<table><tr><th>Word</th><th>Pronounce as</th><th>Source</th></tr>
${pronunciation.map(p => `<tr><td>${esc(p.term)}</td><td>${esc(p.say)}</td><td>${p.from === 'PDF' ? 'Assignment brief' : 'Added'}</td></tr>`).join('')}
</table>
<p class="note">Enforced twice: in the system prompt below, and as text replacements applied just before speech:
${a.voice.chunkPlan.formatPlan.replacements.map(r => `<code>${esc(r.key)} → ${esc(r.value)}</code>`).join(' ')}</p>

<h2>3. Full system message</h2>
<p class="note">Exactly as configured in Vapi. Static rules and facts come first and per-call variables last, so the prompt prefix stays identical across turns and can be cached.</p>
<div class="prompt">${marked.parse(prompt)}</div>
</body></html>`;

await mkdir(path.join(root, 'docs'), { recursive: true });
const htmlPath = path.join(root, 'docs', 'System_Prompt.html');
const pdfPath = path.join(root, 'docs', 'System_Prompt.pdf');
await writeFile(htmlPath, html);

const browsers = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome', '/usr/bin/chromium',
];
const browser = browsers.find(b => existsSync(b));
if (!browser) { console.log(`✓ HTML written to docs/System_Prompt.html — open it and Print → Save as PDF.`); process.exit(0); }

execFileSync(browser, ['--headless=new', '--disable-gpu', '--no-pdf-header-footer', `--print-to-pdf=${pdfPath}`, pathToFileURL(htmlPath).href], { stdio: 'ignore', timeout: 60000 });
console.log(`✓ docs/System_Prompt.pdf written (${Math.round((await readFile(pdfPath)).length / 1024)} KB)`);
