"""反爬混淆还原 + 正文收口的回归测试。

背景（这是用户截图里那个「乱码」的真身）：
    联网发现抓到的某本书，整章正文里到处是 `回『荡』`、`杂『乱』`、
    `纯白『色』空间`。用户以为是编码坏了，其实是**站方的反爬混淆** ——
    把词里的某个字用『』包起来，让按词搜索的爬虫匹配不到。
    人看着就是「多了个括号」，稍一多整页就像乱码。

这个测试锁三件事：
  A. 该还原的必须还原（去括号留字，不丢字）
  B. 不该动的绝不能动（正常当引号用的『』、「」要原样留着）
  C. 收口链路上真的生效了（tidy_content 里调用顺序对）
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.sources.base import deobfuscate, tidy_content  # noqa: E402

_fails: list[str] = []
_pass = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global _pass
    if ok:
        _pass += 1
        print(f"  ✓ {name}")
    else:
        _fails.append(name)
        print(f"  ✗ {name}" + (f"（{detail}）" if detail else ""))
    return ok


def eq(name: str, got: str, want: str) -> bool:
    return check(name, got == want, f"得到 {got!r}，期望 {want!r}")


print("== A. 该还原的必须还原（真实站点抓下来的原样样本）==")
# 下面这些字符串是从 tengc.com 那本书的正文里**原样复制**的
eq("回『荡』 → 回荡", deobfuscate("刺耳的声浪在窄小的空间内翻滚回『荡』。"),
   "刺耳的声浪在窄小的空间内翻滚回荡。")
eq("杂『乱』 → 杂乱", deobfuscate("视界边缘杂『乱』的光斑却渐渐散去。"),
   "视界边缘杂乱的光斑却渐渐散去。")
eq("纯白『色』空间 → 纯白色空间",
   deobfuscate("外面是一片望不到边际的纯白『色』空间，飘浮着成百上千个一模一样的小房间。"),
   "外面是一片望不到边际的纯白色空间，飘浮着成百上千个一模一样的小房间。")
eq("不丢字（长度守恒）", str(len(deobfuscate("回『荡』"))), str(len("回荡")))
check("还原后不含任何『』", "『" not in deobfuscate("回『荡』杂『乱』纯白『色』"))

print("\n== B. 不该动的绝不能动（真的引号）==")
# 『』在中文里是合法引号，一刀切会破坏正常文本
eq("长句引号不动（>4 字）",
   deobfuscate("他喃喃道『我大概知道发生什么了』。"),
   "他喃喃道『我大概知道发生什么了』。")
eq("带标点的引号不动",
   deobfuscate("屏幕上一行字『正在直播，请注意』。"),
   "屏幕上一行字『正在直播，请注意』。")
eq("不含『』的正常文本原样返回",
   deobfuscate("这是一段普通的正文，没有任何括号。"),
   "这是一段普通的正文，没有任何括号。")
eq("空串安全", deobfuscate(""), "")
eq("None 安全", str(deobfuscate(None)), str(None))
# 「他说『好』」这种短引号 —— 拆开是「他说好」，语义不伤，属于可接受
r = deobfuscate("他说『好』然后走了。")
check("短引号拆开后**不丢字**", r.replace("『", "").replace("』", "") == r or "好" in r,
      f"得到 {r!r}")

print("\n== C. 收口链路里真的生效了 ==")
# tidy_content 必须先还原再判模板行 —— 顺序错了这条会挂
inp = "回『荡』的声音\n章节错误,点此举报\n杂『乱』的光"
out = tidy_content(inp, "")
check("正文里的混淆被还原", "回荡" in out and "杂乱" in out, f"得到 {out!r}")
check("模板行仍被清掉", "点此举报" not in out, f"得到 {out!r}")

print("\n== D. 首行标题去重与混淆共存 ==")
out2 = tidy_content("第1章 回『荡』\n第1章 回『荡』\n正文开始", "第1章 回荡")
check("标题去重仍生效", out2.count("第1章") <= 1, f"得到 {out2!r}")
check("正文首行不被误删", "正文开始" in out2, f"得到 {out2!r}")

print(f"\n=== {'全部通过' if not _fails else f'{len(_fails)} 项失败'}（{_pass} 通过 / {len(_fails)} 失败）===")
for f in _fails:
    print(f"  ✗ {f}")
raise SystemExit(0 if not _fails else 1)
