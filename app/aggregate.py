"""按「书」聚合搜索结果。

搜索结果是「来源级」的：同一本《三体》在 5 个站就是 5 条记录。
直接铺给用户就是一屏的重复卡片 —— 用户抱怨的「别狂乱展示」正是这个。

这一层把它们合并成「一本书」：

    《三体》 刘慈欣
    ├─ 维基文库   135 章  ✓ 可用
    ├─ 鲲弩小说   120 章  ✓ 可用
    └─ 某小站      45 章  ✗ 打不开

同一本书只占一个位置，用户看到的是「有几个源能读、哪个最全」，
而不是一堆看不出区别的条目。
"""
from __future__ import annotations

import hashlib
import re

from .models import BookResult
from .suggest import normalize

_PUNCT_RE = re.compile(r"[\s·・\-—_.,，。:：!！?？'\"“”‘’()（）\[\]【】]+")
_VOL_RE = re.compile(r"^(第[一二三四五六七八九十百千0-9]+[部卷季篇辑])")
_VOL_TAIL_RE = re.compile(r"[（(【\[]?(第[一二三四五六七八九十百千0-9]+[部卷季篇辑])[）)】\]]?$")


def book_key(r: BookResult) -> str:
    """把「同一本书的不同写法」归到一把钥匙上。

    需要处理：繁简、空格标点、尾部的卷号（《XX 第二部》不该和《XX》分成两本）。

    **只按书名归并，不掺作者。** 因为很多小站根本不返回作者（或写成「佚名」），
    一旦把作者算进 key，《三体》和《三体（无作者）》就会被拆成两本 ——
    作者只用来在合并后投票选一个显示名。
    """
    t = normalize(r.title)
    t = _PUNCT_RE.sub("", t)
    t = _VOL_TAIL_RE.sub("", t)
    t = _VOL_RE.sub("", t)
    return t or (r.title or "").strip()


def hue_of(text: str) -> int:
    """由书名推一个稳定的色相 —— 前端用它生成封面渐变色。"""
    h = hashlib.md5((text or "?").encode("utf-8")).hexdigest()
    return int(h[:6], 16) % 360


def _pick_title(items: list[BookResult]) -> str:
    """从若干写法里选一个最像「正名」的。

    偏好：更短的（去掉了 SEO 尾巴）、没有卷号的、相关性高的。
    """
    scored = []
    for r in items:
        t = (r.title or "").strip()
        if not t:
            continue
        penalty = len(t) * 1.0
        if _VOL_TAIL_RE.search(t):
            penalty += 8
        scored.append((penalty - r.score * 0.05, t))
    if not scored:
        return "未命名"
    scored.sort(key=lambda x: x[0])
    return scored[0][1]


def _pick_author(items: list[BookResult]) -> str:
    from collections import Counter

    names = [ (r.author or "").strip() for r in items ]
    names = [n for n in names if n and n not in ("未知作者", "佚名", "作者未知", "-")]
    if not names:
        return ""
    # 出现次数最多的赢；同票取短的（短的一般更干净）
    return Counter(names).most_common(1)[0][0]


def _pick_intro(items: list[BookResult]) -> str:
    intro = ""
    for r in sorted(items, key=lambda x: -(x.score or 0)):
        s = (r.intro or "").strip()
        if len(s) > len(intro):
            intro = s
    return intro


def group(results: list[BookResult]) -> list[dict]:
    """把来源级结果聚合成书籍级结果。"""
    buckets: dict[str, list[BookResult]] = {}
    order: list[str] = []
    for r in results:
        k = book_key(r)
        if k not in buckets:
            buckets[k] = []
            order.append(k)
        buckets[k].append(r)

    books: list[dict] = []
    for k in order:
        items = buckets[k]
        items.sort(key=lambda r: (
            0 if r.available else (2 if r.available is None else 1),
            -r.chapter_count,
            -r.score,
        ))
        best = items[0]
        title = _pick_title(items)
        avail = [r for r in items if r.available]
        books.append({
            "key": k,
            "title": title,
            "author": _pick_author(items),
            "intro": _pick_intro(items),
            "hue": hue_of(title),
            "sources": [r.to_dict() for r in items],
            "source_count": len(items),
            # 「目录能打开」和「正文真能读」是两件事，分开数 ——
            # 前端给绿标必须看 readable_count，不然就是把没验证过的说成可读。
            "available_count": len(avail),
            "readable_count": sum(1 for r in items if r.readable),
            "chapter_count": max((r.chapter_count for r in items), default=0),
            "score": round(max((r.score for r in items), default=0.0), 1),
            "best_url": best.url,
            "best_source": best.source,
            "best_source_display": best.source_display or best.source,
            "verified": any(getattr(r, "sample_ok", None) for r in items),
            "sample_chars": max((getattr(r, "sample_chars", 0) or 0) for r in items),
            # 这本书算不算「确切命中」。整批结果里一个都没有时，
            # 前端会打上「只是沾边」的横幅，免得用户以为搜错了。
            "tight": any(getattr(r, "tight", False) for r in items),
        })

    # 排序：先看有几个源真的能读 → 再看目录可达 → 章节是否完整 → 相关性
    books.sort(key=lambda b: (
        0 if b["readable_count"] else (1 if b["available_count"] else 2),
        -b["readable_count"],
        -b["available_count"],
        -b["chapter_count"],
        -b["score"],
    ))
    return books
