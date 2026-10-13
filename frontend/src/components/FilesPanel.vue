<!--
  文件页（Vue 版）
  ============================================================================
  · DOM 钩子全部保留（真机测试与 CSS 都按它们选，不能改）：
      #fileList / #fileEmpty / #fmtPick / #btnFilesReload
      .file / .ic[data-ext] / .nm / .acts / [data-open] / [data-del]
  · 数据**不重写**：复用旧 `loadFiles()`（它里面还有下载链接的拼法、fmtIcon、
    stagger 动效），由它广播 `files:loaded` 回来。理由同 ShelfPanel：
    自己再拉一遍就有两份状态，而且看不出"文件页长什么样"的真相在哪。
  · 「导出格式」下拉框仍然写同一个 PRE 键（`fmt`）—— main.js 里
    `bus.on("book:export")` 就是读 `$("#fmtPick").value`。
    所以这一页的 select **必须保留 id="fmtPick"**，否则导出会拿不到格式、
    甚至抛 null 错。它同时也是 PRE 的写入方（用户在这里选，搜索页导出时读）。
-->
<template>
  <div class="wrap">
    <div class="filters">
      <div class="files-h">导出文件</div>
      <div class="spacer"></div>
      <label class="sr" for="fmtPick">导出格式</label>
      <!-- ⚠ 这个原生 <select> 是**故意**留着的，不是没迁干净 —— 别删。
           原因：main.js 里有 3 处 `fmt: $("#fmtPick").value`
           （bus.on("book:export") / shelf:export / reader:export），
           它们读的是**原生 select 的 .value**。
           Naive 的 n-select 渲染出来是 div + input，`.value` 取不到东西 ——
           真踩过（测试直接断言出 None）：导出会拿到 undefined 格式。
           这里用 native select 当"值的真相源"，样式由 CSS 美化到跟
           n-select 一致；n-select 留给以后彻底重构 main.js 时再换。
           它同时也在 onchange 里写 PRE，兼容旧行为。 -->
      <select
        id="fmtPick"
        v-model="fmt"
        class="fmt-select"
        @change="onFmt(fmt)"
      >
        <option value="txt">TXT（哪里都能开）</option>
        <option value="epub">EPUB（Kindle / 阅读器）</option>
        <option value="html">HTML（自带小阅读器的单文件）</option>
      </select>
      <n-button id="btnFilesReload" size="small" quaternary :loading="loading" @click="reload">
        刷新
      </n-button>
    </div>

    <!-- 骨架：只在"首次加载且还没有数据"时出现，避免刷新时闪一下空态。
         ⚠ 骨架**不能带 `.file` 类** —— 真机测试（test_files_ui / test_buttons F0）
           用 `#fileList .file` 数文件行数，骨架混进去会把 3 个占位当成 3 个文件，
           断言 `行数 == 接口数` 直接失效（而且假绿：空目录 + 骨架 = "3 个文件"）。
           用 `.fsk` 自己的类，样式单独写。 -->
    <div v-if="loading && !files.length" id="fileList">
      <div v-for="i in 3" :key="i" class="fsk">
        <div class="sk-ic"></div>
        <div class="sk-col">
          <div class="sk-line w60"></div>
          <div class="sk-line w40"></div>
        </div>
        <div class="sk-acts">
          <div class="sk-btn"></div>
          <div class="sk-btn"></div>
        </div>
      </div>
    </div>

    <div v-else id="fileList">
      <div v-for="f in files" :key="f.name" class="file" :data-ext="f.ext">
        <div class="ic" :data-ext="f.ext" v-html="fmtIcon(f.ext)"></div>
        <div class="nm">
          <b :title="f.name">{{ f.name }}</b>
          <span>{{ (f.ext || "").toUpperCase() }} · {{ fmtSize(f.size) }} · {{ fmtTime(f.mtime) }}</span>
        </div>
        <div class="acts">
          <n-button v-if="f.ext === 'html'" size="small" :data-open="f.name" @click="onOpen(f)">
            打开看
          </n-button>
          <a class="btn sm" :href="downloadUrl(f)" download>下载</a>
          <n-button size="small" quaternary :data-del="f.name" @click="onDel(f)">删除</n-button>
        </div>
      </div>
    </div>

    <div id="fileEmpty" class="empty" :class="{ hidden: files.length > 0 || loading }">
      <!-- ⚠ 插画用 CSS background，不要写 <img src="/static/...">
           （原因见 ShelfPanel.vue 里的长注释：会被 Vite 当模块解析，把整份产物拖垮） -->
      <div class="empty-art" aria-hidden="true"></div>
      <h3>还没导出过</h3>
      <p>在书籍卡片上点「导出」，或者在书架里导出整本 —— 打包好就能带走。</p>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { NButton } from "naive-ui";
import { api, bus, confirmBox, legacy, PRE, toast, whenAuthReady } from "../legacy/util.js";

/* 格式图标：SVG 比 emoji 可控（吃 currentColor，五套主题都成立）。
   ⚠ 与 app/static/js/files.js 的 fmtIcon 保持同一份 path 数据 ——
   改了这边记得改那边（旧实现还在，迁移期两边都得能画）。 */
const ICONS = {
  txt: "M4 2h8l4 4v12H4zM12 2v4h4",
  epub: "M4 2h9l4 4v12H4zM13 2v4h4M7 10h7M7 13h7",
  html:
    "M12 2a10 10 0 100 20 10 10 0 000-20M2 12h20M12 2c2.5 2.7 3.8 6.2 3.8 10S14.5 19.3 12 22M12 2C9.5 4.7 8.2 8.2 8.2 12S9.5 19.3 12 22",
};

