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

export function mountFiles() {
  $("#btnFilesReload").onclick = loadFiles;
  const pick = $("#fmtPick");
  pick.value = PRE.get("fmt", "txt");
  pick.onchange = e => PRE.set("fmt", e.target.value);
  bus.on("task:done", t => { if (t.kind === "download") loadFiles(); });
}
