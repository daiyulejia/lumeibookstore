"""联网发现：本地来源搜不到时，自己出去把书找回来。

三步，正好对应「去搜索 → 拿到网站 → 去爬取」：

    1. `websearch.find_book_pages()`  搜索引擎找「书页 URL」
    2. 并发核实每个候选              直链打开，看它有没有目录（`webfetch`）
    3. 把核实的成果写进来源库         下次搜同一本书，秒出（`registry`）

为什么绕开「站内搜索」
----------------------
很多站（比如实测的 29zw.com）搜索接口被 Cloudflare WAF 拦得死死的，
但详情页 / 目录 / 正文全敞开。**它不是不能抓，只是不能搜** ——
而「搜」这件事，搜索引擎已经替我们做了。所以这条路
根本不需要那些站的搜索功能，也就绕开了最容易被封的一环。
"""
from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from . import registry, sitelearn, webfetch, websearch
from .models import BookResult
from .relevance import score as score_result
from .utils import fast_mode, fetch_text, host_of

logger = logging.getLogger("novel.discovery")

LogFn = Callable[[str, str, bool], None]

DISCOVER_WORKERS = 10
DISCOVER_BUDGET = 16.0      # 核实阶段的总预算（秒）
PAGE_TTL = 900              # 抓下来的页面在内存里留多久

# 页面缓存：核实阶段抓过的详情页，探测阶段不用再抓一遍
_pg_cache: dict[str, tuple[float, dict]] = {}
_pg_lock = threading.Lock()


# ---------------------------------------------------------------------------
# 页面缓存
# ---------------------------------------------------------------------------
def page_of(url: str, *, force: bool = False) -> dict:
    """抓并解析一个页面，成功的结果缓存起来。"""
    url = (url or "").strip()
    if not url:
        return {"kind": "unknown", "url": url}
    now = time.time()
    if not force:
        with _pg_lock:
            hit = _pg_cache.get(url)
            if hit and now - hit[0] < PAGE_TTL:
                return hit[1]
    data = webfetch.analyze(url)
    if data.get("kind") in ("toc", "chapter"):
        with _pg_lock:
            # 请求地址和重定向后的地址都存一份 —— 核实阶段用的是原始地址，
            # 之后按书抓目录用的是最终地址，不存两份就要多抓一次。
            _pg_cache[url] = (now, data)
            real = data.get("final_url")
            if real and real != url:
                _pg_cache[real] = (now, data)
    return data


def forget_pages() -> int:
    with _pg_lock:
        n = len(_pg_cache)
        _pg_cache.clear()
        return n


# ---------------------------------------------------------------------------
# 书名清洗
# ---------------------------------------------------------------------------
_TAIL_NOISE = re.compile(
    r"(最新章节|最新更新|全文阅读|免费阅读|在线阅读|无弹窗|txt下载|全集|全文"
    r"|小说全文|章节目录|最新章节列表|全部章节|章节列表|目录|列表|"
    r"在线阅读全文|笔趣阁|免费全文)+")
_SITE_TAIL = re.compile(r"[\s\-_|—·]+[^\-_|—·]{0,12}"
                        r"(小说网|文学网|读书网|书城|书院|阅读网|小说阅读|小说吧|中文网)\s*$")


def clean_book_title(s: str) -> str:
    """把搜索引擎给的标题洗成书名。

    Bing 给的常常是「药鼎仙途最新章节_药鼎仙途小说全文阅读_落霞读书」这种，
    直接当书名显示会很长很丑。

    另外要把标题里的**话题标签符**剥掉：搜索引擎会把「#活着」这种话题标签
    原样带进标题，实测搜「余华 活着」时出现过一个源叫 `#活着`（首播网），
    展示出来很脏，而且 `#` 会让 normalize 之后的名字和别的源对不上，
    影响「同一本书」的合并判断。
    """
    s = re.sub(r"\s+", " ", (s or "").strip())
    s = _SITE_TAIL.sub("", s)
    # 反复剥：「药鼎仙途最新章节列表」要剥两次才对
    for _ in range(3):
        new = _TAIL_NOISE.sub("", s).strip()
        if new == s:
            break
        s = new
    # 中文小说书名一般不含空格；空格往往是「书名 作者」或「书名 - 站名」
    parts = [p.strip(" _-—|·") for p in re.split(r"[_\-—|·,，:：/]", s) if p.strip(" _-—|·")]
    if parts:
        # 取第一个「像书名」的段：2~20 字，且不是纯英文/网址
        for p in parts:
            p = re.sub(r"[（(][^）)]*[）)]\s*$", "", p).strip()
            p = p.lstrip("#＃").strip()          # 剥掉话题标签符
            if 1 < len(p) <= 24 and re.search(r"[\u4e00-\u9fff]", p):
                return p
        s = parts[0].lstrip("#＃").strip()
    return s.strip()[:40]


