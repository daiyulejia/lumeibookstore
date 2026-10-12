r"""脏数据拦截的回归测试 —— 零依赖，直接跑：

    .venv/Scripts/python.exe tools/test_junk.py

覆盖两个**真实踩过的坑**（都来自搜「余华 活着」）：

  ① 话题标签符污染书名
     搜索引擎会把 `#活着` 这种话题标签原样带进标题，`clean_book_title`
     没剥，于是展示出来是 `#活着`，而且 normalize 之后和别的源对不上，
     影响「同一本书」的合并判断。

  ② 影视站被当成小说站
     `hbsjob.cn/voddetail/35245.html`（首播网）是苹果 CMS 视频站，
     详情页列的是「第01集、第02集…」的**剧集列表**，启发式数一数够 8 条、
     质量分也够，就被判成 `kind="toc"` 收成一本可读的书。
     正文其实是那部韩国丧尸片《#活着》的剧情简介，完全是另一回事。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.discovery import clean_book_title  # noqa: E402
from app.webfetch import (  # noqa: E402
    _EPISODE_TEXT_RE,
    _VIDEO_NAME_RE,
    _VIDEO_PATH_RE,
)

FAILS: list[str] = []


def check(got, want, label: str) -> None:
    if got != want:
        FAILS.append(f"{label} 期望 {want} 实际 {got}")
        print(f"  ✗ {label}  期望 {want} 实际 {got}")
    else:
        print(f"  ✓ {label}")


def truthy(got, label: str) -> None:
    check(bool(got), True, label)


def falsy(got, label: str) -> None:
    check(bool(got), False, label)


print("\n[1] 话题标签符 —— 书名不能带 #")
check(clean_book_title("#活着"), "活着", "行首 # 要剥掉")
check(clean_book_title("＃活着"), "活着", "全角 ＃ 也要剥")
check(clean_book_title("# 活着"), "活着", "# 后有空格也要剥")
check(clean_book_title("#活着_首播网"), "活着", "标签符 + 站点后缀")
# 正常书名不能被误伤
check(clean_book_title("活着"), "活着", "正常书名不动")
check(clean_book_title("C#入门经典"), "C#入门经典", "书名中间的 # 不能剥")
check(clean_book_title("三体（全集）"), "三体", "原有剥括号能力不受影响")

print("\n[2] 影视站路径 —— 苹果 CMS 特征词")
for u, label in [
    ("https://hbsjob.cn/voddetail/35245.html", "voddetail"),
    ("https://x.com/vodplay/1-2-3.html", "vodplay"),
    ("https://x.com/vodtype/2.html", "vodtype"),
    ("https://x.com/vodshow/1--------.html", "vodshow"),
    ("https://x.com/vodsearch/xxx.html", "vodsearch"),
    ("https://x.com/vod/123.html", "裸 vod 段"),
    ("https://x.com/movie/1234", "movie"),
    ("https://x.com/film/9.html", "film"),
]:
    truthy(_VIDEO_PATH_RE.search(u), f"识别影视路径 {label}")

for u, label in [
    ("https://www.kunnu8.com/huozhe/", "鲲弩小说书页"),
    ("https://www.wyshu.com/xd/huozhao/", "wyshu 书页"),
    ("https://m.akshu88.com/book/101965698.html", "akshu88 书页"),
    ("https://www.xbqg5200.com/book/1234/", "笔趣阁书页"),
    ("https://example.com/html/102/102114/", "通用数字目录"),
    ("https://example.com/b/zh/", "b 路径"),
]:
    falsy(_VIDEO_PATH_RE.search(u), f"不误杀小说路径 {label}")

print("\n[3] 剧集用词 —— 「第N集」是分集，不是章节")
for t in ["第01集", "第1集", "第 3 期", "第十二集", "第100话", "第2期"]:
    truthy(_EPISODE_TEXT_RE.search(t), f"识别剧集 {t}")
for t in ["第一章", "第1章", "第一百二十三章", "第一节", "序章", "楔子"]:
    falsy(_EPISODE_TEXT_RE.search(t), f"不误杀章节 {t}")

print("\n[4] 影视站站名")
for n in ["首播网影视", "南瓜影院", "某某剧场", "天天追剧"]:
    truthy(_VIDEO_NAME_RE.search(n), f"识别影视站名 {n}")
for n in ["鲲弩小说", "落霞读书", "维基文库", "笔趣阁"]:
    falsy(_VIDEO_NAME_RE.search(n), f"不误杀小说站名 {n}")

print()
if FAILS:
    print(f"❌ {len(FAILS)} 项未通过：")
    for f in FAILS:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 全部通过")
