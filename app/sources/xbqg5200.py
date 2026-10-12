"""新笔趣阁 5200 来源（www.xbqg5200.com）。

这个站有三个必须处理的反爬点：

1. **字体反爬（章节名）**
   目录里的章节名不写明文，而是 `<i>&#xe848;</i>29章 小贺谛` 这种 ——
   用站点自带的 font.woff 把私有区码位（U+E800~）**画成**数字和汉字。
   直接取文本得到的是乱码。

   破解思路：同一本书的详情页上，**「最新章节」小部件用的是明文**，
   「全部章节」列表用的是字形。同一个章节 URL 出现两次，把两份标题
   按字符对齐，就能反推出「哪个字形 = 哪个字」。这份映射对全站有效
   （字体文件是站点唯一的一份），所以边抓边学，缓存到磁盘越用越全。

2. **正文分页**  长章节会拆成 `xxx_2.html` / `xxx_3.html`，需要逐页拼接。

3. **热点链接防护** 字体和部分资源带 Referer 校验，裸请求会被 403。

流程：
    搜索  /search/?searchkey=关键词      → 解析 <h4 class="name"> 结果卡片
    目录  详情页 /{分类}/{书号}/          → 章节链接（明文 + 字形两套）
    正文  章节页 id="chaptercontent"     → <p> 段落，处理分页
"""
from __future__ import annotations

import difflib
import json
import re
import html as _html
import logging
import threading
from urllib.parse import urljoin, quote

from ..models import Book, BookResult, Chapter
from ..utils import get_client, fetch_text, clean_text, cached, html_to_text
from .base import Source

logger = logging.getLogger("novel.xbqg5200")

SITE = "https://www.xbqg5200.com"
TOC_TTL = 600

# 正文里需要丢弃的行（站点水印、广告、残留标记）
JUNK = re.compile(
    r"提示您[:：]看后求收藏"
    r"|求收藏|求推荐|加入书签|加书签"
    r"|^&lt;|^<\/?(span|div|p|a|script)"
    r"|^\s*$"
)

# 私有区码位 —— 站点用它们伪装真实字符
_PUA_RE = re.compile(r"[\ue000-\uf8ff]")

# 页面上的按钮/导航文字，不是章节名
_UI_LABEL_RE = re.compile(
    r"^(开始阅读|全部章节|加入书架|推荐本书|直达底部|返回顶部|"
    r"上一页|下一页|章节目录|目录|手机阅读|投推荐票|最新网址)$"
)


class _PuaMap:
    """字形 → 真字 的学习与缓存。

    学习样本来自「同一章节的明文标题 vs 字形标题」的对齐结果；
    因为字体文件全站唯一，学到的映射可以跨书复用，所以落盘长期积累。
    """

    def __init__(self):
        from pathlib import Path

        self.path = Path(__file__).resolve().parent.parent.parent / "cache" / "xbqg_pua.json"
        self._lock = threading.Lock()
        self.map: dict[str, str] = {}
        self._load()

    def _load(self):
        try:
            self.map = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            self.map = {}

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.map, ensure_ascii=False, indent=0),
                                 encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    def learn(self, garbled: str, clean: str) -> int:
        """把「字形标题」和「明文标题」对齐，学出新映射。返回新学到的条目数。"""
        a = [c if not _PUA_RE.match(c) else c for c in garbled]
        b = list(clean)
        if not a or not b:
            return 0
        new = 0
        with self._lock:
            sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag == "equal":
                    continue
                seg_a, seg_b = a[i1:i2], b[j1:j2]
                # 整段替换：长度一致时逐个对应
                if (seg_a and seg_b and len(seg_a) == len(seg_b)
                        and all(_PUA_RE.match(x) for x in seg_a)):
                    for x, y in zip(seg_a, seg_b):
                        if self.map.get(x) != y:
                            self.map[x] = y
                            new += 1
                # 长度不等但都只有一个字形：把明文整段记给这个字形
                elif len(seg_a) == 1 and _PUA_RE.match(seg_a[0]) and seg_b:
                    joined = "".join(seg_b)
                    if len(joined) == 1 and self.map.get(seg_a[0]) != joined:
                        self.map[seg_a[0]] = joined
                        new += 1
            if new:
                self._save()
        return new

    def decode(self, s: str) -> str:
        return _PUA_RE.sub(lambda m: self.map.get(m.group(0), ""), s)


