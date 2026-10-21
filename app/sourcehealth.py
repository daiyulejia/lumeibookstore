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

2026-10-22 线上实测之后补的两件事
--------------------------------
① **冷却要一轮比一轮长**（`BACKOFF`）。原来每次熔断都是固定的 15 分钟，
   于是一个**永远**打不通的源（维基文库：境外站，云端 SSL 握手必超时）
   每小时还要被放进来试 4 次，每次都让一次真实搜索陪它等；一天下来
   日志里 117 条 `The handshake operation timed out`、真正救回来的 0 次。
   现在连挂的轮数越多冷却越长（15m → 30m → 60m → …封顶 8 小时）：
   抖动型的源第一次就恢复，死掉的源很快就不再占日历。
② **状态要落盘**。原来是纯内存，每次 sync/重启都会**忘掉**谁打不通 ——
   重启后的第一次搜索又要陪那几个坏源等满一整轮。现在熔断状态写进
   `cache/sourcehealth.json`（`NOVEL_HEALTH` 可改路径），启动时读回来。
   ⚠ 落盘只写**仍在冷却中**的条目；过期的（`until` 已过 24 小时以上）直接丢，
   否则一份旧文件会让某个源永久回不来。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

# 失败分两类：网络类要等更久（多半是被墙/被封，短时间不会好），
# 其它（解析、结构变化）短冷却就够 —— 可能下一秒就恢复了。
KIND_NET = "net"
KIND_OTHER = "other"

OPEN_AFTER = 2                    # 连续挂几次才熔断
COOLDOWN = {KIND_NET: 900.0,      # 15 分钟：被墙/被封不会马上好
            KIND_OTHER: 300.0}    # 5 分钟

# 连续第 N 次熔断的冷却 = 基础值 × BACKOFF^(N-1)，封顶 MAX_COOLDOWN。
# 为什么要退避：固定 15 分钟意味着"永远打不通的源"一小时被放进来试 4 次，
# 每次都要让一次真实搜索陪它等（见文件头 ①）。
BACKOFF = 2.0
MAX_COOLDOWN = 8 * 3600.0         # 8 小时

# 落盘的文件（熔断状态要跨重启）。`NOVEL_HEALTH` 让测试/多实例分开。
_DEFAULT_PATH = (Path(__file__).resolve().parent.parent
                 / "cache" / "sourcehealth.json")

