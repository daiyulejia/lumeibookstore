"""深夜体检：趁没人用的时候，把来源库刷一遍。

用户原话：「L 源你也可以定期进行排查，比如半夜的时候，凌晨三四点，
都睡了你去排查，那些是 OK 的，这样不会说有些已经坏了，下次搜到时候还去查。」

它干三件事，按成本从低到高：

  1. **体检**（`/api/registry/check`）—— 把库里记的书重开一遍，
     看目录还在不在。死掉的书和站自动清掉。
  2. **学搜索接口**（`/api/registry/learn`）—— 给「还没学过搜索模板」
     的站补课，让它们变成可搜源。这是 L 源**自我升级**的一步。
  3. **报告** —— 把体检前后的数字打出来（站 / 书 / 可搜源），
     进 journal 便于事后回溯。

为什么不直接 `python -c "from app import discovery; ..."`：
和 `ranks_cron.py` 同一个道理 —— **服务在跑，它的内存里有一份来源库缓存**。
另起一个进程去体检、清库，写的是同一个 `cache/registry.json`，
但跑着的服务内存里还是旧的，用户界面上看不到变化，等于白干一轮。
所以走接口，让**服务本体**去做。

另外，走接口还能复用服务里的限速器 / 连接池 / 页面缓存，
不会和线上的用户请求抢出两条独立的连接。

用法：
  python tools/registry_nightly.py                  # 体检 + 学接口
  python tools/registry_nightly.py --check-only
  python tools/registry_nightly.py --learn-only --learn-limit 20
  python tools/registry_nightly.py --port 8000 --quiet

退出码：0 成功；1 有步骤失败；2 服务没在跑（定时任务里算「跳过」）。
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
    """从服务那份 auth.json 取令牌（本机回环其实不需要，带上更保险）。"""
    for p in (ROOT / "cache" / "auth.json",):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            t = d.get("token") or d.get("access_token") or ""
            if t:
                return str(t)
        except Exception:  # noqa: BLE001
            pass
    return ""


def _post(url: str, tok: str, *, timeout: float = 600.0) -> dict:
    if tok:
        url += ("&" if "?" in url else "?") + f"t={tok}"
    req = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _get(url: str, tok: str, *, timeout: float = 600.0) -> dict:
    if tok:
        url += ("&" if "?" in url else "?") + f"t={tok}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main() -> int:
    ap = argparse.ArgumentParser(description="来源库深夜体检 + 学搜索接口")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--check-only", action="store_true", help="只体检，不学接口")
    ap.add_argument("--learn-only", action="store_true", help="只学接口，不体检")
    ap.add_argument("--learn-limit", type=int, default=0, help="一次最多学几个站")
    ap.add_argument("--check-limit", type=int, default=0, help="一次最多体检几本书")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    tok = read_token()
    base = f"http://{a.host}:{a.port}"

    # 先看一眼现状（服务连不上就早退，免得后面每一步都报同一个错）
    try:
        before = _get(f"{base}/api/registry", tok, timeout=30)
    except Exception as e:  # noqa: BLE001
        print(f"[来源库体检] 连不上服务（{a.host}:{a.port}）：{e}", flush=True)
        return 2

    st0 = before.get("stats") or {}
    if not a.quiet:
        print(f"[来源库体检] 开始 —— 站 {st0.get('sites')}（可搜 {st0.get('sites_searchable')}）"
              f" / 书 {st0.get('books')}", flush=True)

    failed = 0

    # ---- 1) 体检 ----
    if not a.learn_only:
        try:
            q = f"?limit={a.check_limit}" if a.check_limit else ""
            rep = _get(f"{base}/api/registry/check{q}", tok)
            print(f"[来源库体检] 完成 —— 查了 {rep.get('checked')} 本，"
                  f"存活 {rep.get('ok')} · 失效 {rep.get('dead')}，"
                  f"清理 {rep.get('books_removed')} 本 / {rep.get('sites_removed')} 站",
                  flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[来源库体检] 体检失败：{e}", flush=True)
            failed += 1

    # ---- 2) 学搜索接口 ----
    if not a.check_only:
        try:
            q = f"?limit={a.learn_limit}" if a.learn_limit else ""
            rep = _post(f"{base}/api/registry/learn{q}", tok)
            # ⚠ `pending` 必须打出来：撞时间预算收手时，没跑完的站既不算
            #   成功也不算失败。不显示的话，日志上看着像"这批都学完了，
            #   只是没学会"，实际上还欠着一批 —— 下一轮也不会有人知道要补。
            pending = int(rep.get("pending") or 0)
            print(f"[来源库体检] 学接口完成 —— 新学会 {rep.get('learned')} 个站"
                  f"（失败 {rep.get('failed')} / 跳过 {rep.get('skipped')}"
                  + (f" / **没跑完 {pending}**" if pending else "") + "），"
                  f"现在共有 {rep.get('searchable')} 个可搜源", flush=True)
            if pending:
                print(f"[来源库体检] 还有 {pending} 个站没来得及学，"
                      f"下一轮（或手动 POST /api/registry/learn）会继续", flush=True)
            # ⚠ 复核那一段原来**一个字都不打**。它是"撤掉假可搜源"的唯一入口
            #   （旧版学习器学出来的模板不认关键词，照常吐首页），撤掉几家、
            #   几家没结论、有没有跑完 —— 全在返回值的 `reverify` 里，
            #   而这里从来没读过它。等于每晚做了一趟没人知道结果的工作。
            rev = rep.get("reverify") or {}
            if rev:
                rpend = int(rev.get("pending") or 0)
                print(f"[来源库体检] 复核模板完成 —— 查了 {rev.get('checked')}"
                      f"（只能靠通用书名的 {rev.get('canary_only')}）"
                      f" / 撤掉 {rev.get('dropped')} 个假可搜源"
                      f" / 留下 {rev.get('kept')} / 没结论 {rev.get('unjudged')}"
                      + (f" / **没跑完 {rpend}**" if rpend else ""), flush=True)
                if rpend:
                    print(f"[来源库体检] 还有 {rpend} 个站的模板没复核，"
                          f"下一轮会继续", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[来源库体检] 学接口失败：{e}", flush=True)
            failed += 1

    # ---- 3) 收尾报告 ----
    try:
        after = _get(f"{base}/api/registry", tok, timeout=30)
        st1 = after.get("stats") or {}
        print(f"[来源库体检] 结果 —— 站 {st0.get('sites')}→{st1.get('sites')}"
              f"（可搜 {st0.get('sites_searchable')}→{st1.get('sites_searchable')}）"
              f" / 书 {st0.get('books')}→{st1.get('books')}", flush=True)
    except Exception:  # noqa: BLE001
        pass

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
