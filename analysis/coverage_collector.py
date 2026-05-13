"""Runs coverage tests and exports gcov/lcov data as JSON."""

import os
import subprocess
import json
import glob
import argparse
import re
import sys

from analysis.reference_calc import (
    assert_matches_known_good_rows,
    calculate_cuts_ref,
)


def run_test(binary, board_l, board_w, cut_l, cut_w):
    """Run the coverage-instrumented binary with given inputs."""
    try:
        result = subprocess.run(
            [binary, str(board_l), str(board_w), str(cut_l), str(cut_w)],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def run_all_tests(binary, test_dir):
    """Run all test input files against the binary."""
    results = []
    test_files = sorted(glob.glob(os.path.join(test_dir, "*.txt")))

    for tf in test_files:
        with open(tf) as f:
            lines = f.read().strip().split("\n")

        for line in lines:
            parts = line.strip().split()
            if len(parts) != 4:
                continue
            bl, bw, cl, cw = map(int, parts)

            rc, stdout, stderr = run_test(binary, bl, bw, cl, cw)

            # Parse actual pieces from stdout
            actual = None
            for out_line in stdout.split("\n"):
                m = re.search(r'Best:\s*(\d+)\s*pieces', out_line)
                if m:
                    actual = int(m.group(1))

            expected = calculate_cuts_ref(bl, bw, cl, cw)
            results.append({
                "name": f"{os.path.basename(tf)}:{bl}x{bw}/{cl}x{cw}",
                "source": "ai_generated" if "ai_" in tf else "manual",
                "board_l": bl, "board_w": bw,
                "cut_l": cl, "cut_w": cw,
                "expected_pieces": expected,
                "actual": actual,
                "passed": expected == actual,
                "returncode": rc
            })

    return results


def collect_gcov(source_dir, build_dir, output_path, source="gcov_curated"):
    """Run gcov and parse results into JSON format for SQLite import."""
    # Find the actual directory containing .gcno/.gcda files
    gcno_dir = None
    for root, dirs, files in os.walk(build_dir):
        for f in files:
            if f.endswith(".gcno"):
                gcno_dir = root
                break
        if gcno_dir:
            break

    if not gcno_dir:
        gcno_dir = build_dir

    # Use llvm-cov gcov for clang-compiled binaries; fall back to gcov
    gcov_tool = None
    for candidate in ["llvm-cov-14", "llvm-cov"]:
        try:
            subprocess.run([candidate, "--version"], capture_output=True)
            gcov_tool = candidate
            break
        except FileNotFoundError:
            continue
    if gcov_tool is None:
        try:
            subprocess.run(["gcov", "--version"], capture_output=True)
            gcov_tool = "gcov"
        except FileNotFoundError:
            gcov_tool = None

    if gcov_tool and gcov_tool.startswith("llvm-cov"):
        gcov_cmd = [gcov_tool, "gcov", "-b", "-c"]
    elif gcov_tool:
        gcov_cmd = [gcov_tool, "-b", "-c"]
    else:
        gcov_cmd = None

    # Run gcov from the gcno directory so it can find the .gcno alongside .gcda
    if gcov_cmd:
        gcda_files = glob.glob(os.path.join(gcno_dir, "*.gcda"))
        if gcda_files:
            # Pass basenames only — llvm-cov gcov expects to find .gcno in cwd
            basenames = [os.path.basename(f) for f in gcda_files]
            subprocess.run(gcov_cmd + basenames, capture_output=True, cwd=gcno_dir)
        else:
            gcov_cmd_fallback = gcov_cmd + ["-o", gcno_dir, "src/plywood_calc.cpp"]
            subprocess.run(gcov_cmd_fallback, capture_output=True, cwd=source_dir)

    # Parse .gcov file — check multiple possible locations
    gcov_file = None
    for search_dir in [gcno_dir, source_dir, "."]:
        candidate = os.path.join(search_dir, "plywood_calc.cpp.gcov")
        if os.path.exists(candidate):
            gcov_file = candidate
            break
    if not gcov_file:
        for search_dir in [gcno_dir, source_dir, "."]:
            gcov_files = glob.glob(os.path.join(search_dir, "*.gcov"))
            if gcov_files:
                gcov_file = gcov_files[0]
                break
    if not gcov_file:
        if os.path.exists(output_path):
            with open(output_path) as f:
                coverage_data = json.load(f)
            print(f"[gcov] Reusing existing coverage JSON: {output_path}")
            return coverage_data
        print("[gcov] No .gcov files found.")
        return []

    coverage_data = _parse_gcov(gcov_file, source=source)

    with open(output_path, "w") as f:
        json.dump(coverage_data, f, indent=2)

    total = len(coverage_data)
    covered = sum(1 for c in coverage_data if c["hit_count"] > 0)
    print(f"[gcov] {covered}/{total} blocks covered ({100*covered/total:.1f}%)")

    return coverage_data


def _parse_gcov(gcov_path, source="gcov_curated"):
    """Parse a .gcov file into structured coverage data."""
    return _parse_gcov_with_source(gcov_path, source_tag=source)


def _parse_gcov_with_source(gcov_path, source_tag):
    """Parse a .gcov file into structured coverage data."""
    records = []
    current_func = "unknown"
    block_counter = 0

    # First pass: build a map of line_number -> function name
    # by detecting function signatures in the source column
    func_line_map = {}
    with open(gcov_path) as f:
        for line in f:
            line = line.rstrip("\n")

            # Function line from gcov -f: function <name> called ...
            func_match = re.match(r'function\s+(\S+)\s+called', line)
            if func_match:
                # Some gcov versions do emit these — use them
                current_func = func_match.group(1)
                block_counter = 0
                continue

            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            line_num_str = parts[1].strip()
            source_text = parts[2] if len(parts) > 2 else ""
            if not line_num_str.isdigit():
                continue
            line_num = int(line_num_str)

            # Detect C/C++ function definitions in source column
            src_stripped = source_text.strip()
            # Skip comment lines
            if src_stripped.startswith("//") or src_stripped.startswith("/*"):
                continue
            func_def = re.match(
                r'.*?\b(\w+)\s*\([^)]*\)\s*\{?\s*$', src_stripped
            )
            if func_def:
                name = func_def.group(1)
                # Filter out keywords that look like function names
                if name not in ("if", "while", "for", "switch", "return",
                                "else", "struct", "class", "sizeof",
                                "printf", "fprintf", "scanf", "memset",
                                "malloc", "free", "atoi"):
                    func_line_map[line_num] = name

    # Second pass: assign functions to executable lines
    current_func = "unknown"
    block_counter = 0

    with open(gcov_path) as f:
        for line in f:
            line = line.rstrip("\n")

            # Function line from gcov -f
            func_match = re.match(r'function\s+(\S+)\s+called', line)
            if func_match:
                current_func = func_match.group(1)
                block_counter = 0
                continue

            parts = line.split(":", 2)
            if len(parts) < 3:
                continue

            count_str = parts[0].strip()
            line_num_str = parts[1].strip()

            if not line_num_str.isdigit():
                continue

            line_num = int(line_num_str)

            # Update current function if this line starts a new function
            if line_num in func_line_map:
                current_func = func_line_map[line_num]
                block_counter = 0

            if count_str == "-":
                continue  # Non-executable line
            elif count_str == "#####" or count_str == "=====":
                hit_count = 0
            else:
                try:
                    hit_count = int(count_str)
                except ValueError:
                    continue

            block_id = f"{current_func}::bb{block_counter}"
            block_counter += 1

            records.append({
                "function": current_func,
                "block_id": block_id,
                "line_start": line_num,
                "line_end": line_num,
                "hit_count": hit_count,
                "source": source_tag
            })

    return records


def coverage_blocks_added_by_replay(baseline_records, replay_records):
    """Return replay-covered blocks that were not covered in the baseline."""
    baseline_hits = {
        record["block_id"]: record.get("hit_count", 0)
        for record in baseline_records
    }
    added = []
    for record in replay_records:
        if record.get("hit_count", 0) <= 0:
            continue
        if baseline_hits.get(record["block_id"], 0) > 0:
            continue
        added.append({
            "function": record["function"],
            "block_id": record["block_id"],
            "line_start": record.get("line_start"),
            "line_end": record.get("line_end"),
        })
    return added


def update_fuzz_stats_replay(stats_path, replay_count, blocks_added):
    """Persist AFL replay contribution fields into data/fuzz_stats.json."""
    if os.path.exists(stats_path):
        with open(stats_path) as f:
            stats = json.load(f)
    else:
        stats = []

    if isinstance(stats, dict):
        stats = [stats]
    if not stats:
        stats = [{"source": "afl"}]

    target = None
    for entry in stats:
        if entry.get("source") == "afl":
            target = entry
            break
    if target is None:
        target = stats[0]

    target["afl_replay_count"] = replay_count
    target["afl_replay_blocks_added"] = len(blocks_added)

    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)
        f.write("\n")

    return stats


