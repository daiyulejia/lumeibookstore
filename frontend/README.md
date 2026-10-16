# 噜妹书院 · 前端（Vite + Vue 3 + Naive UI）

## 为什么有这个目录

原来的前端是**手写 CSS + `innerHTML` 拼字符串**：
4240 行 JS 里有 85 处 `innerHTML`，每个组件都自己拼 HTML、自己
`querySelectorAll` 绑事件、"重画"其实就是整块重写。

能跑，但**加新东西很痛苦**：
- 想接个日期选择器 / 虚拟滚动 / 图表，得手写 DOM、手动绑事件、手动清理
- 清理最容易漏 —— 重画一次监听器就叠一层
- 状态和界面靠人同步，于是有了"骨架期被拍到""渲染到一半被打断"这类 bug

所以引入构建体系，换 Vue 的**声明式渲染**：描述"长什么样"，
更新交给框架。加新轮子只需 `import` 一个组件放进模板。

## 目录结构

```
frontend/
├── package.json          # 依赖与脚本
├── vite.config.js        # 构建配置（含三条硬约束的注释，改前先读）
├── tools/verify-dist.mjs # 产物自检（9 项断言）
└── src/
    ├── main.js           # 入口：找所有 data-vue-* 容器，逐个挂 app
    ├── App.vue           # 根组件（NConfigProvider 包主题 + only 路由）
    ├── theme/
    │   ├── tokens.js     # 把 tokens.css 的 CSS 变量喂给 Naive UI
    │   └── naive.js      # 装主题 + 监听主题切换
    ├── legacy/           # 迁移期桥接旧模块（见下）
    └── components/
        ├── RanksPanel.vue    # 热门榜单（第一个迁移的页面）
        ├── ShelfPanel.vue    # 书架页
        ├── FilesPanel.vue    # 文件页
        ├── DiscoverPanel.vue # 发现页结果区（半迁移：hero 仍是静态 HTML）
        ├── ReaderTop.vue     # 阅读器外壳·上半（.rd-prog + .rd-top）
        ├── ReaderPanels.vue  # 阅读器外壳·两个侧边面板（目录 + 设置）
        ├── ReaderBottom.vue  # 阅读器外壳·下半（.rd-info）
        └── BookCover.vue     # 复用的书封（榜单/书架/发现共用）
```

## 三个必须知道的硬约束

改 `vite.config.js` 之前先读这段。每一条都是踩出来的。

### 1. 产物路径必须出现在 `index.html` 里

`tools/sync_cloud.py` 上线时会从 `index.html` 正则抠出所有
`href="/static/..."` / `src="/static/..."`，然后**逐个请求验证 200**。
只要有一个 404 就判定上线失败。

所以：**加了新产物文件，必须在 `index.html` 里引用**，否则不会被验证，
线上可能白屏而部署"成功"。

### 2. 产物不能混进 `js/` `css/` `vendor/`

`app/main.py` 的 `_asset_version()` 只扫这三个目录的**顶层文件**取
mtime 当版本号（用来给 `/static/x.css?v=...` 打版本，防浏览器拿旧缓存）。
产物混进去会让版本号算错 → 改了前端但版本号没变 → 用户拿到旧代码。

产物一律放 `app/static/dist/`，与那三个目录隔离。
`verify-dist.mjs` 第 3 节会检查这件事。

### 3. 产物名带 `vue-` 前缀

第一版产物叫 `app.css`，撞上了手写的 `css/app.css`。
两个同名的东西摆在项目里，以后 grep / 拷贝极易拿错
（而产物是**不能手改**的）。所以统一 `vue-app.js` / `vue-app.css`。

## 迁移期：`legacy/` 桥接层

**关键点：Vue 侧不 import 旧模块，而是运行期从 window 上取引用。**

