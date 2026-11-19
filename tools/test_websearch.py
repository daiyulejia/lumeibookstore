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
# ⚠ 这里必须**两个都还原**。原来只还原了 `_bing`，`_baidu` 的桩就一路泄漏
#   到后面所有组 —— 2026-11-19 加 H 组时踩到：`W._baidu` 还是这里的 lambda，
#   于是"百度被反爬"那组测的是假货，"正常页抽 2 条"拿回来的是真网络的 7 条。
#   桩不还原 = 后面所有判据都在测上一组的残骸，且**不会报错**。
old = W._bing
old_baidu = W._baidu
try:
    def boom(kw):
        raise RuntimeError("blocked")
    W._bing = boom
    W._baidu = lambda kw: [item(h, t, f"/n/{i}/", "baidu") for i, (h, t) in enumerate(BOOKS)]
    got7 = W.find_book_pages("情欲超市全集", limit=12)
finally:
    W._bing = old
    W._baidu = old_baidu
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
print("G. 候选太薄 → 换一种问法再问一次（2026-11-19）")
print("=" * 62)
# 现场：《遥远的救世主》书名单独问 Bing 只捞回 1 个可用站，百度又被反爬，
# 3 个候选全判"不是目录" → 用户看到 `候选=0`。加问「书名 小说」第一屏就有
# fanqienovel（实抓 33 章）。这条判据量的是**问了几次**和**合并后有几条**，
# 全部用假引擎，不碰网络、不算耗时。


def _one(host: str, path: str, title: str = "遥远的救世主") -> list[dict]:
    out: list[dict] = []
    W._add(out, f"https://{host}{path}", title, "bing")
    return out


def _blocked(kw):
    raise W.EngineBlocked("被反爬（HTTP 302，474 字节验证页）")


_old_bing, _old_baidu = W._bing, W._baidu
_calls: list[str] = []
try:
    def _bing_thin(kw):
        _calls.append(kw)
        if kw.endswith(W.SECOND_QUERY_SUFFIX):
            return _one("www.fanqie.test", "/page/1")
        return _one("www.youyiyan.test", "/book/1")

    W._bing = _bing_thin
    W._baidu = _blocked
    got_thin = W.find_book_pages("遥远的救世主", limit=14)
finally:
    W._bing, W._baidu = _old_bing, _old_baidu

ok("第一轮只有 1 条 → 真的加问了一次",
   _calls == ["遥远的救世主", "遥远的救世主" + W.SECOND_QUERY_SUFFIX], str(_calls))
ok("加问找回来的站进了候选（不只是多问一句）",
   any(g["host"] == "www.fanqie.test" for g in got_thin),
   str([g["host"] for g in got_thin]))
ok("两轮结果合并在一个列表里（第一轮的没被挤掉）",
   {g["host"] for g in got_thin} == {"www.youyiyan.test", "www.fanqie.test"},
   str([g["host"] for g in got_thin]))

# 反向①：候选够多就不许再问（否则每个搜索都白多一个请求 + 一堆噪声）
_calls2: list[str] = []
_old_bing, _old_baidu = W._bing, W._baidu
try:
    def _bing_rich(kw):
        _calls2.append(kw)
        rows: list[dict] = []
        for i in range(4):
            rows += _one(f"www.b{i}.test", f"/b/{i}")
        return rows

    W._bing = _bing_rich
    W._baidu = _blocked
    got_rich = W.find_book_pages("遥远的救世主", limit=14)
finally:
    W._bing, W._baidu = _old_bing, _old_baidu

ok("第一轮已有 4 条 → **不**加问（只问一次）", len(_calls2) == 1, str(_calls2))
ok("并且结果就是第一轮那 4 条", len(got_rich) == 4, str(len(got_rich)))

# 反向②：两轮都命中同一个站时，名额不许翻倍（per_host 是全局上限）
# 这条是第二轮的**副作用**判据：把第二轮当成"新的一轮"重新数名额，
# 同一个站就能占走两倍的位置 —— 那正是 11-04「一个站刷满列表」的原病。
_old_bing, _old_baidu = W._bing, W._baidu
try:
    def _bing_same(kw):
        rows: list[dict] = []
        if kw.endswith(W.SECOND_QUERY_SUFFIX):
            rows += _one("www.same.test", "/s/3")
            rows += _one("www.same.test", "/s/4")
        else:
            rows += _one("www.same.test", "/s/1")
            rows += _one("www.same.test", "/s/2")
        return rows

    W._bing = _bing_same
    W._baidu = _blocked
    got_same = W.find_book_pages("遥远的救世主", limit=6, per_host=2)
finally:
    W._bing, W._baidu = _old_bing, _old_baidu

ok("跨两轮仍然 per_host=2（同一个站不靠两次问法占 4 个名额）",
   len([g for g in got_same if g["host"] == "www.same.test"]) == 2,
   str([g["url"] for g in got_same]))

# 账本：第二轮必须留下「第一轮几条 / 加问了什么 / 新增几条」
_ws_lines: list[str] = []


class _WsCap(logging.Handler):
    def emit(self, rec):
        _ws_lines.append(rec.getMessage())


_wlog = logging.getLogger("novel.websearch")
_wcap = _WsCap()
_wlog.addHandler(_wcap)
_wlvl = _wlog.level
_wlog.setLevel(logging.INFO)
_old_bing, _old_baidu = W._bing, W._baidu
try:
    W._bing = lambda kw: _one("www.only.test", "/o/1")
    W._baidu = _blocked
    W.find_book_pages("遥远的救世主", limit=14)
