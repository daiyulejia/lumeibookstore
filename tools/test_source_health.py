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

    # ----------------------------------------------------------------
    # 「源自己把异常吞了」也必须熔断
    # ----------------------------------------------------------------
    # 2026-10-21 线上实测的真相：熔断器写了半天**一次都没触发**。
    # 原因是好几个源的 search() 为了"一种抓法失败换下一种"而自己 catch 掉、
    # 然后 return []（wikisource / xbqg5200 / kunnu8 都是这样）。
    # 在引擎看来这就是"答话了、只是没这本书" → note_ok 清零。
    # 于是：wikisource 一天 110 次 SSL 握手超时、xbqg5200 55 次 403，
    # 熔断日志 **0 条**，每次搜索都还在名单里陪它们等满 20 秒。
    class _Swallow(Source):
        name = "swallow_src"
        display = "自己吞异常的源"
        priority = 1
        enabled = True
        calls = 0

        def search(self, keyword):
            type(self).calls += 1
            try:
                raise TimeoutError("SSL handshake timed out")
            except Exception as e:          # noqa: BLE001
                self.note_error(e)          # ← 关键：留口条给熔断器
                return []

        def get_chapters(self, url): return []
        def fetch(self, *a, **k): raise AssertionError("不该走到这")

    class _SwallowOK(Source):
        """也吞了异常，但**拿到了结果** —— 一个站能出书就不该被拉黑。"""
        name = "swallow_ok"
        display = "吞了异常但有结果"
        priority = 2
        enabled = True
        calls = 0

        def search(self, keyword):
            type(self).calls += 1
            self.note_error(TimeoutError("某条通路超时"))   # 残留的错误
            from app.models import BookResult
            return [BookResult(title="随便一本书", source=self.name,
                               url="https://example.com/b/1")]

        def get_chapters(self, url): return []
        def fetch(self, *a, **k): raise AssertionError("不该走到这")

    HEALTH.reset()
    eng2 = Engine(sources=[_Swallow, _SwallowOK])
    for _ in range(3):
        eng2.search("随便一本书", discover=False)
    check("★ 源自己吞掉异常时，引擎照样记熔断（否则熔断器永远收不到失败）",
          "swallow_src" in HEALTH.open_sources(), str(HEALTH.open_sources()))
    check("★ 熔断接上了扇出：不再每次搜索都撞同一堵墙",
          _Swallow.calls <= 2, f"calls={_Swallow.calls}")
    # 反向：有结果就说明能与不能的问题解决了 —— 不能因为"内部某条通路失败"拉黑。
    check("★ 有结果时即使内部报错也不熔断（否则搜到书的源会被误杀）",
          "swallow_ok" not in HEALTH.open_sources(), str(HEALTH.open_sources()))
    check("有结果的源每次都在被调用", _SwallowOK.calls >= 3, f"calls={_SwallowOK.calls}")

    # 上一轮的残留错误不能算到这一轮头上（线程局部跨搜索保留）
    class _Flaky(Source):
        name = "flaky_err"
        display = "第一次吞了错、后来好了"
        priority = 1
        enabled = True
        calls = 0

        def search(self, keyword):
            type(self).calls += 1
            if type(self).calls == 1:
                self.note_error(TimeoutError("第一次超时"))
                return []
            return []          # 后面每次都正常答话（空结果）

        def get_chapters(self, url): return []
        def fetch(self, *a, **k): raise AssertionError("不该走到这")

    HEALTH.reset()
    eng3 = Engine(sources=[_Flaky])
    for _ in range(4):
        eng3.search("随便一本书", discover=False)
    check("★ 上一次吞的异常不会算到下一次（否则一次抖动永久拉黑）",
          "flaky_err" not in HEALTH.open_sources(), str(HEALTH.open_sources()))
    HEALTH.reset()

    # ------------------------------------------------------------------
    print("\n—— 卡死**不返回**的源：熔断器也必须学得到 ——")
    # ⚠ 这一段钉的是「判据漏项」，不是「源慢」。
    #   线上实测（2026-10-21）：wikisource 单次 search 要 **186.9 秒**才返回
    #   （5 次重试 + 递增退避，还串两次查询），而引擎 20 秒就收手。
    #   收手时只是把 future 丢下（pool.shutdown(wait=False)）——
    #   _run 永远走不到 note_fail，熔断器一次都不知道它挂过，
    #   于是**下一轮它还在名单里**，再占 20 秒。
    #   实测当天日志里 `The handshake operation timed out` 117 次、熔断 1 次。
    #
    # 所以判据必须是：墙钟到点仍未答话的源 → 也要 note_fail。
    class _Hang(Source):
        name = "hang_src"
        display = "永远不返回的源"
        priority = 1
        enabled = True
        calls = 0

        def search(self, keyword):
            type(self).calls += 1
            # 比本轮墙钟长，但**有限**：线程能自己收尾，测试进程不会挂死。
            # 不能用"真的永久 sleep"—— ThreadPoolExecutor 的线程是
            # 非 daemon 的，进程退出时会 join 它，测试就永远退不出来。
            time.sleep(2.0)
            return []

        def get_chapters(self, url): return []
        def fetch(self, *a, **k): raise AssertionError("不该走到这")

    class _Fast(Source):
        name = "fast_src"
        display = "正常答话的源"
        priority = 2
        enabled = True
        calls = 0

        def search(self, keyword):
            type(self).calls += 1
            return []          # 空结果 —— 正常业务结果

        def get_chapters(self, url): return []
        def fetch(self, *a, **k): raise AssertionError("不该走到这")

    # 把墙钟压到亚秒级，否则这条测试要等 20 秒 × 3 轮。
    # ⚠ 改的是**模块常量**（引擎每次调用都现读），不是函数默认参数 ——
    #   后者在 def 那一刻就固化了，改了也不生效（这个坑本项目踩过）。
    import app.engine as E
    _old = (E.SEARCH_HARD_DEADLINE, E.SEARCH_MIN_WAIT, E.SEARCH_SOFT_DEADLINE)
    E.SEARCH_HARD_DEADLINE = 0.6
    E.SEARCH_MIN_WAIT = 0.1
    E.SEARCH_SOFT_DEADLINE = 0.3
    try:
        HEALTH.reset()
        hang, fast = _Hang(), _Fast()
        eng4 = Engine(sources=[hang, fast])
        st: dict = {}
        seen: list[dict] = []
        for i in range(3):
            st = {}
            eng4.search("随便一本书", discover=False, probe=False,
                        sample=False, stats=st)
            seen.append(st)
        # ⚠ 只能看**熔断之前**那两轮的 stats：第三轮它已被摘出扇出名单，
        #   failed_sources 当然是空的。这条断言第一次写成只看最后一轮，
        #   于是"修好了"和"根本没记"长得一模一样（= 没牙）。
        check("墙钟到点的源被记进 failed_sources（日报才分得清"
              "「没这本书」和「源挂了」）",
              any("hang_src" in (s.get("failed_sources") or []) for s in seen),
              str([s.get("failed_sources") for s in seen]))
        check("★ 卡死不返回的源也会被熔断（不修则永远是「从不熔断」）",
              "hang_src" in HEALTH.open_sources(), str(HEALTH.open_sources()))
        check("★ 熔断接上了扇出：第三轮不再调用它",
              _Hang.calls <= 2, f"calls={_Hang.calls} —— 每轮还在撞这堵墙")
        check("正常答话（哪怕空结果）的源没被误杀",
              "fast_src" not in HEALTH.open_sources(), str(HEALTH.open_sources()))
        check("正常源每轮都被调用", _Fast.calls == 3, f"calls={_Fast.calls}")
    finally:
        HEALTH.reset()
        (E.SEARCH_HARD_DEADLINE, E.SEARCH_MIN_WAIT,
         E.SEARCH_SOFT_DEADLINE) = _old

    # ------------------------------------------------------------------
    print("\n—— 冷却退避：永远打不通的源不该每 15 分钟回来一次 ——")
    # ⚠ 线上实测（2026-10-22）：维基文库是境外站，云端 SSL 握手**必**超时。
    #   固定 15 分钟冷却 = 它每小时被放进来试 4 次，每次都让一次真实搜索
    #   陪它等（日志里 117 条 handshake timed out，救回来 0 次）。
    #   所以连挂的轮数越多，冷却越长。
    from app.sourcehealth import BACKOFF, MAX_COOLDOWN

    def trip_once(h, name: str, exc=None) -> float:
        """挂两次把它熔断，返回这次熔断用的冷却秒数。

        `exc` 直接传异常对象（不是消息字符串）—— 分类看的是类型：
        TimeoutError → 网络类（15 分钟起），ValueError → 解析类（5 分钟起）。
        """
        e = exc if exc is not None else TimeoutError("t")
        h.note_fail(name, e)
        return h.note_fail(name, e)

    def rearm(h, name: str) -> None:
        """把某个源的冷却拨到过去，模拟"时间到了、半开试探"。

        ⚠ 必须再调一次 `allows()`：`trial` 标记是它打的，只改 until 不算
          进入半开（不调的话下一次 note_fail 会当成"又挂了一次"，不熔断）。
        """
        with h._lock:                                   # noqa: SLF001
            h._st[name]["until"] = time.time() - 1      # noqa: SLF001
        h.allows(name)

    hb = SourceHealth()
    d1 = trip_once(hb, "bk")
    check(f"第一次熔断用基础冷却（{d1:.0f}s）",
          abs(d1 - COOLDOWN[KIND_NET]) < 1)
    rearm(hb, "bk")
    d2 = hb.note_fail("bk", TimeoutError("t"))
    check(f"第二次熔断翻倍（{d2:.0f}s ≈ {d1 * BACKOFF:.0f}s）",
          abs(d2 - d1 * BACKOFF) < 1)
    rearm(hb, "bk")
    d3 = hb.note_fail("bk", TimeoutError("t"))
    check(f"第三次再翻倍（{d3:.0f}s ≈ {d2 * BACKOFF:.0f}s）",
          abs(d3 - d2 * BACKOFF) < 1)
    # 一路挂下去要有天花板，否则冷却会涨到几年（等于永久拉黑，且不可解释）
    for _ in range(12):
        rearm(hb, "bk")
        last = hb.note_fail("bk", TimeoutError("t"))
    check(f"冷却封顶在 MAX_COOLDOWN（{last:.0f}s <= {MAX_COOLDOWN:.0f}s）",
          last <= MAX_COOLDOWN + 1)
    check("封顶真的到了（否则上面那条是恒真）", last >= MAX_COOLDOWN - 1)
    # 返回值必须就是真正写进去的时长：日志拿它去说人话，对不上就撒谎
    with hb._lock:                                     # noqa: SLF001
        wrote = hb._st["bk"]["until"] - time.time()    # noqa: SLF001
    check(f"返回的秒数 == 实际写入的冷却（{last:.0f} / {wrote:.0f}）",
          abs(wrote - last) < 2)

    # 反向：恢复一次就该从最小的冷却重新开始 —— 抖动型的源不能被一路
    # 按 8 小时冷却（那等于"挂过一次就再也回不来"）。
    hb.note_ok("bk")
    d_again = trip_once(hb, "bk")
    check(f"答话一次后，再挂又回到基础冷却（{d_again:.0f}s）",
          abs(d_again - COOLDOWN[KIND_NET]) < 1,
          "没清 streak 的写法会一直按封顶值计算")

    # 解析类（非网络）也按同样规则退避，只是起点短
    ho = SourceHealth()
    o1 = trip_once(ho, "pr", ValueError("找不到目录容器"))
    check(f"解析类第一次冷却 = 它自己的基础值（{o1:.0f}s）",
          abs(o1 - COOLDOWN[KIND_OTHER]) < 1)

    print("\n—— 落盘：重启之后还记得谁打不通 ——")
    # 为什么需要它：每次 sync / 重启都丢掉内存记忆 → 重启后第一次搜索
    # 又要陪那几个坏源等满一整轮。
    import json as _json
    import tempfile
    tmpdir = Path(tempfile.mkdtemp(prefix="health-test-"))
    hp = tmpdir / "sourcehealth.json"
    h1 = SourceHealth(path=hp)
    trip_once(h1, "dead_src")
    check(f"熔断后文件写出来了（{hp.name}）", hp.exists())
    h1.note_ok("alive_src")          # 先制造一条"不熔断"的记录
    # 模拟重启：新实例、同一个文件
    h2 = SourceHealth(path=hp)
    check("★ 重启后仍然熔断（不至于重启就忘光）", not h2.allows("dead_src"))
    check("没熔断过的源照常放行", h2.allows("alive_src"))
    raw = _json.loads(hp.read_text(encoding="utf-8"))
    check(f"只写还在冷却中的条目（写了 {sorted(raw)}）",
          "dead_src" in raw and "alive_src" not in raw)
    # 过期的旧账必须丢：一份两天前的文件不该让某个源永久回不来
    raw["dead_src"]["until"] = time.time() - 60
    hp.write_text(_json.dumps(raw), encoding="utf-8")
    h3 = SourceHealth(path=hp)
    check("★ 过期（>24 小时）的落盘条目被丢掉，不会永久拉黑",
          h3.allows("dead_src"), str(h3.snapshot()))
    # ⚠ 上面那条单独**没有牙**：读进来但已过期，`allows()` 一样返回 True，
    #   "丢掉了"和"留着一句早过期的 until"看起来完全一样（mutate 抓出来过）。
    #   所以再钉一条：内存里不该留这条账 —— 留着它，下次 `_save()`/诊断面板
    #   都会看到一条凭空的老记录，复盘时误判"这个源刚挂过"。
    check("过期条目没有被塞进内存账本", "dead_src" not in h3.snapshot(),
          str(h3.snapshot()))
    # 不传 path 的实例一次磁盘都不该碰（测试/库使用者不该被偷偷写文件）
    h4b = SourceHealth()
    trip_once(h4b, "nofile")
    check("没给 path 就不写盘（副作用为零）", sorted(p.name for p in tmpdir.iterdir())
          == ["sourcehealth.json"])

    # ------------------------------------------------------------------
    print("\n—— 冷掉的账：冷却到期后，退避还得接着算（2026-10-26）——")
    # 为什么单独一组：`_save`/`_ensure_loaded` 原来只认「仍在冷却中」的条目，
    #   于是冷却**到期那一刻**条目既不落盘、也不再读回 —— `streak` 每次重启
    #   归 1，`BACKOFF`（15m→30m→60m→…）永远涨不上去，退避代码写了却从没生效。
    #   线上证据（三天、同一台机器，每次 ship 之后都倒退）：
    #     10-23 09:06 熔断 15 分钟 → 10-23 10:06 又 15 分钟
    #     10-24 09:04 熔断 30 分钟 → 10-24 09:51 退回 15 分钟
    #     10-25 09:07 熔断 30 分钟 → 10-25 09:50 退回 15 分钟（09:48:26 重启过）
    #   代价：死源每小时被放回名单试 4 次，每次都让一次真实搜索陪它等满 6 秒。
    from app.sourcehealth import FORGET_AFTER

    # (a) 真走一遍落盘/读回：到期 → 存盘 → 重启 → 再挂，必须接着上一轮退避
    hp5 = tmpdir / "cold-roundtrip.json"
    h9 = SourceHealth(path=hp5)
    trip_once(h9, "coldA")                       # 第 1 轮：15 分钟，落盘
    with h9._lock:                               # noqa: SLF001
        h9._st["coldA"]["until"] = time.time() - 1      # noqa: SLF001  时间到了
    h9.allows("coldA")                           # 半开：until 归 0
    h9._save()                                   # 模拟"到点之后有人写了盘"
    raw9 = _json.loads(hp5.read_text(encoding="utf-8"))
    check("★ 冷掉的条目仍然留在盘上（until=0）",
          "coldA" in raw9 and float(raw9["coldA"]["until"]) == 0.0,
          f"盘上只有 {sorted(raw9)} —— 只写「仍在冷却」的版本会把它整条丢掉")
    h10 = SourceHealth(path=hp5)                 # ← 重启
    check("冷掉的条目不许进内存账本（否则诊断面板冒出幽灵记录）",
          "coldA" not in h10.snapshot(), str(h10.snapshot()))
    d9 = h10.note_fail("coldA", TimeoutError("t"))
    check(f"★ 重启后接着上一轮退避（第 2 轮应 {COOLDOWN[KIND_NET] * 2:.0f}s，"
          f"实际 {d9:.0f}s）", abs(d9 - COOLDOWN[KIND_NET] * 2) < 1,
          "只写「仍在冷却」的版本会退回 900s —— 退避等于没写")

    # (b) 手写一份「已经挂到第 3 轮、且冷却早过了」的盘，验半开试探也没丢
    hp6 = tmpdir / "cold-deep.json"
    past = time.time() - 120
    hp6.write_text(_json.dumps({
        "deep": {"fails": 0, "until": past, "kind": KIND_NET, "why": "TimeoutError: t",
                 "streak": 2, "cd": COOLDOWN[KIND_NET] * 2, "at": past},
        "ancient": {"fails": 0, "until": past, "kind": KIND_NET, "why": "x",
                    "streak": 5, "cd": 28800.0,
                    "at": time.time() - FORGET_AFTER - 60},
    }, ensure_ascii=False), encoding="utf-8")
    h11 = SourceHealth(path=hp6)
    check("过期条目照样放行（失败史 ≠ 熔断中）", h11.allows("deep"))
    d10 = h11.note_fail("deep", TimeoutError("t"))
    check(f"★ 一次失败就重新熔断（半开试探没丢）且接着第 3 轮（{d10:.0f}s）",
          abs(d10 - COOLDOWN[KIND_NET] * 4) < 1,
          f"实际 {d10:.0f}s；攒够两次才熔断或退回 900s 都算没接上")
    check("★ 熔断后立刻生效（不是「挂了一次但仍放行」）", not h11.allows("deep"))
    d11 = h11.note_fail("ancient", TimeoutError("t"))
    check("七天前的死因不该决定今天的冷却（彻底忘掉，从头攒）", abs(d11) < 1,
          f"实际 {d11:.0f}s —— 记得太牢会把修好的站按 8 小时拉黑")

    # (c) 反向：一答话就得把失败史一起清掉（抖动型的源不能被一路按封顶）
    hp7 = tmpdir / "cold-flap.json"
    hp7.write_text(_json.dumps({"flap": {
        "fails": 0, "until": past, "kind": KIND_NET, "why": "w",
        "streak": 4, "cd": 7200.0, "at": past}}, ensure_ascii=False),
        encoding="utf-8")
    h12 = SourceHealth(path=hp7)
    h12.allows("flap")
    h12.note_ok("flap")
    check("答话一次后盘上不留残影（失败史已清）",
          "flap" not in _json.loads(hp7.read_text(encoding="utf-8")))
    d12 = trip_once(h12, "flap")
    check(f"★ 答话一次就把失败史清掉（再挂回到 {COOLDOWN[KIND_NET]:.0f}s，不是封顶）",
          abs(d12 - COOLDOWN[KIND_NET]) < 1, f"实际 {d12:.0f}s")


    # 引擎那行日志必须用**真实**时长：原来写死「熔断 15 分钟」，
    # 加了退避之后那句话会开始撒谎（第二次是 30 分钟）。
    eng_src = (ROOT / "app" / "engine.py").read_text(encoding="utf-8")
    check("★ 引擎日志不再从常量里算时长（写死 15 分钟 = 静默撒谎）",
          "HEALTH.cooldown.get" not in eng_src)
    check("引擎用 note_fail 的返回值去写日志",
          "_log_trip(" in eng_src and "cd = HEALTH.note_fail" in eng_src)

    print("\n" + "=" * 62)
    if fail_n == 0:
        print(f"通过 {ok_n} · 失败 0\n✓ 全部通过")
    else:
        print(f"通过 {ok_n} · 失败 {fail_n}\n✗ 有 {fail_n} 项没过")
    print("=" * 62)
    return 1 if fail_n else 0


if __name__ == "__main__":
    raise SystemExit(main())
