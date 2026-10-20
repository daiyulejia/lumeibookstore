/* ==========================================================================
   基础工具层
   ========================================================================== */

export const $  = (s, r) => (r || document).querySelector(s);
export const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

/** HTML 转义。所有插入 innerHTML 的动态文本都必须过这一层。 */
export const esc = s => String(s == null ? "" : s)
  .replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));

export const fmtSize = n =>
  n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : (n / 1048576).toFixed(1) + " MB";

export const fmtTime = t => {
  const d = new Date(t * 1000), p = x => String(x).padStart(2, "0");
  return `${d.getMonth() + 1}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

export const fmtLeft = t => {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - t));
  if (s < 60) return "刚刚";
  if (s < 3600) return Math.floor(s / 60) + " 分钟前";
  if (s < 86400) return Math.floor(s / 3600) + " 小时前";
  return Math.floor(s / 86400) + " 天前";
};

export const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

export const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

/** 简易节流：用于滚动 / 拖拽等高频回调。 */
export const throttle = (fn, ms) => {
  let last = 0, timer = null;
  return (...a) => {
    const now = Date.now();
    if (now - last >= ms) { last = now; fn(...a); }
    else if (!timer) timer = setTimeout(() => { timer = null; last = Date.now(); fn(...a); }, ms - (now - last));
  };
};

/* ---------- 偏好存储 ---------- */
export const PRE = {
  get(k, d) { try { const v = localStorage.getItem("nd_" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("nd_" + k, JSON.stringify(v)); } catch {} },
  del(k) { try { localStorage.removeItem("nd_" + k); } catch {} },
};

/* ---------- 事件总线 ----------
   跨模块通信用它，而不是互相 import。
   例：shelf 需要知道「阅读器关了要刷新」，但它不该 import reader。 */
const _subs = new Map();
export const bus = {
  /**
   * 订阅。**返回一个退订函数**（调它等于 bus.off(ev, fn)）。
   *
   * ⚠ 为什么要有返回值：Vue 组件里最自然的写法是
   *     `const off = bus.on("x", fn); ... onUnmounted(() => off())`。
   *   如果 on 不返回东西，`off` 就是 undefined —— `onUnmounted` 里
   *   `off && off()` 静默什么都不做，**监听泄漏且毫无报错**
   *   （真踩过：RanksPanel 的 off1/off2 一直是 undefined）。
   *   返回退订函数是这件事唯一不容易写错的接口。
   */
  on(ev, fn) {
    if (!_subs.has(ev)) _subs.set(ev, []);
    _subs.get(ev).push(fn);
    return () => bus.off(ev, fn);
  },
  /* 摘掉监听。
     ⚠ 为什么必须补这个（原来只有 on/emit）：Vue 组件迁进来之后，
       组件会**随页面切换反复挂载/卸载**。旧代码是一次性 mount、
       永不卸载，所以没有 off 也一直没暴露问题；组件一旦卸载却留着
       监听，切回来再挂一次就是**第二份**监听 ——
       表现是"缓存跑完书架刷了两遍 / 阅读器关闭后刷了两次"，
       而且每次来回切都多一份，越来越慢。 */
  off(ev, fn) {
    const arr = _subs.get(ev);
    if (!arr) return;
    if (!fn) { _subs.delete(ev); return; }
    const i = arr.indexOf(fn);
    if (i >= 0) arr.splice(i, 1);
    if (!arr.length) _subs.delete(ev);
  },
  emit(ev, data) {
    // 复制一份再遍历：回调里如果调了 off（很可能，比如"只响应一次"），
    // 直接遍历原数组会因为 splice 而漏掉后面那几个监听者。
    (_subs.get(ev) || []).slice().forEach(fn => {
      try { fn(data); } catch (e) { console.error(e); }
    });
  },
};

/* ---------- 访问令牌 ----------
   一旦把服务暴露到公网（内网穿透），没有令牌就等于把书库送人。
   令牌存在 localStorage，随每个请求带上；服务端没开鉴权时它就是个空值。 */
export const TOKEN = {
  get() { return PRE.get("token", ""); },
  set(v) { PRE.set("token", v || ""); },
};

/* ---------- HTTP ---------- */
class ApiError extends Error {
  constructor(msg, status) { super(msg); this.status = status; }
}

function withToken(url) {
  const t = TOKEN.get();
  if (!t) return url;
  return url + (url.includes("?") ? "&" : "?") + "t=" + encodeURIComponent(t);
}

async function handle(r) {
  if (r.status === 401) {
    bus.emit("auth:required");
    throw new ApiError("需要访问令牌", 401);
  }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(d.error || ("HTTP " + r.status), r.status);
  return d;
}

export const api = {
  async get(u, opts) { return handle(await fetch(withToken(u), opts)); },
  async post(u, body, opts) {
    return handle(await fetch(withToken(u), {
      method: "POST",
      ...(opts || {}),
      // headers 放最后单独合并：调用方给的 signal 等字段不该把 Content-Type 挤掉
      headers: { "Content-Type": "application/json", ...((opts && opts.headers) || {}) },
      body: JSON.stringify(body || {}),
    }));
  },
  async del(u, opts) { return handle(await fetch(withToken(u), { method: "DELETE", ...(opts || {}) })); },
  /** 原始 URL（用于 <a download> / 流式接口），带令牌。 */
  url(u) { return withToken(u); },
  /**
   * 流式接口（NDJSON）。
   * ⚠ opts 必须能带 `signal` —— 否则调用方的 `AbortController.abort()` 是空操作，
   * 被顶掉的旧请求永远不会停，两个流会同时往同一个容器里写、互相覆盖。
   * （实测踩过：discover.js 里 abort 了但 fetch 根本没收 signal。）
   */
  async stream(u, opts) { return fetch(withToken(u), opts); },
};

/* ---------- Toast ---------- */
export function toast(msg, kind) {
  // ⚠ 令牌门在场时，不再弹"需要访问令牌"的红条。
  //   实测（线上、不带 t= 直接打开）：门弹出来的同时，书架/文件各弹一条
  //   "读取书架失败：需要访问令牌"，三条红条正压在门的输入框上 ——
  //   用户想粘贴令牌都点不到，整页又被半透明遮罩蒙着，观感就是"挂了"。
  //   门已经把该说的话说清楚了，**令牌相关的提示统一由门负责**。
  //   注意别用 /令牌/ 做判据："令牌不对"必须照常弹出来（那是门里的反馈）。
  if (kind === "err" && /需要访问令牌/.test(String(msg))
      && document && document.querySelector(".gate")) return;
  const el = document.createElement("div");
  el.className = "toast" + (kind ? " " + kind : "");
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => {
    el.style.transition = "opacity .3s,transform .3s";
    el.style.opacity = "0";
    el.style.transform = "translateY(8px)";
    setTimeout(() => el.remove(), 320);
  }, kind === "err" ? 4200 : 2600);
}

/* ---------- 抽屉 ----------
   统一样式 + 统一关闭动画。之前每个抽屉各写一遍，行为不一致
   （有的立刻消失、有的没遮罩点击关闭、有的 Esc 关不掉）。 */
export function openDrawer({ id, title, body, actions, onMount, side = "" }) {
  let d = document.getElementById(id);
  if (d) {
    // ⚠ 直接 `d.remove()` 会**留下孤儿监听**：上一条 `document.addEventListener
    //   ("keydown", onKey)` 是挂在 document 上的，删 DOM 不会解绑它 ——
    //   只有 `close()` 里的 removeEventListener 会，而这条路径绕过了 close()。
    //   后果：同一个抽屉反复开（点「来源」面板 N 次），按一次 Esc 会触发 N 个
    //   回调，每个都去操作**已经被移除的**旧抽屉（`$(".mask", d)` 返回 null，
    //   被 `?.` 吞掉），然后 emit N 次 `drawer:closed` —— 监听方（比如 reader
    //   刷新目录）就被无意义地跑了 N 遍。先手动收尾再删。
    if (typeof d.__wbClose === "function") { try { d.__wbClose(); } catch {} }
    d.remove();
  }

  d = document.createElement("div");
  d.id = id;
  d.className = "drawer-host";
  d.innerHTML = `
    <div class="mask" data-close></div>
    <aside class="drawer ${side}" role="dialog" aria-modal="true">
      <header>
        <h3>${esc(title)}</h3>
        ${actions || ""}
        <button class="iconbtn" data-close aria-label="关闭">✕</button>
      </header>
      <div class="body">${body || ""}</div>
    </aside>`;
  document.body.appendChild(d);

  const close = () => {
    const mask = $(".mask", d), dr = $(".drawer", d);
    mask?.classList.add("closing");
    dr?.classList.add("closing");
    setTimeout(() => d.remove(), 240);
    document.removeEventListener("keydown", onKey);
    d.__wbClose = null;
    bus.emit("drawer:closed", id);
  };
  const onKey = e => { if (e.key === "Escape") close(); };
  // 把 close 挂到节点上，供"同一个抽屉被重新打开"时清理（见函数开头）。
  d.__wbClose = close;

  $$("[data-close]", d).forEach(b => b.onclick = close);
  document.addEventListener("keydown", onKey);

  const api_ = { el: d, close, body: $(".body", d), header: $("header", d) };
  onMount?.(api_);
  return api_;
}

