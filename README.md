# 噜妹书院 · lumei novel dock

输入书名 → 自动搜索多个来源 → **去噪排序** → **探测哪些真的能打开** → 预览确认 → 下载成 txt。
同一局域网内任何设备都能通过浏览器使用。

界面是一套「噜妹」主题：粉奶油配色 + 圆脸吉祥物 + 漂浮的小脑袋背景，外加「黑糖噜妹」深色版。

---

## 它是干什么的

搜一本书，通常会撞上这些情况：

- 同一个书名在七八个站都有，但**大部分打不开**（404 / 反爬 / 只有目录没有正文）
- 搜索结果里混着**判决书、百科词条、书评、章节页**——它们是"提到了这本书"，不是这本书
- 搜《活着》，返回《原神：活着》《我怎么还活着》；搜《三体》，返回《三体唐诗四库全书本》

所以这个项目的核心不是"抓取"，而是**在一堆似是而非的结果里，判断哪一条真的能读**。整条链路：

```
书名
 └─ 多源并行搜索（本地来源库 + 联网兜底）
     └─ 去噪打分：标题匹配为主、正文命中视为噪音
         └─ 相关性排序 + 自适应门槛（宁缺毋滥，找不到就老实说没找到）
             └─ 抽样探测：真的打开目录页/正文页看一眼
                 └─ 标"可读 / 不可读"→ 用户挑一个 → 下载 / 在线阅读
```

---

## 架构

### 分层

```
┌──────────────────────────────────────────────────────┐
│  前端（原生 JS，无框架）  app/static/                 │
│  · 搜索 / 结果卡 / 榜单 / 阅读器 / 书架 / 文件         │
│  · 事件总线 bus + 各页面模块，动效层 motion.css       │
└───────────────────────┬──────────────────────────────┘
                        │  HTTP / NDJSON 事件流
┌───────────────────────▼──────────────────────────────┐
│  接口层  app/main.py (FastAPI)                        │
│  · /api/search /api/probe /api/download /api/library  │
│  · 令牌鉴权 · SSRF 拦截 · 长任务转后台 + 进度轮询      │
└───────────────────────┬──────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────┐
│  核心层                                               │
│  engine.py     搜索编排：扇出 / 截止时间 / 联网兜底     │
│  relevance.py  相关性打分、去噪、排序（本项目的心脏）   │
│  aggregate.py  多源结果合并、同一本书的跨源归并         │
│  discovery.py  联网发现新站点                          │
│  registry.py   来源库：越用越大，会自己学站内搜索接口   │
│  sitelearn.py  从页面里反推搜索接口与目录结构           │
│  ranks.py      热门榜单抓取 + 缓存 + TTL               │
│  library.py    书架、章节缓存、阅读进度                │
│  exporter.py   导出 txt                                │
│  security.py   令牌 / SSRF 白名单 / 限流               │
└───────────────────────┬──────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────┐
│  来源层  app/sources/                                 │
│  每个站点一个适配器，统一出 search() / toc() / read()  │
│  · builtin       内置站点（各站一套解析）              │
│  · registry_source  来源库里动态学到的站（通用解析）    │
│  · web           联网发现的站                          │
│  · template_source  模板驱动                           │
└──────────────────────────────────────────────────────┘
```

### 几个关键设计

**搜索为什么快**
不是"等所有源答完再返回"——那样永远等不到（总有个源卡死）。改成扇出后按墙钟上限收网，
谁先给出足够多的像样结果就先返回，慢的源让它继续在后台补。

**可读性不靠猜**
结果卡上的"可读"绿标，是**真的打开那本书的目录页看过**才给的。没验证过的不给绿标。

**来源库会自动长大**
本地来源找不到这本书时，就去线上搜；搜到能爬的站，把它的搜索接口学下来存进来源库。
下次再搜同一类书，第一站就是它——搜索本身成了一次"加源"。

---

## 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 后端 | **FastAPI + uvicorn** | 原生支持流式响应，搜索进度可以边跑边推 |
| HTTP | **httpx** | 支持 async/流式；重定向钩子用于 SSRF 二次校验 |
| 解析 | **re 为主，零重量级依赖** | 小说站结构简陋且多变，正则比 CSS 选择器更好控 |
| 中文处理 | **zhconv**（繁简）+ **pypinyin**（排序/首字母） | 繁简统一后再比对，否则匹配全废 |
| 前端 | **Vite + Vue 3 + Naive UI**（分页迁移中，见 `frontend/`） | 旧版是手写 DOM，加新组件（日历/虚拟滚动/图表）要手搓绑定与清理；换声明式渲染后 `import` 即用 |
| 样式 | 旧层：`tokens / app / motion / lumei`；新层：组件 `<style scoped>` | token 层是唯一真相源（Naive 主题也读它），品牌层可整体剥离 |
| 部署 | **`tools/serve.py` 守护进程**（非 systemd）+ 榜单抓取的 systemd timer | 常驻、榜单定时刷新；⚠ 改 Python 后要手动重启，见下 |

