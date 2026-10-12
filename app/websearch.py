"""联网发现：本地来源搜不到时，自己出去把书页找回来。

为什么单开一个模块
------------------
来源库再大也是有限的。用户想看的书如果不在库里，之前只能干说「没找到」——
可这本书在百度/Bing 上明明一搜就有。缺的正是「自己出去找」这一步。

引擎怎么选的（都是实测出来的，不是拍脑袋）
------------------------------------------
- **Bing 为主**：结果直接给真实 URL（`<h2><a href="...">`），不用跟随跳转。
  实测搜《药鼎仙途》，第一条就是 `www.29zw.com/info_68516/`。
- **百度为辅**：它的 `mu="真实URL"` 属性能给出部分结果的真实地址。
  但 `www.baidu.com/link?url=` 那条跳转链会 **403**（反爬），所以千万别去跟。
- **只搜纯书名**：实测百度一旦带上「小说 / 全文阅读」这类后缀，
  反爬立刻触发（返回 1KB 空页）。所以后缀一个都不加。

出来的结果只是「书页 URL」，**不是**可用的来源配置 ——
把它变成能读能下载的东西是 `app/webfetch.py` 的事。
"""
from __future__ import annotations

import re
from typing import Callable, Optional
from urllib.parse import urlparse

from .utils import get_client

# 搜索结果里必然夹带的一堆「不是小说站」的域名。
# 不排掉的话，百度会塞百科 / 知道 / 备案 / 视频站进来。
_NOISE_HOSTS = (
    "baidu.", "bdstatic", "bcebos", "bing.com", "microsoft", "msn.com",
    "live.com", "w3.org", "google", "gstatic", "go.microsoft", "schemas.",
    "office.com", "windows.com", "miit.gov.cn", "mps.gov.cn", "gov.cn",
    "baike.", "zhidao", "zhihu.com", "douban", "bilibili", "iqiyi",
    "weibo", "alicdn", "sogou", "so.com", "360.cn", "sm.cn", "toutiao",
    "douyin", "kuaishou", "baijiahao", "csdn", "jianshu", "163.com",
    "sina.com", "sohu.com", "ifeng.com", "qq.com", "taobao", "jd.com",
    "apple.com", "wikimedia", "wikipedia", "youtube", "twitter", "facebook",
)

# Bing 的结果主链接在 <h2> 里；百度把真实地址放在 mu 属性上
_H2_LINK = re.compile(
    r'<h2[^>]*>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>([\s\S]{0,140}?)</a>', re.I)
_MU_LINK = re.compile(r'mu="(https?://[^"]+)"', re.I)


def _clean_title(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()[:80]


def _is_noise(host: str) -> bool:
    h = host.lower()
    return any(x in h for x in _NOISE_HOSTS)


def _add(out: list[dict], url: str, title: str, engine: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    if not host or _is_noise(host):
        return
    out.append({"url": url, "host": host, "title": title, "engine": engine})


def _bing(keyword: str) -> list[dict]:
    out: list[dict] = []
    r = get_client().get("https://cn.bing.com/search", params={"q": keyword},
                         headers={"Accept-Language": "zh-CN,zh;q=0.9"})
    if r.status_code != 200:
        return out
    for url, title in _H2_LINK.findall(r.text):
        _add(out, url, _clean_title(title), "bing")
    return out


def _baidu(keyword: str) -> list[dict]:
    out: list[dict] = []
    r = get_client().get("https://www.baidu.com/s", params={"wd": keyword},
                         headers={"Accept-Language": "zh-CN,zh;q=0.9"})
    # 被反爬时会返回一个 1KB 左右的空壳，别当成正常结果
    if r.status_code != 200 or len(r.text) < 5000:
        return out
    for url in _MU_LINK.findall(r.text):
        _add(out, url, "", "baidu")
    return out


def find_book_pages(
    keyword: str,
    *,
    limit: int = 14,
    per_host: int = 2,
    log: Optional[Callable[[str, str, bool], None]] = None,
) -> list[dict]:
    """搜书名 → 候选书页 URL。

    log(标题, 详情, 是否成功)：给流式接口推进度用，回调里抛异常会被吞掉。

    返回里每条是 {url, host, title, engine}，已按域名聚合去重 ——
    同一个站最多留 `per_host` 条，否则一个站能把整个列表刷满。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return []

    def say(title: str, detail: str = "", ok: bool = True) -> None:
        if not log:
            return
        try:
            log(title, detail, ok)
        except Exception:  # noqa: BLE001
            pass

    found: list[dict] = []
    for name, fn in (("Bing", _bing), ("百度", _baidu)):
        try:
            got = fn(keyword)
        except Exception as e:  # noqa: BLE001
            say(f"{name} 搜索失败", f"{type(e).__name__}: {str(e)[:50]}", False)
            continue
        say(f"{name} 搜到结果", f"{len(got)} 条")
        found.extend(got)

    by_host: dict[str, list[dict]] = {}
    for it in found:
        by_host.setdefault(it["host"], []).append(it)

    out: list[dict] = []
    for _host, items in by_host.items():
        out.extend(items[:per_host])
        if len(out) >= limit:
            break
    return out[:limit]
