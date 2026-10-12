"""端到端冒烟测试：搜索 → 聚合 → 入书架 → 读章节 → 导出。

直接跑引擎（不启服务），避免动到用户已有的后台进程。
"""
import sys, time, json, io
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

from app.engine import Engine
from app.aggregate import group
from app.exporter import export_epub, export_html, export_txt

t0 = time.time()
eng = Engine()

print("=== 0. 来源 ===")
for s in eng.sources:
    print("   ", s.priority, s.name, s.display, "enabled" if s.enabled else "off")

kw = sys.argv[1] if len(sys.argv) > 1 else "微微一笑很倾城"
print(f"\n=== 1. 搜索《{kw}》 ===")
stats = {}
results = eng.search(kw, stats=stats)
print("   stats:", json.dumps(stats, ensure_ascii=False))

print("\n=== 2. 来源级结果（前 8） ===")
for r in results[:8]:
    print(f"   [{r.source_display or r.source:10s}] {r.title[:26]:28s} "
          f"avail={r.available} 章={r.chapter_count} 抽样={r.sample_ok}/{r.sample_chars} "
          f"score={r.score:.0f} {r.note or r.sample_note}")

books = group(results)
print(f"\n=== 3. 聚合后：{len(books)} 本 ===")
for b in books[:6]:
    print(f"   {b['title'][:24]:26s} {b['author'][:8]:10s} 源={b['source_count']} "
          f"可读={b['available_count']} 最多={b['chapter_count']}章")

if not books:
    print("!! 没有结果，跳过后续"); sys.exit(0)

# 挑一个「真能读」的源
target = None
for b in books:
    for s in b["sources"]:
        if s.get("readable"):
            target = s; break
    if target: break
if target is None:
    print("!! 没有可读来源，跳过"); sys.exit(0)

print(f"\n=== 4. 入书架: [{target['source_display']}] {target['title']} ===")
from app.models import BookResult
res = BookResult(title=target["title"], author=target["author"], source=target["source"],
                 url=target["url"], intro=target["intro"])
try:
    meta = eng.shelve(res)
except Exception as e:
    print("   入书架失败:", e); sys.exit(1)
print("   library_id =", meta["id"], "| total =", meta.get("total"), "| status =", meta.get("status"))
toc = eng.library.toc(meta["id"])
print("   目录前 3:", [c["title"] for c in toc[:3]])
print("   目录后 2:", [c["title"] for c in toc[-2:]])

print("\n=== 5. 读第 1 章（联网） ===")
t = time.time()
ch = eng.library_chapter(meta["id"], 1)
print(f"   {ch['index']}. {ch['title']} | {len(ch['content'])} 字 | cached={ch['cached']} "
      f"| {(time.time()-t)*1000:.0f}ms")
print("   正文开头:", ch["content"][:70].replace("\n", " "))

print("\n=== 6. 再读一次（应命中缓存） ===")
t = time.time()
ch2 = eng.library_chapter(meta["id"], 1)
print(f"   cached={ch2['cached']} | {(time.time()-t)*1000:.0f}ms | 一致={ch2['content'] == ch['content']}")

print("\n=== 7. 缓存前 8 章 ===")
t = time.time()
r = eng.cache_book(meta["id"], progress=lambda d, t_, m: None, limit=8)
print(f"   {r} | {(time.time()-t):.1f}s")

print("\n=== 8. 导出 epub / html / txt ===")
from app.models import Book, Chapter
book = Book(title=meta["title"], author=meta["author"], source=meta.get("source_display", ""),
            url=meta.get("url", ""), intro=meta.get("intro", ""))
for e in toc:
    c = eng.library.chapter(meta["id"], e["index"])
    if c and c["content"].strip():
        book.chapters.append(Chapter(index=c["index"], title=c["title"], content=c["content"]))
print("   导出章节数:", len(book.chapters))
for fn in (export_txt, export_epub, export_html):
    p = fn(book)
    print(f"   {p.name}  {p.stat().st_size} bytes")

print("\n=== 9. 清理 ===")
print("   删除书架:", eng.remove_book(meta["id"]))
print(f"\n总耗时 {time.time()-t0:.1f}s")