/** 给「危险操作」用的确认框。原生 confirm() 在手机上丑且会被部分浏览器拦。
 *
 * ⚠ 以前这里的样式**全是行内 style** —— 结果主题层根本够不到它
 *   （`lumei.css` 只能改类选择器，改不动行内）。而且行内样式
 *   写不了 `:hover` / `prefers-reduced-motion` / 媒体查询。
 *   现在改成 `.cfm-*` 类，样式进 app.css + lumei.css。
 */
export function confirmBox({ title, message, okText = "确定", danger = false }) {
  return new Promise(resolve => {
    const d = document.createElement("div");
    d.className = "drawer-host";
    d.innerHTML = `
      <div class="mask cfm-mask" data-close></div>
      <div class="cfm" role="alertdialog" aria-modal="true" aria-label="${esc(title)}">
        <h3 class="cfm-t">${esc(title)}</h3>
        <p class="cfm-m">${esc(message)}</p>
        <div class="cfm-a">
          <button class="btn ghost" data-no>取消</button>
          <button class="btn ${danger ? "danger" : "primary"}" data-yes>${esc(okText)}</button>
        </div>
      </div>`;
    document.body.appendChild(d);
    const done = v => { d.remove(); resolve(v); };
    $$("[data-close],[data-no]", d).forEach(b => b.onclick = () => done(false));
    $("[data-yes]", d).onclick = () => done(true);
    // 打开后把焦点交给「确定」那一侧的相邻按钮（取消）——
    // 让键盘用户不用先 Tab 一遍才够得着。危险操作不自动聚焦"确定"（防误按回车）。
    $("[data-no]", d)?.focus();
    document.addEventListener("keydown", function k(e) {
      if (e.key === "Escape") { document.removeEventListener("keydown", k); done(false); }
    });
  });
}

