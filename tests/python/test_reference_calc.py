import json

import pytest

from analysis.reference_calc import (
    calculate_cuts_ref,
    known_good_mismatches,
)


@pytest.mark.parametrize(
    ("board_l", "board_w", "cut_l", "cut_w", "expected"),
    [
        (7, 7, 3, 3, 4),
        (100, 100, 100, 100, 1),
        (100, 100, 101, 101, 0),
        (48, 96, 12, 24, 16),
        (48, 96, 24, 12, 16),
        (6, 10, 4, 3, 4),
        (5, 12, 6, 5, 2),
        (100, 50, 50, 100, 1),
        (0, 10, 1, 1, None),
        (-1, 10, 1, 1, None),
        (10, 10, 0, 1, None),
        (10000, 10000, 1, 1, 100000000),
        (10001, 100, 10, 5, None),
    ],
)
def test_calculate_cuts_ref(board_l, board_w, cut_l, cut_w, expected):
    assert calculate_cuts_ref(board_l, board_w, cut_l, cut_w) == expected


def test_reference_matches_known_good_rows():
    with open("data/test_results.json") as f:
        rows = json.load(f)

    mismatches = known_good_mismatches(rows)
    assert mismatches == []
