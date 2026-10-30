"""逐站探针：拿一份**线上注册表副本**把每个可搜站的真机产出打出来。

为什么要有这个（2026-10-30）：
  线上 `search.done` 只给「候选=0」这一个总数，而"22 个站里谁吐了东西、
  谁吐了却被过滤器吃掉、谁压根没答话"三件事在总数里长得一模一样。
  复盘时只能靠这个脚本去问。

用法（**必须**用 venv 的 python，且要绕开代理）：
    set NOVEL_REGISTRY=cache/registry_live.probe.json   # 副本，别写线上那份
    .venv/Scripts/python.exe tools/_daily_probe_sites.py 我的阿勒泰 乡土中国

⚠ 注册表副本一定要用**可写副本**：`_search_one` 会回写 search_hit/shape，
  直接指向 `cache/registry_live.json` 会把线上副本改脏。
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

for _k in list(os.environ):
    if "proxy" in _k.lower():
        os.environ.pop(_k, None)

from app import registry  # noqa: E402
from app.relevance import kw_terms  # noqa: E402
from app.sources import registry_source as rs  # noqa: E402


def probe(host: str, meta: dict, keyword: str) -> dict:
    """只跑抓取 + 抽链接 + 过滤，不改线上任何东西（写的是 NOVEL_REGISTRY 副本）。"""
    try:
        out = rs.RegistrySource()._search_one(host, meta, keyword)
        return {"host": host, "kept": [b.title for b in out], "err": ""}
    except Exception as e:  # noqa: BLE001
        return {"host": host, "kept": [], "err": f"{type(e).__name__}: {e}"}


def main(argv: list[str]) -> int:
    kws = argv[1:] or ["我的阿勒泰"]
    sites = registry.searchable_sites()
    print(f"可搜源 {len(sites)} 个｜注册表={registry._DB}")
    for kw in kws:
        print("=" * 70)
        print(f"关键词《{kw}》 词表={kw_terms(kw)}")
        with ThreadPoolExecutor(max_workers=24) as pool:
            rows = list(pool.map(
                lambda kv: probe(kv[0], kv[1], kw), sites.items()))
        rows.sort(key=lambda r: (-len(r["kept"]), r["host"]))
        hit = 0
        for r in rows:
            if r["kept"]:
                hit += 1
            mark = "✓" if r["kept"] else "·"
            print(f"  {mark} {r['host']:<30} kept={len(r['kept'])} "
                  f"{r['kept'][:3] if r['kept'] else ''} {r['err'][:60]}")
        print(f"  → 有效站 {hit}/{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
