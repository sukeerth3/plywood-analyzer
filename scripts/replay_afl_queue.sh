#!/usr/bin/env bash
# Replay the AFL queue through the gcov-instrumented binary and import the delta.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="$PROJECT_DIR/build"
DATA_DIR="$PROJECT_DIR/data"
QUEUE_DIR="$PROJECT_DIR/fuzzing/findings/default/queue"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BIN="$BUILD_DIR/plywood_calc_cov"
BASELINE_JSON="$DATA_DIR/coverage_baseline.json"
REPLAY_JSON="$DATA_DIR/coverage_replay.json"
FUZZ_STATS_JSON="$DATA_DIR/fuzz_stats.json"

if [ ! -x "$BIN" ]; then
    echo "coverage binary not found: $BIN" >&2
    exit 1
fi
if [ ! -d "$QUEUE_DIR" ]; then
    echo "AFL queue not found: $QUEUE_DIR" >&2
    exit 1
fi

mkdir -p "$DATA_DIR"

cd "$BUILD_DIR"
find . -name '*.gcda' -delete
find . -name '*.gcov' -delete

cd "$PROJECT_DIR"
"$PYTHON_BIN" - "$PROJECT_DIR" "$BIN" "$BASELINE_JSON" <<'PY'
import json
import os
import subprocess
import sys

from analysis.coverage_collector import collect_gcov, run_all_tests
from analysis.reference_calc import assert_matches_known_good_rows

project_dir, binary, baseline_json = sys.argv[1:]
tests_dir = os.path.join(project_dir, "tests")
test_results_path = os.path.join(project_dir, "data", "test_results.json")

with open(test_results_path) as f:
    assert_matches_known_good_rows(json.load(f))

rows = run_all_tests(binary, tests_dir)
stdin_script = os.path.join(tests_dir, "stdin_tests.sh")
if os.path.isfile(stdin_script):
    subprocess.run(["bash", stdin_script, binary], check=True, timeout=30)

with open(test_results_path, "w") as f:
    json.dump(rows, f, indent=2)
    f.write("\n")

collect_gcov(project_dir, os.path.join(project_dir, "build"), baseline_json, source="gcov_curated")
PY

cd "$BUILD_DIR"
find . -name '*.gcda' -delete
find . -name '*.gcov' -delete

cd "$PROJECT_DIR"
replayed=0
timeouts=0
shopt -s nullglob
for f in "$QUEUE_DIR"/id:*; do
    set +e
    timeout 2s "$BIN" < "$f" >/dev/null 2>&1
    status=$?
    set -e
    if [ "$status" -eq 124 ]; then
        timeouts=$((timeouts + 1))
    else
        replayed=$((replayed + 1))
    fi
done

"$PYTHON_BIN" - "$PROJECT_DIR" "$REPLAY_JSON" <<'PY'
import os
import sys

from analysis.coverage_collector import collect_gcov

project_dir, replay_json = sys.argv[1:]
collect_gcov(
    project_dir,
    os.path.join(project_dir, "build"),
    replay_json,
    source="gcov_afl_replay",
)
PY

"$PYTHON_BIN" - "$BASELINE_JSON" "$REPLAY_JSON" "$FUZZ_STATS_JSON" "$replayed" <<'PY'
import json
import sys

from analysis.coverage_collector import (
    coverage_blocks_added_by_replay,
    update_fuzz_stats_replay,
)

baseline_json, replay_json, fuzz_stats_json, replayed = sys.argv[1:]
with open(baseline_json) as f:
    baseline = json.load(f)
with open(replay_json) as f:
    replay = json.load(f)

added = coverage_blocks_added_by_replay(baseline, replay)
update_fuzz_stats_replay(fuzz_stats_json, int(replayed), added)
print(f"AFL queue replayed: {replayed}")
print(f"blocks added by replay: {len(added)}")
PY

"$PYTHON_BIN" "$PROJECT_DIR/analysis/graph_importer.py" \
    --skip-neo4j \
    --coverage-baseline "$BASELINE_JSON" \
    --coverage-replay "$REPLAY_JSON" \
    --test-results "$DATA_DIR/test_results.json" \
    --fuzz-stats "$FUZZ_STATS_JSON"

echo "AFL queue timeouts: $timeouts"
