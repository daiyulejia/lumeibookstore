#!/usr/bin/env bash
# 在云服务器上一键把「噜妹书院」跑起来。
#
# 为什么要有这个脚本
# ------------------
# 用户没碰过 Linux 命令行。让他照着 README 一条条粘贴 8 条命令，
# 中间任何一步打错（少个空格、大小写、路径不对）都会卡住，
# 而报错信息对新手毫无可读性。把这一串固定动作封成一个脚本：
#   · 要么全成功，要么在某一步明确告诉你"卡在哪、怎么办"
#   · 幂等 —— 重复执行不会把事情搞坏（比如重复加 swap、重复启服务）
#
# 它假设：项目已经在这个目录里了（含 requirements.txt、run.py、tools/）。
#
# 用法：
#   bash tools/setup_linux.sh              # 默认端口 8000
#   bash tools/setup_linux.sh 9000         # 想换端口
set -euo pipefail

PORT="${1:-8000}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m   ! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m   ✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
say "0/6  检查环境"
# ---------------------------------------------------------------------------
[ -f requirements.txt ] || die "这个目录里没有 requirements.txt —— 确认你是在项目根目录下跑的？当前：$HERE"
command -v python3 >/dev/null 2>&1 || die "没装 python3。先跑： sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
PYV="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
ok "python3 = $PYV   目录 = $HERE"

# python3-venv 在很多云镜像上是**单独一个包**，默认没装。
# 不先确认的话，`python3 -m venv` 会在下面报一段很难懂的 ensurepip 错误。
if ! python3 -c 'import venv' >/dev/null 2>&1; then
  die "缺 python3-venv 模块。先跑： sudo apt install -y python3-venv"
fi

# ---------------------------------------------------------------------------
say "1/6  2G 小内存机器：配 swap（有就跳过）"
# ---------------------------------------------------------------------------
# 为什么必须做：2G 内存跑 pip 安装 + 之后常驻服务，很容易在某个瞬间
# 内存打满，然后被内核 OOM killer 直接杀掉进程 —— 表现为"服务莫名其妙
# 就没了"，而且没有明显报错。加 2G swap 是这台机器上性价比最高的一步。
if swapon --show 2>/dev/null | grep -q .; then
  ok "已有 swap，跳过"
else
  warn "没有 swap，正在创建 2G 的 /swapfile"
  if sudo fallocate -l 2G /swapfile 2>/dev/null || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none; then
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile >/dev/null
    sudo swapon /swapfile
    # 写进 fstab 才能在重启后仍然生效
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
    ok "swap 已启用（重启后依然有效）"
  else
    warn "建 swap 失败（磁盘空间不够？）—— 不致命，继续，但 2G 内存可能吃紧"
  fi
fi

# ---------------------------------------------------------------------------
say "2/6  建虚拟环境 + 装依赖"
# ---------------------------------------------------------------------------
if [ -d .venv ] && [ -x .venv/bin/python3 ]; then
  ok "已有 .venv，复用"
else
  # 注意：如果 .venv 是从 Windows 传上来的，里面的 bin/ 是不存在的
  # （Windows 版是 Scripts/），所以这里判 bin/python3 而不是目录存在。
  rm -rf .venv
  python3 -m venv .venv
  ok "已创建 .venv"
fi

.venv/bin/python3 -m pip install --upgrade pip -q
say "   正在装依赖（第一次会慢一点）"
.venv/bin/python3 -m pip install -q -r requirements.txt
ok "依赖装好：$(.venv/bin/python3 -c 'import fastapi,uvicorn,httpx,pypinyin,zhconv;print("5/5 可导入")')"

# ---------------------------------------------------------------------------
say "3/6  放行本机防火墙端口 $PORT"
# ---------------------------------------------------------------------------
# 注意这一步只管**服务器自己**的 ufw。云厂商控制台里的「安全组」
# 是另一道门，脚本改不了，必须你手动去点（README 里有截图级别的说明）。
if command -v ufw >/dev/null 2>&1; then
  if sudo ufw status 2>/dev/null | grep -qi 'Status: active'; then
    sudo ufw allow "$PORT"/tcp >/dev/null 2>&1 && ok "ufw 已放行 TCP $PORT" || warn "ufw 放行失败，手动： sudo ufw allow $PORT/tcp"
  else
    ok "ufw 没启用，本机不拦（真正拦人的是云控制台的「安全组」，别忘）"
  fi
else
  ok "没有 ufw，跳过（老镜像用 iptables / firewalld，一般默认就通）"
fi
warn "**去云控制台「安全组」放行 TCP $PORT** —— 这步脚本替你做不了，最容易漏"

