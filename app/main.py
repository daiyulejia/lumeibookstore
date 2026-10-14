"""小说下载服务 —— FastAPI 主程序。

启动后监听 0.0.0.0，同一局域网内其它设备可直接访问。

接口一览
--------
页面
  GET    /                        前端页面

搜索
  POST   /api/confirm             书名确认：归一化 + 「你是不是想找《X》」候选
  GET    /api/search?kw=          流式搜索（NDJSON：item / verified / step / done / error）
  GET    /api/sources             可用来源列表
  GET    /api/sources/check       来源健康检查（域名失效很常见）

联网发现 / 来源库
  POST   /api/fetch-url           给一个书页 URL，自己看出目录和正文在哪
  GET    /api/registry            来源库总览（攒下来的站点和书）
  GET    /api/registry/check      给来源库做体检（失效的自动清掉）
  POST   /api/registry/learn      给站点学站内搜索接口（变成可搜源）
  POST   /api/registry/prune      清理来源库
  DELETE /api/registry/book       从库里删一本书
  DELETE /api/registry/site       从库里删一个站

预览
  POST   /api/preview             取书籍信息 + 目录 + 某章正文样本
  POST   /api/chapter             直接读某章正文（不入书架）

书架 / 阅读
  POST   /api/shelve              入书架（建记录 + 拉目录），返回 library_id
  GET    /api/library             书架列表
  GET    /api/library/stats       书架统计
  GET    /api/library/{bid}       书籍详情（meta + 目录 + 缓存情况）
  GET    /api/library/{bid}/chapter/{n}   读第 n 章（缓存优先，未命中自动联网补）
  POST   /api/library/{bid}/position      保存阅读进度
  POST   /api/library/{bid}/cache         后台把全书缓存进书架
  GET    /api/library/{bid}/toc           只取目录（阅读器翻目录用）
  DELETE /api/library/{bid}               移出书架

导出
  POST   /api/download            导出 txt / epub / html
  POST   /api/cancel/{task_id}    取消下载
  GET    /api/progress/{task_id}  任务进度
  GET    /api/tasks               所有任务
  GET    /api/downloads           已导出文件
  GET    /api/file/{name}         下载文件
  DELETE /api/file/{name}         删除文件
  POST   /api/cache/clear         清进程内缓存

埋点
  POST   /api/log                 前端错误/慢接口回传（写进 logs/app.log）

资源代理
  GET    /api/cover?u=            代理来源站的封面图（带 Referer 破防盗链 + 落盘缓存）
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import history, security, tunnel, visits
from .engine import Engine, source_meta
from .errors import Cancelled, SourceBlocked
from .exporter import DOWNLOAD_DIR, export as export_book

# 封面缓存目录。刻意放在 `cache/` 下而不是 `downloads/`：
# downloads 是给用户看的成品目录（会被 /api/files 列出来），
# 封面只是渲染用的中间件，混进去会污染文件列表。
COVER_CACHE_DIR = DOWNLOAD_DIR.parent / "cache" / "covers"
from .library import book_id as lib_book_id
from .library import valid_id
from .logging_setup import get_logger, get_request_id, log_event, set_request_id
from .logging_setup import setup as setup_logging
from .models import Book, BookResult, Chapter
from .suggest import confirm as confirm_keyword
from .utils import cache_clear

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# 日志：把 httpx / uvicorn 的流水账压掉，换成带 req= 的结构化格式。
# 详见 app/logging_setup.py 头部 —— 那里记了"47% 日志是爬取噪声"的诊断。
LOG_FILE = setup_logging(BASE_DIR.parent / "logs")
logger = get_logger("novel.app")

app = FastAPI(title="噜妹书院 · 找书 / 下载 / 阅读")
engine = Engine()


def _client_ip(request: Request) -> str:
    """取真实客户端 IP，给访客统计用。

    直连时 `request.client.host` 就是对的；但走隧道/反代时那是**代理的**
    地址（127.0.0.1），所有人会算成同一个访客，UV 永远是 1。
    所以优先读代理留下的头。

    ⚠ 顺序很讲究：X-Forwarded-For 是 `客户端, 代理1, 代理2`，
    **第一个**才是原始客户端。取最后一个会把代理算成访客。
    ⚠ 这些头是可以伪造的 —— 但它只用于"大致统计"，不参与任何鉴权，
    被伪造最多让 UV 数字不准，不会造成安全问题。
    """
    for h in ("cf-connecting-ip", "x-real-ip", "x-forwarded-for"):
        v = request.headers.get(h)
        if v:
            return v.split(",")[0].strip()
    return getattr(request.client, "host", "") or ""


@app.middleware("http")
async def _observe(request: Request, call_next):
    """给每个请求打一个 req= 短 id，并记录「访问 + 耗时 + 状态」。

    为什么放在最外层（在鉴权之前）：
      鉴权失败的请求也要有 id —— "401 是怎么回事"同样需要能追。
      而且这样静态资源也走这条路，一次页面加载的所有请求能串成一条线。

    **为什么不用 uvicorn 自带的访问日志**：
      它没有 request_id，一次搜索打十几个请求、后面跟一个报错，
      你没法知道那个报错属于哪次搜索。而且它会把静态资源的 GET 全打出来
      （一个页面 40 行），把有用的淹掉。这里改成：
        · 静态资源只记 DEBUG（默认不显示）
        · /api/* 记 INFO，带耗时
        · 4xx/5xx 记 WARNING/ERROR（这样"出问题"会自己浮上来）
    """
    rid = set_request_id()
    t0 = time.perf_counter()
    path = request.url.path
    try:
        resp = await call_next(request)
    except Exception:
        ms = (time.perf_counter() - t0) * 1000
        logger.exception("http.crash %s %s 耗时=%.0fms", request.method, path, ms)
        raise
    ms = (time.perf_counter() - t0) * 1000
    code = resp.status_code
    if path.startswith("/api/"):
        lv = logging.INFO
        if code >= 500:
            lv = logging.ERROR
        elif code >= 400:
            lv = logging.WARNING
        # 慢请求单独标出来 —— "为什么卡"是最高频的抱怨，
        # 有这一行就不用靠猜。800ms 是拍的：正常接口都在 200ms 内。
        slow = " 慢" if ms > 800 else ""
        log_event(logger, "http", lv, method=request.method, path=path,
                  status=code, ms=f"{ms:.0f}{slow}")
        # 访客记录：只记 API（静态资源一次加载几十条，记了纯属自残）。
        # ⚠ 必须 try 包起来 —— 统计出问题绝不能让业务接口挂。
        try:
            visits.record(
                path,
                _client_ip(request),
                request.headers.get("user-agent", ""),
                ms, code, is_api=True,
            )
        except Exception:  # noqa: BLE001
            logger.exception("visits.record 异常（已忽略，不影响请求）")
    elif code >= 400:
        log_event(logger, "http.asset", logging.WARNING, path=path, status=code)
    resp.headers["X-Request-Id"] = rid
    return resp


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    """公网入口（隧道 / 反代）必须带访问令牌。

    局域网直连不拦 —— 那是你自己的网。判断依据见 security.is_public_entry：
    代理会在请求上留下 CF-Connecting-IP / X-Forwarded-For，直连没有。

    **只守数据接口，不守静态资源**。这一点很容易写错：页面骨架和
    <link>/<script>/<img> 这些子资源，浏览器请求时**不会**带上 ?t= 参数，
    如果连它们一起拦，公网打开就是「HTML 401 + CSS/JS 也 401」= 一片白屏，
    穿透功能直接废掉。而静态资源本身不含任何数据，敏感信息全在 /api/*，
    守住那些就足够了。
    """
    path = request.url.path
    # 限流放在最前面：连静态资源一起算，避免被拿来做压力测试
    if security.rate_limited(request):
        return JSONResponse({"error": "请求太频繁了，歇几秒再试"}, status_code=429)
    if security.is_public_asset(path):
        return await call_next(request)
    # /api/deploy/sh 是"怎么装"的说明书，必须免令牌 ——
    # 服务器在装上之前根本拿不到令牌。它不含任何数据，
    # 真正含数据的是 /api/deploy/tar，那个守的是"只给局域网"。
    # /api/deploy/guide 同理：它只是把 README 那一节渲染出来，
    # 而它是用 window.open 打开的，浏览器不会带 ?t=。
    if path in ("/api/auth", "/api/deploy/sh", "/api/deploy/guide"):
        return await call_next(request)
    # /api/deploy/tar 走它自己的守卫（只认局域网，不认令牌）——
    # 必须在鉴权之前放过去，否则隧道请求会先拿到 401「需要访问令牌」，
    # 那句话在这儿是误导：带令牌也不该给。
    if path == "/api/deploy/tar":
        return await call_next(request)
    if security.needs_auth_response(request):
        return JSONResponse(
            {"error": "需要访问令牌", "need_token": True},
            status_code=401,
        )
    return await call_next(request)

# 任务表：task_id -> {...}
TASKS: dict[str, dict] = {}
TASKS_LOCK = threading.Lock()
MAX_TASKS_KEPT = 60

# 章节预取：正在后台补的章节，避免重复请求
_prefetch_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="prefetch")
_prefetch_lock = threading.Lock()
_prefetch_inflight: set[tuple[str, int]] = set()
# 预取待办上限。`_prefetch_inflight` 同时充当「在跑的」和「排队的」两本账
# （job 的 finally 里才 discard），所以这个数就是**队列深度**。
# 3 个 worker × 每人 3 章缓冲 = 12 就够用了；留一点余量到 16。
# 超了就干脆不预取（见 _schedule_prefetch 注释）—— 预取是锦上添花，
# 不能反过来让「用户已翻过去的旧章节」霸占来源站的限速配额。
PREFETCH_MAX_INFLIGHT = 16


# ---------------------------------------------------------------------------
# 请求体
# ---------------------------------------------------------------------------
class BookReq(BaseModel):
    """标识一个候选书籍。"""

    title: str = ""
    author: str = ""
    source: str
    url: str
    intro: str = ""
    chapter_index: int | None = None


class DownloadReq(BookReq):
    max_chapters: int | None = None   # 最多下载多少章，None = 全部
    keyword: str = ""
    fmt: str = "txt"                  # txt | epub | html
    library_id: str = ""              # 有书架缓存时优先用缓存导出（快得多）


class PositionReq(BaseModel):
    index: int = 1
    percent: float = 0.0
    offset: int = 0


class ConfirmReq(BaseModel):
    """书名确认请求。"""
    text: str = ""


class AdaptReq(BaseModel):
    """站点自动适配请求：给我一个网址，我推导出一份来源配置。"""
    url: str
    keyword: str = "斗破苍穹"   # 用来试搜索、抽目录和正文的测试书
    save: bool = False          # 适配通过后是否直接写进 sites.json


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------
_VER_CACHE: tuple[float, str] = (0.0, "")
_ASSET_DIRS = ("js", "css", "vendor", "dist")


def _asset_version() -> str:
    """前端资源的版本号 = 静态文件里最新的 mtime。

    为什么需要它：这一版把前端从「1959 行单文件」拆成了模块化，
    但页面 URL 还是 `/`。老浏览器里缓存的旧 HTML 引用的是**旧结构**，
    而旧版的阅读器只有上下滚动、连「翻页方式」这个设置项都没有 ——
    用户看到的就是「怎么翻都是往下滚」。

    把版本号拼到 `/static/xxx?v=...` 上之后，只要改了任何一个前端文件，
    引用 URL 就变了，浏览器不可能再拿旧代码来配新页面。

    （之所以每次算而不是缓存到底：就十来个文件 stat 一下，比排查
      「为什么改了没生效」便宜太多了。1 秒 TTL 只是防连击。）
    """
    global _VER_CACHE
    now = time.time()
    if now - _VER_CACHE[0] < 1.0:
        return _VER_CACHE[1]
    newest = 0.0
    for d in _ASSET_DIRS:
        for p in (STATIC_DIR / d).glob("*"):
            try:
                if p.is_file():
                    newest = max(newest, p.stat().st_mtime)
            except OSError:
                pass
    try:
        newest = max(newest, (STATIC_DIR / "index.html").stat().st_mtime)
    except OSError:
        pass
    v = str(int(newest))
    _VER_CACHE = (now, v)
    return v


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def index(request: Request):
    """首页。

    必须带 `Cache-Control: no-cache` —— 不然浏览器按「没有缓存头」的
    启发式规则自作主张缓存下来，前端改了用户也看不到（真实踩过）。
    no-cache 不是「不缓存」，而是「用之前必须先来问一句」；
    配合 ETag，没变就回 304，几乎不费流量。
    """
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    v = _asset_version()
    # 给静态资源引用带上版本号（/static/css/app.css -> ...?v=1699...）
    html = re.sub(r'(/static/[A-Za-z0-9_./-]+\.(?:css|js))(?=["\'])', rf"\1?v={v}", html)

    etag = '"' + hashlib.sha1(html.encode("utf-8")).hexdigest()[:20] + '"'
    headers = {"Cache-Control": "no-cache, must-revalidate", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return HTMLResponse(html, headers=headers)


@app.get("/api/health")
async def health():
    from . import registry
    from .utils import cooldown_clear, cooldowns

    return {"ok": True, "sources": len(engine.sources),
            "library": engine.library.stats(),
            "registry": registry.stats(),
            "cooldowns": cooldowns()}


@app.get("/api/sources")
async def sources():
    return [{"name": s.name, "display": s.display, **source_meta(s)}
            for s in engine.sources]


# ---------------------------------------------------------------------------
# 手机怎么打开：局域网地址 + 防火墙有没有放行
# ---------------------------------------------------------------------------
_net_cache: dict = {}
_NET_TTL = 30.0


@app.get("/api/net")
async def net_info(request: Request, force: bool = False):
    """告诉用户「手机该输什么地址」，以及现在能不能连上。

    netsh 查一次要 1.6 秒，所以缓存 30 秒 —— 这个信息也不会秒变。
    `force=1` 用来跳过缓存：用户照着提示放行了端口之后，
    点「重新检测」必须能立刻看到变化，否则会以为没生效。

    ⚠ 缓存里**只放 netsh 的检测结果**。隧道状态、访问令牌、是否公网入口
    这些都是「随请求而变」的，必须每次现算 —— 否则本机请求攒下的令牌明文，
    会被下一个局域网请求从缓存里原样读走（等于绕过 is_local 那层判断）。
    """
    port = request.url.port or 8000
    now = time.time()
    hit = _net_cache.get("data")
    if (not force and hit and now - _net_cache.get("ts", 0) < _NET_TTL
            and hit.get("port") == port):
        data = dict(hit)          # 复制一份，别让下面往缓存本体上写
    else:
        loop = asyncio.get_running_loop()
        from .netinfo import check

        data = await loop.run_in_executor(None, lambda: check(port))
        _net_cache["data"] = dict(data)
        _net_cache["ts"] = now

    # ↓ 每次请求现算，不进缓存
    t = tunnel.status()
    data["tunnel"] = {"running": t["running"], "url": t["url"], "available": t["available"]}
    # 令牌明文**只给本机**：否则同一 WiFi 上的任何设备都能调这个接口把
    # 公网通行证捞走。别人只给前 4 位，够辨认不够用。
    tok = security.token()
    data["token_hint"] = tok[:4] + "…"
    data["token"] = tok if security.is_local(request) else ""
    data["public_entry"] = security.is_public_entry(request)
    return data


# ---------------------------------------------------------------------------
# 访问令牌
# ---------------------------------------------------------------------------
@app.get("/api/auth")
async def auth_check(request: Request, t: str = ""):
    """校验令牌。前端把 ?t=xxx 拿来这里换一个「通过/不通过」。"""
    if t:
        if secrets_compare(t, security.token()):
            return {"ok": True}
        return JSONResponse({"ok": False, "error": "令牌不对"}, status_code=401)
    return {"ok": True, "required": security.is_public_entry(request)}


def secrets_compare(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a.encode(), b.encode())


# ---------------------------------------------------------------------------
# 一键部署：把项目包 + 安装脚本直接吐给服务器
# ---------------------------------------------------------------------------
# 用户在服务器上只需要粘**一条**命令：
#     curl -fsSL http://<本机IP>:8000/api/deploy/sh | bash
# 下面就负责把这条命令需要的两个东西供出来。
#
# 它们都**只允许局域网直连**取用（security.is_local）：
# /api/deploy/tar 里含访问令牌（cache/auth.json），
# 如果能顺着公网隧道拉，等于把整个项目连钥匙一起送人。
def _deploy_guard(request: Request):
    """返回 None 表示放行，否则返回一个 403 响应。

    ⚠ 必须在**鉴权中间件之前**生效，所以这里的判据是"来源是不是本机/局域网直连"，
    而不是"令牌对不对"。理由：部署包是给一台**还没装上服务**的服务器取的，
    它不可能有令牌；反过来，一个从隧道进来的请求即使带着正确令牌，
    也不该让它把整个项目连 auth.json 一起拉走。
    两件事是正交的，用令牌管反而管错了对象。
    """
    if security.is_local(request):
        return None
    return JSONResponse(
        {"ok": False, "error": "部署包只给局域网直连取用（里面含访问令牌）"},
        status_code=403,
    )


@app.get("/api/deploy")
async def deploy_info(request: Request):
    """部署指引：告诉用户「在服务器上粘哪一条」。

    这里是**从用户当前访问的地址**推出命令的基地址 —— 也就是说：
      · 用户在局域网打开界面 → 命令里是 http://192.168.x.x:8000
      · 用户走隧道打开界面   → 命令里是 https://xxx.trycloudflare.com

    这一点是踩过 bug 才改的：原来一律用 local_ip()（局域网地址），
    结果用户开了隧道、拿着命令去服务器上跑，服务器去连 192.168.x.x
    永远连不上（那是他家里的内网地址）。用 request 的 Host 才对。
    """
    local = security.is_local(request)
    from . import deploy as _dep

    # 用请求自己的 Host 推对外地址；Host 里带端口就用它，没带就补上
    host = request.headers.get("host") or ""
    if not host:
        host = f"{local_ip()}:{request.url.port or 8000}"
    base = _dep.base_url(request.url.scheme, host)

    tok = security.token() if local else ""
    cmd = _dep.deploy_command(base, token=tok if local else "")

    return {
        "ok": True,
        "local": local,
        "base": base,
        "command": cmd,
        "steps": [
            "1. 在腾讯云控制台创建服务器，镜像选 Ubuntu Server 22.04 LTS 64位",
            "2. 安全组放行 TCP 8000（这一步别忘）",
            "3. 用控制台的「登录」/网页终端连上去，粘上面那条命令",
            "4. 装完它会直接告诉你手机该打开哪个地址",
        ],
        "note": ("这台电脑要保持开着（因为服务器要从这里把项目拉过去）；"
                 "拉完就不用了。建议开着「远程访问」，这样人在外面也能重装。"),
    }


@app.get("/api/deploy/tar")
async def deploy_tar(request: Request):
    """项目压缩包（含书架、下载、令牌）。只给局域网直连。"""
    bad = _deploy_guard(request)
    if bad is not None:
        return bad
    from fastapi.responses import Response

    from . import deploy as _dep

    data, n, raw = _dep.cached_tar()
    fname = f"noveldock-{time.strftime('%Y%m%d')}.tar.gz"
    return Response(
        content=data,
        media_type="application/gzip",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "X-Files": str(n),
            "X-Raw-Bytes": str(raw),
        },
    )


@app.get("/api/deploy/sh")
async def deploy_sh(request: Request, t: str = ""):
    """服务器上 `curl ... | bash` 执行的那段脚本。

    这个接口**不要求令牌**：它就是"怎么装"的说明书，
    里面除了地址没有任何秘密。真正含数据的 /api/deploy/tar
    才是需要守的那一个，而它守的是"局域网来源"而不是令牌 ——
    令牌在这里也没用，因为人家还没装上，拿不到令牌。

    ⚠ 脚本里的地址必须**从请求自己的 Host 推**，不能用 local_ip()。
    踩过的真 bug：用户开隧道访问，拿到的脚本里却写死
    `http://192.168.31.99:8000`（他家里的内网地址），
    服务器在公网上根本连不上，下载卡到超时。
    用 Host 推就两边都对：局域网访问给内网地址、隧道访问给隧道地址。
    """
    from fastapi.responses import Response

    from . import deploy as _dep

    host = request.headers.get("host") or ""
    if not host:
        host = f"{local_ip()}:{request.url.port or 8000}"
    base = _dep.base_url(request.url.scheme, host)

    # 只有局域网直连才把令牌写进脚本：走隧道的时候这个接口本身
    # 也只是个说明书，不该顺带把令牌打印出去。
    tok = t or (security.token() if security.is_local(request) else "")
    body = _dep.bootstrap_script(base, token=tok)
    return Response(content=body, media_type="text/x-shellscript; charset=utf-8")


@app.get("/api/deploy/guide")
async def deploy_guide(request: Request):
    """把 README 里「部署到云服务器」那一节单独渲染成一个网页。

    为什么不直接让人翻 README：README 有 1000 多行，
    用户只是想看部署这段。这里从 README 里**切出那一节**再套个简单样式，
    所以内容永远和 README 一致，不会出现两处各说各话。
    """
    from fastapi.responses import HTMLResponse

    md = ""
    try:
        text = (BASE_DIR.parent / "README.md").read_text(encoding="utf-8")
        start = text.find("## 部署到云服务器")
        end = text.find("\n## ", start + 5)
        md = text[start:end if end > 0 else len(text)]
    except Exception as e:  # noqa: BLE001
        md = f"（读不到 README：{e}）"

    # 只做最小转义 + 换行处理：这里不需要完整 Markdown 渲染，
    # 而引入一个 md 库只为这一页不划算。代码块和标题靠 <pre> 保住可读性。
    import html as _h

    lines = []
    for ln in md.splitlines():
        e = _h.escape(ln)
        if ln.startswith("## "):
            lines.append(f"<h2>{_h.escape(ln[3:])}</h2>")
        elif ln.startswith("### "):
            lines.append(f"<h3>{_h.escape(ln[4:])}</h3>")
        elif ln.startswith("```"):
            lines.append("<pre>" if not lines or lines[-1] != "</pre>" else "</pre>")
        elif ln.strip() == "":
            lines.append("<p></p>")
        else:
            lines.append(f"<p>{e}</p>")
    body = "\n".join(lines)

    return HTMLResponse(f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>部署到云服务器</title>
<style>
 body{{max-width:760px;margin:0 auto;padding:26px 20px 80px;
   font:15px/1.85 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
   color:#232019;background:#fbfaf7}}
 h2{{font-size:21px;margin:30px 0 12px;font-weight:600}}
 h3{{font-size:16px;margin:24px 0 8px;font-weight:600}}
 p{{margin:9px 0;color:#3a3630}}
 pre{{background:#f2efe8;border:1px solid #e2ddd2;border-radius:9px;
   padding:12px 14px;overflow-x:auto;font-size:13px;line-height:1.65;
   font-family:ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap}}
 table{{border-collapse:collapse;width:100%;margin:12px 0;font-size:14px}}
 td,th{{border:1px solid #e2ddd2;padding:8px 10px;text-align:left}}
 @media(prefers-color-scheme:dark){{
   body{{background:#1c1a17;color:#eceae5}}
   p{{color:#c9c5bd}} pre{{background:#26231f;border-color:#3a352e}}
   td,th{{border-color:#3a352e}}
 }}
</style>
<h1 style="font-size:24px;font-weight:600;margin:0 0 4px">部署到云服务器</h1>
<p style="color:#8a8378;font-size:13px;margin:0 0 20px">
  这一页的内容直接取自项目 README，不会和文档不同步。</p>
{body}""")


@app.post("/api/auth/rotate")
async def auth_rotate(request: Request):
    """换一个令牌（怀疑链接泄露时用）。换完所有旧链接立刻失效。

    只允许从**本机**发起。这是「我在自己电脑上发现地址被人转发了」的场景；
    如果谁都能调，那同网段的人随手一调，你的公网链接全废，
    顺带还从他自己的响应里拿到了新令牌。
    """
    if not security.is_local(request):
        return JSONResponse({"ok": False, "error": "换令牌只能在本机操作"}, status_code=403)
    tok = security.rotate()
    # 根目录那份「远程访问.txt」里写着完整链接，换了钥匙必须一起换 ——
    # 否则人拿到的是一条打不开的链接，比没有还耽误事。
    tunnel.write_access_file()
    return {"ok": True, "token": tok}


# ---------------------------------------------------------------------------
# 内网穿透：在外地也能用
# ---------------------------------------------------------------------------
@app.get("/api/tunnel")
async def tunnel_status():
    return tunnel.status()


@app.post("/api/tunnel/start")
async def tunnel_start(request: Request):
    port = request.url.port or 8000
    loop = asyncio.get_running_loop()
    r = await loop.run_in_executor(None, lambda: tunnel.start(port))
    if r.get("ok"):
        tok = security.token()
        r["url_with_token"] = f"{r['url']}?t={tok}"
    return r


@app.post("/api/tunnel/stop")
async def tunnel_stop():
    return tunnel.stop()



# ---------------------------------------------------------------------------
# 站点自动适配：粘一个网址进来，推导出一份可用的来源配置
# ---------------------------------------------------------------------------
@app.post("/api/adapt")
async def adapt_site(req: AdaptReq):
    """把一个小说站网址适配成来源配置。

    这不是「加个收藏夹」—— 它会真的跑一遍
    「打开首页 → 找搜索接口 → 推导搜索条目 → 推导目录 → 推导正文」，
    最后用 check_content_quality 判定抓到的正文是不是真的。
    任何一步不过都返回 ok=false 和具体卡在哪，不糊弄。
    """
    from .sources.adapter import adapt_sync

    loop = asyncio.get_running_loop()
    # 先过 SSRF 关：摸清域名的真实 IP，内网/回环/云元数据一律不抓。
    # 公网入口打开之后，这个接口等于是"让别人指挥你的服务器去抓 URL"，
    # 不挡就是一个现成的内网探测跳板。
    #
    # 注意要放线程池里做：getaddrinfo 是**阻塞**调用（域名没缓存时要几百毫秒
    # 到数秒），直接在 async 函数里调会把整个事件循环卡住 —— 适配期间
    # 所有其它请求（包括正在读小说的那次）都得排队等它。
    ok, res = await loop.run_in_executor(None, security.safe_public_url, req.url)
    if not ok:
        return JSONResponse({"ok": False, "url": req.url, "error": res}, status_code=400)
    url = res

    try:
        ad = await loop.run_in_executor(
            None, lambda: adapt_sync(url, req.keyword or "斗破苍穹", save=req.save)
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("适配失败")
        return JSONResponse({"ok": False, "url": url, "error": str(e)}, status_code=400)

    out = ad.to_dict()
    if ad.ok and req.save:
        # 适配成功且用户要保存 → 立刻让引擎把新来源装进来，不用重启
        try:
            engine.reload_sources()
            out["loaded"] = True
        except Exception:  # noqa: BLE001
            logger.exception("重载来源失败")
            out["loaded"] = False
    return out


@app.get("/api/adapt/stream")
async def adapt_stream(request: Request, url: str, keyword: str = "斗破苍穹", save: int = 1):
    """适配的流式版：**跑一步推一步**。

    非流式版要等 10~25 秒才吐出第一个字节，中间全是空白 —— 用户会以为
    卡死了。这里把每一步实时推成 NDJSON，界面就能逐步点亮，
    而且失败时能明确停在哪一步。
    """
    loop = asyncio.get_running_loop()
    # SSRF 校验含 DNS 解析（阻塞），放线程池 —— 见 /api/adapt 里同样的说明
    ok, res = await loop.run_in_executor(None, security.safe_public_url, url)
    if not ok:
        async def bad():
            yield json.dumps({"type": "error", "msg": res}, ensure_ascii=False) + "\n"
        return StreamingResponse(bad(), media_type="application/x-ndjson")
    url = res

    from .sources.adapter import adapt_sync

    queue: asyncio.Queue = asyncio.Queue()

    def on_step(step: dict) -> None:
        # 这是在子线程里回调的，必须 call_soon_threadsafe 回主循环
        loop.call_soon_threadsafe(queue.put_nowait, ("step", step))

    def worker():
        try:
            ad = adapt_sync(url, keyword or "斗破苍穹", save=bool(save), on_step=on_step)
            out = ad.to_dict()
            if ad.ok and save:
                try:
                    engine.reload_sources()
                    out["loaded"] = True
                except Exception:  # noqa: BLE001
                    logger.exception("重载来源失败")
                    out["loaded"] = False
            return out
        except Exception as e:  # noqa: BLE001
            logger.exception("适配失败")
            return {"ok": False, "url": url, "error": str(e), "steps": []}

    task = loop.run_in_executor(None, worker)

    async def gen():
        while True:
            # 先把手上的事件都吐出去
            drained = False
            while not queue.empty():
                kind, payload = queue.get_nowait()
                drained = True
                if kind == "step":
                    yield json.dumps({"type": "step", **payload}, ensure_ascii=False) + "\n"
            if task.done() and queue.empty():
                try:
                    final = await task
                except Exception as e:  # noqa: BLE001
                    final = {"ok": False, "error": str(e)}
                yield json.dumps({"type": "done", **final}, ensure_ascii=False) + "\n"
                return
            if not drained:
                await asyncio.sleep(0.12)

    return StreamingResponse(gen(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})



# ---------------------------------------------------------------------------
# 书名确认
# ---------------------------------------------------------------------------
@app.post("/api/confirm")
async def confirm(req: ConfirmReq):
    """搜之前先把书名理干净，顺带给几个「你是不是想找」的候选。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: confirm_keyword(req.text))


# ---------------------------------------------------------------------------
# 热门榜单
# ---------------------------------------------------------------------------
# 「发现」页除了"搜书名"，还应该能"逛逛有什么好看的"。
# 数据来自已适配的站点自己的榜单（见 app/ranks.py 里对来源的挑选说明）。
#
# 两个接口分工：
#   /api/ranks/kinds  —— 有哪些榜单（很轻，前端一进来就能画标签）
#   /api/ranks        —— 某一类榜单的内容（带 30 分钟缓存）
@app.get("/api/ranks/kinds")
async def ranks_kinds():
    """榜单目录。给前端渲染切换标签用。

    刻意不合并进 /api/ranks：标签要立刻画出来，而榜单内容要联网抓。
    分开之后界面先有骨架、再填内容，不会白屏等。
    """
    from . import ranks as _rk
    return {"ok": True, "kinds": _rk.kinds()}


@app.get("/api/ranks")
async def ranks_get(kind: str = "allvisit"):
    """取一类榜单的内容。

    抓取走线程池（ranks.py 里那个 fetch_text 是同步的），
    所以这里用 to_thread 把它挪出事件循环 —— 否则一个榜单卡住，
    整个服务（包括别人正在读的小说）都得等它。
    """
    import asyncio

    from . import ranks as _rk

    if kind not in {d["kind"] for d in _rk.kinds()}:
        return JSONResponse(
            {"ok": False, "error": f"没有这个榜单：{kind}",
             "kinds": [d["kind"] for d in _rk.kinds()]},
            status_code=400,
        )

    try:
        items = await asyncio.to_thread(_rk.get_rank, kind)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"抓取失败：{e}"}, status_code=502)

    label = next((d["label"] for d in _rk.kinds() if d["kind"] == kind), kind)
    desc = next((d["desc"] for d in _rk.kinds() if d["kind"] == kind), "")
    st = _rk.cache_status().get("kinds", {}).get(kind, {})
    return {
        "ok": True,
        "kind": kind,
        "label": label,
        "desc": desc,
        "count": len(items),
        "items": items,
        # 缓存新鲜度：界面据此刻画「x 分钟前更新」，比假装实时诚实。
        "age": st.get("age"),
        "fresh": st.get("fresh", False),
        # 抓不到不是错误，是"这站今天没数据" —— 界面据此走降级提示，
        # 所以用 200 + 空列表，而不是 4xx/5xx。
        "empty_hint": ("" if items else
                       "这个榜单暂时没抓到内容（站点可能抽风了）。"
                       "过一会儿再来看看，或者直接搜书名。"),
    }


@app.get("/api/ranks/status")
async def ranks_status():
    """榜单缓存的体检报告：每类几条、多久前抓的、过期几个。

    给「定时任务有没有在跑」一个可观测的口子 —— 出问题时能一眼看出
    是任务没执行，还是执行了但站点抓不到。
    """
    from . import ranks as _rk
    from . import sched as _sc
    return {"ok": True, "cache": _rk.cache_status(), "sched": _sc.status()}


@app.post("/api/ranks/refresh")
async def ranks_refresh(kind: str = "", force: bool = True):
    """立刻刷新榜单（默认全部 6 类）。定时任务和界面「立即刷新」都打这里。

    抓取是同步阻塞的，所以放线程池 —— 刷新期间别把读小说的请求卡住。
    """
    import asyncio

    from . import ranks as _rk

    ks = [k.strip() for k in kind.split(",") if k.strip()] if kind else None
    if ks and not set(ks) <= {d["kind"] for d in _rk.kinds()}:
        return JSONResponse({"ok": False, "error": "包含未知榜单"}, status_code=400)

    try:
        rep = await asyncio.to_thread(_rk.refresh, ks, force)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"刷新失败：{e}"}, status_code=502)
    return {"ok": True, **rep}


# ---------------------------------------------------------------------------
# 搜索（流式）
# ---------------------------------------------------------------------------
@app.get("/api/search")
async def search(kw: str = Query(..., min_length=1), sources: str = "",
                 sample: int = 1, probe: int = 1, discover: int = 1):
    """流式返回搜索结果（NDJSON，一行一个事件）。

    事件类型：
      item     搜到一条候选（先展示，让界面有内容）
      verified 该候选探测/校验完成（可用 / 不可用 / 章节数 / 正文抽样）
      step     某个来源在报步骤（目前是「联网发现」在用：正在搜索/核实/入库）
      done     搜索结束，附带按书聚合后的最终结果
      error    出错

    sources:  逗号分隔的来源名，留空=全部
    discover: 本地一条可读的都没有时，要不要联网出去找（默认开）
    """
    only = [s for s in sources.split(",") if s.strip()] or None
    _t0 = time.perf_counter()
    log_event(logger, "search.start", 书名=kw,
              指定来源=len(only) if only else "全部",
              抽样=bool(sample), 探测=bool(probe), 联网=bool(discover))

    async def gen():
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        # 客户端还在不在。用户关标签页 / 连点两次搜索把上一个请求顶掉时，
        # 这个会变 False —— 此时引擎已经没有人在听了。
        alive = threading.Event()
        alive.set()

        # ⚠ 为什么需要它：引擎跑在 `loop.run_in_executor` 的**线程池**里，
        #   而线程池任务**不会**因为客户端断开就停（run_in_executor 返回的
        #   future 我们没有 await，也就没人取消它）。于是用户一走了之之后，
        #   引擎仍会把整轮搜索跑完 —— 每个源照抓、每个候选照探测，
        #   白烧 CPU 和网络，还去撞来源站的限速配额。
        #   这是个**只有真机才会暴露**的问题：单测直接调引擎，永远看不到
        #   客户端断开这回事。
        #
        #   这里不做硬取消（引擎内部有自己的收手/超时逻辑，硬打断更危险），
        #   只做**止损**：断开后不再往队列里塞事件（没人在读），
        #   并且不再触发任何以 on_verified 为入口的回调。
        def push(obj):
            if not alive.is_set():
                return                      # 没人在读了，别攒队列
            try:
                loop.call_soon_threadsafe(queue.put_nowait, obj)
            except RuntimeError:
                # 事件循环已经关了（请求早结束）—— 静默丢弃，别把线程炸掉
                alive.clear()

        def on_verified(r):
            if not alive.is_set():
                return
            push({"type": "verified", "data": r.to_dict()})

        # ⚠ 引擎跑在 run_in_executor 的**线程池**里，而 request_id 存在
        # ContextVar 中 —— ContextVar 不跨线程传播，不手动接过去的话，
        # 引擎打的日志全是 req=----，"search.start" 和 "search.done" 之间
        # 那段最需要追的过程反而没有 id，等于白做。
        _req = get_request_id()

        def run():
            set_request_id(_req)
            # 客户端走了就别再探测了。
            #
            # ⚠ 这里踩过一个想当然的错误：我原以为「断开后 push() 丢了不就行」，
            #   但日志打脸 —— 断开后 search.done 照样出现、耗时 8.9s 一秒不少。
            #   因为 push() 只控制**事件发不发得出去**，而真正烧资源的是
            #   engine.search 内部的探测线程池：它压根不关心有没有人在听，
            #   非要抽到「已验过 3 本正文」才收手。
            #
            #   所以必须把"客户端还在不在"**传进去**，让它把收手条件换成
            #   alive —— 一旦没人听了就立刻停，别再花 6 秒去打来源站。
            def _dead() -> bool:
                return not alive.is_set()

            try:
                stats: dict = {}
                results = engine.search(
                    kw,
                    on_result=lambda r: push({"type": "item", "data": r.to_dict()}),
                    on_verified=on_verified,
                    on_progress=lambda title, detail, ok: push(
                        {"type": "step", "title": title, "detail": detail, "ok": bool(ok)}),
                    only=only,
                    stats=stats,
                    sample=bool(sample),
                    probe=bool(probe),
                    discover=bool(discover),
                    # 客户端断开 → 引擎立刻收手（见上面 _dead 的注释）
                    should_stop=_dead,
                )
                from .aggregate import group as group_books

                books = group_books(results)
                # 记搜索历史。**只记成书数**而不是原始候选数 ——
                # "搜了 X 出来 0 本"才是书库缺口的证据；候选里混着一堆
                # 沾边的噪声，拿它当 hits 会掩盖"其实一本能读的都没有"。
                try:
                    history.add_search(kw, hits=len(books))
                except Exception:  # noqa: BLE001
                    logger.exception("history.add_search 异常（已忽略）")
                log_event(logger, "search.done", 书名=kw, 候选=len(results),
                          成书=len(books),
                          可读=sum(1 for r in results if r.available),
                          联网发现=stats.get("discovered", 0),
                          # 这一轮是不是被"客户端断开"打断收手的。
                          # 打出来给断连止损测试当**确定性判据** ——
                          # 它不像耗时那样随源站快慢漂移（实测漂 5 倍），
                          # 只取决于机制本身该不该收手。
                          aborted=bool(stats.get("aborted")),
                          耗时ms=int((time.perf_counter() - _t0) * 1000))
                push({
                    "type": "done",
                    "count": len(books),
                    "candidates": len(results),
                    "available": sum(1 for r in results if r.available),
                    "ms": stats.get("ms", 0),
                    "discovered": stats.get("discovered", 0),
                    # 一条「确切命中」都没有 → 这批只是沾边，前端要如实说明。
                    "fuzzy": bool(books) and not any(b.get("tight") for b in books),
                    "stats": stats,
                    # 断开收手是否真的触发（引擎填的）。与上面 stats 里的同名字段
                    # 一份两处：这里提到顶层是为了让断连止损测试**不必去解析
                    # stats 的完整结构**，一眼就能读到。它是一条确定性的信号
                    # （只取决于"该不该收手"），不像耗时那样受源站快慢影响。
                    "aborted": bool(stats.get("aborted")),
                    "books": books,
                })
            except Exception as e:  # noqa: BLE001
                log_event(logger, "search.fail", logging.ERROR, 书名=kw,
                          原因=f"{type(e).__name__}: {e}",
                          耗时ms=int((time.perf_counter() - _t0) * 1000))
                logger.exception("搜索失败（详细堆栈）")
                push({"type": "error", "msg": str(e)})

        try:
            loop.run_in_executor(None, run)
            while True:
                item = await queue.get()
                yield json.dumps(item, ensure_ascii=False) + "\n"
                if item["type"] in ("done", "error"):
                    break
        except (GeneratorExit, asyncio.CancelledError):
            # 客户端断开时，生成器是被**关闭/取消**的。这里显式捕一下只是为了
            # 说明"断开是预期路径、不是错误"，真正干活的是下面的 finally。
            raise
        finally:
            # 无论是正常收尾还是客户端半路断开（GeneratorExit），
            # 都要把 alive 落下来 —— 断开的场景正是这个开关存在的理由。
            # 注意这里**不 join** 那个线程：它的收手逻辑靠自己的超时，
            # 硬等会把响应拖住；我们要的只是"别再往里塞东西"。
            #
            # ⚠⚠ 踩过一次「断断续续才生效」，根因是一个**启动顺序竞态**：
            #   原来 `run_in_executor(...)` 写在 `try:` **外面**。
            #   生成器是惰性的 —— `gen()` 被创建时一行都不跑，要等
            #   Starlette 第一次 `__anext__()` 才从头执行到第一个 yield。
            #   如果客户端在**第一个 yield 之前**（响应头都还没吐出去）
            #   就断了，生成器可能**从头到尾没被启动过** ——
            #   于是 finally 不执行、alive 永远是 set 状态，
            #   而 run() 已经在 executor 里跑起来了 → 照样把整轮跑完。
            #   表现就是同一个测试跑两次、一次通过一次失败。
            #   把 `run_in_executor` 挪进 try，保证「任务已提交」和
            #   「有 finally 兜底」是同一个 try 里的原子动作。
            alive.clear()

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# 来源库：联网发现攒下来的站点和书
# ---------------------------------------------------------------------------
@app.get("/api/registry")
async def registry_view():
    """来源库总览：攒了多少站、多少书，都有哪些。"""
    from . import registry

    return {
        "stats": registry.stats(),
        "sites": [
            {"host": h, "healthy": registry.is_healthy(s), "label": registry.site_label(h),
             "searchable": bool((s.get("search_tpl") or "").strip()), **s}
            for h, s in sorted(registry.sites().items(),
                               key=lambda kv: -int(kv[1].get("ok", 0)))
        ],
        "books": [
            {"url": u, "healthy": registry.is_book_healthy(b),
             "label": registry.site_label(b.get("host", "")), **b}
            for u, b in sorted(registry.books().items(),
                               key=lambda kv: -int(kv[1].get("last_ok", 0)))
        ],
    }


@app.get("/api/registry/faults")
async def registry_faults():
    """来源库「失败原因」报表 —— 排查坏源用，**只读，不清理**。

    为什么单独开一个口（而不是塞进 /api/registry）：
      /api/registry 是"总览"（攒了多少站/书），返回体已经很大；
      这里是**诊断视图**，只有真正要排查时才看，没必要每次总览都算一遍。

    两个列表的差别（这是本报表的全部价值）：
      · suspects（疑似坏源）：网络层失败多 → 站可能真的挂了，该清
      · victims（被冤枉的站）：失败多是"形态/搜不出/要登录"，
        而站本身还能成功 → 是**我们的模板/启发式**该修，别错怪站点
    两者混在一起时看不出区别，这正是以前 fail 混装桶的问题。
    """
    from . import registry

    rep = registry.site_fault_breakdown()
    return {
        "ok": True,
        "suspects": rep["suspects"],   # 疑似真的挂了
        "victims": rep["victims"],     # 被冤枉的（该修抓法，不该清站）
        "no_data": rep["no_data"],     # 分类之前的老记录，还没有 fail_* 数据
        "counts": {
            "suspects": len(rep["suspects"]),
            "victims": len(rep["victims"]),
            "sites": len(registry.sites()),
        },
    }


# ---------------------------------------------------------------------------
# 搜索历史 / 访客记录 —— 产品化的两个数据面板
# ---------------------------------------------------------------------------
# 为什么要开这两组接口（而不是"看日志就行"）：
#   日志是**给排障用的** —— 会轮转、会删、格式面向 grep。
#   「最近大家在搜什么」「今天有多少人来过」是**产品问题**，
#   需要一个稳定留存、可直接拿来渲染的结构化来源。
# 它们的共同点是**只读**（历史可删单条/清空，访客只能清空），
# 且**绝不影响主流程** —— 记录失败一律吞掉，不让搜索/访问跟着挂。
@app.get("/api/history/search")
async def history_search(limit: int = 20):
    """最近搜过的词（时间倒序）。前端搜索框的下拉提示用它。"""
    return {"ok": True, "items": history.get_recent(limit)}


@app.get("/api/history/search/hot")
async def history_search_hot(limit: int = 20):
    """热门搜索词（次数倒序）—— 「大家都在搜」用它。

    ⚠ 与 /api/history/search 是两个维度：那个是"最近"，这个是"最多"。
    两者都用同一个库，只是排序不同。
    """
    return {"ok": True, "items": history.get_hot(limit)}


@app.get("/api/history/search/stats")
async def history_search_stats():
    """搜索历史体检：共多少词、累计搜了多少次、有几个词一无所获。

    `empty_words` 是最有价值的一栏 —— 搜了却搜不到的书，
    直接指向书库的覆盖缺口。
    """
    return {"ok": True, **history.stats()}


@app.delete("/api/history/search")
async def history_search_clear(kw: str = ""):
    """删一个搜索词；**不给 kw 就清空全部**。

    为什么用**查询参数**而不是路径参数（`/api/history/search/{kw}`）：
      路径段里放不下斜杠。书名带斜杠非常常见（"哈利波特/魔法石"、
      "斗破苍穹/之万界商城"），而 `%2F` 编码在 Starlette 里会被
      解码成 `/` 去匹配路由 → 404。实测确认过：
      `/api/history/search/aaa%2Fbbb` 和 `/api/history/search/aa/bb`
      **都是 404**（前者编了码、后者没编）。
      查询参数没有这个限制，`?kw=a%2Fb` 能正确还原成 `a/b`。

    ⚠ 两个语义合并在一个路由上，是为了让"清空"和"删一条"共用同一处
      参数校验。但**务必注意**：不带 kw 就是**清空全部** —— 这是破坏性
      操作，前端必须走二次确认（sources.js 里已经包了 confirmBox）。
    """
    kw = (kw or "").strip()
    if kw:
        return {"ok": True, "deleted": history.delete(kw), "cleared": 0}
    return {"ok": True, "removed": history.clear(), "deleted": False}


@app.get("/api/visits")
async def visits_recent(limit: int = 50):
    """最近 N 条访问明细（谁在什么时候打开了哪个接口）。"""
    return {"ok": True, "items": visits.recent(limit)}


@app.get("/api/visits/stats")
async def visits_stats(days: int = 14):
    """访问汇总：今日/昨日 PV·UV、累计、以及最近 N 天趋势。"""
    return {"ok": True, **visits.stats(days)}


@app.delete("/api/visits")
async def visits_clear():
    """清空访客数据。"""
    return {"ok": True, "removed_days": visits.clear()}


@app.get("/api/registry/check")
async def registry_check(limit: int = 0):
    """给来源库做体检：把记下来的书重开一遍。

    只确认「目录页还能不能打开、章数还对不对」，不抓正文 ——
    体检要便宜，跑得起才有意义。失效的会被自动清理掉。
    """
    from . import discovery

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: discovery.health_check(limit=limit))


@app.post("/api/registry/prune")
async def registry_prune(all: int = 0):
    """清理来源库。all=1 清空整库（会先自动留一份 `.bak.json`）；默认只清不健康的。"""
    from . import registry

    return registry.prune(only_dead=not bool(all), confirm=True)


@app.post("/api/registry/learn")
async def registry_learn(host: str = "", limit: int = 0):
    """给来源库里的站点学「站内搜索接口」，让它们变成可搜源。

    这是 L 源自我壮大的入口 —— 学过之后，下次搜**别的**书就能直接
    拿关键词问这个站，不用再走搜索引擎。

    host 为空时：自动挑「还没学过、健康、且没反复失败」的站来学。
    limit 限制一次学几个（默认不限制）。
    """
    from . import discovery, registry

    if host:
        targets = [host]
    else:
        targets = [h for h, s in registry.sites().items() if registry.should_try_learn(h)]
    if limit:
        targets = targets[:limit]

    loop = asyncio.get_running_loop()
    rep = await loop.run_in_executor(
        None, lambda: discovery.learn_sites(targets))
    return {"ok": True, "targets": targets, **rep,
            "searchable": len(registry.searchable_sites())}


@app.delete("/api/registry/book")
async def registry_forget_book(url: str):
    from . import registry

    return {"ok": registry.forget_book(url)}


@app.delete("/api/registry/site")
async def registry_forget_site(host: str):
    from . import registry

    return {"ok": registry.forget_site(host)}


# ---------------------------------------------------------------------------
# 直接抓一个书页 URL（不经过搜索）
# ---------------------------------------------------------------------------
@app.post("/api/fetch-url")
async def fetch_url(req: AdaptReq):
    """给它一个书页地址，它自己看出来能不能抓、有多少章、正文读不读得到。

    这条是「我知道书在哪，直接抓」的入口 —— 和联网发现共用同一套
    通用启发式（`app/webfetch.py`）。

    认出目录之后会**再抽一章正文验一下**：用户粘地址过来，最想知道的就是
    「这里到底读不到得到」。不验的话，付费站（目录能开、正文要登录）会显示成
    「目录可达」，点进去一个字都没有 —— 那就是「显示能下载最后是假的」。
    """
    from . import webfetch
    from .sources.base import check_content_quality
    from .security import safe_public_url

    loop = asyncio.get_running_loop()
    ok, res = await loop.run_in_executor(None, safe_public_url, req.url)
    if not ok:
        return JSONResponse({"ok": False, "error": res}, status_code=400)

    def work():
        from .utils import fast_mode
        with fast_mode(retries=1, timeout=15.0):
            data = webfetch.analyze(req.url)
        # 目录页 → 抽第 2 章（第 1 章常是版权声明），判一下正文成色
        sample = {"sampled": False, "readable": False, "chars": 0, "note": ""}
        toc = data.get("toc") or []
        if data.get("kind") == "toc" and toc:
            idx = 1 if len(toc) > 2 else 0
            try:
                with fast_mode(retries=0, timeout=12.0):
                    html = webfetch.fetch_text(toc[idx]["url"])
                body = webfetch.clean_body(webfetch.extract_content(html))
                good, why = check_content_quality(body)
                sample = {"sampled": True, "readable": bool(good),
                          "chars": len(body), "note": "" if good else why}
            except Exception as e:  # noqa: BLE001
                sample = {"sampled": True, "readable": False, "chars": 0,
                          "note": f"正文抓不到（{type(e).__name__}）"}
        return data, sample

    try:
        data, sample = await loop.run_in_executor(None, work)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(e)[:120]}, status_code=200)

    if data.get("kind") == "toc":
        return {
            "ok": True, "kind": "toc", "url": req.url,
            "title": data.get("title", ""), "author": data.get("author", ""),
            "intro": data.get("intro", ""), "chapters": len(data.get("toc") or []),
            "sample": sample,
            "toc": (data.get("toc") or [])[:50],
        }
    if data.get("kind") == "chapter":
        return {
            "ok": True, "kind": "chapter", "url": req.url,
            "title": data.get("title", ""),
            "chars": len(data.get("content") or ""),
            "sample": sample,
            "sample_text": (data.get("content") or "")[:400],
        }
    return {"ok": False, "error": data.get("note") or "这个页面既没有目录也没有正文，可能不是小说页"}



@app.get("/api/sources/check")
async def check_sources():
    """并发探测各来源是否还能打开（小说站域名经常失效）。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, engine.check_sources)


# ---------------------------------------------------------------------------
# 预览
# ---------------------------------------------------------------------------
@app.post("/api/preview")
async def preview(req: BookReq):
    loop = asyncio.get_running_loop()
    res = BookResult(title=req.title, author=req.author, source=req.source,
                     url=req.url, intro=req.intro)
    try:
        return await loop.run_in_executor(
            None, lambda: engine.preview(res, chapter_index=req.chapter_index)
        )
    except Exception as e:  # noqa: BLE001
        logger.info("预览失败: %s", e)
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/chapter")
async def chapter(req: BookReq):
    loop = asyncio.get_running_loop()
    res = BookResult(title=req.title, author=req.author, source=req.source, url=req.url)
    try:
        return await loop.run_in_executor(
            None, lambda: engine.read_chapter(res, req.chapter_index or 1)
        )
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=400)


# ---------------------------------------------------------------------------
# 书架 / 阅读
# ---------------------------------------------------------------------------
def _meta_view(meta: dict) -> dict:
    """书架记录 + 缓存统计。"""
    bid = meta["id"]
    out = dict(meta)
    out["cached"] = engine.library.count_cached(bid)
    out["size"] = engine.library.chapters_dir_size(bid)
    out["has_toc"] = bool(engine.library.toc(bid))
    return out


@app.post("/api/shelve")
async def shelve(req: BookReq):
    """入书架：建记录 + 拉目录。阅读器靠这个立刻有目录可画。"""
    loop = asyncio.get_running_loop()
    res = BookResult(title=req.title, author=req.author, source=req.source,
                     url=req.url, intro=req.intro)
    try:
        meta = await loop.run_in_executor(None, lambda: engine.shelve(res))
    except Exception as e:  # noqa: BLE001
        logger.info("入书架失败: %s", e)
        return JSONResponse({"error": str(e)}, status_code=400)
    return _meta_view(meta)


@app.get("/api/library")
async def library_list():
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, engine.library.list_books)


@app.get("/api/library/stats")
async def library_stats():
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, engine.library.stats)


@app.get("/api/library/{bid}/toc")
async def library_toc(bid: str):
    if not valid_id(bid):
        return JSONResponse({"error": "bad id"}, status_code=400)
    loop = asyncio.get_running_loop()
    toc = await loop.run_in_executor(None, engine.library.toc, bid)
    return {"id": bid, "total": len(toc), "chapters": toc}


@app.get("/api/library/{bid}")
async def library_detail(bid: str):
    if not valid_id(bid):
        return JSONResponse({"error": "bad id"}, status_code=400)
    loop = asyncio.get_running_loop()
    meta = await loop.run_in_executor(None, engine.library.meta, bid)
    if not meta:
        return JSONResponse({"error": "书架里没有这本书"}, status_code=404)
    toc = await loop.run_in_executor(None, engine.library.toc, bid)
    view = await loop.run_in_executor(None, _meta_view, meta)
    view["chapters"] = toc
    view["total"] = len(toc) or view.get("total", 0)
    # 阅读器要靠这个把「哪些章已经缓存」在目录里标出来
    view["cached_list"] = sorted(await loop.run_in_executor(
        None, engine.library.cached_indexes, bid))
    return view


@app.get("/api/library/{bid}/chapter/{n}")
async def library_read(bid: str, n: int, fetch: int = 1, prefetch: int = 1):
    """读一章。命中缓存直接返回；没命中就联网补一章并写回缓存。"""
    if not valid_id(bid):
        return JSONResponse({"error": "bad id"}, status_code=400)
    loop = asyncio.get_running_loop()
    _t0 = time.perf_counter()
    try:
        data = await loop.run_in_executor(
            None, lambda: engine.library_chapter(bid, n, allow_fetch=bool(fetch))
        )
    except Exception as e:  # noqa: BLE001
        # 阅读页是最重要的页面 —— 它失败必须留下可追的记录，
        # 而且要能一眼分辨"缓存没有"还是"来源挂了"。
        log_event(logger, "read.fail", logging.WARNING, 书=bid, 章=n,
                  允许联网=bool(fetch), 原因=f"{type(e).__name__}: {e}")
        return JSONResponse({"error": str(e)}, status_code=400)
    try:
        _ms = (time.perf_counter() - _t0) * 1000
        # cached=True 才是真·磁盘命中；False 只说明"不是从缓存来的"，
        # 可能在等网络、也可能是"尚未缓存"的空壳。分开记，好定位。
        _hit = bool(data.get("cached"))
        _body = (data.get("content") or "").strip()
        log_event(logger, "read.fetch", 书=bid, 章=n,
                  来源=("缓存" if _hit else ("空" if not _body else "联网")),
                  字数=len(_body), ms=f"{_ms:.0f}")
    except Exception:  # noqa: BLE001
        pass
    if prefetch:
        _schedule_prefetch(bid, n)
    return data


def _schedule_prefetch(bid: str, from_index: int, ahead: int = 3) -> None:
    """后台预取接下来的几章 —— 用户翻页时就是秒出。

    只在「未缓存」时才排任务，并用 in-flight 集合去重，
    避免用户快速翻页时把同几章重复请求好几遍。

    ⚠ 这里踩过一个**队列积压**的坑，行为完全是反的：
    原先是「先登记 in-flight，再丢进池子排队」。看着没问题，但
    `_prefetch_pool` 只有 3 个 worker，而排队**不计入 in-flight 的去重逻辑** ——
    用户连翻 100 章（或按住下一章键），就登记 100 个 key、往队列里塞 100 个任务，
    真正并发执行的永远只有 3 个。
    后果：① 更要命的 —— 用户已经停在第 100 章了，队列里还排着第 8 章，
       worker 会把**远在身后**的章节一章章抓回来，占着网速和来源站的限速配额，
       「预取」变成了「补历史」，用户真正要的下一章反而排在队尾；
    ② 队列没有上限，翻一整本书就能堆出上千个待办任务，内存和连接都被拖住。

    正确做法：**满了就丢**。预取本来就是「锦上添花」—— 排不上队就不排，
    用户真翻到那一章时再同步抓，慢一点而已，绝不该反过来拖累当前阅读。
    """
    try:
        total = len(engine.library.toc(bid))
    except Exception:  # noqa: BLE001
        return
    for idx in range(from_index + 1, min(from_index + 1 + ahead, total + 1)):
        key = (bid, idx)
        with _prefetch_lock:
            # 队列里已经攒够待办了 → 不再接新的，直接放弃这次预取。
            # 判在再加锁之内，避免多个请求同时读到「还没满」而一起挤进去。
            if len(_prefetch_inflight) >= PREFETCH_MAX_INFLIGHT:
                logger.info(
                    "预取队列已满（%d 个待办），跳过 %s 第 %d 章 —— "
                    "不拖累当前阅读，用户翻到再同步抓",
                    len(_prefetch_inflight), bid, idx)
                return
            if key in _prefetch_inflight or engine.library.has_chapter(bid, idx):
                continue
            _prefetch_inflight.add(key)

        def job(k=key):
            try:
                # 用户可能已经把书移出书架了 —— 别再往回写文件
                if engine.library.exists(k[0]):
                    engine.library_chapter(k[0], k[1], allow_fetch=True)
            except Exception:  # noqa: BLE001
                pass
            finally:
                with _prefetch_lock:
                    _prefetch_inflight.discard(k)

        _prefetch_pool.submit(job)


@app.post("/api/library/{bid}/position")
async def library_position(bid: str, req: PositionReq):
    if not valid_id(bid):
        return JSONResponse({"error": "bad id"}, status_code=400)
    loop = asyncio.get_running_loop()
    meta = await loop.run_in_executor(
        None,
        lambda: engine.library.set_position(bid, req.index, req.percent, req.offset),
    )
    if not meta:
        return JSONResponse({"error": "书架里没有这本书"}, status_code=404)
    return {"ok": True, "position": meta.get("position")}


@app.delete("/api/library/{bid}")
async def library_delete(bid: str):
    if not valid_id(bid):
        return JSONResponse({"error": "bad id"}, status_code=400)
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, engine.remove_book, bid)
    return {"ok": ok}


@app.post("/api/library/{bid}/cache")
async def library_cache(bid: str, max_chapters: int | None = None):
    """后台把全书正文缓存进书架（带进度、可取消）。"""
    if not valid_id(bid):
        return JSONResponse({"error": "bad id"}, status_code=400)
    loop = asyncio.get_running_loop()
    meta = await loop.run_in_executor(None, engine.library.meta, bid)
    if not meta:
        return JSONResponse({"error": "书架里没有这本书"}, status_code=404)

    task_id = uuid.uuid4().hex[:12]
    ctl = threading.Event()
    # ⚠ 记下当前请求的 req= —— 缓存是 create_task 起的后台任务，
    # 而 ContextVar 不跨任务复制。不手动接过来的话，后台打的日志
    # 全是 req=----，等于"点缓存 → 报错"这条线还是断的。
    _req = get_request_id()
    _title = meta.get("title", "")
    with TASKS_LOCK:
        TASKS[task_id] = {
            "id": task_id, "kind": "cache", "library_id": bid,
            "title": meta.get("title", ""), "author": meta.get("author", ""),
            "source": meta.get("source_display", meta.get("source", "")),
            "status": "running", "msg": "准备缓存", "done": 0, "total": 0,
            "file": None, "error": None, "partial": False,
            "started": time.time(), "cancel": ctl,
        }
        _prune_tasks()

    def progress(done, total, msg):
        with TASKS_LOCK:
            t = TASKS.get(task_id)
            if t:
                t.update(done=done, total=total, msg=f"第 {done}/{total} 章：{msg}")

    async def run():
        set_request_id(_req)
        _t0 = time.perf_counter()
        log_event(logger, "cache.start", 书=_title, 限章=max_chapters or "全书")
        try:
            res = await loop.run_in_executor(
                None,
                lambda: engine.cache_book(bid, progress=progress, stop=ctl.is_set,
                                          limit=max_chapters),
            )
            if ctl.is_set():
                raise Cancelled()
            log_event(logger, "cache.done", 书=_title,
                      成功章=res["valid"], 总章=res["total"],
                      耗时s=round(time.perf_counter() - _t0, 1))
            _finish_task(task_id, status="done",
                         msg=f"缓存完成：{res['valid']}/{res['total']} 章",
                         done=res["total"], total=res["total"] or 1,
                         partial=res["valid"] < res["total"])
        except Cancelled:
            log_event(logger, "cache.cancel", 书=_title)
            _finish_task(task_id, status="cancelled", msg="已取消缓存")
        except SourceBlocked as e:
            log_event(logger, "cache.fail", logging.WARNING, 书=_title, 原因=f"来源拦截: {e}")
            _finish_task(task_id, status="error", msg=str(e), error=str(e))
        except Exception as e:  # noqa: BLE001
            log_event(logger, "cache.fail", logging.ERROR, 书=_title,
                      原因=f"{type(e).__name__}: {e}")
            logger.exception("缓存失败（详细堆栈）")
            _finish_task(task_id, status="error", msg=str(e), error=str(e))

    asyncio.create_task(run())
    return {"task_id": task_id}


# ---------------------------------------------------------------------------
# 下载 / 导出
# ---------------------------------------------------------------------------
@app.post("/api/download")
async def download(req: DownloadReq):
    """创建导出任务（txt / epub / html），返回 task_id。"""
    task_id = uuid.uuid4().hex[:12]
    ctl = threading.Event()
    fmt = (req.fmt or "txt").lower()
    if fmt not in ("txt", "epub", "html"):
        fmt = "txt"
    with TASKS_LOCK:
        TASKS[task_id] = {
            "id": task_id, "kind": "download",
            "title": req.title or req.keyword,
            "author": req.author,
            "source": req.source,
            "fmt": fmt,
            "status": "running", "msg": "准备中", "done": 0, "total": 0,
            "file": None, "error": None, "partial": False,
            "started": time.time(), "cancel": ctl,
        }
        _prune_tasks()

    _req = get_request_id()
    _job = f"{req.title or req.keyword}"

    def progress(done, total, msg):
        with TASKS_LOCK:
            t = TASKS.get(task_id)
            if t:
                t.update(done=done, total=total, msg=f"第 {done}/{total} 章：{msg}")

    async def run():
        set_request_id(_req)
        _t0 = time.perf_counter()
        log_event(logger, "export.start", 书=_job, 格式=fmt,
                  来源=req.source or "自动")
        loop = asyncio.get_running_loop()
        try:
            lim = req.max_chapters or None
            book = None

            # 1) 书架里已经缓存过 —— 直接从本地拼，不走网络
            if req.library_id and valid_id(req.library_id):
                book = await loop.run_in_executor(
                    None, lambda: _book_from_library(req.library_id, lim)
                )
                if not book.chapters:
                    book = None

            # 2) 否则现抓
            if book is None:
                if req.source and req.url:
                    res = BookResult(title=req.title or req.keyword, author=req.author,
                                     source=req.source, url=req.url, intro=req.intro)
                    book = await loop.run_in_executor(
                        None,
                        lambda: engine.download(res, progress=progress, limit=lim,
                                                stop=ctl.is_set),
                    )
                else:
                    book = await loop.run_in_executor(
                        None,
                        lambda: engine.download_best(req.keyword, progress=progress,
                                                     limit=lim, stop=ctl.is_set),
                    )

            if ctl.is_set():
                raise Cancelled()

            valid = sum(1 for c in book.chapters if c.content.strip())
            if valid == 0:
                raise RuntimeError(
                    "一章正文都没抓到 —— 来源可能临时限流了，等几分钟再试，"
                    "或者换一个来源（点「试读」能先确认内容是否正常）"
                )

            path = await loop.run_in_executor(None, lambda: export_book(book, fmt))
            total = len(book.chapters)
            msg = f"完成：{book.title}（{valid} 章 · {fmt.upper()}）"
            if valid < total:
                msg += f"｜注意：目录共 {total} 章，有 {total - valid} 章没取到正文"
            log_event(logger, "export.done", 书=book.title, 格式=fmt,
                      有效章=valid, 总章=total,
                      大小KB=round(path.stat().st_size / 1024) if path.exists() else 0,
                      耗时s=round(time.perf_counter() - _t0, 1))
            _finish_task(task_id, status="done", msg=msg, file=path.name,
                         done=total, total=total or 1, partial=valid < total)
        except Cancelled:
            log_event(logger, "export.cancel", 书=_job)
            _finish_task(task_id, status="cancelled", msg="已取消下载")
        except Exception as e:  # noqa: BLE001
            log_event(logger, "export.fail", logging.ERROR, 书=_job, 格式=fmt,
                      原因=f"{type(e).__name__}: {e}",
                      耗时s=round(time.perf_counter() - _t0, 1))
            logger.exception("下载失败（详细堆栈）")
            _finish_task(task_id, status="error", msg=str(e), error=str(e))

    asyncio.create_task(run())
    return {"task_id": task_id}


def _book_from_library(bid: str, limit: int | None = None) -> Book:
    """用书架里已缓存的章节拼一本书（不联网）。"""
    meta = engine.library.meta(bid)
    if not meta:
        raise RuntimeError("书架里没有这本书")
    toc = engine.library.toc(bid)
    book = Book(title=meta.get("title", ""), author=meta.get("author", ""),
                source=meta.get("source_display") or meta.get("source", ""),
                url=meta.get("url", ""), intro=meta.get("intro", ""))
    for entry in toc:
        if limit and entry["index"] > limit:
            break
        ch = engine.library.chapter(bid, entry["index"])
        if ch:
            book.chapters.append(Chapter(index=ch["index"], title=ch["title"],
                                         content=ch.get("content", ""), url=ch.get("url", "")))
    return book


@app.post("/api/cancel/{task_id}")
async def cancel(task_id: str):
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return JSONResponse({"error": "任务不存在"}, status_code=404)
        ctl: threading.Event = t["cancel"]
        ctl.set()
        if t["status"] == "running":
            t["status"] = "cancelling"
            t["msg"] = "正在取消…"
    return {"ok": True}


@app.get("/api/progress/{task_id}")
async def progress(task_id: str):
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return {"status": "unknown"}
        return {k: v for k, v in t.items() if k != "cancel"}


@app.get("/api/tasks")
async def tasks():
    with TASKS_LOCK:
        items = [{k: v for k, v in t.items() if k != "cancel"} for t in TASKS.values()]
    return sorted(items, key=lambda t: -t["started"])


@app.post("/api/forget/{task_id}")
async def forget(task_id: str):
    """把一条**已结束**的任务从列表里去掉。

    还在跑的不让删 —— 那样会让用户以为任务被取消了，实际后台还在下载。
    """
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return {"ok": False, "note": "任务不存在"}
        if t["status"] not in ("done", "error", "cancelled"):
            return JSONResponse({"error": "任务还在进行中，请先取消"}, status_code=400)
        TASKS.pop(task_id, None)
    return {"ok": True}


def _prune_tasks():
    """只保留最近 N 个已结束的任务（调用方需持有 TASKS_LOCK）。"""
    if len(TASKS) <= MAX_TASKS_KEPT:
        return
    finished = [t for t in TASKS.values()
                if t["status"] in ("done", "error", "cancelled")]
    finished.sort(key=lambda t: t["started"])
    for t in finished[: max(0, len(TASKS) - MAX_TASKS_KEPT)]:
        TASKS.pop(t["id"], None)


def _finish_task(task_id: str, **fields) -> None:
    """把任务写成终态。**任务可能已经不在字典里了**，所以不能直接下标。

    ⚠ 为什么必须用 .get()：三个入口都会把任务从 TASKS 里拿掉 ——
      · `_prune_tasks()`（超过 MAX_TASKS_KEPT 时淘汰最老的已结束任务）
      · `DELETE /api/tasks/<id>`（用户在前端点「清空已完成」）
      · `/api/forget/<id>`（前端「移除这条记录」）
    而任务体是**后台 asyncio 任务**，它可能还在跑（大书缓存几分钟）。
    这三种情况下 `TASKS[task_id]` 都会 **KeyError** —— 而这个 except 分支
    本身就在处理异常，抛出去会被 asyncio 记成 "Task exception was never
    retrieved"，日志里一堆看不懂的堆栈，用户在界面上看到的却是"进度条卡住"。
    丢一次终态写入无害（那行记录本来就没了），但不能让它把任务体炸掉。
    """
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if t is None:
            return      # 已经被清掉了，没有可写的地方 —— 正常，不算错误
        t.update(**fields)


# ---------------------------------------------------------------------------
# 文件
# ---------------------------------------------------------------------------
_MIME = {
    ".txt": "text/plain; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".epub": "application/epub+zip",
}


@app.get("/api/downloads")
async def downloads():
    if not DOWNLOAD_DIR.exists():
        return []
    files = [p for p in DOWNLOAD_DIR.iterdir()
             if p.is_file() and p.suffix.lower() in _MIME]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {"name": p.name, "size": p.stat().st_size,
         "mtime": int(p.stat().st_mtime), "ext": p.suffix.lower().lstrip(".")}
        for p in files
    ]


def _safe_path(name: str) -> Path | None:
    """把文件名安全地解析到 downloads 目录内（防目录穿越）。"""
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return None
    path = (DOWNLOAD_DIR / name).resolve()
    try:
        path.relative_to(DOWNLOAD_DIR.resolve())
    except ValueError:
        return None
    return path


@app.get("/api/file/{name}")
async def get_file(name: str):
    path = _safe_path(name)
    if path is None or not path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    mime = _MIME.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, filename=name, media_type=mime)


@app.get("/api/cover")
async def get_cover(u: str = ""):
    """把来源站的封面图**代理**回来。

    ⚠ 为什么不能在前端直接 <img src="外站封面">：
      ① 小说站基本都有 Referer 防盗链，浏览器直连一律 403，图全裂；
      ② 等于让用户的浏览器去连几十个陌生站，把 IP 和访问记录送出去。
    所以由服务端带正确 Referer 去取，取回来的字节缓存到磁盘，之后直接吐。

    安全：`assert_public_url` 挡 SSRF（.local / 内网 IP / 云元数据地址），
    content-type 必须是 image/*，体积上限 8MB —— 防止有人拿这个接口
    当「任意 URL 转发器」去探测内网。
    """
    from .security import BlockedURL, assert_public_url

    u = (u or "").strip()
    if not u:
        return JSONResponse({"error": "no url"}, status_code=400)

    # 缓存键用 URL 的哈希 —— 避免把 URL 里的怪字符写进文件名
    key = hashlib.sha256(u.encode("utf-8")).hexdigest()[:32]
    ext = ".img"
    cache_dir = COVER_CACHE_DIR
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass

    # 命中磁盘缓存：直接吐，连 URL 校验都不用做（我们自己存下来的）
    for cand_ext in (".jpg", ".png", ".gif", ".webp", ".img"):
        cp = cache_dir / f"{key}{cand_ext}"
        if cp.exists() and cp.stat().st_size > 0:
            return FileResponse(cp, media_type=_cover_mime(cand_ext),
                                headers={"Cache-Control": "public, max-age=604800"})

    try:
        safe_u = assert_public_url(u)
    except BlockedURL as e:
        log_event(logger, "cover.blocked", logging.WARNING, 地址=u[:120], 原因=str(e))
        return JSONResponse({"error": str(e)}, status_code=400)

    def _grab() -> tuple[bytes, str] | None:
        from .utils import DEFAULT_HEADERS, get_client, host_of
        h = dict(DEFAULT_HEADERS)
        # 带 Referer 骗过防盗链 —— 取值用图片自己所在的站点根，
        # 和「在浏览器里从那个页面看图」的效果一致。
        host = host_of(safe_u)
        if host:
            h["Referer"] = f"https://{host}/"
        h["Accept"] = "image/avif,image/webp,image/*,*/*;q=0.8"
        r = get_client().get(safe_u, headers=h, timeout=8, follow_redirects=True)
        if r.status_code != 200:
            return None
        ct = (r.headers.get("content-type") or "").lower()
        if not ct.startswith("image/"):
            return None  # 不是图片：多半是防盗链页面 / 404 页
        body = r.content
        if not body or len(body) > 8 * 1024 * 1024:
            return None
        return body, ct

    try:
        loop = asyncio.get_running_loop()
        got = await loop.run_in_executor(None, _grab)
    except Exception as e:  # noqa: BLE001
        log_event(logger, "cover.fail", logging.WARNING, 地址=u[:120],
                  原因=f"{type(e).__name__}: {e}")
        return JSONResponse({"error": "fetch failed"}, status_code=502)

    if not got:
        log_event(logger, "cover.fail", logging.WARNING, 地址=u[:120], 原因="不是图片或取不到")
        return JSONResponse({"error": "not an image"}, status_code=404)

    body, ct = got
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
           "image/webp": ".webp"}.get(ct.split(";")[0].strip(), ".img")
    try:
        (cache_dir / f"{key}{ext}").write_bytes(body)
    except Exception:  # noqa: BLE001
        pass

    from fastapi.responses import Response
    return Response(content=body, media_type=ct,
                    headers={"Cache-Control": "public, max-age=604800"})


