#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
锁定「本地全灭 → 联网兜底」这条链路
============================================================================
这是一个**线上事故**的回归测试。事故经过（2026-10-12）：

  用户搜《欢迎进入梦魇直播间》，线上返回 0 条，但**不报任何错**。

  根因是一条死链：
    · xbqg5200（唯一有这本书的常规源）在腾讯云 IP 上首页 502
    · wikisource 要 **184 秒**才返回 —— 所以 done_count 永远停在 5/7
    · 判「本地是否尽力搜过」的条件写的是 `done_count >= len(futs)`
      （要求**每一个**源都答完）—— 永远不成立
    · 于是联网兜底被**永久跳过**
    · 而联网源（web）明明有这本书（6 条、0.0s）

  修法：把「尽力了」改成「所有源答完 **或** 等到了墙钟上限」。
  等到了墙钟上限（hit_deadline）就意味着「该给的耐心给够了」。

为什么必须用假源、不能跑真网络：
  要复现「某个源永不返回」，只能**造一个会挂起的源**。
  真站点的行为不可控（今天 502 明天正常），测试会变成碰运气。

为什么这个测试值得存在：
  这类 bug **不抛异常、不打错误日志**，只表现成「搜不到」——
  靠人工回归几乎必然漏掉。只有断言能钉住它。
============================================================================
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import engine as E                      # noqa: E402
from app.models import BookResult                # noqa: E402

ok_n = 0
bad_n = 0


def ok(m):
    global ok_n
    ok_n += 1
    print(f"  ✓ {m}")


def bad(m):
    global bad_n
    bad_n += 1
    print(f"  ✗ {m}")


def section(t):
    print(f"\n── {t} " + "─" * max(0, 56 - len(t)))


KW = "欢迎进入梦魇直播间"


class HangSrc:
    """会挂起的源 —— 模拟 wikisource（184s 才返回）。

    ⚠ 它是这个测试的**灵魂**：没有它，done_count 就追得上 total，
      `exhausted` 会真，bug 复现不出来。
    """
    name = "hang"
    display = "挂起源"
    priority = 1
    lazy = False
    enabled = True

    def set_log(self, cb):
        pass

    def search(self, kw):
        time.sleep(30)          # 远超测试里设的硬上限
        return []


class EmptySrc:
    """立刻返回、但什么都没有的源 —— 模拟 www_xbiquge_info（全是分类噪声）。"""
    name = "empty"
    display = "空源"
    priority = 2
    lazy = False
    enabled = True

    def set_log(self, cb):
        pass

    def search(self, kw):
        return []


class GoodSrc:
    """本地就能搜到的源 —— 用来验证「有结果时不该联网」。"""
    name = "good"
    display = "好源"
    priority = 3
    lazy = False
    enabled = True

    def set_log(self, cb):
        pass

    def search(self, kw):
        return [BookResult(title=KW, author="桑沃", source=self.name,
                           url="http://good/1")]


class FakeWeb:
    """联网发现源。记录被调了几次 —— 这是断言的核心。"""
    name = E.DISCOVER_SOURCE
    display = "联网发现"
    priority = 90
    lazy = True
    enabled = True

    def __init__(self):
        self.calls = 0
        self.lock = threading.Lock()

    def set_log(self, cb):
        pass

    def search(self, kw):
        with self.lock:
            self.calls += 1
        return [BookResult(title=KW, author="桑沃", source=self.name,
                           url="http://web/1")]


def run_case(sources, discover=True, stats=None):
    eng = E.Engine(sources=sources)
    return eng.search(KW, probe=False, sample=False, discover=discover,
                      stats=stats)


def main() -> int:
    print("=" * 62)
    print("联网兜底回归（本地全灭必须触发）")
    print("=" * 62)

    # 把时间常量压到很小，测试才能在几秒内跑完。
    # 只改本进程的模块全局，不影响别的测试（各测试是独立进程）。
    E.SEARCH_HARD_DEADLINE = 2.0
    E.SEARCH_SOFT_DEADLINE = 1.0
    E.SEARCH_MIN_WAIT = 0.2
    E.SEARCH_GRACE = 0.5

    # -----------------------------------------------------------------
    section("1. 本地全灭（含「有源永不返回」）→ 必须联网")
    web = FakeWeb()
    st: dict = {}
    t0 = time.time()
    res = run_case([HangSrc(), EmptySrc(), web], discover=True, stats=st)
    dt = time.time() - t0

    if web.calls >= 1:
        ok(f"联网兜底被触发（web 源被调 {web.calls} 次）")
    else:
        bad("本地全灭却**没有**联网 —— 真出线上事故时就是这样：不报错、只是搜不到")

    if st.get("discovered", 0) >= 1:
        ok(f"stats.discovered = {st['discovered']}（联网来的候选进了结果）")
    else:
        bad(f"stats.discovered = {st.get('discovered')} —— 联网结果没进 stats")

    if res:
        ok(f"最终返回 {len(res)} 条：《{res[0].title}》（{dt:.1f}s）")
    else:
        bad(f"最终 0 条（联网明明有货）—— 兜底链路没接通")

    # -----------------------------------------------------------------
    section("2. 有源永不返回时，不能干等它 —— 到墙钟上限就走")
    # HangSrc 睡 30s，但硬上限是 2s。整轮必须在 3s 内结束，
    # 否则说明「等所有源」的老毛病又回来了。
    if dt < 10:
        ok(f"整轮 {dt:.1f}s 就结束了（没有被那个永不返回的源拖住）")
    else:
        bad(f"整轮花了 {dt:.1f}s —— 被挂起源拖住了，硬上限没生效")

    # -----------------------------------------------------------------
    section("3. 本地有结果 → 不联网（联网是兜底，不是常规路径）")
    web2 = FakeWeb()
    st2: dict = {}
    res2 = run_case([GoodSrc(), web2], discover=True, stats=st2)
    if web2.calls == 0:
        ok("本地能搜到时没有联网（省了一次 10s 的联网）")
    else:
        bad(f"本地有结果却联网了（web 被调 {web2.calls} 次）—— 每搜一次都白多花十几秒")
    if res2:
        ok(f"返回 {len(res2)} 条")
    else:
        bad("本地有结果的场景返回了 0 条 —— 回归了")

    # -----------------------------------------------------------------
    section("4. discover=False 时要能关掉（别把兜底做成强制）")
    web3 = FakeWeb()
    run_case([HangSrc(), EmptySrc(), web3], discover=False, stats={})
    if web3.calls == 0:
        ok("discover=False 时确实不联网")
    else:
        bad(f"discover=False 仍然联网了 {web3.calls} 次")

    print("\n" + "=" * 62)
    print(f"通过 {ok_n} · 失败 {bad_n}")
    if bad_n:
        print("✗ 有问题，见上面 ✗ 行")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
