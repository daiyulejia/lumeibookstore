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

        print("\n—— 搜索模板必须真能带关键词 ——")
        # 2026-10-21 线上实测：14 个「可搜源」里 6 个的模板是 `/search.html`
        # 这种**不带 `{kw}` 占位**的裸路径。`build_url()` 只做占位替换，
        # 没有占位 = 关键词根本没发给站点，打开的是搜索页/首页（本来就有一堆书），
        # 于是"链接数够多"判真、控制实验也判不了假 —— 全静默。
        R.note_site("good.com", ok=True)
        check("带 {kw} 的模板照常收下",
              R.note_search_tpl("good.com", "/?s={kw}") is True)
        R.note_site("bare.com", ok=True)
        check("★ 裸路径模板被拒收（写不进去）",
              R.note_search_tpl("bare.com", "/search.html") is False)
        check("★ 拒收之后库里没有模板",
              not (R.known_site("bare.com").get("search_tpl") or ""))
        R.note_site("post.com", ok=True)
        check("POST + body 里带 {kw} 照常收下",
              R.note_search_tpl("post.com", "/search.php", method="post",
                                body={"s": "{kw}"}) is True)

        check("★ is_searchable 否掉无占位的模板",
              not R.is_searchable({"search_tpl": "/search.html", "ok": 50}))
        check("is_searchable 认可带 {kw} 的模板",
              R.is_searchable({"search_tpl": "/?s={kw}", "ok": 50}))
        check("★ 库里的假模板进不了可搜清单",
              "bare.com" not in R.searchable_sites())

        # 自愈：库里的旧假模板要被清掉，且**站不许丢**（回到重学队列）
        R.note_site("legacy.com", ok=True)
        R.flush()
        d = disk()
        d["sites"]["legacy.com"].update({"search_tpl": "/search.html",
                                         "search_enc": "utf-8",
                                         "search_ver": 9,
                                         "search_fail": 3,
                                         "search_fail_ver": R.LEARN_VER,
                                         # 故意比"现在"更新：模拟另一个进程刚写过。
                                         # 清理若只写 `_now()`，合并时会被这份赢回去。
                                         "updated": int(time.time()) + 60})
        R._DB.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        R._cache = None                       # 让下一次读库重跑自愈
        s = R.known_site("legacy.com")
        check("★ 自愈把带不了关键词的模板清掉了",
              not (s.get("search_tpl") or ""), repr(s.get("search_tpl")))
        check("★ 站没被丢掉（只是回到重学队列）", bool(s))
        check("★ 失败账清零（否则旧账挡住重学）",
              int(s.get("search_fail") or 0) == 0
              and int(s.get("search_fail_ver") or 0) == 0,
              f"fail={s.get('search_fail')} ver={s.get('search_fail_ver')}")
        R.flush()
        d2 = disk()
        check("★ 清理结果真落了盘（updated 要盖过盘上那份）",
              (d2["sites"]["legacy.com"].get("search_tpl") or "") == "",
              repr(d2["sites"]["legacy.com"].get("search_tpl")))
        R.forget_site("legacy.com")

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

        # -----------------------------------------------------------------
        print("\n—— 学站清单：只挑「值得学」的站 ——")
        # 为什么这道筛子值得测：线上实测（2026-10-18）拿"所有没学过搜索模板
        # 的站"当目标跑批量学习，12 个目标里混进了 `www.kugou.com`（音乐）、
        # `wulin2.games.wanmei.com`（游戏）、`mzh.moegirl.org.cn`（萌娘百科）、
        # `www.chagushici.com`（诗词）。每个站都要花「抓首页 + 最多 6 次爆破」，
        # **真正的小说站反而排不上队**；而且非小说站学会了搜索也永远不会
        # 出现在搜书结果里 —— 纯烧预算。
        # `learn_candidates()` 就是那道筛子：健康 ∧ 不是非小说/影视站 ∧ 没学会
        # ∧ 没放弃，且**能拿目录的排前面**（它证明过"这个站能给整本书"）。
        for h in ("learn-toc.com", "learn-plain.com", "learn-dead.com",
                  "learn-junk.com", "learn-giveup.com"):
            R.note_site(h, ok=True)
        R.note_site("learn-toc.com", ok=True, toc_tpl="/mulu/")
        for _ in range(3):
            R.note_site("learn-dead.com", ok=False)     # 判死
        R.note_site("learn-junk.com", ok=True, name="菜鸟教程")  # 非小说站
        for _ in range(3):
            R.note_search_fail("learn-giveup.com")      # 当前版本下放弃过

        cand = R.learn_candidates()
        check("能拿目录的健康站入选", "learn-toc.com" in cand, str(cand))
        check("普通健康站也入选", "learn-plain.com" in cand, str(cand))
        check("判死的站不入选（活着才有意义）", "learn-dead.com" not in cand, str(cand))
        check("非小说站不入选（学了也用不上）", "learn-junk.com" not in cand, str(cand))
        check("放弃过的站不入选（不自作多情）", "learn-giveup.com" not in cand, str(cand))
        check("能拿目录的排在普通站前面（先学最可能成的）",
              ("learn-toc.com" in cand and "learn-plain.com" in cand
               and cand.index("learn-toc.com") < cand.index("learn-plain.com")),
              str(cand))
        R.note_search_tpl("learn-plain.com", "/search?q={kw}")
        check("已经会搜了的站不再入选", "learn-plain.com" not in R.learn_candidates(),
              str(R.learn_candidates()))

        # -----------------------------------------------------------------
        print("\n—— 学站失败计数：必须带学习器版本号，否则改好学习器也救不回来 ——")
        # 线上实测（2026-10-21）：92 个站没有搜索模板，其中 **89 个 search_fail
        # 已经顶到 3**（永久放弃）。而查下来那批失败正是学习器自己的缺陷：
        #   ① 验证一律按 https，老小说站大量只有 http
        #   ② 爆破预算 6 条，高频的 `/?s=` 排在候选表第 17 位，永远轮不到
        # 修好学习器却不动历史计数，那 89 个站仍然被挡在门外 ——
        # 用户看到的可搜源数量**一个都不会变**，等于白修。
        R.note_site("learn-oldfail.com", ok=True,
                    search_fail=3)             # 旧版本记的 3 次失败（没有 ver）
        check("旧版本记的失败不再挡人（学习器升级后自动复活）",
              R.should_try_learn("learn-oldfail.com"),
              str(R.known_site("learn-oldfail.com")))
        check("学习器升级后这类站重新进入学站清单",
              "learn-oldfail.com" in R.learn_candidates())
        for _ in range(R.SEARCH_LEARN_MAX_TRIES - 1):
            R.note_search_fail("learn-oldfail.com")
        check("当前版本下失败没满额时还算候选",
              R.should_try_learn("learn-oldfail.com"))
        R.note_search_fail("learn-oldfail.com")
        check("当前版本下满额才真的放弃",
              not R.should_try_learn("learn-oldfail.com"),
              str(R.known_site("learn-oldfail.com")))

        # -----------------------------------------------------------------
        print("\n—— 假搜索模板：旧版学出来的必须挑出来复核，假的要能撤掉 ——")
        # 线上实测 21 个已学模板里 9 个是假的（站点不认参数、照常吐首页）。
        # 光把学习器改好清不掉它们 —— 它们带着 search_tpl 蹲在库里，
        # 每次搜索都白打一遍，还把"综合 N 站"撑大。
        R.note_site("tpl-fresh.com", ok=True)
        R.note_search_tpl("tpl-fresh.com", "/?q={kw}")
        # ⚠ 这条判据原来是反的（「当前版本学出来的模板不需要复核」）——
        #   那是把当时的实现当成了规格。实际代价我踩到了：学站阶段为了省请求
        #   只做单轮控制实验，而单轮会翻转（zxs8 限流吐静态页被判"真"），
        #   盖上当前版本的章之后一整个复核轮次都没查它。
        #   现场复发：手动学一轮又学出 www.xxsy.net / www.whxss.com（以前判过假的）。
        #   信任链应当是：**学过 = 候选，两轮复核判真才免检**。
        check("★ 刚学到的模板**必须**进复核队列（学过 ≠ 核实过）",
              "tpl-fresh.com" in R.reverify_candidates(),
              str(R.reverify_candidates()))
        check("★ 学到的模板不盖「已核实」章（search_ver 写 0）",
              int(R.known_site("tpl-fresh.com").get("search_ver") or 0) == 0,
              str(R.known_site("tpl-fresh.com").get("search_ver")))
        # 复核判真之后才盖章，然后才不再复核
        R.note_site("tpl-fresh.com", ok=True, search_ver=R.LEARN_VER)
        check("复核判真（盖章）之后才免检",
              "tpl-fresh.com" not in R.reverify_candidates(),
              str(R.reverify_candidates()))
        saved_ver = R.LEARN_VER
        try:
            R.LEARN_VER = saved_ver + 1      # 模拟"学习器又改好了"
            check("★ 学习器升版后，旧模板进入待复核清单",
                  "tpl-fresh.com" in R.reverify_candidates(),
                  str(R.reverify_candidates()))
        finally:
            R.LEARN_VER = saved_ver

        R.note_site("tpl-bad.com", ok=True)
        R.note_search_tpl("tpl-bad.com", "/x?q={kw}")
        check("撤之前它确实是「可搜源」",
              bool((R.known_site("tpl-bad.com").get("search_tpl") or "")))
        check("撤掉返回 True", R.clear_search_tpl("tpl-bad.com", why="复核：假搜索"))
        check("★ 撤掉之后不再是可搜源",
              not (R.known_site("tpl-bad.com").get("search_tpl") or ""))
        check("撤掉算一次学习失败（别立刻又去学一遍）",
              R.learn_tries(R.known_site("tpl-bad.com")) == 1,
              str(R.known_site("tpl-bad.com")))
        R.flush()
        check("★ 落盘的是空串而不是「键消失」（键消失会在合并时从盘上复活）",
              disk()["sites"]["tpl-bad.com"].get("search_tpl") == "",
              str(disk()["sites"]["tpl-bad.com"].get("search_tpl")))
        check("撤掉后它回到待学队列（还能再学一次真的）",
              "tpl-bad.com" in R.learn_candidates())
        check("本来就没模板的站，撤掉返回 False（不能凭空记一次失败）",
              R.clear_search_tpl("tpl-fresh.com") is True
              and R.clear_search_tpl("learn-toc.com") is False)

        # -----------------------------------------------------------------
        print("\n—— 学站探测词：必须是从页面标题收拾出来的真书名 ——")
        # 库里的 title 存的是**页面标题**：`药鼎仙途最新章节列表` /
        # `《神通者》-天蚕土豆-章节目录`。拿这种串去搜，一搜一个空，
        # 于是明明有搜索接口的站也被记成"学不会"。
        # 实测：29 个站演练用脏标题只学会 3 个。
        R.note_book("http://pt.com/1", title="药鼎仙途最新章节列表",
                    host="pt.com", ok=True)
        check("★ 页面标题被收拾成能搜的书名",
              R.probe_title("pt.com") == "药鼎仙途", repr(R.probe_title("pt.com")))
        check("「书名-作者-站点」只取书名",
              R.clean_book_title("《神通者》-天蚕土豆-章节目录") == "神通者",
              repr(R.clean_book_title("《神通者》-天蚕土豆-章节目录")))
        check("短书名不许被当成噪声丢掉（「活着」是合法书名）",
              R.clean_book_title("活着") == "活着", repr(R.clean_book_title("活着")))
        R.note_site("pt2.com", ok=True, name="落霞读书")
        R.note_book("http://pt2.com/1", title="落霞读书", host="pt2.com", ok=True)
        check("书名其实就是站名的记录不拿来当探测词",
              R.probe_title("pt2.com") == "", repr(R.probe_title("pt2.com")))

        # -----------------------------------------------------------------
        print("\n—— 学站清单：读过整本书的站排最前 ——")
        # 一批只跑得完十几个站，而线上有 92 个待学站 —— 排序就是筛选。
        # 70 个没有目录模板的站里混着企查查/酷狗音乐/豆包漫画/大英百科。
        R.note_site("kb-book.com", ok=True)                     # 只有书，没目录
        R.note_book("http://kb-book.com/1", title="三体",
                    host="kb-book.com", ok=True)
        R.note_site("kb-toc.com", ok=True, toc_tpl="/mulu/")    # 只有目录，没书
        cand2 = R.learn_candidates()
        check("★ 有书页证据（真读过整本书）的排在只有目录模板的前面",
              "kb-book.com" in cand2 and "kb-toc.com" in cand2
              and cand2.index("kb-book.com") < cand2.index("kb-toc.com"),
              str(cand2))

        # -----------------------------------------------------------------
        print("\n—— 学站预算：撞上限必须报 pending ——")
        # 线上实测事故：12 个目标 + 固定 14 秒预算 + 3 线程，
        # 接口只回 `learned=0 / failed=5`，另外 7 个既不算成功也不算失败，
        # **凭空消失**。调用方看着像"都学完了只是没学会"。
        # `as_completed(timeout=)` 超时会直接抛异常跳出循环，剩下没拿到结果
        # 的 future 一个都不会被计数 —— 所以必须自己算 `pending`。
        from app import discovery as D
        check("预算随批量大小增长（12 个站不能还是 14 秒）",
              D._learn_budget(12) > 14.0, f"{D._learn_budget(12)}")
        check("预算有上限（不能无限等）",
              D._learn_budget(1000) <= D._LEARN_BUDGET_MAX,
              f"{D._learn_budget(1000)}")
        check("空批量也有下限（不会算出 0 秒）",
              D._learn_budget(0) >= D._LEARN_BUDGET_MIN,
              f"{D._learn_budget(0)}")
        # 真跑一遍：把预算压到 0.01 秒、让每个站的探测都卡住不返回，
        # 应当**一个都没跑完**，且 `pending` 如实等于目标数。
        saved = (D._learn_budget, D.registry.should_try_learn, D.fetch_text,
                 D.sitelearn.learn_site)

        # 顺手抓日志：撞预算那条日志不能只报个数（见下面的断言）
        import logging as _log

        class _Cap(_log.Handler):
            def __init__(self):
                super().__init__()
                self.lines: list[str] = []

            def emit(self, rec):        # noqa: D102
                self.lines.append(rec.getMessage())

        _cap = _Cap()
        _lg = _log.getLogger("novel.discovery")
        _lg.addHandler(_cap)
        _lg.setLevel(_log.DEBUG)
        try:
            hosts = ["stall1.com", "stall2.com", "stall3.com"]
            D._learn_budget = lambda n: 0.01
            D.registry.should_try_learn = lambda h: True
            # ⚠ 首页必须给**非空** HTML —— 空 HTML 现在会走"首页打不开"快路径
            #   直接失败返回（不爆破），那样三个站都在预算内跑完了，
            #   这条判据就永远测不到 pending。要测的是"学到一半撞预算"。
            D.fetch_text = lambda *a, **k: ("<html>" + "x" * 800 + "</html>",
                                            "https://x.com/")
            # 爆破那一步也必须卡住 —— 不然它会真的去连 stall1.com 这种不存在的域名
            D.sitelearn.learn_site = lambda *a, **k: (time.sleep(0.6), {})[1]
            rep = D.learn_sites(hosts)
            check("撞预算时 pending 等于没跑完的站数",
                  rep.get("pending") == len(hosts), str(rep))
            check("learned + failed + pending 必须等于目标数（一个都不许凭空消失）",
                  rep["learned"] + rep["failed"] + rep.get("pending", -1) == len(hosts),
                  str(rep))
            # ⚠ 只报「还剩 3 个」等于没报：复盘时不知道是哪 3 个，
            #   也就分不清"这些站天生学不会（该放弃）"和"预算不够（该加预算）"——
            #   两者处置相反。这和 search.done 里「未回只给数字」是同一类病
            #   （见 2026-10-23 日报）。
            _txt = "\n".join(_cap.lines)
            check("★ 撞预算时点名没学完的站（不是只给个数）",
                  all(h in _txt for h in hosts),
                  _txt[-240:] or "（这条日志压根没打）")
        finally:
            _lg.removeHandler(_cap)
            (D._learn_budget, D.registry.should_try_learn, D.fetch_text,
             D.sitelearn.learn_site) = saved

        # -----------------------------------------------------------------
        print("\n—— 学站吞吐：单站成本必须与预算假设同量级 ——")
        # 线上实测（2026-10-21 03:20）：
        #     `站点学习超预算，先收手（还剩 23 个没学完）`，接口耗时 120011ms
        # 一整批 120 秒只学完 0~1 个站。根因是抓首页那一步**没走 fast_mode**，
        # 用全站默认 retries=3 + timeout=25s → 一个死站最坏 100 秒（https 再
        # 叠 http 兜底 200 秒），而预算按"每站 8 秒"算。差了一个数量级。
        # 后果：113 个站里 97 个永远学不到模板（可搜源只有 16 个）。
        #
        # 判据不能写"耗时小于 X 秒"（随站点快慢漂），要验**抓首页时实际用的
        # 线程局部参数** —— retries 必须 0、timeout 必须有界。
        from app import utils as _U
        _seen: list[tuple[int, float | None]] = []

        def _probe_fetch(url, *a, **k):
            _seen.append((_U.current_retries(), _U.current_timeout()))
            raise RuntimeError("打不通")     # 模拟死站：走最短路径

        saved2 = (D.registry.should_try_learn, D.fetch_text,
                  D.sitelearn.learn_site, D._learn_budget)
        try:
            D.registry.should_try_learn = lambda h: True
            D.fetch_text = _probe_fetch
            D.sitelearn.learn_site = lambda *a, **k: {}
            D._learn_budget = lambda n: 5.0
            D.learn_sites(["dead1.com", "dead2.com"])
        finally:
            (D.registry.should_try_learn, D.fetch_text,
             D.sitelearn.learn_site, D._learn_budget) = saved2

        check("学站时真的去抓了首页（否则下面等于没测）", len(_seen) >= 2,
              f"抓了 {len(_seen)} 次")
        check("★ 抓首页不重试（retries=0）—— 死站不该被重试 3 次耗掉 100 秒",
              all(r == 0 for r, _ in _seen), f"{_seen}")
        check("★ 抓首页超时受控（≤ _LEARN_FETCH_TIMEOUT，不是全站默认 25 秒）",
              all((t or 99) <= D._LEARN_FETCH_TIMEOUT + 0.01 for _, t in _seen),
              f"{_seen}（上限 {D._LEARN_FETCH_TIMEOUT}）")
        # 预算假设必须与最坏单站成本同量级，否则 pending 数（"还剩 N 个"）
        # 就是假的：预算说能跑 15 个，实际一个都跑不完。
        worst_per_site = 2 * D._LEARN_FETCH_TIMEOUT      # https + http 兜底
        check("★ 每站预算 ≥ 最坏单站成本（https+http 两次抓取）",
              D._LEARN_BUDGET_PER_SITE >= worst_per_site - 0.01,
              f"每站预算 {D._LEARN_BUDGET_PER_SITE}s < 最坏成本 {worst_per_site}s —— "
              f"「还剩 N 个」这个数会失真")

        # -----------------------------------------------------------------
        print("\n—— 搜不出东西的站：不许算「可搜源」——")
        # 线上实测（2026-10-22）：`searchable_sites()` 报 15 个，逐个拿同一个
        # 关键词去搜，**7 个一条书链接都抽不出来**，而且是确定性的 ——
        # xizids/itiandixs 的 POST 落回「搜索_首页」、fanqienovel 是前端渲染、
        # biquhui 把 `?s=` 吞掉回首页。界面照报 15 个，资产是虚的。
        # 判据分两层：抽出 0 条 = 不是搜索页（search_shape）；
        # 抽出 N 条全被过滤 = 站里没这本书（search_miss，永不参与淘汰）。

        def _mk(host: str, **extra) -> dict:
            R.note_site(host, name=host, search_tpl="/?s={kw}",
                        search_method="get", search_ver=R.LEARN_VER, **extra)
            return R.known_site(host)

        alive = _mk("alive.example.com")
        check("前提：模板合法、已核实 → 算可搜源", R.is_searchable(alive),
              str(alive))

        R.note_search_result("alive.example.com", hits=3, raw=40)
        alive = R.known_site("alive.example.com")
        check("搜出结果 → search_hit +1", int(alive.get("search_hit") or 0) == 1,
              str(alive.get("search_hit")))
        check("搜出结果不该被记成 miss/shape",
              not alive.get("search_miss") and not alive.get("search_shape"),
              f"miss={alive.get('search_miss')} shape={alive.get('search_shape')}")

        # ① 抽出 N 条、过滤后 0 条 = "站里没这本书"，**永远不淘汰**
        _mk("miss.example.com")
        for _ in range(6):
            R.note_search_result("miss.example.com", hits=0, raw=12)
        miss = R.known_site("miss.example.com")
        check("抽出链接但没这本书 → 记 search_miss",
              int(miss.get("search_miss") or 0) == 6, str(miss.get("search_miss")))
        check("★ 搜了 6 次都没有这本书，仍然算可搜源（这不是站的错）",
              R.is_searchable(miss),
              f"shape={miss.get('search_shape')} tpl={miss.get('search_tpl')!r}")

        # ② 抽出 0 条 = 打开的不是搜索页 → 连记到顶就作废模板
        _mk("dead.example.com")
        for i in range(R.SEARCH_SHAPE_MAX):
            R.note_search_result("dead.example.com", hits=0, raw=0)
            st = R.known_site("dead.example.com")
            if i < R.SEARCH_SHAPE_MAX - 1:
                check(f"第 {i + 1} 次「不是搜索页」还留着模板（别一棒子打死）",
                      bool((st.get("search_tpl") or "").strip()),
                      str(st.get("search_tpl")))
        dead = R.known_site("dead.example.com")
        check("★ 连续到顶 → 模板作废（写空串，不 pop）",
              dead.get("search_tpl") == "", repr(dead.get("search_tpl")))
        check("★ 作废后不再算可搜源", not R.is_searchable(dead), str(dead))
        check("作废后回复核队列（search_ver 清 0）",
              int(dead.get("search_ver") or 0) == 0, str(dead.get("search_ver")))
        check("作废后回到「可以重学」状态（模板没了、失败账未满）",
              R.should_try_learn("dead.example.com"), "重学被挡住就不会再变好")
        check("作废记了一次学站失败（用来兜底，顶到上限自然放弃）",
              int(dead.get("search_fail") or 0) == 1, str(dead.get("search_fail")))

        # ③ 「搜出过东西」是硬证据 —— 之后偶发几次不是搜索页，不能判死
        _mk("flaky.example.com")
        R.note_search_result("flaky.example.com", hits=2, raw=9)
        for _ in range(R.SEARCH_SHAPE_MAX + 2):
            R.note_search_result("flaky.example.com", hits=0, raw=0)
        flaky = R.known_site("flaky.example.com")
        check("★ 搜出过一次 → 之后连续「不是搜索页」也不作废模板",
              bool((flaky.get("search_tpl") or "").strip()),
              "站点会临时拦爬虫，一次两次不该判死")
        check("这种站仍然算可搜源", R.is_searchable(flaky), str(flaky))
        check("但形态失败账照样记着（排查时看得见）",
              int(flaky.get("search_shape") or 0) == R.SEARCH_SHAPE_MAX + 2,
              str(flaky.get("search_shape")))

        # ④ 混合：搜出过一次之后，再攒满形态失败，账要归零（不能慢慢积成死刑）
        R.note_search_result("flaky.example.com", hits=1, raw=5)
        flaky = R.known_site("flaky.example.com")
        check("再次搜出结果 → 形态失败账清零",
              int(flaky.get("search_shape") or 0) == 0, str(flaky.get("search_shape")))

        # ⑤ 换模板之后搜索产出的账必须从头记
        #    不清的话两种错都会出现：旧模板的"搜出过"护着新坏模板（永久留着白打）、
        #    旧模板的形态失败账让新模板**只剩 1 次机会**就把自己弄死（实测过）。
        #    真实路径是「复核判假 → clear_search_tpl 撤掉 → 重学」——
        #    这条路径上一个模板是**搜出过东西、也攒过形态失败**的，
        #    所以必须走这一遍才测得出那两个计数有没有被清。
        _mk("reborn.example.com")
        R.note_search_result("reborn.example.com", hits=2, raw=9)
        for _ in range(R.SEARCH_SHAPE_MAX):
            R.note_search_result("reborn.example.com", hits=0, raw=0)
        old = R.known_site("reborn.example.com")
        check("前提：旧模板搜出过东西、也攒过形态失败",
              int(old.get("search_hit") or 0) == 1
              and int(old.get("search_shape") or 0) == R.SEARCH_SHAPE_MAX, str(old))
        R.clear_search_tpl("reborn.example.com", why="复核判假")
        check("前提：复核把旧模板撤掉了",
              R.known_site("reborn.example.com").get("search_tpl") == "",
              str(R.known_site("reborn.example.com").get("search_tpl")))
        R.note_search_tpl("reborn.example.com", "/?s={kw}", enc="utf-8")
        reborn = R.known_site("reborn.example.com")
        check("重学之后模板回来了", bool((reborn.get("search_tpl") or "").strip()),
              str(reborn))
        check("★ 重学之后形态失败账清零（新模板等于新假设，不能被旧账挡死）",
              int(reborn.get("search_shape") or 0) == 0,
              str(reborn.get("search_shape")))
        check("★ 重学之后「搜出过」也清零（旧模板的成绩不能护着新模板）",
              int(reborn.get("search_hit") or 0) == 0, str(reborn.get("search_hit")))
        # 上一条模板的**死因**同样属于「旧结论」，必须跟着清。
        # 线上实例（2026-10-22 复盘）：16 个可搜源里有 8 个同时出现
        # `searchable=True` 和 `why=复核：模板不认关键词（假搜索）`——
        # 那 8 个站的模板其实都真的带 `{kw}`（5 个走 POST body），
        # 只是 why 停在上一轮被判假的那条模板上没清。复盘照着这句话
        # 去查「假站为什么还在扇出」，白花了半小时 —— 库是好的，是它在撒谎。
        check("★ 重学之后旧模板的死因清空（不许把上一轮的结论挂在新模板上）",
              not (reborn.get("search_fail_why") or "").strip(),
              repr(reborn.get("search_fail_why")))
        check("重学之后立刻算可搜源（给它一次机会）",
              R.is_searchable(reborn), str(reborn))
        # 反向验一遍：新模板有**完整的 3 次机会**，不是接着旧账只剩 1 次
        for i in range(R.SEARCH_SHAPE_MAX - 1):
            R.note_search_result("reborn.example.com", hits=0, raw=0)
            check(f"新模板第 {i + 1} 次搜不出东西还留着（旧账不许提前把它弄死）",
                  bool((R.known_site("reborn.example.com").get("search_tpl") or "").strip()),
                  str(R.known_site("reborn.example.com").get("search_tpl")))
        R.note_search_result("reborn.example.com", hits=0, raw=0)
        check("★ 攒满 3 次才作废（旧模板的成绩/旧账都不许护着它）",
              R.known_site("reborn.example.com").get("search_tpl") == "",
              str(R.known_site("reborn.example.com").get("search_tpl")))

        # ⑥ 空结果页：`raw == 0` 但**页面就是搜索页**（"没有找到《xx》"）
        #    这是「站里没这本书」的第二种形态，绝不能算模板坏了。
        #    2026-10-29 线上实测（本条是当天的主线）：
        #      夜间刚学到的 8 个源（hbsjob / m.kudushu / gashuw / itiandixs /
        #      jcxs / mingchaonaxieshier / xizids / xuanhuanbiquge）在一次
        #      复盘探针里**全部** shape=3、模板被清空 —— 22 个可搜源掉到 14 个。
        #      它们唯一的"错"是被拿去搜了几本冷门书：空结果页里一条书链接
        #      都没有 → raw=0 → 被算成"打开的不是搜索页" → 连记 3 次作废。
        #      用户搜三本冷门书就会触发同一件事：源池少三分之一，而且不报错。
        _mk("empty.example.com")
        for _ in range(R.SEARCH_SHAPE_MAX + 3):
            R.note_search_result("empty.example.com", hits=0, raw=0,
                                 empty_page=True)
        emp = R.known_site("empty.example.com")
        check("★ 空结果页记 search_miss，不记 search_shape",
              int(emp.get("search_miss") or 0) == R.SEARCH_SHAPE_MAX + 3
              and int(emp.get("search_shape") or 0) == 0, str(emp))
        check("★ 连搜 6 次空结果页，模板照样活着（这不是模板的错）",
              bool((emp.get("search_tpl") or "").strip()),
              repr(emp.get("search_tpl")))
        check("空结果页的站仍然算可搜源", R.is_searchable(emp), str(emp))

        # 但 `empty_page` 不是"永远不作废"的挡箭牌：真正的"不是搜索页"
        # （没有空态文案、也不回显关键词）照样要能攒到作废。
        _mk("mixed.example.com")
        for _ in range(4):
            R.note_search_result("mixed.example.com", hits=0, raw=0,
                                 empty_page=True)
        mid = R.known_site("mixed.example.com")
        check("前提：4 次空结果页之后形态失败账还是 0",
              int(mid.get("search_shape") or 0) == 0, str(mid))
        for _ in range(R.SEARCH_SHAPE_MAX):
            R.note_search_result("mixed.example.com", hits=0, raw=0,
                                 empty_page=False)
        check("★ 真的「不是搜索页」照样攒满作废（empty_page 不许当免死金牌）",
              R.known_site("mixed.example.com").get("search_tpl") == "",
              repr(R.known_site("mixed.example.com").get("search_tpl")))

        print("—— 上面这些必须真落了盘（不只是内存） ——")
        R.flush()
        dsk = disk()["sites"]
        check("search_shape 落盘", int(dsk["flaky.example.com"].get("search_hit") or 0) >= 2,
              str(dsk["flaky.example.com"]))
        check("作废的模板在盘上也是空串", dsk["dead.example.com"].get("search_tpl") == "",
              repr(dsk["dead.example.com"].get("search_tpl")))

        # -----------------------------------------------------------------
        print("\n—— 读库自愈：模板还在，就不许挂旧模板的死因 ——")
        # 线上实测（2026-10-22 复盘）：16 个可搜源里 8 个同时是
        # `searchable=True` 和 `why=复核：模板不认关键词（假搜索）`。
        # 那 8 个站的模板其实都真的带 {kw}（5 个走 POST body），
        # 旧结论是上一轮被判假的那条模板留下的。而且这类站**永远不会**
        # 再走一遍重学（有模板的站两个入口都跳过），不靠读库自愈就永久留着。
        R.flush()
        raw = disk()
        raw["sites"]["stale.example.com"] = {
            "host": "stale.example.com", "ok": 5,
            "search_tpl": "/?s={kw}", "search_enc": "utf-8",
            "search_fail_why": "复核：模板不认关键词（假搜索）",
            "updated": int(time.time()),
        }
        raw["sites"]["legacy.example.com"] = {
            "host": "legacy.example.com", "ok": 5,
            "search_tpl": "", "search_fail_why": "没找到可用的搜索接口",
            "updated": int(time.time()),
        }
        R._DB.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        R._cache = None          # 强制走一次 _load()，自愈就发生在那里
        stale = R.known_site("stale.example.com")
        check("★ 模板还在 → 旧模板的死因被清空（否则同一行既说能搜又说假搜索）",
              not (stale.get("search_fail_why") or "").strip(),
              repr(stale.get("search_fail_why")))
        check("模板还留着（自愈只清死因，不许顺手把站弄没）",
              (stale.get("search_tpl") or "") == "/?s={kw}", repr(stale.get("search_tpl")))
        # 反向：没模板的站，死因是**有效结论**，一个都不许清
        legacy = R.known_site("legacy.example.com")
        check("★ 没模板的站，死因照留（自愈不许把有效结论一起抹掉）",
              (legacy.get("search_fail_why") or "") == "没找到可用的搜索接口",
              repr(legacy.get("search_fail_why")))

        # -----------------------------------------------------------------
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