def _cover_mime(ext: str) -> str:
    return {".jpg": "image/jpeg", ".png": "image/png",
            ".gif": "image/gif", ".webp": "image/webp"}.get(ext, "image/jpeg")


@app.get("/api/read/{name}")
async def read_file(name: str, offset: int = 0, limit: int = 20000):
    """在线读一段文件内容（给页面上的「试读」用）。

    ⚠ 以前是 `path.read_text()` **整个文件读进内存**再切片 —— 试读只要 2 万字符，
    却先把整本书（几 MB，UTF-8 中文一字 3 字节）拉进内存；更要命的是它是
    async 路由，`read_text` 是同步阻塞调用，直接卡在事件循环上 ——
    一本 20MB 的 txt 能让**整个服务**停住几百毫秒，其它请求全排队。
    （用户下载整本书的正文都在这儿，20MB 不是极端情况。）

    现在：按**字节**窗口读 + 增量解码。中文一个字 3 字节，所以字节窗口
    取 limit 的 3 倍再多留 64 字节余量，保证够凑出 limit 个字符；
    `errors="ignore"` 让窗口边界切在半个汉字上时丢掉那个残字而不是报错。
    真实文件远比窗口大时 `total` 拿精确值（stat 一下就有，不用读内容）。
    """
    path = _safe_path(name)
    if path is None or not path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)

    limit = max(0, min(int(limit), 200_000))
    offset = max(0, int(offset))

    # 中文 UTF-8 一字最多 3 字节；多读 64 字节兜住窗口边界
    win = limit * 3 + 64
    with path.open("rb") as f:
        f.seek(offset)
        raw = f.read(win)
    chunk = raw.decode("utf-8", errors="ignore")
    # 按**字符**截断到 limit（上面按字节读的窗口通常比 limit 长一点点）
    chunk = chunk[:limit]

    # total 用字节数近似「字符数上限」，只在文件确实大于窗口时才可能不准 ——
    # 而那种情况下前端本来也是「还有更多，继续翻」，不需要精确总数。
    try:
        if offset + len(raw) < path.stat().st_size:
            total = None  # 未知精确值：让前端按 has_more 判断
        else:
            total = offset + len(chunk)
    except OSError:
        total = offset + len(chunk)

    return {
        "name": name,
        "total": total,
        "offset": offset,
        "next": offset + len(raw),
        "has_more": len(raw) >= win - 64 and bool(raw),
        "content": chunk,
    }


