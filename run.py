"""启动入口：python run.py"""
from __future__ import annotations

import argparse
import os
import sys

import uvicorn

from app.main import app, local_ip
from app.netinfo import check as net_check
from app.netinfo import find_allowed_python
from app.netinfo import is_private as net_is_private
from app.netinfo import looks_like_cloud as net_looks_like_cloud
from app.netinfo import public_ip as net_public_ip

# 已经借过解释器了就别再借一次（否则 execv 会无限递归）
_REEXEC_FLAG = "NOVELDOCK_BORROWED"


def _banner(host: str, port: int) -> str:
    """启动横幅。

    这个横幅存在的唯一理由是「手机上怎么打开」——那是用户最常问的问题，
    而答案有两半：地址是什么，以及**防火墙放行了没有**。只给地址是不够的：
    没放行时手机只会转圈，用户会以为软件坏了。

    后来补了第三半：**访问令牌**。人在外面、只有一台手机的时候，
    令牌只在「已经进去之后」才看得到 —— 而进去的前提正是有令牌。
    所以把它明明白白打在这里（这窗口只在本机屏幕上），
    等于给用户留了一条随时能抄的近路。
    """
    ip = local_ip()
    lines = [
        "=" * 60,
        "  小说下载器已启动",
        "=" * 60,
        f"  本机访问 : http://127.0.0.1:{port}",
    ]
    if host == "0.0.0.0":
        # 云服务器上 lan_ip() 拿到的是内网地址（10.x 那种），
        # 照着打印会让用户在外面拿着手机白试 —— 那个地址只有云内网认。
        # 注意判断用 looks_like_cloud（10.x / 172.16-31.x），
        # **不要**用 is_private：192.168 也是 private，
        # 那会把你家里电脑也当成云服务器、多打一堆没用的话。
        if net_looks_like_cloud(ip):
            pub = net_public_ip()
            if pub:
                lines.append(f"  外网访问 : http://{pub}:{port}")
                lines.append(f"             （公网 IP。记得云控制台「安全组」要放行 {port} 端口）")
                lines.append(f"  内网地址 : http://{ip}:{port}（云内网用，外面连不上）")
            else:
                lines.append(f"  内网地址 : http://{ip}:{port}")
                lines.append("             ⚠ 这是内网地址，外面连不上。")
                lines.append("             （没取到公网 IP；去云控制台看你的公网地址，")
                lines.append("               并确认「安全组」放行了该端口）")
        else:
            lines.append(f"  手机访问 : http://{ip}:{port}")
            lines.append("             （手机连同一个 WiFi，浏览器输这个地址）")
    else:
        lines.append(f"  仅本机   : 绑定在 {host}，手机访问不到")
        lines.append("             （想给手机用，去掉 --host 参数重开）")

    # 令牌 + 公网链接（有就显示）
    try:
        from app import security
        lines.append(f"  访问令牌 : {security.token()}")
    except Exception:  # noqa: BLE001
        pass
    try:
        from app import sched as _sc
        st = _sc.status()
        if st["enabled"]:
            lines.append(f"  热榜刷新 : 每 {max(1, st['interval'] // 60)} 分钟自动一次")
        else:
            lines.append("  热榜刷新 : 已关闭")
    except Exception:  # noqa: BLE001
        pass
    try:
        from app import tunnel
        full = tunnel.write_access_file()      # 顺手刷新根目录那份说明
        if full:
            lines.append(f"  远程访问 : {full}")
        else:
            lines.append("  远程访问 : 未开启（顶栏「网络」面板里点一下就有）")
        lines.append(f"  随时可查 : {tunnel.ACCESS_FILE.name}（就在程序目录里）")
    except Exception:  # noqa: BLE001
        pass

    lines.append("=" * 60)
    return "\n".join(lines)


def _firewall_hint(port: int) -> str:
    # Linux（云服务器）上没有什么"防火墙白名单按 exe 绑"这回事，
    # 拦人的是安全组和 ufw/iptables，netsh 那套在这儿既跑不通、
    # 给出来的命令也是错的。所以直接换一套说法。
    if os.name != "nt":
        return (
            f"  · 云服务器/外网要能访问，两个地方得放行 {port} 端口：\n"
            f"      1) 云厂商控制台的「安全组」放行 TCP {port}（这一步最容易忘）\n"
            f"      2) 服务器本机防火墙：sudo ufw allow {port}/tcp\n"
            f"     （只在本机自己用的话，这两步都可以不管）"
        )
    info = net_check(port)
    if info.get("ok"):
        return f"  ✓ 防火墙已放行 {port} 端口（规则：{info.get('rule_name')}）"
    # profiles 的值是 bool（netsh 在不同代码页下会输出「启用」或 ON，
    # 比字符串必踩坑 —— 曾经因此错报成「防火墙都关着，不会被拦」）
    if info.get("profiles") and not any(info["profiles"].values()):
        return "  ✓ 防火墙三个配置文件都关着，入站不会被拦"
    cmd = (f'netsh advfirewall firewall add rule name="NovelDock {port}" '
           f"dir=in action=allow protocol=TCP localport={port}")
    return (
        "  ⚠ 手机连不上？防火墙没放行入站端口 —— 这是最常见的原因。\n"
        "     用**管理员**身份打开 PowerShell / cmd，粘这一行就好：\n"
        f"       {cmd}\n"
        "     （只放行这一个端口，不用关防火墙。也可以跑 python tools/firewall.py --open）"
    )


