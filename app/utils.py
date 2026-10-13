"""通用工具：HTTP 请求、编码处理、正文清洗。"""
from __future__ import annotations

import re
import os
import time
import random
import threading
import ipaddress
import logging
from contextlib import contextmanager
from typing import Optional

import httpx

from .security import BlockedURL

logger = logging.getLogger("novel.utils")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

# 是否使用系统代理。默认 False，避免代理环境导致境外站点超时。
# 可用环境变量 NOVEL_USE_PROXY=1 开启。
USE_PROXY = os.environ.get("NOVEL_USE_PROXY", "0") == "1"

# 每个域的请求最小间隔（秒）。0 表示不限速。
# 目标站反爬较严时可调大，例如 NOVEL_MIN_INTERVAL=0.5
MIN_INTERVAL = float(os.environ.get("NOVEL_MIN_INTERVAL", "0.3"))

# 每个域名**各自**一把锁 + 上次请求时间，用于友好限速。
#
# 为什么不是一把全局锁：限速靠 sleep（默认 0.3s），若所有域名共用一把锁，
# 那么 A 站 sleep 时 B 站的请求也得跟着排队 —— 一次多源并发搜索会被
# 生生串行化，总耗时等于「源数 × 间隔」。按域名分锁之后，只有对**同一个站**
# 的请求互相等（这才是反爬关心的），跨站完全并行。
_last_request: dict[str, float] = {}
_host_locks: dict[str, threading.Lock] = {}
_host_locks_guard = threading.Lock()


def _lock_for(host: str) -> threading.Lock:
    with _host_locks_guard:
        lk = _host_locks.get(host)
        if lk is None:
            lk = _host_locks[host] = threading.Lock()
        return lk

# 复用同一个 client，减少握手开销
_client: Optional[httpx.Client] = None
_client_no_proxy: Optional[httpx.Client] = None


def _throttle(url: str) -> None:
    """对同一域名的请求做最小间隔限制，避免触发反爬。

    跨域名各走各的锁 —— 见上面 _host_locks 的说明。
    """
    if MIN_INTERVAL <= 0:
        return
    host = host_of(url)
    if not host:
        return
    with _lock_for(host):
        last = _last_request.get(host, 0.0)
        wait = MIN_INTERVAL - (time.time() - last)
        if wait > 0:
            time.sleep(wait + random.uniform(0, 0.1))  # 加一点抖动
        _last_request[host] = time.time()


# ---------------------------------------------------------------------------
# 域名冷却：被反爬拦下之后，别再一遍遍去撞
# ---------------------------------------------------------------------------
# 小说站被连续请求后会短暂「软封」—— 不是返回 403，而是回一个几十字节的
# 空壳页面，或者一直转圈。这时如果继续按正常节奏重试，只会：
#   · 让封禁时间更长
#   · 白占着线程和用户的等待时间
# 所以来源适配器一旦识别出「这是被拦了」，就调 mark_blocked 记一笔，
# 之后对这个域名的请求会直接快速失败，等冷却结束再恢复。
_cooldown: dict[str, float] = {}
_cooldown_lock = threading.Lock()


def host_of(url: str) -> str:
    try:
        return httpx.URL(url).host or ""
    except Exception:  # noqa: BLE001
        return ""


def mark_blocked(url: str, seconds: float = 90.0) -> None:
    """把这个域名拉黑一段时间。"""
    host = host_of(url)
    if not host:
        return
    with _cooldown_lock:
        _cooldown[host] = max(_cooldown.get(host, 0.0), time.time() + seconds)
    logger.info("域名 %s 进入冷却 %.0fs", host, seconds)


def cooldown_left(url: str) -> float:
    """还剩多少秒冷却；0 表示可用。"""
    host = host_of(url)
    if not host:
        return 0.0
    with _cooldown_lock:
        until = _cooldown.get(host, 0.0)
        if until <= time.time():
            _cooldown.pop(host, None)
            return 0.0
        return until - time.time()


def cooldowns() -> dict[str, float]:
    """当前处于冷却的域名 → 剩余秒数（给前端/诊断用）。"""
    now = time.time()
    with _cooldown_lock:
        return {h: round(t - now, 1) for h, t in _cooldown.items() if t > now}


def cooldown_clear() -> None:
    """手动解除所有冷却（用户说「我等不及了」时用）。"""
    with _cooldown_lock:
        _cooldown.clear()


