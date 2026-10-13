/* ==========================================================================
   书架
   ========================================================================== */

import { $, $$, esc, api, toast, bus, confirmBox, debounce } from "./util.js";
import { stagger } from "./motion.js";
import { coverHTML } from "./discover.js";

let shelfCache = [];

/* 上一份书架的「形状」—— 只有**书的集合**变了才广播 shelf:changed。
   ⚠ 为什么用形状比对而不是每次都发：`loadShelf` 会被 `reader:closed`、
   `task:done`、点刷新等多条路径调到，每次都广播的话，监听方
   （`ranks.js` 会重新拉书架 + 重画全部榜单项）就被无意义地跑很多遍。
   用户感知到的"书架变了"只有两种：**多了一本 / 少了一本** ——
   缓存进度变了不算（榜单上的星标只看"在不在书架里"）。 */
function shelfFingerprint(list) {
  return (list || []).map(b => b.id).sort().join("|");
}
let shelfPrint = "";

/* 书架页是否已交给 Vue 渲染。
   ⚠ 迁移期两种实现并存的方式：Vue 版的容器上会带 `data-vue-shelf`。
     为真时这里**只维护状态**（shelfCache / shelf:changed / 顶栏计数），
     不再碰 #shelfList、#shelfStat、#shelfEmpty 这三个 DOM ——
     它们已经不存在于 index.html 里（搬进 Vue 组件了），
     继续写会拿到 null 然后崩。
   ⚠ 为什么状态部分不能一起搬走：`shelfCache` 是"这本书在不在书架里"的
     真相源，阅读器、搜索页、榜单星标都在查它；`shelf:changed` 也还有
     ranks.js 在听。所以留在这里、由 Vue 组件反过来调用（见组件注释）。 */
function vueOwnsShelf() {
  return !!document.querySelector("[data-vue-shelf]");
}

export async function loadShelf() {
  try {
    const list = await api.get("/api/library");
    shelfCache = list;
    const fp = shelfFingerprint(list);
    if (fp !== shelfPrint) {
      shelfPrint = fp;
      bus.emit("shelf:changed");
    }

    // 顶栏那个「书架 (4)」的计数归 shell.js 管，跟 #view-shelf 无关，
    // 所以 Vue 接管了也要更新。
    const n = $("#shelfN");
    if (n) n.textContent = list.length ? `(${list.length})` : "";

    // 把最新数据广播出去。谁渲染谁订阅 —— 迁移期是 Vue 组件，
    // 迁完之前是下面这段 DOM 代码。这样"切到书架 / 缓存跑完 / 阅读器关闭"
    // 所有刷新路径都只有**一个**数据出口，不会出现"缓存跑完可见列表还是旧值"。
    bus.emit("shelf:loaded", list);

    if (vueOwnsShelf()) return;   // 下面的 DOM 都归 Vue 了，别碰

    $("#shelfStat").textContent = list.length ? `共 ${list.length} 本` : "";
    $("#shelfEmpty").classList.toggle("hidden", list.length > 0);

    $("#shelfList").innerHTML = list.map((b, i) => {
      const total = b.total || 0, cached = b.cached || 0;
      const pos = b.position || {};
      const readPct = total ? Math.min(100, ((pos.index || 1) - 1 + (pos.percent || 0)) / total * 100) : 0;
      const cachePct = total ? Math.min(100, cached / total * 100) : 0;
      return `<div class="shelf" data-id="${b.id}">
        ${coverHTML((b.title || "").length * 37 % 360, b.title, b.author)}
        <div class="info">
          <h4>${esc(b.title)}</h4>
          <div class="by">${esc(b.author || "作者未知")} · ${esc(b.source_display || b.source || "")}</div>
          <div class="prog">
            <div>
              <div class="lb"><span>读到 ${pos.index || 1}/${total || "?"} 章</span><span>${readPct.toFixed(0)}%</span></div>
              <div class="bar"><i style="width:${readPct}%"></i></div>
            </div>
            <div>
              <div class="lb"><span>已缓存 ${cached} 章</span><span>${cachePct.toFixed(0)}%</span></div>
              <div class="bar"><i style="width:${cachePct}%;background:var(--ok)"></i></div>
            </div>
          </div>
          <div class="acts">
            <button class="btn primary sm" data-a="read">${readPct > 1 ? "继续阅读" : "开始阅读"}</button>
            <button class="btn sm" data-a="cache">缓存全书</button>
            <button class="btn sm" data-a="export">导出</button>
            <button class="btn ghost sm" data-a="del">移除</button>
          </div>
        </div>
      </div>`;
    }).join("");

    stagger($("#shelfList"), ".shelf");

    $$("#shelfList .shelf").forEach(el => {
      const id = el.dataset.id;
      const b = list.find(x => x.id === id);
      $$("[data-a]", el).forEach(btn => btn.onclick = async () => {
        const a = btn.dataset.a;
        if (a === "read") bus.emit("shelf:read", b);
        if (a === "export") bus.emit("shelf:export", { library_id: id, title: b.title, author: b.author });
        if (a === "cache") bus.emit("shelf:cache", { id, title: b.title });
        if (a === "del") {
          const yes = await confirmBox({
            title: "移出书架",
            message: `把《${b.title}》移出书架？已经缓存的正文章节会一起删掉，下次要重新去网上抓。`,
            okText: "移出", danger: true,
          });
          if (!yes) return;
          await api.del("/api/library/" + id);
          toast("已移出书架");
          // 不用手动广播 —— `loadShelf` 里的形状比对会认出"少了一本"
          // 并自动 `bus.emit("shelf:changed")`（见文件顶部注释）。
          loadShelf();
        }
      });
    });
  } catch (e) {
    toast("读取书架失败：" + e.message, "err");
  }
}

