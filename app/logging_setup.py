"""结构化日志与埋点。
============================================================================
为什么重写（诊断依据）
----------------------
改造前线上一天的日志：**8210 行，其中 3850 行（47%）是 httpx 的爬取噪声**
（"HTTP Request: GET https://xxx 200 OK"）。剩下的 uvicorn 访问日志也没有
任何关联标识 —— 一次搜索会打十几个请求，出问题时**根本串不起来**：

    22:31:04 INFO httpx: HTTP Request: GET https://a.com/1 "200 OK"
    22:31:04 INFO httpx: HTTP Request: GET https://b.com/2 "200 OK"
    22:31:05 INFO 127.0.0.1 "GET /api/search 200 OK"
    ← 到这里报错了，你没法知道是哪本书、哪个来源、哪个请求
    22:31:06 ERROR 入书架失败: 'NoneType' object has no attribute 'get'

所以这一层的目标不是"多打日志"，而是三件事：
  1. **降噪**：把 httpx / uvicorn 的流水账压下去，只留异常
  2. **串联**：每个请求一个 request_id，一路传到爬虫和任务里
  3. **可筛**：日志行带结构化的 [event] 标记，能按事件名 grep

格式（人可读 + 机器可筛，不引 JSON 依赖）
----------------------------------------
    [22:31:05] INFO  req=a3f9  search.start   书名=三体
    [22:31:07] ERROR req=a3f9  search.fail    阶段=验证 原因=...

    · req= 是 4 位短 id —— 长 id 在终端里占地方，5 位随机足够区分同屏
    · 事件名统一 "模块.动作"，grep 得动：search.start / cache.done / export.fail

用法
----
    from .logging_setup import get_logger, set_request_id, log_event
    log = get_logger(__name__)
    log.info("入书架失败: %s", e)              # 普通日志
    log_event(log, "search.start", 书名=q)      # 埋点（自动带上 req= #）
============================================================================
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import random
import string
import sys
import threading
from contextvars import ContextVar
from pathlib import Path

# 每个请求一个 id。用 ContextVar 而不是 threading.local ——
# 应用是 async 的，threading.local 在同一条协程切换线程时会丢。
_req_id: ContextVar[str] = ContextVar("req_id", default="-")


def new_req_id() -> str:
    """4 位。经验值：同一时刻的并发请求很少超过几十，4 位（36^4≈168 万）
    足够不撞；而且短 id 在终端里一眼扫得过来，长 id 会把有用的信息挤出屏幕。"""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=4))


def set_request_id(rid: str | None = None) -> str:
    rid = rid or new_req_id()
    _req_id.set(rid)
    return rid


def get_request_id() -> str:
    return _req_id.get()


# ---------------------------------------------------------------------------
# 降噪：把确定没用的 logger 压到 WARNING
# ---------------------------------------------------------------------------
# 这些是"库的流水账"，不是"应用的行为"：
#   httpx      —— 每次 HTTP 请求一行（爬一本书几百行）
#   httpcore   —— httpx 底层，更啰嗦
#   uvicorn.access —— 访问日志改由我们自己的中间件记（那样才有 req=）
# 保留 WARNING 是因为"HTTP 请求失败"这类还是有价值的信号。
_NOISY = {
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "urllib3": logging.WARNING,
    "uvicorn.access": logging.WARNING,
    "asyncio": logging.WARNING,
    "watchfiles": logging.WARNING,
}


class _Fmt(logging.Formatter):
    """带 req= 的格式。没有 request_id 的日志（启动、定时任务）显示 '-'。"""

    def format(self, record: logging.LogRecord) -> str:
        rid = get_request_id()
        record.req = f"req={rid}" if rid and rid != "-" else "req=----"
        return super().format(record)


def setup(logdir: Path | None = None, level: int = logging.INFO) -> Path | None:
    """装好根 logger。返回日志文件路径（用于打印"日志在哪儿"）。

    · 控制台：给人看的，全量
    · 文件：**按天轮转 + 保留 14 天** —— 排查问题时通常要翻前几天的，
      但没人会去删，所以让程序自己管。单文件超过 8M 也轮转，
      免得一次大批量缓存把单个文件撑到几十 M，`tail` 都卡。
    """
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = _Fmt("%(asctime)s [%(levelname)s] %(req)s %(name)s: %(message)s",
               datefmt="%H:%M:%S")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(level)
    root.addHandler(sh)

    out: Path | None = None
    if logdir:
        try:
            logdir.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.TimedRotatingFileHandler(
                logdir / "app.log", when="midnight", backupCount=14,
                encoding="utf-8", delay=True,
            )
            fh.suffix = "%Y-%m-%d"
            fh.setFormatter(fmt)
            fh.setLevel(level)
            root.addHandler(fh)
            out = logdir / "app.log"
        except Exception as e:  # noqa: BLE001
            print(f"  ! 日志文件装不上（{e}），只走控制台", file=sys.stderr)

    for name, lv in _NOISY.items():
        logging.getLogger(name).setLevel(lv)

    return out


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields) -> None:
    """埋点。event 用「模块.动作」，字段直接写 k=v —— 这样 grep 得动：

        grep 'search.start' logs/app.log
        grep 'cache.fail'   logs/app.log

    字段值里如果有空白，用引号包起来，免得一行日志被切错列。
    """
    if not logger.isEnabledFor(level):
        return
    parts = []
    for k, v in fields.items():
        s = str(v)
        parts.append(f'{k}="{s}"' if (" " in s or "=" in s) else f"{k}={s}")
    logger.log(level, "%s %s", event, " ".join(parts))


# ---------------------------------------------------------------------------
# 埋点事件名登记表 —— 不是为了约束，是为了"口径统一"
# ---------------------------------------------------------------------------
# 同一个动作在两处写不同的事件名（book.add / 入书架），grep 就永远搜不全。
# 这里把已经用到的事件名列出来，新加时照抄风格。
EVENTS = {
    # 搜索链路
    "search.start":      "开始搜索（书名、是否联网）",
    "search.local.hit":  "本地来源命中",
    "search.net.start":  "本地没有，转联网发现",
    "search.done":       "搜索完成（候选数、耗时）",
    "search.fail":       "搜索失败（阶段、原因）",
    # 验证
    "verify.ok":         "某候选验证通过",
    "verify.fail":       "某候选验证失败（原因：超时/无正文/乱码）",
    # 缓存 / 下载
    "cache.start":       "开始缓存章节",
    "cache.done":        "缓存完成（章数、耗时）",
    "cache.fail":        "缓存失败",
    "export.done":       "导出完成（格式、大小）",
    "export.fail":       "导出失败",
    # 阅读
    "read.open":         "打开章节（书、章号）",
    "read.fetch":        "章节取回（来源、耗时）",
    "read.fail":         "章节取不到（书、章、原因）",
    # 来源
    "source.probe":      "探测来源",
    "source.learn":      "学习站点搜索接口",
    "registry.check":    "来源库体检",
    # 适配
    "adapt.start":       "开始适配一个站点",
    "adapt.done":        "适配完成",
    "adapt.fail":        "适配失败",
}