PUA = _PuaMap()


class Xbqg5200Source(Source):
    name = "xbqg5200"
    display = "新笔趣阁5200"
    priority = 12
    homepage = SITE + "/"
    engine = "biquge-pua"

    # ---------- 搜索 ----------
    def search(self, keyword: str) -> list[BookResult]:
        url = f"{SITE}/search/?searchkey={quote(keyword, encoding='utf-8')}"
        try:
            html = fetch_text(url)
        except Exception as e:  # noqa: BLE001
            logger.info("搜索失败: %s", e)
            return []

        # 被限流时站点返回一个几十字节的空壳页面，而不是报错 —— 要认出来，
        # 否则会「成功」返回 0 条，用户以为这本书不存在。
        if _looks_blocked(html):
            return []

        # 结果卡片：<h4 class="name"><a href="/24/24762/" title="书名">…</a></h4>
        #           紧跟着 <div class="author">作者</div>
        # 注意：书名内层可能含 <strong> 等标签，因此优先取 a 的 title 属性
        pat = re.compile(
            r'<h4[^>]*class="[^"]*\bname\b[^"]*"[^>]*>\s*'
            r'<a[^>]+href="(?P<url>/[^"]+)"[^>]*?title="(?P<title>[^"]+)"[^>]*>'
            r'[\s\S]{0,400}?<div[^>]*class="[^"]*author[^"]*"[^>]*>(?P<author>[^<]*)</div>',
            re.I,
        )
        out: list[BookResult] = []
        seen: set[str] = set()
        for m in pat.finditer(html):
            gd = m.groupdict()
            title = clean_text(gd.get("title", ""))
            href = gd.get("url", "")
            if not title or not href or href in seen:
                continue
            seen.add(href)
            out.append(
                BookResult(
                    title=title,
                    author=clean_text(gd.get("author", "")),
                    source=self.name,
                    url=urljoin(SITE, href),
                )
            )
        return out[:30]

    # ---------- 目录 ----------
    def get_chapters(self, result: BookResult) -> list[Chapter]:
        return cached(
            f"toc:{self.name}:{result.url}",
            TOC_TTL,
            lambda: self._load_chapters(result),
        )

    def _load_chapters(self, result: BookResult) -> list[Chapter]:
        try:
            html = fetch_text(result.url)
        except Exception:  # noqa: BLE001
            return []

        # 章节链接形如 /24/24762/2979082.html
        # 内层用非贪婪匹配，因为「字形版」标题里嵌着 <i> 标签
        pat = re.compile(
            r'<a[^>]+href="(?:https?://[^"]+)?(?P<url>/[0-9]+/[0-9]+/(?P<id>[0-9]+)\.html)"'
            r'[^>]*>(?P<inner>[\s\S]*?)</a>',
            re.I,
        )

        # 同一章的 URL 在页面上可能出现两次：
        #   · 「最新章节」小部件 → 明文
        #   · 「全部章节」列表   → 字形混淆
        # 按 URL 归并，明文优先，同时拿两份做对齐学习。
        plain: dict[str, tuple[int, str]] = {}
        garbled: dict[str, tuple[int, str]] = {}
        for m in pat.finditer(html):
            url = m.group("url")
            nid = int(m.group("id"))
            raw = m.group("inner")
            text = _strip_tags(raw)
            if not text:
                continue
            if _PUA_RE.search(text):
                garbled.setdefault(url, (nid, text))
            else:
                if _UI_LABEL_RE.match(text):
                    continue
                plain.setdefault(url, (nid, text))

        # 一边读一边学：全站共用一份字体，映射会越攒越全
        learned = 0
        for url, (_nid, g) in garbled.items():
            p = plain.get(url)
            if p:
                learned += PUA.learn(g, p[1])
        if learned:
            logger.info("xbqg5200 字形映射新增 %d 条（累计 %d）", learned, len(PUA.map))

        # 按章节 ID 升序 = 正确阅读顺序
        merged: dict[str, tuple[int, str]] = {}
        for url, (nid, t) in garbled.items():
            decoded = PUA.decode(t).strip()
            merged[url] = (nid, decoded or t)
        for url, (nid, t) in plain.items():
            merged[url] = (nid, t)          # 明文永远优先

        ordered = sorted(merged.items(), key=lambda kv: kv[1][0])
        return [
            Chapter(index=i, title=title, url=urljoin(SITE, url))
            for i, (url, (_nid, title)) in enumerate(ordered, 1)
        ]

    # ---------- 正文 ----------
    def fetch(self, result: BookResult, progress=None, limit=None, stop=None) -> Book:
        chapters = self.get_chapters(result)
        if limit:
            chapters = chapters[:limit]
        book = Book(title=result.title, author=result.author, source=self.name,
                    url=result.url)
        book.chapters = self.fetch_all(chapters, self.fetch_chapter, progress, stop)
        return book

    # ---------- 单章（预览用） ----------
    def fetch_chapter(self, chapter: Chapter) -> str:
        try:
            return self._fetch_chapter(chapter.url)
        except Exception:  # noqa: BLE001
            return ""

    # ---------- 内部 ----------
    def _fetch_chapter(self, url: str) -> str:
        """抓一章，自动处理分页（xxx_2.html、xxx_3.html …）。"""
        base = re.sub(r"_\d+\.html$", "", url)
        if base.endswith(".html"):
            base = base[: -len(".html")]

        parts: list[str] = []
        # 第 1 页
        html = fetch_text(url)
        if _looks_blocked(html):
            return ""
        parts.append(self._parse_page(html))
        pages = self._page_count(html)

        # 后续页
        for p in range(2, pages + 1):
            try:
                more = fetch_text(f"{base}_{p}.html")
                if _looks_blocked(more):
                    break
                parts.append(self._parse_page(more))
            except Exception:  # noqa: BLE001
                break
        return clean_text("\n\n".join(x for x in parts if x))

    @staticmethod
    def _page_count(html: str) -> int:
        m = re.search(r"<small>\s*\(第\s*\d+\s*/\s*(\d+)\s*页\)\s*</small>", html)
        return int(m.group(1)) if m else 1

    @staticmethod
    def _parse_page(html: str) -> str:
        """提取正文容器里的段落（兼容 <p> 包裹 与 纯 <br/> 两种排版）。"""
        m = re.search(r'<div[^>]*id="chaptercontent"[^>]*>([\s\S]*?)</div>', html, re.I)
        if not m:
            return ""
        return html_to_text(m.group(1), JUNK, br_fallback=True)


def _strip_tags(fragment: str) -> str:
    """把锚点内层 HTML 变成纯文本。

    必须先 unescape 再剥标签 —— 字形是写成 `&#xe848;` 实体的，
    先剥标签的话实体还留着，就认不出这是 PUA 字符了。
    """
    txt = _html.unescape(fragment or "")
    txt = re.sub(r"<[^>]+>", "", txt)
    return clean_text(txt).strip()


def _looks_blocked(html: str) -> bool:
    """识别「被限流」的空壳页面，并让它进入冷却。

    这个站被连续请求后会返回一个一百多字节的空页面 —— HTTP 状态还是 200。
    不认出来的话，调用方会把它当成「这本书没有正文」，用户看到的是
    「章节内容为空」这种莫名其妙的错误。
    """
    if len(html) >= 1200:
        return False
    from ..utils import mark_blocked

    mark_blocked(SITE, 120.0)
    logger.info("xbqg5200 返回空壳页面（%d 字节），判定为限流并进入冷却", len(html))
    return True
