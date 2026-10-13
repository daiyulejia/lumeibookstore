<!--
  App.vue · Vue 应用的根组件
  ==========================================================================
  迁移期这个组件只负责一件事：把 Naive 的主题配置包在最外层，
  然后把具体页面交给子组件。

  注意 NConfigProvider 必须在最外层 —— 里面任何 Naive 组件都靠它拿主题。
  它不吃 DOM 尺寸（默认就是个透传包装），所以不会影响现有布局。
-->
<template>
  <n-config-provider :theme="themeState.theme" :theme-overrides="themeState.overrides">
    <n-message-provider>
      <RanksPanel v-if="mountRanks" />
    </n-message-provider>
  </n-config-provider>
</template>

<script setup>
import { computed, ref } from "vue";
import { NConfigProvider, NMessageProvider } from "naive-ui";
import { themeState } from "./theme/naive.js";
import RanksPanel from "./components/RanksPanel.vue";

// 只有当页面上真的存在榜单容器、且它被标记为「交给 Vue」时才挂载组件。
// 这样旧代码和 Vue 可以在同一页面共存而不打架。
const mountRanks = ref(!!document.querySelector("[data-vue-ranks]"));

// 暴露主题给模板
const theme = computed(() => themeState);
</script>
