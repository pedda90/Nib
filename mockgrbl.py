"""Simulated GRBL plotter for testing without hardware (port name 'SIMULATOR')."""
from __future__ import annotations

import math
import queue
import re
import threading
import time

WORD = re.compile(r"([A-Z])(-?\d*\.?\d+)")


class MockSerial:
    def __init__(self, speedup=20.0):
        self.speedup = speedup
        self._out = queue.Queue()
        self._planner = queue.Queue(maxsize=15)
        self._inbuf = b""
        self.mpos = [0.0, 0.0, 0.0]
        self.g92 = [0.0, 0.0, 0.0]
        self.feed = 1000.0
        self.state = "Idle"
        self.hold = False
        self.is_open = True
        self._reset_flag = threading.Event()
        self._lines = queue.Queue()
        self._rx = 0                  # bytes waiting in the receive buffer
        self.rx_size = 256
        self.report_mask = 1          # $10
        self.drop_ok = 0.0            # test: probability that an 'ok' gets lost
        self._gen = 0
        threading.Thread(target=self._motion, daemon=True).start()
        threading.Thread(target=self._line_worker, daemon=True).start()
        self._out.put(b"\r\nGrbl 1.1h ['$' for help]\r\n")

    # --- serial API -------------------------------------------------------
    def write(self, data: bytes):
        for b in data:
            c = bytes([b])
            if c == b"?":
                self._status()
            elif c == b"!":
                self.hold = True
                if self.state == "Run":
                    self.state = "Hold:0"
            elif c == b"~":
                self.hold = False
                if self.state.startswith("Hold"):
                    self.state = "Run" if not self._planner.empty() else "Idle"
            elif b == 0x18:
                self._gen += 1
                self._reset_flag.set()
                while not self._planner.empty():
                    try:
                        self._planner.get_nowait()
                    except queue.Empty:
                        break
                self.hold = False
                self.state = "Idle"
                self.g92 = [0.0, 0.0, 0.0]
                self._inbuf = b""
                self._rx = 0
                while not self._lines.empty():
                    try:
                        self._lines.get_nowait()
                    except queue.Empty:
                        break
                self._out.put(b"\r\nGrbl 1.1h ['$' for help]\r\n")
            elif b == 0x85:
                pass
            else:
                self._inbuf += c
                if c == b"\n":
                    line = self._inbuf.decode(errors="ignore").strip().upper()
                    self._rx += len(self._inbuf)
                    self._inbuf = b""
                    self._lines.put((line, len(line) + 1))
        return len(data)

    def _line_worker(self):
        while True:
            line, n = self._lines.get()
            self._rx = max(0, self._rx - n)
            self._line(line)

    def _ok(self):
        import random
        if self.drop_ok and random.random() < self.drop_ok:
            return
        self._out.put(b"ok\r\n")

    def readline(self):
        try:
            return self._out.get(timeout=0.1)
        except queue.Empty:
            return b""

    def close(self):
        self.is_open = False

    @property
    def in_waiting(self):
        return self._out.qsize()

    def reset_input_buffer(self):
        pass

    # --- internal ---------------------------------------------------------
    def _status(self):
        w = [self.mpos[i] - self.g92[i] for i in range(3)]
        bf = (f"|Bf:{15 - self._planner.qsize()},{self.rx_size - self._rx - len(self._inbuf)}"
              if self.report_mask & 2 else "")
        self._out.put(
            (f"<{self.state}|MPos:{self.mpos[0]:.3f},{self.mpos[1]:.3f},{self.mpos[2]:.3f}"
             f"|FS:{int(self.feed)},0{bf}|WCO:{self.g92[0]:.3f},{self.g92[1]:.3f},{self.g92[2]:.3f}>\r\n").encode())
        _ = w

    def _line(self, line):
        if not line:
            self._out.put(b"ok\r\n")
            return
        if line == "$$":
            for s in ("$100=80.000", "$101=80.000", "$102=80.000", "$110=12000.000",
                      "$111=12000.000", "$112=6000.000", "$22=0", "$20=1",
                      "$130=420.000", "$131=297.000", "$132=12.000", f"$10={self.report_mask}",
                      "$11=0.010", "$120=1000.000", "$121=1000.000", "$122=500.000"):
                self._out.put((s + "\r\n").encode())
            self._out.put(b"ok\r\n")
            return
        if line.startswith("$J="):
            line = line[3:]
        if line.startswith("$10="):
            self.report_mask = int(float(line[4:]))
        if line.startswith("$"):
            self._out.put(b"ok\r\n")
            return
        words = dict((k, float(v)) for k, v in WORD.findall(line))
        g = words.get("G")
        if g == 92:
            for i, ax in enumerate("XYZ"):
                if ax in words:
                    self.g92[i] = self.mpos[i] - words[ax]
            self._out.put(b"ok\r\n")
            return
        if g in (0, 1) or any(a in words for a in "XYZ"):
            # blocks when the planner is full -> 'ok' delayed (like real hardware)
            if "G53" in line:
                words["G53"] = 1
            self._planner.put((dict(words), "G91" in line, self._gen))
            self._ok()
            return
        if g == 4:
            self._planner.put(({"DWELL": words.get("P", 0)}, False, self._gen))
        self._out.put(b"ok\r\n")

    def _motion(self):
        rel = False
        while True:
            try:
                words, is_rel, gen = self._planner.get(timeout=0.05)
            except queue.Empty:
                if self.state == "Run":
                    self.state = "Idle"
                continue
            if gen != self._gen:
                continue
            while self.hold:
                time.sleep(0.02)
            self._reset_flag.clear()
            self.state = "Run"
            if "DWELL" in words:
                time.sleep(words["DWELL"] / self.speedup)
                continue
            if "F" in words:
                self.feed = words["F"]
            tgt = list(self.mpos)
            for i, ax in enumerate("XYZ"):
                if ax in words:
                    tgt[i] = (self.mpos[i] + words[ax]) if is_rel else (
                        words[ax] if "G53" in words else words[ax] + self.g92[i])
            d = math.dist(tgt, self.mpos)
            dur = d / max(self.feed, 1) * 60 / self.speedup
            steps = max(1, int(dur / 0.02))
            start = list(self.mpos)
            for s in range(1, steps + 1):
                while self.hold:
                    time.sleep(0.02)
                if self._reset_flag.is_set():
                    break
                self.mpos = [start[i] + (tgt[i] - start[i]) * s / steps for i in range(3)]
                time.sleep(dur / steps)
            _ = rel
