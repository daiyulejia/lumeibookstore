"""批量体检小说站点 —— 找出「现在真的能打开」的那些。

用法：
    python tools/probe_pool.py                 # 体检内置候选池
    python tools/probe_pool.py domain.com ...  # 体检指定域名
    python tools/probe_pool.py --search 斗破苍穹 # 顺便测搜索接口

输出 JSON 到 cache/pool_report.json，按「可用 + 响应快」排序。

为什么要这个工具：
    笔趣阁系域名平均寿命只有几个月，改版/换域名/被墙是常态。
    「动态发现」不能靠静态名单，必须能自己跑一遍体检。
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.utils import get_client  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "cache" / "pool_report.json"

# 候选池：来自公开的站点推荐汇总（2026-10 收集）
CANDIDATES = [
    # —— 笔趣阁系 ——
    "biquge.tv", "www.bqg200.com", "www.bqgoo.cc", "www.beqege.cc", "www.bqg.cc",
    "www.biqg.cc", "www.xbiquge.la", "www.bqgui.cc", "www.b520.cc", "www.bqg128.com",
    "www.xbiquge.info", "www.biquge.info", "www.bqg222.com", "www.bqg333.com",
    "www.biqu5200.net", "www.xbqg5200.com", "m.bqg18.cc", "m.bqg234.com", "m.biqubao.com",
    "wap.18biquge.com", "www.biquge365.net", "www.biquge5200.cc", "www.bqwx.cc",
    "www.biquge.co", "www.bqg.tv", "www.biquge88.com", "www.biquges.com",
    # —— 其他网文站 ——
    "www.kunnu8.com", "www.kunnu.com", "www.69shu.com", "www.23us.la", "www.23us.so",
    "www.uukanshu.com", "www.xsw.tw", "m.xsw.tw", "www.wxsy.net", "www.shu69.net",
    "www.lewen6.com", "www.27xs.cc", "www.po5.net", "www.niuyueshu.com",
    "www.55xs.co", "www.book520.cc", "www.56shuku8.com", "www.10000txt.com",
    "www.soduzw.com", "www.tuishujun.com", "www.kuaishu5.com", "mobinovels.com",
    "www.deqixs.com", "www.mbtxtt.com", "www.yehanshu.com", "www.timotxt.com",
    "m.9ggd.com", "www.trxs.cc", "m.1qxs.com", "www.oldtimeswx.cc",
    "m.iquanben.net", "www.sudugu.com", "www.myhaitang.cc", "www.guowx.com",
    "www.xbookben.org", "www.booksos.net", "m.soushuwang.cc", "m.ok120.net",
    "www.yuedsk.com", "m.shuyuan6.com", "m.zydu3.com", "m.mhtxss.com",
    "m.qbiqus.com", "m.xuewens.com", "m.tihuashu.com", "m.lanwen.org",
    "m.seyours.com", "wap.qizi01.com", "m.iwurexs.net", "wap.vcudu.com",
    "www.ibus2333.com", "wap.aixs.info",
    # —— 出版/严肃向 ——
    "www.wyshu.com", "www.shupeng.com", "www.txtnovel.vip",
    # —— 聚合搜索 ——
    "soshu.vip", "www.owlook.com.cn", "www.sobooks.net", "www.qb5.tw",
]

# 常见「一搜就有结果」的路径模板
SEARCH_PATTERNS = [
    "/search.php?keyword={kw}",
    "/search.php?q={kw}",
    "/search.html?s={kw}",
    "/search.html?q={kw}",
    "/search.html?keyword={kw}",
    "/modules/article/search.php?searchkey={kw}",
    "/e/search/?searchget=1&keyboard={kw}",
    "/search/?searchkey={kw}",
    "/search?keyword={kw}",
    "/so.php?q={kw}",
    "/s?q={kw}",
    "/search/{kw}/",
]

BROWSER = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 出现这些就说明不是正常小说站
BAD_MARK = re.compile(
    r"域名出售|域名转让|domain (is )?for sale|服务器错误|该网站正在建设|"
    r"本站已停止|403 Forbidden|404 Not Found|nginx|Apache Tomcat",
    re.I,
)
# 出现这些说明页面里有可点的书
BOOK_MARK = re.compile(r"最新章节|章节目录|txt下载|全文阅读|加入书架|作者：|小说简介")


def norm_url(d: str) -> str:
    return d if d.startswith("http") else "https://" + d


def probe_one(domain: str, keyword: str = "") -> dict:
    url = norm_url(domain)
    out: dict = {"domain": domain, "url": url, "ok": False, "code": None,
                 "ms": None, "size": 0, "title": "", "search_ok": None,
                 "search_url": None, "note": ""}
    t0 = time.time()
    try:
        with get_client().stream("GET", url, headers=BROWSER, timeout=12.0) as r:
            out["code"] = r.status_code
            body = b""
            for chunk in r.iter_bytes():
                body += chunk
                if len(body) > 200_000:
                    break
        out["ms"] = int((time.time() - t0) * 1000)
        out["size"] = len(body)
        txt = body.decode("utf-8", errors="replace")
        if not txt.strip():
            txt = body.decode("gb18030", errors="replace")
        m = re.search(r"<title>([^<]{0,80})", txt, re.I)
        out["title"] = (m.group(1).strip() if m else "")
        if r.status_code != 200:
            out["note"] = f"HTTP {r.status_code}"
            return out
        if BAD_MARK.search(txt[:4000]):
            out["note"] = "疑似停放页/错误页"
            return out
        out["ok"] = True
        # 找搜索接口
        if keyword:
            out.update(_try_search(url, keyword, txt))
    except Exception as e:  # noqa: BLE001
        out["ms"] = int((time.time() - t0) * 1000)
        out["note"] = _brief(e)
    return out


def _try_search(base: str, keyword: str, home_html: str) -> dict:
    """先看首页有没有搜索表单，没有就试常见路径。"""
    kw_u = quote(keyword, encoding="utf-8")
    kw_g = quote(keyword, encoding="gbk")
    cands: list[str] = []

    # 首页表单：<form action="..." ...> 里有 name="xxx"
    for m in re.finditer(r"<form[^>]+action=[\"']?([^\"'\s>]+)[\"']?[^>]*>([\s\S]{0,600}?)</form>",
                         home_html, re.I):
        action, inner = m.group(1), m.group(2)
        if re.search(r"search|so|query", action, re.I):
            field = re.search(r'name=["\']?([\w\[\]]+)', inner)
            if field:
                sep = "&" if "?" in action else "?"
                cands.append(f"{urljoin(base, action)}{sep}{field.group(1)}={kw_u}")
    gem = re.search(r"<form[^>]+action=[\"']?([^\"'\s>]+)[\"']?[^>]*>(?=[\s\S]{0,300}?"
                    r"<input[^>]+name=[\"']?searchkey)", home_html, re.I)

    for p in SEARCH_PATTERNS:
        cands.append(base.rstrip("/") + p.format(kw=kw_u))
    if kw_g != kw_u:
        cands.append(base.rstrip("/") + "/modules/article/search.php?searchkey=" + kw_g)

    seen = set()
    for u in cands:
        if u in seen:
            continue
        seen.add(u)
        try:
            r = get_client().get(u, headers=BROWSER, timeout=12.0)
            if r.status_code != 200:
                continue
            txt = r.text
            if len(txt) < 800:
                continue
            # 关键：结果页必须**真的含有关键词**。
            # 少了这道检查，/search.html?s=xx 这种「参数不生效、直接返回首页」
            # 的站会被判成「搜索可用」—— 首页当然有 3 个以上链接，
            # 也当然有「最新章节」这些字，于是假阳性率极高。
            if keyword[:2] not in txt:
                continue
            # 再排除「跳回首页」这种假命中：搜索结果页的标题里通常带关键词
            if not re.search(r"<title>[^<]{0,60}" + re.escape(keyword[:2]), txt, re.I):
                continue
            books = re.findall(r'href=["\'](/?[\w\-/]*\d+[\w\-/]*\.?html?|/[a-z]+/\d+/?)[\"\']',
                               txt, re.I)
            if len(books) >= 3 and BOOK_MARK.search(txt):
                return {"search_ok": True, "search_url": u,
                        "search_hits": len(books)}
        except Exception:  # noqa: BLE001
            continue
    return {"search_ok": False, "search_url": None}


def _brief(e: Exception) -> str:
    s = str(e)
    if "10054" in s or "ConnectionReset" in s or "RemoteProtocol" in s:
        return "连接被重置（可能被墙/反爬）"
    if "10061" in s or "ConnectError" in s or "refused" in s.lower():
        return "连接被拒"
    if "timeout" in s.lower() or "timed out" in s.lower():
        return "超时"
    if "Name or service" in s or "getaddrinfo" in s or "nodename" in s:
        return "域名不存在"
    if "SSL" in s or "certificate" in s.lower():
        return "证书错误"
    return s[:60]


def main() -> None:
    argv = sys.argv[1:]
    keyword = ""
    # 注意：--search 后面那个值是**关键词**，不能留在 args 里当域名。
    # （之前就是这里把「斗破苍穹」当成一个域名去体检了，结果只搜了 1 个站）
    skip: set[int] = set()
    if "--search" in argv:
        i = argv.index("--search")
        if i + 1 < len(argv):
            keyword = argv[i + 1]
            skip.add(i + 1)
        skip.add(i)
    args = [a for j, a in enumerate(argv) if j not in skip and not a.startswith("--")]
    pool = args or CANDIDATES

    print(f"体检 {len(pool)} 个站点" + (f"，顺带测试搜索「{keyword}」" if keyword else "") + " …\n")
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=16) as pool_ex:
        futs = {pool_ex.submit(probe_one, d, keyword): d for d in pool}
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            results.append(r)
            flag = "OK  " if r["ok"] else "FAIL"
            extra = ""
            if r["ok"] and r.get("search_ok"):
                extra = "  搜索✓"
            elif r["ok"] and keyword:
                extra = "  搜索✗"
            print(f"[{i:3d}/{len(pool)}] {flag} {r['domain']:<28} "
                  f"{str(r['code'] or ''):>4} {str(r['ms'] or ''):>5}ms "
                  f"{r['size']:>7}B  {r['title'][:22]:<22}{extra}"
                  + (f"  ({r['note']})" if r["note"] else ""))

    alive = [r for r in results if r["ok"]]
    alive.sort(key=lambda r: (not r.get("search_ok"), r["ms"] or 9999))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"ts": time.time(), "keyword": keyword, "all": results,
                               "alive": alive}, ensure_ascii=False, indent=1),
                   encoding="utf-8")

    print(f"\n{'='*70}")
    print(f"存活 {len(alive)} / {len(results)}")
    if keyword:
        sr = [r for r in alive if r.get("search_ok")]
        print(f"搜索可用 {len(sr)} 个：")
        for r in sr:
            print(f"   {r['domain']:<28} {r['search_url']}")
    print(f"\n报告已写入 {OUT}")


if __name__ == "__main__":
    main()
