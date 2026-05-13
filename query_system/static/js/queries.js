// Wires the query cards to the demo API and preloads their code blocks.

import { api, ApiError } from './api.js';
import { $, $$, escapeHtml } from './util.js';
import { highlightCypher, highlightSQL } from './highlight.js';
import { renderQ1 } from './render/q1.js';
import { renderQ2 } from './render/q2.js';
import { renderQ3 } from './render/q3.js';
import { renderQ4 } from './render/q4.js';
import { showUncoveredHighlights } from './source.js';

const RENDERERS = { 1: renderQ1, 2: renderQ2, 3: renderQ3, 4: renderQ4 };

function val(sel, fallback = '') {
  return ($(sel)?.value || fallback).trim();
}

function demoParams(n) {
  if (n === 1) {
    return { func: val('#q1-func', 'calculate_cuts') };
  }
  if (n === 2) {
    const sameScope = $('#q2-same-scope')?.checked !== false;
    const varA = val('#q2-var-a', 'vis_height');
    const varB = val('#q2-var-b', 'grid');
    if (sameScope) {
      const scope = val('#q2-scope', 'render_visualization');
      return { var_a: varA, var_b: varB, var_a_func: scope, var_b_func: scope };
    }
    return {
      var_a: varA,
      var_b: varB,
      var_a_func: val('#q2-var-a-func', 'render_visualization'),
      var_b_func: val('#q2-var-b-func', 'render_visualization'),
    };
  }
  return {};
}

function setCodeBlock(n, data) {
  const el = $(`#q${n}-code`);
  if (!el) return;
  if (n === 3 || n === 4) {
    let combined = '';
    if (data.cypher) combined += '-- Neo4j traversal\n' + data.cypher;
    if (data.sql)    combined += '\n\n-- SQLite coverage scope\n' + data.sql;
    el.innerHTML = highlightSQL(combined);
  } else if (data.cypher) {
    el.innerHTML = highlightCypher(data.cypher);
  }
}

function setBusy(card, resultEl, btn, timingEl) {
  card.dataset.state = 'running';
  btn.disabled = true;
  timingEl.classList.remove('visible');
  resultEl.innerHTML = '<div class="spinner-wrap"><div class="spinner" aria-hidden="true"></div><span>Executing query…</span></div>';
}

function setError(card, resultEl, err) {
  card.dataset.state = 'error';
  const hint = err.status === 503
    ? '<br><small style="color:var(--text-muted)">Is Neo4j running? <code style="font-family:var(--mono);color:var(--accent);">docker compose up -d neo4j</code></small>'
    : '';
  const rid = err.requestId ? `<br><small style="color:var(--text-muted)">request id: ${escapeHtml(err.requestId)}</small>` : '';
  resultEl.innerHTML = `<div style="color:var(--red);font-size:13px;padding:8px;line-height:1.5;">&#9888; ${escapeHtml(err.message)}${hint}${rid}</div>`;
}

function addQ3HighlightLink(resultEl) {
  const wrap = document.createElement('div');
  wrap.className = 'q3-source-link-wrap';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn btn-ghost';
  btn.textContent = 'View source highlights →';
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    $('#tab-pipeline')?.click();
    try {
      await showUncoveredHighlights({ scroll: true });
    } finally {
      btn.disabled = false;
    }
  });
  wrap.appendChild(btn);
  resultEl.appendChild(wrap);
}

async function runDemo(n) {
  const card = $(`#qcard-${n}`);
  const resultEl = $(`#result-${n}`);
  const btn = $(`#btn-${n}`);
  const timingEl = $(`#timing-${n}`);
  if (!card || !resultEl || !btn || !timingEl) return;

  setBusy(card, resultEl, btn, timingEl);
  const t0 = performance.now();

  try {
    const data = await api.demo(n, demoParams(n));
    const elapsed = Math.round(performance.now() - t0);
    timingEl.textContent = `${elapsed} ms`;
    timingEl.classList.add('visible');
    setCodeBlock(n, data);
    card.dataset.state = 'done';
    RENDERERS[n](data, resultEl);
    if (n === 3) addQ3HighlightLink(resultEl);
  } catch (err) {
    const elapsed = Math.round(performance.now() - t0);
    timingEl.textContent = `${elapsed} ms`;
    timingEl.classList.add('visible');
    setError(card, resultEl, err instanceof ApiError ? err : new ApiError({ message: err.message || 'failed' }));
  } finally {
    btn.disabled = false;
  }
}

function initQueryTabs() {
  const tabs = $$('.qtab');
  if (!tabs.length) return;

  const activate = (tab) => {
    tabs.forEach((t) => {
      const active = t === tab;
      const panel = document.getElementById(t.getAttribute('aria-controls'));
      t.classList.toggle('active', active);
      t.setAttribute('aria-selected', active ? 'true' : 'false');
      t.tabIndex = active ? 0 : -1;
      if (panel) {
        panel.classList.toggle('active', active);
        panel.hidden = !active;
      }
    });
  };

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => activate(tab));
  });
}

export function initQueries() {
  initQueryTabs();
  document.querySelectorAll('[data-action="run-demo"]').forEach((btn) => {
    btn.addEventListener('click', () => runDemo(Number(btn.dataset.demo)));
  });
}

export async function preloadQueryCode() {
  // Fire in parallel, swallow failures (code blocks degrade gracefully).
  const settled = await Promise.allSettled([api.demo(1, demoParams(1)), api.demo(2, demoParams(2)), api.demo(3), api.demo(4)]);
  settled.forEach((r, i) => {
    if (r.status === 'fulfilled') setCodeBlock(i + 1, r.value);
    else {
      const el = $(`#q${i + 1}-code`);
      if (el) el.textContent = '-- (run the query to see the generated Cypher / SQL)';
    }
  });
}
