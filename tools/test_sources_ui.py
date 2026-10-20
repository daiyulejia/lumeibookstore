"""来源库「站点」列表的行为回归（需要服务在跑 + Chrome）。

为什么要有这一条
----------------
用户看到来源库后的原话是三个字：「网址多」。
线上实测确实是这个体感 —— 114 个网址一屏接一屏，但真能站内搜的只有 15 个、
能读目录的二十几个，剩下大半是历史上碰过、后来打不开的。
平铺成一长串 = 一堵网址墙，用户既看不出哪些有用，也不知道数量为什么这么大。

所以列表改成：**按能力分档排序**（能搜 → 能读目录 → 只是可用 → 已失效），
已失效那档默认只露 6 条，其余折起来。

这条测试盯三件**改错了用户立刻能感觉到、但不报错**的事：
  1. 排序真的按能力走（能搜的必须在最上面）—— 写反了没人会报错
  2. 失效区**真的折了**（默认露 6 条，不是 114 条）
  3. 折叠**不许变成"藏"**：数量必须写出来、按钮必须能展开、能收回去

第 3 条是最容易偷懒的地方：只要 `slice(0, 6)` 一句就"看不见"了，
数字不写、按钮不给，用户根本不知道还有 108 条 —— 那就成了骗人。

为什么必须用真浏览器
--------------------
排序和折叠都是**渲染结果**。静态检查只能看到"代码里写了 sort"，
看不到"排序键拿错了字段导致实际顺序没变"，也看不到
"按钮绑在了被 innerHTML 替换掉的旧节点上"（点了没反应）。

用法：
  python tools/test_sources_ui.py --base http://127.0.0.1:8303
  python tools/test_sources_ui.py --base http://106.53.203.108:8000 --token <t>

⚠ 全程用**假接口**（拦截 /api/registry 返回构造数据），不看真实库：
  真实库的内容每天都在变，拿它断言"第一条必须是 XX 站"必然假红。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import websocket  # noqa: E402
from shot import launch_chrome, page_ws  # noqa: E402


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

    def wait(self, expr, timeout: float = 20.0):
        """等某个表达式变真 —— 首屏 Vue 要一两秒，写死 sleep 在 ship 里会假红。"""
        end = time.time() + timeout
        while time.time() < end:
            if self.js(expr):
                return True
            time.sleep(0.15)
        return False


# 构造一份"和线上一样丑"的库：1 能搜 + 2 能读目录 + 1 只是可用 + 8 已失效
# 失效 8 条 > 默认露 6 条，才能验"折了但没藏"。
FAKE = {
    "stats": {"sites": 12, "sites_ok": 4, "sites_searchable": 1,
              "books": 0, "books_ok": 0, "top_sites": []},
    "sites": [
        {"host": "c-plain.com", "healthy": True, "ok": 1, "fail": 0},
        {"host": "d0-dead.com", "healthy": False, "ok": 0, "fail": 9},
        {"host": "a-search.com", "healthy": True, "searchable": True,
         "has_search_tpl": True, "ok": 7, "fail": 0},
        {"host": "d1-dead.com", "healthy": False, "ok": 0, "fail": 9},
        {"host": "b-toc.com", "healthy": True, "toc_tpl": "/mulu/", "ok": 3, "fail": 0},
        {"host": "d2-dead.com", "healthy": False, "ok": 0, "fail": 9},
        {"host": "d3-dead.com", "healthy": False, "ok": 0, "fail": 9},
        {"host": "d4-dead.com", "healthy": False, "ok": 0, "fail": 9},
        {"host": "d5-dead.com", "healthy": False, "ok": 0, "fail": 9},
        {"host": "d6-dead.com", "healthy": False, "ok": 0, "fail": 9},
        {"host": "d7-dead.com", "healthy": False, "ok": 0, "fail": 9},
        {"host": "b2-toc.com", "healthy": True, "toc_tpl": "/index/", "ok": 2, "fail": 0},
    ],
    "books": [],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="服务地址，如 http://127.0.0.1:8303")
    ap.add_argument("--token", default="", help="线上实例的访问令牌（本地不需要）")
    a = ap.parse_args()

    if a.token and "t=" not in a.base:
        a.base = a.base.rstrip("/") + "/?t=" + urllib.parse.quote(a.token)

    ok_n = fail_n = 0

    def check(label: str, cond: bool, extra: str = "") -> None:
        nonlocal ok_n, fail_n
        if cond:
            ok_n += 1
            print(f"  ✓ {label}")
        else:
            fail_n += 1
            print(f"  ✗ {label}")
            if extra:
                print(f"      {extra}")

    proc, port, _bws, prof = launch_chrome(headless=True, window=(1280, 900))
    try:
        ws = page_ws(port)
        t = Tab(ws)
        t.call("Page.enable")
        t.call("Runtime.enable")
        t.call("Network.enable")

        # ⚠ 假接口必须传**字符串** —— `new Response(<对象>)` 会被转成
        #   "[object Object]"，前端 json() 直接抛错（本项目的经典坑）。
        #   json.dumps 两次：第一次得到 JSON 文本，第二次得到带引号的 JS 字面量。
        body_literal = json.dumps(json.dumps(FAKE, ensure_ascii=False))
        t.call("Page.addScriptToEvaluateOnNewDocument", source=f"""
          (function(){{
            window.__regHit = 0;
            var of = window.fetch;
            window.fetch = function(u, o){{
              var s = String(u);
              if (s.indexOf('/api/registry') === 0 && s.indexOf('/api/registry/') !== 0) {{
                window.__regHit++;
                return Promise.resolve(new Response({body_literal},
                  {{status:200, headers:{{'Content-Type':'application/json'}}}}));
              }}
              return of.apply(this, arguments);
            }};
          }})();
        """)

        print(f"目标服务：{a.base}")
        t.call("Page.navigate", url=a.base.split("#")[0] + "#registry")

        if not t.wait("!!document.querySelector('#srcBody')", timeout=30):
            check("来源库面板挂载出来", False, "等不到 #srcBody —— 页面没起来或深链失效")
            raise SystemExit(1)
        if not t.wait("window.__regHit > 0", timeout=20):
            check("假接口被调用", False,
                  "__regHit=0 —— 拦截没装上（或路径前缀判断写错了）")
            raise SystemExit(1)
        if not t.wait("document.querySelectorAll('#srcBody .hcard').length > 0", timeout=20):
            check("站点行渲染出来", False, "#srcBody 里没有 .hcard")

        hosts = t.js(
            "Array.from(document.querySelectorAll('#srcBody .hcard .hn'))"
            ".map(e => e.textContent.trim())") or []
        print(f"  渲染顺序（前 6 条）：{hosts[:6]}")

        check("能搜的站排第一（能力分档生效）",
              bool(hosts) and hosts[0] == "a-search.com",
              f"第一条是 {hosts[0] if hosts else '(空)'} —— "
              f"排序键可能拿错字段，名单根本没变")
        # 两个"能读目录"的档位：按成功次数降序，b-toc(3) 在 b2-toc(2) 前
        check("能读目录的紧跟在能搜之后，并按成功次数排",
              len(hosts) >= 3 and hosts[1] == "b-toc.com" and hosts[2] == "b2-toc.com",
              f"前三条是 {hosts[:3]}")
        check("只是可用的排在能读目录之后",
              len(hosts) >= 4 and hosts[3] == "c-plain.com", f"第四条是 {hosts[3] if len(hosts) > 3 else '(无)'}")

        shown = len(hosts)
        # 夹具是 4 条活的（1 能搜 + 2 能读目录 + 1 只是可用）+ 8 条失效；
        # 失效默认露 6 → 首屏应有 4+6=10 条。
        check("已失效默认折叠（12 条里只露 4 活 + 6 失效 = 10 条）",
              shown == 10, f"实际露出 {shown} 条 —— 折没折？还是把活的也折了？")

        txt = t.js("(document.querySelector('#srcBody') || {}).textContent || ''") or ""
        check("折叠处写明了总数（不许悄悄藏）",
              "已失效 8 个" in txt, "页面上看不到「已失效 8 个」这句话")

        btn = t.js("!!document.getElementById('regDeadToggle')")
        check("给了「全部展开」的按钮", bool(btn), "没有 #regDeadToggle —— 用户没法看全")

        t.js("(document.getElementById('regDeadToggle')||{}).click?.()")
        expanded = t.wait(
            "document.querySelectorAll('#srcBody .hcard').length === 12", timeout=10)
        n_exp = t.js("document.querySelectorAll('#srcBody .hcard').length")
        check("点一下能把 12 条全都展开", bool(expanded), f"展开后只有 {n_exp} 条")

        t.js("(document.getElementById('regDeadToggle')||{}).click?.()")
        collapsed = t.wait(
            "document.querySelectorAll('#srcBody .hcard').length === 10", timeout=10)
        n_col = t.js("document.querySelectorAll('#srcBody .hcard').length")
        check("再点一下能收回去", bool(collapsed), f"收回后是 {n_col} 条")

        # 反向：活着的站一条都不许被折掉（折叠只能折失效区）
        alive = t.js(
            "Array.from(document.querySelectorAll('#srcBody .hcard .hn'))"
            ".map(e => e.textContent.trim())"
            ".filter(h => h.indexOf('dead') === -1).length")
        check("活着的一条都没被折（折叠只针对失效区）", alive == 4, f"只剩 {alive} 条活的")

        print()
        if fail_n:
            print(f"✗ 有 {fail_n} 项没过")
            return 1
        print(f"✓ 全部通过（{ok_n} 项）")
        return 0
    finally:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        # 临时 profile 用完就删 —— 不然 temp 目录会攒一堆
        try:
            import shutil
            shutil.rmtree(prof, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main())
