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

/* 把任意值渲染成**纯数字**字符串，用于插进 innerHTML 的计数位。
 *
 * 为什么数字也要过一道（而不是直接 `${x || 0}`）：
 *   这些字段来自接口，虽然服务端现在用 int() 强转过，但"接口返回的一定是
 *   数字"是**对另一端的信任**。一旦哪天服务端改成返回字符串、或数据被污染，
 *   直接把值插进 innerHTML 就是注入点。
 *   过 Number() 之后非有限值一律变 0 —— 既防注入，也顺手兜住了 NaN/undefined
 *   渲染成"NaN"那种难看的情况。
 */
const num = v => {
  const n = Number(v);
  return Number.isFinite(n) ? String(n) : "0";
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
  // ⚠ 计数位一律过 num()（本文件顶部有详述：接口给的数字不直接信任）。
  //   statRow/tabsHTML 原来直接插 st.sites 再拿"或 0"兜底 —— 和自己
  //   定义的纪律不一致，顺手补上。
  return `
    <div class="hsum" style="margin-bottom:12px">
      <span><span class="n">${num(st.sites)}</span> 个站</span>
      <span><span class="dot ok"></span>${num(st.sites_ok)} 可用</span>
      <span><span class="dot ok"></span>${num(st.sites_searchable)} 能搜</span>
      <span class="sep"></span>
      <span><span class="n">${num(st.books)}</span> 本书</span>
      <span><span class="dot ok"></span>${num(st.books_ok)} 可用</span>
    </div>`;
}

