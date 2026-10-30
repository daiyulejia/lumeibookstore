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
<li><h3><a href="/html/661/661009/">第三本喵书</a></h3>
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

    # ⚠ 光有进度还不够：线上 15 次超预算里，「没答完的站」**一个名字都没留**，
    #   于是分不清"预算太小"和"某个站永远慢"（前者加预算、后者把站降权，
    #   处置相反）。这条是行为判据 —— 真跑一轮撞预算，看日志里有没有那个站名。
    import logging as _log

    class _Cap(_log.Handler):
        def __init__(self):
            super().__init__()
            self.lines: list[str] = []

        def emit(self, rec):        # noqa: D102
            self.lines.append(rec.getMessage())

    _cap = _Cap()
    _lg = _log.getLogger("novel.registry_source")
    _lg.addHandler(_cap)
    _lg.setLevel(_log.DEBUG)
    _old_budget = RS.SEARCH_BUDGET

    def _slow_fetch(url, *a, **k):
        import time as _t
        _t.sleep(0.8)                       # 一定跑不完，但线程会自己结束
        return "<html><body>nothing</body></html>"

    R.note_site("slowbudget.com", ok=True, name="慢站", search_tpl="/?s={kw}")
    R.flush()
    RS.fetch_text = _slow_fetch
    RS.SEARCH_BUDGET = 0.2
    try:
        RS.RegistrySource().search("喵")
    finally:
        RS.SEARCH_BUDGET = _old_budget
        RS.fetch_text = real_fetch
        _lg.removeHandler(_cap)
    _txt = "\n".join(_cap.lines)
    check("★ 超预算时点名没答完的站（只报个数等于没报）",
          "slowbudget.com" in _txt, _txt[-240:] or "（这条日志压根没打）")

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

    print("\n── 8. 空结果的两种形态必须分开记（否则「可搜源」是虚的）──")
    # 线上实测（2026-10-22）：15 个可搜源里 **7 个拿任何关键词都抽不出
    # 一条书链接**（POST 落回「搜索_首页」/ 前端渲染 SPA / 吞掉 `?s=` 回首页），
    # 而 `_search_one` 把它们和「站里没这本书」记成了同一笔 `fail_empty` ——
    # 库里看不出区别，界面照报 15 个可搜源。
    # 现在：抽到 0 条 = FAIL_SHAPE + search_shape；抽到 N 条全被过滤 = FAIL_EMPTY。
    nav_only = ("<html><body><a href='/'>首页</a><a href='/login'>登录</a>"
                "<a href='/top'>排行</a></body></html>")
    # 有书链接、但标题全是单字（长度 < 2 被过滤）→ 过滤后为空
    # ⚠ 链接形状必须用 `/html/#/#/`（杰奇系书页）：`/book/1.html` 会被
    #   `_CHAPTER_TAIL` 判成章节正文页而直接丢掉，那样测的就不是"过滤后为空"。
    junk_books = ("<html><body>"
                  + "".join(f"<a href='/html/10{i}/10{i}12/'>书</a>" for i in range(1, 9))
                  + "</body></html>")

    def shape_fetch(url, **kw):
        if "shape0.com" in url:
            return (nav_only, url)
        return (junk_books, url)

    R.note_site("shape0.com", ok=True, search_tpl="/?s={kw}")
    R.note_site("filtered.com", ok=True, search_tpl="/?s={kw}")
    R.flush()
    RS.fetch_text = shape_fetch
    try:
        got_shape = RS.RegistrySource()._search_one("shape0.com", {"search_tpl": "/?s={kw}"}, "喵")
        got_filt = RS.RegistrySource()._search_one("filtered.com", {"search_tpl": "/?s={kw}"}, "喵")
    finally:
        RS.fetch_text = real_fetch
    s0 = R.known_site("shape0.com")
    f0 = R.known_site("filtered.com")
    check("两条路都返回空（不抛异常）", got_shape == [] and got_filt == [],
          f"{got_shape} / {got_filt}")
    check("★ 一条链接都抽不到 → 记 fail_shape（打开的不是搜索页）",
          int(s0.get("fail_shape") or 0) == 1, str(s0))
    check("★ 同时记 search_shape（能不能当可搜源的判据靠它）",
          int(s0.get("search_shape") or 0) == 1, str(s0))
    check("这条不算 fail_empty（否则和「站里没这本书」混了）",
          int(s0.get("fail_empty") or 0) == 0, str(s0))
    check("有链接但没这本书 → 记 fail_empty", int(f0.get("fail_empty") or 0) == 1,
          str(f0))
    check("★ 这条不算 fail_shape（站是好的，只是没这本书）",
          int(f0.get("fail_shape") or 0) == 0 and int(f0.get("search_miss") or 0) == 1,
          str(f0))

    print("\n── 9. 超时 ≠ 站点挂了（慢站不该被慢慢判死）──")
    # 单站只给 SEARCH_SITE_TIMEOUT 秒，慢站必然超时。原先一律记 fail_down，
    # `is_healthy` 的 `down >= 3 and down > ok*2` 于是把慢站往死里推 ——
    # 线上 350.ooo 当时 ok=35 / fail_down=70，再超时一次就越线从可搜源里消失。
    import httpx as _httpx

    def _as_fetch(cause):
        def _f(url, *a, **k):
            # 照 fetch_text 的真实形状抛：RuntimeError 包着原始异常（__cause__）
            try:
                raise cause
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"抓取失败: {url} ({e})") from e
        return _f

    R.note_site("slow.com", ok=True, search_tpl="/?s={kw}")
    R.note_site("conn.com", ok=True, search_tpl="/?s={kw}")
    R.flush()
    for host, cause in (("slow.com", _httpx.ReadTimeout("timed out")),
                        ("conn.com", _httpx.ConnectError("refused"))):
        RS.fetch_text = _as_fetch(cause)
        try:
            try:
                RS.RegistrySource()._search_one(host, {"search_tpl": "/?s={kw}"}, "喵")
            except Exception:  # noqa: BLE001
                pass
        finally:
            RS.fetch_text = real_fetch
    slow = R.known_site("slow.com")
    conn = R.known_site("conn.com")
    check("读超时 → 记 fail_slow", int(slow.get("fail_slow") or 0) == 1, str(slow))
    check("★ 读超时**不许**记 fail_down（这是「我们等得不够」，不是站的错）",
          int(slow.get("fail_down") or 0) == 0, str(slow))
    check("★ 读超时也不算「打不开结果页」（换个宽松点的超时就好了，别作废模板）",
          int(slow.get("search_shape") or 0) == 0, str(slow))
    check("连接失败 → 记 fail_down（这才像站挂了）",
          int(conn.get("fail_down") or 0) == 1, str(conn))
    check("连接失败不记 fail_slow", int(conn.get("fail_slow") or 0) == 0, str(conn))
    # ⚠ 线上实测 `m.kudushu.org` 每次都 403：走异常分支 → 不记 search_shape，
    #   而 0 命中又让夜间复核直接跳过 → 既不被判假也不被作废，永久赖在可搜源里。
    #   所以「抓取就打不开」必须和「打开不是搜索页」汇到同一条生命线。
    check("★ 连不上/被 403 也算「打不开结果页」（否则它永远退出不了可搜源）",
          int(conn.get("search_shape") or 0) == 1, str(conn))

    print("\n── 10. 每站只回 6 条时，正主不能排在第 7 位被截掉 ──")
    # 线上实测：www.384g.com 搜「斗破苍穹」返回 **100 条**，含关键词的第一条
    # 在**第 7 位**，而 PER_SITE=6 把前 6 条（NBA/末日逃亡/同人…）全取走 ——
    # 正主一条都没进候选池，排序再准也救不回来。
    many = ("<html><body>"
            + "".join(f"<a href='/html/80{i}/80{i}12/'>别的书{i}</a>" for i in range(1, 9))
            + "<a href='/html/999/999001/'>喵喵正主</a>"
            + "</body></html>")
    RS.fetch_text = lambda url, **k: (many, url)
    try:
        got10 = RS.RegistrySource()._search_one("many.com", {"search_tpl": "/?s={kw}"}, "喵")
    finally:
        RS.fetch_text = real_fetch
    titles = [r.title for r in got10]
    check("★ 标题里带关键词的那条必须进候选（站点排序靠不住）",
          "喵喵正主" in titles, str(titles))
    check(f"候选仍然只回 {RS.PER_SITE} 条（不放开上限）",
          len(got10) <= RS.PER_SITE, str(len(got10)))

    print("\n── 11. 轮换列表型假站：不含关键词的条目一条都不许当候选 ──")
    # 2026-10-28 线上复盘（本条的主线）：
    #   14 个可搜源里 5 个（www.31xss.com / www.dushu.co / www.kepub.net /
    #   www.taishuaile.com / www.taiminc.com）的"搜索页"**不认参数**，照常吐
    #   一页「最新更新」，而且**每次都换一批**：
    #     搜「三体」    → 《全能大佬是团宠》《林轩逆剑狂神》
    #     搜「素食者」  → 《前男友变成鬼之后》《总裁老公超给力》
    #   因为每批都不一样，控制实验（比"换个词结果集变不变"）恒判"真"，
    #   撤不掉；它们的 `search_hit` 涨到 200+，按 ok 排序还排在最前面。
    #   实测《素食者》一次搜索 40 条候选里 24 条来自它们 —— 用户点开是**别的书**。
    #   判据：标题/作者里连一个搜索词都没有的条目，不许进候选池。
    #
    # ⚠ 这条判据的三个反向陷阱，下面每一条都有专门断言（写的时候都踩过）：
    #   ① 按**整串**比对 → 搜「余华 活着」时 `余华活着` 谁都不含，全站清零；
    #   ② 只看标题 → 作者搜索（书名里当然没有作者名）全站清零；
    #   ③ 不做繁转简 → 搜「三體」时站上《三体》被判成不相关。
    fake_rot = ("<html><body>"
                + "".join(f"<a href='/html/90{i}/90{i}12/'>{t}</a>"
                          for i, t in enumerate(
                              ["前男友变成鬼之后", "全能大佬是团宠", "林轩逆剑狂神",
                               "骆驼祥子", "总裁老公超给力", "熟诱"], 1))
                + "</body></html>")
    real_mixed = ("<html><body>"
                  "<li><h3><a href='/html/100/100001/'>素食者</a></h3></li>"
                  "<li><h3><a href='/html/100/100002/'>总裁老公超给力</a></h3></li>"
                  "<li><h3><a href='/html/100/100003/'>前男友变成鬼之后</a></h3></li>"
                  "</body></html>")
    multi_page = ("<html><body>"
                  "<a href='/html/110/110001/'>活着</a>"
                  "<a href='/html/110/110002/'>许三观卖血记</a>"
                  "</body></html>")
    author_page = ("<html><body><li><h3><a href='/html/120/120001/'>我们猫猫不能听这些"
                   "</a></h3><p>作者：咸鱼露</p></li></body></html>")
    trad_page = ("<html><body><a href='/html/130/130001/'>三体（全集）</a>"
                 "<a href='/html/130/130002/'>江南三月三</a></body></html>")

    def offkw_fetch(url, **kw):
        host = url.split("/")[2]
        if host.startswith("fake"):
            return (fake_rot, url)
        if host.startswith("multi"):
            return (multi_page, url)
        if host.startswith("author"):
            return (author_page, url)
        if host.startswith("trad"):
            return (trad_page, url)
        return (real_mixed, url)

    for _h in ("fake.com", "mixed.com", "multi.com", "author.com", "trad.com"):
        R.note_site(_h, ok=True, search_tpl="/?s={kw}")
    R.flush()
    RS.fetch_text = offkw_fetch
    try:
        _one = RS.RegistrySource()._search_one
        got_fake = _one("fake.com", {"search_tpl": "/?s={kw}"}, "三体")
        got_mixed = _one("mixed.com", {"search_tpl": "/?s={kw}"}, "素食者")
        got_multi = _one("multi.com", {"search_tpl": "/?s={kw}"}, "余华 活着")
        got_author = _one("author.com", {"search_tpl": "/?s={kw}"}, "咸鱼露")
        got_trad = _one("trad.com", {"search_tpl": "/?s={kw}"}, "三體")
    finally:
        RS.fetch_text = real_fetch

    check("★ 假站吐 6 条无关书 → 一条候选都不许进（用户点开是别的书）",
          got_fake == [], str([r.title for r in got_fake]))
    fk = R.known_site("fake.com")
    check("★ 假站这笔记成 search_miss 而不是 search_hit"
          "（否则它按 ok 排序永远排最前面）",
          int(fk.get("search_hit") or 0) == 0 and int(fk.get("search_miss") or 0) == 1,
          str(fk))
    check("真命中留着、无关的同页结果丢掉",
          [r.title for r in got_mixed] == ["素食者"],
          str([r.title for r in got_mixed]))
    check("★ 多词关键词「余华 活着」不许被整串比对清零（只认『活着』也留）",
          [r.title for r in got_multi] == ["活着"],
          str([r.title for r in got_multi]))
    check("★ 作者命中要留（书名里当然没有作者名）",
          [r.title for r in got_author] == ["我们猫猫不能听这些"],
          str([r.title for r in got_author]))
    check("★ 繁体关键词「三體」要认得简体《三体》",
          [r.title for r in got_trad] == ["三体（全集）"],
          str([r.title for r in got_trad]))

    # 判据本身的单测：词表要按词拆、要丢单字、一个都不剩时回落原词
    from app.relevance import kw_terms as _kt
    check("kw_terms 按词拆（「余华 活着」→ 两个词）", _kt("余华 活着") == ["余华", "活着"],
          str(_kt("余华 活着")))
    check("kw_terms 丢单字（否则单字会把任何书都算命中）",
          _kt("余华 活") == ["余华"], str(_kt("余华 活")))
    check("kw_terms 一个词都留不下时回落原词（不能返回空表＝悄悄关掉过滤）",
          _kt("活") == ["活"], str(_kt("活")))

    print("\n── 12. 空结果页 ≠ 模板坏了（2026-10-29 线上主线）──")
    # 线上实测：夜间刚学到的 8 个源（hbsjob / m.kudushu / gashuw / itiandixs /
    # jcxs / mingchaonaxieshier / xizids / xuanhuanbiquge）在一次复盘探针里
    # **全部** shape=3、模板被清空 —— 22 个可搜源掉到 14 个。
    # 它们唯一的"错"是被拿去搜了几本冷门书：站上没这本书时，搜索页回的是
    # 「没有找到 xx」这种**空结果页**，里面一条书链接都没有 → raw=0 →
    # 被算成"打开的不是搜索页" → 连记 3 次作废模板。
    # 用户搜三本冷门书就触发同一件事：源池少三分之一，而且全程不报错。
    #
    # ⚠ 这条判据必须走**真的 `_search_one`**（不是直接调 note_search_result）：
    #   要证明的是「页面长什么样」这一维真的被接上去了。只测记账函数的话，
    #   把 `empty_page=` 那个实参删掉，测试照样绿。
    empty_res = ("<html><head><title>搜索_不存在的书_某某小说网</title></head>"
                 "<body><div class='search'><input value='不存在的书'>"
                 "<p>抱歉，没有找到相关的小说，换个关键词试试</p></div></body></html>")
    home_like = ("<html><head><title>某某小说网 - 最新章节</title></head>"
                 "<body><ul><li>最新更新</li><li>排行榜</li>"
                 "<li>分类：玄幻 都市 历史</li></ul></body></html>")
    # 另一类空结果页：**没有**「没有找到」这种文案，但把关键词回显在搜索框/标题里
    # （说明请求真的被当成一次搜索处理了）。这两条证据是"或"的关系，
    # 各写一个用例，缺一个就会有判据被删掉而测试照绿。
    echo_only = ("<html><head><title>站内搜索</title></head>"
                 "<body><form><input name='s' value='不存在的书'></form>"
                 "<div>换个词试试吧</div></body></html>")
    # 第三条用例：只有空态文案、**不回显**关键词（有的站就是不回显）。
    # ⚠ 这条不能省：上面 `empty_res` 同时满足两个证据，删掉任何一条判据
    #   测试都照绿 —— 反证实测过，那一维就是"没牙"的。
    marker_only = ("<html><head><title>站内搜索</title></head>"
                   "<body><p>抱歉，没有找到相关的小说。</p></body></html>")

    def empty_fetch(url, **kw):
        host = url.split("/")[2]
        if host.startswith("emptyres"):
            return (empty_res, url)
        if host.startswith("echoonly"):
            return (echo_only, url)
        if host.startswith("markeronly"):
            return (marker_only, url)
        return (home_like, url)

    for _h in ("emptyres.com", "echoonly.com", "markeronly.com", "homelike.com"):
        R.note_site(_h, ok=True, search_tpl="/?s={kw}")
    R.flush()
    RS.fetch_text = empty_fetch
    try:
        _one = RS.RegistrySource()._search_one
        for _ in range(R.SEARCH_SHAPE_MAX + 2):
            _one("emptyres.com", {"search_tpl": "/?s={kw}"}, "不存在的书")
        _emp = R.known_site("emptyres.com")
        for _ in range(R.SEARCH_SHAPE_MAX + 2):
            _one("echoonly.com", {"search_tpl": "/?s={kw}"}, "不存在的书")
        _echo = R.known_site("echoonly.com")
        for _ in range(R.SEARCH_SHAPE_MAX + 2):
            _one("markeronly.com", {"search_tpl": "/?s={kw}"}, "不存在的书")
        _mark = R.known_site("markeronly.com")
    finally:
        RS.fetch_text = real_fetch

    check("★ 空结果页记 search_miss、不记 search_shape",
          int(_emp.get("search_miss") or 0) == R.SEARCH_SHAPE_MAX + 2
          and int(_emp.get("search_shape") or 0) == 0,
          f"miss={_emp.get('search_miss')} shape={_emp.get('search_shape')}")
    check("★ 连搜 5 次冷门书，模板照样活着（这不是模板的错）",
          bool((_emp.get("search_tpl") or "").strip()),
          repr(_emp.get("search_tpl")))
    check("★ 只回显关键词的空结果页也算搜索页（第二条证据单独成立）",
          int(_echo.get("search_shape") or 0) == 0
          and bool((_echo.get("search_tpl") or "").strip()),
          f"shape={_echo.get('search_shape')} tpl={_echo.get('search_tpl')!r}")
    check("★ 只有空态文案、不回显关键词的空结果页也算搜索页（第一条证据单独成立）",
          int(_mark.get("search_shape") or 0) == 0
          and bool((_mark.get("search_tpl") or "").strip()),
          f"shape={_mark.get('search_shape')} tpl={_mark.get('search_tpl')!r}")

    # 反向：真的"打开的不是搜索页"（没有空态文案、也不回显关键词）照样要死
    RS.fetch_text = empty_fetch
    try:
        _one = RS.RegistrySource()._search_one
        for _ in range(R.SEARCH_SHAPE_MAX):
            _one("homelike.com", {"search_tpl": "/?s={kw}"}, "不存在的书")
        _home = R.known_site("homelike.com")
    finally:
        RS.fetch_text = real_fetch

    check("★ 不是搜索页（无空态文案/不回显关键词）照样攒满作废",
          _home.get("search_tpl") == "", repr(_home.get("search_tpl")))
    check("它的形态失败账记满了（排查时看得见）",
          int(_home.get("search_shape") or 0) == R.SEARCH_SHAPE_MAX,
          str(_home.get("search_shape")))

    # ---- 「可搜源池」这个数本身（2026-10-30 补埋点 `源池=22→15` 的靶子）----
    # `search.done` 里那个 `源池=A→B` 的差值，量的就是 `searchable_sites()` 的
    # 变化。所以这里必须钉两件事，否则那个字段是**假埋点**：
    #   ① 冷门书搜完之后，空结果页的站**还在池里**（差值为 0）；
    #   ② 真坏模板作废之后，它**必须从池里消失**（差值才可能非 0）。
    # 少了①，改动一下就把冷门书重新算成死刑，而日志里"源池 22→22"看着毫无异常。
    _pool = R.searchable_sites()
    _alive = [h for h in ("emptyres.com", "echoonly.com", "markeronly.com")
              if h in _pool]
    check("★ 冷门书之后，空结果页的站仍在可搜源池里（否则「源池=」恒为 22→22）",
          len(_alive) == 3, f"还在池里的={_alive}")
    check("★ 真坏模板被作废后从可搜源池里消失（源池差值才有意义）",
          "homelike.com" not in _pool, f"池里={sorted(_pool)}")

    # ---- 13. 限速页 ≠ 缺书 ≠ 模板坏了（2026-10-30 线上主线）----
    # 线上实证：杰奇 CMS（`/modules/article/search.php`）对同一 IP 限速 30 秒，
    # 超了回一页「错误原因：对不起，两次搜索的间隔时间不得少于 30 秒」。
    # 这页一条书链接都没有、没有空态文案、也不回显关键词 —— 长得和"不是搜索页"
    # 一模一样，于是**用户连搜三本书就把这个站判死**。
    # 10-30 09:55 实测：`www.jcxs.cc` 重学回来之后，又被 3 次冷门书搜索
    # 判死第二次（search.done 里 `源池=15→14` 就是它掉的那一个）。
    busy_page = ("<html><head><title>出现错误！</title></head><body>"
                 "<div class='content'>错误原因：对不起，两次搜索的间隔时间"
                 "不得少于 30 秒<br>请返回并修正</div></body></html>")

    def busy_fetch(url, **kw):
        return (busy_page, url)

    R.note_site("busy.example.com", ok=True, search_tpl="/?s={kw}")
    R.flush()
    RS.fetch_text = busy_fetch
    try:
        _one = RS.RegistrySource()._search_one
        for _ in range(R.SEARCH_SHAPE_MAX + 3):
            _one("busy.example.com", {"search_tpl": "/?s={kw}"}, "不存在的书")
        _busy = R.known_site("busy.example.com")
    finally:
        RS.fetch_text = real_fetch

    check("★ 限速页不攒形态失败（连搜 8 次也不许把模板判死）",
          int(_busy.get("search_shape") or 0) == 0
          and bool((_busy.get("search_tpl") or "").strip()),
          f"shape={_busy.get('search_shape')} tpl={_busy.get('search_tpl')!r}")
    check("★ 限速页连 search_miss 都不许涨（它不代表这个站覆盖窄）",
          int(_busy.get("search_miss") or 0) == 0
          and int(_busy.get("search_hit") or 0) == 0,
          f"miss={_busy.get('search_miss')} hit={_busy.get('search_hit')}")
    check("★ 限速站仍在可搜源池里（源池不该因为它掉）",
          "busy.example.com" in R.searchable_sites(),
          f"池里={sorted(R.searchable_sites())}")

    print("\n" + "=" * 62)
    print(f"通过 {OK} · 失败 {BAD}")
    print("=" * 62)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
