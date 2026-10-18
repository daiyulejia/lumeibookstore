<!--
  发现页 · 结果区（Vue 版）
  ============================================================================
  迁移边界（重要，改之前先读）：
  · **没迁**：`.hero`（标题 + 双水豚插画 + 搜索框）。它是一块静态布局，
    没有状态、没有分支，迁过去只会把 `#q` / `#btnSearch` 这两个**跨模块契约**
    搬进 Vue —— 而 main.js 的 `#q` 读写、`tools/test_buttons.py` 的 A 组断言、
    深链 `searchFromHash` 全都按原生元素找它们。保留在静态 HTML 里最稳。
  · **迁了**：hero 以下所有**有状态**的部分 ——
      #statbar            搜索状态栏（三态：搜索中 / 结果统计 / 空）
      #netLive            联网发现实况面板（步骤列表 + 展开/收起）
      #filters            来源筛选条（只看能读的 / 来源 chips / 清空结果）
      #results            结果卡列表（骨架 / 卡片 / 两种空态）
      #homeEmpty          首屏空态
      #confirmBox         书名确认框 / 网址提示框
    这些正是"旧代码用 innerHTML 拼字符串"的重灾区，也是这次框架化的意义所在。

  ⚠ DOM 钩子一个都不能改：真机测试（test_buttons A 组、test_discover_ui）
    与 theme 层都按它们选元素。改 id = 把验收标准降了。
-->

