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

    这些是**没有证据的猜测**，必须一个个发请求验证。

    ⚠ 顺序就是生死 —— 预算只有十几个候选，排在后面 = **永远轮不到**。
      旧版是按 `SEARCH_PATHS` 的字面顺序「路径 × ?q=」铺开，结果
      `/?s=`（极简站/移动站的常态）排在第 17 位、杰奇组合排在最后，
      而预算 6 只能覆盖到第 6 条 —— 表尾那些高频组合**结构上取不到**。

      实测（2026-10-21，18 个"能抓目录但学不会搜索"的真实小说站）：
        · `/?s={kw}`                 命中 2 个站（luoxiaks / washai）
        · `/modules/article/search.php?searchkey=`  命中 1 个（sudugu）
        · 其余全部落空
      线上已验证可用的模板里，`/search.php?q=` `/?q=` `/search/?q=`
      `/category.php?keyword=` 也都在用。所以按**实测命中率**分四档重排。
    """
    out: list[dict] = []
    seen: set[str] = set()

    def add(tpl: str) -> None:
        if tpl and tpl not in seen and "{kw}" in tpl:
            seen.add(tpl)
            out.append({"tpl": tpl, "enc": "utf-8", "via": "guess",
                        "method": "get"})

    # 第一档：实测命中过的、以及线上已证明在用的
    for path, pname in _JIECI_COMBOS:
        add(f"{path}?{pname}={{kw}}")
    for path in ("/?s=", "/?q=", "/?search="):
        add(path + "{kw}")
    for path, pname in (("/search.php", "q"), ("/search", "keyword"),
                        ("/search", "q"), ("/search/", "q"),
                        ("/search.html", "q"), ("/s", "q"), ("/s", "wd")):
        add(f"{path}?{pname}={{kw}}")

    # 第二档：其它常见「路径 × 参数名」组合
    for path in SEARCH_PATHS:
        if path.endswith("="):
            add(path + "{kw}")          # `/?q=` 这种路径本身带参数名
        elif "?" in path:
            add(f"{path}&q={{kw}}")
        else:
            add(f"{path}?q={{kw}}")
    for path in ("/search.php", "/search", "/search/", "/so.php", "/s",
                 "/search.html"):
        for pname in ("keyword", "kw", "wd", "searchkey", "key", "searchword", "s"):
            add(f"{path}?{pname}={{kw}}")

    # 第三档：CMS 的 GET 路由形态（`/index.php?m=search&q=` 这类）
    for path in ("/index.php?m=search", "/plus/search.php", "/e/search/index.php"):
        for pname in ("q", "keyword", "kw", "wd"):
            add(f"{path}&{pname}={{kw}}")
    return out


# ---------------------------------------------------------------------------
# 验证一个模板到底能不能搜
# ---------------------------------------------------------------------------
# 控制实验用的"绝对搜不到"的书名。故意带不可能出现在任何小说标题里的字母串。
CONTROL_KW = "zzqqxxbuCunZaiDeShuMing"
_CONTROL_KW = CONTROL_KW      # 兼容内部旧引用
# 真关键词的结果集和"搜不到的词"的结果集，重合度超过这个就认为**根本没在筛**。
#
# 0.5 是**量出来的**，不是拍的：拿线上 21 个已学模板做控制实验，
# 真站的 Jaccard 最高 0.24（`www.xizids.com`），假站最低 0.66
# （`www.chamabooks.net` 返的是「全部/言情/耽美」分类导航）——
# 中间是一段干净的空档，取中间值 0.5。
CONTROL_SAME_RATIO = 0.5
_CONTROL_SAME_RATIO = CONTROL_SAME_RATIO   # 兼容内部旧引用


def _fetch_hits(tpl: str, host: str, keyword: str, *,
                enc: str = "utf-8", scheme: str = "https",
                method: str = "get", body: Optional[dict] = None,
                min_hits: int = 3) -> tuple[int, set[str]]:
    """请求一次，回 `(命中章节数, 结果 URL 集合)`。不成立回 `(0, set())`。

    判据用「有没有一堆看起来像章节的链接」而不是「页面里有没有关键词」——
    很多站搜不到时会**回首页**（首页当然有链接，但那是导航不是结果），
    只数关键词会把它误判成成功。

    ⚠ 但它**只回答"这一页像不像结果页"，不回答"结果是不是由关键词筛出来的"**
      —— 后者要靠 `verify_search()` 的控制实验。别拿这个函数的返回值当结论。
    """
    from . import webfetch        # 延迟导入：避免启动期的循环依赖
    from .utils import fetch_text

    url = build_url(tpl, host, keyword, enc=enc, scheme=scheme)
    if not url:
        return 0, set()

    data = None
    if (method or "get").lower() == "post":
        # POST 搜索：关键词放请求体，URL 里不带参数
        data = {k: str(v).replace("{kw}", keyword)
                for k, v in (body or {"s": "{kw}"}).items()}
        # URL 去掉 `?…` 部分（POST 的 tpl 本来就没带）
        url = build_url(tpl, host, "", enc=enc, scheme=scheme) or url

    try:
        html, final = fetch_text(url, with_url=True, data=data)
    except Exception as e:  # noqa: BLE001
        logger.debug("搜索模板验证失败 %s: %s", url, e)
        return 0, set()
    if not html or len(html) < 400:
        return 0, set()

    # 跟随重定向后掉回首页 → 这个模板是假的「能搜」
    fp = urlparse(final or url)
    fpath = (fp.path or "/").rstrip("/")
    if fpath in ("", "/", "/index.php") and fp.query == "":
        return 0, set()

    try:
        toc = webfetch.extract_toc(html, final or url)
    except Exception:  # noqa: BLE001
        return 0, set()
    toc = toc or []
    urls = {str(t.get("url") or "") for t in toc if isinstance(t, dict)}
    urls.discard("")
    if len(toc) < min_hits:
        return 0, set()
    return len(toc), urls


def verify_tpl(tpl: str, host: str, probe_keyword: str, *,
               enc: str = "utf-8", scheme: str = "https",
               method: str = "get", body: Optional[dict] = None,
               min_hits: int = 3) -> Optional[int]:
    """拿探测词去请求一次，回内容里有章节链接就算成。

    返回命中的章节链接数（够多才算真的搜到了）；不成立返回 None。

    ⚠ 这是**单次**判据，只说明"这一页像结果页"。要判断"这个模板真的在按
      关键词筛"，必须用 `verify_search()` —— 见那里关于 5 个假模板的注释。
    """
    n, _ = _fetch_hits(tpl, host, probe_keyword, enc=enc, scheme=scheme,
                       method=method, body=body, min_hits=min_hits)
    return n or None


def verify_search(tpl: str, host: str, probe_keyword: str, *,
                  enc: str = "utf-8", scheme: str = "https",
                  method: str = "get", body: Optional[dict] = None,
                  min_hits: int = 3, control_kw: str = _CONTROL_KW,
                  ) -> Optional[dict]:
    """**真正**验证一个模板：既要"像结果页"，还要"结果随关键词变"。

    做法是**控制实验**：同一个模板再发一次，关键词换成绝对搜不到的书名。
      · 两次结果集重合度 ≥ `_CONTROL_SAME_RATIO` → 这个站根本不认这个参数，
        只是照常吐首页/列表页 → **不是搜索**
      · 重合度低 → 真的在按关键词筛 → 成立

    ⚠ 为什么必须有第二个条件（线上实测，2026-10-21）：
      21 个已学模板里 **5 个是假的** —— `www.xxsy.net` `www.tmwk.cc`
      `www.mhxs.cc` `www.taishuaile.com` `www.tzkibb.com`。它们形如
      `/?q={kw}` / `/search.php?q={kw}`，站点不理这个参数，照常返回
      首页或通用列表（首页当然有一堆像章节的链接）。旧判据只数链接，
      于是全判成"搜到了"。
      后果不是"搜出错书"（相关性排序会把它们筛掉），而是：
        · 界面上"综合 21 站"里有 5 个**永远不可能**贡献一条结果
        · 每次搜索都要多打这 5 个站、多等它们
      也就是说，掺假的可搜源会把"我们的来源有多广"这件事变成假话。

    返回 `{"hits": n}` 或 None。
    """
    n, urls = _fetch_hits(tpl, host, probe_keyword, enc=enc, scheme=scheme,
                          method=method, body=body, min_hits=min_hits)
    if not n:
        return None
    if control_says_fake(tpl, host, enc=enc, scheme=scheme, method=method,
                         body=body, urls=urls, hits=n, min_hits=min_hits):
        return None
    return {"hits": n, "enc": enc}


def control_says_fake(tpl: str, host: str, *, enc: str = "utf-8",
                      scheme: str = "https", method: str = "get",
                      body: Optional[dict] = None, urls: set[str],
                      hits: int, min_hits: int = 3,
                      control_kw: str = _CONTROL_KW) -> bool:
    """控制实验：同一个模板换成"绝对搜不到的书名"，结果集是不是**一模一样**。

    `urls` / `hits` 传调用方**已经拿到**的那次真实探测结果 —— 少发一个请求。
    返回 True = 判假（站点不认这个参数）。

    ⚠ 单独抽成函数是为了让 `learn_site()` 能复用它手上已有的探测结果，
      否则每验一个候选都要把真实探测重跑一遍（一个候选 3 个请求，实测
      一半的学站时间耗在重复请求上）。
    """
    if not control_kw or control_kw == "":
        return False
    n2, urls2 = _fetch_hits(tpl, host, control_kw, enc=enc, scheme=scheme,
                            method=method, body=body, min_hits=min_hits)
    if not n2:
        return False
    union = urls | urls2
    same = (len(urls & urls2) / len(union)) if union else 1.0
    if not union or same >= _CONTROL_SAME_RATIO:
        logger.info(
            "模板不认关键词，判假：%s %s —— 真书名 %d 条 / 搜不到的书名 %d 条，重合 %.0f%%",
            host, tpl, hits, n2, same * 100)
        return True
    return False


def probe_keyword_once(tpl: str, host: str, keyword: str, *,
                       scheme: str = "https", method: str = "get",
                       body: Optional[dict] = None,
                       min_hits: int = 3) -> tuple[str, int, set[str]]:
    """把「探编码」和「探命中」合并成一次最小成本探测。

    返回 `(用哪个编码才通, 命中数, 结果 URL 集合)`；都不通回
    `("utf-8", 0, set())`。

    ⚠ 为什么要合并：旧流程是 `detect_encoding()`（最多 2 个请求）
      再 `verify_tpl()`（1 个请求），一个**失败**的候选要花 3 个请求；
      而爆破表里绝大多数候选都是失败的，于是预算全花在"确认它不行"上
      （实测一个站学不动，一半时间耗在这里）。合并后失败候选最多 2 个请求。
    """
    for enc in ("utf-8", "gb18030"):
        try:
            n, urls = _fetch_hits(tpl, host, keyword, enc=enc, scheme=scheme,
                                  method=method, body=body, min_hits=min_hits)
        except Exception:  # noqa: BLE001
            continue
        if n:
            return enc, n, urls
    return "utf-8", 0, set()


def detect_encoding(host: str, tpl: str, probe_keyword: str, *, scheme: str = "https",
                    method: str = "get", body: Optional[dict] = None) -> str:
    """判断这个站该用 UTF-8 还是 GBK 传关键词。

    做法：用 utf-8 拼一次请求，如果**回内容里没有探测词的任何字符**，
    再试 gb18030（GBK 超集）。中文老站大量是 GBK 的，
    关键词编码错了站方就搜不到、返回空 —— 这一点必须探。

    返回 "utf-8" 或 "gb18030"。
    """
    enc, _, _ = probe_keyword_once(tpl, host, probe_keyword, scheme=scheme,
                                   method=method, body=body)
    return enc


# ---------------------------------------------------------------------------
# 总入口：学一个站
# ---------------------------------------------------------------------------
def _resolve_scheme(host: str, page_url: str, scheme: str) -> str:
    """这个站该按 http 还是 https 去验证。

    ⚠ 这里原先写死 `scheme="https"`，是个**静默的真缺陷**：老小说站
    大量只有 http（`www.tengc.com` 的 https 直接 403）。于是：
      · `detect_encoding()` 按 https 试两次，都失败 → 退回 "utf-8"
      · `verify_tpl()` 按 https 请求，也失败 → 返回 None
      · `learn_site()` 于是对**明明有现成 form** 的站返回 `{}`
    实测 `www.tengc.com`：`learn_from_html()` 正确学到
    `/search49.html` + `searchkey`，用 http 一验就 **25 条章节链接**，
    可整条链路报的却是"找不到搜索接口" —— 三次失败后
    `search_fail=3`，这个站被**永久**踢出学站清单。

    `page_url` 是我们**刚刚抓成功**的那一页，它的 scheme 就是真相，
    比再去 HEAD 一次更准更省。
    """
    sc = (scheme or "").strip().lower()
    if sc in ("http", "https"):
        return sc
    if page_url:
        try:
            s = urlparse(page_url).scheme.lower()
        except Exception:  # noqa: BLE001
            s = ""
        if s in ("http", "https"):
            return s
    return detect_scheme(host)


def learn_site(
    host: str,
    *,
    page_url: str = "",
    html: str = "",
    probe_keyword: str = "",
    allow_guess: bool = True,
    scheme: str = "",
    budget: int = 6,
    js_budget: int = 2,
) -> dict:
    """学一个站的搜索能力。返回学到的配置；学不到返回空 dict。

    · `html` + `page_url`：手上有现成的页面时用（零成本，只在其中找 form / 链接）
    · `allow_guess=True`：还可以爆破常见路径（要发请求，`budget` 限制次数）
    · `js_budget`：最多再去读几个外部 JS 文件找 JS 写出来的搜索框
    · `scheme`：留空即从 `page_url` 推断（推荐）—— 见 `_resolve_scheme()`

    返回::

        {"search_tpl": "/search.php?q={kw}", "search_enc": "gbk",
         "search_via": "form", "search_at": 1760000000}
    """
    host = (host or "").strip().lower()
    if not host:
        return {}
    scheme = _resolve_scheme(host, page_url, scheme)

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
    n_tried = 0
    for c in ordered:
        tpl = c.get("tpl") or ""
        if not tpl or tpl in tried:
            continue
        tried.add(tpl)
        if n_tried >= budget:
            break
        n_tried += 1
        method = c.get("method", "get")
        body = c.get("body")

        if not probe_keyword:
            # 没有探测词就**没法验证** —— 只把 form 学到的当结论，交给上层去验。
            # （爆破出来的都是纯猜测，没验证过的一律不认。）
            if c.get("via") in ("form", "form-post"):
                got = {"search_tpl": tpl, "search_enc": "utf-8",
                       "search_via": c["via"]}
                if method == "post":
                    got["search_method"] = "post"
                    got["search_body"] = body
                return got
            continue

        # 一次探测同时定「编码」和「命中数」；通了再花一个请求做控制实验。
        enc, hits, urls = probe_keyword_once(
            tpl, host, probe_keyword, scheme=scheme, method=method, body=body)
        if not hits:
            continue
        # ⚠ 必须做控制实验：只数链接会把"站点不认参数、照常吐首页"判成搜到了。
        #   线上 21 个已学模板里 9 个是这么混进来的（见 verify_search 的注释）。
        if control_says_fake(tpl, host, enc=enc, scheme=scheme, method=method,
                             body=body, urls=urls, hits=hits):
            continue

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
    "verify_search", "control_says_fake", "probe_keyword_once", "CONTROL_KW",
    "CONTROL_SAME_RATIO",
    "build_url", "make_tpl", "detect_encoding", "detect_scheme",
    "SEARCH_PARAMS", "SEARCH_PATHS",
]
