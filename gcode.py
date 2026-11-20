"""Platzierung (Design -> Blatt -> Maschine) und G-Code-Erzeugung.

Die Platzierungs-Mathematik ist identisch in web/app.js (placePoint) umgesetzt,
damit Vorschau und Plot exakt übereinstimmen.
"""
from __future__ import annotations

import math


def make_placer(bbox, place):
    """bbox = [minx, miny, maxx, maxy] des Designs (mm).
    place = {x, y, scale, rotate(0/90/180/270)}: obere linke Ecke des
    gedrehten+skalierten Designs liegt bei (x, y) auf dem Blatt."""
    minx, miny, maxx, maxy = bbox
    w, h = maxx - minx, maxy - miny
    s = float(place.get("scale", 1.0))
    r = int(place.get("rotate", 0)) % 360
    ox, oy = float(place.get("x", 0.0)), float(place.get("y", 0.0))

    def f(x, y):
        u, v = x - minx, y - miny
        if r == 90:
            u, v = h - v, u
        elif r == 180:
            u, v = w - u, h - v
        elif r == 270:
            u, v = v, w - u
        return ox + u * s, oy + v * s

    return f


def placed_size(bbox, place):
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if int(place.get("rotate", 0)) % 180 == 90:
        w, h = h, w
    s = float(place.get("scale", 1.0))
    return w * s, h * s


def to_machine(x, y, m):
    """Blattkoordinaten (Ursprung links oben, y nach unten) -> Maschine."""
    if m.get("swap_xy"):
        x, y = y, x
    if m.get("invert_x"):
        x = -x
    if m.get("invert_y"):
        y = -y
    return x, y


def from_machine(x, y, m):
    """Umkehrung von to_machine()."""
    if m.get("invert_x"):
        x = -x
    if m.get("invert_y"):
        y = -y
    if m.get("swap_xy"):
        x, y = y, x
    return x, y


def _fmt(v):
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


class GcodeBuilder:
    """Erzeugt (zeile, tag) Paare. tag = (ebenen_index, pfad_index) für Fortschritt/Fortsetzen."""

    def __init__(self, m):
        self.m = m
        self.lines = []

    def emit(self, line, tag=None):
        self.lines.append((line, tag))

    def pen_up(self, tag=None):
        m = self.m
        self.emit(f"G1 Z{_fmt(m['z_up'])} F{int(m['z_feed'])}", tag)
        if m.get("pen_up_delay", 0) > 0:
            self.emit(f"G4 P{m['pen_up_delay']:.2f}", tag)

    def pen_down(self, tag=None):
        m = self.m
        self.emit(f"G1 Z{_fmt(m['z_down'])} F{int(m['z_feed'])}", tag)
        if m.get("pen_down_delay", 0) > 0:
            self.emit(f"G4 P{m['pen_down_delay']:.2f}", tag)

    def header(self):
        self.emit("G21")
        self.emit("G90")
        self.pen_up()

    def layer(self, li, paths, placer, start_path=None, reverse=False):
        """Pfade einer Ebene. Vorwärts: start_path..Ende. Rückwärts: start_path..0, jeder
        Pfad in Gegenrichtung (genau die umgekehrte Fahrt). tag enthält immer den
        Original-Index, damit Fortschritt und Fortsetzen in beiden Richtungen passen."""
        m = self.m
        fd, ft = int(m["feed_draw"]), int(m["feed_travel"])
        n = len(paths)
        if reverse:
            sp = n - 1 if start_path is None else min(int(start_path), n - 1)
            order = range(sp, -1, -1)
        else:
            order = range(0 if start_path is None else int(start_path), n)
        for pi in order:
            p = paths[pi][::-1] if reverse else paths[pi]
            tag = (li, pi)
            pts = [to_machine(*placer(x, y), m) for x, y in p]
            x0, y0 = pts[0]
            self.emit(f"G1 X{_fmt(x0)} Y{_fmt(y0)} F{ft}", tag)
            self.pen_down(tag)
            first = True
            for x, y in pts[1:]:
                if first:
                    self.emit(f"G1 X{_fmt(x)} Y{_fmt(y)} F{fd}", tag)
                    first = False
                else:
                    self.emit(f"G1 X{_fmt(x)} Y{_fmt(y)}", tag)
            self.pen_up(tag)

    def footer(self, go_home=True):
        self.pen_up()
        if go_home:
            self.emit(f"G1 X0 Y0 F{int(self.m['feed_travel'])}")


def frame_gcode(bbox, place, m):
    """Rahmen des platzierten Designs mit angehobenem Stift abfahren."""
    w, h = placed_size(bbox, place)
    x, y = float(place.get("x", 0)), float(place.get("y", 0))
    b = GcodeBuilder(m)
    b.header()
    ft = int(m["feed_travel"])
    for px, py in [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]:
        mx, my = to_machine(px, py, m)
        b.emit(f"G1 X{_fmt(mx)} Y{_fmt(my)} F{ft}")
    return [l for l, _ in b.lines]


def estimate_seconds(layer_stats, scale, m):
    """Grobe Zeitschätzung inkl. Beschleunigungszuschlag."""
    fd = max(float(m["feed_draw"]), 1) / 60.0
    ft = max(float(m["feed_travel"]), 1) / 60.0
    zf = max(float(m["z_feed"]), 1) / 60.0
    zt = abs(float(m["z_down"]) - float(m["z_up"])) / zf * 2
    delays = float(m.get("pen_up_delay", 0)) + float(m.get("pen_down_delay", 0))
    t = (layer_stats["draw_len"] * scale / fd
         + layer_stats["travel_len"] * scale / ft
         + layer_stats["lifts"] * (zt + delays + 0.05))
    return t * 1.15
