"""站点学习：从一个已知能用的书页，反推这个站的「站内搜索接口」怎么拼。

要解决什么
----------
来源库（`app/registry.py`）原本只记「书」—— 哪本书在哪个 URL。
所以搜过一本书之后，**同一个站里的另一本书仍然搜不到**：库里没有它的书页，
而那个站的搜索接口我们没记。于是每次换一本书都要重新出去走一趟搜索引擎。

这一步补上缺的那环：**走过一次，就把这个站的搜索能力也学下来。**

    「我们搜的越多，你从网络上能够找到更多的源，类似给你间接给 L 源提供源」
    —— 用户原话

学什么
------
一个站的搜索接口无非是两个事实：

    · **URL 模板**：`https://www.29zw.com/search.php?q={kw}` 还是
      `https://m.dquanben.com/search/?keyword={kw}` —— 只差**路径和参数名**
    · **编码**：参数值是把关键词原样塞进去（UTF-8）还是 GBK 转义（%C9%FA...）

拿到这两样，就能拿**任意**关键词去搜这个站，不用再问搜索引擎。

怎么学（三个来源，从可靠到兜底）
--------------------------------
1. **HTML 的 `<form>`**：站内搜索框本来就是给用户填关键词用的，
   form 的 action + input[name] 就是现成的答案。**最可靠**。
2. **常见搜索路径爆破**：拿一个已知关键词（书名）去试
   `/search.php?q=`、`/search?keyword=`、`/s?q=` 等一批候选，
   看哪个回的内容里**有章节链接**（复用 `webfetch.extract_toc`）。
3. **首页的搜索链接**：有些站搜索是 GET 链接而不是 form
   （`<a href="/search.php?q=">`）。

只有 1、3 是「零成本」的（页面已经抓在手上了）。2 要额外发请求，
所以只在 `discover()` 里对**已经验证可用的站**做，且只做一次。

为什么不能拿任意关键词搜「没有搜索接口」的站
--------------------------------------------
同一批站里有的是纯静态站（比如某些老盗版站，只有 `/book/1234/` 这种路径，
搜索要么没有、要么在 Cloudflare 后面）。这种站学不出模板，
下次仍然要靠搜索引擎 —— 那就记一个 `search_fail`，
别每次重复爆破，浪费那十几个请求的预算。
"""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse, quote

logger = logging.getLogger("novel.sitelearn")

# ---------------------------------------------------------------------------
# 搜索 URL 的常见形态
# ---------------------------------------------------------------------------
# 参数名候选：按「命中率」排，前面几个是中文小说站里最普遍的。
# 顺序有意义 —— 爆破时按顺序试，先命中的先赢。
SEARCH_PARAMS = (
    "q", "keyword", "kw", "wd", "searchkey", "search_key", "key",
    "word", "s", "query", "searchword", "search", "name", "title",
)

# 路径候选：拼在 host 后面的部分。
SEARCH_PATHS = (
    "/search.php", "/search.html", "/search/", "/search",
    "/so.php", "/so/", "/so", "/s.php", "/s/", "/s",
    "/modules/article/search.php",       # 老笔趣阁系（杰奇CMS）—— 实测 29zw 就用它
    "/e/search/", "/e/search/index.php",
    "/index.php?m=search",               # 部分 CMS 的 GET 路由
    "/plus/search.php",                  # 帝国CMS
    "/?s=", "/?q=", "/?search=",         # WordPress / 极简站
)

# 杰奇 CMS 系的经典组合：`/modules/article/search.php?searchkey=XXX`。
# 单列出来是因为它和上面的「路径 × 参数名」交叉表对不上（那个表只交叉
# 前几个简短路径），而这个组合实测命中率极高 —— 老笔趣阁站基本都是它。
_JIECI_COMBOS = (
    ("/modules/article/search.php", "searchkey"),
    ("/modules/article/search.php", "q"),
    ("/modules/article/search.php", "keyword"),
    ("/e/search/index.php", "keyboard"),
    ("/e/search/index.php", "searchkey"),
)

# form 里不该当搜索框的输入（登录、订阅、评论…）
_BAD_PARAM = re.compile(
    r"^(password|passwd|pwd|user|username|email|mail|code|captcha|verify|"
    r"token|csrf|submit|action|do|go|button|type|id|page|p)$",
    re.I,
)

