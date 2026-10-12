"""鲲弩小说来源（kunnu8.com / luoxiadushu.com）。

这是一个 WordPress 站的典型抓取案例，流程：
    1. REST API 搜索   /wp-json/wp/v2/search?search=关键词  → 得到详情页
    2. 详情页解析      从 /indb/{id}.htm 里找到阅读地址（如 /doupo/）
    3. 目录抓取        阅读地址页含全部章节链接
    4. 正文抓取        章节页正文在 <p> 标签集合里

为什么用类而不是配置：
    因为需要「多步解析 + 地址重写」，配置化表达不了。
    这也演示了框架的扩展方式：简单站用 sites.json，复杂站写类。
"""
from __future__ import annotations

import re
import logging
from urllib.parse import quote, urljoin, urlparse

from ..models import Book, BookResult, Chapter
from ..utils import get_client, fetch_text, clean_text, cached, html_to_text, html_unescape
from .base import Source

logger = logging.getLogger("novel.kunnu8")

SITE = "https://www.kunnu8.com"
API_SEARCH = f"{SITE}/wp-json/wp/v2/search"
TOC_TTL = 600

# 正文段落过滤：页眉页脚、导航、评论区、版权声明等
CONTENT_FILTER = re.compile(
    r"(\d{4}年\d{1,2}月\d{1,2}日)"
    r"|收藏本站|Ctrl\+D|上一章|下一章|^目录$"
    r"|章节错误|求收藏|求推荐|（本章完）"
    r"|评论被关闭|发表评论|请输入评论|昵称|邮箱"
    r"|所有内容版权归|All contents are copyrighted"
    r"|本站.*?整理|内容均.*?收集"
    r"|^&nbsp;$|^\s*$"
)

# 中文数字表
_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


def cn_to_int(s: str) -> int | None:
    """把中文数字转成整数，如 一千三百零五 -> 1305。"""
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    total = 0
    section = 0
    number = 0
    for ch in s:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if number == 0:
                number = 1
            section += number * unit
            number = 0
        elif ch == "万":
            section = (section + number) * 10000
            total += section
            section = 0
            number = 0
        else:
            return None
    return total + section + number


def parse_chapter_no(title: str) -> int | None:
    """从章节标题里解析章节号。支持「第X章」「第X节」「第X回」。"""
    m = re.search(r"第\s*([0-9零一二两三四五六七八九十百千]+)\s*[章节回]", title)
    if not m:
        return None
    return cn_to_int(m.group(1))


# 「第70章 人人都这么活着」「149.我爱你」——搜索接口把章节名当书名返回了
_CHAPTER_TITLE_RE = re.compile(
    r"^\s*(?:第\s*[0-9零一二两三四五六七八九十百千]+\s*[章节回卷篇]"
    r"|[0-9]{1,4}\s*[.、,，:：])"
)


_NAME_NOISE = re.compile(
    r"(小说|全集|全本|完结|免费|全文|在线阅读|全文阅读|最新章节|无弹窗"
    r"|txt下载|下载|手机版|阅读|网站|首发|最新章节列表|目录)+$",
    re.I,
)


def _parse_book_meta(html: str) -> tuple[str, str]:
    """从阅读页的 <title> 里抠出书名和作者。

    该站有几种写法::

        大哥小说, 大哥Priest, 大哥小说在线阅读 - 鲲弩小说
        三体小说全集免费在线阅读 - 刘慈欣 - 落霞读书

    共同点：**第 1 段去干净后缀就是书名，第 2 段去干净书名前缀就是作者**，
    站点名在第 3 段（无所谓，不用管）。
    """
    m = re.search(r"<title>([^<]*)</title>", html, re.I)
    if not m:
        return "", ""
    raw = html_unescape(m.group(1)).strip()
    # 逗号 或 「空格+横线+空格」都是分隔符
    parts = [p.strip() for p in re.split(r"\s*[,，]\s*|\s+[-–—|]\s+", raw) if p.strip()]
    if not parts:
        return "", ""

    name = parts[0]
    prev = None
    while prev != name:                      # 后缀可能叠加（小说+全集+免费+在线阅读）
        prev = name
        name = _NAME_NOISE.sub("", name).strip()
    if not name or len(name) > 30:
        name = parts[0].strip()[:30]
    if not name:
        return "", ""

    author = ""
    if len(parts) > 1:
        a = parts[1]
        if a.startswith(name):
            a = a[len(name):]
        prev = None
        while prev != a:
            prev = a
            a = _NAME_NOISE.sub("", a).strip()
        if 1 <= len(a) <= 14 and "在线" not in a:
            author = a
    return name, author


