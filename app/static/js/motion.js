/* ==========================================================================
   动效编排
   --------------------------------------------------------------------------
   CSS 层（motion.css）负责"怎么动"，这里负责"什么时候动"。

   分工的边界很清楚：
     · 能用 CSS 表达的（hover / active / keyframes）→ 交给 CSS，零 JS 开销
     · 需要知道"第几个""进了视口没""主题切换的起止时刻" → 这里做

   全部是**增强**：任何一段失败都不影响功能，最坏情况只是少一层动效。
   所以每个装饰动作都包了 try —— 动效不该有能力弄坏业务。
   ========================================================================== */

import { $$, throttle } from "./util.js";

/** 系统是否要求减少动效。动效层所有判断都走这里，避免各处各写一遍。 */
export function reduceMotion() {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; }
  catch { return false; }
}

/* ==========================================================================
   1. 错峰：把"第几个"写进 --mo-i
   --------------------------------------------------------------------------
   为什么用 JS 而不是纯 CSS 的 nth-child：
     列表是 innerHTML 一次性写进去的，长度不定；写 12 条 nth-child 规则
     既啰嗦又容易和别的列表打架。直接注入一个变量最省事。

   ⚠ 只在"刚写完列表"时调一次。重复调用要把计数重置，
      否则第二次渲染会从上次的序号接着排，延迟越滚越大。
   ========================================================================== */
export function stagger(root, sel) {
  const list = $$(sel, root || document);
  list.forEach((el, i) => {
    // 上限 12：第 20 张卡片还在延迟入场，用户会觉得"卡"
    el.style.setProperty("--mo-i", String(Math.min(i, 12)));
  });
  return list.length;
}

/* ==========================================================================
   2. 涟漪：点到即反馈
   --------------------------------------------------------------------------
   挂在**按压**（pointerdown）而不是点击（click）上 —— 反馈必须跟上手指，
   等 click 会慢半拍，等接口回来就更晚了。
   用事件委托挂一次，覆盖所有现成和将来动态插入的按钮。
   ========================================================================== */
const RIP_SEL = ".btn, .chip, .rk-tab, .stab, .rtab, .mini, .rk-item, .themecard, .bgcard, .iconbtn";

export function mountRipple(root = document) {
  if (reduceMotion()) return;

  root.addEventListener("pointerdown", e => {
    // 只认主键 / 触摸，右键菜单不触发
    if (e.button !== 0) return;
    const hit = e.target.closest?.(RIP_SEL);
    if (!hit || hit.disabled || hit.classList.contains("disabled")) return;

    try {
      const r = hit.getBoundingClientRect();
      hit.style.setProperty("--rx", (e.clientX - r.left) + "px");
      hit.style.setProperty("--ry", (e.clientY - r.top) + "px");
      hit.classList.add("mo-rip");
      // 动画跑完摘掉类：不摘的话第二次按下不会重放（类名没变，动画不重启）
      const off = () => { hit.classList.remove("mo-rip"); hit.removeEventListener("animationend", off); };
      hit.addEventListener("animationend", off);
      // 兜底：动画事件万一没来（元素被移除等），也要摘
      setTimeout(() => hit.classList.remove("mo-rip"), 700);
    } catch {}
  }, { passive: true });
}

/* ==========================================================================
   3. 滚动联动
   --------------------------------------------------------------------------
   给长列表的条目挂 .mo-reveal，进入视口打 .mo-in。
   过场只播一次（unobserve），不是每次滚动都重播 —— 那是十年前的效果。
   ========================================================================== */
let _io = null;
function io() {
  if (_io) return _io;
  _io = new IntersectionObserver(entries => {
    entries.forEach(en => {
      if (!en.isIntersecting) return;
      en.target.classList.add("mo-in");
      _io.unobserve(en.target);
    });
  }, {
    // 提前 60px 触发：等真进了视口才开始动，会有"追不上"的滞后感
    rootMargin: "0px 0px -60px 0px",
    threshold: 0.01,
  });
  return _io;
}

export function revealOnScroll(root, sel) {
  if (reduceMotion()) {
    $$(sel, root || document).forEach(el => el.classList.add("mo-in"));
    return;
  }
  try { $$(sel, root || document).forEach(el => io().observe(el)); } catch {}
}

/* ==========================================================================
   4. 主题切换过渡
   --------------------------------------------------------------------------
   切主题时给 <html> 挂 .mo-theming，让色值插值过去，切完摘掉。

   为什么不当成永久规则：带上 transition 的 * 选择器会让每一次重绘都走插值，
   滚动、翻页这种高频场景直接掉帧。只在切换那一刻开，是"按需付费"。
   ========================================================================== */
let _themeTimer = null;
export function withThemeTransition(fn) {
  if (reduceMotion()) { fn?.(); return; }
  const html = document.documentElement;
  html.classList.add("mo-theming");
  try { fn?.(); } catch (e) { console.error(e); }
  clearTimeout(_themeTimer);
  // 稍长于 --mo-scene，保证插值跑完再摘（早摘会看到"最后一下跳变"）
  _themeTimer = setTimeout(() => html.classList.remove("mo-theming"), 500);
}

/* ==========================================================================
   5. 数字滚动
   --------------------------------------------------------------------------
   给统计数字一个"到位"的信号。只做插值 + 一次轻微上浮，
   不做那种一长串数字滚动的花活 —— 那是展示用的，不是工具该有的。
   ========================================================================== */
export function tickNumber(el, value) {
  if (!el) return;
  const s = String(value);
  if (el.textContent === s) return;
  el.textContent = s;
  if (reduceMotion()) return;
  el.classList.remove("mo-tick");
  // 强制重排，让同名动画能重放
  void el.offsetWidth;
  el.classList.add("mo-tick");
  const off = () => { el.classList.remove("mo-tick"); el.removeEventListener("animationend", off); };
  el.addEventListener("animationend", off);
}

/* ==========================================================================
   6. 滚动时顶栏收缩
   --------------------------------------------------------------------------
   参考对象的一个共同点：**滚动会让外壳变得更紧凑**，把空间让给内容。
   手机上这一条尤其值钱 —— 58px 的顶栏在 6 寸屏上是很大的占比。
   ========================================================================== */
export function mountScrollChrome() {
  const bar = document.querySelector(".topbar");
  if (!bar) return;
  const onScroll = throttle(() => {
    bar.classList.toggle("shrunk", window.scrollY > 24);
  }, 120);
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
}

/* ==========================================================================
   7. 一次性初始化
   ========================================================================== */
export function initMotion() {
  try {
    mountRipple();
    mountScrollChrome();
  } catch (e) { console.error("动效层初始化失败（不影响功能）:", e); }
}

/* 迁移桥：把 stagger 暴露给新的 Vue 侧复用同一份实现（理由见 util.js 末尾）。 */
window.__lumeiLegacy = Object.assign(window.__lumeiLegacy || {}, { stagger });
