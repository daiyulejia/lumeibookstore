#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
统计面板（来源抽屉的「统计」页签）· 真机验证
============================================================================
为什么单独一个套件：
  这个页签是新加的第三个页签，改动点全在**跨模块接缝**上 ——
  而接缝坏了全都**不报错**：

  · 第三个页签按钮加上去了，但 `renderTab` 的 if/else 链没跟上
    → 点「统计」tab 高亮过去了、内容却还是来源库的（看着像"卡住"）；
  · `#stats` 深链没登记 → 刷新回到默认页签；
  · 数字格子渲染了但拉的是空数据 → 一片 0（看着像"统计没工作"）；
  · 清空按钮没绑 → 点了完全没反应；
  · 拉接口失败时整块空白（没有错误提示）→ 用户以为"这功能本来就没有"。

五节：
  1. 三个页签都在，切到统计能看到内容
  2. 四个数字格子渲染出来了（今日访问/今日来客/昨日/累计）
  3. 搜索区块与访客区块都在（含"搜不到的词"那一栏）
  4. 两个清空按钮都在且绑了（点一下有确认框弹出）
  5. 没有 JS 报错

用法：
    .venv\\Scripts\\python tools\\test_stats_ui.py
    .venv\\Scripts\\python tools\\test_stats_ui.py --url http://127.0.0.1:8011
