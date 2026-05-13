// Q1 result renderer: call-graph mini-visualisation.
import { escapeHtml } from '../util.js';

export function renderQ1(data, container) {
  const callers = data.callers || [];
  const callees = data.callees || [];
  const target = data.function || 'calculate_cuts';

  const parts = ['<div class="cg-vis">'];

  if (callers.length) {
    parts.push('<div class="cg-column">');
    callers.forEach((c) => parts.push(`<div class="cg-node caller">${escapeHtml(c)}</div>`));
    parts.push('</div>');
    parts.push('<div class="cg-edge-wrap"><div class="cg-edge-label">CALLS</div><div class="cg-arrow">&rarr;</div></div>');
  }

  parts.push(`<div class="cg-column"><div class="cg-node target">${escapeHtml(target)}</div>`);
  if (!callers.length) {
    parts.push('<div class="cg-empty" style="margin-top:4px;font-size:10px;">no callers (entry point?)</div>');
  }
  parts.push('</div>');

  if (callees.length) {
    parts.push('<div class="cg-edge-wrap"><div class="cg-edge-label">CALLS</div><div class="cg-arrow">&rarr;</div></div>');
    parts.push('<div class="cg-column">');
    callees.forEach((c) => parts.push(`<div class="cg-node callee">${escapeHtml(c)}</div>`));
    parts.push('</div>');
  } else {
    parts.push('<div class="cg-edge-wrap"><div class="cg-arrow" style="color:var(--border-hi);">&rarr;</div></div>');
    parts.push('<div class="cg-empty">leaf function<br>(no callees)</div>');
  }

  parts.push('</div>');

  if (data.answer) {
    parts.push(`<div style="margin-top:10px;font-size:12.5px;color:var(--text-dim);padding:0 4px;line-height:1.5;">${escapeHtml(data.answer)}</div>`);
  }

  container.innerHTML = parts.join('');
}
