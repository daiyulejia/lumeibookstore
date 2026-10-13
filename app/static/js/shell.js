/* ==========================================================================
   外壳：导航、顶栏 / 底部标签栏、主题面板
   ========================================================================== */

import { $, $$, esc, api, toast, bus, openDrawer, PRE, TOKEN } from "./util.js";
import { themePanelHTML, bindThemePanel, applyTheme, currentThemeId, THEMES } from "./theme.js";

let current = "home";
const hooks = {};

/** 注册「切到某个视图时要干什么」。避免 shell 反向依赖各业务模块。 */
export function onNav(name, fn) { hooks[name] = fn; }

export function nav(name) {
  current = name;
  $$("[data-nav]").forEach(b => b.classList.toggle("on", b.dataset.nav === name));
  ["home", "shelf", "files"].forEach(v => {
    const el = $("#view-" + v);
    if (el) el.classList.toggle("hidden", v !== name);
  });
  // 顺便把 hash 也写上，这样浏览器前进/后退能跟着走，
  // 也能和 main.js 里的 hashchange 处理器对上（它靠比对 hash 判断是否要重跑路由）。
  // ⚠ 用 replaceState 而不是直接 location.hash —— 后者会触发 hashchange，
  // 和 bootRoute() 形成一次多余的往返（点击 → 路由 → 再触发一次路由）。
  const want = name === "home" ? location.pathname : "#" + name;
  try { history.replaceState(null, "", want); } catch {}
  hooks[name]?.(name);
}

export function currentView() { return current; }

/* ---------- 主题面板 ---------- */
export function openTheme() {
  const existing = document.getElementById("themeDrawer");
  if (existing) return;
  openDrawer({
    id: "themeDrawer",
    title: "外观",
    body: `<div id="themeBody">${themePanelHTML()}</div>`,
    onMount: d => {
      bindThemePanel($("#themeBody", d.el), () => {
        // 换主题后把目录/底部栏的强调色也同步过去
        bus.emit("theme:changed", currentThemeId());
      });
    },
  });
}

/* ---------- 令牌 ---------- */
/* ⚠ 这里以前整块是行内 style —— 主题层完全够不到。
   而且 🔒 emoji 和整站气质不搭。现在改成 `.gate` 类组件，
   并复用空状态插画（`empty_wait`：噜噜在等人来 —— 正好对应"等你输令牌"）。 */
function showAuthGate() {
  // ⚠ 防叠层：`bootstrapAuth` 在「401 → 重试 → 仍然 401」等路径上可能被多次调用
  //   （开两个标签页、或网络抖一下就重进一次）。每次都 `appendChild` 一个新遮罩
  //   的结果是**三四个输入框叠在一起**，用户输完按回车，只有最上面那个消失，
  //   下面还压着 —— 看起来像"令牌输对了也进不去"。已经有一个就别再造。
  if (document.querySelector(".gate")) return;
  const d = document.createElement("div");
  d.className = "drawer-host";
  d.innerHTML = `
    <div class="mask"></div>
    <div class="gate" role="dialog" aria-modal="true" aria-label="需要访问令牌">
      <div class="gate-art"><img src="/static/img/lumei/empty_wait@480.webp"
        width="480" height="360" alt="" loading="eager" decoding="async"></div>
      <h3 class="gate-t">需要访问令牌</h3>
      <p class="gate-p">
        这个地址是从<b>公网</b>打开你的书库的，所以要验一下身份。
        令牌在这几个地方都能找到：
      </p>
      <ul class="gate-l">
        <li>电脑上程序目录里的 <code>远程访问.txt</code> —— 开了通道就会自动更新，
            里面有<b>当前能直接打开的完整链接</b>和令牌</li>
        <li>程序的启动窗口（终端）里，开头就打印了一行「访问令牌」</li>
        <li>界面上顶栏的「网络」面板，里面能直接复制</li>
      </ul>
      <p class="gate-hint">
        小提示：开通道时给的那条链接<b>本身就带了令牌</b>，把整条收藏起来，
        下次直接打开就行，不用记这串字符。
      </p>
      <input id="tokIn" type="text" placeholder="粘贴访问令牌" autocomplete="off" spellcheck="false"/>
      <div class="gate-a">
        <button class="btn primary" id="tokGo">进入</button>
      </div>
    </div>`;
  document.body.appendChild(d);

  const go = async () => {
    const v = $("#tokIn").value.trim();
    if (!v) return;
    TOKEN.set(v);
    try {
      const r = await api.get("/api/auth?t=" + encodeURIComponent(v));
      if (r.ok) { d.remove(); location.reload(); }
      else toast("令牌不对", "err");
    } catch {
      TOKEN.set("");
      toast("令牌不对", "err");
    }
  };
  $("#tokGo", d).onclick = go;
  $("#tokIn", d).addEventListener("keydown", e => { if (e.key === "Enter") go(); });
  setTimeout(() => $("#tokIn", d)?.focus(), 150);
}

