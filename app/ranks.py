"""热门榜单：从已适配的小说站抓「点击/推荐/收藏」这类榜单。

为什么做这个
------------
「发现」页原本只能靠书名去搜 —— 你得先知道想读什么。但很多时候人
只是想「看看有什么好看的」。榜单正好填这个空缺：别人已经替你筛过一遍了。

数据源怎么选的（2026-10-11 首次、2026-10-15 扩到多源）
------------------------------------------------------
来源库里当时有 9 个站点，逐个探过：

  ✅ **384g.com** —— 榜单数据最全：`<table id="rankinglist">` 是干净的结构化
     表格，字段有 书名 / 最新章节 / 作者 / 字数 / 更新时间 / 连载状态，
     而且 10 类榜单（总点击 / 月点击 / 总推荐 / 总收藏 / 总字数…）
     **排名各不相同** —— 是真榜单，不是同一张列表换个标题。
     唯一要注意的是编码是 **GBK**。

  ✅ **xbqg5200.com** —— `/top.html`，`li.list-group-item` 列表：
     书名（`a[title]`，书名前带 `[玄幻]` 分类）+ 作者。54 条（6 个分类各 9 条）。

  ✅ **xbiquge.info** —— `/top/`（总榜）、`/top/week_0_1.html`（周榜）…
     每本是一个 `<dd><h3>` 块 + 若干 `<dd class="book_other">` 行，
     带 作者 / 状态 / 更新时间 / 最新章节。**周榜 384g 上是空的，这里有人做。**

  ✅ **luoxiaks.net**（落霞读书）—— `<li class="hot-book2">` 里带书名和作者。
     字段比 384g 少（没有字数、状态），但能在 384g 抽风时兜底。

  ❌ 29zw / tadu / qidian —— 没有稳定的榜单页，或首页是 JS 渲染（HTML 抓不到东西）
  ❌ wyshu / kunnu8 —— 主页上"榜"字只出现在书名里，没有榜单页
  ❌ 月点击榜（monthvisit）—— 三家都没有，别硬凑

⚠ **单一来源 = 只有一家站的书。** 这正是最初版本的毛病：所有标签看着
  不一样，点开全是 384g 那一份 —— 用户翻到底也只看过一家站。所以现在
  每类榜单可以挂**多个来源**（`_SOURCES` 表里按 kind 声明），并且必须
  **按来源交错**（round-robin）合并，见 `_interleave()`。

⚠⚠ **2026-10-22 线上实测：这功能当时仍然是假的。** 逐类数
  `cache/ranks.json` 里的 `source` 集合 —— 7 类里有 **6 类只有一个元素**
  （`384g`）。声明写了 4 家，实际只有 1 家出力，页脚照旧写"综合 4 个站点"。
  原因不是交错写错，而是**别的来源根本没有这几类榜**：
  · xbqg5200 首页 502（服务器自己坏了）、luoxiaks 只有一张综合榜、
  · xbiquge 只有总榜/周榜，没有"字数/推荐/最近更新"。
  这一轮补的是**真能抓到内容**的两个站：
  · **hodei.net/paihang.html** —— 一个页面 10 个榜单块，实测有真数据的 4 类
    （总点击 / 周点击 / 收藏数 / 入库时间），解析要注意的坑见 `parse_hodei`。
  · **xbiquge.info 的 `/lastupdate/` 与 `/lastpost/`** —— 不是榜单页，是列表页，
    但 HTML 结构与 `/top/` 完全一致，直接复用 `parse_xbiquge`。
  补完：`allvisit` 5 家、`weekvisit` 2 家、`goodnum` 2 家、`postdate` 3 家、
  `lastupdate` 2 家；`allvote` 和 `size` 仍是单源 —— 这两类是真没人做，
  有测试盯着"新增榜单类别必须至少两个来源"，例外要在测试里明写。

⚠ **为什么必须交错、不能"主源在前、辅源接在后面"**（这是真踩过的坑）：
  旧写法是 `items.extend(384g)` 然后 `items.extend(luoxiaks)`，最后
  `items[:MAX_ITEMS]`。而 384g 一源就出满 20 条 —— 截断之后**辅源一条都
  看不见**，`cache/ranks.json` 里 allvisit 的 source 集合永远是 `{'384g'}`。
  不报错、不报警，只是"多来源"这个功能**从未生效过**。交错之后
  4 个来源在第 4 条就能全部露脸。

设计取舍
--------
* **缓存 30 分钟**。榜单变化很慢，而抓一次要跑好几个请求。
  更重要的是：别把人家站点当 CDN 刷 —— 这是免费的公开资源，
  高频拉取既不礼貌也容易被封。30 分钟对「看看有什么好书」完全够。
* **一站点失败不能拖垮整体**。每个来源独立 try，返回一部分也比全空好。
* **只抓每个来源的第 1 页**。翻页收益低、请求多，先不做。
* **抓不到就降级**，不留空白页 —— 见 main.py 里 /api/ranks 的 fallback。
* **`source_display` 用域名，不用站点自称的名字。** 三个站都管自己叫
  「新笔趣阁」—— 一律显示"新笔趣阁"的话，用户根本看不出这是**四个不同
  的站**，"综合多来源"就白做了。域名是来源唯一诚实的标识。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

# 复用现有的抓取器：它已经处理了编码猜测（GBK→gb18030）、
# 同域限速、指数退避重试。自己再写一套只会两边不一致。
from .utils import fetch_text

# 缓存落盘的位置。为什么要落盘：进程一重启内存缓存就没了，
# 而「榜单」是那种**没人点也该是热的**东西 —— 用户打开发现页
# 不该先等 3 秒联网。落盘之后重启也能立刻出内容。
# `NOVEL_RANKS` 允许测试用另一份，别把生产缓存搅了。
_ROOT = Path(__file__).resolve().parent.parent
_DB = Path(os.environ.get("NOVEL_RANKS") or (_ROOT / "cache" / "ranks.json"))

# ---------------------------------------------------------------------------
# 榜单定义
# ---------------------------------------------------------------------------
# 只列出**真能抓到内容**的。384g 的 monthvisit / weekvisit 实测是空表
# （站点自己没数据），所以不放进来 —— 放进来只会让用户点开看到一片空白，
# 还以为是程序坏了。
#
# ⚠ weekvisit 后来加回来了：384g 没有，但 **xbiquge.info 的周榜是有内容的**。
#   「哪一类榜单」和「哪个站有这一类」是两件事，别混。见下面 _SOURCES。
SUPPORTED: list[dict[str, str]] = [
    {"kind": "allvisit",   "label": "总点击榜", "desc": "各个站点里被点开最多的"},
    {"kind": "weekvisit",  "label": "本周热读", "desc": "这周读者点开最多的"},
    {"kind": "allvote",    "label": "总推荐榜", "desc": "读者主动推荐最多的"},
    {"kind": "goodnum",    "label": "总收藏榜", "desc": "被收藏最多的"},
    {"kind": "size",       "label": "总字数榜", "desc": "篇幅最长的（适合想追长篇的）"},
    {"kind": "postdate",   "label": "最新入库", "desc": "站点新收录的"},
    {"kind": "lastupdate", "label": "最近更新", "desc": "更新最勤的"},
]
_KINDS = {d["kind"] for d in SUPPORTED}

# ---------------------------------------------------------------------------
# 来源表
# ---------------------------------------------------------------------------
# ⚠ 定义在文件**后面**（`_SOURCES`），因为它的每一项都要指向一个解析函数。
# 那里的注释说明了"为什么按来源写、不按榜单写"。

# 每类榜单最终给多少条。
# 原先 20 —— 那是"只有一个来源"时代的数字。现在一个标签后面可能有 4 个来源，
# 20 条会让每个来源只露 5 条、末尾来源被截掉；30 条大约每源 7~8 条，
# 既"选择更多"又不至于把手机页面拉太长。
MAX_ITEMS = 30


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def _clean(s: str) -> str:
    """去掉标签和多余空白，顺便把 &nbsp; 这类实体处理掉。"""
    s = re.sub(r"<[^>]+>", "", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    return re.sub(r"\s+", " ", s).strip()


def _norm_title(s: str) -> str:
    """书名归一化，**只用于去重比较**，不写回数据。

    ⚠ 必须和前端 `RanksPanel.vue::normTitle()` 用同一套规则。
    那边用它判断"这本书是不是已在你书架里"，这边用它判断
    "两个来源给的是不是同一本书"。两边不一致的后果是：
    榜单上同一本书出现两次（一次标着 384g、一次标着 xbqg5200），
    或者用户明明收了这本书、榜单却还写着"找这本 ›"。

    去掉的是"同一本书在不同站写法不同"的那些差异：书名号、间隔号、
    各种标点、空白，以及大小写。
    """
    s = re.sub(r'[《》「」【】\s·・.。、,，:：!！?？\'"“”‘’()（）\[\]\-—_~～]', "", s or "")
    return s.lower()


def parse_384g(html: str, kind: str) -> list[dict[str, Any]]:
    """解析 384g 的榜单表格。

    结构（实测）:
        <table id="rankinglist">
          <tr><th>小说书名</th><th>最新章节</th>...</tr>
          <tr>
            <td><p><a href="/html/195/195679/">赵氏嫡女</a></p></td>
            <td><p><a href="/html/195/195679/118.html">第..章</a></p></td>
            <td><p>粽爷萌萌哒</p></td>
            <td><p>1057824字</p></td>
            <td><p>2023-09-10</p></td>
            <td><p>连载中</p></td>
          </tr>

    为什么按 `<tr>` 整行切、而不是按 `<td>` 抓：
    因为列的顺序是站点自己定的，某天加一列就会整体错位。
    按行切之后**靠「链接 + 内容特征」认列**，加列不容易崩。

    ⚠ 认作者这一列踩过坑：一开始的写法是「剩下的短文本里第一个当作者」，
    结果把「最新章节」那一格当成了作者 —— 因为像 `新书来了~` 这种
    章节名很短、也不带「第..章」的形状，启发式拦不住，
    页面上就出现了「作者：新书来了~」。
    现在改成**先按位置定位**：第一个 `td` 是书名、第二个是章节、
    第三个是作者 —— 这比猜内容形状可靠得多。特征识别只作为兜底。
    """
    m = re.search(r'id="rankinglist"([\s\S]*?)</table>', html)
    if not m:
        return []
    body = m.group(1)

    out: list[dict[str, Any]] = []
    for row in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", body):
        # 跳过表头
        if "<th" in row:
            continue

        # 书名 = 该行第一个指向书籍详情页的链接
        title_m = re.search(r'<a[^>]+href="(/html/\d+/\d+/?)"[^>]*>([^<]{1,60})</a>', row)
        if not title_m:
            continue
        url = "https://www.384g.com" + title_m.group(1)
        title = _clean(title_m.group(2))
        if not title:
            continue

        # ⚠ 关于「书名里带着作者名」：**这是源站自己的数据脏，不是解析 bug。**
        #   实测 size 榜前几行，站方把作者名拼进了标题链接文字里：
        #       <a href="/html/.../">乡下千金她又掉马甲了茶鸢</a>
        #   而它旁边那格才是作者「孙宝珠」——所以 title 和 author 并不重复，
        #   只是站方书名本身就写歪了（`茶鸢` 是笔名，被粘进了书名）。
        #   这里**故意不做**「把作者从书名尾巴上剪掉」这类清洗：第 3 行标题
        #   叫`茶鸢厉九泽`（笔名+男主名），剪掉`茶鸢`反而更错；而且任何
        #   按字符匹配的剪法都会误伤名字里恰好含这几个字的正常书。
        #   原样透出 + 交给用户判断，比「猜着修」诚实。

        cells = [_clean(c) for c in re.findall(r"<td[^>]*>([\s\S]*?)</td>", row)]

        # --- 按位置认列（主判据）---
        #   实测列序： 书名 | 最新章节 | 作者 | 字数 | 更新 | 状态
        #   但「最新章节」那一格偶尔会缺，所以不能死认第 3 个下标。
        #   做法：把「字数/日期/状态」这几格先挑出来（它们形状唯一、
        #   不会误判），剩下的格子按原顺序排，第 2 个才是作者。
        words = ""
        updated = ""
        status = ""
        rest: list[str] = []
        for c in cells:
            if not c:
                continue
            if re.fullmatch(r"\d+\s*字", c):
                words = c
            elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", c):
                updated = c
            elif c in ("连载中", "已完结", "完结", "全本"):
                status = c
            else:
                rest.append(c)

        # rest 里的顺序就是页面顺序：书名, 最新章节, 作者, ...
        # 书名已经单独拿过了，所以作者是「跳过书名后的第 2 个」。
        author = ""
        others = [c for c in rest if c != title]
        if len(others) >= 2:
            author = others[1]          # 0=最新章节, 1=作者
        elif len(others) == 1:
            # 只有一格：说明这行没给最新章节，那它就是作者。
            # 但要防它是「最新章节」而不是作者 —— 用长度和章节形状筛一下。
            cand = others[0]
            if not re.search(r"第.{0,8}[章节]|大结局|番外|^第[0-9一二三四五六七八九十百千]+", cand):
                author = cand

        out.append({
            "title": title,
            "author": author,
            "url": url,
            "source": "384g",
            # ⚠ 显示名用**域名**而不是"新笔趣阁"。三个来源站都自称"新笔趣阁"，
            #   一律显示中文名的话，用户看到的还是"一个网站"——多来源就白做了。
            "source_display": "384g.com",
            "words": words,
            "updated": updated,
            "status": status,
            "kind": kind,
        })
        if len(out) >= MAX_ITEMS:
            break
    return out


def parse_luoxiaks(html: str, kind: str = "hot") -> list[dict[str, Any]]:
    """解析落霞读书的榜单。

    结构（实测）:
        <li class="hot-book2">
          <a href="https://www.luoxiaks.net/book_88745/" title="叶凡司空嫣然">
            <h2 class="pop-tit">叶凡司空嫣然</h2>
            <span class="pop-intro">家有绝色小姨</span>
          </a>
        </li>

    注意 `<h2 class="pop-tit">` 里是**书名**，`pop-intro` 里是**作者**
    （名字有点误导，实测确认过：斗罗大陆II绝世唐门 → 唐家三少）。
    """
    out: list[dict[str, Any]] = []
    for m in re.finditer(r'<li class="hot-book2">([\s\S]*?)</li>', html):
        block = m.group(1)
        hm = re.search(r'<h2 class="pop-tit">([^<]{1,60})</h2>', block)
        if not hm:
            continue
        title = _clean(hm.group(1))
        if not title:
            continue
        url_m = re.search(r'href="(https?://[^"]*/book_\d+/?[^"]*)"', block)
        url = url_m.group(1) if url_m else ""
        im = re.search(r'<span class="pop-intro">([^<]{1,40})</span>', block)
        author = _clean(im.group(1)) if im else ""

        out.append({
            "title": title,
            "author": author,
            "url": url,
            "source": "luoxiaks",
            "source_display": "落霞读书",
            "words": "",
            "updated": "",
            "status": "",
            "kind": kind,
        })
        if len(out) >= MAX_ITEMS:
            break
    return out


def parse_xbqg5200(html: str, kind: str = "allvisit") -> list[dict[str, Any]]:
    """解析 xbqg5200.com 的 `/top.html`。

    结构（实测）:
        <li class="list-group-item item-34e68100">
          <span class="name">[玄幻] <a href="/2/2201/" title="玩家请上车">玩家请上车</a></span>
          <span class="author">海晏山</span>
        </li>

    ⚠ 两处要留神：

    1. **书名去 `<a>` 的 `title` 属性，不去它的文字。** 页面里
       `[玄幻]` 这个分类前缀写在 `<span class="name">` 里、`<a>` 外面，
       取文字是对的；但有些行的 `[分类]` 会跟着钻进 `<a>` 里
       （站点模板不统一）。`title` 属性永远是干净书名，优先用它，
       取不到再退回文字 + 剥前缀。
    2. `li` 的 class 里有个随机后缀（`item-34e68100`）—— 只能**包含匹配**
       `list-group-item`，不能全等匹配，否则站点一改哈希就整页解析不出来。
    """
    out: list[dict[str, Any]] = []
    for m in re.finditer(
        r'<li[^>]*class="[^"]*\blist-group-item\b[^"]*"[^>]*>([\s\S]*?)</li>', html
    ):
        block = m.group(1)

        a_tag = re.search(r"<a\b[^>]*>", block)
        if not a_tag:
            continue
        tag = a_tag.group(0)
        href = (re.search(r'href="([^"]+)"', tag) or [None, ""])[1]
        if not href:
            continue

        t_attr = re.search(r'title="([^"]{1,60})"', tag)
        if t_attr:
            title = _clean(t_attr.group(1))
        else:
            inner = re.search(r"<a\b[^>]*>([^<]{1,60})</a>", block)
            title = _clean(inner.group(1)) if inner else ""
            # 兜底路径：文字里可能带着 `[玄幻]` 前缀，剥掉
            title = re.sub(r"^\[[^\]]{1,6}\]\s*", "", title)
        if not title:
            continue

        cat_m = re.search(r"\[([^\]]{1,6})\]\s*<a\b", block)
        author_m = re.search(r'<span[^>]*class="[^"]*\bauthor\b[^"]*"[^>]*>([^<]{0,40})</span>', block)

        out.append({
            "title": title,
            "author": _clean(author_m.group(1)) if author_m else "",
            "url": "https://www.xbqg5200.com" + href if href.startswith("/") else href,
            "source": "xbqg5200",
            "source_display": "xbqg5200.com",
            # 分类放 category，**不要塞进 status** —— status 在前端会和
            # 「连载中/已完结」混在一起显示，把分类塞进去会让用户以为
            # 那是更新状态。categories 也可能被别的来源填，先留着备用。
            "category": cat_m.group(1) if cat_m else "",
            "words": "",
            "updated": "",
            "status": "",
            "kind": kind,
        })
        if len(out) >= MAX_ITEMS:
            break
    return out


def parse_xbiquge(html: str, kind: str = "allvisit") -> list[dict[str, Any]]:
    r"""解析 xbiquge.info 的榜单页（`/top/` 总榜、`/top/week_0_1.html` 周榜…）。

    结构（实测）:
        <dd><h3><a href="/11/11913/">[其他]夫人每天都在线打脸</a></h3></dd>
        <dd class="book_other">作者：<span><a href="/search.php?q=…">南之情</a></span></dd>
        <dd class="book_other">状态：完本</dd>
        <dd class="book_other">更新时间：09-08 15:50:59</dd>
        <dd class="book_other">最新章节：<a href="…">第1105章 …</a></dd>

    做法是**按 `<dd><h3>` 切块**：一块 = 一本书。块内的字段用中文标签定位。

    ⚠ 为什么不用 `re.findall(r'<dd>([\s\S]*?)</dd>')` 逐 `<dd>` 取：
    一本书占 5 个 `<dd>`，逐条取会得到"只有书名的一行"和"只有作者的一行"，
    还得再按顺序拼回去 —— 那个拼法在"某本书缺了状态行"时会整体错位。
    按书名块切天然不会有这个问题（字段缺失就只是缺失）。

    ⚠ 书名前的 `[分类]` 前缀写在 `<h3>` 文字里（**在 `<a>` 里面**，
    和 xbqg5200 不一样），所以必须主动剥掉；分类本身保留在 category。
    """
    out: list[dict[str, Any]] = []
    # 第一段是页头（`<dd><h3>` 之前的所有内容），丢掉
    for chunk in re.split(r"<dd\s*>\s*<h3\s*>", html)[1:]:
        link = re.search(r'<a\b[^>]*href="([^"]+)"[^>]*>([^<]{1,80})</a>', chunk)
        if not link:
            continue
        href, raw = link.group(1), _clean(link.group(2))

        cat_m = re.match(r"^\[([^\]]{1,6})\]\s*(.*)$", raw)
        if cat_m:
            cat, title = cat_m.group(1), cat_m.group(2).strip()
        else:
            cat, title = "", raw
        if not title:
            continue

        # 作者：`作者：<span><a …>名字</a></span>`；有的页直接把名字写在冒号后
        author = ""
        a_m = re.search(r"作者[：:]\s*(?:<[^>]+>\s*)*<a\b[^>]*>([^<]{1,40})</a>", chunk)
        if a_m:
            author = _clean(a_m.group(1))
        else:
            a_m = re.search(r"作者[：:]\s*([^<]{1,40})", chunk)
            if a_m:
                author = _clean(a_m.group(1))

        st = re.search(r"状态[：:]\s*([^<]{1,10})", chunk)
        up = re.search(r"更新时间[：:]\s*([^<]{1,20})", chunk)

        out.append({
            "title": title,
            "author": author,
            "url": "https://www.xbiquge.info" + href if href.startswith("/") else href,
            "source": "xbiquge",
            "source_display": "xbiquge.info",
            "category": cat,
            "words": "",
            "updated": _clean(up.group(1)) if up else "",
            "status": _clean(st.group(1)) if st else "",
            "kind": kind,
        })
        if len(out) >= MAX_ITEMS:
            break
    return out


# ---------------------------------------------------------------------------
# hodei.net（好读小说网）—— 一个页面里挂了 10 个榜单块
# ---------------------------------------------------------------------------
# 为什么值得为它单独写解析：**它是唯一一个"总点击/周点击/收藏/入库"四类
# 都有真数据"的站**。加上它之前，7 类榜单里 6 类只有 384g 一家（线上的
# `cache/ranks.json` 里 source 集合就一个元素）—— 用户翻完榜单只见识过
# 一家站，「综合多来源」形同虚设。
#
# 但要小心两个坑（都是实测踩出来的）：
#
# ⚠⚠ **坑一：10 个块的 id 全都一样，id 完全不能当判据。**
#   整页 `id="top_all_1"` 出现 10 次、`id="tabData_1"` 也出现 10 次。
#   按 id 选块 = 永远拿到第 1 块（总点击），于是"周点击"和"总点击"
#   是同一份数据 —— 不报错、不报警，四个标签点开一模一样。
#   唯一可靠的锚是块标题的文字（`<div class="toptab"><span>总点击</span>`）。
#
# ⚠⚠ **坑二：块名高度相似，必须整串相等，不能"包含"。**
#   总点击 / 月点击 / 周点击 / 日点击 四个都带「点击」。
#   用 `"点击" in tab` 之类的写法会把 4 个块当成一类。
#
# ⚠ **坑三：有 4 个 tab 是空的，站方拿默认序冒充榜单。**
#   实测 推荐数 / 下载数 / 评论数 / 评分 四块抽出来的书名**一字不差**
#   （都是 `/book/1/`、`/book/2/`… 的默认入库序）。这不是榜单，
#   是模板兜底。所以：**推荐数不给 allvote 用**，并且解析时拿这个
#   默认序当指纹 —— 目标块的名单跟它一模一样就直接判"这榜没数据"，
#   宁可不给，也不把默认序当"总推荐榜"递给用户。
_HODEI_TABS: dict[str, str] = {
    "allvisit": "总点击",
    "weekvisit": "周点击",
    "goodnum": "收藏数",
    "postdate": "入库时间",
}

# 拿它当"默认序指纹"（见上面坑三）。
_HODEI_DEFAULT_TAB = "下载数"


def _hodei_blocks(html: str) -> list[tuple[str, list[dict[str, Any]]]]:
    """把 hodei 的榜单页切成 `[(块标题, 条目列表), …]`，保持页面顺序。

    结构与切法（实测）:
        <div class="index_toplist mright mbottom">
          <div class="toptab" id="top_all_1"><span>总点击</span></div>
          <div id="tabData_1">
            <div class="topbooks"><ul>
              <li><span class="hits">05-17</span><span class="num">1.</span>
                  <a href="/book/19797/" title="我在精神病院学斩神" target="_blank">…</a>
                  / <a href="/author/sanjiuyinyu.html">三九音域</a></li>
              …
            </ul></div>
          </div>
        </div>

    按 `<div class="index_toplist"` 切块：块与块之间是并列关系，
    切出来的每一段里**只含自己的那一份列表**（下一个块从下一次 split 开始）。
    """
    out: list[tuple[str, list[dict[str, Any]]]] = []
    for chunk in re.split(r'<div class="index_toplist', html)[1:]:
        tm = re.search(r'<div class="toptab"[^>]*>\s*<span>\s*([^<]{1,12}?)\s*</span>',
                       chunk)
        if not tm:
            continue
        tab = tm.group(1)

        ul = re.search(r"<ul[^>]*>([\s\S]*?)</ul>", chunk)
        if not ul:
            out.append((tab, []))
            continue

        rows: list[dict[str, Any]] = []
        for li in re.findall(r"<li[^>]*>([\s\S]*?)</li>", ul.group(1)):
            # 书籍链接：href 和 title 在同一个 <a> 标签里，但属性顺序不保证，
            # 所以先整段取出标签再分别找，别写 `href…title` 这种定序正则。
            tag = re.search(r'<a\b[^>]*href="(/book/\d+/)"[^>]*>', li)
            if not tag:
                continue
            raw_tag = tag.group(0)
            t_attr = re.search(r'title="([^"]{1,60})"', raw_tag)
            if t_attr:
                title = _clean(t_attr.group(1))
            else:
                inner = re.search(r"<a\b[^>]*>([^<]{1,60})</a>", li)
                title = _clean(inner.group(1)) if inner else ""
            if not title:
                continue

            au = re.search(r'href="/author/[^"]*"[^>]*>([^<]{1,20})</a>', li)
            # `<span class="hits">` 其实是**这本书的最近更新日期**（形如 05-17），
            # 不是本榜的名次值 —— 实测同一本书在不同块里这个值相同。
            hit = re.search(r'class="hits"[^>]*>([^<]{1,12})<', li)

            rows.append({
                "title": title,
                "author": _clean(au.group(1)) if au else "",
                "url": "https://www.hodei.net" + tag.group(1),
                "source": "hodei",
                "source_display": "hodei.net",
                "words": "",
                "updated": _clean(hit.group(1)) if hit else "",
                "status": "",
                "kind": "",          # 由 parse_hodei 统一盖，见下
            })
        out.append((tab, rows))
    return out


def parse_hodei(html: str, kind: str) -> list[dict[str, Any]]:
    """解析 hodei.net 的 `/paihang.html`：按**块标题文字**选块。

    `kind` 不在 `_HODEI_TABS` 里（比如 allvote / size / lastupdate）→ 空列表：
    这个站确实没有那几类榜，别硬凑（更别拿默认序冒充，见文件里坑三）。
    """
    tab = _HODEI_TABS.get(kind)
    if not tab:
        return []

    blocks = _hodei_blocks(html)
    picked: Optional[list[dict[str, Any]]] = None
    for name, rows in blocks:
        if name == tab:                 # ⚠ 整串相等，不许用 `in`
            picked = rows
            break
    if picked is None:
        return []

    # 默认序冒充的守卫（坑三）：跟「下载数」那块一模一样 → 这榜没真数据
    dflt = next((rows for name, rows in blocks if name == _HODEI_DEFAULT_TAB), None)
    if dflt and len(dflt) > 1:
        same = ([r["title"] for r in dflt] == [r["title"] for r in picked])
        if same:
            print(f"  [ranks] hodei {kind}（{tab}）抽出来是站点的默认序，"
                  f"不是真榜单，跳过", flush=True)
            return []

    out = picked[:MAX_ITEMS]
    for it in out:
        it["kind"] = kind
    return out


# ---------------------------------------------------------------------------
# 来源表（定义在这里，因为每一项要指向上面这些解析函数）
# ---------------------------------------------------------------------------
# 每一项 = 一个**榜单页**。同一个站点有几种榜就写几项 —— 比如 xbiquge.info
# 的总榜和周榜是两个不同 URL，就是两条（`key` 也不能重）。
#
# 为什么按「来源 → 它能供哪几类榜单」写，而不是「榜单 → 它有哪些来源」：
#   前者的约束是"这个页面上到底排的是什么"，站点写什么就是什么；
#   后者写着写着就会变成"我这类榜单缺数据，把它的总榜塞进去吧" —— 那是**编数据**。
#
# `url` 里的 `{kind}` 只有 384g 用得上（它是 `/paihang/{kind}_1.html`）。
_SOURCES: list[dict[str, Any]] = [
    {
        "key": "384g", "display": "384g.com",
        "url": "https://www.384g.com/paihang/{kind}_1.html",
        "parser": parse_384g,
        "kinds": {"allvisit", "allvote", "goodnum", "size", "postdate", "lastupdate"},
    },
    {
        "key": "luoxiaks", "display": "落霞读书",
        "url": "https://www.luoxiaks.net/top.html",
        "parser": parse_luoxiaks,
        "kinds": {"allvisit"},
    },
    {
        "key": "xbqg5200", "display": "xbqg5200.com",
        "url": "https://www.xbqg5200.com/top.html",
        "parser": parse_xbqg5200,
        "kinds": {"allvisit"},
    },
    {
        "key": "xbiquge", "display": "xbiquge.info",
        "url": "https://www.xbiquge.info/top/",
        "parser": parse_xbiquge,
        "kinds": {"allvisit"},
    },
    {
        "key": "xbiquge-week", "display": "xbiquge.info",
        "url": "https://www.xbiquge.info/top/week_0_1.html",
        "parser": parse_xbiquge,
        "kinds": {"weekvisit"},
    },
    {
        # ⚠ 这两条不是「榜单页」，是站点的**列表页**（首页右上角「更多」跳过去
        #   的那两页）。它们的 HTML 结构和 `/top/` **完全一样**（`<dd><h3>` 块 +
        #   中文标签字段），所以直接复用 `parse_xbiquge` —— 实测 20 条能正常解出。
        #
        #   为什么要它们：`lastupdate`（最近更新）和 `postdate`（最新入库）
        #   原来都只有 384g 一家。这两类数据几乎每个小说站都有，只是不一定
        #   叫「榜」—— 找的时候别只盯着带「排行」二字的页面。
        "key": "xbiquge-lastupdate", "display": "xbiquge.info",
        "url": "https://www.xbiquge.info/lastupdate/",
        "parser": parse_xbiquge,
        "kinds": {"lastupdate"},
    },
    {
        "key": "xbiquge-lastpost", "display": "xbiquge.info",
        "url": "https://www.xbiquge.info/lastpost/",
        "parser": parse_xbiquge,
        "kinds": {"postdate"},
    },
    {
        # 一个页面挂 10 个榜单块 —— 只声明**实测有真数据**的那 4 类。
        # 推荐数 / 下载数 / 评论数 / 评分 四块是默认序冒充，不给 allvote 用。
        # `once`：页面不随 kind 变，一轮刷新里只抓一次（见 _fetch_source）。
        "key": "hodei", "display": "hodei.net",
        "url": "https://www.hodei.net/paihang.html",
        "parser": parse_hodei,
        "once": True,
        "kinds": {"allvisit", "weekvisit", "goodnum", "postdate"},
    },
]


def sources_for(kind: str) -> list[str]:
    """某一类榜单会去哪些站点抓（返回**展示名**，给界面用）。

    界面上「综合 N 个站点」这句话就是靠它算的 —— 而且必须是**声明**
    而不是"从结果里数"：结果里数出来的话，某站今天抽风没抓到，
    界面就会说"来自 3 个站点"，但那其实是**降级**，不是设计。
    """
    return [s["display"] for s in _SOURCES if kind in s["kinds"]]


# ---------------------------------------------------------------------------
# 抓取 + 缓存
# ---------------------------------------------------------------------------
_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_TTL = 1800.0          # 30 分钟
_lock = threading.Lock()

# 「一个页面挂多个榜」的来源，抓回来的 HTML 短时间留一份（见 `_fetch_source`）。
# 只按 **URL** 存，不按 kind —— 存的本来就是同一个页面。TTL 比一次刷新
# 预算长得多、又远小于榜单缓存，够覆盖"7 类连着刷"这一阵子。
_MEMO: dict[str, tuple[float, str]] = {}
_MEMO_TTL = 180.0
# 抓取中标记：同一个人连点两次不该触发两次抓取
_inflight: set[str] = set()
_loaded = False


def _load_from_disk() -> None:
    """把上次落盘的榜单读回内存（只读一次，启动时用）。

    ⚠ 这里**故意不重置时间戳** —— 保留原抓取时刻，这样如果落盘
    至今已超过 TTL，读回来就是"过期"状态，下次访问会自然触发刷新。
    如果把它写成"刚刚抓的"，就会拿一份陈旧数据骗用户 30 分钟。
    """
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        raw = json.loads(_DB.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return          # 没有 / 坏了都当没有，下次抓
    if not isinstance(raw, dict):
        return
    for kind, blk in raw.items():
        if kind not in _KINDS or not isinstance(blk, dict):
            continue
        items = blk.get("items")
        ts = blk.get("ts")
        if isinstance(items, list) and items and isinstance(ts, (int, float)):
            _CACHE[kind] = (float(ts), [i for i in items if isinstance(i, dict)])


def _save_to_disk() -> None:
    """原子落盘。失败不抛 —— 缓存写不进去不该影响接口返回。"""
    try:
        _DB.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: {"ts": ts, "items": items} for k, (ts, items) in _CACHE.items()}
        tmp = _DB.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _DB)          # 原子替换，不会读到半个文件
    except Exception as e:  # noqa: BLE001
        print(f"  [ranks] 缓存落盘失败（不影响使用）：{e}", flush=True)


def cache_status() -> dict[str, Any]:
    """给界面/接口看的缓存体检：每类几条、多久前抓的、是否还新鲜。

    定时任务和界面上的「x 分钟前更新」都靠它。
    """
    _load_from_disk()
    now = time.time()
    out: dict[str, Any] = {"ttl": int(_TTL), "kinds": {}}
    for d in SUPPORTED:
        k = d["kind"]
        hit = _CACHE.get(k)
        # `sources` 是**声明**（该去哪几个站），`got` 是**实际抓到的来源数**
        # （从 items 里去重数出来的）。两个都留着 —— 数量对不上就说明
        # 有站点在抽风，而这个差别在界面上表现为"榜单条目变少了"，
        # 不主动记下来根本发现不了。
        srcs = sources_for(k)
        got: list[str] = []
        if hit:
            for it in hit[1]:
                s = it.get("source_display") or it.get("source") or ""
                if s and s not in got:
                    got.append(s)
        if hit:
            age = now - hit[0]
            out["kinds"][k] = {
                "count": len(hit[1]),
                "age": int(age),
                "fresh": age < _TTL,
                "updated_at": int(hit[0]),
                "sources": srcs,
                "got": got,
            }
        else:
            out["kinds"][k] = {"count": 0, "age": None, "fresh": False,
                               "updated_at": None, "sources": srcs, "got": []}
    ages = [v["age"] for v in out["kinds"].values() if v["age"] is not None]
    out["stale_count"] = sum(1 for v in out["kinds"].values() if not v["fresh"])
    out["oldest_age"] = max(ages) if ages else None
    out["total"] = sum(v["count"] for v in out["kinds"].values())
    return out


def _fetch_source(src: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """抓单个来源。**吞掉异常**并打印 —— 返回 [] 而不是往上抛。

    为什么吞：一个站抽风不该让整类榜单变空。调用方拿到的是"其他来源的并集"，
    少一家总比一条都没有强。

    `src["once"] = True` 的来源（页面不随 kind 变化，比如 hodei 一个页面挂
    10 个榜）**同一轮里只抓一次**：7 类榜单并发刷新时，不然同一个 49KB 页面
    会被抓 4 遍 —— 同域限速把那 4 次排成一条队（每次至少 0.3s 间隔），
    白等两三秒，还可能把整次刷新顶过预算（预算到点就收手，剩下的类别
    这一轮就不更新了）。
    """
    url = src["url"].format(kind=kind)
    # ⚠ 一个来源要不要走 memo，只在**这一处**决定（读写共用这个变量）。
    #   分开写两个 `if src.get("once")` 的话，改错一处只影响一半：
    #   比如"写"那半也放开 —— 所有来源都会被当成"一轮只抓一次"，
    #   榜单内容就永远停在一小时前，而且不报错。反证脚本正是靠这一行
    #   来验"只有声明过的来源才复用"的。
    once = bool(src.get("once"))

    html: Optional[str] = None
    if once:
        now = time.time()
        with _lock:
            hit = _MEMO.get(url)
        if hit and now - hit[0] < _MEMO_TTL:
            html = hit[1]

    if html is None:
        try:
            html = fetch_text(url)
        except Exception as e:  # noqa: BLE001
            print(f"  [ranks] {src['key']} {kind} 抓取失败：{e}", flush=True)
            return []
        if once:
            with _lock:
                _MEMO[url] = (time.time(), html)

    try:
        items = src["parser"](html, kind)
    except Exception as e:  # noqa: BLE001
        print(f"  [ranks] {src['key']} {kind} 解析失败：{e}", flush=True)
        return []
    if not items:
        print(f"  [ranks] {src['key']} {kind} 解析出 0 条（站点改版？）", flush=True)
    return items


def _interleave(buckets: list[list[dict[str, Any]]], limit: int) -> list[dict[str, Any]]:
    """把多个来源的结果**按来源轮流取一条**，合并去重后截断。

    ⚠ 这里是整个多来源功能的命门，改成"按来源顺序一段一段拼"就退化回
    单一来源了（`items[:20]` 会把后面的来源全切掉，且**不报任何错**）。
    所以 tools/test_ranks.py 和 tools/mutate.py 都盯着"交错"这个性质。

    顺序：A1 B1 C1 D1 A2 B2 C2 D2 …（A/B/C/D 是来源）
    去重：按 `_norm_title(title)`（书名归一化，见上），保留**先出现**的那条
      —— 先出现 = 排名更靠前的那个来源，它的 author/字数等字段也更全。
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    if not buckets:
        return out

    depth = max(len(b) for b in buckets)
    for i in range(depth):
        for b in buckets:
            if i >= len(b):
                continue
            it = b[i]
            title = it.get("title") or ""
            key = _norm_title(title)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(it)
            if len(out) >= limit:
                return out
    return out