<template>
  <div class="lu-discover">
    <!-- 搜索状态栏。
         ⚠ `v-html` 是**必要的**：旧代码往里塞的是带 <b> 的富文本
           （「看遍 <b>9</b> 个来源…」），而且逻辑在 discover.js 里，
           这里只做展示。文案由 legacy 侧算好，本组件不重复实现一遍格式化 ——
           那会变成"两处维护同一段文案"。
           富文本内容全部来自旧代码自己的 esc()，不含用户可控的裸 HTML。 -->
    <div class="statbar" id="statbar" v-html="statHTML"></div>

    <!-- 联网发现实况：本地来源都搜不到时，一步步显示「出去找」的过程 -->
    <div
      class="netlive"
      id="netLive"
      :class="{ hidden: !steps.length, done: netDone, folded: netFolded }"
      aria-live="polite"
    >
      <div class="nl-head">
        <span class="nl-spin" :class="{ on: !netDone }" ref="spinEl"></span>
        <b id="netLiveTitle">{{ netTitle }}</b>
        <span class="nl-sub" id="netLiveSub">{{ netSub }}</span>
        <span class="grow"></span>
        <n-button id="netLiveToggle" size="tiny" quaternary @click="netFolded = !netFolded">
          {{ netFolded ? "展开" : "收起" }}
        </n-button>
      </div>
      <ol class="nl-steps" id="netLiveSteps" ref="stepsEl">
        <li v-for="(s, i) in steps" :key="i" :class="stepCls(s)">
          <span class="d"></span>
          <span class="t">{{ s.title }}</span>
          <span v-if="s.detail" class="x">{{ s.detail }}</span>
        </li>
      </ol>
    </div>

    <!-- 筛选条：「只看能读的」+ 来源 chips + 清空结果 -->
    <div class="filters" id="filters" :class="{ hidden: !showFilters }">
      <label class="switch">
        <input type="checkbox" id="onlyOk" :checked="onlyOk" @change="onOnlyOk">
        <span class="track"></span>只看能读的
      </label>
      <span class="vline"></span>
      <div class="srcchips" id="srcChips">
        <button
          v-for="s in sources"
          :key="s.name"
          class="chip"
          :class="{ on: srcOn.has(s.name) }"
          :data-src="s.name"
          type="button"
          @click="toggleSrc(s.name)"
        >{{ s.display }}</button>
      </div>
      <div class="spacer"></div>
      <n-button id="btnClearSearch" size="small" quaternary @click="clearSearch">清空结果</n-button>
    </div>

    <!-- 结果区。四态：骨架 / 卡片 / 两种空。
         ⚠ 骨架用 `.skl` 类（test_buttons 用 `#results .skl` 判断"还在搜"）。 -->
    <div class="grid" id="results">
      <template v-if="searching && !list.length">
        <div v-for="i in 6" :key="i" class="skl">
          <div class="b cv"></div>
          <div class="col">
            <div class="b ln" style="width: 52%"></div>
            <div class="b ln" style="width: 32%; height: 10px"></div>
            <div class="b ln" style="width: 92%; height: 10px"></div>
            <div class="b ln" style="width: 70%; height: 10px"></div>
          </div>
        </div>
      </template>

      <template v-else-if="list.length">
        <!-- 提示条三选一：按作者找到的 > 模糊沾边的 > 都不挂。
             两条同时出现会自相矛盾（一条说"找到了"、一条说"没找到"）。 -->
        <div v-if="byAuthor" class="fuzzy auth">
          <span class="fi">✍️</span>
          <div class="ft">
            <b>按作者找到了 {{ books.length }} 本</b>
            <span>「{{ confirmed }}」是作者名，下面是 ta 的作品 —— 书名里当然不含作者名，这是对的。</span>
          </div>
        </div>
        <div v-else-if="fuzzy" class="fuzzy">
          <span class="fi">🤔</span>
          <div class="ft">
            <b>没找到确切的《{{ confirmed }}》</b>
            <span>下面这 {{ books.length }} 本是「沾边」结果 —— 名字里带这几个字，但不一定是你要的那本。补上作者名一起搜会准很多。</span>
          </div>
        </div>

        <div
          v-for="(b, i) in list"
          :key="groupKey(b)"
          class="book"
          :data-gk="groupKey(b)"
          :class="{ open: open.has(groupKey(b)) }"
          :style="{ '--mo-i': i }"
        >
          <div class="head">
            <BookCover :cover="b.cover" :hue="b.hue" :title="displayTitle(b)" :author="b.author" />
            <div class="meta">
              <h3>{{ displayTitle(b) }}</h3>
              <div class="by">{{ b.author || "作者未知" }}</div>
              <div class="desc">
                <template v-if="b.intro">{{ b.intro }}</template>
                <span v-else class="no-intro">收录于 {{ siteNames(b) }}</span>
              </div>
              <div class="tags">
                <span v-for="(t, ti) in tagsOf(b)" :key="ti" class="pill" :class="t.cls">{{ t.text }}</span>
              </div>
            </div>
          </div>
          <div class="acts">
            <n-button
              size="small" type="primary" data-act="read"
              :data-u="uOf(best(b))" @click="onAct('read', b, best(b))"
            >开始阅读</n-button>
            <n-button size="small" data-act="toggle" @click="toggleOpen(b)">
              来源 {{ b.source_count }} ▾
            </n-button>
            <n-button
              size="small" data-act="dl"
              :data-u="uOf(best(b))" title="导出文件" @click="onAct('dl', b, best(b))"
            >↧</n-button>
          </div>
          <div class="sources">
            <div v-for="(s, si) in b.sources" :key="si" class="srow">
              <span class="nm">{{ s.source_display || s.source }}</span>
              <span class="pill" :class="srcPill(s).cls">{{ srcPill(s).text }}</span>
              <span v-if="tocNote(s)" class="pill" :class="tocNote(s).cls">{{ tocNote(s).text }}</span>
              <span class="grow"></span>
              <span class="n">{{ s.probe_ms ? s.probe_ms + "ms" : "" }}</span>
              <button
                v-if="s.readable || s.available"
                class="mini pri" data-act="read" :data-u="uOf(s)"
                @click="onAct('read', b, s)"
              >阅读</button>
              <button class="mini" data-act="dl" :data-u="uOf(s)" @click="onAct('dl', b, s)">导出</button>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- 首屏空态。插画走 CSS background（不要写 <img src="/static/...">，
         会被 Vite 当模块解析，把整份产物拖垮 —— 见 ShelfPanel 的长注释）。 -->
    <div id="homeEmpty" class="empty"
         :class="{ hidden: !showHomeEmpty, 'no-books': !books.length }">
      <div class="empty-art" aria-hidden="true"></div>
      <h3>{{ emptyTitle }}</h3>
      <p>{{ emptyText }}</p>
      <!-- 不知道读什么时的下一步：推荐页（榜单）。
           只留一句"说个书名"等于把人晾在原地 —— 给一个现成的去处。
           只在一本都没搜到（首屏）时给；搜过但没通过验证时不给（那是另一个问题）。 -->
      <button v-if="!books.length" id="homeToRanks" class="btn ghost sm"
              type="button" @click="toRanks">去推荐逛逛 ›</button>
    </div>

    <!-- 书名确认框 / 网址提示框。内容由旧代码的 renderConfirm / hintUrlBox
         生成（含 chips 交互），这里只做容器 + 事件挂载，不重写那份逻辑。 -->
    <div id="confirmBox" v-html="confirmHTML"></div>
  </div>
