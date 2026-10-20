# -*- coding: utf-8 -*-
"""站点学习（app/sitelearn.py）的行为测试 —— 全部**离线**，不发网络请求。

为什么值得单独测：`learn_site` 的正则和判定逻辑是整个「L 源自我壮大」
的地基。它一旦悄悄失效，表现是**「学了半天什么都没学到」**，
而不是报错 —— 这种 silent failure 只能靠断言固定的 HTML 夹具兜住。

测什么：
  1. `<form>`（GET / POST 两种）能不能被认出来
  2. 内联脚本 / 外部 JS 里 `document.writeln` 出来的表单能不能被认出来
     （**实测踩过**：29zw 的搜索框就是这么写的，静态 HTML 里根本没有 form）
  3. 搜索链接（GET 形态，带示例关键词）能不能反推出模板
  4. 爆破候选的生成与去重
  5. 模板拼接（`{kw}` → 编码后的关键词）
  6. 只有真正「回结果」的模板才算数（掉回首页 / 命中太少都要判否）

用法：python tools/test_sitelearn.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import sitelearn  # noqa: E402

PASS = 0
FAIL = 0


def ok(cond: bool, label: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {label}")
    else:
        FAIL += 1
        print(f"  ✗ {label}")


def eq(got, want, label: str) -> None:
    ok(got == want, f"{label}（得到 {got!r}，期望 {want!r}）")


# ---------------------------------------------------------------------------
# 1) <form>
# ---------------------------------------------------------------------------
def test_form_get() -> None:
    print("\n[<form> GET]")
    html = """
    <html><body>
    <form action="/search.php" method="get">
      <input type="text" name="searchkey" placeholder="搜索">
      <input type="submit" value="搜索">
    </form>
    </body></html>
    """
    got = sitelearn.learn_from_html(html, "https://a.com/", "a.com")
    eq(len(got), 1, "认出一个 form")
    eq(got[0]["tpl"], "/search.php?searchkey={kw}", "模板拼对了")
    eq(got[0]["method"], "get", "方法是 GET")
    eq(got[0]["via"], "form", "来源标成 form")


def test_form_post() -> None:
    print("\n[<form> POST —— 实测 384g 就是这种]")
    html = """
    <form action="/search.php" method="post">
        <input id="text1" type="text" name="s" />
        <input id="text2" type="submit" value="点击搜索"/>
    </form>
    """
    got = sitelearn.learn_from_html(html, "https://b.com/", "b.com")
    eq(len(got), 1, "认出一个 POST form")
    eq(got[0]["tpl"], "/search.php", "模板只有路径（关键词在 body）")
    eq(got[0]["method"], "post", "方法是 POST")
    eq(got[0]["via"], "form-post", "来源标成 form-post")
    eq(got[0]["body"], {"s": "{kw}"}, "body 里放着关键词模板")


def test_form_skips_bad_inputs() -> None:
    print("\n[<form> 噪声过滤]")
    html = """
    <form action="/login.php" method="get">
      <input type="text" name="username">
      <input type="password" name="password">
    </form>
    """
    got = sitelearn.learn_from_html(html, "https://c.com/", "c.com")
    eq(got, [], "登录框不该被当成搜索框")


def test_form_empty_action_uses_page() -> None:
    print("\n[<form> action 为空时用当前页路径]")
    html = '<form method="get"><input type="text" name="wd"></form>'
    got = sitelearn.learn_from_html(html, "https://d.com/s/index.html", "d.com")
    eq(len(got), 1, "认出来了")
    eq(got[0]["tpl"], "/s/index.html?wd={kw}", "用当前页路径拼模板")


# ---------------------------------------------------------------------------
# 2) JS 里 write 出来的表单
# ---------------------------------------------------------------------------
def test_inline_script_form() -> None:
    print("\n[内联脚本里的搜索表单 —— 实测 29zw 的写法]")
    # 注意：引号被转义成了 \'，这是 book.js 里的真实形态
    html = (
        "<html><body><script>\n"
        "function searchBox(){document.writeln(\""
        "<form action=\\'/modules/article/search.php\\' target='_blank'>"
        "<input type=\\'text\\' name=\\'searchkey\\'>"
        "</form>\");}\n"
        "</script></body></html>"
    )
    got = sitelearn.learn_from_scripts(html, "https://e.com/", "e.com")
    eq(len(got), 1, "从内联脚本里挖出了表单")
    eq(got[0]["tpl"], "/modules/article/search.php?searchkey={kw}", "模板拼对了")
    eq(got[0]["via"], "script", "来源标成 script")


def test_bare_js_file() -> None:
    print("\n[整份 JS 文件（不带 <script> 包裹）]")
    js = (
        "function searchBox(){document.writeln(\"<form action='/search.php'>"
        "<input type='text' name='keyword'></form>\");}"
    )
    got = sitelearn.learn_from_scripts(js, "https://f.com/", "f.com")
    eq(len(got), 1, "裸 JS 也能认")
    eq(got[0]["tpl"], "/search.php?keyword={kw}", "模板拼对了")


def test_script_without_search_is_ignored() -> None:
    print("\n[无关脚本不该被认]")
    js = "var x=1; function go(){location.href='/a/b';}"
    eq(sitelearn.learn_from_scripts(js, "https://g.com/", "g.com"), [],
       "没有 search 痕迹的脚本不认")


# ---------------------------------------------------------------------------
# 3) 搜索链接
# ---------------------------------------------------------------------------
def test_search_link() -> None:
    print("\n[搜索链接（带示例关键词）]")
    html = '<a href="/s?q=%E9%83%BD%E5%B8%82">搜索</a>'
    got = sitelearn.learn_from_html(html, "https://h.com/", "h.com")
    eq(len(got), 1, "认出搜索链接")
    eq(got[0]["tpl"], "/s?q={kw}", "把示例值换成了 {kw}")
    eq(got[0]["via"], "link", "来源标成 link")


def test_external_link_ignored() -> None:
    print("\n[跳外域的搜索链接不学]")
    html = '<a href="https://other.com/search?q=x">搜索</a>'
    eq(sitelearn.learn_from_html(html, "https://i.com/", "i.com"), [],
       "外站搜索入口不当成自己的")


def test_kwless_template_rejected() -> None:
    """「带不了关键词」的模板一律不算搜索接口。

    线上实测（2026-10-21）：14 个"可搜源"里有 6 个的模板是 `/search.php`
    `/search` `/search.html` —— **一个 `{kw}` 占位都没有**。
    `build_url()` 只做 `{kw}` 替换，没占位就等于关键词根本没发出去：
    请求打开的是站点搜索页/首页（那儿本来就有一堆书），
    于是 `verify_tpl` 数到十几条链接就判真、控制实验也判不了假。
    """
    print("\n[带不了关键词的模板不算搜索接口]")
    ok(sitelearn.tpl_carries_kw("/search.php?q={kw}"), "GET 带 {kw} → 能带")
    ok(not sitelearn.tpl_carries_kw("/search.html"), "GET 裸路径 → 带不了")
    ok(not sitelearn.tpl_carries_kw("/search"), "GET 连扩展名都没有 → 带不了")
    ok(sitelearn.tpl_carries_kw("/search.php", method="post",
                                body={"s": "{kw}"}),
       "POST + body 里带 {kw} → 能带（实测 384g 就是这种）")
    ok(not sitelearn.tpl_carries_kw("/search.php", method="post",
                                    body={"s": "x"}),
       "POST 但 body 里也没占位 → 带不了")
    ok(not sitelearn.tpl_carries_kw(""), "空模板 → 带不了")

    # 学的时候就不许学进来：`<a href="/search.html">搜索</a>` 这种链接
    # 里没有可替换的示例值，抠完还是裸路径 —— 学它等于给自己埋一个假站。
    html = ('<a href="/search.html">搜索</a>'
            '<a href="/search.php?q=%E9%83%BD%E5%B8%82">站内搜索</a>')
    got = sitelearn.learn_from_html(html, "https://h.com/", "h.com")
    tpls = [c["tpl"] for c in got]
    eq(tpls, ["/search.php?q={kw}"],
       "裸链接 /search.html 被丢掉，只剩真的能带关键词的那条")


# ---------------------------------------------------------------------------
# 4) 爆破候选
# ---------------------------------------------------------------------------
def test_guess_templates() -> None:
    print("\n[爆破候选]")
    got = sitelearn.guess_templates("x.com")
    tpls = [c["tpl"] for c in got]
    ok("/search.php?q={kw}" in tpls, "包含经典 /search.php?q=")
    ok("/modules/article/search.php?searchkey={kw}" in tpls,
       "包含杰奇 CMS 的 /modules/article/search.php?searchkey=")
    eq(len(tpls), len(set(tpls)), "候选之间不重复")
    ok(all("{kw}" in t for t in tpls), "每条候选都带 {kw} 占位")


# ---------------------------------------------------------------------------
# 5) 模板拼接
# ---------------------------------------------------------------------------
def test_build_url() -> None:
    print("\n[模板拼接]")
    u = sitelearn.build_url("/search.php?q={kw}", "a.com", "都市")
    eq(u, "https://a.com/search.php?q=%E9%83%BD%E5%B8%82", "UTF-8 编码正确")
    u2 = sitelearn.build_url("/search.php?q={kw}", "a.com", "都市", enc="gbk")
    ok("%E9%83%BD" not in u2 and "%" in u2, "GBK 用的是另一套转义")
    u3 = sitelearn.build_url("/search.php?q={kw}", "a.com", "abc",
                            scheme="http")
    ok(u3.startswith("http://"), "可以指定 http")


def test_make_tpl() -> None:
    print("\n[make_tpl]")
    eq(sitelearn.make_tpl("a.com", "https://a.com/search?q=1"),
       "/search?q=1", "带域名时只取路径+查询")
    eq(sitelearn.make_tpl("a.com", "search.php"), "/search.php", "补上前导斜杠")


# ---------------------------------------------------------------------------
# 6) 验证：只有真能搜出结果才算
# ---------------------------------------------------------------------------
def test_verify_rejects_homepage_redirect(monkeypatch_html: str = "") -> None:
    print("\n[verify_tpl：掉回首页要判否]")
    import app.webfetch as wf
    import app.utils as ut

    orig_fetch = ut.fetch_text
    orig_toc = wf.extract_toc

    # 造一个「重定向回首页」的假响应
    ut.fetch_text = lambda url, **kw: ("<html>首页</html>", "https://z.com/")
    try:
        # extract_toc 在这条路上不该被调用（首页路径直接判否）
        called = {"n": 0}

        def _toc(*a, **k):
            called["n"] += 1
            return []

        wf.extract_toc = _toc
        got = sitelearn.verify_tpl("/search?q={kw}", "z.com", "三体")
        eq(got, None, "掉回首页 → None")
        eq(called["n"], 0, "压根没去数链接")
    finally:
        ut.fetch_text = orig_fetch
        wf.extract_toc = orig_toc


def test_verify_accepts_real_results() -> None:
    print("\n[verify_tpl：真有一堆章节链接才算成]")
    import app.webfetch as wf
    import app.utils as ut

    orig_fetch = ut.fetch_text
    orig_toc = wf.extract_toc
    ut.fetch_text = lambda url, **kw: (
        "<html>" + "x" * 600 + "</html>", "https://z.com/search?q=1")
    try:
        wf.extract_toc = lambda html, base: [{"title": f"第{i}章", "url": "#"} for i in range(20)]
        got = sitelearn.verify_tpl("/search?q={kw}", "z.com", "三体")
        eq(got, 20, "20 条链接 → 返回 20")

        wf.extract_toc = lambda html, base: [{"title": "第1章", "url": "#"}]
        got2 = sitelearn.verify_tpl("/search?q={kw}", "z.com", "三体")
        eq(got2, None, "只有 1 条链接 → 判否（那是首页导航的量级）")
    finally:
        ut.fetch_text = orig_fetch
        wf.extract_toc = orig_toc


def test_verify_post_body() -> None:
    print("\n[verify_tpl：POST 把关键词放 body]")
    import app.webfetch as wf
    import app.utils as ut

    orig_fetch = ut.fetch_text
    orig_toc = wf.extract_toc
    seen = {}

    def _fetch(url, **kw):
        seen["url"] = url
        seen["data"] = kw.get("data")
        return "<html>" + "x" * 600 + "</html>", "https://z.com/search"

    ut.fetch_text = _fetch
    try:
        wf.extract_toc = lambda html, base: [{"title": f"第{i}章", "url": "#"} for i in range(10)]
        sitelearn.verify_tpl("/search.php", "z.com", "三体",
                             method="post", body={"s": "{kw}"})
        eq(seen["data"], {"s": "三体"}, "关键词进了请求体")
        ok("{kw}" not in (seen["url"] or ""), "URL 里没有占位符残留")
    finally:
        ut.fetch_text = orig_fetch
        wf.extract_toc = orig_toc


def main() -> int:
    print("=== sitelearn 离线测试 ===")
    test_form_get()
    test_form_post()
    test_form_skips_bad_inputs()
    test_form_empty_action_uses_page()
    test_inline_script_form()
    test_bare_js_file()
    test_script_without_search_is_ignored()
    test_search_link()
    test_external_link_ignored()
    test_kwless_template_rejected()
    test_guess_templates()
    test_build_url()
    test_make_tpl()
    test_verify_rejects_homepage_redirect()
    test_verify_accepts_real_results()
    test_verify_post_body()

    print(f"\n{'=' * 40}")
    print(f"通过 {PASS} · 失败 {FAIL}")
    if FAIL:
        print("=== 有失败 ===")
        return 1
    print("=== 全部通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
