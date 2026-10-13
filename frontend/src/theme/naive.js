/**
 * Naive UI 安装器 + 主题响应
 * ==========================================================================
 * 两件事：
 *  1) 全局注册 Naive 的主题配置（此时读一遍 CSS 变量）
 *  2) **监听主题切换**并重新生成 overrides
 *
 * 第 2 点是关键，也是最容易漏的：
 * Naive 的 themeOverrides 是**一次性快照**（构建时读的值）。
 * 用户在「外观」面板切到 lumei-night 时，手写 CSS 部分立刻变色，
 * 但 Naive 组件会停留在旧配色 —— 看起来像"一半主题坏了"。
 * 所以这里挂一个 MutationObserver 盯 `<html data-theme>`，
 * 变了就重新算一遍所有 overrides。
 */
import { NConfigProvider, darkTheme, lightTheme } from "naive-ui";
import { buildOverrides, currentTheme, isDarkTheme } from "./tokens.js";

/** 全局响应式的主题状态 —— NConfigProvider 直接绑它。 */
export const themeState = {
  theme: null, // Naive 的 darkTheme / lightTheme 对象
  overrides: {},
};

function refresh() {
  const name = currentTheme();
  themeState.theme = isDarkTheme(name) ? darkTheme : lightTheme;
  themeState.overrides = buildOverrides();
}

export function installLumeiTheme(app) {
  refresh();

  // ⚠ 主题切换要重算 overrides，否则 Naive 组件不跟着变。
  //   观察 <html> 的 data-theme 属性变化即可（theme.js 就是改这个属性）。
  const mo = new MutationObserver(() => {
    const before = themeState.overrides?.common?.primaryColor;
    refresh();
    if (themeState.overrides?.common?.primaryColor !== before) {
      // 触发 Vue 重渲染（themeState 是普通对象，这里手动通知）
      app._instance?.proxy?.$forceUpdate?.();
    }
  });
  mo.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });

  // 暴露给旧代码：切主题后可以主动喊一声
  window.__lumeiRefreshTheme = refresh;

  app.config.globalProperties.$nTheme = themeState;
}

export { NConfigProvider };
