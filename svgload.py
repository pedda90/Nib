"""SVG -> polylines in millimetres.

Reads SVGs from Illustrator, DrawingBotV3, Inkscape etc.,
applies all transforms and converts units correctly to mm.
Every polyline carries its layer (top-level group) and its color.
"""
from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field

from svgelements import (
    SVG, Arc, Close, Color, CubicBezier, Group, Line, Move, Path, Polygon,
    QuadraticBezier, Shape, SimpleLine, SVGText, SVGImage,
)
from svgelements import Polyline as Polyline_

PX_TO_MM = 25.4 / 96.0  # svgelements works in px at 96 ppi internally


@dataclass
class Polyline:
    pts: list            # [(x, y), ...] in mm
    layer: str           # name of the top-level group / layer
    color: str           # '#rrggbb'
    sub: str = ""        # name of the sublayer (2nd level in Illustrator), otherwise empty
    fill_of: int = -1    # index into LoadResult.fills if this is the edge of a fill-only shape


@dataclass
class FillShape:
    """A filled area, for hatching: closed rings in mm plus the SVG fill rule."""
    rings: list          # [[(x, y), ...], ...]
    layer: str
    color: str           # fill color '#rrggbb'
    sub: str = ""
    rule: str = "nonzero"


@dataclass
class LoadResult:
    polylines: list = field(default_factory=list)
    fills: list = field(default_factory=list)     # FillShape
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


def _visible(c) -> bool:
    try:
        return c is not None and c.value is not None and Color(c).alpha != 0
    except Exception:
        return False


def _fill_of(shape):
    """(fill color, has stroke) – fill color None if the shape isn't filled. SVG fills shapes
    black by default; plotter files rarely mean that, so a default black fill only counts
    when the shape has no stroke at all (e.g. a plain <circle>)."""
    stroke = _visible(shape.stroke)
    if not _visible(shape.fill):
        return None, stroke
    vals = getattr(shape, "values", {}) or {}
    if stroke and str(vals.get("fill", "")).strip().lower() in ("black", ""):
        return None, stroke
    return Color(shape.fill).hexrgb.lower(), stroke


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
    """Number of points for a curve, depending on its (estimated) length."""
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


FLAT_TOL_MM = 0.02  # max deviation of the line approximation from the true curve


def _flatten_bezier(seg, tol_px):
    """Split a Bezier curve into lines with a fixed tolerance (no point-by-point calls)."""
    if isinstance(seg, QuadraticBezier):
        x0, y0 = seg.start.x, seg.start.y
        x1, y1 = seg.control.x, seg.control.y
        x3, y3 = seg.end.x, seg.end.y
        # represent as cubic
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


# ------------------------------------------------------------ fast path data
# svgelements builds an object per path command, which takes seconds for hatching files
# with hundreds of thousands of commands. Long "d" attributes are therefore taken out
# before parsing (replaced by three moves that reveal the element's final transform)
# and read here directly.
BIG_D = 2000                      # characters from which a path's data is read directly
_PATH_TAG = re.compile(r"<path\b[^>]*>", re.S)
_D_ATTR = re.compile(r"(\sd\s*=\s*)([\"'])(.*?)\2", re.S)
_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_NARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}


def _extract_big_paths(text):
    """Replace long d attributes by a marker. Returns (new text, list of d strings)."""
    big = []

    def tag(m):
        t = m.group(0)
        dm = _D_ATTR.search(t)
        if not dm or len(dm.group(3)) < BIG_D or re.search(r"[Aa]", dm.group(3)):
            return t                                   # short, or with arcs: let svgelements do it
        big.append(dm.group(3))
        q = dm.group(2)
        return (t[:dm.start()] + f"{dm.group(1)}{q}M0,0 M1,0 M0,1{q} data-nibd={q}{len(big) - 1}{q}"
                + t[dm.end():])

    return _PATH_TAG.sub(tag, text), big


def _cubic_pts(x0, y0, x1, y1, x2, y2, x3, y3, tol):
    d = max(math.hypot(x0 - 2 * x1 + x2, y0 - 2 * y1 + y2), math.hypot(x1 - 2 * x2 + x3, y1 - 2 * y2 + y3))
    n = max(1, min(500, int(math.ceil(math.sqrt(0.75 * d / tol)))))
    out = []
    for i in range(1, n + 1):
        t = i / n
        mt = 1 - t
        a, b, c, e = mt * mt * mt, 3 * mt * mt * t, 3 * mt * t * t, t * t * t
        out.append((a * x0 + b * x1 + c * x2 + e * x3, a * y0 + b * y1 + c * y2 + e * y3))
    return out


