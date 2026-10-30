# -*- coding: utf-8 -*-
"""收手判据不许被「噪声」骗：没有确切命中就再等一会儿。**纯逻辑 + 假源，不联网。**

为什么必须有这条
----------------
2026-10-24 复盘。线上日志里当天 16 次搜索 `候选=0` 是 0 次，看上去一切正常。
可拿真机复现同一批书时发现一个日志**看不见**的失败：

    搜《兄弟》  扇出 1.76s 收手 → 候选 4 条：
                「嘿兄弟」「兄弟盟」「兄弟恩仇」「盛唐兄弟」
                而 kunnu8 恰好在 1.76s 回来，带着正主
                https://www.kunnu8.com/xiongdi/ —— 被弃
    搜《围城》  同上，正主《围城》被弃，
                留下「迷雾围城」「围城日记」「数字围城」

用户看到的是"4 条候选、没有一本是那本书"，体验上等于搜不到；
可日报里 `候选=4` 看着是成功的 —— 判据压根没埋这个点。

根因：收手条件 ①②③ 看的是「候选条数够」/「答的源够多」。
两者都对**噪声**敏感：自有来源（registry）一个源就能吐 40 条沾边结果，
于是 1.5s 就判定"够了"，把还没答话的慢源和它的独有正主一起扔掉。
**"够多" ≠ "够好"**。

修法：①②③ 全部加一道「至少有一条确切命中」（tight）的门；
④ 软截止无条件保留，保证最坏情况仍有上界。

判据三问
--------
① 会不会只因环境变？——不看耗时（唯一一处耗时断言是 3s vs 60s 的 20 倍余量，
   只用来兜住"整个测试挂死"）。主判据是**结果里有没有那本书**、
   **stats 里的确切命中数**、**谁被记为未回**，都是与机器负载无关的事实。
② 把功能拆掉这条还绿吗？——把 tight 门删掉，场景 A 立刻变红（已用
   tools/mutate.py 反证）。
③ 只验了正向没验反向吗？——场景 B 是反向：**有**确切命中时必须提前收手，
   不许一律等到软截止；场景 C 是另一条反向：没有确切命中时确实等到了软截止。

用法：python tools/test_search_recall.py
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.engine as E  # noqa: E402
from app import relevance as R  # noqa: E402
from app.models import BookResult  # noqa: E402
from app.sourcehealth import HEALTH  # noqa: E402
from app.sources import DISCOVER_SOURCE  # noqa: E402
from app.sources.base import Source  # noqa: E402

ok_n = 0
fail_n = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global ok_n, fail_n
    if cond:
        ok_n += 1
        print(f"  ✓ {name}")
    else:
        fail_n += 1
        print(f"  ✗ {name}")
        if extra:
            print(f"      {extra}")


class _Cap(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, rec: logging.LogRecord) -> None:
        try:
            self.lines.append(rec.getMessage())
        except Exception:  # noqa: BLE001
            pass

    def text(self) -> str:
        return "\n".join(self.lines)


KW = "道诡异仙"
# 「弱匹配」的样本：分落在 [28, 45) —— 会被 rank 留下、但够不上推送门槛。
WEAK_TITLE = "诡仙录"
WEAK_AUTHOR = "某人"
# 这些标题**包含**关键词、打分也过门槛（STREAM_FLOOR=45），
# 但 tightness=0（多出来的那截太长，见 relevance.tightness 的注释）——
# 正是线上把「候选=4」伪装成"搜到了"的那类东西。
NOISE = ["道诡异仙：我能替换代价", "道诡异仙：我即畸变扭曲之源",
         "龙族：从道诡异仙归来的路明非", "道诡异仙外传之血月当空",
         "重生道诡异仙世界", "道诡异仙同人续写", "从道诡异仙开始的诸天",
         "道诡异仙：尸山血海", "我的道诡异仙", "道诡异仙前传",
         "道诡异仙之我为天尊", "诸天道诡异仙"]


class _NoiseFast(Source):
    """秒回一屏噪声。raw 条数轻松过 SEARCH_ENOUGH，但一条确切命中都没有。"""

    name = "recall_noise"
    display = "噪声源"
    priority = 1
    enabled = True
    delay = 0.01
    calls = 0

    def search(self, keyword):
        type(self).calls += 1
        time.sleep(type(self).delay)
        return [BookResult(title=t, url=f"http://noise/{i}", source=self.name,
                           source_display=self.display, author="某人")
                for i, t in enumerate(NOISE)]

    def get_chapters(self, url): return []
    def fetch(self, *a, **k): raise AssertionError("不该走到这")


class _TightSlow(Source):
    """慢半拍，但带的是**正主**。只有它知道这本书在哪。"""

    name = "recall_tight"
    display = "正主源"
    priority = 2
    enabled = True
    delay = 0.5
    calls = 0

    def search(self, keyword):
        type(self).calls += 1
        time.sleep(type(self).delay)
        return [BookResult(title=keyword, url="http://tight/1", source=self.name,
                           source_display=self.display, author="某人")]

    def get_chapters(self, url): return []
    def fetch(self, *a, **k): raise AssertionError("不该走到这")


class _TightFast(_TightSlow):
    name = "recall_tight_fast"
    display = "正主源(快)"
    priority = 3
    delay = 0.01


class _HangForever(Source):
    """永远不回来。用来反证"有确切命中时必须提前收手"。"""

    name = "recall_hang"
    display = "不回来的源"
    priority = 4
    enabled = True
    sleep_s = 3.0

    def search(self, keyword):
        time.sleep(type(self).sleep_s)
        return []

    def get_chapters(self, url): return []
    def fetch(self, *a, **k): raise AssertionError("不该走到这")


class _WeakOnly(Source):
    """只给一条「弱匹配」：能被 rank 留下（>=28 分），但够不上推送门槛（<45）。

    `诡仙录` 对关键词 `道诡异仙` 就是这个位置 —— 四个字里命中后半截，
    分数落在 30 出头。它**不是**这本书，但也不至于被当成垃圾扔掉，
    于是形成那条真实存在的缝：最后列表里有它、过程中一条都不推。
    """

    name = "recall_weak"
    display = "只给弱匹配"
    priority = 5
    enabled = True

    def search(self, keyword):
        return [BookResult(title=WEAK_TITLE, url="http://weak/1", source=self.name,
                           source_display=self.display, author=WEAK_AUTHOR)]

    def get_chapters(self, url): return []
    def fetch(self, *a, **k): raise AssertionError("不该走到这")


class _EmptyLocal(Source):
    """本地一条都没有 —— 逼出联网兜底。"""

    name = "recall_empty"
    display = "本地空源"
    priority = 1
    enabled = True

    def search(self, keyword): return []
    def get_chapters(self, url): return []
    def fetch(self, *a, **k): raise AssertionError("不该走到这")


class _WebTight(Source):
    """联网兜底源（lazy）。**只有它知道这本书在哪** —— 线上最常见的那种救场。"""

    name = DISCOVER_SOURCE
    display = "联网发现"
    priority = 99
    enabled = True
    lazy = True
    calls = 0

    def search(self, keyword):
        type(self).calls += 1
        return [BookResult(title=keyword, url="http://web/1", source=self.name,
                           source_display=self.display, author="某人")]

    def get_chapters(self, url): return []
    def fetch(self, *a, **k): raise AssertionError("不该走到这")


_OLD = None


def _slow_down():
    """把各阶段预算压到测试量级（默认值 1.5s + 6s 太慢）。

    ⚠ 改的是**模块常量**，所以每处读取都必须在运行时取值 ——
      这正是 E.budget_slice 那个坑的反面教材（默认参数在 def 时就求值了）。
    """
    global _OLD
    _OLD = (E.SEARCH_HARD_DEADLINE, E.SEARCH_MIN_WAIT, E.SEARCH_SOFT_DEADLINE,
            E.SEARCH_GRACE, E.SEARCH_ENOUGH, E.SEARCH_ANSWERED_RATIO)
    E.SEARCH_HARD_DEADLINE = 3.0
    E.SEARCH_MIN_WAIT = 0.05
    # 软截止给 1.5s：慢源 0.5s 一定能回来，软截止又远在它后面 ——
    # 于是"收手发生在 0.5s 还是 1.5s"只取决于 tight 门，不取决于竞速。
    E.SEARCH_SOFT_DEADLINE = 1.5
    E.SEARCH_GRACE = 99.0          # 关掉条件③（宽限期），免得它替 tight 门背锅
    E.SEARCH_ENOUGH = 12           # 噪声 12 条正好够 —— 旧实现就是被它骗的
    E.SEARCH_ANSWERED_RATIO = 0.99  # 关掉条件②（答的源占比）


def _restore():
    (E.SEARCH_HARD_DEADLINE, E.SEARCH_MIN_WAIT, E.SEARCH_SOFT_DEADLINE,
     E.SEARCH_GRACE, E.SEARCH_ENOUGH, E.SEARCH_ANSWERED_RATIO) = _OLD


def main() -> int:
    h = _Cap()
    lg = logging.getLogger("novel.engine")
    lg.addHandler(h)
    old_level = lg.level
    lg.setLevel(logging.DEBUG)
    try:
        _slow_down()
        HEALTH.reset()

        # ------------------------------------------------------------
        print("\n—— ① 噪声满屏时，慢源的正主不许被扔掉（今天的核心病灶） ——")
        # ⚠ 场景里**必须有一个不回来的源**：只有 pending 非空时引擎才会走到
        #   "收手还是再等"这个判断。两个源都答完的话，循环自然结束、
        #   压根不触发收手 —— 那样这条测试是空转（踩过）。
        capA = _Cap()
        lg.addHandler(capA)
        for cls in (_NoiseFast, _TightSlow, _HangForever):
            cls.calls = 0
        st: dict = {}
        t0 = time.time()
        res = E.Engine(sources=[_NoiseFast, _TightSlow, _HangForever]).search(
            KW, stats=st, discover=False, probe=False, sample=False)
        elA = time.time() - t0
        lg.removeHandler(capA)
        titles = [r.title for r in res]
        check("噪声源确实说话了（否则这条测试是空转，raw 都到不了 12）",
              st.get("raw", 0) >= E.SEARCH_ENOUGH,
              f"raw={st.get('raw')} 需要 >= {E.SEARCH_ENOUGH}")
        check("★ 正主《道诡异仙》出现在结果里（旧实现 1.5s 就收手、它还没回来）",
              KW in titles,
              f"结果={titles[:6]} —— 全是撞词噪声就说明正主被弃了")
        check("★ 结果里确实有一条是确切命中",
              any(r.tight for r in res),
              str([(r.title, round(r.tightness, 2)) for r in res][:6]))
        check("慢源确实被等到了（不是靠软截止蒙过去的）",
              _TightSlow.calls == 1 and elA < E.SEARCH_SOFT_DEADLINE,
              f"calls={_TightSlow.calls} 耗时={elA:.2f}s 软截止={E.SEARCH_SOFT_DEADLINE}")
        check("确切的慢源到了就收手：不回来的那个被记为「未回」",
              st.get("unreturned_sources") == ["recall_hang"],
              f"未回={st.get('unreturned_sources')}")
        # 反向：噪声源不该被误判成"没答话"
        check("噪声源仍然算「答话了」（无关结果不是「挂」，不能害它被熔断）",
              st.get("sources_answered", 0) == 2,
              f"答={st.get('sources_answered')} 挂={st.get('failed_returned_sources')}")
        check("收手日志必须写出确切条数（不然明天复盘还是看不见）",
              "确切 1 条" in capA.text(),
              capA.text()[-300:])

        # ------------------------------------------------------------
        print("\n—— ② 反向：**有**确切命中时必须提前收手，不许一律等软截止 ——")
        # 判据是机制不是耗时：不回来的那个源必须被记成「未回」。
        # 如果实现退化成"总是等满软截止"，它就会答话（sleep 3s < 软截止 60s），
        # 于是 unreturned 里没有它 —— 这条当场变红。
        _o_soft = E.SEARCH_SOFT_DEADLINE
        E.SEARCH_SOFT_DEADLINE = 60.0
        HEALTH.reset()
        stB: dict = {}
        t0 = time.time()
        resB = E.Engine(sources=[_NoiseFast, _TightFast, _HangForever]).search(
            KW, stats=stB, discover=False, probe=False, sample=False)
        elB = time.time() - t0
        E.SEARCH_SOFT_DEADLINE = _o_soft
        check("★ 有确切命中 → 提前收手（不回来的源被记为「未回」）",
              stB.get("unreturned_sources") == ["recall_hang"],
              f"未回={stB.get('unreturned_sources')} 耗时={elB:.2f}s "
              f"—— 若为空说明这一轮等它答完了（那就是一律等满软截止）")
        check("提前收手仍然秒级返回（20 倍余量，只兜「整个测试挂死」）",
              elB < 3.0, f"{elB:.2f}s")
        check("确切命中在那轮结果里", any(r.tight for r in resB),
              str([r.title for r in resB][:5]))

        # ------------------------------------------------------------
        print("\n—— ③ 反向：**没有**确切命中时，确实等到了软截止（不是一律快收） ——")
        E.SEARCH_SOFT_DEADLINE = 0.7
        HEALTH.reset()
        stC: dict = {}
        t0 = time.time()
        resC = E.Engine(sources=[_NoiseFast, _HangForever]).search(
            KW, stats=stC, discover=False, probe=False, sample=False)
        elC = time.time() - t0
        E.SEARCH_SOFT_DEADLINE = _o_soft
        check("只有噪声、没有正主 → 等满软截止才收手（0.7s 预算，给 0.5s 下限）",
              elC >= 0.5,
              f"{elC:.2f}s —— 太快说明 tight 门没起作用，噪声又被当成「够了」")
        check("这一轮确切命中数为 0（口径没算错）",
              stC.get("tight_hits") == 0 and not any(r.tight for r in resC),
              f"tight_hits={stC.get('tight_hits')}")
        # ---- 「卡满」判据用的是 pushed（真的推给用户过），不是耗时 ----
        # 这个场景是「撞满墙钟 + 有推送」的**唯一**现役样本：
        # 2026-10-24 给收手加了"到 SEARCH_MIN_WAIT 就醒来重判"之后，
        # 有确切命中的那些轮子不再靠撞满墙钟收手，于是这个组合只在这里出现。
        # 判据要卡死在 `hit_deadline 且 pushed`，不能退回只看 `hit_deadline` ——
        # 那会把"结果有了、只是还想再等等"的正常提速误报成"慢到没结果"。
        # ⚠ 2026-10-26：这里原来是 `kept`，改成 `pushed`。差额见场景⑥ ——
        #   弱匹配带上 kept>0 而 pushed=0，用 kept 判会把"空等满墙钟"漏掉。
        check("这一轮确实撞满了墙钟（否则下面那条判据是空转）",
              stC.get("hit_deadline") is True,
              f"hit_deadline={stC.get('hit_deadline')} 耗时={elC:.2f}s")
        check("★ 撞满墙钟但**推过**结果 → 不许报「卡满」"
              "（判据是 pushed，不是耗时）",
              E.source_ledger(stC)["卡满"] == "否" and stC.get("pushed", 0) > 0,
              f"卡满={E.source_ledger(stC)['卡满']} pushed={stC.get('pushed')} "
              f"kept={stC.get('kept')} hit_deadline={stC.get('hit_deadline')}")

        # ------------------------------------------------------------
        print("\n—— ④ 确切命中数必须是**量出来的**，不是常量 ——")
        HEALTH.reset()
        stD: dict = {}
        resD = E.Engine(sources=[_TightFast]).search(
            KW, stats=stD, discover=False, probe=False, sample=False)
        _n_tight = sum(1 for r in resD if r.tight)
        check("stats 里有 tight_hits 字段（旧的没有这个键）",
              "tight_hits" in stD, str(sorted(stD)[:8]))
        check("★ tight_hits 等于结果里确切命中的条数（正反两轮都成立）",
              stD.get("tight_hits") == _n_tight and _n_tight >= 1
              and stC.get("tight_hits") == 0,
              f"有正主那轮 tight_hits={stD.get('tight_hits')} 实得={_n_tight}；"
              f"纯噪声那轮 tight_hits={stC.get('tight_hits')}")

        # ------------------------------------------------------------
        print("\n—— ⑤ 联网兜底救回的正主，也必须算进「确切」（2026-10-25 病灶） ——")
        # 线上实测（搜《我们猫猫不能听这些》）：
        #     done:     候选=1 成书=1 可读=1 确切=0
        #     books[0]: title=我们猫猫不能听这些 tight=true tightness=1.0
        # 「候选=1、确切=0」在算术上就是矛盾的 —— 因为 `确切` 当时取的是
        # 扇出阶段的累加值 `tight_streamed`，而**联网兜底交回来的条目
        # 压根不经过那个循环**，所以最惊险的那条救场路径永远报 0。
        # 这条测试专门走「本地全空 → 联网救回」：扇出确切必须是 0，
        # 最终确切必须是 1，两者一起才能证明口径是算出来的、不是常量。
        HEALTH.reset()
        _WebTight.calls = 0
        stE: dict = {}
        resE = E.Engine(sources=[_EmptyLocal, _WebTight]).search(
            KW, stats=stE, discover=True, probe=False, sample=False)
        check("前置：联网兜底真的被叫起来了（否则这轮什么都没测到）",
              _WebTight.calls == 1, f"calls={_WebTight.calls}")
        check("联网救回的那本确实是确切命中", any(r.tight for r in resE),
              str([(r.title, round(r.tightness, 2)) for r in resE][:3]))
        check("前置：扇出阶段确实一条确切都没有（差值只可能来自联网）",
              stE.get("tight_streamed") == 0,
              f"tight_streamed={stE.get('tight_streamed')}")
        check("★ 确切命中数必须数**最终结果集**，不能只数扇出阶段"
              "（旧实现这里恒为 0，于是「救回来了」被记成「零正主」）",
              stE.get("tight_hits") == 1,
              f"tight_hits={stE.get('tight_hits')} 结果="
              f"{[(r.title, r.tight) for r in resE][:3]}")
        check("★ 口径对账：确切 <= 候选，且确切=0 ⟺ 结果里没有一本是这本书",
              stE.get("tight_hits") == sum(1 for r in resE if r.tight)
              and stE.get("tight_hits") <= stE.get("kept", 0),
              f"确切={stE.get('tight_hits')} 候选={stE.get('kept')}")

        # ------------------------------------------------------------
        print("\n—— ⑥ 弱匹配带：kept>0、但全程一条都没推给用户（欠账①） ——")
        # 缝在哪里：推送门槛 STREAM_FLOOR=45，而 rank 的显示门槛在 best<70 时
        # 只有 28 —— 于是 28~45 分的候选「最后列表里有、过程中一条都不推」。
        # 旧 `卡满` 判据看的是 `kept`，这种轮子会报「否」：
        #   用户对着「正在从 N 个来源里找」空等满整个墙钟，
        #   而日报里它和「有结果、只是收手时还有源没回来」长得一模一样。
        # ⚠ 这里**不判耗时**：判据是账（pushed=0 + hit_deadline）与文案，
        #   机器再忙也不会让 `pushed` 从 0 变 1。
        _s_weak = R.score(BookResult(title=WEAK_TITLE, url="http://weak/1",
                                     source="recall_weak", source_display="只给弱匹配",
                                     author=WEAK_AUTHOR), KW)
        check("前置：弱样本的分落在「会被留下、但不够推送」的带子里"
              f"（28 <= {_s_weak:.1f} < {E.STREAM_FLOOR:.0f}）",
              28.0 <= _s_weak < E.STREAM_FLOOR,
              f"分={_s_weak:.1f} —— 不在这条带子里的话，本组测的不是那个缝")
        _o_hard = E.SEARCH_HARD_DEADLINE
        E.SEARCH_HARD_DEADLINE = 0.6
        HEALTH.reset()
        capF = _Cap()
        lg.addHandler(capF)
        stF: dict = {}
        resF = E.Engine(sources=[_WeakOnly, _HangForever]).search(
            KW, stats=stF, discover=False, probe=False, sample=False)
        lg.removeHandler(capF)
        E.SEARCH_HARD_DEADLINE = _o_hard
        check("前置：候选确实被留下了，且确实撞满了墙钟"
              "（否则下面两条是空转）",
              stF.get("kept", 0) >= 1 and stF.get("hit_deadline") is True,
              f"候选={stF.get('kept')} hit_deadline={stF.get('hit_deadline')} "
              f"结果={[r.title for r in resF][:3]}")
        check("★ 整轮一条都没推给前端（pushed=0）—— 这就是「空等」的定义",
              stF.get("pushed") == 0,
              f"pushed={stF.get('pushed')} —— 若 >0 说明弱样本过了推送门槛，"
              "本组测的就不是那条缝了")
        check("★ 撞满墙钟 + 一条都没推 → 「卡满」必须是「是」"
              "（旧口径看 kept，会误报「否」）",
              E.source_ledger(stF)["卡满"] == "是",
              f"卡满={E.source_ledger(stF)['卡满']} 候选={stF.get('kept')} "
              f"pushed={stF.get('pushed')}")
        check("★ 收手日志不许说「仍无结果」——原始候选就摆在眼前",
              "仍无结果" not in capF.text() and "够推送门槛" in capF.text(),
              capF.text()[-260:] or "（没抓到收手日志，说明这条判据空转）")
    finally:
        lg.removeHandler(h)
        lg.setLevel(old_level)
        _restore()
        HEALTH.reset()

    print("\n── G. 「源池=A→B」：这次搜索顺手废掉了几个源 ──")
    # 2026-10-30 线上主线：连搜三本冷门书（乡土中国/素食者/我的阿勒泰），
    # 8 个站的搜索模板被 `registry.note_search_result` 的 search_shape 连击
    # 当场作废，可搜源 22 → 15，而当天的 `search.done` 里只有「候选=0」——
    # 源池缩水一个字都没写。这个字段量的就是这个差值。
    #
    # ① 正向：字段必须真的出现在 stats 里、并且长得像 `N→M`；
    # ② 反向：这一轮一个源都没被废，两个数必须相等（否则差值永远是假的）；
    # ③ 反向：取不到数时打 `?`，**不许**打成 `0→0`（那会被读成"源池空了"）。
    class _PoolProbe(Source):
        name = "pool_probe"
        display = "池探针"
        priority = 1
        enabled = True

        def search(self, keyword):
            return [BookResult(title=keyword, url="http://pool/1",
                               source=self.name, source_display=self.display)]

        def get_chapters(self, url): return []
        def fetch(self, *a, **k): raise AssertionError("不该走到这")

    # ⚠ 这一组**必须自带数据**，不能靠环境里的 registry：
    #   本机 `cache/registry.json` 的 searchable 是 0，于是 `0→0` 两头天然相等 ——
    #   "差值不许凭空空出现" 那条断言会**恒真**（反证实测：把 `_pool0` 抄成 0
    #   照样全绿，一条都抓不到）。所以先造一份只有 2 个可搜源的临时库。
    stP: dict = {}
    _real_pool = -1
    import importlib
    import os
    import tempfile
    from pathlib import Path as _P
    _tmpdir = tempfile.mkdtemp(prefix="pooltest_")
    _old_env = os.environ.get("NOVEL_REGISTRY")
    os.environ["NOVEL_REGISTRY"] = str(_P(_tmpdir) / "registry.json")
    from app import registry as _R
    importlib.reload(_R)          # 让 _DB 重新指向临时库
    for _h in ("poola.example", "poolb.example"):
        _R.note_site(_h, ok=True, search_tpl="/?s={kw}")
    _R.flush()
    _real_pool = len(_R.searchable_sites())
    try:
        E.Engine([_PoolProbe()]).search(KW, stats=stP, probe=False,
                                        discover=False, sample=False)
    except Exception as e:  # noqa: BLE001
        check("池探针这一轮跑完了（跑不完下面全是空转）", False, repr(e))
    finally:
        if _old_env is None:
            os.environ.pop("NOVEL_REGISTRY", None)
        else:
            os.environ["NOVEL_REGISTRY"] = _old_env
        importlib.reload(_R)
    check("前置：临时库里有 2 个可搜源（否则下面两条是空转）",
          _real_pool == 2, f"可搜源={_real_pool}")
    note = stP.get("pool_note") or ""
    check("★ 搜完必须留下「源池=A→B」（否则源池缩水永远看不见）",
          bool(__import__("re").match(r"^\d+→\d+$", note)), f"源池={note!r}")
    check("★ 两头都等于真实可搜源数（这一轮没废源，差值不许凭空出现）",
          note == f"{_real_pool}→{_real_pool}",
          f"源池={note!r} 真实={_real_pool}")
    check("★ 取不到源池时打「?」，不许补 0（0→0 会被读成源池空了）",
          E._pool_note(-1) == "?", f"_pool_note(-1)={E._pool_note(-1)!r}")

    print("\n" + "=" * 62)
    if fail_n == 0:
        print(f"通过 {ok_n} · 失败 0\n✓ 全部通过")
    else:
        print(f"通过 {ok_n} · 失败 {fail_n}\n✗ 有 {fail_n} 项没过")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
