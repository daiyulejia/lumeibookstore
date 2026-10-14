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

import base64
import logging
import re
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

from . import registry
from .utils import fetch_text, host_of

logger = logging.getLogger("novel.webfetch")

# 常见正文容器命名（命中了就不用走启发式，快很多也准很多）
# ⚠ 顺序即优先级。「最内层」的规律让靠前的名字能压住外层包装。
#
# `word_read` 是实测加的（2026-10-14，`www.zxs8.net`）：「17mb / black / bqg」
# 那套模板（大量笔趣阁克隆都在跑）正文容器就叫这个。不加的后果很具体 ——
# 它的外层 `<div class="container">` 字更多，密度打分会把整页导航一起选中，
# 每章正文开头都挂着面包屑和「上一章 章节目录 保存书签 下一章」。
_CONTENT_HINTS = ("htmlcontent", "chaptercontent", "readcontent", "word_read",
                  "content", "booktext", "textcontent", "showtxt", "article", "txt")

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

# ---------------------------------------------------------------------------
# 「章节链接是 JS 造的」这一类站
# ---------------------------------------------------------------------------
# 实测 `www.zxs8.net`（以及它用的那套「17mb / black / bqg」模板 —— 网上有
# 大量笔趣阁克隆都在跑同一份代码）：
#
#     <ul class="section-list fix ycxsid">
#       <li><a onclick="idm(816445);">第1章 喵</a></li>      ← 没有 href！
#       <li><a onclick="idm(816458);">第2章 喵喵</a></li>
#       ...
#
# 而页面底部自己把「章节地址长什么样」写在了一行内联脚本里：
#
#     var read_aid='3316'; var read_bid='3';
#     var read_rewrite='/{bid}_{aid}/{cid}.html';
#     function idm(id){ … read_rewrite.replace(/{cid}/,id) … window.open(…); }
#
# 于是整本书 119 章，我们只能读到 `<a href>` 的那 12 条（详情页的「最新章节」），
# 界面上显示「12 章」，用户下完才发现只有零头。
#
# **不猜**：模板是页面自己声明的，我们只做「填值 + 交叉验证」——
# 把模板里能由同名变量填上的槽位填掉，剩下**恰好一个**槽位就认为是章节号；
# 填出来的地址，其形状必须和页面上**真实存在的 href** 一致才采纳。
_A_TAG_RE = re.compile(r"""<a\s((?:[^>"']|"[^"]*"|'[^']*')*)>([\s\S]{0,120}?)</a>""", re.I)
_ONCLICK_CALL_RE = re.compile(
    r"""onclick\s*=\s*["'][^"']*?\([^()]*?(\d+)[^()]*?\)""", re.I)
_SCRIPT_RE = re.compile(r"<script\b(?![^>]*\bsrc\s*=)[^>]*>([\s\S]*?)</script>", re.I)
_JS_VAR_RE = re.compile(
    r"""(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*["']([^"'\r\n]*)["']""")
_JS_SLOT_RE = re.compile(r"\{([A-Za-z_$][\w$]*)\}")
#: 模板里那个「由链接自己决定」的槽位，替换成一个不会出现在 URL 里的哨兵。
_SLOT_SENTINEL = "\x00"

# ---------------------------------------------------------------------------
# 正文是 base64 写出来的那一类站
# ---------------------------------------------------------------------------
# 实测 `www.zxs8.net`（「17mb / black / bqg」那套模板 —— 大量笔趣阁克隆
# 都在跑同一份代码）的章节页：
#
#     <div class="word_read">
#       <script>document.writeln(kyvsbt.vz('PHA+54yr5ZKq55So5ZOB5bqX44CCPC9wPg=='));</script>
#       <script>document.writeln(kyvsbt.vz('PHA+5L2c5Li65a+55a6i5Lq66LSt5Lmw5aSn6YeP…'));</script>
#       …
#
# 也就是说**整页 HTML 里一个正文字符都没有** —— 正文是每一段单独 base64
# 之后由 JS 写进 DOM 的。任何「按文本密度找正文容器」的启发式都会失败，
# 我们只能抓到页脚那点「热门小说推荐」，然后判成「抓不到正文」。
#
# 这不是加密也不是反爬（base64 谁都会解），只是这种模板的默认写法 ——
# **该适配的是我们**。不解的话，整个模板家族的站都只能"看得到目录、读不到字"。
_WRITELN_RE = re.compile(
    r"""document\s*\.\s*write(?:ln)?\s*\(\s*"""
    r"""[A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*)*\s*\(\s*"""
    r"""["']([A-Za-z0-9+/=\s]{16,})["']\s*\)+\s*;?""",
    re.I)
