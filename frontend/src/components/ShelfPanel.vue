<!--
  书架页（Vue 版）
  ============================================================================
  迁移要点与「契约保留」说明：
  · DOM 钩子全部保留（真机测试与 CSS 都按它们选，不能改）：
      #shelfList / #shelfStat / #shelfN / #shelfEmpty / #btnShelfReload
      .shelf[data-id] / [data-a] 按钮
  · 数据来源**不重写**：`loadShelf` 是旧代码里被多处复用的函数
    （reader:closed、task:done、ranks 联动都会调它），
    shelfCache 也是"这本书在不在书架里"的真相源。
    这里直接复用 legacy 里的同一份 —— 否则就出现两份状态互相打架。
  · 交互不是自己实现：点"开始阅读/缓存/导出"照样 `bus.emit` 同样的事件，
    由 main.js 里现成的处理器接管（阅读器、任务队列都在那边）。
-->
<template>
  <div class="wrap">
    <div class="filters">
      <div class="shelf-h">我的书架</div>
      <span id="shelfStat" class="shelf-stat">{{ statText }}</span>
      <div class="spacer"></div>
      <n-button id="btnShelfReload" size="small" quaternary :loading="loading" @click="reload">
        刷新
      </n-button>
    </div>

    <div v-if="loading && !books.length" class="shelfgrid" id="shelfList">
      <div v-for="i in 4" :key="i" class="shelf sk">
        <div class="sk-cover"></div>
        <div class="info">
          <div class="sk-line w60"></div>
          <div class="sk-line w40"></div>
          <div class="sk-line w80 tall"></div>
        </div>
      </div>
    </div>

    <div v-else class="shelfgrid" id="shelfList">
      <div
        v-for="(b, i) in books"
        :key="b.id"
        class="shelf"
        :data-id="b.id"
        :style="{ '--mo-i': i }"
      >
        <BookCover :cover="b.cover" :title="b.title" :author="b.author" />
        <div class="info">
          <h4>{{ b.title }}</h4>
          <div class="by">
            {{ b.author || "作者未知" }} · {{ b.source_display || b.source || "" }}
          </div>
          <div class="prog">
            <div>
              <div class="lb">
                <span>读到 {{ b.position?.index || 1 }}/{{ b.total || "?" }} 章</span>
                <span>{{ readPct(b).toFixed(0) }}%</span>
              </div>
              <div class="bar"><i :style="{ width: readPct(b) + '%' }"></i></div>
            </div>
            <div>
              <div class="lb">
                <span>已缓存 {{ b.cached || 0 }} 章</span>
                <span>{{ cachePct(b).toFixed(0) }}%</span>
              </div>
              <div class="bar">
                <i :style="{ width: cachePct(b) + '%', background: 'var(--ok)' }"></i>
              </div>
            </div>
          </div>
          <div class="acts">
            <n-button size="small" type="primary" data-a="read" @click="onAct(b, 'read')">
              {{ readPct(b) > 1 ? "继续阅读" : "开始阅读" }}
            </n-button>
            <n-button size="small" data-a="cache" @click="onAct(b, 'cache')">缓存全书</n-button>
            <n-button size="small" data-a="export" @click="onAct(b, 'export')">导出</n-button>
            <n-button size="small" quaternary data-a="del" @click="onAct(b, 'del')">移除</n-button>
          </div>
        </div>
      </div>
    </div>

    <div id="shelfEmpty" class="empty" :class="{ hidden: books.length > 0 || loading }">
      <!-- ⚠ 插画路径写死在 CSS 里（见下方 <style> 的 .empty-art），
           不要写成 <img src="/static/...">：
           @vitejs/plugin-vue 会把 src 当**模块引用**去解析，rollup 一看
           是绝对路径 /static/... 就报 "failed to resolve import"、
           整个构建挂掉；把它配成 external 更糟 —— 产物里会留下一句
           `import x from "/static/....webp"`，浏览器把 webp 当 JS 模块加载
           直接失败，**整份 vue-app.js 都跑不起来**（连榜单一起白屏）。
           用 CSS background 就绕开了模块解析，路径原样进样式表。 -->
      <div class="empty-art" aria-hidden="true"></div>
      <h3>书架空空，噜噜睡得正香</h3>
      <p>在「发现」里点「开始阅读」，书就会落到这里 —— 之后打开秒进，断网也能看。</p>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { NButton } from "naive-ui";
import BookCover from "./BookCover.vue";
import { api, bus, confirmBox, legacy, toast, whenAuthReady } from "../legacy/util.js";

const books = ref([]);
const loading = ref(true);

const statText = computed(() => (books.value.length ? `共 ${books.value.length} 本` : ""));

function readPct(b) {
  const total = b.total || 0;
  const pos = b.position || {};
  if (!total) return 0;
  return Math.min(100, (((pos.index || 1) - 1 + (pos.percent || 0)) / total) * 100);
}
function cachePct(b) {
  const total = b.total || 0;
  if (!total) return 0;
  return Math.min(100, ((b.cached || 0) / total) * 100);
}

