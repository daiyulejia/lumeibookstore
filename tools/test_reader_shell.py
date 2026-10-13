#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
阅读器外壳迁移（Vue）真机验证
============================================================================
为什么单独一个套件：
  `test_reader_ui.py` 验的是**行为**（翻页、切模式、偏好持久化、目录增量），
  那些都是"点一下会不会翻"级别的功能断言。它**抓不到迁移本身的回归** ——
  迁移期真正会踩的坑全都发生在"渲染权和布局契约"这一层：

  · 外壳拆成三个容器（`.rd-prog/.rd-top` 在 `.rd-stage` 前、`.rd-bottom`
    在之后），如果某个容器挂错位置，`#reader` 的纵向 flex 顺序就乱了
    —— 顶栏跑到正文下面、底栏跑到正文上面。功能全都在，页面全错。
  · 舞台区（`.rd-stage`）与进度条（`#rdSeek`）**必须留在静态 HTML**：
    前者被 `paginate()` 量尺寸、`buildFlip()` 往 `#rdFlipBook` 建 StPageFlip
    实例；后者绑了 pointerdown/move/up 做跟手拖拽。Vue 一旦接管，
    patch 会重建节点 → 旧引用失效 → **翻页偶发失效、拖拽中途丢手势**
    （偶发、极难查，所以要用断言把它钉死成"永久红"）。
  · 旧代码依赖的 id 一个都不能丢：`renderToc()` 会 `$("#rdTocList").innerHTML=""`、
    `$("#rdTocList").scrollTop=0`、`appendToc()` 会 `insertAdjacentHTML`。
    丢了 id → `$()` 返回 null → 抛错 → 整条目录链静默死掉。
    真踩过：`#rdTitle` 丢了，`openReader()` 在 `renderToc()` 之前就崩了，
    表现是"阅读器打开了但目录永远空、正文不加载"。

七节：
  1. 三个容器各渲各的，且 `#reader` 的子元素顺序正确
  2. 舞台区未被 Vue 接管（`#rdFlipBook` 还在、`[data-vue-rdpanels]` 里
     没有 `.rd-stage`）
  3. 进度条 `#rdSeek` / `#rdSeekF` / `#rdSeekH` 未被 Vue 接管
  4. 旧代码依赖的 id 全部存在（移走一个就报红）
  5. 状态链路：打开后 rdChap/rdSub/rdProg 真的有值（不是初始的 —）
  6. 目录：条目铺出来、点开面板能开、搜索能过滤
  7. 没有 JS 报错

用法：
    .venv\\Scripts\\python tools\\test_reader_shell.py
    .venv\\Scripts\\python tools\\test_reader_shell.py --url http://127.0.0.1:8011
