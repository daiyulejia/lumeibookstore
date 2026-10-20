"""内置源的熔断器 —— 「撞过的墙」不该每次搜索都再撞一遍。

为什么需要它
============
2026-10-21 线上日志（真实用户流量）：

    00:40:28  search.start 书名=青叶灵异事务所
    00:40:30  novel.xbqg5200: 搜索失败: HTTP 403
    00:40:33  novel.discovery: 候选核实失败 m.kudushu.org: HTTP 403
    00:40:41  novel.wikisource: 搜索失败: API 请求失败: _ssl.c:990
              The handshake operation timed out
    00:40:48  搜索收手（墙钟 20.0s 到点，仍无结果）：已答 4/7 个源、原始 0 条
    00:46:16  同一本书**再搜一次** → 5/7 个源答完 → 有 1 条结果

同一本书、同一个服务器，相隔 6 分钟：一次 0 条、一次 1 条。
差别只在于「这次哪几个源先回来」。而那几个永远回不来的源
（维基文库 SSL 握手超时、xbqg5200 403、xbqg 502）**每次搜索都还在名单里**，
每次都要陪它们等满 20 秒。

根因不是"慢"，是**没有记忆**：`source.fail` 只写了一条日志，
没有任何东西让下一次搜索知道"这个源现在打不通，别再等它"。

判据口径（很重要，写反了就变成"偶尔没搜到就被永久拉黑"）
--------------------------------------------------------
· **抛异常 = 挂**：连不上、SSL 失败、403/502、连接重置、读取超时。
· **返回空列表 = 没挂**：这通常只是"这个源没有这本书"，是正常业务结果。
  把空结果算失败的话，搜冷门书会把所有源全拉黑，之后搜什么都 0 条 ——
  比慢更糟，而且完全静默。
· 连续 `OPEN_AFTER` 次「挂」才熔断，单次抖动不算。
· 冷却期内**不发请求**（这才省得下那 20 秒）；冷却到期放行**一次**（半开），
  成功清零、失败立刻重新熔断（判据是"这次连通了吗"，不是"又有几次失败"）。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

# 失败分两类：网络类要等更久（多半是被墙/被封，短时间不会好），
# 其它（解析、结构变化）短冷却就够 —— 可能下一秒就恢复了。
KIND_NET = "net"
KIND_OTHER = "other"

OPEN_AFTER = 2                    # 连续挂几次才熔断
COOLDOWN = {KIND_NET: 900.0,      # 15 分钟：被墙/被封不会马上好
            KIND_OTHER: 300.0}    # 5 分钟

# 判定成"网络层问题"的特征（异常类型名 / 消息关键字）。
# ⚠ 这些是**字符串匹配**，所以要放进消息里比对；改源时请保持异常消息可读。
_NET_HINTS = (
    "timeout", "timed out", "ssl", "handshake", "connection", "connect",
    "reset", "refused", "unreachable", "eof", "403", "412", "429",
    "502", "503", "504", "too many requests", "forbidden",
)


def classify(exc: BaseException | str) -> str:
    """把一次失败归类成 KIND_NET / KIND_OTHER。"""
    if isinstance(exc, BaseException):
        text = f"{type(exc).__name__}: {exc}".lower()
        # 超时类异常即使消息里没有关键字也要算网络问题
        if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
            return KIND_NET
    else:
        text = str(exc).lower()
    return KIND_NET if any(h in text for h in _NET_HINTS) else KIND_OTHER


class SourceHealth:
    """按源名记「连续挂了几次 / 什么时候能再试」。线程安全。"""

    def __init__(self, *, open_after: int = OPEN_AFTER,
                 cooldown: Optional[dict[str, float]] = None) -> None:
        self.open_after = open_after
        self.cooldown = dict(cooldown or COOLDOWN)
        self._lock = threading.Lock()
        self._st: dict[str, dict[str, Any]] = {}

    # -- 读 --------------------------------------------------------------
    def allows(self, name: str) -> bool:
        """现在能不能给这个源发请求。

        冷却已到期时返回 True 并把它标成"半开试探"（`_trial`）——
        下一次 `note_fail()` 会**立刻重新熔断**，不必再攒到 open_after 次。
        """
        now = time.time()
        with self._lock:
            s = self._st.get(name)
            if not s:
                return True
            until = float(s.get("until") or 0)
            if until <= now:
                if until:
                    # 冷却刚到期：放行一次，记成试探
                    s["trial"] = True
                    s["until"] = 0
                return True
            return False

    def is_open(self, name: str) -> bool:
        """是否处于熔断期（给测试/诊断用，不做半开转换）。"""
        with self._lock:
            s = self._st.get(name) or {}
            return float(s.get("until") or 0) > time.time()

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._st.items()}

    def open_sources(self) -> list[str]:
        now = time.time()
        with self._lock:
            return sorted(k for k, v in self._st.items()
                          if float(v.get("until") or 0) > now)

    # -- 写 --------------------------------------------------------------
    def note_ok(self, name: str) -> None:
        """这个源这次答话了（哪怕是空列表）—— 一切清零。"""
        with self._lock:
            self._st.pop(name, None)

    def note_fail(self, name: str, exc: BaseException | str = "") -> bool:
        """记一次「挂」。返回**这次是否触发了熔断**。

        `note_ok` 才会清零；空结果请走 `note_ok`（空 ≠ 挂）。
        """
        kind = classify(exc)
        now = time.time()
        with self._lock:
            s = self._st.setdefault(name, {"fails": 0, "until": 0,
                                           "kind": kind, "why": "", "trial": False})
            # 半开试探失败 → 立刻重新熔断（不再等攒够次数）
            tripped = bool(s.get("trial")) or (int(s.get("fails") or 0) + 1) >= self.open_after
            s["fails"] = int(s.get("fails") or 0) + 1
            s["kind"] = kind
            s["why"] = f"{type(exc).__name__}: {exc}"[:160] if isinstance(exc, BaseException) else str(exc)[:160]
            s["trial"] = False
            if tripped:
                s["until"] = now + float(self.cooldown.get(kind, 300.0))
                s["fails"] = 0      # 冷却期重新开始计数，免得一次熔断就永久放不平
            return tripped

    def reset(self) -> None:
        with self._lock:
            self._st.clear()


# 进程级单例：内置源在一个进程里共用一套记忆。
HEALTH = SourceHealth()