旧代码是直接静态提供的 ES module（`/static/js/util.js`）。
如果让 Vite 把它打进产物，运行期会有**两份模块实例**：
- 事件总线 `bus` 会有两个 → Vue 侧 emit、旧侧收不到（幽灵 bug）
- `PRE` / 缓存不共享

所以旧模块在启动时把关键导出挂到 `window.__lumeiLegacy`
（见 `app/static/js/util.js` 末尾的「迁移桥」注释），
Vue 侧从那里取同一个实例。

挂上去的：`$ $$ esc fmtSize fmtTime PRE bus TOKEN api toast confirmBox copyText
stagger searchFromHash`。

⚠ **新增桥接项时，两边都要改**：旧模块 `window.__lumeiLegacy = {...}`，
以及 `src/legacy/*.js` 的导出。

## 命令

```bash
cd frontend

# 装依赖（首次）。注意：esbuild / rollup 的平台二进制
# 有时不会被自动装上，缺了就单独装：
#   npm i @esbuild/win32-x64 @rollup/rollup-win32-x64-msvc
npm install

# 构建 + 自检（上线前跑这个）
npm run build:check

# 只构建
npm run build
```

**平时不用手动跑** —— `tools/ship.py` 的 `[0/4]` 步骤会自动构建 + 自检，
失败就中止，不会把旧产物推上线。

## 组件开发约定

### 保留 DOM 契约

`tools/test_ranks_ui.py` 等真机测试靠 DOM 的 **id / class / data-\*** 来验证
用户可见行为（比如"点刷新会真的重新取数"）。

Vue 重写渲染方式时，**要把这些钩子保留下来**，而不是去改测试 ——
改测试等于把验收标准降了。已经保留的：
`#ranksBox #ranksAge #ranksRefresh #ranksTabs #ranksDesc
#ranksList #ranksToLib`、`.rk-item[data-title]`、`.rk-tab[data-kind]`。
（2026-10-15：原「收起/展开」按钮随榜单独立 tab 化下线，钩子一并移除。）

⚠ 阅读器那一票 id 更要小心：**旧代码并没有停止读写它们**。
`renderToc()` 会 `$("#rdTocList").innerHTML=""`、`.scrollTop=0`、
`appendToc()` 会 `insertAdjacentHTML` —— 它们不是"为了测试保留的钩子"，
是**运行时真的在用**。丢了就是 `$()` 返回 null → 抛错 → 链路静默死。
（这也是 `test_reader_shell.py` 存在的原因：专门钉这一层。）

⚠ `v-html` 喂进去的内容（`#rdTocList` / `#rdThemes` 里的 HTML）**不参与
Vue 的 patch** —— 里面的 class 状态（`.on`）必须**由生成方拼进去**，
不能指望 Vue 去 toggle。

（这也是这里 **没有** 用 Naive 的 `n-tabs` 的原因：它内部渲染 `data-name`，
对不上 `.rk-tab[data-kind]`。十几个标签不值得为它改测试。）

### 样式用 scoped

组件样式写在组件的 `<style scoped>` 里，Vue 自动加属性选择器隔离。
不要再往 `app.css` 里加组件样式 —— 那正是"改一个类要担心别处在用"的来源。

例外：`motion.css`（怎么动）和 `lumei.css`（品牌痕迹）是**通用层**，
按类名作用于任何元素，包括 Vue 渲染的 —— 这是设计如此，别改。

### 错峰统一用 `stagger()`

项目约定：列表入场错峰走 `stagger()`，业务代码不许写行内 `animation-delay`。
有静态断言守着（`tools/test_motion.py` 第 3 节）。Vue 组件也守这条。

## 当前进度

- [x] 构建体系（Vite + Vue 3 + Naive UI + 产物自检）
- [x] 主题桥（7 套主题的 CSS 变量 → Naive themeOverrides）
- [x] 热门榜单（`RanksPanel.vue`）
- [x] 书架页（`ShelfPanel.vue` + 复用的 `BookCover.vue`）
- [x] 文件页（`FilesPanel.vue`）
- [x] 发现页结果区（`DiscoverPanel.vue`）—— **半迁移**，见下
- [x] 阅读器外壳（`ReaderTop.vue` / `ReaderPanels.vue` / `ReaderBottom.vue`）
      —— **外壳迁移，不是整个阅读器**，见下

