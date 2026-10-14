"""数据模型定义。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BookResult:
    """一个搜索到的候选书籍。"""

    title: str
    author: str = ""
    source: str = ""          # 来源适配器名称
    url: str = ""             # 详情页地址
    intro: str = ""           # 简介
    latest_chapter: str = ""  # 最新章节

    # —— 搜索后的加工字段 ——
    score: float = 0.0              # 相关性得分（越高越相关）
    available: bool | None = None   # None=未探测 / True=可用 / False=打不开
    chapter_count: int = 0          # 探测到的章节数
    note: str = ""                  # 探测备注（不可用原因等）
    probe_ms: int = 0               # 探测耗时

    # 目录"看起来只有一部分"时的说明（如「站点显示最新章节是第 109 章，
    # 这里只列到第 50 章」）。为什么必须单独一个字段而不是塞进 note：
    # note 只在 available=False 时才显示，而**这个警告恰恰出现在可用的书上** ——
    # 塞进去等于永远看不见。见 webfetch.toc_completeness()。
    chapter_note: str = ""

    # —— 深度校验（抽样正文）——
    # 目录能打开不等于正文能看：有的站目录是静态页，正文要登录；
    # 有的站被限流后返回一页广告。must 抽一章真读一下才算数。
    sample_ok: bool | None = None   # None=没结论 / True=正文正常 / False=有问题
    sample_chars: int = 0           # 抽样章节的正文字数
    sample_note: str = ""           # 抽样发现的问题
    sampled: bool = False           # **有没有真的去抽过**（区别「没抽」和「抽了但没结论」）

    source_display: str = ""        # 来源中文名（探测时回填）
    library_id: str = ""            # 已入书架的话给出 id
    # 封面图（探测时打开详情页顺手扒到的 og:image）。空字符串 = 这站没有，
    # 前端渲染渐变兜底封面 —— 不留空框，也不影响任何判断逻辑。
    cover: str = ""

    # —— 「这到底是不是同一本书」——
    # 书名撞词比想象中严重：搜《活着》，一堆站会返回「原神：活着」
    # 「我怎么还活着」「生活不止是活着」。它们确实包含关键词、打分也不低，
    # 但不是这本书。tightness 就是「关键词占了标题多大比重」，
    # 1.0 = 基本就是这本书，0 = 只是沾边。见 relevance.tightness()。
    tightness: float = 0.0

    # 这条候选是**因为作者名命中**才被选中的（关键词没出现在书名里）。
    # 前端据此提示「按作者找到了 N 本」，让用户知道"这不是书名匹配、
    # 而是按作者捞的一批"，避免他看到一堆书名对不上的结果以为是搜坏了。
    by_author: bool = False

    @property
    def tight(self) -> bool:
        """是否算「确切命中」。"""
        return self.tightness >= 0.99

    @property
    def display_title(self) -> str:
        """给用户看的书名 —— 剥掉站点硬塞的分类/序号前缀。

        原始 `title` 保留不动（去重键、探测匹配都依赖它），只在展示层清洗：
        用户该看到「斗破苍穹」，不是「[玄幻]斗破苍穹」。
        """
        from .relevance import clean_title
        return clean_title(self.title)

    @property
    def readable(self) -> bool:
        """真的能读吗？—— **要有正面证据**，没验证过就不算数。

        三态：
          · sample_ok=True                → 抽过、正文正常 → 可读
          · sample_ok=False               → 抽过、是假的（登录页/控件页）→ 不可读
          · sample_ok=None 且 sampled=True → 抽过，但这个来源压根没有单章接口
                                            （维基文库、Gutenberg 这类）
                                            → 目录可达就算可读
          · sample_ok=None 且没抽过        → **未验证** → 不算可读

        最后一条是踩过坑的：抽样有条「同一来源最多抽两本」的省时规则，
        而联网发现是一个来源底下挂着几十个站 —— 没抽到的那几个
        原先会被算成「可读」，界面上显示得好好的，点进去一个字都没有。
        """
        if not self.available:
            return False
        if self.sample_ok is not None:
            return bool(self.sample_ok)
        return self.sampled   # 抽过但没结论，才算可读；压根没抽 → 不认

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            # 展示用书名（剥掉 [玄幻] 这类站点分类前缀）；前端优先用它
            "display_title": self.display_title,
            "author": self.author,
            "source": self.source,
            "source_display": self.source_display or self.source,
            "url": self.url,
            "intro": self.intro,
            "latest_chapter": self.latest_chapter,
            "score": round(self.score, 1),
            "available": self.available,
            "chapter_count": self.chapter_count,
            "note": self.note,
            "chapter_note": self.chapter_note,
            "probe_ms": self.probe_ms,
            "sample_ok": self.sample_ok,
            "sample_chars": self.sample_chars,
            "sample_note": self.sample_note,
            "sampled": self.sampled,
            "readable": self.readable,
            "library_id": self.library_id,
            "cover": self.cover,
            "tightness": round(self.tightness, 2),
            "tight": self.tight,
            "by_author": self.by_author,
        }


@dataclass
class Chapter:
    """一章内容。"""

    index: int
    title: str
    content: str = ""
    url: str = ""

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "title": self.title,
            "url": self.url,
            "length": len(self.content or ""),
        }


@dataclass
class Book:
    """一本书的完整信息。"""

    title: str
    author: str = ""
    source: str = ""
    url: str = ""
    intro: str = ""
    chapters: list[Chapter] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "author": self.author,
            "source": self.source,
            "url": self.url,
            "intro": self.intro,
            "chapter_count": len(self.chapters),
        }
