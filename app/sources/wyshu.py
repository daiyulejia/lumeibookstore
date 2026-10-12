"""无忧书城来源（www.wyshu.com）。

这是一个"搜索接口被封锁 / 需要 POST 且返回 403"时的经典解法案例：

    该站的搜索是 EmpireCMS 的 POST /e/search/index.php，直接请求返回 403。
    但站点把全部书籍按分类列在 /ys/ /wx/ /yq/ ... 等页面里。
    因此改为：**爬取分类页建本地索引 → 在索引里搜索**，完全绕开搜索接口。

另外站点用**拼音 slug** 作为书籍路径（微微一笑很倾城 → /ys/weiweiyixiaohenqingcheng/），
所以还支持「拼音直拼 URL」作为兜底。

结构：
    分类页  /{cat}/                    → 书名 + 链接（约 800 本）
    详情页  /{cat}/{slug}/             → 章节链接 /{cat}/{slug}/{数字}.html
                                         + og:novel:* 元信息（书名/作者/分类/最新章节）
    正文页  <article class="article-post"> 里的 <p> 段落
"""
from __future__ import annotations

import re
import json
import time
import logging
from pathlib import Path
from urllib.parse import urljoin

from ..models import Book, BookResult, Chapter
from ..utils import fetch_text, clean_text, cached, html_unescape, html_to_text
from .base import Source

logger = logging.getLogger("novel.wyshu")

SITE = "https://www.wyshu.com"
CATEGORIES = ["ys", "wx", "yq", "wl", "ds", "xy", "kh", "xd"]

CACHE_FILE = Path(__file__).resolve().parent.parent.parent / "cache" / "wyshu_index.json"
CACHE_TTL = 24 * 3600        # 索引缓存 24 小时
TOC_TTL = 600                # 目录缓存 10 分钟

# 正文垃圾行
JUNK = re.compile(
    r"无忧书城|www\.wyshu\.com|请记住本站|求收藏|求推荐"
    r"|^导航[:：]|本章未完|点击下一页|加入书签|上一章|下一章"
    r"|^&nbsp;$|^\s*$"
)

# og:novel:* 元信息
_META_RE = r'<meta[^>]+(?:property|name)="og:novel:{key}"[^>]+content="([^"]*)"'


