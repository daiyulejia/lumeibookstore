"""适配向导「用户只管粘地址，剩下我来兜」的回归测试（全离线）。

用户的原始批评是：
    「有几个问题要填的不是书网址而是首页这里你为什么不能兜底，
      不能让用户去适配我而是我去适配用户」

所以这个套件盯的是**责任划分**，一共四件事：

  A. 用户粘的是**正在读的那一章** → 我们自己顺着「目录」入口找到这本书。
     向导上写着"首页 / 某一本书的页面 / 正在读的那一章，给哪个都行"，
     那就得真的都行。⚠ 这里有一个**静默错**：章节页底部挂着"热门推荐"
     一屏别的书的链接，加上导航里的「章节目录」正好凑够 8 条，
     `_detail_via_page` 的两条判据全过 → 章节页被当成书页，
     读出来的"目录"是 7 本**别的书**、`chapter_re` 又推不出来。
  B. 用户看到的**正文样例**必须和最终读到的正文一致。站点用生僻字顶替
     常用字反爬时，样例里不能还是那几个生僻字 —— 用户正是靠样例判断
     "抓对没抓对"，给假坏样本等于把人往错的方向带。
  C. 适配出来的来源要**真的能搜**：搜索地址 + 结果条目正则缺一不可。
     少了结果条目正则，`ConfiguredSource.search()` 直接返回空 ——
     来源看着有搜索、实际一本书都搜不出来。
  D. 试搜要用**这本书的真名**，不是向导默认的《斗破苍穹》：
     `_looks_like_search_result` 要求结果页里出现关键词前两个字，
     站里没有那本书时会把"有搜索"误判成"没搜索"。

判据都打在"用户看得到的东西"上（步骤文案 / 样例字符串 / 配置字段 /
页面被请求了几次），每条配反证。
用法：.venv/Scripts/python.exe tools/test_adapt_direct.py
"""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import webfetch as W                                    # noqa: E402
from app.sources import adapter as A                             # noqa: E402
from app.sources import configured as C                          # noqa: E402

FIX = ROOT / "tools" / "fixtures"
BASE = "https://www.zxs8.net/"
DETAIL_URL = BASE + "3_3316/"
CHAP_URL = BASE + "3_3316/817762.html"
SEARCH_URL = BASE + "search.html"
MULU1_URL = DETAIL_URL + "mulu/1.html"
MULU2_URL = DETAIL_URL + "mulu/2.html"
MULU3_URL = DETAIL_URL + "mulu/3.html"

BOOK = "我们猫猫不能听这些"
#: 向导里那个"用一个真实书名试搜"的默认关键词。⚠ 站里**没有**这本书 ——
#: 这正是 D 组要的：拿它去试搜必须**判不出来**，只有真书名才能。
DEFAULT_KW = "斗破苍穹"

DETAIL = (FIX / "zxs8_detail.html").read_text(encoding="utf-8")
CHAP = (FIX / "zxs8_chap.html").read_text(encoding="utf-8")
MULU1 = (FIX / "zxs8_mulu1.html").read_text(encoding="utf-8")
MULU2 = (FIX / "zxs8_mulu2.html").read_text(encoding="utf-8")
MULU3 = (FIX / "zxs8_mulu3.html").read_text(encoding="utf-8")

_fail: list[str] = []
_passed = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global _passed
    if ok:
        _passed += 1
        print(f"  ✓ {name}")
    else:
        _fail.append(name)
        print(f"  ✗ {name}" + (f"（{detail}）" if detail else ""))
    return ok


# ---------------------------------------------------------------------------
# 假站点：真实夹具 + 一张首页 + 一张搜索结果页
# ---------------------------------------------------------------------------
# ⚠ 首页必须够大：`_to_site_home` 会把 < EMPTY_SHELL(800 字节) 的页面当成
#   "空壳/限制页"并放弃回首页，太小的话整条链路根本走不到。
HOME = (
    "<html><head><title>找小说吧-全本小说全文阅读</title></head><body>"
    '<a href="/">首  页</a>'
    '<form id="novel_search" action="/search.html" method="post">'
    '<input type="text" name="s" placeholder="输入书名/作者进行搜索"/>'
    '<input type="submit" value="搜索"/></form>'
    '<div class="nav">' + "".join(
        f'<a href="/sort/{i}/">{i}分类</a>' for i in range(20)) + "</div>"
    '<div class="last">' + "".join(
        f'<a href="/3_3316/{816445 + i}.html">第{i + 1}章 喵</a>' for i in range(40)
    ) + "</div></body></html>"
)


