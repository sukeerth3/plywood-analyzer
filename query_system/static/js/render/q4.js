// Q4 result renderer: tainted sources to uncovered sink scopes.
import { escapeHtml } from '../util.js';

export function renderQ4(data, container) {
  const sources = data.sources || [];
  const sinks = data.sinks || [];
  const parts = [];

  parts.push('<div class="q4-flow">');
  parts.push('<div class="q4-column"><div class="q4-label">get_input sources</div>');
  if (sources.length) {
    sources.forEach((source) => {
      parts.push(`<div class="dep-node endpoint" title="${escapeHtml(source)}">${escapeHtml(source)}</div>`);
    });
  } else {
    parts.push('<div class="dep-no-path">No sources found.</div>');
  }
  parts.push('</div>');

  parts.push('<div class="dep-arrow-wrap"><div class="dep-arrow-line"></div><div class="dep-edge-type">taint reach</div></div>');

  parts.push('<div class="q4-column"><div class="q4-label">uncovered sinks</div>');
  if (!sinks.length) {
    parts.push('<div class="dep-no-path">sinks: []</div>');
  } else {
    sinks.forEach((sink) => {
      const vars = (sink.tainted_vars || []).map(escapeHtml).join(', ');
      parts.push('<div class="q4-sink">');
      parts.push(`<strong>${escapeHtml(sink.function)}</strong>`);
      parts.push(`<small>${escapeHtml(sink.uncovered_blocks)} uncovered block(s)</small>`);
      parts.push(`<div>${vars}</div>`);
      if (sink.example_path?.length) {
        parts.push('<details><summary>example path</summary>');
        parts.push(`<code>${sink.example_path.map(escapeHtml).join(' -> ')}</code>`);
        parts.push('</details>');
      }
      parts.push('</div>');
    });
  }
  parts.push('</div></div>');

  if (data.answer) {
    parts.push(`<div style="margin-top:10px;font-size:12.5px;color:var(--text-dim);padding:0 4px;line-height:1.5;">${escapeHtml(data.answer)}</div>`);
  }

  container.innerHTML = parts.join('');
}
