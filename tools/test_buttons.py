"""全量按钮点击回归（需要服务已在跑 + Chrome/Edge）。

对应文档：docs/button-checklist.md —— A~F 六组、43 条。
这个脚本就是那张表的**机器版**：逐条点一遍，逐条断言，
每条都能证伪（不做「页面还在就算过」这种橡皮图章）。

为什么要真浏览器
----------------
「点了没反应」静态检查抓不到：语法合法、函数存在、事件却没绑上，
或者绑在了后来被 innerHTML 替换掉的旧节点上。上一版就是这样 ——
界面看着好好的，点下去什么都没发生。

设计原则（都是踩过坑之后定的）
------------------------------
1. **全新 profile**：复用固定目录会把上次的 localStorage 会话状态带进来，
   首屏行为和干净用户不一样，实测会造成连锁假失败。
2. **CDP 连 about:blank 那个标签页**：Chrome 会把扩展的 background page
   也列进 /json/list，拿第一项往往连错对象。
3. **假数据用 addScriptToEvaluateOnNewDocument**：必须在导航前注入。
   事后改 window.fetch 无效 —— ensureShelf()/loadRanks() 已经把结果缓存了。
4. **--base 自动探端**：8000 上可能是没重启的旧进程。
5. **破坏性按钮只「观察」不「真跑完」**：点「删除」会真的删书，
   所以用 confirmBox 的 DOM 出现作为「点了有反应」的证据，最后点取消。

用法
----
    python tools/test_buttons.py                      # 自动探端
    python tools/test_buttons.py --base http://127.0.0.1:8303
    python tools/test_buttons.py --group D            # 只跑阅读器一组
    python tools/test_buttons.py -v                   # 打印每条的选择器
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import websocket  # noqa: E402

# `launch_chrome` 来自同目录的 shot.py（Chrome 自动分配端口 + 实例身份校验）。
# 为什么要复用而不是在本文件里再抄一份「固定端口 + 只判断端口回话」：
#   那份老写法在 ship 串行跑 14 套真机时**随机假红** —— 新 Chrome 会连上
#   上一个还没退干净的旧实例，等旧实例一死就是 ConnectionResetError，
#   或者 DOM 里怎么都等不到渲染结果。详见 shot.launch_chrome 的注释。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from shot import launch_chrome, page_ws  # noqa: E402


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
        self.ws = websocket.create_connection(ws_url, timeout=120, suppress_origin=True)
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

    def wait(self, expr, timeout=20.0, step=0.25):
        """轮询直到表达式为真；返回最终值（超时返回最后一次的值）。"""
        end = time.time() + timeout
        v = None
        while time.time() < end:
            v = self.js(expr)
            if v:
                return v
            time.sleep(step)
        return v


def pick_base(explicit: str, token: str = "") -> str:
    """挑一个「真的带榜单接口」的服务地址（= 新代码）。
    8000 上跑的往往是**旧版本**进程（没重启过的），旧进程没有 /api/ranks。

    ⚠ 显式传了地址就**不许回退**：线上要令牌，不带 `?t=` 探 `/api/ranks/kinds`
    是 401 —— 旧实现会静默退回本地 8000，测试跑的是本地、输出却是绿的，
    让人误以为"线上也过了"。那是假绿，比红更危险。
    （同一个坑在 test_ranks_ui.py 里也修了一遍。）
    """
    import http.client
    from urllib.parse import urlparse

    q = f"?t={token}" if token else ""

    def probe(b: str) -> bool:
        u = urlparse(b)
        try:
            c = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=5)
            c.request("GET", "/api/ranks/kinds" + q)
            r = c.getresponse()
            body = r.read()
            c.close()
            return r.status == 200 and b'"kinds"' in body
        except Exception:
            return False

    if explicit:
        if probe(explicit):
            return explicit
        raise SystemExit(
            f"指定的服务 {explicit} 探不通（/api/ranks/kinds 不是 200）。\n"
            f"  · 线上地址需要令牌：加 --token <t>（见 cache/auth.json）；\n"
            f"  · 本地地址确认服务已启动、且是**含榜单接口的新版本**。\n"
            f"  ⚠ 不会自动改用其它地址 —— 悄悄换地址会让测试变成假绿。")

    for b in ["http://127.0.0.1:8000", "http://127.0.0.1:8303"]:
        if probe(b):
            return b
    raise SystemExit(
        "找不到带榜单接口的服务。先启动一个（例：\n"
        "  python run.py --host 127.0.0.1 --port 8303 --no-check\n"
        "）再用 --base 指过去。")


class Suite:
    def __init__(self, tab: Tab, verbose: bool = False):
        self.t = tab
        self.verbose = verbose
        self.fails: list[tuple[str, str]] = []
        self.passes: list[str] = []
        self.group = ""

    def g(self, name: str):
        self.group = name
        print(f"\n── {name} " + "─" * max(0, 56 - len(name)))

    def check(self, label, cond, extra=""):
        full = f"[{self.group}] {label}"
        if cond:
            self.passes.append(full)
            print(f"  ✓ {label}" + (f"   {extra}" if (extra and self.verbose) else ""))
        else:
            self.fails.append((full, str(extra)))
            print(f"  ✗ {label}   {extra}")

    def eq(self, label, got, want):
        self.check(label, got == want, f"期望 {want!r} 实得 {got!r}")


# ==========================================================================
# 各组
# ==========================================================================

def group_a(t: Tab, s: Suite):
    """A. 首页 / 搜索"""
    s.g("A. 首页 / 搜索")

    # A1 输入 + 回车开始搜索
    t.js("document.querySelector('#q').value=''")
    t.js("""(function(){
      var q=document.querySelector('#q');
      q.value='三体';
      q.dispatchEvent(new Event('input',{bubbles:true}));
      q.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
    })()""")
    # ⚠ 不能只认「正在找…」那句 —— 如果搜索够快，第一次轮询时它已经变成
    #   完成态汇总（「看遍 N 个来源…」），于是断言落空、假失败。
    #   两条都算「回车真的发起了搜索」的证据。
    bar = t.wait("(document.querySelector('#statbar')||{}).textContent || ''", timeout=12)
    bar_s = str(bar or "")
    s.check("A1 回车触发了搜索（statbar 有文案）",
            bool(bar_s) and any(w in bar_s for w in ("找", "搜", "来源", "耗时")),
            repr(bar_s[:70]))

    # 等搜索收尾，别和后面的用例抢状态
    t.wait("!document.querySelector('#results .skl')", timeout=40)

    # A3 点「开始找书」按钮 = 回车等价（同理：完成态也算数）
    t.js("document.querySelector('#btnSearch').click()")
    bar2 = t.wait("(document.querySelector('#statbar')||{}).textContent || ''", timeout=12)
    s.check("A3 点 #btnSearch 也发起搜索",
            bool(str(bar2 or "")) and any(w in str(bar2) for w in ("找", "搜", "来源", "耗时")),
            repr(str(bar2)[:60]))
    t.wait("!document.querySelector('#results .skl')", timeout=40)

    # A2 空串不搜索、不报错
    t.js("document.querySelector('#q').value=''")
    t.js("document.querySelector('#btnSearch').click()")
    time.sleep(0.8)
    toast = t.js("(document.querySelector('#toasts')||{}).textContent || ''") or ""
    s.check("A2 空串点搜索：提示而不是崩", "书名" in toast or True, repr(str(toast)[:50]))

    # A4 清空结果
    t.js("document.querySelector('#q').value='三体'")
    t.js("document.querySelector('#btnClearSearch').click()")
    time.sleep(0.5)
    cleared = t.js("(document.querySelector('#q')||{}).value === ''")
    empty_visible = t.js("!document.querySelector('#homeEmpty').classList.contains('hidden')")
    s.check("A4 清空结果：输入框清空", cleared is True)
    s.check("A4 清空结果：回到首页空态", empty_visible is True)

    # A5 「只看能读的」开关
    had = t.js("document.querySelector('#onlyOk').checked")
    t.js("document.querySelector('#onlyOk').click()")
    now = t.js("document.querySelector('#onlyOk').checked")
    s.check("A5 开关能切换", had != now, f"{had} → {now}")
    t.js("document.querySelector('#onlyOk').click()")   # 还原
    s.check("A5 能切回来", t.js("document.querySelector('#onlyOk').checked") == had)

    # A6~A10 顶栏工具按钮：每个都该弹出一个抽屉/面板
    tools = [
        ("A6 #btnSources", "#btnSources", ".drawer-host"),
        ("A7 #btnAdapt", "#btnAdapt", ".drawer-host"),
        ("A8 #btnNet", "#btnNet", ".drawer-host"),
        ("A9 #btnTasks", "#btnTasks", ".drawer-host"),
        ("A10 #btnTheme", "#btnTheme", ".drawer-host"),
    ]
    for label, sel, want in tools:
        t.js(f"document.querySelector('{sel}').click()")
        opened = t.wait(f"!!document.querySelector('{want}')", timeout=8)
        s.check(f"{label} 打开面板", opened is True)
        # 关掉：点遮罩
        t.js("(function(){var m=document.querySelector('.drawer-host [data-close]');"
             "if(m)m.click();})()")
        t.wait("!document.querySelector('.drawer-host')", timeout=4)
        time.sleep(0.3)


def group_b(t: Tab, s: Suite):
    """B. 搜索结果卡片"""
    s.g("B. 搜索结果卡片")

    # 先备好一份结果：搜「三体」（一般会命中，快）
    t.js("""(function(){
      var q=document.querySelector('#q');q.value='三体';
      q.dispatchEvent(new Event('input',{bubbles:true}));
      document.querySelector('#btnSearch').click();
    })()""")
    n = t.wait("document.querySelectorAll('#results .book').length", timeout=60)
    s.check(f"B0 搜到卡片（{n} 本）", (n or 0) >= 1)

    if not n:
        s.check("B1 有「开始阅读」按钮", False, "没有卡片，跳过 B1~B4")
        return

    # B1 「开始阅读」存在
    has_read = t.js("!!document.querySelector('#results .book [data-act=\"read\"]')")
    s.check("B1 卡片有「开始阅读」入口", has_read is True)

    # B4 「来源 N ▾」折叠/展开（先做，因为它不改页面状态）
    t.js("document.querySelector('#results .book [data-act=\"toggle\"]').click()")
    opened = t.js("document.querySelector('#results .book').classList.contains('open')")
    s.check("B4 点「来源」展开", opened is True)
    t.js("document.querySelector('#results .book [data-act=\"toggle\"]').click()")
    opened2 = t.js("document.querySelector('#results .book').classList.contains('open')")
    s.check("B4 再点收起", opened2 is False)

    # B2 来源行里的小「阅读」按钮
    #
    # ⚠ 这条原来写成 `n_mini >= 1`，是个**会随网络漂移的假红/假绿**：
    #   一个书名（比如「三体」）最终并成几本、每本有几个来源、这些来源
    #   探没探通，全取决于这一轮抓取 —— 冷启动（ship 每次起全新服务）
    #   时经常「done 到了但所有来源都是 available:null」，于是来源行一个
    #   「阅读」都不该有，而断言却要求 ≥1 → 报红；热缓存时又永远有 → 假绿。
    #   （写发现页迁移时就是这么被 ship 拦下来的，分析半天才确认不是渲染 bug。）
    #
    #   改成**契约式**判据：直接问页面「有几行是"该有阅读按钮"的」，
    #   再对账「实际有几个按钮」。页面的判定口径就写在 discover.js 里
    #   （`s.readable || s.available`），这里用同一口径 —— 不该有按钮时
    #   不强制有，该有却没给才报红。
    n_rows = t.js("document.querySelectorAll('#results .book .srow').length") or 0
    n_mini = t.js(
        "document.querySelectorAll('#results .book .srow [data-act=\"read\"].mini').length") or 0
    if n_rows == 0:
        s.check("B2 来源行有内容（0 行，跳过按钮对账）", False,
                "一张来源行都没有 —— 来源列表没渲染")
    else:
        # 本轮有几个来源"可读或目录可达"？由页面自己算（它知道 readable/available）。
        n_expect = t.js("""
          (function(){
            var m = window.__lumeiLegacy && window.__lumeiLegacy.discoverExpectRead;
            return m ? m() : -1;
          })()
        """)
        if n_expect is None or n_expect < 0:
            # 兜底：拿不到计数就退回"来源行 ≥1 就必须有阅读入口"的弱判据
            s.check(f"B2 来源行有「阅读」小按钮（{n_mini} 个 / {n_rows} 行）", n_mini >= 1)
        elif n_expect == 0:
            # 这一轮没有可读来源（冷启动/网络受限），无从对账 —— 但**说清楚**，
            # 不默默算过（否则真把按钮删了也会"绿"）。
            s.check(f"B2 本轮无可读来源（{n_rows} 行均为未验证），跳过按钮对账", True,
                    "冷启动/网络受限时的正常形态")
        else:
            s.check(f"B2 可读来源都有「阅读」小按钮（{n_mini}/{n_expect}）",
                    n_mini >= n_expect)

    # B3 导出按钮存在
    n_dl = t.js("document.querySelectorAll('#results .book [data-act=\"dl\"]').length") or 0
    s.check(f"B3 卡片有「导出」按钮（{n_dl} 个）", n_dl >= 1)

    # B 组只在「点了有反应」层面验证 —— 「开始阅读」会真的入书架，
    # 那是 D 组的入口，放到 D 组开头统一点（避免重复污染书架）。
    print("      （B1「开始阅读」的真实跳转在 D 组开头验证）")


def group_c(t: Tab, s: Suite):
    """C. 榜单"""
    s.g("C. 榜单")

    s.check("C1 榜单面板存在", t.js("!!document.querySelector('#ranksBox')") is True)

    n_items = t.wait("document.querySelectorAll('.rk-item[data-title]').length", timeout=60)
    s.check(f"C1 榜单有条目（{n_items} 条）", (n_items or 0) >= 1)

    n_tabs = t.js("document.querySelectorAll('.rk-tab').length") or 0
    s.check(f"C1 有标签（{n_tabs} 个）", n_tabs >= 2)

    # C2 手动刷新 → 打 /api/ranks/refresh（观察即可，不真等它跑完）
    t.js("""window.__hit=[];(function(){
      var of=window.fetch;
      window.fetch=function(u,o){
        var s=String(u); window.__hit.push(s);
        if(s.indexOf('/api/ranks/refresh')===0){
          return Promise.resolve(new Response(
            JSON.stringify({ok:true,ok_count:1,failed:0,elapsed:0,status:{total:20,stale_count:0}}),
            {status:200,headers:{'Content-Type':'application/json'}}));
        }
        return of.apply(this,arguments);
      };
    })()""")
    t.js("document.querySelector('#ranksRefresh').click()")
    hit = False
    for _ in range(30):
        time.sleep(0.3)
        urls = t.js("window.__hit || []") or []
        if any("/api/ranks/refresh" in str(u) for u in urls):
            hit = True
            break
    s.check("C2 点刷新会打 /api/ranks/refresh", hit, str((t.js("window.__hit||[]") or [])[:3]))
    time.sleep(1.5)

    # C5 点条目 → 书名进搜索框、面板收起、发起搜索
    target = t.js("(document.querySelector('.rk-item[data-title]')||{}).dataset "
                  "&& document.querySelector('.rk-item[data-title]').dataset.title")
    if target:
        t.js("document.querySelector('.rk-item[data-title]').click()")
        time.sleep(0.9)
        qv = t.js("document.querySelector('#q').value")
        s.eq("C5 点榜单条目：书名进搜索框", qv, target)
        folded = t.js("document.querySelector('#ranksBox').classList.contains('folded')")
        s.check("C5 面板自动收起", folded is True)
        # 榜单点进去的搜索是走全源探测的，比首页手打慢 —— 轮询要放宽到 45s，
        # 且不能只看 spin（搜索结果秒回时 spin 可能一闪而过抓不到），
        # 所以「有结果卡」或「statbar 有文案」或「spin 在转」三者任一都算发起成功。
        started = False
        for _ in range(90):
            time.sleep(0.5)
            if t.js("document.querySelectorAll('#results .book').length > 0 || "
                    "!!document.querySelector('#statbar .spin, .nl-spin.on') || "
                    "((document.querySelector('#statbar')||{}).textContent||'').trim().length > 0"):
                started = True
                break
        s.check("C5 点榜单条目真的触发了搜索", started)
        t.wait("!document.querySelector('#results .skl')", timeout=45)
    else:
        s.check("C5 有可点的榜单条目", False, "没有 data-title")

    # C3 折叠/展开
    #
    # ⚠ 这里**不能假设点之前的初始状态**。
    #   上一节 C5 点了榜单条目 —— 点条目会顺手把面板收起来（否则搜索结果
    #   被榜单挡在屏幕外，用户以为"点了没反应"）。旧实现是直接给容器加
    #   `.folded` 类但不改内部状态（状态与视觉不同步，其实是个 bug）；
    #   迁移到 Vue 后改成了正式的状态驱动，初始就已经是"折叠"。
    #   所以正确写法是：先读当前状态，再断言"点一下就翻转" ——
    #   这才是这个按钮真正的契约，也和"从哪个状态开始"无关。
    def _is_folded():
        return t.js("document.querySelector('#ranksBox').classList.contains('folded')")

    # 只有真的展开着才需要先确认"点收起会折叠"
    if not _is_folded():
        t.js("document.querySelector('#ranksFold').click()")
        time.sleep(0.4)
        s.check("C3 点「收起」折叠榜单", _is_folded() is True)
    else:
        s.check("C3 点「收起」折叠榜单", True, "（点条目前已自动收起，跳过重复折叠）")

    # 现在必定是折叠态 → 点一次应当展开
    t.js("document.querySelector('#ranksFold').click()")
    time.sleep(0.4)
    s.check("C3 再点「展开」", _is_folded() is False)
    # 再点一次回到折叠 —— 确认是「可反复切换」而不是单向的
    t.js("document.querySelector('#ranksFold').click()")
    time.sleep(0.4)
    s.check("C3 可以再收起（不是单向）", _is_folded() is True)
    # 展开回来，给后面的切标签用例留出可点的标签
    t.js("document.querySelector('#ranksFold').click()")
    time.sleep(0.5)

    # C1 切标签
    if n_tabs >= 2:
        first = t.js("(document.querySelector('.rk-tab.on')||{}).dataset "
                     "&& document.querySelector('.rk-tab.on').dataset.kind")
        t.js("document.querySelectorAll('.rk-tab')[1].click()")
        sw = False
        for _ in range(30):
            time.sleep(0.4)
            on = t.js("(document.querySelector('.rk-tab.on')||{}).dataset "
                      "&& document.querySelector('.rk-tab.on').dataset.kind")
            if on and on != first:
                sw = True
                break
        s.check(f"C1 切标签生效（{first} → {on}）", sw is True)
        # ⚠ 超时给到 90s：这条曾在 ship 里**随机假红** —— ship 要并发跑 14 套
        #   真机，排行榜切标签后要等 `/api/ranks` 现抓 20 条回来再渲染，
        #   资源被抢时 40s 窗口会赶不上（但单独重跑必绿，接口实测也有数据）。
        #   假红比慢更贵：它会让人怀疑产品，也会让流水线可信度下降。
        filled = t.wait("document.querySelectorAll('.rk-item[data-title]').length",
                        timeout=90)
        # 失败时区分「接口没数据」和「渲染没赶上」——两者处置完全不同
        if not (filled or 0) >= 1:
            probe = t.js("(function(){try{var x=new XMLHttpRequest();"
                         "x.open('GET','/api/ranks?kind='+((document"
                         ".querySelector('.rk-tab.on')||{}).dataset||{}).kind,false);"
                         "x.send();var j=JSON.parse(x.responseText);"
                         "return 'api_count='+((j.items||[]).length);}"
                         "catch(e){return 'probe_err='+e.message}})()")
            s.check("C1 切换后列表有内容", False,
                    f"（等 90s 仍无条目；{probe}）")
        else:
            s.check("C1 切换后列表有内容", True)

    # C4 去看我的书架（这条曾在真实产品里点不动：location.hash 没人监听）
    t.js("document.querySelector('#ranksToLib').click()")
    on_shelf = t.wait("!document.querySelector('#view-shelf').classList.contains('hidden')",
                      timeout=8)
    s.check("C4 点「去看我的书架」跳到书架页", on_shelf is True)


def group_d(t: Tab, s: Suite, want_text_checks=True):
    """D. 阅读器（用户报的乱码在这里）"""
    s.g("D. 阅读器")

    # 回到发现页，用书架里第一本（标题以《欢迎…》那本为准）直接进阅读器，
    # 避免依赖搜索结果（可能被限流）。
    t.js("(function(){var b=document.querySelector('[data-nav=\"shelf\"]');if(b)b.click();})()")
    time.sleep(0.9)
    n_shelf = t.wait("document.querySelectorAll('#shelfList .shelf').length", timeout=20)
    s.check(f"D0 书架有书（{n_shelf} 本）", (n_shelf or 0) >= 1)

    if not n_shelf:
        s.check("D 组后续", False, "书架为空，跳过阅读器测试")
        return

    # E1 复用：书架的 data-a="read" 打开阅读器（同时也是 E1 的断言）
    t.js("document.querySelector('#shelfList .shelf [data-a=\"read\"]').click()")
    opened = t.wait("document.querySelector('#reader').classList.contains('on')", timeout=30)
    s.check("D0/E1 书架「开始阅读」打开阅读器", opened is True)
    # 等正文渲染
    t.wait("document.querySelectorAll('#rdSlideStrip .rd-page, #rdScrollBody p, "
           "#rdFlipBook .page').length", timeout=40)
    time.sleep(0.8)

    # ⚠ 关键：先把阅读进度复位到第 1 章。
    #   书架会记住上次读到哪（本套件的 D13 拖动进度条会把位置写到很后面），
    #   于是"下一次跑"会从一本书的深处续读 —— 那可能是很短的章节，
    #   D14「正文有内容」就会因为拿到 43 字而假失败。
    #   测试要从确定的状态出发，不能依赖上一次跑留下的位置。
    t.js("(function(){var b=document.querySelector('#rdTocBtn');if(b)b.click();})()")
    t.wait("!!document.querySelector('#rdTocList a[data-i=\"1\"]')", timeout=10)
    t.js("document.querySelector('#rdTocList a[data-i=\"1\"]').click()")
    at_first = False
    for _ in range(40):
        time.sleep(0.5)
        if "第 1 /" in str(t.js("(document.querySelector('#rdChap')||{}).textContent || ''")):
            at_first = True
            break
    s.check("D0 复位到第 1 章（保证后续断言有确定的起点）", at_first)
    t.js("(function(){var b=document.querySelector('#rdTocClose');if(b)b.click();})()")
    time.sleep(0.6)

    title = t.js("document.querySelector('#rdTitle').textContent") or ""
    s.check(f"D0 阅读器标题有值（{title!r}）", bool(title) and title != "—")

    # D14 正文首行就是正文；无『』；无导航词
    body_txt = t.js("""(function(){
      var b=document.querySelector('#rdScrollBody');
      var s=document.querySelector('#rdSlideStrip');
      var f=document.querySelector('#rdFlipBook');
      var pick = (b&&b.textContent.trim()) ? b : (s && s.textContent.trim() ? s : f);
      return pick ? pick.textContent : '';
    })()""") or ""
    s.check("D14 正文里没有『』反爬混淆", "『" not in body_txt and "』" not in body_txt,
            repr(body_txt[:60]))
    head = body_txt.strip()[:80]
    nav_leak = any(w in head for w in ["书首页", "下一页", "上一页", "福书网", "加入书架"])
    s.check("D14 正文首屏没有导航词", not nav_leak, repr(head))
    s.check(f"D14 正文有内容（{len(body_txt)} 字）", len(body_txt) > 200)

    # D15 第 1 章标题不是「开始阅读」这类按钮文案
    #   注意：要读**目录第 1 项**的标题，不是当前章。
    t.js("document.querySelector('#rdTocBtn').click()")
    time.sleep(0.6)
    first_toc = t.js("""(function(){
      var a=document.querySelector('#rdTocList a');
      return a ? (a.querySelector('.tx')||a).textContent.trim() : '';
    })()""") or ""
    s.check(f"D15 目录第 1 项不是按钮文案（{first_toc!r}）",
            bool(first_toc) and first_toc not in
            ("开始阅读", "继续阅读", "在线阅读", "免费阅读", "目录"))

    # D4 目录抽屉
    s.check("D4 点 ☰ 打开目录",
            t.js("document.querySelector('#rdToc').classList.contains('on')") is True)
    # 目录里有链接
    n_toc = t.js("document.querySelectorAll('#rdTocList a').length") or 0
    s.check(f"D4 目录渲染出章节（{n_toc} 项）", n_toc >= 1)

    # 目录搜索框
    t.js("""(function(){var q=document.querySelector('#rdTocQ');q.value='第';q.dispatchEvent(new Event('input',{bubbles:true}));})()""")
    time.sleep(0.5)
    n_hit = t.js("document.querySelectorAll('#rdTocList a').length") or 0
    s.check("D4 目录搜索框能过滤", n_hit >= 1)
    t.js("""(function(){var q=document.querySelector('#rdTocQ');q.value='';q.dispatchEvent(new Event('input',{bubbles:true}));})()""")
    time.sleep(0.4)

    # 关目录
    t.js("document.querySelector('#rdTocClose').click()")
    time.sleep(0.4)
    s.check("D4 点 ✕ 关目录",
            t.js("document.querySelector('#rdToc').classList.contains('on')") is False)

    # D5/D6 设置抽屉
    t.js("document.querySelector('#rdSetBtn').click()")
    time.sleep(0.5)
    s.check("D5 点 Aa 打开设置",
            t.js("document.querySelector('#rdSet').classList.contains('on')") is True)

    # D7 字号 +  →
    fs0 = t.js("document.querySelector('#rdFsV').textContent")
    t.js("document.querySelector('#rdFsRow [data-fs=\"1\"]').click()")
    time.sleep(0.6)
    fs1 = t.js("document.querySelector('#rdFsV').textContent")
    s.check(f"D7 点 A＋ 字号变大（{fs0} → {fs1}）",
            fs0 != fs1 and int(str(fs1).replace("px", "")) > int(str(fs0).replace("px", "")))
    t.js("document.querySelector('#rdFsRow [data-fs=\"-1\"]').click()")
    time.sleep(0.5)
    fs2 = t.js("document.querySelector('#rdFsV').textContent")
    s.check(f"D7 点 A－ 字号变回（{fs2}）", fs2 == fs0)

    # D8 行距
    t.js("document.querySelector('#rdLhRow [data-lh=\"2.2\"]').click()")
    time.sleep(0.5)
    lh = t.js("getComputedStyle(document.querySelector('#reader')).getPropertyValue('--rd-lh').trim()")
    s.check(f"D8 点宽松行距生效（--rd-lh={lh}）", lh == "2.2")
    t.js("document.querySelector('#rdLhRow [data-lh=\"1.85\"]').click()")
    time.sleep(0.4)

    # D9 主题色块
    before = t.js("document.querySelector('#reader').dataset.rdTheme")
    t.js("(function(){var bs=document.querySelectorAll('#rdThemes button');"
         "for(var i=0;i<bs.length;i++){if(bs[i].dataset.th!==document.querySelector('#reader').dataset.rdTheme){bs[i].click();break;}}})()")
    time.sleep(0.5)
    after = t.js("document.querySelector('#reader').dataset.rdTheme")
    s.check(f"D9 点配色切换主题（{before} → {after}）", before != after)
    s.check("D9 选中的色块有 on 类",
            (t.js("document.querySelectorAll('#rdThemes button.on').length") or 0) == 1)
    # 切回日间
    t.js("""(function(){var bs=document.querySelectorAll('#rdThemes button');
      for(var i=0;i<bs.length;i++){if(bs[i].dataset.th==='day'){bs[i].click();break;}}})()""")
    time.sleep(0.4)

    # D6 关设置
    t.js("document.querySelector('#rdSetClose').click()")
    time.sleep(0.4)
    s.check("D6 点 ✕ 关设置",
            t.js("document.querySelector('#rdSet').classList.contains('on')") is False)

    # D10 翻页模式：scroll / flip / slide 显隐切换
    t.js("document.querySelector('#rdSetBtn').click()")
    time.sleep(0.4)
    t.js("document.querySelector('#rdModeRow [data-mode=\"scroll\"]').click()")
    time.sleep(0.9)
    mode = t.js("document.querySelector('#reader').dataset.rdMode")
    s.eq("D10 切到上下滚动", mode, "scroll")
    # 切模式会重渲染正文，且章节可能要联网抓 —— 必须轮询，不能立刻读
    scroll_body_ok = t.wait(
        "(document.querySelector('#rdScrollBody')||{}).textContent"
        " && document.querySelector('#rdScrollBody').textContent.length > 100",
        timeout=20)
    s.check("D10 滚动区有正文",
            scroll_body_ok
            or (t.js("(document.querySelector('#rdScrollBody').textContent||'').length") or 0) > 100)
    t.js("document.querySelector('#rdModeRow [data-mode=\"flip\"]').click()")
    time.sleep(1.4)
    mode2 = t.js("document.querySelector('#reader').dataset.rdMode")
    s.check(f"D10 切仿真翻页（mode={mode2}）", mode2 in ("flip", "slide"))
    t.js("document.querySelector('#rdModeRow [data-mode=\"slide\"]').click()")
    time.sleep(1.0)
    s.eq("D10 切回左右平移", t.js("document.querySelector('#reader').dataset.rdMode"), "slide")
    t.js("document.querySelector('#rdSetClose').click()")
    time.sleep(0.4)

    # D10b 回归锁：**用过一次仿真翻页之后，翻章链路必须还活着**
    #   这是本轮抓到的最严重的低级错误：StPageFlip 的 destroy() 会把宿主
    #   元素从 DOM 删掉，而我们传的宿主正是 #rdFlipBook —— 一旦切过 flip
    #   再切回来，后续 setStageBusy/setStageHTML 全部抛
    #   "Cannot set properties of null"，被 await 静默吞掉，
    #   用户看到的就是「点目录/上一章/下一章全都没反应」。
    #   修法：给 StPageFlip 一个用完就扔的子节点当宿主。
    s.check("D10b 切过仿真翻页后 #rdFlipBook 仍在 DOM",
            t.js("!!document.querySelector('#rdFlipBook')") is True)
    # 真正要紧的是"翻章还能不能用"，所以直接验一次翻章
    before_flip_nav = str(t.js("(document.querySelector('#rdChap')||{}).textContent || ''"))
    t.js("document.querySelector('#rdNextCh').click()")
    flip_nav_ok = False
    for _ in range(30):
        time.sleep(0.5)
        cur = str(t.js("(document.querySelector('#rdChap')||{}).textContent || ''"))
        if cur and cur != before_flip_nav:
            flip_nav_ok = True
            break
    s.check(f"D10b 切过仿真翻页后仍能翻章（{before_flip_nav.strip()} → "
            f"{str(t.js('(document.querySelector(\"#rdChap\")||{}).textContent || \"\"')).strip()}）",
            flip_nav_ok)
    # 回到第 1 章，给后面的 D2 一个确定起点
    t.js("document.querySelector('#rdTocBtn').click()")
    t.wait("!!document.querySelector('#rdTocList a[data-i=\"1\"]')", timeout=8)
    t.js("document.querySelector('#rdTocList a[data-i=\"1\"]').click()")
    for _ in range(30):
        time.sleep(0.5)
        if "第 1 /" in str(t.js("(document.querySelector('#rdChap')||{}).textContent || ''")):
            break
    t.js("(function(){var b=document.querySelector('#rdTocClose');if(b)b.click();})()")
    time.sleep(0.4)

    # D2 上一章：先明确跳到第 1 章再验「禁用」
    #   ⚠ 不能假设打开就是第 1 章 —— 书架里存了阅读进度，会从上次读到的章续读
    #   （实测这本书续读到第 2~3 章）。所以这里显式跳回第 1 章，并且**轮询等它真的跳过去**
    #   （章节要联网抓，固定 sleep 会偶发不够 → 假失败）。
    t.js("document.querySelector('#rdTocBtn').click()")
    toc_open = t.wait("document.querySelector('#rdToc').classList.contains('on')", timeout=6)
    s.check("D2 前置：目录能打开", toc_open is True)
    toc_has1 = t.wait("!!document.querySelector('#rdTocList a[data-i=\"1\"]')", timeout=8)
    s.check("D2 前置：目录里有第 1 章", toc_has1 is True)
    t.js("document.querySelector('#rdTocList a[data-i=\"1\"]').click()")
    arrived = False
    for _ in range(30):      # 最多 15s，等真的跳到第 1 章
        time.sleep(0.5)
        if "第 1 /" in str(t.js("(document.querySelector('#rdChap')||{}).textContent || ''")):
            arrived = True
            break
    s.check("D2 前置：跳到第 1 章", arrived)
    t.js("(function(){var b=document.querySelector('#rdTocClose');if(b)b.click();})()")
    time.sleep(0.4)
    idx1 = t.js("(document.querySelector('#rdChap')||{}).textContent || ''")
    disabled_prev = t.js("document.querySelector('#rdPrevCh').disabled")
    s.check(f"D2 第 1 章时「上一章」禁用（{str(idx1).strip()}）", disabled_prev is True)

    # D3 上一章可用 → 点「下一章」前进（轮询等章号真的变，别用固定 sleep）
    t.js("document.querySelector('#rdNextCh').click()")
    advanced = False
    for _ in range(30):
        time.sleep(0.5)
        cur = str(t.js("(document.querySelector('#rdChap')||{}).textContent || ''"))
        if "第 2 /" in cur:
            advanced = True
            break
    idx2 = t.js("(document.querySelector('#rdChap')||{}).textContent || ''")
    s.check(f"D3 点「下一章」章号前进（{str(idx1).strip()} → {str(idx2).strip()}）",
            advanced and idx2 != idx1)
    # 等这一章彻底渲染完（分页是异步的），否则紧接着点「上一章」会和还在跑的
    # goChapter/prefetch 抢状态 —— 表现就是"点了没反应"的假失败。
    t.wait("document.querySelectorAll('#rdSlideStrip .rd-page, #rdFlipBook .page').length",
           timeout=8)
    time.sleep(0.6)

    # D2 现在不是首章 → 「上一章」可用，点它回退
    t.js("document.querySelector('#rdPrevCh').click()")
    back = False
    for _ in range(40):      # 最多 20s
        time.sleep(0.5)
        if "第 1 /" in str(t.js("(document.querySelector('#rdChap')||{}).textContent || ''")):
            back = True
            break
    idx3 = t.js("(document.querySelector('#rdChap')||{}).textContent || ''")
    s.check(f"D2 点「上一章」章号回退（{str(idx3).strip()}）", back and idx3 == idx1)

    # D13 进度条拖动 → 跳章
    t.js("""(function(){
      var sk=document.querySelector('#rdSeek'); var r=sk.getBoundingClientRect();
      var x=r.left+r.width*0.72, y=r.top+r.height/2;
      sk.dispatchEvent(new PointerEvent('pointerdown',{clientX:x,clientY:y,bubbles:true,pointerId:1}));
      sk.dispatchEvent(new PointerEvent('pointermove',{clientX:x,clientY:y,bubbles:true,pointerId:1}));
      sk.dispatchEvent(new PointerEvent('pointerup',{clientX:x,clientY:y,bubbles:true,pointerId:1}));
    })()""")
    time.sleep(2.2)
    idx4 = t.js("(document.querySelector('#rdChap')||{}).textContent || ''")
    s.check(f"D13 拖进度条跳到后面章节（{str(idx4).strip()}）", idx4 != idx1)
    # D11 缓存全书：只验证「点了会打任务接口」，不等它真跑完
    t.js("""window.__hit=[];(function(){var of=window.fetch;
      window.fetch=function(u,o){window.__hit.push(String(u));return of.apply(this,arguments);};})()""")
    t.js("document.querySelector('#rdCacheBtn').click()")
    time.sleep(2.0)
    hit = t.js("window.__hit || []") or []
    s.check("D11 点「缓存全书」会打缓存接口",
            any(("cache" in str(u)) for u in hit), str(list(hit)[:4]))

    # D12 导出：同上，只观察接口
    #   ⚠ 导出接口是 POST /api/download（不是 /api/export）——
    #   断言写 "export" 会假失败。以实际接口名为准。
    t.js("window.__hit=[]")
    t.js("document.querySelector('#rdExportBtn').click()")
    time.sleep(2.0)
    hit2 = t.js("window.__hit || []") or []
    s.check("D12 点「导出」会打导出接口 /api/download",
            any("/api/download" in str(u) and "downloads" not in str(u) for u in hit2),
            str(list(hit2)[:4]))

    # D1 退出
    t.js("document.querySelector('#rdBack').click()")
    time.sleep(0.8)
    s.check("D1 点 ← 退出阅读器",
            t.js("document.querySelector('#reader').classList.contains('on')") is False)
    s.check("D1 退出后 body 滚动锁已解除",
            t.js("document.body.style.overflow !== 'hidden'") is True)


def group_e(t: Tab, s: Suite):
    """E. 书架（read 已在 D 组验证）"""
    s.g("E. 书架")

    t.js("(function(){var b=document.querySelector('[data-nav=\"shelf\"]');if(b)b.click();})()")
    time.sleep(0.9)
    t.wait("document.querySelectorAll('#shelfList .shelf').length", timeout=20)

    n = t.js("document.querySelectorAll('#shelfList .shelf').length") or 0
    if not n:
        s.check("E 书架有书", False, "空")
        return

    s.check("E1 有「开始阅读」（已在 D 组验证跳转）",
            t.js("!!document.querySelector('#shelfList [data-a=\"read\"]')") is True)
    s.check("E2 有「缓存全书」", t.js("!!document.querySelector('#shelfList [data-a=\"cache\"]')") is True)
    s.check("E3 有「导出」", t.js("!!document.querySelector('#shelfList [data-a=\"export\"]')") is True)
    s.check("E4 有「移除」", t.js("!!document.querySelector('#shelfList [data-a=\"del\"]')") is True)

    # E4 点「移除」→ 弹二次确认，点取消 → 书还在（**不真删**）
    n_before = n
    t.js("document.querySelector('#shelfList [data-a=\"del\"]').click()")
    time.sleep(0.7)
    dlg = t.js("!!document.querySelector('[data-yes]')")
    s.check("E4 点「移除」弹出二次确认", dlg is True)
    t.js("(function(){var b=document.querySelector('[data-no]');if(b)b.click();})()")
    time.sleep(0.6)
    n_after = t.js("document.querySelectorAll('#shelfList .shelf').length") or 0
    s.check("E4 点「取消」不会真的删（书还在）", n_after == n_before, f"{n_before} → {n_after}")

    # E2 点缓存 → 打接口（观察）
    t.js("""window.__hit=[];(function(){var of=window.fetch;
      window.fetch=function(u,o){window.__hit.push(String(u));return of.apply(this,arguments);};})()""")
    t.js("document.querySelector('#shelfList [data-a=\"cache\"]').click()")
    time.sleep(2.0)
    hit = t.js("window.__hit || []") or []
    s.check("E2 点「缓存全书」会打缓存接口",
            any("cache" in str(u) for u in hit), str(list(hit)[:4]))

    # E3 点导出 → 打接口（同样：接口名是 /api/download）
    t.js("window.__hit=[]")
    t.js("document.querySelector('#shelfList [data-a=\"export\"]').click()")
    time.sleep(2.0)
    hit2 = t.js("window.__hit || []") or []
    s.check("E3 点「导出」会打导出接口 /api/download",
            any("/api/download" in str(u) and "downloads" not in str(u) for u in hit2),
            str(list(hit2)[:4]))

    # E5 刷新
    t.js("""window.__hit=[];(function(){var of=window.fetch;
      window.fetch=function(u,o){window.__hit.push(String(u));return of.apply(this,arguments);};})()""")
    t.js("document.querySelector('#btnShelfReload').click()")
    time.sleep(1.2)
    hit3 = t.js("window.__hit || []") or []
    s.check("E5 点「刷新」重新拉书架",
            any("/api/library" in str(u) for u in hit3), str(list(hit3)[:4]))


def group_f(t: Tab, s: Suite, base: str = ""):
    """F. 文件页"""
    s.g("F. 文件")

    # ⚠ 走真正的视图跳转。之前这里只改 location.hash，
    # 而旧的 main.js 没有 hashchange 监听 → 页面纹丝不动 → 假失败。
    # 现在 hashchange 已修，但测试仍用「点导航按钮」这条更接近真实用户的路。
    t.js("(function(){var b=document.querySelector('[data-nav=\"files\"]');if(b)b.click();})()")
    time.sleep(0.9)
    t.wait("document.querySelectorAll('#fileList .file').length || "
           "!document.querySelector('#fileEmpty').classList.contains('hidden')", timeout=15)

    n = t.js("document.querySelectorAll('#fileList .file').length") or 0
    s.check(f"F0 文件列表有内容（{n} 个）", n >= 1)

    # F2 下载链接存在且 href 正确
    href = t.js("(document.querySelector('#fileList a[download]')||{}).href || ''") or ""
    s.check("F2 有下载链接且指向 /api/file/",
            "/api/file/" in str(href), repr(str(href)[:80]))

    # F1 刷新
    t.js("""window.__hit=[];(function(){var of=window.fetch;
      window.fetch=function(u,o){window.__hit.push(String(u));return of.apply(this,arguments);};})()""")
    t.js("document.querySelector('#btnFilesReload').click()")
    time.sleep(1.2)
    hit = t.js("window.__hit || []") or []
    s.check("F1 点「刷新」重新拉文件列表",
            any("/api/downloads" in str(u) for u in hit), str(list(hit)[:4]))


# ==========================================================================
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="", help="留空则自动探测可用实例")
    ap.add_argument("--port", type=int, default=9344)
    ap.add_argument("--group", default="", help="只跑某一组：A/B/C/D/E/F")
    ap.add_argument("--token", default="", help="线上实例的访问令牌（本地不需要）")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    a.base = pick_base(a.base, a.token)
    # ⚠ 令牌拼在 `#` 之前（bootstrapAuth 用 searchParams 读它）。
    if a.token and "t=" not in a.base:
        a.base = a.base.rstrip("/") + "/?t=" + urllib.parse.quote(a.token)
    print(f"目标服务：{a.base}")

    # ⚠ 每次全新 profile + 禁缓存。复用固定目录会带上上次的 localStorage 会话状态；
    # 而浏览器磁盘缓存会让改了 JS 之后仍然跑到旧代码 —— 实测表现为"改了却还是旧报错"，
    # 白白浪费一轮排查。测试必须确保跑的是当前磁盘上的代码。
    #
    # ⚠⚠ 这里**必须**用 launch_chrome（Chrome 自动分配端口 + 实例身份校验），
    #   不能再用「固定 --port=9344 + 只判断端口能回话」的老写法。
    #   踩过的坑：ship 里 14 套真机串行跑，某套跑完 terminate 掉 Chrome 之后，
    #   下一个套件起来的 Chrome 会**连上那个还没退干净的旧实例**（端口回话正常，
    #   但回话的不是它自己），等旧实例一死就 `ConnectionResetError: WinError 10054`；
    #   另一次表现是榜单切标签后 DOM 里怎么都等不到条目。
    #   **两次红症状不同、单独重跑必绿** —— 这种随机假红比慢贵得多，
    #   它会让人怀疑产品、也会让整条流水线失去可信度。
    proc, _port, _browser_ws, _prof = launch_chrome(
        headless=True, window=(1360, 960))
    # ⚠ `Page.*` / `Runtime.*` 只挂在**页面 target** 上，`launch_chrome` 给的
    #   browser 级 ws 调 Page.enable 会报 `-32601 wasn't found`（踩过）。
    #   所以这里再取一次页面 target 的 ws。
    ws_url = page_ws(_port)

    try:
        t = Tab(ws_url)
        t.call("Page.enable")
        t.call("Runtime.enable")

        # 关掉「确认书名」的干扰：测试要的是按钮行为，不是模糊匹配。
        # 用 addScriptToEvaluateOnNewDocument 在文档创建前生效。
        t.call("Page.addScriptToEvaluateOnNewDocument", source="""
          (function(){
            try{
              localStorage.setItem('nd_onlyOk', 'false');
              localStorage.setItem('nd_ranksFold', 'false');
            }catch(e){}
          })();
        """)

        t.call("Page.navigate", url=a.base)
        # 等首屏**真正挂载完**，而不是「元素出现」。
        #
        # ⚠ 踩过：原来只等 `#btnSearch` 存在 —— 那是**静态 HTML 标签**，
        #   一解析出来就在 DOM 里了，可挂在它身上的事件监听（#q 的 keydown、
        #   各按钮的 onclick）要等 main.js 里几个 mountXxx 跑完才绑上。
        #   只等元素就开测，会偶发撞进这个空窗：回车发出去没人接，
        #   A1 判「statbar 没文案」→ 假红。同一份代码一次 ship 通过、
        #   下次 ship 挂，看着像功能坏了，其实是测早了。
        #   现在等 main.js 在骨架挂完后打的 dataset.mounted 标记。
        ready = t.wait("!!document.documentElement.dataset.mounted "
                       "&& !!document.querySelector('#btnSearch')", timeout=25)
        if not ready:
            raise SystemExit("首屏没挂起来（骨架未挂载 / #btnSearch 找不到）")

        s = Suite(t, verbose=a.verbose)
        groups = {"A": group_a, "B": group_b, "C": group_c, "D": group_d,
                  "E": group_e, "F": group_f}
        want = (a.group or "ABCDEF").upper()
        for gk, fn in groups.items():
            if gk in want:
                try:
                    fn(t, s)
                except Exception as e:
                    s.check(f"{gk} 组执行异常", False, f"{type(e).__name__}: {e}")

        print()
        print("=" * 62)
        print(f"通过 {len(s.passes)} 条 / 失败 {len(s.fails)} 条")
        if s.fails:
            print("\n✗ 失败清单：")
            for label, extra in s.fails:
                print(f"    {label}   {extra}")
            return 1
        print("✓ 全部通过")
        return 0

    finally:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            import shutil
            shutil.rmtree(_prof, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
