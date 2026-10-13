#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
发现页结果区真机验证（Vue 迁移版）
============================================================================
为什么单独一个套件：
  `test_buttons.py` 的 A/B 组覆盖了搜索**行为**（能搜出结果、能切筛选、
  点卡片有反应），`test_concurrency.py` 钉了竞态。但它们抓不到"结果区迁到
  Vue 之后"这一类回归：

  · 结果区（#results / #statbar / #filters / #homeEmpty / #confirmBox）
    渲染进了**错误的位置**，或者根本没挂上 —— 页面看着"没生效"、控制台无错。
  · `#q` / `#btnSearch` 这两个**没迁**的跨模块契约被顺手搬进了 Vue，
    于是 main.js 的 `$("#q")`、深链 searchFromHash、test_buttons A 组全断。
  · 搜索结果渲染成空 —— 事件桥（discover:state）没接上，
    表现是"搜索跑完了但一条都不显示"，不报错。
  · 「只看能读的」开关与来源 chips 走岔路：Vue 里改了状态但旧代码不知道，
    或者反过来 —— 表现是"切了没反应"。
  · 首页空态与结果列表**同时显示**（空态从 #results 内部搬到独立元素后，
    显隐条件要显式列全，漏一个就会出现双份）。
  · 骨架屏 `.skl` 消失 → test_buttons 判"还在搜"的判据失效。

六节：
  1. 容器位置正确（结果区在 #view-home 内部、不串到榜单/书架）
  2. 未迁契约仍在（#q / #btnSearch 是原生元素、且在 Vue 容器之外）
  3. 搜一本书：结果卡真的渲染出来 + 卡片结构完整
  4. 「只看能读的」开关与「清空结果」真的生效（且与旧状态机同步）
  5. 首页空态与结果列表互斥（不同时显示）
  6. 没有 JS 报错

用法：
    .venv\\Scripts\\python tools\\test_discover_ui.py
    .venv\\Scripts\\python tools\\test_discover_ui.py --url http://127.0.0.1:8011
============================================================================
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from test_auth_race import Browser, local_token  # noqa: E402

ok_n = 0
bad_n = 0


def ok(m: str) -> None:
    global ok_n
    ok_n += 1
    print(f"  ✓ {m}")


def bad(m: str) -> None:
    global bad_n
    bad_n += 1
    print(f"  ✗ {m}")


def info(m: str) -> None:
    print(f"     {m}")


def section(t: str) -> None:
    print(f"\n── {t} " + "─" * max(0, 56 - len(t)))


def poll(browser, expr, timeout=12.0, every=0.4):
    """轮询一个 JS 表达式，返回第一个为真时的值（否则返回最后一个值）。

    ⚠ 不用 test_buttons 里的 `t.wait` —— 那是另一个 Tab 包装类的接口，
      这里用的是 test_auth_race 的 Browser（只有 .js）。自己写一个更省事，
      也避免为了一个辅助方法去改公共类。
    """
    end = time.time() + timeout
    val = None
    while time.time() < end:
        val = browser.js(expr)
        if val:
            return val
        time.sleep(every)
    return val


