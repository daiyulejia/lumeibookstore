<!-- ==========================================================================
     阅读器侧边面板（ReaderPanels）· 目录 + 设置
     --------------------------------------------------------------------------
     两个 `.rd-panel` 都是 `position:absolute;top:0;bottom:0`，相对
     `.rd-stage` 定位（它们是 `.rd-stage` 的子元素）。因为是绝对定位，
     **外面包一层容器不影响布局** —— 所以这两个面板可以共用一个 Vue 挂载
     容器，放在 `.rd-stage` 内部（见 index.html）。

     ⚠ 为什么值日把面板迁走：面板是"以后要长东西"的地方 ——
       目录想加虚拟滚动 / 分组、设置想加折叠分组 / 新选项（字体粗细、
       段间距、背景纹理），旧代码全是 innerHTML 拼字符串，每加一项都要
       小心引号转义和 class 拼接。声明式之后加东西容易得多。

     ⚠ 目录列表（`#rdTocList`）的内容仍由旧代码生成，用 `v-html` 喂进来 ——
       因为那里有**增量加载**（滚到底 append 240 条）和 `appendToc()` 里
       一段很细的"以 DOM 真实条目数为准"的防重复逻辑（见 reader.js 注释），
       重写风险高、收益低。Vue 只管"这扇门的开合 + 外壳结构"。

     ⚠⚠ **旧代码依赖的 id 必须留在模板里**，一个都不能省。
       迁移后旧代码**并没有停止读写这几处 DOM** ——
       `renderToc()` 会 `box.innerHTML=""`、`box.scrollTop=0`、
       `box.scrollTo()`；`appendToc()` 会 `box.insertAdjacentHTML()`；
       `markToc()` 会 `$$("a", box)`。它们全都要拿到**真实的 `#rdTocList`**。
       踩过：第一版模板里只有 `.list` 没有 `id`，于是 `$("#rdTocList")`
       永远是 `null` → `renderToc()` 第一行 `box.innerHTML` 直接抛错 →
       整条目录链路静默死掉（目录永远空）。这类"id 丢了"的错
       不会在构建期报，也不会有明显的控制台红字（被 try/catch 吞了）。
       所以：**Vue 组件里凡是旧代码还在用的 id，一律照抄**。

     ⚠ `#rdThemes`（色卡）的内容也由旧代码生成（含背景色 style），同样 v-html。
       `#rdFsRow / #rdLhRow / ...`（分段选择器）则改由本组件声明式渲染。
     ========================================================================== -->
<template>
  <!-- 目录 -->
  <aside class="rd-panel" id="rdToc" :class="{ on: tocOpen }">
    <header>
      <h4>目录</h4>
      <!-- ⚠ id="rdTocClose" 保留：旧代码与真机测试都点它（`#rdTocClose`.click()）。
           丢了它的表现很曲折：测试里"先关目录"那步静默无效 → 目录其实还开着
           → 下一步"点 ☰ 打开目录"反而把它关掉 → 断言失败。
           看起来像"☰ 按钮坏了"，其实是面板的 ✕ 不见了。 -->
      <button class="rd-btn" id="rdTocClose" aria-label="关闭目录"
              @click="call('rdClosePanels')">✕</button>
    </header>
    <div class="rd-panel-search">
      <!-- ⚠ id="rdTocQ" 保留：非 Vue 路径下 mountReaderUI 会绑它的 input 事件 -->
      <input type="search" id="rdTocQ" placeholder="搜索章节名…" @input="onTocQuery" />
    </div>
    <!-- 内容由旧代码产出（含 esc() 过的章节名），原样喂进来。
         ⚠ id="rdTocList" 是旧代码的取节点入口，不能改（见上方注释）。 -->
    <div class="list" id="rdTocList" v-html="tocHTML" @click="onTocClick"></div>
  </aside>

  <!-- 设置 -->
  <aside class="rd-panel right" id="rdSet" :class="{ on: setOpen }">
    <header>
      <h4>阅读设置</h4>
      <button class="rd-btn" id="rdSetClose" aria-label="关闭设置"
              @click="call('rdClosePanels')">✕</button>
    </header>
    <div class="list">
      <div class="rd-set-row">
        <div class="gl">配色</div>
        <!-- 色卡由旧代码产（六个固定色卡，背景色是行内 style），v-html。
             ⚠ id="rdThemes" 同样是旧代码的取节点入口（`$$("#rdThemes button")`）。 -->
        <div class="rd-thermos" id="rdThemes" v-html="themesHTML" @click="onThemeClick"></div>
      </div>

      <div class="rd-set-row">
        <div class="gl">字号</div>
        <!-- ⚠ id="rdFsRow" 挂在 .rd-stepper 上（与迁移前的结构逐字对齐）：
             旧代码与真机测试都是 `$("#rdFsRow [data-fs]")` 这样取的。 -->
        <div class="rd-stepper" id="rdFsRow">
          <button data-fs="-1" aria-label="减小字号" @click="call('rdSetOpt', 'fs', -1)">A－</button>
          <span class="v" id="rdFsV">{{ fs }}px</span>
          <button data-fs="1" aria-label="增大字号" @click="call('rdSetOpt', 'fs', 1)">A＋</button>
        </div>
      </div>

      <div class="rd-set-row">
        <div class="gl">行距</div>
        <div class="rd-seg" id="rdLhRow">
          <button v-for="o in LH" :key="o.v" :data-lh="o.v" :class="{ on: +lh === +o.v }"
                  @click="call('rdSetOpt', 'lh', o.v)">{{ o.label }}</button>
        </div>
      </div>

      <div class="rd-set-row">
        <div class="gl">字体</div>
        <div class="rd-seg" id="rdFfRow">
          <button v-for="o in FF" :key="o.v" :data-ff="o.v" :class="{ on: ff === o.v }"
                  @click="call('rdSetOpt', 'ff', o.v)">{{ o.label }}</button>
        </div>
      </div>

      <div class="rd-set-row">
        <div class="gl">每行宽度</div>
        <div class="rd-seg" id="rdWRow">
          <button v-for="o in W" :key="o.v" :data-w="o.v" :class="{ on: +w === +o.v }"
                  @click="call('rdSetOpt', 'w', o.v)">{{ o.label }}</button>
        </div>
      </div>

      <div class="rd-set-row">
        <div class="gl">翻页方式</div>
        <div class="rd-seg" id="rdModeRow">
          <button v-for="o in MODE" :key="o.v" :data-mode="o.v" :class="{ on: mode === o.v }"
                  @click="call('rdSetOpt', 'mode', o.v)">{{ o.label }}</button>
        </div>
      </div>

      <div class="rd-set-row">
        <div class="gl">快捷键</div>
        <div class="rd-kbd">
          <kbd>←</kbd><kbd>→</kbd> 翻页 · <kbd>空格</kbd> 下翻 · <kbd>[</kbd><kbd>]</kbd> 上下章<br>
          <kbd>T</kbd> 目录 · <kbd>S</kbd> 设置 · <kbd>F</kbd> 沉浸 · <kbd>Esc</kbd> 退出<br>
          手机上：点屏幕<b>左右两侧</b>翻页，点<b>中间</b>唤出工具栏；也可以左右滑动。
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from "vue";
import { callLegacy, attachReaderSnapshot } from "../legacy/util.js";

