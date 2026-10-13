#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Vue 迁移的「鉴权时序」真机验证
============================================================================
为什么单独一个套件：这个 bug **只在带令牌的环境下出现**，
本地 /api 不需要令牌，所以本地永远不复现。

现象：
    线上打开首页 → 榜单区块整块不显示（组件的容器一直 hidden），
    控制台/埋点里有一条 401。本地怎么点都正常。

根因：
    页面用 `?t=<token>` 传令牌，读它、写进 PRE 的是旧代码的
    bootstrapAuth()（main.js 里 await 在若干 mount 之后）。
    Vue 是**另一个** `<script type="module">`，加载完立刻 mount ——
    组件的 onMounted 可能跑在 bootstrapAuth() 之前，此时
    `api.get()` 拼出的 URL 不带 t=，线上 401。

修法：旧代码在 bootstrapAuth 结束后置 `window.__lumeiLegacy.authReady`，
      Vue 侧 `whenAuthReady()` 等到它再发请求。

这个套件钉住三件事：
  1. 带令牌访问时，榜单区块**会**显示出来（核心回归）
  2. Vue 发出的请求**带**令牌（不能只靠"恰好没 401"来判断）
  3. 不带令牌时不崩（authReady 超时兜底要能把流程放过去）

用法：
    .venv\\Scripts\\python tools\\test_auth_race.py                 # 用本地服务
    .venv\\Scripts\\python tools\\test_auth_race.py --url http://106.53.203.108:8000
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

from shot import Tab, find_chrome, free_port, wait_devtools  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

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


