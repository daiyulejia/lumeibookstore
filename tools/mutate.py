"""反证工具：**故意破坏产品代码**，看测试是不是真的会报红。

为什么要有这个工具
------------------
本项目最高频的坑不是"没写测试"，而是**写了没牙的测试**（已抓到 13+ 次
"看着在测、其实恒真"）。而那种测试只有一种办法能暴露：**破坏一次**产品代码，
看它会不会红。手工做这件事的问题有两个 —— 容易漏（只反证一半）、
容易忘还原（把源码留在被破坏的状态）。

所以把「替换源码 → 跑测试 → 还原 → 报存活项」固化成常驻工具：

  · **存活** = 那条断言没有牙，必须重写。
  · **片段找不到** = 测试与代码已经脱节（改了实现却没更新反证），也必须修。
  · 无论成败都在 `finally` 里还原；退出时再按内容哈希复核一遍，
    确认源码和进来时**逐字节一致**。

用法::

    .venv/Scripts/python.exe tools/mutate.py              # 全部
    .venv/Scripts/python.exe tools/mutate.py toc          # 只跑某一组
    .venv/Scripts/python.exe tools/mutate.py --list       # 只看清单

⚠ **别在 `tools/ship.py` 跑的时候手动跑它** —— 两边都会替换源码。
"""
from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")

WEB = ROOT / "app" / "webfetch.py"
BASE = ROOT / "app" / "sources" / "base.py"
CONF = ROOT / "app" / "sources" / "configured.py"
ADAP = ROOT / "app" / "sources" / "adapter.py"
SHOT = ROOT / "tools" / "shot.py"
# 品牌层（静态资源）—— 2026-10-15 起也纳入反证。
# ⚠ 这一层原来完全没被反证覆盖：它的失败方式全是**静默**的
#   （文案变长了、JS 不再写那句话、兜底文案和平时不是同一句），
#   而静态检查自己也可能写着恒真的判据。不破坏一次就不知道有没有牙。
ART_JS = ROOT / "app" / "static" / "js" / "art.js"
INDEX_HTML = ROOT / "app" / "static" / "index.html"

# 榜单层（多来源聚合）—— 2026-10-15 纳入反证。
# ⚠ 它的失败方式同样全静默：交错退化成"按来源拼接"、去重失效、
#   某个字段悄悄丢了、来源表漏一项 —— 都不报错，只是榜单悄悄变单薄。
RANKS = ROOT / "app" / "ranks.py"
MAIN = ROOT / "app" / "main.py"
RANKS_VUE = ROOT / "frontend" / "src" / "components" / "RanksPanel.vue"
# 发现页组件（空态里的「去推荐逛逛」就在这里）
DISC_VUE = ROOT / "frontend" / "src" / "components" / "DiscoverPanel.vue"

# 来源库的「目录可能不全」备注 —— 2026-10-15 纳入反证。
# ⚠ 它的失败方式：把"这次没看目录"和"这次看过、目录是全的"混成一个语义，
#   于是**顺手记一笔**的调用会把体检刚写下的警告擦掉；反过来，
#   清警告时若写成 `pop`，合并落盘时又会让旧警告从盘上**复活**。
#   两种都不报错，只表现为"警告该有的时候没有 / 该撤的时候撤不掉"。
REGISTRY = ROOT / "app" / "registry.py"
DISCOVERY = ROOT / "app" / "discovery.py"
# 来源库面板（旧 JS，不经 Vite 构建；改动后要同步推线上静态资源）
SOURCES_JS = ROOT / "app" / "static" / "js" / "sources.js"
# 自有来源搜索链路（学到的模板 → 真的能搜出书）
REGSRC = ROOT / "app" / "sources" / "registry_source.py"
SITELEARN = ROOT / "app" / "sitelearn.py"
# 引擎的"断开收手"记账 —— 2026-10-15 纳入反证。
# ⚠ 失败方式：`aborted` 只由**采样**一个阶段回答，断开落在扇出/探测/联网
#   阶段时收手明明发生了却报 False。它不报错，只是让真机断连测试
#   变成"取决于掐断落在哪个窗口"的偶发假红。
ENGINE = ROOT / "app" / "engine.py"
# 「推荐」独立 tab 的接线 —— 2026-10-15 纳入反证。
# ⚠ 失败方式全是静默：导航少一格（手机进不去）、#view-ranks 丢失
#   （切过去白页）、深链不认（分享的链接落到发现页）、点书名不切页
#   （搜索跑完了眼前却什么都没有）。判据在 tools/test_ranks.py P 段。
SHELL_JS = ROOT / "app" / "static" / "js" / "shell.js"
MAIN_JS = ROOT / "app" / "static" / "js" / "main.js"
DISCOVER_JS = ROOT / "app" / "static" / "js" / "discover.js"
RANKS_JS = ROOT / "app" / "static" / "js" / "ranks.js"
APP_CSS = ROOT / "app" / "static" / "css" / "app.css"

TOC_TEST = ROOT / "tools" / "test_toc_full.py"
SAVE_TEST = ROOT / "tools" / "test_adapt_save.py"
LAUNCH_TEST = ROOT / "tools" / "test_chrome_launcher.py"
DIRECT_TEST = ROOT / "tools" / "test_adapt_direct.py"
MOTION_TEST = ROOT / "tools" / "test_motion.py"
RANKS_TEST = ROOT / "tools" / "test_ranks.py"
REGISTRY_TEST = ROOT / "tools" / "test_registry.py"
REGSRC_TEST = ROOT / "tools" / "test_registry_source.py"
FALLBACK_TEST = ROOT / "tools" / "test_discover_fallback.py"
# 搜索总预算 + 搜索账目（tools/test_engine_budget.py）
BUDGET_TEST = ROOT / "tools" / "test_engine_budget.py"
REL_TEST = ROOT / "tools" / "test_relevance.py"
RELEVANCE = ROOT / "app" / "relevance.py"


@dataclass
class Mutation:
    group: str
    name: str          # 破坏了什么（说实话，别美化）
    path: Path
    old: str
    new: str
    test: Path

    @property
    def why(self) -> str:
        return self.name


