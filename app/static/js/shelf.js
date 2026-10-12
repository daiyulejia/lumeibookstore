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

export async function loadShelf() {
  try {
    const list = await api.get("/api/library");
    shelfCache = list;
    const fp = shelfFingerprint(list);
    if (fp !== shelfPrint) {
      shelfPrint = fp;
      bus.emit("shelf:changed");
    }
    $("#shelfN").textContent = list.length ? `(${list.length})` : "";
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
