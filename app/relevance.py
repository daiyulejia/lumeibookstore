"""搜索结果的相关性打分与去噪。

解决的问题
----------
多源搜索时，有些来源（尤其是维基文库这类全文检索的库）会把「正文里提到过
关键词」的页面也返回回来，例如搜索《微微一笑很倾城》会搜出

    北京互联网法院（2021）京0491民初9699号民事判决书

原因：判决书正文里提到了这本书名，但**它不是这本书**。

判定原则
--------
对「找一本书」这个场景来说，**标题匹配才是有效信号，正文命中是噪音**。
因此打分以标题为主：

    标题完全等于关键词        100 分
    标题以关键词开头/结尾      最高 92 分（越短越精确）
    标题包含关键词             最高 85 分
    关键词包含标题             70 分
    模糊相似（书名略有差异）    最多 60 分
    仅正文/简介命中            -25 分惩罚

再叠加「明显不是书」的黑名单惩罚（判决书/模板/分类/列表……），低于阈值直接丢弃。
"""
from __future__ import annotations

import re
import difflib

from .models import BookResult

# 繁简转换（维基文库等站点返回繁体标题，需要先统一再比对）
try:
    from zhconv import convert as _zh_convert

    def _to_simplified(s: str) -> str:
        try:
            return _zh_convert(s, "zh-cn")
        except Exception:  # noqa: BLE001
            return s

except Exception:  # noqa: BLE001
    def _to_simplified(s: str) -> str:
        return s

# 明显不是「一本小说」的标题特征
NOISE_RE = re.compile(
    r"民事判决书|判决书|裁定书|刑事判决|不起诉决定书|调解书"
    r"|人民法院|人民检察院|法院|审判|案号|律师|原告|被告|上诉人|被上诉人"
    r"|民初|民终|刑初|行初|知民|京\d{4}|沪\d{4}|粤\d{4}"
    r"|^模板:|^分类:|^Category:|^Help:|^维基百科:|^Wikipedia:|^讨论:|^User:|^用户:"
    r"|^文件:|^File:|^Portal:|^主题:|^草稿:|^Draft:"
    r"|消歧义|词条|百科|帮助|使用说明|编辑指南|沙盒|首页$|著作权|版权信息"
    r"|维基文库|Wikisource|MediaWiki"
    r"|^-{2,}|列表$|索引$|书目$|总目$|目录$|年表$|年谱$|全覽$|全览$"
    r"|^\d{4}年|通稿|公告$|通知$|声明$",
    re.I,
)

# 书名里常见的 SEO 尾巴，打分时先剥掉
#
# 「站点名后缀」单独列一组（笔趣阁 / 小说网 / 阅读网 …）—— 它不只是难看，
# 还会让**同一本书的两条结果合不到一起**：
#   实测搜《欢迎进入梦魇直播间》，m.akshu88.com 回了同一本书两条：
#     欢迎进入梦魇直播间           /book/101965698.html
#     欢迎进入梦魇直播间笔趣阁       /book/j101965698.html
#   第二条的"笔趣阁"是**站点名**被拼进标题了。去重键是 normalize(title)，
#   两条键不同 → 各自留一条，用户看到"两个来源"，其实是一个站一本书。
#   而 tightness 的容差是 len(kw)//3 = 3，"笔趣阁"正好 3 字 → 还判成确切命中，
#   于是一条重复项以"正主"的身份混在结果里。
SEO_TAIL_RE = re.compile(
    r"(?:全文阅读|在线阅读|免费阅读|最新章节|无弹窗|完结版|TXT下载|txt下载|手机版|免费"
    r"|笔趣阁|小说网|阅读网|文学网|读书网|小说阅读网|书吧|书城)+$"
)

