"""A controller restart during a pen change loses the origin (G92), so the job must stop –
unless Nib sent the reset itself and restores the origin.

Run with:  python -m pytest tests
"""
import pytest

from conftest import wait
from grbl import Job


def waiting_for_pen_change(m):
    """A job paused at a pen change (its thread isn't started; only the state matters)."""
    job = Job(m, layers=[{"name": "A", "count": 1}, {"name": "B", "count": 1}],
              build_layer=lambda li, sp: [], header=lambda: [], footer=lambda last: [])
    job.state = "pen_change"
    return job


@pytest.fixture
def origin_set(machine):
    m, mock = machine
    m.queue_lines(["G1 X20 Y10 F6000"])
    # the simulator applies G92 to its current position, so let the move finish first
    assert wait(lambda: mock.mpos[:2] == pytest.approx([20.0, 10.0]), 5)
    m.queue_lines(["G92 X0 Y0"])
    assert wait(lambda: mock.g92[:2] == pytest.approx([20.0, 10.0]) and m.buffers_empty(), 5)
    m.zero_set = True
    return m, mock


def test_unexpected_restart_during_pen_change_aborts(origin_set):
    m, mock = origin_set
    job = waiting_for_pen_change(m)
    mock.write(b"\x18")                       # the controller restarts on its own (USB glitch)
    assert wait(lambda: job.state == "aborted", 2)
    assert "origin is lost" in job.message
    assert job._continue.is_set()             # a waiting job thread wakes up and ends
    assert m.zero_set is False


def test_own_reset_during_pen_change_keeps_the_job(origin_set):
    m, mock = origin_set
    job = waiting_for_pen_change(m)
    m.soft_reset_keep_origin(None, 1000)      # reset button: Nib restores the origin
    assert wait(lambda: mock.g92[:2] == pytest.approx([20.0, 10.0]) and m.buffers_empty(), 5)
    assert job.state == "pen_change"
    assert m.zero_set is True


def test_unexpected_restart_while_running_still_aborts(origin_set):
    m, mock = origin_set
    job = waiting_for_pen_change(m)
    job.state = "running"
    mock.write(b"\x18")
    assert wait(lambda: job.state == "aborted", 2)
    assert "unexpectedly" in job.message
