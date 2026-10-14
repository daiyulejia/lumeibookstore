"""站点自动适配器 —— 给一个网址，推导出一份能用的来源配置。

为什么需要它
------------
内置来源永远是有限的。用户搜不到某本书时，最可能的答案不是「这本书不存在」，
而是「我们没接那个站」。但小说站没有统一标准：编码、搜索接口、目录结构、
正文容器各不相同，靠人工写适配器覆盖不过来，而且笔趣阁系域名平均寿命只有
几个月 —— 今天写死的类，明天就 404 了。

所以这里做「结构推导」：抓几个真实页面，从 HTML 里**反推**正则，
再端到端跑一遍自检（搜索 → 目录 → 正文 → 内容质量校验）。
只有真能抓到合格正文的才产出配置；推不出来就返回失败原因，
而不是生成一个「看着像但抓不到东西」的配置 —— 那比没有更糟。

推导策略
--------
不是硬编码某一家的选择器，而是**候选模式库 + 实测打分**：

  搜索条目  多个通用 <a> 提取模式，看哪个能捞出的「像书名的链接」最多
  目录      同上，但要求条目像章节名 / 数量够多
  正文      候选容器模式 + 「汉字密度」兜底：找出页面上纯中文最密集的那块

最后用 check_content_quality() 判定正文是不是真的（不是登录页/广告/导航）。
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote, urljoin, urlparse

from ..utils import clean_text, fetch_text, normalize_title
from .base import check_content_quality, page_mark

logger = logging.getLogger("novel.adapt")

# ---------------------------------------------------------------------------
# 编码
# ---------------------------------------------------------------------------
_META_CHARSET_RE = re.compile(
    r"""<meta[^>]+charset=["']?\s*([\w-]+)""", re.I
)


def _decode(raw: bytes) -> tuple[str, str]:
    """把字节解成文本，返回 (文本, 用的编码)。

    中文老站大量是 gb2312/gbk，直接按 utf-8 解会得到一堆乱码，
    于是所有正则都匹配不上 —— 这是自动适配最容易踩的第一个坑。
    """
    head = raw[:4096].decode("ascii", errors="ignore")
    m = _META_CHARSET_RE.search(head)
    if m:
        enc = m.group(1).lower()
        enc = "gb18030" if enc in ("gb2312", "gbk", "gb18030") else enc
        try:
            return raw.decode(enc, errors="replace"), enc
        except LookupError:
            pass
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8"


