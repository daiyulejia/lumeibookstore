# -*- coding: utf-8 -*-
"""体检线上「可搜源」：这些模板的搜索页，真的能抽出书吗？

用法（**必须在能访问小说站的机器上跑**，本机 DNS 解析不了这些域名）：

    # 在服务器上跑（产物直接是线上那份来源库）
    scp tools/probe_pool_health.py ubuntu@<host>:~/noveldock/
    ssh ubuntu@<host> 'cd ~/noveldock && .venv/bin/python probe_pool_health.py 三体'

    # 或者本机（同网段/能解析时）
    .venv\\Scripts\\python.exe tools\\probe_pool_health.py 三体

为什么要它（2026-11-06 复盘）：
    `/api/registry` 的 `sites_searchable` 只回答「有模板且还算健康」，
    不回答「拿一个真实书名去问，它能不能给出书」。实测 29 个可搜源里
    对《三体》：15 个一条书链接都抽不出（jcxs / xizids / xuanhuanbiquge
    的搜索页是 3KB JS 空壳），另有 4 个抽出 20~144 条却**没有一条标题含
    关键词**（模板不带 kw，照常吐推荐位）。这个数字没人量，就没人在修。

关键点：**用产品自己的两段代码**，不另写一套判据 ——
    `sitelearn.build_url()`          拼 URL（参数名/编码/scheme 全照线上）
    `registry_source._extract_book_links()` + `kw_terms/_mentions`
                                      抽链接 + 判"这条跟关键词有关吗"
自己写正则数 `<a>` 会严重低估：每个站的详情页 URL 形状都不一样。

⚠ 只读：全程不写 `cache/registry.json`（不调 `note_search_result` /
  `note_site`），所以它不会给任何站投"不是搜索页"的票、也不会把模板判死。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import sitelearn  # noqa: E402
from app.sources import registry_source as RS  # noqa: E402
from app.utils import fetch_text  # noqa: E402

TOKEN = "xlSWxxI0HV_NZ8ISk6dl1Sl9"
REGISTRY_URL = "http://106.53.203.108:8000/api/registry?t=" + TOKEN


def _sites() -> list[dict]:
    """线上来源库里的「可搜源」（判据由服务端给，不在本地重写一遍）。"""
    with urllib.request.urlopen(REGISTRY_URL, timeout=40) as r:
        data = json.load(r)
    return [s for s in data["sites"] if s.get("searchable")]


def _url_of(site: dict, kw: str) -> str | None:
    tpl = (site.get("search_tpl") or "").strip()
    if not tpl:
        return None
    if (site.get("search_method") or "get").strip().lower() == "post":
        # POST 模板的关键词在请求体里，本探针只测 GET —— 跳过要说出来，
        # 别让"没测"和"测了 0 条"混成一个数字。
        return None
    return sitelearn.build_url(
        tpl, site["host"], kw,
        enc=(site.get("search_enc") or "utf-8"),
        scheme=(site.get("search_scheme") or "https"),
    )


def probe(site: dict, kw: str) -> tuple[str, str, int, int]:
    host = site["host"]
    url = _url_of(site, kw)
    if not url:
        return host, "POST/无模板", 0, 0
    try:
        with RS.fast_mode(retries=0, timeout=8):
            html, final = fetch_text(url, with_url=True)
    except Exception as e:  # noqa: BLE001
        return host, f"ERR {type(e).__name__}", 0, 0
    if not html:
        return host, "空响应", 0, 0
    raw = RS._extract_book_links(html, final or url)
    terms = RS.kw_terms(kw)
    kept = 0
    for title, _href in raw:
        if not title or RS._BAD_TITLE.match(title):
            continue
        if terms and not RS._mentions(terms, title):
            continue
        kept += 1
    return host, f"{len(html) // 1000}KB", len(raw), kept


def main() -> int:
    kw = (sys.argv[1] if len(sys.argv) > 1 else "三体").strip()
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
              "all_proxy", "ALL_PROXY"):
        os.environ.pop(k, None)

    sites = _sites()
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(lambda s: probe(s, kw), sites))
    rows.sort(key=lambda r: (r[3], r[2], r[0]))

    zero = [r for r in rows if r[2] == 0]
    no_kw = [r for r in rows if r[2] > 0 and r[3] == 0]
    print(f"关键词《{kw}》· 可搜源 {len(rows)} 个")
    print(f"  · 一条书链接都抽不出：{len(zero)} 个")
    print(f"  · 抽出若干、但没一条标题含关键词：{len(no_kw)} 个")
    print(f"  · 真给出「含关键词」的书：{len(rows) - len(zero) - len(no_kw)} 个\n")
    print(f"{'host':<28}{'页面':<18}{'抽出':>5}{'含关键词':>9}")
    for h, st, raw, kept in rows:
        print(f"{h:<28}{st:<18}{raw:>5}{kept:>9}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
