"""Hatch fill: turns filled shapes into parallel lines a pen plotter can draw.

A shape is a list of closed rings [(x, y), ...] in mm. The fill rule decides which areas are
inside, like in SVG: "nonzero" (default) or "evenodd" (holes by alternation).
"""
from __future__ import annotations

import math

import numpy as np


def _edges(rings):
    """All ring edges as an (n, 4) array x0, y0, x1, y1 (rings are closed automatically)."""
    parts = []
    for r in rings:
        a = np.asarray(r, dtype=float)
        if len(a) < 3:
            continue
        if not np.allclose(a[0], a[-1]):
            a = np.vstack([a, a[:1]])
        parts.append(np.hstack([a[:-1], a[1:]]))
    return np.vstack(parts) if parts else np.empty((0, 4))


def _rotate(e, c, s):
    """Rotate edge array by the angle with cos c / sin s around the origin."""
    x0, y0, x1, y1 = e.T
    return np.column_stack([x0 * c - y0 * s, x0 * s + y0 * c, x1 * c - y1 * s, x1 * s + y1 * c])


def _spans(e, y, evenodd):
    """Inside intervals [(xa, xb), ...] of the horizontal line at height y."""
    x0, y0, x1, y1 = e.T
    up = (y0 <= y) & (y1 > y)
    down = (y1 <= y) & (y0 > y)
    hit = up | down
    if not hit.any():
        return []
    t = (y - y0[hit]) / (y1[hit] - y0[hit])
    xs = x0[hit] + t * (x1[hit] - x0[hit])
    wind = np.where(up[hit], 1, -1)
    o = np.argsort(xs, kind="stable")
    xs, wind = xs[o], wind[o]
    out = []
    if evenodd:
        for i in range(0, len(xs) - 1, 2):
            out.append((xs[i], xs[i + 1]))
        return out
    w = 0
    start = None
    for x, d in zip(xs, wind):
        before = w
        w += d
        if before == 0 and w != 0:
            start = x
        elif before != 0 and w == 0 and start is not None:
            out.append((start, x))
    return out


def _inside(e, x, y, evenodd):
    for xa, xb in _spans(e, y, evenodd):
        if xa <= x <= xb:
            return True
    return False


def hatch_lines(rings, spacing, angle=45.0, rule="nonzero", trim=None, join=True):
    """Hatch lines for one shape, as polylines [[(x, y), ...], ...] in the shape's units.

    spacing: distance between lines. angle: degrees, 0 = horizontal, counterclockwise as seen on
    paper (y points down there, so 45° rises to the right like "/"). trim: how far line ends
    stay away from the edge (default half the spacing, so ink doesn't spill over the outline).
    join: connect neighbouring lines into zigzags where the short connector stays inside the
    shape, which saves most pen lifts."""
    spacing = float(spacing)
    if spacing <= 0:
        raise ValueError("spacing must be > 0")
    e = _edges(rings)
    if not len(e):
        return []
    evenodd = rule == "evenodd"
    trim = spacing / 2 if trim is None else float(trim)
    a = math.radians(-angle)                       # y down: negative = counterclockwise on paper
    # work in a frame where the hatch lines are horizontal
    er = _rotate(e, math.cos(-a), math.sin(-a))
    er = er[er[:, 1] != er[:, 3]]                  # horizontal edges never cross a scanline
    if not len(er):
        return []
    ymin = min(er[:, 1].min(), er[:, 3].min())
    ymax = max(er[:, 1].max(), er[:, 3].max())
    rows = []                                      # per scanline: [(xa, xb), ...]
    y = ymin + spacing / 2
    while y < ymax:
        segs = []
        for xa, xb in _spans(er, y, evenodd):
            xa, xb = xa + trim, xb - trim
            if xb - xa > 1e-6:
                segs.append((xa, xb))
        rows.append((y, segs))
        y += spacing

    # zigzag: walk the rows, alternating direction, and chain a segment to one in the next
    # row when the connector is short and stays inside the shape
    lines = []
    open_chains = []                               # chains ending in the previous row: (pts, x_end)
    for ri, (y, segs) in enumerate(rows):
        rev = ri % 2 == 1
        new_chains = []
        free = list(open_chains)
        for xa, xb in segs:
            p0, p1 = ((xb, y), (xa, y)) if rev else ((xa, y), (xb, y))
            chain = None
            if join:
                for k, (pts, (ex, ey)) in enumerate(free):
                    d = math.hypot(p0[0] - ex, p0[1] - ey)
                    if d <= 3 * spacing and _inside(er, (p0[0] + ex) / 2, (p0[1] + ey) / 2, evenodd):
                        chain = pts
                        free.pop(k)
                        break
            if chain is None:
                chain = []
                lines.append(chain)
            chain.extend([p0, p1])
            new_chains.append((chain, p1))
        open_chains = new_chains

    c, s = math.cos(a), math.sin(a)                # back to the original frame
    return [[(x * c - y * s, x * s + y * c) for x, y in pl] for pl in lines if len(pl) >= 2]


