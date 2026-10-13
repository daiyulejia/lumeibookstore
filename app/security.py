"""安全：访问令牌 + SSRF 防护。

为什么需要这一层
----------------
原本这是个纯局域网工具，没有任何鉴权也没关系 —— 能连上你 WiFi 的本来
就是你自己人。但一旦接上内网穿透，服务就有了一个**公网地址**，
那时候「没有鉴权」等于把书架、导出文件、删除接口一起送人。

所以：

1. **令牌**。经代理进来的请求（云隧道/反代）必须带对令牌。
   局域网直连不要求 —— 那是你自己的网络，加一道锁只会让人烦。

2. **SSRF 防护**。「粘贴网址自动适配」是个天然的 SSRF 入口：
   服务端会去抓用户给的任意 URL。加了公网入口之后，别人就能用它当跳板
   去探测你的内网（路由器管理页、NAS、云元数据 169.254.169.254…）。
   所以抓之前先解析域名，内网地址一律拒绝。
"""
from __future__ import annotations

import ipaddress
import json
import os
import secrets
import socket
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Optional

# 令牌存哪
_ROOT = Path(__file__).resolve().parent.parent
_AUTH_FILE = _ROOT / "cache" / "auth.json"

_cache: Optional[str] = None


# ---------------------------------------------------------------------------
# 访问令牌
# ---------------------------------------------------------------------------
def token() -> str:
    """取（必要时生成）访问令牌。"""
    global _cache
    if _cache:
        return _cache

    # 环境变量优先，方便 docker / 自动化部署
    env = os.environ.get("NOVELDOCK_TOKEN", "").strip()
    if env:
        _cache = env
        return _cache

    try:
        if _AUTH_FILE.exists():
            d = json.loads(_AUTH_FILE.read_text(encoding="utf-8"))
            t = str(d.get("token") or "").strip()
            if len(t) >= 16:
                _cache = t
                return _cache
    except Exception:  # noqa: BLE001  文件坏了就当没有，重新生成
        pass

    _cache = secrets.token_urlsafe(18)
    _save(_cache)
    return _cache


