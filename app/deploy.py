"""一键部署：把「项目打包」和「安装脚本」直接由本机服务提供出去。

为什么要有这个模块
------------------
原来的流程是：本机 `pack.py` 打一个 tar.gz → 用户 `scp` 传到服务器 →
在服务器上解压 → 跑脚本。四步里有两步（scp、解压）对不懂 Linux 的人
是纯负担，而且 `scp` 还要知道服务器的 IP、密码、往哪个目录放。

换成一个更省事的路子：**让已经跑起来的本机服务，自己把项目吐出去**。
服务器上只要一条 curl，把 tar.gz 拉过去就地解开就行：

    curl -fsSL http://<本机IP>:8000/api/deploy/tar | tar xz
    cd noveldock && bash tools/oneclick.sh

这样用户需要知道的只有一件事：「在服务器上粘这一行」。
IP 和端口由本机服务自己知道、自己填进命令里。

安全
----
这个包**含访问令牌**（cache/auth.json），所以：
  · 只在**局域网直连**时给（`security.is_local` 那条判据）
  · 从公网/隧道进来的请求一律 403 —— 不能让人顺着隧道把整个项目拉走
  · 走同样那层限流
"""
from __future__ import annotations

import io
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 与 tools/pack.py 保持同一套排除规则。
# 两处各写一份是不得已 —— 一个在 serve 进程里、一个在命令行，
# 但**规则本身必须一致**，否则「本机装的」和「传上去的」内容会不一样。
# 所以这里从 pack.py 里读，而不是重写一遍：
try:
    import sys

    sys.path.insert(0, str(ROOT / "tools"))
    from pack import EXCLUDE_DIRS, EXCLUDE_FILES, is_excluded  # type: ignore
except Exception:  # noqa: BLE001
    # pack.py 不在（比如只部署了 app/），退回到内联的最小规则。
    # 宁可排除得少，也不要因为 import 失败就整包打不出来。
    EXCLUDE_DIRS = {".venv", "__pycache__", "shots", "logs", ".git", "dist",
                    "tools/bin"}
    EXCLUDE_FILES = {"cache/serve.pid", ".run.log", "probe_result.json"}

    def is_excluded(rel: Path) -> bool:  # type: ignore[misc]
        parts = rel.parts
        for i in range(len(parts)):
            if parts[i] in EXCLUDE_DIRS:
                return True
        return str(rel).replace("\\", "/") in EXCLUDE_FILES


def build_tar() -> tuple[bytes, int, int]:
    """在内存里打一个 tar.gz，返回 (字节内容, 文件数, 解压后字节数)。

    为什么用 gzip 而不是 zip：服务器上是 Linux，
    `tar xz` 一条命令就解开了，不用先装 unzip。
    """
    buf = io.BytesIO()
    n = 0
    raw = 0
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in sorted(ROOT.rglob("*")):
            rel = p.relative_to(ROOT)
            if is_excluded(rel) or p.is_dir():
                continue
            # 统一加一层 noveldock/，解压后不会把文件撒得到处都是
            tar.add(p, arcname=str(Path("noveldock") / rel))
            n += 1
            try:
                raw += p.stat().st_size
            except OSError:
                pass
    return buf.getvalue(), n, raw


_cache: dict = {}
_TTL = 120.0


def cached_tar() -> tuple[bytes, int, int]:
    """缓存 2 分钟。

    打一次包要遍历几千个文件（实测约 1~2 秒），而服务器那边
    curl 可能重试。缓存能避免重试变成重复劳动。
    TTL 不设太长：书架里新加了书，用户重新拉一次应该能拿到。
    """
    now = time.time()
    hit = _cache.get("data")
    if hit and now - _cache.get("ts", 0) < _TTL:
        return hit
    data = build_tar()
    _cache["data"] = data
    _cache["ts"] = now
    return data


def deploy_command(base: str, token: str = "") -> str:
    """给用户照着粘的那一整段命令。

    刻意做成「curl 一个 .sh 然后 bash」而不是「curl tar 再解压再 cd」——
    用户只复制一次、只理解"这是安装"，不用知道中间发生了什么。
    那个 .sh（/api/deploy/sh）里才是真正的解压+安装。

    `base` 是**这台服务对外可用的基地址**（形如
    `http://192.168.31.99:8000` 或 `https://xxx.trycloudflare.com`）。
    注意它来自"请求是从哪进来的"，不是 local_ip() —— 见 base_url()。
    """
    q = f"?t={token}" if token else ""
    return f"curl -fsSL {base}/api/deploy/sh{q} | bash"


