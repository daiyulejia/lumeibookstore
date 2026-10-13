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