</template>

<script setup>
/**
 * 迁移说明（写给未来的自己）：
 * 本组件**不自己发搜索请求**，也**不自己实现搜索状态机** ——
 * 那部分（SSE 流式解析、AbortController 竞态守卫、分组算法）是 discover.js
 * 里被测试反复钉过的纯逻辑，重写一遍只会引入新的不一致。
 *
 * 所以分工是：
 *   · discover.js = 数据层 + 状态机（保留）
 *   · 本组件 = 渲染层（新）
 * 两侧靠 **同一条事件总线** 通信：旧代码每次状态变化 emit `discover:state`，
 * 本组件收下后重画。这就是"分页迁移、每步可上线"的具体落地方式。
 *
 * ⚠ 为什么用 bus 而不是让旧代码直接操纵 Vue 的 ref：
 *   那会让 discover.js 反过来依赖 Vue（旧代码要在没有 Vue 的环境里也能跑）。
 *   bus 是项目里已有的跨模块约定，两侧都不需要知道对方是什么。
 */
import { computed, onMounted, onUnmounted, ref, nextTick } from "vue";
import { NButton } from "naive-ui";
import BookCover from "./BookCover.vue";
import { bus, legacy, whenAuthReady } from "../legacy/util.js";

const books = ref([]);          // 全量分组结果（M.books）
const searching = ref(false);
const onlyOk = ref(true);
const sources = ref([]);        // 来源清单（LoadSources 拉的）
const srcOn = ref(new Set());   // 已选中的来源（空 = 全部）
const fuzzy = ref(false);
const confirmed = ref("");
const statHTML = ref("");
const steps = ref([]);          // 联网实况步骤
const netTitle = ref("正在联网找书…");
const netSub = ref("");
const netDone = ref(false);
const netFolded = ref(false);
const showFilters = ref(false);
const homeOverride = ref(null); // 旧代码显式指定首页空态时（清空 / 网址失败）覆盖默认
const confirmHTML = ref("");
const open = ref(new Set());    // 展开「来源」的卡片（按 groupKey）

const spinEl = ref(null);
const stepsEl = ref(null);

/* 可见列表：「只看能读的」过滤后的结果（与旧 visibleBooks() 同口径）。 */
const list = computed(() =>
  onlyOk.value
    ? books.value.filter((b) => (b.sources || []).some((s) => s.readable || s.available))
    : books.value
);

const byAuthor = computed(
  () => !fuzzy.value && list.value.some((b) => (b.sources || []).some((s) => s.by_author))
);

/* 「首页空态」的显示条件 —— 与旧 renderResults() 的三态一一对应：
     ① 正在搜 / 有结果  → 藏起来
     ② 搜完但一本没通过验证 → 空态换成"搜到 N 本但都没通过"（配不同插画文案）
     ③ 一本都没搜到 / 还没搜过 → 默认的"说个书名"
   ⚠ 旧代码是把整个 #results 的 innerHTML 换成空态（空态住在 #results 里面），
     迁移后空态是独立元素（#homeEmpty），所以这里的显示条件必须显式列全，
     否则会出现"空列表 + 默认空态"同时显示（首屏那个状态本来是 #homeEmpty 独显）。 */
const showHomeEmpty = computed(() => {
  if (searching.value) return false;
  if (list.value.length) return false;
  return true;
});

const emptyTitle = computed(() => {
  if (!books.value.length) return "说个书名，噜噜就跑去找";
  return `搜到 ${books.value.length} 本，但都没通过验证`;
});
const emptyText = computed(() => {
  if (!books.value.length) {
    // ⚠ 这里要短。它多占一行，"去推荐逛逛"就往下掉 23px。
    //   实测 1280×800 屏幕的浏览器视口只有 705，"每本都先验证一遍…
    //   才敢说它能读"那种长句会把按钮顶出首屏。意思保留，字数砍半。
    return "每本都先验一遍，真能读到正文才敢说「能读」。";
  }
  return "关掉上面的「只看能读的」看看原始结果，或者点开卡片看每个来源的状态 —— 有的站点目录能开、正文抓不到，卡片上会写清楚。";
});

