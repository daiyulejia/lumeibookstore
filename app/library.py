"""本地书架 —— 让「阅读」不再等于「抓网页」。

为什么要有这一层
----------------
之前点「预览」是现场去抓：抓目录 → 抓第一章 → 慢，而且关掉页面就没了。
这一层把书落到磁盘，于是：

  * **秒开**      目录已缓存，打开即出
  * **翻页不卡**  章节命中缓存直接返回，不命中才联网补一章
  * **离线可读**  已缓存的章节断网也照看
  * **进度留痕**  关掉浏览器再回来，接着上次的位置读
  * **一本一档**  同一本书重复打开不会重复抓

目录结构::

    library/
      <book_id>/
        meta.json        书籍信息 + 阅读进度
        toc.json         目录（[{index,title,url}]）
        ch/0001.json     单章正文（一章一个文件）
        ch/0002.json

单章一个文件是刻意的：1500 章的书如果塞进一个 JSON，每缓存一章都要重写整个
文件；而且写到一半断电会毁掉整本。一章一档，写入是原子的，坏也只坏一章。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

LIBRARY_DIR = Path(__file__).resolve().parent.parent / "library"

_write_lock = threading.Lock()


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def book_id(source: str, url: str) -> str:
    """由「来源 + 详情页地址」推出稳定的 id。

    稳定很重要：同一本书检索两次应该是同一个书架位，否则进度就丢了。
    """
    raw = f"{source}|{url}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()[:14]


def _atomic_write(path: Path, text: str) -> None:
    """先写临时文件再替换 —— 避免写到一半进程被杀留下半截 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=1))


def _index_path(idx: int) -> str:
    return f"{int(idx):05d}.json"


def valid_id(bid: str) -> bool:
    """书架 id 只允许 14 位十六进制 —— 挡住 ../ 之类的路径穿越。"""
    return bool(re.fullmatch(r"[0-9a-f]{6,32}", bid or ""))


