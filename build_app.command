#!/bin/bash
# Builds Nib.app (macOS) into this folder.
# Settings (settings.json) and the resume point (job_state.json) are stored in
# ~/Library/Application Support/Nib.
cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"

pause() { read -r -n 1 -p "Press any key to close..."; echo; }
fail() { pause; exit 1; }

if pgrep -xq Nib; then
  echo "Nib is still running - please quit it first, then run this again."
  fail
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "[1/3] Setting up a Python environment (first run only)..."
  command -v python3 >/dev/null 2>&1 || { echo "Python 3 not found - please install it from python.org."; fail; }
  python3 -m venv .venv || fail
else
  echo "[1/3] Python environment found."
fi

echo "[2/3] Installing/checking packages (the first run can take a few minutes)..."
# Pillow lets PyInstaller turn icon.ico into the macOS app icon
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller pillow || fail

echo "[3/3] Building Nib.app (about a minute)..."
.venv/bin/python -m PyInstaller --noconfirm --clean --windowed --log-level WARN \
  --name Nib --icon "$HERE/icon.ico" \
  --add-data "$HERE/web:web" \
  --exclude-module mockgrbl_tests --exclude-module tkinter \
  --distpath "$HERE/dist" --workpath "$HERE/build/mac" --specpath "$HERE/build/mac" \
  app.py || fail

rm -rf "$HERE/Nib.app"
mv "$HERE/dist/Nib.app" "$HERE/Nib.app" && rm -rf "$HERE/dist"
echo
echo "Done: Nib.app"
pause