def _get(url: str, timeout: float = 12.0, data: Optional[dict] = None) -> tuple[str, str]:
    """抓页面，返回 (html, 编码)。失败抛异常。

    data 非空则发 POST —— 很多小说站的搜索是 POST 表单
    （EmpireCMS 的 /e/search/ 就是），只试 GET 会漏掉一大类站。
    """
    from ..utils import get_client

    r = get_client().request(
        "POST" if data else "GET",
        url,
        data=data,
        timeout=timeout,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    return _decode(r.content)


# ---------------------------------------------------------------------------
# 引擎指纹
# ---------------------------------------------------------------------------
ENGINE_MARKS: list[tuple[str, re.Pattern]] = [
    ("wordpress", re.compile(r"/wp-content/|/wp-json|wp-includes", re.I)),
    ("empirecms", re.compile(r"/e/search/|EmpireCMS|/skin/|/enews", re.I)),
    ("dedecms", re.compile(r"/templets/|DedeCMS|/plus/search", re.I)),
    ("thinkphp", re.compile(r"ThinkPHP|/index\.php/Home/", re.I)),
]


def fingerprint(html: str) -> str:
    for name, rx in ENGINE_MARKS:
        if rx.search(html[:60_000]):
            return name
    return "generic"


# ---------------------------------------------------------------------------
# 候选模式库
# ---------------------------------------------------------------------------
# 搜索结果的条目：通用 <a> 抽取。用命名组，配置里直接复用。
SEARCH_ITEM_PATTERNS = [
    r'<a[^>]+href="(?P<url>[^"]{4,120})"[^>]*>(?P<title>[^<]{2,40})</a>',
    r"<a[^>]+href='(?P<url>[^']{4,120})'[^>]*>(?P<title>[^<]{2,40})</a>",
    r'<a[^>]+href="(?P<url>[^"]+)"[^>]*title="(?P<title>[^"]{2,40})"',
    r'<h[34][^>]*>\s*<a[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>[^<]+)</a>',
]

# 目录页的章节条目
CHAPTER_PATTERNS = [
    r'<a[^>]+href="(?P<url>[^"]+\.html?)"[^>]*>(?P<title>[^<]{2,60})</a>',
    r"<a[^>]+href='(?P<url>[^']+\.html?)'[^>]*>(?P<title>[^<]{2,60})</a>",
    r'<dd[^>]*>\s*<a[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>[^<]+)</a>',
    r'<li[^>]*>\s*<a[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>[^<]+)</a>',
]

# 正文容器候选（覆盖绝大多数网文模板）
CONTENT_PATTERNS = [
    r'<div[^>]+id=["\']?content["\']?[^>]*>(?P<c>[\s\S]*?)</div>',
    r'<div[^>]+id=["\']?chaptercontent["\']?[^>]*>(?P<c>[\s\S]*?)</div>',
    r'<div[^>]+id=["\']?booktxt["\']?[^>]*>(?P<c>[\s\S]*?)</div>',
    r'<div[^>]+id=["\']?chapter_content["\']?[^>]*>(?P<c>[\s\S]*?)</div>',
    r'<div[^>]+class=["\'][^"\']*\bcontent\b[^"\']*["\'][^>]*>(?P<c>[\s\S]*?)</div>',
    r'<div[^>]+id=["\']?htmlContent["\']?[^>]*>(?P<c>[\s\S]*?)</div>',
    r'<article[^>]*>(?P<c>[\s\S]*?)</article>',
    r'<section[^>]+id=["\']?content["\']?[^>]*>(?P<c>[\s\S]*?)</section>',
]

# 书名字段候选
TITLE_PATTERNS = [
    r'<meta[^>]+property=["\']og:novel:book_name["\'][^>]+content=["\']([^"\']+)',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:novel:book_name',
    r'<h1[^>]*>\s*([^<]{2,40}?)\s*</h1>',
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
]

AUTHOR_PATTERNS = [
    r'<meta[^>]+property=["\']og:novel:author["\'][^>]+content=["\']([^"\']+)',
    r'作者[：:]\s*</?[^>]*>?\s*<a?[^>]*>([^<]{2,20})<',
    r'作者[：:]\s*([^\s<，,]{2,20})',
]

# 常见搜索路径（按命中率排）
SEARCH_PATH_TEMPLATES = [
    "/search.php?keyword={kw}",
    "/search.php?q={kw}",
    "/search.html?s={kw}",
    "/search.html?q={kw}",
    "/search.html?keyword={kw}",
    "/modules/article/search.php?searchkey={kw}",
    "/e/search/?searchget=1&keyboard={kw}",
    "/index.php/search?q={kw}",
    "/search/?searchkey={kw}",
    "/search?keyword={kw}",
    "/so.php?q={kw}",
    "/s?q={kw}",
    "/search/{kw}/",
    "/search/{kw}.html",
]

# 搜索输入框的参数名。`s` 必须在内 —— 一大批笔趣阁模板用的就是
# <form action="/search.html"><input name="s">，漏了它整站就"找不到搜索接口"。
SEARCH_FIELD_HINTS = (
    "s", "q", "k", "wd", "kw", "key", "keys", "word", "search", "searchkey",
    "searchkeyboard", "keyboard", "query", "keyword", "keyword",
)


def _looks_like_search_field(name: str) -> bool:
    n = (name or "").lower().strip("[]")
    if not n:
        return False
    if n in SEARCH_FIELD_HINTS:
        return True
    return any(h in n for h in ("search", "key", "word", "query", "kw"))

_FORM_RE = re.compile(r"<form[\s\S]{0,800}?</form>", re.I)
_ACTION_RE = re.compile(r'action=["\']?([^"\'\s>]+)', re.I)
_INPUT_NAME_RE = re.compile(r'<input[^>]+name=["\']?([\w\[\]]+)', re.I)
_HAN = re.compile(r"[\u4e00-\u9fff]")
_CHAP_HINT = re.compile(r"第\s*[0-9零一二三四五六七八九十百千两]+\s*[章节回卷篇]|\d{1,4}\s*[.、]")
_NOISE_HINT = re.compile(
    r"登录|注册|首页|上一页|下一页|目录|书架|排行|推荐|设为首页|手机版|"
    r"Copyright|版权|关于我们|友情链接|举报|投诉|广告|"
    r"直达|底部|顶部|点击阅读|开始阅读|立即阅读|展开|收起|返回|"
    r"全部章节|最新章节|章节目录|投票|打赏|评论",
    re.I,
)
# 容器扫描：目录正则只会写 div，但很多站用 <section>/<article>/<td>
_CONTAINER_RE = re.compile(
    r"<(div|section|article|td|main)\b([^>]*)>([\s\S]{200,80000}?)</\1>", re.I
)
_ID_RE = re.compile(r"""\bid=["']?([\w:-]+)""")
_CLASS_RE = re.compile(r"""\bclass=["']([^"']+)["']""")
_SECOND_CLASS_RE = re.compile(r"""\bclass=['"]([^"']+)['"]""")
_ID_ANY_RE = re.compile(r"""\bid=['"]?([\w:-]+)["']?""")


def _tag_ident(tag: str, attrs: str) -> Optional[tuple[str, str]]:
    """从开标签属性里找一个「可以用来写正则」的锚点。

    优先 id（最可靠），没有就用 class 里最长的那个 token
    （越长越可能是语义化的容器名，如 `chapter-content`，而不是 `col-md-9`）。
    """
    m = _ID_RE.search(attrs) or _ID_ANY_RE.search(attrs)
    if m:
        return "id", m.group(1)
    m = _CLASS_RE.search(attrs) or _SECOND_CLASS_RE.search(attrs)
    if m:
        toks = [t for t in m.group(1).split() if re.fullmatch(r"[A-Za-z][\w-]{2,}", t)]
        if toks:
            return "class", max(toks, key=len)
    return None


def han_ratio(s: str) -> float:
    if not s:
        return 0.0
    return len(_HAN.findall(s)) / len(s)


def han_count(s: str) -> int:
    return len(_HAN.findall(s))


def _strip_tags(html: str) -> str:
    t = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html, flags=re.I)
    t = re.sub(r"<[^>]+>", "\n", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\n{2,}", "\n", t).strip()


# ---------------------------------------------------------------------------
# URL 形状聚类
# ---------------------------------------------------------------------------
_DIGITS_RE = re.compile(r"\d+")


def _url_shape(u: str) -> str:
    """把 URL 的「形态」抽出来：数字一律换成 #。

        /12/12454/93000.html  →  /#/#/#.html
        /book/1/              →  /book/#/

    同一份列表里的真实条目**共享同一种形态**（同一个模板渲染出来的），
    而 logo / 导航 / 侧边栏这些零散链接形态各异。所以按形态分组、
    取最大的那一组，就能自动把导航噪音甩掉 —— 这比维护一张
    「导航词黑名单」通用得多。
    """
    path = urlparse(u).path or "/"
    return _DIGITS_RE.sub("#", path)


def _largest_shape_group(items: list[dict]) -> list[dict]:
    if not items:
        return items
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(_url_shape(it["url"]), []).append(it)
    return max(groups.values(), key=len)


def _dedup_items(items: list[dict]) -> list[dict]:
    """按「书名/章节名 + URL」去重。

    同一个章节常被页面上的两个小部件各渲染一次（顶部「最新章节」
    和下面的完整目录），于是推导出的章节表里会出现两条一样的。
    """
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for it in items:
        k = (normalize_title(it["title"]), it["url"])
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


# ---------------------------------------------------------------------------
# 结果
# ---------------------------------------------------------------------------
@dataclass
class Adaptation:
    """一次适配的完整结果。"""

    url: str
    ok: bool = False
    engine: str = ""
    encoding: str = ""
    name: str = ""
    display: str = ""
    config: Optional[dict] = None
    steps: list[tuple[str, bool, str]] = field(default_factory=list)
    sample_chars: int = 0
    sample_preview: str = ""
    on_step: Optional[Callable[[dict], None]] = None

    def log(self, step: str, ok: bool, detail: str = "") -> None:
        self.steps.append((step, ok, detail))
        # 每一步都落日志。这是「接入一个网址失败了，为什么」**唯一**的取证来源。
        #
        # ⚠ 为什么必须在这里（2026-10-14 补）：adapter 原先**一行日志都没有** ——
        #   用户报「在接入网址里输了，不行」，去 app.log 里翻，只有一条
        #   `path=/api/adapt/stream status=200`（连 URL 和关键词都没有），
        #   完全无法判断是网址填错、站没搜索、还是正文抓不到。
        #   而适配恰恰是**最需要可诊断**的一条路：它要用户手填网址，
        #   失败面最大，且失败后除了界面上那句提示就再无痕迹。
        logger.info("适配步骤 %-4s %-8s %s",
                    "ok" if ok else "FAIL", step, detail[:160])
        if self.on_step is not None:
            try:
                self.on_step(self._step_dict(step, ok, detail))
            except Exception:  # noqa: BLE001  回调坏了不能拖垮适配本身
                pass

    def _step_dict(self, step: str, ok: bool, detail: str) -> dict:
        h = STEP_HUMAN.get(step, {})
        return {
            "step": step,
            "ok": ok,
            "detail": detail,
            "t": h.get("t", step),
            "w": h.get("w", ""),
            "hint": h.get("hint", "") if not ok else "",
        }

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "ok": self.ok,
            "engine": self.engine,
            "encoding": self.encoding,
            "name": self.name,
            "display": self.display,
            "config": self.config,
            "steps": [self._step_dict(s, o, d) for s, o, d in self.steps],
            "sample_chars": self.sample_chars,
            "sample_preview": self.sample_preview,
        }


