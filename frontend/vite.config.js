/**
 * 噜妹书院 · 前端构建配置
 * ==========================================================================
 * 这个项目的服务器是**纯 Python 静态服务**（FastAPI + StaticFiles），
 * 不跑 Node。所以构建产物必须落到 `app/static/` 里，由 Python 直接端出去。
 *
 * 三个必须遵守的硬约束（每一条都是踩出来的）：
 *
 * 1) 产物路径必须出现在 `app/static/index.html` 里。
 *    `tools/sync_cloud.py` 上线时会用正则从 index.html 里抠出
 *    `href="/static/..."` / `src="/static/..."`，然后**逐个请求验证 200**，
 *    只要有一个 404 就判定上线失败。所以 Vite 产出的文件名必须写进 index.html。
 *
 * 2) 产物的顶层目录要避开 `js / css / vendor`。
 *    `app/main.py` 的 `_asset_version()` 只扫 `_ASSET_DIRS = ("js","css","vendor")`
 *    的**顶层文件**拿 mtime 做版本号。产物是哈希文件名 + 深目录，
 *    混进去会让版本号算错（改了前端但版本号没变 → 用户拿到旧缓存）。
 *    这里统一放 `app/static/dist/`，与那三个目录隔离，互不影响。
 *
 * 3) 不能用 hash 命名之外的花哨路径。
 *    `/api/health` 之外，服务器对 `/static/**` 是纯静态映射，
 *    子目录随便建；但为保持可读性，这里把 assets 放在 dist/assets/。
 *
 * 输出策略：**不写 manifest、不带 modulepreload 的复杂产物**，
 * 只产一个 css + 一个 js + 需要的话一份 chunk，方便 index.html 手工/脚本引用。
 */
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";

const STATIC_DIR = fileURLToPath(new URL("../app/static/", import.meta.url));

export default defineConfig({
  plugins: [vue()],

  // 源码在 frontend/src/，产物直接落进 Python 的静态目录
  root: fileURLToPath(new URL("./", import.meta.url)),

  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },

  build: {
    // 产物直接落进 Python 的静态目录下的 dist/ 子目录。
    // ⚠ 必须是 dist/ 而不是 js/ 或 css/ —— main.py 的 _asset_version()
    //   只扫那三个目录的顶层文件算 mtime，产物混进去会让版本号算错。
    outDir: fileURLToPath(new URL("../app/static/dist/", import.meta.url)),
    emptyOutDir: true,
    // 产物不用再转译到很老的语法 —— 这是自己内网用的工具，现代浏览器即可
    target: "es2020",
    // 不压缩到不可读：出问题时线上要能看源码定位（这是自用工具，体积不敏感）
    minify: false,
    // 关掉 sourcemap 文件产出（体积大且服务器上没用，行号靠不压缩就够）
    sourcemap: false,
    cssCodeSplit: false,
    rollupOptions: {
      input: fileURLToPath(new URL("./src/main.js", import.meta.url)),
      /**
       * ⚠ 不要在这里把 `/static/**` 配成 external —— 踩过，后果很重。
       *
       * 症状：源码里写 `<img src="/static/img/xxx.webp">` 时
       *   @vitejs/plugin-vue 会把 src 当模块引用交给 rollup，
       *   不处理就报 "failed to resolve import"，构建直接失败。
       *   于是有人（我）顺手加了 external → 构建过了，但产物里留下
       *   `import x from "/static/img/xxx.webp";` —— 浏览器把 webp
       *   当 JS 模块去加载，**整份 vue-app.js 都执行不了**：
       *   连没改过的榜单区也一起白屏，控制台还只有一句
       *   "Failed to fetch dynamically imported module"，极难定位。
       *
       * 正确做法：**别在模板里引 /static 资源**。
       *   改用 CSS background（路径原样进样式表，绕开模块解析），
       *   见 ShelfPanel.vue 的 .empty-art。
       */
      output: {
        // 固定文件名 —— 版本靠 index.html 的 ?v= 查询串控制，
        // 不走内容哈希，这样 index.html 里的引用是稳定的，不用每次改 HTML。
        //
        // ⚠ 名字必须带 `vue-` 前缀。
        //   第一版叫 app.js/app.css，撞上了手写的 css/app.css ——
        //   产物在 dist/ 下虽然不覆盖它，但两个同名的东西摆在项目里，
        //   以后有人 grep/拷贝极易拿错（产物是不能手改的）。
        //   加前缀这件事写进 verify-dist.mjs 的断言里防回归。
        entryFileNames: "vue-app.js",
        chunkFileNames: "vue-chunk-[name].js",
        assetFileNames: (info) => {
          const n = info.names?.[0] || info.name || "";
          if (n.endsWith(".css")) return "vue-app.css";
          return "assets/[name][extname]";
        },
      },
    },
  },

  // 开发时（vite build --watch）不用 dev server，纯打包
  server: { port: 5273 },
});
