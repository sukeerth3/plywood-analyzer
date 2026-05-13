#!/bin/bash
# tests/stdin_tests.sh
# Exercises the interactive (stdin) code path of plywood_calc_cov.
# Called by coverage_collector.py to cover get_input().

BINARY="${1:-build/plywood_calc_cov}"

# Valid input — exercises the happy path through get_input()
printf '100\n50\n10\n5\n' | "$BINARY" > /dev/null 2>&1
printf '48\n96\n12\n24\n' | "$BINARY" > /dev/null 2>&1
printf '7\n7\n3\n3\n'    | "$BINARY" > /dev/null 2>&1

# Zero/negative — triggers validate_dimensions error inside get_input()
printf '0\n0\n0\n0\n'    | "$BINARY" > /dev/null 2>&1 || true
printf -- '-1\n5\n5\n5\n' | "$BINARY" > /dev/null 2>&1 || true

# Non-numeric — triggers scanf failure branches
printf 'abc\n'            | "$BINARY" > /dev/null 2>&1 || true
printf '100\nxyz\n'       | "$BINARY" > /dev/null 2>&1 || true
printf '100\n50\n!!!\n'   | "$BINARY" > /dev/null 2>&1 || true
printf '100\n50\n10\n@\n' | "$BINARY" > /dev/null 2>&1 || true

# Overflow via stdin
printf '10001\n100\n10\n5\n' | "$BINARY" > /dev/null 2>&1 || true
