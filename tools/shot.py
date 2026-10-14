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
import atexit
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

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


# ---------------------------------------------------------------------------
# Chrome 启动器（公共）—— 消灭「连到别人的 Chrome」这一类随机假红
# ---------------------------------------------------------------------------
# 为什么需要它（不是照抄 free_port 就行）：
#
#   · `free_port()` 的写法是「bind(0) → 拿端口 → close()」。**端口在 close
#     之后到 Chrome 真正 bind 之前是没人占的**，这中间的窗口里可能被别的
#     进程抢走；更常见的是**上一个测试残留的 Chrome 还在监听那个端口**。
#   · 而 `wait_devtools()` 只判断「这个端口能回话」，**不判断回话的是不是
#     我刚起的这个浏览器**。于是测试会连上那个**即将死掉的旧实例**，
#     等它一退，CDP 的 WebSocket 立刻 `ConnectionResetError`
#     （Windows 上就是 WinError 10054）。
#
#   实测表现：**单独跑必绿，在 ship 里 14 套串行跑时随机红，而且每次红
#   的位置和症状都不一样**（这次是「DOM 里没有榜单条目」，下次是
#   「远程主机强迫关闭了一个现有的连接」）—— 因为抢端口的时序每次不同。
#   随机假红比慢贵得多：它让人怀疑产品，也让流水线失去可信度。
#
# 解法用 Chrome 官方的「自动分配端口」：
#   `--remote-debugging-port=0` → Chrome 自己挑一个空闲端口，把**端口**
#   和**浏览器 ws 路径（含唯一 UUID）**写进 `--user-data-dir/DevToolsActivePort`。
#   · 端口由内核分配，不存在「先占后放」的窗口；
#   · 那个 UUID 是**这个实例独有的**，拿它做身份校验就能 100% 确认
#     「连上的就是我刚起的这个」，彻底断掉连错实例的可能。
#
# ⚠ 兼容性：`free_port()` / `wait_devtools()` **原样保留**（10 个旧工具在用），
#   这里只做新增。新代码请用 `launch_chrome()`。


