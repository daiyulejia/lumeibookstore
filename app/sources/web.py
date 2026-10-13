"""联网发现来源：把「搜索引擎找到的书页」当成一个正式来源。

它和别的来源不一样的地方
------------------------
普通来源是「有个站，去搜它」；这个是「**先搜，才有站**」——
`search()` 里现场去搜索引擎找书页、核实、再记进来源库。

两条取数路径
------------
1. **来源库命中**（快）—— 之前搜过这本书，库里记着，直接返回，不联网搜索
2. **联网发现**（慢）—— 库里没有，去搜索引擎找 + 并发核实候选站

抓到之后，目录/正文的解析全交给 `app/webfetch.py` 的通用启发式，
不写死任何一个站的规则。
"""
from __future__ import annotations

import time

from .. import discovery, registry, webfetch
from ..models import Book, BookResult, Chapter
from ..utils import fetch_text, host_of
from .base import Source, check_content_quality, note_for_exception, tidy_content


class DiscoveredSource(Source):
    """联网发现的书籍来源。"""

    name = "web"
    display = "联网发现"
    kind = "discovered"
    engine = "search+fetch"
    priority = 90
    homepage = ""
    has_search = True
    lazy = True          # 不参与常规搜索扇出，只在本地搜不到时被引擎显式唤起
    PROBE_BASE = 6
    FAIL_FAST = 4

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------
    def search(self, keyword: str) -> list[BookResult]:
        # 1) 先看来源库 —— 搜过一次的书不用再上网搜
        hit = discovery.from_registry(keyword)
        if hit:
            if self.log:
                try:
                    self.log("来源库命中", f"{len(hit)} 本（联网发现攒下来的）", True)
                except Exception:  # noqa: BLE001
                    pass
            return hit
        # 2) 库里没有 → 出去找
        return discovery.discover(keyword, log=self.log)

    # ------------------------------------------------------------------
    # 目录
    # ------------------------------------------------------------------
    def get_chapters(self, result: BookResult) -> list[Chapter]:
        data = discovery.page_of(result.url)
        if data.get("kind") != "toc":
            raise RuntimeError("这个地址不是目录页（没解析到章节列表）")

        if data.get("title") and not result.title:
            result.title = discovery.clean_book_title(data["title"])
        if data.get("author") and not result.author:
            result.author = data["author"]
        if data.get("intro") and not result.intro:
            result.intro = data["intro"]

        toc = data.get("toc") or []
        return [Chapter(index=i, title=c["title"], url=c["url"])
                for i, c in enumerate(toc, 1)]

    # ------------------------------------------------------------------
    # 单章
    # ------------------------------------------------------------------
    def fetch_chapter(self, chapter: Chapter) -> str:
        """抓一章正文。

        这里**不走** `analyze()` 的页面类型判定 —— 正文页上常常也挂着
        「推荐阅读」之类的同模板链接，够多的话会被误判成目录页。
        直接按正文容器抽，更稳。
        """
        url = chapter.url
        host = host_of(url)
        try:
            html = fetch_text(url)
        except Exception:  # noqa: BLE001
            registry.note_site(host, ok=False, why=registry.FAIL_DOWN)
            raise

        site = registry.known_site(host)
        body = webfetch.clean_body(
            webfetch.extract_content(html, hint=site.get("content_hint") or ""))

        if len(body) < 60:
            # 学到的容器名过期了（站点改版）→ 放低门槛再试一次
            body = webfetch.clean_body(webfetch.extract_content(html, min_chars=0))

        body = tidy_content(body, chapter.title)
        ok, why = check_content_quality(body)
        if not ok:
            # 抓到的是「阅读器骨架 / 登录提示 / 章节不存在」之类 —— 宁可当失败。
            # 不拦的话，付费站（正文是 JS 渲染的）会交出满页 UI 文字，
            # 而用户看着「下载成功」却读不到一个字。
            # why=gated：页面**打开了**，是要登录/JS，不是站挂了。
            registry.note_site(host, ok=False, why=registry.FAIL_GATED)
            return ""

        # 学一手：这次命中的是什么容器，下次直接用
        hint = webfetch.extract_content_hint(html)
        registry.note_site(host, ok=True, **({"content_hint": hint} if hint else {}))
        return body

    # ------------------------------------------------------------------
    # 整本
    # ------------------------------------------------------------------
    def fetch(self, result: BookResult, progress=None, limit=None, stop=None) -> Book:
        chapters = self.get_chapters(result)
        if limit:
            chapters = chapters[:limit]
        book = Book(
            title=result.title, author=result.author, source=self.name,
            url=result.url, intro=result.intro,
        )
        book.chapters = self.fetch_all(chapters, self.fetch_chapter, progress, stop)
        return book

    # ------------------------------------------------------------------
    # 抽样校验
    # ------------------------------------------------------------------
    def sample(self, result: BookResult, chapters: list | None = None) -> dict:
        """抽一章正文，并且**自己判定**，不交给基类的默认实现。

        为什么必须覆写：基类的默认 `sample()` 在「单章接口返回空」时会
        返回 `ok=None` —— 那是给单页来源（维基文库 / Gutenberg）留的余地，
        它们本来就没有单章接口，不该被误判。

        但联网发现**是有**单章接口的，返回空只意味着一件事：**抓不到正文**。
        如果照抄基类逻辑，塔读这类正版站（目录页静态可读、正文要登录或
        JS 渲染）会被标成「可读」，用户点进去一个字都看不到 ——
        这正是「别显示可以下载最后假的」要拦住的情形。

        返回里 ok 只有 True / False 两种，没有 None。
        """
        t0 = time.time()
        if chapters is None:
            try:
                chapters = self.get_chapters(result)
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "chars": 0,
                        "note": note_for_exception(e), "ms": _ms(t0)}
        if not chapters:
            return {"ok": False, "chars": 0, "note": "没有解析到目录", "ms": _ms(t0)}

        # 第 1 章常常是「作品相关 / 版权声明」，第 2 章更像正文
        idx = 1 if len(chapters) > 2 else 0
        try:
            text = self.fetch_chapter(chapters[idx]) or ""
        except Exception as e:  # noqa: BLE001
            registry.note_site(host_of(result.url), ok=False, why=registry.FAIL_DOWN)
            return {"ok": False, "chars": 0,
                    "note": note_for_exception(e), "ms": _ms(t0)}

        if not text.strip():
            registry.note_site(host_of(result.url), ok=False, why=registry.FAIL_GATED)
            return {"ok": False, "chars": 0,
                    "note": "目录能打开，但正文抓不到（多半是付费站或 JS 渲染）",
                    "ms": _ms(t0)}

        ok, note = check_content_quality(text)
        if not ok:
            registry.note_site(host_of(result.url), ok=False, why=registry.FAIL_GATED)
        else:
            registry.note_book(
                result.url, title=result.title, author=result.author,
                host=host_of(result.url), intro=result.intro, ok=True)
        return {"ok": ok, "chars": len(text.strip()), "note": note, "ms": _ms(t0)}


def _ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)


__all__ = ["DiscoveredSource"]
