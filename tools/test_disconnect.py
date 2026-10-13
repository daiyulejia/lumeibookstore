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
# 候选关键词：用真实书名（要能出网抓、耗时够长，才切得进"中途"）。
#
# ⚠⚠ 为什么是**一列**而不是一个：源站会缓存（wyshu_index.json + 各源 HTTP 缓存），
#   同一个词在本机搜过一遍之后，第二轮就 27ms 秒回了 —— 于是
#   `measurable=False`，整套接近空转（ship 里踩过，见下方 else 分支的警告）。
#   固定单个词时，该词只要被搜过一次就永久失效，**这个套件在 ship 里
#   从此没有牙**。改成一列：逐个试，谁在那个时段还能耗时 > 4s 就用谁。
#   仍是"尽力而为"（全都被缓存时照样不判定），但把命中概率从"几乎必然失效"
#   拉回"多数时候至少有一个冷词"。
KWS = [
    "三体",
    "斗破苍穹",
    "诡秘之主",
    "凡人修仙传",
    "遮天",
]
# 兼容旧引用（其它地方 / 人工调试可能还读 KW）
KW = KWS[0]


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
    """读 `path` 里 start_size 之后的新增内容（按字节偏移）。

    ⚠⚠ 这里必须防**日志轮转/截断**：`start_size` 是调用方在起请求**之前**
    记下的文件大小。若这两者之间 app.log 被轮转（midnight）或被截断，
    `start_size` 会**大于**新文件大小 —— 此时 `f.seek(start_size)` 会
    停在文件末尾之后，`f.read()` 返回**空串** → 调用方看到"日志里啥也没有"
    → 误判成"收手链路没生效"（假红）。

    踩过：2026-10-13 ship 跑 disconnect 时 6 轮全部 `耗时 None /
    aborted=None`，而手动复现同样的关键词却一切正常。差异在于当时
    app.log 还处在「轮转失败 → 静默停写」的坏状态（见 logging_setup.py
    的 _SafeTimedRotatingFileHandler），文件 mtime 冻结、字节数不增长，
    于是"新增内容"恒为空。日志基建修好后此现象消失，但**判据本身
    不该依赖"文件一定单调增长"** —— 轮转是正常运维事件。

    修法：当 `start_size > 当前大小`（说明轮转/截断过），退化为**从头读**
    （宁可多读一点，也要保证不把"有内容"误读成"没内容"）。
    """
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            f.seek(min(start_size, size))
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

        # ---- [1] 量完整一轮的耗时：**与 [2] 的掐断轮同时段**，才可比 ----
        #
        # ⚠ 对照必须和实验"挨着跑"，不能先攒一个 baseline 再用很久。
        #   踩坑现场：早先的写法是先跑完整轮拿到 full_ms、再跑 3 轮掐断，
        #   两组之间隔着十几秒 —— 源站状态早变了，比出来的差异
        #   是**时间差**不是**代码差**。实测出现过「首轮基线 3103ms、
        #   掐断轮 6600ms」，判"没省下时间"，其实只是那会儿源站慢了。
        #   所以改成：每轮掐断之后**立刻**补一轮完整轮当对照，
        #   两边轮流跑，最终各取最好成绩。
        #
        # ⚠⚠ 为什么要**逐个试关键词**：见 KWS 的注释。同一个词被搜过一次
        #   就秒回了（measurable=False → 整套空转）。这里对每个候选词先跑
        #   一轮完整轮"探路"：只要它还能耗时 > 4s（说明有真网络工作在跑），
        #   就把它作为本次的关键词，进入正式的三轮交替；一个都不够长时，
        #   退化为"不判定"并在 else 分支显式警告空转。
        def run_rounds(base: str) -> tuple[list[int], list[int], list[bool | None], list[bool | None], bool]:
            """跑 3 轮「掐断 ↔ 完整」交替，返回各轮数据。"""
            cut_ms_list: list[int] = []
            full_ms_list: list[int] = []
            cut_aborted: list[bool | None] = []
            full_aborted: list[bool | None] = []
            saw_stop = False
            for round_i in (1, 2, 3):
                # —— 实验：2s 掐断 ——
                size1 = logfile.stat().st_size if logfile.exists() else 0
                got = raw_get_disconnect(host, port, base, read_for=2.0)
                cut_ms = wait_done_ms(logfile, size1)
                tail = log_tail(logfile, size1)
                stopped = "客户端已断开" in tail
                if stopped:
                    saw_stop = True
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
            return cut_ms_list, full_ms_list, cut_aborted, full_aborted, saw_stop

        print("\n[0] 挑一个还热不起来的冷关键词（逐个探路：完整轮耗时 > 4s 才算有牙）")
        chosen_kw = ""
        for cand in KWS:
            cbase = f"/api/search?kw={urllib.parse.quote(cand)}" + (f"&t={token}" if token else "")
            s0 = logfile.stat().st_size if logfile.exists() else 0
            raw_get_disconnect(host, port, cbase, read_for=60.0)
            probe_ms = wait_done_ms(logfile, s0)
            print(f"    · 「{cand}」完整一轮 {probe_ms}ms")
            if probe_ms is not None and probe_ms > 4000:
                chosen_kw = cand
                break
        if not chosen_kw:
            chosen_kw = KW
            print(f"    ~ 所有候选词都回得飞快（都进缓存了）；"
                  f"退化为用「{chosen_kw}」，本轮大概率不判定")

        base = f"/api/search?kw={urllib.parse.quote(chosen_kw)}" + (f"&t={token}" if token else "")
        print(f"\n[1]+[2] 交替跑：完整轮（对照）↔ 2s 掐断轮（实验）· 关键词「{chosen_kw}」")
        cut_ms_list, full_ms_list, cut_aborted, full_aborted, saw_stop_any = run_rounds(base)

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
            # ⚠⚠ 关键鉴别：**一轮 search.done 都没读到** 时，不能默认
            #   "源站回得快" —— 那也可能是**日志根本没在写**（曾经的
            #   Windows 轮转静默死亡 bug 就是这个征兆：文件 mtime 冻结、
            #   字节数不增长，于是这里 6 轮全是 None / aborted=None）。
            #   两者症状一样（都是 measurable=False），但根因天差地别：
            #   一个是环境正常、一个是**日志基建坏了**（会让所有排障失明）。
            #   所以显式区分：整个 app.log 在这次运行期间**一点没长** → 报警。
            if not cut_aborted and not full_aborted:
                grew = (logfile.stat().st_size if logfile.exists() else 0) > 0
                print("    ⚠ 本轮**一轮 search.done 都没读到**。两种可能：")
                print("      (a) 源站极快，6 轮都在缓存里秒回（正常，忽略即可）；")
                print("      (b) 日志没在写（app.log 冻结）—— 这才是要查的。")
                print(f"      当前 logs/app.log 存在且非空：{grew}")
                print("      排查：`tail -n 5 logs/app.log` 看 mtime 是不是停在过去；"
                      "若是，见 app/logging_setup.py 的 _SafeTimedRotatingFileHandler。")

        # 核心断言①：断开被识别到了（看日志，最直接的证据）
        #
        # ⚠ 这条也必须尊重 `measurable` 这个前提 —— 判据是**物理前提的**
        #   而不是"为了让它绿而放宽"：
        #   断开检测（`_dead()` → 收手）只有在**服务端还在干活**的时候
        #   才有意义。如果完整一轮只要 0ms（源站命中缓存/回得飞快），
        #   那服务端在我们掐断之前**早就跑完了**，自然什么也没收手 ——
        #   这不是"检测坏了"，是**根本没有可检测的对象**。
        #   ship 里踩过：['test_disconnect.py'] 红，日志写着
        #   「完整轮最长只有 0ms（源站回得快）—— 没有余地可省，本轮不判定」，
        #   然后下一行照样判红 —— 自相矛盾。aborted 那条已经做了这个
        #   `else: 跳过` 的分支，① 当时漏了。
        if measurable:
            check("服务端识别到客户端断开并收手", saw_stop_any,
                  "日志里没有『客户端已断开』—— 断开检测根本没生效")
        else:
            print("    ~ 源站回得太快，服务端在掐断前已跑完 —— "
                  "不存在『可被识别的断开』，① 同样不判定")

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
            # ⚠⚠ 这里必须**明显提示**，不能静默跳过。
            #   后果很严重：`measurable=False` 时两个核心断言都不判定，
            #   套件只剩一句 health 断言 —— **看着全绿，实际什么都没验**。
            #   为什么会恒为 False：搜索结果是**服务端缓存**的，
            #   同一个关键词跑第二遍完整轮就 0ms 返回了（实测如此）。
            #   所以这一整套只有在**冷缓存**（换关键词 / 清缓存）时才有牙。
            print("    ⚠ 注意：本轮两个核心断言（断开收手 / aborted）"
                  "都未判定 —— 整套接近空转。")
            print("      想真验收手链路：换一个没搜过的关键词（改 test_disconnect.py 的 KW），"
                  "或先清 cache/ 里的搜索缓存再跑。")

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
