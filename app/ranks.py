"""热门榜单：从已适配的小说站抓「点击/推荐/收藏」这类榜单。

为什么做这个
------------
「发现」页原本只能靠书名去搜 —— 你得先知道想读什么。但很多时候人
只是想「看看有什么好看的」。榜单正好填这个空缺：别人已经替你筛过一遍了。

数据源怎么选的（2026-10-11 实测）
---------------------------------
来源库里当时有 9 个站点，逐个探过：

  ✅ **384g.com**（新笔趣阁）—— 榜单数据最全：
     `<table id="rankinglist">` 是干净的结构化表格，
     字段有 书名 / 最新章节 / 作者 / 字数 / 更新时间 / 连载状态，
     而且 10 类榜单（总点击 / 月点击 / 总推荐 / 总收藏 / 总字数…）
     **排名各不相同** —— 是真榜单，不是同一张列表换个标题。
     站点健康度 25 成功 / 0 失败。唯一要注意的是编码是 **GBK**。

  ✅ **luoxiaks.net**（落霞读书）—— 备选，作第二来源：
     `<li class="hot-book2">` 里带书名和作者，还有 /rank/monthvisit/ 等分类。
     字段比 384g 少（没有字数、状态），但能在 384g 抽风时兜底。

  ❌ 29zw / tadu / qidian —— 没有稳定的榜单页，或首页是 JS 渲染（HTML 抓不到东西）
  ❌ 月/周点击榜在 384g 上是**空表**（站点自己没数据，不是解析问题）——
     所以下面 SUPPORTED 里只留下确实有内容的那些

设计取舍
--------
* **缓存 30 分钟**。榜单变化很慢，而抓一次要跑好几个请求。
  更重要的是：别把人家站点当 CDN 刷 —— 这是免费的公开资源，
  高频拉取既不礼貌也容易被封。30 分钟对「看看有什么好书」完全够。
* **一站点失败不能拖垮整体**。每个来源独立 try，返回一部分也比全空好。
* **抓不到就降级**，不留空白页 —— 见 main.py 里 /api/ranks 的 fallback。
* **只抓首页那一页**（第 1 页）。翻页收益低、请求多，先不做。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

# 复用现有的抓取器：它已经处理了编码猜测（GBK→gb18030）、
# 同域限速、指数退避重试。自己再写一套只会两边不一致。
from .utils import fetch_text

# 缓存落盘的位置。为什么要落盘：进程一重启内存缓存就没了，
# 而「榜单」是那种**没人点也该是热的**东西 —— 用户打开发现页
# 不该先等 3 秒联网。落盘之后重启也能立刻出内容。
# `NOVEL_RANKS` 允许测试用另一份，别把生产缓存搅了。
_ROOT = Path(__file__).resolve().parent.parent
_DB = Path(os.environ.get("NOVEL_RANKS") or (_ROOT / "cache" / "ranks.json"))

# ---------------------------------------------------------------------------
# 榜单定义
# ---------------------------------------------------------------------------
# 只列出**实测有内容**的。384g 的 monthvisit / weekvisit / monthvote /
# weekvote 经实测返回的是空表（站点自己没数据），所以不放进来 ——
# 放进来只会让用户点开看到一片空白，还以为是程序坏了。
SUPPORTED: list[dict[str, str]] = [
    {"kind": "allvisit",   "label": "总点击榜", "desc": "历来被点开最多的"},
    {"kind": "allvote",    "label": "总推荐榜", "desc": "读者主动推荐最多的"},
    {"kind": "goodnum",    "label": "总收藏榜", "desc": "被收藏最多的"},
    {"kind": "size",       "label": "总字数榜", "desc": "篇幅最长的（适合想追长篇的）"},
    {"kind": "postdate",   "label": "最新入库", "desc": "站点新收录的"},
    {"kind": "lastupdate", "label": "最近更新", "desc": "更新最勤的"},
]
_KINDS = {d["kind"] for d in SUPPORTED}

_384G = "https://www.384g.com/paihang/{kind}_1.html"
_LUOXI = "https://www.luoxiaks.net/top.html"

# 每类榜单取前多少条。表格本来就是约 20 行，全取也行；
# 但 20 条已经足够「翻一翻」，多取只会让手机端页面变长。
MAX_ITEMS = 20


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def _clean(s: str) -> str:
    """去掉标签和多余空白，顺便把 &nbsp; 这类实体处理掉。"""
    s = re.sub(r"<[^>]+>", "", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    return re.sub(r"\s+", " ", s).strip()


def parse_384g(html: str, kind: str) -> list[dict[str, Any]]:
    """解析 384g 的榜单表格。

    结构（实测）:
        <table id="rankinglist">
          <tr><th>小说书名</th><th>最新章节</th>...</tr>
          <tr>
            <td><p><a href="/html/195/195679/">赵氏嫡女</a></p></td>
            <td><p><a href="/html/195/195679/118.html">第..章</a></p></td>
            <td><p>粽爷萌萌哒</p></td>
            <td><p>1057824字</p></td>
            <td><p>2023-09-10</p></td>
            <td><p>连载中</p></td>
          </tr>

    为什么按 `<tr>` 整行切、而不是按 `<td>` 抓：
    因为列的顺序是站点自己定的，某天加一列就会整体错位。
    按行切之后**靠「链接 + 内容特征」认列**，加列不容易崩。

    ⚠ 认作者这一列踩过坑：一开始的写法是「剩下的短文本里第一个当作者」，
    结果把「最新章节」那一格当成了作者 —— 因为像 `新书来了~` 这种
    章节名很短、也不带「第..章」的形状，启发式拦不住，
    页面上就出现了「作者：新书来了~」。
    现在改成**先按位置定位**：第一个 `td` 是书名、第二个是章节、
    第三个是作者 —— 这比猜内容形状可靠得多。特征识别只作为兜底。
    """
    m = re.search(r'id="rankinglist"([\s\S]*?)</table>', html)
    if not m:
        return []
    body = m.group(1)

    out: list[dict[str, Any]] = []
    for row in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", body):
        # 跳过表头
        if "<th" in row:
            continue

        # 书名 = 该行第一个指向书籍详情页的链接
        title_m = re.search(r'<a[^>]+href="(/html/\d+/\d+/?)"[^>]*>([^<]{1,60})</a>', row)
        if not title_m:
            continue
        url = "https://www.384g.com" + title_m.group(1)
        title = _clean(title_m.group(2))
        if not title:
            continue

        # ⚠ 关于「书名里带着作者名」：**这是源站自己的数据脏，不是解析 bug。**
        #   实测 size 榜前几行，站方把作者名拼进了标题链接文字里：
        #       <a href="/html/.../">乡下千金她又掉马甲了茶鸢</a>
        #   而它旁边那格才是作者「孙宝珠」——所以 title 和 author 并不重复，
        #   只是站方书名本身就写歪了（`茶鸢` 是笔名，被粘进了书名）。
        #   这里**故意不做**「把作者从书名尾巴上剪掉」这类清洗：第 3 行标题
        #   叫`茶鸢厉九泽`（笔名+男主名），剪掉`茶鸢`反而更错；而且任何
        #   按字符匹配的剪法都会误伤名字里恰好含这几个字的正常书。
        #   原样透出 + 交给用户判断，比「猜着修」诚实。

        cells = [_clean(c) for c in re.findall(r"<td[^>]*>([\s\S]*?)</td>", row)]

        # --- 按位置认列（主判据）---
        #   实测列序： 书名 | 最新章节 | 作者 | 字数 | 更新 | 状态
        #   但「最新章节」那一格偶尔会缺，所以不能死认第 3 个下标。
        #   做法：把「字数/日期/状态」这几格先挑出来（它们形状唯一、
        #   不会误判），剩下的格子按原顺序排，第 2 个才是作者。
        words = ""
        updated = ""
        status = ""
        rest: list[str] = []
        for c in cells:
            if not c:
                continue
            if re.fullmatch(r"\d+\s*字", c):
                words = c
            elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", c):
                updated = c
            elif c in ("连载中", "已完结", "完结", "全本"):
                status = c
            else:
                rest.append(c)

        # rest 里的顺序就是页面顺序：书名, 最新章节, 作者, ...
        # 书名已经单独拿过了，所以作者是「跳过书名后的第 2 个」。
        author = ""
        others = [c for c in rest if c != title]
        if len(others) >= 2:
            author = others[1]          # 0=最新章节, 1=作者
        elif len(others) == 1:
            # 只有一格：说明这行没给最新章节，那它就是作者。
            # 但要防它是「最新章节」而不是作者 —— 用长度和章节形状筛一下。
            cand = others[0]
            if not re.search(r"第.{0,8}[章节]|大结局|番外|^第[0-9一二三四五六七八九十百千]+", cand):
                author = cand

        out.append({
            "title": title,
            "author": author,
            "url": url,
            "source": "384g",
            "source_display": "新笔趣阁",
            "words": words,
            "updated": updated,
            "status": status,
            "kind": kind,
        })
        if len(out) >= MAX_ITEMS:
            break
    return out


def parse_luoxiaks(html: str, kind: str = "hot") -> list[dict[str, Any]]:
    """解析落霞读书的榜单。

    结构（实测）:
        <li class="hot-book2">
          <a href="https://www.luoxiaks.net/book_88745/" title="叶凡司空嫣然">
            <h2 class="pop-tit">叶凡司空嫣然</h2>
            <span class="pop-intro">家有绝色小姨</span>
          </a>
        </li>

    注意 `<h2 class="pop-tit">` 里是**书名**，`pop-intro` 里是**作者**
    （名字有点误导，实测确认过：斗罗大陆II绝世唐门 → 唐家三少）。
    """
    out: list[dict[str, Any]] = []
    for m in re.finditer(r'<li class="hot-book2">([\s\S]*?)</li>', html):
        block = m.group(1)
        hm = re.search(r'<h2 class="pop-tit">([^<]{1,60})</h2>', block)
        if not hm:
            continue
        title = _clean(hm.group(1))
        if not title:
            continue
        url_m = re.search(r'href="(https?://[^"]*/book_\d+/?[^"]*)"', block)
        url = url_m.group(1) if url_m else ""
        im = re.search(r'<span class="pop-intro">([^<]{1,40})</span>', block)
        author = _clean(im.group(1)) if im else ""

        out.append({
            "title": title,
            "author": author,
            "url": url,
            "source": "luoxiaks",
            "source_display": "落霞读书",
            "words": "",
            "updated": "",
            "status": "",
            "kind": kind,
        })
        if len(out) >= MAX_ITEMS:
            break
    return out


# ---------------------------------------------------------------------------
# 抓取 + 缓存
# ---------------------------------------------------------------------------
_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_TTL = 1800.0          # 30 分钟
_lock = threading.Lock()
# 抓取中标记：同一个人连点两次不该触发两次抓取
_inflight: set[str] = set()
_loaded = False


def _load_from_disk() -> None:
    """把上次落盘的榜单读回内存（只读一次，启动时用）。

    ⚠ 这里**故意不重置时间戳** —— 保留原抓取时刻，这样如果落盘
    至今已超过 TTL，读回来就是"过期"状态，下次访问会自然触发刷新。
    如果把它写成"刚刚抓的"，就会拿一份陈旧数据骗用户 30 分钟。
    """
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        raw = json.loads(_DB.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return          # 没有 / 坏了都当没有，下次抓
    if not isinstance(raw, dict):
        return
    for kind, blk in raw.items():
        if kind not in _KINDS or not isinstance(blk, dict):
            continue
        items = blk.get("items")
        ts = blk.get("ts")
        if isinstance(items, list) and items and isinstance(ts, (int, float)):
            _CACHE[kind] = (float(ts), [i for i in items if isinstance(i, dict)])


def _save_to_disk() -> None:
    """原子落盘。失败不抛 —— 缓存写不进去不该影响接口返回。"""
    try:
        _DB.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: {"ts": ts, "items": items} for k, (ts, items) in _CACHE.items()}
        tmp = _DB.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _DB)          # 原子替换，不会读到半个文件
    except Exception as e:  # noqa: BLE001
        print(f"  [ranks] 缓存落盘失败（不影响使用）：{e}", flush=True)


def cache_status() -> dict[str, Any]:
    """给界面/接口看的缓存体检：每类几条、多久前抓的、是否还新鲜。

    定时任务和界面上的「x 分钟前更新」都靠它。
    """
    _load_from_disk()
    now = time.time()
    out: dict[str, Any] = {"ttl": int(_TTL), "kinds": {}}
    for d in SUPPORTED:
        k = d["kind"]
        hit = _CACHE.get(k)
        if hit:
            age = now - hit[0]
            out["kinds"][k] = {
                "count": len(hit[1]),
                "age": int(age),
                "fresh": age < _TTL,
                "updated_at": int(hit[0]),
            }
        else:
            out["kinds"][k] = {"count": 0, "age": None, "fresh": False, "updated_at": None}
    ages = [v["age"] for v in out["kinds"].values() if v["age"] is not None]
    out["stale_count"] = sum(1 for v in out["kinds"].values() if not v["fresh"])
    out["oldest_age"] = max(ages) if ages else None
    out["total"] = sum(v["count"] for v in out["kinds"].values())
    return out


def _fetch_one(kind: str) -> list[dict[str, Any]]:
    """抓某一类榜单。两个来源都试，合并去重。

    单源失败不抛 —— 返回另一边的结果，或者空列表。
    """
    items: list[dict[str, Any]] = []

    # 1) 主源 384g
    try:
        html = fetch_text(_384G.format(kind=kind))
        items.extend(parse_384g(html, kind))
    except Exception as e:  # noqa: BLE001
        print(f"  [ranks] 384g {kind} 抓取失败：{e}", flush=True)

    # 2) 备选源 luoxiaks（只有一个总榜页，所以只在「总点击」时补）
    if kind == "allvisit":
        try:
            html = fetch_text(_LUOXI)
            extra = parse_luoxiaks(html, kind)
            seen = {i["title"] for i in items}
            for it in extra:
                if it["title"] not in seen:
                    items.append(it)
                    seen.add(it["title"])
        except Exception as e:  # noqa: BLE001
            print(f"  [ranks] luoxiaks 抓取失败：{e}", flush=True)

    return items[:MAX_ITEMS]


def get_rank(kind: str) -> list[dict[str, Any]]:
    """取某一类榜单（带缓存）。未知 kind 返回空列表。

    ⚠ 缓存策略是 **stale-while-revalidate（先给旧的，后台再去抓）**。
    改这里之前先读下面这段 —— 它修的是一个真实的首屏体验问题：

      原来：缓存过期后**同步**去抓（全量榜单要十几秒甚至几十秒）。
        症状：用户打开首页，榜单区一直转圈；服务冷启动 + 机器忙时
        实测能到 60 秒以上（ship 的并发真机测试就是被这个打红的）。
      现在：只要手上有上一份数据（哪怕过期很久），**立刻返回**，
        同时起一个后台线程去刷新。用户 0 秒看到榜单，几十秒后
        界面上的「x 分钟前更新」会自然变成"刚刚更新"。

    边界处理：
      · 从没有过缓存（首次部署）→ 只能同步等，没有别的选择；
      · 已有人在抓 → 不重复抓，直接把旧数据给他；
      · 抓取失败 → 旧数据留在缓存里不动（下面 `if items` 那句守着）。
    """
    if kind not in _KINDS:
        return []

    _load_from_disk()
    now = time.time()
    hit = _CACHE.get(kind)
    if hit and now - hit[0] < _TTL:
        return hit[1]

    # —— 缓存过期，但手上有旧数据 ——
    # 立刻还给用户，抓取丢后台。
    if hit and hit[1]:
        _kick_bg_refresh(kind)
        return hit[1]

    # —— 从来没有过缓存：只能同步等 ——
    # 已有别人在抓这一类 → 等它，别重复抓
    with _lock:
        hit = _CACHE.get(kind)
        if hit and now - hit[0] < _TTL:
            return hit[1]
        if hit and hit[1]:
            # 刚才那一瞬别人抓回来了，直接用
            return hit[1]
        if kind in _inflight:
            return hit[1] if hit else []
        _inflight.add(kind)

    try:
        items = _fetch_one(kind)
        if items:      # 只在真拿到东西时才覆盖缓存 ——
            _CACHE[kind] = (time.time(), items)   # 空的别把上次的好数据冲掉
            _save_to_disk()
            return items
        # ⚠ 抓空了（站点限流 / 抽风）—— **别急着返回空**。
        #   手上那份**过期**缓存对用户仍然远比空白页有价值。
        #
        #   踩过：384g.com 与 luoxiaks.net 双双进入冷却时，明明 cache/ranks.json
        #   里躺着 20 条旧榜，「总推荐榜」标签却是一片空白。原因就在上面那行
        #   `return items` —— 它把 stale 缓存彻底无视了。
        #   注意上面那句注释「空的别把上次的好数据冲掉」只管住了**写入**，
        #   没管住**返回**，于是文件头「抓不到就降级，不留空白页」的承诺
        #   在这里破了个洞。（这个洞**不报错**，只表现为"标签点开是空的"，
        #   人工回归很容易漏 —— 所以另配了 tools/test_ranks_stale.py。）
        if hit and hit[1]:
            return hit[1]
        return items
    finally:
        with _lock:
            _inflight.discard(kind)


# 后台刷新线程集合：防同一类榜单被同时刷两遍。
# 用 _lock 保护（和 _inflight 共用同一把锁，避免两套互斥量打架）。
_BG: set[str] = set()


def _kick_bg_refresh(kind: str) -> None:
    """起一个后台线程去刷新某一类榜单（不阻塞调用方）。

    ⚠ 为什么必须是 daemon 线程：服务被 Ctrl-C / 被 systemd 重启时，
    不能让一个抓取中的线程把进程吊住不退出（用户会遇到"关不掉"）。
    抓一半被杀没有副作用 —— 缓存要么是旧的完整数据、要么还没写入。
    """
    import threading

    with _lock:
        if kind in _inflight or kind in _BG:
            return          # 已经有人在抓了，别重复
        _BG.add(kind)

    def _work() -> None:
        try:
            items = _fetch_one(kind)
            if items:
                with _lock:
                    _CACHE[kind] = (time.time(), items)
                _save_to_disk()
                print(f"  [ranks] 后台刷新 {kind}：{len(items)} 条", flush=True)
            else:
                print(f"  [ranks] 后台刷新 {kind}：没抓到，保留旧数据", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  [ranks] 后台刷新 {kind} 失败：{e}", flush=True)
        finally:
            with _lock:
                _BG.discard(kind)

    threading.Thread(target=_work, name=f"ranks-bg-{kind}", daemon=True).start()


def refresh(kinds_: Optional[list[str]] = None, force: bool = True) -> dict[str, Any]:
    """主动刷新榜单。给定时任务和「立即刷新」按钮用。

    force=True 时**无视 TTL 重抓**（定时任务要的就是这个）；否则只补过期的。
    返回一份结果摘要，方便定时任务打日志。
    """
    _load_from_disk()
    want = [k for k in (kinds_ or [d["kind"] for d in SUPPORTED]) if k in _KINDS]
    started = time.time()
    now = time.time()
    targets = want if force else [
        k for k in want
        if not (_CACHE.get(k) and now - _CACHE[k][0] < _TTL)
    ]

    ok, failed, skipped = 0, 0, len(want) - len(targets)
    for k in targets:
        # ⚠ 别和后台自动刷新撞车：同一类榜单同时在抓两次，纯属浪费
        #   （第三方站有速率限制，多抓一次就多一分被限流的风险）。
        #   已经有后台线程在刷 → 跳过，等它写完缓存就是最新的了。
        #   注意也要计入 skipped —— 循环开始时那个 skipped 只算了
        #   "因 TTL 未过期而没进 targets 的"，这里是第二类跳过原因。
        with _lock:
            if k in _BG or k in _inflight:
                skipped += 1
                continue
        try:
            items = _fetch_one(k)
            if items:
                with _lock:
                    _CACHE[k] = (time.time(), items)
                ok += 1
            else:
                # 抓到空：多半是站点抽风。不覆盖旧缓存，计入 failed。
                failed += 1
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [ranks] refresh {k} 失败：{e}", flush=True)
    if ok:
        _save_to_disk()
    return {
        "ok": ok, "failed": failed, "skipped": skipped,
        "targets": targets, "elapsed": round(time.time() - started, 2),
        "status": cache_status(),
    }


def get_many(kinds: list[str]) -> dict[str, list[dict[str, Any]]]:
    """并发取多类榜单。用于「一次把所有标签的角标都填上」。"""
    _load_from_disk()
    kinds = [k for k in kinds if k in _KINDS]
    if not kinds:
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    # 3 个线程够了 —— 一共就 6 个请求，而且 utils 里有同域限速，
    # 开更多只会一起排队，反而更容易触发对方的风控。
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(get_rank, k): k for k in kinds}
        for f in as_completed(futs):
            k = futs[f]
            try:
                out[k] = f.result()
            except Exception:  # noqa: BLE001
                out[k] = []
    return out


def kinds() -> list[dict[str, str]]:
    """榜单目录，给前端渲染标签用。"""
    return [dict(d) for d in SUPPORTED]


def clear_cache() -> None:
    """清空内存+磁盘缓存。测试用；也留给「强制重来一次」。"""
    global _loaded
    with _lock:
        _CACHE.clear()
        _loaded = True
        try:
            _DB.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
