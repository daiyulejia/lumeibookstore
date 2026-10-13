/**
 * legacy/motion.js · 桥接旧动效层
 * ==========================================================================
 * 动效层（motion.js）无状态、纯函数，直接复用旧实现即可 ——
 * 但要**运行期取**（同 util.js 的理由），避免两份模块实例。
 *
 * 为什么错峰不重写：项目有一个约定 ——
 *   「错峰统一走 stagger()，业务代码不许写行内 animation-delay」
 * （见 tools/test_motion.py 的静态断言）。
 * Vue 组件也要守这条约定，否则那套测试和这套新代码会打架。
 */
function pick(name) {
  const v = window.__lumeiLegacy && window.__lumeiLegacy[name];
  if (!v) throw new Error(`[lumei] 旧模块 ${name} 未挂到 window.__lumeiLegacy`);
  return v;
}

export function stagger(root, sel) {
  return pick("stagger")(root, sel);
}