def collect_lcov(build_dir, output_dir):
    """Run lcov to generate HTML coverage report."""
    try:
        subprocess.run(["lcov", "--version"], capture_output=True, check=False)
        subprocess.run(["genhtml", "--version"], capture_output=True, check=False)
    except FileNotFoundError:
        print("[lcov] Skipping HTML report; lcov/genhtml unavailable.")
        return

    lcov_cmd = [
        "lcov", "--capture",
        "--directory", build_dir,
        "--output-file", os.path.join(output_dir, "coverage.info")
    ]
    subprocess.run(lcov_cmd, capture_output=True)

    genhtml_cmd = [
        "genhtml", os.path.join(output_dir, "coverage.info"),
        "--output-directory", os.path.join(output_dir, "html")
    ]
    subprocess.run(genhtml_cmd, capture_output=True)
    print(f"[lcov] HTML report -> {output_dir}/html/index.html")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect coverage data")
    parser.add_argument("--binary", default="build/plywood_calc_cov",
                        help="Path to coverage-instrumented binary")
    parser.add_argument("--tests", default="tests/",
                        help="Directory with test input files")
    parser.add_argument("--source-dir", default=".",
                        help="Project root directory")
    parser.add_argument("--build-dir", default="build/",
                        help="Build directory with .gcda/.gcno files")
    parser.add_argument("--output", default="data/coverage.json",
                        help="Output JSON path")
    parser.add_argument("--coverage-source", default="gcov_curated",
                        help="Source tag for collected gcov rows")
    args = parser.parse_args()

    os.makedirs("data", exist_ok=True)

    existing_results_path = os.path.join("data", "test_results.json")
    if os.path.exists(existing_results_path):
        with open(existing_results_path) as f:
            assert_matches_known_good_rows(json.load(f))
        print("Reference oracle matches existing known-good rows.")

    print("Running tests...")
    test_results = run_all_tests(args.binary, args.tests)
    print(f"Ran {len(test_results)} test cases.")

    # Run stdin-based tests if the script exists (covers get_input())
    stdin_script = os.path.join(args.tests, "stdin_tests.sh")
    if os.path.isfile(stdin_script):
        print("Running stdin tests...")
        result = subprocess.run(
            ["bash", stdin_script, args.binary],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="")
            sys.exit(result.returncode)

    # Save test results
    with open("data/test_results.json", "w") as f:
        json.dump(test_results, f, indent=2)

    print("Collecting coverage...")
    collect_gcov(args.source_dir, args.build_dir, args.output, source=args.coverage_source)
    collect_lcov(args.build_dir, "data")
