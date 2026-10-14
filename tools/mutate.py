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

TOC_TEST = ROOT / "tools" / "test_toc_full.py"
SAVE_TEST = ROOT / "tools" / "test_adapt_save.py"
LAUNCH_TEST = ROOT / "tools" / "test_chrome_launcher.py"


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
             '               f"用你给的那一页（{len(d_html)} 字节 · {len(d_toc)} 章）"\n'
             '               + (f" —— {d_toc_note}" if d_toc_note else ""))',
             '               f"用你给的那一页（{len(d_html)} 字节 · {len(d_toc)} 章）")',
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
]


# ---------------------------------------------------------------- 还原保险
_ORIGINALS: dict[Path, str] = {}


def _load(path: Path) -> str:
    if path not in _ORIGINALS:
        _ORIGINALS[path] = path.read_text(encoding="utf-8")
    return _ORIGINALS[path]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def restore_all() -> list[str]:
    """把动过的文件按原内容写回；返回"没能还原"的文件名。"""
    bad: list[str] = []
    for path, text in _ORIGINALS.items():
        try:
            if path.read_text(encoding="utf-8") != text:
                path.write_text(text, encoding="utf-8")
            if path.read_text(encoding="utf-8") != text:
                bad.append(str(path))
        except OSError:
            bad.append(str(path))
    return bad


atexit.register(restore_all)


def run_test(test: Path) -> tuple[bool, list[str]]:
    p = subprocess.run([PY, str(test)], cwd=str(ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    reds = [ln.strip() for ln in p.stdout.splitlines() if ln.strip().startswith("✗")]
    return p.returncode == 0, reds


def check_one(m: Mutation) -> tuple[str, str]:
    """返回 (结果, 说明)。结果是 'caught' / 'survived' / 'detached'。"""
    src = _load(m.path)
    if m.old not in src:
        return "detached", "要替换的片段在源码里找不到 —— 测试与代码已脱节"
    if m.old == m.new:
        return "detached", "突变前后一样，等于没改"
    try:
        m.path.write_text(src.replace(m.old, m.new, 1), encoding="utf-8")
        wrote = m.path.read_text(encoding="utf-8")
        if wrote == src:
            # 替换"没落盘"是最隐蔽的假反证：看起来跑过了，其实产品代码没变。
            return "detached", "替换没有真正落盘（源码没变）"
        ok, reds = run_test(m.test)
    finally:
        m.path.write_text(src, encoding="utf-8")
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
    print("=" * 70)
    print(f"突变 {len(todo)} 条 · 问题 {len(bad)} 条")
    for g, n, w in bad:
        print(f"  ✗ [{g}] {n} —— {w}")
    if left:
        print("⚠ 以下文件没能还原，请手动检查：", left)
        return 3
    # 内容哈希复核：确认源码逐字节回到原样。
    drift = [str(p.relative_to(ROOT)) for p, t in _ORIGINALS.items()
             if _sha(p.read_text(encoding="utf-8")) != _sha(t)]
    if drift:
        print("⚠ 源码与进入前不一致：", drift)
        return 3
    print("源码已逐字节还原 ✓")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
