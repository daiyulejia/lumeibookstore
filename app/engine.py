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
from .sourcehealth import HEALTH, classify
from .sources.base import Source, note_for_exception, tidy_content
from .utils import fast_mode, fetch_text, host_of

logger = logging.getLogger("novel.engine")

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
        if skipped:
            targets = [s for s in targets if s.name not in skipped]
            logger.info("跳过 %d 个熔断中的源（%s），剩 %d 个照常扇出",
                        len(skipped), ", ".join(skipped), len(targets))

        raw: list[BookResult] = []
        lock = threading.Lock()
        # 「已推给前端的条数」。**不能拿 len(raw) 当「有结果」的判据** ——
        # raw 里可能全是噪声（实测搜「诡秘之主」raw=20 条但去噪后 0 条），
        # 那种情况下用户界面上依然是空的，用软截止收手等于骗自己。
        streamed = 0

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
                HEALTH.note_ok(src.name)
                return items
            except Exception as e:  # noqa: BLE001
                # 单个来源挂掉是常态（站点会抽风、会改版、会拦爬虫），
                # 不该升级成"搜索失败"。但要留下可筛的记录：
                #   grep 'source.fail' logs/app.log  就能看出哪个源最近老出问题
                log_event(logger, "source.fail", 源=src.name,
                          原因=f"{type(e).__name__}: {e}")
                # 记进熔断器：连续挂到阈值就把这个源暂时摘出扇出名单，
                # 别让「永远打不通的源」每次都吃掉 20 秒墙钟。
                if HEALTH.note_fail(src.name, e):
                    logger.warning("源 %s 连续失败，熔断 %d 分钟（%s）",
                                   src.name,
                                   int(HEALTH.cooldown.get(classify(e), 300) // 60),
                                   f"{type(e).__name__}: {e}"[:120])
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
                    if (
                        len(raw) >= SEARCH_ENOUGH
                        or answered_ratio >= SEARCH_ANSWERED_RATIO
                        or (enough_answered and elapsed >= SEARCH_GRACE)
                        or elapsed >= SEARCH_SOFT_DEADLINE
                    ):
                        logger.info(
                            "搜索收手：已答 %d/%d 个源（%.0f%%）、原始 %d 条/推给前端 %d 条、"
                            "耗时 %.1fs，放弃 %d 个还没回来的慢源",
                            done_count, total, answered_ratio * 100,
                            len(raw), streamed, elapsed, len(pending))
                        break
                # 有结果了 → 最多等到软截止；还没结果 → 放宽到硬上限再等。
                # 这个区分是必须的：源内部会串行发多次请求（wyshu 试十来个
                # 路径），「答完」可能 8~10s。没有结果的 6 秒收手 = 把慢源饿死
                # = 返回空，比慢更糟。
                # ⚠ 判据是 streamed（真推给前端过）而不是 len(raw) —— raw 可能
                #   全是噪声，那种情况下用户看到的还是空，不能算「有结果」。
                ceiling = SEARCH_SOFT_DEADLINE if streamed else SEARCH_HARD_DEADLINE
                wait = max(0.05, ceiling - elapsed)
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
                    logger.info("客户端已断开，扇出收手：已答 %d/%d 个源",
                                done_count, total)
                    break
                if not batch:
                    # 没有任何源在这段窗口内返回 → 到头了
                    #
                    # ⚠ 这一条 break 有**语义**：它意味着「我们尽力等了，还是没等到」。
                    #   下面的联网兜底就是靠它判断的，所以必须显式记下来 ——
                    #   不能指望调用方自己拿 done_count 去比。
                    #   （踩过：线上搜「欢迎进入梦魇直播间」时 7 个源里有 2 个
                    #    永远不返回 —— wikisource 要 184s ——导致 done_count 永远
                    #    追不上 total，联网兜底被永久跳过，搜什么都 0 条。）
                    hit_deadline = True
                    logger.info(
                        "搜索收手（墙钟 %.1fs 到点，%s）：已答 %d/%d 个源、原始 %d 条",
                        time.time() - t_search,
                        "已有结果推给前端" if streamed else "仍无结果",
                        done_count, total, len(raw))
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
                            if it.score >= STREAM_FLOOR:
                                streamed += 1
                                if on_result:
                                    on_result(it)

                    # 收手判断已挪到 while 顶部（每轮开始前判）—— 放在这里
                    # 会导致「已有结果但卡在等下一个慢源」时白等到那个源回来。
                    # 本 batch 处理完若已满足条件，下一轮顶部会立刻 break。
        finally:
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
        results = rank(raw, keyword)
        log_event(logger, "search.rank", 关键词=keyword,
                  原始=len(raw), 去噪后=len(results))

        if probe and results:
            self.probe_all(results, on_verified=on_verified, top=probe_top,
                           should_stop=_stop)
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
        if results and probe and not any(r.available for r in results):
            need_web = exhausted
        # 并行已经跑过就别再串行跑一次（web_extra 已在 raw 里，rank 时合并了）
        already_web = web_thread is not None
        if discover and need_web and not already_web:
            web = self._find_source(DISCOVER_SOURCE)
            if web is not None:
                extra = self._discover(web, keyword, on_result, on_progress,
                                       search_kw=search_kws)
                if extra:
                    if probe:
                        self.probe_all(extra, on_verified=on_verified, top=len(extra),
                                       should_stop=_stop)
                    results = rank(results + extra, keyword)
                    results = self.refine(results, keyword)
        elif discover and need_web and already_web:
            # 并行已发起、本地仍无结果 → 给 web_extra 探测 + 重排
            # （上面 raw 已 extend，这里 results=rank(raw) 已包含 web_extra）
            if results and probe:
                self.probe_all(results, on_verified=on_verified, top=probe_top,
                               should_stop=_stop)
                results = self.refine(results, keyword)

        if sample and results:
            aborted = self.verify_samples(results, on_verified=on_verified,
                                          should_stop=_stop)

        if stats is not None:
            stats.update({
                "raw": len(raw),
                "kept": len(results),
                "filtered": max(0, len(raw) - len(results)),
                "available": sum(1 for r in results if r.available),
                "readable": sum(1 for r in results if r.readable),
                "sources_queried": len(targets),
                "sources_answered": done_count,
                "sources_total": len(targets),
                "timed_out": max(0, len(targets) - done_count),
                "search_ms": int((time.time() - t_search) * 1000),
                "ms": int((time.time() - t_start) * 1000),
                "discovered": sum(1 for r in results if r.source == DISCOVER_SOURCE),
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
            for look_for in looks:
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
            for fut in as_completed(futs, timeout=PROBE_BUDGET):
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
            for fut in as_completed(futs, timeout=SAMPLE_BUDGET):
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
