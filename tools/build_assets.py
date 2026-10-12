#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
噜妹书院 · 素材构建流水线
============================================================================
把「网上的真实水豚噜噜图」变成「站点能直接用的、尺寸合适的、离线可用的」
素材。跑一次就够，产物提交进仓库，运行时零请求、零外链。

素材的真实形态（这一步曾判断错两次，记录在此，别再犯）
-------------------------------------------------------
这些公开表情包大图是 **6×6 的场景拼图**，不是「白底贴纸」：

    ┌────────┬────────┬────────┐
    │ 场景1  │ 场景2  │ 场景3  │  ← 每格是一只噜噜在完整场景里
    │ 001-…  │ 002-…  │ 003-…  │  ← 每格底部有一条水印文字
    ├────────┼────────┼────────┤
    │ 场景7  │ 场景8  │ 场景9  │
    └────────┴────────┴────────┘

两次踩过的坑：
  1. **按白底抠图** —— 场景不是白底，一抠整个画面就没了（产物是残缺色块）。
  2. **用 W/6 均分格** —— 实际格子间距不均（252/253px 交替），
     而且没把底部**水印条**切掉，于是每张图顶端都带着上一行的水印残影。

正确做法：
  · 用**白色间隙检测**真实格子边界（不猜）
  · 单独切掉每格底部的**水印条**
  · 场景**整体保留**，不做抠图 —— 它们本身就是很好的装饰画

产物：
  app/static/img/lumei/
    hero_*.webp      横幅 16:10，首页大图
    empty_*.webp     4:3，空状态
    loading_*.webp   4:3，加载中
    error_*.webp     4:3，错误 / 找不到
    read_*.webp      4:3，阅读页装饰
    每个还带 @480 与 @240 两档

用法：
    .venv\\Scripts\\python tools\\build_assets.py            # 全量
    .venv\\Scripts\\python tools\\build_assets.py --probe    # 只打印检测到的网格
    .venv\\Scripts\\python tools\\build_assets.py --contact  # 只出校对拼图
============================================================================
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

try:
    from PIL import Image, ImageStat
    import numpy as np
except ImportError:
    sys.exit("需要 Pillow + numpy：.venv\\Scripts\\python -m pip install Pillow numpy")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "static" / "img" / "lumei"
RAW = ROOT / "cache" / "raw_assets"
SHOTS = ROOT / "shots"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

SHEETS = [
    ("sheet_a", "https://ddsck-1253963691.cos.ap-shanghai.myqcloud.com/zb_users/upload/2025/11/shuitunlulu01_01.jpg"),
    ("sheet_b", "https://ddsck-1253963691.cos.ap-shanghai.myqcloud.com/zb_users/upload/2025/11/shuitunlulu01_02.jpg"),
    ("sheet_c", "https://ddsck-1253963691.cos.ap-shanghai.myqcloud.com/zb_users/upload/2025/11/shuitunlulu01_03.jpg"),
    ("sheet_d", "https://ddsck-1253963691.cos.ap-shanghai.myqcloud.com/zb_users/upload/2025/11/shuitunlulu01_04.jpg"),
    ("sheet_e", "https://ddsck-1253963691.cos.ap-shanghai.myqcloud.com/zb_users/upload/2025/11/shuitunlulu01_05.jpg"),
]

