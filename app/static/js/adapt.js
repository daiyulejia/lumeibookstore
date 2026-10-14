/* ==========================================================================
   站点适配向导
   --------------------------------------------------------------------------
   设计原则：**每一步都说人话**。
     · 「我在干什么」—— 标题用动词描述，不出现正则/解析器这类词
     · 「为什么要干」—— 一句话说清这步在整个流程里的位置
     · 「看到了什么」—— 具体数字，不糊弄
     · 「卡住了怎么办」—— 失败时给可照做的建议，而不是只抛错误码

   进度是**流式**的：后端每跑完一步就推一条事件过来，界面跟着点亮。
   否则用户要盯着空白等 20 秒，会以为死机了。
   ========================================================================== */

import { $, $$, esc, api, toast, openDrawer } from "./util.js";

/* 步骤名 → 人话。后端也会给一份（以服务端为准），这里只是兜底。 */
const FALLBACK = {
  "打开首页":        { t: "打开这个网站的首页", w: "先确认站还活着、是中文小说站，顺便看出它用什么建站系统" },
  "回到站点首页":    { t: "回到这个网站的首页", w: "你给的是某一本书的页面，我顺着页面上「首页」的链接自己回到了站首页" },
  "找搜索接口":      { t: "找出它的搜索怎么用", w: "知道搜索地址，才能用书名去这个站里找书" },
  "打开搜索页":      { t: "试着搜一本书", w: "用一个真实书名试搜，看它返回什么" },
  "推导搜索条目":    { t: "看懂搜索结果长什么样", w: "从搜索结果里认出「哪一条是书」" },
  "打开详情页":      { t: "点进这本书的详情页", w: "书籍详情页一般挂着完整目录" },
  "推导目录正则":    { t: "读出这本书的目录", w: "拿到章节清单，才能一章一章下" },
  "打开章节页":      { t: "打开其中一章", w: "验证真的能读到正文，而不是只有标题" },
  "推导正文正则":    { t: "把正文抠出来", w: "从整页 HTML 里分出「哪些字是小说的」" },
  "发现章节分页":    { t: "发现这站一章分了好几页", w: "有些站一章拆成 2~3 页，不拼起来会缺一半" },
  "保存配置":        { t: "把这个网站记下来", w: "写进站点列表之后，以后用书名搜索就能用到它" },
  "完成":            { t: "适配完成", w: "配置已保存，可以像内置来源一样搜书了" },
};

let streamCtrl = null;

export function openAdapt() {
  openDrawer({
    id: "adaptDrawer",
    title: "接入一个新网站",
    body: `
      <div class="wiz">
        <div class="lead">
          <span class="ic">🔌</span>
          <b>给我一个小说网站的网址，我去研究它。</b><br>
          我会真的在那个站上搜一本书、点进目录、打开一章，
          把它的结构摸清楚 —— 摸清了就存下来，以后它就是一个可搜索的来源。
          <br><br>
          摸不清也没关系，我会告诉你卡在哪一步、为什么。
        </div>

        <div class="flow">
          <span><i>1</i>你给网址</span>
          <span><i>2</i>我跑一遍</span>
          <span><i>3</i>能用就存下</span>
        </div>

        <div class="field">
          <label>① 网站地址</label>
          <input id="adaptUrl" type="text" placeholder="https://www.example.com" autocomplete="off" spellcheck="false"/>
          <div class="help">
            <b>首页、某一本书的页面、正在读的那一章 —— 给哪个都行。</b><br>
            你要是不小心粘了书页，我会自己顺着页面上的「首页」回到站首页，<b>不用你改</b>。
            浏览器地址栏里直接复制过来就行，比如 <code>https://www.xbiquge.info</code>。
          </div>
        </div>

        <div class="field">
          <label>② 用哪本书来试（随便一本这个站肯定有的）</label>
          <input id="adaptKw" type="text" value="斗破苍穹" autocomplete="off"/>
          <div class="help">
            我要拿一个真实书名去试搜，才能知道搜索功能怎么用。
            输一本<b>热门书</b>最稳 —— 冷门书可能这个站压根没有，那就没法测了。
          </div>
        </div>

        <button class="btn primary block lg" id="adaptGo">开始研究这个网站</button>
        <div id="adaptOut"></div>
      </div>`,
    onMount: d => {
      const go = $("#adaptGo", d.el);
      go.onclick = runAdapt;
      $$("#adaptUrl, #adaptKw", d.el).forEach(i =>
        i.addEventListener("keydown", e => { if (e.key === "Enter") runAdapt(); }));
      setTimeout(() => $("#adaptUrl", d.el)?.focus(), 120);
    },
  });
}

