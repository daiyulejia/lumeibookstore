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
import os
import signal
import subprocess
import sys
import time
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
OFFTOPIC_TEST = ROOT / "tools" / "test_offtopic.py"
REGISTRY_TEST = ROOT / "tools" / "test_registry.py"
REGSRC_TEST = ROOT / "tools" / "test_registry_source.py"
# 源熔断（含「源自己吞了异常也要熔断」，见 app/sources/base.py::note_error）
HEALTH_TEST = ROOT / "tools" / "test_source_health.py"
# 熔断器本体（冷却退避 + 跨重启落盘）
HEALTH_PY = ROOT / "app" / "sourcehealth.py"
# 源自己的墙钟上限（tools/test_source_budget.py）
WIKI = ROOT / "app" / "sources" / "wikisource.py"
BUDGET_SRC_TEST = ROOT / "tools" / "test_source_budget.py"
# wyshu 是第二条「没有自带上限」的源 —— 建索引 8 次 + 拼音兜底 8 次
# 串行无上限，卡住时能把整轮搜索拖满 20s（见 tools/test_source_budget.py ⑥~⑩）
WYSHU = ROOT / "app" / "sources" / "wyshu.py"
# 收手判据不许被噪声骗（tools/test_search_recall.py）
RECALL_TEST = ROOT / "tools" / "test_search_recall.py"
# 目录识别：slug 章节 id / 散文集目录（tools/test_toc_anchor.py）
TOC_ANCHOR_TEST = ROOT / "tools" / "test_toc_anchor.py"
DISCOVERY = ROOT / "app" / "discovery.py"
# 自有来源（学到的模板 → 真的能搜出书）
REGISTRY_SOURCE = ROOT / "app" / "sources" / "registry_source.py"
FALLBACK_TEST = ROOT / "tools" / "test_discover_fallback.py"
# 联网核实的账目（tools/test_discover_async.py 第 4 组）—— 「超预算」那条
# ⚠ 失败方式：日志只剩「超预算」半句话，复盘分不清"全核完了只是都不可用"
#   和"还有 N 个压根没核"，两者处置相反。
DISCOVER_ASYNC_TEST = ROOT / "tools" / "test_discover_async.py"
# 搜索总预算 + 搜索账目（tools/test_engine_budget.py）
BUDGET_TEST = ROOT / "tools" / "test_engine_budget.py"
REL_TEST = ROOT / "tools" / "test_relevance.py"
RELEVANCE = ROOT / "app" / "relevance.py"
# HTTP 客户端复用（tools/test_http_client.py）
UTILS = ROOT / "app" / "utils.py"
HTTP_TEST = ROOT / "tools" / "test_http_client.py"
# 学站吞吐（tools/test_registry.py 的「学站吞吐」组）
DISCOVERY = ROOT / "app" / "discovery.py"
# 可搜源「是不是真的在按关键词搜」（tools/test_search_trust.py）
TRUST_TEST = ROOT / "tools" / "test_search_trust.py"
# 上线链条本身（tools/test_ship_chain.py）—— 破坏的是"上线动作"而不是产品。
# ⚠ 这一组是"判据的判据"：清单漏项、突变脱节、推送丢失，三者都表现为
#   "所有测试绿、该做的事没做"。改 ship.py 时顺手验一下它还有没有牙。
SHIP_PY = ROOT / "tools" / "ship.py"
CHAIN_TEST = ROOT / "tools" / "test_ship_chain.py"


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

    # ------------- 非小说站拦截（tools/test_offtopic.py）--------------
    # ⚠ 这一组之前**一条反证都没有**（漏项）。它的失败方式全是静默的：
    #   漫画/音乐站混在候选池里、轻小说站被误清掉、判据能匹配空串 ——
    #   都不报错，只表现为"搜索里混进一堆给不出书的站"或者"某个小说站
    #   用着用着就不见了"。
    Mutation("offtopic", "判据表里混进「动漫」（哔哩轻小说这类站被清掉）",
             REGISTRY,
             r'r"漫画|漫畫|音乐|音樂|影视|电影|剧集|视频|壁纸|写真|"',
             r'r"漫画|动漫|漫畫|音乐|音樂|影视|电影|剧集|视频|壁纸|写真|"',
             OFFTOPIC_TEST),
    Mutation("offtopic", "漫画/音乐站完全不判（旧行为，它们继续占着候选位）",
             REGISTRY,
             r'r"漫画|漫畫|音乐|音樂|影视|电影|剧集|视频|壁纸|写真|"',
             r'r""',
             OFFTOPIC_TEST),
    Mutation("offtopic", "只看 host 不看站名（教程站/漫画站全放回来）",
             REGISTRY,
             '    return bool(_OFFTOPIC_NAME_RE.search(str(site.get("name") or "")))',
             "    return False",
             OFFTOPIC_TEST),
    Mutation("offtopic", "站名是空串就判成非小说站（爬不到名字的站全被误杀）",
             REGISTRY,
             '    return bool(_OFFTOPIC_NAME_RE.search(str(site.get("name") or "")))',
             '    _n = str(site.get("name") or "")\n'
             '    return (not _n) or bool(_OFFTOPIC_NAME_RE.search(_n))',
             OFFTOPIC_TEST),

    # ------------- hodei 一页十榜（tools/test_ranks.py R/S 段）--------------
    # ⚠ 这一组的共同点：改错**不会报错**，只是四个标签点开是同一份数据
    #   （或者悄悄变成"把默认序当总推荐榜"）。判据必须钉"四份数据不同"。
    Mutation("rankhodei", "按 id 取第一个 tabData 块（四个榜全是「总点击」那一份）",
             RANKS,
             "    for name, rows in blocks:\n"
             "        if name == tab:                 # ⚠ 整串相等，不许用 `in`\n"
             "            picked = rows\n"
             "            break",
             "    for name, rows in blocks:\n"
             "        picked = rows\n"
             "        break",
             RANKS_TEST),
    Mutation("rankhodei", "周榜的块名映射写错（那个来源静默空掉）",
             RANKS,
             '    "weekvisit": "周点击",',
             '    "weekvisit": "本周期",',
             RANKS_TEST),
    Mutation("rankhodei", "默认序冒充榜单的守卫失效（把站点的默认入库序当总收藏榜给用户）",
             RANKS,
             "        same = ([r[\"title\"] for r in dflt] == [r[\"title\"] for r in picked])",
             "        same = False",
             RANKS_TEST),
    Mutation("rankhodei", "守卫一刀切（名单不同也判没数据，那一榜永远是空的）",
             RANKS,
             "        same = ([r[\"title\"] for r in dflt] == [r[\"title\"] for r in picked])",
             "        same = True",
             RANKS_TEST),
    Mutation("rankhodei", "把站点的最近更新日期丢了（榜单上看不到「更新」）",
             RANKS,
             '                "updated": _clean(hit.group(1)) if hit else "",',
             '                "updated": "",',
             RANKS_TEST),
    Mutation("rankhodei", "作者没解析出来（榜单只剩书名）",
             RANKS,
             '                "author": _clean(au.group(1)) if au else "",\n'
             '                "url": "https://www.hodei.net" + tag.group(1),',
             '                "author": "",\n'
             '                "url": "https://www.hodei.net" + tag.group(1),',
             RANKS_TEST),
    Mutation("rankhodei", "「一页多榜」的 HTML memo 失效（7 类刷新把同一页抓 4 遍）",
             RANKS,
             '    if once:\n        now = time.time()',
             '    if False:\n        now = time.time()',
             RANKS_TEST),
    Mutation("rankhodei", "所有来源都当 once 用（榜单内容永远停在一小时前）",
             RANKS,
             '    once = bool(src.get("once"))',
             "    once = True",
             RANKS_TEST),
    Mutation("rankhodei", "清缓存时不清 HTML memo（点「刷新」内容不变）",
             RANKS,
             "        _MEMO.clear()\n",
             "",
             RANKS_TEST),

    # ------------- 来源表本身（tools/test_ranks.py L/S 段）--------------
    # ⚠ 这一组改的都是**配置**，改错不报错、只表现为"某类榜单少一家/抓错页"。
    #   2026-10-22 线上实测就是靠逐类数 source 集合才发现的。
    Mutation("ranksource", "落霞 5 个类目共用一个地址（抓错页：/top.html 是热门混排）",
             RANKS,
             '        "url": "https://www.luoxiaks.net/rank/{kind}/",',
             '        "url": "https://www.luoxiaks.net/top.html",',
             RANKS_TEST),
    Mutation("ranksource", "落霞少声明一类（allvote 退回单源，页脚却照写 N 家）",
             RANKS,
             '        "kinds": {"allvisit", "allvote", "weekvisit", "monthvisit", "goodnum"},',
             '        "kinds": {"allvisit", "weekvisit", "monthvisit", "goodnum"},',
             RANKS_TEST),
    Mutation("ranksource", "hodei 的月点击映射成总点击（月榜 = 总榜的复制品）",
             RANKS,
             '    "monthvisit": "月点击",',
             '    "monthvisit": "总点击",',
             RANKS_TEST),
    Mutation("ranksource", "把空壳页也声明成来源（384g 的月榜是 4471 字节 0 条）",
             RANKS,
             '        "kinds": {"allvisit", "allvote", "goodnum", "postdate", "lastupdate"},',
             '        "kinds": {"allvisit", "allvote", "goodnum", "monthvisit",'
             ' "postdate", "lastupdate"},',
             RANKS_TEST),
    Mutation("ranksource", "把数据造假的「总字数榜」加回目录（唯一来源的字数列自相矛盾）",
             RANKS,
             '    {"kind": "monthvisit", "label": "本月热读", "desc": "这一个月被点开最多的"},',
             '    {"kind": "monthvisit", "label": "本月热读", "desc": "这一个月被点开最多的"},\n'
             '    {"kind": "size", "label": "总字数榜", "desc": "篇幅最长的"},',
             RANKS_TEST),

    # ------- 榜单抓取接熔断器（tools/test_ranks.py T 段）-------
    # ⚠ 这一组的失败方式全是**静默**的：坏源照旧每 30 分钟重撞一次，
    #   只是定时刷新偶尔撞满预算、有几类榜不更新，日志里查不出来。
    Mutation("ranksbreaker", "熔断检查形同虚设（打不通的站照样每轮重撞）",
             RANKS,
             "    if not HEALTH.allows(_breaker_key(src[\"key\"])):",
             "    if False:",
             RANKS_TEST),
    Mutation("ranksbreaker", "榜单和搜索共用一本账（一方成功就把另一方的退避清零）",
             RANKS,
             '    return f"ranks:{key}"',
             "    return key",
             RANKS_TEST),
    Mutation("ranksbreaker", "抓取失败不记账（熔断永远不会触发）",
             RANKS,
             '            _note_fail(src["key"], kind, e)',
             "            pass",
             RANKS_TEST),
    Mutation("ranksbreaker", "抓取成功不清账（抖动的源被一路按 8 小时冷却）",
             RANKS,
             '        _note_ok(src["key"])',
             "        pass",
             RANKS_TEST),
    Mutation("ranksbreaker", "刷新日志不写「哪几类没跑完」（事后查不出漏哪类）",
             MAIN,
             '              成功=rep.get("ok"), 失败=rep.get("failed"),\n'
             '              跳过=rep.get("skipped"), 没跑完=rep.get("pending"),\n',
             '              成功=rep.get("ok"), 失败=rep.get("failed"),\n'
             '              跳过=rep.get("skipped"),\n',
             RANKS_TEST),
    Mutation("ranksource", "把被 JS 挑战墙拦住的站加回来源表（页脚多数一个站、每轮白撞）",
             RANKS,
             "    # ⚠ 2026-10-22 摘掉 xbqg5200：整站被 JS 挑战墙拦住"
             "（`/top.html` 与 `/` 都",
             '    {"key": "xbqg5200", "display": "xbqg5200.com",'
             ' "url": "https://www.xbqg5200.com/top.html",'
             ' "parser": parse_xbqg5200, "kinds": {"allvisit"}},\n'
             "    # ⚠ 2026-10-22 摘掉 xbqg5200：整站被 JS 挑战墙拦住"
             "（`/top.html` 与 `/` 都",
             RANKS_TEST),

    # ------- 模板复核（reverify）的时间上限（tools/test_search_trust.py）-------
    # ⚠ 这一组的失败方式是"接口越跑越久"：线上实测 211.7 秒一条请求，
    #   而日志里只有 `ms="211711 慢"`，看不出时间花在哪一段。
    Mutation("reverifybudget", "复核不再检查时限（又变成一秒上限都没有）",
             DISCOVERY,
             "        if deadline is not None and time.monotonic() >= deadline:",
             "        if False:",
             TRUST_TEST),
    Mutation("reverifybudget", "撞预算收手时不报「还欠几个」（悄悄收手）",
             DISCOVERY,
             "            pending = len(todo) - idx",
             "            pending = 0",
             TRUST_TEST),
    Mutation("reverifybudget", "复核预算没有封顶（站一多就线性变慢）",
             DISCOVERY,
             "               min(_REVERIFY_BUDGET_MAX,\n"
             "                   _REVERIFY_BUDGET_PER_SITE * max(n_targets, 1)))",
             "               _REVERIFY_BUDGET_PER_SITE * max(n_targets, 1))",
             TRUST_TEST),
    Mutation("reverifybudget", "学站接口不埋点（只剩一行 ms=211711 慢）",
             MAIN,
             '    log_event(logger, "source.learn",\n',
             '    log_event(logger, "source.learn.nope",\n',
             TRUST_TEST),
    Mutation("reverifybudget", "复核拿不到结果就收工（假站多活 24 小时）",
             DISCOVERY,
             "_REVERIFY_ATTEMPTS = 2",
             "_REVERIFY_ATTEMPTS = 1",
             TRUST_TEST),
    Mutation("reverifybudget", "复核重试时不等（同域限速还没解除，等于白问）",
             DISCOVERY,
             "_REVERIFY_RETRY_WAIT = 1.0",
             "_REVERIFY_RETRY_WAIT = 0.0",
             TRUST_TEST),

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
             "    return (has_search_tpl(site) and _tpl_can_search(site)\n"
             "            and is_healthy(site))",
             "    return (has_search_tpl(site) and _tpl_can_search(site))",
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
    Mutation("ledger", "把「同站重名去重」算成「非确切命中被挤掉」（账目错比没账目更坏）",
             RELEVANCE,
             '            "loose": [(r.title[:24], round(r.score, 1)) for r in loose][:8],',
             '            "loose": [(r.title[:24], round(r.score, 1)) for r in deduped][:8],',
             REL_TEST),
    Mutation("ledger", "丢弃明细里不带标题",
             ENGINE,
             '                例子=[t for t, _ in (rpt.get("below_cut") or [])[:3]]\n'
             '                     + [t for t, _ in (rpt.get("loose") or [])[:3]])',
             '                例子=[])',
             BUDGET_TEST),

    # ------- 源账：谁答了、谁挂了、谁没回来，必须加得起来 -------
    # 线上 2026-10-22 00:10 的 `答=3/7 超=4 挂=wikisource,xbqg5200`
    # 三个数加起来是 9 > 7 —— 账加不起来，复盘还是得回头翻散落的 source.fail。
    Mutation("源账", "「答」退回数「交回 future 的源」（403 的源也混进答里）",
             ENGINE,
             '                "sources_answered": _ok_n,',
             '                "sources_answered": done_count,',
             BUDGET_TEST),
    Mutation("源账", "没回来的源只留个数、不留名字（等于没记）",
             ENGINE,
             '                "unreturned_sources": _unret_names + _skip_names,',
             '                "unreturned_sources": [],',
             BUDGET_TEST),
    Mutation("源账", "只在撞满墙钟时记未回（提前收手的那批静默消失）",
             ENGINE,
             "                if fut.cancelled():\n"
             '                    _mark(src.name, "skip")\n'
             "                elif not fut.done():\n"
             '                    _mark(src.name, "hang")',
             "                pass",
             BUDGET_TEST),
    # ⚠ 2026-10-24 换靶：这条原来是打在 test_engine_budget 的场景 A 上。
    #   给收手加了「到 SEARCH_MIN_WAIT 就醒来重判」之后，场景 A 不再靠撞满
    #   墙钟收手（命中条件满足了就立刻走），于是 `hit_deadline=True 且有结果`
    #   这个组合在那边消失了 —— 突变实施后测试仍全绿 = 断言失去牙。
    #   现在在 tools/test_search_recall.py 场景③ 里重建了这个组合
    #   （撞满 0.7s 软截止、kept=12、tight=0），靶点改指过去。
    #   ⚠ 2026-10-26 换靶 + 加靶：判据从 `kept` 改成 `pushed`（弱匹配带会
    #   出现 kept>0 而 pushed=0），原来的靶点字符串已经不存在，改成挂在
    #   续行上；另外补两条，分别反证「退回 kept」和「用 kept 冒充 pushed」。
    Mutation("源账", "「卡满」判据退回成只看 hit_deadline（有结果也报卡满）",
             ENGINE,
             '                          and not stats.get("pushed")) else "否",',
             '                          ) else "否",',
             RECALL_TEST),
    Mutation("源账", "「卡满」判据退回 kept（弱匹配带上空等满墙钟也被报成「否」）",
             ENGINE,
             '                          and not stats.get("pushed")) else "否",',
             '                          and not stats.get("kept")) else "否",',
             RECALL_TEST),
    Mutation("源账", "推送数用最终候选数冒充（空等满墙钟那一类从此看不见）",
             ENGINE,
             '                "pushed": streamed,',
             '                "pushed": len(results),',
             RECALL_TEST),
    Mutation("源账", "收手日志退回两态「仍无结果」（原始候选摆在眼前也这么说）",
             ENGINE,
             '                         (f"原始 {len(raw)} 条但没有一条够推送门槛"',
             '                         ("仍无结果"',
             RECALL_TEST),
    Mutation("源账", "学站撞预算只报个数（不知道是哪几个站没学）",
             DISCOVERY,
             '                    len(todo) - finished, ", ".join(left_hosts) or "-")',
             '                    len(todo) - finished, "-")',
             REGISTRY_TEST),
    Mutation("源账", "自有源撞预算只报个数（不知道是哪个站慢）",
             REGISTRY_SOURCE,
             '                        ", ".join(left_hosts) or "-")',
             '                        "-")',
             REGSRC_TEST),
    # ------- 源账补格：「该搜而没搜」必须单独占一格（2026-10-25） -------
    # 线上 10-24 09:04:59《红楼梦》《剑来》：`答=0/0 候选=0 耗时ms=2`。
    # 一个请求都没发出去，却和"搜遍了都没有"长得一模一样。
    Mutation("源账", "熔断跳过的源不进账（全灭时又退回「答=0/0」的假干净）",
             ENGINE,
             '        "熔断": _pack(stats.get("sources_breaker", 0), names_brk),',
             '        "熔断": _pack(0, []),',
             BUDGET_TEST),
    Mutation("源账", "分母不含熔断跳过的源（应搜 1 个被写成 0 个）",
             ENGINE,
             '                "sources_total": len(targets) + len(skipped),',
             '                "sources_total": len(targets),',
             BUDGET_TEST),
    Mutation("源账", "全灭时不吭声（沉默地返回 0 条）",
             ENGINE,
             "                logger.info(\"本轮一个源都没能搜：目标源全部在熔断中（%s）——\"\n"
             "                            \"结果为空不代表没有这本书\", \", \".join(skipped))",
             "                pass",
             BUDGET_TEST),
    Mutation("源账", "联网兜底没跑却不记账（「没联网」和「联网没找到」混为一谈）",
             ENGINE,
             "                web_skipped_budget = True",
             "                web_skipped_budget = False",
             BUDGET_TEST),

    # ------- 目录识别：slug 章节 id / 散文集目录（2026-10-31） -------
    # 线上原样（《我的阿勒泰》）：`候选=1 确切=1 可读=0`，联网说「站点都打不开」。
    # 真相是 cn.shubaoc.com 是**真的书页**，40 章目录，
    # 但章节 id 是 base32（`1u0ri`）→ 模板被拆成 42 份 → 0 章；
    # 而目录标题不叫「第N章」→ 就算归对了模板也只给 0.35 分。
    # 三本书（乡土中国 / 素食者 / 我的阿勒泰）全是这一类。
    Mutation("目录锚点", "模板退回只认 \\d+（slug 站 42 章拆成 42 个单条组）",
             WEB,
             'return p.netloc + "/".join(_norm_seg(s) for s in p.path.split("/"))',
             'return p.netloc + re.sub(r"\\d+", "#", p.path)',
             TOC_ANCHOR_TEST),
    Mutation("目录锚点", "toc_quality 不认页面目录区标记（散文集目录永远 0.35）",
             WEB,
             '    anchored = sum(1 for c in head if c.get("_anchor"))',
             "    anchored = 0.0",
             TOC_ANCHOR_TEST),
    Mutation("目录锚点", "排序不再优先「挂在这本书下」（猜你喜欢顶掉真目录）",
             WEB,
             "    cands.sort(key=lambda c: (c[2] == hint, c[4] >= 0.8, c[0] >= 0.55, c[0], c[1]),",
             "    cands.sort(key=lambda c: (c[2] == hint, c[0] >= 0.55, c[0], c[1]),",
             TOC_ANCHOR_TEST),
    Mutation("目录锚点", "「不是目录」不记账（核实 5 个、日志只有 2 条失败）",
             DISCOVERY,
             '        _bump(tally, "not_toc", host)',
             "        pass",
             TOC_ANCHOR_TEST),
    Mutation("目录锚点", "「不是目录」的日志降成 debug（线上 INFO 级别下静默消失）",
             DISCOVERY,
             '        logger.info("候选不是目录 %s: kind=%s 标题=《%s》 %s",',
             '        logger.debug("候选不是目录 %s: kind=%s 标题=《%s》 %s",',
             TOC_ANCHOR_TEST),

    # ------- 联网兜底的门：有结果但一条可读都没有（2026-10-27） -------
    # 线上原样（《我的阿勒泰》）：`候选=1 成书=1 确切=1 可读=0 联网发现=0`。
    # 唯一候选是确切命中（100 分）但是个死链，收手门 1.5s 就被它喂饱 →
    # exhausted 恒假 → 「本地交不出能读的 → 出去找」这条分支一次都进不去。
    Mutation("联网门", "把「全不可读」这一类的门票退回 exhausted（死链挡住联网兜底）",
             ENGINE,
             "            and not any(r.available for r in results))",
             "            and False)",
             FALLBACK_TEST),
    Mutation("联网门", "「有没有验过」不认 probe（probe=0 时把未验证当成全打不开）",
             ENGINE,
             "            bool(results) and bool(probe)",
             "            bool(results)",
             FALLBACK_TEST),
    Mutation("联网门", "该联网却没跑时不记原因（web_skip 恒空 → 与「跑过」同形）",
             ENGINE,
             '        web_skip = "not_needed" if not need_web else ""',
             '        web_skip = ""',
             FALLBACK_TEST),

    # ------- 召回：收手判据不许被噪声骗（2026-10-24） -------
    # 线上真机复现：搜《兄弟》扇出 1.76s 收手、候选 4 条全是「嘿兄弟/兄弟盟」，
    # 而 kunnu8 恰好在 1.76s 带着正主《兄弟》回来 —— 被弃。
    # 用户看到"4 条候选、没一本是那本书"= 搜不到，日志里 `候选=4` 却像成功。
    Mutation("召回", "收手不再要求「有确切命中」（噪声满屏就收手，正主被弃）",
             ENGINE,
             "                    _tight_ok = tight_streamed > 0",
             "                    _tight_ok = True",
             RECALL_TEST),
    Mutation("召回", "收手条件①②③永久关掉（一律等满软截止，召回回来了但慢 4.5s）",
             ENGINE,
             "                    _tight_ok = tight_streamed > 0",
             "                    _tight_ok = False",
             RECALL_TEST),
    Mutation("召回", "确切命中从不计数（等于那道门永远关着）",
             ENGINE,
             "                            if it.tight:\n"
             "                                tight_streamed += 1",
             "                            pass",
             RECALL_TEST),
    # ⚠ 2026-10-25 换靶：`tight_hits` 的口径从「扇出阶段累加值」改成
    #   「最终结果集里 tight 的条数」，旧靶点（`"tight_hits": tight_streamed,`）
    #   已经不存在。新靶点直接**复原今天这个 bug 本身**：
    #   把最终结果集换成扇出的累加值 → 联网兜底救回的正主又被记成 0。
    #   牙在 test_search_recall.py 场景⑤（本地全空、只有联网那条正主）。
    Mutation("召回", "确切只数扇出阶段（联网兜底救回的正主被记成 0 条）",
             ENGINE,
             '                "tight_hits": sum(1 for r in results if r.tight),',
             '                "tight_hits": tight_streamed,',
             RECALL_TEST),
    Mutation("召回", "收手日志里的确切条数写错（复盘时看不出是 0 条确切还是 13 条）",
             ENGINE,
             "                            len(raw), streamed, tight_streamed, elapsed,",
             "                            len(raw), streamed, streamed, elapsed,",
             RECALL_TEST),
    Mutation("召回", "收手判断没有唤醒机制（条件满足了也要等到下一个源回来）",
             ENGINE,
             "                wake = min(ceiling, SEARCH_MIN_WAIT) if elapsed < SEARCH_MIN_WAIT else ceiling",
             "                wake = ceiling",
             RECALL_TEST),
    Mutation("召回", "「醒来重判」被当成「等到底了」（0.1s 就收手并喂熔断器）",
             ENGINE,
             "                    if time.time() - t_search < ceiling - 0.02:\n"
             "                        continue",
             "                    if False:\n"
             "                        continue",
             RECALL_TEST),

    # ------- 源墙钟：wyshu 是「第二个没有上限的源」（2026-10-24） -------
    # 线上实测搜《我们猫猫不能听这些》：01:0x 耗时 20040ms 候选=0 未回=wyshu，
    # 5 分钟后同一本 7840ms 候选=1。差的就是 wyshu 这轮回没回来。
    Mutation("源墙钟", "wyshu 建索引到点照发下一次请求（8 个分类串行无上限）",
             WYSHU,
             "            if deadline is not None and time.time() >= deadline:\n"
             "                complete = False",
             "            if False:\n"
             "                complete = False",
             BUDGET_SRC_TEST),
    Mutation("源墙钟", "拼音兜底不认 deadline（第二段还是 8 次请求）",
             WYSHU,
             "            if deadline is not None and time.time() >= deadline:\n"
             "                logger.info(\"拼音兜底到点收手",
             "            if False:\n"
             "                logger.info(\"拼音兜底到点收手",
             BUDGET_SRC_TEST),
    Mutation("源墙钟", "残缺索引也写缓存（缺口被固化 24 小时，而且最难被怀疑）",
             WYSHU,
             "        if books and complete:",
             "        if books:",
             BUDGET_SRC_TEST),
    Mutation("源墙钟", "索引为空也静默返回（熔断器永远学不到，每轮还在付时间）",
             WYSHU,
             '            self.note_error(RuntimeError("索引为空：分类页全部抓取失败"))',
             "            pass",
             BUDGET_SRC_TEST),

    # ------- 学站吞吐：单站成本必须与预算同量级 -------
    # 线上实测：120 秒预算只学完 0~1 个站（还剩 23 个），因为抓首页没走
    # fast_mode，一个死站最坏 200 秒。见 app/discovery.py 的注释。
    Mutation("learn", "学站抓首页不走 fast_mode（死站最坏 200 秒）",
             DISCOVERY,
             "            with fast_mode(retries=0, timeout=_LEARN_FETCH_TIMEOUT):\n"
             "                try:\n"
             "                    html, final = fetch_text(page_url, with_url=True)\n"
             "                except Exception:  # noqa: BLE001\n"
             "                    page_url = f\"http://{host}/\"      # 老站只有 http\n"
             "                    html, final = fetch_text(page_url, with_url=True)",
             "            try:\n"
             "                html, final = fetch_text(page_url, with_url=True)\n"
             "            except Exception:  # noqa: BLE001\n"
             "                page_url = f\"http://{host}/\"      # 老站只有 http\n"
             "                html, final = fetch_text(page_url, with_url=True)",
             REGISTRY_TEST),
    Mutation("learn", "每站预算比最坏单站成本还小（「还剩 N 个」变成假数）",
             DISCOVERY,
             "_LEARN_BUDGET_PER_SITE = 16.0",
             "_LEARN_BUDGET_PER_SITE = 8.0",
             REGISTRY_TEST),

    # ------- 联网兜底也要认「客户端已断开」（test_discover_fallback §6）-------
    # 这一段原先完全不认 should_stop，而它是最贵的一段（3~10 秒）。
    # 后果：用户走了还在往外搜，且 aborted 漏报 → 断连测试偶发假红。
    # ⚠ 只在 `_discover` 内部检查一次就够了（外层再查是死代码，已删）；
    #   这条突变就是"内部不检查"——反证能抓住。
    Mutation("discstop", "多词联网兜底中途断了也不停（继续搜下一个词）",
             ENGINE,
             "                if should_stop and should_stop():\n"
             "                    logger.info(\"客户端已断开，联网兜底提前收手（还有 %d 个词没搜）\",\n"
             "                                len(looks) - i_look)\n"
             "                    break",
             "                if False:\n"
             "                    logger.info(\"客户端已断开，联网兜底提前收手（还有 %d 个词没搜）\",\n"
             "                                len(looks) - i_look)\n"
             "                    break",
             FALLBACK_TEST),

    # ------- HTTP 客户端：切换 verify 不许关掉别人的 client -------
    # 线上实证（02:54 搜《斗破苍穹》）：两个不同的源在同一秒报
    # `Cannot send a request, as the client has been closed.` ——
    # 一个自签站触发 TLS 降级，把并发线程正在用的 client 关了。
    Mutation("httpclient", "切 verify 时把别的槽位一起关掉（老实现，跨线程关死）",
             UTILS,
             "        cur = _make_client(verify=verify, use_proxy=use_proxy)\n",
             "        for _c in list(_clients.values()):\n"
             "            _c.close()\n"
             "        _clients.clear()\n"
             "        cur = _make_client(verify=verify, use_proxy=use_proxy)\n",
             HTTP_TEST),
    Mutation("httpclient", "拿到已关闭的 client 也不重建（请求必然报 client closed）",
             UTILS,
             "        if cur is not None and not cur.is_closed:\n"
             "            return cur",
             "        if cur is not None:\n"
             "            return cur",
             HTTP_TEST),

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

    # ------------------------------------------------------------------
    # 可搜源必须真的在按关键词搜（tools/test_search_trust.py）
    # ------------------------------------------------------------------
    # 线上实测（2026-10-21）：21 个"已学会搜索"的站里 **9 个是假的**。
    # 它们形如 `/?q={kw}`，站点不认这个参数，照常返回首页/分类导航 ——
    # 首页当然有一堆"像章节的链接"，旧判据（数到 ≥3 条就算成）全放过。
    # 后果不是"搜出错书"，而是"综合 N 站"这个数字掺水：
    # 那 9 个站永远贡献不了结果，每次搜索却要多打它们一遍。
    Mutation("trust", "控制实验恒放行（等于没做控制实验，假模板照样学会）",
             SITELEARN,
             '    if not control_kw:\n        return "unknown"',
             '    if True:\n        return "unknown"',
             TRUST_TEST),
    Mutation("trust", "learn_site 跳过控制实验（只数链接就认）",
             SITELEARN,
             "        if control_says_fake(tpl, host, enc=enc, scheme=scheme, method=method,",
             "        if False and control_says_fake(tpl, host, enc=enc, scheme=scheme, method=method,",
             TRUST_TEST),
    Mutation("trust", "阈值放宽到 0.9（假站的分类导航页就漏过去了）",
             SITELEARN,
             "CONTROL_SAME_RATIO = 0.5",
             "CONTROL_SAME_RATIO = 0.9",
             TRUST_TEST),
    Mutation("trust", "scheme 写死 https（老站只有 http，明明有 form 也验不过）",
             SITELEARN,
             '        if s in ("http", "https"):\n            return s\n    return detect_scheme(host)',
             '        s = ""\n    return "https"',
             TRUST_TEST),
    Mutation("trust", "爆破表又把 `/?s=` 挪到后面（预算覆盖不到 = 表里没有）",
             SITELEARN,
             '    for path in ("/?s=", "/?q=", "/?search="):',
             '    for path in ("/?q=", "/?search="):',
             TRUST_TEST),
    # 线上实测：第一轮复核只撤掉 5 个（该撤 9 个），漏掉的都是"库里没有
    # 这本书的书名"或"这本书在这站搜不到"的站 —— 通用书名兜底就是补这个洞。
    Mutation("trust", "复核只用库里的书名探测（没书名的假站永远漏过去）",
             DISCOVERY,
             "        if sitelearn.CANARY_KW not in probes:\n"
             "            probes.append(sitelearn.CANARY_KW)",
             "        if False:\n"
             "            probes.append(sitelearn.CANARY_KW)",
             TRUST_TEST),
    # 线上实测：www.xxsy.net 上一轮"没判出结论"（站上那本书搜不到）却被盖了
    # 已核实的章，于是它带着假模板活到下一轮，再也不会被检查。
    # ⚠ 原先这里有一条「复核没结论也盖章」，现在由 `verdict` 组的同名突变负责
    #   （锚点更短、覆盖三态语义）—— 留两条只会有一条先脱节，白吵。

    # ------------------------------------------------------------------
    # 学站失败账必须带学习器版本号（tools/test_registry.py）
    # ------------------------------------------------------------------
    # 线上 92 个站没有搜索模板，其中 89 个 search_fail 顶到 3（永久放弃），
    # 而那批失败正是学习器自己的缺陷造成的。修好学习器却不动历史计数，
    # 那 89 个站仍然被挡在门外 —— 用户看到的可搜源**一个都不会变**。
    Mutation("learnver", "判失败次数时不看版本号（学习器改好了也救不回那 89 个站）",
             REGISTRY,
             '    if int(site.get("search_fail_ver") or 0) != LEARN_VER:\n'
             "        return 0\n"
             '    return int(site.get("search_fail") or 0)',
             '    return int(site.get("search_fail") or 0)',
             REGISTRY_TEST),
    Mutation("learnver", "换版本后第一次失败不重置计数（旧账立刻又被抄回来）",
             REGISTRY,
             '        if int(cur.get("search_fail_ver") or 0) != LEARN_VER:\n'
             '            cur["search_fail"] = 0\n',
             "",
             REGISTRY_TEST),
    Mutation("learnver", "复核清单挑不出旧模板（学好了也清不掉库里那 9 个假的）",
             REGISTRY,
             '        if int(s.get("search_ver") or 0) >= LEARN_VER:\n            continue',
             "        if True:\n            continue",
             REGISTRY_TEST),
    Mutation("learnver", "撤假模板时用 pop（合并落盘时又复活，撤了等于没撤）",
             REGISTRY,
             '        cur["search_tpl"] = ""\n        cur["search_enc"] = ""',
             '        cur.pop("search_tpl", None)\n        cur["search_enc"] = ""',
             REGISTRY_TEST),
    Mutation("learnver", "学站清单不按书页证据排序（船艇站/百科站排到小说站前面）",
             REGISTRY,
             '        out.append((-has_book, -has_toc, -int(site.get("ok") or 0), host))',
             '        out.append((0, -has_toc, -int(site.get("ok") or 0), host))',
             REGISTRY_TEST),
    Mutation("learnver", "探测词不剥页面标题的尾巴（拿「…最新章节列表」去搜，一搜一个空）",
             REGISTRY,
             "            if t.endswith(junk) and len(t) > len(junk) + 1:",
             "            if False and t.endswith(junk) and len(t) > len(junk) + 1:",
             REGISTRY_TEST),
    # ---------------- 上线链条本身（tools/test_ship_chain.py）----------------
    # ⚠ 这一组破坏的是 `tools/ship.py` —— 破坏"上线动作"本身。
    #   失败方式统一是「所有测试都绿，但该做的事没做」，没有一条会报错：
    #   不推送（GitHub 落后）、谎报推送成功、清单文件名写错（那套静默没跑）、
    #   推送这一步的 print 只剩注释里那份（判据用全文匹配就恒真了）。
    Mutation("chain", "链条里不调 push_github（线上是新代码、GitHub 还是旧的）",
             SHIP_PY,
             "            if not push_github():",
             "            if False:",
             CHAIN_TEST),
    Mutation("chain", "找不到 git 也当成功（谎报推送完成，重建服务器时才知道）",
             SHIP_PY,
             '        print(f"  ✗ 找不到 git，没法推送：{e}")\n        return False',
             '        print(f"  ✗ 找不到 git，没法推送：{e}")\n        return True',
             CHAIN_TEST),
    Mutation("chain", "工作区有改动没提交也当成功（线上新、GitHub 空，链条却报全绿）",
             SHIP_PY,
             '                  "再 `git push` 补一次即可，**不用重跑 ship**。")\n'
             '            return 1',
             '                  "再 `git push` 补一次即可，**不用重跑 ship**。")\n'
             '            return 0',
             CHAIN_TEST),
    Mutation("chain", "清单里文件名写错（那套测试静默没跑，清单却照样显示全绿）",
             SHIP_PY,
             '    ("test_ship_chain.py", "上线链条完整"),',
             '    ("test_ship_chainX.py", "上线链条完整"),',
             CHAIN_TEST),
    Mutation("chain", "清单项不写说明（清单是给人看的，空说明等于没写）",
             SHIP_PY,
             '    ("test_motion.py", "动效层规矩"),',
             '    ("test_motion.py", "   "),',
             CHAIN_TEST),
    Mutation("chain", "推送步骤的 print 删掉（`[4/4]` 只剩注释里那份 → 全文匹配恒真）",
             SHIP_PY,
             '    print("\\n[4/4] 推送到 GitHub")',
             '    print("\\n推送到 GitHub")',
             CHAIN_TEST),
    # ---------------- 搜索模板必须真能带关键词（tools/test_registry.py）----------------
    # ⚠ 背景：线上 14 个「可搜源」里 6 个的模板是 `/search.html` 这种裸路径，
    #   关键词根本没发给站点，打开的是搜索页/首页（本来就有一堆书）——
    #   所以"链接数够多"判真、控制实验也判不了假，全静默。
    #   这一组破坏的就是那道防线：判据、写入口、自愈、扇出结构性矛盾。
    Mutation("kwless", "`tpl_carries_kw` 恒真（裸路径也算能搜 → 假站全放进来）",
             SITELEARN,
             '    if "{kw}" in (tpl or ""):\n        return True',
             "    if True:\n        return True",
             REGISTRY_TEST),
    Mutation("kwless", "`is_searchable` 不再校验模板能不能带关键词（库里假模板变回可搜）",
             REGISTRY,
             "    return (has_search_tpl(site) and _tpl_can_search(site)\n"
             "            and is_healthy(site))",
             "    return (has_search_tpl(site) and is_healthy(site))",
             REGISTRY_TEST),
    Mutation("kwless", "`note_search_tpl` 来者不拒（裸路径模板照样进库）",
             REGISTRY,
             '    if not tpl_carries_kw(tpl, method=method, body=body):\n'
             '        logger.info("拒收带不了关键词的搜索模板 %s：%s", host, tpl)\n'
             '        return False',
             "    if False:\n        return False",
             REGISTRY_TEST),
    Mutation("kwless", "自愈不清带不了关键词的模板（库里 6 个假站永远留着）",
             REGISTRY,
             '        if tpl_carries_kw(tpl, method=(site.get("search_method") or "get"),\n'
             '                          body=site.get("search_body")):\n'
             "            continue",
             "        if True:\n            continue",
             REGISTRY_TEST),
    # ⚠ 这里**故意没有**「清理不同步 updated」这条突变：
    #   实测它单独破坏不会红 —— `_read_disk()` 落盘前也会跑一遍自愈，
    #   盘上那份已经被清过了，于是 merge 两边一致。两处互为兜底，
    #   破坏任一处都不坏事，反证测不出来。硬塞一条只会变成"存活"的噪声。
    #   对应的行为判据在 tools/test_registry.py「清理结果真落了盘」。
    # ---------------- 自有来源扇出的结构性矛盾（tools/test_registry_source.py）----------------
    Mutation("kwless", "并发退回 6（14 个站要跑 3 轮，结构上必然超预算）",
             REGISTRY_SOURCE,
             "SEARCH_WORKERS = 24",
             "SEARCH_WORKERS = 6",
             REGSRC_TEST),
    Mutation("kwless", "单站超时退回 8s（比总预算 7s 还长 —— 一个慢站拖垮整批）",
             REGISTRY_SOURCE,
             "SEARCH_SITE_TIMEOUT = 3.5",
             "SEARCH_SITE_TIMEOUT = 8.0",
             REGSRC_TEST),
    Mutation("kwless", "超预算日志只说「先用已有结果」（看不出卡在几个站）",
             REGISTRY_SOURCE,
             '            logger.info("自有来源搜索超预算（%d/%d 个站已答完、%.1fs），先用已有结果 %d 条；"\n'
             '                        "没答完的是 %s",\n'
             "                        done, len(ordered), time.time() - t0, len(results),\n"
             '                        ", ".join(left_hosts) or "-")',
             '            logger.info("自有来源搜索超预算，先用已有结果")',
             REGSRC_TEST),
    # ---------------- 源吞异常也要熔断（tools/test_source_health.py）----------------
    # ⚠ 线上实测：熔断器一天**一次都没触发**，因为源自己 catch 掉异常后 return []，
    #   引擎当成"答话了、只是没这本书"→ note_ok 清零。
    #   结果 wikisource 110 次 SSL 超时 + xbqg5200 55 次 403，全部白等。
    Mutation("kwless", "引擎忽略源吞掉的异常（熔断器永远收不到失败）",
             ENGINE,
             "                if items or not err:",
             "                if True:",
             HEALTH_TEST),
    # ---------------- 控制实验三态：两轮定案（tools/test_search_trust.py）----------------
    # ⚠ 背景：单次采样判真假会翻着玩 —— `www.zxs8.net` 上一轮因为限流吐静态页、
    #   两次结果集不同 → 判"真"→ 盖了"已核实"章 → 再也不查；这一轮实测
    #   真书名 9 条 / 搜不到的书名 9 条、Jaccard 1.00（铁假）。
    #   现在：两轮都判假才撤、两轮都判真才盖章、有分歧=没结论（下次再查）。
    Mutation("verdict", "请求失败也算真站证据（打不开的站会被当成「已核实」盖章）",
             SITELEARN,
             "        if not ok:",
             "        if not ok:\n            diff_rounds += 1",
             TRUST_TEST),
    Mutation("verdict", "一轮判假就撤（单次采样翻转就误撤真站）",
             SITELEARN,
             "    if same_rounds >= need:",
             "    if same_rounds >= 1:",
             TRUST_TEST),
    Mutation("verdict", "「请求成功但 0 条」当成请求失败（真站全被判成没结论，每晚白查）",
             SITELEARN,
             "        return 0, set(), True\n    return len(toc), urls, True",
             "        return 0, set(), False\n    return len(toc), urls, True",
             TRUST_TEST),
    Mutation("verdict", "复核把「没结论」也盖章（假站从此免检 —— xxsy/zxs8 就是这么躲过去的）",
             DISCOVERY,
             "        if real:",
             "        if True:",
             TRUST_TEST),
    Mutation("verdict", "学到的模板直接盖「已核实」章（学过=核实过，单轮翻转的假站直接上岗）",
             REGISTRY,
             '        cur["search_ver"] = 0\n'
             '        cur["search_fail"] = 0          # 学会了，失败账清零',
             '        cur["search_ver"] = LEARN_VER\n'
             '        cur["search_fail"] = 0          # 学会了，失败账清零',
             REGISTRY_TEST),
    Mutation("verdict", "真实探测 0 条也去跑控制实验（「控制词也 0 条」被当成真站证据 → 盖章）",
             SITELEARN,
             "    if not hits or not urls:",
             "    if False:",
             TRUST_TEST),
    # ---------------- 搜不出东西的站不许算「可搜源」（tools/test_registry.py）----------------
    # ⚠ 背景：线上 15 个「可搜源」里 **7 个拿任何关键词都抽不出一条书链接**
    #   （POST 落回「搜索_首页」/ 前端渲染 SPA / 吞掉 `?s=` 回首页 / 403），
    #   而界面照报 15 个 —— 数字是虚的，每次搜索还白占一个并发名额。
    #   这一组破坏的就是「如实记账 → 连记到顶 → 作废模板重学」这条链。
    Mutation("srchdead", "把所有「抽不到链接」的页面都当空结果页（坏模板永远不作废、永不重学）",
             REGISTRY_SOURCE,
             "        empty_page = (not items) and _looks_like_empty_result(html, keyword)",
             "        empty_page = (not items)",
             REGSRC_TEST),
    Mutation("srchdead", "raw=0 也记成 miss（形态失败永远攒不满 → 不作废、永不重学）",
             REGISTRY,
             "        elif raw <= 0 and not empty_page:\n"
             "            cur[\"search_shape\"] = int(cur.get(\"search_shape\") or 0) + 1",
             "        elif raw <= 0 and not empty_page:\n"
             "            cur[\"search_miss\"] = int(cur.get(\"search_miss\") or 0) + 1",
             REGISTRY_TEST),
    Mutation("srchdead", "攒到顶也留着坏模板（只清 search_ver，每晚白查、永远不重学）",
             REGISTRY,
             '            cur["search_tpl"] = ""\n',
             "",
             REGISTRY_TEST),
    Mutation("srchdead", "「搜出过一次」不再清零形态失败账（好站被偶发拦截慢慢判死）",
             REGISTRY,
             '            cur["search_hit"] = int(cur.get("search_hit") or 0) + 1\n'
             '            cur["search_shape"] = 0',
             '            cur["search_hit"] = int(cur.get("search_hit") or 0) + 1',
             REGISTRY_TEST),
    Mutation("srchdead", "不优先取「标题含关键词」的候选（正主排第 7 位就被截掉）",
             REGISTRY_SOURCE,
             "            items = keyed + rest",
             "            items = rest + keyed",
             REGSRC_TEST),
    Mutation("srchdead", "「抓取就打不开」不记形态失败（403 站永久赖在可搜源里）",
             REGISTRY_SOURCE,
             "            if not slow:\n                registry.note_search_result(host, hits=0, raw=0)",
             "            if False:\n                registry.note_search_result(host, hits=0, raw=0)",
             REGSRC_TEST),
    Mutation("srchdead", "超时也记形态失败（我们自己等得不够，却把站作废了）",
             REGISTRY_SOURCE,
             "            if not slow:\n                registry.note_search_result(host, hits=0, raw=0)",
             "            if True:\n                registry.note_search_result(host, hits=0, raw=0)",
             REGSRC_TEST),
    # 换个新模板 = 换了一次假设，旧模板的账不能接着算（否则新模板一定被挡死/护死）
    Mutation("srchdead", "重学不清形态失败账（新模板一上来就被旧账挡死，永远没机会）",
             REGISTRY,
             '        cur["search_hit"] = 0\n        cur["search_shape"] = 0',
             '        cur["search_hit"] = 0',
             REGISTRY_TEST),
    Mutation("srchdead", "重学不清「搜出过」（旧模板的成绩护着新坏模板，永久留着白打）",
             REGISTRY,
             '        cur["search_hit"] = 0\n        cur["search_shape"] = 0',
             '        cur["search_shape"] = 0',
             REGISTRY_TEST),
    # ---------------- 卡死/超时也必须兜住（tools/test_source_budget.py、
    #                  tools/test_source_health.py 的「卡死不返回」组）----------------
    # ⚠ 线上实测（2026-10-21）：`wikisource.search()` 单次 **186.9 秒**才返回。
    #   引擎 20 秒就收手，那个线程还活 167 秒 —— 占着线程和连接池，
    #   同期别的搜索偶发 0 条（同一本书 6 分钟内一次 0 条、一次 1 条）。
    #   两个缺口：① 源自己没有时间上限；② 收手时把卡死的源一丢了之，
    #   连熔断器都不知道它挂过（熔断器只统计"跑完但抛异常"的源）。
    Mutation("hung", "源不看 deadline（到点了还照发下一次请求）",
             WIKI,
             "            if deadline is not None and time.time() >= deadline:",
             "            if False:",
             BUDGET_SRC_TEST),
    Mutation("hung", "搜索预算用光仍串第二次查询（186 秒就是它串出来的）",
             WIKI,
             "        if not hits and time.time() < deadline:",
             "        if not hits:",
             BUDGET_SRC_TEST),
    Mutation("hung", "引擎收手时不清算「卡住没答话」的源（熔断器永远学不到）",
             ENGINE,
             "            if hit_deadline and pending and not _stop():",
             "            if False:",
             HEALTH_TEST),
    # ---------------- 冷却退避 + 跨重启记忆（tools/test_source_health.py）----------
    # ⚠ 2026-10-22 线上实测：维基文库是境外站，云端 SSL 握手**必**超时。
    #   固定 15 分钟冷却 = 每小时被放进来试 4 次，每次都让一次真实搜索陪它等；
    #   `cache` 里没有任何地方记着"这个源打不通"，每次 sync/重启又从头试一遍。
    #   四条改动全都不报错，只表现为"搜索一直慢、答不完"。
    Mutation("backoff", "冷却不退避（死源永远按最短的 15 分钟一轮回来）",
             HEALTH_PY,
             '                dur = min(base * (BACKOFF ** (s["streak"] - 1)), MAX_COOLDOWN)',
             "                dur = min(base, MAX_COOLDOWN)",
             HEALTH_TEST),
    Mutation("backoff", "冷却不封顶（连挂十几次 = 冷却涨到几年，等于永久拉黑）",
             HEALTH_PY,
             '                dur = min(base * (BACKOFF ** (s["streak"] - 1)), MAX_COOLDOWN)',
             '                dur = base * (BACKOFF ** (s["streak"] - 1))',
             HEALTH_TEST),
    Mutation("backoff", "答话一次不清连续轮数（抖动型的源被一路按 8 小时冷却）",
             HEALTH_PY,
             "            had = self._st.pop(name, None) is not None",
             "            _s = self._st.get(name)\n"
             "            had = _s is not None\n"
             "            if _s:\n"
             "                _s[\"until\"] = 0\n"
             "                _s[\"fails\"] = 0",
             HEALTH_TEST),
    Mutation("backoff", "熔断状态不落盘（每次重启都忘光，重启后第一搜又陪坏源等满一轮）",
             HEALTH_PY,
             # ⚠ 锚点别挂在 docstring 上：2026-10-26 改了 `_save` 的说明文字，
             #   旧靶点（连 docstring 一起匹配）当场脱节 —— 而 ship 的静态自检
             #   会因此把「有 7 个突变脱节」报成基线红。靶点要挂在**会变的行为**
             #   上（这里：`_save` 的前两行守卫 + 紧接着的第一句实现）。
             "        if not self._path:\n"
             "            return\n"
             "        now = time.time()\n"
             "        with self._lock:\n"
             "            data: dict[str, Any] = {}",
             "        if True:\n"
             "            return\n"
             "        now = time.time()\n"
             "        with self._lock:\n"
             "            data: dict[str, Any] = {}",
             HEALTH_TEST),
    Mutation("backoff", "读回落盘时不校验到期（旧文件里的过期条目被塞进内存账本）",
             HEALTH_PY,
             # ⚠ 必须带上下一行的注释来定位：2026-10-26 起 `if until <= now:`
             #   在读回（`_ensure_loaded`）和落盘（`_save`）各有一处，
             #   只写那一行会**多处命中**，反证就会改错地方（test_ship_chain 会红）。
             "                if until <= now:\n"
             "                    # 「丢」不等于「忘」：",
             "                if until <= 0:\n"
             "                    # 「丢」不等于「忘」：",
             HEALTH_TEST),

    # ---------------- 超时 ≠ 站点挂了（tools/test_registry_source.py）----------------
    # ⚠ 单站只给 3.5 秒，慢站必然超时；超时若记成 fail_down，
    #   `is_healthy` 的 `down >= 3 and down > ok*2` 会把慢站往死里推 ——
    #   线上 350.ooo 当时 ok=35 / fail_down=70，再超时一次就从可搜源里消失。
    Mutation("slow", "分类器把超时也当成站点故障（慢站被慢慢判死）",
             UTILS,
             '    if isinstance(e, httpx.TimeoutException):\n        return "slow"',
             '    if isinstance(e, httpx.TimeoutException):\n        return "other"',
             REGSRC_TEST),
    Mutation("slow", "分类器把「连不上」也算成慢（死站永远清不掉）",
             UTILS,
             "    if isinstance(e, _CONNECT_DEAD):\n        return \"connect\"",
             "    if isinstance(e, _CONNECT_DEAD):\n        return \"slow\"",
             REGSRC_TEST),
    Mutation("slow", "分类器不沿 __cause__ 下钻（永远只看到 RuntimeError → 全归 other）",
             UTILS,
             "    if isinstance(e, RuntimeError) and cause is not None:\n        e = cause",
             "    if False:\n        e = cause",
             REGSRC_TEST),

    # ---------------- 判据会不会说真话（2026-10-22 复盘）----------------
    # ⚠ 这一组的失败方式不是"功能坏了"，而是**日志/库在撒谎** ——
    #   复盘每天要靠这两处判断"这本书为什么没搜到"，它们一撒谎，
    #   排查方向就是错的。2026-10-22 实测：库里有 8 个站同时是
    #   `searchable=True` 和 `why=复核：模板不认关键词（假搜索）`，
    #   照着这句话去查「假站为什么还在扇出」白花半小时，最后证明
    #   那 8 个站的模板都真的带 `{kw}`（5 个走 POST body）—— 库是好的。
    Mutation("verdict", "重学成功后不清旧模板的死因（库同时说「能搜」和「假搜索」）",
             REGISTRY,
             '        cur["search_fail_why"] = ""',
             '        cur["search_fail_why"] = cur.get("search_fail_why") or ""',
             REGISTRY_TEST),
    Mutation("verdict", "核实超预算时不报「还剩几个没核」（悄悄收手）",
             DISCOVERY,
             "        left = max(0, len(futs) - checked)",
             "        left = 0",
             DISCOVER_ASYNC_TEST),
    Mutation("verdict", "读库自愈不清陈旧死因（模板已换、旧结论还在撒谎）",
             REGISTRY,
             '        site["search_fail_why"] = ""',
             '        site["search_fail_why"] = site.get("search_fail_why") or ""',
             REGISTRY_TEST),
    Mutation("verdict", "自愈不看有没有模板就清死因（把有效结论一起抹掉）",
             REGISTRY,
             '        if not (site.get("search_tpl") or "").strip():\n            continue',
             '        if False:\n            continue',
             REGISTRY_TEST),

    # ---------------- 两字书名的确切命中不许放宽（2026-10-26 真机复盘）------
    # ⚠ 线上实测：搜《兄弟》，「嘿兄弟」「兄弟盟」都被判 tightness=1.0
    #   （容差写作 `max(1, len(kw)//3)`，两字书名也留了"多一个字"的余地）。
    #   两条都不是余华那本，却因为这判据成了"确切命中" → `rank()` 只留它们
    #   （其余候选全丢）、`engine` 的收手门也被喂饱 → 1.7s 收手，正主被弃，
    #   而 `search.done` 上写着 `确切=2` 看着像成功。不报错，只骗人。
    Mutation("tight", "两字书名的容差退回「至少 1 字」（嘿兄弟/兄弟盟冒充正主）",
             RELEVANCE,
             "    allow = 0 if len(kw) <= 2 else max(1, len(kw) // 3)",
             "    allow = max(1, len(kw) // 3)",
             REL_TEST),
    Mutation("tight", "两字书名也要吃「至少 1 字」的容差（同一个洞换个写法）",
             RELEVANCE,
             "    allow = 0 if len(kw) <= 2 else max(1, len(kw) // 3)",
             "    allow = max(0, len(kw) // 3) or 1",
             REL_TEST),
    Mutation("tight", "确切命中不看长度、只要包含就算（连《三体诗》都成《三体》）",
             RELEVANCE,
             "    if extra <= allow:\n        return 1.0",
             "    if True:\n        return 1.0",
             REL_TEST),

    # ---------------- 假搜源：轮换列表要能在**源头**被挡住（2026-10-28 复盘）------
    # ⚠ 线上实测：`www.31xss.com` / `www.dushu.co` / `www.kepub.net` /
    #   `www.taishuaile.com` / `www.taiminc.com` 五站（14 个可搜源里的 5 个）的
    #   "搜索页"每次吐一批**不同的**无关书（搜「三体」回《全能大佬是团宠》）。
    #   控制实验比的是"换个词结果集变不变"，轮换列表每轮都变 → **恒判真**
    #   → 判假撤不掉（试过补「标题相关性」判假，实测会误杀 biqusa 这种真站，
    #   已否决）。所以改在源头：`RegistrySource._search_one` 里，标题和作者
    #   连一个搜索词都没有的条目**不许当候选**。
    #   这组突变要证明的是：这条过滤**真的有牙**（关掉它假站就灌回来），
    #   而且三个反向陷阱都钉住了（整串比对 / 只看标题 / 单字不回落）。
    Mutation("假搜源", "源头过滤关掉（假站 6 条无关书重新变成候选）",
             REGSRC,
             "            if terms and not _mentions(terms, title, author):",
             "            if False:",
             REGSRC_TEST),
    Mutation("假搜源", "作者命中不算数（搜作者名时全站清零）",
             REGSRC,
             "    return bool(na) and any(t in na for t in terms)",
             "    return False",
             REGSRC_TEST),
    Mutation("假搜源", "按**整串**关键词比对（搜「余华 活着」全站清零）",
             REGSRC,
             "        terms = kw_terms(kw_key)",
             "        terms = [_norm(kw_key)]",
             REGSRC_TEST),
    Mutation("假搜源", "不把「含关键词的」排在前面（正主被 PER_SITE 截掉）",
             REGSRC,
             "                (keyed if any(t in nt for t in terms) else rest).append(x)",
             "                (keyed if False else rest).append(x)",
             REGSRC_TEST),
    Mutation("假搜源", "单字词不回落（搜单字书名时过滤把一切都清掉）",
             RELEVANCE,
             "    return long_terms or terms",
             "    return long_terms",
             REGSRC_TEST),

    # ---------------- 空结果页 ≠ 模板坏了（2026-10-29 复盘）------
    # 线上实测：夜间刚学到的 8 个源在一次复盘探针里**全部** shape=3、模板被清空
    # （可搜源 22 → 14）。它们唯一的"错"是被拿去搜了几本冷门书 ——
    # 站上没这本书时搜索页回的是「没有找到 xx」空结果页，里一条书链接都没有，
    # 于是 raw=0，于是被算成"打开的不是搜索页"，连记 3 次就作废模板。
    # 用户搜三本冷门书 = 源池少三分之一，而且全程不报错。
    # 这组要证明的是：① 空结果页不再被算形态失败；② 真的"不是搜索页"仍然会死；
    # ③ 两条证据（空态文案 / 关键词回显）各自都真的接上了。
    Mutation("空结果页", "空结果页照旧算「不是搜索页」（8 个源一天内被自己判死）",
             REGSRC,
             "        empty_page = (not items) and _looks_like_empty_result(html, keyword)",
             "        empty_page = False",
             REGSRC_TEST),
    Mutation("空结果页", "判出来了却不告诉记账（等于没判）",
             REGSRC,
             "        registry.note_search_result(host, hits=len(out), raw=len(items),\n"
             "                                    empty_page=empty_page)",
             "        registry.note_search_result(host, hits=len(out), raw=len(items))",
             REGSRC_TEST),
    Mutation("空结果页", "记账函数不认 empty_page（raw=0 一律记形态失败）",
             REGISTRY,
             "        elif raw <= 0 and not empty_page:",
             "        elif raw <= 0:",
             REGISTRY_TEST),
    Mutation("空结果页", "只认空态文案，不认关键词回显（POST 站的空结果页全判死）",
             REGSRC,
             "    return bool(kw) and kw in _norm(html[:20000])",
             "    return False",
             REGSRC_TEST),
    Mutation("空结果页", "只认关键词回显，不认空态文案",
             REGSRC,
             "    if any(m in low for m in _EMPTY_MARKERS):",
             "    if False:",
             REGSRC_TEST),

    # ---------------- 「源池=A→B」：这次搜索顺手废掉了几个源（2026-10-30）------
    # 线上实测（10-30 09:21）：连搜三本冷门书，8 个站的搜索模板当场作废、
    # 可搜源 22 → 15，而当天 `search.done` 里只有「候选=0」—— 源池缩水
    # 一个字都没写，靠事后 diff registry.json 才发现。
    # 这组钉的是「这个字段真的会说话」：三条突变分别打字段缺失、差值造假、
    # 以及"取不到就补 0"（`0→0` 会被读成源池空了，是另一种说谎）。
    Mutation("源池", "stats 里不写 pool_note（源池缩水再次看不见）",
             ENGINE,
             '                "pool_note": _pool_note(_pool0),',
             '                "pool_note": None,',
             RECALL_TEST),
    Mutation("源池", "开搜前那个数抄成 0（差值恒为非 0，看着像每次都废了站）",
             ENGINE,
             "            _pool0 = len(_reg.searchable_sites())",
             "            _pool0 = 0",
             RECALL_TEST),
    Mutation("源池", "取不到源池时补 0（0→0 会被读成源池空了）",
             ENGINE,
             "    if not isinstance(pool_before, int) or pool_before < 0:\n"
             '        return "?"',
             "    if not isinstance(pool_before, int) or pool_before < 0:\n"
             '        return "0→0"',
             RECALL_TEST),

    # ---------------- 限速页 ≠ 缺书 ≠ 模板坏了（2026-10-30 复盘）------
    # 线上实证：杰奇 CMS 对同一 IP 限速 30 秒，超了回一页「两次搜索的间隔时间
    # 不得少于 30 秒」。这页空得像"不是搜索页"，于是**连搜三本冷门书就把站判死**；
    # 10-30 09:55 `www.jcxs.cc` 重学回来又被判死第二次（源池 15→14）。
    # 三条突变分别打：判据没接上 / 词表只剩一半 / 记账没被跳过。
    Mutation("限速页", "限速页照旧算「不是搜索页」（连搜三本书就废掉一个站）",
             REGSRC,
             "        if (not items) and (not empty_page) and _looks_like_busy_page(html):",
             "        if False:",
             REGSRC_TEST),
    Mutation("限速页", "限速词表只剩一半（「间隔时间」这类不认）",
             REGSRC,
             '    "间隔时间", "两次搜索", "请稍后", "稍后再试", "秒后重试", "秒后再",',
             '    "请稍后", "稍后再试", "秒后重试", "秒后再",',
             REGSRC_TEST),
    Mutation("限速页", "判出限速却不收手（照旧往下记账，等于没判）",
             REGSRC,
             '            logger.debug("自有来源 %s 疑似限速页（关键词=%s），本次不记账",\n'
             "                         host, keyword)\n"
             "            return []",
             '            logger.debug("自有来源 %s 疑似限速页（关键词=%s），本次不记账",\n'
             "                         host, keyword)",
             REGSRC_TEST),

    # ---------------- 冷掉的账也要记得（2026-10-26 复盘）------
    # ⚠ 线上实测（三天，每次 ship 之后都倒退）：
    #     10-23 09:06 熔断 15 分钟 → 10:06 又 15 分钟
    #     10-24 09:04 熔断 30 分钟 → 09:51 退回 15 分钟
    #     10-25 09:07 熔断 30 分钟 → 09:50 退回 15 分钟（09:48:26 重启过）
    #   根因：落盘/读回都只认「仍在冷却中」的条目，冷却**到期那一刻**条目
    #   连 `streak` 一起消失 → 退避（15m→30m→60m…）永远涨不上去，
    #   死源每小时被放回名单试 4 次，每次都让一次真实搜索陪它等满 6 秒。
    #   两条突变分别打「写」和「读」两侧 —— 只修一侧 = 半修。
    Mutation("cold", "落盘只写仍在冷却的条目（到期即整条丢，streak 跟着没）",
             HEALTH_PY,
             "                    if int(v.get(\"streak\") or 0) <= 0:\n                        continue",
             "                    if True:\n                        continue",
             HEALTH_TEST),
    Mutation("cold", "读回时把到期的条目彻底忘掉（重启后从 15 分钟重新开始）",
             HEALTH_PY,
             "                    if streak > 0 and (now - at) <= FORGET_AFTER:",
             "                    if False:",
             HEALTH_TEST),
    Mutation("cold", "重挂时不接上一轮的 streak（半开试探也一并丢掉）",
             HEALTH_PY,
             "                     \"trial\": bool(mem), \"at\": 0.0,\n"
             "                     \"streak\": int((mem or {}).get(\"streak\") or 0),",
             "                     \"trial\": False, \"at\": 0.0,\n"
             "                     \"streak\": 0,",
             HEALTH_TEST),
    Mutation("cold", "答话只清账本、不清失败史（修好的站下次一挂就按封顶 8 小时）",
             HEALTH_PY,
             "            if self._memory.pop(name, None) is not None:\n                had = True",
             "            if False:\n                had = True",
             HEALTH_TEST),
    Mutation("cold", "失败史永不过期（一周前的死因决定今天的冷却）",
             HEALTH_PY,
             "                    if streak > 0 and (now - at) <= FORGET_AFTER:",
             "                    if streak > 0:",
             HEALTH_TEST),
]


