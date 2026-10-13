"""Chrome 启动器纪律 —— 静态回归（不需要真机，秒级）。

为什么要有一条**静态**测试来管这件事：

  曾经的真机随机假红（ship 里 14 套串行跑时，位置和症状每次都不同：
  一次是「DOM 里等不到榜单条目」，下次是 ConnectionResetError/WinError 10054），
  根因是 Chrome 启动的写法：`free_port()` 挑端口 + `wait_devtools()` 只判断
  「端口能不能回话」，**不判断回话的是不是自己刚起的那个实例**。
  旧实例还没退干净时，新 Chrome 会连上它，等它一死连接就被 reset。

  修法是 `tools/shot.py` 的 `launch_chrome()`（Chrome 自动分配端口 +
  `DevToolsActivePort` 实例 UUID 校验 + 启动前删旧文件）。
  但光修一次不够 —— 谁下次随手 `--remote-debugging-port=9344` 写回去，
  这个坑就又回来了，而且**只在 ship 里偶发**，极难察觉。

  所以这里把「纪律」钉成断言：凡是自己起 Chrome 的真机工具，
  **不许硬编码调试端口**，**必须走 launch_chrome**。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
SHOT = TOOLS / "shot.py"

# 这些工具会自己起 Chrome。**新增真机工具时往这里加**。
# ⚠ 登记前先确认它真的用浏览器：test_disconnect 名字像真机，
#   其实是靠 HTTP 模拟「客户端断开」，**根本不起 Chrome** ——
#   早先把它登进来，导致纪律测试报了一个假违规。
BROWSER_TOOLS = [
    "test_buttons.py",
    "test_ranks_ui.py",
    "test_reader_ui.py",
    "test_motion_live.py",
    "test_xss.py",
    "test_concurrency.py",
    "test_auth_race.py",
    "test_telemetry.py",
    "test_shelf_ui.py",
    "test_files_ui.py",
    "test_discover_ui.py",
    "test_reader_shell.py",
]

OK = 0
FAIL = 0


def check(cond: bool, label: str, detail: str = "") -> None:
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {label}")
    else:
        FAIL += 1
        print(f"  ✗ {label}   {detail}")


def read(name: str) -> str:
    p = TOOLS / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def main() -> int:
    print("=" * 62)
    print("Chrome 启动器纪律（静态）")
    print("=" * 62)

    shot = read("shot.py")

    print("\n── 1. shot.py 提供公共启动器 ──")
    check("def launch_chrome(" in shot, "有 launch_chrome()")
    check("--remote-debugging-port=0" in shot,
          "用 port=0（让 Chrome 自己分配，无抢端口竞态）")
    check("DevToolsActivePort" in shot, "从 DevToolsActivePort 读回真实端口")
    check("def page_ws(" in shot,
          "有 page_ws()（Page.*/Runtime.* 只挂在页面 target 上）")

    print("\n── 2. 反证过的关键修复：启动前删旧 DevToolsActivePort ──")
    # 反证实测：profile 里若预写了指向旧实例的文件，不删就会误判身份。
    # 这里用「删除语句出现在 Popen 之前」来表达这条纪律。
    i_remove = shot.find("os.remove(port_file)")
    i_popen = shot.find("proc = subprocess.Popen(args")
    check(i_remove != -1, "确实删了 port_file")
    check(i_remove != -1 and i_popen != -1 and i_remove < i_popen,
          "删除发生在启动 Chrome **之前**",
          f"(remove@{i_remove}, popen@{i_popen})")

    print("\n── 3. 身份校验：必须比对 UUID，不只是「端口能回话」 ──")
    check("browser_ws" in shot, "构造了带 UUID 的 browser_ws")
    check(re.search(r'got\.rstrip\("/"\)\s*==\s*browser_ws\.rstrip\("/"\)', shot)
          is not None, "校验 /json/version 返回的 ws 与自己的**完全相等**")

    print("\n── 4. 各真机工具：不许硬编码调试端口 ──")
    # 硬编码的写法长这样：--remote-debugging-port=9344 / =1240
    hard = re.compile(r"--remote-debugging-port=(\d+)")
    for name in BROWSER_TOOLS:
        src = read(name)
        if not src:
            check(False, f"{name} 存在", "文件不见了")
            continue
        hits = [m for m in hard.findall(src) if m != "0"]
        check(not hits,
              f"{name} 没有硬编码调试端口",
              f"发现 {hits}（应改成 launch_chrome）")

    print("\n── 5. 各真机工具：必须走公共启动器（或复用它封装好的 Browser） ──")
    # 两种「合规」写法：
    #   a) 直接 from shot import launch_chrome
    #   b) from test_auth_race import Browser —— Browser 内部已走 launch_chrome，
    #      又被 shelf_ui / files_ui / discover_ui / reader_shell 等复用。
    # 两种都行；只有「自己 subprocess.Popen 起 Chrome」才算违规。
    for name in BROWSER_TOOLS:
        src = read(name)
        if not src:
            continue
        direct = "launch_chrome" in src
        via_browser = bool(re.search(r"import\s+Browser|Browser\s*\(", src))
        check(direct or via_browser,
              f"{name} 走公共启动器（直接或经 Browser）",
              "自己 Popen 起 Chrome 会重新引入竞态" if not (direct or via_browser) else "")

    print("\n" + "=" * 62)
    print(f"通过 {OK} · 失败 {FAIL}")
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
