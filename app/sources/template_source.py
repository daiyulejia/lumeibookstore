"""通用小说站解析器。

很多小说站使用相似的模板（搜索页 / 详情页 / 目录页 / 阅读页），
这里抽象出一套「模板配置 + 通用抓取流程」，站点之间差异部分用正则描述。
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, quote

from ..models import Book, BookResult, Chapter
from ..utils import fetch_text, clean_text, normalize_title, cached
from .base import Source

TOC_TTL = 600


class TemplateSource(Source):
    """基于模板配置的通用来源。"""

    name = "template"
    display = "通用模板"
    base_url = ""

    # 搜索
    search_url = ""            # 含 {kw} 占位
    search_encoding: Optional[str] = None
    # 搜索结果条目正则：需能取到 标题/链接/作者
    search_item_re = r""
    # 目录页章节列表正则
    chapter_re = r""
    # 正文正则
    content_re = r""
    # 书名页里的书名 / 作者
    book_title_re = r""
    book_author_re = r""

    def _abs(self, href: str) -> str:
        return urljoin(self.base_url, href)

    # ---------- 搜索 ----------
    def search(self, keyword: str) -> list[BookResult]:
        if not self.search_url:
            return []
        url = self.search_url.format(kw=quote(keyword, encoding=self.search_encoding or "utf-8"))
        html = fetch_text(url, encoding=self.search_encoding)
        results: list[BookResult] = []
        for m in re.finditer(self.search_item_re, html, re.S):
            gd = m.groupdict()
            title = clean_text(gd.get("title", ""))
            href = gd.get("url", "")
            if not title or not href:
                continue
            author = clean_text(gd.get("author", "") or "")
            results.append(
                BookResult(
                    title=title,
                    author=author,
                    source=self.name,
                    url=self._abs(href),
                    intro=clean_text(gd.get("intro", "") or "")[:200],
                )
            )
        return self._dedup(results)[:30]

    @staticmethod
    def _dedup(items: list[BookResult]) -> list[BookResult]:
        seen = set()
        out = []
        for it in items:
            key = (normalize_title(it.title), it.url)
            if key in seen:
                continue
            seen.add(key)
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
        html = fetch_text(result.url)
        book_title = self._extract(self.book_title_re, html) or result.title
        chapters: list[Chapter] = []
        idx = 0
        for m in re.finditer(self.chapter_re, html, re.S):
            gd = m.groupdict()
            title = clean_text(gd.get("title", ""))
            href = gd.get("url", "")
            if not title or not href:
                continue
            idx += 1
            chapters.append(Chapter(index=idx, title=title, url=self._abs(href)))
        author = self._extract(self.book_author_re, html) or ""
        return {"title": book_title, "author": author, "chapters": chapters}

    # ---------- 正文 ----------
    def fetch(self, result: BookResult, progress=None, limit=None, stop=None) -> Book:
        chapters = self.get_chapters(result)
        if limit:
            chapters = chapters[:limit]
        book = Book(
            title=result.title,
            author=result.author,
            source=self.name,
            url=result.url,
            intro=result.intro,
        )
        book.chapters = self.fetch_all(chapters, self.fetch_chapter, progress, stop)
        return book

    # ---------- 单章（预览用） ----------
    def fetch_chapter(self, chapter: Chapter) -> str:
        try:
            html = fetch_text(chapter.url)
            raw = self._extract(self.content_re, html, multi=True)
            return clean_text(raw) if raw else ""
        except Exception:  # noqa: BLE001
            return ""

    # ---------- 工具 ----------
    @staticmethod
    def _extract(pattern: str, html: str, multi: bool = False) -> str:
        if not pattern:
            return ""
        if multi:
            parts = re.findall(pattern, html, re.S)
            if not parts:
                return ""
            return "\n".join(p if isinstance(p, str) else "".join(p) for p in parts)
        m = re.search(pattern, html, re.S)
        if not m:
            return ""
        if m.groups():
            return m.group(1)
        return m.group(0)
