"""来源库「失败原因分类」回归 —— note_site 的 why 分桶必须真的落盘。

为什么要这个测试
----------------
来源库的 `fail` 一直是**混装桶**：网络连不上、URL 猜错、正文要登录，
三者都只让 `fail` +1。而 `is_healthy()` 用的判据是
「fail >= 3 and fail > ok*2」—— 于是：

  · 一个好站会因为**我们自己 URL 猜错**被慢慢判死；
  · 一个真挂掉的站只要历史成功多，比值也压不下来、清不掉。

这正是「定期排查坏源」做不起来的原因：数据里根本分不清
"站不行" 还是 "这次抓法不对"。

所以给 `note_site` 加了 `why`：按原因单独计数
（`fail_down` / `fail_empty` / `fail_shape` / `fail_video` / `fail_gated` /
`fail_slow`）。其中 **只有 `fail_down`** 算「站点自身故障」，其余都在说
「这次抓法不对」或「我们给的时间不够」。

这个测试钉三件事：
  ① why 传了会落盘成 `fail_<why>` 且逐次累加；
  ② `fail` 总数仍然照旧累加（不能因为加了 why 就少记）；
  ③ `fail_last_why` 记最近一次原因（排查时一眼看出"最近怎么挂的"）。

用法： python tools/test_registry_why.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = 0
BAD = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global OK, BAD
    if cond:
        OK += 1
        print(f"  ✓ {name}")
    else:
        BAD += 1
        print(f"  ✗ {name}  {extra}")


def main() -> int:
    print("=" * 62)
    print("来源库失败原因分类（note_site 的 why）")
    print("=" * 62)

    tmp = Path(tempfile.mkdtemp(prefix="regwhy-")) / "registry.json"
    # 关键：用独立的库文件，绝不能污染真实 cache/registry.json
    os.environ["NOVEL_REGISTRY"] = str(tmp)

    # 必须在设过环境变量之后再导入 —— _DB 是在模块加载时读 env 的
    from app import registry  # noqa: E402

    print("\n── 1. 分类常量齐全 ──")
    for c in ("FAIL_DOWN", "FAIL_EMPTY", "FAIL_SHAPE", "FAIL_VIDEO", "FAIL_GATED",
              "FAIL_SLOW"):
        check(f"常量 {c} 存在", hasattr(registry, c), "缺这个常量")
    # ⚠ 不写死"共 N 类"—— 加一类就红一次，红的是判据不是产品。
    #   要钉的是「FAIL_WHY_ALL 恰好覆盖所有 FAIL_* 常量」，这样新增原因
    #   忘了登记会红，写死数字反而会逼着人改数字、把真问题盖过去。
    consts = {v for k, v in vars(registry).items()
              if k.startswith("FAIL_") and isinstance(v, str)
              and k != "FAIL_WHY_SITE_FAULT"}
    check("FAIL_WHY_ALL 覆盖所有 FAIL_* 原因",
          set(registry.FAIL_WHY_ALL) == consts,
          f"库里 {sorted(consts)} vs 登记 {sorted(registry.FAIL_WHY_ALL)}")
    check("只有 DOWN 算『站点自身故障』",
          registry.FAIL_WHY_SITE_FAULT == (registry.FAIL_DOWN,),
          f"实际 {registry.FAIL_WHY_SITE_FAULT}")
    check("超时（slow）不算站点故障",
          registry.FAIL_SLOW not in registry.FAIL_WHY_SITE_FAULT,
          "把『我们等得不够』算成站挂了，慢站会被慢慢判死")

    print("\n── 2. why 落盘成 fail_<why> 并累加 ──")
    for _ in range(3):
        registry.note_site("down.example.com", ok=False, why=registry.FAIL_DOWN)
    for _ in range(2):
        registry.note_site("shape.example.com", ok=False, why=registry.FAIL_SHAPE)
    registry.note_site("down.example.com", ok=True)
    registry._save(force=True)

    db = json.loads(tmp.read_text(encoding="utf-8"))
    down = db["sites"]["down.example.com"]
    shape = db["sites"]["shape.example.com"]

    check("fail_down 累加到 3", down.get("fail_down") == 3,
          f"实际 {down.get('fail_down')}")
    check("fail_shape 累加到 2", shape.get("fail_shape") == 2,
          f"实际 {shape.get('fail_shape')}")

    print("\n── 3. fail 总数照旧累加（不能因为加了 why 就少记）──")
    check("down 站 fail 总数 = 3", down.get("fail") == 3, f"实际 {down.get('fail')}")
    check("down 站 ok = 1", down.get("ok") == 1, f"实际 {down.get('ok')}")

    print("\n── 4. fail_last_why 记最近一次原因 ──")
    check("down 站 fail_last_why = down", down.get("fail_last_why") == "down",
          f"实际 {down.get('fail_last_why')}")
    registry.note_site("down.example.com", ok=False, why=registry.FAIL_GATED)
    registry._save(force=True)
    db = json.loads(tmp.read_text(encoding="utf-8"))
    down = db["sites"]["down.example.com"]
    check("再记一次 gated 后，last_why 变成 gated",
          down.get("fail_last_why") == "gated", f"实际 {down.get('fail_last_why')}")
    check("但 fail_down 仍是 3（分桶不被覆盖）",
          down.get("fail_down") == 3, f"实际 {down.get('fail_down')}")

    print("\n── 5. 不传 why 时不产生空分桶（旧调用点向后兼容）──")
    registry.note_site("legacy.example.com", ok=False)
    registry._save(force=True)
    db = json.loads(tmp.read_text(encoding="utf-8"))
    legacy = db["sites"]["legacy.example.com"]
    check("旧调用只记 fail 总数", legacy.get("fail") == 1, f"实际 {legacy.get('fail')}")
    check("不产生 fail_ 开头的空键",
          not any(k.startswith("fail_") and k != "fail_last_why" for k in legacy),
          f"多出来的键：{[k for k in legacy if k.startswith('fail_')]}")

    print("\n" + "=" * 62)
    print(f"通过 {OK} · 失败 {BAD}")
    print("=" * 62)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
