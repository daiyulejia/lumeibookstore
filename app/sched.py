"""进程内定时任务：让「热门榜单」始终是热的。

为什么需要一个进程内的调度器
----------------------------
榜单是**没人点也该是热的**东西。用户打开发现页时，如果要先等 3 秒
联网抓 6 个榜单，体验是"这站好卡"。所以要有人替他把这件事提前做掉。

三层保险，各管一段：
  1. **落盘缓存**（ranks.py）—— 进程重启不丢，重启后立刻有内容
  2. **本模块（进程内定时）** —— 服务活着的时候，每隔 N 分钟自动刷新
  3. **systemd timer**（tools/）—— 进程万一没起来/被停掉，系统层再兜一次

为什么不用 apscheduler 之类
---------------------------
就一个「每隔 N 分钟跑一次」的活，一个 daemon 线程 + 一个 Event.wait 就够了。
引第三方库要处理它的生命周期、日志、异常，收益为负。

为什么用 Event.wait(timeout) 而不是 time.sleep
---------------------------------------------
`time.sleep` 睡死了就**叫不醒** —— 测试里要等 30 分钟，关服务时也要等它
自然醒。Event.wait 可以被立刻唤醒，测试和优雅退出都靠它。

设计上的几个克制
----------------
* **只刷新，不做别的**。不要让它变成"什么都能定时"的框架 —— 那就跑偏了。
* **失败不退出线程**。抓不到就抓不到，下一个周期再试；线程不能死。
* **可关**。`NOVEL_SCHED=0` 或 `--no-sched` 时完全不启动，测试/调试不受干扰。
* **记最后一次结果**，`status()` 能查 —— 出问题时能分清是"没跑"还是"跑了没抓到"。
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Optional

# 默认每 30 分钟刷一次，和缓存 TTL 对齐：刷新周期 > TTL 会让缓存在
# 两次刷新之间过期，用户就会撞上"要现抓"的那一次，白等了。
# 对齐之后，正常访问几乎永远命中新鲜缓存。
DEFAULT_INTERVAL = float(os.environ.get("NOVEL_SCHED_INTERVAL") or 1800)


def _enabled() -> bool:
    """环境变量总闸。`NOVEL_SCHED=0` 关掉（测试默认会关）。"""
    return (os.environ.get("NOVEL_SCHED") or "1").strip() not in ("0", "false", "no", "")


class _Scheduler:
    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self.interval = DEFAULT_INTERVAL
        self.runs = 0
        self.last_started: Optional[float] = None
        self.last_finished: Optional[float] = None
        self.last_result: Optional[dict[str, Any]] = None
        self.last_error: str = ""

    # -- 运行 ---------------------------------------------------------------
    def _loop(self) -> None:
        # 启动后先等一小会儿再跑第一次：让服务先把 HTTP 端口起好、
        # 别和启动期的自检抢网络。60 秒足够，也不影响"第一次刷新"的时效。
        first_delay = float(os.environ.get("NOVEL_SCHED_FIRST_DELAY") or 60)
        if self._wake.wait(self._wait_or_stop(first_delay)):
            return  # 被 stop 唤醒
        while not self._stop.is_set():
            self.run_once()
            # 睡到下一个周期（可被 wake/stop 提前打断）
            if self._wake.wait(self._wait_or_stop(self.interval)):
                if self._stop.is_set():
                    return
                self._wake.clear()   # 手动唤醒 → 立刻再来一轮
                continue

    def _wait_or_stop(self, secs: float) -> float:
        """把"睡觉"和"停止"合成一个等待：停止时立刻返回。"""
        deadline = time.time() + max(0.0, secs)
        while not self._stop.is_set():
            left = deadline - time.time()
            if left <= 0:
                return 0.0
            self._stop.wait(min(left, 1.0))
        return 0.0

    def run_once(self) -> dict[str, Any]:
        """跑一轮刷新。同步执行（线程里调），异常一律吞掉记下来。"""
        from . import ranks as _rk
        with self._lock:
            self.runs += 1
            self.last_started = time.time()
        try:
            rep = _rk.refresh(force=True)
            with self._lock:
                self.last_result = rep
                # ⚠ refresh() 内部**吞掉**了单类异常（它把失败的类计数进
                # `failed`），所以这里不会抛 —— 如果不主动把「全灭」翻成
                # last_error，运维看到的就是「跑过了、错误字段空着」，
                # 明明一类都没抓到却像一切正常。这是实测踩出来的。
                total = rep.get("ok", 0) + rep.get("failed", 0)
                if total and rep.get("ok", 0) == 0:
                    self.last_error = f"全部 {rep['failed']} 类都没抓到（站点可能都挂了）"
                elif rep.get("failed"):
                    self.last_error = f"{rep['failed']} 类抓取失败"
                else:
                    self.last_error = ""
            print(f"  [sched] 榜单刷新完成：成功 {rep['ok']} / 失败 {rep['failed']}"
                  f"，耗时 {rep['elapsed']}s", flush=True)
            return rep
        except Exception as e:  # noqa: BLE001
            with self._lock:
                self.last_error = str(e)
            print(f"  [sched] 榜单刷新出错（下个周期重试）：{e}", flush=True)
            return {"ok": 0, "failed": -1, "error": str(e)}
        finally:
            with self._lock:
                self.last_finished = time.time()

    # -- 生命周期 -----------------------------------------------------------
    def start(self, interval: Optional[float] = None, first_delay: Optional[float] = None) -> bool:
        """启动后台线程。返回是否真的启动了。"""
        if not _enabled():
            print("  [sched] 已禁用（NOVEL_SCHED=0），不启动定时刷新", flush=True)
            return False
        if self._thread and self._thread.is_alive():
            return False
        if interval:
            self.interval = float(interval)
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(target=self._loop, name="ranks-sched", daemon=True)
        self._thread.start()
        print(f"  [sched] 榜单定时刷新已启动：每 {int(self.interval // 60)} 分钟一次"
              f"（首轮 {int(first_delay or 60)}s 后）", flush=True)
        return True

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self._wake.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout)

    def wake(self) -> None:
        """叫醒它立刻跑一轮（界面点「立即刷新」时用）。"""
        self._wake.set()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": _enabled(),
                "running": bool(self._thread and self._thread.is_alive()),
                "interval": int(self.interval),
                "runs": self.runs,
                "last_started": int(self.last_started) if self.last_started else None,
                "last_finished": int(self.last_finished) if self.last_finished else None,
                "last_ok": (self.last_result or {}).get("ok"),
                "last_failed": (self.last_result or {}).get("failed"),
                "last_elapsed": (self.last_result or {}).get("elapsed"),
                "last_error": self.last_error,
            }


_INSTANCE = _Scheduler()


def start(interval: Optional[float] = None, first_delay: Optional[float] = None) -> bool:
    return _INSTANCE.start(interval, first_delay)


def stop(timeout: float = 3.0) -> None:
    _INSTANCE.stop(timeout)


def wake() -> None:
    _INSTANCE.wake()


def run_once() -> dict[str, Any]:
    return _INSTANCE.run_once()


def status() -> dict[str, Any]:
    return _INSTANCE.status()