def launch_chrome(
    *,
    headless: bool = True,
    window: tuple[int, int] = (1360, 960),
    profile_dir: str | None = None,
    extra_args: list[str] | None = None,
    ready_timeout: float = 30.0,
) -> tuple[subprocess.Popen, int, str, str]:
    """起一个**确定属于自己**的 Chrome，返回 `(proc, port, browser_ws, profile)`。

    `port` 由 Chrome 自己分配（不会有抢端口竞态）；`browser_ws` 带本实例
    唯一 UUID，调用方可以拿它核对「DevTools 回话的是不是这个实例」。

    调用方负责在结束时 `proc.terminate()` + 删 `profile` 目录
    （用 `try/finally`，别省）。

    ⚠ profile 目录**必须每次全新**：复用会带上上次的 localStorage
      会话，且浏览器磁盘缓存会让「改了 JS 却还跑旧代码」。
    """
    chrome = find_chrome()
    if not profile_dir:
        # ⚠ 必须**真的唯一**：曾经用 `time.time()*1000 % 100000` 拼名字，
        #   紧挨着起两个就撞了（毫秒取模空间太小）—— 撞了之后 Chrome 认出
        #   「这个 profile 已经有实例在跑」，于是**新进程直接 exit=0**，
        #   调用方拿到一个已经死掉的 proc。用 uuid4 一劳永逸。
        profile_dir = os.path.join(
            tempfile.gettempdir(), f"nd-chrome-{os.getpid()}-{uuid.uuid4().hex[:8]}")
    os.makedirs(profile_dir, exist_ok=True)

    args = [chrome]
    if headless:
        args.append("--headless=new")
    args += [
        "--disable-gpu", "--hide-scrollbars",
        # ← 关键：让 Chrome 自己挑端口，端口号之后从 DevToolsActivePort 读
        "--remote-debugging-port=0",
        "--remote-allow-origins=*",
        "--no-first-run", "--no-default-browser-check",
        f"--user-data-dir={profile_dir}",
        f"--window-size={window[0]},{window[1]}",
        "--no-proxy-server",
        "--disable-application-cache", "--disk-cache-size=1",
    ]
    args += extra_args or []
    args.append("about:blank")

    # ⚠⚠ 启动前**先删掉** DevToolsActivePort（反证测出来的真缺口）。
    #
    #   原本只校验「端口回话的 UUID == 文件里的 UUID」。但反证发现：
    #   如果 profile 目录里**已经有一份**指向另一个活实例的文件，
    #   而新 Chrome 又因单例机制直接 exit=0，那么这份**旧文件**会被读到 ——
    #   端口和 UUID 都恰好对得上那个旧实例，校验**放行**，测试连到别人家。
    #
    #   删掉它之后，「文件存在」本身就等于「**本次**实例写出来了」，
    #   校验才真正成立。
    port_file = os.path.join(profile_dir, "DevToolsActivePort")
    try:
        os.remove(port_file)
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001
        pass

    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)

    # 读 DevToolsActivePort：第一行端口、第二行 ws 路径。
    # 文件是 Chrome **起完才写**的，所以要轮询（不能一次读不到就当失败）。
    #
    # ⚠⚠ 「启动器退出」**不等于**「浏览器没起来」（2026-10-14 Chrome 155 实测）：
    #   新版 Windows 上 `chrome.exe` 会把自己**移交(detach)**给真正的浏览器进程，
    #   启动器随即 `exit=0`，而浏览器还在跑、DevTools 端口也正常回话。
    #   旧代码一看到 `proc.poll() is not None` 就判「Chrome 起来就退了」——
    #   于是**全部真机套件一起红**，看着像产品崩了，其实是判据错了。
    #   现在唯一的成功判据是「DevToolsActivePort 出现且内容完整」：
    #   启动前我们已经把它删掉，所以它出现 = 就是**本次**实例写的。
    #   启动器退出只作为「再等一小会儿就该有文件了」的提示，不直接判死。
    GRACE = 6.0
    deadline = time.time() + ready_timeout
    port = 0
    ws_path = ""
    exited_at = 0.0
    while time.time() < deadline:
        try:
            with open(port_file, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            if len(lines) >= 2:
                port = int(lines[0])
                ws_path = lines[1]
                break
        except Exception:
            pass
        if proc.poll() is not None:
            exited_at = exited_at or time.time()
            if time.time() - exited_at > GRACE:
                raise SystemExit(
                    f"Chrome 启动器已退出（exit={proc.returncode}），且 {GRACE:.0f} 秒内"
                    "没写出 DevToolsActivePort —— 多半是参数被拒 / 被安全软件拦了"
                )
        time.sleep(0.15)
    if not port:
        raise SystemExit(
            "Chrome 没写出 DevToolsActivePort（没起来；启动器"
            f"{'已退出' if exited_at else '仍在跑'}）"
        )

    browser_ws = f"ws://127.0.0.1:{port}{ws_path}"

    # 身份校验：确认这个端口回话的 ws 路径**就是**我们刚读到的那个。
    # 端口是内核分的、UUID 是实例唯一的，两者对上 = 一定是自己这个。
    # （这就是 free_port+wait_devtools 组合缺的那一环。）
    probe_deadline = time.time() + ready_timeout
    while time.time() < probe_deadline:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
                got = json.load(r).get("webSocketDebuggerUrl", "")
            if got.rstrip("/") == browser_ws.rstrip("/"):
                # 登记进来：启动器 detach 之后 `proc.terminate()` 关不掉它，
                # 得靠 DevTools/精确杀进程来收尾（见 close_chrome）。
                _LIVE.append((port, browser_ws, proc, profile_dir))
                return proc, port, browser_ws, profile_dir
        except Exception:
            pass
        time.sleep(0.15)
    proc.terminate()
    raise SystemExit("DevTools 回话的实例不是自己起的（端口被人抢了）")


#: 本进程起过的实例。`atexit` 兜底关掉 —— 不然跑几轮真机就攒一堆僵尸 Chrome。
_LIVE: list[tuple[int, str, object, str]] = []


def _kill_by_profile(profile: str) -> None:
    """按命令行里的 `--user-data-dir` **精确**杀掉属于我们的残留 Chrome。

    只在 Windows 上做，而且只认我们那个唯一 profile 目录 —— 绝不能误杀
    用户自己开着的浏览器。
    """
    if os.name != "nt" or not profile:
        return
    key = profile.replace("/", "\\").lower()
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='chrome.exe'",
             "get", "ProcessId,CommandLine"],
            capture_output=True, text=True, timeout=15,
        ).stdout or ""
    except Exception:  # noqa: BLE001  wmic 在 Win11 上可能已被移除
        return
    for line in out.splitlines():
        if key not in line.replace("/", "\\").lower():
            continue
        m = re.search(r"(\d+)\s*$", line.strip())
        if m:
            try:
                subprocess.run(["taskkill", "/F", "/PID", m.group(1)],
                               capture_output=True, timeout=10)
            except Exception:  # noqa: BLE001
                pass