============================================================================
"""
from __future__ import annotations

import argparse
import json
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


def wait_js(b: "Browser", expr: str, timeout: float = 12.0, step: float = 0.25) -> bool:
    """轮询等一个 JS 表达式变真。固定 sleep 会偶发不够（章节要联网抓）。"""
    end = time.time() + timeout
    while time.time() < end:
        if safe_js(b, expr):
            return True
        time.sleep(step)
    return False


def safe_js(b: "Browser", expr: str, default=None):
    """跑一段 JS，**出错不炸**（返回 default）。

    ⚠ 为什么需要它：`Browser.js()` 遇到页面里的 exception 会直接
      `raise RuntimeError`。而这一套件恰好是"测量页面坏没坏"的 ——
      被测对象坏掉时抛异常，会把整个测试脚本崩掉、后面的断言全部看不到，
      反证时就只能看到一条红，定位不到真正坏了几处。
      包一层，把"页面异常"退化成"这个探针拿不到值"。
    """
    try:
        # ⚠ 这里必须调 b.js —— 不能再包一层 safe_js（会无限递归）。
        #   踩过：批量把 `b.js(` 替换成 `safe_js(b, ` 时，
        #   把 safe_js 自己的函数体也换掉了 → 自调用 → RecursionError →
        #   被 except 吞掉 → **所有探针恒返回 None**（23 项全红，
        #   看起来像"页面完全没加载"，其实是测试自己短路了）。
        #   教训：批量替换后要回读被替换区域的上下文，不能只看"替换了几处"。
        return b.js(expr)
    except Exception:  # noqa: BLE001
        return default


def pick_bid(base: str, q: str) -> str:
    """挑一本缓存最多 / 章节最多的书，尽量不依赖网络。"""
    with urllib.request.urlopen(base + "/api/library" + q, timeout=15) as r:
        lib = json.load(r)
    if not isinstance(lib, list) or not lib:
        raise SystemExit("书架是空的，先收一本进去再来跑这个测试")
    lib.sort(key=lambda x: (-(x.get("cached") or 0), -(x.get("total") or 0)))
    return lib[0]["id"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--token", default="")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    token = a.token or local_token()
    q = f"?t={urllib.parse.quote(token)}" if token else ""

    print("=" * 62)
    print("阅读器外壳 · 真机验证（Vue 迁移版）")
    print("=" * 62)

    try:
        urllib.request.urlopen(base + "/api/health" + q, timeout=5).read()
    except Exception as e:  # noqa: BLE001
        print(f"\n连不上 {base}：{e}")
        return 2

    bid = pick_bid(base, q)
    info(f"用书架里的 {bid} 来测")

    b = Browser()
    try:
        b.goto(base + "/" + q + f"#read={bid}", settle=9.0)
        # 等阅读器真的打开 + 章节信息出来（章节要联网抓，必须轮询）
        opened = wait_js(b, "!!document.querySelector('#reader.on')", 20)
        if not opened:
            # ⚠ 这里**不早退**：早退会让"下面所有断言都没机会跑"，
            #   于是反证时只能看到一条红 —— 看不清真正坏了几处。
            #   继续跑，让每节各自报自己的真实状态（该红的都红出来）。
            bad("阅读器没打开（#reader.on 没加上）—— 下面的断言可能连带失败")
        else:
            wait_js(b, "!!document.querySelector('#rdChap')"
                      " && document.querySelector('#rdChap').textContent"
                      " && document.querySelector('#rdChap').textContent.indexOf('章') >= 0", 25)

        # -------------------------------------------------------------
        section("1. 三个容器各渲各的 / #reader 子元素顺序")
        order = safe_js(b, 
            "JSON.stringify([...document.querySelector('#reader').children]"
            ".map(e => (e.getAttribute('data-vue-rdtop') !== null) ? 'rdtop' "
            ": e.classList.contains('rd-stage') ? 'stage' "
            ": e.classList.contains('rd-bottom') ? 'rdbottom' : e.tagName))")
        try:
            seq = json.loads(order or "[]")
        except Exception:  # noqa: BLE001
            seq = []
        want = ["rdtop", "stage", "rdbottom"]
        if seq == want:
            ok("#reader 子元素顺序 = rdtop → stage → rdbottom（纵向 flex 契约）")
        else:
            bad(f"#reader 子元素顺序不对：{seq}（期望 {want}）"
                " —— 外壳挂错位置会让顶栏/底栏跑到正文的另一侧")

        for sel, name in [("[data-vue-rdtop]", "上半"), ("[data-vue-rdpanels]", "面板"),
                          ("[data-vue-rdbottom]", "下半")]:
            n = safe_js(b, f"(document.querySelector('{sel}')||{{}}).children.length") or 0
            if n >= 1:
                ok(f"{name}容器 {sel} 里渲染出了 {n} 个子节点")
            else:
                bad(f"{name}容器 {sel} 是空的 —— Vue 没渲进去"
                    "（挂载点选错 / 组件没被 REGISTRY 命中）")

        # -------------------------------------------------------------
        section("2. 舞台区未被 Vue 接管")
        if safe_js(b, "!!document.querySelector('#rdFlipBook')"):
            ok("#rdFlipBook 还在（StPageFlip 要靠它建实例）")
        else:
            bad("#rdFlipBook 不在 —— 仿真翻页会整个失效")
        if safe_js(b, "!!document.querySelector('.rd-stage #rdScroll') "
                "&& !!document.querySelector('.rd-stage #rdSlideStrip')"):
            ok(".rd-stage 里的滚动/平移容器都在")
        else:
            bad(".rd-stage 里的视图容器丢了")
        if safe_js(b, "!!document.querySelector('.rd-stage #rdToc') "
                "&& !!document.querySelector('.rd-stage #rdSet')"):
            ok("两个面板是 .rd-stage 的子元素（absolute 定位的包含块才对）")
        else:
            bad("两个面板不在 .rd-stage 内 —— absolute 定位会跑到 #reader 上"
                "（表现为面板盖住顶栏/底栏）")

        # -------------------------------------------------------------
        section("3. 进度条未被 Vue 接管")
        for i in ("rdSeek", "rdSeekF", "rdSeekH", "rdTip"):
            if safe_js(b, f"!!document.getElementById('{i}')"):
                ok(f"#{i} 在（跟手拖拽要持续持有同一个节点）")
            else:
                bad(f"#{i} 不在 —— 拖拽跳章会失效")

        # -------------------------------------------------------------
        section("4. 旧代码依赖的 id 全在")
        # 每一个都是旧代码会 `$("#id")` 去取、取到 null 就抛错的入口。
        ids = ["rdToc", "rdSet", "rdTocList", "rdThemes", "rdProg",
               "rdBack", "rdChap", "rdSub", "rdPct", "rdTocQ",
               "rdTocClose", "rdSetClose", "rdTocBtn", "rdSetBtn",
               "rdPrevCh", "rdNextCh", "rdTitle"]
        missing = [i for i in ids if not safe_js(b, f"!!document.getElementById('{i}')")]
        if missing:
            bad(f"这些 id 丢了：{', '.join(missing)}"
                " —— 旧代码取到 null 会抛错，整条链路静默中断")
        else:
            ok(f"{len(ids)} 个旧代码依赖的 id 全部存在")

        # -------------------------------------------------------------
        section("5. 状态链路（旧代码 → Vue）")
        dbg = safe_js(b, "JSON.stringify(window.__lumeiRdDebug || null)")
        try:
            d = json.loads(dbg or "null") or {}
        except Exception:  # noqa: BLE001
            d = {}
        n_snap = d.get("snapshots") or 0
        if n_snap >= 1:
            ok(f"旧代码已推送 {n_snap} 份状态快照给 Vue")
        else:
            bad("旧代码一份快照都没推 —— 桥没注册上（attachReaderSnapshot 断开）")

        chap = safe_js(b, "(document.getElementById('rdChap')||{}).textContent || ''") or ""
        if "章" in chap and "—" not in chap:
            ok(f"#rdChap 有真实值：{chap!r}")
        else:
            bad(f"#rdChap 还是空的/占位：{chap!r}"
                " —— 状态没同步过来（真踩过：#rdTitle 丢 id 导致 openReader 早崩）")
        sub = safe_js(b, "(document.getElementById('rdSub')||{}).textContent || ''") or ""
        if sub and sub != "—":
            ok(f"#rdSub 有真实值：{sub!r}")
        else:
            bad(f"#rdSub 还是占位：{sub!r}")
        prog = safe_js(b, "(document.getElementById('rdProg')||{}).style.width || ''") or ""
        if prog and prog != "0%":
            ok(f"进度条宽度被写上：{prog}")
        else:
            bad(f"进度条宽度没更新：{prog!r}")

        # 色卡 6 张、且有一张是选中的（v-html 内容里的 .on 必须由旧代码生成，
        # 不能指望 Vue 去 toggle —— 踩过：切主题后高亮不动）
        n_th = safe_js(b, "document.querySelectorAll('#rdThemes button').length") or 0
        if n_th == 6:
            ok("色卡渲染出 6 张")
        else:
            bad(f"色卡数量不对：{n_th}（期望 6）")
        if safe_js(b, "!!document.querySelector('#rdThemes button.on')"):
            ok("有一张色卡带 .on（选中态）")
        else:
            bad("没有任何色卡是选中的 —— v-html 内容里的 .on 没生成")

        # -------------------------------------------------------------
        section("6. 目录与面板")
        n_toc = safe_js(b, "document.querySelectorAll('#rdTocList a[data-i]').length") or 0
        if n_toc >= 1:
            ok(f"目录铺出了 {n_toc} 条")
        else:
            bad("目录一条都没有 —— renderToc/appendToc 链路断了")
        # 面板开合：点 ☰ 应该开、点 ✕ 应该关
        safe_js(b, "document.querySelector('#rdTocBtn').click()")
        opened_toc = wait_js(b, "document.querySelector('#rdToc').classList.contains('on')", 6)
        if opened_toc:
            ok("点 ☰ → 目录面板打开")
        else:
            bad("点 ☰ 打不开目录面板")
        safe_js(b, "(function(){var b=document.querySelector('#rdTocClose');if(b)b.click();})()")
        closed_toc = wait_js(
            b, "!document.querySelector('#rdToc').classList.contains('on')", 6)
        if closed_toc:
            ok("点 ✕ → 目录面板关闭")
        else:
            bad("点 ✕ 关不掉目录面板")
        # 搜索过滤
        safe_js(b, "document.querySelector('#rdTocBtn').click()")
        wait_js(b, "document.querySelector('#rdToc').classList.contains('on')", 6)
        safe_js(b, """(function(){var q=document.querySelector('#rdTocQ');
                 q.value='第';q.dispatchEvent(new Event('input',{bubbles:true}));})()""")
        time.sleep(0.6)
        n_hit = safe_js(b, "document.querySelectorAll('#rdTocList a[data-i]').length") or 0
        if n_hit >= 1:
            ok(f"目录搜索框能过滤（命中 {n_hit} 条）")
        else:
            bad("目录搜索框没反应（rdFilterToc 没接上）")

        # -------------------------------------------------------------
        section("7. 没有 JS 报错")
        # ⚠ 用旧代码埋点自己的收集器（`window.__lumeiErrors`，见 telemetry）。
        #   别去挂 window.onerror —— 它会把"我们故意触发的探针异常"也算进来。
        errs = json.loads(safe_js(b, 
            "JSON.stringify((window.__lumeiErrors || []).map(String))") or "[]")
        if errs:
            bad(f"页面记到 {len(errs)} 条错误：{errs[:2]}")
        else:
            ok("页面没有记到 JS 错误")

    finally:
        try:
            b.close()
        except Exception:  # noqa: BLE001
            pass

    print("\n" + "=" * 62)
    if bad_n == 0:
        print(f"✅ 全部通过（{ok_n} 通过 / 0 失败）")
    else:
        print(f"❌ {bad_n} 项失败（{ok_n} 通过 / {bad_n} 失败）")
    print("=" * 62)
    return 1 if bad_n else 0


if __name__ == "__main__":
    raise SystemExit(main())