# 用一个大概率能在自有源里命中的书名（三体在 test_buttons B 组里也用）
KW = "三体"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--token", default="")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    token = a.token or local_token()
    q = f"?t={urllib.parse.quote(token)}" if token else ""

    print("=" * 62)
    print("发现页结果区 · 真机验证（Vue 迁移版）")
    print("=" * 62)

    try:
        urllib.request.urlopen(base + "/api/health" + q, timeout=5).read()
    except Exception as e:  # noqa: BLE001
        print(f"\n连不上 {base}：{e}")
        return 2

    b = Browser()
    try:
        b.goto(base + "/" + q, settle=10.0)

        # -------------------------------------------------------------
        section("1. 容器位置正确")
        if b.js("!!document.querySelector('#view-home [data-vue-discover]')"):
            ok("[data-vue-discover] 在 #view-home 内部（组件挂对了地方）")
        else:
            bad("[data-vue-discover] 不在 #view-home 里 —— 组件被挂到别处了？")

        # 结果区必须**在** Vue 容器里（否则就是旧元素残留 + 双份）
        if b.js("!!document.querySelector('[data-vue-discover] #results')"):
            ok("#results 由 Vue 渲染（在 [data-vue-discover] 内部）")
        else:
            bad("#results 不在 Vue 容器里 —— 结果区没迁过来 / 渲染到了别处")

        stray = b.js("!!document.querySelector('#ranksBox #results, "
                     "#view-shelf #results, #view-files #results')")
        if stray:
            bad("结果区串到了别的视图里 —— 一个 app 管了多处 DOM")
        else:
            ok("结果区没有串到榜单/书架/文件区")

        # -------------------------------------------------------------
        section("2. 未迁契约仍在（#q / #btnSearch）")
        # ⚠ 这两个是**故意留在静态 HTML 里**的：main.js 的 `$("#q")`、
        #   test_buttons 的 A 组、深链 searchFromHash 全按原生元素找它们。
        #   一旦被搬进 Vue 容器，"是不是原生元素"和"在不在容器外"都要验。
        if b.js("!!document.getElementById('q') && !!document.getElementById('btnSearch')"):
            ok("#q / #btnSearch 都还在")
        else:
            bad("#q 或 #btnSearch 不见了 —— 搜索入口断了")
        if b.js("document.getElementById('q').tagName === 'INPUT'"):
            ok("#q 仍是原生 <input>（.value 读写路径没变）")
        else:
            bad("#q 不再是原生 input —— main.js 的 $('#q').value 会失效")
        inside_vue = b.js(
            "!!document.querySelector('[data-vue-discover] #q')")
        if inside_vue:
            bad("#q 被放进了 Vue 容器里 —— 它与 Vue 渲染耦合了，"
                "旧代码/测试按原生元素找它会不稳")
        else:
            ok("#q 在 Vue 容器之外（未被 Vue 接管的静态 hero 里）")

        # -------------------------------------------------------------
        section("3. 搜一本书：结果卡真的渲染出来")
        b.js(f"document.getElementById('q').value = {json.dumps(KW)}")
        b.js("document.getElementById('btnSearch').click()")

        # 等骨架出现（证明搜索真的发起 + 骨架由 Vue 渲染）
        skel = poll(b, "document.querySelectorAll('#results .skl').length", timeout=12)
        if skel and int(skel) > 0:
            ok(f"搜索发起后出现骨架（#results .skl = {skel}）—— Vue 渲染的加载态在")
        else:
            info("没等到骨架（可能太快已经出结果），继续看结果卡")

        # 等结果卡（或有明确结论的空态）
        n_book = 0
        for _ in range(80):   # 最多 40s
            n_book = b.js("document.querySelectorAll('#results .book').length") or 0
            if n_book:
                break
            # 已经出空态也停（这本搜不到 —— 断言按"渲染链路通"来判，不卡死在数量）
            if b.js("!document.querySelector('#homeEmpty').classList.contains('hidden') "
                    "&& !document.querySelector('#results .skl')"):
                break
            time.sleep(0.5)

        stat = b.js("(document.getElementById('statbar')||{}).textContent || ''")
        info(f"状态栏：{stat.strip()[:80]!r}")

        if n_book:
            ok(f"搜索结果渲染出 {n_book} 张卡片（Vue 结果区链路通）")
            # 卡片结构：封面 / 标题 / 操作按钮 / 来源行
            has_cov = b.js("!!document.querySelector('#results .book .cover')")
            has_ttl = b.js("!!document.querySelector('#results .book h3')")
            has_act = b.js("!!document.querySelector('#results .book [data-act=\"read\"]')")
            has_row = b.js("document.querySelectorAll('#results .book .srow').length")
            if has_cov:
                ok("卡片有封面（.cover）")
            else:
                bad("卡片没有封面 —— BookCover 没渲进去")
            if has_ttl:
                ok("卡片有标题（h3）")
            else:
                bad("卡片没有标题")
            if has_act:
                ok("卡片有「开始阅读」按钮（data-act=read）")
            else:
                bad("卡片没有阅读按钮 —— 点了没法读")
            if has_row and int(has_row) > 0:
                ok(f"卡片有来源行（.srow = {has_row}）")
            else:
                bad("卡片没有来源行 —— 来源列表没渲染")
            # data-gk 身份键必须还在（点错书的元凶见 discover.js 的长注释）
            if b.js("!!document.querySelector('#results .book[data-gk]')"):
                ok("卡片带 data-gk 身份键（点阅读不会串到别的书）")
            else:
                bad("卡片缺 data-gk —— 点「开始阅读」可能开到别的书")
        else:
            # 没有卡片也不算"渲染层坏了" —— 但要能给出一致的说法：
            # 要么有结果区空态，要么状态栏有"看遍 N 个来源"的统计。
            if "来源" in stat or "本" in stat:
                info("这本没搜到卡片，但状态栏有统计 —— 渲染链路仍是通的")
                ok("搜索流程走完（状态栏有统计文案）")
            else:
                bad(f"搜索后既没卡片也没统计文案（statbar={stat.strip()[:40]!r}）—— "
                    "结果区链路可能断了")

        # -------------------------------------------------------------
        section("4. 「只看能读的」与「清空结果」真的生效")
        had = b.js("document.getElementById('onlyOk').checked")
        b.js("document.getElementById('onlyOk').click()")
        time.sleep(0.4)
        now = b.js("document.getElementById('onlyOk').checked")
        if had != now:
            ok(f"「只看能读的」开关能切（{had} → {now}）")
        else:
            bad("点了「只看能读的」但 checked 没变 —— 开关与渲染脱节")
        n_all = b.js("document.querySelectorAll('#results .book').length") or 0
        b.js("document.getElementById('onlyOk').click()")   # 还原
        time.sleep(0.4)
        n_restore = b.js("document.querySelectorAll('#results .book').length") or 0
        info(f"切换前 {n_all} 张 / 还原后 {n_restore} 张卡片")
        if b.js("document.getElementById('onlyOk').checked") == had:
            ok("能切回来（状态与 PRE 同步）")
        else:
            bad("切不回来 —— 开关状态没还原")

        # 清空结果：结果卡消失 + 首屏空态回来
        b.js("document.getElementById('btnClearSearch').click()")
        time.sleep(0.6)
        n_after = b.js("document.querySelectorAll('#results .book').length") or 0
        if n_after == 0:
            ok("「清空结果」后结果卡清空了")
        else:
            bad(f"点了「清空结果」还剩 {n_after} 张卡片")
        if b.js("document.getElementById('q').value === ''"):
            ok("「清空结果」顺带清空了搜索框（与旧行为一致）")
        else:
            bad("「清空结果」没清搜索框 —— 与旧行为不一致")

        # -------------------------------------------------------------
        section("5. 首页空态与结果列表互斥")
        # ⚠ 这个断言必须**在列表非空时**检查。
        #   写第一版时放在了「清空结果」之后 —— 那时 books=0、空态本就该显示，
        #   "互斥"永远成立，于是把 `showHomeEmpty 恒为 true` 这种缺陷放过去了
        #   （做回退验证时发现的：注入"空态永远显示"竟然全绿）。
        #   所以先重新搜一次，在**有结果**的那一刻验互斥。
        b.js(f"document.getElementById('q').value = {json.dumps(KW)}")
        b.js("document.getElementById('btnSearch').click()")
        n_book2 = 0
        for _ in range(80):
            n_book2 = b.js("document.querySelectorAll('#results .book').length") or 0
            if n_book2:
                break
            time.sleep(0.5)
        if n_book2:
            empty_vis = b.js("!document.getElementById('homeEmpty').classList.contains('hidden')")
            if empty_vis:
                bad("有结果卡时空态**还显示着** —— 空态显隐条件漏了分支"
                    "（结果区与空态同时出现）")
            else:
                ok(f"有 {n_book2} 张结果卡时空态收起了（互斥成立）")
        else:
            info("第二遍没搜到卡片，互斥断言退化为「空态该显示」")
            empty_vis = b.js("!document.getElementById('homeEmpty').classList.contains('hidden')")
            if empty_vis:
                ok("无结果时空态显示（符合预期）")
            else:
                bad("无结果但空态也没显示 —— 首屏会一片空白")

        # 反向：清空后空态必须回来（两个方向都验，避免"恒 false"混过去）
        b.js("document.getElementById('btnClearSearch').click()")
        time.sleep(0.6)
        if b.js("!document.getElementById('homeEmpty').classList.contains('hidden')"):
            ok("清空后空态回来了（双向都成立）")
        else:
            bad("清空后空态没回来 —— showHomeEmpty 是不是恒 false？")

        # 骨架类不能被结果卡复用（test_buttons 用 .skl 判"还在搜"）
        comp = (ROOT / "frontend" / "src" / "components" / "DiscoverPanel.vue").read_text("utf-8")
        tpl = comp.split("</template>")[0] if "</template>" in comp else comp
        # 骨架必须在 `#results` 里、且用 .skl
        if 'class="skl"' in tpl or 'class="skl ' in tpl:
            ok("骨架用 .skl 类（test_buttons 的「还在搜」判据没失效）")
        else:
            bad("找不到 .skl 骨架类 —— test_buttons 判定「还在搜」会失效")
        # 结构断言：组件里不能出现 `innerHTML`（那正是要迁走的东西）。
        # ⚠ 剥注释要**真的剥块注释**，不能只按行首过滤 ——
        #   DiscoverPanel 的注释里到处在说"旧代码用 innerHTML 拼字符串"，
        #   按行首过滤会把这些说明文字当成代码（写这条时踩到了，
        #   20 项里唯一那一红就是它）。
        code = comp
        code = re.sub(r"<!--.*?-->", "", code, flags=re.S)      # HTML 注释
        code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)        # 块注释
        code = re.sub(r"//[^\n]*", "", code)                     # 行注释
        if "innerHTML" in code:
            bad("DiscoverPanel.vue 里出现了 innerHTML —— 组件不该再拼 HTML")
        else:
            ok("组件（剥掉注释后）没有 innerHTML —— 渲染交给声明式模板")

        # -------------------------------------------------------------
        section("6. 没有 JS 报错")
        errs = json.loads(b.js("""
          JSON.stringify((window.__lumeiErrors || []).map(String))
        """) or "[]")
        if errs:
            bad(f"页面记到 {len(errs)} 条错误：{errs[:2]}")
        else:
            ok("页面没有记到 JS 错误")
    finally:
        b.close()

    print("\n" + "=" * 62)
    if bad_n == 0:
        print(f"通过 {ok_n} · 失败 0\n✓ 全部通过")
    else:
        print(f"通过 {ok_n} · 失败 {bad_n}\n✗ 有 {bad_n} 项没过")
    print("=" * 62)
    return 1 if bad_n else 0


if __name__ == "__main__":
    sys.exit(main())
