/* ==========================================================================
   搜索历史下拉 —— 让「搜过什么」不用再敲第二遍
   ==========================================================================

   为什么要有它
   ------------
   搜索是这个站唯一的入口，此前每次都得重新敲一遍书名。
   后端已经把搜索词变成了**持久数据**（见 app/history.py、/api/history/search），
   这一层负责把它变成可见的、能点的东西：

     · 输入框**聚焦**时，下拉出最近搜过的词（按时间倒序）
     · 点一下就填进去并直接搜 —— 复搜常用书从"敲 5 个字"变成"点一下"
     · 每条右侧有个小 × 单独删；顶部有"清空"
     · 输入框有内容时，下拉会**按当前输入过滤**（等于本地联想）

   设计约束（踩过的坑写在这里，免得下次重犯）
   -----------------------------------------
   · **下拉不能挡住搜索**：`blur` 时立即收起。但如果点的是下拉里的条目，
     blur 会先于 click 触发，导致"人还没点到，框已经收了" —— 经典坑。
     解法是把收起**延迟一帧**（setTimeout 0），让 click 先跑完。
   · **键盘可用**：↑↓ 选、Enter 确认、Esc 收起。鼠标能做的键盘也要能做。
   · **绝不打扰**：拉不到历史就静默什么都不显示，不 toast、不报错。
     历史是"锦上添花"，后端挂了不该让搜索框变成砖头。
   · **不缓存**：每次聚焦都重新拉。历史变化很频繁（自己刚搜完就变），
     缓存反而会出现"刚搜的词不在列表里"的怪现象。

   与 /api/search 的配合
   --------------------
   搜索成功后后端会自动记一条，所以这里**不需要**在提交时手动上报 ——
   那是后端的事，前端只管展示。这也避免了"前端记一次、后端记一次"的重复计数。
   ========================================================================== */

import { $, api, esc, confirmBox } from "./util.js";

const MAX_SHOW = 8;

let _box = null;      // 下拉容器
let _input = null;    // 搜索输入框
let _items = [];      // 当前展示的历史（原始对象，按时间倒序）
let _active = -1;     // 键盘高亮的下标（-1 = 没选）
let _open = false;

/* 拉最近搜索历史。失败返回空数组（静默）。 */
async function fetchRecent() {
  try {
    const r = await api.get("/api/history/search?limit=20");
    const items = (r && r.items) || [];
    return items.filter(it => it && it.kw);
  } catch {
    return [];
  }
}

/* 按当前输入过滤。空输入 = 全部。 */
function filtered() {
  const q = (_input && _input.value || "").trim().toLowerCase();
  if (!q) return _items.slice(0, MAX_SHOW);
  return _items.filter(it => it.kw.toLowerCase().includes(q)).slice(0, MAX_SHOW);
}

function close() {
  if (!_box) return;
  _box.hidden = true;
  _open = false;
  _active = -1;
}

/* ⚠ 这个"延迟收起"是必需的，不是保守写法：
   mousedown 在下拉条目上 → input 先收到 blur → 若这里同步 close()，
   下拉消失、条目被移除，随后的 click 落在一个已经不在 DOM 的元素上 ——
   点上去像"没反应"。延迟到下一帧，click 就能正常跑完。 */
function closeSoon() {
  setTimeout(() => {
    // 只有真的失焦才收（点下拉里的按钮时焦点还在下拉内）
    if (document.activeElement && _box && _box.contains(document.activeElement)) return;
    close();
  }, 120);
}

function render() {
  if (!_box) return;
  const list = filtered();
  if (!list.length) { close(); return; }

  _box.innerHTML =
    `<div class="h-head"><span>最近搜索</span>`
    + `<button type="button" class="h-clear" data-act="clear">清空</button></div>`
    + list.map((it, i) => {
        // ⚠ hits=0 的词加个标记：它意味着"搜过但一本都没找到"，
        //   是**书库缺口**的直接线索。让用户也能看到，而不是只藏在后台统计里。
        const miss = Number(it.hits || 0) <= 0 ? `<i class="h-miss" title="上次没找到">无结果</i>` : "";
        return `<button type="button" class="h-item${i === _active ? " on" : ""}"`
          + ` data-i="${i}" data-kw="${esc(it.kw)}">`
          + `<span class="h-kw">${esc(it.kw)}</span>${miss}`
          + `<span class="h-x" data-act="del" data-kw="${esc(it.kw)}" title="删掉这条">×</span>`
          + `</button>`;
      }).join("");

  _box.hidden = false;
  _open = true;
}

/* 下拉里的点击：命中 / 删除 / 清空 */
function onBoxClick(e) {
  const t = e.target;
  if (!t || !t.closest) return;

  const act = t.getAttribute("data-act");

  if (act === "clear") {
    e.preventDefault();
    clearAll();
    return;
  }

  if (act === "del") {
    e.preventDefault();
    // ⚠ stopPropagation：不然删完还会冒泡到条目的"命中"逻辑，变成删完顺手又搜一次
    e.stopPropagation();
    const kw = t.getAttribute("data-kw") || "";
    delOne(kw);
    return;
  }

  const item = t.closest(".h-item");
  if (!item) return;
  e.preventDefault();
  pick(item.getAttribute("data-kw") || "");
}

