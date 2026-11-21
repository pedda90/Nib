"""Nib als eigenes Programmfenster (ohne Browser).

Startet den Nib-Server im Hintergrund und zeigt die Oberfläche in einem
Windows-Fenster (Edge WebView2, ist in Windows 11 eingebaut). Wird das Fenster
geschlossen, beendet sich Nib. Läuft gerade ein Plot, wird vorher gefragt.

Aus dieser Datei baut build_exe.bat die Nib.exe.
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import traceback

import webview

import server as S


def _log_to_file():
    """Ohne Konsolenfenster gehen Meldungen in nib.log neben der exe."""
    if sys.stdout is None or sys.stderr is None:
        f = open(os.path.join(S.DATA, "nib.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f


def _ask(title, text):
    """Ja/Nein-Abfrage als normales Windows-Meldungsfenster."""
    MB_YESNO, MB_ICONWARNING, MB_DEFBUTTON2, MB_TOPMOST, IDYES = 0x4, 0x30, 0x100, 0x40000, 6
    return ctypes.windll.user32.MessageBoxW(None, text, title,
                                            MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2 | MB_TOPMOST) == IDYES


def _error(title, text):
    ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)


def main():
    _log_to_file()
    try:
        srv = S.make_server(S.PORT, fallback=True)
    except Exception as e:
        _error("Nib", f"Nib konnte nicht starten:\n{e}")
        return
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"Nib läuft auf http://127.0.0.1:{port}/")

    win = webview.create_window(
        "Nib", f"http://127.0.0.1:{port}/",
        width=1600, height=1000, min_size=(1100, 700),
        maximized=True, background_color="#16181c", text_select=True)

    def on_closing():
        if S._job_busy():
            if not _ask("Nib beenden?",
                        "Es läuft gerade ein Plot.\n\nWirklich beenden? Der Plot wird abgebrochen, "
                        "die Stelle wird gemerkt und kann später fortgesetzt werden."):
                return False          # Fenster bleibt offen
            try:
                m = S.APP.settings["machine"]
                job = S.APP.job
                job.abort(m["z_up"], m["z_feed"])
                S.APP.save_progress(job, force=True)
            except Exception:
                traceback.print_exc()
        return True

    win.events.closing += on_closing

    # Browser-Speicher (Fensteraufteilung, Bezugspunkt, Schrittweite) dauerhaft neben der exe
    storage = os.path.join(S.DATA, "fensterdaten")
    try:
        webview.start(private_mode=False, storage_path=storage, gui="edgechromium")
    finally:
        try:
            S.APP.machine.disconnect()
        except Exception:
            pass
        srv.shutdown()


if __name__ == "__main__":
    main()
