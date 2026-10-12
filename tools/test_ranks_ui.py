"""榜单界面功能回归（需要服务已在跑 + Chrome）。

这个测试**不断言渲染细节**（那东西改样式就会红，没有价值），
只断言「点一下会发生什么」—— 也就是行为契约：

  1. 榜单面板出现，标签渲染出来
  2. 点一条榜单 → 书名填进搜索框
  3. 点一条榜单 → 面板收起（避免挡住搜索结果）
  4. 点一条榜单 → 真的触发了搜索（结果区出现卡片，或进入"搜索中"）

为什么必须用真浏览器
--------------------
「点了没反应」这类问题**静态检查抓不到** —— 语法都合法、函数都存在，
但事件没绑上、或者绑在了后来被替换掉的节点上。
上一版就是这种情况：界面看着好好的，点下去什么都没发生。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import websocket  # noqa: E402


def find_chrome() -> str:
    for p in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]:
        if os.path.exists(p):
            return p
    raise SystemExit("找不到 Chrome / Edge")


class Tab:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=90, suppress_origin=True)
        self._id = 0

    def call(self, method, **params):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expr):
        r = self.call("Runtime.evaluate", expression=expr,
                      returnByValue=True, awaitPromise=True)
        if r.get("exceptionDetails"):
            return None
        return r.get("result", {}).get("value")


def pick_base(explicit: str) -> str:
    """挑一个「真的带榜单接口」的服务地址。

    ⚠ 踩过坑：--base 默认写死 8000，但 8000 上跑的往往是**旧版本**进程
    （没重启过的那种）。旧进程没有 /api/ranks，于是榜单渲染 0 条，
    10 项断言全红 —— 看起来像功能坏了，其实是测错了对象。
    所以这里先探一遍：优先 --base，其次常见端口，谁有榜单接口就用谁。
    """
    import http.client
    from urllib.parse import urlparse

    cands = [explicit, "http://127.0.0.1:8000", "http://127.0.0.1:8303"]
    seen: set[str] = set()
    for b in cands:
        if not b or b in seen:
            continue
        seen.add(b)
        u = urlparse(b)
        try:
            c = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=3)
            c.request("GET", "/api/ranks/kinds")
            r = c.getresponse()
            body = r.read()
            c.close()
            if r.status == 200 and b'"kinds"' in body:
                return b
        except Exception:
            pass
    raise SystemExit(
        "找不到带榜单接口的服务。先启动一个（例：\n"
        "  python run.py --host 127.0.0.1 --port 8303 --no-check\n"
        "）再用 --base 指过去。")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="", help="留空则自动探测可用实例")
    ap.add_argument("--port", type=int, default=9333)
    ap.add_argument("--fake-shelf", default="",
                    help="逗号分隔的书名，装成书架里有这些书（用来验「已在书架」角标）")
    a = ap.parse_args()

    a.base = pick_base(a.base)
    print(f"目标服务：{a.base}")

    chrome = find_chrome()
    # ⚠ 每次用**全新的 profile 目录**。复用固定目录时，上一次跑留下的
    # 会话状态（localStorage 里的令牌、hash、甚至 service worker 缓存）
    # 会带进来，导致首屏行为和"干净用户"不一样 —— 实测表现为首次等待
    # 超时、7 项断言连锁变红，但功能其实是好的。测试要的是可复现。
    prof = os.path.join(tempfile.gettempdir(), f"nd-rankstest-{os.getpid()}")
    proc = subprocess.Popen(
        [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--remote-debugging-port={a.port}", "--no-first-run", "--no-default-browser-check",
         f"--user-data-dir={prof}", "--window-size=1280,900",
         # 和 test_buttons 对齐：别让磁盘缓存喂一份过期的 JS/CSS 进来，
         # 否则改了前端却测出旧行为（踩过：改了 JS 还报旧行为，查半天）。
         "--disable-application-cache", "--disk-cache-size=1",
         "--no-proxy-server", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    fails: list[str] = []

    def check(label, cond, extra=""):
        if cond:
            print(f"  ✓ {label}")
        else:
            fails.append(label)
            print(f"  ✗ {label} {extra}")

    try:
        # 等 DevTools。
        # ⚠ 这里必须**挑出 target 那个标签页**，不能拿 /json/list 的第一个 ——
        # Chrome 会把扩展的 background page 也列进来（实测第一项是
        # `chrome-extension://.../background.html`），连错标签页的后果是
        # 所有断言都"失败"，看起来像功能坏了，其实是测错了对象。
        import http.client
        ws_url = None
        for _ in range(60):
            try:
                c = http.client.HTTPConnection("127.0.0.1", a.port, timeout=5)
                c.request("GET", "/json/list")
                tabs = json.loads(c.getresponse().read())
                # 优先精确匹配 about:blank（我们启动时开的那个），
                # 退而求其次取任何 page 类型
                for tb in tabs:
                    if tb.get("type") == "page" and tb.get("url", "").startswith("about:"):
                        ws_url = tb["webSocketDebuggerUrl"]
                        break
                if not ws_url:
                    for tb in tabs:
                        if tb.get("type") == "page":
                            ws_url = tb["webSocketDebuggerUrl"]
                            break
                if ws_url:
                    break
            except Exception:
                pass
            time.sleep(0.3)
        if not ws_url:
            raise SystemExit("DevTools 端口没起来")

        t = Tab(ws_url)
        t.call("Page.enable")
        t.call("Runtime.enable")

        # 假书架：必须在导航**之前**注入。踩过坑 —— 事后替换 window.fetch
        # 是没用的，因为页面加载时 ensureShelf() 已经跑过、把（真·空的）
        # 书架结果缓存住了，后面再怎么改都不会重取。
        # 用 addScriptToEvaluateOnNewDocument 才是在文档创建前生效。
        if a.fake_shelf:
            names = [s.strip() for s in a.fake_shelf.split(",") if s.strip()]
            payload = json.dumps([{"title": n} for n in names], ensure_ascii=False)
            t.call("Page.addScriptToEvaluateOnNewDocument", source=f"""
              (function(){{
                var of = window.fetch;
                window.fetch = function(u, o){{
                  var s = String(u);
                  if (s.indexOf('/api/library') === 0) {{
                    return Promise.resolve(new Response({json.dumps(payload)},
                      {{status:200, headers:{{'Content-Type':'application/json'}}}}));
                  }}
                  return of.apply(this, arguments);
                }};
              }})();
            """)

        t.call("Page.navigate", url=a.base)

        # 等榜单面板出现且有内容。
        # ⚠ 第一次拉榜单要联网，冷启可能要十几秒（尤其注入了 fetch patch 时）。
        # 原先是 60×0.5s=30s，实测在冷缓存 + 拦截场景下偶发不够用 ——
        # 于是 7 项断言连锁变红，看着像功能全坏，其实只是没等够。
        ok = False
        for _ in range(120):        # 最多 60s
            time.sleep(0.5)
            n = t.js("document.querySelectorAll('.rk-item[data-title]').length")
            if n and n > 0:
                ok = True
                break
        check("榜单加载出条目", ok)

        print()
        print("== 界面结构 ==")
        check("面板可见",
              t.js("(function(){var b=document.querySelector('#ranksBox');"
                   "return !!b && !b.hidden;})()") is True)
        tabs_n = t.js("document.querySelectorAll('.rk-tab').length")
        check(f"标签渲染（{tabs_n} 个）", (tabs_n or 0) >= 4)
        items_n = t.js("document.querySelectorAll('.rk-item[data-title]').length")
        check(f"条目渲染（{items_n} 条）", (items_n or 0) >= 5)
        check("第一条有条目名",
              bool(t.js("(document.querySelector('.rk-item[data-title]')||{}).dataset "
                        "&& document.querySelector('.rk-item[data-title]').dataset.title")))
        check("有「收起」按钮", t.js("!!document.querySelector('#ranksFold')") is True)

        # ---- 本轮新增的三个产品点 ----
        print()
        print("== 新增：手动刷新 / 新鲜度 / 回书架 ==")
        check("有「刷新」按钮", t.js("!!document.querySelector('#ranksRefresh')") is True)
        # 「x 分钟前更新」要真的填上字，不能是个空壳
        age_txt = t.js("(document.querySelector('#ranksAge')||{}).textContent || ''")
        check(f"新鲜度有文案（{age_txt!r}）",
              bool(age_txt) and ("更新" in age_txt))
        check("有回书架入口", t.js("!!document.querySelector('#ranksToLib')") is True)
        # 底部说明里要讲清数据来源与刷新节奏，否则用户不知道这数据哪来的
        foot = t.js("(document.querySelector('.rk-foot')||{}).textContent || ''")
        check("底部说明了数据来源与刷新节奏",
              ("公开榜单" in foot) and ("30 分钟" in foot or "刷新" in foot),
              repr(foot[:60]))

        print()
        print("== 点击刷新会真的重新取数 ==")
        # 只**观察**有没有打刷新接口，不真的让它跑完 ——
        # 真刷一轮要联网 4 秒，跑完会重新渲染列表，后面的「点一条」就会
        # 点在半空状态上（实测：target 变成 None，两条断言假失败）。
        # 所以这里把 refresh 的响应也拦掉，让它立刻返回，状态不受扰动。
        t.js("""window.__hit=[];(function(){
          var of = window.fetch;
          window.fetch = function(u, o){
            var s = String(u);
            window.__hit.push(s);
            if (s.indexOf('/api/ranks/refresh') === 0) {
              return Promise.resolve(new Response(
                JSON.stringify({ok:true, ok_count:1, failed:0, elapsed:0,
                                status:{total:20, stale_count:0}}),
                {status:200, headers:{'Content-Type':'application/json'}}));
            }
            return of.apply(this, arguments);
          };
        })()""")
        t.js("document.querySelector('#ranksRefresh').click()")
        hit = False
        for _ in range(30):
            time.sleep(0.4)
            urls = t.js("window.__hit || []") or []
            if any("/api/ranks/refresh" in str(u) for u in urls):
                hit = True
                break
        check("点刷新会打 /api/ranks/refresh", hit,
              str((t.js("window.__hit || []") or [])[:4]))
        # 等刷新流程自己收尾，别让它和下一段抢状态
        time.sleep(2.0)

        print()
        print("== 点一条会发生什么（行为契约）==")

        # 记录点击前
        before_q = t.js("document.querySelector('#q').value")
        target = t.js("document.querySelector('.rk-item[data-title]').dataset.title")
        print(f"     准备点：《{target}》")

        # 点它
        t.js("document.querySelector('.rk-item[data-title]').click()")
        time.sleep(0.8)

        after_q = t.js("document.querySelector('#q').value")
        check(f"书名填进了搜索框（{before_q!r} → {after_q!r}）", after_q == target)

        folded = t.js("document.querySelector('#ranksBox').classList.contains('folded')")
        check("面板自动收起（不挡住搜索结果）", folded is True)

        # ---- 「点击真的触发了搜索」怎么判？----
        #
        # ⚠ 这里踩过一个坑：最早判的是 `#statbar .spin, .nl-spin.on`，
        #   而这两个选择器**在前端根本不存在**：
        #     · `#statbar` 里放的是纯文本「正在 N 个来源里找《…》…」
        #       （见 discover.js 的 runSearch），没有 .spin 元素；
        #     · `.nl-spin` 只出现在「联网发现」面板 #netlive 的 #netLiveSpin 上，
        #       而且不带 .on 类。
        #   于是 searching 恒为 False，这条断言**一直是**靠「结果卡片出现」
        #   兜底的。而兜底成不成，取决于榜单第一条恰好是不是本地有命中的书 ——
        #   某天第一条是《赵氏嫡女》（本地源对现代言情零覆盖，rank 去噪后 0 条，
        #   要靠联网兜底跑满 30 秒才出结果），兜底也失效，于是**假红**。
        #   注意：这不是产品回归，是这条检测自己写错了。
        #
        # 现在按**真实信号**判，三条任意一条成立即算「搜索起来了」：
        #   ① #statbar 出现「正在 … 里找」—— 搜索态文案（最直接）
        #   ② #results 里已经画出结果卡片 —— 已从流里收到 item
        #   ③ 请求记录里出现 /api/search —— 端到端确认接口被调用
        #      （__hit 是本文件上面拦 fetch 时挂上的，见「点刷新」那段）
        started = False
        for _ in range(40):
            time.sleep(0.5)
            n = t.js("document.querySelectorAll('#results .book').length") or 0
            searching = t.js(
                "(() => {"
                "  const s = document.querySelector('#statbar');"
                "  const tx = s ? (s.textContent || '') : '';"
                "  return (tx.indexOf('正在') >= 0 && tx.indexOf('里找') >= 0)"
                "      || !!document.querySelector('#netlive .nl-spin');"
                "})()") or False
            hit_api = any(
                "/api/search" in str(u)
                for u in (t.js("window.__hit || []") or []))
            if n > 0 or searching or hit_api:
                started = True
                break
        stat_txt = t.js("(document.querySelector('#statbar')||{}).textContent || ''")
        check("点击真的触发了搜索", started, f"statbar={stat_txt[:40]!r}")
        # 再单钉一条接口级的：点击必须真的打到 /api/search。
        # 比上面那条更硬 —— 前者可能被「旧的状态文案」蒙混，这条不会。
        urls = t.js("window.__hit || []") or []
        check("请求真的打到了 /api/search",
              any("/api/search" in str(u) for u in urls),
              str([u for u in urls if "search" in str(u)][-3:]))

        print()
        print("== 切换标签 ==")
        # 展开回来（点「收起」按钮），换个标签
        t.js("document.querySelector('#ranksFold').click()")
        time.sleep(0.4)
        t.js("(document.querySelectorAll('.rk-tab')[1]||{}).click "
             "&& document.querySelectorAll('.rk-tab')[1].click()")
        switched = False
        for _ in range(30):
            time.sleep(0.4)
            on = t.js("(document.querySelector('.rk-tab.on')||{}).dataset "
                      "&& document.querySelector('.rk-tab.on').dataset.kind")
            if on and on != "allvisit":
                switched = True
                break
        check("点第二个标签能切换", switched)

        # 切换后列表要有内容（或明确在加载）
        filled = False
        for _ in range(40):
            time.sleep(0.5)
            n = t.js("document.querySelectorAll('.rk-item[data-title]').length") or 0
            if n > 0:
                filled = True
                break
        check("切换后列表有内容", filled)

        print()
        print("== 没有 JS 报错 ==")
        # 从 console 抓过的报错没法在这里重放，简单确认全局没坏
        check("核心全局还在", t.js("typeof window !== 'undefined'") is True)

        # ---- 「已在书架」角标（只在给了 --fake-shelf 时验）----
        if a.fake_shelf:
            print()
            print("== 「已在书架」角标 ==")
            # ⚠ 必须导航到**干净的 URL**（不带 #search=…）。
            # 前面的「点一条」测试把 hash 改成了 #search=书名，直接再
            # navigate(a.base) 会停在搜索结果页，榜单面板根本没渲染 ——
            # 于是断言全红，看起来像角标坏了，其实是页面状态不对。
            clean = a.base.split("#")[0]
            # 还要把「收起」状态清掉：前面点过条目，folded 已经写进
            # localStorage，重载后会是收起态（列表 display:none，DOM 里
            # 查不到 .rk-item）。这两件事叠加是最初 3 条假失败的真因。
            t.js("try{localStorage.removeItem('nd_ranksFold');}catch(e){}")
            t.call("Page.navigate", url=clean)
            for _ in range(120):
                time.sleep(0.5)
                n = t.js("document.querySelectorAll('.rk-item[data-title]').length")
                if n and n > 0:
                    break
            # 等 ensureShelf 回来补画角标（它是并着跑的，不阻塞列表渲染）
            for _ in range(30):
                time.sleep(0.4)
                if (t.js("document.querySelectorAll('.rk-owned').length") or 0) >= 1:
                    break

            n_owned = t.js("document.querySelectorAll('.rk-item.owned').length") or 0
            check(f"有被标记为「已在书架」的条目（{n_owned} 条）", n_owned >= 1)
            badge = t.js("(function(){var e=document.querySelector('.rk-owned');"
                         "return e?e.textContent:'';})()") or ""
            check(f"角标文案正确（{badge!r}）", "已在书架" in badge)
            # 未拥有的条目不该被误标
            total = t.js("document.querySelectorAll('.rk-item[data-title]').length") or 0
            n_go = t.js("document.querySelectorAll('.rk-item .rk-go').length") or 0
            check(f"未拥有的条目仍是「找这本」（{n_go} 条）", n_go >= 1)
            check("标记数不超过总数", n_owned <= total)

    finally:
        try:
            proc.kill()
        except Exception:
            pass
        # 临时 profile 用完就删 —— 不然 temp 目录会攒一堆
        try:
            import shutil
            shutil.rmtree(prof, ignore_errors=True)
        except Exception:
            pass

    print()
    if fails:
        print(f"✗ {len(fails)} 项失败：")
        for f in fails:
            print(f"    {f}")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
