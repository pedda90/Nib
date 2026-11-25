"""Streaming to the (simulated) controller: acknowledgements must stay in step with the lines sent.

Run with:  python -m pytest tests
"""
import pytest

from conftest import wait
from grbl import Machine


def test_long_pen_down_delay_keeps_acks_in_step(machine):
    """During G4 the controller reports 'Idle' but holds back the 'ok' until the dwell is
    over; the lines after it wait in its receive buffer. The lost-ack safety net must not
    take that for missing acknowledgements."""
    m, mock = machine
    lines = ["G1 X30 Y0 F3000",                                          # travel (0.6 s)
             "G1 Z5 F3000", "G4 P1.00"]                                  # pen down + delay
    lines += [f"G1 X{i:.3f} Y{i / 2:.3f} F6000" for i in range(1, 13)]   # more than 127 bytes
    m.queue_lines(lines)
    assert wait(lambda: m.state.startswith("Run"), 1), "travel move not seen"
    assert wait(lambda: m.buffers_empty() and mock.state == "Idle" and mock._planner.empty()
                and not mock._moving, 10), "job did not finish"
    seq = m.status_seq
    assert wait(lambda: m.status_seq >= seq + 2, 2)                     # fresh position
    assert m.lost_acks_total == 0, "acknowledgements wrongly treated as lost during the dwell"
    assert mock.rx_overflows == 0, "receive buffer of the controller overflowed"
    assert m.mpos[:2] == pytest.approx([12.0, 6.0])


@pytest.mark.parametrize("line, seconds", [
    ("G4 P1.00", 1.0), ("G04P0.5", 0.5), ("g4 p2", 2.0),
    ("G1 Z5 F3000", 0.0), ("G40", 0.0), ("G1 X14 Y4", 0.0),
])
def test_dwell_time(line, seconds):
    assert Machine._dwell_time(line) == seconds