def _save(t: str) -> None:
    try:
        _AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        _AUTH_FILE.write_text(
            json.dumps({"token": t, "created": int(time.time())}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass


def rotate() -> str:
    """换一个令牌（怀疑泄露时用）。"""
    global _cache
    _cache = secrets.token_urlsafe(18)
    _save(_cache)
    return _cache


def _client_of(request) -> str:
    return (request.client.host if request.client else "") or ""


def _is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "::1", "localhost") or host.startswith("127.")


# ---------------------------------------------------------------------------
# 服务暴露面：判断「这台服务是不是直接挂在网络上」
# ---------------------------------------------------------------------------
# 这是一个**踩过大坑**才补上的判据。原来的逻辑只看「有没有代理头」：
# 有 CF-Connecting-IP / X-Forwarded-For 就算公网，没有就当局域网直连放行。
#
# 这个前提是「公网访问一定要经过隧道」。但把服务部署到**云服务器**之后，
# 情况完全不同：浏览器直接连 `http://<公网IP>:8000`，**一个代理头都没有**，
# 于是被当成「局域网直连」一路放行 —— 任何人扫到这个端口，
# 打开 /api/library 就能拿到整个书架的元数据。这是真实的越权，不是理论风险。
#
# 所以判据要扩成三条，任一成立就算「公网暴露」：
#   1. 请求带了代理头（隧道/反代）
#   2. 服务绑在 0.0.0.0 / ::（= 有意对网络开放）
#   3. 来源 IP 不是回环（从别的机器连过来的）
#
# 注意 3 单独用会误伤局域网（家里手机连 192.168.x.x 就是非回环）。
# 所以 2 和 3 要**同时**成立才算公网 —— 绑 0.0.0.0 且来源不是本机，
# 那必然是从网络上来的。而「本机自己访问 127.0.0.1」永远算本地。
_bind_exposed: Optional[bool] = None


def set_bind_exposed(flag: bool) -> None:
    """由启动层（serve.py / run.py）告知：服务是否绑在对外地址上。

    为什么不由这里自己探测：绑在哪个地址只有启动那一刻知道，
    而这个模块是被各处 import 的，没有一个天然的初始化时机。
    让启动层显式告知，语义最清楚，也方便测试时直接改。
    """
    global _bind_exposed
    _bind_exposed = bool(flag)


def bind_exposed() -> bool:
    return bool(_bind_exposed)


def is_public_entry(request) -> bool:
    """这个请求是不是从**公网入口**进来的？(决定要不要令牌)

    成立条件（任一）：
      · 带了 Cloudflare / 反代的转发头 —— 确凿经过了代理
      · 服务绑在 0.0.0.0（对外开放）**且**来源不是回环地址

    第二条是为「云服务器直接暴露端口」补的。见上面 _bind_exposed 那段注释。

    ⚠ 关于「伪造转发头」
    ------------------
    转发头只看**存在与否**，不看来源 IP。有人可能担心：伪造
    `X-Forwarded-For` 能否**绕过**鉴权？答案是不能 —— 伪造只会让判定
    变成「是公网入口」，于是**要求令牌**（更严格），不会更宽松。
    最坏情况是攻击者把自己挡在门外（无收益）。

    真正的风险在**反方向**：如果哪天在前面架了 nginx/CF，而代理**忘了**
    配置转发头，那么真公网用户会被判成「局域网直连」→ **不需要令牌**，
    整个书架裸奔。**加反代时必须同时确认转发头已配**（这也是本项目
    目前没加反代的原因之一 —— 直连 + 令牌是最简单的正确形态）。
    """
    h = request.headers
    if h.get("cf-connecting-ip") or h.get("cf-ray"):
        return True
    if h.get("x-forwarded-for") or h.get("x-real-ip"):
        return True

    # 服务没对外绑 → 只可能是本机/局域网内部使用，历史行为不变
    if not _bind_exposed:
        return False

    # 绑了 0.0.0.0：本机自己访问（127.0.0.1）依然算本地，
    # 从别的 IP 来的就算公网入口，要令牌。
    return not _is_loopback(_client_of(request))


def check_request(request) -> bool:
    """返回 True = 放行。经代理进来的必须带对令牌。"""
    if not is_public_entry(request):
        return True  # 局域网直连

    supplied = (
        request.query_params.get("t")
        or request.headers.get("x-token")
        or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    )
    # 常数时间比较，避免计时侧信道
    return bool(supplied) and secrets.compare_digest(str(supplied), token())


def needs_auth_response(request) -> bool:
    return is_public_entry(request) and not check_request(request)


def is_local(request) -> bool:
    """请求是不是「本机直连」—— 只有这种才配拿到令牌明文。

    为什么要区分：`/api/net` 会把访问令牌一起返回（界面上要显示出来给用户
    复制到手机）。但那个接口任何能连上你服务的人都能调 —— 局域网里的另一台
    电脑、公共 WiFi 上的陌生人。若不加区分地返回明文，等于「谁连上你的网，
    谁就拿到了公网通行证」。所以明文只给本机，别人只给前几位提示。
    """
    if is_public_entry(request):
        return False
    return _is_loopback(_client_of(request))


# 页面骨架与静态资源不设防。理由见 main._auth_gate：
# 浏览器对 <link>/<script>/<img> 不会自动带 ?t=，拦了就是白屏；
# 而它们本身不含任何数据，数据全在 /api/* 里。
_PUBLIC_ASSET_EXACT = ("/", "/index.html", "/favicon.ico")
_PUBLIC_ASSET_PREFIXES = ("/static/",)


def is_public_asset(path: str) -> bool:
    """静态资源或页面骨架 —— 不需要令牌。"""
    return path in _PUBLIC_ASSET_EXACT or path.startswith(_PUBLIC_ASSET_PREFIXES)


# ---------------------------------------------------------------------------
# 公网入口限流
# ---------------------------------------------------------------------------
# 令牌是 token_urlsafe(18)，约 144 bit 随机量 —— 猜是猜不出来的，所以这层
# 不是防爆破，防的是另外两件事：
#   · 令牌一旦到了别人手里，被拿来狂刷（把这台家用机当免费算力）
#   · 未授权状态下拿接口当靶子打
# 局域网直连不限 —— 那是你自己的网，限它只会误伤自己人。
_RL_WINDOW = 10.0
_RL_MAX = 150          # 每 10 秒 / 每 IP 上限；正常看小说翻页远远用不到
_rl_hits: dict[str, list[float]] = {}
_rl_lock = threading.Lock()


def _client_ip(request) -> str:
    h = request.headers
    ip = h.get("cf-connecting-ip") or h.get("x-forwarded-for", "").split(",")[0].strip()
    return (ip or _client_of(request)).strip()


def rate_limited(request) -> bool:
    """超过阈值返回 True（调用方回 429）。只对公网入口生效。"""
    if not is_public_entry(request):
        return False
    ip = _client_ip(request)
    if not ip:
        return False
    now = time.time()
    with _rl_lock:
        hits = [t for t in _rl_hits.get(ip, ()) if now - t < _RL_WINDOW]
        hits.append(now)
        _rl_hits[ip] = hits
        # 顺手清掉早就没动静的 IP，别让这个表无限长
        if len(_rl_hits) > 512:
            for k in [k for k, v in _rl_hits.items() if not v or now - v[-1] > 60]:
                _rl_hits.pop(k, None)
        return len(hits) > _RL_MAX


# ---------------------------------------------------------------------------
# SSRF 防护
# ---------------------------------------------------------------------------
class BlockedURL(ValueError):
    """URL 指向了不该去的地方。"""


_PRIVATE_HOST_SUFFIX = (".local", ".internal", ".localhost", ".lan", ".home", ".corp")


def assert_public_url(url: str) -> str:
    """校验 URL 可以安全地被服务端抓取。返回规范化后的 URL。"""
    u = (url or "").strip()
    if not u:
        raise BlockedURL("网址是空的")

    if "://" not in u:
        u = "https://" + u

    p = urllib.parse.urlparse(u)
    if p.scheme not in ("http", "https"):
        raise BlockedURL(f"只支持 http / https，不支持 {p.scheme}")
    host = p.hostname
    if not host:
        raise BlockedURL("网址里没解析出域名")

    low = host.lower()
    if low in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"):
        raise BlockedURL("不能指向本机地址")
    if low.endswith(_PRIVATE_HOST_SUFFIX):
        raise BlockedURL("不能指向内网域名")

    # 解析出真实 IP 再判 —— 只判字符串会被 `http://127.0.0.1.nip.io` 这类
    # 「解析到 127.0.0.1 的域名」绕过
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise BlockedURL(f"域名解析不了：{host}") from e

    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise BlockedURL(f"这个网址解析到了内网地址（{ip_str}），出于安全考虑不抓取")
        # 云元数据服务的保留地址
        if str(ip) == "169.254.169.254":
            raise BlockedURL("不能访问云服务器的元数据地址")

    return u


def safe_public_url(url: str) -> tuple[bool, str]:
    """不抛异常的版本，给接口层用。返回 (ok, url或错误信息)。"""
    try:
        return True, assert_public_url(url)
    except BlockedURL as e:
        return False, str(e)
