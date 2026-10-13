/* ==========================================================================
   发现（搜索 + 结果）
   ========================================================================== */

import { $, $$, esc, api, toast, PRE, bus, debounce } from "./util.js";
import { stagger } from "./motion.js";
import { artHTML } from "./art.js";

export const M = {
  books: [], flat: [], byUrl: new Map(), stats: {},
  onlyOk: PRE.get("onlyOk", true),
  srcFilter: new Set(),
  sources: [],
  searching: false, ctrl: null,
  confirmed: "", confirmData: null,
  fuzzy: false,
  steps: [],            // 「联网发现」的实时步骤
};

/* 只读排障探针：线上出问题时在 Console 敲 `__ndState()` 就能看到搜索状态机。
   刻意**只读**（返回快照，不暴露 M 本体），避免误改。
   回归测试 tools/test_concurrency.py 也靠它断言「连点两次搜索」后的状态。 */
try {
  Object.defineProperty(window, "__ndState", {
    value: () => ({
      searching: !!M.searching,
      hasCtrl: !!M.ctrl,
      confirmed: M.confirmed,
      books: M.flat.length,
      steps: M.steps.length,
    }),
    writable: false, configurable: true,
  });
} catch { /* 非浏览器环境（单测）忽略 */ }

/* ---------- 来源 ---------- */
export async function loadSources() {
  try {
    M.sources = await api.get("/api/sources");
    const wrap = $("#srcChips");
    wrap.innerHTML = M.sources.map(s =>
      `<button class="chip" data-src="${esc(s.name)}">${esc(s.display)}</button>`).join("");
    $$(".chip", wrap).forEach(c => c.onclick = () => {
      const n = c.dataset.src;
      if (M.srcFilter.has(n)) M.srcFilter.delete(n); else M.srcFilter.add(n);
      c.classList.toggle("on");
      if (M.confirmed) runSearch(M.confirmed, false);
    });
  } catch {}
}

/* ---------- 书名确认 ---------- */
const kickConfirm = debounce(async text => {
  if (!text || text.trim().length < 2) { $("#confirmBox").innerHTML = ""; return; }
  try {
    const d = await api.post("/api/confirm", { text });
    M.confirmData = d;
    if (!d.suspect) { $("#confirmBox").innerHTML = ""; return; }
    renderConfirm(d);
  } catch { $("#confirmBox").innerHTML = ""; }
}, 320);

function renderConfirm(d) {
  const chips = (d.suggestions || []).map(s =>
    `<button class="chip" data-t="${esc(s.title)}">${esc(s.title)}<span class="r">${esc(s.reason)}</span></button>`).join("");
  // ⚠ 这里以前整块写行内 style —— 主题层够不到（同 confirmBox 的老毛病）。
  //   改成 .cfs 类组件；"🤔" emoji 也去掉了：这个框是**让用户做决定**的，
  //   不需要情绪插画抢戏。
  $("#confirmBox").innerHTML = `
    <div class="cfs">
      <div class="cfs-h">
        <div class="cfs-b">
          <div class="cfs-t">${d.changed ? "我把它理成了" : "你找的是不是"}《${esc(d.keyword)}》？</div>
          <div class="cfs-s">${d.changed ? `原始输入：${esc(d.raw)}` : "先确认一下，省得搜错"}</div>
          ${chips ? `<div class="cfs-chips">${chips}</div>` : ""}
        </div>
      </div>
      <div class="cfs-a">
        <button class="btn ghost sm" id="cfCancel">再改改</button>
        <button class="btn primary sm" id="cfGo">就搜《${esc(d.keyword)}》</button>
      </div>
    </div>`;
  $("#cfGo").onclick = () => { $("#confirmBox").innerHTML = ""; runSearch(d.keyword, true); };
  $("#cfCancel").onclick = () => { $("#confirmBox").innerHTML = ""; $("#q").focus(); };
  $$("#confirmBox .chip").forEach(c => c.onclick = () => {
    $("#q").value = c.dataset.t;
    $("#confirmBox").innerHTML = "";
    runSearch(c.dataset.t, true);
  });
}

