"""Reference oracle for plywood cut-count semantics."""
from __future__ import annotations

from typing import Any

MAX_DIMENSION = 10000


def calculate_cuts_ref(board_l: int, board_w: int, cut_l: int, cut_w: int) -> int | None:
    """Return the expected best piece count, or None for rejected inputs."""
    values = (board_l, board_w, cut_l, cut_w)
    if any(v <= 0 for v in values):
        return None
    if any(v > MAX_DIMENSION for v in values):
        return None

    normal = (board_l // cut_l) * (board_w // cut_w)
    rotated = (board_l // cut_w) * (board_w // cut_l)
    return max(normal, rotated)


def known_good_mismatches(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return known-good result rows whose actual count disagrees with the oracle."""
    mismatches = []
    for row in rows:
        actual = row.get("actual")
        if actual is None or row.get("returncode") != 0:
            continue
        expected = calculate_cuts_ref(
            int(row["board_l"]),
            int(row["board_w"]),
            int(row["cut_l"]),
            int(row["cut_w"]),
        )
        if expected != actual:
            mismatches.append({
                "name": row.get("name"),
                "expected": expected,
                "actual": actual,
            })
    return mismatches


def assert_matches_known_good_rows(rows: list[dict[str, Any]]) -> None:
    """Raise if the oracle disagrees with any known-good binary result row."""
    mismatches = known_good_mismatches(rows)
    if not mismatches:
        return

    details = "; ".join(
        f"{m['name']} expected={m['expected']} actual={m['actual']}"
        for m in mismatches
    )
    raise AssertionError(f"reference oracle mismatches known-good rows: {details}")
