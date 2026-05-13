// Q2 result renderer: dependency path between two variables.
import { escapeHtml } from '../util.js';

export function renderQ2(data, container) {
  const paths = data.paths || [];
  const parts = [];

  if (!data.dependent || !paths.length) {
    parts.push(
      '<div class="dep-no-path">No dependency path found between ' +
        `<strong>${escapeHtml(data.var_a)}</strong> and <strong>${escapeHtml(data.var_b)}</strong>.<br>` +
        '<small style="color:var(--text-muted)">These variables may be in different functions or have no data-flow relationship.</small></div>'
    );
  } else {
    const p = paths[0];
    const nodes = p.nodes || [];

    parts.push('<div class="dep-chain">');
    nodes.forEach((node, i) => {
      const endpoint = i === 0 || i === nodes.length - 1;
      parts.push(
        `<div class="dep-node ${endpoint ? 'endpoint' : 'intermediate'}" title="${escapeHtml(node)}">${escapeHtml(node)}</div>`
      );
      if (i < nodes.length - 1) {
        parts.push('<div class="dep-arrow-wrap"><div class="dep-arrow-line"></div><div class="dep-edge-type">data_flow</div></div>');
      }
    });
    parts.push('</div>');

    parts.push(
      `<div style="margin-top:8px;font-size:12px;color:var(--text-dim);padding:0 4px;">Shortest path: depth ${p.depth} &middot; ${paths.length} path(s) found` +
        (paths.length > 1 ? ' <span style="color:var(--text-muted)">(showing shortest)</span>' : '') +
        '</div>'
    );
  }

  if (data.answer) {
    parts.push(`<div style="margin-top:8px;font-size:12.5px;color:var(--text-dim);padding:0 4px;line-height:1.5;">${escapeHtml(data.answer)}</div>`);
  }

  container.innerHTML = parts.join('');
}
