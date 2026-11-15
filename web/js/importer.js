// Lead import agent (browser side): any file → rows → mapped columns → clean leads.
// Mapping uses fast keyword rules; the Python API's AI mapper (Groq) is tried first.
import { config, isLive } from './config.js';

const FIELDS = {
  name: ['name', 'full name', 'fullname', 'customer', 'customer name', 'client', 'cname', 'lead', 'lead name', 'contact name', 'naam'],
  phone: ['phone', 'mobile', 'mob', 'mob no', 'mobile no', 'contact', 'contact no', 'number', 'phone number', 'cell', 'whatsapp', 'tel'],
  email: ['email', 'e-mail', 'mail', 'email id'],
  location: ['location', 'city', 'area', 'locality', 'address', 'country', 'place', 'region'],
  budget: ['budget', 'approx budget', 'price range', 'investment', 'range'],
  notes: ['notes', 'remarks', 'comment', 'comments', 'note'],
};

const norm = s => String(s || '').toLowerCase().replace(/[^a-z ]/g, ' ').replace(/\s+/g, ' ').trim();

export function guessMapping(headers) {
  const map = {};
  for (const h of headers) {
    const n = norm(h);
    let best = null, score = 0;
    for (const [field, keys] of Object.entries(FIELDS)) {
      for (const k of keys) {
        const s = n === k ? 3 : n.startsWith(k) || n.endsWith(k) ? 2 : n.includes(k) ? 1 : 0;
        if (s > score) { score = s; best = field; }
      }
    }
    map[h] = score ? best : 'extra';
  }
  return map;
}

export async function aiMapping(headers, sample) {
  if (!isLive.api()) return null;
  try {
    const r = await fetch(`${config.apiBaseUrl}/leads/map`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ headers, sample: sample.slice(0, 5) }),
    });
    return r.ok ? (await r.json()).mapping : null;
  } catch { return null; }
}

export function normalisePhone(raw) {
  let p = String(raw || '').replace(/[^\d+]/g, '');
  if (p.startsWith('00')) p = '+' + p.slice(2);
  if (!p.startsWith('+')) {
    if (p.length === 10) p = '+91' + p;
    else if (p.length === 12 && p.startsWith('91')) p = '+' + p;
    else if (p.length === 11 && p.startsWith('0')) p = '+91' + p.slice(1);
  }
  return /^\+\d{10,15}$/.test(p) ? p : null;
}

const titleCase = s => String(s || '').trim().toLowerCase().replace(/\b\w/g, c => c.toUpperCase());

export function cleanRows(rows, mapping, source) {
  const seen = new Set();
  const out = [], invalid = [], dupes = [];
  for (const row of rows) {
    const lead = { source, extra: {} };
    for (const [col, field] of Object.entries(mapping)) {
      const v = row[col];
      if (v === undefined || v === null || v === '') continue;
      if (field === 'extra') lead.extra[col] = v;
      else lead[field] = lead[field] ? `${lead[field]}, ${v}` : String(v).trim();
    }
    lead.phone = normalisePhone(lead.phone);
    if (lead.name) lead.name = titleCase(lead.name);
    if (!lead.phone) { invalid.push(row); continue; }
    if (seen.has(lead.phone)) { dupes.push(row); continue; }
    seen.add(lead.phone);
    out.push(lead);
  }
  return { leads: out, invalid, dupes };
}

// --- File readers ---------------------------------------------------------
let XLSX = null;
async function loadXlsx() {
  if (XLSX) return XLSX;
  await new Promise((res, rej) => {
    const s = document.createElement('script');
    s.src = 'https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js';
    s.onload = res; s.onerror = () => rej(new Error('Could not load the spreadsheet reader'));
    document.head.appendChild(s);
  });
  XLSX = window.XLSX;
  return XLSX;
}

function parseSql(text) {
  const rows = [];
  const re = /insert\s+into\s+[`"\w.]+\s*\(([^)]+)\)\s*values\s*([\s\S]+?);/gi;
  let m;
  while ((m = re.exec(text))) {
    const cols = m[1].split(',').map(c => c.trim().replace(/[`"']/g, ''));
    const tuples = m[2].match(/\((?:[^()']|'(?:[^']|'')*')*\)/g) || [];
    for (const t of tuples) {
      const vals = [...t.slice(1, -1).matchAll(/'((?:[^']|'')*)'|([^,\s][^,]*)/g)].map(v => (v[1] ?? v[2] ?? '').replace(/''/g, "'").trim());
      const row = {};
      cols.forEach((c, i) => { row[c] = vals[i] === 'NULL' ? '' : vals[i]; });
      rows.push(row);
    }
  }
  return rows;
}

export async function readFile(file) {
  const ext = file.name.split('.').pop().toLowerCase();
  if (ext === 'sql') return parseSql(await file.text());
  if (ext === 'json') {
    const j = JSON.parse(await file.text());
    return Array.isArray(j) ? j : j.leads || j.data || [];
  }
  if (['csv', 'xlsx', 'xls', 'tsv', 'txt', 'ods'].includes(ext)) {
    const X = await loadXlsx();
    const wb = X.read(await file.arrayBuffer(), { type: 'array' });
    return X.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { defval: '', raw: false });
  }
  throw new Error(`Unsupported file type: .${ext}. Use CSV, Excel, JSON or SQL.`);
}
