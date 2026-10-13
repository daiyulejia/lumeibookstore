#!/usr/bin/env node
/**
 * verify-dist.mjs · 构建产物自检
 * ==========================================================================
 * 这个脚本守的是「Vite 产物能被现有 Python 服务正确端出去」这条链。
 * 每条断言都对应一个真实会出事的地方：
 *
 *  1) 产物存在（app/static/dist/vue-app.js + vue-app.css）
 *     —— 构建失败但没报错时，index.html 会引到 404，白屏。
 *
 *  2) index.html 引用了产物
 *     —— sync_cloud.py 从 index.html 抠 /static/... 逐个验 200，
 *        没被引用 = 不会被验证 = 上线了但页面白。
 *
 *  3) 产物**没有**混进 js/ css/ vendor/
 *     —— main.py 的 _asset_version() 扫这三个目录顶层文件算 mtime。
 *        混进去会让版本号算到产物上，改了手写 CSS 版本号却不变 → 用户拿旧缓存。
 *        （另外产物名带 vue- 前缀也是为这个：第一版叫 app.css，
 *          与手写的 css/app.css 同名，极易拿错文件。）
 *
 *  4) 产物里没有 import 一个不存在的 chunk
 *     —— 手动配了 entryFileNames 等固定名，chunk 拆分的假设变化时
 *        会产生悬空 import，浏览器报"Cannot find module"。
 *
 *  5) 产物里的 CSS 变量引用（var(--x)）在 tokens.css 里都有定义或带 fallback
 *     —— 组件级样式最容易写错变量名（--t-4 / --s-card-2 这类），
 *        写错不会报错、只是静默失效（字变黑/背景透明），很难发现。
 *
 * 用法：node tools/verify-dist.mjs   （由 npm run build:check 调用）
 */
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

// 本文件在 frontend/tools/，项目根要往上两级
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const STATIC = join(ROOT, "app", "static");
const DIST = join(STATIC, "dist");
const INDEX = join(STATIC, "index.html");

const JS_NAME = "vue-app.js";
const CSS_NAME = "vue-app.css";

let okN = 0;
let badN = 0;
const ok = (m) => { okN++; console.log(`  ✓ ${m}`); };
const bad = (m) => { badN++; console.log(`  ✗ ${m}`); };

console.log("=".repeat(62));
console.log("前端产物自检（Vite → app/static/dist）");
console.log("=".repeat(62));

/* 1. 产物存在 */
console.log("\n── 1. 产物文件 ──");
const JS = join(DIST, JS_NAME);
const CSS = join(DIST, CSS_NAME);
if (existsSync(JS)) ok(`${JS_NAME} 存在（${(statSync(JS).size / 1024).toFixed(0)} KB）`);
else bad(`${JS_NAME} 不存在 —— 构建没跑或失败了`);
if (existsSync(CSS)) ok(`${CSS_NAME} 存在（${(statSync(CSS).size / 1024).toFixed(0)} KB）`);
else bad(`${CSS_NAME} 不存在 —— 构建没跑或失败了`);

/* 2. index.html 引用了产物 */
console.log("\n── 2. index.html 引用了产物 ──");
const html = readFileSync(INDEX, "utf-8");
if (html.includes(`/static/dist/${JS_NAME}`)) ok(`index.html 引了 /static/dist/${JS_NAME}`);
else bad(`index.html 没引 ${JS_NAME} —— 页面不会加载 Vue 应用`);
if (html.includes(`/static/dist/${CSS_NAME}`)) ok(`index.html 引了 /static/dist/${CSS_NAME}`);
else bad(`index.html 没引 ${CSS_NAME} —— 组件样式会失效`);

/* 3. 产物没混进 js/ css/ vendor/ */
console.log("\n── 3. 产物与手写资源的目录隔离 ──");
for (const d of ["js", "css", "vendor"]) {
  const dir = join(STATIC, d);
  if (!existsSync(dir)) continue;
  const strays = readdirSync(dir).filter(
    (f) => f === JS_NAME || f === CSS_NAME || /^vue-chunk-/.test(f)
  );
  if (strays.length) bad(`${d}/ 里混进了产物文件：${strays.join(", ")} —— 会让版本号算错`);
  else ok(`${d}/ 干净（没有产物文件）`);
}

/* 4. 产物没有悬空 import */
console.log("\n── 4. chunk 引用完整 ──");
const jsTxt = existsSync(JS) ? readFileSync(JS, "utf-8") : "";
const chunkRefs = [...jsTxt.matchAll(/["'`](\.\/)?(vue-chunk-[A-Za-z0-9_.-]+\.js)["'`]/g)]
  .map((m) => m[2]);
const uniq = [...new Set(chunkRefs)];
if (!uniq.length) ok("产物是单文件，无 chunk 依赖");
else {
  const missing = uniq.filter((f) => !existsSync(join(DIST, f)));
  if (missing.length) bad(`产物引用了不存在的 chunk：${missing.join(", ")}`);
  else ok(`${uniq.length} 个 chunk 引用都在`);
}

/* 5. CSS 变量没有悬空引用 */
console.log("\n── 5. CSS 变量都有定义 ──");
const tokens = readFileSync(join(STATIC, "css", "tokens.css"), "utf-8");
const defined = new Set([...tokens.matchAll(/(--[a-z0-9-]+)\s*:/gi)].map((m) => m[1]));
const compCss = existsSync(CSS) ? readFileSync(CSS, "utf-8") : "";
const used = [...new Set([...compCss.matchAll(/var\((--[a-z0-9-]+)/gi)].map((m) => m[1]))];
const undef = used.filter((v) => !defined.has(v));
if (!undef.length) {
  ok(`用到 ${used.length} 个变量，全部在 tokens.css 里有定义`);
} else {
  // 允许 var(--x, fallback) 的写法 —— 写了兜底的才算安全
  const hardUndef = undef.filter((v) => {
    const re = new RegExp(`var\\(\\s*${v.replace(/-/g, "\\-")}\\s*\\)`, "i");
    return re.test(compCss);
  });
  if (hardUndef.length) bad(`组件 CSS 引用未定义变量且无兜底：${hardUndef.join(", ")}`);
  else ok(`用到 ${used.length} 个变量，未定义的那些都写了 fallback（可接受）`);
}

console.log("\n" + "=".repeat(62));
if (badN === 0) console.log(`通过 ${okN} · 失败 0\n✓ 产物可用`);
else console.log(`通过 ${okN} · 失败 ${badN}\n✗ 产物有问题，先修再上线`);
console.log("=".repeat(62));

process.exit(badN === 0 ? 0 : 1);