/** 空态里的「去推荐逛逛」：改 hash 即可，main.js 的 hashchange 会接管路由。
 *  ⚠ 不直接调 nav()：Vue 侧不 import 旧 shell 模块（会打进第二份实例），
 *    走 hash 是唯一不产生第二份状态的路径。
 */
function toRanks() {
  location.hash = "#ranks";
}

/* ---------- 纯函数（与 discover.js 同口径，改动要两边同步） ---------- */

function groupKey(b) {
  return `${(b.title || "").trim()}\u0000${(b.author || "").trim()}`;
}
function displayTitle(b) {
  return b.display_title || b.title;
}
function siteNames(b) {
  return [...new Set((b.sources || []).map((s) => s.source_display || s.source).filter(Boolean))].join("、");
}
function uOf(s) {
  return `${(s && s.source) || ""}|${(s && s.url) || ""}`;
}
function best(b) {
  return (b.sources || []).find((s) => s.readable) || (b.sources || [])[0] || {};
}

/* 来源徽标：与旧 srcPill() 完全一致（口径不能松 —— 见 discover.js 的注释：
   没验证过就不许给绿标，否则点进去一个字都没有）。 */
function srcPill(s) {
  if (s.readable) return { cls: "ok", text: `✓ 可读 · ${s.chapter_count} 章` };
  if (s.sample_ok === false) return { cls: "warn", text: "目录在，正文抓不到" };
  if (s.available) return { cls: "mute", text: `目录 ${s.chapter_count} 章 · 正文未验证` };
  if (s.available === false) return { cls: "bad", text: `✕ ${s.note || "打不开"}` };
  return { cls: "mute", text: "未验证" };
}

/* 「目录可能不全」—— 后端 `webfetch.toc_completeness` 算出来的。
   必须显示：界面上的「12 章」和「这本书就是 12 章」长得一模一样，
   用户下完才发现是零头 —— 最坏的一种失败是「他以为拿到了」。 */
function tocNote(s) {
  return s && s.chapter_note ? { cls: "warn", text: `⚠ ${s.chapter_note}` } : null;
}

/* 书籍级标签：与旧 bookHTML() 一致。 */
function tagsOf(b) {
  const out = [];
  const sampledBad = (b.sources || []).some((s) => s.sample_ok === false);
  const sampledGood = (b.sources || []).some((s) => s.sample_ok === true);
  if (b.readable_count) out.push({ cls: "ok", text: `${b.readable_count} 个来源可读` });
  else if (sampledBad) out.push({ cls: "warn", text: "目录能开，但正文抓不到" });
  else if (b.available_count) out.push({ cls: "mute", text: `${b.available_count} 个来源目录可达 · 正文未验证` });
  else out.push({ cls: "bad", text: "暂无可用来源" });
  if (b.chapter_count) out.push({ cls: "mute", text: `最多 ${b.chapter_count} 章` });
  // 只有**验过且通过**才敢说"正文已验证"
  if (sampledGood && b.sample_chars) out.push({ cls: "ok", text: "正文已验证" });
  if (b.source_count > 1) out.push({ cls: "mute", text: `${b.source_count} 个站点收录` });
  return out;
}

/* 联网实况步骤的类：hit（命中来源库）= 绿点，bad（失败）= 红点。 */
const HIT = /发现可用来源|来源库命中|来源库已更新|收录/;
function stepCls(s) {
  if (s.ok === false) return "bad";
  return HIT.test(s.title) ? "hit" : "";
}

/* ---------- 交互：全部交给旧代码的同一条路径（bus） ---------- */

function onOnlyOk(e) {
  const v = e.target.checked;
  onlyOk.value = v;
  legacy("setOnlyOk")(v);
}
function toggleSrc(name) {
  legacy("toggleSource")(name);
}
function clearSearch() {
  legacy("clearSearch")();
}
function toggleOpen(b) {
  const k = groupKey(b);
  const s = new Set(open.value);
  if (s.has(k)) s.delete(k);
  else s.add(k);
  open.value = s;
}
function onAct(act, b, s) {
  if (!s || !s.url) return;
  if (act === "read") bus.emit("book:read", s);
  if (act === "dl") bus.emit("book:export", { src: s, book: b });
}

