#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
静态资源缓存策略自检
============================================================================
为什么单开一条
--------------
2026-10-14：把首页「每天轮换的那对图必须含噜妹」修好了，服务器上确实是新的，
**但用户手机上还看到两个噜噜** —— 因为浏览器一直在跑**缓存的旧 art.js**。

根因在前端结构：页面里只有入口 `/static/js/main.js?v=1791…` 带版本号，
而模块之间的 `import "./art.js"` 是**裸路径，拿不到 `?v=`**。
于是 art.js 走的是"没有 Cache-Control"的默认策略 —— 浏览器按
`Last-Modified` 做**启发式缓存**（约 10% 的年龄），而且每次 304 命中后
还会**续期**，越用越难更新。结果：**改一个模块内的 JS，用户可能几天都拿不到。**

这一坑最阴的地方：**只在服务器上查永远发现不了**（线上文件是新的），
必须站在"浏览器缓存"的角度才能看见。

判据（只看真实 HTTP 响应头，不做源码字符串匹配 —— 那种断言会被注释骗过）
  · `/static/**/*.js`、`/static/**/*.css` → 必须 `no-cache`
    （= 用前先校验；配 ETag 没变就 304，几乎不费流量）
  · 图片 → **不该**是 no-cache（体积大、换素材会换文件名，长缓存更划算）
  · `/`（HTML）→ 必须 `no-cache`，否则前端改了用户看不到

用法：
    python tools/test_cache_headers.py [--url http://127.0.0.1:8000]
"""
from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

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


def head(url: str, timeout: float = 10.0):
    """取响应头（先试 HEAD，服务端不支持就退化成 GET）。"""
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return {k.lower(): v for k, v in r.headers.items()}
        except urllib.error.HTTPError as e:
            return {k.lower(): v for k, v in e.headers.items()}
        except Exception:  # noqa: BLE001
            continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    a = ap.parse_args()

    base = a.url.rstrip("/")
    srv = None
    if not base:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from ship import LocalServer
        srv = LocalServer()
        srv.__enter__()
        base = srv.base

    try:
        print(f"目标：{base}")

        # ---- 代码类资源必须 no-cache -------------------------------------
        # ⚠ 这里用**真实响应头**而不是去 grep main.py：
        #   源码里写了 `Cache-Control` 但没生效（比如被 StaticFiles 覆盖、
        #   或换了个 mount）的情况，只有发一次请求才看得出来。
        #   本项目已经栽过太多次「看着写了、其实没生效」，所以只认响应头。
        for path in ("/static/js/art.js", "/static/js/main.js",
                     "/static/css/app.css", "/static/css/lumei.css"):
            h = head(base + path)
            if h is None:
                check(f"{path} 能取到响应头", False, "请求失败")
                continue
            cc = (h.get("cache-control") or "").lower()
            check(f"{path} 带 no-cache（发版即生效）", "no-cache" in cc,
                  f"Cache-Control={cc!r} —— 模块内的 import 是裸路径，"
                  f"没有 no-cache 用户会一直跑旧代码")

        # ---- 图片：应当**可长缓存**，不该被一刀切成 no-cache -------------
        # 反过来也要验：如果为了修上面那条把图片也设成 no-cache，
        # 每次都要回源下载整张图 —— 那是把"能缓存"的东西白白浪费掉。
        h = head(base + "/static/img/lumei/hero_lumei@480.webp")
        if h is None:
            check("图片能取到响应头", False, "请求失败")
        else:
            cc = (h.get("cache-control") or "").lower()
            check("图片没有被设成 no-cache（该缓存还是要缓存）",
                  "no-cache" not in cc, f"Cache-Control={cc!r}")

        # ---- HTML：必须 no-cache ----------------------------------------
        h = head(base + "/")
        if h is None:
            check("/ 能取到响应头", False, "请求失败")
        else:
            cc = (h.get("cache-control") or "").lower()
            check("/ 带 no-cache（改了前端用户能看到）", "no-cache" in cc,
                  f"Cache-Control={cc!r}")

        # ---- HTML 里的资源引用要带版本号 ---------------------------------
        # 这是第一道防线（配合上面的 no-cache 双保险）：
        # 版本号变了 URL 就变了，浏览器不可能拿旧文件配新页面。
        try:
            with urllib.request.urlopen(base + "/", timeout=10) as r:
                html = r.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            html = ""
        check("index.html 的 css/js 引用带 ?v= 版本号",
              bool(html) and "?v=" in html,
              "没有版本号 → 第一道防线失效，只剩 no-cache 兜底")
    finally:
        if srv is not None:
            srv.__exit__(None, None, None)

    print("\n" + "=" * 62)
    print(f"通过 {OK} · 失败 {BAD}")
    print("✓ 全部通过" if not BAD else "✗ 有失败")
    print("=" * 62)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
