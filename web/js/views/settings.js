import { config } from '../config.js';
import { esc, icon, toast } from '../ui.js';

// Settings: what a sales manager can change without code. Saved values reach every call within ~30 s,
// and question changes are pushed to the browser assistant too, so phone and browser calls ask the same thing.
const STEPS = [
  ['intent', 'Intent (checkpoint 1)'], ['geography', 'Geography (checkpoint 2)'], ['budget', 'Budget (checkpoint 3)'],
  ['timeline', 'Timeline (checkpoint 4)'], ['decision', 'Who decides? (soft extra question)'],
  ['pitch', 'The pitch + call-to-action'], ['callback', 'Asking for the expert call time'],
];
const TONES = ['positive', 'calm', 'hesitant', 'irritated', 'angry'];
const PIN_KEY = 'wow-admin-pin';

export default async function settingsView(el) {
  let res;
  try { res = await (await fetch(`${config.apiBaseUrl}/settings`)).json(); }
  catch { el.innerHTML = '<p class="muted">Could not reach the API.</p>'; return; }
  let s = structuredClone(res.settings);

  const num = (path, val, attrs = '') => `<input class="input mono" type="number" data-path="${path}" value="${esc(val)}" style="width:76px" ${attrs}>`;
  const draw = () => {
    const sc = s.scoring;
    el.innerHTML = `
      <div class="page-head">
        <div><h1>Settings</h1><p class="muted">Change how Divya qualifies and follows up. Saved changes reach every call within about 30 seconds.</p></div>
        <div class="row" style="gap:8px"><button class="btn btn-ghost" id="defaults">Reset to defaults</button>
          <button class="btn btn-primary" id="save">${icon('check')}Save settings</button></div>
      </div>

      <section class="card card-pad" style="margin-bottom:16px">
        <h2>Questions Divya asks</h2>
        <p class="muted small" style="margin:4px 0 12px">Used on phone and browser calls, in this order. Divya may phrase them naturally. The Hindi version is used when the lead speaks Hindi/Hinglish.</p>
        <div class="stack" style="gap:12px">
          ${STEPS.map(([k, label]) => `
            <div><div class="small" style="font-weight:600;margin-bottom:4px">${label}</div>
              <div class="grid g-2" style="gap:8px">
                <textarea class="input" rows="2" data-path="questions.${k}.en" aria-label="${label} in English">${esc(s.questions[k]?.en || '')}</textarea>
                <textarea class="input" rows="2" data-path="questions.${k}.hi" aria-label="${label} in Hindi">${esc(s.questions[k]?.hi || '')}</textarea>
              </div></div>`).join('')}
        </div>
      </section>

      <section class="card card-pad" style="margin-bottom:16px">
        <h2>Lead score and pass mark</h2>
        <p class="muted small" style="margin:4px 0 12px">Each call is scored 0–100 from what the lead actually said. Full = clear yes, Partial = stretch / hesitant / unsure.</p>
        <div class="table-wrap"><table>
          <thead><tr><th>Answer</th><th>Full points</th><th>Partial points</th><th>Must-have for Hot</th></tr></thead>
          <tbody>${Object.entries(sc.points).map(([k, p]) => `
            <tr><td>${esc(p.label)}</td><td>${num(`scoring.points.${k}.max`, p.max, 'min="0" max="100"')}</td>
              <td>${'partial' in p ? num(`scoring.points.${k}.partial`, p.partial, 'min="0" max="100"') : '<span class="faint small">—</span>'}</td>
              <td><input type="checkbox" data-req="${k}" ${(sc.hot_requires || []).includes(k) ? 'checked' : ''} aria-label="${esc(p.label)} must be a yes for Hot"></td></tr>`).join('')}
          </tbody></table></div>
        <div class="row" style="margin-top:12px;gap:16px">
          <span class="small"><b>Total full points:</b> <span id="total" class="mono"></span> / 100</span>
          <label class="small row" style="gap:6px">🔥 Hot from ${num('scoring.tiers.hot', sc.tiers.hot, 'min="1" max="100"')}</label>
          <label class="small row" style="gap:6px">Warm from ${num('scoring.tiers.warm', sc.tiers.warm, 'min="1" max="99"')}</label>
          <span class="small muted">below Warm = Cold</span>
        </div>
        <div class="row small" style="margin-top:10px;gap:12px"><b>Tone at the end of the call:</b>
          ${TONES.map(t => `<label class="row" style="gap:4px">${t} ${num(`scoring.tone.${t}`, sc.tone?.[t] ?? 0, 'min="-50" max="20"')}</label>`).join('')}
        </div>
      </section>

      <div class="grid g-2" style="margin-bottom:16px">
        <section class="card card-pad">
          <h2>Calling hours (India time)</h2>
          <p class="muted small" style="margin:4px 0 12px">Automatic calls (call-backs, re-attempts, new leads) only go out in this window. India's telecom rules allow sales calls 9 am – 9 pm.</p>
          <div class="row" style="gap:12px"><label class="small row" style="gap:6px">From ${num('calling_hours.start', s.calling_hours.start, 'min="0" max="23"')}:00</label>
            <label class="small row" style="gap:6px">To ${num('calling_hours.end', s.calling_hours.end, 'min="1" max="24"')}:00</label></div>
        </section>
        <section class="card card-pad">
          <h2>Re-attempts when nobody picks up</h2>
          <p class="muted small" style="margin:4px 0 12px">One step per retry, separated by commas: <span class="mono">10m</span>, <span class="mono">2h</span>, or <span class="mono">next 11:00</span> (next day at that time). After the last one the lead is marked unreachable.</p>
          <input class="input mono" id="retry" value="${esc((s.retry || []).join(', '))}" style="width:100%">
          <p class="small" style="margin-top:6px" id="retry-help"></p>
        </section>
      </div>

      <div class="grid g-2">
        <section class="card card-pad">
          <h2>New leads</h2>
          <label class="row small" style="gap:8px;margin-top:8px"><input type="checkbox" data-bool="speed_to_lead.enabled" ${s.speed_to_lead.enabled ? 'checked' : ''}>
            Call every new lead automatically within seconds of arriving (website form, Facebook, Instagram, Google Ads)</label>
          <label class="row small" style="gap:8px;margin-top:6px"><input type="checkbox" data-bool="speed_to_lead.manual" ${s.speed_to_lead.manual ? 'checked' : ''}>
            Also call leads added by hand on the Leads page, right away</label>
          <label class="row small" style="gap:8px;margin-top:6px"><input type="checkbox" data-bool="speed_to_lead.imports" ${s.speed_to_lead.imports ? 'checked' : ''}>
            Also call uploaded leads (Excel, CSV, JSON, SQL), a few at a time</label>
          <label class="row small" style="gap:6px;margin-top:6px">Uploaded leads called per scheduler run (about every 5 minutes)
            ${num('speed_to_lead.per_run', s.speed_to_lead.per_run ?? 3, 'min="1" max="10"')}</label>
          <p class="muted small" style="margin-top:6px">Outside calling hours they are called at the start of the next window. On the free Twilio trial only verified numbers can be called.</p>
        </section>
        <section class="card card-pad">
          <h2>Sales team hand-off</h2>
          <label class="small" style="display:block;margin-top:8px">Sales team WhatsApp number (for "Share on WhatsApp")
            <input class="input mono" data-path="handoff.sales_whatsapp" placeholder="e.g. +91 98765 43210" value="${esc(s.handoff.sales_whatsapp)}" style="width:100%;margin-top:4px"></label>
          <label class="small" style="display:block;margin-top:10px">CRM webhook (optional): every finished call's profile is sent here
            <input class="input mono" data-path="handoff.crm_webhook" placeholder="https://your-crm.example.com/webhook" value="${esc(s.handoff.crm_webhook)}" style="width:100%;margin-top:4px"></label>
        </section>
      </div>`;
    bind();
    refresh();
  };

  const setPath = (path, value) => {
    const keys = path.split('.'); let o = s;
    keys.slice(0, -1).forEach(k => { o[k] = o[k] ?? {}; o = o[k]; });
    o[keys.at(-1)] = value;
  };
  const refresh = () => {
    const total = Object.values(s.scoring.points).reduce((a, p) => a + Number(p.max || 0), 0);
    const t = el.querySelector('#total');
    t.textContent = total; t.style.color = total === 100 ? '' : 'var(--bad, #b3261e)';
    const steps = (s.retry || []);
    el.querySelector('#retry-help').innerHTML = steps.length
      ? `Up to <b>${steps.length + 1}</b> calls in total: first call, then ${steps.map(x => `<span class="mono">${esc(x)}</span>`).join(' → ')}, then stop.`
      : 'No re-attempts: one call only.';
  };
  const bind = () => {
    el.querySelectorAll('[data-path]').forEach(i => i.oninput = () => {
      setPath(i.dataset.path, i.type === 'number' ? Number(i.value) : i.value); refresh();
    });
    el.querySelectorAll('[data-bool]').forEach(i => i.onchange = () => setPath(i.dataset.bool, i.checked));
    el.querySelectorAll('[data-req]').forEach(i => i.onchange = () => {
      const set = new Set(s.scoring.hot_requires || []);
      i.checked ? set.add(i.dataset.req) : set.delete(i.dataset.req);
      s.scoring.hot_requires = [...set];
    });
    el.querySelector('#retry').oninput = e => { s.retry = e.target.value.split(',').map(x => x.trim()).filter(Boolean); refresh(); };
    el.querySelector('#defaults').onclick = () => { s = structuredClone(res.defaults); draw(); toast('Defaults loaded: press Save to keep them'); };
    el.querySelector('#save').onclick = save;
  };

  const save = async () => {
    let pin = '';
    try { pin = sessionStorage.getItem(PIN_KEY) || ''; } catch {}
    if (res.pin_required && !pin) pin = window.prompt('Admin PIN to save settings:') || '';
    if (res.pin_required && !pin) return;
    const btn = el.querySelector('#save'); btn.disabled = true;
    try {
      const r = await fetch(`${config.apiBaseUrl}/settings`, { method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-Admin-Pin': pin }, body: JSON.stringify({ settings: s }) });
      const j = await r.json().catch(() => ({}));
      if (r.status === 401) { try { sessionStorage.removeItem(PIN_KEY); } catch {} throw new Error(j.detail || 'Wrong PIN'); }
      if (!r.ok) throw new Error(j.detail || `Could not save (${r.status})`);
      try { sessionStorage.setItem(PIN_KEY, pin); } catch {}
      res.settings = j.settings; s = structuredClone(j.settings); draw();
      toast(`Saved. Live on every call within ~30 s${j.browser_assistant_synced ? ', browser assistant updated' : ''}.`);
    } catch (e) { toast(e.message); }
    btn.disabled = false;
  };

  draw();
}
