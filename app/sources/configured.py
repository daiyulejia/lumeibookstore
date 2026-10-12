"""配置化来源 —— 学习爬虫的核心示例。

把「一个小说站」抽象成一份 JSON 配置：
- 搜索 URL 模板、结果条目正则
- 目录页正则、正文正则

新增站点只需在 sites.json 里加一条，无需改 Python 代码。
这演示了爬虫框架最关键的设计思想：**结构与代码分离**。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urljoin

from ..models import Book, BookResult, Chapter
from ..utils import fetch_text, clean_text, normalize_title, cached
from .base import Source, page_mark, page_url, strip_page_mark, tidy_content

CONFIG_FILE = Path(__file__).resolve().parent / "sites.json"
TOC_TTL = 600

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
                Chapter(index=len(chapters) + 1, title=title, url=urljoin(result.url, href))
            )
        # 有的站目录是「最新章节在最上面」，不翻过来的话用户从第 1 章开始读
        # 读到的是结局。这里统一按升序修正，并重编 index。
        if _looks_descending(chapters):
            chapters.reverse()
            for i, c in enumerate(chapters, 1):
                c.index = i
        title = ""
        author = ""
        if self.cfg.get("book_title_re"):
            t = self._extract(self.cfg["book_title_re"], html)
            if t:
                title = clean_text(t)
        if self.cfg.get("book_author_re"):
            author = clean_text(self._extract(self.cfg["book_author_re"], html) or "")
        return {"title": title, "author": author, "chapters": chapters}

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
        text = self._fetch_page(chapter.url)
        if not self.cfg.get("chapter_paged"):
            return tidy_content(strip_page_mark(text), chapter.title)

        # 一章被拆成多页（第(1/3)页）—— 必须把后续页也抓回来拼上，
        # 否则「下载成功」的书每章只有前 1/3，而且用户完全看不出来。
        mark = page_mark(text)
        if not mark:
            return tidy_content(strip_page_mark(text), chapter.title)
        cur, total = mark
        if total <= 1 or total > 30:
            return tidy_content(strip_page_mark(text), chapter.title)

        parts = [strip_page_mark(text)]
        for n in range(cur + 1, total + 1):
            u = page_url(chapter.url, n)
            if not u:
                break
            try:
                more = self._fetch_page(u)
            except Exception:  # noqa: BLE001
                break
            body = strip_page_mark(more)
            # 页面不存在时很多站会把上一页原样返回，靠「内容没变」判断到底
            if not body.strip() or body.strip() == parts[-1].strip():
                break
            parts.append(body)
        return tidy_content("\n\n".join(p for p in parts if p.strip()), chapter.title)

    def _fetch_page(self, url: str) -> str:
        try:
            html = fetch_text(url, encoding=self.encoding)
            raw = self._extract(
                self.cfg.get("content_re", ""),
                html,
                multi=self.cfg.get("content_multi", False),
                filt=self.cfg.get("content_filter"),
            )
            return clean_text(raw) if raw else ""
        except Exception:  # noqa: BLE001
            return ""

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
