"""导出：TXT / EPUB / HTML 阅读版。

只有 TXT 太寒酸了 —— 用户拿到手的是「能看的东西」，不是「一堆字」。

* **TXT**   兼容一切，丢进哪儿都能看（老需求，保留）
* **EPUB**  电子书标准，手机阅读器 / Kindle（转一下）都能导入，
            有目录、有样式、可改字号 —— 真正拿来读的格式
* **HTML**  单文件自包含，双击就是一个小阅读器：左边目录、右边正文、
            可切换主题、上下章。发给别人也不用装任何东西

EPUB 是手写的最小实现（不加依赖）：只用到 zipfile + XML，
比引入 ebooklib 更快也更可控。
"""
from __future__ import annotations

import html as _html
import re
import time
import uuid
import zipfile
from pathlib import Path
from typing import Iterable

from .models import Book, Chapter

DOWNLOAD_DIR = Path(__file__).resolve().parent.parent / "downloads"


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip()
    return name[:80] or "untitled"


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    return path.with_name(f"{path.stem}_{int(time.time())}{path.suffix}")


def _meta_lines(book: Book, valid: list[Chapter]) -> list[str]:
    author = (book.author or "").strip() or "未知作者"
    lines = [f"书名：{book.title}", f"作者：{author}"]
    if book.source:
        lines.append(f"来源：{book.source}")
    if book.url:
        lines.append(f"地址：{book.url}")
    if len(valid) != len(book.chapters):
        lines.append(f"章节：{len(valid)} 章（目录共 {len(book.chapters)} 章，部分未取到正文）")
    else:
        lines.append(f"章节：{len(valid)} 章")
    return lines


# ---------------------------------------------------------------------------
# TXT
# ---------------------------------------------------------------------------
def export_txt(book: Book) -> Path:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    author = (book.author or "").strip() or "未知作者"
    path = _unique(DOWNLOAD_DIR / safe_filename(f"{book.title}_{author}.txt"))

    valid = [ch for ch in book.chapters if ch.content.strip()]
    lines = _meta_lines(book, valid)
    if book.intro:
        lines += ["", "简介：", book.intro.strip()]
    lines += [f"导出时间：{time.strftime('%Y-%m-%d %H:%M:%S')}", "=" * 40, ""]

    for ch in valid:
        lines += [ch.title, "", ch.content.strip(), "", ""]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# EPUB（EPUB 3，最小实现）
# ---------------------------------------------------------------------------
_XHTML = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" \
xml:lang="zh-CN" lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <title>{title}</title>
  <link rel="stylesheet" type="text/css" href="../style.css"/>
</head>
<body>
  <section epub:type="chapter">
    <h1 class="ct">{title}</h1>
{body}
  </section>
