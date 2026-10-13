/* ==========================================================================
   文件（导出的成品）
   ========================================================================== */

import { $, $$, esc, api, toast, PRE, bus, fmtSize, fmtTime, confirmBox } from "./util.js";
import { stagger } from "./motion.js";

/* 拉出一张 SVG 格式图标（比 emoji 可控：能吃 currentColor，五套主题都成立）。
   为什么不用素材水豚图当格式图标：那是"吉祥物"，用在"文件格式"上是望文生义 ——
   格式是**功能性**的，需要一眼分辨，不该用有情绪的插画。 */
function fmtIcon(ext) {
  const p = {
    txt: "M4 2h8l4 4v12H4zM12 2v4h4",
    epub: "M4 2h9l4 4v12H4zM13 2v4h4M7 10h7M7 13h7",
    html: "M12 2a10 10 0 100 20 10 10 0 000-20M2 12h20M12 2c2.5 2.7 3.8 6.2 3.8 10S14.5 19.3 12 22M12 2C9.5 4.7 8.2 8.2 8.2 12S9.5 19.3 12 22",
  }[ext] || "M4 2h8l4 4v12H4z";
  return `<svg viewBox="0 0 24 24" width="22" height="22" fill="none"
    stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
    <path d="${p}"/></svg>`;
}

export async function loadFiles() {
  try {
    const list = await api.get("/api/downloads");

    // ⚠ 先广播再画 DOM。
    //   Vue 版的 FilesPanel 拿不到这份 list（它是本函数的局部变量），
    //   只能靠这个事件把数据接过去。顺序上先 emit 也更安全：
    //   万一下面旧 DOM 那几步抛了（元素已被迁走、为 null），
    //   Vue 侧至少已经拿到数据了。
    bus.emit("files:loaded", list);

    // —— 以下是旧实现（手写 DOM）。文件页迁到 Vue 之后
    //    #fileEmpty / #fileList 已经不在 index.html 里，为 null。
    //    用 vueOwnsFiles() 提前退出，别去 null 上挂东西。
    if (vueOwnsFiles()) return;

    $("#fileEmpty").classList.toggle("hidden", list.length > 0);
    $("#fileList").innerHTML = list.map((f, i) => `
      <div class="file">
        <div class="ic" data-ext="${esc(f.ext)}">${fmtIcon(f.ext)}</div>
        <div class="nm">
          <b title="${esc(f.name)}">${esc(f.name)}</b>
          <span>${f.ext.toUpperCase()} · ${fmtSize(f.size)} · ${fmtTime(f.mtime)}</span>
        </div>
        <div class="acts">
          ${f.ext === "html" ? `<button class="btn sm" data-open="${esc(f.name)}">打开看</button>` : ""}
          <a class="btn sm" href="${api.url("/api/file/" + encodeURIComponent(f.name))}" download>下载</a>
          <button class="btn ghost sm" data-del="${esc(f.name)}">删除</button>
        </div>
      </div>`).join("");

    stagger($("#fileList"), ".file");

    $$("[data-open]").forEach(b => b.onclick = () =>
      window.open(api.url("/api/file/" + encodeURIComponent(b.dataset.open)), "_blank"));
    $$("[data-del]").forEach(b => b.onclick = async () => {
      const yes = await confirmBox({ title: "删除文件", message: `删除 ${b.dataset.del}？这个操作不能撤销。`, okText: "删除", danger: true });
      if (!yes) return;
      await api.del("/api/file/" + encodeURIComponent(b.dataset.del));
      toast("已删除");
      loadFiles();
    });
  } catch (e) {
    toast("读取文件失败：" + e.message, "err");
  }
}

/* Vue 是否已经接管了这一页。
   ⚠ 判断依据是「容器上有没有 data-vue-files」，不是「Vue 那个模块加载没成功」——
   迁移期两种实现并存：Vue 版在任何一步出问题（构建没跟上、脚本被拦），
   这里就自动退回旧实现，页面永远不会空着。 */
function vueOwnsFiles() {
  return !!document.querySelector("[data-vue-files]");
}

export function mountFiles() {
  // ⚠ 必须先判断再取元素：文件页迁到 Vue 之后 `#btnFilesReload` / `#fmtPick`
  //   已经不在 index.html 里了（改由 Vue 渲染），下面 `pick.value = ...`
  //   会直接在 null 上抛 TypeError —— 而这个函数是在 main.js 的启动流程里
  //   被调用的，一抛就**整条启动链断掉**（搜索、书架、阅读器全挂）。
  //   书架页迁的时候踩过同一个坑（见 shelf.js 的 vueOwnsShelf）。
  if (vueOwnsFiles()) return;
  $("#btnFilesReload").onclick = loadFiles;
  const pick = $("#fmtPick");
  pick.value = PRE.get("fmt", "txt");
  pick.onchange = e => PRE.set("fmt", e.target.value);
}

/* ⚠ 事件订阅与 DOM 所有权**解耦**：
   `task:done → 刷新文件列表` 是"数据对不对"的事，跟这一页谁渲染无关。
   如果把它一起塞进 mountFiles 的提前 return 里，Vue 版就永远收不到导出完成
   的通知 —— 用户导出了一本书，切到文件页看到的还是旧列表（或者要手动点刷新）。
   所以这条订阅留在外面，Vue 侧那份由 FilesPanel 自己订（见 FilesPanel.vue）。

   为什么不在这里也 emit 一个事件给 Vue 用：那样导出完成时要多绕一圈，
   而且 Vue 组件的订阅时机（onMounted 之后）又会出现"广播早于订阅"的老问题。
   让 Vue 直接订阅 bus 是最短路径。 */
export function wireFilesEvents() {
  if (vueOwnsFiles()) return;
  bus.on("task:done", t => { if (t.kind === "download") loadFiles(); });
}

export function isFilesPage() {
  return vueOwnsFiles();
}

/* 迁移桥：Vue 侧要复用同一份 loadFiles（它里面还有 fmtIcon 与封面/下载链接
   的拼法，重写一遍就等于把'文件页长什么样'两处维护）。
   理由同 shelf.js 末尾的 loadShelf。（files.js 自己不需要 Vue 侧反向调用，
   但导出格式下拉框要读 PRE，所以 PRE 已经在 util.js 的桥上。） */
window.__lumeiLegacy = Object.assign(window.__lumeiLegacy || {}, { loadFiles });
