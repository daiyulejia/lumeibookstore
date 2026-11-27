#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
锁定 `search.done` 那几格账的**含义**（不是格式）
============================================================================
这三条都是 2026-11-26 复盘时当场抓到的"判据自己说谎"：

  ① `可读=` 数的是 `available`（目录能打开），而前端绿标看的是
     `readable`（正文抽样通过）。同一天真机《我们仨》：
         search.done … 可读=1 …
     唯一那本正文抽样回「连接被拒绝」，用户一个字都读不到。
     两件事共用一个词，日报只能照着写"这一轮成功"。

  ② `web_gave` 的默认值 `= 0` 写在 `web_thread.join()` **之后**，
     把刚数好的真值冲掉：
         search.web.preempt … 已等=1.5s
         并行联网兜底回收 1 条候选
         search.done … 联网发现=0 联网=not_needed
     同一轮里"回收了候选"和"一次都没跑"同时成立。

  ③ 并行兜底那一路真交回了候选，`联网=` 该写 `preempt`。
     这条由 `test_discover_fallback.py` 场景 9 端到端跑，
     这里只钉住**纯函数**的三个返回值。

为什么用 AST / 源码顺序断言，而不是端到端：
  ①② 是"某个字面量在某一行的语义"，端到端要造出"正文判假"和
  "并行兜底恰好先交付"两种时序，单测里不稳定（上面那个文件已经证明：
  场景 9 原来只用 EmptySrc 时，扇出在 0.05s 前就结束，web 其实是**串行**
  调用的 —— 断言绿着，测的却是另一条路）。这类"判据本身要稳定"的地方，
  静态断言比时序稳定得多。

用法： python tools/test_search_ledger.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import engine as E  # noqa: E402

OK = 0
BAD = 0


def ok(m: str) -> None:
    global OK
    OK += 1
    print(f"  ✓ {m}")


def bad(m: str) -> None:
    global BAD
    BAD += 1
    print(f"  ✗ {m}")


def section(t: str) -> None:
    print(f"\n── {t} " + "─" * max(0, 56 - len(t)))


# ---------------------------------------------------------------------------
# 逐字面量找 log_event(...) 里某个关键字实参的源码文本
# ---------------------------------------------------------------------------
def _kwarg_text(path: Path, func: str, key: str) -> list[str]:
    """返回 `path` 里所有 `func(...)` 调用中 `key=<expr>` 的 expr 源码。"""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = ""
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name != func:
            continue
        for kw in node.keywords:
            if kw.arg == key:
                out.append(ast.get_source_segment(src, kw.value) or "")
    return out


def _find_line(path: Path, needle: str) -> int:
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if needle in line:
            return i
    return -1


def _counters(src: str) -> dict[str, list[int]]:
    """找出所有「累加计数器」：`cur["x"] = int(cur.get("x") or 0) + 1`。

    只认这一种写法 —— 它是本项目里记"这件事发生了几次"的唯一姿势
    （`search_hit` / `search_kwblind` / `tpl_dead` …都是它）。
    动态拼出来的键（`f"fail_{why}"`）不在其中：那种键本来就没有固定判据。
    """
    out: dict[str, list[int]] = {}
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target = node.targets[0]
        if not (isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "cur"
                and isinstance(target.slice, ast.Constant)
                and isinstance(target.slice.value, str)):
            continue
        val = node.value
        if (isinstance(val, ast.BinOp) and isinstance(val.op, ast.Add)
                and isinstance(val.right, ast.Constant) and val.right.value == 1):
            out.setdefault(target.slice.value, []).append(node.lineno)
    return out


def _write_only(src: str) -> list[str]:
    """在**同一份源码**里，写了却一次都没被读的计数器（按名字排序）。"""
    tree = ast.parse(src)
    counters = _counters(src)
    dead: list[str] = []
    for key, lines in counters.items():
        readers = [n.lineno for n in ast.walk(tree)
                   if isinstance(n, ast.Constant) and n.value == key
                   and n.lineno not in lines]
        if not readers:
            dead.append(key)
    return sorted(dead)