_SCRIPT_BLOCK_RE = re.compile(r"<script\b[^>]*>([\s\S]*?)</script\s*>", re.I)
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
#: `xxx.html` → `xxx_2.html` 用的（阅读页续页地址）
# 阅读页页码后缀。⚠ 必须把**已有的** `_N` 一起吃掉（2026-10-14 踩到）：
#   旧写法 `^(.*?)(\.html?)$` 从第 2 页 `817762_1.html` 出发会生成
#   `817762_1_2.html`，而页面上声明的真实续页是 `817762_2.html` —— 永远对不上。
_PAGE_SUFFIX_RE = re.compile(r"^(.*?)(?:_(\d+))?(\.[a-z]+)$", re.I)


def _b64_text(s: str) -> Optional[str]:
    """base64 → 文本。解出来不像正文（没有汉字也没有标签）就返回 None。"""
    t = re.sub(r"[^A-Za-z0-9+/=]", "", s or "")
    if len(t) < 16:
        return None
    t += "=" * (-len(t) % 4)
    try:
        raw = base64.b64decode(t)
    except Exception:  # noqa: BLE001
        return None
    for enc in ("utf-8", "gbk"):
        try:
            txt = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if txt and ("<" in txt or _HAN_RE.search(txt)):
            return txt
    return None


def _decode_writeln_script(body: str) -> Optional[str]:
    """`<script>` 里除了 `document.write(...)` 什么都没写时，返回它写出来的 HTML。

    有别的语句就返回 None（那是一个正常脚本，不能碰）。
    """
    pos, out = 0, []
    for m in _WRITELN_RE.finditer(body or ""):
        if body[pos:m.start()].strip():
            return None
        txt = _b64_text(m.group(1))
        if txt is None:
            return None
        out.append(txt)
        pos = m.end()
    if (body or "")[pos:].strip():
        return None
    return "".join(out) if out else None


def unwrap_writeln(html: str) -> str:
    """把 `document.write(解码器('BASE64'))` 还原成它真正会写出来的 HTML。

    只替换**解得开、且解出来像文本**的那些；解不开就原样留着 ——
    宁可少还原，也不能把页面改坏（后面的正则会拿这份 HTML 继续干活）。

    ⚠ 必须**连 `<script>` 标签一起去掉**。第一版只换了调用本身，于是变成
      `<script><p>猫咪用品店。</p></script>` —— 而 `_prep()` 会把
      `<script>` 整段删掉（那是它对"脚本"的一贯处理），正文又被扔了。
      实测表现：正文只捞出 282 字导航文字，页面里明明有 2212 个汉字。
    """
    s = html or ""
    if "document.write" not in s:
        return s
    hits = 0

    def _whole_script(m: re.Match) -> str:
        nonlocal hits
        txt = _decode_writeln_script(m.group(1))
        if txt is None:
            return m.group(0)
        hits += 1
        return txt

    out = _SCRIPT_BLOCK_RE.sub(_whole_script, s)

    # 脚本块里混着别的语句（没被上面整块换掉）时的兜底：只换那个调用。
    def _call(m: re.Match) -> str:
        nonlocal hits
        txt = _b64_text(m.group(1))
        if txt is None:
            return m.group(0)
        hits += 1
        return txt

    out = _WRITELN_RE.sub(_call, out)
    if hits:
        logger.info("正文混淆：解开 %d 段 document.writeln(base64)", hits)
    return out


def _page_variant(url: str, n: int) -> Optional[str]:
    """`xxx.html` / `xxx_3.html` → `xxx_{n}.html`。推不出来返回 None。

    ⚠ **先把已有的 `_N` 剥掉再叠**，否则会 `_1_2` 这样套娃（见
      `_PAGE_SUFFIX_RE` 上面的注释）。这也让函数**幂等**：
      `_page_variant(_page_variant(u, 1), 1) == _page_variant(u, 1)`。
    """
    m = _PAGE_SUFFIX_RE.match(url or "")
    if not m:
        return None
    return f"{m.group(1)}_{n}{m.group(3)}"


def reading_next_url(html: str, base_url: str) -> Optional[str]:
    """阅读页自己声明的「**同一章的下一页**」地址。

    实测 zxs8：章节页用一行 JS 声明下一页 ——
        var hhekgv = '/3_3316/817762_1.html';
    这一个变量有两种含义，得靠地址区分：
      · `{本章地址}_N.html` → **本章的第 N+1 页**（要拼起来）
      · `{另一章}.html`     → 下一章的第一页（不需要，我们按目录逐章走）

    所以判据是「**它正好等于本章地址的 `_N` 变体**」，和变量叫什么都不相干。
    不这样收口的话，把「下一章」也当续页拼进来，就会出现每章尾部挂着
    下一章开头的怪书。

    ⚠ 只认**页码更大**的变体（无后缀 ≡ 第 1 页，即 `cur_n = 0`）。这一条同时
      排除两件事：**声明自己**（自循环，把同一页拼 N 遍）、**声明的"上一页"**
      （往回拼，同样只得到重复内容）。少了它，一章 3 页以上时第 3 页会拼不上，
      而界面上看不出来 —— 又是一次静默不完整。
    """
    m0 = _PAGE_SUFFIX_RE.match((base_url or "").split("#")[0])
    if not m0:
        return None
    cur_n = int(m0.group(2)) if m0.group(2) else 0
    want: dict[str, str] = {}
    for k in range(cur_n + 1, cur_n + 7):
        v = _page_variant(base_url, k)
        if v:
            want[v.rstrip("/")] = v
    for raw in [v for _n, v in _JS_VAR_RE.findall(html or "")]:
        u = urljoin(base_url, raw.strip()).split("#")[0].rstrip("/")
        if u in want:
            return want[u]
    return None


