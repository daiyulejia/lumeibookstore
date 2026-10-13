---
name: ship-lumei
description: 把噜妹书院（novel-downloader）的本地改动自检、同步到云服务器、并推送到 GitHub。当用户说「同步」「上线」「推到云上」「部署一下」「改完了发上去」「push」「提交」「sync」「ship」，或者刚做完一轮功能改动需要让线上生效 / 备份到远程仓库时使用。
---

# 噜妹书院 · 上线 + 推送

把「改了代码 → 自检 → 同步云端 → 推 GitHub」这条每次都要重复的链固化。
**不要手工拼命令**，两条命令就够。

> 用户原话：「每次修改了都要及时推送到云服务器」「每次改完了都记得推送，
> commit msg 记得写的清楚点，为啥这么做，做了啥，结果啥」。
> 所以**上线和推送是成对的**，做完一轮改动两件都要做，别只做一半。

## 第一步：自检 + 上线

在项目根目录（`novel-downloader/`）执行：

```bash
.venv/Scripts/python.exe tools/ship.py
```

它会依次：

1. **静态自检**（17 套）—— `test_motion.py`（动效 + 主题覆盖 37 项）/ `test_art.py` /
   `test_parse.py` / `test_ranks.py` / `test_registry.py` / `test_registry_author.py` /
   `test_relevance.py` / `test_sitelearn.py` / `test_deobfuscate.py` / `test_security.py` /
   `test_discover_fallback.py` / `test_ranks_stale.py` / `test_bookurl.py` /
   `test_junk.py`（影视站 + 话题标签符）/ `test_filename.py`（Windows 文件名）/
   `test_cover.py` / `test_frontend.py` /
   `test_events_registry.py`（埋点登记表双向一致性，5 项）
2. **真机自检**（14 套，自己起临时服务、跑完自动关）—— `test_motion_live.py` /
   `test_buttons.py`（79 项）/ `test_ranks_ui.py` / `test_reader_ui.py`（30 项）/
   `test_xss.py`（19 项注入）/ `test_concurrency.py`（11 项并发竞态）/
   `test_telemetry.py`（8 项前端埋点）/ `test_disconnect.py`（5 项断连止损）/
   `test_auth_race.py`（鉴权时序）/ `test_shelf_ui.py` / `test_files_ui.py` /
   `test_discover_ui.py` / `test_reader_shell.py`（23 项阅读器外壳）
3. **同步** —— 调 `tools/sync_cloud.py`：打包 → scp → 远端只覆盖代码 → 验证

**任何一项红就停下，绝不往线上推。** 这是这个脚本最重要的性质 ——
以前是"先同步了再说"，结果线上跑到一半才发现坏了。

## 改完之后的两条自证纪律

### A. 反证（测试写完必须故意破坏产品代码）
新写的断言，一定要把对应功能拆掉/改坏，确认它**真能报红**。
本项目已经抓到多次"看着在测、其实恒真"的假测试。
反证时**不要**在 `ship.py` 跑的同时改文件（见下）。

### B. 改了后端代码要验证时，先重启本地服务
本地 8000 由 `tools/serve.py` 守护，**不热重载**。
踩过：补了 `verify.*` 埋点后搜书，`grep logs/app.log` 一片空白，
差点以为埋点没生效 —— 实际是服务还跑着旧代码。
"grep 不到日志"优先怀疑服务没重启，再怀疑代码。

### C. 真机套件红了，先看症状是否"每次都不一样"——那多半是 Chrome 竞态，不是产品坏了
**症状**：`ship` 里真机串行跑 14 套时随机报红，但**单独重跑那一个套件必绿**；
且两次红的**位置和错误都不同**（一次是「DOM 里等不到榜单条目」，
下次是 `ConnectionResetError: [WinError 10054] 远程主机强迫关闭了一个现有的连接`）。

**根因**：老的 Chrome 启动写法是「`free_port()` 挑端口 + `wait_devtools()`
只判断端口能不能回话」。两个洞：
1. `free_port()` 是「bind(0) → 读端口 → close()」——
   **close 之后到 Chrome 真正 bind 之前，端口是没人占的**，窗口期可能被抢；
2. 更要命的是**不校验身份** —— 上一个套件 terminate 掉的旧 Chrome 还没退干净时，
   新 Chrome 可能连上那个**即将死掉的旧实例**，等它一退，WebSocket 立刻被 reset。

**对策（已实现，新代码请直接用）**：
- `tools/shot.py` 的 **`launch_chrome()`** —— 用官方 `--remote-debugging-port=0`
  让 Chrome 自己挑端口，从 `--user-data-dir/DevToolsActivePort` 读回端口 + 实例 UUID；
  **启动前先删掉那个文件**，所以「文件存在」== 「本次实例写出来的」。
