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
   ⚠ 落盘只把**仍在冷却中**的条目放进内存账本；`until <= now` 的不进
   `snapshot()`，否则一份旧文件会让诊断面板上多出一条"刚挂过"的幽灵记录。

2026-10-26 复盘：**冷态的账被一起丢了**
--------------------------------------
上面那句"只写仍在冷却中的条目"有个副作用：冷却**到期**的那一刻，条目就
既不再落盘、也不再被读回 —— 于是 `streak`（这是它连着第几轮熔断）每次
重启都归 1，`BACKOFF` 的指数退避**永远涨不上去**。

线上证据（同一台机器、同一个源，一天之内）：

    10-23 09:06  源 wikisource 熔断 15 分钟
    10-23 10:06  源 wikisource 熔断 15 分钟   ← 一小时后又从 15 分钟开始
    10-24 09:04  源 wikisource 熔断 30 分钟
    10-24 09:51  源 wikisource 熔断 15 分钟   ← 倒退
    10-25 09:07  源 wikisource 熔断 30 分钟
    10-25 09:50  源 wikisource 熔断 15 分钟   ← 倒退（09:48:26 服务重启过）

三天的时钟对得上：**每次 ship/重启之后，冷却都从 15 分钟重来**。
15 分钟冷却意味着一个死源每小时被放进来试 4 次，每次都让一次真实搜索
陪它等满 6 秒墙钟 —— 退避写了、却从来没生效过。

修法：落盘时把**到期但还没被证实恢复**的条目也写下去（`until=0`），
读回时**不进内存账本**（不进 `snapshot()`/`open_sources()`，不会有幽灵
记录），而是进 `_memory`（失败史）。这个源下次再挂时：

· `streak` 接着上一轮算（15m → 30m → 60m …），退避这才真的生效；
· 直接按"半开试探"处理（一次失败就重新熔断），不必再攒够两次 ——
  它本来就是**到期后被放出来试**的那一次，只是试的时候进程重启了；
· 一答话（`note_ok`）就整条清掉，抖动型的源照样从头开始。

唯一的取舍：一份**很久以前**的失败史不该决定今天的冷却。所以失败史带
时间戳，`FORGET_AFTER`（7 天）之后自动忘掉 —— 站点是会修的。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("novel.health")

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

# 失败史保留多久（秒）。超过就整条忘掉：站点是会修的，
# 一份上周的死因不该决定今天的冷却。真正一直挂着的源不会过期 ——
# 它每次半开试探失败都会刷新时间戳。
FORGET_AFTER = 7 * 86400.0