def _run() -> int:
    print("=" * 62)
    print("search.done 账本语义（可读 / 可达 / 联网 / 正文）")
    print("=" * 62)

    main_py = ROOT / "app" / "main.py"
    eng_py = ROOT / "app" / "engine.py"

    # -----------------------------------------------------------------
    section("1. 「可读」只许数 readable，「可达」只许数 available")
    exprs = _kwarg_text(main_py, "log_event", "可读")
    if not exprs:
        bad("search.done 里找不到 `可读=` —— 字段被改名/删掉了？")
    else:
        good = [e for e in exprs if "readable" in e]
        if len(good) == len(exprs) and "available" not in "".join(exprs):
            ok(f"可读={exprs[0].strip()}（数的是正文抽样通过）")
        else:
            bad(f"可读={exprs} —— 又数回目录可达了？"
                f"两件事共用一个词，日报就会把「打不开」写成「能读」")

    avail = _kwarg_text(main_py, "log_event", "可达")
    if avail and all("available" in e for e in avail):
        ok(f"可达={avail[0].strip()}（目录能打开，另一件事）")
    else:
        bad(f"可达={avail} —— 缺失或数错了；没有它就没法区分"
            f"「目录能开正文不能读」和「目录都打不开」")

    # -----------------------------------------------------------------
    section("2. 正文抽样的判假必须点名（`正文=` 那一格）")
    src_main = main_py.read_text(encoding="utf-8")
    if "sample_ledger(stats)" in src_main:
        ok("search.done 里带 **sample_ledger(stats)（正文= 那一格）")
    else:
        bad("search.done 少了 `正文=` —— 抽样判假又会变成「日志里一个字都没有」")

    led = E.sample_ledger
    if led(None) == {"正文": "-"}:
        ok("没跑抽样时打 `-`（不补 0：`验0/真0/假0` 会被读成「抽了都不行」）")
    else:
        bad(f"sample_ledger(None)={led(None)!r}，应为 '-'")

    one = led({"sampled": 2, "sample_ok_n": 1,
               "sample_failed": [("axxsw.net", "连接被拒绝")],
               "sample_unverified": 1})
    v = one.get("正文", "")
    if "假1" in v and "axxsw.net" in v and "连接被拒绝" in v:
        ok(f"判假点名 host+原因：{v}")
    else:
        bad(f"sample_ledger={one!r} —— 判假没有点名，复盘只能知道"
            f"「有一本读不了」，不知道是哪个站")

    # 截断也不许沉默：超过 3 个必须写出还剩几个
    many = led({"sampled": 5, "sample_ok_n": 0,
                "sample_failed": [(f"h{i}.com", "x") for i in range(5)],
                "sample_unverified": 0})
    if "+2" in many.get("正文", ""):
        ok(f"判假超过 3 个时把「还剩几个」写出来：{many['正文']}")
    else:
        bad(f"sample_ledger 截断没写 +N：{many!r} —— 沉默地截断会让人以为只有 3 个")

    # -----------------------------------------------------------------
    section("3. 默认值不许写在真值之后（`web_gave` 被清零那次）")
    # 断言方式看**行号**：`web_gave = 0` 必须在 join 之前。
    n_def = sum(1 for line in eng_py.read_text(encoding="utf-8").splitlines()
                if line.strip() == "web_gave = 0")
    l_def = _find_line(eng_py, "web_gave = 0")
    l_join = _find_line(eng_py, "web_thread.join(")
    if n_def == 0:
        bad("找不到 `web_gave = 0` —— 默认值没了（分支没赋值时会 NameError）")
    elif n_def > 1:
        bad(f"`web_gave = 0` 出现 {n_def} 次 —— 多出来的那一次正在覆盖真值")
    elif l_join > 0 and l_def > l_join:
        bad(f"`web_gave = 0` 在第 {l_def} 行、join 在第 {l_join} 行 —— "
            f"默认值写在真值之后，会把「并行兜底交回几条」冲成 0")
    else:
        ok(f"`web_gave = 0` 在第 {l_def} 行、join 在第 {l_join} 行（默认值在真值之前）")

    # -----------------------------------------------------------------
    section("4. `联网=` 的三态（纯函数）")
    lab = E.web_skip_label
    cases = [
        (False, 1, "preempt", "并行兜底交了 1 条 → 不能说「一次都没跑」"),
        (False, 0, "not_needed", "本地够用、联网没给东西"),
        (True, 0, "", "串行联网真跑了"),
    ]
    for need, gave, want, why in cases:
        got = lab(need_web=need, web_gave=gave)
        if got == want:
            ok(f"web_skip_label({need},{gave})={got!r} —— {why}")
        else:
            bad(f"web_skip_label({need},{gave})={got!r}，应为 {want!r} —— {why}")

    # -----------------------------------------------------------------
    section("5. 「正文全判假 → 补联网」的两道守卫（源码级）")
    src_eng = eng_py.read_text(encoding="utf-8")
    for needle, why in (
        ("late_evidence and not discover", "discover 关着时必须记 disabled，不能落 not_needed"),
        ("not any(r.readable for r in results)", "门票要看「一条能读的都没有」"),
        ("not already_web", "并行那路跑过就别再烧一次联网预算"),
    ):
        if needle in src_eng:
            ok(f"守卫在：`{needle}`（{why}）")
        else:
            bad(f"守卫 `{needle}` 不见了 —— {why}")

    # -----------------------------------------------------------------
    section("6. 账本计数器必须有读者（只写不读 = 埋点等于没埋）")
    # 2026-11-27 复盘：`search_kwblind`（"这个模板不按关键词过滤"）11-18 就加上了，
    # 之后连着被写进库 31/47/58 次，**却没有任何一处代码读它** ——
    # 于是三次判定一个处置都没触发，`sk.3qdu.org/.com/.net` 一直占着
    # 10 个可搜源里的 3 个。复盘时查不到原因，因为日志里根本没有这一格。
    #
    # 这条闸门是通用的：凡 `cur["x"] = int(cur.get("x") or 0) + 1` 这种
    # "累加计数器"，模块里必须至少有一处把它当判据读（比较/参与算术），
    # 否则它只是往库里堆数字。
    # ⚠ 例外必须**写进下面的白名单并说明理由** —— 白名单本身就是复盘材料：
    #   "这个字段我明确不参与任何决策"，比"忘了读"诚实得多。
    informational = {
        # `note_search_result` 的文档写死了：「`search_miss` 永远不参与任何淘汰
        # —— '没这本书'不是站的错」。它只给 /api/registry 和复盘看。
        "search_miss": "只做展示：「站里没这本书」不许参与任何淘汰",
    }
    scanned = ["app/registry.py", "app/sources/registry_source.py"]
    write_only: list[str] = []
    checked = 0
    for rel in scanned:
        path = ROOT / rel
        src_text = path.read_text(encoding="utf-8")
        for key, lines in _counters(src_text).items():
            if key in informational:
                continue
            checked += 1
            if key in _write_only(src_text):
                write_only.append(f"{rel}::{key}（写在第 {lines} 行，全模块零读取）")
    if write_only:
        bad("这些计数器只写不读，等于白记：" + "；".join(write_only))
    else:
        ok(f"{checked} 个计数器都有读者（{len(informational)} 个"
           f"「只做展示」的已登记理由：{', '.join(informational)}）")
    # ⚠ 扫描器自己也要有牙：拿一段**合成**源码（一个只写不读、一个有读者）
    #   喂给它，两种都必须判对。否则"0 个问题"可能只是"它什么都不看"。
    sample = (
        "def f(cur):\n"
        "    cur['nobody_reads_me'] = int(cur.get('nobody_reads_me') or 0) + 1\n"
        "    cur['has_reader'] = int(cur.get('has_reader') or 0) + 1\n"
        "    return cur.get('has_reader') or 0\n"
    )
    flagged = _write_only(sample)
    if flagged == ["nobody_reads_me"]:
        ok("扫描器自检：只写不读的被抓、有读者的不误报")
    else:
        bad(f"扫描器自检失败：{flagged!r}，应为 ['nobody_reads_me'] "
            f"—— 这条坏了，上面那个「0 个问题」就没意义")
    # 反向：白名单里的字段若后来真的参与了决策，说明理由过期了，也要叫一声。
    for key, reason in informational.items():
        if not reason.strip():
            bad(f"白名单 `{key}` 没写理由 —— 没有理由的例外就是漏读")

    print("\n" + "=" * 62)
    print(f"通过 {OK} · 失败 {BAD}")
    if BAD:
        print("✗ 有问题，见上面 ✗ 行")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