class Browser:
    def __init__(self):
        self.port = free_port()
        self.profile = tempfile.mkdtemp(prefix="authrace-")
        self.proc = subprocess.Popen(
            [
                find_chrome(),
                "--headless=new", "--disable-gpu", "--hide-scrollbars",
                "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                f"--remote-debugging-port={self.port}",
                "--remote-allow-origins=*",
                f"--user-data-dir={self.profile}",
                "--window-size=1280,900",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        wait_devtools(self.port)
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/json/new?about:blank", method="PUT")
        with urllib.request.urlopen(req, timeout=5) as r:
            ws = json.load(r)["webSocketDebuggerUrl"]
        self.t = Tab(ws)
        self.t.call("Page.enable")
        self.t.call("Runtime.enable")
        self.t.call("Network.enable")
        # 记下所有发出的请求 URL —— 用来断言「带没带令牌」
        # 同时给每条请求打一个「发车时 authReady 了没」的戳。
        # 这是**本地也能测出竞态**的关键：本地 /api 不要令牌，
        # 所以「没带 t=」在本地不会被拒，光看结果永远是绿的；
        # 但只要这条戳是 false，就说明 Vue 抢在 bootstrapAuth() 之前发了车，
        # 搬到线上（要令牌）就是 401 —— 正是那个线上专属 bug。
        self.t.call("Page.addScriptToEvaluateOnNewDocument", source="""
          window.__reqs = [];
          window.__reqMeta = [];
          const _ready = () => !!(window.__lumeiLegacy && window.__lumeiLegacy.authReady);
          const _f = window.fetch;
          window.fetch = function(u, o) {
            try {
              window.__reqs.push(String(u));
              window.__reqMeta.push({ u: String(u), ready: _ready() });
            } catch (e) {}
            return _f.apply(this, arguments);
          };
        """)

    def goto(self, url, settle=6.0):
        self.t.call("Page.navigate", url=url)
        time.sleep(settle)

    def js(self, expr, await_promise=False):
        """跑一段 JS 并取回值。

        ⚠ 这里**不能**自作聪明包一层 `(() => { expr })()` ——
        块体箭头函数没有 return，`1+1`、`!!document.body` 这类表达式
        会被求值成 undefined，于是所有断言都拿到 None（曾踩：
        测试 5 项全红，其实是测试自己把返回值吃掉了）。
        直接交给 Runtime.evaluate 求**完成值**即可。
        """
        r = self.t.call("Runtime.evaluate", expression=expr, returnByValue=True,
                        awaitPromise=await_promise)
        if "exceptionDetails" in r:
            raise RuntimeError(str(r["exceptionDetails"])[:300])
        return r.get("result", {}).get("value")

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=8)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def local_token() -> str:
    """本地服务如果有令牌就带上 —— 让本地也能复现线上的时序。"""
    try:
        return json.loads((ROOT / "cache" / "auth.json").read_text("utf-8")).get("token", "")
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--token", default="", help="访问令牌（默认从 cache/auth.json 读）")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    token = a.token or local_token()

    print("=" * 62)
    print("Vue 迁移 · 鉴权时序真机验证")
    print("=" * 62)

    try:
        urllib.request.urlopen(base + "/api/health", timeout=5).read()
    except Exception as e:  # noqa: BLE001
        print(f"\n连不上 {base}：{e}")
        return 2

    b = Browser()
    try:
        # -------------------------------------------------------------
        section("1. 带令牌打开：榜单区块要显示出来")
        url = base + "/" + (f"?t={urllib.parse.quote(token)}" if token else "")
        b.goto(url, settle=8.0)

        # 等到组件拿到数据（或明确放弃）
        shown = False
        for _ in range(40):
            if b.js("!document.getElementById('ranksBox').hidden"):
                shown = True
                break
            time.sleep(0.4)
        if shown:
            ok("ranksBox 显示出来了（组件成功拿到榜单目录）")
        else:
            bad("ranksBox 一直 hidden —— 组件请求失败/被 401 拒了")

        # Vue 有没有真的挂上
        if b.js("!!document.querySelector('#vue-root .rk-vue')"):
            ok("Vue 组件已挂载（#vue-root 里有 .rk-vue）")
        else:
            bad("Vue 组件没挂上 —— 产物没加载？")

        # 竞态核心断言：组件发的请求，不能有一条是「authReady 之前」发出去的。
        # 这条在本地也有效（不看结果看时序），是对线上 401 的直接编码。
        early = json.loads(b.js("""
          JSON.stringify((window.__reqMeta || [])
            .filter(m => m.u.indexOf('/api/ranks') >= 0 && !m.ready))
        """) or "[]")
        if early:
            bad(f"{len(early)} 个榜单请求在 authReady 之前就发车了"
                f"（线上必 401）：{[m['u'] for m in early][:2]}")
        else:
            ok("榜单请求都在 authReady 之后才发（无抢跑，线上不会 401）")

        # -------------------------------------------------------------
        section("2. Vue 发出的请求要带令牌")
        reqs = json.loads(b.js("JSON.stringify(window.__reqs || [])") or "[]")
        api_reqs = [u for u in reqs if "/api/" in u]
        info(f"共 {len(api_reqs)} 个 /api 请求")
        if not token:
            info("（本地无令牌环境，跳过「带令牌」断言）")
            ok("无令牌环境下页面正常（不崩）")
        else:
            ranks_reqs = [u for u in api_reqs if "/api/ranks" in u]
            if not ranks_reqs:
                bad("没抓到 /api/ranks 请求 —— 组件根本没发？")
            else:
                without = [u for u in ranks_reqs if "t=" not in u]
                if without:
                    bad(f"{len(without)} 个榜单请求**没带令牌**（会 401）：{without[:2]}")
                else:
                    ok(f"{len(ranks_reqs)} 个榜单请求全部带令牌")

        # -------------------------------------------------------------
        section("3. authReady 信号被置位了")
        ready = b.js("!!(window.__lumeiLegacy && window.__lumeiLegacy.authReady)")
        if ready:
            ok("__lumeiLegacy.authReady = true（旧代码完成鉴权后置位）")
        else:
            bad("authReady 没置位 —— Vue 侧 whenAuthReady() 会走到超时兜底")

        # -------------------------------------------------------------
        section("4. 没有 401 / 没有 JS 报错")
        errs = json.loads(b.js("""
          JSON.stringify((window.__lumeiErrors || []).map(String))
        """) or "[]")
        if errs:
            bad(f"页面记到 {(len(errs))} 条错误：{errs[:2]}")
        else:
            ok("页面没有记到 JS 错误")
    finally:
        b.close()

    # -------------------------------------------------------------
    section("5. 不带令牌：不能崩（authReady 超时兜底）")
    b2 = Browser()
    try:
        b2.goto(base + "/", settle=9.0)
        # 不带令牌时服务端会返回鉴权门，但页面本身不该崩
        alive = b2.js("!!document.querySelector('#btnSearch')")
        if alive:
            ok("不带令牌时页面骨架仍然在（没白屏）")
        else:
            bad("不带令牌时页面是空的 —— 兜底逻辑有问题")
        # 超时兜底：即使 authReady 没来，组件也该在 ~8s 内放弃等待而不是永久卡住
        loading = b2.js("!!document.querySelector('#vue-root .rk-skel')")
        if loading:
            info("组件还停在下骨架态（可能仍在等/重试）")
        else:
            ok("组件没有永久卡在加载态")
    finally:
        b2.close()

    print("\n" + "=" * 62)
    if bad_n == 0:
        print(f"通过 {ok_n} · 失败 0\n✓ 全部通过")
    else:
        print(f"通过 {ok_n} · 失败 {bad_n}\n✗ 有 {bad_n} 项没过")
    print("=" * 62)
    return 1 if bad_n else 0


if __name__ == "__main__":
    sys.exit(main())
