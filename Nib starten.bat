@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Erster Start: Python-Umgebung wird eingerichtet...
  py -3 -m venv .venv || (echo Python nicht gefunden - bitte von python.org installieren. & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt || (pause & exit /b 1)
)
".venv\Scripts\python.exe" server.py
if errorlevel 1 pause