const call = callLegacy;

/* 选项表：**必须与旧代码里的按钮一一对应**（值、顺序、文案）。
   旧代码那边靠 `data-lh="1.6"` 之类取值，这里直接调 rdSetOpt(kind, val)，
   传的就是同一批值 —— 两边不会分叉。 */
const LH = [{ v: 1.6, label: "紧凑" }, { v: 1.85, label: "标准" }, { v: 2.2, label: "宽松" }];
const FF = [{ v: "serif", label: "宋体" }, { v: "sans", label: "黑体" }, { v: "kai", label: "楷体" }];
const W = [{ v: 32, label: "窄" }, { v: 40, label: "中" }, { v: 50, label: "宽" }];
const MODE = [
  { v: "slide", label: "左右平移" },
  { v: "flip", label: "仿真翻页" },
  { v: "scroll", label: "上下滚动" },
];

const tocOpen = ref(false);
const setOpen = ref(false);
const tocHTML = ref("");
const themesHTML = ref("");
const fs = ref(19);
const lh = ref(1.85);
const ff = ref("serif");
const w = ref(40);
const mode = ref("slide");

function applyState(st) {
  if (!st) return;
  if (typeof st.tocOpen === "boolean") tocOpen.value = st.tocOpen;
  if (typeof st.setOpen === "boolean") setOpen.value = st.setOpen;
  if (typeof st.tocHTML === "string") tocHTML.value = st.tocHTML;
  if (typeof st.themesHTML === "string") themesHTML.value = st.themesHTML;
  if (typeof st.fs === "number") fs.value = st.fs;
  if (st.lh != null) lh.value = st.lh;
  if (typeof st.ff === "string") ff.value = st.ff;
  if (st.w != null) w.value = st.w;
  if (st.modes && typeof st.modes.mode === "string") mode.value = st.modes.mode;
}

/* —— 交互回传 —— */
function onTocQuery(e) { call("rdFilterToc", e.target.value); }
function onTocClick(e) {
  const a = e.target.closest("a");
  if (!a) return;
  e.preventDefault();
  call("rdGoChapter", a.dataset.i);
}
/** 主题色卡那一排：旧代码把 `<button data-th="lumei">` 拼出来，这里委托。 */
function onThemeClick(e) {
  const b = e.target.closest("button[data-th]");
  if (b) call("rdSetTheme", b.dataset.th);
}

let off = null;
onMounted(() => {
  nextTick(() => { off = attachReaderSnapshot(applyState); });
});
onUnmounted(() => { if (off) off(); });
</script>

<style scoped>
/* 目录搜索框那一栏：旧代码里是行内 style（padding + 一条底边框线）。
   ⚠ test_motion.py 有一条断言"组件样式不许写行内 style"—— 行内 style
   优先级高于任何类选择器，主题层够不到它。迁过来正好把它修掉。

   ⚠⚠ 那条**底边框线故意不写在这里**，而是进了 `app/static/css/reader.css`。
     为什么：那条线用的主题变量定义在 `#reader[data-rd-theme="…"]` 上
     （reader.css），**不在** `tokens.css`。而 `verify-dist.mjs` 第 5 节的
     规则是"组件产物里用到的变量必须在 tokens.css 里有定义，否则要有
     fallback"—— 裸用会被它拦下（构建直接失败，这次真被拦了）。
     写 fallback 也不对：兜底值会盖掉六套主题各自的线色。
     正确的归属就是"跟着主题变量走"→ 放回 reader.css，与那个变量同层。
     组件这边只留纯几何（padding / 字号）。

   ⚠ 还有一条更阴的：**注释里也不能写出那个变量的完整字面量**。
     自检是拿正则扫整个产物 CSS 的，不区分注释 ——
     第一版就是把变量名写在注释里当例子，结果注释本身被当成"引用"报红。 */
.rd-panel-search {
  padding: 11px;
}
.rd-panel-search input { font-size: 13.5px; }
</style>