def close_chrome(port: int = 0, browser_ws: str = "", proc=None,
                 profile: str = "") -> None:
    """把 `launch_chrome()` 起的实例**真的关掉**。

    为什么不能只 `proc.terminate()`（2026-10-14 实测 Chrome 155）：
      新版 Windows 上启动器会 **detach**，`proc` 早就 exit=0 了 —— 
      `terminate()` 是空操作，浏览器进程会一直留着。跑一轮真机（十几套）
      就攒出十几个僵尸 Chrome，最后把机器拖死、还会干扰下一轮的启动。

    所以先礼后兵：
      1) 走 DevTools 的 `Browser.close`（优雅、精准，不用猜 PID）；
      2) 兜底按 `--user-data-dir=<我们那个唯一目录>` 精确杀残留；
      3) 删掉 profile 目录。
    """
    if browser_ws:
        try:
            ws = websocket.create_connection(browser_ws, timeout=5)
            ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
            try:
                ws.recv()
            except Exception:  # noqa: BLE001  关掉时连接会断，属正常
                pass
            ws.close()
        except Exception:  # noqa: BLE001
            pass
    if proc is not None:
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:  # noqa: BLE001
            pass
    if profile:
        _kill_by_profile(profile)
        shutil.rmtree(profile, ignore_errors=True)


def close_all_chrome() -> None:
    """关掉本进程起过的所有实例（`atexit` 注册）。"""
    for port, ws, proc, prof in list(_LIVE):
        close_chrome(port, ws, proc, prof)
    _LIVE.clear()


atexit.register(close_all_chrome)


def page_ws(port: int, *, prefer: str = "about:", timeout: float = 20.0) -> str:
    """从 DevTools 端口拿**页面 target** 的 WebSocket 地址。

    ⚠ 为什么需要它（踩过）：`Page.*` / `Runtime.*` 这些域**只挂在页面 target 上**，
      在 browser 级 WebSocket 上调用会报
      `-32601 'Page.enable' wasn't found`。
      `launch_chrome` 返回的 `browser_ws` 是 browser 级的（适合 Browser.getVersion
      这类域）—— 要用 Page/Runtime 就必须走这个函数拿页面 target。

    `prefer`：优先挑 url 以它开头的 target（默认我们启动时开的 `about:blank`）。
      **不能直接拿第一个** —— 扩展的 background page 也会被列进 /json/list。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/json/list", timeout=1) as r:
                tabs = json.load(r)
            pages = [tb for tb in tabs if tb.get("type") == "page"]
            for tb in pages:
                if tb.get("url", "").startswith(prefer):
                    return tb["webSocketDebuggerUrl"]
            if pages:
                return pages[0]["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.15)
    raise SystemExit(f"拿不到页面 target 的 ws（端口 {port}）")


def snapshot_png(ws_url: str, out_path: str, *, full: bool = False,
                 timeout: float = 30.0) -> bool:
    """用 CDP 抓一张整页/可视区截图。返回是否成功。

    给「新代码」用；旧工具的自己那份截图逻辑保持不动。
    """
    import base64
    try:
        t = Tab(ws_url)
    except Exception:
        return False
    try:
        t.call("Page.enable")
        params = {"format": "png"}
        if full:
            params["captureBeyondViewport"] = True
            m = t.call("Page.getLayoutMetrics")
            cs = m.get("cssContentSize") or m.get("contentSize") or {}
            if cs.get("width"):
                params["clip"] = {
                    "x": 0, "y": 0,
                    "width": cs["width"], "height": cs["height"],
                    "scale": 1,
                }
        res = t.call("Page.captureScreenshot", **params)
        data = res.get("data") or ""
        if not data:
            return False
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(data))
        return True
    except Exception:
        return False
    finally:
        try:
            t.ws.close()
        except Exception:
            pass


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
