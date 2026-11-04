# -*- coding: utf-8 -*-
"""同一个查询的**在飞**请求合并（app/searchflight.py）的行为测试。

为什么需要它
------------
2026-10-31 23:14 线上：用户连点搜索，8 秒里进来 **16 个一模一样**的请求。
当时每个请求都自己起一轮引擎 —— 各自去百度/必应、各自扇出 7 个来源站。
后果是**自伤**，而且三层都不报错：

  · 搜索引擎返回**别的页面**（实测候选是「江苏教育考试院」「3D 漫画」
    「educoder 编程学习」，跟书名毫无关系）→ 8 轮里 7 轮 `候选=0`，
    而单独搜同一本书是 `候选=2 可读=2`。受控实验（8 并发）复现 7/8 为空。
  · 4 个来源站被同一关键词打限速 → 模板被判死，可搜源池 23→19（永久）。

所以合并要做对三件事，下面每一条都有断言：
  1. N 个并发请求只跑**一轮**引擎；
  2. **一个请求走掉不等于全停**（否则先断的那个会把别人一起弄死）；
  3. **最后**一个走掉才收手（否则连点 16 次会留下 16 个跑完没人要的轮次）。

⚠ 别用耗时当判据（会随机器负载漂）。这里只数"引擎被调了几次"、
  "stop 置没置位"、"收到几个 done" —— 全是机制布尔量/计数。

用法：python tools/test_search_flight.py
"""
from __future__ import annotations

import asyncio
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.searchflight import Flight, FlightBook  # noqa: E402

ok_n = 0
fail_n = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global ok_n, fail_n
    if cond:
        ok_n += 1
        print(f"  ✓ {name}")
    else:
        fail_n += 1
        print(f"  ✗ {name} {extra}")


async def drain(sub, timeout: float = 8.0) -> list[dict]:
    out: list[dict] = []
    while True:
        ev = await asyncio.wait_for(sub.queue.get(), timeout)
        out.append(ev)
        if ev.get("type") in ("done", "error"):
            return out


# ---------------------------------------------------------------------------
# ① 合并：N 个并发请求只跑一轮
# ---------------------------------------------------------------------------
async def case_merge() -> None:
    print("\n【① 8 个相同请求 = 1 轮引擎】")
    calls: list[int] = []
    go = threading.Event()          # 让 runner 卡住，保证 8 次 ensure_started 都落在"启动前"

    def runner(push, should_stop):
        calls.append(1)
        go.wait(5)
        for i in range(3):
            push({"type": "item", "data": {"i": i}})
            time.sleep(0.02)
        push({"type": "done", "count": 3})

    book = FlightBook()
    key = book.key_of("三体", None, True, True, True)
    loop = asyncio.get_running_loop()
    subs = []
    flights = set()
    for _ in range(8):
        f, _fresh = book.acquire(key, lambda: Flight(key, runner))
        flights.add(id(f))
        subs.append((f, f.subscribe(loop)))
    # 真实路径上**每个请求的生成器**都会调一次 ensure_started。
    # 所以这里也必须每个都调 —— 只调一次的话，「启动不幂等」这个 bug
    # 在测试里根本不会发生（反证当场报"存活"）。
    fired = [f.ensure_started(loop) for f, _s in subs]
    check("8 次「启动」只有一次真的起了引擎",
          sum(1 for x in fired if x) == 1, f"fired={fired}")
    go.set()

    got = [await drain(s) for _f, s in subs]
    check("8 个并发请求只起了一轮引擎", len(calls) == 1, f"calls={len(calls)}")
    check("8 个请求挂在同一个 flight 上", len(flights) == 1, f"flights={len(flights)}")
    check("8 个订阅者都收到 done",
          all(g[-1].get("type") == "done" for g in got),
          f"末事件={[g[-1].get('type') for g in got]}")
    check("每个人都拿全了过程事件（各 4 条）",
          all(len(g) == 4 for g in got), f"条数={[len(g) for g in got]}")

    # 跑完要从登记簿摘掉，否则下一个请求会挂到一个已经结束的轮次上
    await asyncio.sleep(0.05)
    check("跑完即从登记簿摘除", len(book) == 0, f"len={len(book)}")


# ---------------------------------------------------------------------------
# ② 迟到的订阅者：这一轮已经结束了才来
# ---------------------------------------------------------------------------
async def case_late_join() -> None:
    print("\n【② 迟到的订阅者要能拿到结果】")

    def runner(push, should_stop):
        push({"type": "item", "data": {"i": 0}})
        push({"type": "done", "count": 1, "books": [{"title": "三体"}]})

    book = FlightBook()
    key = book.key_of("三体", None, True, True, True)
    loop = asyncio.get_running_loop()
    f, _ = book.acquire(key, lambda: Flight(key, runner))
    first = f.subscribe(loop)
    f.ensure_started(loop)
    await drain(first)
    await asyncio.sleep(0.05)

    # 「迟到」= 已经订到这一轮、但开始读的时候它早跑完了。
    # （跑完之后 `acquire` 会另起新一轮 —— 那是对的，不是迟到。
    #   所以这里必须直接订**那个已结束的 flight**。）
    sub = f.subscribe(loop)
    got = await drain(sub)
    check("迟到者能拿到 done（不是干等到超时）",
          got[-1].get("type") == "done", f"末事件={got[-1].get('type')}")
    check("迟到者拿到的结果里有书",
          bool(got[-1].get("books")), f"books={got[-1].get('books')}")


