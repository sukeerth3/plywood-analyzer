#!/bin/bash
# scripts/run_pipeline.sh
# Master script that runs the full analysis pipeline.
# Usage: ./scripts/run_pipeline.sh [--fuzz] [--skip-neo4j]

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="$PROJECT_DIR/build"
DATA_DIR="$PROJECT_DIR/data"
SRC="$PROJECT_DIR/src/plywood_calc.cpp"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"

find_tool() {
    local tool
    for tool in "$@"; do
        if command -v "$tool" >/dev/null 2>&1; then
            command -v "$tool"
            return 0
        fi
    done
    return 1
}

# Prefer versioned LLVM tools when they are available.
CLANG="${CLANG:-$(find_tool clang-14 clang || true)}"
CLANGXX="${CLANGXX:-$(find_tool clang++-14 clang++ || true)}"
OPT="${OPT:-$(find_tool opt-14 opt || true)}"
SCAN_BUILD="${SCAN_BUILD:-$(find_tool scan-build-14 scan-build || true)}"

RUN_FUZZ=false
SKIP_NEO4J=false

for arg in "$@"; do
    case $arg in
        --fuzz) RUN_FUZZ=true ;;
        --skip-neo4j) SKIP_NEO4J=true ;;
    esac
done

echo "============================================"
echo "  Plywood Analyzer - Full Pipeline"
echo "  COM S 5130 Final Project"
echo "============================================"
echo ""

mkdir -p "$BUILD_DIR" "$BUILD_DIR/cfg" "$DATA_DIR"

# Step 1: Compile
echo "[1/9] Compiling plywood calculator..."
if [ -n "$CLANG" ] && [ -n "$CLANGXX" ] && command -v cmake >/dev/null 2>&1 && command -v make >/dev/null 2>&1; then
    cd "$BUILD_DIR"
    cmake "$PROJECT_DIR" -DCMAKE_C_COMPILER="$CLANG" -DCMAKE_CXX_COMPILER="$CLANGXX"
    make -j"$(nproc)" plywood_calc plywood_calc_cov 2>&1 | tail -3
    echo "      Debug binary:    $BUILD_DIR/plywood_calc"
    echo "      Coverage binary: $BUILD_DIR/plywood_calc_cov"
elif [ -x "$BUILD_DIR/plywood_calc" ] && [ -x "$BUILD_DIR/plywood_calc_cov" ]; then
    echo "      Reusing existing build artifacts."
    echo "      Debug binary:    $BUILD_DIR/plywood_calc"
    echo "      Coverage binary: $BUILD_DIR/plywood_calc_cov"
else
    echo "      Error: no compiler toolchain available and no prebuilt binaries found."
    exit 1
fi
echo ""

# Step 2: Emit LLVM IR
echo "[2/9] Emitting LLVM IR..."
if [ -n "$CLANGXX" ]; then
    "$CLANGXX" -S -emit-llvm -g -O0 "$SRC" -o "$BUILD_DIR/plywood_calc.ll"
    echo "      IR: $BUILD_DIR/plywood_calc.ll"
elif [ -f "$BUILD_DIR/plywood_calc.ll" ]; then
    echo "      Reusing existing IR: $BUILD_DIR/plywood_calc.ll"
else
    echo "      Error: no clang++ available and no existing IR found."
    exit 1
fi
echo ""

