// Sign-in for the dashboard. The session token (7 days) is kept in this browser and sent with every API call.
import { config } from './config.js';

const KEY = 'wow-session';

export const session = () => { try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch { return null; } };
const save = s => { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch {} };
export const signedIn = () => { const s = session(); return !!(s && s.token && s.expires * 1000 > Date.now()); };

export function signOut() {
  try { localStorage.removeItem(KEY); sessionStorage.removeItem('wow-admin-pin'); } catch {}
  location.hash = '#/overview';
  location.reload();
}

// Add the session to every call to our API; a 401 means the session ended → back to the sign-in screen.
const realFetch = window.fetch.bind(window);
window.fetch = async (input, init = {}) => {
  const url = typeof input === 'string' ? input : input?.url || '';
  const ours = url.startsWith(config.apiBaseUrl) || url.startsWith('/api/');
  const s = session();
  if (ours && s?.token) init = { ...init, headers: { ...(init.headers || {}), Authorization: `Bearer ${s.token}` } };
  let res;
  const method = (init.method || 'GET').toUpperCase();
  for (let attempt = 0; ; attempt++) {
    try { res = await realFetch(input, init); break; }
    catch (e) {   // network blip ("Failed to fetch"): retry reads twice, quickly
      if (!ours || method !== 'GET' || attempt >= 2) throw e;
      await new Promise(r => setTimeout(r, 400 * (attempt + 1)));
    }
  }
  if (ours && res.status === 401 && signedIn() && !url.includes('/auth/login')) {
    try { localStorage.removeItem(KEY); } catch {}
    location.reload();
  }
  return res;
};

export function renderSignIn(root) {
  root.innerHTML = `
    <main style="min-height:100vh;display:grid;place-items:center;padding:16px;background:var(--bg, #f6f3ec)">
      <form id="signin" class="card card-pad" style="width:100%;max-width:380px;display:grid;gap:12px">
        <div><div class="faint small">Whispers of the Wind · Divyasree Developers</div>
          <h1 style="margin:4px 0 2px">Sign in</h1>
          <p class="muted small">The WOW voice agent dashboard is private.</p></div>
        <label class="small" style="display:grid;gap:4px">Email
          <input class="input" name="email" type="email" autocomplete="username" required></label>
        <label class="small" style="display:grid;gap:4px">Password
          <input class="input" name="password" type="password" autocomplete="current-password" required></label>
        <button class="btn btn-primary" id="go" type="submit">Sign in</button>
        <p class="small" id="err" role="alert" style="color:var(--bad, #b3261e);min-height:1em;margin:0"></p>
        <p class="faint small" style="margin:0">Leads can still enquire on the public <a href="enquire.html">Enquire page</a>.</p>
      </form>
    </main>`;
  const f = root.querySelector('#signin');
  f.querySelector('[name=email]').focus();
  f.onsubmit = async e => {
    e.preventDefault();
    const go = f.querySelector('#go'), err = f.querySelector('#err');
    go.disabled = true; go.textContent = 'Signing in…'; err.textContent = '';
    try {
      const d = Object.fromEntries(new FormData(f));
      const r = await realFetch(`${config.apiBaseUrl}/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: d.email, password: d.password }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || 'Could not sign in');
      save(j);
      location.reload();
    } catch (ex) { err.textContent = ex.message; go.disabled = false; go.textContent = 'Sign in'; }
  };
}
