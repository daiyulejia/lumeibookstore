"""联网发现：本地来源搜不到时，自己出去把书页找回来。

为什么单开一个模块
------------------
来源库再大也是有限的。用户想看的书如果不在库里，之前只能干说「没找到」——
可这本书在百度/Bing 上明明一搜就有。缺的正是「自己出去找」这一步。

引擎怎么选的（都是实测出来的，不是拍脑袋）
------------------------------------------
- **Bing 为主**：结果直接给真实 URL（`<h2><a href="...">`），不用跟随跳转。
  实测搜《药鼎仙途》，第一条就是 `www.29zw.com/info_68516/`。
- **百度为辅**：它的 `mu="真实URL"` 属性能给出部分结果的真实地址。
  但 `www.baidu.com/link?url=` 那条跳转链会 **403**（反爬），所以千万别去跟。
- **只搜纯书名**：实测百度一旦带上「小说 / 全文阅读」这类后缀，
  反爬立刻触发（返回 1KB 空页）。所以后缀一个都不加。

出来的结果只是「书页 URL」，**不是**可用的来源配置 ——
把它变成能读能下载的东西是 `app/webfetch.py` 的事。

名额怎么分（2026-11-04 线上复盘）
--------------------------------
Bing 和百度的返回**质量不一样**，而且是**同一个查询**上不一样：
搜《情欲超市全集》时，Bing 回 10 条「撞词的新闻」
（`女子写淫秽小说被判10年半案`、`四年级女儿洗澡时…`），百度回 7 条真书页
（`m.31xs.com/12/12741/` 能开出 112 章）。

原来的写法把两个引擎的结果**按引擎顺序平铺再截断**，于是这 10 条噪声吃掉了
12 个候选名额里的 9 个，真书页只剩 3 个位置。那晚这 3 个恰好是
「死站 + 一个章节页 + 一个打不开」，核实完 0 命中 —— 日志写 `联网发现=0`，
和"网上真的没有这本书"完全无法区分，用户那边就是"搜不到"。

现在：**每个引擎各自分桶、按组轮转取名次**（bing1、baidu1、bing2、baidu2…），
噪声再多的引擎也只能占走自己那一半名额；引擎内部再按「标题与书名的
二元组重合度」排序，让撞词噪声沉到桶底（是排序，不是门 —— 低分不会被扔掉）。
"""
from __future__ import annotations

import logging
import re
from typing import Callable, Optional
from urllib.parse import urlparse

from .utils import get_client

logger = logging.getLogger("novel.websearch")

# 搜索结果里必然夹带的一堆「不是小说站」的域名。
# 不排掉的话，百度会塞百科 / 知道 / 备案 / 视频站进来。
_NOISE_HOSTS = (
    "baidu.", "bdstatic", "bcebos", "bing.com", "microsoft", "msn.com",
    "live.com", "w3.org", "google", "gstatic", "go.microsoft", "schemas.",
    "office.com", "windows.com", "miit.gov.cn", "mps.gov.cn", "gov.cn",
    "baike.", "zhidao", "zhihu.com", "douban", "bilibili", "iqiyi",
    "weibo", "alicdn", "sogou", "so.com", "360.cn", "sm.cn", "toutiao",
    "douyin", "kuaishou", "baijiahao", "csdn", "jianshu", "163.com",
    "sina.com", "sohu.com", "ifeng.com", "qq.com", "taobao", "jd.com",
    "apple.com", "wikimedia", "wikipedia", "youtube", "twitter", "facebook",
)

# Bing 的结果主链接在 <h2> 里；百度把真实地址放在 mu 属性上
_H2_LINK = re.compile(
    r'<h2[^>]*>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>([\s\S]{0,140}?)</a>', re.I)
_MU_LINK = re.compile(r'mu="(https?://[^"]+)"', re.I)