# 落盘的文件（熔断状态要跨重启）。`NOVEL_HEALTH` 让测试/多实例分开。
_DEFAULT_PATH = (Path(__file__).resolve().parent.parent
                 / "cache" / "sourcehealth.json")

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
        # 失败史（**不在冷却中**的旧账）：name → {streak, cd, kind, why, at}。
        # ⚠ 它**不是** `_st` 的一部分，刻意不让 `snapshot()`/`open_sources()`
        #   看见 —— 那些接口回答的是"这个源现在能不能发请求 / 面板上该不该
        #   标红"，一条早就到期的旧账混进去就是幽灵记录（见文件头）。
        #   它唯一的用途：重启后 `note_fail` 接着上一轮的 `streak` 退避。
        self._memory: dict[str, dict[str, Any]] = {}
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
        # 读回的两类账，分开报出来（否则"重启后到底想起了什么"只能靠猜）：
        #   open   仍在冷却 → 进账本，这次连请求都不发
        #   memory 已到期但没被证实恢复 → 只留失败史，照样发请求，
        #          但一次失败就按上一轮的退避重新熔断（见文件头 2026-10-26）
        n_open: list[str] = []
        n_mem: list[str] = []
        with self._lock:
            for name, blk in raw.items():
                if not isinstance(blk, dict):
                    continue
                name = str(name)
                until = float(blk.get("until") or 0)
                streak = int(blk.get("streak") or 0)
                # 只收「仍在冷却中」的进账本；已经到期的直接丢。
                # ⚠ 别写成"顺带判一下够不够旧"：`until <= now` 已经覆盖了
                #   "旧"这件事，再加一个 `until < now - 24h` 就是**死条件** ——
                #   第一版就是这么写的（还配了一条"过期丢掉了"的断言），
                #   看着严谨，实际什么都没多做。判据要能分辨"丢掉了"和
                #   "留着一条早过期的记录"，所以下面还钉了 `snapshot()` 里不许有它。
                if until <= now:
                    # 「丢」不等于「忘」：这一格原来直接 continue，于是
                    # `streak` 跟着一起没了 → 每次重启退避都从 15 分钟重来
                    # （线上三天的证据见文件头 2026-10-26）。失败史留下来，
                    # 但**绝不进账本**：账本是"现在能不能发请求"，它是过去。
                    at = float(blk.get("at") or until or 0)
                    if streak > 0 and (now - at) <= FORGET_AFTER:
                        self._memory[name] = {
                            "streak": streak,
                            "cd": float(blk.get("cd") or 0),
                            "kind": str(blk.get("kind") or KIND_OTHER),
                            "why": str(blk.get("why") or ""),
                            "at": at,
                        }
                        n_mem.append(f"{name}(streak={streak})")
                    continue
                self._st[name] = {
                    "fails": int(blk.get("fails") or 0),
                    "until": until,
                    "kind": str(blk.get("kind") or KIND_OTHER),
                    "why": str(blk.get("why") or ""),
                    "trial": False,
                    "streak": streak or 1,
                    "cd": float(blk.get("cd") or 0),
                    "at": float(blk.get("at") or now),
                }
                n_open.append(f"{name}({int((until - now) / 60)}分)")
        if n_open or n_mem:
            logger.info("熔断器读回落盘：仍冷却 %d 个（%s）；已到期但保留失败史 %d 个（%s）",
                        len(n_open), ", ".join(n_open) or "-",
                        len(n_mem), ", ".join(n_mem) or "-")

    def _save(self) -> None:
        """落盘（原子替换）。失败不抛。

        ⚠ 落的是**两样**东西：仍在冷却的条目（`until>now`，完整状态）
        和已到期但还没被证实恢复的失败史（`until=0`，只留 streak/为什么）。
        只写前者的版本会让 `streak` 在每次重启时归 1 —— 退避形同虚设，
        而死源依旧每小时被放进来试一次（见文件头 2026-10-26）。
        """
        if not self._path:
            return
        now = time.time()
        with self._lock:
            data: dict[str, Any] = {}
            for k, v in self._st.items():
                until = float(v.get("until") or 0)
                block = {kk: v.get(kk) for kk in
                         ("fails", "until", "kind", "why", "streak", "cd", "at")}
                if until <= now:
                    # ⚠ 账本里**已经到期**的条目也要写下去（按失败史的样子：
                    #   until=0）。丢掉它就等于把 `streak` 一起忘了 —— 这是
                    #   退避永远涨不上去的真正原因（见文件头 2026-10-26）。
                    #   没熔断过的（streak=0）不写，免得盘上全是"挂了一次"的噪声。
                    if int(v.get("streak") or 0) <= 0:
                        continue
                    block["until"] = 0.0
                    block["fails"] = 0
                    block["at"] = float(v.get("at") or now)
                data[k] = block
            for k, v in self._memory.items():
                if k in data:
                    continue        # 账本里已经有一条更新的，别拿旧史覆盖它
                data[k] = {"fails": 0, "until": 0.0,
                           "kind": v.get("kind"), "why": v.get("why"),
                           "streak": v.get("streak"), "cd": v.get("cd"),
                           "at": v.get("at")}
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
        ⚠ 落盘的失败史（`_memory`）同样要清 —— 那是"上一次死亡"的记忆，
          它已经答话了，旧账再留着，下次一挂就按 8 小时封顶。
        """
        self._ensure_loaded()
        had = False
        with self._lock:
            had = self._st.pop(name, None) is not None
            if self._memory.pop(name, None) is not None:
                had = True
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
            s = self._st.get(name)
            if s is None:
                # 账本里没有，但**可能有失败史**（冷却到期 / 进程重启过）。
                # 接着上一轮的 streak 退避，并按"半开试探"对待 ——
                # 这一次本来就是「到期后放出来试一试」，只是试的时候重启了。
                # ⚠ 不接的话：15m→30m→60m 永远涨不上去，死源每小时回来一次。
                mem = self._memory.pop(name, None)
                s = {"fails": 0, "until": 0, "kind": kind, "why": "",
                     "trial": bool(mem), "at": 0.0,
                     "streak": int((mem or {}).get("streak") or 0),
                     "cd": float((mem or {}).get("cd") or 0.0)}
                self._st[name] = s
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
                s["at"] = now       # 失败史的时间戳（`FORGET_AFTER` 按它算）
                s["fails"] = 0      # 冷却期重新开始计数，免得一次熔断就永久放不平
        if dur:
            self._save()
        return dur

    def reset(self) -> None:
        self._ensure_loaded()
        with self._lock:
            self._st.clear()
            self._memory.clear()
        self._save()


# 进程级单例：内置源在一个进程里共用一套记忆。
# `path` 让它**跨重启**也记得谁打不通（原来是纯内存，每次 sync/重启就忘光，
# 重启后的第一次搜索又要陪那几个坏源等满一整轮）。
HEALTH = SourceHealth(path=os.environ.get("NOVEL_HEALTH") or _DEFAULT_PATH)
