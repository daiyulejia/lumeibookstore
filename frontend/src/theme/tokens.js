/**
 * 主题桥 · 把现有 tokens.css 的 CSS 变量喂给 Naive UI
 * ==========================================================================
 * 为什么要它：
 * 项目已经有**一套成熟的主题令牌系统**（`app/static/css/tokens.css`，
 * 7 套配色 × 表面/文字/强调/语义 四组变量）。Naive UI 自己也有主题体系
 * （JS 对象形式的 themeOverrides）。
 *
 * 如果不管它、让两套各跑各的，结果是：
 *   · Naive 的按钮是它自己的蓝，旁边手写的按钮是我们的橙 —— 两个牌子
 *   · 切主题时（比如切到 lumei-night）手写部分变了、Naive 组件没变
 *
 * 所以这里做**单向桥接**：CSS 变量 → Naive 主题对象。
 * 约定：CSS 变量是**唯一真相源**，Naive 只是消费方。
 * 以后加新主题只改 tokens.css，这个文件不用动。
 *
 * 实现要点：
 * 变量是运行时读的（getComputedStyle），所以：
 *   · 主题切换时必须重新生成一次 themeOverrides（见 useTheme()）
 *   · 深色主题要显式告诉 Naive `dark: true`，否则它的基础色阶还是浅色的
 */

/** 读一个 CSS 变量当前的计算值。 */
export function cssVar(name, fallback = "") {
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return v || fallback;
}

/** 深色主题名单 —— 决定 Naive 的 darkTheme 开关。 */
export const DARK_THEMES = new Set(["midnight", "obsidian", "lumei-night"]);

export function isDarkTheme(theme) {
  return DARK_THEMES.has(theme || "");
}

/**
 * 生成 Naive UI 的 themeOverrides。
 *
 * 只覆盖「我们在意的那些」——Naive 的默认值对没覆盖到的部分仍然生效，
 * 这样既保证了品牌一致，又不用把 Naive 每个组件的每个色都手写一遍
 * （那会变成一个永远追不上的维护负担）。
 */
export function buildOverrides() {
  return {
    common: {
      // 主色：我们的强调色，Naive 所有 primary 组件都吃它
      primaryColor: cssVar("--a-1", "#e8912f"),
      primaryColorHover: cssVar("--a-2", "#f6b95c"),
      primaryColorPressed: cssVar("--a-1", "#e8912f"),
      primaryColorSuppl: cssVar("--a-2", "#f6b95c"),

      // 语义色
      successColor: cssVar("--ok", "#5f9368"),
      warningColor: cssVar("--warn", "#c9902a"),
      errorColor: cssVar("--err", "#c9614c"),
      infoColor: cssVar("--info", "#5c82ab"),

      // 圆角体系直接用我们的令牌，避免 Naive 的默认圆角和手写部分对不上
      borderRadius: cssVar("--r-s", "10px"),
      borderRadiusSmall: cssVar("--r-xs", "6px"),

      // 文字与表面
      textColorBase: cssVar("--t-1", "#2f2620"),
      textColor1: cssVar("--t-1", "#2f2620"),
      textColor2: cssVar("--t-2", "#6d5f50"),
      textColor3: cssVar("--t-3", "#a1937f"),

      bodyColor: cssVar("--s-bg", "#fdf9f2"),
      cardColor: cssVar("--s-card", "#fffdf8"),
      modalColor: cssVar("--s-card", "#fffdf8"),
      popoverColor: cssVar("--s-card", "#fffdf8"),

      borderColor: cssVar("--s-line", "#eee0c9"),
      dividerColor: cssVar("--s-line-2", "#f7eedd"),

      // 字体：吃页面本身的字体栈，不硬编
      fontFamily: cssVar("--font-ui", "system-ui, sans-serif"),
      fontFamilyMono: "ui-monospace, SFMono-Regular, Menlo, monospace",
    },
    Button: {
      borderRadiusMedium: cssVar("--r-full", "999px"),
    },
    Input: {
      borderRadius: cssVar("--r-full", "999px"),
    },
    Card: {
      borderRadius: cssVar("--r-l", "20px"),
    },
  };
}

/** 拿到当前主题名（html[data-theme]）。 */
export function currentTheme() {
  return document.documentElement.getAttribute("data-theme") || "lumei";
}
