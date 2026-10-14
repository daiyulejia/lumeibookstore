/* ==========================================================================
   热门榜单 —— 「不知道读什么」时的入口

   数据来自已适配站点的公开榜单（见 app/ranks.py）。点一本书，
   直接把它当书名丢进现有的搜索流程 —— 复用发现页已经验证过的那套，
   不另开一条"从榜单直接下载"的路径（那条路的可用性没人验证过）。
   ========================================================================== */

import { $, esc, api, toast, PRE, bus } from "./util.js";
import { stagger } from "./motion.js";
import { runSearch } from "./discover.js";

const RK = {
  kinds: [],
  cur: "allvisit",
  cache: new Map(),      // kind -> items（前端也缓存一层，切标签不重复请求）
  loading: false,
  folded: PRE.get("ranksFold", false),
  mounted: false,
  age: null,             // 服务端告知的"这份数据多久前抓的"（秒）
  refreshedAt: 0,        // 本地记录：我们这次刷新拿到的时刻
  onShelf: null,         // 书架书名的归一化集合；null = 还没取过
  shelfPromise: null,    // 取书架的进行中 promise（并发去重）
};

/* 每条榜单配一个色，纯为了视觉区分 —— 不承载任何语义。
   ⚠ 与 frontend/src/components/RanksPanel.vue 的 HUE **必须逐项一致**：
   这里是 Vue 没挂上时的降级实现，同一类榜单在两条路径下颜色不同，
   看起来就像"页面坏了"。加 kind 时两份一起加。 */
const HUE = {
  allvisit: 22, weekvisit: 315, allvote: 350, goodnum: 268,
  size: 200, postdate: 145, lastupdate: 40,
};

