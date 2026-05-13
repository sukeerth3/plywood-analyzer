// Q3 result renderer: coverage table with animated bars.
import { escapeHtml } from '../util.js';

function colorFor(pct) {
  if (pct >= 90) return { bar: 'bar-green',  text: 'var(--green)'  };
  if (pct >= 50) return { bar: 'bar-yellow', text: 'var(--yellow)' };
  return             { bar: 'bar-red',    text: 'var(--red)'    };
}

export function renderQ3(data, container) {
  const reachable = data.reachable_functions || [];
  const uncovered = data.uncovered_functions || [];
  const byName = new Map(uncovered.map((f) => [f.function, f]));

  const rows = reachable.map((fname) => {
    const info = byName.get(fname);
    const pct = info ? info.coverage_pct : 100.0;
    const { bar, text } = colorFor(pct);
    return (
      '<tr class="cov-row">' +
        `<td class="cov-fname">${escapeHtml(fname)}</td>` +
        `<td class="cov-bar-cell"><div class="cov-bar"><div class="cov-bar-fill ${bar}" style="width:${pct}%"></div></div></td>` +
        `<td class="cov-pct" style="color:${text}">${pct.toFixed(1)}%</td>` +
      '</tr>'
    );
  }).join('');

  container.innerHTML =
    '<table class="cov-table"><thead><tr>' +
      '<th>Function</th><th>Coverage</th><th>%</th>' +
    '</tr></thead><tbody>' + rows + '</tbody></table>' +
    `<div style="margin-top:8px;font-size:11.5px;color:var(--text-dim);padding:0 2px;">${reachable.length} functions reachable from main &middot; ${uncovered.length} with uncovered blocks</div>`;

  // Animate bars up from 0 on next frame.
  requestAnimationFrame(() => {
    container.querySelectorAll('.cov-bar-fill').forEach((bar) => {
      const target = bar.style.width;
      bar.style.width = '0%';
      setTimeout(() => { bar.style.width = target; }, 50);
    });
  });
}
