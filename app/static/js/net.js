/* ==========================================================================
   手机访问 · 内网穿透
   --------------------------------------------------------------------------
   两件事放一屏，因为它们是同一个问题的两种答案：
     「在家」→ 局域网地址
     「在外地」→ 公网地址（临时隧道）
   ========================================================================== */

import { $, esc, api, toast, openDrawer, copyText } from "./util.js";

let timer = null;

async function renderNet(force) {
  const body = $("#netBody");
  if (!body) return;
  body.innerHTML = `<div class="skel"><i class="w1"></i><i class="w2"></i><i class="w3"></i></div>`;

  try {
    const n = await api.get("/api/net" + (force ? "?force=1" : ""));
    const fwOk = n.ok !== false;
    const t = n.tunnel || {};

    body.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:20px">

        <!-- ============ 在家 ============ -->
        <section>
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:5px">
            <span style="font-size:16px">🏠</span>
            <b style="font-size:14px">在同一个 WiFi 下</b>
          </div>
          <p style="margin:0 0 4px;font-size:13px;color:var(--t-2);line-height:1.7">
            手机连上家里的 WiFi，浏览器打开这个地址：
          </p>
          <div class="urlrow">
            <code id="netUrl">${esc(n.url)}</code>
            <button class="btn primary sm" data-copy="${esc(n.url)}">复制</button>
          </div>
          ${fwOk
            ? `<div class="netstate ok">
                 <span class="vh">✓ 端口已放行，能连上</span>
                 ${n.rule_name ? `命中防火墙规则「${esc(n.rule_name)}」` : "防火墙不会拦入站（三个网络配置文件都关着）"}
               </div>`
            : `<div class="netstate bad">
                 <span class="vh">⚠ 现在手机连不上：防火墙没放行 ${esc(String(n.port))} 端口</span>
                 Windows 防火墙默认拦入站，而且失败时手机只会一直转圈，<b>电脑上没有任何提示</b>。<br><br>
                 以<b>管理员</b>身份打开 PowerShell 或 cmd，粘这一行：
                 <pre>netsh advfirewall firewall add rule name="NovelDock ${esc(String(n.port))}" dir=in action=allow protocol=TCP localport=${esc(String(n.port))}</pre>
                 只放行这一个端口，<b>不用关防火墙</b>。放行后点下面的「重新检测」。
               </div>
               <button class="btn sm block" style="margin-top:10px" id="netAgain">重新检测</button>`}

          <details class="rawfold" style="margin-top:12px">
            <summary>连不上时，按这个顺序查</summary>
            <div class="netnote">
              <ol>
                <li>手机和电脑是不是<b>同一个 WiFi</b>（不是流量上网）</li>
                <li>电脑上这个程序<b>还在运行吗</b>（窗口关了就断了）</li>
                <li>上面那条防火墙规则加了没</li>
                <li>路由器有没有开「AP 隔离 / 客户端隔离」—— 开了的话同一 WiFi 也互相看不见</li>
              </ol>
              <div style="margin-top:8px;color:var(--t-3)">
                本机地址 ${esc(n.lan)} · 当前网络类型「${esc(n.current || "未知")}」。
                换 WiFi 后地址会变，回这里看新的就行。
              </div>
            </div>
          </details>
        </section>

        <div style="height:1px;background:var(--s-line-2)"></div>

        <!-- ============ 在外地 ============ -->
        <section>
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:5px">
            <span style="font-size:16px">🌍</span>
            <b style="font-size:14px">在外面（4G / 公司 / 别人家）</b>
          </div>
          <p style="margin:0 0 4px;font-size:13px;color:var(--t-2);line-height:1.7">
            局域网地址只在同一个 WiFi 里有效。要在外面也能看，需要开一条
            <b>临时公网通道</b> —— 它会给你的电脑分配一个公网网址，手机在哪儿都能打开。
          </p>

          <div id="tunnelBox">
            ${t.running ? tunnelRunningHTML(t) : tunnelIdleHTML(t)}
          </div>

          <details class="rawfold" style="margin-top:12px">
            <summary>这条通道是怎么来的、有什么风险</summary>
            <div class="netnote">
              用的是 Cloudflare 的快速隧道（quick tunnel）：一条从你电脑<b>主动连出去</b>的加密通道，
              所以不用在路由器上做端口映射，也不需要有公网 IP。<br><br>
              <b>要知道的三件事：</b>
              <ol>
                <li>网址是随机的，<b>每次开启都不一样</b>，关掉就失效</li>
                <li>它确实是公网可达的 —— 所以必须带访问令牌，我没做「裸奔」模式</li>
                <li>免费隧道不保证速度，忙的时候会慢</li>
              </ol>
              <div style="margin-top:8px;color:var(--t-3)">
                令牌相当于这把锁的钥匙。分享链接给别人时，链接里已经带了令牌；
                如果不想让旧链接继续能用，点下面「换一个令牌」。
              </div>
            </div>
          </details>
        </section>

        <!-- ============ 令牌 ============ -->
        <section>
          <div class="sec-lb">访问令牌</div>
          <div class="urlrow" style="margin:0">
            <code style="font-size:12px">${esc(n.token || "")}</code>
            <button class="btn sm" data-copy="${esc(n.token || "")}">复制</button>
          </div>
          <div class="btnrow">
            <button class="btn ghost sm" id="tokRotate">换一个令牌</button>
          </div>
          <div class="hint">
            局域网直连不用令牌；只有走公网通道进来的请求才要求带上它。<br>
            <b>令牌不会自己变</b>（只有点「换一个令牌」才变），记一次能一直用。
          </div>
          <div class="hint box">
            <b>人在外面、又不记得令牌？</b>程序目录里有一份
            <code>远程访问.txt</code>，每次开了通道都会自动更新 ——
            里面写着<b>当前能直接打开的完整链接</b>和令牌，随时可以翻。
          </div>
        </section>

        <!-- ============ 云服务器（第三种答案）============ -->
        <section id="deploySec">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:5px">
            <span style="font-size:16px">☁️</span>
            <b style="font-size:14px">或者：部署到云服务器（更省心）</b>
          </div>
          <p style="margin:0 0 10px;font-size:13px;color:var(--t-2);line-height:1.7">
            临时通道每次重启都换地址，而且<b>得开着这台电脑</b>。
            买一台云服务器装上去，就是一个固定地址、7×24 自己跑，
            不用再管这台电脑开没开。
            <b>装的过程不用你敲任何命令</b> —— 下面那条粘一次就行。
          </p>
          <div id="deployBox">
            <div class="skel"><i class="w1"></i><i class="w2"></i></div>
          </div>
        </section>
      </div>`;

    bindBody(n);
    loadDeploy();
  } catch (e) {
    body.innerHTML = `<div class="empty"><div class="e">📱</div><h3>拿不到网络信息</h3><p>${esc(e.message)}</p></div>`;
  }
}

/* 云服务器部署：只在这里取「那条命令」，取不到就安静地收起这一块 ——
   它是个附加选项，不该因为拿不到就把整个网络面板搞成错误页。 */
async function loadDeploy() {
  const box = $("#deployBox");
  if (!box) return;
  let d = null;
  try {
    d = await api.get("/api/deploy");
  } catch (e) {
    box.innerHTML = `<div class="netnote" style="margin:0">
      拿不到部署信息：${esc(e.message || e)}</div>`;
    return;
  }
  if (!d || !d.ok) return;

  const cmd = d.command || "";
  box.innerHTML = `
    <div style="font-size:12px;font-weight:750;color:var(--t-3);margin-bottom:7px;
                letter-spacing:.04em">在服务器的终端里，粘这一条</div>
    <div class="urlrow" style="margin:0;align-items:stretch">
      <code id="deployCmd" style="font-size:11.5px;word-break:break-all;line-height:1.6">${esc(cmd)}</code>
      <button class="btn primary sm" data-copy="${esc(cmd)}">复制</button>
    </div>
    <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
      <button class="btn sm" id="deployDl">下载安装包</button>
      <button class="btn ghost sm" id="deployGuide">看图文步骤</button>
    </div>
    <div class="netnote" style="margin-top:11px">
      <b>顺序是这样的：</b>
      <ol style="margin:6px 0 0;padding-left:18px">
        <li>去腾讯云买一台，镜像选 <b>Ubuntu Server 22.04 LTS 64位</b>
            （公共镜像，别选宝塔）</li>
        <li>买的时候在<b>安全组</b>里放行 <b>TCP ${esc(String(d.port))}</b> ——
            这一步最容易忘，漏了手机就是打不开</li>
        <li>用控制台的「登录 / 网页终端」连上去，粘上面那条命令，等 2~3 分钟</li>
        <li>装完它会自己打印出手机该打开的地址，直接照抄进手机</li>
      </ol>
      <div style="margin-top:9px;color:var(--t-3)">
        ${esc(d.note || "")}
      </div>
    </div>`;

  box.querySelectorAll("[data-copy]").forEach((b) => {
    b.onclick = () => copyText(b.getAttribute("data-copy"));
  });
  const dl = $("#deployDl");
  if (dl) dl.onclick = () => { window.location.href = "/api/deploy/tar"; };
  const gd = $("#deployGuide");
  if (gd) gd.onclick = () => window.open("/api/deploy/guide", "_blank");
}

function tunnelIdleHTML(t) {
  return `
    <div class="netstate" style="background:var(--s-card-2);border-color:var(--s-line-2)">
      <span class="vh" style="color:var(--t-2)">通道没开</span>
      现在是关着的。需要在外地访问时再开，用完可以关掉 —— 不开就没有公网暴露面。
    </div>
    <button class="btn primary block" style="margin-top:10px" id="tunStart">
      ${t.available ? "开启公网通道" : "开启公网通道（首次需下载约 55MB 组件）"}
    </button>`;
}

function tunnelRunningHTML(t) {
  const strong = t.url + "?t=";
  return `
    <div class="netstate ok">
      <span class="vh">✓ 通道已开启，外面可以访问了</span>
      把这个地址发到手机上（或直接在这台手机的浏览器里点开）—— 它<b>已经带了令牌</b>，打开就能用。
    </div>
    <div class="urlrow">
      <code id="netPub">${esc(strong)}…</code>
      <button class="btn primary sm" id="copyPubAll">复制完整链接</button>
    </div>
    <div style="display:flex;gap:8px">
      <button class="btn ghost sm" id="tunStop">关闭通道</button>
      <button class="btn ghost sm" id="tunRefresh">刷新状态</button>
    </div>`;
}

function bindBody(n) {
  const t = n.tunnel || {};

  document.querySelectorAll("[data-copy]").forEach(b => b.onclick = async () => {
    const ok = await copyText(b.dataset.copy);
    const old = b.textContent;
    b.textContent = ok ? "已复制" : "复制失败";
    setTimeout(() => { b.textContent = old; }, 1400);
  });

  const again = $("#netAgain");
  if (again) again.onclick = () => renderNet(true);

  // 公网链接要带上令牌：先把完整链接取回来再复制
  let fullUrl = t.url ? t.url + "?t=" + (n.token || "") : "";
  const showPub = $("#netPub");
  if (showPub && fullUrl) showPub.textContent = fullUrl;

  const cp = $("#copyPubAll");
  if (cp) cp.onclick = async () => {
    const ok = await copyText(fullUrl);
    cp.textContent = ok ? "已复制 ✓" : "复制失败";
    setTimeout(() => { cp.textContent = "复制完整链接"; }, 1600);
  };

  const start = $("#tunStart");
  if (start) start.onclick = async () => {
    start.disabled = true;
    start.textContent = t.available ? "正在建立通道…" : "正在下载组件（约 55MB）…";
    const box = $("#tunnelBox");
    box.innerHTML = `<div class="netstate" style="background:var(--s-card-2);border-color:var(--s-line-2)">
      <span class="vh" style="color:var(--t-2)">正在建立…</span>
      正在和 Cloudflare 握手，通常 5~20 秒。首次使用还要先下载组件，会久一点。
    </div>`;
    try {
      const r = await api.post("/api/tunnel/start", {});
      if (r.ok) {
        fullUrl = r.url_with_token || "";
        toast("通道已开启");
        renderNet(true);
      } else {
        box.innerHTML = `<div class="netstate bad">
          <span class="vh">⚠ 没开起来</span>${esc(r.error || "未知错误")}
        </div>
        <button class="btn sm block" style="margin-top:10px" id="tunRetry">再试一次</button>`;
        const rt = $("#tunRetry");
        if (rt) rt.onclick = () => renderNet(false);
      }
    } catch (e) {
      box.innerHTML = `<div class="netstate bad"><span class="vh">⚠ 没开起来</span>${esc(e.message)}</div>`;
    }
  };

  const stop = $("#tunStop");
  if (stop) stop.onclick = async () => {
    stop.disabled = true;
    await api.post("/api/tunnel/stop", {});
    toast("通道已关闭");
    renderNet(true);
  };

  const rf = $("#tunRefresh");
  if (rf) rf.onclick = () => renderNet(true);

  const rot = $("#tokRotate");
  if (rot) rot.onclick = async () => {
    const r = await api.post("/api/auth/rotate", {});
    // 换完令牌，本页也得跟着换，否则自己会被锁在外面
    const { TOKEN } = await import("./util.js");
    TOKEN.set(r.token);
    toast("已换新令牌，旧链接立刻失效");
    renderNet(true);
  };

  // 通道开着时每 20 秒刷一次状态（进程可能自己挂了）
  clearInterval(timer);
  if (t.running) timer = setInterval(() => {
    if (document.getElementById("netBody")) renderNet(true);
    else clearInterval(timer);
  }, 20000);
}

export function openNet() {
  const existing = document.getElementById("netDrawer");
  if (existing) { renderNet(false); return; }
  openDrawer({
    id: "netDrawer",
    title: "在别的设备上打开",
    body: `<div id="netBody"></div>`,
    onMount: () => renderNet(false),
  });
}
