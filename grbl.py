"""GRBL-Verbindung, Streaming (Zeichenzähl-Protokoll) und Plot-Auftrag."""
from __future__ import annotations

import collections
import re
import threading
import time

import serial
import serial.tools.list_ports

from mockgrbl import MockSerial

RX_BUFFER = 127          # GRBL Standard: 128 Byte Empfangspuffer
SIM_PORT = "SIMULATOR"
STATUS_RE = re.compile(r"<([^|>]+)\|(.*)>")


def list_ports():
    out = []
    for p in serial.tools.list_ports.comports():
        out.append({"port": p.device, "desc": p.description})
    out.append({"port": SIM_PORT, "desc": "Simulierter Plotter (zum Testen)"})
    return out


class Machine:
    def __init__(self):
        self.ser = None
        self.port = None
        self.lock = threading.RLock()
        self._wlock = threading.Lock()
        self.fw = {}
        self.zero_set = False
        self.cv = threading.Condition(self.lock)
        self.pending = collections.deque()     # (zeile, tag)
        self.inflight = collections.deque()    # (laenge, zeile, tag)
        self.log = collections.deque(maxlen=400)
        self.log_seq = 0
        self.state = "Getrennt"
        self.mpos = [0.0, 0.0, 0.0]
        self.wco = [0.0, 0.0, 0.0]
        self.feed = 0
        self.status_seq = 0
        self.version = ""
        self.last_alarm = ""
        self.banner_event = threading.Event()
        self._running = False
        self.on_ack = None        # callback(tag)
        self.on_error = None      # callback(text)
        self.on_alarm = None      # callback(text)
        self.on_reset = None      # callback()
        self.on_fw = None         # callback(fw) wenn $130/$131 gelesen
        self._last_ok_t = 0.0     # Zeitpunkt des letzten 'ok'
        self._idle_since = None   # seit wann der Plotter 'Idle' meldet
        self._raw = collections.deque(maxlen=300)   # letzte Zeilen (Zeit, rx/tx, Text) für Diagnose
        self._anomalies = 0       # Antworten mit angehängtem/eingeschobenem Text
        self._odd = collections.deque(maxlen=200)   # auffällige Zeilen (Zeit, Text)
        self.lost_acks_total = 0
        self._diag_count = 0

    # ------------------------------------------------------------------ log
    def _log(self, kind, text):
        with self.lock:
            last = self.log[-1] if self.log else None
            if last and last["k"] == kind and last["m"] == text and time.time() - last.get("ts", 0) < 5:
                return  # gleiche Meldung nicht mehrfach hintereinander
            self.log_seq += 1
            self.log.append({"n": self.log_seq, "t": time.strftime("%H:%M:%S"), "k": kind, "m": text, "ts": time.time()})

    # ----------------------------------------------------------- verbinden
    def connect(self, port, baud=115200):
        self.disconnect()
        if port == SIM_PORT:
            ser = MockSerial()
        else:
            ser = serial.Serial(port, int(baud), timeout=0.1, write_timeout=2)
        self.ser = ser
        self.port = port
        self.banner_event.clear()
        self.zero_set = False
        self.fw = {}
        self._running = True
        self.state = "Verbinde…"
        threading.Thread(target=self._reader, daemon=True).start()
        # Manche Boards starten beim Öffnen neu und schicken ein Banner. Der UUNA-Plotter
        # tut das nicht -> mit '$I' nach der Version fragen (kein Reset, nichts bewegt sich).
        if not self.banner_event.wait(1.5):
            self._write(b"\r\n")
            time.sleep(0.2)
            self._write(b"$I\n")
            self.banner_event.wait(2.0)
        threading.Thread(target=self._sender, daemon=True).start()
        threading.Thread(target=self._poller, daemon=True).start()
        self._log("info", f"Verbunden mit {port}" + (f" ({self.version})" if self.version else ""))
        if not self.version:
            self._log("warn", "Plotter antwortet nicht – ist die richtige COM-Schnittstelle gewählt "
                              "und die UUNA-Software geschlossen?")
        # Firmware-Einstellungen (u. a. max. Verfahrweg $130/$131) lesen
        self.send("$$", tag=None)
        return True

    def disconnect(self):
        self._running = False
        with self.cv:
            self.pending.clear()
            self.inflight.clear()
            self.cv.notify_all()
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
        if self.port:
            self._log("info", "Verbindung getrennt")
        self.ser = None
        self.port = None
        self.state = "Getrennt"
        self.version = ""

    @property
    def connected(self):
        return self.ser is not None and self._running

    def _write(self, data: bytes):
        s = self.ser
        if s is None:
            return
        try:
            with self._wlock:
                s.write(data)
        except Exception as e:
            self._log("err", f"Schreibfehler: {e}")
            self._running = False
            self.state = "Getrennt"

    # --------------------------------------------------------------- threads
    def _reader(self):
        # readline() liefert bei Timeout auch halbe Zeilen (z. B. "o" … "k"). Deshalb sammeln
        # und nur vollständige Zeilen auswerten – sonst gehen 'ok' verloren und der Plot bleibt stehen.
        buf = b""
        while self._running and self.ser is not None:
            try:
                raw = self.ser.readline()
            except Exception as e:
                self._log("err", f"Lesefehler: {e} – Verbindung verloren")
                self._running = False
                self.state = "Getrennt"
                break
            if not raw:
                continue
            buf += raw
            while b"\n" in buf:
                one, buf = buf.split(b"\n", 1)
                line = one.decode(errors="ignore").strip()
                if line:
                    self._raw.append((time.time(), "rx", line))
                    self._handle_line(line)
            if len(buf) > 4096:          # Müll ohne Zeilenende verwerfen
                buf = b""

    def _handle_line(self, line):
        if True:
            if line != "ok" and (line.startswith("<") or line.startswith("ok")):
                # Statusmeldung und 'ok' können ineinander geschrieben sein, z. B.
                # "<Run|...>ok", "ok<Run|...>", "<Run|MPos:..|okFS:..>", "okok".
                # In Statusmeldungen kommt "ok" sonst nie vor -> jedes "ok" ist eine Bestätigung.
                n_ok = line.count("ok")
                rest = line.replace("ok", "")
                if rest.startswith("error"):
                    self._anomalies += 1
                    self._odd.append((time.strftime("%H:%M:%S"), line))
                    for _ in range(n_ok):
                        self._handle_line("ok")
                    self._handle_line(rest)
                    return
                st = rest.find("<")
                if st >= 0:
                    end = rest.find(">", st)
                    if end > st:
                        self._parse_status(rest[st:end + 1])
                    elif re.fullmatch(r"<[A-Za-z]+(:\d)?(\|[A-Za-z]+:[-\d.,]+)*", rest[st:].strip()):
                        self._parse_status(rest[st:].strip() + ">")   # nur das '>' fehlt
                    leftover = (rest[:st] + (rest[end + 1:] if end > st else "")).strip()
                else:
                    leftover = rest.strip()
                if line.startswith("<") and line.endswith(">") and n_ok == 0 and line.count("<") == 1:
                    return                                   # normale Statusmeldung
                self._anomalies += 1
                self._odd.append((time.strftime("%H:%M:%S"), line))
                for _ in range(n_ok):
                    self._handle_line("ok")
                if leftover and leftover.startswith(("[", "ALARM", "$")):
                    self._handle_line(leftover)
                return
            elif line == "ok" or line.startswith("error"):
                with self.cv:
                    item = self.inflight.popleft() if self.inflight else None
                    self._last_ok_t = time.time()
                    self.cv.notify_all()
                if line.startswith("error"):
                    sent = item[1] if item else "?"
                    msg = f"{line} bei Zeile: {sent}"
                    self._log("err", msg)
                    if self.on_error:
                        self.on_error(msg)
                elif item and item[2] == "console":
                    self._log("ok", f"ok ({item[1]})")
                if item and self.on_ack:
                    self.on_ack(item[2])
            elif line.startswith("ALARM"):
                self.last_alarm = line
                self.state = "Alarm"
                self._log("err", f"{line} – mit 'Entsperren' freigeben")
                with self.cv:
                    self.pending.clear()
                    self.cv.notify_all()
                if self.on_alarm:
                    self.on_alarm(line)
            elif line.startswith("[VER:"):
                self.version = line[5:].split(":")[0].strip()
                self.banner_event.set()
            elif re.match(r"^\$\d+=", line):
                k, v = line[1:].split("=", 1)
                try:
                    self.fw[int(k)] = float(v)
                except ValueError:
                    pass
                if int(k) in (130, 131) and self.fw.get(130) and self.fw.get(131) and self.on_fw:
                    self.on_fw(self.fw)
            elif line.lower().startswith("grbl") or (not line.startswith("[") and "uuna" in line.lower()):
                self.version = line.split("[")[0].strip()
                with self.cv:
                    self.inflight.clear()
                    self.cv.notify_all()
                self.banner_event.set()
                self._log("info", f"Controller gestartet: {line}")
                if self.on_reset:
                    self.on_reset()
            else:
                self._log("rx", line)

    def _parse_status(self, line):
        m = STATUS_RE.match(line)
        if not m:
            return
        self.status_seq += 1
        self.state = m.group(1)
        if self.state.startswith("Idle"):
            if self._idle_since is None:
                self._idle_since = time.time()
        else:
            self._idle_since = None
        for field in m.group(2).split("|"):
            if ":" not in field:
                continue
            k, v = field.split(":", 1)
            try:
                nums = [float(x) for x in v.split(",")]
            except ValueError:
                continue
            if k == "MPos":
                self.mpos = (nums + [0, 0, 0])[:3]
            elif k == "WPos":
                self.mpos = [(nums + [0, 0, 0])[i] + self.wco[i] for i in range(3)]
            elif k == "WCO":
                self.wco = (nums + [0, 0, 0])[:3]
            elif k in ("FS", "F"):
                self.feed = nums[0]

    def _poller(self):
        while self._running:
            self._write(b"?")
            time.sleep(0.2)
            self._check_lost_acks()

    LOST_ACK_WAIT = 0.8   # s Stillstand, ab dem fehlende 'ok' angenommen werden

    def _check_lost_acks(self):
        """Sicherheitsnetz: Ist der Plotter *nach* dem Senden des ältesten offenen Befehls in
        den Stillstand (Idle) gegangen und kam seit LOST_ACK_WAIT kein 'ok' mehr, hat er alle
        Befehle ausgeführt (nachgemessen: Stiftposition = Ziel des zuletzt gesendeten Befehls),
        nur die Bestätigungen fehlen. Dann den Zähler freigeben, damit es sofort weitergeht."""
        now = time.time()
        w = self.LOST_ACK_WAIT
        with self.cv:
            if not self.inflight or not self.state.startswith("Idle"):
                return
            oldest = self.inflight[0][3]
            if (self._idle_since is None or self._idle_since <= oldest
                    or now - self._idle_since < w or now - self._last_ok_t < w):
                return
            n = len(self.inflight)
            pend = [i[1] for i in self.inflight]
            self.inflight.clear()
            self.cv.notify_all()
            raw = list(self._raw)
        self.lost_acks_total += n
        self._log("warn", f"{n} Bestätigung(en) vom Plotter fehlten – weiter (insgesamt {self.lost_acks_total})")
        self._write_diag(n, pend, raw)

    DIAG_FILE = "verbindung_diagnose.log"

    def _write_diag(self, n, pend, raw):
        """Die letzten gesendeten/empfangenen Zeilen in eine Datei schreiben (max. 20 Einträge
        pro Sitzung), damit man sieht, was mit den 'ok' passiert ist."""
        if self._diag_count >= 20:
            return
        self._diag_count += 1
        try:
            import os
            import sys
            base = (os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False)
                    else os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(base, self.DIAG_FILE)
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n===== {time.strftime('%d.%m.%Y %H:%M:%S')}  {n} fehlende ok, "
                        f"Auffälligkeiten bisher: {self._anomalies}\n")
                f.write("offen: " + " | ".join(pend) + "\n")
                if self._odd:
                    f.write("auffällige Zeilen (zuletzt):\n")
                    for t, l in list(self._odd)[-40:]:
                        f.write(f"  {t} {l!r}\n")
                    f.write("Verlauf:\n")
                t0 = raw[0][0] if raw else 0
                for t, k, l in raw:
                    f.write(f"{t - t0:8.3f} {k} {l!r}\n")
        except Exception:
            pass

    def _sender(self):
        while self._running:
            with self.cv:
                while self._running and not self._can_send():
                    self.cv.wait(0.2)
                if not self._running:
                    break
                line, tag = self.pending.popleft()
                data = (line + "\n").encode()
                self.inflight.append((len(data), line, tag, time.time()))
                self._raw.append((time.time(), "tx", line))
            self._write(data)
            if tag == "console":
                self._log("tx", line)

    def _can_send(self):
        if not self.pending:
            return False
        nxt = len(self.pending[0][0]) + 1
        used = sum(i[0] for i in self.inflight)
        return used + nxt <= RX_BUFFER

    # ---------------------------------------------------------------- API
    def queue_lines(self, lines, tag=None):
        with self.cv:
            for l in lines:
                if isinstance(l, tuple):
                    self.pending.append(l)
                else:
                    self.pending.append((l, tag))
            self.cv.notify_all()

    def send(self, line, tag="console"):
        self.queue_lines([line.strip()], tag)

    def realtime(self, b: bytes):
        self._write(b)

    def idle_and_empty(self):
        with self.lock:
            return not self.pending and not self.inflight and self.state.startswith("Idle")

    def buffers_empty(self):
        with self.lock:
            return not self.pending and not self.inflight

    def clear_queue(self):
        with self.cv:
            self.pending.clear()
            self.cv.notify_all()

    def z_check(self, z):
        """Fehlertext, wenn Z (Arbeitskoordinate) außerhalb der Firmware-Grenze 0..$132 liegt."""
        if not self.fw.get(20) or not self.fw.get(132):
            return None
        mz = z + self.wco[2]
        if mz < -0.001 or mz > self.fw[132] + 0.001:
            lo, hi = -self.wco[2], self.fw[132] - self.wco[2]
            return (f"Z {z:g} mm liegt außerhalb des erlaubten Z-Bereichs ({lo:.2f} bis {hi:.2f} mm). "
                    f"Stifthöhen unter 'Geschwindigkeit & Stift' anpassen.")
        return None

    def z_limits(self):
        if not self.fw.get(20) or not self.fw.get(132):
            return None
        return -self.wco[2], self.fw[132] - self.wco[2]

    def soft_reset_keep_origin(self, z_up, z_feed):
        """Stoppt sofort, behält aber den gesetzten Nullpunkt (G92) bei."""
        wpos = [self.mpos[i] - self.wco[i] for i in range(3)]
        self.realtime(b"!")
        t0 = time.time()
        while time.time() - t0 < 3 and not (self.state.startswith("Hold:0") or self.state == "Idle"
                                             or self.state.startswith("Alarm")):
            time.sleep(0.05)
        wpos = [self.mpos[i] - self.wco[i] for i in range(3)]
        self.clear_queue()
        self.banner_event.clear()
        self.realtime(b"\x18")
        self.banner_event.wait(3)
        time.sleep(0.2)
        with self.cv:
            self.inflight.clear()
        if self.state == "Alarm" or self.last_alarm:
            self.send("$X", tag=None)
            self.last_alarm = ""
        # Nullpunkt wiederherstellen (G92 geht beim Reset verloren)
        lines = [f"G92 X{wpos[0]:.3f} Y{wpos[1]:.3f}", "G21", "G90"]
        if z_up is not None and self.z_check(z_up) is None:
            lines.append(f"G1 Z{z_up} F{int(z_feed)}")
        self.queue_lines(lines, None)

    def status(self):
        wpos = [round(self.mpos[i] - self.wco[i], 3) for i in range(3)]
        with self.lock:
            return {
                "connected": self.connected,
                "port": self.port,
                "state": self.state,
                "version": self.version,
                "mpos": [round(v, 3) for v in self.mpos],
                "wpos": wpos,
                "feed": self.feed,
                "queued": len(self.pending),
                "zero_set": getattr(self, "zero_set", False),
                "wco": [round(v, 3) for v in self.wco],
                "fw_max": [self.fw.get(130), self.fw.get(131)] if getattr(self, "fw", None) else None,
                "fw_soft_limits": bool(getattr(self, "fw", {}).get(20)),
            }

    def log_since(self, n):
        with self.lock:
            return [e for e in self.log if e["n"] > n]


