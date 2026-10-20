"""真实书名探针：打线上 /api/search，量「到底有多能搜」。

为什么需要它：日志里只有 `search.done 书名=X 候选=0 成书=0`，
它告诉你「这一次没搜到」，但不告诉你「整体命中率是多少、是哪几本搜不到、
慢在哪」。做产品判断需要后三个数，所以得有一把能反复量的尺子。

用法：

    .venv\\Scripts\\python tools\\probe_search.py                 # 内置书单
    .venv\\Scripts\\python tools\\probe_search.py 三体 诡秘之主     # 指定书名
    .venv\\Scripts\\python tools\\probe_search.py --json          # 给自动化解析
    .venv\\Scripts\\python tools\\probe_search.py --local         # 打本地 8000
    .venv\\Scripts\\python tools\\probe_search.py --min-hit 0.8   # 命中率低于它就退出码 1

⚠⚠ 事件字段口径（踩过一次，整整一轮都在读错的字段）：
   `done` 事件里**没有** `results` 这个键。真实结构见 main.py:995：
       {"type":"done", "count":成书数, "candidates":候选数, "available":可读数,
        "books":[{title, author, readable_count, available_count, source_count,
                  chapter_count, tight, best_source_display, ...}], ...}
   早先按 `done["results"]` 读 → 永远是空列表 → 探针报「命中 0/8」，
   而当时线上其实是有结果的。**探针自己错了会伪装成产品坏了**，
   所以这里对"没拿到 books 键"单独判成 `schema_error`，绝不混进"0 条"。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

REMOTE = "http://106.53.203.108:8000"
LOCAL = "http://127.0.0.1:8000"
TOKEN = "xlSWxxI0HV_NZ8ISk6dl1Sl9"

# 冷热混搭：热门的搜不到 = 引擎坏了；冷门的搜不到 = 书库覆盖不够。
# 两种结论的处置完全不同，所以要分开看。
BOOKS = [
    ("三体", "hot"),
    ("斗破苍穹", "hot"),
    ("诡秘之主", "hot"),
    ("大奉打更人", "hot"),
    ("夜的命名术", "mid"),
    ("长夜余火", "mid"),
    ("青叶灵异事务所", "cold"),
    ("重生之爷太重口了", "cold"),
]

# 单本超过这个秒数就算「卡住」——引擎有 20s 硬上限，超过它说明上限本身失效了。
SLOW_S = 19.0


def _opener(base: str):
    # 本机走 8000 时把代理摘掉：环境里的 http_proxy 会让 127.0.0.1 也走代理 → 502。
    if base.startswith(LOCAL):
        os.environ.pop("http_proxy", None)
        os.environ.pop("HTTP_PROXY", None)
        os.environ.pop("https_proxy", None)
        os.environ.pop("HTTPS_PROXY", None)
        os.environ.pop("all_proxy", None)
        os.environ.pop("ALL_PROXY", None)
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def search(base: str, token: str, kw: str, timeout: float = 90.0) -> dict:
    """打一次搜索，返回一场账。"""
    q = urllib.parse.urlencode(
        {"kw": kw, "t": token, "discover": 1, "probe": 1, "sample": 1})
    url = f"{base}/api/search?{q}"
    op = _opener(base)
    t0 = time.time()
    items = verified_steps = 0
    done: dict | None = None
    err = ""
    try:
        with op.open(url, timeout=timeout) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                typ = ev.get("type")
                if typ == "item":
                    items += 1
                elif typ == "verified":
                    verified_steps += 1
                elif typ == "done":
                    done = ev
                elif typ == "error":
                    err = str(ev.get("msg") or "error")
    except Exception as e:  # noqa: BLE001
        return {"kw": kw, "error": f"{type(e).__name__}: {e}",
                "elapsed": round(time.time() - t0, 1)}

    elapsed = round(time.time() - t0, 1)
    base_row = {"kw": kw, "elapsed": elapsed, "items": items,
                "verified": verified_steps, "error": err}

    if done is None:
        base_row.update(books=0, schema_error="没有收到 done 事件")
        return base_row
    if "books" not in done:
        # 字段口径变了 → 必须报出来，不能当成「0 条结果」。
        base_row.update(books=0, schema_error=f"done 里没有 books 键：{sorted(done)}")
        return base_row

    books = done["books"] or []
    top = books[0] if books else {}
    base_row.update(
        books=len(books),
        candidates=done.get("candidates", 0),
        available=done.get("available", 0),
        readable_books=sum(1 for b in books if b.get("readable_count")),
        tight=any(b.get("tight") for b in books),
        top_title=top.get("title", ""),
        top_chapters=top.get("chapter_count", 0),
        top_readable=top.get("readable_count", 0),
        top_sources=top.get("source_count", 0),
        top_src=top.get("best_source_display") or top.get("best_source") or "",
        # 前 5 本，给「搜到了但都是沾边货」这种情况留证据
        titles=[b.get("title", "") for b in books[:5]],
    )
    return base_row


def main() -> int:
    ap = argparse.ArgumentParser(description="真实书名打线上搜索，量命中率")
    ap.add_argument("names", nargs="*", help="书名，留空用内置书单")
    ap.add_argument("--base", default="", help="服务地址，默认线上")
    ap.add_argument("--token", default=TOKEN)
    ap.add_argument("--local", action="store_true", help="打本地 http://127.0.0.1:8000")
    ap.add_argument("--json", action="store_true", help="输出 JSON（给自动化用）")
    ap.add_argument("--min-hit", type=float, default=0.0,
                    help="命中率低于它就退出码 1")
    ap.add_argument("--gap", type=float, default=1.0, help="两次请求之间的间隔秒")
    a = ap.parse_args()

    base = a.base or (LOCAL if a.local else REMOTE)
    todo = [(n, "given") for n in a.names] if a.names else BOOKS

    rows = []
    for kw, tier in todo:
        r = search(base, a.token, kw)
        r["tier"] = tier
        rows.append(r)
        if not a.json:
            if r.get("schema_error"):
                mark = "‼"
            elif r.get("error"):
                mark = "!"
            elif r.get("books"):
                mark = "✓"
            else:
                mark = "✗"
            print(f"  {mark} {kw:<10} 成书={r.get('books', 0):<2} "
                  f"可读本={r.get('readable_books', 0):<2} "
                  f"候选={r.get('candidates', r.get('items', 0)):<3} "
                  f"首本={r.get('top_title', '') or '-'}"
                  f"/{r.get('top_readable', 0)}可读"
                  f"/{r.get('top_chapters', 0)}章 "
                  f"耗时={r.get('elapsed')}s"
                  f"{(' ' + r['error']) if r.get('error') else ''}"
                  f"{(' ' + r['schema_error']) if r.get('schema_error') else ''}",
                  flush=True)
        time.sleep(max(0.0, a.gap))

    n = len(rows) or 1
    hit = sum(1 for r in rows if r.get("books"))
    readable = sum(1 for r in rows if r.get("readable_books"))
    slow = [r for r in rows if (r.get("elapsed") or 0) >= SLOW_S]
    bad = [r for r in rows if r.get("schema_error") or r.get("error")]
    report = {
        "base": base, "total": len(rows), "hit": hit, "readable": readable,
        "hit_rate": round(hit / n, 3), "readable_rate": round(readable / n, 3),
        "slow": [{"kw": r["kw"], "elapsed": r["elapsed"]} for r in slow],
        "bad": [{"kw": r["kw"], "why": r.get("schema_error") or r.get("error")} for r in bad],
        "rows": rows,
    }

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"\n命中 {hit}/{len(rows)} · 可读本 {readable}/{len(rows)} · "
              f"卡到 {SLOW_S:.0f}s 的 {len(slow)} 个 · 探针自己坏的 {len(bad)} 个")
        for r in slow:
            print(f"  慢：{r['kw']} {r['elapsed']}s")
        for r in bad:
            print(f"  坏：{r['kw']} {r.get('schema_error') or r.get('error')}")
        if hit < len(rows):
            miss = [r["kw"] for r in rows if not r.get("books")]
            print(f"  没搜到：{'、'.join(miss)}")

    # 探针自己坏掉 ≠ 产品坏掉，两种都要拦，但退出码分开方便自动化分辨。
    if bad:
        return 2
    if hit / n < a.min_hit:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
