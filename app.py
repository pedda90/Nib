"""Nib in its own program window (no browser).

Starts the Nib server in the background and shows the interface in a
Windows window (Edge WebView2, built into Windows 11). Closing the window
quits Nib. If a plot is running, the user is asked first.

build_exe.bat builds Nib.exe from this file.
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
    """Without a console window, output goes to nib.log next to the exe."""
    if sys.stdout is None or sys.stderr is None:
        f = open(os.path.join(S.DATA, "nib.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f


def _ask(title, text):
    """Yes/no question as a normal Windows message box."""
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
        _error("Nib", f"Nib could not start:\n{e}")
        return
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"Nib running at http://127.0.0.1:{port}/")

    win = webview.create_window(
        "Nib", f"http://127.0.0.1:{port}/",
        width=1600, height=1000, min_size=(1100, 700),
        maximized=True, background_color="#121110", text_select=True)

    def on_closing():
        if S._job_busy():
            if not _ask("Quit Nib?",
                        "A plot is running.\n\nQuit anyway? The plot will be aborted; "
                        "the position is saved so you can resume later."):
                return False          # keep the window open
            try:
                m = S.APP.settings["machine"]
                job = S.APP.job
                job.abort(m["z_up"], m["z_feed"])
                S.APP.save_progress(job, force=True)
            except Exception:
                traceback.print_exc()
        return True

    win.events.closing += on_closing

    # browser storage (layout, reference point, step size) kept permanently next to the exe
    storage = os.path.join(S.DATA, "webview_data")
    old = os.path.join(S.DATA, "fensterdaten")          # folder name used by older versions
    if os.path.isdir(old) and not os.path.exists(storage):
        try:
            os.rename(old, storage)
        except OSError:
            storage = old
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
