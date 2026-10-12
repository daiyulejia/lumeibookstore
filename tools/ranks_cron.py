"""定时刷新的执行体：打本地接口让**正在跑的服务**去刷新榜单。

为什么不自己 import 抓
----------------------
服务已经在跑，它的内存里有一份榜单缓存。如果这个脚本另起一个进程
去抓，有两个问题：
  ① 落盘文件是共享的，但**跑着的服务内存里还是旧的** —— 用户看到
     的还是老数据，等于白刷一轮。
  ② 抓取逻辑会变成两份（一份在服务里、一份在定时脚本里），
     哪天改了口径必然分裂。

所以这里只做一件事：`POST /api/ranks/refresh`，把刷新的活交给服务本体。
令牌从 cache/auth.json 读（和服务同源），不需要额外配置。

用法：
  python tools/ranks_cron.py                # 刷新全部
  python tools/ranks_cron.py --kind allvisit
  python tools/ranks_cron.py --port 8000 --quiet

退出码：0 成功；1 刷新失败；2 服务没在跑（定时任务里这属于"跳过"，
不是错误，但也值得在 journal 里留一句）。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_token() -> str:
    """从服务自己那份 auth.json 里取令牌。取不到就带着空令牌试 ——
    本机回环访问本来就不需要令牌（security.is_local 认回环）。"""
    for p in (ROOT / "cache" / "auth.json",):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            t = d.get("token") or d.get("access_token") or ""
            if t:
                return str(t)
        except Exception:  # noqa: BLE001
            pass
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="刷新 NovelDock 热榜缓存")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--kind", default="", help="只刷某类（默认全部）")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--no-force", action="store_true",
                    help="只补过期的，不强制全刷")
    a = ap.parse_args()

    tok = read_token()
    url = f"http://{a.host}:{a.port}/api/ranks/refresh"
    if a.kind:
        url += f"?kind={a.kind}"
    if tok:
        url += ("&" if "?" in url else "?") + f"t={tok}"
    if a.no_force:
        url += ("&" if "?" in url else "?") + "force=0"

    req = urllib.request.Request(url, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=150) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        print(f"[热榜刷新] 接口返回 {e.code}：{detail}", flush=True)
        return 1
    except Exception as e:  # noqa: BLE001
        # 连不上 = 服务没在跑。定时任务里这不算错误，但要留痕。
        print(f"[热榜刷新] 连不上服务（{a.host}:{a.port}）：{e}", flush=True)
        return 2

    try:
        d = json.loads(body)
    except Exception:  # noqa: BLE001
        print(f"[热榜刷新] 返回不是 JSON：{body[:200]}", flush=True)
        return 1

    ok = d.get("ok") and not d.get("error")
    if not a.quiet or not ok:
        st = d.get("status") or {}
        print(f"[热榜刷新] 成功 {d.get('ok')} 类 / 失败 {d.get('failed')} 类"
              f"，耗时 {d.get('elapsed')}s，缓存共 {st.get('total')} 条"
              f"（过期 {st.get('stale_count')} 类）", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
