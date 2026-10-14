"""源适配器基类。

每个小说来源实现一个 Source 子类，程序会自动发现并轮询它们。
新增来源只需在 sources/ 目录下加一个文件，无需改动其它代码。
"""
from __future__ import annotations

import re
import time
import threading
import logging
from abc import ABC, abstractmethod
from typing import Callable, Optional

from ..errors import SourceBlocked
from ..models import Book, BookResult, Chapter
from ..webfetch import looks_like_ui_skeleton

logger = logging.getLogger("novel.source")

# 探测回调：probe 完成后的结果
ProbeInfo = dict


class Source(ABC):
    """一个内容来源。

    子类必须实现 search() 和 fetch()。
    fetch() 的 limit 参数用于限制最大章节数（None = 全部），
    stop 参数是一个「该不该停」的回调，返回 True 时应当尽快中断。
    """

    name: str = "unknown"          # 展示用名称
    display: str = "未知来源"       # 中文名
    enabled: bool = True           # 是否启用
    priority: int = 100            # 越小越先尝试
    homepage: str = ""             # 站点首页（用于健康检查）

    # 来源从哪来：builtin（手写适配器）/ adapted（自动推导）/ custom（配置文件）
    # / discovered（联网发现来的）
    # 前端「来源健康检查」用它区分徽章，也用来告诉用户「这条是自己加的」。
    kind: str = "builtin"
    engine: str = ""               # 站点引擎指纹：wordpress / empirecms / generic…
    chapter_paged: bool = False    # 章节是否被拆成多页（多页会走自动拼接）
    has_search: bool = True        # 是否支持站内搜索（不支持只能靠详情页 URL）

    # 「懒惰来源」：不参与每轮搜索的并发扇出，只由引擎在需要时显式调用。
    # 联网发现用它 —— 它一次要跑搜索引擎 + 十几个站点核实，
    # 如果每搜一次都捎上它，所有搜索都会慢一截。
    lazy: bool = False

    # 探测时给这个来源的页数上限（单页来源=1）
    probe_cost: int = 1

    # 连续多少章抓不到正文就判定来源挂了（被限流/封 IP/改版）
    FAIL_FAST: int = 5

    # 单次搜索里，这个来源**最快时**最多被探测几个候选。
    # 同域请求会被限速串行，所以慢站多探一个就多等两秒。
    # 实际配额按实测速度自适应 —— 见 probe_limit()。
    PROBE_BASE: int = 4

    # 实测平均探测耗时（毫秒），EWMA。类属性 0 = 还没测过。
    _probe_ms_avg: float = 0.0

    # 进度回调（线程局部）。引擎在**工作线程里**调 set_log 注入，
    # 来源自己的 search() 里用 self.log(...) 往外推步骤。
    # 用线程局部而不是实例属性：一个来源可能同时被多个搜索用，
    # 共享一个实例属性会让两个搜索的日志串台。
    _tls = threading.local()

    def set_log(self, cb: Optional[Callable[[str, str, bool], None]]) -> None:
        self._tls.log = cb

    @property
    def log(self) -> Optional[Callable[[str, str, bool], None]]:
        return getattr(self._tls, "log", None)

    def note_probe(self, ms: int) -> None:
        """记一次探测耗时，用于自适应配额。"""
        ms = max(0, int(ms or 0))
        cur = getattr(self, "_probe_ms_avg", 0.0)
        self._probe_ms_avg = float(ms) if cur <= 0 else cur * 0.6 + ms * 0.4

    def probe_limit(self) -> int:
        """这次搜索里最多探几个。

        慢站少探、快站多探 —— 否则一个每页 2 秒的站会独吞整轮搜索的预算，
        用户等 30 秒只为了看某一家的目录。
        """
        avg = getattr(self, "_probe_ms_avg", 0.0)
        if avg >= 1800:
            return 1
        if avg >= 900:
            return 2
        if avg >= 400:
            return 3
        return self.PROBE_BASE

    @abstractmethod
    def search(self, keyword: str) -> list[BookResult]:
        """按关键词搜索，返回候选列表。失败时应抛异常或返回空列表。"""
        raise NotImplementedError

    @abstractmethod
    def fetch(
        self,
        result: BookResult,
        progress=None,
        limit: int | None = None,
        stop: Optional[Callable[[], bool]] = None,
    ) -> Book:
        """抓取一本书的完整内容。

        progress: 可选回调 progress(done, total, msg)
        limit:    最多抓取多少章（None = 全部）
        stop:     可选回调，返回 True 表示用户已取消，应尽快中断
        """
        raise NotImplementedError

    # 可选：只获取目录（不抓正文）
    def get_chapters(self, result: BookResult) -> list:
        raise NotImplementedError

    # 可选：抓取单章正文（供预览用）
    def fetch_chapter(self, chapter) -> str:
        """抓取指定章节的正文。返回空串表示该来源不支持单章抓取。"""
        return ""

    # ------------------------------------------------------------------
    # 统一的章节抓取循环：带中断检查 + 连续失败熔断
    # ------------------------------------------------------------------
    def fetch_all(
        self,
        chapters: list[Chapter],
        fetch_one: Callable[[Chapter], str],
        progress=None,
        stop: Optional[Callable[[], bool]] = None,
    ) -> list[Chapter]:
        """按顺序抓章节正文，返回已抓取的章节列表。

        熔断：如果前面若干章**全都**抓不到正文，说明来源已不可用，
        直接抛 SourceBlocked，而不是傻乎乎地跑完全部请求再交出一个空文件。
        """
        total = len(chapters)
        done: list[Chapter] = []
        consec_fail = 0
        for ch in chapters:
            if check_stop(stop):
                break
            try:
                content = fetch_one(ch) or ""
            except Exception as e:  # noqa: BLE001
                logger.debug("章节抓取失败 %s: %s", ch.url, e)
                content = ""
            ch.content = tidy_content(content, ch.title)
            done.append(ch)
            consec_fail = 0 if content.strip() else consec_fail + 1
            if progress:
                progress(ch.index, total, ch.title)
            if consec_fail >= self.FAIL_FAST and not any(c.content.strip() for c in done):
                raise SourceBlocked(
                    f"连续 {consec_fail} 章都没抓到正文，{self.display} 可能已限流或改版"
                )
        return done

    # ------------------------------------------------------------------
    # 可用性探测：搜索之后立刻验证「这个候选到底打不打得开、有没有目录」
    # ------------------------------------------------------------------
    def probe(self, result: BookResult) -> ProbeInfo:
        """快速验证候选是否真的能下载。

        返回::

            {"ok": bool, "chapters": int, "note": str, "ms": int}

        默认实现 = 尝试取目录。单页来源（维基文库/Gutenberg）请覆写。
        """
        t0 = time.time()
        try:
            chapters = self.get_chapters(result)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "chapters": 0,
                    "note": note_for_exception(e), "ms": _ms(t0)}
        ms = _ms(t0)
        if not chapters:
            return {"ok": False, "chapters": 0, "note": "打不开或没有目录", "ms": ms}
        return {"ok": True, "chapters": len(chapters), "note": "", "ms": ms}

    # ------------------------------------------------------------------
    # 深度校验：抽一章正文，确认「真的能读」
    # ------------------------------------------------------------------
    def sample(self, result: BookResult, chapters: list | None = None) -> ProbeInfo:
        """抽一章正文读一下，判断内容是不是真的。

        为什么不能只看目录：很多站的目录页是纯静态的（谁都能打开），
        但正文要点「开始阅读」才给、或者被限流后返回一页广告/验证码。
        只看目录就标「可用」，用户点进去才发现是假的 —— 这就是
        「别显示可以下载最后假的」要解决的事。

        返回::

            {"ok": bool|None, "chars": int, "note": str}
            ok=None 表示「这个来源没法便宜地抽样」，不作判断。

        默认实现只调 fetch_chapter（单章抓取）；拿不到就放弃判断，
        绝不为了抽样去把整本抓一遍。
        """
        if chapters is None:
            try:
                chapters = self.get_chapters(result)
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "chars": 0, "note": note_for_exception(e)}
        if not chapters:
            return {"ok": False, "chars": 0, "note": "没有目录"}

        # 第 1 章经常是「作品相关 / 版权声明」，第 2 章更像正文
        idx = 1 if len(chapters) > 2 else 0

        try:
            text = self.fetch_chapter(chapters[idx]) or ""
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "chars": 0, "note": note_for_exception(e)}

        if not text.strip():
            # 单章接口没实现（单页来源），交给子类覆写，这里不误判
            return {"ok": None, "chars": 0, "note": ""}

        ok, note = check_content_quality(text)
        return {"ok": ok, "chars": len(text.strip()), "note": note}


