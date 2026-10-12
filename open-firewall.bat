@echo off
chcp 65001 >nul
cd /d "%~dp0"

set PORT=%~1
if "%PORT%"=="" set PORT=8000

REM Self-elevate: relaunch this same script through UAC if not admin yet.
net session >nul 2>&1
if not errorlevel 1 goto run

echo Need administrator rights. A UAC prompt will pop up - click Yes.
powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0' -ArgumentList '%PORT%'"
exit /b

:run
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo Allow inbound TCP port %PORT% on the LAN (for your phone)...
echo.
".venv\Scripts\python.exe" tools\firewall.py --open --port %PORT%
echo.
pause