@app.delete("/api/file/{name}")
async def delete_file(name: str):
    path = _safe_path(name)
    if path is None or not path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    path.unlink()
    logger.info("已删除文件: %s", name)
    return {"ok": True, "name": name}


# ---------------------------------------------------------------------------
# 杂项
# ---------------------------------------------------------------------------
@app.post("/api/cache/clear")
async def clear_cache():
    from .utils import cache_clear as _cc
    from .utils import cooldown_clear, cooldowns

    n = _cc()
    left = cooldowns()
    cooldown_clear()
    return {"cleared": n, "cooldowns_cleared": len(left)}


# ---------------------------------------------------------------------------
# 前端埋点回传
# ---------------------------------------------------------------------------
class UiLogReq(BaseModel):
    """浏览器里发生的事，回传到服务端日志 —— 让「用户报的 bug」能对着日志查。"""
    event: str = ""
    message: str = ""
    stack: str = ""
    url: str = ""
    ua: str = ""
    extra: str = ""


# 为什么需要这个端点：
#   后端日志再全，也照不到「点了没反应」「页面白屏」「按钮卡死」这类
#   **只发生在用户浏览器里**的问题 —— 而那恰恰是用户最容易来报的 bug。
#   原来前端一个错误都不上报，线上出问题只能靠猜。现在 JS 报错、
#   Promise 拒绝、接口失败都会带着路径和堆栈落进 logs/app.log，
#   `grep 'ui.error' logs/app.log` 就能捞出来。
#
# 为什么不用 WARNING 而用 ERROR：这是**真出事了**才上报的（不是常规噪音），
#   用 ERROR 让它在日志里显眼，也方便按级别筛。
@app.post("/api/log")
async def ui_log(req: UiLogReq):
    ev = (req.event or "ui.error").strip()
    # 白名单：只接受登记过的 ui.* 事件，避免被外部刷出乱七八糟的"事件名"污染日志
    if ev not in ("ui.error", "ui.reject", "ui.api.fail", "ui.slow"):
        ev = "ui.error"

    lv = logging.WARNING if ev == "ui.slow" else logging.ERROR
    log_event(
        logger, ev, lv,
        消息=(req.message or "")[:300],
        页面=(req.url or "")[:200],
        堆栈=(req.stack or "")[:600],
        客户端=(req.ua or "")[:160],
        附加=(req.extra or "")[:160],
    )
    return {"ok": True}