function stepOf(name) {
  return FALLBACK[name] || { t: name, w: "" };
}

/** 渲染一条步骤。state: wait | yes | no */
function stepHTML(name, state, detail, server) {
  const meta = server || stepOf(name);
  const icon = state === "yes" ? "✓" : state === "no" ? "✕" : "·";
  return `<div class="step ${state}">
    <span class="si">${icon}</span>
    <span class="st">
      <b>${esc(meta.t || name)}</b>
      ${meta.w ? `<span style="color:var(--t-3)">${esc(meta.w)}</span>` : ""}
      ${detail ? `<span>${esc(detail)}</span>` : ""}
    </span>
  </div>`;
}

/** 还没跑到的步骤，先摆出灰的占位，让用户知道总共有几步。 */
// 还没走到的步骤（灰条）。
// ⚠ 必须**排除已经走过的**：用户粘的是某本书的页面时，后端会直接拿它当详情页、
//   跳过搜索那两步（见 adapter._detail_via_page）—— 不过滤的话它们会永远
//   挂在灰条里，看起来像"卡住了"。
function pendingHTML(done) {
  const have = new Set(done || []);
  const order = ["回到站点首页", "打开首页", "找搜索接口", "推导搜索条目", "推导目录正则", "推导正文正则"];
  return order.filter(n => !have.has(n)).map(n => {
    const m = stepOf(n);
    return `<div class="step"><span class="si">·</span>
      <span class="st"><b style="color:var(--t-3)">${esc(m.t)}</b></span></div>`;
  }).join("");
}

async function runAdapt() {
  const url = $("#adaptUrl").value.trim();
  const kw = ($("#adaptKw").value || "斗破苍穹").trim();
  const out = $("#adaptOut");

  if (!url) { toast("先填个网址吧", "err"); $("#adaptUrl").focus(); return; }
  if (!/^https?:\/\//i.test(url) && !/\w+\.\w{2,}/.test(url)) {
    toast("这看着不像网址 —— 应该长得像 https://www.example.com", "err");
    $("#adaptUrl").focus();
    return;
  }

  if (streamCtrl) { try { streamCtrl.abort(); } catch {} }
  streamCtrl = new AbortController();

  $("#adaptGo").disabled = true;
  $("#adaptGo").textContent = "正在研究…";
  out.innerHTML = `
    <div style="margin-top:6px">
      <div class="steps" id="adaptSteps">${pendingHTML()}</div>
      <div style="text-align:center;font-size:12.5px;color:var(--t-3);margin-top:14px">
        正在真抓页面，通常 10~25 秒。你可以看着它走到哪一步。
      </div>
    </div>`;

  const stepsBox = () => $("#adaptSteps");
  let rendered = [];

  try {
    const resp = await api.stream("/api/adapt/stream?url=" + encodeURIComponent(url)
      + "&keyword=" + encodeURIComponent(kw) + "&save=1");
    if (!resp.ok || !resp.body) throw new Error("HTTP " + resp.status);

    const reader = resp.body.getReader(), dec = new TextDecoder();
    let buf = "";
    let final = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split("\n"); buf = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        let ev; try { ev = JSON.parse(line); } catch { continue; }

        if (ev.type === "step") {
          rendered.push(ev);
          const box = stepsBox();
          if (box) {
            box.innerHTML = rendered.map(s => stepHTML(s.step, s.ok ? "yes" : "no", s.detail, s)).join("")
              + (ev.ok ? pendingHTML(rendered.map(s => s.step)) : "");
          }
        } else if (ev.type === "done") {
          final = ev;
        } else if (ev.type === "error") {
          throw new Error(ev.msg || "适配出错");
        }
      }
    }

    if (final) renderFinal(final, url);
    else out.innerHTML += `<div class="verdict bad"><b>连接中断了</b>没拿到完整的适配结果。可能是网络不稳，再点一次试试。</div>`;

  } catch (e) {
    if (e.name !== "AbortError") {
      out.innerHTML = `<div class="verdict bad">
        <b>研究失败</b>
        出了点问题：${esc(e.message)}
        <ul>
          <li>检查网址是不是复制全了（要带 <code>https://</code>）</li>
          <li>确认这个网站在浏览器里能正常打开</li>
          <li>如果网站需要登录才能搜索，那这个站就接不了</li>
        </ul>
      </div>`;
    }
  } finally {
    $("#adaptGo").disabled = false;
    $("#adaptGo").textContent = "开始研究这个网站";
    streamCtrl = null;
  }
}

