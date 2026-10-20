"""来源库站内搜索：把「学到的站」变成**常规来源**，参与每轮搜索。

它和 `sources/web.py` 的分工
-----------------------------
两个都建立在来源库（`cache/registry.json`）上，但姿势相反：

    · `web.DiscoveredSource`  —— **先搜，才有站**。每次都得出去走一趟
      搜索引擎，慢（一轮 10 秒起），而且是 `lazy`，只在本地全灭时才唤起。
    · `RegistrySource`（本文件）—— **先有站，直接搜**。库里的站已经学过
      站内搜索模板，拿关键词拼个 URL 就能问它，快（每个站 1~2 秒），
      参与常规扇出。

于是搜书变成两段路：

    第一本《XX》  →  本地 7 个预置源都没有 → 联网发现 → 找到 A/B/C 站
                     → **顺手学下 A/B/C 的搜索模板** → 存进 L 源
    第二本《YY》  →  本地预置源没有 → **RegistrySource 直接拿《YY》去问 A/B/C**
                     （不用再走搜索引擎！）
                     → 命中就秒出；没命中才走联网发现兜底

这就是用户要的「我们搜的越多，能搜的源就越多，下一次先在我们自己的源里找」。

为什么阈值调高（它比预置源更慢一点）
------------------------------------
预置源是写死适配器的（一次请求就能拿结果列表）；RegistrySource 是
「拼 URL → 抓 HTML → 通用启发式抽链接」，比预置源贵一些。
但它比联网发现**便宜一个数量级**，所以排位放在预置源之后、
`web` 之前（priority 60）。

并发与预算
----------
库里可能有几十个站，全打一遍就是几十个请求。所以：
  · 只能搜**健康且学过模板**的（`registry.searchable_sites()`）
  · 单次搜索里限制并发数（`SEARCH_WORKERS`）和总预算（`SEARCH_BUDGET`）
  · 同域请求本来就被 `utils` 的限速器串行化，不会打爆任何一个站
"""
from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from urllib.parse import urljoin, urlparse

from .. import registry, sitelearn, webfetch
from ..models import Book, BookResult, Chapter
from ..utils import fast_mode, fetch_text, host_of, normalize_title
from .base import Source, tidy_content

logger = logging.getLogger("novel.registry_source")

# 单次搜索最多同时问几个站。
#
# ⚠ 这个数字原来写 6，和「总预算 7 秒」是**结构性矛盾**（2026-10-21 线上实测）：
#   14 个可搜站 / 6 并发 = 要跑 3 轮；而单站超时给的是 8 秒 ——
#   单站超时比总预算还长，等于「只要有一个站慢到 8 秒，整批必然超预算」。
#   线上日志 15 次 `自有来源搜索超预算，先用已有结果`，全部是这句，
#   而那 15 次一条结果都没拿到（命中日志只在有结果时才打）。
#   后果直接对应「热门书也搜不到」：真能搜的站被排在慢站后面，永远轮不到。
#   所以并发要能**一次性覆盖全部可搜站**（上限 24，防将来库变很大时打爆）。
SEARCH_WORKERS = 24
# 单次搜索的总预算（秒）。超了就先把已经拿到的给你 ——
# 它排位在预置源之后，用户很可能在第 1 秒就看到别的站的结果了，
# 这里不该让人干等。
SEARCH_BUDGET = 7.0
# 单站超时（秒）。**必须明显小于总预算** —— 否则一个慢站就能把整批拖到超预算，
# 前面那些已经答完的站的结果也会跟着"看起来没拿到"。3.5s 对一个搜索页 GET 足够。
SEARCH_SITE_TIMEOUT = 3.5
# 一个站最多回多少条候选（防止「搜一个常见词，某个站把整站都吐回来」）
PER_SITE = 6
# 总候选上限
TOTAL_LIMIT = 40

# 候选条目的标题看起来「太不干净」就丢：纯导航、太短、太长
_BAD_TITLE = re.compile(
    r"^(首页|登录|注册|书架|排行|全部小说|小说大全|搜索|下一页|上一页|"
    r"章节列表|目录|作品相关|查看更多|更多|home|login|register)$",
    re.I,
)


