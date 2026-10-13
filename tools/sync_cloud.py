"""一键把本机代码同步到云服务器（保留服务器上的书架/令牌/下载）。

为什么要有它
------------
手工流程是：pack → scp → ssh → tar → 挑着覆盖 → 重启。三次里有一次忘了
「别覆盖 library/」，服务器上读过的进度就没了。所以固化成脚本，且**默认
只覆盖代码、绝不动数据目录**。

用法
----
    .venv\\Scripts\\python tools\\sync_cloud.py              # 打包 + 上传 + 升级 + 验证
    .venv\\Scripts\\python tools\\sync_cloud.py --dry-run     # 只打印将要做的事
    .venv\\Scripts\\python tools\\sync_cloud.py --skip-pack   # 复用 dist/noveldock.tar.gz

服务器信息（可被环境变量覆盖）
------------------------------
    NOVELDOCK_HOST      默认 106.53.203.108
    NOVELDOCK_USER      默认 ubuntu
    NOVELDOCK_KEY       默认 ~/.ssh/noveldock_ed25519
    NOVELDOCK_PORT      默认 8000

数据安全
--------
服务器上**保留**这些（不做任何覆盖）：
    library/       书架与章节缓存
    downloads/     导出的 txt
    logs/          日志
    .venv/         虚拟环境
    cache/*.json   令牌 / 榜单 / 来源库 / 书源索引（缺哪个补哪个，已有的不覆盖）
只覆盖：app/  tools/  run.py  requirements.txt  probe.py  README.md  *.bat  *.sh

书架体检
--------
同步时会顺带体检 `library/`：
  * 有 meta.json  → 正常，逐本打印书名 / 已缓存章节 / 总章数 / 状态
  * 无 meta.json  → 判定为孤儿目录（下载中断留下的），**自动隔离**到
                    `~/noveldock.orphan-quarantine/`，不删除。
    （踩过的坑：健康接口只数有 meta.json 的，目录里却躺着没主的残骸，
     导致「书架显示 4 本、`ls library` 却有 5 个目录」对不上。）
`status: toc` 的书是用户正在读的（只抓了目录+前几章），一律保留，绝不清理。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HOST = os.environ.get("NOVELDOCK_HOST", "106.53.203.108")
USER = os.environ.get("NOVELDOCK_USER", "ubuntu")
KEY = os.environ.get("NOVELDOCK_KEY", str(Path.home() / ".ssh" / "noveldock_ed25519"))
PORT = os.environ.get("NOVELDOCK_PORT", "8000")


def _load_token() -> str:
    """取访问令牌。

    **不硬编码**：这个仓库是公开的，令牌写在源码里等于把钥匙挂在网上。
    优先读环境变量，其次读 `cache/auth.json`（运行期生成，已被 .gitignore
    排除，不会进版本库）。两边都没有就返回空串 —— 调用方会跳过需要令牌
    的那一步并提示，而不是偷偷用一个错令牌去 401。
    """
    env = os.environ.get("NOVELDOCK_TOKEN")
    if env:
        return env.strip()
    for p in (ROOT / "cache" / "auth.json", ROOT / "cache" / "token.json"):
        try:
            if p.exists():
                import json
                data = json.loads(p.read_text(encoding="utf-8"))
                for k in ("token", "t", "auth", "key"):
                    v = data.get(k) if isinstance(data, dict) else None
                    if isinstance(v, str) and v.strip():
                        return v.strip()
        except Exception:  # noqa: BLE001
            continue
    return ""


TOKEN = _load_token()

REMOTE_ROOT = f"/home/{USER}/noveldock"
TARBALL = ROOT / "dist" / "noveldock.tar.gz"
REMOTE_TMP = f"/home/{USER}/noveldock_new.tar.gz"

# 远端升级脚本：只覆盖代码，数据目录一概不碰。
# 注意里面的 `$NEW` 指向包内的顶层目录 —— pack.py 打出来的包里
# 自带一层 `noveldock/`，解压后是 noveldock_new/noveldock/，
# 这个坑踩过一次（脚本在 noveldock_new/ 里找 app/ 找不到，静默什么都没做）。
UPGRADE_SH = r"""#!/usr/bin/env bash
set -euo pipefail
ROOT="__ROOT__"
NEW="__NEW__"
TS="$(date +%Y%m%d-%H%M%S)"
# 注：这里的 1/7..7/7 是**服务器内部**的步骤，与本机侧的 1/5..5/5 不是一套编号。

echo "== [服务器 1/7] 备份当前代码 =="
tar czf "$HOME/noveldock.bak-$TS.tar.gz" -C "$(dirname "$ROOT")" \
  --exclude='noveldock/.venv' --exclude='noveldock/logs' \
  --exclude='noveldock/library' --exclude='noveldock/downloads' \
  "noveldock" 2>/dev/null || echo "  (备份警告，继续)"