class _NoCacheCode(StaticFiles):
    """静态资源：代码类（.js / .css）必须**每次回源校验**。

    为什么需要它（2026-10-14 真实踩到）：
      `/` 会给 HTML 里的引用拼上版本号（`main.js?v=1791…`），但前端是
      **原生 ES module** —— 模块之间的 `import "./art.js"` 是**裸路径**，
      拿不到 `?v=`。于是 `art.js` 用的是"没有 Cache-Control"的默认策略，
      浏览器按 `Last-Modified` 走**启发式缓存**（约 10% 的年龄，且每次
      304 命中后还会"续期"），结果就是：**我们把首页轮换池修好了，
      用户手机上还在跑旧逻辑**，看到的还是一对"两个噜噜"的图。
      这一坑的可怕之处是"服务器上明明是新的" —— 只查线上会以为没问题。

    做法：对 .js/.css 回 `no-cache, must-revalidate`。
      `no-cache` 不是"不缓存"，而是"用之前必须先问一句" ——
      配合 ETag，文件没变就回 304，几乎不费流量；变了立刻拿到新的。
      图片/字体不在此列：它们体积大、且换素材时会换文件名，长缓存更划算。
    """

    async def get_response(self, path: str, scope):
        resp = await super().get_response(path, scope)
        if resp.status_code == 200 and path.endswith((".js", ".css")):
            resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp


app.mount("/static", _NoCacheCode(directory=STATIC_DIR), name="static")


def local_ip() -> str:
    """本机局域网地址。实现在 netinfo 里（和防火墙检测放一起，见那个模块的注释）。"""
    from .netinfo import lan_ip

    return lan_ip()
