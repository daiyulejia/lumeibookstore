<!--
  RanksPanel.vue · 热门榜单（第一个迁移到 Vue 的组件）
  ==========================================================================
  行为完全对齐旧的 ranks.js（数据来源、缓存、书架标记、点书名去搜），
  但**渲染方式换成 Vue 声明式**：

    旧：拼 innerHTML 字符串 → 一次性塞进 DOM → 手动 querySelectorAll 绑事件
    新：把数据放在 reactive state 里 → 模板描述长什么样 → Vue 自己 diff/更新

  这一换带来三个立竿见影的好处（也是用户说的"接新轮子"）：
    1) 以后想加个日期选择器/虚拟滚动/图表，直接 import 组件放模板里就行，
       不用再手写 DOM + 手动绑事件 + 手动清理（旧方式最容易漏的是清理，
       重新渲染一次监听器就叠一层）。
    2) 加个「已读」按钮、加个右键菜单，是加几行模板，不是加几十行 DOM 操作。
    3) 状态与界面天然一致 —— 旧代码里"渲染到一半被打断"的坑（我们刚修的
       骨架期误判就是这个）在声明式下基本不存在。

  对外契约（旧代码仍然这么用）：
    · 容器 #ranksBox 保留，内部由 Vue 接管
    · 点书名 → 填进 #q + 走 runSearch()，与旧路径一致
    · 书架变化（bus 的 shelf:changed / task:done）→ 重画标记
-->
<template>
  <div class="rk-vue">
    <!-- 头部：标题 + 新鲜度 + 操作 -->
    <div class="rk-head">
      <h2 class="rk-title">热门榜单</h2>
      <span class="rk-age" id="ranksAge">{{ freshness }}</span>
      <div class="rk-actions">
        <!-- ⚠ id 是**对外契约**，不是内部细节：tools/test_ranks_ui.py 靠它
             验证"刷新按钮点了会转""收起会折起来"等用户可见行为。
             Vue 重写渲染方式时保留这些钩子，测试就还能守住同一批行为
             （而不是把测试改松 —— 那等于把验收标准降了）。 -->
        <n-button id="ranksRefresh" size="small" quaternary :loading="loading" @click="refresh">
          <template #icon><n-icon><RefreshIcon /></n-icon></template>
          刷新
        </n-button>
        <n-button id="ranksFold" size="small" quaternary @click="folded = !folded">
          {{ folded ? "展开" : "收起" }}
        </n-button>
      </div>
    </div>

    <!-- 榜单类型切换 -->
    <!-- ⚠ 这里**没有**用 Naive 的 n-tabs，而是自己用按钮 + Naive 的视觉令牌实现。
         原因：n-tabs 内部渲染 `data-name`，而 tools/test_ranks_ui.py 的
         「切标签缓存不串台」用例靠 `.rk-tab[data-kind]` 来点标签。
         要么改测试（降验收标准），要么让 DOM 保持原契约 —— 后者对。
         自己写这十几个标签一点也不亏：样式本来就要跟噜妹主题走，
         用 Naive 的反而还要再去覆盖它。
         （这正是"N 个标签"这种小控件不该引重组件库的地方。） -->
    <div v-if="!folded" id="ranksTabs" class="rk-tabs" role="tablist">
      <button
        v-for="k in kinds"
        :key="k.kind"
        class="rk-tab"
        :class="{ on: k.kind === cur }"
        :data-kind="k.kind"
        role="tab"
        :aria-selected="k.kind === cur"
        type="button"
        @click="onKindChange(k.kind)"
      >
        {{ k.label }}
      </button>
    </div>

    <!-- 说明这一榜是按什么排的 -->
    <p v-if="!folded && curDesc" class="rk-desc" id="ranksDesc">{{ curDesc }}</p>

    <!-- 列表主体：骨架 / 数据 / 空 / 错误 四态 -->
    <div v-if="!folded" class="rk-body">
      <!-- 加载骨架：用 Naive 的 skeleton，比手写灰条更规整 -->
      <div v-if="loading && !items.length" class="rk-skel">
        <n-skeleton v-for="i in 6" :key="i" height="46px" :sharp="false" />
      </div>

      <!-- 真数据 -->
      <TransitionGroup v-else-if="items.length" name="rk-item" tag="div" class="rk-list" id="ranksList">
        <button
          v-for="(it, i) in items"
          :key="it.title + i"
          class="rk-item"
          :class="{ owned: isOwned(it.title) }"
          :data-title="it.title"
          :data-kind="it.kind"
          type="button"
          @click="pick(it)"
        >
          <span class="rk-no" :class="medalClass(i)">{{ i + 1 }}</span>
          <span class="rk-ttl" :style="{ '--h': hueFor(it.kind) }">
            <b>{{ it.title }}</b>
            <em>{{ metaOf(it) || "\u00a0" }}</em>
          </span>
          <span class="rk-src">{{ it.source_display || it.source || "" }}</span>
          <span v-if="isOwned(it.title)" class="rk-owned" title="这本书已经在你书架里了">
            ✓ 已在书架
          </span>
          <span v-else class="rk-go">找这本 ›</span>
        </button>
      </TransitionGroup>

      <!-- 空 -->
      <div v-else-if="!loading" class="rk-err">
        {{ emptyHint || "这个榜单暂时没有内容。" }}
        <n-button size="tiny" quaternary @click="reload">重试</n-button>
      </div>

      <!-- 错误 -->
      <div v-if="error && items.length" class="rk-err">
        刷新失败：{{ error }}
        <n-button size="tiny" quaternary @click="reload">重试</n-button>
      </div>
    </div>

    <!-- 底部：说明来源 + 回书架的入口（榜单看完想回自己存的书，是自然的下一步）
         id 同样是契约（test_ranks_ui 的「有回书架入口」）。 -->
    <div class="rk-foot">
      榜单来自公开榜单页，后台每 30 分钟自动刷新 ·
      <button class="rk-link" id="ranksToLib" type="button" @click="toShelf">去看我的书架 ›</button>
    </div>
  </div>