#: 把内部步骤名翻译成人话。
#:   t = 这一步在干什么（动词开头，不出现"正则/解析器"这类词）
#:   w = 为什么要干这一步（说清它在前后的位置）
#:   hint = 失败了大概率是什么原因、该怎么办
STEP_HUMAN: dict[str, dict[str, str]] = {
    "打开首页": {
        "t": "打开这个网站的首页",
        "w": "先确认站还活着、是中文小说站，顺便看出它用什么建站系统",
        "hint": "这个站可能已经关了、换了域名，或者对非浏览器访问做了拦截（返回空页/验证页）。换一个站试试。",
    },
    "找搜索接口": {
        "t": "找出它的搜索怎么用",
        "w": "知道搜索地址，才能用书名去这个站里找书",
        "hint": "页面里既没有搜索表单、也猜不出搜索地址。这个站可能没有搜索功能，或者搜索是 JS 动态加载的。",
    },
    "打开搜索页": {
        "t": "试着搜一本书",
        "w": "用一个真实书名试搜，看它返回什么",
        "hint": "搜索地址打得开但请求失败，可能是要登录、要带 Cookie，或者被限流了。",
    },
    "推导搜索条目": {
        "t": "看懂搜索结果长什么样",
        "w": "从搜索结果里认出「哪一条是书」",
        "hint": "搜索结果页里找不到像书名列表的结构。有些站的搜索结果是 JS 渲染的，抓 HTML 抓不到。",
    },
    "打开详情页": {
        "t": "点进这本书的详情页",
        "w": "书籍详情页一般挂着完整目录",
        "hint": "从搜索结果点进去打不开，可能是详情页需要登录或跳转到了别的地方。",
    },
    "推导目录正则": {
        "t": "读出这本书的目录",
        "w": "拿到章节清单，才能一章一章往下抓",
        "hint": "详情页里没找到成规模的章节链接。这个站可能把目录放在单独的页面，或者用 JS 加载。",
    },
    "打开章节页": {
        "t": "打开其中一章",
        "w": "验证真的能读到正文，而不是只有标题",
        "hint": "章节链接点不开，可能被防抓取拦了，或者链接是相对地址拼错了。",
    },
    "推导正文正则": {
        "t": "把正文抠出来",
        "w": "从整页 HTML 里分出「哪些字是小说的」",
        "hint": "找不到正文容器，或者找到的内容太短/不像中文小说。这个站的反爬可能比较强。",
    },
    "发现章节分页": {
        "t": "发现这站一章分了好几页",
        "w": "有些站一章拆成 2~3 页，不拼起来会缺一半内容",
    },
    "完成": {
        "t": "适配完成",
        "w": "配置已保存，现在可以像内置来源一样搜书了",
    },
}


