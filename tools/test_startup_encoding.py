# -*- coding: utf-8 -*-
"""启动横幅的编码加固 —— **一个装饰字符不许把服务打死在监听之前**。

为什么值得单独测
----------------
`run.py` 的启动横幅里带 `⇄`（U+21C4，借解释器提示那一段）。Windows 上
stdout 一旦不是控制台而是**管道**，编码就是 cp936（GBK），而 GBK 里没有
`⇄` —— `print()` 直接抛

    UnicodeEncodeError: 'gbk' codec can't encode character '\\u21c4'

异常从 `_borrow_exe()` 一路冒到 `main()` 外面，进程在 `uvicorn.run()` **之前**
就退了。守护脚本（`tools/serve.py`）看到退出就 60 秒后重启，于是：

    2026-11-13 00:00:44 → 09:17:57，`logs/server-2026-11-13.log` 里
    **542 次「启动 / 服务退出（code=1，存活 2s）/ 60s 后重启」**、
    557KB 全是同一条栈。

产品侧的表现是「双击之后窗口一直滚 traceback，网页打不开」，而人看不出
是哪个字符惹的 —— 栈里那行还是乱码。这不是"环境问题"：**环境没法编码
一个装饰字符，不该等于服务起不来**。

判据怎么定（三问自查）
--------------------
① 会不会只因环境变：用 `PYTHONIOENCODING=gbk` 显式构造编码，不依赖本机
   默认代码页，也不看耗时。
② 把功能拆掉还绿吗：A 组第二段就是**不调加固**跑同一条打印 —— 它必须
   rc≠0。这条同时是永久反证：证明这个洞真实存在、判据有牙。
③ 只验正向没验反向：C 组验「能编码的字符不许被顺手改掉」、B 组验
   「中文不许变成乱码」、D 组验「不是 TextIOWrapper 的流不许拦住启动」。

用法： python tools/test_startup_encoding.py
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import run  # noqa: E402

FAILS: list[str] = []
OK = 0


def check(cond, name, detail: str = "") -> None:
    global OK
    if cond:
        OK += 1
        print(f"  ✓ {name}")
    else:
        FAILS.append(f"{name}{('：' + detail) if detail else ''}")
        print(f"  ✗ {name}{('：' + detail) if detail else ''}")


ARROW = "\u21c4"          # GBK 编码不了的那个字符
CJK = "当前解释器不在白名单"  # GBK 编码得了、而且用户必须看懂的字


def _py(code: str, encoding: str) -> subprocess.CompletedProcess:
    """在指定 stdio 编码下跑一小段代码，返回 CompletedProcess。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = encoding
    env.pop("PYTHONUTF8", None)  # 别让它把编码悄悄改回 utf-8
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT, env=env, capture_output=True, timeout=120,
        encoding=encoding, errors="replace",
    )


print("A. 真实复现：GBK 管道下打印横幅里的箭头")
# 这两段唯一的差别就是有没有先调 _harden_stdio() —— 也就是产品的那一行。
WITH_GUARD = (
    "import sys; sys.path.insert(0, '.'); import run; run._harden_stdio(); "
    f"print('  {ARROW} {CJK}')"
)
NO_GUARD = (
    "import sys; sys.path.insert(0, '.'); import run; "
    f"print('  {ARROW} {CJK}')"
)
on = _py(WITH_GUARD, "gbk")
check(on.returncode == 0,
      "加固后：GBK 管道里打印 ⇄ 不再崩（rc=0）",
      f"rc={on.returncode} stderr={on.stderr[-300:]}")
check("UnicodeEncodeError" not in on.stderr,
      "加固后：stderr 里没有 UnicodeEncodeError",
      on.stderr[-300:])
off = _py(NO_GUARD, "gbk")
check(off.returncode != 0,
      "反证：不调加固时同一条打印真的会死（证明这个洞存在、判据有牙）",
      f"rc={off.returncode}（本应 ≠0）")
check("UnicodeEncodeError" in off.stderr,
      "反证的死因就是编码，不是别的错",
      off.stderr[-300:])