class WyshuSource(Source):
    name = "wyshu"
    display = "无忧书城"
    priority = 8
    homepage = SITE + "/"
    engine = "custom"

    # ---------- 搜索（本地索引） ----------
    def search(self, keyword: str) -> list[BookResult]:
        keyword = keyword.strip()
        if not keyword:
            return []
        index = self._load_index()
        kw = keyword.replace("《", "").replace("》", "").replace(" ", "").lower()

        hits: list[BookResult] = []
        for title, meta in index.items():
            t = title.replace(" ", "").lower()
            if kw in t:
                hits.append(
                    BookResult(
                        title=title,
                        author=meta.get("author", ""),
                        source=self.name,
                        url=meta["url"],
                        intro=meta.get("intro", ""),
                    )
                )
        # 标题越短（越接近精确匹配）越靠前
        hits.sort(key=lambda r: (kw not in r.title.lower(), len(r.title)))
        if hits:
            return hits[:30]

        # 索引没有 → 试拼音直拼兜底
        return self._search_by_pinyin(keyword)

    def _search_by_pinyin(self, keyword: str) -> list[BookResult]:
        """用拼音猜 URL（微微一笑很倾城 → weiweiyixiaohenqingcheng）。

        这是「书不在本地索引里」时的兜底方案 —— 只要站点有这本书、且 slug
        正好是整句拼音，就能命中。
        """
        try:
            from pypinyin import lazy_pinyin

            slug = "".join(lazy_pinyin(keyword))
        except Exception:  # noqa: BLE001
            return []
        if not slug:
            return []
        # 拼音 slug 只含字母数字
        slug = re.sub(r"[^a-z0-9]", "", slug)
        if not slug:
            return []

        for cat in CATEGORIES:
            url = f"{SITE}/{cat}/{slug}/"
            try:
                html = fetch_text(url)
            except Exception:  # noqa: BLE001
                continue
            # 确认是详情页（含章节链接）
            if not re.search(rf'/{cat}/{re.escape(slug)}/\d+\.html', html):
                continue
            title, author = self._parse_detail(html)
            title = title or keyword          # 解析失败就用用户输入
            return [BookResult(title=title, author=author, source=self.name, url=url)]
        return []

    # ---------- 索引构建与缓存 ----------
    def _load_index(self) -> dict[str, dict]:
        # 读缓存
        if CACHE_FILE.exists():
            try:
                data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                books = data.get("books")
                if time.time() - data.get("_ts", 0) < CACHE_TTL and books:
                    return books
            except Exception:  # noqa: BLE001
                pass
        # 重建
        books = self._build_index()
        if books:
            try:
                CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                CACHE_FILE.write_text(
                    json.dumps({"_ts": time.time(), "books": books}, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:  # noqa: BLE001
                pass
        return books

    @staticmethod
    def _parse_detail(html: str) -> tuple[str, str]:
        """从详情页解析 (书名, 作者)。

        优先用 og:novel 元信息（最准），退化到 <h1>，再退化到 <title>。
        """
        def meta(key: str) -> str:
            m = re.search(_META_RE.format(key=key), html, re.I)
            return html_unescape(m.group(1)).strip() if m else ""

        title = meta("book_name")
        author = meta("author")
        if not title:
            m = re.search(r"<h1[^>]*>([\s\S]{0,120}?)</h1>", html, re.I)
            if m:
                title = clean_text(re.sub(r"<[^>]+>", "", m.group(1)))
        if not title:
            m = re.search(r"<title>([^<]+)</title>", html, re.I)
            if m:
                title = clean_text(m.group(1).split("_")[0].split("-")[0])
        title, author2 = WyshuSource._parse_title(title)
        return title, (author or author2)

    @staticmethod
    def _parse_title(raw: str) -> tuple[str, str]:
        """把「书名(作者所著小说)_小说在线阅读_无忧书城」拆成 (书名, 作者)。"""
        raw = clean_text(raw)
        author = ""
        m = re.search(r"[（(]([^（()）]{1,12}?)所著小说[)）]", raw)
        if m:
            author = m.group(1).strip()
        # 去掉括号说明和 SEO 后缀
        title = re.sub(r"[（(][^（()）]*[)）]", "", raw)
        title = re.split(r"[_|]", title)[0]
        title = re.sub(r"(全文阅读|在线阅读|最新章节|免费阅读|无弹窗)$", "", title.strip())
        return title.strip(), author

    def _build_index(self) -> dict[str, dict]:
        """爬所有分类页，建立 书名 -> {url, author} 索引。"""
        books: dict[str, dict] = {}
        seen_urls: set[str] = set()
        for cat in CATEGORIES:
            try:
                html = fetch_text(f"{SITE}/{cat}/")
            except Exception as e:  # noqa: BLE001
                logger.info("分类页 %s 抓取失败: %s", cat, e)
                continue
            for m in re.finditer(
                rf'href="(/{cat}/[a-z0-9_-]+/)"[^>]*>([^<]{{2,80}})<', html, re.I
            ):
                url = urljoin(SITE, m.group(1))
                if url in seen_urls:
                    continue
                title, author = self._parse_title(m.group(2))
                if not title:
                    continue
                seen_urls.add(url)
                books[title] = {"url": url, "author": author}
        logger.info("wyshu 索引构建完成：%d 本", len(books))
        return books

    # ---------- 目录 ----------
    def get_chapters(self, result: BookResult) -> list[Chapter]:
        """取目录。

        注意：书名/作者也在这个页面里，所以要**每次**都回填到 result，
        不能只写在被缓存的那个函数里 —— 否则第二次（缓存命中）调用时
        result 上的书名作者就丢了（下载记录里会变成「未知作者」）。
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
        return data["chapters"]

    def _load_detail(self, result: BookResult) -> dict:
        try:
            html = fetch_text(result.url)
        except Exception:  # noqa: BLE001
            return {"title": "", "author": "", "chapters": []}

        title, author = self._parse_detail(html)

        # 章节链接可能是相对路径 /ys/{slug}/{数字}.html，也可能是绝对地址
        path = re.sub(r"^https?://[^/]+", "", result.url).rstrip("/")  # /ys/{slug}
        pat = re.compile(
            rf'<a[^>]+href="(?:https?://[^"]+)?{re.escape(path)}/(?P<id>\d+)\.html"[^>]*>(?P<title>[^<]+)</a>',
            re.I,
        )
        uniq: dict[str, tuple[int, str]] = {}
        for m in pat.finditer(html):
            t = clean_text(m.group("title"))
            if not t:
                continue
            url = f"{SITE}{path}/{m.group('id')}.html"
            uniq[url] = (int(m.group("id")), t)
        ordered = sorted(uniq.items(), key=lambda kv: kv[1][0])
        chapters = [
            Chapter(index=i, title=t, url=url)
            for i, (url, (_nid, t)) in enumerate(ordered, 1)
        ]
        return {"title": title, "author": author, "chapters": chapters}

    # ---------- 正文 ----------
    def fetch(self, result: BookResult, progress=None, limit=None, stop=None) -> Book:
        chapters = self.get_chapters(result)
        if limit:
            chapters = chapters[:limit]
        book = Book(title=result.title, author=result.author,
                    source=self.name, url=result.url)
        book.chapters = self.fetch_all(chapters, self.fetch_chapter, progress, stop)
        return book

    @staticmethod
    def _parse_content(html: str) -> str:
        m = re.search(
            r'<article[^>]*class="[^"]*article-post[^"]*"[^>]*>([\s\S]*?)</article>',
            html, re.I,
        )
        if not m:
            return ""
        # 该站排版不统一：部分章节用 <p>，部分只有 <br/><br/>，
        # 交给 html_to_text 统一处理（br_fallback=True 因为片段已是正文容器）
        return html_to_text(m.group(1), JUNK, br_fallback=True)

    # ---------- 单章（预览用） ----------
    def fetch_chapter(self, chapter: Chapter) -> str:
        try:
            return self._parse_content(fetch_text(chapter.url))
        except Exception:  # noqa: BLE001
            return ""