function submitSearch() {
  const raw = $("#q").value.trim();
  if (!raw) { toast("先说一本书名吧", "err"); return; }
  // 粘进来的是地址就别去搜了 —— 直接打开看（用户在百度上已经找到页面了）
  if (isUrl(raw)) { runFetchUrl(raw); return; }
  const kw = (M.confirmData && M.confirmData.raw === raw) ? M.confirmData.keyword : raw;
  if (M.confirmData && M.confirmData.raw === raw && M.confirmData.suspect) { renderConfirm(M.confirmData); return; }
  runSearch(kw, true);
}

/* ---------- 搜索 ---------- */
export async function runSearch(kw, toastIt) {
  if (M.searching) { try { M.ctrl.abort(); } catch {} }
  M.searching = true; M.confirmed = kw;
  M.books = []; M.flat = []; M.byUrl.clear(); M.fuzzy = false;
  M.steps = []; resetNetLive();

  $("#confirmBox").innerHTML = "";
  $("#filters").classList.remove("hidden");
  $("#homeEmpty").classList.add("hidden");
  renderSkeleton();

  const n = M.srcFilter.size || M.sources.length;
  $("#statbar").innerHTML = `正在${n ? ` ${n} 个来源` : "全部来源"}里找《<b>${esc(kw)}</b>》…
    <span class="sep"></span>先搜后验，稍等几秒`;

  const ctrl = new AbortController(); M.ctrl = ctrl;
  let last = 0;
  try {
    const url = "/api/search?kw=" + encodeURIComponent(kw)
      + (M.srcFilter.size ? "&sources=" + encodeURIComponent([...M.srcFilter].join(",")) : "");
    const resp = await api.stream(url, { signal: ctrl.signal });
    if (!resp.ok || !resp.body) throw new Error("HTTP " + resp.status);
    const reader = resp.body.getReader(), dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split("\n"); buf = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        let ev; try { ev = JSON.parse(line); } catch { continue; }
        handleEvent(ev);
        const now = Date.now();
        if (ev.type !== "done" && now - last > 400) { last = now; renderResults(); }
      }
    }
  } catch (e) {
    if (e.name !== "AbortError") toast("搜索出错：" + e.message, "err");
  } finally {
    // ⚠ 这里必须确认「我还是当前那一次搜索」才能收尾。
    //
    // 实测踩到的竞态：用户连点两次搜索（A → B）。
    //   · B 进来时 abort 掉 A 的 fetch，A 的 reader.read() 抛 AbortError；
    //   · A 的 finally **无条件**把 M.searching 置 false —— 可 B 还在跑。
    //   · 于是 M.searching=false，下一次点击不再 abort，两个流同时往 #results 写，
    //     互相覆盖；A 的空 renderResults() 还会把 B 已经流式渲染出的结果擦掉。
    // 只在「M.ctrl 还是我自己」时收尾，被顶掉的旧请求直接静默退出。
    if (M.ctrl !== ctrl) return;
    M.searching = false;
    finishNetLive();
    renderResults();
  }
}

function handleEvent(ev) {
  if (ev.type === "item" || ev.type === "verified") {
    const d = ev.data;
    M.byUrl.set(d.source + "|" + d.url, d);
    const i = M.flat.findIndex(x => x.source === d.source && x.url === d.url);
    if (i >= 0) M.flat[i] = d; else M.flat.push(d);
  } else if (ev.type === "step") {
    // 「联网发现」在工作线程里一步步往外推，直接画出来 ——
    // 用户看得见「搜索 → 拿到网站 → 去爬取 → 入库」真的在发生。
    M.steps.push(ev);
    renderNetLive();
  } else if (ev.type === "done") {
    M.stats = ev.stats || {};
    M.fuzzy = !!ev.fuzzy;
    M.discovered = ev.discovered || 0;
    M.books = (ev.books || []).map(b => {
      b.sources = (b.sources || []).map(s => M.byUrl.get(s.source + "|" + s.url) || s);
      return b;
    });
    if (!M.books.length && M.flat.length) M.books = fallbackGroup(M.flat);
    const disc = M.discovered
      ? `<span class="sep"></span><span style="color:var(--a-1)">联网找回 <b>${M.discovered}</b> 个来源</span>`
      : "";
    $("#statbar").innerHTML =
      `<span>看遍 <b>${M.stats.sources_queried || 0}</b> 个来源</span><span class="sep"></span>` +
      `<span>原始 <b>${M.stats.raw || 0}</b> 条</span><span class="sep"></span>` +
      `<span>滤掉噪音 <b>${M.stats.filtered || 0}</b> 条</span><span class="sep"></span>` +
      `<span>并成 <b>${M.books.length}</b> 本</span><span class="sep"></span>` +
      `<span style="color:var(--ok)">正文验证通过 <b>${M.stats.readable || 0}</b></span>` +
      disc +
      `<span class="sep"></span><span>耗时 <b>${((M.stats.ms || 0) / 1000).toFixed(1)}s</b></span>`;
  } else if (ev.type === "error") {
    toast("搜索失败：" + ev.msg, "err");
  }
}

