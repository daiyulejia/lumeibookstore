/* ==========================================================================
   阅读器
   --------------------------------------------------------------------------
   三种翻页模式：
     scroll  上下滚动
     slide   左右平移（自己实现，跟手拖拽）
     flip    仿真翻页（交给 StPageFlip 做纸张卷曲）

   分页算法（paginate）说人话：
     把整章文字塞进一个"和真实页面一样宽、但高度不限"的量尺里，
     浏览器排一次版，然后读每个段落的 offsetTop / offsetHeight ——
     这时**一次布局**就拿到了全部段落的位置，纯算术就能切页。

     为什么不逐段试排：那样每加一段都要读一次 scrollHeight，
     等于每段强制一次重排（forced reflow）。一章 150 段就是 150 次，
     手机上要几百毫秒。而这个办法只要 1 次。

     规则：**段落不拆**。放不下就整段挪到下一页。
     段末留几行空白比"一句话劈两半"读起来舒服得多。
     只有当一个段落本身比整页还高（罕见，比如整章没有换行）才拆。
   ========================================================================== */

import { $, $$, esc, api, toast, PRE, bus, clamp, debounce } from "./util.js";
import { busyHTML, failHTML } from "./art.js";

const RD = {
  bid: "", title: "", author: "", total: 0, index: 1,
  chapters: [], cached: new Set(), meta: null,

  mode:  PRE.get("rd_mode", "slide"),
  // 默认用「噜妹」而不是「日间」：
  //   RD_THEMES 里 lumei 是第一个（= 设计上认定的主场配色），
  //   但默认值曾经是 day —— 于是「第一个色卡」和「实际默认」对不上，
  //   用户从没主动选过配色，就永远看不到本站自己的阅读配色。
  //   这是一个纯默认值错误，不影响功能，只影响"有没有主题"。
  theme: PRE.get("rd_theme", "lumei"),
  fs:    PRE.get("rd_fs", 19),
  lh:    PRE.get("rd_lh", 1.85),
  ff:    PRE.get("rd_ff", "serif"),
  w:     PRE.get("rd_w", 40),

  pages: [],      // 当前章的每一页的 HTML
  page: 0,        // 当前页（0 基）
  pf: null,       // StPageFlip 实例
  loading: false,
  open: false,
  scrollFrac: 0,
  _pre: null,     // 预取好的下一章缓存 {index, data}
  _drag: null,
};

/** 当前章的原始正文 HTML（含 <h2>）。
 *  改字号/行距/切翻页模式时用它重排，不必重新请求网络。 */
let lastChapterHTML = "";

const LS_MODE_KEY = "rd_mode";
export const isReaderOpen = () => RD.open;

/* ==========================================================================
   打开 / 关闭
   ========================================================================== */
export async function openReader(meta) {
  RD.bid = meta.id;
  RD.title = meta.title || "—";
  RD.author = meta.author || "";
  RD.meta = meta;
  RD.total = meta.total || 0;
  RD.pages = []; RD.page = 0; RD._pre = null;

  const el = $("#reader");
  el.classList.add("on");
  RD.open = true;
  lockScroll(true);
  applyPrefs();

  try { history.replaceState(null, "", "#read=" + RD.bid); } catch {}

  $("#rdTitle").textContent = RD.title;
  renderSub();

  // 首屏加载：不用骨架屏（阅读页没有"结构"可占位），
  // 用「噜噜在翻书」—— 用户等的是一件具体的事，图比灰块更像"正在为你做"。
  setStageBusy(true);
  try {
    const d = await api.get(`/api/library/${RD.bid}`);
    RD.chapters = d.chapters || [];
    RD.total = RD.chapters.length || RD.total;
    RD.cached = new Set(d.cached_list || []);
    const pos = meta.position || { index: 1, percent: 0 };
    renderToc(RD.chapters, pos.index || 1);
    await goChapter(pos.index || 1, { percent: pos.percent || 0 });
  } catch (e) {
    // 打不开就把话说清楚，并且**把滚动锁交还** ——
    // 否则手机上是"页面卡死 + 上滑没反应"，比看不到内容更糟。
    setStageHTML(failHTML({
        key: "error_sad",
        line: "打不开这本书",
        sub: (e.message || "网络断了，或者服务没在跑") + " —— 点右上角 ✕ 退出去重试就行。",
      }));
    unlockScrollGuard();
  } finally {
    setStageBusy(false);
  }
}

/* 滚动锁：进阅读器时锁住背景页的滚动。
   两道保险 ——
     1) 明确解锁（closeReader / 打开失败）
     2) 兜底：万一有谁忘了解锁，鼠标滚不动、手指滑不动，也要能自救 */
let _scrollGuard = 0;
function lockScroll(on) {
  document.body.style.overflow = on ? "hidden" : "";
  clearTimeout(_scrollGuard);
  if (!on) return;
  // 3 秒后检查：如果阅读器已经不在前台了，说明解锁逻辑被漏掉了，补一刀
  _scrollGuard = setTimeout(() => {
    if (!$("#reader").classList.contains("on")) document.body.style.overflow = "";
  }, 3000);
}
function unlockScrollGuard() {
  clearTimeout(_scrollGuard);
  document.body.style.overflow = "";
}