# 站点把**分类**拼进书名了：「[玄幻]斗破苍穹」「[网游]穿越斗破苍穹」。
# 这是最脏的一类前缀 —— 它不只是难看，还会**破坏同一本书的判定**：
#
#   [玄幻]斗破苍穹        tightness = 0.67   （多出"玄幻"2字，超出容差1）
#   [网游]穿越斗破苍穹      tightness = 0.00   （多出"网游穿越"4字，判定为另一本书）
#   斗破苍穹              tightness = 1.00   （正主）
#
# 结果：搜《斗破苍穹》，真正那本因为带前缀被判定"不是它"，
# 一堆《斗破苍穹之XXX》同人反而排在前面。
#
# 规则：**只有**方括号/书名号里是纯分类词（2~4 字、不含数字和"之"等连接词）
# 且位于标题最开头时才剥 —— 不敢宽，因为《[综]xxx》《[HP]xxx》这类
# 同人圈的方括号是作品名的一部分，剥了就错了。
_CATEGORY_WORDS = (
    r"玄幻|奇幻|武侠|仙侠|都市|言情|历史|军事|游戏|网游|科幻|悬疑|恐怖|"
    r"灵异|推理|竞技|校园|职场|穿越|重生|系统|修真|现代|古代|古言|现言|"
    r"耽美|百合|轻小说|同人|二次元|综漫|豪门|总裁|宫斗|宅斗|种田|末世|"
    r"无限流|快穿|异能|热血|青春|文学|名著|外国文学|中国文学|当代|纪实"
)
_CATEGORY_PREFIX_RE = re.compile(
    r"^\s*[\[【（(《〈]\s*(?:" + _CATEGORY_WORDS + r")\s*[\]】）)）》〉]\s*"
)


def strip_category_prefix(title: str) -> str:
    """剥掉标题开头的**纯分类**前缀（「[玄幻]斗破苍穹」→「斗破苍穹」）。

    只认白名单里的分类词，且必须被方括号完整包住。剥不出来就原样返回 ——
    宁可留着脏前缀，也不能把《[HP]魔法觉醒》这种真的带方括号的书名改坏。
    """
    s = title or ""
    out = _CATEGORY_PREFIX_RE.sub("", s, count=1).strip()
    # 剥完不能把标题掏空（「[玄幻]」这种只有分类的站内页，留着原样）
    return out if len(out) >= 2 else s


# 全角/半角方括号包着**单字或两位**数字：「[1]活着」「【12】活着」——
# 那是列表编号，同样不该算进书名。
_INDEX_PREFIX_RE = re.compile(r"^\s*[\[【（(]\s*\d{1,3}\s*[\]】）)]\s*")


def clean_title(title: str) -> str:
    """给**展示用**的清洗：剥掉分类前缀与序号前缀。

    与 normalize() 的区别：normalize 是给比对用的（去掉所有标点），
    clean_title 保留书名本身的可读性，只是把站点硬塞的前缀拿掉。
    """
    s = (title or "").strip()
    prev = None
    while prev != s:
        prev = s
        s = _INDEX_PREFIX_RE.sub("", s).strip()
        s = strip_category_prefix(s)
    return s or (title or "").strip()

# 「評論/研究/考證」类页面：相关但不是书本身
# 注意：匹配前标题已转简体，所以这里只需写简体词
ABOUT_RE = re.compile(
    r"考证|研究|赏析|解读|评论|浅谈|漫谈|札记|校注|笺注"
    r"|^(谈|论|评|说|读|评点)"
    r"|维基百科|百度百科|豆瓣"
)

# 「紅樓夢/第01回」这类是**章节页**，不是书本身
CHAPTER_PAGE_RE = re.compile(
    r"/(?:第?\s*[0-9一二三四五六七八九十百千]+\s*[回章节卷篇]"
    r"|[卷部篇辑]\s*[0-9一二三四五六七八九十百千]+"
    r"|[0-9]{1,4})$"
)

# 「第216章 活着」「149.我爱你」——**章节名被当成书名**返回了。
# 有些站的搜索接口是按「章」检索的（鲲弩小说的 WordPress 搜索就是按 post 搜，
# 返回的全是章节），于是搜「活着」会出来一堆「第70章 人人都这么活着」。
# 这类显然不是书，重罚；但若用户自己搜的就是章节名，就不判。
CHAPTER_TITLE_RE = re.compile(
    r"^\s*(?:第\s*[0-9零一二两三四五六七八九十百千]+\s*[章节回卷篇]"
    r"|[0-9]{1,4}\s*[.、,，:：])"
)