function renderFinal(r, url) {
  const out = $("#adaptOut");
  const steps = (r.steps || []).map(s => stepHTML(s.step, s.ok ? "yes" : "no", s.detail, s)).join("");
  const cfg = r.config || {};

  if (!r.ok) {
    const last = (r.steps || []).slice(-1)[0] || {};
    const hint = last.hint || "不是所有站都能接 —— 有的搜索要登录、有的是 JS 渲染、有的干脆没有搜索功能。";
    out.innerHTML = `
      ${steps}
      <div class="verdict bad" style="margin-top:14px">
        <b>这个站暂时接不了</b>
        卡在「${esc(stepOf(last.step).t || last.step || "未知")}」这一步。<br><br>
        <b>怎么办：</b>
        <ul><li>${esc(hint)}</li>
        <li>换个站试试 —— 大部分传统小说站都能接上</li></ul>
      </div>`;
    return;
  }

  out.innerHTML = `
    ${steps}
    <div class="verdict ok" style="margin-top:14px">
      <b>✓ 接上了，可以用</b>
      以后可以在「发现」里直接搜到<b>${esc(r.display || "")}</b>的书了。
      <ul>
        <li>识别到的建站系统：<b>${esc(r.engine || "通用")}</b></li>
        <li>抽样抓到正文：<b>${r.sample_chars || 0} 字</b>（能抓到这个量才算数）</li>
        ${cfg.chapter_paged ? `<li>这个站一章分了好几页，我已经开启<b>自动拼接</b>，每章都会抓全</li>` : ""}
      </ul>
      <div style="margin-top:10px;font-size:12px;color:var(--t-3)">
        正文样例：${esc((r.sample_preview || "").slice(0, 70))}…
      </div>
    </div>

    <details class="rawfold">
      <summary>我摸到的结构（给想了解细节的人看）</summary>
      <pre>${esc(JSON.stringify({
        search_url: cfg.search_url,
        search_item_re: cfg.search_item_re,
        chapter_re: cfg.chapter_re,
        content_re: cfg.content_re,
      }, null, 1))}</pre>
    </details>

    <button class="btn primary block" style="margin-top:14px" id="adaptDone">好，去搜一本书试试</button>`;

  const done = $("#adaptDone");
  if (done) done.onclick = () => {
    document.getElementById("adaptDrawer")?.remove();
    location.hash = "#search=" + encodeURIComponent($("#adaptKw").value || "斗破苍穹");
    location.reload();
  };
}
