# -*- coding: utf-8 -*-
"""源熔断器（app/sourcehealth.py）的行为测试。**纯逻辑，不联网。**

为什么必须有这条
----------------
2026-10-21 线上真实日志（同一本书《青叶灵异事务所》，相隔 6 分钟）：

    00:40  search.start → xbqg5200 HTTP 403 / wikisource SSL 握手超时
           → 搜索收手（墙钟 20.0s 到点，仍无结果）：已答 4/7 个源、原始 0 条
    00:46  同一本书再搜 → 5/7 个源答完 → 有 1 条结果

同一本书、同一台服务器，一次 0 条、一次 1 条。差别只在"这次哪几个源先回来"。
那几个**永远回不来**的源每次都在名单里，每次都要陪它们等满 20 秒。

熔断器就是给这件事加记忆。而它的判据有一个**必须写死的反向约束**：

    返回空列表 ≠ 挂

如果空结果也算失败，搜几本冷门书就会把所有源全拉黑，之后搜什么都 0 条 ——
比慢更糟，而且完全静默（没有任何报错）。所以下面专门有一条
「空结果不算挂」的反向判据，改代码时别把它当废话删掉。

用法：python tools/test_source_health.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.sourcehealth import (COOLDOWN, HEALTH, KIND_NET, KIND_OTHER,  # noqa: E402
                              SourceHealth, classify)

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


def main() -> int:
    print("\n—— 分类：什么算「网络挂了」 ——")
    check("TimeoutError 算网络问题", classify(TimeoutError("read timeout")) == KIND_NET)
    check("ConnectionError 算网络问题", classify(ConnectionError("reset")) == KIND_NET)
    check("HTTP 403 的异常消息算网络问题",
          classify(RuntimeError("抓取失败: https://x/ (HTTP 403)")) == KIND_NET)
    check("HTTP 502 算网络问题",
          classify(RuntimeError("抓取失败: (HTTP 502)")) == KIND_NET)
    check("SSL 握手超时算网络问题",
          classify(RuntimeError("_ssl.c:990: The handshake operation timed out")) == KIND_NET)
    check("解析类错误不算网络问题（冷却短一些就该够）",
          classify(ValueError("找不到目录容器")) == KIND_OTHER)

    print("\n—— 熔断：连续挂才熔断，单次抖动不算 ——")
    h = SourceHealth()
    check("没见过的源默认放行", h.allows("a"))
    h.note_fail("a", TimeoutError("t"))
    check("挂一次**仍放行**（单次抖动不该被拉黑）", h.allows("a"),
          "一次失败就熔断 = 网络抖一下就把好源摘掉")
    tripped = h.note_fail("a", TimeoutError("t"))
    check("连续挂两次 → 触发熔断", tripped)
    check("熔断期内不放行", not h.allows("a"))

    print("\n—— 隔离：熔断只影响那个源 ——")
    check("别的源不受影响", h.allows("b"))

    print("\n—— 反向判据：空结果不是失败 ——")
    # 这条是全文最重要的正向约束的反面。空列表走 note_ok。
    h2 = SourceHealth()
    for _ in range(5):
        h2.note_ok("c")             # 连搜 5 次都没这本书
    check("连续 5 次空结果之后依然放行（空 ≠ 挂）", h2.allows("c"),
          "空结果被算成失败的话，搜冷门书会把所有源拉黑")

    print("\n—— 恢复：成功一次就清零 ——")
    h3 = SourceHealth()
    h3.note_fail("d", TimeoutError("t"))
    h3.note_fail("d", TimeoutError("t"))
    check("先确认它已熔断（不是恒真）", not h3.allows("d"))
    h3.note_ok("d")
    check("答话一次就恢复", h3.allows("d"))
    check("恢复后状态清空（没有残留计数）", not h3.snapshot())

    print("\n—— 半开：冷却到期放行一次，失败立刻重熔 ——")
    h4 = SourceHealth()
    h4.note_fail("e", TimeoutError("t"))
    h4.note_fail("e", TimeoutError("t"))
    check("已熔断", not h4.allows("e"))
    # 把冷却时间戳拨到过去，模拟"15 分钟到了"
    with h4._lock:                                  # noqa: SLF001
        h4._st["e"]["until"] = time.time() - 1      # noqa: SLF001
    check("冷却到期后放行（半开试探）", h4.allows("e"))
    tripped2 = h4.note_fail("e", TimeoutError("t"))
    check("半开试探再失败 → **立刻**重新熔断（不必再攒两次）", tripped2)
    check("重新熔断后不放行", not h4.allows("e"))

    print("\n—— 冷却时长：被墙的等更久 ——")
    h5 = SourceHealth()
    h5.note_fail("n", TimeoutError("t"))
    h5.note_fail("n", TimeoutError("t"))
    h5.note_fail("o", ValueError("解析失败"))
    h5.note_fail("o", ValueError("解析失败"))
    snap = h5.snapshot()
    net_until = snap["n"]["until"]
    other_until = snap["o"]["until"]
    check("网络类冷却比解析类长",
          COOLDOWN[KIND_NET] > COOLDOWN[KIND_OTHER],
          f"{COOLDOWN[KIND_NET]} vs {COOLDOWN[KIND_OTHER]}")
    check("实际写入的 until 也遵守这个差异（不是只写在常量里）",
          (net_until - time.time()) > (other_until - time.time()),
          f"net {net_until - time.time():.0f}s / other {other_until - time.time():.0f}s")

    print("\n—— 诊断：open_sources 能列出当前熔断的源 ——")
    h6 = SourceHealth()
    h6.note_fail("p", TimeoutError("t"))
    h6.note_fail("p", TimeoutError("t"))
    h6.note_ok("q")
    check("只列出真的熔断了的", h6.open_sources() == ["p"], str(h6.open_sources()))

    print("\n—— 全局单例 ——")
    check("HEALTH 是同一份（进程级共用）",
          HEALTH is __import__("app.sourcehealth", fromlist=["HEALTH"]).HEALTH)

    # ------------------------------------------------------------------
    print("\n—— 引擎真的用上它了吗（只测熔断器本身是不够的）——")
    # ⚠ 这一段的动机：上面 20 多条全绿也只证明「熔断器逻辑对」，
    #   完全可能引擎根本没调用它（= 一条没人用的死代码），而所有测试依然绿。
    #   这正是本项目反复抓到的「只数配置不验产物」。
    from app.engine import Engine
    from app.sources.base import Source

    class _Boom(Source):
        name = "boom_src"
        display = "会挂的源"
        priority = 1
        enabled = True
        calls = 0

        def search(self, keyword):
            type(self).calls += 1
            raise TimeoutError("SSL handshake timed out")

        def get_chapters(self, url): raise AssertionError("不该走到这")
        def fetch(self, *a, **k): raise AssertionError("不该走到这")

    class _OK(Source):
        name = "ok_src"
        display = "正常的源"
        priority = 2
        enabled = True
        calls = 0

        def search(self, keyword):
            type(self).calls += 1
            return []            # 没这本书 —— 正常业务结果，不是故障

        def get_chapters(self, url): return []
        def fetch(self, *a, **k): raise AssertionError("不该走到这")

    HEALTH.reset()
    eng = Engine(sources=[_Boom, _OK])
    for _ in range(3):
        eng.search("随便一本书", discover=False)
    check("引擎第一次真的调用了那个源（否则下面等于没测）",
          _Boom.calls >= 1, f"calls={_Boom.calls}")
    check("连续挂之后，引擎**不再调用**它（熔断接上了扇出）",
          _Boom.calls <= 2, f"calls={_Boom.calls} —— "
          f"引擎没走熔断，每次搜索都还在撞这堵墙")
    check("熔断器确实记下了它", "boom_src" in HEALTH.open_sources(),
          str(HEALTH.open_sources()))
    # ⚠ 这条必须在**引擎层**验，不能只在熔断器单元层验：
    #   引擎完全可能把「空结果」也当失败记进去（=`note_ok` 只在有结果时调）。
    #   那种写法下熔断器本身的单测依然全绿，而真实效果是
    #   「搜几本冷门书把所有源全拉黑」—— 用户侧表现就是"搜什么都 0 条"。
    check("空结果的源没被熔断（空 ≠ 挂，且在引擎里也成立）",
          "ok_src" not in HEALTH.open_sources(),
          f"ok_src 被熔断了：{HEALTH.open_sources()}")
    check("空结果的源每次搜索都还在被调用（没被悄悄摘出去）",
          _OK.calls >= 3, f"calls={_OK.calls}（3 次搜索应各调一次）")
    HEALTH.reset()

    print("\n" + "=" * 62)
    if fail_n == 0:
        print(f"通过 {ok_n} · 失败 0\n✓ 全部通过")
    else:
        print(f"通过 {ok_n} · 失败 {fail_n}\n✗ 有 {fail_n} 项没过")
    print("=" * 62)
    return 1 if fail_n else 0


if __name__ == "__main__":
    raise SystemExit(main())
