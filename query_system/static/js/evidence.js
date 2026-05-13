// Storage tab evidence renderer.

import { api } from './api.js';
import { $, $$, escapeHtml } from './util.js';
import { showUncoveredHighlights, scrollToLine } from './source.js';

function pathValue(obj, path) {
  return path.split('.').reduce((acc, part) => (acc == null ? undefined : acc[part]), obj);
}

function setNeo4jUnavailable() {
  $$('[data-evidence-neo4j]').forEach((el) => { el.textContent = '—'; });
  paintEdgeRows('#evidence-calls', []);
  paintEdgeRows('#evidence-depends', []);
}

function paintEdgeRows(selector, rows) {
  const body = $(selector);
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="2">—</td></tr>';
    return;
  }
  body.innerHTML = rows
    .map(([a, b]) => `<tr><td>${escapeHtml(a)}</td><td>${escapeHtml(b)}</td></tr>`)
    .join('');
}

async function loadNeo4jEvidence() {
  try {
    const data = await api.evidence.neo4j();
    $$('[data-evidence-neo4j]').forEach((el) => {
      const value = pathValue(data, el.dataset.evidenceNeo4j);
      el.textContent = value ?? '—';
    });
    paintEdgeRows('#evidence-calls', data.samples?.calls || []);
    paintEdgeRows('#evidence-depends', data.samples?.depends_on || []);
  } catch {
    setNeo4jUnavailable();
  }
}

function paintAfl(fuzzRows) {
  const row = (fuzzRows || [])[0] || {};
  $('#afl-execs') && ($('#afl-execs').textContent = row.total_execs?.toLocaleString() ?? '—');
  $('#afl-rate') && ($('#afl-rate').textContent = row.execs_per_sec == null ? '—' : Number(row.execs_per_sec).toLocaleString());
  $('#afl-paths') && ($('#afl-paths').textContent = row.paths_total?.toLocaleString() ?? '—');
  $('#afl-crashes') && ($('#afl-crashes').textContent = row.unique_crashes?.toLocaleString() ?? '—');
}

function measuredDeltaText(data) {
  const baseline = data.baseline || {};
  const replay = data.replay || {};
  const replayed = Number(data.afl_queue_inputs_replayed || 0);
  const added = data.blocks_added_by_replay || [];
  return (
    `Of the ${Number(baseline.total_blocks || 0).toLocaleString()} line-blocks instrumented by gcov, ` +
    `${Number(baseline.hit_blocks || 0).toLocaleString()} are exercised by the 29 curated tests; ` +
    `replaying ${replayed.toLocaleString()} AFL queue inputs through the same coverage binary covers ` +
    `${Number(replay.hit_blocks || 0).toLocaleString()} blocks, contributing ` +
    `${added.length.toLocaleString()} previously-uncovered blocks.`
  );
}

function paintCoverageDelta(data) {
  const baseline = data.baseline || {};
  const replay = data.replay || {};
  const added = data.blocks_added_by_replay || [];
  $('#delta-baseline') && ($('#delta-baseline').textContent = `${baseline.hit_blocks ?? '—'}/${baseline.total_blocks ?? '—'}`);
  $('#delta-baseline-pct') && ($('#delta-baseline-pct').textContent = baseline.pct == null ? '—' : `${Number(baseline.pct).toFixed(1)}%`);
  $('#delta-replay') && ($('#delta-replay').textContent = `${replay.hit_blocks ?? '—'}/${replay.total_blocks ?? '—'}`);
  $('#delta-replay-pct') && ($('#delta-replay-pct').textContent = replay.pct == null ? '—' : `${Number(replay.pct).toFixed(1)}%`);
  $('#delta-replayed') && ($('#delta-replayed').textContent = Number(data.afl_queue_inputs_replayed || 0).toLocaleString());
  $('#delta-added') && ($('#delta-added').textContent = added.length.toLocaleString());

  const summary = measuredDeltaText(data);
  $('#coverage-delta-summary') && ($('#coverage-delta-summary').textContent = summary);
  $('#afl-replay-framing') && ($('#afl-replay-framing').textContent = summary);

  const list = $('#coverage-delta-blocks');
  if (!list) return;
  if (!added.length) {
    list.innerHTML = '<li>No previously-uncovered blocks were added by AFL replay.</li>';
    return;
  }
  list.innerHTML = added
    .map((row) => `<li>${escapeHtml(row.function)} · ${escapeHtml(row.block_id)} · line ${escapeHtml(row.line_start)}</li>`)
    .join('');
}

async function loadCoverageDelta() {
  try {
    paintCoverageDelta(await api.evidence.delta());
  } catch {
    const empty = {
      baseline: {},
      replay: {},
      blocks_added_by_replay: [],
      afl_queue_inputs_replayed: 0,
    };
    paintCoverageDelta(empty);
  }
}

async function loadSqliteEvidence() {
  try {
    const data = await api.evidence.sqlite();
    paintAfl(data.fuzz || []);
  } catch {
    paintAfl([]);
  }
}

async function jumpToUncoveredLine(line) {
  $('#tab-pipeline')?.click();
  await showUncoveredHighlights({ scroll: false });
  requestAnimationFrame(() => scrollToLine(line));
}

async function loadUncoveredRows() {
  const body = $('#evidence-uncovered');
  if (!body) return;

  try {
    const data = await api.evidence.uncovered();
    const rows = data.rows || [];
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="3">—</td></tr>';
      return;
    }
    body.innerHTML = rows
      .map((row) => (
        `<tr class="evidence-link-row" data-line="${escapeHtml(row.line_start)}">` +
          `<td>${escapeHtml(row.function)}</td>` +
          `<td>${escapeHtml(row.block_id)}</td>` +
          `<td>${escapeHtml(row.line_start)}</td>` +
        '</tr>'
      ))
      .join('');
    body.querySelectorAll('[data-line]').forEach((row) => {
      row.addEventListener('click', () => jumpToUncoveredLine(Number(row.dataset.line)));
    });
  } catch {
    body.innerHTML = '<tr><td colspan="3">—</td></tr>';
  }
}

export function loadEvidence() {
  loadNeo4jEvidence();
  loadSqliteEvidence();
  loadUncoveredRows();
  loadCoverageDelta();
}

export function initEvidence() {
  window.addEventListener('tab:change', (e) => {
    if (e.detail?.name === 'storage') loadEvidence();
  });
  loadEvidence();
}
