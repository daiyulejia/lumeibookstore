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
