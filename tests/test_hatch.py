"""Hatch fill geometry.

Run with:  python -m pytest tests
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import hatch as H  # noqa: E402

SQ = [(0, 0), (10, 0), (10, 10), (0, 10)]
HOLE_CW = [(3, 3), (7, 3), (7, 7), (3, 7)]          # same direction as SQ
HOLE_CCW = HOLE_CW[::-1]                           # opposite direction


def segments(lines):
    for pl in lines:
        for a, b in zip(pl, pl[1:]):
            yield a, b


def drawn_length(lines):
    return sum(math.dist(a, b) for a, b in segments(lines))


def test_square_horizontal_is_one_zigzag():
    lines = H.hatch_lines([SQ], 1.0, angle=0)
    assert len(lines) == 1                           # all rows joined
    ys = sorted({round(y, 6) for _, y in lines[0]})
    assert ys == [0.5 + i for i in range(10)]        # rows at half spacing from the edge
    xs = [x for x, _ in lines[0]]
    assert min(xs) == pytest.approx(0.5) and max(xs) == pytest.approx(9.5)   # trimmed ends


def test_without_join_one_line_per_row():
    lines = H.hatch_lines([SQ], 1.0, angle=0, join=False)
    assert len(lines) == 10
    assert all(len(pl) == 2 for pl in lines)


@pytest.mark.parametrize("angle", [0, 30, 45, 90, 135])
def test_lines_stay_inside(angle):
    for x, y in (p for pl in H.hatch_lines([SQ], 0.7, angle) for p in pl):
        assert -1e-6 <= x <= 10 + 1e-6 and -1e-6 <= y <= 10 + 1e-6


def test_coverage_matches_area():
    # area / spacing ≈ total hatch length (minus trimmed ends and connectors)
    lines = H.hatch_lines([SQ], 0.5, angle=45, join=False)
    assert drawn_length(lines) == pytest.approx(100 / 0.5, rel=0.08)


@pytest.mark.parametrize("rings, rule", [
    ([SQ, HOLE_CW], "evenodd"),
    ([SQ, HOLE_CCW], "nonzero"),
])
def test_holes_stay_empty(rings, rule):
    lines = H.hatch_lines(rings, 0.5, angle=0, rule=rule)
    for (x0, y0), (x1, y1) in segments(lines):
        if abs(y0 - y1) < 1e-9 and 3.5 < y0 < 6.5:   # rows through the hole
            lo, hi = sorted((x0, x1))
            assert not (lo < 5 < hi), "a line crosses the hole"


def test_nonzero_same_direction_fills_inner_ring():
    lines = H.hatch_lines([SQ, HOLE_CW], 0.5, angle=0, rule="nonzero", join=False)
    row = [pl for pl in lines if abs(pl[0][1] - 5.25) < 1e-6]
    assert len(row) == 1 and math.dist(*row[0]) == pytest.approx(9.5)


def test_zigzag_does_not_jump_across_a_gap():
    # two separate squares: connectors must not cross the empty space between them
    right = [(15, 0), (25, 0), (25, 10), (15, 10)]
    for (x0, y0), (x1, y1) in segments(H.hatch_lines([SQ, right], 1.0, angle=0)):
        lo, hi = sorted((x0, x1))
        assert not (lo < 12.5 < hi)


def test_angle_is_counterclockwise_on_paper():
    # y points down on paper: at 45° a line must rise to the right ("/"), i.e. y falls as x grows
    (x0, y0), (x1, y1) = H.hatch_lines([SQ], 2.0, angle=45, join=False)[0]
    assert (x1 - x0) * (y1 - y0) < 0
    (x0, y0), (x1, y1) = H.hatch_lines([SQ], 2.0, angle=90, join=False)[0]
    assert abs(x1 - x0) < 1e-9                       # vertical


def test_cross_hatch_doubles_lines():
    one = drawn_length(H.hatch_shape([SQ], 1.0, 45, cross=False))
    two = drawn_length(H.hatch_shape([SQ], 1.0, 45, cross=True))
    assert two == pytest.approx(2 * one, rel=0.05)


def test_degenerate_input():
    assert H.hatch_lines([], 1.0) == []
    assert H.hatch_lines([[(0, 0), (1, 1)]], 1.0) == []
    with pytest.raises(ValueError):
        H.hatch_lines([SQ], 0)


def test_test_strip():
    paths = H.test_strip(5, 7)
    w, h = H.test_strip_size()
    xs = [x for p in paths for x, _ in p]
    ys = [y for p in paths for _, y in p]
    assert min(xs) >= 5 - 1e-6 and max(xs) <= 5 + w + 1e-6
    assert min(ys) >= 7 - 1e-6 and max(ys) <= 7 + h + 1e-6
