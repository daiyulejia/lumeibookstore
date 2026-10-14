"""窄屏不溢出回归：手机上「页面比屏幕宽 / 一行看不全」。

为什么单独写这个
----------------
2026-10-13 用户报：「手机阅读的时候……一行看不全或者页面比屏幕宽」。

排查发现**两处真会让文档比屏幕宽**（都不是阅读器本身，而是它外面的壳）：
  1. 顶栏 `.topbar` 是 flex 一行：品牌（~107px）+ 右侧 **5 个** 38px 图标按钮
     （~206px）+ gap + padding ≈ 361px。在 360px 及以下屏上比屏幕还宽 ——
     整份文档被撑到 ~355px，右侧（含阅读器行尾）被切掉。
  2. Hero 的「两张图 + 对话气泡」一行放不下（320px 屏 → 文档被撑到 327px）。

这两处**截图看不出来**（截图只拍可视区，不知道右边被切了），
只有真机量 `innerWidth` vs `documentElement.scrollWidth` 才暴露。
所以这条测的不是"画得对不对"，是"**有没有横向溢出**" —— 一个纯几何判据。

测法（判据只取决于布局，不随网络/内容漂移）：
  · 在若干真实手机宽度（320/360/393）打开首页与阅读器
  · 断言 `documentElement.scrollWidth <= innerWidth`（允许 1px 亚像素误差）
  · 断言顶栏自身 `scrollWidth <= innerWidth`（顶栏是最容易溢出的那条）
  · 阅读器两种翻页模式都量一遍

用法： python tools/test_mobile_fit.py [--url http://127.0.0.1:8000]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shot import Tab, launch_chrome, page_ws  # noqa: E402

OK = 0
BAD = 0
TOL = 1.5          # 允许的亚像素误差（deviceScaleFactor=3 下的舍入）


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
    r = tab.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
    if r.get("exceptionDetails"):
        return {"ok": False, "err": r["exceptionDetails"].get("text")}
    return {"ok": True, "value": r.get("result", {}).get("value")}


def pick_bid(base: str) -> str:
    with urllib.request.urlopen(base + "/api/library", timeout=15) as r:
        lib = json.load(r)
    if not lib:
        raise SystemExit("书架是空的，先收一本进去再来跑这个测试")
    lib.sort(key=lambda b: (-(b.get("cached") or 0), -(b.get("total") or 0)))
    return lib[0]["id"]


def reset_pos(base: str, bid: str) -> None:
    try:
        req = urllib.request.Request(
            f"{base}/api/library/{bid}/position",
            data=json.dumps({"index": 0, "percent": 0.0, "offset": 0}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=8).read()
    except Exception:  # noqa: BLE001
        pass


def open_reader(tab: Tab, base: str, bid: str, mode: str) -> None:
    js(tab, "location.replace('about:blank')")
    time.sleep(0.4)
    reset_pos(base, bid)
    tab.call("Page.addScriptToEvaluateOnNewDocument",
             source=f"localStorage.setItem('nd_rd_mode',JSON.stringify({mode!r}))")
    tab.call("Page.navigate", url=f"{base}/#read={bid}")
    wait(tab, "!!document.querySelector('#reader.on')", 20)
    wait(tab, "!!document.querySelector('#rdChap')", 15)
    time.sleep(0.8)


# 量"有没有横向溢出"。返回 {winW, docW, topbarW, ...}
#
# ⚠⚠ 判据的关键：**跟"请求的宽度"比，不是跟 innerWidth 比**。
#   踩过（这条测试第一版就是这么写错的，反证时不报红）：
#   mobile 模拟下，如果页面内容把布局撑宽，Chrome 会把 `innerWidth` 一起放大
#   （请求 320 → 实际 innerWidth=355）。于是 `docW <= innerW` 恒成立 ——
#   因为两个数一起涨。**看着绿，其实页面比屏幕宽了 35px。**
#   正确的量：`innerWidth` 必须**等于**我们 `setDeviceMetricsOverride` 请求的值。
_MEASURE = r"""
(() => {
  const de = document.documentElement;
  const tb = document.querySelector('.topbar');
  return JSON.stringify({
    winW: innerWidth,
    docW: de.scrollWidth,
    bodyW: document.body.scrollWidth,
    topbarW: tb ? tb.scrollWidth : null,
    topbarClientW: tb ? tb.clientWidth : null,
  });
})()
"""


def assert_fits(tab: Tab, label: str, want_w: int) -> None:
    """断言页面在**请求的宽度**下没有横向溢出。

    ⚠ 判 `innerWidth == want_w` 而不是 `docW <= innerW`：见 _MEASURE 上面的注释。
    """
    r = js(tab, _MEASURE)
    if not r.get("ok"):
        check(f"{label}：能量到尺寸", False, str(r.get("err")))
        return
    m = json.loads(r["value"])
    win = m["winW"]
    check(f"{label}：视口没被内容撑宽（请求 {want_w}）", win <= want_w + TOL,
          f"innerWidth={win} > 请求 {want_w}px —— 页面内容比屏幕宽，右侧会被切")
    check(f"{label}：文档不溢出", m["docW"] <= want_w + TOL,
          f"documentElement.scrollWidth={m['docW']} > {want_w}px")
    if m["topbarW"] is not None:
        check(f"{label}：顶栏不溢出", m["topbarW"] <= want_w + TOL,
              f".topbar.scrollWidth={m['topbarW']} > {want_w}px")



def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    a = ap.parse_args()

    base = a.url or ""
    srv = None
    proc = None
    try:
        if not base:
            from ship import LocalServer
            srv = LocalServer()
            srv.__enter__()
            base = srv.base

        proc, port, _bws, profile = launch_chrome(
            headless=True, window=(420, 900), extra_args=["--disable-extensions"])
        try:
            tab = Tab(page_ws(port))
            tab.call("Page.enable")
            tab.call("Runtime.enable")

            bid = pick_bid(base)

            for w in (320, 360, 393):
                tab.call("Emulation.setDeviceMetricsOverride",
                         width=w, height=852, deviceScaleFactor=3, mobile=True)
                tab.call("Emulation.setTouchEmulationEnabled",
                         enabled=True, maxTouchPoints=5)

                # —— 首页 ——
                tab.call("Page.navigate", url=base + "/")
                wait(tab, "!!document.querySelector('#q')", 20)
                wait(tab, "document.documentElement.dataset.mounted", 15)
                time.sleep(0.6)
                assert_fits(tab, f"首页@{w}px", w)

                # —— 其余五个视图 ——
                # 为什么要逐个量：用户报的是「窄屏横向溢出」这一**类**问题，
                # 而溢出往往来自某个**页面独有的**宽元素（固定 min-width 的网格、
                # 一排表格、一个长不换行的标签）。只在首页量过，等于说
                # "只要首页不溢出，别的页面也不会" —— 这是没有依据的假设。
                # 实测本轮它们都干净，但**没人钉住** → 日后一改就可能悄悄退回去。
                for vname, vhash in (("书架", "#shelf"), ("文件", "#files"),
                                     ("统计", "#stats"), ("来源", "#sources"),
                                     ("登记表", "#registry")):
                    tab.call("Page.navigate", url=base + "/" + vhash)
                    wait(tab, "!!document.querySelector('#q')", 20)
                    wait(tab, "document.documentElement.dataset.mounted", 15)
                    time.sleep(0.6)
                    assert_fits(tab, f"{vname}@{w}px", w)

                # —— 阅读器（两种翻页模式）——
                for mode in ("slide", "flip"):
                    open_reader(tab, base, bid, mode)
                    wait(tab, "document.querySelectorAll('.rd-page,.flipbook .page').length>1", 20)
                    assert_fits(tab, f"阅读器@{w}px/{mode}", w)

            # —— 首页 Hero：轮换要真的生效，而且**右边永远是噜妹** ——
            #
            # ⚠ 旧版这里只数了 `data-hero-pool` 的**字符串条数**，于是假绿：
            #   池里写了 3 对，但 `rotateHeroArt()` 会用 `ART[key]` 过滤，
            #   当时 `hero_lulu/hero_lumei` 没登记进 ART → 含噜妹的那对天天被丢，
            #   首页连着几天只有噜噜。条数测试完全看不出来。
            #   现在改成读**真正渲染出来的 `currentSrc`**，并校验它落在池子里。
            tab.call("Emulation.setDeviceMetricsOverride",
                     width=393, height=852, deviceScaleFactor=3, mobile=True)
            tab.call("Page.navigate", url=base + "/")
            wait(tab, "!!document.querySelector('[data-hero-pool]')", 20)
            time.sleep(1.2)
            r = js(tab, r"""
            (() => {
              const dup = document.querySelector('[data-hero-pool]');
              const pool = (dup?.dataset.heroPool || '').split(',').map(s=>s.trim())
                .filter(Boolean).map(s => s.split('|').map(x=>x.trim()));
              const imgs = [...(dup ? dup.querySelectorAll('[data-hero-role]') : [])];
              const shown = imgs.map(i => (i.currentSrc || i.src || '').split('/').pop()
                .replace(/@\d+\.webp$/, ''));
              const loaded = imgs.map(i => i.naturalWidth > 0);
              return JSON.stringify({pool, shown, loaded});
            })()
            """)
            m = json.loads(r["value"]) if r.get("ok") else {}
            pool = m.get("pool") or []
            shown = m.get("shown") or []
            loaded = m.get("loaded") or []

            check("Hero 轮换池 ≥2 对（否则谈不上『每天轮换』）", len(pool) >= 2,
                  f"pool={pool}")
            check("Hero 两张图都真的加载出来了", len(loaded) == 2 and all(loaded),
                  f"loaded={loaded} shown={shown} —— 名字拼错/文件缺失")

            # 渲染出来的这一对必须是池子里的某一对 —— 证明 rotateHeroArt 真的跑过
            # 且没有把这一对过滤掉（过滤掉就会回落到 HTML 里的静态兜底图）。
            in_pool = len(shown) == 2 and any(
                [shown[0], shown[1]] == [p[0], p[1]] for p in pool)
            check("Hero 当前渲染的一对确实来自轮换池（轮换真生效）", in_pool,
                  f"shown={shown} pool={pool} —— 可能是 rotateHeroArt 把它过滤掉了")

            # ⚠ 这条是「首页每天都要有噜妹」的端到端判据：
            #   约定是**左=噜噜、右=噜妹**，所以右边那张的文件名必须以 hero_lumei 开头。
            check("Hero 右侧是噜妹（hero_lumei*）—— 首页每天都有噜妹",
                  len(shown) == 2 and shown[1].startswith("hero_lumei"),
                  f"shown={shown} —— 右边不是噜妹，用户会说『首页没有噜妹』")
            check("Hero 左右两张不是同一张（是一『对』）",
                  len(shown) == 2 and shown[0] != shown[1], f"shown={shown}")

            # —— 首页那句「数据都在你自己电脑上」必须已被删掉 ——
            check("首页不再有「数据都在你自己电脑上」眉标",
                  not js(tab, "!!document.querySelector('.eyebrow')").get("value"))
        finally:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
    finally:
        if srv is not None:
            srv.__exit__(None, None, None)

    print("\n" + "=" * 62)
    print(f"通过 {OK} · 失败 {BAD}")
    print("✓ 全部通过" if not BAD else "✗ 有失败")
    print("=" * 62)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
