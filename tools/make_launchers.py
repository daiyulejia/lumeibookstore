"""生成两个 .bat 启动脚本（start.bat / open-firewall.bat）。

为什么用生成器而不是直接写文件：批处理有三个必须同时满足的硬要求，
普通文本写入一个都保证不了。

1. **必须 CRLF 换行。** 用普通文本编辑器/工具写入会得到 LF-only 的 .bat，
   cmd.exe 会按字节偏移错读，`( )` 块和 `goto` 标号全部解析错乱 ——
   实测报出「'…创建虚拟环境...' 不是内部或外部命令」这种离谱错误。

2. **批处理正文只用 ASCII。** 这里踩的坑最绕：cmd 的 `echo` 按**当前代码页**
   把文件字节原样吐出去，而 Python 在 UTF-8 模式下按 UTF-8 输出。
   两套编码混在同一个控制台里，必然有一方乱码 —— 切哪个代码页都只能救一边。
   所以批处理里不写中文，所有中文提示交给 Python 打（它说得更清楚）。

3. **显式 `set PYTHONUTF8=1`。** 用户双击时环境里没有开发环境注入的那些变量，
   不设的话 Python 按 cp936 输出，和 `chcp 65001` 对不上。

用法：python tools/make_launchers.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 纯 ASCII —— 不要往里加中文，理由见模块开头第 2 条
START_BAT = """@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Force UTF-8 for Python so it matches chcp 65001 above.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set PORT=8000

if not exist ".venv\\Scripts\\python.exe" (
    echo [1/3] First run: creating virtualenv...
    python -m venv .venv
    ".venv\\Scripts\\python.exe" -m pip install -q -r requirements.txt
)

echo.
echo [2/3] Checking LAN access ^(can your phone reach it?^)...
".venv\\Scripts\\python.exe" tools\\firewall.py --port %PORT%

REM Skip the elevation prompt if we are already allowed OR if run.py can
REM borrow another Python that IS allowed (it does that automatically).
".venv\\Scripts\\python.exe" -c "import sys;sys.path.insert(0,'.');from app.netinfo import check,find_allowed_python;a=check(%PORT%)['ok'];b=bool(find_allowed_python(%PORT%));sys.exit(0 if (a or b) else 1)" >nul 2>&1
if not errorlevel 1 goto start

echo.
set /p "ANS=  Open port %PORT% now? (one admin prompt) [Y/N]: "
if /i not "%ANS%"=="Y" goto start
echo   Requesting admin rights...
powershell -NoProfile -Command "Start-Process -Verb RunAs -WorkingDirectory '%CD%' -FilePath 'cmd.exe' -ArgumentList '/k','.venv\\Scripts\\python.exe tools\\firewall.py --open --port %PORT%'"
echo   Finish that window, then come back here.
timeout /t 3 >nul

:start
echo.
echo [3/3] Starting Novel Dock...
".venv\\Scripts\\python.exe" run.py --port %PORT%
echo.
pause
"""

OPEN_FIREWALL_BAT = """@echo off
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
".venv\\Scripts\\python.exe" tools\\firewall.py --open --port %PORT%
echo.
pause
"""

FILES = {
    "start.bat": START_BAT,
    "open-firewall.bat": OPEN_FIREWALL_BAT,
}


def main() -> int:
    for name, body in FILES.items():
        target = ROOT / name
        data = body.replace("\n", "\r\n").encode("ascii")
        target.write_bytes(data)
        crlf = data.count(bytes([13, 10]))
        print(f"已写入 {name:20s} ASCII · CRLF {crlf} 处 · {len(data)} 字节")
    return 0


if __name__ == "__main__":
    sys.exit(main())
