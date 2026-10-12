---
name: ship-lumei
description: 把噜妹书院（novel-downloader）的本地改动自检并同步到云服务器。当用户说「同步」「上线」「推到云上」「部署一下」「改完了发上去」「sync」「ship」，或者刚做完一轮功能改动需要让线上生效时使用。也会在需要跑全量回归自检（动效 / 素材 / 按钮 / 解析器 / 来源库）时使用。
---

# 噜妹书院 · 上线

把「改了代码 → 自检 → 同步 → 验收」这条每次都要重复的链固化。**不要手工拼命令**，
一条命令就够，省下的时间比读这份文档多。

## 一句话入口

在项目根目录（`novel-downloader/`）执行：

```bash
.venv/Scripts/python.exe tools/ship.py
```

它会依次：

1. **静态自检** —— `test_motion.py`（动效规矩）/ `test_art.py`（素材质量）/
   `test_parse.py` / `test_ranks.py` / `test_registry.py` / `test_relevance.py` /
   `test_sitelearn.py` / `test_deobfuscate.py`
2. **真机自检** —— 自己起一个临时本地服务（跑完自动关），再跑
   `test_motion_live.py`（CDP 真机）/ `test_buttons.py`（78 项按钮）
3. **同步** —— 调 `tools/sync_cloud.py`：打包 → scp → 远端只覆盖代码 → 验证

**任何一项红就停下，绝不往线上推。** 这是这个脚本最重要的性质 ——
以前是"先同步了再说"，结果线上跑到一半才发现坏了。

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
  那些检查都是抓过真 bug 的（动效层抓到 4 个、素材层抓到 3 处情绪错配）。
- **静态资源 404** → `sync_cloud.py` 的 4/5 会逐个打首页引用到的静态文件。
  报哪个就查哪个有没有被打进包（`tools/pack.py` 的排除规则）。
- **同步后页面没变** → 浏览器强刷（Ctrl+Shift+R）。CSS/JS 有缓存。
- **服务没起来** → 看 `logs/`；远端用
  `systemctl --user status noveldock` 或 `tools/service.py start`。

## 别做的事

- 不要手工 `scp` + `tar` + 挑文件覆盖 —— 那条路走过三次，有一次差点把服务器
  的 `library/` 覆盖掉（读过的进度全没）。`sync_cloud.py` 存在的全部理由就是这个。
- 不要为了"快一点"跳过自检。自检 85 秒，比修线上问题快得多。
