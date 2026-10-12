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

print()
if FAILS:
    print(f"❌ {len(FAILS)} 项未通过：")
    for f in FAILS:
        print("   -", f)
    sys.exit(1)
print("✅ 全部通过")
