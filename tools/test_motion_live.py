#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
动效层 · 真浏览器验证
============================================================================
静态检查（tools/test_motion.py）只能保证"文件被引用了"，
保证不了"浏览器真的应用了"。这个脚本补上后半段。

为什么值得单独写：动效的失败方式是**静默**的 ——
motion.css 404 了、变量没解析、.mo-theming 忘了摘，
这些都不会让任何功能坏掉，只是"变朴素了"，很容易一路带到线上没人发现。

六项检查：
  1. motion.css 真的被解析（--mo-standard 在 computed style 里取得到）
  2. list 项上真的有 --mo-i（stagger 生效）
  3. 按下按钮真的出现 .mo-rip（涟漪生效）
  4. 主题切换真的带过渡（.mo-theming 出现，且**会消失**）
  5. 章末装饰的伪元素真的加载了 read_pair
  6. prefers-reduced-motion 模拟成 reduce 后，装饰真的停

用法：
    .venv\\Scripts\\python tools/test_motion_live.py
    .venv\\Scripts\\python tools/test_motion_live.py --base http://127.0.0.1:8011
============================================================================
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from shot import find_chrome, free_port, wait_devtools, Tab   # noqa: E402

ok_n = 0
bad_n = 0


def ok(m):
    global ok_n; ok_n += 1; print(f"  ✓ {m}")


def bad(m):
    global bad_n; bad_n += 1; print(f"  ✗ {m}")


def info(m):
    print(f"     {m}")


def section(t):
    print(f"\n── {t} " + "─" * max(0, 56 - len(t)))


