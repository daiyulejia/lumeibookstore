# -*- coding: utf-8 -*-
"""「这次抓取失败该记谁的账」+「越线之后能不能回来」—— 纯逻辑，不联网。

为什么单独立一套（2026-11-17 复盘）
------------------------------------
两件事今天同时被证实是**产品自己的 bug**，而且都不报错、不崩、日志一片安静：

① **我方限流被记成「站点挂了」**
   `fetch_text` 在同域限流冷却期内**一个请求都不发**（保护我们别被墙），
   抛 `errors.LocalCooldown`。这是"我们自己决定不做这个动作"。
   可下面这两行曾经在 **6 个地方**各写了一遍：

       slow = classify_fetch_error(e) == "slow"
       why  = FAIL_SLOW if slow else FAIL_DOWN

   `LocalCooldown` 不属于 `slow`（它是 RuntimeError，不是 httpx 超时），
   于是被归到 `FAIL_DOWN`「站点网络层失败」——**把自己的保护记成对方的罪**。
   11-16 只给引擎修了这条（`source.skip`），那 6 处一处没动。
   所以判据必须钉住："判据只有一处，6 个入口都要按它走"。

② **越过健康死亡线就再也回不来**
   `is_healthy` 只有死亡线（`down >= 3 and down > ok*2`），没有复活路径：
   一旦越线，站同时被 `searchable_sites()`（不再扇出）和
   `discovery._verify`（跳过已失效站点）排除 —— **永远拿不到下一次成功**去记
   `ok`，计数就冻结在越线那一刻。冻结的取值必然是 `down == 2*ok + 1`：
   实测库里 4 个有模板的站 **4/4** 全停在这个值上（6/13、7/15、60/121、386/773），
   四个数量级完全不同的站分子分母都恰好落在这个式子上 —— 这是"越线即冻结"
   的指纹，不是巧合。后果是「可搜源」只会单向缩水，缩到 0 之后没有任何自动化
   能把它找回来（本地库现在就是 `sites_searchable=0`）。

反向判据（防止"修过头"）：
  · 真挂了（ConnectError）仍要记账，不许因为加了冷却判断就把脏水一起倒了；
  · 健康站 / 没学过模板的站 / 被判为影视站的站**不许**进试用通道；
  · 试用站不许算进 `sites_searchable`（那会让"资产"这个数字重新虚高）。

用法：python tools/test_site_fault.py
"""
from __future__ import annotations

import logging
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 导入期就把库文件指到临时目录：本文件会大量 `note_site`，不隔离会写生产库。
_TMPDIR = pathlib.Path(tempfile.mkdtemp(prefix="novel-sitefault-test-"))
os.environ["NOVEL_REGISTRY"] = str(_TMPDIR / "registry.json")

import httpx                                        # noqa: E402

from app import registry as R                        # noqa: E402
from app import discovery as D                       # noqa: E402
from app.errors import LocalCooldown                 # noqa: E402
from app.sources import registry_source as RS        # noqa: E402

OK = 0
BAD = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global OK, BAD
    if cond:
        OK += 1
        print(f"  ✓ {name}")
    else:
        BAD += 1
        print(f"  ✗ {name}  {extra}")


class _Cap(logging.Handler):
    """抓日志行，用来断言"有没有点名"。"""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, rec: logging.LogRecord) -> None:      # noqa: D102
        # getMessage() 已经把 args 填进模板了，**不能再 % 一次**（会 TypeError）。
        self.lines.append(rec.getMessage())


_cap = _Cap()


def _lines() -> list[str]:
    return [x for x in _cap.lines]

def _make_site(host: str, *, ok_n: int, down_n: int, tpl: str = "/s?q={kw}",
               **extra) -> None:
    """造一个"刚好在某个计数状态"的站 —— 数字全部自己造，不依赖环境。"""
    R.note_site(host, ok=True, search_tpl=tpl, **extra)
    for _ in range(max(0, ok_n - 1)):
        R.note_site(host, ok=True)
    for _ in range(down_n):
        R.note_site(host, ok=False, why=R.FAIL_DOWN)


