#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
动效层 / 素材层的静态检查
============================================================================
为什么需要它：动效这种东西是"看起来对了"的，没有断言就很容易在后续改动里
被悄悄弄丢 —— 比如有人把 motion.css 从 index.html 里删了，站点还能跑，
只是变朴素了，没人会发现。

这个脚本只做**静态**检查（读文件、不启浏览器、不联网），所以可以进 CI：

  1. 动效层与素材层已挂载
  2. 曲线与时长统一走 --mo-* 令牌，业务文件里不许写裸 cubic-bezier
  3. 列表的错峰统一走 stagger()，不许再写行内 animation-delay
  4. prefers-reduced-motion 有兜底
  5. **主题痕迹覆盖**：书架/文件/抽屉/任务/来源/榜单/阅读页都要有噜妹规则，
     且品牌规则必须集中在 lumei.css（业务 CSS 里不许出现 data-theme）
  6. art.js 里定义的每个状态都至少有调用方（不养闲素材）
  7. 所有引用的素材文件真实存在
  8. 素材比例与 art.js 里声明的一致（防"加载时跳一下"）

用法：
    .venv\\Scripts\\python tools/test_motion.py
    .venv\\Scripts\\python tools/test_motion.py --base http://127.0.0.1:8011  # 额外验线上产物
============================================================================
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
CSS = STATIC / "css"
JS = STATIC / "js"
HTML = STATIC / "index.html"
IMG = STATIC / "img" / "lumei"

ok_n = 0
bad_n = 0


def ok(msg: str) -> None:
    global ok_n
    ok_n += 1
    print(f"  ✓ {msg}")


def bad(msg: str) -> None:
    global bad_n
    bad_n += 1
    print(f"  ✗ {msg}")


def section(t: str) -> None:
    print(f"\n── {t} " + "─" * max(0, 58 - len(t)))


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception as e:
        bad(f"读不到 {p.name}: {e}")
        return ""


def _extract_at_rule_body(css: str, at: str, keyword: str):
    """从 CSS 里**真解析**出某条 at-rule（如 `@media (prefers-reduced-motion...)`）
    的 `{ ... }` 块体；找不到返回 None。

    为什么必须用括号配对而不是正则 `\\{(.*?)\\}`：
      非贪婪正则会停在**第一个** `}`，而真正想拿的是整块 ——
      实测会导致"块里明明被破坏成别的值，断言却匹配到块外的 `animation:none` 而假绿"。
      这是本文件里踩过的坑（`test_motion` 的可访问性断言第一版就是正则版，
      **反证时不报红**），所以这里老实用计数器配对。
    """
    i = css.find(at)
    while i != -1:
        j = css.find("{", i)
        if j == -1:
            return None
        # at-rule 的"前导"（从 @ 到 { 之间）里要出现过关键字
        if keyword in css[i:j]:
            depth, k = 1, j + 1
            while k < len(css) and depth:
                if css[k] == "{":
                    depth += 1
                elif css[k] == "}":
                    depth -= 1
                k += 1
            return css[j + 1:k - 1]
        i = css.find(at, i + 1)
    return None


# ===========================================================================
# 1. 挂载
# ===========================================================================
def t_mounted() -> None:
    section("1. 动效层 / 素材层已挂载")
    html = read(HTML)

    if '/static/css/motion.css' in html:
        ok("index.html 引了 motion.css")
    else:
        bad("index.html 没引 motion.css —— 动效层根本没生效")

    # 顺序：motion 要在 app.css 之后（否则覆盖不了业务样式），
    # 在 lumei.css 之前（品牌层必须最后，才能盖住）
    i_app = html.find("/static/css/app.css")
    i_mo = html.find("/static/css/motion.css")
    i_lu = html.find("/static/css/lumei.css")
    if i_app < 0 or i_mo < 0 or i_lu < 0:
        bad("CSS 顺序判不了（有文件没被引用）")
    elif i_app < i_mo < i_lu:
        ok("CSS 顺序正确：app → motion → lumei")
    else:
        bad(f"CSS 顺序不对（app={i_app} motion={i_mo} lumei={i_lu}）—— "
            "motion 必须在 app 之后、lumei 之前")

    for f in ("motion.js", "art.js"):
        if (JS / f).exists():
            ok(f"{f} 存在")
        else:
            bad(f"{f} 缺失")

    # main.js 必须启动动效层
    main = read(JS / "main.js")
    if "initMotion()" in main:
        ok("main.js 调了 initMotion()")
    else:
        bad("main.js 没调 initMotion() —— 涟漪和滚动联动都不会生效")


