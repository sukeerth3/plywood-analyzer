#!/usr/bin/env bash
# Fast pre-demo health check. Prints PASS/FAIL per check and exits non-zero on failure.

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

FAILURES=0
FLASK_PID=""
FLASK_LOG=""

pass() {
    printf 'PASS  %s\n' "$1"
}

fail() {
    printf 'FAIL  %s\n' "$1"
    FAILURES=$((FAILURES + 1))
}

cleanup() {
    if [[ -n "${FLASK_PID:-}" ]] && kill -0 "$FLASK_PID" 2>/dev/null; then
        kill "$FLASK_PID" 2>/dev/null || true
        wait "$FLASK_PID" 2>/dev/null || true
    fi
    if [[ -n "${FLASK_LOG:-}" && -f "$FLASK_LOG" ]]; then
        rm -f "$FLASK_LOG"
    fi
}
trap cleanup EXIT

printf 'Plywood Analyzer demo smoke test\n'
printf 'Repository: %s\n\n' "$ROOT_DIR"

if python3 - <<'PY' >/tmp/plywood_neo4j_check.out 2>&1
import os
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI", "bolt://localhost:7687"),
    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "plywood2026")),
)
try:
    driver.verify_connectivity()
finally:
    driver.close()
PY
then
    pass "Neo4j reachable at bolt://localhost:7687"
else
    fail "Neo4j reachable at bolt://localhost:7687 ($(tr '\n' ' ' </tmp/plywood_neo4j_check.out | sed 's/[[:space:]]*$//'))"
fi
rm -f /tmp/plywood_neo4j_check.out

if [[ -f data/coverage.db ]]; then
    pass "data/coverage.db exists"
else
    fail "data/coverage.db exists"
fi

if python3 - <<'PY' >/tmp/plywood_sqlite_check.out 2>&1
import sqlite3

conn = sqlite3.connect("data/coverage.db")
cur = conn.cursor()
for table in ("coverage", "test_cases", "fuzz_stats"):
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    count = cur.fetchone()[0]
    print(f"{table}={count}")
    if count <= 0:
        raise SystemExit(f"{table} has zero rows")
conn.close()
PY
then
    pass "SQLite coverage/test/fuzz tables have non-zero rows ($(tr '\n' ' ' </tmp/plywood_sqlite_check.out | sed 's/[[:space:]]*$//'))"
else
    fail "SQLite coverage/test/fuzz tables have non-zero rows ($(tr '\n' ' ' </tmp/plywood_sqlite_check.out | sed 's/[[:space:]]*$//'))"
fi
rm -f /tmp/plywood_sqlite_check.out

if [[ -x build/plywood_calc ]]; then
    pass "build/plywood_calc exists and is executable"
else
    fail "build/plywood_calc exists and is executable"
fi

if [[ -x build/plywood_calc_cov ]]; then
    pass "build/plywood_calc_cov exists and is executable"
else
    fail "build/plywood_calc_cov exists and is executable"
fi

for demo in 1 2 3 4; do
    if python3 -m query_system.cli --demo "$demo" >/tmp/plywood_demo_${demo}.out 2>&1; then
        pass "CLI demo $demo exits 0"
    else
        fail "CLI demo $demo exits 0 ($(tr '\n' ' ' </tmp/plywood_demo_${demo}.out | sed 's/[[:space:]]*$//'))"
    fi
    rm -f "/tmp/plywood_demo_${demo}.out"
done

if ! command -v curl >/dev/null 2>&1; then
    fail "curl is available for /api/health check"
else
    pass "curl is available for /api/health check"
    if [[ -n "${DEMO_WEB_PORT:-}" ]]; then
        WEB_PORT="$DEMO_WEB_PORT"
    else
        WEB_PORT="$(python3 - <<'PY'
