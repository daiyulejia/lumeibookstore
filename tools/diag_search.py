"""搜索慢的根因诊断：把一次搜索拆成阶段，看时间到底花在哪。

用户反馈「一直显示正在从七个来源里找 XXX，很慢」。这个脚本不猜，
直接量：每个来源各花多久、探测阶段多久、抽样阶段多久、慢源是谁。

用法：
  python tools/diag_search.py 三体
  python tools/diag_search.py 活着 --repeat 3
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kw", nargs="?", default="三体")
    ap.add_argument("--repeat", type=int, default=1)
    a = ap.parse_args()

    from app.engine import Engine

    eng = Engine()
    targets = [s for s in eng._sources if not getattr(s, "lazy", False)]
    print(f"=== 搜索「{a.kw}」 来源 {len(targets)} 个 ===\n")

    all_runs: list[dict] = []
    for r in range(a.repeat):
        print(f"--- 第 {r+1} 轮 ---")
        timings: dict[str, float] = {}
        counts: dict[str, int] = {}
        errs: dict[str, str] = {}

        def run_one(src):
            t = time.time()
            try:
                items = src.search(a.kw) or []
                return src.name, items, time.time() - t, ""
            except Exception as e:  # noqa: BLE001
                return src.name, [], time.time() - t, f"{type(e).__name__}: {e}"

        # 只测「搜索」阶段（不含探测/抽样），这是第一段耗时
        t_search = time.time()
        raw = []
        with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
            futs = {pool.submit(run_one, s): s for s in targets}
            for f in as_completed(futs):
                name, items, dt, err = f.result()
                timings[name] = dt
                counts[name] = len(items)
                if err:
                    errs[name] = err
                raw.extend(items)
        search_total = time.time() - t_search

        # 关键指标：所有源里最慢的那个 = 用户实际等待时间的下界
        slowest = max(timings.items(), key=lambda x: x[1]) if timings else ("-", 0)
        print(f"  搜索阶段合计（=最慢源）: {search_total:6.2f}s")
        print(f"  原始候选: {len(raw)} 条\n")
        for n, dt in sorted(timings.items(), key=lambda x: -x[1]):
            flag = "  ← 拖后腿" if dt == slowest[1] and dt > 2.0 else ""
            e = f"  [{errs[n]}]" if n in errs else ""
            print(f"    {dt:6.2f}s  {counts[n]:>3} 条  {n}{e}{flag}")

        # 再测完整链路（含探测 + 抽样），看总耗时
        t_full = time.time()
        stats: dict = {}
        eng.search(a.kw, stats=stats, probe=True, sample=True, discover=False)
        full_total = time.time() - t_full
        print(f"\n  完整链路（搜索+探测+抽样）: {full_total:6.2f}s")
        print(f"  stats: {stats}\n")

        all_runs.append({"search": search_total, "full": full_total, "slowest": slowest})

    if len(all_runs) > 1:
        print("=== 汇总 ===")
        print(f"  搜索阶段中位: {statistics.median(r['search'] for r in all_runs):.2f}s")
        print(f"  完整链路中位: {statistics.median(r['full'] for r in all_runs):.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