# ===========================================================================
# 2. 令牌纪律
# ===========================================================================
# 业务文件里允许出现裸曲线的白名单：只有在定义令牌的地方才行
TOKEN_FILES = {"motion.css", "tokens.css", "reader.css"}


def t_tokens() -> None:
    section("2. 曲线与时长走 --mo-* 令牌")
    mc = read(CSS / "motion.css")
    for name in ("--mo-standard", "--mo-decel", "--mo-spring",
                 "--mo-instant", "--mo-quick", "--mo-flow", "--mo-scene"):
        if name in mc:
            ok(f"{name} 已定义")
        else:
            bad(f"{name} 没定义")

    # 业务 CSS 里出现裸 cubic-bezier 就报 —— 那意味着又有地方"自己发明曲线"
    offenders = []
    for f in sorted(CSS.glob("*.css")):
        if f.name in TOKEN_FILES:
            continue
        txt = read(f)
        # 排除注释行里的说明
        for m in re.finditer(r"cubic-bezier\([^)]*\)", txt):
            line_no = txt[:m.start()].count("\n") + 1
            line = txt.splitlines()[line_no - 1]
            if line.strip().startswith(("*", "/*", "//")):
                continue
            offenders.append(f"{f.name}:{line_no}")
    if offenders:
        bad(f"业务 CSS 里有裸 cubic-bezier：{', '.join(offenders[:6])}")
    else:
        ok("业务 CSS 无裸曲线（全部走令牌）")


def t_stagger() -> None:
    section("3. 列表错峰统一走 stagger()")
    # 业务 JS 里不该再有行内 animation-delay —— 那会让节奏各写各的
    offenders = []
    for f in sorted(JS.glob("*.js")):
        txt = read(f)
        for m in re.finditer(r'animation-delay:\s*\$\{[^}]*\}', txt):
            line_no = txt[:m.start()].count("\n") + 1
            offenders.append(f"{f.name}:{line_no}")
    if offenders:
        bad(f"仍有行内 animation-delay：{', '.join(offenders)}")
    else:
        ok("业务 JS 里没有行内 animation-delay")

    # 三个长列表都要调 stagger
    for f, sel in (("discover.js", ".book"), ("shelf.js", ".shelf"), ("files.js", ".file")):
        txt = read(JS / f)
        if "stagger(" in txt:
            ok(f"{f} 用了 stagger（{sel}）")
        else:
            bad(f"{f} 没用 stagger —— 列表入场会没有错峰")

    # ⚠ 榜单：错峰必须挂在**唯一入口** writeList 上，而不是散在 bindItems 里。
    #
    # 为什么专门盯这一处：榜单有四条写入路径（骨架 / 缓存命中 / 真数据 / 出错），
    # 原来错峰写在 bindItems —— 它只覆盖后三条，骨架那条漏掉，
    # 首屏会先硬弹一屏灰条、再换成错峰的真列表（两次生硬入场），
    # 真机测试还会因为拍到骨架期而误判"stagger 没覆盖全"。
    # 收成 writeList 后，四条路径自动一致；这条断言防止有人日后又绕过它。
    rk = read(JS / "ranks.js")
    if re.search(r"function\s+writeList\s*\(", rk):
        ok("ranks.js 有 writeList() 统一入口")
    else:
        bad("ranks.js 没有 writeList() —— 四条渲染路径又会各写各的")

    if re.search(r"function\s+writeList[\s\S]{0,600}?stagger\(", rk):
        ok("writeList() 内部调了 stagger（所有渲染路径统一错峰）")
    else:
        bad("writeList() 里没有 stagger —— 错峰又漏了")

    # 除 writeList 自身外，不该再有别处直接写 ranksList 的 innerHTML
    stray = []
    for m in re.finditer(r'(\$\("#ranksList"\)|list)\.innerHTML\s*=', rk):
        line_no = rk[:m.start()].count("\n") + 1
        # writeList 内部那一处（list.innerHTML = html）是唯一合法写入
        if "list.innerHTML = html" not in rk.splitlines()[line_no - 1]:
            stray.append(f"ranks.js:{line_no}")
    if stray:
        bad(f"绕开 writeList 直接写榜单列表：{', '.join(stray)}")
    else:
        ok("榜单列表只有 writeList 一处写入（无绕开路径）")