/** 从链接里的 ?t=xxx 取令牌：分享出去的链接带令牌，进来一次就记住。 */
export async function bootstrapAuth() {
  const u = new URL(location.href);
  let t = u.searchParams.get("t");
  // ⚠ 兜底：`?t=` 可能被写在 `#` **后面**（`/` + `#shelf?t=x`）。
  //   那种情况下它属于 fragment，searchParams 根本看不到 ——
  //   于是令牌被静默丢掉、整站 401，而地址栏看着"明明带着令牌"。
  //   真踩过：写测试时把 `#shelf` 写在前面，7 项断言全红，
  //   排查很久才发现是"令牌放错位置"而不是功能坏了。
  //   用户分享 `#shelf` 深链时同样会踩，所以这里兜住。
  if (!t && u.hash.includes("t=")) {
    const h = new URLSearchParams(u.hash.replace(/^#/, "").replace(/^[^?]*/, ""));
    t = h.get("t");
  }
  if (t) {
    TOKEN.set(t);
    // 从地址栏抹掉 —— 不然令牌会留在浏览器历史/别人看到的地址里
    u.searchParams.delete("t");
    // hash 里那份也要抹（否则刷新一次又会被再读一遍，永远清不掉）
    if (u.hash.includes("t=")) {
      u.hash = u.hash.replace(/([?&])t=[^&]*&?/, "$1").replace(/[?&]$/, "");
    }
    try { history.replaceState(null, "", u.pathname + u.search + u.hash); } catch {}
  }
  try {
    const r = await api.get("/api/auth");
    if (r.ok === false) showAuthGate();
  } catch (e) {
    if (e.status === 401) showAuthGate();
  } finally {
    // ⚠ 迁移桥：告诉 Vue 侧「令牌已就绪、可以发请求了」。
    //   必须在这里（而不是更早）置位 —— 令牌是上面 TOKEN.set() 写的，
    //   早于此置位就等于骗人：Vue 照样会发出不带 t= 的请求，线上 401。
    //   见 frontend/src/legacy/util.js 的 whenAuthReady()。
    window.__lumeiLegacy = Object.assign(window.__lumeiLegacy || {}, {
      authReady: true,
    });
  }
}

/* ---------- 挂载 ---------- */
export function mountShell() {
  $$("[data-nav]").forEach(b => b.onclick = () => nav(b.dataset.nav));

  $("#btnTheme").onclick = openTheme;
  $("#btnSources").onclick = () => bus.emit("ui:sources");
  $("#btnAdapt").onclick = () => bus.emit("ui:adapt");
  $("#btnNet").onclick = () => bus.emit("ui:net");
  $("#btnTasks").onclick = () => bus.emit("ui:tasks");

  // 快捷键：输入框里不响应，否则打字会误触
  document.addEventListener("keydown", e => {
    if ($("#reader").classList.contains("on")) return;
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea") return;
    if (e.key === "/") { e.preventDefault(); $("#q")?.focus(); nav("home"); }
  });

  bus.on("auth:required", showAuthGate);
}

export function mountThemeMeta() {
  // 让手机状态栏颜色跟着主题走（applyTheme 里已处理 theme-color）
  applyTheme();
  window.matchMedia("(prefers-color-scheme: dark)");
}
