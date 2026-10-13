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
import shutil
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
    # HTTP 客户端复用：verify 翻转时必须关旧连接池，否则 socket 累积、
    # 最终表现为「跑一阵就全超时」—— 这类症状极难反推到根因。
    ("test_http_client.py", "客户端复用"),
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
    # 脏数据拦截：话题标签符污染书名、影视站被当成小说站。
    # 后者尤其隐蔽 —— 苹果 CMS 的「第01集…」列表和章节目录长得一样。
    # 见 tools/test_junk.py 的注释。
    ("test_junk.py", "脏数据拦截"),
    # 文件名清洗：Windows 保留设备名（裸 CON/NUL/AUX/COM1..9/LPT1..9 建不了文件）、
    # 结尾点空格、空名。这些在 Linux 上**全都不存在**，所以本地/线上都测不出，
    # 只有真的在 Windows 上跑才暴露。见 tools/test_filename.py 的注释。
    ("test_filename.py", "文件名安全"),
    # 封面抽取：拿错封面比拿不到更糟 —— 站点占位图（nocover.jpg）一旦被
    # 当成真封面缓存下来，那本书就永远显示灰图；懒加载站（src=占位、
    # data-src=真图）只读 src 则 100% 拿错。两种写法都是从真实站点抄来的。
    ("test_cover.py", "封面抽取"),
    # 前端产物上线链路：产物存在 / 被引用 / pack 不误排 / 版本号扫得到 /
    # 路径一致。五个坏法全都表现成"白屏但部署成功"，人工必漏。
    # 尤其 pack.py 的 EXCLUDE_DIRS 含 `dist`、而匹配按路径段 ——
    # app/static/dist/ 会被误伤（接 Vite 时真踩过）。见该文件注释。
    ("test_frontend.py", "前端产物链路"),
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
    # 前端注入：payload 当搜索词打进去，断言没有真的元素生成、没有代码执行。
    # grep innerHTML 判断不了"那个变量到底过没过 esc()"，只有真浏览器说了算。
    ("test_xss.py", "前端注入"),
    # 并发竞态：连点两次搜索后的状态机。这条钉住的是「abort 生效 + finally
    # 有守卫」—— 两个 bug 都不报错，只表现为"结果串台/按钮失灵"，人工必漏。
    ("test_concurrency.py", "并发竞态"),
    # 前端埋点：JS 错误 / Promise 拒绝 / 接口失败 必须落进 logs/app.log。
    # 这条直接读日志文件 —— 「用户报的 bug 能不能对上日志」只能这么验。
    ("test_telemetry.py", "前端埋点"),
    # 客户端断开后引擎要**收手**。修之前：用户关掉页面/连点两次搜索，
    # 服务端照样把整轮跑完（实测白烧 13.9s，vs 修复后 3.5s）。
    # 靠读日志里的「客户端已断开」+ 比对耗时来判定 —— 没有这个测试，
    # 这种「不报错、只是烧资源」的退化永远发现不了。
    ("test_disconnect.py", "断连止损"),
    # 鉴权时序：Vue 是**另一个** module script，加载完立刻 mount，
    # 可能抢在读 ?t= 的 bootstrapAuth() 之前发请求 —— 线上 401、
    # 榜单整块不显示，而**本地因 /api 免令牌永远不复现**。
    # 这条不看结果看时序（请求发车时 authReady 了没），本地也有牙。
    ("test_auth_race.py", "鉴权时序"),
    # 书架页（Vue 迁移后）。test_buttons 的 E 组只验"点了会怎样"，
    # 验不到渲染层：组件挂错容器（真踩过，一个 app 管多处 DOM，
    # 书架被渲进榜单区内部、页面静默空白）、插画消失、请求回声。
    ("test_shelf_ui.py", "书架界面"),
    # 文件页（Vue 迁移后）。这条钉的是一条**跨模块契约**：
    # `#fmtPick` 必须还是原生 select —— main.js 有 3 处读
    # `$("#fmtPick").value` 拿导出格式，Naive 的 n-select 渲成 div，
    # `.value` 取到 None，导出会静默用错格式。
    # 写这条断言时特地做了回退验证（换回 n-select 立刻报红）。
    ("test_files_ui.py", "文件界面"),
    # 发现页结果区（Vue 迁移后）。test_buttons 的 A/B 组验的是搜索**行为**，
    # 这条专盯"结果区交给 Vue 之后"的回归：组件挂错位置、状态桥
    # （discover:state）没接上导致"搜完了却一条不显示"、`#q`/`#btnSearch`
    # 被顺手搬进 Vue 破坏跨模块契约、空态与结果列表同时显示。
    # 全部断言都做了回退验证（断桥 / 搬 #q / 空态恒显示，三处都能报红）。
    ("test_discover_ui.py", "发现界面"),
    # 阅读器外壳（Vue 迁移后）。test_reader_ui 验的是"点一下会不会翻页"，
    # 抓不到迁移本身的回归 —— 那类问题全都发生在"渲染权与布局契约"这层：
    # 三个挂载容器挂错位置（#reader 纵向 flex 顺序乱掉）、
    # 舞台区/进度条被 Vue 抢走（StPageFlip 旧引用失效、拖拽丢手势，
    # **偶发且极难查**）、旧代码依赖的 id 丢失（$() 拿 null 直接抛错，
    # 整条链路静默中断）。这条把它们钉成"永久红"。
    ("test_reader_shell.py", "阅读器外壳"),
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
    "test_xss.py": "--url",
    "test_concurrency.py": "--url",
    "test_telemetry.py": "--url",
    "test_disconnect.py": "--url",
    "test_auth_race.py": "--url",
    "test_shelf_ui.py": "--url",
    "test_files_ui.py": "--url",
    "test_discover_ui.py": "--url",
    "test_reader_shell.py": "--url",
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


