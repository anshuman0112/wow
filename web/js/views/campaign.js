import { campaign, flow, facts, pronunciation, edgeCases, voices } from '../campaign-data.js';
import { syncedAt } from '../voices.generated.js';
import { esc, moodBadge } from '../ui.js';

export default async function campaignView(el) {
  const p = campaign.persona;
  let cp = 0;
  el.innerHTML = `
    <div class="page-head">
      <div><h1>Campaign & knowledge</h1><p class="muted">Everything Divya says and knows comes from this page</p></div>
      <span class="badge b-ok"><span class="dot"></span>Active</span>
    </div>

    <div class="grid g-2">
      <section class="card card-pad">
        <h2>${esc(campaign.name)}</h2>
        <p class="muted small">${esc(campaign.client)}</p>
        <dl class="kv" style="margin-top:14px">
          <dt>Goal</dt><dd>${esc(campaign.goal)}</dd>
          <dt>Agent</dt><dd>${esc(p.name)} — ${esc(p.role)}</dd>
          <dt>Voice</dt><dd>${esc(p.voice)}</dd>
          <dt>Languages</dt><dd>${p.languages.map(esc).join(', ')}</dd>
          <dt>Tone</dt><dd>${esc(p.tone)}</dd>
          <dt>Reply length</dt><dd>${esc(p.maxReply)}</dd>
        </dl>
      </section>
      <section class="card card-pad">
        <h2>Tech stack</h2>
        <p class="muted small">Free tiers used for this build</p>
        <dl class="kv" style="margin-top:14px">
          ${campaign.stack.map(s => `<dt>${esc(s.part)}</dt><dd>${esc(s.tool)}</dd>`).join('')}
        </dl>
      </section>
    </div>

    <section class="card" style="margin-top:16px">
      <div class="card-head"><div><h2>Voices</h2><p class="muted small">ElevenLabs Flash v2.5 — every voice can speak English, Hindi and Hinglish. Pick one on the Talk page. ${syncedAt ? `Library synced ${esc(new Date(syncedAt).toLocaleString('en-IN'))}.` : 'Run <span class="mono">npm run voices</span> to add your ElevenLabs library.'}</p></div></div>
      <div class="list">
        ${voices.map((v, i) => `
          <div class="list-item">
            <div class="avatar">${esc(v.name[0])}</div>
            <div style="flex:1;min-width:0"><div class="row"><b>${esc(v.name)}</b>${i === 0 ? '<span class="badge b-brand">Default</span>' : ''}${v.pinned ? '<span class="badge b-gold">Your pick</span>' : `<span class="badge">${esc(v.category || 'library')}</span>`}</div>
              <div class="muted small">${esc(v.style)} · ${esc(v.languages)}</div></div>
            ${v.previewUrl
              ? `<audio controls preload="none" src="${esc(v.previewUrl)}" style="height:32px;max-width:220px"></audio>`
              : `<a class="btn btn-ghost small" href="https://elevenlabs.io/voices/${esc(v.id)}" target="_blank" rel="noopener">Preview ↗</a>`}
          </div>`).join('')}
      </div>
    </section>

    <section class="card" style="margin-top:16px">
      <div class="card-head"><div><h2>Conversation flow</h2><p class="muted small">From the assignment brief · numbered steps in green are the 4 qualification checkpoints · any step the lead already answered is skipped</p></div></div>
      <div class="steps">
        ${flow.map((s, i) => `
          <div class="step ${s.checkpoint ? 'cp' : ''}">
            <div class="step-n">${s.checkpoint ? ++cp : '•'}</div>
            <div>
              <div class="row"><h3>${esc(s.title)}</h3>${s.checkpoint ? '<span class="badge b-brand">Checkpoint</span>' : ''}</div>
              <p class="muted small" style="margin-top:2px">${esc(s.detail)}</p>
              <div class="quote">"${esc(s.line)}"</div>
            </div>
          </div>`).join('')}
      </div>
    </section>

    <section class="card" style="margin-top:16px">
      <div class="card-head">
        <div><h2>Fact sheet</h2><p class="muted small">Divya answers only from these facts. Anything else → "our Property Expert will confirm that". If a website disagrees with the brief, the brief wins.</p></div>
        <div class="row"><span class="badge b-brand">Brief</span><span class="badge b-gold">Web research</span></div>
      </div>
      <div class="grid g-2 card-pad">
        ${facts.map(g => `
          <div>
            <h3 style="margin-bottom:8px">${esc(g.group)}</h3>
            <dl class="kv">
              ${g.items.map(f => `<dt>${esc(f.k)}</dt><dd>${esc(f.v)} <span class="badge ${f.src === 'pdf' ? 'b-brand' : 'b-gold'}" style="font-size:10.5px;padding:0 6px">${f.src === 'pdf' ? 'Brief' : 'Web'}</span></dd>`).join('')}
            </dl>
          </div>`).join('')}
      </div>
    </section>

    <div class="grid g-2" style="margin-top:16px">
      <section class="card">
        <div class="card-head"><div><h2>Pronunciation guide</h2><p class="muted small">Included in the system prompt</p></div></div>
        <div class="table-wrap"><table>
          <thead><tr><th>Word</th><th>Say it as</th><th></th></tr></thead>
          <tbody>${pronunciation.map(x => `<tr><td class="cell-title">${esc(x.term)}</td><td>${esc(x.say)}</td><td>${x.from === 'PDF' ? '<span class="badge b-brand">Brief</span>' : ''}</td></tr>`).join('')}</tbody>
        </table></div>
      </section>
      <section class="card">
        <div class="card-head"><div><h2>Edge cases</h2><p class="muted small">Mood is read on every turn and the reply adapts</p></div></div>
        <div class="list">
          ${edgeCases.map(e => `
            <div class="list-item" style="align-items:flex-start">
              <div style="flex:1">
                <div class="row"><b>${esc(e.name)}</b>${moodBadge(e.mood)}</div>
                <p class="muted small" style="margin-top:3px">"${esc(e.reply)}"</p>
              </div>
            </div>`).join('')}
        </div>
      </section>
    </div>`;
}