finally:
    W._bing, W._baidu = _old_bing, _old_baidu
    _wlog.removeHandler(_wcap)
    _wlog.setLevel(_wlvl)

_sec = [ln for ln in _ws_lines if "第二次问法" in ln]
ok("账本点名「第一轮=1 / 加问了什么 / 新增=0」",
   _sec and "第一轮=1" in _sec[-1] and W.SECOND_QUERY_SUFFIX in _sec[-1]
   and "新增=0" in _sec[-1], _sec[-1] if _sec else "（没有这行日志）")

print("=" * 62)
print("H. 百度被反爬 ≠ 百度没有结果（2026-11-19）")
print("=" * 62)
# 现场（本机）：`www.baidu.com/s` 回 HTTP 200 + 2649 字节「百度安全验证」，
# 换 cookie、换 UA、换 m.baidu 都一样 → 这个 IP 被判定成机器人。
# 旧代码把它和"没搜到"一起 `return []`，全链路只剩聚合行 `百度=0`，
# 读起来就是"百度没这本书"。于是"少了一半候选"这件事三天没人看见。

MU_HTML = ('<html><body>' + ('x' * 6000) +
           '<a mu="https://www.realbook.test/b/1">a</a>'
           '<a mu="https://www.realbook2.test/b/2">b</a></body></html>')


class _Resp:
    def __init__(self, text: str, status: int = 200, url: str = "https://www.baidu.com/s"):
        self.text = text
        self.status_code = status
        self.url = url


_old_client = W.get_client
_hits = {"n": 0}


def _fake_client(resp):
    def _get(url, **kw):
        _hits["n"] += 1
        return resp
    return type("C", (), {"get": staticmethod(_get)})()


W._baidu_blocked_until = 0.0
try:
    W.get_client = lambda: _fake_client(_Resp("百度安全验证", 200))
    _e = None
    try:
        W._baidu("三体")
    except Exception as exc:  # noqa: BLE001
        _e = exc
    ok("验证页 → 抛 EngineBlocked（不是返回空列表）",
       isinstance(_e, W.EngineBlocked), type(_e).__name__)
    ok("错误里点明是「被反爬」，不是「没结果」",
       _e is not None and "反爬" in str(_e), str(_e))
    ok("而且没被当成「正常返回 0 条」混过去",
       not isinstance(_e, type(None)))

    _before = _hits["n"]
    W.get_client = lambda: _fake_client(_Resp("百度安全验证", 200))
    _e2 = None
    try:
        W._baidu("三体")
    except Exception as exc:  # noqa: BLE001
        _e2 = exc
    ok("冷却期内**不再发请求**（越打越死，也免得刷满日志）",
       _hits["n"] == _before, f"{_before} → {_hits['n']}")
    ok("冷却期内的错误说清还剩几秒",
       _e2 is not None and "冷却中" in str(_e2), str(_e2))

    W._baidu_blocked_until = 0.0
    W.get_client = lambda: _fake_client(_Resp('<html>正常结果页</html>' + "y" * 5000, 200))
    _e3 = None
    try:
        W._baidu("三体")
    except Exception as exc:  # noqa: BLE001
        _e3 = exc
    ok("正常大页面但一条 mu 都没有 → 空列表，**不抛**（这才是「没这本书」）",
       _e3 is None, str(_e3))

    W._baidu_blocked_until = 0.0
    W.get_client = lambda: _fake_client(_Resp(MU_HTML, 200))
    got_b = W._baidu("三体")
    ok("正常页 → 抽出 2 条候选（判据不是恒抛）",
       [g["host"] for g in got_b] == ["www.realbook.test", "www.realbook2.test"],
       str([g["host"] for g in got_b]))
    ok("没被误判成「被反爬」（抛了就说明判据太松）", W._baidu_blocked_until == 0.0)

    # 反向②：**结果页里恰好出现验证字样**（用户的帖子标题写着「请输入验证码」）
    # 不许被当成被反爬。真验证页只有 2.6KB，正常结果页 40~100KB ——
    # 所以判据是「带指纹 **且** 体量明显不是结果页」，缺一不可。
    W._baidu_blocked_until = 0.0
    _big = ('<html><body>' + ('x' * 30000) +
            '<a mu="https://www.realbook3.test/b/3">请输入验证码</a></body></html>')
    W.get_client = lambda: _fake_client(_Resp(_big, 200))
    _e5 = None
    try:
        _got5 = W._baidu("三体")
    except Exception as exc:  # noqa: BLE001
        _e5, _got5 = exc, []
    ok("大结果页里夹着「请输入验证码」→ 不判被反爬（按体量区分验证页）",
       _e5 is None and [g["host"] for g in _got5] == ["www.realbook3.test"],
       str(_e5) if _e5 else str([g["host"] for g in _got5]))

    W._baidu_blocked_until = 0.0
    W.get_client = lambda: _fake_client(_Resp("x" * 3000, 200))
    _e4 = None
    try:
        W._baidu("三体")
    except Exception as exc:  # noqa: BLE001
        _e4 = exc
    ok("既不是结果页、也不带验证字样的小空壳 → 也抛，且写明字节数",
       isinstance(_e4, W.EngineBlocked) and "3000" in str(_e4), str(_e4))
finally:
    W.get_client = _old_client
    W._baidu_blocked_until = 0.0

print("=" * 62)
print(f"{'全部通过' if not fails else '有失败'}（{ok_n} 通过 / {bad_n} 失败）")
if fails:
    for f in fails:
        print("  ✗", f)
print("=" * 62)
sys.exit(1 if fails else 0)
