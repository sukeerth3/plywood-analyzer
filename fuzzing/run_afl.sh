#!/bin/bash
# fuzzing/run_afl.sh
# Sets up and runs AFL++ fuzzing on the plywood calculator.
# Prerequisite: AFL++ installed (handled by Docker image).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SRC="$PROJECT_DIR/src/plywood_calc.cpp"
FUZZ_DIR="$PROJECT_DIR/fuzzing"
BUILD_DIR="$FUZZ_DIR/afl_build"
INPUT_DIR="$FUZZ_DIR/seed_corpus"
OUTPUT_DIR="$FUZZ_DIR/findings"
AFL_BIN="${AFL_BIN:-$(command -v afl-fuzz || true)}"
AFL_CXX="${AFL_CXX:-$(command -v afl-clang-fast++ || true)}"
FUZZ_RUN_SECONDS="${FUZZ_RUN_SECONDS:-${AFL_RUN_SECONDS:-60}}"

mkdir -p "$BUILD_DIR" "$INPUT_DIR" "$OUTPUT_DIR"

if [ -z "$AFL_BIN" ] || [ -z "$AFL_CXX" ]; then
    echo "[afl] Error: afl-fuzz and afl-clang-fast++ must be installed and on PATH." >&2
    exit 1
fi

# ── Step 1: Compile with AFL instrumentation ──
echo "[afl] Compiling with afl-clang-fast++..."
"$AFL_CXX" -Wall -Wextra -g -O1 "$SRC" -o "$BUILD_DIR/plywood_calc_afl"
echo "[afl] Binary: $BUILD_DIR/plywood_calc_afl"

# ── Step 2: Prepare seed corpus from test files ──
echo "[afl] Preparing seed corpus..."

# Convert test input files to stdin format (one per file)
rm -f "$INPUT_DIR"/seed_*.txt
idx=0
for testfile in "$PROJECT_DIR"/tests/*.txt; do
    while IFS= read -r line; do
        # Each line has: board_l board_w cut_l cut_w
        # Convert to newline-separated stdin input
        bl=$(echo "$line" | awk '{print $1}')
        bw=$(echo "$line" | awk '{print $2}')
        cl=$(echo "$line" | awk '{print $3}')
        cw=$(echo "$line" | awk '{print $4}')

        if [ -n "$bl" ] && [ -n "$bw" ] && [ -n "$cl" ] && [ -n "$cw" ]; then
            printf '%s\n%s\n%s\n%s\n' "$bl" "$bw" "$cl" "$cw" > "$INPUT_DIR/seed_${idx}.txt"
            idx=$((idx + 1))
        fi
    done < "$testfile"
done

echo "[afl] Created $idx seed inputs."

# ── Step 3: Run AFL++ ──
echo "[afl] Starting fuzzer..."
echo "[afl] Output: $OUTPUT_DIR"
echo "[afl] Duration: ${FUZZ_RUN_SECONDS}s"

if [ -r /proc/sys/kernel/core_pattern ]; then
    core_pattern="$(cat /proc/sys/kernel/core_pattern)"
    if [ "$core_pattern" != "core" ]; then
        if [ -w /proc/sys/kernel/core_pattern ]; then
            echo core > /proc/sys/kernel/core_pattern
            echo "[afl] Set /proc/sys/kernel/core_pattern to core."
        elif command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
            sudo -n bash -c "echo core > /proc/sys/kernel/core_pattern"
            echo "[afl] Set /proc/sys/kernel/core_pattern to core with sudo."
        else
            export AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES="${AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES:-1}"
            echo "[afl] core_pattern is '$core_pattern'; using AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES=1."
        fi
    fi
fi

export AFL_SKIP_CPUFREQ="${AFL_SKIP_CPUFREQ:-1}"
export AFL_NO_UI="${AFL_NO_UI:-1}"

# Keep each pipeline run's metrics fresh and avoid AFL++ refusing an existing
# findings/default directory from a previous run.
rm -rf "$OUTPUT_DIR/default"

# Note: the binary reads from stdin in interactive mode (no argc==5)
set +e
unset AFL_RUN_SECONDS
timeout "${FUZZ_RUN_SECONDS}s" "$AFL_BIN" \
    -i "$INPUT_DIR" \
    -o "$OUTPUT_DIR" \
    -t 5000 \
    -- "$BUILD_DIR/plywood_calc_afl"
status=$?
set -e

if [ "$status" -eq 124 ]; then
    echo "[afl] Fuzzing stopped after ${FUZZ_RUN_SECONDS}s timeout."
    exit 0
fi

exit "$status"
