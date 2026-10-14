"""「这网站的目录/正文能不能读全」的回归测试（全离线，打真实页面形状）。

背景（用户原话：「有几个问题要填的不是书网址而是首页这里你为什么不能兜底」、
「其次有坑你要继续呀不可以停」）：

    实测站 `www.zxs8.net`（跑的是「17mb / black / bqg」那套模板，大量笔趣阁
    克隆都在用同一份代码）——《我们猫猫不能听这些》**全书 119 章**，
    而我们只读到 12 章，正文一个字都读不到。

    四个独立的坑叠在一起，每个都**不报错**、只是悄悄少给东西：

    A. 章节链接是 JS 造的：`<a onclick="idm(816445);">第1章 喵</a>`（没有 href），
       而页面自己在内联脚本里声明了地址模板 `var read_rewrite='/{bid}_{aid}/{cid}.html'`。
       → 只认 `<a href>` 的话，整本书只读到详情页挂的 12 条「最新章节」。
    B. 完整目录还分页：`/mulu/1.html` 只到第 100 章，第 101–119 章在 `/mulu/2.html`。
       → 只跳一跳就是「看起来完整、实际缺 19 章」。
    C. 正文是 base64 写出来的：`document.writeln(kyvsbt.vz('PHA+…'))`，
       整页 HTML 里**一个正文字符都没有**。
    D. 正文里「的」被换成生僻字「葶」（同一类反爬，更隐蔽）。

    还有两个"责任划分"上的坑（也是用户抱怨的点）：
    E. 适配向导写着"填首页"，用户粘了书页 → 我们该自己回到首页，而不是让他改。
    F. `rstrip("/")` 把 `/3_3316/` 变成 `/3_3316` —— 后者在这个站是 **404**。

还有四个**同源的静默点**（都是"读不全却不报错"这一族）：
    G. 搜索限速页冒充搜索结果（`搜索间隔【5】秒…` + 一屏分类导航当书）。
    H. 非贪婪正则取不到嵌套容器（`word_read` 里套 `read_btn`）→ 只拿到第一层。
    I. 站点把「相邻推荐」的 20 条书名链接塞在**正文容器里面**。
    J. 「一章拆多页」有**两套机制**（模板式 `page_url` / 声明式 `reading_next_url`），
       只走一条就会在另一种站上悄悄少给后半章；目录分页还有预算上限，
       撞上限却不说 = 把"被自己停下"当完整目录交付。

判据一律打在**真实抓下来的页面**上（`tools/fixtures/zxs8_*.html`，
其中章节页的结构照抄实测页面、只有正文段落换成自写文字），
并且几乎每条都配**反证**：把产品代码的那个机制人为破掉，看断言会不会真红。
少了反证，这种测试最容易变成"恒真的假测试"（本项目抓到过 6 次）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import webfetch as W                                  # noqa: E402
from app.models import Chapter                                  # noqa: E402
from app.sources import adapter as A                            # noqa: E402
from app.sources import configured as C                         # noqa: E402
from app.sources.base import deobfuscate, page_url              # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
BASE = "https://www.zxs8.net/"
DETAIL_URL = "https://www.zxs8.net/3_3316/"
MULU1_URL = "https://www.zxs8.net/3_3316/mulu/1.html"
MULU2_URL = "https://www.zxs8.net/3_3316/mulu/2.html"
CHAP_URL = "https://www.zxs8.net/3_3316/817762.html"
CHAP2_URL = "https://www.zxs8.net/3_3316/817762_1.html"

PAGES = {
    DETAIL_URL: "zxs8_detail.html",
    MULU1_URL: "zxs8_mulu1.html",
    MULU2_URL: "zxs8_mulu2.html",
    "https://www.zxs8.net/3_3316/mulu/3.html": "zxs8_mulu3.html",
    CHAP_URL: "zxs8_chap.html",
}
_raw = {u: (FIX / f).read_text(encoding="utf-8") for u, f in PAGES.items()}
DETAIL, MULU1, MULU2, CHAP = (
    _raw[DETAIL_URL], _raw[MULU1_URL], _raw[MULU2_URL], _raw[CHAP_URL])

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


def han(s: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", s or ""))


class FakeNet:
    """把 `webfetch.fetch_text` 换成"只认 fixture 的假网络"。

    为什么必须换掉：这里要验 `upgrade_toc` 那条**多页拼接**的链路，而它自己会
    发请求。用假网络把「网站上有哪些页」写死，判据才稳定、也不会去打扰真站
    （实测那个站有 5 秒搜索限速，测试打多了会把自己限死）。
    """

    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def __call__(self, url: str, **kw):
        url = url.split("#")[0]
        if url not in self.pages:
            raise RuntimeError(f"假网络里没有 {url}")
        html = self.pages[url]
        return (html, url) if kw.get("with_url") else html

    def __enter__(self):
        self._old = W.fetch_text
        W.fetch_text = self
        return self

    def __exit__(self, *exc):
        W.fetch_text = self._old
        return False


def main() -> int:
    print("== A0. 判据 C：站点自报的「最新章节」必须抓得到（两种语序都要认）==")
    _lts = [int(m.group(1)) for rx in W._LATEST_CHAPTER_RES
            if (m := rx.search(DETAIL))]
    check("实测页面写的是 `第119章 喵喵最新章节试读`（**章号在前**）→ 认出 119",
          119 in _lts, str(_lts))
    _lts2 = [int(m.group(1)) for rx in W._LATEST_CHAPTER_RES
             if (m := rx.search("最新章节：第119章 喵喵喵"))]
    check("另一种语序 `最新章节：第119章`（关键词在前）也要认",
          119 in _lts2, str(_lts2))

    print("\n== A. 章节链接是 JS 造的（onclick + 页面自报模板）==")
    det_toc = W.extract_toc(DETAIL, DETAIL_URL)
    check("详情页只挂 12 条「最新章节」——这就是用户看到的『12 章』",
          len(det_toc) == 12, f"实际 {len(det_toc)}")
    d_partial, d_note = W.toc_completeness(det_toc, DETAIL)
    check("而且这 12 条**被如实判定为片段**（不是当成全书）", d_partial)
    check("说明文案是**人话**（不能是 URL 里的章节 id 号）",
          "第 108 章" in d_note, d_note)

    m1_toc = W.extract_toc(MULU1, MULU1_URL)
    check("目录页靠页面自报的模板补回 onclick 章节（≥100 条）",
          len(m1_toc) >= 100, f"实际 {len(m1_toc)}")
    check("首条就是第 1 章（模板填对了，没有错位）",
          bool(m1_toc) and m1_toc[0]["title"].startswith("第1章"),
          m1_toc[0]["title"] if m1_toc else "空")
    check("章号取自**标题**而不是 URL 里的 id（判据 A/B 才成立）",
          W.chapter_numbers(m1_toc)[:1] == [1], str(W.chapter_numbers(m1_toc)[:3]))

    print("\n── 反证 A1：模板里有一个槽位填不上时，必须整条拒绝 ──")
    v1 = re.sub(r"var\s+read_aid\s*=\s*'[^']*';\s*", "", MULU1)
    n1 = len(W.extract_toc(v1, MULU1_URL))
    check("删掉配套变量 `read_aid` 后条目数暴跌（不是恒真）",
          n1 < 30, f"删掉后还有 {n1} 条（原来 101）")
    print("── 反证 A2：模板与页面真实 href 形状对不上时不许采纳 ──")
    v2 = MULU1.replace("/{bid}_{aid}/{cid}.html", "/x{aid}y/{cid}.html")
    n2 = len(W.extract_toc(v2, MULU1_URL))
    check("形状对不上 → 拒绝（否则『交叉验证』那条判据是摆设）",
          n2 < 30, f"实际 {n2}")
    print("── 反证 A3：把 onclick 去掉，补链接的能力必须跟着消失 ──")
    n3 = len(W.extract_toc(MULU1.replace("onclick", "data-onc"), MULU1_URL))
    check("没有 onclick 就没有可还原的章节链接", n3 < 30, f"实际 {n3}")

    print("\n== B. 完整目录还分页：必须一路跟到没页为止 ==")
    with FakeNet(dict(_raw)):
        got, _url, note = W.upgrade_toc(det_toc, DETAIL, DETAIL_URL)
    check("详情页 12 条 → 拼页后 **119 章**（一路跟到底）",
          len(got) == 119, f"实际 {len(got)}")
    check("首尾正确：第1章 … 第119章",
          bool(got) and got[0]["title"].startswith("第1章")
          and got[-1]["title"].startswith("第119章"),
          f"{got[0]['title']} … {got[-1]['title']}" if got else "空")
    check("章号连续无缺口（1..119）",
          W.chapter_numbers(got) == list(range(1, 120)),
          f"共 {len(W.chapter_numbers(got))} 个章号")
    check("拼全之后**不再**报「可能不全」", note == "", note)

    print("\n── 反证 B1：拿掉第 2 页，必须如实说可能不全，不能假装完整 ──")
    with FakeNet({k: v for k, v in _raw.items() if k != MULU2_URL}):
        p_toc, _u, p_note = W.upgrade_toc(det_toc, DETAIL, DETAIL_URL)
    check("只跟到第 1 页时条数确实少了（101 < 119）",
          len(p_toc) == 101, f"实际 {len(p_toc)}")
    check("**并且给出提示**（页面上有「下一页」却没跟到 → 必须说出来）",
          "部分章节" in p_note, repr(p_note))

    print("\n── 反证 B2：一条都抓不到时，绝不把好目录换坏 ──")
    with FakeNet({DETAIL_URL: DETAIL}):
        s_toc, _u, s_note = W.upgrade_toc(det_toc, DETAIL, DETAIL_URL)
    check("跟页全失败时保留原始目录（12 条，而不是空）",
          len(s_toc) == 12, f"实际 {len(s_toc)}")
    check("**并且说明可能不全**（沉默 = 界面把 12 条当全书）",
          bool(s_note) and "章" in s_note, repr(s_note))

    print("\n── 反证 B3：拼到更多章节、但仍不完整时，必须保住**更全的那份** ──")
    # 场景：两页都被截短（第 1 页只到第 50 章、第 2 页只给第 101–110 章）。
    # 拼完 60 条、仍缺了一大段 → 依旧判为片段。此时**绝不能**因为"还没拼齐"
    # 就把刚拼到的 10 章扔掉（曾经就是这样：返回旧目录 —— 多拿到的章节
    # 被自己的谨慎吞掉了）。
    def _trunc(html: str, fn: str, keep: int) -> tuple[str, int]:
        n = [0]

        def rep(m):
            n[0] += 1
            return m.group(0) if n[0] <= keep else ""

        pat = r'<a[^>]*onclick="' + fn + r'\(\d+\);"[^>]*>[^<]*</a>'
        return re.sub(pat, rep, html), n[0]

    short1, n1 = _trunc(MULU1, "idm", 50)
    short2, n2 = _trunc(MULU2, "rwezja", 10)
    # 两页页尾都有 `<p>最新章节：<a href>第119章 喵喵</a></p>` —— 它会让
    # 目录的**最大章号**变成 119，从而掩盖"只有前 50 章"这件事。真删掉它，
    # 才能造出"拼了更多、却依然缺一大段"的场景。
    _tail = re.compile(r'<p>最新章节：<a[^>]*>[^<]*</a></p>')
    short1, short2 = _tail.sub("", short1), _tail.sub("", short2)
    check("（前置）两页都被截短：100 → 50、19 → 10",
          (n1, n2) == (100, 19)
          and W.chapter_numbers(W.extract_toc(short1, MULU1_URL)) == list(range(1, 51))
          # 第 2 页的「开始阅读」还指回第 1 章，所以只看 100 以上的章号
          and [n for n in W.chapter_numbers(W.extract_toc(short2, MULU2_URL)) if n > 100]
          == list(range(101, 111)),
          f"{n1}/{n2} · "
          f"{W.chapter_numbers(W.extract_toc(short1, MULU1_URL))[-2:]} / "
          f"{sorted(n for n in W.chapter_numbers(W.extract_toc(short2, MULU2_URL)))[:2]}")
    with FakeNet({**{k: v for k, v in _raw.items() if k not in (MULU1_URL, MULU2_URL)},
                  MULU1_URL: short1, MULU2_URL: short2}):
        b3_toc, _u, b3_note = W.upgrade_toc(det_toc, DETAIL, DETAIL_URL)
    check("**保住拼上来的部分**：60 条（50 + 新拼的 10），不是退回 50 条",
          len(b3_toc) == 60, f"实际 {len(b3_toc)}")
    check("章号是拼起来的两段（1–50 与 101–110）",
          W.chapter_numbers(b3_toc) == list(range(1, 51)) + list(range(101, 111)),
          f"实际 {len(W.chapter_numbers(b3_toc))} 个")
    check("同时如实说还缺（不完整靠『说出来』，不靠『少给』）",
          bool(b3_note) and "章" in b3_note, repr(b3_note))

    print("\n== C. 正文是 base64 写出来的 ==")
    check("原始 HTML 里**一个正文字符都没有**（所以必须解码）",
          "猫咪用品店" not in CHAP)
    unwrapped = W.unwrap_writeln(CHAP)
    check("解出来就有正文了", "猫咪用品店" in unwrapped)
    check("**没有留下孤零零的 `);</script>` 残留**"
          "（必须在 `<script>` 标签那一级整体替换，不然正文又被当脚本删掉）",
          unwrapped.count("document.writeln") == 0 and ");</script>" not in unwrapped)
    extracted = W.extract_content(CHAP)
    body = W.clean_body(extracted)
    check("走完整链路能拿到正文（≥200 汉字）", han(body) >= 200, f"实际 {han(body)} 汉字")
    check("正文里没有混进「热门小说推荐」那块", "洛雪音毒医至尊" not in body)
    check("正文选的是 `word_read`，不是外层 `container`（少一层面包屑垃圾）",
          "找小说吧>" not in extracted, extracted[:60])
    check("导航词「章节目录 / 上一章」被清洗掉，不会读进正文",
          "章节目录" not in body and "上一章" not in body, body[:60])

    print("\n== D. 「一章拆成多页」——续页是页面自己声明的 ==")
    check("本章地址声明了同章续页 `_1.html`",
          W.reading_next_url(CHAP, CHAP_URL) == CHAP2_URL,
          str(W.reading_next_url(CHAP, CHAP_URL)))
    print("── 第 2 页继续声明第 3 页（`_N` 必须先把旧的剥掉再叠）──")
    # 用第 1 页的 HTML 只改那行 JS 变量来当"第 2 页"：同一个站同一套模板，
    # 两页结构完全一样，差别只在声明的那一行 —— 不必再存一份 4KB 的 base64 正文。
    chap2_html = CHAP.replace("817762_1.html", "817762_2.html")
    check("第 2 页 → 第 3 页",
          W.reading_next_url(chap2_html, CHAP2_URL)
          == "https://www.zxs8.net/3_3316/817762_2.html",
          str(W.reading_next_url(chap2_html, CHAP2_URL)))
    check("`_page_variant` 先剥已有的 `_N`（幂等，不许套娃成 `_1_1`）",
          W._page_variant(CHAP2_URL, 1) == CHAP2_URL
          and W._page_variant(CHAP_URL, 2)
          == "https://www.zxs8.net/3_3316/817762_2.html",
          f"{W._page_variant(CHAP2_URL, 1)} / {W._page_variant(CHAP_URL, 2)}")
    check("往回指的「上一页」**不给**（否则会把同一页拼两遍）",
          W.reading_next_url(CHAP, CHAP2_URL) is None,
          str(W.reading_next_url(CHAP, CHAP2_URL)))
    print("── 反证 D1：声明的是**下一章**时，绝不能当成本章续页 ──")
    check("指向别的章（`/3_3316/817774.html`）→ 返回 None",
          W.reading_next_url(CHAP.replace("817762_1.html", "817774.html"), CHAP_URL) is None)

    print("\n== E. 「生僻字顶替常用字」反爬（的 → 葶）==")
    check("`密闭葶肮脏`（一段里出现 3 次）→ 全部还原成「的」",
          deobfuscate("密闭葶肮脏塑料袋里，装着葶东西和葶味道")
          == "密闭的肮脏塑料袋里，装着的东西和的味道")
    check("出现得越多越稳（同一段 5 次）",
          deobfuscate("葶猫葶尾巴葶毛葶耳朵葶爪子") == "的猫的尾巴的毛的耳朵的爪子")
    check("**只出现一两次时不换**（真写到药材「葶苈」不能误伤）",
          deobfuscate("葶苈是一味药") == "葶苈是一味药")

    print("\n== F. 适配向导：用户粘什么，我们适应什么 ==")
    check("书页上能找到回首页的入口（注意「首  页」中间带空格）",
          W.home_link(DETAIL, DETAIL_URL) == BASE,
          str(W.home_link(DETAIL, DETAIL_URL)))
    check("书页上「完整目录」入口认得出",
          W.toc_entry_links(DETAIL, DETAIL_URL) == [MULU1_URL],
          str(W.toc_entry_links(DETAIL, DETAIL_URL)))
    starts = sorted(t for u, t in W._abs_links(W._prep(DETAIL), DETAIL_URL) if u == MULU1_URL)
    check("**同一个 href 上挂着多种文字**（实测「章节目录」「开始阅读」）——"
          "所以入口识别只能靠**文字**，不能靠 href 反推",
          len(set(starts)) >= 2, str(starts))

    print("\n── 反证 F1：用户给的本来就是首页时，不许凭空多一步 ──")
    called: list[str] = []
    old_get = A._get
    A._get = lambda u, **kw: (called.append(u) or (DETAIL, "utf-8"))  # type: ignore
    try:
        ad = A.Adaptation(url=BASE, name="t", display="t")
        out_url, _h, _e = A._to_site_home(BASE, DETAIL, "utf-8", ad)
        check("首页输入不被改写", out_url == BASE, out_url)
        check("**而且没有多发一次请求**", called == [], str(called))
    finally:
        A._get = old_get

    print("── 反证 F2：书页输入时必须回首页，并记一条人能看懂的话 ──")
    called.clear()
    A._get = lambda u, **kw: (called.append(u) or ("x" * 900, "utf-8"))  # type: ignore
    try:
        ad = A.Adaptation(url=DETAIL_URL, name="t", display="t")
        out_url, _h, _e = A._to_site_home(DETAIL_URL, DETAIL, "utf-8", ad)
        check("书页 → 站首页", out_url == BASE, out_url)
        check("真的去抓了首页（而不是只改了个变量）", called == [BASE], str(called))
        check("步骤里写明了「你给的是内页」",
              bool(ad.steps) and "内页" in ad.steps[-1][2], str(ad.steps[-1:]))
    finally:
        A._get = old_get

    print("\n── 反证 F3：末尾斜杠不能乱删（zxs8 不带斜杠是 404）──")
    check("`_to_site_home` 不碰首页的末尾斜杠",
          A._to_site_home(BASE, DETAIL, "utf-8",
                          A.Adaptation(url=BASE, name="t", display="t"))[0] == BASE)
    # ⚠ 必须**先剥注释再判子串**：那句"原来这里写了 rstrip 所以变 404"的说明
    #   本身就在注释里，不剥的话产品代码改对了测试反而**红**（子串匹配的老坑）。
    _src = Path(A.__file__).read_text(encoding="utf-8")
    _code = "\n".join(ln.split("#", 1)[0] for ln in _src.splitlines())
    _impl = _code.split("def _adapt_impl", 1)[1].split("\ndef ", 1)[0]
    check("`_adapt_impl` 里不再出现 `rstrip('/')`（只查代码，不查注释）",
          'rstrip("/")' not in _impl)

    print("\n── 反证 F4：走完整条适配流程，「目录可能不全」必须写进用户看得见的那步 ──")
    # 离线全链路：只把网络换成 fixture（`_get` 走 adapter 自己的入口，
    # `upgrade_toc` 那条链走 webfetch.fetch_text，两条都要替）。
    # ⚠ 首页必须**够大**：`_to_site_home` 会把 < EMPTY_SHELL(800 字节) 的页面
    #   当成"空壳/限制页"并放弃回首页 —— 太少内容的话这条链路根本走不到。
    HOME_HTML = (
        '<html><head><title>找小说吧-全本小说全文阅读</title></head><body>'
        '<a href="/">首  页</a>'
        '<form action="/search.html" method="post">'
        '<input type="text" name="s"/><input type="submit" value="搜索"/>'
        "</form>"
        '<div class="nav">' + "".join(
            f'<a href="/sort/{i}/">{i}分类</a>' for i in range(20)) + "</div>"
        '<div class="last">' + "".join(
            f'<a href="/3_3316/{816445 + i}.html">第{i + 1}章 喵</a>' for i in range(40)
        ) + "</div></body></html>"
    )

    def _fake_get(url: str, timeout: float = 12.0, data=None):
        u = url.split("#")[0]
        if u in _raw:
            return _raw[u], "utf-8"
        if u.rstrip("/") == BASE.rstrip("/"):
            return HOME_HTML, "utf-8"
        # 详情页里的章节链接（模板填出来的 id）→ 一律拿那一章 fixture 顶上，
        # 这一步只关心"目录章数/提示有没有说出来"，不关心是哪一章。
        if re.search(r"/3_3316/\d+\.html$", u):
            return _raw[CHAP_URL], "utf-8"
        raise RuntimeError(f"假网络里没有 {u}")

    _old_get = A._get
    A._get = _fake_get
    try:
        with FakeNet(dict(_raw)):
            full = A._adapt_impl(DETAIL_URL, "我们猫猫不能听这些", save=False)
        with FakeNet({k: v for k, v in _raw.items() if k != MULU2_URL}):
            part = A._adapt_impl(DETAIL_URL, "我们猫猫不能听这些", save=False)
    finally:
        A._get = _old_get

    def _step(ad, name: str) -> str:
        return next((d for s, _ok, d in ad.steps if s == name), "")

    check("（前置）整条链路能走通（离线也能适配成功）", full.ok, str(full.steps[-1:]))
    check("章数说的是**完整目录**的 119（不是详情页那 12 条）",
          "119 章" in _step(full, "打开详情页"), _step(full, "打开详情页"))
    check("目录整齐时**不**乱报「可能不全」（否则这句提示会变成狼来了）",
          "可能" not in _step(full, "打开详情页"), _step(full, "打开详情页"))
    # 反证：拿掉分页的第 2 页 → 只能拿到 101 章，且必须在**用户看得见**的那步
    # 里说出来。只写日志不算 —— 日志用户看不到（这是本轮修的坑）。
    check("缺第 2 页时章数变成 101（真的少了）",
          "101 章" in _step(part, "打开详情页"), _step(part, "打开详情页"))
    check("**并且**把「可能不全」写进了那一步（不能只落日志）",
          "部分章节" in _step(part, "打开详情页"), _step(part, "打开详情页"))

    print("\n== G. 搜索被限速时要认得出来，别把限速页当搜索结果 ==")
    COOL = (FIX / "zxs8_cooldown.html").read_text(encoding="utf-8")
    check("`搜索间隔【5】秒…` → 5", A._search_cooldown(COOL) == 5,
          str(A._search_cooldown(COOL)))
    check("无括号的写法也认：`搜索间隔 10 秒` → 10",
          A._search_cooldown("搜索间隔 10 秒，请稍后再试") == 10)
    check("限速页**不算**有效搜索结果页（否则会拿分类导航当书）",
          A._looks_like_search_result(COOL, "我们猫猫不能听这些") is False)
    print("── 反证 G1：钉住那个「只写了开括号」的历史 bug ──")
    good = re.escape("搜索间隔") + r"[【\[（(]?\s*\d{1,3}\s*[】\]）)]?\s*秒"
    bad = re.escape("搜索间隔") + r"[【\[（(]?\s*\d{1,3}\s*秒"
    check("收括号必须可选匹配：少写它就会**静默**匹配不上",
          bool(re.search(good, "搜索间隔【5】秒")) and not re.search(bad, "搜索间隔【5】秒"))

    print("\n== H. 容器嵌套时也能取正文（栈式配对 vs 非贪婪正则）==")
    nested = ('<div class="outer"><div class="word_read"><div class="read_btn">'
              '<a href="/a">上一章</a></div><p>' + "猫是很好的动物，" * 40
              + "</p></div></div>")
    blocks = {t: i for t, i in W.container_blocks(nested)}
    check("`container_blocks` 能切出嵌套 div",
          any("word_read" in t for t in blocks), str([t[:40] for t in blocks][:4]))
    if any("word_read" in t for t in blocks):
        inner = next(i for t, i in blocks.items() if "word_read" in t)
        check("里层内容没被第一层 `</div>` 截断（非贪婪正则就会截断）",
              han(inner) >= 240, f"实际 {han(inner)} 汉字")
    naive = re.search(r'<div[^>]*class="word_read"[^>]*>([\s\S]*?)</div>', nested)
    check("── 反证 H1：旧的写法（非贪婪）确实会截断 ──",
          naive is not None and han(naive.group(1)) < 20,
          f"非贪婪取到 {han(naive.group(1)) if naive else -1} 汉字")

    print("\n== I. 正文尾巴上的「相邻推荐」不能读进正文 ==")
    # 实测 zxs8 的原文（就写在 word_read **里面**）：
    #   <p style="font-size:12px;">相邻推荐:<a href="/3_3314/">…</a>&nbsp;…</p>
    # 不删的话正文尾巴上挂着 20 个别的书名，用户读着读着就串了书。
    rec = ('<p style="font-size:12px;">相邻推荐:'
           + "".join(f'<a href="/3_9{n:03d}/">某本书{n}</a>&nbsp;&nbsp;' for n in range(20))
           + "</p>")
    check("一段 20 个书名链接 → 整段删掉", W._drop_link_paras(rec) == "")
    check("正文段落（没有链接）原样保留",
          W._drop_link_paras("<p>小猫慢慢睁开了眼睛。</p>")
          == "<p>小猫慢慢睁开了眼睛。</p>")
    check("只有 2 个链接的段落**不算**推荐（门槛 3）",
          W._drop_link_paras('<p><a href="/a">甲</a><a href="/b">乙</a></p>') != "")
    print("── 反证 I1：目录（`<li>` 逐条列章节）绝不能被当推荐删掉 ──")
    mulu_html = ('<ul><li><a href="/1.html">第1章</a></li>'
                 '<li><a href="/2.html">第2章</a></li>'
                 '<li><a href="/3.html">第3章</a></li></ul>')
    check("`<li>` 列表原样保留（只认 `<p>` 就是为了这个）",
          W._drop_link_paras(mulu_html) == mulu_html)
    print("── 反证 I2：段落里自由文字够多时不许删 ──")
    keep2 = ('<p>小猫看着<a href="/a">甲</a>，又看看<a href="/b">乙</a>，'
             '还有<a href="/c">丙</a>，慢慢地睡着了，梦里有很多鱼。</p>')
    check("夹在叙述里的链接段落原样保留", W._drop_link_paras(keep2) == keep2)
    got_rec = W.clean_body(W.extract_content(
        '<div class="word_read"><p>' + "猫在窗台上打盹。" * 60 + "</p>" + rec + "</div>",
        hint="word_read"))
    check("**集成**：走完整链路也读不到推荐",
          "某本书3" not in got_rec and "猫在窗台上打盹" in got_rec,
          got_rec[-40:])

    print("\n== J. 「一章拆多页」的两套机制必须收敛（模板式 vs 声明式）==")
    # 两套机制历史上是**各管一段**的：
    #   · `page_url`（模板式）：只会 `xxx.html → xxx_2.html`，从续页出发还会
    #     拼成 `xxx_1_2.html`（对不上真实续页）—— 静默少给后半章。
    #   · `reading_next_url`（声明式）：只认页面自己写的续页地址。
    # 只走其中一条，就会在另一种站上悄悄少给。这里把两条都钉住。
    print("── J1：模板式 —— 剥掉已有的 `_N` 再叠 ──")
    check("`x.html` → `x_2.html`",
          page_url("https://s/a/x.html", 2) == "https://s/a/x_2.html",
          str(page_url("https://s/a/x.html", 2)))
    check("**从续页出发**：`x_1.html` → `x_3.html`（不是 `x_1_3.html`）",
          page_url("https://s/a/x_1.html", 3) == "https://s/a/x_3.html",
          str(page_url("https://s/a/x_1.html", 3)))
    check("非 `.html`（推不出模板）→ None，宁可不拼也不拼错",
          page_url("https://s/a/x", 2) is None, str(page_url("https://s/a/x", 2)))
    # 反证：把**旧写法**跑一遍，证明"剥旧 `_N`"这一条不是摆设 ——
    # 旧写法确实会从续页拼出对不上的地址。
    _om = re.match(r"^(.*?)(\.html?)$", "https://s/a/x_1.html", re.I)
    check("反证：旧写法 `^(.*?)(\\.html?)$` 拼出的是 `x_1_3.html`（永远对不上）",
          f"{_om.group(1)}_3{_om.group(2)}" == "https://s/a/x_1_3.html")

    print("\n── J2：声明式 —— 页面没标页数、只声明了续页时，后半章也必须读到 ──")
    _CH = "https://t.test/a/1.html"
    _CH1 = "https://t.test/a/1_1.html"
    _CH2 = "https://t.test/a/1_2.html"

    def _chap(body: str, nxt: str = "") -> str:
        js = f"<script>var zz = '{nxt}';</script>" if nxt else ""
        return (f'<html><body><div class="word_read">{body}</div>{js}'
                "</body></html>")

    def _src(pages: dict[str, str]) -> "object":
        cfg = {"name": "t.test", "base_url": "https://t.test/",
               "chapter_paged": True,
               "content_re": r'<div class="word_read">([\s\S]*?)</div>'}
        src = C.ConfiguredSource(cfg)
        old = C.fetch_text
        C.fetch_text = lambda url, **kw: pages[url.split("#")[0]]
        return src, old

    # 场景 1：**没有**「第(x/y)页」标记，只有一行 JS 声明续页。
    # 旧实现走 `_fetch_paged_chapter` 会因为 `page_mark` 为空而**直接返回第 1 页**
    # —— 用户读到的是半章，界面上看不出任何异常。
    pages = {_CH: _chap("猫咪在窗台上打盹。" * 20, nxt=_CH1),
             _CH1: _chap("可是罐头还没有开。" * 20)}
    src, old = _src(pages)
    try:
        got = src._fetch_paged_chapter(Chapter(1, "第1章 喵", url=_CH))
    finally:
        C.fetch_text = old
    check("**两页都读到**（旧实现这里只有前一页）",
          "猫咪在窗台上打盹" in got and "可是罐头还没有开" in got, got[:40])
    # 反证：把声明行拿掉，后半段必须跟着消失 —— 说明上面那条是靠机制过的，
    # 不是恒真（内容碰巧进了正文）。
    pages2 = {_CH: _chap("猫咪在窗台上打盹。" * 20)}
    src, old = _src(pages2)
    try:
        got2 = src._fetch_paged_chapter(Chapter(1, "第1章 喵", url=_CH))
    finally:
        C.fetch_text = old
    check("反证：没有续页声明时**只应**拿到第 1 页（不是恒真）",
          "猫咪在窗台上打盹" in got2 and "可是罐头还没有开" not in got2)

    print("── J3：三页链式声明（每一步都要问页面自己）──")
    pages3 = {_CH: _chap("第一段。" * 20, nxt=_CH1),
              _CH1: _chap("第二段。" * 20, nxt=_CH2),
              _CH2: _chap("第三段。" * 20)}
    src, old = _src(pages3)
    try:
        got3 = src._fetch_paged_chapter(Chapter(1, "第1章 喵", url=_CH))
    finally:
        C.fetch_text = old
    check("三段全在（链式跟到底）",
          all(t in got3 for t in ("第一段", "第二段", "第三段")), got3[:40])

    print("── J4：页码越界返回同一页时不许拼重复 ──")
    pages4 = {_CH: _chap("同一段。" * 20, nxt=_CH1),
              _CH1: _chap("同一段。" * 20)}   # 站里返回了跟第 1 页一样的内容
    src, old = _src(pages4)
    try:
        got4 = src._fetch_paged_chapter(Chapter(1, "第1章 喵", url=_CH))
    finally:
        C.fetch_text = old
    check("内容没变就停（同一页不会被拼 N 遍）",
          got4.count("同一段。") == 20, f"实际出现 {got4.count('同一段。')} 次")

    print("── J5：带「第(1/2)页」标记的老机制仍然工作 ──")
    # 有页码标记时按**页码模板**拼，所以续页在这里是 `1_2.html`
    # （没有声明式续页可用时，`page_url` 就是唯一的线索）。
    pages5 = {_CH: _chap("（1/2 页）前半段。" * 20),
              _CH2: _chap("后半段。" * 20)}
    src, old = _src(pages5)
    try:
        got5 = src._fetch_paged_chapter(Chapter(1, "第1章 喵", url=_CH))
    finally:
        C.fetch_text = old
    check("按页数拼齐",
          "前半段" in got5 and "后半段" in got5, got5[:40])

    print("\n── J6：目录分页的**预算上限**：停在半路还硬说「完整」是静默截断 ──")
    def _mulu_page(n: int) -> str:
        first = (n - 1) * 3 + 1
        links = "".join(f'<a href="/b/1/{first + i}.html">第{first + i}章 喵{i}</a>'
                        for i in range(3))
        nxt = (f'<a href="/b/1/mulu/{n + 1}.html">下一页</a>' if n < 8 else "")
        return f'<html><body><div class="list">{links}</div>{nxt}</body></html>'

    _MU1 = "https://t.test/b/1/mulu/1.html"
    _mpages = {f"https://t.test/b/1/mulu/{n}.html": _mulu_page(n) for n in range(1, 9)}
    _jp1 = _mpages[_MU1]
    _jtoc = W.extract_toc(_jp1, _MU1, min_items=3)
    check("（前置）第 1 页读出 3 章、且页面还有「下一页」",
          len(_jtoc) == 3 and W._next_page_url(_jp1, _MU1) is not None,
          f"{len(_jtoc)} 条")
    with FakeNet(_mpages):
        _jm, _ju, _jgot, _jpend = W._merge_paged(_jtoc, _jp1, _MU1, budget=5)
    # 每页 3 章 → 跟满 budget=5 页就是 15 章（第 8 页还没走到）
    check("跟满 5 页就停下（不会无限跟）", _jgot == 15, f"实际 {_jgot}")
    check("**停在半路必须标 pending**（后面明明还有「下一页」）", bool(_jpend))
    with FakeNet(_mpages):
        _jt2, _ju2, _jnote = W.upgrade_toc(_jtoc, _jp1, _MU1)
    check("并且**如实提示**可能只含部分章节（沉默 = 用户以为这就是全书）",
          bool(_jnote) and "章" in _jnote, repr(_jnote))
    # 反证：目录到头的站（最后一页没有「下一页」）不该被误标成"可能不全"。
    _short = {k: v for k, v in _mpages.items() if k.endswith(("1.html", "2.html"))}
    _short["https://t.test/b/1/mulu/2.html"] = (
        _mulu_page(2).replace('<a href="/b/1/mulu/3.html">下一页</a>', ""))
    with FakeNet(_short):
        _sm, _su, _sgot, _spend = W._merge_paged(_jtoc, _jp1, _MU1, budget=5)
    check("反证：真到最后一页（没有「下一页」）→ 不许误报 pending",
          _sgot == 3 and _spend is False, f"got={_sgot} pending={_spend}")

    print("\n" + "=" * 62)
    print(f"通过 {_passed} · 失败 {len(_fail)}")
    for f in _fail:
        print("  ✗ " + f)
    print("=" * 62)
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
