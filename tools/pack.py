"""打包一份「可以直接传到云服务器」的项目压缩包。

为什么不能直接 tar 整个目录
---------------------------
项目本地有 147M，但**真正需要传上去的只有大约 30M**。多出来的是：

  · `.venv/`            62M  —— Windows 的虚拟环境，里面是 .exe/.pyd，
                                传到 Linux 上一个都用不了，必须在服务器上重建
  · `tools/bin/`        53M  —— cloudflared.exe（Windows 二进制），
                                Linux 版 tunnel.py 会自己下 cloudflared（无后缀）
  · `shots/`           5.9M  —— 开发时的截图，跟运行无关
  · `__pycache__/`     —— 字节码缓存，换平台就是垃圾
  · `logs/`            —— 旧日志，上面会重新生成
  · `cache/serve.pid`  —— 别人的进程号，传上去只会误导

**要保留的数据**（这是"全搬过去"的核心）：
  · `library/`                  7.9M  —— 书架的正文缓存 + 阅读进度
  · `downloads/`                 16M  —— 已导出的 txt
  · `cache/auth.json`                  —— 访问令牌（保住就不用重新配手机）
  · `cache/registry.json` 等           —— 来源库、适配结果
  · 全部代码 / README / requirements.txt

用法：
  python tools/pack.py                 # 生成 dist/noveldock-YYYYMMDD.tar.gz
  python tools/pack.py --out /tmp/x.tgz --with-cloudflared
"""
from __future__ import annotations

import argparse
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 顶层就要排除的目录名（整棵子树都不进包）
EXCLUDE_DIRS = {
    ".venv", "__pycache__", "shots", "logs", ".git", "dist", ".idea", ".vscode",
    "tools/bin",          # 见下面 WITH_CLOUDFLARED 开关
}

# 明确排除的文件（相对项目根）
EXCLUDE_FILES = {
    "cache/serve.pid",
    ".run.log",
    "probe_result.json",   # 开发期的一次性产物，上面用不到
}

# 数据目录 —— 这些**必须**进包，显式列出来是为了"少一个都会被发现"
KEEP_HINT = ("library/", "downloads/", "cache/", "app/", "tools/")


def is_excluded(rel: Path) -> bool:
    parts = rel.parts
    for i in range(len(parts)):
        if "/".join(parts[: i + 1]) in EXCLUDE_DIRS:
            return True
        if parts[i] in EXCLUDE_DIRS:
            return True
    return "/".join(parts) in EXCLUDE_FILES or str(rel).replace("\\", "/") in EXCLUDE_FILES


def human(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024 or unit == "G":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n}B"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="", help="输出文件（默认 dist/noveldock-日期.tar.gz）")
    ap.add_argument("--with-cloudflared", action="store_true",
                    help="把 tools/bin/cloudflared.exe 也打进去（默认不打，它是 Windows 版，Linux 上用不到）")
    a = ap.parse_args()

    if a.with_cloudflared:
        EXCLUDE_DIRS.discard("tools/bin")

    out = Path(a.out) if a.out else ROOT / "dist" / f"noveldock-{time.strftime('%Y%m%d')}.tar.gz"
    out.parent.mkdir(parents=True, exist_ok=True)

    added: list[tuple[str, int]] = []
    skipped = 0
    with tarfile.open(out, "w:gz") as tar:
        for p in sorted(ROOT.rglob("*")):
            rel = p.relative_to(ROOT)
            if is_excluded(rel):
                skipped += 1
                continue
            if p.is_dir():
                continue
            # arcname 统一带一层 `noveldock/`，解压后不会把文件撒在当前目录里
            tar.add(p, arcname=str(Path("noveldock") / rel))
            try:
                added.append((str(rel).replace("\\", "/"), p.stat().st_size))
            except OSError:
                pass

    size = out.stat().st_size
    print(f"✓ 已生成：{out}")
    print(f"  压缩包 {human(size)}（原目录未排除时约 147M）")
    print(f"  打进 {len(added)} 个文件，跳过 {skipped} 项")

    # 关键数据是否都在 —— 少一个都要当场喊出来，
    # 别等用户在服务器上发现"书架空了"
    have = {n for n, _ in added}
    print("\n  关键数据检查：")
    checks = [
        ("library/", any(h.startswith("library/") for h in have)),
        ("downloads/", any(h.startswith("downloads/") for h in have)),
        ("cache/registry.json", "cache/registry.json" in have),
        ("cache/auth.json（访问令牌）", "cache/auth.json" in have),
        ("app/", any(h.startswith("app/") for h in have)),
        ("tools/setup_linux.sh", "tools/setup_linux.sh" in have),
        ("tools/noveldock.service.tmpl", "tools/noveldock.service.tmpl" in have),
        ("requirements.txt", "requirements.txt" in have),
        ("run.py", "run.py" in have),
    ]
    ok = True
    for label, good in checks:
        print(f"    {'✓' if good else '✗'} {label}")
        if not good:
            ok = False

    # 反向确认：不该进包的东西真的没进去
    bad = [h for h in have if h.startswith(".venv/") or h.startswith("shots/")
           or h.endswith(".exe") or "__pycache__" in h]
    if bad:
        print(f"\n  ✗ 有不该进包的文件混进来了（{len(bad)} 个，例：{bad[:3]}）")
        ok = False
    else:
        print("\n  ✓ 没有混进 .venv / *.exe / 截图 / 字节码缓存")

    # 包里带着访问令牌（cache/auth.json 和 远程访问.txt）—— 这是刻意的：
    # 用户要"全搬过去"，令牌搬过去就不用重新给手机配钥匙。
    # 但必须**说清楚**，因为这意味着这个 tar.gz 本身就是敏感文件，
    # 不能随手丢到公共网盘、聊天群里。
    secrets_in_pack = [h for h in have
                       if h in ("cache/auth.json", "远程访问.txt")]
    if secrets_in_pack:
        print(f"\n  ⚠ 包里含访问令牌（{'、'.join(secrets_in_pack)}）")
        print("    这是你要求的「全搬过去」，好处是手机不用重新配。")
        print("    但它意味着这个压缩包本身是敏感文件：别发到公开的地方，传完可以删。")

    # 传给用户照抄的命令。两点是踩过坑才改的：
    #   · 用户名写 ubuntu 而不是 root —— 腾讯云轻量默认建的用户就是 ubuntu，
    #     用 root 登录会被拒（sshd 默认 PermitRootLogin 关着），
    #     而报错信息只是「Permission denied」，看不出是用户名错了。
    #   · 用实际文件名，不用 noveldock-*.tar.gz 通配 ——
    #     --out 指定成 noveldock.tar.gz 时那个通配符根本匹配不上。
    print("\n  传到服务器后：")
    print(f'    scp "{out.name}" ubuntu@<你的公网IP>:~/')
    print("    # 服务器上：")
    print(f"    tar xzf {out.name} && cd noveldock")
    print("    bash tools/oneclick.sh")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
