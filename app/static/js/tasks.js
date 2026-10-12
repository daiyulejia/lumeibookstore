/* ==========================================================================
   任务（导出 / 缓存全书）
   ========================================================================== */

import { $, $$, esc, api, toast, bus, openDrawer } from "./util.js";

const POLLING = new Set();
const TASKS = new Map();

/* ---------- 发起 ---------- */
export async function createExport(body) {
  try {
    const r = await api.post("/api/download", body);
    toast(`开始导出 ${String(body.fmt || "txt").toUpperCase()}`);
    openTasks();
    pollTask(r.task_id);
  } catch (e) { toast("导出失败：" + e.message, "err"); }
}

export async function cacheBook({ id, title }) {
  try {
    const r = await api.post(`/api/library/${id}/cache`, {});
    toast(`开始缓存《${title}》，关掉页面也会继续`);
    openTasks();
    pollTask(r.task_id);
  } catch (e) { toast("缓存失败：" + e.message, "err"); }
}

/* ---------- 抽屉 ---------- */
export function openTasks() {
  const existing = document.getElementById("taskDrawer");
  if (existing) { refreshTasks(); return; }

  openDrawer({
    id: "taskDrawer",
    title: "任务",
    body: `<div id="taskBody"><div class="skel"><i class="w1"></i><i class="w2"></i></div></div>`,
    onMount: () => refreshTasks(),
  });
}

async function refreshTasks() {
  const body = $("#taskBody");
  if (!body) return;
  try {
    const list = await api.get("/api/tasks");
    const active = list.filter(t => t.status === "running" || t.status === "cancelling");
    $("#taskDot").classList.toggle("hidden", active.length === 0);

    if (!list.length) {
      body.innerHTML = `<div class="empty" style="padding:40px 0"><div class="e">😴</div>
        <h3>没有任务</h3><p>导出、缓存全书都会出现在这里。</p></div>`;
      return;
    }

    const doneN = list.filter(t => ["done", "error", "cancelled"].includes(t.status)).length;
    body.innerHTML = `
      <div class="hsum" style="margin-bottom:12px">
        <span><span class="n">${list.length}</span> 个</span>
        ${active.length ? `<span><span class="dot ok"></span>${active.length} 进行中</span>` : ""}
        <span class="sep"></span>
        ${doneN ? `<button class="btn ghost sm" id="taskClear">清掉已结束的 ${doneN} 个</button>` : ""}
      </div>
      ${list.map(t => {
        const pct = t.total ? Math.min(100, t.done / t.total * 100) : (t.status === "running" ? 3 : 100);
        const cls = { done: "ok", error: "bad", cancelled: "mute" }[t.status] || "warn";
        const label = { running: "进行中", cancelling: "取消中", done: "已完成", error: "失败", cancelled: "已取消" }[t.status] || t.status;
        return `<div class="task is-${t.status}">
          <div class="tl"><b>${esc(t.title || "未命名")}</b><span class="pill ${cls}">${label}</span></div>
          <div class="ts">${esc(t.msg || "")}</div>
          <div class="bar"><i style="width:${pct}%"></i></div>
          <div class="ta">
            ${t.status === "running" ? `<button class="btn sm" data-cancel="${t.id}">取消</button>` : ""}
            ${t.file ? `<button class="btn sm primary" data-get="${esc(t.file)}">下载</button>` : ""}
            ${["done", "error", "cancelled"].includes(t.status) ? `<button class="btn ghost sm" data-forget="${t.id}">移除</button>` : ""}
          </div>
        </div>`;
      }).join("")}`;

    const clr = $("#taskClear", body);
    if (clr) clr.onclick = async () => {
      for (const t of list) {
        if (["done", "error", "cancelled"].includes(t.status)) {
          try { await api.post("/api/forget/" + t.id); } catch {}
        }
      }
      refreshTasks();
    };
    $$("[data-cancel]", body).forEach(b => b.onclick = async () => {
      await api.post("/api/cancel/" + b.dataset.cancel);
      toast("已发送取消");
      refreshTasks();
    });
    $$("[data-get]", body).forEach(b => b.onclick = () => {
      const a = document.createElement("a");
      a.href = api.url("/api/file/" + encodeURIComponent(b.dataset.get));
      a.download = b.dataset.get;
      a.click();
    });
    $$("[data-forget]", body).forEach(b => b.onclick = async () => {
      try { await api.post("/api/forget/" + b.dataset.forget); } catch {}
      TASKS.delete(b.dataset.forget);
      refreshTasks();
    });
  } catch {}
}

/* ---------- 轮询 ---------- */
/* ⚠ 这里踩过一个"任务卡在 0% 永不结束"的坑，两条原因都要堵住：
   ① `catch {}` 把网络抖动也当成"任务没了"直接退出去 —— 用户看到进度条冻住，
      刷新页面才能恢复。网络错要**继续重试**，只有明确的 unknown 才算结束。
   ② 轮询串行跑 1 次/秒看似无害，但导出大书会跑几分钟 —— 期间标签页被挂起
      （切后台 / 锁屏）时 setTimeout 会被节流，回来时可能落后几十次。
      记录 `fail` 次数，连续失败到上限才放弃，并在放弃时把话说给用户听。 */
const POLL_MAX_FAIL = 5;

export function pollTask(id) {
  if (POLLING.has(id)) return;
  POLLING.add(id);
  let fail = 0;
  const tick = async () => {
    if (!POLLING.has(id)) return;      // 期间被别处停掉了
    try {
      const t = await api.get("/api/progress/" + id);
      fail = 0;
      if (t.status === "unknown") { POLLING.delete(id); return; }
      TASKS.set(id, t);
      refreshTasks();
      if (t.status === "running" || t.status === "cancelling") { setTimeout(tick, 1000); return; }
      POLLING.delete(id);
      if (t.status === "done") { toast("完成：" + t.msg, "ok"); bus.emit("task:done", t); }
      else if (t.status === "error") toast("失败：" + t.msg, "err");
      else bus.emit("task:done", t);
    } catch (e) {
      // 网络抖一下而已 —— 退避重试，别把任务判死
      if (++fail > POLL_MAX_FAIL) {
        POLLING.delete(id);
        toast("任务进度查不到了：" + (e && e.message ? e.message : "网络异常"), "err");
        return;
      }
      setTimeout(tick, Math.min(8000, 1000 * fail));
    }
  };
  tick();
}

export function mountTasks() {
  $("#btnTasks").onclick = () => { $("#taskDot").classList.add("hidden"); openTasks(); };
}