def fetch_reading_pages(
    url: str,
    fetch_one: Callable[[str], tuple[str, str]],
    *,
    max_pages: int = 6,
) -> str:
    """把「一章被拆成多页」的续页全都抓回来拼成一份正文。

    fetch_one(url) -> (正文, 该页 HTML)：正文怎么抽由调用方决定
    （配置来源用 `content_re`，联网发现用通用启发式）—— 拼接逻辑只写这一份。

    为什么必须拼（实测 zxs8 的 `第108章`）：
      第 1 页 2212 个汉字，续页还有 1760 个 —— **不拼就少了 44%**，
      而界面上一切正常，用户读完以为章节就是这么短。**静默的不完整
      比报错坏得多。**
    """
    body, html = fetch_one(url)
    parts = [body] if (body or "").strip() else []
    seen = {(body or "").strip()}
    cur_url, cur_html = url, html or ""
    for _ in range(max(0, max_pages - 1)):
        nxt = reading_next_url(cur_html, cur_url)
        if not nxt:
            break
        try:
            nb, nh = fetch_one(nxt)
        except Exception:  # noqa: BLE001
            break
        key = (nb or "").strip()
        # 页码越界时很多站会把上一页原样返回 —— 靠「内容没变」判断到底，
        # 不然就会把同一页拼 N 遍（实测 `_2.html` 就是返回第 1 页的内容）。
        if not key or key in seen:
            break
        seen.add(key)
        parts.append(nb)
        cur_url, cur_html = nxt, nh or ""
    return "\n\n".join(p for p in parts if p.strip())
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
#: 适配器的正文容器候选标签（见 `container_blocks`）。
_CONTAINER_TAGS = frozenset(("div", "section", "article", "td", "main"))


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


# ---------------------------------------------------------------------------
# 目录完整性 / 完整目录页
# ---------------------------------------------------------------------------
# 「最新更新 / 最新章节」这类说法后面跟着的章号 —— **页面自己说出的**"全书到第几章"。
# 只在页面上真有这种句子时才用；没有就不猜（见 toc_completeness 的第三条判据）。
_LATEST_CHAPTER_RES = (
    re.compile(r"(?:最近更新|最新更新|最新章节|最后更新|更新时间)[^第\n]{0,24}?"
               r"第\s*(\d{1,5})\s*[章节]"),
    re.compile(r"第\s*(\d{1,5})\s*[章节][^第\n]{0,16}?(?:已完结|已全本|完本|大结局)"),
    # ⚠ **章号在前**的写法也认（2026-10-14 实测 zxs8 才发现的漏洞）：
    #   那个站的详情页写的是「第119章 喵喵最新章节试读」—— 上面两条都要求
    #   关键词在前，于是**判据 C 在实际站点上从来没生效过**，而它是唯一能
    #   抓到「站点只收录了前一半」的判据。只因判据 A 先命中（目录从第 108 章
    #   开始）才没暴露；一旦目录恰好从第 1 章开始、又缺后半段，就完全失明。
    re.compile(r"第\s*(\d{1,5})\s*[章节][^第\n]{0,16}?(?:最新章节|最新更新)"),
)

#: 「去看完整目录」这类入口的链接文字。
#: ⚠ 必须**严格**。刻意**不收**「开始阅读 / 阅读全文 / 继续阅读」——
#:   它们常常直接指向**第一章**，跟进去会得到一个只有 1 条的"目录"，
#:   比原来的片段更坏（实测 zxs8 详情页上「开始阅读」「阅读全文」的 href
#:   一半指向 /mulu/、一半指向最新章节页，靠文字根本分不出来，宁可不收）。
_TOC_ENTRY_RE = re.compile(r"(完整目录|全部目录|全部章节|章节目录|目录)")


_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}

#: 章号藏在标题里。三种写法：阿拉伯数字、中文数字、以及「1. 标题」这种序号。
_CHAPTER_NUM_RES = (
    re.compile(r"第\s*(\d{1,5})\s*[章节回卷篇]"),
    re.compile(r"第\s*([零〇一二三四五六七八九十百千万两]{1,7})\s*[章节回卷篇]"),
    re.compile(r"^\s*(\d{1,5})\s*[.、]\s*\S"),
)