def _fetch_one(kind: str) -> list[dict[str, Any]]:
    """抓某一类榜单：把 `_SOURCES` 里声明支持它的来源**并行**跑一遍，
    交错合并去重，截到 MAX_ITEMS。

    * 并行：不同域名，`utils.fetch_text` 的同域限速互不影响，所以并行是安全的；
      串行的话 4 个源排在一条线上，最慢的那个决定总耗时（实测能到十几秒）。
    * 单源失败不抛 —— 见 `_fetch_source`。
    * 未知 kind / 没有来源支持 → 空列表（不是异常）。
    """
    srcs = [s for s in _SOURCES if kind in s["kinds"]]
    if not srcs:
        return []

    buckets: list[list[dict[str, Any]]] = []
    if len(srcs) == 1:
        # 一个来源就别起线程池了，纯属开销
        buckets.append(_fetch_source(srcs[0], kind))
    else:
        # 按**声明顺序**收结果（as_completed 的完成顺序不可预测，
        # 用它会导致"谁是第一个来源"在两次刷新之间跳来跳去，
        # 交错出来的次序也跟着乱 —— 排行榜最忌讳名次随机变）。
        with ThreadPoolExecutor(max_workers=min(4, len(srcs))) as ex:
            futs = {ex.submit(_fetch_source, s, kind): idx for idx, s in enumerate(srcs)}
            got: dict[int, list[dict[str, Any]]] = {}
            for f in as_completed(futs):
                try:
                    got[futs[f]] = f.result()
                except Exception as e:  # noqa: BLE001
                    print(f"  [ranks] 来源 {futs[f]} {kind} 异常：{e}", flush=True)
                    got[futs[f]] = []
            buckets = [got.get(i, []) for i in range(len(srcs))]

    return _interleave(buckets, MAX_ITEMS)


