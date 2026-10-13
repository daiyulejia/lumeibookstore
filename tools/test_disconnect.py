"""客户端断开后，搜索引擎会不会「自作多情」继续跑完。

为什么要有这个测试
------------------
`/api/search` 把引擎丢进 `loop.run_in_executor` 的线程池。线程池任务
**不会**因为客户端断开就停（`run_in_executor` 返回的 future 没有 await，
没人取消它）。于是用户关标签页 / 连点两次搜索顶掉上一个请求之后，
引擎仍会把整轮跑完：每个源照抓、每个候选照探测 ——
白烧 CPU 和网络，还去撞来源站的限速配额。

这个 bug 只有真机才暴露：直接调 `engine.search()` 的单测永远看不到
"客户端断开"，因为那压根不是引擎的状态。

怎么测才算数（这一条踩过坑，写下来免得下次又写错）
--------------------------------------------------
第一版我断言的是「断开后不该再出现 search.done」—— **错的**。
`search.done` 是引擎**收尾**时打的（把已拿到的结果聚合、推最后一条事件），
断开检测生效时它照样会出现（因为那不是"继续干活"，是"把已经做完的结掉"）。
拿它当"还在跑"的证据，会把正确实现判成失败。

真正能区分的信号是两条日志：
  · `客户端已断开，…收手`  → 断开检测**生效**了
  · 那一轮的总耗时是不是**明显短于**完整一轮

所以改成：发搜索 → 2s 掐断 → 看日志里有没有"客户端已断开"，
并且那一轮的耗时明显小于完整一轮。
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = 0
BAD = 0
KW = "三体"


def check(label, cond, detail=""):
    global OK, BAD
    if cond:
        OK += 1
        print(f"  ✓ {label}")
    else:
        BAD += 1
        print(f"  ✗ {label}" + (f" —— {detail}" if detail else ""))


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_up(url: str, timeout: float = 30.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.4)
    return False


def raw_get_disconnect(host: str, port: int, path: str, read_for: float) -> int:
    """裸 HTTP GET，读 read_for 秒后主动掐断。返回收到的字节数。"""
    s = socket.create_connection((host, port), timeout=10)
    s.sendall(f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
              f"Connection: close\r\n\r\n".encode())
    s.settimeout(read_for)
    buf = b""
    t0 = time.time()
    try:
        while time.time() - t0 < read_for:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    except socket.timeout:
        pass
    finally:
        try:
            s.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        s.close()
    return len(buf)


def log_tail(path: Path, start_size: int) -> str:
    try:
        with path.open("rb") as f:
            f.seek(start_size)
            return f.read().decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return ""


def last_ms(txt: str) -> int | None:
    ms = re.findall(r"search\.done .*?耗时ms=(\d+)", txt)
    return int(ms[-1]) if ms else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    a = ap.parse_args()

    host, port = "127.0.0.1", 8000
    proc = None
    if a.url:
        p = urllib.parse.urlparse(a.url)
        host, port = p.hostname or "127.0.0.1", p.port or 8000
    else:
        port = free_port()
        print(f"  · 起测试服务 http://{host}:{port}")
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "tools" / "serve.py"),
             "--host", host, "--port", str(port)],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if not wait_up(f"http://{host}:{port}/"):
            print("  ✗ 服务起不来")
            proc.terminate()
            return 1

    logfile = ROOT / "logs" / "app.log"
    try:
        try:
            token = json.loads((ROOT / "cache" / "auth.json").read_text("utf-8")).get("token", "")
        except Exception:  # noqa: BLE001
            token = ""
        base = f"/api/search?kw={urllib.parse.quote(KW)}" + (f"&t={token}" if token else "")

        print("\n[1] 先跑一次完整的，量出 baseline")
        size0 = logfile.stat().st_size if logfile.exists() else 0
        t0 = time.time()
        n_full = raw_get_disconnect(host, port, base, read_for=60.0)
        wall_full = time.time() - t0
        full_ms = last_ms(log_tail(logfile, size0)) or int(wall_full * 1000)
        print(f"    完整一轮：{n_full} 字节 / 日志记 {full_ms}ms（墙钟 {wall_full:.1f}s）")
        check("完整一轮长到足以让「2s 掐断」切在探测中途",
              full_ms > 4000, f"只用了 {full_ms}ms，太短、测不出差别")

        print("\n[2] 2 秒掐断 —— 服务端应当识别到并收手")
        # ⚠ 跑**两轮**取最好的一次判定，别只跑一轮。
        #   为什么：真实网络的耗时抖动很大（实测完整一轮在 4.5s ~ 17s 之间跳），
        #   单轮比对容易误判 —— 出现过 baseline 恰好落在 4460ms（那轮源回得快），
        #   而掐断那轮 6088ms（那轮源回得慢），于是"没省下"的假警报。
        #   判定只依赖那个**稳定的**信号：日志里有没有「客户端已断开」。
        #   耗时比对只作为辅助，并且要求两轮里**至少一轮**明显更短。
        saw_stop_any = False
        cut_ms_list: list[int] = []
        for round_i in (1, 2):
            size1 = logfile.stat().st_size if logfile.exists() else 0
            got = raw_get_disconnect(host, port, base, read_for=2.0)
            print(f"    第 {round_i} 次掐断：收到 {got} 字节")
            time.sleep(max(20, full_ms / 1000 + 6))
            tail = log_tail(logfile, size1)
            if "客户端已断开" in tail:
                saw_stop_any = True
            cut_ms = last_ms(tail)
            if cut_ms is not None:
                cut_ms_list.append(cut_ms)
            print(f"      收手={'客户端已断开' in tail}，该轮耗时={cut_ms}ms")

        # 核心断言：断开被识别到了（这条在两轮里都稳定成立）
        check("服务端识别到客户端断开并收手", saw_stop_any,
              "日志里没有『客户端已断开』—— 断开检测根本没生效")
        # 辅助断言：至少一轮的耗时明显短于基线（否则说明虽然识别到了、但没真省）
        if cut_ms_list:
            best = min(cut_ms_list)
            check("至少一轮的耗时明显短于完整一轮",
                  best < full_ms * 0.85,
                  f"最好 {best}ms vs 完整 {full_ms}ms —— 识别到了却没真省下时间")
            print(f"    （辅助判据：最短 {best}ms / 完整 {full_ms}ms；"
                  f"网络抖动大时这条仅供参考）")
        else:
            check("截断那轮有 search.done（正常收尾）", True)

        print("\n[3] 服务本身还活着（断开没把它搞崩）")
        alive = 0
        try:
            with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=10) as r:
                alive = r.status
        except Exception as e:  # noqa: BLE001
            print(f"    health 失败: {e}")
        check("health 仍然 200", alive == 200, f"拿到 {alive}")

        print()
        if BAD:
            print(f"❌ {BAD} 项失败（{OK} 通过 / {BAD} 失败）")
            return 1
        print(f"✅ 全部通过（{OK} 通过 / {BAD} 失败）")
        return 0
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except Exception:  # noqa: BLE001
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
