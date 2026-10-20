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

    ⚠ 挂起必须**可放行**（`release()`），不能裸睡。
      踩过：原来写的是 `time.sleep(30)`，测试逻辑 2 秒就跑完了，可进程
      退出时还要**干等 28 秒** —— `concurrent.futures.thread` 注册了
      atexit 钩子去 join 所有工作线程，而非 daemon 线程不会因为主逻辑
      结束就消失。实测单跑这个测试要 **34.9s**，其中 30s 纯等待；
      它还在 ship 的静态套件里，每次上线都白烧这 30 秒。
      现在改成等一个 Event，测试收尾时统一 set —— 挂起时长对被测逻辑
      没有影响（它要的只是"在硬上限内不返回"），但对总耗时影响 30 秒。
    """
    name = "hang"
    display = "挂起源"
    priority = 1
    lazy = False
    enabled = True
    _live: list = []

    def __init__(self):
        self._stop = threading.Event()
        HangSrc._live.append(self)

    @classmethod
    def release(cls):
        for s in cls._live:
            s._stop.set()

    def set_log(self, cb):
        pass

    def search(self, kw):
        self._stop.wait(30)     # 远超测试里设的硬上限，但收尾时可立刻放行
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


def run_case(sources, discover=True, stats=None, should_stop=None):
    eng = E.Engine(sources=sources)
    return eng.search(KW, probe=False, sample=False, discover=discover,
                      stats=stats, should_stop=should_stop)


def _run() -> int:
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

    # -----------------------------------------------------------------
    section("5. 断开收手必须在 stats 上如实体现（收手可能落在**任何**阶段）")
    # 为什么单列一条：
    #   `aborted` 以前只由**正文抽样**一个阶段回答。断开如果落在
    #   扇出 / 探测 / 联网兜底，收手**确实发生了**（那些阶段都认 should_stop、
    #   也确实提前停了），但 `aborted` 仍然是 False —— 对外报"这一轮跑完了"。
    #   后果不只是数字不准：真机那条断连测试的判据就是它，于是那条测试
    #   能不能过**取决于 2 秒掐断恰好落在采样窗口里**（窗口很窄），
    #   表现为时绿时红的"偶发假红"——而偶发假红最容易把真问题一起糊过去。
    #   这条判据不依赖任何时序：传一个恒真的 should_stop 就能稳定复现。
    st5: dict = {}
    run_case([HangSrc(), EmptySrc()], discover=False, stats=st5,
             should_stop=lambda: True)
    if st5.get("aborted"):
        ok("在扇出阶段就被打断 → aborted=True（旧实现这里是 False）")
    else:
        bad(f"扇出阶段已经收手，aborted 却是 {st5.get('aborted')!r} —— "
            "收手信号没记进 stats（真机断连测试会因此偶发假红）")

    # 反证：**没**断开的一轮不许报 aborted。少了这条，上面那条就可能是恒真。
    st6: dict = {}
    run_case([GoodSrc()], discover=False, stats=st6, should_stop=lambda: False)
    if st6.get("aborted") is False:
        ok("没有断开的一轮 aborted=False（上面的判据不是恒真）")
    else:
        bad(f"没断开也报了 aborted={st6.get('aborted')!r} —— 判据恒真，等于没测")

    # 接线：**每个**阶段的收手都要汇到 `_stop()`（唯一的置位点）。
    # 光靠上面那条还不够 —— 它命中的是扇出阶段；如果探测/联网阶段
    # 直接把原始 `should_stop` 透传下去，断开落在那些阶段时照样不记。
    # 这类"漏一个出口"的写法不会报错，只会在换一个掐断时机时失效。
    #
    # ⚠ 这里原先用 `eng_src.count("should_stop=_stop)")` 配一个写死的期望值 4。
    #   它坏过两次，两次都不是产品坏了：
    #     ① 给某个调用加了 `budget=` 参数 → 变成 `should_stop=_stop, budget=..)`，
    #        收尾的 `)` 没了，计数直接掉到 0；
    #     ② 多了一个「联网兜底后探测」的调用点 → 总数变成 5，"应为 4" 当场误报。
    #   子串计数只认文本形状，不认语法结构 —— 换个换行就漂。改用 AST：
    #   按**调用点**数，逐个检查它传的 should_stop 是不是 `_stop`。
    #   这样加调用点、改参数顺序、拆成多行都不会误报，而"漏传原始函数"照样抓住。
    import ast

    eng_src = (ROOT / "app" / "engine.py").read_text(encoding="utf-8")
    tree = ast.parse(eng_src)
    phase_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr in ("probe_all", "verify_samples")
    ]

    def _stop_arg(call: ast.Call):
        for kw in call.keywords:
            if kw.arg == "should_stop":
                return getattr(kw.value, "id", None) or "(非简单名)"
        return None

    wrong = [(c.lineno, _stop_arg(c)) for c in phase_calls
             if _stop_arg(c) != "_stop"]
    if len(phase_calls) >= 4 and not wrong:
        ok(f"探测/联网/抽样各阶段的收手都汇到 _stop()"
           f"（{len(phase_calls)} 个调用点全部传 _stop）")
    else:
        bad(f"有 {len(wrong)} 个阶段的收手没汇到 _stop()：{wrong}"
            f"（共 {len(phase_calls)} 个调用点）—— 那些阶段的收手不会被记进 stats")

    print("\n" + "=" * 62)
    print(f"通过 {ok_n} · 失败 {bad_n}")
    if bad_n:
        print("✗ 有问题，见上面 ✗ 行")
        return 1
    print("✓ 全部通过")
    return 0


def main() -> int:
    try:
        return _run()
    finally:
        # ⚠ 必须放行挂起源的工作线程，否则它们会一直等 Event ——
        #   `concurrent.futures.thread` 注册的 atexit 钩子会 join 所有
        #   工作线程，于是进程在**逻辑已经跑完之后**再干等 30 秒。
        #   （这个测试单跑曾要 34.9s，其中 30s 是纯等待。）
        HangSrc.release()


if __name__ == "__main__":
    raise SystemExit(main())