/* ---------- 联网发现实况面板 ---------- */
function resetNetLive() {
  const box = $("#netLive");
  if (!box) return;
  box.classList.add("hidden");
  box.classList.remove("done");
  box.classList.remove("folded");
  $("#netLiveSteps").innerHTML = "";
  $("#netLiveTitle").textContent = "正在联网找书…";
  $("#netLiveSub").textContent = "";
  $("#netLiveToggle").textContent = "收起";
}

function renderNetLive() {
  const box = $("#netLive");
  if (!box || !M.steps.length) return;
  box.classList.remove("hidden");

  const last = M.steps[M.steps.length - 1];
  $("#netLiveTitle").textContent = last.title;
  $("#netLiveSub").textContent = last.detail || "";

  const ul = $("#netLiveSteps");
  const hitWords = /发现可用来源|来源库命中|来源库已更新|收录/;
  ul.innerHTML = M.steps.map(s => {
    const cls = s.ok === false ? "bad" : (hitWords.test(s.title) ? "hit" : "");
    return `<li class="${cls}"><span class="d"></span>` +
      `<span class="t">${esc(s.title)}</span>` +
      (s.detail ? `<span class="x">${esc(s.detail)}</span>` : "") + `</li>`;
  }).join("");
  ul.scrollTop = ul.scrollHeight;
}

function finishNetLive() {
  const box = $("#netLive");
  if (!box || !M.steps.length) return;
  renderNetLive();
  box.classList.add("done");

  const fromLib = M.steps.some(s => /来源库命中/.test(s.title));
  const n = M.discovered || 0;
  if (fromLib) {
    $("#netLiveTitle").textContent = `来源库里已经有 ${n} 个来源`;
    $("#netLiveSub").textContent = "不用再联网搜了";
  } else if (n) {
    $("#netLiveTitle").textContent = `联网找回 ${n} 个来源`;
    $("#netLiveSub").textContent = "已记进来源库，下次搜这本会快很多";
    box.classList.add("folded");   // 步骤收起，别抢搜索结果的位置
    $("#netLiveToggle").textContent = "展开";
  } else {
    $("#netLiveTitle").textContent = "联网没找到能用的来源";
    $("#netLiveSub").textContent = "";
  }
}

function fallbackGroup(flat) {
  const m = new Map();
  flat.forEach(r => {
    const k = (r.title || "").trim();
    if (!m.has(k)) m.set(k, {
      key: k, title: k, author: r.author, intro: r.intro,
      hue: (k.length * 37) % 360, sources: [], source_count: 0,      available_count: 0, readable_count: 0, chapter_count: 0, score: r.score,
    });
    const b = m.get(k); b.sources.push(r); b.source_count++;
    if (r.available) b.available_count++;
    if (r.readable) b.readable_count++;
    b.chapter_count = Math.max(b.chapter_count, r.chapter_count || 0);
  });
  return [...m.values()];
}

function renderSkeleton() {
  // 骨架屏只**画结构**，不放插画 —— 它的工作是在首屏抢先占位，
  // 插一张 480px 的图反而会让"正在搜"变慢（图还没到就先空了）。
  // 插画留给"已经在等了、需要一点安慰"的场景（见 reader 的 setStageBusy）。
  $("#results").innerHTML = Array.from({ length: 6 }).map(() => `
    <div class="skl"><div class="b cv"></div><div class="col">
      <div class="b ln" style="width:52%"></div>
      <div class="b ln" style="width:32%;height:10px"></div>
      <div class="b ln" style="width:92%;height:10px"></div>
      <div class="b ln" style="width:70%;height:10px"></div>
    </div></div>`).join("");
}

