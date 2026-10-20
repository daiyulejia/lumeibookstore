#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
前端构建产物 · 上线链路自检
============================================================================
Vite 产物（app/static/dist/）要能真的到线上，中间有**四道关**，
每一道错了都表现成同一个症状：**页面白屏 / 样式丢失，但部署显示成功**。
这个脚本把四道关全钉住 —— 它们都不会报错，只会让站坏掉。

  1. 产物存在且被 index.html 引用
     —— 不引用 = 不会被 sync_cloud 验证 = 白屏也算"成功"。

  2. pack.py 不会把产物排掉
     —— ⚠ 这是最容易踩的一个：EXCLUDE_DIRS 里有 `dist`，
        而匹配是**按路径段**的，于是 `app/static/dist/` 会被误伤。
        产物不进包 → 服务器上没有 → 404 白屏，而本地测试全绿。
        （真发生过：第一次接 Vite 时就是这条。）

  3. main.py 的版本号扫得到 dist/
     —— _ASSET_DIRS 不含 dist 的话，改了 Vue 代码版本号不变，
        浏览器继续用旧产物 → "改了没生效"。

  4. index.html 里的引用路径与产物实际文件名一致
     —— 产物名见过一次碰撞（app.css 撞手写的 css/app.css），
        改名 vue-app.* 之后如果 index.html 没跟着改，同样是 404。

用法：
    .venv\\Scripts\\python tools\\test_frontend.py
============================================================================
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
DIST = STATIC / "dist"
INDEX = STATIC / "index.html"

ok_n = 0
bad_n = 0


def ok(m: str) -> None:
    global ok_n
    ok_n += 1
    print(f"  ✓ {m}")


def bad(m: str) -> None:
    global bad_n
    bad_n += 1
    print(f"  ✗ {m}")


def section(t: str) -> None:
    print(f"\n── {t} " + "─" * max(0, 56 - len(t)))