- `Page.*` / `Runtime.*` 命令**只挂在页面 target 上**，要用 **`page_ws(port)`**
  拿页面级 ws；直接拿 `launch_chrome` 的 browser 级 ws 调 `Page.enable`
  会报 `-32601 'Page.enable' wasn't found`（踩过）。
- 反证方式见下（这三步是本轮实际做过的，能精确复现/验证）。

**判断口诀**：随机红 + 单独跑必绿 + 每次症状不同 ⇒ **先怀疑浏览器/端口竞态**，
别急着改产品代码。


## 第二步：推送 GitHub

```bash
git add -A
git commit -m "<见下面的规范>"
git push origin main
```

- 仓库：`git@github.com:daiyulejia/lumeibookstore.git`（**私有**）
- 下载的小说不传（`.gitignore` 已排除 `library/` `downloads/` `cache/` `tmp_assets/`）
- commit message 写清三件事：**为什么改 / 改了啥 / 结果如何**。
  例：
  ```
  fix(search): 连点搜索会串台 —— abort 从未生效 + finally 无守卫

  为什么：用户连点两次搜索时，两个 NDJSON 流同时往 #results 写、互相覆盖。
  改了啥：① api.stream/api.post 接 signal（原来 AbortController 是空转）；
         ② runSearch/runFetchUrl 的收尾加 `M.ctrl !== ctrl` 守卫。
  结果：新增 test_concurrency.py（11 项）钉住，全套回归绿。
  ```
- push 偶尔报 `Connection reset by peer`（网络抖动），重试即可。

## 开关

| 想要什么 | 命令 |
|---|---|
| 只自检，先不上线 | `tools/ship.py --only-test` |
| 改的是文案/注释，跳过自检 | `tools/ship.py --skip-test` |
| 没装 Chrome，跳过真机检查 | `tools/ship.py --skip-live` |
| 想先看看要做什么 | `tools/ship.py --dry-run` |
| 只同步，不跑自检 | `tools/sync_cloud.py` |
| 复用已打好的包 | `tools/sync_cloud.py --skip-pack` |

## 服务器信息

- `NOVELDOCK_HOST` 默认 `106.53.203.108`
- `NOVELDOCK_USER` 默认 `ubuntu`
- `NOVELDOCK_KEY` 默认 `~/.ssh/noveldock_ed25519`
- `NOVELDOCK_PORT` 默认 `8000`

都在 `tools/sync_cloud.py` 头部，可用环境变量覆盖，不必改脚本。

## 同步时**绝不会**动的东西

`library/`（书架与章节缓存）、`downloads/`（导出文件）、`logs/`、`.venv/`，
以及 `cache/` 里已有的 json（令牌 / 榜单 / 来源库 / 书源索引 —— 缺的补，有的一律保留服务器版本）。

只覆盖：`app/` `tools/` `run.py` `requirements.txt` `probe.py` `README.md` `*.bat` `*.sh`。

## 出问题时

- **自检红了** → 按输出修，改完重跑。别用 `--skip-test` 绕过 ——
  那些检查都是抓过真 bug 的（动效层抓到 4 个、素材层抓到 3 处情绪错配、
  `test_concurrency` 抓到 abort 空转、`test_telemetry` 抓到前端零上报）。
- **静态资源 404** → `sync_cloud.py` 的 4/5 会逐个打首页引用到的静态文件。
  报哪个就查哪个有没有被打进包（`tools/pack.py` 的排除规则）。
- **同步后页面没变** → 浏览器强刷（Ctrl+Shift+R）。CSS/JS 有缓存。
- **服务没起来** → 看 `logs/`；远端用
  `systemctl --user status noveldock` 或 `tools/service.py start`。
- **线上出了问题，要查原因** → 先看日志，别猜：
  ```bash
  ssh -i ~/.ssh/noveldock_ed25519 ubuntu@106.53.203.108 \
      'grep -h "ui\.\|search\.fail" ~/noveldock/logs/app.log | tail -50'
  ```
  `ui.error` = 浏览器 JS 报错（带堆栈）、`ui.reject` = Promise 拒绝、
  `ui.api.fail` = 接口失败。用户说"搜不出来"时**第一件事就是 grep `ui.api.fail`**。

## 别做的事

- 不要手工 `scp` + `tar` + 挑文件覆盖 —— 那条路走过三次，有一次差点把服务器
  的 `library/` 覆盖掉（读过的进度全没）。`sync_cloud.py` 存在的全部理由就是这个。
- 不要为了"快一点"跳过自检。自检几分钟，比修线上问题快得多。
- 不要只上线不推送 —— 用户明确要求两边同步。
