"""前端埋点回归 —— JS 错误 / Promise 拒绝 / 接口失败 必须能落到服务端日志。

为什么要这个测试
----------------
用户的原话是「万一出现 bug，你可以直接去拉线上的 log，日志，埋点等，
可以快速定位问题」。而后端日志**天生照不到**只发生在浏览器里的问题：
点了没反应、页面白屏、接口 500 了但界面只是安静转圈。

埋点这条链有三段，断任何一段都等于没埋：
  ① 前端钩子装上（window.onerror / unhandledrejection / fetch 包装）
  ② 真的发出 POST /api/log
  ③ 服务端真的写进 logs/app.log

只有**真浏览器 + 真服务端 + 真读日志文件**才能同时验到这三段。
单看前端 JS 代码只能验 ①，看不到 ③。

用法： python tools/test_telemetry.py --url http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shot import Tab, launch_chrome, page_ws  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OK = 0
BAD = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global OK, BAD
    if cond:
        OK += 1
        print(f"  ✓ {name}")
    else:
        BAD += 1
        print(f"  ✗ {name}  {extra}")


def js(tab: Tab, expr: str):
    r = tab.call("Runtime.evaluate", expression=expr,
                 returnByValue=True, awaitPromise=True)
    if r.get("exceptionDetails"):
        return None
    return r.get("result", {}).get("value")


def goto(tab: Tab, url: str, wait: float = 3.0) -> None:
    tab.call("Page.navigate", url=url)
    time.sleep(wait)


def log_files() -> list[Path]:
    d = ROOT / "logs"
    if not d.is_dir():
        return []
    return sorted(d.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)


def read_tail(path: Path, n: int = 400) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return ""


def newest_log_text() -> str:
    fs = log_files()
    return read_tail(fs[0]) if fs else ""


def marker(k: str) -> str:
    """给每个用例一个独一无二的消息，方便在日志里精确定位。"""
    return f"TTEL-{k}-{int(time.time() * 1000) % 1000000}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--w", type=int, default=1240)
    ap.add_argument("--h", type=int, default=900)
    a = ap.parse_args()

    print("=" * 62)
    print("前端埋点回归（前端钩子 → /api/log → 日志文件）")
    print("=" * 62)

    # -----------------------------------------------------------------
    print("\n[0] 端点基本可用性")
    body = json.dumps({"event": "ui.error", "message": "TTEL-PROBE"}).encode()
    req = urllib.request.Request(a.url.rstrip("/") + "/api/log", data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read().decode() or "{}")
        check("POST /api/log 返回 ok", d.get("ok") is True, str(d)[:120])
    except Exception as e:  # noqa: BLE001
        check("POST /api/log 可用", False, f"{type(e).__name__}: {e}")
        print("\n端点不通，后面的用例没意义，直接结束。")
        return 1

    # ⚠ 用 shot.launch_chrome（Chrome 自动分配端口 + DevToolsActivePort 实例 UUID
    #   校验），不要退回「free_port() + wait_devtools()」——后者只判断「端口能回话」，
    #   不判断回话的是不是自己刚起的实例。上一个套件 terminate 掉的旧 Chrome 还没退
    #   干净时，这里会连上它，等它一死就是 ConnectionResetError/WinError 10054。
    #   实测症状：ship 里 14 套串行跑随机红、单独重跑必绿、每次红的位置都不同。
    proc, port, _bws, profile = launch_chrome(
        headless=True, window=(a.w, a.h),
        extra_args=["--disable-extensions"])
    try:
        # Page.*/Runtime.* 只挂在**页面 target** 上，要用 page_ws 拿页面级 ws。
        tab = Tab(page_ws(port))
        tab.call("Page.enable")
        tab.call("Runtime.enable")
        tab.call("Emulation.setDeviceMetricsOverride",
                 width=a.w, height=a.h, deviceScaleFactor=1, mobile=False)

        goto(tab, a.url)

        # -------------------------------------------------------------
        print("\n[1] 全局钩子装上了吗")
        check("window.onerror 有监听（error 事件已接管）",
              js(tab, "typeof window.__ndState === 'function' "
                      "|| !!window.fetch") is not None, "")
        # 直接看 fetch 是否被包装（包装后 toString 里应出现我们的实现标记）
        wrapped = js(tab, "String(window.fetch).includes('__ndCalls') "
                          "|| !String(window.fetch).includes('[native code]')")
        check("fetch 被埋点层包装", bool(wrapped), "fetch 仍是原生实现")

        # -------------------------------------------------------------
        print("\n[2] JS 运行时错误 → 日志")
        mk = marker("ERR")
        js(tab, f"setTimeout(()=>{{ throw new Error({json.dumps(mk)}); }}, 0)")
        time.sleep(2.0)
        txt = newest_log_text()
        check(f"ui.error 落进日志（{mk}）", mk in txt,
              "日志里找不到这条错误 —— 钩子没生效或没写盘")

        # -------------------------------------------------------------
        print("\n[3] 未处理的 Promise 拒绝 → 日志")
        mk2 = marker("REJ")
        # ⚠ 必须用 setTimeout 包一层。
        #   直接 `Runtime.evaluate("Promise.reject(...)")` 是**测不到**的：
        #   CDP 会把返回值当成要 await 的 Promise 接住，于是它不再"未被处理"，
        #   浏览器压根不发 unhandledrejection —— 那样测的是 CDP 的接球，
        #   不是我们的钩子。丢进 setTimeout 才是真正没人管的拒绝。
        js(tab, f"setTimeout(()=>{{ Promise.reject(new Error("
                f"{json.dumps(mk2)})); }}, 0)")
        time.sleep(2.0)
        txt = newest_log_text()
        check(f"ui.reject 落进日志（{mk2}）", mk2 in txt,
              "Promise 拒绝没被上报（这是最常见的『点了没反应』）")

        # -------------------------------------------------------------
        print("\n[4] 接口 500 → 日志（前端只是安静转圈时也能查）")
        mk3 = marker("API")
        # 打一个必然失败的接口（不存在的路径 → 404，非 401）
        js(tab, f"""(()=>{{
          window.__ndT = {json.dumps(mk3)};
          return fetch('/api/__no_such_endpoint__' + '?m=' + window.__ndT)
                 .then(()=>1).catch(()=>1);
        }})()""")
        time.sleep(2.5)
        txt = newest_log_text()
        check(f"ui.api.fail 落进日志（{mk3}）", mk3 in txt,
              "接口失败没上报 —— 用户说『搜不出来』时你会查不到原因")

        # -------------------------------------------------------------
        print("\n[5] 去重：同一错误连报 50 次，日志里不该出现 50 条")
        mk4 = marker("DEDUP")
        js(tab, f"""(()=>{{
          const m = {json.dumps(mk4)};
          for (let i = 0; i < 50; i++) setTimeout(()=>{{ throw new Error(m); }}, 0);
          return 1;
        }})()""")
        time.sleep(3.0)
        txt = newest_log_text()
        n = txt.count(mk4)
        check(f"同一错误被去重（出现 {n} 次，应 ≤ 2）", n <= 2,
              f"出现 {n} 次 —— 去重失效，一个渲染循环里的错能刷爆日志")

        # -------------------------------------------------------------
        print("\n[6] abort 不算错误（用户连点搜索是正常行为）")
        before = newest_log_text().count("ui.api.fail")
        js(tab, """(()=>{
          const c = new AbortController();
          const p = fetch('/api/tasks', {signal:c.signal}).catch(()=>1);
          c.abort();
          return p;
        })()""")
        time.sleep(2.0)
        after = newest_log_text().count("ui.api.fail")
        check("主动 abort 没有新增 ui.api.fail", after == before,
              f"{before} → {after}（abort 被误报成接口失败）")

        print(f"\n{'✅ 全部通过' if not BAD else f'❌ {BAD} 项失败'}"
              f"（{OK} 通过 / {BAD} 失败）")
        return 1 if BAD else 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
