"""`tools/restart_check.py` 的判据回归（纯本地，不需要服务/Chrome）。

为什么值得单独立一套测试
------------------------
restart_check 是"部署链"上的**最后一道闸**：它决定 `ship.py` 会不会因为
"代码同步了、但线上没重启"而**中止上线**。这种闸门有个典型的坏法 ——
**闸门永远开着**（恒返回"通过"），于是它看起来在工作，其实什么都没拦。
本项目已经在这类"看着在测、其实恒真"的判据上栽过 11 次，所以：

**本文件里每一条判据都配了反证**（故意喂"应该判红"的输入，断言它真的红）。
没有反证的断言不算数。

另外这层测试能在本地跑是有意的：`restart_check.py` 本身只能在 Linux 上跑
（要 pgrep + `ps -o etimes=`），而 Windows 开发机上没有这些 —— 所以
**判定逻辑（judge）与探针（probe）必须拆开**，前者纯函数、可本地测。

用法： python tools/test_restart_check.py
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
OK = 0
BAD = 0

spec = importlib.util.spec_from_file_location("restart_check", TOOLS / "restart_check.py")
rc_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc_mod)


def check(name: str, cond: bool, extra: str = "") -> None:
    global OK, BAD
    if cond:
        OK += 1
        print(f"  ✓ {name}")
    else:
        BAD += 1
        print(f"  ✗ {name}  {extra}")


def _fake_root(tmp: pathlib.Path) -> pathlib.Path:
    """造一个像项目根的最小目录：只有 app/ 与 logs/。"""
    (tmp / "app").mkdir(parents=True, exist_ok=True)
    (tmp / "logs").mkdir(parents=True, exist_ok=True)
    return tmp


def main() -> int:
    now = time.time()

    print("── 1. judge：进程启动 vs 代码落盘 的先后 ──")
    # 正常情况：先落盘(now-100) 再启动(now-10) → 通过
    check("进程比代码新 → 通过", rc_mod.judge(now - 100, now - 10) is True)
    # ⚠ 反证：这正是要抓的那个 bug（重启没生效，进程还是旧的）→ 必须判红
    check("**进程比代码旧 → 判红**（反证：这是要抓的场景）",
          rc_mod.judge(now - 10, now - 100) is False)
    # 容差边界：文件系统时间戳精度可能只到秒，同一次同步里两者可以"同时"
    check(f"容差 {rc_mod.TOL:g}s 之内（代码略新于进程）→ 通过",
          rc_mod.judge(now, now - rc_mod.TOL + 0.5) is True)
    check(f"超出容差 {rc_mod.TOL:g}s（代码明显新于进程）→ 判红",
          rc_mod.judge(now, now - rc_mod.TOL - 5) is False)

    print("\n── 2. newest_source：只跟「会被加载的代码」有关 ──")
    with tempfile.TemporaryDirectory() as d:
        tmp = _fake_root(pathlib.Path(d))
        code = tmp / "app" / "main.py"
        code.write_text("# code\n", encoding="utf-8")
        os_old = now - 3600
        os.utime(code, (os_old, os_old))
        # 数据目录里放一个"刚刚写过"的文件 —— 真实场景：刚下载完一本书、
        # 刚写了一条日志。若判据把 logs/ 也算进"源码"，就会误判成
        # "进程比代码旧"→ 每次同步都假红，闸门变成噪音，进而被人忽略。
        noisy = tmp / "logs" / "app.log"
        noisy.write_text("x\n", encoding="utf-8")
        os.utime(noisy, (now, now))
        newest, where = rc_mod.newest_source(tmp)
        check("logs/ 里的最新文件**不许**左右判据（否则每跑一次假红）",
              where == "app/main.py", f"实际取到 {where!r}")
        check("取到的 mtime 就是那份代码的 mtime",
              abs(newest - os_old) < 1e-6, f"newest={newest}")

    print("\n── 3. 扫描范围契约（防止以后被悄悄放宽）──")
    data_dirs = ("cache/", "library/", "downloads/", "logs/", "dist/")
    bad = [g for g in rc_mod.CODE_GLOBS if g.startswith(data_dirs)]
    check("CODE_GLOBS 不许包含数据/产物目录", not bad, f"混进了：{bad}")
    check("CODE_GLOBS 至少覆盖 app/ 与 run.py",
          any(g.startswith("app/") for g in rc_mod.CODE_GLOBS)
          and "run.py" in rc_mod.CODE_GLOBS)

    print("\n── 4. 探针不可用时**绝不谎报成功** ──")
    with tempfile.TemporaryDirectory() as d:
        tmp = _fake_root(pathlib.Path(d))
        r = subprocess.run([sys.executable, str(TOOLS / "restart_check.py"),
                            "--root", str(tmp)],
                           capture_output=True, text=True, cwd=str(ROOT))
        if shutil.which("pgrep") is None:
            # 本机（Windows）没有 pgrep —— 正是"探针不可用"的真实场景。
            # 此时**必须**是退出码 3（无法判定），不能是 0（谎报通过）。
            check("本机无 pgrep → 退出码 3，不谎报成功", r.returncode == 3,
                  f"rc={r.returncode} out={r.stdout.strip()[:80]}")
        else:
            check("有 pgrep 但没有该进程 → 非零退出（不是 0）",
                  r.returncode != 0, f"rc={r.returncode}")
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run([sys.executable, str(TOOLS / "restart_check.py"),
                            "--root", d],
                           capture_output=True, text=True, cwd=str(ROOT))
        check("--root 不是项目根（没有 app/）→ 退出码 3，不谎报成功",
              r.returncode == 3, f"rc={r.returncode}")

    print("\n" + "=" * 62)
    print(f"通过 {OK} · 失败 {BAD}")
    print("=" * 62)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