# ---------------------------------------------------------------- 还原保险
_ORIGINALS: dict[Path, str] = {}

# 被**外部改动**过的文件：本次进程缓存的原文已经过期，绝不能再往上写
# （见 `check_one` 的 finally —— 反证工具把别人刚保存的代码覆盖掉，
#   比"没还原"严重得多）。收尾的 `restore_all()` 也要跳过它们。
_CLOBBERED: set[Path] = set()

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

# ------------------------------------------------------------------ 独占锁
# ⚠⚠ 为什么必须有它（2026-10-21 实测，代价是两个文件的源码被永久改坏）：
#   同一个仓库里**跑两个反证**（两个会话各跑一次 ship / 各自跑 mutate）时，
#   后启动那个进程的"基线"读到的是前一个**还没还原的突变版**，
#   于是它把"被改坏的源码"当成原文缓存下来；等它还原时，写回去的
#   就是这个坏版本 —— 突变变成了永久改动，还不报错。
#   当时的表现：`is_searchable()` 少了 `and is_healthy(site)`（坏站被算成
#   可搜资产）、`wikisource` 少了 deadline 判断，接着十几套测试"基线红"，
#   看上去像一堆测试同时烂了。
#   判据：**拿不到锁就不许改源码**。宁可让这次 ship 红，也不能把工作区改坏。
_LOCK = ROOT / "dist" / "tmp" / "mutate.lock"
_LOCK_FRESH = 20 * 60          # 秒。一轮全量反证约 5 分钟，20 分钟足够宽松


