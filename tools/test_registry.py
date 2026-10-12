# -*- coding: utf-8 -*-
"""来源库（app/registry.py）的行为测试。

为什么值得单独立一个测试：来源库是**进程内缓存 + 退出时落盘**的，
而落盘那一步一旦写错，用户攒了几个月的站点会在一瞬间被清空 ——
这种 bug 平时看不出来，出事就是不可逆的数据丢失。

盯四件事：
  1. 落盘时不能把「别的进程写进去的数据」抹掉
  2. 删除要真的删掉（不能因为合并的并集语义又冒出来）
  3. 健康筛选认得准
  4. **测试自己不许碰生产库**（这条是被真事故逼出来的，见下）

关于第 4 条
-----------
这份测试最早是直接改 `cache/registry.json` 的：先备份、测完写回去。
看着没问题，实际上 `prune(only_dead=False)` 会把真库里的每个键**记进墓碑**
并立刻落盘 —— 备份只救回了文件，救不回已经写进去的墓碑语义；
叠加上「进程退出时 atexit 又 flush 一次」，
一次测试就能把攒好的来源库洗成只剩测试夹具。

所以现在：
  · 测试一开始就把 `registry._DB` 指到临时目录，**全程不碰生产库**
  · 生产库路径只读一次，用「它有没有被改动」当断言

用法：python tools/test_registry.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 双保险：直接在导入期就把库文件指到临时位置。
# （registry 支持 NOVEL_REGISTRY 环境变量，就是为这个场景加的）
_TMPDIR = Path(tempfile.mkdtemp(prefix="novel-registry-test-"))
os.environ["NOVEL_REGISTRY"] = str(_TMPDIR / "registry.json")

from app import registry as R  # noqa: E402

PROD_DB = ROOT / "cache" / "registry.json"
_prod_before: bytes | None = None

ok_n = 0
fail_n = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global ok_n, fail_n
    if cond:
        ok_n += 1
        print(f"  ✓ {name}")
    else:
        fail_n += 1
        print(f"  ✗ {name} {extra}")


def disk() -> dict:
    return json.loads(R._DB.read_text(encoding="utf-8"))


def main() -> int:
    global _prod_before
    print(f"\n临时库：{R._DB}")

    try:
        print("\n—— 基础读写 ——")
        R.note_site("a.com", ok=True)
        R.note_book("http://a.com/1", title="甲", host="a.com", chapters=10)
        R.flush()
        d = disk()
        check("写入后能落盘", "a.com" in d["sites"] and "http://a.com/1" in d["books"])
        check("成功/失败计数记对了", d["sites"]["a.com"]["ok"] == 1
              and "fail" not in d["sites"]["a.com"], str(d["sites"]["a.com"]))

        print("\n—— 多进程：不能抹掉别人写的 ——")
        d["sites"]["b.com"] = {"host": "b.com", "ok": 7, "updated": int(time.time()) + 50}
        d["books"]["http://b.com/2"] = {"title": "乙", "host": "b.com",
                                        "chapters": 20, "last_check": int(time.time()) + 50}
        R._DB.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        R.note_site("a.com", ok=True)
        R._save(force=True)
        d2 = disk()
        check("别的进程写的站点保住了", "b.com" in d2["sites"])
        check("别的进程写的书保住了", "http://b.com/2" in d2["books"])
        check("自己写的那条还在", "a.com" in d2["sites"])
        check("同键取新的那份", int(d2["sites"]["b.com"]["ok"]) == 7)

        print("\n—— 删除语义 ——")
        R.forget_site("b.com")
        R.forget_book("http://b.com/2")
        R.flush()
        d3 = disk()
        check("删掉的站点没被并集捞回来", "b.com" not in d3["sites"])
        check("删掉的书没被并集捞回来", "http://b.com/2" not in d3["books"])

        print("\n—— 健康判定 ——")
        R.note_site("flaky.com", ok=True)
        check("成功过的站算健康", R.is_healthy(R.known_site("flaky.com")))
        for _ in range(3):
            R.note_site("dead.com", ok=False)
        check("连续失败 3 次的站算失效", not R.is_healthy(R.known_site("dead.com")))
        check("失效站被 healthy_sites 排除", "dead.com" not in R.healthy_sites())
        r = R.prune(only_dead=True)
        check("清失效只清失效的", r["sites_removed"] == 1 and "flaky.com" in R.sites(),
              str(r))

        print("\n—— 查书 ——")
        R.note_book("http://x.com/book/1", title="药鼎仙途", author="寒香寂寞",
                    host="x.com", chapters=4000)
        R.note_book("http://x.com/book/2", title="药鼎仙途外传", host="x.com", chapters=50)
        R.note_book("http://x.com/book/3", title="完全无关", host="x.com", chapters=5)
        hits = [b["title"] for b in R.find_books("药鼎仙途")]
        check("精确命中排最前", hits and hits[0] == "药鼎仙途", str(hits))
        check("包含关键词的也能找到", "药鼎仙途外传" in hits, str(hits))
        check("无关的不返回", "完全无关" not in hits, str(hits))
        check("带《》也认", bool(R.find_books("《药鼎仙途》")))
        check("不存在的书返回空", R.find_books("压根没有这本书") == [])

        print("\n—— 护栏：全清要显式确认 ——")
        # 先落一次盘：缩水护栏是拿「盘上那份」当基准的，
        # 上面这些 note_* 都还压在内存里（落盘有 1 秒节流）
        R.flush()
        check("库里有足够条目，护栏才有意义", R._count(R._read_disk()) >= 5,
              str(R._count(R._read_disk())))
        try:
            R.prune(only_dead=False)
            check("不传 confirm 会被拒绝", False, "居然没报错")
        except ValueError as e:
            check("不传 confirm 会被拒绝", "confirm" in str(e), str(e))
        check("被拒之后数据还在", len(R.sites()) > 0 and len(R.books()) > 0,
              f"sites={len(R.sites())} books={len(R.books())}")
        n = R.prune(only_dead=False, confirm=True)
        check("传了 confirm 才真的清空", not R.sites() and not R.books(), str(n))
        bak = R._DB.with_name(R._DB.stem + ".bak.json")
        check("缩水护栏留了备份", bak.exists(), str(bak))

        print("\n—— 生产库没被碰过 ——")
        now = PROD_DB.read_bytes() if PROD_DB.exists() else None
        check("生产库内容一字未改", now == _prod_before,
              f"size {len(_prod_before or b'')} -> {len(now or b'')}")

        print(f"\n{'✅ 全部通过' if not fail_n else '❌ 有失败'}（{ok_n} 通过 / {fail_n} 失败）")
        return 1 if fail_n else 0
    finally:
        shutil.rmtree(_TMPDIR, ignore_errors=True)


if __name__ == "__main__":
    _prod_before = PROD_DB.read_bytes() if PROD_DB.exists() else None
    sys.exit(main())