# 选格：(sheet, row, col)，0-based；focus = 裁切时的垂直重心（0=顶 1=底）
#
# 选格标准（**第 4 条是后补的，也是最重要的**）：
#   1. 主体大、居中、正脸或清晰侧脸
#   2. 场景干净，不要挤满道具，**不能带表情包文字**（那是梗图，不适合当装饰）
#   3. 情绪对得上用途
#   4. ⚠ **同一个视觉组合里的几张，必须来自同一张 sheet 的同一行** ——
#      这些素材是"同一集动画的截图拼图"，同一行 = 同一个场景 = 同样的光照、
#      色温、白平衡。跨行/跨 sheet 拼两张，不管单独多好看，放一起就是
#      "两个来源的图"（首页 Hero 曾因此一冷一暖，被判定为"不像一对"）。
#      实在要跨行时，用 tone_match() 做色温归一，别硬拼。
#
# focus 的经验值（这些素材里，主体一般坐得偏上）：
#   0.20~0.30 = 特写（身体占满画面，头在上方）
#   0.35~0.45 = 中景（有上半身和周围环境）
SCENES = {
    # ---- 首页 Hero：噜噜 / 噜妹 ----
    # 选特写而不是全身像 —— 小尺寸下特写才看得清表情，全身体现不出"可爱"。
    # ⚠ 这两张**同属 sheet_b 第 2 行**（同一场景的一对）：暖橙、同一光照、
    #   同一背景色调。B2,2 是噜噜（无装饰），B3,2 戴粉蝴蝶结是噜妹 ——
    #   正好对应"一对情侣"的视觉分工，这是全素材库里唯一这样天然成对的组合。
    #   历史版本用过 A0,0 + C2,2：单看都行，并排一冷一暖（R-B 差 67），
    #   像临时拼的 —— 别再退回去。
    "hero_lulu":      ("sheet_b", 2, 2, 0.28),   # 正面特写，暖橙，无装饰 = 噜噜
    # 噜妹这张原始亮度只有 137.8、噜噜 162.8（差 25 级），并排明显"右暗一截"。
    # focus 调了 4 档都拉不动（差异来自素材本身，不是取景），只能用色温归一。
    # 0.70 而不是默认 0.5 —— 0.5 只把差从 30 压到 18，仍然看得出；
    # 提到 0.7 后压到 ~10，肉眼基本齐平，且还没到"洗掉固有色"的程度。
    "hero_lumei":     ("sheet_b", 3, 2, 0.28),   # 正面特写，暖橙 + 粉蝴蝶结 = 噜妹

    # ---- 空状态 ----
    # ⚠ empty_sleep 曾用 D0,2（躺床看手机）—— 那格**带「好难啊」表情包文字**，
    #   而且情绪是"焦虑"不是"松驰"，与「书架空着、睡得正香」完全相反。已换。
    "empty_sleep":    ("sheet_d", 1, 0, 0.30),   # 缩在粉被子里闭眼 —— 睡得正香
    "empty_wait":     ("sheet_a", 1, 3, 0.26),   # 两人一起趴在床边等 —— 等你来搜
    "empty_lonely":   ("sheet_c", 3, 0, 0.30),   # 仰头望星空 —— 有点想书（冷调，但意境对）

    # ---- 加载 / 等待 ----
    # ⚠ 这两个槽位历史上有硬伤，都换掉了：
    #   loading_drink 曾用 A0,3 —— 那格**脸上挂着泪痕**，拿"在哭"当加载态，
    #     等于告诉用户"出事了"，是最典型的情绪错配。
    #   loading_read 曾用 A1,1 —— 那格是一只躺着 + 一只拿锅铲，既不是"在看书"，
    #     构图也乱，完全对不上「正在取这一章」的语义。
    "loading_drink":  ("sheet_b", 0, 4, 0.30),   # 半眯眼靠着抱枕、窗外黄昏 —— 不着急
    "loading_read":   ("sheet_a", 0, 5, 0.30),   # 戴眼镜捧书 —— 正在找，在看书

    # ---- 错误 / 没找到 ----
    "error_confused": ("sheet_d", 0, 1, 0.34),   # 张着嘴一脸懵（找不到）
    "error_sad":      ("sheet_d", 0, 3, 0.34),   # 眯眼犯困 → 「算了吧，明天再找」

    # ---- 阅读页装饰 ----
    "read_pair":      ("sheet_a", 3, 0, 0.30),   # 两只贴脸靠在一起（陪伴）—— 素材里最好的"一对"
    # read_eat 只用在阅读配色色卡的 22px 圆角标上，看不出细节，
    # 所以选格标准不是"构图好"而是"暖橙 + 有食欲感"。
    # 曾用 A2,1（拿锅铲砸东西）—— 语义是"生气"不是"吃"，已换。
    "read_eat":       ("sheet_a", 3, 3, 0.35),   # 坐在碗前拿勺子 —— 边吃边看
}


# ---------------------------------------------------------------------------
# 网格检测：不猜，量出来
# ---------------------------------------------------------------------------
def find_gaps(axis_white: np.ndarray, thresh: float = 0.72) -> list[tuple[int, int]]:
    """把「整行/整列接近白」的位置聚成若干区间（= 格子间的缝）。"""
    idx = [i for i, v in enumerate(axis_white) if v > thresh]
    if not idx:
        return []
    out, start, prev = [], idx[0], idx[0]
    for x in idx[1:]:
        if x - prev > 2:
            out.append((start, prev))
            start = x
        prev = x
    out.append((start, prev))
    return out


