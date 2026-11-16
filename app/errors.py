"""异常定义。"""
from __future__ import annotations


class Cancelled(Exception):
    """用户主动取消下载。"""


class SourceBlocked(Exception):
    """来源连续多章都抓不到正文 —— 多半是被限流/封 IP 或站点改版了。

    抛出这个异常而不是默默返回空章节，是为了避免「下载完成」却得到一个空文件。
    """


class LocalCooldown(RuntimeError):
    """**我们自己**把这个域名拉黑了（限流保护），不是站挂了。

    为什么要专门一个类型（2026-11-16 复盘，线上日志里当场复发的病灶）
    ----------------------------------------------------------------
    `utils.fetch_text` 在同域冷却期内直接抛错不发请求 —— 这是**本地保护**，
    目的是"别再撞了"。但引擎把这个异常当成"源抛异常"：
        source.fail 源=xbqg5200 原因="RuntimeError: 该站点刚被限流，冷却中（还剩 118s）"
        → HEALTH.note_fail() → 连续 3 次 → 熔断 5 分钟
    于是出现一个自噬循环：
        打太快 → 站返回 59 字节空壳 → 我们自限流 120s（对的）
        → 冷却期内每次搜索都被调一次 → 每次都记一次"失败"（错的）
        → 3 次记满，全局熔断 300s，而**冷却只有 120s**
        → 熔断比冷却还长，且 streak+1 → 下次 10 分钟 → 越封越久
    也就是说：一个"只是我们打太快"的站，被我们自己的保护机制判死，
    而且越保护越死。本地实例 2026-11-16 09:51:48 的
    `WARNING 源 xbqg5200 连续失败，熔断 5 分钟` 整条链只有这一行结论。

    正确处置：**跳过，不记挂、不喂熔断器**。它既不该进 `挂=`（那是"源坏了"），
    也不该静默消失（收手可以，不许沉默地收手）—— 所以 `search.done` 里
    单开一格 `自限=`，带名字。

    继承 `RuntimeError` 是为了让所有既有的 `except RuntimeError` 不受影响：
    这个改动只改变**归因**，不改变控制流。
    """

    #: 冷却还剩多少秒（0 = 不知道）
    seconds: float = 0.0
    #: 被冷却的域名（可能为空）
    host: str = ""

    def __init__(self, seconds: float = 0.0, host: str = "") -> None:
        self.seconds = float(seconds or 0.0)
        self.host = host or ""
        left = int(round(self.seconds))
        super().__init__(f"该站点刚被限流，冷却中（还剩 {left}s）")


#: 归因用的文本标记。
#: ⚠ 不能只靠 `isinstance`：很多源把异常**自己吞掉**、只留一句话给
#:   `Source.take_error()`（引擎第 680 行那条路径拿到的就是**字符串**）。
#:   只认类型的话，那条路径会继续把自限流记成"挂"——闸门装在一半入口上。
LOCAL_COOLDOWN_MARK = "该站点刚被限流"


def is_local_cooldown(x: object) -> bool:
    """这次失败是不是"我们自己限流"（而不是源挂了）。

    同时接受异常对象与 `take_error()` 交回来的字符串。
    """
    if isinstance(x, LocalCooldown):
        return True
    return LOCAL_COOLDOWN_MARK in str(x or "")
