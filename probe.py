"""站点探测器 —— 学习爬虫的实用小工具。

用途：
1. 批量检测候选站点是否可达（状态码 / 响应大小 / 编码）
2. 自动识别搜索表单 action 与参数名
3. 探测结果可用来判断某个源值不值得写适配器

用法：
    python probe.py                # 探测内置候选列表
    python probe.py https://a.com https://b.com    # 探测指定站点
"""
from __future__ import annotations

import re
import sys
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 候选站点列表 —— 想加站点直接往这里加
CANDIDATES = [
    ("qbwx", "https://www.qbwx.cc"),
    ("biqudu", "https://www.biqudu.cc"),
    ("b5200", "https://www.b5200.net"),
    ("biquge365", "https://www.biquge365.net"),
    ("69yuedu", "https://www.69yuedu.net"),
    ("书海阁", "https://www.shuhaige.net"),
    ("书迷楼", "https://www.shumilou.co"),
    ("看书阁", "https://www.kanshuge.la"),
    ("顶点小说", "https://www.23qb.com"),
    ("飘天文学", "https://www.piaotia.com"),
    ("笔趣阁", "https://www.biquge.co"),
    ("全本小说网", "https://www.qb5200.com"),
]


def detect_encoding(resp: httpx.Response) -> str:
    """判断网页编码。"""
    ct = resp.headers.get("content-type", "").lower()
    m = re.search(r"charset=([\w-]+)", ct)
    if m:
        enc = m.group(1).lower()
        return "gb18030" if enc in ("gb2312", "gbk", "gb18030") else enc
    raw = resp.content[:3000]
    head = raw.decode("ascii", errors="ignore").lower()
    m = re.search(r'charset=["\']?([\w-]+)', head)
    if m:
        enc = m.group(1).lower()
        return "gb18030" if enc in ("gb2312", "gbk", "gb18030") else enc
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "gb18030"


def find_search_form(html: str, base: str) -> dict:
    """从页面里提取搜索表单信息。"""
    info = {"forms": [], "search_urls": []}
    for f in re.findall(r"<form[\s\S]{0,500}?</form>", html, re.I):
        action = re.search(r'action=["\']([^"\']*)', f, re.I)
        method = re.search(r'method=["\']([^"\']*)', f, re.I)
        inputs = re.findall(r'<input[^>]*name=["\']([^"\']+)["\'][^>]*', f, re.I)
        # 只要含搜索相关字段的
        if inputs and any(
            k in " ".join(inputs).lower() for k in ("search", "key", "word", "q", "kw")
        ):
            info["forms"].append({
                "action": action.group(1) if action else "",
                "method": (method.group(1) if method else "get").upper(),
                "inputs": inputs,
            })
    # JS 里常见的搜索 URL 模板
    for m in re.finditer(r'["\'](/[^"\']*(?:search|sou)[^"\']*)["\']', html, re.I):
        info["search_urls"].append(m.group(1))
    info["search_urls"] = list(dict.fromkeys(info["search_urls"]))[:5]
    return info


def probe(name: str, url: str) -> dict:
    """探测单个站点。"""
    result = {"name": name, "url": url, "status": None, "size": 0, "encoding": "", "error": "", "search": {}}
    try:
        with httpx.Client(
            trust_env=False, timeout=10, follow_redirects=True, verify=False,
            headers={"User-Agent": UA},
        ) as c:
            r = c.get(url)
            result["status"] = r.status_code
            result["size"] = len(r.content)
            enc = detect_encoding(r)
            result["encoding"] = enc
            if r.status_code == 200 and len(r.content) > 2000:
                html = r.content.decode(enc, errors="replace")
                result["search"] = find_search_form(html, url)
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {str(e)[:60]}"
    return result


def main():
    targets = CANDIDATES
    if len(sys.argv) > 1:
        targets = [(u, u) for u in sys.argv[1:]]

    print(f"开始探测 {len(targets)} 个站点...\n")
    alive = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(probe, n, u): (n, u) for n, u in targets}
        for fut in as_completed(futures):
            r = fut.result()
            flag = "✅" if r["status"] == 200 and r["size"] > 5000 else "❌"
            status = r["status"] if r["status"] else r["error"][:30]
            print(f'{flag} {r["name"]:14} {str(status):8} {r["size"]:>7}  {r["encoding"]}')
            if r["search"].get("forms") or r["search"].get("search_urls"):
                for f in r["search"]["forms"][:1]:
                    print(f'      表单: {f["method"]} {f["action"]} 字段={f["inputs"]}')
                for u in r["search"].get("search_urls", [])[:2]:
                    print(f'      链接: {u}')
            if r["status"] == 200 and r["size"] > 5000:
                alive.append(r)

    print(f"\n存活站点: {len(alive)} 个")
    out = "probe_result.json"
    with open(out, "w", encoding="utf-8") as fp:
        json.dump(alive, fp, ensure_ascii=False, indent=2)
    print(f"详细结果已写入 {out}")


if __name__ == "__main__":
    main()
