"""内置站点实例（模板配置）。

说明：
- 这里的站点都是长期存在、结构相对稳定的公开站点。
- 抓取仅用于个人学习/研究，请遵守目标站点的 robots 与版权规定。
- 站点改版时，只需调整这里对应的正则即可，无需改其它代码。
"""
from __future__ import annotations

from .template_source import TemplateSource


class BiqugeSource(TemplateSource):
    """通用笔趣阁系模板。

    国内存在大量结构几乎一致的笔趣阁镜像站，模板如下。
    若某个域名失效，改 base_url / search_url 即可，或复制本类新增一个镜像。

    ⚠️ 默认 disabled：b520.cc 实测已返回 404（域名已失效）。
    想启用的话把 enabled 改回 True，并把 base_url 换成当前能打开的镜像。
    """

    name = "biquge"
    display = "笔趣阁"
    priority = 40
    enabled = False

    base_url = "https://www.b520.cc"
    search_url = "https://www.b520.cc/modules/article/search.php?searchkey={kw}"

    # 搜索结果：<tr> 内含 <a href="/1_1244/">书名</a> 与作者
    search_item_re = (
        r'<tr>.*?<td class="odd">.*?<a href="(?P<url>[^"]+)"[^>]*>(?P<title>[^<]+)</a>.*?'
        r'<td class="odd">(?P<author>[^<]*)</td>'
    )

    # 目录页：<dd><a href="xxx.html">章节名</a></dd>
    chapter_re = r'<dd>\s*<a[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>[^<]+)</a>'

    book_title_re = r'<meta property="og:novel:book_name" content="([^"]+)"'
    book_author_re = r'<meta property="og:novel:author" content="([^"]+)"'

    # 正文：<div id="content">...</div>
    content_re = r'<div[^>]+id="content"[^>]*>(?P<c>[\s\S]*?)</div>'


class QisuuSource(TemplateSource):
    """奇书网系模板（下载页结构，适合直接抓 txt 链接的场景）。

    ⚠️ 默认 disabled：qisuu.la 实测已失效。启用前请先换成能打开的域名。
    """

    name = "qisuu"
    display = "奇书网"
    priority = 50
    enabled = False

    base_url = "https://www.qisuu.la"
    search_url = "https://www.qisuu.la/modules/article/search.php?searchkey={kw}"

    search_item_re = (
        r'<a href="(?P<url>[^"]+\.html)"[^>]*>(?P<title>[^<]{2,40})</a>'
    )
    chapter_re = r'<a[^>]+href="(?P<url>[^"]+\.html)"[^>]*>(?P<title>[^<]{1,40})</a>'
    book_title_re = r"<title>([^<_-]+)"
    content_re = r'<div[^>]+id="content"[^>]*>(?P<c>[\s\S]*?)</div>'


# 注册表：新增来源在此追加
BUILTIN_SOURCES = [
    BiqugeSource,
    QisuuSource,
]
