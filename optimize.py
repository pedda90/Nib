"""Path optimization: simplify, remove duplicates, sort, join."""
from __future__ import annotations

import math


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def path_length(pts):
    return sum(_dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def simplify(pts, tol):
    """Ramer-Douglas-Peucker (iterative) + removal of points that are too close."""
    if tol <= 0 or len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if seg2 == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = ((px - ax) * dx + (py - ay) * dy) / seg2
                t = 0 if t < 0 else 1 if t > 1 else t
                d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > best:
                best, idx = d, i
        if best > tol:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return [p for p, k in zip(pts, keep) if k]


def dedupe(paths, q=0.05):
    seen = set()
    out = []
    for p in paths:
        key = tuple((round(x / q), round(y / q)) for x, y in p)
        rkey = key[::-1]
        if key in seen or rkey in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def sort_paths(paths, start=(0.0, 0.0), with_index=False):
    """Greedy nearest neighbour with a grid index; paths may be reversed.
    With with_index=True the list of original indices is returned as well."""
    n = len(paths)
    if n < 2:
        return (list(paths), list(range(n))) if with_index else list(paths)
    xs = [c for p in paths for c in (p[0][0], p[-1][0])]
    ys = [c for p in paths for c in (p[0][1], p[-1][1])]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    area = max((maxx - minx) * (maxy - miny), 1.0)
    cell = max(math.sqrt(area / n) * 1.5, 0.5)

    grid = {}

    def key(pt):
        return (int((pt[0] - minx) // cell), int((pt[1] - miny) // cell))

    for i, p in enumerate(paths):
        for end in (0, 1):
            pt = p[0] if end == 0 else p[-1]
            grid.setdefault(key(pt), []).append((i, end))

    used = [False] * n
    gx_max = int((maxx - minx) // cell) + 1
    gy_max = int((maxy - miny) // cell) + 1
    max_ring = max(gx_max, gy_max) + 2
    out = []
    order = []
    cur = start
    for _ in range(n):
        cx, cy = key(cur)
        best = None
        best_d = float("inf")
        ring = 0
        while ring <= max_ring + abs(cx) + abs(cy):
            for gx in range(cx - ring, cx + ring + 1):
                for gy in (range(cy - ring, cy + ring + 1)
                           if gx in (cx - ring, cx + ring) else (cy - ring, cy + ring)):
                    bucket = grid.get((gx, gy))
                    if not bucket:
                        continue
                    alive = []
                    for (i, end) in bucket:
                        if used[i]:
                            continue
                        alive.append((i, end))
                        pt = paths[i][0] if end == 0 else paths[i][-1]
                        d = (pt[0] - cur[0]) ** 2 + (pt[1] - cur[1]) ** 2
                        if d < best_d:
                            best_d, best = d, (i, end)
                    if len(alive) != len(bucket):
                        grid[(gx, gy)] = alive
            # everything outside ring r is at least r*cell away.
            if best is not None and math.sqrt(best_d) <= ring * cell:
                break
            ring += 1
        if best is None:  # fallback (shouldn't happen)
            i = used.index(False)
            best = (i, 0)
        i, end = best
        used[i] = True
        p = paths[i] if end == 0 else paths[i][::-1]
        out.append(p)
        order.append(i)
        cur = p[-1]
    return (out, order) if with_index else out


def merge_paths(paths, tol):
    if tol <= 0 or not paths:
        return paths
    out = [list(paths[0])]
    for p in paths[1:]:
        if _dist(out[-1][-1], p[0]) <= tol:
            out[-1].extend(p[1:])
        else:
            out.append(list(p))
    return out


def optimize(paths, opts, start=(0.0, 0.0)):
    simp = float(opts.get("simplify", 0.02))
    min_len = float(opts.get("min_len", 0.0))
    paths = [simplify(p, simp) for p in paths]
    paths = [p for p in paths if len(p) >= 2 and path_length(p) >= min_len]
    if opts.get("dedupe", True):
        paths = dedupe(paths)
    if opts.get("sort", True):
        paths = sort_paths(paths, start)
    if opts.get("merge", True):
        paths = merge_paths(paths, float(opts.get("merge_tol", 0.1)))
    return paths


def optimize_tagged(paths, tags, opts, start=(0.0, 0.0)):
    """Like optimize, but every path keeps its tag (e.g. sublayer).
    All paths are sorted together; duplicates are only removed within the same
    tag and joining only happens between paths with the same tag. This way tags can
    be filtered out later without changing the order of the remaining paths.
    Result: list of (tag, path)."""
    simp = float(opts.get("simplify", 0.02))
    min_len = float(opts.get("min_len", 0.0))
    items = []
    for p, t in zip(paths, tags):
        p = simplify(p, simp)
        if len(p) >= 2 and path_length(p) >= min_len:
            items.append((t, p))
    if opts.get("dedupe", True):
        by = {}
        for t, p in items:
            by.setdefault(t, []).append(p)
        keep = {t: {id(p) for p in dedupe(v)} for t, v in by.items()}
        items = [(t, p) for t, p in items if id(p) in keep[t]]
    if opts.get("sort", True) and items:
        sorted_p, order = sort_paths([p for _, p in items], start, with_index=True)
        items = [(items[i][0], p) for i, p in zip(order, sorted_p)]
    if opts.get("merge", True) and items:
        tol = float(opts.get("merge_tol", 0.1))
        if tol > 0:
            out = [(items[0][0], list(items[0][1]))]
            for t, p in items[1:]:
                if t == out[-1][0] and _dist(out[-1][1][-1], p[0]) <= tol:
                    out[-1][1].extend(p[1:])
                else:
                    out.append((t, list(p)))
            items = out
    return items


def stats(paths, start=(0.0, 0.0)):
    draw = travel = 0.0
    cur = start
    for p in paths:
        travel += _dist(cur, p[0])
        draw += path_length(p)
        cur = p[-1]
    return {"draw_len": draw, "travel_len": travel, "lifts": len(paths)}