def _cn_to_int(s: str) -> Optional[int]:
    """中文数字 → int（「一百零三」→ 103）。认不出来返回 None。

    章节标题里中文数字很常见（「第十章」「第一百零三章」），
    不认它就会有整整一类站判不了目录齐不齐。
    """
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    total = section = number = 0
    for ch in s:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if unit == 10000:
                section = (section + number) * unit
                total += section
                section = number = 0
            else:
                section += (number or 1) * unit
                number = 0
        else:
            return None
    return total + section + number


def _chapter_num_of(title: str) -> Optional[int]:
    """从标题里读出章号（「第108章 喵喵」→ 108）。"""
    t = title or ""
    for i, rx in enumerate(_CHAPTER_NUM_RES):
        m = rx.search(t)
        if not m:
            continue
        v = _cn_to_int(m.group(1)) if i == 1 else None
        if v is None:
            try:
                v = int(m.group(1))
            except (TypeError, ValueError):
                v = None
        if v:
            return v
    return None


def chapter_numbers(chapters: list[dict]) -> list[int]:
    """目录条目对应的章节号 —— **优先看标题**，标题认不出来就不判（返回空）。

    为什么不能拿 URL 里的数字当章号（2026-10-14 踩到）：
      很多站的章节地址长这样 —— `www.zxs8.net/3_3316/816445.html`。
      那串数字是**章节 id**，不是章号。拿它去判「目录齐不齐」，
      会得出「目录从第 816445 章开始，前面应该还有」这种**胡话**；
      更糟的是**一份完整的目录也会被判成片段**（假警报），
      于是白白去跟一次「完整目录」入口，可能把好目录换坏。
      标题里的「第108章」才是页面**自己说出来的**章号，只认它。

    标题里认不出章号（多数条目标题长得不像章节）就返回空列表 ——
    **宁可漏报，不可乱报**（判不了的事不说，见 toc_completeness）。
    """
    if not chapters:
        return []
    out: list[int] = []
    miss = 0
    for c in chapters:
        v = _chapter_num_of(str(c.get("title") or ""))
        if v is None:
            miss += 1
            if miss > max(1, int(len(chapters) * 0.3)):
                return []        # 缺得太多，这一列章号不可信 → 不判
            continue
        out.append(v)
    return out if len(out) >= 3 else []


def toc_completeness(chapters: list[dict], html: str = "") -> tuple[bool, str]:
    """这个目录看起来**是不是只有一部分**？返回 (partial, 人话说明)。

    为什么必须有它（2026-10-14 线上实测踩到）：
      很多站的**详情页只挂「最新章节」十几条**，完整目录在另一个页面上。
      而 `toc_quality()` 拿这十几条去算会得到 **1.0** —— 它判的是
      "这像不像一串章节链接"，**不判"齐不齐"**。于是界面上显示"12 章"
      当作全书，用户下载完才发现只有零头。
      **这比"找不到"更坏：用户以为拿到了。**
      （实测 `www.zxs8.net/3_3316/`：《我们猫猫不能听这些》**全书 119 章**，
        详情页只列第 108–119 章共 12 条，而页面上明明挂着 `/3_3316/mulu/1.html`
        「章节目录」的入口 —— 我们从来没去点过。）

    判据三条，**判不了就不说**（宁可漏报，不能乱报）：
      A. 首项章号 > 1         → 这个列表不是从头开始的
      B. 章号跨度远大于条目数  → 中间缺了一大段（如 1, 101..109）
      C. 页面自己写了「最新章节为第 N 章」，而 N 大于目录里的最大章号
    C 是唯一能抓到「站点只收录了前一半」的判据（前两条都看不出来）。
    """
    nums = chapter_numbers(chapters)
    if len(chapters) >= 3 and not nums:
        return False, ""        # 标题不是「第N章」格式 → 判不了，不乱说
    top = 0
    if nums:
        lo, hi = min(nums), max(nums)
        top = hi
        # A 必须看**第一条自己的**章号，不能看 min(nums) ——
        # 中间某条标题认不出章号时 min 会被跳过，判据就跑到别的条目上去了。
        first = _chapter_num_of(str(chapters[0].get("title") or ""))
        if first and first > 1:
            return True, f"目录从第 {first} 章开始，前面应该还有"
        if hi - lo + 1 > len(nums) * 1.3:
            return True, f"只有第 {lo}–{hi} 章中的 {len(nums)} 章，中间有缺章"
    if html and top:
        for rx in _LATEST_CHAPTER_RES:
            m = rx.search(html)
            if not m:
                continue
            try:
                latest = int(m.group(1))
            except ValueError:
                break
            if latest > top:
                return True, f"站点显示最新章节是第 {latest} 章，这里只列到第 {top} 章"
            break
    return False, ""


