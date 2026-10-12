"""Project Gutenberg 来源（www.gutenberg.org）。

- 官方站点，结构稳定
- 提供公版书籍，含大量中文古典作品
- 支持直接下载纯文本
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from ..models import Book, BookResult, Chapter
from ..utils import get_client, clean_text, fetch_text
from .base import Source

BASE = "https://www.gutenberg.org"


class GutenbergSource(Source):
    name = "gutenberg"
    display = "Gutenberg"
    priority = 5
    homepage = "https://www.gutenberg.org/"
    engine = "gutenberg"

    def search(self, keyword: str) -> list[BookResult]:
        # 站点搜索：支持中英文
        url = f"{BASE}/ebooks/search/?query={keyword.replace(' ', '+')}&submit_search=Go%21"
        html = fetch_text(url)
        results: list[BookResult] = []
        # 结果条目：<li class="booklink"> ... <a href="/ebooks/1234" ...>标题</a>
        for m in re.finditer(
            r'<li class="booklink">[\s\S]*?<a[^>]+href="(?P<url>/ebooks/\d+)"[^>]*>\s*'
            r'<span class="title">(?P<title>[^<]+)</span>\s*[\s\S]*?'
            r'<span class="subtitle">(?P<author>[^<]*)</span>',
            html,
        ):
            gd = m.groupdict()
            results.append(
                BookResult(
                    title=clean_text(gd["title"]),
                    author=clean_text(gd["author"]),
                    source=self.name,
                    url=urljoin(BASE, gd["url"]),
                )
            )
        # 容错：另一套模板
        if not results:
            for m in re.finditer(
                r'<a class="link" href="(?P<url>/ebooks/\d+)"[^>]*>[\s\S]*?'
                r'<span class="title">(?P<title>[^<]+)</span>',
                html,
            ):
                gd = m.groupdict()
                results.append(
                    BookResult(
                        title=clean_text(gd["title"]),
                        source=self.name,
                        url=urljoin(BASE, gd["url"]),
                    )
                )
        return results[:30]

    def get_chapters(self, result: BookResult) -> list[Chapter]:
        """Gutenberg 是整本下载，这里返回单章占位。"""
        return [Chapter(index=1, title=result.title, url=result.url)]

    # ---------- 可用性探测（单页来源，需覆写） ----------
    def probe(self, result: BookResult) -> dict:
        import time as _t

        t0 = _t.time()
        try:
            txt = self._download_text(result)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "chapters": 0,
                    "note": str(e)[:70], "ms": int((_t.time() - t0) * 1000)}
        ms = int((_t.time() - t0) * 1000)
        if len(txt.strip()) < 500:
            return {"ok": False, "chapters": 0, "note": "文本过短", "ms": ms}
        n = len(self._split_chapters(txt)) or 1
        return {"ok": True, "chapters": n, "note": "", "ms": ms}

    def fetch(self, result: BookResult, progress=None, limit=None, stop=None) -> Book:
        """下载纯文本版本并尝试按章节切分。"""
        book = Book(title=result.title, author=result.author, source=self.name, url=result.url)
        txt = self._download_text(result)
        if progress:
            progress(1, 1, "解析正文")
        for i, (title, content) in enumerate(self._split_chapters(txt), 1):
            book.chapters.append(Chapter(index=i, title=title, content=content, url=result.url))
        if not book.chapters:
            book.chapters.append(Chapter(index=1, title=result.title, content=txt, url=result.url))
        if limit:
            book.chapters = book.chapters[:limit]
        return book

    # ---------- 内部 ----------
    def _download_text(self, result: BookResult) -> str:
        """找到并在可用格式中优先取 txt。"""
        page = fetch_text(result.url)
        # 优先 .txt 链接
        m = re.search(r'href="(?P<u>[^"]+\.txt[^"]*)"', page)
        if m:
            return fetch_text(urljoin(BASE, m.group("u")))
        # 退而求其次：HTML 阅读页
        m = re.search(r'href="(?P<u>/files/[^"]+\.html)"', page)
        if m:
            return clean_text(fetch_text(urljoin(BASE, m.group("u"))))
        raise RuntimeError("未找到可下载的文本格式")

    @staticmethod
    def _split_chapters(txt: str) -> list[tuple[str, str]]:
        """按常见章节标题切分。"""
        pattern = re.compile(
            r"^\s*(第[零一二三四五六七八九十百千0-9]+[回章节卷篇][^\n]{0,40}|"
            r"CHAPTER\s+[IVXLC\d]+[^\n]{0,40})\s*$",
            re.M,
        )
        marks = list(pattern.finditer(txt))
        if len(marks) < 3:
            return []
        out: list[tuple[str, str]] = []
        for i, m in enumerate(marks):
            start = m.end()
            end = marks[i + 1].start() if i + 1 < len(marks) else len(txt)
            out.append((m.group(1).strip(), clean_text(txt[start:end])))
        return out
