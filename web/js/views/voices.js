import { config } from '../config.js';
import { esc, icon, toast } from '../ui.js';
import { voices as browserVoices, browserVoice, setBrowserVoice } from '../campaign-data.js';

// Phone voice library: listen to each voice (▶ plays the exact Twilio voice in the browser) and pick
// the one Divya uses on every real phone call.
const SDK = 'https://cdn.jsdelivr.net/npm/@twilio/voice-sdk@2.18.5/dist/twilio.min.js';
let device = null, deviceAt = 0, current = null;

function loadSdk() {
  if (window.Twilio?.Device) return Promise.resolve();
  return new Promise((ok, fail) => {
    const s = document.createElement('script');
    s.src = SDK; s.onload = ok; s.onerror = () => fail(new Error('Could not load the Twilio player'));
    document.head.appendChild(s);
  });
}

async function getDevice() {
  if (device && Date.now() - deviceAt < 4 * 60 * 1000) return device;   // tokens live 5 minutes
  await loadSdk();
  const r = await fetch(`${config.apiBaseUrl}/voices/preview-token`);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Preview not available');
  const { token } = await r.json();
  device?.destroy();
  device = new window.Twilio.Device(token, { logLevel: 'error', codecPreferences: ['opus', 'pcmu'], tokenRefreshMs: 60000 });
  deviceAt = Date.now();
  device.on('tokenWillExpire', async () => {   // keep a long-open page working
    try { device.updateToken((await (await fetch(`${config.apiBaseUrl}/voices/preview-token`)).json()).token); deviceAt = Date.now(); }
    catch { closeDevice(); }
  });
  device.on('error', err => { if (err?.code === 20104) closeDevice(); });   // expired: rebuild on next Play
  return device;
}

function closeDevice() { try { device?.destroy(); } catch {} device = null; }

export default async function voices(el) {
  let data;
  try { data = await (await fetch(`${config.apiBaseUrl}/voices/phone`)).json(); }
  catch { el.innerHTML = '<p class="muted">Could not reach the API.</p>'; return; }

  const render = () => {
    el.innerHTML = `
      <div class="page-head">
        <div><h1>Voices</h1>
        <p class="muted">Divya talks through two different systems, and each has its own voices. Pick one for each.</p></div>
      </div>
      <h2 style="margin:4px 0 10px">📞 Phone calls <span class="muted small" style="font-weight:400">· real calls to a lead's phone (Twilio voices)</span></h2>
      <div class="banner">${icon('info')}<span>Previews play through your speakers via Twilio. Your browser may ask for
        microphone permission once: it is only needed to open the audio line, nothing is recorded.
        Phone networks carry 8 kHz audio, so the HD voices are the clearest choice.</span></div>
      <div class="grid g-3">
        ${data.library.map((v, n) => {
          const inUse = v.id === data.selected;
          return `
          <section class="card card-pad" style="${inUse ? 'outline:2px solid var(--brand, #8a6d3b)' : ''}">
            <div class="row"><h2>${n + 1}. ${esc(v.label)}</h2><span class="spacer"></span>
              ${inUse ? '<span class="badge b-ok">In use</span>' : ''}</div>
            <p class="muted" style="margin-top:6px">${esc(v.style)}</p>
            <p class="small faint mono" style="margin-top:6px">${esc(v.id)}</p>
            <div class="row" style="margin-top:12px;gap:8px">
              <button class="btn btn-ghost" data-play="${esc(v.id)}">${icon('play')}<span>Play</span></button>
              <button class="btn ${inUse ? '' : 'btn-primary'}" data-use="${esc(v.id)}" ${inUse ? 'disabled' : ''}>
                ${icon('check')}<span>${inUse ? 'Selected' : 'Use this voice'}</span></button>
            </div>
          </section>`; }).join('')}
      </div>
      <h2 style="margin:28px 0 6px">🌐 Browser calls <span class="muted small" style="font-weight:400">· "Talk to Divya" in the browser (ElevenLabs voices via Vapi)</span></h2>
      <p class="muted small" style="margin-bottom:10px">Saved in this browser. To hear one, choose it and start a call on Talk to Divya.</p>
      <div class="grid g-3">
        ${browserVoices.map(v => {
          const inUse = v.id === browserVoice().id;
          return `
          <section class="card card-pad" style="${inUse ? 'outline:2px solid var(--brand, #8a6d3b)' : ''}">
            <div class="row"><h2>${esc(v.name)}</h2><span class="spacer"></span>
              ${inUse ? '<span class="badge b-ok">In use</span>' : ''}</div>
            <p class="muted" style="margin-top:6px">${esc(v.style || '')}</p>
            <p class="small faint" style="margin-top:6px">${esc(v.languages || '')}</p>
            <div class="row" style="margin-top:12px;gap:8px">
              ${v.previewUrl ? `<audio controls preload="none" src="${esc(v.previewUrl)}" style="height:32px;max-width:100%"></audio>` : ''}
              <button class="btn ${inUse ? '' : 'btn-primary'}" data-buse="${esc(v.id)}" ${inUse ? 'disabled' : ''}>
                ${icon('check')}<span>${inUse ? 'Selected' : 'Use this voice'}</span></button>
            </div>
          </section>`; }).join('')}
      </div>`;
  };
  render();

  const stop = () => { try { current?.disconnect(); } catch {} current = null; };
  const setPlaying = id => el.querySelectorAll('[data-play]').forEach(b => {
    const on = b.dataset.play === id;
    b.innerHTML = `${icon(on ? 'end' : 'play')}<span>${on ? 'Stop' : 'Play'}</span>`;
  });

  el.addEventListener('click', async e => {
    const play = e.target.closest('[data-play]'), use = e.target.closest('[data-use]'), buse = e.target.closest('[data-buse]');
    if (buse) {
      setBrowserVoice(buse.dataset.buse);
      toast(`Browser calls will now use ${browserVoice().name}`);
      render();
      return;
    }
    if (play) {
      const id = play.dataset.play;
      const wasPlaying = current && current._voice === id;
      stop(); setPlaying(null);
      if (wasPlaying) return;
      play.disabled = true; play.innerHTML = `${icon('play')}<span>Connecting…</span>`;
      try {
        const dev = await getDevice();
        current = await dev.connect({ params: { voice: id } });
        current._voice = id;
        setPlaying(id);
        const done = () => { if (current?._voice === id) current = null; setPlaying(null); };
        current.on('disconnect', done); current.on('cancel', done);
        current.on('error', err => { toast(`Preview failed: ${err.message || err}`); done(); });
      } catch (err) { toast(err.message || 'Preview failed'); setPlaying(null); }
      play.disabled = false;
    }
    if (use) {
      use.disabled = true;
      const r = await fetch(`${config.apiBaseUrl}/voices/phone`, { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ voice: use.dataset.use }) });
      if (r.ok) {
        data.selected = (await r.json()).selected;
        const v = data.library.find(x => x.id === data.selected);
        toast(`Divya will now call leads with ${v?.label || 'this voice'}`);
        stop(); render();
      } else { toast('Could not save the voice'); use.disabled = false; }
    }
  });
  return () => { stop(); closeDevice(); };   // leaving the page closes the audio line
}
