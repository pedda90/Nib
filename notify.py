"""System notifications ("Plot complete", "Change pen") on Windows and macOS.

Runs in the background and never raises: a notification that can't be shown is simply skipped.
Title and text are handed over as data (environment variables / arguments), never pasted into
a script.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading

# Windows: a toast via the WinRT API, shown under PowerShell's app id (works without installing
# anything; Nib.exe has no registered app id of its own)
_PS_TOAST = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast><visual><binding template="ToastGeneric"><text/><text/></binding></visual></toast>')
$t = $xml.GetElementsByTagName('text')
$t.Item(0).AppendChild($xml.CreateTextNode($env:NIB_TITLE)) | Out-Null
$t.Item(1).AppendChild($xml.CreateTextNode($env:NIB_TEXT)) | Out-Null
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show(
    [Windows.UI.Notifications.ToastNotification]::new($xml))
"""

_OSA = ('on run argv\n'
        'display notification (item 2 of argv) with title (item 1 of argv) sound name "Glass"\n'
        'end run')


def _send(title, text):
    try:
        if sys.platform == "win32":
            env = dict(os.environ, NIB_TITLE=title, NIB_TEXT=text)
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-Command", _PS_TOAST], env=env, capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        elif sys.platform == "darwin":
            subprocess.run(["osascript", "-e", _OSA, title, text], capture_output=True, timeout=20)
        else:
            subprocess.run(["notify-send", title, text], capture_output=True, timeout=20)
    except Exception:
        pass


def notify(title, text):
    """Show a system notification without waiting for it."""
    threading.Thread(target=_send, args=(str(title), str(text)), daemon=True).start()