# ---------------------------------------------------------------------------
# 各步推导
# ---------------------------------------------------------------------------
def _pick_best_link_pattern(
    html: str, patterns: list[str], *, min_hits: int, chapterish: bool
) -> tuple[Optional[str], list[dict]]:
    """在候选模式里挑一个「捞得最多且最像样」的。

    打分不只看数量，还要过两道筛：
      1. URL 形状聚类 —— 甩掉 logo / 导航 / 侧边栏这类零散链接
      2. 目录页额外要求「像章节名的占比够高」，否则一页全是
         「直达底部 / 点击阅读」也会被判成 95 章
    """
    best: tuple[float, Optional[str], list[dict]] = (0.0, None, [])
    for pat in patterns:
        try:
            rx = re.compile(pat, re.S | re.I)
        except re.error:
            continue
        items: list[dict] = []
        for m in rx.finditer(html):
            gd = m.groupdict()
            title = clean_text(gd.get("title", "") or "")
            href = (gd.get("url", "") or "").strip()
            if not title or not href or len(title) > 60:
                continue
            if _NOISE_HINT.search(title):
                continue
            if href.startswith(("#", "javascript:", "mailto:")):
                continue
            items.append({"title": title, "url": href})
        items = _dedup_items(items)
        items = _largest_shape_group(items)
        if len(items) < min_hits:
            continue

        if chapterish:
            good = sum(1 for it in items if _CHAP_HINT.search(it["title"]))
            # 至少 1/4 得像章节名，否则这不是目录页
            if good < max(3, int(len(items) * 0.25)):
                continue
            score = good * 2.0 + len(items) * 0.3
        else:
            good = sum(1 for it in items if 2 <= len(it["title"]) <= 20)
            score = len(items) * (good / max(len(items), 1))

        if score > best[0]:
            best = (score, pat, items)
    return best[1], best[2]


