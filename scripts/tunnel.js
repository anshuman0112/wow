// Opens a free public link to n8n (Cloudflare quick tunnel, no account needed) and points
// everything at it: .env, web/js/config.js and the Vapi assistant's webhook.
//   npm run tunnel      (keep this window open while you make calls)
import { spawn, execSync } from 'node:child_process';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const envPath = path.join(root, '.env');
const cfgPath = path.join(root, 'web/js/config.js');

const exe = ['C:/Program Files (x86)/cloudflared/cloudflared.exe', 'C:/Program Files/cloudflared/cloudflared.exe']
  .find(p => existsSync(p)) || 'cloudflared';

// 1. Make sure n8n is running
try { execSync('docker compose up -d', { cwd: root, stdio: 'ignore' }); } catch { console.warn('! Could not start n8n — is Docker Desktop open?'); }

// 2. Start the tunnel and wait for its public URL
console.log('Starting tunnel to http://127.0.0.1:5678 …');
const cf = spawn(exe, ['tunnel', '--no-autoupdate', '--url', 'http://127.0.0.1:5678'], { stdio: ['ignore', 'pipe', 'pipe'] });
let done = false;
const onData = async buf => {
  const m = !done && String(buf).match(/https:\/\/[a-z0-9-]+\.trycloudflare\.com/);
  if (!m) return;
  done = true;
  await point(m[0]).catch(e => console.error('✗', e.message));
  console.log('\nTunnel is live. Keep this window open while making calls (Ctrl+C to stop).');
};
cf.stdout.on('data', onData);
cf.stderr.on('data', onData);
cf.on('exit', code => { console.log(`Tunnel stopped (${code}).`); process.exit(code ?? 0); });

async function point(url) {
  console.log(`✓ Public n8n URL: ${url}`);

  // .env
  let env = readFileSync(envPath, 'utf8');
  const set = (k, v) => { env = new RegExp(`^${k}=.*$`, 'm').test(env) ? env.replace(new RegExp(`^${k}=.*$`, 'm'), `${k}=${v}`) : env + `\n${k}=${v}\n`; };
  set('N8N_PUBLIC_URL', url);
  set('N8N_VAPI_WEBHOOK_URL', `${url}/webhook/vapi-events`);
  writeFileSync(envPath, env);
  console.log('✓ .env updated');

  // web app
  let cfg = readFileSync(cfgPath, 'utf8');
  cfg = cfg.replace(/n8nBaseUrl: '[^']*'/, `n8nBaseUrl: '${url}/webhook'`);
  writeFileSync(cfgPath, cfg);
  console.log('✓ web/js/config.js updated');

  // Vapi assistant webhook (no other settings touched)
  const vars = Object.fromEntries(env.split(/\r?\n/).map(l => l.match(/^([A-Z0-9_]+)=(.*)$/)).filter(Boolean).map(m => [m[1], m[2]]));
  let state = {};
  try { state = JSON.parse(readFileSync(path.join(root, 'vapi/.state.json'), 'utf8')); } catch {}
  if (vars.VAPI_PRIVATE_KEY && state.assistantId) {
    // Give Cloudflare a few seconds to start routing before Vapi might call it.
    await new Promise(r => setTimeout(r, 4000));
    const res = await fetch(`https://api.vapi.ai/assistant/${state.assistantId}`, {
      method: 'PATCH',
      headers: { Authorization: `Bearer ${vars.VAPI_PRIVATE_KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ server: { url: `${url}/webhook/vapi-events` }, serverMessages: ['end-of-call-report', 'status-update'] }),
    });
    console.log(res.ok ? '✓ Vapi will send call reports to the new URL' : `✗ Vapi update failed (${res.status}): ${await res.text()}`);
  } else {
    console.log('! Vapi not updated (run `npm run sync` first).');
  }

  // Live demo site: redeploy so it uses the new n8n link too
  if (existsSync(path.join(root, 'web/.vercel')) && !process.argv.includes('--no-deploy')) {
    console.log('… Updating the live site on Vercel (about 30 s)');
    try {
      execSync('npx -y vercel@65.9.0 deploy --prod --yes', { cwd: path.join(root, 'web'), stdio: 'ignore' });
      console.log('✓ Live site updated: https://vaani-divyasree.vercel.app');
    } catch { console.log('! Vercel redeploy failed — run: npm run deploy'); }
  }
}
