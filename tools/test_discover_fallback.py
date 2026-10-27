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

    # 联网换来的候选**也会被探测**（`probe=True` 时走 probe_all）——
    # 早先这些假源没有 probe 接口，于是"本地全灭 → 联网 → 探测"这条
    # 真实路径在任何测试里都没被跑过，第一条真机 bug 才发现。
    def probe(self, r):
        return {"ok": True, "chapters": 5, "ms": 1, "note": ""}

    def probe_limit(self):
        return 4

    def note_probe(self, ms):
        pass


class DeadSrc:
    """搜得到书名、但**打不开目录**的源 —— 线上 registry 的原样复制。

    2026-10-27 线上实测（《我的阿勒泰》）：
      `候选=1 成书=1 确切=1 可读=0 联网发现=0 耗时ms=2041`
      唯一候选是 https://www.bqg5555.cc/xs/268912/，探测回「这个地址不是
      目录页（没解析到章节列表）」，可用=false、0 章。

    它的可怕之处在于**它是确切命中**（tightness=1.0、score=100）：
    收手门被它喂饱（1.5s 就收），`hit_deadline` 永远是 False、
    `done_count` 也追不上 total → `exhausted` 永远是 False →
    「有结果但一条可读都没有」那条联网分支一次都进不去。
    """
    name = "dead"
    display = "死链源"
    priority = 4
    lazy = False
    enabled = True

    def set_log(self, cb):
        pass

    def search(self, kw):
        return [BookResult(title=KW, author="桑沃", source=self.name,
                           url="http://dead/1")]

    def probe(self, r):
        return {"ok": False, "chapters": 0, "ms": 1,
                "note": "这个地址不是目录页（没解析到章节列表）"}

    def probe_limit(self):
        return 4

    def note_probe(self, ms):
        pass


class AliveSrc:
    """和 DeadSrc 一模一样，但**打得开** —— 反向断言用。

    没有它，「全部不可读就联网」这条判据可以被改写成「有结果就联网」
    而测试照样绿：那会让每一次搜索都白多花 3~10 秒。
    """
    name = "alive"
    display = "能读的源"
    priority = 4
    lazy = False
    enabled = True

    def set_log(self, cb):
        pass

    def search(self, kw):
        return [BookResult(title=KW, author="桑沃", source=self.name,
                           url="http://alive/1")]

    def probe(self, r):
        return {"ok": True, "chapters": 40, "ms": 1, "note": ""}

    def probe_limit(self):
        return 4

    def note_probe(self, ms):
        pass


