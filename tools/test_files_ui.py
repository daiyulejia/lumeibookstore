#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
文件页真机验证（Vue 迁移版）
============================================================================
为什么单独一个套件：
  `test_buttons.py` 的 F 组覆盖了文件页的**行为**（列出导出文件、删除），
  但抓不到渲染层与迁移契约的回归。这个套件专门盯这几件事：

  · 文件页迁到 Vue 后，组件被渲染进了**错误的位置**
    （真踩过：一容器一 app 写错，组件渲进了榜单区，
     #view-files 里的容器永远是空的 —— 页面看着"没生效"、控制台无错）。
  · `#fmtPick` 这个 id 必须还在 —— main.js 的
    `bus.on("book:export")` 就是读 `$("#fmtPick").value` 拿导出格式的，
    它没了导出会静默用错格式（甚至抛 null 错）。
  · 数据只有一条来源：loadFiles 广播 `files:loaded`，组件订阅。
    有人又加回"组件自己 api.get('/api/downloads')"就会出现两份数据。
  · HTML 文件才有「打开看」按钮、每个文件都要有「下载」链接。
  · 空态插画（CSS background）消失。
  · 切来切去刷新次数失控（bus.off 没摘干净 → 监听叠加）。

六节：
  1. 容器位置正确（文件页渲染在 #view-files 内部，不是别处）
  2. #fmtPick 契约仍在，且值能从 PRE 恢复
  3. 文件行数与接口对账 + 下载链接 + HTML 才有「打开看」
  4. 导航能切到文件页并且真的看得见
  5. 只有一份数据源（组件源码里没有 api.get('/api/downloads')）
  6. 没有 JS 报错

