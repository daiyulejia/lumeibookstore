"""榜单「过期缓存兜底」回归测试（纯逻辑，不联网）。

为什么必须有它
--------------
榜单数据来自第三方站（384g.com / luoxiaks.net），**会被限流**。当缓存
过了 30 分钟 TTL、而这一轮抓取又失败（返回空）时，`get_rank` 曾经直接
返回空列表 —— 用户点开「总推荐榜」看到一片空白，而 cache/ranks.json 里
其实躺着 20 条旧榜。

这类 bug 和「联网兜底被永久跳过」是同一种病：
  · **不报错**、不抛异常、日志里看不出异常
  · 只表现成「那个标签是空的」，看起来像"这站本来就没数据"
所以人工回归必漏，只有把它钉成断言才守得住。

线上实例：384g 与 luoxiaks 双双进入冷却 → 6 个标签里 4 个空白。
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import ranks  # noqa: E402

# ⚠ 第一件事：把落盘路径挪到临时目录。
#   不这么做的话，第 4 组用例的 _save_to_disk() 会**写进真实的
#   cache/ranks.json**，把线上缓存冲掉 —— 测试污染数据的经典踩法。
_TMP = Path(tempfile.mkdtemp(prefix="ranks_stale_"))
ranks._DB = _TMP / "ranks.json"        # 真实缓存绝不能被碰

PASS = 0
FAIL = 0
FAILS: list[str] = []


def check(label: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {label}")
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  ✗ {label} {extra}")


def reset(cached: dict | None = None) -> None:
    """把模块状态清成"刚启动、有/没有缓存"的样子。"""
    ranks._CACHE.clear()
    ranks._inflight.clear()
    ranks._loaded = True          # 阻止 _load_from_disk 去读临时文件
    if cached:
        ranks._CACHE.update(cached)


_OLD = time.time() - ranks._TTL - 120      # 明确过期
_FRESH = time.time() - 60                  # 明确新鲜
_ITEMS = [{"title": f"旧榜第{i}本", "url": f"/old/{i}"} for i in range(20)]
_NEW = [{"title": "新榜第1本", "url": "/new/1"}]


def main() -> int:
    print("=" * 66)
    print("榜单过期缓存兜底 —— 抓不到时不能给空白页")
    print("=" * 66)

    print("\n── 1. 缓存过期 + 抓取失败（被限流）→ 必须回退旧缓存 ────────────")
    # 这是本次事故的核心场景。384g 冷却时走的就是这条路。
    reset({"allvote": (_OLD, _ITEMS)})
    ranks._fetch_one = lambda k: []
    got = ranks.get_rank("allvote")
    check("回退到那份过期缓存（不是空白页）", len(got) == 20,
          f"只拿到 {len(got)} 条 —— 用户会看到空标签")
    check("回退的确实是旧榜内容", bool(got) and got[0]["title"] == "旧榜第0本")

    print("\n── 2. 缓存新鲜 → 直接用缓存，不发起抓取（省一次联网）──────────")
    reset({"allvote": (_FRESH, _ITEMS)})
    calls: list[str] = []
    ranks._fetch_one = lambda k: (calls.append(k), [])[1]
    got = ranks.get_rank("allvote")
    check("返回缓存内容", len(got) == 20)
    check("没有发起抓取", not calls, f"居然抓了：{calls}")

    print("\n── 3. 无缓存 + 抓取失败 → 返回空，不能崩 ──────────────────────")
    reset()
    ranks._fetch_one = lambda k: []
    try:
        got = ranks.get_rank("allvote")
    except Exception as e:  # noqa: BLE001
        got = None
        check("不能抛异常", False, f"抛了 {type(e).__name__}: {e}")
    check("返回空列表", got == [], repr(got))

    print("\n── 4. 抓取成功 → 新数据覆盖缓存 ───────────────────────────────")
    reset({"allvote": (_OLD, _ITEMS)})
    ranks._fetch_one = lambda k: _NEW
    got = ranks.get_rank("allvote")
    check("用新数据（不是旧缓存）", len(got) == 1 and got[0]["title"] == "新榜第1本",
          repr(got[:2]))
    check("新数据已写进内存缓存",
          ranks._CACHE.get("allvote", (0, []))[1][0]["title"] == "新榜第1本")

    print("\n── 5. 未知 kind → 空（且不抓取）───────────────────────────────")
    reset()
    calls = []
    ranks._fetch_one = lambda k: (calls.append(k), [])[1]
    check("返回空", ranks.get_rank("no_such_kind") == [])
    check("没为不存在的 kind 发起抓取", not calls)

    print("\n" + "=" * 66)
    print(f"通过 {PASS} · 失败 {FAIL}")
    if FAIL:
        print("✗ 失败清单：")
        for f in FAILS:
            print(f"    {f}")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
