// Natural-language query panel: runs /api/query, renders the answer,
// and shows a helpful degraded-mode message when ANTHROPIC_API_KEY is missing.

import { api, ApiError } from './api.js';
import { $, escapeHtml } from './util.js';

function show(el, msg, { error = false } = {}) {
  el.textContent = msg;
  el.className = 'nl-result visible' + (error ? ' error' : '');
}

async function run() {
  const input = $('#nl-input');
  const out = $('#nl-result');
  if (!input || !out) return;
  const q = input.value.trim();
  if (!q) return;

  show(out, 'Running query…');

  try {
    const data = await api.nlQuery(q);
    let msg = data.answer || JSON.stringify(data.results || data, null, 2);
    if (data.explanation) msg = `${data.explanation}\n\n${msg}`;
    show(out, msg);
  } catch (err) {
    if (err instanceof ApiError && err.code === 'llm_unconfigured') {
      show(
        out,
        '⚠ NL queries require ANTHROPIC_API_KEY in .env — this is an extension point beyond the three deterministic demos. The framework is wired up; add a key to enable it.',
        { error: true }
      );
      return;
    }
    const rid = err.requestId ? ` (request id: ${escapeHtml(err.requestId)})` : '';
    show(out, `⚠ ${err.message}${rid}`, { error: true });
  }
}

export function initNL() {
  const input = $('#nl-input');
  const btn = $('#nl-btn');
  if (btn) btn.addEventListener('click', run);
  if (input) input.addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });
}
