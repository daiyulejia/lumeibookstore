"""把服务装成「开机自动在后台跑」。

为什么用启动文件夹而不是 Windows 服务 / 计划任务
------------------------------------------------
- **Windows 服务**要管理员权限，而且服务会话里没有用户环境，
  跑 venv、读写用户目录都容易出岔子。
- **计划任务**的「登录时触发」在很多机器上同样要提权。
- **启动文件夹**：纯用户级，双击都不用，重启电脑后自己就在了。
  对「我自己电脑上的一个工具」这个场景，它是对的粒度。

启动项是一个 .vbs 而不是 .bat —— .bat 每次会闪一个黑窗口，
.vbs 用 `WScript.Shell.Run(..., 0, ...)` 能完全静默启动。

用法（Windows）：
  python tools/service.py install     # 装自启（并立刻启动）
  python tools/service.py remove      # 取消自启（并停止）
  python tools/service.py status      # 看状态
  python tools/service.py stop        # 只停，不动自启

用法（Linux / 云服务器）：
  同一个脚本会自动走 **systemd --user** 这条路 —— 云服务器上没有
  「启动文件夹」这种东西，正确的粒度是一个 user unit。
  而且云服务器本来就该 7x24 常驻，systemd 天生就是干这个的：
  崩了自动拉起、开机自动起来、`journalctl` 能翻日志。

    python3 tools/service.py install    # 装 systemd --user 常驻（并立刻启动）
    python3 tools/service.py status
    python3 tools/service.py stop
    python3 tools/service.py remove

  注意：`--user` 的 unit 只在**你登录着**的时候跑。云服务器上
  你通常是 ssh 进去的，一断连 session 就没了 —— 所以 install 里
  会自动执行 `loginctl enable-linger`，让服务在你登出后继续跑。
  这一步是云部署最容易漏、也最致命的地方（服务看着装好了，
  一关 ssh 就停）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASK_NAME = "NovelDock 噜妹书院"

# Linux（systemd --user）那边用的名字必须是纯 ASCII、无空格 ——
# unit 文件名会被 systemctl 当标识符用，中文名在部分 systemd 版本上
# 会有转义/匹配问题，而且 shell 里 tab 补全会很麻烦。
UNIT_NAME = "noveldock"

# 热榜定时刷新用的 unit。刻意和主服务分开命名（-ranks 后缀）：
# 主服务的 start/stop/status 语义是「让网站活着」，而这个只是「定时喂缓存」，
# 混在一个 unit 里会让两条命周期互相牵连。分开之后单独停掉定时、
# 或者单独看它的日志都很清爽。
RANKS_UNIT = "noveldock-ranks"

# 解释器选择逻辑只写一份，就在 serve.py 里 —— 两边各写一遍迟早会漂移，
# 而漂移的后果是自启拉起一个没装依赖的解释器，服务起不来还查不出原因。
sys.path.insert(0, str(ROOT / "tools"))
# 项目根也要加：status 里要 `from app import ...` 拿令牌、局域网 IP、
# 隧道地址。少这一行的话那几个 import 会静默失败，
# 表现就是"该打的三行没打出来、也不报错"（踩过一次）。
sys.path.insert(0, str(ROOT))
from serve import project_python  # noqa: E402

IS_LINUX = os.name != "nt"


# ---------------------------------------------------------------------------
# Linux / 云服务器：systemd --user
# ---------------------------------------------------------------------------
# 为什么不复用下面 Windows 那套逻辑
# ---------------------------------
# 「启动文件夹 + .vbs」是 Windows 独有的东西，Linux 上没有对应物。
# Linux 上要做「开机自启 + 崩了重启」，标准答案就是 systemd。
#
# 为什么用 `--user` 而不是系统级 `/etc/systemd/system/`
# -----------------------------------------------------
# 系统级 unit 要 root（sudo）才能装。而这个工具的数据全在**你自己的
# home 目录**里（项目根、cache/auth.json、library/…），让 root 去跑
# 反而要处理一堆属主/权限问题。user unit 就够用，而且不需要 sudo。
#
# 唯一的坑：user unit 默认**只在你登录期间**运行 —— ssh 一断就停。
# 解法是 `loginctl enable-linger <用户>`，让 systemd 为这个用户
# 一直保留一个 session。install 里会自动做这一步（见 enable_linger）。


def unit_dir() -> Path:
    """systemd user unit 该放哪。

    XDG_CONFIG_HOME 优先（用户可能改过），否则退回家目录下的默认位置。
    """
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def unit_path() -> Path:
    return unit_dir() / f"{UNIT_NAME}.service"


def unit_template() -> str:
    """读那份 .tmpl 模板。

    模板独立成文件（而不是内嵌在这个 py 里）有两个好处：
      · 语法高亮 / 编辑器识别正常，不会像之前 VBS 那样踩编码坑
      · 用户可以直接 `cat` 出来看、照着改
    代价是路径要自己找 —— 找不到就退回一份内嵌的最小版本，
    不能让「模板文件丢了」把安装整个卡死。
    """
    tmpl = ROOT / "tools" / "noveldock.service.tmpl"
    try:
        return tmpl.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        # 最小可用兜底。注意 WorkingDirectory 和 ExecStart 仍然是完整的，
        # 少掉的只是注释和内存软上限那些"锦上添花"。
        return (
            "[Unit]\n"
            "Description=NovelDock\n"
            "After=network-online.target\n"
            "Wants=network-online.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            "WorkingDirectory=__ROOT__\n"
            "ExecStart=__PY__ __ROOT__/tools/serve.py --host 0.0.0.0 --port __PORT__\n"
            "Restart=always\n"
            "RestartSec=5\n"
            "StandardOutput=journal\n"
            "StandardError=journal\n"
            "SyslogIdentifier=noveldock\n\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )


def render_unit(port: int) -> str:
    """把模板里的占位符填成这台机器上的真实路径。

    路径里可能有空格（`/home/my user/...`），systemd 的 ExecStart 里
    空格会被当参数分隔符 —— 所以**必须**给两段路径都加引号。

    路径一律用 `as_posix()` 渲染（正斜杠）。systemd unit 是 Linux 的东西，
    里面塞 `C:\\foo\\bar` 那种反斜杠路径是错的 —— 哪怕这份代码在
    Windows 上被调用（比如用户先在本机看了一眼再传上去），也要输出
    正确的 Linux 形式，不能让它"看起来像 Linux"却带着 Windows 分隔符。
    """
    py = project_python()
    # serve.py 的完整路径在这里拼好，模板里只留一个 __SERVE__ 占位符 ——
    # 这样不用在模板里写 `__ROOT__/tools/serve.py` 那种"半拼接"，
    # 避免 `C:\\x` + `/tools/...` 混出 `C:\\x/tools` 这种畸形路径。
    serve = (ROOT / "tools" / "serve.py").as_posix()
    root = Path(ROOT).as_posix()
    py_posix = Path(py).as_posix()

    text = unit_template()
    for key, val in (
        ("__ROOT__", root),
        ("__PY__", py_posix),
        ("__SERVE__", serve),
        ("__PORT__", str(port)),
    ):
        text = text.replace(key, val)
    # 路径含空格时给 ExecStart 里两段路径加引号（systemd 的空格分隔问题）
    if " " in root or " " in py_posix:
        text = text.replace(
            f"ExecStart={py_posix} {serve}",
            f'ExecStart="{py_posix}" "{serve}"',
        )
    return text


# ---------------------------------------------------------------------------
# 热榜定时刷新（systemd timer）
# ---------------------------------------------------------------------------
def _render_tmpl(name: str, extra: dict[str, str]) -> str:
    """把 tools/<name> 里的模板填上 `__XXX__` 占位符。

    和 render_unit 共用同一套约定（占位符 + as_posix + 路径带空格才加引号），
    所以这里抽出来复用 —— 三个模板各写一遍替换逻辑，迟早漏掉一个占位符，
    而漏掉的后果是 unit 里留着一个字面量 `__PY__`，systemd 会直接报语法错。
    """
    # ⚠ 模板文件本身**必须从真实项目目录读**，不能用 ROOT。
    # ROOT 会被测试替换成一个假路径（用来验渲染结果），
    # 那次查找就变成 `PurePosixPath('/home/ubuntu/...').read_text()` → 崩。
    # 也就是说：ROOT 决定"往 unit 里填什么路径"，真正去哪读模板是另一回事。
    tmpl = Path(__file__).resolve().parent / name
    text = tmpl.read_text(encoding="utf-8")
    fields = {
        "__ROOT__": Path(ROOT).as_posix(),
        "__PY__": Path(project_python()).as_posix(),
        **extra,
    }
    for k, v in fields.items():
        text = text.replace(k, v)
    # 路径含空格时给 ExecStart 加引号（systemd 用空格分参数）
    py_posix = fields["__PY__"]
    if " " in fields["__ROOT__"] or " " in py_posix:
        for exe in (f"{py_posix} {fields['__ROOT__']}/tools/ranks_cron.py",):
            text = text.replace(f"ExecStart={exe}", f'ExecStart="{py_posix}" '
                                                    f'"{fields["__ROOT__"]}/tools/ranks_cron.py"')
    return text


def render_ranks_units(port: int) -> tuple[str, str]:
    """渲染热榜的 service + timer 两份 unit（不落盘，纯字符串）。

    抽成纯函数是为了能离线断言 —— 见 tools/test_service_unit.py。
    """
    svc = _render_tmpl("noveldock-ranks.service.tmpl", {"__PORT__": str(port)})
    tmr = _render_tmpl("noveldock-ranks.timer.tmpl", {"__PORT__": str(port)})
    return svc, tmr


# 来源库深夜体检用的 unit。同样单独命名（-registry 后缀）——
# 它和热榜刷新是两件完全不相干的事：
#   · 热榜刷新是「喂前端缓存」，白天也要跑（每 30 分钟）
#   · 来源库体检是「打扫自己的库」，只该在半夜跑（凌晨 3~4 点）
# 合成一个 unit 就没法给它们不同的作息。
REGISTRY_UNIT = "noveldock-registry"


def render_registry_units(port: int) -> tuple[str, str]:
    """渲染来源库体检的 service + timer 两份 unit（纯字符串，可离线断言）。"""
    svc = _render_tmpl("noveldock-registry.service.tmpl", {"__PORT__": str(port)})
    tmr = _render_tmpl("noveldock-registry.timer.tmpl", {"__PORT__": str(port)})
    return svc, tmr


def lin_install_registry(port: int) -> int:
    """装来源库深夜体检（Linux）。幂等：重复跑就是重写 + reload。"""
    d = unit_dir()
    d.mkdir(parents=True, exist_ok=True)
    svc, tmr = render_registry_units(port)
    (d / f"{REGISTRY_UNIT}.service").write_text(svc, encoding="utf-8")
    (d / f"{REGISTRY_UNIT}.timer").write_text(tmr, encoding="utf-8")
    print(f"✓ 已写入来源库体检 unit：\n  {d / (REGISTRY_UNIT + '.timer')}\n"
          f"  {d / (REGISTRY_UNIT + '.service')}")

    rc, out = systemctl("daemon-reload")
    if rc != 0:
        print(f"! daemon-reload 失败：{out.strip()}")

    rc, out = systemctl("enable", "--now", f"{REGISTRY_UNIT}.timer")
    if rc == 0:
        print("✓ 来源库深夜体检已启用（凌晨 3:17 / 3:37 / 3:57 各一次）")
    else:
        print(f"! 启用失败：{out.strip()}")
        print(f"  看日志： journalctl --user -u {REGISTRY_UNIT} -n 50 --no-pager")

    # 不在这里立即试跑 —— 体检会打几十个请求，安装时（多半是白天）
    # 立刻跑一轮会跟用户抢带宽，而且和「深夜」的设计初衷相悖。
    # 想看效果请手动 `systemctl --user start noveldock-registry.service`。
    print("\n常用命令：")
    print(f"  下次什么时候跑： systemctl --user list-timers {REGISTRY_UNIT} --no-pager")
    print(f"  立刻体检一次：  systemctl --user start {REGISTRY_UNIT}.service")
    print(f"  看执行日志：    journalctl --user -u {REGISTRY_UNIT} -n 50 --no-pager")
    print(f"  关掉定时：      systemctl --user disable --now {REGISTRY_UNIT}.timer")
    return 0 if rc == 0 else 1


def lin_remove_registry() -> int:
    systemctl("disable", "--now", f"{REGISTRY_UNIT}.timer")
    for ext in (".timer", ".service"):
        p = unit_dir() / f"{REGISTRY_UNIT}{ext}"
        if p.exists():
            p.unlink()
    systemctl("daemon-reload")
    print("✓ 已移除来源库深夜体检")
    return 0


def lin_status_registry() -> int:
    """来源库体检的体检：装了没、timer 活没活、库现在什么样。"""
    tmr = unit_dir() / f"{REGISTRY_UNIT}.timer"
    print(f"来源库深夜体检：{'✓ 已装' if tmr.exists() else '✗ 未装'}")
    if tmr.exists():
        _, out = systemctl("is-active", f"{REGISTRY_UNIT}.timer")
        print(f"   timer 状态：{out.strip() or '（拿不到）'}")
        _, out = systemctl("is-enabled", f"{REGISTRY_UNIT}.timer")
        print(f"   开机自启：  {out.strip() or '（拿不到）'}")
        rc, out = systemctl("list-timers", f"{REGISTRY_UNIT}", "--no-pager")
        if rc == 0 and out.strip():
            for line in out.strip().splitlines():
                if REGISTRY_UNIT in line:
                    print(f"   下次执行：  {' '.join(line.split()[:3])}")
                    break
    else:
        print("  装上： python3 tools/service.py install-registry")
    # 库侧
    try:
        import json
        import urllib.request
        with urllib.request.urlopen(
                "http://127.0.0.1:8000/api/registry", timeout=8) as r:
            st = json.loads(r.read().decode("utf-8"))
        s = st.get("stats") or {}
        print(f"   来源库：   站 {s.get('sites')}（健康 {s.get('sites_ok')}，"
              f"可搜 {s.get('sites_searchable')}）/ 书 {s.get('books')}"
              f"（健康 {s.get('books_ok')}）")
    except Exception as e:  # noqa: BLE001
        print(f"   （读不到服务状态：{e}）")
    return 0


def lin_install_ranks(port: int) -> int:
    """装热榜定时刷新（Linux）。幂等：重复跑就是重写 + reload。"""
    d = unit_dir()
    d.mkdir(parents=True, exist_ok=True)
    svc, tmr = render_ranks_units(port)
    (d / f"{RANKS_UNIT}.service").write_text(svc, encoding="utf-8")
    (d / f"{RANKS_UNIT}.timer").write_text(tmr, encoding="utf-8")
    print(f"✓ 已写入定时刷新 unit：\n  {d / (RANKS_UNIT + '.timer')}\n"
          f"  {d / (RANKS_UNIT + '.service')}")

    rc, out = systemctl("daemon-reload")
    if rc != 0:
        print(f"! daemon-reload 失败：{out.strip()}")

    rc, out = systemctl("enable", "--now", f"{RANKS_UNIT}.timer")
    if rc == 0:
        print("✓ 热榜定时刷新已启用（每 30 分钟一次）")
    else:
        print(f"! 启用失败：{out.strip()}")
        print(f"  看日志： journalctl --user -u {RANKS_UNIT} -n 50 --no-pager")

    # 先手动跑一次，确认链路是通的 —— 不然用户要等 30 分钟才知道坏没坏。
    print("· 立即试跑一次…")
    rc2, out2 = systemctl("start", f"{RANKS_UNIT}.service")
    if rc2 == 0:
        print("✓ 试跑完成（详情见 journal）")
    else:
        print(f"! 试跑失败：{out2.strip()}")

    print("\n常用命令：")
    print(f"  下次什么时候刷： systemctl --user list-timers {RANKS_UNIT} --no-pager")
    print(f"  手动刷一次：    systemctl --user start {RANKS_UNIT}.service")
    print(f"  看执行日志：    journalctl --user -u {RANKS_UNIT} -n 50 --no-pager")
    print(f"  关掉定时：      systemctl --user disable --now {RANKS_UNIT}.timer")
    return 0 if rc == 0 else 1


def lin_remove_ranks() -> int:
    systemctl("disable", "--now", f"{RANKS_UNIT}.timer")
    for ext in (".timer", ".service"):
        p = unit_dir() / f"{RANKS_UNIT}{ext}"
        if p.exists():
            p.unlink()
    systemctl("daemon-reload")
    print("✓ 已移除热榜定时刷新")
    return 0


def lin_status_ranks() -> int:
    """热榜定时的体检：装了没、timer 活没活、下次啥时候、上次结果如何。

    这里同时读**两个**来源：
      · systemd timer 的状态（任务层有没有在跑）
      · 服务自己的 /api/ranks/status（缓存层新不新）
    只看前者会漏掉「任务在跑但站点抓不到」，只看后者会漏掉「缓存新
    但其实是进程内线程刷的、timer 根本没装」。
    """
    tmr = unit_dir() / f"{RANKS_UNIT}.timer"
    print(f"定时刷新：{'✓ 已装' if tmr.exists() else '✗ 未装'}")
    if not tmr.exists():
        print("  装上： python3 tools/service.py install-ranks")
        return 0
    _, out = systemctl("is-active", f"{RANKS_UNIT}.timer")
    print(f"   timer 状态：{out.strip() or '（拿不到）'}")
    _, out = systemctl("is-enabled", f"{RANKS_UNIT}.timer")
    print(f"   开机自启：  {out.strip() or '（拿不到）'}")
    rc, out = systemctl("list-timers", f"{RANKS_UNIT}", "--no-pager")
    if rc == 0 and out.strip():
        for line in out.strip().splitlines():
            if RANKS_UNIT in line:
                print(f"   下次执行：  {' '.join(line.split()[:3])}")
                break
    # 缓存侧
    try:
        import json
        import urllib.request
        with urllib.request.urlopen(
                "http://127.0.0.1:8000/api/ranks/status", timeout=6) as r:
            st = json.loads(r.read().decode("utf-8"))
        c = st.get("cache", {})
        s = st.get("sched", {})
        print(f"   缓存条目：  {c.get('total')} 条"
              f"（过期 {c.get('stale_count')} 类）")
        age = c.get("oldest_age")
        print(f"   最旧一份：  {'—' if age is None else str(int(age // 60)) + ' 分钟前'}")
        print(f"   进程内刷新：{'运行中' if s.get('running') else '未运行'}"
              f"，已跑 {s.get('runs')} 轮")
        if s.get("last_error"):
            print(f"   ⚠ 上次错误：{s['last_error']}")
    except Exception as e:  # noqa: BLE001
        print(f"   （读不到服务状态：{e}）")
    return 0


def systemctl(*args: str) -> tuple[int, str]:
    """跑 systemctl --user …，把 stdout+stderr 一起返回。

    云服务器上如果 systemd 不可用（极少数精简镜像），
    或者用户在 WSL/容器里——那 `systemctl` 会报错。这里不吞异常，
    让调用方看到真实原因，比"什么都没发生"强。
    """
    try:
        p = subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True, text=True, timeout=30,
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "找不到 systemctl —— 这台机器上可能没有 systemd（容器 / WSL1？）"
    except Exception as e:  # noqa: BLE001
        return 1, f"{type(e).__name__}: {e}"


def enable_linger() -> None:
    """让 user service 在你退出 ssh 之后继续跑。

    这一步**极易漏**：不做的话，`systemctl --user start` 看着一切正常，
    你关掉 ssh 窗口服务就停了 —— 而你去手机上打开时它已经没了。

    需要 sudo（loginctl enable-linger 是特权操作）。所以这里
    只尝试、不强制：失败就打印一行提示，让用户自己决定要不要执行。
    """
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    if not user:
        return
    try:
        p = subprocess.run(
            ["loginctl", "show-user", user, "--property=Linger"],
            capture_output=True, text=True, timeout=15,
        )
        if "Linger=yes" in (p.stdout or ""):
            return  # 已经开着
    except Exception:  # noqa: BLE001
        pass
    try:
        p = subprocess.run(
            ["sudo", "-n", "loginctl", "enable-linger", user],
            capture_output=True, text=True, timeout=20,
        )
        if p.returncode == 0:
            print(f"✓ 已开启 linger：退出 ssh 后服务会继续跑（用户 {user}）")
        else:
            print(f"! 没开成 linger（{user}）。**这一步很重要**：")
            print(f"    不开的话，你一关掉 ssh，服务就停了。")
            print(f"    手动执行一次即可： sudo loginctl enable-linger {user}")
    except FileNotFoundError:
        print(f"! 这台机器没有 loginctl。请确认： sudo loginctl enable-linger {user}")
    except Exception as e:  # noqa: BLE001
        print(f"! 开 linger 时出错：{type(e).__name__}: {e}")
        print(f"    手动执行： sudo loginctl enable-linger {user}")


def lin_install(port: int) -> int:
    d = unit_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = unit_path()
    p.write_text(render_unit(port), encoding="utf-8")
    print(f"✓ 已写入 systemd unit：\n  {p}")

    rc, out = systemctl("daemon-reload")
    if rc != 0:
        print(f"! daemon-reload 失败：{out.strip()}")
        print("  （下面这几步可能都会跟着失败，留意一下输出）")

    # enable + start：enable 管"开机自启"，start 管"现在就起来"
    rc, out = systemctl("enable", "--now", f"{UNIT_NAME}.service")
    if rc == 0:
        print("✓ 已启用开机自启，并立即启动")
    else:
        print(f"! 启动失败：{out.strip()}")
        print(f"  看日志： journalctl --user -u {UNIT_NAME} -n 50 --no-pager")

    enable_linger()

    print("\n常用命令：")
    print(f"  看状态： python3 tools/service.py status")
    print(f"  看日志： journalctl --user -u {UNIT_NAME} -n 50 --no-pager")
    print(f"  实时日志： journalctl --user -u {UNIT_NAME} -f")
    print(f"  停掉：   python3 tools/service.py stop")
    return 0 if rc == 0 else 1


def lin_remove(stop_too: bool = True) -> int:
    if stop_too:
        systemctl("disable", "--now", f"{UNIT_NAME}.service")
    else:
        systemctl("disable", f"{UNIT_NAME}.service")
    p = unit_path()
    if p.exists():
        p.unlink()
        print("✓ 已移除 systemd unit")
    else:
        print("· 没有 systemd unit")
    systemctl("daemon-reload")
    return 0


def lin_status(port: int) -> int:
    p = unit_path()
    print(f"开机自启：{'✓ 已装' if p.exists() else '✗ 未装'}")
    if p.exists():
        print(f"    unit：{p}")
    rc, out = systemctl("is-active", f"{UNIT_NAME}.service")
    state = out.strip()
    print(f"服务状态：{state if state else '（拿不到）'}")
    rc2, out2 = systemctl("is-enabled", f"{UNIT_NAME}.service")
    print(f"自启状态：{out2.strip() or '（拿不到）'}")

    # 下面是和 Windows 分支共用的「人在外面真正要看的东西」。
    _print_access_info(port)
    return 0


def startup_dir() -> Path:
    if os.name != "nt":
        return Path.home() / ".config" / "autostart"
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def launcher_path() -> Path:
    return startup_dir() / f"{TASK_NAME}.vbs"


def pythonw() -> str:
    return project_python(windowless=True)


def vbs_source() -> str:
    """生成启动用的 VBS。

    VBS 里字符串的转义规则是「两个双引号 = 一个字面双引号」，
    所以要让 WScript 收到一个「pythonw.exe 路径 + serve.py 路径」
    且两段都带引号的命令行，源码里每个双引号都得写成两个。
    （路径里可能有空格，不加引号会被拆成两个参数。）

    ⚠ 这段源码必须**保持纯 ASCII**。csript/wscript 读 .vbs 时按系统
    ANSI 代码页（简中是 GBK）解析，而 install() 是按 utf-8 写盘的 ——
    一旦这里出现中文，写下去就是 UTF-8 字节、读回来按 GBK 解，
    注释会变成乱码（严重时引号被吃掉、脚本直接语法错误起不来）。
    纯 ASCII 时两种编码完全一致，所以现在没问题。
    """
    pw = pythonw()
    sp = str(ROOT / "tools" / "serve.py")
    inner = f'"{pw}" "{sp}"'.replace('"', '""')
    return (
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'sh.Run "{inner}", 0, False\r\n'
    )


def _spawn_background() -> bool:
    """用 pythonw 直接把守护进程拉起来，**不经过 wscript**。

    为什么不用 wscript 跑 .vbs：多一层解释器就多一个可能被安全策略掐掉的
    环节。实测在受限环境里 `wscript.exe <vbs>` 会被拦（进程建了就没了，
    还不报错），而 pythonw 直接起是好的。pythonw 本身就无控制台窗口，
    再加 DETACHED_PROCESS 脱离父进程，静默程度和 .vbs 方案一样，环节更少。

    .vbs 依旧写进启动文件夹 —— 那是给「开机自动」用的，和这里的「立刻启动」是两回事。
    """
    pw = pythonw()
    sp = str(ROOT / "tools" / "serve.py")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    try:
        subprocess.Popen(
            [pw, sp], cwd=str(ROOT), creationflags=flags,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def install(start_now: bool = True) -> int:
    d = startup_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = launcher_path()
    p.write_text(vbs_source(), encoding="utf-8", newline="")
    print(f"✓ 已写入开机启动项：\n  {p}")

    if start_now:
        # 先看看是不是已经在跑了，别起两个（两个会抢端口和缓存目录）
        st = _serve_status()
        if st.get("running"):
            print("· 服务已经在跑了，不用重复启动")
        elif _spawn_background():
            print("✓ 已在后台启动（pythonw 静默运行）")
        else:
            try:
                subprocess.Popen(["wscript.exe", str(p)], cwd=str(ROOT))
                print("✓ 已通过开机启动项启动")
            except Exception as e:  # noqa: BLE001
                print(f"! 后台启动失败：{e}\n  手动跑：{pythonw()} {ROOT / 'tools' / 'serve.py'}")

    print("\n日志在 logs/ 里。要看状态： python tools/service.py status")
    return 0


def remove(stop_too: bool = True) -> int:
    p = launcher_path()
    if p.exists():
        p.unlink()
        print(f"✓ 已移除开机启动项")
    else:
        print("· 没有开机启动项")
    if stop_too:
        _serve(["stop"])
    return 0


def _serve(args: list[str]) -> int:
    return subprocess.call([project_python(), str(ROOT / "tools" / "serve.py"), *args])


def _serve_status(port: int = 8000) -> dict:
    import json
    try:
        out = subprocess.run(
            [project_python(), str(ROOT / "tools" / "serve.py"), "--status", "--port", str(port)],
            capture_output=True, text=True, timeout=30,
        ).stdout
        return json.loads(out)
    except Exception:  # noqa: BLE001
        return {}


def status(port: int) -> int:
    p = launcher_path()
    st = _serve_status(port)
    print(f"开机自启：{'✓ 已装' if p.exists() else '✗ 未装'}")
    if p.exists():
        print(f"    入口：{p}")
    print(f"服务状态：{'✓ 正在运行' if st.get('running') else '✗ 没在跑'}"
          + (f"（pid {st.get('pid')}）" if st.get("pid") else ""))
    print(f"端口 {port}：{'监听中' if st.get('listening') else '无监听'}")
    if st.get("log"):
        print(f"日志：{st['log']}")

    _print_access_info(port)
    return 0


def _print_access_info(port: int) -> None:
    """打印「人在外面真正要看的东西」：能打开的链接 + 钥匙。

    只报"服务在跑"是不够的 —— 用户在外面只有一部手机，
    他需要的是**一条能直接点开的地址**和**一串能用的令牌**。
    所以这几行比上面的运行状态更重要。

    这些属于"锦上添花"的信息：拿不到不该让 status 整体失败，
    但要留一条痕迹 —— 别像上次那样被静默 except 吞掉、查半天。
    Windows / Linux 两个分支共用这一段。
    """
    tok = ""
    try:
        from app import netinfo, security
        tok = security.token()
        ip = netinfo.lan_ip()
        if ip:
            if IS_LINUX and netinfo.looks_like_cloud(ip):
                pub = netinfo.public_ip()
                if pub:
                    print(f"    外网访问：http://{pub}:{port}   （云服务器的公网 IP）")
                else:
                    print(f"    内网地址：http://{ip}:{port}   （云内网；外面连不上）")
            else:
                print(f"    局域网：http://{ip}:{port}   （手机同 WiFi 时用这个，不需要令牌）")
        print(f"    访问令牌：{tok}")
    except Exception as e:  # noqa: BLE001
        print(f"    （拿不到局域网/令牌：{type(e).__name__}: {e}）")
    try:
        from app import tunnel
        st_t = tunnel.status() or {}
        url = str(st_t.get("url") or "").strip()
        if url and st_t.get("running") and tok:
            print(f"    远程访问：{url}?t={tok}")
        elif url:
            print(f"    远程访问：{url}（隧道没在跑，这个地址现在打不开）")
        else:
            print("    远程访问：未开启（界面上「网络」面板里点一下就有了）")
        if tunnel.ACCESS_FILE.exists():
            print(f"    随时可查：{tunnel.ACCESS_FILE.name}（就在程序目录里，链接和令牌都写在里面）")
    except Exception as e:  # noqa: BLE001
        print(f"    （拿不到隧道状态：{type(e).__name__}: {e}）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=[
        "install", "remove", "status", "stop", "start",
        # 热榜定时刷新（仅 Linux/systemd 有意义）
        "install-ranks", "remove-ranks", "status-ranks",
        # 来源库深夜体检（仅 Linux/systemd 有意义）
        "install-registry", "remove-registry", "status-registry",
    ])
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()

    # 热榜定时刷新是 systemd 专属能力。Windows 那边由进程内调度器覆盖
    # （run.py 里那个 sched 线程），所以这里明确告诉用户不用另外装东西 ——
    # 而不是默默什么都不做，让人以为漏配了。
    if a.action.endswith("-ranks"):
        if not IS_LINUX:
            print("· Windows/本机不需要装这个：")
            print("  热榜刷新已经由服务进程内的调度器负责（启动时自动开）。")
            print("  想确认它在跑：打开界面 → 顶栏「网络」右侧的榜单状态，")
            print("  或 curl http://127.0.0.1:8000/api/ranks/status")
            return 0
        if a.action == "install-ranks":
            return lin_install_ranks(a.port)
        if a.action == "remove-ranks":
            return lin_remove_ranks()
        return lin_status_ranks()

    # 来源库深夜体检同理：它是 systemd 定时能力，本机跑没有意义
    # （本机开发时手动 `tools/registry_nightly.py` 就行）。
    if a.action.endswith("-registry"):
        if not IS_LINUX:
            print("· Windows/本机不需要装这个：")
            print("  深夜体检是给长期跑着的线上服务用的。本机想手动跑一次：")
            print("    .venv\\Scripts\\python tools\\registry_nightly.py")
            return 0
        if a.action == "install-registry":
            return lin_install_registry(a.port)
        if a.action == "remove-registry":
            return lin_remove_registry()
        return lin_status_registry()

    # Linux / 云服务器走 systemd，Windows 走启动文件夹。
    # 两条路都叫 install/remove/status/stop/start，命令保持一致 ——
    # 用户在两台机器上来回切时不用记两套。
    if IS_LINUX:
        if a.action == "install":
            return lin_install(a.port)
        if a.action == "remove":
            return lin_remove()
        if a.action == "status":
            return lin_status(a.port)
        if a.action == "stop":
            systemctl("stop", f"{UNIT_NAME}.service")
            print("✓ 已停止")
            return 0
        if a.action == "start":
            rc, out = systemctl("start", f"{UNIT_NAME}.service")
            print("✓ 已启动" if rc == 0 else f"! 启动失败：{out.strip()}")
            return 0 if rc == 0 else 1

    if a.action == "install":
        return install()
    if a.action == "remove":
        return remove()
    if a.action == "status":
        return status(a.port)
    if a.action == "stop":
        return _serve(["stop"])
    if a.action == "start":
        st = _serve_status(a.port)
        if st.get("running"):
            print("已经在一个跑了")
            return 0
        if _spawn_background():
            print("✓ 已在后台启动（pythonw 静默运行）")
            return 0
        return _serve(["--port", str(a.port)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
