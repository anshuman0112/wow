// Live browser call with Divya via the Vapi Web SDK (this is the shareable demo link).
import { config, isLive } from '../config.js';
import { voices, voiceConfig, browserVoice } from '../campaign-data.js';
import { getCalls, getLeads } from '../store.js';
import { esc, icon, toast, statusBadge, interestBadge } from '../ui.js';

export default async function talk(el, [leadId] = []) {
  const live = isLive.vapi();
  // Opened from Leads → "Call now": personalise the call for that lead and link the result to it.
  const lead = leadId ? (await getLeads().catch(() => [])).find(l => l.id === leadId) : null;
  const firstName = (lead?.name || '').trim().split(/\s+/)[0] || '';
  let vapi = null, state = 'idle', muted = false, timer = null, seconds = 0, demoStop = false;
  const transcript = []; // { role, text, partial }

  el.innerHTML = `
    <div class="page-head">
      <div><h1>Talk to Divya</h1><p class="muted">Divyasree consultant · Whispers of the Wind · English & Hindi</p></div>
    </div>
    ${lead ? `<section class="card card-pad" style="margin-bottom:16px">
      <div class="row">
        <div class="avatar">${esc((lead.name || '?')[0])}</div>
        <div style="flex:1;min-width:0"><b>Calling ${esc(lead.name || 'lead')}</b> ${statusBadge(lead.status)}
          <div class="muted small">${esc(lead.phone || '')}${lead.location ? ' · ' + esc(lead.location) : ''}${lead.budget ? ' · budget ' + esc(lead.budget) : ''}</div></div>
        <a class="btn btn-ghost small" href="#/talk">Not this lead</a>
      </div>
      <p class="muted small" style="margin-top:10px">Browser call: you play ${esc(firstName || 'the lead')}. Divya greets them by name, and the result (summary, hot / warm / cold, callback) is saved to this lead automatically.</p>
    </section>` : ''}
    ${live ? '' : `<div class="banner">${icon('info')}<span><b>Live calling is not connected yet.</b> Add the Vapi public key and assistant ID in <span class="mono">web/js/config.js</span>. Meanwhile you can replay a sample conversation (text only).</span></div>`}
    <div class="grid g-main">
      <section class="card">
        <div class="orb-wrap">
          <div class="orb" id="orb"><div class="orb-inner">${icon('mic')}</div></div>
          <div>
            <div class="status-line"><span class="pulse" id="pulse"></span><span id="status">Ready</span></div>
            <div class="muted small mono" id="clock" style="margin-top:4px">0:00</div>
          </div>
          <div class="row" style="justify-content:center;gap:12px">
            ${live ? `<label class="small muted" style="display:flex;flex-direction:column;gap:4px;align-items:center">Your first name (optional)
              <input class="input" id="caller" maxlength="40" placeholder="e.g. Rahul" value="${esc(firstName)}" style="width:180px;text-align:center"></label>` : ''}
          </div>
          <p class="muted small" style="margin-top:-6px">Voice for this browser call: <b>${esc(browserVoice().name)}</b> · <a href="#/voices">change on the Voices page</a></p>
          <div class="row" style="justify-content:center">
            <button class="btn btn-primary" id="start">${icon('phone')}${live ? 'Start call' : 'Replay sample call'}</button>
            <button class="btn" id="mute" hidden>${icon('micOff')}Mute</button>
            <button class="btn btn-danger" id="stop" hidden>${icon('end')}End call</button>
          </div>
          <p class="muted small" style="max-width:380px">Speak naturally — you can interrupt Divya at any time and she will stop and listen. Try asking in Hindi, or tell her the budget is too high.</p>
        </div>
      </section>
      <section class="card">
        <div class="card-head"><h2>Live score</h2><span class="muted small" id="live-note">updates after each answer</span></div>
        <div class="card-pad" id="live-score">
          <div class="row" style="gap:10px"><span class="mono" id="ls-num" style="font-size:28px;font-weight:650">0</span><span class="muted">/100</span>
            <span class="spacer"></span><span id="ls-tier"></span></div>
          <div style="height:8px;border-radius:6px;background:var(--border);margin:8px 0 10px;overflow:hidden">
            <div id="ls-bar" style="height:100%;width:0%;background:var(--brand, #2f6b4f);transition:width .4s"></div></div>
          <div class="stack small" id="ls-rows" style="gap:4px"><span class="muted">Start a call: the score fills in as the lead answers.</span></div>
        </div>
        <div class="card-head" style="border-top:1px solid var(--border)"><h2>Live transcript</h2><span class="muted small" id="turns"></span></div>
        <div class="transcript" id="tx" aria-live="polite" style="min-height:320px;max-height:560px;overflow-y:auto">
          <div class="empty" id="tx-empty">The conversation will appear here.</div>
        </div>
      </section>
    </div>
    <section class="card card-pad" style="margin-top:16px">
      <h2>Things to try</h2>
      <div class="grid g-3" style="margin-top:12px">
        ${tip('Happy path', '"It is for investment, budget around 1.5 crore."')}
        ${tip('Hindi', '"Kya hum Hindi mein baat kar sakte hain?"')}
        ${tip('Budget too low', '"My budget is only 70 lakhs."')}
        ${tip('Location doubt', '"Nandi Hills is too far for me."')}
        ${tip('Irritated', '"Why are you calling me? I am busy."')}
        ${tip('Off-topic', '"What is the exact price of a corner plot?"')}
      </div>
    </section>`;

  const $ = id => el.querySelector('#' + id);

  const setState = s => {
    state = s;
    if (!$('status')) return;
    const labels = { idle: 'Ready', connecting: 'Connecting…', listening: 'Listening', speaking: 'Divya is speaking', ended: 'Call ended' };
    $('status').textContent = labels[s] || s;
    $('pulse').classList.toggle('on', s === 'listening' || s === 'speaking');
    $('orb').classList.toggle('live', s === 'listening' || s === 'speaking');
    const inCall = ['connecting', 'listening', 'speaking'].includes(s);
    $('start').hidden = inCall; $('stop').hidden = !inCall; $('mute').hidden = !inCall || !live;
    if (inCall && !timer) { seconds = 0; timer = setInterval(() => { seconds++; $('clock').textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`; }, 1000); }
    if (!inCall && timer) { clearInterval(timer); timer = null; }
  };

  const renderTx = () => {
    const box = $('tx');
    if (!box || !transcript.length) return;
    box.innerHTML = transcript.map(m => `<div class="msg ${m.role}${m.partial ? ' partial' : ''}"><span class="who">${m.role === 'assistant' ? 'Divya' : 'You'}</span>${esc(m.text)}</div>`).join('');
    box.scrollTop = box.scrollHeight;
    $('turns').textContent = `${transcript.filter(m => !m.partial).length} turns`;
  };

  const onTranscript = (role, text, partial) => {
    const last = transcript[transcript.length - 1];
    if (last && last.partial && last.role === role) { last.text = text; last.partial = partial; }
    else transcript.push({ role, text, partial });
    renderTx();
    if (!partial && role === 'user') queueLiveScore();
  };

  // Live score: after each finished lead answer, score the conversation so far (same rules as the final profile).
  let lsTimer = null, lsBusy = false, lsAgain = false;
  const queueLiveScore = () => { clearTimeout(lsTimer); lsTimer = setTimeout(runLiveScore, 1200); };
  async function runLiveScore() {
    if (lsBusy) { lsAgain = true; return; }
    lsBusy = true;
    try {
      const r = await fetch(`${config.apiBaseUrl}/score/live`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: transcript.filter(m => !m.partial).map(m => ({ role: m.role, text: m.text })) }) });
      if (r.ok) paintScore(await r.json());
    } catch {}
    lsBusy = false;
    if (lsAgain) { lsAgain = false; queueLiveScore(); }
  }
  function paintScore(s) {
    if (!$('ls-num')) return;
    $('ls-num').textContent = s.score; $('ls-bar').style.width = `${s.score}%`;
    $('ls-tier').innerHTML = interestBadge(s.tier);
    const mark = r => r.key === 'tone' ? '◑' : r.verdict === 'yes' ? '✅' : r.verdict === 'partial' ? '◐' : r.verdict === 'no' ? '✖️' : '·';
    $('ls-rows').innerHTML = (s.breakdown || []).map(r => `<div class="row" style="gap:8px;flex-wrap:nowrap"><span>${mark(r)}</span>
      <span style="flex:1">${esc(r.label)}${r.evidence ? ` <span class="muted">“${esc(r.evidence)}”</span>` : ''}</span>
      <span class="mono">${r.points > 0 ? '+' : ''}${r.points}</span></div>`).join('')
      + ((s.hot_blocked_by || []).length ? `<div class="muted">Not Hot yet: needs ${esc(s.hot_blocked_by.join(', '))}</div>` : '');
  }

  async function startLive() {
    setState('connecting');
    try {
      const mod = await import('https://esm.sh/@vapi-ai/web@3.1.0');
      const Vapi = mod.default?.default || mod.default;
      vapi = new Vapi(config.vapiPublicKey);
      vapi.on('call-start', () => setState('listening'));
      vapi.on('call-end', () => setState('ended'));
      vapi.on('speech-start', () => setState('speaking'));
      vapi.on('speech-end', () => setState('listening'));
      vapi.on('volume-level', v => { $('orb').style.transform = `scale(${1 + Math.min(v, 1) * 0.12})`; });
      vapi.on('message', m => {
        if (m.type === 'transcript') onTranscript(m.role === 'user' ? 'user' : 'assistant', m.transcript, m.transcriptType === 'partial');
      });
      vapi.on('error', e => { console.error(e); toast('Call error — check the Vapi keys'); setState('ended'); });
      const name = (el.querySelector('#caller')?.value || '').trim();
      const voiceId = browserVoice().id;
      const overrides = { voice: voiceConfig(voiceId), metadata: { campaign_id: 'divyasree-wow', voice: voiceId, ...(lead ? { lead_id: lead.id } : {}) } };
      const vars = {};
      if (name) vars.name = name;
      if (lead?.location) vars.location = lead.location;
      if (lead) vars.lead_id = lead.id;
      if (Object.keys(vars).length) overrides.variableValues = vars;
      await vapi.start(config.vapiAssistantId, overrides);
    } catch (e) {
      console.error(e); toast('Could not start the call: ' + (e.message || e)); setState('idle');
    }
  }

  async function startDemo() {
    demoStop = false;
    const [sample] = await getCalls();
    setState('connecting');
    await wait(600);
    for (const m of sample.messages) {
      if (demoStop) return;
      setState(m.role === 'assistant' ? 'speaking' : 'listening');
      const words = m.text.split(' ');
      for (let i = 1; i <= words.length; i += 3) {
        if (demoStop) return;
        onTranscript(m.role, words.slice(0, i).join(' '), true);
        await wait(110);
      }
      if (demoStop) return;
      onTranscript(m.role, m.text, false);
      await wait(500);
    }
    if (!demoStop) setState('ended');
  }

  $('start').onclick = () => { transcript.length = 0; $('tx').innerHTML = ''; live ? startLive() : startDemo(); };
  $('stop').onclick = () => { demoStop = true; vapi?.stop(); setState('ended'); };
  $('mute').onclick = () => { muted = !muted; vapi?.setMuted(muted); $('mute').innerHTML = `${icon(muted ? 'mic' : 'micOff')}${muted ? 'Unmute' : 'Mute'}`; };

  return () => { demoStop = true; try { vapi?.stop(); } catch {} if (timer) clearInterval(timer); };
}

const wait = ms => new Promise(r => setTimeout(r, ms));
const tip = (t, s) => `<div class="cp-box"><div class="k">${t}</div><div class="v" style="font-weight:450">${esc(s)}</div></div>`;