export function closeReader() {
  const el = $("#reader");
  el.classList.remove("on", "immersive");
  RD.open = false;
  RD.bid = "";
  destroyFlip();
  $("#rdToc").classList.remove("on");
  $("#rdSet").classList.remove("on");
  // 必须无条件把滚动锁摘掉：一旦这行被跳过，body 就永久 overflow:hidden，
  // 手机上表现就是"整个页面卡住、上滑没反应"。宁可多清一次，也不能漏清。
  unlockScrollGuard();
  try { history.replaceState(null, "", location.pathname + location.hash.replace(/^#read=.*/, "")); } catch {}
  bus.emit("reader:closed");
}

/* ==========================================================================
   偏好
   ========================================================================== */
function applyPrefs() {
  const r = $("#reader");
  r.dataset.rdTheme = RD.theme;
  r.dataset.rdMode = RD.mode;
  r.style.setProperty("--rd-fs", RD.fs + "px");
  r.style.setProperty("--rd-lh", RD.lh);
  r.style.setProperty("--rd-measure", RD.w + "em");
  r.style.setProperty("--rd-ff",
    RD.ff === "serif" ? 'Georgia,"Songti SC","SimSun","Noto Serif SC",serif'
    : RD.ff === "kai" ? '"Kaiti SC",KaiTi,"STKaiti","Noto Serif SC",serif'
    : '-apple-system,"PingFang SC","Microsoft YaHei",sans-serif');

  PRE.set("rd_mode", RD.mode); PRE.set("rd_theme", RD.theme);
  PRE.set("rd_fs", RD.fs); PRE.set("rd_lh", RD.lh);
  PRE.set("rd_ff", RD.ff); PRE.set("rd_w", RD.w);

  $$("#rdThemes button").forEach(b => b.classList.toggle("on", b.dataset.th === RD.theme));
  const fsV = $("#rdFsV"); if (fsV) fsV.textContent = RD.fs + "px";
  $$("#rdLhRow button").forEach(b => b.classList.toggle("on", +b.dataset.lh === +RD.lh));
  $$("#rdFfRow button").forEach(b => b.classList.toggle("on", b.dataset.ff === RD.ff));
  $$("#rdWRow button").forEach(b => b.classList.toggle("on", +b.dataset.w === +RD.w));
  $$("#rdModeRow button").forEach(b => b.classList.toggle("on", b.dataset.mode === RD.mode));
}

/* ==========================================================================
   章节加载
   ========================================================================== */
/* 章节请求的**代次**。每发起一次 goChapter 就 +1。
   ⚠ 为什么需要它（真实竞态）：`goChapter` 是 async 的，中间有一个网络 `await`。
   用户连点「下一章」两次（或按住 ] 不放 / 滚动到底连续触发）会同时飞出**两个**
   请求，而 `RD.index = n` 是在 await **之后**才写的 —— 于是**后到的那份正文
   会覆盖掉先到的**，出现「章节号显示第 8 章、正文是第 7 章」的错位。
   旧请求返回时对不上号就直接丢弃，谁最后发出谁说了算。 */
let _chapSeq = 0;

async function goChapter(n, opt = {}) {
  if (!RD.bid) return;
  n = clamp(n, 1, RD.total || 1);

  const seq = ++_chapSeq;
  const bid = RD.bid;

  // 命中预取就直接用，省掉一次网络往返
  // ⚠ 必须连 bid 一起比对：`_pre` 是全局单槽，换书后旧书预取的正文会残留在里面。
  //   只比 index 的话，B 书第 6 章会渲染出 A 书第 6 章的正文。
  let d;
  if (RD._pre && RD._pre.index === n && RD._pre.bid === bid) {
    d = RD._pre.data; RD._pre = null;
  } else {
    RD.loading = true;
    setStageBusy(true);
    try {
      d = await api.get(`/api/library/${bid}/chapter/${n}`);
    } catch (e) {
      if (seq !== _chapSeq || bid !== RD.bid) return;   // 已经被更新的请求取代
      RD.loading = false;
      setStageBusy(false);
      setStageHTML(failHTML({
        key: "error_confused",
        line: "这一章没取到",
        sub: (e.message || "可能是来源限流了") + " —— 过一会儿点下面重试就行。",
      }) + `<p style="text-align:center;margin-top:14px">
        <button class="btn primary sm" id="rdRetry">再试一次</button></p>`);
      const btn = $("#rdRetry");
      if (btn) btn.onclick = () => goChapter(n);
      return;
    }
    RD.loading = false;
    setStageBusy(false);
  }

  // ⚠ 拿到正文后**再确认一次**：期间用户可能已经翻了别的章、甚至关了阅读器。
  //   （关阅读器时 `RD.bid` 会变空，所以两个判据都要看。）
  if (seq !== _chapSeq || bid !== RD.bid) return;

  RD.index = n;
  RD.cached.add(n);
  renderChapter(d);
  markToc(n);

  if (opt.percent > 0.001) {
    requestAnimationFrame(() => gotoPercent(opt.percent));
  }
  updateBar();
  savePosition();
  prefetch(n + 1);
}

function renderChapter(d) {
  const paras = splitParas(d.content || "");
  const title = d.title || ("第 " + d.index + " 章");
  if (!paras.length) {
    // 空正文不是"错误"，是"这次没拿到" —— 所以用犯困的噜噜（error_sad），
    // 而不是懵掉的那张。语义上更贴：「算了吧，过会儿再来」。
    setStageHTML(`<h2>${esc(title)}</h2>` + failHTML({
      key: "error_sad",
      line: "这一章没有正文",
      sub: "来源可能限流了。过一会儿点重试，或者去目录换一章接着读 —— 之前缓存的章节都还在。",
    }));
    RD.pages = []; updateBar();
    return;
  }

  const article = `<h2>${esc(title)}</h2>` + paras.map(p => `<p>${esc(p)}</p>`).join("");
  lastChapterHTML = article;

  destroyFlip();
  if (RD.mode === "scroll") {
    setStageHTML(article);
    RD.pages = [];
    RD.scrollFrac = 0;
    requestAnimationFrame(() => { updateScrollProgress(); });
  } else {
    buildPaged(article, title);
  }
  renderSub();
}

/** 把正文切成段落。
 *
 * 小说站有两种完全不同的排版习惯，必须都认：
 *   ① 空行分段    「第一段\n\n第二段」      —— 新笔趣阁系
 *   ② 单换行分段  「第一段\n第二段」        —— 无忧书城系（实测 37 行 = 37 段）
 *
 * 只按空行切的话，②类站点整章会变成**一个巨段**：
 * 分页时分不开、阅读器里也是一个密不透风的文字块。
 * 判据简单可靠：按空行切出来只有一两段、但换行却有一大堆 → 改成按行切。
 */
function splitParas(text) {
  const t = String(text || "");
  const byBlank = t.split(/\n\s*\n/).map(s => s.trim()).filter(Boolean);
  const newlines = (t.match(/\n/g) || []).length;
  if (byBlank.length <= 2 && newlines >= 4) {
    return t.split(/\n+/).map(s => s.trim()).filter(Boolean);
  }
  return byBlank;
}

function setStageHTML(html) {
  // 每个节点都判空：任何一个渲染宿主缺失，也不该让整条翻章链路崩掉
  // （曾经就是因为 #rdFlipBook 被 StPageFlip.destroy() 删掉，
  //   这里抛异常 → 目录/上一章/下一章全部静默失效）。
  const sb = $("#rdScrollBody"); if (sb) sb.innerHTML = html;
  const ss = $("#rdSlideStrip"); if (ss) ss.innerHTML = "";
  const fb = $("#rdFlipBook");   if (fb) fb.innerHTML = "";
}

function setStageBusy(on) {
  if (!on) return;
  // 用「噜噜在翻书」替代三个跳动圆点。
  // 圆点的问题不是丑，是**没有信息** —— 用户不知道在等什么。
  // 图 + 一行字至少传达了两件事：在动、在找书。
  const busy = busyHTML({ key: "loading_read", line: "正在取这一章…", compact: true });
  const wrap = `<div style="width:100%">${busy}</div>`;
  if (RD.mode === "scroll") {
    const sb = $("#rdScrollBody"); if (sb) sb.innerHTML = busy;
  } else {
    const ss = $("#rdSlideStrip"); if (ss) ss.innerHTML = wrap;
    const fb = $("#rdFlipBook");   if (fb) fb.innerHTML = "";
  }
}

function renderSub() {
  const bits = [RD.author || "作者未知"];
  if (RD.total) bits.push(`共 ${RD.total} 章`);
  const el = $("#rdSub");
  if (el) el.textContent = bits.join(" · ");
}

/* ==========================================================================
   分页
   ========================================================================== */

/**
 * 把整章切成"每页一段 HTML"。
 * 量尺用的就是真实的 .rd-page 结构，所以 CSS 里的字号/行距/内边距/栏宽
 * 一比一对上，不存在"JS 里算一套、浏览器排一套"的偏差。
 */
function paginate(article, title) {
  const stage = $(".rd-stage");
  const W = stage.clientWidth, H = stage.clientHeight;
  if (!W || !H) return [article];

  // 造一个离屏量尺：和真页同宽同高、同样的 class（拿到同样的排版）
  const ruler = document.createElement("div");
  ruler.className = "rd-page";
  ruler.style.cssText = `position:absolute;left:-999999px;top:0;width:${W}px;height:${H}px;visibility:hidden;pointer-events:none`;
  ruler.innerHTML = `<div class="pg-body" id="rdRulerBody">${article}</div>`;
  $(".rd-stage").appendChild(ruler);

  const body = $("#rdRulerBody", ruler);
  const pageH = body.clientHeight;
  const blocks = $$(":scope > *", body);
  if (!blocks.length) { ruler.remove(); return [article]; }

  // 关键：offsetTop 是布局算出来的真实位置，一次读取即可
  const items = blocks.map(b => ({
    top: b.offsetTop,
    h: b.offsetHeight,
    html: b.outerHTML,
  }));

  const pages = [];
  let cur = [], bottom = pageH;

  const flush = () => { if (cur.length) { pages.push(cur); cur = []; } };

  for (const it of items) {
    // 正常放得下
    if (it.top + it.h <= bottom + 1) { cur.push(it.html); continue; }

    // 单块比一整页还高 → 只能拆（罕见）
    if (it.h > pageH) {
      flush();
      const chunks = splitTallBlock(it.html, body, pageH);
      for (let i = 0; i < chunks.length; i++) {
        if (i === chunks.length - 1) { cur = [chunks[i]]; bottom = pageH; }
        else pages.push([chunks[i]]);
      }
      continue;
    }

    // 放不下 → 整段挪到下一页（段末留白，但不拆句）
    flush();
    bottom = it.top + pageH;
    cur.push(it.html);
  }
  flush();
  ruler.remove();
  return pages.length ? pages.map(p => p.join("")) : [article];
}

/** 段落自身高于整页时按字符二分，切出尽量填满的几块。 */
function splitTallBlock(html, body, pageH) {
  const probe = document.createElement("div");
  probe.style.cssText = `position:absolute;left:-999999px;top:0;width:${body.clientWidth}px`;
  document.body.appendChild(probe);

  const tag = (html.match(/^<\s*(\w+)/) || [, "p"])[1];
  const raw = html.replace(/^<[^>]+>/, "").replace(/<\/[^>]+>$/, "");

  const out = [];
  let rest = raw;
  let guard = 0;
  while (rest && guard++ < 200) {
    probe.innerHTML = `<${tag}>${rest}</${tag}>`;
    if (probe.offsetHeight <= pageH) { out.push(`<${tag}>${rest}</${tag}>`); break; }
    // 二分找"最长能放下"的前缀
    let lo = 1, hi = rest.length, best = 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      probe.innerHTML = `<${tag}>${rest.slice(0, mid)}</${tag}>`;
      if (probe.offsetHeight <= pageH) { best = mid; lo = mid + 1; }
      else hi = mid - 1;
    }
    out.push(`<${tag}>${rest.slice(0, best)}</${tag}>`);
    rest = rest.slice(best);
  }
  probe.remove();
  return out.length ? out : [html];
}

/* ==========================================================================
   渲染：平移模式
   ========================================================================== */
function buildPaged(article, title) {
  RD.pages = paginate(article, title);

  if (RD.mode === "slide") {
    const strip = $("#rdSlideStrip");
    const W = $(".rd-stage").clientWidth;
    strip.style.width = (RD.pages.length * W) + "px";
    strip.innerHTML = RD.pages.map((html, i) => `
      <div class="rd-page" style="width:${W}px">
        <div class="pg-body">${html}</div>
        <div class="pg-no">${i + 1} / ${RD.pages.length}</div>
      </div>`).join("");
    RD.page = 0;
    slideTo(0, false);
  } else {
    buildFlip();
  }
  updateBar();
}

function slideTo(p, animate = true) {
  const strip = $("#rdSlideStrip");
  const W = $(".rd-stage").clientWidth || 1;
  p = clamp(p, 0, Math.max(0, RD.pages.length - 1));
  RD.page = p;
  strip.classList.toggle("dragging", !animate);
  strip.style.transform = `translate3d(${-p * W}px,0,0)`;
  if (!animate) requestAnimationFrame(() => strip.classList.remove("dragging"));
  updateBar();
}

/* ==========================================================================
   渲染：仿真翻页（StPageFlip）
   ========================================================================== */
function destroyFlip() {
  if (RD.pf) { try { RD.pf.destroy(); } catch {} RD.pf = null; }
}

/* ⚠ 为什么把 StPageFlip 挂在一个**子节点**而不是 #rdFlipBook 本身
   --------------------------------------------------------------------------
   StPageFlip 的 destroy() 里有一句 `this.distElement.remove()` ——
   它会把**你传给它的那个宿主元素**直接从文档里删掉。
   我们传给它的正是 #rdFlipBook，于是：
     切到仿真翻页 → 再切回平移翻页 → destroy() → #rdFlipBook 从 DOM 消失
     → 之后 setStageBusy()/setStageHTML() 里 `$("#rdFlipBook")` 拿到 null
     → 抛 "Cannot set properties of null (setting 'innerHTML')"
     → 而且是在 goChapter() 的 await 之后抛的，被静默吞掉

   用户看到的现象就是：**只要用过一次「仿真翻页」，之后点目录 / 上一章 /
   下一章全部没反应** —— 典型的"点了没反应"低级错误。

   解法：给它一个用完就扔的子节点当宿主，destroy() 删的是子节点，
   #rdFlipBook 这个"门牌号"始终还在。
   -------------------------------------------------------------------------- */
function buildFlip() {
  const outer = $("#rdFlipBook");
  if (!outer) return;                 // 门牌号被人拆了（理论上不该发生）
  outer.innerHTML = "";
  const stage = $(".rd-stage");
  const availW = stage.clientWidth, availH = stage.clientHeight;
  // 纸张别铺满整个宽屏 —— 一页 1000px 宽的中文正文没法读
  const pageW = Math.min(availW, 760);
  const pageH = availH;

  outer.style.width = pageW + "px";
  outer.style.height = pageH + "px";

  // 真正的宿主：StPageFlip 删的是它
  const host = document.createElement("div");
  host.className = "flip-host";
  host.style.width = pageW + "px";
  host.style.height = pageH + "px";
  outer.appendChild(host);

  RD.pages.forEach((html, i) => {
    const d = document.createElement("div");
    d.className = "page";
    d.innerHTML = `<div class="pg-body">${html}</div><div class="pg-no">${i + 1} / ${RD.pages.length}</div>`;
    host.appendChild(d);
  });

  if (typeof window.St === "undefined" || !window.St.PageFlip) {
    // 库没加载出来（离线/被拦）→ 老实退回平移模式，而不是白屏
    console.warn("StPageFlip 未加载，退回平移模式");
    RD.mode = "slide";
    PRE.set("rd_mode", "slide");
    $("#reader").dataset.rdMode = "slide";
    $$("#rdModeRow button").forEach(b => b.classList.toggle("on", b.dataset.mode === "slide"));
    buildPaged(RD.pages.join(""), RD.title);
    toast("翻页组件没加载出来，已改用平移翻页", "warn");
    return;
  }

  const pages = $$(".page", host);
  try {
    RD.pf = new window.St.PageFlip(host, {
      width: pageW, height: pageH,
      size: "fixed",
      usePortrait: true,          // 单页显示：手机上必须，桌面也更好读
      showCover: false,
      drawShadow: true,
      maxShadowOpacity: 0.28,
      flippingTime: 620,
      mobileScrollSupport: false,
      swipeDistance: 22,
      showPageCorners: true,
      useMouseEvents: true,
      disableFlipByClick: true,   // 点击交给我们的分区逻辑，避免误触
      startPage: 0,
    });
    RD.pf.loadFromHTML(pages);
    RD.pf.on("flip", e => { RD.page = e.data; updateBar(); savePosition(); });
  } catch (err) {
    console.error(err);
    RD.mode = "slide";
    PRE.set("rd_mode", "slide");
    $("#reader").dataset.rdMode = "slide";
    $$("#rdModeRow button").forEach(b => b.classList.toggle("on", b.dataset.mode === "slide"));
    buildPaged(RD.pages.join(""), RD.title);
    toast("仿真翻页启动失败，已改用平移翻页", "warn");
    return;
  }
  RD.page = 0;
}

/* ==========================================================================
   翻页动作
   ========================================================================== */
function flash() {
  const f = $("#rdFlash");
  f.classList.remove("on");
  void f.offsetWidth;
  f.classList.add("on");
}

/* StPageFlip 的 flipNext/flipPrev 在单页（portrait）模式下并不可靠 ——
   实测 flipNext 能翻、flipPrev 静默无效（不报错也不动）。
   统一改用 turnToPage(目标页)，前进后退行为一致，也方便做边界判断。 */
function flipTo(page) {
  if (!RD.pf) return false;
  page = clamp(page, 0, Math.max(0, RD.pages.length - 1));
  try {
    RD.pf.turnToPage(page);
    RD.page = page;
    updateBar();
    savePosition();
    return true;
  } catch (e) {
    console.warn("翻页失败，退回平移模式", e);
    return false;
  }
}

export function pageNext() {
  if (RD.mode === "scroll") {
    const sc = $("#rdScroll");
    const max = sc.scrollHeight - sc.clientHeight;
    if (sc.scrollTop >= max - 24) goChapter(RD.index + 1);
    else sc.scrollBy({ top: sc.clientHeight * 0.88, behavior: "smooth" });
    return;
  }
  if (RD.page < RD.pages.length - 1) {
    if (RD.mode === "flip") flipTo(RD.page + 1);
    else { slideTo(RD.page + 1); flash(); }
  } else goChapter(RD.index + 1);
}

export function pagePrev() {
  if (RD.mode === "scroll") {
    const sc = $("#rdScroll");
    if (sc.scrollTop <= 24) goChapter(RD.index - 1);
    else sc.scrollBy({ top: -sc.clientHeight * 0.88, behavior: "smooth" });
    return;
  }
  if (RD.page > 0) {
    if (RD.mode === "flip") flipTo(RD.page - 1);
    else { slideTo(RD.page - 1); flash(); }
  } else goChapter(RD.index - 1);
}

function gotoPercent(p) {
  p = clamp(p, 0, 1);
  if (RD.mode === "scroll") {
    const sc = $("#rdScroll");
    const max = sc.scrollHeight - sc.clientHeight;
    sc.scrollTop = Math.max(0, max * p);
    updateScrollProgress();
  } else {
    const total = Math.max(1, RD.pages.length);
    const page = clamp(Math.round((total - 1) * p), 0, total - 1);
    if (RD.mode === "flip" && RD.pf) { try { RD.pf.turnToPage(page); } catch {} RD.page = page; }
    else slideTo(page, false);
    updateBar();
  }
}

/* ==========================================================================
   进度 / 状态栏
   ========================================================================== */
function updateBar() {
  const total = RD.total || 1;
  const frac = RD.mode === "scroll"
    ? (RD.scrollFrac || 0)
    : (RD.pages.length ? (RD.page + 1) / RD.pages.length : 0);

  const overall = clamp(((RD.index - 1) + frac) / total, 0, 1);
  const pct = (overall * 100).toFixed(1).replace(/\.0$/, "");

  const chap = $("#rdChap");
  if (chap) {
    // 手机上一行放不下「第 2 / 341 章 · 1/10 页」，会被省略号吃掉后半段 ——
    // 而页码恰恰是翻页时最需要看到的信息。窄屏改用紧凑写法。
    const narrow = window.innerWidth < 560;
    chap.textContent = narrow
      ? `${RD.index}/${total} 章 · ${RD.page + 1}/${Math.max(RD.pages.length, 1)} 页`
      : (RD.mode === "scroll"
          ? `第 ${RD.index} / ${total} 章`
          : `第 ${RD.index} / ${total} 章 · ${RD.page + 1}/${Math.max(RD.pages.length, 1)} 页`);
  }
  const pe = $("#rdPct"); if (pe) pe.textContent = pct + "%";
  const pr = $("#rdProg"); if (pr) pr.style.width = (overall * 100) + "%";
  const sf = $("#rdSeekF"); if (sf) sf.style.width = (overall * 100) + "%";
  const sh = $("#rdSeekH"); if (sh) sh.style.left = (overall * 100) + "%";

  const pv = $("#rdPrevCh"), nx = $("#rdNextCh");
  if (pv) pv.disabled = RD.index <= 1 && (RD.mode === "scroll" ? true : RD.page === 0);
  if (nx) nx.disabled = RD.index >= total;
}

function updateScrollProgress() {
  const sc = $("#rdScroll");
  if (!sc) return;
  const max = sc.scrollHeight - sc.clientHeight;
  RD.scrollFrac = max > 0 ? clamp(sc.scrollTop / max, 0, 1) : 1;
  updateBar();
}

const savePosition = debounce(() => {
  if (!RD.bid) return;
  const total = RD.total || 1;
  const frac = RD.mode === "scroll"
    ? (RD.scrollFrac || 0)
    : (RD.pages.length ? (RD.page + 1) / RD.pages.length : 0);
  const percent = clamp(((RD.index - 1) + frac) / total, 0, 1);
  api.post(`/api/library/${RD.bid}/position`, { index: RD.index, percent, offset: 0 }).catch(() => {});
  PRE.set("pos_" + RD.bid, { index: RD.index, percent });
}, 1400);

/* ==========================================================================
   预取下一章
   ========================================================================== */
async function prefetch(n) {
  if (n > RD.total || !RD.bid) return;
  if (RD._pre && RD._pre.index === n && RD._pre.bid === RD.bid) return;
  // ⚠ 进入时把「我是哪本书、哪一代」记下来。
  //
  // 实测踩到的坑：预取请求发出后用户**换了书**（或连点翻章），
  // 慢请求回来时无条件把结果写进 RD._pre —— 可 RD._pre 是**全局单槽**，
  // 于是 B 书翻到第 6 章时命中 A 书第 6 章的正文：
  // 标题栏写着 B 书第 6 章，正文却是 A 书的。
  // （goChapter 自己有 _chapSeq 守卫，但命中的是**别书的数据**，
  //   守卫在消费侧校验 bid/seq 都能过 —— 拦不住。）
  const seq = _chapSeq, bid = RD.bid;
  try {
    const d = await api.get(`/api/library/${bid}/chapter/${n}`);
    if (seq !== _chapSeq || bid !== RD.bid) return;   // 已经换书/换章，丢弃
    RD._pre = { index: n, data: d, bid };
  } catch {}
}

/* ==========================================================================
   目录
   ========================================================================== */
let tocTo = 0, tocAll = [], tocCur = 1;

function renderToc(chapters, cur) {
  tocAll = chapters; tocCur = cur; tocTo = 0;
  const box = $("#rdTocList");
  // ⚠ `box.onscroll` 每渲染一次就被换成新的闭包，但旧的那个不会被 GC ——
  //   它已经被浏览器的事件循环持有（同名属性只是"不再被引用"，不是"解绑"）。
  //   换书 / 重开阅读器时如果 DOM 没被清，之前的监听还会继续 fire，
  //   `appendToc` 于是被**调用两次**，同一段章节会以 480 条为步长重复插入。
  //   下次赋值是幂等的（属性覆盖），所以这里只需要保证渲染前**真的清空** DOM
  //   —— 清空了旧监听就找不到 `#rdTocList` 之外的东西可插，插进去也是空列表。
  box.innerHTML = "";
  box.scrollTop = 0;
  appendToc(0, 240);
  box.onscroll = () => {
    if (box.scrollTop + box.clientHeight > box.scrollHeight - 240) appendToc(tocTo, tocTo + 240);
  };
}

function appendToc(from, to) {
  const box = $("#rdTocList");
  if (!box || !tocAll.length) return;
  // 已经铺到哪儿了？——以 **DOM 里真实的条目数**为准，而不是 `tocTo`。
  // 两者本该一致；一旦因为"滚到底连触发两次 onscroll"而分叉，
  // 继续用 `tocTo` 就会把一个区间插两遍（章节号在目录里重复出现）。
  const already = box.querySelectorAll("a[data-i]").length;
  if (to <= already) { tocTo = already; return; }
  const chunk = tocAll.slice(already, to);
  if (!chunk.length) {
    if (!already) box.innerHTML = `<div class="lbl">没有目录</div>`;
    tocTo = already;
    return;
  }
  box.insertAdjacentHTML("beforeend", chunk.map(c => {
    const on = c.index === tocCur ? " on" : "";
    const has = RD.cached.has(c.index) ? " has" : "";
    return `<a href="#" class="${on}${has}" data-i="${c.index}"><span class="dotread"></span><span class="tx">${esc(c.title)}</span></a>`;
  }).join(""));
  tocTo = already + chunk.length;
}

function markToc(n) {
  tocCur = n;
  const box = $("#rdTocList");
  $$("a", box).forEach(a => {
    const isCur = +a.dataset.i === n;
    a.classList.toggle("on", isCur);
    if (RD.cached.has(+a.dataset.i)) a.classList.add("has");
    if (isCur && (a.offsetTop < box.scrollTop || a.offsetTop > box.scrollTop + box.clientHeight - 60)) {
      box.scrollTo({ top: Math.max(0, a.offsetTop - box.clientHeight / 2), behavior: "smooth" });
    }
  });
}

/* ==========================================================================
   手势 / 交互
   ========================================================================== */
function bindOnce() {
  if (bindOnce.done) return;
  bindOnce.done = true;

  // --- 点击分区：左翻、右翻、中间出工具栏 ---
  $(".rd-zones").addEventListener("click", e => {
    const z = e.target.closest(".rd-zone");
    if (!z) return;
    // 用户正在选字，别把页面翻走
    if (String(window.getSelection?.() || "").length > 2) return;
    if (z.classList.contains("l")) pagePrev();
    else if (z.classList.contains("r")) pageNext();
    else toggleChrome();
  });

  // --- 平移模式：跟手拖拽 ---
  const strip = $("#rdSlideStrip");
  const stage = $(".rd-stage");
  stage.addEventListener("pointerdown", e => {
    if (RD.mode !== "slide") return;
    if (e.pointerType === "mouse" && e.button !== 0) return;
    if (e.target.closest(".rd-zone.c")) return;
    RD._drag = { x0: e.clientX, y0: e.clientY, dx: 0, active: true };
  });
  stage.addEventListener("pointermove", e => {
    const d = RD._drag;
    if (!d || !d.active) return;
    d.dx = e.clientX - d.x0;
    // 纵向意图更明显 → 放行，交给滚动/系统手势
    if (Math.abs(e.clientY - d.y0) > Math.abs(d.dx) && Math.abs(d.dx) < 28) { d.active = false; return; }
    const W = stage.clientWidth || 1;
    const base = -RD.page * W;
    let x = base + d.dx;
    // 到头了还继续拖 → 阻尼，给"拉不动"的手感
    const min = -(RD.pages.length - 1) * W, max = 0;
    if (x > max) x = max + (x - max) * 0.32;
    if (x < min) x = min + (x - min) * 0.32;
    strip.classList.add("dragging");
    strip.style.transform = `translate3d(${x}px,0,0)`;
    try { stage.setPointerCapture(e.pointerId); } catch {}
  });
  const endDrag = () => {
    const d = RD._drag; RD._drag = null;
    if (!d || !d.active) return;
    strip.classList.remove("dragging");
    const W = stage.clientWidth || 1;
    if (d.dx < -W * 0.18) slideTo(RD.page + 1);
    else if (d.dx > W * 0.18) slideTo(RD.page - 1);
    else slideTo(RD.page);
    if (Math.abs(d.dx) > W * 0.18) flash();
  };
  stage.addEventListener("pointerup", endDrag);
  stage.addEventListener("pointercancel", endDrag);

  // --- 滚动模式进度 ---
  $("#rdScroll").addEventListener("scroll", () => {
    if (RD.mode === "scroll") updateScrollProgress();
  }, { passive: true });

  // --- 键盘 ---
  document.addEventListener("keydown", e => {
    if (!RD.open) return;
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea") { if (e.key === "Escape") e.target.blur(); return; }
    const k = e.key;
    if (k === "Escape") {
      if ($("#rdSet").classList.contains("on")) return $("#rdSet").classList.remove("on");
      if ($("#rdToc").classList.contains("on")) return $("#rdToc").classList.remove("on");
      return closeReader();
    }
    if (k === "ArrowRight" || k === "PageDown" || (k === " " && !e.shiftKey)) { e.preventDefault(); pageNext(); }
    else if (k === "ArrowLeft" || k === "PageUp" || (k === " " && e.shiftKey)) { e.preventDefault(); pagePrev(); }
    else if (k === "ArrowDown") { e.preventDefault(); if (RD.mode === "scroll") $("#rdScroll").scrollBy({ top: 120, behavior: "smooth" }); else pageNext(); }
    else if (k === "ArrowUp") { e.preventDefault(); if (RD.mode === "scroll") $("#rdScroll").scrollBy({ top: -120, behavior: "smooth" }); else pagePrev(); }
    else if (k === "]") goChapter(RD.index + 1);
    else if (k === "[") goChapter(RD.index - 1);
    else if (k === "t" || k === "T") $("#rdToc").classList.toggle("on");
    else if (k === "s" || k === "S") $("#rdSet").classList.toggle("on");
    else if (k === "f" || k === "F") toggleChrome();
  });

  // --- 尺寸变化：重排（手机横竖屏切换会走到这） ---
  window.addEventListener("resize", debounce(() => {
    if (!RD.open || RD.mode === "scroll" || !RD.pages.length) return;
    reflow();
  }, 260));
}

function toggleChrome() {
  const el = $("#reader");
  el.classList.toggle("immersive");
}

/* ==========================================================================
   设置面板 / 顶栏按钮
   ========================================================================== */
const RD_THEMES = [
  { id: "lumei", name: "噜妹", bg: "#fdf9f2", fg: "#2f2620" },
  { id: "day",   name: "日间", bg: "#fdfdfc", fg: "#2b2a27" },
  { id: "sepia", name: "羊皮", bg: "#f7eeda", fg: "#4b3f2f" },
  { id: "mint",  name: "护眼", bg: "#e6efe4", fg: "#2f3a30" },
  { id: "dusk",  name: "暮色", bg: "#1b1b1e", fg: "#c8c5bf" },
  { id: "black", name: "纯黑", bg: "#000000", fg: "#9d9d9d" },
];

export function mountReaderUI() {
  $("#rdThemes").innerHTML = RD_THEMES.map(t =>
    `<button data-th="${t.id}" title="${t.name}" style="background:${t.bg};color:${t.fg}">文</button>`).join("");

  $("#rdTocBtn").onclick = () => { $("#rdSet").classList.remove("on"); $("#rdToc").classList.toggle("on"); };
  $("#rdSetBtn").onclick = () => { $("#rdToc").classList.remove("on"); $("#rdSet").classList.toggle("on"); };
  $("#rdTocClose").onclick = () => $("#rdToc").classList.remove("on");
  $("#rdSetClose").onclick = () => $("#rdSet").classList.remove("on");
  $("#rdBack").onclick = closeReader;
  $("#rdExportBtn").onclick = () => {
    if (!RD.bid) return;
    bus.emit("reader:export", { library_id: RD.bid, title: RD.title, author: RD.author });
  };
  $("#rdCacheBtn").onclick = () => {
    if (!RD.bid) return;
    bus.emit("reader:cache", { id: RD.bid, title: RD.title });
  };
  $("#rdPrevCh").onclick = () => goChapter(RD.index - 1);
  $("#rdNextCh").onclick = () => goChapter(RD.index + 1);

  // ⚠ 目录里的「已缓存」小圆点要在缓存跑完后**当场亮起来**。
  //   `main.js` 一直在发 `reader:cache-done`，但**这里没人收** ——
  //   死代码。用户的真实体验是：读到一半点「缓存全书」，进度条跑完、
  //   章节其实已经落盘了，可目录上那些小圆点还是一片灰，看起来像"没缓存成"，
  //   于是他会再点一次（白跑一遍全量抓取）。
  //   这里收到事件后：把缓存清单补进去 → 让目录上对应条目点亮。
  bus.on("reader:cache-done", t => {
    if (!RD.open || !t || !t.library_id || t.library_id !== RD.bid) return;
    const n = Math.max(0, +t.done || 0);
    for (let i = 1; i <= n; i++) RD.cached.add(i);
    const box = $("#rdTocList");
    if (box) $$("a[data-i]", box).forEach(a => {
      if (RD.cached.has(+a.dataset.i)) a.classList.add("has");
    });
    if (t.partial) toast(`缓存完成，但有 ${(t.total || 0) - (t.done || 0)} 章没取到`, "warn");
  });

  $$("#rdThemes button").forEach(b => b.onclick = () => { RD.theme = b.dataset.th; applyPrefs(); });
  $$("#rdFsRow [data-fs]").forEach(b => b.onclick = () => {
    RD.fs = clamp(RD.fs + (+b.dataset.fs), 13, 32); applyPrefs(); reflow();
  });
  $$("#rdLhRow button").forEach(b => b.onclick = () => { RD.lh = +b.dataset.lh; applyPrefs(); reflow(); });
  $$("#rdFfRow button").forEach(b => b.onclick = () => { RD.ff = b.dataset.ff; applyPrefs(); reflow(); });
  $$("#rdWRow button").forEach(b => b.onclick = () => { RD.w = +b.dataset.w; applyPrefs(); reflow(); });
  $$("#rdModeRow button").forEach(b => b.onclick = () => {
    if (RD.mode === b.dataset.mode) return;
    RD.mode = b.dataset.mode;
    applyPrefs();
    if (lastChapterHTML) {
      const d = parseChapterHTML(lastChapterHTML);
      destroyFlip();
      if (RD.mode === "scroll") { setStageHTML(lastChapterHTML); RD.pages = []; requestAnimationFrame(updateScrollProgress); }
      else buildPaged(lastChapterHTML, d.title);
    }
  });

  // 进度条：点一下跳章，拖拽则连续预览
  const seek = $("#rdSeek");
  const seekAt = clientX => {
    const r = seek.getBoundingClientRect();
    return clamp((clientX - r.left) / r.width, 0, 1);
  };
  const tip = $("#rdTip");
  seek.addEventListener("pointerdown", e => {
    seek.classList.add("dragging");
    seek.setPointerCapture(e.pointerId);
    const f = seekAt(e.clientX);
    const ch = Math.max(1, Math.round(f * (RD.total || 1)));
    tip.textContent = `第 ${ch} 章`;
    tip.style.left = (f * 100) + "%";
    $("#rdSeekF").style.width = (f * 100) + "%";
    $("#rdSeekH").style.left = (f * 100) + "%";
  });
  seek.addEventListener("pointermove", e => {
    if (!seek.classList.contains("dragging")) return;
    const f = seekAt(e.clientX);
    const ch = Math.max(1, Math.round(f * (RD.total || 1)));
    tip.textContent = `第 ${ch} 章`;
    tip.style.left = (f * 100) + "%";
    $("#rdSeekF").style.width = (f * 100) + "%";
    $("#rdSeekH").style.left = (f * 100) + "%";
  });
  const seekEnd = e => {
    if (!seek.classList.contains("dragging")) return;
    seek.classList.remove("dragging");
    const f = seekAt(e.clientX);
    goChapter(Math.max(1, Math.round(f * (RD.total || 1))));
  };
  seek.addEventListener("pointerup", seekEnd);
  seek.addEventListener("pointercancel", () => seek.classList.remove("dragging"));

  $("#rdTocQ").addEventListener("input", e => {
    const q = e.target.value.trim();
    if (!q) { renderToc(tocAll, tocCur); return; }
    const hits = tocAll.filter(c => (c.title || "").includes(q));
    $("#rdTocList").innerHTML = hits.length
      ? hits.slice(0, 300).map(c => `<a href="#" data-i="${c.index}"><span class="dotread"></span><span class="tx">${esc(c.title)}</span></a>`).join("")
      : `<div class="lbl">没有匹配的章节</div>`;
  });
  $("#rdTocList").addEventListener("click", e => {
    const a = e.target.closest("a");
    if (!a) return;
    e.preventDefault();
    goChapter(+a.dataset.i);
    if (window.innerWidth < 900) $("#rdToc").classList.remove("on");
  });

  bindOnce();
}

/** 字体/行距/栏宽变了必须重新分页 —— 页数会变，页码也要跟着走。 */
function reflow() {
  if (!RD.open || !lastChapterHTML) return;
  // ⚠ 滚动模式**也有重排要做**。以前这里直接 `return` —— 于是用户在滚动模式
  //   下调字号 / 行高 / 栏宽，正文的视觉宽度变了，但 `RD.scrollFrac` 是按
  //   **旧的** scrollHeight 算出来的百分比，接下来保存进度时会把它当成
  //   "当前读到哪" 上报。真实后果：调到小字号后，同一段文字占据的滚动比例
  //   从 60% 缩到 35%，用户**下一次打开这本书会莫名其妙往前跳一截**。
  //   滚动模式没有"页"要重排，但要按当前阅读比例**重新对齐滚动位置**，
  //   并让 scrollFrac 与新的 scrollHeight 保持一致。
  if (RD.mode === "scroll") {
    const keep = RD.scrollFrac || 0;
    requestAnimationFrame(() => {
      const sc = $("#rdScroll");
      if (!sc) return;
      const max = sc.scrollHeight - sc.clientHeight;
      sc.scrollTop = max > 0 ? Math.round(keep * max) : 0;
      updateScrollProgress();
    });
    return;
  }
  const keep = RD.pages.length ? RD.page / Math.max(RD.pages.length - 1, 1) : 0;
  destroyFlip();
  const title = parseChapterHTML(lastChapterHTML).title;
  RD.pages = paginate(lastChapterHTML, title);
  if (RD.mode === "slide") {
    const strip = $("#rdSlideStrip");
    const W = $(".rd-stage").clientWidth;
    strip.style.width = (RD.pages.length * W) + "px";
    strip.innerHTML = RD.pages.map((html, i) => `
      <div class="rd-page" style="width:${W}px"><div class="pg-body">${html}</div>
      <div class="pg-no">${i + 1} / ${RD.pages.length}</div></div>`).join("");
    slideTo(Math.round(keep * (RD.pages.length - 1)), false);
  } else {
    buildFlip();
    if (RD.pf) { try { RD.pf.turnToPage(Math.round(keep * (RD.pages.length - 1))); } catch {} }
  }
}

function parseChapterHTML(html) {
  const m = html.match(/<h2[^>]*>([\s\S]*?)<\/h2>/);
  return { title: m ? m[1].replace(/<[^>]+>/g, "") : "" };
}
