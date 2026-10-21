# -*- coding: utf-8 -*-
"""判据：**上线链条本身**是完整的 —— 清单没漏项、反证没脱节、推送没丢掉。

为什么需要这一套
----------------
`tools/ship.py` 是项目唯一的"上线动作"。它自己的清单出问题时，症状是
**所有测试都绿，但该做的事没做**：

  · `STATIC_SUITES` 里文件名写错 → 那一套测试根本没跑，却显示"全绿"
  · `tools/mutate.py` 里某条突变的 `old` 片段与源码脱节 → 要等反证
    跑到第 100 多条才发现（一次 ship 十七分钟，2026-10-21 连踩两次：
    改 `_LEARN_BUDGET_PER_SITE=12→16`、改 `should_stop=_stop)` 收尾括号）
  · 链条里**没有推送这一步** → 线上是新代码、GitHub 还是旧的，
    哪天要重建服务器，拉下来是半年前的代码（2026-10-21 实测：本地攒了 4 个提交）

前两条是"静态就能查"的：文件名是否存在、片段是否唯一匹配。
它们本该在 1 秒内报红，而不是让人等 17 分钟。
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

OK = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {extra}")


def load(name: str):
    """把 tools/ 下的脚本当模块载入（它们不是包）。

    ⚠ 必须先注册进 `sys.modules` 再 `exec_module`：`@dataclass` 装饰器内部
    会回查 `sys.modules[cls.__module__].__dict__`，没注册就拿到 None →
    `AttributeError: 'NoneType' object has no attribute '__dict__'`。
    这是"只在这一套测试里崩、单独跑 mutate.py 却没事"的原因。
    """
    spec = importlib.util.spec_from_file_location(f"_t_{name}",
                                                  ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod.__name__] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(mod.__name__, None)
    return mod


def scan(muts, to_lf) -> tuple[list[str], list[str], list[str], list[str]]:
    """扫一遍突变清单，返回 (脱节, 多处命中, 前后一样, 正在被反证)。

    ⚠⚠ 匹配口径必须和 `mutate.check_one()` **完全一致**：它先把 CRLF 归一成
    LF 再 `in`，因为突变片段是照 `\\n` 写的、而工作区的 `.py` 是 CRLF。
    第一版直接拿 `newline=""` 的原文去数，5 条"脱节"全是**判据自己的错**
    —— 判据的基准必须与被判者的口径一致，否则红的是判据不是产品。
    """
    drift: list[str] = []
    ambiguous: list[str] = []
    same: list[str] = []
    inflight: list[str] = []
    for m in muts:
        if not m.path.is_file():
            continue
        if m.old == m.new:
            same.append(m.name)
            continue
        text = to_lf(m.path.read_text(encoding="utf-8", newline=""))
        cnt = text.count(m.old)
        if cnt == 0:
            # ⚠ 得分清"真脱节"和"正在被反证"：
            #   `mutate.py` 会把源码临时改成 `new` 再跑本套测试，此刻
            #   `old` 当然找不到 —— 那是 in-flight，不是清单坏了。
            #   判据：`new` 在源码里出现 = 现在我们正看着被改坏的那一版。
            #   不分的话，反证输出里每条红都多挂一句"脱节"，把真信号挤掉
            #   （`check_one` 只显示前两条红行）。
            if m.new and m.new in text:
                inflight.append(f"{m.path.name}: {m.name}")
            else:
                drift.append(f"{m.path.name}: {m.name}")
        elif cnt > 1:
            ambiguous.append(f"{m.path.name}: {m.name}（{cnt} 处）")
    return drift, ambiguous, same, inflight


def main() -> int:
    import ship

    print("\n—— 上线清单：写进去的每一套都必须真的存在 ——")
    missing = [n for n, _ in ship.STATIC_SUITES
               if not (ROOT / "tools" / n).is_file()]
    check("★ STATIC_SUITES 里每个文件都存在（写错名字 = 那套测试静默没跑）",
          not missing, str(missing))
    missing_live = [n for n, _ in ship.LIVE_SUITES
                    if not (ROOT / "tools" / n).is_file()]
    check("★ LIVE_SUITES 里每个文件都存在", not missing_live, str(missing_live))
    dup = [n for n, _ in ship.STATIC_SUITES + ship.LIVE_SUITES
           if sum(1 for m, _ in ship.STATIC_SUITES + ship.LIVE_SUITES if m == n) > 1]
    check("清单里没有重复项（重复会让人以为跑了两遍）", not dup, str(sorted(set(dup))))
    desc_empty = [n for n, d in ship.STATIC_SUITES if not d.strip()]
    check("每项都有中文说明（清单是给人看的）", not desc_empty, str(desc_empty))

    print("\n—— 上线链条：[4/4] 推送 GitHub 不许丢 ——")
    # 这一条钉的是"链条完整性"，不是"这次推没推"。
    src = (ROOT / "tools" / "ship.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    called: set[str] = set()
    lits: set[str] = set()          # 代码里真正出现的**字符串字面量**
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            lits.add(node.value)
    check("★ ship 真的会调 push_github（否则线上新、GitHub 旧）",
          "push_github" in called, str(sorted(called)))
    # ⚠⚠ 这两条原先写的是 `"[4/4]" in src` —— **注释也算**，等于恒真：
    #   `[4/4] 推送到 GitHub` 这几个字在注释里躺了好几十行，
    #   把 print 删掉它照样绿。判据只认 ast 里的字符串字面量。
    check("ship 里有 [4/4] 推送这一步的输出（人能看见它在做）",
          any("[4/4]" in s for s in lits), str([s for s in lits if "4]" in s][:3]))
    check("★ push 失败要红（不是警告了事）",
          any("推送失败" in s for s in lits)
          and any(isinstance(n, ast.Return)
                  and isinstance(n.value, ast.Constant) and n.value.value == 1
                  for n in ast.walk(tree)))
    # ⚠⚠ 「工作区是脏的」也必须红，不能只打印一句警告。
    #   真事（2026-10-21）：ship 打印「✓ 上线完成」、线上确实换了新代码，
    #   而 **GitHub 上什么都没有** —— 14 个改动没提交，`git push` 看到
    #   "没有待推送的提交"就返回成功。真正该做的事（提交）谁也没做，
    #   而链条报的是全绿。判据要求：`if dirty:` 这个分支里必须有 `return 1`。
    dirty_gate = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if "dirty" not in ast.dump(node.test):
            continue
        if any(isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)
               and n.value.value == 1 for n in ast.walk(node)):
            dirty_gate = True
    check("★ 工作区有未提交改动 → ship 必须红（否则线上新、GitHub 空，却报成功）",
          dirty_gate)

    # git 不可用时必须返回 False —— "没推成功"和"没 git"不能都算成功
    saved = ship.subprocess.run

    def _no_git(*a, **k):
        raise OSError("git not found")

    buf = io.StringIO()
    try:
        ship.subprocess.run = _no_git
        with contextlib.redirect_stdout(buf):
            got = ship.push_github()
    finally:
        ship.subprocess.run = saved
    check("★ 找不到 git 时 push_github 返回 False（不许谎报成功）", got is False)
    # ⚠ 这条不是"顺手多问一句"：`return False` 但一声不吭，人看到的只有
    #   一个红步骤、没有原因，就会怀疑测试烂了。必须**说出来**。
    check("push 失败时把原因打出来了（不然红得莫名其妙）",
          "git not found" in buf.getvalue(), buf.getvalue()[:80])

    print("\n—— 反证清单：每条突变必须能在源码里唯一命中 ——")
    # 这是今天最贵的一条教训：改了一个常量，反证跑 17 分钟才报"源码脱节"。
    mut = load("mutate")
    check("突变清单读得到", len(mut.MUTATIONS) >= 100, str(len(mut.MUTATIONS)))
    bad_path = [m.name for m in mut.MUTATIONS if not m.path.is_file()]
    check("每条突变的目标文件都存在", not bad_path, str(bad_path[:5]))

    drift, ambiguous, same, inflight = scan(mut.MUTATIONS, mut._to_lf)
    # ⚠ 「源码现在处于 new 状态」这条只能**当线索**，不能当判据。
    #   会误报的原因很实在：突变片段写短了（比如 `例子=[])`），
    #   别人重构之后这段字面量恰好在别处存在、而原来的 `old` 不在了 ——
    #   于是"看起来像残留"，其实只是那条突变脱节了（下面 `drift` 会红）。
    #   真正靠得住的判据是**状态文件**：`dist/tmp/mutate_pending.json` 非空
    #   = 此刻正有一次反证在改源码（见 mutate._save_pending）。
    #   而"被强杀留下残留"这个洞已经用**先记后改**堵死了（见下面那条断言）。
    _pend = ROOT / "dist" / "tmp" / "mutate_pending.json"
    try:
        _running = bool(json.loads(_pend.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        _running = False
    if inflight:
        print(f"  · 有 {len(inflight)} 条源码正处于 new 形态"
              f"（{'反证在跑' if _running else '**没有反证在跑，值得看一眼**'}）："
              f"{[i.split(':')[0] for i in inflight][:4]}")
    check("★ 没有脱节的突变（片段在源码里找得到）—— 之前要等 17 分钟才发现",
          not drift, str(drift[:5]))
    check("★ 每条突变都唯一命中（多处命中会改错地方，反证失去意义）",
          not ambiguous, str(ambiguous[:5]))
    check("每条突变的 old/new 不一样（否则它什么都没破坏）", not same, str(same[:5]))

    # ⚠ 上面三条本身也可能恒真（比如 scan 的循环条件写错、一条都没扫）。
    #   拿两条**必定出问题**的假突变喂进去，扫不出来就说明这三条没牙。
    fake = [
        mut.Mutation("x", "假·片段不存在", mut.REGISTRY,
                     "ZZZ_这段源码里一定没有_ZZZ", "yyy", mut.REGISTRY),
        mut.Mutation("x", "假·片段出现多次", mut.REGISTRY,
                     "import ", "import  ", mut.REGISTRY),
    ]
    d2, a2, _, _ = scan(fake, mut._to_lf)
    check("★ 判据自己有牙：编一条脱节突变必须被扫出来", len(d2) == 1, str(d2))
    check("★ 判据自己有牙：编一条多处命中的突变也必须被扫出来", len(a2) == 1, str(a2))

    print("\n—— 反证工具自身：并发/外部改动必须能被认出来 ——")
    # ⚠ 真事（2026-10-21）：两个会话在同一个仓库里各跑一次反证，
    #   对方的"还原"会把我这边的突变写回去 —— 于是那条测试其实跑在
    #   **没被破坏的代码**上，却被报成「存活（断言没牙）」。
    #   更糟的方向是：收尾时把别人刚保存的改动**整份覆盖**掉。
    #   这两条都靠工具自己的判据守住，不是靠人记得别同时跑。
    msrc = (ROOT / "tools" / "mutate.py").read_text(encoding="utf-8")
    check("★ 跑完测试后复核「突变还在盘上」（否则并发干扰会被误报成断言没牙）",
          "after = _to_lf(_read(m.path))" in msrc)
    check("★ 只在自己的突变还在盘上时才写回原文（否则覆盖别人的改动）",
          "if _to_lf(_read(m.path)) == patched:" in msrc)
    check("被外部改动过的文件收尾时也不再还原（原文已经过期）",
          "_CLOBBERED.add(m.path)" in msrc and "if path in _CLOBBERED:" in msrc)
    check("「被外部改动」与「存活」分开报（环境问题别伪装成产品问题）",
          '"touched"' in msrc and "被外部改动  [" in msrc)
    # ⚠ 独占锁：两个反证同时跑会把源码**永久改坏**（对方的"原文"其实是
    #   我改坏的版本，它还原时写回来的就是坏代码）。当时的表现是
    #   `is_searchable()` 少了健康度判断 → 十几套测试"基线红"。
    check("★ 反证有独占锁（两个同时跑会把源码永久改坏）",
          "_acquire_lock()" in msrc and "_LOCK_FRESH" in msrc)
    check("抢锁在「还原残留」之前（否则会去改别人正在改的文件）",
          msrc.index("_acquire_lock()") < msrc.index("_recover_pending()"))
    # ⚠⚠ 这条钉的是**被强杀也不会留残留**：原来的顺序是"先改源码、再记清单"，
    #   恰好在这两步之间被杀 → 源码改坏了、清单里却没有它 → 下次启动也救不回来。
    #   2026-10-21 就这样把 `save_adapted()` 的"同名覆盖"整行弄丢过
    #   （产品会写出重复站点，而表现只是 test_adapt_save 红）。
    check("★ 先把原文记进清单、再动源码（被强杀也不留残留）",
          msrc.index("_save_pending()\n        _write(m.path")
          < msrc.index("_write(m.path, _in_style(patched, src))"))

    print("\n" + "=" * 60)
    print(f"通过 {OK} · 失败 {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
