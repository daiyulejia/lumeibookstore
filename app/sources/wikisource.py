"""维基文库来源（zh.wikisource.org）。

- 官方 MediaWiki API，结构稳定
- 内容为公版书籍，合法可靠
- 已做批量抓取 + 限流退避，避免被封
"""
from __future__ import annotations

import re
import time
import logging
import threading
from urllib.parse import urlencode

from ..errors import SourceBlocked
from ..models import Book, BookResult, Chapter
from ..utils import get_client, clean_text, clean_wikitext, cached
from .base import Source, note_for_exception

logger = logging.getLogger("novel.wikisource")

API = "https://zh.wikisource.org/w/api.php"


class WikisourceSource(Source):
    name = "wikisource"
    display = "维基文库"
    # ⚠ 曾经是 1（最高优先级），但这是**明显错配**：
    #   维基文库收录的是公版古籍（教女遺規 / 女範捷錄 / 鄭氏世家…），
    #   对当代网文**零覆盖**；搜「赵氏嫡女」时它按"女"字匹配出 20 条古籍，
    #   全被 rank() 去噪清掉，纯属无效工作量。
    #   而它在服务器上一次要 **184 秒** 才返回（本地 1.1s），priority=1 等于
    #   在每一轮搜索里都被这 184s 拖着。降到 50（排在所有网文源之后、
    #   自有来源之前）—— 公版书场景仍能搜到，但不再抢占最快路径。
    priority = 50
    homepage = "https://zh.wikisource.org/"
    engine = "mediawiki"

    BATCH = 20          # 每次批量抓取的页面数
    SLEEP = 0.2         # 请求间隔
    CONCURRENCY = 3     # 并发线程数（过高会触发限流）

    # ---------- 搜索 ----------
    def search(self, keyword: str) -> list[BookResult]:
        """两步搜索。

        维基文库默认是**全文检索**，搜「微微一笑很倾城」会搜出一堆
        「北京互联网法院（2021）京0491民初9699号民事判决书」——因为判决书
        正文里提到了这本书名。所以先用 intitle: 限定「标题必须包含关键词」，
        没有结果再退回全文检索（交给上层相关性过滤去重排）。
        """
        hits = self._search_raw(f"intitle:{keyword}")
        if not hits:
            hits = self._search_raw(keyword)

        out: list[BookResult] = []
        for h in hits:
            title = h.get("title", "")
            snippet = re.sub(r"<[^>]+>", "", h.get("snippet", ""))
            out.append(
                BookResult(
                    title=title,
                    author="",
                    source=self.name,
                    url=title,
                    intro=clean_text(snippet),
                )
            )
        return out

    def _search_raw(self, query: str) -> list[dict]:
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": 20,
            "srnamespace": 0,
            "format": "json",
            "utf8": 1,
        }
        try:
            data = self._api(params)
        except Exception as e:  # noqa: BLE001
            logger.info("搜索失败: %s", e)
            return []
        return data.get("query", {}).get("search", [])

    # ---------- 可用性探测（单页来源，需覆写） ----------
    def probe(self, result: BookResult) -> dict:
        """维基文库的探测优化：多数书籍有子页面（章节），
        只要 allpages 查到足量子页就能判定可用，**省掉一次正文请求**。
        """
        import time as _t

        t0 = _t.time()

        def el() -> int:
            return int((_t.time() - t0) * 1000)

        page = result.url or result.title
        try:
            subs = self._subpages(page)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "chapters": 0,
                    "note": note_for_exception(e), "ms": el()}

        if len(subs) >= 5:
            return {"ok": True, "chapters": 1 + len(subs), "note": "", "ms": el()}

        # 子页面很少 → 可能是单页作品，取一次正文确认不是空页
        try:
            text = self._batch_texts([page]).get(page, "")
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "chapters": 0,
                    "note": note_for_exception(e), "ms": el()}
        if len(text.strip()) < 200:
            return {"ok": False, "chapters": 0, "note": "页面内容过短", "ms": el()}
        return {"ok": True, "chapters": 1 + len(subs), "note": "", "ms": el()}

    # ---------- 单章（预览用） ----------
    def fetch_chapter(self, chapter) -> str:
        try:
            return self._batch_texts([chapter.url]).get(chapter.url, "")
        except Exception:  # noqa: BLE001
            return ""

    # ---------- 目录 ----------
    def get_chapters(self, result: BookResult) -> list[Chapter]:
        return [Chapter(index=1, title=result.title, url=result.title)]

    # ---------- 抓取全书 ----------
    def fetch(self, result: BookResult, progress=None, limit=None, stop=None) -> Book:
        page = result.url or result.title
        book = Book(title=page, source=self.name, url=page, intro=result.intro)

        # 子页面（章节），加上主页面本身
        subpages = self._subpages(page)
        titles = [page] + subpages
        if limit:
            titles = titles[: limit + 1]

        total = len(titles)
        texts = self._batch_texts(titles, progress=progress, stop=stop)

        # 建立归一化映射（下划线/空格差异）
        norm = {self._norm(k): v for k, v in texts.items()}

        for t in titles:
            content = texts.get(t) or norm.get(self._norm(t), "")
            if not content.strip():
                continue
            # 主页面标题用书名，其余去掉前缀
            title = t.split("/", 1)[-1] if "/" in t else t
            book.chapters.append(
                Chapter(index=len(book.chapters) + 1, title=title, content=content, url=t)
            )

        if not book.chapters:
            raise SourceBlocked("维基文库没有返回任何正文（可能被限流或页面不存在）")
        return book

    @staticmethod
    def _norm(s: str) -> str:
        return s.replace("_", " ").strip()

    # ---------- 内部实现 ----------
    def _api(self, params: dict, retries: int = 5) -> dict:
        url = f"{API}?{urlencode(params)}"
        last: Exception | None = None
        for i in range(retries):
            try:
                r = get_client().get(url)
                ct = r.headers.get("content-type", "")
                if "json" in ct:
                    data = r.json()
                    # 识别限流/错误响应
                    if "error" in data:
                        code = data["error"].get("code", "")
                        last = RuntimeError(f"API error: {code}")
                        time.sleep(1.5 * (i + 1))
                        continue
                    return data
                last = RuntimeError(f"非 JSON 响应({r.status_code}): {r.text[:80]}")
            except Exception as e:  # noqa: BLE001
                last = e
            time.sleep(1.0 * (i + 1) + 0.5 * i * i)  # 递增退避
        raise RuntimeError(f"API 请求失败: {last}")

    def _subpages(self, title: str) -> list[str]:
        return cached(f"ws:sub:{title}", 600, lambda: self._subpages_raw(title))

    def _subpages_raw(self, title: str) -> list[str]:
        params = {
            "action": "query",
            "list": "allpages",
            "apprefix": f"{title}/",
            "aplimit": 500,
            "format": "json",
            "utf8": 1,
        }
        try:
            data = self._api(params)
        except Exception:  # noqa: BLE001
            return []
        pages = data.get("query", {}).get("allpages", [])
        return [p["title"] for p in pages]

    def _batch_texts(self, titles: list[str], progress=None, stop=None) -> dict[str, str]:
        """批量获取页面维基源码。

        使用 prop=revisions + rvslots=main（支持一次取多页，比 extracts 快得多），
        再将 wikitext 清洗为纯文本。
        """
        out: dict[str, str] = {}
        total = len(titles)
        done = 0
        # MediaWiki 单次 titles 上限 50
        chunk_size = 50
        for i in range(0, total, chunk_size):
            if stop and stop():
                break
            chunk = titles[i : i + chunk_size]
            params = {
                "action": "query",
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "titles": "|".join(chunk),
                "format": "json",
                "utf8": 1,
                "redirects": 1,
            }
            try:
                data = self._api(params)
                pages = data.get("query", {}).get("pages", {})
                for _, p in pages.items():
                    title = p.get("title", "")
                    try:
                        wt = p["revisions"][0]["slots"]["main"]["*"]
                    except (KeyError, IndexError, TypeError):
                        wt = ""
                    out[title] = clean_wikitext(wt)
            except Exception as e:  # noqa: BLE001
                logger.debug("批量抓取失败: %s", e)
            done += len(chunk)
            if progress:
                progress(min(done, total), total, f"抓取 {min(done, total)}/{total}")
            time.sleep(self.SLEEP)
        return out

    def _page_text(self, title: str) -> str:
        got = self._batch_texts([title])
        return got.get(title, "")
