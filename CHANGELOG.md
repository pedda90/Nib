# Changelog

## Unreleased
- **Hatch fill:** filled shapes can be hatched or cross-hatched per layer, with adjustable spacing
  (on paper, independent of the scale) and angle, optionally with the outline. A test strip with
  six spacings helps to find the right one for a pen; it loads like a drawing (also without a
  file) and gives your file back when closed. Lines can be joined into zigzags or drawn one by
  one. Preview and time estimate include it.
- **Plot summary** when a plot ends or is stopped: plot time with the estimate in brackets, line
  length per pen and in total, number of lines, time per pen and from start to end.
- **Notifications:** a system notification (Windows, macOS) and a short sound when the plot ends
  or the next pen is due. Can be switched off under *Layers*.
- Refused API requests no longer make Windows reset the connection.

## 1.2.0 – 2026-11-25
- **Security:** the local API only answers Nib's own page. Other web sites open in the browser
  can no longer control the plotter (per-start access token, Host/Origin check, JSON-only POSTs,
  no framing). A tab left open from an earlier start reloads itself to get the new token.
- **Pen change:** if the controller restarts during a pen change (e.g. a loose USB cable), the
  origin is lost – the job now stops instead of drawing the next layer in the wrong place.
  The reset and unlock buttons keep working as before.
- **Pen delays:** a pen up/down delay of about 0.4 s or more no longer confuses the streaming
  (acknowledgements were taken as lost during the pause, which could overflow the controller's
  receive buffer).
- The simulator handles `G4` like the real controller. Automated tests in `tests/`
  (`python -m pytest tests`), run by GitHub Actions on every push; `Nib.exe` and `Nib.app` for
  releases are now built there too.

## 1.1.0 – 2026-11-24
- **macOS:** Nib now runs on macOS as a native app (`Nib.app`, Apple Silicon), tested with the
  UUNATeK 3.0. Native dialogs, macOS serial ports (`/dev/cu.*`), settings in
  `~/Library/Application Support/Nib`. `Start Nib.command` and `build_app.command` for running and
  building from source.
- **Version number** shown in Nib.app (*About Nib*) and in Nib.exe (*Properties → Details*).
- The total line length above the preview now follows the scale, like the per-layer lengths.
- New screenshots (A3 landscape); the README shows dark mode first.
- `build_exe.bat` shows its progress, stops early if Nib.exe is still running and keeps its window open.

## 1.0.0 – 2026-11-24
First public release (Windows).
