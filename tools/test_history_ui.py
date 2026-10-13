#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
搜索历史下拉 · 真机验证
============================================================================
为什么单独一个套件：
  纯静态断言（test_search_history.py）能保证"代码接上了"，
  但保证不了"**真的能点**"。下拉这种东西的坑全在**运行时行为**上，
  而且是静态扫描完全看不见的：

  · `blur` 抢在 `click` 前面 → 下拉先收起、条目消失 → 点上去"像没反应"。
    这是下拉菜单最经典的坑，只会在真机出现（静态检查永远绿）。
  · `position:absolute` 找不到定位祖先 → 下拉跑到整页宽 / 错位的角落。
  · 派发的 `keydown Enter` 没被搜索框接住 → 点了历史词，输入框填上了，
    但**搜索没跑**（用户看到"点了没反应"）。
  · 键盘 ↑↓ 只改了变量没改 DOM → 高亮不跟着走。
  · 删单条没 stopPropagation → 删完顺手又搜了一次（数据已经没了才搜）。

五节：
  1. 下拉初始是关着的（不能一进页面就杵在那儿）
  2. 聚焦后能开，且条目数量与接口一致
  3. 位置对齐搜索框（left/right 与 .searchbox 重合）
  4. 键盘 ↑↓ 能改高亮、Esc 能关
  5. 点历史词 → 输入框被填上 + 真的触发了搜索

用法：
    .venv\\Scripts\\python tools\\test_history_ui.py
    .venv\\Scripts\\python tools\\test_history_ui.py --url http://127.0.0.1:8011
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