### 阅读器为什么拆成三个组件 / 三个容器

这是整个迁移里**唯一被布局契约逼出来的**设计，改之前务必先看这段。

`#reader` 是 `display:flex; flex-direction:column`，**子元素的流式顺序就是布局**：

```
#reader
 ├─ .rd-prog        ← position:absolute，不在流里
 ├─ .rd-top         ← flex:0 0 auto（顶栏）
 ├─ .rd-stage       ← flex:1（正文舞台，**绝不归 Vue**）
 └─ .rd-bottom      ← flex:0 0 auto（底栏）
```

Vue **只能把一棵树渲进一个容器**，没法把节点插到"容器之后、下一个兄弟
之前"。所以"stage 之前的（`.rd-prog` + `.rd-top`）"和"stage 之后的
（`.rd-bottom`）"必然是**两个容器、两个 app 实例**，中间再夹一个
面板容器（在 `.rd-stage` 内）：

| 容器 | 组件 | 管什么 |
|---|---|---|
| `[data-vue-rdtop]` | `ReaderTop.vue` | `.rd-prog` + `.rd-top`（书名/作者/进度/四个按钮） |
| `[data-vue-rdpanels]` | `ReaderPanels.vue` | 目录 + 设置两个 `.rd-panel`（放在 `.rd-stage` 内） |
| `[data-vue-rdbottom]` | `ReaderBottom.vue` | `.rd-info`（章节 / 百分比） |

**绝不能交给 Vue 的两块**（也写在 `index.html` 的注释里）：

- **`.rd-stage`** —— `paginate()` 要量它的 `clientWidth/clientHeight`；
  `buildFlip()` 要往 `#rdFlipBook` 建 StPageFlip 实例。
  Vue 一旦接管就会 patch 重建节点 → StPageFlip 持有的旧引用失效 →
  **翻页动画偶发失效、分页错乱**（偶发、极难查，所以宁可保守）。
- **`#rdSeek`**（进度条）—— 绑了 `pointerdown/move/up` 做跟手拖拽，
  `seekAt()` 还要读它自己的 `getBoundingClientRect`。这类"跟手势强耦合"
  的交互必须让旧代码**持续持有同一个节点**，patch 中途换掉 = 手势丢失。

### 迁移期状态桥：一份快照，多个订阅者

三个组件是三个 app 实例，而旧代码的 `attachReader(apply)` **只保留一个
回调** —— 三个都调它，后一个会覆盖前一个（表现："只有一个组件能收到
状态更新"，而且是"后挂载的那个能收到"）。

所以走 `legacy/util.js` 的 `attachReaderSnapshot(apply)`：**第一个**订阅者
向旧代码注册，快照进来后广播给全部订阅者。返回退订函数（`onUnmounted` 时调）。

调试用：`window.__lumeiRdDebug` 暴露了 `{ snapshots, last, registered }` ——
"旧代码没推"还是"Vue 没收到"，一眼分清。

### 目录列表为什么用"内存镜像"

`renderToc()` / `appendToc()` / `markToc()` 里有**增量加载**（滚到底
append 240 条）和一段很细的"以 DOM 真实条目数为准"的防重复逻辑。

Vue 接管后 `#rdTocList` 是 Vue 渲染的、内容靠 `v-html` ——
直接写它会：① 与 `v-html` 打架（下一帧被覆盖），② 读到上一帧的节点。
所以 `reader.js` 里加了一层 `tocBox()`：Vue 在时返回一个**游离的 `<div>`
镜像**，旧逻辑一字不改地跑在镜像上，跑完把 `mirror.innerHTML` 整段
`setTocHTML()` 推给 Vue。