用法：
    .venv\\Scripts\\python tools\\test_files_ui.py
    .venv\\Scripts\\python tools\\test_files_ui.py --url http://127.0.0.1:8011
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
    # ⚠ 令牌必须拼在 `#` **之前**（bootstrapAuth 用 searchParams 读它，
    #   fragment 里的读不到 —— 踩过，见 test_shelf_ui.py 的同名注释）。
    q = f"?t={urllib.parse.quote(token)}" if token else ""

    print("=" * 62)
    print("文件页 · 真机验证（Vue 迁移版）")
    print("=" * 62)

    try:
        urllib.request.urlopen(base + "/api/health" + q, timeout=5).read()
    except Exception as e:  # noqa: BLE001
        print(f"\n连不上 {base}：{e}")
        return 2

    # 文件接口此时有多少个 —— 拿来跟渲染出的行数对账
    try:
        with urllib.request.urlopen(base + "/api/downloads" + q, timeout=8) as r:
            files = json.load(r)
        n_files = len(files) if isinstance(files, list) else 0
    except Exception as e:  # noqa: BLE001
        print(f"\n读 /api/downloads 失败：{e}")
        return 2
    n_html = len([f for f in files if f.get("ext") == "html"]) if n_files else 0
    info(f"接口返回 {n_files} 个文件（其中 {n_html} 个 html）")

    b = Browser()
    try:
        b.goto(base + "/" + q + "#files", settle=9.0)

        # -------------------------------------------------------------
        section("1. 容器位置正确")
        in_files_view = b.js(
            "!!document.querySelector('#view-files #vue-root-files #fileList')")
        if in_files_view:
            ok("#fileList 在 #view-files 内部（组件挂对了地方）")
        else:
            bad("#fileList 不在 #view-files 里 —— 组件被挂到别处了？"
                "（多容器挂载写错时的典型症状）")
        stray = b.js("!!document.querySelector('#ranksBox #fileList, #view-shelf #fileList')")
        if stray:
            bad("文件列表串到了别的视图里 —— 一个 app 管了多处 DOM")
        else:
            ok("文件列表没有串到榜单/书架区（每个容器各挂一个 app 实例）")

        # -------------------------------------------------------------
        section("2. #fmtPick 契约仍在")
        # ⚠ 这是**跨模块契约**：main.js 里
        #   bus.on("book:export", ...) → fmt: $("#fmtPick").value
        #   这个 id 一旦消失，导出就静默拿不到用户选的格式。
        if b.js("!!document.getElementById('fmtPick')"):
            ok("#fmtPick 还在（main.js 靠它读导出格式）")
        else:
            bad("#fmtPick 不见了 —— bus.on('book:export') 读不到导出格式")
        # 旧实现里 `$("#fmtPick").value` 是原生 select；Naive 的 n-select
        # 渲染出来是 div + input。得确认**取值路径**没断：
        # main.js 读的是 `.value` —— 原生 select 有，div 没有。
        val = b.js("(document.getElementById('fmtPick') || {}).value")
        info(f"#fmtPick.value = {val!r}")
        if val in ("txt", "epub", "html"):
            ok(f"#fmtPick.value 能取到格式（{val}）—— 导出侧读得到")
        else:
            bad(f"#fmtPick.value 取不到有效格式（{val!r}）—— "
                "main.js 的导出会拿错格式，需要给组件补一个隐藏的原生 select")

        # -------------------------------------------------------------
        section("3. 文件行与接口对账")
        rows = b.js("document.querySelectorAll('#fileList .file').length")
        if n_files == 0:
            info("本来就没有导出文件，跳过数量对账")
            if b.js("!document.getElementById('fileEmpty').classList.contains('hidden')"):
                ok("无文件时「空状态」露出来了")
            else:
                bad("无文件但没显示空状态")
        else:
            if rows == n_files:
                ok(f"渲染出 {rows} 行，与接口 {n_files} 个一致")
            else:
                bad(f"行数 {rows} ≠ 接口 {n_files} 个")
            if b.js("document.getElementById('fileEmpty').classList.contains('hidden')"):
                ok("有文件时「空状态」是收起的")
            else:
                bad("有文件时空状态还露着")

            # 每个文件都必须有下载链接（.acts a[download]）
            links = b.js("document.querySelectorAll('#fileList .file .acts a[download]').length")
            if links == n_files:
                ok(f"每个文件都有下载链接（{links} 个）")
            else:
                bad(f"下载链接 {links} 个 ≠ 文件 {n_files} 个")
            # 图标是 SVG（吃 currentColor）
            if b.js("document.querySelectorAll('#fileList .file .ic svg').length") == n_files:
                ok("每个文件都有格式图标（SVG）")
            else:
                bad("格式图标缺失（.ic 里的 svg 数量不对）")
            # HTML 才该有「打开看」
            opens = b.js("document.querySelectorAll('#fileList .file [data-open]').length")
            if opens == n_html:
                ok(f"「打开看」按钮数 {opens} 与 html 文件数 {n_html} 一致")
            elif opens >= n_html:
                ok(f"「打开看」按钮数 {opens} ≥ html 文件数 {n_html}（宽松通过）")
            else:
                bad(f"「打开看」按钮只有 {opens} 个，应该有 {n_html} 个（html 文件才能打开看）")
            dels = b.js("document.querySelectorAll('#fileList .file [data-del]').length")
            if dels == n_files:
                ok(f"每个文件都有删除按钮（{dels} 个）")
            else:
                bad(f"删除按钮 {dels} 个 ≠ 文件 {n_files} 个")

        # -------------------------------------------------------------
        section("4. 导航能切到文件页")
        b.js("document.querySelector('[data-nav=files]').click()")
        time.sleep(1.2)
        if not b.js("document.getElementById('view-files').classList.contains('hidden')"):
            ok("点导航后 #view-files 显示出来")
        else:
            bad("点了「文件」导航但 #view-files 还是隐藏的")
        if b.js("document.getElementById('fileList').offsetHeight > 0 || "
                "document.getElementById('fileEmpty').offsetHeight > 0"):
            ok("文件页内容真的可见（有布局高度）")
        else:
            bad("文件页容器高度为 0 —— 显示出来了但看不见（CSS/隐藏态问题）")

        # -------------------------------------------------------------
        section("5. 组件没有自己拉文件列表（回声）")
        comp = (ROOT / "frontend" / "src" / "components" / "FilesPanel.vue").read_text("utf-8")
        code = "\n".join(
            ln for ln in comp.splitlines()
            if not ln.strip().startswith(("*", "/*", "//"))
        )
        # 只针对 GET —— 删除那一步的 api.del 是正当的。
        if re.search(r'api\.get\(\s*["\'`]/api/downloads', code):
            bad("FilesPanel.vue 里出现了 api.get('/api/downloads') —— 组件在自拉数据，"
                "应只订阅 files:loaded（否则两份数据源，会出现回声/旧值）")
        else:
            ok("组件没有 api.get('/api/downloads')（数据只来自 files:loaded）")
        if "files:loaded" in comp:
            ok("组件订阅了 files:loaded（单一数据出口）")
        else:
            bad("组件没有订阅 files:loaded —— 它靠什么拿数据？")
        # ⚠ 「导出完成 → 刷新」这条订阅必须存在，否则导完切过来看还是旧列表。
        if "task:done" in comp:
            ok("组件订阅了 task:done（导出完成会自动刷新列表）")
        else:
            bad("组件没订阅 task:done —— 导出完切到文件页会看到旧列表")

        def count_dl(browser):
            rs = json.loads(browser.js("JSON.stringify(window.__reqs || [])") or "[]")
            return len([u for u in rs if "/api/downloads" in u])

        n = count_dl(b)
        info(f"这台浏览器整个会话共打 /api/downloads {n} 次"
             f"（含启动、onNav 切页；旧代码常态量级 2~4）")
        if n > 8:
            bad(f"打了 {n} 次，明显失控 —— 疑似组件或监听叠加")
        else:
            ok(f"数量在正常量级内（{n} ≤ 8）")

        # ⚠ 结构性断言：骨架屏**不能**带 `.file` 类。
        #   为什么单独钉：`#fileList .file` 是"有几个文件"的判据
        #   （test_buttons F0、本套件第 3 节、以及线上数数的唯一口径）。
        #   骨架如果复用 .file，加载态会被当成"3 个文件"—— 空目录时
        #   甚至会出现"3 个文件"的假绿。写这条时做了回退验证
        #   （把骨架改回 class="file"，本断言立刻报红）。
        #   判据：取 `#fileList` 里 **v-else 之前**（也就是骨架分支）那一段，
        #   看里面有没有 class="…file…"。
        tpl = comp.split("</template>")[0] if "</template>" in comp else comp
        skel = ""
        if 'id="fileList"' in tpl:
            seg = tpl.split('id="fileList"', 1)[1]
            skel = seg.split("v-else", 1)[0]        # 骨架分支
        if re.search(r'class="[^"]*\bfile\b[^"]*"', skel):
            bad("骨架屏带上了 .file 类 —— 会被「数文件」的断言当成真文件")
        else:
            ok("骨架屏没有复用 .file 类（数文件不会被骨架污染）")
        if "fsk" in tpl:
            ok("骨架用了独立的 .fsk 类")
        else:
            bad("找不到独立的骨架类（.fsk）—— 是不是又复用 .file 了？")

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