def main() -> int:
    print("=" * 62)
    print("前端产物 · 上线链路自检")
    print("=" * 62)

    html = INDEX.read_text(encoding="utf-8") if INDEX.exists() else ""

    # ---------------------------------------------------------------
    section("1. 产物存在 + 被 index.html 引用")
    js = DIST / "vue-app.js"
    css = DIST / "vue-app.css"
    if js.exists() and js.stat().st_size > 10000:
        ok(f"vue-app.js 存在（{js.stat().st_size // 1024} KB）")
    else:
        bad("vue-app.js 不存在或过小 —— 跑 `cd frontend && npm run build`")
    if css.exists() and css.stat().st_size > 500:
        ok(f"vue-app.css 存在（{css.stat().st_size // 1024} KB）")
    else:
        bad("vue-app.css 不存在或过小 —— 跑 `cd frontend && npm run build`")

    for name, path in (("js", "/static/dist/vue-app.js"), ("css", "/static/dist/vue-app.css")):
        if path in html:
            ok(f"index.html 引了 {path}")
        else:
            bad(f"index.html 没引 {path} —— 产物不会被 sync_cloud 验证，白屏也算成功")

    # ---------------------------------------------------------------
    section("2. pack.py 不会把产物排掉")
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import pack  # type: ignore

        for rel in ("app/static/dist/vue-app.js", "app/static/dist/vue-app.css"):
            if pack.is_excluded(Path(rel)):
                bad(f"{rel} 被 pack 排除了 —— 产物到不了服务器（白屏！）")
            else:
                ok(f"{rel} 会进包")
        # 顺带确认排除逻辑本身没被改坏
        if pack.is_excluded(Path("frontend/node_modules/vue/index.js")):
            ok("frontend/node_modules/ 正确排除（几万个文件）")
        else:
            bad("frontend/node_modules/ 没被排除 —— 包会大得离谱")
        if pack.is_excluded(Path("dist/noveldock.tar.gz")):
            ok("顶层 dist/ 仍被排除（tarball 不该进包）")
        else:
            bad("顶层 dist/ 没被排除 —— 包会自我嵌套")
    except Exception as e:  # noqa: BLE001
        bad(f"导入 pack.py 失败：{e}")

    # ---------------------------------------------------------------
    section("3. main.py 的版本号扫得到 dist/")
    main_py = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    m = re.search(r"_ASSET_DIRS\s*=\s*\(([^)]*)\)", main_py)
    if m:
        dirs = re.findall(r'"([^"]+)"', m.group(1))
        if "dist" in dirs:
            ok(f"_ASSET_DIRS 含 dist（{dirs}）—— 改 Vue 代码版本号会变")
        else:
            bad(f"_ASSET_DIRS = {dirs}，不含 dist —— 改了前端版本号不变，"
                "用户拿到旧缓存")
    else:
        bad("找不到 _ASSET_DIRS 定义 —— app/main.py 结构变了？")

    # ---------------------------------------------------------------
    section("4. 引用路径与产物实际文件名一致")
    # 从 index.html 抠出 /static/dist/ 下的所有引用，逐个确认文件真的在
    refs = set(re.findall(r'(?:href|src)="(/static/dist/[^"?]+)', html))
    if not refs:
        bad("index.html 里没有任何 /static/dist/ 引用 —— 前端没接上")
    else:
        for r in sorted(refs):
            p = STATIC / r[len("/static/"):]
            if p.exists():
                ok(f"{r} → 文件存在")
            else:
                bad(f"{r} → 文件不存在（改过产物名却没同步 index.html？）")

    # 反向：dist/ 里有没有"产出了但没人引用"的文件（漏引用 = 白屏）
    #
    # ⚠ `.gz` **不是**"另一个产物"，是**同一产物的另一种编码**
    #   （tools/gzip_static.py 构建期压出来的）。浏览器永远按**源文件名**请求
    #   （/static/dist/vue-app.js），能不能走 .gz 由请求头 Accept-Encoding 决定、
    #   由服务端 app/main.py::_gzip_response() 挑 ——
    #   所以它**不可能、也不应该**出现在 index.html 的 src/href 里。
    #   上一版把它当孤儿，等于"凡是做了预压缩就必红"：判据本身错了，不是产品坏了。
    #
    #   但"不查"也不对：**没有源文件的 .gz 才是真孤儿**（源文件改了名或删了，
    #   .gz 忘清理），这种残骸不会报错，只会白占体积、还可能喂给浏览器过期内容。
    #   所以拆成两条：源文件集合照旧查孤儿，.gz 单独查"有没有对应的源"。
    if DIST.exists():
        names = {p.name for p in DIST.iterdir() if p.is_file()}
        on_disk = {f"/static/dist/{n}" for n in names if not n.endswith(".gz")}
        orphan = on_disk - refs
        if orphan:
            bad(f"dist/ 里有产出了但 index.html 没引用的文件：{sorted(orphan)}")
        else:
            ok("dist/ 里的文件都被 index.html 引用了（无孤儿产物）")

        # 预压缩残骸：.gz 在、源不在
        gz_stale = sorted(f"/static/dist/{n}" for n in names
                          if n.endswith(".gz") and n[:-3] not in names)
        if gz_stale:
            bad(f"dist/ 里有找不到源文件的 .gz 残骸：{gz_stale}\n"
                f"      → 源文件改名/删掉后 .gz 没跟着清，会白占体积；\n"
                f"        重跑 `python tools/gzip_static.py` 会清掉它们。")
        else:
            ok("没有 .gz 残骸（每个 .gz 都有对应的源文件）")

    print("\n" + "=" * 62)
    if bad_n == 0:
        print(f"通过 {ok_n} · 失败 0\n✓ 全部通过")
    else:
        print(f"通过 {ok_n} · 失败 {bad_n}\n✗ 有 {bad_n} 项没过")
    print("=" * 62)
    return 1 if bad_n else 0


if __name__ == "__main__":
    sys.exit(main())