_FORM_RE = re.compile(r"<form\b([^>]*)>([\s\S]*?)</form\s*>", re.I)
_FORM_ACTION_RE = re.compile(r"""action\s*=\s*["']([^"']*)["']""", re.I)
_FORM_METHOD_RE = re.compile(r"""method\s*=\s*["']([^"']*)["']""", re.I)
_INPUT_RE = re.compile(
    r"""<input\b([^>]*?)/?>""", re.I)
_ATTR_RE = re.compile(r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*["']([^"']*)["']""")
# 搜索链接（GET 形态的搜索入口）
_SEARCH_LINK_RE = re.compile(
    r"""<a\b[^>]*href\s*=\s*["']([^"']*(?:search|so\.php|/s\?)[^"']*)["'][^>]*>"""
    r"""([\s\S]{0,60}?)</a>""", re.I)

# 「这个链接看起来像搜索入口」
_SEARCHISH = re.compile(r"(search|/so\.php|/s\?|[?&](q|wd|kw|keyword|key)=)", re.I)


# ---------------------------------------------------------------------------
# JS 里内联的搜索表单
# ---------------------------------------------------------------------------
# ⚠ 这是实测踩出来的一个**大坑**：很多中文小说站（尤其杰奇 CMS 系的
#   老站）的搜索框不是写在 HTML 里的，而是用脚本 document.write 出来的：
#
#     function searchBox(){document.writeln(
#       "<form action='/modules/article/search.php' target='_blank'>...
#        <input type='text' ... name='searchkey'>...</form>");}
#
#   于是「从 HTML 里找 <form>」永远找不到 —— 静态 HTML 里根本没有 form。
#   实测 www.29zw.com 就是这样，而它的搜索接口完全可用
#   （`/modules/article/search.php?searchkey=XXX`）。
#
#   修法：把内联脚本里的 `action='...'` / `name='...'` 也当成线索。
#   注意脚本里的引号可能是单引号、也可能被转义（`\'`），都要认。
_JS_ACTION_RE = re.compile(
    r"""action\s*=\s*(?:\\?["'])([^"'\\]+)(?:\\?["'])""", re.I)
_JS_NAME_RE = re.compile(
    r"""name\s*=\s*(?:\\?["'])([^"'\\]+)(?:\\?["'])""", re.I)
_SCRIPT_RE = re.compile(r"<script\b[^>]*>([\s\S]*?)</script\s*>", re.I)
# 「这是一整份 JS 文件」的证据：它自己在往页面里写 HTML。
_JS_WRITE_RE = re.compile(r"document\s*\.\s*writ(?:e|eln)\s*\(", re.I)


def learn_from_scripts(html: str, page_url: str, host: str) -> list[dict]:
    """从内联脚本（或一整份 JS 文件）里挖「被 JS 写出来的搜索表单」。

    只在脚本同时出现 `action=` 和一个像搜索框的 `name=` 时才认 ——
    否则脚本里到处都是 action/name，噪声太大。
    """
    out: list[dict] = []
    seen: set[str] = set()
    text = html or ""

    # 先把 <script> 块抠出来。一个都没抠到、**且输入里也没有 HTML 结构标签**时，
    # 才当成「传进来的本身就是 JS 文件」。
    #
    # ⚠ 这个判据是必需的：早先只要「没抠到 <script>」就把整段当 JS，结果一段
    #   普通的 `<form action="/search.php">` HTML 被 form 分支和 script 分支
    #   各收一次 —— 同一个模板出两条候选。
    #   判据用「有没有 HTML 结构标签」而不是「有没有 `<`」，因为 JS 里
    #   写 `document.writeln("<form ...>")` 时字符串里也有 `<`。
    blocks = [m.group(1) or "" for m in _SCRIPT_RE.finditer(text)]
    if not blocks:
        # 没有 <script> 块时，怎么判断「这是裸 JS」？
        # 判据收得很紧：**必须真的在 document.write/writeln 一段表单**，
        # 否则一律当成 HTML（交给上面的 form/link 分支处理）。
        #
        # 为什么不用「含不含 <html>/<body>」这种宽判据：
        #   一段 `<form action="/search.php" method="post">…` 的 HTML 片段
        #   既没有 `<script>` 也没有 `<html>`，宽判据会把它误认成裸 JS，
        #   于是同一个模板被 form 和 script 分支各收一次（实测踩过）。
        if not _JS_WRITE_RE.search(text):
            return []
        blocks = [text]

    for code in blocks:
        # 只关心「像在做搜索框」的脚本
        if not _SEARCHISH.search(code) and "search" not in code.lower():
            continue
        acts = _JS_ACTION_RE.findall(code)
        names = [_n for _n in _JS_NAME_RE.findall(code)
                 if _n and not _BAD_PARAM.match(_n)]
        if not acts or not names:
            continue
        # 取「最像搜索」的那个参数名
        names.sort(key=lambda n: (0 if re.search(r"search|keyword|key|word|kw", n, re.I) else 1, len(n)))
        for action in acts:
            if not re.search(r"(search|so\.php|/s\b|plus/|e/search)", action, re.I):
                continue
            tpl = make_tpl(host, action)
            if not tpl:
                continue
            sep = "&" if "?" in tpl else "?"
            full = f"{tpl}{sep}{names[0]}={{kw}}"
            if full in seen:
                continue
            seen.add(full)
            out.append({"tpl": full, "enc": "utf-8", "via": "script", "method": "get"})
    return out


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
def make_tpl(host: str, path_qs: str) -> str:
    """把「路径 + 查询串」做成模板：关键词的位置换成 `{kw}`。

    `host` 单独存（registry 的键已经是 host 了），模板只存 host 之后的部分，
    这样站换了 www / m 子域也能靠改 host 复用。
    """
    p = (path_qs or "").strip()
    if not p:
        return ""
    if p.startswith("http://") or p.startswith("https://"):
        u = urlparse(p)
        p = u.path + (("?" + u.query) if u.query else "")
    if not p.startswith("/"):
        p = "/" + p
    return p


