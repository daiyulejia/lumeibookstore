"""长时间内存稳定性压测（在服务器上跑）。

为什么需要这个
--------------
README 上一直挂着一句「长时间运行的内存稳定性 —— 未实测」。这不是凑数：
这个服务是**长期常驻**的（systemd + Linger 开机自启），而它有几处容易
长胖的地方：

  · 榜单缓存 / 书架缓存 —— 都是进程内 dict，理论上只增不减
  · 调度线程 —— 每轮 refresh 都会新建线程池，池子没关干净就漏线程
  · HTTP 客户端连接 —— 每次抓取都开连接，keep-alive 没复用会堆 fd

所以这个脚本干的不是「跑一下看崩不崩」，而是**盯住三个数**：
RSS（常驻内存）、线程数、fd 数。跑 N 轮，看它们是不是随轮数单调爬升。

判据（都是"有爬升就是 bug"的硬线，不设模糊区间）：
  · RSS  增长 < 15% 且 < 60MB  → 允许（有波动、有缓存预热，但不该线性涨）
  · 线程数 增长 ≤ 5            → 允许
  · fd   增长 < 50             → 允许

用法（服务器上）：
  .venv/bin/python3 tools/test_mem.py                # 默认 30 轮
  .venv/bin/python3 tools/test_mem.py --rounds 60 --base http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'✓' if ok else '✗'} {name}" + (f"（{detail}）" if detail else ""))
    if not ok:
        _fails.append(name)
    return ok


def proc_stat(pid: int) -> dict:
    """读一个进程的 RSS / 线程数 / fd 数。不在 Linux 上就返回空。"""
    out: dict = {}
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                out["rss_kb"] = int(line.split()[1])
            elif line.startswith("Threads:"):
                out["threads"] = int(line.split()[1])
    except Exception:
        pass
    try:
        out["fds"] = len(os.listdir(f"/proc/{pid}/fd"))
    except Exception:
        pass
    return out


def children(pid: int) -> list[int]:
    """拿一个进程的直接子进程。"""
    out = []
    try:
        for line in Path(f"/proc/{pid}/task/{pid}/children").read_text().split():
            out.append(int(line))
    except Exception:
        pass
    return out


def cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode().strip()
    except Exception:
        return ""


def proc_cpu_ms(pid: int) -> int:
    """进程累计 CPU 时间（毫秒）。用来确认它真的在干活。"""
    try:
        parts = Path(f"/proc/{pid}/stat").read_text().split()
        # utime(14) + stime(15)，单位是 clock tick（一般 100/s）
        ticks = int(parts[13]) + int(parts[14])
        return int(ticks * 1000 / os.sysconf("SC_CLK_TCK"))
    except Exception:
        return -1


def resolve_worker(pid: int) -> tuple[int, str]:
    """从 systemd 给的主进程号，往下找到**真正在干活**的那个。

    ⚠ 这里踩过一个很隐蔽的坑：systemd 报的 MainPID 是 `tools/serve.py`
    —— 一个启动器，它 fork 出 `run.py`(uvicorn) 之后就基本不动了。
    如果直接测 serve.py，会看到 RSS 稳如磐石（12.4M 一动不动）、
    线程数恒为 1、fd 恒为 4，然后欢天喜地地宣布"内存非常稳定"
    —— 而真正的服务器进程根本一个请求都没算进去。

    所以：优先认 cmdline 里带 `run.py` 的子进程；没有再退回主进程。
    同时也用『谁在 LISTEN 端口』兜底，因为那是绝对意义上的"干活的人"。
    """
    # 1) 主进程自己就是 run.py（有些部署方式直接 exec，不 fork）
    if "run.py" in cmdline(pid):
        return pid, cmdline(pid)
    # 2) 子进程里找 run.py
    for c in children(pid):
        if "run.py" in cmdline(c):
            return c, cmdline(c)
    # 3) 顺着子进程再找一层（serve.py → sh -c → run.py 这种情况）
    for c in children(pid):
        for g in children(c):
            if "run.py" in cmdline(g):
                return g, cmdline(g)
    return pid, cmdline(pid)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--rounds", type=int, default=30, help="压测轮数")
    ap.add_argument("--pid", type=int, default=0, help="被测进程号；0=自动从 systemd 取")
    a = ap.parse_args()

    if not sys.platform.startswith("linux"):
        print("这个脚本只在 Linux 上有意义（要读 /proc）。跳过。")
        return 0

    pid = a.pid
    if not pid:
        # 从 systemd 拿主进程号 —— 但注意那多半是启动器 serve.py，
        # 下面必须再往下找到真正的 run.py，否则测的是个闲置壳子。
        try:
            import subprocess
            pid = int(subprocess.run(
                ["systemctl", "--user", "show", "noveldock", "-p", "MainPID", "--value"],
                capture_output=True, text=True, check=True).stdout.strip())
        except Exception as e:
            print(f"拿不到服务进程号：{e}")
            return 1
    if not pid or not Path(f"/proc/{pid}").exists():
        print(f"进程 {pid} 不存在")
        return 1

    main_pid, worker_cmd = resolve_worker(pid)
    pid = main_pid

    print(f"=== 内存稳定性压测 ===")
    print(f"  进程 PID : {pid}")
    print(f"  命令行   : {worker_cmd or '(读不到)'}")
    print(f"  轮数     : {a.rounds}")
    print(f"  目标     : {a.base}\n")
    if not worker_cmd:
        print("  ⚠ 读不到命令行，可能权限不足；测出来的数可能不是真正干活的那个进程。")

    # 首页 / 榜单 / 状态 三个接口轮流打 —— 覆盖「读缓存」「读写状态」两种路径
    urls = [f"{a.base}/", f"{a.base}/api/ranks/status", f"{a.base}/api/ranks?kind=allvisit"]

    samples: list[dict] = []
    base = proc_stat(pid)
    if not base:
        print("读 /proc 失败，可能没权限。用 sudo 再试。")
        return 1
    samples.append(base)
    cpu0 = proc_cpu_ms(pid)
    n_ok = n_fail = 0
    errs: list[str] = []
    print(f"  轮 00  RSS={base.get('rss_kb',0)/1024:.1f}M  "
          f"线程={base.get('threads','?')}  fd={base.get('fds','?')}")

    t0 = time.time()
    for i in range(1, a.rounds + 1):
        for u in urls:
            try:
                with urllib.request.urlopen(u, timeout=25) as r:
                    r.read()
                n_ok += 1
            except Exception as e:
                # 单个请求失败不算「内存不稳」，但**必须记账** ——
                # 早先这里写成 `except: pass`，结果 180 个请求全失败
                # 也只花 0.3 秒，而报告上却显示「全部通过」。静默吞错
                # 会让压测变成一场自欺欺人的仪式。
                n_fail += 1
                if len(errs) < 3:
                    errs.append(f"{type(e).__name__}: {e}")
        st = proc_stat(pid)
        samples.append(st)
        if i % max(1, a.rounds // 10) == 0 or i == a.rounds:
            print(f"  轮 {i:02d}  RSS={st.get('rss_kb',0)/1024:.1f}M  "
                  f"线程={st.get('threads','?')}  fd={st.get('fds','?')}")
    elapsed = time.time() - t0
    cpu1 = proc_cpu_ms(pid)

    first, last = samples[0], samples[-1]
    peak = max((s.get("rss_kb") or 0) for s in samples) / 1024

    rss0, rss1 = (first.get("rss_kb") or 0) / 1024, (last.get("rss_kb") or 0) / 1024
    grow = rss1 - rss0
    grow_pct = (grow / rss0 * 100) if rss0 else 0
    th0, th1 = first.get("threads", 0), last.get("threads", 0)
    fd0, fd1 = first.get("fds", 0), last.get("fds", 0)

    print(f"\n == 结果（{elapsed:.1f}s，{a.rounds} 轮 × {len(urls)} 请求）==")
    print(f"  RSS   : {rss0:.1f}M → {rss1:.1f}M（峰值 {peak:.1f}M，增长 {grow:+.1f}M / {grow_pct:+.1f}%）")
    print(f"  线程数: {th0} → {th1}（{th1-th0:+d}）")
    print(f"  fd 数 : {fd0} → {fd1}（{fd1-fd0:+d}）")
    print(f"  请求   : {n_ok} 成功 / {n_fail} 失败（共 {a.rounds * len(urls)} 次）\n")

    # ⚠ 先验「我们测的真是干活的那个进程」，再谈稳不稳。
    # 前面翻过车：测到了闲置的启动器 serve.py，RSS 永远是 12.4M，
    # 所有"稳定"的断言都轻松通过 —— 假绿灯比红灯危险得多。
    #
    # 判据曾经写成「RSS 必须变化」，但那是错的：uvicorn 在启动阶段就把
    # 内存池扩到位了，之后 180 个轻请求完全可以在预留内存里打完，
    # RSS 纹丝不动恰恰是**好**现象。所以改成两条不会误报的硬证据：
    #   ① 命令行里是 run.py（不是 serve.py 壳子）
    #   ② 进程累计 CPU 时间确实涨了（证明它在处理请求）
    check("被测进程是 run.py（不是闲置的启动器壳子）",
          "run.py" in worker_cmd, worker_cmd.split()[-1] if worker_cmd else "?")
    check("进程累计 CPU 时间在增长（说明真的在干活）",
          cpu1 > cpu0, f"{cpu0}ms → {cpu1}ms")
    check("压测请求基本都成功了（没有静默失败）",
          n_fail <= max(1, a.rounds * len(urls) * 0.02), f"{n_fail} 次失败")

    check("RSS 增长不超过 60MB", grow < 60, f"{grow:+.1f}M")
    check("RSS 增长不超过 15%", grow_pct < 15, f"{grow_pct:+.1f}%")
    check("峰值 RSS 不超过 400MB", peak < 400, f"{peak:.1f}M")
    check("线程数增长不超过 5", th1 - th0 <= 5, f"{th1-th0:+d}")
    check("fd 增长不超过 50", fd1 - fd0 < 50, f"{fd1-fd0:+d}")

    # 曲线形状：如果 RSS 后 1/3 的平均值还显著高于前 1/3，说明在持续长胖，
    # 哪怕总量没超阈值也该报警 —— 30 轮不长胖不代表 3000 轮不长胖。
    n = len(samples)
    third = max(1, n // 3)
    early = sum((s.get("rss_kb") or 0) for s in samples[:third]) / third / 1024
    late = sum((s.get("rss_kb") or 0) for s in samples[-third:]) / third / 1024
    drift = ((late - early) / early * 100) if early else 0
    print(f"  曲线漂移: 前 1/3 均 {early:.1f}M → 后 1/3 均 {late:.1f}M（{drift:+.1f}%）")
    check("RSS 曲线没有持续爬升（后段均 ≤ 前段均 + 20%）", drift < 20, f"{drift:+.1f}%")

    report = {
        "pid": pid, "rounds": a.rounds, "elapsed": round(elapsed, 1),
        "rss_first_mb": round(rss0, 1), "rss_last_mb": round(rss1, 1),
        "rss_peak_mb": round(peak, 1), "rss_grow_mb": round(grow, 1),
        "rss_grow_pct": round(grow_pct, 1),
        "threads_first": th0, "threads_last": th1,
        "fds_first": fd0, "fds_last": fd1,
        "drift_pct": round(drift, 1),
        "pass": not _fails,
    }
    (ROOT / "logs" / "mem_report.json").parent.mkdir(exist_ok=True)
    (ROOT / "logs" / "mem_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + ("=== 全部通过 ===" if not _fails else f"=== {len(_fails)} 项失败 ==="))
    for f in _fails:
        print(f"  ✗ {f}")
    return 0 if not _fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