def t_a11y() -> None:
    section("4. 可访问性兜底")
    mc = read(CSS / "motion.css")
    if "prefers-reduced-motion" in mc:
        ok("motion.css 有 prefers-reduced-motion 兜底")
    else:
        bad("motion.css 缺 prefers-reduced-motion —— 这是可访问性要求，不是可选项")

    # ⚠⚠ 品牌层也必须自带兜底。
    #
    # 为什么专门盯 lumei.css：品牌层的所有动效（水豚呼吸 / 入场 / 暖光脉动 /
    # logo 呼吸）都写在 lumei.css 里，**不在 motion.css**。
    # 上面那条只证明"框架层有兜底"，管不到品牌层 —— 踩过：新加的 `.lu-duo::before`
    # 暖光脉动（7s 循环）当时就漏在 reduced-motion 块外，系统偏好"减少动效"的人
    # 照样会看到它一直在呼吸。这类"新增动效忘记补兜底"最容易反复发生，
    # 所以这里钉一条：lumei.css 必须有 prefers-reduced-motion 块。
    lc = read(CSS / "lumei.css")
    if "prefers-reduced-motion" in lc:
        ok("lumei.css 有 prefers-reduced-motion 兜底（品牌层动效不会漏）")
    else:
        bad("lumei.css 缺 prefers-reduced-motion —— 品牌层的呼吸/入场/暖光会无视系统偏好")

    # 品牌层里出现的每一个动画，都要能在 reduced-motion 块里被关掉。
    #
    # ⚠ 这里不能只 grep "animation:none"（第一版就是这么写的，**反证时不报红**）：
    #   · 块里但凡正则可以匹配到别处的 `animation:none`，断言就假绿；
    #   · 而且 `\n\}` 只能匹配到**第一个** `}`（块里本来就该只有一个，
    #     但破坏后多个声明分支会让人误以为"还在关"）。
    # 正确做法：**真解析出块体**，要求块内 `animation` 声明存在且**没有不是 none 的**。
    body = _extract_at_rule_body(lc, "@media", "prefers-reduced-motion")
    if body is None:
        bad("品牌层找不到 prefers-reduced-motion 块体（只有关键字不算）")
    else:
        # ⚠⚠ 必须**先剥掉注释**再判 —— 踩过（本断言第一版就是漏了这步）：
        #   给规矩写的说明注释里也会出现 `.lu-duo::before` 这类选择器名，
        #   于是"把规则整条删掉"后，注释还在 → 子串匹配照样命中 → **假绿**。
        #   （反证时就是这样骗过去的：删了规则，测试仍全绿。）
        body_code = re.sub(r"/\*.*?\*/", "", body, flags=re.S)

        # ⚠ 值的边界是 `;` 或 `}` 或行尾 —— 不能只切 `;`：
        #   块里**最后一条**声明后面直接跟 `}`（没有分号），
        #   用 `[^;]+` 会把 `}` 一起吞进来（踩过：值变成 "none!important}" 判红）。
        anims = re.findall(r"animation\s*:\s*([^;}\n]+)", body_code)
        if not anims:
            bad("品牌层 reduced-motion 块里没有任何 animation 声明 —— 品牌动效关不掉")
        else:
            # 值可能是 `none` 或 `none!important`（`!important` 前不一定有空格）
            not_none = [a.strip() for a in anims
                        if not a.strip().lower().startswith("none")]
            if not_none:
                bad(f"品牌层 reduced-motion 块里有 'animation' 没关成 none："
                    f"{', '.join(not_none[:3])}")
            else:
                ok(f"品牌层 reduced-motion 块把关掉的动画全设成 none（{len(anims)} 处）")

        # 新增动效忘记补兜底是最容易反复发生的（暖光脉动就漏过一次）。
        # 用一条稳的契约代替脆弱的"逐个 keyframes 追宿主"：
        # 块里必须同时关掉 水豚族（呼吸/入场/浮动）与 暖光脉动。
        if ".lu-capy" in body_code and ".lu-duo::before" in body_code:
            ok("品牌层兜底覆盖了 水豚(呼吸/入场/浮动) + 暖光脉动")
        else:
            miss = [s for s in (".lu-capy", ".lu-duo::before") if s not in body_code]
            bad(f"品牌层兜底漏了：{', '.join(miss)}")

    mj = read(JS / "motion.js")
    if "reduceMotion()" in mj and "matchMedia" in mj:
        ok("motion.js 有 reduceMotion() 判定，装饰动作会跳过")
    else:
        bad("motion.js 没有 reduceMotion() —— JS 侧的动效会无视系统偏好")

    if "mo-rip" in mc and "pointerdown" in mj:
        ok("涟漪挂在 pointerdown 上（跟手，不等 click）")
    else:
        bad("涟漪没挂 pointerdown —— 反馈会慢半拍")