# 落盘条目最多留多久：超过这个时间的旧账直接丢，免得某个源永久回不来。
STALE_AFTER = 24 * 3600.0

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
    """按源名记「连续挂了几次 / 什么时候能再试」。线程安全。

    `path=None`（默认）= 纯内存，不碰磁盘（测试默认走这条）。
    给 `<path>` 就落盘：熔断时写、`allows()` 第一次调用时读回来。
    """

    def __init__(self, *, open_after: int = OPEN_AFTER,
                 cooldown: Optional[dict[str, float]] = None,
                 path: Optional[Path | str] = None) -> None:
        self.open_after = open_after
        self.cooldown = dict(cooldown or COOLDOWN)
        self._lock = threading.Lock()
        self._st: dict[str, dict[str, Any]] = {}
        self._path = Path(path) if path else None
        self._loaded = False

    # -- 落盘 ------------------------------------------------------------
    def _ensure_loaded(self) -> None:
        """第一次访问时把上次的熔断状态读回来（只读一次）。"""
        if self._loaded or not self._path:
            return
        self._loaded = True
        raw: dict[str, Any] = {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return          # 没有 / 坏了都当没有
        if not isinstance(raw, dict):
            return
        now = time.time()
        with self._lock:
            for name, blk in raw.items():
                if not isinstance(blk, dict):
                    continue
                until = float(blk.get("until") or 0)
                # 只收「仍在冷却中」且不太旧的；过期的旧账丢掉
                if until <= now or until < now - STALE_AFTER:
                    continue
                self._st[str(name)] = {
                    "fails": int(blk.get("fails") or 0),
                    "until": until,
                    "kind": str(blk.get("kind") or KIND_OTHER),
                    "why": str(blk.get("why") or ""),
                    "trial": False,
                    "streak": int(blk.get("streak") or 1),
                    "cd": float(blk.get("cd") or 0),
                }

    def _save(self) -> None:
        """把**仍在冷却中**的条目写盘（原子替换）。失败不抛。"""
        if not self._path:
            return
        now = time.time()
        with self._lock:
            data = {k: {kk: v.get(kk) for kk in
                        ("fails", "until", "kind", "why", "streak", "cd")}
                    for k, v in self._st.items()
                    if float(v.get("until") or 0) > now}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(tmp, self._path)      # 原子：别写出半截 JSON
        except Exception:  # noqa: BLE001
            pass            # 落盘失败只影响"重启后记得"，不该影响搜索

    # -- 读 --------------------------------------------------------------
    def allows(self, name: str) -> bool:
        """现在能不能给这个源发请求。

        冷却已到期时返回 True 并把它标成"半开试探"（`_trial`）——
        下一次 `note_fail()` 会**立刻重新熔断**，不必再攒到 open_after 次。
        """
        self._ensure_loaded()
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
        """这个源这次答话了（哪怕是空列表）—— 一切清零。

        ⚠ 连 `streak` 也要清：清了它，下次再挂又从容忍 15 分钟开始。
          不清的话，一个"挂挂挂…好了一次…又挂"的源会被一路按 8 小时冷却，
          恢复的信号就被当成没发生过（实测的抖动型源正好是这种形态）。
        """
        self._ensure_loaded()
        had = False
        with self._lock:
            had = self._st.pop(name, None) is not None
        # ⚠ 只在**真的删掉了一条**时才落盘：`note_ok` 是热路径（每个源每次
        #   搜索都会调一次），无脑写盘等于每次搜索多 7 次 文件 tmp+replace。
        if had:
            self._save()

    def note_fail(self, name: str, exc: BaseException | str = "") -> float:
        """记一次「挂」。返回**这次熔断实际用的冷却秒数**（0.0 = 没熔断）。

        ⚠ 返回秒数而不是 bool：日志里原来写死"熔断 15 分钟"，加了退避之后
          那句会开始撒谎（第二次是 30 分钟）。让调用方拿真实值去说。

        `note_ok` 才会清零；空结果请走 `note_ok`（空 ≠ 挂）。
        """
        self._ensure_loaded()
        kind = classify(exc)
        now = time.time()
        dur = 0.0
        with self._lock:
            s = self._st.setdefault(name, {"fails": 0, "until": 0,
                                           "kind": kind, "why": "", "trial": False,
                                           "streak": 0, "cd": 0.0})
            # 半开试探失败 → 立刻重新熔断（不再等攒够次数）
            tripped = bool(s.get("trial")) or (int(s.get("fails") or 0) + 1) >= self.open_after
            s["fails"] = int(s.get("fails") or 0) + 1
            s["kind"] = kind
            s["why"] = f"{type(exc).__name__}: {exc}"[:160] if isinstance(exc, BaseException) else str(exc)[:160]
            s["trial"] = False
            if tripped:
                # 这一轮是第几次连着熔断 → 冷却指数增长，封顶 MAX_COOLDOWN
                s["streak"] = int(s.get("streak") or 0) + 1
                base = float(self.cooldown.get(kind, 300.0))
                dur = min(base * (BACKOFF ** (s["streak"] - 1)), MAX_COOLDOWN)
                s["until"] = now + dur
                s["cd"] = dur
                s["fails"] = 0      # 冷却期重新开始计数，免得一次熔断就永久放不平
        if dur:
            self._save()
        return dur

    def reset(self) -> None:
        self._ensure_loaded()
        with self._lock:
            self._st.clear()
        self._save()


# 进程级单例：内置源在一个进程里共用一套记忆。
# `path` 让它**跨重启**也记得谁打不通（原来是纯内存，每次 sync/重启就忘光，
# 重启后的第一次搜索又要陪那几个坏源等满一整轮）。
HEALTH = SourceHealth(path=os.environ.get("NOVEL_HEALTH") or _DEFAULT_PATH)