def build_url(tpl: str, host: str, keyword: str, *, enc: str = "utf-8",
              scheme: str = "https") -> str:
    """把模板 + 关键词拼成一个能直接请求的 URL。"""
    tpl = (tpl or "").strip()
    host = (host or "").strip()
    if not tpl or not host:
        return ""
    if enc and enc.lower() in ("gbk", "gb2312", "gb18030"):
        kw = quote(keyword, encoding="gb18030")
    else:
        kw = quote(keyword, encoding="utf-8")
    path = tpl.replace("{kw}", kw)
    # 模板本来就是完整 URL 时**直接用**，别再往 host 后面拼。
    # 学习链路存的都是路径形（/search.php?q={kw}），但这个函数是公共入口，
    # 拿到完整 URL 一旦拼错就是 `https://host/https://...` —— 请求必 404，
    # 而且记进 fail_down，把一个能用的站慢慢拖进"不健康"。
    if re.match(r"^https?://", tpl, re.I):
        return path
    base = f"{scheme}://{host}"
    if not path.startswith("/"):
        path = "/" + path
    return base + path


# ---------------------------------------------------------------------------
# 从 HTML 里学
# ---------------------------------------------------------------------------
def _attrs(chunk: str) -> dict:
    return {k.lower(): v for k, v in _ATTR_RE.findall(chunk or "")}


