"""局域网访问：本机地址 + 防火墙是否放行。

为什么单独一个模块
------------------
「手机打不开」这件事，九成不是服务的问题，而是 Windows 防火墙把入站
请求丢了 —— 而这个失败**没有任何提示**：电脑上 `127.0.0.1:8000` 一切正常，
手机上就是转圈。用户只会以为是软件坏了。

更坑的是 Windows 的「Python」放行规则是**按 exe 路径**绑定的。
用 WorkBuddy 自带 Python 放过行，不代表项目 venv 里的
`.venv\\Scripts\\python.exe` 也被放行 —— 它俩是两个不同的可执行文件。
实测这台机器上就是如此：有一条 `Python` 放行规则，但它指向
`D:\\Program Files (x86)\\WorkBuddy\\resources\\vendor\\python\\python.exe`，
对本项目**一点用都没有**。

所以启动时主动查一次，把「手机连不上」从玄学变成一句能照着做的提示。
"""
from __future__ import annotations

import re
import socket
import subprocess
import sys
import urllib.request
from typing import Optional


def lan_ip() -> str:
    """本机在局域网里的地址。

    用「连一下外网地址再看自己用的哪个网卡」这个技巧，而不是遍历网卡 ——
    有 VPN / WSL / Hyper-V 虚拟网卡时，遍历很容易挑到 192.168.32.1 这种
    手机根本路由不到的地址。
    """
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        return "127.0.0.1"
    finally:
        if s is not None:
            s.close()


def is_private(ip: str) -> bool:
    """是不是内网地址（RFC1918 + 回环 + 链路本地）。

    为什么需要：云服务器上 lan_ip() 拿到的是**内网 IP**（腾讯云常见
    10.x.x.x）。横幅要是照着它打印「手机访问 http://10.0.0.5:8000」，
    用户在外面拿手机试半天也连不上 —— 那个地址只在云厂商的内网里有效。
    所以要识别出来，换成公网 IP 的说法。
    """
    try:
        parts = [int(x) for x in ip.split(".")]
    except Exception:  # noqa: BLE001
        return False
    if len(parts) != 4:
        return False
    a, b = parts[0], parts[1]
    if a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 192 and b == 168:
        return True
    if a == 127:
        return True
    if a == 169 and b == 254:
        return True
    return False


def looks_like_cloud(ip: str) -> bool:
    """更像"云服务器内网"还是"家里路由器分的内网"？

    这两者都是 private，但横幅该说的话完全不同：
      · 192.168.x.x → 家用/公司局域网，说「手机连同一个 WiFi 用这个」
      · 10.x / 172.16-31.x → 云厂商的内网段居多（腾讯云、阿里云常用 10.x）

    只靠网段猜当然不完美（公司内网也常用 10.x），但**猜错的代价不对称**：
    对家里用户多说一句"这也是内网地址"没什么损失，
    对云服务器用户少说一句"外面连不上"则会让他白折腾很久。
    所以宁可偏向报。

    注意不要用 is_private 直接判断 —— 192.168 也是 private，
    那会把你家里电脑也当成云服务器（多打一堆没用的话）。
    """
    try:
        a, b = [int(x) for x in ip.split(".")[:2]]
    except Exception:  # noqa: BLE001
        return False
    if a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    return False


def public_ip(timeout: float = 3.0) -> str:
    """问外面的服务「我的公网 IP 是什么」。

    只在需要的时候调（云服务器上），而且**必须容错**：这个请求要走外网，
    在国内网络下不一定通。拿不到就返回空串，让调用方退回原来的说法，
    绝不因为拿不到公网 IP 就把启动流程卡住。

    多试几家：单一服务挂了/被墙了都还有别的兜底。
    """
    for url in (
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
        "https://ipinfo.io/ip",
    ):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                ip = r.read(64).decode("utf-8", "replace").strip()
            # 简单校验：四段数字。别把一整个 HTML 错误页当 IP 打出去。
            if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", ip):
                return ip
        except Exception:  # noqa: BLE001
            continue
    return ""


