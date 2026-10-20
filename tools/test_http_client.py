# -*- coding: utf-8 -*-
"""HTTP 客户端复用回归 —— **切换 verify 时绝不能关掉别的线程正在用的 client**。

为什么值得单独测
----------------
`fetch_text` 遇到自签证书会**降级重试**（`verify=False`），于是 `get_client()`
的 verify 参数会在 True/False 之间来回翻转。而搜索是**并发的**
（扇出 7 个源、探测 6 个候选同时跑）。

旧实现「切换 verify 时 close 掉旧 client」，在单线程下看着很对（还顺手解决了
"旧连接池没关、socket 累积"），但它有个致命副作用：

    一个自签证书的小站触发 TLS 降级 → 把同一瞬间**别的线程正在用的
    client 关掉** → 那些请求报
        RuntimeError: Cannot send a request, as the client has been closed.

线上实证（2026-10-21 02:54，搜《斗破苍穹》）——两个**不同的源**在同一秒报这个错：

    verify.fail 源=www_xbiquge_info 原因="抓取失败: … (Cannot send a request"
    verify.fail 源=web              原因="抓取失败: … (Cannot send a request"

用户侧看到的是"这本书目录打不开 / 0 章"，而且是**随机**的：取决于那一刻
有没有别的线程恰好撞上降级。跨请求互相搞死，极难复现。

所以判据从「旧 client 有没有被关」改成 **「别人的 client 还活着吗 / 还能发请求吗」**
—— 前者只是机制，后者才是用户能感知的结果。**别把机制当规格写进测试**
（这正是本文件上一版犯的错：它专门断言"旧 client 被 close 了"，
等于把 bug 钉成了需求）。

用法： python tools/test_http_client.py
"""
from __future__ import annotations

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app import utils as U  # noqa: E402

FAILS: list[str] = []
OK = 0


def check(cond, label: str, extra: str = "") -> None:
    global OK
    if cond:
        OK += 1
        print(f"  ✓ {label}")
    else:
        FAILS.append(label)
        print(f"  ✗ {label}  {extra}")


print("=" * 62)
print("HTTP 客户端复用回归（切换 verify 不许关别人的 client）")
print("=" * 62)

# 全程别碰真实网络，也尽量别用系统代理
for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
          "all_proxy", "ALL_PROXY"):
    os.environ.pop(k, None)

print("\n[1] 同一个 (代理, 校验) 组合 → 复用同一个 client")
a = U.get_client(use_proxy=False, verify=True)
b = U.get_client(use_proxy=False, verify=True)
check(a is b, "同参数两次调用返回同一对象（真的在复用，没每次 new）")

print("\n[2] ★ 切到 verify=False，严格那个**必须还活着**")
strict = U.get_client(use_proxy=False, verify=True)
loose = U.get_client(use_proxy=False, verify=False)
check(loose is not strict, "两种 verify 是两个不同对象（各用各的连接池）")
check(not strict.is_closed,
      "★ 切 verify 后，原来那个 client 仍然可用（没被关掉）",
      "被关了 —— 并发时别的线程会报 "
      "『Cannot send a request, as the client has been closed』")

print("\n[3] 切回来还是同一个严格 client（不是又造一个）")
again = U.get_client(use_proxy=False, verify=True)
check(again is strict, "切回 verify=True 拿到的是原来那个对象")
check(not again.is_closed, "它仍然活着")
check(not loose.is_closed, "降级那个也仍然活着（两个槽位各自独立）")

print("\n[4] 有代理 / 无代理 两条通道互不干扰")
nop = U.get_client(use_proxy=False, verify=True)
prox = U.get_client(use_proxy=True, verify=True)
check(prox is not nop, "两条通道是两个不同对象")
check(not nop.is_closed, "拿到有代理 client 时，无代理那个**没有**被误关")
check(not prox.is_closed, "有代理 client 是活的")

print("\n[5] 反复翻转 verify 也不泄漏（槽位固定，不随调用次数增长）")
# 旧的泄漏问题是"socket 累积"，新实现靠**槽位数固定**解决 ——
# 所以判据是「对象总数有上限」，而不是「旧对象被关掉」。
U.close_clients()
seen = set()
for i in range(20):
    cur = U.get_client(use_proxy=bool(i % 2), verify=bool((i // 2) % 2))
    seen.add(id(cur))
check(len(seen) <= 4, f"翻转 20 次只产生了 {len(seen)} 个 client（上限 4）",
      f"产生了 {len(seen)} 个 —— 槽位没复用，会累积 socket")
check(all(not c.is_closed for c in U._clients.values()),
      "四个槽位都用着、都没被关")

print("\n[6] 槽位里躺着一个已关闭的 client → 必须重建，不能把死的递出去")
# 场景：外部代码（或某个库的清理逻辑、或一次 close_clients 之后残留）
# 把槽位里的 client 关掉了。这时候再要，必须给一个能用的。
# 直接把死对象递出去的话，用户侧看到的是 `Cannot send a request,
# as the client has been closed.` —— 和本轮修的那个事故是同一个症状。
dead = U.get_client(use_proxy=False, verify=True)
dead.close()
revived = U.get_client(use_proxy=False, verify=True)
check(revived is not dead, "已关闭的 client 不再被复用（换了一个新的）")
check(not revived.is_closed, "递出去的是能用的 client")

print("\n[7] ★ 并发实证：一个线程降级，另一个线程的请求不许失败")
# 这条才是用户能感知的那一面：用 MockTransport 让"发请求"变成纯本地动作，
# 于是在不联网的前提下，真的走一遍 httpx 的 send 路径。
orig_make = U._make_client


def _mock_make(*, verify: bool, use_proxy: bool):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    return httpx.Client(transport=httpx.MockTransport(handler), verify=verify,
                        trust_env=False)


U.close_clients()
U._make_client = _mock_make
try:
    strict2 = U.get_client(use_proxy=False, verify=True)
    check(strict2.get("http://a.invalid/").text == "ok", "严格 client 能正常请求")

    err: list[str] = []

    def _worker():
        try:
            # 模拟"另一个线程撞上自签站 → 触发 TLS 降级"
            t = threading.Thread(
                target=lambda: U.get_client(use_proxy=False, verify=False))
            t.start()
            t.join()
            # 降级发生之后，这个线程继续用自己手里的 client 发请求
            strict2.get("http://a.invalid/")
        except Exception as e:  # noqa: BLE001
            err.append(f"{type(e).__name__}: {e}")

    th = threading.Thread(target=_worker)
    th.start()
    th.join()
    check(not err, "另一个线程降级后，本线程的请求照常成功（不再被跨线程关死）",
          str(err))
finally:
    U._make_client = orig_make
    U.close_clients()

print()
if FAILS:
    print(f"❌ {len(FAILS)} 项未通过：")
    for f in FAILS:
        print(f"   - {f}")
    sys.exit(1)
print(f"✅ 全部通过（{OK} 项）")
