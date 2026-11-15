// Runs supabase/schema.sql against your Supabase database.
//   npm run db:schema
// Needs SUPABASE_URL and SUPABASE_DB_PASSWORD in .env. Tries the direct host first,
// then the connection pooler in common regions (direct hosts are IPv6-only on new projects).
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import pg from 'pg';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const env = {};
if (existsSync(path.join(root, '.env'))) {
  for (const line of readFileSync(path.join(root, '.env'), 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (m && m[2]) env[m[1]] = m[2].replace(/^["']|["']$/g, '');
  }
}
const ref = (env.SUPABASE_URL || '').match(/https:\/\/([a-z0-9]+)\.supabase\.co/)?.[1];
const password = env.SUPABASE_DB_PASSWORD;
if (!ref) { console.error('✗ SUPABASE_URL missing in .env'); process.exit(1); }
if (!password) { console.error('✗ Add SUPABASE_DB_PASSWORD=... to .env (Supabase → Project Settings → Database)'); process.exit(1); }

const regions = ['ap-south-1', 'ap-southeast-1', 'us-east-1', 'us-east-2', 'us-west-1', 'eu-central-1', 'eu-west-1', 'eu-west-2', 'ap-northeast-1', 'ap-southeast-2', 'ca-central-1', 'sa-east-1'];
const targets = [
  { host: `db.${ref}.supabase.co`, user: 'postgres', label: 'direct' },
  ...regions.flatMap(r => ['aws-0', 'aws-1'].map(p => ({ host: `${p}-${r}.pooler.supabase.com`, user: `postgres.${ref}`, label: `pooler ${p} ${r}` }))),
];

const sql = readFileSync(path.join(root, 'supabase', 'schema.sql'), 'utf8');

for (const t of targets) {
  const client = new pg.Client({ host: t.host, port: 5432, user: t.user, password, database: 'postgres', ssl: { rejectUnauthorized: false }, connectionTimeoutMillis: 6000 });
  try {
    await client.connect();
  } catch (e) {
    const msg = String(e.message || e);
    if (/password authentication failed/i.test(msg)) { console.error('✗ Wrong database password. Reset it in Supabase → Project Settings → Database.'); process.exit(1); }
    continue; // unreachable host / wrong region → try next
  }
  try {
    console.log(`✓ Connected (${t.label})`);
    await client.query(sql);
    await client.query("notify pgrst, 'reload schema'");
    const { rows } = await client.query(`select table_name from information_schema.tables where table_schema='public' and table_name in ('campaigns','leads','calls','leads_public','calls_public') order by 1`);
    console.log('✓ Schema applied. Objects:', rows.map(r => r.table_name).join(', '));
  } catch (e) {
    console.error('✗ SQL error:', e.message);
    process.exitCode = 1;
  } finally {
    await client.end();
  }
  process.exit();
}
console.error('✗ Could not reach the database on any host. Check the password, or copy the "Session pooler" connection string from Supabase → Connect.');
process.exit(1);