def with_token(path: str, token: str) -> str:
    """把令牌拼到 URL 上。**必须处理"路径里已经有查询参数"的情况。**

    ⚠ 这里踩过一个坑，值得记下来：直接写 `path + "?t=" + token` 时，
    若 path 已经带了 `?limit=20`，拼出来就是
    `/api/history/search?limit=20?t=xxx` —— 第二个 `?` 不会被当成分隔符，
    于是 `limit` 的值变成了 `"20?t=xxx"`，FastAPI 解析 int 失败 →
    **422**。症状是"接口明明 curl 能通，测试却报 422"，
    很容易误判成后端问题。
    """
    if not token:
        return path
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}t={urllib.parse.quote(token)}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--token", default="")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    token = a.token or local_token()
    # ⚠ 别再手写 `"?t=" + token` —— 见 with_token() 的注释。
    #   这里保留一个不带参数的裸 q 给浏览器 URL 用（那种路径没有查询串）。
    q = f"?t={urllib.parse.quote(token)}" if token else ""

    print("=" * 62)
    print("搜索历史下拉 · 真机验证")
    print("=" * 62)

    try:
        urllib.request.urlopen(base + "/api/health" + q, timeout=5).read()
    except Exception as e:  # noqa: BLE001
        print(f"\n连不上 {base}：{e}")
        return 2

    # 先确保历史里有东西 —— 否则下拉永远是空的，"能不能开"就测不出。
    # ⚠ 这些词是**测试写进生产库**的，跑完要清掉（见 finally）。
    #   不清的话每次跑测试都在用户的历史里拉屎。
    seed = ["__测试用书A__", "__测试用书B__", "__测试用书C__"]
    seeded: list[str] = []
    for w in seed:
        try:
            sreq = with_token("/api/search?" + urllib.parse.urlencode(
                {"kw": w, "probe": 0, "sample": 0, "discover": 0}), token)
            req = urllib.request.Request(base + sreq)
            # 搜索会记历史；★ 只要请求真的跑到了 handler 就一定记上了，
            #   不需要读完流（读完要等十几秒，这里只要"记一笔"）
            urllib.request.urlopen(req, timeout=6).read(64)
            seeded.append(w)
        except Exception:  # noqa: BLE001
            pass

    # ⚠ 必须等一拍再读历史。`/api/search` 是**流式**的，`read(64)` 拿到
    #   开头就返回了，但后端 handler 还在跑 —— `history.add_search` 是在
    #   流**快结束时**才执行的（它要等 `books` 聚合出来才有 hits）。
    #   立刻读接口会拿到"上一刻"的条数，于是下面"下拉条目数 == 接口条数"
    #   必然对不上（实测：下拉 4 条、接口才 2 条）。
    #   这是测试自己的时序坑，不是产品问题。
    time.sleep(4.0)

    # 拿当前历史（用来和下拉条目数对账）
    try:
        hist_url = base + with_token("/api/history/search?limit=20", token)
        with urllib.request.urlopen(hist_url, timeout=8) as r:
            hist = json.load(r)
        n_hist = len(hist.get("items") or [])
    except Exception as e:  # noqa: BLE001
        print(f"\n读 /api/history/search 失败：{e}")
        return 2
    info(f"接口返回 {n_hist} 条历史")
    if n_hist == 0:
        print("\n历史是空的，没法验证下拉（种子写入也失败了？）")
        return 2

    b = Browser()
    try:
        # 收集页面 JS 错误 —— Browser 类没提供 errors()，这里自己装一个钩子。
        # ⚠ 必须在 goto 之前注入（addScriptToEvaluateOnNewDocument 对
        #   **之后**的每次导航都生效），晚一步就漏了加载期的错误。
        b.t.call("Page.addScriptToEvaluateOnNewDocument", source="""
          window.__errs = [];
          window.addEventListener('error', e => {
            try { window.__errs.push(String((e && e.message) || e)); } catch (_) {}
          });
          window.addEventListener('unhandledrejection', e => {
            try {
              const r = e && e.reason;
              window.__errs.push(String((r && r.message) || r));
            } catch (_) {}
          });
        """)
        b.goto(base + "/" + q, settle=8.0)

        # -------------------------------------------------------------
        section("1. 初始是关着的")
        box_exists = b.js("!!document.querySelector('.h-drop')")
        if box_exists:
            ok(".h-drop 已挂上（mountHistory 跑了）")
        else:
            bad(".h-drop 不存在 —— mountHistory 没执行？")
        hidden0 = b.js("(() => { const d = document.querySelector('.h-drop');"
                       " return !d || d.hidden; })()")
        if hidden0:
            ok("初始是隐藏的（不会一进页面就杵在那儿）")
        else:
            bad("初始就显示着 —— 应该在 hidden")

        # -------------------------------------------------------------
        section("2. 聚焦能开，条目数与接口一致")
        # ⚠⚠ 这里必须派发 focus **事件**，不能调 `el.focus()`。
        #    headless Chrome 的窗口没有系统焦点，`el.focus()` **不会**触发
        #    focus 事件 —— 于是监听器压根不跑，下拉永远不开。
        #    这是 headless 的已知行为，不是产品 bug（第一版测试就是这么
        #    假红了 7 项，一度以为是真问题）。派发事件测的是"监听器接住了吗"，
        #    正是这一层该测的东西。
        b.js("document.getElementById('q').dispatchEvent(new FocusEvent('focus'))")
        time.sleep(1.0)
        opened = b.js("(() => { const d = document.querySelector('.h-drop');"
                      " return !!d && !d.hidden; })()")
        if opened:
            ok("聚焦后下拉打开了")
        else:
            bad("聚焦后下拉没打开（focus 监听或 render 有问题）")
        items = b.js("document.querySelectorAll('.h-drop .h-item').length")
        info(f"下拉里有 {items} 条，接口 {n_hist} 条")
        # 下拉最多显示 8 条（MAX_SHOW），所以断言"等于 min(n,8)"
        want = min(n_hist, 8)
        if items == want:
            ok(f"条目数 {items} == min(接口 {n_hist}, 上限 8)")
        else:
            bad(f"条目数对不上：下拉 {items}，期望 {want}")

        # -------------------------------------------------------------
        section("3. 位置对齐搜索框")
        # ⚠ 下拉**没打开**时几何信息毫无意义（宽高都是 0），
        #   那会一次性刷出三条误导性的红。这里先看它开没开，
        #   没开就只报一条（真正的病因在第 2 节）。
        if not opened:
            bad("下拉没打开，跳过位置断言（病因见上一条）")
            geo = None
        else:
            geo = b.js("""(() => {
              const d = document.querySelector('.h-drop');
              const s = document.querySelector('.searchbox');
              if (!d || !s) return null;
              const a = d.getBoundingClientRect(), c = s.getBoundingClientRect();
              return {dl: a.left, sl: c.left, dr: a.right, sr: c.right,
                      dt: a.top, sb: c.bottom, dw: a.width, sw: c.width};
            })()""")
        if geo:
            dx_l = abs((geo["dl"] or 0) - (geo["sl"] or 0))
            dx_r = abs((geo["dr"] or 0) - (geo["sr"] or 0))
            if dx_l < 8 and dx_r < 8:
                ok(f"左右与搜索框对齐（左差 {dx_l:.0f}px，右差 {dx_r:.0f}px）")
            else:
                bad(f"左右没对齐搜索框：左差 {dx_l:.0f}px 右差 {dx_r:.0f}px"
                    "（典型的 absolute 找不到定位祖先）")
            if geo["dt"] >= geo["sb"] - 4:
                ok("在搜索框正下方（top >= searchbox.bottom）")
            else:
                bad(f"位置不对：下拉 top={geo['dt']:.0f} < 搜索框 bottom={geo['sb']:.0f}")
            # 宽度不能跑到整页宽（说明定位祖先错了）
            if abs(geo["dw"] - geo["sw"]) < 12:
                ok("宽度与搜索框一致（没跑到整页宽）")
            else:
                bad(f"宽度异常：下拉 {geo['dw']:.0f} vs 搜索框 {geo['sw']:.0f}")
        else:
            bad("取不到几何信息（元素不在？）")

        # -------------------------------------------------------------
        section("4. 键盘 ↑↓ / Esc")
        # 同样派发事件而非 .focus()（理由见第 2 节）
        b.js("document.getElementById('q').dispatchEvent(new FocusEvent('focus'))")
        time.sleep(0.6)
        b.js("""document.getElementById('q').dispatchEvent(
          new KeyboardEvent('keydown', {key:'ArrowDown', bubbles:true}))""")
        time.sleep(0.2)
        has_on = b.js("document.querySelectorAll('.h-drop .h-item.on').length")
        if has_on >= 1:
            ok("按下 ↓ 后有高亮条目（.h-item.on）")
        else:
            bad("按下 ↓ 没有高亮 —— 键盘导航没生效")
        b.js("""document.getElementById('q').dispatchEvent(
          new KeyboardEvent('keydown', {key:'Escape', bubbles:true}))""")
        time.sleep(0.3)
        closed = b.js("(() => { const d = document.querySelector('.h-drop');"
                      " return !d || d.hidden; })()")
        if closed:
            ok("按下 Esc 收起了下拉")
        else:
            bad("按下 Esc 没收起")

        # -------------------------------------------------------------
        section("5. 点历史词 → 填上 + 触发搜索")
        # 监听搜索是否真的跑了：runSearch 会改 #statbar（出现"正在…里找"）
        b.js("document.getElementById('q').dispatchEvent(new FocusEvent('focus'))")
        time.sleep(0.6)
        first_kw = b.js("(() => { const it = document.querySelector('.h-drop .h-item');"
                        " return it ? it.getAttribute('data-kw') : ''; })()")
        info(f"准备点的历史词：{first_kw!r}")
        if first_kw:
            # 用 DOM click 而不是鼠标坐标 —— 我们测的是"点击处理器接住了没有"，
            # 不是"元素在那个像素位置"（后者已被第 3 节覆盖）。
            # 但 ⚠ mousedown 要单独补一次：history.js 只对 mousedown 做了
            # preventDefault（防焦点被抢），DOM click() 不触发 mousedown，
            # 补上是为贴近真实鼠标行为。
            b.js("""(() => {
              const it = document.querySelector('.h-drop .h-item');
              if (!it) return;
              it.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
              it.dispatchEvent(new MouseEvent('click', {bubbles:true}));
            })()""")
            time.sleep(1.2)
            val = b.js("document.getElementById('q').value")
            if val == first_kw:
                ok(f"输入框被填成了 {val!r}")
            else:
                bad(f"输入框没被填上：期望 {first_kw!r}，实际 {val!r}")

            # 搜索是否被触发：输入框清空/statbar 变化都能说明，
            # 用最稳的一条 —— runSearch 会把输入框的值保留但让 #statbar 有文字
            stat = b.js("(document.getElementById('statbar')||{}).textContent || ''")
            if stat.strip():
                ok(f"搜索被触发了（statbar = {stat.strip()[:40]!r}）")
            else:
                bad("点了历史词但搜索没跑（statbar 是空的）—— "
                    "派发的 Enter 没被接住？")
        else:
            bad("下拉里没找到可点的条目")
            # -------------------------------------------------------------
        section("6. 没有 JS 报错")
        errs = b.js("(window.__errs || [])")
        if not errs:
            ok("全程无 JS 错误")
        else:
            bad(f"有 {len(errs)} 条 JS 错误：{errs[:2]}")

    finally:
        # 清掉测试写进去的种子词，别污染用户历史
        for w in seeded:
            try:
                # ⚠ 用查询参数（不是路径段）—— 见 app/main.py 的注释：
                #   路径段放不下斜杠，而我们这两个种子词虽然没斜杠，
                #   也统一走同一条路径，免得"测试用 A 写法、产品用 B 写法"。
                durl = base + with_token(
                    "/api/history/search?kw=" + urllib.parse.quote(w), token)
                req = urllib.request.Request(durl, method="DELETE")
                urllib.request.urlopen(req, timeout=5).read()
            except Exception:  # noqa: BLE001
                pass
        b.close()

    print("\n" + "=" * 62)
    print(f"通过 {ok_n} · 失败 {bad_n}")
    print("=" * 62)
    return 1 if bad_n else 0


if __name__ == "__main__":
    sys.exit(main())