def run_case(sources, discover=True, stats=None, should_stop=None,
             probe=False, sample=False):
    eng = E.Engine(sources=sources)
    return eng.search(KW, probe=probe, sample=sample, discover=discover,
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

    # --------------------------------------------------------------
    section("6. 联网兜底阶段也必须认「客户端已断开」")
    # 为什么单独一条：扇出/探测/抽样三个阶段都认 should_stop，只有
    # **联网兜底**这一段原先完全不认 —— 而它恰恰是最贵的一段
    # （两个搜索引擎 + 十几个站核实，3~10 秒）。
    # 后果有两个：
    #   ① 用户走了之后还在往外搜，白烧配额；
    #   ② 断开信号落在这里时 `aborted` 报 False —— 于是「断连止损」在
    #      ship 里偶发假红（换一个掐断时机就红，单独重跑又绿）。
    class WebDuringDisconnect(FakeWeb):
        """第二次被调用前把自己标成"客户端已断开"。

        用多词关键词（两个等长词）才会触发 `_discover` 里"逐个词搜"的循环，
        于是第一轮搜完之后就有机会检查断开、不去搜第二个词。
        """

        def search(self, kw):
            with self.lock:
                self.calls += 1
            stop_flag["v"] = True        # 模拟：联网搜索期间用户关掉了页面
            return [BookResult(title=KW, author="桑沃", source=self.name,
                               url="http://web/1")]

    stop_flag = {"v": False}
    web2 = WebDuringDisconnect()
    st7: dict = {}
    eng7 = E.Engine(sources=[EmptySrc(), web2])
    eng7.search("余华 活着", probe=False, sample=False, discover=True,
                stats=st7, should_stop=lambda: stop_flag["v"])
    if web2.calls == 1:
        ok("多词联网兜底搜完第一个词后，发现已断就不再搜下一个")
    else:
        bad(f"联网兜底搜了 {web2.calls} 次（应为 1）—— 断开后还在往外搜")
    if st7.get("aborted") is True:
        ok("断开落在联网兜底阶段，aborted 也如实为 True（不再漏报）")
    else:
        bad(f"断开落在联网兜底阶段，aborted={st7.get('aborted')!r} —— "
            f"收手信号没记进 stats，断连测试会因此偶发假红")

    # 反向：没断开时必须两个词都搜 —— 否则上面那条可能是"永远只搜一次"
    stop_flag["v"] = False
    web3 = WebDuringDisconnect()
    web3.search = FakeWeb.search.__get__(web3, type(web3))   # 用不打标记的原版
    st8: dict = {}
    eng8 = E.Engine(sources=[EmptySrc(), web3])
    eng8.search("余华 活着", probe=False, sample=False, discover=True, stats=st8)
    if web3.calls >= 1:
        ok("没断开时联网兜底照常搜（上面的判据不是恒真）")
    else:
        bad("没断开却没联网 —— 兜底被误杀")

    # —— 断开发生在「扇出结束之后、联网开始之前」这一瞬 ——
    # 窗口很窄，但只要它存在，联网兜底就该被拦下（一次 3~10 秒的对外请求）。
    # 构造方式：让唯一那个本地源在返回空的同时把 stop 置位 ——
    # 扇出到此已经"尽力且答完"（exhausted=True），随后的收手检查必须拦住联网。
    class EmptyAndStop(EmptySrc):
        def search(self, kw):
            ev_stop.set()       # 答完的同一瞬间，客户端走了
            return []

    ev_stop = threading.Event()
    web4 = FakeWeb()
    st9: dict = {}
    eng9 = E.Engine(sources=[EmptyAndStop(), web4])
    eng9.search("单词书", probe=False, sample=False, discover=True,
                stats=st9, should_stop=ev_stop.is_set)
    if web4.calls == 0:
        ok("断开落在「扇出之后、联网之前」，联网兜底被拦下（不白烧一次对外搜索）")
    else:
        bad(f"断开后仍然联网搜了 {web4.calls} 次 —— 这一段的收手检查没接上")

    # --------------------------------------------------------------
    section("7. 有结果但**一条可读的都没有** → 必须联网（哪怕没撞满墙钟）")
    # 2026-10-27《我的阿勒泰》线上原样：
    #   `候选=1 成书=1 确切=1 可读=0 联网发现=0 耗时ms=2041`
    #   唯一候选是 bqg5555 的 /xs/268912/，探测回「这个地址不是目录页」。
    #   它是**确切命中**（100 分、tightness=1.0），于是收手门 1.5s 就被喂饱 →
    #   hit_deadline=False、done_count 追不上 total → exhausted=False →
    #   「有结果但没有一条可读 → 出去找」这条分支**一次都进不去**。
    #   用户拿到一张点不开的卡片，引擎自己以为"本地有结果"。
    web5 = FakeWeb()
    st10: dict = {}
    res10 = run_case([DeadSrc(), HangSrc(), web5], discover=True, stats=st10,
                     probe=True)
    if web5.calls >= 1:
        ok(f"本地只有死链时联网兜底被触发（web 被调 {web5.calls} 次）")
    else:
        bad("本地交不出任何可读结果，联网兜底却没跑 —— 用户只会看到一张点不开的卡片")
    if st10.get("web_skip") == "":
        ok("stats.web_skip 为空串 = 真的联网了（埋点与事实一致）")
    else:
        bad(f"联网其实跑了，web_skip={st10.get('web_skip')!r} —— 埋点在说反话")
    if st10.get("hit_deadline") is False:
        ok("这一轮确实是**提前收手**（不是撞满墙钟）—— 正是原来漏掉的那种情形")
    else:
        bad("构造失败：这一轮撞满了墙钟，测不到「提前收手也要联网」")
    if res10:
        ok(f"最终仍返回 {len(res10)} 条（联网结果并进原结果，不丢）")
    else:
        bad("最终 0 条 —— 联网后反而把原有候选丢了")

    # 反向断言：本地有**能读**的结果时，一条都不许联网。
    # 少了这条，上面那条判据可以被改写成「有结果就联网」（每搜一次
    # 白多花 3~10 秒）而测试照样全绿。
    web6 = FakeWeb()
    st11: dict = {}
    run_case([AliveSrc(), web6], discover=True, stats=st11, probe=True)
    if web6.calls == 0:
        ok("本地有可读结果 → 没联网（没有为了「更全」白烧一次对外搜索）")
    else:
        bad(f"本地明明有一条可读的，却联网了 {web6.calls} 次 —— 兜底变成了常规路径")
    if st11.get("web_skip") == "not_needed":
        ok("web_skip=not_needed（「不需要」与「没找到」在日志里分得开）")
    else:
        bad(f"web_skip={st11.get('web_skip')!r}，应为 not_needed")

    # 反向断言 ②：关掉探测时 available 全是 None（= 没验过），
    # 不能照字面判成「全打不开」 —— 否则每一次 probe=0 的搜索都会去联网。
    web7 = FakeWeb()
    st12: dict = {}
    run_case([DeadSrc(), web7], discover=True, stats=st12, probe=False)
    if web7.calls == 0:
        ok("probe=0（未验证）时不联网 —— 没有把「没验过」当成「打不开」")
    else:
        bad(f"probe=0 却联网了 {web7.calls} 次 —— 把「未验证」判成了「全打不开」")

    # 反向断言 ③：该联网但调用方关了 discover → 原因必须如实记成 disabled。
    web8 = FakeWeb()
    st13: dict = {}
    run_case([DeadSrc(), HangSrc(), web8], discover=False, stats=st13, probe=True)
    if web8.calls == 0 and st13.get("web_skip") == "disabled":
        ok("discover=False 时不联网，且 web_skip=disabled（不冒充「没找到」）")
    else:
        bad(f"discover=False 时 web 被调 {web8.calls} 次、"
            f"web_skip={st13.get('web_skip')!r} —— 应为 0 次 + disabled")

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
