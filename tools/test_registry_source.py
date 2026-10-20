# -*- coding: utf-8 -*-
"""自有来源（app/sources/registry_source.py）的搜索链路回归。

为什么值得单独立一套测试
------------------------
这是 L 源升级的**兑现环节**：夜间学到的站内搜索模板，最终要靠
`RegistrySource.search() → _search_one() → _extract_book_links()` 变成
搜索结果。它一断，表现为「每次搜索悄悄少一批自有源结果」——
不报错、日志只有一句 debug，别的测试全绿。

而这段逻辑恰好最容易静默坏（本文件历史上踩过的坑都在注释里）：
  · `_BOOK_PATH` 量词写成 `{2,}` → 模板化路径上**永不命中**，不报错；
  · 章节链接往往比书链接**更多**，只按数量排会把「最新章节列表」当结果；
  · `/html/102/102114/79.html` 被 `_BOOK_PATH` **部分命中** → 章节页混进结果。

所以这里用一页**照真实站点形状造的**搜索结果页（杰奇 CMS 系的
`/html/#/#/` 书页 + 每本带一条 `/html/#/#/#.html` 最新章节 +
零散导航），把「书赢、章节输、导航出局」钉成判据，并配反证。

用法： python tools/test_registry_source.py
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 双保险：导入期就把库文件指到临时目录（同 tools/test_registry.py）——
# `_search_one` 会调 registry.note_site 记成败，不隔离就写进生产库。
_TMPDIR = pathlib.Path(tempfile.mkdtemp(prefix="novel-regsrc-test-"))
os.environ["NOVEL_REGISTRY"] = str(_TMPDIR / "registry.json")

from app import registry as R                       # noqa: E402
from app.sources import registry_source as RS      # noqa: E402

OK = 0
BAD = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global OK, BAD
    if cond:
        OK += 1
        print(f"  ✓ {name}")
    else:
        BAD += 1
        print(f"  ✗ {name}  {extra}")


# ---------------------------------------------------------------------------
# 夹具：一页「站内搜索结果」。照真实站点（384g / 老笔趣阁，杰奇 CMS 系）的
# 形状造：
#   · 3 本书的结果链接：/html/#/#/（无扩展名、两段数字）
#   · 每本书旁边一条「最新章节」：/html/#/#/#.html —— **共 6 条，比书多**
#     （历史上就踩过：只按数量排，最新章节列表会冒充搜索结果）
#   · 侧边栏「最近更新」再塞 3 条章节链接（进一步把章节组做大）
#   · 导航 / 登录 / 分类 / 翻页：零散模板，一组只有一条
#   · 第一本书出现两次（同 href 同书名）→ 去重后必须只剩一条
# ---------------------------------------------------------------------------
SEARCH_PAGE = """<!doctype html><html><head><title>搜索_喵</title></head><body>
<div class="nav"><a href="/">首页</a> <a href="/login.html">登录</a>
<a href="/sort/1/">玄幻</a> <a href="/sort/2/">都市</a> <a href="/top/">排行</a></div>
<ul class="result">
<li><h3><a href="/html/489/489427/">我们猫猫不能听这些</a></h3>
  <p>作者：<a href="/author/12/">咸鱼露</a> · <a href="/html/489/489427/749.html">第119章 喵喵最新章节试读</a></p></li>
<li><h3><a href="/html/502/502231/">某本很长的书名全书读起来</a></h3>
  <p>作者：<a href="/author/30/">隔壁老王</a> · <a href="/html/502/502231/1203.html">第240章 再一次见面</a></p></li>
<li><h3><a href="/html/661/661009/">第三本书</a></h3>
  <p>作者：<a href="/author/77/">无名氏</a> · <a href="/html/661/661009/88.html">第17章 尾声</a></p></li>
<li><h3><a href="/html/489/489427/">我们猫猫不能听这些</a></h3>
  <p>重复出现的一条（同 href 同书名）</p></li>
