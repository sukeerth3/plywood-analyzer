// Entry point. Imported as a module by index.html.

import { initTabs } from './tabs.js';
import { initQueries, preloadQueryCode } from './queries.js';
import { initOptions } from './options.js';
import { initNL } from './nl.js';
import { loadStats, checkHealth, startPolling } from './stats.js';
import { loadSource, initSourceControls } from './source.js';
import { loadSchema } from './schema.js';
import { initEvidence } from './evidence.js';

function boot() {
  initTabs();
  initQueries();
  initNL();
  initSourceControls();
  initEvidence();
  const optionsReady = initOptions();

  // Fire-and-forget initial loads in parallel.
  loadStats();
  checkHealth();
  loadSource();
  loadSchema();
  optionsReady.finally(() => preloadQueryCode());

  startPolling();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot, { once: true });
} else {
  boot();
}
