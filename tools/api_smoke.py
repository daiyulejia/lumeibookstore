"""接口冒烟：用 TestClient 走一遍主要端点（尽量少打网络）。"""
import sys, json
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)

def show(name, r, keep=None):
    ok = r.status_code == 200
    body = r.text
    if keep:
        try:
            d = r.json()
            body = json.dumps({k: d[k] for k in keep if k in d}, ensure_ascii=False)[:200]
        except Exception:
            pass
    print(f"[{'OK ' if ok else 'FAIL'}] {name} {r.status_code} {body[:160]}")

r = c.get("/")
show("GET /", r)
print("     html bytes:", len(r.text), "| 含阅读器:", 'id="reader"' in r.text,
      "| 含书架:", 'id="view-shelf"' in r.text, "| 含设置面板:", 'id="rdSet"' in r.text)

show("GET /api/health", c.get("/api/health"))
show("GET /api/sources", c.get("/api/sources"))
show("GET /api/downloads", c.get("/api/downloads"))

r = c.post("/api/confirm", json={"text": "《微微一笑很倾城》 小说 txt下载"})
show("POST /api/confirm", r, ["keyword", "changed", "suspect", "exact", "index_size"])
print("     候选:", [s["title"] for s in r.json()["suggestions"][:4]])

r = c.post("/api/confirm", json={"text": "斗破苍穷"})
print("     斗破苍穷 ->", r.json()["keyword"], "| 建议:", [(s["title"], s["reason"]) for s in r.json()["suggestions"][:3]])

# 用一个已知的书入书架，测阅读链路（会打一次网络）
r = c.post("/api/shelve", json={
    "title": "微微一笑很倾城", "author": "顾漫", "source": "wyshu",
    "url": "https://www.wyshu.com/ys/weiweiyixiaohenqingcheng/", "intro": ""})
show("POST /api/shelve", r, ["id", "title", "author", "total", "status", "source_display"])
if r.status_code == 200:
    bid = r.json()["id"]
    show("GET /api/library", c.get("/api/library"), ["books"])
    d = c.get(f"/api/library/{bid}").json()
    print(f"     detail: total={d['total']} chapters={len(d['chapters'])} cached={d['cached']} cached_list={d['cached_list'][:5]}")
    ch = c.get(f"/api/library/{bid}/chapter/1").json()
    print(f"     chapter1: {ch['title']} {len(ch['content'])} 字 cached={ch['cached']}")
    p = c.post(f"/api/library/{bid}/position", json={"index": 3, "percent": 0.05, "offset": 0})
    print("     position ->", p.json())
    meta = c.get(f"/api/library/{bid}").json()
    print("     回读 position ->", meta["position"])
    toc = c.get(f"/api/library/{bid}/toc").json()
    print("     toc ->", toc["total"], "章, 第一条:", toc["chapters"][0])
    show("DELETE /api/library/{bid}", c.delete(f"/api/library/{bid}"))

show("GET /api/library/badid!!!", c.get("/api/library/badid!!!"))
show("GET /api/library/deadbeefdeadbeef", c.get("/api/library/deadbeefdeadbeef"))
show("POST /api/cancel/nope", c.post("/api/cancel/nope"))
print("\n全部走通")
