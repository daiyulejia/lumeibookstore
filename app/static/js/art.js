/* ==========================================================================
   噜妹素材 · 状态映射
   --------------------------------------------------------------------------
   为什么单独一个模块：素材「用在哪」是个**设计决策**，不是某个页面的私事。
   散在各页面里写 <img src="/static/img/lumei/xxx.webp"> 的话：
     · 同一个状态在两个页面会配不同的图（看着像两个人做的）
     · 换素材要全局搜路径
     · 没法一眼看出"哪些素材还没用上"

   所以这里做两件事：
     1. 用**状态名**索引素材（不是文件名）—— 调用方说"我要一个加载态"
     2. 提供降级：非噜妹主题下自动换成中性表达，不留品牌痕迹

   ⚠ 「状态 → 图」的挑选标准见 docs/design-spec-lumei.md §3.3：
      必须与情绪对得上。空书架是"睡得香"，找不到书是"懵"，
      不是随便一张好看的图。
   ========================================================================== */

import { esc } from "./util.js";

const DIR = "/static/img/lumei";

/** 状态 → 素材规格。
 *
 *  w/h 是 @480 档的真实像素（严格按素材原始比例，写错会让浏览器预留错高度，
 *  表现为加载时"跳一下"）。
 *  mood 是这张图传达的情绪 —— 换素材时拿它当验收标准。
 */
const ART = {
  /* 空状态 */
  empty_wait:   { file: "empty_wait",   w: 480, h: 360, mood: "等你来搜" },
  empty_sleep:  { file: "empty_sleep",  w: 480, h: 360, mood: "睡得正香" },
  empty_lonely: { file: "empty_lonely", w: 480, h: 360, mood: "有点想书" },

  /* 加载 */
  loading_read:  { file: "loading_read",  w: 480, h: 360, mood: "正在找，不着急" },
  loading_drink: { file: "loading_drink", w: 480, h: 360, mood: "等一会儿，先喝点" },

  /* 错误 */
  error_confused: { file: "error_confused", w: 480, h: 360, mood: "懵了，没找到" },
  error_sad:      { file: "error_sad",      w: 480, h: 360, mood: "算了吧，明天再找" },

  /* 阅读页。
     ⚠ 这两张不通过 artHTML() 调用 —— 它们在 CSS 里当背景用：
        read_pair 做「读完一章」的收尾标记，read_eat 做阅读配色色卡的角标。
        原因见 lumei.css §5：分页要靠量段落位置，插 <img> 会把页码算错；
        背景不占高度，是唯一安全的选择。*/
  read_pair: { file: "read_pair", w: 480, h: 360, mood: "两只靠在一起（CSS 用在章末）" },
  read_eat:  { file: "read_eat",  w: 480, h: 360, mood: "边吃边看（CSS 用在色卡角标）" },
};

/** 只在 CSS 里使用的素材 —— 静态检查靠它区分"孤儿"和"CSS 引用"。 */
export const CSS_ONLY = new Set(["read_pair", "read_eat"]);

/** 由 index.html 直引的素材（首页 Hero 是它自己的布局，不走 st-art 体系）。 */
export const HTML_ONLY = new Set(["hero_lulu", "hero_lumei"]);

/** 取某张状态的图片 URL（含 @240/@480 两档 srcset）。 */
export function artUrl(key, size = 480) {
  const a = ART[key];
  if (!a) return "";
  return `${DIR}/${a.file}${size === 480 ? "@480" : size === 240 ? "@240" : ""}.webp`;
}

/**
 * 渲染一张状态插画。
 *
 * @param key    ART 里的键（状态名）
 * @param size   "s" | "m" | "l"  —— 对应 lumei.css §2.1 的三档
 * @param cls    额外类名
 *
 * 用 <img> 而不是 CSS background：需要 alt（无障碍）+ srcset（省流量）+
 * decoding=async（不阻塞主线程）。背景图这三样都给不了。
 */
export function artHTML(key, size = "m", cls = "") {
  const a = ART[key];
  if (!a) return "";
  return `<img class="st-art ${size} ${cls}" src="${artUrl(key, 480)}"
    srcset="${artUrl(key, 240)} 240w, ${artUrl(key, 480)} 480w"
    sizes="${size === "s" ? "132px" : size === "l" ? "252px" : "196px"}"
    width="${a.w}" height="${a.h}" alt="" loading="lazy" decoding="async">`;
}