def toc_entry_links(html: str, base_url: str, *, limit: int = 2) -> list[str]:
    """页面上「去看完整目录」的入口 —— **只收页面里真实存在的链接**。

    ⚠ 绝不猜地址（`/all.html`、`/dir/1_2.html` 这种）。实测教训：
      猜出来的地址返回 404，而**很多站的 404 页也长得像目录** ——
      实测某个 404 页面 `extract_toc` 吐出了 20 条假章节。
      一旦跟错，就会把一份干净的片段目录换成更脏的东西。
    """
    cur = base_url.rstrip("/")
    same_host = (urlparse(base_url).hostname or "").lower()
    out: list[str] = []
    for url, txt in _abs_links(_prep(html), base_url):
        if (urlparse(url).hostname or "").lower() != same_host:
            continue
        if url.rstrip("/") == cur:
            continue
        if not _TOC_ENTRY_RE.search(txt or ""):
            continue
        if url in out:
            continue
        out.append(url)
        if len(out) >= limit:
            break
    return out


#: 「下一页」的链接文字。**只认这些**，不认「开始阅读 / 阅读全文」——
#: 后者在详情页上一半指向目录、一半指向最新章节，跟错了会拿到更差的目录。
_NEXT_TEXT_RE = re.compile(r"(下一页|下页|后一页|下一章|»|›|&gt;|＞)")
_PREV_TEXT_RE = re.compile(r"(上一页|上页|前一页|首页|«|‹|&lt;|＜)")


def _next_page_url(html: str, base_url: str) -> Optional[str]:
    """页面上的「下一页」—— 只认**和当前页同一路径形状**的兄弟页。

    为什么必须限定形状：`/3_3316/mulu/1.html` 的「下一页」是
    `/3_3316/mulu/2.html`（`_template` 数字归一化后一致），
    而正文页底部的「下一页」指向下一章、形状也一样 ——
    所以还要求文字必须是「下一页」这几个词，且**很短**。
    """
    cur = base_url.rstrip("/")
    want = _template(base_url)
    for url, txt in _abs_links(_prep(html), base_url):
        if _template(url) != want:
            continue
        if url.rstrip("/") == cur:
            continue
        t = (txt or "").strip()
        if not t or len(t) > 6:
            continue
        if _PREV_TEXT_RE.search(t):
            continue
        if _NEXT_TEXT_RE.search(t):
            return url
    return None


def _order_chapters(chapters: list[dict]) -> list[dict]:
    """按章号重排（章号认不出来就保持原序 —— 至少顺序是页面给的）。"""
    nums = chapter_numbers(chapters)
    if len(nums) < 3 or len(nums) < len(chapters) * 0.7:
        return chapters
    # 章号只覆盖了一部分条目（中间有认不出的），那就别强行对齐索引
    if len(nums) != len(chapters):
        return chapters
    order = sorted(range(len(chapters)), key=lambda i: nums[i])
    if order == list(range(len(chapters))):
        return chapters
    return [chapters[i] for i in order]


def _merge_paged(
    toc: list[dict], html: str, base: str, *, budget: int = 5
) -> tuple[list[dict], str, int, bool]:
    """分页目录：跟着页面上的「下一页」把后面的页拼起来。

    返回 (目录, 落地地址, 新增条数, 还有没跟到的页)。

    为什么不能只跳一跳就完事（实测 zxs8）：
      「完整目录」`/3_3316/mulu/1.html` 只列第 1–100 章，
      第 101–119 章在 `/mulu/2.html`。只跳一跳的话，
      我们拿到的是「看起来完整、实际缺 19 章」的目录 ——
      **静默的不完整**，正是要消灭的那种错。
    所以：一直跟到「下一页」没了、或再也没有新章节为止（有上限，不会跑飞）。

    ⚠ 最后那个 `pending` 很关键：**页面上明明有「下一页」，但抓不到/抓回来
      是空的** —— 这时候必须让上层知道"可能还缺"，而不是假装完整。
      少这一位，"跟页失败"和"本来就是最后一页"就分不开了。
    """
    if not toc:
        return toc, base, 0, False
    want_tpl = toc[0].get("_tpl") or ""
    seen = {c.get("url") for c in toc if c.get("url")}
    merged = list(toc)
    cur_html, cur_base, got, pages, pending = html, base, 0, 0, False
    for _ in range(max(0, budget)):
        nxt = _next_page_url(cur_html, cur_base)
        if not nxt:
            break
        try:
            n_html, n_url = fetch_text(nxt, with_url=True)
        except Exception:  # noqa: BLE001
            pending = True
            break
        # min_items 放低到 3：最后一页常常只有两三章，不能被"至少 8 条"挡掉。
        n_toc = extract_toc(n_html, n_url, min_items=3)
        # 必须和已有目录**同一套地址模板** —— 否则就是把别的东西（推荐位、
        # 其它书）拼进来了。这是比数量更硬的判据。
        if want_tpl and n_toc and (n_toc[0].get("_tpl") or "") != want_tpl:
            break
        fresh = [c for c in n_toc if c.get("url") and c["url"] not in seen]
        if not fresh:
            break
        for c in fresh:
            seen.add(c["url"])
            merged.append(c)
        got += len(fresh)
        pages += 1
        cur_html, cur_base = n_html, n_url
    # 撞到预算上限、而页面上**还有**「下一页」→ 是我们自己停下，不是目录到头了。
    # 必须如实标"可能不全"，不能静默截断（>500 章的书曾经就这样少给）。
    if pages >= budget and _next_page_url(cur_html, cur_base):
        pending = True
        logger.info("目录分页：已达 %d 页上限，后面还有「下一页」，如实标注可能不全", budget)
    if got:
        merged = _order_chapters(merged)
        logger.info("目录分页：往后跟了 %d 页，合并后 %d 章", pages, len(merged))
    return merged, cur_base, got, pending