def _run(cmd: str) -> str:
    """跑一条命令并把输出解成文本。

    netsh 在中文 Windows 上按 UTF-8 输出，英文版/旧版可能是 GBK，
    所以两把都试一遍，别让一行乱码把整个检测搞崩。
    """
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, timeout=15)
    except Exception:  # noqa: BLE001
        return ""
    raw = p.stdout or b""
    for enc in ("utf-8", "gbk"):
        try:
            t = raw.decode(enc)
        except Exception:  # noqa: BLE001
            continue
        if "\ufffd" not in t:
            return t
    return raw.decode("utf-8", errors="replace")


def is_admin() -> bool:
    """当前进程有没有管理员权限（加防火墙规则要这个）。"""
    if sys.platform != "win32":
        try:
            import os  # noqa: PLC0415

            return os.geteuid() == 0
        except Exception:  # noqa: BLE001
            return False
    try:
        return subprocess.run("net session", shell=True,
                              capture_output=True, timeout=10).returncode == 0
    except Exception:  # noqa: BLE001
        return False


# netsh 的输出里，字段名后面跟一堆空格，偶尔还有全角空格（\u3000）
_PAD = " \t\u3000"

# 字段名要**中英双认**。这不是过度设计：netsh 在控制台代码页为 65001 时
# 会退回英文输出（实测：chcp 936 → 「状态 启用」，chcp 65001 → 「State ON」），
# 而 start.bat 里正好设了 chcp 65001。只认中文的话，解析会一条规则都找不到，
# 于是明明放行了还一直提示「没放行」。
_FIELDS: dict[str, tuple[str, ...]] = {
    "name": ("规则名称", "Rule Name"),
    "enabled": ("已启用", "Enabled"),
    "profiles": ("配置文件", "Profiles"),
    "protocol": ("协议", "Protocol"),
    "port": ("本地端口", "LocalPort"),
    "program": ("程序", "Program"),
    "action": ("操作", "Action"),
}

# 「开启」的各种写法
_TRUE = {"是", "启用", "开启", "ON", "On", "on", "Yes", "YES", "True", "1"}
# 「允许」的各种写法
_ALLOW = {"允许", "Allow", "ALLOW", "allow"}

# 配置文件统一成中文，好比较（规则里写的是 Public，当前网络读到的是 公用）
_PROFILE_CANON = {
    "域": "域", "专用": "专用", "公用": "公用",
    "Domain": "域", "Private": "专用", "Public": "公用",
}
_ANY = {"任何", "Any", "ANY", "any", ""}


def _canon_profile(s: str) -> str:
    return _PROFILE_CANON.get(s.strip(_PAD), "")


def _is_on(v: str) -> bool:
    return v.strip(_PAD) in _TRUE


def _is_allow(v: str) -> bool:
    return v.strip(_PAD) in _ALLOW


def _is_any(v: str) -> bool:
    return v.strip(_PAD) in _ANY


def _grab(block: list[str], key: str) -> str:
    """从规则块里取值，中英文字段名都认。

    只按**第一个**冒号切 —— 程序路径里全是冒号（`D:\\a\\b.exe`），
    用 rsplit 或按所有冒号切都会把路径切碎。
    """
    names = _FIELDS.get(key, (key,))
    for line in block:
        s = line.strip(_PAD)
        for n in names:
            if s.startswith(n + ":") or s.startswith(n + "："):
                return s.split(":", 1)[-1].strip(_PAD)
    return ""


def _split_rules(text: str) -> list[dict]:
    blocks: list[list[str]] = []
    cur: list[str] = []
    for line in text.splitlines():
        head = line.strip(_PAD)
        if head.startswith("规则名称") or head.startswith("Rule Name"):
            if cur:
                blocks.append(cur)
            cur = [line]
        elif cur:
            cur.append(line)
    if cur:
        blocks.append(cur)

    out = []
    for b in blocks:
        d = {k: _grab(b, k) for k in _FIELDS}
        if d["name"]:
            out.append(d)
    return out


def _port_hit(spec: str, port: int) -> bool:
    """规则的「本地端口」是否覆盖 port。

    spec 可能是 `8000`、`8000,8001`、`8000-8010`、或 `任何` / `Any`。
    """
    if not spec:
        return False
    for part in spec.split(","):
        part = part.strip(_PAD)
        if _is_any(part):
            return True
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if m and int(m.group(1)) <= port <= int(m.group(2)):
            return True
        if part.isdigit() and int(part) == port:
            return True
    return False


