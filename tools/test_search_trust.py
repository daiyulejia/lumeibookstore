"""判据：**"可搜源"必须真的在按关键词搜**，不许把"站点吐首页"算成搜索。

为什么单开一套
--------------
线上实测（2026-10-21）：21 个"已学会搜索"的站里 **9 个是假的**。
它们形如 `/?q={kw}` / `/search.php?q={kw}`，站点根本不认这个参数，
照常返回首页或分类导航 —— 首页当然有一堆"像章节的链接"，于是旧判据
（`verify_tpl`：数到 ≥3 个章节链接就算成）把它们全判成"搜到了"。

后果不是"搜出错书"（相关性排序会把它们筛掉），而是：
  · 界面上"综合 N 站"里有一批站**永远不可能**贡献一条结果
  · 每次搜索都要多打这些站、多等它们
也就是说，掺假的可搜源会把"我们的来源有多广"变成一句假话。
这类缺陷不报错、不写日志，人工回归**必漏**，所以判据必须钉死。

这一套同时钉住三件在真实站群上验证过的事：
  1. 控制实验：换一个绝对搜不到的书名，结果集一模一样 → 判假
  2. scheme 必须从"刚刚抓成功那一页"推断（老站只有 http，写死 https 就永远验不过）
  3. 爆破表的顺序 —— 预算能覆盖到的前 N 条里必须包含实测最高频的组合
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ⚠ 复核要用来源库 —— 必须先把它指到临时目录，否则会动生产库
#   （`cache/registry.json` 是用户攒了几个月的资产，见 test_registry.py 的注释）。
os.environ["NOVEL_REGISTRY"] = os.path.join(
    tempfile.mkdtemp(prefix="trust-test-"), "registry.json")

from app import discovery, registry, sitelearn, utils, webfetch   # noqa: E402
from app.sitelearn import CANARY_KW, CONTROL_KW                   # noqa: E402

OK = 0
FAIL = 0
CALLS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {extra}")


# ---------------------------------------------------------------------------
# 假网页
# ---------------------------------------------------------------------------
# host → {关键词: 结果 URL 列表}；关键字 "*" = 不管关键词都吐这个
PAGES: dict[str, dict[str, list[str]]] = {}
_PAD = "<html><body>" + ("x" * 600) + "<pre>"


def _kw_of(url: str, data) -> str:
    if data:
        for v in data.values():
            return str(v)
    q = parse_qs(urlparse(url).query)
    for vs in q.values():
        if vs:
            return vs[0]
    return ""


def _fake_fetch(url: str, *a, **k):
    CALLS.append(url)
    host = (urlparse(url).hostname or "").lower()
    kw = _kw_of(url, k.get("data"))
    table = PAGES.get(host, {})
    urls = table.get(kw) or table.get("*") or []
    html = _PAD + "\n".join(urls) + "</pre></body></html>"
    return html, url


def _fake_toc(html: str, base_url: str = ""):
    body = html.split("<pre>", 1)[-1]
    return [{"url": ln.strip(), "title": ""}
            for ln in body.splitlines() if ln.strip().startswith("http")]


def install() -> None:
    utils.fetch_text = _fake_fetch
    webfetch.extract_toc = _fake_toc
    sitelearn.fetch_text = _fake_fetch      # learn_site 内部按需导入，保险起见


REAL = "斗破苍穹"


def main() -> int:
    install()

    print("\n—— 控制实验：换一个搜不到的书名，结果集一模一样 → 判假 ——")
    # 假的：不管关键词是啥都吐同一批"像章节的链接"
    PAGES["fake.com"] = {"*": ["https://fake.com/x/1.html",
                               "https://fake.com/x/2.html",
                               "https://fake.com/x/3.html",
                               "https://fake.com/x/4.html"]}
    # 真的：结果随关键词变
    PAGES["real.com"] = {
        REAL: ["https://real.com/b/1.html", "https://real.com/b/2.html",
               "https://real.com/b/3.html"],
        CONTROL_KW: [],
    }
    fake_hits = sitelearn._fetch_hits("/?q={kw}", "fake.com", REAL)
    check("先确认假站「看起来」搜到了（否则下面等于没测）", fake_hits[0] >= 3,
          str(fake_hits[0]))
    check("★ 假站被控制实验抓住", sitelearn.control_says_fake(
        "/?q={kw}", "fake.com", urls=fake_hits[1], hits=fake_hits[0]))
    check("★ 假站 verify_search 返回 None（不许记成可搜源）",
          sitelearn.verify_search("/?q={kw}", "fake.com", REAL) is None)

    real_hits = sitelearn._fetch_hits("/?q={kw}", "real.com", REAL)
    check("真站控制实验放行", not sitelearn.control_says_fake(
        "/?q={kw}", "real.com", urls=real_hits[1], hits=real_hits[0]))
    got = sitelearn.verify_search("/?q={kw}", "real.com", REAL)
    check("★ 真站 verify_search 通过", bool(got), str(got))

    print("\n—— 控制实验的两个反向：不能凭「搜不到」冤枉人 ——")
    # 换个关键词，真站啥也没搜到（库里没有那本书）→ 不能判假
    check("控制词搜不到（0 条）不算假 —— 那只是这站没这本书",
          not sitelearn.control_says_fake(
              "/?q={kw}", "real.com", urls=real_hits[1], hits=real_hits[0],
              control_kw="完全另一本不存在的书"))
    # 部分重合：4 条里 2 条重合 → Jaccard 2/6=0.33 < 0.5 → 仍算真
    PAGES["half.com"] = {
        REAL: ["https://half.com/a.html", "https://half.com/b.html",
               "https://half.com/c.html", "https://half.com/d.html"],
        CONTROL_KW: ["https://half.com/a.html", "https://half.com/b.html",
                     "https://half.com/z.html"],
    }
    hh = sitelearn._fetch_hits("/?q={kw}", "half.com", REAL)
    check("部分重合（≤ 0.5）不算假 —— 别把「推荐位混进结果」误杀",
          not sitelearn.control_says_fake(
              "/?q={kw}", "half.com", urls=hh[1], hits=hh[0]))
    check("门槛常量就摆在 0.24（真站最高）和 0.66（假站最低）之间",
          0.24 < sitelearn.CONTROL_SAME_RATIO < 0.66,
          str(sitelearn.CONTROL_SAME_RATIO))

    print("\n—— 学站：假搜索不许被学成模板 ——")
    got_fake = sitelearn.learn_site(
        "fake.com", page_url="https://fake.com/", html="<html>首页</html>",
        probe_keyword=REAL, budget=4, js_budget=0)
    check("★ 学会一个假模板 = 白占一个可搜源名额", not got_fake.get("search_tpl"),
          str(got_fake))
    got_real = sitelearn.learn_site(
        "real.com", page_url="https://real.com/", html="<html>首页</html>",
        probe_keyword=REAL, budget=4, js_budget=0)
    check("真搜索照常学下来", bool(got_real.get("search_tpl")), str(got_real))

    print("\n—— scheme：老站只有 http，写死 https 就永远验不过 ——")
    # 线上实测 www.tengc.com：https 直接 403，form 是 POST /search49.html
    scheme_seen: list[str] = []

    def _probe_fetch(url, *a, **k):
        CALLS.append(url)
        scheme_seen.append(urlparse(url).scheme)
        host = (urlparse(url).hostname or "").lower()
        kw = _kw_of(url, k.get("data"))
        table = PAGES.get(host, {})
        urls = table.get(kw) or table.get("*") or []
        return _PAD + "\n".join(urls) + "</pre></body></html>", url

    utils.fetch_text = _probe_fetch
    PAGES["old.com"] = {REAL: ["https://old.com/1.html", "https://old.com/2.html",
                               "https://old.com/3.html"],
                        CONTROL_KW: ["https://old.com/9.html"]}
    form_html = ('<form method="post" action="/search49.html">'
                 '<input type="text" name="searchkey"></form>')
    got_old = sitelearn.learn_site(
        "old.com", page_url="http://old.com/index.html", html=form_html,
        probe_keyword=REAL, budget=4, js_budget=0)
    check("★ 从 page_url 推断出 http（不是写死 https）",
          bool(got_old.get("search_tpl")), str(got_old))
    check("★ 验证请求真的打的是 http",
          bool(scheme_seen) and set(scheme_seen) == {"http"}, str(set(scheme_seen)))
    check("agent 给的 scheme 优先（不被 page_url 覆盖）",
          sitelearn._resolve_scheme("x.com", "http://x.com/", "https") == "https")

    print("\n—— 爆破表顺序：预算覆盖不到 = 等于表里没有 ——")
    table = [c["tpl"] for c in sitelearn.guess_templates("x.com")]
    budget = 12
    first = table[:budget]
    check("★ 实测最高频的 `/?s=` 必须排在预算能覆盖到的范围内",
          "/?s={kw}" in first, f"排在第 {table.index('/?s={kw}') + 1} 位" if "/?s={kw}" in table else "压根没有")
    check("杰奇 CMS 组合排最前（老笔趣阁站的主流形态）",
          table[0].startswith("/modules/article/search.php"), table[0])
    check("每条候选都带 {kw} 占位（否则拼出来的 URL 搜不了）",
          all("{kw}" in t for t in table), str([t for t in table if "{kw}" not in t])[:80])
    check("候选不重复", len(table) == len(set(table)), f"{len(table)} vs {len(set(table))}")

    print("\n—— 别重复发请求：一个候选最多 2 次（探编码 + 控制实验）——")
    CALLS.clear()
    sitelearn.learn_site("real.com", page_url="https://real.com/",
                         html="<html>首页</html>", probe_keyword=REAL,
                         budget=1, js_budget=0)
    check("只验一个候选时请求数 ≤ 4（utf-8 通了就不再试 gb18030）",
          len(CALLS) <= 4, f"发了 {len(CALLS)} 个：{CALLS}")

    # ------------------------------------------------------------------
    print("\n—— 复核：库里那批假模板必须撤得掉，真模板不许误撤 ——")
    # 线上第一轮复核只撤掉 5 个（该撤 9 个）：另外 4 个是"库里没有它的书名"
    # 或者"那本书在这站搜不到"，于是判不了真假，就留着了。
    # 现在补一次**通用书名**探测（《斗破苍穹》几乎每个小说站都有），
    # 假站两个关键词都给同一批结果，照样抓得住。
    utils.fetch_text = _fake_fetch
    webfetch.extract_toc = _fake_toc
    registry.flush()

    # ① 库里没有书名，但模板是假的（任何关键词都吐同一批分类导航）
    registry.note_site("nobook-fake.com", ok=True)
    registry.note_search_tpl("nobook-fake.com", "/?q={kw}")
    PAGES["nobook-fake.com"] = {"*": ["https://nobook-fake.com/c/1.html",
                                      "https://nobook-fake.com/c/2.html",
                                      "https://nobook-fake.com/c/3.html"]}
    # ② 有书名，但那个书名在这站搜不到；模板是真的（结果随关键词变）
    registry.note_site("ownbook-real.com", ok=True)
    registry.note_book("http://ownbook-real.com/1", title="药鼎仙途最新章节列表",
                       host="ownbook-real.com", ok=True)
    registry.note_search_tpl("ownbook-real.com", "/?q={kw}")
    PAGES["ownbook-real.com"] = {
        CANARY_KW: ["https://ownbook-real.com/b/1.html",
                    "https://ownbook-real.com/b/2.html",
                    "https://ownbook-real.com/b/3.html"],
        CONTROL_KW: ["https://ownbook-real.com/other/9.html"],
    }
    # ③ 什么都不给（搜不到）—— 不能凭"搜不到"撤别人的模板
    registry.note_site("quiet.com", ok=True)
    registry.note_search_tpl("quiet.com", "/?q={kw}")
    PAGES["quiet.com"] = {}

    rep = discovery.reverify_sites(["nobook-fake.com", "ownbook-real.com",
                                    "quiet.com"])
    check("★ 库里没有书名的假站也撤得掉（靠通用书名兜底）",
          rep["dropped"] == 1 and rep["kept"] == 2, str(rep))
    check("★ 假站模板真的清空了",
          not (registry.known_site("nobook-fake.com").get("search_tpl") or ""),
          str(registry.known_site("nobook-fake.com")))
    check("自己书名搜不到、但模板是真的站不许误撤",
          bool(registry.known_site("ownbook-real.com").get("search_tpl")))
    check("搜不到任何东西的站不许误撤（判不了真假就别动它）",
          bool(registry.known_site("quiet.com").get("search_tpl")))
    check("复核记录了「只能靠通用书名」的那一类",
          rep.get("canary_only") == 2, str(rep))
    check("撤掉的站会重新回到待学队列（还能再学一次真的）",
          "nobook-fake.com" in registry.learn_candidates())

    print("\n" + "=" * 60)
    print(f"通过 {OK} · 失败 {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
