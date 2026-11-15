import { icon } from './ui.js';
import { mode } from './store.js';
import overview from './views/overview.js';
import talk from './views/talk.js';
import voicesView from './views/voices.js';
import leads from './views/leads.js';
import calls from './views/calls.js';
import campaignView from './views/campaign.js';
import brief from './views/brief.js';
import integrations from './views/integrations.js';

const routes = [
  { path: 'overview', label: 'Overview', icon: 'home', view: overview },
  { path: 'talk', label: 'Talk to Aanya', icon: 'mic', view: talk },
  { path: 'voices', label: 'Phone voices', icon: 'play', view: voicesView },
  { path: 'leads', label: 'Leads', icon: 'users', view: leads },
  { path: 'calls', label: 'Calls', icon: 'history', view: calls },
  { section: 'Setup' },
  { path: 'campaign', label: 'Campaign & knowledge', icon: 'book', view: campaignView },
  { path: 'brief', label: 'Assignment checklist', icon: 'list', view: brief },
  { path: 'integrations', label: 'Integrations', icon: 'plug', view: integrations },
];

const viewEl = document.getElementById('view');
let cleanup = null;

function renderNav(active) {
  document.getElementById('nav').innerHTML = routes.map(r => r.section
    ? `<div class="nav-label">${r.section}</div>`
    : `<a href="#/${r.path}" class="${r.path === active ? 'active' : ''}">${icon(r.icon)}<span>${r.label}</span></a>`).join('');
  document.getElementById('mobile-nav').innerHTML = routes.filter(r => r.path)
    .map(r => `<a href="#/${r.path}" class="${r.path === active ? 'active' : ''}">${r.label}</a>`).join('');
}

async function router() {
  const [path, ...rest] = (location.hash.replace(/^#\/?/, '') || 'overview').split('/');
  const route = routes.find(r => r.path === path) || routes[0];
  renderNav(route.path);
  if (typeof cleanup === 'function') { try { cleanup(); } catch {} }
  cleanup = null;
  viewEl.innerHTML = '<div class="empty">Loading…</div>';
  try {
    cleanup = await route.view(viewEl, rest);
  } catch (e) {
    console.error(e);
    viewEl.innerHTML = `<div class="card card-pad"><h2>Something went wrong</h2><p class="muted" style="margin-top:6px">${String(e.message || e)}</p></div>`;
  }
  document.title = `${route.label} · Vaani`;
  viewEl.focus({ preventScroll: true });
}

// Theme toggle (remembered per browser)
const root = document.documentElement;
try { const t = localStorage.getItem('vaani-theme'); if (t) root.dataset.theme = t; } catch {}
document.getElementById('theme-btn').addEventListener('click', () => {
  const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  root.dataset.theme = dark ? 'light' : 'dark';
  try { localStorage.setItem('vaani-theme', root.dataset.theme); } catch {}
});

document.getElementById('mode-pill').innerHTML = mode() === 'live'
  ? '<span class="badge b-ok"><span class="dot"></span>Live data</span>'
  : '<span class="badge b-gold"><span class="dot"></span>Demo data</span>';

window.addEventListener('hashchange', router);
router();
