"""直链抓取：给一个「书页 URL」，自己看出目录和正文在哪。

和 `sources/` 里那些适配器的区别
--------------------------------
适配器是**先有站点配置、再去搜书**（要求该站有可用的搜索接口）。
这里反过来：**书页 URL 已经在手上了**，只需要把这一本抓下来。

这条路能绕开很多麻烦 —— 实测 `www.29zw.com` 的 `/search.php` 被
Cloudflare 拦得死死的，但它的详情页 / 目录 / 正文全是敞开的。
换句话说：**它不是不能抓，只是不能搜**。而「搜」这件事，
搜索引擎已经替我们做了（见 `app/websearch.py`）。

怎么做到通用（不写死任何站的规则）
----------------------------------
**目录**：把页面里所有 `<a href>` 归一化成模板（数字 → `#`）后分组，
取条目最多的那组 —— 一个小说详情页里，章节链接必然是「同一模板、
几百上千条」，而导航链接只有个位数，天然分得开。

分好组之后还剩一个坑：**同一个模板可能被用两次**。
实测 `29zw.com` 的详情页顶部挂着「最新章节」面板（9 条，倒序），
下面才是完整目录（4534 条，正序），两者 URL 模板一模一样，
于是被并成了一组 —— 直接读出来就是

    1  第1559章 末章-登仙(大结局)
    2  第4553章：第十八章宇宙之眼(2)
    3  第4552章：第十八章宇宙之眼(1)     ← 倒着走
    ...
    10 第一卷第一章 落魄皇子 (1)          ← 忽然又从头开始

所以要靠**URL 里的数字**重新排。不看第一列、也不看最后一列，
而是找出「**这一组 URL 里哪一列数字在变**」—— 那一列就是章节号。
这比猜「第几个数字是章节 id」稳得多，也适用于
`/book/1234/5678.html`（书 id 不变、章节号在变）这种多段路径。

**正文**：按「文本密度」找容器（字数多、链接少），
并优先命中常见命名（`htmlContent` / `content` / `chaptercontent`…）。

学到的容器名会记进来源库（`app/registry.py`），同一个站第二次直接命中，
不再重新猜。
"""
from __future__ import annotations

import re
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

from . import registry
from .utils import fetch_text, host_of

# 常见正文容器命名（命中了就不用走启发式，快很多也准很多）
_CONTENT_HINTS = ("htmlcontent", "chaptercontent", "readcontent", "content",
                  "booktext", "textcontent", "showtxt", "article", "txt")

# ---------------------------------------------------------------------------
# 视频站否决
# ---------------------------------------------------------------------------
# 影视站（苹果 CMS / 首播网 / 南瓜影视这一类）**长得极像小说站**：
# 详情页会列一长串「第01集、第02集、…」的剧集链接，启发式数一数够 8 条、
# 质量分也够，就被判成 `kind="toc"` 当成书收进来。
#
# 实测：搜「余华 活着」时 `hbsjob.cn/voddetail/35245.html`（首播网）被当成
# 一个可读源，标题还是从搜索引擎带来的话题标签 `#活着`，正文却是那部韩国
# 丧尸片《#活着》的剧情简介 —— 完全是另一回事。
#
# 判据用**路径特征**，而不是页面内容：苹果 CMS 的路径是固定词表
# （`voddetail` / `vodplay` / `vodtype` / `vodshow` / `vodsearch`），
# 小说站几乎不可能用；内容特征（有没有 `<video>`）反而不稳，
# 很多视频站用 JS 播放器，HTML 里一个 video 标签都没有。
_VIDEO_PATH_RE = re.compile(
    r"/(?:vod(?:detail|play|type|show|search|list)?|show|play|detail|"
    r"movie|film|dianshiju|dongman|zongyi|variety)(?:/|$|\?|\.html)",
    re.I,
)

# 剧集用词：出现在「章节链接」的文字里就说明这是分集列表，不是章节目录。
_EPISODE_TEXT_RE = re.compile(r"第\s*[0-9零一二三四五六七八九十百]{1,4}\s*[集期话]")

# 站名里带这些词的，直接判为影视站
_VIDEO_NAME_RE = re.compile(r"影视|电影|影院|剧场|视频|TV|电视|播放|追剧|综艺|动漫", re.I)

