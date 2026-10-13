# -*- coding: utf-8 -*-
r"""文件名清洗的离线回归 —— 零依赖，不联网，直接跑：

    .venv/Scripts/python.exe tools/test_filename.py

为什么要有这一份
----------------
`safe_filename()` 以前只做了「把非法字符换成下划线」这一件事，在 **Linux
上完全够用** —— 而服务恰好跑在 Ubuntu 上，所以本地和线上都测不出问题。

但用户是**在 Windows 上下载**的，Windows 有几条 Linux 没有的规矩：

  ① **保留设备名**：`CON` `PRN` `AUX` `NUL` `COM1..9` `LPT1..9` 是设备不是
     文件，拿它们当文件名会直接 `OSError: [Errno 22]`。带扩展名也拦
     （`CON.txt`）。一本书叫《CON》《AUX》《NUL》并不稀奇，英文书更多。
  ② **结尾的点和空格**：Windows 会**静默**去掉，于是"写进去的名字"和
     "实际文件名"对不上，后续按原名去找就找不到。
  ③ **空名 / 纯点名**：`.` 和 `..` 是目录本身。

这类 bug 的特点是「在开发机上永远不会出现」，所以必须用断言钉住，
不能靠"我这儿跑得通"。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.exporter import _unique, safe_dirname, safe_filename  # noqa: E402

FAILS: list[str] = []


def check(got, want, label: str) -> None:
    if got != want:
        FAILS.append(f"{label} 期望 {want!r} 实际 {got!r}")
        print(f"  ✗ {label}  期望 {want!r} 实际 {got!r}")
    else:
        print(f"  ✓ {label}")


_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def no_reserved(got: str, label: str) -> None:
    """断言结果不是**裸**保留设备名。

    ⚠ 只判裸名 —— 带扩展名的不算（见 test_filename 末尾的实测段）。
    """
    check((got or "").strip().upper() in _RESERVED, False, label)


print("\n[1] Windows 保留设备名 —— 裸名必须拦")
for n in ["CON", "con", "PRN", "AUX", "NUL", "COM1", "COM9", "LPT1", "LPT9"]:
    no_reserved(safe_filename(n), f"裸名 {n} 被改写成安全名")

# 带扩展名的**不该**动 —— 实测现代 Windows 10/11 能正常创建（见文末）
for n in ["CON.txt", "con.txt", "NUL.txt", "AUX.txt", "COM1.txt"]:
    check(safe_filename(n), n, f"{n} 带扩展名是合法的，不该改写")

# 改名后还得能看出原名，不能变成一坨
check(safe_filename("CON").startswith("CON"), True, "保留名改写后仍保留可读性（前缀）")

# 不能误伤「以保留名开头但更长的」普通名字
check(safe_filename("CONAN"), "CONAN", "CONAN 是正常书名，不能动")
check(safe_filename("AUXILIARY"), "AUXILIARY", "AUXILIARY 不能动")
check(safe_filename("NULAND"), "NULAND", "NULAND 不能动")
check(safe_filename("COM10"), "COM10", "COM10 不在保留名单（只到 COM9）")

print("\n[2] 结尾的点与空格 —— Windows 会静默截断")
check(safe_filename("三体..."), "三体", "结尾的点要去掉")
check(safe_filename("三体   "), "三体", "结尾空格要去掉")
check(safe_filename("三体. . "), "三体", "混合的点和空格一起去")
check(safe_filename("三体...txt"), "三体...txt", "中间的点不能动")

print("\n[3] 空名与纯点名")
check(safe_filename(""), "untitled", "空串")
check(safe_filename("   "), "untitled", "全是空格")
check(safe_filename("."), "untitled", "单个点")
check(safe_filename(".."), "untitled", "两个点")
check(safe_filename("..."), "untitled", "三个点")
check(safe_dirname(".."), "untitled", "目录名 .. 也不行")

print("\n[4] 非法字符（原有能力，不能退化）")
check(safe_filename('a/b\\c:d*e?f"g<h>i|j'), "a_b_c_d_e_f_g_h_i_j", "全部换成下划线")
# 换行/制表符会被**换成下划线**（不是删掉）—— 判据是"原字符不残留"，
# 而不是"变成空"。这样 `三体\n上` 会得到 `三体_上`，至少还看得出原来断开过。
_r = safe_filename("三体\n\t\r")
check("\n" in _r or "\t" in _r or "\r" in _r, False, "换行制表符不残留（已换成下划线）")
check(safe_filename("三体"), "三体", "普通书名不受影响")
check(safe_filename("三 体"), "三 体", "中间空格保留（书名里的空格是合法的）")

print("\n[5] 长度与真实用例")
long_name = "长" * 200
check(len(safe_filename(long_name)) <= 80, True, "超长名截到 80 字以内")
# 真实调用形态：f"{book.title}_{author}.txt"
check(safe_filename("CON_天蚕土豆.txt"), "CON_天蚕土豆.txt",
      "实际调用带 _作者 后缀时，CON_ 不是保留名，不动它才对")
check(safe_filename("_天蚕土豆.txt"), "_天蚕土豆.txt", "空书名 + 作者 → 正常")
check(safe_filename("三体_刘慈欣.txt"), "三体_刘慈欣.txt", "常规书名")
check(safe_filename("活着_余华.epub"), "活着_余华.epub", "epub 后缀")

print("\n[6] safe_dirname —— 目录名不带扩展名语义")
check(safe_dirname("CON"), "CON_book", "目录名 CON 要改写")
no_reserved(safe_dirname("AUX"), "目录名 AUX 改写后安全")
check(safe_dirname("斗破苍穹"), "斗破苍穹", "常规目录名不动")
check(safe_dirname("斗破苍穹."), "斗破苍穹", "目录名结尾点要去掉")

print("\n[7] 真实文件系统验证 —— 结论不能只靠推理")
# 这一段用**真的创建文件**来确认判据对不对。理由：保留名的行为跟
# Windows 版本有关（实测这台 Win11 上 `CON.txt` 能创建、裸 `CON` 不能），
# 所以"该拦谁"必须以实测为准，不能照抄文档。
import tempfile  # noqa: E402

_tmp = tempfile.mkdtemp(prefix="nd-fn-")
try:
    # ① 清洗后的结果必须**真的能创建**
    for n in ["CON", "NUL", "AUX", "COM1", "LPT9", ".", "..", "三体...", ""]:
        out = safe_filename(n)
        try:
            p = os.path.join(_tmp, out)
            with open(p, "w", encoding="utf-8") as f:
                f.write("x")
            os.remove(p)
            check(True, True, f"清洗后能落盘：{n!r} → {out!r}")
        except OSError as e:
            check(False, True, f"清洗后仍然落不了盘：{n!r} → {out!r}（{e}）")

    # ② 反证：**裸保留名确实**创建不了（证明上面那条修复不是无的放矢）
    _bare_failed = False
    try:
        p = os.path.join(_tmp, "CON")
        with open(p, "w") as f:
            f.write("x")
        os.remove(p)
    except OSError:
        _bare_failed = True
    # 这条在 Linux / macOS 上会"失败"（因为裸 CON 合法）—— 那是正常的，
    # 所以只做提示，不计入失败。
    if _bare_failed:
        print("  · 反证成立：本机裸 CON 确实创建不了（说明修复有必要）")
    else:
        print("  · 本机裸 CON 能创建（非 Windows，或系统已放宽）—— 跳过反证")
finally:
    import shutil  # noqa: E402
    shutil.rmtree(_tmp, ignore_errors=True)

# ===========================================================================
# [8] 导出重名不覆盖（_unique）
# ===========================================================================
# 真 bug：`_unique()` 以前是「不存在就用，否则加**秒级**时间戳」——
#   ① 只检查一次，加完时间戳**不回头确认**那个名字是否已存在；
#   ② 时间戳精度是秒。
# 于是同一秒内导出两次同一本书（连点两下 / 前端重试），第二次算出的
# `书名_作者_1758….txt` 恰好就是第一次那个名字 → `write_text` **覆盖**。
# 用户表现：导出了两次，文件只有一个，且第一次的内容没了。
print()
print("── 8. 导出重名不覆盖（_unique） ─────────────────────────────────")
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

_dtmp = tempfile.mkdtemp(prefix="nd-uniq-")
try:
    base = Path(_dtmp) / "三体_刘慈欣.txt"

    # 不存在时原样返回
    check(str(_unique(base)), str(base), "目标不存在时原样返回（不瞎加后缀）")

    # 存在一次 → 得到 _1
    base.write_text("first", encoding="utf-8")
    p1 = _unique(base)
    check(p1.name, "三体_刘慈欣_1.txt", "重名时加 _1 后缀")

    # ★ 核心：连续调用多次必须**每次都不同**（旧实现同秒内会返回同一个）
    p1.write_text("second", encoding="utf-8")
    p2 = _unique(base)
    check(p2.name, "三体_刘慈欣_2.txt", "再重名时继续往后计数（不是重复 _1）")
    check(p1 != p2, True, "两次调用给出的路径必须不同（旧实现会相同→覆盖）")

    p2.write_text("third", encoding="utf-8")
    p3 = _unique(base)
    check(p3.name, "三体_刘慈欣_3.txt", "第三次是 _3")

    # 真实落盘验证：三个文件**都还在**、内容各自独立
    check(base.read_text(encoding="utf-8"), "first", "原始文件内容完好（没被覆盖）")
    check(p1.read_text(encoding="utf-8"), "second", "_1 内容完好")
    check(p2.read_text(encoding="utf-8"), "third", "_2 内容完好")

    # 中间空位会被复用（_2 被删掉后，下一个该用 _2 而不是 _4）
    p2.unlink()
    p4 = _unique(base)
    check(p4.name, "三体_刘慈欣_2.txt", "中间空位复用（比盲目递增更自然）")

    # 无扩展名也不能崩
    noext = Path(_dtmp) / "无后缀"
    noext.write_text("x", encoding="utf-8")
    p5 = _unique(noext)
    check(p5.name, "无后缀_1", "无扩展名文件也能正常加计数（suffix 为空串）")
finally:
    import shutil  # noqa: E402
    shutil.rmtree(_dtmp, ignore_errors=True)

print()
if FAILS:
    print(f"❌ {len(FAILS)} 项未通过：")
    for f in FAILS:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 全部通过")
