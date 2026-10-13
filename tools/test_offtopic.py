"""非小说站拦截回归 —— 教程/词典/博客/商城/文档站 必须被挡在来源库外。

为什么要这个测试
----------------
来源库里混进了一堆**根本不是小说站**的站，而且是"合法"混进来的：

  它们是搜索引擎对任何关键词都会顺手给的**通用结果** ——
  搜「三体」，搜索引擎除了给小说站，还会给菜鸟教程、爱奇艺、百科。
  这些站**不是坏站**（菜鸟教程 ok=35、MDN ok=13，健康得很），
  所以 `is_healthy()` 永远放行；它们的页面也确实有"正文"，
  于是 `analyze()` 还会给它们学一个 `content_hint`，看起来完全正常。

  但用户搜的是小说，这些站永远给不出小说。它们只会：
    · 占着候选的位子，把真小说站挤下去
    · 拖慢探测（每个候选都要真打一次）

  实测：178 站里有 23 个是这类（12.9%），包括
  菜鸟教程 / 爱词霸词典 / MDN / 博客园 / 腾讯云 / 看云文档 / 森海塞尔商城…

这个测试钉三件事：
  ① 判据只在「明显的非小说站」上命中（拿真实站名 + 常见垃圾站名验证）
  ② **绝不误杀小说站** —— 这是本测试最重要的部分。
     小说站起名很花（起名"XX动漫"的其实是轻小说站），
     所以判据只用「教程/词典/商城」这类小说站绝不会用的词。
  ③ `_scrub` 会把命中的站判死（ok 归零 + 打旗标），且**不删记录**
     （和影视站同一套自愈逻辑：判错了还能自己爬回来）

用法： python tools/test_offtopic.py
"""
from __future__ import annotations

import copy
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = 0
BAD = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global OK, BAD
    if cond:
        OK += 1
        print(f"  ✓ {name}")
    else:
        BAD += 1
        print(f"  ✗ {name}  {extra}")


# 真实小说站名单 —— 全部取自线上 registry.json 的活跃站（ok 数高的那些）。
# 判据**一个都不许命中**，否则就是把真小说站清掉了。
REAL_NOVEL_SITES = [
    ("www.384g.com", "新笔趣阁"),
    ("www.zilijian.cc", "字里间"),
    ("www.jnsxs.org", "吉内斯小说"),
    ("www.xxsy.net", "潇湘书院"),
    ("www.tadu.com", "塔读免费小说"),
    ("www.29zw.com", "29中文小说网"),
    ("m.akshu88.com", "爱看书吧"),
    ("www.tengc.com", "福书网"),
    ("www.luoxiaks.net", "落霞读书"),
    ("m.qidian.com", "起点中文网"),
    ("www.wyshu.com", "无忧书城"),
    ("m.dquanben.com", "全本小说网(笔趣阁)"),
    ("tianyashuku.net", "天涯书库"),
    ("www.irrxs.com", "人人小说网"),
    ("www.biqugela.cc", "笔趣阁啦"),
    ("www.shuzhaige.com", "书斋阁"),
    ("www.biquhui.vip", "笔趣会"),
    # ⚠ 下面这些是**最容易误杀**的：名字里带"动漫""二次元"，
    #   但其实是轻小说站（合法小说分类）。判据里绝对不能有"动漫"。
    ("www.linovelib.com", "哔哩轻小说"),
    ("www.wenku8.net", "轻之文库"),
    ("www.qidian.com", "起点中文网"),
    ("www.zongheng.com", "纵横中文网"),
]

# 应当命中的非小说站（线上真实抓到的 + 常见形态）
OFFTOPIC_SITES = [
    ("www.runoob.com", "菜鸟教程"),
    ("www.iciba.com", "爱词霸在线词典"),
    ("www.cnblogs.com", "博客园"),
    ("developer.mozilla.org", "MDNWebDocs"),
    ("www.kancloud.cn", ""),
    ("cloud.tencent.com", "腾讯云"),
    ("www.sennheiser.com.cn", "官方网站及在线商城"),
    ("www.deepl.com", "全世界最准确的翻译器"),
    ("fanyi.youdao.com", "在线即时翻译"),
    ("docs.pingcode.com", ""),
    ("github.com", ""),
    ("www.xiaohongshu.com", "你的生活兴趣社区"),
]