MUTATIONS: list[Mutation] = [
    # ---------------- 目录/正文读不全（tools/test_toc_full.py）----------------
    Mutation("toc", "`_page_variant` 不剥已有的 `_N`（从续页出发套娃成 `_1_1`）",
             WEB,
             'return f"{m.group(1)}_{n}{m.group(3)}"',
             'return f"{m.group(1)}_{n}{m.group(2)}"',
             TOC_TEST),
    Mutation("toc", "续页只认 `_1.._6`（等于允许往回拼 / 拼自己）",
             WEB,
             "for k in range(cur_n + 1, cur_n + 7):",
             "for k in range(1, 7):",
             TOC_TEST),
    Mutation("toc", "拼到更多章节却仍不完整时，把刚拼到的丢掉（旧行为）",
             WEB,
             "        toc, base = merged, m_url\n",
             "        toc, base = toc, base\n",
             TOC_TEST),
    Mutation("toc", "跟页全失败时保持沉默（不告诉用户『可能不全』）",
             WEB,
             "    if still or partial:\n"
             '        return toc, base, why2 or why or "这份目录可能不完整，只含部分章节"\n'
             '    return toc, base, ""',
             '    return toc, base, ""',
             TOC_TEST),
    Mutation("toc", "判据 C 不认『章号在前』的写法（只认关键词在前）",
             WEB,
             '    re.compile(r"第\\s*(\\d{1,5})\\s*[章节][^第\\n]{0,16}?(?:最新章节|最新更新)"),',
             "",
             TOC_TEST),
    Mutation("toc", "生僻字替换门槛提到 99（几乎不替换）",
             BASE,
             "_subst_min = 3",
             "_subst_min = 99",
             TOC_TEST),
    Mutation("toc", "搜索限速正则少写收括号（历史 bug：永匹配不上）",
             ADAP,
             r"[【\[（(]?\s*(\d{1,3})\s*[】\]）)]?\s*秒",
             r"[【\[（(]?\s*(\d{1,3})\s*秒",
             TOC_TEST),
    Mutation("toc", "`page_url` 不剥已有的 `_N`（从续页拼出 `_1_2`）",
             BASE,
             '    m = re.match(r"^([\\s\\S]*?)(?:_(\\d+))?(\\.[a-z]+)$", url or "", re.I)\n'
             "    if not m:\n"
             "        return None\n"
             '    return f"{m.group(1)}_{n}{m.group(3)}"',
             '    m = re.match(r"^([\\s\\S]*)(\\.[a-z]+)$", url or "", re.I)\n'
             "    if not m:\n"
             "        return None\n"
             '    return f"{m.group(1)}_{n}{m.group(2)}"',
             TOC_TEST),
    Mutation("toc", "续页只走模板式，丢掉声明式兜底",
             CONF,
             "u = webfetch.reading_next_url(cur_html, cur_url) or page_url(cur_url, n + 1)",
             "u = page_url(cur_url, n + 1)",
             TOC_TEST),
    Mutation("toc", "续页只走声明式，丢掉模板式（`(x/y)页` 的站就残了）",
             CONF,
             "u = webfetch.reading_next_url(cur_html, cur_url) or page_url(cur_url, n + 1)",
             "u = webfetch.reading_next_url(cur_html, cur_url)",
             TOC_TEST),
    Mutation("toc", "续页不判『内容没变』（页码越界会把同一页拼 N 遍）",
             CONF,
             "            if not key or key in seen:\n                break",
             "            if not key:\n                break",
             TOC_TEST),
    Mutation("toc", "`_merge_paged` 撞页数上限也不标 pending（静默截断）",
             WEB,
             "    if pages >= budget and _next_page_url(cur_html, cur_base):\n"
             "        pending = True",
             "    if False:\n"
             "        pending = True",
             TOC_TEST),
    Mutation("toc", "「目录可能不全」只写日志、不写进用户看得见的那一步",
             ADAP,
             '               (f"用你给的那一页（{len(d_html)} 字节 · {len(d_toc)} 章）" if same_page\n'
             '                else f"用你给的那一章的目录页（{len(d_html)} 字节 · {len(d_toc)} 章）")\n'
             '               + (f" —— {d_toc_note}" if d_toc_note else ""))',
             '               (f"用你给的那一页（{len(d_html)} 字节 · {len(d_toc)} 章）" if same_page\n'
             '                else f"用你给的那一章的目录页（{len(d_html)} 字节 · {len(d_toc)} 章）"))',
             TOC_TEST),
    Mutation("toc", "`upgrade_toc` 忽略 pending（把被自己停下当完整目录）",
             WEB,
             "        if pending:\n"
             '            return toc, base, m_why or "这个站的目录分了页，还有几页没跟完，可能只含部分章节"\n',
             "",
             TOC_TEST),

    # ---------------- Chrome 启动器（tools/test_chrome_launcher.py）----------------
    # ⚠ 这条要**复现旧代码的判断顺序**（先看进程活不活、再看端口文件），
    #   不是单纯改个常量 —— 只把 GRACE 调小是**没有牙**的：端口文件已经在
    #   第一轮循环里被读到了，根本走不到那个分支（被 mutate 自己抓出来过）。
    Mutation("chrome", "先判『启动器活着吗』再看端口文件（Chrome 155 detach → 全红）",
             SHOT,
             "    while time.time() < deadline:\n"
             "        try:\n"
             "            with open(port_file, \"r\", encoding=\"utf-8\") as f:",
             "    while time.time() < deadline:\n"
             "        if proc.poll() is not None:\n"
             "            raise SystemExit(f\"Chrome 起来就退了（exit={proc.returncode}）\")\n"
             "        try:\n"
             "            with open(port_file, \"r\", encoding=\"utf-8\") as f:",
             LAUNCH_TEST),

    # ---------------- sites.json 落盘（tools/test_adapt_save.py）----------------
    Mutation("save", "读不出本地站点表也照写（把整份配置改写成一条）",
             ADAP,
             "    if LOCAL_SITES.exists():",
             "    if False:",
             SAVE_TEST),
    Mutation("save", "不检查结构（`{whatever:1}` 也会被覆盖成 sites 列表）",
             ADAP,
             '        if not isinstance(data, dict) or not isinstance(data.get("sites"), list):',
             "        if False:",
             SAVE_TEST),
    Mutation("save", "不用原子写（退回先清空再写的 `write_text`）",
             ADAP,
             "        _atomic_write_text(\n"
             '            LOCAL_SITES, json.dumps(data, ensure_ascii=False, indent=2)\n'
             "        )",
             "        LOCAL_SITES.write_text(\n"
             '            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"\n'
             "        )",
             SAVE_TEST),
    Mutation("save", "运行时站点写回 `app/`（部署一覆盖，用户加的站就没了）",
             ADAP,
             "        _atomic_write_text(\n"
             "            LOCAL_SITES, json.dumps(data, ensure_ascii=False, indent=2)\n",
             "        _atomic_write_text(\n"
             "            CONFIG_FILE, json.dumps(data, ensure_ascii=False, indent=2)\n",
             SAVE_TEST),
    Mutation("save", "加载端只读内置站点表（用户加的站看不见）",
             CONF,
             "    for cfg in _read_sites(CONFIG_FILE) + _read_sites(LOCAL_FILE):",
             "    for cfg in _read_sites(CONFIG_FILE):",
             SAVE_TEST),
    Mutation("save", "同名时内置赢（把用户在向导里改过的盖回去）",
             CONF,
             "    for cfg in _read_sites(CONFIG_FILE) + _read_sites(LOCAL_FILE):",
             "    for cfg in _read_sites(LOCAL_FILE) + _read_sites(CONFIG_FILE):",
             SAVE_TEST),
    Mutation("save", "同名不覆盖而是一直追加（站点列表越滚越长）",
             ADAP,
             '    sites = [s for s in sites if not (isinstance(s, dict) and s.get("name") == cfg["name"])]',
             "    sites = list(sites)",
             SAVE_TEST),

    # ---- 适配向导的「责任划分」：用户只管粘地址，剩下我来兜 ----
    Mutation("direct", "用户给章节页时，先「就当它是书页」（把章节页认成书页）",
             ADAP,
             "        direct = (\n"
             "            _detail_via_chapter(given_url, given_html, ad)\n"
             "            or _detail_via_page(given_url, given_html)\n"
             "        )",
             "        direct = (\n"
             "            _detail_via_page(given_url, given_html)\n"
             "            or _detail_via_chapter(given_url, given_html, ad)\n"
             "        )",
             DIRECT_TEST),
    Mutation("direct", "顺着「目录」入口跳时不再判『入口是我上一级』（书页也乱跳）",
             ADAP,
             "        if not _is_under(given_url, target):\n"
             "            continue      # 入口不是我上一级 → 我多半本来就是书页，别乱跳",
             "        if not target:\n"
             "            continue",
             DIRECT_TEST),
    Mutation("direct", "样例/质量判定用未收口的原文（用户看到反爬生僻字）",
             ADAP,
             '    shown = tidy_content(strip_page_mark(text), probe_ch["title"])',
             "    shown = strip_page_mark(text)",
             DIRECT_TEST),
    Mutation("direct", "直接路径不再顺手认搜索结果结构（来源等于没有搜索）",
             ADAP,
             "            s_pat, s_items = _pick_best_link_pattern(\n"
             "                s_html, SEARCH_ITEM_PATTERNS, min_hits=5, chapterish=False\n"
             "            )",
             "            s_pat, s_items = \"\", []",
             DIRECT_TEST),
    Mutation("direct", "试搜一律用向导默认关键词（站里没那本书就判成『没搜索』）",
             ADAP,
             "    probe_kw = book_title or keyword",
             "    probe_kw = keyword",
             DIRECT_TEST),
    Mutation("direct", "拿到试搜页后又重打一次搜索（白白多撞一次限速）",
             ADAP,
             "            if not _looks_like_search_result(s_html, keyword):\n"
             "                s_html, _ = _search_fetch(s_url, s_data)",
             "            s_html, _ = _search_fetch(s_url, s_data)",
             DIRECT_TEST),

    # ---- 品牌层（静态资源）：文案 / 轮换 / 兜底 ----
    Mutation("brand", "首页短句池里塞一句超长的（用户说过『不要太长』）",
             ART_JS,
             '  "书中自有草木香",',
             '  "书中自有草木香，一盏灯下读旧书，窗外风来的时候正好翻到那一页",',
             MOTION_TEST),
    Mutation("brand", "rotateHeroArt 不再把短句写进气泡（池子变死代码）",
             ART_JS,
             '    const line = heroLineFor();\n'
             '    if (line) say.textContent = line;',
             '    const line = heroLineFor();\n'
             '    if (line) say.dataset.line = line;',
             MOTION_TEST),
    Mutation("brand", "index.html 的兜底短句改成池子外的文案（两种气质）",
             INDEX_HTML,
             '<span class="lu-say">书中自有草木香</span>',
             '<span class="lu-say">噜噜噜噜噜</span>',
             MOTION_TEST),

    # ------------- 榜单多来源聚合（tools/test_ranks.py）--------------
    # 这一组的共同点：全是"按一个网站抓"时代留下的写法，改回去**不报任何错**，
    # 只是榜单悄悄退回单一来源 —— 正是用户说的"太单薄"。
    Mutation("ranks", "多来源按顺序拼接，不再交错（旧写法：extend + 截断）",
             RANKS,
             "    return _interleave(buckets, MAX_ITEMS)",
             "    return [x for b in buckets for x in b][:MAX_ITEMS]",
             RANKS_TEST),
    Mutation("ranks", "只抓声明的头 3 个来源（第 4 个声明了却从不去抓）",
             RANKS,
             '    srcs = [s for s in _SOURCES if kind in s["kinds"]]',
             '    srcs = [s for s in _SOURCES if kind in s["kinds"]][:3]',
             RANKS_TEST),
    Mutation("ranks", "结果按**完成顺序**拼桶（名次随响应快慢跳，不报错）",
             RANKS,
             "            buckets = [got.get(i, []) for i in range(len(srcs))]",
             "            buckets = list(got.values())",
             RANKS_TEST),
    Mutation("ranks", "跨来源去重失效（同一本书出现两次）",
             RANKS,
             "            if not key or key in seen:",
             "            if not key:",
             RANKS_TEST),
    Mutation("ranks", "书名归一化形同虚设（《斗破苍穹》与斗破苍穹算两本）",
             RANKS,
             "    s = re.sub(r'[《》「」【】\\s·・.。、,，:：!！?？\\'\"“”‘’()（）\\[\\]\\-—_~～]', \"\", s or \"\")",
             "    s = (s or \"\").strip()",
             RANKS_TEST),
    Mutation("ranks", "xbiquge 按 `</dd>` 逐条切（把「作者：」那一行当成一本书）",
             RANKS,
             '    for chunk in re.split(r"<dd\\s*>\\s*<h3\\s*>", html)[1:]:',
             '    for chunk in re.split(r"</dd>", html)[1:]:',
             RANKS_TEST),
    Mutation("ranks", "xbiquge 不剥书名的 `[分类]` 前缀",
             RANKS,
             '        cat_m = re.match(r"^\\[([^\\]]{1,6})\\]\\s*(.*)$", raw)',
             "        cat_m = None",
             RANKS_TEST),
    Mutation("ranks", "xbiquge 假定每个榜单页的书名都带 `[分类]` 前缀（分类榜会整页空）",
             RANKS,
             '        cat_m = re.match(r"^\\[([^\\]]{1,6})\\]\\s*(.*)$", raw)',
             '        cat_m = re.match(r"^\\[([^\\]]{1,6})\\]\\s*(.*)$", raw)\n'
             '        if not cat_m:\n'
             '            continue',
             RANKS_TEST),
    Mutation("ranks", "xbiquge 悄悄丢掉更新时间字段",
             RANKS,
             '            "updated": _clean(up.group(1)) if up else "",',
             '            "updated": "",',
             RANKS_TEST),
    Mutation("ranks", "xbqg5200 把分类塞进 status（前端会当成『连载/完结』）",
             RANKS,
             '            "category": cat_m.group(1) if cat_m else "",\n'
             '            "words": "",\n'
             '            "updated": "",\n'
             '            "status": "",\n'
             '            "kind": kind,',
             '            "category": cat_m.group(1) if cat_m else "",\n'
             '            "words": "",\n'
             '            "updated": "",\n'
             '            "status": cat_m.group(1) if cat_m else "",\n'
             '            "kind": kind,',
             RANKS_TEST),
    Mutation("ranks", "xbqg5200 的 li 用全等 class 匹配（站点改哈希就整页解析不出）",
             RANKS,
             'r\'<li[^>]*class="[^"]*\\blist-group-item\\b[^"]*"[^>]*>([\\s\\S]*?)</li>\', html',
             'r\'<li[^>]*class="list-group-item item-34e68100"[^>]*>([\\s\\S]*?)</li>\', html',
             RANKS_TEST),
    Mutation("ranks", "xbqg5200 的 url 不拼站点域名（相对地址直接透出）",
             RANKS,
             '            "url": "https://www.xbqg5200.com" + href if href.startswith("/") else href,',
             '            "url": href,',
             RANKS_TEST),
    Mutation("ranks", "周榜的来源被漏掉（目录里有标签却没人供数据）",
             RANKS,
             '    {\n'
             '        "key": "xbiquge-week", "display": "xbiquge.info",\n'
             '        "url": "https://www.xbiquge.info/top/week_0_1.html",\n'
             '        "parser": parse_xbiquge,\n'
             '        "kinds": {"weekvisit"},\n'
             '    },\n',
             "",
             RANKS_TEST),
    Mutation("ranks", "/api/ranks 不再返回 sources（页脚『综合 N 个站点』退化成老文案）",
             MAIN,
             '        "sources": srcs,',
             '        "sources": [],',
             RANKS_TEST),
    Mutation("ranks", "Vue 色相表少一项（与降级 JS 那份不一致）",
             RANKS_VUE,
             "const HUE = { allvisit: 22, weekvisit: 315, allvote: 350",
             "const HUE = { allvisit: 22, allvote: 350",
             RANKS_TEST),

    # ------- 「目录可能不全」备注（tools/test_registry.py）-------
    Mutation("registry", "「这次不评价目录」和「这次查过、目录是全的」混成一个语义"
                         "（顺手记一笔的调用会擦掉体检刚写下的警告）",
             REGISTRY,
             "        if note is not None:",
             "        if note:",
             REGISTRY_TEST),
    Mutation("registry", "清警告用 pop（落盘合并时从盘上复活，警告永远撤不掉）",
             REGISTRY,
             '            cur["note"] = note[:120]',
             '            cur.pop("note", None) if not note else cur.update({"note": note[:120]})',
             REGISTRY_TEST),
    Mutation("registry", "发现流程不再交出目录结论（界面上永远没有那句警告）",
             DISCOVERY,
             '                       note=str(data.get("chapter_note") or ""))\n'
             "    r.score = score_result(r, keyword)",
             "                       )\n"
             "    r.score = score_result(r, keyword)",
             REGISTRY_TEST),
    Mutation("registry", "目录结论不再挂到返回结果上（接口/界面拿不到）",
             DISCOVERY,
             '    if data.get("chapter_note"):\n'
             '        r.chapter_note = str(data["chapter_note"])',
             '    if data.get("chapter_note"):\n'
             "        pass",
             REGISTRY_TEST),
    Mutation("registry", "『可搜源』的判据漏掉健康度（坏站又被算成资产）",
             REGISTRY,
             "    return has_search_tpl(site) and is_healthy(site)",
             "    return has_search_tpl(site)",
             REGISTRY_TEST),
    Mutation("registry", "总览的『可搜源』不走统一判据（数模板不管健康，与列表对不上）",
             REGISTRY,
             "        searchable = sum(1 for s in s_all.values() if is_searchable(s))",
             "        searchable = sum(1 for s in s_all.values() if has_search_tpl(s))",
             REGISTRY_TEST),
    Mutation("registry", "搜索扇出又把判据写了一遍（数模板不管健康，坏站进扇出）",
             REGISTRY,
             "    return {h: s for h, s in sites().items() if is_searchable(s)}",
             "    return {h: s for h, s in sites().items() if has_search_tpl(s)}",
             REGISTRY_TEST),

    # ------- 自有来源搜索链路（tools/test_registry_source.py）-------
    Mutation("regsrc", "抽链接不分组不评分（导航/章节全混进结果）",
             REGSRC,
             "    if not links:\n        return []",
             "    if not links:\n        return []\n    return _dedup_pairs(links)",
             REGSRC_TEST),
    Mutation("regsrc", "章节页不再被排除（最新章节列表冒充搜索结果）",
             REGSRC,
             "    if _CHAPTER_TAIL.search(_path_tpl_of(u)):\n        return False\n"
             "    if _BOOK_PATH.search(_path_tpl_of(u)):\n        return True",
             "    if _BOOK_PATH.search(_path_tpl_of(u)):\n        return True",
             REGSRC_TEST),
    Mutation("regsrc", "build_url 把完整 URL 模板拼到 host 后面（必 404，还记成 fail_down）",
             SITELEARN,
             "    if re.match(r\"^https?://\", tpl, re.I):\n        return path\n"
             "    base = f\"{scheme}://{host}\"",
             "    base = f\"{scheme}://{host}\"",
             REGSRC_TEST),
    Mutation("registry", "/api/registry 的 searchable 退回旧口径（总览与列表两个数字）",
             MAIN,
             '             "searchable": registry.is_searchable(s),',
             '             "searchable": bool((s.get("search_tpl") or "").strip()),',
             REGISTRY_TEST),
    Mutation("registry", "来源库面板不亮「能搜」徽标（攒的资产看不见）",
             SOURCES_JS,
             "    s.searchable\n"
             "      ? `<span class=\"tag ok\" title=\"学过它的站内搜索：搜书时会直接来这个站找，不用再联网\">能搜</span>`\n"
             "      : \"\",",
             "    \"\",",
             REGISTRY_TEST),
    Mutation("registry", "总览统计不显示可搜源数（夜间学的资产没处看）",
             SOURCES_JS,
             "      <span><span class=\"dot ok\"></span>${num(st.sites_searchable)} 能搜</span>\n",
             "",
             REGISTRY_TEST),
    Mutation("registry", "statRow 的计数退回直接插值（绕过 num() 防注入纪律）",
             SOURCES_JS,
             "      <span><span class=\"n\">${num(st.sites)}</span> 个站</span>",
             "      <span><span class=\"n\">${st.sites || 0}</span> 个站</span>",
             REGISTRY_TEST),
    Mutation("registry", "书行不显示「⚠ 可能不全」（章节数会冒充全书）",
             SOURCES_JS,
             '`${b.chapters} 章${b.note ? " ⚠ 可能不全" : ""}</span>`',
             '`${b.chapters} 章</span>`',
             REGISTRY_TEST),

    # ------- 断开收手记账（tools/test_discover_fallback.py）-------
    Mutation("engine", "`aborted` 只认采样阶段（断开落在扇出/探测阶段就不记）",
             ENGINE,
             '                "aborted": bool(aborted or cut_short),',
             '                "aborted": bool(aborted),',
             FALLBACK_TEST),
    Mutation("engine", "`_stop()` 不再置位（收手发生了但没人记账）",
             ENGINE,
             "            if should_stop and should_stop():\n"
             "                cut_short = True\n"
             "                return True",
             "            if should_stop and should_stop():\n"
             "                return True",
             FALLBACK_TEST),
    # ⚠ 靶点别写 `should_stop=_stop)` —— 那个收尾括号会随"给调用加个参数"
    #   而消失（本轮加 budget= 就踩了，突变报"源码脱节"）。锚在**参数本身**上。
    Mutation("engine", "探测阶段直接透传原始 should_stop（绕过唯一的记账点）",
             ENGINE,
             "                               should_stop=_stop, budget=pb)",
             "                               should_stop=should_stop, budget=pb)",
             FALLBACK_TEST),

    # ------- 搜索总预算 + 搜索账目（tools/test_engine_budget.py）-------
    # 线上实测的违约：对外说"最多等 20 秒"，实际 30.3 秒（`耗时ms=30313`）。
    # 三段各有各的满额预算、谁也不看前面花了多少 —— 每段都"正常完成"，
    # 一条错都不报。下面几条专打「某一段偷偷不受总预算约束」。
    Mutation("budget", "预算算成负数（时间过冲时不钳到 0）",
             ENGINE,
             "    left = total - (time.time() - t_start)\n"
             "    return max(0.0, min(want, left))",
             "    left = total - (time.time() - t_start)\n"
             "    return min(want, left)",
             BUDGET_TEST),
    Mutation("budget", "总预算默认值在 def 时求值（之后改常量全不生效）",
             ENGINE,
             "def budget_slice(t_start: float, want: float,\n"
             "                 total: float | None = None) -> float:",
             "def budget_slice(t_start: float, want: float,\n"
             "                 total: float | None = 22.0) -> float:",
             BUDGET_TEST),
    Mutation("budget", "探测永远用满额（不看这一轮还剩多少）",
             ENGINE,
             "            for fut in as_completed(futs, timeout=budget):\n"
             "                if should_stop and should_stop():\n"
             "                    # 客户端断开 → 没必要再把剩下的候选一个个打开验证。",
             "            for fut in as_completed(futs, timeout=PROBE_BUDGET):\n"
             "                if should_stop and should_stop():\n"
             "                    # 客户端断开 → 没必要再把剩下的候选一个个打开验证。",
             BUDGET_TEST),
    Mutation("budget", "预算用光时静默跳过探测（把「没验」伪装成「验过不可用」）",
             ENGINE,
             "                logger.info(\n"
             "                    \"跳过探测：总预算 %.0fs 已用完（已耗 %.1fs）—— %d 个候选保持\"\n"
             "                    \"「未验证」，不再为补徽标让用户多等\",\n"
             "                    SEARCH_TOTAL_BUDGET, time.time() - t_start, len(results))",
             "                pass",
             BUDGET_TEST),
    Mutation("budget", "stats 里不报预算数值（超了也没人知道）",
             ENGINE,
             '                "budget_s": _allow_s,',
             '                "budget_s": 0,',
             BUDGET_TEST),
    Mutation("budget", "抽样那段不看预算（回到各段各自满额的老写法）",
             ENGINE,
             "                aborted = self.verify_samples(results, on_verified=on_verified,\n"
             "                                              should_stop=_stop, budget=sb)",
             "                aborted = self.verify_samples(results, on_verified=on_verified,\n"
             "                                              should_stop=_stop)",
             BUDGET_TEST),

    # ------- 搜索账目：说清楚「候选是怎么没的」-------
    # `search.rank 原始=14 去噪后=2` 说不出那 12 条是什么、为什么被丢，
    # 于是「这本书搜不到」永远无法复盘。
    Mutation("ledger", "被丢的候选不记标题（只留个数字，等于没记）",
             RELEVANCE,
             '            "below_cut": [(r.title[:24], round(r.score, 1))\n'
             '                          for r in ordered if r.score < cut][:8],',
             '            "below_cut": [],',
             REL_TEST),
    Mutation("ledger", "什么都没丢也报丢弃（日志全是噪声，真信号被淹）",
             RELEVANCE,
             '            "below_cut_n": sum(1 for r in ordered if r.score < cut),',
             '            "below_cut_n": 1,',
             REL_TEST),
    Mutation("ledger", "不报门槛值（复盘时判不出是不是阈值太高）",
             RELEVANCE,
             '            "cut": round(cut, 1),',
             '            "cut": 0.0,',
             REL_TEST),
    Mutation("ledger", "不传 report 时就不干活（埋点污染了主流程）",
             RELEVANCE,
             "    if report is not None:\n"
             "        report.clear()",
             "    if report is None:\n"
             "        return []\n"
             "    if report is not None:\n"
             "        report.clear()",
             REL_TEST),
    Mutation("ledger", "引擎不发丢弃明细事件",
             ENGINE,
             'logger, "search.rank.drop", 关键词=keyword,',
             'logger, "search.rank", 关键词=keyword,',
             BUDGET_TEST),
    Mutation("ledger", "丢弃明细里不带标题",
             ENGINE,
             '                例子=[t for t, _ in (rpt.get("below_cut") or [])[:3]]\n'
             '                     + [t for t, _ in (rpt.get("dropped_loose") or [])[:3]])',
             '                例子=[])',
             BUDGET_TEST),

    # ------- 「推荐」独立 tab 的接线（tools/test_ranks.py P 段）-------
    Mutation("rankstab", "底栏没有「推荐」入口（手机上永远进不去推荐页）",
             INDEX_HTML,
             '  <button data-nav="ranks"><i>🏆</i>推荐</button>\n',
             "",
             RANKS_TEST),
    Mutation("rankstab", "#view-ranks 被改名（nav() 切过去找不到页，白屏）",
             INDEX_HTML,
             '<section id="view-ranks" class="hidden" data-view>',
             '<section id="view-ranks-x" class="hidden" data-view>',
             RANKS_TEST),
    Mutation("rankstab", "nav() 的页面清单漏了 ranks（推荐页永远切不进去）",
             SHELL_JS,
             '["home", "ranks", "shelf", "files"]',
             '["home", "shelf", "files"]',
             RANKS_TEST),
    Mutation("rankstab", "深链 #ranks 落到发现页（分享出去的推荐页链接失效）",
             MAIN_JS,
             'else if (h === "#ranks") nav("ranks");',
             'else if (h === "#ranks") nav("home");',
             RANKS_TEST),
    Mutation("rankstab", "searchFromHash 不再切回发现页（推荐页点书名像没反应）",
             DISCOVER_JS,
             '  nav("home");\n  $("#q").value = kw;',
             '  $("#q").value = kw;',
             RANKS_TEST),
    Mutation("rankstab", "降级 JS 点书名绕开 searchFromHash（不切回发现页）",
             RANKS_JS,
             "      searchFromHash(t);",
             '      $("#q").value = t;',
             RANKS_TEST),
    Mutation("rankstab", "把折叠样式加回来（死代码复活，没人会发现）",
             APP_CSS,
             ".ranks[hidden]{display:none}",
             ".ranks[hidden]{display:none}\n.ranks.folded .rk-body{display:none}",
             RANKS_TEST),
    Mutation("rankstab", "推荐页拿不到目录时不说话（点进去一片空白）",
             RANKS_VUE,
             '    <div v-if="!kinds.length" class="rk-err" id="ranksKindsErr">\n'
             '      {{ kindsError || "榜单暂时取不到。" }}\n'
             '      <n-button id="ranksKindsRetry" size="tiny" quaternary @click="retryKinds">重试</n-button>\n'
             '    </div>\n',
             "",
             RANKS_TEST),
    Mutation("rankstab", "降级路径退回静默留白（hidden 掉整块）",
             RANKS_JS,
             "  } catch {\n"
             "    box.hidden = false;\n"
             "    box.innerHTML = '<div class=\"rk-err\" id=\"ranksKindsErr\">'\n"
             "      + \"榜单目录没拿到 —— 可能是网络不通，或访问令牌过期了。</div>\";\n"
             "  }",
             "  } catch {\n"
             "    box.hidden = true;\n"
             "  }",
             RANKS_TEST),
    Mutation("rankstab", "切页不回顶（落地上个页面的半截位置）",
             SHELL_JS,
             "  try { window.scrollTo(0, 0); } catch {}\n",
             "",
             RANKS_TEST),
    Mutation("rankstab", "首页空态的去处指错页（去推荐 → 去书架）",
             DISC_VUE,
             'location.hash = "#ranks"',
             'location.hash = "#shelf"',
             RANKS_TEST),
    Mutation("rankstab", "不记住上次看的榜单类别（每次回到总点击榜）",
             RANKS_VUE,
             '    PRE.set("ranksKind", kind);   // 换过类别就记住（见 cur 的注释）',
             "",
             RANKS_TEST),
    # ⚠ 这条不是"少个功能"，是"点了没反应"：nav() 用 replaceState 改 hash
    #   不触发 hashchange，main.js 的 _lastHash 靠这个广播才跟得上。
    #   删掉广播后，「推荐页 → 发现 → 再点去推荐逛逛」会静默不动。
    Mutation("rankstab", "nav() 不广播 hash（去推荐逛第二次点不动）",
             SHELL_JS,
             '  bus.emit("shell:nav", name);\n',
             "",
             RANKS_TEST),
    # ⚠ 极简档被删的后果不是"不好看"，是按钮掉到折线以下、用户看不见。
    #   真机侧由 test_buttons 固定两个真实视口钉住，这里钉住别把规则清掉。
    Mutation("rankstab", "首屏空态丢掉极简档（第二张插画把入口顶到折线以下）",
             DISC_VUE,
             "#homeEmpty.no-books .empty-art { display: none; }\n",
             "",
             RANKS_TEST),
]


