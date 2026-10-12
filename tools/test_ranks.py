"""榜单解析回归测试（纯离线，用固化下来的真实 HTML 样本）。

为什么离线
----------
榜单解析依赖**外部站点的 HTML 结构**，那东西随时会变。把它做成
「每次跑都去联网抓」会有两个问题：跑得慢、而且站点一改结构就红一片，
分不清是"我写错了"还是"人家改版了"。

所以这里用 `tools/fixtures/` 里的真实样本 —— 都是从站点上原样截下来的，
解析器跑它们应该稳定输出。真站点改版时，重新截一份样本、看测试怎么红，
就知道要改哪。

覆盖的坑
--------
· GBK 编码（384g 是 gbk，其他站多是 utf-8）—— 样本已按 gb18030 解好
· **空表**（384g 的月/周榜确实是空表，不能当成解析失败）
· 字段缺失（luoxiaks 没有字数和状态）
· 表头行不能被当成数据
· 作者列不能抓到「最新章节」那格
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIX = Path(__file__).resolve().parent / "fixtures"


def read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def main() -> int:
    from app import ranks

    fails: list[str] = []

    def check(label, cond):
        if cond:
            print(f"  ✓ {label}")
        else:
            fails.append(label)
            print(f"  ✗ {label}")

    # -----------------------------------------------------------------
    print("== A. 384g 榜单解析（真实样本）==")
    html = read("384g_allvisit.html")
    items = ranks.parse_384g(html, "allvisit")
    check(f"解析出条目（{len(items)} 条）", len(items) >= 10)
    check("不超过上限", len(items) <= ranks.MAX_ITEMS)

    first = items[0] if items else {}
    print(f"     第一条：{first.get('title')} / {first.get('author')} / "
          f"{first.get('words')} / {first.get('updated')} / {first.get('status')}")

    check("第一条有书名", bool(first.get("title")))
    check("第一条有完整 URL", (first.get("url") or "").startswith("https://www.384g.com/html/"))
    check("第一条有作者", bool(first.get("author")))
    check("第一条有字数（以「字」结尾）", bool(first.get("words")) and first["words"].endswith("字"))
    check("第一条有更新时间（日期形状）",
          bool(first.get("updated")) and len(first["updated"]) == 10 and first["updated"].count("-") == 2)
    check("第一条有状态", first.get("status") in ("连载中", "已完结"))

    # 表头不能被收进来
    titles = [i["title"] for i in items]
    check("没有把表头「小说书名」当成书", "小说书名" not in titles)
    check("没有把「最新章节」当作者",
          all(i["author"] != "最新章节" for i in items))

    # ⚠ 回归：曾经把短章节名「新书来了~」当成了作者。
    # 那本书（插翅难飞）的第二章格是「新书来了~」——短、且不带「第..章」形状，
    # 启发式拦不住。现在改成按列位置认，作者应该是「风动铃心」。
    inv = [i for i in items if i["title"] == "插翅难飞"]
    check("「插翅难飞」的作者是风动铃心（不是章节名「新书来了~」）",
          bool(inv) and inv[0]["author"] == "风动铃心")
    check("没有把章节名当作者（扫全表）",
          all(not i["author"].endswith("~") for i in items))
    check("作者里不含「章」「节」等章节字样",
          all(not re.search(r"第.{0,8}[章节]", i["author"]) for i in items))

    # 书名不能是章节名
    chap_like = [t for t in titles if t.startswith("第") and ("章" in t or "节" in t)]
    check(f"书名里没有混进章节名（{chap_like[:2]}）", not chap_like)

    # 每条都要有基本字段
    check("每条都有 title + url",
          all(i.get("title") and i.get("url") for i in items))

    # -----------------------------------------------------------------
    print()
    print("== B. 空表（384g 月/周榜的真实情况）==")
    empty_html = read("384g_empty.html")
    empty = ranks.parse_384g(empty_html, "monthvisit")
    check("空表解析出 0 条（而不是报错）", empty == [])

    # -----------------------------------------------------------------
    print()
    print("== C. luoxiaks 榜单解析（真实样本）==")
    lx = read("luoxiaks_top.html")
    lx_items = ranks.parse_luoxiaks(lx)
    check(f"解析出条目（{len(lx_items)} 条）", len(lx_items) >= 5)
    f2 = lx_items[0] if lx_items else {}
    print(f"     第一条：{f2.get('title')} / {f2.get('author')}")
    check("第一条有书名", bool(f2.get("title")))
    check("第一条有作者", bool(f2.get("author")))
    check("第一条 URL 指向 /book_", "/book_" in (f2.get("url") or ""))
    check("书名不含 HTML 标签", all("<" not in i["title"] for i in lx_items))
    # 实测确认过：斗罗大陆II绝世唐门 的作者是 唐家三少
    duo = [i for i in lx_items if "斗罗大陆" in i["title"]]
    check("「斗罗大陆」的作者是唐家三少（验证 pop-intro 确实是作者）",
          bool(duo) and duo[0]["author"] == "唐家三少")

    # -----------------------------------------------------------------
    print()
    print("== D. 脏数据 / 边界 ==")
    check("空字符串 → 0 条", ranks.parse_384g("", "x") == [])
    check("没有 target 表 → 0 条", ranks.parse_384g("<html><body>hi</body></html>", "x") == [])
    check("表里只有表头 → 0 条",
          ranks.parse_384g('<table id="rankinglist"><tr><th>书名</th></tr></table>', "x") == [])
    check("luoxiaks 空串 → 0 条", ranks.parse_luoxiaks("") == [])
    check("行里没有书籍链接 → 跳过",
          ranks.parse_384g('<table id="rankinglist"><tr><td>广告</td></tr></table>', "x") == [])

    # -----------------------------------------------------------------
    print()
    print("== E. 榜单目录 ==")
    ks = ranks.kinds()
    check(f"目录非空（{len(ks)} 类）", len(ks) >= 4)
    check("每类有 kind/label/desc", all({"kind", "label", "desc"} <= set(k) for k in ks))
    check("kind 唯一", len({k["kind"] for k in ks}) == len(ks))
    # 实测为空表的不能出现在目录里
    check("不含实测空表的 monthvisit", "monthvisit" not in {k["kind"] for k in ks})
    check("不含实测空表的 weekvisit", "weekvisit" not in {k["kind"] for k in ks})

    # -----------------------------------------------------------------
    print()
    print("== F. 未知 kind / 缓存语义（不联网）==")
    check("未知 kind → 空列表", ranks.get_rank("nonexistent_xyz") == [])
    ranks.clear_cache()
    check("清缓存后仍能查目录", len(ranks.kinds()) >= 4)

    # -----------------------------------------------------------------
    print()
    print("== G. size 榜：源站把作者粘进书名的脏数据（原样透出）==")
    # 背景：size 榜头几行，站方自己的标题链接文字里就带着作者名
    # （`乡下千金她又掉马甲了茶鸢`，而作者格写的是「孙宝珠」）。
    # 这不是解析 bug —— title 取的就是那个 <a> 的文字，是**源站书名本身写歪了**。
    # 下面几条把「原样透出」这个决定钉住：将来谁想加清洗，会先在这里变红。
    size_items = ranks.parse_384g(read("384g_size.html"), "size")
    check(f"size 样本能解出条目（{len(size_items)} 条）", len(size_items) >= 10)

    zig = [i for i in size_items if "乡下千金" in i["title"]]
    check("脏书名那条还在（没有被偷偷过滤掉）", len(zig) >= 1)
    if zig:
        check("作者格取的是旁边的真作者「孙宝珠」，不是书名里粘的那个",
              zig[0]["author"] == "孙宝珠")
        check("书名原样保留（故意不剪「茶鸢」）",
              zig[0]["title"] == "乡下千金她又掉马甲了茶鸢")
        check("字数格解析正常", zig[0]["words"].endswith("字"))
        check("状态格解析正常", zig[0]["status"] in ("连载中", "已完结"))

    # 干净的行不能被上面的规则影响
    clean = [i for i in size_items if i["title"] == "永生诀"]
    check("干净书名「永生诀」没被误伤", bool(clean))
    if clean:
        check("「永生诀」作者 = 姜蘑菇", clean[0]["author"] == "姜蘑菇")

    print()
    if fails:
        print(f"✗ {len(fails)} 项失败：")
        for f in fails:
            print(f"    {f}")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
