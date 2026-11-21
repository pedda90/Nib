@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First start: setting up the Python environment...
  py -3 -m venv .venv || (echo Python not found - please install it from python.org. & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt || (pause & exit /b 1)
)
".venv\Scripts\python.exe" server.py
if errorlevel 1 pause