# ---------------------------------------------------------------------------
# 从来源库找
# ---------------------------------------------------------------------------
def from_registry(keyword: str, *, limit: int = 8) -> list[BookResult]:
    out: list[BookResult] = []
    for b in registry.find_books(keyword, limit=limit):
        r = BookResult(
            title=b.get("title", ""), author=b.get("author", ""),
            source="web", url=b["url"], intro=b.get("intro", ""),
            source_display="联网发现",
        )
        r.cover = b.get("cover", "") or ""
        r.chapter_count = int(b.get("chapters", 0) or 0)
        host = b.get("host", "")
        r.note = f"来自 {registry.site_label(host)}" if host else ""
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# 联网发现
# ---------------------------------------------------------------------------
def _verify(cand: dict, keyword: str) -> Optional[BookResult]:
    """核实一个候选：打开它，看有没有目录。"""
    url, host = cand["url"], cand["host"]

    # 库里记着这个站已经不行了（连续失败过），就别再花一个并发槽去撞它。
    # 一个候选要占 10 秒超时预算，而整轮核实只有十几秒。
    site = registry.known_site(host)
    if site and not registry.is_healthy(site):
        logger.debug("跳过已失效站点 %s", host)
        return None

    try:
        # retries=0：核实阶段必须**硬性**卡住时间。一个连不上的站
        # 重试一次就是 2 倍超时，会把整轮预算吃光（实测踩过）。
        with fast_mode(retries=0, timeout=10.0):
            data = page_of(url)
    except Exception as e:  # noqa: BLE001
        logger.info("候选核实失败 %s: %s", host, e)
        # why=down：网络层失败（连不上/超时/5xx），这才是"站点可能挂了"。
        registry.note_site(host, ok=False, why=registry.FAIL_DOWN)
        return None

    if data.get("kind") != "toc":
        # why=shape：页**打开了**，只是不是章节目录 —— 多半是搜索引擎
        # 给的地址指向了书页/简介页，是我们 URL 猜错，不是站不行。
        # （早先这里和上面的网络失败记成同一笔，把好站拖进"高失败率"。）
        registry.note_site(host, ok=False, why=registry.FAIL_SHAPE)
        return None

    toc = data.get("toc") or []
    # 用跟随重定向之后的地址当书的唯一标识 ——
    # 搜索引擎给的 /book/catalogue/349017/ 和站点自己的 /book/x/349017/toc
    # 是同一页，用原始地址当键就会重复收录。
    real_url = data.get("final_url") or url
    real_host = data.get("host") or host
    # 站名（"落霞读书"）比 host（"www.luoxiaks.net"）好认得多；
    # `analyze` 已经从 og:site_name / title 尾巴里顺手学了一份
    site_name = data.get("site_name") or ""

    title = clean_book_title(data.get("title") or cand.get("title") or "") or keyword
    r = BookResult(
        title=title, author=(data.get("author") or "")[:40],
        source="web", url=real_url, intro=(data.get("intro") or "")[:200],
        source_display="联网发现",
    )
    r.available = True
    r.chapter_count = len(toc)
    r.note = f"来自 {site_name or real_host}"

    registry.note_site(real_host, ok=True, **({"name": site_name} if site_name else {}))
    registry.note_book(real_url, title=r.title, author=r.author, host=real_host,
                       intro=r.intro, chapters=r.chapter_count)
    r.score = score_result(r, keyword)
    logger.info("联网发现命中: %s 《%s》 %d 章 (质量 %.2f)",
                real_host, r.title, r.chapter_count, float(data.get("quality") or 0))
    return r


# ---------------------------------------------------------------------------
# L 源升级：把「找到的站」升级成「下次能直接搜的源」
# ---------------------------------------------------------------------------
# 并发预算：学一个站要发好几个请求（爆破搜索路径），不能占太多槽位，
# 否则会和「用户正在等的那次搜索」抢带宽。
_LEARN_WORKERS = 3
_LEARN_BUDGET = 14.0


