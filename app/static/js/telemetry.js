/* ==========================================================================
   前端埋点 —— 把「浏览器里发生的事」回传到服务端日志
   ==========================================================================

   为什么需要它
   ------------
   后端日志再全，也照不到这三类问题 —— 而它们恰恰是最常见的用户报障：

     · 点了没反应（JS 抛异常，动作链断了）
     · 页面白屏 / 卡死（未捕获的 Promise 拒绝）
     · 「搜了半天没结果」（接口 500 了，但前端只是安静地转圈）

   以前这些一个都不上报，用户说"搜不出来"时，服务端日志一片空白，
   只能靠猜。现在它们会带着**页面路径 + 堆栈 + 客户端**落进 logs/app.log：

       grep 'ui.error' logs/app.log
       grep 'ui.api.fail' logs/app.log

   设计约束
   --------
   · **绝不打扰用户**：上报失败就悄悄算了，不 toast、不再抛。
   · **绝不打转圈**：同一类错误做去重 + 上限（默认 20 条/次会话），
     否则一个在渲染循环里报的错能瞬间刷爆日志。
   · **不阻塞业务**：用 navigator.sendBeacon（浏览器会自己找时机发），
     不支持时退回 fetch + keepalive。
   ========================================================================== */

const ENDPOINT = "/api/log";

/* 本次会话已上报的条数 + 去重集合。刷新页面即重置 —— 这正是我们要的粒度
   （持续复现的问题每次会话都会报，偶发的一次就够）。 */
let _sent = 0;
const _seen = new Set();
const MAX_SENT = 20;

/* 慢接口阈值：超过这个毫秒数的接口成功也记一笔，用来找"为什么这么慢"。 */
const SLOW_MS = 6000;

function payload(event, message, stack, extra) {
  return JSON.stringify({
    event,
    message: String(message == null ? "" : message).slice(0, 300),
    stack: String(stack || "").slice(0, 600),
    url: (location.pathname + location.search).slice(0, 200),
    ua: navigator.userAgent || "",
    extra: String(extra || "").slice(0, 160),
  });
}

/* 真正发出去。sendBeacon 是首选 —— 它在页面正在卸载时也能把请求发完，
   而这正是「白屏前最后一个错误」最常见的时刻。 */
function send(event, message, stack, extra) {
  if (_sent >= MAX_SENT) return;
  const key = event + "|" + message;
  if (_seen.has(key)) return;
  _seen.add(key);
  _sent += 1;

  const body = payload(event, message, stack, extra);
  try {
    if (navigator.sendBeacon) {
      // sendBeacon 的 body 只认 Blob/字符串；用 Blob 才能指定 content-type
      const blob = new Blob([body], { type: "application/json" });
      if (navigator.sendBeacon(ENDPOINT, blob)) return;
    }
    fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    }).catch(() => {});
  } catch {
    /* 上报本身失败就算了 —— 绝不能让"记录错误"变成新的错误 */
  }
}

/** 手动记一笔（业务代码里想留痕时用）。 */
export function track(event, message, extra) {
  send(event, message, "", extra);
}

/** 装全局钩子。在 main.js 最早期调一次。 */
export function installTelemetry() {
  // ① 未捕获的同步错误
  window.addEventListener("error", e => {
    // 资源加载失败（img/script）也会走这里，但 e.error 为空、e.message 是
    // 泛泛的 "Script error."；有 e.error 的才是真 JS 异常，只报那种。
    if (e && e.error) {
      send("ui.error", e.message || String(e.error),
           (e.error && e.error.stack) || "", (e.filename || "") + ":" + (e.lineno || 0));
    }
  });

  // ② 未处理的 Promise 拒绝 —— 最常见的"点了没反应"，因为 async 函数里
  //    抛出的错在没人 await 时会静默消失，界面上什么都看不出来。
  window.addEventListener("unhandledrejection", e => {
    const r = e && e.reason;
    const msg = r && r.message ? r.message : String(r);
    const st = r && r.stack ? r.stack : "";
    send("ui.reject", msg, st, "");
  });

  // ③ 顺手给 fetch 记一笔耗时/失败 —— 覆盖"接口挂了但界面没提示"的情况。
  //    ⚠ 只观测，不改写行为：包一层后原样返回原 Promise。
  const rawFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    // 别把自己上报的请求也包进去（会递归、且没意义）
    if (url.includes(ENDPOINT)) return rawFetch(input, init);
    const t0 = Date.now();
    const p = rawFetch(input, init);
    p.then(r => {
      const dt = Date.now() - t0;
      if (!r.ok && r.status !== 401) {   // 401 会走令牌闸门，不是 bug
        send("ui.api.fail", "HTTP " + r.status, "", url.slice(0, 120) + " " + dt + "ms");
      } else if (dt >= SLOW_MS) {
        send("ui.slow", "接口耗时 " + dt + "ms", "", url.slice(0, 120));
      }
    }).catch(err => {
      // 主动 abort 的不算错误（那是用户连点搜索，正常行为）
      if (err && err.name === "AbortError") return;
      const dt = Date.now() - t0;
      send("ui.api.fail", (err && err.message) || "请求失败", "", url.slice(0, 120) + " " + dt + "ms");
    });
    return p;
  };
}