def get_rank(kind: str) -> list[dict[str, Any]]:
    """取某一类榜单（带缓存）。未知 kind 返回空列表。

    ⚠ 缓存策略是 **stale-while-revalidate（先给旧的，后台再去抓）**。
    改这里之前先读下面这段 —— 它修的是一个真实的首屏体验问题：

      原来：缓存过期后**同步**去抓（全量榜单要十几秒甚至几十秒）。
        症状：用户打开首页，榜单区一直转圈；服务冷启动 + 机器忙时
        实测能到 60 秒以上（ship 的并发真机测试就是被这个打红的）。
      现在：只要手上有上一份数据（哪怕过期很久），**立刻返回**，
        同时起一个后台线程去刷新。用户 0 秒看到榜单，几十秒后
        界面上的「x 分钟前更新」会自然变成"刚刚更新"。

    边界处理：
      · 从没有过缓存（首次部署）→ 只能同步等，没有别的选择；
      · 已有人在抓 → 不重复抓，直接把旧数据给他；
      · 抓取失败 → 旧数据留在缓存里不动（下面 `if items` 那句守着）。
    """
    if kind not in _KINDS:
        return []

    _load_from_disk()
    now = time.time()
    hit = _CACHE.get(kind)
    if hit and now - hit[0] < _TTL:
        return hit[1]

    # —— 缓存过期，但手上有旧数据 ——
    # 立刻还给用户，抓取丢后台。
    if hit and hit[1]:
        _kick_bg_refresh(kind)
        return hit[1]

    # —— 从来没有过缓存：只能同步等 ——
    # 已有别人在抓这一类 → 等它，别重复抓
    with _lock:
        hit = _CACHE.get(kind)
        if hit and now - hit[0] < _TTL:
            return hit[1]
        if hit and hit[1]:
            # 刚才那一瞬别人抓回来了，直接用
            return hit[1]
        if kind in _inflight:
            return hit[1] if hit else []
        _inflight.add(kind)

    try:
        items = _fetch_one(kind)
        if items:      # 只在真拿到东西时才覆盖缓存 ——
            _CACHE[kind] = (time.time(), items)   # 空的别把上次的好数据冲掉
            _save_to_disk()
            return items
        # ⚠ 抓空了（站点限流 / 抽风）—— **别急着返回空**。
        #   手上那份**过期**缓存对用户仍然远比空白页有价值。
        #
        #   踩过：384g.com 与 luoxiaks.net 双双进入冷却时，明明 cache/ranks.json
        #   里躺着 20 条旧榜，「总推荐榜」标签却是一片空白。原因就在上面那行
        #   `return items` —— 它把 stale 缓存彻底无视了。
        #   注意上面那句注释「空的别把上次的好数据冲掉」只管住了**写入**，
        #   没管住**返回**，于是文件头「抓不到就降级，不留空白页」的承诺
        #   在这里破了个洞。（这个洞**不报错**，只表现为"标签点开是空的"，
        #   人工回归很容易漏 —— 所以另配了 tools/test_ranks_stale.py。）
        if hit and hit[1]:
            return hit[1]
        return items
    finally:
        with _lock:
            _inflight.discard(kind)