- 好处：增量/去重/高亮逻辑**只维护一份**，零重写、零分叉风险。
- 注意：**滚动监听要绑可见节点**（镜像不在文档里，`clientHeight` 恒 0，
  `onscroll` 永不触发 → 目录只有前 240 条）。同样，`markToc` 的
  "滚到当前章"也要作用在可见节点上（镜像里元素的 `offsetTop` 恒 0）。

### 发现页为什么是"半迁移"

发现页分两块，边界是**有意划的**，改之前先看清：

| 块 | 归属 | 原因 |
|---|---|---|
| `.hero`（标题 + 双水豚 + 搜索框 `#q` / `#btnSearch`） | **静态 HTML** | `#q` / `#btnSearch` 是跨模块契约：main.js 的 `$("#q")`、深链 `searchFromHash`、`test_buttons.py` A 组都按**原生元素**找它们。迁进 Vue 只会把这些依赖变成"不可靠" |
| hero 以下（`#statbar` / `#netLive` / `#filters` / `#results` / `#homeEmpty` / `#confirmBox`） | **Vue**（`DiscoverPanel.vue`） | 这些是"有状态 + 反复重画"的部分，旧代码用 `innerHTML` 拼字符串的重灾区 |

两块靠 **事件总线**通信（不是互相 import）：

```
discover.js（数据层 + 状态机，保留）
   │  状态变化 → bus.emit("discover:state", 快照)
   ▼
DiscoverPanel.vue（渲染层，新）
   │  用户操作 → legacy("setOnlyOk" / "toggleSource" / "clearSearch")
   ▼
discover.js（同一条被验证过的路径）
```

- Vue 组件挂载后调 `legacy("attachDiscover")(fn)` 注册自己，`discover.js`
  据此知道"该 emit 了"；卸载时 `detachDiscover()`。
- `discover.js` 里所有 DOM 写入都包了一层（`setStat` / `setFilters` /
  `setHomeEmpty` / `setConfirm`）：Vue 在就更新影子状态 + 推快照，否则写 DOM。
  这样同一个数据层能喂两种渲染实现，迁移期任一侧出问题页面都不会空白。

每迁完一个页面，删掉对应的旧模块和 `legacy/` 里的桥接项。
全迁完后 `legacy/` 整个目录都可以删。

## 两个"跨模块契约"：删了会静默坏掉

迁移时最容易踩的不是渲染，是**别的模块靠 DOM 找你这块东西**。
旧代码大量用 `$("#id")` 反查，Vue 一换渲染方式这些 id 就没了。
必须保留的、以及为什么：