def upgrade_toc(toc: list[dict], html: str, base: str) -> tuple[list[dict], str, str]:
    """目录像"只有一部分"时：先跟一次「完整目录」入口，再把分页目录拼齐。

    返回 (目录, 落地地址, 提示)——提示非空表示"这份目录可能不全，为什么"。

    只做**一跳**到完整目录页、只认真实存在的链接、且**必须严格更完整**才替换。
    任何一步不确定就原样返回 —— 宁可少拿，也不能把好目录换坏。
    （反例：详情页上「开始阅读」「阅读全文」也指向 `/mulu/1.html`，
      但我们刻意不认这两个词，见 `_TOC_ENTRY_RE`。）
    """
    if not toc:
        return toc, base, ""

    partial, why = toc_completeness(toc, html)
    judge_html, page_html = html, html

    if partial:
        logger.info("目录可能不完整（%s）：%s", why, base)
        for cand in toc_entry_links(html, base):
            try:
                c_html, c_url = fetch_text(cand, with_url=True)
            except Exception:  # noqa: BLE001
                continue
            c_toc = extract_toc(c_html, c_url)
            # 门槛：条目数至少翻倍（够多才配叫"完整目录"）、
            #       自身质量过硬（挡住"404 页 / 推荐列表"那种假目录）、
            #       并且自己不能再是片段。
            if len(c_toc) < max(8, len(toc) * 2):
                continue
            q, _ = toc_quality(c_toc)
            if q < 0.8:
                continue
            if toc_completeness(c_toc, c_html)[0]:
                continue
            logger.info("目录增强：%s 跟到完整目录页 %s（%d → %d 章）",
                        base, c_url, len(toc), len(c_toc))
            toc, base, page_html = c_toc, c_url, c_html
            break

    # 分页拼齐。**即便没跟到新页面也要试** —— 因为分页的第 1 页看起来
    # 完全"正常"（第 1–100 章，首项就是第 1 章），判据 A/B/C 都发现不了
    # 它背后还有 19 章。这是"静默不完整"最隐蔽的一种。
    merged, m_url, got, pending = _merge_paged(toc, page_html, base)
    if got:
        m_partial, m_why = toc_completeness(merged, judge_html)
        # ⚠ 只要**真的多拿到了章节**，就必须用更全的那份，哪怕它仍被判定为
        #   片段 —— 曾经这里在 `m_partial` 时返回旧目录（把 101 章换成 12 章），
        #   等于"因为还没拼齐，所以连拼到的都不要了"。多的一定比少的好，
        #   不完整这件事靠 `m_why` 如实告诉用户，不靠少给章节来表达。
        toc, base = merged, m_url
        # ⚠ `pending` 也必须算"不全"：那是**我们自己的页数上限**把它停下的，
        #   不是目录到头了。只看 `m_partial` 的话，一本 600 章的书会被当成
        #   "目录完整"交付（又一处静默截断）。
        if pending:
            return toc, base, m_why or "这个站的目录分了页，还有几页没跟完，可能只含部分章节"
        if not m_partial:
            return toc, base, ""
        logger.info("目录分页：拼接后仍像片段（%s），保留更全的一份并如实提示", m_why)
        return toc, base, m_why
    if pending:
        # 有「下一页」却没跟到 → 如实说，别让用户以为这就是全书
        return toc, base, "这个站的目录分了页，后面几页没抓到，可能只含部分章节"
    # 走到这里：完整目录入口没跟到、分页也没跟到。目录**仍然**像片段的话
    # 必须把理由说出来 —— 沉默等于让界面把「12 条最新章节」显示成「全书」。
    still, why2 = toc_completeness(toc, judge_html)
    if still or partial:
        return toc, base, why2 or why or "这份目录可能不完整，只含部分章节"
    return toc, base, ""


def home_link(html: str, base_url: str) -> Optional[str]:
    """页面里回**站点首页**的入口（只在文字明确时采纳）。

    为什么要它：适配向导上写的是"填网站首页"，用户粘的却是某一本书的页面。
    **该适配的是我们**，不是让用户去理解这个约定 —— 书页上一定有回首页的
    入口（logo / 「首页」），跟着它回去就行。
    """
    same = (urlparse(base_url).hostname or "").lower()
    for url, txt in _abs_links(_prep(html), base_url):
        if (urlparse(url).hostname or "").lower() != same:
            continue
        # ⚠ 文字里可能有空格：「首  页」（实测 zxs8 就是两个空格）
        t = re.sub(r"\s+", "", txt or "")
        if t in ("首页", "主页", "网站首页", "回到首页", "返回首页", "小说首页"):
            return url
    return None


