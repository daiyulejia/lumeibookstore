#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
书架页真机验证（Vue 迁移版）
============================================================================
为什么单独一个套件：
  `test_buttons.py` 的 E 组已经覆盖了书架的**行为**（点阅读/缓存/导出/移除），
  但那个套件跑的是"整页交互"视角，抓不到**渲染层**的回归 ——
  比如：

  · 书架迁到 Vue 后，组件被渲染进了**错误的位置**
    （真踩过：一个 App 实例挂到榜单区的 #vue-root 上，于是书架组件
     被渲进了首页榜单区内部，#view-shelf 里的容器永远是空的。
     页面看着"没生效"，控制台一点错都没有 —— 这种只有断言
     「元素在它该在的地方」才能抓到）。
  · 数据只有一条来源：loadShelf 广播 shelf:loaded，组件订阅。
    如果有人又加回"组件自己 api.get"，就会出现两份数据、
    "缓存跑完可见列表还是旧值"这种回声。
  · 空书架插画（CSS background）消失。
  · bus.off 没摘干净导致切来切去刷新越来越多遍（监听叠加）。

六节：
  1. 容器位置正确（书架渲染在 #view-shelf 内部，不是别处）
  2. 骨架 / 数据：.shelf 数量与接口数量一致，且带 data-id
  3. 卡片内容完整（封面 / 书名 / 作者 / 两条进度条 / 四个按钮）
  4. 导航能切到书架并且真的看得见
  5. 只有一份数据源（window.__shelfReq 计数 === 1）
  6. 没有 JS 报错

