"""埋点事件名登记表 ↔ 实际代码 的一致性回归。

为什么要这个测试
----------------
`app/logging_setup.py` 里的 `EVENTS` 表是"口径统一"的锚：新人照它找事件、
线上排障时照着它 grep。但这张表**天生会漂移**，而且漂移的方式极其阴险：

  ① **登记了却没人发（死条目）**
     它比"压根没登记"更坏 —— 你在日志里 grep 不到，第一反应是
     "这条链路没触发"，于是去查业务逻辑；实际是**根本没埋**。
     排查时间就这么烧掉了。本轮实测就抓到 11 个这种死条目。

  ② **发了却没登记（口径漂移）**
     新同学照着表找 `source.fail`，表里没有；其实代码里发得挺勤。

两种漂移都是**静默的**：不报错、不崩溃、测试全绿 ——
直到某天线上出事、你去拉日志，才发现表是骗人的。

所以这里做双向校验，并且**把"计划中"单列一段**：
"计划中"的事件必须**确实还没人发**（否则说明功能落地了，
条目该从计划段搬到已发段），这样表的每一行都有明确含义。

用法： python tools/test_events_registry.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
OK = 0
BAD = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global OK, BAD
    if cond:
        OK += 1
        print(f"  ✓ {name}")
    else:
        BAD += 1
        print(f"  ✗ {name}  {extra}")


def parse_registry() -> dict[str, str]:
    """从 logging_setup.py 抠出 EVENTS 字典（名字 → 说明）。"""
    src = (APP / "logging_setup.py").read_text(encoding="utf-8")
    block = src.split("EVENTS = {", 1)[1].split("\n}", 1)[0]
    return dict(re.findall(r'"([a-z_.]+)":\s*"([^"]*)"', block))


def scan_fired() -> set[str]:
    """扫出后端**真正调用**的所有 log_event 事件名。

    注意三种写法都要覆盖（漏一种就会假红/假绿）：
      · log_event(log, "name", ...)          —— 常规
      · log_event(log, "name", lv, ...)      —— 带日志级别
      · log_event(log, f"name.{x}", ...)     —— 变量拼名（本仓库暂无，
                                                扫不到时靠人肉 grep 兜底）
    所以这里统一用「逗号后紧跟字符串字面量」的模式，不数参数个数。
    """
    pat = re.compile(r'log_event\(\s*[A-Za-z_][\w.,\s]*?,\s*"([a-z_.]+)"')
    fired: set[str] = set()
    for p in APP.rglob("*.py"):
        if p.name == "logging_setup.py":
            continue
        fired |= set(pat.findall(p.read_text(encoding="utf-8")))
    return fired


def scan_front() -> set[str]:
    """扫出前端 telemetry.js 回传的事件名。"""
    js = (APP / "static/js/telemetry.js").read_text(encoding="utf-8")
    return set(re.findall(r'event:\s*"([a-z_.]+)"', js)) | \
        set(re.findall(r'"(ui\.[a-z_.]+)"', js))


def main() -> int:
    print("=" * 62)
    print("埋点事件名登记表 ↔ 实际代码 一致性")
    print("=" * 62)

    reg = parse_registry()
    fired = scan_fired()
    front = scan_front()

    # 「计划中」= 说明里带 [计划] 标记
    planned = {k for k, v in reg.items() if v.startswith("[计划]")}
    live_reg = set(reg) - planned
    print(f"\n登记 {len(reg)}（已发段 {len(live_reg)} / 计划段 {len(planned)}）"
          f" · 后端实发 {len(fired)} · 前端实发 {len(front)}\n")

    print("── 1. 已发段：登记的事件必须真的有人发 ──")
    dead = sorted(live_reg - fired - front)
    check(f"{len(live_reg)} 个『已发』事件都有调用点", not dead,
          f"死条目（表里有、代码里没有）：{dead}")

    print("\n── 2. 计划段：登记为『计划』的必须确实还没人发 ──")
    # 反向保护：功能一旦落地开始发事件，就该把条目搬出计划段，
    # 否则表会一边标着"计划中"、一边在线上跑着，误导阅读者。
    implemented = sorted(planned & (fired | front))
    check(f"{len(planned)} 个『计划』事件确实都还没实现", not implemented,
          f"已实现但仍标着[计划]：{implemented}（请搬到『已发』段并去掉 [计划] 前缀）")

    print("\n── 3. 口径漂移：代码里发的事件必须在表里有名 ──")
    unregistered = sorted((fired | front) - set(reg))
    check("所有实发事件都已登记", not unregistered,
          f"发了却没登记：{unregistered}（照着表 grep 会漏掉这些）")

    print("\n── 4. 命名规范 ──")
    # 规则：事件名是「模块.动作」小写点分。
    # **例外白名单**：允许少量"类别根名"（如 `http` 代表全部 API 请求，
    # 与 `http.asset` 并列）。为什么不一刀切强制带点：
    #   `http` 已经在线上日志里跑了很久，改名等于让所有现存日志查询失联。
    # 白名单是**显式**的 —— 新加根名必须同时改这里，无法悄悄溜进来。
    ROOT_NAMES_OK = {"http"}  # 类别根名，与 http.asset 并列
    badname = [
        k for k in reg
        if k not in ROOT_NAMES_OK
        and not re.fullmatch(r"[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)+", k)
    ]
    check("事件名都是『模块.动作』小写点分（根名走白名单）", not badname,
          f"不合规：{badname}")

    print("\n── 5. 前端事件必须带 ui. 前缀 ──")
    badfront = [e for e in front if not e.startswith("ui.")]
    check("前端回传事件都带 ui. 前缀", not badfront, f"缺前缀：{badfront}")

    print("\n" + "=" * 62)
    print(f"通过 {OK} · 失败 {BAD}")
    print("=" * 62)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