# 后台刷新线程集合：防同一类榜单被同时刷两遍。
# 用 _lock 保护（和 _inflight 共用同一把锁，避免两套互斥量打架）。
_BG: set[str] = set()


def _kick_bg_refresh(kind: str) -> None:
    """起一个后台线程去刷新某一类榜单（不阻塞调用方）。

    ⚠ 为什么必须是 daemon 线程：服务被 Ctrl-C / 被 systemd 重启时，
    不能让一个抓取中的线程把进程吊住不退出（用户会遇到"关不掉"）。
    抓一半被杀没有副作用 —— 缓存要么是旧的完整数据、要么还没写入。
    """
    import threading

    with _lock:
        if kind in _inflight or kind in _BG:
            return          # 已经有人在抓了，别重复
        _BG.add(kind)

    def _work() -> None:
        try:
            items = _fetch_one(kind)
            if items:
                with _lock:
                    _CACHE[kind] = (time.time(), items)
                _save_to_disk()
                print(f"  [ranks] 后台刷新 {kind}：{len(items)} 条", flush=True)
            else:
                print(f"  [ranks] 后台刷新 {kind}：没抓到，保留旧数据", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  [ranks] 后台刷新 {kind} 失败：{e}", flush=True)
        finally:
            with _lock:
                _BG.discard(kind)

    threading.Thread(target=_work, name=f"ranks-bg-{kind}", daemon=True).start()


# 「立即刷新」的总预算与并发度。
# ⚠ 为什么要这两条（线上实测 2026-10-21）：
#   `/api/ranks/refresh` 两次分别用了 **47.2 秒 / 33.0 秒**
#   （日志：`status=200 ms="47229 慢"`，其中一次正好在 01:00 榜单定时任务之后）。
#   调用方是**定时任务（不带 kind = 全部 7 类）**；界面上的「刷新」按钮
#   只带一个 kind（单类并发抓 3~4 个源），所以按钮本身并不慢。
#   根因：refresh() 把 7 个类别**串行**跑 —— 每个类别内部虽然并发，
#   但类别之间一个接一个，总时长 = 7 份单类耗时相加 ≈ 40 秒，和实测对得上。
#   这直接拖长夜间任务的窗口（顺带挤占同一时段的学习任务带宽）。
#   现在类别之间也并发（3 个一批，和 get_many 用同一个并发度），
#   并且给整次刷新一个总预算：到点就收手，**已经抓到的照样写缓存**，
#   没跑完的如实放进 `pending` 返回（收手可以，不许沉默地收手）。
RANKS_REFRESH_BUDGET = 25.0
RANKS_REFRESH_WORKERS = 3


def refresh(kinds_: Optional[list[str]] = None, force: bool = True) -> dict[str, Any]:
    """主动刷新榜单。给定时任务和「立即刷新」按钮用。

    force=True 时**无视 TTL 重抓**（定时任务要的就是这个）；否则只补过期的。
    返回一份结果摘要，方便定时任务打日志。

    `pending` = 撞总预算收手时**还没跑完**的类别（这些的缓存保持旧值）。
    """
    _load_from_disk()
    want = [k for k in (kinds_ or [d["kind"] for d in SUPPORTED]) if k in _KINDS]
    started = time.time()
    now = time.time()
    targets = want if force else [
        k for k in want
        if not (_CACHE.get(k) and now - _CACHE[k][0] < _TTL)
    ]

    ok, failed, skipped = 0, 0, len(want) - len(targets)

    def _one(k: str) -> Optional[bool]:
        """抓一类。返回 True=成功 / False=失败 / None=跳过（别人正在抓）。"""
        # ⚠ 别和后台自动刷新撞车：同一类榜单同时在抓两次，纯属浪费
        #   （第三方站有速率限制，多抓一次就多一分被限流的风险）。
        #   已经有后台线程在刷 → 跳过，等它写完缓存就是最新的了。
        with _lock:
            if k in _BG or k in _inflight:
                return None
            _inflight.add(k)
        try:
            items = _fetch_one(k)
            if items:
                with _lock:
                    _CACHE[k] = (time.time(), items)
                return True
            # 抓到空：多半是站点抽风。不覆盖旧缓存，计入 failed。
            return False
        except Exception as e:  # noqa: BLE001
            print(f"  [ranks] refresh {k} 失败：{e}", flush=True)
            return False
        finally:
            with _lock:
                _inflight.discard(k)

    done: dict[str, Optional[bool]] = {}
    if targets:
        pool = ThreadPoolExecutor(
            max_workers=min(RANKS_REFRESH_WORKERS, len(targets)))
        futs = {pool.submit(_one, k): k for k in targets}
        try:
            for f in as_completed(futs, timeout=RANKS_REFRESH_BUDGET):
                k = futs[f]
                try:
                    # ⚠ 必须是三态原样保存：True=成功 / False=失败 / None=跳过。
                    #   写 `bool(f.result())` 会把 None 压成 False ——
                    #   "别人正在抓、我跳过"就被算成"抓失败了"，
                    #   统计上凭空多出一批失败（实测就是这么被测试抓到的）。
                    done[k] = f.result()
                except Exception:  # noqa: BLE001
                    done[k] = False
        except Exception:  # noqa: BLE001  超预算（含 futures.TimeoutError）
            print(f"  [ranks] 刷新超预算（{RANKS_REFRESH_BUDGET:.0f}s），先收手："
                  f"已完成 {len(done)}/{len(targets)}", flush=True)
        finally:
            # 不等没回来的慢源 —— 它们在后台自然结束（每次抓取都有 timeout），
            # 这一轮的调用方不该陪着它们等。
            pool.shutdown(wait=False, cancel_futures=True)

    for r in done.values():
        if r is None:
            skipped += 1
        elif r:
            ok += 1
        else:
            failed += 1
    pending = [k for k in targets if k not in done]
    if ok:
        _save_to_disk()
    return {
        "ok": ok, "failed": failed, "skipped": skipped,
        "pending": len(pending), "pending_kinds": pending,
        "targets": targets, "elapsed": round(time.time() - started, 2),
        "status": cache_status(),
    }


def get_many(kinds: list[str]) -> dict[str, list[dict[str, Any]]]:
    """并发取多类榜单。用于「一次把所有标签的角标都填上」。"""
    _load_from_disk()
    kinds = [k for k in kinds if k in _KINDS]
    if not kinds:
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    # 3 个线程够了 —— 一共就 6 个请求，而且 utils 里有同域限速，
    # 开更多只会一起排队，反而更容易触发对方的风控。
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(get_rank, k): k for k in kinds}
        for f in as_completed(futs):
            k = futs[f]
            try:
                out[k] = f.result()
            except Exception:  # noqa: BLE001
                out[k] = []
    return out


def kinds() -> list[dict[str, str]]:
    """榜单目录，给前端渲染标签用。"""
    return [dict(d) for d in SUPPORTED]


def clear_cache() -> None:
    """清空内存+磁盘缓存。测试用；也留给「强制重来一次」。"""
    global _loaded
    with _lock:
        _CACHE.clear()
        # ⚠ `_MEMO` 也要清 —— 它缓存的是**抓回来的 HTML**。不清的话
        #   "强制重来一次"仍可能拿到上一次的页面（对用户就是"点了刷新
        #   内容没变"），测试里换一份假网络也会读到上一份假页面。
        _MEMO.clear()
        _loaded = True
        try:
            _DB.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
