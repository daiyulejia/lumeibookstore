/**
 * Vue 应用入口
 * ==========================================================================
 * 这个文件是**新的**前端入口，与旧的 `app/static/js/main.js` 并存。
 *
 * 迁移策略（用户确认：先搭骨架、逐页迁移）：
 *   每迁完一块，就在那块容器的父级标上 `data-vue-<名字>`，
 *   由这里按标记**逐个挂载**对应组件；没标的块继续走旧代码。
 *
 * ⚠ 为什么是"多容器各挂各的"而不是"一个 App 挂到某一个 #vue-root"：
 *   第一版是单挂载点（`#vue-root` 放在榜单区里），结果书架组件
 *   **渲染进了榜单区内部** —— Vue 只能把整棵 App 树渲染到那一个元素里，
 *   `#view-shelf` 里的 `#vue-root-shelf` 永远是空的（页面看着"没生效"，
 *   但控制台一点错都没有，极难定位）。
 *   页面里本来就有多个互不相邻的挂载区（榜单在首页、书架在 #view-shelf），
 *   所以必须是"一个容器一个 app 实例"。
 *
 * 代价：多个 app 实例，各自持有一份 Naive 的 config-provider —— 可接受
 *   （主题都是同一套 CSS 变量，不存在两份状态）。
 * 收益：迁移粒度干净，"迁一块挂一块"，互不影响，随时可回退。
 */
import { createApp } from "vue";
import App from "./App.vue";
import { installLumeiTheme } from "./theme/naive.js";

/**
 * 在页面上找所有"交给 Vue"的容器，各挂一个 app。
 *
 * 约定：容器自己带 `data-vue` 属性的值就是**组件名**（跟 App.vue 里
 * 注册的名字一致）。这样加一块新页面时，只要在某处放一个
 * `<div data-vue="ShelfPanel"></div>`，这边不用改代码。
 */
const MOUNTS = [
  { name: "RanksPanel", sel: "[data-vue-ranks]" },
  { name: "ShelfPanel", sel: "[data-vue-shelf]" },
  { name: "FilesPanel", sel: "[data-vue-files]" },
  { name: "DiscoverPanel", sel: "[data-vue-discover]" },
];

let mounted = 0;
for (const m of MOUNTS) {
  const hosts = document.querySelectorAll(m.sel);
  hosts.forEach((host) => {
    // 容器里的那个真正挂载点：优先用 host 自己，没有子容器时就用它。
    const target = host.firstElementChild || host;
    const app = createApp(App, { only: m.name });
    installLumeiTheme(app);
    app.mount(target);
    mounted++;
  });
}

if (!mounted) {
  // 没找到任何挂载点说明当前页面还没迁过来 —— 静默跳过，不影响旧代码
  console.info("[lumei] 没有找到 Vue 挂载点，跳过（该页尚未迁移）");
}