def detect_grid(im: Image.Image) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """返回 (横向内容带, 纵向内容带) —— 即每一行/列的 [起, 止) 像素范围。"""
    a = np.asarray(im.convert("RGB")).astype(np.int16)
    H, W, _ = a.shape
    # 「白」= 三个通道都 >195
    whites = a.min(axis=2) > 195
    row_gaps = find_gaps(whites.mean(axis=1))
    col_gaps = find_gaps(whites.mean(axis=0))

    def bands(gaps, total):
        """由缝隙反推内容带：两个缝之间就是内容。"""
        bands = []
        prev_end = 0
        for s, e in gaps:
            if s - prev_end > 40:            # 够宽才算一段内容
                bands.append((prev_end, s))
            prev_end = e
        if total - prev_end > 40:
            bands.append((prev_end, total))
        return bands

    return bands(row_gaps, H), bands(col_gaps, W)


def split_watermark(band: tuple[int, int], sheet_name: str, r: int) -> tuple[int, int]:
    """把一个内容带拆成「画面」和「水印」两段。

    水印条的特征：紧贴内容底部、约 16px 高、整体偏白且文字是深灰。
    实测各图基本一致（内容 ~220px + 水印 ~16px），所以直接按比例切最稳。
    """
    top, bottom = band
    h = bottom - top
    # 水印约占 7%，且固定 14~20px
    wm = max(12, min(20, round(h * 0.07)))
    return (top, bottom - wm)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def fetch(url: str, dest: Path, force: bool = False) -> Path:
    if dest.exists() and dest.stat().st_size > 10_000 and not force:
        return dest
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://ddsck.cn/"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    if len(data) < 10_000:
        raise RuntimeError(f"下载失败：{url} -> {len(data)} bytes")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def cell_of(sheet: str, r: int, c: int) -> Image.Image:
    """取一格（已切掉水印条）。"""
    im = Image.open(RAW / f"{sheet}.jpg").convert("RGB")
    rows, cols = detect_grid(im)
    if r >= len(rows) or c >= len(cols):
        raise IndexError(f"{sheet} 只有 {len(rows)} 行 {len(cols)} 列，取不到 [{r},{c}]")
    top, bottom = split_watermark(rows[r], sheet, r)
    left, right = cols[c]
    return im.crop((left, top, right, bottom))


def cover(im: Image.Image, w: int, h: int, focus: float = 0.38) -> Image.Image:
    """按目标宽高比做「cover」裁切，主体大致居中（focus 为垂直重心）。"""
    tw, th = im.width, round(im.width * h / w)
    if th <= im.height:
        top = round((im.height - th) * focus)
        return im.crop((0, top, im.width, top + th))
    tw = round(im.height * w / h)
    left = (im.width - tw) // 2
    return im.crop((left, 0, left + tw, im.height))


# ---------------------------------------------------------------------------
# 残影修补
# ---------------------------------------------------------------------------
# 这些素材是"表情包图集"，除了底部的文字水印，**部分格子的四角还压着一个
# 半透明的圆形 logo 残影**（类似"小红书/微博"转发水印）。它很淡，缩略图
# 完全看不出，但一放大就在纯色背景上显形 —— 属于"看着不利索"的那类脏。
#
# 处理方式：对指定的角做**内容感知填充** —— 用同一条带上的邻近像素向角部
# 拉伸（resize 一个同行的窄条），再与原因做一次羽化混合盖上去。
# 为什么不直接模糊：模糊会留下一团"糊斑"，比原来的残影更显眼；
# 拉伸邻近背景能接上原有的渐变，看起来才像"本来就没有"。
#
# ⚠ 这是按需的：只对确认有残影的格子开，别全局默认开 ——
#   对干净图做无谓的修补只会引入新的伪影。
REPAIR = {
    # role: (角, 修补边长占该边的比例)
    "loading_drink": ("tr", 0.34),   # B0,4 右上有个圆形残影（窗户边的光斑状）
}


def repair_corner(im: Image.Image, corner: str, frac: float) -> Image.Image:
    """把某个角上的一块，用旁边的同带背景"拉过去"盖住。"""
    W, H = im.size
    bw, bh = max(8, round(W * frac)), max(8, round(H * frac))
    if corner in ("tr", "br"):
        band = im.crop((W - bw * 2, 0 if corner == "tr" else H - bh, W - bw, bh if corner == "tr" else H))
    else:
        band = im.crop((bw, 0 if corner == "tl" else H - bh, bw * 2, bh if corner == "tl" else H))
    patch = band.resize((bw, bh), Image.LANCZOS)

    # 羽化：把补丁用一张"从角到带内渐变透明"的蒙版盖上去，接缝看不出来
    mask = Image.new("L", (bw, bh), 255)
    px = mask.load()
    for y in range(bh):
        for x in range(bw):
            if corner == "tr":
                d = (x + y) / (bw + bh)
            elif corner == "tl":
                d = ((bw - x) + y) / (bw + bh)
            elif corner == "br":
                d = (x + (bh - y)) / (bw + bh)
            else:
                d = ((bw - x) + (bh - y)) / (bw + bh)
            px[x, y] = int(255 * max(0.0, 1 - d * 1.6))

    box_x = 0 if corner in ("tl", "bl") else W - bw
    box_y = 0 if corner in ("tl", "tr") else H - bh
    out = im.copy()
    out.paste(patch, (box_x, box_y), mask)
    return out