class RegistrySource(Source):
    """来源库里的「可搜站」—— 参与常规扇出的自有源。"""

    name = "registry"
    display = "自有来源"
    kind = "discovered"
    engine = "learned-search"
    # 60：排在所有预置源之后、联网发现（90）之前。
    priority = 60
    homepage = ""
    has_search = True
    # 不 lazy —— 它要参与常规扇出，这是这次升级的**核心目的**。
    lazy = False
    PROBE_BASE = 4
    FAIL_FAST = 5

    # 单个站点的「实测平均耗时」，用来决定单次能给几个站并发。
    _speed_ms: float = 0.0

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------
    def search(self, keyword: str) -> list[BookResult]:
        keyword = (keyword or "").strip()
        if not keyword:
            return []

        sites = registry.searchable_sites()
        if not sites:
            return []

        # 按「这个站历史上成功过几次」排，老大难的站放后面 ——
        # 预算不够时可以少打几个。
        ordered = sorted(
            sites.items(),
            key=lambda kv: (-int(kv[1].get("ok", 0)), kv[0]),
        )

        results: list[BookResult] = []
        seen: set[tuple[str, str]] = set()
        lock = threading.Lock()

        if self.log:
            try:
                self.log("自有来源", f"拿关键词去 {len(ordered)} 个已学会的站里搜", True)
            except Exception:  # noqa: BLE001
                pass

        t0 = time.time()
        pool = ThreadPoolExecutor(max_workers=min(SEARCH_WORKERS, len(ordered)))
        futs = {pool.submit(self._search_one, host, meta, keyword): host
                for host, meta in ordered}
        done = 0        # 已经"答完"的站数（不是命中条数）——
        # ⚠ 超预算那条日志原先只写"先用已有结果"，完全看不出卡在哪：
        #   是 3 个站答完就超了（预算太小），还是 13 个答完只剩 1 个慢（正常）。
        #   线上 15 次这条日志就是这么白写的，排障时一句信息都没有。
        fails = 0       # 抓取就失败了的站数（网络层），用来判"整批是不是全挂了"
        try:
            for fut in as_completed(futs, timeout=SEARCH_BUDGET):
                done += 1
                try:
                    got = fut.result()
                except Exception as e:  # noqa: BLE001
                    fails += 1
                    logger.debug("自有来源单站搜索异常: %s", e)
                    got = []
                for r in got or []:
                    key = (normalize_title(r.title), r.url)
                    with lock:
                        if key in seen:
                            continue
                        seen.add(key)
                        results.append(r)
                        if len(results) >= TOTAL_LIMIT:
                            break
                if len(results) >= TOTAL_LIMIT:
                    break
        except Exception:  # noqa: BLE001
            logger.info("自有来源搜索超预算（%d/%d 个站已答完、%.1fs），先用已有结果 %d 条",
                        done, len(ordered), time.time() - t0, len(results))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        if results and self.log:
            try:
                self.log("自有来源命中", f"{len(results)} 条（{time.time() - t0:.1f}s）", True)
            except Exception:  # noqa: BLE001
                pass
        # 「整批全挂」才上抛给熔断器：一个站抓不到只是它自己的事，
        # 但 8 个站一个都没连上，就是这条链路（DNS/出口/被封）出了问题 ——
        # 得让引擎知道，否则它会以为"自有来源只是没这本书"，永远不熔断。
        if not results and fails >= len(ordered):
            self.note_error(f"自有来源 {fails} 个站全部抓取失败")
        return results

    # ------------------------------------------------------------------
    def _search_one(self, host: str, meta: dict, keyword: str) -> list[BookResult]:
        """拿一个站搜一次，抽列表页里的书链接。"""
        tpl = (meta.get("search_tpl") or "").strip()
        if not tpl:
            return []
        enc = (meta.get("search_enc") or "utf-8").strip()
        scheme = (meta.get("search_scheme") or "https").strip()
        method = (meta.get("search_method") or "get").strip().lower()
        body_tpl = meta.get("search_body") or None

        t_start = time.time()
        try:
            with fast_mode(retries=0, timeout=SEARCH_SITE_TIMEOUT):
                if method == "post":
                    # POST 搜索：URL 不带关键词，关键词在请求体里
                    url = sitelearn.build_url(tpl, host, "", enc=enc, scheme=scheme)
                    data = {k: str(v).replace("{kw}", keyword)
                            for k, v in (body_tpl or {"s": "{kw}"}).items()}
                    html, final = fetch_text(url, with_url=True, data=data)
                else:
                    url = sitelearn.build_url(tpl, host, keyword, enc=enc, scheme=scheme)
                    html, final = fetch_text(url, with_url=True)
        except Exception as e:  # noqa: BLE001
            logger.debug("自有来源抓取失败 %s: %s", host, e)
            registry.note_site(host, ok=False, why=registry.FAIL_DOWN)
            # 留口条给熔断器 + 让 search() 数得出"有几个站失败"。
            # 只在**整批**都失败时才上抛成"这个源挂了"（见 search() 末尾）。
            self.note_error(e)
            raise
        finally:
            self._note_speed((time.time() - t_start) * 1000)

        if not html:
            # 请求成功但没拿到 HTML —— 站能开、只是这次没内容，
            # 归 empty（不是 down，别把站判死）
            registry.note_site(host, ok=False, why=registry.FAIL_EMPTY)
            return []

        base = final or url
        # 抽「书页链接」：列表页里书名链接通常都指向 /book/… /info_… 这种详情页。
        # 用通用启发式 —— 拿所有 <a>，按 URL 模板分组，取条目最多那组。
        items = _extract_book_links(html, base)
        out: list[BookResult] = []
        for title, href in items[:PER_SITE]:
            if not title or _BAD_TITLE.match(title):
                continue
            if len(title) < 2 or len(title) > 60:
                continue
            out.append(BookResult(
                title=title,
                # 顺手把列表页上的作者带上 —— 作者搜索全靠它，见 _author_near
                author=_author_near(html, title, base),
                source=self.name,
                url=href,
                source_display=self.display,
            ))

        if out:
            registry.note_site(host, ok=True)
        else:
            # 搜到了结果页、但一条书链接都没有 —— 多半是这个模板「能开但搜不出」
            # （站改版了）。记一笔失败，但不删模板（模板本身没错，
            # 是抽链接的启发式需要跟着变）。
            registry.note_site(host, ok=False, why=registry.FAIL_EMPTY)
        return out

    @classmethod
    def _note_speed(cls, ms: float) -> None:
        ms = max(0.0, float(ms))
        cur = cls._speed_ms
        cls._speed_ms = ms if cur <= 0 else cur * 0.6 + ms * 0.4

    # ------------------------------------------------------------------
    # 目录（复用通用启发式，和联网发现同一条路）
    # ------------------------------------------------------------------
    def get_chapters(self, result: BookResult) -> list[Chapter]:
        from .. import discovery
        data = discovery.page_of(result.url)
        if data.get("kind") != "toc":
            raise RuntimeError("这个地址不是目录页（没解析到章节列表）")
        if data.get("title") and not result.title:
            result.title = discovery.clean_book_title(data["title"])
        if data.get("author") and not result.author:
            result.author = data["author"]
        if data.get("intro") and not result.intro:
            result.intro = data["intro"]
        # 顺手把封面带回来 —— 探测本来就要打开这页，白拿的。
        if data.get("cover") and not result.cover:
            result.cover = data["cover"]
        toc = data.get("toc") or []
        return [Chapter(index=i, title=c["title"], url=c["url"])
                for i, c in enumerate(toc, 1)]

    # ------------------------------------------------------------------
    def fetch_chapter(self, chapter: Chapter) -> str:
        """抓一章正文。和联网发现同款 —— 按学到的容器名抽，学不到就启发式。"""
        url = chapter.url
        host = host_of(url)
        try:
            html = fetch_text(url)
        except Exception:  # noqa: BLE001
            # 取正文失败 = 网络层，算站的账
            registry.note_site(host, ok=False, why=registry.FAIL_DOWN)
            raise

        site = registry.known_site(host)
        body = webfetch.clean_body(
            webfetch.extract_content(html, hint=site.get("content_hint") or ""))
        if len(body) < 60:
            body = webfetch.clean_body(webfetch.extract_content(html, min_chars=0))
        body = tidy_content(body, chapter.title)

        from .base import check_content_quality
        ok, _why = check_content_quality(body)
        if not ok:
            # 拿到了页面但正文质量不行（多半是要登录/JS 渲染）→ gated，非站挂
            registry.note_site(host, ok=False, why=registry.FAIL_GATED)
            return ""
        hint = webfetch.extract_content_hint(html)
        registry.note_site(host, ok=True, **({"content_hint": hint} if hint else {}))
        return body

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
    def sample(self, result: BookResult, chapters: list | None = None) -> dict:
        """抽一章正文自己判定，语义同联网发现（不给 ok=None 的余地）。"""
        from .base import check_content_quality, note_for_exception
        t0 = time.time()
        if chapters is None:
            try:
                chapters = self.get_chapters(result)
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "chars": 0,
                        "note": note_for_exception(e), "ms": _ms(t0)}
        if not chapters:
            return {"ok": False, "chars": 0, "note": "没有解析到目录", "ms": _ms(t0)}
        idx = 1 if len(chapters) > 2 else 0
        try:
            text = self.fetch_chapter(chapters[idx]) or ""
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "chars": 0,
                    "note": note_for_exception(e), "ms": _ms(t0)}
        if not text.strip():
            return {"ok": False, "chars": 0,
                    "note": "目录能打开，但正文抓不到（多半是付费站或 JS 渲染）",
                    "ms": _ms(t0)}
        ok, note = check_content_quality(text)
        return {"ok": ok, "chars": len(text.strip()), "note": note, "ms": _ms(t0)}