function tabsHTML() {
  const st = (REG && REG.stats) || {};
  return `<div class="regtabs">
    <button class="rtab${regTab === "sites" ? " on" : ""}" data-rt="sites">站点 ${num(st.sites)}</button>
    <button class="rtab${regTab === "books" ? " on" : ""}" data-rt="books">书 ${num(st.books)}</button>
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
    // 「能搜」是这个库最重要的资产：学过站内搜索的站，下次搜书会直接来
    // 这里（不用再走搜索引擎）。夜间自动学的就是它 —— 不亮出来的话，
    // 用户看到的只是一串"可用/已失效"，完全不知道搜索能力在长。
    // ⚠ 判据用接口的 `searchable`（健康 + 有模板），和总览那个数同源；
    //   有模板但站已失效的不标（那种站搜了也打不开，标了是空头支票）。
    s.searchable
      ? `<span class="tag ok" title="学过它的站内搜索：搜书时会直接来这个站找，不用再联网">能搜</span>`
      : "",
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
  // ⚠ 章节数必须和「目录可能不全」**一起**出现。
  //   单看一个「12 章」和「这本书就是 12 章」长得一模一样 ——
  //   我们实测过的那本《我们猫猫不能听这些》全书 119 章，
  //   站点把完整目录放在 /mulu/2.html，只跟第一页就是 12 章。
  //   用户按这个数字判断"要不要下"，下完才发现是零头。
  //   `b.note` 是体检/联网发现抓目录时如实带回来的结论（见 app/registry.py
  //   note_book 的三态说明）：这个来源的目录是不是只有一部分。
  const chap = b.chapters
    ? `<span class="tag${b.note ? " slow" : ""}"${b.note ? ` title="${esc(b.note)}"` : ""}>`
      + `${b.chapters} 章${b.note ? " ⚠ 可能不全" : ""}</span>`
    : (b.note ? `<span class="tag slow" title="${esc(b.note)}">目录可能不全</span>` : "");
  const tags = [
    chap,
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
      标着<b>能搜</b>的站还学过<b>站内搜索</b>：搜书会直接来这些站找，夜里也会接着学新的。
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
   抽屉：三个页签
   -------------------------------------------------------------------------- */
let tab = "check";

function renderTab() {
  $$("#srcTabs .stab").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
  $("#srcHint").textContent =
    tab === "check" ? "当前能不能打开"
    : tab === "stats" ? "搜索历史与访客（本机数据）"
    : "联网发现攒下来的站和书";
  if (tab === "check") renderSources();
  else if (tab === "stats") renderStats();
  else renderRegistry();
}

/* 深链：#sources 开抽屉、#registry 开来源库、#stats 开统计。
   刷新能保持，也能把「我的来源库」直接发给别人看。 */
function setHash(h) {
  if (location.hash === h) return;
  try { history.replaceState(null, "", location.pathname + h); } catch { /* 无所谓 */ }
}

bus.on("drawer:closed", id => {
  if (id === "srcDrawer" && /^#(sources|registry|stats)$/.test(location.hash)) setHash("");
});

/* --------------------------------------------------------------------------
   统计页签：搜索历史 + 访客记录
   --------------------------------------------------------------------------
   为什么放在这个抽屉里而不是另开一页：
     它们都是"关于这个站本身"的数据，和来源库/来源检测是同一类东西
     （都是"运维视角"）；另开一页会让底部导航变长，而移动端导航栏
     只有 3~4 格，再加就挤了。放页签里既找得到、又不占导航。

   两块都有"清空"，所以都走 confirmBox 二次确认 —— 数据是一点点攒的，
   手滑一下全没了会很难受（而且删了就真没了，服务端不留备份）。
   -------------------------------------------------------------------------- */
async function renderStats() {
  const body = $("#srcBody");
  if (!body) return;
  const my = take();
  body.innerHTML = Array.from({ length: 3 }).map(() =>
    `<div class="skel" style="margin-bottom:9px"><i class="w1"></i></div>`).join("");
  try {
    // ⚠ 热词榜单独 catch，**不能进 Promise.all 的必败链**：
    //   Promise.all 是"一损俱损" —— 热词接口挂掉会让整个统计面板报错，
    //   而用户失去的是"四格数字 + 访客明细"这些更重要的东西。
    //   热词只是锦上添花，缺了就当空榜渲染。
    const soft = p => p.catch(() => null);
    const [hs, vs, recent, hot] = await Promise.all([
      api.get("/api/history/search/stats"),
      api.get("/api/visits/stats"),
      api.get("/api/visits?limit=12"),
      soft(api.get("/api/history/search/hot?limit=10")),
    ]);
    if (!fresh(my)) return;

    const emptyWords = (hs.empty_words || []);
    const topPaths = (vs.top_paths_today || []);
    const rows = (recent && recent.items) || [];
    const hotWords = (hot && hot.items) || [];

    body.innerHTML = `
      <div class="stgrid">
        <div class="stcell"><b>${num(vs.pv_today)}</b><span>今日访问</span></div>
        <div class="stcell"><b>${num(vs.uv_today)}</b><span>今日来客</span></div>
        <div class="stcell"><b>${num(vs.pv_yesterday)}</b><span>昨日访问</span></div>
        <div class="stcell"><b>${num(vs.uv_total)}</b><span>累计来客</span></div>
      </div>

      <div class="stsec">
        <div class="sth">搜索 <span>共 ${num(hs.words)} 个词 · 搜了 ${num(hs.searches)} 次</span></div>
        ${hotWords.length
          ? `<div class="stnote">大家都在搜（点一下直接再搜一次）：</div>
             <div class="stchips">${hotWords.map(w =>
               `<span class="stchip click" data-hot="${esc(w.kw)}" title="搜过 ${num(w.count)} 次">${esc(w.kw)} <i>${num(w.count)}</i></span>`
             ).join("")}</div>`
          : `<div class="stnone">还没有搜过任何词</div>`}
        ${emptyWords.length
          ? `<div class="stnote">这 ${num(hs.empty)} 个词一本都没搜到 —— 多半是书库还没覆盖：</div>
             <div class="stchips">${emptyWords.map(w =>
               `<span class="stchip bad">${esc(w)}</span>`).join("")}</div>`
          : `<div class="stnone">还没有"搜不到"的词</div>`}
        <button class="mini" data-act="clrh">清空搜索历史</button>
      </div>

      <div class="stsec">
        <div class="sth">访问 <span>今天最常打开的接口</span></div>
        ${topPaths.length
          ? `<div class="stchips">${topPaths.map(p =>
              `<span class="stchip">${esc(p.path)} <i>${num(p.n)}</i></span>`).join("")}</div>`
          : `<div class="stnone">今天还没有访问</div>`}
        <div class="stnote">
          下载进度、健康探测这类机器轮询计入访问数，但不占下面的明细 ——
          否则一屏全是心跳，看不出"谁真的打开了什么"。
        </div>
        ${rows.length ? `
          <div class="sth" style="margin-top:10px">最近来过</div>
          <div class="stlist">${rows.map(r => {
            const d = new Date((r.ts || 0) * 1000);
            const t = `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} `
              + `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
            return `<div class="strow${r.new ? " isnew" : ""}">
              <span class="t">${t}</span>
              <span class="p">${esc(r.path || "")}</span>
              <span class="w">${esc(r.ua || "")}</span>
              <span class="c${r.code >= 500 ? " bad" : ""}">${num(r.code)}</span>
            </div>`;
          }).join("")}</div>` : ""}
        <button class="mini" data-act="clrv">清空访问记录</button>
      </div>

      <div class="stnote" style="margin-top:14px">
        IP 已脱敏（只留前三段），不存 Cookie、不做跨站追踪 —— 只用来大致知道"有人在用"。
      </div>`;

    // 「大家都在搜」点一下直接复用主搜索流程 —— 不另写一套搜索逻辑，
    // 否则两个入口的埋点/历史记录 / 流式行为会漂移。
    // 做法：把词填回 #q 再派发回车，和用户自己敲完按回车走的是同一条路。
    $$("[data-hot]", body).forEach(el => {
      el.onclick = () => {
        const q = $("#q");
        if (!q) return;
        q.value = el.dataset.hot || "";
        // 收起抽屉，否则会盖在结果上（用户点了词却看不见搜出来的东西）。
        // 走 openDrawer 挂在宿主节点上的 __wbClose（它会解绑 document 上的
        // Esc 监听），不要直接 remove() —— 那会留下孤儿监听（util.js 有详述）。
        const host = document.getElementById("srcDrawer");
        if (typeof host?.__wbClose === "function") { try { host.__wbClose(); } catch {} }
        q.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      };
    });
    const clrh = $("[data-act=clrh]", body);
    if (clrh) clrh.onclick = async () => {
      if (!(await confirmBox({
        title: "清空搜索历史？",
        message: "搜过的词会全部忘掉，无法恢复。",
        okText: "清空", danger: true,
      }))) return;
      try { await api.del("/api/history/search"); toast("搜索历史已清空"); renderStats(); }
      catch (e) { toast("清空失败：" + e.message, "err"); }
    };
    const clrv = $("[data-act=clrv]", body);
    if (clrv) clrv.onclick = async () => {
      if (!(await confirmBox({
        title: "清空访问记录？",
        message: "今日/累计的访问与来客数都会归零，无法恢复。",
        okText: "清空", danger: true,
      }))) return;
      try { await api.del("/api/visits"); toast("访问记录已清空"); renderStats(); }
      catch (e) { toast("清空失败：" + e.message, "err"); }
    };
  } catch (e) {
    if (fresh(my)) body.innerHTML = `<div class="errtext">读取统计失败：${esc(e.message)}</div>`;
  }
}