/* ---------- 渲染 ---------- */
/**
 * 纯 CSS 生成的封面。
 *
 * ⚠ 这是**兜底**，不是主方案：真正抓到的封面图（`coverHTML(coverUrl)`）
 *   优先，拿不到才用这个。为什么留着：搜索阶段只回传书名/作者，
 *   封面要等探测打开书页才拿得到 —— 而探测是有预算的（只探前 N 个），
 *   排在后头的书永远等不到图。用一个由书名哈希决定的渐变色块兜住，
 *   列表就不会出现「有的有图有的没有」那种参差感。
 *   色相来自 aggregate.hue_of()，同一本书永远是同一个颜色。
 *
 * 调用方式两种：
 *   coverHTML(hue)              —— 只有色相（老调用点，仍兼容）
 *   coverHTML(coverUrl, title, author) —— 有真封面
 */
export function coverHTML(a, title, author, lg) {
  // 兼容老签名：第一个参数是数字就是色相
  if (typeof a === "number") return gradientCover(a, title, author, lg);

  const url = (a || "").trim();
  if (!url) return gradientCover((title || "").length * 37 % 360, title, author, lg);
  // ⚠ 封面必须走代理回传，不能直接把外站 URL 塞进 <img src>：
  //   ① 来源站大多有 Referer 防盗链，直连浏览器必然 403（图裂）
  //   ② 会让用户的浏览器直连外站，暴露 IP / 访问记录
  //   /api/cover 由服务端带正确 Referer 去取并缓存，前端只认这个。
  const src = `/api/cover?u=${encodeURIComponent(url)}`;
  return `<div class="cover${lg ? " lg" : ""} has-img">
    <img src="${esc(src)}" alt="" loading="lazy" decoding="async"
         onerror="this.parentNode.classList.remove('has-img');this.remove()">
    <div class="t">${esc((title || "?").slice(0, 7))}</div>
    <div class="a">${esc((author || "佚名").slice(0, 6))}</div>
  </div>`;
}

function gradientCover(hue, title, author, lg) {
  const h = ((hue % 360) + 360) % 360;
  const c1 = `hsl(${h} 58% 50%)`, c2 = `hsl(${(h + 38) % 360} 54% 34%)`;
  return `<div class="cover${lg ? " lg" : ""}" style="background:linear-gradient(150deg,${c1},${c2})">
    <div class="t">${esc((title || "?").slice(0, 7))}</div>
    <div class="a">${esc((author || "佚名").slice(0, 6))}</div>
  </div>`;
}

function srcPill(s) {
  if (s.readable) return `<span class="pill ok">✓ 可读 · ${s.chapter_count} 章</span>`;
  // 「抽过、但抓不到正文」—— 塔读这类付费站就是这个形状
  if (s.sample_ok === false) return `<span class="pill warn">目录在，正文抓不到</span>`;
  // 目录能打开但**没抽过正文**：不能说"可读"。
  // 没验证就不许给绿标 —— 否则点进去一个字都没有，就是"显示能下载最后是假的"。
  if (s.available) return `<span class="pill mute">目录 ${s.chapter_count} 章 · 正文未验证</span>`;
  if (s.available === false) return `<span class="pill bad">✕ ${esc(s.note || "打不开")}</span>`;
  return `<span class="pill mute">未验证</span>`;
}

export function visibleBooks() {
  return M.onlyOk ? M.books.filter(b => (b.sources || []).some(s => s.readable || s.available)) : M.books;
}

