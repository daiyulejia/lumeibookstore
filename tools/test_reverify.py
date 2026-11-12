# -*- coding: utf-8 -*-
"""夜间复核的**终点**与**限速**（app/discovery.reverify_sites + sitelearn）。

为什么单独立一份（2026-11-12 线上复盘）
--------------------------------------
复核有两条终点：判假 → 撤模板；判真 → 盖章免检。但「没结论」这条
**只 `unjudged += 1` 然后就没了** —— 站留在 `reverify_candidates()` 里，
每夜重查。线上 6 个站（350.ooo / m.kudushu / bqg5555 / hodei / maozhuar /
nana00）因此每夜 03:18 / 03:40 / 04:00 各被查一轮，每站 2 个探测词 ×
2 次尝试，连着三天名单一字不差，≈36+ 请求/夜、**零信息**。

逐站复现后真相是两件事被混成了一件：
  · 4 个站的第 2 个请求拿回 **59 字节**的
    `<script>alert("搜索间隔: 30 秒");window.history.go(-1);</script>`
    → 站点明说"隔 N 秒再问"，而我们 1 秒内问了两次（自己打太快）。
  · 2 个站（hodei / kudushu）连站上自己的书名都搜不到 / 整站 403
    → 这才是"真判不了"。

`unknown` 一个词盖住两种病，于是两种都永远治不好：
限速本该"等一会儿再问"，判不了本该"够了就撤"。这份测试钉住四条：
  1. 限速页必须被认出来（`throttle_wait`），不能当成"请求失败"
  2. 每轮都撞限速 → `judge_by_control` 回 `throttled`，**不是** `unknown`
  3. `throttled` 的站**不许**记进"没结论"的计数（那是我们打太快，不是站的错）
  4. 连续 `_REVERIFY_MISS_MAX` 夜拿不到结论 → 撤模板并记进判死账（有终点）

用法：python tools/test_reverify.py
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMPDIR = Path(tempfile.mkdtemp(prefix="novel-reverify-test-"))
os.environ["NOVEL_REGISTRY"] = str(_TMPDIR / "registry.json")

from app import discovery as D  # noqa: E402
from app import registry as R  # noqa: E402
from app import sitelearn as SL  # noqa: E402

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


THROTTLE_HTML = '<script>alert("搜索间隔: 30 秒");window.history.go(-1);</script>'


def main() -> int:
    print("—— ① 限速页必须被认出来（否则永远被当成「请求失败」） ——")
    check("★ 线上原文（59 字节）认出 30 秒",
          SL.throttle_wait(THROTTLE_HTML) == 30, str(SL.throttle_wait(THROTTLE_HTML)))
    check("同一句换成 10 秒也认",
          SL.throttle_wait('<script>alert("搜索间隔: 10 秒");window.history.go(-1);</script>') == 10)
    check("「请 5 秒后再试」也认", SL.throttle_wait("请 5 秒后再试") == 5)
    check("反向：正常结果页不许被判成限速",
          SL.throttle_wait("<html>" + "书" * 800 + "</html>") == 0)
    check("反向：长页面里偶然出现「搜索间隔」不算（限速页都很短）",
          SL.throttle_wait("<html>" + "搜 索 间 隔 : 3 0 秒" * 400 + "</html>") == 0)
    check("反向：空串不算限速", SL.throttle_wait("") == 0)

    print("\n—— ② 每轮都撞限速 → throttled（不是 unknown） ——")
    real_state = SL._fetch_hits_state

    def _all_busy(*a, **kw):        # noqa: ANN002
        return 0, set(), "busy", 30

    SL._fetch_hits_state = _all_busy
    try:
        v = SL.judge_by_control("tpl", "h", urls={"a", "b", "c"}, hits=3,
                                rounds=2, busy_wait=0)
        check("★ 每轮都被限速挡住 → 结论是 throttled", v == "throttled", v)
        v2 = SL.judge_by_control("tpl", "h", urls={"a", "b", "c"}, hits=3,
                                 rounds=2, busy_wait=0.001)
        check("★ 等不起（wait>busy_wait）照样是 throttled，不许硬睡",
              v2 == "throttled", v2)
    finally:
        SL._fetch_hits_state = real_state

    def _ctl_empty(*a, **kw):       # noqa: ANN002
        return 0, set(), "empty", 0

    SL._fetch_hits_state = _ctl_empty
    try:
        v = SL.judge_by_control("tpl", "h", urls={"a", "b", "c"}, hits=3,
                                rounds=2, busy_wait=0)
        check("★ 反向：控制词**成功但 0 条** → 判真（限速的修法不许污染判真）",
              v == "real", v)
    finally:
        SL._fetch_hits_state = real_state

    def _ctl_err(*a, **kw):         # noqa: ANN002
        return 0, set(), "error", 0

    SL._fetch_hits_state = _ctl_err
    try:
        v = SL.judge_by_control("tpl", "h", urls={"a", "b", "c"}, hits=3,
                                rounds=2, busy_wait=0)
        check("反向：网络层失败仍然是 unknown（那是真的什么都没说明）",
              v == "unknown", v)
    finally:
        SL._fetch_hits_state = real_state

    print("\n—— ③「没结论」要有终点：连续 3 夜就撤模板 ——")
    # 三个站：A 每次都判不了、B 每次都被限速、C 每次都判真
    for h in ("miss.example.com", "busy.example.com", "real.example.com"):
        R.note_site(h, name=h)
        R.note_book(f"https://{h}/book/1/", host=h, title="某本书", chapters=8)
        check(f"前提：{h} 有模板", R.note_search_tpl(h, "/?s={kw}"))
    import time as _t
    # 让判死账里没有它们的记录（干净起点）
    R.flush()

    calls = {"n": 0}

    def _probe(tpl, host, keyword, **kw):    # noqa: ANN001,ANN003
        return 5, {f"https://{host}/{i}" for i in range(5)}, "ok", 0

    def _judge(tpl, host, **kw):             # noqa: ANN001,ANN003
        calls["n"] += 1
        if host == "real.example.com":
            return "real"
        if host == "busy.example.com":
            return "throttled"
        return "unknown"

    real_probe, real_judge = SL._fetch_hits_state, SL.judge_by_control
    SL._fetch_hits_state = _probe
    SL.judge_by_control = _judge
    _lg = logging.getLogger("novel.discovery")
    _old_lvl = _lg.level
    _lg.setLevel(logging.INFO)
    try:
        first = D.reverify_sites(["miss.example.com"], budget=60)
        check("第 1 夜：没结论（不撤）",
              first["unjudged"] == 1 and first["dropped"] == 0, str(first))
        check("★ 第 1 夜就把「连续几夜」写下来（否则永远数不出来）",
              int(R.known_site("miss.example.com").get("reverify_miss") or 0) == 1,
              str(R.known_site("miss.example.com").get("reverify_miss")))
        D.reverify_sites(["miss.example.com"], budget=60)
        check("第 2 夜：仍然没结论，还留着",
              int(R.known_site("miss.example.com").get("reverify_miss") or 0) == 2
              and R.has_search_tpl(R.known_site("miss.example.com")))
        third = D.reverify_sites(["miss.example.com"], budget=60)
        _s = R.known_site("miss.example.com")
        check("★ 第 3 夜：撤模板（这就是终点）",
              third["dropped"] == 1 and third["missed_dropped"] == 1,
              str(third))
        check("★ 模板真的没了", not R.has_search_tpl(_s), str(_s.get("search_tpl")))
        check("★ 而且记进了判死账（复盘看得见条数）",
              R.tpl_dead_count(_s, "miss.example.com") >= 1,
              f"tpl_dead={R.tpl_dead_count(_s, 'miss.example.com')}")
        # 一次判死还不够拉黑（那是既有设计：一次失误不许永久钉死），
        # 但**第二轮**判不了就必须合闸 —— 否则"每夜查一遍"只是从
        # 「每夜问 4 个请求」变成「每夜问 4 个请求 + 每 3 夜重学一遍」。
        check("前提：判死一次之后还允许它再学一次",
              R.should_try_learn("miss.example.com"))
        R.note_search_tpl("miss.example.com", "/?s={kw}")
        for _ in range(D._REVERIFY_MISS_MAX):
            D.reverify_sites(["miss.example.com"], budget=60)
        _s = R.known_site("miss.example.com")
        check("★ 第二轮仍是没结论 → 判死两次，闸门合上（7 天内不再花预算）",
              R.tpl_dead_count(_s, "miss.example.com") >= R.TPL_DEAD_MAX
              and not R.should_try_learn("miss.example.com"),
              f"tpl_dead={R.tpl_dead_count(_s, 'miss.example.com')}")
        check("它从复核队列里消失（不用再每夜查它）",
              "miss.example.com" not in R.reverify_candidates())

        # B：每夜都撞限速 —— 不记 miss、不撤模板、留在队列等下一夜
        b1 = D.reverify_sites(["busy.example.com"], budget=60)
        _b = R.known_site("busy.example.com")
        check("★ 限速的站单独计数（throttled=1，没结论=0）",
              b1["throttled"] == 1 and b1["unjudged"] == 0, str(b1))
        check("★ 限速**不许**记进「连续没结论」的账（这是我们打太快）",
              int(_b.get("reverify_miss") or 0) == 0,
              str(_b.get("reverify_miss")))
        for _ in range(3):
            D.reverify_sites(["busy.example.com"], budget=60)
        _b = R.known_site("busy.example.com")
        check("★ 连撞四夜也不撤模板（不是站的错，等得起就还有结论）",
              R.has_search_tpl(_b) and int(_b.get("reverify_miss") or 0) == 0,
              f"tpl={_b.get('search_tpl')} miss={_b.get('reverify_miss')}")
        check("它还留在复核队列里", "busy.example.com" in R.reverify_candidates())

        # C：判真 → 盖章免检
        c1 = D.reverify_sites(["real.example.com"], budget=60)
        _c = R.known_site("real.example.com")
        check("判真：留下并盖章", c1["kept"] == 1 and
              int(_c.get("search_ver") or 0) >= R.LEARN_VER, str(c1))
        check("判真之后不再进复核队列",
              "real.example.com" not in R.reverify_candidates())
    finally:
        SL._fetch_hits_state, SL.judge_by_control = real_probe, real_judge
        _lg.setLevel(_old_lvl)

    print("\n—— ④ 声明 30 秒的站：**不等**（等过 30 秒根本不放行） ——")
    # 实测（2026-11-12 深夜）：350.ooo 隔 30.5 秒再问仍然回同一句限速页，
    # 而且一个站吃掉 136.9 秒、把同批另外 2 个站挤出预算。
    # 所以 30 秒档一律记 throttled、不睡；这里钉住"请求数有界"而不是耗时
    # （耗时随负载漂，不是判据）。
    h30 = "slow30.example.com"
    R.note_site(h30, name=h30)
    R.note_book(f"https://{h30}/book/1/", host=h30, title="某本书", chapters=8)
    R.note_search_tpl(h30, "/?s={kw}")
    seen = {"n": 0}

    def _probe30(tpl, host, keyword, **kw):   # noqa: ANN001,ANN003
        seen["n"] += 1
        if kw.get("dummy") or keyword == SL.CONTROL_KW:
            return 0, set(), "busy", 30
        return 5, {f"https://{host}/{i}" for i in range(5)}, "ok", 0

    real_p2 = SL._fetch_hits_state
    SL._fetch_hits_state = _probe30
    try:
        r30 = D.reverify_sites([h30], budget=100)
    finally:
        SL._fetch_hits_state = real_p2
    check("★ 30 秒档记 throttled（不是没结论）",
          r30["throttled"] == 1 and r30["unjudged"] == 0, str(r30))
    check("★ 一个站最多 3 个请求（1 次真探测 + 2 轮控制），不许在那里干等",
          seen["n"] <= 3, f"请求数={seen['n']}")
    check("★ 也不许记进「连续没结论」的账",
          int(R.known_site(h30).get("reverify_miss") or 0) == 0)
    check("模板留着（限速不是撤模板的理由）", R.has_search_tpl(R.known_site(h30)))

    print("\n—— ④b 反向：判真必须清「连续没结论」的旧账 ——")
    h = "flip.example.com"
    R.note_site(h, name=h)
    R.note_book(f"https://{h}/book/1/", host=h, title="某本书", chapters=8)
    R.note_search_tpl(h, "/?s={kw}")
    R.note_reverify_miss(h)
    R.note_reverify_miss(h)
    check("前提：已经攒了两次没结论",
          int(R.known_site(h).get("reverify_miss") or 0) == 2)
    R.clear_reverify_miss(h)
    check("★ 拿到结论后旧账清零（否则下一夜再来一次就被误撤）",
          int(R.known_site(h).get("reverify_miss") or 0) == 0)

    print(f"\n{'✅ 全部通过' if not BAD else '❌ 有失败'}（{OK} 通过 / {BAD} 失败）")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
