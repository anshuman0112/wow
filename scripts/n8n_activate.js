// Imports the latest workflow files into n8n (Docker) and switches them on.
//   npm run n8n:activate
// WF3 (auto-dialer) is switched on only when VAPI_PHONE_NUMBER_ID is set (i.e. Twilio is connected).
import { execSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const env = Object.fromEntries(readFileSync(path.join(root, '.env'), 'utf8').split(/\r?\n/)
  .map(l => l.match(/^([A-Z0-9_]+)=(.*)$/)).filter(Boolean).map(m => [m[1], m[2].trim()]));
const run = cmd => execSync(cmd, { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, MSYS_NO_PATHCONV: '1' } }).toString();

const ids = {
  'WF1 knowledge builder': 'cHYHmxqY3LTVWwa5',
  'WF2 lead import': 'MYXhLGo8hP9VnaPJ',
  'WF4 end-of-call save': 'iCvnbx7Iy6Ix63Va',
  ...(env.VAPI_PHONE_NUMBER_ID || (env.TWILIO_ACCOUNT_SID && env.TWILIO_AUTH_TOKEN) ? { 'WF3 auto-dialer + call now': '8VpOqJuNDWQenrOf' } : {}),
};

run('docker compose up -d');
run('node n8n/build_workflows.js');
run('docker compose exec -T n8n n8n import:workflow --separate --input=/workflows');
for (const [name, id] of Object.entries(ids)) {
  run(`docker compose exec -T n8n n8n publish:workflow --id=${id}`);
  console.log(`✓ ${name} on`);
}
if (!env.VAPI_PHONE_NUMBER_ID) console.log('· WF3 auto-dialer stays off until Twilio is connected (npm run twilio)');
run('docker compose restart n8n');
const t0 = Date.now();
while (Date.now() - t0 < 120000) {
  try { if (run('docker compose logs --since 2m n8n').includes('Editor is now accessible')) break; } catch {}
  execSync(process.platform === 'win32' ? 'ping -n 3 127.0.0.1 >NUL' : 'sleep 2', { shell: true });
}
console.log('✓ n8n restarted and ready at http://localhost:5678');
