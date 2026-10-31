"""章节地址是「数字+字母」编码的站，目录曾被我们自己拆碎（2026-10-31 复盘）。

现场
----
线上《我的阿勒泰》连续两天 `候选=1 确切=1 可读=0`，联网也说「搜到的站点
都打不开或没有目录」。真抓下来看：`cn.shubaoc.com/novel/bpo/` 是**真的书页**，
页面里有 40 条章节链接，标题「我的阿勒泰(李娟)」。

三个独立的坑，每个都不报错：

  A. **章节 id 是 base32**（`1u0ri`、`1u11f`、`1u0tl`）。`_template()` 只把
     `\\d+` 换成 `#`，于是 42 条章节链接分成 42 个「模板」，每组 1~3 条，
     全都够不到 `min_items=8` —— 整本书 0 章。这是**把目录拆碎**。
  B. **slug 里的数字被当成章节号**。`1u11f` 会抽出 `1`、`11` 两列数字，
     `_chapter_keys()` 挑「变化最多的那列」当章号再据此重排 —— 一本顺序
     正确的书会被排成乱序。
  C. **散文集的目录不叫「第N章」**。`toc_quality()` 只看「URL 单调」+「标题
     带第N章」，而《我的阿勒泰》的目录是「自序 / 第一辑 阿勒泰文字（2007-2009）
     我所能带给你们的事物」，ratio=0 → 一份 40 条的真目录被判 0.35 分、
     整本书判 unknown。**这三天的三本书（乡土中国 / 素食者 / 我的阿勒泰）
     恰好全是这一类**，这就是"冷门书搜不到"背后的系统性原因。

修法
----
  A. `_template()` 认「数字开头、混着字母」的 slug 段（`_is_slug_seg`）。
  B. `_num_columns()` 跳过 slug 段。
  C. 加第三条证据 `_looks_like_toc_block()`：页面自己写着「章节列表」、
     链接都挂在本页这本书下、且是页面上的主要链接群 —— 三条同时成立才认。
     任一条不成立就退回旧判据（宁可漏判，不可乱报）。

  D. 顺手修埋点：`_verify()` 的「页打开了、但不是目录」原来**静默 return**，
     线上「核实 5 个候选、0 命中」只留下 2 条 403 日志，另外 3 个凭空消失。
     现在逐条点名 + `web_ledger()` 把它摊进 search.done 的 `联网核=`。

判据全部打在 `tools/fixtures/shubaoc_toc.html`（结构照抄实测页面，
章节名照抄，正文简介自写），并且每条都配反证 —— 把产品代码的那个机制
人为破掉，看断言会不会真红。本项目已经抓到过 6 次"恒真的假测试"。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import discovery as D                              # noqa: E402
from app import webfetch as W                               # noqa: E402
from app.engine import web_ledger                           # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
HTML = (FIX / "shubaoc_toc.html").read_text(encoding="utf-8")
PAGE_URL = "https://cn.shubaoc.com/novel/bpo/"

ok_n = 0
bad_n = 0
fails: list[str] = []


def ok(name: str, cond: bool, detail="") -> None:
    global ok_n, bad_n
    if cond:
        ok_n += 1
        print(f"  ✓ {name}" + (f"  {detail}" if detail != "" else ""))
    else:
        bad_n += 1
        fails.append(name)
        print(f"  ✗ {name}  {detail}")


def breaks(name: str, cond: bool, detail="") -> None:
    """反证：条件被破坏时断言必须**不成立**。"""
    global ok_n, bad_n
    if not cond:
        ok_n += 1
        print(f"  ✓ 反证 ok：{name}")
    else:
        bad_n += 1
        fails.append(f"反证：{name}")
        print(f"  ✗ 反证失败（说明判据没牙）：{name}")


print("=" * 62)
print("A. 章节 id 是 base32 时，模板必须归一成同一个")
print("=" * 62)
t1 = W._template("https://cn.shubaoc.com/novel/bpo/1u0ri.html")
t2 = W._template("https://cn.shubaoc.com/novel/bpo/1u11f.html")
t3 = W._template("https://cn.shubaoc.com/novel/bpo/1u0tl.html")
ok("三条 slug 地址同模板", t1 == t2 == t3, t1)
breaks("把 _template 退回只认 \\d+ 时，这条必须不成立",
       W.re.sub(r"\d+", "#", "/novel/bpo/1u0ri.html")
       == W.re.sub(r"\d+", "#", "/novel/bpo/1u11f.html"))

print("=" * 62)
print("B. slug 里的数字不是章节号，不许拿它重排")
print("=" * 62)
cols = W._num_columns(["https://cn.shubaoc.com/novel/bpo/1u0ri.html",
                       "https://cn.shubaoc.com/novel/bpo/1u11f.html"])
ok("slug 段不贡献数字列", all(c == [] for c in cols), str(cols))
ok("认不出章号 → 不排序", W._chapter_keys(
    ["https://cn.shubaoc.com/novel/bpo/1u0ri.html",
     "https://cn.shubaoc.com/novel/bpo/1u11f.html"]) is None)
# 反证：老站那种 /3_3316/mulu/2.html 必须仍然认得出章号
keys = W._chapter_keys(["https://a.com/3_3316/mulu/1.html",
                        "https://a.com/3_3316/mulu/2.html",
                        "https://a.com/3_3316/mulu/3.html"])
ok("回归：纯数字目录仍能认出章号", keys == [1, 2, 3], str(keys))

print("=" * 62)
print("C. 散文集目录（不含第N章）必须靠页面目录区认出来")
print("=" * 62)
toc = W.extract_toc(HTML, PAGE_URL)
ok("抽出 12 条（旧代码只能抽到 0 条）", len(toc) == 12, f"n={len(toc)}")
q, why = W.toc_quality(toc)
ok("质量 ≥0.55（旧代码 0.35 → 判 unknown）", q >= 0.55, f"q={q} why={why}")
ok("说明里点明证据来源", "章节列表" in why, why)
ok("顺序：第一条是「自序」，顶部的「最新章节」被挪到末尾",
   bool(toc) and toc[0]["title"] == "自序", toc[0]["title"] if toc else "")
breaks("页面不写「章节列表」时，不许给这条证据",
       W._looks_like_toc_block(HTML.replace("章节列表", "作品信息"), PAGE_URL,
                               toc) is False)

print("=" * 62)
print("D. 「猜你喜欢」不能被当成目录（误判的代价是下到别人的书）")
print("=" * 62)
toc2 = W.extract_toc(HTML, PAGE_URL)
titles2 = [c["title"] for c in toc2]
ok("正常页面：抽到的不是「猜你喜欢」那 8 条",
   "素食者" not in titles2 and "活着" not in titles2, str(titles2[:3]))

# 最险的一种页面：**完全认不出目录区**（锚点文字和 class 都不是目录的），
# slug 目录 0.0 分，而「猜你喜欢」是单调递增的 /book/2345/…/book/2352/（0.35 分）。
# 只按质量分排，噪声就赢了 —— 用户点开一本书，目录是别人的书。
NOANCHOR = (HTML.replace("章节列表", "作品信息")
                .replace("chapter-list", "info-list"))
toc3 = W.extract_toc(NOANCHOR, PAGE_URL)
titles3 = [c["title"] for c in toc3]
ok("认不出目录区时，也不许把「猜你喜欢」当目录",
   "素食者" not in titles3 and "活着" not in titles3, str(titles3[:3]))
_orig_prefix = W._book_prefix
try:
    # 把「这本书的路径前缀」拆成 "/"（等于这条判据失效）
    W._book_prefix = lambda p: "/"
    toc4 = W.extract_toc(NOANCHOR, PAGE_URL)
    titles4 = [c["title"] for c in toc4]
finally:
    W._book_prefix = _orig_prefix
breaks("把「挂在这本书下」拆掉后，噪声真的会顶上来（证明这条判据有牙）",
       "素食者" not in titles4)

ok("「猜你喜欢」的 URL 前缀对不上本书 → 不给目录证据",
   W._looks_like_toc_block(HTML, PAGE_URL,
                           [{"url": "https://cn.shubaoc.com/book/%d/" % (2345 + i),
                             "title": "素食者"} for i in range(8)]) is False)

print("=" * 62)
print("E. 核实账本：『不是目录』必须点名，不能沉默消失")
print("=" * 62)
ok("没跑联网 → 打 `-`，不补 0", web_ledger(None) == {"联网核": "-"},
   str(web_ledger(None)))
led = web_ledger({"cands": 5, "hit": [], "fetch_fail": ["www.99csw.com"],
                  "not_toc": ["leshu8.com", "tv.cctv.com"], "unchecked": 0})
s = led["联网核"]
ok("账本带候选数→命中数", s.startswith("5→0"), s)
ok("失败带名字", "失败=1(www.99csw.com)" in s, s)
ok("不是目录带名字", "非目录=2(leshu8.com,tv.cctv.com)" in s, s)

# _verify 的「不是目录」分支：日志 + 账本，两样都要
_orig_page = D.page_of
_orig_note = D.registry.note_site
_orig_known = D.registry.known_site
_orig_healthy = D.registry.is_healthy
try:
    D.page_of = lambda url: {"kind": "chapter", "title": "我的阿勒泰(李娟)",
                             "note": ""}
    D.registry.note_site = lambda *a, **k: None
    D.registry.known_site = lambda host: None
    D.registry.is_healthy = lambda site: True

    class _Cap(logging.Handler):
        def __init__(self):
            super().__init__()
            self.lines: list[str] = []

        def emit(self, rec):
            self.lines.append(rec.getMessage())

    cap = _Cap()
    D.logger.addHandler(cap)
    D.logger.setLevel(logging.INFO)
    tally: dict = {}
    r = D._verify({"url": PAGE_URL, "host": "cn.shubaoc.com"}, "我的阿勒泰", tally)
    D.logger.removeHandler(cap)

    ok("不是目录 → 返回 None", r is None)
    ok("不是目录 → 点名进账本", tally.get("not_toc") == ["cn.shubaoc.com"],
       str(tally.get("not_toc")))
    ok("不是目录 → 日志里有一行（旧代码这里是静默 return）",
       any("候选不是目录" in ln and "cn.shubaoc.com" in ln for ln in cap.lines),
       " | ".join(cap.lines[-2:]))
finally:
    D.page_of = _orig_page
    D.registry.note_site = _orig_note
    D.registry.known_site = _orig_known
    D.registry.is_healthy = _orig_healthy

print("=" * 62)
print(f"{'全部通过' if not fails else '有失败'}（{ok_n} 通过 / {bad_n} 失败）")
if fails:
    for f in fails:
        print("  ✗", f)
print("=" * 62)
sys.exit(1 if fails else 0)