/** 归一化书名做比对：去掉空格和常见装饰，避免「《三体》」对不上「三体」。 */
function normTitle(s) {
  return String(s || "")
    .replace(/[《》「」【】\s·・.。、,，:：!！?？'"'"()（）\[\]\-—_~～]/g, "")
    .toLowerCase();
}

/** 取书架书名集合。
 *
 * 为什么不 `import { shelf } from "./shelf.js"`：这个项目的跨模块通信
 * **统一走事件总线**（shelf.js 里明写了「跨模块通信用它，而不是互相 import」），
 * 而且 shelf 和 ranks 都被 main.js 引入，直接互相 import 会成环。
 * 这里只要一份"有哪些书"，直接打接口最干净 —— 不碰 shelf 的内部状态。
 */
function ensureShelf(force) {
  if (!force && RK.onShelf) return Promise.resolve(RK.onShelf);
  if (RK.shelfPromise) return RK.shelfPromise;
  RK.shelfPromise = api.get("/api/library")
    .then(list => {
      const s = new Set();
      for (const b of (Array.isArray(list) ? list : [])) {
        const t = normTitle(b && b.title);
        if (t) s.add(t);
      }
      RK.onShelf = s;
      return s;
    })
    .catch(() => { RK.onShelf = RK.onShelf || new Set(); return RK.onShelf; })
    .finally(() => { RK.shelfPromise = null; });
  return RK.shelfPromise;
}

export function renderRanks() {
  const box = $("#ranksBox");
  if (!box) return;
  if (RK.folded) {
    box.classList.add("folded");
  } else {
    box.classList.remove("folded");
  }
  const fb = $("#ranksFold");
  if (fb) fb.textContent = RK.folded ? "展开" : "收起";
  paintFreshness();
}

/** 「x 分钟前更新」——比假装实时诚实，也让用户知道后台有没有在干活。 */
function paintFreshness() {
  const el = $("#ranksAge");
  if (!el) return;
  if (RK.age == null && !RK.refreshedAt) { el.textContent = ""; return; }
  let secs = RK.age ?? 0;
  // 本地刷新成功后按本地时钟滚动，不用等下一次请求回来
  if (RK.refreshedAt) secs = Math.max(0, (Date.now() - RK.refreshedAt) / 1000);
  el.textContent = secs < 90 ? "刚刚更新"
    : secs < 3600 ? `${Math.round(secs / 60)} 分钟前更新`
    : secs < 86400 ? `${Math.round(secs / 3600)} 小时前更新`
    : `${Math.round(secs / 86400)} 天前更新`;
  el.title = "榜单来自公开榜单页，后台会定时自动刷新";
}

function tabsHTML() {
  return RK.kinds.map(k =>
    `<button class="rk-tab${k.kind === RK.cur ? " on" : ""}" data-kind="${esc(k.kind)}"
       role="tab" aria-selected="${k.kind === RK.cur}">${esc(k.label)}</button>`).join("");
}

function itemHTML(it, i) {
  const hue = HUE[it.kind] ?? 22;
  const rank = i + 1;
  // 前三名给个更醒目的角标 —— 榜单的"前几名"本身就有信息量
  const medal = rank <= 3 ? ` m${rank}` : "";
  const meta = [];
  if (it.author) meta.push(esc(it.author));
  if (it.words) meta.push(esc(it.words));
  if (it.status) meta.push(esc(it.status));
  if (it.updated) meta.push(esc(it.updated));

  // 「已在书架」标记：榜单里最有用的一条附加信息 ——
  // 看到一本眼熟的书，第一反应就是"我是不是已经存过了"。
  const owned = !!RK.onShelf && RK.onShelf.has(normTitle(it.title));
  const go = owned
    ? `<span class="rk-owned" title="这本书已经在你书架里了">✓ 已在书架</span>`
    : `<span class="rk-go">找这本 ›</span>`;

  return `<button class="rk-item${owned ? " owned" : ""}" data-title="${esc(it.title)}" type="button">
    <span class="rk-no${medal}">${rank}</span>
    <span class="rk-ttl" style="--h:${hue}">
      <b>${esc(it.title)}</b>
      <em>${meta.join(" · ") || "&nbsp;"}</em>
    </span>
    <span class="rk-src">${esc(it.source_display || it.source || "")}</span>
    ${go}
  </button>`;
}

function skeleton(n = 6) {
  return Array.from({ length: n }, () =>
    `<div class="rk-item sk"><span class="rk-no"></span>
      <span class="rk-ttl"><b></b><em></em></span></div>`).join("");
}

/**
 * 唯一的「把 HTML 写进榜单列表」入口。
 *
 * 为什么必须收成一个函数：列表有四条写入路径 ——
 * 骨架（首屏等待）、缓存命中、真数据回来了、出错。
 * 之前错峰只在 bindItems 里挂，而 bindItems **只覆盖后三条**，
 * 骨架那条是漏的：首屏会先硬生生弹出六条灰条（无错峰），
 * 等数据回来再换成带错峰的真榜单 —— 两次生硬入场，观感很跳。
 * 更要命的是测试按 `#ranksList .rk-item` 数错峰覆盖，
 * 骨架期被拍到时就会判成"stagger 没覆盖全"。
 * 收成一个入口，四条路径自动一致，以后加第五条也不会忘。
 */
function writeList(html) {
  const list = $("#ranksList");
  if (!list) return;
  list.innerHTML = html;
  stagger(list, ".rk-item");
}

/** 只重画已渲染的列表（不重新请求），用于书架变化后刷新标记。 */
function repaintItems() {
  const list = $("#ranksList");
  const items = RK.cache.get(RK.cur);
  if (!list || !items || !items.length) return;
  if (list.querySelector(".rk-item.sk")) return;   // 还在骨架态，别插队
  writeList(items.map(itemHTML).join(""));
  bindItems();
}

export async function loadRanks(kind) {
  if (kind) RK.cur = kind;
  const list = $("#ranksList");
  const desc = $("#ranksDesc");
  if (!list) return;

  // 切标签时先把选中态画上，别等网络回来才动
  const tb = $("#ranksTabs");
  if (tb) tb.innerHTML = tabsHTML();

  const k = RK.kinds.find(x => x.kind === RK.cur);
  if (desc) desc.textContent = k ? k.desc : "";

  // 书架标记是"锦上添花"，不能拖慢榜单出内容 —— 所以并着跑，
  // 不等它。回来了再补画一次标记（repaintItems）。
  ensureShelf(false).then(() => repaintItems());

  // 前端缓存命中 → 立刻渲染
  const hit = RK.cache.get(RK.cur);
  if (hit) {
    writeList(hit.length ? hit.map(itemHTML).join("") : emptyHTML());
    bindItems();
    paintFreshness();
    return;
  }

  writeList(skeleton());
  RK.loading = true;
  // ⚠ 把「我这次要的是哪一类」记成快照。
  //
  // 原来的写法两处都直接用 RK.cur —— 可 `await` 期间用户可能已经切走了，
  // `RK.cur` 早变了。后果是**旧榜单的数据被写进新标签的缓存键**：
  //   用户点「总点击榜」→ 还没回来就点「推荐票榜」
  //   → 总点击榜的响应回来，`RK.cache.set(RK.cur, items)` 用的是**推荐票榜**的 key
  //   → 之后切回推荐票榜，命中缓存，看到的是总点击榜的内容（而且不会再去请求）。
  // 用快照：请求谁、缓存写给谁，都认准发起时那一个。
  const want = RK.cur;
  try {
    const d = await api.get(`/api/ranks?kind=${encodeURIComponent(want)}`);
    if (!d || !d.ok) throw new Error((d && d.error) || "拿不到榜单");
    const items = d.items || [];
    RK.cache.set(want, items);
    if (typeof d.age === "number") { RK.age = d.age; RK.refreshedAt = 0; }
    // 用户可能已经切走了，别把旧结果盖上去
    if (RK.cur !== want) return;
    writeList(items.length ? items.map(itemHTML).join("") : emptyHTML(d.empty_hint));
    bindItems();
    paintFreshness();
  } catch (e) {
    if (RK.cur !== want) return;      // 已经切走了，别把错误盖到新标签上
    writeList(`<div class="rk-err">没拿到榜单：${esc(e.message || e)}
      <button class="btn ghost sm" id="rkRetry">重试</button></div>`);
    const rt = $("#rkRetry");
    if (rt) rt.onclick = () => loadRanks();
  } finally {
    // ⚠ 只有「我还是当前那次」才能清 loading —— 否则旧请求收尾会
    //   把新请求的 loading 状态清掉（新请求还在跑，界面却以为完事了）。
    if (RK.cur === want) RK.loading = false;
  }
}

/** 手动刷新：立刻拿最新榜单，不用等下一个 30 分钟周期。 */
export async function refreshRanks() {
  const btn = $("#ranksRefresh");
  if (btn) { btn.disabled = true; btn.classList.add("spin"); }
  try {
    // 只刷当前这一类就够了（用户在看的是它）——全刷要十几秒，
    // 而"刷新我眼前这个"才是真实诉求。
    await api.post(`/api/ranks/refresh?kind=${encodeURIComponent(RK.cur)}`);
    RK.cache.delete(RK.cur);
    RK.refreshedAt = Date.now();
    RK.age = 0;
    await loadRanks();
    toast("已刷新到最新");
  } catch (e) {
    toast("刷新失败：" + (e.message || e), "warn");
  } finally {
    if (btn) { btn.disabled = false; btn.classList.remove("spin"); }
  }
}

function emptyHTML(hint) {
  return `<div class="rk-err">${esc(hint || "这个榜单暂时没有内容。")}
    <button class="btn ghost sm" id="rkRetry">重试</button></div>`;
}

function bindItems() {
  const list = $("#ranksList");
  if (!list) return;
  // 错峰统一由 writeList() 负责（四条渲染路径都走它），这里只管绑事件。
  list.querySelectorAll(".rk-item[data-title]").forEach(el => {
    el.onclick = () => {
      const t = el.dataset.title;
      if (!t) return;
      // 复用发现页的搜索流程：填进输入框 → 滚上去 → 开搜。
      // 这样"从榜单点进来"和"自己手打书名"走的是同一条被验证过的路。
      const q = $("#q");
      if (q) q.value = t;
      const box = $("#ranksBox");
      if (box) box.classList.add("folded");
      window.scrollTo({ top: 0, behavior: "smooth" });
      runSearch(t, true);
    };
  });
  const rt = $("#rkRetry");
  if (rt) rt.onclick = () => { RK.cache.delete(RK.cur); loadRanks(); };
}

export async function mountRanks() {
  if (RK.mounted) return;
  RK.mounted = true;

  const box = $("#ranksBox");
  if (!box) return;

  const fb = $("#ranksFold");
  if (fb) fb.onclick = () => {
    RK.folded = !RK.folded;
    PRE.set("ranksFold", RK.folded);
    renderRanks();
    // 从收起状态展开时，如果还没数据就顺手拉一次
    if (!RK.folded && !RK.cache.size) loadRanks();
  };

  // 标签用事件委托 —— 标签是动态重建的，逐个绑会漏掉后来生成的
  const tb = $("#ranksTabs");
  if (tb) tb.onclick = e => {
    const b = e.target.closest(".rk-tab");
    if (!b) return;
    const kind = b.dataset.kind;
    if (!kind || kind === RK.cur) return;
    loadRanks(kind);
  };

  const rf = $("#ranksRefresh");
  if (rf) rf.onclick = () => refreshRanks();

  // 「去看我的书架」：榜单看完想回到自己存的书，这是很自然的下一步。
  const tl = $("#ranksToLib");
  if (tl) tl.onclick = () => { location.hash = "#shelf"; };

  // 书架变了（下载完一本 / 删了一本）→ 重新取一次书架集合，重画标记。
  // 走事件总线而不是直接调 shelf 内部函数：这是这个项目的约定，见 util.js。
  bus.on("task:done", () => ensureShelf(true).then(() => repaintItems()));
  bus.on("shelf:changed", () => ensureShelf(true).then(() => repaintItems()));

  try {
    const d = await api.get("/api/ranks/kinds");
    RK.kinds = (d && d.kinds) || [];
    if (!RK.kinds.length) { box.hidden = true; return; }
    if (!RK.kinds.some(k => k.kind === RK.cur)) RK.cur = RK.kinds[0].kind;
    box.hidden = false;
    renderRanks();
    // 默认展开时才立刻拉数据 —— 收起的用户不该白白触发一次联网
    if (!RK.folded) loadRanks();
  } catch {
    // 拿不到目录（比如老版本服务端）就当这个功能不存在，不要报错打扰用户
    box.hidden = true;
  }
}

export { RK };
