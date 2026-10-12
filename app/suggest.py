"""书名确认与纠错 —— 先确认，再开搜。

用户敲进来的东西很少是干净的书名：

    《微微一笑很倾城》
    微微一笑很倾城 小说
    微微一笑很倾城_全文阅读_最新章节
    微微一笑很倾城（顾漫）txt下载
    唯美一笑很倾城        ← 打错了

如果直接拿这串去检索，命中率会很低，用户还会以为「这网站真烂」。
所以搜之前先做两件事：

1. **归一化**  把书名从这堆噪音里剥出来（去《》、去 SEO 尾巴、去括号里的作者、
   繁转简、去多余空格）。
2. **给候选**  拿本地站点索引 + 书架藏书 + 内置热门书单做模糊匹配，
   音近（微微 / 唯唯）也算命中 —— 拼音相同基本就是打错了字。

只有当「归一化后和原输入不一样」或者「找到了相近的书」时才提示用户确认，
否则直接搜 —— 别没事找事打断人。
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Iterable, Optional

try:
    from zhconv import convert as _zh_convert
except Exception:  # noqa: BLE001
    def _zh_convert(s: str, _variant: str = "zh-cn") -> str:
        return s

try:
    from pypinyin import lazy_pinyin as _lazy_pinyin
except Exception:  # noqa: BLE001
    def _lazy_pinyin(s: str) -> list[str]:
        return list(s)


# 书名后面常见的「尾巴」，全部当噪音剥掉
_TAIL_NOISE = [
    "全文阅读", "免费阅读", "在线阅读", "无弹窗", "无弹窗广告", "最新章节",
    "最新章节列表", "全文免费阅读", "小说在线阅读", "txt下载", "TXT下载",
    "下载", "笔趣阁", "全文免费", "免费全文", "小说", "在线", "看书",
    "手机版", "顶点", "首发", "完结", "全本", "精校版", "完整版",
]
_NOISE_RE = re.compile("|".join(re.escape(x) for x in _TAIL_NOISE))
_PAREN_RE = re.compile(r"[（(【\[][^）)】\]]{0,20}[）)】\]]")
_BRACKET_RE = re.compile(r"[《》〈〉「」『』\u3000]")
_SEP_RE = re.compile(r"[_\-—–|/\\,，.。!！?？:：;；'\"“”‘’*#~^]+")


def normalize(raw: str) -> str:
    """把用户输入剥成一个干净书名。"""
    s = _zh_convert((raw or "").strip(), "zh-cn")
    s = _BRACKET_RE.sub("", s)
    s = _PAREN_RE.sub("", s)          # 括号里通常是作者名 / 卷号
    s = _SEP_RE.sub(" ", s)
    s = _NOISE_RE.sub(" ", s)
    s = re.sub(r"\s+", "", s)         # 中文书名里的空格基本都是噪音
    return s.strip()


def clean_keyword(raw: str) -> str:
    """归一化，但太激进时退回去（别把用户真正想搜的名字削没了）。"""
    n = normalize(raw)
    if len(n) < 2:
        return (raw or "").strip()
    return n


def is_suspect(raw: str) -> bool:
    """输入「需要确认」吗？（归一化后明显变了 / 明显有问题）"""
    r = (raw or "").strip()
    if not r:
        return False
    if len(r) > 40:
        return True
    n = normalize(r)
    if not n:
        return True
    return n != r


def _pinyin(s: str) -> str:
    return "".join(_lazy_pinyin(s)).lower()


# ---------------------------------------------------------------------------
# 候选索引
# ---------------------------------------------------------------------------
_BUILTIN_POPULAR = [
    "斗破苍穹", "斗罗大陆", "完美世界", "遮天", "凡人修仙传", "仙逆", "武动乾坤",
    "大主宰", "元尊", "神墓", "将夜", "雪中悍刀行", "剑来", "诡秘之主", "宿命之环",
    "庆余年", "间客", "大道朝天", "择天记", "诛仙", "飘邈之旅", "星辰变", "盘龙",
    "吞噬星空", "九鼎记", "莽荒纪", "飞剑问道", "沧元图", "一念永恒", "我欲封天",
    "求魔", "仙逆", "三体", "球状闪电", "超新星纪元", "流浪地球", "活着", "许三观卖血记",
    "兄弟", "平凡的世界", "白鹿原", "围城", "边城", "骆驼祥子", "四世同堂", "家",
    "春", "秋", "雷雨", "日出", "尘埃落定", "红高粱", "丰乳肥臀", "生死疲劳", "蛙",
    "檀香刑", "一句顶一万句", "我不是潘金莲", "手机", "一地鸡毛", "温故一九四二",
    "狼图腾", "藏地密码", "鬼吹灯", "盗墓笔记", "沙海", "老九门", "黄河鬼棺",
    "考古手记", "茅山后裔", "民调局异闻录", "苗疆蛊事", "最后一个道士",
    "微微一笑很倾城", "何以笙箫默", "杉杉来吃", "你是我的荣耀", "顾漫",
    "步步惊心", "甄嬛传", "如懿传", "琅琊榜", "风起长林", "大明王朝1566",
    "人民的名义", "大江大河", "欢乐颂", "都挺好", "狂飙", "隐秘的角落",
    "红楼梦", "西游记", "水浒传", "三国演义", "聊斋志异", "儒林外史", "镜花缘",
    "封神演义", "东周列国志", "史记", "资治通鉴", "世说新语", "搜神记", "山海经",
    "傲慢与偏见", "简爱", "呼啸山庄", "悲惨世界", "巴黎圣母院", "战争与和平",
    "安娜卡列尼娜", "罪与罚", "卡拉马佐夫兄弟", "百年孤独", "霍乱时期的爱情",
    "老人与海", "了不起的盖茨比", "1984", "动物农场", "美丽新世界", "沙丘",
    "基地", "银河系漫游指南", "海伯利安", "安德的游戏", "机器人学三定律",
    "哈利波特", "魔戒", "冰与火之歌", "纳尼亚传奇", "地海传奇", "碟形世界",
    "沙僧日记", "悟空传", "此间的少年", "九州缥缈录", "海上牧云记", "羽传说",
    "龙族", "上海堡垒", "九州天空城", "天行健", "大秦帝国", "明朝那些事儿",
    "万历十五年", "万历首辅张居正", "曾国藩", "李鸿章", "苏东坡传", "王阳明",
    "苏菲的世界", "枪炮病菌与钢铁", "人类简史", "未来简史", "今日简史",
    "乡土中国", "乌合之众", "娱乐至死", "影响力", "思考快与慢", "原则",
]


class TitleIndex:
    """书名候选索引。数据源：本地站点索引 + 书架藏书 + 内置热门书单。"""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = Path(cache_dir) if cache_dir else \
            Path(__file__).resolve().parent.parent / "cache"
        self._titles: Optional[list[str]] = None
        self._ts = 0.0

    # -- 数据 -------------------------------------------------------------
    def _load(self) -> list[str]:
        titles: set[str] = set(_BUILTIN_POPULAR)

        # 本地爬下来的站点索引（无忧书城等）
        idx = self.cache_dir / "wyshu_index.json"
        if idx.exists():
            try:
                data = json.loads(idx.read_text(encoding="utf-8"))
                books = data.get("books") if isinstance(data, dict) else None
                if isinstance(books, dict):
                    titles.update(books.keys())
            except Exception:  # noqa: BLE001
                pass

        # 书架里已经有的书
        try:
            lib = Path(__file__).resolve().parent.parent / "library"
            if lib.exists():
                for d in lib.iterdir():
                    if not d.is_dir():
                        continue
                    m = d / "meta.json"
                    if m.exists():
                        try:
                            titles.add(json.loads(m.read_text(encoding="utf-8"))["title"])
                        except Exception:  # noqa: BLE001
                            pass
        except Exception:  # noqa: BLE001
            pass

        return sorted(t for t in titles if t and len(t) >= 2)

    def titles(self) -> list[str]:
        import time

        if self._titles is None or time.time() - self._ts > 300:
            self._titles = self._load()
            self._ts = time.time()
        return self._titles

    # -- 查询 -------------------------------------------------------------
    def suggest(self, raw: str, limit: int = 6, floor: float = 0.55) -> list[dict]:
        kw = normalize(raw)
        if len(kw) < 2:
            return []

        kp = _pinyin(kw)
        scored: list[tuple[float, str, str]] = []
        for t in self.titles():
            tn = normalize(t)
            if not tn:
                continue
            s, why = 0.0, ""
            if tn == kw:
                s, why = 1.0, "完全匹配"
            elif tn.startswith(kw) or kw.startswith(tn):
                s, why = 0.93 - min(abs(len(tn) - len(kw)) * 0.02, 0.2), "开头一致"
            elif kw in tn or tn in kw:
                s, why = 0.86 - min(abs(len(tn) - len(kw)) * 0.02, 0.25), "包含"
            else:
                r = difflib.SequenceMatcher(None, kw, tn).ratio()
                pr = difflib.SequenceMatcher(None, kp, _pinyin(tn)).ratio()
                if pr > r and pr >= 0.75:
                    s, why = pr * 0.9, "读音接近"
                else:
                    s = r * 0.85
                    why = "形近"
                # 长度差太大肯定不是同一本
                if abs(len(tn) - len(kw)) > 4:
                    s *= 0.55
            if s >= floor:
                scored.append((s, t, why))

        scored.sort(key=lambda x: (-x[0], len(x[1])))
        out, seen = [], set()
        for s, t, why in scored:
            if t in seen:
                continue
            seen.add(t)
            out.append({"title": t, "score": round(s, 3), "reason": why})
            if len(out) >= limit:
                break
        return out


_index: Optional[TitleIndex] = None


def default_index() -> TitleIndex:
    global _index
    if _index is None:
        _index = TitleIndex()
    return _index


def confirm(raw: str, *, limit: int = 6) -> dict:
    """给前端用的「确认一下」结果。

    返回::

        {
          "raw":      原始输入,
          "keyword":  归一化后打算真正拿去搜的词,
          "changed":  是否和原始输入不同,
          "suspect":  是否建议确认,
          "exact":    本地索引里是否有完全同名的书,
          "suggestions": [{title, score, reason}, ...],
        }
    """
    r = (raw or "").strip()
    kw = clean_keyword(r)
    idx = default_index()
    sugg = idx.suggest(r, limit=limit)
    exact = any(s["score"] >= 0.999 for s in sugg)
    return {
        "raw": r,
        "keyword": kw,
        "changed": kw != r,
        "suspect": is_suspect(r) or (bool(sugg) and not exact),
        "exact": exact,
        "suggestions": sugg,
        "index_size": len(idx.titles()),
    }
