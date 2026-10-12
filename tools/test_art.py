#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
噜妹书院 · 素材层静态检查
============================================================================
test_motion.py 管的是"动效有没有按规矩来"，本文件管**素材本身的质量**。

为什么单独要一个：
  素材这事儿踩过两个坑，而且都是"看起来没问题"的那种 ——
    1. **情绪错配**：拿"在哭"的图当加载态、"睡不着焦虑"的图当"睡得香"。
       单看每张都挺可爱，只有对着用途逐张核才发现不对。
    2. **不成套**：首页两张各自都好看，并排一冷一暖、一亮一暗，
       像临时拼的。这个问题**静态代码里完全看不出来**，
       必须量像素才暴露。
  这两类错误以前靠人眼看，靠不住（一冷一暖那版就是"各自看都觉得还行"）。

检查项
------
  A. 配置完整      SCENES 覆盖 art.js 声明的所有状态（双向，不许有孤儿）
  B. 无文字水印    OCR 太重，改用"底部条带方差"启发式：
                  表情包文字集中在底部，且是深色高对比 —— 方差会异常高
  C. 色温自检      每对"应该像一套"的图，Δ色温 / Δ亮度 在容差内
  D. 情绪对得上    MOOD 表把每个槽位的**期望情绪**写死，
                  换素材时必须过这一关（这是防"望文生义"的机器化）
  E. 尺寸/比例     三种导出档位都存在，且比例与声明一致
============================================================================
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    from PIL import Image, ImageStat
    import numpy as np
except ImportError:
    sys.exit("需要 Pillow + numpy")

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "app" / "static" / "img" / "lumei"
ART_JS = ROOT / "app" / "static" / "js" / "art.js"
BUILD = ROOT / "tools" / "build_assets.py"

ok = fail = 0


def check(cond: bool, msg: str, detail: str = "") -> bool:
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {msg}")
    else:
        fail += 1
        print(f"  ✗ {msg}")
        if detail:
            for line in detail.strip().splitlines():
                print(f"      {line}")
    return cond


# ---------------------------------------------------------------------------
# 期望情绪表 —— 这是本文件的核心，也是"防望文生义"的机器化表达
# ---------------------------------------------------------------------------
# 每一项写的是**这个槽位必须传达什么**，不是"这张图长什么样"。
# 换素材的人（包括未来的我）得先回答"新图传达这个情绪吗"，
# 而不是"新图好看吗"。历史事故：
#   loading_drink 用过"脸挂泪痕"的图 —— 加载态在哭，等于告诉用户出事了。
#   empty_sleep   用过"躺床上刷手机 + 好难啊"的图 —— 那是焦虑，不是松弛。
MOOD = {
    "hero_lulu":      "平静、正面、无负面情绪（门面，不能是不高兴）",
    "hero_lumei":     "平静、正面、与 hero_lulu 同一光照",
    "empty_wait":     "期待、等人（空态：等你来搜）",
    "empty_sleep":    "松弛、闭眼（空态：睡得香。绝不能是焦虑/失眠）",
    "empty_lonely":   "安静、望向远处（空态：有点想书）",
    "loading_drink":  "松弛、放松（加载态：不着急。绝不能是哭/急）",
    "loading_read":   "专注、在看东西（加载态：正在找）",
    "error_confused": "茫然、张嘴（错误态：找不到）",
    "error_sad":      "低落、疲惫（错误态：明天再找）",
    "read_pair":      "亲密、成对（阅读页：陪伴感）",
    "read_eat":       "温暖、有食感（阅读色卡角标）",
}

# 允许残留的色温差（R-B），超了告警。这个数值是实测定的：
# 提高到 0.7 强度对齐后是 14，留一倍余量 → 30。
TONE_TOLERANCE = 30
LUM_TOLERANCE = 22