def learn_sites(
    hosts: list[str],
    *,
    keyword: str = "",
    log: Optional[LogFn] = None,
) -> dict:
    """给一批刚验证可用的站学站内搜索模板。

    为什么要单独一趟、而不是在 `_verify()` 里顺手做：
    `_verify()` 只抓了**书页**（详情页），那上面通常没有搜索框
    （搜索框在首页 / 列表页）。而且爆破搜索路径是**额外请求**，
    混在核实阶段会拖慢「用户正在等的那一批」。

    所以放在核实完、结果已经交给用户之后，后台慢慢学 —— 用户这次
    只关心结果，学习是为了**下一次**能在自己的源里搜到。

    这一步是「L 源越用越大」的关键：**每搜一次新书，就可能多几个可搜源。**
    """
    hosts = [h for h in dict.fromkeys(h or "" for h in hosts) if h]
    if not hosts:
        return {"learned": 0, "failed": 0, "skipped": 0}

    def say(title: str, detail: str = "", ok: bool = True) -> None:
        if not log:
            return
        try:
            log(title, detail, ok)
        except Exception:  # noqa: BLE001
            pass

    # 已经会了 / 已放弃的站直接跳过
    todo = [h for h in hosts if registry.should_try_learn(h)]
    skipped = len(hosts) - len(todo)
    if not todo:
        return {"learned": 0, "failed": 0, "skipped": skipped}

    say("学习站点搜索", f"{len(todo)} 个站（下次搜别的书能直接用）")

    learned = failed = 0
    lock = threading.Lock()

    def _learn_one(host: str) -> bool:
        try:
            # 先用首页 —— 搜索框 / 搜索链接都在那儿
            page_url = f"https://{host}/"
            try:
                html, final = fetch_text(page_url, with_url=True)
            except Exception:  # noqa: BLE001
                page_url = f"http://{host}/"      # 老站只有 http
                html, final = fetch_text(page_url, with_url=True)
        except Exception as e:  # noqa: BLE001
            logger.debug("学 %s 时抓首页失败: %s", host, e)
            html, final = "", f"https://{host}/"

        # 探测词：优先用这次搜的书名（一般能搜到），否则用「小说」
        probe = (keyword or "").strip() or "小说"
        try:
            with fast_mode(retries=0, timeout=20.0):
                got = sitelearn.learn_site(
                    host, page_url=(final or page_url), html=html,
                    probe_keyword=probe, allow_guess=True, budget=6,
                )
        except Exception as e:  # noqa: BLE001
            logger.debug("学 %s 失败: %s", host, e)
            got = {}

        if got.get("search_tpl"):
            # scheme 也顺手记一下（老站 http / 新站 https 不同）
            try:
                sch = sitelearn.detect_scheme(host)
            except Exception:  # noqa: BLE001
                sch = "https"
            # 返回 False 表示"这个站已经有模板了，我这次学到的不作数"——
            # 并发搜索时几个线程会同时爆破同一个站，这是正常情况不是错误。
            fresh = registry.note_search_tpl(
                host, got["search_tpl"], enc=got.get("search_enc", "utf-8"),
                via=got.get("search_via", ""),
                method=got.get("search_method", "get"),
                body=got.get("search_body"))
            registry.note_site(host, ok=True, search_scheme=sch)
            logger.info("学会站点搜索%s: %s → %s %s(%s)",
                        "" if fresh else "（已有，未覆盖）",
                        host, got["search_tpl"], got.get("search_method", "get"),
                        got.get("search_enc"))
            return True

        registry.note_search_fail(host, reason="没找到可用的搜索接口")
        return False

    pool = ThreadPoolExecutor(max_workers=min(_LEARN_WORKERS, len(todo)))
    futs = {pool.submit(_learn_one, h): h for h in todo}
    try:
        for fut in as_completed(futs, timeout=_LEARN_BUDGET):
            try:
                ok = bool(fut.result())
            except Exception:  # noqa: BLE001
                ok = False
            with lock:
                if ok:
                    learned += 1
                else:
                    failed += 1
    except Exception:  # noqa: BLE001
        logger.info("站点学习超预算，先收手")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if learned:
        say("自有来源扩大", f"新学会 {learned} 个站的搜索，下次直接用", True)
    return {"learned": learned, "failed": failed, "skipped": skipped}


