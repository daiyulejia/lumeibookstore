"""`launch_chrome()` 的回归测试（全离线，不真的起浏览器）。

为什么必须有这个套件（2026-10-14 真事故）：
    Chrome 升到 155 之后，Windows 上的 `chrome.exe` **会把自己 detach**——
    启动器进程 `exit=0` 退出，真正的浏览器进程继续跑、DevTools 端口也正常。
    而 `launch_chrome()` 当时把「启动器退出」当成致命错误，直接抛
    「Chrome 起来就退了」→ **18 套真机全部一起红**，看着像产品崩了。

    这类"环境一变就整体红"的判据最贵：它让人怀疑产品，也让流水线失去可信度。
    所以这里用**假进程 + 本地假 DevTools**（真的 HTTP 服务，不是 mock 返回值）
    把三条不变量钉死：
      1. 启动器退出 **不算** 失败 —— 只要 DevToolsActivePort 写出来了就算起来了；
      2. 端口文件**一直不出现**才算失败，且报错要说清是"启动器已退出"；
      3. detach 之后必须能靠 `Browser.close` 关掉实例（否则一轮真机攒一堆僵尸）。

用法：.venv/Scripts/python.exe tools/test_chrome_launcher.py
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tools.shot as S                                          # noqa: E402

_fail: list[str] = []
_passed = 0

WS_PATH = "/devtools/browser/11112222-3333-4444-5555-666677778888"


def check(name: str, ok: bool, detail: str = "") -> bool:
    global _passed
    if ok:
        _passed += 1
        print(f"  ✓ {name}")
    else:
        _fail.append(name)
        print(f"  ✗ {name}" + (f"（{detail}）" if detail else ""))
    return ok


class FakeProc:
    """冒充 `subprocess.Popen`：`poll()` 直接给退出码（= detach 后的启动器）。"""

    def __init__(self, returncode: int | None = 0):
        self.returncode = returncode
        self.pid = 424242
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True


def _devtools_server():
    """一个只回答 `/json/version` 的假 DevTools（真 HTTP 服务，真端口）。"""
    class H(BaseHTTPRequestHandler):
        def do_GET(self):                                       # noqa: N802
            payload = json.dumps({
                "webSocketDebuggerUrl":
                    f"ws://127.0.0.1:{self.server.server_address[1]}{WS_PATH}",
            })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload.encode())

        def log_message(self, *a):                              # 静音
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


class _Harness:
    """把 `find_chrome` / `subprocess.Popen` 换掉，`launch_chrome` 就进沙盒了。

    `write_port`：假启动器要不要像真 Chrome 那样写出 DevToolsActivePort。
    """

    def __init__(self, *, write_port: bool, port: int = 0,
                 never_exit: bool = False):
        self.write_port = write_port
        self.port = port
        self.proc = FakeProc(None if never_exit else 0)
        self.launched: list[list[str]] = []

    def __enter__(self):
        self._old = (S.find_chrome, S.subprocess.Popen)

        def fake_launch(args, **kw):
            self.launched.append(list(args))
            if self.write_port:
                prof = next(a.split("=", 1)[1] for a in args
                            if a.startswith("--user-data-dir="))
                Path(prof).mkdir(parents=True, exist_ok=True)
                # 真 Chrome 是"起完才写"，这里也照这个时序写。
                Path(prof, "DevToolsActivePort").write_text(
                    f"{self.port}\n{WS_PATH}\n", encoding="utf-8")
            return self.proc

        S.find_chrome = lambda: "C:/fake/chrome.exe"
        S.subprocess.Popen = fake_launch
        return self

    def __exit__(self, *exc):
        (S.find_chrome, S.subprocess.Popen) = self._old
        return False


def _try_launch(**kw):
    try:
        r = S.launch_chrome(**kw)
        return True, "", r
    except SystemExit as e:
        return False, str(e), None


def main() -> int:
    print("== A. 启动器 detach（exit=0）+ 端口文件写好 → 必须**判成功** ==")
    srv, port = _devtools_server()
    try:
        with _Harness(write_port=True, port=port) as h:
            ok, err, r = _try_launch(ready_timeout=5.0)
            check("启动器已退出也能成功（旧代码在这里误报『起来就退了』）", ok, err)
            if ok:
                proc, got_port, browser_ws, profile = r
                check("返回的端口就是 DevToolsActivePort 里那个",
                      got_port == port, str(got_port))
                check("**并且**启动器进程确实已退出 —— 证明「成功」不依赖"
                      "「启动器还活着」这个错误判据", proc.poll() is not None)
                check("实例被登记进 `_LIVE`（detach 后只能靠它收尾）",
                      any(p == port for p, *_ in S._LIVE), str(S._LIVE))
    finally:
        srv.shutdown()

    print("\n== B.（反证）端口文件一直不出现 → 必须**判失败**，且说清原因 ==")
    S._LIVE.clear()
    with _Harness(write_port=False):
        ok, err, _ = _try_launch(ready_timeout=1.0)
    check("没写出 DevToolsActivePort 就是失败", not ok, err)
    check("报错要提到 DevToolsActivePort（不是含糊的『起来就退了』）",
          "DevToolsActivePort" in err, err)
    check("报错要说明启动器已退出（这才是可诊断的信息）",
          "启动器已退出" in err, err)

    print("\n== C. 正常情况（启动器健在 + 端口文件写好）不许回归 ==")
    srv2, port2 = _devtools_server()
    try:
        with _Harness(write_port=True, port=port2, never_exit=True):
            ok, err, r = _try_launch(ready_timeout=5.0)
            check("照旧成功", ok and r[1] == port2, err)
    finally:
        srv2.shutdown()

    print("\n== D. 收尾：detach 之后必须能真的关掉（否则攒僵尸 Chrome）==")
    # 判据是"发出了 CDP `Browser.close`"，而不是"调了 terminate"——
    # detach 之后 terminate 是空操作，正因如此才会有僵尸进程。
    sent: list[str] = []
    old_conn = S.websocket.create_connection

    class _WS:
        def send(self, data):
            sent.append(json.loads(data).get("method", ""))

        def recv(self):
            return "{}"

        def close(self):
            pass

    S.websocket.create_connection = lambda url, timeout=5: _WS()
    proc = FakeProc(0)          # 已退出（= detach 后的启动器）
    try:
        S.close_chrome(port=1234, browser_ws="ws://127.0.0.1:1234/devtools/browser/x",
                       proc=proc, profile="")
    finally:
        S.websocket.create_connection = old_conn
    check("收尾走的是 CDP `Browser.close`", sent == ["Browser.close"], str(sent))
    check("没有对已退出的启动器做无意义的 terminate", proc.terminated is False)
    src = (ROOT / "tools" / "shot.py").read_text(encoding="utf-8")
    check("`atexit` 兜底真的注册了（漏了就会攒僵尸进程）",
          "atexit.register(close_all_chrome)" in src)

    print("\n== E.（反证）「启动器退出就判死」的旧写法必须已消失 ==")
    check("源码里不再有『一看到进程退出就 raise』的判据",
          "if proc.poll() is not None:\n            raise SystemExit(f\"Chrome 起来就退了"
          not in src)

    print("\n" + "=" * 62)
    print(f"通过 {_passed} · 失败 {len(_fail)}")
    for f in _fail:
        print("  ✗ " + f)
    print("=" * 62)
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