echo "  备份 -> ~/noveldock.bak-$TS.tar.gz"

echo "== [服务器 2/7] 同步代码（保留数据目录）=="
if [ ! -d "$NEW/app" ]; then
  echo "  x 解压目录里没有 app/： $NEW"
  exit 1
fi
cd "$NEW"
for item in app tools run.py requirements.txt README.md probe.py; do
  if [ -e "$item" ]; then
    rm -rf "$ROOT/$item"
    cp -r "$item" "$ROOT/$item"
    echo "  up $item"
  fi
done
find "$NEW" -maxdepth 1 -type f \( -name '*.bat' -o -name '*.sh' -o -name '*.md' \) \
  -exec cp -f {} "$ROOT/" \; 2>/dev/null || true
echo "  启动脚本与文档已同步"

echo "== [服务器 3/7] 补齐 cache 中缺失的键（不覆盖已有）=="
mkdir -p "$ROOT/cache"
for f in "$NEW"/cache/*.json; do
  [ -e "$f" ] || continue
  b="$(basename "$f")"
  if [ ! -e "$ROOT/cache/$b" ]; then
    cp "$f" "$ROOT/cache/$b"
    echo "  + cache/$b"
  else
    echo "  = cache/$b 保留服务器版本"
  fi
done

echo "== [服务器 4/7] 语法自检 =="
cd "$ROOT"
"$ROOT/.venv/bin/python3" - <<'PY'
import ast, pathlib, sys
bad = []
for p in pathlib.Path("app").rglob("*.py"):
    try:
        ast.parse(p.read_text(encoding="utf-8"))
    except SyntaxError as e:
        bad.append("%s: %s" % (p, e))
if bad:
    print("  语法错误:")
    for b in bad:
        print("   ", b)
    sys.exit(1)
print("  所有 app/*.py 语法 OK")
PY

echo "== [服务器 5/7] 书架体检 =="
# 线上 library/ 里只应有「有 meta.json 的书」。历史上出现过两种垃圾：
#   a) 有 ch/ 但没有 meta.json 的孤儿目录（下载中断留下的，健康接口不认它，
#      但目录一直躺着，肉眼看书架和接口数对不上）；
#   b) 那些 toc 状态的书（只抓了目录+前几章，属于用户正在看的，**不能动**）。
# 所以这里只隔离 a)，b) 一律保留。
"$ROOT/.venv/bin/python3" - "$ROOT" <<'PY'
import json, pathlib, shutil, sys, time
root = pathlib.Path(sys.argv[1])
lib = root / "library"
if not lib.is_dir():
    print("  (无 library 目录，跳过)")
    raise SystemExit(0)
qa = root.parent / "noveldock.orphan-quarantine"
rows, orphans = [], []
for d in sorted(lib.iterdir()):
    if not d.is_dir():
        continue
    meta = d / "meta.json"
    chs = len(list((d / "ch").glob("*.json"))) if (d / "ch").is_dir() else 0
    if meta.is_file():
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
        except Exception:
            m = {}
        rows.append("  - %-14s %-12s %4d/%-5s %s" % (
            d.name, (m.get("title") or "?")[:12], chs,
            m.get("total") or "?", m.get("status") or "?"))
    else:
        orphans.append(d)
for r in rows:
    print(r)
print("  合计 %d 本有 meta.json" % len(rows))
if orphans:
    qa.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    for d in orphans:
        dst = qa / ("%s-%s" % (d.name, ts))
        shutil.move(str(d), str(dst))
        print("  ⚠ 隔离孤儿目录 %s（有 ch/ 无 meta.json）-> %s" % (d.name, dst.name))
else:
    print("  无孤儿目录")
PY

echo "== [服务器 6/6] 重启服务 =="
systemctl --user restart noveldock 2>/dev/null || "$ROOT/.venv/bin/python3" "$ROOT/tools/service.py" start
sleep 7
echo "  服务状态: $(systemctl --user is-active noveldock 2>/dev/null || echo 未知)"
echo "  线上标题: $(grep -o '<title>[^<]*</title>' "$ROOT/app/static/index.html" | head -1)"

echo "== [服务器 7/7] 清理本次残留 =="
# 1) 解压出来的临时目录与上传的包，用完就没价值了（13M 一个，不删会堆积）
rm -rf "$HOME/noveldock_new" "$HOME/noveldock_new.tar.gz"
echo "  已删解压目录与上传包"
# 2) 代码备份只留最近 3 个。每次同步都会生成一个，不留上限的话
#    改十次就攒十个，而真正有用的始终只有最新的和「手工做的那份完整备份」。
#    注意：不碰 noveldock.bak-1011-2303（那是带完整 library+downloads 的回滚基准）。
cd "$HOME"
ls -1t noveldock.bak-*.tar.gz 2>/dev/null | tail -n +4 | while read -r old; do
  rm -f "$old"
  echo "  清理旧备份 $(basename "$old")"
done
echo "  最近备份："
ls -1t noveldock.bak-*.tar.gz 2>/dev/null | head -3 | sed 's/^/    /' || echo "    (无)"

echo "  DONE"
"""


def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """在无代理环境下跑外部命令。

    环境里挂着 http_proxy=http://127.0.0.1:63386，
    不去掉的话 curl 打本地/局域网服务会拿到 502。
    ssh/scp 不受影响，但统一去掉更省心。
    """
    env = dict(os.environ)
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
              "all_proxy", "ALL_PROXY"):
        env.pop(k, None)
    return subprocess.run(cmd, env=env, **kw)


def ssh_base() -> list[str]:
    return [
        "ssh", "-i", KEY,
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=12",
        "-o", "ServerAliveInterval=15",
        f"{USER}@{HOST}",
    ]


def scp_base() -> list[str]:
    return [
        "scp", "-i", KEY,
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=12",
        "-o", "ServerAliveInterval=15",
    ]


def step(n: str, msg: str) -> None:
    print(f"\n\033[1;36m[{n}] {msg}\033[0m")


def run(cmd: list[str], *, tries: int = 1, what: str = "", **kw) -> int:
    """跑一条外部命令，失败时按需重试。

    ⚠ 为什么要重试：ssh/scp 会偶发失手（服务器侧 sshd 瞬时繁忙、
    网络抖动、连接被中途掐断），**跟"代码有问题"完全无关**。
    实测踩到过一次：ship 的 [3/3] 同步直接报「✗ 同步失败」，
    但同一秒手动再跑一遍 sync_cloud 就全绿 —— 纯瞬时故障。
    这种失败最坑的地方是它会让人怀疑自己刚改的代码，
    所以对「幂等的网络动作」自动重试，把噪声挡掉；
    真正的错误（密钥不对、路径不存在）重试几次照样失败，不会被掩盖。
    """
    for i in range(max(1, tries)):
        rc = sh(cmd, **kw).returncode
        if rc == 0:
            return 0
        if i + 1 < tries:
            wait = 3 * (i + 1)
            print(f"  ! {what or cmd[0]} 第 {i+1} 次失败（rc={rc}），"
                  f"{wait}s 后重试…")
            time.sleep(wait)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印，不真做")
    ap.add_argument("--skip-pack", action="store_true", help="复用已有 tar.gz")
    ap.add_argument("--skip-verify", action="store_true", help="跳过最后的线上验证")
    a = ap.parse_args()

    print("噜妹书院 · 同步到云服务器")
    print(f"  目标：{USER}@{HOST}  ->  {REMOTE_ROOT}")
    print(f"  密钥：{KEY}")

    if not Path(KEY).exists():
        print(f"\n✗ 找不到密钥 {KEY}")
        print("  先配一次免密登录，或设 NOVELDOCK_KEY 指向正确的私钥。")
        return 1

    # ---- 1. 打包 ----
    if a.skip_pack and TARBALL.exists():
        step("1/5", f"复用已有包 {TARBALL.name}（{TARBALL.stat().st_size/1e6:.1f} MB）")
    else:
        step("1/5", "打包项目（排除 .venv / 截图 / 字节码）")
        if a.dry_run:
            print("  [dry-run] pack.py --out dist/noveldock.tar.gz")
        else:
            if run([sys.executable, str(ROOT / "tools" / "pack.py"),
                    "--out", str(TARBALL)]) != 0:
                print("✗ 打包失败")
                return 1

    if not TARBALL.exists():
        print(f"✗ 包不存在：{TARBALL}")
        return 1
    print(f"  包大小 {TARBALL.stat().st_size/1e6:.1f} MB")

    # ---- 2. 上传 ----
    step("2/5", "上传到服务器")
    if a.dry_run:
        print(f"  [dry-run] scp {TARBALL} {USER}@{HOST}:{REMOTE_TMP}")
    else:
        if run(scp_base() + [str(TARBALL), f"{USER}@{HOST}:{REMOTE_TMP}"],
               tries=3, what="上传") != 0:
            print("✗ 上传失败（网络？密钥？）")
            return 1
        print("  上传完成")

    # ---- 3. 远端升级 ----
    step("3/5", "服务器上解压 + 只覆盖代码（保留书架/令牌/下载）")
    script = (UPGRADE_SH
              .replace("__ROOT__", REMOTE_ROOT)
              .replace("__NEW__", f"/home/{USER}/noveldock_new/noveldock"))
    if a.dry_run:
        print("  [dry-run] 远端执行 upgrade.sh")
    else:
        # 先把新包解开（脚本自己会 tar xzf 到 noveldock_new）
        prep = (
            f"rm -rf /home/{USER}/noveldock_new && "
            f"mkdir -p /home/{USER}/noveldock_new && "
            f"tar xzf {REMOTE_TMP} -C /home/{USER}/noveldock_new"
        )
        if run(ssh_base() + [prep], tries=2, what="远端解压") != 0:
            print("✗ 解压失败")
            return 1
        r = sh(ssh_base() + ["bash -s"], input=script.encode("utf-8"))
        if r.returncode != 0:
            print("✗ 远端升级失败")
            return 1

    # ---- 4. 验证 ----
    # 资源没全到位要能让整条链以非零退出（见下面 bad 分支的注释）
    verify_failed = False
    if a.skip_verify or a.dry_run:
        step("4/5", "跳过线上验证")
    else:
        step("4/5", "验证线上服务")
        import json
        import re
        import urllib.request
        try:
            url = f"http://{HOST}:{PORT}/api/health?t={TOKEN}"
            with urllib.request.urlopen(url, timeout=20) as resp:
                d = json.load(resp)
            lib = d.get("library", {})
            print(f"  ✓ health ok · 书架 {lib.get('books')} 本 / "
                  f"{lib.get('chapters')} 章 · 来源 {d.get('sources')} 个")
        except Exception as e:  # noqa: BLE001
            print(f"  ! health 检查失败：{e}")
        # 逐本列出来，这样每次同步都能一眼看到书架有没有被动过
        try:
            with urllib.request.urlopen(
                    f"http://{HOST}:{PORT}/api/library?t={TOKEN}",
                    timeout=20) as resp:
                ld = json.load(resp)
            books = ld.get("books", ld) if isinstance(ld, dict) else ld
            for b in books:
                print("    - %-14s %4s/%-5s %s" % (
                    str(b.get("title"))[:14], b.get("cached", 0),
                    b.get("total", 0), b.get("status", "")))
        except Exception as e:  # noqa: BLE001
            print(f"  ! 书架列表检查失败：{e}")
        try:
            with urllib.request.urlopen(
                    f"http://{HOST}:{PORT}/", timeout=20) as resp:
                html = resp.read().decode("utf-8", "ignore")
            m = re.search(r"<title>([^<]*)</title>", html)
            print(f"  ✓ 标题：{m.group(1) if m else '(没解析到)'}")

            # ---- 静态资源落地检查 ----
            # 为什么必须逐个头验：同步"成功"≠资源上线。曾经发生过
            # 本地改了 css/js、包也传上去了，但远端 rm -rf app 时漏了
            # 新目录（img/lumei），结果页面引用了一堆 404，
            # 而 4/5 只打 health（它不碰静态文件）—— **全绿，但站是坏的**。
            # 所以这里把「首页引用到的每个静态文件」挨个打一遍，
            # 任何一个非 200 就明确报出来。
            refs = set(re.findall(r'(?:href|src)="(/static/[^"]+)"', html))
            for extra in ("/static/css/motion.css", "/static/css/lumei.css",
                          "/static/js/motion.js", "/static/js/art.js",
                          "/static/img/lumei/hero_lulu@480.webp",
                          "/static/img/lumei/read_pair@480.webp"):
                refs.add(extra)
            bad = []
            for path in sorted(refs):
                if not path.endswith((".css", ".js", ".webp", ".png", ".svg", ".ico")):
                    continue
                try:
                    req = urllib.request.Request(f"http://{HOST}:{PORT}{path}")
                    with urllib.request.urlopen(req, timeout=15) as r:
                        code = r.status
                        size = len(r.read())
                    if code != 200 or size < 40:
                        bad.append(f"{path} -> {code} ({size}B)")
                except Exception as e:  # noqa: BLE001
                    bad.append(f"{path} -> {e}")
            if bad:
                print(f"  ✗ 静态资源有 {len(bad)} 个没到位：")
                for b in bad:
                    print(f"      {b}")
                # ⚠ 以前这里**只打印、不返回非零** —— 于是"静态资源 404、
                #   站点实际是坏的"依然以退出码 0 收场，ship 的 [3/3]
                #   会打印「✓ 上线完成」。上面那大段注释说明白了
                #   "同步成功 ≠ 资源上线"，可代码却没把这个判断兑现。
                #   资源没到位 = 部署确实有问题，必须让整条链失败。
                verify_failed = True
            else:
                print(f"  ✓ 静态资源 {len(refs)} 个全部 200")
        except Exception as e:  # noqa: BLE001
            print(f"  ! 首页检查失败：{e}")

    step("5/5", "完成")
    print(f"  访问：http://{HOST}:{PORT}/?t={TOKEN}")
    if verify_failed:
        print("\n✗ 部署完成了，但线上静态资源没全到位 —— 上面的清单就是原因。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