def _clean_title(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()[:80]


def _is_noise(host: str) -> bool:
    h = host.lower()
    return any(x in h for x in _NOISE_HOSTS)


def _add(out: list[dict], url: str, title: str, engine: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    if not host or _is_noise(host):
        return
    out.append({"url": url, "host": host, "title": title, "engine": engine})


def _overlap(title: str, keyword: str) -> int:
    """标题里有多少个「关键词的二元组」—— 用来判断这条结果到底是这本书、还是撞词。

    ⚠ 为什么不用「包含书名」这种硬判据：书页标题往往**不写全名**
      （《情欲超市全集》的书页标题是「情欲超市 二_吕志王友_在线阅读」），
      硬判会把它也丢掉。二元组重合度是**排序键**，不是门 —— 分数低只是排到后面，
      绝不会被扔掉。

    线上依据（2026-11-04）：Bing 搜「情欲超市全集」返回的 10 条全是
    「女子写淫秽小说被判10年半案」「四年级女儿洗澡时…」这类**撞词的新闻**，
    标题与关键词的二元组重合度是 0；而百度返回的真书页是 3~4。
    """
    kw = re.sub(r"\s+", "", keyword or "")
    if len(kw) < 2:
        return 1 if kw and kw in title else 0
    grams = {kw[i:i + 2] for i in range(len(kw) - 1)}
    t = re.sub(r"\s+", "", title or "")
    return sum(1 for g in grams if g in t)


def _buckets(items: list[dict], *, per_host: int, keyword: str) -> list[list[dict]]:
    """一个引擎的结果 → 按域名分组（每站最多 `per_host` 条），组按「像不像这本书」降序。

    返回的是「组列表」，不是平铺的条目 —— 取的时候按组轮转，
    这样同一个站不会连续占掉好几个名额。
    """
    by_host: dict[str, list[dict]] = {}
    for it in items:
        by_host.setdefault(it["host"], []).append(it)
    groups = [g[:per_host] for g in by_host.values()]
    # 同一引擎内部：先给标题与书名重合度高的站，撞词噪声自然沉底。
    # 稳定排序（sort 是稳定的），重合度相同的保持搜索引擎给的原始名次。
    groups.sort(key=lambda g: -max(_overlap(x.get("title") or "", keyword) for x in g))
    return groups


def _bing(keyword: str) -> list[dict]:
    out: list[dict] = []
    r = get_client().get("https://cn.bing.com/search", params={"q": keyword},
                         headers={"Accept-Language": "zh-CN,zh;q=0.9"})
    if r.status_code != 200:
        return out
    for url, title in _H2_LINK.findall(r.text):
        _add(out, url, _clean_title(title), "bing")
    return out


def _baidu(keyword: str) -> list[dict]:
    out: list[dict] = []
    r = get_client().get("https://www.baidu.com/s", params={"wd": keyword},
                         headers={"Accept-Language": "zh-CN,zh;q=0.9"})
    # 被反爬时会返回一个 1KB 左右的空壳，别当成正常结果
    if r.status_code != 200 or len(r.text) < 5000:
        return out
    for url in _MU_LINK.findall(r.text):
        _add(out, url, "", "baidu")
    return out


def find_book_pages(
    keyword: str,
    *,
    limit: int = 14,
    per_host: int = 2,
    log: Optional[Callable[[str, str, bool], None]] = None,
) -> list[dict]:
    """搜书名 → 候选书页 URL。

    log(标题, 详情, 是否成功)：给流式接口推进度用，回调里抛异常会被吞掉。

    返回里每条是 {url, host, title, engine}，已按域名聚合去重 ——
    同一个站最多留 `per_host` 条，否则一个站能把整个列表刷满。

    ⚠ **名额按引擎轮转，不是先到先得**（2026-11-04 线上复盘，见文件头）。
      原来是把 Bing 的结果全铺在前面、再把百度的接在后面，最后截到 `limit` ——
      于是 Bing 一旦返回一堆「撞词的新闻页」，它就把 12 个名额里的 9 个吃掉，
      百度找回来的真书页只剩 3 个位置。线上《情欲超市全集》那次 12 个候选里
      11 个是新闻站、核实全判「不是目录」，日志只写 `联网发现=0`，
      看起来和"网上真的没有这本书"一模一样。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return []

    def say(title: str, detail: str = "", ok: bool = True) -> None:
        if not log:
            return
        try:
            log(title, detail, ok)
        except Exception:  # noqa: BLE001
            pass

    found: list[dict] = []
    per_engine: list[list[dict]] = []
    names: list[str] = []
    for name, fn in (("Bing", _bing), ("百度", _baidu)):
        names.append(name)
        try:
            got = fn(keyword)
        except Exception as e:  # noqa: BLE001
            say(f"{name} 搜索失败", f"{type(e).__name__}: {str(e)[:50]}", False)
            per_engine.append([])
            continue
        say(f"{name} 搜到结果", f"{len(got)} 条")
        found.extend(got)
        per_engine.append(got)

    # 每个引擎各自分桶，再按「组」轮转取值：bing 第 1 个站、百度第 1 个站、
    # bing 第 2 个站…… 直到凑满 `limit`。噪声再多的引擎也只能占自己那一半。
    buckets = [_buckets(items, per_host=per_host, keyword=keyword)
               for items in per_engine]

    out: list[dict] = []
    # ⚠ `per_host` 是**全局**上限，不是每个引擎各 2 条。两个引擎都返回同一个站
    #   的时候，按引擎各算一次就等于让这个站占 4 个名额 —— 那正是这条限制
    #   当初要防的事（一个站把整个列表刷满）。
    host_n: dict[str, int] = {}
    i = 0
    while len(out) < limit and any(i < len(b) for b in buckets):
        for b in buckets:
            if i < len(b):
                for it in b[i]:
                    if host_n.get(it["host"], 0) >= per_host:
                        continue
                    host_n[it["host"]] = host_n.get(it["host"], 0) + 1
                    out.append(it)
                    if len(out) >= limit:
                        break
            if len(out) >= limit:
                break
        i += 1

    # 「候选是谁给的」必须落进 app.log —— 否则复盘时分不清
    # 「百度一条都没返回」和「百度返回了但被截掉」这两种完全相反的情况。
    # （11-04 那晚就分不清：日志只有 `非目录=11`，且只点了 5 个名字。）
    logger.info("联网候选: 去重前=%d 取=%d 各引擎=%s",
                len(found), len(out[:limit]),
                " ".join(f"{n}={len(e)}" for n, e in zip(names, per_engine)))
    return out[:limit]
