// Overview tab: load aggregate stats, update health badge, and refresh both
// periodically so the UI reflects backend state without a reload.

import { api } from './api.js';
import { $ } from './util.js';

const STAT_MAP = [
  ['stat-functions', (d) => d.functions],
  ['stat-edges',     (d) => d.graph_edges],
  ['stat-coverage',  (d) => `${d.coverage_pct}%`],
  ['stat-warnings',  (d) => d.warnings],
  ['stat-bugs',      (d) => d.scan_bugs],
  ['stat-tests',     (d) => d.test_cases],
];

export async function loadStats() {
  try {
    const d = await api.stats();
    for (const [id, pick] of STAT_MAP) {
      const el = document.getElementById(id);
      const val = pick(d);
      if (el && val !== undefined && val !== null) el.textContent = val;
    }
  } catch {
    // Keep the baked-in defaults; non-fatal.
  }
}

export async function checkHealth() {
  const badge = $('#health-badge');
  if (!badge) return;
  try {
    const d = await api.health();
    const ok = d.status === 'ok' && d.neo4j === 'ok';
    const degraded = d.status === 'ok';
    badge.textContent = ok ? '● Connected' : degraded ? '● DB offline' : '● Error';
    badge.className = ok ? 'tag tag-green' : degraded ? 'tag tag-yellow' : 'tag tag-red';
  } catch {
    badge.textContent = '● Disconnected';
    badge.className = 'tag tag-red';
  }
}

export function startPolling({ statsMs = 30000, healthMs = 15000 } = {}) {
  setInterval(loadStats, statsMs);
  setInterval(checkHealth, healthMs);
}
