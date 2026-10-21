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

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.sources.wikisource as WS  # noqa: E402

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

    print(f"\n{'='*60}\n通过 {ok_n} / 失败 {fail_n}\n")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
