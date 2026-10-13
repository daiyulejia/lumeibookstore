"""搜索历史 —— 让「搜过什么」不只是浏览器的私事。

为什么要有它
------------
搜索是这个站的**唯一入口**。在此之前，用户每次都得重新敲一遍书名，
而我们对「大家在搜什么」一无所知 —— 结果就是：

  * 搜「斗破」的人第二天来，还得再敲一遍「斗破」；
  * 热词榜只能靠猜，运营上没有抓手；
  * 服务器日志里 `search.start` 记了词，但那是**日志**，
    没人会为了看热词去 grep 日志，而且日志会轮转、会删。

这一层把搜索词变成**一等数据**：既给用户一个"继续上次"的入口，
也给「热门搜索」提供原料。

为什么不放浏览器 localStorage
----------------------------
localStorage 最简单，但它是**每浏览器独立**的 —— 换设备就没了，
而且服务端拿不到，热词榜就无从做起。这里选服务端落盘，
前端仍然可以只读最近 N 条做下拉，体验一样。

落盘结构（`cache/history.json`）::

    {
      "items": [
        {"kw": "斗破苍穹", "ts": 1760000000, "count": 3, "hits": 12},
        ...
      ],
      "version": 1
    }

`kw` 是主键（同一本书搜两次不新增条目，只 `count += 1`）。
`hits` 是该词最后一次搜索命中的候选数，用来区分"搜得到"和"总也搜不到"——
后者才是有价值的线索（说明书库覆盖不到位）。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from .logging_setup import get_logger, log_event

logger = get_logger("novel.history")

_ROOT = Path(__file__).resolve().parent.parent
_DB = Path(os.environ.get("NOVEL_HISTORY") or (_ROOT / "cache" / "history.json"))

# 保留上限。搜索词是低价值高频数据，留太多既占盘也没人看。
# 200 条足够覆盖"下拉里的最近 20 条 + 热词榜前 50 条"。
_MAX_ITEMS = 200

# 单个搜索词的最大长度。防止有人往接口里灌一整本书当词。
_MAX_KW = 60

_lock = threading.Lock()
_items: list[dict[str, Any]] = []
_loaded = False
_dirty = False


def _clean_kw(kw: str) -> str:
    """规整搜索词：去首尾空白、折叠内部连续空白、截断超长。

    ⚠ 折叠空白而不是直接 strip：`"斗破  苍穹"` 和 `"斗破 苍穹"` 是同一个词，
    不折叠的话热词榜里会出现两个"看起来一样"的条目。
    """
    s = " ".join(str(kw or "").split())
    return s[:_MAX_KW]


def _load() -> None:
    """首次访问时从磁盘读回。只读一次，之后全走内存。"""
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        raw = json.loads(_DB.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except Exception as e:  # noqa: BLE001
        # 文件坏了当空库继续跑 —— 历史是"锦上添花"，不该让主流程起不来
        log_event(logger, "history.load.fail", 原因=str(e)[:120])
        return
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        kw = _clean_kw(it.get("kw"))
        if not kw:
            continue
        try:
            ts = float(it.get("ts") or 0)
        except (TypeError, ValueError):
            ts = 0.0
        try:
            cnt = int(it.get("count") or 1)
        except (TypeError, ValueError):
            cnt = 1
        try:
            hits = int(it.get("hits") or 0)
        except (TypeError, ValueError):
            hits = 0
        out.append({"kw": kw, "ts": ts, "count": max(1, cnt), "hits": max(0, hits)})
    _items.extend(out[: _MAX_ITEMS])


def _save() -> None:
    """原子落盘。失败不抛 —— 历史写不进去不该影响搜索本身。"""
    global _dirty
    try:
        _DB.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "items": _items[:_MAX_ITEMS]}
        tmp = _DB.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, _DB)
        _dirty = False
    except Exception as e:  # noqa: BLE001
        log_event(logger, "history.save.fail", 原因=str(e)[:120])


def add_search(kw: str, hits: int = 0) -> None:
    """记一次搜索。

    `hits` 传本次命中的候选数 —— 0 表示"搜了但什么都没搜到"，
    这类词在热词榜里要单独标出来，是**书库缺口**的直接证据。
    """
    global _dirty
    kw = _clean_kw(kw)
    if not kw:
        return
    now = time.time()
    with _lock:
        _load()
        hit = None
        for it in _items:
            if it["kw"] == kw:
                hit = it
                break
        if hit is None:
            _items.insert(0, {"kw": kw, "ts": now, "count": 1, "hits": int(hits)})
        else:
            hit["ts"] = now
            hit["count"] += 1
            hit["hits"] = int(hits)
            # 重排到最前 —— 列表按"最近搜过"排序
            _items.remove(hit)
            _items.insert(0, hit)
        del _items[_MAX_ITEMS:]
        _dirty = True
        _save()


def get_recent(limit: int = 20) -> list[dict[str, Any]]:
    """最近搜过的词（按时间倒序）。**只读，不落盘。**"""
    with _lock:
        _load()
        n = max(1, min(int(limit or 20), _MAX_ITEMS))
        return [dict(it) for it in _items[:n]]


def get_hot(limit: int = 20) -> list[dict[str, Any]]:
    """热门搜索词（按搜索次数倒序）。

    ⚠ 与 get_recent 是两个不同的维度：最近 = 时间序，热门 = 次数序。
    界面上「最近搜索」用前者，「大家都在搜」用后者。
    """
    with _lock:
        _load()
        n = max(1, min(int(limit or 20), _MAX_ITEMS))
        ranked = sorted(_items, key=lambda it: (-it["count"], -it["ts"]))
        return [dict(it) for it in ranked[:n]]


def delete(kw: str) -> bool:
    """删一个词。返回是否真删掉了。"""
    kw = _clean_kw(kw)
    if not kw:
        return False
    with _lock:
        _load()
        for i, it in enumerate(_items):
            if it["kw"] == kw:
                _items.pop(i)
                _save()
                log_event(logger, "history.del", 词=kw)
                return True
        return False


def clear() -> int:
    """清空历史。返回删掉的条数。"""
    with _lock:
        _load()
        n = len(_items)
        _items.clear()
        if n:
            _save()
        log_event(logger, "history.clear", 条数=n)
        return n


def stats() -> dict[str, Any]:
    """给界面看的体检：总词数、累计搜索次数、搜不到的词有几个。

    「搜不到的词」是这里最有价值的一栏 —— 它们直接指向书库缺口。
    """
    with _lock:
        _load()
        total_searches = sum(int(it["count"]) for it in _items)
        empty = [dict(it) for it in _items if int(it.get("hits") or 0) <= 0]
        return {
            "words": len(_items),
            "searches": total_searches,
            "empty": len(empty),
            "empty_words": [it["kw"] for it in empty[:20]],
            "latest": int(_items[0]["ts"]) if _items else 0,
        }
