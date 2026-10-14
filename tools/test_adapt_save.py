"""`sites.json` 落盘的回归测试（全离线）。

为什么值得单独一个套件：`sites.json` 是**站点配置**，不是缓存。
它坏了不是"少几条搜索结果"，而是**内置来源 + 用户自己加过的站一起消失**。
而原实现有两条路会把它毁掉：

  1. `CONFIG_FILE.write_text(...)` —— "先清空再写"。进程在中间被杀
     （部署重启 / OOM / Ctrl-C）就留下半截 JSON。
  2. 读失败时 `data = {"sites": []}`，然后照样写 —— 一次暂时性的读失败
     （文件被占、编码抖一下）就把整个文件**改写成只有一个条目**，
     而且**不报错**，用户完全不知道自己的站点列表没了。

判据都打在"文件在磁盘上的最终状态"上（不是函数返回值），并且每条配反证。
用法：.venv/Scripts/python.exe tools/test_adapt_save.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.sources import adapter as A                            # noqa: E402
from app.sources import configured as C                         # noqa: E402

_fail: list[str] = []
_passed = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global _passed
    if ok:
        _passed += 1
        print(f"  ✓ {name}")
    else:
        _fail.append(name)
        print(f"  ✗ {name}" + (f"（{detail}）" if detail else ""))
    return ok


BUILTIN = [
    {"name": "builtin_a", "display": "A站", "base_url": "https://a.test/"},
    {"name": "builtin_b", "display": "B站", "base_url": "https://b.test/"},
    {"name": "builtin_c", "display": "C站", "base_url": "https://c.test/"},
]


class _Case:
    """把「运行时站点表」指向临时目录，跑完还原。

    ⚠ 指向的是 `LOCAL_SITES`（= `cache/sites_local.json`），不是仓库里那份
      `app/sources/sites.json` —— 后者在部署时会被仓库版本覆盖，**绝不能**
      拿来存用户加的站点（这正是本轮修的那个坑）。
    """

    def __init__(self, raw: str | None = None):
        self.raw = raw

    def __enter__(self):
        self._old = (A.LOCAL_SITES, A.CONFIG_FILE)
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "sites_local.json"
        if self.raw is not None:
            self.path.write_text(self.raw, encoding="utf-8")
        A.LOCAL_SITES = self.path
        # ⚠ **两个都隔离**：反证时会把产品代码改成写 CONFIG_FILE（复现旧行为），
        #   如果只隔离 LOCAL_SITES，那一跑就会**真的改写仓库里的 sites.json**。
        #   测试工具绝不能碰生产配置文件。
        A.CONFIG_FILE = Path(self._dir.name) / "sites.json"
        return self

    def __exit__(self, *exc):
        (A.LOCAL_SITES, A.CONFIG_FILE) = self._old
        self._dir.cleanup()
        return False

    def read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def names(self) -> list[str]:
        return [s.get("name") for s in self.read().get("sites", [])]

    def leftovers(self) -> list[str]:
        return sorted(p.name for p in self.path.parent.glob("*.tmp"))


def main() -> int:
    print("== A. 正常保存：只动同名那条，别的不许丢 ==")
    with _Case(json.dumps({"sites": BUILTIN}, ensure_ascii=False)) as c:
        ok = A.save_adapted({"name": "builtin_b", "display": "B站新版"})
        check("返回成功", ok is True)
        check("内置 3 条都在（没有把别的站点挤掉）",
              {"builtin_a", "builtin_b", "builtin_c"} <= set(c.names()),
              str(c.names()))
        check("同名是**覆盖**不是追加（不出现两条 builtin_b）",
              c.names().count("builtin_b") == 1, str(c.names()))
        check("新内容真的写进去了",
              next(s for s in c.read()["sites"]
                   if s["name"] == "builtin_b")["display"] == "B站新版")
        check("没有留下 `.tmp` 残渣", c.leftovers() == [], str(c.leftovers()))

    print("\n== B. 新站是**追加**（原列表一条不少）==")
    with _Case(json.dumps({"sites": BUILTIN}, ensure_ascii=False)) as c:
        A.save_adapted({"name": "new_z", "display": "Z站"})
        check("4 条，顺序是 原有 3 + 新增 1",
              c.names() == ["builtin_a", "builtin_b", "builtin_c", "new_z"],
              str(c.names()))

    print("\n== C. 文件不存在 → 允许新建（这是唯一「可以空手写」的情况）==")
    with _Case(None) as c:
        ok = A.save_adapted({"name": "only_one", "display": "独苗"})
        check("新建成功且只有这一条", ok is True and c.names() == ["only_one"],
              str(c.names()))

    print("\n== D.（反证）文件读不动时：**必须不写**，保住原文件 ==")
    # 造一个"半截 JSON"（正是旧实现在进程被杀时会留下的东西）。
    broken = '{"sites": [{"name": "builtin_a"'
    with _Case(broken) as c:
        ok = A.save_adapted({"name": "new_z", "display": "Z站"})
        check("明确返回失败（而不是假装成功）", ok is False)
        check("**原文件一个字都没改**（旧实现会把它改写成只剩 new_z 一条）",
              c.path.read_text(encoding="utf-8") == broken,
              c.path.read_text(encoding="utf-8")[:60])
        check("没有留下 `.tmp` 残渣", c.leftovers() == [], str(c.leftovers()))

    print("\n== E.（反证）结构不对（不是 {sites: [...]}）也要拒绝 ==")
    with _Case(json.dumps({"whatever": 1})) as c:
        ok = A.save_adapted({"name": "new_z"})
        check("拒绝写入并保住原文件",
              ok is False and c.read() == {"whatever": 1}, str(c.read()))

    print("\n== F.（反证）原子写：最终替换失败时，原文件必须完好 ==")
    with _Case(json.dumps({"sites": BUILTIN}, ensure_ascii=False)) as c:
        before = c.path.read_text(encoding="utf-8")
        old_replace = A.os.replace

        def _boom(src, dst):
            raise OSError("模拟替换瞬间失败（磁盘满 / 被占用）")

        A.os.replace = _boom
        try:
            ok = A.save_adapted({"name": "new_z"})
        finally:
            A.os.replace = old_replace
        check("返回失败", ok is False)
        check("原文件仍是完整的 3 条（不是半截 JSON）",
              c.path.read_text(encoding="utf-8") == before and len(c.names()) == 3,
              str(c.names()))
        check("临时文件被清掉了，不留垃圾", c.leftovers() == [], str(c.leftovers()))

    print("\n== G. 用户加的站必须**留得住**：写 `cache/`，不是会被部署覆盖的 `app/` ==")
    # 部署 = 用仓库版本覆盖整个 `app/`。运行时来源若写进 `app/sources/sites.json`，
    # 下次部署就没了 —— 用户加了站、过一天发现站不见了，还不知道为什么。
    check("运行时站点表落在 `cache/` 下（部署脚本保留 cache、且已 gitignore）",
          A.LOCAL_SITES.parent.name == "cache"
          and A.LOCAL_SITES.name == "sites_local.json",
          str(A.LOCAL_SITES))
    check("而且**不是**那个会被覆盖的 `app/sources/sites.json`",
          A.LOCAL_SITES != A.CONFIG_FILE, str(A.LOCAL_SITES))
    check("`save_adapted` 写的是本地那份（不是 CONFIG_FILE）",
          "_atomic_write_text(\n            LOCAL_SITES" in
          (ROOT / "app" / "sources" / "adapter.py").read_text(encoding="utf-8"))
    check("支持 `NOVEL_SITES` 覆盖（照 `NOVEL_RANKS` 的范式，测试/本地服务可隔离）",
          "NOVEL_SITES" in (ROOT / "app" / "sources" / "adapter.py").read_text(encoding="utf-8"))

    print("\n== H. 加载端：内置 + 本地 **两处都读**，同名以本地为准 ==")
    with tempfile.TemporaryDirectory() as d:
        local = Path(d) / "sites_local.json"
        local.write_text(json.dumps({"sites": [
            {"name": "builtin_a", "display": "A站(用户改过)", "base_url": "https://a.test/"},
            {"name": "user_added", "display": "用户加的站", "base_url": "https://u.test/"},
        ]}, ensure_ascii=False), encoding="utf-8")
        _old_local, _old_cfg = C.LOCAL_FILE, C.CONFIG_FILE
        builtin = Path(d) / "sites.json"
        builtin.write_text(json.dumps({"sites": BUILTIN}, ensure_ascii=False),
                           encoding="utf-8")
        C.LOCAL_FILE, C.CONFIG_FILE = local, builtin
        try:
            got = {s.name: s for s in C.load_configured_sources()}
        finally:
            C.LOCAL_FILE, C.CONFIG_FILE = _old_local, _old_cfg
        check("内置的 3 条还在", {"builtin_a", "builtin_b", "builtin_c"} <= set(got),
              str(sorted(got)))
        check("用户加的站也读出来了", "user_added" in got, str(sorted(got)))
        check("同名时**本地赢**（用户改过的不该被仓库旧版盖回去）",
              got["builtin_a"].display == "A站(用户改过)",
              got["builtin_a"].display if "builtin_a" in got else "丢了")

    print("\n== I. 适配流程真的会把「没保存成功」说出来（不是只写日志）==")
    src = Path(ROOT / "app" / "sources" / "adapter.py").read_text(encoding="utf-8")
    check("`_adapt_impl` 里 save 的返回值有被使用（不是裸调用）",
          "if save_adapted(cfg):" in src)
    check("失败那条步骤文案是**人话**（提到没覆盖已有站点）",
          "没有覆盖你已有的站点" in src)

    print("\n" + "=" * 62)
    print(f"通过 {_passed} · 失败 {len(_fail)}")
    for f in _fail:
        print("  ✗ " + f)
    print("=" * 62)
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