export function findShelfBook(id) {
  return shelfCache.find(b => b.id === id);
}

export function mountShelf() {
  // ⚠ 书架页已迁到 Vue 时直接跳过：
  //   #btnShelfReload 在 index.html 里已经不存在了（搬进组件），
  //   这里 `$("#btnShelfReload").onclick = ...` 会 TypeError 把
  //   main.js 的启动流程整个炸掉 —— 后面 mountFiles/mountTasks/wireEvents
  //   全都不执行，页面看着"半死不活"（真机测试会一片红，但原因藏在
  //   一个 null 上，极难定位）。监听也交给组件自己订（它会在卸载时摘掉，
  //   而这里订的是永不摘的全局监听，两边都订会刷新两遍）。
  if (vueOwnsShelf()) return;

  $("#btnShelfReload").onclick = loadShelf;
  bus.on("reader:closed", loadShelf);
  // ⚠ 缓存/导出跑完必须重拉书架。
  //   以前只订了 `reader:closed` —— 于是「点缓存全书 → 进度条跑到 100% →
  //   回到书架，那条「已缓存 3/120 章」的绿条**还是旧值**」。用户会以为没缓存成，
  //   再点一次（白跑一遍全量抓取）。
  //   ⚠ 先节流一下再拉：一个任务完成只发一次事件，但"缓存全书 + 同时导出"
  //   会连发两次，没必要打两遍接口。
  bus.on("task:done", debounce(loadShelf, 300));
}

/* ---------- 迁移桥（Vue 侧要复用这两个） ----------
   ⚠ 为什么书架迁到 Vue 了还要留着这里的东西：
     ① `loadShelf` 被**别处的旧代码**调（main.js 的 reader:closed /
        task:done 处理链、ranks.js 的 shelf:changed 联动），
        这个函数还是旧代码在跑；
     ② shelfCache 是搜索页/阅读器查"这本书在不在书架里"的真相源。
     Vue 组件**不重写**这段逻辑，而是复用同一份 —— 否则又是"两份状态"。
     等全部迁完再一起删。 */
window.__lumeiLegacy = Object.assign(window.__lumeiLegacy || {}, {
  loadShelf, findShelfBook,
});
