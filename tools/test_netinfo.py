"""局域网/防火墙检测的回归测试。

这里最容易错的不是「没找到规则」，而是**假信号**：

  - 把一条指向**别的** python.exe 的规则当成「已放行」→ 手机还是连不上
  - 把一条只对「专用网络」生效的规则当成放行 → 当前是公用网络，一样连不上
  - 把 netsh 的英文输出（`State  ON`）当成「防火墙关着」→ 反过来告诉用户
    「不用担心」，比不检测更糟

所以下面除了正向用例，还专门固化这几个反向用例。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import netinfo  # noqa: E402

CASES_PORT = [
    ("任何", 8000, True, "通配端口"),
    ("Any", 8000, True, "英文通配"),
    ("8000", 8000, True, "精确命中"),
    ("8000", 8001, False, "端口不同"),
    ("8000,8001,8080", 8080, True, "列表命中"),
    ("8000-8010", 8005, True, "区间内"),
    ("8000-8010", 8011, False, "区间外"),
    ("", 8000, False, "空值"),
    ("9000", 8000, False, "无关端口"),
]

CASES_PROFILE = [
    ("公用", "公用", True, "同为公用"),
    ("专用,公用", "公用", True, "多选含公用"),
    ("专用", "公用", False, "只对专用 —— 当前公用，不该算放行"),
    ("Public", "公用", True, "英文 Public 对应公用"),
    ("Public,Private", "公用", True, "英文多选含公用"),
    ("Private", "公用", False, "英文 Private 只对专用"),
    ("任何", "公用", True, "中文通配"),
    ("Any", "公用", True, "英文通配"),
    ("", "公用", True, "没写则视为不限"),
]

# netsh 中文模式下的字段
CASES_GRAB_CN = [
    ("本地端口:     \u3000                      任何", "port", "任何"),
    ("程序:                                 D:\\program files (x86)\\workbuddy\\vendor\\python.exe",
     "program", r"D:\program files (x86)\workbuddy\vendor\python.exe"),
    ("已启用:                               是", "enabled", "是"),
    ("操作:                                 允许", "action", "允许"),
]

# netsh 在 chcp 65001 下会切成英文 —— 实测出来的，必须能解析
CASES_GRAB_EN = [
    ("LocalPort:                            Any", "port", "Any"),
    ("Program:                              D:\\program files (x86)\\workbuddy\\vendor\\python.exe",
     "program", r"D:\program files (x86)\workbuddy\vendor\python.exe"),
    ("Enabled:                              Yes", "enabled", "Yes"),
    ("Action:                               Allow", "action", "Allow"),
    ("Profiles:                             Public", "profiles", "Public"),
]

CASES_PROFILE_HEAD = [
    ("域配置文件 设置:", "域"),
    ("专用配置文件 设置:", "专用"),
    ("公用配置文件 设置:", "公用"),
    ("状态                                  启用", ""),
    ("----------------------------------------------------------------------", ""),
    ("Domain Profile Settings:", "域"),
    ("Private Profile Settings:", "专用"),
    ("Public Profile Settings:", "公用"),
    ("State                                 ON", ""),
]

# 开关值：中英都要认。曾经只认「启用」，于是英文的 ON 被当成「关闭」
CASES_ON = [
    ("启用", True), ("是", True), ("ON", True), ("On", True), ("Yes", True),
    ("关闭", False), ("否", False), ("OFF", False), ("No", False),
]

# 端到端：一段真实的 netsh 英文输出，应能识别出「有一条放行 8000 的规则」
FAKE_EN_RULES = """
Rule Name:                            NovelDock 8000
----------------------------------------------------------------------
Enabled:                              Yes
Direction:                            In
Profiles:                             Private,Public
LocalIP:                              Any
RemoteIP:                             Any
Protocol:                             TCP
LocalPort:                            8000
RemotePort:                           Any
Program:                              Any
Action:                               Allow

Rule Name:                            Python
----------------------------------------------------------------------
Enabled:                              Yes
Direction:                            In
Profiles:                             Public
Protocol:                             TCP
LocalPort:                            Any
Program:                              D:\\program files (x86)\\workbuddy\\resources\\vendor\\python\\python.exe
Action:                               Allow
"""


def main() -> int:
    bad = 0

    def chk(ok: bool, note: str, extra: str = "") -> None:
        nonlocal bad
        bad += 0 if ok else 1
        print(f"  {'✓' if ok else '✗'} {note}{('  ' + extra) if extra and not ok else ''}")

    print("—— 端口匹配 ——")
    for spec, port, want, note in CASES_PORT:
        chk(netinfo._port_hit(spec, port) == want, note)

    print("—— 配置文件匹配（跨语言） ——")
    for spec, cur, want, note in CASES_PROFILE:
        chk(netinfo._profile_hit(spec, cur) == want, note)

    print("—— 字段解析：中文模式 ——")
    for line, key, want in CASES_GRAB_CN:
        got = netinfo._grab([line], key)
        chk(got == want, f"{key} → {got!r}")

    print("—— 字段解析：英文模式（chcp 65001 下 netsh 会切英文） ——")
    for line, key, want in CASES_GRAB_EN:
        got = netinfo._grab([line], key)
        chk(got == want, f"{key} → {got!r}")

    print("—— 配置文件标题行 ——")
    for line, want in CASES_PROFILE_HEAD:
        got = netinfo._profile_of(line)
        chk(got == want, f"{line[:26]!r} → {got!r}")

    print("—— 开关值（英文 ON 不能当成关闭） ——")
    for val, want in CASES_ON:
        chk(netinfo._is_on(val) == want, f"{val!r} → {netinfo._is_on(val)}")

    print("—— 端到端：解析一段英文 netsh 输出 ——")
    rules = netinfo._split_rules(FAKE_EN_RULES)
    chk(len(rules) == 2, f"应解析出 2 条规则，实际 {len(rules)}")
    hit = None
    for r in rules:
        if not netinfo._is_allow(r["action"]) or not netinfo._is_on(r["enabled"]):
            continue
        if not netinfo._profile_hit(r["profiles"], "公用"):
            continue
        if r["protocol"] != "TCP" or not netinfo._port_hit(r["port"], 8000):
            continue
        if r["program"] and not netinfo._is_any(r["program"]):
            continue
        hit = r["name"]
        break
    chk(hit == "NovelDock 8000", f"应认出放行规则，实际 {hit!r}")

    # 反向：那条绑定到别的 python.exe 的规则**不能**算数
    other = [r for r in rules if r["name"] == "Python"][0]
    prog_blocks = (other["program"] and not netinfo._is_any(other["program"])
                   and other["program"].lower() != r"C:\proj\.venv\Scripts\python.exe".lower())
    chk(prog_blocks, "指向别的 python.exe 的规则必须被排除")

    print("✅ 全部通过" if not bad else f"❌ {bad} 项失败")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
