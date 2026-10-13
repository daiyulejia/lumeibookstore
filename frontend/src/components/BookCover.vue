<!--
  书封 —— 全站复用的一块。
  ============================================================================
  为什么要抽成组件：旧代码里它是 `discover.js` 的 `coverHTML()`，返回一坨
  字符串，靠 `innerHTML` 拼进页面。三个问题：
    ① 每多用一次就多一份"拼字符串 + 记得 esc 每个字段"的心智负担，
       漏一个就是 XSS；
    ② 换个页面要用就得 import 另一页的模块（shelf.js 就 import 了
       discover.js —— 书架依赖搜索页，纯属历史包袱）；
    ③ 里面的 `onerror` 是靠内联属性挂的，没法复用、没法测。
  组件化之后：传参即用、字段自动转义、图片兜底是声明式的。

  DOM 契约（**不能改**，CSS 与真机测试都按它选）：
    .cover[.lg][.has-img] > img / .t / .a
  ⚠ 有真封面时保留 .t/.a 文本层（CSS 里 display:none 藏起来）而不是不渲染：
    CSS 注释说明了原因 —— 万一图是半透明 PNG，底下有字才不显得空洞。
-->
<template>
  <div class="cover" :class="{ lg, 'has-img': hasImg }" :style="gradientStyle">
    <img
      v-if="proxySrc"
      :src="proxySrc"
      alt=""
      loading="lazy"
      decoding="async"
      @error="hasImg = false"
    />
    <div class="t">{{ shortTitle }}</div>
    <div class="a">{{ shortAuthor }}</div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue";

const props = defineProps({
  /** 真封面外链（可空 —— 空了就用渐变色块兜底） */
  cover: { type: String, default: "" },
  /** 兼容旧签名：直接传色相数字，强制走渐变 */
  hue: { type: Number, default: null },
  title: { type: String, default: "" },
  author: { type: String, default: "" },
  lg: { type: Boolean, default: false },
});

const hasImg = ref(false);

const proxySrc = computed(() => {
  // 传了 hue 就等于"指名要渐变"，不再看 cover
  if (props.hue !== null) return "";
  const u = (props.cover || "").trim();
  if (!u) return "";
  // ⚠ 封面必须走代理回传，不能把外站 URL 直接塞进 <img src>：
  //   ① 来源站大多有 Referer 防盗链，直连浏览器必然 403（图裂）
  //   ② 会让用户的浏览器直连外站，暴露 IP / 访问记录
  //   /api/cover 由服务端带正确 Referer 去取并缓存，前端只认这个。
  return `/api/cover?u=${encodeURIComponent(u)}`;
});

// 只要有图就先进 has-img 态（img 铺满），加载失败由 @error 摘掉退回渐变。
watch(proxySrc, (v) => { hasImg.value = !!v; }, { immediate: true });

// 色相：显式给了就用，否则由书名长度推 —— 同一本书永远同色，
// 列表里不会出现"有的有图有的没有"那种参差感（旧 coverHTML 的原始意图）。
const hue = computed(() => {
  if (props.hue !== null) return ((props.hue % 360) + 360) % 360;
  return ((props.title || "").length * 37) % 360;
});

const gradientStyle = computed(() => {
  if (hasImg.value) return undefined;
  const h = hue.value;
  const c1 = `hsl(${h} 58% 50%)`;
  const c2 = `hsl(${(h + 38) % 360} 54% 34%)`;
  return { background: `linear-gradient(150deg,${c1},${c2})` };
});

const shortTitle = computed(() => (props.title || "?").slice(0, 7));
const shortAuthor = computed(() => (props.author || "佚名").slice(0, 6));
</script>
