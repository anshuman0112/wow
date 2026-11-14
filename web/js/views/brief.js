// Assignment checklist — every requirement from the Revspot PDF and where it is handled.
import { esc, icon } from '../ui.js';

const S = { done: ['Done', 'b-ok'], build: ['Designed · being built', 'b-gold'], todo: ['To do', ''] };

const sections = [
  { title: '1. Conversation architecture', items: [
    ['Introduction as a Divyasree consultant, mentions project and location', 'Campaign → Conversation flow, step "Introduction"', 'done'],
    ['Always asks permission to speak', 'Greeting ends with "Is this a good time for two minutes?"', 'done'],
    ['Checkpoint: intent (self-use vs investment)', 'Flow step 1', 'done'],
    ['Checkpoint: geography (Nandi Hills / Devanahalli corridor)', 'Flow step 2', 'done'],
    ['Checkpoint: budget (₹92.4 lakh+ fitment)', 'Flow step 3', 'done'],
    ['Checkpoint: timeline (phased delivery, Dec 2029)', 'Flow step 4', 'done'],
    ['The pitch: "Private Valley" lifestyle — clubhouse, nature, community', 'Flow step "The pitch"', 'done'],
    ['CTA: follow-up call with a Property Expert', 'Flow step "Call to action"; callback time saved per lead', 'done'],
  ]},
  { title: '2. Technical requirements', items: [
    ['Affirmations ("Understood", "Perfect")', 'System prompt style rules', 'build'],
    ['No re-asking if the user gave info early', 'System prompt checkpoint tracker; full history sent every turn', 'build'],
    ['Pronunciation guide: Divyasree, Nandi, Lakh, Crore', 'Campaign → Pronunciation guide (in system prompt)', 'done'],
    ['Tone: premium, conversational, non-intrusive', 'Persona + max 2-sentence replies', 'done'],
    ['Holds a 2–3 minute conversation', 'Flow sized for ~2.5 minutes', 'build'],
  ]},
  { title: '3. Deliverables', items: [
    ['Demo link — shareable working bot', 'Talk to Aanya page, deployed on Vercel', 'build'],
    ['Or recorded audio — at least 5 conversation flows', '6 scenarios planned (see Calls page samples)', 'todo'],
    ['System Prompt (PDF) with pronunciation dictionary', 'Written: docs/system_prompt.md · PDF export pending', 'build'],
  ]},
  { title: 'Bonus', items: [
    ['Edge cases: irritated user, budget fit but not location, etc.', 'Campaign → Edge cases (12 handled) + live mood detection', 'done'],
    ['Multilingual: English + Hindi', 'Deepgram multi + Llama 3.3 70B + ElevenLabs multilingual', 'build'],
    ['Additional project details if asked (searched online)', 'Campaign → Fact sheet, items tagged "Web"', 'done'],
  ]},
  { title: 'Extras beyond the brief', items: [
    ['Every call, recording, transcript and summary stored', 'Supabase (calls table + recordings bucket) via n8n', 'build'],
    ['Automatic hot / warm / cold scoring and mood tracking', 'Vapi analysis → Calls page', 'build'],
    ['Upload any lead file (CSV, Excel, JSON, SQL)', 'Leads → Import (auto column detection)', 'done'],
    ['Automatic outbound dialing', 'n8n auto-dialer + Twilio', 'build'],
    ['Reusable for other businesses', 'Campaign-based design', 'build'],
  ]},
];

export default async function brief(el) {
  const all = sections.flatMap(s => s.items);
  const done = all.filter(i => i[2] === 'done').length;
  el.innerHTML = `
    <div class="page-head">
      <div><h1>Assignment checklist</h1><p class="muted">Each requirement in the Revspot brief and where it lives in this build</p></div>
      <span class="badge b-brand">${done} / ${all.length} done</span>
    </div>
    <div class="stack">
      ${sections.map(s => `
        <section class="card">
          <div class="card-head"><h2>${esc(s.title)}</h2></div>
          ${s.items.map(([req, where, st]) => `
            <div class="check">
              <div class="check-ico ${st === 'done' ? '' : 'pending'}">${st === 'done' ? icon('check') : ''}</div>
              <div style="flex:1;min-width:0">
                <div style="font-weight:550">${esc(req)}</div>
                <div class="muted small">${esc(where)}</div>
              </div>
              <span class="badge ${S[st][1]}">${S[st][0]}</span>
            </div>`).join('')}
        </section>`).join('')}
    </div>`;
}
