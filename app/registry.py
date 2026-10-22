"""来源库：把「联网发现」找到的站点和书攒起来，越用越大。

为什么要单独存一份
------------------
搜索引擎每次都能重新找一遍，但那意味着**每次搜书都要联网、要解析、
要赌一次**。把找到的结果记下来之后：

  · 下次搜同一本书 → 秒出，不用再走搜索引擎
  · 同一个站第二次抓 → 直接用它上次的容器名，不用重新猜
  · 攒久了能做健康筛选 → 把死站清掉，让本地命中率越来越高

这正是「不断壮大、后续定期筛选」要的东西。

存哪、存什么
------------
`cache/registry.json`::

    {
      "sites": {
        "www.29zw.com": {
          "name": "29中文小说网",
          "toc_hint": "",             # 学到的目录容器名
          "content_hint": "htmlcontent",
          "ok": 12, "fail": 0,        # 成功/失败计数
          "last_ok": 1760000000,
          "first_seen": 1759900000,
          "updated": 1760000000
        }
      },
      "books": {
        "https://www.29zw.com/info_68516/": {
          "title": "药鼎仙途", "author": "寒香寂寞",
          "host": "www.29zw.com",
          "chapters": 4543,
          "ok": 3, "fail": 0,
          "last_ok": 1760000000,
          "last_check": 1760000000
        }
      }
    }

并发
----
搜索池 + 探测池会同时写这个文件，所以：
  · 一把进程内锁保证读改写是原子的
  · 写盘用「临时文件 + os.replace」，避免读到半个 JSON
  · 内存里缓存一份，只有内容真的变了才落盘
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("novel.registry")

_ROOT = Path(__file__).resolve().parent.parent
# 库文件的落点。`NOVEL_REGISTRY` 可以让测试 / 命令行工具用另一份，
# 免得跑一次测试就把生产库里攒的站点洗掉（真踩过，见 README「来源库」一节）。
_DB = Path(os.environ.get("NOVEL_REGISTRY") or (_ROOT / "cache" / "registry.json"))

_lock = threading.RLock()
_cache: Optional[dict] = None
_dirty = False
_last_save = 0.0

# 被删掉的键。合并写盘时靠它把「删除」这个意图表达出来 ——
# 单纯取并集会把删掉的键又捞回来。
_tomb: dict[str, set[str]] = {"sites": set(), "books": set()}

# 落盘节流：来源库一次联网会写好几次，但每次写盘都是「读改写一个 JSON」。
# 网络请求本身就 100ms 起，所以每秒最多写一次完全不影响写入及时性，
# 又能避免并发核实 6 个站时把同一个文件来回覆盖 6 遍。
SAVE_MIN_INTERVAL = 1.0

# 站点「不健康」的判定门槛：成功过 0 次、失败 ≥ 3 次
UNHEALTHY_FAILS = 3

# 「模板打开的根本不是搜索结果页」—— 连续几次、且从没搜出过东西，就作废这个模板。
#
# ⚠ 这条修的是「可搜源数量是虚的」（2026-10-22 线上实测）。
#   当时 `searchable_sites()` 报 15 个，逐个拿同一个关键词去搜，**7 个一条
#   书链接都抽不出来**，而且是**确定性的**（换成别的关键词、换成它自己站上
#   有的书名，一样 0 条）：
#     · `www.xizids.com` / `www.itiandixs.com`  POST 落回「小说搜索_首页」——
#       参数名不对，站根本没执行搜索
#     · `fanqienovel.com`                       前端渲染的 SPA，HTML 里没有书链接
#     · `www.biquhui.vip`                       把 `?s=` 吞掉、直接回首页
#     · `m.kudushu.org`                         403（拦爬虫）
#     · `www.guazimanhua.com`                   漫画站，本来就不该在这份名单里
#     · `wap.jjwxc.net`                         编码错 → 标题是乱码，全被过滤
#   这和以前「界面说能搜 6 个、实际只问 3 个」是同一类病：**数字不代表能力**。
#   修法：搜索时如实记「抽出几条链接」——
#     · 抽出 0 条      → 这不是搜索页（`search_shape` +1）
#     · 抽出 N 条但全被过滤 → 这才是"站里没这本书"（`search_miss` +1，永不淘汰）
#   连续 `SEARCH_SHAPE_MAX` 次"不是搜索页"且**从来没搜出过东西** → 作废模板、
#   记一次学站失败，让它用修好的学习器重学。重学仍不行就由
#   `SEARCH_LEARN_MAX_TRIES` 自然放弃 —— 有终点，不会每晚白查。
SEARCH_SHAPE_MAX = 3

# 失败原因分类 —— 传给 `note_site(..., why=...)`。
# 为什么必须分类：`fail` 是个混装桶，"站点真的连不上"和"我们 URL 猜错了"
# 都只让它 +1。于是 is_healthy 的比值判据会把猜错路径算成"这个站不行"，
# 好站被慢慢判死；而真挂掉的站如果历史成功多，比值也压不下去。
# 分类之后「定期排查坏源」才能只盯 FAIL_DOWN 那一类（见 FAIL_WHY_* 命名）。
FAIL_DOWN = "down"      # 网络层失败：连不上/5xx —— 站点可能真的挂了
FAIL_EMPTY = "empty"    # 打开了但没内容：模板能开、搜不出（多半改版了）
FAIL_SHAPE = "shape"    # 打开了但不是章节目录：URL 猜错 / 页面形态不符
FAIL_VIDEO = "video"    # 判为影视站（剧集列表冒充章节目录）—— 主动否决，非故障
FAIL_GATED = "gated"    # 正文要登录 / 靠 JS 渲染，只拿到一屏控件 —— 不是挂了
# 「我们给的时间不够」—— 和「站点挂了」必须分开（2026-10-22 补）。
#   扇出时单站只给 3.5 秒（`SEARCH_SITE_TIMEOUT`），慢站必然超时；
#   而超时原先一律记成 FAIL_DOWN「网络层失败」，`is_healthy` 的
#   `down >= 3 and down > ok*2` 就把它往死里推。
#   线上实测 `350.ooo`：ok=35 / fail_down=**70** —— 刚好卡在 `70 > 70` 不成立
#   的临界点上，**再超时一次就判死**，然后悄悄从可搜源里消失。
#   而它其实只是慢：同一轮里它照样能返回结果。所以超时单独一类，不算站故障。
FAIL_SLOW = "slow"      # 超时（我们给的时间太短）—— 不是站点故障
FAIL_WHY_ALL = (FAIL_DOWN, FAIL_EMPTY, FAIL_SHAPE, FAIL_VIDEO, FAIL_GATED,
                FAIL_SLOW)

# 哪些原因**不该**算作「这个站挂了」。
# is_healthy 目前仍是旧的"总 fail"判据（纯增量改动，先不动线上行为），
# 但「定期排查坏源」要按这份名单算：只有 DOWN 才说明站点真出问题了，
# 其余几类都在说"这次抓法不对 / 我们给的时间不够"，站点本身可能是好的。
FAIL_WHY_SITE_FAULT = (FAIL_DOWN,)

# 写盘前的「缩水护栏」：盘上至少这么多条、且新内容不到原来一半时，先留一份备份。
SHRINK_GUARD_MIN = 5
SHRINK_GUARD_RATIO = 0.5

# 影视站的路径特征（和 webfetch._VIDEO_PATH_RE 同一套词表）。
# 为什么来源库这里也要判：库里的站点是**踩着历史成功记录**走缓存命中的，
# 根本不会再走一遍 `analyze()` —— 所以 webfetch 里新加的否决拦不到**已经
# 学坏了的**条目。实测：`hbsjob.cn`（首播网）ok=4 蹲在库里，搜「余华 活着」
# 时直接命中缓存，把一部韩国丧尸片的剧集列表当成《活着》的章节目录端出来。
# 所以读数时要顺手清一遍 —— 这叫「自愈」，不然脏数据永远洗不掉。
_VIDEO_PATH_RE = re.compile(
    r"/(?:vod(?:detail|play|type|show|search|list)?|show|play|detail|"
    r"movie|film|dianshiju|dongman|zongyi|variety)(?:/|$|\?|\.html)",
    re.I,
)


def _is_video_site(host: str, site: dict) -> bool:
    """这个站点条目是不是影视站（该被剔除）。"""
    tpl = str(site.get("toc_tpl") or "")
    if tpl and _VIDEO_PATH_RE.search("/" + tpl.lstrip("/")):
        return True
    name = str(site.get("name") or "")
    # 站名判据要**同时**有影视特征词和「章节数偏多且不像章」才成立，
    # 但站名能骗人的地方多（轻小说站自称「动漫」），所以这里只认最硬的
    # 「影视/电影/影院/剧场/追剧」——不含「动漫」（动漫是合法小说分类）。
    if re.search(r"影视|电影|影院|剧场|追剧|播放器", name):
        return True
    return False


def _is_video_book(url: str) -> bool:
    """这本书的地址是不是影视站的详情页。"""
    try:
        p = urlparse(url).path or ""
    except Exception:  # noqa: BLE001
        p = url or ""
    return bool(_VIDEO_PATH_RE.search(p))


# ---------------------------------------------------------------------------
# 非小说站（教程/词典/博客/商城/文档站…）
# ---------------------------------------------------------------------------
# 为什么也要在来源库里判 —— 和影视站同一个道理，而且更隐蔽：
#   这些站**不是坏站**，它们健康得很（菜鸟教程 ok=35、MDN ok=13），
#   所以 `is_healthy` 永远放行；它们的页面也确实有"正文"，于是
#   `analyze()` 会给它们学一个 `content_hint`，看起来完全正常。
#   但用户搜的是小说，这些站永远不可能给出小说 —— 它们只会：
#     · 占着搜索结果的位子（把真小说站挤下去）
#     · 拖慢探测（每个候选都要真打一次）
#   实测：178 个站里有 22 个是这类（12%），包括菜鸟教程、爱词霸、MDN、
#   博客园、小红书、森海塞尔商城…全是「搜索引擎顺手给的通用结果」。
#
# 判据只用**站名里的强特征词**：宁可漏判也不能误杀 ——
#   小说站起名很花（"XX书屋"、"XX阅读"、"XX阁"），任何"像不像小说站"
#   的正面判据都会误杀；反过来，"教程/词典/商城"这类词几乎没有小说站会用。
_OFFTOPIC_NAME_RE = re.compile(
    r"教程|词典|辞典|翻译|文档|百科|问答|社区|论坛|博客|Blog|Docs|"
    r"商城|购物|旗舰店|官方网站|招聘|课程|教育|培训|"
    r"软件|源码|下载站|图库|素材|安全资讯|"
    # ⚠ 2026-10-22 线上实测补的一类：**漫画 / 音乐 / 影视**站。
    #   它们和教程站一样"合法混进来"—— 健康、有正文、分析得出一堆字段，
    #   但用户搜的是小说，它们永远给不出。实测被这类放过的：
    #   guazimanhua（漫画）、doubaomanhua、manhuazhan、5nd.com、kugou（音乐）。
    #   拿线上 178 站全量预演过：这批词**零误杀**（真小说站名一个都不命中）。
    #
    # ⚠⚠ **"动漫"绝对不能进这张表。** 「XX动漫」是轻小说站常见的自称
    #   （哔哩轻小说、轻之文库那一类），加进去等于把真小说站清掉 ——
    #   tools/test_offtopic.py 第 3 节专门守着这条。
    r"漫画|漫畫|音乐|音樂|影视|电影|剧集|视频|壁纸|写真|"
    r"Wiki|GitHub|Stack|MDN",
    re.I,
)
# 少数"通用大站"没有明显中文特征词，但显然不是小说站，单独列白名单拦掉。
_OFFTOPIC_HOST_RE = re.compile(
    r"^(?:github\.com|developer\.mozilla\.org|stackoverflow\.com|"
    r"zhihu\.com|baidu\.com|youtube\.com|wikipedia\.org|"
    r"bilibili\.com|csdn\.net|juejin\.cn|cnblogs\.com)$",
    re.I,
)
# 主机名里就能看出用途的（工具站 / 文档站 / SaaS）。
# 为什么用 host 而不是 name：这些站的 name 往往是空的（爬不到 og:site_name），
# 只剩 host 可判 —— 实测 svgtool.cn / svgview.com / kancloud.cn 都是这样。
_OFFTOPIC_HOST_SUB_RE = re.compile(
    r"(?:^|\.)(?:svgtool|svgview|svg-gen|kancloud|motionsites|"
    r"seowebchecker|scriptcat|runoob|iciba)\.|"
    r"^cloud\.tencent\.com$|^docs\.|^wiki\.",
    re.I,
)


def _is_offtopic_site(host: str, site: dict) -> bool:
    """这个站点条目是不是「非小说站」（该被剔除）。"""
    h = (host or "").strip().lower()
    if _OFFTOPIC_HOST_RE.match(h) or _OFFTOPIC_HOST_SUB_RE.search(h):
        return True
    return bool(_OFFTOPIC_NAME_RE.search(str(site.get("name") or "")))



def _scrub(db: dict) -> int:
    """把库里识别为影视站 / 非小说站的条目判死（自愈）。返回清理条数。

    **不移除条目**，只把 `ok` 归零、打上 `fail` 计数和原因 ——
    这样：
      · `is_healthy()` 会否掉它，不再被当候选（达到目的）
      · 记录还在，排查时能看到"这个站曾经被学过、后被判定为影视站"
      · 万一判错了（比如某个小说站的路径恰好含 /show/），
        后续真实访问成功会重新累加 `ok`，能自己爬回来
    """
    n = 0
    for host, site in list((db.get("sites") or {}).items()):
        if not isinstance(site, dict):
            continue
        if site.get("video_blocked"):
            continue
        if _is_video_site(host, site):
            site["ok"] = 0
            site["fail"] = max(int(site.get("fail") or 0), UNHEALTHY_FAILS)
            site["video_blocked"] = 1
            site["blocked_why"] = "影视站（路径/站名特征）"
            n += 1
            continue
        # 非小说站（教程/词典/博客/商城/文档站…）。
        # 用独立的 `offtopic_blocked` 旗标而不是复用 video_blocked ——
        # 两者原因不同，排查时要能分辨；`is_healthy()` 只看 ok/fail，
        # 所以两种旗标都能达成效力，旗标只影响可读性。
        if site.get("offtopic_blocked"):
            continue
        if _is_offtopic_site(host, site):
            site["ok"] = 0
            site["fail"] = max(int(site.get("fail") or 0), UNHEALTHY_FAILS)
            site["offtopic_blocked"] = 1
            site["blocked_why"] = "非小说站（教程/词典/博客/商城等特征）"
            n += 1
    for url, b in list((db.get("books") or {}).items()):
        if not isinstance(b, dict):
            continue
        if b.get("video_blocked"):
            continue
        if _is_video_book(url):
            b["ok"] = 0
            b["fail"] = max(int(b.get("fail") or 0), UNHEALTHY_FAILS)
            b["video_blocked"] = 1
            b["blocked_why"] = "影视站（路径特征）"
            n += 1
    return n


def _scrub_kwless(db: dict) -> int:
    """清掉「带不了关键词」的搜索模板（自愈）。返回清理条数。

    为什么必须清（2026-10-21 线上实测）：
      14 个「可搜源」里有 6 个的模板是 `/search.php` `/search` `/search.html`
      这类**不带 `{kw}` 占位**的裸路径。`build_url()` 只做 `{kw}` 替换，
      没有占位就等于关键词没发出去 —— 打开的是站点的搜索页/首页，
      那一页本来就有一堆书，于是验证时"链接数够多"判真、控制实验也判不了假
      （换任何词打开的都是同一页，只是动态链接略有不同）。

      它们每次搜索都白占预算（14 站 / 6 并发 / 单站 8s 超时 / 总预算 7s，
      结构上必然超时），把真能搜的站挤到收手之后 —— 这是「热门书也搜不到」
      的一大半原因。

    清掉之后**站不会丢**：它只是回到「还没学会搜索」的状态，
    下一轮学站会重新爆破（线上 384g 的正确模板是 `POST /search.php`，
    旧的那份是 GET 裸路径）。所以顺便把失败账也清零，别让旧账挡住重学。

    ⚠ 必须写 `""` 而不是 `pop`：落盘走 `_merge()` 逐键覆盖，
      内存里没有的键会从盘上**复活**（这个坑踩过一次，见 clear_search_tpl）。
    """
    from .sitelearn import tpl_carries_kw

    n = 0
    for host, site in list((db.get("sites") or {}).items()):
        if not isinstance(site, dict):
            continue
        tpl = (site.get("search_tpl") or "").strip()
        if not tpl:
            continue
        if tpl_carries_kw(tpl, method=(site.get("search_method") or "get"),
                          body=site.get("search_body")):
            continue
        site["search_tpl"] = ""
        site["search_enc"] = ""
        site["search_body"] = {}
        site["search_method"] = ""
        site["search_ver"] = 0
        site["search_fail"] = 0        # 旧模板的失败不该挡住重学
        site["search_fail_ver"] = 0
        # ⚠ 必须把 `updated` 推到**比原来更新**：`_merge()` 合并同名条目时
        #   按 updated 比新旧，不同步这个时间戳，盘上那份（模板还在）会赢，
        #   于是这次清理在落盘时被静默丢弃 —— 下次启动模板又回来了。
        #   也不能只写 `_now()`：盘上那份可能刚被别的进程（命令行工具）更新过，
        #   时间戳比"现在"还新，同秒比较也会让它赢。所以取两者较大值 +1。
        # ⚠ `updated` 推到比原来更新是**防御性**写法：`_merge()` 合并同名条目
        #   时按 updated 比新旧，不推就可能让盘上那份（模板还在）赢。
        #   诚实说明：实测这条**单独破坏不会出事** —— 因为 `_read_disk()` 里
        #   同样跑 `_scrub_and_log()`，落盘前盘上那份已经被清过一遍了。
        #   两处互为兜底，所以这里也不配一条单独的突变（它测不出来），
        #   行为判据在 tools/test_registry.py「清理结果真落了盘」。
        #   取两者较大值 +1 而不是只写 `_now()`：盘上那份可能刚被别的进程
        #   （命令行工具）更新过，时间戳比"现在"还新。
        site["updated"] = max(_now(), int(site.get("updated") or 0) + 1)
        logger.info("清掉带不了关键词的搜索模板（站回到重学队列）：%s %s", host, tpl)
        n += 1
    return n


def _scrub_and_log(db: dict) -> None:
    """跑自愈并**留一条日志**（原先是静默的）。

    为什么要留痕：自愈会在**读库时**悄悄把条目判死（ok 归零）。
    静默的话，用户看到"这个站怎么突然不出现了"，翻日志却什么都找不到 ——
    正是需求里说的"方便线上拉日志定位问题"要解决的问题。
    另外记录**分类数量**（影视站 vs 非小说站），
    这样线上能一眼看出"库里垃圾是哪种更多"。

    异常仍然吞掉（不能因为自愈失败就整个读库失败），但降级为 warning 留痕。
    """
    try:
        n_kw = _scrub_kwless(db)
        n = _scrub(db)
    except Exception as e:  # noqa: BLE001
        try:
            from .logging_setup import get_logger
            get_logger("novel.registry").warning("来源库自愈失败（已忽略）：%s", e)
        except Exception:  # noqa: BLE001
            pass
        return
    if n or n_kw:
        # 清模板是**写操作**（`_scrub` 原来只改内存、靠后续写入顺带落盘，
        # 但清模板不会伴随任何写入，不主动置脏就等于重启后又回来）。
        #
        # ⚠ 这里**不能**直接 `_maybe_save()`：本函数是在 `_load()` 里被调的，
        #   那时 `_cache` 还没赋值，`_save()` 的 `_merge(disk, _cache or _empty())`
        #   会拿空库去合并 —— 写回去等于什么都没改（清模板白清）。
        #   置脏就够了：下一次真实写入或进程退出时的 `flush()` 会带上。
        global _dirty
        _dirty = True
    if not n:
        if n_kw:
            try:
                from .logging_setup import get_logger, log_event
                log_event(get_logger("novel.registry"), "registry.scrub",
                          新判死=0, 影视站=0, 非小说站=0, 空模板=n_kw)
            except Exception:  # noqa: BLE001
                pass
        return
    try:
        from .logging_setup import get_logger, log_event
        blocked = (db.get("sites") or {}).values()
        video = sum(1 for s in blocked if isinstance(s, dict) and s.get("video_blocked"))
        off = sum(1 for s in blocked if isinstance(s, dict) and s.get("offtopic_blocked"))
        log_event(get_logger("novel.registry"), "registry.scrub",
                  新判死=n, 影视站=video, 非小说站=off, 空模板=n_kw)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# 读 / 写
# ---------------------------------------------------------------------------
def _empty() -> dict:
    return {"sites": {}, "books": {}}


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    try:
        raw = json.loads(_DB.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except Exception:  # noqa: BLE001
        raw = {}
    raw.setdefault("sites", {})
    raw.setdefault("books", {})
    if not isinstance(raw["sites"], dict):
        raw["sites"] = {}
    if not isinstance(raw["books"], dict):
        raw["books"] = {}
    # 自愈：把影视站 / 非小说站条目判死，见 _scrub 注释
    _scrub_and_log(raw)
    _cache = raw
    return _cache


def _read_disk() -> dict:
    """直接读盘，不走内存缓存。"""
    try:
        raw = json.loads(_DB.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return _empty()
    except Exception:  # noqa: BLE001
        return _empty()
    raw.setdefault("sites", {})
    raw.setdefault("books", {})
    if not isinstance(raw["sites"], dict):
        raw["sites"] = {}
    if not isinstance(raw["books"], dict):
        raw["books"] = {}
    # 自愈：把影视站 / 非小说站条目判死，见 _scrub 注释
    _scrub_and_log(raw)
    return raw


def _merge(disk: dict, mine: dict) -> dict:
    """把内存里这份和磁盘上那份合并。

    为什么不能直接覆盖：来源库是**进程内缓存 + 退出时落盘**的。
    如果有第二个进程也动过这个文件（命令行工具、另一个服务实例），
    直接覆盖就会把它写进去的东西整片抹掉 —— 实测踩过，
    一个只读过空库的进程退出时，能把攒了几十站的库清成空文件。

    合并规则：键取并集；同一个键两份都有时，比 `updated`（站点）/
    `last_check`（书）谁新用谁。

    **删除要单独记**（`_tomb`）：并集天然会把删掉的键又捞回来，
    所以被删的键进墓碑，合并时从两边都剔除。
    """
    out = _empty()
    for bucket, stamp in (("sites", "updated"), ("books", "last_check")):
        merged: dict = dict(disk.get(bucket) or {})
        for k, v in (mine.get(bucket) or {}).items():
            old = merged.get(k)
            if old is None:
                merged[k] = v
                continue
            if int(v.get(stamp, 0) or 0) >= int(old.get(stamp, 0) or 0):
                # 新的一份未必带着旧的一份学到的东西，补齐了再放
                keep = dict(old)
                keep.update(v)
                for f in ("first_seen",):
                    if f in old and f not in v:
                        keep[f] = old[f]
                merged[k] = keep
        for k in _tomb[bucket]:
            merged.pop(k, None)
        out[bucket] = merged
    return out


def _count(db: dict) -> int:
    return len(db.get("sites") or {}) + len(db.get("books") or {})


def _backup_if_shrunk(disk: dict, merged: dict) -> None:
    """写盘前的护栏：这次要写的内容比盘上那份缩水一大半，就先留一份备份。

    正常清理是**逐条**删的（清失效站），不会一下砍掉一半以上；
    真的出现这种量级的缩水，多半是事故 —— 比如某个只读过空库的进程退出时
    把整份快照覆盖回去（实测踩过）。一份 `registry.bak.json` 成本极低，
    但能把「不可逆的丢失」变成「可逆的」。

    注意判据里**不看墓碑**：用户主动点「清空」时墓碑是满的，
    那种情况同样值得留一份底。
    """
    before, after = _count(disk), _count(merged)
    if before < SHRINK_GUARD_MIN or after >= before * SHRINK_GUARD_RATIO:
        return
    try:
        bak = _DB.with_name(_DB.stem + ".bak.json")
        shutil.copy2(_DB, bak)
    except Exception:  # noqa: BLE001
        pass


def _save(force: bool = False) -> None:
    global _dirty, _cache
    if not _dirty and not force:
        return
    disk = _read_disk()
    merged = _merge(disk, _cache or _empty())
    _backup_if_shrunk(disk, merged)
    tmp = _DB.with_suffix(".json.tmp")
    try:
        _DB.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, _DB)          # 原子替换，不会读到半个文件
        _cache = merged
        _tomb["sites"].clear()        # 墓碑随写盘一起失效
        _tomb["books"].clear()
        _dirty = False
    except Exception:  # noqa: BLE001
        try:
            tmp.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


def flush() -> None:
    """把内存里的改动落盘（进程退出前调一次）。"""
    with _lock:
        _save(force=True)


def _maybe_save() -> None:
    """节流落盘：有改动、且距上次写盘超过 SAVE_MIN_INTERVAL 才写。

    写完置 _save_min 时间戳；不写的话改动留在内存，等下一次或 flush。
    """
    global _last_save
    if not _dirty:
        return
    now = time.time()
    if now - _last_save < SAVE_MIN_INTERVAL:
        return
    _last_save = now
    _save(force=True)


atexit.register(flush)


def _now() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------
# 站点
# ---------------------------------------------------------------------------
def note_site(host: str, *, ok: bool = True, name: str = "", why: str = "",
              **fields) -> None:
    """记一次站点的抓取结果。

    ok=True 计入成功、ok=False 计入失败；其余字段直接合并进去。

    `why` —— **失败原因分类**，这是给「定期排查坏源」用的（见下方长注释）。
    只在 ok=False 时有意义，取值遵循下面的 FAIL_* 常量。
    """
    host = (host or "").strip().lower()
    if not host:
        return
    with _lock:
        db = _load()
        cur = db["sites"].setdefault(host, {})
        # 站名只在「还没学过」时填。**`name` 等于 host 也算没学过** ——
        # 早先发现流程拿 host 当占位名写进去过，那种值是没信息量的，
        # 遇到真名字要让它覆盖掉，否则界面上永远是 `www.xxx.com`。
        if name and not cur.get("name"):
            cur["name"] = name
        elif name and cur.get("name") in (host, host.replace("www.", "")):
            cur["name"] = name
        for k, v in fields.items():
            if v not in (None, ""):
                cur[k] = v
        if ok:
            cur["ok"] = int(cur.get("ok", 0)) + 1
            cur["last_ok"] = _now()
        else:
            cur["fail"] = int(cur.get("fail", 0)) + 1
            # 按原因分类单独计数。为什么要单独记而不是只加 fail：
            # `fail` 是个**混装桶** —— 网络错、URL 猜错、真的一条结果都没有，
            # 三者都只会让它 +1。于是 `is_healthy` 的
            # 「fail > ok*2」判据把「我们自己 URL 猜错」也算成"这个站不行"，
            # 一个好好的站会因为猜错路径被慢慢判死；反过来，
            # 一个真正挂掉的站只要历史上成功过很多次，比值也压不下去。
            # 分桶之后，「定期排查坏源」才能只看 FAIL_DOWN 那一类。
            # ⚠ 本字段是**纯增量**：目前不改任何健康判定（避免动线上行为），
            #   先攒数据；等数据够了再让 registry.check 用它做决策。
            if why:
                key = f"fail_{why}"
                cur[key] = int(cur.get(key, 0)) + 1
                cur["fail_last_why"] = why
        if "first_seen" not in cur:
            cur["first_seen"] = _now()
        cur["updated"] = _now()
        global _dirty
        _dirty = True
        _maybe_save()


def known_site(host: str) -> dict:
    host = (host or "").strip().lower()
    with _lock:
        return dict(_load()["sites"].get(host) or {})


def sites() -> dict:
    with _lock:
        return {k: dict(v) for k, v in _load()["sites"].items()}


def healthy_sites() -> dict:
    return {h: s for h, s in sites().items() if is_healthy(s)}


def searchable_sites() -> dict:
    """能**站内搜索**的站 —— 学过 `search_tpl` 且还健康的。

    这是 L 源升级的核心：来源库从「记着哪本书在哪」变成
    「记着哪些站可以拿任意关键词去搜」。有了它，
    `sources/registry_source.py` 就能拿新书的关键词直接搜这些站，
    不用每次都重新走搜索引擎。

    ⚠ 判据必须走 `is_searchable()`，**不许在这里再写一遍**「健康 且 有模板」：
      这是全项目「可搜源」的**第三个消费方**（stats 总览 / /api/registry
      徽标 / 本函数给搜索扇出）。曾经各写一份，线上实测 3 vs 6 ——
      界面说"能搜 6 个"，实际搜索只问 3 个，用户看到的资产是虚的。
    """
    return {h: s for h, s in sites().items() if is_searchable(s)}


def note_search_tpl(host: str, tpl: str, *, enc: str = "utf-8", via: str = "",
                    method: str = "get", body: Optional[dict] = None) -> bool:
    """把一个站学到的搜索模板记下来。返回**这次是否真的写进去了**。

    只记**新学到**的（已有就不覆盖）—— 搜索模板一旦验证可用就是稳定的，
    偶尔一次爆破失误不该把好模板冲掉。想强制换用 `note_site(..., search_tpl=...)`。

    返回值刻意是 bool：并发场景下调用方需要知道「这次学到的是新的，还是
    别人已经先学到了」—— 这比事后再读一遍库更准（读的时候可能又被别人改了）。

    `method="post"` 时 `body` 是请求体模板（值里带 `{kw}`），
    因为有些站的搜索只认 POST（实测 384g 就是）。
    """
    host = (host or "").strip().lower()
    tpl = (tpl or "").strip()
    if not host or not tpl:
        return False
    # ⚠ 带不了关键词的模板**拒收**（2026-10-21 补）。
    #   以前只判"空不空"，于是 `/search.html` 这种裸路径被当成搜索接口存下来：
    #   请求出去关键词根本没发，打开的是搜索页/首页，验证时"链接数够多"就判真。
    #   拦在写入口比事后复核便宜得多 —— 复核一次要打两次真站点。
    from .sitelearn import tpl_carries_kw
    if not tpl_carries_kw(tpl, method=method, body=body):
        logger.info("拒收带不了关键词的搜索模板 %s：%s", host, tpl)
        return False
    notes = {"search_tpl": tpl, "search_enc": (enc or "utf-8")}
    if via:
        notes["search_via"] = via
    if (method or "get").lower() == "post":
        notes["search_method"] = "post"
        notes["search_body"] = body or {"s": "{kw}"}
    with _lock:
        # 「判空」和「写入」在同一把锁里完成。
        #
        # 原来的写法是：锁内判空、`return`（**锁在这里就释放了**），
        # 然后锁外调 `note_site` 写入。理论上并发学同一个站时，两个线程
        # 可以同时通过判空，后写的把先写的好模板覆盖掉。
        #
        # ⚠ 诚实说明：我**没能构造出稳定复现**这个竞态。
        #   因为 `_load()` 返回的是缓存引用（同一份 dict），判空与写入之间
        #   只隔几条字典操作，GIL 的调度粒度下这个窗口极窄 ——
        #   用 threading.Barrier 强行撑开窗口试了三种写法都没测出来。
        #   但"检查与写入不在同一临界区"本身是明确的坏味道，
        #   而改成锁内写入是**零成本、零行为变化**的（note_site 的其余语义
        #   这里用不到：name 覆盖规则、fail 计数都不涉及），
        #   所以按防御性加固保留。返回 bool 是为了让调用方能区分
        #   「我学到的是新的」还是「别人已经先学到了」（并发下事后重读库不可靠）。
        db = _load()
        cur = db["sites"].setdefault(host, {})
        if (cur.get("search_tpl") or "").strip():
            return False     # 已经学过，不重复学
        for k, v in notes.items():
            if v not in (None, ""):
                cur[k] = v
        # ⚠ **学到的模板不盖「已核实」的章**（2026-10-21 深夜改）。
        #   写 0 而不是 LEARN_VER，是为了让它一定进一次完整复核
        #   （`reverify_candidates()` 只挑 `search_ver < LEARN_VER` 的）。
        #
        #   为什么必须这样：「学过」和「核实过」是两件事。
        #   学站阶段为了省请求只做**单轮**控制实验（`rounds=1`），
        #   而单轮会翻转 —— 实测 `www.zxs8.net` 限流吐静态页那一轮就被判成"真"，
        #   盖上当前版本的章之后**一整个复核轮次都没查它**，直到我手动实测
        #   Jaccard=1.00 才发现它是铁假。
        #   现场还能看到同样的复发：这一轮学站又学出 `www.xxsy.net` /
        #   `www.whxss.com`（都是以前判过假的），它们带着"已核实"章直接上岗。
        #   所以信任链收紧成：学过 = 候选，连夜复核（两轮）判真才免检。
        #   盖章只发生在 `discovery.reverify_sites()` 的 `real` 分支。
        cur["search_ver"] = 0
        cur["search_fail"] = 0          # 学会了，失败账清零
        cur["search_fail_ver"] = LEARN_VER
        # ⚠ 上一条模板的**死因**也要一起清掉（2026-10-22 复盘）。
        #   `search_fail_why` 说的是「**那一个**模板为什么被撤」，不是
        #   「这个站行不行」。重学成功换了新模板，旧结论就失效了 ——
        #   留着会让 `/api/registry` 同一行里同时出现
        #   `searchable=True` 和 `why=复核：模板不认关键词（假搜索）`。
        #   这不是显示问题：2026-10-22 的复盘就是被这句话骗去查了半小时
        #   「8 个假站还在扇出」，最后证明 8 个站的模板都真的带 `{kw}`
        #   （5 个走 POST body），**库是好的，是判据自己在撒谎**。
        #   复盘靠的就是这一行，它必须只说自己有资格说的那句话。
        cur["search_fail_why"] = ""
        # ⚠ **换了新模板，搜索产出的账必须从头记**（2026-10-22）。
        #   `search_hit` / `search_shape` 说的是「**这个模板**行不行」，不是
        #   「这个站行不行」。不清的话会两头出错：
        #     · 旧模板攒满 `search_shape` → 作废 → 重学出新模板 → 计数还停在 3，
        #       新模板一上来就被判"搜不出东西"的站，永远没机会证明自己；
        #     · 旧模板曾经搜出过东西（`search_hit > 0`）→ 新模板再烂也不会被
        #       作废（判据要求 `search_hit == 0`），坏模板永久留着、每次搜索白打。
        #   所以学到一个**新**模板 = 一次新假设 = 证据重采。
        cur["search_hit"] = 0
        cur["search_shape"] = 0
        cur["ok"] = int(cur.get("ok", 0)) + 1
        cur["last_ok"] = _now()
        if "first_seen" not in cur:
            cur["first_seen"] = _now()
        cur["updated"] = _now()
        global _dirty
        _dirty = True
        _maybe_save()
        return True


def note_search_result(host: str, *, hits: int, raw: int) -> None:
    """记一次「拿关键词去这个站搜」的**真实产出**（只由 `_search_one` 调）。

    参数是两个不同层次的数量，**不能合成一个**：
      · `raw`  = 结果页里抽出几条**书链接**（还没过滤）
      · `hits` = 过滤后真正交给上层的条数

    为什么要分开记（线上实测，2026-10-22）：
      `_search_one` 原先只看「最后有没有结果」，于是两种完全相反的情况
      记成了同一笔 `FAIL_EMPTY`：
        ① 页面对、站里就是没这本书（`raw > 0`，全被过滤）→ 正常业务结果
        ② **打开的根本不是搜索页**（`raw == 0`）→ 模板/抓法坏了
      表现是 15 个「可搜源」里 7 个对任何关键词都 0 条，而库里看不出来区别。
      分开之后 `search_shape`（②）才有资格当「这站算不算可搜源」的判据，
      `search_miss`（①）**永远不参与**任何淘汰 —— "没这本书"不是站的错。

    另一个方向也要清账：**只要搜出过东西，`search_shape` 就归零**。
    站点会临时拦爬虫、会偶发 403，一次两次形态失败不该累积成死刑；
    而"搜出过结果"是模板确实可用的**硬证据**。
    """
    host = (host or "").strip().lower()
    if not host:
        return
    with _lock:
        db = _load()
        cur = db["sites"].setdefault(host, {})
        hits = max(0, int(hits or 0))
        raw = max(0, int(raw or 0))
        if hits > 0:
            cur["search_hit"] = int(cur.get("search_hit") or 0) + 1
            cur["search_shape"] = 0
            cur["search_last"] = _now()
        elif raw <= 0:
            cur["search_shape"] = int(cur.get("search_shape") or 0) + 1
        else:
            cur["search_miss"] = int(cur.get("search_miss") or 0) + 1
        # 连续「不是搜索页」到顶，且从来没搜出过 → 模板作废、回重学队列。
        # ⚠ 为什么是「清掉」而不是「留着但不用」：
        #   留着的话它每晚都要进 `reverify_candidates()`，而控制实验对
        #   "真词 0 条、控制词 0 条"的站**判不出结论**（见 `judge_by_control`
        #   的三态），于是它会永远在队列里转圈、永远不干活。既然实测已经
        #   是"拿任何关键词都抽不出链接"，这个模板就是**确定无用**的 ——
        #   清掉，让学站器用修好的逻辑（`tpl_carries_kw` + 控制实验）重学一遍。
        #   重学失败会记 `search_fail`，顶到 `SEARCH_LEARN_MAX_TRIES` 就自然放弃。
        # ⚠ 写 `""` 不 `pop` —— 落盘 `_merge()` 逐键覆盖，内存里没的键会从盘上复活
        #   （和 `note_book(note=)` 那条三态教训同一个坑）。
        if (int(cur.get("search_hit") or 0) == 0
                and int(cur.get("search_shape") or 0) >= SEARCH_SHAPE_MAX
                and (cur.get("search_tpl") or "").strip()):
            dead_tpl = (cur.get("search_tpl") or "").strip()
            cur["search_tpl"] = ""
            cur["search_ver"] = 0
            cur["search_fail"] = int(cur.get("search_fail") or 0) + 1
            cur["search_fail_ver"] = LEARN_VER
            cur["search_fail_why"] = "模板打开的不是搜索页"
            logger.info("站 %s 连续 %d 次打开的不是搜索页（模板 %s），"
                        "作废该模板让它重学（已失败 %d 次）",
                        host, int(cur.get("search_shape") or 0), dead_tpl[:60],
                        int(cur.get("search_fail") or 0))
        cur["updated"] = _now()
        global _dirty
        _dirty = True
        _maybe_save()


def note_search_fail(host: str, *, reason: str = "") -> None:
    """记一次「这个站学不出搜索接口」。

    不是为了惩罚它，而是为了**下次别重复爆破** —— 爆破一次要发好几个请求，
    而同一批站里总有那么几个真的没有站内搜索（纯静态站）。
    记下来之后 `should_try_learn` 会跳过它。

    ⚠ 失败次数上要盖一个**学站逻辑版本号**（`LEARN_VER`）——
    见 `should_try_learn()` 里那段长注释：不盖版本号的话，学习器自己的
    缺陷会把健康的小说站**永久**钉死，改好学习器也救不回来。
    """
    host = (host or "").strip().lower()
    if not host:
        return
    with _lock:
        db = _load()
        cur = db["sites"].setdefault(host, {})
        # ⚠ 换过版本就**从头记**，不能接着旧的次数往上加。
        #   否则"旧版记了 3 次"的站只要再用新版失败 1 次，计数就变成 4，
        #   立刻又满额被放弃 —— 等于版本号根本没起作用（`should_try_learn()`
        #   虽然不算旧账，但这里又把它抄回来了）。
        if int(cur.get("search_fail_ver") or 0) != LEARN_VER:
            cur["search_fail"] = 0
        cur["search_fail"] = int(cur.get("search_fail", 0)) + 1
        cur["search_fail_ver"] = LEARN_VER
        if reason:
            cur["search_fail_why"] = reason[:60]
        cur["updated"] = _now()
        global _dirty
        _dirty = True
        _maybe_save()


# 一个站最多爆破几次。3 次都不成就认命 —— 它多半真的没有站内搜索。
SEARCH_LEARN_MAX_TRIES = 3

# 学站逻辑的版本号。**每次改「怎么学」都要 +1。**
#
# 学站逻辑的版本号。**每次改「怎么学」都要 +1。**
#
# 为什么需要它（线上实测，2026-10-21）：来源库 92 个站没有搜索模板，
# 其中 **89 个的 `search_fail` 已经顶到 3** —— 也就是"永久放弃"。
# 后来查出这批失败是学习器自己的缺陷造成的：
#   · 验证一律按 https，而老的小说站大量只有 http → 永远验不过
#   · 爆破预算 6 条，而高频的 `/?s=` 排在候选表第 17 位 → 永远轮不到
# 也就是说这 89 条"认命"记录里混着一大批**本来能学会**的站。
# 把学习器修好却不动历史计数，修了等于没修 —— 用户看到的可搜源数量
# 一个都不会变。所以计数必须带版本号：老版本记的失败自动不计入，
# 升级后那批站重新回到候选里，用**新的**学习器再试 3 次。
#
# v3（2026-10-21 晚）：复核要「两个探测词」且「没结论不盖已核实的章」。
#   v2 判真的条件太松（拿站上那本书探不到就跳过后又盖了章），
#   于是 www.xxsy.net 这种"永远返回同一批书"的假模板被盖成了"已核实"，
#   再也不会被检查。v3 让它重新进复核队列。
#
# v4（2026-10-21 深夜）：复核改成**三态 + 两轮采样**。
#   单次采样会翻转 —— `www.zxs8.net` 上一轮因为限流吐静态页、两次结果集
#   不同 → 判"真"→ 盖章 → 从此不再复核。这一轮实测：真书名 9 条、
#   搜不到的书名 9 条，Jaccard **1.00**（铁假）。v4 要两轮都判假才撤、
#   两轮都判真才盖章，有分歧就算"没结论"（下次再查）。
#
# v5（2026-10-21 深夜）：**学到的模板不再盖「已核实」章**。
#   v4 之前 `note_search_tpl()` 一学会就写 `search_ver=LEARN_VER`，等于
#   "学过 = 已核实" —— 可学站阶段为了省请求只做单轮控制实验，会翻转。
#   实测后果：手动学一轮又学出 `www.xxsy.net` / `www.whxss.com`（都是以前判过假的），
#   它们带着 v4 章直接上岗、不进复核队列。v5 起学到的模板写 `search_ver=0`，
#   必须过一夜的两轮复核才盖章免检；版本号升上来让带 v4 章的重新排队。
LEARN_VER = 5


def should_try_learn(host: str) -> bool:
    """还要不要为这个站花预算去学搜索接口。

    ⚠ 失败计数**只算当前学习器版本记下的那些**。
      老版本记的失败一律不计入 —— 因为那些失败可能正是学习器自己的缺陷
      造成的（见 `LEARN_VER`）。不加版本号的话，修好学习器之后这批站
      仍然被历史计数挡在门外，「修好了」在用户那里**一点感觉都没有**：
      可搜源数量一个都不变。实测就踩过：92 个无模板站里 89 个顶到 3 次。
    """
    h = (host or "").strip().lower()
    if not h:
        return False
    s = known_site(h)
    if not s:
        return False                    # 没见过的站先别学
    if (s.get("search_tpl") or "").strip():
        return False                    # 已经会了
    return learn_tries(s) < SEARCH_LEARN_MAX_TRIES


def learn_tries(site: dict) -> int:
    """这个站**在当前学习器版本下**失败过几次。"""
    if int(site.get("search_fail_ver") or 0) != LEARN_VER:
        return 0
    return int(site.get("search_fail") or 0)


def reverify_candidates() -> list[str]:
    """有搜索模板、但那是**旧版学习器**学出来的站 —— 需要复核一遍。

    为什么必须有这条：旧判据只问"这一页像不像结果页"，不问"结果是不是由
    关键词筛出来的"。实测线上 21 个已学模板里 9 个是假的（站点根本不认
    那个参数，照常吐首页/分类页）。这批假模板已经写进库里了，
    光把学习器改好**清不掉它们** —— 它们带着 `search_tpl` 蹲在那里，
    每次搜索都会被打一遍，还把"综合 N 站"这个数字撑大。
    所以要有"按版本挑出来复核"的入口，见 `discovery.reverify_sites()`。
    """
    out: list[str] = []
    for host, s in sites().items():
        if not isinstance(s, dict):
            continue
        if not (s.get("search_tpl") or "").strip():
            continue
        if int(s.get("search_ver") or 0) >= LEARN_VER:
            continue
        out.append(host)
    return sorted(out)


# 书名后面常见的"尾巴"。来源库里 `title` 存的是**页面标题**（`<title>`），
# 所以长这样：`药鼎仙途最新章节列表` / `《神通者》-天蚕土豆-章节目录` /
# `欢迎进入梦魇直播间笔趣阁`。拿这种串当探测词去搜站内搜索，**一搜一个空**，
# 于是明明有搜索接口的站也会被判成"学不会"。
# 实测（2026-10-21，29 个站演练）：探测词全是这种脏标题，只学会 3 个。
_TITLE_JUNK = (
    "最新章节列表", "最新章节", "章节目录", "章节列表", "全文阅读", "全文免费阅读",
    "无弹窗", "免费阅读", "免费全文阅读", "在线阅读", "笔趣阁", "小说阅读网",
    "小说", "阅读", "全文", "目录", "列表",
)
_TITLE_SEP_RE = re.compile(r"[-_|—–~·:：,，/\\]|\s{2,}")


def clean_book_title(title: str) -> str:
    """把页面标题收拾成**能拿去搜**的书名。收拾不出来就回空串。"""
    t = (title or "").strip()
    if not t:
        return ""
    t = t.replace("《", "").replace("》", "").replace("〈", "").replace("〉", "")
    # 页面标题常常是「书名 - 作者 - 站点」，取第一段就是书名
    head = _TITLE_SEP_RE.split(t, 1)[0].strip()
    if len(head) >= 2:
        t = head
    # 反复剥尾巴（"…最新章节列表笔趣阁"要剥两层）
    changed = True
    while changed:
        changed = False
        for junk in _TITLE_JUNK:
            if t.endswith(junk) and len(t) > len(junk) + 1:
                t = t[: -len(junk)].strip()
                changed = True
            elif t.startswith(junk) and len(t) > len(junk) + 1:
                t = t[len(junk):].strip()
                changed = True
    t = t.strip(" -_|—–~·:：,，/\\!！?？")
    # 太短/只剩符号的不要（"活着"两个字是合法书名，所以门槛是 2）
    if len(t) < 2:
        return ""
    if not re.search(r"[\u4e00-\u9fffA-Za-z]", t):
        return ""
    return t[:40]


def probe_title(host: str) -> str:
    """这个站上**确实有**的一本书的书名 —— 学站时拿它当探测词。

    为什么不能随口用「小说」或"这次搜的书名"当探测词：
      · 用「小说」：搜出来的是一堆书名里不含"小说"的书，没法判断相关性；
      · 用"这次搜的书名"：这本书可能根本**不在这站上**（它是从别的站搜来的），
        于是这站明明有搜索接口，也会因为"搜不到"被记成学不会。
    拿站上真实的书名去探，才既搜得到、又对得上。

    ⚠ 必须过 `clean_book_title()` —— 库里的 `title` 是页面标题，
      直接拿去搜基本必空（实测踩过，见 `_TITLE_JUNK` 的注释）。
      另外要排除"书名其实就是本站站名"的记录（那是抓页面标题时抓成了站名）。
    """
    h = (host or "").strip().lower()
    if not h:
        return ""
    label = site_label(h)
    best, best_ok = "", -1
    for b in books().values():
        if not isinstance(b, dict):
            continue
        if (b.get("host") or "").strip().lower() != h:
            continue
        t = clean_book_title(str(b.get("title") or ""))
        if not t or t == label or t == h:
            continue
        ok = int(b.get("ok") or 0)
        if ok > best_ok:
            best, best_ok = t, ok
    return best


def clear_search_tpl(host: str, *, why: str = "") -> bool:
    """把一个**验证不成立**的搜索模板撤掉。返回是否真的撤掉了。

    ⚠ 键必须写 `""` 而不是 `pop` —— 落盘走 `_merge()`，内存里没有的键
      会从盘上复活（和 `note_book(note="")` 同一个坑，见那里的注释）。

    `search_fail` 同时 +1 并盖版本号：撤掉之后这个站会回到"待学"队列，
    但不会立刻又被学一遍（要等 `SEARCH_LEARN_MAX_TRIES` 用完）。
    """
    h = (host or "").strip().lower()
    if not h:
        return False
    with _lock:
        db = _load()
        cur = db["sites"].get(h)
        if not isinstance(cur, dict) or not (cur.get("search_tpl") or "").strip():
            return False
        cur["search_tpl"] = ""
        cur["search_enc"] = ""
        cur["search_body"] = {}
        cur["search_ver"] = 0
        cur["search_fail"] = int(cur.get("search_fail") or 0) + 1
        cur["search_fail_ver"] = LEARN_VER
        if why:
            cur["search_fail_why"] = why[:60]
        cur["updated"] = _now()
        global _dirty
        _dirty = True
        _maybe_save()
        return True


def site_label(host: str) -> str:
    """给一个 host，返回**给人看**的站名；没学到就退回 host。

    界面上「来自 落霞读书」比「来自 www.luoxiaks.net」好认太多。
    早先发现流程拿 host 本身当过占位名，那种值等同于没有 —— 一并挡掉。
    """
    host = (host or "").strip().lower()
    if not host:
        return ""
    name = str(known_site(host).get("name") or "").strip()
    if not name or name.lower() in (host, host.removeprefix("www.")):
        return host
    return name


def learn_candidates() -> list[str]:
    """**值得**花预算去学站内搜索的站（按"最可能学会"排前面）。

    ⚠ 为什么不能直接用 `should_try_learn()` 的全集：它只问「有没有模板 /
    有没有放弃过」，**不问这个站是不是还活着、是不是小说站**。线上实测
    拿它当清单跑批量学习，12 个目标里混进了
    `www.kugou.com`（音乐）、`wulin2.games.wanmei.com`（游戏）、
    `mzh.moegirl.org.cn`（萌娘百科）、`www.chagushici.com`（诗词）——
    每个都要花首页抓取 + 最多 6 次爆破，**真正的小说站反而排不上队**。
    学完了也没用：非小说站学到的搜索接口永远不会出现在搜书结果里。

    所以这里加两道筛：① `is_healthy()`（已经判死的不学）
    ② `_is_offtopic_site` / `_is_video_site`（分类都不对的，活着也不学）。

    排序理由：**已经成功抓到过目录的站优先**（`toc_tpl` 在）——
    它证明过「这个站能给整本书」，学会了搜索就是直接变可用源；
    只 ok 过几次的站次之。同档内按成功次数降序。

    ⚠ 排序**就是**筛选：一批只跑得完十几个站（`_LEARN_BUDGET_MAX=120s`），
    而线上有 92 个待学站。所以"谁排前面"直接决定"这轮学的是不是有用的站"。
    实测：70 个没有 `toc_tpl` 的站里混着企查查 / 酷狗音乐 / 豆包漫画 /
    wikiwand / 大英百科 / 船艇网 —— 它们永远学不出能用的搜索，但只要
    排在真小说站前面，就要白花一次预算。现在用「有书页证据 > 有目录模板 >
    历史成功数」三级排序，这 42 个已证明能读整本书的站稳稳排在最前。
    """
    book_hosts = {
        (b.get("host") or "").strip().lower()
        for b in books().values() if isinstance(b, dict)
    }
    out: list[tuple[int, int, int, str]] = []
    for host, site in sites().items():
        if not isinstance(site, dict):
            continue
        if not should_try_learn(host):
            continue
        if not is_healthy(site):
            continue
        if _is_offtopic_site(host, site) or _is_video_site(host, site):
            continue
        has_book = 1 if host in book_hosts else 0
        has_toc = 1 if (site.get("toc_tpl") or "").strip() else 0
        out.append((-has_book, -has_toc, -int(site.get("ok") or 0), host))
    return [h for _, _, _, h in sorted(out)]


def is_healthy(site: dict) -> bool:
    """一个站点还算不算「能用」。

    ⚠ 改动（本轮）：计入了两件事，它们各自都在真实数据上验证过影响面。

    ① **`offtopic_blocked` 也要否**（原来只查 `video_blocked`）。
       `_scrub()` 早就给非小说站打了 `offtopic_blocked` 并置 `ok=0`，
       但 `is_healthy` 不看这个旗标 —— 于是那些站只要**历史上攒过 ok**
       （实测 `www.kancloud.cn` ok=32），`fail > ok*2` 就不成立，**又活回来**。
       修完实测：正确否掉 16 个（腾讯云/有道翻译/爱词霸/博客园/DeepL/
       森海塞尔商城/小红书/SVG 工具站/文档站…），**逐个人工核实全部该否**。

    ② **有 `search_tpl` 的站在比值判据上放宽**（只计 `fail_down`）。
       「能不能拿关键词搜到这个站」和「我们抓某本书正文时猜没猜对路径」
       是两件事，但它们被混在同一个 `fail` 桶里 —— 结果是可搜源
       被"猜错路径"慢慢拖死。实测被误杀的两个：
         · `www.tadu.com`   ok=39 fail=79（**只超阈值 1**），
                            实测 HTTP 200 / 45KB，站活得好好的；
         · `www.biqugela.cc` ok=6 fail=15
       两者 `fail_down` 都是 **0** —— 从没有过网络层失败，纯粹是抓法问题。
       放宽后 `sites_searchable` 从 **1 → 3**，且**零非小说站混入**。
       （判据仍守住底线：`fail_down` 高的一样否，非小说站一样否。）
    """
    if not site:
        return False
    # 被判为影视站 / 非小说站的，一律不健康 —— 这条要放在最前面，
    # 因为下面的计数判据在「它恰好最近访问成功」时可能放行它。
    if site.get("video_blocked") or site.get("offtopic_blocked"):
        return False
    ok = int(site.get("ok", 0))
    fail = int(site.get("fail", 0))
    if ok == 0 and fail >= UNHEALTHY_FAILS:
        return False
    down = int(site.get("fail_down") or 0)
    # 真正挂掉的：**网络层**失败多，且压过成功次数 —— 一律否。
    # 用 fail_down 而不是混装的 fail：混装桶里"我们自己猜错路径"也算失败，
    # 拿它判站是冤枉（见上面 ② 的实测）。
    if down >= 3 and down > ok * 2:
        return False
    # 可搜源（学过站内搜索接口）只要没被网络层失败压死就保留 ——
    # 它能搜，就是 L 源的资产，不该因为抓某本书时猜错路径被丢掉。
    if (site.get("search_tpl") or "").strip():
        return True
    # 其余站维持原比值判据（混装 fail 也认 —— 保守，避免放过未知的新站）
    if fail >= 3 and fail > ok * 2:
        return False
    return True


def is_searchable(site: dict) -> bool:
    """这个站现在**能不能直接站内搜** —— 全项目唯一判据。

    ⚠ 为什么必须收敛到一处（线上实测抓到的口径漂移）：
      以前「可搜源」有两套口径 ——
        · `stats()["sites_searchable"]` 数的是「健康 **且** 有 search_tpl」
        · `/api/registry` 每项给界面的 `searchable` 只看「有没有 search_tpl」
      实测差了一倍（3 vs 6），多出来的三个
      （`www.xizids.com` / `big5.cctv.com` / `350.ooo`）**都已经被判为不健康**。
      于是同一句「有 N 个可搜源」，看总览是 3、按站点列表数是 6，
      用户没法知道该信哪个 —— 更糟的是**坏站被算进了资产**。
      两处各写一遍判据就一定会再漂，所以只留这一个函数。

    2026-10-21 又补了一条：模板**必须真的能把关键词带出去**。
    14 个"可搜源"里有 6 个的模板是 `/search.php` `/search` `/search.html`
    这类**不带 `{kw}` 占位**的路径 —— `build_url()` 只做 `{kw}` 替换，
    没有占位就等于关键词没发给站点，打开的是搜索页/首页（那儿本来就有一堆书），
    所以验证时"数到十几条链接"也判真。详见 `sitelearn.tpl_carries_kw`。
    ⚠ 判据仍然只在这一处 —— 界面、总览、扇出、复核全都调它。
    ⚠ 「搜不出东西」不在这里判：到顶那一刻模板已经在 `note_search_result()`
      里被清空了，`has_search_tpl()` 自然返回 False。再加一条
      `search_shape >= MAX` 是**冗余**的（反证实测：把它改成恒假，全部测试
      照样绿）—— 冗余判据还会带来真危害：重学出新模板后计数若没清零，
      新模板会被立刻挡死。所以这里只留一条真实生效的判据。
    """
    return (has_search_tpl(site) and _tpl_can_search(site)
            and is_healthy(site))


def _tpl_can_search(site: dict) -> bool:
    """库里的模板是不是一个"真能带关键词出去"的搜索接口。

    单独拿出来是为了让 `is_searchable` 的注释说清一件事：
    「学过模板」和「模板能搜」是两件事，中间差的就是这个函数。
    """
    from .sitelearn import tpl_carries_kw   # 函数内 import：registry 不反向依赖上层

    return tpl_carries_kw((site.get("search_tpl") or "").strip(),
                          method=(site.get("search_method") or "get"),
                          body=site.get("search_body"))


def has_search_tpl(site: dict) -> bool:
    """有没有学过站内搜索接口（**不管站还健不健康**）—— 只给诊断用。

    界面该说「能搜」= `is_searchable`；这个只用来区分
    「模板压根没学过」和「模板有、但站已经不行了」——
    两者的修法完全不同（前者去学站，后者去清库/换域名）。
    """
    return bool((site.get("search_tpl") or "").strip())


def forget_site(host: str) -> bool:
    host = (host or "").strip().lower()
    with _lock:
        db = _load()
        hit = db["sites"].pop(host, None) is not None
        if hit:
            _tomb["sites"].add(host)
            global _dirty
            _dirty = True
            _maybe_save()
        return hit


def site_fault_breakdown() -> dict:
    """按**失败原因**统计各站，给「定期排查坏源」用。**只读，不动任何数据。**

    为什么需要它（而不是继续用 is_healthy）：
      `is_healthy` 看的是混装的 `fail` 总数比 —— 分不清"站挂了"和
      "我们这次抓法不对"。这里只看 `fail_down`（网络层失败），
      那才是"站点可能真的坏了"的证据。

    返回值：
      {
        "suspects": [ {host, down, ok, last_why, healthy}, ... ],  # down 多、ok 少
        "victims":  [ {host, shape, empty, gated, ok}, ... ],     # 失败多但都是抓法问题
        "no_data":  int,     # 一次都没记过 fail_* 的站（分类之前的老数据）
      }

    ⚠ 刻意**不自动清理**：这个函数只报告。删数据是 `prune` 的事，
      而"哪些算坏源"的阈值需要先拿真实数据校准（见 fail_* 为什么不改判定）。
    """
    # ⚠ 变量名别叫 `sites` —— 会把下面的模块函数 `sites()` 遮蔽掉，
    #    报 UnboundLocalError（本函数第一版就是这么挂的）。
    all_sites = sites()
    suspects, victims = [], []
    no_data = 0
    for host, s in all_sites.items():
        down = int(s.get("fail_down") or 0)
        ok = int(s.get("ok") or 0)
        shape = int(s.get("fail_shape") or 0)
        empty = int(s.get("fail_empty") or 0)
        gated = int(s.get("fail_gated") or 0)
        video = int(s.get("fail_video") or 0)
        if not any((down, shape, empty, gated, video)):
            # 分类之前的老记录：只有混装的 fail，没有 fail_*
            if int(s.get("fail") or 0):
                no_data += 1
            continue
        # 判据：网络层失败数 ≥ 2 且多于成功数 —— 说明它不是偶尔抽风
        if down >= 2 and down > ok:
            suspects.append({
                "host": host, "name": s.get("name") or host,
                "down": down, "ok": ok,
                "last_why": s.get("fail_last_why") or "",
                "healthy": is_healthy(s),
            })
        elif (shape + empty + gated) > down and ok > 0:
            # 失败基本都是"抓法不对"（形态/搜不出/要登录），而站还能成功
            # → 站是好的，是模板/启发式要修。这类**不该**被当坏源清掉。
            victims.append({
                "host": host, "name": s.get("name") or host,
                "shape": shape, "empty": empty, "gated": gated, "ok": ok,
            })
    suspects.sort(key=lambda x: (-x["down"], x["host"]))
    victims.sort(key=lambda x: -(x["shape"] + x["empty"] + x["gated"]))
    return {"suspects": suspects, "victims": victims, "no_data": no_data}


# ---------------------------------------------------------------------------
# 书
# ---------------------------------------------------------------------------
def note_book(
    url: str,
    *,
    title: str = "",
    author: str = "",
    intro: str = "",
    host: str = "",
    chapters: int = 0,
    note: Optional[str] = None,
    ok: bool = True,
) -> None:
    r"""把一本「联网发现」的书记下来。

    `note` 是**三态**，别把它简化成字符串默认值：

      None（缺省） = 「这次调用不评价目录完整性」→ **不动**已有的 note
      ""           = 「这次查过，目录是完整的」→ **清掉**已有的 note
      "非空串"      = 「这次查过，目录只拿到一部分」→ 写上原因

    ⚠ 为什么必须区分 None 和 ""：写这句话的调用方有两类 ——
    体检（`discovery._check_book`，真的去抓过目录、有资格下结论）和
    顺手记录（`web.py` 的抓正文成功、`discovery` 的失败记账，**没看目录**）。
    如果 "" 和 None 一个语义，第二类调用就会把第一类刚写下的
    「目录可能不全」**顺手擦掉** —— 于是那条警告在库里的存在时间取决于
    调用顺序，而不是取决于目录到底全不全。

    ⚠ 反过来同样要防：**目录后来变全了，警告必须能消失**。
    只写不清（`if note:` 那种写法）的话，一条过早写下的警告会永远挂在
    那本书上，用户看到的是一个早就修好的假问题。所以体检那条路
    每次都把结论（哪怕是空串）交上来。
    """
    url = (url or "").strip()
    if not url:
        return
    with _lock:
        db = _load()
        cur = db["books"].setdefault(url, {})
        if title:
            cur["title"] = title[:80]
        if author and not cur.get("author"):
            cur["author"] = author[:40]
        if intro and not cur.get("intro"):
            cur["intro"] = intro[:200]
        if host:
            cur["host"] = host
        if chapters:
            cur["chapters"] = int(chapters)
        if note is not None:
            # ⚠ 清掉警告时必须写**空串**，不能 `pop` 掉这个键。
            #   落盘走 `_merge()`，它对同一个键是「先取盘上那份、再用内存那份
            #   逐个键覆盖」，而**内存那份没有这个键时不会覆盖** ——
            #   于是 `pop` 掉的 note 会在合并时从盘上复活，
            #   用户看到的警告永远撤不掉（"目录其实已经修好了"也撤不掉）。
            #   写空串就落在"覆盖"这一侧，合并之后仍然是空的。
            cur["note"] = note[:120]
        if ok:
            cur["ok"] = int(cur.get("ok", 0)) + 1
            cur["last_ok"] = _now()
        else:
            cur["fail"] = int(cur.get("fail", 0)) + 1
        if "first_seen" not in cur:
            cur["first_seen"] = _now()
        cur["last_check"] = _now()
        global _dirty
        _dirty = True
        _maybe_save()


def known_book(url: str) -> dict:
    with _lock:
        return dict(_load()["books"].get((url or "").strip()) or {})


def books() -> dict:
    with _lock:
        return {k: dict(v) for k, v in _load()["books"].items()}


def healthy_books() -> dict:
    return {u: b for u, b in books().items() if is_book_healthy(b)}


def is_book_healthy(book: dict) -> bool:
    if not book:
        return False
    # 影视站的书一律不健康（同 is_healthy）
    if book.get("video_blocked"):
        return False
    ok = int(book.get("ok", 0))
    fail = int(book.get("fail", 0))
    if ok == 0 and fail >= UNHEALTHY_FAILS:
        return False
    if fail >= 3 and fail > ok * 2:
        return False
    return True


def forget_book(url: str) -> bool:
    url = (url or "").strip()
    with _lock:
        db = _load()
        hit = db["books"].pop(url, None) is not None
        if hit:
            _tomb["books"].add(url)
            global _dirty
            _dirty = True
            _maybe_save()
        return hit


# ---------------------------------------------------------------------------
# 查书：从本地库里找匹配的书
# ---------------------------------------------------------------------------
_TITLE_NOISE = re.compile(r"[\s\u3000《》〈〉“”‘’'\"()（）\[\]【】:：;；,，.。!！?？·、\-—_~～|/\\]+")


def _norm(s: str) -> str:
    return _TITLE_NOISE.sub("", (s or "")).lower()


def find_books(keyword: str, *, limit: int = 10) -> list[dict]:
    """在库里找和关键词对得上的书。

    排序：书名完全相等 > 包含关键词 > 其它。同分的按健康度和章节数。
    只返回**健康**的条目。
    """
    kw = _norm(keyword)
    if not kw:
        return []
    out: list[tuple[tuple, str, dict]] = []
    for url, b in books().items():
        if not is_book_healthy(b):
            continue
        t = _norm(b.get("title", ""))
        if not t:
            continue
        if t == kw:
            rank = 0
        elif kw in t or t in kw:
            rank = 1
        else:
            continue
        out.append(((rank, -int(b.get("chapters", 0)), -int(b.get("ok", 0))), url, b))
    out.sort(key=lambda x: x[0])
    res = []
    for _k, url, b in out[:limit]:
        item = dict(b)
        item["url"] = url
        res.append(item)
    return res


# ---------------------------------------------------------------------------
# 统计 / 健康筛选
# ---------------------------------------------------------------------------
def stats() -> dict:
    with _lock:
        db = _load()
        s_all, b_all = db["sites"], db["books"]
        s_ok = sum(1 for s in s_all.values() if is_healthy(s))
        b_ok = sum(1 for b in b_all.values() if is_book_healthy(b))
        by_host: dict[str, int] = {}
        for b in b_all.values():
            h = b.get("host", "")
            if h:
                by_host[h] = by_host.get(h, 0) + 1
        top = sorted(by_host.items(), key=lambda kv: -kv[1])[:8]
        # 「可搜源」的统计一并给出来 —— 界面用来说明 L 源到底长了多少。
        # ⚠ 判据走 `is_searchable()`，和 `/api/registry` 每项那个旗标**同一个函数**；
        #   两处各写一遍就会出现「总览说 3、列表数出 6」这种没法解释的差。
        searchable = sum(1 for s in s_all.values() if is_searchable(s))
        return {
            "sites": len(s_all),
            "sites_ok": s_ok,
            "sites_searchable": searchable,
            "books": len(b_all),
            "books_ok": b_ok,
            "top_sites": [{"host": h, "books": n} for h, n in top],
            "path": str(_DB),
        }


def dead() -> dict:
    """列出不健康的站点和书（给「定期筛选」用）。"""
    with _lock:
        db = _load()
        return {
            "sites": {h: s for h, s in db["sites"].items() if not is_healthy(s)},
            "books": {u: b for u, b in db["books"].items() if not is_book_healthy(b)},
        }


def prune(*, only_dead: bool = True, confirm: bool = False) -> dict:
    """清理来源库。

    only_dead=True（默认）只清不健康的；
    only_dead=False 会清空整库 —— 这种操作**必须**显式传 confirm=True，
    否则直接报错拒绝。

    为什么要这道闸：`prune(only_dead=False)` 是唯一一个「一次调用能删光全库」
    的入口，而它曾经被测试脚本顺手调过一次，把生产库里攒的站点全清了
    （见 README「来源库」一节）。默认参数越危险，越要让人打出来。
    返回被清掉的条数。
    """
    if not only_dead and not confirm:
        raise ValueError("清空整个来源库需要 confirm=True")
    with _lock:
        db = _load()
        if not only_dead:
            n_s, n_b = len(db["sites"]), len(db["books"])
            _tomb["sites"].update(db["sites"])
            _tomb["books"].update(db["books"])
            db["sites"], db["books"] = {}, {}
        else:
            n_s = n_b = 0
            for h in [h for h, s in db["sites"].items() if not is_healthy(s)]:
                db["sites"].pop(h, None)
                _tomb["sites"].add(h)
                n_s += 1
            for u in [u for u, b in db["books"].items() if not is_book_healthy(b)]:
                db["books"].pop(u, None)
                _tomb["books"].add(u)
                n_b += 1
        if n_s or n_b:
            global _dirty
            _dirty = True
        _save(force=True)
        return {"sites_removed": n_s, "books_removed": n_b}
