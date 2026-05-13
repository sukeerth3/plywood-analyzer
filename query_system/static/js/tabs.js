// Accessible tab router. Synchronises with URL hash so deep-links and
// back/forward buttons work. Fires a "tab:change" CustomEvent consumers
// can listen for to lazy-load panel content.

import { $$ } from './util.js';

const DEFAULT = 'overview';

function setTab(name) {
  $$('.nav-tab').forEach((t) => {
    const active = t.dataset.tab === name;
    t.setAttribute('aria-selected', active ? 'true' : 'false');
    t.tabIndex = active ? 0 : -1;
  });
  $$('.panel').forEach((p) => {
    const active = p.id === `panel-${name}`;
    p.setAttribute('aria-hidden', active ? 'false' : 'true');
  });
  if (window.location.hash.slice(1) !== name) {
    history.replaceState(null, '', `#${name}`);
  }
  window.dispatchEvent(new CustomEvent('tab:change', { detail: { name } }));
}

function fromHash() {
  const h = window.location.hash.slice(1);
  const valid = ['overview', 'storage', 'queries', 'pipeline'];
  return valid.includes(h) ? h : DEFAULT;
}

export function initTabs() {
  const tabs = $$('.nav-tab');

  tabs.forEach((t) => {
    t.addEventListener('click', () => setTab(t.dataset.tab));
    t.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      const idx = tabs.indexOf(t);
      const next = (idx + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      tabs[next].focus();
      setTab(tabs[next].dataset.tab);
    });
  });

  window.addEventListener('hashchange', () => setTab(fromHash()));
  setTab(fromHash());
}
