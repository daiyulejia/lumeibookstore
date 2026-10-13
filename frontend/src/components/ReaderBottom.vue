<!-- ==========================================================================
     阅读器外壳 · 下半（ReaderBottom）
     --------------------------------------------------------------------------
     管 `.rd-info`（章节 / 百分比）。它必须待在 `.rd-stage` **之后** ——
     `#reader` 是纵向 flex，顺序即布局（理由详见 ReaderTop.vue）。

     ⚠ 本组件**不渲染** `.rd-bottom` 这个外壳，也不渲染 `#rdSeek`：
       `.rd-bottom` 的 CSS 用了 `> .rd-btns:first-child { order:2 }` 这类
       子选择器（窄屏重排），而且 `#rdSeek` 绑了 pointerdown/move/up 做
       跟手拖拽、`seekAt()` 还要读它的 boundingRect。这两件事都要求
       `.rd-bottom` 的子节点**由旧代码持有**（Vue 的 patch 会重建节点，
       拖拽中途把节点换掉 = 手势丢失、进度条跳回原位）。
       所以：`.rd-bottom` 外壳 + `#rdSeek` + 两组按钮留在静态 HTML，
       本组件只把**章节信息那一段**声明式化（它的内容变化最频繁）。

     ⚠⚠ `id="rdChap"` / `id="rdPct"` 必须留在 `<span>` 上，且**内外层
       结构要和迁移前逐字一致**（`<span class="ch" id="rdChap">`）。
       理由有二：
         ① 旧代码的 `setReaderField()` 非 Vue 路径直接写这些节点；
         ② 大量真机测试（test_reader_ui.py / test_motion.py / …）
            的判据就是 `document.querySelector('#rdChap').textContent`
            —— 它读的是**那个 span**，不是外层 div。一旦 id 挪到外层
            或改名，测试会以"读到 '—'"的形式静默失败。
     ========================================================================== -->
<template>
  <div class="rd-info">
    <span class="ch" id="rdChap">{{ chap }}</span>
    <span class="sep"> · </span>
    <span class="pct" id="rdPct">{{ pct }}</span>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from "vue";
import { attachReaderSnapshot } from "../legacy/util.js";

const chap = ref("—");
const pct = ref("0%");

function applyState(st) {
  if (!st) return;
  if (typeof st.chap === "string") chap.value = st.chap;
  if (typeof st.pct === "string") pct.value = st.pct;
}

// ⚠ 与 ReaderTop 共用同一份快照（两个 app 实例，见 util.js 的订阅表说明）
let off = null;
onMounted(() => {
  nextTick(() => { off = attachReaderSnapshot(applyState); });
});
onUnmounted(() => { if (off) off(); });
</script>
