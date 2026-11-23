"""「同一个东西被并发抓 N 遍」的回归测试（全离线，不需要网络）。

背景（2026-11-23 复盘，这是同一条母题的第三次）
------------------------------------------------
缓存只在**跑完之后**才有值。冷缓存下一瞬间来 N 个同一个 key 的请求，
N 个全部 miss、N 个都去干同一件事 —— 缓存挡不住这种重复。三次实证：

  · 2026-11-01：8 秒里 16 个同名搜索各起一轮引擎 → 搜索引擎被我们打成
    「不认识这个词」，并发 8 个时 7/8 拿到 0 条，单独搜是 2 条。
  · 2026-11-22：长书目录要跟 21 页分页，预览与搜索同时打同一个书页 →
    两份完整分页，线上一次 **107 秒**，而日志一直写 `候选=1 成书=1` 全绿。
  · 2026-11-23：`page_of()` 两个线程同时进来 —— 复现脚本实测
    `webfetch.analyze` 被调用 **2 次**；`cached()` 的 producer 更是
    完全没有合并，而它下面挂的正是「整本目录」这种最贵的活（7 个调用点：configured / kunnu8×2 / template_source / wikisource / wyshu / xbqg5200）。

判据一律不看耗时（会随机器负载漂），只看**干活次数**、拿到的是不是同一份、
以及「跑完有没有摘牌」。

⚠ 为什么要有「跑完摘牌」这条**反向**判据：单飞一旦变成缓存，
   「刚学会新站却还返回旧空结果」就会成为常态（2026-10-24 栽过一次）。
   合并的只能是**同一时刻正在跑**的那一份。
"""
from __future__ import annotations

import ast
import logging
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import discovery, utils                            # noqa: E402

_passed = 0
_fail: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    global _passed
    if ok:
        _passed += 1
        print(f"  ✓ {name}")
    else:
        _fail.append(name)
        print("  ✗ " + name + (f"（{detail}）" if detail else ""))
    return ok


# ---------------------------------------------------------------------------
# 观测装置：谁在等、等了几个 —— **计数器**，不是计时
# ---------------------------------------------------------------------------
_WAITS: list[int] = []


class ProbeFlight(utils._Flight):
    """把「有人并入这一轮」这件事记下来（进 `wait` 就是真的在等领跑者）。"""

    __slots__ = ()

    def wait(self, timeout=None):
        _WAITS.append(1)
        return super().wait(timeout)


class patched_flight:
    """换掉 `_Flight`，好数「有几个线程真的并进来了」。"""

    def __enter__(self):
        self._old = utils._Flight
        utils._Flight = ProbeFlight
        return self

    def __exit__(self, *a):
        utils._Flight = self._old
        return False


def wait_until(pred, seconds: float = 3.0) -> bool:
    """等一个**状态**（不是等一段时间）。超时返回 False，让断言自己报红。"""
    end = time.time() + seconds
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.005)
    return pred()


def call_in_thread(fn, seconds: float = 8.0):
    """在**另一个线程**里跑一次（用于"下一次调用"这类跨线程语义）。"""
    box: list = [None]

    def wrap():
        try:
            box[0] = fn()
        except BaseException as e:      # noqa: BLE001
            box[0] = e
    t = threading.Thread(target=wrap, daemon=True)
    t.start()
    t.join(seconds)
    return box[0]


