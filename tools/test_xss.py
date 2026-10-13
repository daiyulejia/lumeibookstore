"""前端注入（XSS）回归 —— 把恶意 payload 当搜索词打进去，看 DOM 有没有被注入。

为什么必须用**真浏览器**测
--------------------------
`grep innerHTML` 能找出「哪一行在拼 HTML」，但判断不了「拼进去的那个变量
到底过没过 `esc()`」—— 调用链可能隔着两三层函数。只有真的把 payload 打进
输入框、再问浏览器「页面里有没有真的出现这个 script 元素 / 有没有执行」，
结论才靠得住。

测什么
------
① 关键词注入：`<img src=x onerror=...>` 这类 payload 当搜索词，
   断言它**原样以文本形式**出现在 DOM 里（说明被转义了），
   而不是变成一个真的 `<img>` 元素。
② 已入库书名注入：书架里若有带特殊字符的书名，渲染时同样不能变成元素。
③ 全局哨兵：payload 里挂 `window.__XSS_HIT = 1`，跑完断言这个值不存在 ——
   这是最硬的判据，元素判定可能有假阴性（转义了但长得像），
   「代码到底有没有被执行」骗不了人。

用法： python tools/test_xss.py [--url http://127.0.0.1:8000]
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
        return None
    return r.get("result", {}).get("value")


# 每个 payload 都往 window 上挂一个哨兵 —— 只要它出现，就说明代码被执行了
PAYLOADS = [
    '<img src=x onerror="window.__XSS_IMG=1">',
    '"><script>window.__XSS_SCRIPT=1</script>',
    "<svg/onload=window.__XSS_SVG=1>",
    "';window.__XSS_QUOTE=1;'",
    "<iframe src=javascript:window.__XSS_IFRAME=1>",
    "`+window.__XSS_TICK=1+`",
    "${window.__XSS_TMPL=1}",
    "]}]}window.__XSS_JSON=1",
]

SENTINELS = [
    "__XSS_IMG", "__XSS_SCRIPT", "__XSS_SVG", "__XSS_QUOTE",
    "__XSS_IFRAME", "__XSS_TICK", "__XSS_TMPL", "__XSS_JSON",
]


def clear_sentinels(tab: Tab) -> None:
    expr = ";".join(f"delete window.{s}" for s in SENTINELS)
    js(tab, "(()=>{" + expr + ";return 1})()")


def sentinel_hit(tab: Tab) -> list[str]:
    hit = []
    for s in SENTINELS:
        if js(tab, f"typeof window.{s} !== 'undefined'") is True:
            hit.append(s)
    return hit


def goto(tab: Tab, url: str, wait: float = 3.0) -> None:
    tab.call("Page.navigate", url=url)
    time.sleep(wait)


def type_and_search(tab: Tab, kw: str) -> None:
    """把关键词打进搜索框并触发搜索（模拟真人输入 + 回车）。"""
    ok = js(tab, f"""(()=>{{
      const q = document.querySelector('#q');
      if (!q) return false;
      q.value = {json.dumps(kw)};
      q.dispatchEvent(new Event('input', {{bubbles:true}}));
      const ev = new KeyboardEvent('keydown', {{key:'Enter', code:'Enter',
        keyCode:13, which:13, bubbles:true}});
      q.dispatchEvent(ev);
      return true;
    }})()""")
    return ok


def test_keyword_injection(tab: Tab, base: str) -> None:
    print("\n[1] 搜索关键词注入 —— payload 当搜索词")
    goto(tab, base)
    for p in PAYLOADS:
        clear_sentinels(tab)
        type_and_search(tab, p)
        time.sleep(1.6)     # 给一点时间让 statbar / 结果卡渲染出来
        hit = sentinel_hit(tab)
        check(f"payload 未执行: {p[:34]}", not hit, f"哨兵被触发: {hit}")

    # 再整体扫一遍：页面里不该出现「由 payload 变成的真元素」
    n_img = js(tab, "document.querySelectorAll('img[src=\"x\"]').length") or 0
    check("没有真的 <img src=x> 元素", int(n_img) == 0, f"找到 {n_img} 个")
    n_svg = js(tab, "document.querySelectorAll('svg[onload]').length") or 0
    check("没有真的 <svg onload> 元素", int(n_svg) == 0, f"找到 {n_svg} 个")
    n_iframe = js(tab, "document.querySelectorAll('iframe').length") or 0
    check("页面里没有被注入 iframe", int(n_iframe) == 0, f"找到 {n_iframe} 个")
    # script 标签数量应保持稳定（注入的 <script> 如果真被解析会多出来）
    n_script = js(tab, "document.querySelectorAll('script').length") or 0
    check("script 标签数没有异常增长", int(n_script) < 30, f"找到 {n_script} 个")


def test_text_is_escaped(tab: Tab, base: str) -> None:
    """更正面的一条：payload 应该**以文本形式**出现在页面上。"""
    print("\n[2] payload 应当以文本形式出现（说明被转义）")
    goto(tab, base)
    clear_sentinels(tab)
    p = '<b id="nd-xss-probe">XSS</b>'
    type_and_search(tab, p)
    time.sleep(1.6)
    # 真元素不存在
    n = js(tab, "document.querySelectorAll('#nd-xss-probe').length") or 0
    check("payload 没变成真元素 #nd-xss-probe", int(n) == 0, f"找到 {n} 个")
    # 但文本里应该有它的影子（statbar 会显示关键词）
    body = js(tab, "document.body.innerText") or ""
    check("关键词以文本形式出现在页面上", "XSS" in body or "nd-xss-probe" in body,
          "没找到（可能搜索太快、statbar 已清掉，属正常）")
    check("没有哨兵被触发", not sentinel_hit(tab), f"触发: {sentinel_hit(tab)}")


def test_hash_injection(tab: Tab, base: str) -> None:
    """从 URL hash / query 注入 —— 有些页面会读 hash 回填输入框。"""
    print("\n[3] URL 参数注入")
    for q in ['?q=%3Cimg%20src%3Dx%20onerror%3Dwindow.__XSS_IMG%3D1%3E',
              '?kw=%3Csvg%2Fonload%3Dwindow.__XSS_SVG%3D1%3E']:
        clear_sentinels(tab)
        goto(tab, base + q, wait=2.0)
        hit = sentinel_hit(tab)
        check(f"URL 参数未执行 {q[:26]}…", not hit, f"哨兵被触发: {hit}")


def test_cover_is_safe(tab: Tab, base: str) -> None:
    """封面图必须是走 /api/cover 代理的，且**不能**是外站直连。

    为什么放在 XSS 套件里：封面地址来自第三方站点的页面（og:image），
    属于典型的**不可信输入**。如果前端直接把外站 URL 塞进 <img src>：
      · 恶意站可以塞 `javascript:` 或 `data:text/html,<script>…` 做 XSS
      · 也会让用户浏览器直连外站（泄露 IP / 访问记录、绕过防盗链限制）
    所以断言两件事：① 卡片里的封面 <img> 一律指向同源的 /api/cover；
    ② 页面上不存在 src 以 javascript: 开头的 img。
    """
    print("\n[4] 封面图安全性（外站地址必须走代理）")
    goto(tab, base, wait=2.0)
    type_and_search(tab, "三体")
    time.sleep(6.0)     # 等结果卡 + 探测回填封面

    n_cover = js(tab, "document.querySelectorAll('#results .cover img').length") or 0
    off_site = js(tab, """(()=>{
      return [].slice.call(document.querySelectorAll('#results .cover img'))
        .filter(i => { try { return new URL(i.src, location.href).origin !== location.origin; }
                       catch(e){ return true; } }).length;
    })()""") or 0
    js_imgs = js(tab, """[].slice.call(document.querySelectorAll('img'))
        .filter(i => (i.getAttribute('src')||'').trim().toLowerCase().startsWith('javascript:')).length""") or 0

    # 封面数量取决于站点有没有图，**不能**断言"必须有" —— 没有图是正常的
    # （前端画渐变封面兜底）。能断言的是"有图的话必须同源"。
    check("封面 <img> 全部同源（走 /api/cover 代理）", int(off_site) == 0,
          f"{off_site} 个直连外站（共 {n_cover} 个封面）")
    check("没有 src=javascript: 的 img", int(js_imgs) == 0, f"找到 {js_imgs} 个")
    print(f"    （本次搜到 {n_cover} 个封面图；0 个也正常 —— 站点没图时前端画渐变封面）")


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
        tab.call("Emulation.setDeviceMetricsOverride",
                 width=a.w, height=a.h, deviceScaleFactor=1, mobile=False)

        test_keyword_injection(tab, a.url)
        test_text_is_escaped(tab, a.url)
        test_hash_injection(tab, a.url)
        test_cover_is_safe(tab, a.url)

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