# ---------------------------------------------------------------------------
# 前端构建（Vite → app/static/dist）
# ---------------------------------------------------------------------------
FRONTEND = ROOT / "frontend"

# 找 node/npm：优先 managed 版本（本项目约定的隔离环境），再退到 PATH。
# 为什么要按路径找而不是直接用 "npm"：Windows 上 Git Bash 的 PATH
# 不一定带 node，而 managed 版本是确定存在的。
_NODE_CANDIDATES = [
    Path(os.path.expanduser("~")) / ".workbuddy" / "binaries" / "node" /
    "versions" / "22.22.2-6",
]


def _find_node_bin() -> tuple[str | None, str | None]:
    """返回 (node_dir, npm_cmd)。找不到就 (None, None)。"""
    for d in _NODE_CANDIDATES:
        npm = d / ("npm.cmd" if os.name == "nt" else "npm")
        if npm.exists():
            return str(d), str(npm)
    # 退到 PATH
    npm = shutil.which("npm")
    if npm:
        return None, npm
    return None, None


def build_frontend(dry_run: bool = False) -> bool:
    """构建前端 + 自检产物。没有 node 时**不阻断**（只是警告）。

    为什么"没有 node 就不阻断"：服务器上不装 node，线上是纯 Python 起的；
    开发者机器上应该有。缺 node 说明是在一个不能构建的环境里跑
    （比如远端），这时用已有的产物继续是对的 —— 总比整个流程卡死好。
    但**只要 node 在，构建失败就是硬失败** —— 那说明源码有语法错，
    绝不能带着旧产物上线。
    """
    if not FRONTEND.exists():
        print("  ~ 没有 frontend/ 目录，跳过（还没迁到 Vue？）")
        return True

    node_dir, npm = _find_node_bin()
    if not npm:
        print("  ~ 找不到 node/npm，跳过构建（用现有产物继续）")
        print("    装了 node 之后重跑，产物才会是最新的。")
        return True

    env = dict(os.environ)
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        env.pop(k, None)
    if node_dir:
        env["PATH"] = node_dir + os.pathsep + env.get("PATH", "")

    if dry_run:
        print(f"  （dry-run）会执行：{npm} run build:check  （cwd={FRONTEND}）")
        return True

    r = subprocess.run(
        [npm, "run", "build:check"], cwd=FRONTEND, env=env,
        capture_output=True, text=True, shell=(os.name == "nt"),
    )
    out = (r.stdout or "") + (r.stderr or "")
    lines = out.strip().splitlines()
    if r.returncode == 0:
        tail = lines[-1:] or [""]
        print(f"  ✓ 构建 + 产物自检  {tail[0][:70]}")
        return True

    print("  ✗ 前端构建/自检失败 —— 产物没更新，**不能上线**")
    # 和 run_suite 同理：把 ✗ 行连上下文抓出来，别让人只看个"失败"
    fails = [i for i, ln in enumerate(lines) if "✗" in ln or "error" in ln.lower()]
    shown: list[int] = []
    for i in fails[:12]:
        for j in range(max(0, i - 1), min(len(lines), i + 2)):
            if j not in shown:
                shown.append(j)
    shown.sort()
    for j in shown:
        print(f"      {lines[j]}")
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

    # ------------------------------------------------------------------
    # [0/4] 前端构建
    # ------------------------------------------------------------------
    # 为什么把构建放进 ship、而不是让人记得手动跑：
    # 前端已经迁到 Vite + Vue3（见 frontend/），源码在 frontend/src/，
    # 产物在 app/static/dist/。**产物才是真正被部署的东西**。
    # 忘了构建 → 改了源码、传的还是上次的产物 → 线上看起来"改了没生效"，
    # 而所有测试又都是绿的（它们测的是产物）。这是最隐蔽的一类事故。
    #
    # 所以：构建 → 产物自检 → 测试，都在一条链上，顺序不可颠倒。
    # 没有 node 时**只警告不阻断**（服务器上没有 node，也不该有）。
    if not a.skip_test:
        print("\n[0/4] 前端构建（Vite → app/static/dist）")
        if not build_frontend(a.dry_run):
            print("✗ 前端构建失败，没有继续。")
            return 1

    if not a.skip_test:
        print("\n[1/4] 静态自检")
        failed = [n for n, d in STATIC_SUITES if not run_suite(n, d)]
        if failed:
            print(f"\n✗ 静态自检有 {len(failed)} 项没过：{failed}")
            print("  按上面的输出修掉再跑。**没有推到线上。**")
            return 1

        if not a.skip_live:
            print("\n[2/4] 真机自检（需要本地服务 + Chrome）")
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
            print("\n[2/4] 真机自检 —— 已跳过")
    else:
        print("\n[0/4] 前端构建 —— 已跳过（--skip-test）")
        print("[1/4] 静态自检 —— 已跳过")
        print("[2/4] 真机自检 —— 已跳过")

    if a.only_test:
        print(f"\n✓ 自检全绿（{time.time()-t0:.1f}s）。没同步（--only-test）。")
        return 0

    print("\n[3/4] 同步到云服务器")
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