设计取向是**依赖尽量少**：小说站页面结构参差，能用标准库解决就不引框架，
少一层依赖就少一处版本冲突。（历史包袱里唯一的例外见 `requirements.txt`。）

---

## 项目结构

```
novel-downloader/
├── app/
│   ├── main.py            FastAPI 入口与全部接口
│   ├── engine.py          搜索编排
│   ├── relevance.py       相关性打分 / 去噪 / 排序
│   ├── aggregate.py       多源合并与归并
│   ├── discovery.py       联网发现站点
│   ├── registry.py        来源库
│   ├── sitelearn.py       站点搜索接口学习
│   ├── ranks.py           榜单抓取与缓存
│   ├── library.py         书架 / 章节缓存 / 进度
│   ├── exporter.py        导出 txt
│   ├── security.py        令牌 / SSRF / 限流
│   ├── sched.py           定时任务
│   ├── sources/           各站点适配器
│   └── static/            前端（js / css / 素材）
├── tools/                 开发与运维脚本
│   ├── ship.py            一键上线（打包 + 同步 + 全量回归）
│   ├── sync_cloud.py      同步到云服务器（只覆盖代码，不动数据）
│   ├── pack.py            打包
│   ├── serve.py           守护进程
│   └── test_*.py          回归测试套件（约 20 套）
├── run.py                 本地启动
└── requirements.txt
```

---

## 快速开始

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Windows
# .venv/bin/pip install -r requirements.txt       # macOS / Linux
python run.py
```

浏览器打开提示的地址即可。局域网访问不校验令牌。

---

## 回归测试

改动前先跑，别把已经修好的又弄回去：

```bash
.venv/Scripts/python tools/test_relevance.py    # 相关性判定（核心，改动最频繁）
.venv/Scripts/python tools/test_security.py     # 令牌 / SSRF
.venv/Scripts/python tools/test_parse.py        # 站点解析
.venv/Scripts/python tools/test_buttons.py      # 真机按钮（需要 Chrome）
```

`tools/ship.py` 会一次跑完全部套件再上线。

### 改完必做（两条硬规则）

**① 同步到云服务器** —— 任何代码改动完成后：

```bash
.venv/Scripts/python tools/sync_cloud.py
```

只覆盖代码，**绝不动** `library/` `downloads/` `logs/` `.venv/`。

**② 改了 Python 要重启线上服务** —— 同步**不会**自动重启。

线上跑的是 `tools/serve.py` 的守护进程（**不是** systemd；
`systemctl is-active noveldock` 是 `inactive`，别被它误导）：

```bash
# 线上目录是 /home/ubuntu/noveldock
ssh -i ~/.ssh/noveldock_ed25519 ubuntu@106.53.203.108 \
  "cd /home/ubuntu/noveldock && .venv/bin/python3 tools/serve.py --stop"
ssh -i ~/.ssh/noveldock_ed25519 ubuntu@106.53.203.108 \
  "cd /home/ubuntu/noveldock && \
   nohup .venv/bin/python3 tools/serve.py --host 0.0.0.0 --port 8000 >/dev/null 2>&1 &"
```

前端产物（`app/static/dist/`）是静态文件，**不用**重启。

⚠ 重启完必须 `curl` 量一次关键接口 + 线上跑一遍真机套件，
确认新代码真的在跑（不然会出现"我明明改了"却毫无变化的迷惑现场）。

⚠ 别用 `systemctl restart noveldock` —— 那个 unit 是 inactive 的，
重启它只会报错或者什么都没发生，而你会以为已经生效了。

---

## 排障：日志在哪、怎么查

服务端日志在 `logs/app.log`（按天切分），每行是一个 `模块.动作` 事件 + `k=v` 字段，
所以直接 grep 得动：

```bash
grep 'search.start'  logs/app.log      # 谁在什么时候搜了什么
grep 'search.done'   logs/app.log      # 耗时、候选数
grep 'search.fail'   logs/app.log      # 失败在哪个阶段、什么原因
grep 'ui.error'      logs/app.log      # 浏览器里的 JS 报错（带堆栈）
grep 'ui.reject'     logs/app.log      # 未处理的 Promise 拒绝
grep 'ui.api.fail'   logs/app.log      # 接口失败（用户说"搜不出来"先查这条）
grep 'cover\.'       logs/app.log      # 封面取不到 / 被安全策略拦（查"有的书没图"）
```

事件名登记在 `app/logging_setup.py` 的 `EVENTS` 里，加埋点时照抄风格，
不然同一个动作换个名字写，grep 就永远搜不全。

前端错误（JS 异常 / Promise 拒绝 / 接口失败）会自动回传到 `POST /api/log` 落进同一份日志 ——
**浏览器里发生的问题，服务端日志里也查得到**。线上拉日志：

```bash
ssh -i ~/.ssh/noveldock_ed25519 ubuntu@106.53.203.108 \
    'grep -h "ui\.\|search\.fail" ~/noveldock/logs/app.log | tail -50'
```

