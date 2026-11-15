// Admin PIN for actions that reveal real phone numbers or change settings. Asked once per browser session.
const KEY = 'wow-admin-pin';

export function getPin() {
  try { if (JSON.parse(localStorage.getItem('wow-session') || 'null')?.token) return 'signed-in'; } catch {}
  let pin = '';
  try { pin = sessionStorage.getItem(KEY) || ''; } catch {}
  if (!pin) pin = window.prompt('Admin PIN:') || '';
  return pin;
}

export function rememberPin(pin) { try { sessionStorage.setItem(KEY, pin); } catch {} }
export function forgetPin() { try { sessionStorage.removeItem(KEY); } catch {} }

// fetch with the PIN header; forgets a wrong PIN so the next try asks again.
export async function pinFetch(url, opts = {}) {
  const pin = getPin();
  if (!pin) throw new Error('PIN needed');
  const r = await fetch(url, { ...opts, headers: { ...(opts.headers || {}), 'X-Admin-Pin': pin } });
  if (r.status === 401) { forgetPin(); throw new Error('Wrong admin PIN'); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `Request failed (${r.status})`);
  rememberPin(pin);
  return r;
}
