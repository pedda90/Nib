@echo off
rem Builds Nib.exe (its own window, no browser) into this folder.
rem Settings (settings.json) and the resume point (job_state.json) are stored next to the exe.
cd /d "%~dp0"
tasklist /fi "imagename eq Nib.exe" 2>nul | find /i "Nib.exe" >nul && (
  echo Nib.exe is still running - please close it first, then run this again.
  pause & exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Setting up a Python environment ^(first run only^)...
  py -3 -m venv .venv || (echo Python not found - please install it from python.org. & pause & exit /b 1)
) else (
  echo [1/3] Python environment found.
)
echo [2/3] Installing/checking packages ^(the first run can take a few minutes^)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller || (pause & exit /b 1)
echo [3/3] Building Nib.exe ^(about half a minute^)...
rem version shown under Properties - Details, taken from VERSION in server.py
".venv\Scripts\python.exe" version_info.py "%~dp0build\version_info.txt" || (pause & exit /b 1)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --log-level WARN ^
  --name Nib --icon "%~dp0icon.ico" --version-file "%~dp0build\version_info.txt" ^
  --add-data "%~dp0web;web" ^
  --exclude-module mockgrbl_tests --exclude-module tkinter ^
  --distpath "%~dp0." --workpath "%~dp0build" --specpath "%~dp0build" ^
  app.py || (pause & exit /b 1)
echo.
echo Done: Nib.exe
pause