# ---------------------------------------------------------------------------
# ③④ 退订语义：一个走 ≠ 全停；全走才停
# ---------------------------------------------------------------------------
async def case_leave() -> None:
    print("\n【③ 一个请求走掉不许把别人弄死 / ④ 全走才收手】")
    stop_seen = threading.Event()
    started = threading.Event()

    def runner(push, should_stop):
        started.set()
        for _ in range(600):                 # 最多等 6s
            if should_stop():
                stop_seen.set()
                break
            time.sleep(0.01)
        push({"type": "done", "count": 0})

    book = FlightBook()
    key = book.key_of("围城", None, True, True, True)
    loop = asyncio.get_running_loop()
    f, _ = book.acquire(key, lambda: Flight(key, runner))
    a = f.subscribe(loop)
    b = f.subscribe(loop)
    f.ensure_started(loop)
    await asyncio.wait_for(asyncio.to_thread(started.wait, 3), 5)

    f.leave(a)
    await asyncio.sleep(0.1)
    check("还剩一个订阅者时引擎**不**收手", not stop_seen.is_set())
    check("flight 还算「有人在听」", f.subscribers == 1, f"subs={f.subscribers}")

    f.leave(b)
    ok = await asyncio.wait_for(asyncio.to_thread(stop_seen.wait, 3), 5)
    check("最后一个订阅者走掉 → 引擎收手", bool(ok))
    check("收手后这一轮不再接受新订阅", not f.accepts())


# ---------------------------------------------------------------------------
# ⑤ key：参数不同就不许合并
# ---------------------------------------------------------------------------
def case_key() -> None:
    print("\n【⑤ 合并粒度：改了什么就必须分开】")
    book = FlightBook()
    base = book.key_of("三体", None, True, True, True)
    check("同一组参数 → 同 key", book.key_of("三体", None, True, True, True) == base)
    check("指定来源不同 → 不同 key",
          book.key_of("三体", ["a"], True, True, True) != base)
    check("关掉联网 → 不同 key",
          book.key_of("三体", None, True, True, False) != base)
    check("关掉探测 → 不同 key",
          book.key_of("三体", None, True, False, True) != base)
    check("来源顺序不影响 key",
          book.key_of("三体", ["b", "a"], True, True, True)
          == book.key_of("三体", ["a", "b"], True, True, True))
    check("书名前后的空格不影响 key",
          book.key_of(" 三体 ", None, True, True, True) == base)

    class _F:
        pass

    f1, fresh1 = book.acquire(base, _F)
    f1.accepts = lambda: True           # type: ignore[method-assign]
    f2, fresh2 = book.acquire(base, _F)
    check("同一个 key 复用同一个对象", f1 is f2 and fresh1 and not fresh2)


# ---------------------------------------------------------------------------
# ⑥ 引擎炸了：订阅者必须收到 error，不能挂死
# ---------------------------------------------------------------------------
async def case_crash() -> None:
    print("\n【⑥ 引擎抛异常时不许让请求挂住】")

    def runner(push, should_stop):
        raise RuntimeError("故意炸")

    book = FlightBook()
    key = book.key_of("活着", None, True, True, True)
    loop = asyncio.get_running_loop()
    f, _ = book.acquire(key, lambda: Flight(key, runner))
    sub = f.subscribe(loop)
    f.ensure_started(loop)
    got = await drain(sub)
    check("引擎抛异常 → 订阅者收到 error",
          got[-1].get("type") == "error", f"末事件={got[-1].get('type')}")


