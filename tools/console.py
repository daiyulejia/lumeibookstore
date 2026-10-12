"""打开页面，把控制台报错和未捕获异常抓出来。

为什么需要它：前端出错时截图只会给你一张"没渲染出来"的图，
看不出原因。这个脚本直接连 DevTools，把 console.error 和
window.onerror 全收下来打印 —— 排 JS 问题时比截图快十倍。

用法：
  python tools/console.py <url> [--ms 15000] [--w 1240] [--h 860] [--run "js表达式"]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shot import Tab, find_chrome, free_port, wait_devtools  # noqa: E402

import os  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import urllib.request  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--ms", type=int, default=15000)
    ap.add_argument("--w", type=int, default=1240)
    ap.add_argument("--h", type=int, default=860)
    ap.add_argument("--run", default="", help="加载后额外跑一段 JS")
    ap.add_argument("--pre", default="", help="页面脚本执行前先跑（预置 localStorage 等）")
    a = ap.parse_args()

    chrome = find_chrome()
    port = free_port()
    profile = tempfile.mkdtemp(prefix="nd-console-")

    proc = subprocess.Popen(
        [chrome, "--headless=new", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", f"--window-size={a.w},{a.h}",
         "--no-first-run", "--no-default-browser-check", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_devtools(port)
        # 直接用已经开着的那个标签页（新版 Chrome 的 /json/new 要 PUT，怪麻烦的）
        tab_url = ""
        for _ in range(40):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
                targets = json.load(r)
            for t in targets:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    tab_url = t["webSocketDebuggerUrl"]
                    break
            if tab_url:
                break
            time.sleep(0.25)
        if not tab_url:
            raise SystemExit("没找到可用的标签页")
        tab = Tab(tab_url)

        tab.call("Runtime.enable")
        tab.call("Log.enable")
        tab.call("Page.enable")

        # 收集日志
        logs: list[str] = []
        orig = tab.call

        def pump(seconds: float) -> None:
            """非阻塞地把 ws 上堆积的事件读出来。"""
            tab.ws.settimeout(0.25)
            deadline = time.time() + seconds
            while time.time() < deadline:
                try:
                    raw = tab.ws.recv()
                except Exception:
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                m = msg.get("method")
                if m == "Runtime.consoleAPICalled":
                    args = msg["params"].get("args", [])
                    txt = " ".join(str(x.get("value", x.get("description", ""))) for x in args)
                    if msg["params"].get("type") in ("error", "warning"):
                        logs.append(f"[{msg['params']['type']}] {txt}")
                elif m == "Runtime.exceptionThrown":
                    d = msg["params"]["exceptionDetails"]
                    desc = (d.get("exception") or {}).get("description") or d.get("text")
                    logs.append(f"[异常] {desc}")
                elif m == "Log.entryAdded":
                    e = msg["params"]["entry"]
                    if e.get("level") in ("error", "warning"):
                        logs.append(f"[{e['level']}/{e.get('source')}] {e.get('text')} {e.get('url','')}")
            # 恢复长超时，否则后面 Runtime.evaluate 会误判成超时
            tab.ws.settimeout(60)

        if a.pre:
            tab.call("Page.addScriptToEvaluateOnNewDocument", source=a.pre)
        tab.call("Page.navigate", url=a.url)
        pump(a.ms / 1000)

        if a.run:
            print("---- run ----")
            print(tab.js(a.run))
            pump(3)

        print("---- 控制台 ----")
        if logs:
            for line in logs[:60]:
                print(line[:400])
        else:
            print("（干净，没有报错）")

        print("---- 状态 ----")
        print(tab.js("""JSON.stringify({
          url: location.href,
          title: document.title,
          ready: document.readyState,
          theme: document.documentElement.dataset.theme,
          bg: document.documentElement.dataset.bg,
          readerOpen: !!document.querySelector('#reader.on'),
          rdMode: (document.querySelector('#reader')||{}).dataset?.rdMode,
          pages: document.querySelectorAll('.rd-page').length,
          flipPages: document.querySelectorAll('.flipbook .page').length,
          scrollLen: (document.querySelector('#rdScrollBody')||{}).innerText?.length || 0,
          chap: (document.querySelector('#rdChap')||{}).textContent
        })"""))
        return 0
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
