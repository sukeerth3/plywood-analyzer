// Tiny syntax highlighters for Cypher, SQL, C++.
// Input must already be HTML-escaped — these return HTML strings.

import { escapeHtml } from './util.js';

const CYPHER_KW = /\b(MATCH|RETURN|WHERE|WITH|OPTIONAL|CALL|CREATE|MERGE|DELETE|SET|REMOVE|ORDER|BY|LIMIT|SKIP|DISTINCT|AS|AND|OR|NOT|IN|STARTS|ENDS|CONTAINS|IS|NULL|EXISTS|COLLECT|COUNT|SUM|AVG|MIN|MAX|length|nodes|shortestPath|allShortestPaths)\b/g;
const CYPHER_LABEL = /(:(?:Function|BasicBlock|Variable|CALLS|DEPENDS_ON|SUCCESSOR|ENTRY_BLOCK))\b/g;

export function highlightCypher(code) {
  let s = escapeHtml(code);
  s = s.replace(CYPHER_KW, '<span class="kw">$1</span>');
  s = s.replace(CYPHER_LABEL, '<span class="label">$1</span>');
  s = s.replace(/(&#39;[^&]*?&#39;|&quot;[^&]*?&quot;)/g, '<span class="str">$1</span>');
  s = s.replace(/(\$\w+)/g, '<span class="param">$1</span>');
  s = s.replace(/(\/\/.*|--.*)/g, '<span class="comment">$1</span>');
  return s;
}

const SQL_KW = /\b(SELECT|FROM|WHERE|GROUP|BY|ORDER|HAVING|LIMIT|OFFSET|AND|OR|NOT|IN|JOIN|ON|LEFT|COUNT|SUM|AVG|MIN|MAX|AS|DISTINCT|CASE|WHEN|THEN|ELSE|END|INTEGER|TEXT|REAL)\b/gi;

export function highlightSQL(code) {
  let s = escapeHtml(code);
  s = s.replace(SQL_KW, (m) => `<span class="kw">${m}</span>`);
  s = s.replace(/(&#39;.*?&#39;)/g, '<span class="str">$1</span>');
  s = s.replace(/(--.*)/g, '<span class="comment">$1</span>');
  s = s.replace(/(\?|:\w+)/g, '<span class="param">$1</span>');
  return s;
}

const CPP_KW = /\b(int|char|double|float|void|bool|struct|class|if|else|while|for|do|return|const|static|inline|NULL|nullptr|true|false|new|delete|printf|fprintf|malloc|free|memset|memcpy|std|size_t)\b/g;

export function highlightCpp(code) {
  let s = escapeHtml(code);
  // Stash comments / strings / char-literals before keyword & preproc passes —
  // otherwise the word "class" inside `<span class="comment">…</span>` gets
  // re-matched by CPP_KW, and `#39` from a `&#39;` char-literal gets matched
  // by the preproc regex, both producing broken nested markup.
  const stash = [];
  const stashIt = (html) => {
    const tok = `\x00${stash.length}\x00`;
    stash.push(html);
    return tok;
  };
  s = s.replace(/\/\/[^\n]*/g, (m) => stashIt(`<span class="comment">${m}</span>`));
  s = s.replace(/&quot;(?:[^&\\]|\\.)*?&quot;/g, (m) => stashIt(`<span class="str">${m}</span>`));
  s = s.replace(/&#39;[^&]*?&#39;/g, (m) => stashIt(`<span class="str">${m}</span>`));
  s = s.replace(/#\w+/g, '<span class="preproc">$&</span>');
  s = s.replace(CPP_KW, '<span class="kw">$1</span>');
  s = s.replace(/\b(\d+(?:\.\d+)?)\b/g, '<span class="num">$1</span>');
  s = s.replace(/\x00(\d+)\x00/g, (_, i) => stash[i]);
  return s;
}
