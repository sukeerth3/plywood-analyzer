// Populates query parameter controls from live DB-backed option endpoints.

import { api } from './api.js';
import { $, escapeHtml } from './util.js';

const DEFAULTS = {
  q1Func: 'calculate_cuts',
  q2Scope: 'render_visualization',
  q2VarA: 'vis_height',
  q2VarB: 'grid',
};

const variableCache = new Map();
let functions = [];

function setOptions(select, values, preferred) {
  if (!select) return;
  const current = select.value;
  const wanted = values.includes(preferred) ? preferred : (values.includes(current) ? current : values[0]);
  select.innerHTML = values
    .map((v) => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`)
    .join('');
  if (wanted) select.value = wanted;
}

async function variablesFor(functionName) {
  if (!functionName) return [];
  if (!variableCache.has(functionName)) {
    const data = await api.options.variables(functionName);
    variableCache.set(functionName, data.variables || []);
  }
  return variableCache.get(functionName) || [];
}

function syncQ2Mode() {
  const same = $('#q2-same-scope')?.checked !== false;
  const sameGroup = $('#q2-same-scope-controls');
  const crossGroup = $('#q2-cross-scope-controls');
  if (sameGroup) sameGroup.hidden = !same;
  if (crossGroup) crossGroup.hidden = same;
}

async function refreshQ2Variables({ preserve = true } = {}) {
  const same = $('#q2-same-scope')?.checked !== false;
  const varA = $('#q2-var-a');
  const varB = $('#q2-var-b');
  const oldA = preserve ? varA?.value : '';
  const oldB = preserve ? varB?.value : '';

  if (same) {
    const scope = $('#q2-scope')?.value || DEFAULTS.q2Scope;
    const vars = await variablesFor(scope);
    setOptions(varA, vars, oldA || DEFAULTS.q2VarA);
    setOptions(varB, vars, oldB || DEFAULTS.q2VarB);
    return;
  }

  const funcA = $('#q2-var-a-func')?.value || DEFAULTS.q2Scope;
  const funcB = $('#q2-var-b-func')?.value || DEFAULTS.q2Scope;
  setOptions(varA, await variablesFor(funcA), oldA || DEFAULTS.q2VarA);
  setOptions(varB, await variablesFor(funcB), oldB || DEFAULTS.q2VarB);
}

export async function initOptions() {
  try {
    const data = await api.options.functions();
    functions = data.functions || [];
    setOptions($('#q1-func'), functions, DEFAULTS.q1Func);
    setOptions($('#q2-scope'), functions, DEFAULTS.q2Scope);
    setOptions($('#q2-var-a-func'), functions, DEFAULTS.q2Scope);
    setOptions($('#q2-var-b-func'), functions, DEFAULTS.q2Scope);
    syncQ2Mode();
    await refreshQ2Variables({ preserve: false });
  } catch (err) {
    const msg = `Options unavailable: ${err.message}`;
    ['q1-func', 'q2-scope', 'q2-var-a', 'q2-var-b', 'q2-var-a-func', 'q2-var-b-func'].forEach((id) => {
      const el = $(`#${id}`);
      if (el) el.innerHTML = `<option value="">${escapeHtml(msg)}</option>`;
    });
  }

  $('#q2-scope')?.addEventListener('change', () => refreshQ2Variables());
  $('#q2-var-a-func')?.addEventListener('change', () => refreshQ2Variables());
  $('#q2-var-b-func')?.addEventListener('change', () => refreshQ2Variables());
  $('#q2-same-scope')?.addEventListener('change', () => {
    syncQ2Mode();
    refreshQ2Variables();
  });
}
