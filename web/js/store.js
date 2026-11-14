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

export async function getLeads() {
  if (mode() === 'demo') return mem.leads;
  const { data, error } = await (await sb()).from('leads_public').select('*').order('created_at', { ascending: false });
  if (error) throw error;
  return data;
}

export async function getCalls() {
  if (mode() === 'demo') return mem.calls;
  const { data, error } = await (await sb()).from('calls_public').select('*').order('started_at', { ascending: false });
  if (error) throw error;
  return data.map(normaliseCall);
}

export async function getCall(id) {
  const calls = await getCalls();
  return calls.find(c => c.id === id || c.vapi_call_id === id);
}

export async function addLeads(rows) {
  if (mode() === 'demo') {
    const existing = new Set(mem.leads.map(l => l.phone.replace(/\D/g, '')));
    let n = 0;
    for (const r of rows) {
      if (existing.has(r.phone.replace(/\D/g, ''))) continue;
      mem.leads.unshift({ id: 'L-' + (2000 + mem.leads.length), status: 'new', interest: null, attempts: 0, created_at: new Date().toISOString(), ...r });
      n++;
    }
    return n;
  }
  // The browser never writes to the database directly: n8n (WF2) saves leads with the service key.
  if (!isLive.n8n()) throw new Error('Set n8nBaseUrl in config.js to import leads into Supabase.');
  const res = await fetch(`${config.n8nBaseUrl}/lead-import`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'ngrok-skip-browser-warning': 'true' }, body: JSON.stringify({ leads: rows }),
  });
  if (!res.ok) throw new Error(`Lead import failed (${res.status})`);
  return (await res.json()).imported ?? rows.length;
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
