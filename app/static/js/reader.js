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
  // 换书必须清掉目录去重哨兵（见 setTocHTML 的注释）——否则这本新书的
  // 目录若与上一本"恰好逐字相同"（比如同一本书重开），会被判成重复而
  // **不推给 Vue**，表现为"打开这本书目录是空的 / 还是上一本的"。
  _rdTocHTMLSent = null;

  const el = $("#reader");
  el.classList.add("on");
  RD.open = true;
  lockScroll(true);
  applyPrefs();

  try { history.replaceState(null, "", "#read=" + RD.bid); } catch {}

  // ⚠ `#rdTitle`（顶栏书名）已迁 Vue —— Vue 路径下它由 syncReader() 推的
  //   `title` 渲染，这里**不能再无条件写 DOM**：
  //   踩过：原来是无条件的 `$("#rdTitle").textContent = ...`，
  //   而迁移后 `#rdTitle` 不再是静态 HTML（Vue 的 `<b>` 当时没有 id）→
  //   `$()` 返回 null → 这一行抛 TypeError →
  //   **`openReader` 在 `renderToc()` / `goChapter()` 之前就中断了**。
  //   表现极具迷惑性：`#reader.on` 已经加上（前面几行），阅读器"打开了"、
  //   顶栏底栏都在（Vue 渲的），但目录永远空、章节永远 `—`、正文不加载
  //   —— 看着像"目录模块坏了"，其实是这行 null 写崩了整条启动链路。
  //   这类"迁走的东西还留在旧写路径里"是迁移期最危险的坑：静态检查发现不了
  //   （`$()` 的返回类型是 any），只有真机跑一遍才现形。
  //   修法：判容器 + 保留 id（非 Vue 路径照旧）。
  if (vueOwnsReaderShell()) syncReader();
  else $("#rdTitle").textContent = RD.title;
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
  setReaderFields({ tocOpen: false, setOpen: false });
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

  // ⚠⚠ `#reader` 的 `data-rd-theme` 与 `--rd-*` 变量上面已经设好了，**没有**迁到 Vue。
  //   为什么：那是分页算法的输入（`paginate()` 读 `.rd-stage` 的 clientWidth/
  //   clientHeight，而它受 `--rd-pad` / `--rd-measure` / `--rd-fs` 影响）。
  //   如果这些变量由 Vue 异步写，分页可能在"旧字号"下算完 → 页数偏差。
  //   Vue 那边只负责"哪个色卡是选中的"，实质排版仍由这里同步写 style。
  setThemes();
  setSegs();
}

/** 色卡那一排按钮的 HTML（六个色卡，内容固定）。
 *  ⚠ 生成一次、两条路径共用：Vue 在时喂给 v-html，不在时写进 DOM。
 *    如果两边各拼一遍字符串，早晚会改一处忘一处（"新增一个色卡，
 *    只有旧实现看得到"），所以宁可多存一个变量。
 *
 *  ⚠⚠ `.on` 必须**在这里打**，不能指望别处补。
 *     踩过：当初的想法是"HTML 是死的、选中态由 Vue 打 .on" ——
 *     但这一段 HTML 是 **v-html** 喂给 Vue 的，**Vue 不会去改 v-html
 *     内容里的 class**（它是原样 innerHTML，不参与 patch）。
 *     于是切主题后色卡高亮永远停在初始那个。所以生成时就把 `.on`
 *     按当前 `RD.theme` 拼进去；切主题时由 `renderThemeSwatches()`
 *     重新生成整段（它本来就挂在 applyPrefs 里）。 */
function themesHTML() {
  return RD_THEMES.map(t =>
    `<button data-th="${t.id}" title="${t.name}"${t.id === RD.theme ? ' class="on"' : ""} ` +
    `style="background:${t.bg};color:${t.fg}">文</button>`).join("");
}