def _find_search_url(base: str, home_html: str, keyword: str) -> tuple[Optional[str], str]:
    """找出这个站能用的搜索地址模板。返回 (模板, 说明)。"""
    cands: list[tuple[str, str]] = []
    # 1) 首页里的搜索表单
    for f in _FORM_RE.findall(home_html):
        am = _ACTION_RE.search(f)
        if not am:
            continue
        action = am.group(1).strip()
        names = _INPUT_NAME_RE.findall(f)
        if not names:
            continue
        field = next((n for n in names if _looks_like_search_field(n)), None)
        if field is None:
            # 表单本身不像搜索：action 里带 search/so 才勉强收下
            if not re.search(r"search|/so\b|sou", action, re.I):
                continue
            field = names[0]
        full = urljoin(base, action)
        if "{kw}" in full or "%s" in full:
            continue
        sep = "&" if "?" in full else "?"
        cands.append((
            (f"{full}{sep}{field}={{kw}}", "get", None),
            f"首页表单 GET {action} 字段={field}",
        ))
        # 同一个表单也按 POST 试一遍 —— 很多站的搜索是 POST，
        # 例如 EmpireCMS 的 /e/search/index.php（本站内置的无忧书城就是）
        cands.append((
            (full, "post", {field: "{kw}"}),
            f"首页表单 POST {action} 字段={field}",
        ))

    # 2) 常见路径
    for tpl in SEARCH_PATH_TEMPLATES:
        cands.append(((base.rstrip("/") + tpl, "get", None), f"常见路径 {tpl}"))

    tried: set[str] = set()
    attempts = 0
    MAX_ATTEMPTS = 16   # 上限：表单派生的一定先试，后面才是猜路径，别为猜路径耗太久
    for (tpl, method, body), why in cands:
        for enc in ("utf-8", "gbk"):
            if attempts >= MAX_ATTEMPTS:
                return None, "没找到可用的搜索接口（试了常见路径都不通）"
            kwv = quote(keyword, encoding=enc)
            if method == "post":
                u = tpl
                data = {k: v.replace("{kw}", keyword) for k, v in (body or {}).items()}
            else:
                u = tpl.replace("{kw}", kwv)
                data = None
            key = f"{method}:{u}:{enc}"
            if key in tried:
                continue
            tried.add(key)
            attempts += 1
            try:
                html, _ = _get(u, timeout=10.0, data=data)
            except Exception:  # noqa: BLE001
                continue
            if len(html) < 500:
                continue
            if _looks_like_search_result(html, keyword):
                if method == "post":
                    # POST 的模板里没地方放 {kw}，用一次性的实际地址
                    return (u, "post", body), why
                return (tpl, "get", None), why
    return None, "没找到可用的搜索接口"