# ---------------------------------------------------------------- 还原保险
_ORIGINALS: dict[Path, str] = {}

# ⚠ 一律用 `newline=""` 读写。为什么不是小事：
#   默认的文本模式会把 **CRLF 归一成 \n**（读）再把 \n **按平台写成 CRLF**（写）。
#   于是"读进来再写回去"看起来内容一样，磁盘上却可能**被换掉整份行尾**。
#   更要命的是 `restore_all()` 的复核用的是同一条归一化读法 —— 它会说
#   "逐字节一致 ✓"，而实际行尾已经变了。这个工具的本职就是"事后把源码
#   恢复原样"，恢复不干净等于把污染留在工作区里。
#   （`.py` 是 CRLF、`app/static/js/*.js` 是 LF，混着来 —— 正好会踩到。）
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", newline="")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="")


# ------------------------------------------------------- 被强杀时的残留还原
# 为什么需要它（2026-10-15 真踩到，代价是一次莫名其妙的"基线全红"）：
#   `check_one()` 用 `try/finally` 还原，可 `finally` **只在 Python 能正常
#   退栈时才跑**。进程被 SIGTERM / 被工具超时杀掉时它不跑，`atexit` 也不跑
#   —— 那条突变就**留在了源码里**。
#   最阴的是下一步：工具紧接着再跑一次，而它是拿"**当前**内容"当基准的
#   （`_load` 第一次读盘就是基准），于是把上一次留下的污染**当成了基线**。
#   表现形式有两种，都不指向真因：
#     · "基线就是红的，跳过"（看着像测试烂了）
#     · 更糟 —— 反证全绿：被破坏的代码恰好和突变方向一致，突变等于没做。
#   对策：每写坏一个文件之前，把它的**原始内容**另存一份到 `_PENDING`；
#   跑完正常还原后把它**清空**；启动时若发现有内容，先还原再干活。
#
#   ⚠ 为什么是"清空"而不是"删除"：一轮全量反证会调它 50+ 次，`unlink()`
#     会撞上沙箱的**批量删除护栏**（实测：`SAFE_DELETE_BULK_CONFIRM_REQUIRED`，
#     整个反证步骤当场判失败 —— 而且报错出现在 mutate 的日志里，看起来像
#     测试烂了，其实是我自己在删文件）。留个空壳既等效，也不触发护栏。
_PENDING = ROOT / "dist" / "tmp" / "mutate_pending.json"
# 上一次写进 `_PENDING` 的内容（内存里去重，避免上百次重复写盘）
_PENDING_LAST: str | None = None


