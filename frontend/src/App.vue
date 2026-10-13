<!--
  Vue 应用根组件。
  ============================================================================
  迁移期的挂载策略：**一个容器一个 app 实例**（见 src/main.js 的注释）。
  这里用 `only` prop 决定这个实例该渲染哪个页面组件 ——
  因为 Vue 只能把整棵树渲进一个元素里，不能"一个 app 同时管两处
  互不相邻的 DOM"（踩过：书架组件被渲进了榜单区内部）。

  `only` 由 main.js 按容器上的 `data-vue-*` 标记传入。
-->
<template>
  <n-config-provider :theme="themeState.theme" :theme-overrides="themeState.overrides">
    <component :is="comp" />
  </n-config-provider>
</template>

<script setup>
import { computed } from "vue";
import { NConfigProvider } from "naive-ui";
import { themeState } from "./theme/naive.js";
import RanksPanel from "./components/RanksPanel.vue";
import ShelfPanel from "./components/ShelfPanel.vue";

const props = defineProps({
  /** 这个 app 实例负责渲染哪个组件（见 main.js 的 MOUNTS） */
  only: { type: String, default: "" },
});

const REGISTRY = { RanksPanel, ShelfPanel };
const comp = computed(() => REGISTRY[props.only] || RanksPanel);
</script>