def _looks_like_search_result(html: str, keyword: str) -> bool:
    """搜索结果页应该同时满足：有关键词、有一批链接、不是错误页。"""
    if keyword and keyword[:2] not in html:
        return False
    if re.search(r"没有找到|无搜索结果|not found|404", html, re.I) and len(html) < 4000:
        return False
    links = re.findall(r'<a[^>]+href="[^"]+"[^>]*>[^<]{2,40}</a>', html)
    return len(links) >= 8


async def adapt(url: str, keyword: str = "斗破苍穹", *, save: bool = False) -> Adaptation:
    """把一个网址适配成来源配置。同步实现，async 只是给 FastAPI 用。"""
    return adapt_sync(url, keyword, save=save)


def adapt_sync(
    url: str,
    keyword: str = "斗破苍穹",
    *,
    save: bool = False,
    on_step: Optional[Callable[[dict], None]] = None,
) -> Adaptation:
    """完整适配流程（同步）—— 外面包一层，只负责**记日志**。

    为什么拆成两层：`_adapt_impl` 里有十来个 `return ad`（每一步失败都会
    提前返回），要保证「无论从哪个出口出去，都有一条结论落进日志」，
    只能在外面套一层。少了它就会出现「界面上显示失败、日志里一片空白」。
    """
    logger.info("适配开始 url=%s 试搜关键词=%s 保存=%s", url, keyword, save)
    t0 = time.time()
    try:
        ad = _adapt_impl(url, keyword, save=save, on_step=on_step)
    except Exception:
        logger.exception("适配异常 url=%s", url)
        raise
    last_step, last_ok, last_detail = ad.steps[-1] if ad.steps else ("", False, "")
    logger.info(
        "适配%s url=%s 耗时=%dms 卡在=%s 详情=%s",
        "成功" if ad.ok else "失败", ad.url, int((time.time() - t0) * 1000),
        last_step or "-", str(last_detail)[:120])
    return ad


