"""TLS 校验策略测试：默认严格 + 证书错误才降级（且只降一次）。"""
from __future__ import annotations

import os
import ssl
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import utils  # noqa: E402

FAILS: list[str] = []


def check(name: str, got, want, label: str = "") -> None:
    if got != want:
        FAILS.append(f"{name}: {label} 期望 {want!r} 实际 {got!r}")
        print(f"  ✗ {name}  {label}  期望 {want!r} 实际 {got!r}")
    else:
        print(f"  ✓ {name}  {label}  {got!r}")


print("\n[E] TLS 校验 —— 默认严格，证书错误才降级")

# 1) 证书类异常必须被识别
try:
    raise ssl.SSLCertVerificationError("certificate verify failed: self-signed certificate")
except Exception as e:  # noqa: BLE001
    check("_cert_error", utils._cert_error(e), True, "SSLCertVerificationError 应判定为可降级")

# 2) 包在别的异常里（chain）也要认得出来
try:
    try:
        raise ssl.SSLError("hostname mismatch")
    except Exception as inner:  # noqa: BLE001
        raise RuntimeError("抓取失败") from inner
except Exception as e:  # noqa: BLE001
    check("_cert_error", utils._cert_error(e), True, "__cause__ 链上的证书错也要认出")

# 3) 网络抖动**不能**被误判成证书问题（否则会偷偷关掉校验）
check("_cert_error", utils._cert_error(TimeoutError("timed out")), False, "超时不是证书问题")
check("_cert_error", utils._cert_error(ConnectionResetError("reset by peer")), False,
      "连接重置不是证书问题")
check("_cert_error", utils._cert_error(ValueError("HTTP 404")), False, "HTTP 错误不是证书问题")

# 4) 默认 client 必须开启校验
c = utils.get_client(use_proxy=False)
check("get_client", c.__dict__.get("_nb_verify"), True, "默认 client 校验开启")
check("get_client", utils._client_no_proxy.__dict__.get("_nb_verify"), True,
      "无代理 client 校验开启")

# 5) 请求降级 → 拿到的是另一个 client（不校验），且原 client 不被污染
r = utils.get_client(use_proxy=False, verify=False)
check("get_client", r.__dict__.get("_nb_verify"), False, "降级 client 校验关闭")
check("get_client", r is not c, True, "降级 client 与严格 client 是两个对象")

# 6) 再要严格 client 时应切回严格那个（不残留降级）
c2 = utils.get_client(use_proxy=False)
check("get_client", c2.__dict__.get("_nb_verify"), True, "切回严格校验")

# 7) NOVEL_TLS_STRICT=1 时不允许降级
check("_TLS_STRICT", utils._TLS_STRICT, True, "默认允许降级（strict 关闭）")

print()
if FAILS:
    print(f"❌ {len(FAILS)} 项失败")
    for f in FAILS:
        print("   -", f)
    sys.exit(1)
print("✅ 全部通过")
