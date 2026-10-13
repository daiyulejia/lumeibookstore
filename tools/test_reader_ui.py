"""阅读器交互回归：翻页到底有没有真的翻、切模式会不会丢进度。

为什么单独写这个：截图只能证明"画出来了"，证明不了"点一下会不会翻"。
翻页是这次改造的核心功能，必须能用断言卡住。

用法： python tools/test_reader_ui.py [--bid <书架id>] [--url http://127.0.0.1:8000]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shot import Tab, launch_chrome, page_ws  # noqa: E402

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


def wait(tab: Tab, expr: str, timeout: float = 15.0) -> bool:
    return tab.wait_js(expr, timeout)


def js(tab: Tab, expr: str):
    """返回 {ok, value}，异常也拿得到。"""
    r = tab.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
    if r.get("exceptionDetails"):
        return {"ok": False, "err": r["exceptionDetails"].get("text")}
    return {"ok": True, "value": r.get("result", {}).get("value")}


def pick_bid(base: str) -> str:
    with urllib.request.urlopen(base + "/api/library", timeout=15) as r:
        lib = json.load(r)
    if not lib:
        raise SystemExit("书架是空的，先收一本进去再来跑这个测试")
    # 优先挑缓存最多 / 章节最多的，尽量不依赖网络
    lib.sort(key=lambda b: (-(b.get("cached") or 0), -(b.get("total") or 0)))
    return lib[0]["id"]


def reset_pos(base: str, bid: str) -> None:
    """把这本书的阅读位置重置到第 1 章开头。

    ⚠ 为什么必须有它：阅读位置是**存到服务器**的
      （`api.post('/api/library/<id>/position')`，见 reader.js）。
      于是一个用例翻了几页之后，下一个用例**打开同一本书会恢复那个位置** ——
      初始状态不再是第 0 页。

      这个坑的表现极具迷惑性：
        · `test_slide` 断言「点右侧 → 整条位移 / 点左侧 → 位移复原」，
          它隐含假设"进去时在第 0 页"。而 `test_flip` 跑在它前面、
          翻过页并把位置存了下来 → `test_slide` 进去时已经在第 5 页，
          `t0` 是 `translate3d(-4960px)`，点一次左只退一页 →
          断言 `t2 == t0` 失败。
        · 更坑的是它**看起来像 flaky**：第二次单独跑就过了
          （因为上一次跑结束时位置恰好被后面的用例改回开头）。
      修法就是每个用例打开前先重置位置，让用例之间彻底独立。
    """
    import urllib.request
    try:
        req = urllib.request.Request(
            f"{base}/api/library/{bid}/position",
            data=json.dumps({"index": 0, "percent": 0.0, "offset": 0}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=8).read()
    except Exception as e:  # noqa: BLE001
        print(f"  (重置阅读位置失败，忽略：{e})")


def open_reader(tab: Tab, base: str, bid: str, mode: str) -> None:
    # 先离开当前文档：导航到"只差 hash"的同一个 URL 不会真的重新加载，
    # 页面脚本不会重跑，预置的 localStorage 也就不生效 —— 会被静默跳过整个用例。
    js(tab, "location.replace('about:blank')")
    time.sleep(0.5)
    # 打开前先把位置归零，免得上一个用例留下的进度影响本用例（见 reset_pos 注释）
    reset_pos(base, bid)
    tab.call("Page.addScriptToEvaluateOnNewDocument",
             source=f"localStorage.setItem('nd_rd_mode',JSON.stringify({mode!r}))")
    tab.call("Page.navigate", url=f"{base}/#read={bid}")
    wait(tab, "!!document.querySelector('#reader.on')", 20)
    wait(tab, "!!document.querySelector('#rdChap') && /章/.test(document.querySelector('#rdChap').textContent)", 25)


def test_flip(tab: Tab, base: str, bid: str) -> None:
    print("\n—— 仿真翻页 ——")
    open_reader(tab, base, bid, "flip")
    ok = wait(tab, "document.querySelectorAll('.flipbook .page').length>1", 20)
    check("StPageFlip 渲染出多页", ok,
          js(tab, "document.querySelectorAll('.flipbook .page').length").get("value"))
    if not ok:
        return

    pages = js(tab, "document.querySelectorAll('.flipbook .page').length")["value"]
    check("页数 > 1", pages > 1, f"pages={pages}")

    cur = js(tab, "document.querySelector('#rdChap').textContent")["value"]
    check("状态栏显示页码", "/" in cur and "页" in cur, cur)

    # 点右侧应该翻到下一页
    js(tab, "document.querySelector('.rd-zone.r').click()")
    time.sleep(1.6)
    after = js(tab, "document.querySelector('#rdChap').textContent")["value"]
    check("点右侧 → 翻到下一页", after != cur, f"前={cur} 后={after}")

    # 点左侧应该翻回去
    js(tab, "document.querySelector('.rd-zone.l').click()")
    time.sleep(1.6)
    back = js(tab, "document.querySelector('#rdChap').textContent")["value"]
    check("点左侧 → 翻回上一页", back == cur, f"期望={cur} 实际={back}")

    # 中间点击应该切沉浸模式
    before = js(tab, "document.querySelector('#reader').classList.contains('immersive')")["value"]
    js(tab, "document.querySelector('.rd-zone.c').click()")
    time.sleep(0.8)
    after2 = js(tab, "document.querySelector('#reader').classList.contains('immersive')")["value"]
    check("点中间 → 切换沉浸模式", before != after2, f"{before} -> {after2}")


def test_slide(tab: Tab, base: str, bid: str) -> None:
    print("\n—— 左右平移 ——")
    open_reader(tab, base, bid, "slide")
    ok = wait(tab, "document.querySelectorAll('.rd-page').length>1", 20)
    check("分页渲染出多页", ok,
          js(tab, "document.querySelectorAll('.rd-page').length").get("value"))
    if not ok:
        return

    # 每页都应该有正文，不能出现"只有标题的空页"
    lens = js(tab, """JSON.stringify([...document.querySelectorAll('.rd-page .pg-body')]
        .map(e => (e.innerText||'').trim().length))""")["value"]
    arr = json.loads(lens)
    # 最后一页本来就装不满，单独放过；前面每一页都必须真的有内容
    check("最后一页之前的每页都有正文（>80 字）",
          all(n > 80 for n in arr[:-1]) if len(arr) > 1 else True, f"各页字数={arr}")
    check("首页不是只有个标题", (arr[0] if arr else 0) > 80, f"首页字数={arr[0] if arr else 0}")

    cur = js(tab, "document.querySelector('#rdChap').textContent")["value"]
    t0 = js(tab, "document.querySelector('#rdSlideStrip').style.transform")["value"]
    js(tab, "document.querySelector('.rd-zone.r').click()")
    time.sleep(0.9)
    t1 = js(tab, "document.querySelector('#rdSlideStrip').style.transform")["value"]
    check("点右侧 → 整条位移", t0 != t1, f"{t0} -> {t1}")
    after = js(tab, "document.querySelector('#rdChap').textContent")["value"]
    check("页码 +1", after != cur, f"{cur} -> {after}")

    js(tab, "document.querySelector('.rd-zone.l').click()")
    time.sleep(0.9)
    t2 = js(tab, "document.querySelector('#rdSlideStrip').style.transform")["value"]
    check("点左侧 → 位移复原", t2 == t0, f"{t2} vs {t0}")


def test_scroll(tab: Tab, base: str, bid: str) -> None:
    print("\n—— 上下滚动 ——")
    open_reader(tab, base, bid, "scroll")
    # ⚠ 等到**正文真的够长**，不能只等 h2（标题先出来、正文还在加载）。
    #   踩过：只等 h2 就 scrollTop=400，此时 #rdScroll 的 scrollHeight
    #   还不够 400px，根本滚不动 → 进度停在 0% → 「滚动后进度有值」假失败。
    #   它还会伪装成 flaky（正文偶尔加载快点就过了）。
    ok = wait(tab, "!!document.querySelector('#rdScrollBody h2')", 20)
    wait(tab, "(document.querySelector('#rdScrollBody')||{}).innerText "
              "&& document.querySelector('#rdScrollBody').innerText.length > 400 "
              "&& document.querySelector('#rdScroll').scrollHeight "
              "> document.querySelector('#rdScroll').clientHeight + 450", 25)
    check("渲染出正文", ok)
    if not ok:
        return
    h = js(tab, "document.querySelector('#rdScrollBody').innerText.length")["value"]
    check("正文字数合理", (h or 0) > 200, f"len={h}")
    # 段落必须切开了，不能是一整块
    pn = js(tab, "document.querySelectorAll('#rdScrollBody p').length")["value"]
    check("正文按段落切开（>3 段）", (pn or 0) > 3, f"p={pn}")
    # 往下滚，滚动要被真的响应
    #
    # ⚠ 踩过：原来断言 `#rdPct != "0%"` —— **这个期望本身是错的**。
    #   #rdPct 显示的是**全书**进度：`overall = ((index-1) + 本章滚动比例) / 总章数`。
    #   在第 1 章里滚 400px，本章比例约 9%，但总章数 1541 →
    #   overall ≈ 0.09/1541 ≈ 0.006% → toFixed(1) 后就是 "0%"。
    #   所以「0%」是**正确显示**，测试却判它失败（还会随章节数变化而 flaky）。
    #   真正该验的是「滚动被监听到了」→ 看本章滚动比例 RD.scrollFrac 动没动。
    before_frac = js(tab, "(()=>{try{const sc=document.querySelector('#rdScroll');"
                          "const max=sc.scrollHeight-sc.clientHeight;"
                          "return max>0 ? sc.scrollTop/max : -1;}catch(e){return -2;}})()")["value"]
    js(tab, "document.querySelector('#rdScroll').scrollTop = 400")
    time.sleep(0.6)
    st = js(tab, "document.querySelector('#rdScroll').scrollTop")["value"] or 0
    check("滚动真的生效（scrollTop 变了）", (st or 0) > 0, f"scrollTop={st}")
    # #rdPct 是**全书**进度，第 1 章滚 400px 显示 0% 是正确的 ——
    # 真正该验的是「本章滚动比例被算出来了」。
    frac = js(tab, "(()=>{try{const sc=document.querySelector('#rdScroll');"
                   "const max=sc.scrollHeight-sc.clientHeight;"
                   "return max>0 ? sc.scrollTop/max : -1;}catch(e){return -2;}})()")["value"]
    check("滚动比例被算出来（>0）",
          isinstance(frac, (int, float)) and frac > 0,
          f"本页滚动比例={frac}")


def test_persist(tab: Tab, base: str, bid: str) -> None:
    print("\n—— 偏好持久化 ——")
    open_reader(tab, base, bid, "slide")
    wait(tab, "document.querySelectorAll('.rd-page').length>1", 20)
    js(tab, "document.querySelector('#rdSetBtn').click()")
    time.sleep(0.5)
    js(tab, "document.querySelector('#rdLhRow [data-lh=\"2.2\"]').click()")
    time.sleep(1.2)
    lh = js(tab, "localStorage.getItem('nd_rd_lh')")["value"]
    check("改行距被记住", lh in ("2.2", "2.2"), f"nd_rd_lh={lh}")
    # 改字号后应该重排，页数会变（或者至少不报错）
    n0 = js(tab, "document.querySelectorAll('.rd-page').length")["value"]
    for _ in range(3):
        js(tab, "document.querySelector('#rdFsRow [data-fs=\"1\"]').click()")
        time.sleep(0.4)
    time.sleep(1.2)
    n1 = js(tab, "document.querySelectorAll('.rd-page').length")["value"]
    check("加大字号后重新分页（页数变多）", n1 >= n0, f"{n0} -> {n1}")
    err = js(tab, "document.querySelectorAll('.pg-body, .rd-page').length")["value"]
    check("重排后页面还在（没白屏）", (err or 0) > 0)


def test_touch(tab: Tab, base: str) -> None:
    """移动模拟下量各处按钮的热区。

    为什么必须单独测：桌面视口里 (hover:none)/(pointer:coarse) 恒为 false，
    触摸样式等于没写 —— 而"手机上点不动"恰恰只在这些查询成立时才暴露。
    这里把 (手机尺寸 + 触摸模拟 + 媒体查询命中) 三件事一起断言，
    任何一个环节退化都会被抓住。
    """
    print("\n—— 触摸热区（iPhone 尺寸 + 触摸模拟）——")

    # 切到移动模拟：mobile=True 才会让 hover:none / pointer:coarse 命中
    tab.call("Emulation.setDeviceMetricsOverride",
             width=393, height=852, deviceScaleFactor=3, mobile=True)
    tab.call("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
    tab.call("Page.navigate", url=base + "/")
    wait(tab, "!!document.querySelector('.tabbar')", 15)
    time.sleep(1.0)

    # 媒体查询真的命中了吗？没命中后面测的都不是触摸样式，白测。
    r = js(tab, "matchMedia('(hover:none)').matches")
    check("(hover:none) 命中", r.get("value") is True, f"got {r.get('value')}")
    r = js(tab, "matchMedia('(pointer:coarse)').matches")
    check("(pointer:coarse) 命中", r.get("value") is True, f"got {r.get('value')}")

    # 造一张卡片来量按钮：真实结果依赖搜索结果，不稳定，
    # 所以这里注入一份与 bookHTML 同构的 DOM，只量尺寸。
    js(tab, """
    (() => {
      const old = document.getElementById('__touchprobe');
      if (old) old.remove();
      const d = document.createElement('div');
      d.id = '__touchprobe';
      d.innerHTML = `<div class="wrap"><div class="book"><div class="head">`
        + `<div class="meta"><h3>探针</h3></div></div>`
        + `<div class="acts">`
        + `<button class="btn primary sm" id="__a">开始阅读</button>`
        + `<button class="btn sm" id="__b">来源 5</button>`
        + `<button class="btn sm icon" id="__c">\u21e7</button>`
        + `</div></div></div>`;
      document.body.appendChild(d);
      return 1;
    })()
    """)
    time.sleep(0.3)

    # iOS 人机指南：可点目标建议 >= 44x44 CSS px。
    # 门槛取 42 而不是 44：修复前实测 32.6px、修复后 47px，
    # 42 正好卡在两者中间，能把"触摸优化被改回去了"一刀切出来 ——
    # 设置成 44 会放过 43px 这种"差不多但没做"的情况。
    # 宽度门槛对纯图标按钮特别重要：修复前「↧」只有 26.6px，手指点不中。
    for sel, label, min_h, min_w in [
        ("#__a", "开始阅读", 42, 60),
        ("#__b", "来源 N", 42, 60),
        ("#__c", "导出图标", 42, 40),
    ]:
        r = js(tab, f"""(() => {{
            const e = document.querySelector('{sel}');
            if (!e) return null;
            const b = e.getBoundingClientRect();
            return [b.width, b.height];
        }})()""")
        v = r.get("value")
        if not v:
            check(f"{label} 能量到尺寸", False, "元素没找到")
            continue
        w, h = float(v[0]), float(v[1])
        check(f"{label} 热区 {w:.0f}x{h:.0f}px",
              h >= min_h and w >= min_w,
              f"要求 >= {min_w}x{min_h}")

    # hover 位移在触屏上必须关掉：iOS 会把 :hover 粘住，
    # .book:hover 的 translateY(-3px) 会让卡片"浮起来下不去"。
    # 注意等入场动画播完再量 —— card-in 动画期间 transform 会是个小数矩阵，
    # 那不是 hover 的效果，误判了会冤枉代码。
    time.sleep(1.2)
    r = js(tab, """(() => {
        const e = document.querySelector('#__touchprobe .book');
        if (!e) return null;
        const m = getComputedStyle(e).transform;
        if (m === 'none') return 'none';
        const n = m.match(/matrix\\(([^)]+)\\)/);
        if (!n) return m;
        const p = n[1].split(',').map(Number);
        // 只要 Y 位移与缩放是恒等，就算位移已关掉
        const identity = Math.abs(p[4]) < 0.01 && Math.abs(p[5]) < 0.01
                      && Math.abs(p[0] - 1) < 0.01 && Math.abs(p[3] - 1) < 0.01;
        return identity ? 'identity' : m;
    })()""")
    tr = r.get("value")
    check("卡片 hover 位移已关闭", tr in ("none", "identity"),
          f"transform={tr}")

    # 底部不能被固定标签栏咬掉按钮：末卡按钮底边要留在 tabbar 上沿之上。
    # 先把探针挪进 #results 并滚到底 —— 否则量到的是"还没滚下来"的位置，
    # 会算出一个假的遮挡量。
    js(tab, """(() => {
        const probe = document.querySelector('#__touchprobe .book');
        const box = document.getElementById('results');
        if (probe && box) box.appendChild(probe);
        return 1;
    })()""")
    time.sleep(0.4)
    r = js(tab, """(() => {
        window.scrollTo(0, 999999);
        return 1;
    })()""")
    time.sleep(0.4)
    r = js(tab, """(() => {
        const cards = document.querySelectorAll('#results .book');
        if (!cards.length) return null;
        const acts = cards[cards.length - 1].querySelector('.acts');
        if (!acts) return null;
        const tb = document.querySelector('.tabbar');
        if (!tb) return null;
        return [acts.getBoundingClientRect().bottom, tb.getBoundingClientRect().top];
    })()""")
    v = r.get("value")
    if v:
        gap = float(v[1]) - float(v[0])
        check(f"末卡按钮未被底栏遮挡（余 {gap:.0f}px）", gap >= 0,
              f"被压住 {-gap:.0f}px")
    else:
        check("末卡按钮未被底栏遮挡", False, "量不到（没卡片或没底栏）")

    # 收尾：把移动模拟撤掉，免得影响后面的用例
    tab.call("Emulation.setDeviceMetricsOverride",
             width=1240, height=860, deviceScaleFactor=1, mobile=False)


def test_toc_integrity(tab: Tab, base: str, bid: str) -> None:
    """目录不许出现重复章节 —— 防的是 appendToc 被重复调用。

    为什么值得单独立一条：`#rdTocList` 的 `onscroll` 是**赋值式**监听，
    但"滚到底"很容易在一次滚动里连触发两次（Chrome 在 momentum 滚动下就是）。
    以前 `appendToc` 用 `tocTo` 当游标，两次调用就把同一个 `[tocTo, tocTo+240)`
    区间**插两遍** —— 目录里章节号重复出现，用户滚动时看到"第 5 章"又一次。
    修法是拿 **DOM 里真实的条目数**当游标（`a[data-i]` 计数）而不是变量。

    这里不去模拟"滚到底"（不稳），而是**直接连调两次**，再数条目：
    重复插入的 bug 会立刻变成数量对不上。
    """
    print("\n—— 目录完整性 ——")
    open_reader(tab, base, bid, "scroll")
    js(tab, "document.querySelector('#rdTocBtn').click()")
    time.sleep(0.8)

    # 连调两次（幂等），再数一遍长度
    js(tab, """
    (() => {
      const box = document.querySelector('#rdTocList');
      if (!box) return 0;
      box.dispatchEvent(new Event('scroll'));
      box.dispatchEvent(new Event('scroll'));
      return box.querySelectorAll('a[data-i]').length;
    })()""")
    time.sleep(0.6)
    n = js(tab, "document.querySelectorAll('#rdTocList a[data-i]').length")["value"] or 0
    check("目录铺出了内容", n > 0, f"条目数={n}")

    idx = js(tab, """
    (() => {
      const ids = [...document.querySelectorAll('#rdTocList a[data-i]')]
        .map(a => +a.dataset.i);
      return { total: ids.length, uniq: new Set(ids).size };
    })()""")["value"] or {}
    check("目录里没有重复章节号",
          idx.get("total") == idx.get("uniq"),
          f"共 {idx.get('total')} 条 / 去重后 {idx.get('uniq')} 条")

    # 再点一次目录按钮（关掉再开）——重开不许把内容翻倍
    js(tab, "document.querySelector('#rdTocBtn').click()")
    time.sleep(0.4)
    js(tab, "document.querySelector('#rdTocBtn').click()")
    time.sleep(0.4)
    n2 = js(tab, "document.querySelectorAll('#rdTocList a[data-i]').length")["value"] or 0
    check("重开目录不会把条目翻倍", n2 <= n + 1, f"{n} -> {n2}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--bid", default="")
    ap.add_argument("--w", type=int, default=1240)
    ap.add_argument("--h", type=int, default=860)
    a = ap.parse_args()

    bid = a.bid or pick_bid(a.url)
    print(f"用书架里的 {bid} 来测")

    # ⚠ 用 shot.launch_chrome（Chrome 自动分配端口 + DevToolsActivePort 实例 UUID
    #   校验），不要退回「free_port() + wait_devtools()」——后者只判断「端口能回话」，
    #   不判断回话的是不是自己刚起的实例。上一个套件 terminate 掉的旧 Chrome 还没退
    #   干净时，这里会连上它，等它一死就是 ConnectionResetError/WinError 10054。
    #   实测症状：ship 里 14 套串行跑随机红、单独重跑必绿、每次红的位置都不同。
    proc, port, _bws, profile = launch_chrome(
        headless=True, window=(a.w, a.h),
        extra_args=["--disable-extensions"])
    try:
        # Page.*/Runtime.* 只挂在**页面 target** 上，要用 page_ws 拿页面级 ws。
        tab = Tab(page_ws(port))
        tab.call("Page.enable")
        tab.call("Runtime.enable")
        tab.call("Emulation.setDeviceMetricsOverride",
                 width=a.w, height=a.h, deviceScaleFactor=1, mobile=False)

        test_flip(tab, a.url, bid)
        test_slide(tab, a.url, bid)
        test_scroll(tab, a.url, bid)
        test_persist(tab, a.url, bid)
        test_toc_integrity(tab, a.url, bid)
        test_touch(tab, a.url)

        print(f"\n{'✅ 全部通过' if not BAD else f'❌ {BAD} 项失败'}（{OK} 通过 / {BAD} 失败）")
        return 1 if BAD else 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