def _ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)


# ---------------------------------------------------------------------------
# 从搜索列表页里抽书链接
# ---------------------------------------------------------------------------
_A_RE = re.compile(r"""<a\s[^>]*?href\s*=\s*["']([^"']+)["'][^>]*>([\s\S]{0,90}?)</a>""", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_HIDDEN_RE = re.compile(r"<(script|style|noscript)\b[^>]*>[\s\S]*?</\1\s*>", re.I)
# 详情页 URL 的常见形态。
#
# ⚠ 这里匹配的是**模板化之后**的路径（数字已被换成 `#`），所以用 `[#\d]`
#   而不是 `\d` —— 踩过这个坑：拿 `\d{3,}` 去匹配 `/html/#/#/` 永远不中，
#   结果分类导航组反而排到了书页组前面。
#
# `/html/#/#/`（杰奇 CMS 系）单独列出来 —— 实测 384g / 老笔趣阁都是它，
# 而它**不以 book/info 开头**，靠 `/book/` 那套是认不出来的。
#
# ⚠ 两条纪律（都踩过坑）：
#   ① **不能靠尾部锚定来排章节页** —— 一批站的书目录页本身就是 `/book/#/`
#      或 `/xs/#/`（带斜杠结尾），一锚就把它们也误杀了。
#   ② 正确的判据是「**路径最后一段**是不是 `数字.html`」——那才是章节正文页。
#      用 _CHAPTER_TAIL 单独判，比把所有模式都加锚干净得多。
# ⚠ 这个正则**只吃模板化路径**（数字已换成 `#`，见 _path_tpl_of）。
#   所以每一处"数字段"都必须写成 `[#\d]` —— 写 `\d` 会永远匹配不上，
#   这就是本文件历史上反复踩的坑：
#     · 拿 `\d{3,}` 去匹配 `/html/#/#/`      → 永不命中，导航组排到书页组前面
#     · 拿 `[^/]*[#\d]{3,}` 去匹配 `/book/#/` → 也永不命中
#       （`[^/]*` 先吞掉 `#`，后面就再没有字符可给 `[#\d]{3,}` 了），
#       结果 `/book/123456/` 这种最常见的书页被判成"不像书"
#
# 三条形态：
#   · `/(book|info|xs|…)/…` 关键字系 —— 后面跟一段长度≥3 的编号
#   · `/html/#/#/`          杰奇 CMS 系（384g / 老笔趣阁）
#   · `/#/#/`               无关键字的纯数字两段/三段
#
# ⚠⚠ 量词只能用 `+`，**不能用 `{2,}`** —— 模板化会把**整段数字**压成一个
#   `#`，所以 `/#/#/` 里每一段都只有 1 个字符，`{2,}` / `{3,}` / `{4,}`
#   全部落空。这是本文件里最阴的一个坑：正则"看起来没问题"，
#   但在模板化输入上永远不命中，而且**不报错**（判成 False 就走兜底组去了）。
_BOOK_PATH = re.compile(
    r"/(?:book|info|b|xs|xsw|novel|read|xiao?shuo|article)/[^/]*[#\d]+/?"
    r"|/html/[#\d]+/[#\d]+/?"
    r"|/[#\d]+/[#\d]+/?",
    re.I)

# 单段形态（`/123456/`）**单独用原始路径判** —— 不能并进 _BOOK_PATH。
# 因为模板化把整段数字压成一个 `#`，`/#/` 跟 `/page/2/`（也含数字）长得
# 一模一样，放宽就会把分页、列表页、用户页全当成书。
# 判据只能回到原始路径上数位数：书 ID 通常是 4 位以上，页码不是。
_SINGLE_SEG_BOOK = re.compile(r"^/[A-Za-z0-9_\-]*?(\d{4,})/?$")

# 章节正文页的形状：路径最后一段是「数字.html」。
#   /html/102/102114/79.html  → 是章节
#   /book/123456/            → 不是（书目录页）
# 为什么必须单独判：`/html/102/102114/79.html` 会被 _BOOK_PATH 第 2 条
# **部分命中**（`/html/102/102114/` 那段），于是章节页混进搜索结果。
# 实测：搜「余华」返回的那条「附：英文版…评论摘要」，URL 正是
# `.../102114/79.html`，探测时报「这个地址不是目录页」——它压根是一章正文。
_CHAPTER_TAIL = re.compile(r"/[#\d]+\.html?$", re.I)


def looks_like_book_url(u: str) -> bool:
    """这个 URL 的形状像「书页」吗？（不是章节正文页）

    判定 = 「像书页路径」**且**「不是章节正文页」。

    ⚠ 两个正则吃的**不是同一种输入**（踩过）：
      · `_BOOK_PATH`   历史上就是拿**模板化路径**判的（`/#/#/` 这种），
        保持原样 —— 换成原始 URL 会让一批本来就靠模板归组进来的书页
        （杰奇系的 `/0/143/`）反而判不出来。
      · `_CHAPTER_TAIL` 判「结尾一段是不是 `数字.html`」—— 那是章节正文页，
        必须排除。不排除的后果：`/html/102/102114/79.html` 会被
        `_BOOK_PATH` **部分命中**（`/html/102/102114/` 那段），
        于是章节页混进搜索结果。实测：搜「余华」返回的
        「附：英文版…评论摘要」URL 正是 `.../102114/79.html`，
        探测时报「这个地址不是目录页」——它压根是一章正文。
    """
    if _CHAPTER_TAIL.search(_path_tpl_of(u)):
        return False
    if _BOOK_PATH.search(_path_tpl_of(u)):
        return True
    # 单段形态回原始路径判（见 _SINGLE_SEG_BOOK 的注释）
    try:
        from urllib.parse import urlparse
        return bool(_SINGLE_SEG_BOOK.match(urlparse(u).path or ""))
    except Exception:  # noqa: BLE001
        return False
# URL 模板化：数字换成 #
_NUM_RE = re.compile(r"\d+")


def _tpl_of(u: str) -> str:
    """把一个 URL 归一化成模板（数字 → #），用来按形状分组。"""
    p = urlparse(u)
    return f"{p.netloc}{_NUM_RE.sub('#', p.path)}#{'#' if p.query else ''}"


def _path_tpl_of(u: str) -> str:
    """只要路径部分的模板（不含 netloc、不含查询串）。

    `_BOOK_PATH` 之类的正则要拿它来判 —— 直接拿 `_tpl_of` 的结果会带
    查询串的尾标记（`.../489427/#`），`$` 锚点就匹配不上了。
    """
    return _NUM_RE.sub("#", urlparse(u).path or "")


def _text_of(s: str) -> str:
    import html as _html
    return _html.unescape(_TAG_RE.sub("", s or "")).strip()


# ---------------------------------------------------------------------------
# 从列表行里抽作者
# ---------------------------------------------------------------------------
# ⚠ 为什么值得专门做：自有来源（registry）的搜索结果**一直不带作者** ——
#   `BookResult` 的 author 字段只有等到 probe 打开详情页才回填（见
#   `get_chapters` 里那句 `result.author = data["author"]`）。于是
#   作者搜索在这条路径上完全失效：搜「顾漫」时，站点**明明返回了**
#   骄阳似我 / 微微一笑很倾城 / 杉杉来吃，但每条 author 都是空的，
#   relevance 里的作者匹配没有东西可比，全部被当噪音丢掉 → 0 条。
#   （实测：服务器上 7 个源只有 registry 搜得到顾漫的书，它不带作者，
#     作者搜索就等于不存在。）
#
# 列表页上作者信息**就在书名旁边**，只是以前没去取。各站写法不一，
# 但模式很集中 —— 「作者：xxx」/「xxx 著」/ 紧跟在标题后的一个短名字。
_AUTHOR_LABEL_RE = re.compile(
    r"(?:作者|作\s*者|著者|writer|author)\s*[:：]?\s*"
    r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_.·\-]{0,15})", re.I)