def search_page(kw: str) -> str:
    """假搜索结果页 —— **只认这本书**。

    `_looks_like_search_result` 要求结果页里出现关键词前两个字，所以拿
    《斗破苍穹》来试搜就是"没有找到"（真实站点就是这个行为，也是 D 组
    那个坑的根源）。判据的可信度就建立在这上面。
    """
    if not kw or kw[:2] not in BOOK:
        return (
            "<html><head><title>搜索</title></head><body><a href=\"/\">首  页</a>"
            f'<div class="so">没有找到“{kw}”相关的书</div>'
            + "".join(f'<a href="/sort/{i}/">{i}分类</a>' for i in range(10))
            + "</body></html>"
        )
    # 10 条**同一形状**的书名链接（含这本书）—— 形状聚类才挑得出来。
    return (
        "<html><head><title>搜索</title></head><body><a href=\"/\">首  页</a>"
        f'<div class="so">搜索“{kw}”共 1 条</div><ul class="book-list">'
        f'<li><a href="{DETAIL_URL}">{BOOK}</a></li>'
        + "".join(f'<li><a href="/3_{3300 + i}/">其它书{i}</a></li>' for i in range(9))
        + "</ul></body></html>"
    )


def chap_without_toc_entry(html: str) -> str:
    """把章节页里那个「章节目录」入口抠掉（反证用）。"""
    return re.sub(r'<a href="/3_3316/">章节目录</a>', "<span>目录没了</span>", html)


class Net:
    """假网络：`adapter._get` 的替身，同时数每个地址被打了几次。"""

    def __init__(self, *, chap: str | None = None):
        self.hits: list[str] = []
        self.pages = {
            BASE: HOME,
            DETAIL_URL: DETAIL,
            CHAP_URL: chap if chap is not None else CHAP,
            MULU1_URL: MULU1,
            MULU2_URL: MULU2,
            MULU3_URL: MULU3,
        }

    def __call__(self, url: str, timeout: float = 12.0, data=None):
        u = url.split("#")[0]
        self.hits.append(u)
        k = u.rstrip("/")
        for page_url, html in self.pages.items():
            if page_url.rstrip("/") == k:
                return html, "utf-8"
        if k == SEARCH_URL.rstrip("/"):
            return search_page((data or {}).get("s") or ""), "utf-8"
        # 详情页里那些章节链接（模板填出来的 id）→ 一律拿那一章夹具顶上：
        # 这一步只关心"目录/正则有没有推出来"，不关心具体是哪一章。
        if re.search(r"/3_3316/\d+(_\d+)?\.html$", u):
            return CHAP, "utf-8"
        raise RuntimeError(f"假网络里没有 {u}")

    def hits_of(self, url: str) -> int:
        return sum(1 for h in self.hits if h.rstrip("/") == url.rstrip("/"))


class FakeNet:
    """`webfetch.fetch_text` 的替身（`upgrade_toc` 那条链自己会发请求）。"""

    def __call__(self, url: str, **kw):
        u = url.split("#")[0]
        table = {BASE: HOME, DETAIL_URL: DETAIL, CHAP_URL: CHAP,
                 MULU1_URL: MULU1, MULU2_URL: MULU2, MULU3_URL: MULU3}
        for page_url, html in table.items():
            if page_url.rstrip("/") == u.rstrip("/"):
                return (html, page_url) if kw.get("with_url") else html
        if re.search(r"/3_3316/\d+(_\d+)?\.html$", u):
            return (CHAP, u) if kw.get("with_url") else CHAP
        raise RuntimeError(f"假网络里没有 {u}")

    def __enter__(self):
        self._old = W.fetch_text
        W.fetch_text = self
        return self

    def __exit__(self, *exc):
        W.fetch_text = self._old
        return False


def run(url: str, keyword: str, *, net: Net | None = None, save: bool = False):
    """在假网络上跑一次完整适配。返回 (Adaptation, Net)。"""
    net = net or Net()
    old = A._get
    A._get = net
    try:
        with FakeNet():
            ad = A._adapt_impl(url, keyword, save=save)
    finally:
        A._get = old
    return ad, net


def step(ad, name: str) -> str:
    return next((d for s, _ok, d in ad.steps if s == name), "")


def step_ok(ad, name: str):
    return next((ok for s, ok, _d in ad.steps if s == name), None)