/**
 * 拉一次书架。
 * ⚠ 数据**只有一条来源**：调旧代码的 `loadShelf()`，然后由它广播
 *   `shelf:loaded` 回来（见下方 onLoaded）。
 *   为什么不在这里自己 `api.get("/api/library")`：
 *     · loadShelf 内部还有「书架形状变了才广播 shelf:changed」的去重，
 *       榜单的星标靠这个事件重画；自己拉就把去重丢了，榜单被反复重画；
 *     · shelfCache 是"这本书在不在书架里"的真相源，必须由同一处维护。
 *
 * ⚠ 也**不要**在 onMounted 里无脑调它。
 *   旧代码在启动时已经拉了（main.js 的 loadShelf()），切到书架还有
 *   onNav("shelf", loadShelf) 再拉一次 —— 组件再调就变成一次加载打
 *   4 遍同一个接口（真机数过）。所以这里改成"按需补拉"：
 *   订阅之后等一小会儿，要是没等到 `shelf:loaded`（说明广播发生在
 *   组件挂载之前、没人收到），才自己补一次。
 */
let gotData = false;

async function reload() {
  loading.value = true;
  armSafety();
  try {
    // ⚠ loadShelf 自己把异常吞了（内部 try/catch 里 toast），所以这里
    //   `await` 之后不会抛 —— 成功与否只能靠 `shelf:loaded` 事件判断。
    //   因此 loading 的复位主要靠 onLoaded，另有 armSafety 兜底超时。
    await legacy("loadShelf")();
  } catch (e) {
    toast("读取书架失败：" + e.message, "err");
    loading.value = false;
  }
}

const onLoaded = (list) => {
  gotData = true;
  books.value = Array.isArray(list) ? list : [];
  loading.value = false;
  clearTimeout(safety);
};

/** 兜底：万一 loadShelf 静默失败了（比如接口 500 被它吞掉），
    15 秒后强制摘掉骨架态，别让用户对着灰条干等。 */
let safety = null;
function armSafety() {
  clearTimeout(safety);
  safety = setTimeout(() => { loading.value = false; }, 15000);
}

async function onAct(b, a) {
  if (a === "read") bus.emit("shelf:read", b);
  else if (a === "export") {
    bus.emit("shelf:export", { library_id: b.id, title: b.title, author: b.author });
  } else if (a === "cache") {
    bus.emit("shelf:cache", { id: b.id, title: b.title });
  } else if (a === "del") {
    const yes = await confirmBox({
      title: "移出书架",
      message: `把《${b.title}》移出书架？已经缓存的正文章节会一起删掉，下次要重新去网上抓。`,
      okText: "移出",
      danger: true,
    });
    if (!yes) return;
    try {
      await api.del("/api/library/" + b.id);
      toast("已移出书架");
      reload();
    } catch (e) {
      toast("移出失败：" + e.message, "err");
    }
  }
}

// ⚠ 只订这一个事件就够了。
//   "...缓存跑完 / 阅读器关闭 / 切到书架" 这些刷新路径，旧代码里已经
//   各自接了 `loadShelf`（main.js 的 onNav、shelf.js 的 bus.on），
//   loadShelf 每次都会广播 `shelf:loaded` —— 这里订阅它即可。
//   自己再订一遍 task:done / reader:closed 就会刷新两遍（而且还要管
//   卸载时摘监听，白白多一份出错的余地）。
onMounted(async () => {
  // 令牌就绪再发请求（与榜单同样的时序坑，见 legacy/util.js 的 whenAuthReady）。
  await whenAuthReady();

  // ⚠ 先订阅、再（按需）拉。顺序不能反：
  //   启动时 bootRoute() / onNav 可能已经拉过一轮并广播了 `shelf:loaded`，
  //   那时组件还没挂上、事件没人收 —— 先订阅才能保证收得到。
  bus.on("shelf:loaded", onLoaded);

  // 已经在加载中就先摆骨架（避免"闪一下空列表"）。
  loading.value = true;

  // 等一小会儿看有没有现成的广播：
  //   · 有 → onLoaded 已经填好了，这一轮不用再打接口；
  //   · 没有 → 说明广播早于订阅，自己补拉一次。
  // 200ms 足够覆盖"同一轮事件循环里已经 emit 过"的情况，
  // 又短到用户感知不到延迟。
  setTimeout(() => {
    if (!gotData) reload();
  }, 200);
});

onUnmounted(() => {
  // 组件卸载必须摘监听，否则切走再回来会挂上第二份。
  // （bus.off 是为 Vue 迁移新加的，见 app/static/js/util.js 的注释。）
  bus.off("shelf:loaded", onLoaded);
  clearTimeout(safety);
});
</script>

<style scoped>
.shelf-h {
  font-size: 19px;
  font-weight: 800;
}
.shelf-stat {
  font-size: 13px;
  color: var(--t-3);
}
.sk .sk-cover {
  width: 66px;
  height: 92px;
  border-radius: var(--r-s);
  background: var(--s-line-2);
  flex: 0 0 auto;
}
.sk-line {
  height: 10px;
  border-radius: 6px;
  background: var(--s-line-2);
  margin-bottom: 9px;
}
.sk-line.w60 { width: 60%; }
.sk-line.w40 { width: 40%; }
.sk-line.w80 { width: 80%; }
.sk-line.tall { height: 22px; }

/* 空书架插画。
   ⚠ 用 background 而不是 <img>（原因见模板里的注释：<img src="/static/...">
     会被 Vite 当模块解析，external 又会留下坏 import 把整份产物拖垮）。
   .empty-art 的公共样式（宽度/圆角/阴影/主题降饱和）在 lumei.css 里，
   这里只补 div 缺的那部分：因为是 div 没有内在尺寸，
   要自己给 aspect-ratio 撑出原图的比例（480×360 = 4:3）。 */
.empty-art {
  aspect-ratio: 480 / 360;
  background-image: url("/static/img/lumei/empty_sleep@480.webp");
  background-size: cover;
  background-position: center;
}
</style>