class Job:
    """Ein Plot-Auftrag über mehrere Ebenen mit Stiftwechsel-Pausen."""

    def __init__(self, machine: Machine, layers, build_layer, header, footer,
                 start_layer=0, start_path=0, pen_change=True, on_progress=None, change_moves=None):
        self.m = machine
        self.layers = layers                # [{id,name,color,count}]
        self.build_layer = build_layer      # f(li, start_path) -> [(zeile, tag)]
        self.header = header
        self.footer = footer
        self.start_layer = start_layer
        self.start_path = start_path
        self.pen_change = pen_change
        self.on_progress = on_progress
        self.change_moves = change_moves    # f() -> Zeilen: Stift hoch + zum Nullpunkt
        self._next_layer = None             # beim Stiftwechsel: Ebene, die als nächste kommt
        self.state = "läuft"
        self.message = ""
        self.layer_idx = start_layer
        self.path_idx = start_path if start_path is not None else 0
        self.recent = collections.deque(maxlen=60)
        self.errors = 0
        self.t_start = time.time()
        self.t_paused = 0.0
        self._pause_t = None
        self.done_paths_before = 0
        self._continue = threading.Event()
        self._abort = False
        self.lines_total = 0
        self.lines_acked = 0
        machine.on_ack = self._ack
        machine.on_alarm = self._alarm
        machine.on_reset = self._reset
        machine.on_error = self._error
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    # Callbacks vom Machine-Reader
    def _ack(self, tag):
        if isinstance(tag, tuple):
            self.lines_acked += 1
            self.recent.append(tag)
            self.layer_idx, self.path_idx = tag
            if self.on_progress:
                self.on_progress(self)

    def _error(self, text):
        if self.state in ("läuft", "pausiert"):
            self.errors += 1

    def _alarm(self, text):
        if self.state in ("läuft", "pausiert", "stiftwechsel"):
            self._abort = True
            self.state = "abgebrochen"
            self.message = f"Abbruch durch {text}"
            self._continue.set()

    def _reset(self):
        if self.state in ("läuft", "pausiert") and not self._abort:
            self._abort = True
            self.state = "abgebrochen"
            self.message = "Controller wurde unerwartet neu gestartet"
            self._continue.set()

    def resume_point(self):
        if not self.recent and self._next_layer is not None:
            # Vorige Ebene ist komplett fertig -> nächste Ebene von vorne (rückwärts: vom Ende)
            li = self._next_layer
            return (li, self.layers[li]["count"] - 1 if getattr(self, "reverse", False) else 0)
        if not self.recent:
            if self.start_path is not None:
                return (self.start_layer, self.start_path)
            last = self.layers[self.start_layer]["count"] - 1
            return (self.start_layer, last if getattr(self, "reverse", False) else 0)
        return self.recent[0]

    def _wait_done(self):
        mark = None
        while not self._abort:
            if self.m.buffers_empty():
                # erst zwei *neue* Statusmeldungen abwarten, dann muss 'Idle' kommen
                if mark is None:
                    mark = self.m.status_seq
                elif self.m.status_seq >= mark + 2 and self.m.state.startswith("Idle"):
                    return True
            else:
                mark = None
            if not self.m.connected:
                self._abort = True
                self.state = "abgebrochen"
                self.message = "Verbindung verloren"
                return False
            time.sleep(0.1)
        return False

    def _run(self):
        self.m.queue_lines(self.header())
        for li in range(self.start_layer, len(self.layers)):
            if self._abort:
                return
            if li > self.start_layer and self.pen_change:
                # Stiftwechsel immer am Nullpunkt (Stift hoch, dann nach X0 Y0)
                self.m.queue_lines(self.change_moves() if self.change_moves else self.footer(False))
                if not self._wait_done():
                    return
                # Ebene davor ist vollständig gezeichnet: Fortsetzen-Stelle = nächste Ebene
                self.recent.clear()
                self._next_layer = li
                self.layer_idx, self.path_idx = self.resume_point()
                if self.on_progress:
                    self.on_progress(self)
                self.state = "stiftwechsel"
                self.message = (f"Stift wechseln für Ebene {li + 1} '{self.layers[li]['name']}' "
                                f"({self.layers[li]['color']}) – Kopf steht am Nullpunkt. "
                                f"Du kannst verfahren und den Nullpunkt neu setzen, dann 'Weiter'")
                self._continue.clear()
                self._continue.wait()
                if self._abort:
                    return
                # Falls noch verfahren wird: erst fertig werden lassen
                while not self._abort and not self.m.state.startswith("Idle"):
                    time.sleep(0.1)
                if self._abort:
                    return
                self.state = "läuft"
                self.message = ""
                self.m.queue_lines(self.header())
            sp = self.start_path if li == self.start_layer else None
            lines = self.build_layer(li, sp)
            self.lines_total += len(lines)
            self.m.queue_lines(lines)
        self.m.queue_lines(self.footer(True))
        if self._wait_done():
            self.state = "fertig"
            self.message = "Plot abgeschlossen"
            self.m._log("info", f"Plot fertig in {self.elapsed_str()}")

    # Steuerung
    def pause(self):
        if self.state == "läuft":
            self.m.realtime(b"!")
            self.state = "pausiert"
            self._pause_t = time.time()

    def resume(self):
        if self.state == "pausiert":
            self.m.realtime(b"~")
            self.state = "läuft"
            if self._pause_t:
                self.t_paused += time.time() - self._pause_t
                self._pause_t = None
        elif self.state == "stiftwechsel":
            self._continue.set()

    def abort(self, z_up, z_feed):
        was = self.state
        self._abort = True
        self.state = "abgebrochen"
        self.message = "Vom Benutzer gestoppt"
        self._continue.set()
        if was in ("läuft", "pausiert"):
            self.m.soft_reset_keep_origin(z_up, z_feed)
        else:
            self.m.clear_queue()
            if self.m.state.startswith("Jog"):
                self.m.realtime(b"\x85")       # laufendes Verfahren abbrechen

    def elapsed(self):
        t = time.time() - self.t_start - self.t_paused
        if self._pause_t:
            t -= time.time() - self._pause_t
        return t

    def elapsed_str(self):
        s = int(self.elapsed())
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"

    def info(self):
        return {
            "state": self.state,
            "message": self.message,
            "layer": self.layer_idx,
            "path": self.path_idx,
            "lines_total": self.lines_total,
            "lines_acked": self.lines_acked,
            "elapsed": self.elapsed(),
            "errors": self.errors,
            "resume": list(self.resume_point()),
        }
