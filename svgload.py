"""SVG -> Polylinien in Millimetern.

Liest SVGs aus Illustrator, DrawingBotV3, Inkscape usw. ein,
wendet alle Transformationen an und rechnet die Einheiten korrekt in mm um.
Jede Polylinie bekommt ihre Ebene (oberste Gruppe) und ihre Farbe mit.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from svgelements import (
    SVG, Arc, Close, Color, CubicBezier, Group, Line, Move, Path, Polygon,
    QuadraticBezier, Shape, SimpleLine, SVGText, SVGImage,
)
from svgelements import Polyline as Polyline_

PX_TO_MM = 25.4 / 96.0  # svgelements rechnet intern in px bei 96 ppi


@dataclass
class Polyline:
    pts: list            # [(x, y), ...] in mm
    layer: str           # Name der obersten Gruppe / Ebene
    color: str           # '#rrggbb'
    sub: str = ""        # Name der Unterebene (2. Ebene in Illustrator), sonst leer


@dataclass
class LoadResult:
    polylines: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    width_mm: float = 0.0
    height_mm: float = 0.0


def _color_of(shape) -> str:
    for c in (shape.stroke, shape.fill):
        try:
            if c is not None and c.value is not None and Color(c).alpha != 0:
                return Color(c).hexrgb.lower()
        except Exception:
            pass
    return "#000000"


def _group_label(g) -> str:
    vals = getattr(g, "values", {}) or {}
    for k, v in vals.items():
        if isinstance(k, str) and k.endswith("label") and v:
            return str(v)
    for k in ("data-name", "id"):
        if vals.get(k):
            return str(vals[k])
    return ""


def _seg_samples(seg, tol_mm: float) -> int:
    """Anzahl Stützpunkte für eine Kurve, abhängig von ihrer (geschätzten) Länge."""
    if isinstance(seg, CubicBezier):
        pts = (seg.start, seg.control1, seg.control2, seg.end)
    elif isinstance(seg, QuadraticBezier):
        pts = (seg.start, seg.control, seg.end)
    else:  # Arc
        try:
            length = seg.length(error=1e-3)
        except Exception:
            length = abs(seg.end - seg.start) * 2
        return max(2, min(400, int(math.ceil(length * PX_TO_MM / max(tol_mm, 0.05)))))
    length = sum(abs(pts[i + 1] - pts[i]) for i in range(len(pts) - 1))
    return max(2, min(400, int(math.ceil(length * PX_TO_MM / max(tol_mm, 0.05)))))


FLAT_TOL_MM = 0.02  # max. Abweichung der Linien-Näherung von der echten Kurve


def _flatten_bezier(seg, tol_px):
    """Bezier-Kurve mit fester Toleranz in Linien zerlegen (ohne Punkt-für-Punkt-Aufrufe)."""
    if isinstance(seg, QuadraticBezier):
        x0, y0 = seg.start.x, seg.start.y
        x1, y1 = seg.control.x, seg.control.y
        x3, y3 = seg.end.x, seg.end.y
        # als Kubische darstellen
        x1, y1, x2, y2 = (x0 + 2 * (x1 - x0) / 3, y0 + 2 * (y1 - y0) / 3,
                          x3 + 2 * (x1 - x3) / 3, y3 + 2 * (y1 - y3) / 3)
    else:
        x0, y0 = seg.start.x, seg.start.y
        x1, y1 = seg.control1.x, seg.control1.y
        x2, y2 = seg.control2.x, seg.control2.y
        x3, y3 = seg.end.x, seg.end.y
    d = max(math.hypot(x0 - 2 * x1 + x2, y0 - 2 * y1 + y2),
            math.hypot(x1 - 2 * x2 + x3, y1 - 2 * y2 + y3))
    n = max(1, min(500, int(math.ceil(math.sqrt(0.75 * d / tol_px)))))
    pts = []
    for i in range(1, n + 1):
        t = i / n
        mt = 1 - t
        a, b, c, e = mt * mt * mt, 3 * mt * mt * t, 3 * mt * t * t, t * t * t
        pts.append((a * x0 + b * x1 + c * x2 + e * x3, a * y0 + b * y1 + c * y2 + e * y3))
    return pts


def _path_to_polylines(path: Path, curve_step_mm: float) -> list:
    tol_px = FLAT_TOL_MM / PX_TO_MM
    out = []
    cur = []
    start = None
    for seg in path:
        if isinstance(seg, Move):
            if len(cur) > 1:
                out.append(cur)
            cur = [(seg.end.x, seg.end.y)]
            start = seg.end
        elif isinstance(seg, Close):
            if cur and start is not None:
                cur.append((start.x, start.y))
                out.append(cur)
            cur = [(start.x, start.y)] if start is not None else []
        elif isinstance(seg, Line):
            if not cur:
                cur = [(seg.start.x, seg.start.y)]
            cur.append((seg.end.x, seg.end.y))
        elif isinstance(seg, (CubicBezier, QuadraticBezier)):
            if not cur:
                cur = [(seg.start.x, seg.start.y)]
            cur.extend(_flatten_bezier(seg, tol_px))
        elif isinstance(seg, Arc):
            if not cur:
                cur = [(seg.start.x, seg.start.y)]
            n = _seg_samples(seg, curve_step_mm)
            for i in range(1, n + 1):
                p = seg.point(i / n)
                cur.append((p.x, p.y))
    if len(cur) > 1:
        out.append(cur)
    return [[(x * PX_TO_MM, y * PX_TO_MM) for x, y in pl] for pl in out]


def load_svg(source, curve_step_mm: float = 0.3) -> LoadResult:
    """source: Dateipfad oder file-like Objekt."""
    res = LoadResult()
    try:
        svg = SVG.parse(source, reify=True, ppi=96.0)
    except Exception as e:
        raise ValueError(f"The file is empty or not a valid SVG ({e}).") from None
    try:
        res.width_mm = float(svg.width) * PX_TO_MM
        res.height_mm = float(svg.height) * PX_TO_MM
    except Exception:
        pass

    skipped_text = skipped_img = 0

    def handle(shape, layer, sub=""):
        nonlocal skipped_text, skipped_img
        if isinstance(shape, SVGText):
            skipped_text += 1
            return
        if isinstance(shape, SVGImage):
            skipped_img += 1
            return
        if not isinstance(shape, Shape):
            return
        vals = getattr(shape, "values", {}) or {}
        if vals.get("display") == "none" or vals.get("visibility") == "hidden":
            return
        color = _color_of(shape)
        # Schneller Weg für einfache Linien (DrawingBot/Illustrator-Schraffuren)
        if isinstance(shape, SimpleLine) and shape.transform.is_identity():
            res.polylines.append(Polyline(
                [(shape.x1 * PX_TO_MM, shape.y1 * PX_TO_MM), (shape.x2 * PX_TO_MM, shape.y2 * PX_TO_MM)],
                layer, color, sub))
            return
        if isinstance(shape, (Polyline_, Polygon)) and shape.transform.is_identity():
            pts = [(p.x * PX_TO_MM, p.y * PX_TO_MM) for p in shape.points]
            if isinstance(shape, Polygon) and pts:
                pts.append(pts[0])
            if len(pts) > 1:
                res.polylines.append(Polyline(pts, layer, color, sub))
            return
        try:
            p = abs(Path(shape))
        except Exception:
            return
        for pl in _path_to_polylines(p, curve_step_mm):
            res.polylines.append(Polyline(pl, layer, color, sub))

    # Illustrator verpackt alles in 1-2 Hüllgruppen -> bis zur eigentlichen Ebenen-Ebene absteigen
    container = svg
    while True:
        kids = [c for c in container if isinstance(c, (Group, Shape))]
        if len(kids) == 1 and isinstance(kids[0], Group):
            container = kids[0]
        else:
            break

    for i, child in enumerate(container):
        if isinstance(child, Group):
            name = _group_label(child) or f"Group {i + 1}"
            # Unterebenen (Illustrator: Ebene > Unterebene) mit Namen merken
            for j, sc in enumerate(child):
                if isinstance(sc, Group):
                    sname = _group_label(sc) or f"{name} – group {j + 1}"
                    for el in sc.select():
                        if el is not sc:
                            handle(el, name, sname)
                else:
                    handle(sc, name)
        else:
            handle(child, "No layer")

    if skipped_text:
        res.warnings.append(
            f"{skipped_text} text element(s) ignored – convert them to outlines in Illustrator first.")
    if skipped_img:
        res.warnings.append(f"{skipped_img} image(s) ignored – only vector paths are plotted.")
    if not res.polylines:
        res.warnings.append("No plottable paths found.")
    return res
