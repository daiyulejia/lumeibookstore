"""自有来源（registry）从搜索列表页抽作者的回归。

为什么单独写这个：作者搜索依赖 `BookResult.author`，而自有来源
**以前根本不填这个字段**（只有 probe 打开详情页时才回填）。
结果是搜「顾漫」时站点明明返回了骄阳似我 / 微微一笑很倾城，
但每条 author 都是空的，relevance 的作者匹配没东西可比 → 0 条。

列表页的形态不止一种，这里把见过的几种都钉住：
  ① 表格行（新笔趣阁系）：作者是无标签的第 3 个 <td>，
     而且第 2 格写着「第55章 作者番外语」——拿"作者："去匹配会抽出垃圾。
  ② 标签式：作者：xxx
  ③ 后缀式：xxx 著

用法： python tools/test_registry_author.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.sources.registry_source import _author_near  # noqa: E402

OK = 0
BAD = 0


def check(name: str, got, want) -> None:
    global OK, BAD
    if got == want:
        OK += 1
        print(f"  ✓ {name}  {got!r}")
    else:
        BAD += 1
        print(f"  ✗ {name}  期望 {want!r}，实际 {got!r}")


BASE = "https://www.384g.com/search.php"

# ---------------------------------------------------------------------------
print("\n[1] 表格行 —— 无标签的第 3 格是作者")
# ---------------------------------------------------------------------------
# 真实页面结构（缩略），关键是第 2 格含「作者」二字，绝不能抽成作者
TABLE = """
<table>
  <tr>
    <td class="odd"><a href="/html/406/406301/">骄阳似我</a></td>
    <td class="even"><a href="/html/406/406301/55.html">第55章 作者番外语</a></td>
    <td class="odd">顾漫</td>
    <td class="even">745270K</td>
    <td class="odd" align="left">2024-09-10</td>
    <td class="even" align="left">连载中</td>
  </tr>
  <tr>
    <td class="odd"><a href="/html/272/272593/">微微一笑很倾城</a></td>
    <td class="even"><a href="/html/272/272593/54.html">番外五 哥哥弟弟</a></td>
    <td class="odd">顾漫</td>
    <td class="even">62631K</td>
    <td class="odd" align="left">2024-08-03</td>
    <td class="even" align="left">连载中</td>
  </tr>
</table>
"""
check("表格行抽到作者", _author_near(TABLE, "骄阳似我", BASE), "顾漫")
check("表格行第二个书名也对", _author_near(TABLE, "微微一笑很倾城", BASE), "顾漫")
# 这是核心防回归点：第 2 格里有「作者」二字，不能被当成标签
check("没有把「第55章 作者番外语」当成作者",
      _author_near(TABLE, "骄阳似我", BASE) != "番外语", True)

# ---------------------------------------------------------------------------
print("\n[2] 标签式与后缀式")
# ---------------------------------------------------------------------------
LABEL = '<div class="row"><h3><a href="/x/1">杉杉来吃</a></h3><span>作者：顾漫</span><span>分类：言情</span></div>'
check("「作者：xxx」", _author_near(LABEL, "杉杉来吃", BASE), "顾漫")

SUFFIX = '<dt><a href="/b/2">你是我的荣耀</a></dt><dd>顾漫 著 | 都市 | 2024</dd>'
check("「xxx 著」", _author_near(SUFFIX, "你是我的荣耀", BASE), "顾漫")

# ---------------------------------------------------------------------------
print("\n[3] 找不到就返回空 —— 不许瞎猜")
# ---------------------------------------------------------------------------
NOAUTH = '<div><a href="/b/4">某本书</a><span>分类：玄幻</span><span>状态：连载</span></div>'
check("没有作者信息时返回空", _author_near(NOAUTH, "某本书", BASE), "")
check("书名不在页面里时返回空", _author_near(NOAUTH, "不存在的书名", BASE), "")

# 表格里只有噪音格（字数/日期/状态）时也不能硬凑一个作者出来
NOISE_TABLE = """
<table><tr>
  <td><a href="/html/1/1/">某书</a></td>
  <td><a href="/html/1/1/9.html">第9章 大结局</a></td>
  <td>2048K</td><td>2024-01-01</td><td>连载中</td>
</tr></table>
"""
check("表格里只有噪音格时返回空", _author_near(NOISE_TABLE, "某书", BASE), "")

# 少数民族名带间隔号
ETH = '<tr><td><a href="/b/9">草原牧歌</a></td><td><a href="/b/9/1.html">第1章</a></td><td>玛拉沁夫·巴雅尔</td><td>30K</td><td>完本</td></tr>'
check("带间隔号的名字", _author_near(ETH, "草原牧歌", BASE), "玛拉沁夫·巴雅尔")

print()
if BAD:
    print(f"❌ {BAD} 项未通过（{OK} 通过 / {BAD} 失败）")
    sys.exit(1)
print(f"✅ 全部通过（{OK} 项）")