def main() -> int:
    # 挂在 `novel` 上，不要只挂 `novel.registry`：本文件还要断言
    # `novel.registry_source` 那侧的留痕（⑦ 组）。
    lg = logging.getLogger("novel")
    lg.setLevel(logging.INFO)
    lg.addHandler(_cap)

    # ------------------------------------------------------------------
    print("\n—— ① 判据只有一处：什么该记「站的账」 ——")
    check("本地限流冷却 → **不记账**（我们一个请求都没发）",
          R.site_fault_why(LocalCooldown(37.0, "a.com")) is None,
          "这是我们自己的保护，记成站的账就会把好站往死亡线上推")
    check("读超时 → slow（我们等得不够）",
          R.site_fault_why(httpx.ReadTimeout("t")) == R.FAIL_SLOW)
    check("连接不上 → down（这才是真的像站挂了）",
          R.site_fault_why(httpx.ConnectError("x")) == R.FAIL_DOWN)
    check("被 fetch_text 包了一层的读超时仍然识别出 cause",
          R.site_fault_why(_wrapped(httpx.ReadTimeout("t"))) == R.FAIL_SLOW)
    check("被包了一层的连接错误仍然是 down",
          R.site_fault_why(_wrapped(httpx.ConnectError("x"))) == R.FAIL_DOWN)

    # ------------------------------------------------------------------
    print("\n—— ② 记账：冷却只留痕，不涨任何计数 ——")
    h = "cool.example"
    R.note_site(h, ok=True, search_tpl="/s?q={kw}")
    before = dict(R.known_site(h))
    _cap.lines.clear()
    booked = R.note_fetch_fail(h, LocalCooldown(12.0, h))
    after = R.known_site(h)
    check("note_fetch_fail 返回 False（= 没记站的账）", booked is False)
    check("fail 没涨", int(after.get("fail", 0)) == int(before.get("fail", 0)),
          f"{before.get('fail')} → {after.get('fail')}")
    check("fail_down 没涨（关键：它才是判死的那个分子）",
          int(after.get("fail_down", 0)) == int(before.get("fail_down", 0)))
    check("留了痕：日志里有 site.skip 并点名域名",
          any("site.skip" in x and h in x for x in _lines()), str(_lines()[-3:]))

    h2 = "realdown.example"
    R.note_site(h2, ok=True, search_tpl="/s?q={kw}")
    _cap.lines.clear()
    R.note_fetch_fail(h2, httpx.ConnectError("x"))
    s2 = R.known_site(h2)
    check("反过来：真连不上**必须**涨 fail_down（别把脏水一起倒了）",
          int(s2.get("fail_down", 0)) == 1, str(s2))

    h3 = "slow.example"
    R.note_site(h3, ok=True, search_tpl="/s?q={kw}")
    R.note_fetch_fail(h3, httpx.ReadTimeout("t"))
    s3 = R.known_site(h3)
    check("超时记 fail_slow，且 fail_down 保持 0",
          int(s3.get("fail_slow", 0)) == 1 and int(s3.get("fail_down", 0)) == 0,
          str(s3))

    # ------------------------------------------------------------------
    print("\n—— ③ 越线：降级要点名，且不许每次都喊 ——")
    hd = "demote.example"
    _cap.lines.clear()
    # ⚠ 数字要**刚好越线**：down > 2*ok。2/4 是 4 > 4 不成立（还是健康），
    #   踩过一次 —— 断言失败时先怀疑自己的夹具，别急着改产品。
    _make_site(hd, ok_n=2, down_n=5)
    demotes = [x for x in _lines() if "site.demote" in x]
    check("越过死亡线时打了 site.demote 并点名域名",
          len(demotes) == 1 and hd in demotes[0], str(_cap.lines[-5:]))
    check("先确认它确实不健康了（不是恒真）",
          not R.is_healthy(R.known_site(hd)))
    _cap.lines.clear()
    R.note_site(hd, ok=False, why=R.FAIL_DOWN)
    check("已经降级的站再失败一次**不再喊**（否则日志会被刷满）",
          not [x for x in _lines() if "site.demote" in x])

    # ------------------------------------------------------------------
    print("\n—— ④ 越线即冻结的指纹：down == 2*ok + 1 ——")
    hf = "frozen.example"
    _make_site(hf, ok_n=6, down_n=13)
    s = R.known_site(hf)
    check("ok=6/down=13 判为不健康（13 > 2*6）", not R.is_healthy(s))
    check("它**不再**出现在可搜源里（这就是冻结的开始）",
          hf not in R.searchable_sites())
    check("而且不会算进 stats 的可搜源数",
          all(k != hf for k in R.searchable_sites()))

    # ------------------------------------------------------------------
    print("\n—— ⑤ 试用通道：越线的站能靠一次成功回来 ——")
    ht = "probation.example"
    _make_site(ht, ok_n=6, down_n=13)
    picked = R.probation_sites()
    check("被挑进试用（否则这个站永远拿不到下一次 ok）", ht in picked, str(list(picked)))
    check("试用站**不算进**可搜源（资产数字不许重新虚高）",
          ht not in R.searchable_sites())
    check("同一个站冷却期内不重复挑（限额才有意义）",
          ht not in R.probation_sites())
    R.note_site(ht, ok=True)
    check("成功一次 → ok+1 让 down <= 2*ok 重新成立 → 立刻恢复健康",
          R.is_healthy(R.known_site(ht)), str(R.known_site(ht)))
    check("恢复后重新算可搜源资产", ht in R.searchable_sites())

    print("\n—— ⑤b 试用通道的反向判据：谁不许进去 ——")
    hok = "healthy2.example"
    _make_site(hok, ok_n=5, down_n=0)
    check("健康的站不占试用名额", hok not in R.probation_sites())
    hnt = "notpl.example"
    R.note_site(hnt, ok=True)
    for _ in range(6):
        R.note_site(hnt, ok=False, why=R.FAIL_DOWN)
    check("没学过搜索模板的站不进试用（它压根没法「站内搜」）",
          hnt not in R.probation_sites())
    hvid = "video.example"
    _make_site(hvid, ok_n=2, down_n=5, video_blocked=True)
    check("被判为影视站的**不许**借试用通道复活",
          hvid not in R.probation_sites())

    print("\n—— ⑤c 试用限额：一次搜索最多带 PROBATION_MAX 个，且先试成功多的 ——")
    many = [f"many{i}.example" for i in range(4)]
    for i, hh in enumerate(many):
        # 前两个成功 9 次（更可能是被一次坏天气误杀的），后两个只成功 3 次。
        _make_site(hh, ok_n=(9 if i < 2 else 3), down_n=(19 if i < 2 else 7))
    got = R.probation_sites()
    check(f"最多只挑 {R.PROBATION_MAX} 个", len(got) == R.PROBATION_MAX, str(list(got)))
    check("挑的是成功次数多的（更可能是被一次坏天气误杀）",
          set(got) == set(many[:R.PROBATION_MAX]), str(list(got)))

    # ------------------------------------------------------------------
    print("\n—— ⑥ 接线：可搜源为 0 时，试用站要让扇出**跑起来** ——")
    # 造一个"可搜源全灭、只剩试用站"的局面（本地库现在就是这个状态）。
    for hh in list(R.sites()):
        s = R.known_site(hh)
        if R.is_searchable(s):
            R.note_site(hh, ok=False, why=R.FAIL_DOWN)
            R.note_site(hh, ok=False, why=R.FAIL_DOWN)
            while R.is_healthy(R.known_site(hh)):
                R.note_site(hh, ok=False, why=R.FAIL_DOWN)
    print(f"     现在可搜源 {len(R.searchable_sites())} 个、"
          f"试用候选 {len(R.probation_sites())} 个")
    asked: list[str] = []

    def fake_fetch(url, **kw):
        asked.append(url)
        return ("<html><body>没有找到</body></html>", url)

    real_fetch = RS.fetch_text
    RS.fetch_text = fake_fetch
    try:
        RS.RegistrySource().search("喵")
    finally:
        RS.fetch_text = real_fetch
    check("可搜源为 0 时仍然发起了请求（原来这里直接 return []）",
          bool(asked), f"asked={asked}")

    # ------------------------------------------------------------------
    print("\n—— ⑦ 冷却不许喂熔断器（同 source.skip 的道理，这一层在来源库） ——")
    hc = "coolfeed.example"
    R.note_site(hc, ok=True, search_tpl="/s?q={kw}")
    R.flush()

    def boom(url, *a, **k):
        raise LocalCooldown(88.0, "coolfeed.example")

    errs: list[str] = []
    real_note_error = RS.RegistrySource.note_error
    RS.fetch_text = boom
    RS.RegistrySource.note_error = lambda self, msg: errs.append(str(msg))
    raised: BaseException | None = None
    try:
        out = RS.RegistrySource()._search_one(
            hc, {"search_tpl": "/s?q={kw}"}, "喵")
    except BaseException as e:      # noqa: BLE001
        # ⚠ 必须自己接住：让它崩出去的话，反证工具只看到"退出码非 0、
        #   一行 ✗ 都没有"，分不清是"判据没牙"还是"测试崩了"。
        out, raised = [], e
    finally:
        RS.fetch_text = real_fetch
        RS.RegistrySource.note_error = real_note_error
    check("冷却时不该抛异常（抛了就会被记成源失败）", raised is None, repr(raised))
    check("冷却时返回空结果（不是异常）", out == [], str(out))
    check("没有把冷却上报给熔断器（否则冷却 120s 会熔断好几分钟）",
          errs == [], str(errs))
    sc = R.known_site(hc)
    check("也没有顺手涨 fail_down / 记「搜不出」",
          int(sc.get("fail_down", 0)) == 0
          and int(sc.get("fail", 0)) == 0, str(sc))
    check("留了痕：日志点名了这个站被冷却挡住",
          any("限流冷却挡住" in x and hc in x for x in _lines()),
          str(_lines()[-3:]))

    # ------------------------------------------------------------------
    print("\n—— ⑧ 两个真实入口：核实候选 / 坏源排查 ——")
    # 这一组测的是**调用点**，不是 helper。6 个入口都改成调 helper 才算修好；
    # 只测 helper 的话，任何一个入口写回老写法都测不出来。
    hv = "verify.example"
    R.note_site(hv, ok=True, search_tpl="/s?q={kw}")
    cand = {"url": f"https://{hv}/book/1", "host": hv}
    real_page_of = D.page_of

    def _boom_factory(exc):
        def _f(url, *a, **kw):
            raise exc
        return _f

    D.page_of = _boom_factory(LocalCooldown(60.0, hv))
    try:
        got = D._verify(cand, "喵", {})
        swept = D._check_book(cand["url"], {"host": hv, "title": "喵"})
    finally:
        D.page_of = real_page_of
    sv = R.known_site(hv)
    check("核实阶段遇到我方冷却 → 返回 None（不记站的账）", got is None)
    check("核实阶段**没有**涨 fail_down",
          int(sv.get("fail_down", 0)) == 0, str(sv))
    check("它还在可搜源里（一次都没真打，凭什么判死）",
          R.is_searchable(sv), str(sv))
    check("坏源排查遇到冷却 → 连这本书都不记（否则好书会被体检删掉）",
          swept is False and cand["url"] not in R.books(), str(list(R.books())[-3:]))

    D.page_of = _boom_factory(httpx.ConnectError("x"))
    try:
        D._verify(cand, "喵", {})
    finally:
        D.page_of = real_page_of
    check("反过来：真连不上照样记 fail_down（别把脏水一起倒了）",
          int(R.known_site(hv).get("fail_down", 0)) == 1,
          str(R.known_site(hv)))

    # ------------------------------------------------------------------
    print("\n—— ⑨ 防复发：判据只许有一处（新增入口不许再手写那两行） ——")
    # 11-16 的教训已经写进 MEMORY：**闸门装在一个入口上，就等于没装**。
    # 今天发现的正是同一件事的第七个入口 —— 靠"记得改"是不行的，得有闸。
    # 用 AST 扫调用点（注释和 docstring 里提到的不算，天然排除），
    # 断言 `classify_fetch_error(` 的调用**只出现在 registry.site_fault_why**。
    sites_used = _classify_call_sites()
    files = sorted({x.split(":")[0] for x in sites_used})
    check("判据只有一处（唯一调用点在 app/registry.py）",
          files == ["app/registry.py"], f"实际 {files} {sites_used}")
    # ⚠ 这条是防"扫描器自己坏了"：扫描器返回空列表时上一条**恒真**。
    check("扫描器确实扫到了那一次调用（否则上一条是空转）",
          len(sites_used) == 1, str(sites_used))

    # ------------------------------------------------------------------
    print(f"\n{'=' * 60}\n通过 {OK} / 失败 {BAD}\n")
    return 0 if BAD == 0 else 1


def _classify_call_sites() -> list[str]:
    """扫出 `classify_fetch_error(` 的**真实调用点**（`文件:行`）。

    用 AST 而不是 grep：grep 会把注释和 docstring 里的示例也数进来
    （本轮新写的注释里就有三处提到它），那样这条判据永远是红的。
    """
    import ast

    out: list[str] = []
    for p in sorted((ROOT / "app").rglob("*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:          # 语法错留给别的测试报，这里不抢戏
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "classify_fetch_error"):
                out.append(f"{p.relative_to(ROOT).as_posix()}:{node.lineno}")
    return out


def _wrapped(cause: BaseException) -> RuntimeError:
    """照 `fetch_text` 的形状包一层：`raise RuntimeError(...) from last_err`。"""
    try:
        raise RuntimeError("抓取失败: https://x/") from cause
    except RuntimeError as e:
        return e


if __name__ == "__main__":
    sys.exit(main())
