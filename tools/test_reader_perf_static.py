#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
阅读器热路径 · 静态自检（不用浏览器）
============================================================================
为什么需要它：`tools/test_reader_ui.py` 的 `test_perf` 已经能用真机把
"翻一页推了几份快照"数出来，但那需要 Chrome + 本地服务。而**最典型的那种
回归**（有人顺手把 `tocHTML` 塞回 `syncReader()` 的快照、或者把
`setReaderFields` 拆成多次 `setReaderField`）在**纯静态层面**就能抓 ——
读一眼源码就够，不必起浏览器。两条一起上：

  · 静态（本文件）：快、必然能跑、在 ship 的第一阶段就拦下。
  · 真机（test_reader_ui.test_perf）：慢，但验的是**真实运行结果**。
两层都有才叫"钉住"。只有真机的话，没装 Chrome 的环境就完全没保护；
只有静态的话，绕过写法（比如换个函数名推快照）就抓不住。

本文件钉四条
------------
  1. `syncReader()` 的快照里**不许有 tocHTML**
     —— 它是整本书目录（大书几 MB），而 syncReader 走每次翻页的高频路径。
        线上"阅读器有点卡"的根因就是它。谁加回来谁就得改这条。
  2. `updateBar()` 里**不许**出现多次 `setReaderField(`
     —— 必须走 `setReaderFields({...})` 一次推完。三次推 = 三份全量快照。
  3. 高频调用点（closeReader / rdTogglePanel / rdClosePanels）也要批量推。
  4. `setTocHTML` 必须有**去重**判据（`_rdTocHTMLSent`）
     —— 换章时 markToc 会重拼整份目录 HTML，内容没变就不该重推。

用法：
    .venv\\Scripts\\python tools\\test_reader_perf_static.py
============================================================================
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READER_JS = ROOT / "app" / "static" / "js" / "reader.js"

OK = 0
BAD = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global OK, BAD
    if cond:
        OK += 1
        print(f"  ✓ {name}")
    else:
        BAD += 1
        print(f"  ✗ {name}  {extra}")


def slice_function(src: str, header: str) -> str:
    """取出以 header 开头、到下一个顶层 `}` 为止的函数体。

    够用的原因：reader.js 里的函数都是顶层 `function xxx(...)` 且靠列 0 的
    `}` 收尾（项目风格一致）。取不到就返回空串，由断言报红 ——
    这样"函数被改名/删掉"也会被发现，而不是静默跳过。
    """
    i = src.find(header)
    if i < 0:
        return ""
    j = src.find("\n}", i)
    return src[i:(j + 2) if j > 0 else len(src)]


def main() -> int:
    src = READER_JS.read_text(encoding="utf-8")
    print("\n—— 阅读器热路径（静态）——")

    # ── 1. syncReader 的快照里不许有 tocHTML ──────────────────────────
    body = slice_function(src, "function syncReader()")
    check("找得到 syncReader()", bool(body),
          "没找到函数体 —— 改名了？本测试需要同步更新")
    if body:
        # 只看"传给 _rdApply 的那个对象字面量"里有没有 tocHTML 这个 key。
        # 用正则找 `tocHTML:` 作为对象键的写法（注释里提到 tocHTML 不算）。
        has_toc_key = re.search(r"^\s*tocHTML\s*:", body, re.M) is not None
        check("syncReader 的快照里没有 tocHTML（它是每次翻页的高频路径）",
              not has_toc_key,
              "快照里又出现了 tocHTML —— 翻页会重推整本书目录，卡顿回归")

    # ── 2. updateBar 不许多次 setReaderField ──────────────────────────
    bar = slice_function(src, "function updateBar()")
    check("找得到 updateBar()", bool(bar))
    if bar:
        # 数 `setReaderField(` —— 注意 `setReaderFields(` 也算前缀命中，
        # 所以要用负向断言排除 `s`。
        calls = re.findall(r"setReaderField(?!s)\s*\(", bar)
        check("updateBar 里没有 setReaderField(（单个字段的写法）",
              len(calls) == 0,
              f"出现 {len(calls)} 次 —— 应改成一次 setReaderFields({{...}})")
        batch = re.findall(r"setReaderFields\s*\(", bar)
        check("updateBar 走的是 setReaderFields( 批量推", len(batch) >= 1,
              f"setReaderFields 调用数={len(batch)}")

    # ── 3. 其它高频点也要批量推 ────────────────────────────────────────
    # closeReader / rdTogglePanel / rdClosePanels：一次事件里改多个面板开合，
    # 各推一次就是两次全量快照。它们**应当**用 setReaderFields。
    for fn in ("function rdTogglePanel(", "function rdClosePanels("):
        b = slice_function(src, fn)
        if not b:
            check(f"找得到 {fn}", False, "未找到")
            continue
        singles = re.findall(r"setReaderField(?!s)\s*\(", b)
        check(f"{fn} 用批量推（没有逐个 setReaderField）",
              len(singles) == 0, f"出现 {len(singles)} 次单个写法")

    # closeReader 里查一下（它可能很短、也可能内联在别的结构里）
    cr = slice_function(src, "export function closeReader()")
    if cr:
        singles = re.findall(r"setReaderField(?!s)\s*\(", cr)
        check("closeReader 用批量推（没有逐个 setReaderField）",
              len(singles) == 0, f"出现 {len(singles)} 次单个写法")

    # ── 4. setTocHTML 必须有去重 ──────────────────────────────────────
    toc = slice_function(src, "function setTocHTML(")
    check("找得到 setTocHTML()", bool(toc))
    if toc:
        check("setTocHTML 有去重判据（内容没变就不重推）",
              "_rdTocHTMLSent" in toc and "!==" in toc,
              "没看到 _rdTocHTMLSent 的比较 —— 换章会整段重推目录")
    # 去重哨兵必须在换书时被清掉，否则新书目录可能"被判重复"而不显示
    openr = slice_function(src, "export async function openReader(")
    check("换书时清掉了目录去重哨兵（否则新书目录可能不显示）",
          "_rdTocHTMLSent = null" in openr,
          "openReader 里没看到 _rdTocHTMLSent = null")

    # ── 5. 诊断探针必须挂着（真机测试依赖它）──────────────────────────
    check("rdSyncCount 已挂在 __lumeiLegacy 上（真机测试要用）",
          re.search(r"^\s*rdSyncCount,\s*$", src, re.M) is not None,
          "没在 __lumeiLegacy 的导出里看到 rdSyncCount")

    print("\n" + "=" * 62)
    if BAD == 0:
        print(f"通过 {OK} · 失败 0\n✓ 全部通过")
    else:
        print(f"通过 {OK} · 失败 {BAD}\n✗ 有 {BAD} 项没过")
    print("=" * 62)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