# ===========================================================================
# 5. 主题痕迹覆盖（用户原话：「主题不能只做主页，到处都要适配」）
# ===========================================================================
# 每个条目 = (人类可读的页面/组件名, 该有主题规则的 CSS 片段特征)
# 特征用**选择器子串**而不是行号 —— 行号会随编辑漂移，选择器是"契约"。
THEME_COVERAGE = [
    ("书架卡片 · 书封高光", 'html[data-theme="lumei"] .shelf .cover::after'),
    ("书架卡片 · 继续阅读按钮", 'html[data-theme="lumei"] .shelf .acts .btn.primary'),
    ("书架卡片 · hover 描边", 'html[data-theme="lumei"] .shelf:hover'),
    ("文件行 · 图标底衬", 'html[data-theme="lumei"] .file .ic'),
    ("文件行 · 格式图标着色", 'html[data-theme="lumei"] .file .ic[data-ext="epub"]'),
    ("抽屉 · 头部暖线", 'html[data-theme="lumei"] .drawer > header'),
    ("抽屉 · 移动端把手", 'html[data-theme="lumei"] .drawer::before'),
    ("遮罩 · 暖色", 'html[data-theme="lumei"] .mask'),
    ("确认框 · 顶部暖线", 'html[data-theme="lumei"] .cfm'),
    ("令牌闸门 · 顶线+插画", 'html[data-theme="lumei"] .gate'),
    ("书名确认卡 · 左线", 'html[data-theme="lumei"] .cfs'),
    ("任务卡 · 左边线", 'html[data-theme="lumei"] .task'),
    ("任务卡 · 运行中呼吸", 'html[data-theme="lumei"] .task.is-running'),
    ("来源卡 · hover 描边", 'html[data-theme="lumei"] .hcard:hover'),
    ("榜单标签 · 选中态", 'html[data-theme="lumei"] .rk-tab.on'),
    ("阅读页 · 章末收尾", '#reader[data-rd-theme="lumei"] .rd-article::after'),
    ("阅读页 · 色卡角标", '.rd-thermos .th-card[data-th="lumei"]'),
    ("首页 · 吉祥物一对", '.lu-capy'),
    ("空状态 · 插图", '.empty-art'),
    # —— 搜索结果卡（.book）：本轮补的缺口 ——
    # 这是用户**停留最久**的界面（逐条读书名、挑来源、点"收进书架"），
    # 但之前清单里没有它，lumei.css 里也确实一处覆盖都没有
    # （`grep -c '.book' lumei.css` 返回 0）—— 于是整站最暖的首页点下去，
    # 结果是通体冷灰的卡片，主题在这里"断片"了。
    # 教训：**清单本身也会漏**，漏掉的页面看起来"已通过检查"。
    # 所以补清单时要按「用户会停留的页面」逐个过一遍，不是按现有 CSS 反推。
    ("搜索结果卡 · hover 暖边", 'html[data-theme="lumei"] .book:hover'),
    ("搜索结果卡 · 书封高光", 'html[data-theme="lumei"] .book .cover::after'),
    ("搜索结果卡 · 收进书架按钮", 'html[data-theme="lumei"] .book .acts .btn.primary'),
    ("搜索结果卡 · 来源行 hover", 'html[data-theme="lumei"] .book .srow:hover'),
    ("搜索状态栏 · 关键词暖色", 'html[data-theme="lumei"] .statbar b'),
    ("加载骨架 · 暖白流光", 'html[data-theme="lumei"] .skel i::after'),
    # 移动端底部标签栏：**每一屏都在**，是除顶栏外出现频率最高的元素。
    # 它的背景/选中色走主题变量（自动适配），缺的只是品牌痕迹。
    ("底部标签栏 · 暖色顶线", 'html[data-theme="lumei"] .tabbar'),
    ("底部标签栏 · 选中暖点", 'html[data-theme="lumei"] .tabbar button.on::after'),
    ("筛选条 · 胶囊 hover 暖边", 'html[data-theme="lumei"] .filters .chip:hover'),
    # 联网发现面板（.netlive）：「本地全灭 → 联网兜底」时才出现。
    # 用户此刻已经等了几秒、最容易犯嘀咕，而这就是他**全程盯着看**的那块。
    ("联网发现 · 暖色顶边", 'html[data-theme="lumei"] .netlive'),
    ("联网发现 · 命中站点柔光", 'html[data-theme="lumei"] .nl-steps li.hit .d'),
    ("联网发现 · 进行中那步脉动", 'html[data-theme="lumei"] .nl-steps li:last-child .t'),
    # 首页 Hero + 搜索框：这是**用户看到的第一屏**，也是设计规范 §4.1
    # 「必须适配主题的页面」里白纸黑字列着的两项。
    # 但之前这两项既不在清单里、lumei.css 里也一处覆盖都没有
    # （`grep -c '.hero' lumei.css` = 0）—— 于是首页最上面两块是冷的，
    # 品牌从第二屏才开始。这正好复现了上面第 248 行写下的教训：
    # 「**清单本身也会漏**，漏掉的页面看起来'已通过检查'」。
    ("首页 Hero · eyebrow 暖描边", 'html[data-theme="lumei"] .hero .eyebrow'),
    ("首页 Hero · 标题暖光晕", 'html[data-theme="lumei"] .hero h1'),
    ("首页搜索框 · 焦点橙色光晕", 'html[data-theme="lumei"] .searchbox:focus-within'),
    ("首页搜索框 · 主题色光标", 'html[data-theme="lumei"] .searchbox input'),
    # Toast（全局提示）：曝光量仅次于顶栏 —— 每保存/搜索/导出一次就跳一下。
    # 之前 `grep -c toast lumei.css` = 0，主题在这块是断的。
    # ⚠ 注意区分：.toast.ok / .warn / .err 早就吃主题了（语义色在 lumei token
    # 里本来就是暖的），真正没适配的是**中性 toast** —— 它用 --t-1 暖黑，
    # 在奶油底上是"挖了个洞"。所以清单断言的是中性态那条选择器。
    ("Toast · 中性态暖褐药丸", 'html[data-theme="lumei"] .toast:not(.ok)'),
    ("Toast · 暖调贴身影", 'html[data-theme="lumei"] .toast'),
]