def _profile_hit(rule_profiles: str, current: str) -> bool:
    """规则是否作用于**当前**网络配置文件。

    当前网络是「公用」时，一条只写了「专用」的规则是不生效的 ——
    这是很多人加了规则还是连不上的原因。规则里可能写 `Public`，
    而当前网络读到的是 `公用`，所以两边都要归一化再比。
    """
    if not rule_profiles or not current:
        return True
    if _is_any(rule_profiles):
        return True
    want = _canon_profile(current) or current
    for p in re.split(r"[,，]", rule_profiles):
        p = p.strip(_PAD)
        if not p:
            continue
        got = _canon_profile(p)
        if got and (got == want or got in want or want in got):
            return True
    return False


_PROFILE_HEAD = re.compile(r"^(域|专用|公用)")
_PROFILE_HEAD_EN = re.compile(r"^(Domain|Private|Public)\b", re.I)


def _profile_of(line: str) -> str:
    """从「域配置文件 设置:」这类标题行里认出配置文件。中英文都认。"""
    s = line.strip(_PAD)
    m = _PROFILE_HEAD.match(s)
    if m and "配置文件" in s:
        return m.group(1)
    m = _PROFILE_HEAD_EN.match(s)
    if m:
        return _PROFILE_CANON.get(m.group(1).capitalize(), "")
    return ""


def _profiles_state() -> dict[str, bool]:
    """三个配置文件各自的开关状态。值只返回 bool，别再比字符串了 ——
    英文系统给的是 `ON`，比 `启用` 会漏判，进而错报「防火墙关着」。"""
    txt = _run("netsh advfirewall show allprofiles state")
    out: dict[str, bool] = {}
    cur = ""
    for line in txt.splitlines():
        s = line.strip(_PAD)
        if not s:
            continue
        head = _profile_of(s)
        if head:
            cur = head
            continue
        if cur and (s.startswith("状态") or s.startswith("State")):
            val = s.replace("状态", "").replace("State", "").strip(_PAD)
            out[cur] = _is_on(val)
            cur = ""
    return out


def current_profile() -> str:
    """当前生效的配置文件：域 / 专用 / 公用。"""
    txt = _run("netsh advfirewall show currentprofile")
    for line in txt.splitlines():
        p = _profile_of(line)
        if p:
            return p
    return ""


def _find_rule(rules: list[dict], port: int, current: str,
               exe: str) -> Optional[dict]:
    """在规则里找**第一条**能放行 (port, current, exe) 的。

    抽出来是因为它有两个用途：判断「现在能不能连」，以及
    `find_allowed_python()` 要用同一套判据反推「哪个解释器已经被放行了」。
    两处判据必须一模一样，否则会出现「提示说能用、实际连不上」。
    """
    for r in rules:
        if not _is_allow(r["action"]):
            continue
        if not _is_on(r["enabled"]):
            continue
        if not _profile_hit(r["profiles"], current):
            continue
        if r["protocol"] not in ("TCP", "任何", "Any"):
            continue
        if not _port_hit(r["port"], port):
            continue
        prog = r["program"]
        # 规则要么不限程序，要么恰好指到我们这个 exe。
        # 「指向别的 python.exe」不算 —— 这正是最常见的假阳性。
        if prog and not _is_any(prog):
            if not exe or prog.strip(_PAD).lower() != exe.lower():
                continue
        return r
    return None


def _inbound_rules() -> list[dict]:
    return _split_rules(
        _run("netsh advfirewall firewall show rule name=all dir=in verbose"))


def _exe_of(path: str) -> str:
    import os  # noqa: PLC0415

    try:
        return os.path.abspath(path or "")
    except Exception:  # noqa: BLE001
        return path or ""