export function renderResults() {
  const list = visibleBooks();
  const box = $("#results");
  if (!list.length) {
    if (M.searching) { box.innerHTML = ""; return; }
    // 两种"没结果"是**不同的事**，不能给同一句话：
    //   ① 搜到了，但一本都没通过验证 —— 用户需要的是"帮我放宽条件"
    //   ② 一本都没搜到 —— 用户需要的是"换个词再试"
    // 所以配的图也不同：① 用犯困（有点泄气但还有戏），② 用独坐（确实没找着）。
    box.innerHTML = M.books.length
      ? `<div class="empty">${artHTML("error_sad", "m")}
           <h3>搜到 ${M.books.length} 本，但都没通过验证</h3>
           <p>关掉上面的「只看能读的」看看原始结果，或者点开卡片看每个来源的状态 ——
              有的站点目录能开、正文抓不到，卡片上会写清楚。</p></div>`
      : `<div class="empty">${artHTML("empty_lonely", "m")}
           <h3>没找到能读的</h3>
           <p>换个书名试试。如果记得作者，把作者名一起搜会准很多。</p></div>`;
    return;
  }
  // 提示条三选一：按作者找到的 > 模糊沾边的 > 都不挂。
  // 两条同时出现会自相矛盾（一条说"找到了"、一条说"没找到"）。
  const byAuthor = !M.fuzzy && list.some(b =>
    (b.sources || []).some(s => s.by_author));
  box.innerHTML = (byAuthor ? authorBanner()
    : (M.fuzzy ? fuzzyBanner() : "")) + list.map((b, i) => bookHTML(b, i)).join("");
  bindBooks();
  // 错峰由动效层统一编排（motion.css 读 --mo-i）。
  // 不在这里写 animation-delay —— 上限、步长、曲线都是动效层的职责，
  // 分散到各业务文件里就会「有的列表 40ms、有的 35ms」，节奏不齐。
  stagger(box, ".book");
}

function fuzzyBanner() {
  return `<div class="fuzzy">
    <span class="fi">🤔</span>
    <div class="ft"><b>没找到确切的《${esc(M.confirmed || "")}》</b>
      <span>下面这 ${M.books.length} 本是「沾边」结果 —— 名字里带这几个字，但不一定是你要的那本。
      补上作者名一起搜会准很多。</span></div>
  </div>`;
}

/* 「按作者找到了 N 本」的提示条。
   ⚠ 为什么需要：作者搜索的结果**书名里没有关键词** —— 用户搜「顾漫」看到
   《微微一笑很倾城》《何以笙箫默》，如果没有任何说明，第一反应是"搜错了/搜索坏了"
   （这两个词面上一看毫无关系）。必须明说"这是按作者捞的"，用户才知道结果是对的。
   和 fuzzy 提示条互斥：fuzzy 是"没找到、这是沾边的"，这里是"找到了、是按作者找的"，
   两种情况说的是相反的事，同时出现只会让人更糊涂。 */
function authorBanner() {
  const n = M.books.length;
  return `<div class="fuzzy auth">
    <span class="fi">✍️</span>
    <div class="ft"><b>按作者找到了 ${n} 本</b>
      <span>「${esc(M.confirmed || "")}」是作者名，下面是 ta 的作品 ——
      书名里当然不含作者名，这是对的。</span></div>
  </div>`;
}

/* 书籍的**稳定身份键** —— 与后端分组口径一致（title + author）。
   ⚠ 不要用下标做身份：下标只在渲染那一瞬有效。见 bookHTML 里的长注释。 */
function groupKey(b) {
  return `${(b.title || "").trim()}\u0000${(b.author || "").trim()}`;
}

/* 从卡片自己的 data-gk 反查书；反查失败才退回下标（兼容旧 DOM）。
   ⚠ 这个"先身份、再下标"的顺序很重要：只要还拿得到 gk 且它在当前列表里，
   就一定返回**当初渲染这张卡的那本书**，不会被中途的列表变化带偏。 */
function bookOf(card) {
  const gk = card.dataset.gk;
  if (gk) {
    const hit = visibleBooks().find(x => groupKey(x) === gk);
    if (hit) return hit;
    // gk 不在可见列表里（用户刚关掉「只看能读的」、这本被过滤掉了）——
    // 那就回**全量**列表找，别拿别人的书顶上。
    const any = M.books.find(x => groupKey(x) === gk);
    if (any) return any;
  }
  return visibleBooks()[+card.dataset.i];
}

