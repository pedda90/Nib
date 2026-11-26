"""Shared fixtures: a Machine connected to the built-in simulator."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import grbl  # noqa: E402
from mockgrbl import MockSerial  # noqa: E402


def wait(cond, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def machine(monkeypatch):
    """Machine connected to a real-time simulator with GRBL's 128-byte receive buffer."""
    mock = MockSerial(speedup=1.0)
    mock.rx_size = 128
    monkeypatch.setattr(grbl, "MockSerial", lambda: mock)
    m = grbl.Machine()
    m.connect(grbl.SIM_PORT)
    assert wait(lambda: m.idle_and_empty(), 5), "simulator did not settle after connecting"
    yield m, mock
    m.disconnect()


@pytest.fixture(autouse=True)
def _private_data_files(tmp_path, monkeypatch):
    """No test writes Nib's real settings, resume point or file memory."""
    import server
    monkeypatch.setattr(server, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(server, "JOBSTATE_FILE", str(tmp_path / "job_state.json"))
    monkeypatch.setattr(server, "MEMORY_FILE", str(tmp_path / "file_memory.json"))