def base_url(scheme: str, host: str) -> str:
    """算出「这台服务现在对外可用的基地址」。

    为什么不能直接用 local_ip()
    --------------------------
    这是个踩过的真 bug：服务器从隧道地址
    `https://xxx.trycloudflare.com` 请求脚本，脚本里却写死了
    `http://192.168.31.99:8000`（local_ip 拿到的局域网地址）——
    服务器在公网上，那个地址它永远连不上，于是下载超时。

    正确做法是**用请求自己的 Host 头**：请求是从哪儿进来的，
    就让脚本从哪儿拉包。这样局域网访问就给局域网地址、
    隧道访问就给隧道地址，两边都对。

    scheme 的判断：cloudflare 隧道是 https，而它在本地是 http。
    看 Host 里有没有 `trycloudflare`，有就是隧道（走 https）。
    """
    h = (host or "").strip()
    if not h:
        return ""
    # 隧道域名一定带 trycloudflare；它是公网 https
    sch = "https" if "trycloudflare" in h.lower() else scheme
    return f"{sch}://{h}"


def bootstrap_script(base: str, token: str = "") -> str:
    """服务器上真正执行的那段 bash。

    它要干的事：把 tar 拉下来 → 解压 → 进目录 → 交给 oneclick.sh。
    写成脚本而不是一段 `curl|tar xz && cd && bash`，是因为：
      · 用户可以 `cat` 出来看懂每一步在干嘛（透明）
      · 出错时能明确停在哪一步、打印什么
      · 需要判断"目录已存在"这种分支，一行 `&&` 串不下

    `base` 见 base_url()：必须是**从请求推断出来的对外地址**，
    不能是 local_ip()。
    """
    q = f"?t={token}" if token else ""
    return f"""#!/usr/bin/env bash
# 噜妹书院 · 从本机服务拉取并安装
#
# 这一段是 `curl ... | bash` 真正执行的内容。它做的事：
#   1. 把项目包下载到临时文件
#   2. 解开
#   3. 跑一键安装脚本
#
# 你可以先 `curl -fsSL <同一个地址> -o setup.sh` 存下来看一眼再跑。
set -euo pipefail

BASE="{base}"
SRC="$BASE/api/deploy/tar{q}"
DIR="${{HOME}}/noveldock"
TMP="$(mktemp -t noveldock-XXXXXX.tar.gz)"

printf '\\033[1;36m  下载项目包...\\033[0m\\n'
printf '  来源 %s\\n' "$SRC"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$SRC" -o "$TMP"
elif command -v wget >/dev/null 2>&1; then
  wget -q -O "$TMP" "$SRC"
else
  printf '\\033[1;31m  这台机器既没有 curl 也没有 wget。\\033[0m\\n'
  printf '  先装一个： sudo apt update && sudo apt install -y curl\\n'
  exit 1
fi

SIZE="$(wc -c < "$TMP" | tr -d ' ')"
if [ "$SIZE" -lt 100000 ]; then
  printf '\\033[1;31m  下载的东西不对劲（只有 %s 字节）。\\033[0m\\n' "$SIZE"
  printf '  多半是拿不到服务地址。确认：电脑上那个程序还开着吗？\\n'
  cat "$TMP" | head -5
  exit 1
fi
printf '  拿到 %s KB\\n' "$((SIZE / 1024))"

printf '\\033[1;36m  解压到 %s ...\\033[0m\\n' "$DIR"
mkdir -p "$(dirname "$DIR")"
# 已经装过就整个换掉：升级场景下留着旧的没意义，
# 而且数据（library/downloads）在包里的那份才是用户最新的。
rm -rf "$DIR"
tar xzf "$TMP" -C "$(dirname "$DIR")"
rm -f "$TMP"

cd "$DIR"
printf '\\033[1;36m  开始安装...\\033[0m\\n\\n'
exec bash tools/oneclick.sh
"""
