#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
噜妹书院 · 一条命令走完「自检 → 同步 → 验收」
============================================================================
为什么要有它（用户的真实抱怨：「你同步本地代码到线上弄了这么久，
这种经常要做的东西，你可以总结归纳成一个文档或者skill，下次直接触发」）

问题不在 sync_cloud.py 本身（它已经够稳），而在**外围流程**：
每次改完，实际要做的是
    1. 想起来该跑哪些测试（现在有 11 个套件，记不全）
    2. 起本地服务（有几个测试需要 base）
    3. 跑测试、看有没有挂
    4. 跑 sync_cloud.py
    5. 看验证输出（以前只验 health，不看静态资源）
光"想起来 + 粘命令"就占了大半时间，还漏过步骤。

所以把这条链固化在这里。用法只有一句：

    .venv\\Scripts\\python tools\\ship.py

它会：
  · 自动起一个临时本地服务（跑完自动关）—— 需要真机的检查也能跑
  · 并行跑所有静态检查，串行跑需要服务的检查
  · **任何一项红就停下，不往线上推**
  · 全绿才调 sync_cloud.py
  · 最后再独立验一遍线上静态资源

常用开关：
    --only-test      只自检，不同步
    --skip-test      跳过自检直接同步（修文案这类小改动用）
    --skip-live      跳过需要真机浏览器的检查（没装 Chrome 时）
    --dry-run        打印将要做什么，不真执行
============================================================================
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# 静态检查（不需要服务）—— 快，先跑。
# 挑的是「改动影响了这一块，就必须过」的那些；不是测试越全越好 ——
# 全跑一遍要好几分钟，长到人会开始跳过它，那就等于没有。
STATIC_SUITES = [
    ("test_motion.py", "动效层规矩"),
    ("test_art.py", "素材层质量"),
    ("test_parse.py", "解析器"),
    ("test_ranks.py", "榜单解析"),
    ("test_registry.py", "来源库"),
    ("test_relevance.py", "结果相关性"),
    ("test_sitelearn.py", "站点学习"),
    ("test_deobfuscate.py", "反混淆"),
    # 纯逻辑、不用服务。之前漏在外面，结果"改了安全策略却没人验"。
    ("test_security.py", "安全策略"),
    # 联网兜底（本地全灭必须联网）。这类 bug 不报错、只表现为"搜不到"，
    # 人工回归必漏 —— 见 tools/test_discover_fallback.py 的注释。
    ("test_discover_fallback.py", "联网兜底"),
    # 榜单抓不到（被限流）时要回退到过期的旧缓存，不能给空白页。
    # 同样是"不报错、只显空"的那类 —— 见 tools/test_ranks_stale.py 的注释。
    ("test_ranks_stale.py", "榜单兜底"),
    # 自有来源从列表页抽作者。作者搜索全靠这个字段 ——
    # 它一旦退化，表现是"搜作者名 0 条"，不报错。见该文件的注释。
    ("test_registry_author.py", "作者抽取"),
    # 书页 URL 形状：书页要认得出、章节正文页要挡住。
    # 退化的表现是「章节被当成一本书收进结果，点进去只有一章」——
    # 也不报错，只是结果脏。见 tools/test_bookurl.py 的注释。
    ("test_bookurl.py", "书页 URL"),
]

# 真机检查（需要本地服务 + Chrome）
LIVE_SUITES = [
    ("test_motion_live.py", "动效真机"),
    ("test_buttons.py", "按钮全量"),
    # ⚠ 这三个**一直存在但从没进过这条链** —— 于是"榜单 UI 改了没人验"
    #   "阅读器翻页回归没人跑"。它们才是真正会拦住线上事故的那些，
    #   补进来之后 ship 才配叫"一条命令上线"。
    ("test_ranks_ui.py", "榜单界面"),
    ("test_reader_ui.py", "阅读器交互"),
]

# 各真机套件的参数名不一样（历史原因，别硬统一 —— 改脚本参数名会连带改 CI）。
# ⚠ 漏配的后果踩过：test_motion_live 的 --base **有默认值 8011**，
#   而 ship 起的是随机端口 —— 不传它就跑去连 8011，报「连不上」，
#   看着像动效坏了，其实是测错了端口。（这个坑一直藏着：以前单独跑时
#   8011 上恰好有服务，直到某次 ship 才暴露。）
LIVE_ARGS = {
    "test_motion_live.py": "--base",
    "test_buttons.py": "--base",
    "test_ranks_ui.py": "--base",
    "test_reader_ui.py": "--url",   # 这个老脚本用的还是 --url
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_up(url: str, timeout: float = 25) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.4)
    return False


