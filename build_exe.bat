@echo off
rem Baut Nib.exe (eigenes Fenster, kein Browser) in diesen Ordner.
rem Einstellungen (settings.json) und Fortsetzen-Stand (job_state.json) liegen neben der exe.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || (echo Python nicht gefunden - bitte von python.org installieren. & pause & exit /b 1)
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller || (pause & exit /b 1)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name Nib --icon "%~dp0icon.ico" ^
  --add-data "%~dp0web;web" ^
  --exclude-module mockgrbl_tests --exclude-module tkinter ^
  --distpath "%~dp0." --workpath "%~dp0build" --specpath "%~dp0build" ^
  app.py || (pause & exit /b 1)
echo.
echo Fertig: Nib.exe