# 标点/空白归一化时忽略的字符
_PUNCT_RE = re.compile(
    r"[\s\u3000《》〈〉“”‘’'\"()（）\[\]【】{}:：;；,，.。!！?？·、\-—_~～|/\\*#]+"
)


def normalize(s: str) -> str:
    """书名归一化：剥分类前缀与 SEO/站点名尾巴 + 繁转简 + 去标点 + 转小写。

    ⚠ 「剥尾巴」必须在这里做，**不能只在 tightness/score 里做** ——
    去重键用的是 `normalize(title)`（见 _dedup），只在打分里剥会导致
    同一本书的两个标题归一化后仍然不同，去重白做：

        欢迎进入梦魇直播间          → 欢迎进入梦魇直播间
        欢迎进入梦魇直播间笔趣阁      → 欢迎进入梦魇直播间笔趣阁   ← 键不同，留两条

    实测就是 m.akshu88.com 那两条（/book/101965698.html 与
    /book/j101965698.html），用户看到"两个来源"，其实是同一个站同一本书。
    """
    s = _to_simplified((s or "").lower())
    # 先剥掉带标点形态的尾巴（「三体（全文阅读）」→「三体」），再去标点
    s = _strip_tail_paren(s.strip())
    s = SEO_TAIL_RE.sub("", s).strip()
    return _PUNCT_RE.sub("", s)


def _tokens(s: str) -> list[str]:
    """粗略切词（中文按 2-gram，英文按单词），用于计算覆盖率。"""
    s = normalize(s)
    if not s:
        return []
    if re.search(r"[a-z]", s):
        return re.findall(r"[a-z]+|\d+", s) or [s]
    if len(s) <= 2:
        return [s]
    return [s[i : i + 2] for i in range(len(s) - 1)]


# 标题尾部的括号注释：「微微一笑很倾城（顾漫 著）」「三体（全集）」
# 这些是**版本/作者**信息，不是书名本身的一部分，算长度时先剥掉。
_TAIL_PAREN_RE = re.compile(r"[（(【\[][^（()）【】\[\]]*[）)】\]]\s*$")


def _strip_tail_paren(s: str) -> str:
    """反复剥掉结尾的括号注释。"""
    prev = None
    while prev != s:
        prev = s
        s = _TAIL_PAREN_RE.sub("", s).strip()
    return s


