"""源包。

BUILTIN_SOURCES 汇总所有可用来源，优先级：数字越小越先尝试。

分类：
- 官方 API：wikisource / gutenberg —— 稳定，但只有公版书
- 网文站（写类）：wyshu / kunnu8 / xbqg5200 —— 结构复杂，需要多步解析
- 配置化源（sites.json）：简单站用 JSON 描述，加站不改代码
- 模板源：早期实现，作补充
- 联网发现（web）：本地都搜不到时才出去搜，找到的站自动入库

每个 Source 的契约见 base.py：
    search()       按关键词找候选
    get_chapters() 取目录（探测可用性与下载都依赖它）
    fetch()        抓全书（必须处理 stop 中断）
    fetch_chapter() 抓单章（预览用）
    probe()        可用性探测（默认=试取目录，单页来源需覆写）
"""
from .base import Source  # noqa: F401
from .wikisource import WikisourceSource
from .gutenberg import GutenbergSource
from .wyshu import WyshuSource
from .kunnu8 import Kunnu8Source
from .xbqg5200 import Xbqg5200Source
from .builtin import BiqugeSource, QisuuSource
from .configured import load_configured_sources
from .registry_source import RegistrySource
from .web import DiscoveredSource

# 注意：配置化来源是实例而非类，引擎里已兼容两种形式
BUILTIN_SOURCES = [
    WikisourceSource,       # priority 50 公版书（对网文零覆盖，降权；曾=1，要 184s）
    GutenbergSource,        # priority 5  公版书（官方站）
    WyshuSource,            # priority 8  网文（分类索引 + 拼音兜底，实测可用）
    Kunnu8Source,           # priority 10 网文（WP REST API，实测可用）
    Xbqg5200Source,         # priority 12 网文（含分页，易被限流）
] + load_configured_sources() + [
    BiqugeSource,           # priority 40 域名已失效（enabled=False）
    QisuuSource,            # priority 50 域名已失效（enabled=False）
    RegistrySource,         # priority 60 自有来源（学到的站，拿关键词直接搜）
    DiscoveredSource,       # priority 90 联网发现（lazy，只在本地搜不到时唤起）
]

# 引擎「本地搜不到」时会去找这个来源
DISCOVER_SOURCE = DiscoveredSource.name
