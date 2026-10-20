"""构建期把可压缩的文本资源预压成 `.gz`（服务器只负责"该发哪个"）。

为什么不在运行时挂 `GZipMiddleware`
-----------------------------------
1. **它会伤功能**：那个中间件对**所有**响应生效，包括 `/api/search` 的
   SSE 流。gzip 的流包装要攒够一块才吐，就把"逐条出结果"变成
   "憋一会儿一起出" —— 那正是这个项目最怕的体验（搜书时盯着空屏）。
2. **白烧 CPU**：每次请求现压 638KB，一天几万次请求就是几万次压缩。
   预压缩只压一次。

那为什么不只靠 `Cache-Control` 304
----------------------------------
304 只能救"老用户二次访问"。**新用户/换设备/清缓存**第一次拿到的就是
638KB 明文 —— 实测线上 `vue-app.js` 638KB、无 `Content-Encoding`，
轻量服务器带宽下首屏要 5~6 秒才挂上 Vue。这才是要治的那一次。

口径
----
· 只压**文本**（js/css/html/json/svg/txt）。图片/字体本来就是压缩格式，
  再压只会更大 —— 而且会白占一份磁盘。
· 小于 `MIN_BYTES` 的不压：HTTP 头本身就几十字节，压了反而更慢。
· `gzip.compress(..., mtime=0)`：同样的源文件压出**同样字节**，
  避免每次构建 `.gz` 都在 git 里显出一个"全变了"的 diff。
"""
from __future__ import annotations

import gzip
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"

TEXT_EXT = {".js", ".css", ".html", ".json", ".svg", ".txt"}
MIN_BYTES = 1024


def build(static_dir: Path | str | None = None, verbose: bool = True) -> tuple[int, int, int]:
    """生成/刷新 `.gz`。返回 (处理数, 原始总字节, 压缩后总字节)。"""
    base = Path(static_dir) if static_dir else STATIC
    n = raw_total = gz_total = 0
    if not base.is_dir():
        if verbose:
            print(f"  ~ 没有 {base}，跳过预压缩")
        return 0, 0, 0

    for p in sorted(base.rglob("*")):
        if not p.is_file() or p.name.endswith(".gz"):
            continue
        if p.suffix.lower() not in TEXT_EXT:
            continue
        gz = p.with_name(p.name + ".gz")
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        if len(raw) < MIN_BYTES:
            # 太小：把可能残留的旧 .gz 删掉，别让它比源文件还大
            if gz.exists():
                try:
                    gz.unlink()
                except OSError:
                    pass
            continue
        try:
            fresh = (gz.exists()
                     and gz.stat().st_mtime >= p.stat().st_mtime
                     and gz.stat().st_size > 0)
        except OSError:
            fresh = False
        if not fresh:
            data = gzip.compress(raw, 9, mtime=0)
            tmp = gz.with_name(gz.name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, gz)
        n += 1
        raw_total += len(raw)
        gz_total += gz.stat().st_size

    if verbose:
        if n:
            print(f"  ✓ 预压缩 {n} 个文件  "
                  f"{raw_total // 1024}KB → {gz_total // 1024}KB"
                  f"（省 {100 - gz_total * 100 // max(raw_total, 1)}%）")
        else:
            print("  ~ 没有需要预压缩的文本资源")
    return n, raw_total, gz_total


def main() -> int:
    n, raw, gz = build()
    return 0 if n >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