# ---------------------------------------------------------------------------
say "4/6  跑一遍自检（离线测试）"
# ---------------------------------------------------------------------------
FAILED=0
for t in test_registry test_parse test_netinfo test_relevance test_boiler test_service_unit; do
  if .venv/bin/python3 "tools/$t.py" >/tmp/nd_$t.log 2>&1; then
    ok "$t"
  else
    warn "$t 失败（详情 /tmp/nd_$t.log）"
    FAILED=1
  fi
done
[ "$FAILED" = "0" ] || warn "有测试没过。不一定是环境问题，但先看一眼再继续比较稳。"

# ---------------------------------------------------------------------------
say "5/6  装成 systemd 常驻服务"
# ---------------------------------------------------------------------------
.venv/bin/python3 tools/service.py install --port "$PORT" || \
  die "装服务失败。看上面的报错，或 journalctl --user -u noveldock -n 50 --no-pager"

# 热榜定时刷新：单独一个 systemd timer。
# 装不上不算致命 —— 服务里的进程内调度器还在，只是少一层系统级兜底，
# 所以这里 warn 而不 die，别让一个"锦上添花"的东西挡住主服务上线。
say "5.5/6  装热榜定时刷新（systemd timer）"
.venv/bin/python3 tools/service.py install-ranks --port "$PORT" || \
  warn "热榜定时刷新没装上（不影响使用，服务内也会自动刷）。"

# ---------------------------------------------------------------------------
say "6/6  等它起来，然后告诉你地址"
# ---------------------------------------------------------------------------
# 这一步刻意做得比"打印个地址"重：用户不懂 Linux，他没法自己判断
# "到底通没通"。所以脚本要**替他判断完**，最后只留一句能照做的话。
sleep 4

LOCAL_OK=0
if curl -s -o /dev/null --noproxy '*' --max-time 8 "http://127.0.0.1:$PORT/"; then
  LOCAL_OK=1
fi

PUB_IP="$(curl -s --noproxy '*' --max-time 6 https://api.ipify.org 2>/dev/null || true)"
case "$PUB_IP" in
  *[!0-9.]*|"") PUB_IP="" ;;
esac

EXT_OK=0
if [ -n "$PUB_IP" ]; then
  # 从"外网视角"再测一次：这一步等于替用户验证了安全组到底放行没有。
  # 从服务器自己回连自己的公网 IP，走的是外网路径，所以能测出安全组。
  if curl -s -o /dev/null --noproxy '*' --max-time 10 "http://$PUB_IP:$PORT/"; then
    EXT_OK=1
  fi
fi

TOKEN="$(.venv/bin/python3 -c 'import sys;sys.path.insert(0,".");from app import security;print(security.token())' 2>/dev/null || true)"

echo
printf '\033[1m────────────────────────────────────────────────\033[0m\n'
if [ "$LOCAL_OK" = "1" ] && [ "$EXT_OK" = "1" ]; then
  printf '\033[1;32m  全部就绪。手机现在就打开这个地址：\033[0m\n\n'
  printf '\033[1;36m      http://%s:%s?t=%s\033[0m\n\n' "$PUB_IP" "$PORT" "$TOKEN"
  printf '  （整条链接都带着钥匙，收藏它就行）\n'
  printf '\033[1m────────────────────────────────────────────────\033[0m\n'
elif [ "$LOCAL_OK" = "1" ]; then
  printf '\033[1;33m  服务本身是好的（本机能打开），但外网还没通。\033[0m\n\n'
  printf '  九成是**安全组**没放行 —— 这是唯一一步脚本替你做不了的事：\n'
  printf '    · 打开腾讯云控制台 → 你这台服务器 → 「安全组」\n'
  printf '    · 加一条入站规则：协议 TCP，端口 %s，来源 0.0.0.0/0，允许\n' "$PORT"
  if [ -n "$PUB_IP" ]; then
    printf '\n  放行之后再打开：\n\n'
    printf '\033[1;36m      http://%s:%s?t=%s\033[0m\n' "$PUB_IP" "$PORT" "$TOKEN"
  fi
  printf '\n  放行完不用重启任何东西，直接刷手机就行。\n'
  printf '\033[1m────────────────────────────────────────────────\033[0m\n'
else
  printf '\033[1;31m  服务没起来。把下面这段整个发给我：\033[0m\n\n'
  journalctl --user -u noveldock -n 25 --no-pager 2>/dev/null \
    | sed 's/^/      /' || echo "      （读不到日志）"
  printf '\033[1m────────────────────────────────────────────────\033[0m\n'
fi

echo
.venv/bin/python3 tools/service.py status --port "$PORT" 2>/dev/null || true
echo
echo "  常用（你一般用不到，记不住也没关系）："
echo "    看日志   journalctl --user -u noveldock -f"
echo "    重启     .venv/bin/python3 tools/service.py stop && .venv/bin/python3 tools/service.py start"
echo "  这台机器重启后它会自己起来，不用管。"

