"""批量适配 —— 把体检出来的存活站点跑一遍自动适配，能用的写进 sites.json。

用法：
    python tools/adapt_pool.py                    # 用 cache/pool_report.json 里存活的站
    python tools/adapt_pool.py site1.com site2.com
    python tools/adapt_pool.py --keyword 活着      # 换一本测试书

流程：
    tools/probe_pool.py 体检 → 本脚本适配 → 能用的自动落盘 → 重启服务生效

设计原则：
    **只保存真的跑通的**。适配器会端到端走一遍
    「搜索 → 目录 → 正文 → 内容质量校验」，任何一步不过就不落盘。
    宁可不加这个源，也不要加一个「看着能搜到、点进去抓不到正文」的源。
"""
from __future__ import annotations

import io
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.sources.adapter import adapt_sync, save_adapted  # noqa: E402
from app.sources.configured import ConfiguredSource  # noqa: E402

POOL_REPORT = ROOT / "cache" / "pool_report.json"


def load_alive() -> list[str]:
    if not POOL_REPORT.exists():
        print(f"没有 {POOL_REPORT}，先跑 tools/probe_pool.py")
        return []
    data = json.loads(POOL_REPORT.read_text(encoding="utf-8"))
    alive = data.get("alive", [])
    # 搜索可用的排前面（更可能适配成功）
    alive.sort(key=lambda r: (not r.get("search_ok"), r.get("ms") or 9999))
    return [r["url"] for r in alive]


def self_check(cfg: dict, keyword: str) -> tuple[bool, str]:
    """用生成的配置真跑一遍：搜索 → 目录 → 正文。

    这一步是「别显示可以下载最后假的」在自动适配上的对应物 ——
    适配器内部的校验只验了一本书的一个章节，这里再独立走一遍
    完整链路，确认 ConfiguredSource 拿着这份配置确实能用。
    """
    try:
        src = ConfiguredSource(cfg)
        hits = src.search(keyword)
        if not hits:
            return False, "搜索无结果"
        hit = hits[0]
        chapters = src.get_chapters(hit)
        if len(chapters) < 3:
            return False, f"只拿到 {len(chapters)} 章"
        idx = 1 if len(chapters) > 1 else 0
        text = src.fetch_chapter(chapters[idx])
        if len(text) < 200:
            return False, f"正文只抽到 {len(text)} 字"
        return True, f"《{hit.title}》{len(chapters)} 章，抽 {len(text)} 字"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:50]}"


def main() -> None:
    argv = sys.argv[1:]
    keyword = "斗破苍穹"
    if "--keyword" in argv:
        i = argv.index("--keyword")
        if i + 1 < len(argv):
            keyword = argv[i + 1]
            argv = argv[:i] + argv[i + 2 :]
    targets = [a for a in argv if not a.startswith("--")] or load_alive()

    print(f"待适配 {len(targets)} 个站，测试书目《{keyword}》\n")
    ok_list: list[dict] = []

    def work(u: str):
        t0 = time.time()
        try:
            ad = adapt_sync(u, keyword)
        except Exception as e:  # noqa: BLE001
            return u, None, f"崩溃 {type(e).__name__}: {str(e)[:40]}", 0
        return u, ad, "", time.time() - t0

    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(work, u): u for u in targets}
        for i, fut in enumerate(as_completed(futs), 1):
            u, ad, err, dt = fut.result()
            if err or ad is None:
                print(f"[{i:3d}/{len(targets)}] ✗ {u:<34} {err}")
                continue
            if not ad.ok:
                last = ad.steps[-1][2] if ad.steps else ""
                print(f"[{i:3d}/{len(targets)}] ✗ {u:<34} {ad.steps[-1][0] if ad.steps else ''}: {last[:52]}")
                continue
            good, detail = self_check(ad.config, keyword)
            if not good:
                print(f"[{i:3d}/{len(targets)}] ⚠ {u:<34} 自检不过：{detail}")
                continue
            print(f"[{i:3d}/{len(targets)}] ✓ {u:<34} {detail}  ({dt:.0f}s)")
            ok_list.append(ad.config)

    for cfg in ok_list:
        save_adapted(cfg)
    print(f"\n{'='*74}")
    print(f"适配成功 {len(ok_list)} / {len(targets)}，已写入 sites.json")
    for cfg in ok_list:
        print(f"   {cfg['display']:<18} {cfg['base_url']}")


if __name__ == "__main__":
    main()
