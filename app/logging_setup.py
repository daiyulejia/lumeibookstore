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
import time
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


class _SafeTimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """轮转失败**不许把日志打死**的 TimedRotatingFileHandler。

    ⚠⚠ 为什么必须有这个子类（踩过，且是**生产级**的问题）：

    Windows 上 `os.rename(source, dest)` 在**文件被任何进程打开**时会抛
    `PermissionError: [WinError 32]`。而 `TimedRotatingFileHandler.doRollover()`
    的第一步就是 `self.rotate(self.baseFilename, dfn)` —— 于是只要在
    零点轮转的那一刻 `app.log` 还被别的句柄占着（另一个 noveldock 进程、
    编辑器、`tail -f`、上一次没退干净的进程……），轮转就失败。

    失败之后更糟：`logging` 默认把 handler 的异常**吞掉**并打印到 stderr，
    但**该 handler 从此再不写文件**（它已经处于一个坏掉的状态）。
    实测症状：
      · `logs/app.log` 的 mtime 停在轮转前那一刻（例如 23:42），
        之后**所有日志全部丢失** —— 接口照常返回 200，只是什么都不记；
      · `logs/app.log.<今天>` 根本不生成（轮转没成功）；
      · 前端埋点测试全红（"日志里找不到 ui.error"），
        而它会伪装成"埋点钩子坏了" —— 排查方向完全错。
      · 只有**重启进程**才能恢复（重启时 delay=True 会重新开文件）。
    这个坑 2026-10-13 真踩了：日志静默死了近 2 小时才被发现。

    修法：把 `rotate()` 包起来。
      · Linux/macOS 上 rename 不会因"被占用"失败，行为不变；
      · Windows 上失败时**不抛**，而是把当前文件**就地轮转**：
        直接改名成目标名，失败就退化为"**继续往同一个文件追加**"
        （宁可文件不分天，也绝不能把日志丢掉）。
    日志宁可"没切成新文件"，也绝不能"什么都不写"。
    """

    def rotate(self, source, dest):
        try:
            return super().rotate(source, dest)
        except PermissionError:
            # 文件被占用 —— 最常见的就是另一个进程还开着它。
            # 退路：不轮转。继续往原文件写，日志一条都不丢。
            # 为了让运维一眼看出"今天没切成新文件"，往文件里补一行说明。
            try:
                with open(source, "a", encoding="utf-8") as fh:
                    fh.write(
                        f"\n--- [{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                        f"日志轮转被跳过（目标 {Path(dest).name} 被占用）；"
                        f"继续写入当前文件，日志未丢失 ---\n"
                    )
            except Exception:  # noqa: BLE001
                pass
            # 关键：把下次轮转时间往后推，否则**每写一行都会重试一次轮转**
            # （每次失败都写一遍说明行 → 日志被说明行刷满）。
            self.rolloverAt = self.computeRollover(int(time.time()))
        except Exception:  # noqa: BLE001
            # 其它任何轮转异常也不要让 handler 死掉。
            try:
                self.rolloverAt = self.computeRollover(int(time.time()))
            except Exception:  # noqa: BLE001
                pass


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
            # ⚠ 用 _SafeTimedRotatingFileHandler（不是 logging 自带的那个）：
            #   Windows 上轮转若因"文件被占用"失败，自带实现会**静默停写**，
            #   于是日志从此一片空白却毫无提示。见上面那个类的注释。
            fh = _SafeTimedRotatingFileHandler(
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
#
# ⚠ 这张表**必须与实际代码同步**，而且要有测试兜底
#   （见 tools/test_events_registry.py）。原因：
#     ① 登记了却没人发 → 死条目。它比"压根没登记"更坏 ——
#        日志里 grep 不到，看起来像"这条链路没触发"，实际是"根本没埋"。
#     ② 发了却没登记 → 口径漂移。新同学照着表找事件，永远找不到那几个。
#   这两种漂移都不会报错、不会崩，只会让人在线上抓 bug 时白费半天。
#   所以下面分三段：已发的 / 计划中的 / 前端回传的，**别混着写**。
#
# 另一个必须记住的坑：有些事件名**扫不到**，别以为它们没埋 ——
#   ① 带日志级别的调用 `log_event(log, "http", lv, ...)`（lv 是第 3 个位置参数）
#      用 `log_event\([^,]+,\s*"` 这种简单正则能扫到，但若正则写死了两个参数就会漏；
#   ② 真正难扫的是**变量拼名**（f"cache.{act}"）。本仓库目前没有这种写法，
#      但一旦引入，任何静态扫描都会漏 —— 那时测试会假红，记得回来看这段。
# 所以本次同步用的判据是「逐个 grep 调用点」，不是纯正则。
# ---------------------------------------------------------------------------
EVENTS = {
    # ---- A. 后端已发（改这些名字前先 grep 一遍调用点） ----
    # 搜索链路
    "search.start":      "开始搜索（书名、是否联网）",
    "search.done":       "搜索完成（候选数、**确切命中数**、耗时）",
    "search.fail":       "搜索失败（阶段、原因）",
    "search.rank":       "相关性排序完成（原始数 → 去噪后）",
    # 只有上一条无法复盘「这本书为什么搜不到」：`原始=14 去噪后=2` 说不出
    # 那 12 条是什么、为什么被丢。这条把账目摊开：门槛多少、最高分多少、
    # 多少条"低于门槛"（多为站点返回的别的书）、多少条"非确切命中被挤掉"
    # （多为规则太狠），并举例标题。两类处置相反，必须分开数。
    "search.rank.drop":  "候选被筛掉的明细（门槛、两类丢弃数、示例标题）",
    "search.web.preempt": "本地太慢，提前起联网兜底（已等秒数）",
    # 来源 / 网络
    "source.fail":       "某个来源抛异常（站点抽风/改版/拦爬虫，不升级为搜索失败）",
    "http":              "HTTP 请求（方法、状态、耗时）",
    "http.asset":        "静态资源请求",
    # 验证
    "verify.ok":         "某候选验证通过",
    "verify.fail":       "某候选验证失败（原因：超时/无正文/乱码）",
    # 缓存 / 下载
    "cache.start":       "开始缓存章节",
    "cache.done":        "缓存完成（章数、耗时）",
    "cache.fail":        "缓存失败",
    "cache.cancel":      "缓存被取消（用户点了停止）",
    # 导出
    "export.start":      "开始导出",
    "export.done":       "导出完成（格式、大小）",
    "export.fail":       "导出失败",
    "export.cancel":     "导出被取消",
    # 阅读
    "read.fetch":        "章节取回（来源、耗时）",
    "read.fail":         "章节取不到（书、章、原因）",
    # 来源库自愈（读库时静默清理影视站/非小说站 —— 留痕才查得动）
    "registry.scrub":    "来源库自愈：判死了多少站（影视/非小说分类计数）",
    # 封面代理（/api/cover）。封面是"锦上添花"的装饰 —— 挂了不该影响
    # 任何功能，但必须留痕，否则会表现成"有的书有图有的没图"没法查。
    "cover.blocked":     "封面地址被安全策略拦下（SSRF 防护）",
    "cover.fail":        "封面取不到（防盗链/不是图片/超时）",
    # 搜索历史 / 访客记录（见 app/history.py、app/visits.py）
    "history.del":       "删除一个搜索词",
    "history.clear":     "清空搜索历史（删掉的条数）",
    "history.load.fail": "搜索历史落盘文件损坏（当空库继续跑）",
    "history.save.fail": "搜索历史写盘失败（不影响搜索本身）",
    "visits.clear":      "清空访客数据（删掉的天数）",
    "visits.load.fail":  "访客记录落盘文件损坏（当空库继续跑）",
    "visits.save.fail":  "访客记录写盘失败（不影响访问本身）",
    "visits.record.fail": "访客记录本条目写入抛异常（已吞掉，不影响请求）",
    # 榜单定时刷新（/api/ranks/refresh）。⚠ 定时任务由 systemd 打进来，
    # curl 的输出没人看 —— 所以"这次刷新到底哪几类没跑完"只能靠这条日志。
    # 起因：2026-10-22 11:02 那次刷新用了 25.0 秒（正好撞满预算），
    # 日志里只有一行 `ms="25006 慢"`，事后查不出是哪几类被收手。
    "ranks.refresh":     "榜单刷新结果（成功/失败/没跑完的类目、耗时）",
    # 学站 + 模板复核（POST /api/registry/learn）。⚠ 这条原来登记在"计划中"，
    # 而功能其实早就实现了 —— 于是表上是死条目、代码里一行都没埋。
    # 后果在线上很具体：2026-10-22 那几条请求分别是 168.7s / 209.8s / 211.7s，
    # 日志里只有 `ms="211711 慢"`，查不出学了几家、复核撤掉几家、有没有跑完。
    "source.learn":      "学站内搜索接口 + 复核假模板（学会/撤掉/没结论/没跑完/耗时）",

    # ---- B. 计划中（**目前无人发**，登记是为了定口径，别当成已实现）----
    # 这一段整个属于「L 源闭环」需求：自有源 → 联网搜索 → 探测 →
    # 爬取成功则收录；以及定期排查坏源。功能还没落地，埋点先占位。
    # ⚠ 测试 test_events_registry.py 会校验这一段**确实还没人发**；
    # 等哪天实现了、开始发了，就要把条目搬到 A 段，否则测试会提醒你。
    "search.local.hit":  "[计划] 本地来源命中（不用联网）",
    "search.net.start":  "[计划] 本地没有，转联网发现",
    "read.open":         "[计划] 打开章节（书、章号）—— 前端还没回传",
    "source.probe":      "[计划] 探测一个来源是否可用",
    "registry.check":    "[计划] 来源库体检（排查坏源）",
    "adapt.start":       "[计划] 开始适配一个站点",
    "adapt.done":        "[计划] 适配完成",
    "adapt.fail":        "[计划] 适配失败",

    # ---- C. 前端回传（浏览器里发生的，经 /api/log 到服务端）----
    # 为什么前端也要埋点：后端日志再全，也照不到"点了没反应""页面白屏"
    # 这类只发生在用户浏览器里的问题 —— 那正是用户最容易来报的 bug。
    "ui.error":          "JS 运行时错误（含堆栈）",
    "ui.reject":         "未处理的 Promise 拒绝",
    "ui.api.fail":       "接口失败（路径、状态码、耗时）",
    "ui.slow":           "接口慢（超过阈值）",
}
