#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
噜妹书院 · 拉线上日志
============================================================================
用户原话：「万一出现 bug，你可以直接去拉线上的 log、日志、埋点，
          可以快速定位问题。」

线上的结构化日志在 `~/noveldock/logs/app.log`（按天轮转，保留 14 天）。
这个脚本负责把它拿下来、按需过滤，不用手工 ssh + cat。

用法
----
    # 最近 100 行
    python tools/logs.py

    # 只看错误
    python tools/logs.py --level ERROR

    # 按事件名筛（这是结构化日志最大的好处）
    python tools/logs.py --event search.fail
    python tools/logs.py --event cache          # 前缀匹配：cache.start/done/fail
    python tools/logs.py --event export --lines 50

    # 只看某一次请求的全过程（req= 是短 id，从错误行里能直接看到）
    python tools/logs.py --req a3f9

    # 拉前一天的日志
    python tools/logs.py --day 2026-10-11

    # 看服务是不是还活着、上次重启在什么时候
    python tools/logs.py --status

    # 把日志存到本地（交给编辑器看）
    python tools/logs.py --save logs/pulled.log --lines 2000
============================================================================
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HOST = os.environ.get("NOVELDOCK_HOST", "106.53.203.108")
USER = os.environ.get("NOVELDOCK_USER", "ubuntu")
KEY = os.environ.get("NOVELDOCK_KEY", str(Path.home() / ".ssh" / "noveldock_ed25519"))
REMOTE_ROOT = f"/home/{USER}/noveldock"


def ssh(args: list[str], timeout: int = 60) -> tuple[int, str]:
    cmd = [
        "ssh", "-i", KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=15",
        "-o", "BatchMode=yes",
        f"{USER}@{HOST}", " ".join(args),
    ]
    env = dict(os.environ)
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        env.pop(k, None)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 1, f"超时（{timeout}s）—— 服务器没响应或网络不通"


def build_remote_cmd(a: argparse.Namespace) -> str:
    """拼一条远端 shell 命令。用 grep/awk 在**服务器上**过滤 ——
    拉全量再本地筛会浪费几十 MB 带宽，而且慢。"""
    f = f"{REMOTE_ROOT}/logs/app.log"
    if a.day:
        f = f"{REMOTE_ROOT}/logs/app.log.{a.day}"

    parts = [f'F={f}']
    parts.append('if [ ! -f "$F" ]; then echo "找不到日志文件：$F"; ls -1 '
                 f'{REMOTE_ROOT}/logs/ 2>/dev/null; exit 1; fi')

    # 过滤条件（顺序：先按 level/event/req 缩小，再取行数）
    conds = []
    if a.level:
        conds.append(f'grep -F "[{a.level.upper()}]"')
    if a.event:
        # 事件名在 req= 之后、冒号之前，grep 事件名本身即可
        # （不用更严的正则，否则 grep 到 "http.crash" 里含 "http" 的场景会误伤）
        conds.append(f'grep -F "{a.event}"')
    if a.req:
        conds.append(f'grep -F "req={a.req} "')

    if conds:
        parts.append('cat "$F" | ' + " | ".join(conds) + f' | tail -n {a.lines}')
    else:
        parts.append(f'tail -n {a.lines} "$F"')
    return "; ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description="拉噜妹书院的线上日志")
    ap.add_argument("--lines", type=int, default=100, help="取最后多少行（默认 100）")
    ap.add_argument("--level", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                    help="只看某个级别")
    ap.add_argument("--event", help="按事件名筛，如 search.fail / cache / export")
    ap.add_argument("--req", help="只看某一次请求（4 位短 id）")
    ap.add_argument("--day", help="看哪一天，格式 2026-10-11（默认今天）")
    ap.add_argument("--save", help="存到本地文件而不是打印")
    ap.add_argument("--status", action="store_true", help="看服务状态而不是日志")
    ap.add_argument("--list-events", action="store_true", help="列出全部事件名")
    a = ap.parse_args()

    if a.list_events:
        sys.path.insert(0, str(ROOT))
        from app.logging_setup import EVENTS
        print("可筛的事件名（--event 后面跟这些）：\n")
        for name, desc in sorted(EVENTS.items()):
            print(f"  {name:20s} {desc}")
        print("\n提示：--event 是**前缀/包含匹配**，所以 `--event cache` "
              "能把 cache.start / cache.done / cache.fail 一次全带出来。")
        return 0

    if a.status:
        rc, out = ssh([
            "systemctl --user is-active noveldock 2>/dev/null || echo 未运行",
            ";",
            "echo '--- 定时任务 ---'",
            ";",
            "systemctl --user list-timers --no-pager 2>/dev/null | head -5",
            ";",
            "echo '--- 日志文件 ---'",
            ";",
            f"ls -lh {REMOTE_ROOT}/logs/ 2>/dev/null | tail -6",
        ])
        print(out.strip())
        return rc

    # 先确认日志在哪（第一次跑时可能还没生成 —— 比如刚部署完还没人用过）
    cmd = build_remote_cmd(a)
    rc, out = ssh([cmd], timeout=90)
    if rc != 0:
        print(f"✗ 拉日志失败：\n{out.strip()}")
        return rc

    header = f"# {HOST} {REMOTE_ROOT}/logs/app.log"
    if a.day:
        header += f".{a.day}"
    if a.level:
        header += f"  level={a.level}"
    if a.event:
        header += f"  event={a.event}"
    if a.req:
        header += f"  req={a.req}"

    body = out.rstrip("\n")
    n = len(body.splitlines()) if body else 0

    if a.save:
        p = Path(a.save)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(header + "\n" + body + "\n", encoding="utf-8")
        print(f"✓ {n} 行 → {p}")
        return 0

    print(header)
    print(body if body else "（没有匹配的行）")
    print(f"\n（共 {n} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
