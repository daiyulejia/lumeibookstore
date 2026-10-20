"""静态资源压缩回归（纯 HTTP，不需要浏览器，秒级）。

钉住两件事
----------
1. **发的是不是压缩过的**：`/static/dist/vue-app.js` 带
   `Accept-Encoding: gzip` 时必须有 `Content-Encoding: gzip`，且字节数
   远小于原文。这条不是"优化建议" —— 实测未压缩时线上首屏要 5~6 秒
   才挂上 Vue（638KB 明文），新用户第一次打开就是这个体感。
2. **没有波及 API**：`/api/*` 的响应**不许**被压缩。
   为什么不许：`/api/search` 是 SSE 流，gzip 的流包装要攒块，
   会把"逐条出结果"变成"憋一会儿一起出"。所以本项目刻意**不用**
   `GZipMiddleware`，只对 `/static` 回预压缩文件（见 tools/gzip_static.py）。
   这条判据就是防着哪天有人图省事把它挂上去。

另有两个"退路"也要验，否则压缩一旦出问题就是白屏：
  · 客户端不说 gzip → 必须回**原文**（不能发 gzip 字节给不认的客户端）
  · 图片（.webp）→ 不回 gzip（本来就压过，再压更大）
"""
from __future__ import annotations

import argparse
import gzip
import http.client
import sys
from urllib.parse import urlparse


def fetch(base: str, path: str, accept: str = "") -> tuple[int, dict, bytes]:
    u = urlparse(base)
    c = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=20)
    headers = {"Accept-Encoding": accept} if accept else {}
    c.request("GET", path, headers=headers)
    r = c.getresponse()
    body = r.read()
    hs = {k.lower(): v for k, v in r.getheaders()}
    st = r.status
    c.close()
    return st, hs, body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="服务地址，如 http://127.0.0.1:8303")
    ap.add_argument("--token", default="", help="线上实例的访问令牌（本地不需要）")
    a = ap.parse_args()

    if a.token and "t=" not in a.base:
        sep = "&" if "?" in a.base else "?"
        a.base = a.base.rstrip("/") + "/" + sep + "t=" + a.token

    fails: list[str] = []

    def check(label: str, cond: bool, extra: str = "") -> None:
        if cond:
            print(f"  ✓ {label}")
        else:
            fails.append(label)
            print(f"  ✗ {label} {extra}")

    print("== 静态资源预压缩 ==")
    JS = "/static/dist/vue-app.js"
    st_gz, h_gz, b_gz = fetch(a.base, JS, "gzip, deflate")
    st_raw, h_raw, b_raw = fetch(a.base, JS, "")

    check(f"取到 {JS}（{st_gz}）", st_gz == 200 and len(b_raw) > 0,
          f"status={st_gz} raw={len(b_raw)}")
    enc = h_gz.get("content-encoding", "")
    check(f"带 gzip 时回了压缩体（content-encoding={enc!r}）",
          enc == "gzip", "没压缩 —— 首屏会退回明文 600KB+")
    if enc == "gzip" and b_raw:
        ratio = len(b_gz) * 100 // len(b_raw)
        check(f"体积确实变小（{len(b_raw) // 1024}KB → {len(b_gz) // 1024}KB，{ratio}%）",
              ratio <= 60, f"只省到 {ratio}%，压缩没生效？")
        try:
            plain = gzip.decompress(b_gz)
        except Exception as e:  # noqa: BLE001
            plain = b""
            print(f"     （解压失败：{e}）")
        check("解压后与原文逐字节一致（不是坏包）",
              plain == b_raw, f"解压长度 {len(plain)} vs 原文 {len(b_raw)}")
    check("响应声明了 Vary: Accept-Encoding（缓存才对得上）",
          "accept-encoding" in h_gz.get("vary", "").lower(),
          f"vary={h_gz.get('vary')!r}")

    st_no, h_no, b_no = fetch(a.base, JS, "")
    check("客户端不接受 gzip → 回原文（不能把压缩体塞给它）",
          st_no == 200 and not h_no.get("content-encoding")
          and b_no[:2] != b"\x1f\x8b", f"enc={h_no.get('content-encoding')!r}")

    print()
    print("== 压缩不许波及 API ==")
    # 这条防的是"图省事挂 GZipMiddleware"：那会把 SSE 攒块。
    api = "/api/ranks/kinds"
    if a.token and "t=" not in api:
        api = api + "?t=" + a.token.split("t=")[-1]
    st_a, h_a, _ = fetch(a.base, api, "gzip, deflate")
    check(f"API 响应不被 gzip（{api} → {st_a}）",
          st_a == 200 and not h_a.get("content-encoding"),
          f"enc={h_a.get('content-encoding')!r} —— SSE 会被攒块，"
          f"搜书就不会逐条出结果了")

    print()
    print("== 已压缩格式不重复压 ==")
    # 找一张真实存在的图（首页插画），确认它不会被 gzip 一遍
    IMG = "/static/img/lumei/empty_wait@480.webp"
    st_i, h_i, _ = fetch(a.base, IMG, "gzip, deflate")
    if st_i == 200:
        check("webp 不回 gzip（再压只会更大）",
              not h_i.get("content-encoding"),
              f"enc={h_i.get('content-encoding')!r}")
    else:
        print(f"  ~ 跳过（{IMG} 不存在，{st_i}）")

    print()
    if fails:
        print(f"✗ {len(fails)} 项失败：")
        for f in fails:
            print(f"    {f}")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
