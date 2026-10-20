# -*- coding: utf-8 -*-
"""榜单「立即刷新」的行为测试（`app/ranks.py::refresh`）。**纯逻辑，不联网。**

为什么单独立一条
----------------
线上实测（2026-10-21 日志）：「立即刷新」两次分别用了 **47.2 秒 / 33.0 秒**
（`POST /api/ranks/refresh status=200 ms="47229 慢"`）。
用户点一下刷新就是盯着转圈将近一分钟。

根因：`refresh()` 把 7 个类别**串行**跑 —— 每个类别内部虽然并发，
但类别之间一个接一个，总时长 = 7 份单类耗时相加。
最要命的是**这个按钮原先一条测试都没有**，所以串行改并发这件事没人会拦。

这条测试盯三件事：
  1. 类别之间**真的并发**（不是"开了线程池但还是一个一个等"）
  2. 撞总预算必须**如实报 pending**（收手可以，不许沉默收手）
  3. 单类失败不拖垮其它类；只有真抓到的才覆盖缓存

⚠ 关于第 1 条怎么验：**绝不能用"耗时小于 X 秒"当判据** ——
  那东西随机器负载漂，CI 上必假红（本项目的经典教训）。
  这里改成观测**同时在跑的 `_fetch_one` 有几个**：串行实现下这个峰值永远是 1，
  并发实现下会 ≥2。这是因果证据，不是时间阈值。

用法：python tools/test_ranks_refresh.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 隔离：绝不碰生产 cache/ranks.json
_TMP = Path(tempfile.mkdtemp(prefix="novel-ranks-test-"))
os.environ["NOVEL_RANKS"] = str(_TMP / "ranks.json")

from app import ranks as R  # noqa: E402

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


class Probe:
    """替身 `_fetch_one`：记录并发峰值与调用次数。"""

    def __init__(self, *, delay: float = 0.12, fail: tuple[str, ...] = (),
                 empty: tuple[str, ...] = ()):
        self.delay = delay
        self.fail = set(fail)
        self.empty = set(empty)
        self.lock = threading.Lock()
        self.cur = 0
        self.peak = 0
        self.calls: list[str] = []

    def __call__(self, kind: str):
        with self.lock:
            self.cur += 1
            self.peak = max(self.peak, self.cur)
            self.calls.append(kind)
        try:
            time.sleep(self.delay)
            if kind in self.fail:
                raise RuntimeError("站点抽风（模拟）")
            if kind in self.empty:
                return []
            return [{"title": f"{kind} 的书", "url": f"https://x/{kind}/1"}]
        finally:
            with self.lock:
                self.cur -= 1


def use(probe: Probe, *, budget: float = 25.0):
    R._fetch_one = probe                       # noqa: SLF001
    R.RANKS_REFRESH_BUDGET = budget            # noqa: SLF001


def main() -> int:
    kinds = [d["kind"] for d in R.SUPPORTED]
    print(f"\n临时缓存：{R._DB}")
    print(f"榜单类别：{len(kinds)} 个 —— {', '.join(kinds)}")

    orig_fetch = R._fetch_one
    orig_budget = R.RANKS_REFRESH_BUDGET

    try:
        # -------------------------------------------------------------
        print("\n—— 类别之间必须并发（线上 47s 的病根）——")
        R._CACHE.clear()
        p = Probe()
        use(p)
        rep = R.refresh(force=True)
        print(f"     并发峰值 {p.peak} · 调用 {len(p.calls)} 次 · 用时 {rep['elapsed']}s")
        check("真的并发跑了（并发峰值 ≥2）", p.peak >= 2,
              f"峰值只有 {p.peak} —— 这正是串行实现的形状（47 秒就是这么来的）")
        check("每个类别都被抓了一次", len(p.calls) == len(kinds),
              f"调用了 {len(p.calls)} 次 / 共 {len(kinds)} 类")
        check("全部成功时 ok 等于类别数", rep["ok"] == len(kinds), str(rep))
        check("没有 pending", rep.get("pending") == 0, str(rep))

        # -------------------------------------------------------------
        print("\n—— 单类失败不拖垮其它类 ——")
        R._CACHE.clear()
        dead = kinds[0]
        p = Probe(fail=(dead,))
        use(p)
        rep = R.refresh(force=True)
        check("失败的那类计入 failed", rep["failed"] == 1, str(rep))
        check("其它类照样成功", rep["ok"] == len(kinds) - 1, str(rep))
        check("失败的那类没写进缓存", dead not in R._CACHE, str(list(R._CACHE)))

        print("\n—— 抓到空 → 不覆盖旧缓存 ——")
        R._CACHE.clear()
        empty_kind = kinds[1]
        R._CACHE[empty_kind] = (time.time(), [{"title": "旧数据", "url": "https://x/old"}])
        p = Probe(empty=(empty_kind,))
        use(p)
        R.refresh(force=True)
        kept = (R._CACHE.get(empty_kind) or (0, []))[1]
        check("空结果不覆盖旧缓存（站点抽风不该清榜）",
              kept and kept[0]["title"] == "旧数据", str(kept))

        # -------------------------------------------------------------
        print("\n—— 撞总预算：收手必须报 pending，已完成的照样进缓存 ——")
        R._CACHE.clear()
        # 预算比"每类耗时 × 类别数 / 并发度"小得多 → 必然跑不完
        p = Probe(delay=0.4)
        use(p, budget=0.25)
        rep = R.refresh(force=True)
        print(f"     ok={rep['ok']} pending={rep.get('pending')} "
              f"pending_kinds={rep.get('pending_kinds')}")
        check("报出了 pending（没跑完的不许装作跑完了）",
              int(rep.get("pending") or 0) > 0, str(rep))
        check("pending 列了具体是哪几类",
              isinstance(rep.get("pending_kinds"), list)
              and len(rep["pending_kinds"]) == int(rep.get("pending") or -1),
              str(rep.get("pending_kinds")))
        check("还没跑完的类不许写进缓存（写进去就是假数据）",
              all(k not in R._CACHE for k in (rep.get("pending_kinds") or [])),
              str(list(R._CACHE)))
        check("一个都没跑完时缓存必须是空的（不是「反正有 ok 就算过」）",
              rep["ok"] == 0 and len(R._CACHE) == 0,
              f"ok={rep['ok']} cache={list(R._CACHE)}")

        # -------------------------------------------------------------
        print("\n—— 后台正在刷的类要跳过，不重复抓 ——")
        R._CACHE.clear()
        busy = kinds[0]
        R._BG.add(busy)
        try:
            p = Probe(delay=0.02)
            use(p)
            rep = R.refresh(force=True)
        finally:
            R._BG.discard(busy)
        check("后台正在刷的类别被跳过", busy not in p.calls,
              f"还是抓了：{busy}")
        check("跳过也计数（skipped 不是沉默）", rep["skipped"] >= 1, str(rep))

        print("\n" + "=" * 62)
        if fail_n == 0:
            print(f"通过 {ok_n} · 失败 0\n✓ 全部通过")
        else:
            print(f"通过 {ok_n} · 失败 {fail_n}\n✗ 有 {fail_n} 项没过")
        print("=" * 62)
        return 1 if fail_n else 0
    finally:
        R._fetch_one = orig_fetch              # noqa: SLF001
        R.RANKS_REFRESH_BUDGET = orig_budget   # noqa: SLF001
        import shutil
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
