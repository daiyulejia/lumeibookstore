"""榜单持久化 + 定时调度的回归（纯离线，不联网）。

为什么这两件事要一起测
----------------------
它们是一体的：落盘是为了「重启后立刻有内容」，定时是为了「内容一直是新的」。
单独测任何一半都测不出真问题 —— 比如「落盘了但时间戳被重置」这种 bug，
只看落盘文件是好的，只有把「读回来的 age 必须还是老样子」断言上才抓得住。

所以这里**全部假造抓取**（monkeypatch `_fetch_one`），不碰网络：
  · 快、稳、不依赖站点心情
  · 能精确构造「抓到了」「抓到空」「抛异常」三种情况

覆盖面：
  A. 落盘 → 读回（含「时间戳不能重置」这个关键语义）
  B. 空结果不覆盖好缓存（落盘版也要成立）
  C. refresh(force=True/False) 的选择性
  D. 调度线程：真的会跑、能被叫醒、能干净停掉、异常不会把线程弄死
  E. 关掉开关就不启动
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ⚠ 必须在 import app.ranks 之前设：模块级就把 _DB 定死了。
_TMP = Path(tempfile.mkdtemp(prefix="nd-ranks-"))
os.environ["NOVEL_RANKS"] = str(_TMP / "ranks.json")
os.environ["NOVEL_SCHED"] = "0"          # 默认别让调度线程自己跑起来


def main() -> int:
    from app import ranks
    from app import sched

    fails: list[str] = []

    def check(label: str, cond: bool) -> None:
        print(f"  {'✓' if cond else '✗'} {label}")
        if not cond:
            fails.append(label)

    def fake_fetch(mapping):
        """把 _fetch_one 换成查表；表里没写的 kind 返回空。"""
        def _f(kind):
            v = mapping.get(kind, [])
            if isinstance(v, Exception):
                raise v
            return list(v)
        return _f

    def item(t: str) -> dict:
        return {"title": t, "author": "某人", "url": "", "source": "384g",
                "source_display": "新笔趣阁", "words": "1字", "updated": "2026-01-01",
                "status": "连载中", "kind": "allvisit"}

    # =====================================================================
    print("== A. 落盘 → 读回（时间戳不能重置）==")
    ranks.clear_cache()
    old_ts = time.time() - 600          # 假装 10 分钟前抓的
    ranks._CACHE["allvisit"] = (old_ts, [item("落盘书")])
    ranks._save_to_disk()
    check("落盘文件已生成", Path(os.environ["NOVEL_RANKS"]).exists())

    # 模拟重启：清内存、允许重新加载
    ranks._CACHE.clear()
    ranks._loaded = False
    ranks._load_from_disk()
    got = ranks._CACHE.get("allvisit")
    check("读回后条目还在", bool(got) and got[1][0]["title"] == "落盘书")
    check("⚠ 时间戳保持原样（不是「刚刚」）", bool(got) and abs(got[0] - old_ts) < 1.0)

    st = ranks.cache_status()
    age = st["kinds"]["allvisit"]["age"]
    check(f"体检报告里的 age 也是老的（{age}s，应≈600）", age is not None and age >= 590)
    check("该榜单仍算新鲜（600 < 1800 的 TTL）", st["kinds"]["allvisit"]["fresh"] is True)

    # 过期的情况：读回来就该是「不新鲜」，下次访问自然触发刷新
    ranks._CACHE.clear()
    ranks._loaded = False
    ranks._CACHE["allvisit"] = (time.time() - 99999, [item("老书")])
    ranks._save_to_disk()
    ranks._CACHE.clear()
    ranks._loaded = False
    ranks._load_from_disk()
    check("超 TTL 的缓存读回来标记为不新鲜",
          ranks.cache_status()["kinds"]["allvisit"]["fresh"] is False)

    # =====================================================================
    print()
    print("== B. 空结果不覆盖好缓存（落盘版也要成立）==")
    ranks.clear_cache()
    ranks._fetch_one = fake_fetch({"allvisit": [item("好书")]})
    ranks.get_rank("allvisit")
    check("先抓到一条", ranks._CACHE["allvisit"][1][0]["title"] == "好书")

    ranks._CACHE["allvisit"] = (0.0, ranks._CACHE["allvisit"][1])   # 强制过期
    ranks._fetch_one = fake_fetch({"allvisit": []})                 # 站点抽风返回空
    ranks.get_rank("allvisit")
    check("抓到空时旧数据还在（没被空列表冲掉）",
          ranks._CACHE["allvisit"][1][0]["title"] == "好书")

    # =====================================================================
    print()
    print("== C. refresh 的 force 语义 ==")
    ranks.clear_cache()
    calls: list[str] = []

    def counting_fetch(kind):
        calls.append(kind)
        return [item(f"{kind}-书")]

    ranks._fetch_one = counting_fetch
    rep = ranks.refresh(["allvisit", "allvote"], force=True)
    check(f"force=True 两类都抓了（{rep['ok']}）", rep["ok"] == 2 and rep["failed"] == 0)
    check("确实调用了两次抓取", sorted(calls) == ["allvisit", "allvote"])

    calls.clear()
    rep = ranks.refresh(["allvisit", "allvote"], force=False)
    check("force=False 且都新鲜 → 全跳过",
          rep["skipped"] == 2 and rep["ok"] == 0 and not calls)

    ranks._CACHE["allvisit"] = (0.0, ranks._CACHE["allvisit"][1])    # 弄过期一个
    calls.clear()
    rep = ranks.refresh(["allvisit", "allvote"], force=False)
    check("force=False 只补过期的那个", rep["ok"] == 1 and calls == ["allvisit"])

    # 抓取抛异常不能把 refresh 带崩
    ranks.clear_cache()
    ranks._fetch_one = fake_fetch({"allvisit": RuntimeError("站点炸了"),
                                   "allvote": [item("正常的")]})
    rep = ranks.refresh(["allvisit", "allvote"], force=True)
    check("一类抛异常，另一类照常成功", rep["ok"] == 1 and rep["failed"] == 1)

    # =====================================================================
    print()
    print("== D. 调度线程 ==")
    ranks.clear_cache()
    ticks: list[float] = []

    def tick_fetch(kind):
        ticks.append(time.time())
        return [item("定时书")]

    ranks._fetch_one = tick_fetch
    os.environ["NOVEL_SCHED"] = "1"
    os.environ["NOVEL_SCHED_FIRST_DELAY"] = "0.05"

    ok = sched.start(interval=0.4)
    check("调度线程起来了", ok is True)
    check("状态显示 running", sched.status()["running"] is True)

    deadline = time.time() + 6
    while time.time() < deadline and len(ticks) < 12:   # 6 类 × 2 轮
        time.sleep(0.1)
    check(f"自动跑过至少一轮（抓了 {len(ticks)} 次）", len(ticks) >= 6)
    check("一轮 = 全部 6 类", len(ticks) >= 6)

    before = len(ticks)
    sched.wake()                       # 手动叫醒，应立刻再来一轮
    deadline = time.time() + 4
    while time.time() < deadline and len(ticks) < before + 6:
        time.sleep(0.1)
    check(f"wake() 能催出下一轮（{before} → {len(ticks)}）", len(ticks) >= before + 6)

    st = sched.status()
    check("status 里有 runs 计数", st["runs"] >= 2)
    check("status 记录上次结果", st["last_ok"] is not None)

    sched.stop()
    time.sleep(0.3)
    check("stop() 之后线程停了", sched.status()["running"] is False)
    n_after_stop = len(ticks)
    time.sleep(0.8)
    check("停掉之后不再抓（真停了）", len(ticks) <= n_after_stop + 6)

    # 抓取抛异常，线程必须活着（不能一崩就死）
    print()
    print("== D2. 抓取一直失败，线程不能死 ==")
    def boom(kind):
        raise RuntimeError("永远失败")
    ranks._fetch_one = boom
    os.environ["NOVEL_SCHED_FIRST_DELAY"] = "0.05"
    sched.start(interval=0.3)
    time.sleep(1.2)
    check("一直失败但线程仍活着", sched.status()["running"] is True)
    check("错误被记进 last_error", bool(sched.status()["last_error"]))
    sched.stop()
    time.sleep(0.3)

    # =====================================================================
    print()
    print("== E. 开关 ==")
    os.environ["NOVEL_SCHED"] = "0"
    check("NOVEL_SCHED=0 时 start 返回 False", sched.start(interval=1) is False)
    check("status.enabled = False", sched.status()["enabled"] is False)
    os.environ["NOVEL_SCHED"] = "1"
    check("恢复后 enabled = True", sched.status()["enabled"] is True)
    sched.stop()

    print()
    if fails:
        print(f"✗ {len(fails)} 项失败：")
        for f in fails:
            print(f"    {f}")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