def main() -> int:
    print("=" * 62)
    print("非小说站拦截（教程/词典/博客/商城/文档站）")
    print("=" * 62)

    # 关键：指向一份临时库，绝不能碰真实 cache/registry.json
    tmp = Path(tempfile.mkdtemp(prefix="offtopic-")) / "registry.json"
    os.environ["NOVEL_REGISTRY"] = str(tmp)

    from app import registry  # noqa: E402

    print("\n── 1. 非小说站必须命中 ──")
    miss = [f"{h}({n})" for h, n in OFFTOPIC_SITES
            if not registry._is_offtopic_site(h, {"name": n})]
    check(f"{len(OFFTOPIC_SITES)} 个非小说站全部命中", not miss, f"漏判：{miss}")

    print("\n── 2. 小说站一个都不许误杀（本测试最关键）──")
    false_pos = [f"{h}({n})" for h, n in REAL_NOVEL_SITES
                 if registry._is_offtopic_site(h, {"name": n})]
    check(f"{len(REAL_NOVEL_SITES)} 个真实小说站零误杀", not false_pos,
          f"误杀：{false_pos}")

    print("\n── 3. '动漫'不是判据（轻小说站会自称动漫）──")
    check("站名含'动漫'的站不被误杀",
          not registry._is_offtopic_site("www.example-ln.com", {"name": "XX动漫轻小说"}),
          "把轻小说站当成了非小说站")

    print("\n── 4. _scrub 把命中的站判死但不删记录 ──")
    db = {"sites": {
        "www.runoob.com": {"name": "菜鸟教程", "ok": 35, "fail": 2},
        "www.384g.com": {"name": "新笔趣阁", "ok": 295, "fail": 3},
    }, "books": {}}
    before = copy.deepcopy(db)
    n = registry._scrub(db)
    check("scrub 返回清理数 = 1", n == 1, f"实际 {n}")
    junk = db["sites"]["www.runoob.com"]
    good = db["sites"]["www.384g.com"]
    check("垃圾站 ok 归零", junk.get("ok") == 0, f"实际 {junk.get('ok')}")
    check("垃圾站带上 offtopic_blocked 旗标",
          junk.get("offtopic_blocked") == 1, "旗标没打上")
    check("垃圾站有可读原因", "非小说站" in str(junk.get("blocked_why")),
          f"实际 {junk.get('blocked_why')}")
    check("垃圾站**记录还在**（不删，可事后排查）",
          "www.runoob.com" in db["sites"], "记录被删了")
    check("真小说站没被动过", good == before["sites"]["www.384g.com"],
          f"被改了：{good}")
    check("垃圾站变成不健康",
          not registry.is_healthy(junk), "判完还是健康的")

    print("\n── 5. 幂等：再 scrub 一次不会重复计数 ──")
    n2 = registry._scrub(db)
    check("第二次 scrub 返回 0", n2 == 0, f"实际 {n2}")

    # ------------------------------------------------------------------
    print("\n── 6. off-topic 旗标必须真的能拦住「历史 ok 很多」的站 ──")
    #
    # ⚠ 这一节钉的是一个**真实漏检**（本轮发现并修）：
    #   `_scrub` 早就给非小说站打了 `offtopic_blocked` 并把 ok 归零，
    #   但 `is_healthy` **只看 video_blocked**、不看 offtopic_blocked。
    #   于是那些站只要历史上攒过 ok（实测 www.kancloud.cn ok=32），
    #   `fail > ok*2` 就不成立 —— **又活回来了**。
    #   第 4 节那条「垃圾站变成不健康」测不出这个：runoob 是 ok=0，
    #   靠的是 `ok==0 and fail>=3` 那条命中的，与旗标无关。
    #
    #   所以这里构造一个「ok 很高 + 带 offtopic 旗标」的站：
    #   只有真的读旗标，它才会被判不健康。
    hot = {
        "ok": 32, "fail": 3,
        "offtopic_blocked": 1,
        "name": "某文档站",
    }
    check("带 offtopic 旗标、且 ok=32 的站 → 不健康",
          not registry.is_healthy(hot),
          "旗标没被 is_healthy 读到（这正是修之前的 bug）")
    # 反例：同样的 ok/fail，去掉旗标 → 健康（证明是"旗标"起了作用，
    # 不是 ok/fail 恰好算下来不健康）
    hot2 = dict(hot)
    del hot2["offtopic_blocked"]
    check("同样计数、去掉旗标 → 健康（证明是旗标起的效力）",
          registry.is_healthy(hot2),
          "去掉旗标也判不健康，说明这条断言没测到旗标")

    print("\n── 7. 可搜源（search_tpl）不该被「猜错路径」拖死 ──")
    #
    # ⚠ 本轮第二个真实修复：fail 是**混装桶**（网络失败 / URL 猜错 / 搜不出
    #   都算），于是「能站内搜索」的站会因抓某本书时猜错路径而累积 fail，
    #   最终被 `fail > ok*2` 误杀，连带丢掉 search_tpl 这个 L 源资产。
    #   实测被误杀：www.tadu.com（ok=39/fail=79，只超阈值 1，站实测活着）、
    #   www.biqugela.cc（ok=6/fail=15）。两者 fail_down 都是 0。
    tpl_site = {
        "ok": 39, "fail": 79, "fail_down": 0,   # 混装 fail 超阈值，但无网络失败
        "search_tpl": "/search",
        "name": "某小说站",
    }
    check("可搜源：混装 fail 超阈值、但无网络层失败 → 仍健康",
          registry.is_healthy(tpl_site),
          "被混装 fail 误杀了（修复前就是这个行为）")
    # 底线：同样的站若**网络层失败**确实高，照样否 —— 放宽不等于放水
    dead_tpl = {
        "ok": 1, "fail": 9, "fail_down": 9,     # 网络层失败压过成功
        "search_tpl": "/search",
        "name": "已挂的可搜站",
    }
    check("可搜源：网络层失败压过成功 → 照样否（放宽≠放水）",
          not registry.is_healthy(dead_tpl),
          "放宽后把真挂掉的站也放行了")
    # 非可搜站维持原判据（保守，别动未知行为）
    plain_dead = {"ok": 1, "fail": 9, "fail_down": 0, "name": "普通站"}
    check("普通站（无 search_tpl）维持混装比值判据",
          not registry.is_healthy(plain_dead),
          "普通站的判据被顺手放宽了（不该）")

    print("\n" + "=" * 62)
    print(f"通过 {OK} · 失败 {BAD}")
    print("=" * 62)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