# 「书名 xxx 著」这种把作者放在书名后的写法
_AUTHOR_SUFFIX_RE = re.compile(
    r"([\u4e00-\u9fff]{2,12})\s*(?:著|作品|文集)\b")

# 表格列表页（新笔趣阁系）：一行 <tr> 里，作者是个**没有任何标签的 <td>**
#    <tr>
#      <td class="odd"><a href="/html/406/406301/">骄阳似我</a></td>
#      <td class="even"><a ...>第55章 作者番外语</a></td>   ← 最新章（干扰项）
#      <td class="odd">顾漫</td>                              ← 作者
#      <td class="even">745270K</td>  ← 字数
#      <td class="odd">2024-09-10</td> ← 日期
#      <td class="even">连载中</td>    ← 状态
#    </tr>
# ⚠ 第二格里写着「第55章 **作者**番外语」—— 用「作者：」去搜会先命中它，
#   抽出「番外语」这种垃圾（实测踩到过）。所以表格形态要**按列位取**，
#   不能靠标签。下面这个按 <tr> 切行，取「像人名」的那一格。
_TR_ROW_RE = re.compile(r"<tr\b[^>]*>([\s\S]{0,900}?)</tr>", re.I)
_TD_CELL_RE = re.compile(r"<td\b[^>]*>([\s\S]{0,200}?)</td>", re.I)
# 「看起来像人名」：2~12 个中文/少数民族名·点，且不含数字、不含常见字段词
_PERSON_RE = re.compile(r"^[\u4e00-\u9fff]{2,12}(?:[·\.][\u4e00-\u9fff]{1,8})*$")
_CELL_NOISE_RE = re.compile(
    r"\d|章|分类|状态|字数|更新|点击|排行|首页|连载|完结|作者|更多|全部|"
    r"最新章节|目录|详情|阅读|书友|推荐|收藏|投票")


