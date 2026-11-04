# -*- coding: utf-8 -*-
"""一次引擎运行 = 一次「在飞」的搜索，可以被多个 HTTP 请求共用。

为什么需要它（线上实证，2026-10-31 23:14）
----------------------------------------
那天 8 秒里来了 **16 个完全一样**的搜索请求（同一个书名、同样参数）。
当时每个请求都自己起一轮引擎：各自去百度/必应、各自扇出 7 个源。
结果是**自伤**，而且每一层都不报错：

  · 搜索引擎被同一个查询打了十几次 → 返回的是**别的页面**
    （实测拿回来的候选是「江苏教育考试院」「3D 漫画」「educoder 编程学习」，
    跟《情欲超市全集》毫无关系），核实 9~10 个候选、全部「不是目录」，
    于是这一轮的 `候选=0`。**单独搜同一本书是 `候选=2 可读=2`。**
  · 来源站被同一个关键词打了十几次 → 返回限速页 / 空页 →
    被算成「连续 3 次打开的不是搜索页」→ **模板被判死**
    （实测这一晚 `www.itiandixs.com` / `m.kudushu.org` /
    `www.xuanhuanbiquge.com` / `www.xizids.com` 四个站的模板当场被作废，
    可搜源池 23→19）。这笔损失是**永久的**，且算在别的用户头上。

重复请求本身没有错（用户连点、前端重试、脚本探测都会产生），
错在**每次重复都从零开始干一遍**。所以这里把「同一个查询的在飞运行」
收成一份：第一个请求触发，后面同 key 的请求挂上去当订阅者，事件广播给所有人。

三条硬约束（都是踩过坑的地方）
------------------------------
1. **单人走不等于整轮停**。原来 `alive` 是「这个请求还在不在」，
   现在必须是「**还有没有一个订阅者在听**」—— 否则第一个请求断开
   会把后来挂上来的请求一起弄死。
2. **只有在有人真的开始读的时候才启动引擎**。生成器是惰性的，
   客户端可能在第一个 yield 之前就断了；那时要是引擎已经在跑，
   就等于白烧一轮（见 `app/main.py::search` 里那段长注释）。
   所以启动由第一个 `subscribe()` 之后的 `ensure_started()` 触发。
3. **迟到的订阅者要「补课」**。它进来时前面的事件已经发过了，
   而前端是靠 `done` 里的 books 出结果的 —— 只补 `done` 也能活，
   但会把「正在搜」的过程画面吞掉，所以直接把已发生的事件队列拷一份。

⚠ 这不是缓存。合并的只是**同一时刻**在飞的那一轮，跑完就散。
   上一轮的结果（尤其是「本地没有、联网也没找到」这种）**绝不复用** ——
   那会让「刚学会新站却还返回旧空结果」变成常态，和 2026-10-24
   「有缓存就不再算」是同一个坑。
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

# 订阅者队列里只认这两种事件是「这一轮的结尾」
_TERMINAL = ("done", "error")


class _Sub:
    """一个订阅者 = 一个 HTTP 请求的收件箱。"""

    __slots__ = ("queue", "loop", "alive")

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.loop = loop
        self.alive = threading.Event()
        self.alive.set()


class Flight:
    """一轮在飞的搜索。

    `runner(push, should_stop)` 在调用方给的线程里跑，负责真正干活；
    它只需要往 `push` 里塞事件（`item`/`verified`/`step`/`done`/`error`）。
    """

    __slots__ = ("key", "_runner", "_lock", "_subs", "_events", "_stop",
                 "_finished", "_submitted", "_terminal", "_abandoned", "joined",
                 "req_id", "_on_finish")

    def __init__(self, key: tuple, runner: Callable[[Callable, Callable], None],
                 req_id: str = "----"):
        self.key = key
        self._runner = runner
        self._lock = threading.Lock()
        self._subs: list[_Sub] = []
        self._events: list[dict] = []
        self._stop = threading.Event()
        self._finished = False
        self._submitted = False
        self._terminal = False
        self._abandoned = False
        self.joined = 0
        self.req_id = req_id
        # 收尾后的回调（登记簿用它把自己摘掉）。默认没有 ——
        # 单测里可以脱开登记簿单独跑一轮 flight。
        self._on_finish: Callable[[], None] | None = None

    # ------------------------------------------------------------------
    # 对外状态
    # ------------------------------------------------------------------
    def accepts(self) -> bool:
        """还能不能挂上来。

        `abandoned` 必须一起判：最后一个订阅者走了之后，这一轮已经在下线路上，
        新请求挂上去只会拿到半截结果 —— 那种「看着像搜到了、其实是残缺的」
        比直接重跑一轮贵得多。
        """
        with self._lock:
            return not self._finished and not self._abandoned

    @property
    def subscribers(self) -> int:
        with self._lock:
            return len(self._subs)

    # ------------------------------------------------------------------
    # 订阅 / 退订
    # ------------------------------------------------------------------
    def subscribe(self, loop: asyncio.AbstractEventLoop) -> _Sub | None:
        """挂上来。已经发生过的事件会先补一遍（迟到的订阅者也能看到过程）。

        返回 `None` 表示**这一轮已经被放弃了**（最后一个订阅者走掉了），
        调用方必须换一轮新的 —— 不许挂上去。

        ⚠ 这一条是 2026-11-02 01:25 线上实证补的，`accepts()` 挡不住它：
          `acquire()` 在请求处理函数里调、`subscribe()` 要等生成器第一次
          `__anext__()` 才跑，中间隔着"把响应头发出去"这一跳。实测就是这道缝：
            · 新请求的 `acquire` 先过（此刻这一轮还活着，于是拿到同一个 flight）；
            · 老请求这时断开 → `leave` 把 `_stop` 置上、这一轮成了弃轮；
            · 新请求这才 `subscribe` —— 挂到一具尸体上，引擎下一次判
              `should_stop()` 立刻收手，用户等了 1.5 秒拿到 `候选=0`。
          日志上的样子极具误导性：`合并=2`（说明确实有两个订阅者）配
          `aborted=True`，看起来像"客户端自己走了"，其实是**我们自己
          把新请求交给了已经死掉的那一轮**。
        """
        sub = _Sub(loop)
        with self._lock:
            if self._abandoned:
                return None
            self.joined += 1
            for ev in self._events:
                sub.queue.put_nowait(ev)
            if self._finished:
                # 这一轮已经结束了：只把历史事件当回放，不再占订阅位。
                sub.alive.clear()
            else:
                self._subs.append(sub)
        return sub

    def leave(self, sub: _Sub) -> None:
        """一个请求走了（读完 / 断开 / 抛错都走这里）。"""
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)
            sub.alive.clear()
            if not self._subs and not self._finished:
                # 没人在听了 —— 告诉引擎可以收手了。
                # ⚠ 只在**一个订阅者都不剩**时才算，单个请求断开不算。
                self._abandoned = True
                self._stop.set()

    # ------------------------------------------------------------------
    # 广播
    # ------------------------------------------------------------------
    def push(self, obj: dict) -> None:
        """把一个事件发给所有还活着的订阅者（引擎线程里调）。"""
        if obj.get("type") in _TERMINAL:
            self._terminal = True
        with self._lock:
            if not self._finished:
                self._events.append(obj)
            live = [s for s in self._subs if s.alive.is_set()]
            # 读端已经走了的订阅者顺手清掉 —— 否则一晚上下来 _subs 只增不减。
            self._subs = [s for s in self._subs if s.alive.is_set()]
        for s in live:
            try:
                s.loop.call_soon_threadsafe(s.queue.put_nowait, obj)
            except RuntimeError:
                # 事件循环已经关了（请求早结束）—— 静默丢弃，别把引擎线程炸掉。
                s.alive.clear()

    # ------------------------------------------------------------------
    # 启动 / 收尾
    # ------------------------------------------------------------------
    def ensure_started(self, loop: asyncio.AbstractEventLoop) -> bool:
        """由第一个真正开始读的请求（或任一个订阅者）触发，幂等。

        返回 True 表示「这次是我启动的」。多个请求同时进来时只有一个能拿到，
        所以引擎不会因为合并而被启动两次。
        """
        with self._lock:
            if self._submitted or self._finished:
                return False
            self._submitted = True
        loop.run_in_executor(None, self._run)
        return True

    def _run(self) -> None:
        try:
            self._runner(self.push, self._stop.is_set)
        except Exception:  # noqa: BLE001
            logger.exception("搜索线程异常（已广播 error 给订阅者）")
        finally:
            if not self._terminal:
                # 引擎没来得及说「结束」就没了 —— 订阅者会永远等下去，
                # 所以这里必须替它说一句，宁可报错也不能挂住请求。
                self.push({"type": "error", "msg": "搜索线程异常结束"})
            self.finish()

    def finish(self) -> None:
        with self._lock:
            self._finished = True
            self._subs = []
            cb = self._on_finish
        if cb is not None:
            # 放在锁外调：登记簿的 release 自己会拿它自己的锁，
            # 两把锁嵌套迟早会撞上，而这里没有任何理由嵌套。
            try:
                cb()
            except Exception:  # noqa: BLE001
                logger.exception("flight 收尾回调异常（已忽略）")


class FlightBook:
    """在飞搜索的登记簿：同 key 复用，跑完即删。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[tuple, Flight] = {}

    @staticmethod
    def key_of(kw: str, only: Iterable[str] | None,
               sample: bool, probe: bool, discover: bool) -> tuple:
        """合并的粒度。

        ⚠ 必须把 `only` / `sample` / `probe` / `discover` 全算进去：
          它们改的是**这一轮要干什么**，不是同一件事的两个叫法。
          只看书名就合并的话，"指定来源=1" 的探针会和"全部来源"的用户搜索
          共用一轮，谁先来谁是爹 —— 返回的结果与用户看到的筛选条件对不上。
        """
        return (kw.strip(),
                tuple(sorted(only or ())),
                bool(sample), bool(probe), bool(discover))

    def acquire(self, key: tuple, factory: Callable[[], Flight]) -> tuple[Flight, bool]:
        """拿一个可挂的 flight；没有就现建一个。返回 (flight, 是否新建)。"""
        with self._lock:
            cur = self._items.get(key)
            if cur is not None and cur.accepts():
                return cur, False
            if cur is not None:
                # 旧的已经结束/被放弃，但还没从簿上摘掉 —— 顺手清掉。
                self._items.pop(key, None)
            f = factory()
            self._items[key] = f
            f._on_finish = lambda: self.release(key, f)
            return f, True

    def release(self, key: tuple, flight: Flight) -> None:
        with self._lock:
            if self._items.get(key) is flight:
                self._items.pop(key, None)

    def subscribe(self, key: tuple, factory: Callable[[], Flight],
                  loop: asyncio.AbstractEventLoop) -> tuple[Flight, _Sub]:
        """**原子地**「拿一轮 + 挂上去」。请求路径只该用这个，别用 acquire。

        为什么不能 `acquire()` 再 `subscribe()`：见 `Flight.subscribe` 的
        注释（2026-11-02 线上：中间那道缝让新请求挂到被放弃的那一轮上，
        用户等 1.5s 拿到 0 条）。这里把两步放进同一把锁里，
        "还能不能挂"与"挂上去"之间就没有缝了。

        拿不到就现建一轮 —— 弃轮/结束轮的 key 会被顺手摘掉，
        下一次 `acquire` 才不会又把它捞出来。
        """
        for _attempt in range(4):
            with self._lock:
                cur = self._items.get(key)
                if cur is not None and cur.accepts():
                    sub = cur.subscribe(loop)
                    if sub is not None:
                        return cur, sub
                    # 就在这一瞬间被放弃了（leave 不拿登记簿的锁）—— 换新的
                if cur is not None and self._items.get(key) is cur:
                    self._items.pop(key, None)
                f = factory()
                self._items[key] = f
                f._on_finish = lambda: self.release(key, f)
                sub = f.subscribe(loop)
                if sub is not None:
                    return f, sub
            # 刚建好就被放弃：只可能是别的线程在别处乱动，重来一次即可。
        raise RuntimeError("在飞搜索登记簿连续 4 次拿不到可订阅的一轮")

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