/** 复制文本。http 非 localhost 时剪贴板 API 会被拒，所以要退回老办法。 */
export async function copyText(s) {
  try { await navigator.clipboard.writeText(s); return true; }
  catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = s; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return ok;
    } catch { return false; }
  }
}

/* ==========================================================================
   迁移桥 · 把本模块的关键对象挂到 window，供新的 Vue 侧复用
   --------------------------------------------------------------------------
   为什么要有它：项目正在「分页迁移到 Vue3 + Naive UI」（见 frontend/）。
   Vue 侧需要 $ / esc / api / bus / PRE 这些**同一份实例** ——
   如果让 Vite 把 util.js 打进产物，运行期就会存在两个模块实例，
   最要命的是 `bus` 会有两个：Vue 侧 emit、旧侧收不到（幽灵 bug）。

   所以约定：**旧模块在运行期把导出挂到 window.__lumeiLegacy**，
   Vue 侧只取引用、不重新打包（见 frontend/src/legacy/util.js）。

   等全部页面迁完、旧代码删掉时，这个桥和 legacy/ 一起删。
   ========================================================================== */
window.__lumeiLegacy = Object.assign(window.__lumeiLegacy || {}, {
  $, $$, esc, fmtSize, fmtTime, PRE, bus, TOKEN, api, toast, confirmBox, copyText,
  debounce,
});