def _declared_url_rule(
    html: str, base_url: str, real_urls: list[str]
) -> Optional[str]:
    """页面自己在内联 JS 里声明的「章节地址模板」→ 带一个槽位的绝对 URL 模板。

    返回值形如 ``https://www.zxs8.net/3_3316/\\x00.html``，
    其中 `\\x00` 由链接自带的数字填进去。

    判据（全部满足才认，认不出就返回 None —— 不猜）：
      1. 模板字符串里带 `{xxx}` 槽位，且至少**能由一个同名变量填掉一个**
         （如 `{aid}` ← `read_aid='3316'`；同名按「变量名以 `_槽位名` 结尾」匹配）
      2. 填完之后**恰好剩一个**槽位 —— 那个就是链接自己带的章节号
      3. 把哨兵换成任意数字，得到的 URL **形状**必须和页面上某个真实
         `<a href>` 一致（`_template()` 数字归一化后相等）。
         这条是命门：没有它，一段无关的 JS 字符串就能被当成模板用。
    """
    scripts = "\n".join(_SCRIPT_RE.findall(html or ""))
    if "{" not in scripts:
        return None
    vals = {n: v for n, v in _JS_VAR_RE.findall(scripts)}
    if not vals:
        return None
    real_tpls = {_template(u) for u in real_urls}
    if not real_tpls:
        return None

    for value in vals.values():
        slots = list(dict.fromkeys(_JS_SLOT_RE.findall(value)))
        if not slots:
            continue
        filled, left = value, []
        for s in slots:
            got = _var_for_slot(vals, s)
            if got is None:
                left.append(s)
            else:
                filled = filled.replace("{" + s + "}", got)
        if len(left) != 1:
            continue
        cand = filled.replace("{" + left[0] + "}", _SLOT_SENTINEL)
        probe = urljoin(base_url, cand.replace(_SLOT_SENTINEL, "1"))
        if not probe.startswith("http"):
            continue
        if _template(probe) not in real_tpls:
            continue
        logger.info("章节地址模板：页面自报 %r → %s", value, cand)
        return urljoin(base_url, cand)
    return None


def _var_for_slot(vals: dict[str, str], slot: str) -> Optional[str]:
    """找一个变量来填 `{slot}` —— 名字对得上、且值是个纯数字。"""
    want = slot.lower()
    for name, val in vals.items():
        n = name.lower()
        if (n == want or n.endswith("_" + want)) and val.isdigit():
            return val
    return None


def _onclick_links(html: str, base_url: str, rule: str) -> list[tuple[str, str]]:
    """把 `onclick="idm(816445)"` 这种章节锚点还原成真实 URL。

    只处理**没有 href** 的锚点 —— 有 href 的已经由 `_abs_links` 收过了，
    再来一次只会重复。
    """
    out: list[tuple[str, str]] = []
    for attrs, inner in _A_TAG_RE.findall(html or ""):
        if re.search(r"\bhref\s*=", attrs, re.I):
            continue
        m = _ONCLICK_CALL_RE.search(attrs)
        if not m:
            continue
        url = urljoin(base_url, rule.replace(_SLOT_SENTINEL, m.group(1)))
        if not url.startswith("http"):
            continue
        out.append((url, re.sub(r"\s+", " ", _text_of(inner))))
    return out


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
    doc = _prep(unwrap_writeln(html))
    links = _abs_links(doc, base_url)
    # 章节链接是 JS 造的（`onclick="idm(816445)"`）时，把页面**自己声明**的
    # 地址模板拿来补回这批链接。见 _declared_url_rule 的注释 ——
    # 不补的话，zxs8 那种站整本书只能读到 12 条「最新章节」。
    # ⚠ 模板要从**原始 html** 里读（脚本已经被 _prep 删掉了）。
    rule = _declared_url_rule(html, base_url, [u for u, _ in links])
    if rule:
        extra = _onclick_links(doc, base_url, rule)
        if extra:
            logger.info("目录来源：onclick 章节链接 +%d 条（%s）",
                        len(extra), extra[0][0])
            links = links + extra
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

    seen: dict[str, int] = {}
    chapters: list[dict] = []
    for url, txt in items:
        title = _clean_chapter_title(txt)
        if url in seen:
            # 同一个地址出现两次时**留下标题更好的那条**。
            # 实测 zxs8 的目录页：第一条是「开始阅读」按钮（href 指向第 1 章），
            # 而第 1 章自己那条在 onclick 里、标题是真的「第1章 喵」。
            # 谁先谁后取决于链接在页面里的位置，不能靠"先到先得"。
            i = seen[url]
            if _is_nav_title(chapters[i]["title"]) and not _is_nav_title(title):
                chapters[i]["title"] = title
            continue
        seen[url] = len(chapters)
        chapters.append({"url": url, "title": title})

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
def _div_blocks(
    html: str, tags: frozenset[str] = _DIV_TAGS
) -> list[tuple[str, str]]:
    """切出所有 `<tag …>…</tag>`，返回 (开标签, 内容)。

    用一遍扫描 + 栈配对，而不是对每个 div 重跑正则 ——
    详情页动辄 50 万字符、上万个 div，逐层重扫会慢一个数量级。
    """
    doc = _drop_link_paras(_prep(html))
    stack: list[list] = []
    out: list[tuple[str, str]] = []
    for m in _ANY_BLOCK.finditer(doc):
        closing, tag, _attrs, selfclose = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if tag not in tags or selfclose or tag in _VOID_TAGS:
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