def hatch_shape(rings, spacing, angle=45.0, cross=False, rule="nonzero", join=True):
    """Hatch (and optionally cross-hatch at +90°) one shape. join=False: every line on its own
    (pen lifted in between) instead of zigzags."""
    out = hatch_lines(rings, spacing, angle, rule, join=join)
    if cross:
        out += hatch_lines(rings, spacing, angle + 90.0, rule, join=join)
    return out


# ----------------------------------------------------------------- test strip
# Single-stroke digits for the labels of the test strip, on a 2 x 3 grid (x right, y down).
_GLYPHS = {
    "0": [[(0, 0), (2, 0), (2, 3), (0, 3), (0, 0)]],
    "1": [[(1, 0), (1, 3)]],
    "2": [[(0, 0), (2, 0), (2, 1.5), (0, 1.5), (0, 3), (2, 3)]],
    "3": [[(0, 0), (2, 0), (2, 3), (0, 3)], [(0, 1.5), (2, 1.5)]],
    "4": [[(0, 0), (0, 1.5), (2, 1.5)], [(2, 0), (2, 3)]],
    "5": [[(2, 0), (0, 0), (0, 1.5), (2, 1.5), (2, 3), (0, 3)]],
    "6": [[(2, 0), (0, 0), (0, 3), (2, 3), (2, 1.5), (0, 1.5)]],
    "7": [[(0, 0), (2, 0), (2, 3)]],
    "8": [[(0, 0), (2, 0), (2, 3), (0, 3), (0, 0)], [(0, 1.5), (2, 1.5)]],
    "9": [[(2, 1.5), (0, 1.5), (0, 0), (2, 0), (2, 3), (0, 3)]],
    ".": [[(0.4, 2.7), (0.4, 3)]],
}


def text_paths(text, x, y, height=2.5):
    """Polylines for digits and '.' with the top-left corner at (x, y)."""
    k = height / 3
    out = []
    cx = x
    for ch in text:
        g = _GLYPHS.get(ch)
        if g:
            out += [[(cx + px * k, y + py * k) for px, py in stroke] for stroke in g]
        cx += (1.2 if ch == "." else 2.8) * k
    return out


TEST_SPACINGS = (0.2, 0.3, 0.4, 0.5, 0.6, 0.8)
TEST_SIZE, TEST_GAP, TEST_LABEL = 20.0, 4.0, 3.5     # square, gap, label height (mm)


def test_strip(x, y, angle=45.0, cross=False, size=TEST_SIZE, gap=TEST_GAP, spacings=TEST_SPACINGS,
               join=True):
    """Paths of the hatch test strip with its top-left corner at (x, y), in sheet mm:
    one square per spacing, outlined, with the spacing written below it."""
    paths = []
    for i, sp in enumerate(spacings):
        x0 = x + i * (size + gap)
        sq = [(x0, y), (x0 + size, y), (x0 + size, y + size), (x0, y + size), (x0, y)]
        paths += hatch_shape([sq], sp, angle, cross, join=join)
        paths.append(sq)
        paths += text_paths(f"{sp:.1f}", x0 + 1, y + size + 2, TEST_LABEL)
    return paths


def test_strip_size(n=len(TEST_SPACINGS), size=TEST_SIZE, gap=TEST_GAP):
    """(width, height) of the test strip in mm."""
    return n * size + (n - 1) * gap, size + 2 + TEST_LABEL
