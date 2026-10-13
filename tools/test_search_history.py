# -*- coding: utf-8 -*-
"""搜索历史 / 访客记录 —— **接入链路**的静态自检。

为什么需要它（纯静态，不启服务）
--------------------------------
新功能最容易坏的地方不是内部逻辑（那两个模块各有自己的行为测试），
而是**接线**：东西写好了，但没人调用 / 路由没挂 / 深链没接 /
登记表没同步。这类坏法全都**不报错**，表现是：

  · 后端写了一堆接口，前端却从没发过请求 → 界面上那个面板永远空着；
  · 前端写了 `mountHistory()`，但 main.js 里忘了调 → 下拉永远不出现；
  · CSS 类名写错（`.h-drop` vs `.h-dropdown`）→ 下拉出来了但没样式，
    糊成一坨压在页面中间，看起来像"页面坏了"；
  · 埋点登记表漏了新事件 → 线上 grep 不到，以为功能没触发。

这些光靠"跑起来看看"是**抓不全**的（你得恰好点到那个面板、恰好展开下拉）。
所以这里用静态断言把它们钉住 —— 改坏了立刻红，不用手点。

用法：python tools/test_search_history.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
JS = APP / "static" / "js"
CSS = APP / "static" / "css"

ok_n = 0
fail_n = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global ok_n, fail_n
    if cond:
        ok_n += 1
        print(f"  ✓ {name}")
    else:
        fail_n += 1
        print(f"  ✗ {name} {extra}")


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    main_js = read(JS / "main.js")
    hist_js = read(JS / "history.js")
    src_js = read(JS / "sources.js")
    util_js = read(JS / "util.js")
    app_py = read(APP / "main.py")
    hist_py = read(APP / "history.py")
    vis_py = read(APP / "visits.py")
    css = read(CSS / "app.css") + read(CSS / "lumei.css")
    events_py = read(APP / "logging_setup.py")

    print("\n—— 1. 后端模块存在且接口挂上了 ——")
    check("app/history.py 存在", bool(hist_py))
    check("app/visits.py 存在", bool(vis_py))
    for route, desc in [
        ('"/api/history/search"', "最近搜索"),
        ('"/api/history/search/hot"', "热门搜索"),
        ('"/api/history/search/stats"', "搜索历史统计"),
        ('"/api/visits"', "最近访问"),
        ('"/api/visits/stats"', "访问统计"),
    ]:
        check(f"路由 {route}（{desc}）已注册", route in app_py)

    print("\n—— 2. 中间件真的记访问了 ——")
    check("_observe 里调了 visits.record", "visits.record(" in app_py)
    # ⚠ 这条是本次最重要的断言之一：记录必须包在 try 里。
    #   否则统计一出问题，**所有接口**跟着 500 —— 那是灾难性的耦合。
    i_rec = app_py.find("visits.record(")
    around = app_py[max(0, i_rec - 400):i_rec]
    check("visits.record 包在 try 里（不能让它拖垮接口）", "try:" in around,
          "附近没有 try —— 统计异常会让所有接口一起 500")
    check("有 _client_ip（走代理时才能拿到真实 IP）", "def _client_ip" in app_py)
    check("_client_ip 优先读 x-forwarded-for",
          "x-forwarded-for" in app_py and "split(\",\")[0]" in app_py.replace("'", '"'))

    print("\n—— 3. 搜索成功后真的记了历史 ——")
    check("/api/search 里调了 history.add_search", "history.add_search(" in app_py)
    i_add = app_py.find("history.add_search(")
    around2 = app_py[max(0, i_add - 400):i_add]
    check("history.add_search 也包在 try 里", "try:" in around2)
    # hits 必须传"成书数"而不是原始候选数 —— 见 history.py 的注释
    check("add_search 传了 hits=len(books)", "hits=len(books)" in app_py,
          "hits 口径错了：只有成书数为 0 才说明书库缺口")

    print("\n—— 4. 前端接线：mountHistory 真被调用 ——")
    check("history.js 导出了 mountHistory", "export function mountHistory" in hist_js)
    check("main.js import 了它", "mountHistory" in main_js and "from \"./history.js\"" in main_js)
    check("main.js 里真的调用了 mountHistory()",
          re.search(r"^\s*mountHistory\(\)", main_js, re.M) is not None,
          "只 import 不调用 = 下拉永远不出现")
    check("mountHistory 在 mountDiscover 之后调用（DOM 顺序）",
          main_js.find("mountDiscover()") < main_js.find("mountHistory()"))

    print("\n—— 5. 下拉的关键行为还在 ——")
    check("拉取 /api/history/search", '/api/history/search' in hist_js)
    check("聚焦时拉历史", re.search(r'addEventListener\("focus"', hist_js) is not None)
    check("点历史词会派发 Enter（复用搜索主路径）", 'key: "Enter"' in hist_js)
    check("有延迟收起（否则 blur 抢先、点不中）", "closeSoon" in hist_js and "setTimeout" in hist_js)
    check("键盘支持 ↑↓", 'ArrowDown' in hist_js and 'ArrowUp' in hist_js)
    check("键盘支持 Esc", 'Escape' in hist_js)
    # ⚠ 删单条必须 stopPropagation，否则删完会顺带触发条目点击 = 又搜一次
    i_del = hist_js.find('act === "del"')
    around3 = hist_js[i_del:i_del + 400]
    check("删单条 stopPropagation（否则删完又搜一次）", "stopPropagation" in around3)
    check("包裹 .h-wrap（否则 absolute 会跑到整页宽）", 'className = "h-wrap"' in hist_js)
    check("包 h-wrap 时把 .searchbox 挪进去", "wrap.appendChild(host)" in hist_js)
    # ⚠ 下拉里的"清空"必须二次确认 —— 它是不可逆的，且按钮就在搜索框下方，
    #   比统计页签那两个更容易误触。两处同样的动作（清空搜索历史）行为要一致。
    check("下拉「清空」有二次确认（不可逆，防误触）",
          re.search(r"async function clearAll[\s\S]{0,400}?confirmBox\(", hist_js)
          is not None,
          "清空搜索历史没确认就删了 —— 手滑一下全没")
    check("下拉「清空」的确认框标了 danger", 
          re.search(r"async function clearAll[\s\S]{0,500}?danger: true", hist_js)
          is not None)

    print("\n—— 6. CSS 类名对得上 ——")
    # 前端造的类名，必须都能在 CSS 里找到 —— 否则样式不生效（不报错）
    for cls in [".h-wrap", ".h-drop", ".h-head", ".h-item", ".h-kw", ".h-x", ".h-clear"]:
        check(f"CSS 有 {cls}", cls in css)
    for cls in [".stgrid", ".stcell", ".stsec", ".stchips", ".stchip", ".strow"]:
        check(f"CSS 有 {cls}", cls in css)
    # history.js 用到的类名必须与 CSS 一致（防止改名漏改一处）
    check("history.js 里的 h-item 与 CSS 同名", 'class="h-item' in hist_js or "h-item" in hist_js)
    check("下拉 hidden 时真的隐藏", ".h-drop[hidden]" in css)
    check("下拉有 z-index（不能被搜索结果盖住）",
          re.search(r"\.h-drop\{[^}]*z-index", css, re.S) is not None)

    print("\n—— 7. 统计页签接线 ——")
    check("sources.js 有 renderStats", "function renderStats" in src_js)
    check("统计 tab 按钮存在", 'data-tab="stats"' in src_js)
    check("renderTab 会分发到 stats", 'tab === "stats"' in src_js)
    check("拉 /api/visits/stats", "/api/visits/stats" in src_js)
    check("拉 /api/history/search/stats", "/api/history/search/stats" in src_js)
    check("清空走 confirmBox 二次确认", "confirmBox({" in src_js)
    # ⚠ openSources 的白名单必须接受 stats，否则深链 #stats 会落回默认页
    check("openSources 接受 stats 参数",
          re.search(r'initialTab === "stats"', src_js) is not None)
    check("深链 #stats 已接（main.js）", '"#stats"' in main_js)
    check("关抽屉时 #stats 也会清 hash",
          re.search(r"#\(sources\|registry\|stats\)", src_js) is not None,
          "drawer:closed 里的正则没跟上新 hash")

    print("\n—— 7b. 热词榜：接了、且挂了不拖垮整页 ——")
    # 后端这个接口早就写好了，但前端一直没人消费 —— 钉住"真接了"。
    check("拉 /api/history/search/hot", "/api/history/search/hot" in src_js,
          "热词榜没接上，后台接口白写")
    check("热词 chip 带 data-hot（可点）", "data-hot" in src_js)
    # ⚠ 关键：热词榜必须**单独兜错**，不能进 Promise.all 的必败链。
    #   Promise.all 一损俱损 —— 热词接口挂掉会让四格数字 + 访客明细
    #   一起消失，那是把"锦上添花"做成了"单点故障"。
    check("热词请求单独 catch（挂了不拖垮整个统计面板）",
          re.search(r"soft\(\s*api\.get\(\"/api/history/search/hot", src_js)
          is not None,
          "热词又裸进 Promise.all 了 —— 它一挂整页就没数字了")
    # 点热词必须复用主搜索（填回 #q + 派发 Enter），不能自己另写一套
    check("点热词填回 #q（复用主搜索流程）", 'q.value = el.dataset.hot' in src_js)
    check("点热词派发 Enter（走主搜索，不另写一套）",
          'new KeyboardEvent("keydown", { key: "Enter"' in src_js)
    check("点热词后收抽屉（不挡结果）", "__wbClose" in src_js,
          "直接 remove() 会留下挂在 document 上的孤儿 Esc 监听")
    check("热词 chip 有可点样式 .click", ".stchip.click" in css,
          "没有 cursor/hover，用户不会知道它可点")

    print("\n—— 8. 埋点登记表同步 ——")
    for ev in ["history.del", "history.clear", '"visits.clear"', "visits.load.fail"]:
        check(f"EVENTS 登记了 {ev}", ev in events_py)

    print("\n—— 8b. 删单条走查询参数（路径段放不下斜杠）——")
    # ⚠ 这是一条**回归防线**，对应一个真实踩过的 bug：
    #   最初把删单条写成 `DELETE /api/history/search/{kw}`，
    #   而书名带斜杠非常常见（"哈利波特/魔法石"、"斗破苍穹/之万界商城"）。
    #   实测 `/api/history/search/aaa%2Fbbb` 和 `/api/history/search/aa/bb`
    #   **都返回 404**（%2F 被 Starlette 解码后拿去匹配路由，匹配不上）。
    #   改成 `?kw=` 查询参数就没这个问题。
    #   下面两条断言把"不要再改回路径参数"钉死。
    check("后端删单条用查询参数 kw（不是路径段）",
          re.search(r'@app\.delete\("/api/history/search"\)\s*\n\s*async def \w+\(kw: str', app_py)
          is not None,
          "路由签名变了？删单条必须吃 kw 查询参数")
    check("后端**没有** /{kw} 路径参数路由（那会漏掉带斜杠的词）",
          '@app.delete("/api/history/search/{kw}")' not in app_py,
          "又写回路径参数了 —— 带斜杠的书名会删不掉（404）")
    check("前端删单条用 ?kw= 拼 query",
          "/api/history/search?kw=" in hist_js,
          "前端还在拼路径段")

    print("\n—— 9. 数据文件不进代码包（避免把本地数据推上线）——")
    pack = read(ROOT / "tools" / "pack.py")
    if pack:
        check("pack 排除了 cache/（history.json/visits.json 在里面）",
              "cache" in pack, "pack.py 没排 cache，本地统计会被推到线上覆盖")
    else:
        check("tools/pack.py 可读", False)

    print("\n" + "=" * 62)
    print(f"通过 {ok_n} · 失败 {fail_n}")
    print("=" * 62)
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
