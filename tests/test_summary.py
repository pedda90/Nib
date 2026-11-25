"""Summary at the end of a plot: line length per pen and in total, times, estimate.

Run with:  python -m pytest tests
"""
import pytest

import grbl
import server as S
from conftest import wait
from mockgrbl import MockSerial

SVG = b'''<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">
<path d="M10 10 L60 10" stroke="#ff0000" fill="none"/>
<path d="M10 20 L60 20 L60 40" stroke="#ff0000" fill="none"/>
<path d="M10 50 L90 50" stroke="#0000ff" fill="none"/>
</svg>'''


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(S, "JOBSTATE_FILE", str(tmp_path / "job_state.json"))
    sent = []
    monkeypatch.setattr(S, "notify", lambda title, text: sent.append((title, text)))
    monkeypatch.setattr(grbl, "MockSerial", lambda: MockSerial(speedup=200.0))
    a = S.App()
    a.settings["optimize"]["group"] = "color"
    a.settings["job"]["pen_change"] = False
    a.upload("lines.svg", SVG)
    a.machine.connect(grbl.SIM_PORT)
    assert wait(lambda: a.machine.idle_and_empty(), 5)
    yield a, sent
    a.machine.disconnect()


def run(a, place, estimate=123.0):
    ids = [l["id"] for l in a.doc["layers"]]
    r = a.start_job({"layers": ids, "place": place, "estimate": estimate})
    assert r.get("ok") is not False and "error" not in r, r
    assert wait(lambda: getattr(a.job, "summary", None) is not None, 30), a.job.state
    return a.job.summary


def test_summary_of_a_finished_plot(app):
    a, sent = app
    sm = run(a, {"x": 10, "y": 10, "scale": 2.0, "rotate": 0})
    assert sm["state"] == "done" and sm["file"] == "lines.svg"
    red, blue = sm["pens"]
    assert red["color"] == "#ff0000" and red["paths"] == 2
    assert red["draw_m"] == pytest.approx((50 + 70) * 2 / 1000)      # scale 2
    assert blue["draw_m"] == pytest.approx(80 * 2 / 1000)
    assert sm["draw_m"] == pytest.approx(0.4)
    assert sm["estimate"] == 123.0 and sm["plot_secs"] > 0 and sm["wall_secs"] >= sm["plot_secs"]
    assert red["secs"] is None                  # no pen change pause -> no time per pen
    assert sent and sent[-1][0] == "Nib – plot complete" and "0.4 m" in sent[-1][1]
    assert a.job_info()["summary"] == sm


def test_no_notification_when_switched_off(app):
    a, sent = app
    a.settings["job"]["notify"] = False
    run(a, {"x": 10, "y": 10, "scale": 1.0, "rotate": 0})
    assert sent == []


def test_times_per_pen_and_pen_change_notification(app):
    a, sent = app
    a.settings["job"]["pen_change"] = True
    ids = [l["id"] for l in a.doc["layers"]]
    a.start_job({"layers": ids, "place": {"x": 10, "y": 10, "scale": 1.0, "rotate": 0}})
    assert wait(lambda: a.job.state == "pen_change", 30)
    assert wait(lambda: any(t == "Nib – change pen" for t, _ in sent), 5)
    a.job.resume()
    assert wait(lambda: getattr(a.job, "summary", None) is not None, 30)
    sm = a.job.summary
    assert [p["secs"] is not None for p in sm["pens"]] == [True, True]
    assert sm["wall_secs"] >= sm["plot_secs"]


def test_summary_of_a_stopped_plot_counts_only_what_was_drawn(app):
    a, _ = app
    a.settings["job"]["pen_change"] = True
    ids = [l["id"] for l in a.doc["layers"]]
    a.start_job({"layers": ids, "place": {"x": 10, "y": 10, "scale": 1.0, "rotate": 0}})
    assert wait(lambda: a.job.state == "pen_change", 30)
    a.job.abort(None, 1000)                       # stopped at the pen change before blue
    assert wait(lambda: getattr(a.job, "summary", None) is not None, 10)
    sm = a.job.summary
    assert sm["state"] == "aborted"
    assert [p["color"] for p in sm["pens"]] == ["#ff0000"]
    assert sm["draw_m"] == pytest.approx(0.12)