def _adapt_impl(
    url: str,
    keyword: str = "斗破苍穹",
    *,
    save: bool = False,
    on_step: Optional[Callable[[dict], None]] = None,
) -> Adaptation:
    """完整适配流程（同步）。

    on_step: 每完成一步回调一次，参数是 `_step_dict()` 的结果（含人话文案）。
             给流式接口用 —— 用户能看到"走到哪一步了"，而不是干等 20 秒。
             回调里抛异常会被吞掉，不能因为推送失败毁掉适配本身。
    """
    url = url.strip().rstrip("/")
    if not url.startswith("http"):
        url = "https://" + url
    host = urlparse(url).netloc or url
    ad = Adaptation(url=url, name=re.sub(r"[^\w]+", "_", host)[:24], display=host)
    ad.on_step = on_step

    # ---- 0. 首页 ----
    try:
        home, enc = _get(url)
    except Exception as e:  # noqa: BLE001
        ad.log("打开首页", False, f"{type(e).__name__}: {str(e)[:60]}")
        return ad
    ad.encoding = enc
    ad.engine = fingerprint(home)
    if len(home) < 800:
        ad.log("打开首页", False, f"页面只有 {len(home)} 字节，像是空壳/限制页")
        return ad
    home_title = ""
    m = re.search(r"<title>([^<]{0,80})", home, re.I)
    if m:
        home_title = m.group(1).strip()
    ad.display = re.sub(r"[-_|—].*$", "", home_title).strip() or host
    ad.log("打开首页", True, f"{len(home)} 字节 · {enc} · 引擎={ad.engine} · {home_title[:34]}")

    # ---- 1. 搜索接口 ----
    found, why = _find_search_url(url, home, keyword)
    if not found:
        ad.log("找搜索接口", False, why)
        return ad
    s_tpl, s_method, s_body = found
    ad.log("找搜索接口", True, f"{s_method.upper()} {s_tpl}  （{why}）")
    s_url = (
        s_tpl.replace("{kw}", quote(keyword, encoding="utf-8"))
        if "{kw}" in s_tpl
        else s_tpl
    )
    s_data = (
        {k: v.replace("{kw}", keyword) for k, v in (s_body or {}).items()}
        if s_body
        else None
    )
    try:
        s_html, _ = _get(s_url, data=s_data)
    except Exception as e:  # noqa: BLE001
        ad.log("打开搜索页", False, str(e)[:60])
        return ad

    # ---- 2. 搜索条目正则 ----
    s_pat, s_items = _pick_best_link_pattern(
        s_html, SEARCH_ITEM_PATTERNS, min_hits=5, chapterish=False
    )
    if not s_pat or not s_items:
        ad.log("推导搜索条目", False, "搜索结果页里找不到像书名的链接列表")
        return ad
    # 候选里优先挑「标题像关键词」的那条，作为进详情页的入口
    nk = normalize_title(keyword)
    detail = next(
        (it for it in s_items if nk and nk in normalize_title(it["title"])),
        s_items[0],
    )
    detail_url = urljoin(s_url, detail["url"])
    ad.log("推导搜索条目", True, f"{len(s_items)} 条，取《{detail['title']}》进详情页")

    # ---- 3. 详情页：目录 + 书名/作者 ----
    try:
        d_html, _ = _get(detail_url)
    except Exception as e:  # noqa: BLE001
        ad.log("打开详情页", False, str(e)[:60])
        return ad
    c_pat, c_items = _pick_best_link_pattern(
        d_html, CHAPTER_PATTERNS, min_hits=5, chapterish=True
    )
    if not c_pat or len(c_items) < 5:
        ad.log("推导目录正则", False, f"详情页只找到 {len(c_items)} 条章节链接")
        return ad
    ad.log("推导目录正则", True, f"{len(c_items)} 章，例：{' / '.join(i['title'][:14] for i in c_items[:3])}")

    book_title = ""
    for p in TITLE_PATTERNS:
        mm = re.search(p, d_html, re.S | re.I)
        if mm:
            cand = clean_text(mm.group(1))
            if 1 < len(cand) <= 40:
                book_title = cand
                break
    book_author = ""
    for p in AUTHOR_PATTERNS:
        mm = re.search(p, d_html, re.S | re.I)
        if mm:
            cand = clean_text(mm.group(1))
            if 1 < len(cand) <= 20:
                book_author = cand
                break

    # ---- 4. 正文正则 ----
    # 目录里第 2 章通常才是真正文（第 1 章常是「作品相关」之类）
    probe_ch = c_items[1] if len(c_items) > 1 else c_items[0]
    ch_url = urljoin(detail_url, probe_ch["url"])
    try:
        ch_html, _ = _get(ch_url)
    except Exception as e:  # noqa: BLE001
        ad.log("打开章节页", False, str(e)[:60])
        return ad

    content_pat, text = _infer_content(ch_html)
    if not content_pat:
        ad.log("推导正文正则", False, "找不到正文容器")
        return ad
    ok, note = check_content_quality(text)
    ad.sample_chars = len(text)
    ad.sample_preview = text[:120].replace("\n", " ")
    if not ok:
        ad.log("推导正文正则", False, f"抓到了但内容不合格：{note}")
        return ad
    ad.log(
        "推导正文正则",
        True,
        f"{content_pat[:40]}… 抽出 {len(text)} 字，样例：{ad.sample_preview[:50]}",
    )

    # ---- 5. 组装配置 ----
    cfg = {
        "name": ad.name,
        "display": ad.display,
        "priority": 30,
        "enabled": True,
        "base_url": url,
        "homepage": url,
        "encoding": enc if enc != "utf-8" else "",
        "search_url": s_tpl,
        "search_item_re": s_pat,
        "chapter_re": c_pat,
        "content_re": content_pat,
        # 推导出来的都是「一整个正文容器」的正则，不是「一行一段」。
        # 这种必须走 content_multi=false：那条路径用 clean_text()，
        # 它会把 <br> / </p> 还原成换行；multi=true 是逐段裸去标签，
        # 段落分隔会全丢，读起来是一坨。
        "content_multi": False,
        "_adapted": True,
        "_engine": ad.engine,
        "_verified": f"{len(text)} 字正文通过质量校验",
    }
    if s_method == "post":
        cfg["search_method"] = "post"
        if s_body:
            cfg["search_body"] = s_body
    if book_title:
        cfg["book_title_re"] = TITLE_PATTERNS[0]
    if book_author:
        cfg["book_author_re"] = AUTHOR_PATTERNS[0]
    # 这一章是不是被拆成多页了？是的话要打开分页拼接，
    # 否则每章只抓到第 1 页，用户拿到的是残缺的书。
    mark = page_mark(text)
    if mark and mark[1] > 1:
        cfg["chapter_paged"] = True
        ad.log("发现章节分页", True, f"第 {mark[0]}/{mark[1]} 页 —— 已开启自动拼接")
    ad.config = cfg
    ad.ok = True
    ad.log("完成", True, f"来源「{ad.display}」可用（引擎 {ad.engine}）")

    if save:
        save_adapted(cfg)
    return ad