def tightness(title: str, keyword: str) -> float:
    """关键词在标题里「占得多满」—— 用来判断这是不是**同一本书**。

    分数（score）回答的是「这条结果有多可能出现我们要的书」，
    它挡得住判决书，挡不住撞词：

        搜《活着》 → xbqg5200 返回「原神：活着」「我怎么还活着」
                     「生活不止是活着」「黑山启示录：活着」

    这些标题都包含关键词、都是真书，打分也都在 70~92，光按分数筛不掉。
    但它们显然**不是余华的《活着》**。区别在于多出来的那截有多长：

        活着      vs  活着                多 0 字   → 就是它
        三体      vs  三体（全集）         剥括号后相等 → 就是它
        微微一笑很倾城 vs ...（顾漫 著）    剥括号后相等 → 就是它
        活着      vs  原神：活着           多 2 字   → 存疑
        活着      vs  我怎么还活着         多 4 字   → 不是它
        三体      vs  三体唐诗四库全书本    多 8 字   → 不是它

    所以容差是**关键词长度的三分之一（至少 1 字）**，再叠加一次括号码的剥离：
    书名越长，允许的修饰越多；书名只有两个字时，多一个字都算另起炉灶。
    """
    kw = normalize(keyword)
    if not kw:
        return 0.0
    # 先把站点的分类前缀剥掉再算「占多满」——
    # 「[玄幻]斗破苍穹」的"玄幻"会让 tightness 从 1.0 掉到 0.67，
    # 正主反被判定成"不是这本书"（见 strip_category_prefix 注释）。
    simp = _to_simplified(clean_title(title))
    stripped = SEO_TAIL_RE.sub("", _strip_tail_paren(simp.strip()))
    t = normalize(stripped if len(stripped) >= 2 else simp)
    if not t or kw not in t:
        return 0.0
    extra = len(t) - len(kw)
    if extra <= 0:
        return 1.0
    allow = max(1, len(kw) // 3)
    if extra <= allow:
        return 1.0
    return max(0.0, 1.0 - (extra - allow) / (allow + 2.0))


def score(result: BookResult, keyword: str) -> float:
    """给一个候选打相关性分（0~100，可因惩罚为负）。"""
    kw = normalize(keyword)
    if not kw:
        return 0.0

    raw_title = result.title or ""
    # 统一转简体后再做所有模式匹配 —— 否则维基文库的「消歧義/考證」匹配不上
    # 简体词表，繁体噪音就会漏网。
    # 先剥分类前缀（「[玄幻]斗破苍穹」→「斗破苍穹」），否则整条打分会走偏。
    simp_title = _to_simplified(clean_title(raw_title))
    stripped = SEO_TAIL_RE.sub("", _strip_tail_paren(simp_title.strip()))
    t = normalize(stripped if len(stripped) >= 2 else simp_title)
    if not t:
        return 0.0

    # 「到底是不是同一本书」先算出来挂在结果上，供 rank() 事后判断。
    result.tightness = tightness(raw_title, keyword)

    # —— 1. 标题匹配 ——
    if t == kw:
        s = 100.0
    elif t.startswith(kw) or t.endswith(kw):
        s = 92.0 - min(len(t) - len(kw), 30)
    elif kw in t:
        s = 85.0 - min(len(t) - len(kw), 45)
    elif t in kw:
        s = 70.0
    else:
        # 只沾了个边（比如「原神：活着」和「活着」有共同字）——由相似度给分。
        ratio = difflib.SequenceMatcher(None, kw, t).ratio()
        s = ratio * 60.0 if ratio >= 0.55 else ratio * 15.0

    # —— 2. token 覆盖率：应对「微微一笑很倾城（顾漫 著）」「紅樓夢考證」这类 ——
    #     注意必须惩罚「多出来的字数」，否则「談《紅樓夢》作者的背景」会拿满分。
    kt, tt = set(_tokens(keyword)), set(_tokens(raw_title))
    extra = len(t) - len(kw)
    if kt and tt:
        cover = len(kt & tt) / len(kt)
        if cover >= 0.999 and extra <= 12:
            s = max(s, 96.0 - min(extra * 4.0, 62.0))
        elif cover >= 0.6:
            s = max(s, 50.0 + cover * 30.0 - min(max(extra, 0) * 2.0, 25.0))

    # —— 2.5 「短关键词 + 长标题」通常是**另一部作品** ——
    #     搜「三体」，维基文库会返回「三體唐詩（四庫全書本）」：
    #     它以关键词开头，于是蒙到 84 分，但其实是一本唐诗集。
    #     判据不是「多了几个字」，而是**关键词在标题里占多大比重**：
    #       三体 / 三体唐诗四库全书本   = 2/10  → 20%，判定为另一个作品
    #       微微一笑很倾城 / ...顾漫著  = 8/12  → 67%，正常通过
    #     用比例而不是字数差，是为了对长短关键词一视同仁。
    if kw and kw in t:
        ratio = len(kw) / max(len(t), 1)
        if ratio < 0.40:
            s -= min((0.40 - ratio) * 140.0, 40.0)

    # —— 2.8 作者匹配：搜「顾漫」应该能找到《微微一笑很倾城》——
    #     在这之前，关键词**全程只对书名匹配**（下面第 4 条那个 +2.0 只是
    #     "这条有作者信息、像个书目条目"，不是把关键词和 author 字段做比对）。
    #     于是搜作者名一个结果都出不来 —— 而"记得作者、记不清书名"是很常见的
    #     找书方式。
    #
    #     给分的分寸很关键，三条约束：
    #       ① 必须**显著低于**书名匹配（书名 85~100，这里封顶 72）。
    #          否则搜「活着」时，作者恰好叫「活着」的杂项页面会跟余华的书平起平坐。
    #       ② 只在**书名没匹配上**时才给分（`kw not in t`）。书名对了就别动它 ——
    #          作者命中是"退而求其次"的信号，不能反过来挤掉更准的。
    #       ③ 关键词得**整段**出现在作者字段里（normalize 后子串匹配），
    #          不做模糊 —— "作者名沾个边"太容易误伤。
    #     分数随作者名长度递减：单字作者名（「唐」）命中面太广，压到最低。
    if kw not in t and result.author:
        a = normalize(_to_simplified(result.author))
        # 去掉「著/作品集」之类的尾巴，否则「顾漫著」匹配不上关键词「顾漫」的边界判断
        a = re.sub(r"(著|编著|主编|作品|小说|文集|全集|译)$", "", a).strip()
        # ④ **单字关键词不给作者分**。名字只有一个字的人太多了
        #    （「唐」「白」「苏」），搜一个字就返回一堆"作者叫这个字"的书，
        #    是纯噪音 —— 用户想搜书名时看到这些会更困惑。
        #    两字是实际可用作者名的下限（顾漫 / 余华 / 莫言…）。
        if len(kw) >= 2 and a and kw in a:
            base = 72.0 - min(max(len(kw) - 2, 0) * 6.0, 24.0)
            if kw == a:
                base += 6.0            # 作者名与关键词完全一致 → 就是这个人
            s = max(s, base)
            # 打个标记，前端可以说「按作者找到了 N 本」
            result.by_author = True

    # —— 3. 噪音惩罚 ——
    if NOISE_RE.search(simp_title):
        s -= 75.0
    # 「某某书/第01回」是章节页，不是书
    if CHAPTER_PAGE_RE.search(simp_title.strip()):
        s -= 40.0
    # 带「/」的是维基类站点的**子页面**（「三體唐詩 (四庫全書本)/卷2」），
    # 它是书的组成部分，不该和书本身并列展示。
    if "/" in simp_title.strip() and "/" not in keyword:
        s -= 35.0
    # 标题本身就是个章节名 → 这说明来源的搜索接口是按章检索的，
    # 拿到的不是书。重罚，让它在阈值之下；真正能读的那些会在探测拿到
    # 真书名后被「回填重排」救回来（见 engine.refine）。
    if CHAPTER_TITLE_RE.match(simp_title.strip()) and not CHAPTER_TITLE_RE.match(keyword.strip()):
        s -= 45.0
    # 「某某书考证/研究/赏析」是二手资料，不是书本身
    if ABOUT_RE.search(simp_title) and not ABOUT_RE.search(keyword):
        s -= 25.0
    # 标题不命中、却出现在简介/摘要里 → 只是「被提到」，不是这本书
    if kw not in t:
        intro_n = normalize(result.intro)
        if kw in intro_n:
            s -= 25.0
        elif kt and intro_n:
            it = set(_tokens(result.intro))
            if kt and len(kt & it) / len(kt) >= 0.9:
                s -= 15.0

    # —— 4. 有作者信息略加分（说明是书籍条目而非杂项页面） ——
    if result.author and result.author.strip() not in ("", "未知作者", "佚名"):
        s += 2.0

    return s


def _adaptive_threshold(best: float, threshold: float) -> float:
    """根据最高分自适应决定门槛。

    找到了「就是这本书」的结果时，就只保留同一档次的候选，
    免得「关于某书的论文」混在真正的书目里让人挑花眼。
    """
    if best >= 95:
        return max(threshold, 68.0)
    if best >= 85:
        return max(threshold, 55.0)
    if best >= 70:
        return max(threshold, 42.0)
    return threshold


def _dedup(results: list[BookResult]) -> list[BookResult]:
    """同一个**站**里书名相同（含繁简/标点差异）的只留一条。

    小说站的搜索页常把同一本书挂在不同分类路径下，会出现两条一模一样的
    「红楼梦」，既浪费探测又要用户自己分辨。保留得分最高的那条。

    判「同一个站」而不是「同一个来源」是有原因的：联网发现（`web`）这一个
    来源底下挂着几十个不同的站，用来源名当键的话，搜一本书在 6 个站上都找到了，
    会被合并成 1 条 —— 用户就只剩一个选择，而且不知道还有别的站能读。
    所以键里必须带上域名。
    """
    best: dict[tuple[str, str, str], BookResult] = {}
    for r in results:
        k = (r.source, _host_of(r.url), normalize(r.title))
        cur = best.get(k)
        if cur is None or r.score > cur.score or (
            r.score == cur.score and r.chapter_count > cur.chapter_count
        ):
            best[k] = r
    keep = {id(v) for v in best.values()}
    return [r for r in results if id(r) in keep]


def _host_of(url: str) -> str:
    try:
        from urllib.parse import urlparse

        return (urlparse(url or "").hostname or "").lower()
    except Exception:  # noqa: BLE001
        return ""


# 多词搜索里「这个词算中了」的分数线。
#
# 为什么不能是 0：score() 末尾有一层兜底（有作者信息 +2.0；标题和关键词只沾
# 一点边时按相似度给分），导致**不相关**的结果也能拿到 2~15 分。用它判命中，
# 「余华 活着」里的《活着》/未知作者 会被认为"命中了余华"，跟正主并列第一。
#
# 取值 28 的依据：title 分支的最低有效分是「关键词包含标题」的 70 分、
# 「标题以关键词开头/结尾」最低 62 分、模糊相似命中我记得是 33 分起 ——
# 也就是说凡是"标题真的和这个词有关"的，都在 28 之上；28 以下全是兜底噪音。
_HIT_MIN = 28.0


def _split_terms(keyword: str) -> list[str]:
    """把「余华 活着」这类关键词拆成多个词。

    为什么要拆：「书名 + 作者」是最自然的搜法之一，界面上也提示用户
    "把作者名一起搜会准很多"。但在此之前，空格被当成书名的一部分 ——
    搜「余华 活着」会去找一本叫《余华活着》的书，结果必然是 0 条。

    分隔符：空白、加号、逗号、顿号。都拆。
    拆完每个词都要有实际内容（≥1 字），过滤空串。
    """
    s = (keyword or "").strip()
    if not s:
        return []
    parts = [p.strip() for p in re.split(r"[\s+,，、]+", s) if p.strip()]
    return parts


def score_multi(result: BookResult, keyword: str) -> float:
    """多词关键词的打分：逐词算，再按「命中几个词」加权。

    规则刻意保守 —— 多词是**收窄**条件的，不是放宽：
      · 一个词都没中的（书名也没中、作者也没中）→ 直接 0，踢掉。
      · 中了**部分**词 → 取命中词里的最高分，再按命中比例打折。
        搜「余华 活着」，只中"活着"的《活着》该留下但该排在
        「书名+作者都中」的后面。
      · **全中** → 在最高分基础上加成，确保排在部分命中的前面。

    为什么用"加成"而不是把两个词的分数相加：相加会让长书名虚高，
    而这里的目的是**排序**，不是绝对分值。
    """
    terms = _split_terms(keyword)
    if len(terms) <= 1:
        return score(result, keyword)

    scores = [score(result, t) for t in terms]
    # ⚠ 不能用 `> 0` 判命中 —— score() 有一条兜底尾巴（"有作者信息 +2"、
    #   模糊相似度按比例给分），**任何**书对**任何**词都能拿到 2~10 分，
    #   于是 hit 永远非空，"一个词都没中 → 0 分"这条规则形同虚设。
    #   实测后果：搜「余华 活着」时《活着》/未知作者 对"余华"得 2.0 被当作命中，
    #   与正主同样拿满加成，两条打平 110 分 —— 排序失效。
    #   所以必须设阈值：低于 _HIT_MIN 的分数视为「没中」。
    hit = [s for s in scores if s >= _HIT_MIN]
    if not hit:
        return 0.0

    best = max(hit)
    # 命中比例：全中的往上抬，部分中的往下压
    ratio = len(hit) / len(terms)
    if len(hit) == len(terms):
        return best + 8.0 * (len(terms) - 1)      # 全中：加成，稳定排前面
    # 部分命中：按比例打折（中 1/2 → ×0.75；中 1/3 → ×0.67）
    return best * (0.5 + 0.5 * ratio)


def rank(
    results: list[BookResult],
    keyword: str,
    *,
    threshold: float = 28.0,
    keep_min: int = 3,
    limit: int = 60,
) -> list[BookResult]:
    """打分、去噪、去重、排序。

    - 门槛随最高分自适应（见 _adaptive_threshold）
    - 只有「确实没找到像样的结果」时才放宽门槛兜底，
      避免因为阈值过严导致「明明有结果却显示没找到」。
    - 关键词含空格时按多词处理（「余华 活着」，见 score_multi）。
    """
    if not results:
        return []
    multi = len(_split_terms(keyword)) > 1
    for r in results:
        r.score = score_multi(r, keyword) if multi else score(r, keyword)

    ordered = sorted(results, key=lambda r: -r.score)
    cut = _adaptive_threshold(ordered[0].score, threshold)
    kept = [r for r in ordered if r.score >= cut]

    # —— 确切命中优先 ——
    # 只要这批里确实有「像这本书」的，就**不再**把沾边的端上来。
    # 搜《活着》，xbqg5200 会返回「原神：活着」「我怎么还活着」……
    # 它们分数都不低，但都不是用户要的那本；满屏这种比只给一条更像话。
    tight = [r for r in kept if r.tight]
    if tight:
        kept = tight
    else:
        # —— 作者搜索的特殊情况 ——
        # 搜「顾漫」时，她的书书名里**都不含**「顾漫」，于是 tightness 全是 0
        # —— 上面那条「有确切命中就不给沾边的」会把**全部**结果清空，
        # 作者搜索等于白做。所以：一个 tight 都没有、却有作者命中的，
        # 就按作者结果端出去（它们本来就是这批里最相关的）。
        # 反过来说，只要找到了一本确切命名的书，作者匹配的就退居其后 ——
        # 「搜书名」的意图优先于「搜作者」。
        by_author = [r for r in kept if getattr(r, "by_author", False)]
        if by_author:
            kept = by_author
        # 只有「确实没找到像样的结果」时才放宽门槛兜底；
        # 已经找到高分结果时，宁缺毋滥（否则判决书之类的又会从后门溜进来）。
        #
        # 兜底也有底线：最高分连 FALLBACK_FLOOR 都不到，说明这批结果**真的不相关**，
        # 那就老实说没找到 —— 硬凑 3 条「安士全書/文昌帝君陰騭文」给用户看，
        # 比什么都不显示更糟（用户会以为是搜索坏了）。
        #
        # 注：这条兜底与上面「作者命中」不会同时生效 —— 能走到这里说明
        # by_author 为空，而兜底只是拿 ordered[:keep_min] 补足数量，两者不冲突。
        elif (len(kept) < keep_min and ordered[0].score < CONFIDENT
                and ordered[0].score >= FALLBACK_FLOOR):
            kept = ordered[:keep_min]
    return _dedup(kept)[:limit]


def looks_like_book(title: str) -> bool:
    """粗判标题是否像一本书（用于入口处的快速过滤）。"""
    return not NOISE_RE.search(title or "")


# 高于此分说明「基本确定就是这本书」，此时不再用低分结果凑数
CONFIDENT = 60.0

# 最低兜底线：最高分低于它就连兜底都不要了 —— 老实说「没找到」
FALLBACK_FLOOR = 20.0