def _save_pending() -> None:
    """记下"已经动过、还没还原"的那些文件的原始内容。"""
    global _PENDING_LAST
    try:
        payload = json.dumps({str(p): t for p, t in _ORIGINALS.items()},
                             ensure_ascii=False)
    except (TypeError, ValueError):
        return
    # 内容没变就别再写 —— 一轮全量反证会调它上百次，而内容只在
    # "第一次碰某个文件"时才会变。少写 100 次纯属顺带。
    if payload == _PENDING_LAST:
        return
    try:
        _PENDING.parent.mkdir(parents=True, exist_ok=True)
        _PENDING.write_text(payload, encoding="utf-8", newline="")
        _PENDING_LAST = payload
    except OSError:
        pass          # 记不下来也不该让反证跑不成（正常退出还会还原）


def _clear_pending() -> None:
    global _PENDING_LAST
    if _PENDING_LAST == "{}":
        return
    try:
        _PENDING.write_text("{}", encoding="utf-8", newline="")
        _PENDING_LAST = "{}"
    except OSError:
        pass


def _recover_pending() -> list[str]:
    """上次跑了一半被杀？先把残留的突变还原掉，再拿干净内容当基准。"""
    try:
        data = json.loads(_PENDING.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not data:
        return []
    fixed: list[str] = []
    for p, text in data.items():
        path = Path(p)
        try:
            if _read(path) != text:
                _write(path, text)
                fixed.append(f"{path.relative_to(ROOT)}")
        except OSError:
            pass
    _clear_pending()
    return fixed


def _load(path: Path) -> str:
    if path not in _ORIGINALS:
        _ORIGINALS[path] = _read(path)
    return _ORIGINALS[path]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _to_lf(text: str) -> str:
    """把 CRLF 归一成 LF，**只在内存里**做替换匹配用。

    ⚠ 为什么必须分两步（匹配用 LF、写盘用原样式）：
      · 突变里的 `old`/`new` 片段是照 `\\n` 写的（人写代码就是敲回车）；
      · 而仓库里的 `.py` 在工作区是 **CRLF**、`app/static/js/*.js` 是 LF。
      如果拿 `\\n` 的片段去 CRLF 的原文里 `in`，**永远找不到** ——
      工具会报"脱节"，而真相是它自己读错了行尾（刚踩过：
      一次全量 5 条 `detached`，看着像测试烂了）。
    """
    return text.replace("\r\n", "\n")


def _in_style(lf_text: str, sample: str) -> str:
    """按 `sample` 的行尾样式把 LF 文本还原（写盘用）。"""
    return lf_text.replace("\n", "\r\n") if "\r\n" in sample else lf_text


def restore_all() -> list[str]:
    """把动过的文件按原内容写回；返回"没能还原"的文件名。"""
    bad: list[str] = []
    for path, text in _ORIGINALS.items():
        try:
            if _read(path) != text:
                _write(path, text)
            if _read(path) != text:
                bad.append(str(path))
        except OSError:
            bad.append(str(path))
    return bad


atexit.register(restore_all)


def _sigterm(signum, frame):   # noqa: ARG001
    """被 SIGTERM 杀掉时也要还原。

    ⚠ 只拦 SIGTERM：SIGKILL 谁也拦不住（那种只能靠 `_PENDING` 兜底），
      SIGINT 交给 Python 默认处理 —— KeyboardInterrupt 会正常退栈、
      走进 `finally`，用不着这里插手。
    """
    left = restore_all()
    _clear_pending()
    print("\n⚠ 被 SIGTERM 终止 —— 已把源码还原回去"
          + (f"（**未能还原**：{left}）" if left else ""), flush=True)
    raise SystemExit(3)


def run_test(test: Path) -> tuple[bool, list[str]]:
    p = subprocess.run([PY, str(test)], cwd=str(ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    reds = [ln.strip() for ln in p.stdout.splitlines() if ln.strip().startswith("✗")]
    return p.returncode == 0, reds


def check_one(m: Mutation) -> tuple[str, str]:
    """返回 (结果, 说明)。结果是 'caught' / 'survived' / 'detached'。"""
    src = _load(m.path)                      # 原样（可能带 CRLF）
    flat = _to_lf(src)                       # 匹配与替换都在 LF 上做
    if m.old not in flat:
        return "detached", "要替换的片段在源码里找不到 —— 测试与代码已脱节"
    if m.old == m.new:
        return "detached", "突变前后一样，等于没改"
    patched = flat.replace(m.old, m.new, 1)
    if patched == flat:
        return "detached", "替换没有改动内容"
    try:
        _write(m.path, _in_style(patched, src))
        if _to_lf(_read(m.path)) == flat:
            # 替换"没落盘"是最隐蔽的假反证：看起来跑过了，其实产品代码没变。
            return "detached", "替换没有真正落盘（源码没变）"
        # ⚠ 必须在**写坏之后**才记待还原清单：否则"没来得及写就崩"也会留下
        #   一条记录，下次启动凭空"还原"一遍（内容其实没变，但白吓一跳）。
        _save_pending()
        ok, reds = run_test(m.test)
    finally:
        _write(m.path, src)
        _clear_pending()
    if ok:
        return "survived", "突变后测试仍然全绿 —— 断言没有牙"
    return "caught", " · ".join(reds[:2])[:150]


def main() -> int:
    ap = argparse.ArgumentParser(description="反证（突变）测试")
    ap.add_argument("groups", nargs="*", help="只跑这些组；缺省=全部")
    ap.add_argument("--list", action="store_true", help="只列出清单")
    args = ap.parse_args()

    groups = args.groups or sorted({m.group for m in MUTATIONS})
    todo = [m for m in MUTATIONS if m.group in groups]
    unknown = set(args.groups) - {m.group for m in MUTATIONS}
    if unknown:
        print(f"没有这些组：{sorted(unknown)}（现有：{sorted({m.group for m in MUTATIONS})}）")
        return 2

    if args.list:
        for m in todo:
            print(f"[{m.group}] {m.name}\n      {m.path.relative_to(ROOT)} → {m.test.name}")
        print(f"共 {len(todo)} 条")
        return 0

    try:
        signal.signal(signal.SIGTERM, _sigterm)
    except (ValueError, OSError, AttributeError):
        pass     # 非主线程 / 平台不支持 —— 还有 `_PENDING` 兜底

    # ⚠ 先清掉上一次被强杀留下的残留突变，再拿基准。
    #   顺序不能反：`_load()` 第一次读盘就是基准，读到的若是污染内容，
    #   整轮反证就全建在错的基线上（轻则"基线就红"，重则全绿而其实没测）。
    leftovers = _recover_pending()
    if leftovers:
        print("⚠ 上一次没跑完，源码里还留着突变 —— 已还原："
              + "、".join(leftovers))
        print("  （`finally` 只在正常退栈时才跑，被强杀时不跑；"
              "而本工具是拿「当前内容」当基准的，残留会被误当成基线。）")

    print(f"反证 {len(todo)} 条（组：{'/'.join(sorted({m.group for m in todo}))}）")
    print("=" * 70)
    bad: list[tuple[str, str, str]] = []
    base_cache: dict[Path, tuple[bool, list[str]]] = {}
    for m in todo:
        # 先确认改动前的基线是绿的 —— 否则"突变后被抓住"毫无意义。
        if m.test not in base_cache:
            base_cache[m.test] = run_test(m.test)
        base_ok, base_reds = base_cache[m.test]
        if not base_ok:
            print(f"?  [{m.group}] 基线就是红的，跳过：{m.name}")
            bad.append((m.group, m.name, f"基线红：{base_reds[:1]}"))
            continue
        got, why = check_one(m)
        if got == "caught":
            print(f"✓ 被抓住  [{m.group}] {m.name}")
            print(f"      {why}")
        else:
            tag = "✗ 存活  " if got == "survived" else "? 脱节  "
            print(f"{tag}[{m.group}] {m.name}")
            print(f"      {why}")
            bad.append((m.group, m.name, why))

    left = restore_all()
    _clear_pending()
    print("=" * 70)
    print(f"突变 {len(todo)} 条 · 问题 {len(bad)} 条")
    for g, n, w in bad:
        print(f"  ✗ [{g}] {n} —— {w}")
    if left:
        print("⚠ 以下文件没能还原，请手动检查：", left)
        return 3
    # 内容哈希复核：确认源码逐字节回到原样。
    # ⚠ 必须用 `_read`（`newline=""`）—— 用默认读法会把 CRLF 归一成 \n，
    #   跟进来时那份**原始字节**文本比就会**误报不一致**；
    #   反过来更糟：真被改坏了行尾它也看不出来。它就是靠这条复核取信的。
    drift = [str(p.relative_to(ROOT)) for p, t in _ORIGINALS.items()
             if _sha(_read(p)) != _sha(t)]
    if drift:
        print("⚠ 源码与进入前不一致：", drift)
        return 3
    print("源码已逐字节还原 ✓")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
