# -*- coding: utf-8 -*-
"""通用解析的离线回归：目录排序、目录质量评分、正文成色判定。

为什么要有这一份
----------------
这三处判据都是从**真实站点**上打出来的（29zw 的目录乱序、塔读的 1561 条
假章节、塔读的控件页冒充正文），修完很容易被后来的改动碰坏 —— 而
碰坏了平时看不出来：目录还是能出 4543 条、正文还是"有 440 字"，
只是顺序全乱、或者把付费站标成可读。

所以把它们钉在这里：**全部用本地 HTML 字符串**，不联网、不依赖任何
站点当天活不活得下来。跑一次不到一秒。

用法：python tools/test_parse.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import webfetch  # noqa: E402
from app.sources.base import check_content_quality  # noqa: E402

ok_n = 0
fail_n = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global ok_n, fail_n
    if cond:
        ok_n += 1
        print(f"  ✓ {name}")
    else:
        fail_n += 1
        print(f"  ✗ {name} {extra}")


# ---------------------------------------------------------------------------
# 坑 1：同模板双区块
# ---------------------------------------------------------------------------
def _toc_page(total: int = 60, panel: int = 9) -> str:
    """仿 29zw 的详情页：顶部「最新章节」倒序面板 + 下方完整目录（正序）。

    顶部那块是**最后 N 章的倒序副本**（URL 和完整目录里那几条一模一样），
    两块 URL 模板也一模一样 —— 所以按模板扁平分组必然把它们合成一组。

    刻意用一本**只有 60 章**的小书：29zw 那本是 4543 章，
    倒序的 9 条只占 0.2%，怎么排都对；换成本这种小书，
    同样的 9 条就占了 13%，原来那套「97% 有序才重排」的判据会直接放弃排序，
    用户看到的第一条就成了「第60章 大结局」。
    """
    full = "\n".join(
        f'<dd><a href="/book/999/{n}.html">第{n}章 标题{n}</a></dd>'
        for n in range(1, total + 1))
    top = "\n".join(
        f'<dd><a href="/book/999/{n}.html">第{n}章 标题{n}</a></dd>'
        for n in range(total, total - panel, -1))          # 倒序，URL 与上面重复
    return (
        "<html><head><title>测试书 - 测试小说网</title>"
        '<meta property="og:site_name" content="测试小说网"></head><body>'
        f'<div class="latest"><dl>{top}</dl></div>'
        f'<div id="list-chapterAll"><dl class="panel-body">{full}</dl></div>'
        "</body></html>"
    )


def test_toc() -> None:
    print("\n—— 目录：同模板双区块要按章节号重排 ——")
    html = _toc_page()
    toc = webfetch.extract_toc(html, "https://demo.test/book/999/")
    titles = [c["title"] for c in toc]

    check("解析出了目录", len(toc) == 60, f"得到 {len(toc)} 条")
    check("第一条是第1章（不是顶部倒序面板里的第60章）",
          bool(toc) and titles[0].startswith("第1章"), str(titles[:3]))
    check("最后一条是第60章",
          bool(toc) and titles[-1].startswith("第60章"), str(titles[-3:]))

    nums = [int(t[1:].split("章")[0]) for t in titles if t.startswith("第") and "章" in t]
    asc = all(nums[i] >= nums[i - 1] for i in range(1, len(nums)))
    check("章节号整体递增", asc, str(nums[:12]))
    check("重复的 URL 被去掉了", len(set(c["url"] for c in toc)) == len(toc))

    q, why = webfetch.toc_quality(toc)
    check("目录质量评分够高", q >= 0.55, f"q={q} why={why}")

    # 更极端：40 章的书，倒序面板 9 条，占比 22%
    toc2 = webfetch.extract_toc(_toc_page(total=40), "https://demo.test/book/999/")
    check("小书（40 章）也排得对",
          len(toc2) == 40 and toc2[0]["title"].startswith("第1章")
          and toc2[-1]["title"].startswith("第40章"),
          f"{len(toc2)} 条，首 {toc2[0]['title'] if toc2 else '-'} 末 {toc2[-1]['title'] if toc2 else '-'}")


def test_toc_quality_rejects_junk() -> None:
    print("\n—— 目录质量：识别「猜你喜欢」那种假目录 ——")
    # 仿塔读：一堆详情页链接，条目数够多、URL 也同模板，但**不是章节**
    junk = [
        {"title": f"《猜你喜欢{ i }》", "url": f"https://demo.test/book/{1000 + i}/"}
        for i in range(40)
    ]
    q, why = webfetch.toc_quality(junk)
    check("假目录评分低（会被判成 unknown）", q < 0.55, f"q={q} why={why}")

    real = [
        {"title": f"第{i}章 标题", "url": f"https://demo.test/book/9/{i}.html"}
        for i in range(1, 41)
    ]
    q2, _ = webfetch.toc_quality(real)
    check("真目录评分高", q2 >= 0.55, f"q={q2}")


def test_site_name() -> None:
    print("\n—— 站名：从 title 尾巴 / og:site_name 里认出来 ——")
    cases = [
        ('<html><head><title>药鼎仙途最新章节-29中文小说网</title></head></html>', "29中文小说网"),
        ('<html><head><title>药鼎仙途在线阅读 - 寒香寂寞  - 落霞读书</title></head></html>', "落霞读书"),
        ('<html><head><meta property="og:site_name" content="起点中文网">'
         '<title>x</title></head></html>', "起点中文网"),
        # 「免费阅读」这种尾巴不是站名 —— 宁可返回空，也不要瞎认
        ('<html><head><title>某书免费阅读无弹窗</title></head></html>', ""),
    ]
    for html, want in cases:
        got = webfetch.extract_site_name(html)
        check(f"认站名 {want or '(空)'}", got == want, f"得到 {got!r}")


# ---------------------------------------------------------------------------
# 坑 2：控件页冒充正文
# ---------------------------------------------------------------------------
# 塔读某章真实抽出来的形状：61 行 / 440 字，平均每行 7 个字，一个字正文没有
_TADU_SKELETON = """已在书架
快来设置你喜欢的阅读方式吧~
阅读主题：
字体大小：
16
18
20
22
24
26
28
页面宽度：
800
900
1280
保存
扫码手机阅读
第二卷第五章 对策
书名：药鼎仙途
作者：寒香寂寞
字数：3315
更新时间：2011-04-05 09:42:50
您还未登录，登录后看书更方便
登录后可记录阅读进度，发表评论，为喜欢的作者投银票、打赏
微信登录
QQ登录
微博登录
手机号登录
投银票
《药鼎仙途》这本书很棒，快来投票吧~
当前可投票
立即投票
如何获取银票？
提示
投票成功
确认
打赏本书
《药鼎仙途》这本书很棒，决定打赏一下~
100塔豆
500塔豆
1000塔豆
5000塔豆
10000塔豆
188888塔豆
写的真好，塔豆奉上！
120字符
立即打赏"""

_REAL_CHAPTER = "\n".join([
    "张凡转过身来，看着那片被夕阳染红的山谷，心里说不出的滋味。"
    "他想起三年前第一次站在这里时，手里连一柄像样的剑都没有。"
]) * 40

# 正文里正巧提到「登录」——不该被误杀
_REAL_WITH_WORD = "他打开电脑，输入账号密码，点了一下登录按钮，屏幕跳转，出现了一行小字：欢迎回来。" * 25


def test_skeleton() -> None:
    print("\n—— 正文成色：控件页不能算正文 ——")
    check("控件页被认出来", webfetch.looks_like_ui_skeleton(_TADU_SKELETON))
    bad, why = check_content_quality(_TADU_SKELETON)
    check("控件页质量判定不过关", not bad, why)

    check("真实章节不被误判", not webfetch.looks_like_ui_skeleton(_REAL_CHAPTER))
    good, _ = check_content_quality(_REAL_CHAPTER)
    check("真实章节判定通过", good)

    check("正文里提到「登录」不误杀", not webfetch.looks_like_ui_skeleton(_REAL_WITH_WORD))
    check("正文里提到「登录」质量判定通过", check_content_quality(_REAL_WITH_WORD)[0])

    # 短文本不该被这条判据处理（长度那条管）
    check("很短的文本不触发控件判据", not webfetch.looks_like_ui_skeleton("他走了。\n风很大。"))


# ---------------------------------------------------------------------------
# 坑 3：没抽样 ≠ 可读
# ---------------------------------------------------------------------------
def test_readable_needs_evidence() -> None:
    print("\n—— 可读性：没有证据不许说可读 ——")
    from app.models import BookResult

    r = BookResult(title="x", source="web", url="https://a.test/1")
    r.available = True
    check("目录可达但没抽过 → 不算可读", not r.readable)

    r.sampled = True            # 抽过，但这个来源没有单章接口（维基文库那种）
    r.sample_ok = None
    check("抽过但无结论 → 按可用算（单页来源才走这里）", r.readable)

    r.sample_ok = False         # 抽过、是假的
    check("抽过且是假的 → 不可读", not r.readable)

    r.sample_ok = True
    check("抽过且正常 → 可读", r.readable)

    r2 = BookResult(title="y", source="web", url="https://b.test/1")
    r2.available = False
    r2.sampled = True
    r2.sample_ok = True
    check("目录都打不开 → 一律不可读", not r2.readable)


def main() -> int:
    test_toc()
    test_toc_quality_rejects_junk()
    test_site_name()
    test_skeleton()
    test_readable_needs_evidence()
    print(f"\n{'✅ 全部通过' if not fail_n else '❌ 有失败'}（{ok_n} 通过 / {fail_n} 失败）")
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