def learn_from_html(html: str, page_url: str, host: str) -> list[dict]:
    """从一页 HTML 里找搜索入口。返回候选列表（可能多个，交给调用方验证）。

    每条::

        {"tpl": "/search.php?s={kw}", "enc": "gbk", "via": "form", "method": "get"}
        {"tpl": "/search.php", "enc": "utf-8", "via": "form-post", "method": "post",
         "body": {"s": "{kw}"}}          # POST 搜索（关键词在请求体里）

    只提取**看起来像站内搜索**的 form / 链接。返回空列表 = 这页没有搜索入口。
    """
    out: list[dict] = []
    seen: set[str] = set()
    html = html or ""

    # ---- 1) <form> ----
    for m in _FORM_RE.finditer(html):
        head, body = m.group(1), m.group(2)
        ha = _attrs(head)
        method = (ha.get("method") or "get").lower()
        action = ha.get("action") or ""
        # 找到 form 里那个「文本输入框」
        param = ""
        for im in _INPUT_RE.finditer(body):
            ia = _attrs(im.group(1))
            typ = (ia.get("type") or "text").lower()
            name = (ia.get("name") or "").strip()
            if not name or typ not in ("text", "search", ""):
                continue
            if _BAD_PARAM.match(name):
                continue
            param = name
            break
        if not param:
            continue
        # action 可能是空串（提交到本页）—— 那就用当前页路径
        if not action:
            action = urlparse(page_url).path or "/"
        tpl = make_tpl(host, action)
        if not tpl:
            continue

        if method == "post":
            # POST 搜索：关键词在请求体。模板存 URL、body 里放 `{kw}`。
            # 实测 384g 就是这种（`POST /search.php  s=…`）。
            key = f"POST {tpl}#{param}"
            if key in seen:
                continue
            seen.add(key)
            out.append({"tpl": tpl, "enc": "utf-8", "via": "form-post",
                        "method": "post", "body": {param: "{kw}"}})
            continue

        key2 = f"GET {tpl}#{param}"
        if key2 in seen:
            continue
        seen.add(key2)
        sep = "&" if "?" in tpl else "?"
        out.append({"tpl": f"{tpl}{sep}{param}={{kw}}", "enc": "utf-8",
                    "via": "form", "method": "get"})

    # ---- 2) 搜索链接 ----
    for href, text in _SEARCH_LINK_RE.findall(html):
        href = (href or "").strip()
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue
        if not _SEARCHISH.search(href):
            continue
        absu = urljoin(page_url, href)
        u = urlparse(absu)
        if (u.hostname or "").lower() != (host or "").lower():
            # 跳到别的域名（比如站群）——先不学，免得把外站当自己的搜索
            continue
        tpl = make_tpl(host, u.path + (("?" + u.query) if u.query else ""))
        if not tpl or "{kw}" in tpl.replace("{kw}", ""):
            continue
        # 链接里已经带了示例关键词（/s?q=都市）→ 把值抠出来换成 {kw}
        tpl = _replace_value_with_kw(tpl)
        if not tpl or tpl in seen:
            continue
        seen.add(tpl)
        out.append({"tpl": tpl, "enc": "utf-8", "via": "link", "method": "get"})

    # ---- 3) 内联脚本里被 document.writeln 出来的表单 ----
    # 放在最后追加：它的证据强度不如真 HTML form，但比纯猜强。
    for c in learn_from_scripts(html, page_url, host):
        if c["tpl"] not in seen:
            seen.add(c["tpl"])
            out.append(c)

    return out


_KV_RE = re.compile(r"([?&])([a-zA-Z_][-a-zA-Z0-9_]*)=([^&]*)")


def _replace_value_with_kw(tpl: str) -> str:
    """把 `/s?q=%E9%83%BD%E5%B8%82` 变成 `/s?q={kw}`。

    只替换**第一个非空、非分页/排序**的参数值 —— 搜索链接里通常只有一个
    真正的查询参数（另一个可能是 `page=1` 之类）。
    """
    if "{kw}" in tpl:
        return tpl
    m = _KV_RE.search(tpl)
    while m:
        name, val = m.group(2), m.group(3)
        if val and not _BAD_PARAM.match(name) and name.lower() not in ("page", "p", "pageno", "order", "sort"):
            return tpl[:m.start(3)] + "{kw}" + tpl[m.end(3):]
        m = _KV_RE.search(tpl, m.end())
    return ""


def guess_templates(host: str) -> list[dict]:
    """爆破候选：常见搜索路径 × 常见参数名。

    这些是**没有证据的猜测**，必须一个个发请求验证（靠 `verify_tpl`）。
    排在前面的是中文小说站里命中率最高的组合，先试中的先赢。
    """
    out: list[dict] = []
    seen: set[str] = set()
    # 参数名优先用高频的，路径也用高频的 —— 交叉时按路径分组，
    # 让「/search.php?q=」这种经典组合排最前。
    for path in SEARCH_PATHS:
        if path.endswith("="):
            # `/?q=` 这种路径本身带参数名
            tpl = path + "{kw}"
        elif "?" in path:
            sep = "&" if path.endswith(("?", "&")) else "&"
            tpl = f"{path}{sep}q={{kw}}"
        else:
            tpl = f"{path}?q={{kw}}"
        if tpl not in seen:
            seen.add(tpl)
            out.append({"tpl": tpl, "enc": "utf-8", "via": "guess", "method": "get"})
    # 再补一批「路径 + 其它参数名」的组合（只在经典路径上换参数名）
    for path in ("/search.php", "/search", "/search/", "/so.php", "/s"):
        for pname in ("keyword", "kw", "wd", "searchkey", "key", "searchword", "s"):
            tpl = f"{path}?{pname}={{kw}}"
            if tpl not in seen:
                seen.add(tpl)
                out.append({"tpl": tpl, "enc": "utf-8", "via": "guess", "method": "get"})
    # 杰奇 CMS 系（老笔趣阁）的经典组合，单独优先补进去
    for path, pname in _JIECI_COMBOS:
        tpl = f"{path}?{pname}={{kw}}"
        if tpl not in seen:
            seen.add(tpl)
            out.append({"tpl": tpl, "enc": "utf-8", "via": "guess", "method": "get"})
    return out