| id / 结构 | 谁在读 | 丢了会怎样 |
|---|---|---|
| `#fmtPick`（**必须是原生 `<select>`**） | `main.js` 3 处 `fmt: $("#fmtPick").value` | 导出静默用错格式。n-select 渲成 `div`，`.value` 取到 `None` —— 踩过，`test_files_ui.py` 第 2 节有断言 |
| `#q` `#btnSearch`（**必须原生、且留在 Vue 容器之外**） | `main.js` 的 `$("#q")`、深链 `searchFromHash`、`test_buttons.py` A 组 | 搜索入口整个断掉。**故意没迁进 Vue** —— 见「发现页为什么是半迁移」。`test_discover_ui.py` 第 2 节有断言 |
| `#statbar` `#results` `#filters` `#homeEmpty` `#confirmBox` `#netLive` | `discover.js` 搜索流程 / `test_buttons.py` A 组 | 搜索整条链断。**已迁到 Vue**，id 由 `DiscoverPanel.vue` 渲染，`discover.js` 通过 `vueOwnsDiscover()` 让出写入权 |
| `#view-<name>` + `data-view` | `shell.js` 的 `nav()` 切 `.hidden` | 导航点了没反应 |
| `#shelfList` `#shelfEmpty` `#shelfStat` `#shelfN` | `shelf.js` / 真机测试 | 书架刷新失效 |
| `#fileList` `#fileEmpty` | `files.js` / 真机测试 | 文件列表不更新 |
| `#ranksBox` 等 | `ranks.js` / `test_ranks_ui.py` | 榜单不刷新 |
| 阅读器一大票 id：`#rdToc` `#rdSet` `#rdTocList` `#rdThemes` `#rdTocQ` `#rdTocClose` `#rdSetClose` `#rdTocBtn` `#rdSetBtn` `#rdBack` `#rdCacheBtn` `#rdExportBtn` `#rdProg` `#rdChap` `#rdSub` `#rdPct` `#rdTitle` `#rdFsRow`/`#rdLhRow`/`#rdFfRow`/`#rdWRow`/`#rdModeRow` + `[data-lh]`/`[data-fs]`/… | `reader.js`（`renderToc` 会 `$("#rdTocList").innerHTML=""`、`scrollTop`、`insertAdjacentHTML`；`setReaderField` 会写 `#rdChap` 等）、`test_reader_ui.py` / `test_buttons.py` D 组 | **静默死**。踩过两次：① `#rdTitle` 丢了 → `openReader()` 在 `renderToc()` 之前抛 TypeError → 目录永远空、正文不加载（阅读器"打开了"但全是空壳）；② `#rdTocClose` 丢了 → 测试里"先关面板"那步静默无效 → 下一步"点 ☰"反而关掉 → 看着像"☰ 坏了"。`test_reader_shell.py` 第 4 节逐个断言 |
| **面板内容靠 `v-html` 喂**（`#rdTocList` / `#rdThemes` 里的 HTML） | `reader.js` 生成 | v-html 的内容**不参与 Vue patch** —— 里面的 `.on` 必须**由生成方拼好**。踩过：切主题后色卡高亮不动（当时以为"theme 传过去 Vue 会 toggle"，实际没人用它） |

⚠ 判断"该不该用 Vue 实现"，看旧模块里有没有 `vueOwnsXxx()`
（`shelf.js` / `files.js` 各有一份）。它的语义是：
**容器在，就我（Vue）管；容器不在，旧实现顶上** ——
保证迁移期任一侧出问题页面都不会空白。

## 挂载模型（很重要，改之前先看这条）

**一个容器挂一个 app 实例**，不是"一个 App 挂到某一个 #vue-root"。

- `app/static/index.html` 里哪个容器带 `data-vue-*`，那块就归 Vue；
- `src/main.js` 的 `MOUNTS` 列出所有容器的选择器，
  对每个容器各 `createApp(App, { only: "<组件名>" })` + `mount`；
- `App.vue` 用 `only` 决定这个实例渲染哪个页面组件。

⚠ 为什么必须这样：Vue **只能把整棵树渲进一个元素**。
第一版是单挂载点（`#vue-root` 放在榜单区里），结果书架组件被渲进了
榜单区内部，`#view-shelf` 里的容器永远是空的 —— 页面看着"没生效"，
控制台一点错都没有（真踩过）。
`tools/test_shelf_ui.py` 第 1 节专门断言"书架在它该在的地方、没串到榜单区"。

⚠ 挂载点取哪个元素：`main.js` 用的是 `host.firstElementChild || host`
（容器里若嵌了一个专门的内层挂载点就用它，否则用容器自己）。
所以 `<section id="ranksBox" data-vue-ranks><div id="vue-root"></div></section>`
渲进内层 div，而 `<div data-vue-rdtop></div>` 这种空容器就渲进它自己。

⚠ 阅读器是**三个容器**（同一个页面上三处互不相邻的挂载区）——
它们各挂一个 app 实例，理由见上面的「阅读器为什么拆成三个组件」。
`test_reader_shell.py` 第 1 节断言三者的**顺序**（rdtop → stage → rdbottom），
因为 `#reader` 的纵向 flex 让"顺序"直接等于"布局"。