function bookHTML(b, i) {
  if (!b.sources || !b.sources.length) return "";
  const best = b.sources.find(s => s.readable) || b.sources[0] || {};
  const tags = [];
  // 「抽过、但抽出来是控件页/错误页」要和「没抽过」分开说 ——
  // 两者都是"不可读"，但原因不同，给用户的下一步动作也不同。
  const sampledBad = b.sources.some(s => s.sample_ok === false);
  const sampledGood = b.sources.some(s => s.sample_ok === true);
  if (b.readable_count) tags.push(`<span class="pill ok">${b.readable_count} 个来源可读</span>`);
  else if (sampledBad) tags.push(`<span class="pill warn">目录能开，但正文抓不到</span>`);
  else if (b.available_count)
    tags.push(`<span class="pill mute">${b.available_count} 个来源目录可达 · 正文未验证</span>`);
  else tags.push(`<span class="pill bad">暂无可用来源</span>`);
  if (b.chapter_count) tags.push(`<span class="pill mute">最多 ${b.chapter_count} 章</span>`);
  // 只有**验过且通过**才敢说"正文已验证"。
  // 原来这里看的是 sample_chars，于是塔读那 495 字的控件页也被打了这个绿标。
  if (sampledGood && b.sample_chars) tags.push(`<span class="pill ok">正文已验证</span>`);
  if (b.source_count > 1) tags.push(`<span class="pill mute">${b.source_count} 个站点收录</span>`);

  const rows = b.sources.map(s => `
    <div class="srow">
      <span class="nm">${esc(s.source_display || s.source)}</span>
      ${srcPill(s)}
      <span class="grow"></span>
      <span class="n">${s.probe_ms ? s.probe_ms + "ms" : ""}</span>
      ${s.readable || s.available
        ? `<button class="mini pri" data-act="read" data-u="${esc(s.source)}|${esc(s.url)}">阅读</button>` : ""}
      <button class="mini" data-act="dl" data-u="${esc(s.source)}|${esc(s.url)}">导出</button>
    </div>`).join("");

  const siteNames = [...new Set(b.sources.map(s => s.source_display || s.source).filter(Boolean))];
  const desc = b.intro ? esc(b.intro) : `<span class="no-intro">收录于 ${esc(siteNames.join("、"))}</span>`;

  // ⚠ data-i 之外再挂一份**稳定的身份键**。
  //   为什么：`data-i` 是 `visibleBooks()` 的**下标**，只对"渲染那一刻"的列表成立。
  //   而展示列表是会变的 —— 「只看能读的」开关（`#onlyOk`）、搜索中途每 400ms
  //   的增量重绘、`done` 事件后的重新分组，都会让它变短或重排。
  //   只要出现「DOM 还是旧的、列表已经变了」的窗口，`visibleBooks()[+data-i]`
  //   就会**指向另一本书** —— 表现是"点阅读搜出来的不是这本"。
  //   这里的 key 用书自己的 title+author 组合（`group_key()` 同款口径），
  //   渲染和反查两边都从它走，下标错位就伤不到正确性。
  const gk = groupKey(b);
  // 展示用书名：后端已剥掉「[玄幻]」这类站点分类前缀（display_title），
  // 没有该字段时退回原书名 —— 不能因为后端没升级就把标题显示成空。
  const dtitle = b.display_title || b.title;
  return `<div class="book" data-i="${i}" data-gk="${esc(gk)}">
    <div class="head">
      ${coverHTML(b.cover || b.hue, dtitle, b.author)}
      <div class="meta">
        <h3>${esc(dtitle)}</h3>
        <div class="by">${esc(b.author || "作者未知")}</div>
        <div class="desc">${desc}</div>
        <div class="tags">${tags.join("")}</div>
      </div>
    </div>
    <div class="acts">
      <button class="btn primary sm" data-act="read" data-u="${esc(best.source || "")}|${esc(best.url || "")}">开始阅读</button>
      <button class="btn sm" data-act="toggle">来源 ${b.source_count} ▾</button>
      <button class="btn sm icon" data-act="dl" data-u="${esc(best.source || "")}|${esc(best.url || "")}" title="导出文件">↧</button>
    </div>
    <div class="sources">${rows}</div>
  </div>`;
}