def _acquire_lock() -> bool:
    """拿到独占锁才能动源码。返回 False = 已经有一个反证在跑。"""
    try:
        if _LOCK.exists():
            age = time.time() - _LOCK.stat().st_mtime
            if age < _LOCK_FRESH:
                holder = ""
                try:
                    holder = _LOCK.read_text(encoding="utf-8").strip()
                except OSError:
                    pass
                print(f"✗ 已经有一个反证在跑（{holder or '?'}，"
                      f"{int(age)} 秒前留下的锁）—— 两个反证同时跑会把源码改坏。")
                print(f"  等它跑完再试；确认是残留的话删掉 {_LOCK.relative_to(ROOT)}")
                return False
            print(f"⚠ 捡到一个过期锁（{int(age / 60)} 分钟前），当残留处理")
        _LOCK.parent.mkdir(parents=True, exist_ok=True)
        _LOCK.write_text(f"pid={os.getpid()} at={time.strftime('%H:%M:%S')}",
                         encoding="utf-8")
        return True
    except OSError as e:
        # 写不了锁文件（只读目录之类）—— 不该因此把反证停掉，
        # 但要说出来：这种情况下"两个反证同时跑"的护栏就没有了。
        print(f"⚠ 拿不到锁文件（{e}）—— 这一轮没有并发保护")
        return True