print()
print("B. 只退化不能编码的字符，中文不许变乱码")
with tempfile.TemporaryDirectory() as td:
    path = os.path.join(td, "out.txt")
    with open(path, "w", encoding="gbk", errors="strict") as fh:
        run._harden_stdio([fh])
        print(f"  {ARROW} {CJK}", file=fh)
    with open(path, encoding="gbk", errors="replace") as fh:
        got = fh.read()
    check(CJK in got, "中文原样落盘（没有变成 ? 串）", repr(got))
    check(ARROW not in got, "编码不了的箭头退化了（没有抛异常）", repr(got))

print()
print("C. 反向：能编码的时候什么都不许动")
buf = io.StringIO()
run._harden_stdio([buf])
errs = getattr(buf, "errors", None)
check(errs is None or errs == "strict",
      "非 TextIOWrapper 的流：加固失败也不许改它的行为、更不许抛",
      f"errors={errs!r}")
saved = sys.stdout
try:
    # 真·TextIOWrapper 且编码得了 → errors 必须保持 strict，
    # 否则等于为了一个箭头把全程序的编码错误都吞了。
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "utf8.txt")
        with open(path, "w", encoding="utf-8", errors="strict") as fh:
            run._harden_stdio([fh])
            check(fh.errors == "strict",
                  "utf-8 流：加固不把 errors 改成 replace（不吞真错误）",
                  f"errors={fh.errors!r}")
            print(f"  {ARROW} {CJK}", file=fh)
        with open(path, encoding="utf-8") as fh:
            got = fh.read()
    check(ARROW in got and CJK in got,
          "utf-8 流：箭头和中文都原样输出（没被替换）", repr(got))
finally:
    sys.stdout = saved

print()
print("D. 端到端：main() 里真走到带 ⇄ 的那一行，GBK 输出也不许死")
ALT = {"exe": "C:/Python312/python.exe", "rule": "Python", "version": "3.12"}
hint = run._borrow_hint(ALT)
check(ARROW in hint,
      "借解释器提示里确实带着 GBK 编码不了的 ⇄（洞是真的，不是假想）",
      repr(hint[:40]))

# 只把「防火墙检测 + 找已放行的解释器」这两件依赖机器状态的事换掉，
# 打印仍然是产品自己的 `_borrow_hint()`；argparse / 横幅 / 安全层 /
# 定时器全走真实 main()。stdout 换成 GBK 真流，和线上那条崩溃路径一致。
with tempfile.TemporaryDirectory() as td:
    path = os.path.join(td, "main.txt")
    out = open(path, "w", encoding="gbk", errors="strict")
    old_argv, old_stdout, old_borrow = sys.argv, sys.stdout, run._borrow_exe
    old_run = run.uvicorn.run
    try:
        # 为什么是 0.0.0.0：只有这条路 main() 才会去借解释器、才会打那行 ⇄。
        # （`--no-check` 会让它跳过 _borrow_exe，所以这里**不能**带。）
        sys.argv = ["run.py", "--host", "0.0.0.0", "--port", "18000", "--no-sched"]
        sys.stdout = out
        run._borrow_exe = lambda port: print(run._borrow_hint(ALT), flush=True)
        run.uvicorn.run = lambda *a, **k: None  # 不真监听
        crash = ""
        try:
            run.main()
        except BaseException as e:  # noqa: BLE001  main 里任何异常都算没起来
            crash = f"{type(e).__name__}: {e}"
    finally:
        sys.stdout = old_stdout
        sys.argv = old_argv
        run._borrow_exe = old_borrow
        run.uvicorn.run = old_run
        out.close()
    check(not crash, "main() 在 GBK 标准输出下走完全程（没有半路退出）", crash)
    with open(path, encoding="gbk", errors="replace") as fh:
        body = fh.read()
    check("小说下载器已启动" in body,
          "横幅真的打出来了（不是「没走到那行」蒙过去的）", repr(body[:200]))
    check("当前解释器不在防火墙白名单里" in body,
          "带 ⇄ 的那行真的打出来了（端到端覆盖的正是崩溃点）", repr(body[:400]))

print()
if FAILS:
    print(f"❌ {len(FAILS)} 项未通过：")
    for f in FAILS:
        print(f"   - {f}")
    sys.exit(1)
print(f"✅ 全部通过（{OK} 项）")
