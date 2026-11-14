# -*- coding: utf-8 -*-
"""源自己的墙钟上限：一个「打不通的站」不许比整轮搜索活得更久。**纯逻辑，不联网。**

为什么必须有这条
----------------
2026-10-21 复盘（真实线上日志 + 服务端实测）：

    wikisource.search("青叶灵异事务所") → 返回 0 条，耗时 **186.9 秒**

引擎 20 秒就收手了，可这个线程还活着 167 秒。当天日志里
`The handshake operation timed out` 出现 **117 次** —— 也就是每搜几次书
就攒一个僵尸线程，而共享 httpx client 只有 10 个连接。

它造成的不是「慢」，而是**别的搜索偶发 0 条**：
同一天同一本书《青叶灵异事务所》相隔 6 分钟，一次 0 条、一次 1 条。

根因有两层，缺一不可：
  ① `wikisource._api()` 是「5 次重试 + 递增退避」，`search()` 还要串两次
     （intitle 一次、全文一次）——**这个源自己没有任何时间上限**。
  ② 引擎墙钟到点后只是把 future 丢下（`pool.shutdown(wait=False)`），
     卡死的源**永远不进熔断器**（熔断器只统计"跑完但抛异常"的），
     于是下一轮它还在名单里。—— 这一层见 tools/test_source_health.py
     的「卡死不返回的源也要被熔断」组。

这里钉的是第 ① 层。判据刻意**不看耗时**（耗时随机器负载漂），
只看两件与负载无关的事实：
  · 请求**次数**（到点还发不发下一次）；
  · 第二次 `_search_raw` **发没发**（186 秒就是它串出来的）。

用法：python tools/test_source_budget.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.sources.wikisource as WS  # noqa: E402
import app.sources.wyshu as WY  # noqa: E402
from app.utils import current_timeout  # noqa: E402

ok_n = 0
fail_n = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global ok_n, fail_n
    if cond:
        ok_n += 1
        print(f"  ✓ {name}")
    else:
        fail_n += 1
        print(f"  ✗ {name}")
        if extra:
            print(f"      {extra}")


class _FakeResp:
    status_code = 200
    text = ""

    def __init__(self) -> None:
        self.headers = {"content-type": "application/json"}

    def json(self) -> dict:
        return {"query": {"search": []}}


class _BoomClient:
    """每次 get 都立刻失败 —— 模拟「TLS 握手超时」，但不真的等 25 秒。

    用立刻失败而不是真挂住，是为了让判据与机器负载无关：
    我们数的是**发了几次请求**，不是"花了多少毫秒"。
    """

    def __init__(self) -> None:
        self.calls = 0

    def get(self, url, **kw):
        self.calls += 1
        raise TimeoutError("_ssl.c:990: The handshake operation timed out")


class _OKClient:
    calls = 0

    def get(self, url, **kw):
        type(self).calls += 1
        return _FakeResp()


def main() -> int:
    # =====================================================================
    print("\n—— ⓿ 结构性一致：声明的时间预算必须真的能被用满（2026-11-09） ——")
    # 这一组不跑任何网络，钉的是**三个数字之间的关系**。
    # 病灶原型（线上 11-06，17 次搜索里 12 次）：`RegistrySource` 内部
    # 预算 7.0s，而引擎「有结果就收手」的软截止是 6.0s、宽限期更是 3.5s ——
    # 于是它永远在半路被扔掉，30 个已学会的站抓回来的候选全部作废。
    # 这类矛盾**单看任何一处代码都看不出来**，只存在于两个常量的大小关系里，
    # 所以必须做成可断言的数字。
    import app.engine as E                       # noqa: E402
    import app.sources as SRC                    # noqa: E402
    import app.sources.registry_source as RS     # noqa: E402
    import app.utils as U                        # noqa: E402

    _all = SRC.BUILTIN_SOURCES
    _classes = [x if isinstance(x, type) else type(x) for x in _all]
    check("前置：枚举到 >= 8 个源（否则下面几条是空转）",
          len(_classes) >= 8, f"只枚到 {len(_classes)} 个")

    _declared = {c.name: getattr(c, "budget_s", None) for c in _classes}
    _declared = {k: v for k, v in _declared.items() if v}
    check("前置：至少有一个源声明了 budget_s（否则『让路』机制没启用过）",
          bool(_declared), f"声明表={_declared}")
    _bad = {k: v for k, v in _declared.items() if not (0 < float(v) <= E.SEARCH_SOFT_DEADLINE)}
    check("★ 声明了预算的源，值必须 <= 引擎软截止（否则『声明了也永远等不到』是假话）",
          not _bad, f"越界={_bad} 软截止={E.SEARCH_SOFT_DEADLINE}")

    check("★ 自有来源必须声明 budget_s（它是唯一一个内部要扇出 30 个站的源）",
          bool(getattr(RS.RegistrySource, "budget_s", None)),
          f"budget_s={getattr(RS.RegistrySource, 'budget_s', None)!r}")
    check("★ 声明值必须就是它自己真正在用的预算（两处只改一处等于没改）",
          getattr(RS.RegistrySource, "budget_s", None) == RS.SEARCH_BUDGET,
          f"budget_s={getattr(RS.RegistrySource, 'budget_s', None)!r} "
          f"SEARCH_BUDGET={RS.SEARCH_BUDGET!r}")
    check("自有来源的总预算必须小于引擎软截止",
          RS.SEARCH_BUDGET < E.SEARCH_SOFT_DEADLINE,
          f"{RS.SEARCH_BUDGET} vs {E.SEARCH_SOFT_DEADLINE}")
    check("单站超时必须明显小于它自己的总预算（否则一个慢站拖死整批）",
          RS.SEARCH_SITE_TIMEOUT < RS.SEARCH_BUDGET,
          f"{RS.SEARCH_SITE_TIMEOUT} vs {RS.SEARCH_BUDGET}")
    check("★ 连接池必须容得下自有来源的并发（池子比扇出小 → 站被压成几批串行）",
          U.POOL_MAX_CONNECTIONS >= RS.SEARCH_WORKERS,
          f"池={U.POOL_MAX_CONNECTIONS} 并发={RS.SEARCH_WORKERS}")

    src = WS.WikisourceSource()

    print("\n—— ① 到点就**不发**请求（而不是发完再判） ——")
    boom = _BoomClient()
    WS.get_client = lambda *a, **k: boom          # type: ignore[assignment]
    try:
        # deadline 已经过期 → 一次都不该发
        try:
            src._api({"action": "query"}, retries=5, deadline=time.time() - 1)
            check("过期 deadline 应该抛异常", False, "没抛，说明到点还在发请求")
        except RuntimeError as e:
            check("过期 deadline 抛异常", True)
            check("异常里说清是「预算」问题（不是伪装成站点错误）",
                  "预算" in str(e), str(e)[:120])
        check("过期 deadline → 一个请求都没发", boom.calls == 0,
              f"calls={boom.calls}")

        print("\n—— ② 搜索只重试 SEARCH_RETRIES 次，不是 5 次 ——")
        boom2 = _BoomClient()
        WS.get_client = lambda *a, **k: boom2      # type: ignore[assignment]
        check("搜索路径的重试次数是 2（写死在这里，改大要有理由）",
              src.SEARCH_RETRIES == 2, f"SEARCH_RETRIES={src.SEARCH_RETRIES}")
        src.SEARCH_BUDGET = 0.3        # 只改实例，别污染其它测试
        try:
            src._api({"action": "query"}, retries=src.SEARCH_RETRIES,
                     deadline=time.time() + src.SEARCH_BUDGET)
        except RuntimeError:
            pass
        check("预算 0.3s 时第二次请求被**拦住**（不是照发 2 次）",
              boom2.calls == 1, f"calls={boom2.calls}")

        print("\n—— ③ search() 第一次就把预算用光时，不许再串第二次 ——")
        # 186.9 秒 = 5 次重试 × 2 次串行。第二次串行是"纯加倍的浪费"：
        # 第一次都握手不通了，全文检索不可能通。
        calls: list[str] = []

        def _slow_raw(query, deadline=None):
            calls.append(query)
            time.sleep(src.SEARCH_BUDGET + 0.1)     # 把预算耗尽
            return []

        src._search_raw = _slow_raw                 # type: ignore[assignment]
        t0 = time.time()
        got = src.search("三体")
        check("返回空（没有瞎编结果）", got == [], str(got)[:80])
        check("只发了一次搜索请求（intitle 那次）", len(calls) == 1, str(calls))
        check("没有出现「全文检索」那一次", all("三体" != c for c in calls), str(calls))

        print("\n—— ④ 打不通时必须**说出来**（熔断器才学得到） ——")
        # 引擎的熔断器只认 take_error() 拿到的异常。搜不到却静默返回 []，
        # 会被当成「答话了、只是没这本书」→ note_ok 清零 → 永远不熔断。
        boom3 = _BoomClient()
        WS.get_client = lambda *a, **k: boom3      # type: ignore[assignment]
        src2 = WS.WikisourceSource()
        src2.SEARCH_BUDGET = 0.3
        src2.take_error()                            # 清掉可能残留的
        t0 = time.time()
        out = src2.search("三体")
        el = time.time() - t0
        check("返回空而不是抛给上层（搜索不该因一个源崩掉）", out == [])
        err = src2.take_error()
        check("把被吞掉的异常记下来了（否则熔断器永远收不到失败）",
              bool(err), f"take_error()={err!r}")
        check("异常里能看出是超时/握手（熔断按「网络类」算，冷却更久）",
              ("timeout" in err.lower() or "handshake" in err.lower()
               or "超" in err), err[:120])
        # 上限 6s 预算 + 一次退避睡眠 + 余量；这里只防"又回到 186 秒"
        check("整次搜索在秒级收手（不是分钟级）", el < 10.0, f"{el:.1f}s")

        print("\n—— ⑤ 正常站不受影响（别把好路径也掐死） ——")
        okc = _OKClient()
        WS.get_client = lambda *a, **k: okc        # type: ignore[assignment]
        src3 = WS.WikisourceSource()
        src3.SEARCH_BUDGET = 3.0
        got3 = src3.search("红楼梦")
        check("能正常拿到结果就走正常路径", got3 == [], "假 client 只回空列表，这里只看不抛")
        check("正常路径下两次搜索都发（intitle + 全文，因为预算还剩）",
              okc.calls == 2, f"calls={okc.calls}")
        check("正常路径下**不**留错误记录（别把成功记成挂）",
              src3.take_error() == "", src3.take_error()[:80])
    finally:
        # 还原模块级 get_client（否则后面的测试会用到假 client）
        import importlib
        importlib.reload(WS)

    # ------------------------------------------------------------------
    # wyshu：第二条「没有自带墙钟上限」的源（2026-10-24 复盘补齐）
    # ------------------------------------------------------------------
    # 病灶：索引过期时串行抓 8 个分类页、索引没命中时再串行试 8 个拼音 URL，
    # 两段都没有任何上限。**别的源也没出结果时引擎不会早收手**，
    # 于是一个卡住的 wyshu 就能把整轮搜索拖满 20s，到点仍是 0 条。
    #
    #   线上实测（2026-10-24）：搜《我们猫猫不能听这些》
    #     01:0x  耗时ms=20040 候选=0 未回=wyshu      ← 0 条
    #     同一本 耗时ms=7840  候选=1（1 本可读）      ← 5 分钟后
    #   同一本书两次结果相反，差的就是"wyshu 这轮回没回来"。
    print("\n—— ⑥ wyshu 建索引：到点不再发请求（不是发完再判） ——")
    _old_cache = WY.CACHE_FILE
    tmp_cache = ROOT / "cache" / "_test_wyshu_index.json"
    WY.CACHE_FILE = tmp_cache                  # type: ignore[assignment]
    if tmp_cache.exists():
        tmp_cache.unlink()
    calls = []

    def _slow_fetch(url, **kw):
        calls.append(url)
        time.sleep(0.20)
        # 一个含书籍链接的分类页（能让 _build_index 真的收到书）
        return '<a href="/ys/ceshi/">测试书(某人所著小说)_小说在线阅读</a>'

    _old_fetch = WY.fetch_text
    WY.fetch_text = _slow_fetch                # type: ignore[assignment]
    try:
        src4 = WY.WyshuSource()
        src4.SEARCH_BUDGET = 0.35
        books, complete = src4._build_index(deadline=time.time() + 0.35)
        check("★ 预算用完之后**不再发下一次请求**", len(calls) <= 3,
              f"calls={len(calls)}（8 个分类全发说明上限没生效）")
        check("预算用完 → 明确报「没抓完」（不许当成抓全了）",
              complete is False, f"complete={complete}")
        check("已经抓到的书要留下（不是白干）", len(books) >= 1, str(list(books)[:3]))

        print("\n—— ⑦ 没抓完**不许写缓存**（残缺索引缓存 24h 比不缓存更坏） ——")
        # 把残缺索引写进缓存，之后每次搜索都在残缺索引里查，缺的书永久查不到，
        # 而且缓存命中是最快路径 —— 最不可能被怀疑的一条。
        src4._load_index(deadline=time.time() + 0.35)
        check("★ 被预算截断时不落盘", not tmp_cache.exists(),
              f"{tmp_cache} 存在 = 残缺索引被缓存了")

        print("\n—— ⑧ 预算充足时走完整路径（别把好路径也掐死） ——")
        calls.clear()
        books2, complete2 = src4._build_index(deadline=time.time() + 30.0)
        check("★ 8 个分类全都抓（不受上限影响）", len(calls) == len(WY.CATEGORIES),
              f"calls={len(calls)} 分类数={len(WY.CATEGORIES)}")
        check("抓全了就报 complete=True", complete2 is True)
        check("抓全了才落盘", src4._load_index(deadline=time.time() + 30.0)
              and tmp_cache.exists(), str(tmp_cache))

        print("\n—— ⑨ 拼音兜底也要认 deadline（它才是第二段 8 次请求） ——")
        calls.clear()
        got = src4._search_by_pinyin("微微一笑很倾城", deadline=time.time() - 1)
        check("★ deadline 已过 → 一个分类都不试", calls == [],
              f"calls={len(calls)} —— 到点还试，等于 8 次请求照发")
        check("返回空而不是瞎编一个结果", got == [], str(got)[:80])

        print("\n—— ⑩ 索引一本都没抓到必须**说出来**（静默空 = 熔断器永远学不到） ——")
        def _boom_fetch(url, **kw):
            raise TimeoutError("_ssl.c:990: The handshake operation timed out")

        WY.fetch_text = _boom_fetch            # type: ignore[assignment]
        if tmp_cache.exists():
            tmp_cache.unlink()
        src5 = WY.WyshuSource()
        src5.take_error()
        src5._load_index(deadline=time.time() + 5.0)
        err = src5.take_error()
        check("★ 索引为空时把错误记下来了（否则引擎当成「答话了、没这本书」）",
              bool(err) and "索引为空" in err, repr(err))
        check("空索引不落盘", not tmp_cache.exists())
    finally:
        WY.fetch_text = _old_fetch             # type: ignore[assignment]
        WY.CACHE_FILE = _old_cache             # type: ignore[assignment]
        try:
            if tmp_cache.exists():
                tmp_cache.unlink()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # ⑪~⑭ 「声明了 6s，可调用方只等 1.5s」+「预算不是墙钟」（2026-11-15 复盘）
    # ------------------------------------------------------------------
    # 线上/本机实测（2026-11-15，直连这个源、不经引擎）：
    #   12 本真实书名只有 2 本命中，其余全走拼音兜底、**0 命中**、
    #   每本烧 2.7~4.0s；其中《我的阿勒泰》跑了 **10230ms**（声明 6s）。
    # 引擎那头：`搜索收手 1.5s 放弃 ...(wyshu)`，6 秒后它才回来 ——
    # 抓到的 594 本被整批扔掉。并且：8 个分类页串行要 4.25s（并行 3.07s，
    # 站点会限速），所以同步建**永远**被截断 → 不落盘 → 下一轮还是冷的 →
    # 它 100% 的时间都在白跑。修法：搜索只读缓存，冷的踢后台。
    #
    # ⚠ 判据刻意不看耗时（随机器负载漂），看的是**结构事实**：
    #   同步路径有没有抓取、后台有没有真的起来并在建完后落盘、
    #   传给 httpx 的超时是多少、请求次数有没有被预算截住。
    print("\n—— ⑪ 冷索引：搜索不许同步建，踢后台 ——")
    _old_fetch2 = WY.fetch_text
    _old_cache2 = WY.CACHE_FILE
    tmp_cold = ROOT / "cache" / "_test_wyshu_cold.json"
    WY.CACHE_FILE = tmp_cold                   # type: ignore[assignment]
    if tmp_cold.exists():
        tmp_cold.unlink()
    WY._BUILD_STATE.update({"running": False, "last": 0.0, "thread": None})
    calls_c: list[str] = []

    def _cat_fetch(url, **kw):
        calls_c.append(url)
        return '<a href="/ys/ceshi/">测试书(某人所著小说)_在线阅读</a>'

    WY.fetch_text = _cat_fetch                 # type: ignore[assignment]
    try:
        src6 = WY.WyshuSource()
        # ⚠ 这里必须把 `_kick_build` 换成一个只记账的桩：
        #   它一起来就会开始抓分类页，直接断言 `calls_c == []` 是在**赌线程启动慢**
        #   （第一版就这么写，跑第二遍就红了 —— 后台已经抓了两个分类页）。
        #   判据要问的是"搜索这条同步路径有没有抓取"，不是"机器多快"。
        kicks: list[int] = []
        src6._kick_build = lambda: kicks.append(1)   # type: ignore[method-assign]
        got6 = src6.search("三体")
        check("★ 冷索引时**同步路径一次抓取都不发**（同步建必然被引擎半路扔掉）",
              calls_c == [], f"calls={len(calls_c)}")
        check("★ 冷索引把构建踢出去了（否则永远冷）", kicks == [1], f"kicks={kicks}")
        check("冷索引返回空，不拿残缺索引冒充结果", got6 == [], str(got6)[:60])

        print("\n—— ⑪b 真的踢一次后台：建完要落盘、抓的是分类页 ——")
        del src6._kick_build                       # 还原成真实现
        WY._BUILD_STATE.update({"running": False, "last": 0.0, "thread": None})
        src6._kick_build()
        th = WY._BUILD_STATE.get("thread")
        check("后台构建线程起来了", th is not None, repr(th))
        if th is not None:
            th.join(timeout=10)
        check("后台建完 → 落盘（下一轮才可能是热的）", tmp_cold.exists(),
              str(tmp_cold))
        check("后台**真的抓了**分类页（不是空转）",
              len([u for u in calls_c if u.rstrip("/").endswith(tuple(WY.CATEGORIES))]) >= 1,
              str(calls_c[:3]))

        print("\n—— ⑫ 热了之后真有产出（它原先 100% 白跑） ——")
        calls_c.clear()
        got7 = src6.search("测试书")
        check("★ 热索引命中（0 抓取、结果里就是那本书）",
              any("测试书" in b.title for b in got7) and calls_c == [],
              f"条={len(got7)} calls={len(calls_c)}")

        print("\n—— ⑬ 后台构建单飞：同一时刻只建一份 ——")
        if tmp_cold.exists():
            tmp_cold.unlink()
        WY._BUILD_STATE.update({"running": False, "last": 0.0, "thread": None})
        calls_c.clear()
        src6._kick_build()
        th1 = WY._BUILD_STATE.get("thread")
        src6._kick_build()
        th2 = WY._BUILD_STATE.get("thread")
        check("★ 连踢两次只建一份（第二次被闸门挡掉）",
              th1 is not None and th1 is th2, f"{th1} vs {th2}")
        if th1 is not None:
            th1.join(timeout=10)
        check("被挡掉的第二次不许另起一批抓取（8 个分类只抓一遍）",
              len([u for u in calls_c if "/ys/" in u or "/wx/" in u]) <= 3,
              str(calls_c[:5]))

        print("\n—— ⑭ 拼音兜底：单独预算 + 单请求墙钟 ——")
        # 这一段每次搜索都会跑（索引没命中时），实测 12/12 空手、每次 2.7~4.0s，
        # 而引擎 1.5s 就收手 —— 超过它的部分全部是白烧的线程和连接。
        tmp_cold.write_text(json.dumps(
            {"_ts": time.time(), "books": {"别的书": {"url": "https://www.wyshu.com/ys/biede/",
                                                   "author": ""}}},
            ensure_ascii=False), encoding="utf-8")
        py_calls: list[str] = []
        timeouts: list[float | None] = []

        def _slow_py(url, **kw):
            py_calls.append(url)
            timeouts.append(current_timeout())
            time.sleep(0.50)
            return "not a detail page"

        WY.fetch_text = _slow_py             # type: ignore[assignment]
        src7 = WY.WyshuSource()
        src7.PINYIN_BUDGET = 1.6
        got8 = src7.search("搜不到的书")
        check("★ 预算到了就不再发（8 个分类被截在 4 个以内）",
              len(py_calls) <= 4,
              f"calls={len(py_calls)} —— 8 个全试说明预算没生效"
              "（1.6s 预算 / 每次 0.5s，允许一个在飞请求的尾巴）")
        check("拼音兜底没命中时返回空而不是瞎编", got8 == [], str(got8)[:60])
        check("★ 每次请求都**带着超时**发（不是 None / 不是默认 12s）",
              bool(timeouts) and all(t is not None and t <= 1.6 for t in timeouts),
              str(timeouts))
        # 反面：把「和剩余预算取小」去掉之后，超时会一直是常量上限。
        # 判据是"最后一次比第一次小"——剩余时间在变少，它必须跟着变。
        check("★ 超时跟着**剩余预算**缩（去掉 min(剩余,上限) 就变常量）",
              len(timeouts) >= 2 and max(timeouts) > min(timeouts),
              str(timeouts))
    finally:
        WY.fetch_text = _old_fetch2            # type: ignore[assignment]
        WY.CACHE_FILE = _old_cache2            # type: ignore[assignment]
        WY._BUILD_STATE.update({"running": False, "last": 0.0, "thread": None})
        try:
            if tmp_cold.exists():
                tmp_cold.unlink()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # ⑮ 退避睡眠也必须认 deadline（2026-11-15：声明 6s，实测 7.33s）
    # ------------------------------------------------------------------
    # wikisource 的请求超时早就夹过剩余预算了，但**两次退避睡眠是无条件的**，
    # 睡完也不再看表 → 6s 预算实测 7.2~7.3s（3 本真书 3/3 如此、且 3/3 都是 0 条）。
    # 判据看「睡多久」，不看总耗时（后者随机器负载漂）。
    print("\n—— ⑮ 退避睡眠不许越过预算（预算是承诺，不是墙钟） ——")
    _old_ws_client = WS.get_client
    _old_ws_time = WS.time

    class _FakeTime:
        """只记录 sleep、不真的睡；sleep 推进**虚拟时钟**（否则"预算用完"永远不来）。

        ⚠ 第一版没推进时钟 → 两次退避各睡 0.3s、加起来 0.6s，判据报红
          而产品是对的。假时钟必须自己也走，否则测的是假象。
        """

        def __init__(self) -> None:
            self.sleeps: list[float] = []
            self.offset = 0.0

        def time(self) -> float:
            return time.time() + self.offset

        def sleep(self, s: float) -> None:
            self.sleeps.append(s)
            self.offset += s

    shim = _FakeTime()
    boom2 = _BoomClient()
    WS.time = shim                              # type: ignore[assignment]
    WS.get_client = lambda *a, **k: boom2       # type: ignore[assignment]
    try:
        try:
            src._api({"action": "query"}, retries=2, deadline=time.time() + 0.30)
        except RuntimeError:
            pass
        check("★ 退避睡眠不超过剩余预算（不夹 = 6s 预算跑出 7.33s）",
              bool(shim.sleeps) and sum(shim.sleeps) <= 0.35,
              f"sleeps={shim.sleeps}")
        check("预算用完之后不再发请求", boom2.calls <= 2, f"calls={boom2.calls}")

        shim.sleeps.clear()
        boom3 = _BoomClient()
        WS.get_client = lambda *a, **k: boom3   # type: ignore[assignment]
        try:
            src._api({"action": "query"}, retries=3, deadline=time.time() - 1)
        except RuntimeError:
            pass
        check("★ 预算已过时**一秒都不睡**（老实现会先睡 1.0s 再判）",
              shim.sleeps == [], f"sleeps={shim.sleeps}")
        check("预算已过时也不发请求", boom3.calls == 0, f"calls={boom3.calls}")
    finally:
        WS.time = _old_ws_time                  # type: ignore[assignment]
        WS.get_client = _old_ws_client          # type: ignore[assignment]

    print(f"\n{'='*60}\n通过 {ok_n} / 失败 {fail_n}\n")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