def discover(
    keyword: str,
    *,
    log: Optional[LogFn] = None,
    limit: int = 12,
    budget: float = DISCOVER_BUDGET,
    learn_async: bool = True,
) -> list[BookResult]:
    """搜书名 → 找书页 → 核实 → 记进来源库。

    ⚠ `learn_async=True`（默认）：结果好了就立刻返回，「学站」丢后台。
      这不是优化，是**正确性** —— 见 `_learn_later()` 的注释。
    """
    def say(title: str, detail: str = "", ok: bool = True) -> None:
        if not log:
            return
        try:
            log(title, detail, ok)
        except Exception:  # noqa: BLE001
            pass

    keyword = (keyword or "").strip()
    if not keyword:
        return []

    say("联网搜索", f"本地没有《{keyword}》，出去找找")
    try:
        cands = websearch.find_book_pages(keyword, limit=limit, log=log)
    except Exception as e:  # noqa: BLE001
        say("联网搜索失败", str(e)[:60], False)
        return []

    # 同一个 URL 只核实一次
    seen: set[str] = set()
    uniq = []
    for c in cands:
        if c["url"] in seen:
            continue
        seen.add(c["url"])
        uniq.append(c)

    if not uniq:
        say("没搜到候选", "搜索引擎没有返回可用结果", False)
        return []

    say("核实候选站点", f"{len(uniq)} 个地址")

    results: list[BookResult] = []
    seen_url: set[str] = set()
    lock = threading.Lock()
    pool = ThreadPoolExecutor(max_workers=min(DISCOVER_WORKERS, len(uniq)))
    futs = {pool.submit(_verify, c, keyword): c for c in uniq}
    try:
        for fut in as_completed(futs, timeout=budget):
            try:
                r = fut.result()
            except Exception as e:  # noqa: BLE001
                logger.debug("核实异常: %s", e)
                r = None
            if not r:
                continue
            with lock:
                # 两个候选重定向到同一页 → 只留一条
                if r.url in seen_url:
                    continue
                seen_url.add(r.url)
                results.append(r)
            say("发现可用来源", f"{r.title} · {r.chapter_count} 章 ({host_of(r.url)})")
    except Exception:  # noqa: BLE001
        logger.info("联网核实超预算，先用已有结果")
        say("核实超时", "先把已经找到的给你", True)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if results:
        results.sort(key=lambda r: -r.score)
        say("来源库已更新", f"新收录 {len(results)} 条")
    else:
        say("没找到能用的", "搜到的站点都打不开或没有目录", False)

    # ---- L 源升级：后台/收尾地把「这次找到的站」学成「下次能直接搜的源」 ----
    # 放在最后：用户已经拿到结果了，学站内搜索是为**下一次**服务。
    # 同步做（而不是另起线程）是为了让日志里的「自有来源扩大」能在
    # 本次搜索的进度流里显示出来 —— 用户能直观看到「L 源又变大了」。
    if results:
        try:
            _learn_later([host_of(r.url) for r in results], keyword=keyword,
                         log=log, inline=not learn_async)
        except Exception as e:  # noqa: BLE001
            logger.info("站点学习启动失败（不影响本次结果）: %s", e)

    return results


# 后台「学站」线程：只为了能在测试里等它收尾。
_learn_threads: list[threading.Thread] = []
_learn_lock = threading.Lock()


