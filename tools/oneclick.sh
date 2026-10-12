#!/usr/bin/env bash
# 一条命令装完。给「不想碰 Linux」的人用。
#
# 用法（在腾讯云控制台的网页终端里，或者 ssh 进去之后，粘这一整行）：
#
#   curl -fsSL http://<你的电脑局域网IP>:8000/api/deploy.sh | bash
#
# 或者项目已经在服务器上了，直接：
#
#   bash tools/oneclick.sh
#
# 它做什么
# --------
# 假设当前目录（或脚本所在目录）已经是项目根。整件事封成一个脚本，
# 是为了让人**只记一条命令**，而不是记 8 条、还要理解每条在干嘛。
#
# 这个脚本本身不会下载任何东西 —— 项目得先在那台机器上。
# 传项目那一步见 README「部署到云服务器」。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

printf '\033[1;36m  噜妹书院 · 一键安装\033[0m\n\n'
printf '  项目目录：%s\n\n' "$HERE"

# setup_linux.sh 是真正干活的那个。这里只负责把它找出来并调起来 ——
# 不做第二套逻辑，避免两个脚本各说各话（上次 .vbs 就踩过这个坑）。
if [ -x tools/setup_linux.sh ]; then
  exec bash tools/setup_linux.sh "$@"
elif [ -f tools/setup_linux.sh ]; then
  exec bash tools/setup_linux.sh "$@"
fi

printf '\033[1;31m  ✗ 当前目录里没有 tools/setup_linux.sh\033[0m\n\n'
printf '  说明你不在项目根目录，或者项目还没传上来。\n'
printf '  先确认： ls\n'
printf '  应该能看到 README.md、run.py、tools/ 这几样。\n'
exit 1
