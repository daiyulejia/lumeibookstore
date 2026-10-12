"""守护进程：让服务能长期挂着，崩了自己起来，日志落盘。

为什么要它
----------
`run.py` 是前台进程：终端一关、或某次未捕获的异常把进程带走了，
服务就没了 —— 而你可能正在外面用手机看小说。

这个脚本把它包一层：
  · 崩了就自动拉起来（带退避，防止疯狂重启刷日志）
  · 输出全部写进 logs/，出问题时能倒查
  · 日志按天切，自动清理太老的，不会把硬盘塞满
  · 单实例：已经有一个在跑就不再起第二个（否则端口冲突，而且两个进程
    会互相抢缓存目录）

用法：
  python tools/serve.py                 # 前台跑（调试用）
  pythonw tools/serve.py                # 后台静默跑（开机自启用这个）
  python tools/serve.py --stop          # 停掉正在跑的那个
  python tools/serve.py --status        # 看状态
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGDIR = ROOT / "logs"
PIDFILE = ROOT / "cache" / "serve.pid"
KEEP_DAYS = 7


def log_path() -> Path:
    return LOGDIR / f"server-{datetime.now():%Y-%m-%d}.log"


def project_python(windowless: bool = False) -> str:
    """挑出**真正装着依赖**的解释器。

    为什么不用 sys.executable
    ------------------------
    项目的依赖（fastapi / uvicorn / httpx）装在 .venv 里。本脚本有可能被
    任意解释器拉起 —— 开机自启、系统 python、别的工具。那种时候
    sys.executable 指向的是「没装依赖」的解释器，用它去跑 run.py 会
    `import uvicorn` 失败、秒退，然后被守护逻辑当成崩溃无限重启，
    日志里刷满 ModuleNotFoundError。

    所以要跨解释器调用时，一律先认项目自带的 .venv，认不到才退回自己。
    """
    if os.name == "nt":
        sub, names = "Scripts", (("pythonw.exe", "python.exe") if windowless
                                 else ("python.exe", "pythonw.exe"))
    else:
        sub, names = "bin", ("python3", "python")
    for n in names:
        p = ROOT / ".venv" / sub / n
        if p.exists():
            return str(p)

    exe = Path(sys.executable)
    if windowless and os.name == "nt":
        w = exe.with_name("pythonw.exe")
        if w.exists():
            return str(w)
    return str(exe)


def ensure_stdio() -> None:
    """pythonw.exe 没有控制台，sys.stdout / sys.stderr 是 None。

    任何 print 都会抛 `AttributeError: 'NoneType' object has no attribute
    'write'` —— 而且是在第一行日志就炸，守护进程直接没起来、还什么都不说。
    这里把它们补到日志文件上，让后台跑也能留下痕迹。
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        LOGDIR.mkdir(parents=True, exist_ok=True)
        f = open(log_path(), "a", encoding="utf-8", buffering=1)
    except Exception:  # noqa: BLE001
        import io

        f = io.StringIO()  # 实在开不了文件也别让 print 崩
    if sys.stdout is None:
        sys.stdout = f
    if sys.stderr is None:
        sys.stderr = f