def _borrow_exe(port: int) -> str | None:
    """当前解释器没被防火墙放行时，换一个**已经被放行**的解释器重启自己。

    为什么值得这么做：Windows 的程序放行规则是**按 exe 路径**绑定的，
    而往防火墙里加规则要管理员权限。但用户机器上往往**已经**有一条指向
    别的 python 的放行规则（装了 IDE / 工具就会自带），那条规则允许它
    接收入站连接。既然它已经在白名单里，直接借它来跑就行了 ——
    用户不用提权、不用动任何系统配置，也不需要理解防火墙。

    返回替换后的 exe 路径；没得借就返回 None（调用方照常继续）。
    """
    if sys.platform != "win32":
        return None
    if os.environ.get(_REEXEC_FLAG):
        return None  # 已经借过了，别再套娃

    try:
        if net_check(port).get("ok"):
            return None  # 当前解释器本来就被放行
        alt = find_allowed_python(port)
    except Exception:  # noqa: BLE001
        return None
    if not alt:
        return None

    # 把当前进程依赖的库路径带过去。用 sys.path 里现成的 site-packages
    # 而不是自己拼 `.venv/Lib/site-packages` —— 后者一换布局就错。
    deps = [p for p in sys.path if p and "site-packages" in p.replace("\\", "/").lower()]
    env = dict(os.environ)
    env[_REEXEC_FLAG] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    old_pp = env.get("PYTHONPATH", "")
    parts = deps + ([old_pp] if old_pp else [])
    if parts:
        env["PYTHONPATH"] = os.pathsep.join(parts)

    script = os.path.abspath(sys.argv[0])
    argv = [alt["exe"], script] + sys.argv[1:]
    print(
        f"  ⇄ 当前解释器不在防火墙白名单里，改用已放行的解释器启动\n"
        f"     {alt['exe']}\n"
        f"     （命中规则「{alt['rule']}」，Python {alt['version']}，"
        f"无需管理员权限、不修改系统设置）",
        flush=True,
    )
    # 用 subprocess 而不是 os.execve：Windows 上 os.execv 系列拼命令行时
    # **不给带空格的参数加引号**，`D:\Program Files (x86)\...` 会被空格切碎，
    # 实测报 "D:\program: can't open file ...files"。
    # 前台运行 + 继承 stdio，父进程一直等到服务结束 —— 这样用户双击 bat 时
    # 日志照常打在同一个窗口里，也不会因为父进程先退出而丢输出。
    import subprocess  # noqa: PLC0415

    try:
        rc = subprocess.call(argv, env=env)
    except KeyboardInterrupt:
        rc = 0
    except Exception as e:  # noqa: BLE001
        print(f"     ⚠ 换用失败（{e}），继续用当前解释器\n", flush=True)
        return None
    # 子进程（也就是真正的服务）已经退出，本进程的使命结束
    raise SystemExit(rc)


def main():
    ap = argparse.ArgumentParser(description="小说下载器")
    ap.add_argument("--host", default="0.0.0.0", help="监听地址（0.0.0.0 表示局域网可访问）")
    ap.add_argument("--port", type=int, default=8000, help="端口")
    ap.add_argument("--no-check", action="store_true",
                    help="跳过防火墙检测（启动快一点）")
    ap.add_argument("--no-borrow", action="store_true",
                    help="不借用其它已被防火墙放行的 Python 解释器")
    ap.add_argument("--no-sched", action="store_true",
                    help="不启动榜单定时刷新（调试用；等价于 NOVEL_SCHED=0）")
    ap.add_argument("--sched-interval", type=float, default=None,
                    help="榜单刷新间隔秒数（默认 1800，即 30 分钟）")
    args = ap.parse_args()

    # 先借解释器（会 execv 替换自己），再做后面的检测和启动
    if args.host == "0.0.0.0" and not args.no_check and not args.no_borrow:
        _borrow_exe(args.port)

    # 告诉安全层「这台服务是不是挂在网络上」。这一步不能省：
    # 绑 0.0.0.0 意味着同网段/公网都能连进来，此时「来源 IP 不是回环」
    # 就必须带令牌 —— 否则云服务器直接暴露端口时，任何人扫到都能读书架。
    # 绑 127.0.0.1 则只有本机能连，维持原来的宽松行为。
    try:
        from app import security as _sec
        _sec.set_bind_exposed(args.host in ("0.0.0.0", "::", "0"))
    except Exception:  # noqa: BLE001  安全层加载失败不该拦住启动
        pass

    print(_banner(args.host, args.port), flush=True)
    if args.host == "0.0.0.0" and not args.no_check:
        try:
            print(_firewall_hint(args.port), flush=True)
        except Exception as e:  # noqa: BLE001
            # 检测本身失败不该拦住启动 —— 这只是个提示
            print(f"  （防火墙检测跳过：{e}）", flush=True)
        print("=" * 60, flush=True)

    # 榜单定时刷新：让「发现页」打开就是热的，而不是让用户等联网抓取。
    # 放在 uvicorn.run 之前 —— 它是 daemon 线程，主进程一停它跟着走，
    # 不需要额外的退出钩子。首轮延迟 60s，错开启动期的自检和端口就绪。
    if args.no_sched:
        os.environ["NOVEL_SCHED"] = "0"
    try:
        from app import sched as _sched
        _sched.start(interval=args.sched_interval)
    except Exception as e:  # noqa: BLE001  定时器起不来不该拦住服务
        print(f"  （榜单定时刷新未启动：{e}）", flush=True)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    sys.exit(main())
