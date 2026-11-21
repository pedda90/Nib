@echo off
rem Builds Nib.exe (its own window, no browser) into this folder.
rem Settings (settings.json) and the resume point (job_state.json) are stored next to the exe.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || (echo Python not found - please install it from python.org. & pause & exit /b 1)
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller || (pause & exit /b 1)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name Nib --icon "%~dp0icon.ico" ^
  --add-data "%~dp0web;web" ^
  --exclude-module mockgrbl_tests --exclude-module tkinter ^
  --distpath "%~dp0." --workpath "%~dp0build" --specpath "%~dp0build" ^
  app.py || (pause & exit /b 1)
echo.
echo Done: Nib.exe
