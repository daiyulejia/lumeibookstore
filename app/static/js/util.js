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
  on(ev, fn) {
    if (!_subs.has(ev)) _subs.set(ev, []);
    _subs.get(ev).push(fn);
  },
  emit(ev, data) {
    (_subs.get(ev) || []).forEach(fn => { try { fn(data); } catch (e) { console.error(e); } });
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
  async get(u) { return handle(await fetch(withToken(u))); },
  async post(u, body) {
    return handle(await fetch(withToken(u), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }));
  },
  async del(u) { return handle(await fetch(withToken(u), { method: "DELETE" })); },
  /** 原始 URL（用于 <a download> / 流式接口），带令牌。 */
  url(u) { return withToken(u); },
  async stream(u) { return fetch(withToken(u)); },
};

/* ---------- Toast ---------- */
export function toast(msg, kind) {
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
