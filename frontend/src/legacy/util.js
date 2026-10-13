/**
 * legacy/ · 迁移期的桥接层
 * ==========================================================================
 * 为什么需要这层：
 * 旧代码是**直接静态提供的 ES module**（`/static/js/util.js`），
 * 没有构建步骤。Vite 构建时如果直接 `import "../../app/static/js/util.js"`，
 * 它会被打进产物 —— 而那些文件又同时被旧的 main.js 加载，
 * 结果是二进制的两份副本（内存里两份模块实例）：
 *   · 事件总线 `bus` 会有**两个**，Vue 侧 emit、旧侧收不到（真踩过这类坑）
 *   · PRE / 缓存也不共享
 *
 * 所以这里的做法是：**不在构建期 import 旧文件，而是在运行期从 window 上取**。
 * 由旧的 util.js 在启动时把 `bus / api / PRE` 挂到 window（见下面 ensure()），
 * Vue 侧拿到的是**同一个实例**，两侧状态天然共享。
 *
 * 代价：需要旧代码暴露这几个对象。这比"两个 bus"的隐性 bug 划算得多。
 */

/** 从 window 上取旧代码的导出；没挂上就报一个清楚的错。 */
function pick(name) {
  const v = window.__lumeiLegacy && window.__lumeiLegacy[name];
  if (!v) {
    throw new Error(
      `[lumei] 旧模块 ${name} 还没挂到 window.__lumeiLegacy 上。` +
        `检查 app/static/js/util.js 是否已加桥接（迁移期必需）。`
    );
  }
  return v;
}

/** 工具：$ / esc / api / toast / PRE */
export const api = new Proxy(
  {},
  { get: (_t, k) => pick("api")[k] }
);
export const bus = new Proxy({}, { get: (_t, k) => pick("bus")[k] });

export function esc(s) {
  return pick("esc")(s);
}
export function $(sel, root) {
  return pick("$")(sel, root);
}
export function toast(msg, kind) {
  return pick("toast")(msg, kind);
}
export const PRE = new Proxy({}, { get: (_t, k) => pick("PRE")[k] });

export function confirmBox(opts) {
  return pick("confirmBox")(opts);
}
export function debounce(fn, ms) {
  return pick("debounce")(fn, ms);
}
/** 取某个旧模块暴露的东西（如 shelf.js 的 loadShelf）。 */
export function legacy(name) {
  return pick(name);
}

/**
 * 等到「旧代码完成了鉴权初始化」再继续。
 *
 * ⚠ 为什么必须有这个：页面用的是 `?t=<token>` 传令牌，
 * 而读这个参数、写进 PRE 的动作发生在旧代码的 `bootstrapAuth()` 里
 * （main.js 第 121 行，`await` 之前还有若干 mount）。
 * Vue 的入口是**另一个** `<script type="module">`，
 * 加载完就立刻 mount —— 于是组件的 onMounted 很可能跑在
 * bootstrapAuth() 之前，此时 `api.get()` 拼出来的 URL **不带令牌**，
 * 线上直接 401（本地因为 /api 不需要令牌，根本不复现）。
 *
 * 症状很隐蔽：本地一切正常、线上榜单区块整块不显示（组件拿到 401 就
 * 收起了容器），控制台只有一条被埋在埋点里的 401。
 *
 * 做法：轮询 window.__lumeiLegacy.authReady（旧代码在 bootstrapAuth
 * 完成后置位），最多等 8 秒兜底。
 */
export function whenAuthReady(timeoutMs = 8000) {
  return new Promise((resolve) => {
    const t0 = Date.now();
    const tick = () => {
      const L = window.__lumeiLegacy || {};
      // authReady 没被旧代码置位时（比如旧代码是老版本）也别死等 ——
      // 超时就放行，让组件照常发请求、失败了自己兜底。
      if (L.authReady || Date.now() - t0 > timeoutMs) {
        resolve(!!L.authReady);
        return;
      }
      setTimeout(tick, 60);
    };
    tick();
  });
}

/**
 * 订阅"旧代码推过来的状态快照"，并**支持多个订阅者**。
 *
 * ⚠ 为什么需要这层转发，而不是让每个组件各自调 `attachReader(apply)`：
 *   阅读器外壳被拆成**两个 Vue app 实例**（上半在 `.rd-stage` 之前、
 *   下半在之后 —— 因为 `#reader` 是纵向 flex，顺序即布局，而 Vue
 *   没法把节点插到"容器之后、下一个兄弟之前"）。
 *   旧代码的 `attachReader` 只保留**一个**回调；两个组件都调它的话，
 *   后一个会把前一个覆盖掉 —— 于是两个面板里只有一个能收到状态更新，
 *   而且是"后挂载的那个能收到"，表现是"上一章/下一章按钮永远灰着"这类
 *   看似无关的症状。
 *
 *   所以：**第一个**订阅者负责向旧代码注册，快照进来后广播给全部订阅者。
 *   这样上层（reader.js）保持"单一回调"的简单契约，组件侧可以随便拆。
 *
 * 返回退订函数（组件 onUnmounted 时调，避免热重载/来回切换时越积越多）。
 */
const _rdSubs = [];
let _rdRegistered = false;

/* 迁移期诊断计数：真机测试靠它区分"旧代码没推"和"Vue 没收到"。
   踩过：目录为空时完全看不出是哪一段断的 —— 旧代码可能压根没渲染，
   也可能渲染了但广播没到。加两个计数，一眼定位。 */
export const rdDebug = { snapshots: 0, last: null };

export function attachReaderSnapshot(apply) {
  _rdSubs.push(apply);
  if (!_rdRegistered) {
    const fn = window.__lumeiLegacy && window.__lumeiLegacy.attachReader;
    if (typeof fn === "function") {
      fn((st) => {
        rdDebug.snapshots++;
        rdDebug.last = st;
        for (const f of _rdSubs.slice()) { try { f(st); } catch { /* 单个订阅者出错不影响其它 */ } }
      });
      _rdRegistered = true;
    }
    // ⚠ 注册失败也要暴露出来：如果旧代码的桥还没挂（两个 module 并行加载），
    //   这里会静默拿不到 —— 表现就是"Vue 永远收不到状态"。
    rdDebug.registered = _rdRegistered;
  }
  return () => {
    const i = _rdSubs.indexOf(apply);
    if (i >= 0) _rdSubs.splice(i, 1);
  };
}

/**
 * 调旧代码暴露的函数；不存在就静默跳过。
 *
 * ⚠ 迁移期必须"静默"：页面里两个 `<script type="module">` **并行**加载，
 *   Vue 组件可能比旧代码的桥先就绪。此刻用户点了按钮，应该什么都不做，
 *   而不是抛一个 `undefined is not a function` 把控制台刷红。
 */
export function callLegacy(name, ...args) {
  const fn = window.__lumeiLegacy && window.__lumeiLegacy[name];
  if (typeof fn === "function") return fn(...args);
  return undefined;
}

// 迁移期诊断：把阅读器桥的状态挂到 window，真机测试可以直接读，
// 不必为了看一个计数而临时改代码。（只读，不影响任何行为。）
if (typeof window !== "undefined") {
  window.__lumeiRdDebug = rdDebug;
}

