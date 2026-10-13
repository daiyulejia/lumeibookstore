<!-- ==========================================================================
     阅读器外壳 · 上半（ReaderTop）
     --------------------------------------------------------------------------
     管 `.rd-prog` + `.rd-top`。它们在 `#reader` 里位于 `.rd-stage` **之前**。

     ⚠ 为什么外壳拆成两个组件 / 两个挂载点：
       `#reader` 是 `display:flex; flex-direction:column`，子元素的**流式顺序**
       就是 `.rd-prog`（absolute，不在流里）→ `.rd-top` → `.rd-stage` → `.rd-bottom`。
       而 Vue 只能把一棵树渲进一个容器，**没法把节点插到"容器之后、下一个兄弟之前"**
       —— 所以"stage 之前的上半"和"stage 之后的下半"必须是两个容器、两个 app 实例。
       这不是设计过度，是布局契约逼出来的（见 frontend/README.md 的说明）。

     ⚠⚠ 舞台区（`.rd-stage`）绝不归 Vue 管：
       `paginate()` 要量它的 clientWidth/clientHeight、`buildFlip()` 要往
       `#rdFlipBook` 建 StPageFlip 实例。Vue 一旦接管就会 patch 重建节点，
       StPageFlip 持有的旧引用失效 → 翻页动画偶发失效、分页位置错乱
       （偶发、极难查，所以宁可保守）。进度条 `#rdSeek` 同理（跟手势强耦合）。

     ⚠ 模块顶层不能求值 legacy(...)：页面里两个 `<script type="module">`
       （旧 main.js 与 vue-app.js）**并行**加载，谁先执行不确定；
       桥是旧 util.js 挂的，早一步就抛错 → 必须惰性取值。
     ========================================================================== -->
<template>
  <!-- ⚠ id="rdProg" 是旧代码的取节点入口（`setReaderField("progress", …)`
       在非 Vue 路径下会 `$("#rdProg").style.width = …`），必须照抄。 -->
  <div class="rd-prog" id="rdProg" :style="{ width: progress * 100 + '%' }"></div>

  <div class="rd-top">
    <!-- ⚠ id="rdBack" 同上：旧代码可能直接取它。 -->
    <button class="rd-btn" id="rdBack" title="退出 (Esc)" aria-label="退出"
            @click="call('rdBack')">←</button>
    <!-- 阅读页的品牌标记：只在噜妹阅读配色下出现（见 lumei.css §5）。
         看书时 UI 应该尽量消失，所以它极小、极淡、只是"认得出来"而已。 -->
    <span class="rd-capy-mark" aria-hidden="true"></span>
    <div class="ttl">
      <!-- ⚠ id="rdTitle" / id="rdSub" 保留：旧代码与真机测试都在取它们
           （`$("#rdTitle")`、`document.querySelector('#rdSub').textContent`）。
           踩过：迁 Vue 时只写了 `<b>{{ title }}</b>`，把 id 丢了 ——
           旧代码 `openReader` 里那行 `$("#rdTitle").textContent = ...`
           于是抛 TypeError，**整条启动链路当场中断**（目录空、正文不加载）。 -->
      <b id="rdTitle">{{ title || "—" }}</b>
      <small id="rdSub">{{ sub }}</small>
    </div>
    <button class="rd-btn" id="rdTocBtn" title="目录 (T)" aria-label="目录"
            @click="call('rdTogglePanel', 'toc')">☰</button>
    <button class="rd-btn" id="rdCacheBtn" title="缓存全书" aria-label="缓存全书"
            @click="call('rdCache')">⤓</button>
    <button class="rd-btn" id="rdSetBtn" title="设置 (S)" aria-label="设置"
            @click="call('rdTogglePanel', 'set')">Aa</button>
    <button class="rd-btn" id="rdExportBtn" title="导出" aria-label="导出"
            @click="call('rdExport')">↧</button>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from "vue";
import { callLegacy, attachReaderSnapshot } from "../legacy/util.js";

const title = ref("—");
const sub = ref("—");
const progress = ref(0);

/** reader.js 的 `syncReader()` 推过来的一整块快照（上半关心的字段）。 */
function applyState(st) {
  if (!st) return;
  if (typeof st.title === "string") title.value = st.title || "—";
  if (typeof st.sub === "string") sub.value = st.sub;
  if (typeof st.progress === "number") progress.value = st.progress;
}

/** 调旧代码（静默跳过 —— 迁移期组件可能比桥先就绪）。 */
const call = callLegacy;

// ⚠ 快照是**一份广播给多个订阅者**的：外壳拆成两个 app 实例（见文件头），
//   若两个都去调 `attachReader`，后一个会把前一个的回调覆盖掉，
//   于是"只有一个组件能收到状态"。所以统一走 bridge 的订阅表。
let off = null;
onMounted(() => {
  nextTick(() => { off = attachReaderSnapshot(applyState); });
});
onUnmounted(() => { if (off) off(); });
</script>