# ---------------------------------------------------------------------------
# 验证一个模板到底能不能搜
# ---------------------------------------------------------------------------
def verify_tpl(tpl: str, host: str, probe_keyword: str, *,
               enc: str = "utf-8", scheme: str = "https",
               method: str = "get", body: Optional[dict] = None,
               min_hits: int = 3) -> Optional[int]:
    """拿探测词去请求一次，回内容里有章节链接就算成。

    返回命中的章节链接数（够多才算真的搜到了）；不成立返回 None。

    判据用「有没有一堆看起来像章节的链接」而不是「页面里有没有关键词」——
    很多站搜不到时会**回首页**（首页当然有链接，但那是导航不是结果），
    只数关键词会把它误判成成功。
    """
    from . import webfetch        # 延迟导入：避免启动期的循环依赖
    from .utils import fetch_text

    url = build_url(tpl, host, probe_keyword, enc=enc, scheme=scheme)
    if not url:
        return None

    data = None
    if (method or "get").lower() == "post":
        # POST 搜索：关键词放请求体，URL 里不带参数
        data = {k: str(v).replace("{kw}", probe_keyword)
                for k, v in (body or {"s": "{kw}"}).items()}
        # URL 去掉 `?…` 部分（POST 的 tpl 本来就没带）
        url = build_url(tpl, host, "", enc=enc, scheme=scheme) or url

    try:
        html, final = fetch_text(url, with_url=True, data=data)
    except Exception as e:  # noqa: BLE001
        logger.debug("搜索模板验证失败 %s: %s", url, e)
        return None
    if not html or len(html) < 400:
        return None

    # 跟随重定向后掉回首页 → 这个模板是假的「能搜」
    fp = urlparse(final or url)
    fpath = (fp.path or "/").rstrip("/")
    if fpath in ("", "/", "/index.php") and fp.query == "":
        return None

    try:
        toc = webfetch.extract_toc(html, final or url)
    except Exception:  # noqa: BLE001
        return None
    n = len(toc or [])
    if n < min_hits:
        return None
    return n


def detect_encoding(host: str, tpl: str, probe_keyword: str, *, scheme: str = "https",
                    method: str = "get", body: Optional[dict] = None) -> str:
    """判断这个站该用 UTF-8 还是 GBK 传关键词。

    做法：用 utf-8 拼一次请求，如果**回内容里没有探测词的任何字符**，
    再试 gb18030（GBK 超集）。中文老站大量是 GBK 的，
    关键词编码错了站方就搜不到、返回空 —— 这一点必须探。

    返回 "utf-8" 或 "gb18030"。
    """
    for enc in ("utf-8", "gb18030"):
        try:
            n = verify_tpl(tpl, host, probe_keyword, enc=enc, scheme=scheme,
                           method=method, body=body)
        except Exception:  # noqa: BLE001
            continue
        if n:
            return enc
    return "utf-8"


