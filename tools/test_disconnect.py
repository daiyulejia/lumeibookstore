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

⚠ 上面最后那句"看耗时"后来被**删掉**了 —— 它是个坏判据。
  为什么：耗时受源站快慢支配，实测同一本书能在 2.3s ~ 25.6s 之间跳（5 倍）。
  "完整一轮"经常碰巧比"掐断那轮"还短，于是**正确的实现被反复判红**
  （本文件历史上红过三次，我调了三次阈值都没用 —— 问题不在阈值，
  在于这个指标压根不随代码变化）。
  现在的判据换成引擎自报的 `aborted`（附着在 `search.done` 日志上）：
  它只取决于"该不该收手"，源站再快再慢都不影响，是**确定性信号**。
  耗时仍然打印出来给人看趋势，但不参与 pass/fail。
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


_ABORTED_RE = re.compile(r"search\.done .*?aborted=(\w+)")


def last_aborted(txt: str) -> bool | None:
    """从日志里读「这一轮是不是被断开收手打断的」。

    ⚠ 这是本测试**唯一可靠**的判据，别再回去比耗时。
      为什么：日志里的 `aborted` 只取决于机制本身（该不该收手），
      而耗时受源站快慢影响，实测同一本书能在 2.3s ~ 25.6s 之间跳（5 倍）。
      用耗时当判据时，"完整一轮"经常**碰巧比掐断那轮还短** ——
      于是正确的实现被反复判红（本文件历史上红过三次，每次都是这个原因）。
      一个只随环境漂移、不随代码变化的指标，不配当判据。
    """
    vals = _ABORTED_RE.findall(txt)
    if not vals:
        return None
    return vals[-1] == "True"