def main() -> int:
    print("== A. 用户粘「正在读的那一章」，也要能适配（不许让他改成书页）==")
    ad, net = run(CHAP_URL, BOOK)
    check("整条链路走通（章节页输入也能适配成功）", ad.ok, str(ad.steps[-1:]))
    check("步骤里**明说**了是顺着「目录」入口找到的",
          step_ok(ad, "找到书的目录") is True, str([s for s, _o, _d in ad.steps]))
    check("并且去**那一章**的上一级目录页抓了",
          net.hits_of(DETAIL_URL) >= 1, str(net.hits))
    detail_step = step(ad, "打开详情页")
    check("「打开详情页」的文案说清了用的是哪一页",
          "你给的那一章的目录页" in detail_step, detail_step)
    check("目录是**完整**的 119 章（不是章节页上那 8 条别的书）",
          "119 章" in detail_step, detail_step)
    cfg = ad.config or {}
    check("`chapter_re` 推出来了（章节页那 8 条别的书是推不出来的）",
          bool(cfg.get("chapter_re")), str(sorted(cfg)))
    # 判据打在**行为 + 产品自己的运行时过滤**上（不是断言正则长什么样，
    # 也不是在测试里重写一遍形状过滤）：把推出来的正则拿去跑详情页，
    # 再走一遍 `ConfiguredSource._clean_list`，看剩下的是不是这本书的章节。
    # ⚠ 推导出来的正则是**结构性**的（`<li>…<a href=…>`），它会连导航一起匹配到，
    #   所以必须过运行时那道形状聚类 —— 这也正是"推导和运行必须一致"那条纪律。
    _got = [{"title": m.groupdict().get("title") or "",
             "url": m.groupdict().get("url") or ""}
            for m in re.finditer(cfg.get("chapter_re") or "", DETAIL, re.S | re.I)]
    _items = C.ConfiguredSource(cfg)._clean_list(_got)
    check("推出来的正则 + 运行时过滤 → 读出的**是这本书的章节**（`/3_3316/<id>.html`）",
          len(_items) >= 8 and all(
              re.search(r"/3_3316/\d+\.html", it["url"]) for it in _items),
          str([it["url"] for it in _items[:4]]))

    print("\n── 反证 A1：章节页确实会让「就当它是书页」那条判据误判 ──")
    # 8 条 = 7 条热门推荐（**别的书**）+ 页面自己的书页链接。它们连章节都不是。
    mis = A._detail_via_page(CHAP_URL, CHAP)
    check("章节页被判成「就是书页」→ 所以必须先把它摘出去", bool(mis))
    check("那 8 条里**没有一条**是章节（全是别的书 / 书页链接）",
          all(not re.search(r"/3_3316/\d+\.html", u["url"])
              for u in W.extract_toc(CHAP, CHAP_URL)),
          str([u["url"] for u in W.extract_toc(CHAP, CHAP_URL)]))

    print("\n── 反证 A2：入口被抠掉时，不许再声称「找到了目录」，也不能硬认 ──")
    stripped = run(CHAP_URL, BOOK, net=Net(chap=chap_without_toc_entry(CHAP)))[0]
    check("不再出现「找到书的目录」那一步",
          step_ok(stripped, "找到书的目录") is None,
          str([s for s, _o, _d in stripped.steps]))
    check("改走搜索那条路，照样适配成功（不是失败，也不是硬认章节页）",
          stripped.ok and bool((stripped.config or {}).get("chapter_re")),
          f"ok={stripped.ok} cfg={sorted(stripped.config or {})}")

    print("\n── 反证 A3：给的是**书页**时，别为了兜底多打一次请求 ──")
    # 书页的「完整目录」入口指向它的**下一级**（`/3_3316/mulu/1.html`），
    # 那种情况原判据本来就是对的 → `_is_under` 那一条就是拦住"书页也跟着跳"的。
    # ⚠ 数的是 `adapter._get` 的命中：`upgrade_toc` 走的是 `webfetch.fetch_text`，
    #   两条链分开数，才看得出这一跳到底是谁打的。
    _bp, bp_net = run(DETAIL_URL, BOOK)
    check("（前置）书页输入也能适配成功", _bp.ok, str(_bp.steps[-1:]))
    check("没有为了兜底去 `_get` 一次「完整目录」页",
          bp_net.hits_of(MULU1_URL) == 0, str(bp_net.hits))
    check("「打开详情页」的文案说的是「你给的那一页」（不是目录页）",
          "你给的那一页" in step(_bp, "打开详情页"), step(_bp, "打开详情页"))

    print("\n== B. 用户看到的正文样例必须和最终读到的正文一致 ==")
    # 夹具的正文是 base64 写出来的，得解出来才能看有没有反爬生僻字
    # （直接 grep 夹具文件是**看不到**的 —— 里面只有 base64）。
    body = "".join(
        base64.b64decode(b).decode("utf-8")
        for b in re.findall(r"kyvsbt\.vz\('([A-Za-z0-9+/=]+)'\)", CHAP))
    check("（前置）夹具正文里真的有反爬生僻字「葶」（≥3 处）",
          body.count("葶") >= 3, f"葶={body.count('葶')}")
    check("样例里**不许**出现「葶」（否则等于给用户看假坏样本）",
          "葶" not in ad.sample_preview, ad.sample_preview[:80])
    check("样例是能读的中文（「葶」已还原成「的」）",
          "的" in ad.sample_preview, ad.sample_preview[:80])
    check("样例长度与正文口径一致（不是空壳）", ad.sample_chars >= 120,
          str(ad.sample_chars))

    print("── 反证 B1：把收口那一步拿掉，样例里就会重新长出「葶」 ──")
    _old_tidy = A.tidy_content
    A.tidy_content = lambda t, title="": t          # noqa: ARG005  ← 复现旧行为
    try:
        raw_ad, _ = run(CHAP_URL, BOOK)
    finally:
        A.tidy_content = _old_tidy
    check("拿掉收口后样例里确实出现「葶」（说明这条判据有牙）",
          "葶" in raw_ad.sample_preview, raw_ad.sample_preview[:80])

    print("\n== C. 直接路径也要把搜索能力带上（否则「下次按书名搜」是空话）==")
    c_cfg = ad.config or {}
    check("配置里有搜索地址", bool(c_cfg.get("search_url")), str(sorted(c_cfg)))
    check("配置里**也有**结果条目正则（少了它 search() 恒返回空）",
          bool(c_cfg.get("search_item_re")), str(sorted(c_cfg)))
    src = C.ConfiguredSource(c_cfg)
    check("来源自报「有搜索」", src.has_search is True)
    _old_fetch = C.fetch_text
    C.fetch_text = lambda url, **kw: search_page(BOOK)      # noqa: ARG005
    try:
        got = src.search(BOOK)
    finally:
        C.fetch_text = _old_fetch
    check("真的搜得出书（不是「有搜索但一本都搜不到」）",
          len(got) >= 1 and BOOK in got[0].title,
          str([b.title for b in got[:3]]))

    print("── 反证 C1：拿掉「顺手认结果结构」，来源就没有搜索能力了 ──")
    _old_pick = A._pick_best_link_pattern
    A._pick_best_link_pattern = lambda *a, **k: ("", [])    # noqa: ARG005
    try:
        noeat, _ = run(CHAP_URL, BOOK)
    finally:
        A._pick_best_link_pattern = _old_pick
    n_cfg = noeat.config or {}
    check("配置里就没有 `search_url` 了（`has_search` 变 False）",
          not n_cfg.get("search_url"), str(sorted(n_cfg)))
    check("或者至少 `search_item_re` 没了（两种写法都算「没搜索」）",
          not n_cfg.get("search_item_re"), str(sorted(n_cfg)))

    print("\n== D. 试搜要用这本书的**真名**，不是向导默认的《斗破苍穹》==")
    d_ad, _ = run(CHAP_URL, DEFAULT_KW)
    d_cfg = d_ad.config or {}
    check("站里没有《斗破苍穹》，但搜索能力**照样**认出来了",
          bool(d_cfg.get("search_url")), f"key={DEFAULT_KW} cfg={sorted(d_cfg)}")
    _old_title = A._book_title_of
    A._book_title_of = lambda html: ""                      # noqa: ARG005
    try:
        d_no, _ = run(CHAP_URL, DEFAULT_KW)
    finally:
        A._book_title_of = _old_title
    check("（反证）退回默认关键词后就认不出来了 → 这条判据有牙",
          not (d_no.config or {}).get("search_url"),
          str(sorted(d_no.config or {})))

    print("\n== E. 试搜页不许被重复请求（限速就是这么撞上的）==")
    calls = {"n": 0}
    _old_sf = A._search_fetch

    def _spy(url, data, *, tries=3):
        calls["n"] += 1
        return search_page((data or {}).get("s") or ""), "utf-8"

    A._search_fetch = _spy
    try:
        e_ad, e_net = run(BASE, BOOK)          # 给首页 → 走搜索那条路
    finally:
        A._search_fetch = _old_sf
    check("（前置）搜索那条路走通了", e_ad.ok, str(e_ad.steps[-1:]))
    check("搜索页只被打了一次", e_net.hits_of(SEARCH_URL) == 1,
          f"hits={e_net.hits_of(SEARCH_URL)}")
    check("`_search_fetch` 一次都没调（复用它自己刚试搜成功的那张页面）",
          calls["n"] == 0, str(calls))

    print("\n" + "=" * 62)
    if _fail:
        print(f"通过 {_passed} · 失败 {len(_fail)}")
        for n in _fail:
            print(f"  ✗ {n}")
        return 1
    print(f"通过 {_passed} · 失败 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
