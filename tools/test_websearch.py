"""联网候选的「名额分配」：一个引擎的噪声不许吃光另一个引擎的真结果。

现场（2026-11-04 22:37，线上《情欲超市全集》）
--------------------------------------------
`search.done` 那一行是 `候选=0 确切=0 可读=0 联网=preempt
联网核="12→0 失败=1(www.2yuedu.com) 非目录=11(www.jfdaily.com,...)"` ——
12 个候选、核实完全部判「不是目录」，读起来就是"网上没有这本书"。

真机复现（同一台服务器、同一个关键词）把两个引擎分开看：

    Bing 10 条：京华网/环球网/千龙网/中青在线/东北网/齐鲁晚报…
                《四年级女儿洗澡时，妈妈无意间瞄了一眼》《女子写淫秽小说被判10年半案》
                —— **撞词的新闻**，一条书页都没有
    百度  7 条：ldks.cc / m.31xs.com / 2yuedu / aihewens / xkushu / dyxlib / 35xs
                —— 其中 m.31xs.com/12/12741/ 能开出 112 章

而 `find_book_pages()` 原来是「Bing 全铺在前、百度接在后，截到 limit=12」：
9 条新闻页把名额占光，百度只剩 3 个位置。那 3 个恰好是死站 + 一个章节页 +
一个打不开 → 0 命中。**书就在那儿，是我们没去核它。**

为什么这条判据以前没抓到
------------------------
`find_book_pages()` 是本模块里唯一**没有任何测试**的函数（`tools/` 下只有
`test_discover_async.py` 把整个函数用假数据替换掉了）。名额分配这种
"看起来只是列表拼接"的逻辑，从来没人验过；线上表现又只是"搜不到"。
配套补的埋点：`联网候选: 去重前=N 取=M 各引擎=bing9 百度7` +
`联网核` 那一格多一个 `引擎=bing6,baidu6`。

判据三问
--------
① 会不会只因环境变？—— 全部用假引擎，不碰网络、不算耗时。
② 把功能拆掉这条还绿吗？—— 见 `tools/mutate.py` 的「名额」组。
③ 只验了正向没验反向吗？—— 第 2 组把两个引擎对调（真书页在 Bing、
   噪声在百度），确认不是"专门保百度"。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import websearch as W                              # noqa: E402
from app import discovery as D                              # noqa: E402
from app.engine import web_ledger                           # noqa: E402

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


def item(host: str, title: str = "", path: str = "/book/1/", engine="bing"):
    return {"url": f"https://{host}{path}", "host": host,
            "title": title, "engine": engine}


# 线上真实形状：Bing 回 9 个新闻站（标题全与书名无关），百度回 7 个书页
NEWS = [
    ("www.jfdaily.com", "女子写淫秽小说被判10年半案"),
    ("3w.huanqiu.com", "四年级女儿洗澡时，妈妈无意间瞄了一眼"),
    ("culture.qianlong.com", "妈妈的高跟鞋 母女的奏鸣曲"),
    ("qnzj.cyol.com", "支教的女友（小说）"),
    ("mzqb.cyol.com", "偷窥（小说）"),
    ("heilongjiang.dbw.cn", "禽兽男子霸占生母八年"),
    ("society.huanqiu.com", "三家小说经营网站被约谈"),
    ("epaper.jinghua.cn", "笔趣阁无弹窗广告小说全文免费阅读"),
    ("www.qlwb.com.cn", "涉淫秽色情，这三家网站被约谈"),
]
BOOKS = [
    ("www.ldks.cc", "情欲超市_吕志王友_在线阅读"),
    ("m.31xs.com", "情欲超市 二_最新章节"),
    ("www.2yuedu.com", "情欲超市 全集_全文阅读"),
    ("www.aihewens.com", "情欲超市"),
    ("wap.xkushu.com", "情欲超市_小说"),
    ("www.dyxlib.cn", "情欲超市 二"),
    ("www.35xs.cc", "情欲超市全集"),
]


def _engine(rows, *, engine: str, path: str):
    """照真引擎的写法造结果：**过一遍 `_add()`**，去噪才会真的被验到。

    ⚠ 第一版这里直接 return 现成的 dict，等于绕过了 `_add()` —— 于是
      「搜索引擎自家域名被滤掉」那条断言拿到的是假绿：`www.baidu.com`
      明明出现在结果里，因为它压根没走过过滤。
    """
    def fn(kw):
        out: list[dict] = []
        for i, (h, t) in enumerate(rows):
            W._add(out, f"https://{h}{path.format(i)}", t, engine)
        return out
    return fn


def run(news, books, *, limit=12):
    """把两个引擎换掉，跑一遍真正的 `find_book_pages`。"""
    old_bing, old_baidu = W._bing, W._baidu
    try:
        W._bing = _engine(news, engine="bing", path="/news/{}.shtml")
        W._baidu = _engine(books, engine="baidu", path="/novel/{}/")
        return W.find_book_pages("情欲超市全集", limit=limit)
    finally:
        W._bing, W._baidu = old_bing, old_baidu


print("=" * 62)
print("A. 9 条噪声 + 7 条真书页：真书页必须拿到一半名额")
print("=" * 62)
got = run(NEWS, BOOKS)
hosts = [g["host"] for g in got]
books_kept = [h for h in hosts if h in dict(BOOKS)]
news_kept = [h for h in hosts if h in dict(NEWS)]
ok("凑满 limit", len(got) == 12, f"取 {len(got)} 条")
ok("真书页 ≥ 6 条（旧写法只有 3 条）", len(books_kept) >= 6,
   f"书页 {len(books_kept)} / 噪声 {len(news_kept)}")
ok("噪声没有吃光名额", len(news_kept) <= 6, f"噪声 {len(news_kept)}")
ok("两个引擎都进得来", {"bing", "baidu"} <= {g["engine"] for g in got},
   str(sorted({g["engine"] for g in got})))

print("=" * 62)
print("B. 反向：真书页在 Bing、噪声在百度 —— 判据不是「专门保百度」")
print("=" * 62)
got2 = run(BOOKS, NEWS)
hosts2 = [g["host"] for g in got2]
books2 = [h for h in hosts2 if h in dict(BOOKS)]
ok("真书页仍然 ≥ 6 条", len(books2) >= 6, f"书页 {len(books2)}/{len(hosts2)}")

print("=" * 62)
print("C. 引擎内部：撞词噪声沉到桶底，别占同一个引擎的前排")
print("=" * 62)
# Bing 自己回 8 条：5 条噪声 + 3 条真书页（百度一条都没有）
mixed = NEWS[:5] + [("www.ldks.cc", "情欲超市_在线阅读"),
                    ("m.31xs.com", "情欲超市 二"),
                    ("www.35xs.cc", "情欲超市全集")]
got3 = run(mixed, [])
ok("前 3 位全是真书页",
   {g["host"] for g in got3[:3]} == {"www.ldks.cc", "m.31xs.com", "www.35xs.cc"},
   str([g["host"] for g in got3[:3]]))
ok("噪声没被扔掉（排序不是门）", len(got3) == 8, f"取 {len(got3)} 条")

print("=" * 62)
print("D. 老规矩不能被这次改动带坏")
print("=" * 62)
# 同一个站最多 per_host 条
dup = [("www.a.com", f"情欲超市 {i}") for i in range(6)]
got4 = run([], dup)
ok("同站最多 2 条", len(got4) == 2, f"取 {len(got4)} 条")
# ⚠ 跨引擎也要算同一个上限：两个引擎都回了这个站，不能变成 2+2=4 条。
#   这是「按引擎分桶」改动的直接副作用 —— 第一版就是 4 条。
got4b = run([("www.a.com", "情欲超市")] * 3, [("www.a.com", "情欲超市")] * 3)
ok("同一个站在两个引擎里出现 → 总数仍 ≤ 2", len(got4b) <= 2, f"取 {len(got4b)} 条")
# 噪声域名照旧过滤
got5 = run([("www.baidu.com", "情欲超市")], BOOKS)
ok("搜索引擎自家域名仍被滤掉", all(g["host"] != "www.baidu.com" for g in got5),
   str([g["host"] for g in got5]))
# 两个引擎都空
got6 = run([], [])
ok("都没结果 → 空列表", got6 == [], str(got6))
# 一个引擎抛异常不影响另一个
old = W._bing
try:
    def boom(kw):
        raise RuntimeError("blocked")
    W._bing = boom
    W._baidu = lambda kw: [item(h, t, f"/n/{i}/", "baidu") for i, (h, t) in enumerate(BOOKS)]
    got7 = W.find_book_pages("情欲超市全集", limit=12)
finally:
    W._bing = old
ok("一个引擎挂了，另一个照常出候选", len(got7) == len(BOOKS), f"取 {len(got7)} 条")

print("=" * 62)
print("E. 账本：名字被截断时必须写出还剩几个 + 候选是谁给的")
print("=" * 62)
many = [f"h{i}.com" for i in range(11)]
led = web_ledger({"cands": 12, "hit": [], "fetch_fail": [],
                  "not_toc": many, "unchecked": 0,
                  "engines": {"bing": 9, "baidu": 3}})
s = led["联网核"]
ok("点名 5 个 + 明写还剩 6 个", "非目录=11(h0.com,h1.com,h2.com,h3.com,h4.com+6)" in s, s)
ok("带引擎分布", "引擎=bing9,baidu3" in s, s)
led2 = web_ledger({"cands": 2, "hit": [], "fetch_fail": [],
                   "not_toc": ["a.com"], "unchecked": 0})
ok("不足 5 个不加 +0", "非目录=1(a.com)" in led2["联网核"]
   and "+0" not in led2["联网核"], led2["联网核"])
ok("没有引擎信息就不打这一格", "引擎=" not in led2["联网核"], led2["联网核"])

print("=" * 62)
print("F. 「引擎」这一格是 discover() 真算出来的，不是手填的")
print("=" * 62)
# ⚠ 第一版只拿手搓的 tally 调 web_ledger()，于是「把计数写成 0」那条突变
#   活得好好的 —— ledger 会照章打出 `引擎=bing0,baidu0`。判据必须穿过
#   discover()：**数是从候选上数出来的**，不是外面塞进来的。
_cands = ([{"url": f"https://news{i}.test/a.shtml", "host": f"news{i}.test",
            "title": "撞词新闻", "engine": "bing"} for i in range(9)]
          + [{"url": f"https://book{i}.test/b/", "host": f"book{i}.test",
              "title": "情欲超市", "engine": "baidu"} for i in range(3)])
_old_find, _old_verify = D.websearch.find_book_pages, D._verify
_old_learn = D.learn_sites
_lines: list[str] = []


class _Cap(logging.Handler):
    def emit(self, rec):
        _lines.append(rec.getMessage())


_log = logging.getLogger("novel.discovery")
_cap = _Cap()
_log.addHandler(_cap)
_lvl = _log.level
_log.setLevel(logging.INFO)


def _fake_verify(cand, keyword, tally=None):
    # 全部判「不是目录」—— 这样名字堆到 12 个，才测得到「+6」那个尾巴。
    D._bump(tally, "not_toc", cand["host"])
    return None


try:
    D.websearch.find_book_pages = lambda kw, **k: [dict(c) for c in _cands]
    D._verify = _fake_verify
    D.learn_sites = lambda *a, **k: {"learned": 0, "failed": 0, "skipped": 0}
    D.discover("情欲超市全集")
    t = D.last_tally()
finally:
    D.websearch.find_book_pages = _old_find
    D._verify = _old_verify
    D.learn_sites = _old_learn
    _log.removeHandler(_cap)
    _log.setLevel(_lvl)

ok("discover 数出的引擎分布 = bing9 / baidu3",
   t.get("engines") == {"bing": 9, "baidu": 3}, str(t.get("engines")))
ok("账本里真带着这一格", "引擎=bing9,baidu3" in web_ledger(t)["联网核"],
   web_ledger(t)["联网核"])

# 「联网核实账」那行也**不许沉默地截断名字**（2026-11-04 线上：
# `不是目录=11(5 个名字)` —— 看上去点名了，其实 6 个名字凭空消失）。
_led = [ln for ln in _lines if "联网核实账" in ln]
ok("核实账那行确实打出 12 个不是目录", _led and "不是目录=12" in _led[-1],
   _led[-1] if _led else "（没有这行日志）")
ok("多于 6 个时要明写还剩几个", _led and "(+6)" in _led[-1],
   _led[-1] if _led else "（没有这行日志）")

print("=" * 62)
print(f"{'全部通过' if not fails else '有失败'}（{ok_n} 通过 / {bad_n} 失败）")
if fails:
    for f in fails:
        print("  ✗", f)
print("=" * 62)
sys.exit(1 if fails else 0)