function bindBooks() {
  $$("#results .book").forEach(card => {
    $$("[data-act]", card).forEach(btn => {
      btn.onclick = async e => {
        e.stopPropagation();
        const act = btn.dataset.act;
        if (act === "toggle") {
          card.classList.toggle("open");
          const n = $$(".srow", card).length;
          btn.textContent = card.classList.contains("open") ? "收起 ▴" : `来源 ${n} ▾`;
          return;
        }
        const [source, url] = (btn.dataset.u || "").split("|");
        const b = bookOf(card);
        if (!b) return;
        // ⚠ 这里**不能**再用 `|| b.sources[0]` 兜底 —— 见上面的 handleEvent：
        //   `sources` 数组里的条目是**流式期间就挂上去的**，`done` 之后会用
        //   `M.byUrl` 的完整版本替换。没对上就是两次卡片渲染之间列表变了，
        //   "拿别的来源顶上"比"什么都不做"更坏（用户点 A 站，实际开 B 站）。
        const src = b.sources.find(s => s.source === source && s.url === url);
        if (!src) return;
        if (act === "read") bus.emit("book:read", src);
        if (act === "dl") bus.emit("book:export", { src, book: b });
      };
    });
  });
}

/* ---------- 绑定 ---------- */
export function mountDiscover() {
  $("#onlyOk").checked = M.onlyOk;
  $("#onlyOk").onchange = e => { M.onlyOk = e.target.checked; PRE.set("onlyOk", M.onlyOk); renderResults(); };
  $("#btnSearch").onclick = submitSearch;
  $("#q").addEventListener("keydown", e => { if (e.key === "Enter") submitSearch(); });
  $("#q").addEventListener("input", e => {
    const v = e.target.value.trim();
    hintUrlBox(isUrl(v) ? v : "");
    if (!isUrl(v)) kickConfirm(v);
  });
  const nlToggle = $("#netLiveToggle");
  if (nlToggle) nlToggle.onclick = () => {
    const box = $("#netLive");
    const folded = box.classList.toggle("folded");
    nlToggle.textContent = folded ? "展开" : "收起";
  };
  $("#btnClearSearch").onclick = () => {
    M.books = []; M.flat = []; M.byUrl.clear();
    resetNetLive();
    renderResults();
    $("#statbar").innerHTML = "";
    $("#filters").classList.add("hidden");
    $("#homeEmpty").classList.remove("hidden");
    $("#q").value = "";
    $("#confirmBox").innerHTML = "";
    hintUrlBox("");
    M.confirmed = "";
  };
}

/* --------------------------------------------------------------------------
   粘一个书页地址直接抓
   --------------------------------------------------------------------------
   「我在百度上搜到了这本书的页面，地址在这儿」—— 那就别再让我去搜了，
   直接打开看。走的和联网发现**同一套**通用启发式（`app/webfetch.py`），
   所以「能不能抓、有多少章」的口径完全一致。
   -------------------------------------------------------------------------- */
function isUrl(s) {
  return /^https?:\/\/[^\s]+\.\S{2,}/i.test((s || "").trim());
}

function hintUrlBox(url) {
  const btn = $("#btnSearch");
  if (btn) btn.textContent = url ? "直接抓这个地址" : "开始找书";
  const box = $("#confirmBox");
  if (!box) return;
  if (!url) { if (M.confirmData && !M.confirmData.suspect) box.innerHTML = ""; return; }
  box.innerHTML = `
    <div class="cfs">
      <div class="cfs-h" style="align-items:center">
        <span class="cfs-ic" aria-hidden="true">🔗</span>
        <div class="cfs-b">
          <div class="cfs-t">这是个网址，我会直接打开看</div>
          <div class="cfs-s">
            自己认出目录和正文在哪 —— 不用先搜。抓不到会直说，不会假装能读。
          </div>
        </div>
      </div>
    </div>`;
}

