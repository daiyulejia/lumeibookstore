r"""书页 URL 形状判定的回归测试 —— 零依赖，直接跑：

    .venv/Scripts/python.exe tools/test_bookurl.py

这些都是**真实踩过的坑**：

  搜「余华」返回的「附：英文版、法文版和德文版评论摘要」，URL 是
  `https://www.384g.com/html/102/102114/79.html` —— 那是**一章正文**，
  却被当成书收进结果，探测时报「这个地址不是目录页（没解析到章节列表）」。

  根因：`_BOOK_PATH` 的第 2 条 `/html/[#\d]+/[#\d]+/?` 对
  `/html/102/102114/79.html` 会**部分命中**（`/html/102/102114/` 那段），
  因为 `re.search` 不要求匹配到结尾。

另一个更阴的坑（改这个文件必看）：
  `_BOOK_PATH` 吃的是**模板化路径**（数字已换成 `#`），所以量词只能用 `+`。
  写 `{2,}` / `{3,}` 永远落空 —— 正则看着没问题，实际一个都不命中，
  而且**不报错**，只是静默走兜底组，把书页全丢进"不像书"那一档。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.sources.registry_source import looks_like_book_url  # noqa: E402

FAILS: list[str] = []


def check(got, want, label: str) -> None:
    if got != want:
        FAILS.append(f"{label} 期望 {want} 实际 {got}")
        print(f"  ✗ {label}  期望 {want} 实际 {got}")
    else:
        print(f"  ✓ {label}")


print("\n[G] 书页 URL 形状 —— 书页要认得出，章节页要挡住")

# —— 书页：各站最常见的目录页形态 ——
OK = [
    ("https://www.384g.com/html/102/102114/", "杰奇 CMS（384g）"),
    ("https://www.xbiquge.info/0/143/", "xbiquge 两段数字"),
    ("https://www.book.com/book/123456/", "book 系"),
    ("https://www.a.com/info/1234567/", "info 系"),
    ("https://www.a.com/xs/1234567/", "xs 系"),
    ("https://www.a.com/read/998877/", "read 系"),
    ("https://www.a.com/novel/123456/", "novel 系"),
    ("https://www.a.com/123456/", "单段大编号"),
]
for u, desc in OK:
    check(looks_like_book_url(u), True, f"{desc} 应判为书页")

# —— 章节正文页：必须挡住 ——
#   判据是「路径最后一段是 数字.html」。这不是苛刻，是必须：
#   章节混进来后，用户点"开始阅读"会直接落到某一章，不是这本书。
BAD = [
    ("https://www.384g.com/html/102/102114/79.html", "杰奇章节正文（本次踩的坑）"),
    ("https://www.xbiquge.info/0/143/12345.html", "xbiquge 章节"),
    ("https://www.book.com/book/123456/789.html", "book 系章节"),
    ("https://www.a.com/html/102/102114/1.html", "章号很小（第 1 章）"),
]
for u, desc in BAD:
    check(looks_like_book_url(u), False, f"{desc} 不该判为书页")

# —— 压根不是书的页面 ——
NAV = [
    ("https://www.a.com/", "首页"),
    ("https://www.a.com/rank/", "榜单页"),
    ("https://www.a.com/tag/xuanhuan/", "分类页"),
    # 这几条是"放宽单段形态"时差点放进来的 ——
    #   模板化把整段数字压成一个 `#`，`/page/2/` 和 `/123456/` 长得一样，
    #   所以单段形态必须回**原始路径**数数字位数，不能只看模板。
    ("https://www.a.com/page/2/", "分页"),
    ("https://www.a.com/list/12/", "列表页"),
    ("https://www.a.com/user/888/", "用户页"),
    ("https://www.a.com/rank/1/", "榜单分页"),
    ("https://www.a.com/12/", "两位页码"),
]
for u, desc in NAV:
    check(looks_like_book_url(u), False, f"{desc} 不该判为书页")

print()
if FAILS:
    print(f"❌ {len(FAILS)} 项失败：")
    for f in FAILS:
        print("   -", f)
    sys.exit(1)
print("✅ 全部通过")