def t_theme_coverage() -> None:
    section("6. 主题痕迹覆盖（每个页面都要有，不能只做主页）")
    lc = read(CSS / "lumei.css")
    # 归一空白：选择器里可能有换行（多选择器逗号分隔写法）
    flat = re.sub(r"\s+", " ", lc)
    missing = []
    for name, sel in THEME_COVERAGE:
        # 去掉空格比对，避免 `.a > .b` 与 `.a>.b` 写法差异造成假红
        if sel.replace(" ", "") in flat.replace(" ", ""):
            pass
        else:
            missing.append((name, sel))
    if missing:
        for name, sel in missing:
            bad(f"{name} 没有主题规则（找不到 `{sel}`）")
    else:
        ok(f"{len(THEME_COVERAGE)} 个页面/组件都有噜妹主题规则")

    # 反向：品牌皮必须可摘 —— 业务 CSS 里不许出现 data-theme="lumei"
    for f in ("app.css", "reader.css", "motion.css", "backgrounds.css"):
        s = read(CSS / f)
        if 'data-theme="lumei"' in s:
            bad(f"{f} 里出现了 data-theme=lumei —— 品牌规则必须集中在 lumei.css，否则摘不掉")
        else:
            ok(f"{f} 干净（品牌规则没漏进来）")

    # 反向：**组件样式不许写行内 style** —— 行内 style 优先级高于任何类选择器，
    # 主题层再怎么改也够不到它。confirmBox 就栽在这上面（整块弹窗无法被主题化）。
    # 只查 JS 里 `class="..."  style="...": ` 形态的组件骨架，放过位置微调类行内
    # （如 `style="width:X%"` 这种"运行时数据"，它本来就该是行内）。
    INLINE_OK = ("width:", "height:", "top:", "left:", "--x:", "display:none")
    for f in sorted(JS.glob("*.js")):
        src = read(f)
        for m in re.finditer(r'style="([^"]*)"', src):
            body = m.group(1)
            if "var(--s-card)" in body or "var(--s-line)" in body or "border-radius" in body:
                bad(f"{f.name} 里有组件骨架行内 style（主题层够不到）：{body[:50]}…")
                break