async function runFetchUrl(url) {
  // 正在搜的话先掐掉 —— 两个流程同时往 #results 里写会互相覆盖
  if (M.searching) { try { M.ctrl.abort(); } catch { /* 没在跑就算了 */ } }
  M.searching = true;
  // 真的 AbortController（不是占位对象）—— 这样上层 runSearch 顶掉它时是
  // 真取消，而不是抛 "M.ctrl.abort is not a function" 被 catch 静默吞掉。
  const ctrl = new AbortController();
  M.ctrl = ctrl;
  M.confirmed = "";
  $("#confirmBox").innerHTML = "";
  resetNetLive();
  $("#homeEmpty").classList.add("hidden");
  $("#filters").classList.add("hidden");
  $("#statbar").innerHTML = `<span class="dot"></span>正在打开这个地址…`;
  renderSkeleton();

  let d;
  try {
    d = await api.post("/api/fetch-url", { url }, { signal: ctrl.signal });
  } catch (e) {
    if (M.ctrl !== ctrl) return;          // 已被新流程顶掉，别动界面
    M.searching = false;
    if (e.name === "AbortError") return;  // 自己放弃的，不算错误
    $("#results").innerHTML = "";
    toast("打不开这个地址：" + e.message, "err");
    $("#statbar").innerHTML = `<span style="color:var(--err)">${esc(e.message)}</span>`;
    return;
  }
  if (M.ctrl !== ctrl) return;            // 同上：慢请求回来时已经换人了
  M.searching = false;

  if (!d || !d.ok) {
    $("#results").innerHTML = "";
    $("#homeEmpty").classList.remove("hidden");
    $("#statbar").innerHTML = `<span style="color:var(--err)">${esc((d && d.error) || "这个页面不像小说页")}</span>`;
    return;
  }

  const host = (d.url || "").replace(/^https?:\/\//, "").split("/")[0];
  if (d.kind === "toc") {
    const s = d.sample || {};
    const src = {
      source: "web", source_display: "直接抓取", url: d.url,
      title: d.title || "", author: d.author || "",
      available: true, chapter_count: d.chapters || 0,
      note: `来自 ${host}`,
      sampled: !!s.sampled, sample_ok: s.sampled ? !!s.readable : null,
      sample_chars: s.chars || 0, sample_note: s.note || "",
    };
    M.books = [{
      key: host, title: d.title || url, author: d.author || "", intro: d.intro || "",
      hue: ((d.title || host).length * 37) % 360,
      readable_count: s.readable ? 1 : 0, available_count: 1, source_count: 1,
      chapter_count: d.chapters || 0, score: 0, tight: true,
      sample_chars: s.chars || 0, verified: s.readable,
      sources: [src],
    }];
    M.flat = [src]; M.byUrl = new Map([[d.url, src]]);
    $("#results").classList.remove("hidden");
    renderResults();
    $("#statbar").innerHTML = s.readable
      ? `<span style="color:var(--ok)">认出了目录 · <b>${d.chapters || 0}</b> 章
         <span class="sep"></span>正文抽了 <b>${s.chars || 0}</b> 字，读得到</span>
         <span class="sep"></span>来源 <b>${esc(host)}</b>`
      : `<span style="color:var(--warn)">认出了目录 · <b>${d.chapters || 0}</b> 章
         <span class="sep"></span>但正文抓不到${s.note ? "：" + esc(s.note) : ""}</span>
         <span class="sep"></span>来源 <b>${esc(host)}</b>`;
  } else {
    // 给的是一张正文页：不算「一本书」，直接说清
    $("#results").innerHTML = "";
    $("#homeEmpty").classList.remove("hidden");
    toast(`这个地址是一章正文（${d.chars || 0} 字），不是目录页`, "warn");
    $("#statbar").innerHTML = `<span>这是一张正文页，不是目录页 —— 换成书的目录地址我才能列章</span>`;
  }
}

export function searchFromHash(kw) {
  $("#q").value = kw;
  // 深链里也可能是地址（#search=https://…），同样直接抓
  if (isUrl(kw)) { hintUrlBox(kw); runFetchUrl(kw); return; }
  kickConfirm(kw);
  runSearch(kw, true);
}

/* 迁移桥：Vue 侧点榜单书名要走同一条搜索路径（理由见 util.js 末尾）。
   挂 searchFromHash 而不是 runSearch —— 前者会顺手填好输入框，语义更完整。 */
window.__lumeiLegacy = Object.assign(window.__lumeiLegacy || {}, { searchFromHash });
