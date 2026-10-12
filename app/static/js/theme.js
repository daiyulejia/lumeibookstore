/* ==========================================================================
   主题 + 背景
   --------------------------------------------------------------------------
   配色是「主题」，纹理是「背景」，两者正交，可以任意组合。
   主题色值唯一来源是 css/tokens.css —— 这里是「菜单」，不是「菜谱」：
   只负责选哪个、记住选择、以及在面板里画出色卡预览。
   ========================================================================== */

import { $$, PRE } from "./util.js";
import { withThemeTransition } from "./motion.js";

/** 每个主题的预览色。和 tokens.css 里的值保持同步 —— 面板色卡靠它渲染。
 *
 *  ⚠ lumei 的色值必须与 tokens.css 的 `html[data-theme="lumei"]` 一致。
 *    曾经这里是旧的粉色（#ff6d8f），改 tokens 时忘了同步，
 *    结果「面板里是粉的、选完是橙的」—— 色卡就是给用户看的，不能骗人。
 */
export const THEMES = [
  { id: "lumei",       name: "噜妹",   dark: false, bg: "#fdf9f2", card: "#fffdf8", a1: "#e8912f", a2: "#f6b95c", fg: "#2f2620" },
  { id: "lumei-night", name: "黑糖噜妹", dark: true,  bg: "#1f1a14", card: "#2b2419", a1: "#f0a640", a2: "#f8c877", fg: "#f7efe2" },
  { id: "latte",    name: "拿铁",   dark: false, bg: "#f7f3ec", card: "#fffdfa", a1: "#c25627", a2: "#e2823f", fg: "#211d18" },
  { id: "mist",     name: "青雾",   dark: false, bg: "#f4f6f8", card: "#ffffff", a1: "#0f7c86", a2: "#1fa5ae", fg: "#161c22" },
  { id: "forest",   name: "松间",   dark: false, bg: "#f3f5f0", card: "#fdfefb", a1: "#3d7a3a", a2: "#5da05a", fg: "#1a2018" },
  { id: "sakura",   name: "樱雾",   dark: false, bg: "#faf5f6", card: "#fffcfd", a1: "#c2456f", a2: "#e07398", fg: "#221a1e" },
  { id: "midnight", name: "午夜",   dark: true,  bg: "#0d1017", card: "#161b26", a1: "#f5934f", a2: "#ffb87d", fg: "#e8ecf3" },
  { id: "obsidian", name: "曜石",   dark: true,  bg: "#08090c", card: "#121419", a1: "#8b7cf8", a2: "#a99cff", fg: "#eef1f6" },
];

export const BGS = [
  { id: "lumei",  name: "噜妹",   tip: "暖色光晕 + 极淡纸纹（本站主场）" },
  { id: "aurora", name: "光晕", tip: "三团缓慢漂移的柔光" },
  { id: "mesh",   name: "网格",   tip: "细网格 + 顶部淡出" },
  { id: "paper",  name: "纸纹",   tip: "细腻的纸张颗粒" },
  { id: "stars",  name: "星空",   tip: "极缓慢飘移的星点" },
  { id: "wave",   name: "波浪",   tip: "底部层叠的色波" },
  { id: "plain",  name: "纯净",   tip: "一块干净的底色" },
];

// 默认就用「噜妹」—— 这是本站的主场配色，不是第七套换肤
const AUTO_LIGHT = "lumei";
const AUTO_DARK = "lumei-night";

let media = null;

const isAuto = () => PRE.get("theme", "auto") === "auto";
const systemDark = () => window.matchMedia("(prefers-color-scheme: dark)").matches;

/** 把主题/背景应用到 <html>。返回当前**实际生效**的主题 id。 */
export function applyTheme() {
  const pref = PRE.get("theme", "auto");
  const id = pref === "auto" ? (systemDark() ? AUTO_DARK : AUTO_LIGHT) : pref;
  const bg = PRE.get("bg", "aurora");

  const root = document.documentElement;
  root.dataset.theme = id;
  root.dataset.bg = bg;

  // 让手机浏览器地址栏也跟着变，
  // 否则深色主题下顶部会横着一条刺眼的白条。
  const meta = document.querySelector('meta[name="theme-color"]');
  const t = THEMES.find(x => x.id === id);
  if (meta && t) meta.setAttribute("content", t.bg);
  return id;
}