/**
 * 加载态：图 + 一行说明 +（可选）一行补充。
 *
 * ⚠ 上一版阅读器里是三个跳动的圆点（.rd-dots）。
 *    那东西的问题不是丑，是**没有信息**：用户不知道在等什么、还要多久。
 *    换成"噜噜在翻书"之后，至少传达了两件事 —— 在动、在找书。
 */
export function busyHTML({ key = "loading_read", line = "正在找…", sub = "", compact = false } = {}) {
  return `<div class="st-busy${compact ? " compact" : ""}">
    ${artHTML(key, compact ? "s" : "m")}
    <div class="st-line">${esc(line)}</div>
    ${sub ? `<div class="st-sub">${esc(sub)}</div>` : ""}
  </div>`;
}

/**
 * 错误态：图 + 标题 + 说明（+ 调用方自己接按钮）。
 *
 * 文案原则：**说人话，给出下一步**。
 * "HTTP 500" 对用户没有意义；"这一章没取到，过会儿点重试"才有。
 */
export function failHTML({ key = "error_confused", line = "出了点问题", sub = "" } = {}) {
  return `<div class="st-fail">
    ${artHTML(key, "m")}
    <div class="st-line">${esc(line)}</div>
    ${sub ? `<div class="st-sub">${esc(sub)}</div>` : ""}
  </div>`;
}

/** 列出所有已定义的状态键 —— 给"素材有没有闲着的"这类检查用。 */
export function artKeys() { return Object.keys(ART); }

/* ==========================================================================
   首页 Hero：噜噜/噜妹**每天轮换**
   --------------------------------------------------------------------------
   为什么要它：一对固定的图看久了就成了"背景板"，用户不会再注意到它们。
   每天换一张（按日期取模，不需要服务端、不需要存储），
   让"今天的噜噜"变成一个每天会变的小惊喜 —— 成本几乎为零。

   ⚠ 几个必须守住的点：
     1. **不能随机**（`Math.random()`）—— 每次刷新都换会显得"闪"、像没加载稳。
        按**日期**取模：同一天上午下午看到的都一样，跨天变一次。
     2. 只换 `src`/`srcset`，**不动 width/height**：所有素材宽高比一致
        （都是 480×360），改尺寸会让页面跳一下。
     3. 轮换单位是**一整对**，不是单张 —— 池子里每项是 `左|右`。
        理由见 index.html 那段注释：素材分"特写"和"场景"两类取景，
        左右各自随机挑会挑出"一大头 + 一远景"，不成一对。
     4. 只在噜妹主题下显示（非噜妹主题 `.lu-duo` 本来就被隐藏）。

   池子来自 `data-hero-pool`（写在 HTML 上，方便运营直接改 HTML 增删候选，
   不用回来改 JS）。格式：`左键|右键,左键|右键,...`
   ========================================================================== */

/** 取"今天是第几天"（本地时区，从 Unix 纪元算起）。
 *  用本地时区而不是 UTC：用户的"今天"应该是他自己的今天。 */
function dayIndex() {
  const d = new Date();
  return Math.floor((d.getTime() - d.getTimezoneOffset() * 60000) / 86400000);
}

/**
 * 按日期给首页 Hero 的那一对图轮换素材。
 *
 * @param root  容器（默认取 `[data-hero-pool]`）；没找到就静默返回。
 */
export function rotateHeroArt(root = null) {
  const dup = root || document.querySelector("[data-hero-pool]");
  if (!dup) return;

  // 解析 `左|右,左|右,...`；任何一侧缺失/非法就丢掉这一对（宁可少一天候选，
  // 也不显示半张空图）。
  const pairs = (dup.dataset.heroPool || "")
    .split(",")
    .map(s => s.trim())
    .filter(Boolean)
    .map(s => s.split("|").map(x => x.trim()))
    .filter(p => p.length === 2 && ART[p[0]] && ART[p[1]]);
  if (!pairs.length) return;               // 池子为空：保留 HTML 里的兜底图

  const imgs = dup.querySelectorAll("[data-hero-role]");
  if (imgs.length < 2) return;

  const [lk, rk] = pairs[dayIndex() % pairs.length];
  const assign = (img, key) => {
    const base = `${DIR}/${ART[key].file}`;
    img.src = `${base}@480.webp`;
    img.srcset = `${base}@240.webp 240w, ${base}@480.webp 480w`;
  };
  assign(imgs[0], lk);
  assign(imgs[1], rk);
}