def _author_near(html: str, title: str, base_url: str) -> str:
    """在这条书链接**所在的那一行**里找作者名。

    两种页面形态都认：
      ① 表格行（新笔趣阁系）：作者是一个**无标签的 <td>** —— 按列位取，
         且必须跳过「最新章」那一格（它常写成「第55章 作者番外语」，
         拿「作者：」去匹配会抽出"番外语"）。
      ② 其他：用「作者：xxx」/「xxx 著」标签式匹配。

    找不到就返回空 —— **宁可空着也不瞎猜**：作者名猜错的代价比没有更大
    （会让作者搜索返回完全不相干的书，用户更困惑）。
    """
    if not html or not title:
        return ""
    idx = html.find(title)
    if idx < 0:
        return ""

    # —— ① 先试表格行 ——
    # 往前找最近的 <tr>，截到 </tr>（找不到就取一个有限窗口）。
    row_start = html.rfind("<tr", max(0, idx - 1200), idx)
    if row_start >= 0:
        row_end = html.find("</tr>", idx)
        row = html[row_start: row_end + 5 if row_end >= 0 else idx + 700]
        m = _TR_ROW_RE.search(row)
        row_html = m.group(1) if m else row
        cells = [_text_of(c) for c in _TD_CELL_RE.findall(row_html)]
        if len(cells) >= 3:
            # 标题格之后的第一格通常是「最新章」，从第 3 格起找像人名的。
            # （第 1 格是书名本身，第 2 格是最新章节 —— 都不该是作者。）
            for c in cells[2:]:
                c = c.strip()
                if not c or len(c) > 16:
                    continue
                if _CELL_NOISE_RE.search(c):
                    continue
                if _PERSON_RE.match(c):
                    return _clean_author(c)
            # 表格形态但没找到人名 → 不要退回去做标签匹配：
            # 那会把「最新章」里的「作者」二字当标签用。直接收工。
            return ""

    # —— ② 标签式 ——
    win = html[max(0, idx - 120): idx + len(title) + 400]
    win = _HIDDEN_RE.sub("", win)
    m = _AUTHOR_LABEL_RE.search(win)
    if m:
        return _clean_author(m.group(1))
    m = _AUTHOR_SUFFIX_RE.search(win)
    if m:
        return _clean_author(m.group(1))
    return ""


