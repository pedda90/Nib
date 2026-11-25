"""Nib – local web server for the GRBL pen plotter.

Start:  python server.py           (opens the browser at http://127.0.0.1:8765)
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import io
import json
import mimetypes
import os
import secrets
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import numpy as np

import gcode as G
import hatch as H
import optimize as O
from grbl import Job, Machine, list_ports
from svgload import load_svg

VERSION = "1.2.0"   # shown in Nib.app's "Get Info"; bump for every release

HERE = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "frozen", False):
    # as Nib.exe: the interface is inside the exe, settings live next to the exe
    RES = getattr(sys, "_MEIPASS", HERE)
    if sys.platform == "darwin":
        # inside Nib.app the program folder is read-only or moved by macOS: keep user files apart
        DATA = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Nib")
        os.makedirs(DATA, exist_ok=True)
    else:
        DATA = os.path.dirname(os.path.abspath(sys.executable))
else:
    RES = DATA = HERE
WEB = os.path.join(RES, "web")
SETTINGS_FILE = os.path.join(DATA, "settings.json")
JOBSTATE_FILE = os.path.join(DATA, "job_state.json")
PORT = 8765

# Access token for the API. Any web page open in the user's browser can send requests to
# 127.0.0.1, so every /api/ call must carry this token. It is created fresh at every start
# and only handed out inside index.html, which other sites can't read (same-origin policy;
# DNS rebinding is stopped by the Host check in Handler._allowed_host).
TOKEN = secrets.token_urlsafe(32)
TOKEN_PLACEHOLDER = b"__NIB_TOKEN__"

DEFAULTS = {
    "connection": {"port": "COM3", "baud": 115200},
    "machine": {
        "feed_draw": 6000, "feed_travel": 12000,
        "z_up": 0.5, "z_down": 5.0, "z_feed": 6000,
        "pen_down_delay": 0.0, "pen_up_delay": 0.0,
        "invert_x": False, "invert_y": False, "swap_xy": False,
        "jog_feed": 11000,
        "limits_on": True, "max_x": 420.0, "max_y": 297.0,
    },
    "paper": {"name": "A3 quer", "w": 420.0, "h": 297.0},
    "place": {"x": 10.0, "y": 10.0, "scale": 1.0, "rotate": 0},
    "optimize": {"group": "auto", "simplify": 0.02, "merge_tol": 0.1, "min_len": 0.0,
                 "dedupe": True, "sort": True, "merge": True, "curve_step": 0.3},
    "job": {"pen_change": True, "go_home": True, "reverse": False},
}


def deep_merge(base, upd):
    out = copy.deepcopy(base)
    for k, v in (upd or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def allowed_area(m, machine=None, wco_xy=None):
    """Allowed area in sheet coordinates (x0, y0, x1, y1), measured from the origin.

    If the plotter's firmware limits are known ($130/$131 with $20=1), only those apply.
    Without homing they count from the power-on position (machine coordinate 0..max) and
    are converted via the origin offset (WCO) – so the origin may be anywhere.
    Otherwise (e.g. simulator, swapped axes): 0..max_x / 0..max_y from the origin.
    """
    ux, uy = float(m["max_x"]), float(m["max_y"])
    if machine is not None and machine.connected and not (
            m.get("invert_x") or m.get("invert_y") or m.get("swap_xy")):
        st = machine.status()
        wco = st.get("wco")
        if wco:
            # the work area (setting) counts from machine home = power-on corner,
            # in addition to the firmware limit – the smaller value wins.
            # (the firmware limit of 297 mm is larger than the real Y travel -> carriage hits the end.)
            fx, fy = st.get("fw_max") or (None, None)
            mx = min(ux, fx) if (st.get("fw_soft_limits") and fx) else ux
            my = min(uy, fy) if (st.get("fw_soft_limits") and fy) else uy
            wx, wy = (wco_xy if wco_xy is not None else wco[:2])
            return -wx, -wy, mx - wx, my - wy
    return 0.0, 0.0, ux, uy


SPEED_NAMES = {"feed_draw": "Drawing", "feed_travel": "Travel", "jog_feed": "Jog", "z_feed": "Z"}


def speed_limits(fw):
    """(max X/Y, max Z) in mm/min from $110/$111/$112, or (None, None)."""
    if not fw or not (fw.get(110) and fw.get(111)):
        return None, None
    return min(fw[110], fw[111]), fw.get(112)


def clamp_speeds(m, fw):
    """Cap speeds at the firmware maximum. Returns the changed fields."""
    vxy, vz = speed_limits(fw)
    changed = []
    if not vxy:
        return changed
    for k in ("feed_draw", "feed_travel", "jog_feed", "z_feed"):
        lim = vz if k == "z_feed" else vxy
        if lim and float(m.get(k, 0)) > lim:
            m[k] = lim
            changed.append(f"{SPEED_NAMES[k]} {lim:g} mm/min")
    return changed


def check_limits(bbox, place, m, machine=None, wco_xy=None):
    """Error message if the placed design leaves the allowed area, otherwise None."""
    if not m.get("limits_on", True):
        return None
    w, h = G.placed_size(bbox, place)
    x, y = float(place.get("x", 0)), float(place.get("y", 0))
    ax0, ay0, ax1, ay1 = allowed_area(m, machine, wco_xy)
    eps = 0.01
    if x < ax0 - eps or y < ay0 - eps or x + w > ax1 + eps or y + h > ay1 + eps:
        return (f"The design is outside the machine limits (allowed X {ax0:.1f} to {ax1:.1f}, "
                f"Y {ay0:.1f} to {ay1:.1f} mm from origin; it covers X {x:.1f}–{x + w:.1f}, "
                f"Y {y:.1f}–{y + h:.1f} mm). Move or shrink it, or check the origin.")
    return None


FILL_DEFAULT = {"mode": "off", "spacing": 0.4, "angle": 45, "outline": True, "join": True}
FILL_MODES = ("off", "hatch", "cross")


def fill_config(opts, key):
    """Hatch settings of one layer (by its group key), checked and with defaults filled in."""
    c = dict(FILL_DEFAULT)
    c.update((opts.get("fill") or {}).get(str(key)) or {})
    if c["mode"] not in FILL_MODES:
        c["mode"] = "off"
    try:
        c["spacing"] = min(20.0, max(0.05, float(c["spacing"])))
        c["angle"] = float(c["angle"]) % 180
    except (TypeError, ValueError):
        c["spacing"], c["angle"] = FILL_DEFAULT["spacing"], FILL_DEFAULT["angle"]
    c["outline"] = bool(c["outline"])
    c["join"] = bool(c["join"])
    return c


def _comparable_opts(o):
    """Options that change the plotted paths – for recognising a resume point.
    (Sublayer visibility, the scale used for hatching and inactive fills don't count.)"""
    o = {k: v for k, v in (o or {}).items() if k not in ("hidden", "fill_scale")}
    fills = {k: v for k, v in (o.get("fill") or {}).items() if (v or {}).get("mode", "off") != "off"}
    if fills:
        o["fill"] = fills
    else:
        o.pop("fill", None)
    return o


def _color_name(hexcol, names):
    """Name a color layer, e.g. 'hatch Y' -> 'Y (#f5d000)'."""
    top = sorted(names.items(), key=lambda kv: -kv[1])
    if top and top[0][0] not in ("No layer",) and not top[0][0].startswith("Group "):
        label = top[0][0]
        if len(top) > 1:
            label += f" +{len(top) - 1}"
        return f"{label}  {hexcol}"
    return f"Color {hexcol}"


class App:
    def __init__(self):
        self.settings = deep_merge(DEFAULTS, load_json(SETTINGS_FILE, {}))
        self.machine = Machine()
        self.machine.on_fw = self._fw_received
        self.job: Job | None = None
        self.raw = None           # LoadResult
        self.file_name = ""
        self.file_hash = ""
        self.doc = None           # processed layers
        self.doc_lock = threading.Lock()
        self.hidden = set()       # hidden sublayers "L<i>/<name>"
        self._opt_cache = {}      # (mode, layer, options) -> [(sublayer, path)], all sublayers together
        self._all_cache = {}      # id(tagged) -> (tagged, rounded flat paths) for the JSON reply
        self._hatch_cache = {}    # (fill index, spacing, angle, cross) -> hatch lines
        self._last_save = 0.0

    def _fw_received(self, fw):
        """Take the work area from the plotter firmware ($130/$131)."""
        fx, fy = fw.get(130), fw.get(131)
        m = self.settings["machine"]
        # only shrink: a smaller, self-measured work area is kept.
        nx, ny = min(m["max_x"], fx), min(m["max_y"], fy)
        if (m["max_x"], m["max_y"]) != (nx, ny):
            m["max_x"], m["max_y"] = nx, ny
            self.save_settings()
        self.machine._log("info", f"Work area reported by firmware: {fx:g} × {fy:g} mm"
                          + (" – soft limits on, measured from the power-on position"
                             if fw.get(20) else ""))
        vxy, vz = speed_limits(fw)
        if vxy:
            self.machine._log("info", f"Max speed reported by firmware: X/Y {vxy:g} mm/min, Z {vz:g} mm/min")
        changed = clamp_speeds(m, fw)
        if changed:
            self.save_settings()
            self.machine._log("warn", "Capped at firmware maximum: " + ", ".join(changed))

    # ------------------------------------------------------------ document
    def upload(self, name, data: bytes):
        res = load_svg(io.BytesIO(data), float(self.settings["optimize"]["curve_step"]))
        with self.doc_lock:
            self.raw = res
            self.file_name = name
            self.file_hash = hashlib.sha1(data).hexdigest()
            self.hidden = set()
            self._opt_cache = {}
            self._all_cache = {}
            self._hatch_cache = {}
            xs = [x for pl in res.polylines for x, _ in pl.pts] or [0]
            ys = [y for pl in res.polylines for _, y in pl.pts] or [0]
            self._bbox = [min(xs), min(ys), max(xs), max(ys)]
        return self.process(self.settings["optimize"])

    def process(self, opts, hidden=None, light=False):
        """Lay out the document. light=True (used when only showing/hiding sublayers):
        the reply carries layer stats but no path data – the client filters its own copy."""
        opts = {k: v for k, v in opts.items() if k not in ("hidden", "light")}
        self.settings["optimize"] = deep_merge(self.settings["optimize"], opts)
        self.save_settings()
        opts = self.settings["optimize"]
        if hidden is not None:
            self.hidden = set(hidden)
        if self.raw is None:
            return {"error": "No file loaded"}
        t0 = time.time()
        polys = self.raw.polylines
        mode = opts.get("group", "auto")
        if mode == "auto":
            ncol = len({p.color for p in polys})
            nlay = len({p.layer for p in polys})
            mode = "color" if 2 <= ncol <= 12 else ("layer" if nlay > 1 else "color")
        keyof = lambda layer, color: layer if mode == "layer" else (color if mode == "color" else "Alle")
        fscale = float(opts.get("fill_scale") or 1.0) or 1.0
        fcfg = {}                                    # group key -> hatch settings

        def cfg(key):
            if key not in fcfg:
                fcfg[key] = fill_config(opts, key)
            return fcfg[key]

        # hatch lines of filled shapes become ordinary paths of their layer
        extra = []                                   # Polyline-like (pts, layer, color, sub)
        nfills = {}
        for fi, f in enumerate(getattr(self.raw, "fills", [])):
            key = keyof(f.layer, f.color)
            nfills[key] = nfills.get(key, 0) + 1
            c = cfg(key)
            if c["mode"] == "off":
                continue
            # spacing is given on paper: undo the placement scale
            hk = (fi, round(c["spacing"] / fscale, 5), c["angle"], c["mode"], c["join"])
            lines = self._hatch_cache.get(hk)
            if lines is None:
                lines = H.hatch_shape(f.rings, c["spacing"] / fscale, c["angle"], c["mode"] == "cross",
                                      f.rule, join=c["join"])
                self._hatch_cache[hk] = lines
            extra += [(pl, f.layer, f.color, f.sub) for pl in lines]

        def all_paths():
            for p in polys:
                if p.fill_of >= 0:
                    c = cfg(keyof(p.layer, p.color))
                    if c["mode"] != "off" and not c["outline"]:
                        continue                     # edge of a hatched shape, outline off
                yield p.pts, p.layer, p.color, getattr(p, "sub", "")
            yield from extra

        groups = {}
        # layer order (and so the ids L0, L1, …) comes from the file alone, so hatch
        # settings – e.g. dropping outlines – never shift layers around
        order = list(dict.fromkeys([keyof(p.layer, p.color) for p in polys]
                                   + [keyof(f.layer, f.color) for f in getattr(self.raw, "fills", [])]))
        for pts, p_layer, p_color, p_sub in all_paths():
            key = keyof(p_layer, p_color)
            # sublayer: Illustrator sublayer; for color layers the Illustrator layer,
            # for Illustrator layers the color
            sub = p_sub or (p_color if mode == "layer" else p_layer)
            if key not in groups:
                groups[key] = {"paths": [], "colors": {}, "subs": {}, "names": {}}
                if key not in order:
                    order.append(key)
            gi = order.index(key)
            groups[key]["subs"][sub] = groups[key]["subs"].get(sub, 0) + 1
            # all paths (hidden ones too) go into the joint optimization
            groups[key]["paths"].append(pts)
            groups[key].setdefault("tags", []).append(sub)
            if f"L{gi}/{sub}" in self.hidden:
                continue
            groups[key]["colors"][p_color] = groups[key]["colors"].get(p_color, 0) + 1
            groups[key].setdefault("names", {})
            nm = p_layer.rstrip("0123456789 ").strip() or p_layer
            groups[key]["names"][nm] = groups[key]["names"].get(nm, 0) + 1
            groups[key].setdefault("full", set()).add(p_layer)

        bbox = self._bbox

        layers = []
        okey = json.dumps({k: v for k, v in opts.items() if k not in ("fill", "fill_scale")}, sort_keys=True)
        cache = {}
        for i, key in enumerate(order):
            g = groups.get(key)
            if g is None:
                continue                             # nothing left to draw (e.g. outline off, fill off)
            lid = f"L{i}"
            visible = tuple(s for s in g["subs"] if f"{lid}/{s}" not in self.hidden)
            start = (bbox[0], bbox[1])
            # optimize once with ALL sublayers together (independent of hiding);
            # hiding only filters afterwards – the order of the rest stays the same.
            c = cfg(key)
            ck = (mode, key, okey, json.dumps(c, sort_keys=True) + (f"@{fscale:g}" if c["mode"] != "off" else ""))
            tagged = self._opt_cache.get(ck)
            if tagged is None:
                tagged = O.optimize_tagged(g["paths"], g["tags"], opts, start=start)
            cache[ck] = tagged
            vis = set(visible)
            paths = [p for t, p in tagged if t in vis]
            hidden_here = len(visible) < len(g["subs"])
            if not paths and not hidden_here:
                continue
            st = O.stats(paths, start=(bbox[0], bbox[1]))
            color = (max(g["colors"].items(), key=lambda kv: kv[1])[0] if g["colors"]
                     else (key if mode == "color" else "#000000"))
            subs = ([{"name": s, "count": n, "hidden": f"{lid}/{s}" in self.hidden} for s, n in g["subs"].items()]
                    if len(g["subs"]) > 1 else [])
            names = g["names"] or {s: 1 for s in g["subs"]}
            if len(g.get("full", ())) == 1:          # exactly one Illustrator layer -> show its full name
                names = {next(iter(g["full"])): 1}
            layers.append({
                "id": lid, "name": str(key) if mode != "color" else _color_name(key, names),
                "color": color, "count": len(paths), "points": sum(len(p) for p in paths),
                "paths": paths, "subs": subs, **st,
                # all paths in plot order with their sublayer, so the client can hide sublayers itself
                "subnames": list(g["subs"]), "tagged": tagged,
                # hatch fill: group key the settings belong to, number of filled shapes
                "key": str(key), "fills": nfills.get(key, 0), "fill": c,
            })
        self._opt_cache = cache
        hidden_now = sorted(h for h in self.hidden if any(
            f"{l['id']}/{s['name']}" == h for l in layers for s in l["subs"]))
        with self.doc_lock:
            self.doc = {"name": self.file_name, "hash": self.file_hash, "bbox": bbox,
                        "layers": layers, "mode": mode, "warnings": list(self.raw.warnings),
                        "opts": copy.deepcopy(opts) | ({"hidden": hidden_now} if hidden_now else {}),
                        "hidden": hidden_now,
                        "width_mm": self.raw.width_mm, "height_mm": self.raw.height_mm}
        return self.doc_json(time.time() - t0, light=light)

    def doc_json(self, took=0.0, light=False):
        """Full reply: every path of a layer (hidden sublayers too) as 'all' plus 'tags'
        (index into 'subnames'); the visible 'paths' are derived from it on the client."""
        d = self.doc
        if d is None:
            return {"doc": None}
        layers = []
        for l in d["layers"]:
            base = {k: v for k, v in l.items() if k not in ("paths", "tagged")}
            if not light:
                ix = {n: i for i, n in enumerate(l["subnames"])}
                base["all"] = self._flat_all(l["tagged"])
                base["tags"] = [ix[t] for t, _ in l["tagged"]]
            layers.append(base)
        return {"doc": {k: v for k, v in d.items() if k != "layers"} | {"layers": layers},
                "took": round(took, 2), "resume": self.resume_info()}

    def _flat_all(self, tagged):
        """Paths as flat [x0, y0, x1, y1, …] rounded to 0.01 mm – computed once per
        optimization result (rounding a million coordinates one by one takes ~0.5 s)."""
        hit = self._all_cache.get(id(tagged))
        if hit and hit[0] is tagged:
            return hit[1]
        lens = [2 * len(p) for _, p in tagged]
        flat = np.fromiter((c for _, p in tagged for pt in p for c in pt), dtype=float, count=sum(lens))
        vals = np.round(flat, 2).tolist()
        out, o = [], 0
        for n in lens:
            out.append(vals[o:o + n])
            o += n
        if len(self._all_cache) > 40:
            self._all_cache.clear()
        self._all_cache[id(tagged)] = (tagged, out)
        return out

    # ---------------------------------------------------------- settings
    def save_settings(self):
        try:
            save_json(SETTINGS_FILE, self.settings)
        except Exception:
            traceback.print_exc()

    @staticmethod
    def path_key(p):
        """Fingerprint of a line: start, end, point count (independent of its number)."""
        r = lambda v: round(v, 2)
        return [r(p[0][0]), r(p[0][1]), r(p[-1][0]), r(p[-1][1]), len(p)]

    def resume_info(self):
        st = load_json(JOBSTATE_FILE, None)
        if not st or not self.doc or st.get("finished"):
            return None
        if st.get("hash") != self.doc["hash"]:
            return None
        if "path_key" not in st:
            # old state without fingerprint: only with exactly the same settings
            return st if st.get("opts") == self.doc["opts"] else None
        if _comparable_opts(st.get("opts")) != _comparable_opts(self.doc["opts"]):
            return None
        by_id = {l["id"]: l for l in self.doc["layers"]}
        ids = st.get("layer_ids") or []
        if not ids or st.get("layer", 0) >= len(ids) or ids[st["layer"]] not in by_id:
            return None
        paths = by_id[ids[st["layer"]]]["paths"]
        key = st["path_key"]
        hit = next((i for i, p in enumerate(paths) if p and self.path_key(p) == key), None)
        if hit is None:
            return None          # the line no longer exists (e.g. hidden)
        out = dict(st)
        out["moved"] = hit != st.get("path")
        out["path"] = hit
        return out

    def save_progress(self, job, force=False, finished=False):
        if not force and time.time() - self._last_save < 2:
            return
        self._last_save = time.time()
        li, pi = job.resume_point()
        key = None
        try:
            lid = job.layer_ids[li]
            lp = next(l for l in self.doc["layers"] if l["id"] == lid)["paths"]
            if 0 <= pi < len(lp):
                key = self.path_key(lp[pi])
        except Exception:
            pass
        try:
            save_json(JOBSTATE_FILE, {
                "path_key": key,
                "hash": self.doc["hash"], "opts": self.doc["opts"], "name": self.doc["name"],
                "layer_ids": job.layer_ids, "layer": li, "path": pi,
                "layer_name": job.layers[li]["name"] if li < len(job.layers) else "",
                "place": job.place, "reverse": getattr(job, "reverse", False), "finished": finished, "time": time.strftime("%d.%m.%Y %H:%M"),
            })
        except Exception:
            traceback.print_exc()

    # ------------------------------------------------------------------ Job
    def start_job(self, body):
        if self.job and self.job.state in ("running", "paused", "pen_change"):
            return {"error": "A plot is already running"}
        if not self.machine.connected:
            return {"error": "Plotter not connected"}
        if self.doc is None:
            return {"error": "No file loaded"}
        m = self.settings["machine"]
        place = body.get("place", self.settings["place"])
        by_id = {l["id"]: l for l in self.doc["layers"]}
        ids = [i for i in body.get("layers", []) if i in by_id and by_id[i]["count"]]
        if not ids:
            return {"error": "No layer selected"}
        layers = [by_id[i] for i in ids]
        err = (check_limits(self.doc["bbox"], place, m, self.machine)
               or self.machine.z_check(m["z_up"]) or self.machine.z_check(m["z_down"]))
        if err:
            return {"error": err}
        placer = G.make_placer(self.doc["bbox"], place)

        reverse = bool(body.get("reverse", False))

        def build_layer(li, sp):
            b = G.GcodeBuilder(m)
            b.layer(li, layers[li]["paths"], placer, sp, reverse)
            return b.lines

        def header():
            b = G.GcodeBuilder(m)
            b.header()
            return b.lines

        def footer(home):
            b = G.GcodeBuilder(m)
            b.footer(home and self.settings["job"]["go_home"])
            return b.lines

        def change_moves():
            b = G.GcodeBuilder(m)
            b.footer(True)          # pen up, go to origin
            return b.lines

        sl = int(body.get("start_layer", 0))
        sp = body.get("start_path")
        sp = None if sp is None else int(sp)
        meta = [{"id": l["id"], "name": l["name"], "color": l["color"], "count": l["count"]}
                for l in layers]
        job = Job(self.machine, meta, build_layer, header, footer, sl, sp,
                  pen_change=bool(self.settings["job"]["pen_change"]),
                  # save immediately when there are no confirmed lines (start, pen change)
                  on_progress=lambda j: self.save_progress(j, force=not j.recent),
                  change_moves=change_moves)
        job.layer_ids = ids
        job.place = place
        job.reverse = reverse
        self.job = job
        self.settings["place"] = place
        self.save_settings()
        job.start()
        self.machine._log("info", f"Plot started: {self.doc['name']} – {len(layers)} layer(s)"
                          + (" – reverse" if reverse else "")
                          + (f", from layer {sl + 1} path {sp + 1}" if sp is not None else ""))
        threading.Thread(target=self._watch_job, args=(job,), daemon=True).start()
        return {"ok": True}

    def _watch_job(self, job):
        while job.state in ("running", "paused", "pen_change"):
            time.sleep(0.5)
        self.save_progress(job, force=True, finished=(job.state == "done"))

    def job_info(self):
        if not self.job:
            return None
        info = self.job.info()
        info["layers"] = self.job.layers
        info["layer_ids"] = self.job.layer_ids
        info["reverse"] = getattr(self.job, "reverse", False)
        return info


APP = App()

# heartbeat of the browser page: when the last window closes, Nib exits.
LIFE = {"last_poll": 0.0, "bye_at": 0.0, "seen": False}
BYE_GRACE = 5        # s after closing (reloading the page checks in again before that)
NO_POLL_LIMIT = 180  # s without a heartbeat (crash; background tabs poll only rarely)


class Handler(BaseHTTPRequestHandler):
    server_version = f"Nib/{VERSION}"

    def log_message(self, *a):
        pass

    def end_headers(self):
        # no framing by other sites (clickjacking), no MIME sniffing
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    # ------------------------------------------------------------ access check
    def _origins(self):
        port = self.server.server_address[1]
        return {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def _allowed_host(self):
        """Host must be our own address. A different name means DNS rebinding:
        a foreign site pointing its own domain at 127.0.0.1 to read Nib's pages."""
        host = (self.headers.get("Host") or "").lower()
        return f"http://{host}" in self._origins()

    def _allowed_api(self, query):
        """API calls need the token (header, or ?token= for navigator.sendBeacon) and,
        if the browser names an origin, it must be Nib's own page."""
        origin = self.headers.get("Origin")
        if origin is not None and origin not in self._origins():
            return False
        sent = self.headers.get("X-Nib-Token") or (parse_qs(query).get("token") or [""])[0]
        return hmac.compare_digest(sent.encode(), TOKEN.encode())

    _deny_seen = {}           # (method, path, reason, origin, host) -> [time last printed, repeats since]
    _deny_lock = threading.Lock()

    def _deny(self, why):
        # a stale browser tab can knock several times a second: print each kind of
        # refusal at most every 10 s, with the number of repeats in between
        origin, host = self.headers.get("Origin"), self.headers.get("Host")
        key = (self.command, urlparse(self.path).path, why, origin, host)
        now = time.time()
        with Handler._deny_lock:
            seen = Handler._deny_seen.setdefault(key, [0.0, 0])
            show = now - seen[0] >= 10
            repeats = seen[1]
            seen[:] = [now, 0] if show else [seen[0], seen[1] + 1]
        if show:
            more = f" – {repeats} more since the last message" if repeats else ""
            print(f"Blocked request {key[0]} {key[1]}: {why} (Origin: {origin}, Host: {host}){more}")
        # read a (small) request body first: answering while the client is still sending
        # makes Windows reset the connection, and the client sees an error instead of 403
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if 0 < n <= 1 << 20:
                self.rfile.read(n)
            else:
                self.close_connection = True
        except (ValueError, OSError):
            self.close_connection = True
        data = json.dumps({"error": "Forbidden"}).encode()
        self.send_response(403)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _check(self, url):
        """True if the request may proceed; otherwise a 403 has been sent."""
        if not self._allowed_host():
            self._deny("wrong Host")
            return False
        if url.path.startswith("/api/") and not self._allowed_api(url.query):
            self._deny("missing/invalid token or foreign Origin")
            return False
        return True

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        url = urlparse(self.path)
        if not self._check(url):
            return
        path = url.path
        try:
            if path == "/api/status":
                LIFE["last_poll"], LIFE["seen"] = time.time(), True
                try:
                    since = int((parse_qs(url.query).get("log") or ["0"])[0])
                except ValueError:
                    since = 0
                return self._json({"machine": APP.machine.status(), "job": APP.job_info(),
                                   "area": allowed_area(APP.settings["machine"], APP.machine),
                                   "mset": APP.settings["machine"],
                                   "vmax": speed_limits(APP.machine.fw),
                                   "log": APP.machine.log_since(since)})
            if path == "/api/ports":
                return self._json({"ports": list_ports()})
            if path == "/api/settings":
                return self._json(APP.settings)
            if path == "/api/defaults":
                return self._json(DEFAULTS)
            if path == "/api/doc":
                return self._json(APP.doc_json())
            return self._static(path)
        except Exception as e:
            traceback.print_exc()
            return self._json({"error": str(e)}, 500)

    def _static(self, path):
        if path == "/":
            path = "/index.html"
        fp = os.path.normpath(os.path.join(WEB, path.lstrip("/")))
        if not fp.startswith(WEB) or not os.path.isfile(fp):
            self.send_error(404)
            return
        with open(fp, "rb") as f:
            data = f.read()
        if path == "/index.html":
            data = data.replace(TOKEN_PLACEHOLDER, TOKEN.encode())
        self.send_response(200)
        ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        url = urlparse(self.path)
        if not self._check(url):
            return
        path = url.path
        try:
            if path == "/api/upload":
                name = unquote(self.headers.get("X-Filename", "file.svg"))
                return self._json(APP.upload(name, self._body()))
            # JSON only: browsers can't send that cross-site without a CORS preflight,
            # which this server never approves
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return self._json({"error": "Expected Content-Type: application/json"}, 415)
            body = json.loads(self._body() or b"{}")
            return self._json(self.route(path, body))
        except Exception as e:
            traceback.print_exc()
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def route(self, path, b):
        M = APP.machine
        S = APP.settings
        mset = S["machine"]
        busy = APP.job and APP.job.state in ("running", "paused", "pen_change")

        if path == "/api/bye":
            LIFE["bye_at"] = time.time()
            return {"ok": True}
        if path == "/api/settings":
            APP.settings = deep_merge(S, b)
            changed = clamp_speeds(APP.settings["machine"], M.fw)
            if changed:
                M._log("warn", "Capped at firmware maximum: " + ", ".join(changed))
            APP.save_settings()
            return APP.settings
        if path == "/api/process":
            return APP.process(b, b.get("hidden"), light=bool(b.get("light")))
        if path == "/api/connect":
            S["connection"] = {"port": b["port"], "baud": int(b.get("baud", 115200))}
            APP.save_settings()
            try:
                M.connect(b["port"], b.get("baud", 115200))
            except Exception as e:
                M.disconnect()
                return {"error": f"Connection failed: {e}. Is the UUNA software or a second Nib still running?"}
            return {"ok": True}
        if path == "/api/disconnect":
            M.disconnect()
            return {"ok": True}

        if not M.connected:
            return {"error": "Plotter not connected"}

        # real-time commands always work
        if path == "/api/feedhold":
            M.realtime(b"!")
            return {"ok": True}
        if path == "/api/job/pause":
            APP.job and APP.job.pause()
            return {"ok": True}
        if path == "/api/job/resume":
            APP.job and APP.job.resume()
            return {"ok": True}
        if path == "/api/job/stop":
            if APP.job:
                APP.job.abort(mset["z_up"], mset["z_feed"])
            return {"ok": True}
        if path == "/api/reset":
            M.soft_reset_keep_origin(mset["z_up"], mset["z_feed"])
            return {"ok": True}
        if path == "/api/job/start":
            return APP.start_job(b)

        # during a pen change, jogging, moving the pen and resetting the origin are allowed
        changing = APP.job and APP.job.state == "pen_change"
        if busy and not (changing and path in (
                "/api/jog", "/api/jog/cancel", "/api/pen", "/api/zero", "/api/goto_zero")):
            return {"error": "Not possible while plotting"}

        if path == "/api/command":
            for line in str(b.get("gcode", "")).replace(";", "\n").splitlines():
                if line.strip():
                    M.send(line)
            return {"ok": True}
        if path == "/api/jog":
            dx, dy = float(b.get("x", 0)), float(b.get("y", 0))
            if mset.get("limits_on", True) and (dx or dy):
                # current position in sheet coordinates, clamp the target to the work area
                wx, wy = M.status()["wpos"][:2]
                cx, cy = G.from_machine(wx, wy, mset)
                ax0, ay0, ax1, ay1 = allowed_area(mset, M)
                # if already outside, only allow moves back into the area
                tx = min(max(cx + dx, min(ax0, cx)), max(ax1, cx))
                ty = min(max(cy + dy, min(ay0, cy)), max(ay1, cy))
                if abs(tx - (cx + dx)) > 1e-6 or abs(ty - (cy + dy)) > 1e-6:
                    M._log("warn", f"Jog stopped at the limit (allowed X {ax0:.1f}–{ax1:.1f}, "
                                   f"Y {ay0:.1f}–{ay1:.1f} mm from origin)")
                dx, dy = tx - cx, ty - cy
            mx, my = G.to_machine(dx, dy, mset)
            parts = []
            if mx:
                parts.append(f"X{mx:.3f}")
            if my:
                parts.append(f"Y{my:.3f}")
            if b.get("z"):
                dz = float(b["z"])
                zl = M.z_limits() if mset.get("limits_on", True) else None
                if zl:
                    cz = M.status()["wpos"][2]
                    tz = min(max(cz + dz, min(zl[0], cz)), max(zl[1], cz))
                    if abs(tz - (cz + dz)) > 1e-6:
                        M._log("warn", f"Z stopped at the limit (allowed {zl[0]:.2f} to {zl[1]:.2f} mm)")
                    dz = tz - cz
                if abs(dz) > 1e-6:
                    parts.append(f"Z{dz:.3f}")
            if parts:
                M.send(f"$J=G21G91{''.join(parts)}F{int(mset['jog_feed'])}", tag=None)
            return {"ok": True}
        if path == "/api/jog/cancel":
            M.realtime(b"\x85")
            return {"ok": True}
        if path == "/api/pen":
            z = mset["z_down"] if b.get("down") else mset["z_up"]
            err = M.z_check(z)
            if err:
                return {"error": err}
            M.send(f"G90 G1 Z{z} F{int(mset['z_feed'])}", tag=None)
            return {"ok": True}
        if path == "/api/zero":
            if changing and mset.get("limits_on", True):
                # the plot must still fit the work area with the new origin
                st = M.status()
                err = check_limits(APP.doc["bbox"], APP.job.place, mset, M, wco_xy=st["mpos"][:2])
                if err:
                    return {"error": "Can't set the origin here – " + err}
            M.send("G92 X0 Y0", tag="console")
            if changing:
                M._log("info", "Origin reset during pen change")
            M.zero_set = True
            return {"ok": True}
        if path in ("/api/goto_zero", "/api/goto_machine_zero"):
            # raise the pen (configured height if valid, otherwise all the way up)
            lift = (f"G90 G1 Z{mset['z_up']} F{int(mset['z_feed'])}" if M.z_check(mset["z_up"]) is None
                    else f"G90 G53 G1 Z0 F{int(mset['z_feed'])}")
            if path == "/api/goto_zero":
                move = f"G1 X0 Y0 F{int(mset['feed_travel'])}"
            else:
                # G53 = machine coordinates -> power-on position, the origin stays unchanged
                move = f"G53 G1 X0 Y0 F{int(mset['feed_travel'])}"
                M._log("info", "Moving to machine home (power-on position)")
            M.queue_lines([lift, move], None)
            return {"ok": True}
        if path == "/api/unlock":
            if M.state.startswith("Alarm"):
                # this firmware requires a reset after an alarm ("Reset to continue").
                # the origin is kept.
                M._log("info", "Clearing alarm (reset, origin is kept)…")
                M.soft_reset_keep_origin(mset["z_up"], mset["z_feed"])
            else:
                M.send("$X")
            return {"ok": True}
        if path == "/api/frame":
            if APP.doc is None:
                return {"error": "No file loaded"}
            place = b.get("place", S["place"])
            err = check_limits(APP.doc["bbox"], place, mset, M) or M.z_check(mset["z_up"])
            if err:
                return {"error": err}
            M.queue_lines(G.frame_gcode(APP.doc["bbox"], place, mset), None)
            M._log("info", "Tracing the frame (pen up)")
            return {"ok": True}
        if path == "/api/hatch_test":
            return hatch_test(b, mset, M)
        return {"error": f"Unknown command {path}"}


def hatch_test(b, m, machine):
    """Plot the hatch test strip with its top-left corner at the current pen position:
    one square per spacing, with the current pen heights and speeds."""
    try:
        angle = float(b.get("angle", 45)) % 180
    except (TypeError, ValueError):
        angle = 45.0
    cross = b.get("mode") == "cross"
    join = b.get("join", True) is not False
    wx, wy = machine.status()["wpos"][:2]
    x, y = G.from_machine(wx, wy, m)
    w, h = H.test_strip_size()
    if m.get("limits_on", True):
        ax0, ay0, ax1, ay1 = allowed_area(m, machine)
        if x < ax0 - 0.01 or y < ay0 - 0.01 or x + w > ax1 + 0.01 or y + h > ay1 + 0.01:
            return {"error": f"The test strip ({w:.0f} × {h:.0f} mm, drawn to the right of and below "
                             f"the pen) doesn't fit here. Move the pen to a free spot first."}
    err = machine.z_check(m["z_up"]) or machine.z_check(m["z_down"])
    if err:
        return {"error": err}
    gb = G.GcodeBuilder(m)
    gb.header()
    gb.layer(0, H.test_strip(x, y, angle, cross, join=join), lambda px, py: (px, py))
    gb.pen_up()
    sx, sy = G.to_machine(x, y, m)
    gb.emit(f"G1 X{G._fmt(sx)} Y{G._fmt(sy)} F{int(m['feed_travel'])}")   # back to where it started
    machine.queue_lines([line for line, _ in gb.lines], None)
    machine._log("info", f"Plotting the hatch test strip ({w:.0f} × {h:.0f} mm): spacings "
                         + ", ".join(f"{s:g}" for s in H.TEST_SPACINGS) + " mm")
    return {"ok": True, "spacings": list(H.TEST_SPACINGS)}


def _job_busy():
    return bool(APP.job and APP.job.state in ("running", "paused", "pen_change"))


def watchdog(srv):
    """Shuts the server down when no browser window is open any more – never during a plot."""
    told = False
    while True:
        time.sleep(1)
        if _job_busy():
            if LIFE["bye_at"] and LIFE["last_poll"] < LIFE["bye_at"] and not told:
                print("Browser closed – the plot continues, Nib exits afterwards.")
                told = True
            continue
        now = time.time()
        closed = LIFE["bye_at"] and LIFE["last_poll"] < LIFE["bye_at"] and now - LIFE["bye_at"] > BYE_GRACE
        lost = LIFE["seen"] and now - LIFE["last_poll"] > NO_POLL_LIMIT
        if closed or lost:
            print("Browser closed – Nib is exiting.")
            srv.shutdown()
            return


class _Server(ThreadingHTTPServer):
    # bind the port exclusively: on Windows SO_REUSEADDR would otherwise let a second
    # Nib bind the same port – requests then end up at the wrong program.
    allow_reuse_address = False

    def server_bind(self):
        import socket
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(port=PORT, fallback=False):
    """Create the HTTP server. With fallback=True a free port is used if the port is taken."""
    try:
        return _Server(("127.0.0.1", port), Handler)
    except OSError:
        if not fallback:
            raise
        return _Server(("127.0.0.1", 0), Handler)


def main():
    no_browser = "--no-browser" in sys.argv
    port = PORT
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    srv = make_server(port)
    url = f"http://127.0.0.1:{port}/"
    print(f"Nib running at {url}  (Ctrl+C to quit)")
    if not no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    if "--keep-running" not in sys.argv:
        threading.Thread(target=watchdog, args=(srv,), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        APP.machine.disconnect()


if __name__ == "__main__":
    main()
