/**
 * Vue 应用入口
 * ==========================================================================
 * 这个文件是**新的**前端入口，与旧的 `app/static/js/main.js` 并存。
 *
 * 迁移策略（用户确认：先搭骨架、逐页迁移）：
 *   第一阶段只把「发现页的榜单区」搬进 Vue，其余页面继续走旧代码。
 *   所以这里有意**不接管整页** —— 只挂载到一个容器上，
 *   旧代码仍然照常跑。等某一页完全迁完再摘掉旧的。
 *
 * 为什么不做「Vue 接管整页」：
 *   现有代码有 100+ 项自动化断言（tools/test_*.py），
 *   一次性接管会让它们大面积失效。分页迁移能保证每一步都可上线、可回滚。
 */
import { createApp } from "vue";
import App from "./App.vue";
import { installLumeiTheme } from "./theme/naive.js";

/** 挂载点：由 index.html 里的一个空容器提供。 */
const el = document.getElementById("vue-root");

if (el) {
  const app = createApp(App);
  installLumeiTheme(app);
  app.mount(el);
} else {
  // 没找到挂载点说明当前页面还没迁过来 —— 静默跳过，不影响旧代码
  console.info("[lumei] 未找到 #vue-root，跳过 Vue 挂载（该页尚未迁移）");
}
