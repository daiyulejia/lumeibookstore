/* ==========================================================================
   启动
   ========================================================================== */

import { installTelemetry } from "./telemetry.js";
import { $, api, toast, bus } from "./util.js";
import { initTheme } from "./theme.js";
import { initMotion } from "./motion.js";
import { nav, onNav, mountShell, bootstrapAuth } from "./shell.js";
import { mountDiscover, loadSources, searchFromHash } from "./discover.js";
import { mountRanks } from "./ranks.js";
import { mountHistory } from "./history.js";
import { mountShelf, loadShelf } from "./shelf.js";
import { mountFiles, loadFiles, wireFilesEvents } from "./files.js";
import { mountTasks, createExport, cacheBook, openTasks, pollTask } from "./tasks.js";
import { openSources } from "./sources.js";
import { openAdapt } from "./adapt.js";
import { openNet } from "./net.js";
import { mountReaderUI, openReader, closeReader, isReaderOpen } from "./reader.js";

/* ---------- 编排 ---------- */
function wireEvents() {
  bus.on("ui:sources", openSources);
  bus.on("ui:adapt", openAdapt);
  bus.on("ui:net", openNet);
  bus.on("ui:tasks", openTasks);

  // 从搜索结果进入阅读：先收进书架，再打开
  bus.on("book:read", async src => {
    if (!src || !src.url) { toast("这本书没有可用来源", "err"); return; }
    toast(`正在把《${src.title || ""}》收进书架…`);
    try {
      const meta = await api.post("/api/shelve", {
        title: src.title, author: src.author,
        source: src.source, url: src.url, intro: src.intro,
      });
      openReader(meta);
    } catch (e) { toast("入书架失败：" + e.message, "err"); }
  });

  bus.on("book:export", ({ src, book }) => createExport({
    title: src.title || (book && book.title),
    author: src.author || (book && book.author),
    source: src.source, url: src.url, intro: src.intro,
    fmt: $("#fmtPick").value,
    library_id: src.library_id || "",
  }));

  bus.on("shelf:read", b => openReader(b));
  bus.on("shelf:export", body => createExport({ ...body, fmt: $("#fmtPick").value }));
  bus.on("shelf:cache", body => cacheBook(body));
  bus.on("reader:cache", body => cacheBook(body));
  bus.on("reader:export", body => createExport({ ...body, fmt: $("#fmtPick").value }));

  // 缓存完成后，如果正在读这本书，把目录上的小圆点刷新一下
  bus.on("task:done", t => {
    if (t.kind === "cache" && isReaderOpen()) bus.emit("reader:cache-done", t);
  });
}

/* ---------- 深链 ----------
   #shelf / #files / #search=书名 / #read=书架id
   刷新能保持状态，也能把「这次搜索」「这本书」直接发给人。

   ⚠ 这个函数要能被**重复调用**（挂上 hashchange 之后）：
   之前它只在启动时跑一次，于是运行时改 hash 是**静默无效**的 ——
   榜单底部「去看我的书架」就是这么点不动的（`location.hash="#shelf"` 设了，
   却没有任何人监听 hashchange）。所有状态重置都要写在这里，不能靠"页面只加载一次"。 */
async function bootRoute() {
  const h = decodeURIComponent(location.hash || "");

  const rd = h.match(/^#read=([0-9a-f]{6,32})$/);
  if (rd) {
    try { openReader(await api.get("/api/library/" + rd[1])); }
    catch { toast("这本书不在书架里", "err"); }
    return;
  }
  const se = h.match(/^#search=(.+)$/);
  if (se) { nav("home"); searchFromHash(se[1]); return; }
  if (h === "#registry") { nav("home"); openSources("registry"); return; }
  if (h === "#stats") { nav("home"); openSources("stats"); return; }
  if (h === "#sources") { nav("home"); openSources(); return; }
  if (h === "#shelf") nav("shelf");
  else if (h === "#files") nav("files");
  else nav("home");
}

/* ---------- 键盘：任务面板 ---------- */
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && isReaderOpen()) return;
});

/* ---------- go ---------- */
(async function main() {
  // ⚠ 第一件事：装前端埋点钩子。必须早于任何 fetch / 任何 await ——
  //   它是**全局**钩子（onerror / unhandledrejection / fetch 包装），
  //   晚一步装，那之前发生的错误就漏了。
  installTelemetry();

  initTheme();
  initMotion();
  mountShell();
  mountDiscover();
  // ⚠ 必须在 mountDiscover **之后** —— 那个函数会插入（或复用）搜索框周围的
  //   DOM；如果先把 .searchbox 包进 .h-wrap，mountDiscover 里的
  //   `$("#q")` 虽然还是找得到，但 `input.closest(".searchbox")` 的层级判断
  //   会落在旧结构上。跑在它后面就没有这个先后依赖。
  mountHistory();
  mountShelf();
  mountFiles();
  wireFilesEvents();
  mountTasks();
  mountReaderUI();
  wireEvents();

  // ---- 给自动化测试一个「骨架已挂载」的信号 ----
  // ⚠ 为什么需要它：HTML 里的静态标签（#btnSearch、#q …）在**解析出来**时
  //   就在 DOM 里了，但挂在它们身上的事件监听要等上面这几个 mountXxx 跑完
  //   才绑上。测试如果只等「元素存在」就发回车，正好撞进这个空窗 ——
  //   同一份代码一次 ship 通过、下次 ship 挂（实测：test_buttons 的
  //   「A1 回车触发了搜索」就是这样偶发假红的，看着像功能坏了）。
  //   等到这个标记再动手，就没有这个空窗了。
  document.documentElement.dataset.mounted = "1";

  // 切到书架/文件时按需刷新（不是每次启动都拉一遍）
  onNav("shelf", loadShelf);
  onNav("files", loadFiles);

  await bootstrapAuth();

  loadSources();
  loadShelf();
  bootRoute();
  // ⚠ 榜单已迁移到 Vue（frontend/src/components/RanksPanel.vue）。
  //   这里用「容器上有没有 data-vue-ranks」来判断该不该用旧实现 ——
  //   迁移期两种实现并存：Vue 版没有就退回旧版，页面永远不会空着。
  //   全部迁完后这两行连同 ranks.js 一起删。
  if (!document.querySelector("[data-vue-ranks]")) {
    mountRanks();
  }

  // ⚠ 运行时改 hash 也要真的跳过去。
  // 没有这一行，`location.hash="#shelf"`（榜单里的「去看我的书架」就是这么调的）
  // 会静默无效 —— 页面停在原地，按钮看着像坏的。
  // 记录上一次的 hash，避免 nav() 自己 replaceState 后又被这里回环触发一遍。
  let _lastHash = location.hash;
  window.addEventListener("hashchange", () => {
    if (location.hash === _lastHash) return;
    _lastHash = location.hash;
    // 阅读器自己管 #read=…，别把它顶掉
    if (isReaderOpen() && /^#read=/.test(location.hash)) return;
    bootRoute();
  });

  // 有正在跑的任务（比如上次开的缓存全书）就接着盯
  try {
    const tasks = await api.get("/api/tasks");
    tasks.filter(t => t.status === "running").forEach(t => pollTask(t.id));
  } catch {}
})();