# ---------------------------------------------------------------------------
# 书架
# ---------------------------------------------------------------------------
class Library:
    def __init__(self, root: Path = LIBRARY_DIR):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- 路径 -------------------------------------------------------------
    def _dir(self, bid: str) -> Path:
        if not valid_id(bid):
            raise ValueError(f"非法书架 id: {bid!r}")
        return self.root / bid

    # -- 创建 / 读取 -------------------------------------------------------
    def exists(self, bid: str) -> bool:
        return valid_id(bid) and (self._dir(bid) / "meta.json").exists()

    def ensure(
        self,
        source: str,
        url: str,
        title: str = "",
        author: str = "",
        intro: str = "",
        *,
        source_display: str = "",
        extra: Optional[dict] = None,
    ) -> dict:
        """拿到（或新建）一本书的书架记录，返回 meta。"""
        bid = book_id(source, url)
        d = self._dir(bid)
        meta = _read_json(d / "meta.json")
        if meta:
            # 已有记录：把新拿到的元信息补进去（搜索页的作者通常更准）
            changed = False
            for k, v in (("title", title), ("author", author), ("intro", intro)):
                if v and not meta.get(k):
                    meta[k] = v
                    changed = True
            if changed:
                _write_json(d / "meta.json", meta)
            return meta

        now = time.time()
        meta = {
            "id": bid,
            "title": title or "未命名",
            "author": author or "",
            "source": source,
            "source_display": source_display or source,
            "url": url,
            "intro": intro or "",
            "created": now,
            "updated": now,
            "opened": now,
            "total": 0,          # 目录总章数
            "cached": 0,         # 已缓存正文字数
            "status": "new",     # new | toc | caching | ready | failed
            "position": {"index": 1, "percent": 0.0, "offset": 0, "updated": now},
            "quality": {},
        }
        if extra:
            meta.update(extra)
        with _write_lock:
            _write_json(d / "meta.json", meta)
        return meta

    def meta(self, bid: str) -> Optional[dict]:
        if not valid_id(bid):
            return None
        return _read_json(self._dir(bid) / "meta.json")

    def update(self, bid: str, **fields) -> Optional[dict]:
        with _write_lock:
            meta = _read_json(self._dir(bid) / "meta.json")
            if not meta:
                return None
            meta.update(fields)
            meta["updated"] = time.time()
            _write_json(self._dir(bid) / "meta.json", meta)
            return meta

    # -- 目录 -------------------------------------------------------------
    def save_toc(self, bid: str, chapters: Iterable) -> list[dict]:
        toc = []
        for c in chapters:
            if isinstance(c, dict):
                toc.append({"index": int(c.get("index", 0)),
                            "title": str(c.get("title", "")),
                            "url": str(c.get("url", ""))})
            else:
                toc.append({"index": int(c.index), "title": c.title, "url": c.url})
        _write_json(self._dir(bid) / "toc.json", toc)
        self.update(bid, total=len(toc))
        return toc

    def toc(self, bid: str) -> list[dict]:
        if not valid_id(bid):
            return []
        return _read_json(self._dir(bid) / "toc.json", []) or []

    # -- 章节 -------------------------------------------------------------
    def chapter(self, bid: str, index: int) -> Optional[dict]:
        if not valid_id(bid):
            return None
        return _read_json(self._dir(bid) / "ch" / _index_path(index))

    def put_chapter(self, bid: str, index: int, title: str, content: str,
                    url: str = "") -> None:
        from .sources.base import tidy_content

        d = self._dir(bid) / "ch"
        d.mkdir(parents=True, exist_ok=True)
        _write_json(d / _index_path(index), {
            "index": int(index),
            "title": title,
            "content": tidy_content(content or "", title),
            "url": url,
            "ts": time.time(),
        })

    def has_chapter(self, bid: str, index: int) -> bool:
        return (self._dir(bid) / "ch" / _index_path(index)).exists()

    def cached_indexes(self, bid: str) -> set[int]:
        d = self._dir(bid) / "ch"
        if not d.exists():
            return set()
        out = set()
        for p in d.glob("*.json"):
            try:
                out.add(int(p.stem))
            except ValueError:
                continue
        return out

    def count_cached(self, bid: str) -> int:
        return len(self.cached_indexes(bid))

    def chapters_dir_size(self, bid: str) -> int:
        d = self._dir(bid) / "ch"
        if not d.exists():
            return 0
        return sum(p.stat().st_size for p in d.glob("*.json"))

    # -- 进度 -------------------------------------------------------------
    def set_position(self, bid: str, index: int, percent: float = 0.0,
                     offset: int = 0) -> Optional[dict]:
        with _write_lock:
            d = self._dir(bid)
            meta = _read_json(d / "meta.json")
            if not meta:
                return None
            meta["position"] = {
                "index": max(1, int(index)),
                "percent": round(max(0.0, min(1.0, float(percent))), 4),
                "offset": max(0, int(offset)),
                "updated": time.time(),
            }
            meta["opened"] = time.time()
            _write_json(d / "meta.json", meta)
            return meta

    def touch_opened(self, bid: str) -> None:
        self.update(bid, opened=time.time())

    # -- 列表 / 删除 -------------------------------------------------------
    def list_books(self) -> list[dict]:
        out: list[dict] = []
        if not self.root.exists():
            return out
        for d in self.root.iterdir():
            if not d.is_dir() or not valid_id(d.name):
                continue
            meta = _read_json(d / "meta.json")
            if not meta:
                continue
            meta["cached"] = self.count_cached(d.name)
            meta["size"] = self.chapters_dir_size(d.name)
            out.append(meta)
        out.sort(key=lambda m: -(m.get("opened") or m.get("created") or 0))
        return out

    def delete(self, bid: str) -> bool:
        d = self._dir(bid)
        if not d.exists():
            return False
        shutil.rmtree(d, ignore_errors=True)
        return True

    def stats(self) -> dict:
        books = self.list_books()
        return {
            "books": len(books),
            "chapters": sum(b.get("cached", 0) for b in books),
            "size": sum(b.get("size", 0) for b in books),
        }
