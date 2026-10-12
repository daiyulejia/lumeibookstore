"""真·页面截图工具（CDP 驱动）。

为什么不用 `chrome --headless --screenshot`：
它只有 `--virtual-time-budget`，虚拟时钟在页面"空闲"时会瞬间跑完，
而流式搜索是异步 fetch，结果还没回来时钟就走完了 —— 截出来永远是 loading。

这个脚本直连 DevTools 协议，可以：
  - 等某个 CSS 选择器出现（`wait_selector`）
  - 等某个 JS 表达式为真（`wait_js`）
  - 等网络静默
然后才截图。需要 websocket-client。

用法：
  python tools/shot.py <url> <out.png> [--w 1080] [--h 810] [--wait ".book"] [--ms 60000]
  python tools/shot.py <url> <out.png> --w 393 --h 852 --mobile

关于 --mobile：
  不加这个开关时视口是"桌面"语义，(hover:none) / (pointer:coarse) 恒为
  false —— 也就是说**触摸相关的 CSS 在桌面视口下根本不会生效**，
  拿它测手机样式等于没测。加了之后会同时：
    · setDeviceMetricsOverride(mobile=True, deviceScaleFactor=3)
    · setTouchEmulationEnabled(maxTouchPoints=5)
  媒体查询才真正命中，截出来的才是手机上会看到的样子。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import websocket  # type: ignore

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_chrome() -> str:
    for p in CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    for name in ("chrome", "msedge", "chromium"):
        hit = shutil.which(name)
        if hit:
            return hit
    raise SystemExit("找不到 Chrome / Edge，装一个再来。")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_devtools(port: int, timeout: float = 20.0) -> str:
    """等 DevTools 起来，返回 browser 的 ws 地址。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
                return json.load(r)["webSocketDebuggerUrl"]
        except Exception:
            time.sleep(0.15)
    raise SystemExit("DevTools 端口没起来")


class Tab:
    """一个极简 CDP 客户端：只实现我们要用的几个命令。"""

    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(
            ws_url, timeout=60, suppress_origin=True
        )
        self._id = 0

    def call(self, method: str, **params):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expr: str):
        r = self.call(
            "Runtime.evaluate",
            expression=expr,
            returnByValue=True,
            awaitPromise=True,
        )
        res = r.get("result", {})
        if r.get("exceptionDetails"):
            return None
        return res.get("value")

    def wait_js(self, expr: str, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.js(expr) is True:
                    return True
            except Exception:
                pass
            time.sleep(0.25)
        return False

    def shot(self, path: str, full: bool = False):
        params = {"format": "png"}
        if full:
            params["captureBeyondViewport"] = True
        r = self.call("Page.captureScreenshot", **params)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["data"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("out")
    ap.add_argument("--w", type=int, default=1080)
    ap.add_argument("--h", type=int, default=810)
    ap.add_argument("--wait", default="", help="等到该 CSS 选择器出现")
    ap.add_argument("--wait-js", default="", help="等到该 JS 表达式为 true")
    ap.add_argument("--ms", type=int, default=60000, help="等待上限（毫秒）")
    ap.add_argument("--settle", type=int, default=900, help="就绪后再等这么久（毫秒）")
    ap.add_argument("--full", action="store_true", help="整页截图")
    ap.add_argument("--mobile", action="store_true",
                    help="按移动设备模拟：让 (hover:none) / (pointer:coarse) "
                         "真正命中，并把视口按 devicePixelRatio 缩放。"
                         "不传就还是桌面行为 —— 注意桌面下触摸相关的 "
                         "媒体查询不成立，测不到触摸样式。")
    ap.add_argument("--dpr", type=float, default=0, help="设备像素比（0=自动：mobile 时 3，否则 1）")
    ap.add_argument("--pre", default="",
                    help="页面脚本**执行前**先跑一段 JS（用来预置 localStorage，"
                         "比如强制指定阅读器翻页模式）")
    ap.add_argument("--js", default="",
                    help="页面加载**之后**、截图之前跑一段 JS。"
                         "用来把界面点到要截的那个状态 —— 比如点开某个抽屉"
                         "（`document.querySelector('#btnNet').click()`）。"
                         "注意和 --pre 的区别：--pre 在页面脚本之前，改不到 DOM。")
    args = ap.parse_args()

    chrome = find_chrome()
    port = free_port()
    profile = tempfile.mkdtemp(prefix="shotprof-")
    proc = subprocess.Popen(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={profile}",
            f"--window-size={args.w},{args.h}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        browser_ws = wait_devtools(port)
        # 新建一个 tab
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT"
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            tab_ws = json.load(r)["webSocketDebuggerUrl"]
        _ = browser_ws

        t = Tab(tab_ws)
        t.call("Page.enable")
        t.call("Runtime.enable")
        # mobile=True 会让 Chrome 用触摸设备的行为算媒体查询，
        # 于是 (hover:none) / (pointer:coarse) 才会命中 —— 桌面视口下
        # 那两个查询恒为 false，触摸样式等于没写，测了个寂寞。
        dpr = args.dpr or (3 if args.mobile else 1)
        t.call(
            "Emulation.setDeviceMetricsOverride",
            width=args.w,
            height=args.h,
            deviceScaleFactor=dpr,
            mobile=bool(args.mobile),
        )
        if args.mobile:
            t.call("Emulation.setTouchEmulationEnabled", enabled=True,
                   maxTouchPoints=5)
        if args.pre:
            t.call("Page.addScriptToEvaluateOnNewDocument", source=args.pre)
        t.call("Page.navigate", url=args.url)

        ok = True
        if args.wait:
            sel = json.dumps(args.wait)
            ok = t.wait_js(f"!!document.querySelector({sel})", args.ms / 1000)
        if args.wait_js:
            ok = t.wait_js(args.wait_js, args.ms / 1000) and ok
        if not ok:
            print("  ! 等待超时，仍然截图")
        # --js 放在等待之后、settle 之前：先让界面自己加载好，
        # 再模拟用户的那一下点击，然后留出动画时间。
        if args.js:
            try:
                t.js(args.js)
            except Exception as e:  # noqa: BLE001
                print(f"  ! --js 执行出错：{e}")
        time.sleep(args.settle / 1000 + (0.8 if args.js else 0))

        t.shot(args.out, full=args.full)
        size = os.path.getsize(args.out)
        print(f"  {'ok' if ok else 'timeout'} {args.out} ({size} bytes)")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