# ---------------------------------------------------------------------------
# 色温 / 亮度归一（"让几张图看起来像一套"的关键一步）
# ---------------------------------------------------------------------------
# 为什么必须有这一步：
#   "同一张 sheet 同一行"能保证**场景**一致，但保不住**取景**一致 ——
#   取景偏下就多进暗部，取景偏上就多进高光，两张并排立刻一明一暗。
#   首页 Hero 实测：噜噜亮度 162.8 / 噜妹 137.8，差 25 级 —— 肉眼看就是
#   "右边那块暗一截"。靠手调 focus 是碰运气，量化对齐才是正解。
#
# 做法：把待对齐的图按"来源图"的均值和标准差做一次线性映射（同
# Reinhard 色彩迁移的简化版，不加协方差那层 —— 卡通素材用不上，
# 而且过度对齐会把主体本身的固有色也洗掉）。
#   目标：均值对齐（解决明暗差）+ 幅度压缩一半（解决对比度差）
#   ⚠ 只对**同一组**图做（Hero 一对、阅读页一对），别全库统一 ——
#     每张图有自己要传达的情绪，全局拉平会让"星空暗调""黄昏暖调"
#     这些刻意的氛围全部消失。
TONE_PAIRS = {
    # 被对齐者: (参照者, 强度)
    "hero_lumei": ("hero_lulu", 0.70),
}

# 允许残留的色温差（R-B）。超过就在构建末尾告警 —— 靠人眼盯容易漏。
TONE_TOLERANCE = 40


def tone_match(im: Image.Image, ref: Image.Image, strength: float = 0.5) -> Image.Image:
    """把 im 的亮度/色温往 ref 上靠。strength=1 完全对齐，0.5 走一半。"""
    a = np.asarray(im, dtype=np.float32)
    r = np.asarray(ref, dtype=np.float32)
    out = a.copy()
    for ch in range(3):
        am, asd = a[:, :, ch].mean(), a[:, :, ch].std() + 1e-6
        rm, rsd = r[:, :, ch].mean(), r[:, :, ch].std() + 1e-6
        # 目标均值 = 往参照均值走 strength 比例；标准差只拉一半（防洗掉固有色）
        tm = am + (rm - am) * strength
        tsd = asd + (asd * (rsd / asd) - asd) * (strength * 0.5)
        out[:, :, ch] = (a[:, :, ch] - am) / asd * tsd + tm
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def sheet_of(role: str) -> str:
    spec = SCENES[role]
    return f"{spec[0]}[{spec[1]},{spec[2]}]"


def focus_of(role: str) -> float:
    spec = SCENES[role]
    return spec[3] if len(spec) > 3 else 0.30


def warn_tone() -> None:
    """量一遍"应该像一套"的图之间的色温差，超容差告警。"""
    problems = []
    for role, (ref_role, _strength) in TONE_PAIRS.items():
        pa, pr = OUT / f"{role}@480.webp", OUT / f"{ref_role}@480.webp"
        if not (pa.exists() and pr.exists()):
            continue
        sa = ImageStat.Stat(Image.open(pa).convert("RGB").resize((60, 40))).mean
        sr = ImageStat.Stat(Image.open(pr).convert("RGB").resize((60, 40))).mean
        d_tone = abs((sa[0] - sa[2]) - (sr[0] - sr[2]))
        d_lum = abs(sum(sa) - sum(sr)) / 3
        flag = ""
        if d_tone > TONE_TOLERANCE:
            flag = "  ← 色温差偏大"
            problems.append(f"{role} vs {ref_role}: Δ色温 {d_tone:.0f}")
        print(f"      · {role} ↔ {ref_role}: Δ色温 {d_tone:5.1f}  Δ亮度 {d_lum:5.1f}{flag}")
    if problems:
        print("\n⚠ 色温自检未通过：")
        for p in problems:
            print(f"    - {p}")
        print("  处理：调 SCENES 的取景（focus），或把这一对加进 TONE_PAIRS。")


def save_webp(im: Image.Image, dest: Path, quality: int = 84) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "WEBP", quality=quality, method=6)
    return dest.stat().st_size