def _fast_d(d, m):
    """Path data -> polylines in mm. m = (a, b, c, d, e, f) maps user units to px.
    Handles M L H V C S Q T Z (absolute and relative); no arcs (those take the slow way)."""
    a, b, c, dd, e, f = m
    tol = FLAT_TOL_MM / PX_TO_MM
    k = PX_TO_MM
    out = []
    cur = []
    toks = _TOKEN.findall(d)
    i, n = 0, len(toks)
    x = y = sx = sy = 0.0          # current point, subpath start (user units)
    lcx = lcy = None               # last control point (for S/T)
    lastcmd = ""
    cmd = ""

    def T(px, py):
        return (a * px + c * py + e, b * px + dd * py + f)

    while i < n:
        t = toks[i]
        if t[0].isalpha():
            cmd = t
            i += 1
            if cmd in "Zz":
                if cur:
                    cur.append(T(sx, sy))
                    if len(cur) > 1:
                        out.append(cur)
                cur = [T(sx, sy)]
                x, y = sx, sy
                lastcmd = cmd
                continue
        elif not cmd:
            i += 1
            continue
        up = cmd.upper()
        na = _NARGS[up]
        if i + na > n:
            break
        try:
            v = [float(z) for z in toks[i:i + na]]
        except ValueError:
            break
        i += na
        rel = cmd.islower()
        if up == "M":
            if len(cur) > 1:
                out.append(cur)
            x, y = (x + v[0], y + v[1]) if rel else (v[0], v[1])
            sx, sy = x, y
            cur = [T(x, y)]
            cmd = "l" if rel else "L"          # further pairs are line-tos
            lcx = None
        elif up == "L":
            x, y = (x + v[0], y + v[1]) if rel else (v[0], v[1])
            cur.append(T(x, y)); lcx = None
        elif up == "H":
            x = x + v[0] if rel else v[0]
            cur.append(T(x, y)); lcx = None
        elif up == "V":
            y = y + v[0] if rel else v[0]
            cur.append(T(x, y)); lcx = None
        elif up in "CS":
            if up == "C":
                c1x, c1y, c2x, c2y, ex, ey = v
                if rel:
                    c1x += x; c1y += y; c2x += x; c2y += y; ex += x; ey += y
            else:
                c2x, c2y, ex, ey = v
                if rel:
                    c2x += x; c2y += y; ex += x; ey += y
                if lcx is not None and lastcmd.upper() in "CS":
                    c1x, c1y = 2 * x - lcx, 2 * y - lcy
                else:
                    c1x, c1y = x, y
            p0, p1, p2, p3 = T(x, y), T(c1x, c1y), T(c2x, c2y), T(ex, ey)
            if not cur:
                cur = [p0]
            cur.extend(_cubic_pts(*p0, *p1, *p2, *p3, tol))
            lcx, lcy = c2x, c2y
            x, y = ex, ey
        elif up in "QT":
            if up == "Q":
                qx, qy, ex, ey = v
                if rel:
                    qx += x; qy += y; ex += x; ey += y
            else:
                ex, ey = v
                if rel:
                    ex += x; ey += y
                if lcx is not None and lastcmd.upper() in "QT":
                    qx, qy = 2 * x - lcx, 2 * y - lcy
                else:
                    qx, qy = x, y
            c1 = (x + 2 * (qx - x) / 3, y + 2 * (qy - y) / 3)
            c2 = (ex + 2 * (qx - ex) / 3, ey + 2 * (qy - ey) / 3)
            p0, p1, p2, p3 = T(x, y), T(*c1), T(*c2), T(ex, ey)
            if not cur:
                cur = [p0]
            cur.extend(_cubic_pts(*p0, *p1, *p2, *p3, tol))
            lcx, lcy = qx, qy
            x, y = ex, ey
        else:                                           # arc: not expected here
            x, y = (x + v[5], y + v[6]) if rel else (v[5], v[6])
            cur.append(T(x, y)); lcx = None
        lastcmd = cmd
    if len(cur) > 1:
        out.append(cur)
    return [[(px * k, py * k) for px, py in pl] for pl in out]


def load_svg(source, curve_step_mm: float = 0.3) -> LoadResult:
    """source: file path or file-like object."""
    res = LoadResult()
    big = []
    try:
        raw = source.read() if hasattr(source, "read") else open(source, "rb").read()
        text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else raw
        text, big = _extract_big_paths(text)
        svg = SVG.parse(io.StringIO(text), reify=True, ppi=96.0)
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
        # fast path for simple lines (DrawingBot/Illustrator hatching) – never filled
        if isinstance(shape, SimpleLine) and shape.transform.is_identity():
            res.polylines.append(Polyline(
                [(shape.x1 * PX_TO_MM, shape.y1 * PX_TO_MM), (shape.x2 * PX_TO_MM, shape.y2 * PX_TO_MM)],
                layer, color, sub))
            return
        pls = []
        if vals.get("data-nibd") is not None and big:
            # long path data read directly; the three moves give the final transform
            try:
                q = [seg.end for seg in shape if isinstance(seg, Move)]
                (ex, ey), (ax, ay), (cx, cy) = (q[0].x, q[0].y), (q[1].x, q[1].y), (q[2].x, q[2].y)
                m = (ax - ex, ay - ey, cx - ex, cy - ey, ex, ey)
                pls = _fast_d(big[int(vals["data-nibd"])], m)
            except Exception:
                pls = []
        elif isinstance(shape, (Polyline_, Polygon)) and shape.transform.is_identity():
            pts = [(p.x * PX_TO_MM, p.y * PX_TO_MM) for p in shape.points]
            if isinstance(shape, Polygon) and pts:
                pts.append(pts[0])
            pls = [pts] if len(pts) > 1 else []
        else:
            try:
                pls = _path_to_polylines(abs(Path(shape)), curve_step_mm)
            except Exception:
                return
        fill, stroke = _fill_of(shape)
        fi = -1
        if fill is not None:
            rings = [pl for pl in pls if len(pl) >= 3]
            if rings:
                rule = "evenodd" if str(vals.get("fill-rule", "")).strip() == "evenodd" else "nonzero"
                res.fills.append(FillShape(rings, layer, fill, sub, rule))
                if not stroke:
                    fi = len(res.fills) - 1        # its outline is only the edge of the fill
        for pl in pls:
            res.polylines.append(Polyline(pl, layer, color, sub, fi))

    # Illustrator wraps everything in 1-2 container groups -> descend to the actual layer level
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
            # remember sublayers (Illustrator: layer > sublayer) with their names
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
