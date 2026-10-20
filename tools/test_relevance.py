"""相关性判定的回归测试 —— 零依赖，直接跑：

    .venv/Scripts/python.exe tools/test_relevance.py

这些都是**真实踩过的坑**，每条都对应一次线上搜错的截图：

  搜《微微一笑很倾城》 → 返回「北京互联网法院…民事判决书」
  搜《活着》           → 返回「原神：活着」「我怎么还活着」（余华那本反而没有）
  搜《三体》           → 返回「三體唐詩（四庫全書本）」
  搜《斗破苍穹》        → 返回「安士全書/文昌帝君陰騭文廣義節錄」
  搜《活着》           → 鲲弩的 WordPress 搜索按章检索，返回一堆「第N章 活着」

改打分逻辑前先跑这个，别把已经修好的又弄回去。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import BookResult  # noqa: E402
from app.relevance import rank, score, tightness  # noqa: E402

FAILS: list[str] = []


def check(name: str, got, want, label: str = "") -> None:
    if got != want:
        FAILS.append(f"{name}: {label} 期望 {want!r}，实际 {got!r}")
        print(f"  ✗ {name}  {label}  期望 {want!r} 实际 {got!r}")
    else:
        print(f"  ✓ {name}  {label}  {got!r}")


def R(title: str, source: str = "s", url: str = "u", author: str = "", intro: str = "") -> BookResult:
    return BookResult(title=title, author=author, source=source, url=url, intro=intro, available=True)


# ---------------------------------------------------------------------------
print("\n[1] tightness —— 「这到底是不是同一本书」")
# ---------------------------------------------------------------------------
TIGHT = [
    ("活着", "活着"),
    ("三体", "三体"),
    ("三体", "三体（全集）"),
    ("三体", "三体 (全集)"),
    ("盗墓笔记", "盗墓笔记（全集）"),
    ("微微一笑很倾城", "微微一笑很倾城（顾漫 著）"),
    ("微微一笑很倾城", "微微一笑很倾城（顾漫著）"),
    ("斗破苍穹", "斗破苍穹"),
    # 站点把分类拼进书名 —— 剥掉前缀后必须仍然算「确切命中」。
    # 线上实测：新笔趣阁返回的全部是「[玄幻]斗破苍穹」这种，不剥的话
    # tightness 掉到 0.67/0.00，真正那本被判定成"不是这本书"，
    # 一堆《斗破苍穹之XXX》同人反而排到前面。
    ("斗破苍穹", "[玄幻]斗破苍穹"),
    ("斗破苍穹", "[网游]斗破苍穹"),
    ("活着", "【6】活着"),
    ("活着", "[1]活着"),
]
for kw, t in TIGHT:
    check("tightness", tightness(t, kw) >= 0.99, True, f"《{kw}》 vs {t} 应算确切命中")

LOOSE = [
    # 搜《活着》：都是真书、都含关键词，但都不是余华那本
    ("活着", "原神：活着"),
    ("活着", "我怎么还活着"),
    ("活着", "生活不止是活着"),
    ("活着", "黑山启示录：活着"),
    ("活着", "活着：我成了地主家儿子徐福贵"),
    # 搜《三体》：维基文库把「三體唐詩」当成命中
    ("三体", "三體唐詩（四庫全書本）"),
    ("三体", "三体唐诗"),
    # 二手资料不是书本身
    ("红楼梦", "红楼梦考证"),
    # 标题里手工带上作者名（不是括号形式）—— 保守判为沾边
    ("三体", "三体 刘慈欣"),
]
for kw, t in LOOSE:
    check("tightness", tightness(t, kw) < 0.99, True, f"《{kw}》 vs {t} 只算沾边")

check("tightness", tightness("无关的书", "活着"), 0.0, "关键词不在标题里 → 0")


# ---------------------------------------------------------------------------
print("\n[2] score —— 噪音必须被压下去")
# ---------------------------------------------------------------------------
print("  —— 判决书（当年搜《微微一笑很倾城》返回的那种）——")
judge = "北京互联网法院（2021）京0491民初9699号民事判决书"
check("score", score(R(judge), "微微一笑很倾城") < 30, True, f"{judge[:16]}… 应被重罚")

print("  —— 章节名被当成书名（鲲弩按章检索）——")
for t in ("第两百一十六章 活着", "第1章 贺谛", "149.我爱你"):
    check("score", score(R(t), "活着") < 30, True, f"{t} 应被重罚")

print("  —— 维基类子页面 ——")
check("score", score(R("三體唐詩 (四庫全書本)/卷2"), "三体") < 60, True, "带 / 的子页面应扣分")

print("  —— 兜底书单型噪音 ——")
for t in ("安士全書", "文昌帝君陰騭文廣義節錄", "全覽"):
    check("score", score(R(t), "斗破苍穹") < 28, True, f"{t} 应低于门槛")


# ---------------------------------------------------------------------------
print("\n[3] rank —— 有确切命中时，不端沾边的上来")
# ---------------------------------------------------------------------------
res = [
    R("原神：活着", source="xbqg5200"),
    R("我怎么还活着", source="xbqg5200"),
    R("活着", source="kunnu8", author="余华"),
]
kept = rank(res, "活着")
check("rank", [r.title for r in kept], ["活着"], "只保留确切命中")

res2 = [
    R("原神：活着", source="xbqg5200"),
    R("我怎么还活着", source="xbqg5200"),
]
kept2 = rank(res2, "活着")
check("rank", len(kept2) > 0, True, "没有确切命中时仍然返回沾边结果（前端加横幅说明）")
check("rank", all(not r.tight for r in kept2), True, "这些结果 tightness 都应 < 1")

res3 = [
    R("三體唐詩（四庫全書本）", source="wikisource"),
    R("三体", source="wyshu"),
    R("三体", source="kunnu8"),
    R("三体（全集）", source="xbqg5200"),
]
kept3 = rank(res3, "三体")
titles = sorted(r.title for r in kept3)
check("rank", "三體唐詩（四庫全書本）" in titles, False, "唐诗集必须被滤掉")
check("rank", len(kept3), 3, "三条《三体》都留下")

print("  —— 同一来源里同名书去重 ——")
dup = [R("红楼梦", source="a", url="u1"), R("紅樓夢", source="a", url="u2")]
check("rank", len(rank(dup, "红楼梦")), 1, "同源同名（繁简差异）只留一条")


# ---------------------------------------------------------------------------
print("\n[4] 自适应门槛 —— 真的不相关时老实说没找到")
# ---------------------------------------------------------------------------
junk = [R("安士全書", source="x"), R("文昌帝君陰騭文廣義節錄", source="x")]
check("rank", rank(junk, "斗破苍穹"), [], "全是不相关结果时返回空，不硬凑")

# ---------------------------------------------------------------------------
print("\n[5] 作者搜索 —— 关键词命中的是作者而不是书名")
# ---------------------------------------------------------------------------
gu = [R("微微一笑很倾城", author="顾漫"), R("何以笙箫默", author="顾漫"),
      R("杉杉来吃", author="顾漫"), R("活着", author="余华")]
got = rank(gu, "顾漫")
check("rank", [r.title for r in got],
      ["微微一笑很倾城", "何以笙箫默", "杉杉来吃"], "只留作者是顾漫的三本")
check("rank", all(r.by_author for r in got), True, "三条都被标记成作者命中")

# 「顾漫著」这种带后缀的作者字段也要认
check("rank", len(rank([R("微微一笑很倾城", author="顾漫著")], "顾漫")), 1,
      "作者字段带「著」字仍然匹配")

# 书名命中必须优先于作者命中 —— 找到"就叫这个名字"的书时，作者结果退居其后
mix = [R("顾漫", author="某某"), R("微微一笑很倾城", author="顾漫")]
check("rank", [r.title for r in rank(mix, "顾漫")], ["顾漫"],
      "书名精确命中时不混入作者结果")

# 单字关键词不给作者分（「唐」「白」这类名字太常见，纯噪音）
check("rank", rank([R("活着", author="余华"), R("某杂项页", author="唐")], "唐"), [],
      "单字关键词不走作者匹配")

# 搜书名时不能被作者匹配污染：搜「活着」仍要拿到余华的《活着》
check("rank", [r.title for r in rank([R("活着", author="余华")], "活着")], ["活着"],
      "正常书名搜索不受影响")

# 作者名是别人名字的子串时（顾漫 ⊂ 顾漫夏），完全一致的要排在前面
sub = [R("沈先生又在刷存在感", author="顾漫夏"), R("骄阳似我", author="顾漫")]
check("rank", [r.title for r in rank(sub, "顾漫")], ["骄阳似我", "沈先生又在刷存在感"],
      "作者名完全一致的排在「名字含关键词」的前面")

# ---------------------------------------------------------------------------
print("\n[6] 书名清洗 —— 剥掉站点硬塞的分类/序号前缀")
# ---------------------------------------------------------------------------
from app.relevance import clean_title  # noqa: E402

# 该剥的
STRIP = [
    ("[玄幻]斗破苍穹", "斗破苍穹"),
    ("[网游]穿越斗破苍穹", "穿越斗破苍穹"),
    ("【12】活着", "活着"),
    ("[1]活着", "活着"),
    ("（都市）活着", "活着"),
    ("[都市] 活着", "活着"),
]
for src, want in STRIP:
    check("clean_title", clean_title(src), want, f"{src} → {want}")

# **不该剥的** —— 剥错了就是把书名改坏，比留着脏前缀更糟
KEEP = [
    "[HP]魔法觉醒",      # 同人圈的方括号是作品名的一部分
    "[综]某科学的超电磁炮",
    "斗破苍穹",           # 本来就没前缀
    "[玄幻]",            # 只有分类、剥完为空 → 原样保留
    "魔法禁书目录[新约]",   # 方括号在**结尾**，不是前缀
]
for src in KEEP:
    check("clean_title", clean_title(src), src, f"{src} 不应被改动")

# display_title 走的是同一条清洗
from app.models import BookResult  # noqa: E402
same = BookResult(title="[玄幻]斗破苍穹", author="", source="s", url="u")
check("display_title", same.display_title, "斗破苍穹", "BookResult.display_title 也清洗")
check("to_dict", same.to_dict().get("display_title"), "斗破苍穹", "to_dict 带上 display_title")
check("to_dict", same.to_dict().get("title"), "[玄幻]斗破苍穹", "原始 title 保持不变")

# ---------------------------------------------------------------------------
print("\n[7] 站点名后缀 —— 同一本书的两条要能合并")
# ---------------------------------------------------------------------------
from app.relevance import normalize, _dedup  # noqa: E402

# 实测：搜《欢迎进入梦魇直播间》，m.akshu88.com 回了同一本书两条，
# 第二条标题多了站点名「笔趣阁」→ normalize 后键不同 → 去重失效，
# 用户看到"两个来源"，其实是一个站同一本书。
TAILS = [
    ("欢迎进入梦魇直播间", "欢迎进入梦魇直播间笔趣阁"),
    ("三体", "三体小说网"),
    ("活着", "活着阅读网"),
    ("三体", "三体（全文阅读）"),
]
for base, t in TAILS:
    check("normalize", normalize(t) == normalize(base), True,
          f"{t} 去掉后缀后应与 {base} 同键")

dup2 = [
    BookResult(title="欢迎进入梦魇直播间", author="", source="web",
               url="http://m.akshu88.com/book/101965698.html"),
    BookResult(title="欢迎进入梦魇直播间笔趣阁", author="", source="web",
               url="http://m.akshu88.com/book/j101965698.html"),
]
check("_dedup", len(_dedup(dup2)), 1, "站点名后缀造成的重复应被合并")

# **不能误伤的真书名** —— 剥错了就是把书改坏，比留着后缀更糟。
# 这里断言的是「归一化结果 == 原词本身」，所以这些词必须是不含标点/不需要
# 转换的形态；一旦被 SEO_TAIL_RE 误剥，就会变成更短的前缀而对不上。
KEEPT = ["小说家", "下载人生", "书院风云", "免费的代价", "书城纪事", "全集", "活着"]
for t in KEEPT:
    check("normalize", normalize(t), t.lower(), f"《{t}》不该被剥")

# ---------------------------------------------------------------------------
print("\n[8] 多词关键词 —— 「余华 活着」这种搜法")
# ---------------------------------------------------------------------------
from app.relevance import _split_terms, score_multi  # noqa: E402

# 拆词
check("_split_terms", _split_terms("余华 活着"), ["余华", "活着"], "空格分隔")
check("_split_terms", _split_terms("余华+活着"), ["余华", "活着"], "加号分隔")
check("_split_terms", _split_terms("余华,活着"), ["余华", "活着"], "逗号分隔")
check("_split_terms", _split_terms("活着"), ["活着"], "单词不拆")

# 搜「余华 活着」：书名 + 作者**都中**的排第一，只中一个的退后
multi = [
    BookResult(title="活着", author="余华", source="s", url="u1"),
    BookResult(title="活着", author="未知", source="s", url="u2"),
    BookResult(title="兄弟", author="余华", source="s", url="u3"),
]
got = [r.title for r in rank(multi, "余华 活着")]
check("rank", got[0], "活着", "书名+作者都中的排第一")
sc_both = [score_multi(r, "余华 活着") for r in multi]
check("score_multi", sc_both[0] > sc_both[1], True, "全中 > 只中书名")
check("score_multi", sc_both[0] > sc_both[2], True, "全中 > 只中作者")
# 一个词都不中的直接出局
nohit = [BookResult(title="三体", author="刘慈欣", source="s", url="u9")]
check("score_multi", score_multi(nohit[0], "余华 活着"), 0.0, "一个词都不中 → 0 分")

# —— 防回归：不能把 score() 的兜底尾巴当成「命中」 ——
# score() 对任何书都至少给 2 分（有作者信息 +2）。早期版本用 `s > 0` 判命中，
# 于是《活着》/未知作者 对「余华」的 2 分被算成命中，与正主并列 110 分。
from app.relevance import _HIT_MIN, score as _sc

_ghost = BookResult(title="活着", author="未知", source="s", url="g1")
check("score_multi", _sc(_ghost, "余华") < _HIT_MIN, True,
      "兜底分（2.0）不得被当成命中「余华」")
check("score_multi", _ghost.by_author if hasattr(_ghost, "by_author") else False, False,
      "未命中作者时不得打 by_author 标记")
# 全中（110）必须**严格大于**只中书名（76.5），否则排序没有区分度
check("score_multi", sc_both[0] > sc_both[1] + 20, True,
      "全中要与只中书名拉开明显差距（>20 分）")
# 只中作者（60）与只中书名（76.5）都要留在场上，不能被误杀成 0
check("score_multi", sc_both[1] >= _HIT_MIN and sc_both[2] >= _HIT_MIN, True,
      "只中一个词的结果应保留（≥ _HIT_MIN）")

# —— 账目报告：说清楚「这批候选是怎么没的」 ——
# 动机（2026-10-21 线上）：日志只有 `search.rank 原始=14 去噪后=2`，
# 它说"14 条里留了 2 条"，但**不说那 12 条是什么、为什么被丢**。
# 于是「这本书搜不到」无法复盘 —— "站点返回的全是别的书"和
# "规则把好结果也挤掉了"在这一行里长得一模一样，处置却完全相反。
print("\n[9] 账目报告 —— 被丢掉的候选要说得出理由")
_rpt: dict = {}
_books = [R("诡秘之主", "s1", "u1")]
_books += [R(f"无关的书{i}", f"n{i}", f"n{i}") for i in range(6)]
_out = rank(list(_books), "诡秘之主", report=_rpt)
check("report", _rpt.get("kept"), len(_out), "留下的条数要和真实返回一致")
check("report", _rpt.get("raw"), 7, "原始条数")
check("report", _rpt.get("below_cut_n"), 6, "6 条无关书应记在「低于门槛」里")
check("report", any("无关的书" in t for t, _ in _rpt.get("below_cut") or []), True,
      "被丢的标题要能看见（否则等于没记）")
check("report", _rpt.get("cut", 0) > 0, True, "门槛值要报出来（复盘时要判断是不是阈值太高）")

# 不传 report 时必须照旧工作（不能因为加了埋点就要求人人都传）
check("rank(不传 report)", len(rank(list(_books), "诡秘之主")), len(_out),
      "加 report 不能改变原有行为")

# —— 反向：一条都没丢时不要瞎报「丢了」——否则日志里全是噪声，等于没信号
_rpt2: dict = {}
rank([R("三体", "s1", "u1")], "三体", report=_rpt2)
check("report", _rpt2.get("below_cut_n"), 0, "没丢东西就不能报丢弃")
check("report", _rpt2.get("loose_n"), 0, "同上")
check("report", _rpt2.get("deduped_n"), 0, "同上")

# —— ★ 同站重名是「去重」，不许算成「规则太狠」 ——
# 线上实测错报（2026-10-21）：
#   search.rank.drop 关键词=斗破苍穹 … 非确切命中被挤掉=1
#   例子=['[玄幻]斗破苍穹：与女王陛下的爱恨情仇', '斗破苍穹']
# 第二条《斗破苍穹》分数 100、tightness=1.0，它根本不是被规则挤掉的，
# 是被 _dedup 当成"同站同名"合并了（该站把同一本书挂在两个路径下）。
# 把去重算进"规则太狠"，复盘就会去改本来就对的阈值 —— 账目错比没账目更坏。
_rpt3: dict = {}
_same = [R("斗破苍穹", "s1", "u1", "天蚕土豆"), R("斗破苍穹", "s1", "u9", "天蚕土豆"),
         R("[玄幻]斗破苍穹：与女王陛下的爱恨情仇", "s1", "u2", "天蚕土豆")]
_out3 = rank(_same, "斗破苍穹", report=_rpt3)
check("report", _rpt3.get("deduped_n"), 1, "同站同名那条应记在「去重」里")
check("report", any("斗破苍穹" == t for t, _ in _rpt3.get("deduped") or []), True,
      "被并掉的正主书名要能看见")
check("report", _rpt3.get("loose_n"), 1,
      "非确切命中被挤掉的是那条玄幻同人（1 条），不是正主")
check("report", all("玄幻" in t for t, _ in _rpt3.get("loose") or []), True,
      "「非确切命中被挤掉」里只许出现确实不是确切命中的那些")
check("report", len(_out3), 1, "最终只剩 1 条（另一条同站重名被并掉）")

# 反向：没有「确切命中」时，loose 必须是 0（那时规则没生效，谁都没被挤掉）
_rpt4: dict = {}
rank([R("三体漫谈", "s1", "u1"), R("三体艺术", "s2", "u2")], "三体", report=_rpt4)
check("report", _rpt4.get("loose_n"), 0, "没有确切命中时不该报「被挤掉」")

print()
if FAILS:
    print(f"❌ {len(FAILS)} 项未通过：")
    for f in FAILS:
        print("   -", f)
    sys.exit(1)
print("✅ 全部通过")
