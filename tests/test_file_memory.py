"""Settings per file: loading an SVG again brings back its placement, optimization, hatch
settings, hidden sublayers, layer order and ticks, and which layers were plotted.

Run with:  python -m pytest tests
"""
import pytest

import grbl
import server as S
from conftest import wait
from mockgrbl import MockSerial

SVG = b'''<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">
<g id="Outline"><path d="M10 10 L60 10" stroke="#ff0000" fill="none"/></g>
<g id="Detail"><path d="M10 20 L60 20" stroke="#ff0000" fill="none"/></g>
<rect x="20" y="30" width="20" height="20" fill="#ff0000"/>
<path d="M10 50 L90 50" stroke="#0000ff" fill="none"/>
</svg>'''
SVG_V2 = SVG.replace(b"L90 50", b"L80 50")          # the same drawing, exported again with a change

PLACE = {"x": 33, "y": 44, "scale": 1.5, "rotate": 90}
ORDER = [{"key": "#0000ff", "on": True}, {"key": "#ff0000", "on": False}]


def fresh_app():
    a = S.App()                                     # a restart: memory comes from the file
    a.settings["optimize"]["group"] = "color"
    return a


@pytest.fixture
def remembered():
    a = fresh_app()
    a.upload("portrait.svg", SVG)
    red = next(l for l in a.doc["layers"] if l["key"] == "#ff0000")
    hidden = [f"{red['id']}/{red['subs'][1]['name']}"]
    a.process({"simplify": 0.5, "fill": {"#ff0000": {"mode": "cross", "spacing": 0.7}}}, hidden)
    a.remember(place=PLACE, order=ORDER, reverse=True)
    return hidden


def test_reloading_a_file_restores_everything(remembered):
    a = fresh_app()
    a.settings["optimize"]["simplify"] = 0.02               # e.g. another file was loaded in between
    a.settings["optimize"]["fill"] = {}
    out = a.upload("whatever-name.svg", SVG)
    m = out["memory"]
    assert m["match"] == "file"
    assert m["place"] == PLACE and m["order"] == ORDER and m["reverse"] is True and m["saved"]
    assert a.settings["optimize"]["simplify"] == 0.5
    red = next(l for l in a.doc["layers"] if l["key"] == "#ff0000")
    assert red["fill"]["mode"] == "cross" and red["fill"]["spacing"] == 0.7
    assert out["doc"]["hidden"] == remembered


def test_unknown_file_has_no_memory():
    a = fresh_app()
    assert "memory" not in a.upload("new.svg", SVG)


def test_changed_file_is_recognised_by_name_without_progress(remembered):
    a = fresh_app()
    a.upload("portrait.svg", SVG)
    a.remember(done={"#ff0000": "26.11.2026"})
    b = fresh_app()
    m = b.upload("portrait.svg", SVG_V2)["memory"]
    assert m["match"] == "name" and m["place"] == PLACE and m["done"] == {}
    assert b.settings["optimize"]["simplify"] == 0.5
    assert fresh_app().upload("other.svg", SVG_V2)["memory"]["match"] == "file"   # now known by content


def test_hatch_test_strip_is_not_remembered_and_gives_the_file_back(remembered):
    a = fresh_app()
    a.upload("portrait.svg", SVG)
    a.load_hatch_test({"angle": 30})
    a.remember(place={"x": 1, "y": 1, "scale": 1, "rotate": 0})
    assert len(a._mem()) == 1
    back = a.close_hatch_test()
    assert back["memory"]["quiet"] and back["memory"]["order"] == ORDER
    assert fresh_app().upload("portrait.svg", SVG)["memory"]["place"] == PLACE


def test_oldest_files_are_dropped(monkeypatch):
    monkeypatch.setattr(S, "MEMORY_MAX", 2)
    a = fresh_app()
    for i in range(3):
        a.upload(f"f{i}.svg", SVG.replace(b"L60 10", f"L{61 + i} 10".encode()))
        a.remember(place={"x": i, "y": 0, "scale": 1, "rotate": 0})
    assert sorted(e["name"] for e in fresh_app()._mem().values()) == ["f1.svg", "f2.svg"]


@pytest.fixture
def plotter(monkeypatch):
    monkeypatch.setattr(grbl, "MockSerial", lambda: MockSerial(speedup=200.0))
    monkeypatch.setattr(S, "notify", lambda title, text: None)
    a = fresh_app()
    a.settings["job"]["pen_change"] = True
    a.upload("lines.svg", SVG)
    a.machine.connect(grbl.SIM_PORT)
    assert wait(lambda: a.machine.idle_and_empty(), 5)
    yield a
    a.machine.disconnect()


def test_plotted_layers_are_marked_done(plotter):
    a = plotter
    first, second = (l["id"] for l in a.doc["layers"])
    keys = {l["id"]: l["key"] for l in a.doc["layers"]}
    a.start_job({"layers": [first, second], "place": {"x": 10, "y": 10, "scale": 1, "rotate": 0}})
    assert wait(lambda: a.job.state == "pen_change", 30)
    assert list(a.done_marks()) == [keys[first]]           # first layer is done at the pen change
    a.job.abort(a.settings["machine"]["z_up"], a.settings["machine"]["z_feed"])
    assert wait(lambda: getattr(a.job, "summary", None) is not None, 10)
    assert list(fresh_app().upload("lines.svg", SVG)["memory"]["done"]) == [keys[first]]
    # the rest of the drawing, later: now both are done
    a.start_job({"layers": [second], "place": {"x": 10, "y": 10, "scale": 1, "rotate": 0}})
    assert wait(lambda: getattr(a.job, "summary", None) is not None, 30)
    assert set(a.done_marks()) == {keys[first], keys[second]}
    a.clear_done()
    assert a.done_marks() == {}
