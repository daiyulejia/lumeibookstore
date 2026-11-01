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


def main() -> int:
    print("在飞搜索合并 —— 行为自检")
    asyncio.run(case_merge())
    asyncio.run(case_late_join())
    asyncio.run(case_leave())
    case_key()
    asyncio.run(case_crash())
    print(f"\n结果：{ok_n} 通过，{fail_n} 失败")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
