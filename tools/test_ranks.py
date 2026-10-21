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
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIX = Path(__file__).resolve().parent / "fixtures"


def read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def main() -> int:
    from app import ranks

    # ⚠⚠ 先把缓存落盘路径挪到临时目录，再碰任何东西。
    #   下面 F/L 段会调 `ranks.clear_cache()`，而它会 `_DB.unlink()` ——
    #   不隔离的话这一跑就把**真实的 `cache/ranks.json` 删掉**：
    #   本地服务的榜单白刷一轮，线上跑一次测试同样会清掉缓存。
    #   不报错、不影响本次判定，所以一直没有被发现。
    #   （test_ranks_stale.py 早就这么做了，那边写着"真实缓存绝不能被碰"；
    #     这里漏了。）
    import tempfile
    ranks._DB = Path(tempfile.mkdtemp(prefix="ranks-test-")) / "ranks.json"

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
    # ⚠ 2026-10-22 晚：这条原来断言「monthvisit 不在目录里（真没人做月榜）」。
    #   实测推翻了它 —— hodei 的「月点击」块是**真数据**（与总点击/周点击/
    #   日点击/收藏数首条各不相同），落霞读书也有 `/rank/monthvisit/`。
    #   所以月榜现在是**有来源**的类别，进目录；而「总字数榜」反倒因为
    #   唯一来源的字数列自相矛盾而下线 —— 判据要跟着事实走，别跟着旧结论。
    check("月榜有来源 → 进目录",
          "monthvisit" in {k["kind"] for k in ks} and len(ranks.sources_for("monthvisit")) >= 2)
    # ⚠ weekvisit 的态度在 2026-10-15 变了，这条断言跟着改了 —— 值得写清楚：
    #   384g 的周榜**仍然是空表**，所以"有没有内容"这个判据不再是"这个 kind
    #   能不能进目录"，而是"**有没有一个来源真做这类榜**"。
    #   xbiquge.info 的 /top/week_0_1.html 是周榜且有内容 → 收进来。
    #   下面两条把"来源"这个真正的判据钉住（而不是简单地把断言删掉）：
    check("384g 不声明支持 weekvisit（它的周榜确实是空表）",
          "384g" not in {s["key"] for s in ranks._SOURCES
                         if "weekvisit" in s["kinds"]})
    check("weekvisit 有别的来源兜着（xbiquge 周榜 + 落霞 + hodei）",
          "weekvisit" in {k["kind"] for k in ks}
          and len(ranks.sources_for("weekvisit")) >= 2)

    # -----------------------------------------------------------------
    print()
    print("== F. 未知 kind / 缓存语义（不联网）==")
    check("未知 kind → 空列表", ranks.get_rank("nonexistent_xyz") == [])
    ranks.clear_cache()
    check("清缓存后仍能查目录", len(ranks.kinds()) >= 4)

    # -----------------------------------------------------------------
    print()
    print("== G. 「总字数榜」为什么下线（线上实测的字数列不可信）==")
    # 2026-10-22 线上 `/api/ranks?kind=size` 的前三条是同一本书的三个马甲，
    # 字数 910063888 / 682460826 / 456249205，而章节数只有 432 / 270 / 1404 章
    # —— 折合每章 100~325 万字，物理上不可能（正常 2~4 千字/章）。
    # 更硬的证据：站内同一本书两个条目、章节数一样、字数差 5 倍
    #   · 医婿（4551 章）67436106 字    · 医婿叶凡唐若雪（4551 章）13516110 字
    # 而 `/paihang/size_1.html` **就是按这个字段排序的** —— 顺序和数字都是假的。
    # 所以摘掉这个类别，换成有真数据的「本月热读」。下面钉住这个决定：
    size_items = ranks.parse_384g(read("384g_size.html"), "size")
    check(f"样本仍能解析（{len(size_items)} 条）—— 解析器没问题，坏的是数据",
          len(size_items) >= 10)
    # 「不可能的字数」直接量出来，别只在注释里说
    top_words = max(int("".join(c for c in i["words"] if c.isdigit()) or 0)
                    for i in size_items)
    check(f"榜首要命的字数量级（{top_words} 字 > 1 亿）—— 现实中最长的网文也只到"
          f" 3~4 千万字", top_words > 100_000_000)
    check("SUPPORTED 里不再有总字数榜",
          "size" not in {k["kind"] for k in ranks.kinds()})
    check("384g 也不再声明 size（它只有这一列能算，而这一列不可信）",
          "size" not in next(s["kinds"] for s in ranks._SOURCES if s["key"] == "384g"))
    ranks.clear_cache()
    check("点 size 标签返回空列表（不抛异常，界面走「暂无数据」）",
          ranks.get_rank("size") == [])

    # -----------------------------------------------------------------
    print()
    print("== H. xbqg5200 榜单解析（真实样本）==")
    xq = ranks.parse_xbqg5200(read("xbqg5200_top.html"), "allvisit")
    check(f"解析出条目（{len(xq)} 条）", len(xq) >= 10)
    f3 = xq[0] if xq else {}
    print(f"     第一条：{f3.get('title')} / {f3.get('author')} / 分类={f3.get('category')}")
    check("第一条有书名", bool(f3.get("title")))
    check("第一条有作者", bool(f3.get("author")))
    check("URL 指向站点域", (f3.get("url") or "").startswith("https://www.xbqg5200.com/"))
    # ⚠ 书名必须**不带** `[玄幻]` 这类分类前缀（前缀在 <a> 外面，取错位置就带上了）
    check("书名不带 [分类] 前缀",
          all(not i["title"].startswith("[") for i in xq))
    check("分类被单独记下来了",
          any(i.get("category") for i in xq))
    # ⚠ 分类不能塞进 status —— 前端会把 status 当"连载/完结"显示
    check("分类没有被塞进 status",
          all(i.get("status") == "" for i in xq))
    check("source/source_display 都写了",
          all(i.get("source") == "xbqg5200" and i.get("source_display") for i in xq))
    # ⚠ `li` 的 class 里有个站点生成的哈希后缀（`item-34e68100`）。
    #   写全等匹配 `class="list-group-item item-34e68100"` 的话，**这个真实样本
    #   照样能过** —— 站点换一次哈希整页就解析不出东西。所以这条判据必须拿
    #   **改过哈希的** HTML 来验：真实样本验不出这个坑。
    tweaked = read("xbqg5200_top.html").replace("item-34e68100", "item-9f00ab12")
    check("class 哈希后缀变了也能认出来（包含匹配，不是全等）",
          len(ranks.parse_xbqg5200(tweaked, "allvisit")) == len(xq))
    check("哈希换掉后书名/作者还是对的",
          [i["title"] for i in ranks.parse_xbqg5200(tweaked, "allvisit")] ==
          [i["title"] for i in xq])

    # -----------------------------------------------------------------
    print()
    print("== I. xbiquge.info 榜单解析（真实样本：总榜 / 周榜）==")
    bi = ranks.parse_xbiquge(read("xbiquge_top.html"), "allvisit")
    check(f"总榜解析出条目（{len(bi)} 条）", len(bi) >= 10)
    f4 = bi[0] if bi else {}
    print(f"     第一条：{f4.get('title')} / {f4.get('author')} / "
          f"{f4.get('status')} / {f4.get('updated')}")
    check("第一条有书名", bool(f4.get("title")))
    check("第一条有作者", bool(f4.get("author")))
    check("第一条有状态", bool(f4.get("status")))
    check("第一条有更新时间", bool(f4.get("updated")))
    check("URL 指向站点域", (f4.get("url") or "").startswith("https://www.xbiquge.info/"))
    # ⚠ 这个站的书名带 [分类] 前缀（和 xbqg5200 不同：前缀写在 <a> 里面）
    check("书名剥掉了 [分类] 前缀",
          all(not i["title"].startswith("[") for i in bi))
    check("分类被单独记下来了", any(i.get("category") for i in bi))
    # ⚠ 一本书占 5 个 <dd>；"按 <dd> 逐条取"会把作者行当成一本书。
    #   下面几条钉住"按书名块切"：作者不会是"作者："这种残缺串，书名不会带
    #   "状态：""更新时间："这类标签残留。
    check("作者里没有「作者：」这种标签残留",
          all("：" not in i["author"] and ":" not in i["author"] for i in bi))
    # ⚠ 判据要**只认字段标签**：书名里本来就可能带全角冒号
    #   （实测「悠哉兽世：种种田，生生崽」），写 `"：" not in title` 会误红。
    check("书名里没有串进下一行的字段标签",
          all(not re.search(r"(状态|更新时间|作者|最新章节)\s*[：:]", i["title"])
              for i in bi))
    check("条数 = 页面上的书名块数（30 个 <dd><h3>）",
          len(re.findall(r"<dd\s*>\s*<h3\s*>", read("xbiquge_top.html"))) == 30)

    wk = ranks.parse_xbiquge(read("xbiquge_week.html"), "weekvisit")
    check(f"周榜解析出条目（{len(wk)} 条）", len(wk) >= 10)
    check("周榜首条是「过万重山」（实测）",
          bool(wk) and wk[0]["title"] == "过万重山")
    check("周榜 kind 传下去了", all(i["kind"] == "weekvisit" for i in wk))

    # ⚠ 这个站**不是每个榜单页的书名都带 `[分类]` 前缀**：总榜/周榜带，
    #   分类榜（/top/all_1_1.html）不带。用同一份解析器就要两边都对 ——
    #   如果实现改成"必须匹配到 `[...]` 才算书名"，分类榜就会整页解析成空。
    cat = ranks.parse_xbiquge(read("xbiquge_all_1.html"), "allvisit")
    check(f"分类榜（书名不带前缀）也能解析（{len(cat)} 条）", len(cat) >= 10)
    check("分类榜首条是「伏天氏」（实测，原文无 [分类] 前缀）",
          bool(cat) and cat[0]["title"] == "伏天氏")
    check("不带前缀时 category 是空串，而不是把整段当分类",
          cat[0]["category"] == "" and cat[0]["title"] == "伏天氏")
    check("分类榜的书名没有残留方括号",
          all(not i["title"].startswith("[") and "]" not in i["title"] for i in cat))

    # -----------------------------------------------------------------
    print()
    print("== J. 来源表契约 ==")
    srcs = ranks._SOURCES
    check(f"来源表非空（{len(srcs)} 项）", len(srcs) >= 4)
    check("每项都有 key/display/url/parser/kinds",
          all({"key", "display", "url", "parser", "kinds"} <= set(s) for s in srcs))
    check("key 唯一", len({s["key"] for s in srcs}) == len(srcs))
    check("url 是 http(s)", all(s["url"].startswith("https://") for s in srcs))
    check("parser 可调用", all(callable(s["parser"]) for s in srcs))
    check("kinds 都是目录里有的 kind",
          all(s["kinds"] <= {k["kind"] for k in ks} for s in srcs))
    # ⚠ 反向：**每一类目录里的榜单都必须至少有一个来源**。
    #   漏了这个，就会出现"目录里有这个标签、点开永远是空的"——
    #   而 SUPPORTED 是我们手写的，来源表也是手写的，两边很容易脱节。
    nogot = [k["kind"] for k in ks if not ranks.sources_for(k["kind"])]
    check(f"每类榜单都至少有一个来源（没有来源的：{nogot}）", not nogot)
    check("总点击榜是综合多来源的（>=3 个站点）",
          len(ranks.sources_for("allvisit")) >= 3)
    check("总点击榜的展示名互不相同（否则用户看不出是多来源）",
          len(set(ranks.sources_for("allvisit"))) == len(ranks.sources_for("allvisit")))

    # -----------------------------------------------------------------
    print()
    print("== K. 交错合并 / 去重（纯函数 _interleave）==")
    A = [{"title": f"A{i}"} for i in range(1, 6)]
    B = [{"title": f"B{i}"} for i in range(1, 6)]
    C = [{"title": f"C{i}"} for i in range(1, 3)]      # 只有 2 条
    m = ranks._interleave([A, B, C], 100)
    order = [i["title"] for i in m]
    print(f"     交错结果：{order}")
    check("按来源轮流取（前 3 条来自 3 个不同来源）",
          order[:3] == ["A1", "B1", "C1"])
    check("短的来源取完后，长的继续（不会整段跳过）",
          order == ["A1", "B1", "C1", "A2", "B2", "C2", "A3", "B3", "A4", "B4", "A5", "B5"])
    check("总条数 = 各来源之和", len(m) == 12)
    # 去重：同一本书（带书名号/空格差异）只留一份，且留**先出现**的那个来源
    d = ranks._interleave(
        [[{"title": "斗破苍穹", "source": "x"}],
         [{"title": "《斗破苍穹》", "source": "y"}, {"title": "别的一本", "source": "y"}]],
        100,
    )
    check("跨来源同一本书去重（《》差异也算同一本）",
          [i["title"] for i in d] == ["斗破苍穹", "别的一本"])
    check("去重保留的是先出现的那个来源", d and d[0]["source"] == "x")
    check("空书名不会互相顶掉", len(ranks._interleave([[{"title": ""}, {"title": ""}]], 100)) == 0)
    check("限流生效", len(ranks._interleave([A, B], 3)) == 3)
    # ⚠ 反证：这个性质**不是恒真**的 —— 换成"按来源顺序拼接"（旧写法）
    #   前 3 条就全是同一个来源。所以上面那条断言是有牙的，不是摆设。
    naive = (A + B + C)[:3]
    check("反证：旧的「顺序拼接」写法过不了这条（前 3 条同源）",
          len({i["title"][0] for i in naive}) == 1)

    # -----------------------------------------------------------------
    print()
    print("== L. 端到端：多来源抓取 → 交错 → 去重 → 截断（假网络）==")
    # 为什么必须有这一段：K 段测的是纯函数，**用不用它**是另一回事。
    # 旧代码的 bug 正是"函数写得挺好但根本没被调用/调用完又被顺序拼接盖掉"。
    real_fetch = ranks.fetch_text

    # ⚠ 假网络必须**记账**，不能只靠"认不出就 raise"。
    #   因为 `_fetch_source` 会吞掉异常（这是它对生产代码的正确行为）——
    #   于是新增一个来源、假网络不认识它的地址时，测试**不会红**，
    #   只是那个来源静默地空掉，而"实际出现 >= 4 个站点"照样过。
    #   所以下面把 `unknown` 单独记下来，最后当成断言查一遍。
    asked: list[str] = []
    unknown: list[str] = []

    def lx_page(titles: list[str]) -> str:
        """造一份落霞读书 `/rank/<kind>/` 的样本（`<li class="hot-book2">` 结构）。"""
        lis = "".join(
            f'<li class="hot-book2"><a href="https://www.luoxiaks.net/book_{700 + i}/">'
            f'<h2 class="pop-tit">{t}</h2>'
            f'<span class="pop-intro">作者{i}</span></a></li>'
            for i, t in enumerate(titles, 1))
        return f'<html><body><ul class="hot-books">{lis}</ul></body></html>'

    def fake_fetch(url: str, **kw):
        asked.append(url)
        if "384g.com/paihang/allvisit" in url:
            return read("384g_allvisit.html")
        if "luoxiaks.net/rank/" in url:
            # ⚠ 必须**按类目返回不同内容**：落霞的 5 个类目是 5 个不同页面
            #   （/rank/allvisit/、/rank/allvote/…）。如果这里统一返回一份
            #   样本，"四个来源其实是同一份数据"这种错误就抓不出来 ——
            #   而 hodei 那边正是这么翻过车的（一页十榜，四个 tab 同名次）。
            kind = url.rstrip("/").rsplit("/", 1)[-1]
            return lx_page([f"{kind}专用书{i}" for i in range(1, 4)])
        if "xbqg5200.com" in url:
            return read("xbqg5200_top.html")
        if "xbiquge.info/top/week" in url:
            return read("xbiquge_week.html")
        # ⚠ 这两条必须排在下面的 `xbiquge.info` 泛匹配**前面**，
        #   否则列表页会被当成总榜样本喂进去（结构一样，测出来全绿，
        #   但"到底抓的是哪个 URL"这件事就没被验过了）。
        if "xbiquge.info/lastupdate" in url:
            return read("xbiquge_lastupdate.html")
        if "xbiquge.info/lastpost" in url:
            # 实测这两页是同一套模板（`<dd><h3>` 块 + 中文标签字段），
            # 结构上可以共用一份样本；内容差异与本测试无关。
            return read("xbiquge_lastupdate.html")
        if "xbiquge.info" in url:
            return read("xbiquge_top.html")
        if "hodei.net" in url:
            return read("hodei_rank.html")
        if "384g.com/paihang/" in url:
            # 384g 所有榜单共用同一张 `<table id="rankinglist">` 表格，
            # 只有排行内容不同 —— 结构验证用同一份样本是够的。
            return read("384g_allvisit.html")
        unknown.append(url)
        raise AssertionError(f"假网络不认识这个地址：{url}")

    def declared_urls(kind: str) -> list[str]:
        return [s["url"].format(kind=kind) for s in ranks._SOURCES if kind in s["kinds"]]

    ranks.fetch_text = fake_fetch
    try:
        ranks.clear_cache()
        got = ranks._fetch_one("allvisit")
        asked_allvisit = list(asked)
    finally:
        ranks.fetch_text = real_fetch

    miss = [u for u in declared_urls("allvisit") if u not in asked_allvisit]
    check(f"声明的每个来源都被真的请求过（缺：{miss}）", not miss)
    check(f"假网络认识每一个被请求的地址（不认识：{unknown}）", not unknown)

    shown = []
    for i in got:
        s = i.get("source_display") or i.get("source")
        if s not in shown:
            shown.append(s)
    print(f"     前 6 条：{[(i['title'][:6], i.get('source')) for i in got[:6]]}")
    print(f"     出现过的来源：{shown}")
    check(f"总条数不超过上限（{len(got)} <= {ranks.MAX_ITEMS}）", len(got) <= ranks.MAX_ITEMS)
    check(f"实际出现 >= 4 个不同站点（{len(shown)}）", len(shown) >= 4)
    # ⚠ 比"数出来 >= 4"更硬的一条：**实际出现的来源数 == 声明的来源数**。
    #   「声明 5 家、实际只出 1 家」正是 2026-10-22 线上实测抓到的真问题
    #   （`cache/ranks.json` 里 7 类有 6 类的 source 集合只有一个元素，
    #    而页脚照旧写着"综合 N 个站点"）。只数"有没有 4 家"这种阈值判据
    #   在加第 5 家的时候不会变红，等号会。
    check(f"实际出现的来源数 == 声明的来源数"
          f"（{len(shown)} / {len(ranks.sources_for('allvisit'))}）",
          len(shown) == len(ranks.sources_for("allvisit")))
    # ⚠ 这条是整段的核心：**交错**的意思就是"前 N 条里就能看全所有来源"。
    #   旧写法（主源全在前）会让前 20 条只有一个来源 —— 那正是用户说的
    #   "榜单都是一个网站来的，太单薄"。
    first4 = {i.get("source") for i in got[:4]}
    check(f"前 4 条已覆盖 >= 4 个来源（{first4}）", len(first4) >= 4)
    keys = [ranks._norm_title(i["title"]) for i in got]
    check("没有重复书名（跨来源去重生效）", len(keys) == len(set(keys)))
    check("每条都带 source_display", all(i.get("source_display") for i in got))

    # 少来源的榜单：不能因为"多来源"改造而抓不到东西
    ranks.fetch_text = fake_fetch
    try:
        ranks.clear_cache()
        wk2 = ranks._fetch_one("weekvisit")
        mv2 = ranks._fetch_one("monthvisit")
        av2 = ranks._fetch_one("allvote")
    finally:
        ranks.fetch_text = real_fetch
    check(f"weekvisit 抓得到（{len(wk2)} 条）", len(wk2) >= 10)
    # ⚠ 2026-10-22 晚：weekvisit 从两家变三家（落霞 /rank/weekvisit/ 也上了）。
    #   原断言 `== {"xbiquge"}` 是单来源时代的事实，现在跟着改，
    #   并继续钉"名次按声明顺序"（落霞在 _SOURCES 里更靠前 → 首条必须是它）。
    check(f"weekvisit 的三个来源都出结果了（{sorted({i.get('source') for i in wk2})}）",
          {i.get("source") for i in wk2} == {"luoxiaks", "xbiquge", "hodei"})
    check("weekvisit 首条来自声明更靠前的落霞",
          bool(wk2) and wk2[0].get("source") == "luoxiaks")
    check(f"monthvisit 抓得到（{len(mv2)} 条）", len(mv2) >= 6)
    check(f"monthvisit 两个来源都出结果（{sorted({i.get('source') for i in mv2})}）",
          {i.get("source") for i in mv2} == {"luoxiaks", "hodei"})
    check(f"allvote 两个来源都出结果（{sorted({i.get('source') for i in av2})}）",
          {i.get("source") for i in av2} == {"384g", "luoxiaks"})
    # ⚠ 「同一份数据当两家来源」的照妖镜：落霞 5 个类目是 5 个不同页面，
    #   假网络按 URL 末尾的类目名返回不同内容 —— 抓到 allvote 就必须是
    #   allvote 那页的书名。若谁把 URL 改回固定的 /top.html（5 类共用一个
    #   地址），这里立刻变成 allvisit 的内容，红。
    #   ⚠ 判据只看**落霞那几条**：allvote 的首条是 384g 的（声明更靠前，
    #     交错第一条给主源），拿 overall 首条去比会误判。
    lx_av = [i for i in av2 if i.get("source") == "luoxiaks"]
    check("allvote 抓的是 /rank/allvote/ 那一页，不是 /top.html "
          f"（落霞首条：{lx_av[0]['title'] if lx_av else '空'}）",
          bool(lx_av) and all(i["title"].startswith("allvote") for i in lx_av))
    check("没有来源的 kind → 空列表（不抛异常）",
          ranks._fetch_one("dayvisit") == [])

    # 一源失败不拖垮整体
    def broken_384g(url: str, **kw):
        if "384g.com" in url:
            raise RuntimeError("站点 503")
        return fake_fetch(url, **kw)

    ranks.fetch_text = broken_384g
    try:
        ranks.clear_cache()
        partial = ranks._fetch_one("allvisit")
    finally:
        ranks.fetch_text = real_fetch
    pshown = {i.get("source") for i in partial}
    check(f"384g 挂了，另外 3 个来源照常出结果（{pshown}）",
          len(pshown) >= 3 and "384g" not in pshown)
    check("降级后仍然没有重复书名",
          len([ranks._norm_title(i["title"]) for i in partial])
          == len({ranks._norm_title(i["title"]) for i in partial}))

    # -----------------------------------------------------------------
    # 名次只能由**声明的顺序**决定，不能由「谁先返回」决定。
    #   `_fetch_one` 用 `as_completed` 收结果（完成顺序不可预测），
    #   如果直接把结果按完成顺序拼桶，同一类榜单每刷新一次
    #   第一个来源就可能换人 —— 排行榜最忌讳名次随机跳，
    #   而且**不报错**，只表现为"每次打开顺序都不太一样"。
    # 做法：把**第一个声明的来源**故意拖慢，让它最后一个返回。
    first_host = ranks._SOURCES[0]["url"].split("//")[1].split("/")[0]
    first_key = ranks._SOURCES[0]["key"]

    def slow_first(url: str, **kw):
        if first_host in url:
            time.sleep(0.4)          # 拖到其他来源都返回之后
        return fake_fetch(url, **kw)

    ranks.fetch_text = slow_first
    try:
        ranks.clear_cache()
        ordered = ranks._fetch_one("allvisit")
    finally:
        ranks.fetch_text = real_fetch
    lead = ordered[0].get("source") if ordered else None
    check(f"名次按**声明顺序**、不按返回快慢"
          f"（声明第一的来源={first_key}/{first_host}，实际首条来自 {lead}）",
          lead == first_key)
    check("拖慢一个来源不影响总数", len(ordered) >= 20)

    # -----------------------------------------------------------------
    print()
    print("== M. 前端两侧的榜单色相表必须一致（Vue + 降级 JS）==")
    # 为什么值得一条测试：`app/static/js/ranks.js` 是 Vue 没挂上时的降级实现，
    # 两份 HUE 各写一份。加了新 kind 只改一处的话，同一类榜单在两条路径下
    # 颜色不同 —— 不报错，看起来就像"页面抽风"。
    import re as _re

    def hue_keys(path: str) -> dict[str, int]:
        src = (ROOT / path).read_text(encoding="utf-8")
        m = _re.search(r"HUE\s*=\s*\{([^}]*)\}", src, _re.S)
        if not m:
            return {}
        out: dict[str, int] = {}
        for km, vm in _re.findall(r"(\w+)\s*:\s*(\d+)", m.group(1)):
            out[km] = int(vm)
        return out

    hue_vue = hue_keys("frontend/src/components/RanksPanel.vue")
    hue_js = hue_keys("app/static/js/ranks.js")
    print(f"     Vue: {hue_vue}")
    print(f"     JS : {hue_js}")
    check(f"两处色相表都解析出来了（{len(hue_vue)} / {len(hue_js)} 项）",
          bool(hue_vue) and bool(hue_js))
    check("两处色相表逐项相同", hue_vue == hue_js)
    # 反向：目录里每一个 kind 都得有配色，否则新加的标签全挤在默认色上
    # （`HUE[k] ?? 22` 会让它看起来"跟总点击榜一个色"）。
    miss = sorted({k["kind"] for k in ks} - set(hue_vue))
    check(f"目录里的每个 kind 都有配色（缺：{miss}）", not miss)
    # 反向：配色表里不许留已经下线的 kind（`size` 下线后那份 200 就该删掉，
    # 否则后人照着色相表以为这一类还在）
    dead_hue = sorted(set(hue_vue) - {k["kind"] for k in ks})
    check(f"配色表里没有已下线类目的残留色（{dead_hue}）", not dead_hue)

    # -----------------------------------------------------------------
    print()
    print("== N. /api/ranks 接口契约（离线，假网络）==")
    # 为什么要到接口这一层：`sources` 是新加的字段，而它是**页脚那句
    # "综合 N 个站点"唯一的来源**。只测 ranks 模块测不到它 ——
    # 字段漏传/传空的话，界面上表现为"页脚退回老文案"，不报错。
    api_fetch = ranks.fetch_text
    ranks.fetch_text = fake_fetch
    try:
        ranks.clear_cache()
        from fastapi.testclient import TestClient

        from app import main as _main

        cli = TestClient(_main.app)
        r = cli.get("/api/ranks?kind=allvisit")
        check(f"GET /api/ranks 返回 200（{r.status_code}）", r.status_code == 200)
        d = r.json()
        check("ok=true", d.get("ok") is True)
        check(f"返回的不是空列表（{d.get('count')} 条）", (d.get("count") or 0) >= 10)
        check(f"sources 声明了 >=3 个站点（{d.get('sources')}）",
              isinstance(d.get("sources"), list) and len(d["sources"]) >= 3)
        check("items 里真的出现了多个站点",
              len({i.get("source_display") for i in d["items"] if i.get("source_display")}) >= 4)
        check("页脚会写「综合 N 个站点」，N 必须和实际出现的站点数对得上",
              len({i.get("source_display") for i in d["items"] if i.get("source_display")})
              == len(d.get("sources") or []))
        check("label/desc 都在（标签与说明靠它们）",
              bool(d.get("label")) and bool(d.get("desc")))
        check("age/fresh 字段还在（界面靠它说『x 分钟前更新』）",
              "age" in d and "fresh" in d)
        r2 = cli.get("/api/ranks?kind=nonexistent_xyz")
        check(f"未知 kind → 400（{r2.status_code}）", r2.status_code == 400)
        r3 = cli.get("/api/ranks/kinds")
        check("GET /api/ranks/kinds 200", r3.status_code == 200)
        check(f"kinds 7 类（{len(r3.json().get('kinds', []))}）",
              len(r3.json().get("kinds", [])) == len(ks))
        # 状态接口里要能看到"声明来源"与"实际抓到的来源"
        r4 = cli.get("/api/ranks/status")
        kst = (r4.json().get("cache", {}).get("kinds", {}) or {}).get("allvisit", {})
        check("status 里带了 sources（声明）",
              isinstance(kst.get("sources"), list) and len(kst["sources"]) >= 3)
        check("status 里带了 got（实际抓到的来源）",
              isinstance(kst.get("got"), list) and len(kst["got"]) >= 4)
        check("status 的 got 与 sources 数量一致（抽风会在这里露出来）",
              len(kst.get("got") or []) == len(kst.get("sources") or []))
    finally:
        ranks.fetch_text = api_fetch
        ranks.clear_cache()

    # -----------------------------------------------------------------
    print()
    print("== O. 前端接线（静态检查：页脚那句『综合 N 个站点』）==")
    # ⚠ 这一段是**静态检查**，不是行为验证 —— 它只能证明"那几行还在"。
    #   真正的行为验证在 tools/test_ranks_ui.py（真机跑，断言页脚文本）。
    #   留这一段是因为：`sources` 从接口到页脚要经过三处（ref / applyRank /
    #   模板），漏掉任何一处都只是"页脚少半句话"，谁都不会注意。
    vue = (ROOT / "frontend/src/components/RanksPanel.vue").read_text(encoding="utf-8")
    check("Vue 里有 sources 状态", "const sources = ref([])" in vue)
    check("applyRank 把接口的 sources 落进状态",
          "sources.value = Array.isArray(d.sources) ? d.sources : [];" in vue)
    check("模板用的是 footLine", "{{ footLine }}" in vue)
    check("footLine 读 sources.value", "const n = sources.value.length;" in vue)
    check("页脚仍然提到『公开榜单页』与『30 分钟』（界面测试的验收词）",
          "公开榜单页" in vue and "30 分钟" in vue)
    # 降级路径：老后端不带 sources 时，页脚不能变成空白
    check("没有 sources 时页脚有兜底文案", 'n === 1 ?' in vue and '"榜单来自公开榜单页"' in vue)

    # -----------------------------------------------------------------
    print()
    print("== P. 推荐 tab 接线（静态检查：独立页面 + 导航可达 + 折叠已下线）==")
    # ⚠ 2026-10-15 榜单从发现页区块升级成独立 tab。它的失败方式全是**静默**的：
    #   导航少一格（某个尺寸的设备永远进不去）、#view-ranks 不存在
    #   （切过去白页）、深链不认（分享出去的链接落到发现页）、点书名
    #   不切页（搜索在后台跑完了、眼前却什么都没有）。
    #   这里是接线底线；真机行为在 test_ranks_ui.py 与 test_buttons.py C 组。
    idx = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    shell_js = (ROOT / "app/static/js/shell.js").read_text(encoding="utf-8")
    main_js = (ROOT / "app/static/js/main.js").read_text(encoding="utf-8")
    disc_js = (ROOT / "app/static/js/discover.js").read_text(encoding="utf-8")
    rk_js = (ROOT / "app/static/js/ranks.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/css/app.css").read_text(encoding="utf-8")

    check("顶栏 + 底栏都有「推荐」入口（各一个 data-nav=ranks）",
          idx.count('data-nav="ranks"') == 2)
    check("推荐是独立页面（#view-ranks 带 data-view）",
          re.search(r'<section id="view-ranks"[^>]*data-view', idx) is not None)
    # 榜单容器必须搬进 #view-ranks、离开发现页 —— 按文档顺序：
    # view-home < view-ranks < ranksBox < view-shelf
    i_home = idx.index('id="view-home"')
    i_view = idx.index('id="view-ranks"')
    i_box = idx.index('id="ranksBox"')
    i_shelf = idx.index('id="view-shelf"')
    check("榜单容器长在 #view-ranks 里（已搬出发现页）",
          i_home < i_view < i_box < i_shelf)
    check("榜单容器全站只有一个（没在发现页留副本）",
          idx.count('id="ranksBox"') == 1
          and idx.count('data-vue-ranks hidden') == 1)
    check("shell.nav() 认识 ranks 视图",
          '["home", "ranks", "shelf", "files"]' in shell_js)
    check("深链 #ranks 路由到推荐页",
          'h === "#ranks"' in main_js and 'nav("ranks")' in main_js)
    # 点书名切回发现页：searchFromHash 体内、runSearch 之前必须有 nav("home")
    sf = disc_js[disc_js.index("export function searchFromHash"):]
    sf_body = sf[:sf.index("runSearch(kw, true);")]
    check("searchFromHash 先切回发现页再搜（点书名不白屏）",
          'nav("home");' in sf_body)
    check("降级 JS 点书名也走 searchFromHash（同一语义）",
          "searchFromHash(t);" in rk_js)
    check("「收起」功能整体下线（Vue 侧无残留）", "ranksFold" not in vue)
    check("「收起」功能整体下线（降级 JS 无残留）", "ranksFold" not in rk_js)
    check("旧折叠样式已清理", ".ranks.folded" not in css)

    # -----------------------------------------------------------------
    print()
    print("== Q. 推荐页不留白 / 进出体验（静态检查）==")
    # ⚠ 这一段的动机：榜单升级成**独立 tab** 之后，同类失败从"少一个区块"
    #   变成了"点进去一片空白"—— 严重程度完全不同，判据必须跟上。
    disc_vue = (ROOT / "frontend/src/components/DiscoverPanel.vue").read_text(encoding="utf-8")
    check("取不到榜单目录时给出说明 + 重试（Vue 侧）",
          'id="ranksKindsErr"' in vue and 'id="ranksKindsRetry"' in vue)
    check("失败时同样把容器露出来（不再有 hidden=true 分支）",
          "box.hidden = false" in vue and "hidden = true" not in vue)
    check("降级路径也不再静默留白（有说明、无 hidden 分支）",
          "ranksKindsErr" in rk_js and "hidden = true" not in rk_js)
    check("切页回到顶部（否则会停在上个页面的半截位置）",
          "window.scrollTo(0, 0);" in shell_js)
    check("发现页空态给出去处：去推荐逛逛",
          'id="homeToRanks"' in disc_vue and 'location.hash = "#ranks"' in disc_vue)
    check("推荐页记住上次看的榜单类别",
          'PRE.get("ranksKind"' in vue and 'PRE.set("ranksKind"' in vue)
    # ⚠ 这条钉的是 hash 去重与 nav() 的同步。
    #   nav() 用 replaceState 改 hash（不触发 hashchange），main.js 又靠
    #   `_lastHash` 去重 —— 两者不同步时，"在推荐页 → 点发现 → 再点
    #   去推荐逛逛" 这串操作里那一次 hashchange 会被当成重复吞掉，
    #   页面纹丝不动。这是真浏览器测出来的，不是设想。
    main_js = (ROOT / "app/static/js/main.js").read_text(encoding="utf-8")
    check("nav() 改 hash 后会广播，main.js 同步去重变量",
          'bus.emit("shell:nav"' in shell_js
          and 'bus.on("shell:nav"' in main_js)
    # 光有按钮不够 —— 它得在首屏折线以上，否则用户不滚就看不见。
    # 真机判据在 test_buttons（固定 1280×705 / 390×690 各测一次）；
    # 这里只钉住"首屏极简档别被删"，防止有人当成多余的样式清掉。
    check("首屏空态用极简档（不放第二张插画，免得把入口顶到折线以下）",
          "#homeEmpty.no-books .empty-art { display: none; }" in disc_vue
          and 'no-books' in disc_vue)

    # -----------------------------------------------------------------
    print()
    print("== R. hodei.net 一页十榜：按块标题选，不按 id ==")
    # ⚠ 这一段的动机（线上实测 2026-10-22）：7 类榜单里 6 类只有 384g 一个
    #   来源，「综合多来源」是句空话。hodei.net/paihang.html 一页挂 10 个榜，
    #   补进来能一次填上 4 类 —— 但它有两个**只表现为静默错数据**的坑：
    #     · 10 个块的 id 全叫 `top_all_1` / `tabData_1`（重复 10 次）；
    #       按 id 取 = 每个标签拿到的都是"总点击"那一份。
    #     · 块名（总点击/月点击/周点击/日点击）高度相似，用"包含"匹配会串。
    #   所以判据必须钉"四类榜拿到的**不是同一份**数据"。
    hd = read("hodei_rank.html")
    hv = ranks.parse_hodei(hd, "allvisit")
    hw = ranks.parse_hodei(hd, "weekvisit")
    hg = ranks.parse_hodei(hd, "goodnum")
    hp = ranks.parse_hodei(hd, "postdate")
    for nm, lst in (("allvisit", hv), ("weekvisit", hw),
                    ("goodnum", hg), ("postdate", hp)):
        check(f"{nm} 解析出条目（{len(lst)} 条）", len(lst) >= 10)
    h_first = {nm: (lst[0]["title"] if lst else None)
               for nm, lst in (("allvisit", hv), ("weekvisit", hw),
                               ("goodnum", hg), ("postdate", hp))}
    print(f"     四个榜的首条：{h_first}")
    # 实测值：总点击=我在精神病院学斩神 / 周点击=拒嫁豪门… / 收藏数=你却爱着一个傻逼
    check("总点击榜首条 = 我在精神病院学斩神（实测）",
          h_first["allvisit"] == "我在精神病院学斩神")
    check("周点击榜首条 = 拒嫁豪门：少奶奶99次出逃（实测）",
          h_first["weekvisit"] == "拒嫁豪门：少奶奶99次出逃")
    check("四个榜拿到的是**四份不同**的数据（按 id 选块会全一样）",
          len(set(h_first.values())) == 4)
    # ⚠ 反证：直接把"第一个 tabData 块"抽出来，就是按 id 选块的结果 ——
    #   四个榜全等于它。这条证明上面那条不是恒真。
    first_block = re.search(r'id="tabData_\d+"([\s\S]*?)</ul>', hd)
    naive_first = re.findall(r'title="([^"]{1,60})"', first_block.group(1)) if first_block else []
    check("反证：按 id 取第一个块会得到「总点击」那一份（四个榜会全撞它）",
          bool(naive_first) and naive_first[0] == h_first["allvisit"]
          and naive_first[0] != h_first["weekvisit"])
    # ⚠ 也不能靠**位置**：把 10 个块的顺序整体倒过来，结果必须不变
    chunks = re.split(r'(?=<div class="index_toplist)', hd)
    head, blocks_ = chunks[0], chunks[1:]
    shuffled = head + "".join(reversed(blocks_))
    check("块顺序被打乱后，四个榜的结果完全不变（不靠位置）",
          [i["title"] for i in ranks.parse_hodei(shuffled, "allvisit")] ==
          [i["title"] for i in hv]
          and [i["title"] for i in ranks.parse_hodei(shuffled, "weekvisit")] ==
          [i["title"] for i in hw])
    check("每条都带 source/source_display",
          all(i.get("source") == "hodei" and i.get("source_display") == "hodei.net"
              for i in hv + hw + hg + hp))
    check("作者都解析出来了（不是空串）",
          all(i.get("author") for i in hv + hw + hg + hp))
    # 实测值：我在精神病院学斩神 → 三九音域
    check("首条作者 = 三九音域（实测）",
          bool(hv) and hv[0]["author"] == "三九音域")
    check("URL 指向站点域", all((i.get("url") or "").startswith("https://www.hodei.net/book/")
                                for i in hv + hw + hg + hp))
    check("kind 传下去了", all(i["kind"] == "weekvisit" for i in hw))
    # `<span class="hits">` 是**这本书的更新日期**，不是本榜的名次值。
    # 判据：同一本书在两个不同的榜里，这个值必须相同（名次值不会相同）。
    def _by_title(lst, t):
        return next((i for i in lst if i["title"] == t), None)

    same_book = "你却爱着一个傻逼"
    a, b = _by_title(hv, same_book), _by_title(hg, same_book)
    check(f"同一本书在不同榜里 updated 相同（{a and a['updated']} / {b and b['updated']}）"
          f"—— 证明它是书籍属性，不是名次值",
          bool(a) and bool(b) and a["updated"] == b["updated"] and bool(a["updated"]))
    # 站点确实没有的榜 → 空，别硬凑，更别拿默认序冒充
    for miss_kind in ("allvote", "lastupdate"):
        check(f"hodei 没有 {miss_kind}（返回空，不硬凑）",
              ranks.parse_hodei(hd, miss_kind) == [])
    # 「月点击」是另一块**真数据**（不是总点击的别名）：首条必须不同
    hm = ranks.parse_hodei(hd, "monthvisit")
    check(f"hodei 月点击能解出来（{len(hm)} 条）", len(hm) >= 10)
    check("月点击 ≠ 总点击（同一页里两块不同的榜）",
          bool(hm) and bool(hv) and hm[0]["title"] != hv[0]["title"])
    check("月点击的 kind 标记正确", all(i["kind"] == "monthvisit" for i in hm))

    # ⚠⚠ 「空表冒充榜单」：实测 推荐数/下载数/评论数/评分 四个 tab 抽出来的
    #    书名**一字不差**（都是 /book/1/、/book/2/… 的默认入库序）。
    #    拿它当"总推荐榜"递给用户 = 编数据。所以解析时比对"下载数"那块，
    #    一模一样就判定"这榜没数据"。
    def hodei_page(blocks: list[tuple[str, list[str]]]) -> str:
        parts = []
        for tab, titles in blocks:
            lis = "".join(
                f'<li><span class="hits">01-0{i}</span><span class="num">{i}.</span>'
                f'<a href="/book/{900 + i}/" title="{t}" target="_blank">{t}</a>'
                f' / <a href="/author/a{i}.html">作者{i}</a></li>'
                for i, t in enumerate(titles, 1))
            parts.append(
                '<div class="index_toplist mright mbottom">'
                f'<div class="toptab" id="top_all_1"><span>{tab}</span></div>'
                f'<div id="tabData_1"><div class="topbooks"><ul>{lis}</ul></div></div></div>')
        return "<html><body>" + "".join(parts) + "</body></html>"

    DEFAULT_SEQ = ["甲书", "乙书", "丙书"]
    fake_same = hodei_page([("下载数", DEFAULT_SEQ), ("收藏数", DEFAULT_SEQ)])
    check("收藏数那块的名单和「下载数」默认序一样 → 判为没数据（不给编）",
          ranks.parse_hodei(fake_same, "goodnum") == [])
    # 反向：名单不一样就得给出来，否则上面那条就是"干脆全都返回空"
    fake_diff = hodei_page([("下载数", DEFAULT_SEQ), ("收藏数", ["真书一", "真书二"])])
    got_diff = ranks.parse_hodei(fake_diff, "goodnum")
    check("收藏数名单和默认序不同 → 照常给出（守卫不是一刀切）",
          [i["title"] for i in got_diff] == ["真书一", "真书二"])
    check("块标题不是整串相等时不认（月点击 ≠ 总点击）",
          ranks.parse_hodei(hodei_page([("月点击", ["书A"])]), "allvisit") == [])
    check("hodei 空串 → 0 条", ranks.parse_hodei("", "allvisit") == [])

    # -----------------------------------------------------------------
    print()
    print("== S. 每类榜单都要有第二个来源（单来源必须登记）==")
    # ⚠ 动机：2026-10-22 线上实测 7 类里 6 类只有 384g 一家。
    #   这条判据的作用不是"现在够不够多"，而是**以后加榜单类别时不许
    #   不加来源就上路** —— 加一类只有一家的榜，用户点开还是"一家站"。
    #
    # ⚠ 2026-10-22 晚：例外清空了。原来 allvote / size 单源是登记过的，
    #   这一轮 allvote 补上落霞 `/rank/allvote/`，size 因为数据是假的整类下线 ——
    #   于是「每类 ≥2 来源」不再有例外。以后真要再开口子，必须在这里写
    #   清楚开放的是哪一类、为什么，而不是把判据改宽。
    SINGLE_OK: set[str] = set()
    single = [k["kind"] for k in ks if len(ranks.sources_for(k["kind"])) < 2]
    print(f"     声明来源数：{ {k['kind']: len(ranks.sources_for(k['kind'])) for k in ks} }")
    check(f"每一类榜单都至少有 2 个来源（单源的：{single}）",
          not single and set(single) <= SINGLE_OK)
    # 同一个 URL 声明两次 = 同一份内容抓两遍，交错出来两条一样的书
    urls = [s["url"] for s in ranks._SOURCES]
    check(f"来源表里没有重复 URL（{len(urls)} 项 / {len(set(urls))} 个地址）",
          len(urls) == len(set(urls)))
    # ⚠ 同一"来源"在**同一类**里不能出现两次（不同 key 但同一 display 也算重复：
    #   页脚"综合 N 个站点"会数成两家，实际是一家）
    dup_disp = [(k["kind"], s["display"]) for k in ks for s in ranks._SOURCES
                if k["kind"] in s["kinds"]
                and [x["display"] for x in ranks._SOURCES
                     if k["kind"] in x["kinds"]].count(s["display"]) > 1]
    check(f"同一类里没有重复的展示名（{dup_disp}）", not dup_disp)
    check("hodei 声明了实测有真数据的那 5 类",
          next(s["kinds"] for s in ranks._SOURCES if s["key"] == "hodei")
          == {"allvisit", "weekvisit", "monthvisit", "goodnum", "postdate"})
    check("hodei 没把「推荐数」那类空表塞给 allvote",
          "allvote" not in next(s["kinds"] for s in ranks._SOURCES if s["key"] == "hodei"))
    # 块名映射表的键必须都是**真的榜单类别** —— 否则映射白写、静默返回空
    check("hodei 的块名映射键都在榜单目录里",
          set(ranks._HODEI_TABS) <= {k["kind"] for k in ks})
    # 落霞 5 个类目共用一个 URL 模板，展开后必须 5 个不同地址
    lx = next(s for s in ranks._SOURCES if s["key"] == "luoxiaks")
    lx_urls = [lx["url"].format(kind=k) for k in sorted(lx["kinds"])]
    check(f"落霞 5 个类目展开成 5 个不同地址（{lx_urls}）",
          len(lx_urls) == len(lx["kinds"]) == len(set(lx_urls)))
    # 384g 的月/周榜是空壳页（HTTP 200、4471 字节、0 行），声明了就是撒谎
    g384 = next(s for s in ranks._SOURCES if s["key"] == "384g")
    check(f"384g 不声明 monthvisit/weekvisit（那两页是空壳，声明了页脚会撒谎）",
          not ({"monthvisit", "weekvisit"} & g384["kinds"]))

    # -----------------------------------------------------------------
    # 「一页多榜」的来源：一轮里只该抓一次。
    #   hodei 一个页面供 4 类榜；不 memo 的话 7 类并发刷新会把这个 49KB
    #   页面抓 4 遍，同域限速把它们排成一条队（每次 ≥0.3s），白等两三秒。
    ranks.fetch_text = fake_fetch
    try:
        ranks.clear_cache()
        asked.clear()
        ranks._fetch_one("allvisit")          # 5 家
        wk3 = ranks._fetch_one("weekvisit")   # xbiquge 周榜 + hodei（同一页）
        ranks._fetch_one("allvisit")          # **同一类再抓一遍**
    finally:
        ranks.fetch_text = real_fetch
    n_hodei = sum(1 for u in asked if "hodei.net" in u)
    n_384g = sum(1 for u in asked if "384g.com" in u)
    check(f"hodei（once 来源）三轮只抓了 {n_hodei} 次", n_hodei == 1)
    # ⚠ 复用 memo 的风险不是"少抓一次"，而是**后面那个 kind 拿到同一份页面后
    #   解析错块**（比如复用成了 allvisit 那一块）。所以必须验内容。
    hw3 = [i for i in wk3 if i.get("source") == "hodei"]
    check(f"复用同一份页面，weekvisit 仍然取到周点击那块（{hw3[0]['title'] if hw3 else None}）",
          bool(hw3) and hw3[0]["title"] == h_first["weekvisit"])
    # 反证：384g 没声明 once —— 同一个 URL 抓了两次就要真的请求两次。
    # 少了这条，"把 once 放开给所有来源"这种改法会一路绿到底，
    # 而那意味着榜单内容永远停在一小时前（旧数据当新数据给用户）。
    check(f"反证：384g 没声明 once，同一个 URL 抓两次就请求 {n_384g} 次",
          n_384g == 2)

    ranks.fetch_text = fake_fetch
    try:
        ranks.clear_cache()               # 清缓存必须连 HTML memo 一起清
        asked.clear()
        ranks._fetch_one("allvisit")
    finally:
        ranks.fetch_text = real_fetch
    check("清缓存后 hodei 会重新抓（memo 被清掉了）",
          sum(1 for u in asked if "hodei.net" in u) == 1)

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
