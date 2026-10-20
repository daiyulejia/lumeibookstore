# -*- coding: utf-8 -*-
"""搜索「总预算」测试：整轮搜索最多花多少秒。**纯逻辑 + 假源，不联网。**

为什么必须有这条
----------------
对外说的是"搜一本书最多等 20 秒"，而线上实测（2026-10-21）这条契约被违反了：

    02:11:56  search.done 书名=重生之爷太重口了 耗时ms=20771
    02:13:59  search.done 书名=重生之爷太重口了 耗时ms=20577
    02:17:47  search.done 书名=重生之爷太重口了 耗时ms=30313   ← 30 秒

根因不是某个源变慢了，而是**三段各有各的预算、谁也不看前面花了多少**：

    扇出  SEARCH_HARD_DEADLINE  20s
    探测  PROBE_BUDGET          12s
    抽样  SAMPLE_BUDGET         10s     最坏 42s

每段都"在自己预算内正常完成"，所以**一条错都不报** —— 这种违约最难发现。

所以这里验的不是"某段快不快"，而是三个因果问题：
  ① 剩余预算算得对不对（含"时间过冲时不能返回负数"）
  ② 预算给多少就真的只花多少（给 0.2 秒的探测预算，不能验出 5 个）
  ③ 预算用完时**说出来**了吗（静默跳过 = 把"没验"伪装成"验过但不行"）

用法：python tools/test_engine_budget.py
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.engine as E  # noqa: E402
from app.models import BookResult  # noqa: E402
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
    """抓日志。判「跳过要说明」只能靠它 —— 静默跳过不留任何痕迹。"""

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


def _cap(logger_name: str = "novel.engine"):
    h = _Cap()
    lg = logging.getLogger(logger_name)
    lg.addHandler(h)
    old = lg.level
    lg.setLevel(logging.DEBUG)
    return h, lg, old


def _uncap(h, lg, old):
    lg.removeHandler(h)
    lg.setLevel(old)


class _Slow(Source):
    """搜索慢、但会回一条候选的源（用来把扇出时间烧掉）。"""

    name = "slow_src"
    display = "慢源"
    priority = 1
    enabled = True
    delay = 0.4
    calls = 0

    def search(self, keyword):
        type(self).calls += 1
        time.sleep(type(self).delay)
        return [BookResult(title=keyword, url="http://slow/1", source="slow_src",
                           source_display="慢源", author="某人")]

    def probe(self, r):
        r.available = True
        r.chapter_count = 10
        return {}

    def sample(self, r):
        r.sample_ok = True
        return {"chars": 900}

    def get_chapters(self, url): return []
    def fetch(self, *a, **k): raise AssertionError("不该走到这")


class _SlowProbe(Source):
    """搜索秒回，但**探测很慢** —— 专门用来验"探测预算给多少就花多少"。"""

    name = "slowprobe_src"
    display = "探测慢的源"
    priority = 2
    enabled = True
    probe_s = 1.0
    probed = 0

    def search(self, keyword):
        return [BookResult(title=f"{keyword}{i}", url=f"http://sp/{i}",
                           source="slowprobe_src", source_display="探测慢的源",
                           author="某人") for i in range(5)]

    def probe(self, r):
        type(self).probed += 1
        time.sleep(type(self).probe_s)
        r.available = False          # 反正验不出可用，重点是"验了几个"
        return {}

    def sample(self, r):
        return {}

    def get_chapters(self, url): return []
    def fetch(self, *a, **k): raise AssertionError("不该走到这")


class _SlowSample(Source):
    """搜索快、探测快、**抽样很慢** —— 专门验"抽样那段也认总预算"。"""

    name = "slowsample_src"
    display = "抽样慢的源"
    priority = 3
    enabled = True
    sample_s = 1.0

    def search(self, keyword):
        return [BookResult(title=f"{keyword}{i}", url=f"http://ss/{i}",
                           source="slowsample_src", source_display="抽样慢的源",
                           author="某人") for i in range(3)]

    def probe(self, r):
        # ⚠ 必须回 {"ok": True}：引擎是按 `bool(info.get("ok"))` 定 available 的，
        #   回空字典等于"探测失败" —— 抽样只挑 available 为真的候选，
        #   于是抽样一条都不会跑，而「一本都没验成」那条判据会**恒绿**。
        return {"ok": True, "chapters": 20, "ms": 1}

    def sample(self, r):
        time.sleep(type(self).sample_s)
        # 同理必须回 ok=True：引擎按 `info.get("ok")` 记 sample_ok，
        # 回空字典会让「验成几本」永远是 0 —— 判据于是恒绿。
        return {"ok": True, "chars": 1200}

    def get_chapters(self, url): return []
    def fetch(self, *a, **k): raise AssertionError("不该走到这")


def main() -> int:
    # --------------------------------------------------------------
    print("\n—— ① 剩余预算怎么算 ——")
    now = time.time()
    check("刚开跑时给满额", abs(E.budget_slice(now, 12.0) - 12.0) < 0.01)
    check("已耗 3 秒、本阶段要 30 秒 → 只给 (总量-3)",
          abs(E.budget_slice(now - 3.0, 30.0) - (E.SEARCH_TOTAL_BUDGET - 3.0)) < 0.2,
          str(E.budget_slice(now - 3.0, 30.0)))
    check("已耗 3 秒、本阶段只要 12 秒 → 仍给满 12（剩余比满额多时不多给也不克扣）",
          abs(E.budget_slice(now - 3.0, 12.0) - 12.0) < 0.2,
          str(E.budget_slice(now - 3.0, 12.0)))
    check("本阶段满额大于剩余时，按剩余给（不能多给）",
          E.budget_slice(now - (E.SEARCH_TOTAL_BUDGET - 2.0), 12.0) <= 2.2)
    check("预算已用光 → 返回 0", E.budget_slice(now - 99.0, 12.0) == 0.0)
    # ⚠ 反向：时间过冲（时钟跳变 / 已耗超总预算）时**不许返回负数**。
    #   负数传给 as_completed 会立刻抛 TimeoutError，看着像"超时"，
    #   实际是"算出了个不可能的值" —— 这种静默错误最难追。
    check("时间过冲时返回 0 而不是负数", E.budget_slice(now - 9999.0, 12.0) >= 0.0,
          str(E.budget_slice(now - 9999.0, 12.0)))
    check("总预算可被显式覆盖（测试/特殊场景要用，且证明它读的是入参不是常量）",
          abs(E.budget_slice(now - 5.0, 12.0, total=8.0) - 3.0) < 0.2)
    # 这一条是给「改模块常量当突变靶点」那个坑上的保险：
    # 默认值必须是 None 才会在现场读常量，写死在 def 里的话下面这条恒绿。
    _old = E.SEARCH_TOTAL_BUDGET
    E.SEARCH_TOTAL_BUDGET = 1.0
    try:
        check("改模块常量后 budget_slice 立刻跟着变（说明没在 def 时求值）",
              E.budget_slice(now, 12.0) <= 1.01, str(E.budget_slice(now, 12.0)))
    finally:
        E.SEARCH_TOTAL_BUDGET = _old

    # --------------------------------------------------------------
    print("\n—— ② 探测：给多少预算就只花多少 ——")
    _SlowProbe.probed = 0
    eng = E.Engine(sources=[_SlowProbe])
    cands = _SlowProbe().search("预算书")
    t0 = time.time()
    out = eng.probe_all(cands, top=5, budget=0.25)
    spent = time.time() - t0
    check("预算 0.25s，实际没有拖到满额 1s", spent < 0.9, f"实际花了 {spent:.2f}s")
    check("超预算的候选保持「未验证」(available is None)，不是被标成不可用",
          sum(1 for r in out if r.available is None) >= 1,
          f"未验证 {sum(1 for r in out if r.available is None)} / {len(out)}")
    check("没有把「没验」说成「验过不可用」",
          all(r.available is not False or r.note for r in out),
          "有候选被标成不可用却没有任何原因")

    # --------------------------------------------------------------
    print("\n—— ③ 探测预算为 0：立刻返回，且不谎报「验过」 ——")
    _SlowProbe.probed = 0
    _SlowProbe.probe_s = 1.0
    reported: list[BookResult] = []
    eng0 = E.Engine(sources=[_SlowProbe])
    cands0 = _SlowProbe().search("零预算")
    t0 = time.time()
    eng0.probe_all(cands0, top=5, budget=0.0, on_verified=reported.append)
    spent0 = time.time() - t0
    # 提交给线程池的 future 已经在跑了，撤不回来 —— 但**必须立刻返回**，
    # 不能把用户一起拖到探测结束。这里验的是"不阻塞"，不是"线程没启动"。
    check("budget=0 时立刻返回，不等那 1 秒的探测",
          spent0 < 0.6, f"实际等了 {spent0:.2f}s")
    check("budget=0 时没有回调任何「已验」事件（不谎报）",
          len(reported) == 0, f"回调了 {len(reported)} 条")

    # --------------------------------------------------------------
    print("\n—— ④ 引擎级：总预算用光时跳过探测，并打日志说出来 ——")
    _old_total, _old_deadline = E.SEARCH_TOTAL_BUDGET, E.SEARCH_HARD_DEADLINE
    _old_reserve = E.SAMPLE_RESERVE
    # 把总预算压到"扇出还没跑完就用光"。扇出受 SEARCH_HARD_DEADLINE 管，
    # 这里把它一起压小，让这一轮必然在预算边缘结束。
    E.SEARCH_TOTAL_BUDGET = 0.3
    E.SAMPLE_RESERVE = 5.0        # 让探测那笔预算直接算成负数
    _Slow.delay = 0.5             # 扇出比总预算还慢
    h, lg, old = _cap()
    try:
        eng2 = E.Engine(sources=[_Slow])
        stats: dict = {}
        res = eng2.search("预算书", stats=stats, discover=False, sample=False)
    finally:
        _uncap(h, lg, old)
        E.SEARCH_TOTAL_BUDGET, E.SEARCH_HARD_DEADLINE = _old_total, _old_deadline
        E.SAMPLE_RESERVE = _old_reserve
    txt = h.text()
    check("预算给的数被如实报进 stats", stats.get("budget_s") == 0.3,
          str(stats.get("budget_s")))
    check("stats 里有 over_budget 这个判据字段", "over_budget" in stats, str(sorted(stats)))
    check("预算用光时打了「跳过探测」的日志（不是静默跳过）",
          "跳过探测" in txt, f"日志里没有：\n{txt[-500:]}")
    check("跳过探测时日志给出了已耗时间（复盘要能算账）",
          "已耗" in txt)

    # --------------------------------------------------------------
    print("\n—— ⑤ 正常预算下别把功能改坏 ——")
    E.SEARCH_TOTAL_BUDGET = 22.0
    _SlowProbe.probe_s = 0.0
    _SlowProbe.probed = 0
    eng3 = E.Engine(sources=[_SlowProbe])
    stats3: dict = {}
    got = eng3.search("正常书", stats=stats3, discover=False, sample=False)
    check("总预算充足时探测照常跑（真验了，不是被跳过）",
          _SlowProbe.probed >= 1, f"probed={_SlowProbe.probed}")
    check("总预算充足时不会误报超预算", stats3.get("over_budget") is False,
          str(stats3.get("over_budget")))
    check("正常路径仍有结果", bool(got), f"拿到 {len(got)} 条")

    # --------------------------------------------------------------
    print("\n—— ⑥ 抽样那一段也认总预算（不是只有探测认） ——")
    # 为什么单独验：②⑤ 只证明"探测"这一段被管住。抽样是**另一段**
    # 各自满额 10 秒的代码，产品上完全可以只给探测接预算、把抽样漏掉 ——
    # 那种情况下总耗时照样能到 30 秒，而上面所有判据全绿。
    #
    # ⚠ 这里踩了一次"恒真判据"：最初写成「把总预算调到 0.8 秒，
    #   断言抽样一本都没验成」。结果它不是抓住了"抽样不看预算"，
    #   而是**总预算太小导致探测先被跳过**，没有 available 的候选，
    #   抽样本来就不会跑 —— 也就是说这条判据在任何实现下都是绿的。
    #   反证当场把它抓出来了（第 6 条突变漏网）。
    #   所以必须分两层：先单测 verify_samples 自己认不认 budget，
    #   再单测引擎有没有把 budget 传下去。
    _SlowSample.sample_s = 1.0
    eng4 = E.Engine(sources=[_SlowSample])
    cands4 = _SlowSample().search("抽样书")
    for r in cands4:
        r.available = True          # 直接给好前提，绕开探测
    t0 = time.time()
    eng4.verify_samples(cands4, budget=0.3)
    spent4 = time.time() - t0
    done4 = sum(1 for r in cands4 if getattr(r, "sample_ok", None))
    check("verify_samples(预算 0.3s) + 抽样要 1s → 一本都没验成",
          done4 == 0, f"验成 {done4} 本 —— 抽样没看 budget 参数")
    check("verify_samples(预算 0.3s) 立刻返回，不等满额",
          spent4 < 0.9, f"花了 {spent4:.2f}s")

    # 反向：预算充足时必须真能验出正文 —— 否则上面那条"0 本"可能只是
    # 因为抽样压根没实现（恒为 0 的判据没有牙）。
    cands5 = _SlowSample().search("抽样书")
    for r in cands5:
        r.available = True
    _SlowSample.sample_s = 0.0
    eng5 = E.Engine(sources=[_SlowSample])
    eng5.verify_samples(cands5, budget=10.0)
    done5 = sum(1 for r in cands5 if getattr(r, "sample_ok", None))
    check("预算充足时抽样真能验出正文（反证上面那条不是恒真）",
          done5 >= 1, f"验成 {done5} 本")

    # —— 第二层：引擎真的把预算传下去了吗 ——
    # 单测 verify_samples 认 budget 还不够：引擎完全可以照旧按满额调用它
    # （= 抽样那段永远拿 10 秒），而所有"verify_samples 认 budget"的判据全绿。
    seen: dict = {}

    def _spy(results, **kw):
        seen.update(kw)
        return False

    _SlowSample.sample_s = 0.0
    eng6 = E.Engine(sources=[_SlowSample])
    eng6.verify_samples = _spy          # 猴补在实例上，engine 里是 self.xxx
    eng6.search("抽样书", stats={}, discover=False, sample=True)
    check("引擎调用抽样时**传了** budget", "budget" in seen,
          f"实际参数：{sorted(seen)}")
    check("传下去的 budget 不超过本段满额（真的被总预算约束，不是抄了个大数）",
          float(seen.get("budget", 1e9)) <= E.SAMPLE_BUDGET + 0.001,
          f"budget={seen.get('budget')} 满额={E.SAMPLE_BUDGET}")

    # --------------------------------------------------------------
    print("\n—— ⑦ 搜索账目要能复盘（日志里看得见丢了什么） ——")
    # 动机：`search.rank 原始=14 去噪后=2` 这一行只能看出"丢了 12 条"，
    # 看不出那 12 条是"站点返回了别的书"还是"规则把好结果挤掉了"。
    # 前者该换源，后者该改规则 —— 处置相反，而它们在那行日志里长得一模一样。
    class _Noisy(Source):
        name = "noisy_src"
        display = "返回一堆无关书的源"
        priority = 4
        enabled = True

        def search(self, keyword):
            out = [BookResult(title=keyword, url="http://noisy/1",
                              source="noisy_src", source_display="返回一堆无关书的源",
                              author="某人")]
            out += [BookResult(title=f"完全无关的书{i}", url=f"http://noisy/n{i}",
                               source="noisy_src", source_display="返回一堆无关书的源",
                               author="路人") for i in range(6)]
            return out

        def probe(self, r): return {"ok": True, "chapters": 5, "ms": 1}
        def sample(self, r): return {"ok": True, "chars": 500}
        def get_chapters(self, url): return []
        def fetch(self, *a, **k): raise AssertionError("不该走到这")

    h, lg, old = _cap()
    try:
        eng7 = E.Engine(sources=[_Noisy])
        eng7.search("复盘书", stats={}, discover=False, sample=False)
    finally:
        _uncap(h, lg, old)
    txt7 = h.text()
    check("丢弃明细有独立事件 search.rank.drop", "search.rank.drop" in txt7,
          "日志里只有 search.rank，没法复盘 —— 这就是本轮要修的")
    check("明细里带上了被丢的标题（不是只有个数字）",
          "完全无关的书" in txt7, f"日志：\n{txt7[-400:]}")
    check("明细里分开了「低于门槛」和「非确切命中被挤掉」两类",
          "低于门槛" in txt7 and "非确切命中" in txt7)

    print("\n" + "=" * 62)
    if fail_n == 0:
        print(f"通过 {ok_n} · 失败 0\n✓ 全部通过")
    else:
        print(f"通过 {ok_n} · 失败 {fail_n}\n✗ 有 {fail_n} 项没过")
    print("=" * 62)
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