def contact_sheet() -> None:
    files = [f for f in sorted(OUT.glob("*.webp")) if "@" not in f.name]
    if not files:
        print("没有产物可校对")
        return
    cw, chh = 260, 200
    cols = 4
    rows = (len(files) + cols - 1) // cols
    sheet = Image.new("RGB", (cw * cols, chh * rows), (250, 246, 238))
    for i, f in enumerate(files):
        im = Image.open(f).convert("RGB")
        im.thumbnail((cw - 12, chh - 24), Image.LANCZOS)
        x = (i % cols) * cw + (cw - im.width) // 2
        y = (i // cols) * chh + (chh - im.height) // 2
        sheet.paste(im, (x, y))
    SHOTS.mkdir(exist_ok=True)
    sheet.save(SHOTS / "assets_check.png")
    print(f"校对图 → shots/assets_check.png（{len(files)} 张）")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-raw", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--probe", action="store_true", help="只打印检测到的网格")
    ap.add_argument("--contact", action="store_true", help="只出校对图")
    args = ap.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    if args.contact:
        contact_sheet()
        return 0

    print(f"[1/3] 准备素材（{len(SHEETS)} 张拼接图）…")
    have = {}
    for name, url in SHEETS:
        try:
            p = fetch(url, RAW / f"{name}.jpg", force=args.force)
            have[name] = p
            print(f"      ✓ {name}  {p.stat().st_size // 1024}KB")
        except Exception as e:
            print(f"      ✗ {name}  {e}")
    if not have:
        return 1

    if args.probe:
        print("\n检测到的网格（行内容带 / 列内容带）：")
        for name in have:
            im = Image.open(RAW / f"{name}.jpg")
            rows, cols = detect_grid(im)
            print(f"  {name}: {len(rows)} 行 × {len(cols)} 列")
            print(f"    行: {rows}")
            print(f"    列: {cols}")
        return 0

    print("[2/3] 生成场景图 …")
    ok = 0
    bases: dict[str, Image.Image] = {}
    for role, spec in SCENES.items():
        sheet, r, c = spec[0], spec[1], spec[2]
        focus = spec[3] if len(spec) > 3 else 0.30
        if sheet not in have:
            print(f"      ! 跳过 {role}（缺 {sheet}）")
            continue
        try:
            cell = cell_of(sheet, r, c)
        except Exception as e:
            print(f"      ! 跳过 {role}（{e}）")
            continue
        ar = (16, 10) if role.startswith("hero") else (4, 3)
        base = cover(cell, *ar, focus=focus)
        # 残影修补要在**裁到目标比例之后**做 —— 修补用的是"角上那块背景"，
        # 裁切会改变哪块像素落在角上，先在原格上修就错位了。
        if role in REPAIR:
            corner, frac = REPAIR[role]
            base = repair_corner(base, corner, frac)
        bases[role] = base

    # 色温归一：必须在**所有 base 都裁好之后**统一做 ——
    # 它是"两张之间"的操作，得先有两个成品才能比较。
    for role, (ref_role, strength) in TONE_PAIRS.items():
        if role in bases and ref_role in bases:
            bases[role] = tone_match(bases[role], bases[ref_role], strength)
            print(f"      ~ {role:16s} 色温对齐 ← {ref_role}（强度 {strength:g}）")

    for role, base in bases.items():
        ar = (16, 10) if role.startswith("hero") else (4, 3)
        for target, q, suf in ((960, 84, ""), (480, 84, "@480"), (240, 82, "@240")):
            save_webp(base.resize((target, round(target * ar[1] / ar[0])), Image.LANCZOS),
                      OUT / f"{role}{suf}.webp", q)
        mark = f"  修补{REPAIR[role][0]}" if role in REPAIR else ""
        print(f"      ✓ {role:16s} ← {sheet_of(role)} focus={focus_of(role)}{mark}")
        ok += 1

    print("[3/3] 出校对图 …")
    contact_sheet()

    # 色温自检：把每对「应该看起来像一套」的图量一遍 R-B，
    # 超容差就告警。这一步是补"人眼会漏"的洞 —— 前几版一冷一暖
    # 就是靠肉眼各自看图，各自都觉得没问题，合起来才发觉不对劲。
    warn_tone()

    if not args.keep_raw:
        for p in have.values():
            p.unlink(missing_ok=True)
        try:
            RAW.rmdir()
        except OSError:
            pass

    tot = sum(f.stat().st_size for f in OUT.rglob("*.webp"))
    print(f"\n完成：{ok} 组场景 → {OUT}")
    print(f"      {len(list(OUT.rglob('*.webp')))} 个 webp，共 {tot // 1024}KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