# 正文开头出现这些，基本可以断定拿到的不是正文
_ERROR_HEAD_RE = re.compile(
    r"^\s*(请?登录|注册|立即登录|无权限|权限不足|404|403|页面不存在|"
    r"章节不存在|本书已下架|该章节不存在|内容已删除|访问受限|安全验证|"
    r"请输入验证码|系统提示|错误提示|抱歉)",
    re.I,
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 章节名混进正文里说明抓错容器了
_JUNK_MIX_RE = re.compile(r"加入书签|投推荐票|手机阅读|本章未完|点击下一页|目录 上一章 下一章")


def check_content_quality(text: str) -> tuple[bool, str]:
    """判断一段正文「像不像真的正文」。"""
    t = (text or "").strip()
    if len(t) < 120:
        return False, f"正文只有 {len(t)} 字"
    # 够长也可能不是正文：正版站的正文页能打开，但正文要登录或 JS 渲染，
    # 抽出来是一屏控件（登录/打赏/投票/字体大小…），平均每行没几个字。
    if looks_like_ui_skeleton(t):
        return False, "拿到的是页面控件，不是正文（多半要登录或 JS 渲染）"
    head = t[:120]
    if _ERROR_HEAD_RE.search(head):
        return False, "拿到的是登录/错误页"
    cjk = len(_CJK_RE.findall(t))
    ratio = cjk / max(len(t), 1)
    if ratio < 0.30:
        return False, "正文疑似乱码或非中文"
    if _JUNK_MIX_RE.search(head):
        return False, "正文里混进了导航文字"
    return True, ""



def _short(e: Exception, n: int = 70) -> str:
    msg = str(e).replace("\n", " ").strip()
    return (msg[:n] + "…") if len(msg) > n else (msg or e.__class__.__name__)


# 探测失败要能区分「真的打不开」和「只是慢/超时」——
# 后者不该让用户以为这本书没了。
_TIMEOUT_RE = re.compile(r"timed?\s*out|timeout|超时|ReadTimeout|ConnectTimeout", re.I)
_STATUS_RE = re.compile(r"HTTP (\d{3})")


def note_for_exception(e: Exception) -> str:
    msg = str(e)
    if _TIMEOUT_RE.search(msg):
        return "响应超时"
    m = _STATUS_RE.search(msg)
    if m:
        code = m.group(1)
        if code == "403":
            return "被拒绝访问 (403)"
        if code == "404":
            return "页面不存在 (404)"
        if code.startswith("5"):
            return f"站点出错 ({code})"
        return f"HTTP {code}"
    if "Connection" in msg or "10054" in msg or "10061" in msg:
        return "连接被拒绝"
    return _short(e)


def _ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)


