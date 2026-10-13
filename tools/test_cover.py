"""封面抽取（webfetch.extract_cover）的回归测试。

为什么要测这一块
----------------
封面本身是"锦上添花"的功能，但**取错封面比没有封面更糟**：
  · 站点没封面时会放一张 `nocover.jpg` 占位图。如果把它当封面缓存在本地，
    那本书就**永远**显示那张灰图 —— 而正确行为是回退到前端画的渐变封面。
  · 很多站的封面是**懒加载**的：`src` 写占位图、真地址在 `data-src`。
    只读 `src` 会 100% 拿到占位图。
上面两种都是从真实站点（xbqg5200 等）抓到的实际写法，不是假想。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from app.webfetch import extract_cover

    fails: list[str] = []

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}：期望 {want!r}，实际 {got!r}")
            print(f"  ✗ {label}")
        else:
            print(f"  ✓ {label}")

    B = "https://a.com/book/1045/"

    print("[1] og:image 优先")
    check("绝对地址直接可用",
          extract_cover('<meta property="og:image" content="https://cdn.a.com/c.jpg">', B),
          "https://cdn.a.com/c.jpg")
    check("相对地址按 base 补全",
          extract_cover('<meta property="og:image" content="/img/c.png">', B),
          "https://a.com/img/c.png")
    check("协议相对 //host 补 https",
          extract_cover('<meta property="og:image" content="//cdn.a.com/x.jpg">', B),
          "https://cdn.a.com/x.jpg")
    check("twitter:image 兜底",
          extract_cover('<meta name="twitter:image" content="https://a.com/t.jpg">', B),
          "https://a.com/t.jpg")
    check("og:image 是占位图 → 丢掉并继续找别的",
          extract_cover(
              '<meta property="og:image" content="https://a.com/nocover.jpg">'
              '<img class="cover" src="/real.jpg">', B),
          "https://a.com/real.jpg")
    check("og:image 与 img 都在 → og:image 赢",
          extract_cover('<meta property="og:image" content="https://a.com/x.jpg">'
                        '<img class="cover" src="/y.jpg">', B),
          "https://a.com/x.jpg")

    print("[2] 懒加载（真实站点写法）")
    # 原样复制自 https://www.xbqg5200.com/book/1045/ 的真实标签
    check("src 是占位图、data-src 才是真封面 → 取 data-src",
          extract_cover(
              '<img class="thumbnail" src="http://www.xbqg5200.com/static/wucuo/nocover.jpg"'
              ' data-src="http://img.xbqg5200.com/files/article/image/23/23067/23067s.jpg"'
              ' width="120px" height="160px" alt="林楚徐露">', B),
          "http://img.xbqg5200.com/files/article/image/23/23067/23067s.jpg")
    check("data-src 在 src 之前也能取到",
          extract_cover('<img data-src="/real.jpg" class="cover" src="/ph.gif">', B),
          "https://a.com/real.jpg")
    check("data-original 同样认",
          extract_cover('<img class="cover" data-original="/o.jpg" src="/ph.gif">', B),
          "https://a.com/o.jpg")

    print("[3] 占位图 / 无效地址必须丢弃")
    check("nocover.jpg 直接丢",
          extract_cover('<img src="http://a.com/static/nocover.jpg" class="cover">', B),
          "")
    check("default-cover 丢",
          extract_cover('<img class="cover" src="/img/default-cover.png">', B),
          "")
    check("placeholder 丢",
          extract_cover('<meta property="og:image" content="https://a.com/placeholder.png">', B),
          "")
    check("data: 内联图丢",
          extract_cover('<meta property="og:image" content="data:image/gif;base64,AAAA">', B),
          "")
    check("页面没有图 → 空串（前端画渐变封面）",
          extract_cover('<html><body>没有任何图片</body></html>', B),
          "")
    check("img 没有 src/data-src → 空串",
          extract_cover('<img class="cover">', B),
          "")

    print("[4] 不该误伤的写法")
    check("普通文章配图（class 不含 cover）不认",
          extract_cover('<img src="/photo.jpg">', B),
          "")
    check("class 含 cover 的子串（coverflow）也算命中",
          extract_cover('<img class="coverflow" src="/c.jpg">', B),
          "https://a.com/c.jpg")
    check("封面地址超长要截断到 500",
          len(extract_cover('<meta property="og:image" content="https://a.com/'
                            + "x" * 900 + '.jpg">', B)) <= 500,
          True)

    print()
    if fails:
        print(f"✗ {len(fails)} 项失败：")
        for f in fails:
            print(f"    {f}")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
