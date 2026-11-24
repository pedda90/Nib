#!/bin/bash
# Starts Nib on macOS in its own window.
# The first start sets up a Python environment and installs what Nib needs (a few minutes).
cd "$(dirname "$0")" || exit 1

pause() { read -r -n 1 -p "Press any key to close..."; echo; }

if [ ! -x ".venv/bin/python" ]; then
  echo "First start: setting up the Python environment..."
  if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 not found - please install it from python.org."
    pause; exit 1
  fi
  python3 -m venv .venv || { pause; exit 1; }
  .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt || { rm -rf .venv; pause; exit 1; }
fi

.venv/bin/python app.py || pause
