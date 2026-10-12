"""systemd unit 渲染的回归测试。

为什么值得单独测
----------------
`tools/service.py install` 往磁盘写的东西，用户**没法在装之前看到**
（他没有 Linux 机器，是在腾讯云上跑；写完才会 `systemctl` 试）。
所以「渲染出来的 unit 是不是对的」这件事，必须在这里静态验证掉 ——
等他在云上发现 ExecStart 里混了反斜杠，就太晚了。

这几条断言各自对应一个真实会踩的坑：
  · 反斜杠  —— Windows 上 str(Path) 会出反斜杠，而 unit 是 Linux 的
  · 引号    —— 路径带空格时 systemd 会把 ExecStart 切碎
  · 占位符  —— 模板改了但渲染没跟上，会留下 __SERVE__ 这种字面量
  · 三行齐全 —— WorkingDirectory / ExecStart / WantedBy 少一个服务就起不来
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import PurePosixPath

ROOT = __file__.rsplit("tools", 1)[0].rstrip("/\\")
spec = importlib.util.spec_from_file_location("svc", ROOT + "/tools/service.py")
svc = importlib.util.module_from_spec(spec)
sys.path.insert(0, ROOT + "/tools")
sys.path.insert(0, ROOT)
spec.loader.exec_module(svc)


def render(fake_root: str, port: int = 8000) -> str:
    svc.ROOT = PurePosixPath(fake_root)
    svc.project_python = lambda: fake_root + "/.venv/bin/python3"
    return svc.render_unit(port)


def line_of(text: str, prefix: str) -> str:
    for ln in text.splitlines():
        if ln.startswith(prefix):
            return ln
    return ""


def check(name: str, cond: bool, detail: str = "") -> bool:
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  — {detail}" if detail and not cond else ""))
    return cond


def main() -> int:
    ok = True
    for fake in ("/home/ubuntu/novel-downloader", "/root/novel"):
        print(f"\n[普通路径] {fake}")
        u = render(fake)
        ok &= check("无反斜杠", "\\" not in u, repr(u[:80]))
        ok &= check("无残留占位符", not re.findall(r"__[A-Z]+__", u),
                    str(re.findall(r"__[A-Z]+__", u)))
        ok &= check("WorkingDirectory 正确",
                    line_of(u, "WorkingDirectory=") == f"WorkingDirectory={fake}",
                    line_of(u, "WorkingDirectory="))
        ok &= check("ExecStart 正确",
                    line_of(u, "ExecStart=") ==
                    f"ExecStart={fake}/.venv/bin/python3 {fake}/tools/serve.py "
                    f"--host 0.0.0.0 --port 8000",
                    line_of(u, "ExecStart="))
        ok &= check("有 WantedBy", "WantedBy=default.target" in u)
        ok &= check("有 Restart=always", "Restart=always" in u)

    print("\n[带空格的路径] /home/my user/novel-downloader")
    u = render("/home/my user/novel-downloader")
    ex = line_of(u, "ExecStart=")
    ok &= check("ExecStart 两段路径都加了引号",
                ex.startswith('ExecStart="') and ex.count('"') == 4, ex)
    ok &= check("无残留占位符", not re.findall(r"__[A-Z]+__", u))
    ok &= check("无反斜杠", "\\" not in u)

    print("\n[端口参数] --port 9123")
    u = render("/home/ubuntu/novel-downloader", 9123)
    ok &= check("端口被正确替换",
                line_of(u, "ExecStart=").endswith("--port 9123"),
                line_of(u, "ExecStart="))

    print("\n[模板缺失时的兜底]")
    orig = svc.unit_template
    svc.unit_template = lambda: (_ for _ in ()).throw(FileNotFoundError("模拟模板丢失"))
    try:
        # 兜底路径读的是内嵌常量，不走文件；这里直接测内嵌版本能否渲染
        tmpl = ("[Unit]\nDescription=NovelDock\nAfter=network-online.target\n"
                "Wants=network-online.target\n\n[Service]\nType=simple\n"
                "WorkingDirectory=__ROOT__\n"
                "ExecStart=__PY__ __SERVE__ --host 0.0.0.0 --port __PORT__\n"
                "Restart=always\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n")
        svc.unit_template = lambda: tmpl
        u = render("/home/ubuntu/novel-downloader")
        ok &= check("兜底模板也能渲染出合法 ExecStart",
                    line_of(u, "ExecStart=").startswith("ExecStart=/home/"),
                    line_of(u, "ExecStart="))
    finally:
        svc.unit_template = orig

    print("\n[热榜定时刷新 unit]")
    # 这两个 unit 是"兜底层"，装错了的后果是「热榜悄悄不再更新」——
    # 而用户根本不会去 journal 里翻，只会觉得"这功能最近没新书了"。
    # 所以静态断言比主服务还重要：主服务坏了马上看得出来，这个坏了很安静。
    for fake in ("/home/ubuntu/novel-downloader", "/root/novel"):
        svc.ROOT = PurePosixPath(fake)
        svc.project_python = lambda: fake + "/.venv/bin/python3"
        rsvc, rtmr = svc.render_ranks_units(8000)

        tag = fake.split("/")[-1]
        ok &= check(f"[{tag}] timer 无反斜杠", "\\" not in rtmr, repr(rtmr[:80]))
        ok &= check(f"[{tag}] timer 无残留占位符",
                    not re.findall(r"__[A-Z]+__", rtmr),
                    str(re.findall(r"__[A-Z]+__", rtmr)))
        ok &= check(f"[{tag}] service 无残留占位符",
                    not re.findall(r"__[A-Z]+__", rsvc),
                    str(re.findall(r"__[A-Z]+__", rsvc)))

        # timer 三要素：绑主服务 / 有周期 / 开机补跑
        ok &= check(f"[{tag}] timer 依赖主服务",
                    line_of(rtmr, "Wants=").endswith("noveldock.service"),
                    line_of(rtmr, "Wants="))
        ok &= check(f"[{tag}] timer 有固定周期",
                    "OnCalendar=" in rtmr and "00/30" in rtmr,
                    line_of(rtmr, "OnCalendar="))
        ok &= check(f"[{tag}] timer 开机后补跑",
                    bool(line_of(rtmr, "OnBootSec=")), line_of(rtmr, "OnBootSec="))
        ok &= check(f"[{tag}] timer 会补跑错过的时间点",
                    line_of(rtmr, "Persistent=").endswith("true"),
                    line_of(rtmr, "Persistent="))
        ok &= check(f"[{tag}] timer 装在 timers.target",
                    line_of(rtmr, "WantedBy=").endswith("timers.target"),
                    line_of(rtmr, "WantedBy="))

        # service：必须打本地刷新接口，而不是自己 import 抓
        ex = line_of(rsvc, "ExecStart=")
        ok &= check(f"[{tag}] 执行体是 ranks_cron.py", ex.endswith("ranks_cron.py"), ex)
        ok &= check(f"[{tag}] 用项目 venv 解释器", ".venv/bin/python3" in ex, ex)
        ok &= check(f"[{tag}] WorkingDirectory 正确",
                    line_of(rsvc, "WorkingDirectory=") == f"WorkingDirectory={fake}",
                    line_of(rsvc, "WorkingDirectory="))
        ok &= check(f"[{tag}] 是 oneshot（跑完就退，不是常驻）",
                    line_of(rsvc, "Type=") == "Type=oneshot", line_of(rsvc, "Type="))
        ok &= check(f"[{tag}] 有超时保护（站点挂了不会一直挂）",
                    bool(line_of(rsvc, "TimeoutStartSec=")),
                    line_of(rsvc, "TimeoutStartSec="))
        # ⚠ 这次踩过的坑：service 里若写了 [Install] WantedBy=...，
        # systemd 会把它当成能被 enable 的常驻服务，而它其实是 oneshot。
        ok &= check(f"[{tag}] oneshot 不该带 [Install]",
                    "[Install]" not in rsvc)

    print("\n[路径带空格]")
    svc.ROOT = PurePosixPath("/home/my user/novel-downloader")
    svc.project_python = lambda: "/home/my user/novel-downloader/.venv/bin/python3"
    rsvc, _ = svc.render_ranks_units(8000)
    ex = line_of(rsvc, "ExecStart=")
    ok &= check("空格路径下 ExecStart 加了引号",
                ex.startswith('ExecStart="') and ex.count('"') == 4, ex)

    print()
    if ok:
        print("=== 全部通过 ===")
        return 0
    print("=== 有失败项 ===")
    return 1


if __name__ == "__main__":
    sys.exit(main())
