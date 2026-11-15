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
    ['Affirmations ("Understood", "Perfect")', 'System prompt rule 4 · heard in the first live call ("Wonderful", "Understood")', 'done'],
    ['No re-asking if the user gave info early', 'System prompt checkpoint tracker; full history sent every turn', 'build'],
    ['Pronunciation guide: Divyasree, Nandi, Lakh, Crore', 'Campaign → Pronunciation guide (in system prompt)', 'done'],
    ['Tone: premium, conversational, non-intrusive', 'Persona + max 2-sentence replies', 'done'],
    ['Holds a 2–3 minute conversation', 'First live call: 2 min 28 s, ended by Aanya after booking the callback', 'done'],
  ]},
  { title: '3. Deliverables', items: [
    ['Demo link — shareable working bot', 'https://vaani-divyasree.vercel.app → Talk to Aanya', 'done'],
    ['Or recorded audio — at least 5 conversation flows', '6 scenarios to record on the live bot (Calls page keeps each recording)', 'todo'],
    ['System Prompt (PDF) with pronunciation dictionary', 'docs/System_Prompt.pdf (npm run pdf)', 'done'],
  ]},
  { title: 'Bonus', items: [
    ['Edge cases: irritated user, budget fit but not location, etc.', 'Two-step persuasive counters (benefits, staged payments, plot loans, growth corridor, the small gap) + irritated/angry/busy handling + mood detection, in the prompt and the phone engine', 'done'],
    ['Multilingual: English + Hindi', 'Switches to Hinglish when the lead does (browser: Deepgram multi + ElevenLabs; phone: Hinglish replies, FAQ answers and objections in both languages)', 'done'],
    ['Additional project details if asked (searched online)', 'Fact sheet: 38 acres, ~207 plots, RERA, ~Rs 7,700/sq ft, schools, hospitals, distances (Campaign page, items tagged "Web")', 'done'],
  ]},
  { title: 'Extras beyond the brief', items: [
    ['Real phone calls to leads', 'Leads → Call phone (free Twilio trial); reviewers verify their number on the Leads page first', 'done'],
    ['Phone voice library', 'Phone voices page: 7 voices, play in the browser, choose the one calls use', 'done'],
    ['Every call, transcript and summary stored', 'Python API (FastAPI) saves calls to Supabase with AI summary, interest and checkpoints', 'done'],
    ['Automatic hot / warm / cold scoring and mood tracking', 'AI analysis after each call → Calls page', 'done'],
    ['Zero-token answers for most-asked questions', 'Redis FAQ cache (price, amenities, schools, hospitals, location, RERA, payment...)', 'done'],
    ['Upload any lead file (CSV, Excel, JSON, SQL)', 'Leads → Import (auto column detection)', 'done'],
    ['Reusable for other businesses', 'All knowledge in campaign.json + knowledge builder API', 'done'],
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
