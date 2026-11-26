# Changelog

## Unreleased
- **Settings per file:** Nib remembers placement, optimization and hatch settings, hidden
  sublayers, layer order and ticks, and the plot direction of every file. Loading it again – even
  much later – brings them back. Layers that were plotted to the end get a ✓ and are unticked
  then, so a half-finished drawing continues with the next colour; **Plot everything again**
  starts over. Stored in `file_memory.json`.
- New README screenshots: a four-colour CMYK portrait (56,000 lines) placed on A4.
- Colour layers whose name already contains the colour code (e.g. “1 Yellow (#f5d000)” from Linedraw) don't show it twice.

## 1.3.1 – 2026-11-25
A small fix for 1.3.0.

- Buttons that should be hidden stay hidden (e.g. “Summary of the last plot” showed while plotting).
- New screenshots with a hatched layer; all release notes use the same layout.

## 1.3.0 – 2026-11-25
Hatch fill for filled shapes, a summary at the end of every plot, and notifications.

- **Hatch fill:** filled shapes can be hatched or cross-hatched per layer, with adjustable spacing
  (on paper, independent of the scale) and angle, optionally with the outline. A test strip with
  six spacings helps to find the right one for a pen; it loads like a drawing (also without a
  file) and gives your file back when closed. Lines can be joined into zigzags or drawn one by
  one. Preview and time estimate include it.
- **Plot summary** when a plot ends or is stopped: plot time with the estimate in brackets, line
  length per pen and in total, number of lines, time per pen and from start to end.
- **Notifications:** a system notification (Windows, macOS) and a short sound when the plot ends
  or the next pen is due. Can be switched off under *Layers*.
- Number fields accept a decimal comma as well as a point (1,5 or 1.5), whatever the system language.
- Refused API requests no longer make Windows reset the connection.

## 1.2.0 – 2026-11-25
Safer and more reliable: the local API is protected, two streaming problems are fixed, and the
releases are now built automatically.

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
Nib now runs on macOS as a native app, alongside Windows.

- **macOS:** Nib now runs on macOS as a native app (`Nib.app`, Apple Silicon), tested with the
  UUNATeK 3.0. Native dialogs, macOS serial ports (`/dev/cu.*`), settings in
  `~/Library/Application Support/Nib`. `Start Nib.command` and `build_app.command` for running and
  building from source.
- **Version number** shown in Nib.app (*About Nib*) and in Nib.exe (*Properties → Details*).
- The total line length above the preview now follows the scale, like the per-layer lengths.
- New screenshots (A3 landscape); the README shows dark mode first.
- `build_exe.bat` shows its progress, stops early if Nib.exe is still running and keeps its window open.

## 1.0.0 – 2026-11-24
The first public release of Nib, a modern control software for the UUNATeK 3.0 pen plotter
(GRBL/FluidNC), for Windows 10 and 11.

- SVG import from Illustrator, Inkscape and similar tools, at the correct size in mm.
- Layers by colour or by layer, with automatic pauses for pen changes.
- Path optimisation: sorting, joining lines, removing duplicates, simplifying.
- Live preview with progress and a realistic time estimate.
- Pause/resume, and resuming after an abort, even after restarting Nib.
- Plotting in reverse, or starting from any path.
- Pen-height setup, jogging and a G-code console.
- Built-in simulator for trying everything out without a plotter.
- Light and dark theme.