/** 启动时调用一次。会监听系统深浅色变化（选了「跟随系统」才响应）。 */
export function initTheme() {
  applyTheme();
  media = window.matchMedia("(prefers-color-scheme: dark)");
  const onChange = () => { if (isAuto()) applyTheme(); };
  if (media.addEventListener) media.addEventListener("change", onChange);
  else media.addListener(onChange);
}

export function currentThemeId() {
  return document.documentElement.dataset.theme;
}

/* ---------- 面板 ---------- */
function themeCard(t) {
  const on = !isAuto() && currentThemeId() === t.id;
  return `<button class="themecard${on ? " on" : ""}" data-th="${t.id}">
    <div class="nm">${t.name}${t.dark ? " 🌙" : " ☀️"}<span class="ck">✓</span></div>
    <div class="sw">
      <i class="c1" style="background:${t.bg}"></i>
      <i class="c2" style="background:${t.card}"></i>
      <i class="c3" style="background:${t.fg}"></i>
      <i class="c4" style="background:linear-gradient(135deg,${t.a1},${t.a2})"></i>
    </div>
  </button>`;
}

function bgCard(b) {
  const on = PRE.get("bg", "aurora") === b.id;
  return `<button class="bgcard${on ? " on" : ""}" data-bg="${b.id}" title="${b.tip}">
    <div class="pv" data-pv="${b.id}"></div>
    <div class="nm">${b.name}</div>
  </button>`;
}

/**
 * 主题面板。
 * 色卡是**按真实色值渲染**的，不是截图 —— 改 tokens.css 这里自动跟着变，
 * 不会出现「面板里好看、选完发现不一样」。
 */
export function themePanelHTML() {
  const auto = isAuto();
  return `
    <div style="display:flex;flex-direction:column;gap:20px">
      <div>
        <div style="font-size:12px;font-weight:750;color:var(--t-3);margin-bottom:10px;letter-spacing:.04em">配色</div>
        <div class="themegrid">
          <button class="themecard${auto ? " on" : ""}" data-th="auto">
            <div class="nm">跟随系统<span class="ck">✓</span></div>
            <div class="sw">
              <i class="c1" style="background:linear-gradient(135deg,#f7f3ec 50%,#0d1017 50%)"></i>
              <i class="c2" style="background:#fffdfa"></i>
              <i class="c3" style="background:#161b26"></i>
              <i class="c4" style="background:linear-gradient(135deg,#c25627,#f5934f)"></i>
            </div>
          </button>
          ${THEMES.map(themeCard).join("")}
        </div>
      </div>

      <div>
        <div style="font-size:12px;font-weight:750;color:var(--t-3);margin-bottom:10px;letter-spacing:.04em">背景</div>
        <div class="bggrid">${BGS.map(bgCard).join("")}</div>
      </div>

      <div style="font-size:12px;color:var(--t-3);line-height:1.75;padding-top:4px;border-top:1px solid var(--s-line-2)">
        阅读器有<b>自己独立的配色</b>（看书时想要的和逛书店时不一样）——
        进书以后点右上角 <b>Aa</b> 调。
      </div>
    </div>`;
}

/** 面板里的点击绑定。面板 DOM 由 shell 的 openDrawer 提供。
 *
 *  ⚠ 切换必须走 withThemeTransition()：
 *    换主题是「同一个界面的两个状态」，硬切会像闪了一下；
 *    而全站常驻 transition 又会让滚动/翻页掉帧。
 *    所以只在切换那一刻开插值，切完就摘。
 */
export function bindThemePanel(root, onChanged) {
  $$("[data-th]", root).forEach(b => b.onclick = () => {
    PRE.set("theme", b.dataset.th);
    withThemeTransition(() => {
      applyTheme();
      $$("[data-th]", root).forEach(x => x.classList.toggle("on", x === b));
    });
    onChanged?.();
  });
  $$("[data-bg]", root).forEach(b => b.onclick = () => {
    PRE.set("bg", b.dataset.bg);
    withThemeTransition(() => {
      applyTheme();
      $$("[data-bg]", root).forEach(x => x.classList.toggle("on", x === b));
    });
    onChanged?.();
  });
}
