@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM ===================================================================
REM  噜妹书院 · 部署到云服务器（双击我）
REM
REM  它做三件事：
REM    1. 把你电脑上的项目打成一个 tar.gz（含书架、下载、访问令牌）
REM    2. 问你云服务器的公网 IP
REM    3. 打印出「你接下来只需要粘的那一条命令」
REM
REM  为什么不直接自己 scp 过去：scp 要输服务器密码，
REM  我这边不能替你把密码敲进去（也不该知道你的密码）。
REM  所以最后那一下必须你来 —— 就一条命令，复制粘贴的事。
REM ===================================================================

echo.
echo ============================================================
echo   噜妹书院 · 部署到云服务器
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 没找到 .venv，请先双击 start.bat 让程序跑起来一次。
    echo.
    pause
    exit /b 1
)

echo [1/3] 正在打包项目（约 10 秒）...
echo.
".venv\Scripts\python.exe" tools\pack.py --out "dist\noveldock.tar.gz"
if errorlevel 1 (
    echo.
    echo [错误] 打包失败，看上面的红字。
    echo.
    pause
    exit /b 1
)

echo.
echo [2/3] 填你云服务器的公网 IP
echo.
echo   在哪看：腾讯云控制台 - 轻量应用服务器 - 实例列表
echo   实例那一行「公网 IP」列，形如 43.xxx.xxx.xxx
echo.
set /p "SRV_IP=  粘贴公网 IP，然后回车: "
if "%SRV_IP%"=="" (
    echo.
    echo   [取消] 没填 IP。
    echo.
    pause
    exit /b 1
)

REM 去掉可能被一起复制进来的空格
set "SRV_IP=%SRV_IP: =%"

echo.
echo ============================================================
echo   第 3 步：打开你电脑上的一个终端
echo ============================================================
echo.
echo   按 Win 键，输入 powershell，回车。
echo   然后把这**一整个**下面的命令复制过去，回车：
echo.
echo ------------------------------------------------------------
echo scp "%~dp0dist\noveldock.tar.gz" ubuntu@%SRV_IP%:~
echo ------------------------------------------------------------
echo.
echo   它会问密码 —— 就是你创建服务器时设的那个（或控制台重置的那个）。
echo   输密码时屏幕上**不会显示任何字符**，这是正常的，打完直接回车。
echo.
echo   传完之后，再复制这**一整个**到服务器上执行
echo   （用腾讯云控制台的「登录」/网页终端连上去）：
echo.
echo ------------------------------------------------------------
echo tar xzf noveldock.tar.gz ^&^& cd noveldock ^&^& bash tools/oneclick.sh
echo ------------------------------------------------------------
echo.
pause