</body>
</html>
"""

_EPUB_CSS = """@charset "utf-8";
html, body { margin: 0; padding: 0; }
body { font-family: serif; line-height: 1.8; }
h1.ct { font-size: 1.3em; text-align: center; margin: 1.2em 0 1.6em; font-weight: 600; }
p { margin: 0 0 0.9em; text-indent: 2em; font-size: 1em; }
.cover { text-align: center; margin-top: 25%; }
.cover h1 { font-size: 2em; }
.cover p { text-indent: 0; color: #666; }
.info { margin: 2em 1.5em; font-size: 0.9em; color: #444; }
"""

_CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _xesc(s: str) -> str:
    return _html.escape(s or "", quote=True)


def _paras(text: str) -> str:
    out = []
    for block in re.split(r"\n\s*\n", (text or "").strip()):
        block = block.replace("\n", " ").strip()
        if block:
            out.append(f"    <p>{_xesc(block)}</p>")
    return "\n".join(out)


def export_epub(book: Book) -> Path:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    author = (book.author or "").strip() or "未知作者"
    path = _unique(DOWNLOAD_DIR / safe_filename(f"{book.title}_{author}.epub"))

    valid = [ch for ch in book.chapters if ch.content.strip()]
    if not valid:
        raise RuntimeError("没有正文可导出")

    uid = "urn:uuid:" + str(uuid.uuid4())
    items, spine, nav_li, ncx_nav = [], [], [], []
    for i, ch in enumerate(valid, 1):
        name = f"text/ch{i:04d}.xhtml"
        items.append((f"ch{i}", name))
        spine.append(f"ch{i}")
        nav_li.append(f'      <li><a href="{name}">{_xesc(ch.title)}</a></li>')
        ncx_nav.append(
            f'    <navPoint id="np{i}" playOrder="{i}">\n'
            f'      <navLabel><text>{_xesc(ch.title)}</text></navLabel>\n'
            f'      <content src="{name}"/>\n'
            f'    </navPoint>'
        )

    nav = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" \
xml:lang="zh-CN" lang="zh-CN">
<head><meta charset="utf-8"/><title>目录</title>
<link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>目录</h1>
    <ol>
{chr(10).join(nav_li)}
    </ol>
  </nav>
</body>
</html>
"""

    ncx = f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{uid}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{_xesc(book.title)}</text></docTitle>
  <navMap>
{chr(10).join(ncx_nav)}
  </navMap>
</ncx>
"""

    manifest = "\n".join(
        f'    <item id="{iid}" href="{href}" media-type="application/xhtml+xml"/>'
        for iid, href in items
    )
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" \
xml:lang="zh-CN">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{uid}</dc:identifier>
    <dc:title>{_xesc(book.title)}</dc:title>
    <dc:creator>{_xesc(author)}</dc:creator>
    <dc:language>zh-CN</dc:language>
    <dc:description>{_xesc((book.intro or '')[:900])}</dc:description>
    <dc:source>{_xesc(book.url or '')}</dc:source>
    <meta property="dcterms:modified">{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="css" href="style.css" media-type="text/css"/>
{manifest}
  </manifest>
  <spine toc="ncx">
{chr(10).join(f'    <itemref idref="{i}"/>' for i in spine)}
  </spine>
</package>
"""

    with zipfile.ZipFile(path, "w") as z:
        # mimetype 必须是第一个条目且不压缩，否则有些阅读器不认
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", _CONTAINER, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/nav.xhtml", nav, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/toc.ncx", ncx, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/style.css", _EPUB_CSS, compress_type=zipfile.ZIP_DEFLATED)
        for i, ch in enumerate(valid, 1):
            z.writestr(
                f"OEBPS/text/ch{i:04d}.xhtml",
                _XHTML.format(title=_xesc(ch.title), body=_paras(ch.content)),
                compress_type=zipfile.ZIP_DEFLATED,
            )
    return path


# ---------------------------------------------------------------------------
# HTML 单文件阅读版
# ---------------------------------------------------------------------------
_HTML_TMPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title} · {author}</title>
<style>
:root{{--bg:#f6f4ef;--fg:#26241f;--dim:#8a8579;--line:#e2ddd2;--card:#fff;--accent:#b4552d}}
html[data-theme=night]{{--bg:#16181c;--fg:#c9ccd2;--dim:#7b8189;--line:#262a31;--card:#1d2026;--accent:#c98a63}}
html[data-theme=sepia]{{--bg:#f3e9d6;--fg:#4a3f2d;--dim:#9c8f77;--line:#e2d5bb;--card:#fbf5e9;--accent:#9c6b3a}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.9 -apple-system,"PingFang SC","Microsoft YaHei",serif;transition:background .3s,color .3s}}
#w{{display:flex;min-height:100vh}}
#toc{{width:280px;flex:0 0 280px;border-right:1px solid var(--line);height:100vh;overflow:auto;position:sticky;top:0;background:var(--card);transition:margin .28s}}
#toc.hide{{margin-left:-280px}}
#toc h2{{font-size:14px;color:var(--dim);padding:18px 18px 8px;margin:0;font-weight:600;letter-spacing:.08em}}
#toc a{{display:block;padding:9px 18px;color:var(--fg);text-decoration:none;font-size:14px;border-left:3px solid transparent;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
#toc a:hover{{background:rgba(127,127,127,.08)}}
#toc a.on{{border-left-color:var(--accent);color:var(--accent);background:rgba(127,127,127,.06)}}
#toc input{{margin:12px 18px;width:calc(100% - 36px);padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:transparent;color:var(--fg);outline:none}}
main{{flex:1;min-width:0;padding:0 0 90px}}
#bar{{position:sticky;top:0;backdrop-filter:blur(12px);background:color-mix(in srgb,var(--bg) 82%,transparent);border-bottom:1px solid var(--line);padding:10px 20px;display:flex;align-items:center;gap:12px;z-index:5}}
#bar b{{font-size:15px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
button{{font:inherit;font-size:13px;padding:6px 12px;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;cursor:pointer}}
button:hover{{border-color:var(--accent);color:var(--accent)}}
#prog{{height:3px;background:var(--accent);width:0;transition:width .2s;position:sticky;top:0;z-index:6}}
.art{{max-width:41em;margin:0 auto;padding:40px 24px 80px}}
.art h1{{font-size:1.5em;line-height:1.5;margin:0 0 1.6em;text-align:center}}
.art p{{margin:0 0 1em}}
.foot{{max-width:41em;margin:0 auto;padding:0 24px 60px;display:flex;gap:10px;justify-content:space-between}}
.cover{{max-width:41em;margin:0 auto;padding:14vh 24px}}
.cover h1{{font-size:2.4em;margin:0 0 .3em}}
.cover .a{{color:var(--dim);margin-bottom:2em}}
.cover .i{{line-height:2;font-size:.95em;color:var(--dim)}}
#top{{position:fixed;right:18px;bottom:18px;width:42px;height:42px;border-radius:50%;display:grid;place-items:center;box-shadow:0 6px 20px rgba(0,0,0,.18);opacity:0;pointer-events:none;transition:opacity .2s}}
#top.show{{opacity:1;pointer-events:auto}}
</style>
</head>
<body>
<div id="prog"></div>
<div id="w">
  <nav id="toc">
    <input id="q" placeholder="搜索章节…"/>
    <h2>目录 · {n} 章</h2>
    <div id="toclist">{toc}</div>
  </nav>
  <main>
    <div id="bar">
      <button onclick="document.getElementById('toc').classList.toggle('hide')">☰ 目录</button>
      <b>{title}</b>
      <button id="tb">🌗 主题</button>
    </div>
    <div id="pages">{pages}</div>
  </main>
</div>
<button id="top" onclick="scrollTo({{top:0,behavior:'smooth'}})">↑</button>
<script>
var themes=['day','sepia','night'],ti=0;
document.getElementById('tb').onclick=function(){{ti=(ti+1)%3;document.documentElement.dataset.theme=themes[ti];}};
var secs=[].slice.call(document.querySelectorAll('.ch'));
var links=[].slice.call(document.querySelectorAll('#toclist a'));
function show(i){{secs.forEach(function(s,j){{s.style.display=j===i?'':'none'}});links.forEach(function(a,j){{a.classList.toggle('on',j===i)}});var a=links[i];if(a)a.scrollIntoView({{block:'nearest'}});location.hash='c'+(i+1);scrollTo(0,0);}}
links.forEach(function(a,i){{a.onclick=function(e){{e.preventDefault();show(i);}}}});
document.getElementById('q').oninput=function(){{var v=this.value.trim();links.forEach(function(a,i){{a.style.display=!v||a.textContent.indexOf(v)>=0?'':'none';}});}};
addEventListener('scroll',function(){{var h=document.body.scrollHeight-innerHeight;document.getElementById('prog').style.width=(h>0?Math.min(100,scrollY/h*100):100)+'%';document.getElementById('top').classList.toggle('show',scrollY>600);}});
document.addEventListener('keydown',function(e){{var cur=secs.findIndex(function(s){{return s.style.display!=='none'}});if(cur<0)return;
 if(e.key==='ArrowRight'||e.key==='PageDown'||e.key===' '&&!e.shiftKey){{if(cur<secs.length-1)show(cur+1);}}
 if(e.key==='ArrowLeft'||e.key==='PageUp'){{if(cur>0)show(cur-1);}}}});
var m=location.hash.match(/^#c(\\d+)$/);show(m?Math.min(secs.length-1,parseInt(m[1])-1):0);
</script>
</body>
</html>
"""


def export_html(book: Book) -> Path:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    author = (book.author or "").strip() or "未知作者"
    path = _unique(DOWNLOAD_DIR / safe_filename(f"{book.title}_{author}_阅读版.html"))

    valid = [ch for ch in book.chapters if ch.content.strip()]
    if not valid:
        raise RuntimeError("没有正文可导出")

    toc, pages = [], []
    for i, ch in enumerate(valid):
        toc.append(f'<a href="#c{i+1}" data-i="{i}">{_xesc(ch.title)}</a>')
        pages.append(
            f'<section class="ch" id="c{i+1}" style="display:none">'
            f'<div class="art"><h1>{_xesc(ch.title)}</h1>{_paras(ch.content)}</div>'
            f'<div class="foot">'
            f'<button onclick="show({i-1})"{" disabled" if i == 0 else ""}>← 上一章</button>'
            f'<button onclick="show({i+1})"{" disabled" if i == len(valid) - 1 else ""}>下一章 →</button>'
            f'</div></section>'
        )

    head = (
        f'<div class="art"><div class="cover">'
        f'<h1>{_xesc(book.title)}</h1>'
        f'<div class="a">{_xesc(author)}</div>'
        + (f'<div class="i">{_xesc(book.intro.strip())[:500]}</div>' if book.intro else "")
        + f'<div class="i" style="margin-top:2em">共 {len(valid)} 章 · 来自 {_xesc(book.source or "网络")}</div>'
        f'</div></div>'
    )

    path.write_text(
        _HTML_TMPL.format(
            title=_xesc(book.title), author=_xesc(author), n=len(valid),
            toc="\n".join(toc), pages=head + "\n".join(pages),
        ),
        encoding="utf-8",
    )
    return path


EXPORTERS = {"txt": export_txt, "epub": export_epub, "html": export_html}


def export(book: Book, fmt: str = "txt") -> Path:
    fn = EXPORTERS.get((fmt or "txt").lower(), export_txt)
    return fn(book)
