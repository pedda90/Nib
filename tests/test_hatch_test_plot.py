"""The hatch test strip is plotted where the preview shows it.

Run with:  python -m pytest tests
"""
import copy

import pytest

import server as S
from conftest import wait


@pytest.fixture
def mset():
    m = copy.deepcopy(S.DEFAULTS["machine"])
    m["feed_draw"] = m["feed_travel"] = 60000      # quick in the real-time simulator
    return m


def test_strip_is_plotted_at_the_given_position(machine, mset):
    m, mock = machine
    r = S.hatch_test({"x": 50, "y": 60, "angle": 45, "mode": "hatch", "join": True}, mset, m)
    assert r.get("ok"), r
    seen = []
    assert wait(lambda: seen.append(tuple(round(v, 1) for v in mock.mpos[:2])) or
                (m.buffers_empty() and mock.state == "Idle" and mock._planner.empty() and not mock._moving
                 and len(seen) > 20), 60)
    w, h = S.H.test_strip_size()
    first = next(i for i, (x, y) in enumerate(seen) if abs(x - 50) < 0.2 and abs(y - 60) < 0.2)
    xs = [p[0] for p in seen[first:]]                 # from the strip's corner on (not the way there)
    ys = [p[1] for p in seen[first:]]
    assert min(xs) >= 50 - 0.01 and max(xs) <= 50 + w + 0.01
    assert max(ys) <= 60 + h + 0.01
    assert mock.mpos[:2] == pytest.approx([50, 60])   # back at the strip's corner


def test_strip_outside_the_work_area_is_refused(machine, mset):
    m, _ = machine
    r = S.hatch_test({"x": mset["max_x"] - 20, "y": 10}, mset, m)
    assert "doesn't fit" in r.get("error", "")
