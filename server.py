"""Nib – lokaler Webserver für den GRBL-Stiftplotter.

Start:  python server.py           (öffnet den Browser auf http://127.0.0.1:8765)
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import mimetypes
import os
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

import gcode as G
import optimize as O
from grbl import Job, Machine, list_ports
from svgload import load_svg

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
SETTINGS_FILE = os.path.join(HERE, "settings.json")
JOBSTATE_FILE = os.path.join(HERE, "job_state.json")
PORT = 8765

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


def allowed_area(m, machine=None):
    """Erlaubter Bereich in Blattkoordinaten (x0, y0, x1, y1), gemessen ab dem Nullpunkt.

    Sind die Firmware-Grenzen des Plotters bekannt ($130/$131 bei $20=1), gelten nur diese.
    Ohne Referenzfahrt zählen sie ab der Einschaltposition (Maschinenkoordinate 0..max) und
    werden über den Nullpunkt-Versatz (WCO) umgerechnet – der Nullpunkt darf also überall liegen.
    Sonst (z. B. Simulator, Achsen gedreht): 0..max_x / 0..max_y ab Nullpunkt.
    """
    ux, uy = float(m["max_x"]), float(m["max_y"])
    if machine is not None and machine.connected and not (
            m.get("invert_x") or m.get("invert_y") or m.get("swap_xy")):
        st = machine.status()
        wco = st.get("wco")
        if wco:
            # Arbeitsbereich (Einstellung) gilt ab Maschinen-Nullpunkt = Einschaltecke,
            # zusätzlich zur Firmware-Grenze – der kleinere Wert gewinnt.
            # (Die Firmware-Grenze 297 mm ist größer als der echte Y-Weg -> Anschlag.)
            fx, fy = st.get("fw_max") or (None, None)
            mx = min(ux, fx) if (st.get("fw_soft_limits") and fx) else ux
            my = min(uy, fy) if (st.get("fw_soft_limits") and fy) else uy
            wx, wy = wco[0], wco[1]
            return -wx, -wy, mx - wx, my - wy
    return 0.0, 0.0, ux, uy


SPEED_NAMES = {"feed_draw": "Zeichnen", "feed_travel": "Leerfahrt", "jog_feed": "Verfahren", "z_feed": "Z"}


def speed_limits(fw):
    """(max. X/Y, max. Z) in mm/min aus $110/$111/$112, oder (None, None)."""
    if not fw or not (fw.get(110) and fw.get(111)):
        return None, None
    return min(fw[110], fw[111]), fw.get(112)


def clamp_speeds(m, fw):
    """Geschwindigkeiten auf das Firmware-Maximum begrenzen. Gibt geänderte Felder zurück."""
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


def check_limits(bbox, place, m, machine=None):
    """Fehlermeldung, wenn das platzierte Design den erlaubten Bereich verlässt, sonst None."""
    if not m.get("limits_on", True):
        return None
    w, h = G.placed_size(bbox, place)
    x, y = float(place.get("x", 0)), float(place.get("y", 0))
    ax0, ay0, ax1, ay1 = allowed_area(m, machine)
    eps = 0.01
    if x < ax0 - eps or y < ay0 - eps or x + w > ax1 + eps or y + h > ay1 + eps:
        return (f"Design liegt außerhalb der Maschinengrenzen (erlaubt X {ax0:.1f} bis {ax1:.1f}, "
                f"Y {ay0:.1f} bis {ay1:.1f} mm ab Nullpunkt): belegt X {x:.1f}–{x + w:.1f}, "
                f"Y {y:.1f}–{y + h:.1f} mm. Bitte verschieben/verkleinern oder den Nullpunkt prüfen.")
    return None


def _color_name(hexcol, names):
    """Farbebene benennen, z. B. 'hatch Y' -> 'Y (#f5d000)'."""
    top = sorted(names.items(), key=lambda kv: -kv[1])
    if top and top[0][0] not in ("Ohne Ebene",) and not top[0][0].startswith("Gruppe "):
        label = top[0][0]
        if len(top) > 1:
            label += f" +{len(top) - 1}"
        return f"{label}  {hexcol}"
    return f"Farbe {hexcol}"


class App:
    def __init__(self):
        self.settings = deep_merge(DEFAULTS, load_json(SETTINGS_FILE, {}))
        self.machine = Machine()
        self.machine.on_fw = self._fw_received
        self.job: Job | None = None
        self.raw = None           # LoadResult
        self.file_name = ""
        self.file_hash = ""
        self.doc = None           # verarbeitete Ebenen
        self.doc_lock = threading.Lock()
        self._last_save = 0.0

    def _fw_received(self, fw):
        """Arbeitsbereich aus der Plotter-Firmware übernehmen ($130/$131)."""
        fx, fy = fw.get(130), fw.get(131)
        m = self.settings["machine"]
        # Nur verkleinern: ein selbst gemessener (kleinerer) Arbeitsbereich bleibt erhalten.
        nx, ny = min(m["max_x"], fx), min(m["max_y"], fy)
        if (m["max_x"], m["max_y"]) != (nx, ny):
            m["max_x"], m["max_y"] = nx, ny
            self.save_settings()
        self.machine._log("info", f"Arbeitsbereich laut Plotter-Firmware: {fx:g} × {fy:g} mm"
                          + (" – Software-Endschalter aktiv, gelten ab der Einschaltposition"
                             if fw.get(20) else ""))
        vxy, vz = speed_limits(fw)
        if vxy:
            self.machine._log("info", f"Max. Geschwindigkeit laut Firmware: X/Y {vxy:g} mm/min, Z {vz:g} mm/min")
        changed = clamp_speeds(m, fw)
        if changed:
            self.save_settings()
            self.machine._log("warn", "Auf Firmware-Maximum begrenzt: " + ", ".join(changed))

    # ------------------------------------------------------------ Dokument
    def upload(self, name, data: bytes):
        res = load_svg(io.BytesIO(data), float(self.settings["optimize"]["curve_step"]))
        with self.doc_lock:
            self.raw = res
            self.file_name = name
            self.file_hash = hashlib.sha1(data).hexdigest()
        return self.process(self.settings["optimize"])

    def process(self, opts):
        self.settings["optimize"] = deep_merge(self.settings["optimize"], opts)
        self.save_settings()
        opts = self.settings["optimize"]
        if self.raw is None:
            return {"error": "Keine Datei geladen"}
        t0 = time.time()
        polys = self.raw.polylines
        mode = opts.get("group", "auto")
        if mode == "auto":
            ncol = len({p.color for p in polys})
            nlay = len({p.layer for p in polys})
            mode = "color" if 2 <= ncol <= 12 else ("layer" if nlay > 1 else "color")
        groups = {}
        order = []
        for p in polys:
            key = p.layer if mode == "layer" else (p.color if mode == "color" else "Alle")
            if key not in groups:
                groups[key] = {"paths": [], "colors": {}}
                order.append(key)
            groups[key]["paths"].append(p.pts)
            groups[key]["colors"][p.color] = groups[key]["colors"].get(p.color, 0) + 1
            groups[key].setdefault("names", {})
            nm = p.layer.rstrip("0123456789 ").strip() or p.layer
            groups[key]["names"][nm] = groups[key]["names"].get(nm, 0) + 1

        allx = [x for p in polys for x, _ in p.pts] or [0]
        ally = [y for p in polys for _, y in p.pts] or [0]
        bbox = [min(allx), min(ally), max(allx), max(ally)]

        layers = []
        for i, key in enumerate(order):
            g = groups[key]
            paths = O.optimize(g["paths"], opts, start=(bbox[0], bbox[1]))
            if not paths:
                continue
            st = O.stats(paths, start=(bbox[0], bbox[1]))
            color = max(g["colors"].items(), key=lambda kv: kv[1])[0]
            layers.append({
                "id": f"L{i}", "name": str(key) if mode != "color" else _color_name(key, g["names"]),
                "color": color, "count": len(paths), "points": sum(len(p) for p in paths),
                "paths": paths, **st,
            })
        with self.doc_lock:
            self.doc = {"name": self.file_name, "hash": self.file_hash, "bbox": bbox,
                        "layers": layers, "mode": mode, "warnings": list(self.raw.warnings),
                        "opts": copy.deepcopy(opts),
                        "width_mm": self.raw.width_mm, "height_mm": self.raw.height_mm}
        return self.doc_json(time.time() - t0)

    def doc_json(self, took=0.0):
        d = self.doc
        if d is None:
            return {"doc": None}
        layers = []
        for l in d["layers"]:
            flat = [[round(c, 2) for pt in p for c in pt] for p in l["paths"]]
            layers.append({k: v for k, v in l.items() if k != "paths"} | {"paths": flat})
        return {"doc": {k: v for k, v in d.items() if k != "layers"} | {"layers": layers},
                "took": round(took, 2), "resume": self.resume_info()}

    # ---------------------------------------------------------- Einstellungen
    def save_settings(self):
        try:
            save_json(SETTINGS_FILE, self.settings)
        except Exception:
            traceback.print_exc()

    def resume_info(self):
        st = load_json(JOBSTATE_FILE, None)
        if not st or not self.doc:
            return None
        if st.get("hash") != self.doc["hash"] or st.get("opts") != self.doc["opts"]:
            return None
        if st.get("finished"):
            return None
        return st

    def save_progress(self, job, force=False, finished=False):
        if not force and time.time() - self._last_save < 2:
            return
        self._last_save = time.time()
        li, pi = job.resume_point()
        try:
            save_json(JOBSTATE_FILE, {
                "hash": self.doc["hash"], "opts": self.doc["opts"], "name": self.doc["name"],
                "layer_ids": job.layer_ids, "layer": li, "path": pi,
                "layer_name": job.layers[li]["name"] if li < len(job.layers) else "",
                "place": job.place, "reverse": getattr(job, "reverse", False), "finished": finished, "time": time.strftime("%d.%m.%Y %H:%M"),
            })
        except Exception:
            traceback.print_exc()

    # ------------------------------------------------------------------ Job
    def start_job(self, body):
        if self.job and self.job.state in ("läuft", "pausiert", "stiftwechsel"):
            return {"error": "Es läuft bereits ein Plot"}
        if not self.machine.connected:
            return {"error": "Plotter nicht verbunden"}
        if self.doc is None:
            return {"error": "Keine Datei geladen"}
        m = self.settings["machine"]
        place = body.get("place", self.settings["place"])
        by_id = {l["id"]: l for l in self.doc["layers"]}
        ids = [i for i in body.get("layers", []) if i in by_id]
        if not ids:
            return {"error": "Keine Ebene ausgewählt"}
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

        sl = int(body.get("start_layer", 0))
        sp = body.get("start_path")
        sp = None if sp is None else int(sp)
        meta = [{"id": l["id"], "name": l["name"], "color": l["color"], "count": l["count"]}
                for l in layers]
        job = Job(self.machine, meta, build_layer, header, footer, sl, sp,
                  pen_change=bool(self.settings["job"]["pen_change"]),
                  on_progress=lambda j: self.save_progress(j))
        job.layer_ids = ids
        job.place = place
        job.reverse = reverse
        self.job = job
        self.settings["place"] = place
        self.save_settings()
        job.start()
        self.machine._log("info", f"Plot gestartet: {self.doc['name']} – {len(layers)} Ebene(n)"
                          + (" – rückwärts" if reverse else "")
                          + (f", ab Ebene {sl + 1} Pfad {sp + 1}" if sp is not None else ""))
        threading.Thread(target=self._watch_job, args=(job,), daemon=True).start()
        return {"ok": True}

    def _watch_job(self, job):
        while job.state in ("läuft", "pausiert", "stiftwechsel"):
            time.sleep(0.5)
        self.save_progress(job, force=True, finished=(job.state == "fertig"))

    def job_info(self):
        if not self.job:
            return None
        info = self.job.info()
        info["layers"] = self.job.layers
        info["layer_ids"] = self.job.layer_ids
        info["reverse"] = getattr(self.job, "reverse", False)
        return info


APP = App()


class Handler(BaseHTTPRequestHandler):
    server_version = "Nib/1.0"

    def log_message(self, *a):
        pass

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
        path = urlparse(self.path).path
        try:
            if path == "/api/status":
                q = urlparse(self.path).query
                since = int(q.split("log=")[1]) if "log=" in q else 0
                return self._json({"machine": APP.machine.status(), "job": APP.job_info(),
                                   "area": allowed_area(APP.settings["machine"], APP.machine),
                                   "mset": APP.settings["machine"],
                                   "vmax": speed_limits(APP.machine.fw),
                                   "log": APP.machine.log_since(since)})
            if path == "/api/ports":
                return self._json({"ports": list_ports()})
            if path == "/api/settings":
                return self._json(APP.settings)
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
        path = urlparse(self.path).path
        try:
            if path == "/api/upload":
                name = unquote(self.headers.get("X-Filename", "datei.svg"))
                return self._json(APP.upload(name, self._body()))
            body = json.loads(self._body() or b"{}")
            return self._json(self.route(path, body))
        except Exception as e:
            traceback.print_exc()
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def route(self, path, b):
        M = APP.machine
        S = APP.settings
        mset = S["machine"]
        busy = APP.job and APP.job.state in ("läuft", "pausiert", "stiftwechsel")

        if path == "/api/settings":
            APP.settings = deep_merge(S, b)
            changed = clamp_speeds(APP.settings["machine"], M.fw)
            if changed:
                M._log("warn", "Auf Firmware-Maximum begrenzt: " + ", ".join(changed))
            APP.save_settings()
            return APP.settings
        if path == "/api/process":
            return APP.process(b)
        if path == "/api/connect":
            S["connection"] = {"port": b["port"], "baud": int(b.get("baud", 115200))}
            APP.save_settings()
            try:
                M.connect(b["port"], b.get("baud", 115200))
            except Exception as e:
                M.disconnect()
                return {"error": f"Verbindung fehlgeschlagen: {e}. Läuft die UUNA-Software noch?"}
            return {"ok": True}
        if path == "/api/disconnect":
            M.disconnect()
            return {"ok": True}

        if not M.connected:
            return {"error": "Plotter nicht verbunden"}

        # Echtzeit-Befehle gehen immer
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

        if busy:
            return {"error": "Während eines Plots nicht möglich"}

        if path == "/api/command":
            for line in str(b.get("gcode", "")).replace(";", "\n").splitlines():
                if line.strip():
                    M.send(line)
            return {"ok": True}
        if path == "/api/jog":
            dx, dy = float(b.get("x", 0)), float(b.get("y", 0))
            if mset.get("limits_on", True) and (dx or dy):
                # aktuelle Position in Blattkoordinaten, Ziel auf Arbeitsbereich begrenzen
                wx, wy = M.status()["wpos"][:2]
                cx, cy = G.from_machine(wx, wy, mset)
                ax0, ay0, ax1, ay1 = allowed_area(mset, M)
                # Wenn man schon außerhalb steht, nur Bewegung zurück in den Bereich zulassen
                tx = min(max(cx + dx, min(ax0, cx)), max(ax1, cx))
                ty = min(max(cy + dy, min(ay0, cy)), max(ay1, cy))
                if abs(tx - (cx + dx)) > 1e-6 or abs(ty - (cy + dy)) > 1e-6:
                    M._log("warn", f"Verfahren an der Grenze gestoppt (erlaubt X {ax0:.1f}–{ax1:.1f}, "
                                   f"Y {ay0:.1f}–{ay1:.1f} mm ab Nullpunkt)")
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
                        M._log("warn", f"Z an der Grenze gestoppt (erlaubt {zl[0]:.2f} bis {zl[1]:.2f} mm)")
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
            M.send("G92 X0 Y0", tag="console")
            M.zero_set = True
            return {"ok": True}
        if path in ("/api/goto_zero", "/api/goto_machine_zero"):
            # Stift anheben (eingestellte Höhe, falls gültig, sonst ganz nach oben)
            lift = (f"G90 G1 Z{mset['z_up']} F{int(mset['z_feed'])}" if M.z_check(mset["z_up"]) is None
                    else f"G90 G53 G1 Z0 F{int(mset['z_feed'])}")
            if path == "/api/goto_zero":
                move = f"G1 X0 Y0 F{int(mset['feed_travel'])}"
            else:
                # G53 = Maschinenkoordinaten -> Einschaltposition, Nullpunkt bleibt unverändert
                move = f"G53 G1 X0 Y0 F{int(mset['feed_travel'])}"
                M._log("info", "Fahre zum Maschinen-Nullpunkt (Einschaltposition)")
            M.queue_lines([lift, move], None)
            return {"ok": True}
        if path == "/api/unlock":
            if M.state.startswith("Alarm"):
                # Diese Firmware verlangt nach einem Alarm einen Reset ("Reset to continue").
                # Nullpunkt bleibt dabei erhalten.
                M._log("info", "Alarm wird aufgehoben (Reset, Nullpunkt bleibt erhalten)…")
                M.soft_reset_keep_origin(mset["z_up"], mset["z_feed"])
            else:
                M.send("$X")
            return {"ok": True}
        if path == "/api/area_from_pos":
            # Aktuelle Position (ab Einschaltecke) als Grenze übernehmen, abzüglich Reserve
            axis = b.get("axis")
            if axis not in ("x", "y"):
                return {"error": "Achse fehlt"}
            if not M.connected:
                return {"error": "Nicht verbunden"}
            reserve = float(b.get("reserve", 1.0))
            sx, sy = G.from_machine(*M.status()["mpos"][:2], mset)
            v = round(abs(sx if axis == "x" else sy) - reserve, 1)
            if v < 10:
                return {"error": f"Position {axis.upper()} {v + reserve:.1f} mm ist zu klein für eine Grenze"}
            mset[f"max_{axis}"] = v
            APP.save_settings()
            M._log("info", f"Arbeitsbereich: Max. {axis.upper()} = {v:g} mm "
                           f"(Position {v + reserve:.1f} mm − {reserve:g} mm Reserve)")
            return {"ok": True, "value": v}
        if path == "/api/area_open":
            # Zum Ausmessen: Grenze vorübergehend auf das Firmware-Maximum öffnen
            fx, fy = M.status().get("fw_max") or (None, None)
            mset["max_x"], mset["max_y"] = fx or 420.0, fy or 297.0
            APP.save_settings()
            M._log("warn", f"Arbeitsbereich zum Ausmessen geöffnet: {mset['max_x']:g} × {mset['max_y']:g} mm "
                           "– nur in kleinen Schritten zum Anschlag joggen!")
            return {"ok": True}
        if path == "/api/frame":
            if APP.doc is None:
                return {"error": "Keine Datei geladen"}
            place = b.get("place", S["place"])
            err = check_limits(APP.doc["bbox"], place, mset, M) or M.z_check(mset["z_up"])
            if err:
                return {"error": err}
            M.queue_lines(G.frame_gcode(APP.doc["bbox"], place, mset), None)
            M._log("info", "Rahmen wird abgefahren (Stift oben)")
            return {"ok": True}
        return {"error": f"Unbekannter Befehl {path}"}


def main():
    no_browser = "--no-browser" in sys.argv
    port = PORT
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Nib läuft auf {url}  (Beenden mit Strg+C)")
    if not no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        APP.machine.disconnect()


if __name__ == "__main__":
    main()