def _clean_author(a: str) -> str:
    a = (a or "").strip(" 　·:：,，.。")
    # 明显是导航/字段名的，不要
    if not a or len(a) > 16:
        return ""
    if _BAD_TITLE.match(a) or re.search(r"分类|状态|字数|更新|点击|章节|首页|排行", a):
        return ""
    return a


def _extract_book_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """从一个搜索列表页里抽出「书名 → 详情页 URL」。

    通用启发式，和 `webfetch.extract_toc` 同源思路：
      1. 把所有 <a> 归一化成模板（数字 → #）
      2. 按模板分组
      3. 挑「既像书页路径、条目又多」的那组
         —— 搜索列表里，结果链接必然是同模板的一批；
            导航/侧边栏是零散的各种模板。

    另外兜一道：如果模板组按路径都不像书页，就退回「链接文字像书名」的判定
    （中文 2~20 字、不含导航词）。
    """
    html = _HIDDEN_RE.sub("", html or "")
    links: list[tuple[str, str]] = []
    for href, inner in _A_RE.findall(html):
        href = (href or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        absu = urljoin(base_url, href)
        t = _text_of(inner)
        if not t:
            continue
        links.append((t, absu))

    if not links:
        return []

    groups: dict[str, list[tuple[str, str]]] = {}
    for t, u in links:
        groups.setdefault(_tpl_of(u), []).append((t, u))

    # 优先挑「路径看起来就是书页」的组
    #
    # 排序键的含义（都是越靠前越像「书」）：
    #   looks_book —— 路径形状命中 `_BOOK_PATH`
    #   -depth     —— **层级越浅越像书页**。同一个搜索页里，
    #                 书页是 `/html/489/489427/`（2 段数字），
    #                 章节是 `/html/489/489427/749.html`（3 段数字 + 扩展名）。
    #                 章节链接往往**比书还多**（每本书配一条最新章），
    #                 只按数量排会把「最新章节列表」当成结果 —— 实测踩过。
    #   -len(title) 中位数之类不做，交给下面的 good 计数
    #   len(items) —— 同分时条目多的赢
    scored: list[tuple[int, int, int, int, list[tuple[str, str]]]] = []
    for tpl, items in groups.items():
        if len(items) < 2:
            continue
        sample = _path_tpl_of(items[0][1])
        looks_book = 1 if looks_like_book_url(items[0][1]) else 0
        depth = sample.count("#")
        # 组内标题长度合理（2~40）的比例越高越好
        good = sum(1 for t, _u in items if 2 <= len(t) <= 40)
        # 有没有 `.html` 扩展名 —— 章节页几乎都有，详情页常常没有
        has_ext = 1 if re.search(r"\.html?$", sample, re.I) else 0
        scored.append((looks_book, -depth, -has_ext, good, items))

    if scored:
        scored.sort(key=lambda x: (x[0], x[1], x[2], x[3], len(x[4])), reverse=True)
        best = scored[0][4]
        if len(best) >= 2 and scored[0][0] == 1:
            return _dedup_pairs(best)

    # 兜底：从所有链接里挑「文字像书名」的，且路径要像书页
    out: list[tuple[str, str]] = []
    for t, u in links:
        if not (2 <= len(t) <= 30):
            continue
        if not re.search(r"[\u4e00-\u9fff]", t) or _BAD_TITLE.match(t):
            continue
        if looks_like_book_url(u):
            out.append((t, u))
    return _dedup_pairs(out)


def _dedup_pairs(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for t, u in items:
        k = normalize_title(t) + "|" + u
        if k in seen:
            continue
        seen.add(k)
        out.append((t, u))
    return out


__all__ = ["RegistrySource"]
