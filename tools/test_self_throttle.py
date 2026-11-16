# -*- coding: utf-8 -*-
"""「被我们自己的限流冷却挡住」不许记成「源挂了」。

为什么必须有这条
================
2026-11-16 复盘，本地实例日志里抓到的**当场复发**的病灶（09:51:31~09:51:48）：

    09:51:31  xbqg5200 返回空壳页面（59 字节），判定为限流并进入冷却 120s
    09:51:33  source.fail 源=xbqg5200 原因="RuntimeError: 该站点刚被限流，冷却中（还剩 118s）"
    09:51:48  WARNING 源 xbqg5200 连续失败，熔断 5 分钟（…冷却中（还剩 104s））

根因是一条**自噬循环**（不是站坏了）：

    我们打太快 → 站返回空壳 → `utils.mark_blocked` 把域名关 120s（对的，这是保护）
    → 冷却期内每次搜索都被打一次 → `fetch_text` 立刻抛 LocalCooldown（对的，没发请求）
    → 引擎把它当"源抛异常" → `HEALTH.note_fail` → 3 次 → 全局熔断 300s
    → **熔断比冷却还长**，且 streak+1（下次 10 分钟、20 分钟…封顶 8 小时）

于是"只是我们打太快"的站被自己的保护机制判死，越保护越死。
它还会污染日报：`挂=xbqg5200` 读起来是"这个站坏了"，处置却是"降速/等它"。

这里钉四件事（三条正向 + 三条反向，缺一条就是恒真）：
  ① 抛出型（`raise LocalCooldown`）→ 进 `自限=`，不进 `挂=`，不喂熔断器
  ② 吞异常型（`note_error(LocalCooldown)` 后 `return []`）→ 同样处置
     ⚠ 这是**另一条入口**：2026-11-11 的教训是"闸门装在一个入口上等于没装"，
       很多源（wikisource / xbqg5200 / kunnu8）是自己 catch 掉再 return [] 的。
  ③ 真的挂了（普通 RuntimeError）→ 仍然进 `挂=` 并且**必须**喂熔断器
  ④ 账加得起来：答+挂+未回+熔断+自限 == 应搜

用法：python tools/test_self_throttle.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.engine as E  # noqa: E402
import app.utils as U  # noqa: E402
from app.errors import LocalCooldown, is_local_cooldown  # noqa: E402
from app.models import BookResult  # noqa: E402
from app.sources.base import Source  # noqa: E402

ok_n = 0
fail_n = 0

# ⚠ 每个场景用**独立源名**：同一个进程里熔断器是共享的，重名会让
#   后面的场景一开始就被前面拉黑（2026-10-31 踩过：测试"绿的是空转"）。
_H = E.HEALTH


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


def _cap(name: str = "novel.engine"):
    h = _Cap()
    lg = logging.getLogger(name)
    lg.addHandler(h)
    old = lg.level
    lg.setLevel(logging.DEBUG)
    return h, lg, old


def _uncap(h, lg, old):
    lg.removeHandler(h)
    lg.setLevel(old)


# ---------------------------------------------------------------- 假源


class _ThrottleRaise(Source):
    """冷却期内直接抛（多数源走的就是这条：fetch_text 第一句就 raise）。"""

    name = "thr_raise"
    display = "自限流-抛型"
    priority = 1
    enabled = True

    def search(self, keyword):
        raise LocalCooldown(118, "www.thr-raise.test")

    def probe(self, r): return {}
    def sample(self, r): return {}
    def get_chapters(self, url): return []
    def fetch(self, *a, **k): raise AssertionError("不该走到这")


class _ThrottleSwallow(Source):
    """自己 catch 掉、只把一句话交给引擎（wikisource/xbqg5200 那类）。

    ⚠ 这条路径拿到的是**字符串**，不是异常对象 —— 只靠 isinstance 认不出来。
    """

    name = "thr_swallow"
    display = "自限流-吞型"
    priority = 1
    enabled = True

    def search(self, keyword):
        self.note_error(LocalCooldown(104, "www.thr-swallow.test"))
        return []

    def probe(self, r): return {}
    def sample(self, r): return {}
    def get_chapters(self, url): return []
    def fetch(self, *a, **k): raise AssertionError("不该走到这")


class _RealBroken(Source):
    """真的挂了（对照组）。必须进 `挂=` 并喂熔断器，否则上面两条就是恒真。"""

    name = "thr_broken"
    display = "真挂了"
    priority = 1
    enabled = True

    def search(self, keyword):
        raise RuntimeError("HTTP 502")

    def probe(self, r): return {}
    def sample(self, r): return {}
    def get_chapters(self, url): return []
    def fetch(self, *a, **k): raise AssertionError("不该走到这")


class _Fine(Source):
    """正常源，用来把账凑成"多源"（只有 1 个源时账加得起来是废话）。"""

    name = "thr_fine"
    display = "正常源"
    priority = 1
    enabled = True

    def search(self, keyword):
        return [BookResult(title=keyword, url="http://thr-fine/1",
                           source="thr_fine", source_display="正常源", author="某人")]

    def probe(self, r):
        r.available = True
        r.chapter_count = 10
        return {"ok": True}

    def sample(self, r):
        r.sample_ok = True
        return {"chars": 900}

    def get_chapters(self, url): return []
    def fetch(self, *a, **k): raise AssertionError("不该走到这")


def _search_once(sources, kw: str) -> tuple[dict, list]:
    st: dict = {}
    res = E.Engine(sources=sources).search(
        kw, stats=st, discover=False, probe=False, sample=False)
    return st, res


def main() -> int:
    print("=" * 70)
    print("自限流冷却 ≠ 源挂了")
    print("=" * 70)

    # ---- 0. 类型判据本身 ----
    print("\n[0] 异常类型与文本判据")
    check("0a LocalCooldown 是 RuntimeError 的子类（既有 except 不受影响）",
          issubclass(LocalCooldown, RuntimeError))
    _c = LocalCooldown(118.4, "x.test")
    check("0b 消息里带剩余秒数（人能读懂）",
          "还剩 118s" in str(_c), str(_c))
    check("0c is_local_cooldown 认异常对象",
          is_local_cooldown(_c) is True)
    check("0d is_local_cooldown 认 take_error() 交回来的字符串",
          is_local_cooldown("LocalCooldown: 该站点刚被限流，冷却中（还剩 104s）") is True)
    check("0e 反向：普通错误不被误认",
          is_local_cooldown("RuntimeError: HTTP 502") is False
          and is_local_cooldown("") is False)

    # ---- 0f. fetch_text 真的抛这个类型（不是我们只在测试里造） ----
    # ⚠ 用 127.0.0.1:1：冷却期内**根本不会发请求**，所以端口是假的也无所谓。
    _url = "http://127.0.0.1:1/thr-probe"
    U.mark_blocked(_url, 60)
    try:
        U.fetch_text(_url)
        check("0f 冷却期内 fetch_text 抛 LocalCooldown", False, "没有抛任何异常")
    except LocalCooldown as e:
        check("0f 冷却期内 fetch_text 抛 LocalCooldown", True)
        check("0g 抛出来的实例带剩余秒数（>0）", e.seconds > 0, f"seconds={e.seconds}")
    except Exception as e:  # noqa: BLE001
        check("0f 冷却期内 fetch_text 抛 LocalCooldown", False,
              f"抛的是 {type(e).__name__}: {e}")
    finally:
        U.cooldown_clear()

    # ---- 1. 抛型：进 自限=，不进 挂= ----
    print("\n[1] 抛型（raise LocalCooldown）")
    _H.reset()
    _cap_h, _lg, _old = _cap()
    try:
        st1, _ = _search_once([_ThrottleRaise()], "自限流甲")
    finally:
        _txt1 = _cap_h.text()
        _uncap(_cap_h, _lg, _old)
    _led1 = E.source_ledger(st1)
    check("1a ★ 记进「自限」而不是「挂」",
          _led1["自限"] == "1(thr_raise)" and _led1["挂"] == "0",
          f"自限={_led1['自限']} 挂={_led1['挂']}")
    check("1b sources_failed 里没有它（日报不会写「这个站坏了」）",
          st1.get("sources_failed") == 0
          and st1.get("selfthrottle_sources") == ["thr_raise"],
          f"挂={st1.get('failed_returned_sources')} "
          f"自限={st1.get('selfthrottle_sources')}")
    check("1c ★ 它没有被喂进熔断器（连记 1 次不该开）",
          _H.is_open("thr_raise") is False, f"open={_H.open_sources()}")
    check("1d ★ 日志点名了，且不是 source.fail",
          "source.skip" in _txt1 or "本地限流冷却" in _txt1,
          _txt1[-400:])
    check("1e 日志没把它写成故障（不许用 source.fail 的措辞）",
          "连续失败" not in _txt1 and "source.fail" not in _txt1, _txt1[-400:])

    # ---- 2. 连做 3 轮仍然不开（这才是"不喂熔断器"的真判据） ----
    print("\n[2] 连续 3 轮自限流 → 熔断器仍然不动作")
    _H.reset()
    for _ in range(3):
        _search_once([_ThrottleRaise()], "自限流乙")
    check("2a ★ 三轮自限流之后仍未熔断（旧实现第 3 轮就封 5 分钟）",
          _H.is_open("thr_raise") is False,
          f"open={_H.open_sources()} snapshot={_H.snapshot().get('thr_raise')}")
    # 反向：真挂了的三轮**必须**熔断，否则上面这条是恒真
    for _ in range(3):
        _search_once([_RealBroken()], "对照丙")
    check("2b ★ 反向：真挂了三轮必须熔断（证明 2a 不是恒真）",
          _H.is_open("thr_broken") is True,
          f"open={_H.open_sources()}")

    # ---- 3. 吞型：另一条入口 ----
    print("\n[3] 吞型（note_error 后 return []）—— 闸门不能只装一半")
    _H.reset()
    st3, _ = _search_once([_ThrottleSwallow()], "自限流丁")
    _led3 = E.source_ledger(st3)
    check("3a ★ 吞异常的路径也认得出（字符串标记）",
          _led3["自限"] == "1(thr_swallow)" and _led3["挂"] == "0",
          f"自限={_led3['自限']} 挂={_led3['挂']}")
    for _ in range(2):
        _search_once([_ThrottleSwallow()], "自限流戊")
    check("3b ★ 吞型连做 3 轮也不熔断",
          _H.is_open("thr_swallow") is False, f"open={_H.open_sources()}")

    # ---- 4. 账加得起来 ----
    print("\n[4] 源账：答 + 挂 + 未回 + 熔断 + 自限 == 应搜")
    _H.reset()
    st4, _ = _search_once([_Fine(), _ThrottleRaise(), _RealBroken()], "账目己")
    _led4 = E.source_ledger(st4)
    _sum4 = (st4.get("sources_answered", 0) + st4.get("sources_failed", 0)
             + st4.get("sources_unreturned", 0) + st4.get("sources_breaker", 0)
             + st4.get("sources_selfthrottle", 0))
    check("4a ★ 五格之和 == 应搜（多一个 自限 之后仍然加得起来）",
          _sum4 == st4.get("sources_total") == 3,
          f"答={st4.get('sources_answered')} 挂={st4.get('sources_failed')} "
          f"未回={st4.get('sources_unreturned')} 熔断={st4.get('sources_breaker')} "
          f"自限={st4.get('sources_selfthrottle')} 应搜={st4.get('sources_total')}")
    check("4b 一格一个名字，互不串门",
          _led4["答"] == "1/3" and _led4["挂"] == "1(thr_broken)"
          and _led4["自限"] == "1(thr_raise)", str(_led4))

    # ---- 5. 同一母题第二处：榜单侧 ----
    # ⚠ 只修搜索那一条等于把闸门装在一半入口上（2026-11-11 的教训）。
    #   榜单每 30 分钟刷一轮，同一轮里一个源的 5 个类目会各记一次失败 ——
    #   一次抖动就能把它在榜单侧封 5 分钟，代价是那一类榜单停更。
    print("\n[5] 榜单侧（ranks._fetch_source）也不许把自限流记成故障")
    import app.ranks as R  # noqa: E402

    _H.reset()
    _rsrc = {"key": "thr_ranks", "url": "http://127.0.0.1:1/ranks-{kind}",
             "parser": lambda h, k: [], "kinds": {"allvisit"}}
    U.mark_blocked("http://127.0.0.1:1/ranks-allvisit", 60)
    try:
        for _ in range(3):
            R._fetch_source(_rsrc, "allvisit")
    finally:
        U.cooldown_clear()
    check("5a ★ 三轮自限流之后，榜单侧的熔断器也没动作",
          _H.is_open("ranks:thr_ranks") is False,
          f"open={_H.open_sources()} "
          f"snapshot={_H.snapshot().get('ranks:thr_ranks')}")

    # 反向：真挂了三轮**必须**熔断（否则 5a 是恒真）
    _H.reset()
    _rsrc2 = {"key": "thr_ranks_broken", "url": "http://127.0.0.1:1/rb-{kind}",
              "parser": lambda h, k: [], "kinds": {"allvisit"}}
    _orig_fetch = R.fetch_text

    def _boom(url, **kw):
        raise RuntimeError("HTTP 502")

    R.fetch_text = _boom
    try:
        for _ in range(3):
            R._fetch_source(_rsrc2, "allvisit")
    finally:
        R.fetch_text = _orig_fetch
    check("5b ★ 反向：榜单侧真挂了三轮必须熔断（证明 5a 不是恒真）",
          _H.is_open("ranks:thr_ranks_broken") is True,
          f"open={_H.open_sources()}")

    # ⚠ 收尾必须清干净：`HEALTH` 是进程级单例，在本机会把假源名写进
    #   `cache/sourcehealth.json`，之后 `/api/registry`、排障日志里都会
    #   出现一个不存在的站（`thr_ranks_broken`），徒增困惑。
    _H.reset()

    print("\n" + "=" * 70)
    print(f"通过 {ok_n} / 失败 {fail_n}")
    print("=" * 70)
    return 1 if fail_n else 0


if __name__ == "__main__":
    raise SystemExit(main())
