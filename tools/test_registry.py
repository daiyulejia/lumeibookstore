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
import re
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

        # -----------------------------------------------------------------
        print("\n—— 「目录可能不全」的备注（三态语义）——")
        # 为什么盯这件事：来源库面板会把这句和「12 章」并排显示。
        # 单看一个「12 章」和「这本书就是 12 章」长得一模一样，
        # 而实测那本《我们猫猫不能听这些》全书 119 章、第一页只有 12 章 ——
        # 用户按数字判断要不要下，下完才发现是零头。
        U = "http://y.com/book/1"
        warn = "这份目录可能不完整，只含部分章节"
        R.note_book(U, title="大部头", host="y.com", chapters=12, note=warn)
        check("写了 note 就能读到", R.known_book(U).get("note") == warn,
              str(R.known_book(U)))
        # ① 缺省（None）= 「这次没看目录」→ 不能擦掉别人的结论
        R.note_book(U, host="y.com", ok=True)
        check("不传 note 的调用不会擦掉已有警告",
              R.known_book(U).get("note") == warn, str(R.known_book(U)))
        # ② 落盘 + 合并之后警告还在（`_merge` 会拿盘上那份补键）
        R.flush()
        check("警告能落盘", (disk()["books"].get(U) or {}).get("note") == warn)
        R._cache = None                   # 丢掉内存缓存 → 下次访问从盘上重读
        check("从盘上重读后警告还在",
              R.known_book(U).get("note") == warn, str(R.known_book(U)))
        # ③ 传空串 = 「这次查过，目录是完整的」→ 警告必须消失，**且撤得掉**
        R.note_book(U, host="y.com", chapters=119, note="")
        check("目录变全后警告立刻消失（传空串清掉）", not R.known_book(U).get("note"),
              str(R.known_book(U)))
        check("章节数同时更新成新的", R.known_book(U).get("chapters") == 119,
              str(R.known_book(U).get("chapters")))
        R.flush()
        # ⚠ 这一条才是关键：落盘走 `_merge()`，同一键是「先取盘上那份、
        #   再用内存那份逐键覆盖」，**内存那份没有这个键时不会覆盖**。
        #   所以清警告如果写成 `pop("note")`，合并时它就从盘上**复活**了 ——
        #   界面上表现为"警告永远撤不掉"（连目录真修好了也撤不掉）。
        check("清掉的警告在落盘/合并后不会复活",
              not (disk()["books"].get(U) or {}).get("note"),
              str((disk()["books"].get(U) or {}).get("note")))
        # ④ 失败记账（压根没看目录）不许凭空造出警告
        R.note_book("http://y.com/book/2", host="y.com", ok=False)
        check("失败记账不会凭空写 note",
              not R.known_book("http://y.com/book/2").get("note"))
        # ⑤ 没传过 note 的书，字段是空的（不能默认成"不全"）
        check("没结论的书没有 note", not R.known_book("http://x.com/book/1").get("note"))

        # -----------------------------------------------------------------
        print("\n—— 接线：发现流程必须真的把「目录结论」交给来源库 ——")
        # 上面验的是 `note_book` **自己**对不对。可它再正确也没用：
        # 只要**调用方**忘了传 `note`，界面上照样永远看不到警告 ——
        # 而且同样是静默的（不会报错，只会少一句话）。
        # 这里做源码级接线检查（同 tools/test_ranks.py 的前端接线检查），
        # 配套 `tools/mutate.py` 的 discovery 突变：把参数删掉必须报红。
        disc_path = ROOT / "app" / "discovery.py"
        disc = disc_path.read_text(encoding="utf-8")
        # 发现（_verify_candidate）与体检（_check_book）**两处都要交**：
        # 只交一处的话，另一条路径下的书永远挂着过期的警告（或永远没有）。
        wires = re.findall(r'note\s*=\s*str\(\s*data\.get\(\s*"chapter_note"\s*\)[^\n]*',
                           disc)
        check("发现 / 体检两处都交出了目录结论", len(wires) == 2,
              f"找到 {len(wires)} 处：{[w[:40] for w in wires]}")
        # 结论还得**挂到返回结果上**才传得到接口和界面（r.chapter_note）。
        check("目录结论会挂到返回结果上（界面才拿得到）",
              bool(re.search(r"r\.chapter_note\s*=\s*str\(", disc)))

        # -----------------------------------------------------------------
        print("\n—— 「可搜源」全项目只有一个判据 ——")
        # 线上实测踩到的口径漂移：`stats()["sites_searchable"]` 数的是
        # 「健康 **且** 学过模板」（=3），而 `/api/registry` 每项给界面的旗标
        # 只看「有没有模板」（=6）—— 多出来那三个**已经判为不健康**。
        # 同一句话出现两个数字，用户不知道信哪个；更糟的是坏站被算成资产。
        # 判据只能有一个函数（is_searchable），两份写成断言钉住。
        tpl = "https://{h}/search.php?q={kw}"
        R.note_site("good.com", ok=True, name="好站",
                    search_tpl=tpl.format(h="good.com", kw="{kw}"))
        # 学过模板、但被判为影视站（不健康）—— 这是差值的来源
        R.note_site("bad.com", ok=False, name="坏站", video_blocked=True,
                    search_tpl=tpl.format(h="bad.com", kw="{kw}"))
        # 健康、但压根没学过模板 —— 不该算进可搜源
        R.note_site("plain.com", ok=True, name="普通站")
        R.flush()
        check("健康 + 有模板 → 可搜", R.is_searchable(R.sites()["good.com"]))
        check("不健康 + 有模板 → **不算**可搜（坏站不能算资产）",
              not R.is_searchable(R.sites()["bad.com"]))
        check("但它照样能被识别出『模板还在』（诊断用）",
              R.has_search_tpl(R.sites()["bad.com"]))
        check("健康 + 没模板 → 不算可搜", not R.is_searchable(R.sites()["plain.com"]))

        # —— 第三个消费方：**搜索扇出**（RegistrySource 拿关键词直接问这些站）。
        #    searchable_sites() 以前把「健康 且 有模板」又写了一遍 ——
        #    三处各写一份的结局就是漂（界面 6 个、实际只搜 3 个）。
        ss = R.searchable_sites()
        check("搜索扇出收下健康 + 有模板的站", "good.com" in ss, str(sorted(ss)))
        check("搜索扇出**不收**被判死的站（哪怕学过模板）",
              "bad.com" not in ss)
        check("搜索扇出不收没学过模板的站", "plain.com" not in ss)

        # 关键一条：接口返回的两个口径必须**是同一个数**。
        from fastapi.testclient import TestClient  # noqa: E402
        from app import main as M                  # noqa: E402
        api = TestClient(M.app)
        reg = api.get("/api/registry")
        check("GET /api/registry 200", reg.status_code == 200, str(reg.status_code))
        view = reg.json()
        n_list = sum(1 for s in view["sites"] if s["searchable"])
        check("总览的『可搜源』= 站点列表里标记可搜的条数",
              view["stats"]["sites_searchable"] == n_list,
              f"stats={view['stats']['sites_searchable']} vs 列表={n_list}")
        check("标了可搜的站一定健康",
              all(s["healthy"] for s in view["sites"] if s["searchable"]),
              str([s["host"] for s in view["sites"] if s["searchable"] and not s["healthy"]]))
        check("标了可搜的站一定有模板",
              all(s["has_search_tpl"] for s in view["sites"] if s["searchable"]))
        # 三个消费方必须是**同一个数**：总览统计、面板徽标、搜索扇出。
        # 漂移的真实后果：界面说「能搜 6 个」，实际每轮搜索只问 3 个。
        n_fan = len(R.searchable_sites())
        check("三个消费方同一个数（总览 / 徽标 / 搜索扇出）",
              view["stats"]["sites_searchable"] == n_list == n_fan,
              f"stats={view['stats']['sites_searchable']} 徽标={n_list} 扇出={n_fan}")

        # -----------------------------------------------------------------
        print("\n—— 接线：来源库面板要把「能搜」亮出来 ——")
        # 可搜源是这个库攒的**主要资产**（夜间自动学的就是它），
        # 但站点行原来只显示「目录模板已学 / 正文容器 / 成败次数」，
        # 从不说哪个站能搜 —— 用户看到的只是一串可用/失效，
        # 完全不知道搜索能力在长。徽标判据必须是接口的 `searchable`
        # （健康 + 有模板）：有模板但站已失效的不标，那是空头支票。
        # 静态检查（同上），配 mutate：删掉徽标必须报红。
        js = (ROOT / "app" / "static" / "js" / "sources.js").read_text(encoding="utf-8")
        check("站点行有「能搜」徽标（判据=接口的 searchable）",
              bool(re.search(r's\.searchable\s*\?\s*`<span class="tag ok"[^>]*>能搜</span>`\s*:\s*""',
                             js, re.S)),
              "徽标不在或判据不是 s.searchable")
        check("总览统计里能看到可搜源数（sites_searchable）",
              "num(st.sites_searchable)" in js,
              "statRow 没显示 sites_searchable")
        # 计数位必须过 num()（防注入纪律，见 sources.js 顶部的长注释；
        # statRow/tabsHTML 原来写 `${st.sites || 0}`，和自己定义的纪律不一致）。
        bad_num = re.findall(r"\$\{st\.\w+ \|\| 0\}", js)
        check(f"statRow/tabsHTML 的计数都走 num()（残留：{bad_num}）", not bad_num)
        # 书行的「⚠ 可能不全」也是这面板的一部分（上一轮加的）：章节数必须
        # 和目录结论一起出现 —— 「12 章」和「这本书就是 12 章」长得一模一样。
        check("书行的章节标签带「⚠ 可能不全」（判据=b.note）",
              bool(re.search(r"b\.note \? \" ⚠ 可能不全\"", js)),
              "⚠ 文案不在，或判据不是 b.note")

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