def _release_lock() -> None:
    try:
        _LOCK.unlink(missing_ok=True)
    except OSError:
        pass


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
        if path in _CLOBBERED:
            # 这个文件在跑的过程中被别人改过 —— 我们手里的原文是旧的，
            # 写回去就是覆盖别人的改动。跳过并在下面如实说出来。
            continue
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
    """返回 (结果, 说明)。结果见下面四处 return。"""
    src = _load(m.path)                      # 原样（可能带 CRLF）
    flat = _to_lf(src)                       # 匹配与替换都在 LF 上做
    if m.old not in flat:
        return "detached", "要替换的片段在源码里找不到 —— 测试与代码已脱节"
    if m.old == m.new:
        return "detached", "突变前后一样，等于没改"
    patched = flat.replace(m.old, m.new, 1)
    if patched == flat:
        return "detached", "替换没有改动内容"
    after: str | None = None
    try:
        # ⚠⚠ 先把"原文"记进待还原清单，**再**动源码。
        #   反过来的顺序（先写、后记）有一个要命的时间窗：进程恰好在这两步
        #   之间被强杀 → 源码被改坏、清单里却没有它 → 下次启动也还原不了，
        #   于是**产品代码永久坏着**。2026-10-21 就这样把
        #   `save_adapted()` 的"同名覆盖"整行弄丢过（表现成 test_adapt_save
        #   红，看着像测试烂了，其实是产品真的会写重复条目）。
        #   记在前面不会造成"白还原一遍"：`_recover_pending()` 是**按内容比对**
        #   的，没真被改过的文件它跳过、不写。
        _save_pending()
        _write(m.path, _in_style(patched, src))
        if _to_lf(_read(m.path)) == flat:
            # 替换"没落盘"是最隐蔽的假反证：看起来跑过了，其实产品代码没变。
            return "detached", "替换没有真正落盘（源码没变）"
        ok, reds = run_test(m.test)
        # ⚠⚠ 跑完之后必须确认"突变还在盘上"。为什么：
        #   两个 mutate 进程同时跑（同一个仓库、两个会话 / 两次 ship），
        #   或者另一个会话正拿着自己的缓冲区保存这个文件时，**对方会把源码
        #   写回它缓存的那一份** —— 于是这一条测试其实跑在**没被破坏的代码**
        #   上，结果被报成「存活」，看上去像"断言没牙"，其实什么都没测到。
        #   这不是设想：2026-10-21 两个会话同时在这个仓库里跑反证，
        #   engine 那条连着两次报存活，单独跑又稳稳抓住。
        after = _to_lf(_read(m.path))
    finally:
        # ⚠⚠ 只在"我们的突变仍然在盘上"时才写回原文。
        #   无条件写回会把**别人刚保存的改动整份覆盖掉**（`src` 是本次进程
        #   第一次读到的内容，早就过期了）—— 反证工具把产品代码改坏一版，
        #   还理直气壮说"已逐字节还原"，这比不还原更糟。
        try:
            if _to_lf(_read(m.path)) == patched:
                _write(m.path, src)
            else:
                # 被别人改过了 —— 别碰它，也别在收尾时再"还原"一次。
                _CLOBBERED.add(m.path)
        except OSError:
            pass
        _clear_pending()
    if after is not None and after != patched:
        return "touched", ("测试期间源码被外部改动（另一个进程/会话在写同一个"
                           "文件），这一条不算数 —— 重跑一次")
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

    # ⚠⚠ 先抢锁，再碰源码。顺序不能反：`_recover_pending()` 会**写源码**，
    #   而另一个反证可能正跑到一半 —— 我去"还原"它正在改的文件，就是把它的
    #   突变成永久改动（这个事故真发生过，见 `_acquire_lock` 的注释）。
    if not _acquire_lock():
        return 4
    atexit.register(_release_lock)

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
        elif got == "touched":
            # ⚠ 和"存活"分开报：存活说的是"断言没牙"（产品问题），
            #   这个说的是"这一条根本没测到"（环境问题）。混在一起报，
            #   下次真出现没牙的断言时，人会以为是并发干扰而放过它。
            print(f"!  被外部改动  [{m.group}] {m.name}")
            print(f"      {why}")
            bad.append((m.group, m.name, why))
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
