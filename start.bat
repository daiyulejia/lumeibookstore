@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Force UTF-8 for Python so it matches chcp 65001 above.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set PORT=8000

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] First run: creating virtualenv...
    python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)

echo.
echo [2/3] Checking LAN access ^(can your phone reach it?^)...
".venv\Scripts\python.exe" tools\firewall.py --port %PORT%

REM Skip the elevation prompt if we are already allowed OR if run.py can
REM borrow another Python that IS allowed (it does that automatically).
".venv\Scripts\python.exe" -c "import sys;sys.path.insert(0,'.');from app.netinfo import check,find_allowed_python;a=check(%PORT%)['ok'];b=bool(find_allowed_python(%PORT%));sys.exit(0 if (a or b) else 1)" >nul 2>&1
if not errorlevel 1 goto start

echo.
set /p "ANS=  Open port %PORT% now? (one admin prompt) [Y/N]: "
if /i not "%ANS%"=="Y" goto start
echo   Requesting admin rights...
powershell -NoProfile -Command "Start-Process -Verb RunAs -WorkingDirectory '%CD%' -FilePath 'cmd.exe' -ArgumentList '/k','.venv\Scripts\python.exe tools\firewall.py --open --port %PORT%'"
echo   Finish that window, then come back here.
timeout /t 3 >nul

:start
echo.
echo [3/3] Starting Novel Dock...
".venv\Scripts\python.exe" run.py --port %PORT%
echo.
pause