export function openSources(initialTab = "") {
  if (initialTab === "stats" || initialTab === "registry" || initialTab === "check") tab = initialTab;
  const existing = document.getElementById("srcDrawer");
  if (existing) { renderTab(); setHash(tab === "registry" ? "#registry" : tab === "stats" ? "#stats" : "#sources"); return; }
  openDrawer({
    id: "srcDrawer",
    title: "来源",
    body: `<div id="srcTabs">
        <button class="stab on" data-tab="check">实时检测</button>
        <button class="stab" data-tab="registry">来源库</button>
        <button class="stab" data-tab="stats">统计</button>
      </div>
      <div class="shint" id="srcHint"></div>
      <div id="srcBody"></div>`,
    actions: `<button class="iconbtn" id="srcAgainH" title="刷新">↻</button>`,
    onMount: d => {
      $$("#srcTabs .stab", d.el).forEach(b => b.onclick = () => {
        tab = b.dataset.tab;
        setHash(tab === "registry" ? "#registry" : tab === "stats" ? "#stats" : "#sources");
        renderTab();
      });
      $("#srcAgainH", d.el).onclick = () => renderTab();
      renderTab();
    },
  });
  setHash(tab === "registry" ? "#registry" : tab === "stats" ? "#stats" : "#sources");
}
