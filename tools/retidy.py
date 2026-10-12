"""把书架里**已缓存**的章节正文重新清一遍。

为什么需要它：模板行过滤器是后加的，之前缓存下来的章节已经落盘了，
不会自己变干净 —— 用户点开旧书还是会看到「点此举报」。
这个脚本就地重写已缓存章节的 content 字段（幂等，跑几次结果一样）。

用法：
    python tools/retidy.py            # 只报告，不动文件
    python tools/retidy.py --apply    # 真的写回
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.sources.base import tidy_content  # noqa: E402

LIB = ROOT / "library"


def chapter_files():
    if not LIB.is_dir():
        return
    for book in sorted(LIB.iterdir()):
        chd = book / "ch"
        if not chd.is_dir():
            continue
        for f in sorted(chd.glob("*.json")):
            yield book.name, f


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的写回（默认只报告）")
    args = ap.parse_args()

    total = changed = 0
    per_book: dict[str, list[int]] = {}
    for book, f in chapter_files():
        total += 1
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"  ! 读不了 {f}: {e}")
            continue
        old = d.get("content") or ""
        new = tidy_content(old, d.get("title") or "")
        if new == old:
            continue
        changed += 1
        saved = len(old) - len(new)
        per_book.setdefault(book, []).append(saved)
        if args.apply:
            d["content"] = new
            f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    print(f"扫描 {total} 个已缓存章节，{changed} 个需要清理")
    for book, saved in per_book.items():
        print(f"  {book}: {len(saved)} 章，共瘦身 {sum(saved)} 字")
    if not args.apply and changed:
        print("\n这是演练。加 --apply 才会写回。")
    elif args.apply:
        print("\n已写回。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