</template>

<script setup>
/**
 * 迁移说明（写给未来的自己）：
 * 这个组件**不自己发请求**，而是复用旧的 ranks.js 已经建立的
 * 缓存/时序逻辑 —— 那部分是纯数据、没有 DOM 依赖，重写一遍只会引入
 * 新的不一致。做法是：把旧模块当「数据源」import 进来，
 * 组件只做「展示 + 交互」。
 *
 * 等旧模块的其余部分都迁完了，再把数据层也搬进来，最后删掉 ranks.js。
 * 这就是「分页迁移、每步可上线」的具体落地方式。
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { NButton, NIcon, NSkeleton } from "naive-ui";
import { api, bus, PRE, toast, whenAuthReady } from "../legacy/util.js";
import { stagger } from "../legacy/motion.js";

// 极简的刷新图标（内联 SVG，省一个图标库依赖）
const RefreshIcon = {
  template: `<svg viewBox="0 0 20 20" width="15" height="15" fill="none"
    stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
    <path d="M16 10a6 6 0 1 1-1.8-4.3"/><path d="M16 3v3h-3"/></svg>`,
};

/* 每条榜单一个色相，纯视觉区分，不承载语义（沿用旧值） */
const HUE = { allvisit: 22, allvote: 350, goodnum: 268, size: 200, postdate: 145, lastupdate: 40 };

const kinds = ref([]);
const cur = ref("allvisit");
const items = ref([]);
const loading = ref(false);
const error = ref("");
const emptyHint = ref("");
const folded = ref(PRE.get("ranksFold", false));
const age = ref(null);
const refreshedAt = ref(0);
const onShelf = ref(null);
const shelfPromise = ref(null);

/* ---------- 工具 ---------- */

