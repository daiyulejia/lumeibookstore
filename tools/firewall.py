"""防火墙自助工具：看看手机能不能连上，不能就放行。

手机上打不开这个下载器时，需要排查的其实只有两件事：
  1. 手机和电脑是不是同一个 WiFi
  2. Windows 防火墙有没有放行这个端口

第 2 条是最容易被忽略的，而且失败时**没有任何提示** ——
电脑上 127.0.0.1 一切正常，手机上就是转圈。这个脚本把它说清楚。

用法：
    python tools/firewall.py            # 体检
    python tools/firewall.py --open     # 放行（需要用管理员身份运行）
    python tools/firewall.py --port 9000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.netinfo import check, find_allowed_python, is_admin, open_port  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--open", action="store_true", help="加一条入站放行规则（需管理员）")
    args = ap.parse_args()

    if args.open:
        if not is_admin():
            print("❌ 需要管理员权限。")
            print("   最简单：直接双击项目根目录的 open-firewall.bat（它会自己申请提权）")
            print("   或者：开始菜单搜 PowerShell → 右键 →「以管理员身份运行」，然后执行：")
            print(f"     cd \"{Path(__file__).resolve().parent.parent}\"")
            print(f"     .venv\\Scripts\\python.exe tools\\firewall.py --open --port {args.port}")
            return 2
        ok, msg = open_port(args.port)
        print(("✅ 已放行 " if ok else "❌ 放行失败 ") + f"{args.port} 端口")
        print(msg)
        # 立刻复验一次：netsh 说「确定」不等于规则真的生效
        # （比如名字重复、或者只对别的网络配置文件生效）
        after = check(args.port)
        print()
        if after["ok"]:
            print(f"✅ 复验通过：规则「{after['rule_name']}」已覆盖 {args.port} 端口")
            print(f"   手机上打开 http://{after['lan']}:{after['port']} 就行")
            if after["current"] != "专用" and after["current"] != "域":
                print(f"   （当前网络是「{after['current']}」，规则已包含这个配置文件，没问题）")
        else:
            print(f"⚠ 复验没通过：还是没找到覆盖 {args.port} 的规则。")
            print(f"   当前网络类型「{after['current']}」，检查一下规则是不是只勾了别的配置文件。")
        return 0 if ok else 1

    info = check(args.port)

    print("=" * 56)
    print("  局域网访问体检")
    print("=" * 56)
    print(f"  本机地址 : {info['lan']}")
    print(f"  手机访问 : http://{info['lan']}:{info['port']}")
    print()
    print(f"  当前网络 : {info['current'] or '未知'}（只有「专用」和「公用」会影响入站规则）")
    st = info["profiles"] or {}
    if st:
        # 值统一是 bool，别拿字符串比 —— netsh 在 65001 代码页下输出的是 ON
        print("  防火墙   : " + " · ".join(f"{k}{'启用' if v else '关闭'}" for k, v in st.items()))
    else:
        print("  防火墙   : 未知")
    print()
    if info["ok"]:
        print(f"  ✅ 已放行：规则「{info['rule_name']}」覆盖了 {info['port']} 端口")
        print("     手机上打开上面那个链接即可。（连不上先确认是同一个 WiFi）")
    else:
        print(f"  ❌ 当前解释器没有被放行 → 手机连不上 {info['port']} 端口")
        print()
        # 先看有没有「不用提权」的路子：机器上可能已经有别的 python
        # 在白名单里（装了 IDE / 工具常自带），借它跑就行。
        alt = find_allowed_python(args.port) if sys.platform == "win32" else None
        if alt:
            print("     ✅ 不用提权，也不用改系统设置 —— 有这个现成的：")
            print(f"        {alt['exe']}")
            print(f"        （已命中放行规则「{alt['rule']}」，Python {alt['version']}）")
            print("        直接启动就会自动用它来跑：")
            print("          .venv\\Scripts\\python.exe run.py")
            print("        （或双击 start.bat。想强制用当前解释器加 --no-borrow。）")
            print()
            print("     如果你更想按端口放行（推荐，一劳永逸）：")
        else:
            print("     修法一（推荐，一条命令）：以管理员身份打开 PowerShell 后执行")
        print(f"       .venv\\Scripts\\python.exe tools\\firewall.py --open --port {info['port']}")
        print("       或直接双击 open-firewall.bat（会自己申请提权）")
        print()
        print("     修法二（图形界面）：")
        print("       Win+R → 输入 wf.msc → 入站规则 → 新建规则")
        print(f"       → 端口 → TCP → 特定本地端口 {info['port']} → 允许连接 → 三个配置文件都勾 → 起个名字")
        print()
        print("     为什么「Python」规则常常没用：Windows 的程序放行规则是按")
        print("     **exe 路径**绑定的。那条规则多半指向别的 python.exe，")
        print("     和本项目 venv 里的不是同一个文件。按端口放行才不受路径影响。")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