</ul>
<div class="side"><h4>最近更新</h4>
<a href="/html/771/771002/3.html">第4章 更新一</a>
<a href="/html/772/772010/9.html">第5章 更新二</a>
<a href="/html/773/773015/2.html">第6章 更新三</a></div>
<div class="pages"><a href="/search.php?q=%E5%96%B5&amp;page=2">下一页</a></div>
</body></html>"""

NAV_ONLY_PAGE = """<html><body>
<a href="/">首页</a> <a href="/login.html">登录</a>
<a href="/sort/1/">玄幻</a></body></html>"""


def main() -> int:
    print("=" * 62)
    print("自有来源搜索链路回归（学到的模板 → 真的能搜出书）")
    print("=" * 62)

    print("\n── 1. looks_like_book_url：书页认得出、章节页挡得住 ──")
    check("杰奇系书页 /html/102/102114/ → 像",
          RS.looks_like_book_url("https://www.384g.com/html/102/102114/") is True)
    check("关键字系 /book/123456/ → 像",
          RS.looks_like_book_url("https://x.com/book/123456/") is True)
    check("单段长数字 /123456/ → 像",
          RS.looks_like_book_url("https://x.com/123456/") is True)
    # 反证：这三条正是历史上真实混进过结果的形态
    check("章节页 /html/102/102114/79.html → **不像**（第2条会被部分命中）",
          RS.looks_like_book_url("https://www.384g.com/html/102/102114/79.html") is False)
    check("翻页 /page/2/ → 不像", RS.looks_like_book_url("https://x.com/page/2/") is False)
    check("作者页 /author/12/ → 不像", RS.looks_like_book_url("https://x.com/author/12/") is False)

    print("\n── 2. _extract_book_links：书赢、章节输、导航出局 ──")
    base = "https://www.fakesite.com/search.php?q=%E5%96%B5"
    items = RS._extract_book_links(SEARCH_PAGE, base)
    titles = [t for t, _u in items]
    urls = [u for _t, u in items]
    print(f"     抽到 {len(items)} 条：{titles}")
    check("抽出 3 本书（不多不少）", len(titles) == 3, f"实际 {len(titles)} 条：{titles}")
    check("第一条就是结果书", "我们猫猫不能听这些" in titles, str(titles))
    check("同 href 同书名的重复条被去掉",
          titles.count("我们猫猫不能听这些") == 1, str(titles))
    check("全是绝对地址（拼上了站点域名）",
          all(u.startswith("https://www.fakesite.com/") for u in urls), str(urls[:3]))
    check("章节链接一条都没混进来（第119章…/第4章 更新一…）",
          not any("章" in t for t in titles), str(titles))
    check("导航一条都没进来（登录/玄幻/下一页）",
          not any(t in ("首页", "登录", "玄幻", "下一页") for t in titles), str(titles))
    check("空页面 → 空列表", RS._extract_book_links("", base) == [])
    check("只有导航的页面 → 空列表",
          RS._extract_book_links(NAV_ONLY_PAGE, base) == [],
          str(RS._extract_book_links(NAV_ONLY_PAGE, base)))

    print("\n── 3. build_url：模板拼 URL（搜索的起点）──")
    from app import sitelearn as SL
    u = SL.build_url("/search.php?q={kw}", "good.com", "喵")
    check("路径形模板 → base + 路径 + 关键词",
          u == "https://good.com/search.php?q=%E5%96%B5", u)
    u_abs = SL.build_url("https://other.com/search.php?q={kw}", "good.com", "喵")
    check("完整 URL 形模板 → 直接用（拼到 base 后面必是 404，"
          "还会记成 fail_down 把站拖死）",
          u_abs == "https://other.com/search.php?q=%E5%96%B5", u_abs)
    check("gbk 站的关键词按 gb18030 编码",
          SL.build_url("/s?kw={kw}", "g.com", "喵", enc="gbk")
          == "https://g.com/s?kw=%DF%F7")

    print("\n── 4. _search_one：拼模板 → 抓页 → 变成 BookResult ──")
    asked: list[str] = []

    def fake_fetch(url, **kw):
        asked.append(url)
        if "empty.com" in url:
            return (NAV_ONLY_PAGE, "https://empty.com/search.php?q=%E5%96%B5")
        return (SEARCH_PAGE, "https://good.com/search.php?q=%E5%96%B5")

    real_fetch = RS.fetch_text
    RS.fetch_text = fake_fetch
    try:
        # 空站先**正经注册**一遍（模板是学习时由 note_search_tpl 写进去的，
        # _search_one 只负责记成败）—— 这样才能验「失败不冲掉模板」。
        R.note_site("empty.com", ok=False, name="空站",
                    search_tpl="/search.php?q={kw}")
        R.flush()
        fail_before = int(R.sites()["empty.com"].get("fail", 0))
        got = RS.RegistrySource()._search_one(
            "good.com", {"search_tpl": "/search.php?q={kw}"}, "喵")
        empty_got = RS.RegistrySource()._search_one(
            "empty.com", {"search_tpl": "/search.php?q={kw}"}, "喵")
    finally:
        RS.fetch_text = real_fetch

    check("拼出来的 URL 带着关键词", any("q=%E5%96%B5" in u for u in asked), str(asked))
    check("每条候选都带 source_display（界面靠它说「自有来源」）",
          all(getattr(r, "source_display", "") for r in got))
    check("每条候选的 url 是绝对地址", all(r.url.startswith("https://good.com/") for r in got))
    check("成功搜索后给站点记了一笔成功（ok+1）",
          int(R.sites()["good.com"].get("ok", 0)) >= 1, str(R.sites()["good.com"]))
    check("搜不出书链接的站 → 空结果（不是异常）", empty_got == [], str(empty_got))
    check("搜不出的站记了失败**但不冲掉模板**（模板没错，是启发式要跟进）",
          int(R.sites()["empty.com"].get("fail", 0)) > fail_before
          and bool(R.sites()["empty.com"].get("search_tpl")),
          str(R.sites()["empty.com"]))

    print("\n── 5. search() 扇出：只问「健康且学过模板」的站 ──")
    # 好站：健康 + 有模板 → 必须被问到
    R.note_site("good.com", ok=True, name="好站", search_tpl="/search.php?q={kw}")
    # 坏站：学过模板、但被判为影视站（不健康）→ **绝不能问**
    #   （searchable_sites 走 is_searchable 的契约，见 tools/test_registry.py）
    R.note_site("bad.com", ok=False, name="坏站", video_blocked=True,
                search_tpl="/s.php?q={kw}")
    R.flush()
    asked.clear()
    RS.fetch_text = fake_fetch
    try:
        out = RS.RegistrySource().search("喵")
    finally:
        RS.fetch_text = real_fetch
    hosts_asked = {u.split("/")[2] for u in asked}
    print(f"     问了 {sorted(hosts_asked)}，拿回 {len(out)} 条")
    check("健康 + 有模板的站被问到", "good.com" in hosts_asked, str(hosts_asked))
    check("被判死的站**没被问到**（坏站进扇出 = 白烧一次 8s 超时）",
          "bad.com" not in hosts_asked, str(hosts_asked))
    check("真的搜到了书", len(out) >= 1, f"{len(out)} 条")

    print("\n── 6. 扇出预算：14 个站要能在 7 秒内全问到 ──")
    # 2026-10-21 线上实测：14 个可搜站 / 6 并发 = 要跑 3 轮；
    # 而单站超时给的是 8 秒 —— **单站超时比总预算还长**，
    # 等于「只要有一个站慢到 8 秒，整批必然超预算」。
    # 线上 15 次 `自有来源搜索超预算，先用已有结果`，全部是这句，
    # 而那 15 次一条结果都没拿到。后果直接对应「热门书也搜不到」。
    check("★ 单站超时明显小于总预算（否则一个慢站就能拖垮整批）",
          RS.SEARCH_SITE_TIMEOUT < RS.SEARCH_BUDGET,
          f"单站 {RS.SEARCH_SITE_TIMEOUT}s vs 总预算 {RS.SEARCH_BUDGET}s")
    check("★ 并发数能一次覆盖常见数量的可搜站（不用排队跑多轮）",
          RS.SEARCH_WORKERS >= 12, str(RS.SEARCH_WORKERS))
    # 判据不能只说"数字够大"—— 得验**实际行为**：14 个站时只发一轮。
    check("★ 14 个站时并发上限就是 14（不是 6 排队跑三轮）",
          min(RS.SEARCH_WORKERS, 14) == 14)

    # 超预算日志要能看出"卡在哪"（旧版只有一句"先用已有结果"，一句信息都没有）
    import inspect
    src = inspect.getsource(RS.RegistrySource.search)
    check("★ 超预算日志带进度（答完几个 / 共几个 / 耗时 / 已有几条）",
          "个站已答完" in src and "len(ordered)" in src, src[src.find("超预算"):][:80])

    print("\n── 7. 整批全挂要让熔断器知道（部分挂不算） ──")
    # `_search_one` 原来 catch 掉异常直接 return []，引擎会把"挂"当成
    # "没这本书" → note_ok 清零 → 熔断器永远收不到失败。
    # 现在它把错误记在实例上（note_error），search() 判「整批全挂」才上抛。
    R.note_site("dead1.com", ok=True, search_tpl="/?s={kw}")
    R.note_site("dead2.com", ok=True, search_tpl="/?s={kw}")
    R.flush()

    boom_asked: list[str] = []

    def boom_fetch(url, *a, **k):
        boom_asked.append(url)
        raise OSError("DNS 挂了")

    RS.fetch_text = boom_fetch
    src_obj = RS.RegistrySource()
    try:
        out2 = src_obj.search("喵")
        err2 = src_obj.take_error()
    finally:
        RS.fetch_text = real_fetch
    check("整批全挂时返回空结果（不抛给引擎）", out2 == [], str(out2))
    check("★ 整批全挂时把错误留给熔断器（否则永远不熔断）", bool(err2), repr(err2))
    check("错误里说清是「全部站都失败」", "全部" in (err2 or ""), repr(err2))

    # 反向：只要有结果，就不该报"挂" —— 否则搜到书也会被拉黑。
    R.note_site("alive.com", ok=True, search_tpl="/?s={kw}")
    R.flush()
    RS.fetch_text = fake_fetch
    src3 = RS.RegistrySource()
    try:
        out3 = src3.search("喵")
        err3 = src3.take_error()
    finally:
        RS.fetch_text = real_fetch
    check("有结果时不报「挂」（空结果≠挂，这是熔断器的红线）",
          bool(out3) and not err3, f"out={len(out3)} err={err3!r}")

    print("\n" + "=" * 62)
    print(f"通过 {OK} · 失败 {BAD}")
    print("=" * 62)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
