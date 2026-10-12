"""访问令牌判据的回归测试。

为什么要专门测这个
------------------
这块逻辑踩过一次**真实的越权**：原来的 is_public_entry() 只看代理头，
把「服务绑在 0.0.0.0 且从网络访问」误判成局域网直连，于是云服务器上
任何人扫到 8000 端口，打开 /api/library 就能拿到书架元数据。

这个 bug 的危险之处在于：**本机测试永远测不出来** ——
本机访问时 client.host 是 127.0.0.1，怎么测都"正常"。
所以必须用假 request 显式构造"从别的 IP 连进来"的场景。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class FakeURL:
    def __init__(self, port=8000):
        self.port = port


class FakeRequest:
    """够用的假 request：headers / client.host / query_params。"""

    def __init__(self, headers=None, client_host="127.0.0.1", query=None):
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.client = type("C", (), {"host": client_host})()
        self.query_params = query or {}
        self.url = FakeURL()


def main() -> int:
    from app import security

    fails: list[str] = []

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}：期望 {want}，实际 {got}")
            print(f"  ✗ {label}")
        else:
            print(f"  ✓ {label}")

    print("== A. 绑本机（127.0.0.1）时：一切照旧，局域网不要求令牌 ==")
    security.set_bind_exposed(False)
    # 绑本机时，从别的 IP 连进来在物理上不可能，但即使构造出来也应放行
    r = FakeRequest(client_host="192.168.31.5")
    check("无头 + 非回环来源 → 非公网入口", security.is_public_entry(r), False)
    check("无头 + 非回环来源 → 放行", security.check_request(r), True)

    print()
    print("== B. 绑 0.0.0.0 时：从网络来的必须带令牌（修复的核心）==")
    security.set_bind_exposed(True)

    r = FakeRequest(client_host="106.53.203.108")
    check("公网来源 + 无令牌 → 判定为公网入口", security.is_public_entry(r), True)
    check("公网来源 + 无令牌 → 拒绝", security.check_request(r), False)
    check("公网来源 + 无令牌 → 需要 401", security.needs_auth_response(r), True)

    r = FakeRequest(client_host="192.168.31.5")   # 云服务器上不该有，但保险
    check("内网来源 + 无令牌 → 也判定为公网入口", security.is_public_entry(r), True)
    check("内网来源 + 无令牌 → 拒绝", security.check_request(r), False)

    tok = security.token()
    r = FakeRequest(client_host="106.53.203.108", query={"t": tok})
    check("公网来源 + 正确令牌 → 放行", security.check_request(r), True)

    r = FakeRequest(client_host="106.53.203.108", query={"t": "wrong-token-xxxxx"})
    check("公网来源 + 错误令牌 → 拒绝", security.check_request(r), False)

    r = FakeRequest(client_host="106.53.203.108", headers={"Authorization": f"Bearer {tok}"})
    check("公网来源 + Bearer 头 → 放行", security.check_request(r), True)

    r = FakeRequest(client_host="106.53.203.108", headers={"X-Token": tok})
    check("公网来源 + X-Token 头 → 放行", security.check_request(r), True)

    print()
    print("== C. 绑 0.0.0.0 时：本机自己访问仍然免令牌（别把自己锁外面）==")
    r = FakeRequest(client_host="127.0.0.1")
    check("回环来源 + 无令牌 → 非公网入口", security.is_public_entry(r), False)
    check("回环来源 + 无令牌 → 放行", security.check_request(r), True)

    r = FakeRequest(client_host="::1")
    check("IPv6 回环 → 放行", security.check_request(r), True)

    r = FakeRequest(client_host="127.0.0.5")
    check("127.x 段内 → 放行", security.check_request(r), True)

    print()
    print("== D. 代理头仍然单独成立（隧道场景不能被这个改动破坏）==")
    security.set_bind_exposed(False)   # 就算绑本机
    r = FakeRequest(client_host="127.0.0.1", headers={"CF-Connecting-IP": "1.2.3.4"})
    check("隧道 + 无令牌 → 公网入口", security.is_public_entry(r), True)
    check("隧道 + 无令牌 → 拒绝", security.check_request(r), False)

    r = FakeRequest(client_host="127.0.0.1", headers={"X-Forwarded-For": "1.2.3.4"})
    check("X-Forwarded-For + 无令牌 → 拒绝", security.check_request(r), False)

    r = FakeRequest(client_host="127.0.0.1", headers={"CF-Ray": "abc123"})
    check("CF-Ray + 无令牌 → 拒绝", security.check_request(r), False)

    security.set_bind_exposed(True)
    r = FakeRequest(client_host="127.0.0.1", headers={"CF-Connecting-IP": "1.2.3.4"},
                    query={"t": security.token()})
    check("隧道 + 正确令牌 → 放行", security.check_request(r), True)

    print()
    print("== E. is_local（谁能拿到令牌明文）==")
    security.set_bind_exposed(True)
    r = FakeRequest(client_host="127.0.0.1")
    check("本机 → 可以拿令牌明文", security.is_local(r), True)
    r = FakeRequest(client_host="106.53.203.108")
    check("公网来源 → 不给令牌明文", security.is_local(r), False)
    r = FakeRequest(client_host="127.0.0.1", headers={"CF-Connecting-IP": "1.2.3.4"})
    check("走隧道 → 不给令牌明文", security.is_local(r), False)

    # 复位，避免影响后续 import 这个模块的东西
    security.set_bind_exposed(False)

    print()
    print("== F. 重定向到内网必须被拦（纵深防御）==")
    # ⚠ `assert_public_url` 只在**用户提交那一刻**校验，而客户端开着
    #   `follow_redirects=True` —— 站点回一个 302 到内网就能绕过它。
    #   `utils._guard_redirect` 是每次请求（含重定向后）都会跑的钩子。
    import httpx
    from app.utils import _guard_redirect
    from app.security import BlockedURL

    def blocked(u) -> bool:
        try:
            _guard_redirect(httpx.Request("GET", u))
            return False
        except BlockedURL:
            return True

    check("公网站点放行", blocked("https://www.384g.com/search.php"), False)
    check("重定向到 127.0.0.1 → 拦", blocked("http://127.0.0.1/"), True)
    check("重定向到 localhost → 拦", blocked("http://localhost/"), True)
    check("重定向到云元数据 → 拦", blocked("http://169.254.169.254/latest/meta-data/"), True)
    check("重定向到 10.x 内网 → 拦", blocked("http://10.0.0.5/"), True)
    check("重定向到 192.168.x → 拦", blocked("http://192.168.1.1/"), True)
    check("重定向到 [::1] → 拦", blocked("http://[::1]/"), True)
    # 域名交给入口那层判（钩子不做 DNS，避免每个请求多一次系统调用）
    check("域名不在钩子里判（交给入口）", blocked("http://example.com/"), False)

    print()
    if fails:
        print(f"✗ {len(fails)} 项失败：")
        for f in fails:
            print(f"    {f}")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