function fmtIcon(ext) {
  const p = ICONS[ext] || "M4 2h8l4 4v12H4z";
  return (
    `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" ` +
    `stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">` +
    `<path d="${p}"/></svg>`
  );
}

const files = ref([]);
const loading = ref(true);

// 初始值从 PRE 读 —— 和旧实现一致，用户上次选的格式要记住。
const fmt = ref(PRE.get("fmt", "txt"));

function onFmt(v) {
  PRE.set("fmt", v);
}

// ⚠ 不能在模块顶层求值 `legacy("fmtSize")` ——
//   页面里两个 `<script type="module">`（旧 main.js 与 vue-app.js）是
//   **并行**加载的，谁先执行不确定；桥接是旧 util.js 挂的，
//   早一步就会抛 "旧模块 fmtSize 还没挂到 window.__lumeiLegacy 上"。
//   所以包一层惰性取值（`legacy()` 每次调用都会重新 pick，
//   挂载之后就一直命中，开销可以忽略）。
const fmtSize = (n) => legacy("fmtSize")(n);
const fmtTime = (t) => legacy("fmtTime")(t);

function downloadUrl(f) {
  return api.url("/api/file/" + encodeURIComponent(f.name));
}

function onOpen(f) {
  window.open(downloadUrl(f), "_blank");
}

async function onDel(f) {
  const yes = await confirmBox({
    title: "删除文件",
    message: `删除 ${f.name}？这个操作不能撤销。`,
    okText: "删除",
    danger: true,
  });
  if (!yes) return;
  try {
    await api.del("/api/file/" + encodeURIComponent(f.name));
    toast("已删除");
    reload();
  } catch (e) {
    toast("删除失败：" + e.message, "err");
  }
}

/**
 * 拉一次文件列表。
 * ⚠ 数据只有一条来源：旧代码的 `loadFiles()`，它成功后广播 `files:loaded`。
 *   loadFiles 内部把异常吞了（自己 toast），所以 await 之后不抛 ——
 *   loading 的复位靠 onLoaded，另有 armSafety 兜底。
 */
let gotData = false;

async function reload() {
  loading.value = true;
  armSafety();
  try {
    await legacy("loadFiles")();
  } catch (e) {
    toast("读取文件失败：" + e.message, "err");
    loading.value = false;
  }
}

const onLoaded = (list) => {
  gotData = true;
  files.value = Array.isArray(list) ? list : [];
  loading.value = false;
  clearTimeout(safety);
};

/** 兜底：旧实现静默失败（接口 500 被吞）时别让用户对着骨架干等。 */
let safety = null;
function armSafety() {
  clearTimeout(safety);
  safety = setTimeout(() => { loading.value = false; }, 15000);
}

onMounted(async () => {
  await whenAuthReady();

  // 先订阅再按需补拉（顺序不能反，理由见 ShelfPanel 的同名注释）。
  bus.on("files:loaded", onLoaded);
  // ⚠ 「导出完成 → 刷新列表」由组件自己订。
  //   旧实现在 files.js 的 wireFilesEvents 里订，但那条被 vueOwnsFiles() 挡住了
  //   （否则会和组件这里重复刷两遍）。不订的话导出完切过来看还是旧列表。
  bus.on("task:done", onTaskDone);

  loading.value = true;
  setTimeout(() => { if (!gotData) reload(); }, 200);
});

function onTaskDone(t) {
  if (t && t.kind === "download") reload();
}

onUnmounted(() => {
  bus.off("files:loaded", onLoaded);
  bus.off("task:done", onTaskDone);
  clearTimeout(safety);
});
</script>

<style scoped>
.files-h {
  font-size: 19px;
  font-weight: 800;
}
.fmt-select {
  width: auto;
  min-width: 190px;
  /* 原生 select 也得跟 Naive 控件一个长相（否则这一行"混搭"很显眼） */
  padding: 5px 10px;
  border-radius: var(--r-s);
  border: 1px solid var(--s-line);
  background: var(--s-bg-2);
  color: var(--t-1);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}
.fmt-select:focus-visible {
  outline: 2px solid var(--a-1);
  outline-offset: 1px;
}

/* 骨架条。
   ⚠ `.fsk` 是**独立**的骨架容器类，不能复用 `.file`（见模板里的注释）。 */
.fsk {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
}
.sk-ic {
  width: 40px;
  height: 40px;
  border-radius: var(--r-s);
  background: var(--s-line-2);
  flex: 0 0 auto;
}
.sk-col {
  flex: 1;
  min-width: 0;
}
.sk-acts {
  display: flex;
  gap: 8px;
  flex: 0 0 auto;
}
.sk-line {
  height: 10px;
  border-radius: 6px;
  background: var(--s-line-2);
  margin-bottom: 8px;
}
.sk-line.w60 { width: 60%; }
.sk-line.w40 { width: 40%; }
.sk-btn {
  width: 56px;
  height: 26px;
  border-radius: var(--r-s);
  background: var(--s-line-2);
}

/* 空态插画：div 没有内在尺寸，要自己撑出原图比例（480×360） */
.empty-art {
  aspect-ratio: 480 / 360;
  background-image: url("/static/img/lumei/loading_drink@480.webp");
  background-size: cover;
  background-position: center;
}
</style>