import socket

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PY
)"
    fi

    FLASK_LOG="$(mktemp /tmp/plywood_flask.XXXXXX.log)"
    WEB_HOST=127.0.0.1 WEB_PORT="$WEB_PORT" python3 -m query_system.web_app >"$FLASK_LOG" 2>&1 &
    FLASK_PID=$!

    HEALTH_OK=0
    for _ in $(seq 1 30); do
        if ! kill -0 "$FLASK_PID" 2>/dev/null; then
            break
        fi
        HTTP_CODE="$(curl -sS -o /tmp/plywood_health.out -w '%{http_code}' "http://127.0.0.1:${WEB_PORT}/api/health" 2>/tmp/plywood_health.err || true)"
        if [[ "$HTTP_CODE" == "200" ]]; then
            HEALTH_OK=1
            break
        fi
        sleep 0.25
    done

    if [[ "$HEALTH_OK" == "1" ]]; then
        pass "/api/health returns 200 on port ${WEB_PORT}"
    else
        fail "/api/health returns 200 on port ${WEB_PORT} (flask log: $(tail -5 "$FLASK_LOG" | tr '\n' ' ' | sed 's/[[:space:]]*$//'))"
    fi
    rm -f /tmp/plywood_health.out /tmp/plywood_health.err

    if ! command -v jq >/dev/null 2>&1; then
        fail "jq is available for API JSON checks"
    else
        pass "jq is available for API JSON checks"
        BASE_URL="http://127.0.0.1:${WEB_PORT}"

        api_jq_check() {
            local label="$1"
            local url="$2"
            local filter="$3"
            local out err
            out="$(mktemp /tmp/plywood_api_json.XXXXXX.out)"
            err="$(mktemp /tmp/plywood_api_json.XXXXXX.err)"
            if curl -fsS "$url" 2>"$err" | jq -e "$filter" >"$out" 2>>"$err"; then
                pass "$label"
            else
                fail "$label ($(tr '\n' ' ' <"$err" | sed 's/[[:space:]]*$//') $(tr '\n' ' ' <"$out" | sed 's/[[:space:]]*$//'))"
            fi
            rm -f "$out" "$err"
        }

        api_status_check() {
            local label="$1"
            local url="$2"
            local expected="$3"
            local code
            code="$(curl -s -o /dev/null -w '%{http_code}' "$url" || true)"
            if [[ "$code" == "$expected" ]]; then
                pass "$label"
            else
                fail "$label (expected HTTP ${expected}, got ${code})"
            fi
        }

        api_jq_check "/api/options/functions returns at least 6 functions" \
            "${BASE_URL}/api/options/functions" \
            '.functions | length >= 6'
        api_jq_check "/api/options/variables includes render_visualization defaults" \
            "${BASE_URL}/api/options/variables?function=render_visualization" \
            '.variables | index("vis_height") != null and index("grid") != null'
        api_jq_check "/api/evidence/sqlite reports expected gcov coverage" \
            "${BASE_URL}/api/evidence/sqlite" \
            '.coverage.coverage_pct >= 98 and .coverage.coverage_pct <= 100 and .coverage.uncovered_blocks == 2'
        api_jq_check "/api/evidence/coverage/uncovered reports uncovered row shape" \
            "${BASE_URL}/api/evidence/coverage/uncovered" \
            '.count == 2 and (.rows | length) == .count and (.rows[0].line_start | type) == "number"'
        api_jq_check "/api/evidence/neo4j reports graph evidence" \
            "${BASE_URL}/api/evidence/neo4j" \
            '.relationships.DEPENDS_ON >= 1 and .labels.Function >= 6'
        api_jq_check "/api/source/highlights reports uncovered lines" \
            "${BASE_URL}/api/source/highlights?kind=uncovered" \
            '(.highlights | length) == 2 and (.highlights[0].line | type) == "number"'
        api_status_check "/api/source/highlights rejects bogus kind" \
            "${BASE_URL}/api/source/highlights?kind=bogus" \
            "400"
        api_jq_check "/api/demo/1 accepts func parameter" \
            "${BASE_URL}/api/demo/1?func=main" \
            '.callees | index("get_input") != null and index("calculate_cuts") != null and index("print_result") != null and index("render_visualization") != null and index("validate_dimensions") != null'
        api_jq_check "/api/demo/2 accepts scoped variable parameters" \
            "${BASE_URL}/api/demo/2?var_a=vis_height&var_b=grid&var_a_func=render_visualization&var_b_func=render_visualization" \
            '.dependent == true and (.paths | length) > 0 and .paths[0].depth >= 1'
        api_jq_check "/api/demo/4 reports taint reach shape" \
            "${BASE_URL}/api/demo/4" \
            '.type == "taint_reach" and (.sources | length) > 0 and (.sinks | length) > 0'
    fi
fi

printf '\nSummary: '
if [[ "$FAILURES" -eq 0 ]]; then
    printf 'PASS - all demo checks passed.\n'
    exit 0
fi

printf 'FAIL - %s check(s) failed.\n' "$FAILURES"
exit 1