class Browser:
    """一个临时的 headless Chrome，跑完就关。"""

    def __init__(self, w=1280, h=900, pre_js=""):
        self.port = free_port()
        self.profile = tempfile.mkdtemp(prefix="motionprof-")
        self.proc = subprocess.Popen(
            [
                find_chrome(),
                "--headless=new", "--disable-gpu", "--hide-scrollbars",
                "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                f"--remote-debugging-port={self.port}",
                "--remote-allow-origins=*",
                f"--user-data-dir={self.profile}",
                f"--window-size={w},{h}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        wait_devtools(self.port)

        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/json/new?about:blank", method="PUT")
        with urllib.request.urlopen(req, timeout=5) as r:
            tab_ws = json.load(r)["webSocketDebuggerUrl"]

        self.t = Tab(tab_ws)
        self.t.call("Page.enable")
        self.t.call("Runtime.enable")
        self.t.call("Emulation.setDeviceMetricsOverride",
                    width=w, height=h, deviceScaleFactor=1, mobile=False)
        if pre_js:
            self.t.call("Page.addScriptToEvaluateOnNewDocument", source=pre_js)

    def goto(self, url, settle=3.0):
        self.t.call("Page.navigate", url=url)
        time.sleep(settle)

    def js(self, expr, await_promise=False):
        """跑一段 JS 并取回值。表达式里可以直接 return（包成 IIFE）。"""
        src = expr
        if not expr.strip().startswith("(") and not expr.strip().startswith("new "):
            src = f"(() => {{ {expr} }})()"
        r = self.t.call("Runtime.evaluate", expression=src, returnByValue=True,
                        awaitPromise=await_promise, userGesture=True)
        if "exceptionDetails" in r:
            raise RuntimeError(str(r["exceptionDetails"])[:300])
        return r.get("result", {}).get("value")

    def emulate_reduced(self, on=True):
        self.t.call("Emulation.setEmulatedMedia", features=[
            {"name": "prefers-reduced-motion", "value": "reduce" if on else "no-preference"},
        ])

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=8)
        except Exception:
            try: self.proc.kill()
            except Exception: pass


# ===========================================================================
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8011")
    a = ap.parse_args()
    base = a.base.rstrip("/")

    print("=" * 62)
    print("动效层 · 真浏览器验证")
    print("=" * 62)

    # 先确认服务活着，否则后面全是误导性的失败
    try:
        urllib.request.urlopen(base + "/api/health", timeout=5).read()
    except Exception as e:
        print(f"\n连不上 {base}：{e}")
        print("先启动服务再跑这个脚本。")
        return 2

    try:
        b = Browser()
    except Exception as e:
        print(f"起不了浏览器：{e}")
        return 2

    try:
        b.goto(base + "/")
        # ⚠ 等首屏数据 —— 但要等**真的挂载完**，不能只 sleep 一个固定秒数。
        #   踩过的坑：ship 会在跑完静态自检后立刻起真机测试，机器正忙，
        #   1.5s 里 main.js 的 `mountDiscover()` 可能还没跑到 `wireEvents()`
        #   —— `#btnSearch` 这个**静态标签**早就被解析进 DOM 了（元素在），
        #   可它的 `pointerdown` 涟漪监听还没绑上（见 main.js 里的
        #   `document.documentElement.dataset.mounted = "1"` 标记）。
        #   于是第 3 节「按下后按钮带上 .mo-rip」偶发假红，看着像涟漪坏了。
        #   等 `mounted` 标记出现再往下走，就与"机器忙不忙"解耦了。
        deadline = time.time() + 25
        while time.time() < deadline:
            if b.js("return !!(document.documentElement.dataset.mounted"
                    " && document.querySelector('#btnSearch'))"):
                break
            time.sleep(0.25)
        time.sleep(0.6)   # 再留一点给榜单/动效的首次渲染

        raw = b.js("""
          const cs = getComputedStyle(document.documentElement);
          return JSON.stringify({
            mo:  cs.getPropertyValue('--mo-standard').trim(),
            dur: cs.getPropertyValue('--mo-flow').trim(),
            scene: cs.getPropertyValue('--mo-scene').trim(),
            cssLoaded: [...document.styleSheets].some(s => (s.href||'').includes('motion.css')),
            artLoaded: [...document.styleSheets].some(s => (s.href||'').includes('lumei.css')),
            htmlCls: document.documentElement.className,
          });
        """)
        d = json.loads(raw)

        # ---------------------------------------------------------------
        section("1. 样式真的被解析")
        if d["cssLoaded"]:
            ok("motion.css 进了 document.styleSheets")
        else:
            bad("motion.css 没进 styleSheets —— 链接 404 了？")

        if d["mo"].startswith("cubic-bezier"):
            ok(f"--mo-standard 解析成功：{d['mo']}")
        else:
            bad(f"--mo-standard 取不到（得到 {d['mo']!r}）")

        if d["dur"].endswith(("ms", "s")):
            ok(f"--mo-flow 解析成功：{d['dur']}")
        else:
            bad(f"--mo-flow 取不到（得到 {d['dur']!r}）")

        if not d["htmlCls"]:
            ok("初始时 <html> 上没有残留状态类（干净）")
        else:
            info(f"初始 class={d['htmlCls']!r}")

        # ---------------------------------------------------------------
        section("2. 错峰变量真的写进去了")
        n_i = b.js("""
          const els = document.querySelectorAll('#results .book, #ranksList .rk-item, #shelfList .shelf');
          let withVar = 0, tot = els.length;
          els.forEach(e => { if (getComputedStyle(e).getPropertyValue('--mo-i').trim() !== '') withVar++; });
          return JSON.stringify({tot, withVar});
        """)
        ni = json.loads(n_i)
        if ni["tot"] == 0:
            info("当前页面没有列表项 —— 跳过（不算失败）")
        elif ni["withVar"] == ni["tot"]:
            ok(f"{ni['tot']} 个列表项全部带 --mo-i")
        else:
            bad(f"只有 {ni['withVar']}/{ni['tot']} 个列表项带 --mo-i —— stagger 没覆盖全")

        # ---------------------------------------------------------------
        section("3. 涟漪：pointerdown 后有 .mo-rip")
        rip = b.js("""
          const btn = document.querySelector('#btnSearch');
          if (!btn) return 'nobtn';
          const r = btn.getBoundingClientRect();
          btn.dispatchEvent(new PointerEvent('pointerdown', {
            bubbles: true, cancelable: true, button: 0,
            clientX: r.left + r.width / 2, clientY: r.top + r.height / 2,
          }));
          return btn.classList.contains('mo-rip') ? 'yes' : 'no';
        """)
        if rip == "yes":
            ok("按下后按钮带上 .mo-rip（涟漪生效）")
        elif rip == "nobtn":
            bad("找不到 #btnSearch —— 页面结构变了？")
        else:
            bad("按下后没有 .mo-rip —— 涟漪没生效")

        # 涟漪是"一次性"的，动画结束必须摘掉，否则第二次按下不重放
        gone = b.js("new Promise(r => setTimeout(() => r("
                    "document.querySelector('#btnSearch').classList.contains('mo-rip')"
                    " ? 'still' : 'cleared'), 900))", await_promise=True)
        if gone == "cleared":
            ok("动画结束后 .mo-rip 被摘掉（第二次按下还能重放）")
        else:
            bad(".mo-rip 没被摘掉 —— 涟漪只会在第一次出现")

        # ---------------------------------------------------------------
        section("4. 主题切换带过渡")
        t = json.loads(b.js("""
          document.querySelector('#btnTheme')?.click();
          const drawer = !!document.querySelector('#themeDrawer');
          const card = document.querySelector('#themeDrawer [data-th="midnight"]');
          if (card) card.click();
          return JSON.stringify({
            drawer,
            during: document.documentElement.classList.contains('mo-theming'),
            applied: document.documentElement.dataset.theme,
          });
        """))
        if t["drawer"]:
            ok("外观面板能打开")
        else:
            bad("外观面板没打开 —— 检查 #btnTheme 的绑定")
        if t["during"]:
            ok("切换时 .mo-theming 挂在 <html> 上（色值在插值）")
        else:
            bad("切换时没有 .mo-theming —— 主题还是硬切")
        if t["applied"] == "midnight":
            ok("主题真的切过去了（data-theme=midnight）")
        else:
            bad(f"主题没切过去（data-theme={t['applied']!r}）")

        end = b.js("new Promise(r => setTimeout(() => r("
                   "document.documentElement.classList.contains('mo-theming')"
                   " ? 'still' : 'cleared'), 800))", await_promise=True)
        if end == "cleared":
            ok("过渡结束后 .mo-theming 被摘掉（不会一直走插值拖慢滚动）")
        else:
            bad(".mo-theming 没被摘掉 —— 全站会一直插值，滚动掉帧")

        # ---------------------------------------------------------------
        section("5. 章末装饰的伪元素真的加载了素材")
        # 先把主题切回噜妹（上一步切到 midnight 了），装饰只在噜妹配色下出现
        b.js("document.querySelector('#themeDrawer [data-th=\"lumei\"]')?.click();")
        time.sleep(0.4)

        deco = json.loads(b.js("""
          new Promise(r => {
            location.hash = '#read=0e808fead79e79';
            setTimeout(() => {
              const rd = document.querySelector('#reader');
              const a  = document.querySelector('#rdScrollBody');
              if (!a || !rd) return r(JSON.stringify({err: 'no-reader'}));
              const cs = getComputedStyle(a, '::after');
              r(JSON.stringify({
                theme: rd.dataset.rdTheme,
                bg: (cs.backgroundImage || ''),
                w: cs.width, h: cs.height, op: cs.opacity,
              }));
            }, 3000);
          })
        """, await_promise=True))
        if deco.get("err"):
            bad(f"阅读器没打开（{deco['err']}）—— 书架里那本书还在吗")
        elif "read_pair" in deco.get("bg", ""):
            ok(f"章末伪元素加载了 read_pair（{deco['w']} × {deco['h']}, opacity={deco['op']}）")
        else:
            bad(f"章末没有 read_pair 背景（theme={deco.get('theme')}, bg={deco.get('bg','')[:60]}）")
            info("装饰只在 #reader[data-rd-theme=\"lumei\"] 下出现，确认阅读配色是噜妹")

        # ---------------------------------------------------------------
        section("6. 素材真的能解码（不是 404 的连接点）")
        img_ok = b.js("""
          new Promise(r => {
            const u = '/static/img/lumei/loading_read@480.webp';
            const im = new Image();
            im.onload  = () => r(JSON.stringify({ok: true, w: im.naturalWidth, h: im.naturalHeight}));
            im.onerror = () => r(JSON.stringify({ok: false}));
            im.src = u;
            setTimeout(() => r(JSON.stringify({ok: false, timeout: true})), 5000);
          })
        """, await_promise=True)
        di = json.loads(img_ok)
        if di.get("ok"):
            ok(f"loading_read@480.webp 解码成功（{di['w']}×{di['h']}）")
            if di["w"] == 480:
                ok("实际宽度 480，与 art.js 声明一致")
            else:
                bad(f"实际宽度 {di['w']}，art.js 里声明的是 480")
        else:
            bad("loading_read@480.webp 加载失败")

        # ---------------------------------------------------------------
        section("7. prefers-reduced-motion 模拟成 reduce 后装饰应停")
        b.emulate_reduced(True)
        time.sleep(0.5)
        rm = json.loads(b.js("""
          return JSON.stringify({
            matches: window.matchMedia('(prefers-reduced-motion: reduce)').matches
          });
        """))
        if rm["matches"]:
            ok("媒体查询已模拟为 reduce（页面能读到这个偏好）")
        else:
            info("模拟没生效 —— 浏览器版本可能不支持 setEmulatedMedia features")

        # 在 reduce 下重新加载，涟漪应该被跳过
        b.t.call("Page.reload")
        time.sleep(3.0)
        rip2 = b.js("""
          const btn = document.querySelector('#btnSearch');
          if (!btn) return 'nobtn';
          const r = btn.getBoundingClientRect();
          btn.dispatchEvent(new PointerEvent('pointerdown', {
            bubbles: true, cancelable: true, button: 0,
            clientX: r.left + r.width/2, clientY: r.top + r.height/2,
          }));
          return btn.classList.contains('mo-rip') ? 'yes' : 'no';
        """)
        if rip2 == "no":
            ok("reduce 下涟漪被跳过（尊重系统偏好）")
        elif rip2 == "nobtn":
            info("reduce 下找不到按钮 —— 跳过")
        else:
            bad("reduce 下涟漪仍然出现 —— reduceMotion() 判定没起作用")

        # ---------------------------------------------------------------
        # 8. 主题痕迹真的落到计算样式上（不只看 CSS 文件里有没有那段选择器）
        #
        # 为什么必须真机验：静态检查只能证明"lumei.css 里写了这条规则"，
        # 证明不了"它赢了层叠、真的作用到了元素上" ——
        # 被行内 style / 更高优先级选择器盖掉是这类 CSS 最常见的失效方式。
        section("8. 主题痕迹的计算样式（真机）")

        # ⚠ 第 7 节把媒体查询模拟成了 prefers-reduced-motion:reduce —— 而
        #   reduce 下我们的规则是 `animation:none!important`（正确行为！）。
        #   不关掉这个模拟，下面所有"应该有动效"的断言都会假红。
        #   （第一次跑就是这么翻车的：任务卡报"没有呼吸"，其实是被 reduce 正确地关掉了。）
        b.emulate_reduced(False)
        time.sleep(0.3)

        # ⚠ 第 4 节把主题切成了 midnight —— 也要切回来，
        #   否则量出来的全是别的主题的值。
        b.js("""
          document.documentElement.dataset.theme = 'lumei';
          return 'ok';
        """)
        time.sleep(0.4)
        cur = b.js("return document.documentElement.dataset.theme")
        if cur == "lumei":
            ok("已切回噜妹主题 + 关掉 reduce 模拟，后续量的是正确环境下的值")
        else:
            bad(f"切不回噜妹主题（当前 {cur!r}）—— 下面的结果不可信")

        # 8a. 确认框：真实走一遍 confirmBox
        cfm = json.loads(b.js("""
          return new Promise(async r => {
            const { confirmBox } = await import('/static/js/util.js');
            confirmBox({ title: '删除文件', message: '删掉它？', okText: '删除', danger: true });
            await new Promise(s => setTimeout(s, 500));
            const el = document.querySelector('.cfm');
            if (!el) { r(JSON.stringify({ found: false })); return; }
            const cs = getComputedStyle(el);
            r(JSON.stringify({
              found: true,
              topW: cs.borderTopWidth,
              topC: cs.borderTopColor,
              radius: cs.borderRadius,
              mask: !!document.querySelector('.cfm-mask'),
            }));
            document.querySelector('.cfm [data-no]')?.click();
          });
        """, await_promise=True))
        if not cfm.get("found"):
            bad("confirmBox 没有渲染出 .cfm —— 组件类没生效")
        else:
            if cfm["topW"] == "2px":
                ok(f"确认框顶部 2px 暖线生效（{cfm['topC']}）")
            else:
                bad(f"确认框顶部线宽是 {cfm['topW']}，期望 2px —— 主题规则没生效")
            if cfm["radius"] and cfm["radius"] != "0px":
                ok(f"确认框圆角走令牌：{cfm['radius']}")
            else:
                bad("确认框没有圆角 —— 类样式没加载")
            if cfm["mask"]:
                ok("确认框用了 .cfm-mask 遮罩")
            else:
                bad("确认框没有 .cfm-mask")

        # 8b. 任务卡：只有运行中才呼吸（这是最容易被写错的一条）
        taskanim = json.loads(b.js("""
          const mk = (cls) => {
            const d = document.createElement('div');
            d.className = 'task ' + cls;
            d.innerHTML = '<div class="tl"><b>t</b></div>';
            document.body.appendChild(d);
            return getComputedStyle(d).animationName;
          };
          const run = mk('is-running');
          const done = mk('is-done');
          document.querySelectorAll('.task').forEach(e => e.remove());
          return JSON.stringify({ run, done });
        """))
        if "lu-task-hum" in (taskanim.get("run") or ""):
            ok("任务卡运行中会呼吸（lu-task-hum）")
        else:
            bad(f"运行中的任务卡没有呼吸动效：{taskanim.get('run')}")
        if "lu-task-hum" in (taskanim.get("done") or ""):
            bad("已完成的任务卡也在呼吸 —— 会让人以为还在跑")
        else:
            ok("已完成的任务卡不呼吸（正确）")

        # 8c. 文件格式图标：SVG 吃 currentColor，格式不同色不同
        #
        # ⚠ 必须把 .ic 放进一个 .file 里 —— 主题选择器是 `.file .ic[data-ext=…]`。
        #   上一版直接挂在 body 下，选择器当然不匹配（那不是代码错，是测试造错了 DOM）。
        ficon = json.loads(b.js("""
          const host = document.createElement('div');
          host.className = 'file';
          document.body.appendChild(host);
          const mk = (ext) => {
            const d = document.createElement('div');
            d.className = 'ic'; d.dataset.ext = ext;
            d.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22"></svg>';
            host.appendChild(d);
            return getComputedStyle(d).color;
          };
          const epub = mk('epub'), html = mk('html'), txt = mk('txt');
          host.remove();
          return JSON.stringify({ epub, html, txt });
        """))
        if ficon.get("epub") and ficon.get("html") and ficon["epub"] != ficon["html"]:
            ok(f"文件图标按格式着色（txt={ficon['txt']} epub={ficon['epub']} html={ficon['html']}）")
        else:
            bad(f"文件图标没有按格式区分颜色：epub={ficon.get('epub')} html={ficon.get('html')}")

        # 8d. 品牌规则确实只在 lumei.css（真机上验一遍变量存在）
        tokens = json.loads(b.js("""
          const cs = getComputedStyle(document.documentElement);
          return JSON.stringify({
            a1: cs.getPropertyValue('--a-1').trim(),
            a2: cs.getPropertyValue('--a-2').trim(),
          });
        """))
        if tokens.get("a1") and tokens.get("a2"):
            ok(f"主题令牌在位：--a-1={tokens['a1']} --a-2={tokens['a2']}")
        else:
            bad("拿不到 --a-1/--a-2 —— 主题可能没挂上")

    finally:
        b.close()

    print("\n" + "=" * 62)
    print(f"通过 {ok_n} · 失败 {bad_n}")
    if bad_n:
        print("✗ 有问题，见上面 ✗ 行")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