============================================================================
"""
from __future__ import annotations

import argparse
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
    q = f"?t={urllib.parse.quote(token)}" if token else ""

    print("=" * 62)
    print("统计面板 · 真机验证")
    print("=" * 62)

    try:
        urllib.request.urlopen(base + "/api/health" + q, timeout=5).read()
    except Exception as e:  # noqa: BLE001
        print(f"\n连不上 {base}：{e}")
        return 2

    # 先往搜索历史里种几个词 —— 否则"大家都在搜"永远是空的，测不出它到底渲染没有。
    # ⚠ 这些词会写进（隔离的）历史库；seed 词带前缀便于识别，跑完在 finally 里删掉。
    #   搜索接口是流式的，read(64) 只拿到开头；add_search 在流快结束时才执行，
    #   所以下面必须等一拍再开浏览器（同 test_history_ui.py 的时序坑）。
    seed = ["__统计测试热词甲__", "__统计测试热词乙__"]
    for w in seed:
        try:
            sreq = "/api/search?" + urllib.parse.urlencode(
                {"kw": w, "probe": 0, "sample": 0, "discover": 0})
            urllib.request.urlopen(
                urllib.request.Request(base + sreq + ("&" + q[1:] if q else "")),
                timeout=6).read(64)
        except Exception:  # noqa: BLE001
            pass
    time.sleep(4.0)

    b = Browser()
    try:
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
        # 直接带 #stats 深链进去 —— 这样一次就同时验了"深链能用"和"页签能渲染"
        b.goto(base + "/" + q + "#stats", settle=8.0)

        # -------------------------------------------------------------
        section("1. 三个页签 + 统计能打开")
        tabs = b.js("Array.from(document.querySelectorAll('#srcTabs .stab'))"
                    ".map(b => b.dataset.tab)")
        info(f"页签：{tabs}")
        if isinstance(tabs, list) and set(tabs) >= {"check", "registry", "stats"}:
            ok(f"三个页签都在（{len(tabs)} 个）")
        else:
            bad(f"页签不全：{tabs}")
        # 深链 #stats 应该直接把抽屉打开、并落在统计页
        drawer = b.js("!!document.getElementById('srcDrawer')")
        if drawer:
            ok("#stats 深链把抽屉打开了（刷新能保持状态）")
        else:
            bad("#stats 深链没打开抽屉")
        on_stats = b.js("(() => { const b = document.querySelector"
                        "('#srcTabs .stab[data-tab=stats]');"
                        " return !!b && b.classList.contains('on'); })()")
        if on_stats:
            ok("「统计」页签是高亮的")
        else:
            bad("落在别的页签上了（renderTab 的分发没跟上？）")

        # -------------------------------------------------------------
        section("2. 四个数字格子")
        cells = b.js("document.querySelectorAll('#srcBody .stcell').length")
        if cells == 4:
            ok("四个数字格子都渲染了")
        else:
            bad(f"数字格子数量不对：{cells}（期望 4）")
        # 格子里的数字必须是个数（不能是 undefined/NaN）
        nums = b.js("Array.from(document.querySelectorAll('#srcBody .stcell b'))"
                    ".map(e => e.textContent.trim())")
        info(f"数字：{nums}")
        if isinstance(nums, list) and nums and all(
                n.replace(".", "").isdigit() for n in nums):
            ok("格子里的都是数字（没渲染成 undefined/NaN）")
        else:
            bad(f"数字渲染有问题：{nums}")

        # -------------------------------------------------------------
        section("3. 搜索区块 + 访客区块")
        has_search = b.js("(() => { const h = Array.from("
                          "document.querySelectorAll('#srcBody .sth'));"
                          " return h.some(e => e.textContent.includes('搜索')); })()")
        if has_search:
            ok("有「搜索」区块")
        else:
            bad("没找到「搜索」区块")
        has_visit = b.js("(() => { const h = Array.from("
                         "document.querySelectorAll('#srcBody .sth'));"
                         " return h.some(e => e.textContent.includes('访问')); })()")
        if has_visit:
            ok("有「访问」区块")
        else:
            bad("没找到「访问」区块")
        # 隐私说明必须在 —— 这是产品承诺，不是可有可无的装饰
        has_privacy = b.js("(() => document.getElementById('srcBody')"
                           ".textContent.includes('脱敏'))()")
        if has_privacy:
            ok("有隐私说明（IP 脱敏）")
        else:
            bad("没有隐私说明 —— 存了 IP 却不告诉用户，产品上说不过去")
        # 机器轮询的口径也要说清：否则用户看到"访问 183"会以为真有 183 次点击，
        # 而实际大半是下载进度条的心跳。口径不写出来，数字就是误导。
        has_noise_note = b.js("(() => document.getElementById('srcBody')"
                              ".textContent.includes('机器轮询'))()")
        if has_noise_note:
            ok("有轮询口径说明（机器轮询计入访问但不占明细）")
        else:
            bad("没说清机器轮询口径 —— 数字会被误读成真实点击量")

        # -------------------------------------------------------------
        section("4. 两个清空按钮都在")
        btn_h = b.js("!!document.querySelector('#srcBody [data-act=clrh]')")
        btn_v = b.js("!!document.querySelector('#srcBody [data-act=clrv]')")
        if btn_h:
            ok("「清空搜索历史」按钮在")
        else:
            bad("没有清空搜索历史按钮")
        if btn_v:
            ok("「清空访问记录」按钮在")
        else:
            bad("没有清空访问记录按钮")

        # 点一下必须弹确认框（数据删了就没了，不能一点就走）
        if btn_h:
            b.js("document.querySelector('#srcBody [data-act=clrh]').click()")
            time.sleep(0.4)
            cfm = b.js("!!document.querySelector('.cfm')")
            if cfm:
                ok("点清空有二次确认（不会误删）")
                # 关掉确认框，别真删
                b.js("(() => { const n = document.querySelector('.cfm [data-no]');"
                     " if (n) n.click(); })()")
                time.sleep(0.2)
            else:
                bad("点清空没有确认框 —— 一下就把数据删了")

        # -------------------------------------------------------------
        section("5. 大家都在搜（热门词榜）")
        # 后端 get_hot 早就写好了，但一直没人消费 —— 这一节就是钉住"前端真接了"。
        hot = b.js("Array.from(document.querySelectorAll('#srcBody [data-hot]'))"
                   ".map(e => e.dataset.hot)")
        info(f"热词：{hot}")
        if isinstance(hot, list) and hot:
            ok(f"热词榜渲染了（{len(hot)} 个词）")
        else:
            bad("热词榜一个词都没有 —— 种了数据还空，说明前端没接 /api/history/search/hot")
        clicks = b.js("document.querySelectorAll('#srcBody .stchip.click').length")
        if clicks and clicks == (len(hot) if isinstance(hot, list) else 0):
            ok("热词 chip 都带可点样式（.click）")
        else:
            bad(f"可点 chip 数对不上：{clicks} vs 热词 {len(hot) if isinstance(hot, list) else '?'}")
        # 点一下必须真的把词填进搜索框（复用了主搜索路径，不是自己编的）
        if isinstance(hot, list) and hot:
            b.js("document.querySelector('#srcBody [data-hot]').click()")
            time.sleep(0.6)
            qv = b.js("(document.querySelector('#q') || {}).value || ''")
            if qv == hot[0]:
                ok("点热词把词填进了搜索框（复用主搜索流程）")
            else:
                bad(f"点热词没填对：搜索框是 {qv!r}，期望 {hot[0]!r}")
            # 抽屉该收起来了，否则会盖住结果
            gone = b.js("!document.getElementById('srcDrawer')")
            if gone:
                ok("点热词后抽屉收起了（不挡结果）")
            else:
                bad("点热词后抽屉还开着 —— 用户看不见搜出来的东西")

        # -------------------------------------------------------------
        section("6. 没有 JS 报错")
        errs = b.js("(window.__errs || [])")
        if not errs:
            ok("全程无 JS 错误")
        else:
            bad(f"有 {len(errs)} 条 JS 错误：{errs[:2]}")

    finally:
        b.close()
        # 清掉种进去的测试词 —— 跑测试不该在（隔离）库里留垃圾。
        for w in seed:
            try:
                urllib.request.urlopen(urllib.request.Request(
                    base + "/api/history/search?kw=" + urllib.parse.quote(w)
                    + ("&" + q[1:] if q else ""), method="DELETE"), timeout=5).read()
            except Exception:  # noqa: BLE001
                pass

    print("\n" + "=" * 62)
    print(f"通过 {ok_n} · 失败 {bad_n}")
    print("=" * 62)
    return 1 if bad_n else 0


if __name__ == "__main__":
    sys.exit(main())