def find_allowed_python(port: int) -> Optional[dict]:
    """找一个**已经被防火墙放行**的 python 解释器，用来跑本项目。

    为什么要有这个：Windows 的放行规则是按 **exe 路径**绑定的，
    而用户机器上往往已经有一条指向**别的** python 的规则
    （装了某些 IDE / 工具就会自带）。既然那条规则允许它接收入站连接，
    那用它来跑服务就**不用提权、也不用改系统配置**。

    只考虑版本和当前解释器一致的（ABI 要对得上，否则 C 扩展会崩）。
    """
    if sys.platform != "win32":
        return None
    try:
        import os  # noqa: PLC0415

        import subprocess as _sp  # noqa: PLC0415

        have = tuple(sys.version_info[:2])
        cur_now = current_profile()
        for r in _inbound_rules():
            if not _is_allow(r["action"]) or not _is_on(r["enabled"]):
                continue
            if not _profile_hit(r["profiles"], cur_now):
                continue
            if r["protocol"] != "TCP":
                continue
            prog = r["program"].strip(_PAD)
            if not prog or _is_any(prog):
                continue
            if not prog.lower().endswith("python.exe"):
                continue
            if not os.path.isfile(prog):
                continue
            if _exe_of(prog).lower() == _exe_of(sys.executable).lower():
                continue  # 就是自己，没意义
            # 规则必须能放行这个端口（大部分这类规则是「任何端口」）
            if not _port_hit(r["port"], port):
                continue
            # 版本必须一致，否则 cp3xx 的 .pyd 加载不了
            try:
                out = _sp.run([prog, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
                              capture_output=True, timeout=20)
                ver = out.stdout.decode("ascii", errors="ignore").strip()
            except Exception:  # noqa: BLE001
                continue
            if ver != f"{have[0]}.{have[1]}":
                continue
            return {"exe": prog, "rule": r["name"], "version": ver}
    except Exception:  # noqa: BLE001
        return None
    return None


def check(port: int, exe: str = "") -> dict:
    """检查「手机能不能连上这个端口」，并给出可执行的建议。

    `exe` 留空时用当前进程的解释器；传别的路径可以问
    「如果换成这个解释器跑，会不会被放行」。

    返回 dict：
        lan / port / url        局域网地址与访问链接
        rule_found / rule_name  有没有规则放行这个端口
        profiles / current      配置文件开关与当前所处
        admin                   当前进程是否管理员
        ok                      手机现在是否能连上
        advice                  不行的话，照着做什么
    """
    ip = lan_ip()
    info: dict = {
        "lan": ip,
        "port": port,
        "url": f"http://{ip}:{port}",
        "rule_found": False,
        "rule_name": "",
        "profiles": {},
        "current": "",
        "admin": is_admin(),
        "ok": False,
        "advice": "",
    }

    if sys.platform != "win32":
        # macOS / Linux 上大多是「服务监听 + 同网段」就能通，
        # 少数发行版有 ufw/firewalld，这里不强猜。
        info["ok"] = True
        return info

    self_exe = _exe_of(exe or sys.executable or "")

    info["profiles"] = _profiles_state()
    info["current"] = current_profile()

    hit = _find_rule(_inbound_rules(), port, info["current"], self_exe)
    if hit:
        info["rule_found"] = True
        info["rule_name"] = hit["name"]

    info["ok"] = info["rule_found"]
    if not info["ok"]:
        cmd = (f'netsh advfirewall firewall add rule name="NovelDock {port}" '
               f"dir=in action=allow protocol=TCP localport={port}")
        info["advice"] = (
            "Windows 防火墙没有放行入站端口，手机连不上。\n"
            "用**管理员**身份打开 PowerShell / cmd，粘这一行：\n"
            f"    {cmd}\n"
            "（只放行这一个端口，不需要关掉防火墙）"
        )
    return info


def open_port(port: int, name: Optional[str] = None) -> tuple[bool, str]:
    """加一条入站放行规则。需要管理员权限。

    只放行端口、不动防火墙总开关 —— 为了一个下载器把防火墙关掉是
    很糟糕的建议，等于把整台机器的入站面全敞开了。
    """
    if sys.platform != "win32":
        return False, "这个帮助函数目前只处理 Windows 防火墙"
    if not is_admin():
        return False, "需要管理员权限：请用「管理员身份」重开 PowerShell / cmd"
    label = name or f"NovelDock {port}"
    cmd = (f'netsh advfirewall firewall add rule name="{label}" '
           f"dir=in action=allow protocol=TCP localport={port}")
    out = _run(cmd)
    ok = "确定" in out or "Ok" in out or "ok" in out
    return ok, out.strip() or cmd