def _infer_content(html: str) -> tuple[Optional[str], str]:
    """推导正文容器：候选模式 → 通用容器扫描 → 汉字密度兜底。

    三条路都必须**真的产出一个能复用的正则**，而不是只把这段文字抠出来。
    因为这套配置是要落盘给 ConfiguredSource 逐章复用的：
    这次能抽出来但写不成正则，等于没适配成功。
    """
    # —— 路径 1：已知的常见模板 ——
    best: tuple[float, Optional[str], str] = (0.0, None, "")
    for pat in CONTENT_PATTERNS:
        try:
            rx = re.compile(pat, re.S | re.I)
        except re.error:
            continue
        m = rx.search(html)
        if not m:
            continue
        text = clean_text(_strip_tags(m.group("c")))
        hc = han_count(text)
        if hc < 80:
            continue
        score = hc * han_ratio(text.replace("\n", ""))
        if score > best[0]:
            best = (score, pat, text)
    if best[1]:
        return best[1], best[2]

    # —— 路径 2：扫描所有容器，挑汉字最密的那个，再**反推**正则 ——
    return _synthesize_content_re(html)


def _synthesize_content_re(html: str) -> tuple[Optional[str], str]:
    """找出正文块，并照着它的 id/class（或标签名）写一条正则。"""
    rows: list[tuple[float, str, str, str]] = []  # (score, tag, attrs, text)
    for m in _CONTAINER_RE.finditer(html):
        tag, attrs, inner = m.group(1).lower(), m.group(2), m.group(3)
        text = clean_text(_strip_tags(inner))
        hc = han_count(text)
        if hc < 120:
            continue
        rows.append((hc * han_ratio(text.replace("\n", "")), tag, attrs, text))
    if not rows:
        return None, ""
    rows.sort(key=lambda r: -r[0])

    # 从高分往低试：写法正则 → 验证它在这页抽出来的字数与原始块对得上
    for score, tag, attrs, text in rows[:4]:
        ident = _tag_ident(tag, attrs)
        if ident:
            kind, val = ident
            pat = (
                rf'<{tag}[^>]+\b{kind}=["\']?{re.escape(val)}["\']?[^>]*>'
                rf"(?P<c>[\s\S]*?)</{tag}>"
            )
        else:
            # 没有 id/class：只能用标签名。仅当这种标签在页面里数量不多时
            # 才敢这么写（页面里一堆 <div> 就没法用 <div> 定位）。
            if len(re.findall(rf"<{tag}\b", html, re.I)) > 4:
                continue
            pat = rf"<{tag}[^>]*>(?P<c>[\s\S]*?)</{tag}>"

        try:
            got = re.search(pat, html, re.S | re.I)
        except re.error:
            continue
        if not got:
            continue
        out = clean_text(_strip_tags(got.group("c")))
        # 抽出来的必须和当初打分的那块差不多（允许 15% 差异）
        if han_count(out) < han_count(text) * 0.85:
            continue
        return pat, out
    return None, ""


# ---------------------------------------------------------------------------
# 落盘
# ---------------------------------------------------------------------------
CONFIG_FILE = Path(__file__).resolve().parent / "sites.json"


def save_adapted(cfg: dict) -> None:
    """把适配出的配置写进 sites.json（同名则覆盖）。"""
    import json

    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        data = {"sites": []}
    sites = [s for s in data.get("sites", []) if s.get("name") != cfg["name"]]
    sites.append(cfg)
    data["sites"] = sites
    CONFIG_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
