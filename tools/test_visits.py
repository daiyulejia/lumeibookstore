# -*- coding: utf-8 -*-
"""访客记录（app/visits.py）的行为测试。

为什么值得单独测
----------------
它跑在**每个 API 请求**上（中间件里），是全局热路径：
  · 一旦它抛异常，所有接口一起 500 —— 所以它必须**永不抛**；
  · 一旦它写盘太频，磁盘会被打满 —— 所以落盘必须节流；
  · 一旦它把静态资源也记上，一次页面加载就能塞进几十条噪音 —— 所以必须过滤。

另外两个容易做错、且**错了不会报错**的点：
  1. **IP 脱敏**：写错了会把完整 IP 存下来（隐私问题）；
  2. **UV 口径**：指纹里带不带"日"决定了 UV 是"日活"还是"历史总人数"，
     这个差异在代码里只有一个字符，但语义差得很远。

照 test_registry.py 的做法：导入期改环境变量，全程不碰生产库。

用法：python tools/test_visits.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMPDIR = Path(tempfile.mkdtemp(prefix="novel-visits-test-"))
os.environ["NOVEL_VISITS"] = str(_TMPDIR / "visits.json")

from app import visits as V  # noqa: E402

PROD_DB = ROOT / "cache" / "visits.json"
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
    return json.loads(V._DB.read_text(encoding="utf-8"))


def main() -> int:
    global _prod_before
    print(f"\n临时库：{V._DB}")

    if PROD_DB.exists():
        _prod_before = PROD_DB.read_bytes()

    try:
        print("\n—— 1. IP 脱敏（隐私红线）——")
        check("IPv4 只留前三段", V._mask_ip("203.0.113.45") == "203.0.113.*",
              V._mask_ip("203.0.113.45"))
        check("IPv6 只留前两组", V._mask_ip("2001:db8::1") == "2001:db8:*",
              V._mask_ip("2001:db8::1"))
        check("空 IP 不崩", V._mask_ip("") == "?")
        # 关键：完整 IP 绝不能出现在落盘里
        V.record("/api/search", "203.0.113.45", "Mozilla/5.0 Chrome/120", 12.0, 200)
        V._save(force=True)
        raw = V._DB.read_text(encoding="utf-8")
        check("落盘里搜不到完整 IP", "203.0.113.45" not in raw,
              "完整 IP 泄漏进了落盘文件！")

        print("\n—— 2. UA 压成大类 ——")
        check("Chrome/Windows", V._ua_family(
            "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/120.0 Safari/537.36")
            == "Chrome/Windows", V._ua_family("Mozilla/5.0 (Windows NT 10.0) Chrome/120.0"))
        check("Safari/iPhone", V._ua_family(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604.1") == "Safari/iOS",
            V._ua_family("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604.1"))
        check("curl 归到 Bot/CLI", V._ua_family("curl/8.4.0") == "Bot/CLI",
              V._ua_family("curl/8.4.0"))
        check("空 UA 不崩", V._ua_family("") == "?")

        print("\n—— 3. 过滤：静态资源 / 4xx 探测 / 自身接口 ——")
        V.clear()
        V.record("/static/js/main.js", "1.1.1.1", "Chrome", 1.0, 200, is_api=False)
        check("静态资源不记（is_api=False）", V.stats()["pv_total"] == 0)

        V.record("/static/x.css", "1.1.1.1", "Chrome", 1.0, 200, is_api=True)
        check("静态前缀即使 is_api 也不记", V.stats()["pv_total"] == 0)

        V.record("/api/search", "1.1.1.1", "Chrome", 5.0, 404, is_api=True)
        check("4xx 探测不抬高访问量", V.stats()["pv_total"] == 0)

        # ⚠ 这条最重要：/api/visits 自己不能被记 —— 否则"看统计"这个动作
        #   本身不断产生新访问，页面每刷一次数字就涨一次（自激）。
        V.record("/api/visits/stats", "1.1.1.1", "Chrome", 3.0, 200, is_api=True)
        check("自身 /api/visits 不记（防自激）", V.stats()["pv_total"] == 0)

        # /api/history 同理：搜索框**每次聚焦**都拉一次历史做下拉，
        # 纯界面装饰、不是"用户在访问内容"。不排掉的话 top_paths 会被它占满。
        V.record("/api/history/search", "1.1.1.1", "Chrome", 3.0, 200, is_api=True)
        V.record("/api/history/search/hot", "1.1.1.1", "Chrome", 3.0, 200, is_api=True)
        check("搜索历史查询不记（否则淹没真实行为）",
              V.stats()["pv_total"] == 0, f'pv={V.stats()["pv_total"]}')

        V.record("/api/search", "1.1.1.1", "Chrome", 5.0, 500, is_api=True)
        check("5xx 要记（那是真出事）", V.stats()["pv_total"] == 1)

        print("\n—— 3b. 机器轮询：进聚合、不进明细 ——")
        # 线上实测：一次看明细 30 条里 24 条是 /api/progress/{id}。
        # 那是下载进度条每秒一次的心跳（tasks.js 的 pollTask），一个 5 分钟
        # 的导出就是 300 次。它代表"真人在线"，所以 PV 要算；
        # 但它不该把"刚刚谁来过"刷成一屏下载进度，所以明细不能留。
        V.clear()
        for _ in range(30):
            V.record("/api/progress/abc123", "1.1.1.1", "Chrome", 4.0, 200)
        check("进度轮询 30 次 → 明细 0 条（不刷屏）",
              len(V.recent(50)) == 0, f"recent={len(V.recent(50))}")
        check("进度轮询 30 次 → PV 仍然是 30（真人确实在线）",
              V.stats()["pv_today"] == 30, str(V.stats()["pv_today"]))
        V.record("/api/progress/abc123", "1.1.1.1", "Chrome", 4.0, 200)
        _paths = [x["path"] for x in V.stats()["top_paths_today"]]
        check("进度轮询仍写在 paths 里（能看出有人在等下载）",
              any(p.startswith("/api/progress") for p in _paths), str(_paths))

        V.record("/api/health", "1.1.1.1", "Chrome", 4.0, 200)
        check("健康探测也不进明细（PV 会算）",
              len(V.recent(50)) == 0, f"recent={len(V.recent(50))}")

        V.record("/api/library", "1.1.1.1", "Chrome", 9.0, 200)
        check("真实页面请求仍然要进明细",
              len(V.recent(50)) == 1 and V.recent(50)[0]["path"] == "/api/library",
              str(V.recent(50)))
        check("进度轮询不会把真实请求挤掉（明细只有 1 条）",
              len(V.recent(50)) == 1, f"recent={len(V.recent(50))}")

        print("\n—— 4. PV / UV ——")
        V.clear()
        for _ in range(3):
            V.record("/api/search", "1.1.1.1", "Chrome/Win", 5.0, 200)
        st = V.stats()
        check("同设备访问 3 次 → PV=3", st["pv_today"] == 3, str(st["pv_today"]))
        check("同设备访问 3 次 → UV=1", st["uv_today"] == 1, str(st["uv_today"]))

        V.record("/api/search", "2.2.2.2", "Chrome/Win", 5.0, 200)
        st = V.stats()
        check("换 IP → UV=2", st["uv_today"] == 2, str(st["uv_today"]))
        check("换 IP → PV=4", st["pv_today"] == 4, str(st["pv_today"]))

        V.record("/api/health", "3.3.3.3", "Firefox/macOS", 2.0, 200)
        st = V.stats()
        check("第三个访客 → UV=3", st["uv_today"] == 3, str(st["uv_today"]))

        print("\n—— 5. UV 口径：指纹带『日』= 日活 ——")
        # ⚠ 这是本模块最容易写错的一处。指纹里 `day` 的有无决定语义：
        #   带 → 同一设备跨天算两个访客（日活）；不带 → 变成"历史总人数"。
        fp1 = V._fingerprint("2026-10-13", "1.1.1.*", "Chrome/Win")
        fp2 = V._fingerprint("2026-10-14", "1.1.1.*", "Chrome/Win")
        fp3 = V._fingerprint("2026-10-13", "1.1.1.*", "Chrome/Win")
        check("同设备跨天 → 不同指纹（这是日活口径）", fp1 != fp2)
        check("同设备同天 → 同指纹", fp1 == fp3)
        check("指纹很短（12 位，FS 友好）", len(fp1) == 12, str(len(fp1)))

        print("\n—— 6. 趋势与榜首路径 ——")
        V.clear()
        for _ in range(5):
            V.record("/api/search", "1.1.1.1", "Chrome", 5.0, 200)
        for _ in range(2):
            V.record("/api/library", "1.1.1.1", "Chrome", 5.0, 200)
        st = V.stats()
        top = st["top_paths_today"]
        check("榜首路径是 /api/search（访问最多）",
              top and top[0]["path"] == "/api/search" and top[0]["n"] == 5, str(top))
        check("趋势非空且含今天",
              any(t["day"] == st["today"] for t in st["trend"]), str(st["trend"]))
        check("趋势里的 pv 是整数",
              all(isinstance(t["pv"], int) for t in st["trend"]))

        print("\n—— 7. 明细：最近访问 + new 标记 ——")
        V.clear()
        V.record("/api/search", "9.9.9.9", "Chrome", 5.0, 200)
        V.record("/api/search", "9.9.9.9", "Chrome", 5.0, 200)
        r = V.recent(10)
        check("明细记了 2 条", len(r) == 2, str(len(r)))
        check("最近的在最前（时间倒序）", r[0]["ts"] >= r[1]["ts"])
        check("第一条 new=True（新访客）", r[1]["new"] is True, str(r[1]))
        check("第二条 new=False（老访客）", r[0]["new"] is False, str(r[0]))
        check("明细里也是脱敏 IP", all("ip" in x and x["ip"].endswith("*") for x in r))

        print("\n—— 8. 永不抛异常（中间件红线）——")
        # 用各种畸形输入猛砸，确认一个异常都不冒出来
        for bad in (
            ("/api/x", None, None, 0, 200),
            ("/api/x", "", "", 0, 200),
            ("/api/x", "not-an-ip", "x" * 5000, 0, 200),
            (None, "1.1.1.1", "UA", 0, 200),
        ):
            try:
                V.record(*bad)  # type: ignore[arg-type]
            except Exception as e:  # noqa: BLE001
                check(f"畸形输入不抛（{str(bad[0])[:12]}）", False,
                      f"{type(e).__name__}: {e}")
                break
        else:
            check("畸形输入全部吞掉，一个异常都没冒", True)

        print("\n—— 9. 损坏文件：当空库继续跑 ——")
        V._DB.write_text("]]] 不是 json", encoding="utf-8")
        V._loaded = False
        V._data["days"] = {}
        V._data["recent"] = []
        V._data["first_seen"] = 0
        try:
            got = V.stats()
            check("坏文件不抛异常", True)
            check("坏文件读成空统计", got["pv_total"] == 0, str(got["pv_total"]))
        except Exception as e:  # noqa: BLE001
            check("坏文件不抛异常", False, f"{type(e).__name__}: {e}")
        V.record("/api/search", "1.1.1.1", "Chrome", 5.0, 200)
        check("坏文件之后还能记", V.stats()["pv_total"] >= 1)

        print("\n—— 9b. 自愈：历史噪音在读取时被清掉 ——")
        # 背景：写入端过滤是后来才加的，库里已经躺着一批 /api/progress 明细。
        # 不清的话它们会一直占着「最近来过」的头部，直到被新访问顶出 200 条上限。
        legacy = {
            "version": 1,
            "days": {},
            "recent": [
                {"ts": 100, "path": "/api/progress/aaa", "ip": "1.1.1.*",
                 "ua": "Chrome", "ms": 3, "code": 200, "new": False},
                {"ts": 99, "path": "/api/library", "ip": "1.1.1.*",
                 "ua": "Chrome", "ms": 9, "code": 200, "new": False},
                {"ts": 98, "path": "/api/health", "ip": "1.1.1.*",
                 "ua": "Chrome", "ms": 2, "code": 200, "new": False},
                {"ts": 97, "path": "/api/progress/bbb", "ip": "1.1.1.*",
                 "ua": "Chrome", "ms": 3, "code": 200, "new": False},
                {"ts": 96, "path": "/api/search", "ip": "1.1.1.*",
                 "ua": "Chrome", "ms": 40, "code": 200, "new": False},
            ],
            "first_seen": 90,
        }
        V._DB.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        V._loaded = False
        rows = V.recent(50)
        paths = [r["path"] for r in rows]
        check("自愈后历史进度噪音没了",
              not any(p.startswith(("/api/progress", "/api/health")) for p in paths),
              str(paths))
        check("自愈不误删真实访问（library + search 都还在）",
              "/api/library" in paths and "/api/search" in paths, str(paths))
        check("自愈后条数 = 真实条数 2", len(rows) == 2, str(len(rows)))
        check("自愈保持原有顺序（新的在前）",
              paths[:2] == ["/api/library", "/api/search"], str(paths))

        print("\n—— 10. 生产库没被碰过 ——")
        if _prod_before is not None:
            now = PROD_DB.read_bytes() if PROD_DB.exists() else None
            check("生产库内容一字未改", now == _prod_before)
        else:
            check("生产库本来就不存在（也没被创建）", not PROD_DB.exists())

    finally:
        import shutil

        shutil.rmtree(_TMPDIR, ignore_errors=True)

    print("\n" + "=" * 62)
    print(f"通过 {ok_n} · 失败 {fail_n}")
    print("=" * 62)
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