def wait_done_ms(logfile: Path, start_size: int, timeout: float = 75.0,
                 every: float = 0.25) -> int | None:
    """等日志里出现「这一轮跑完」，返回它记的耗时；等不到就 None。

    为什么不 sleep 一个拍脑袋的时长：源站响应在 3s ~ 18s 之间跳，
    固定 sleep 要么白等（源快时），要么在源慢时**读到上一轮的 done** ——
    那正是本次踩的坑：掐断轮拿到的其实是紧邻的完整轮的耗时，
    两个数于是"一样长"，断言报"没省下时间"，可实际省没省根本没被量到。
    改成轮询「出现新的 done」，就永远读的是自己那一轮的数。
    """
    end = time.time() + timeout
    while time.time() < end:
        m = last_ms(log_tail(logfile, start_size))
        if m is not None:
            return m
        time.sleep(every)
    return None


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

        # ---- [1] 量完整一轮的耗时：**与 [2] 的掐断轮同时段**，才可比 ----
        #
        # ⚠ 对照必须和实验"挨着跑"，不能先攒一个 baseline 再用很久。
        #   踩坑现场：早先的写法是先跑完整轮拿到 full_ms、再跑 3 轮掐断，
        #   两组之间隔着十几秒 —— 源站状态早变了，比出来的差异
        #   是**时间差**不是**代码差**。实测出现过「首轮基线 3103ms、
        #   掐断轮 6600ms」，判"没省下时间"，其实只是那会儿源站慢了。
        #   所以改成：每轮掐断之后**立刻**补一轮完整轮当对照，
        #   两边轮流跑，最终各取最好成绩。
        print("\n[1]+[2] 交替跑：完整轮（对照）↔ 2s 掐断轮（实验）")
        cut_ms_list: list[int] = []
        full_ms_list: list[int] = []
        cut_aborted: list[bool | None] = []    # 掐断轮：引擎自报"是不是被打断的"
        full_aborted: list[bool | None] = []   # 完整轮：应当都没被打断
        saw_stop_any = False
        for round_i in (1, 2, 3):
            # —— 实验：2s 掐断 ——
            size1 = logfile.stat().st_size if logfile.exists() else 0
            got = raw_get_disconnect(host, port, base, read_for=2.0)
            cut_ms = wait_done_ms(logfile, size1)
            tail = log_tail(logfile, size1)
            stopped = "客户端已断开" in tail
            if stopped:
                saw_stop_any = True
            if cut_ms is not None:
                cut_ms_list.append(cut_ms)
            cut_aborted.append(last_aborted(tail))
            print(f"    第 {round_i} 轮 · 掐断：收到 {got} 字节 / "
                  f"该轮耗时 {cut_ms}ms / 日志收手={stopped} / "
                  f"引擎自报 aborted={cut_aborted[-1]}")

            # —— 对照：紧跟着跑一轮完整的 ——
            size2 = logfile.stat().st_size if logfile.exists() else 0
            raw_get_disconnect(host, port, base, read_for=60.0)
            full_ms = wait_done_ms(logfile, size2)
            if full_ms is not None:
                full_ms_list.append(full_ms)
            full_aborted.append(last_aborted(log_tail(logfile, size2)))
            print(f"    第 {round_i} 轮 · 完整：该轮耗时 {full_ms}ms / "
                  f"引擎自报 aborted={full_aborted[-1]}")

        # 前提：完整轮要够长，2s 掐断才可能切在"还在干活"的中途。
        # 全都不够长时说明这一时段源站回得飞快，机制照样对、只是没有
        # "活可被打断" —— 这种情况**不作失败**，改成明说"本轮不判定"。
        measurable = bool(full_ms_list) and max(full_ms_list) > 4000
        if measurable:
            check("完整一轮长到足以让「2s 掐断」切在探测中途", True,
                  f"三轮完整轮最大 {max(full_ms_list)}ms")
        else:
            print(f"    ~ 完整轮最长只有 {max(full_ms_list or [0])}ms（源站回得快）"
                  f"—— 没有余地可省，本轮不判定收手效果")

        # 核心断言①：断开被识别到了（看日志，最直接的证据）
        check("服务端识别到客户端断开并收手", saw_stop_any,
              "日志里没有『客户端已断开』—— 断开检测根本没生效")

        # 核心断言②：**引擎自报的 aborted 为真**（确定性的机制信号）
        #
        # ⚠ 这一条是本测试的主判据，耗时那条已经删了。
        #   为什么删：耗时受源站快慢支配，实测同一本书波动 2.3s ~ 25.6s（5 倍），
        #   "完整一轮"经常碰巧比"掐断那轮"还短 —— 于是正确实现被反复判红
        #   （本文件历史上红了三次，三次都是这个原因，我改了三次阈值都没用，
        #    因为问题不在阈值，在于**这个指标本身就不随代码变化**）。
        #   换成 aborted 之后：它只取决于"该不该收手"，源站再快再慢都不影响。
        if measurable:
            n_cut_aborted = sum(1 for x in cut_aborted if x is True)
            check("引擎自报「这一轮被打断收手」（aborted=True）",
                  n_cut_aborted >= 1,
                  f"三轮掐断里没有一轮 aborted=True（实测 {cut_aborted}）"
                  f"—— 断开信号没传进引擎")
            # 反向：完整轮**不该**自报被打断。少了这条，一个恒返回 True 的
            # 实现也能让上面那条通过（假绿）。
            n_full_aborted = sum(1 for x in full_aborted if x is True)
            check("完整一轮没有被误判为「被打断」（aborted=False）",
                  n_full_aborted == 0,
                  f"有 {n_full_aborted} 轮完整搜索自报被打断（实测 {full_aborted}）"
                  f"—— aborted 恒为真，这个信号是坏的")
        else:
            print(f"    ~ 源站回得太快（{max(full_ms_list or [0])}ms），"
                  f"跳过 aborted 判定（掐断轮自报 {cut_aborted}）")

        # 参考信息（**不判定**）：耗时对照仍然打出来给人看趋势，
        # 但它不参与 pass/fail —— 理由同上，这个数会随环境漂移。
        if cut_ms_list and full_ms_list:
            print(f"    （参考·非判据：掐断轮耗时 {cut_ms_list} / "
                  f"完整轮耗时 {full_ms_list}；受源站快慢影响，仅看趋势）")

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