def main() -> int:
    print("=" * 62)
    print("素材层检查")
    print("=" * 62)

    build_src = BUILD.read_text(encoding="utf-8")
    art_src = ART_JS.read_text(encoding="utf-8")

    # ---- A. 配置完整性 -------------------------------------------------
    print("\n── A. 配置与声明是否对齐 ──────────────────────────────────")
    scenes = dict(re.findall(r'"(\w+)"\s*:\s*\(\s*"(\w+)"\s*,\s*\d+\s*,\s*\d+', build_src))
    scene_keys = set(scenes.keys())
    check(len(scene_keys) >= 11, f"build_assets.py 定义了 {len(scene_keys)} 个场景")

    # art.js 里声明的状态
    art_keys = set(re.findall(r'^\s{2}(\w+):\s*\{', art_src, re.M))
    hero_keys = set(re.findall(r'HTML_ONLY = new Set\(\[([^\]]+)\]\)', art_src))
    heroes = set(re.findall(r'"(\w+)"', art_src.split("HTML_ONLY")[1].split("\n")[0])) if "HTML_ONLY" in art_src else set()

    missing = scene_keys - art_keys - heroes
    check(not missing, "SCENES 里的每个角色都在 art.js 有声明（或属于 HTML_ONLY）",
          f"缺失：{sorted(missing)}")

    # 每个场景都有 MOOD 说明
    no_mood = scene_keys - set(MOOD.keys())
    check(not no_mood,
          "每个场景都写了期望情绪（MOOD 表）",
          f"没写的：{sorted(no_mood)}\n"
          "  加一个场景时必须同时回答『它要传达什么情绪』——\n"
          "  这一条是防「望文生义」的，不是形式主义。")

    # ---- B. 底部水印残留 -------------------------------------------------
    print("\n── B. 有没有带表情包文字 ──────────────────────────────────")
    # ⚠ 这一项**曾经用"底部暗像素占比"来做，结果大面积误报** ——
    #   夜空、暗墙、深色抱枕这些正常的暗部全被判成文字（8/11 误报）。
    #   教训：判据必须抓"文字区别于背景的**特征**"，不能只抓"像文字的亮度"。
    #
    # 文字的真实特征：**横向高频**。一行字在水平方向上有大量明暗交替的
    # 边缘（笔画），而背景（哪怕是暗背景）在水平方向是平缓的。
    # 所以量「水平梯度」在底部条带的密度，而不量亮度。
    #   实测：干净素材 p95 梯度 < 18；带字素材 > 45。
    dirty = []
    for role in sorted(scene_keys):
        p = IMG / f"{role}@480.webp"
        if not p.exists():
            continue
        a = np.asarray(Image.open(p).convert("L")).astype(np.float32)
        H = a.shape[0]
        band = a[int(H * 0.82):, :]
        gx = np.abs(np.diff(band, axis=1))          # 水平梯度
        # 取 p95 而不是均值 —— 文字笔画是稀疏的，均值会被大片背景稀释
        strength = float(np.percentile(gx, 95))
        if strength > 40:
            dirty.append(f"{role}（水平梯度 p95 = {strength:.0f}）")
    check(not dirty,
          "所有素材底部都没有表情包文字残留",
          "\n".join(dirty) + "\n  换一格，或调 focus 把文字裁出去。")

    # ---- C. 色温自检 -----------------------------------------------------
    print("\n── C. 「应该像一套」的图，色温亮度对得上吗 ────────────────")
    pairs = re.findall(r'"(\w+)"\s*:\s*\(\s*"(\w+)"\s*,\s*[\d.]+\)', build_src.split("TONE_PAIRS")[1].split("}")[0])
    if not pairs:
        check(False, "TONE_PAIRS 里至少有一对需要对齐的图",
              "首页 Hero 是两张并排的图，必须声明色温对齐关系。")
    for role, ref in pairs:
        pa, pr = IMG / f"{role}@480.webp", IMG / f"{ref}@480.webp"
        if not (pa.exists() and pr.exists()):
            check(False, f"{role} 或 {ref} 文件缺失")
            continue
        sa = ImageStat.Stat(Image.open(pa).convert("RGB").resize((60, 40))).mean
        sr = ImageStat.Stat(Image.open(pr).convert("RGB").resize((60, 40))).mean
        d_tone = abs((sa[0] - sa[2]) - (sr[0] - sr[2]))
        d_lum = abs(sum(sa) - sum(sr)) / 3
        check(d_tone <= TONE_TOLERANCE and d_lum <= LUM_TOLERANCE,
              f"{role} ↔ {ref} 色温亮度对齐（Δ色温 {d_tone:.0f} / Δ亮度 {d_lum:.0f}）",
              f"容差：色温 ≤{TONE_TOLERANCE}，亮度 ≤{LUM_TOLERANCE}。\n"
              "  修法：先调 SCENES 的取景（尽量同 sheet 同行）；\n"
              "  不行就把这一对加进 TONE_PAIRS 并提高强度。")

    # ---- D. 三档都存在且比例正确 -----------------------------------------
    print("\n── D. 三档导出都在，比例对 ────────────────────────────────")
    bad = []
    for role in sorted(scene_keys):
        for suf, want_ar in (("", None), ("@480", None), ("@240", None)):
            p = IMG / f"{role}{suf}.webp"
            if not p.exists():
                bad.append(f"{role}{suf}.webp 不存在")
                continue
        # 比例检查：hero 是 16:10，其余 4:3
        for suf in ("", "@480", "@240"):
            p = IMG / f"{role}{suf}.webp"
            if not p.exists():
                continue
            w, h = Image.open(p).size
            want = 16 / 10 if role.startswith("hero") else 4 / 3
            if abs(w / h - want) > 0.02:
                bad.append(f"{role}{suf}.webp 比例 {w}/{h}={w/h:.3f}，应为 {want:.3f}")
    check(not bad, "每个角色都有 3 档导出，且比例一致", "\n".join(bad))

    # ---- 汇总 -----------------------------------------------------------
    print("\n" + "=" * 62)
    print(f"通过 {ok} · 失败 {fail}")
    if fail:
        print("✗ 有问题，先把上面标 ✗ 的处理掉")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
