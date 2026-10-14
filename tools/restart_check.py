"""验证「线上真的在跑这次同步的代码」。

为什么要有它
------------
**「同步成功」≠「新代码在跑」。**

服务是常驻进程，代码落盘后必须**重启**才生效。而"重启"这一步会
**静默失败** —— 历史上真实发生过三种形态：

  1. 端口还被旧进程占着 → 新进程 bind 失败、静默退出，你以为起来了；
  2. 守护进程和干活进程是两层，只杀上层 → 下层孤儿存活，继续跑旧代码；
  3. 托管方式变了（systemd / 手工 setsid / supervisor），脚本却还在按
     老姿势重启 → 命令"成功"了，但根本没碰到真正的那个进程。

三种的共同点：**只从服务器侧看，全都是"一切正常"**。表现只有一个 ——
"服务器上明明是新的，用户看到的还是旧的"。这类 bug 排查成本极高，
所以不能靠"我执行过重启命令"来判断，必须看**事实**。

判据（为什么是这样的判据）
--------------------------
    process_start_time + TOL >= newest_source_mtime

即：**真正干活的那个进程，必须是在最新代码落盘之后才启动的**。

它满足"只取决于机制本身"的要求：
  * 不看耗时（耗时随机器负载漂移，曾害得正确实现反复判红）；
  * 不看日志有没有输出（日志可以因为轮转死掉而空白）；
  * 只用两个单调量之间的**先后关系** —— 进程启动 vs 文件落盘，
    跟机器快慢、网络快慢无关。

启动时间怎么拿：`ps -o etimes=`（已运行秒数）反推。
  ⚠ 不用 `ps -o lstart`：它的格式受 locale 影响（中文环境下
  `%a %b` 会变成"周三 10月"），解析必炸。`etimes` 是**纯数字**。
  ⚠ 不用 `/proc/<pid>/stat` 的 starttime：它要配合 `btime` 换算，
  在容器/WSL 里 btime 可能是 0，算出来的时间点是错的（比 locale 更阴）。

退出码
------
    0  进程比代码新 —— 本次同步的代码确实在跑
    1  进程比代码**旧** —— 重启没生效，线上还在跑旧代码（这是要抓的那个）
    2  没找到干活的进程 —— 服务根本没起来
    3  探针不可用（没有 ps / 拿不到 etimes）—— 无法判定，不谎报成功

用法
----
    python tools/restart_check.py --root /home/ubuntu/noveldock
    python tools/restart_check.py --root . --pattern "run.py --host"
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time

# 容差：文件落盘与进程启动之间可能有毫秒级先后抖动（同一次同步里，
# 明显是"先写文件、后重启"，但文件系统时间戳精度可能只到秒）。
TOL = 2.0

# 扫哪些文件算"代码"。只扫代码目录 —— 绝不扫 cache/ library/ downloads/ logs/，
# 否则"刚下载完一本书"会让 logs 里的文件 mtime 变成最新，从而误判成
# "进程比代码旧"。判据必须只跟**会被加载的代码**有关。
CODE_GLOBS = (
    "run.py",
    "app/**/*.py",
    "app/**/*.html",
    "app/**/*.css",
    "app/**/*.js",
    "tools/*.py",
)


def judge(newest_mtime: float, start_ts: float, tol: float = TOL) -> bool:
    """进程启动时间是否"不早于"最新代码的落盘时间。

    抽成纯函数是为了能**被单测反证**：把 start_ts 调到代码之前，它必须返回 False。
    （这个项目有一条硬纪律：写完判据要故意破坏数据确认它会红，否则等于没测。）
    """
    return start_ts + tol >= newest_mtime


def newest_source(root: pathlib.Path) -> tuple[float, str]:
    """返回 (最新代码 mtime, 那个文件的相对路径)。"""
    best, where = 0.0, ""
    for pat in CODE_GLOBS:
        for p in root.glob(pat):
            if not p.is_file():
                continue
            try:
                t = p.stat().st_mtime
            except OSError:
                continue
            if t > best:
                # 统一成 POSIX 风格：这个脚本在 Linux 上跑，但测试在 Windows 上跑，
                # `str(relative_to())` 在两边分别给 `app/main.py` 与 `app\main.py`，
                # 会让"路径对不上"变成假红。as_posix() 两边一致。
                best, where = t, p.relative_to(root).as_posix()
    return best, where


def probe(pattern: str) -> list[tuple[int, float]] | None:
    """找匹配 pattern 的进程，返回 [(pid, 启动时刻的 time.time() 估算值)]。

    `pgrep -f` 匹配**整个命令行**，所以 pattern 用 `run.py --host` 这种
    特征串即可（serve.py 的命令行里不含它，不会误伤守护进程）。

    **探针不可用时返回 None**（不是空列表）—— 这两种情况必须分开：
      · 空列表 = "探针好用，但确实没有这个进程" → 服务根本没起来（退出码 2）
      · None   = "这台机器上根本没有探针"（Windows 没有 pgrep，MSYS 的 ps
                 也不支持 `-o etimes=`）→ **无法判定**，绝不能谎报成功（退出码 3）
    把它们混成一种，就会在开发机上"验证通过"，而线上到底重启没重启根本不知道。
    """
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    except FileNotFoundError:
        return None
    now = time.time()
    out: list[tuple[int, float]] = []
    for pid in (r.stdout or "").split():
        if not pid.isdigit():
            continue
        try:
            p = subprocess.run(["ps", "-o", "etimes=", "-p", pid],
                               capture_output=True, text=True)
        except FileNotFoundError:
            return None
        v = (p.stdout or "").strip()
        if v.isdigit():
            out.append((int(pid), now - int(v)))
    if (r.stdout or "").split() and not out:
        # 有 PID 但一个都拿不到 etimes= → ps 不支持这个格式，同样算探针不可用
        return None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".", help="项目根（代码目录的父目录）")
    ap.add_argument("--pattern", default="run.py --host",
                    help="干活的进程的命令行特征（默认 run.py --host）")
    ap.add_argument("--tol", type=float, default=TOL, help="容差秒数")
    a = ap.parse_args()

    root = pathlib.Path(a.root).resolve()
    if not (root / "app").is_dir():
        print(f"  ! {root} 下没有 app/ —— 不是项目根？")
        return 3

    newest, where = newest_source(root)
    if newest <= 0:
        print("  ! 没扫到任何代码文件")
        return 3

    procs = probe(a.pattern)
    if procs is None:
        print("  ! 这台机器上探针不可用（没有 pgrep / ps 不支持 -o etimes=）"
              " —— 无法判定，**不算通过**")
        return 3
    if not procs:
        print(f"  x 找不到干活的进程（pgrep -f {a.pattern!r} 无结果）"
              " —— 服务没起来")
        return 2

    pid, start = max(procs, key=lambda x: x[1])  # 取最新的那个
    now = time.time()
    age_sec = int(now - start)
    code_sec = int(now - newest)
    ok = judge(newest, start, a.tol)
    mark = "✓" if ok else "x"
    print(f"  {mark} 进程 pid={pid} 启动于 {age_sec}s 前；"
          f"最新代码 {where} 是 {code_sec}s 前")
    if not ok:
        print("     进程比源码旧 → 重启没生效，线上还在跑旧代码。"
              f"（--pattern {a.pattern!r}）")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
