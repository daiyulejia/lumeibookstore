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

# 搜索的墙钟上限（秒）。**这是 2026-10-24 复盘补的，和第 ① 个 186s 事故同源。**
#
# 病灶：这个源的搜索有两条「串行打 N 个页面」的路径，都没有任何时间上限 ——
#   ① 索引过期时 `_build_index()` 串行抓 8 个分类页（缓存 TTL 24h，所以
#      每天第一次搜索必然走这条）；
#   ② 索引里没命中时 `_search_by_pinyin()` 再串行试 8 个分类的拼音 URL。
# 两条加起来最坏 16 次请求。引擎的扇出硬上限是 20s，而**当别的源也没出结果时
# （streamed=0）引擎不会早收手**，于是一个卡住的 wyshu 就能把整轮搜索拖满 20s，
# 到点仍是 0 条 —— 用户看到的是"搜不到"，日志里只有 `未回=wyshu`。
#
# 线上实测（2026-10-24 01:0x）：搜《我们猫猫不能听这些》
#   耗时ms=20040 候选=0 成书=0 可读=0 答=4/5 未回=wyshu
#   同一本书 5 分钟前的一次：耗时ms=7840 候选=1（1 本可读）
# ——同一本书两次结果相反，差的就是"wyshu 这轮回没回来"。
#
# 6s 的取值沿用 wikisource（同样的取舍：够它抓完正常情况下的两三页，
# 又不会比整轮预算更长寿）。判据不看耗时，只看"到点还发不发下一次请求"。
SEARCH_BUDGET = 6.0

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

    # 搜索墙钟上限。挂成类属性（而不是只留在模块级）是为了能被测试/特殊场景
    # 按实例覆盖 —— 与 wikisource 的做法一致。
    SEARCH_BUDGET = SEARCH_BUDGET

    # ---------- 搜索（本地索引） ----------
    def search(self, keyword: str) -> list[BookResult]:
        keyword = keyword.strip()
        if not keyword:
            return []
        # 整轮（建索引 + 拼音兜底）共用一个 deadline —— 两段各自限额是不够的，
        # 8 + 8 = 16 次请求照样能突破 6s。见 SEARCH_BUDGET 的注释。
        deadline = time.time() + self.SEARCH_BUDGET
        index = self._load_index(deadline=deadline)
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
        return self._search_by_pinyin(keyword, deadline=deadline)

    def _search_by_pinyin(self, keyword: str,
                          deadline: float | None = None) -> list[BookResult]:
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

        tried = 0
        for cat in CATEGORIES:
            # 到点就不发下一次 —— 这是"每秒都在烧配额"和"整轮搜索被一个源拖死"
            # 之间的那条线。**必须真的不发**，不能发完再看时间。
            if deadline is not None and time.time() >= deadline:
                logger.info("拼音兜底到点收手：已试 %d/%d 个分类（预算 %.0fs）",
                            tried, len(CATEGORIES), self.SEARCH_BUDGET)
                break
            tried += 1
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
    def _load_index(self, deadline: float | None = None) -> dict[str, dict]:
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
        books, complete = self._build_index(deadline=deadline)
        # ⚠ 只有**抓完全部分类**才写缓存。
        #   被预算截断时写下去，等于把一份残缺索引缓存 24 小时 ——
        #   之后每一次搜索都在残缺索引里查，缺的书永久查不到，
        #   而且没有任何报错（缓存命中是最快路径，反而最不可能被怀疑）。
        #   宁可这一轮没缓存、下一轮再抓一次。
        if books and complete:
            try:
                CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                CACHE_FILE.write_text(
                    json.dumps({"_ts": time.time(), "books": books}, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:  # noqa: BLE001
                pass
        elif not books:
            # 一本都没抓到 = 这个源这一轮等于不存在。**必须说出来** ——
            # 静默返回 [] 会被引擎记成"答话了、只是没这本书"（note_ok），
            # 熔断器永远学不到，于是每轮搜索都还在为它付时间。
            self.note_error(RuntimeError("索引为空：分类页全部抓取失败"))
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

    def _build_index(self, deadline: float | None = None) -> tuple[dict[str, dict], bool]:
        """爬所有分类页，建立 书名 -> {url, author} 索引。

        返回 `(索引, 是否抓完全部分类)`。第二个值决定**能不能写缓存** ——
        被预算截断时抓到的只是残缺索引，缓存它等于把缺口固化 24 小时
        （见 _load_index 里的注释）。
        """
        books: dict[str, dict] = {}
        seen_urls: set[str] = set()
        complete = True
        for _i, cat in enumerate(CATEGORIES):
            # 到点立刻停：**不发**这一次请求，而不是发完再判。
            if deadline is not None and time.time() >= deadline:
                complete = False
                logger.info("索引构建到点收手：已抓 %d/%d 个分类、%d 本"
                            "（预算 %.0fs，本轮不写缓存）",
                            _i, len(CATEGORIES), len(books), self.SEARCH_BUDGET)
                break
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
        if complete:
            logger.info("wyshu 索引构建完成：%d 本", len(books))
        return books, complete

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
