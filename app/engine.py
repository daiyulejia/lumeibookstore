"""下载调度器：多源并行搜索 → 相关性过滤 → 按书聚合 → 可用性探测 → 深度校验 → 入书架 / 下载。

一条搜索请求实际走过的路：

    1. 并行问所有来源           （谁先返回谁先展示，界面不空着）
    2. 相关性打分，砍掉噪音      （搜《微微一笑很倾城》不该出判决书）
    3. 按「书」聚合             （同一本书在 5 个站 = 1 张卡片，不是 5 条）
    4. 并发探测目录可达性        （能不能打开、多少章）
    5. 抽样读一章正文            （「目录能开」不等于「正文能看」，这一步才敢说可用）
    6. 排序、交给界面

点「开始阅读」后走的是另一条路：先入书架（缓存目录），阅读时按需补章节，
命中缓存就秒开 —— 详见 app/library.py。
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from .aggregate import group as group_books
from .errors import SourceBlocked
from .library import Library, book_id as lib_book_id
from .logging_setup import log_event
from .models import Book, BookResult, Chapter
from .relevance import CHAPTER_TITLE_RE
from .relevance import rank, score as score_result
from .sources import BUILTIN_SOURCES, DISCOVER_SOURCE
from .sourcehealth import HEALTH
from .sources.base import Source, note_for_exception, tidy_content
from .utils import fast_mode, fetch_text, host_of

logger = logging.getLogger("novel.engine")


def _log_trip(name: str, seconds: float, why: str) -> None:
    """把「熔断了多久」写成一句人话。

    ⚠ 为什么要有这个函数：原来这行日志是**写死**「熔断 15 分钟」——
    加了指数退避之后第二次是 30 分钟、第三次 60 分钟，写死的字就开始撒谎，
    而这种谎**不会报错**，只会让复盘的人按 15 分钟去推断现场。
    时长由 `note_fail()` 返回（真实值），这里只负责排版。
    """
    if seconds >= 3600:
        how = f"{seconds / 3600:.1f} 小时".replace(".0 ", " ")
    else:
        how = f"{max(1, int(round(seconds / 60)))} 分钟"
    logger.warning("源 %s 连续失败，熔断 %s（%s）", name, how, why[:120])

# 一次最多探测多少个候选
DEFAULT_PROBE_TOP = 14
PROBE_WORKERS = 6
# 探测总预算（秒），超时的候选标为「未验证」。
# 从 20s 收到 12s：候选早在第 1 秒就流式推给前端了，用户能立刻点。
# 探测只是**给卡片补状态徽标**（可读 / 目录 N 章 / 打不开），它不是
# 用户等待的必要条件 —— 让它拖到 20 秒是捡了芝麻。
PROBE_BUDGET = 12.0
STREAM_FLOOR = 45.0     # 边搜边推的临时门槛（低于它的候选不推给前端）
PROBE_PER_SOURCE = 4    # 单个来源最多探测几个的**上限**；实际配额还会按
                        # 实测速度收紧（见 Source.probe_limit）
# 「够用就停」：验出这么多可用候选就不再等剩下的了。
# 不设这个上限时，最坏情况要跑满 PROBE_BUDGET + SAMPLE_BUDGET ≈ 45 秒
# （搜《活着》实测 50s），而用户早在第 3 个可用来源出现时就该看到结果了。
PROBE_ENOUGH = 4

# ---------------------------------------------------------------------------
# 搜索阶段的「软截止」—— 修的是用户反馈的「一直显示正在从 N 个来源里找，很慢」
# ---------------------------------------------------------------------------
# 病灶：原来用 `as_completed(futures)` 等**全部**来源返回，于是总耗时 = 最慢
# 那个来源的耗时。实测（tools/diag_search.py）：
#     搜「活着」   → wyshu 花了 14.56s，而它贡献了 **0 条**结果
#     搜「都市」   → kunnu8 花了  7.86s，贡献 1 条
#     搜「三体」   → gutenberg 花 4.34s，贡献 **0 条**
# 也就是**一个什么都没找到的来源，决定了用户要盯着「正在找…」看多少秒**。
# 这是纯粹的浪费 —— 用户要的是「尽快看到书」，不是「等所有站都答完」。
#
# 修法三层：
#   ① 软截止 SEARCH_SOFT_DEADLINE：**已经有结果**时到点就收手，不等剩下的。
#      慢源不是「没用了」而是「来不及了」—— 它晚到的结果对本次没意义。
#   ② 够用即停 SEARCH_ENOUGH：已经攒够候选，且最慢的还在跑，
#      就不必再等 —— 快源通常 1~2s 就答完了。
#   ③ 没结果时用硬上限 SEARCH_HARD_DEADLINE：一条都还没搜到的 `elapsed` 里
#      **不允许**被软截止收手。因为源内部是串行多请求的（wyshu 试十来个路径
#      才死心），「答完」天然可能 8~10s；6 秒就收只会把所有源饿死、返回空。
#      这是实测踩出来的：早先无条件 6s 收手，斗破苍穹/活着/诡秘之主全 0 条。
#
# ⚠ 另一个必须记住的坑：不能用 `for fut in as_completed(futs):` 再在循环体里
#   判 elapsed。as_completed 本身是阻塞的 —— 没有 fut 完成就不进循环体，
#   一批源集体慢的时候那个「墙钟上限」形同虚设（实测 6 个源集体拖到 10.8s，
#   循环体一次都没跑）。必须给 as_completed 传 timeout，循环轮询。
#   但不能一把梭 `as_completed(futs, timeout=)` 让它抛异常了事 —— 那样会把
#   「已返回、只是这一轮还没轮到处理」的结果一起丢掉。
SEARCH_SOFT_DEADLINE = 6.0   # 有结果时的墙钟上限（秒）
SEARCH_ENOUGH = 12           # 攒够这么多条候选就可以提前收手
SEARCH_MIN_WAIT = 1.5        # 但至少等这么久，免得第一个快源刚回来就收摊
# 「已经拿到结果、且已经不止一个源答过」→ 再给一点时间（这个秒数）就收手。
#
# 这一条是本轮提速的主力。实测（搜「斗破苍穹」逐源计时）：
#     xbqg5200 1.15s → 8 条      wikisource 1.50s → 20 条
#     gutenberg 3.54s → 0 条      kunnu8 3.81s → 2 条
#     xbiquge  5.82s → 17 条     wyshu 6.98s → **0 条**
# 第 2 个源 1.5 秒就已经拿到 20 条了，却因为要等 0 条的 wyshu，用户多盯了 5 秒。
# 所以：**已经有结果、且已经有两个以上源答完**，那就是「够用了」，
# 再宽限 SEARCH_GRACE 秒收手即可 —— 不必等那个什么都找不到的慢源。
SEARCH_GRACE = 3.5
# 冷门书名（像「斗破苍穹」只命中 1 条）永远攒不到 SEARCH_ENOUGH 条，
# 于是每次都要干等满软截止 —— 这就是用户抱怨的「点一本书要等很久」的来源。
# 修法：**不再以「攒够多少条」为唯一门槛**，改成看「有多少个源已经答完」。
# 只要手上有结果、且绝大部分源都回来了，剩下那一两个慢源晚到的结果毫无价值。
SEARCH_ANSWERED_RATIO = 0.75  # 已答源占比达到这个数就可以收手（有结果的前提下）
# 硬上限：**一个结果都还没搜到**时最多等这么久。
#
# 为什么软截止（6s）不能无条件生效：源内部往往要**串行发多次请求**才能得出结论
# —— 比如 wyshu 会依次试 `/yq/x/ /wl/x/ /ds/x/ /xy/x/ ...` 十来个路径，全 404
# 才算答完。这种源的「答完时间」天然 > 6s。如果 6 秒到点就不管有没有结果一律
# 收手，会把它们全部饿死，出现「搜什么都 0 条」这种**比慢更糟**的结果。
# （实测踩过：加了无条件看门狗之后 斗破苍穹/活着/诡秘之主 全部 0 条。）
#
# 所以策略是：**有结果才允许提前收手；没结果就继续等，最多等到这个硬上限**。
SEARCH_HARD_DEADLINE = 20.0

# ---------------------------------------------------------------------------
# 「总预算」—— 修的是「搜一本书要等 30 秒」这个**契约被违反**的问题
# ---------------------------------------------------------------------------
# 病灶：20 秒硬上限只管**搜索扇出**那一段。扇出结束后还有两个阶段各自
# 按**固定的满额预算**开跑：
#     探测 probe_all      → PROBE_BUDGET  12s
#     抽样 verify_samples → SAMPLE_BUDGET 10s
# 三段相加最坏 42 秒，而且每一段都"不知道前面已经花掉多少"。
#
# 线上实测（2026-10-21，搜《重生之爷太重口了》）：
#     02:11:56  search.done 耗时ms=20771
#     02:13:59  search.done 耗时ms=20577
#     02:17:47  search.done 耗时ms=30313   ← 20s 扇出 + 10s 探测/抽样
# 用户看到的是「点了搜索，三十秒后才有结果」——而我们对外说的是 20 秒上限。
# 这种违约最恶劣的一点是**不报错**：每段都"在自己预算内正常完成"。
#
# 修法：给整轮搜索一个总预算，后面每一段的预算 = min(本段满额, 总预算 - 已耗)。
# 省下来的顺序是**先砍抽样、再砍探测**：抽样只是补一个"正文真能读"的绿标，
# 探测补的是"目录能打开 + 章节数"，而候选本身第 1 秒就已经流式给前端了。
# 两者都不该让用户多等一秒。
SEARCH_TOTAL_BUDGET = 22.0
# 给抽样预留的秒数。不预留给 10s 满额是因为抽样有 SAMPLE_ENOUGH=3 的
# 提前收手，正常的书 1~2 秒就够；留 6 秒是"够用且不挤占探测"的折中。
SAMPLE_RESERVE = 6.0
# 联网兜底（本地一条都没有 → 出去搜）单独一个**更大但仍有上限**的总预算。
# 为什么可以更大：用户要的是"搜到"，本地全灭时唯一的出路就是联网，
# 这时候提前收手等于直接交出 0 条。但仍必须有上限 —— 不然"尽力找"
# 就会退化成"永远在转圈"（实测串行联网能拖到 33s）。
DISCOVER_TOTAL_BUDGET = SEARCH_TOTAL_BUDGET + 10.0

# 并行联网兜底的预热阈值：本地零产出时，等过这个时间就把联网兜底
# **并行**发出去（本地慢源继续等，谁先出结果用谁）。
#
# 设成和 SEARCH_MIN_WAIT 一致（1.5s）：本地快源 1~2s 出结果就不触发，
# 省一次联网请求；本地全灭则提前到 1.5s 就开始联网，把"33s 串行"压到
# ~20s 并行。
#
# ⚠ 不降低 SEARCH_HARD_DEADLINE —— 用户明确要求"搜到最重要"，
#   降上限会牺牲召回。并行是纯收益：不牺牲召回、只省串行等待。
SEARCH_WEB_PREEMPT = 1.5

# 深度校验：对最靠前的这几个「可用」候选抽一章正文验证
SAMPLE_TOP = 8
SAMPLE_WORKERS = 4
# 抽样预算从 15s 收到 10s。同理，抽样是**锦上添花的绿标**，
# 不是「能不能读」的前提（没抽到的如实标「未验证」，不骗人）。
SAMPLE_BUDGET = 10.0
SAMPLE_PER_SOURCE = 2   # 同一来源最多抽样几本（抽样各要一次跨页请求）
SAMPLE_ENOUGH = 3       # 验够几本正文本就收手


def budget_slice(t_start: float, want: float,
                 total: float | None = None) -> float:
    """本轮还剩多少秒可以给这一阶段用。

    返回 0 表示"总预算已经用完了"——**调用方必须如实说出来**
    （打一条日志 / 在 stats 里标出来），不能静默跳过：
    静默跳过会让"没探测"和"探测过但都不可用"看起来一模一样，
    前端就会把一批没验证过的候选显示成"未验证"，而复盘时无从分辨。

    want 是本阶段的满额预算，total 是整轮搜索的总墙钟上限。

    ⚠ total 的默认值写成 None 再在函数体里取模块常量，**不是多此一举**：
      写成 `total: float = SEARCH_TOTAL_BUDGET` 是在 def 那一刻求值，
      之后无论怎么改模块里的 SEARCH_TOTAL_BUDGET，这个默认值都还是老数字。
      踩过这个坑——测试里把总预算调到 1 秒，函数照样按 22 秒算，
      于是"总预算被尊重"的判据**恒绿**，等于没测。
    """
    if total is None:
        total = SEARCH_TOTAL_BUDGET
    left = total - (time.time() - t_start)
    return max(0.0, min(want, left))


def source_meta(src: Source) -> dict:
    """来源的展示元信息。

    抽成函数是为了让 /api/sources 和 /api/sources/check 用同一份字段定义 ——
    前端「来源健康检查」抽屉要展示「这条是内置的还是自动适配的、走的什么引擎、
    章节要不要拼页」，两边字段名必须对得上，否则界面会一半有值一半空。
    """
    return {
        "kind": getattr(src, "kind", "builtin"),
        "engine": getattr(src, "engine", "") or "",
        "priority": getattr(src, "priority", 100),
        "homepage": getattr(src, "homepage", "") or getattr(src, "base_url", ""),
        "has_search": bool(getattr(src, "has_search", True)),
        "chapter_paged": bool(getattr(src, "chapter_paged", False)),
    }


def source_ledger(stats: dict) -> dict:
    """把「源账」摊成 search.done 里那四个字段 —— 每一格都带名字。

    为什么要专门一个函数
    --------------------
    复盘日报每天要回答的第一个问题是「这本书为什么搜不到」。以前那行日志是

        答=3/7 超=4 挂=wikisource,xbqg5200

    `答` 其实是「把结果交回来的源数」（交回来的可以是 403 的源），
    `超` 其实是「收手时还没回来的个数」，而 `挂` 里的源又**混在这两个数里** ——
    3 + 4 = 7 已经等于总数，再挂两个名字就是 9 > 7，账根本加不起来。
    线上 2026-10-22 00:10 就是这么一行，逼得人回头去翻散落的 source.fail。

    现在四格互斥、都带名字，加起来必须等于总数：

        答=真的答了话   挂=返回了但挂了   未回=到点没回来   熔断=该搜没搜   到点=是否撞满墙钟

    `未回` 尤其重要：线上真机 10 次搜索里有 9 次 `未回=1~2`，
    而那些源只是慢、并没有死。没有名字就永远查不出"到底是谁在拖"。

    `熔断` 是 2026-10-25 补的第五格。原来被熔断跳过的源**根本不进账**：
    分母是过滤后的源数，于是"全部目标源都在熔断"算出来是 `答=0/0`——
    一个加得起来、却完全没有信息量的账（线上 10-24 09:04:59 的
    《红楼梦》《剑来》就是这行，耗时 2ms、候选 0，复盘时只能靠人肉
    反推"是不是熔断了"）。它们必须单独占一格并带名字，
    否则"没这本书"和"这个源这个月就没通过"永远长得一模一样。
    """
    names_fail = list(stats.get("failed_returned_sources") or [])
    names_unret = list(stats.get("unreturned_sources") or [])
    names_brk = list(stats.get("breaker_sources") or [])

    def _pack(n: int, names: list[str]) -> str:
        return f"{n}" + (f"({','.join(names)})" if names else "")

    return {
        "答": f"{stats.get('sources_answered', 0)}/{stats.get('sources_total', 0)}",
        "挂": _pack(stats.get("sources_failed", 0), names_fail),
        "未回": _pack(stats.get("sources_unreturned", 0), names_unret),
        "熔断": _pack(stats.get("sources_breaker", 0), names_brk),
        # ⚠ 判「是不是慢到没结果」不能用 `耗时ms>=20000`：耗时是环境量，
        #   机器一忙就漂，同一本书能差 5 倍。这个布尔量只取决于机制。
        #
        # 而且**不能直接用 hit_deadline**：它的语义只是「最后一次等待窗口
        # 空手而归」，有结果之后把软截止等完也是 True（正常提速路径）。
        # 复盘真正要分的是「一条都没出、硬等到底」—— 那才是慢到没结果，
        # 和「有结果、只是收手时还有源没回来」处置完全不同。
        #
        # ⚠ 2026-10-26 修口径：判据从 `kept` 换成 `pushed`。
        #   `kept` 是**搜索结束后**才有的数（rank 之后），而用户等的是过程中
        #   有没有东西出来。两者之间夹着一段真实存在过的带子：
        #     best<70 → rank 的显示门槛 28 分，而推送门槛是 45 分
        #     ⇒ 28~45 分的候选「最后会显示、过程中一条都不推」
        #   这种轮子在**旧口径下报「卡满=否」**（因为 kept>0），
        #   于是"用户盯着'正在从 7 个来源里找'看了 20 秒、一个字都没见到"
        #   这件事，在日报里根本不存在。
        #   换成 `pushed` 之后：撞满墙钟 + 一条都没推 = 卡满，与"真没有"同格，
        #   再靠 `候选=` 区分「有候选但都太弱」与「压根没有」。
        "卡满": "是" if (stats.get("hit_deadline")
                          and not stats.get("pushed")) else "否",
    }


def _pool_note(pool_before: int) -> str:
    """把「开搜时可搜源 → 收尾时可搜源」摊成 `22→15`。

    差值就是**这次搜索顺手废掉的搜索模板数**：某个站连续 3 次抽不到书链接，
    `registry.note_search_result` 就把它的 `search_tpl` 清空、退出可搜池。

    2026-10-30 09:21 的线上实例（就是它催生了这个字段）：连搜《乡土中国》
    《素食者》《我的阿勒泰》三本冷门书，8 个站的模板当场被作废、可搜源
    22 → 15，而当天的 `search.done` 里只有「候选=0」—— 源池缩水这件事
    在日志里**一个字都没有**，是靠事后 diff registry.json 才发现的。

    ⚠ 取不到就打 `?`，**不补 0**：`0→0` 会被读成"源池空了"，那是另一件事
      （和 10-25「答=0/0 看起来干净、其实零信息」是同一类坑）。
    """
    if not isinstance(pool_before, int) or pool_before < 0:
        return "?"
    try:
        from . import registry as _reg
        after = len(_reg.searchable_sites())
    except Exception:  # noqa: BLE001
        return "?"
    return f"{pool_before}→{after}"


class Engine:
    """管理所有来源，提供搜索、探测、书架、阅读与下载。"""

    def __init__(self, sources: list | None = None, library: Library | None = None):
        self.library = library or Library()
        self._sources: list[Source] = []
        self._install(sources if sources is not None else BUILTIN_SOURCES)

    def _install(self, items: list) -> None:
        for item in items:
            try:
                # 支持两种形式：类（会实例化）和已经实例化的对象
                obj = item() if isinstance(item, type) else item
                if getattr(obj, "enabled", True):
                    self._sources.append(obj)
            except Exception as e:  # noqa: BLE001
                logger.warning("初始化源 %s 失败: %s", item, e)
        self._sources.sort(key=lambda s: s.priority)

    def reload_sources(self) -> int:
        """重新读一遍来源（含 sites.json 里新增的适配来源）。

        自动适配成功后调用 —— 让用户刚适配好的站点立刻能用，
        而不用重启服务。已存在的同名来源会被新的替换掉。
        """
        from .sources import BUILTIN_SOURCES as FRESH

        old = {s.name: s for s in self._sources}
        fresh: list[Source] = []
        for item in FRESH:
            try:
                obj = item() if isinstance(item, type) else item
                if getattr(obj, "enabled", True):
                    fresh.append(obj)
            except Exception as e:  # noqa: BLE001
                logger.warning("重载源 %s 失败: %s", item, e)
        # 保留那些不在 BUILTIN 里、但运行时动态装进来的源
        names = {s.name for s in fresh}
        fresh.extend(s for n, s in old.items() if n not in names)
        fresh.sort(key=lambda s: s.priority)
        self._sources = fresh
        return len(fresh)

    @property
    def sources(self) -> list[Source]:
        return self._sources

    # ==================================================================
    # 搜索
    # ==================================================================
    def search(
        self,
        keyword: str,
        on_result: Optional[Callable[[BookResult], None]] = None,
        on_verified: Optional[Callable[[BookResult], None]] = None,
        probe: bool = True,
        probe_top: int = DEFAULT_PROBE_TOP,
        sample: bool = True,
        only: Optional[list[str]] = None,
        stats: Optional[dict] = None,
        discover: bool = True,
        on_progress: Optional[Callable[[str, str, bool], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> list[BookResult]:
        """并行搜索所有源 → 打分去噪 → 并发探测 → 抽样校验。

        on_result:   每搜到一批候选就回调（先让界面有东西显示）
        on_verified: 每个候选探测/校验完成时回调（界面据此更新状态徽标）
        only:        只搜索这些来源（None = 全部）
        stats:       传入一个 dict，会填入本次搜索的统计信息
        discover:    本地来源全军覆没时，要不要联网出去找
        on_progress: 步骤级进度回调 on_progress(标题, 详情, 是否成功)
                     （目前只有「联网发现」会推，界面用它显示「正在联网找…」）
        should_stop: 返回 True 时**立刻收手**。用于「客户端已经断开」——
                     没人看结果了，就没必要为了"完整"去把每个来源都打完、
                     把每个候选都探测一遍；那是在白烧 CPU、网络和站点的
                     限速配额。默认 None = 永不主动停。
        """
        keyword = keyword.strip()
        if not keyword:
            return []

        # 「这一轮有没有真的被打断过」——所有阶段的收手都汇到这一处。
        # ⚠ 以前这个问题只由 `verify_samples`（采样）一个阶段回答，于是断开
        #   如果落在**扇出抓取 / 探测 / 联网兜底**那几个阶段，收手确实发生了
        #   （那些阶段都认 should_stop、也确实提前停了），但 `aborted` 仍然
        #   是 False —— 对外报的是"这一轮完整跑完了"。
        #   后果不只是数字不准：真机断连测试的判据就是它，于是那条测试
        #   能不能过**取决于那 2 秒掐断恰好落在采样窗口里**（窗口很窄），
        #   表现为"时绿时红的偶发假红"——而偶发假红最容易把真问题一起
        #   糊过去。`aborted` 的语义既然是"这一轮被打断"，就该由**所有**
        #   阶段的收手信号共同决定，所以在唯一入口 `_stop()` 里统一置位。
        cut_short = False

        def _stop() -> bool:
            # 一次调用里包一层，避免到处都是 `is not None and ...()`
            nonlocal cut_short
            if should_stop and should_stop():
                cut_short = True
                return True
            return False

        # 「这一轮是不是被客户端断开打断的」——供 stats / 日志 / 真机测试读。
        # ⚠ 必须在**分支之外**先初始化。踩过：一开始只在 `if sample and results:`
        #   里 `aborted = self.verify_samples(...)` 赋值，结果 `sample=False`
        #   的调用路径（联网兜底测试就是 `probe=False, sample=False`）走到
        #   `stats.update({"aborted": bool(aborted)})` 时 UnboundLocalError。
        #   ship 的静态自检当场把它拦下来了 —— 这正是"每次改完跑全量"的意义。
        aborted = False

        # —— 多词关键词：「搜索用词」与「排序用词」要分开 ——
        # 用户搜「余华 活着」时，把整串丢给站点搜索多半 0 结果（站点的搜索框
        # 不是全文检索，空格常常被当成书名的一部分）。但排序又必须用**完整
        # 关键词**，否则「书名 + 作者」这个约束就丢了（见 relevance.score_multi）。
        #
        # 所以：搜索用**最长的那个词**（书名通常比作者名长），排序用整串。
        #   搜「余华 活着」      → 站点搜「活着」，排序按「书名 且 作者」
        #   搜「顾漫 微微一笑很倾城」→ 站点搜「微微一笑很倾城」
        # 为什么不挑"最小的"或"第一个"：用最长词最接近"用户在找的那本书"，
        # 而且本站的搜索是**词级**匹配，用短词（作者名）搜出来的候选里
        # 混着一堆同作者的其他书，排序阶段再滤一遍，浪费配额。
        #
        # ⚠⚠ 但「取最长」单独用会漏召回 —— 实测踩到的坑：
        #     搜「余华 活着」时两个词**等长**（都 2 字），max() 返回**第一个**
        #     「余华」，于是拿作者名当书名去搜，站点返回的全是余华的书
        #     （《兄弟》…），《活着》**根本没进候选池** —— 排序再准也无从谈起。
        #   修法：并列最长时把**所有**并列词都搜，结果合并后再按完整关键词排序。
        #     这样「余华 活着」会同时搜「余华」和「活着」，两边候选池加起来，
        #     正主《活着》在池子里，score_multi 才能把它顶到第一。
        from .relevance import _split_terms
        _terms = _split_terms(keyword)
        if len(_terms) > 1:
            _mlen = max(len(t) for t in _terms)
            _ties = [t for t in _terms if len(t) == _mlen]
        else:
            _ties = []
        search_kws = _ties if _ties else [keyword]

        t_start = time.time()
        # ---- 「可搜源池」开搜前数一遍（2026-10-30 补的埋点）----
        # 为什么要这个数：源池会**被搜索本身吃掉**。`registry_source._search_one`
        # 抽不到书链接时会记一次 `search_shape`，连记 3 次就把模板作废、站退出
        # 可搜池（`registry.note_search_result`）。线上实测（2026-10-30 09:21）：
        # 三本冷门书（乡土中国/素食者/我的阿勒泰）连着搜一遍，**8 个站的模板
        # 当场被作废**，可搜源 22 → 15，而 `search.done` 里只有「候选=0」——
        # 源池缩水这件事在日志里一个字都没有，是靠事后翻 registry.json 才发现的。
        # 所以把「开搜时几个」写进 stats，`search.done` 里和收尾数拼成 `源池=22→15`：
        # 一次搜索有没有顺手废掉几个源，一眼就能看出来。
        # ⚠ 取不到就给 -1（"不知道"），**不许**用 0 冒充 —— 0 会被读成"源池空了"。
        try:
            from . import registry as _reg
            _pool0 = len(_reg.searchable_sites())
        except Exception:  # noqa: BLE001
            _pool0 = -1
        # 「懒惰来源」（联网发现）不参与常规扇出 —— 它一次要跑两个搜索引擎
        # 外加十几个站点的核实，每搜一次都捎上它，所有搜索都会慢一截。
        targets = [s for s in self._sources if not getattr(s, "lazy", False)]
        if only:
            want = {s.strip() for s in only if s.strip()}
            targets = [s for s in self._sources if s.name in want]

        # ---- 熔断：打不通的源别再占着日历 ----
        # 线上实测（2026-10-21）：同一个书名两次搜索，一次 0 条卡满 20s、
        # 一次 1 条 —— 差别只在"哪几个源先回来"。而维基文库（SSL 握手超时）、
        # xbqg5200（403）这类源**每次都在名单里**，每次都要陪它们等满 20 秒。
        # 熔断之后它们连请求都不发，剩下的源更快答完，收手判定也更准。
        # ⚠ 只跳过"连续挂过"的源；空结果不算挂（见 app/sourcehealth.py）。
        skipped = [s.name for s in targets if not HEALTH.allows(s.name)]
        # 「指定了、但压根没有这个源」—— 和熔断是两件事，后果却一样：
        # 一个请求都不发，2 毫秒后返回 0 条。以前连一行日志都没有。
        missing: list[str] = []
        if only:
            _have = {s.name for s in self._sources}
            missing = sorted(n for n in (w.strip() for w in only) if n and n not in _have)
            if missing:
                logger.info("指定来源不存在，已忽略：%s（现有源里没有这些名字）",
                            ", ".join(missing))
        if skipped:
            targets = [s for s in targets if s.name not in skipped]
            logger.info("跳过 %d 个熔断中的源（%s），剩 %d 个照常扇出",
                        len(skipped), ", ".join(skipped), len(targets))
            if not targets:
                # 全灭：这不是"没有这本书"，是**一个请求都没发出去**。
                # ⚠ 这种 0 条在 `search.done` 里和"搜遍了都没有"长得一模一样
                #   （答=0/0、耗时ms=2），复盘时会被当成书库缺口去补源。
                #   线上真出现过（2026-10-24 09:04:59《红楼梦》《剑来》），
                #   当时靠人肉反推"是不是熔断了"，所以这里必须说出来。
                logger.info("本轮一个源都没能搜：目标源全部在熔断中（%s）——"
                            "结果为空不代表没有这本书", ", ".join(skipped))

        raw: list[BookResult] = []
        # 这一轮**挂了**的源名（抛异常 / 自己吞了异常 / 墙钟到点仍不返回）。
        # 为什么要单独攒一份而不是只打日志：
        #   `search.done` 里只有「候选=0」这一个数字，复盘时**分不清**
        #   「书真的没有」和「源全挂了」—— 今天就是靠散在几行日志里的
        #   403 / 握手超时反推的，白烧半小时。把名字带进 stats，
        #   search.done 就能一眼看出是哪种。
        failed_sources: set[str] = set()
        # ---- 源账：每个源**最终**落在哪一格（四类互斥，不重叠） ----
        # ⚠ 之前只有 done_count 一个数字，于是日志里的 `答=3/7` 是
        #   「3 个源把 future 交回来了」，**交回来的可以是挂掉的源**
        #   （403 / 握手超时都算"返回了"）。后果是复盘时数字加不起来：
        #   线上 2026-10-22 00:10 那行 `答=3/7 超=4 挂=wikisource,xbqg5200`，
        #   3 + 4 = 7 已经等于总数，再挂两个名字就成了 9 > 7 ——
        #   谁也不敢拿它下结论，结果还是要去翻散落的 source.fail。
        #   所以改成显式记账：ok（真的答话）/ fail（返回了但挂了）/
        #   hang（到点都没回来）/ skip（压根没轮到跑就被取消）。
        #   四格之和必须等于 sources_total，对不上就当场说出来。
        outcome: dict[str, str] = {}
        outcome_lock = threading.Lock()

        def _mark(name: str, kind: str) -> None:
            """给源记一笔。**先写先得**：卡死后才姗姗来迟的结果不改判。"""
            with outcome_lock:
                outcome.setdefault(name, kind)

        lock = threading.Lock()
        # 「已推给前端的条数」。**不能拿 len(raw) 当「有结果」的判据** ——
        # raw 里可能全是噪声（实测搜「诡秘之主」raw=20 条但去噪后 0 条），
        # 那种情况下用户界面上依然是空的，用软截止收手等于骗自己。
        streamed = 0
        # 「其中有多少条是**确切命中**」（title 基本等于搜索词，见
        # relevance.tightness）。streamed 只说明"过了相关性门槛"，
        # 门槛是宽的：搜《兄弟》时「嘿兄弟」「兄弟盟」「盛唐兄弟」全都过。
        # 真正决定"用户这次搜到了没有"的是这个数，所以它必须单独计数 ——
        # 见下面收手判据和 search.done 的 `确切=`。
        tight_streamed = 0

        # ---- 并行联网兜底 ----
        # 本地全灭时不必"等满 20s 硬上限再串行联网"——可以本地继续等、
        # 联网同时跑，谁先出结果用谁。把"本地全灭"场景从 33s 压到 ~20s，
        # 且不牺牲召回（本地慢源晚到的真结果照样能用）。
        # 触发条件刻意保守：只在「本地零产出 + 过 SEARCH_WEB_PREEMPT」时
        # 才提前发起；本地快源出结果就不触发，省一次联网请求。
        web_target = self._find_source(DISCOVER_SOURCE) if discover else None
        web_thread: Optional[threading.Thread] = None
        # ⚠ `web_extra` 是**跨线程写、主线程读**的：工作线程整体赋值（不是 append），
        #   主线程在 join 之后读。裸 list 变量在这两个动作之间没有 happens-before，
        #   CPython 下虽然大概率能看见，但这是**依赖实现细节的正确性** ——
        #   哪天换成 append 累加、或有人把 join 挪到别处，就会读到一个空列表
        #   并且**静默**丢掉整批联网结果（表现：兜底跑完了，用户还是 0 条）。
        #   用一个带锁的小盒子，把"取回结果"这件事变成显式的同步点。
        web_box: dict[str, list[BookResult]] = {"items": []}
        web_box_lock = threading.Lock()

        def _run(src: Source):
            try:
                src.set_log(on_progress)
                # 清掉上一次可能残留的"吞掉的异常"（线程局部跨搜索保留）。
                # 不清的话，上一轮失败的源这一轮答得好好的，也会被算成挂。
                if hasattr(src, "take_error"):
                    src.take_error()
                # 搜索结果用 search_kws（多词时取最长词，并列最长时全搜，见上）；
                # 后面排序/去噪仍然用完整的 keyword。
                items = []
                seen_u: set[str] = set()
                for _kw in search_kws:
                    for it in (src.search(_kw) or []):
                        u = getattr(it, "url", "") or ""
                        if u and u in seen_u:
                            continue
                        seen_u.add(u)
                        items.append(it)
                for it in items:
                    it.source_display = src.display
                # 「答话了」——**哪怕返回空列表**也要记成功。
                # 空结果只是"这个源没有这本书"，是正常业务结果；
                # 把它算失败的话，搜几本冷门书就会把所有源全拉黑，
                # 之后搜什么都 0 条，而且完全静默。
                #
                # ⚠ 但「空结果」有两种，必须分开（2026-10-21 线上实测）：
                #   ① 真的答话了、就是没这本书  → note_ok（绝不能拉黑）
                #   ② 源**内部**把异常吞了、于是返回 []  → 这是"挂"，要记熔断
                #   ②以前被当成了①：`novel.wikisource` 一天 110 次 SSL 握手超时、
                #   `xbqg5200` 55 次 403，而熔断日志 0 条 —— 熔断器根本没收到过失败，
                #   于是每次搜索都还在名单里陪它们等满 20 秒。
                err = src.take_error() if hasattr(src, "take_error") else ""
                if items or not err:
                    _mark(src.name, "ok")
                    HEALTH.note_ok(src.name)
                else:
                    _mark(src.name, "fail")
                    failed_sources.add(src.name)
                    log_event(logger, "source.fail", 源=src.name, 原因=err[:160])
                    cd = HEALTH.note_fail(src.name, err)
                    if cd:
                        _log_trip(src.name, cd, err)
                return items
            except Exception as e:  # noqa: BLE001
                # 单个来源挂掉是常态（站点会抽风、会改版、会拦爬虫），
                # 不该升级成"搜索失败"。但要留下可筛的记录：
                #   grep 'source.fail' logs/app.log  就能看出哪个源最近老出问题
                log_event(logger, "source.fail", 源=src.name,
                          原因=f"{type(e).__name__}: {e}")
                failed_sources.add(src.name)
                _mark(src.name, "fail")
                # 记进熔断器：连续挂到阈值就把这个源暂时摘出扇出名单，
                # 别让「永远打不通的源」每次都吃掉 20 秒墙钟。
                cd = HEALTH.note_fail(src.name, e)
                if cd:
                    _log_trip(src.name, cd, f"{type(e).__name__}: {e}")
                return []
            finally:
                src.set_log(None)

        # ---- 带软截止的扇出（见文件头 SEARCH_SOFT_DEADLINE 那段注释）----
        #
        # ⚠ 这里踩过一个很隐蔽的坑：最初写成
        #     for fut in as_completed(futs):
        #         ...判断 elapsed 再 break
        #   看起来有软截止，**其实是假的**。`as_completed` 本身是阻塞的 ——
        #   只有当「至少有一个 fut 完成」时才会进循环体，才有机会看 elapsed。
        #   如果这一批源全都慢（实测有一次 6 个源集体拖到 10.8s 才答完），
        #   前 10.8 秒里循环体一次都没执行，那个 6 秒的墙钟上限形同虚设。
        #   修法：给 `as_completed` 传 timeout，把自己变成「每次最多等这么久」，
        #   TimeoutError 就当作「该收手了」的信号，跳出。
        #
        # 也不能直接用 `as_completed(futures, timeout=)` 一把梭：它一超时就抛，
        # 会把「已经返回、只是这一轮还没轮到处理」的结果一起丢掉。所以要
        # 循环调用 —— 每轮拿一批已完成的结果，超时就收手。
        t_search = time.time()
        pool = ThreadPoolExecutor(max_workers=min(8, len(targets) or 1))
        futs = {pool.submit(_run, s): s for s in targets}
        done_count = 0
        pending = set(futs)

        def _pend_names() -> list[str]:
            """还没回来的源名 —— 日志里只给个数，复盘时永远查不出"谁在拖"。"""
            return sorted(futs[f].name for f in pending if f in futs)
        # 「是不是等到了墙钟上限才结束的」—— 见下面 need_web 的注释。
        # 默认 False = 因为「已经有结果」提前收手；True = 真的等到了头。
        hit_deadline = False
        try:
            while pending:
                elapsed = time.time() - t_search
                total = len(futs)
                answered_ratio = done_count / total if total else 1.0

                # ---- 先判「该不该收手」，再决定等多久 ----
                # 不能把收手判断只放在「batch 到达后」：那样一旦已有结果、却
                # 卡在等下一个慢源上，就会一直等到它回来才收 —— 白白多等。
                # （实测就是这里：6s 就该收的搜索拖到了 12.7s。）
                #
                # 收手四条（都要求先过 SEARCH_MIN_WAIT 底限，免得快源还没回来
                # 就收摊；**每一条都要求 streamed 非空**，即真的有东西推给前端）：
                #   ① 已有结果 + 攒够原始候选条数 → 来源够多，没必要再等
                #   ② 已有结果 + 大部分源答完     → 剩下一两个慢源没价值
                #   ③ 已有结果 + 至少两个源答过 + 宽限期到 → 提速主力，见 SEARCH_GRACE
                #   ④ 已有结果 + 软截止到          → 兜底
                #
                # ⚠ 四条都必须挂在 streamed 上，**包括第 ① 条**。踩过这个坑：
                #   最早第 ① 条只看 len(raw) >= 12，结果搜「诡秘之主」时
                #   3 个源凑出 20 条原始候选、但去噪后是 0 条（全是噪声），
                #   于是在 1.8s 就收手、返回空 —— 比慢更糟。判据必须是
                #   「真的推给前端过」（streamed），raw 只代表"来源吐了东西"。
                enough_answered = done_count >= 2

                # ---- 本地零产出 + 过了预热阈值 → 提前并行发起联网兜底 ----
                # 本地慢源继续等（最多到 SEARCH_HARD_DEADLINE），联网同时在
                # 跑。谁先出结果用谁。把"本地全灭"从 33s 串行压到 ~20s 并行。
                # 不降 SEARCH_HARD_DEADLINE —— 降了会牺牲召回（用户要求"搜到
                # 最重要"）。并行是纯收益。
                if (web_target is not None
                        and web_thread is None
                        and not streamed
                        and elapsed >= SEARCH_WEB_PREEMPT):
                    def _run_web(_w=web_target, _kw=keyword, _skw=search_kws,
                                 _or=on_result, _op=on_progress):
                        got = self._discover(_w, _kw, _or, _op, search_kw=_skw)
                        with web_box_lock:
                            web_box["items"] = got or []
                    web_thread = threading.Thread(
                        target=_run_web, name="discover", daemon=True)
                    web_thread.start()
                    log_event(logger, "search.web.preempt",
                              关键词=keyword, 已等=f"{elapsed:.1f}s")
                if elapsed >= SEARCH_MIN_WAIT and streamed:
                    # ---- 「够用了」到底该以什么为判据？ ----
                    # ⚠ 2026-10-24 复盘出来的一个大洞：①②③ 原来看的是
                    #   「候选条数够」/「答的源够多」，两者都对**噪声**敏感 ——
                    #   自有来源（registry）一个源随手就能吐 40 条沾边结果，
                    #   于是 1.5s 就判定"够了"，把还没答话的慢源和它的
                    #   **独有正主**一起扔掉，而且不报任何错。
                    #
                    #   线上实测（真机复现，同一台线上服务）：
                    #     搜《兄弟》  扇出 1.76s 收手、候选 4 条，全是
                    #                「嘿兄弟/兄弟盟/兄弟恩仇/盛唐兄弟」；
                    #                而 kunnu8 恰好在 1.76s 回来，带着正主
                    #                https://www.kunnu8.com/xiongdi/ —— 被弃。
                    #     搜《围城》  同上，kunnu8 的正主《围城》被弃，
                    #                留下「迷雾围城/围城日记/数字围城」。
                    #   用户看到的是"4 条候选、没有一本是那本书"，
                    #   体验上等于搜不到；可日报里 `候选=4` 看着是成功的 ——
                    #   这就是这个洞能活这么久的原因（判据看不见它）。
                    #
                    #   所以真正的"够用" = **至少有一条确切命中**。
                    #   一条都没有时，宁可按软截止再等一会儿（那是这个设计的
                    #   上界，不是新增的上界），也不拿噪声冒充结果。
                    #   ⚠ 软截止那条④必须**无条件**保留：它是唯一的兜底上界，
                    #     否则"永远没有确切命中的书"会把总预算吃穿。
                    _tight_ok = tight_streamed > 0
                    if (
                        (_tight_ok and len(raw) >= SEARCH_ENOUGH)
                        or (_tight_ok and answered_ratio >= SEARCH_ANSWERED_RATIO)
                        or (_tight_ok and enough_answered and elapsed >= SEARCH_GRACE)
                        or elapsed >= SEARCH_SOFT_DEADLINE
                    ):
                        # 收手原因必须写清楚：`确切=0` 的收手只可能是撞软截止，
                        # 而"有确切命中、攒够条数"是正常提速 —— 两者在耗时上
                        # 分不出来，在处置上（该补源 / 该不管）完全相反。
                        logger.info(
                            "搜索收手：已返回 %d/%d 个源（%.0f%%）、原始 %d 条/"
                            "推给前端 %d 条（其中确切 %d 条）、耗时 %.1fs，"
                            "放弃 %d 个还没回来的慢源（%s）",
                            done_count, total, answered_ratio * 100,
                            len(raw), streamed, tight_streamed, elapsed,
                            len(pending),
                            ", ".join(_pend_names()) or "-")
                        break
                # 有结果了 → 最多等到软截止；还没结果 → 放宽到硬上限再等。
                # 这个区分是必须的：源内部会串行发多次请求（wyshu 试十来个
                # 路径），「答完」可能 8~10s。没有结果的 6 秒收手 = 把慢源饿死
                # = 返回空，比慢更糟。
                # ⚠ 判据是 streamed（真推给前端过）而不是 len(raw) —— raw 可能
                #   全是噪声，那种情况下用户看到的还是空，不能算「有结果」。
                ceiling = SEARCH_SOFT_DEADLINE if streamed else SEARCH_HARD_DEADLINE
                # ⚠ 还没到 SEARCH_MIN_WAIT 时，最多只等到那个点就得醒来重判一次。
                #   不这么写的话，一旦「已完成的源」在 1.5s 前就被消费完，
                #   这一轮会**一直阻塞到下一个源回来**（或撞满 ceiling）——
                #   哪怕 1.5s 时收手条件早就满足了。
                #   实测（2026-10-24 写召回测试时暴露）：噪声源 0.01s 到、
                #   正主 0.02s 到，剩下一个永不回来的源把收手硬生生拖到 3.0s，
                #   而该收手的时刻是 0.05s（测试里 MIN_WAIT 被压到 0.05）。
                #   线上的对应代价是：收手条件满足后还要多等最多
                #   (ceiling - SEARCH_MIN_WAIT) ≈ 4.5s。
                wake = min(ceiling, SEARCH_MIN_WAIT) if elapsed < SEARCH_MIN_WAIT else ceiling
                wait = max(0.05, wake - elapsed)
                # ⚠⚠ 这里必须**逐个取**，不能 `list(as_completed(...))`。
                # 踩过大坑：`list(as_completed(pending, timeout=wait))` 不是
                # 「回一个处理一个」，它会**阻塞到所有 fut 都完成或超时**，
                # 一次性把整批塞给你。于是 6 个源在第一次调用里就被全部收走，
                # 循环体只跑一轮，那个「收手判断」根本来不及执行 —— 提速
                # 改动等于没写，且**完全不报错**（实测 6 个源 7.7s 一次收完）。
                # 正确做法：迭代器用 next() 一次只拿一个，每次拿完都回到循环
                # 顶部重新判收手。
                try:
                    it = as_completed(pending, timeout=wait)
                    fut = next(it)
                    batch = [fut]
                except StopIteration:
                    batch = []
                except TimeoutError:
                    batch = []
                except Exception as e:  # noqa: BLE001  老解释器的 futures.TimeoutError
                    if "timeout" not in type(e).__name__.lower():
                        raise
                    batch = []
                if _stop():
                    # 客户端已经断开（关页 / 连点两次搜索把上一次顶掉）——
                    # 没人看结果了，没必要再等这些慢源。立刻收手。
                    logger.info("客户端已断开，扇出收手：已返回 %d/%d 个源",
                                done_count, total)
                    break
                if not batch:
                    # 没有任何源在这段窗口内返回。
                    # ⚠ 必须区分两种"空"：
                    #   ① 这段 wait 只是**醒来重判**的定时器（wait < ceiling）——
                    #      回顶部重新算收手条件就行，**不能**当成"等到底了"。
                    #      踩过：加了「到 SEARCH_MIN_WAIT 就醒来重判」之后，
                    #      0.05s 那次醒来被当成撞满墙钟，于是 0.1s 就收手，
                    #      把马上要回来的正主判成"未回"并喂给熔断器。
                    #   ② 真的等满了本轮 ceiling —— 这才叫"我们尽力了"。
                    if time.time() - t_search < ceiling - 0.02:
                        continue
                    # ---- ② 的语义 ----
                    # 这一条 break 有**语义**：它意味着「我们尽力等了，还是没等到」。
                    #   下面的联网兜底就是靠它判断的，所以必须显式记下来 ——
                    #   不能指望调用方自己拿 done_count 去比。
                    #   （踩过：线上搜「欢迎进入梦魇直播间」时 7 个源里有 2 个
                    #    永远不返回 —— wikisource 要 184s ——导致 done_count 永远
                    #    追不上 total，联网兜底被永久跳过，搜什么都 0 条。）
                    hit_deadline = True
                    # ⚠ 这里原来只有两态：「已有结果推给前端」/「仍无结果」。
                    #   第二种是**会撒谎的**：原始 36 条摆在那儿、去噪后还剩几条，
                    #   只是没有一条够得上推送门槛（STREAM_FLOOR=45）——
                    #   旧文案把它写成"仍无结果"，复盘时只能读成"这本书没有"。
                    #   线上真实样本（10-25 09:08:03 搜《我们猫猫不能听这些》）：
                    #     收手（墙钟 20.0s 到点，仍无结果）：已返回 4/5 个源、原始 36 条
                    #     search.rank 原始=36 去噪后=0 → 最高分 10.0
                    #   这一例确实是"真没有"（kept=0），所以文案没错；但**同样的
                    #   文案**也覆盖「kept>0、只是不够推送」那一种，两者处置相反。
                    #   所以三态：推了 N 条 / 有候选但没有一条到推送门槛 / 真空。
                    logger.info(
                        "搜索收手（墙钟 %.1fs 到点，%s）：已返回 %d/%d 个源、原始 %d 条、"
                        "没回来的是 %s",
                        time.time() - t_search,
                        (f"已推给前端 {streamed} 条" if streamed else
                         (f"原始 {len(raw)} 条但没有一条够推送门槛"
                          f"（{STREAM_FLOOR:.0f} 分），用户这 {time.time() - t_search:.1f}s"
                          " 里什么都没看到" if raw else "一条候选都没拿到")),
                        done_count, total, len(raw),
                        ", ".join(_pend_names()) or "-")
                    break
                pending.difference_update(batch)

                for fut in batch:
                    src = futs[fut]
                    done_count += 1
                    try:
                        items = fut.result()
                    except Exception as e:  # noqa: BLE001
                        logger.info("源 %s 结果异常: %s", src.name, e)
                        items = []
                    if items:
                        with lock:
                            raw.extend(items)
                        # 边搜边打分：明显不相关的（判决书之类）根本不推给前端，
                        # 免得结果列表先蹦出一堆垃圾再被刷掉。
                        #
                        # ⚠ streamed 的累加**必须独立于 on_result 是否存在**。
                        # 踩过的坑：最早写成「在 if on_result 里 ++」，结果
                        # 不传回调时（引擎被直接调用/其它调用路径）streamed 恒为 0，
                        # 收手条件「已有结果」永远不成立 —— 于是所有搜索都跑满
                        # 全部源，那个「提速」改动等于没写，还不报错。
                        for it in items:
                            it.score = score_result(it, keyword)
                            # score_result 顺手把 tightness 挂上来了（见
                            # relevance.score_result），所以这里读 it.tight 是免费的。
                            # 确切口径**不受 STREAM_FLOOR 影响**：它回答的是
                            # "池子里到底有没有这本书"，而不是"推没推给前端"。
                            if it.tight:
                                tight_streamed += 1
                            if it.score >= STREAM_FLOOR:
                                streamed += 1
                                if on_result:
                                    on_result(it)

                    # 收手判断已挪到 while 顶部（每轮开始前判）—— 放在这里
                    # 会导致「已有结果但卡在等下一个慢源」时白等到那个源回来。
                    # 本 batch 处理完若已满足条件，下一轮顶部会立刻 break。
        finally:
            # ---- 墙钟到点仍没返回的源：必须记账，而且**必须喂给熔断器** ----
            # ⚠ 这是今天复盘出来的一个**判据漏洞**（不是"源慢"那么轻）：
            #   熔断器只统计「跑完、但抛了异常」的源（见 _run 里的 take_error）。
            #   而**卡死不返回**的源，future 永远不完成 → _run 永远走不到
            #   note_fail → 熔断器一次都不知道它挂过 → 每轮搜索它还在名单里。
            #   线上实测（2026-10-21）：`wikisource.search()` 单次 **186.9 秒**
            #   才返回（5 次重试 + 递增退避 + search 里串两次），而这台机器
            #   到 zh.wikisource.org 的 TLS 握手天天超时（当天 117 次）。
            #   于是每搜一次书就多一个活 167 秒的僵尸线程，占着线程和连接池，
            #   同期别的搜索就会偶发「一个源都没答话」→ 0 条
            #   （这就是「同一本书 6 分钟内一次 0 条、一次 1 条」的机制）。
            #
            # 判据：**真的等满了硬上限**（hit_deadline）+ **客户端没走**
            #   + fut 确实还没完成。三条缺一不可：
            #   · 有结果提前收手时不清算 —— 那时剩下的源只是"来不及"，不是坏；
            #   · 客户端断开时不清算 —— 那是用户不看了，不是源的错，
            #     否则连点两次搜索就能把全部源拉黑。
            if hit_deadline and pending and not _stop():
                hung: list[str] = []
                for fut in list(pending):
                    if fut.done():
                        continue
                    src = futs.get(fut)
                    if src is None:
                        continue
                    hung.append(src.name)
                    failed_sources.add(src.name)
                    HEALTH.note_fail(src.name, "timeout: 墙钟到点仍未答话")
                    log_event(logger, "source.fail", 源=src.name,
                              原因="timeout: 墙钟到点仍未答话")
                if hung:
                    logger.info("墙钟到点仍未答话：%s（已记账，连续两轮就会被熔断）",
                                ", ".join(sorted(set(hung))))
            # ---- 账尾：还没回来的源必须**记名字**，不能只留个数字 ----
            # 为什么这一段独立于上面那段（后者只在"撞满硬上限"时跑）：
            # 大部分搜索是**提前收手**的（线上 10 次真机搜索，9 次
            # `未回=1~2` 但都没撞满 22 秒）。那些源不是死了，只是慢；
            # 可复盘时看到 `超=2` 完全不知道是谁 —— 想知道就得再去翻
            # `搜索收手…放弃 2 个` 后面那半句，而那半句当时根本没名字。
            # 所以这里对**所有**没交回来的源都要留名：
            #   · 还在跑（not done）→ hang：到点没回来
            #   · 被取消（cancelled）→ skip：压根没轮到跑（线程池排不上）
            for fut in list(pending):
                src = futs.get(fut)
                if src is None:
                    continue
                if fut.cancelled():
                    _mark(src.name, "skip")
                elif not fut.done():
                    _mark(src.name, "hang")
                # fut.done() 但没被消费（收手后 0.1 秒内刚回来）：
                # _run 自己已经记过 ok/fail，这里不动 —— 它确实答话了。
            # 不等没回来的慢源 —— 它们在后台自然结束，结果对本轮无意义。
            # cancel_futures 只能取消**还没开始跑**的；已经在跑的线程
            # 会在自己超时后退出，不会泄漏（每次 fetch 都有 timeout）。
            pool.shutdown(wait=False, cancel_futures=True)

        # ---- 等并行发起的联网兜底（如果触发了） ----
        # 它和本地慢源是并行跑的，到这里时通常已经跑完或快好了。
        # 给一个上限别无限挂 —— 联网兜底内部有 fetch timeout，正常会自己结束。
        if web_thread is not None:
            web_thread.join(timeout=SEARCH_HARD_DEADLINE + 5)
            with web_box_lock:
                web_extra = list(web_box["items"])
            if web_extra:
                with lock:
                    raw.extend(web_extra)
                logger.info("并行联网兜底回收 %d 条候选（与本地扇出并行跑）",
                            len(web_extra))
            elif web_thread.is_alive():
                # 还在跑 = 我们没等到它 —— 说清楚，别让"兜底跑了但没赶上"
                # 表现成"联网也没找到"（这两种的下一步动作完全不同）。
                logger.info("并行联网兜底超时未归（仍在运行），本轮不等它了")

        # 相关性打分 + 去噪 + 排序
        rpt: dict = {}
        results = rank(raw, keyword, report=rpt)
        log_event(logger, "search.rank", 关键词=keyword,
                  原始=len(raw), 去噪后=len(results))
        # 光有「原始=14 去噪后=2」没法复盘 —— 得知道那 12 条是什么、为什么被丢。
        # 门槛砍掉的 vs 被「确切命中优先」挤掉的，处置方式完全相反：
        #   前者往往是站点返回了一堆别的书（该换源/该调阈值），
        #   后者往往说明规则太狠（明明有相关结果却一条都没留下）。
        # 只在**真的丢了东西**时打，免得正常的搜索把日志刷满。
        if raw and (rpt.get("below_cut_n") or rpt.get("loose_n")
                    or rpt.get("deduped_n")):
            log_event(
                logger, "search.rank.drop", 关键词=keyword,
                门槛=rpt.get("cut"), 最高分=rpt.get("best"), 留下=rpt.get("kept"),
                低于门槛=rpt.get("below_cut_n"),
                非确切命中被挤掉=rpt.get("loose_n"),
                # 同站重名被并掉 —— 这一类**不是**质量问题，单独记，
                # 免得复盘时把它当成"规则太狠"去改本来就对的阈值。
                同站重名被并掉=rpt.get("deduped_n"),
                # 只举 3 个例子：日志要看趋势，不是要看全量清单
                例子=[t for t, _ in (rpt.get("below_cut") or [])[:3]]
                     + [t for t, _ in (rpt.get("loose") or [])[:3]])

        if probe and results:
            # 探测预算 = min(满额, 总预算 - 已耗 - 给抽样预留的那份)。
            # 扇出已经烧掉 20 秒时这里会算出 0 —— 那就干脆别探，并**说出来**。
            pb = budget_slice(t_start, PROBE_BUDGET,
                              SEARCH_TOTAL_BUDGET - SAMPLE_RESERVE)
            if pb <= 0.0:
                logger.info(
                    "跳过探测：总预算 %.0fs 已用完（已耗 %.1fs）—— %d 个候选保持"
                    "「未验证」，不再为补徽标让用户多等",
                    SEARCH_TOTAL_BUDGET, time.time() - t_start, len(results))
            else:
                self.probe_all(results, on_verified=on_verified, top=probe_top,
                               should_stop=_stop, budget=pb)
            results = self.refine(results, keyword)

        # ---- 本地一条可读的都没有？出去找 ----
        # 触发条件刻意保守：只有在「什么都没搜到」或「搜到的全打不开」
        # 时才联网。本地能出结果就绝不联网 —— 联网是兜底，不是常规路径。
        #
        # 「全打不开」这一条必须挂在 probe 之后：关掉探测时所有候选的
        # available 都是 None（= 没验证过），照字面判就会把每一次搜索
        # 都当成「全军覆没」而触发联网。
        #
        # ⚠ 关键前提：**必须确认「本地真的尽力找了」**，否则空结果不能说明
        # 本地没有这本书 —— 只是那几个源还没答完。
        #
        # 但「尽力」到底怎么判？这里踩过一个**线上事故级**的坑：
        # 最早写成 `done_count >= len(futs)`（要求每一个源都答完）。
        # 这在现实中**永远不成立** —— 只要有一个源卡死不返回，
        # done_count 就永远追不上 total，联网兜底被**永久跳过**。
        #
        # 实测（服务器上）：
        #   · xbqg5200 在腾讯云 IP 上首页 502 —— 唯一有《欢迎进入梦魇直播间》
        #     的常规源，直接哑火
        #   · wikisource 要 **184 秒**才返回 —— done_count 停在 5/7
        #   · 于是 exhausted 永假 → 不联网 → 返回 0 条
        #   · 而联网源（web）明明有这本书（0.0s，6 条）
        # 最恶劣的是**它不报任何错**，只表现成「搜不到」。
        #
        # 正确的「尽力了」是这两种之一：
        #   ① 所有源都答完了（done_count == total）
        #   ② 等到了墙钟上限才收手（hit_deadline）—— 该给的耐心给够了
        # **不包括**「因为已有结果提前收手」：那种情况 results 非空，
        # 本来也不会走到联网分支。
        exhausted = (done_count >= len(futs)) or hit_deadline
        need_web = (not results) and exhausted
        # ---- 「有结果、但一条可读的都没有」这一类的门票**不能**是 exhausted ----
        # 2026-10-27 线上实测（《我的阿勒泰》）：
        #   search.done 候选=1 成书=1 确切=1 可读=0 联网发现=0 耗时ms=2041
        #   唯一候选是 registry 的 https://www.bqg5555.cc/xs/268912/，探测回
        #   「这个地址不是目录页（没解析到章节列表）」→ 可用=false、0 章。
        #   它偏偏是**确切命中**（tightness=1.0、score=100），于是收手门在 1.5s
        #   就被喂饱：hit_deadline=False、done_count 4 < 5 → exhausted=False →
        #   这条分支（原本就是为"搜到的全打不开"写的）**一次都进不去**。
        #   用户拿到一张点不开的卡片，而引擎以为自己"本地有结果"。
        #
        # 为什么这一类的门票可以低于 `exhausted`：
        #   `exhausted` 回答的是"我们等够了没有"，它针对**零结果** ——
        #   那种情况下没回来的慢源还可能翻盘，所以必须等满。
        #   而走到这一行时扇出**已经结束**：没回来的源结果本轮一律不会再用
        #   （上面 finally 已记账 + shutdown）。也就是说"提前收手"和
        #   "撞满墙钟"对本地可读产出没有区别 —— 两种情况下本地都交不出
        #   能读的东西，联网是唯一剩下的路。拿 `exhausted` 当门票，等于用
        #   "等够了没"去回答"本地还能不能救"，问错了问题。
        #
        # 只在 `probe` 开着时成立：关掉探测时 available 全是 None（没验过），
        # 照字面判会把每一次搜索都当成"全打不开"。
        need_web = need_web or (
            bool(results) and bool(probe)
            and not any(r.available for r in results))
        # 并行已经跑过就别再串行跑一次（web_extra 已在 raw 里，rank 时合并了）
        already_web = web_thread is not None
        # 「本地全灭、本该联网，但总预算已经用完了」——**必须记下来**：
        # 否则"联网也没找到"和"联网压根没跑"在日志里一模一样。
        web_skipped_budget = False
        # ---- 「这轮为什么没联网」也要留字段 ----
        # 线上 `联网发现=0` 同时对应四件处置完全不同的事：
        #   not_needed 本地有能读的结果（好事，不必联网）
        #   preempt    并行那路已经跑过（不是没跑）
        #   budget     该跑，预算没了
        #   disabled   调用方关掉了 discover
        # 2026-10-27《我的阿勒泰》就是被"not_needed"的假象盖住的：
        # 它本地交不出任何可读结果，日志里却只有一句 `联网发现=0`。
        web_skip = "not_needed" if not need_web else ""
        if discover and need_web and not already_web:
            web = self._find_source(DISCOVER_SOURCE)
            # 联网兜底也是**串行**加在后面的，同样得看总预算 ——
            # 否则前面 20 秒扇出 + 10 秒联网 = 又回到 30 秒。
            wb = budget_slice(t_start, 30.0, DISCOVER_TOTAL_BUDGET)
            # ⚠ 「断开后不再出去搜」这条判断**只写在 `_discover` 内部**，这里不重复。
            #   联网兜底一轮要 3~10 秒（两个搜索引擎 + 十几个站核实），
            #   而断开后没有任何人还在听 —— 纯白烧，还去撞搜索站的反爬配额。
            #   这段原先**完全不认 should_stop**，于是：
            #     · 断开后照样跑完；
            #     · `aborted` 报 False → 断连止损在换一个掐断时机时**偶发假红**
            #       （ship 实测三轮全 False，单独重跑又绿）。
            #   修法是在 `_discover` 的"逐个词"循环里检查 —— 那里既能拦住
            #   进入前就断开的，也能拦住"多词搜到一半断了"的。
            #   这里再写一遍外层检查是**死代码**（内层第一轮就 break），
            #   反证当场证明了这一点（删掉外层检查，测试照样绿），所以删掉。
            if web is not None and wb > 0.0:
                extra = self._discover(web, keyword, on_result, on_progress,
                                       search_kw=search_kws, should_stop=_stop)
                if extra:
                    if probe:
                        # 联网换来的候选必须探测 —— 它的价值就在于"本地没有、
                        # 远端有"，不验一下等于把不知道能不能读的东西端上去。
                        self.probe_all(
                            extra, on_verified=on_verified, top=len(extra),
                            should_stop=_stop,
                            budget=budget_slice(t_start, PROBE_BUDGET,
                                                DISCOVER_TOTAL_BUDGET))
                    results = rank(results + extra, keyword)
                    results = self.refine(results, keyword)
            elif web is not None:
                # ⚠ 2026-10-25 修：这里原来写的是「记一句『跳过联网兜底：总预算
                #   已用完』**然后照样把兜底跑完**」，后面还跟着一段一模一样的
                #   死分支（`elif web is not None`，永远到不了）。两个后果：
                #     · 日志撒谎 —— 它说"跳过"，实际又跑了 3~10 秒；
                #     · 契约破防 —— `over_budget` 是按 DISCOVER_TOTAL_BUDGET(32s)
                #       算的，这里真跑起来就成了"对外承诺 32 秒、实际 42 秒"，
                #       而且不报错、不断言。
                #   收手可以，但不许**沉默地收手**、更不许**说反话**：
                #   真的不跑了，并把这件事记进 stats（`web_skipped_budget`），
                #   让日报能看见「这一轮本地全灭而且联网没跑」。
                web_skipped_budget = True
                web_skip = "budget"
                logger.info(
                    "跳过联网兜底：总预算 %.0fs 已用完（已耗 %.1fs）—— 本轮不联网，"
                    "本地结果照常返回",
                    DISCOVER_TOTAL_BUDGET, time.time() - t_start)
            elif web is None:
                # 该联网、预算也有，但装配里压根没有联网来源 —— 这不是"没找到"。
                web_skip = "no_source"
        elif discover and need_web and already_web:
            # 并行已发起、本地仍无结果 → 给 web_extra 探测 + 重排
            # （上面 raw 已 extend，这里 results=rank(raw) 已包含 web_extra）
            web_skip = "preempt"
            if results and probe:
                self.probe_all(
                    results, on_verified=on_verified, top=probe_top,
                    should_stop=_stop,
                    budget=budget_slice(t_start, PROBE_BUDGET,
                                        DISCOVER_TOTAL_BUDGET))
                results = self.refine(results, keyword)
        elif need_web:
            # 该联网、但调用方把 discover 关了 —— 记清楚原因。
            # 不记的话，它和"联网了但没找到"在 search.done 里一模一样，
            # 复盘时会去查搜索引擎，而真正的原因是一个开关。
            web_skip = "disabled"

        if sample and results:
            sb = budget_slice(t_start, SAMPLE_BUDGET)
            if sb <= 0.0:
                logger.info(
                    "跳过正文抽样：总预算 %.0fs 已用完（已耗 %.1fs）—— %d 个候选"
                    "保持「正文未验证」，不再为此让用户多等",
                    SEARCH_TOTAL_BUDGET, time.time() - t_start, len(results))
            else:
                aborted = self.verify_samples(results, on_verified=on_verified,
                                              should_stop=_stop, budget=sb)

        if stats is not None:
            # 这一轮适用哪个上限：走了联网兜底就有更大的额度（见 DISCOVER_TOTAL_BUDGET）
            _allow_s = (DISCOVER_TOTAL_BUDGET if (discover and need_web)
                        else SEARCH_TOTAL_BUDGET)
            # ---- 源账：四格互斥，加起来必须等于总数 ----
            with outcome_lock:
                _snap = dict(outcome)
            _ok_n = sum(1 for v in _snap.values() if v == "ok")
            _fail_names = sorted(n for n, v in _snap.items() if v == "fail")
            _unret_names = sorted(n for n, v in _snap.items() if v == "hang")
            _skip_names = sorted(n for n, v in _snap.items() if v == "skip")
            _accounted = _ok_n + len(_fail_names) + len(_unret_names) + len(_skip_names)
            # 应搜 = 真的扇出出去的 + 熔断被跳过的（后者也是"该搜而没搜"）
            _expect = len(targets) + len(skipped)
            if _accounted + len(skipped) != _expect:
                # 账对不上就当场说，别让日报拿着一个加不起来的数字下结论
                logger.info(
                    "源账对不上：应搜 %d 个源（扇出 %d + 熔断 %d），记账 %d 个"
                    "（答=%d 挂=%d 未回=%d 未跑=%d）",
                    _expect, len(targets), len(skipped), _accounted + len(skipped),
                    _ok_n, len(_fail_names), len(_unret_names), len(_skip_names))
            stats.update({
                "raw": len(raw),
                "kept": len(results),
                # 「边搜边推」到底推出去几条 —— 这个数和 `kept` **不是一回事**，
                # 差在 STREAM_FLOOR（推送门槛 45 分）与 rank 的显示门槛
                # （best<70 时 28 分）之间那一段。
                #
                # 线上能观测到的后果（2026-10-26 复盘，欠账①的根源）：
                #   一条候选 34 分 → 最终列表里有它（用户最后能看到），
                #   但整个扇出过程一条都没推 → 前端全程"正在找…"，
                #   而 old 收手判据全挂在 `streamed` 上 → 只能等满硬上限 20s。
                #   日志里这 20 秒只留一行 `耗时ms=20009 候选=1`，
                #   跟"真没有"长得一模一样。
                # 有了这个数，`卡满` 才能问出正确的那个问题：
                #   "等满了墙钟，**用户到底看到东西没有**"。
                "pushed": streamed,
                # 「候选里有几条是**这本书**」（确切命中）。
                # ⚠ 只有 `候选=` 是不够的：`候选=4` 既可能是"有正主 + 3 条同类"，
                #   也可能是"4 条全是『嘿兄弟/兄弟盟』" —— 用户感受完全相反
                #   （搜到了 / 搜不到），而旧日志里两者一模一样。
                #   这个数就是让日报能区分它们的最小埋点。
                #
                # ⚠ 2026-10-25 复盘修：这个数必须**从最终结果集里数**，不能拿
                #   扇出阶段的累加值（`tight_streamed`）冒充。扇出阶段的计数
                #   只覆盖「本地源交回来的条目」，而**联网兜底救回的正主
                #   压根不经过那个循环** —— 于是最惊险、最需要复盘的那条路径
                #   反而永远报 `确切=0`。
                #
                #   线上实测（搜《我们猫猫不能听这些》）：
                #       done: 候选=1 成书=1 可读=1 确切=0
                #       books[0]: 我们猫猫不能听这些 / tightness=1.0 / tight=true
                #                             ↑ 同一份数据里自称不确切
                #   一行日志里「候选=1、确切=0」在算术上就不成立 ——
                #   可它每天都在被当成"这本书没有正主"的证据。
                #
                #   所以口径定死：**确切 = 最终结果里 tight 的条数**，
                #   和 `候选`（len(results)）数的是同一个集合，两者必须能对账：
                #       确切 <= 候选，且 确切=0 ⟺ 结果里没有任何一本是这本书
                #   收手判据要的是另一个数（"到现在为止到了几条正主"），
                #   它继续用 `tight_streamed`，放在单独的键里，别混。
                "tight_hits": sum(1 for r in results if r.tight),
                # 「扇出阶段累计到几条正主」—— 只给收手判据和复盘对照用。
                # 它小于 tight_hits 时，差值就是**联网兜底/晚回来的源贡献的**。
                "tight_streamed": tight_streamed,
                "filtered": max(0, len(raw) - len(results)),
                "available": sum(1 for r in results if r.available),
                "readable": sum(1 for r in results if r.readable),
                "sources_queried": len(targets),
                # 开搜时的「可搜源」个数（-1 = 没取到）。收尾时再数一遍，
                # `pool_note` 就是 `22→15` —— 差值 = **这次搜索顺手废掉的
                # 搜索模板数**（冷门书把没搜出过东西的站连记 3 次形态失败就
                # 作废，见 `registry.note_search_result`）。
                # 2026-10-30 前这个差值只能靠人肉 diff registry.json 才发现。
                "pool_before": _pool0,
                "pool_note": _pool_note(_pool0),
                # ⚠ 语义收窄（2026-10-23）：只数**真的答了话**的源。
                #   原来是 done_count，把"返回了 403 的源"也算进去 ——
                #   于是 `答=3` 可能是"2 个有内容 + 1 个 403"，读者无从分辨。
                "sources_answered": _ok_n,
                # ⚠ 分母含**熔断被跳过**的源：它们是"该搜而没搜"，不是"没有"。
                #   2026-10-25 修。不含的话，「全部目标源都在熔断里」会算成
                #   `答=0/0` —— 一个看起来干净、实际一个请求都没发的账。
                #   线上真出现过：10-24 09:04:59《红楼梦》《剑来》 耗时ms=2
                #   答=0/0 候选=0，复盘时无法与"搜遍了都没有"区分。
                "sources_total": len(targets) + len(skipped),
                "sources_breaker": len(skipped),
                "breaker_sources": sorted(skipped),
                # 返回了但挂了的（403 / 握手超时 / 吞异常）—— 与"未回"互斥
                "sources_failed": len(_fail_names),
                "failed_returned_sources": _fail_names,
                # 到点还没回来的（hang）+ 压根没轮到跑的（skip）
                "sources_unreturned": len(_unret_names) + len(_skip_names),
                "unreturned_sources": _unret_names + _skip_names,
                # 保留旧键（`超=` 一直读它）：现在等于「未回」的个数
                "timed_out": len(_unret_names) + len(_skip_names),
                # 这一轮是不是**真的撞满了墙钟上限**。
                # ⚠ 拿 `耗时ms>=20000` 当判据是不行的：那是环境量，
                #   机器一忙就漂。这个布尔量只取决于机制该不该收手。
                "hit_deadline": bool(hit_deadline),
                # 这一轮**挂了**的源（异常 / 吞异常 / 墙钟到点不返回）。
                # 有它才能把「书真的没有」和「源全挂了」分开 ——
                # 两者在 search.done 里都只是「候选=0」，而处置完全相反：
                # 前者该补源/补书，后者等几分钟重试就好。
                # ⚠ 它含"墙钟到点未回"的源（那些也要喂熔断器），
                #   所以**不能**和 `sources_failed` 混着用：一个含未回、一个只含返回了的。
                "failed_sources": sorted(failed_sources),
                "search_ms": int((time.time() - t_search) * 1000),
                "ms": int((time.time() - t_start) * 1000),
                # 总预算有没有被突破。**这是对外契约的判据**：
                # "搜一本书最多等 22 秒"这句话，只能靠一个明确的布尔量来验，
                # 不能靠"人肉看日志里的耗时ms"——没人会天天去看。
                # 各阶段自报"我在自己预算内完成了"是不够的，加起来超了就是超了。
                # 走了联网兜底的那一轮允许更长的上限（DISCOVER_TOTAL_BUDGET），
                # 否则"本地全灭、出去找"这条路径会永远被判超预算。
                "budget_s": _allow_s,
                "over_budget": (time.time() - t_start) > _allow_s,
                "discovered": sum(1 for r in results if r.source == DISCOVER_SOURCE),
                # 本地全灭、本该联网，但总预算已经用完 → 没有联网。
                # 与「联网了但没找到」是两件处置相反的事，必须分开记。
                "web_skipped_budget": bool(web_skipped_budget),
                # 这轮**为什么**没联网（""=真的跑了）。见上面 web_skip 的注释：
                # not_needed / preempt / budget / no_source / disabled。
                "web_skip": web_skip,
                # 断开收手是否真的触发了（供真机测试断言）。
                # ⚠ 用它而不是"耗时是不是更短"来验证收手 —— 耗时受源站快慢
                #   影响，波动能有 5 倍（实测 2.3s ~ 25.6s），
                #   拿它当判据必然假红假绿；而这个布尔量只取决于机制本身。
                #   断连止损测试就是踩了那个坑，改成看这个。
                "aborted": bool(aborted or cut_short),
            })
        return results

    def _discover(
        self,
        web: Source,
        keyword: str,
        on_result: Optional[Callable[[BookResult], None]],
        on_progress: Optional[Callable[[str, str, bool], None]],
        search_kw: Optional[object] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> list[BookResult]:
        """唤起联网发现来源，拿回它的候选。

        单独一个方法是为了让异常不外泄 —— 联网发现失败不该让整次搜索崩掉，
        毕竟本地结果（如果有）还是能用的。

        `keyword` 是**完整关键词**（用于打分），`search_kw` 是**实际拿去搜的
        词**（多词时是最长那个；并列最长时是 list，要逐个搜）。两者分开是因为
        "搜什么"和"按什么排序"是两件事。
        """
        # search_kw 可能是 str 也可能是 list[str]（多词并列最长，见 search()）
        if isinstance(search_kw, (list, tuple)):
            looks = [str(x) for x in search_kw if str(x).strip()] or [keyword]
        else:
            looks = [search_kw or keyword]
        try:
            web.set_log(on_progress)
            extra: list[BookResult] = []
            seen_u: set[str] = set()
            for i_look, look_for in enumerate(looks):
                # 多词并列最长时这里要搜好几个词，每个词都是一次完整联网搜索。
                # 客户端走了就别再搜下一个 —— 没人会看到结果。
                if should_stop and should_stop():
                    logger.info("客户端已断开，联网兜底提前收手（还有 %d 个词没搜）",
                                len(looks) - i_look)
                    break
                for it in (web.search(look_for) or []):
                    u = getattr(it, "url", "") or ""
                    if u and u in seen_u:
                        continue
                    seen_u.add(u)
                    extra.append(it)
        except Exception as e:  # noqa: BLE001
            logger.info("联网发现失败: %s", e)
            return []
        finally:
            web.set_log(None)

        for it in extra:
            it.source_display = web.display
            it.score = score_result(it, keyword)
        if on_result:
            for it in extra:
                on_result(it)
        if extra:
            logger.info("联网发现补充 %d 条候选", len(extra))
        return extra

    def search_books(self, keyword: str, **kw) -> tuple[list[dict], list[BookResult], dict]:
        """搜索并聚合到「书」这一层。返回 (books, results, stats)。"""
        stats: dict = {}
        results = self.search(keyword, stats=stats, **kw)
        books = group_books(results)
        stats["books"] = len(books)
        return books, results, stats

    # ==================================================================
    # 可用性探测
    # ==================================================================
    def probe_all(
        self,
        results: list[BookResult],
        on_verified: Optional[Callable[[BookResult], None]] = None,
        top: int = DEFAULT_PROBE_TOP,
        should_stop: Optional[Callable[[], bool]] = None,
        budget: float = PROBE_BUDGET,
    ) -> list[BookResult]:
        """并发探测候选，可用的排到前面。

        results 已按相关性排好序，这里按顺序取，但**每个来源限量**，
        且配额按该来源的实测速度自适应 —— 同域请求会被限速串行，
        一个每页 2 秒的慢站必须有更小的配额，否则会独吞整轮搜索预算。
        """
        head: list[BookResult] = []
        per_src: dict[str, int] = {}
        for r in results:
            if len(head) >= top:
                break
            src = self._find_source(r.source)
            quota = min(PROBE_PER_SOURCE, src.probe_limit()) if src else 1
            n = per_src.get(r.source, 0)
            if n >= quota:
                continue
            per_src[r.source] = n + 1
            head.append(r)

        if not head:
            return results

        pool = ThreadPoolExecutor(max_workers=min(PROBE_WORKERS, len(head)))
        futs = {pool.submit(self._probe_one, r): r for r in head}
        ok = 0
        try:
            for fut in as_completed(futs, timeout=budget):
                if should_stop and should_stop():
                    # 客户端断开 → 没必要再把剩下的候选一个个打开验证。
                    # 探测是整轮搜索里最贵的一段（每个候选都要打一次详情页），
                    # 没人看结果时继续跑纯粹是浪费。
                    logger.info("客户端已断开，停止探测（已验证 %d 个）", ok)
                    break
                try:
                    r = fut.result()
                except Exception as e:  # noqa: BLE001
                    r = futs[fut]
                    r.available = False
                    r.note = str(e)[:70]
                if on_verified:
                    on_verified(r)
                if r.available:
                    ok += 1
                    # 埋点：哪一个候选、哪一源、验证结果、耗时。
                    # 这条是"L 源闭环"的眼睛 —— 想判断一个源好不好，
                    # 就看 verify.ok 里它出现的比例；全是 fail 的就是坏源，
                    # 该进定期排查名单（registry.check）。
                    # 注意**逐条发**而不是只发汇总：线上排障时要能按
                    # 「源=xxx」grep 出这个源最近到底怎么挂的，汇总给不了这个。
                    log_event(logger, "verify.ok", 源=r.source,
                              书名=r.title[:30], 章=r.chapter_count,
                              耗时=f"{r.probe_ms}ms")
                    if ok >= PROBE_ENOUGH:
                        # 已经有这么多个可用来源了，剩下的不必再验：
                        # 再验一个就要多占一次同域请求，而用户在等。
                        logger.info("已验出 %d 个可用候选，提前收手", ok)
                        break
                else:
                    # 失败也逐条记：失败原因（超时/无正文/404）是评估源质量
                    # 最值钱的信息 —— 只说"某个源不行"没法定位是站点改版
                    # 还是被限流，带上 note 才能一眼分辨。
                    log_event(logger, "verify.fail", 源=r.source,
                              书名=r.title[:30],
                              原因=(r.note or "未知")[:60],
                              耗时=f"{r.probe_ms}ms")
        except Exception:  # noqa: BLE001  (TimeoutError 或其它)
            logger.info("探测超预算，剩余候选标记为未验证")
        finally:
            # 超时的线程不再等待，让它们在后台自然结束
            pool.shutdown(wait=False, cancel_futures=True)

        # 排序：可读优先 → 章节多的优先 → 相关性高的优先
        return sorted(results, key=lambda r: (
            0 if r.readable else (1 if r.available else (3 if r.available is None else 2)),
            -r.chapter_count,
            -r.score,
        ))

    def _probe_one(self, r: BookResult) -> BookResult:
        src = self._find_source(r.source)
        if src is None:
            r.available = False
            r.note = "未安装该来源"
            return r
        r.source_display = src.display
        try:
            with fast_mode():
                info = src.probe(r)
        except Exception as e:  # noqa: BLE001
            r.available = False
            r.note = note_for_exception(e)
            return r
        r.available = bool(info.get("ok"))
        r.chapter_count = int(info.get("chapters") or 0)
        # 探测**没话要说**时，别把原有的备注抹掉。
        # 联网发现的结果身上带着「来自 落霞读书」这种站名备注，
        # 探测成功时它自己没有备注，一覆盖就成空白 —— 卡片上就啥也看不见了。
        note = (info.get("note") or "").strip()
        if note:
            r.note = note
        r.probe_ms = int(info.get("ms") or 0)
        # 实测耗时回流给来源，用于下一轮的配额自适应
        src.note_probe(r.probe_ms)
        return r

    # ==================================================================
    # 深度校验：抽样读正文
    # ==================================================================
    def refine(self, results: list[BookResult], keyword: str) -> list[BookResult]:
        """探测回填了**真书名**之后再排一次。

        为什么需要：有些站的搜索接口是按「章」检索的，拿回来的标题是
        「第216章 活着」这种（鲲弩小说就是这样），真书名要打开阅读页才知道。
        探测刚好会去开阅读页，于是顺带把真名带回来了 —— 此时重排，
        就能把原本因为「标题像章节」而被罚分的真正好书救回来，
        同时把「探测完还是个章节名」的残留彻底剔掉。

        不做这一步的后果很直观：搜《活着》，结果里全是「第X章 活着」。
        """
        before = len(results)

        def is_chapterish(r: BookResult) -> bool:
            t = (r.title or "").strip()
            return bool(CHAPTER_TITLE_RE.match(t)) and not CHAPTER_TITLE_RE.match(keyword.strip())

        kept = [r for r in results if not is_chapterish(r)]
        out = rank(kept, keyword)
        if len(out) != before:
            logger.info("探测回填书名后重排：%d → %d", before, len(out))
        return out

    def verify_samples(
        self,
        results: list[BookResult],
        on_verified: Optional[Callable[[BookResult], None]] = None,
        top: int = SAMPLE_TOP,
        should_stop: Optional[Callable[[], bool]] = None,
        budget: float = SAMPLE_BUDGET,
    ) -> bool:
        """对最靠前的「目录可达」候选，抽一章正文验证内容是真的。

        为什么必须做：不少站的目录页是静态的，谁都能打开；但正文要点开
        「开始阅读」才给，或者被限流后返回一页广告/验证码。只看目录就标
        「可用」，用户点进去才发现是空的 —— 这就是「别显示可以下载最后假的」。
        """
        targets = [r for r in results if r.available][:top]
        if not targets:
            # ⚠ 这里踩过一个「静默空转」：抽样只挑 `available` 为真的候选，
            #   而 `available` 是**探测（probe）**填的。如果调用方关掉了 probe
            #   （`probe=0`），所有候选的 available 都是 None → targets 恒为空
            #   → 抽样一次都不跑，但函数**正常返回、不报错**。
            #   后果是「说好了要验正文，实际一个字都没验」，而前端仍按
            #   `sample_ok === null` 显示「正文未验证」—— 看着像"还没轮到"，
            #   其实是"根本不会发生"。留一条 warn 让它在日志里现形。
            if results and not any(r.available for r in results):
                logger.warning(
                    "抽样校验被跳过：%d 个候选的 available 全为空（多半是 probe=0 时调用）"
                    "—— 正文不会得到验证", len(results))
            return False

        # 同一来源最多抽两本 —— 每抽一本都要跨页请求，抽样不能比探测还贵。
        # **但要按「来源 + 域名」计数，不能只按来源名**：联网发现（web）
        # 一个来源底下挂着几十个互不相干的站，只按来源名计数的话，
        # 5 个不同站点会被当成同一个来源、只抽其中 2 个，
        # 剩下 3 个「没抽过」的就会顶着「可读」的标签出现在结果里。
        # 内置来源一个来源就是一个站，加了域名之后行为不变。
        picked: list[BookResult] = []
        per_src: dict[tuple[str, str], int] = {}
        for r in targets:
            key = (r.source, host_of(r.url))
            n = per_src.get(key, 0)
            if n >= SAMPLE_PER_SOURCE:
                continue
            per_src[key] = n + 1
            picked.append(r)
        targets = picked

        pool = ThreadPoolExecutor(max_workers=min(SAMPLE_WORKERS, len(targets)))
        futs = {pool.submit(self._sample_one, r): r for r in targets}
        ok = 0
        aborted = False
        try:
            for fut in as_completed(futs, timeout=budget):
                if should_stop and should_stop():
                    aborted = True
                    logger.info("客户端已断开，停止正文抽样（已验 %d 本）", ok)
                    break
                try:
                    r = fut.result()
                except Exception:  # noqa: BLE001
                    r = futs[fut]
                    r.sample_ok = None
                if on_verified:
                    on_verified(r)
                if r.sample_ok:
                    ok += 1
                    if ok >= SAMPLE_ENOUGH:
                        # 正文本已经验过几本了，够用户选；再抽下去只是拖时间。
                        logger.info("已验过 %d 本正文，提前收手", ok)
                        break
        except Exception:  # noqa: BLE001
            logger.info("抽样校验超预算，部分候选未做正文验证")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        return aborted

    def _sample_one(self, r: BookResult) -> BookResult:
        src = self._find_source(r.source)
        if src is None:
            return r
        # 先打上「抽过了」的标记，再去抽。
        # 抽样抛异常时 ok 仍然是 None，但 sampled 已经为 True ——
        # 这样「抽了但没结论」和「压根没抽」就分得开了（见 BookResult.readable）。
        r.sampled = True
        try:
            with fast_mode():
                info = src.sample(r)
        except Exception as e:  # noqa: BLE001
            r.sample_ok = None
            r.sample_note = note_for_exception(e)
            return r
        r.sample_ok = info.get("ok")
        r.sample_chars = int(info.get("chars") or 0)
        r.sample_note = info.get("note", "") or ""
        return r

    # ==================================================================
    # 预览
    # ==================================================================
    def preview(self, result: BookResult, chapter_index: int | None = None) -> dict:
        """取书籍信息 + 目录 + 某一章正文样本（不下载全书）。"""
        src = self._find_source(result.source)
        if src is None:
            raise RuntimeError(f"找不到来源: {result.source}")

        with fast_mode(retries=2, timeout=15.0):
            chapters = src.get_chapters(result)

        if not chapters:
            raise RuntimeError("这个来源打不开或没有解析到目录")

        idx = 0
        if chapter_index:
            idx = max(0, min(chapter_index - 1, len(chapters) - 1))
        target = chapters[idx]

        content = ""
        with fast_mode(retries=2, timeout=20.0):
            try:
                content = src.fetch_chapter(target) or ""
            except Exception:  # noqa: BLE001
                content = ""
            if not content:
                # 单页来源（Gutenberg 等）不支持单章抓取，退化为抓第一章
                try:
                    book = src.fetch(result, progress=None, limit=idx + 1)
                    if book.chapters:
                        content = book.chapters[min(idx, len(book.chapters) - 1)].content
                except Exception:  # noqa: BLE001
                    content = ""

        return {
            "title": result.title,
            "author": result.author,
            "source": result.source,
            "source_display": src.display,
            "url": result.url,
            "intro": result.intro,
            "available": result.available,
            "score": round(result.score, 1),
            "total_chapters": len(chapters),
            "chapters": [c.to_dict() for c in chapters],
            "sample_index": target.index,
            "sample_title": target.title,
            "sample": content,
        }

    def read_chapter(self, result: BookResult, chapter_index: int) -> dict:
        """读取指定章节正文（预览里点章节时用）。"""
        src = self._find_source(result.source)
        if src is None:
            raise RuntimeError(f"找不到来源: {result.source}")
        with fast_mode(retries=2, timeout=20.0):
            chapters = src.get_chapters(result)
            if not chapters:
                raise RuntimeError("没有目录")
            idx = max(0, min(chapter_index - 1, len(chapters) - 1))
            ch = chapters[idx]
            content = src.fetch_chapter(ch) or ""
            if not content:
                book = src.fetch(result, progress=None, limit=idx + 1)
                if book.chapters:
                    content = book.chapters[min(idx, len(book.chapters) - 1)].content
        return {
            "index": ch.index,
            "title": ch.title,
            "content": content,
            "total_chapters": len(chapters),
        }

    # ==================================================================
    # 书架
    # ==================================================================
    def shelve(self, result: BookResult, *, fetch_toc: bool = True) -> dict:
        """把一本书放进书架：建记录 + 拉目录（不拉正文）。

        目录到手后，阅读器就能立刻画出目录、显示总章数；
        正文按需边读边补 —— 用户不用等整本下完才能开始看。
        """
        src = self._find_source(result.source)
        meta = self.library.ensure(
            result.source, result.url,
            title=result.title, author=result.author, intro=result.intro,
            source_display=(src.display if src else result.source),
        )
        if not fetch_toc:
            return meta
        if self.library.toc(meta["id"]) and meta.get("status") in ("toc", "ready", "caching"):
            return meta

        if src is None:
            raise RuntimeError(f"找不到来源: {result.source}")

        try:
            with fast_mode(retries=2, timeout=18.0):
                chapters = src.get_chapters(result)
        except Exception as e:  # noqa: BLE001
            self.library.update(meta["id"], status="failed", error=note_for_exception(e))
            raise

        if not chapters:
            self.library.update(meta["id"], status="failed", error="没有解析到目录")
            raise RuntimeError("这个来源没有解析到目录")

        self.library.save_toc(meta["id"], chapters)
        meta = self.library.update(
            meta["id"],
            status="toc",
            title=result.title or meta.get("title"),
            author=result.author or meta.get("author"),
            intro=result.intro or meta.get("intro"),
            source_display=(src.display if src else meta.get("source_display")),
        ) or meta
        meta["cached"] = self.library.count_cached(meta["id"])
        return meta

    def library_chapter(self, bid: str, index: int, *, allow_fetch: bool = True) -> dict:
        """从书架取一章：命中缓存直接返回，没命中就联网补一章并写回缓存。"""
        meta = self.library.meta(bid)
        if not meta:
            raise RuntimeError("书架里没有这本书")
        toc = self.library.toc(bid)
        if not toc:
            raise RuntimeError("这本书还没有目录")

        index = max(1, min(int(index), len(toc)))
        entry = toc[index - 1]

        hit = self.library.chapter(bid, index)
        if hit and (hit.get("content") or "").strip():
            return {
                "index": index, "title": hit.get("title") or entry["title"],
                "content": hit["content"], "total": len(toc),
                "cached": True, "prev_cached": self.library.has_chapter(bid, index - 1),
                "next_cached": self.library.has_chapter(bid, index + 1),
            }

        if not allow_fetch:
            return {"index": index, "title": entry["title"], "content": "",
                    "total": len(toc), "cached": False, "error": "尚未缓存"}

        src = self._find_source(meta["source"])
        if src is None:
            raise RuntimeError(f"来源 {meta['source']} 不可用")

        ch = Chapter(index=index, title=entry["title"], url=entry["url"])
        content = ""
        with fast_mode(retries=2, timeout=20.0):
            try:
                content = src.fetch_chapter(ch) or ""
            except Exception as e:  # noqa: BLE001
                logger.info("补章节失败 %s#%s: %s", bid, index, e)

        if not content:
            # 单页来源没有单章接口 —— 退化成按顺序抓到这一章
            try:
                with fast_mode(retries=1, timeout=30.0):
                    book = src.fetch(self._as_result(meta), progress=None, limit=index)
                for c in book.chapters:
                    if c.content.strip():
                        self.library.put_chapter(bid, c.index, c.title, c.content, c.url)
                got = self.library.chapter(bid, index)
                content = (got or {}).get("content", "")
            except Exception as e:  # noqa: BLE001
                logger.info("退化抓取失败 %s#%s: %s", bid, index, e)

        if content.strip():
            content = tidy_content(content, entry["title"])
            self.library.put_chapter(bid, index, entry["title"], content, entry["url"])

        return {
            "index": index, "title": entry["title"], "content": content,
            "total": len(toc), "cached": bool(content.strip()),
            "prev_cached": self.library.has_chapter(bid, index - 1),
            "next_cached": self.library.has_chapter(bid, index + 1),
        }

    def _as_result(self, meta: dict) -> BookResult:
        return BookResult(
            title=meta.get("title", ""), author=meta.get("author", ""),
            source=meta.get("source", ""), url=meta.get("url", ""),
            intro=meta.get("intro", ""), source_display=meta.get("source_display", ""),
        )

    def cache_book(
        self,
        bid: str,
        progress: Optional[Callable[[int, int, str], None]] = None,
        stop: Optional[Callable[[], bool]] = None,
        limit: int | None = None,
    ) -> dict:
        """把整本书的正文缓存进书架（后台任务用）。"""
        meta = self.library.meta(bid)
        if not meta:
            raise RuntimeError("书架里没有这本书")
        src = self._find_source(meta["source"])
        if src is None:
            raise RuntimeError(f"来源 {meta['source']} 不可用")

        result = self._as_result(meta)
        if not self.library.toc(bid):
            self.shelve(result)

        toc = self.library.toc(bid)
        if not toc:
            raise RuntimeError("没有目录")
        if limit:
            toc = toc[:limit]

        self.library.update(bid, status="caching")
        done = 0
        valid = 0
        consec_fail = 0
        try:
            for entry in toc:
                if stop and stop():
                    break
                if self.library.has_chapter(bid, entry["index"]):
                    done += 1
                    valid += 1
                    if progress:
                        progress(done, len(toc), entry["title"])
                    continue
                ch = Chapter(index=entry["index"], title=entry["title"], url=entry["url"])
                try:
                    content = src.fetch_chapter(ch) or ""
                except Exception:  # noqa: BLE001
                    content = ""
                if content.strip():
                    self.library.put_chapter(bid, entry["index"], entry["title"],
                                             content, entry["url"])
                    valid += 1
                    consec_fail = 0
                else:
                    consec_fail += 1
                done += 1
                if progress:
                    progress(done, len(toc), entry["title"])
                if consec_fail >= src.FAIL_FAST and valid == 0:
                    raise SourceBlocked(
                        f"连续 {consec_fail} 章都没抓到正文，"
                        f"{src.display} 可能已限流或改版"
                    )
        finally:
            self.library.update(
                bid,
                status="ready" if valid else "failed",
                cached=self.library.count_cached(bid),
            )
        return {"cached": self.library.count_cached(bid), "total": len(toc), "valid": valid}

    def remove_book(self, bid: str) -> bool:
        return self.library.delete(bid)

    # ==================================================================
    # 下载（导出文件）
    # ==================================================================
    def download(
        self,
        result: BookResult,
        progress=None,
        limit: int | None = None,
        stop: Optional[Callable[[], bool]] = None,
    ) -> Book:
        src = self._find_source(result.source)
        if src is None:
            raise RuntimeError(f"找不到来源: {result.source}")
        return src.fetch(result, progress=progress, limit=limit, stop=stop)

    def download_best(
        self,
        keyword: str,
        progress=None,
        limit: int | None = None,
        stop: Optional[Callable[[], bool]] = None,
    ) -> Book:
        """搜索并自动挑最匹配的一本下载，失败就换下一个候选。"""
        results = self.search(keyword)
        if not results:
            raise RuntimeError(f"没有找到《{keyword}》")

        last_err: Optional[Exception] = None
        for cand in results[:8]:
            if stop and stop():
                raise RuntimeError("已取消")
            try:
                logger.info("尝试下载: [%s] %s", cand.source, cand.title)
                book = self.download(cand, progress=progress, limit=limit, stop=stop)
                real = [c for c in book.chapters if len(c.content) > 50]
                if len(real) >= 3:
                    return book
                last_err = RuntimeError(f"{cand.title} 内容不完整（有效章节 {len(real)}）")
            except Exception as e:  # noqa: BLE001
                if stop and stop():
                    raise
                last_err = e
                logger.info("下载失败，换下一个: %s", e)
        raise RuntimeError(f"所有候选都失败了: {last_err}")

    def _find_source(self, name: str) -> Optional[Source]:
        for s in self._sources:
            if s.name == name:
                return s
        return None

    # ==================================================================
    # 来源健康检查
    # ==================================================================
    def check_sources(
        self,
        on_result: Optional[Callable[[dict], None]] = None,
    ) -> list[dict]:
        """并发 ping 各来源首页，报告「能不能打开」。

        小说站域名寿命普遍很短，跑一遍就能知道哪些还活着，
        免得用户在一个已经挂掉的源上白等。
        """

        def one(src: Source) -> dict:
            url = src.homepage or getattr(src, "base_url", "")
            meta = source_meta(src)
            if not url:
                return {"name": src.name, "display": src.display, "ok": None,
                        "ms": 0, "note": "无首页地址", **meta}
            t0 = time.time()
            try:
                with fast_mode(retries=0, timeout=8.0):
                    fetch_text(url)
                return {"name": src.name, "display": src.display, "ok": True,
                        "ms": int((time.time() - t0) * 1000), "note": "",
                        "url": url, **meta}
            except Exception as e:  # noqa: BLE001
                return {"name": src.name, "display": src.display, "ok": False,
                        "ms": int((time.time() - t0) * 1000),
                        "note": str(e)[:80], "url": url, **meta}

        out: list[dict] = []
        with ThreadPoolExecutor(max_workers=min(8, len(self._sources) or 1)) as pool:
            futs = {pool.submit(one, s): s for s in self._sources}
            for fut in as_completed(futs, timeout=30):
                try:
                    info = fut.result()
                except Exception as e:  # noqa: BLE001
                    src = futs[fut]
                    info = {"name": src.name, "display": src.display, "ok": False,
                            "ms": 0, "note": str(e)[:80]}
                out.append(info)
                if on_result:
                    on_result(info)
        out.sort(key=lambda x: (x["ok"] is not True, x["ms"]))
        return out
