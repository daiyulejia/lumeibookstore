"""`discovery.discover()` 不许被「学站」阻塞 —— 结果就绪必须立刻交付。

为什么值得一条专门测试
----------------------
这不是性能优化，是**正确性**。线上真实事故（2026-10-14，用户报「这本书找不到」）：

    本地 7 个来源全部零覆盖
    → 引擎在 2.5s 抢跑「联网发现」（墙钟硬上限只有 20s）
    → 联网其实**已经找到**了（实测命中 zxs8.net，《我们猫猫不能听这些》）
    → 但 `discover()` 拿到结果后不返回，先**同步**把「学站」跑完
      （`learn_sites`，预算 14s）
    → 函数 17.2s 才 return，而 20s 就到点了
    → 用户看到「没找到」

也就是说：**结果在 3.2 秒就绪，交付却在 17.2 秒** —— 白丢的 14 秒直接把
整轮搜索顶到收手线上。而「学站」是给**下一次**搜索用的，与本次结果无关。

这个 bug 的阴险之处：**它不报错**。日志里全是 INFO，界面上是「没找到」，
重跑一次又可能好（网络快的时候刚好赶上）—— 典型的"偶发"外貌。

本测试的判据
------------
它不测耗时绝对值（那会随机器快慢漂），而是测**两个量之间的先后关系**：

    「结果已交付」必须早于「学站跑完」

做法：把联网部分（搜索/核实/学站）全部换成**确定性 stub**，其中
`learn_sites` 故意睡 `LEARN_SEC` 秒。然后
  · 默认调用（learn_async=True）→ 必须在远小于 LEARN_SEC 内返回；
  · 反证：`learn_async=False`（= 改动前的同步行为）→ 必须真的等到 LEARN_SEC。

反证是**内建的**：第二种调用就是"把修复拆掉"的样子。它要是也不慢，
说明这测试没牙。跑完还要人工再反证一次（把默认值翻回同步，看它是否变红）。

用法： python tools/test_discover_async.py
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ⚠ 必须**在 import app.registry 之前**设好：来源库会写 cache/registry.json，
#   不隔离的话本测试的假站点会污染真实来源库（踩过的同类坑见 history/visits）。
_TMP = pathlib.Path(tempfile.mkdtemp(prefix="nd-discover-"))
os.environ["NOVEL_REGISTRY"] = str(_TMP / "registry.json")

from app import discovery  # noqa: E402

OK = 0
BAD = 0
LEARN_SEC = 2.5

#: 记录「学站」是否真跑过、以及它拿到的 host
LEARN_RAN: list[list[str]] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global OK, BAD
    if cond:
        OK += 1
        print(f"  ✓ {name}")
    else:
        BAD += 1
        print(f"  ✗ {name}  {extra}")


def _fake_find(keyword, *, limit=14, per_host=2, log=None):
    return [{"url": "https://fake.test/book/1/", "host": "fake.test",
             "title": "假书", "engine": "stub"}]


def _fake_page_of(url, *, force: bool = False):
    return {
        "kind": "toc", "url": url, "final_url": url, "host": "fake.test",
        "site_name": "假站", "title": "假书", "author": "某人", "intro": "",
        "toc": [{"title": f"第{i}章", "url": f"{url}{i}.html"} for i in range(1, 21)],
        "quality": 1.0, "size": 9999,
    }


def _fake_learn(hosts, *, keyword="", log=None):
    time.sleep(LEARN_SEC)
    LEARN_RAN.append(list(hosts))
    return {"learned": 1, "failed": 0, "skipped": 0}


def main() -> int:
    print("── 0. 装 stub（联网部分全部确定化）──")
    discovery.websearch.find_book_pages = _fake_find
    discovery.page_of = _fake_page_of
    discovery.learn_sites = _fake_learn
    check("stub 已生效", discovery.learn_sites is _fake_learn)

    print("\n── 1. 默认：结果就绪即返回，不等学站 ──")
    LEARN_RAN.clear()
    t0 = time.time()
    res = discovery.discover("假书")
    async_ms = (time.time() - t0) * 1000
    check(f"返回耗时 {async_ms:.0f}ms < 学站耗时 {LEARN_SEC*1000:.0f}ms 的一半"
          f"（说明没等学站）",
          async_ms < LEARN_SEC * 1000 * 0.5,
          f"实际 {async_ms:.0f}ms —— 像是等了学站")
    check("结果**没有**因为不等学站而丢失", len(res) == 1,
          f"拿到 {len(res)} 条")
    if res:
        check("结果内容正确（标题/来源/章节数）",
              res[0].title == "假书" and res[0].source == "web"
              and res[0].chapter_count == 20,
              f"{res[0].title} / {res[0].source} / {res[0].chapter_count}")

    print("\n── 2. 学站确实被丢到后台跑（不是被吞掉）──")
    check("返回时学站还没跑完（真后台）", LEARN_RAN == [],
          f"返回时已跑完：{LEARN_RAN}")
    discovery.wait_learn(timeout=LEARN_SEC + 10)
    check("等一会儿之后学站跑过了、host 正确",
          LEARN_RAN and LEARN_RAN[-1] == ["fake.test"], f"{LEARN_RAN}")

    print("\n── 3. 反证：同步版（= 修复前的行为）必须真的会等 ──")
    LEARN_RAN.clear()
    t0 = time.time()
    res2 = discovery.discover("假书", learn_async=False)
    sync_ms = (time.time() - t0) * 1000
    check(f"learn_async=False 时确实等到学站（≥{LEARN_SEC*1000*0.9:.0f}ms）",
          sync_ms >= LEARN_SEC * 1000 * 0.9, f"实际 {sync_ms:.0f}ms")
    check("同步版结果同样正确", len(res2) == 1)
    check("**两者耗时差 > 2s** —— 证明「等不等学站」是真实差异，"
          "而不是两条路都很快（否则本测试无牙）",
          (sync_ms - async_ms) > 2000, f"异步 {async_ms:.0f}ms vs 同步 {sync_ms:.0f}ms")

    print("\n" + "=" * 62)
    print(f"通过 {OK} · 失败 {BAD}")
    print("=" * 62)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