/* 点一个历史词：填进去 + 触发搜索。
   ⚠ 这里**不直接调 runSearch**（那会把 discover 与本模块耦合死），
   而是给输入框设值后派发一次 Enter —— 走的还是用户敲回车那条路。
   好处：确认书名/直链判断等所有既有逻辑自动生效，不用重复实现。 */
function pick(kw) {
  if (!kw || !_input) return;
  _input.value = kw;
  close();
  _input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
}

async function delOne(kw) {
  // 先从本地列表拿掉（乐观更新，点下去立刻见效），再去请求后端
  _items = _items.filter(it => it.kw !== kw);
  // ⚠ 必须重置高亮下标。删掉的可能是当前高亮那条，`_active` 会指向
  //   已经不存在的位置；下一次回车就会 `list[_active].kw` 取到 undefined
  //   而抛 TypeError（不重置的话，症状是"删了一条再按回车，控制台报错、
  //   输入框什么都没发生"）。
  _active = -1;
  render();
  // ⚠ 用**查询参数**而不是路径段：书名带斜杠很常见（"哈利波特/魔法石"），
  //   而路径参数里 `%2F` 会被 Starlette 解码后拿去匹配路由 → 404。
  //   见 app/main.py 里 history_search_clear 的 docstring。
  try { await api.del("/api/history/search?kw=" + encodeURIComponent(kw)); } catch {}
}

async function clearAll() {
  // ⚠ 必须二次确认。理由有两层：
  //   ① 这是**不可逆**的（服务端不做软删、不留备份，删了就真没了）；
  //   ② 按钮就在搜索框正下方，比统计页签那两个更容易误触 ——
  //      而统计面板里同样的动作是要确认的，两处不一致本身也是产品问题。
  //   确认框是异步的，期间下拉会因 blur 收起，所以确认后再处理。
  if (!(await confirmBox({
    title: "清空搜索历史？",
    message: "搜过的词会全部忘掉，无法恢复。",
    okText: "清空", danger: true,
  }))) {
    if (_input) _input.focus();
    return;
  }
  _items = [];
  close();
  try { await api.del("/api/history/search"); } catch {}
  if (_input) _input.focus();
}

/* 键盘：↑↓ 移动、Enter 确认、Esc 收起 */
function onKey(e) {
  if (!_open) return;
  const list = filtered();
  if (!list.length) return;

  if (e.key === "ArrowDown") {
    e.preventDefault();
    _active = (_active + 1) % list.length;
    render();
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    _active = _active <= 0 ? list.length - 1 : _active - 1;
    render();
  } else if (e.key === "Enter" && _active >= 0) {
    // ⚠ 有高亮时拦截回车（用历史词搜），没高亮就放行给原来的提交逻辑。
    //   不拦的话会出现"上下选了半天，一回车搜的却是输入框里的旧文本"。
    //   `_active` 的越界保护：列表可能在高亮之后变短（比如刚删了一条），
    //   直接 `list[_active].kw` 会抛 TypeError。
    const it = list[_active];
    if (!it) { _active = -1; return; }
    e.preventDefault();
    e.stopPropagation();
    pick(it.kw);
  } else if (e.key === "Escape") {
    close();
  }
}

/** 装到搜索框上。main.js 启动时调一次。 */
export function mountHistory() {
  const input = $("#q");
  if (!input) return;                    // 没有搜索框（比如纯书架页）就不装

  _input = input;

  // 下拉容器：**必须包一层 .h-wrap 再放进去**。
  //   · 直接塞进 .searchbox 不行 —— 它是 flex 容器，下拉会被当成第三个
  //     格子，把输入框和按钮挤变形；
  //   · 直接插在 .searchbox 后面也不行 —— 那样 `position:absolute` 会去
  //     找更外层的定位祖先（.hero / .wrap），left:0/right:0 就跑到整页宽了。
  //   包一层 relative 的 .h-wrap 把两者圈在一起，下拉才能正好对齐搜索框。
  const box = document.createElement("div");
  box.className = "h-drop";
  box.hidden = true;

  const host = input.closest(".searchbox") || input.parentElement;
  const wrap = document.createElement("div");
  wrap.className = "h-wrap";
  if (host && host.parentElement) {
    host.parentElement.insertBefore(wrap, host);
    wrap.appendChild(host);        // 把 .searchbox 挪进 wrap
    wrap.appendChild(box);
  }
  _box = box;

  box.addEventListener("mousedown", e => e.preventDefault());  // 别让点击抢走焦点
  box.addEventListener("click", onBoxClick);
  input.addEventListener("focus", async () => {
    _items = await fetchRecent();
    _active = -1;
    render();
  });
  input.addEventListener("input", () => {
    if (!_items.length) return;
    _active = -1;
    render();
  });
  input.addEventListener("keydown", onKey);
  input.addEventListener("blur", closeSoon);
}
