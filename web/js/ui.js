// Small UI helpers shared by all views.

export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const P = {
  home: '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
  phone: '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6.5 6.5 0 0 1 3.5 6"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>',
  book: '<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 21V5M8 7h7"/>',
  check: '<path d="M20 6L9 17l-5-5"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4 6h.01M4 12h.01M4 18h.01"/>',
  plug: '<path d="M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0zM12 18v4"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  micOff: '<path d="M3 3l18 18M9 9v2a3 3 0 0 0 5 2.2M15 9.5V6a3 3 0 0 0-6 0"/><path d="M5 11a7 7 0 0 0 11.5 5.3M19 11a7 7 0 0 1-.6 2.8M12 18v3"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  play: '<path d="M7 4l13 8-13 8z"/>',
  end: '<path d="M3 15c5-5 13-5 18 0l-2.5 2.5-3-1.5v-2.5a10 10 0 0 0-7 0V16l-3 1.5z"/>',
  file: '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
};
export const icon = (name, size) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"${size ? ` style="width:${size}px;height:${size}px"` : ''} aria-hidden="true">${P[name] || ''}</svg>`;

export const initials = n => String(n || '?').split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase();

export const fmtDur = s => `${Math.floor((s || 0) / 60)}:${String(Math.round((s || 0) % 60)).padStart(2, '0')}`;

export const fmtDate = iso => iso ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Kolkata' }) : '—';

export function interestBadge(v) {
  if (!v) return '<span class="badge">Not scored</span>';
  const label = { hot: 'Hot', warm: 'Warm', cold: 'Cold' }[v] || v;
  return `<span class="badge b-${esc(v)}"><span class="dot"></span>${label}</span>`;
}

export function statusBadge(v) {
  const m = {
    new: ['New', 'b-brand'], queued: ['Queued', 'b-gold'], calling: ['Calling', 'b-gold'],
    called: ['Called', 'b-ok'], no_answer: ['No answer', ''], do_not_call: ['Do not call', 'b-bad'],
    re_engaged: ['Interested again', 'b-hot'],
    callback: ['Call-back', 'b-gold'],
  }[v] || [v || '—', ''];
  return `<span class="badge ${m[1]}">${m[0]}</span>`;
}

export function moodBadge(v) {
  const m = { positive: 'b-ok', calm: 'b-brand', hesitant: 'b-gold', irritated: 'b-warm', angry: 'b-bad' }[v] || '';
  return `<span class="badge ${m}">${esc(v || '—')}</span>`;
}

export function toast(text) {
  const t = document.createElement('div');
  t.className = 'toast'; t.textContent = text; t.setAttribute('role', 'status');
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2600);
}

export function demoBanner(mode) {
  if (mode !== 'demo') return '';
  return `<div class="banner">${icon('info')}<span><b>Demo mode — sample data.</b> These leads and calls are illustrative examples. Add Supabase keys in <span class="mono">web/js/config.js</span> to show real calls.</span></div>`;
}
