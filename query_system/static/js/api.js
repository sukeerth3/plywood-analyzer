// Thin fetch wrapper:
// - Throws ApiError with code/message/status/requestId on non-2xx.
// - Accepts the standard error envelope { error: { code, message, request_id } }.
// - Adds a timeout via AbortController.

export class ApiError extends Error {
  constructor({ code, message, status, requestId }) {
    super(message || code || 'request failed');
    this.code = code || 'unknown';
    this.status = status;
    this.requestId = requestId;
  }
}

async function request(method, path, { body, timeoutMs = 10000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
  } catch (e) {
    clearTimeout(timer);
    throw new ApiError({
      code: e.name === 'AbortError' ? 'timeout' : 'network_error',
      message: e.name === 'AbortError' ? `Request timed out after ${timeoutMs} ms` : e.message,
      status: 0,
    });
  }
  clearTimeout(timer);

  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch { /* non-JSON response */ }
  }

  if (!res.ok) {
    const env = data && data.error;
    throw new ApiError({
      code: (env && env.code) || `http_${res.status}`,
      message: (env && env.message) || res.statusText || 'Request failed',
      status: res.status,
      requestId: env && env.request_id,
    });
  }
  return data;
}

async function requestText(method, path, { timeoutMs = 10000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(path, { method, signal: ctrl.signal });
  } catch (e) {
    clearTimeout(timer);
    throw new ApiError({
      code: e.name === 'AbortError' ? 'timeout' : 'network_error',
      message: e.name === 'AbortError' ? `Request timed out after ${timeoutMs} ms` : e.message,
      status: 0,
    });
  }
  clearTimeout(timer);

  const text = await res.text();
  if (!res.ok) {
    throw new ApiError({
      code: `http_${res.status}`,
      message: res.statusText || 'Request failed',
      status: res.status,
    });
  }
  return text;
}

function qs(params = {}) {
  const entries = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && String(v) !== '');
  if (!entries.length) return '';
  return '?' + new URLSearchParams(entries).toString();
}

export const api = {
  health:  () => request('GET', '/api/health', { timeoutMs: 3000 }),
  stats:   () => request('GET', '/api/stats',  { timeoutMs: 5000 }),
  source:  () => request('GET', '/api/source', { timeoutMs: 5000 }),
  schema:  () => requestText('GET', '/api/schema', { timeoutMs: 5000 }),
  demo:    (n, params = {}) => request('GET', `/api/demo/${encodeURIComponent(n)}${qs(params)}`, { timeoutMs: 15000 }),
  options: {
    functions: () => request('GET', '/api/options/functions', { timeoutMs: 5000 }),
    variables: (f) => request('GET', `/api/options/variables${qs({ function: f })}`, { timeoutMs: 5000 }),
  },
  evidence: {
    neo4j: () => request('GET', '/api/evidence/neo4j', { timeoutMs: 5000 }),
    sqlite: () => request('GET', '/api/evidence/sqlite', { timeoutMs: 5000 }),
    uncovered: () => request('GET', '/api/evidence/coverage/uncovered', { timeoutMs: 5000 }),
    delta: () => request('GET', '/api/evidence/coverage/delta', { timeoutMs: 5000 }),
  },
  highlights: (kind) => request('GET', `/api/source/highlights${qs({ kind })}`, { timeoutMs: 5000 }),
  nlQuery: (q) => request('POST', '/api/query', { body: { question: q }, timeoutMs: 30000 }),
};
