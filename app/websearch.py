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
import time
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


class EngineBlocked(RuntimeError):
    """搜索引擎**拒绝了我们**（反爬验证页 / 异常空壳）—— 不是"没有结果"。

    ⚠ 这个异常存在的唯一理由，是让这两件事在日志里分开（2026-11-19）：
      之前 `_baidu` 在拿到「百度安全验证」2.6KB 页面时和"一条都没搜到"
      **返回同一个 `[]`**，全链路只有聚合行 `百度=0`。
      复盘时它读起来就是"百度没结果"，而事实是"百度整个引擎不可用" ——
      一边是少一半候选，一边是"这本书网上没有"，处置完全相反。
      而百度是 discovery 的两个引擎之一：它一死，冷门书的候选供给
      从 6~10 条掉到 1~2 条，用户在界面上看到的还是"搜不到"。
    """


# 被拒之后**短期不再试**。理由不是省流量（一个搜索才多一个请求），
# 而是"越打越死"：同一个 IP 连续被判定为机器人，冷却只会越来越长。
# 更要紧的是：冷却期内的调用**不发请求**，也就不会把"被拦"重复写进日志，
# 一天几百次搜索不会刷出几百行同一件事。
BAIDU_BLOCK_COOLDOWN = 600.0
_baidu_blocked_until = 0.0

# 百度反爬页的指纹。都是实测见过的（2026-11-19 本机）：
#   ① HTTP 200 + 2649 字节，标题「百度安全验证」；
#   ② HTTP 302 直接跳 wappass 验证域（跟随重定向后仍是 ①）。
_BAIDU_WALL_MARKS = ("百度安全验证", "wappass.baidu.com", "请输入验证码")

# 「页面里出现这几个词」本身不足以定罪 —— 搜索结果里就可能有用户帖子写着
# 「请输入验证码」。真正的验证页**同时**很小（实测 2649 字节，正常结果页
# 40~100KB）。所以两条一起看：带指纹 **且** 明显不是结果页的体量。
_BAIDU_WALL_MAX = 20000


def _baidu(keyword: str) -> list[dict]:
    global _baidu_blocked_until
    now = time.time()
    if now < _baidu_blocked_until:
        raise EngineBlocked(
            f"冷却中（{int(_baidu_blocked_until - now)}s 后再试）")
    out: list[dict] = []
    r = get_client().get("https://www.baidu.com/s", params={"wd": keyword},
                         headers={"Accept-Language": "zh-CN,zh;q=0.9"})
    body = r.text or ""
    wall = any(m in str(r.url) for m in _BAIDU_WALL_MARKS) or (
        len(body) < _BAIDU_WALL_MAX
        and any(m in body for m in _BAIDU_WALL_MARKS))
    if wall:
        _baidu_blocked_until = now + BAIDU_BLOCK_COOLDOWN
        logger.info("百度拒绝了我们（HTTP %s / 验证页 %d 字节），%.0f 分钟内不再试",
                    r.status_code, len(body), BAIDU_BLOCK_COOLDOWN / 60)
        raise EngineBlocked(f"被反爬（HTTP {r.status_code}，{len(body)} 字节验证页）")
    if r.status_code != 200:
        raise EngineBlocked(f"HTTP {r.status_code}")
    # 正常结果页是几十上百 KB。1~5KB 的壳子既不是结果页、也不带验证字样，
    # 但**同样不是"没有这本书"** —— 一律当异常，别伪装成空结果。
    if len(body) < 5000:
        raise EngineBlocked(f"返回异常页（{len(body)} 字节，不是结果页）")
    for url in _MU_LINK.findall(body):
        _add(out, url, "", "baidu")
    return out


# 第一轮候选少于这个数，就**换一种问法再问一次**（2026-11-19）。
#
# 为什么（今天量出来的，不是猜的）：
#   搜《遥远的救世主》，Bing 用书名当查询只捞出 1 个可用站（youyiyan），
#   百度又整个被反爬（见 `EngineBlocked`）→ 3 个候选、全是"不是目录" → `候选=0`。
#   同一个 Bing 换成「遥远的救世主 小说」再问一次，第一屏就出现
#   fanqienovel.com，实抓 **33 章**、可读。一本书从"搜不到"变成"能读"，
#   代价只是多一个请求。
#
#   《我的阿勒泰》同理：书名单独搜只给 1 个可读站（maiguiread，且它只有简介），
#   加「小说」后多出 qidian / tianyabooks / zishiba 三个书站 —— 今天它们
#   都连不上，但这说明"多问一句"换来的是真书站，不是噪声。
#
# 为什么设门槛而不是每次都问两次：
#   候选够多（>= 4）时第二轮只是在给核实阶段喂噪声，而核实是这条链上最贵的
#   资源（每个候选要开一次页、10s 上限）。只有"快没得核实了"才值得多问。
SECOND_QUERY_MIN = 4
SECOND_QUERY_SUFFIX = " 小说"


