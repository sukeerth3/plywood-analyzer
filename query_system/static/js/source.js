// Pipeline tab: full source evidence viewer with optional line highlights.

import { api } from './api.js';
import { $, escapeHtml } from './util.js';
import { highlightCpp } from './highlight.js';

let currentSource = null;
let currentHighlights = [];

function highlightsByLine(highlights) {
  const byLine = new Map();
  (highlights || []).forEach((h) => {
    if (!byLine.has(h.line)) byLine.set(h.line, []);
    byLine.get(h.line).push(h);
  });
  return byLine;
}

function renderSource(d, highlights = []) {
  const meta = $('#source-meta');
  const linesEl = $('#source-lines');
  if (!linesEl) return;

  if (meta) meta.textContent = `${d.lines} lines`;

  const byLine = highlightsByLine(highlights);
  const sourceLines = d.source.endsWith('\n')
    ? d.source.slice(0, -1).split('\n')
    : d.source.split('\n');

  linesEl.innerHTML = sourceLines
    .map((line, i) => {
      const lineNo = i + 1;
      const marks = byLine.get(lineNo) || [];
      const uncovered = marks.some((m) => m.kind === 'uncovered-gcov-line-block');
      const title = marks
        .map((m) => `${m.block_id} — hit_count ${m.hit_count}`)
        .join('\n');
      const badges = marks
        .map((m) =>
          `<span class="src-hit-badge ${m.hit_count === 0 ? 'src-hit-badge--zero' : ''}" title="${escapeHtml(title)}">${escapeHtml(m.hit_count)}&times;</span>`
        )
        .join('');
      return (
        `<div class="src-line ${uncovered ? 'src-line--uncovered' : ''}" data-line="${lineNo}" title="${escapeHtml(title)}">` +
          '<span class="src-gutter">' +
            `<span class="src-linenum">${lineNo}</span>` +
            `<span class="src-hit-badges">${badges}</span>` +
          '</span>' +
          `<span class="src-code">${highlightCpp(line)}</span>` +
        '</div>'
      );
    })
    .join('');
}

export async function loadSource(highlights = currentHighlights) {
  const linesEl = $('#source-lines');
  if (!linesEl) return;

  try {
    const d = await api.source();
    currentSource = d;
    renderSource(d, highlights);
  } catch (err) {
    linesEl.innerHTML =
      `<div class="src-line"><span class="src-linenum">!</span>` +
      `<span class="src-code" style="color:var(--red);">Failed to load source: ${escapeHtml(err.message)}</span></div>`;
  }
}

export function scrollToLine(line) {
  const target = $(`.src-line[data-line="${line}"]`);
  if (!target) return;
  target.scrollIntoView({ block: 'center' });
}

export async function showUncoveredHighlights({ scroll = false } = {}) {
  const data = await api.highlights('uncovered');
  currentHighlights = data.highlights || [];
  const toggle = $('#source-toggle-uncovered');
  if (toggle) toggle.checked = true;

  if (currentSource) renderSource(currentSource, currentHighlights);
  else await loadSource(currentHighlights);

  if (scroll && currentHighlights.length) {
    requestAnimationFrame(() => scrollToLine(currentHighlights[0].line));
  }
}

export function initSourceControls() {
  $('#source-toggle-uncovered')?.addEventListener('change', async (e) => {
    if (e.target.checked) {
      await showUncoveredHighlights({ scroll: true });
    } else {
      currentHighlights = [];
      if (currentSource) renderSource(currentSource, []);
    }
  });
}