# Step 3: Extract call graph
echo "[3/9] Extracting call graph..."
cd "$PROJECT_DIR"
if [ -n "$OPT" ]; then
    "$OPT" -enable-new-pm=0 -dot-callgraph "$BUILD_DIR/plywood_calc.ll" -o /dev/null 2>&1 || true
    mv -f ./*.callgraph.dot "$BUILD_DIR/" 2>/dev/null || true
fi
CALLGRAPH="$(find "$BUILD_DIR" -maxdepth 1 -name '*.callgraph.dot' -print -quit)"
if [ -n "$CALLGRAPH" ]; then
    echo "      Call graph: $CALLGRAPH"
else
    echo "      Warning: no callgraph DOT file produced."
fi
echo ""

# Step 4: Extract CFGs
echo "[4/9] Extracting control flow graphs..."
cd "$PROJECT_DIR"
if [ -n "$OPT" ]; then
    "$OPT" -enable-new-pm=0 -dot-cfg "$BUILD_DIR/plywood_calc.ll" -o /dev/null 2>&1 || true
    find . -maxdepth 1 -name '.*.dot' -exec mv -f {} "$BUILD_DIR/cfg/" \; 2>/dev/null || true
fi
CFG_COUNT=$(find "$BUILD_DIR/cfg/" -name "*.dot" 2>/dev/null | wc -l)
echo "      CFG files: $CFG_COUNT"
echo ""

# Step 5: Extract data dependencies
echo "[5/9] Extracting data dependencies..."
"$PYTHON_BIN" "$PROJECT_DIR/analysis/dep_extractor.py" \
    "$BUILD_DIR/plywood_calc.ll" \
    -o "$DATA_DIR/dependencies.json"
echo ""

# Step 6: Run Clang Static Analyzer
echo "[6/9] Running Clang Static Analyzer..."
if [ -n "$SCAN_BUILD" ] && [ -n "$CLANGXX" ]; then
    "$SCAN_BUILD" --use-analyzer="$CLANGXX" \
        "$CLANGXX" -Wall -Wextra "$SRC" -o /dev/null 2>&1 | \
        tee "$DATA_DIR/scan-build-output.txt" | tail -5
else
    echo "      Skipping static analyzer; tool unavailable."
fi
echo ""

# Step 7: Run tests + collect coverage
echo "[7/9] Running tests and collecting coverage..."

find "$BUILD_DIR" -name "*.gcda" -delete 2>/dev/null || true
find "$BUILD_DIR" -name "*.gcov" -delete 2>/dev/null || true

"$PYTHON_BIN" "$PROJECT_DIR/analysis/coverage_collector.py" \
    --binary "$BUILD_DIR/plywood_calc_cov" \
    --tests "$PROJECT_DIR/tests/" \
    --source-dir "$PROJECT_DIR" \
    --build-dir "$BUILD_DIR" \
    --output "$DATA_DIR/coverage.json"
echo ""

FUZZ_STATS_JSON="$DATA_DIR/fuzz_stats.json"
if [ "$RUN_FUZZ" = true ]; then
    echo "[8/9] Running AFL fuzzing..."
    if ! FUZZ_RUN_SECONDS="${FUZZ_RUN_SECONDS:-60}" bash "$PROJECT_DIR/fuzzing/run_afl.sh"; then
        echo "      Warning: AFL fuzzing command failed; attempting to parse any stats that were written."
    fi
    "$PYTHON_BIN" - "$PROJECT_DIR" "$FUZZ_STATS_JSON" <<'PY'
import json
import pathlib
import sys

project_dir = pathlib.Path(sys.argv[1])
output_path = pathlib.Path(sys.argv[2])
stats_file = project_dir / "fuzzing" / "findings" / "default" / "fuzzer_stats"
source = "afl"
data = {
    "source": source,
    "total_execs": 0,
    "execs_per_sec": 0.0,
    "unique_crashes": 0,
    "unique_hangs": 0,
    "paths_total": 0,
    "paths_found": 0,
    "corpus_count": 0,
    "run_time_seconds": 0.0,
}

if stats_file.exists():
    parsed = {}
    for line in stats_file.read_text().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip()
    def as_int(name):
        raw = parsed.get(name, "0").replace(",", "")
        try:
            return int(float(raw))
        except ValueError:
            return 0
    def as_float(name):
        raw = parsed.get(name, "0").replace(",", "")
        try:
            return float(raw)
        except ValueError:
            return 0.0
    def first_int(*names):
        for name in names:
            value = as_int(name)
            if value:
                return value
        return 0
    data.update({
        "total_execs": as_int("execs_done"),
        "execs_per_sec": as_float("execs_per_sec"),
        "unique_crashes": as_int("saved_crashes"),
        "unique_hangs": as_int("saved_hangs"),
        "paths_total": first_int("paths_total", "corpus_count"),
        "paths_found": first_int("paths_found", "corpus_found"),
        "corpus_count": first_int("corpus_count", "paths_total"),
        "run_time_seconds": as_float("run_time"),
    })

output_path.write_text(json.dumps([data], indent=2))
if data["total_execs"] <= 0:
    raise SystemExit("[fuzz] Error: AFL stats missing or execs_done is zero.")
print(f"[fuzz] Stats JSON: {output_path}")
PY
    echo ""
else
    echo "[8/9] Skipping AFL fuzzing (default)."
    "$PYTHON_BIN" - "$PROJECT_DIR" "$FUZZ_STATS_JSON" <<'PY'
import json
import pathlib
import sys

project_dir = pathlib.Path(sys.argv[1])
output_path = pathlib.Path(sys.argv[2])
stats_file = project_dir / "fuzzing" / "findings" / "default" / "fuzzer_stats"

def parse_afl_stats(path):
    parsed = {}
    for line in path.read_text().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip()

    def as_int(name):
        raw = parsed.get(name, "0").replace(",", "")
        try:
            return int(float(raw))
        except ValueError:
            return 0

    def as_float(name):
        raw = parsed.get(name, "0").replace(",", "")
        try:
            return float(raw)
        except ValueError:
            return 0.0

    def first_int(*names):
        for name in names:
            value = as_int(name)
            if value:
                return value
        return 0

    return {
        "source": "afl",
        "total_execs": as_int("execs_done"),
        "execs_per_sec": as_float("execs_per_sec"),
        "unique_crashes": as_int("saved_crashes"),
        "unique_hangs": as_int("saved_hangs"),
        "paths_total": first_int("paths_total", "corpus_count"),
        "paths_found": first_int("paths_found", "corpus_found"),
        "corpus_count": first_int("corpus_count", "paths_total"),
        "run_time_seconds": as_float("run_time"),
    }

data = {
    "source": "afl_skipped",
    "total_execs": 0,
    "execs_per_sec": 0.0,
    "unique_crashes": 0,
    "unique_hangs": 0,
    "paths_total": 0,
    "paths_found": 0,
    "corpus_count": 0,
    "run_time_seconds": 0.0,
}

if stats_file.exists():
    parsed = parse_afl_stats(stats_file)
    if parsed["total_execs"] > 0:
        data = parsed

output_path.write_text(json.dumps([data], indent=2))
if data["source"] == "afl":
    print(f"[fuzz] Reused AFL stats JSON: {output_path}")
else:
    print(f"[fuzz] Placeholder stats JSON: {output_path}")
PY
    echo ""
fi

# Step 9: Import into Neo4j + SQLite
if [ "$SKIP_NEO4J" = false ]; then
    echo "[9/9] Importing data into Neo4j + SQLite..."
    IMPORT_ARGS=(--clear --cfg-dir "$BUILD_DIR/cfg" --deps "$DATA_DIR/dependencies.json" --coverage "$DATA_DIR/coverage.json" --test-results "$DATA_DIR/test_results.json" --fuzz-stats "$FUZZ_STATS_JSON")
    if [ -n "$CALLGRAPH" ]; then
        IMPORT_ARGS+=(--callgraph "$CALLGRAPH")
    fi
    "$PYTHON_BIN" "$PROJECT_DIR/analysis/graph_importer.py" "${IMPORT_ARGS[@]}"
else
    echo "[9/9] Importing data into SQLite (skipping Neo4j only)."
    "$PYTHON_BIN" "$PROJECT_DIR/analysis/graph_importer.py" \
        --skip-neo4j \
        --coverage "$DATA_DIR/coverage.json" \
        --test-results "$DATA_DIR/test_results.json" \
        --fuzz-stats "$FUZZ_STATS_JSON"
fi

echo ""
echo "============================================"
echo "  Pipeline complete."
echo ""
echo "  Query system:"
echo "    CLI:  python3 -m query_system.cli --demo 1"
echo "    Web:  python3 -m query_system.web_app"
echo "============================================"