def _ask(keyword: str, say) -> tuple[list[dict], list[list[dict]], list[str]]:
    """问一遍所有引擎，返回 (全部结果, 每个引擎的结果, 引擎名)。

    ⚠ 引擎函数名必须在这里**按全局名解析**（`_bing` / `_baidu` 写在元组里
      而不是先取成局部变量），否则 `tools/test_websearch.py` 把它们换桩以后
      这里还在调真的 —— 测试会去打真站点。
    """
    found: list[dict] = []
    per_engine: list[list[dict]] = []
    names: list[str] = []
    for name, fn in (("Bing", _bing), ("百度", _baidu)):
        names.append(name)
        try:
            got = fn(keyword)
        except Exception as e:  # noqa: BLE001
            # `EngineBlocked` 落在这里：日志里必须看得出"这个引擎没给我们东西，
            # 而且是因为它拦了我们"，否则 `百度=0` 与"百度没这本书"同形。
            say(f"{name} 搜索失败", f"{type(e).__name__}: {str(e)[:60]}", False)
            per_engine.append([])
            continue
        say(f"{name} 搜到结果", f"{len(got)} 条")
        found.extend(got)
        per_engine.append(got)
    return found, per_engine, names


def _pick(per_engine: list[list[dict]], *, keyword: str, per_host: int, limit: int,
          out: list[dict], host_n: dict[str, int], seen: set[str]) -> None:
    """按「组」轮转把候选填进 `out`（原地追加）。

    每个引擎各自分桶，再按「组」轮转取值：bing 第 1 个站、百度第 1 个站、
    bing 第 2 个站…… 直到凑满 `limit`。噪声再多的引擎也只能占自己那一半。

    `out` / `host_n` / `seen` 由调用方持有：第二轮要接着第一轮的名额和去重，
    不能自己重新数一遍（否则同一个站能靠两次问法占走两倍名额）。
    """
    buckets = [_buckets(items, per_host=per_host, keyword=keyword)
               for items in per_engine]
    i = 0
    while len(out) < limit and any(i < len(b) for b in buckets):
        for b in buckets:
            if i < len(b):
                for it in b[i]:
                    if it["url"] in seen:
                        continue
                    if host_n.get(it["host"], 0) >= per_host:
                        continue
                    host_n[it["host"]] = host_n.get(it["host"], 0) + 1
                    seen.add(it["url"])
                    out.append(it)
                    if len(out) >= limit:
                        break
            if len(out) >= limit:
                break
        i += 1


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

    ⚠ **候选太薄时要换一种问法再问一次**（2026-11-19，见 `SECOND_QUERY_MIN`）。
      两个引擎里死一个（百度反爬）、另一个只认书名时，第一轮就只有 1~2 条候选，
      后面核实再准也没用 —— 那不是"网上没有这本书"，是**我们只问了一句**。
      门槛只看第一轮的候选条数（纯计数，不碰耗时），够多就不问。
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

    found, per_engine, names = _ask(keyword, say)

    out: list[dict] = []
    # ⚠ `per_host` 是**全局**上限，不是每个引擎各 2 条。两个引擎都返回同一个站
    #   的时候，按引擎各算一次就等于让这个站占 4 个名额 —— 那正是这条限制
    #   当初要防的事（一个站把整个列表刷满）。
    host_n: dict[str, int] = {}
    seen: set[str] = set()
    _pick(per_engine, keyword=keyword, per_host=per_host, limit=limit,
          out=out, host_n=host_n, seen=seen)
    first_n = len(out)

    # 「候选是谁给的」必须落进 app.log —— 否则复盘时分不清
    # 「百度一条都没返回」和「百度返回了但被截掉」这两种完全相反的情况。
    # （11-04 那晚就分不清：日志只有 `非目录=11`，且只点了 5 个名字。）
    logger.info("联网候选: 去重前=%d 取=%d 各引擎=%s",
                len(found), first_n,
                " ".join(f"{n}={len(e)}" for n, e in zip(names, per_engine)))

    if first_n < SECOND_QUERY_MIN:
        query2 = keyword + SECOND_QUERY_SUFFIX
        say("换一种说法再搜", f"第一轮只有 {first_n} 条，加问「{query2}」")
        found2, per_engine2, names2 = _ask(query2, say)
        _pick(per_engine2, keyword=keyword, per_host=per_host, limit=limit,
              out=out, host_n=host_n, seen=seen)
        logger.info("联网候选（第二次问法）: 第一轮=%d 加问=《%s》 新增=%d 合计=%d",
                    first_n, query2, len(out) - first_n, len(out))

    return out[:limit]

