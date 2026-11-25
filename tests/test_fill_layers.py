"""Hatch fill from SVG import to the plotted layers.

Run with:  python -m pytest tests
"""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server as S  # noqa: E402
import svgload  # noqa: E402

SVG = b'''<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">
<path d="M0 0 L10 0" stroke="#000000"/>
<rect x="10" y="10" width="20" height="20" fill="#ff0000"/>
<path d="M50 50 L60 50 L60 60 Z" style="fill:none;stroke:#0000ff"/>
<path d="M60 60 h30 v30 h-30z M70 70 h10 v10 h-10z" fill-rule="evenodd" fill="#ff0000" stroke="#00aa00"/>
</svg>'''


def test_import_finds_filled_shapes():
    r = svgload.load_svg(io.BytesIO(SVG))
    assert [(f.color, f.rule, len(f.rings)) for f in r.fills] == [("#ff0000", "nonzero", 1), ("#ff0000", "evenodd", 2)]
    edge = [p for p in r.polylines if p.fill_of >= 0]
    assert len(edge) == 1 and edge[0].color == "#ff0000"   # only the rect has no stroke of its own


def test_stroked_paths_without_fill_attribute_are_not_filled():
    svg = b'''<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm" viewBox="0 0 10 10">
    <path d="M0 0 L10 0 L10 10 Z" stroke="#000"/></svg>'''
    assert svgload.load_svg(io.BytesIO(svg)).fills == []


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(S, "JOBSTATE_FILE", str(tmp_path / "job_state.json"))
    a = S.App()
    a.settings["optimize"]["group"] = "color"
    a.upload("test.svg", SVG)
    return a


def red(app):
    return next(l for l in app.doc["layers"] if l["key"] == "#ff0000")


def length(paths):
    return sum(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 for p in paths for (x0, y0), (x1, y1) in zip(p, p[1:]))


def test_layers_report_fillable_shapes(app):
    assert red(app)["fills"] == 2
    assert red(app)["fill"]["mode"] == "off"
    assert next(l for l in app.doc["layers"] if l["key"] == "#000000")["fills"] == 0


def test_hatch_adds_paths_and_outline_switch(app):
    off = length(red(app)["paths"])
    app.process({"fill": {"#ff0000": {"mode": "hatch", "spacing": 1.0, "angle": 0}}})
    hatched = length(red(app)["paths"])
    # 20x20 square + 30x30 square minus 10x10 hole, at 1 mm: about 1200 mm of hatching
    assert hatched - off == pytest.approx(1200, rel=0.15)
    app.process({"fill": {"#ff0000": {"mode": "hatch", "spacing": 1.0, "angle": 0, "outline": False}}})
    no_outline = length(red(app)["paths"])
    assert no_outline == pytest.approx(hatched - 80, rel=0.02)   # the rect's 80 mm edge is gone


def test_cross_hatch_and_scale(app):
    app.process({"fill": {"#ff0000": {"mode": "hatch", "spacing": 1.0}}})
    one = length(red(app)["paths"])
    app.process({"fill": {"#ff0000": {"mode": "cross", "spacing": 1.0}}})
    two = length(red(app)["paths"])
    assert two > one * 1.7
    # at 50 % scale the spacing on paper stays 1 mm, i.e. 2 mm in design units -> about half
    # the hatch length in design units (on paper: a quarter of the area, same spacing)
    app.process({"fill": {"#ff0000": {"mode": "hatch", "spacing": 1.0}}, "fill_scale": 0.5})
    assert length(red(app)["paths"]) == pytest.approx(one / 2, rel=0.1)


def test_connect_lines_off_draws_every_line_on_its_own(app):
    app.process({"fill": {"#ff0000": {"mode": "hatch", "spacing": 1.0, "angle": 0, "join": True}}})
    joined = red(app)["count"]
    app.process({"fill": {"#ff0000": {"mode": "hatch", "spacing": 1.0, "angle": 0, "join": False}}})
    single = red(app)
    assert single["fill"]["join"] is False
    assert single["count"] > 5 * joined
    # every hatch line is a single straight stroke (2 points); only outlines have more
    assert sum(len(p) == 2 for p in single["paths"]) >= single["count"] - 3


def test_layer_ids_stay_put_when_outlines_are_dropped(app):
    before = [(l["id"], l["key"]) for l in app.doc["layers"]]
    # the red rect is the first red path; without its outline red's first path comes later
    app.process({"fill": {"#ff0000": {"mode": "hatch", "outline": False}}})
    assert [(l["id"], l["key"]) for l in app.doc["layers"]] == before


def test_resume_ignores_scale_and_inactive_fill():
    a = {"simplify": 0.02, "fill_scale": 1.0, "fill": {"#f00": {"mode": "off"}}}
    b = {"simplify": 0.02, "fill_scale": 0.5, "hidden": ["x"]}
    assert S._comparable_opts(a) == S._comparable_opts(b)
    c = {"simplify": 0.02, "fill": {"#f00": {"mode": "hatch"}}}
    assert S._comparable_opts(a) != S._comparable_opts(c)


def test_bad_fill_values_fall_back():
    c = S.fill_config({"fill": {"k": {"mode": "zigzag", "spacing": "x", "angle": 200}}}, "k")
    assert c["mode"] == "off" and c["spacing"] == S.FILL_DEFAULT["spacing"]
    assert S.fill_config({"fill": {"k": {"spacing": 0}}}, "k")["spacing"] == 0.05
    assert S.fill_config({"fill": {"k": {"angle": 200}}}, "k")["angle"] == 20


def test_hatch_test_strip_loads_like_a_file_and_gives_the_file_back(app):
    before = (app.doc["name"], [l["key"] for l in app.doc["layers"]])
    r = app.load_hatch_test({"angle": 30, "mode": "cross", "join": False})
    d = r["doc"]
    assert d["test"] is True and d["name"].startswith("Hatch test strip – cross 30°")
    assert [l["key"] for l in d["layers"]] == ["#000000"]
    w, h = S.H.test_strip_size()
    assert d["bbox"][2] - d["bbox"][0] == pytest.approx(w, abs=0.5)
    single = d["layers"][0]["count"]
    # changing the settings reloads the strip; the file stays set aside
    d = app.load_hatch_test({"angle": 30, "mode": "cross", "join": True})["doc"]
    assert d["layers"][0]["count"] < single
    d = app.close_hatch_test()["doc"]
    assert d["test"] is False
    assert (d["name"], [l["key"] for l in d["layers"]]) == before


def test_closing_the_test_strip_without_a_file(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(S, "JOBSTATE_FILE", str(tmp_path / "job_state.json"))
    a = S.App()
    assert a.load_hatch_test({})["doc"]["test"] is True
    assert a.close_hatch_test() == {"doc": None}


def test_a_new_file_replaces_the_set_aside_one(app):
    app.load_hatch_test({})
    app.upload("other.svg", SVG)               # opening a file while the strip is loaded
    assert app.doc["test"] is False and app.doc["name"] == "other.svg"
    assert app.close_hatch_test()["doc"]["name"] == "other.svg"   # nothing to go back to