class Kunnu8Source(Source):
    name = "kunnu8"
    display = "鲲弩小说"
    priority = 10
    homepage = SITE + "/"
    engine = "wordpress"

    # 已知的分类/聚合目录，不是书
    EXCLUDE_SEG = {
        "mingzhu", "yuanzhu", "xuanyi", "hot", "yanqing", "hao",
        "xiandai", "dangdai", "kehuan", "wuxia", "tuili", "dan",
        "jingdian", "indb", "zuojia", "book", "page", "tag", "s",
    }

    # ---------- 搜索 ----------
    def search(self, keyword: str) -> list[BookResult]:
        """搜索。

        这个站有**两条**互不覆盖的搜索通路，必须都走：

        1. 站内搜索页 `/search/{kw}` —— 返回的是**书籍级**条目，
           形如「活着 → /huozhe/」，排在最前面，书名干净。
        2. WP REST API `/wp-json/wp/v2/search` —— 只**按文章（=章节）**检索，
           返回「第70章 人人都这么活着」这种，URL 是章节页。

        只走 (2) 会漏书：搜《活着》，余华那本 `/huozhe/` 因为没有任何
        章节标题里带「活着」而**永远不出现** —— 页面上明明就有。
        （这是实测发现的召回缺口，不是理论问题。）

        所以 (1) 优先，(2) 兜底补量；(2) 的结果要把章节 URL 收敛回
        书籍根路径（/saye/122048.htm → /saye/），同一本书只留一条。
        """
        books: dict[str, BookResult] = {}

        # —— 通路 1：站内搜索页，拿干净的书籍条目 ——
        try:
            html = fetch_text(f"{SITE}/search/{quote(keyword, encoding='utf-8')}",
                              retries=1)
            for m in re.finditer(
                r'<a[^>]+href="' + re.escape(SITE) + r'/([A-Za-z0-9_-]{2,30})/"[^>]*>([^<]{2,40})</a>',
                html,
            ):
                seg, title = m.group(1), clean_text(m.group(2))
                if seg.lower() in self.EXCLUDE_SEG or not title:
                    continue
                root = f"{SITE}/{seg}/"
                books[root] = BookResult(title=title, source=self.name, url=root)
        except Exception as e:  # noqa: BLE001
            logger.info("站内搜索页失败: %s", e)

        # —— 通路 2：WP REST API，补章节命中的书 ——
        try:
            r = get_client().get(
                API_SEARCH, params={"search": keyword, "per_page": 20}
            )
            items = r.json()
        except Exception as e:  # noqa: BLE001
            logger.info("WP 搜索失败: %s", e)
            items = []

        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                if it.get("subtype") not in (None, "post"):
                    continue
                title = clean_text(it.get("title", ""))
                root = self._book_root(it.get("url", ""))
                if not root:
                    continue
                cur = books.get(root)
                if cur is None:
                    books[root] = BookResult(title=title, source=self.name, url=root)
                elif not title:
                    continue
                elif _CHAPTER_TITLE_RE.match(cur.title or "") and not _CHAPTER_TITLE_RE.match(title):
                    # 同一本书被多条章节命中时，优先保留「不像章节名」的那个
                    cur.title = title
        return list(books.values())

    def _book_root(self, url: str) -> str:
        """把章节页收敛成书籍根路径：/saye/122048.htm → /saye/。

        注意还有一种情况：WordPress 搜索对**热门书会直接返回详情页**
        （/indb/7369.htm，标题就是干净的书名）。这种不能收敛成
        /indb/（那是分类目录），原样保留，交给 _resolve_read_url 去解析。
        """
        url = (url or "").strip()
        if re.match(r"https?://[^/]+/indb/\d+\.htm", url):
            return url
        m = re.match(r"(https?://[^/]+)/([A-Za-z0-9_-]{2,30})(?:/|$)", url)
        if not m:
            return ""
        seg = m.group(2)
        if seg.lower() in self.EXCLUDE_SEG:
            return ""
        return f"{m.group(1)}/{seg}/"

    # ---------- 目录 ----------
    def get_chapters(self, result: BookResult) -> list[Chapter]:
        """取目录。

        顺带把**真书名/作者**回填到 result —— 搜索接口给的是章节标题，
        书名只有打开阅读页才知道。每次都回填（不能只写在被缓存的函数里），
        否则缓存命中时书名又丢了。
        """
        data = cached(
            f"toc:{self.name}:{result.url}",
            TOC_TTL,
            lambda: self._load_detail(result),
        )
        if data.get("title"):
            result.title = data["title"]
        if data.get("author") and not result.author:
            result.author = data["author"]
        return data.get("chapters") or []

    def _load_detail(self, result: BookResult) -> dict:
        read_url = self._resolve_read_url(result.url)
        if not read_url:
            return {"title": "", "author": "", "chapters": []}
        try:
            html = fetch_text(read_url)
        except Exception:  # noqa: BLE001
            return {"title": "", "author": "", "chapters": []}

        # 优先读页面结构：详情页里有干净的
        #     <div class="book-describe"><h1>活着</h1><p>作者：余华</p>
        # 这比从 <title> 里猜靠谱得多 —— 该站的 <title> 写法很花，
        # 「活着, 余华 活着小说, 活着小说在线阅读 - 落霞读书」这种
        # 按逗号切出来，第二部分是「作者+书名+小说」混在一起的，
        # 会把作者解析成「余华 活着」。
        h1 = re.search(r"<h1[^>]*>([^<]{1,40})</h1>", html, re.I)
        au = re.search(r"作者[：:]\s*([^<\n]{1,20})", html)
        html_title = clean_text(h1.group(1)) if h1 else ""
        html_author = clean_text(au.group(1)) if au else ""
        title, author = _parse_book_meta(html)
        if html_title:
            title = html_title
        if html_author:
            author = html_author

        # 章节链接形如 /doupo/20980.htm
        pat = re.compile(
            r'<a[^>]+href="(?P<url>https?://[^"]+?/\d+\.htm)"[^>]*>(?P<title>[^<]+)</a>',
            re.I,
        )
        seen: set[str] = set()
        items: list[tuple[int, int, str, str]] = []
        for m in pat.finditer(html):
            url = m.group("url")
            t = clean_text(m.group("title"))
            if not t or url in seen:
                continue
            seen.add(url)
            # 优先按标题里的章节号排序（更准）；取不到再用 URL 数字 ID
            cno = parse_chapter_no(t)
            num = re.search(r"/(\d+)\.htm", url)
            url_id = int(num.group(1)) if num else 0
            items.append((cno, url_id, t, url))

        # 排序：有章节号的按章节号；没有的排到最后（按 ID）
        def key(x):
            cno, url_id, _t, _u = x
            return (0, cno, url_id) if cno else (1, url_id, 0)

        items.sort(key=key)
        chapters: list[Chapter] = []
        for i, (_cno, _uid, t, url) in enumerate(items, 1):
            chapters.append(Chapter(index=i, title=t, url=url))
        return {"title": title, "author": author, "chapters": chapters}

    # ---------- 正文 ----------
    def fetch(self, result: BookResult, progress=None, limit=None, stop=None) -> Book:
        chapters = self.get_chapters(result)
        if limit:
            chapters = chapters[:limit]
        book = Book(title=result.title, author=result.author, source=self.name,
                    url=result.url, intro=result.intro)
        book.chapters = self.fetch_all(chapters, self.fetch_chapter, progress, stop)
        return book

    # ---------- 单章（预览用） ----------
    def fetch_chapter(self, chapter: Chapter) -> str:
        try:
            return self._parse_content(fetch_text(chapter.url))
        except Exception:  # noqa: BLE001
            return ""

    # ---------- 内部 ----------
    def _resolve_read_url(self, detail_url: str) -> str:
        """从详情页里找出真正的阅读地址。

        如果传进来的本来就是书籍根路径（/dage/），直接用它 —— 搜索接口
        已经把章节页收敛过了，没必要再抓一次详情页。
        """
        if re.fullmatch(r"https?://[^/]+/[A-Za-z0-9_-]{2,30}/", detail_url or ""):
            seg = urlparse(detail_url).path.strip("/").lower()
            if seg not in self.EXCLUDE_SEG:
                return detail_url
        return cached(
            f"readurl:{self.name}:{detail_url}",
            TOC_TTL,
            lambda: self._resolve_read_url_uncached(detail_url),
        )

    def _resolve_read_url_uncached(self, detail_url: str) -> str:
        try:
            html = fetch_text(detail_url)
        except Exception:  # noqa: BLE001
            return ""

        # 优先找 title 与详情页一致、且路径为「单段小写字母」的链接
        cands = re.findall(
            r'href="(https?://www\.(?:luoxia|kunnu8)\.com/[A-Za-z0-9_-]+/)"[^>]*>([^<]+)<',
            html,
        )
        for url, _name in cands:
            seg = urlparse(url).path.strip("/").lower()
            if seg and seg not in self.EXCLUDE_SEG and re.fullmatch(r"[a-z0-9_-]{2,30}", seg):
                # 统一到当前站点
                return urljoin(SITE + "/", seg + "/")
        return ""

    @staticmethod
    def _parse_content(html: str) -> str:
        """章节页正文：<p> 标签集合。

        页面结构是「正文 <p>... </p> + 评论区」，
        因此遇到评论/版权标记即停止收集，避免把评论混进正文。

        这里 br_fallback=False：传给 html_to_text 的是**整页 HTML**，
        没有 <p> 时按 <br> 切会把导航和页脚都当成正文。
        """
        # 先切掉评论区之后的内容
        cut = re.search(
            r"(评论被关闭|发表评论|相关推荐|猜你喜欢|<div[^>]+id=\"comments?\")",
            html,
        )
        if cut:
            html = html[: cut.start()]
        return html_to_text(html, CONTENT_FILTER, br_fallback=False)