_A_RE = re.compile(r"""<a\s[^>]*?href\s*=\s*["']([^"']+)["'][^>]*>([\s\S]{0,80}?)</a>""", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_HIDDEN_RE = re.compile(r"<(script|style|noscript|template)\b[^>]*>[\s\S]*?</\1\s*>", re.I)
_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")

# 块级标签 → 换行。
# 不加这一步，`<div>甲</div><div>乙</div>` 会被压成「甲乙」——
# 实测起点和 dquanben 的正文段落就是被这么粘成一行的，
# 于是「菜单书友圈　讨论热烈：本章含0条段评」这种导航文字全都
# 混进了正文第一段，而按行的广告过滤根本没机会生效。
_BLOCK_BREAK_RE = re.compile(
    r"<\s*(?:br|hr)\s*/?\s*>"
    r"|</\s*(?:p|div|li|ul|ol|dl|dd|dt|tr|td|th|h[1-6]|section|article"
    r"|blockquote|table|pre|figure)\s*>",
    re.I)

# 块级元素扫描用。属性部分允许引号里带 >，否则 `title="a>b"` 会把标签切断
_ANY_BLOCK = re.compile(
    r"<(/?)([a-zA-Z][a-zA-Z0-9]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*?)(/?)>", re.S)
_VOID_TAGS = frozenset((
    "br", "img", "hr", "input", "meta", "link", "source", "col", "area",
    "base", "wbr", "embed", "param", "track", "path", "circle", "rect",
    "line", "polygon", "polyline", "use", "stop", "ellipse",
))

_DIV_TAGS = frozenset(("div",))


# ---------------------------------------------------------------------------
# 预处理 & 通用小工具
# ---------------------------------------------------------------------------
def _prep(html: str) -> str:
    """去掉注释和 script/style —— 它们的 `a<b` 之类会打乱标签配对。"""
    return _HIDDEN_RE.sub("", _COMMENT_RE.sub("", html or ""))


def _text_of(fragment: str) -> str:
    frag = _HIDDEN_RE.sub("", fragment)
    return re.sub(r"[ \t\u3000]+", " ", _TAG_RE.sub("", frag)).strip()


def _abs_links(html: str, base_url: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for href, txt in _A_RE.findall(html):
        href = href.strip()
        if href.startswith(("javascript:", "mailto:", "#")):
            continue
        url = urljoin(base_url, href)
        if not url.startswith("http"):
            continue
        out.append((url, re.sub(r"\s+", " ", _text_of(txt))))
    return out


def _template(u: str) -> str:
    """把 URL 里的数字换成 #，用来判断「是不是同一类链接」。"""
    p = urlparse(u)
    return p.netloc + re.sub(r"\d+", "#", p.path)


def _num_columns(urls: list[str]) -> list[list[str]]:
    """把每个 URL 路径里的数字串按位置切开，返回「列」。"""
    cols: list[list[str]] = []
    for u in urls:
        cols.append(re.findall(r"\d+", urlparse(u).path))
    return cols


def _chapter_keys(urls: list[str]) -> Optional[list[int]]:
    """从一组 URL 里认出「哪一列数字是章节号」，返回那一列。

    判据：**变化最多的那一列**。书 id、站 id 在一本书内是不变的，
    只有章节号会从第 1 章一直变到第 4534 章。
    并列时取靠后的一列（章节号通常在路径末尾）。
    """
    cols = _num_columns(urls)
    if not cols:
        return None
    width = min(len(c) for c in cols)
    if width <= 0:
        return None
    best_i, best_n = -1, 1
    for i in range(width):
        n = len({c[i] for c in cols})
        if n >= best_n:          # >= 让靠后的列在并列时胜出
            best_i, best_n = i, n
    if best_i < 0:
        return None
    try:
        return [int(c[best_i]) for c in cols]
    except ValueError:
        return None


def _monotonic(vals: list[int]) -> int:
    """1 = 递增，-1 = 递减，0 = 乱序。允许极少量毛刺。"""
    if len(vals) < 3:
        return 0
    n = len(vals) - 1
    up = sum(1 for a, b in zip(vals, vals[1:]) if b >= a)
    dn = sum(1 for a, b in zip(vals, vals[1:]) if b <= a)
    if up / n >= 0.97:
        return 1
    if dn / n >= 0.97:
        return -1
    return 0


# ---------------------------------------------------------------------------
# 目录提取
# ---------------------------------------------------------------------------
# 站方往章节名尾巴上挂的词，读者不需要看
_TITLE_TAIL_RE = re.compile(r"(最新章节|最新更新|免费阅读|全文阅读|在线阅读|无弹窗)+$")

# 「像章节名」：第N章 / 第N节 / 第N回 / 第N卷 / 第一章 / 12. 12、
_CHAPTER_TOKEN_RE = re.compile(
    r"第\s*[0-9零一二三四五六七八九十百千两]{1,6}\s*[章节回卷篇条]|^\s*\d{1,4}\s*[.、,，:：]")


# 章节标题里**纯导航词**：抓下来的其实是按钮文案，不是章节名。
#
# 实测（tengc.com）：目录第一项的锚文本是「开始阅读」—— 那是「从第1章开始读」
# 那个按钮，站点把它和章节链接写在同一个列表里。结果阅读器第一页顶上显示
# 标题「开始阅读」，用户以为坏了。
#
# 只拦**整条就是导航词**的（`开始阅读`、`继续阅读`、`立即阅读`），
# 不拦包含它们的正常标题（「第3章 开始阅读的那一天」要留着）。
_NAV_TITLE_RE = re.compile(
    r"^(开始阅读|继续阅读|立即阅读|点击阅读|在线阅读|免费阅读|全文阅读|"
    r"开始观看|继续观看|前往阅读|进入阅读|阅读本书|在线阅读|马上阅读|"
    r"目录|章节目录|全部章节|查看目录|返回目录|"
    r"加入书架|收藏本书|加入收藏|推荐本书|投推荐票|"
    r"上一章|下一章|上一页|下一页|返回|顶部|底部|展开|收起)$")


def _clean_chapter_title(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    for _ in range(3):
        new = _TITLE_TAIL_RE.sub("", s).strip()
        if new == s:
            break
        s = new
    return s


def _is_nav_title(s: str) -> bool:
    """这一条「标题」其实是个按钮/导航词，不是章节名。"""
    return bool(s and _NAV_TITLE_RE.match(s.strip()))


def toc_quality(chapters: list[dict]) -> tuple[float, str]:
    """这一组链接「像不像真的章节目录」。返回 (可信度 0~1, 说明)。

    为什么要判：详情页上「猜你喜欢 / 同作者作品」的链接往往也有几十条，
    条目数甚至可能比某些短篇的目录还多。只看数量就会选中它 ——
    实测塔读的详情页就栽在这儿：抓回 1561 条「章节」，第一条叫《药鼎仙途》。

    两个正交的判据：
      · **URL 里有一列数字是单调的** —— 章节地址必然从第 1 章递增到最后
      · **标题里带「第N章/节/回/卷」的比例高** —— 章节名的通用长相

    只有单调**不算**证据：「猜你喜欢 / 同作者作品」那一排链接的
    `/book/1234/`、`/book/1235/` 同样是一路递增的（书 id 本来就是顺序发的）。
    所以还要求标题里至少**有一条**长得像章节 —— 一个真目录里
    连一条「第N章」都没有，基本可以断定不是目录。
    """
    if not chapters:
        return 0.0, "没有条目"
    n = len(chapters)
    if n < 3:
        return 0.0, "条目太少"

    head = chapters[:200]
    titled = sum(1 for c in head if _CHAPTER_TOKEN_RE.search(c.get("title", "")))
    ratio = titled / len(head)

    keys = _chapter_keys([c.get("url", "") for c in chapters])
    mono = bool(keys) and _monotonic(keys) != 0

    if mono and ratio >= 0.5:
        return 1.0, ""
    if ratio >= 0.85:
        # 标题非常像章节，即便 URL 不单调也认（有的站用哈希地址）
        return 0.9, ""
    if mono and ratio > 0.0:
        return 0.8, ""
    if ratio >= 0.55:
        return 0.5, "章节名不太像章节"
    if mono:
        return 0.35, "链接像章节，但标题里一条像章节名的都没有"
    return min(0.3, ratio * 0.4), "看起来不是章节列表"


def extract_toc(
    html: str,
    base_url: str,
    *,
    min_items: int = 8,
    tpl_hint: str = "",
) -> list[dict]:
    """从详情页里挑出章节列表。

    做法：把所有 `<a href>` 按 URL 模板（数字 → `#`）分组 ——
    一个小说详情页里，章节链接必然是「同一模板、几百上千条」，
    而导航链接只有个位数，天然就分得开。

    分好组之后**不看数量最大，而看质量最好**（见 toc_quality）。

    tpl_hint: 上次在这个站认出来的模板（存在来源库里）。命中就优先用它 ——
              同一个站第二次抓，不用再重新猜哪一组才是目录。
    """
    doc = _prep(html)
    links = _abs_links(doc, base_url)
    if not links:
        return []

    groups: dict[str, list[tuple[str, str]]] = {}
    for url, txt in links:
        groups.setdefault(_template(url), []).append((url, txt))

    cands: list[tuple[float, int, str, list[dict]]] = []
    for tpl, items in groups.items():
        if len(items) < min_items:
            continue
        chapters = _build_chapters(items)
        if len(chapters) < min_items:
            continue
        q, _why = toc_quality(chapters)
        cands.append((q, len(chapters), tpl, chapters))

    if not cands:
        return []

    # 学过的模板优先；否则按 (质量, 数量) 排
    hint = (tpl_hint or "").strip()
    cands.sort(key=lambda c: (c[2] == hint, c[0] >= 0.55, c[0], c[1]), reverse=True)
    _q, _n, tpl, chapters = cands[0]

    for i, c in enumerate(chapters, 1):
        c["index"] = i
        c["_tpl"] = tpl
    return chapters


def _sort_direction(vals: list[int]) -> int:
    """这列数字整体朝哪边走：1 递增 / -1 递减 / 0 说不清。

    和 `_monotonic` 的分工不一样：
      · `_monotonic` 回答「算不算严格有序」，用来判断「这组链接像不像目录」，
        所以门槛卡在 97%，宁可漏也不能认错；
      · 这个回答的是「**要不要重排一次**」，门槛 60% 就够。

    为什么必须分开：站点常把「最新章节」那一小块（倒序）和完整目录（正序）
    塞进同一组链接里，两块 URL 模板一模一样。块儿大的时候（29zw 那页，
    倒序只占 9/4543 = 0.2%）`_monotonic` 还能认出主方向；
    换成一本 60 章的书，同样是 9 条倒序，占比 13% —— 立刻就判成"乱序"、
    干脆不排了，用户看到的第一条就是「第60章 大结局」。

    主方向依然是明确的（绝大多数相邻对都在递增），所以按 60% 定方向、
    统一按章节号升序排 —— 这才是给人读的顺序。
    """
    if len(vals) < 3:
        return 0
    n = len(vals) - 1
    up = sum(1 for a, b in zip(vals, vals[1:]) if b >= a)
    if up / n >= 0.60:
        return 1
    if up / n <= 0.40:
        return -1
    return 0


def _build_chapters(items: list[tuple[str, str]]) -> list[dict]:
    """把一组同模板链接整理成章节列表：排序 → 去重 → 清洗标题。"""
    urls = [u for u, _ in items]
    keys = _chapter_keys(urls)
    ordered_by_key = bool(keys) and _sort_direction(keys) != 0
    if ordered_by_key:
        order = sorted(range(len(items)), key=lambda i: keys[i])
        items = [items[i] for i in order]

    seen: set[str] = set()
    chapters: list[dict] = []
    for url, txt in items:
        if url in seen:
            continue
        seen.add(url)
        chapters.append({"url": url, "title": _clean_chapter_title(txt)})

    # 没有任何可用的数字列时，退回「看标题里的第N章是不是递减」
    if not ordered_by_key:
        nums = [int(m.group(1)) for c in chapters[:12]
                if (m := re.search(r"第\s*(\d+)\s*[章节回]", c["title"]))]
        if len(nums) >= 4 and nums == sorted(nums, reverse=True):
            chapters.reverse()

    for i, c in enumerate(chapters, 1):
        t = c.get("title") or ""
        # 「开始阅读」这种按钮文案不是章节名 —— 它在第 1 条上最常见
        # （站点把「从第一章开始读」的按钮和章节链接排在一起）。
        # 丢掉标题但不丢条目：URL 是真的章节地址，正文能抓到。
        # 给它一个老实的占位名，而不是把按钮文字当成书名显示给用户。
        if not t or _is_nav_title(t):
            c["title"] = f"第 {i} 章" if i > 1 or len(chapters) > 1 else "正文"
        else:
            c["title"] = t
    return chapters


# ---------------------------------------------------------------------------
# 正文提取
# ---------------------------------------------------------------------------
def _div_blocks(html: str) -> list[tuple[str, str]]:
    """切出所有 `<div …>…</div>`，返回 (开标签, 内容)。

    用一遍扫描 + 栈配对，而不是对每个 div 重跑正则 ——
    详情页动辄 50 万字符、上万个 div，逐层重扫会慢一个数量级。
    """
    doc = _prep(html)
    stack: list[list] = []
    out: list[tuple[str, str]] = []
    for m in _ANY_BLOCK.finditer(doc):
        closing, tag, _attrs, selfclose = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if tag not in _DIV_TAGS or selfclose or tag in _VOID_TAGS:
            continue
        if not closing:
            stack.append([tag, m.group(0), m.end()])
            continue
        for i in range(len(stack) - 1, -1, -1):
            if stack[i][0] == tag:
                _t, open_tag, oend = stack.pop(i)
                out.append((open_tag, doc[oend:m.start()]))
                break
    return out


def _visible(s: str) -> str:
    s = _HIDDEN_RE.sub("", s)
    s = _BLOCK_BREAK_RE.sub("\n", s)     # 块级标签 → 换行（见上面说明）
    s = _TAG_RE.sub("", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
    s = re.sub(r"[ \t\u3000]+", " ", s)
    return re.sub(r"\n[ \t]*(\n[ \t]*)+", "\n", s)


def extract_content(html: str, *, hint: str = "", min_chars: int = 200) -> str:
    """找出正文。hint 是上次在这个站学到的容器名。"""
    blocks = _div_blocks(html)
    if not blocks:
        return ""

    # 预计算一次，后面三种策略共用
    cands: list[tuple[str, str, int]] = []
    for open_tag, inner in blocks:
        text = _visible(inner).strip()
        if not text:
            continue
        cands.append((open_tag.lower(), text, len(_A_RE.findall(inner))))
    if not cands:
        return ""

    # 1) 上次学到的容器名，优先
    if hint:
        h = hint.lower()
        for low, text, _l in cands:
            if h in low and len(text) >= min_chars:
                return text

    # 2) 常见命名（同一个名字可能命中多层，取最内层）
    for key in _CONTENT_HINTS:
        best = ""
        for low, text, _l in cands:
            if key in low and len(text) >= min_chars:
                if not best or len(text) < len(best):
                    best = text
        if best:
            return best

    # 3) 兜底：文本密度最高（字数 - 链接惩罚）
    best, best_score = "", 0
    for _low, text, links in cands:
        if len(text) < min_chars:
            continue
        sc = len(text) - 30 * links
        if sc > best_score:
            best, best_score = text, sc
    return best


def extract_content_hint(html: str, *, min_chars: int = 200) -> str:
    """反推出「哪个容器名装着正文」—— 用于学习。

    返回形如 `id="htmlcontent"` 里那个 `htmlcontent`，学不到就空串。
    """
    blocks = _div_blocks(html)
    best_tag, best_len = "", 0
    for open_tag, inner in blocks:
        text = _visible(inner).strip()
        if len(text) < min_chars:
            continue
        if best_len == 0 or (len(text) < best_len and len(text) >= min_chars):
            # 取「够长里最短的」= 最内层
            if best_len == 0 or len(text) < best_len:
                best_tag, best_len = open_tag, len(text)
    if not best_tag:
        return ""
    for key in _CONTENT_HINTS:
        if key in best_tag.lower():
            return key
    return ""


# ---------------------------------------------------------------------------
# 去掉站点固定尾巴
# ---------------------------------------------------------------------------
_JUNK_LINE_RE = re.compile(
    r"(请记住|本站|手机版|加入书签|返回目录|上一章|下一章|温馨提示|为您提供|"
    r"免费阅读|无弹窗|更新最快|一秒记住|本站域名|章节错误|点此举报|"
    r"求收藏|求推荐|投推荐票|加入书架|天才一秒)")

# 阅读器自带的导航词。它们常常**单独占一行**（起点移动版、dquanben 都是），
# 长度极短、不像正文。只对「整行就是这个词」的短行生效 ——
# 「他打开了目录」里的「目录」不会被误伤。
_READER_NAV = frozenset((
    "目录", "书架", "存书签", "书签", "设置", "投票", "评论", "全屏",
    "上一章", "下一章", "返回目录", "章节目录", "加入书架", "推荐本书",
    "手机阅读", "阅读模式", "字号", "字体", "背景", "夜间", "日间",
    "顶部", "底部", "菜单", "书友圈", "段评", "章评", "本章评论",
    # 实测（tengc.com）正文容器顶上挂着这三行：书首页 / 下一页 / 第一章。
    # 「书首页」是「书的首页」的按钮文案，不是正文，也不是常见导航词。
    # 「下一页」在「分页章节」（一章拆成 _2.html / _3.html）里是翻页按钮。
    # 「第一章」单独占一行时同样是章节导航（正文里的「第一章」不会独占一行）。
    "书首页", "本书首页", "返回书页", "下一页", "上一页", "第一章",
))

# 夹在正文行里的评论文案（带数字，很好认）
_MARKER_LINE_RE = re.compile(r"(讨论热烈|本章含\s*\d+\s*条|共\s*\d+\s*条(段评|章评|评论)|"
                             r"^\d+\s*条(段评|章评|评论)$)")

# 「第二十六章 引发危机菜单」—— 章节名尾巴上粘了个导航词。
# 只在**以「第N章/节/回/卷」开头**的行上剥离，且剥完还剩内容，precision 才够高。
_TITLE_GLUE_RE = re.compile(
    r"^(\s*第\s*[0-9零一二三四五六七八九十百千两]{1,6}\s*[章节回卷篇]"
    r"[^\n]{0,60}?)\s*(?:菜单|书友圈|段评|章评|目录|书架|存书签)\s*$")

# 纯符号垃圾行（保留 * ※ ×，那是作者的分节符）
_SYMBOL_ONLY_RE = re.compile(
    r"^[\s\u3000:：。，,.、；;！!？?~～\-—_=#·…“”\"'（）()\[\]【】『』「」<>|]+$")


# ---------------------------------------------------------------------------
# 「这是正文，还是一页控件？」
# ---------------------------------------------------------------------------
# 正版站（塔读、起点这类）经常是这个形状：目录页静态可读、正文页也能打开，
# 但正文要登录或 JS 渲染 —— 抽出来的就全是**控件文字**：
# 登录、注册、打赏、投票、字体大小、页面宽度…… 一行几个字，总量还不算少。
#
# 实测塔读某章抽出 61 行 / 440 字，平均每行 7 个字，**一个字正文都没有**。
# 光看「够不够长」拦不住它（440 早就过了 120 那条线），得看**形状**：
# 真实小说的段落是长句，平均每行十几字往上；控件页全是短标签。
_UI_WORDS_RE = re.compile(
    r"(登录|注册|书架|打赏|投推荐票|投银票|投票|阅读主题|字体大小|页面宽度|"
    r"扫码|客户端|下载APP|个人中心|立即投票|立即打赏)")
PROSE_UI_HITS = 5        # 命中这么多种不同的 UI 词
PROSE_UI_MAX_AVG = 14.0  # 且平均每行不到这么多字
PROSE_MIN_LINES = 12     # 行数太少不判 —— 短章本来就没几行


def looks_like_ui_skeleton(text: str) -> bool:
    """这一页是「正文」，还是「一屏控件」？

    **两条同时成立**才定性：命中的 UI 词种类够多（≥5）、平均每行字数很少（<14）。

    只用一条都不够：真实章节里出现「登录」两个字很正常，
    很短的章节平均行字数也可能偏低 —— 但两者同时出现，基本只有控件页。
    这条判据是通用的，不含任何站点名。
    """
    t = (text or "").strip()
    if not t:
        return False
    lines = [x for x in t.split("\n") if x.strip()]
    if len(lines) < PROSE_MIN_LINES:
        return False
    if len(set(_UI_WORDS_RE.findall(t))) < PROSE_UI_HITS:
        return False
    return len(t) / len(lines) < PROSE_UI_MAX_AVG


def clean_body(text: str) -> str:
    """把正文整成「一行一段」的干净文本。"""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"[ \t\u3000]+", " ", t)

    out: list[str] = []
    for raw in t.split("\n"):
        ln = raw.strip()
        if not ln or len(ln) < 2:
            continue

        # 长行里出现「本站」是正文在讲故事，不能删；只有短行才是站方模板
        if len(ln) <= 40 and _JUNK_LINE_RE.search(ln):
            continue
        # 整行就是一个阅读器导航词
        if ln in _READER_NAV:
            continue
        if len(ln) <= 30 and _MARKER_LINE_RE.search(ln):
            continue
        if len(ln) <= 6 and _SYMBOL_ONLY_RE.match(ln) and not re.search(r"[*※×]", ln):
            continue

        # 「第二十六章 引发危机菜单」→ 「第二十六章 引发危机」
        stripped = _TITLE_GLUE_RE.sub(r"\1", ln)
        if stripped != ln and len(stripped) >= 4:
            ln = stripped
        # 剥完如果整行就是个导航词，同样丢弃
        if ln in _READER_NAV:
            continue

        out.append(ln)
    return "\n".join(out).strip()


# ---------------------------------------------------------------------------
# 页面元信息（书名 / 作者 / 简介）
# ---------------------------------------------------------------------------
def _meta_content(html: str, prop: str) -> str:
    pat = re.compile(
        r"<meta[^>]+?(?:property|name)\s*=\s*[\"']" + re.escape(prop) + r"[\"'][^>]*?>",
        re.I)
    m = pat.search(html)
    if not m:
        return ""
    cm = re.search(r"content\s*=\s*[\"']([^\"']*)[\"']", m.group(0), re.I)
    return _text_of(cm.group(1)) if cm else ""


_H1_RE = re.compile(r"<h1[^>]*>([\s\S]{0,90}?)</h1>", re.I)
_TITLE_RE = re.compile(r"<title[^>]*>([\s\S]{0,160}?)</title>", re.I)
# title 尾巴里那些「明显不是站名」的词。宁可返回空、界面显示域名，
# 也别把一个「免费阅读」当成站名存进来源库。
_TAIL_STOP = re.compile(
    r"^(最新章节|全文阅读|免费阅读|在线阅读|无弹窗|全文免费阅读|免费全文阅读"
    r"|免费阅读全文|小说阅读网?|全文|目录|首页|xxx)$")


def extract_site_name(html: str) -> str:
    """猜这个站叫什么。

    顺序：`og:site_name` → `<title>` 里最后一个「- 站名」尾巴 → 猜不出就返回空串。

    为什么要这个：来源库里存的是 host（`www.luoxiaks.net`），
    界面上显示一长串域名，用户根本认不出是哪家。
    站点自己的 title 尾巴里写着「落霞读书」，白拿的。

    只在**猜不出**时返回空 —— 与其硬凑一个错的站名，不如老实显示域名。
    """
    name = _meta_content(html, "og:site_name")
    if not name:
        m = _TITLE_RE.search(_prep(html))
        if m:
            t = _text_of(m.group(1))
            parts = [p.strip() for p in re.split(r"[\-_|—–]{1,2}", t) if p.strip()]
            # 至少要能切出两段，最后一段才是站名；只有一段说明这站没写站名
            if len(parts) >= 2:
                tail = parts[-1]
                if (2 <= len(tail) <= 16
                        and not _CHAPTER_TOKEN_RE.search(tail)
                        and not _TAIL_STOP.match(tail)):
                    name = tail
    name = re.sub(r"[\s\u3000]+", "", name)
    name = re.sub(r"^[-_|—–]+|[-_|—–]+$", "", name)
    # 太短（"书"）、太长（一段话）、或根本不像名字的，一律不认
    return name[:20] if 2 <= len(name) <= 20 else ""


def extract_meta(html: str) -> dict:
    """从详情页上扒书名 / 作者 / 简介。

    走 `og:novel:*` 这类通用 meta 标签 —— 中文小说站大面积采用，
    比猜 DOM 结构靠谱。
    """
    title = (_meta_content(html, "og:novel:book_name")
             or _meta_content(html, "og:novel:novel_name")
             or _meta_content(html, "og:title")
             or _meta_content(html, "book_name"))
    author = (_meta_content(html, "og:novel:author")
              or _meta_content(html, "og:novel:writer")
              or _meta_content(html, "author"))
    intro = (_meta_content(html, "og:description")
             or _meta_content(html, "description"))

    if not title:
        m = _H1_RE.search(_prep(html))
        if m:
            title = _text_of(m.group(1))
    # 很多站的书名 meta 会带上「- 站名」或「最新章节」这类尾巴
    title = re.sub(r"[\s_\-|—]+(最新章节|全文阅读|免费阅读|在线阅读).*$", "", title).strip()
    title = re.sub(r"\s*[-_|—]\s*[^-_|—]{2,20}(小说网|文学网|读书|书城|书院|阅读网|小说阅读).*$",
                   "", title).strip()
    return {"title": title[:60], "author": author[:40], "intro": intro[:300]}


# 封面图。取 og:image 是首选 —— 中文小说站几乎都在详情页放了它，
# 而且它是**绝对地址**（或相对 base 的地址），比自己猜 DOM 里哪张 <img> 是封面稳得多。
_COVER_META_KEYS = (
    "og:image", "og:image:url", "og:image:secure_url",
    "twitter:image", "twitter:image:src", "image",
)

# 站点自带的「没有封面」占位图。
# ⚠ 一定要认出来，否则我们不但拿不到图，还会把占位图当封面**缓存到本地**，
#   之后这本书永远显示那张灰色占位图 —— 比没有封面更糟
#   （没有封面时前端会画渐变封面，至少好看）。
_COVER_PLACEHOLDER_RE = re.compile(
    r"(nocover|no-cover|no_cover|nocoverimg|default[-_]?cover|book[-_]?default"
    r"|placeholder|blank\.|empty\.|loading\.|icon[-_]?book|nophoto)",
    re.I,
)


def _looks_like_placeholder(url: str) -> bool:
    return bool(_COVER_PLACEHOLDER_RE.search(url or ""))


def extract_cover(html: str, base: str = "") -> str:
    """从详情页扒封面图地址（绝对 URL）。

    为什么必须服务端扒、不能前端直接 <img src="外站">：
      ① 小说站基本都有 Referer 防盗链，浏览器直连一律 403，图全裂；
      ② 让用户浏览器去连几十个陌生站，等于把 IP 和访问记录送出去。
    所以这里只负责**找到**地址，真正的取图交给 /api/cover 由服务端带 Referer 去拿。

    返回 "" 表示这页没有可用的封面 —— 调用方渲染成渐变兜底封面，不留空框。

    实测踩过的两种坑（都是从真实站点上抓到的）：
      · **懒加载**：`<img class="thumbnail" src="nocover.jpg" data-src="真封面.jpg">`
        —— 只读 `src` 会永远拿不到真图，必须优先读 `data-src` 这类真实地址。
      · **占位图**：站点没封面时给一张 `nocover.jpg`。必须识别并丢弃，
        否则会把占位图缓存下来，那本书从此永远显示灰图。
    """
    raw = ""
    for k in _COVER_META_KEYS:
        raw = _meta_content(html, k)
        if raw and not _looks_like_placeholder(raw):
            break
        raw = ""
    if not raw:
        # meta 缺失时退一步：详情页常见的 <img class="cover|bookimg|thumbnail"> 写法。
        for tag in _COVER_IMG_RE.findall(_prep(html)):
            src, lazy = _img_inner(tag)
            # 懒加载地址优先 —— 它的 src 通常就是占位图
            cand = (lazy or src or "").strip()
            if cand and not cand.startswith("data:") and not _looks_like_placeholder(cand):
                raw = cand
                break
    raw = (raw or "").strip()
    if not raw or raw.startswith("data:") or _looks_like_placeholder(raw):
        # data: 内联图多数是占位符/加载动画，不是封面
        return ""
    try:
        # urljoin 顺带处理了「//host/x.jpg」和「/x.jpg」两种相对写法
        return urljoin(base or "", raw)[:500]
    except Exception:  # noqa: BLE001
        return ""


# ⚠ 属性顺序在这个正则里被**刻意放宽**了：真实站点写成
#   `<img class="thumbnail" src="…" data-src="…">`（src 在前），
#   也会写成 `<img data-src="…" class="cover">`。
#   所以「筛标签」和「取属性」分成两步，不假设 src / data-src 谁先谁后。
#
# ⚠ 类名匹配**不能用 `\bcover\b`**：`\b` 在 `-` 和字母之间不成立，
#   于是 `book-cover` 能中但 `coverbox` 不中 —— 而后者恰恰是常见的
#   骨架类名。这里改成「显式分隔符 + 子串」，`cover`/`thumbnail`/`bookimg`
#   用子串匹配（宁可多认几个也别漏），再靠上面的占位图/尺寸校验兜住误判。
_COVER_IMG_RE = re.compile(
    r"""<img\b(?=[^>]*\b(?:class|id)\s*=\s*["'][^"']*(?:cover|thumbnail|bookimg|book_img|book-img)[^"']*["'])"""
    r"""[^>]*?>""",
    re.I,
)
_IMG_SRC_RE = re.compile(r"""\bsrc\s*=\s*["']([^"']+)["']""", re.I)
_IMG_LAZY_RE = re.compile(
    r"""\b(?:data-src|data-original|data-lazy-src|data-echo|data-url)\s*=\s*["']([^"']+)["']""",
    re.I,
)


def _img_inner(raw_tag: str) -> tuple[str, str]:
    """从 <img ...> 标签里取 (src, 懒加载真地址)。"""
    m = _IMG_SRC_RE.search(raw_tag)
    src = m.group(1) if m else ""
    m2 = _IMG_LAZY_RE.search(raw_tag)
    lazy = m2.group(1) if m2 else ""
    return src, lazy


# ---------------------------------------------------------------------------
# 页面级入口：给一个 URL，自己判断是详情页还是正文页
# ---------------------------------------------------------------------------
def analyze(url: str, *, log: Optional[Callable[..., None]] = None) -> dict:
    """抓一个页面并判断它是什么。

    返回::

        {"kind": "toc", "url":…, "final_url":…, "title":…, "author":…,
         "intro":…, "toc":[...], "quality": 0~1}
        {"kind": "chapter", "url":…, "final_url":…, "title":…, "content":…}
        {"kind": "unknown", "url":…, "final_url":…}

    判断完全靠内容 —— 章节链接够多、且像章节，就是目录页；
    正文够长就是正文页。

    `final_url` 是跟随重定向之后真实落地的地址。搜索引擎给的
    `/book/catalogue/349017/` 和站点自己的 `/book/x/349017/toc`
    其实是同一页，不去重就会出两张一模一样的卡片。
    """
    html, final_url = fetch_text(url, with_url=True)
    base = final_url or url
    host = host_of(base) or host_of(url)
    site = registry.known_site(host)

    toc = extract_toc(html, base, tpl_hint=site.get("toc_tpl") or "")
    meta = extract_meta(html)
    # 封面只在这里取一次，随 analyze 的返回值一起带出去 ——
    # 前端列表卡直接用，不必再为每本书单独打一次详情页。
    cover = extract_cover(html, base)
    # 站名顺手学一下（只学一次，`note_site` 里 name 为空才填）
    sname = extract_site_name(html)

    # —— 视频站否决（必须在 toc 判定**之前**）——
    # 见 _VIDEO_PATH_RE 注释：影视站的剧集列表会被误判成章节目录。
    # 这里判死了还要 `note_site(ok=False)`，否则下次还会来撞。
    #
    # 三档判据，从硬到软：
    #   ① 路径里就有 vod*/movie 这类苹果 CMS 特征词 —— 最硬，单独成立。
    #   ② 目录条目里 ≥60% 是「第N集/期/话」 —— 剧集列表，单独成立。
    #   ③ 站名带「影视/追剧」等词 —— **必须同时**有较多目录条目才生效。
    #      单靠站名太险：轻小说站常自称「XX动漫」，光看名字会误杀。
    _epn = sum(1 for c in toc if _EPISODE_TEXT_RE.search(str(c.get("title") or "")))
    _ep_ratio = (_epn / len(toc)) if toc else 0.0
    _bad_path = bool(_VIDEO_PATH_RE.search(base) or _VIDEO_PATH_RE.search(url))
    _bad_ep = len(toc) >= 8 and _ep_ratio >= 0.6
    _bad_name = bool(_VIDEO_NAME_RE.search(sname)) and len(toc) >= 8
    if _bad_path or _bad_ep or _bad_name:
        registry.note_site(host, ok=False, name=sname, why=registry.FAIL_VIDEO)
        return {
            "kind": "unknown", "url": url, "final_url": base, "host": host,
            "note": "影视站，不是小说站", "size": len(html),
        }

    if len(toc) >= 8:
        quality, why = toc_quality(toc)
        tpl = toc[0].get("_tpl", "") if toc else ""
        if quality >= 0.55:
            registry.note_site(host, ok=True, name=sname,
                               **({"toc_tpl": tpl} if tpl else {}))
            for c in toc:
                c.pop("_tpl", None)
            return {
                "kind": "toc", "url": url, "final_url": base, "host": host,
                "site_name": sname,
                "title": meta["title"], "author": meta["author"], "intro": meta["intro"],
                "cover": cover,
                "toc": toc, "quality": quality, "size": len(html),
            }
        registry.note_site(host, ok=False, name=sname, why=registry.FAIL_SHAPE)
        return {
            "kind": "unknown", "url": url, "final_url": base, "host": host,
            "note": why, "size": len(html),
        }

    content = extract_content(html, hint=site.get("content_hint") or "")
    body = clean_body(content)
    if len(body) >= 200:
        # 够长不代表是正文 —— 正版站的正文页能打开，但正文要登录或 JS 渲染，
        # 抽出来是一屏控件。这种必须判死，否则会显示「可读」然后一个字都读不到。
        if looks_like_ui_skeleton(body):
            registry.note_site(host, ok=False, name=sname, why=registry.FAIL_GATED)
            return {
                "kind": "unknown", "url": url, "final_url": base, "host": host,
                "note": "只拿到页面控件，正文要登录或 JS 渲染", "size": len(html),
            }
        hint = extract_content_hint(html) or site.get("content_hint") or ""
        registry.note_site(host, ok=True, name=sname,
                           **({"content_hint": hint} if hint else {}))
        return {
            "kind": "chapter", "url": url, "final_url": base, "host": host,
            "site_name": sname,
            "title": meta["title"], "content": body, "cover": cover, "size": len(html),
        }

    registry.note_site(host, ok=False, name=sname, why=registry.FAIL_SHAPE)
    return {"kind": "unknown", "url": url, "final_url": base, "host": host,
            "size": len(html)}
