"""HTTP 客户端复用回归 —— 切换 verify 时必须关掉旧的连接池。

为什么值得单独测
----------------
`fetch_text` 遇到自签证书会**降级重试**（`verify=False`），于是全局
`get_client()` 的 verify 会在 True/False 之间来回翻转。

原实现：「verify 不一样就 new 一个，旧对象直接丢掉」——
旧 client 的**连接池没关**，底层 socket 只能等 GC。

后果（真实且难查）：多站轮询 + 频繁 TLS 降级时（自签小站正是本项目的
主要目标），会累积大量半开 / TIME_WAIT 连接，最终表现成
「服务跑一段时间后所有请求都超时」。这种症状**极难反推**到
"某次 verify 翻转丢了个 client"。

测试手法
--------
`httpx.Client.close()` 会把内部状态置为已关闭（`_state == CLOSED`）。
所以只要拿到旧对象的引用，就能断言它**真的被关了** ——
这比数 socket 数量稳定得多。

用法： python tools/test_http_client.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


def closed(cli) -> bool:
    """这个 httpx.Client 是不是已经关闭了？"""
    try:
        # httpx 内部状态机：关闭后 _state 是 CLOSED
        st = getattr(cli, "_state", None)
        name = getattr(st, "name", str(st))
        return name.upper() == "CLOSED"
    except Exception:  # noqa: BLE001
        return False


print("=" * 62)
print("HTTP 客户端复用回归（verify 切换要关旧连接池）")
print("=" * 62)

# 全程别碰真实网络，也尽量别用系统代理
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)

print("\n[1] 同一个 verify 多次调用 → 复用同一个 client")
try:
    a = U.get_client(use_proxy=False, verify=True)
    b = U.get_client(use_proxy=False, verify=True)
    check(a is b, "同参数两次调用返回同一对象（真的在复用，没每次 new）")
except Exception as e:  # noqa: BLE001
    check(False, "拿到 client", f"{type(e).__name__}: {e}")
    a = b = None

print("\n[2] 切换 verify → 旧 client 必须被 close")
# 注意：必须先拿到旧对象引用再切 —— 切换后全局变量就指向新的了
old = U.get_client(use_proxy=False, verify=True)
check(not closed(old), "切换前旧 client 是活的")
new = U.get_client(use_proxy=False, verify=False)
check(new is not old, "verify 变了 → 换了对象（预期行为）")
check(closed(old), "★ 旧 client 被 close 了（不是丢给 GC）",
      "旧连接池没关 —— socket 会累积，最终表现为『跑一阵就全超时』")
check(not closed(new), "新 client 是活的")

print("\n[3] 再切回来 → 又换一个，且上一个也被关")
mid = U.get_client(use_proxy=False, verify=True)
check(mid is not new, "verify 又变了 → 再换对象")
check(closed(new), "★ 上一个（verify=False 那个）也被 close 了")

print("\n[4] 有代理 / 无代理 两条通道互不干扰")
# 无代理那条刚用过；这里切到"有代理"通道，不该把无代理的关掉
nop = U.get_client(use_proxy=False, verify=True)
prox = U.get_client(use_proxy=True, verify=True)
check(prox is not nop, "两条通道是两个不同对象")
check(not closed(nop), "拿到有代理 client 时，无代理那个**没有**被误关")
check(not closed(prox), "有代理 client 是活的")

print("\n[5] 连翻多次 verify 不留活口（模拟反复 TLS 降级）")
alive = []
cur = U.get_client(use_proxy=False, verify=True)
for i in range(8):
    nxt = U.get_client(use_proxy=False, verify=bool(i % 2))
    if nxt is not cur:
        alive.append((cur, closed(cur)))
    cur = nxt
leaked = [c for c, is_closed in alive if not is_closed]
check(not leaked, f"反复翻转 8 次后没有泄漏的 client（检了 {len(alive)} 次切换）",
      f"有 {len(leaked)} 个没关")

print()
if FAILS:
    print(f"❌ {len(FAILS)} 项未通过：")
    for f in FAILS:
        print(f"   - {f}")
    sys.exit(1)
print(f"✅ 全部通过（{OK} 项）")