def _learn_later(hosts: list[str], *, keyword: str, log: Optional[LogFn],
                 inline: bool) -> None:
    """学站内搜索模板 —— **默认放后台，绝不挡在结果前面**。

    ⚠ 为什么必须后台（2026-10-14 线上实测踩到，用户报「这本书找不到」）：
      学站是 `learn_sites()` 干的，预算 `_LEARN_BUDGET = 14.0` 秒。
      原先它**同步**写在 `discover()` 的结尾，于是实测时间线变成：

          0.3s  Bing 搜到结果        1.5s  百度搜到结果
          3.2s  ✓ 发现可用来源（结果其实**已经好了**）
          3.2s  开始学站 …
         17.2s  ← 函数才 return

      而搜索的墙钟硬上限是 `engine.SEARCH_HARD_DEADLINE = 20s`。
      留给「联网发现」的余量只剩 **不到 3 秒** —— 只要联网稍慢一点，
      整轮就被收手，用户看到的是「没找到」。
      真实事故：搜《我们猫猫不能听这些》，本地 7 个源零覆盖，
      联网**其实已经找到**（实测命中 zxs8.net），却因为这一等被砍成 0 结果。

      学站是**为下一次**服务的（把这次发现的站学成"下次能直接搜的源"），
      跟本次结果毫无关系，没有任何理由挡在结果交付前面。

    `inline=True` 只为测试保留（用来反证"同步版确实会阻塞"）。
    """
    def run() -> None:
        try:
            learn_sites(hosts, keyword=keyword, log=log)
        except Exception as e:  # noqa: BLE001
            logger.info("站点学习失败（不影响本次结果）: %s", e)

    if inline:
        run()
        return

    t = threading.Thread(target=run, name="learn-sites", daemon=True)
    with _learn_lock:
        _learn_threads[:] = [x for x in _learn_threads if x.is_alive()]
        _learn_threads.append(t)
    t.start()


def wait_learn(timeout: float = 30.0) -> None:
    """等后台学站线程收尾（**只给测试用**，产品路径不需要等）。"""
    with _learn_lock:
        threads = list(_learn_threads)
    for t in threads:
        t.join(timeout)


def health_check(*, log: Optional[LogFn] = None, limit: int = 0) -> dict:
    """定期筛选：把来源库里记的书重开一遍，活着的续命、死掉的记一笔。

    只查「目录页还能不能打开、章数还对不对」，不抓正文 ——
    健康检查要便宜，能跑得起才有意义。
    """
    items = list(registry.books().items())
    if limit:
        items = items[:limit]
    if not items:
        return {"checked": 0, "ok": 0, "dead": 0, "removed": 0}

    ok = dead = 0
    pool = ThreadPoolExecutor(max_workers=min(DISCOVER_WORKERS, len(items)))
    futs = {pool.submit(_check_book, url, meta): url for url, meta in items}
    try:
        for fut in as_completed(futs, timeout=max(30.0, len(items) * 3.0)):
            try:
                good = fut.result()
            except Exception:  # noqa: BLE001
                good = False
            if good:
                ok += 1
            else:
                dead += 1
    except Exception:  # noqa: BLE001
        logger.info("来源库健康检查超时")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    removed = {"sites_removed": 0, "books_removed": 0}
    if dead:
        removed = registry.prune(only_dead=True)
    if log:
        try:
            log("来源库体检完成",
                f"存活 {ok} · 失效 {dead} · 清理 {removed['books_removed']} 本 / "
                f"{removed['sites_removed']} 站", True)
        except Exception:  # noqa: BLE001
            pass
    return {"checked": len(items), "ok": ok, "dead": dead, **removed}


def _check_book(url: str, meta: dict) -> bool:
    """体检一本书（被 `sweep` 定期调用）。

    这里就是「定期排查坏源」的执行体：一条条重开历史书目，
    连不上的把站也一并记一笔失败。**为什么失败原因要分类**：
    sweep 的结论会直接影响哪些站被降级，而"站挂了"和
    "这本书的 URL 过期了（站还在，是书被删/改了路径）"是两件事 ——
    只有前者该算站的账。
    """
    host = meta.get("host") or host_of(url)
    try:
        with fast_mode(retries=0, timeout=12.0):
            data = page_of(url, force=True)
    except Exception:  # noqa: BLE001
        # 网络层失败：站可能真的挂了 → 记站的账
        registry.note_book(url, host=host, ok=False)
        registry.note_site(host, ok=False, why=registry.FAIL_DOWN)
        return False

    toc = data.get("toc") or []
    if data.get("kind") != "toc" or len(toc) < 3:
        # 打开了但不像章节目录：多半是**这本书**的地址过期了，
        # 不是站不行 → 只记书的账，站最多记 shape（不计入"站点挂了"）
        registry.note_book(url, host=host, ok=False)
        registry.note_site(host, ok=False, why=registry.FAIL_SHAPE)
        return False

    registry.note_book(url, title=data.get("title") or meta.get("title", ""),
                       author=data.get("author") or meta.get("author", ""),
                       host=host, chapters=len(toc), ok=True)
    registry.note_site(host, ok=True)
    return True