/* ---------- 数据订阅 ----------
   旧代码在状态变化时 emit `discover:state`，payload 就是一份快照。
   一次事件把整块状态刷掉，不做增量 diff —— 这是**渲染层**最简单也最不容易
   写错的形态（旧代码本来就是"整块重写"，语义完全一致）。 */
function applyState(st) {
  if (!st) return;
  books.value = st.books || [];
  searching.value = !!st.searching;
  onlyOk.value = st.onlyOk !== false;
  fuzzy.value = !!st.fuzzy;
  confirmed.value = st.confirmed || "";
  statHTML.value = st.statHTML || "";
  showFilters.value = !!st.filtersVisible;
  confirmHTML.value = st.confirmHTML || "";
  steps.value = st.steps || [];
  netTitle.value = st.netTitle || "正在联网找书…";
  netSub.value = st.netSub || "";
  netDone.value = !!st.netDone;
  // 面板收起状态由 discover.js 决定（它知道"有发现就自动收起"的规则）
  if (typeof st.netFolded === "boolean") netFolded.value = st.netFolded;
  if (st.sources) sources.value = st.sources;
  if (st.srcOn) srcOn.value = new Set(st.srcOn);
  // 列表变化后重放错峰动画（与项目约定一致：动效由 stagger 编排，不写行内 delay）
  nextTick(() => {
    const root = document.querySelector("[data-vue-discover]");
    if (root) legacy("stagger")(root, ".book");
  });
}

onMounted(async () => {
  // 令牌就绪再让旧代码发请求（见 legacy/util.js 的 whenAuthReady）
  await whenAuthReady();

  bus.on("discover:state", applyState);

  // 告诉旧代码「渲染权在我这儿」—— 它据此跳过所有 innerHTML 写入。
  // 用 legacy 里的同一个函数，保证两边判断口径一致。
  legacy("attachDiscover")(applyState);
});

onUnmounted(() => {
  bus.off("discover:state", applyState);
  legacy("detachDiscover")();
});
</script>

<style scoped>
/* 组件级样式。基础视觉都在 app.css / lumei.css 里（那些是通用层，
   按类名作用于任何元素，包括 Vue 渲染的 —— 这是设计如此）。
   这里只补 app.css 没有、而 Vue 模板需要的少量东西。 */
.lu-discover { display: block; }
.vline {
  width: 1px;
  height: 15px;
  background: var(--s-line);
}
/* 「联网实况」的 spinner：旧代码靠 `#netLiveSpin` 的存在与否切动画，
   迁移后由一个类控制（`.on` 才转）。基线样式在 app.css 里。 */

/* 空态插画：div 没内在尺寸，要自己撑出 480×360。 */
.empty-art {
  aspect-ratio: 480 / 360;
  background-image: url("/static/img/lumei/empty_wait@480.webp");
  background-size: cover;
  background-position: center;
}

/* 首屏空态（一本都还没有）用**极简档**。
   ⚠ 这不是"审美偏好"，是可用性问题，而且是量出来的：
     · Hero 435px + 空态 441px → 文档 1027
     · 1280×800 的屏幕，浏览器视口只有 **705**（工具栏吃掉 ~95px）
     · 「去推荐逛逛」落在 y=730／832 —— **在折线以下**，用户不滚就看不见
   两条压缩都试过（插画 240→160→132、留白 70→28→22），最好也只差 10px ——
   因为病根不在尺寸，在**首屏放了两张插画**：Hero 已经有一张噜噜/噜妹，
   空态再来一张纯属重复装饰，却把最重要的入口顶下去。
   所以首屏直接不要那张图：只留"标题 + 一句说明 + 入口"，按钮 y≈628。
   ⚠ 搜过但没结果时（books 非空、只是没过验证）仍保留插画 —— 那种时候
     用户需要安慰，而且他已经滚到结果区，不受首屏折线约束。
   ⚠ 只作用于 #homeEmpty，不动通用的 .empty（书架/文件页空态保持原样）。 */
#homeEmpty.no-books { padding-top: 20px; padding-bottom: 20px; }
#homeEmpty.no-books .empty-art { display: none; }
@media (max-width: 480px) {
  #homeEmpty.no-books { padding-top: 14px; padding-bottom: 14px; }
}

</style>
