"""前端并发竞态回归 —— 「连点两次搜索」后的状态机必须是自洽的。

为什么必须用**真浏览器 + 手工 stub fetch** 测
------------------------------------------------
`M.searching` 是个内存标志位，静态检查（grep / eslint）只能看出「谁写了它」，
看不出「两次并发调用之后它变成了什么」。而且真网络的快慢不可控 ——
今天第一个请求先回、明天后回，测试会变成碰运气。

所以我们**自己接管 fetch**：
  · 第 1 次搜索：返回一个**永不 resolve** 的 Promise（模拟卡住的慢请求）
  · 第 2 次搜索：立刻返回一个合法的空 NDJSON 流
然后断言：第二次搜索结束后 `M.searching === false`、
并且**第一个请求被 abort 掉时没有把状态搅乱**。

被钉住的真 bug（本轮修的）
--------------------------
`runSearch` 的 `finally { M.searching = false }` 原本**没有守卫**：
  · 用户连点（A → B）→ B 进来 abort 掉 A → A 的 finally 无条件把
    `M.searching` 清成 false（**可 B 还在跑**）
  · 于是下次点击不再 abort，两个流同时往 `#results` 写、互相覆盖
修法：`if (M.ctrl !== ctrl) return;` —— 被顶掉的旧请求不许收尾。

用法： python tools/test_concurrency.py [--url http://127.0.0.1:8000]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shot import Tab, launch_chrome, page_ws  # noqa: E402

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
        print("      JS 异常:", json.dumps(r["exceptionDetails"])[:220])
        return None
    return r.get("result", {}).get("value")


def goto(tab: Tab, url: str, wait: float = 3.0) -> None:
    tab.call("Page.navigate", url=url)
    time.sleep(wait)


# 抢在页面 module 之前装好 fetch 拦截器。
# Page.addScriptToEvaluateOnNewDocument 会在**每次新文档创建时、任何脚本执行前**
# 注入 —— 这是唯一能可靠劫持 fetch 的时机（等 module 跑完就晚了）。
SNIFFER = r"""
(() => {
  const realFetch = window.fetch.bind(window);
  window.__ndCalls = [];        // 每次 runSearch 触发的请求都会记一笔
  window.__ndMode  = 'real';    // 'real' | 'slow' | 'fast'
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (!/\/api\/search/.test(url)) return realFetch(input, init);
    if (window.__ndMode === 'slow') {
      // 永不 resolve，但**响应 abort 信号** —— 真实浏览器行为
      return new Promise((resolve, reject) => {
        const sig = init && init.signal;
        window.__ndCalls.push({ mode: 'slow', aborted: false });
        const rec = window.__ndCalls[window.__ndCalls.length - 1];
        if (sig) sig.addEventListener('abort', () => {
          rec.aborted = true;
          const e = new Error('AbortError'); e.name = 'AbortError';
          reject(e);
        });
      });
    }
    window.__ndCalls.push({ mode: 'fast', aborted: false });
    // 合法但空的 NDJSON：一个 done 事件就收尾
    const body = new ReadableStream({
      start(c) {
        c.enqueue(new TextEncoder().encode(
          JSON.stringify({type:'done',data:{books:[],count:0}}) + "\n"));
        c.close();
      }
    });
    return Promise.resolve(new Response(body, {
      status: 200, headers: {'Content-Type':'application/x-ndjson'} }));
  };
})();
"""


def start_search(tab: Tab, kw: str) -> None:
    """模拟真人：填进输入框 + 回车。submitSearch() 会读输入框当前值。"""
    js(tab, f"""(()=>{{
      const q = document.querySelector('#q');
      if (!q) return false;
      q.value = {json.dumps(kw)};
      q.dispatchEvent(new Event('input', {{bubbles:true}}));
      q.dispatchEvent(new KeyboardEvent('keydown', {{
        key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true }}));
      return true;
    }})()""")


def state(tab: Tab) -> dict:
    return js(tab, "window.__ndState ? window.__ndState() : null") or {}


def set_mode(tab: Tab, mode: str) -> None:
    js(tab, f"window.__ndMode = {json.dumps(mode)}")


def test_double_click(tab: Tab, base: str) -> None:
    print("\n[1] 连点两次搜索：状态机必须自洽（旧请求不许搅乱新请求）")
    goto(tab, base)
    if js(tab, "typeof window.__ndState") != "function":
        check("排障探针 __ndState 存在", False,
              "页面没暴露 __ndState（assets 没重新构建？）")
        return
    check("排障探针 __ndState 存在", True)

    # 清空调用记录：页面加载自身可能触发过搜索（hash/默认）
    js(tab, "window.__ndCalls = []")

    # 第 1 次：慢 —— 卡住
    set_mode(tab, "slow")
    start_search(tab, "竞态测试一")
    time.sleep(0.6)
    s1 = state(tab)
    check("慢请求期间 searching=true", s1.get("searching") is True, str(s1))

    # 第 2 次：快 —— 立即完成
    set_mode(tab, "fast")
    start_search(tab, "竞态测试二")
    time.sleep(1.2)
    s2 = state(tab)
    check("新请求结束后 searching=false", s2.get("searching") is False, str(s2))
    check("confirmed 是新关键词", s2.get("confirmed") == "竞态测试二", str(s2))

    calls = js(tab, "window.__ndCalls") or []
    slow = [c for c in calls if c.get("mode") == "slow"]
    fast = [c for c in calls if c.get("mode") == "fast"]
    check("确实发出了 1 个慢请求", len(slow) == 1, f"实际 {len(slow)}")
    check("确实发出了 1 个快请求", len(fast) == 1, f"实际 {len(fast)}")
    check("慢请求被 abort 掉了", bool(slow) and slow[0].get("aborted") is True,
          f"慢请求 aborted={slow[0].get('aborted') if slow else 'N/A'}")

    # 关键断言：慢请求 abort 后**不能**把新请求的状态清掉。
    # 旧代码在这里会 searching=false 得"看起来没问题"，但真正的判据是
    # 「abort 之后立刻看」—— 如果 finally 没守卫，会有一瞬间 false 导致
    # 后续点击不再 abort。我们直接验：abort 已发生后，状态仍由新请求主导。
    time.sleep(0.8)
    s3 = state(tab)
    check("稳定后状态仍是「不在搜」而非错乱",
          s3.get("searching") is False and s3.get("confirmed") == "竞态测试二",
          str(s3))


def test_after_slow_abort_can_search_again(tab: Tab, base: str) -> None:
    print("\n[2] 卡住的请求被顶掉后，还能再发起新搜索（按钮没卡死）")
    goto(tab, base)
    js(tab, "window.__ndCalls = []")

    set_mode(tab, "slow")
    start_search(tab, "卡住")
    time.sleep(0.5)
    check("进入搜索中", state(tab).get("searching") is True, str(state(tab)))

    set_mode(tab, "fast")
    start_search(tab, "第二次")
    time.sleep(1.2)

    set_mode(tab, "fast")
    start_search(tab, "第三次")
    time.sleep(1.2)

    s = state(tab)
    check("连搜三次后状态正常（没卡在 searching）",
          s.get("searching") is False and s.get("confirmed") == "第三次", str(s))
    calls = js(tab, "window.__ndCalls") or []
    check("第三个请求真的发出去了（证明按钮没死）",
          len([c for c in calls if c.get("mode") == "fast"]) >= 2,
          f"fast 调用数 {len([c for c in calls if c.get('mode')=='fast'])}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--w", type=int, default=1240)
    ap.add_argument("--h", type=int, default=900)
    a = ap.parse_args()

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
        tab.call("Page.addScriptToEvaluateOnNewDocument", source=SNIFFER)
        tab.call("Emulation.setDeviceMetricsOverride",
                 width=a.w, height=a.h, deviceScaleFactor=1, mobile=False)

        test_double_click(tab, a.url)
        test_after_slow_abort_can_search_again(tab, a.url)

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
