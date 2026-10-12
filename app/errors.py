"""异常定义。"""
from __future__ import annotations


class Cancelled(Exception):
    """用户主动取消下载。"""


class SourceBlocked(Exception):
    """来源连续多章都抓不到正文 —— 多半是被限流/封 IP 或站点改版了。

    抛出这个异常而不是默默返回空章节，是为了避免「下载完成」却得到一个空文件。
    """