def check_stop(stop: Optional[Callable[[], bool]]) -> bool:
    """统一的「是否该中断」判断。"""
    return bool(stop and stop())


# 判重时忽略的字符（空白 + 常见标点）
_TITLE_NOISE_RE = re.compile(r"[\s\u3000《》〈〉“”‘’'\"()（）\[\]【】:：;；,，.。!！?？·、\-—_~～|/\\]+")

# 「第(1/3)页」—— 不少笔趣阁系模板把一章拆成几页，
# 每页正文开头带这个标记，链接是 xxx.html / xxx_2.html / xxx_3.html。
# 只抓第一页会让「下载成功」的书**缺 2/3 的内容**，而且完全看不出来。
_PAGE_MARK_RE = re.compile(r"第?\s*[（(]?\s*(\d+)\s*/\s*(\d+)\s*[)）]?\s*页")


def page_mark(text: str) -> Optional[tuple[int, int]]:
    """返回 (当前页, 总页数)，没有分页标记则 None。"""
    m = _PAGE_MARK_RE.search(text or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def strip_page_mark(text: str) -> str:
    """把「第(1/3)页」这种页眉标记从正文里去掉。"""
    if not text:
        return text
    out = []
    for line in text.split("\n"):
        if _PAGE_MARK_RE.fullmatch(line.strip()):
            continue
        out.append(_PAGE_MARK_RE.sub("", line))
    return "\n".join(out).strip("\n")


def page_url(url: str, n: int) -> Optional[str]:
    """按常见模板推出第 n 页的地址：xxx.html / xxx_1.html → xxx_2.html。

    ⚠ 必须把**已有的** `_N` 一起吃掉再叠（2026-10-14 踩到）：旧写法
      `^(.*?)(\\.html?)$` 从续页 `817762_1.html` 出发会生成
      `817762_1_2.html`，而真实续页是 `817762_2.html` —— **永远对不上**。
      更坏的是它不报错：读到的就是"一章只有前一页"的残缺正文。
      这一点和 `webfetch._page_variant` 是同一条纪律（那边有反证钉住）。
      这里**不能**直接调 webfetch 的实现：`base.py` 是被 webfetch 依赖的
      底层，反向依赖会把模块拖成环。

    只处理最普遍的那种；推不出来就返回 None，宁可不拼也不要拼错。
    """
    m = re.match(r"^([\s\S]*?)(?:_(\d+))?(\.[a-z]+)$", url or "", re.I)
    if not m:
        return None
    return f"{m.group(1)}_{n}{m.group(3)}"


def _norm_line(s: str) -> str:
    return _TITLE_NOISE_RE.sub("", s or "").lower()


def strip_leading_title(text: str, title: str) -> str:
    """去掉正文开头重复的章节标题。

    小说站的章节页模板几乎都会把标题渲染两遍：一次在 <h1> 里（阅读器
    已经单独显示了），一次作为正文容器的第一行。照原样读出来就是

        上部 面壁者 第1节 危机纪年第3年，三体舰队距太阳系4.21光年   ← 标题
        危机纪年第3年，三体舰队距太阳系4.21光年                    ← 正文里又来一遍

    判定用「互相包含」而不是「完全相等」：实测有的站正文首行只是标题的
    后半截（标题带了「上部 面壁者 第1节」这类前缀），完全相等匹配不上。
    所以要**循环剥**：有的站一前一后把标题的两种写法都写了一遍。
    """
    if not text or not title:
        return text
    lines = text.split("\n")
    i = 0
    stripped_any = False
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        first = lines[i].strip()
        if len(first) > 60:  # 这么长不可能是标题行，是正文
            break
        a, b = _norm_line(first), _norm_line(title)
        if not a or not b:
            break
        if a == b:
            stripped_any = True
            i += 1
            continue
        # 只判「互相包含」，再加两道闸防误杀：
        #   1) 短行（< 6 字）必须是「无句末标点」的短语，否则可能是正文对话
        #      例：标题「第1章 初入江湖」，正文首行「初入江湖」—— 4 字，要剥
        #          而「你，是本王的。」带句号，是正文，不能剥
        #   2) 长行才允许纯包含判定（老规则）
        if a in b or b in a:
            if len(a) >= 6 or (len(a) >= 3 and not re.search(r"[。！？!?…]", first)):
                stripped_any = True
                i += 1
                continue
        break
    if not stripped_any:
        return text
    rest = "\n".join(lines[i:]).lstrip("\n")
    # 别把整章都删光了（万一某章正文就只有标题一行）
    return rest if rest.strip() else text


# 站方模板行：几乎每章都挂着同一句。它们不是正文，留着会让每一章
# 都从一句广告开始，读者翻页时格外刺眼。
# 实测（xbiquge.info）：『章节错误,点此举报』在**章首**，
# 『加入书签，方便阅读』在**章尾**，两类都要清。
#
# 分两档是踩过坑的：「广告」这种词单看很泛，
# 「他说：这本小说的广告打得真好。」是正文，不是 banner。
# 所以强关键词才允许**行内任意位置**命中，泛词必须**开头 + 够短**。
_BOILER_RE = re.compile(
    r"章节错误|点此举报|加入书签|方便阅读|记住本站|天才一秒|一秒记住|"
    r"手机用户请|手机版阅读|无弹窗|全文免费阅读|求收藏|求推荐|投推荐票|"
    r"加入书架|内容加载失败|本站域名|所有小说|版权归|如有侵权",
    re.I,
)

# 泛词：只有整行基本就是这个 banner 时才算，避免吃掉正文里的同一个词
_BANNER_START_RE = re.compile(
    r"^\W{0,3}(广告|声明|温馨提示|免责|上一章|下一章|返回目录|章节目录|"
    r"阅读模式|最新章节|请记住本站|本站不)",
    re.I,
)

# 「整句式」站点提示 —— 站点把一句完整的话直接插进正文里。
# 实测 zxs8 每章结尾都挂着：
#   请勿开启浏览器阅读模式，否则将导致章节内容缺失及无法阅读下一章。
# 它比上面两类 banner 长得多（30 多字，所以 `_BANNER_START_RE` 的 18 字上限
# 和"必须在行首"两条都挡不住），但特征词唯一，伤不到正文。
# 上限 60 字：正常叙述段落远长于此，而这类提示句在任何站都不会超 60。
_SENTENCE_BANNER_RE = re.compile(
    r"浏览器阅读模式|开启阅读模式|使用阅读模式|"
    r"阅读模式[^，。；]{0,8}(缺失|无法阅读|乱码)",
    re.I,
)

# 纯符号垃圾行：形如 `：。：`、`。。。`。真实段落不会由标点单独构成。
# 保留含 * ※ × 的行 —— 那是作者用的分节符，读者需要它。
_SYMBOL_ONLY_RE = re.compile(
    r"^[\s\u3000:：。，,.、；;！!？?~～\-—_=#·…“”\"'（）()\[\]【】『』「」<>]+$"
)


def _is_boiler(s: str) -> bool:
    if len(s) <= 60 and _SENTENCE_BANNER_RE.search(s):
        return True
    if len(s) <= 32 and _BOILER_RE.search(s):
        return True
    if len(s) <= 18 and _BANNER_START_RE.search(s):
        return True
    if len(s) <= 6 and _SYMBOL_ONLY_RE.match(s) and not re.search(r"[*※×]", s):
        return True
    return False


def strip_boilerplate(text: str) -> str:
    """去掉站方模板行（举报/书签/推荐位）和纯符号垃圾行。

    只删**整行判定命中**的：正文里聊到「广告」两个字不该被吞掉半句话。
    """
    if not text:
        return text
    return "\n".join(
        line for line in text.split("\n")
        if not (line.strip() and _is_boiler(line.strip()))
    )


# ---------------------------------------------------------------------------
# 反爬混淆还原：站方往正文里插『』把词切开
# ---------------------------------------------------------------------------
# 实测（tengc.com，一本联网发现抓到的书）：
#     真实正文「回荡」→ 站点输出「回『荡』」
#     真实正文「杂乱」→ 站点输出「杂『乱』」
#     真实正文「纯白色空间」→ 站点输出「纯白『色』空间」
#
# 这是很常见的一种反爬：把**词里的某个字**用括号包起来，让字符串匹配失效
# （爬虫按「回荡」搜正文就搜不到），但人看着只是多了个括号。
# 用户看到的就是「乱码」—— 截图里那本书整章都是这种东西。
#
# 判据要小心：『』在中文里**本身是合法引号**（书名、强调、外号都用）。
# 一刀切删掉会破坏正常文本。所以只在**明显是「包裹单个字/短词」**时才拆：
#   · 括号内 ≤ 4 个字符（真引号句通常更长，或有标点）
#   · 括号外紧邻的是汉字（`回『荡』` 成立；「他说『好』」也成立，但那种
#     拆开（说好）依然通顺，不伤语义）
#   · 括号内**不含标点/空白**（真引号里经常有逗号句号）
#
# 拆法是**去括号留字**（`回『荡』` → `回荡`），不是删整段 ——
# 删掉就丢字了。
_OBFUSC_RE = re.compile(r"([\u4e00-\u9fff])[『「]([^『』「」\s，。！？；：、,\.!?;:]{1,4})[』」]([\u4e00-\u9fff])?")
# 落单的：`纯白『色』空间` 这种左边已经拆过一次的，再处理一次
_OBFUSC_LOOSE_RE = re.compile(r"[『「]([^『』「」\s，。！？；：、,\.!?;:]{1,3})[』」]")


# ---------------------------------------------------------------------------
# 「生僻字顶替常用字」反爬
# ---------------------------------------------------------------------------
# 实测 `www.zxs8.net`（「17mb / black / bqg」模板家族，大量笔趣阁克隆都在跑）：
# **整本书的正文里，「的」被换成了生僻字「葶」**：
#     真实正文「密闭的肮脏塑料袋」→ 站点输出「密闭葶肮脏塑料袋」
#     真实正文「白猫的根据地」    → 站点输出「白猫葶根据地」
# 和 『』 是同一类反爬（让按词匹配的爬虫失效），但隐蔽得多 ——
# 人读起来只是"个别字怪怪的"，很容易被当成噪声放过。
#
# 映射是**实测**出来的，不是猜的：
#   · 同一章里 `的` = 14 次（全在导航/UI 文字里）、`葶` = 43 次（全在正文里），
#     把 43 处 葶 逐一代入 的，**每一句都通顺**
#   · 四个不同章节（跨全书）用的都是同一个字，说明是**服务端在正文渲染时
#     统一替换**，不是每次请求随机
#   · 最强旁证：同一页的 `<meta description>` 里是**正常的「的」** ——
#     只有书籍正文那条渲染链路被替换过
# 门槛用「本段出现 ≥3 次」：生僻字偶然出现一两次是可能的
# （「葶苈」是药材名，个别书里真会写到），出现几十次就只可能是替换。
_subst_chars = {"葶": "的"}
_subst_min = 3


def fix_subst(text: str) -> str:
    """把「生僻字顶替常用字」还原回来（见上面实测说明）。"""
    s = text or ""
    for bad, good in _subst_chars.items():
        if s.count(bad) >= _subst_min:
            s = s.replace(bad, good)
    return s


def deobfuscate(text: str) -> str:
    """还原站方的反爬混淆。

    两类：
      · **生僻字顶替常用字** —— 实测 `的` → `葶`（见 `fix_subst`）
      · **『』包裹单词** —— `回『荡』` → `回荡`
    只做「去括号留字 / 换回本字」，绝不删字。
    ⚠ 入参是 None / 空串时**原样返回**，不做 `or ""` 归一 ——
      调用方拿它当"没有正文"的哨兵值比较（`is None`），归一成 `""`
      就把哨兵弄丢了。这里踩过一次，别改回去。
    """
    if not text:
        return text
    text = fix_subst(text)
    if "『" not in text and "「" not in text:
        return text

    # 第一遍：汉字 + 『x』 (+汉字) → 直接拼接
    def _join(m: re.Match) -> str:
        return m.group(1) + m.group(2) + (m.group(3) or "")

    prev = None
    cur = text
    # 反复跑到不动（`纯白『色』空间` 需要两轮：先拆右边，再吃左边）
    for _ in range(4):
        prev = cur
        cur = _OBFUSC_RE.sub(_join, cur)
        if cur == prev:
            break

    # 第二遍：还剩落单的短括号（左右都不是汉字，或只有一边是）
    # 只在**非常短**（≤3 字）且不含标点时才拆 —— 这是最保守的口子，
    # 目的是救 `纯白『色』空间` 这种，同时不碰 `他说『我知道了』`。
    cur = _OBFUSC_LOOSE_RE.sub(lambda m: m.group(1), cur)
    return cur


def _trim_blank_edges(text: str) -> str:
    """去掉正文首尾的空行，段间空行保留。

    为什么不用 `text.strip()`：那会把**第一段的缩进**一起吃掉
    （很多站用 `&nbsp;` 排版，首段缩进跟后面几段不一致看着很怪）。
    只按行裁，缩进原样留着。
    """
    lines = text.split("\n")
    i, j = 0, len(lines)
    while i < j and not lines[i].strip():
        i += 1
    while j > i and not lines[j - 1].strip():
        j -= 1
    return "\n".join(lines[i:j])


def tidy_content(text: str, title: str = "") -> str:
    """正文收口：还原反爬混淆 → 清模板行 → 去开头重复的标题 → 裁首尾空行。

    所有落地路径（阅读、缓存、导出）都走这里，避免每个调用点各写一遍、
    漏掉其中一步 —— 之前「首行标题去重」就漏过一处。

    裁首尾空行是因为 `strip_boilerplate` 删掉章首的「章节错误,点此举报」
    之后会**留下一个空行**，阅读器第一屏顶上就顶着一块空白。

    ⚠ `deobfuscate` 必须在最前面做：它还原的是「`回『荡』` → `回荡`」，
    而模板行判定（`_BOILER_RE`）是按文本匹配的 —— 先还原才能让
    「加了混淆的模板行」也被正确识别出来。
    """
    return _trim_blank_edges(
        strip_leading_title(strip_boilerplate(deobfuscate(text or "")), title)
    )
