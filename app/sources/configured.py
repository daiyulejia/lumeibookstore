"""配置化来源 —— 学习爬虫的核心示例。

把「一个小说站」抽象成一份 JSON 配置：
- 搜索 URL 模板、结果条目正则
- 目录页正则、正文正则

新增站点只需在 sites.json 里加一条，无需改 Python 代码。
这演示了爬虫框架最关键的设计思想：**结构与代码分离**。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urljoin

from .. import webfetch
from ..models import Book, BookResult, Chapter
from ..utils import fetch_text, clean_text, normalize_title, cached
from .base import Source, page_mark, page_url, strip_page_mark, tidy_content

logger = logging.getLogger("novel.configured")

CONFIG_FILE = Path(__file__).resolve().parent / "sites.json"
TOC_TTL = 600

#: 目录少于这个条数就认为是"没吃饱"，值得退回通用启发式再试一次。
MIN_TOC = 8

# 从「第123章」「123.」「123、」里抠出章节序号
_CH_NUM_RE = re.compile(r"第\s*(\d{1,5})\s*[章节回]|^\s*(\d{1,5})\s*[.、,，:：)]")


def _chapter_no(title: str) -> Optional[int]:
    m = _CH_NUM_RE.search(title or "")
    if not m:
        return None
    for g in m.groups():
        if g:
            return int(g)
    return None


def _looks_descending(chapters: list) -> bool:
    """目录是不是「最新章节在前」的倒序？

    很多小说站的目录页把最新一章放最前面，照原样抓下来，
    第一章就是「第249章」，用户从"开头"翻开是结局 —— 书就白读了。
    判据：抽前面若干章 + 末尾若干章的序号，看是不是整体递减。
    """
    nums = [(c.index, _chapter_no(c.title)) for c in chapters]
    nums = [(i, n) for i, n in nums if n is not None]
    if len(nums) < 8:
        return False
    head = [n for _, n in nums[:8]]
    tail = [n for _, n in nums[-8:]]
    # 前 8 章序号 > 后 8 章序号，且前段内部也是递减 → 判定倒序
    if not (sum(head) / len(head) > sum(tail) / len(tail)):
        return False
    desc = sum(1 for a, b in zip(head, head[1:]) if a > b)
    return desc >= len(head) - 2


class ConfiguredSource(Source):
    """由 JSON 配置驱动的通用来源。"""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.name = cfg["name"]
        self.display = cfg.get("display", cfg["name"])
        self.priority = cfg.get("priority", 50)
        self.enabled = cfg.get("enabled", True)
        self.base_url = cfg["base_url"]
        self.encoding = cfg.get("encoding")
        self.homepage = cfg.get("homepage", self.base_url)
        # 元信息：给前端「来源健康检查」展示，也说明这条是内置还是自动适配来的
        self.kind = "adapted" if cfg.get("_adapted") else "custom"
        self.engine = cfg.get("_engine", "") or ""
        self.chapter_paged = bool(cfg.get("chapter_paged"))
        self.has_search = bool(cfg.get("search_url"))

    # ---------- 列表清洗 ----------
    def _clean_list(self, items: list[dict]) -> list[dict]:
        """对抽取出的条目做去重 + URL 形状过滤。

        为什么运行时也要做：自动适配器是**照着真实页面**推导正则的，
        推导时用了「URL 形状聚类」把 logo / 导航 / 侧边栏甩掉。
        如果运行时不做同样的事，那套正则落到 ConfiguredSource 手里
        就会把整页链接都当成章节/结果 —— 推导和运行必须一致。
        """
        from .adapter import _dedup_items, _largest_shape_group

        if not self.cfg.get("shape_filter", self.cfg.get("_adapted", False)):
            return items
        return _largest_shape_group(_dedup_items(items))

    # ---------- 搜索 ----------
    def search(self, keyword: str) -> list[BookResult]:
        tpl = self.cfg.get("search_url")

        # 没有搜索接口时，用 direct_url 规则直接拼详情页地址
        if not tpl:
            direct = self.cfg.get("direct_url")
            if direct:
                slug = self.cfg.get("slug_from") or keyword
                url = direct.format(book=slug, kw=slug)
                # 探测该地址是否有效
                try:
                    html = fetch_text(url, encoding=self.encoding)
                    title = self._extract(self.cfg.get("book_title_re", ""), html) or keyword
                    return [BookResult(
                        title=clean_text(title), source=self.name, url=url,
                    )]
                except Exception:  # noqa: BLE001
                    return []
            return []

        url = tpl.format(
            kw=quote(keyword, encoding=self.encoding or "utf-8"),
            kw_gbk=quote(keyword, encoding="gbk"),
        )
        # POST 表单搜索（EmpireCMS 那类）—— 关键词放在请求体里，
        # 自动适配器会在 config 里给出 search_method / search_body。
        if (self.cfg.get("search_method") or "get").lower() == "post":
            body = {
                k: str(v).replace("{kw}", keyword)
                for k, v in (self.cfg.get("search_body") or {"keyword": "{kw}"}).items()
            }
            html = fetch_text(url, encoding=self.encoding, data=body)
        else:
            html = fetch_text(url, encoding=self.encoding)
        results: list[BookResult] = []
        item_re = self.cfg.get("search_item_re", "")
        if not item_re:
            return []
        raw: list[dict] = []
        for m in re.finditer(item_re, html, re.S | re.I):
            gd = m.groupdict()
            raw.append({
                "title": clean_text(gd.get("title", "") or ""),
                "url": (gd.get("url", "") or "").strip(),
                "author": clean_text(gd.get("author", "") or ""),
                "intro": clean_text(gd.get("intro", "") or "")[:200],
            })
        for it in self._clean_list(raw):
            title, href = it["title"], it["url"]
            if not title or not href or len(title) > 60:
                continue
            if href.startswith(("#", "javascript:", "mailto:")):
                continue
            results.append(
                BookResult(
                    title=title,
                    author=it.get("author", ""),
                    source=self.name,
                    url=urljoin(self.base_url, href),
                    intro=it.get("intro", ""),
                )
            )
        return self._dedup(results)[:30]

    @staticmethod
    def _dedup(items: list[BookResult]) -> list[BookResult]:
        seen, out = set(), []
        for it in items:
            k = (normalize_title(it.title), it.url)
            if k in seen:
                continue
            seen.add(k)
            out.append(it)
        return out

    # ---------- 目录 ----------
    def get_chapters(self, result: BookResult) -> list[Chapter]:
        """取目录。书名/作者每次都回填（不能只写在被缓存的函数里）。"""
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
        html = fetch_text(result.url, encoding=self.encoding)
        chapters = self._chapters_by_regex(html, result.url)
        chapters = self._repair_toc(chapters, html, result.url)
        title = ""
        author = ""
        if self.cfg.get("book_title_re"):
            t = self._extract(self.cfg["book_title_re"], html)
            if t:
                title = clean_text(t)
        if self.cfg.get("book_author_re"):
            author = clean_text(self._extract(self.cfg["book_author_re"], html) or "")
        return {"title": title, "author": author, "chapters": chapters}

    def _chapters_by_regex(self, html: str, base: str) -> list[Chapter]:
        """按学到的 `chapter_re` 抽目录（纯静态、不发网络请求）。"""
        ch_re = self.cfg.get("chapter_re", "")
        raw: list[dict] = []
        if ch_re:
            for m in re.finditer(ch_re, html, re.S | re.I):
                gd = m.groupdict()
                raw.append({
                    "title": clean_text(gd.get("title", "") or ""),
                    "url": (gd.get("url", "") or "").strip(),
                })
        chapters: list[Chapter] = []
        for it in self._clean_list(raw):
            title, href = it["title"], it["url"]
            if not title or not href:
                continue
            chapters.append(
                Chapter(index=len(chapters) + 1, title=title, url=urljoin(base, href))
            )
        # 有的站目录是「最新章节在最上面」，不翻过来的话用户从第 1 章开始读
        # 读到的是结局。这里统一按升序修正，并重编 index。
        if _looks_descending(chapters):
            chapters.reverse()
            for i, c in enumerate(chapters, 1):
                c.index = i
        return chapters

    def _repair_toc(
        self, chapters: list[Chapter], html: str, base: str
    ) -> list[Chapter]:
        """目录太少、或明显只有一部分时，退回**通用启发式**再取一次。

        为什么非有这一步不可（2026-10-14 实测 `www.zxs8.net`）：
          学到的 `chapter_re` 只认 `<a href>`，而这个站的整本目录是
          `<a onclick="idm(816445);">第1章 喵</a>`（**没有 href**）——
          详情页上能读到的只有「最新章节」那 12 条。
          于是配置"适配成功"、界面显示"12 章"，用户下完才发现
          《我们猫猫不能听这些》其实有 119 章。

        **配置推导天生脆弱**：它只是对**一个页面**的快照，站方换个模板、
        换套 JS，正则就残废了 —— 而且残废得**悄无声息**（能抽到东西，
        只是抽不全）。所以兜底不能也交给正则，得交给不依赖任何正则的
        通用启发式（`webfetch.extract_toc` + 真实链接驱动的完整性修补）。
        """
        like = [{"url": c.url, "title": c.title} for c in chapters]
        partial, why = webfetch.toc_completeness(like, html)
        if len(chapters) >= MIN_TOC and not partial:
            return chapters

        better = webfetch.extract_toc(html, base)
        picked = better if len(better) > len(like) else like
        picked, _url, _note = webfetch.upgrade_toc(picked, html, base)
        if len(picked) <= len(chapters):
            return chapters
        logger.info(
            "目录兜底：%s 正则只拿到 %d 章（%s），通用启发式拿到 %d 章",
            base, len(chapters), why or "条数偏少", len(picked))
        return [
            Chapter(index=i, title=str(c.get("title") or ""), url=str(c.get("url") or ""))
            for i, c in enumerate(picked, 1)
        ]

    # ---------- 正文 ----------
    def fetch(self, result: BookResult, progress=None, limit=None, stop=None) -> Book:
        chapters = self.get_chapters(result)
        if limit:
            chapters = chapters[:limit]
        book = Book(title=result.title, author=result.author, source=self.name, url=result.url, intro=result.intro)
        book.chapters = self.fetch_all(chapters, self.fetch_chapter, progress, stop)
        return book

    # ---------- 单章（预览用） ----------
    def fetch_chapter(self, chapter: Chapter) -> str:
        # 非「第(x/y)页」式分页的站，也可能把一章拆成 `xxx_1.html` ——
        # 那种续页是页面用 JS 声明出来的（见 webfetch.reading_next_url）。
        # 统一走 fetch_reading_pages 拼接，逻辑只写一份。
        if self.cfg.get("chapter_paged"):
            return self._fetch_paged_chapter(chapter)
        text = webfetch.fetch_reading_pages(chapter.url, self._page_pair)
        return tidy_content(strip_page_mark(text), chapter.title)

    def _page_pair(self, url: str) -> tuple[str, str]:
        """抓一页 → (正文, 原始 HTML)。"""
        html = fetch_text(url, encoding=self.encoding)
        # 正文可能是 `document.writeln(base64)` 写出来的（实测 zxs8）——
        # 不先解，`content_re` 在原始 HTML 上一个字也匹配不到。
        html = webfetch.unwrap_writeln(html)
        if self.cfg.get("content_re"):
            raw = self._extract(
                self.cfg["content_re"],
                html,
                multi=self.cfg.get("content_multi", False),
                filt=self.cfg.get("content_filter"),
            )
            return (clean_text(raw) if raw else ""), html
        # 适配器只学到了「正文容器叫什么」（如 `word_read`），没写得出正则 ——
        # 那种容器里套着容器，非贪婪正则只能取到第一层 `</div>` 之前的一截。
        # 交给通用抽取：它走栈式配对，不怕嵌套。见 adapter._synthesize_content_re。
        return webfetch.extract_content(html, hint=self.cfg.get("content_hint") or ""), html

    def _fetch_paged_chapter(self, chapter: Chapter) -> str:
        """把一章的**所有页**抓齐。两种「一章拆多页」都要认：

        ① 页面标了「第(1/3)页」—— 总页数明说了，按页码往后拼；
        ② 页面没标页数，但内联 JS 声明了续页（`xxx_1.html`，实测 zxs8）。

        只认其中一种就会**静默少给后半章**：界面一切正常，用户以为章节
        本来就这么短。所以走一个循环、**每一步都先问页面自己**
        （`reading_next_url`，站点换模板也跟得上），问不到再退回「按页码
        模板拼」的通用推测（`page_url`）——声明式优先、模板式兜底。
        """
        try:
            body, html = self._page_pair(chapter.url)
        except Exception:  # noqa: BLE001
            return ""
        parts = [strip_page_mark(body)] if (body or "").strip() else []
        seen = {(body or "").strip()}
        mark = page_mark(body)
        total = mark[1] if mark else 0
        if total > 30:  # 这么离谱多半是页脚噪音，别当真
            total = 0
        # 有页数就按页数走；没有就靠声明式续页，给个上限防跑飞。
        limit = total or 6
        cur_url, cur_html = chapter.url, html or ""
        for n in range(1, max(1, limit)):
            u = webfetch.reading_next_url(cur_html, cur_url) or page_url(cur_url, n + 1)
            if not u:
                break
            try:
                nb, nh = self._page_pair(u)
            except Exception:  # noqa: BLE001
                break
            seg = strip_page_mark(nb)
            key = seg.strip()
            # 页码越界时很多站把上一页原样返回 —— 靠「内容没变」判断到底，
            # 不然会把同一页拼 N 遍。
            if not key or key in seen:
                break
            seen.add(key)
            parts.append(seg)
            cur_url, cur_html = u, nh or ""
        return tidy_content("\n\n".join(p for p in parts if p.strip()), chapter.title)

    @staticmethod
    def _extract(pattern: str, html: str, multi: bool = False, filt: Optional[str] = None) -> Optional[str]:
        if not pattern:
            return None
        if multi:
            parts = re.findall(pattern, html, re.S | re.I)
            if not parts:
                return None
            # 逐段清洗：去标签 + 过滤页眉页脚
            f = re.compile(filt) if filt else None
            lines: list[str] = []
            for p in parts:
                seg = p if isinstance(p, str) else "".join(p)
                seg = re.sub(r"<[^>]+>", "", seg)
                seg = seg.strip()
                if not seg:
                    continue
                if f and f.search(seg):
                    continue
                lines.append(seg)
            return "\n\n".join(lines) if lines else None
        m = re.search(pattern, html, re.S | re.I)
        if not m:
            return None
        return m.group(1) if m.groups() else m.group(0)


def load_configured_sources() -> list[ConfiguredSource]:
    """从 sites.json 读取所有启用的来源。"""
    if not CONFIG_FILE.exists():
        return []
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for cfg in data.get("sites", []):
        if not cfg.get("enabled", True):
            continue
        try:
            out.append(ConfiguredSource(cfg))
        except Exception:  # noqa: BLE001
            continue
    return out