def say(msg: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        LOGDIR.mkdir(parents=True, exist_ok=True)
        with open(log_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def prune_logs() -> None:
    """删掉太老的日志。不然挂几个月能攒出几百 MB。

    ⚠ 现在有两套日志，别只顾一个：
      · server-YYYY-MM-DD.log —— 本脚本重定向的**原始 stdout**（含启动横幅、
        没被 logging 接管的 print、子进程输出）。兜底用，排查"进程起没起"看它。
      · app.log / app.log.YYYY-MM-DD —— 应用自己的**结构化日志**
        （带 req= 和事件名，见 app/logging_setup.py）。查业务问题看它。
    两套都清，保留策略一致。
    """
    try:
        cutoff = time.time() - KEEP_DAYS * 86400
        for pat in ("server-*.log", "app.log.*"):
            for p in LOGDIR.glob(pat):
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", port)) == 0


def running_pid() -> int | None:
    try:
        if not PIDFILE.exists():
            return None
        pid = int(PIDFILE.read_text().strip())
        # Windows 上 os.kill(pid, 0) 不可靠，改问 tasklist
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                 capture_output=True, text=True, timeout=10).stdout
            return pid if str(pid) in out else None
        os.kill(pid, 0)
        return pid
    except Exception:  # noqa: BLE001
        return None


def stop() -> int:
    pid = running_pid()
    if not pid:
        print("没有在跑")
        return 0
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=15)
        else:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        print(f"已停止 pid={pid}")
    except Exception as e:  # noqa: BLE001
        print(f"停止失败：{e}")
        return 1
    finally:
        PIDFILE.unlink(missing_ok=True)
    return 0


def status(port: int) -> int:
    pid = running_pid()
    up = port_busy(port)
    print(json.dumps({
        "running": bool(pid) or up,
        "pid": pid,
        "port": port,
        "listening": up,
        "log": str(log_path()),
        "logs": sorted(p.name for p in LOGDIR.glob("server-*.log"))[-3:] if LOGDIR.exists() else [],
    }, ensure_ascii=False, indent=2))
    return 0


def supervise(host: str, port: int, no_borrow: bool) -> None:
    if port_busy(port):
        say(f"端口 {port} 已经有服务在跑，不重复启动")
        return

    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()))
    LOGDIR.mkdir(parents=True, exist_ok=True)
    prune_logs()

    say(f"守护启动 · {host}:{port} · 日志 {log_path().name}")

    backoff = 3
    while True:
        # 用项目 .venv 的解释器跑 run.py —— 而不是 sys.executable。
        # 见 project_python() 的说明：serve.py 自己可能没装在依赖环境里。
        cmd = [project_python(), str(ROOT / "run.py"), "--host", host, "--port", str(port)]
        if no_borrow:
            cmd.append("--no-borrow")
        # 不设 PYTHONUNBUFFERED 的话日志会攒在缓冲区里，崩了看不到最后的输出
        env = dict(os.environ, PYTHONUNBUFFERED="1")

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        t0 = time.time()
        try:
            with open(log_path(), "a", encoding="utf-8") as lf:
                lf.write(f"\n{'='*60}\n{datetime.now():%Y-%m-%d %H:%M:%S} 启动\n{'='*60}\n")
                proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env,
                                        stdout=lf, stderr=subprocess.STDOUT,
                                        creationflags=creationflags)
                proc.wait()
                rc = proc.returncode
        except KeyboardInterrupt:
            say("收到中断，退出守护")
            PIDFILE.unlink(missing_ok=True)
            return
        except Exception as e:  # noqa: BLE001
            say(f"启动子进程失败：{e}")
            rc = -1

        lived = time.time() - t0
        say(f"服务退出（code={rc}，存活 {lived:.0f}s）")

        # 正常退出（Ctrl+C / SIGTERM）就别再拉起来了
        if rc == 0:
            say("正常退出，守护结束")
            PIDFILE.unlink(missing_ok=True)
            return

        # 活得够久说明不是启动就崩，重置退避
        if lived > 60:
            backoff = 3
        else:
            backoff = min(backoff * 2, 60)
        say(f"{backoff}s 后重启…")
        try:
            time.sleep(backoff)
        except KeyboardInterrupt:
            PIDFILE.unlink(missing_ok=True)
            return


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--no-borrow", action="store_true")
    a = ap.parse_args()

    # 必须在任何 print 之前 —— pythonw 下 sys.stdout 是 None
    ensure_stdio()

    if a.stop:
        return stop()
    if a.status:
        return status(a.port)
    supervise(a.host, a.port, a.no_borrow)
    return 0


if __name__ == "__main__":
    sys.exit(main())
