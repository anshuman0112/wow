// Assignment checklist — every requirement from the Revspot PDF and where it is handled.
import { esc, icon } from '../ui.js';

const S = { done: ['Done', 'b-ok'], build: ['Designed · being built', 'b-gold'], todo: ['To do', ''] };

const sections = [
  { title: '1. Conversation architecture', items: [
    ['Introduction as a Divyasree consultant, mentions project and location', 'Greeting: "This is Divya, a consultant from Divyasree Developers, calling about Whispers of the Wind… near Nandi Hills"', 'done'],
    ['Always asks permission to speak', 'Greeting ends with "Is this a good time for two minutes?"', 'done'],
    ['Checkpoint: intent (self-use vs investment)', 'Asked first: "Are you looking for a weekend home or an investment?"', 'done'],
    ['Checkpoint: geography (Nandi Hills / Devanahalli corridor)', 'Asked second; a code check makes sure it is never skipped', 'done'],
    ['Checkpoint: budget (₹92.4 lakh+ fitment)', 'Asked third, with a two-step persuasive counter if the budget is lower', 'done'],
    ['Checkpoint: timeline (phased delivery, Dec 2029)', 'Asked fourth: "Possession is December 2029, is that comfortable?"', 'done'],
    ['The pitch: "Private Valley" lifestyle — clubhouse, nature, community', 'Only after all 4 checkpoints: private valley, 74% open green space, eco-parks, 20,000 sq ft clubhouse, like-minded community', 'done'],
    ['CTA: follow-up call with a Property Expert', 'The lead picks the day and time (never invented); callback time saved on the Calls page', 'done'],
  ]},
  { title: '2. Technical requirements', items: [
    ['Affirmations ("Understood", "Perfect")', 'Heard in live calls: "Understood", "Perfect", "Got it", "Great"', 'done'],
    ['No re-asking if the user gave info early', 'A checkpoint tracker in code marks what the lead already said; tested: an early budget or intent is never asked again', 'done'],
    ['Pronunciation guide: Divyasree, Nandi, Lakh, Crore', 'In the system prompt (Div-yaa-shree, Nun-dhee, Laakh, Kror) and applied to phone speech', 'done'],
    ['Tone: premium, conversational, non-intrusive', 'Premium HD voice, max 2 short sentences, never pushy, polite exit after two counters', 'done'],
    ['Holds a 2–3 minute conversation', 'Live phone call: 2 min 51 s, all 4 checkpoints covered, callback booked', 'done'],
  ]},
  { title: '3. Deliverables', items: [
    ['Demo link — shareable working bot', 'https://vaani-divyasree.vercel.app → Talk to Divya (browser) · Leads → verify a number for a real phone call', 'done'],
    ['Or recorded audio — at least 5 conversation flows', 'Browser calls are recorded automatically (Calls page). Still to record: happy path, low budget, far location, Hindi, irritated lead', 'todo'],
    ['System Prompt (PDF) with pronunciation dictionary', 'docs/System_Prompt.pdf (also in the GitHub repo)', 'done'],
  ]},
  { title: 'Bonus', items: [
    ['Edge cases: irritated user, budget fit but not location, etc.', 'Two-step persuasive counters (benefits, staged payments, plot loans, growth corridor, the small gap) + irritated/angry/busy handling + mood detection, in the prompt and the phone engine', 'done'],
    ['Multilingual: English + Hindi', 'Switches to Hinglish when the lead does (browser: Deepgram multi + ElevenLabs; phone: Hinglish replies, FAQ answers and objections in both languages)', 'done'],
    ['Additional project details if asked (searched online)', 'Fact sheet: 38 acres, ~207 plots, RERA, ~Rs 7,700/sq ft, schools, hospitals, distances (Campaign page, items tagged "Web")', 'done'],
  ]},
  { title: 'Extras beyond the brief', items: [
    ['Real phone calls to leads', 'Leads → Call phone (free Twilio trial); reviewers verify their number on the Leads page first', 'done'],
    ['Phone voice library', 'Voices page: 7 phone voices with ▶ preview + 3 browser voices, one clear place to choose both', 'done'],
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