def container_blocks(html: str) -> list[tuple[str, str]]:
    """正文容器扫描：div / section / article / td / main，**支持任意嵌套**。

    为什么要单列一个（2026-10-14）：适配器里原先用
    `<div[^>]*>([\\s\\S]{200,80000}?)</div>` 这种**非贪婪**正则扫容器，
    一旦容器里还套着 div（`word_read` 里就套着 `read_btn`），
    它只会取到**第一个 `</div>` 之前**的一小截 —— 正文全被截掉，
    于是"推导正文正则"永远失败。栈式扫描不存在这个问题。
    """
    return _div_blocks(html, _CONTAINER_TAGS)


#: 站点的「相邻推荐 / 猜你喜欢」—— 一整段只有书名链接。
#: 实测 zxs8 的原文长这样（而且就写在**正文容器里面**）：
#:     <p style="font-size:12px;">相邻推荐:<a href="/3_3314/">都市之超能警探</a>
#:     &nbsp;<a …>穿成总裁蚊子血[穿书]</a>&nbsp;…（一共 20 条）</p>
#: 不删的话，正文尾巴上会挂着 20 个别的书名 —— 用户读着读着就串了书。
_A_FULL_RE = re.compile(r"<a\b[^>]*>[\s\S]{0,60}?</a>", re.I)
_PARA_RE = re.compile(r"<p\b[^>]*>([\s\S]{0,6000}?)</p>", re.I)


def _drop_link_paras(html: str) -> str:
    """丢掉「整段只有一个书名列表」的 `<p>`。

    判据：段内链接 ≥3 个，**且**除掉这些链接之后几乎没有自由文字
    （≤8 字 —— 正好容下「相邻推荐:」这种标签词）。

    ⚠ **只认 `<p>`**：目录站大量用 `<div>` / `<li>` 逐条列章节
      （`<li><a href=…>第1章</a></li>`），一旦把"只含链接的块"当推荐删掉，
      整本书的目录会被清空。而且这个函数只服务于**正文**链路
      （`_div_blocks` → `extract_content` / `container_blocks`），
      不经手 `extract_toc`。
    """
    dropped = 0

    def repl(m: re.Match) -> str:
        nonlocal dropped
        inner = m.group(1)
        if len(_A_RE.findall(inner)) < 3:
            return m.group(0)
        rest = re.sub(r"<[^>]+>", "", _A_FULL_RE.sub("", inner))
        rest = re.sub(r"[\s\u3000]+", "", rest.replace("&nbsp;", ""))
        if len(rest) > 8:
            return m.group(0)
        dropped += 1
        return ""

    out = _PARA_RE.sub(repl, html or "")
    if dropped:
        logger.info("正文清洗：丢掉 %d 段「只有书名链接」的推荐位", dropped)
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
    # 正文可能是 base64 + document.writeln 写出来的（见 unwrap_writeln）——
    # 必须先还原，否则整页 HTML 里一个正文字符都没有。
    html = unwrap_writeln(html)
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
    html = unwrap_writeln(html)
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
         "intro":…, "toc":[...], "quality": 0~1,
         "partial": bool, "chapter_note": str}   ← 目录是不是只有一部分、为什么
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
    # 详情页常常只挂「最新章节」十几条 —— 目录像"只有一部分"时，
    # 去点一次页面上「完整目录」的入口，并把分页目录拼齐。
    # 见 upgrade_toc 的注释。
    toc, base, toc_note = upgrade_toc(toc, html, base)
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
            # 目录"看起来不完整"时要**如实说出来**（见 toc_completeness）：
            # 否则界面把「12 章」当全书，用户下完才发现只有零头 —— 那比搜不到更坏。
            partial, chapter_note = toc_completeness(toc, html)
            if toc_note and not chapter_note:
                partial, chapter_note = True, toc_note
            return {
                "kind": "toc", "url": url, "final_url": base, "host": host,
                "site_name": sname,
                "title": meta["title"], "author": meta["author"], "intro": meta["intro"],
                "cover": cover,
                "toc": toc, "quality": quality, "size": len(html),
                "partial": partial, "chapter_note": chapter_note,
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