# ---------------------------------------------------------------------------
# ⑦ 弃轮不许被后来者继承（acquire 与 subscribe 之间的那道缝）
# ---------------------------------------------------------------------------
async def case_takeover() -> None:
    print("\n【⑦ 最后一个订阅者走掉的轮次，新请求不许挂上去】")
    calls: list[int] = []
    gates: list[threading.Event] = []

    def runner(push, should_stop):
        g = threading.Event()
        gates.append(g)
        calls.append(1)
        # 真实引擎就是这样：在扇出里循环等源，每个窗口判一次「还有没有人听」。
        while not should_stop():
            if g.wait(0.01):
                break
        if should_stop():
            push({"type": "done", "count": 0, "aborted": True})
        else:
            push({"type": "done", "count": 2, "aborted": False})

    book = FlightBook()
    key = book.key_of("你腿真美", None, True, True, True)
    loop = asyncio.get_running_loop()
    f1, _ = book.acquire(key, lambda: Flight(key, runner))
    a = f1.subscribe(loop)
    f1.ensure_started(loop)
    await _wait_for(lambda: len(calls) == 1, 3.0)

    # ---- 线上 2026-11-02 01:25 的真实时序，一步不差地重放 ----
    # 新请求（前端点「就搜」）先 acquire —— 此刻这一轮还活着，于是拿到同一个。
    f2, _ = book.acquire(key, lambda: Flight(key, runner))
    check("复现线上时序：缝里拿到的是同一轮", f2 is f1)
    # 紧接着老请求断开，这一轮成了弃轮。
    f1.leave(a)

    # ⚠ 这里就是 bug 本身：旧代码会返回一个能用的 sub（挂到尸体上），
    #   于是新请求拿到 done count=0 —— 用户看到"没找到这本书"。
    check("弃轮拒绝新订阅（返回 None，而不是挂上去）",
          f2.subscribe(loop) is None)

    # 走真实接线：登记簿原子地给一轮，必须是**新的**一轮。
    f3, sub3 = book.subscribe(key, lambda: Flight(key, runner), loop)
    check("原子接口换了一轮新的", f3 is not f1 and f3 is not f2)
    f3.ensure_started(loop)
    await _wait_for(lambda: len(gates) == 2, 3.0)
    if len(gates) >= 2:
        gates[1].set()
    got = await drain(sub3)
    check("新请求拿到的是真结果，不是 0 条",
          got[-1].get("count") == 2, f"末事件={got[-1]}")
    check("新请求没被误标成 aborted", got[-1].get("aborted") is False,
          f"末事件={got[-1]}")
    check("没有因此多跑一轮（仍是 2 轮：弃轮 + 新轮）",
          len(calls) == 2, f"calls={len(calls)}")


# ---------------------------------------------------------------------------
# ⑧ 已经跑完的一轮绝不许被复用（哪怕它还没从登记簿上摘掉）
# ---------------------------------------------------------------------------
async def case_finished() -> None:
    """`finish()` 与 `release()` 之间有一道**真实存在**（但很短）的窗口：
    先置 `_finished`，之后才回调登记簿摘牌。这道窗口里新请求如果被塞一份
    「上一轮的回放」，用户就会拿到**别人的**（可能是空的）结果 ——
    这正是 `searchflight.py` 模块注释里明令禁止的"复用上一轮"。

    这里把摘牌挡掉来把窗口固定住（线上它只是几微秒，靠运气撞）。
    """
    print("\n【⑧ 已结束的一轮只许回放，不许当成新一轮发出去】")

    def runner(push, should_stop):
        push({"type": "done", "count": 9})

    book = FlightBook()
    key = book.key_of("活着", None, True, True, True)
    loop = asyncio.get_running_loop()
    f, _ = book.acquire(key, lambda: Flight(key, runner))
    f._on_finish = lambda: None      # 固定住「跑完但还没摘牌」那道窗口
    a = f.subscribe(loop)
    f.ensure_started(loop)
    await drain(a)
    # ⚠ 收到 done ≠ 这一轮已经「结束」：`push(done)` 在前、`finish()` 在 runner
    #   线程退栈时才跑。不等这一步会偶发红（我第一版就是这样，单独跑绿、
    #   ship 里 red —— 典型的"判据自己有时序问题"）。
    await _wait_for(lambda: not f.accepts(), 3.0)
    check("前提：这一轮跑完了但还挂在登记簿上", len(book) == 1 and not f.accepts(),
          f"len={len(book)} accepts={f.accepts()}")

    f2, sub2 = book.subscribe(key, lambda: Flight(key, runner), loop)
    check("新请求拿到的是**新的一轮**，不是上一轮的回放", f2 is not f,
          f"same={f2 is f}")


# ---------------------------------------------------------------------------
# ⑨ 接线：请求路径必须走原子接口
# ---------------------------------------------------------------------------
def case_wiring() -> None:
    print("\n【⑨ 接线：别再拆成 acquire + subscribe】")
    src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    check("搜索接口用原子的 FlightBook.subscribe",
          "_FLIGHTS.subscribe(" in src)
    check("不再有 _FLIGHTS.acquire(（那道缝就是它开出来的）",
          "_FLIGHTS.acquire(" not in src)

    js = (ROOT / "app" / "static" / "js" / "discover.js").read_text(encoding="utf-8")
    n = js.count("M.searching && M.confirmed === d.keyword")
    check("「就搜」与确认框都不会掐掉正在跑的同名搜索（两处守卫）",
          n >= 2, f"命中 {n} 处")


async def _wait_for(cond, timeout: float) -> bool:
    """等一个**机制**成立（不是等一段时间）。超时只是为了别把测试挂死。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        await asyncio.sleep(0.01)
    return bool(cond())


def main() -> int:
    print("在飞搜索合并 —— 行为自检")
    asyncio.run(case_merge())
    asyncio.run(case_late_join())
    asyncio.run(case_leave())
    case_key()
    asyncio.run(case_crash())
    asyncio.run(case_takeover())
    asyncio.run(case_finished())
    case_wiring()
    print(f"\n结果：{ok_n} 通过，{fail_n} 失败")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