# ===========================================================================
# 7. 素材
# ===========================================================================
ART_RE = re.compile(
    r'(\w+):\s*\{\s*file:\s*"([^"]+)",\s*w:\s*(\d+),\s*h:\s*(\d+)', re.S)


def t_assets() -> None:
    section("7. 素材：定义齐全 · 文件存在 · 比例一致")
    art = read(JS / "art.js")
    entries = ART_RE.findall(art)
    if not entries:
        bad("art.js 里没解析出任何状态定义")
        return
    ok(f"art.js 定义了 {len(entries)} 个状态")

    # 每个 @480 文件都要在
    missing = []
    for key, f, w, h in entries:
        p = IMG / f"{f}@480.webp"
        if not p.exists():
            missing.append(f"{f}@480.webp")
    if missing:
        bad(f"素材文件缺失：{', '.join(missing)}")
    else:
        ok(f"{len(entries)} 个状态的主图都在")

    # 比例一致性：读 webp 头拿真实宽高，和声明值比
    try:
        from PIL import Image
    except ImportError:
        print("     (跳过比例检查：没装 Pillow)")
        return

    mismatch = []
    for key, f, w, h in entries:
        p = IMG / f"{f}@480.webp"
        if not p.exists():
            continue
        im = Image.open(p)
        rw, rh = im.size
        # 允许 1px 的舍入差（cover 裁切时会四舍五入）
        if abs(rw - int(w)) > 1 or abs(rh - int(h)) > 1:
            mismatch.append(f"{f}: 声明 {w}×{h} 实际 {rw}×{rh}")
    if mismatch:
        bad("比例与声明不符（浏览器会先按声明预留高度，加载后跳一下）：\n      "
            + "\n      ".join(mismatch))
    else:
        ok("所有素材的实际比例与 art.js 声明一致")

    # 反向检查：素材目录里有没有谁都没用到的（孤儿素材）
    # 三种"被用到"的方式都算数：artHTML() 调用 / CSS 背景 / index.html 直引
    used = {f for _, f, _, _ in entries}
    css_txt = "\n".join(read(p) for p in CSS.glob("*.css"))
    html_txt = read(HTML)

    all_files = sorted({p.stem.replace("@480", "").replace("@240", "")
                        for p in IMG.glob("*.webp")})
    orphans = []
    for name in all_files:
        if name in used:
            continue
        if f"img/lumei/{name}" in css_txt or f"img/lumei/{name}" in html_txt:
            continue
        orphans.append(name)
    if orphans:
        bad(f"孤儿素材（谁都没引用）：{', '.join(orphans)}")
    else:
        ok(f"没有孤儿素材（全部 {len(all_files)} 张都有落点）")

    # hero_* 走 index.html 直引（不是 st-art 体系），单独确认存在
    for f in ("hero_lulu", "hero_lumei"):
        if f"img/lumei/{f}@480.webp" in html_txt:
            ok(f"{f} 由首页直引")
        else:
            bad(f"{f} 没在首页引用 —— 首页会少一半吉祥物")

    # ---------------------------------------------------------------------
    # ⚠⚠ Hero 轮换池的两条硬契约（2026-10-14 新增）
    #
    # 背景：用户报「首页两个图片都是噜噜，没有噜妹」。根因是轮换池里的条目
    #   在 `rotateHeroArt()` 里被 `ART[key]` **静默过滤掉了** ——
    #   `hero_lulu`/`hero_lumei` 当时只登记在 HTML_ONLY，没进 ART，
    #   于是"含噜妹的那一对"每天都被丢弃，连着几天首页只有噜噜。
    #   而当时的测试只数了 `data-hero-pool` 里的**字符串条数**，
    #   没验"过滤之后还剩几对"→ 假绿。
    #
    # 所以这里改成**对着 art.js 真正校验过滤结果**：
    #   ① 池里每一项的左右两个键都必须在 ART 里（否则会被丢掉）
    #   ② 每一项都必须**含且只含一个**「噜妹」键（LUMEI_KEYS）
    # ② 就是「每一天首页都要有噜妹」这句产品承诺的机器化表达。
    # ---------------------------------------------------------------------
    m = re.search(r'data-hero-pool="([^"]+)"', html_txt)
    lumei = re.search(r"LUMEI_KEYS = new Set\(\[([^\]]*)\]\)", art)
    if not m:
        bad("首页找不到 data-hero-pool —— Hero 就不会轮换")
    elif not lumei:
        bad("art.js 没有 LUMEI_KEYS —— 无法校验『每天都要有噜妹』")
    else:
        art_keys = {k for k, _, _, _ in entries}
        lumei_keys = set(re.findall(r'"(\w+)"', lumei.group(1)))
        raw = [s.strip() for s in m.group(1).split(",") if s.strip()]
        dropped, no_lumei, both_lumei = [], [], []
        for item in raw:
            pair = [x.strip() for x in item.split("|")]
            if len(pair) != 2 or any(k not in art_keys for k in pair):
                dropped.append(item)          # 会被 rotateHeroArt 静默丢掉
                continue
            n = sum(1 for k in pair if k in lumei_keys)
            if n == 0:
                no_lumei.append(item)
            elif n == 2:
                both_lumei.append(item)

        if dropped:
            bad(f"Hero 轮换池里有会被丢弃的条目（键不在 ART 里）：{', '.join(dropped)}\n"
                f"      → rotateHeroArt() 会静默跳过它们，轮换就少几天。"
                f"加素材时记得同时登记进 art.js 的 ART。")
        else:
            ok(f"Hero 轮换池 {len(raw)} 对全部有效（没有会被静默丢弃的）")

        if no_lumei:
            bad(f"Hero 轮换池里有**不含噜妹**的配对：{', '.join(no_lumei)}\n"
                f"      → 轮到它们的那天，首页只有噜噜，用户会说『没有噜妹』。"
                f"排布约定：左=噜噜、右=噜妹（见 index.html 注释）。")
        elif both_lumei:
            bad(f"Hero 轮换池里有**两边都是噜妹**的配对：{', '.join(both_lumei)}")
        else:
            ok(f"Hero 每一对都含且只含一个噜妹（{len(raw)} 对）")

        if len(raw) < 2:
            bad(f"Hero 轮换池只有 {len(raw)} 对 —— 起不到『每天轮换』的作用")
        else:
            ok(f"Hero 轮换池 ≥2 对（当前 {len(raw)} 对）")

    # read_pair / read_eat 走 CSS 背景，确认真的被引用了
    for f in ("read_pair", "read_eat"):
        if f"img/lumei/{f}" in css_txt:
            ok(f"{f} 由 CSS 引用（不占分页高度）")
        else:
            bad(f"{f} 声明为 CSS_ONLY，但 CSS 里没有引用它")

    # 调用的状态键必须在 art.js 里定义过（防拼错）
    defined = {k for k, _, _, _ in entries}
    badkey = []
    for f in sorted(JS.glob("*.js")):
        txt = read(f)
        for m in re.finditer(r'artHTML\(\s*"(\w+)"', txt) or []:
            pass
        for m in re.finditer(r'(?:artHTML|busyHTML|failHTML)\(\s*\{[^}]*?key:\s*"(\w+)"', txt, re.S):
            if m.group(1) not in defined:
                badkey.append(f"{f.name}: key={m.group(1)}")
        for m in re.finditer(r'artHTML\(\s*"(\w+)"', txt):
            if m.group(1) not in defined:
                badkey.append(f"{f.name}: artHTML({m.group(1)})")
    if badkey:
        bad(f"调用了未定义的状态键：{', '.join(badkey)}")
    else:
        ok("所有 artHTML/busyHTML/failHTML 调用键都已定义")