function renderThemeSwatches() {
  _rdThemesHTML = themesHTML();
  if (_rdApply) _rdApply({ themesHTML: _rdThemesHTML });
  if (vueOwnsReaderShell()) return;
  const box = $("#rdThemes");
  if (box) box.innerHTML = _rdThemesHTML;
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
  setReaderField("sub", bits.join(" · "));
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

  // 手机上一行放不下「第 2 / 341 章 · 1/10 页」，会被省略号吃掉后半段 ——
  // 而页码恰恰是翻页时最需要看到的信息。窄屏改用紧凑写法。
  const narrow = window.innerWidth < 560;
  const chapTxt = narrow
    ? `${RD.index}/${total} 章 · ${RD.page + 1}/${Math.max(RD.pages.length, 1)} 页`
    : (RD.mode === "scroll"
        ? `第 ${RD.index} / ${total} 章`
        : `第 ${RD.index} / ${total} 章 · ${RD.page + 1}/${Math.max(RD.pages.length, 1)} 页`);

  // ⚠⚠ 这三个字段**必须一次推完**，不能各自调一次 setReaderField。
  //
  //   为什么（实测卡顿的根因，两层）：
  //   ① `setReaderField` 内部会调 `syncReader()`，每次推**一份完整快照**。
  //      翻一页要改 chap/pct/progress 三个字段 → 旧写法连调三次 → 推三份。
  //   ② 更狠的是：`syncReader()` 的快照里**曾经还带着 `tocHTML`**
  //      —— 整本书的目录，大书几千条 `<a>`、几 MB 的字符串。
  //      于是"翻一页"= 把整份目录序列化并过一遍 Vue 响应式，而且 ×3。
  //      一本 3000 章的书，一次翻页就在搬几 MB 字符串 ×3 次。
  //
  //   这就是「阅读器有点卡」的来源。跟"几个人访问"完全无关 ——
  //   它纯粹是**单机**开销，人多人少一样卡（多人在线只会让服务器忙，
  //   但那是另一条链路，不是这里）。
  //
  //   修法（两处一起改才根治）：
  //   · 这里改成一次 `setReaderFields({chap, pct, progress})`，内部只 sync 一次；
  //   · `syncReader()` 里**删掉 `tocHTML`**，目录改由 renderToc()/setTocHTML()
  //     在目录真的变化时单独推。
  //   Vue 那边本来就是把这几个字段合并渲染的，一次推和三次推**结果完全相同**，
  //   只是少了两次全量 diff（以及几 MB 的无谓字符串传递）。
  setReaderFields({ chap: chapTxt, pct: pct + "%", progress: overall });
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

/* 目录列表的**取节点入口**。
 *
 * ⚠⚠ 为什么需要这层间接（迁移期最关键的一处设计）：
 *   非 Vue 路径下，目录列表就是页面里那个 `#rdTocList`，旧逻辑直接
 *   `box.innerHTML=""` / `box.querySelectorAll("a[data-i]")` / `box.scrollTo(...)`。
 *   Vue 路径下 `#rdTocList` 是 **Vue 渲染的**，而且它的内容靠 `v-html` —— 
 *   Vue 会**在下一帧把我们的写入覆盖掉**，直接写它会：① 与 v-html 打架，
 *   ② 读到的是上一帧的节点（Vue 异步）。
 *
 *   修法：Vue 接管时改用**内存镜像**（一个游离的 `<div>`），
 *   `appendToc()` 里那段"以 DOM 真实条目数为准"的防重复逻辑**一字不改**
 *   地跑在这个镜像上，跑完把 `mirror.innerHTML` 整段通过 setTocHTML()
 *   推给 Vue。好处：
 *     · 增量/去重/高亮逻辑只维护一份（镜像上），零重写、零分叉风险；
 *     · Vue 那边永远只收到"当前完整快照"，不需要知道增量过程；
 *     · 旧逻辑里对 DOM 的所有 API（querySelectorAll / insertAdjacentHTML）
 *       在镜像上语义完全一致（它就是个真 div，只是不在文档里）。
 *   代价：每次 append 要序列化一次 HTML（几百条 a 标签，几毫秒，可接受）。 */
let _rdTocMirror = null;
function tocBox() {
  if (!vueOwnsReaderShell()) return $("#rdTocList");
  // ⚠ 每次重新确认容器：换书 / 重开阅读器会清空，镜像必须跟着新开一个
  //   （否则残留上一本的条目，`already` 从几百开始 → 新目录永远铺不出来）。
  if (!_rdTocMirror) _rdTocMirror = document.createElement("div");
  return _rdTocMirror;
}

/** 换书 / 重开阅读器时把镜像也清掉（与 DOM 的清空同步）。 */
function resetTocBox() { _rdTocMirror = null; }

function renderToc(chapters, cur) {
  tocAll = chapters; tocCur = cur; tocTo = 0;
  resetTocBox();
  const box = tocBox();
  // ⚠ `box.onscroll` 每渲染一次就被换成新的闭包，但旧的那个不会被 GC ——
  //   它已经被浏览器的事件循环持有（同名属性只是"不再被引用"，不是"解绑"）。
  //   换书 / 重开阅读器时如果 DOM 没被清，之前的监听还会继续 fire，
  //   `appendToc` 于是被**调用两次**，同一段章节会以 480 条为步长重复插入。
  //   下次赋值是幂等的（属性覆盖），所以这里只需要保证渲染前**真的清空** DOM
  //   —— 清空了旧监听就找不到 `#rdTocList` 之外的东西可插，插进去也是空列表。
  if (!box) return;
  box.innerHTML = "";
  box.scrollTop = 0;
  if (vueOwnsReaderShell()) setTocHTML("");
  appendToc(0, 240);
  // ⚠ 滚动监听必须绑在**可见的那个节点**上：
  //   非 Vue 路径 = `#rdTocList` 自己（box 就是它）；
  //   Vue 路径 = `#rdTocList` 仍然是滚动容器（Vue 渲染出来的），
  //     而 box 是内存镜像（不在文档里、clientHeight 恒为 0、永远不会滚）。
  //   绑错的表现：镜像的 scrollHeight 也永远 0，"滚到底再加载"永不触发
  //   → 目录只有前 240 条。
  const scroller = vueOwnsReaderShell() ? $("#rdTocList") : box;
  if (!scroller) return;
  scroller.onscroll = () => {
    if (scroller.scrollTop + scroller.clientHeight > scroller.scrollHeight - 240) {
      appendToc(tocTo, tocTo + 240);
    }
  };
}

function appendToc(from, to) {
  const box = tocBox();
  if (!box || !tocAll.length) return;
  // 已经铺到哪儿了？——以 **DOM 里真实的条目数**为准，而不是 `tocTo`。
  // 两者本该一致；一旦因为"滚到底连触发两次 onscroll"而分叉，
  // 继续用 `tocTo` 就会把一个区间插两遍（章节号在目录里重复出现）。
  const already = box.querySelectorAll("a[data-i]").length;
  if (to <= already) { tocTo = already; return; }
  const chunk = tocAll.slice(already, to);
  if (!chunk.length) {
    if (!already) {
      box.innerHTML = `<div class="lbl">没有目录</div>`;
      if (vueOwnsReaderShell()) setTocHTML(box.innerHTML);
    }
    tocTo = already;
    return;
  }
  box.insertAdjacentHTML("beforeend", chunk.map(c => {
    const on = c.index === tocCur ? " on" : "";
    const has = RD.cached.has(c.index) ? " has" : "";
    return `<a href="#" class="${on}${has}" data-i="${c.index}"><span class="dotread"></span><span class="tx">${esc(c.title)}</span></a>`;
  }).join(""));
  tocTo = already + chunk.length;
  // ⚠ 目录是**增量**长出来的（滚到底再 append 240 条）。Vue 接管后
  //   `#rdTocList` 的内容由 v-html 决定，所以每 append 一批就要把
  //   当前的整段 HTML 同步过去 —— 否则下一页 240 条永远不会出现
  //   （旧代码是直接往 DOM 里 insertAdjacentHTML，Vue 那边毫无感知）。
  //   代价：每次同步要序列化一遍已有条目（几百条时几毫秒），可接受；
  //   换成"增量推给 Vue 再拼"要维护两份顺序，反而更容易错。
  if (vueOwnsReaderShell()) setTocHTML(box.innerHTML);
}

function markToc(n) {
  tocCur = n;
  const box = tocBox();
  if (!box) return;
  // ⚠ 高亮写在**镜像**上（那是内容的权威来源，v-html 下一帧会照着它渲），
  //   而"滚到当前章"必须作用在**可见节点**上 —— 镜像不在文档里，
  //   它的 clientHeight/scrollTop 恒为 0，`scrollTo` 是空操作，
  //   而且 mirror 里元素的 `offsetTop` 也是 0 → 定位会算到 -height/2。
  //   这正是"目录滚不到当前章"的成因（如果两个都用 box 的话）。
  const live = vueOwnsReaderShell() ? $("#rdTocList") : box;
  $$("a", box).forEach(a => {
    const isCur = +a.dataset.i === n;
    a.classList.toggle("on", isCur);
    if (RD.cached.has(+a.dataset.i)) a.classList.add("has");
  });
  // 滚到当前章：在 in-document 的节点上重查一次（镜像里的元素不在文档，
  // 没有布局信息）。Vue 路径下内容是上一帧同步过去的，若此刻 DOM 还没
  // 更新（用户翻页很快），这一帧跳过、下一帧 markToc 会再来一次。
  if (live) {
    const cur = live.querySelector(`a[data-i="${n}"]`);
    if (cur && (cur.offsetTop < live.scrollTop
        || cur.offsetTop > live.scrollTop + live.clientHeight - 60)) {
      live.scrollTo({ top: Math.max(0, cur.offsetTop - live.clientHeight / 2), behavior: "smooth" });
    }
  }
  // 翻页时"当前章"高亮跟着走 —— Vue 那边是 v-html，必须把新的 class 同步过去
  if (vueOwnsReaderShell()) setTocHTML(box.innerHTML);
}

/* ==========================================================================
   手势 / 交互
   ========================================================================== */
function bindOnce() {
  if (bindOnce.done) return;
  bindOnce.done = true;

  // --- 点击分区：左翻、右翻、中间出工具栏 ---
  //   ⚠ 与下面的拖拽是这样分工的：**先按下并移动超过阈值 → 判为拖拽**
  //   （拖拽已经在 pointerup 里翻好页了，这里直接跳过）；
  //   只有"按下即抬起、几乎没移动"才算点击。
  //   不这样分的话，一次滑动翻页会在结束时**再触发一次 click**，
  //   变成"滑一页翻两页"。`_sawDragAt` 就是用来消掉这次多余 click 的。
  $(".rd-zones").addEventListener("click", e => {
    const z = e.target.closest(".rd-zone");
    if (!z) return;
    // 刚刚是拖拽（600ms 内）→ 这次 click 是浏览器补发的，吞掉。
    // ⚠ 用"时间戳"而不是布尔 + 定时器：定时器要处理"拖拽中又移动"
    //   （反复重置）、"endDrag 没跑"（永不复位）两种情况，很容易写错；
    //   时间戳是纯读的判据，到点自然失效，不会卡死。
    if (now() - _sawDragAt < 600) return;
    // 用户正在选字，别把页面翻走
    if (String(window.getSelection?.() || "").length > 2) return;
    if (z.classList.contains("l")) pagePrev();
    else if (z.classList.contains("r")) pageNext();
    else toggleChrome();
  });

  // --- 跟手拖拽翻页（平移模式自己实现；仿真模式交给 StPageFlip）---
  //
  //  ⚠ 两种模式的分工必须写清，否则会互相打架：
  //    · slide → 本段代码全权处理（拖 strip、松手按位移决定翻不翻）
  //    · flip  → **不要**在 pointerdown 里建 `_drag` —— StPageFlip 自己有
  //      `useMouseEvents:true` + `swipeDistance:22`，它监听 mouse 事件翻页。
  //      我们再插一手会把它的拖拽打断（而且 `_drag` 对 flip 也没意义：
  //      strip 在 flip 模式下不存在 / 不可见）。
  //    之前 flip 的滑动"能用但别扭"，根因不是这里，而是 `.rd-zones`
  //    那层覆盖 div 没有 `touch-action:none`（见 reader.css）——
  //    手指一动的 pointer 流被浏览器取消去滚动页面了。
  const strip = $("#rdSlideStrip");
  const stage = $(".rd-stage");
  stage.addEventListener("pointerdown", e => {
    if (RD.mode !== "slide") return;
    if (e.pointerType === "mouse" && e.button !== 0) return;
    // 让**中间区**也能起手拖 —— 以前这里直接 `return` 掉了（`.rd-zone.c`），
    // 于是"从屏幕正中左右滑"永远没反应，只有边缘 26% 能滑，
    // 而正中占 48% 宽 —— 这正是"只会点击翻页"观感的主要来源。
    RD._drag = { x0: e.clientX, y0: e.clientY, dx: 0, active: true, moved: false };
  });
  stage.addEventListener("pointermove", e => {
    const d = RD._drag;
    if (!d || !d.active) return;
    d.dx = e.clientX - d.x0;
    // 纵向意图更明显 → 放行，交给滚动/系统手势
    if (Math.abs(e.clientY - d.y0) > Math.abs(d.dx) && Math.abs(d.dx) < 28) {
      d.active = false;
      d.moved = false;
      return;
    }
    // 位移够大才算"真的在拖" —— 这个标记有两个用途：
    //   ① 记下"刚刚是拖拽"，让松手后那次多余的 click 不翻页（防"滑一页翻两页"）；
    //   ② 没超阈值时不算拖，纯点击照常走 toggleChrome。
    if (Math.abs(d.dx) > 8) {
      d.moved = true;
      _sawDragAt = now();
    }
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
    // 阈值从 18% 降到 12%：手机上"轻扫一下"通常只有屏幕宽的一成多，
    // 18% 要求手指划过近 1/5 屏才算数，体感偏"滑不动"。
    const TH = 0.12;
    if (d.dx < -W * TH) slideTo(RD.page + 1);
    else if (d.dx > W * TH) slideTo(RD.page - 1);
    else slideTo(RD.page);
    if (Math.abs(d.dx) > W * TH) flash();
    // 松手后浏览器补的那次 click 由 `_sawDragAt` 时效自然吞掉，这里不用动。
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
      // ⚠ 判"面板开着没"读的是**影子状态**，不是 `classList.contains("on")`。
      //   Vue 接管后那两个面板的 class 由 Vue 渲染，而 Vue 是**异步**更新 DOM 的
      //   —— 用户刚按 T 开了目录、立刻按 Esc，此刻 DOM 上可能还没有 "on"，
      //   于是旧写法会误判成"面板没开"、直接把整个阅读器关掉。
      //   影子状态是同步的，不存在这一帧的落后。
      if (_rdSetOpen) return setReaderField("setOpen", false);
      if (_rdTocOpen) return setReaderField("tocOpen", false);
      return closeReader();
    }
    if (k === "ArrowRight" || k === "PageDown" || (k === " " && !e.shiftKey)) { e.preventDefault(); pageNext(); }
    else if (k === "ArrowLeft" || k === "PageUp" || (k === " " && e.shiftKey)) { e.preventDefault(); pagePrev(); }
    else if (k === "ArrowDown") { e.preventDefault(); if (RD.mode === "scroll") $("#rdScroll").scrollBy({ top: 120, behavior: "smooth" }); else pageNext(); }
    else if (k === "ArrowUp") { e.preventDefault(); if (RD.mode === "scroll") $("#rdScroll").scrollBy({ top: -120, behavior: "smooth" }); else pagePrev(); }
    else if (k === "]") goChapter(RD.index + 1);
    else if (k === "[") goChapter(RD.index - 1);
    else if (k === "t" || k === "T") rdTogglePanel("toc");
    else if (k === "s" || k === "S") rdTogglePanel("set");
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
  renderThemeSwatches();

  // ⚠ 顶栏那三个按钮（目录/设置/退出）以及两个面板的关闭按钮，
  //   一旦迁到 Vue 就不再是"静态 HTML 元素"了 —— 旧代码这里拿
  //   `$("#rdTocBtn")` 会拿到 null（Vue 渲染的节点还没出现或已重建）。
  //   所以整段绑定都要**判容器**：Vue 在时交给 Vue（它 @click 调同名桥接函数），
  //   不在时才由这里挂。
  if (!vueOwnsReaderShell()) {
    $("#rdTocBtn").onclick = () => rdTogglePanel("toc");
    $("#rdSetBtn").onclick = () => rdTogglePanel("set");
    $("#rdTocClose").onclick = () => rdClosePanels();
    $("#rdSetClose").onclick = () => rdClosePanels();
  }
  // ⚠ 顶栏所有按钮都要判容器 —— 迁到 Vue 之后它们不再是"静态 HTML 元素"，
  //   而且 `$("#rdBack")` 可能为 null（Vue 节点还没渲染或已被 patch 掉）→
  //   这里无条件 `el.onclick = ...` 会**直接抛错**，把 mountReaderUI 后半段
  //   （包括进度条绑手势）全部跳过 —— 表现是"进度条拖不动、目录点不动"。
  //   踩过：`$("#rdBack").onclick = closeReader` 原来是无条件执行的。
  if (!vueOwnsReaderShell()) {
    $("#rdBack").onclick = closeReader;
    $("#rdExportBtn").onclick = () => {
      if (!RD.bid) return;
      bus.emit("reader:export", { library_id: RD.bid, title: RD.title, author: RD.author });
    };
    $("#rdCacheBtn").onclick = () => {
      if (!RD.bid) return;
      bus.emit("reader:cache", { id: RD.bid, title: RD.title });
    };
  }
  // 这两个留在静态 HTML（窄屏重排直接子选择器依赖它们的位置），两边通用
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
    // ⚠ 走 tocBox()：Vue 路径下内容的权威来源是**镜像**，
    //   只点亮可见 DOM 的话，下一次 setTocHTML()（翻页时的 markToc）
    //   会把镜像里"还没点亮"的旧 HTML 覆盖回去 —— 小圆点又会灭掉。
    const box = tocBox();
    if (box) $$("a[data-i]", box).forEach(a => {
      if (RD.cached.has(+a.dataset.i)) a.classList.add("has");
    });
    if (vueOwnsReaderShell()) setTocHTML(box ? box.innerHTML : "");
    if (t.partial) toast(`缓存完成，但有 ${(t.total || 0) - (t.done || 0)} 章没取到`, "warn");
  });

  // 设置面板里的一次性选项：Vue 在时全部由组件模板 @click="..." 调 rdSetOpt，
  // 这里只负责"没迁时"的绑定 —— 两边走**同一个** rdSetOpt，行为不会分叉。
  if (!vueOwnsReaderShell()) {
    $$("#rdThemes button").forEach(b => b.onclick = () => rdSetTheme(b.dataset.th));
    $$("#rdFsRow [data-fs]").forEach(b => b.onclick = () => rdSetOpt("fs", b.dataset.fs));
    $$("#rdLhRow button").forEach(b => b.onclick = () => rdSetOpt("lh", b.dataset.lh));
    $$("#rdFfRow button").forEach(b => b.onclick = () => rdSetOpt("ff", b.dataset.ff));
    $$("#rdWRow button").forEach(b => b.onclick = () => rdSetOpt("w", b.dataset.w));
    $$("#rdModeRow button").forEach(b => b.onclick = () => rdSetOpt("mode", b.dataset.mode));
  }

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

  if (!vueOwnsReaderShell()) {
    $("#rdTocQ").addEventListener("input", e => rdFilterToc(e.target.value));
    $("#rdTocList").addEventListener("click", e => {
      const a = e.target.closest("a");
      if (!a) return;
      e.preventDefault();
      rdGoChapter(a.dataset.i);
    });
  }

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

/* ==========================================================================
   迁移桥：把「阅读器外壳（.rd-prog / .rd-top / .rd-bottom / 两个面板）」
   交给 Vue 渲染，旧代码继续管「分页 + 翻页 + 滚动」这块实质逻辑。
   ==========================================================================

   为什么要迁：阅读页是**用户停留最久**的界面（有人一读一晚上），
   它的外壳（标题栏、进度条、设置面板、目录）现在还是旧代码用 innerHTML
   拼字符串 —— 想加个新轮子（滑杆用 Naive 的、目录虚拟滚动、设置面板
   分组折叠）就得动一大坨字符串拼接。迁完之后外壳是声明式的，加东西容易。

   为什么不整页迁：分页算法（paginate）、三种翻页模式、StPageFlip 的
   生命周期、以及 `#reader[data-rd-theme]` 那套 CSS 变量，都是
   **已经被真机测试钉死**的行为（test_reader 30 项）。整页重写风险大、
   收益低 —— 那些逻辑本来就不该被"框架"接管（它跟 DOM 的布局测量强耦合，
   Vue 的声明式帮不上忙，反而隔了一层不好读 clientWidth/clientHeight）。

   所以边界划在：**Vue 管"长什么样"，旧代码管"怎么翻页"**。

   ⚠⚠ 两条硬约束（踩过才知道，改这里必须守住）：

   1) **舞台区（.rd-stage 里的三个 .rd-view）必须留在 Vue 容器之外。**
      `paginate()` 靠 `$(".rd-stage")` 量 clientWidth/clientHeight、
      靠 `$("#rdRulerBody")` 读 offsetTop，`buildFlip()` 直接操作
      `#rdFlipBook` 建 StPageFlip 实例。这些元素一旦被 Vue 接管，
      Vue 会在 patch 时**重建节点** —— StPageFlip 持有的旧节点引用立刻失效，
      表现是"翻页动画突然失效 / 分页位置错乱"，而且是偶发的、极难查。
      所以容器挂在 `#reader` 内部、但**包住 stage 之外的兄弟节点**。

   2) **Vue 组件模块顶层不能求值 legacy(...)。**
      页面里两个 `<script type="module">`（旧 main.js 与 vue-app.js）
      **并行**加载，谁先执行不确定，而桥是旧 util.js 挂的 ——
      早一步就抛错。所有桥接项必须包一层惰性取值。

   3) **渲染进 Vue 的 DOM 用的是 `v-html`，内容由旧代码产出。**
      `#rdTocList` / `#rdThemes` 的 HTML 由旧代码生成（含 esc() 过的书名），
      原样喂给 v-html 即可 —— 与 discover 页的 #statbar / #confirmBox 同一手法。
      好处：旧代码里的 `$$("a[data-i]", box)` 之类查询照样能查到自己写的节点。
   ========================================================================== */

/** Vue 是不是接管了阅读器外壳（容器在 = Vue 管，容器不在 = 旧实现顶上）。
 *  ⚠ 阅读器外壳是**三个**容器，不是一个 —— 判定要三个都查。
 *     踩过：这里一开始写的是 `[data-vue-reader]`（一个不存在的选择器），
 *     于是永远返回 false，旧代码继续自己写 DOM，Vue 那三个容器则是空的
 *     —— 表现成"Vue 一个节点都没渲进去"。对称地，只要**任一个**在，
 *     就说明这块交给 Vue 了（三个容器是同一次迁移加的，不会只来一个）。 */
const RD_SHELL_SEL = "[data-vue-rdtop],[data-vue-rdpanels],[data-vue-rdbottom]";
function vueOwnsReaderShell() {
  return !!document.querySelector(RD_SHELL_SEL);
}

let _rdApply = null;

/** Vue 侧挂载后调它注册同步回调；立刻来一发，把当前状态交出去。 */
export function attachReader(apply) {
  _rdApply = apply;
  syncReader();
}

export function detachReader() {
  _rdApply = null;
}

/** 把外壳需要的全部状态打成一份快照推给 Vue。
 *
 *  ⚠⚠ 目录（tocHTML）**绝不能**放进这份快照。它由 renderToc() 单独推 ——
 *     因为它是几百上千条 `<a>` 拼出来的大字符串（大书几 MB），而
 *     syncReader() 走的是**每次翻页**都要跑的高频路径。曾经这里带着
 *     `tocHTML`，结果翻一页就得把整份目录重新过一遍 Vue 响应式 ——
 *     这就是线上反馈「阅读器有点卡」的根因（跟几个人访问无关，是纯单机开销）。
 *     谁把它加回来，翻页就会立刻变慢；tools/test_reader_ui.py 的
 *     test_perf 里有一条断言专门盯这个（数 syncReader 的调用次数）。
 *
 *  ⚠ 另外：一次事件里要改多个字段时，必须走 setReaderFields({...})
 *     批量推**一次**，不要连调多次 setReaderField（那是"翻一页推三遍全量"）。 */
function syncReader() {
  if (!_rdApply) return;
  _rdSyncCount++;                    // 诊断计数（见 rdSyncCount()），纯读、无副作用
  _rdApply({
    open: RD.open,
    title: RD.title,
    sub: _rdSub,
    theme: RD.theme,
    modes: { mode: RD.mode },
    fs: RD.fs, lh: RD.lh, ff: RD.ff, w: RD.w,
    themesHTML: _rdThemesHTML,
    chap: _rdChap, pct: _rdPct,
    tocOpen: !!_rdTocOpen, setOpen: !!_rdSetOpen,
    progress: _rdProgress,
  });
}

/* syncReader 被调用的累计次数。
   为什么要暴露它：翻页的"卡"本质是**每次翻页推了几份快照**，
   这是个行为量、与环境负载无关，比测耗时稳得多。测试用它做根因级断言：
   翻一页 syncReader 只该 +1。回归（有人把字段拆成多次推、或把
   tocHTML 重新塞回快照）会立刻体现成 +3 或耗时暴涨。 */
let _rdSyncCount = 0;
/** 读累计同步次数（诊断用；不支持重置，测试取差值即可）。 */
export function rdSyncCount() { return _rdSyncCount; }

/* 影子状态：Vue 在时写这里 + syncReader()，不在时写 DOM。
   为什么要影子而不是直接读 DOM：Vue 在时 DOM 是 Vue 的产物，
   此刻读 DOM 会读到"上一帧的"值（Vue 是异步更新），
   于是连续两次 set 之间会丢状态。 */
let _rdSub = "—";
let _rdChap = "—";
let _rdPct = "0%";
let _rdProgress = 0;
let _rdTocOpen = false;
let _rdSetOpen = false;

/* 「刚刚那一下是拖拽，不是点击」的时间戳（毫秒）。
   为什么需要它：拖拽翻页在 pointerup 里就翻完了，但浏览器紧接着还会
   在同一个位置补一个 click —— 那个 click 会命中 `.rd-zone` 再翻一次，
   就成了"滑一页翻两页"。所以拖拽结束时记下时间，click 处理器看到
   "刚刚（600ms 内）才拖过"就直接让过去。
   ⚠ 用时间戳而不是布尔标记：布尔需要"用完置回 false"，而"什么时候
   置回"很难做对 —— 浏览器可能不补 click（pointercancel / 指针移出窗口），
   标记就永久为真，把**用户之后每一次正经点击**都吞掉（"点了没反应"）。
   时间戳没有复位动作，到点自然失效，不会卡死。 */
let _sawDragAt = 0;
/** 当前时间（毫秒）。单独包一层：方便在测试里改时钟，也免得散落 Date.now()。 */
const now = () => Date.now();

/** 批量写多个字段 —— **一次 syncReader()**，而不是每个字段各推一次。
 *
 *  存在的唯一理由就是性能：`syncReader()` 推的是**整份外壳快照**
 *  （open/title/theme/fs/lh/... 一整套）。翻页这种高频路径上，
 *  每多推一次就是一次不必要的全量 diff —— 旧写法在 `updateBar()` 里
 *  连推三次（chap/pct/progress），就是线上「阅读器有点卡」的直接来源。
 *  见 `updateBar()` 的注释。
 *
 *  ⚠ 注意：快照里**已经不含 `tocHTML`**（目录单独推，见 syncReader 的注释），
 *    所以单次 sync 的成本已经不高；但"少推两次"依然是实打实的收益，
 *    而且这条纪律能防止将来有人再往快照里加字段时又退化成多次推。
 */
function setReaderFields(patch) {
  for (const [field, val] of Object.entries(patch)) {
    if (field === "sub") _rdSub = val;
    else if (field === "chap") _rdChap = val;
    else if (field === "pct") _rdPct = val;
    else if (field === "progress") _rdProgress = val;
    else if (field === "tocOpen") _rdTocOpen = !!val;
    else if (field === "setOpen") _rdSetOpen = !!val;
  }
  if (vueOwnsReaderShell()) { syncReader(); return; }
  for (const [field, val] of Object.entries(patch)) writeReaderFieldDom(field, val);
}

/** 单个字段写入。语义等价于「设一个值然后刷新」，保留给一次性调用点用。 */
function setReaderField(field, val) {
  setReaderFields({ [field]: val });
}

/** 把单个字段写进旧实现的 DOM（Vue 不在时走这条路）。 */
function writeReaderFieldDom(field, val) {
  const el = field === "sub" ? $("#rdSub")
    : field === "chap" ? $("#rdChap")
    : field === "pct" ? $("#rdPct")
    : field === "progress" ? $("#rdProg")
    : field === "tocOpen" ? $("#rdToc")
    : $("#rdSet");
  if (!el) return;
  if (field === "sub" || field === "chap" || field === "pct") el.textContent = val;
  else if (field === "progress") el.style.width = (val * 100) + "%";
  else el.classList.toggle("on", !!val);
}

/** 色卡那一排的 HTML（内容固定，挂载时算一次）。 */
let _rdThemesHTML = "";

/** 目录列表：单独一个入口，避免每次翻页都重传几百条。 */
let _rdTocHTML = "";

/* 上一次真正推给 Vue 的目录 HTML。用来做**去重**：
   markToc() 在每次换章时都会重拼一遍 box.innerHTML（就为了挪一个
   `.on` 高亮类）然后 setTocHTML() 推过去。而目录一旦加载完，
   条目数量是不变的 —— 变的只是某个 `<a>` 上的 class。
   大目录（几千条）每次换章都整段重推，就是白搬几百 KB。
   只加高亮、不改结构时，字符串其实**完全相同**，直接跳过即可。
   ⚠ 不能用 `_rdTocHTML` 做判据 —— 那个一直被赋新值；这里要的是
   "上次真的送出去的是什么"。 */
let _rdTocHTMLSent = null;

function setTocHTML(html) {
  _rdTocHTML = html;
  // 内容一字不差就不要再推一遍（换章重推整份目录的主要浪费就在这里）。
  // 注意首次（_rdTocHTMLSent=null）必须推，否则目录永远不显示。
  if (_rdApply && html !== _rdTocHTMLSent) {
    _rdTocHTMLSent = html;
    _rdApply({ tocHTML: html });
  }
  if (vueOwnsReaderShell()) return;
  const box = $("#rdTocList");
  if (box) box.innerHTML = html;
}

/** 主题色卡那一排按钮的**选中态**。
 *
 *  ⚠ 这里必须**重新生成整段 HTML**，不能只推一个 `theme` 让 Vue 去 toggle。
 *     踩过：一开始 `setThemes()` 只做 `_rdApply({theme})`，注释写着
 *     "由 Vue 打 .on" —— 但这排按钮是 **v-html** 喂进去的，
 *     Vue 根本不参与它内部节点的 patch，`theme` 传过去也没人用。
 *     现象：切主题后背景变了、色卡高亮却没动。
 *     现在改成调 `renderThemeSwatches()`（按当前 RD.theme 重拼字符串），
 *     两条路径（Vue / 非 Vue）行为一致。 */
function setThemes() {
  renderThemeSwatches();
}

/** 设置面板里那些"分段选择器"的选中态（字号/行距/字体/栏宽/翻页方式）。 */
function setSegs() {
  if (_rdApply) _rdApply({ fs: RD.fs, lh: RD.lh, ff: RD.ff, w: RD.w, modes: { mode: RD.mode } });
  if (vueOwnsReaderShell()) return;
  const fsV = $("#rdFsV"); if (fsV) fsV.textContent = RD.fs + "px";
  $$("#rdLhRow button").forEach(b => b.classList.toggle("on", +b.dataset.lh === +RD.lh));
  $$("#rdFfRow button").forEach(b => b.classList.toggle("on", b.dataset.ff === RD.ff));
  $$("#rdWRow button").forEach(b => b.classList.toggle("on", +b.dataset.w === +RD.w));
  $$("#rdModeRow button").forEach(b => b.classList.toggle("on", b.dataset.mode === RD.mode));
}

/* —— 交互回传：Vue 里的按钮点下去，走**同一条**旧代码路径 ——
   不复制逻辑，只转发调用。这样两边行为永远一致，也省得写两遍测试。 */

/** 设置面板里的一次性选项（字号 ±1 / 行距 / 字体 / 栏宽 / 翻页方式）。 */
export function rdSetOpt(kind, val) {
  if (kind === "fs") { RD.fs = clamp(RD.fs + (+val), 13, 32); applyPrefs(); reflow(); }
  else if (kind === "lh") { RD.lh = +val; applyPrefs(); reflow(); }
  else if (kind === "ff") { RD.ff = val; applyPrefs(); reflow(); }
  else if (kind === "w") { RD.w = +val; applyPrefs(); reflow(); }
  else if (kind === "mode") {
    if (RD.mode === val) return;
    RD.mode = val;
    applyPrefs();
    if (lastChapterHTML) {
      const d = parseChapterHTML(lastChapterHTML);
      destroyFlip();
      if (RD.mode === "scroll") {
        setStageHTML(lastChapterHTML); RD.pages = [];
        requestAnimationFrame(updateScrollProgress);
      } else buildPaged(lastChapterHTML, d.title);
    }
  }
}

export function rdSetTheme(id) { RD.theme = id; applyPrefs(); }

/** 开合两个侧边面板（互斥：开目录就关设置，反之亦然）。 */
export function rdTogglePanel(which) {
  if (which === "toc") setReaderFields({ setOpen: false, tocOpen: !_rdTocOpen });
  else setReaderFields({ tocOpen: false, setOpen: !_rdSetOpen });
}

export function rdClosePanels() {
  setReaderFields({ tocOpen: false, setOpen: false });
}

/** 目录里点某一章。 */
export function rdGoChapter(i) {
  goChapter(+i);
  if (window.innerWidth < 900) setReaderField("tocOpen", false);
}

/** 目录搜索框输入 → 过滤。旧代码里这段逻辑内联在 mountReaderUI 的
 *  事件监听里，这里提出来复用，两处都调它。 */
export function rdFilterToc(q) {
  const s = (q || "").trim();
  if (!s) { renderToc(tocAll, tocCur); return; }
  const hits = tocAll.filter(c => (c.title || "").includes(s));
  setTocHTML(hits.length
    ? hits.slice(0, 300).map(c =>
        `<a href="#" data-i="${c.index}"><span class="dotread"></span>` +
        `<span class="tx">${esc(c.title)}</span></a>`).join("")
    : `<div class="lbl">没有匹配的章节</div>`);
}

/** 阅读器顶栏 / 底栏那几个按钮 —— 全部转回旧代码的实现。 */
export function rdBack() { closeReader(); }
export function rdExport() {
  if (!RD.bid) return;
  bus.emit("reader:export", { library_id: RD.bid, title: RD.title, author: RD.author });
}
export function rdCache() {
  if (!RD.bid) return;
  bus.emit("reader:cache", { id: RD.bid, title: RD.title });
}
export function rdPrevChapter() { goChapter(RD.index - 1); }
export function rdNextChapter() { goChapter(RD.index + 1); }

/** 只读探针：给真机测试对账用（口径与渲染同源）。 */
export function readerExpect() {
  return {
    open: RD.open,
    theme: RD.theme,
    mode: RD.mode,
    fs: RD.fs,
    lh: RD.lh,
    ff: RD.ff,
    w: RD.w,
    index: RD.index,
    total: RD.total,
    chapters: tocAll.length,
    themes: RD_THEMES.length,
    vueShell: vueOwnsReaderShell(),
  };
}

window.__lumeiLegacy = Object.assign(window.__lumeiLegacy || {}, {
  attachReader, detachReader,
  rdSetOpt, rdSetTheme, rdTogglePanel, rdClosePanels, rdGoChapter, rdFilterToc,
  rdBack, rdExport, rdCache, rdPrevChapter, rdNextChapter,
  readerExpect,
  // 只读诊断探针（同 discover.js 的 __ndState 约定）：
  // 排障时在 Console 敲 `__lumeiLegacy.rdSyncCount()` 能看到
  // syncReader 被推了多少次。翻一页只该 +1 —— 如果是 +3，
  // 说明有人把字段拆成多次推、又或者把 tocHTML 塞回了快照。
  rdSyncCount,
});