用法：
    .venv\\Scripts\\python tools\\test_shelf_ui.py
    .venv\\Scripts\\python tools\\test_shelf_ui.py --url http://127.0.0.1:8011
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--token", default="")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    token = a.token or local_token()
    # ⚠ 令牌必须拼在 `#` **之前**：`bootstrapAuth()` 用
    #   `new URL(href).searchParams.get("t")` 读它，而 `#` 之后的东西
    #   属于 fragment、searchParams 看不到 —— 写成 `/` + `#shelf?t=x`
    #   会静默丢掉令牌，线上直接 401（踩过：整个套件 7 项假红，
    #   查了很久才发现是测试自己把令牌放错了位置）。
    q = f"?t={urllib.parse.quote(token)}" if token else ""

    print("=" * 62)
    print("书架页 · 真机验证（Vue 迁移版）")
    print("=" * 62)

    try:
        urllib.request.urlopen(base + "/api/health" + q, timeout=5).read()
    except Exception as e:  # noqa: BLE001
        print(f"\n连不上 {base}：{e}")
        return 2

    # 书架接口此时有多少本 —— 拿来跟渲染出的卡片数对账
    try:
        with urllib.request.urlopen(base + "/api/library" + q, timeout=8) as r:
            shelf = json.load(r)
        n_books = len(shelf) if isinstance(shelf, list) else 0
    except Exception as e:  # noqa: BLE001
        print(f"\n读 /api/library 失败：{e}")
        return 2
    info(f"接口返回 {n_books} 本书")

    b = Browser()
    try:
        b.goto(base + "/" + q + "#shelf", settle=9.0)

        # -------------------------------------------------------------
        section("1. 容器位置正确")
        in_shelf_view = b.js(
            "!!document.querySelector('#view-shelf #vue-root-shelf #shelfList')")
        if in_shelf_view:
            ok("#shelfList 在 #view-shelf 内部（组件挂对了地方）")
        else:
            bad("#shelfList 不在 #view-shelf 里 —— 组件被挂到别处了？"
                "（多容器挂载写错时的典型症状）")
        # 反向断言：书架**不该**出现在榜单区里
        stray = b.js("!!document.querySelector('#ranksBox #shelfList')")
        if stray:
            bad("书架被渲染进了榜单区内部 —— 一个 app 管了多处 DOM")
        else:
            ok("书架没有串到榜单区（每个容器各挂一个 app 实例）")

        # -------------------------------------------------------------
        section("2. 卡片数量与接口对账")
        cards = b.js("document.querySelectorAll('#shelfList .shelf').length")
        if n_books == 0:
            info("书架本来就是空的，跳过数量对账")
            if b.js("!document.getElementById('shelfEmpty').classList.contains('hidden')"):
                ok("空书架时「空状态」露出来了")
            else:
                bad("空书架但没显示空状态")
        else:
            if cards == n_books:
                ok(f"渲染出 {cards} 张卡片，与接口 {n_books} 本一致")
            else:
                bad(f"卡片数 {cards} ≠ 接口 {n_books} 本")
            if b.js("!!document.querySelector('#shelfList .shelf').dataset.id"):
                ok("卡片带 data-id（点各种操作要靠它定位）")
            else:
                bad("卡片没有 data-id")
            if b.js("document.getElementById('shelfEmpty').classList.contains('hidden')"):
                ok("有书时「空状态」是收起的")
            else:
                bad("有书时空状态还露着")

        # -------------------------------------------------------------
        section("3. 卡片内容完整")
        if n_books:
            if b.js("document.querySelectorAll('#shelfList .cover').length > 0"):
                ok("封面渲染出来了（.cover）")
            else:
                bad("封面没渲染（.cover 一个都没有）")
            if b.js("(document.querySelector('#shelfList .shelf h4')||{}).textContent"):
                ok("书名渲染出来了（<h4>）")
            else:
                bad("书名是空的")
            if b.js("document.querySelectorAll('#shelfList .prog .bar').length >= 2"):
                ok("两条进度条都在（阅读进度 / 缓存进度）")
            else:
                bad("进度条少于两条")
            acts = b.js("document.querySelectorAll('#shelfList .shelf [data-a]').length")
            want = n_books * 4
            if acts >= want:
                ok(f"每本书 4 个操作按钮（共 {acts} 个 ≥ {want}）")
            else:
                bad(f"操作按钮只有 {acts} 个，应该是 {want} 个")
        else:
            info("书架空，跳过内容检查")

        # -------------------------------------------------------------
        section("4. 导航能切到书架")
        b.js("document.querySelector('[data-nav=shelf]').click()")
        time.sleep(1.2)
        if not b.js("document.getElementById('view-shelf').classList.contains('hidden')"):
            ok("点导航后 #view-shelf 显示出来")
        else:
            bad("点了「书架」导航但 #view-shelf 还是隐藏的")
        if b.js("document.getElementById('shelfList').offsetHeight > 0 || "
                "document.getElementById('shelfEmpty').offsetHeight > 0"):
            ok("书架内容真的可见（有布局高度）")
        else:
            bad("书架容器高度为 0 —— 显示出来了但看不见（CSS/隐藏态问题）")

        # -------------------------------------------------------------
        section("5. 组件没有自己拉书架（回声）")
        # 先用**结构性**断言钉死"组件里没有 /api/library"：
        #   数请求次数这条路很难做准 —— /api/library 有好几个正当来源
        #   （启动、onNav、ranks 的星标、shelf:changed 诱发 ranks 再拉），
        #   数量随书架里书的多少变化（线上 9 本比本地 4 本多一次）。
        #   与其猜阈值，不如直接确认"组件源码里没有这个接口"。
        comp = (ROOT / "frontend" / "src" / "components" / "ShelfPanel.vue").read_text("utf-8")
        # 只看**真正会跑的代码**：先剥掉注释（上面那段"为什么不自拉"的
        # 注释里就写着 api.get("/api/library")，不剥会误判成自拉）。
        code = "\n".join(
            ln for ln in comp.splitlines()
            if not ln.strip().startswith(("*", "/*", "//"))
        )
        # 只针对 GET（`api.get`）—— 删除那一步的 `api.del("/api/library/" + id)`
        # 是正当的，不该被判成"自拉数据"。
        if re.search(r'api\.get\(\s*["\'`]/api/library', code):
            bad("ShelfPanel.vue 里出现了 api.get('/api/library') —— 组件在自拉数据，"
                "应只订阅 shelf:loaded（否则两份数据源，会出现回声/旧值）")
        else:
            ok("组件没有 api.get('/api/library')（数据只来自 shelf:loaded）")
        if "shelf:loaded" in comp:
            ok("组件订阅了 shelf:loaded（单一数据出口）")
        else:
            bad("组件没有订阅 shelf:loaded —— 它靠什么拿数据？")

        # 再做一次**运行时**量级检查（只作为粗筛，不作为主判据）。
        # ⚠ 不追求精确计数：这台浏览器前面已经做过"点导航切到书架"
        #   （会触发 onNav → loadShelf），还有 shelf:changed 会诱发
        #   ranks 再拉一次，实际次数随时序/书量浮动（线上观察到 4~5）。
        #   真正钉死"组件不自拉"的是上面那条结构性断言。
        #   这里只拦"明显失控"（比如监听叠加导致每次都多打一轮）。
        def count_lib(browser):
            rs = json.loads(browser.js("JSON.stringify(window.__reqs || [])") or "[]")
            return len([u for u in rs if "/api/library" in u])

        n_home = count_lib(b)
        info(f"这台浏览器整个会话共打 /api/library {n_home} 次"
             f"（含导航切换、shelf:changed 诱发 ranks；旧代码常态量级 2~5）")
        if n_home > 8:
            bad(f"打了 {n_home} 次，明显失控 —— 疑似组件或监听叠加")
        else:
            ok(f"数量在正常量级内（{n_home} ≤ 8）")

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
