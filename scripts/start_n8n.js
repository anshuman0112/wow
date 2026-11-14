// Starts n8n locally with the keys from .env available to workflows as $env.X
//   npm run n8n            → start n8n on http://localhost:5678
//   npm run n8n:import     → import the 4 workflows from n8n/workflows
import { readFileSync, existsSync } from 'node:fs';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const N8N = 'n8n@2.46.3';

const env = { ...process.env };
const envFile = path.join(root, '.env');
if (existsSync(envFile)) {
  for (const line of readFileSync(envFile, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (m && m[2]) env[m[1]] = m[2].replace(/^["']|["']$/g, '');
  }
} else {
  console.warn('! No .env found — copy .env.example to .env and fill in your keys.');
}

Object.assign(env, {
  N8N_BLOCK_ENV_ACCESS_IN_NODE: 'false',   // lets workflows read $env.SUPABASE_URL etc.
  GENERIC_TIMEZONE: 'Asia/Kolkata',
  N8N_PORT: env.N8N_PORT || '5678',
  N8N_DIAGNOSTICS_ENABLED: 'false',
  N8N_RUNNERS_ENABLED: 'true',
});
if (env.N8N_PUBLIC_URL) env.WEBHOOK_URL = env.N8N_PUBLIC_URL;   // your ngrok URL, so n8n shows correct webhook links

const args = process.argv.includes('--import')
  ? ['import:workflow', '--separate', `--input=${path.join(root, 'n8n', 'workflows')}`]
  : ['start'];

console.log(`> npx ${N8N} ${args.join(' ')}`);
const child = spawn('npx', ['-y', N8N, ...args], { env, stdio: 'inherit', shell: process.platform === 'win32' });
child.on('exit', code => process.exit(code ?? 0));
