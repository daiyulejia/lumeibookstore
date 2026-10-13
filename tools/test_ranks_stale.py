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
    # ⚠ _BG 也要清 —— 它是"正在后台刷新的榜单集合"。
    #   不清的话上一组留下的 kind 会把下一组的去重逻辑挡住（假绿）。
    getattr(ranks, "_BG", set()).clear()
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

    print("\n── 1. 缓存过期 + 有旧数据 → 立刻回旧数据，抓取丢后台 ──────────")
    # ⚠ 这一组在引入 stale-while-revalidate 后**语义变了**：
    #   以前是"同步去抓，抓不到才回退旧缓存"（用户要等十几秒）；
    #   现在是"立刻回旧缓存，同时后台去抓"（用户 0 秒看到内容）。
    #   两者都保证"不给空白页"，但前者有可感知的等待。
    reset({"allvote": (_OLD, _ITEMS)})
    went_bg: list[str] = []
    ranks._fetch_one = lambda k: []
    # 把后台线程换掉，别真起线程 —— 这里要测的是"调用方拿到什么"，
    # 不是"线程有没有跑起来"（那是下面第 6 组的事）。
    orig_kick = ranks._kick_bg_refresh
    ranks._kick_bg_refresh = lambda k: went_bg.append(k)
    try:
        t0 = time.time()
        got = ranks.get_rank("allvote")
        dt = time.time() - t0
    finally:
        ranks._kick_bg_refresh = orig_kick
    check("回退到那份过期缓存（不是空白页）", len(got) == 20,
          f"只拿到 {len(got)} 条 —— 用户会看到空标签")
    check("回退的确实是旧榜内容", bool(got) and got[0]["title"] == "旧榜第0本")
    check("调用方**没有**被同步抓取阻塞（< 0.5s）", dt < 0.5,
          f"等了 {dt:.2f}s —— 用户会对着骨架干等")
    check("后台刷新被踢起来了", went_bg == ["allvote"], f"实际：{went_bg}")

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

    print("\n── 4. 无缓存 + 抓取成功 → 同步等，拿到新数据 ──────────────────")
    # 首次部署的场景：手上什么都没有，只能等。
    # ⚠ 这条**必须**保持同步语义 —— 改成"后台抓 + 立刻返回空"
    #   会让第一次访问的用户看到空榜单（比等十几秒更糟）。
    reset()
    ranks._fetch_one = lambda k: _NEW
    got = ranks.get_rank("allvote")
    check("拿到新数据", len(got) == 1 and got[0]["title"] == "新榜第1本",
          repr(got[:2]))
    check("新数据已写进内存缓存",
          ranks._CACHE.get("allvote", (0, []))[1][0]["title"] == "新榜第1本")

    print("\n── 6. 后台刷新真的会更新缓存（不是踢一脚就完事）─────────────")
    # 用真线程跑一遍完整路径：旧缓存 → 立刻返回 → 后台抓到新数据 → 缓存被换掉。
    # 这条钉的是 _kick_bg_refresh 里的**写入**那一段 —— 只有"踢起来了"
    # 不够，抓回来的东西必须真的落进缓存，否则用户永远停在旧榜上。
    reset({"allvote": (_OLD, _ITEMS)})
    ranks._fetch_one = lambda k: _NEW
    got = ranks.get_rank("allvote")
    check("第一次调用拿到旧缓存", bool(got) and got[0]["title"] == "旧榜第0本")
    # 等后台线程把新数据写进去（轮询，最多 3 秒）
    swapped = False
    for _ in range(60):
        time.sleep(0.05)
        cur_cache = ranks._CACHE.get("allvote", (0, []))[1]
        if cur_cache and cur_cache[0]["title"] == "新榜第1本":
            swapped = True
            break
    check("后台线程把新数据写进缓存了", swapped,
          "缓存一直没更新 —— 用户会永远停在旧榜上")

    print("\n── 7. 同一类榜单不会被同时刷两遍（后台去重）───────────────────")
    # 防的是"首页 3 个组件同时请求同一个榜单 → 起 3 个抓取线程"。
    # 判据：看**真正开出去的线程**里有几个是抓这一类榜单的。
    # 不去重的话会是 3 个；去重了应该是 1 个。
    reset({"allvote": (_OLD, _ITEMS)})
    ranks._fetch_one = lambda k: (time.sleep(0.25), _NEW)[1]
    orig_kick = ranks._kick_bg_refresh

    def spy(k: str) -> None:
        # 直接调真的那个 —— 它会做去重（_BG 集合）
        ranks._kick_bg_refresh = orig_kick
        try:
            orig_kick(k)
        finally:
            ranks._kick_bg_refresh = spy

    ranks._kick_bg_refresh = spy
    try:
        for _ in range(3):
            ranks.get_rank("allvote")
        # 数一下此刻还在跑的 ranks-bg-* 线程
        import threading as _th
        live = [t for t in _th.enumerate() if t.name.startswith("ranks-bg-")]
        time.sleep(0.6)
        after = [t for t in _th.enumerate() if t.name.startswith("ranks-bg-")]
    finally:
        ranks._kick_bg_refresh = orig_kick
    check("同一类榜单同时只有一个后台刷新线程", len(live) <= 1,
          f"同时有 {len(live)} 个 —— 去重失效（3 个组件会各起一个）")
    check("后台线程跑完后会自己清理", len(after) == 0,
          f"还剩 {len(after)} 个没退出")

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
