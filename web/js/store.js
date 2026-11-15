// Data layer. Demo mode = in-memory sample data. Live mode = Supabase.
import { config, isLive } from './config.js';
import { sampleLeads, sampleCalls } from './mock-data.js';

let supabase = null;
const mem = {
  leads: structuredClone(sampleLeads),
  calls: sampleCalls.map(c => ({ ...c, messages: c.messages.map(([r, t]) => ({ role: r === 'a' ? 'assistant' : 'user', text: t })) })),
};

async function sb() {
  if (!supabase) {
    const { createClient } = await import('https://esm.sh/@supabase/supabase-js@2.118.0');
    supabase = createClient(config.supabaseUrl, config.supabaseAnonKey);
  }
  return supabase;
}

export const mode = () => (isLive.supabase() ? 'live' : 'demo');

// One page shows leads and calls in several places: share one request instead of fetching the same list
// 3-5 times (each a round trip to the server). Kept for a few seconds; any change clears it.
const shared = new Map();
const SHARE_MS = 8000;
function once(key, load) {
  const hit = shared.get(key);
  if (hit && Date.now() - hit.at < SHARE_MS) return hit.p;
  const p = load().catch(e => { shared.delete(key); throw e; });
  shared.set(key, { p, at: Date.now() });
  return p;
}
export const refreshData = () => shared.clear();

export async function getLeads() {
  if (mode() === 'demo') return mem.leads;
  return once('leads', async () => {
    const r = await fetch(`${config.apiBaseUrl}/data/leads`);   // signed-in API (the database is private)
    if (!r.ok) throw new Error(`Could not load leads (${r.status})`);
    return await r.json();
  });
}

export async function getCalls() {
  if (mode() === 'demo') return mem.calls;
  return once('calls', async () => {
    const r = await fetch(`${config.apiBaseUrl}/data/calls`);   // signed-in API (the database is private)
    if (!r.ok) throw new Error(`Could not load calls (${r.status})`);
    return (await r.json()).map(normaliseCall);
  });
}

export async function getCall(id) {
  const calls = await getCalls();
  return calls.find(c => c.id === id || c.vapi_call_id === id);
}

export async function addLeads(rows) {
  refreshData();
  if (mode() === 'demo') {
    const existing = new Set(mem.leads.map(l => l.phone.replace(/\D/g, '')));
    let n = 0;
    for (const r of rows) {
      if (existing.has(r.phone.replace(/\D/g, ''))) continue;
      mem.leads.unshift({ id: 'L-' + (2000 + mem.leads.length), status: 'new', interest: null, attempts: 0, created_at: new Date().toISOString(), ...r });
      n++;
    }
    return { imported: n, new: [], re_engaged: [], already_contacted: [], already_listed: [], do_not_call: [] };
  }
  // The browser never writes to the database directly: the Python API saves leads with the service key.
  const res = await fetch(`${config.apiBaseUrl}/leads/import`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ leads: rows }),
  });
  if (!res.ok) throw new Error(`Lead import failed (${res.status})`);
  // { imported, new, re_engaged, already_contacted, already_listed, do_not_call }: every duplicate, by name
  return await res.json();
}

// Ask the Python API to ring one lead's real phone (Twilio bridge or Vapi number).
export async function callNow(leadId) {
  refreshData();
  if (mode() === 'demo') throw new Error('Demo mode: connect Supabase to make real calls.');
  const res = await fetch(`${config.apiBaseUrl}/calls/now`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lead_id: leadId }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Could not start the call (${res.status})`);
}

function normaliseCall(c) {
  return {
    ...c,
    id: c.id,
    checkpoints: { intent: c.intent, geography: c.geography_fit, budget: c.budget_fit, timeline: c.timeline_fit },
    messages: (c.messages || []).filter(m => m.role === 'assistant' || m.role === 'bot' || m.role === 'user')
      .map(m => ({ role: m.role === 'user' ? 'user' : 'assistant', text: m.message || m.text || '' })),
  };
}
