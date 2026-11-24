# Changelog

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
