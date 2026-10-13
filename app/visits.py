"""访客记录 —— 谁在用这个站、用得多不多、是不是第一次来。

为什么要有它
------------
上线后最常被问的两个问题，此前**都答不上来**：

  · 「有人用吗？」—— 日志里有 `http` 行，但那是流水账，还得自己 awk 汇总；
  · 「昨天是不是挂了？」—— 只能看到此刻，看不到趋势。

日志是**给排障用的**，不是给看数据用的：它会轮转、会删、格式面向 grep。
这一层把"访问"变成结构化的、能长期留存的数据，并且**自带聚合**。

设计边界（很重要）
------------------
这是自建小站，不是商业分析平台。刻意**不做**下面这些：

  · 不存完整 IP —— 只存脱敏后的（`1.2.3.*`），够区分访客，又降了隐私风险；
  · 不存完整 UA —— 只抽浏览器/系统大类（Chrome / Windows），长 UA 没意义还占盘；
  · 不记每一条静态资源 —— 一次页面加载几十个请求，记了就是把库撑爆；
  · 不引入 Cookie 追踪 —— 用「日 + 脱敏 IP + UA 大类」的哈希做访客指纹；
  · 机器轮询（进度条每秒一次的心跳）不计入明细 —— 见 `_NOISE_PREFIX`，
    它算 PV（代表真人在线），但不该把"谁来过"刷成一屏下载进度。

落盘结构（`cache/visits.json`）::

    {
      "version": 1,
      "days": {
        "2026-10-13": {"pv": 128, "uv": ["a1b2c3", ...], "paths": {"/api/search": 30}},
        ...
      },
      "recent": [ {"ts":..., "path":"/api/search", "ip":"1.2.3.*", "ua":"Chrome/Windows", "ms":120, "code":200, "new": true} ],
      "first_seen": 1760000000
    }

`days` 是聚合（长期留存，看趋势），`recent` 是明细（只留最近 N 条，看"刚刚谁来过"）。
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .logging_setup import get_logger, log_event

logger = get_logger("novel.visits")

_ROOT = Path(__file__).resolve().parent.parent
_DB = Path(os.environ.get("NOVEL_VISITS") or (_ROOT / "cache" / "visits.json"))

# 明细只留 200 条 —— 够看"最近谁来过"，再多就是给自己攒垃圾。
_MAX_RECENT = 200
# 聚合按天留 400 天。超过一年基本没人看，但留一年足够对比"去年同期"。
_MAX_DAYS = 400

_lock = threading.Lock()
_data: dict[str, Any] = {"version": 1, "days": {}, "recent": [], "first_seen": 0}
_loaded = False
_save_counter = 0

# 落盘节流：访问是高频动作，每次请求都写盘会把磁盘打满。
# 每 20 次访问或每 60 秒落一次 —— 崩了最多丢最近几十条明细，聚合不受影响。
_SAVE_EVERY = 20
_SAVE_INTERVAL = 60.0
_last_save = 0.0


def _mask_ip(ip: str) -> str:
    """脱敏 IP：IPv4 只留前三段，IPv6 只留前两组。

    为什么要脱敏：完整 IP 属于个人信息，而这里根本不需要精确到主机 ——
    "1.2.3.*" 已经足够区分不同访客，也足够看出"是不是同一个人在刷"。
    """
    s = str(ip or "").strip()
    if not s:
        return "?"
    if ":" in s:                       # IPv6
        parts = [p for p in s.split(":") if p]
        return ":".join(parts[:2]) + ":*" if parts else "?"
    parts = s.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3]) + ".*"
    return s[:16]


def _ua_family(ua: str) -> str:
    """把长 UA 压成「浏览器/系统」两大类。

    ⚠ 抽大类而不是原样存：一条 Chrome 的 UA 有 120+ 字符，
    存 200 条就是 24KB 的纯噪音，而它要回答的问题只有
    "是手机还是电脑"。
    """
    s = str(ua or "")
    if not s:
        return "?"
    if "Edg/" in s:
        b = "Edge"
    elif "OPR/" in s or "Opera" in s:
        b = "Opera"
    elif "Firefox/" in s:
        b = "Firefox"
    elif "Chrome/" in s or "CriOS" in s:
        b = "Chrome"
    elif "Safari/" in s:
        b = "Safari"
    elif "curl" in s or "python" in s.lower() or "httpx" in s.lower():
        b = "Bot/CLI"
    else:
        b = "其它"

    if "iPhone" in s or "iPad" in s:
        o = "iOS"
    elif "Android" in s:
        o = "Android"
    elif "Windows" in s:
        o = "Windows"
    elif "Mac OS X" in s:
        o = "macOS"
    elif "Linux" in s:
        o = "Linux"
    else:
        o = "?"
    # 命令行/爬虫不带 OS 信息，硬拼一个 `?` 只会让界面出现
    # 「Bot/CLI/?」这种读起来莫名其妙的字符串。这类直接返回大类。
    if b == "Bot/CLI" or o == "?":
        return b
    return f"{b}/{o}"


def _fingerprint(day: str, ip: str, ua: str) -> str:
    """访客指纹 = 日 + 脱敏IP + UA大类的哈希。

    为什么带上"日"：这样同一台设备**每天算一个新访客**（= 次日回访会被
    统计成 UV，符合"日活"的直觉）。如果只用 IP+UA，那 UV 会变成
    "历史总人数"，日活就永远涨不上去，看不出趋势。
    """
    raw = f"{day}|{ip}|{ua}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def _today() -> str:
    return date.today().isoformat()


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        raw = json.loads(_DB.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except Exception as e:  # noqa: BLE001
        log_event(logger, "visits.load.fail", 原因=str(e)[:120])
        return
    if not isinstance(raw, dict):
        return
    days = raw.get("days")
    if isinstance(days, dict):
        _data["days"] = days
    recent = raw.get("recent")
    if isinstance(recent, list):
        rows = [r for r in recent if isinstance(r, dict)]
        # 自愈：清掉历史上写进来的机器轮询噪音。
        # 为什么要在**读**的时候做（而不是只靠写入端过滤）：
        # 过滤规则是后加的，库里已经躺着一批 `/api/progress/*` 明细 ——
        # 它们会一直占着列表前部，直到新访问把它们顶出 200 条上限。
        # 用户点开「最近来过」看到一屏下载进度，就是这个问题。
        # 读时顺手清一遍既不用停机、也不用改数据文件格式，且幂等。
        rows = [r for r in rows
                if not str(r.get("path") or "").startswith(_NOISE_PREFIX)]
        _data["recent"] = rows[:_MAX_RECENT]
    try:
        _data["first_seen"] = float(raw.get("first_seen") or 0)
    except (TypeError, ValueError):
        _data["first_seen"] = 0.0


def _save(force: bool = False) -> None:
    """原子落盘（带节流）。失败不抛。"""
    global _save_counter, _last_save
    now = time.time()
    if not force:
        _save_counter += 1
        if _save_counter < _SAVE_EVERY and (now - _last_save) < _SAVE_INTERVAL:
            return
    _save_counter = 0
    _last_save = now
    # 天数封顶：超过就丢最老的（字典按插入序，丢前面的）
    days = _data["days"]
    if len(days) > _MAX_DAYS:
        for k in list(days.keys())[: len(days) - _MAX_DAYS]:
            days.pop(k, None)
    try:
        _DB.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "days": _data["days"],
            "recent": _data["recent"][:_MAX_RECENT],
            "first_seen": _data["first_seen"],
        }
        tmp = _DB.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, _DB)
    except Exception as e:  # noqa: BLE001
        log_event(logger, "visits.save.fail", 原因=str(e)[:120])


# 不记的路径前缀。
#   · 静态资源：一次页面加载几十个请求，记了纯属自残；
#   · /api/visits 自身：否则"看统计"这个动作本身不断产生新访问，
#     页面每刷新一次数字就涨一次 —— 看起来像有人在不停刷（自激）；
#   · /api/history 同理：搜索框**每次聚焦**都会拉一次历史做下拉，
#     而这纯属界面装饰、不是用户"在访问内容"。不排掉的话，
#     top_paths_today 会被 `/api/history/search` 占满，真实行为被淹没。
# 判断用 startswith，所以前缀要写到不会被误伤的粒度
# （`/api/visits` 不会误伤 `/api/visitsomething`，因为不存在这种路径）。
_SKIP_PREFIX = ("/static", "/favicon", "/api/visits", "/api/history")


# 「机器轮询」路径：算 PV，但**不进明细列表**。
#
# 为什么单独开一类（而不是直接塞进 _SKIP_PREFIX）
# ------------------------------------------------
# 线上实测发现：一次看明细，30 条里 **24 条**都是 `/api/progress/{id}`。
# 那是下载任务进度条 —— 前端 `pollTask()` **每秒拉一次**（见 tasks.js），
# 一个跑 5 分钟的导出就是 300 次请求。后果有两层：
#
#   · 明细列表被同一路径刷屏，真正的"有人打开了阅读器/书架"全被淹掉，
#     想看"刚刚谁来过"变成了看"谁挂着下载"；
#   · PV 会退化成"某个人把页面挂了多久"，而不是"页面被看了几次"。
#
# 但也不能直接不记：这类请求确实代表**真人在线**（有人在等下载完成）。
# 所以口径定成「计入 PV/UV，只是不占明细」——既保住"有人用吗"的答案，
# 又让明细能读。明细里同一路径本就会重复出现，去掉噪音不损失信息。
_NOISE_PREFIX = ("/api/progress", "/api/health")


def record(path: str, ip: str, ua: str, ms: float, code: int,
           *, is_api: bool = True) -> None:
    """记一次访问。**绝不抛异常** —— 访问统计出问题不该影响任何接口。"""
    try:
        p = str(path or "")
        if not is_api:
            return
        if p.startswith(_SKIP_PREFIX):
            return
        # 4xx 大多是探测（扫描器找 /wp-admin 之类），不该抬高"访问量"。
        # 只记 2xx/3xx 和 5xx（5xx 要留，那是真出事了）。
        if 400 <= code < 500:
            return

        mip = _mask_ip(ip)
        fam = _ua_family(ua)
        day = _today()
        fp = _fingerprint(day, mip, fam)
        now = time.time()

        with _lock:
            _load()
            if not _data["first_seen"]:
                _data["first_seen"] = now
            blk = _data["days"].setdefault(day, {"pv": 0, "uv": [], "paths": {}})
            blk["pv"] = int(blk.get("pv") or 0) + 1
            uv = blk.setdefault("uv", [])
            is_new = fp not in uv
            if is_new:
                uv.append(fp)
                # 日 UV 上限，防止被刷爆内存
                if len(uv) > 5000:
                    del uv[:-4000]
            paths = blk.setdefault("paths", {})
            paths[p] = int(paths.get(p) or 0) + 1
            if len(paths) > 60:
                # 路径种类封顶，保住最多的那些
                keep = sorted(paths.items(), key=lambda kv: -kv[1])[:50]
                blk["paths"] = dict(keep)
            # 机器轮询只进聚合（PV 已 +1、paths 已计数），但不占明细列表 ——
            # 否则「刚刚谁来过」会被每秒一次的进度轮询刷屏（见 _NOISE_PREFIX）。
            if not p.startswith(_NOISE_PREFIX):
                _data["recent"].insert(0, {
                    "ts": int(now), "path": p, "ip": mip, "ua": fam,
                    "ms": int(ms), "code": int(code), "new": bool(is_new),
                })
                del _data["recent"][_MAX_RECENT:]
            _save()
    except Exception as e:  # noqa: BLE001
        # 统计是"锦上添花"，绝不能因为它让业务接口 500
        try:
            log_event(logger, "visits.record.fail", 原因=str(e)[:120])
        except Exception:  # noqa: BLE001
            pass


def recent(limit: int = 50) -> list[dict[str, Any]]:
    """最近 N 条访问明细。**只读。**"""
    with _lock:
        _load()
        n = max(1, min(int(limit or 50), _MAX_RECENT))
        return [dict(r) for r in _data["recent"][:n]]


def stats(days: int = 14) -> dict[str, Any]:
    """给界面看的汇总：今日 / 昨日 / 累计 PV·UV，以及最近 N 天的趋势。

    「今日 UV」用的是**日指纹**，所以它天然等于"今天有多少台设备来过"，
    这正是用户问「有人用吗」时想知道的数。
    """
    with _lock:
        _load()
        today = _today()
        d = _data["days"]
        blk = d.get(today) or {}
        # 昨天：用 datetime 算，别自己减 86400 —— 夏令时/闰秒会让它错一天
        try:
            y = datetime.fromisoformat(today).date().toordinal() - 1
            yday = date.fromordinal(y).isoformat()
        except Exception:  # noqa: BLE001
            yday = ""
        yblk = d.get(yday) or {}

        total_pv = sum(int(v.get("pv") or 0) for v in d.values())
        total_uv = sum(len(v.get("uv") or []) for v in d.values())

        today_paths = sorted((blk.get("paths") or {}).items(),
                             key=lambda kv: -kv[1])[:10]

        # 趋势：最近 days 天，按日期升序（图表要从左到右读）
        keys = sorted(d.keys())[-max(1, min(int(days or 14), 90)):]
        trend = [{
            "day": k,
            "pv": int((d[k] or {}).get("pv") or 0),
            "uv": len((d[k] or {}).get("uv") or []),
        } for k in keys]

        return {
            "today": today,
            "pv_today": int(blk.get("pv") or 0),
            "uv_today": len(blk.get("uv") or []),
            "pv_yesterday": int(yblk.get("pv") or 0),
            "uv_yesterday": len(yblk.get("uv") or []),
            "pv_total": total_pv,
            "uv_total": total_uv,
            "first_seen": int(_data["first_seen"] or 0),
            "top_paths_today": [{"path": p, "n": n} for p, n in today_paths],
            "trend": trend,
        }


def clear() -> int:
    """清空访客数据。返回删掉的天数。"""
    with _lock:
        _load()
        n = len(_data["days"])
        _data["days"] = {}
        _data["recent"] = []
        _data["first_seen"] = 0
        _save(force=True)
        log_event(logger, "visits.clear", 天数=n)
        return n
