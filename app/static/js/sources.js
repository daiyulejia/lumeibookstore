/* ==========================================================================
   来源健康检查 + 来源库
   —— 前者是「内置/适配的来源现在还活着吗」，
      后者是「联网发现攒下来的站和书」（用户点名的「不断壮大、定期筛选」）。
   ========================================================================== */

import { $, $$, esc, api, bus, openDrawer, toast, confirmBox } from "./util.js";
import { stagger } from "./motion.js";
import { artHTML } from "./art.js";

/* 渲染代次。
   两个页签各是一次**异步**渲染：点了「来源库」之后，先前那次
   「实时检测」的请求可能才回来，把新内容覆盖掉 —— 界面上就会看到
   「来源库」高亮着、内容却是来源检测。每次渲染领一个号，
   写完 innerHTML 前对一下号，过期的那次直接放弃。 */
let seq = 0;
const take = () => ++seq;
const fresh = n => n === seq;

const KIND_LABEL = {
  builtin: "内置", adapted: "自动适配", custom: "自定义", discovered: "联网发现",
};

function srcCard(s, i) {
  const state = s.ok === true ? "ok" : s.ok === false ? "bad" : "mute";
  const word = s.ok === true ? "正常" : s.ok === false ? "打不开" : "未测";
  const ms = s.ms || 0;
  const spd = s.ok !== true ? "" :
    ms < 500 ? `<span class="tag ok">${ms} ms</span>` :
    ms < 1800 ? `<span class="tag">${ms} ms</span>` :
    `<span class="tag slow">${ms} ms</span>`;
  const kind = s.kind || "builtin";
  const tags = [
    `<span class="tag ${kind === "builtin" ? "" : "own"}">${KIND_LABEL[kind] || esc(kind)}</span>`,
    s.engine ? `<span class="tag">${esc(s.engine)}</span>` : "",
    s.chapter_paged ? `<span class="tag own">分页自动拼接</span>` : "",
    s.has_search === false ? `<span class="tag slow">无站内搜索</span>` : "",
    spd,
  ].filter(Boolean).join("");
  const host = (s.url || "").replace(/^https?:\/\//, "").replace(/\/$/, "");
  return `<div class="hcard${state === "bad" ? " bad" : ""}">
    <div class="hr">
      <span class="hn">${esc(s.display || s.name)}</span>
      <span class="pill ${state}">${word}</span>
    </div>
    ${host ? `<div class="hu">${esc(host)}${s.note ? " · " + esc(s.note) : ""}</div>` : ""}
    <div class="htags">${tags}</div>
  </div>`;
}

async function renderSources() {
  const body = $("#srcBody");
  if (!body) return;
  const my = take();
  body.innerHTML = Array.from({ length: 4 }).map(() =>
    `<div class="skel" style="margin-bottom:9px"><i class="w1"></i></div>`).join("");
  try {
    const list = await api.get("/api/sources/check");
    if (!fresh(my)) return;                      // 已经切到别的页签了
    const ok = list.filter(s => s.ok === true).length;
    const bad = list.filter(s => s.ok === false).length;
    const unk = list.length - ok - bad;
    body.innerHTML = `
      <div class="hsum" style="margin-bottom:12px">
        <span><span class="n">${list.length}</span> 个来源</span>
        <span><span class="dot ok"></span>${ok} 正常</span>
        ${bad ? `<span><span class="dot bad"></span>${bad} 打不开</span>` : ""}
        ${unk ? `<span><span class="dot mute"></span>${unk} 未测</span>` : ""}
        <span class="sep"></span>
        <button class="btn ghost sm" id="srcAgain">再测一次</button>
      </div>
      ${list.map(srcCard).join("")}
      <div style="font-size:12px;color:var(--t-3);line-height:1.75;margin-top:14px;padding-top:12px;border-top:1px solid var(--s-line-2)">
        这里只反映<b>此刻</b>能不能打开。小说站经常抽风、限流、换域名，
        打不开不代表永久失效 —— 过一会儿再测一次往往就好了。
        被站点封 IP 时（连接都建不起来）会自动进入 90 秒冷却，不再反复去撞。
      </div>`;
    const again = $("#srcAgain", body);
    if (again) again.onclick = renderSources;
    stagger(body, ".hcard");
  } catch (e) {
    if (!fresh(my)) return;
    body.innerHTML = `<div class="empty">${artHTML("error_confused", "m")}
      <h3>探测失败</h3><p>${esc(e.message)}</p></div>`;
  }
}

/* --------------------------------------------------------------------------
   来源库
   -------------------------------------------------------------------------- */
let REG = null;
let regTab = "sites";

async function loadRegistry() {
  try {
    REG = await api.get("/api/registry");
  } catch (e) {
    REG = null;
    REG_ERROR = e.message || "读取失败";
    return;
  }
  REG_ERROR = "";
}
let REG_ERROR = "";

function statRow() {
  const st = (REG && REG.stats) || {};
  return `
    <div class="hsum" style="margin-bottom:12px">
      <span><span class="n">${st.sites || 0}</span> 个站</span>
      <span><span class="dot ok"></span>${st.sites_ok || 0} 可用</span>
      <span class="sep"></span>
      <span><span class="n">${st.books || 0}</span> 本书</span>
      <span><span class="dot ok"></span>${st.books_ok || 0} 可用</span>
    </div>`;
}

function tabsHTML() {
  const st = (REG && REG.stats) || {};
  return `<div class="regtabs">
    <button class="rtab${regTab === "sites" ? " on" : ""}" data-rt="sites">站点 ${st.sites || 0}</button>
    <button class="rtab${regTab === "books" ? " on" : ""}" data-rt="books">书 ${st.books || 0}</button>
    <span class="grow"></span>
    <button class="btn ghost sm" id="regCheck">体检</button>
    <button class="btn ghost sm" id="regPrune">清失效</button>
  </div>`;
}

function siteRow(s, i) {
  const ok = +s.ok || 0, fail = +s.fail || 0;
  const hp = s.healthy ? `<span class="pill ok">可用</span>`
                       : `<span class="pill bad">已失效</span>`;
  const tags = [
    s.toc_tpl ? `<span class="tag own">目录模板已学</span>` : "",
    s.content_hint ? `<span class="tag own">正文容器 ${esc(s.content_hint)}</span>` : "",
    ok ? `<span class="tag ok">成功 ${ok}</span>` : "",
    fail ? `<span class="tag slow">失败 ${fail}</span>` : "",
  ].filter(Boolean).join("");
  const last = s.last_ok ? new Date(s.last_ok * 1000).toLocaleDateString() : "—";
  // 学到站名就把域名降成副标题；没学到就还是显示域名（别装作认识它）
  const named = s.label && s.label !== s.host;
  return `<div class="hcard${s.healthy ? "" : " bad"}">
    <div class="hr"><span class="hn">${esc(named ? s.label : s.host)}</span>${hp}</div>
    <div class="hu">${named ? `<span class="mono">${esc(s.host)}</span> · ` : ""}最近成功 ${last}</div>
    <div class="htags">${tags}</div>
    <div class="racts"><button class="mini" data-forget-site="${esc(s.host)}">移出库</button></div>
  </div>`;
}

function bookRow(b, i) {
  const hp = b.healthy ? `<span class="pill ok">可用</span>` : `<span class="pill bad">已失效</span>`;
  const tags = [
    b.chapters ? `<span class="tag">${b.chapters} 章</span>` : "",
    b.author ? `<span class="tag">${esc(b.author)}</span>` : "",
    b.ok ? `<span class="tag ok">命中 ${b.ok} 次</span>` : "",
  ].filter(Boolean).join("");
  const named = b.label && b.label !== b.host;
  return `<div class="hcard${b.healthy ? "" : " bad"}">
    <div class="hr"><span class="hn">${esc(b.title || b.url)}</span>${hp}</div>
    <div class="hu">${named ? `${esc(b.label)} <span class="mono">${esc(b.host || "")}</span>` : esc(b.host || "")}</div>
    <div class="htags">${tags}</div>
    <div class="racts"><button class="mini" data-forget-book="${esc(b.url)}">移出库</button></div>
  </div>`;
}

async function renderRegistry() {
  const body = $("#srcBody");
  if (!body) return;
  const my = take();
  if (!REG) {
    body.innerHTML = `<div class="empty"><div class="e">📡</div><h3>读取中…</h3></div>`;
    await loadRegistry();
    if (!fresh(my)) return;
    if (!REG) {
      body.innerHTML = `<div class="empty"><div class="e">🗃️</div>
        <h3>读不到来源库</h3><p>${esc(REG_ERROR)}</p></div>`;
      return;
    }
  }
  const sites = REG.sites || [];
  const books = REG.books || [];
  const rows = regTab === "sites" ? sites.map(siteRow) : books.map(bookRow);
  const emptyText = regTab === "sites"
    ? `<div class="empty" style="padding:26px 0"><div class="e">🌐</div>
        <h3>还没有攒下站点</h3><p>本地来源搜不到某本书时，我会自己去搜索引擎找，
        把能打开、有目录的站记进这里 —— 用得越多，能直接命中的书就越多。</p></div>`
    : `<div class="empty" style="padding:26px 0"><div class="e">📚</div>
        <h3>还没有攒下书</h3><p>联网找到的书会记在这里，下次搜同一本可以直接命中，
        不用再走一遍搜索引擎。</p></div>`;
  if (!fresh(my)) return;

  body.innerHTML = statRow() + tabsHTML() + (rows.length ? rows.join("") : emptyText) + `
    <div style="font-size:12px;color:var(--t-3);line-height:1.75;margin-top:14px;padding-top:12px;border-top:1px solid var(--s-line-2)">
      这是<b>联网发现</b>攒下来的库：搜书时本地来源全打不开，我就会出去搜，
      把找到的站和书存进来 —— 库越大，下次越不用联网。
      同一个站第二次抓会直接用它上次学到的<b>目录模板</b>和<b>正文容器</b>，不再重新猜。
      「体检」会把记下的书重开一遍，连续打不开的自动清掉。
    </div>`;

  $$("[data-rt]", body).forEach(b => b.onclick = () => { regTab = b.dataset.rt; renderRegistry(); });
  stagger(body, ".hcard");
  const ck = $("#regCheck", body);
  if (ck) ck.onclick = async () => {
    ck.disabled = true; ck.textContent = "体检中…";
    try {
      const r = await api.get("/api/registry/check");
      toast(`体检完成：存活 ${r.ok} · 失效 ${r.dead} · 清理 ${r.books_removed} 本 / ${r.sites_removed} 站`, r.dead ? "warn" : "ok");
      await loadRegistry(); renderRegistry();
    } catch (e) { toast("体检失败：" + e.message, "err"); }
    finally { const n = $("#regCheck"); if (n) { n.disabled = false; n.textContent = "体检"; } }
  };
  const pr = $("#regPrune", body);
  if (pr) pr.onclick = async () => {
    const yes = await confirmBox({
      title: "清理来源库",
      message: "把来源库里已经失效的站点和书清掉？健康的那部分会保留。",
      okText: "清理失效项", danger: true,
    });
    if (!yes) return;
    try {
      const r = await api.post("/api/registry/prune", {});
      toast(`清理完成：${r.books_removed} 本 / ${r.sites_removed} 站`, "ok");
      await loadRegistry(); renderRegistry();
    } catch (e) { toast("清理失败：" + e.message, "err"); }
  };
  $$("[data-forget-site]", body).forEach(b => b.onclick = async () => {
    await api.del("/api/registry/site?host=" + encodeURIComponent(b.dataset.forgetSite));
    await loadRegistry(); renderRegistry();
  });
  $$("[data-forget-book]", body).forEach(b => b.onclick = async () => {
    await api.del("/api/registry/book?url=" + encodeURIComponent(b.dataset.forgetBook));
    await loadRegistry(); renderRegistry();
  });
}

/* --------------------------------------------------------------------------
   抽屉：两个页签
   -------------------------------------------------------------------------- */
let tab = "check";

function renderTab() {
  $$("#srcTabs .stab").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
  $("#srcHint").textContent = tab === "check"
    ? "当前能不能打开"
    : "联网发现攒下来的站和书";
  if (tab === "check") renderSources(); else renderRegistry();
}

/* 深链：#sources 开抽屉、#registry 直接落在来源库那一页。
   刷新能保持，也能把「我的来源库」直接发给别人看。 */
function setHash(h) {
  if (location.hash === h) return;
  try { history.replaceState(null, "", location.pathname + h); } catch { /* 无所谓 */ }
}

bus.on("drawer:closed", id => {
  if (id === "srcDrawer" && /^#(sources|registry)$/.test(location.hash)) setHash("");
});

export function openSources(initialTab = "") {
  if (initialTab) tab = initialTab;
  const existing = document.getElementById("srcDrawer");
  if (existing) { renderTab(); setHash(tab === "registry" ? "#registry" : "#sources"); return; }
  openDrawer({
    id: "srcDrawer",
    title: "来源",
    body: `<div id="srcTabs">
        <button class="stab on" data-tab="check">实时检测</button>
        <button class="stab" data-tab="registry">来源库</button>
      </div>
      <div class="shint" id="srcHint"></div>
      <div id="srcBody"></div>`,
    actions: `<button class="iconbtn" id="srcAgainH" title="刷新">↻</button>`,
    onMount: d => {
      $$("#srcTabs .stab", d.el).forEach(b => b.onclick = () => {
        tab = b.dataset.tab;
        setHash(tab === "registry" ? "#registry" : "#sources");
        renderTab();
      });
      $("#srcAgainH", d.el).onclick = () => renderTab();
      renderTab();
    },
  });
  setHash(tab === "registry" ? "#registry" : "#sources");
}
