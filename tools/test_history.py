# -*- coding: utf-8 -*-
"""搜索历史（app/history.py）的行为测试。

为什么值得单独测
----------------
这一层把「用户搜过什么」从**日志**（会轮转、会删）变成**持久数据**，
落盘文件一旦写坏，用户的下拉提示就空了、热词榜归零 ——
而且因为它**绝不能影响搜索本身**，出问题时会静默降级，
没人会发现，直到某天想看热词才发现库是空的。

盯四件事：
  1. **同一本书搜两次不新增条目**（只 count+1）—— 否则热词榜会全是重复
  2. **规整**：`"斗破  苍穹"` 与 `"斗破 苍穹"` 必须算同一个词
  3. **搜不到的词**要被标出来（hits=0）—— 这是书库缺口的证据
  4. **测试自己不许碰生产库**（照 test_registry.py 的做法，导入期改环境变量）

用法：python tools/test_history.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ⚠ 导入期就把库文件指到临时目录，全程不碰生产库。
#   history 支持 NOVEL_HISTORY 环境变量，就是为这个场景加的。
_TMPDIR = Path(tempfile.mkdtemp(prefix="novel-history-test-"))
os.environ["NOVEL_HISTORY"] = str(_TMPDIR / "history.json")

from app import history as H  # noqa: E402

PROD_DB = ROOT / "cache" / "history.json"
_prod_before: bytes | None = None

ok_n = 0
fail_n = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global ok_n, fail_n
    if cond:
        ok_n += 1
        print(f"  ✓ {name}")
    else:
        fail_n += 1
        print(f"  ✗ {name} {extra}")


def disk() -> dict:
    return json.loads(H._DB.read_text(encoding="utf-8"))


def main() -> int:
    global _prod_before
    print(f"\n临时库：{H._DB}")

    if PROD_DB.exists():
        _prod_before = PROD_DB.read_bytes()

    try:
        print("\n—— 1. 基础：记一次搜索 ——")
        H.add_search("斗破苍穹", hits=3)
        H.add_search("诡秘之主", hits=5)
        d = disk()
        kws = [it["kw"] for it in d["items"]]
        check("两条都记下了", kws == ["诡秘之主", "斗破苍穹"], str(kws))
        check("落盘结构有 version", d.get("version") == 1, str(d.get("version")))
        check("hits 记对了",
              d["items"][1]["hits"] == 3 and d["items"][0]["hits"] == 5)

        print("\n—— 2. 同一个词搜两次：不新增条目，只 count+1 ——")
        H.add_search("斗破苍穹", hits=4)
        d2 = disk()
        n = len([it for it in d2["items"] if it["kw"] == "斗破苍穹"])
        check("条目数没变（只有一条『斗破苍穹』）", n == 1, f"实际 {n} 条")
        hit = [it for it in d2["items"] if it["kw"] == "斗破苍穹"][0]
        check("count 涨到 2", hit["count"] == 2, str(hit["count"]))
        check("hits 被更新为最新一次", hit["hits"] == 4, str(hit["hits"]))
        check("重搜后排在**最前面**（最近搜过优先）",
              d2["items"][0]["kw"] == "斗破苍穹", str([i["kw"] for i in d2["items"]]))

        print("\n—— 3. 规整：空白折叠（只折叠，不删空格）——")
        # ⚠ 这里是个**易错点**，值得说清：`_clean_kw` 是"折叠"不是"去空格" ——
        #   `"斗破  苍穹"`（两空格）→ `"斗破 苍穹"`（一空格），它**不等于**
        #   `"斗破苍穹"`（无空格）。两者是**不同的词**，各自占一条。
        #   这是刻意的：书名里的空格有时是语义的一部分（网文标题常带空格），
        #   直接删掉会把 `"斗破 苍穹"` 和 `"斗破苍穹"` 混成一个，
        #   而它们可能真的是两本不同的书。
        #   所以要验证的是「同一个词的连续空白变体归一」，不是「空格全没了」。
        n0 = len(H.get_recent(200))
        H.add_search("斗破苍穹   ")
        H.add_search(" 斗破苍穹")
        H.add_search("斗破苍穹")
        check("首尾空白不影响：三处空白变体归成同一条",
              len(H.get_recent(200)) == n0, f"{n0} → {len(H.get_recent(200))}")
        kd = [it for it in H.get_recent(200) if it["kw"] == "斗破苍穹"][0]
        check("空白变体的 count 都累到同一词", kd["count"] >= 3, str(kd["count"]))

        # 内部连续空白折叠
        H.add_search("诡秘  之主")
        H.add_search("诡秘  之主")
        same = [it for it in H.get_recent(200) if it["kw"] == "诡秘 之主"]
        check("内部多空格折叠成一格，且同一词", len(same) == 1 and same[0]["count"] == 2,
              str([(it["kw"], it["count"]) for it in H.get_recent(6)]))
        check("折叠后的『诡秘 之主』不等于无空格的『诡秘之主』（刻意不混）",
              H.delete("诡秘 之主") and any(it["kw"] == "诡秘之主" for it in H.get_recent(200)))

        print("\n—— 4. 空词 / 超长词：不当数据收 ——")
        n0 = len(H.get_recent(200))
        H.add_search("   ")
        H.add_search("")
        check("空词/纯空白不收", len(H.get_recent(200)) == n0)
        H.add_search("长" * 500)
        longest = max(len(it["kw"]) for it in H.get_recent(200))
        check("超长词被截断", longest <= H._MAX_KW, f"最长 {longest}")

        print("\n—— 5. 最近 vs 热门：两个维度 ——")
        # ⚠ 断言要用**相对关系**，不能写死"谁第一" ——
        #   前面几节已经把 `斗破苍穹` 的 count 累到了 5，写死排名会随
        #   前面的用例改动而假红（第一版就是这么挂的）。这里只断言
        #   "热门榜按次数单调不增" + "两种排序确实不同"。
        for _ in range(6):
            H.add_search("热词甲")          # 累到 6 次，确保超过所有旧词
        H.add_search("冷门乙")
        hot = H.get_hot(5)
        recent = H.get_recent(5)
        counts = [int(it["count"]) for it in hot]
        check("热门榜按次数单调不增",
              all(counts[i] >= counts[i + 1] for i in range(len(counts) - 1)), str(counts))
        check("热门第一确实是次数最多的那个", hot[0]["kw"] == "热词甲",
              str([(it["kw"], it["count"]) for it in hot[:3]]))
        check("最近第一是最后搜的那个", recent[0]["kw"] == "冷门乙",
              str([it["kw"] for it in recent[:3]]))
        check("两种排序结果确实不同（不是同一个列表）",
              [it["kw"] for it in hot[:3]] != [it["kw"] for it in recent[:3]])

        print("\n—— 6. 搜不到的词：书库缺口的证据 ——")
        H.add_search("根本不存在的书", hits=0)
        st = H.stats()
        check("stats 报出空词", "根本不存在的书" in st["empty_words"], str(st["empty_words"]))
        check("empty 计数 ≥ 1", st["empty"] >= 1, str(st["empty"]))
        check("searches 是各词 count 之和",
              st["searches"] == sum(int(it["count"]) for it in H.get_recent(200)),
              f'{st["searches"]}')

        print("\n—— 7. 删除 / 清空 ——")
        ok = H.delete("冷门乙")
        check("删存在的词返回 True", ok is True)
        check("删完真没了", not any(it["kw"] == "冷门乙" for it in H.get_recent(200)))
        check("删不存在的词返回 False", H.delete("压根没有的词") is False)

        # ⚠ 含斜杠 / 问号 / 井号的词必须能正常存取删。
        #   这些字符在**路由层**有坑（路径段放不下斜杠，见 test_search_history.py
        #   的 8b 节），模块本身不关心 —— 但这条断言保证"模块侧没顺手把它们
        #   洗掉或过滤掉"，否则修了路由也还是存不进这种词。
        weird = ["哈利波特/魔法石", "斗破苍穹?序章", "C#入门"]
        for w in weird:
            H.add_search(w, hits=1)
        got = [it["kw"] for it in H.get_recent(10)]
        for w in weird:
            check(f"特殊字符词能存：{w!r}", w in got, str(got))
        check("特殊字符词能删",
              all(H.delete(w) for w in weird))

        n_before = len(H.get_recent(200))
        removed = H.clear()
        check("清空返回删掉的条数", removed == n_before, f"{removed} vs {n_before}")
        check("清空后库是空的", H.get_recent(200) == [])

        print("\n—— 8. 损坏文件：当空库继续跑，不能崩 ——")
        H._DB.write_text("{ 这不是 json", encoding="utf-8")
        H._loaded = False
        H._items.clear()
        try:
            got = H.get_recent(10)
            check("坏文件不抛异常", True)
            check("坏文件读成空库", got == [], str(got))
        except Exception as e:  # noqa: BLE001
            check("坏文件不抛异常", False, f"{type(e).__name__}: {e}")
        # 坏文件之后还能正常写
        H.add_search("恢复后的词")
        check("坏文件之后还能写", any(it["kw"] == "恢复后的词" for it in H.get_recent(10)))

        print("\n—— 9. 生产库没被碰过 ——")
        if _prod_before is not None:
            now = PROD_DB.read_bytes() if PROD_DB.exists() else None
            check("生产库内容一字未改", now == _prod_before)
        else:
            check("生产库本来就不存在（也没被创建）", not PROD_DB.exists())

    finally:
        import shutil

        shutil.rmtree(_TMPDIR, ignore_errors=True)

    print("\n" + "=" * 62)
    print(f"通过 {ok_n} · 失败 {fail_n}")
    print("=" * 62)
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