# ===========================================================================
# 6. 线上产物（可选）
# ===========================================================================
def t_live(base: str) -> None:
    section("6. 线上产物可访问")

    def get(path: str) -> tuple[int, bytes]:
        req = urllib.request.Request(base.rstrip("/") + path,
                                     headers={"User-Agent": "test-motion"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()

    try:
        code, body = get("/")
        html = body.decode("utf-8", "replace")
        if code == 200 and "motion.css" in html:
            ok("GET / 200 且含 motion.css")
        else:
            bad(f"GET / 返回 {code}，motion.css {'在' if 'motion.css' in html else '不在'}")

        for path, want in (("/static/css/motion.css", "--mo-standard"),
                           ("/static/js/motion.js", "initMotion"),
                           ("/static/js/art.js", "artHTML"),
                           ("/static/img/lumei/loading_read@480.webp", None)):
            try:
                code, body = get(path)
            except Exception as e:
                bad(f"GET {path} 失败：{e}")
                continue
            if code != 200:
                bad(f"GET {path} → {code}")
            elif want and want.encode() not in body:
                bad(f"GET {path} 200 但内容里没有 {want}")
            else:
                ok(f"GET {path} 200" + (f" 且含 {want}" if want else ""))
    except Exception as e:
        bad(f"连不上 {base}：{e}")


# ===========================================================================
def t_bus_contract() -> None:
    """4. 事件总线的接口契约（Vue 迁移期最容易踩的一处）。

    两条硬约束：
      a) `bus.on()` **必须返回退订函数**。Vue 组件里最常见的写法是
         `const off = bus.on("x", fn); onUnmounted(() => off())`。
         如果 on 不返回东西，off 就是 undefined、`off && off()` 静默不执行，
         **监听泄漏且零报错**（真踩过：RanksPanel 的 off1/off2 一直是
         undefined，组件卸载后旧事件还在往死组件上写）。
      b) `bus.off()` 必须存在。旧代码一次性 mount、永不卸载，没有 off
         也不暴露问题；组件会反复挂载/卸载，没有 off 就没法摘干净。
    """
    section("4. 事件总线契约（on 返回退订 / off 存在）")
    txt = read(JS / "util.js")

    if re.search(r"off\s*\(\s*ev\s*,\s*fn\s*\)\s*\{", txt):
        ok("bus 有 off(ev, fn)")
    else:
        bad("bus 缺 off() —— Vue 组件卸载时摘不掉监听，会越挂越多")

    # on 里必须有一句 return（返回退订函数）
    m = re.search(r"\bon\s*\(\s*ev\s*,\s*fn\s*\)\s*\{(.*?)\n  \}", txt, re.S)
    if not m:
        bad("没找到 bus.on 的实现，无法校验")
    elif re.search(r"\breturn\b", m.group(1)):
        ok("bus.on() 会返回值（退订函数）")
    else:
        bad("bus.on() 没有 return —— 组件里 `const off = bus.on(...)` "
            "会拿到 undefined，卸载时摘不掉监听（静默泄漏）")

    # 组件里用 bus.on 的返回值退订时，不该再依赖不存在的 bus.off 变体
    comp_dir = ROOT / "frontend" / "src" / "components"
    if comp_dir.is_dir():
        for f in sorted(comp_dir.glob("*.vue")):
            c = f.read_text("utf-8")
            if "bus.on(" in c and "onUnmounted" in c and "bus.off(" not in c \
                    and not re.search(r"=\s*bus\.on\(", c):
                bad(f"{f.name}: 订了 bus.on 但既没用返回值退订、也没调 bus.off "
                    "—— 卸载后会泄漏")
                return
        ok("Vue 组件都正确地摘了监听（用返回值或 bus.off）")


# ===========================================================================
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="", help="可选：线上地址，额外验产物")
    a = ap.parse_args()

    print("=" * 62)
    print("动效层 / 素材层 静态检查")
    print("=" * 62)

    t_mounted()
    t_tokens()
    t_stagger()
    t_bus_contract()
    t_a11y()
    t_theme_coverage()
    t_assets()
    if a.base:
        t_live(a.base)

    print("\n" + "=" * 62)
    print(f"通过 {ok_n} · 失败 {bad_n}")
    if bad_n:
        print("✗ 有问题，见上面 ✗ 行")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