function normTitle(s) {
  return String(s || "")
    .replace(/[《》「」【】\s·・.。、,，:：!！?？'"'"()（）\[\]\-—_~～]/g, "")
    .toLowerCase();
}

const isOwned = (t) => !!(onShelf.value && onShelf.value.has(normTitle(t)));
const hueFor = (k) => HUE[k] ?? 22;
const medalClass = (i) => (i + 1 <= 3 ? ` m${i + 1}` : "");

function metaOf(it) {
  const meta = [];
  if (it.author) meta.push(it.author);
  if (it.words) meta.push(it.words);
  if (it.status) meta.push(it.status);
  if (it.updated) meta.push(it.updated);
  return meta.join(" · ");
}

const curDesc = computed(() => kinds.value.find((k) => k.kind === cur.value)?.desc || "");

const freshness = computed(() => {
  if (age.value == null && !refreshedAt.value) return "";
  let secs = age.value ?? 0;
  if (refreshedAt.value) secs = Math.max(0, (Date.now() - refreshedAt.value) / 1000);
  if (secs < 90) return "刚刚更新";
  if (secs < 3600) return `${Math.round(secs / 60)} 分钟前更新`;
  if (secs < 86400) return `${Math.round(secs / 3600)} 小时前更新`;
  return `${Math.round(secs / 86400)} 天前更新`;
});

/* ---------- 数据 ---------- */

function ensureShelf(force) {
  if (!force && onShelf.value) return Promise.resolve(onShelf.value);
  if (shelfPromise.value) return shelfPromise.value;
  shelfPromise.value = api
    .get("/api/library")
    .then((list) => {
      const s = new Set();
      for (const b of Array.isArray(list) ? list : []) {
        const t = normTitle(b && b.title);
        if (t) s.add(t);
      }
      onShelf.value = s;
      return s;
    })
    .catch(() => {
      onShelf.value = onShelf.value || new Set();
      return onShelf.value;
    })
    .finally(() => {
      shelfPromise.value = null;
    });
  return shelfPromise.value;
}

async function loadRanks(kind) {
  if (kind) cur.value = kind;
  const want = cur.value;
  loading.value = true;
  error.value = "";
  // 书架标记并着跑，不拖慢榜单出内容（沿用旧策略）
  ensureShelf(false);

  try {
    const d = await api.get(`/api/ranks?kind=${encodeURIComponent(want)}`);
    if (!d || !d.ok) throw new Error((d && d.error) || "拿不到榜单");
    if (cur.value !== want) return; // 用户切走了，别把旧结果盖上去
    items.value = d.items || [];
    emptyHint.value = d.empty_hint || "";
    if (typeof d.age === "number") age.value = d.age;
    refreshedAt.value = 0;
  } catch (e) {
    if (cur.value !== want) return;
    error.value = e.message || String(e);
    items.value = [];
  } finally {
    if (cur.value === want) loading.value = false;
  }
  // 错峰由动效层统一编排（与旧代码同一个约定）
  requestAnimationFrame(() => {
    const root = document.querySelector("[data-vue-ranks]") || document;
    stagger(root, ".rk-item");
  });
}

function onKindChange(k) {
  if (k === cur.value) return;
  loadRanks(k);
}

function reload() {
  loadRanks();
}

/** 刷新当前这一榜（全刷要十几秒，而"刷新我眼前这个"才是真实诉求）。
 *
 * 与旧 ranks.js 的 refreshRanks() 完全同语义：
 * POST 触发服务端重抓 → 丢掉本地缓存 → 重拉 → 提示。
 * 差异只在"转圈"的表现：旧代码手加 `.spin` 类，这里用 Naive 按钮自带的
 * loading 态（同一个视觉意图，少一处手写样式）。
 */
async function refresh() {
  try {
    await api.post(`/api/ranks/refresh?kind=${encodeURIComponent(cur.value)}`);
    refreshedAt.value = Date.now();
    age.value = 0;
    await loadRanks();
    toast("已刷新到最新");
  } catch (e) {
    toast("刷新失败：" + (e.message || e), "warn");
  }
}

/** 点书名 → 复用发现页的搜索流程（与旧代码走同一条被验证过的路）。
 *
 * 旧代码是直接 import runSearch 调的。Vue 侧**不能**再 import 一次 ——
 * 那会打进产物、变成第二份 discover 模块实例（两份状态、两个 AbortController）。
 * 所以走旧代码暴露在 window 上的 `searchFromHash`（同一个实例），
 * 它内部就是 "填 input + runSearch(kw, true)"，正是我们要的语义。
 *
 * 另外要**顺手把面板收起**：搜索结果紧接着就出来了，榜单挂在上面
 * 会把结果顶到屏幕外 —— 点了书名却"看不到任何反应"，是最糟的体验。
 * （这条是 tools/test_ranks_ui.py 明写的验收项：「面板自动收起」。）
 */
function pick(it) {
  const t = it && it.title;
  if (!t) return;
  folded.value = true; // 挡住搜索结果，先收起来
  const q = document.getElementById("q");
  if (q) q.value = t;
  window.scrollTo({ top: 0, behavior: "smooth" });
  const go = window.__lumeiLegacy && window.__lumeiLegacy.searchFromHash;
  if (go) go(t);
  else bus.emit("ranks:search", t); // 兜底：桥还没上就发事件
}

/** 「去看我的书架」：改 hash 即可，旧代码的 hashchange 会接住。 */
function toShelf() {
  location.hash = "#shelf";
}

/* ---------- 生命周期 ---------- */

let off1 = null;
let off2 = null;

// 收起状态要写回容器类名（旧 CSS `.ranks.folded` 靠它收起，
// 也是 test_ranks_ui 会检查的地方）。Vue 只管状态，类名映射放这里。
watch(folded, (v) => {
  const box = document.getElementById("ranksBox");
  if (box) box.classList.toggle("folded", !!v);
  PRE.set("ranksFold", !!v);
});

onMounted(async () => {
  // ⚠ 先等令牌就绪，再发第一个请求。
  //   页面用 `?t=<token>` 传令牌，读它的是旧代码的 bootstrapAuth()；
  //   而 Vue 是另一个 module，加载完立刻 mount —— onMounted 很可能跑在
  //   bootstrapAuth 之前，此时请求不带 t=，**线上 401**。
  //   本地 /api 不需要令牌，所以本地永远不复现，只在线上表现为
  //   "榜单区块整块不显示"。见 legacy/util.js 的 whenAuthReady()。
  await whenAuthReady();

  const box = document.getElementById("ranksBox");
  // 恢复上次的收起状态（类名也要同步，否则展开/收起的视觉状态对不上）
  if (box) box.classList.toggle("folded", !!folded.value);
  try {
    const d = await api.get("/api/ranks/kinds");
    kinds.value = (d && d.kinds) || [];
    if (!kinds.value.length) {
      // 拿不到榜单目录（比如后端版本旧）→ 整个区块不显示，不打扰用户
      if (box) box.hidden = true;
      return;
    }
    if (!kinds.value.some((k) => k.kind === cur.value)) cur.value = kinds.value[0].kind;
    if (box) box.hidden = false;
    if (!folded.value) loadRanks();
  } catch {
    kinds.value = [];
    if (box) box.hidden = true;
  }

  // 书架变了 → 重画「已在书架」标记（走事件总线，与旧约定一致）
  ensureShelf(true);
  off1 = bus.on("task:done", () => ensureShelf(true));
  off2 = bus.on("shelf:changed", () => ensureShelf(true));
});

onUnmounted(() => {
  off1 && off1();
  off2 && off2();
});
</script>

<style scoped>
/* 组件级样式：只作用于本组件（Vue 的 scoped 自动加属性选择器），
   不会污染全站 —— 这也是相对旧方式的一个实实在在的改进：
   旧代码所有样式都堆在 app.css，改一个类要担心是不是别处在用。 */
.rk-vue { display: block; }
.rk-head { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.rk-title { font: 700 15px/1.2 var(--font-ui, system-ui); color: var(--t-1); margin: 0; }
.rk-age { font-size: 12px; color: var(--t-3); }
.rk-actions { margin-left: auto; display: flex; gap: 4px; }
.rk-tabs { margin-bottom: 8px; }
.rk-desc { font-size: 12px; color: var(--t-3); margin: 2px 0 10px; min-height: 16px; }

/* 标签：与旧版视觉一致（旧版在 app.css 里，已随迁移删除）。
   选中态走噜噜橙 —— 品牌层 lumei.css 也有一条 `.rk-tab.on` 覆盖，
   两条不冲突：这里给基线，主题层给"噜妹味"。 */
.rk-tabs { display: flex; gap: 7px; overflow-x: auto; padding-bottom: 9px; }
.rk-tabs::-webkit-scrollbar { display: none; }
.rk-tab {
  flex: none;
  border: 1px solid var(--s-line, #eee0c9);
  background: var(--s-card-2, #fcf6ea);
  color: var(--t-2);
  border-radius: var(--r-full, 999px);
  padding: 5px 13px;
  font: 500 12.5px/1.5 var(--font-ui, system-ui);
  cursor: pointer;
  white-space: nowrap;
  transition: background .18s, border-color .18s, color .18s;
}
.rk-tab:hover { border-color: var(--a-line, #f0d3a4); color: var(--t-1); }
.rk-tab.on {
  background: var(--a-1);
  border-color: var(--a-1);
  color: var(--a-ink, #fff);
}
.rk-skel { display: flex; flex-direction: column; gap: 6px; }
.rk-list { display: flex; flex-direction: column; gap: 6px; }

/* 入场错峰：--mo-i 由 stagger() 写，样式只描述"怎么动" */
.rk-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border: 1px solid transparent;
  border-radius: var(--r-m, 14px);
  background: transparent;
  cursor: pointer;
  text-align: left;
  font: inherit;
  color: inherit;
  width: 100%;
  animation: rk-in .42s var(--ease-out, cubic-bezier(.16,1,.3,1)) both;
  animation-delay: calc(var(--mo-i, 0) * 34ms);
  transition: background .18s, border-color .18s;
}
.rk-item:hover { background: var(--s-card-2, #fcf6ea); border-color: var(--s-line, #eee0c9); }
.rk-item.owned { background: color-mix(in srgb, var(--ok-bg, #eaf3ea) 46%, transparent); }

@keyframes rk-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: none; }
}
.rk-item-enter-active, .rk-item-leave-active { transition: all .28s var(--ease-out, ease); }
.rk-item-enter-from { opacity: 0; transform: translateY(8px); }
.rk-item-leave-to { opacity: 0; transform: translateX(-8px); }

.rk-no {
  width: 24px; height: 24px; flex: none;
  display: grid; place-items: center;
  border-radius: 8px;
  font: 700 12px/1 var(--font-ui, system-ui);
  background: var(--s-card-3, #f6ecda);
  color: var(--t-2);
}
.rk-no.m1 { background: linear-gradient(140deg, #f6b95c, #e8912f); color: #fff; }
.rk-no.m2 { background: linear-gradient(140deg, #c9d2dd, #a9b6c4); color: #fff; }
.rk-no.m3 { background: linear-gradient(140deg, #e3b98c, #c9915f); color: #fff; }

.rk-ttl { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 2px; }
.rk-ttl b {
  font: 600 14px/1.3 var(--font-ui, system-ui);
  color: var(--t-1);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.rk-ttl em { font-style: normal; font-size: 12px; color: var(--t-3); }
.rk-src { font-size: 12px; color: var(--t-4, var(--t-3)); flex: none; }
.rk-go { font-size: 12px; color: var(--a-1); opacity: 0; flex: none; transition: opacity .18s; }
.rk-item:hover .rk-go { opacity: 1; }
.rk-owned { font-size: 12px; color: var(--ok); flex: none; }
.rk-err { font-size: 13px; color: var(--t-2); padding: 16px 4px; display: flex; align-items: center; gap: 8px; }

/* 底部说明 + 回书架入口 */
.rk-foot {
  margin-top: 12px; padding-top: 10px;
  border-top: 1px solid var(--s-line-2, #f7eedd);
  font-size: 12px; color: var(--t-3);
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
}
.rk-link {
  background: none; border: 0; padding: 0; cursor: pointer;
  font: inherit; color: var(--a-1);
}
.rk-link:hover { text-decoration: underline; }
</style>