# ---------------------------------------------------------------------------
# 总入口：学一个站
# ---------------------------------------------------------------------------
def learn_site(
    host: str,
    *,
    page_url: str = "",
    html: str = "",
    probe_keyword: str = "",
    allow_guess: bool = True,
    scheme: str = "https",
    budget: int = 6,
    js_budget: int = 2,
) -> dict:
    """学一个站的搜索能力。返回学到的配置；学不到返回空 dict。

    · `html` + `page_url`：手上有现成的页面时用（零成本，只在其中找 form / 链接）
    · `allow_guess=True`：还可以爆破常见路径（要发请求，`budget` 限制次数）
    · `js_budget`：最多再去读几个外部 JS 文件找 JS 写出来的搜索框

    返回::

        {"search_tpl": "/search.php?q={kw}", "search_enc": "gbk",
         "search_via": "form", "search_at": 1760000000}
    """
    host = (host or "").strip().lower()
    if not host:
        return {}

    tried: set[str] = set()
    cands: list[dict] = []

    # 1) 现有 HTML（免费）
    if html and page_url:
        cands.extend(learn_from_html(html, page_url, host))

    # 2) 外部 JS 文件（很便宜 —— 一个请求，命中率却很高）
    #    很多站的搜索框是 `searchBox()` 这种函数 write 出来的，
    #    静态 HTML 里根本没有 form（实测 29zw 就是）。
    if html and page_url and js_budget > 0:
        cands.extend(_learn_from_external_js(html, page_url, host, js_budget))

    # 3) 爆破（付得更多，要发好几个请求）
    guessed = guess_templates(host) if (allow_guess and probe_keyword) else []

    # 先验证「有证据」的候选：它们命中率远高于猜的
    ordered = cands + guessed
    n_req = 0
    for c in ordered:
        tpl = c.get("tpl") or ""
        if not tpl or tpl in tried:
            continue
        tried.add(tpl)
        if n_req >= budget:
            break
        n_req += 1
        method = c.get("method", "get")
        body = c.get("body")
        enc = (detect_encoding(host, tpl, probe_keyword, scheme=scheme,
                               method=method, body=body)
               if probe_keyword else "utf-8")
        hits = (verify_tpl(tpl, host, probe_keyword, enc=enc, scheme=scheme,
                           method=method, body=body)
                if probe_keyword else None)
        if hits is None and not probe_keyword:
            # 没有探测词就没法验证 —— 只把 form 学到的当候选，交给上层再定
            if c.get("via") in ("form", "form-post"):
                got = {"search_tpl": tpl, "search_enc": enc,
                       "search_via": c["via"]}
                if method == "post":
                    got["search_method"] = "post"
                    got["search_body"] = body
                return got
            continue
        if hits:
            got = {"search_tpl": tpl, "search_enc": enc,
                   "search_via": c.get("via", "")}
            if method == "post":
                got["search_method"] = "post"
                got["search_body"] = body
            return got

    return {}


_SCRIPT_SRC_RE = re.compile(
    r"""<script\b[^>]*\bsrc\s*=\s*(?:\\?["'])([^"'\\]+)(?:\\?["'])""", re.I)


def _learn_from_external_js(html: str, page_url: str, host: str,
                            budget: int = 2) -> list[dict]:
    """抓站点的 JS 文件，从里面找被 write 出来的搜索表单。

    只挑「名字像搜索」的 JS 先抓（`search*.js` / `book.js` / `common.js`），
    抓不到就算了 —— 这只是一条**加分线**，不成立也不影响 form/爆破那两条。
    """
    from .utils import fetch_text
    out: list[dict] = []
    srcs: list[str] = []
    for src in _SCRIPT_SRC_RE.findall(html or ""):
        src = (src or "").strip()
        if not src or src.startswith(("http://", "https://")):
            if src.startswith(("http://", "https://")) and host in src:
                srcs.append(src)
            continue
        srcs.append(urljoin(page_url, src))
    # 「名字像搜索相关」的排前面
    srcs = sorted(
        dict.fromkeys(srcs),
        key=lambda u: (0 if re.search(r"(search|soso|book|common|main|head|global|base)", u, re.I) else 1),
    )
    for u in srcs[:max(0, budget)]:
        try:
            code = fetch_text(u)
        except Exception:  # noqa: BLE001
            continue
        if not code or "search" not in code.lower():
            continue
        got = learn_from_scripts(code, page_url, host)
        if got:
            out.extend(got)
            break          # 一个 JS 找到就够了，不必再抓别的
    return out


def detect_scheme(host: str) -> str:
    """这个站是 http 还是 https。老站大量只有 http。"""
    from .utils import get_client
    for sch in ("https", "http"):
        try:
            r = get_client().head(f"{sch}://{host}/", follow_redirects=True, timeout=8.0)
            if r.status_code < 500:
                return sch
        except Exception:  # noqa: BLE001
            continue
    return "https"


__all__ = [
    "learn_site", "learn_from_html", "guess_templates", "verify_tpl",
    "build_url", "make_tpl", "detect_encoding", "detect_scheme",
    "SEARCH_PARAMS", "SEARCH_PATHS",
]