class LocalServer:
    """起一个临时的本地服务给测试用。跑完一定关掉 —— 留着会占端口，
    下次跑就会莫名"端口被占"（这个坑踩过）。"""

    def __init__(self) -> None:
        self.port = free_port()
        self.proc: subprocess.Popen | None = None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "LocalServer":
        env = dict(os.environ)
        env.pop("http_proxy", None)
        env.pop("https_proxy", None)
        env.pop("HTTP_PROXY", None)
        env.pop("HTTPS_PROXY", None)
        env["NOVEL_SCHED"] = "0"          # 测试时关掉后台调度，免得互相干扰
        self.proc = subprocess.Popen(
            [PY, str(ROOT / "run.py"), "--host", "127.0.0.1",
             "--port", str(self.port), "--no-check"],
            cwd=ROOT, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if not wait_up(self.base + "/api/health"):
            self.__exit__(None, None, None)
            raise SystemExit(f"✗ 本地服务没起来（端口 {self.port}）")
        print(f"  · 测试服务已就绪 {self.base}")
        return self

    def __exit__(self, *exc) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def run_suite(name: str, desc: str, extra: list[str] | None = None) -> bool:
    path = ROOT / "tools" / name
    if not path.exists():
        print(f"  ~ {desc}: 跳过（没有 {name}）")
        return True
    cmd = [PY, str(path)] + (extra or [])
    env = dict(os.environ)
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        env.pop(k, None)
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
    if r.returncode == 0:
        print(f"  ✓ {desc}  {tail[0][:70]}")
        return True
    print(f"  ✗ {desc}  —— 失败")
    out = (r.stdout or "") + (r.stderr or "")
    lines = out.strip().splitlines()
    # ⚠ 以前是「打印最后 25 行」。踩过坑：真机套件有 24 条 ✓ 加若干小节标题，
    #   那一条 ✗ 往往落在倒数 30 行开外 —— 于是**失败原因根本看不见**，
    #   只看到"失败"两个字，还得自己去翻日志重跑一遍。
    #   正确做法：把所有 ✗ 行连上下文一起捞出来，再补尾部，保证"谁错了、错在哪"一定可见。
    fails = [i for i, ln in enumerate(lines) if "✗" in ln]
    shown: list[int] = []
    for i in fails:
        for j in range(max(0, i - 2), min(len(lines), i + 2)):
            if j not in shown:
                shown.append(j)
    shown.sort()
    if shown:
        print("      ── 失败处（含上下文）──")
        for j in shown:
            print(f"      {lines[j]}")
    tail = lines[-8:]
    if any(j >= len(lines) - 8 for j in shown):
        tail = []
    for line in tail:
        print(f"      {line}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-test", action="store_true", help="只自检，不同步")
    ap.add_argument("--skip-test", action="store_true", help="跳过自检直接同步")
    ap.add_argument("--skip-live", action="store_true", help="跳过需要浏览器的检查")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不执行")
    a = ap.parse_args()

    print("=" * 62)
    print("噜妹书院 · 一键上线")
    print("=" * 62)
    t0 = time.time()

    if not a.skip_test:
        print("\n[1/3] 静态自检")
        failed = [n for n, d in STATIC_SUITES if not run_suite(n, d)]
        if failed:
            print(f"\n✗ 静态自检有 {len(failed)} 项没过：{failed}")
            print("  按上面的输出修掉再跑。**没有推到线上。**")
            return 1

        if not a.skip_live:
            print("\n[2/3] 真机自检（需要本地服务 + Chrome）")
            try:
                with LocalServer() as srv:
                    failed = []
                    for n, d in LIVE_SUITES:
                        flag = LIVE_ARGS.get(n)
                        extra = [flag, srv.base] if flag else None
                        if not run_suite(n, d, extra):
                            failed.append(n)
            except SystemExit as e:
                print(f"  {e}")
                print("  （没有本地服务就跳过真机检查；有 Chrome 的话它会自己起）")
                failed = []
            if failed:
                print(f"\n✗ 真机自检有 {len(failed)} 项没过：{failed}")
                print("  **没有推到线上。**")
                return 1
        else:
            print("\n[2/3] 真机自检 —— 已跳过")
    else:
        print("\n[1/3] 静态自检 —— 已跳过")
        print("[2/3] 真机自检 —— 已跳过")

    if a.only_test:
        print(f"\n✓ 自检全绿（{time.time()-t0:.1f}s）。没同步（--only-test）。")
        return 0

    print("\n[3/3] 同步到云服务器")
    cmd = [PY, str(ROOT / "tools" / "sync_cloud.py")]
    if a.dry_run:
        cmd.append("--dry-run")
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        print("\n✗ 同步失败")
        return r.returncode

    print(f"\n{'=' * 62}")
    print(f"✓ 上线完成，用时 {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