def run_threads(targets: list, seconds: float = 8.0) -> tuple[list, int]:
    """并发跑几个函数，收集返回值。返回 (返回值, 卡住的线程数)。

    卡住的线程要单独报出来 —— 否则「挂死」会表现成 `None`，
    看起来像"返回了空值"，那是另一种沉默。
    """
    out: list = [None] * len(targets)

    def wrap(i, fn):
        try:
            out[i] = fn()
        except BaseException as e:      # noqa: BLE001 — 异常本身也是结果
            out[i] = e

    ths = [threading.Thread(target=wrap, args=(i, fn), daemon=True)
           for i, fn in enumerate(targets)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(seconds)
    return out, sum(1 for t in ths if t.is_alive())


# ---------------------------------------------------------------------------
def main() -> int:
    # ======================================================================
    print("\nA. `cached()`：冷缓存下的并发未命中只许跑一遍 producer")
    # ======================================================================
    utils.cache_clear()
    calls: list = []

    def slow_producer():
        calls.append(1)
        # 等到真的有人并进来再返回 —— 这不是计时，是**同步点**：
        # 只有这样才能确定「第二个线程确实赶上了这一轮」，
        # 而不是靠"睡一会儿它应该到了"（那条 2026-11-15 栽过）。
        wait_until(lambda: len(_WAITS) >= 1, 2.0)
        return {"v": 42}

    with patched_flight():
        _WAITS.clear()
        res, stuck = run_threads([lambda: utils.cached("k1", 60, slow_producer),
                                  lambda: utils.cached("k1", 60, slow_producer)])
    check("两个线程同 key 并发未命中 → producer 只跑 1 遍",
          len(calls) == 1 and not stuck, f"跑了 {len(calls)} 遍，卡住 {stuck}")
    check("两边拿到的是同一份结果（不是各解析一份）",
          res[0] is res[1] and isinstance(res[0], dict) and res[0].get("v") == 42,
          repr(res))

    # —— 反向：跑完必须摘牌，下一次调用要重新干（不是缓存）——
    # ⚠ 这条必须打在 `single_flight` 自己身上：`cached()` 本来就是缓存，
    #   拿它验"跑完还跑不跑"会把两件事混成一件（第一版就写错了，当场报红）。
    # ⚠ 必须**换一个线程**再调：同一个线程重入会被当成"递归重入"而直接自己跑
    #   （那是防死锁的正确行为），拿它验"摘没摘牌"会恒绿 —— 第一次就写错了。
    calls.clear()
    _ = call_in_thread(lambda: utils.single_flight(
        "k_sf", lambda: calls.append(9) or {"v": 7}))
    _ = call_in_thread(lambda: utils.single_flight(
        "k_sf", lambda: calls.append(9) or {"v": 8}))
    check("⚠ 反向：单飞跑完就摘牌，同 key 下一次**必须重跑**（它不是缓存）",
          len(calls) == 2, f"跑了 {len(calls)} 遍")

    # —— 命中时不许调 producer ——
    calls.clear()
    _ = utils.cached("k1", 60, lambda: calls.append(3) or {"v": 8})
    check("TTL 内命中不调 producer",
          len(calls) == 0, f"跑了 {len(calls)} 遍")

    # —— TTL 从**完成时刻**算，不是开始时刻 ——
    # 旧实现记的是开始时刻：producer 跑 0.5 秒、TTL 0.3 秒时，
    # 结果刚放进去就已经"过期"，同一本书的第二次预览又从头抓一遍。
    # 长书正是这种形状（一次解析 5~25 秒），所以这不是理论问题。
    utils.cache_clear()
    n_ttl: list = []

    def slowp():
        n_ttl.append(1)
        time.sleep(0.5)               # 桩自己的固定睡眠，不是机器耗时
        return {"t": 1}

    _ = utils.cached("k_ttl", 0.3, slowp)
    _ = utils.cached("k_ttl", 0.3, slowp)
    check("TTL 从**完成时刻**算（producer 比 TTL 慢时，紧接着那次仍算命中）",
          len(n_ttl) == 1, f"跑了 {len(n_ttl)} 遍")

    # ======================================================================
    print("\nA2. 领跑者失败：等着的人自己重跑，不集体继承失败")
    # ======================================================================
    utils.cache_clear()
    calls2: list = []
    started = threading.Event()

    def first():
        def p():
            started.set()
            # 必须等**真有人并进来**才抛：不然领跑者瞬间失败、还没来得及摘牌，
            # 第二路自然会自己跑一遍 —— 突变"失败不唤醒"就永远抓不到。
            wait_until(lambda: len(_WAITS) >= 1, 2.0)
            raise RuntimeError("第一次抖了一下")
        return utils.cached("k2", 60, p)

    def flaky():
        calls2.append(1)
        return {"ok": True}

    def second():
        wait_until(started.is_set, 2.0)     # 状态，不是时长
        time.sleep(0.05)                   # 让「等领跑者」这条路真的走一次
        return utils.cached("k2", 60, flaky)

    with patched_flight():
        _WAITS.clear()
        r, stuck2 = run_threads([first, second])
    check("领跑者抛错 → 等着的那一路自己重跑并拿到结果（不继承异常）",
          not stuck2 and isinstance(r[1], dict) and r[1].get("ok") is True,
          f"stuck={stuck2} r={r}")
    check("……而且只多跑一遍（不是所有人都重来）",
          len(calls2) <= 1, f"producer 跑了 {len(calls2)} 遍")

    # ======================================================================
    print("\nB. `page_of()`：同一个书页并发 → 只解析一次；两种预算不许合并")
    # ======================================================================
    seen: list = []
    wait_peer = {"on": True}

    def fake_analyze(url, *, log=None, full=False):
        seen.append((url, full))
        if wait_peer["on"]:
            wait_until(lambda: len(_WAITS) >= 1, 2.0)
        # 目录「完整」—— 否则 `page_of(full=True)` 会按 `toc_pending`
        # 主动重解析，缓存那条断言就测不到了。
        return {"kind": "toc", "url": url, "final_url": url, "toc": [],
                "toc_pending": False, "quality": 1.0}

    old_analyze = discovery.webfetch.analyze
    discovery.webfetch.analyze = fake_analyze
    try:
        discovery.forget_pages()
        U = "http://fl.example/book/9/"
        with patched_flight():
            _WAITS.clear()
            r, stuck3 = run_threads([lambda: discovery.page_of(U, full=True),
                                     lambda: discovery.page_of(U, full=True)])
        check("同 URL + 同模式并发 → `webfetch.analyze` 只调 1 次",
              len(seen) == 1 and not stuck3, f"调了 {len(seen)} 次：{seen}")
        check("两边拿到同一份目录对象",
              isinstance(r[0], dict) and r[0] is r[1], repr(r))

        # —— 反向：`full` 不同不许合并 ——
        # 合并了有两种坏法：下载拿到 3 页的残目录 / 探测陪着跑 25 秒。
        # ⚠ 必须用**同一个地址**、只换 `full`，否则这条测的是"不同 URL 不合并"
        #   （永远成立，等于空转）。
        seen.clear()
        discovery.forget_pages()
        # 这里**同样**要有同步点：没有它，两路可能天然错开（第一路早跑完了），
        # 突变"key 里去掉 full"就照绿不误 —— 反证当场抓到了这一点。
        wait_peer["on"] = True
        U2 = "http://fl.example/book/10/"
        # 用 `force=True` 绕开缓存读 —— 不然第二次直接命中缓存，
        # 测的就成了"缓存命不命中"，而不是"单飞的 key 里有没有 full"。
        r2, stuck4 = run_threads([lambda: discovery.page_of(U2, force=True, full=False),
                                  lambda: discovery.page_of(U2, force=True, full=True)])
        check("⚠ 反向：同一地址 `full=False` 与 `full=True` 各解析一次（预算不同不许合并）",
              len(seen) == 2 and sorted(f for _u, f in seen) == [False, True]
              and not stuck4,
              f"{seen}")

        # —— 缓存仍然有效：第二次调用不再解析 ——
        # （上面 `forget_pages()` 把缓存清过了，所以先让第一次把缓存填上）
        seen.clear()
        _ = discovery.page_of(U, full=True)
        seen.clear()
        _ = discovery.page_of(U, full=True)
        check("解析结果进缓存，同一地址第二次不再解析",
              len(seen) == 0, f"又解析了 {len(seen)} 次")
    finally:
        discovery.webfetch.analyze = old_analyze
        discovery.forget_pages()

    # ======================================================================
    print("\nC. 不许把请求挂死：领跑者卡住 / 同线程重入")
    # ======================================================================
    utils.cache_clear()
    blocked = threading.Event()
    calls3: list = []

    def stuck_producer():
        calls3.append(1)
        blocked.wait(3.0)          # 领跑者卡住，直到测试放行
        return {"slow": True}

    t_a = threading.Thread(
        target=lambda: utils.single_flight("k3", stuck_producer, wait=0.08),
        daemon=True)
    t_a.start()
    wait_until(lambda: len(calls3) == 1, 2.0)      # 领跑者已经开跑
    got = utils.single_flight("k3", lambda: {"mine": True}, wait=0.08)
    blocked.set()
    t_a.join(3.0)
    check("领跑者超时没回来 → 等待的人自己跑并拿到结果（不无限挂住）",
          isinstance(got, dict) and got.get("mine") is True, repr(got))
    check("……且如实记账（`flight_stats['timeout']` 有数）",
          utils.flight_stats["timeout"] >= 1, str(utils.flight_stats))

    # 同线程重入同一个 key：不许自己等自己（死锁）
    utils.cache_clear()
    holder: list = []

    def outer():
        def inner_prod():
            return "inner"

        return utils.single_flight("k4", lambda: utils.single_flight("k4", inner_prod))

    th = threading.Thread(target=lambda: holder.append(outer()), daemon=True)
    th.start()
    th.join(2.0)
    check("同一线程重入同一个 key 不死锁（直接自己跑）",
          holder == ["inner"], f"卡住或返回 {holder}")

    # ======================================================================
    print("\nD. 记账与日志：合并这件事必须看得见")
    # ======================================================================
    utils.cache_clear()
    utils.flight_stats.update({"started": 0, "joined": 0, "timeout": 0})
    recs: list[logging.LogRecord] = []

    class Grab(logging.Handler):
        def emit(self, record):
            recs.append(record)

    lg = logging.getLogger("novel.utils")
    old_level = lg.level
    h = Grab()
    lg.addHandler(h)
    lg.setLevel(logging.INFO)
    try:
        calls4: list = []

        def prod4():
            calls4.append(1)
            wait_until(lambda: len(_WAITS) >= 1, 2.0)
            return {"v": 1}

        with patched_flight():
            _WAITS.clear()
            run_threads([lambda: utils.single_flight("k5", prod4),
                         lambda: utils.single_flight("k5", prod4)])
    finally:
        lg.removeHandler(h)
        lg.setLevel(old_level)

    check("合并发生时会记一笔（`flight_stats['joined']`）",
          utils.flight_stats["joined"] >= 1 and len(calls4) == 1,
          f"{utils.flight_stats} calls={len(calls4)}")
    check("合并发生时会打一行日志、带 key（复盘能看到「这是同一件事」）",
          any("合并" in r.getMessage() for r in recs),
          f"{[r.getMessage()[:40] for r in recs]}")

    # ======================================================================
    print("\nE. 结构闸门：这两条热路径必须走单飞（以后新加的别漏）")
    # ======================================================================
    def func_calls_single_flight(path: Path, fn: str) -> tuple[bool, bool]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = False
        ok = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn:
                found = True
                for sub in ast.walk(node):
                    if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                            and sub.func.id == "single_flight"):
                        ok = True
        return found, ok

    found1, ok1 = func_calls_single_flight(ROOT / "app" / "utils.py", "cached")
    found2, ok2 = func_calls_single_flight(ROOT / "app" / "discovery.py", "page_of")
    # 扫描器先自证「确实扫到了那两个函数」 —— 否则下面两条恒真
    check("（自证）扫描器确实找到 `cached` / `page_of` 两个函数体",
          found1 and found2, f"cached={found1} page_of={found2}")
    check("`cached()` 走单飞（7 个调用点共用这一处）", ok1)
    check("`page_of()` 走单飞", ok2)

    print("\n" + "=" * 62)
    print(f"通过 {_passed} · 失败 {len(_fail)}")
    for f in _fail:
        print("  ✗ " + f)
    print("=" * 62)
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