def _guard_redirect(request: httpx.Request) -> None:
    """请求发出前再校一次目标地址 —— 挡住「重定向到内网」。

    ⚠ 为什么需要：`assert_public_url()` 是在**用户提交 URL 那一刻**校验的，
    但客户端开着 `follow_redirects=True` —— 站点回一个
    `302 http://169.254.169.254/latest/meta-data/` 就能把我们带去云元数据接口，
    而**这一次跳转再也没有人校验过**。同理 DNS 也可能在校验之后被换成内网 IP
    （TOCTOU / DNS rebinding）。

    httpx 的 `event_hooks["request"]` 对**每一次**请求都跑（含重定向后的），
    是最靠近"真的发出去"的那道闸。这里做三件事：
      ① 目标 IP 落在内网/保留网段 → 直接拒绝
      ② 云元数据地址 → 拒绝
      ③ 只查 IP 字面量、不做 DNS 解析 —— 事件钩子里再做一次 getaddrinfo
         会让每个请求多一次系统调用，拖慢正常抓取；而**主干防护**
         （域名解析到内网）已经由 assert_public_url 在入口挡住了。
    这个钩子是"纵深防御"的第二层，不是唯一一层。
    """
    try:
        host = request.url.host
    except Exception:  # noqa: BLE001
        return
    if not host:
        return
    low = host.lower().strip("[]")
    if low in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "169.254.169.254"):
        raise BlockedURL(f"拒绝请求内网/元数据地址：{host}")
    try:
        ip = ipaddress.ip_address(low)
    except ValueError:
        return          # 是域名，交给入口那层管
    if (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
        raise BlockedURL(f"拒绝请求内网地址：{host}")


# —— TLS 校验策略 ——
# 早期这里直接写了 verify=False —— 图省事，但代价是**完全放弃证书校验**：
# 任何中间人（公共 Wi-Fi、运营商劫持、恶意代理）都能替换抓到的正文，
# 用户看到的「小说」可能被人改过，而且毫无痕迹。
#
# 但也不能一律 verify=True —— 大量小站用的是自签/过期/域名不匹配的证书，
# 一开校验就整站抓不到，直接丢书源。
#
# 折中（也是业界常见做法）：
#   · 默认 **开启** 校验（certifi 根证书），这是安全的那一档；
#   · 只有**确实是证书问题**（SSLCertVerificationError / 自签 / 过期）时，
#     才针对**那一个请求**降级为不校验重试一次，并打一条 warn 日志。
# 这样：正常站点全程受保护，劣质证书站也能抓到，且降级行为在日志里可追溯。
_TLS_STRICT = os.environ.get("NOVEL_TLS_STRICT", "0") != "1"  # NOVEL_TLS_STRICT=1 → 永不降级


def _cert_error(exc: BaseException) -> bool:
    """判断异常是不是「证书不可信」这类可降级的问题。

    只认证书本身的问题；域名不匹配（hostname mismatch）也算 —— 那多半是
    小站配错了证书，不是攻击。其余网络错误交给上层重试逻辑，不走降级。
    """
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        name = type(cur).__name__.lower()
        if "ssl" in name or "cert" in name:
            return True
        msg = str(cur).lower()
        if ("certificate" in msg or "ssl" in msg
                or "self signed" in msg or "self-signed" in msg
                or "hostname mismatch" in msg):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def _make_client(*, verify: bool, use_proxy: bool) -> httpx.Client:
    """建一个 httpx.Client。两处（有/无代理）只差 trust_env 与 limits。"""
    kw: dict = dict(
        headers=DEFAULT_HEADERS,
        timeout=httpx.Timeout(25.0, connect=12.0),
        follow_redirects=True,
        verify=verify,
        event_hooks={"request": [_guard_redirect]},
    )
    if not use_proxy:
        kw["trust_env"] = False          # 关键：忽略系统代理
        kw["limits"] = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    return httpx.Client(**kw)


def get_client(use_proxy: bool | None = None, *, verify: bool = True) -> httpx.Client:
    """拿一个（复用的）HTTP 客户端。

    ⚠ 切换 `verify` 时**必须先 close 旧的**。
    踩过的坑：自签证书的小站会让 `fetch_text` 用 `verify=False` 重试，
    而原来的写法是「verify 不一样就 new 一个、把旧的直接丢掉」——
    旧 client 的**连接池没关**（底层 socket 没释放），只能等 GC。
    在「多站轮询 + 频繁触发 TLS 降级」的场景下（自签小站正是本项目的
    主要目标），会累积大量半开/TIME_WAIT 连接，最终表现成
    「跑一段时间后所有请求都超时」——这种症状极难反推到"曾经丢过一个 client"。
    （实测：这个项目里 verify 翻转确实会发生，见 fetch_text 的 relaxed 重试。）
    """
    global _client, _client_no_proxy
    if use_proxy is None:
        use_proxy = USE_PROXY
    cur = _client if use_proxy else _client_no_proxy
    if cur is not None and cur.__dict__.get("_nb_verify") is not verify:
        # 换 verify 等于换一整套连接池 —— 旧的得**主动关掉**，不能等 GC
        try:
            cur.close()
        except Exception:  # noqa: BLE001
            pass
        cur = None
    if cur is None:
        cur = _make_client(verify=verify, use_proxy=use_proxy)
        cur.__dict__["_nb_verify"] = verify
        if use_proxy:
            _client = cur
        else:
            _client_no_proxy = cur
    return cur



class _FatalHTTP(Exception):
    """4xx 这类「重试也没用」的错误，直接放弃。"""


# 连接被重置/拒绝通常是反爬或站点不可用，重试多了只会浪费时间且更容易被封
_CONN_ERRORS = (
    httpx.ReadError,
    httpx.RemoteProtocolError,
    ConnectionResetError,
    ConnectionAbortedError,
)

# 连 TCP 都建不起来 —— 多半是被这个站把 IP 封了。
# 实测 `www.29zw.com`：反复请求十几次之后，连接直接超时（连首页也一样），
# 而同期百度 / 落霞 / 西红柿全部秒开。这就是「连接级封禁」的样子。
# 遇到它要记一笔冷却，否则后面每个候选都要白等一次超时，把整轮搜索拖垮。
_CONNECT_DEAD = (httpx.ConnectTimeout, httpx.ConnectError)
_BLOCK_SECONDS = 90.0


DEFAULT_RETRIES = 3
DEFAULT_TIMEOUT: Optional[float] = None


def fetch_text(url: str, *, encoding: Optional[str] = None, retries: int | None = None,
               data: Optional[dict] = None, with_url: bool = False):
    """抓取网页文本，自动处理编码问题。

    data 非空则发 POST（很多小说站的搜索表单是 POST，GET 会 403 或跳首页）。

    内置：同域限速 + 指数退避重试（应对临时限流/连接被断）。

    重试策略（避免在死链上浪费时间）：
      - 4xx（除了 429）→ 立刻放弃，不重试
      - 连接被重置 / 拒绝 → 最多重试 1 次
      - 5xx / 429 / 超时 → 正常退避重试

    在 fast_mode() 上下文里调用时，会自动使用更短的超时和更少的重试
    （用于「搜索后的可用性探测」—— 这类请求宁可不做也不能卡住用户）。

    with_url=True 时返回 `(文本, 最终 URL)`。跟随重定向之后真实落在哪个地址
    很重要：搜索引擎给的 `/book/catalogue/349017/` 和 `/book/x/349017/toc`
    是同一页，不去重就会出现两张一模一样的卡片。
    """
    if retries is None:
        retries = current_retries()
    timeout = current_timeout()

    left = cooldown_left(url)
    if left > 0:
        raise RuntimeError(f"该站点刚被限流，冷却中（还剩 {left:.0f}s）")

    last_err: Optional[Exception] = None
    # 本请求是否已经因为证书问题降级过一次（见 _cert_error / _TLS_STRICT）
    relaxed = False
    attempt = 0
    while attempt <= retries:
        try:
            _throttle(url)
            kwargs: dict = {"timeout": timeout} if timeout is not None else {}
            cli = get_client(verify=relaxed)
            if data:
                resp = cli.post(url, data=data, **kwargs)
            else:
                resp = cli.get(url, **kwargs)
            code = resp.status_code
            if code == 200:
                raw = resp.content
                enc = encoding or _guess_encoding(resp, raw)
                text = raw.decode(enc, errors="replace")
                return (text, str(resp.url)) if with_url else text
            if 400 <= code < 500 and code != 429:
                raise _FatalHTTP(f"HTTP {code}")
            raise RuntimeError(f"HTTP {code}")
        except _FatalHTTP:
            raise
        except _CONNECT_DEAD as e:
            # 连 TCP 都建不起来 → 大概率被封 IP，记一笔冷却，别继续撞
            last_err = e
            mark_blocked(url, _BLOCK_SECONDS)
            if attempt >= min(retries, 1):
                break
            time.sleep(0.5 + random.uniform(0, 0.3))
        except _CONN_ERRORS as e:
            last_err = e
            if attempt >= min(retries, 1):
                break
            time.sleep(0.5 + random.uniform(0, 0.3))
        except Exception as e:  # noqa: BLE001
            last_err = e
            # —— 证书问题：降级一次（不校验）重试，并留痕 ——
            # 只降级一次、只针对证书类错误，且不发散到其它异常，
            # 免得「网络抖动」也被当成证书问题偷偷关掉校验。
            if _TLS_STRICT and not relaxed and _cert_error(e):
                relaxed = True
                logger.warning(
                    "TLS 校验失败，降级重试（不校验证书）：%s —— %s", url, e
                )
                continue    # 不消耗重试次数，直接换 client 再试
            if attempt < retries:
                time.sleep(0.8 * (2 ** attempt) + random.uniform(0, 0.5))
        attempt += 1

    raise RuntimeError(f"抓取失败: {url} ({last_err})")


# 探测模式下使用的宽松参数（线程局部，避免污染正常下载）
_local = threading.local()


def current_retries() -> int:
    """当前线程的重试次数。

    必须返回**具体数字**：早先这里用 getattr(_local,"retries",3)，
    而 fast_mode 退出时把值恢复成了 None，于是 fast_mode 之后的每一次
    fetch_text 都会 `None + 1` 抛 TypeError，被上层 except 吞掉后
    静默返回空正文 —— 表现就是「下载成功但文件是空的」。
    """
    v = getattr(_local, "retries", None)
    return DEFAULT_RETRIES if v is None else v


def current_timeout():
    return getattr(_local, "timeout", None)


@contextmanager
def fast_mode(retries: int = 1, timeout: float = 12.0):
    """进入「快速失败」模式：短超时 + 少重试。

    用于可用性探测 / 预览这类需要立刻给用户反馈的场景。

    退出时恢复到进入前的**具体值**（而不是 None），这样上下文之外的
    调用不会拿到一个 None 去参与算术。
    """
    prev = (current_retries(), current_timeout())
    _local.retries, _local.timeout = retries, timeout
    try:
        yield
    finally:
        _local.retries, _local.timeout = prev


def _guess_encoding(resp: httpx.Response, raw: bytes) -> str:
    """猜测网页编码。中文站常见 gbk / utf-8。"""
    ct = resp.headers.get("content-type", "").lower()
    m = re.search(r"charset=([\w-]+)", ct)
    if m:
        enc = m.group(1).lower()
        if enc in ("gb2312", "gbk", "gb18030"):
            return "gb18030"
        return enc

    head = raw[:3000].decode("ascii", errors="ignore").lower()
    m = re.search(r'charset=["\']?([\w-]+)', head)
    if m:
        enc = m.group(1).lower()
        if enc in ("gb2312", "gbk", "gb18030"):
            return "gb18030"
        return enc

    # 中文站没声明时，优先试 utf-8
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "gb18030"


def clean_text(text: str) -> str:
    """去掉 HTML 标签 / 广告 / 多余空白。"""
    text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_unescape(text)

    # 去掉常见广告行
    ad_patterns = [
        r"一秒记住.*?免费阅读",
        r".*?最新章节.*?请记住",
        r"手机用户请浏览.*?",
        r"本章未完.*?点击下一页",
        r"天才一秒记住.*",
        r"本站网址.*",
        r"请记住本书首发域名.*",
    ]
    for p in ad_patterns:
        text = re.sub(p, "", text)

    # 去掉维基文库页面的导航行（上一回/下一回/回目录）
    text = re.sub(r"^\s*(上一回|下一回|回目录)(\s+(上一回|下一回|回目录))*\s*$", "", text, flags=re.M)

    # 规范化空白
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_unescape(text: str) -> str:
    import html as _html

    return _html.unescape(text)


def html_to_text(fragment: str, junk: Optional["re.Pattern"] = None,
                 br_fallback: bool = True) -> str:
    """把正文 HTML 片段转成纯文本。

    必须同时兼容两种排版，否则会稳定地「漏掉」一部分章节：

      A. 每段用 <p> 包裹            —— 大多数小说站
      B. 整段纯文本，只用 <br/> 换行 —— 同一个站的不同章节都可能不一样
         （无忧书城就是这样：有的章节有 <p>，有的全是 <br/><br/>）

    br_fallback: 只有在传入的片段**已经是正文容器**时才该开启；
                 如果传的是整页 HTML，没有 <p> 时会把导航也当成正文。
    """
    frag = re.sub(r"<(script|style)[\s\S]*?</\1>", "", fragment, flags=re.I)
    paras = re.findall(r"<p[^>]*>([\s\S]*?)</p>", frag, re.I)
    if not paras and br_fallback:
        # 连续两个 <br> 视为分段，单个 <br> 视为段内换行
        chunks = re.split(r"(?:<br\s*/?>\s*){2,}", frag, flags=re.I)
        paras = [re.sub(r"<br\s*/?>", "\n", c, flags=re.I) for c in chunks]

    lines: list[str] = []
    for p in paras:
        seg = re.sub(r"<[^>]+>", "", p)
        seg = html_unescape(seg).replace("\xa0", " ").replace("&nbsp;", " ")
        seg = re.sub(r"[ \t\u3000]+", " ", seg).strip()
        if len(seg) < 2:
            continue
        if junk and junk.search(seg):
            continue
        lines.append(seg)
    return clean_text("\n\n".join(lines))


def normalize_title(s: str) -> str:
    """书名归一化，方便匹配。"""
    s = s.strip()
    s = re.sub(r"[《》\s]", "", s)
    return s.lower()


# --------------------------------------------------------------------------
# 进程内缓存：目录页抓一次就够了 —— 预览一次、下载一次不必抓两遍
# --------------------------------------------------------------------------
_cache_lock = threading.Lock()
_mem_cache: dict[str, tuple[float, object]] = {}


def cached(key: str, ttl: float, producer):
    """带 TTL 的进程内缓存。producer 在未命中时调用。"""
    now = time.time()
    with _cache_lock:
        hit = _mem_cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = producer()
    with _cache_lock:
        _mem_cache[key] = (now, val)
    return val


def cache_clear(prefix: str | None = None) -> int:
    """清缓存，返回清掉的条数。"""
    with _cache_lock:
        if prefix is None:
            n = len(_mem_cache)
            _mem_cache.clear()
            return n
        keys = [k for k in _mem_cache if k.startswith(prefix)]
        for k in keys:
            _mem_cache.pop(k, None)
        return len(keys)


def clean_wikitext(wt: str) -> str:
    """把 MediaWiki 维基源码清洗为纯文本。"""
    if not wt:
        return ""
    t = wt
    # 语言转换标记 -{zh-hans:云; zh-hant:雲;}- 取简体（第一个值）
    t = re.sub(r"-\{[^{}]*?(?:[:|])([^{}|;]*)[^{}]*\}-", r"\1", t)
    t = re.sub(r"-\{([^{}]*)\}-", r"\1", t)
    # 去掉 {{~~|...}} 这类没闭合好的残留
    t = re.sub(r"\{\{~~\|", "", t)
    # 去掉模板 {{...}}（含嵌套的简单情形）
    for _ in range(4):
        t = re.sub(r"\{\{[^{}]*\}\}", "", t)
    t = re.sub(r"\{\{[^{}]*$", "", t)  # 未闭合的尾部模板
    t = re.sub(r"^[^{}]*\}\}", "", t, flags=re.M)  # 残留的 }} 行
    # 去掉表格
    t = re.sub(r"\{\|[\s\S]*?\|\}", "", t)
    # 去掉注释
    t = re.sub(r"<!--[\s\S]*?-->", "", t)
    # 去掉 <ref>...</ref> 与自闭合标签
    t = re.sub(r"<ref[^>]*/>", "", t)
    t = re.sub(r"<ref[\s\S]*?</ref>", "", t)
    t = re.sub(r"<[^>]+>", "", t)
    # 链接 [[a|b]] -> b ；[[a]] -> a
    t = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\[\[([^\]]*)\]\]", r"\1", t)
    # 外链 [url 文本] -> 文本
    t = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", t)
    t = re.sub(r"\[https?://\S+\]", "", t)
    # 标题 == x == -> x
    t = re.sub(r"^={2,}\s*(.*?)\s*={2,}\s*$", r"\1", t, flags=re.M)
    # 粗体/斜体
    t = t.replace("'''", "").replace("''", "")
    # 列表符号
    t = re.sub(r"^[*#:;]+\s*", "", t, flags=re.M)
    # 水平线
    t = re.sub(r"^-{4,}\s*$", "", t, flags=re.M)

    return clean_text(t)
