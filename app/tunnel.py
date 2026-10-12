"""内网穿透：把本机服务临时挂到一个公网 https 地址上。

为什么选 Cloudflare 快速隧道（cloudflared quick tunnel）
--------------------------------------------------------
- **不用注册、不用域名、不用改路由器**。跑起来就给你一个
  `https://xxx-xxx-xxx.trycloudflare.com`，手机在外地打开就能用。
- 走的是**出站长连接**，所以不需要在路由器上做端口映射，
  也不受「家里宽带没有公网 IP」的限制（这才是大多数人真正的问题）。
- 关了就是关了，不常驻，安全面小。

代价要说清楚（界面上也会写）：
- 地址是**随机且每次都不一样**的，重启换一个。
- 它是一条公网通道 —— 所以必须有访问令牌，见 app/security.py。
- 免费快速隧道没有 SLA，慢的时候会卡。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
_BIN_DIR = _ROOT / "tools" / "bin"

# 「现在这条能直接打开的链接」落一份到项目根目录，图的就是好找。
ACCESS_FILE = _ROOT / "远程访问.txt"

_WIN_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
_NIX_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"

_URL_RE = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com", re.I)

_proc: Optional[subprocess.Popen] = None
_url: str = ""
_started: float = 0.0
_log: list[str] = []
_lock = threading.Lock()
_downloading = False


# ---------------------------------------------------------------------------
# 找 / 装二进制
# ---------------------------------------------------------------------------
def binary() -> Optional[str]:
    env = os.environ.get("CLOUDFLARED", "").strip()
    if env and Path(env).exists():
        return env

    name = "cloudflared.exe" if os.name == "nt" else "cloudflared"
    local = _BIN_DIR / name
    if local.exists():
        return str(local)

    found = shutil.which("cloudflared")
    return found or None


def download() -> str:
    """下载 cloudflared。只在第一次用穿透时发生（约 55MB）。"""
    global _downloading
    with _lock:
        if _downloading:
            raise RuntimeError("正在下载中，稍等一下")
        _downloading = True
    try:
        _BIN_DIR.mkdir(parents=True, exist_ok=True)
        name = "cloudflared.exe" if os.name == "nt" else "cloudflared"
        target = _BIN_DIR / name
        url = _WIN_URL if os.name == "nt" else _NIX_URL

        _log.append(f"下载 cloudflared: {url}")
        tmp = target.with_suffix(target.suffix + ".part")
        with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total and got % (8 << 20) < (1 << 20):
                    _log.append(f"  已下载 {got // (1 << 20)}MB / {total // (1 << 20)}MB")
        tmp.replace(target)
        if os.name != "nt":
            target.chmod(0o755)
        _log.append("下载完成")
        return str(target)
    finally:
        _downloading = False


def ensure_binary() -> str:
    b = binary()
    if b:
        return b
    return download()


# ---------------------------------------------------------------------------
# 启停
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 把「当前能直接打开的链接」写到好找的地方
# ---------------------------------------------------------------------------
def write_access_file() -> str:
    """把当前链接 + 令牌写进项目根目录的 `远程访问.txt`，返回完整链接。

    为什么值得专门做这件事
    ----------------------
    手机用的那条链接是**自包含**的（`…trycloudflare.com?t=<令牌>`），
    收藏它就够，根本不用记什么 key。但人一急很容易只存下裸地址
    `https://xxx.trycloudflare.com`，再打开就撞上「需要访问令牌」那一页 ——
    而**令牌只有在已经进去之后才看得到**，人不在电脑边就成了死循环。
    实测就是这么卡的：人在外面，有链接、没钥匙，谁也救不了。

    所以隧道一起来就把完整链接落一份到根目录。顺带把令牌也写清楚 ——
    令牌是**稳定的**（只有点「换一个令牌」才会变），记一次能一直用。
    """
    try:
        from . import security
        tok = security.token()
    except Exception:  # noqa: BLE001
        tok = ""

    running = bool(_proc and _proc.poll() is None) and bool(_url)
    full = f"{_url}?t={tok}" if (_url and tok) else ""

    lines = ["远程访问（内网穿透）", ""]
    if running:
        lines += [
            "能直接打开的那条链接（已经带了令牌，收藏这一条就够）：",
            "",
            f"    {full}",
            "",
        ]
    else:
        lines += [
            "隧道当前**没在跑**，所以现在没有可用的公网地址。",
            "在电脑上打开程序 → 顶栏「网络」面板 → 点「开启远程访问」。",
            "",
        ]
    lines += [
        f"访问令牌（只有点「换一个令牌」才会变，记一次能一直用）：",
        "",
        f"    {tok}",
        "",
        "说明：",
        "  · 地址是 cloudflared 快速隧道给的，**每次重启都会换一个** ——",
        "    上面这条就是当前有效的那个，换了之后这个文件会跟着更新。",
        "  · 手机和电脑连同一个 WiFi 时走局域网直连，**不需要令牌**。",
        "  · 令牌等于钥匙。带令牌的链接别随手发到公开的地方。",
        "",
        f"更新于 {time.strftime('%Y-%m-%d %H:%M:%S')}"
        + ("（隧道运行中）" if running else "（隧道未运行）"),
        "",
    ]
    try:
        ACCESS_FILE.write_text("\n".join(lines), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return full


def _reader(proc: subprocess.Popen) -> None:
    """读 cloudflared 的输出，从里面抠出公网地址。"""
    global _url
    assert proc.stderr is not None
    for raw in proc.stderr:
        line = raw.decode("utf-8", "replace").rstrip()
        _log.append(line)
        if len(_log) > 400:
            del _log[:200]
        m = _URL_RE.search(line)
        if m and not _url:
            _url = m.group(0)
            write_access_file()      # 拿到地址就马上落盘，别等人家来问
    _log.append("[隧道进程结束]")
    write_access_file()


def start(port: int) -> dict:
    """启动隧道。返回 {ok, url, error}。"""
    global _proc, _url, _started, _log

    with _lock:
        if _proc and _proc.poll() is None:
            write_access_file()
            return {"ok": True, "url": _url, "already": True}

        _url = ""
        _log = []
        _started = time.time()

        try:
            exe = ensure_binary()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"拿不到 cloudflared：{e}"}

        cmd = [exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"]
        _log.append("启动: " + " ".join(cmd))

        creationflags = 0
        if os.name == "nt":
            # 别弹出一个黑窗口
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            _proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"启动失败：{e}"}

        threading.Thread(target=_reader, args=(_proc,), daemon=True).start()

    # 等地址出现（首次连接通常 5~15 秒；下载另算）
    deadline = time.time() + 90
    while time.time() < deadline:
        if _url:
            return {"ok": True, "url": _url}
        if _proc and _proc.poll() is not None:
            tail = "\n".join(_log[-8:])
            return {"ok": False, "error": "隧道进程退出了。\n" + tail}
        time.sleep(0.4)

    return {"ok": False, "error": "等了 90 秒还没拿到公网地址，网络可能不通。"}


def stop() -> dict:
    global _proc, _url
    with _lock:
        if _proc and _proc.poll() is None:
            try:
                _proc.terminate()
                try:
                    _proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    _proc.kill()
            except Exception:  # noqa: BLE001
                pass
        _proc = None
        _url = ""
        if not _log or _log[-1] != "[已停止]":
            _log.append("[已停止]")
    # 文件里改写成「隧道没在跑」—— 免得人拿着一条死链在外面反复试。
    # 注意令牌照旧留着：它是稳定的，下次开隧道还是这一把钥匙。
    write_access_file()
    return {"ok": True}


def access_file_text() -> str:
    """给界面用：直接读出（必要时先刷新）那份文件的内容。"""
    try:
        if not ACCESS_FILE.exists():
            write_access_file()
        return ACCESS_FILE.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return f"读不到：{e}"


def status() -> dict:
    running = bool(_proc and _proc.poll() is None)
    return {
        "running": running,
        "url": _url if running else "",
        "started": int(_started) if running else 0,
        "seconds": int(time.time() - _started) if running else 0,
        "available": bool(binary()),
        "downloading": _downloading,
        "tail": _log[-12:] if running else [],
    }
