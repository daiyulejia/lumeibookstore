#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
噜妹书院 · 一条命令走完「自检 → 同步 → 验收」
============================================================================
为什么要有它（用户的真实抱怨：「你同步本地代码到线上弄了这么久，
这种经常要做的东西，你可以总结归纳成一个文档或者skill，下次直接触发」）

问题不在 sync_cloud.py 本身（它已经够稳），而在**外围流程**：
每次改完，实际要做的是
    1. 想起来该跑哪些测试（现在有 11 个套件，记不全）
    2. 起本地服务（有几个测试需要 base）
    3. 跑测试、看有没有挂
    4. 跑 sync_cloud.py
    5. 看验证输出（以前只验 health，不看静态资源）
光"想起来 + 粘命令"就占了大半时间，还漏过步骤。

所以把这条链固化在这里。用法只有一句：

    .venv\\Scripts\\python tools\\ship.py

它会：
  · 自动起一个临时本地服务（跑完自动关）—— 需要真机的检查也能跑
  · 并行跑所有静态检查，串行跑需要服务的检查
  · **任何一项红就停下，不往线上推**
  · 全绿才调 sync_cloud.py
  · 最后再独立验一遍线上静态资源

常用开关：
    --only-test      只自检，不同步
    --skip-test      跳过自检直接同步（修文案这类小改动用）
    --skip-live      跳过需要真机浏览器的检查（没装 Chrome 时）
    --dry-run        打印将要做什么，不真执行
============================================================================
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# 静态检查（不需要服务）—— 快，先跑。
# 挑的是「改动影响了这一块，就必须过」的那些；不是测试越全越好 ——
# 全跑一遍要好几分钟，长到人会开始跳过它，那就等于没有。
STATIC_SUITES = [
    ("test_motion.py", "动效层规矩"),
    ("test_art.py", "素材层质量"),
    ("test_parse.py", "解析器"),
    ("test_ranks.py", "榜单解析"),
    ("test_registry.py", "来源库"),
    # 自有来源（学到的模板）→ 真的能搜出书。这条链路一断，表现为
    # 「每次搜索悄悄少一批自有源结果」——不报错、日志只有一句 debug。
    ("test_registry_source.py", "自有来源搜索"),
    ("test_relevance.py", "结果相关性"),
    ("test_sitelearn.py", "站点学习"),
    # 「可搜源」必须真的在按关键词搜。线上 21 个已学模板里 9 个是假的
    # （站点不认参数、照常吐首页），后果是「综合 N 站」这个数字掺水 ——
    # 不报错、不写日志，人工回归必漏。
    ("test_search_trust.py", "可搜源真假"),
    ("test_deobfuscate.py", "反混淆"),
    # 纯逻辑、不用服务。之前漏在外面，结果"改了安全策略却没人验"。
    ("test_security.py", "安全策略"),
    # HTTP 客户端复用：verify 翻转时必须关旧连接池，否则 socket 累积、
    # 最终表现为「跑一阵就全超时」—— 这类症状极难反推到根因。
    ("test_http_client.py", "客户端复用"),
    # 联网兜底（本地全灭必须联网）。这类 bug 不报错、只表现为"搜不到"，
    # 人工回归必漏 —— 见 tools/test_discover_fallback.py 的注释。
    ("test_discover_fallback.py", "联网兜底"),
    # 榜单抓不到（被限流）时要回退到过期的旧缓存，不能给空白页。
    # 同样是"不报错、只显空"的那类 —— 见 tools/test_ranks_stale.py 的注释。
    ("test_ranks_stale.py", "榜单兜底"),
    # 自有来源从列表页抽作者。作者搜索全靠这个字段 ——
    # 它一旦退化，表现是"搜作者名 0 条"，不报错。见该文件的注释。
    ("test_registry_author.py", "作者抽取"),
    # 书页 URL 形状：书页要认得出、章节正文页要挡住。
    # 退化的表现是「章节被当成一本书收进结果，点进去只有一章」——
    # 也不报错，只是结果脏。见 tools/test_bookurl.py 的注释。
    ("test_bookurl.py", "书页 URL"),
    # 脏数据拦截：话题标签符污染书名、影视站被当成小说站。
    # 后者尤其隐蔽 —— 苹果 CMS 的「第01集…」列表和章节目录长得一样。
    # 见 tools/test_junk.py 的注释。
    ("test_junk.py", "脏数据拦截"),
    # 文件名清洗：Windows 保留设备名（裸 CON/NUL/AUX/COM1..9/LPT1..9 建不了文件）、
    # 结尾点空格、空名。这些在 Linux 上**全都不存在**，所以本地/线上都测不出，
    # 只有真的在 Windows 上跑才暴露。见 tools/test_filename.py 的注释。
    ("test_filename.py", "文件名安全"),
    # 封面抽取：拿错封面比拿不到更糟 —— 站点占位图（nocover.jpg）一旦被
    # 当成真封面缓存下来，那本书就永远显示灰图；懒加载站（src=占位、
    # data-src=真图）只读 src 则 100% 拿错。两种写法都是从真实站点抄来的。
    ("test_cover.py", "封面抽取"),
    # 前端产物上线链路：产物存在 / 被引用 / pack 不误排 / 版本号扫得到 /
    # 路径一致。五个坏法全都表现成"白屏但部署成功"，人工必漏。
    # 尤其 pack.py 的 EXCLUDE_DIRS 含 `dist`、而匹配按路径段 ——
    # app/static/dist/ 会被误伤（接 Vite 时真踩过）。见该文件注释。
    ("test_frontend.py", "前端产物链路"),
    # 埋点事件名登记表 ↔ 实际代码的一致性。纯静态、不用服务。
    # 为什么必须有：这张表会**双向静默漂移** —— 登记了没人发（死条目，
    # 日志里 grep 不到，看起来像"链路没触发"，实际是根本没埋）、
    # 发了没登记（照着表找事件永远找不到）。两种漂移都不报错，
    # 只在线上排障时白烧时间。本轮实测抓到 11 个死条目 + 8 个未登记。
    # 见 tools/test_events_registry.py 的注释。
    ("test_events_registry.py", "埋点登记表"),
    # 来源库「失败原因分类」：note_site 的 why 分桶必须真的落盘。
    # 背景：fail 一直是混装桶（网络错 / URL 猜错 / 要登录 都只 +1），
    # 导致 is_healthy 的比值判据分不清"站不行"还是"这次抓法不对" ——
    # 这正是「定期排查坏源」做不起来的原因。本改动先攒数据、不改判定。
    # 见 tools/test_registry_why.py 的注释。
    ("test_registry_why.py", "失败原因分类"),
    # 非小说站拦截：教程/词典/博客/商城/文档站必须被挡在来源库外。
    # 它们是搜索引擎对任何关键词都顺手给的通用结果，**不是坏站**
    # （菜鸟教程 ok=35 健康得很），所以 is_healthy 永远放行 ——
    # 实测 178 站里有 23 个是这类（12.9%），白占候选位、拖慢探测。
    # 本测试最看重的部分是「零误杀」：21 个真实小说站一个都不许命中。
    # 见 tools/test_offtopic.py 的注释。
    ("test_offtopic.py", "非小说站拦截"),
    # 源熔断：线上实测同一本书两次搜索一次 0 条（卡满 20s）、一次 1 条 ——
    # 差别只在"哪几个源先回来"，而永远回不来的源（SSL 超时 / 403 / 502）
    # 每次都在名单里陪着等满 20 秒。熔断器给这件事加记忆。
    # ⚠ 这条的核心是那条**反向**判据：「空结果 ≠ 挂」—— 写反了会把所有源
    #   在一次搜冷门书后全拉黑，之后搜什么都 0 条，而且完全静默。
    ("test_source_health.py", "源熔断"),
    # 源**自己**的墙钟上限：一个打不通的站不许比整轮搜索活得更久。
    # 线上实测（2026-10-21）`wikisource.search()` 单次 **186.9 秒**才返回
    # （5 次重试 + 递增退避，`search()` 里还串两次查询），而引擎 20 秒就收手 ——
    # 每搜一次书就多一个活 167 秒的僵尸线程，占着线程和连接池，
    # 同期别的搜索就偶发「一个源都没答话」→ 0 条。
    # ⚠ 判据不看耗时（随机器负载漂），看**请求次数**和「第二次查询发没发」。
    ("test_source_budget.py", "源墙钟上限"),
    # 收手判据不许被**噪声**骗：没有确切命中就再等一会儿。
    # 线上实测（2026-10-24 真机复现）搜《兄弟》：扇出 1.76s 收手、候选 4 条
    # 全是「嘿兄弟/兄弟盟/兄弟恩仇/盛唐兄弟」，而 kunnu8 恰好在 1.76s 回来、
    # 带着正主 —— 被弃。用户看到"4 条候选、没一本是那本书"= 搜不到，
    # 可日志里 `候选=4` 看着是成功的，**判据压根没埋这个点**。
    # 根因：收手条件 ①②③ 看「候选条数够 / 答的源够多」，两者都对噪声敏感。
    # ⚠ 判据不看耗时，看「结果里有没有那本书」「确切命中数」「谁被记为未回」。
    ("test_search_recall.py", "收手别被噪声骗"),
    # 榜单「立即刷新」：线上实测全量刷新 47.2 秒 / 33.0 秒（`ms="47229 慢"`）——
    # 7 个类别**串行**跑的，类别内部并发、类别之间排队，总时长就是 7 份相加。
    # 这个接口原先一条测试都没有。
    # ⚠ 判据**不能**是"耗时小于 X 秒"（随机器负载漂）——改成观测
    #   `_fetch_one` 的**并发峰值**：串行实现永远是 1，并发实现 ≥2。
    ("test_ranks_refresh.py", "榜单刷新"),
    # 搜索总预算：对外说"最多等 20 秒"，线上实测 30.3 秒（`耗时ms=30313`）。
    # 根因是三段各有各的满额预算、谁也不看前面花了多少 ——
    # 扇出 20s + 探测 12s + 抽样 10s，最坏 42s，而且**一条错都不报**。
    # ⚠ 判据不能是"耗时小于 X 秒"（随源站快慢漂），得验「预算给多少就只花多少」。
    # 另一半是「账目」（search.rank.drop）：只有 `原始=14 去噪后=2` 无法复盘
    # 「这本书为什么搜不到」—— 分不清是站点返回了别的书、还是规则把好结果挤了。
    ("test_engine_budget.py", "搜索总预算与账目"),
    # Chrome 启动器纪律：真机套件不许硬编码调试端口、不许自己 Popen 起 Chrome。
    # 为什么值得一条**静态**测试来管：真机随机假红极难查 ——
    # 老写法（free_port + 只判断端口能回话）会连到上一个还没退干净的旧实例，
    # 表现为「ship 里随机红、单独重跑必绿、每次红的位置都不同」。
    # 谁下次随手写回 `--remote-debugging-port=9344`，这条就拦住他。
    # 见 tools/test_browser_launch.py 的注释。
    ("test_browser_launch.py", "Chrome 启动器纪律"),
    # ⚠ 2026-10-14 真事故：Chrome 升到 155 后启动器会 detach（exit=0），
    #   而 launch_chrome 把"启动器退出"当成致命错误 → 18 套真机一起红，
    #   看着像产品崩了。这个套件用假进程 + 本地假 DevTools 把判据钉死。
    ("test_chrome_launcher.py", "Chrome 启动判据（detach）"),
    # 搜索历史：同一本书搜两次不能新增条目（否则热词榜全是重复）、
    # 空白必须折叠归一、**搜不到的词要标出来**（那是书库缺口的证据）。
    # 它"绝不能影响搜索本身"，所以出问题会**静默降级**，
    # 没人会发现，直到某天想看热词才发现库是空的。
    # 见 tools/test_history.py 的注释。
    ("test_history.py", "搜索历史"),
    # 访客记录：跑在每个 API 请求上（中间件热路径），三条红线 ——
    # ① 永不抛异常（抛了所有接口一起 500）；② 落盘必须节流（否则打满磁盘）；
    # ③ 静态资源/4xx/自身接口不许记（否则自激、噪音淹没有数据）。
    # 另外 IP 必须脱敏（隐私）、UV 口径必须带"日"（否则变成历史总人数）。
    # 见 tools/test_visits.py 的注释。
    ("test_visits.py", "访客记录"),
    # 搜索历史/访客的**接线**自检（纯静态）：模块各自的行为测试保证
    # 内部逻辑对，但"有人调用它吗、路由挂了吗、CSS 类名对得上吗、
    # 深链接了吗、登记表同步了吗"这些**接线**问题它们都抓不到 ——
    # 而且这类坏法全都不报错，只是界面上那块永远空着 / 没样式。
    # 见 tools/test_search_history.py 的注释。
    ("test_search_history.py", "历史/访客接线"),
    # 阅读器热路径（纯静态）。为什么要在"静态层"再钉一遍：
    # 线上报「阅读器有点卡」，根因是 syncReader() 的快照里带着整本书的
    # tocHTML，而它走的是**每次翻页**的高频路径（再加上 updateBar 连推
    # 三次）—— 翻一页搬几 MB 字符串 ×3。真机 test_reader_ui.test_perf
    # 能把它数出来，但那要 Chrome + 本地服务；这条在纯静态层读源码就拦，
    # 快、必然能跑，没装 Chrome 的环境也有保护。
    # 见 tools/test_reader_perf_static.py 的注释。
    ("test_reader_perf_static.py", "阅读器热路径"),
    # 部署链的最后一道闸：`sync_cloud.py` 重启之后会用 tools/restart_check.py
    # 判定"干活的进程是否比最新源码新"，不过就中止上线。
    # ⚠ 闸门最典型的坏法是**永远开着**（恒返回通过）—— 看起来在工作，其实什么都没拦。
    #   所以这条专门反证 judge()：喂"进程比代码旧"必须判红；并且钉住
    #   "探针不可用（Windows 没有 pgrep）时不许谎报成功"。
    # 见 tools/test_restart_check.py 与 tools/restart_check.py 的注释。
    ("test_restart_check.py", "重启验证判据"),
    # 联网发现**不许被「学站」阻塞**：结果就绪必须立刻交付。
    # 线上真事故：本地 7 个源零覆盖 → 联网其实已经找到（实测命中 zxs8.net），
    # 但 discover() 同步把 14s 的学站跑完才 return，而墙钟上限只有 20s
    # → 用户看到「没找到」。它不报错、还"偶发"（网络快的时候刚好赶上）。
    # 测试内建反证：同步版必须真的会等，否则判据无牙。
    # 现在还多钉一条**账目**（2026-10-22 复盘）：「联网核实超预算」那条日志
    # 原来只有半句话，复盘分不清"全核完了只是都不可用"和"还有 N 个没核"，
    # 两者处置相反（换搜索词 vs 加预算），而日志长得一模一样。
    # 见 tools/test_discover_async.py 与 app/discovery._learn_later() 的注释。
    ("test_discover_async.py", "联网发现不被学站阻塞 + 核实账目"),
    # 「目录/正文读不全」是一整类**静默**故障：不报错、界面还显示得很正常。
    # 线上实测 www.zxs8.net（17mb/black/bqg 模板家族）一本书叠了六个坑：
    #   JS 造章节链接（`onclick` 无 href）、完整目录还分页、正文用 base64
    #   `document.writeln` 写出来、生僻字顶替常用字（的→葶）、适配向导
    #   要求填首页而用户粘的是书页、`rstrip("/")` 把 200 变 404。
    # 全打在这批真机抓下来的 fixture 上，且每条都配**反证**（把机制破掉必须报红）
    # —— 这类判据最容易写成恒真的假测试（本项目已抓到 7 条）。
    # 见 tools/test_toc_full.py 的注释。
    ("test_toc_full.py", "目录/正文完整性"),
    # sites.json 是**站点配置**（不是缓存）：它坏了 = 内置来源 + 用户自己加过的
    # 站一起消失。原实现有两条路会毁掉它：直接 write_text（先清空再写，
    # 中途被杀留半截）、读失败时照样写（把整份配置改写成一条）。
    # 见 tools/test_adapt_save.py。
    ("test_adapt_save.py", "站点配置落盘安全"),
    # 适配向导的「责任划分」：用户只管粘地址，剩下我来兜。
    #   ① 粘的是**正在读的那一章** → 顺着页面上「目录」入口自己找到这本书
    #      （⚠ 章节页底部挂着"热门推荐"一屏别的书 + 导航「章节目录」正好凑够
    #      8 条，会被 `_detail_via_page` 当成书页 —— 静默把目录读成别的书）；
    #   ② 给用户看的**正文样例**必须和最终读到的正文一致（反爬生僻字要还原，
    #      否则用户照着假坏样本判断"没抓对"）；
    #   ③ 适配出来的来源要**真的能搜**（搜索地址 + 结果条目正则缺一不可），
    #      且试搜要用**这本书的真名**而不是向导默认的《斗破苍穹》。
    # 见 tools/test_adapt_direct.py。
    ("test_adapt_direct.py", "适配向导兜底/样例/搜索能力"),
    # **上线链条本身**是完整的：清单里每个文件真的存在、反证清单里每条突变的
    # 片段真的能在源码里唯一命中、链条里有「推送 GitHub」这一步。
    # 为什么值得单独一套：这三个坏法全都表现成「所有测试都绿，但该做的事没做」——
    #   · 文件名写错 → 那套测试静默没跑，却显示全绿；
    #   · 突变片段与源码脱节 → 要等反证跑到第 100 多条才报（一次 ship 17 分钟，
    #     2026-10-21 连踩两次）；这条现在 1 秒内报红；
    #   · 链条里没推送 → 线上是新代码、GitHub 还是旧的（实测本地攒了 4 个提交）。
    # 见 tools/test_ship_chain.py 的注释。
    ("test_ship_chain.py", "上线链条完整"),
    # ⚠ 反证（突变）**必须排在最后**：它会临时替换源码再还原。
    #   放中间的话，后面那些套件可能读到被破坏的产物 → 假红。
    #   它自己会先确认"改动前的基线是绿的"，再把每条断言逐个打破；
    #   存活 = 断言没牙，脱节 = 测试与代码已经对不上。见 tools/mutate.py。
    ("mutate.py", "反证（突变）"),
]

# 真机检查（需要本地服务 + Chrome）
LIVE_SUITES = [
    ("test_motion_live.py", "动效真机"),
    ("test_buttons.py", "按钮全量"),
    # ⚠ 这三个**一直存在但从没进过这条链** —— 于是"榜单 UI 改了没人验"
    #   "阅读器翻页回归没人跑"。它们才是真正会拦住线上事故的那些，
    #   补进来之后 ship 才配叫"一条命令上线"。
    ("test_ranks_ui.py", "榜单界面"),
    ("test_reader_ui.py", "阅读器交互"),
    # 前端注入：payload 当搜索词打进去，断言没有真的元素生成、没有代码执行。
    # grep innerHTML 判断不了"那个变量到底过没过 esc()"，只有真浏览器说了算。
    ("test_xss.py", "前端注入"),
    # 并发竞态：连点两次搜索后的状态机。这条钉住的是「abort 生效 + finally
    # 有守卫」—— 两个 bug 都不报错，只表现为"结果串台/按钮失灵"，人工必漏。
    ("test_concurrency.py", "并发竞态"),
    # 前端埋点：JS 错误 / Promise 拒绝 / 接口失败 必须落进 logs/app.log。
    # 这条直接读日志文件 —— 「用户报的 bug 能不能对上日志」只能这么验。
    ("test_telemetry.py", "前端埋点"),
    # 客户端断开后引擎要**收手**。修之前：用户关掉页面/连点两次搜索，
    # 服务端照样把整轮跑完（实测白烧 13.9s，vs 修复后 3.5s）。
    # 靠读日志里的「客户端已断开」+ 比对耗时来判定 —— 没有这个测试，
    # 这种「不报错、只是烧资源」的退化永远发现不了。
    ("test_disconnect.py", "断连止损"),
    # 鉴权时序：Vue 是**另一个** module script，加载完立刻 mount，
    # 可能抢在读 ?t= 的 bootstrapAuth() 之前发请求 —— 线上 401、
    # 榜单整块不显示，而**本地因 /api 免令牌永远不复现**。
    # 这条不看结果看时序（请求发车时 authReady 了没），本地也有牙。
    ("test_auth_race.py", "鉴权时序"),
    # 静态资源压缩（纯 HTTP，秒级）。实测线上未压缩时首屏要 5~6 秒才挂上
    # Vue（638KB 明文）—— 这条既钉"该压的压了"，也钉
    # "别图省事挂 GZipMiddleware"（那会把 SSE 攒块，搜书不再逐条出结果）。
    ("test_static_gzip.py", "静态压缩"),
    # 来源库「站点」列表（用户原话「网址多」）。线上 114 个网址平铺成一堵墙，
    # 而真能站内搜的只有 15 个 —— 改成按能力分档排序 + 失效区折叠。
    # 这条钉三件「改错了不报错、用户立刻能感觉到」的事：排序真按能力走、
    # 失效区真折了、**折叠不许变成藏**（总数必须写出来、能展开能收回）。
    ("test_sources_ui.py", "来源库列表"),
    # 书架页（Vue 迁移后）。test_buttons 的 E 组只验"点了会怎样"，
    # 验不到渲染层：组件挂错容器（真踩过，一个 app 管多处 DOM，
    # 书架被渲进榜单区内部、页面静默空白）、插画消失、请求回声。
    ("test_shelf_ui.py", "书架界面"),
    # 文件页（Vue 迁移后）。这条钉的是一条**跨模块契约**：
    # `#fmtPick` 必须还是原生 select —— main.js 有 3 处读
    # `$("#fmtPick").value` 拿导出格式，Naive 的 n-select 渲成 div，
    # `.value` 取到 None，导出会静默用错格式。
    # 写这条断言时特地做了回退验证（换回 n-select 立刻报红）。
    ("test_files_ui.py", "文件界面"),
    # 发现页结果区（Vue 迁移后）。test_buttons 的 A/B 组验的是搜索**行为**，
    # 这条专盯"结果区交给 Vue 之后"的回归：组件挂错位置、状态桥
    # （discover:state）没接上导致"搜完了却一条不显示"、`#q`/`#btnSearch`
    # 被顺手搬进 Vue 破坏跨模块契约、空态与结果列表同时显示。
    # 全部断言都做了回退验证（断桥 / 搬 #q / 空态恒显示，三处都能报红）。
    ("test_discover_ui.py", "发现界面"),
    # 阅读器外壳（Vue 迁移后）。test_reader_ui 验的是"点一下会不会翻页"，
    # 抓不到迁移本身的回归 —— 那类问题全都发生在"渲染权与布局契约"这层：
    # 三个挂载容器挂错位置（#reader 纵向 flex 顺序乱掉）、
    # 舞台区/进度条被 Vue 抢走（StPageFlip 旧引用失效、拖拽丢手势，
    # **偶发且极难查**）、旧代码依赖的 id 丢失（$() 拿 null 直接抛错，
    # 整条链路静默中断）。这条把它们钉成"永久红"。
    ("test_reader_shell.py", "阅读器外壳"),
    # 搜索历史下拉。静态断言只能保证"代码接上了"，保证不了**真的能点** ——
    # 下拉的坑全在运行时：blur 抢在 click 前把下拉收掉（点上去"像没反应"）、
    # absolute 找不到定位祖先跑到整页宽、派发的 Enter 没被接住（点了不搜）、
    # ↑↓ 只改变量不改 DOM。这些静态扫描一个都抓不到。
    # 已做回退验证：拆掉 .h-wrap 立刻报红（左差 302px / 宽 1264 vs 660）。
    ("test_history_ui.py", "搜索历史下拉"),
    # 统计面板（来源抽屉的第三个页签）。改动点全在**跨模块接缝**上，
    # 而接缝坏了全都不报错：renderTab 的 if/else 没跟上（点了页签
    # 高亮过去、内容还是旧的）、#stats 深链没登记、拉接口失败整块空白、
    # 清空按钮没绑（点了没反应）。
    ("test_stats_ui.py", "统计面板"),
    # 窄屏不溢出（用户报「手机上一行看不全 / 页面比屏幕宽」）。
    # 这条钉的是一个**截图看不出来**的几何判据：截图只拍可视区，
    # 不知道右边被切了 —— 只有量 `innerWidth` vs `documentElement.scrollWidth` 才暴露。
    # ⚠ 判据必须跟**请求的宽度**比，不能跟 innerWidth 比（后者会被内容一起撑大，
    #   于是恒真）；这一点本套件的第一版就写错了，反证时才抓到。见 test_mobile_fit.py。
    ("test_mobile_fit.py", "窄屏不溢出"),
    # 静态资源缓存策略（**不用 Chrome，只用 HTTP**，但同样需要起的这个服务）。
    # 钉的是「发版之后用户到底能不能拿到新代码」：前端是原生 ES module，
    # 页面里只有入口 main.js?v=… 带版本号，模块间的 import 是**裸路径**，
    # 拿不到 ?v= → art.js 曾长期没有任何 Cache-Control，浏览器走启发式缓存
    # 并不断续期。真实事故：首页轮换池修好了、服务器上是新的，
    # **用户手机上还在跑旧 art.js**，看到的还是一对"两个噜噜"的图。
    # ⚠ 这个坑只从服务器侧查永远发现不了，必须看响应头。见该文件注释。
    ("test_cache_headers.py", "资源缓存策略"),
]

# 各真机套件的参数名不一样（历史原因，别硬统一 —— 改脚本参数名会连带改 CI）。
# ⚠ 漏配的后果踩过：test_motion_live 的 --base **有默认值 8011**，
#   而 ship 起的是随机端口 —— 不传它就跑去连 8011，报「连不上」，
#   看着像动效坏了，其实是测错了端口。（这个坑一直藏着：以前单独跑时
#   8011 上恰好有服务，直到某次 ship 才暴露。）
LIVE_ARGS = {
    "test_motion_live.py": "--base",
    "test_buttons.py": "--base",
    "test_ranks_ui.py": "--base",
    "test_reader_ui.py": "--url",   # 这个老脚本用的还是 --url
    "test_xss.py": "--url",
    "test_concurrency.py": "--url",
    "test_telemetry.py": "--url",
    "test_disconnect.py": "--url",
    "test_auth_race.py": "--url",
    "test_static_gzip.py": "--base",
    "test_sources_ui.py": "--base",
    "test_shelf_ui.py": "--url",
    "test_files_ui.py": "--url",
    "test_discover_ui.py": "--url",
    "test_reader_shell.py": "--url",
    "test_history_ui.py": "--url",
    "test_stats_ui.py": "--url",
    "test_mobile_fit.py": "--url",
    "test_cache_headers.py": "--url",
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_up(url: str, timeout: float = 25) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.4)
    return False


class LocalServer:
    """起一个临时的本地服务给测试用。跑完一定关掉 —— 留着会占端口，
    下次跑就会莫名"端口被占"（这个坑踩过）。"""

    def __init__(self) -> None:
        self.port = free_port()
        self.proc: subprocess.Popen | None = None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "LocalServer":
        env = dict(os.environ)
        env.pop("http_proxy", None)
        env.pop("https_proxy", None)
        env.pop("HTTP_PROXY", None)
        env.pop("HTTPS_PROXY", None)
        env["NOVEL_SCHED"] = "0"          # 测试时关掉后台调度，免得互相干扰
        # ⚠ 把**统计类**数据文件指到临时目录。
        #   为什么必须这么做：真机套件里有会**真的搜索 / 真的访问**的用例
        #   （test_history_ui 要往历史里种种子词、每次请求都会记访问），
        #   不隔离的话它们会写进你的真实 `cache/history.json` / `visits.json`。
        #   测试自己虽然会清理，但那依赖 finally 一定跑得到 —— 中途崩了
        #   就往用户的数据里留垃圾。指到临时目录就没有这个风险。
        #   只隔离这两个"纯统计"文件：registry / library / cache 是对业务
        #   结果有影响的，恰好相反 —— 真机测试**需要**它们是真的。
        _tmpstats = tempfile.mkdtemp(prefix="novel-ship-stats-")
        env["NOVEL_HISTORY"] = str(Path(_tmpstats) / "history.json")
        env["NOVEL_VISITS"] = str(Path(_tmpstats) / "visits.json")
        # ⚠ 熔断账本也要隔离（2026-10-22 起它落盘了）。
        #   真机套件里有故意做失败源的用例（boom_src / hang_src …），
        #   不隔离的话它们会被写进真实 `cache/sourcehealth.json`，
        #   下次真实搜索时账本里躺着一堆根本不存在的源名。
        env["NOVEL_HEALTH"] = str(Path(_tmpstats) / "sourcehealth.json")
        self._stats_dir = _tmpstats
        self.proc = subprocess.Popen(
            [PY, str(ROOT / "run.py"), "--host", "127.0.0.1",
             "--port", str(self.port), "--no-check"],
            cwd=ROOT, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if not wait_up(self.base + "/api/health"):
            self.__exit__(None, None, None)
            raise SystemExit(f"✗ 本地服务没起来（端口 {self.port}）")
        print(f"  · 测试服务已就绪 {self.base}")
        return self

    def __exit__(self, *exc) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        # 清掉临时统计目录
        shutil.rmtree(getattr(self, "_stats_dir", ""), ignore_errors=True)


def run_suite(name: str, desc: str, extra: list[str] | None = None) -> bool:
    path = ROOT / "tools" / name
    if not path.exists():
        print(f"  ~ {desc}: 跳过（没有 {name}）")
        return True
    cmd = [PY, str(path)] + (extra or [])
    env = dict(os.environ)
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        env.pop(k, None)
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
    if r.returncode == 0:
        print(f"  ✓ {desc}  {tail[0][:70]}")
        return True
    print(f"  ✗ {desc}  —— 失败")
    out = (r.stdout or "") + (r.stderr or "")
    lines = out.strip().splitlines()
    # ⚠ 以前是「打印最后 25 行」。踩过坑：真机套件有 24 条 ✓ 加若干小节标题，
    #   那一条 ✗ 往往落在倒数 30 行开外 —— 于是**失败原因根本看不见**，
    #   只看到"失败"两个字，还得自己去翻日志重跑一遍。
    #   正确做法：把所有 ✗ 行连上下文一起捞出来，再补尾部，保证"谁错了、错在哪"一定可见。
    fails = [i for i, ln in enumerate(lines) if "✗" in ln]
    shown: list[int] = []
    for i in fails:
        for j in range(max(0, i - 2), min(len(lines), i + 2)):
            if j not in shown:
                shown.append(j)
    shown.sort()
    if shown:
        print("      ── 失败处（含上下文）──")
        for j in shown:
            print(f"      {lines[j]}")
    tail = lines[-8:]
    if any(j >= len(lines) - 8 for j in shown):
        tail = []
    for line in tail:
        print(f"      {line}")
    return False


# ---------------------------------------------------------------------------
# 前端构建（Vite → app/static/dist）
# ---------------------------------------------------------------------------
FRONTEND = ROOT / "frontend"

# 找 node/npm：优先 managed 版本（本项目约定的隔离环境），再退到 PATH。
# 为什么要按路径找而不是直接用 "npm"：Windows 上 Git Bash 的 PATH
# 不一定带 node，而 managed 版本是确定存在的。
_NODE_CANDIDATES = [
    Path(os.path.expanduser("~")) / ".workbuddy" / "binaries" / "node" /
    "versions" / "22.22.2-6",
]


def _find_node_bin() -> tuple[str | None, str | None]:
    """返回 (node_dir, npm_cmd)。找不到就 (None, None)。"""
    for d in _NODE_CANDIDATES:
        npm = d / ("npm.cmd" if os.name == "nt" else "npm")
        if npm.exists():
            return str(d), str(npm)
    # 退到 PATH
    npm = shutil.which("npm")
    if npm:
        return None, npm
    return None, None


def _ensure_gzip() -> bool:
    """构建完立刻做静态资源预压缩（`tools/gzip_static.py`）。

    ⚠ 为什么这一步必须在 ship 里、不能靠"记得手动跑"：
      `app/main.py` 的静态挂载只在 **.gz 比源文件新** 时才发 gz，
      否则回退明文（宁可慢也不发旧字节）。所以"改了前端却忘了预压缩"
      不会出错，只会**悄悄退回 638KB 明文** —— 首屏又变 6 秒，
      而且所有测试都是绿的（它们不测体积）。
      把它钉在构建之后，这个退化就不可能发生。
    """
    try:
        import gzip_static  # 同目录
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ 预压缩模块导入失败：{type(e).__name__}: {e}")
        return False
    try:
        gzip_static.build()
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ 静态预压缩失败：{type(e).__name__}: {e}")
        return False
    return True


def build_frontend(dry_run: bool = False) -> bool:
    """构建前端 + 自检产物。没有 node 时**不阻断**（只是警告）。

    为什么"没有 node 就不阻断"：服务器上不装 node，线上是纯 Python 起的；
    开发者机器上应该有。缺 node 说明是在一个不能构建的环境里跑
    （比如远端），这时用已有的产物继续是对的 —— 总比整个流程卡死好。
    但**只要 node 在，构建失败就是硬失败** —— 那说明源码有语法错，
    绝不能带着旧产物上线。
    """
    if not FRONTEND.exists():
        print("  ~ 没有 frontend/ 目录，跳过（还没迁到 Vue？）")
        return _ensure_gzip()

    node_dir, npm = _find_node_bin()
    if not npm:
        print("  ~ 找不到 node/npm，跳过构建（用现有产物继续）")
        print("    装了 node 之后重跑，产物才会是最新的。")
        return _ensure_gzip()

    env = dict(os.environ)
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        env.pop(k, None)
    if node_dir:
        env["PATH"] = node_dir + os.pathsep + env.get("PATH", "")

    if dry_run:
        print(f"  （dry-run）会执行：{npm} run build:check  （cwd={FRONTEND}）")
        return True

    r = subprocess.run(
        [npm, "run", "build:check"], cwd=FRONTEND, env=env,
        capture_output=True, text=True, shell=(os.name == "nt"),
    )
    out = (r.stdout or "") + (r.stderr or "")
    lines = out.strip().splitlines()
    if r.returncode == 0:
        tail = lines[-1:] or [""]
        print(f"  ✓ 构建 + 产物自检  {tail[0][:70]}")
        return _ensure_gzip()

    print("  ✗ 前端构建/自检失败 —— 产物没更新，**不能上线**")
    # 和 run_suite 同理：把 ✗ 行连上下文抓出来，别让人只看个"失败"
    fails = [i for i, ln in enumerate(lines) if "✗" in ln or "error" in ln.lower()]
    shown: list[int] = []
    for i in fails[:12]:
        for j in range(max(0, i - 1), min(len(lines), i + 2)):
            if j not in shown:
                shown.append(j)
    shown.sort()
    for j in shown:
        print(f"      {lines[j]}")
    return False


def push_github(timeout: float = 180.0) -> bool:
    """把本地 main 推到 GitHub。成功/无事可推都返回 True。

    ⚠ 为什么不"顺手加一句 git push 就算完"：这个项目的 git 操作一律走
      bash 里的 `git`（Windows 上是 Git Bash），而 ship 是 Python 起的子进程，
      PATH 不一定一样。所以先探一遍 `git --version`，探不到就**明确报出来**
      （"没推成功"和"没 git 可用"是两回事，不能都当成成功）。
    """
    try:
        v = subprocess.run(["git", "--version"], cwd=ROOT,
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"  ✗ 找不到 git，没法推送：{e}")
        return False
    if v.returncode != 0:
        print(f"  ✗ git 不可用：{(v.stderr or '').strip()[:200]}")
        return False
    try:
        r = subprocess.run(["git", "push", "origin", "main"], cwd=ROOT,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.SubprocessError as e:
        print(f"  ✗ push 超时/失败：{e}")
        return False
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode != 0:
        print(f"  ✗ push 返回 {r.returncode}：{out[:400]}")
        return False
    print(f"  ✓ 已推送：{out.splitlines()[-1][:160] if out else 'ok'}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-test", action="store_true", help="只自检，不同步")
    ap.add_argument("--skip-test", action="store_true", help="跳过自检直接同步")
    ap.add_argument("--skip-live", action="store_true", help="跳过需要浏览器的检查")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不执行")
    a = ap.parse_args()

    print("=" * 62)
    print("噜妹书院 · 一键上线")
    print("=" * 62)
    t0 = time.time()

    # ------------------------------------------------------------------
    # [0/4] 前端构建
    # ------------------------------------------------------------------
    # 为什么把构建放进 ship、而不是让人记得手动跑：
    # 前端已经迁到 Vite + Vue3（见 frontend/），源码在 frontend/src/，
    # 产物在 app/static/dist/。**产物才是真正被部署的东西**。
    # 忘了构建 → 改了源码、传的还是上次的产物 → 线上看起来"改了没生效"，
    # 而所有测试又都是绿的（它们测的是产物）。这是最隐蔽的一类事故。
    #
    # 所以：构建 → 产物自检 → 测试，都在一条链上，顺序不可颠倒。
    # 没有 node 时**只警告不阻断**（服务器上没有 node，也不该有）。
    if not a.skip_test:
        print("\n[0/4] 前端构建（Vite → app/static/dist）")
        if not build_frontend(a.dry_run):
            print("✗ 前端构建失败，没有继续。")
            return 1

    if not a.skip_test:
        print("\n[1/4] 静态自检")
        failed = [n for n, d in STATIC_SUITES if not run_suite(n, d)]
        if failed:
            print(f"\n✗ 静态自检有 {len(failed)} 项没过：{failed}")
            print("  按上面的输出修掉再跑。**没有推到线上。**")
            return 1

        if not a.skip_live:
            print("\n[2/4] 真机自检（需要本地服务 + Chrome）")
            try:
                with LocalServer() as srv:
                    failed = []
                    for n, d in LIVE_SUITES:
                        flag = LIVE_ARGS.get(n)
                        extra = [flag, srv.base] if flag else None
                        if not run_suite(n, d, extra):
                            failed.append(n)
            except SystemExit as e:
                print(f"  {e}")
                print("  （没有本地服务就跳过真机检查；有 Chrome 的话它会自己起）")
                failed = []
            if failed:
                print(f"\n✗ 真机自检有 {len(failed)} 项没过：{failed}")
                print("  **没有推到线上。**")
                return 1
        else:
            print("\n[2/4] 真机自检 —— 已跳过")
    else:
        print("\n[0/4] 前端构建 —— 已跳过（--skip-test）")
        print("[1/4] 静态自检 —— 已跳过")
        print("[2/4] 真机自检 —— 已跳过")

    if a.only_test:
        print(f"\n✓ 自检全绿（{time.time()-t0:.1f}s）。没同步（--only-test）。")
        return 0

    print("\n[3/4] 同步到云服务器")
    cmd = [PY, str(ROOT / "tools" / "sync_cloud.py")]
    if a.dry_run:
        cmd.append("--dry-run")
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        print("\n✗ 同步失败")
        return r.returncode

    # ------------------------------------------------------------------
    # [4/4] 推送到 GitHub
    # ------------------------------------------------------------------
    # ⚠ 这一步**原先不在 ship 里**，而项目规矩写的是「一条命令：自检+上线+推送」。
    #   后果很具体：线上已经是新代码，GitHub 上还是旧的；本地提交攒了 4 个
    #   没人推（2026-10-21 实测就是这么发现的）。哪天服务器要重建，
    #   拉下来的是半年前的代码 —— 而这个缺口不会有任何报错。
    #   所以推送必须是链条的最后一环，且失败要红。
    print("\n[4/4] 推送到 GitHub")
    if a.dry_run:
        print("  · dry-run，跳过推送")
    else:
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip()
        if dirty:
            # ⚠⚠ 这里原来是"打印一句警告然后照样返回成功"。后果真发生了
            #   （2026-10-21）：ship 打印「✓ 上线完成」，线上确实换了新代码，
            #   而 GitHub 上什么都没有 —— 工作区 14 个改动没提交，
            #   而 `push` 看到"没有待推送的提交"就返回成功。
            #   这正是这个项目反复踩的那类洞：**该做的事没做，但不报错**。
            #   所以只要工作区是脏的，就必须红 —— 哪怕线上已经同步过了。
            files = dirty.splitlines()
            print(f"  ✗ 工作区有 {len(files)} 个改动没提交 —— 这些**不会**被推到 "
                  f"GitHub：")
            for ln in files[:8]:
                print(f"      {ln}")
            if len(files) > 8:
                print(f"      …… 还有 {len(files) - 8} 个")
            print("  · 线上已经更新（[3/4] 跑完了）。先 `git commit` 写清为什么，"
                  "再 `git push` 补一次即可，**不用重跑 ship**。")
            return 1
        ahead = subprocess.run(["git", "rev-list", "--count", "origin/main..HEAD"],
                               cwd=ROOT, capture_output=True, text=True).stdout.strip()
        if ahead in ("", "0"):
            print("  · 没有待推送的提交")
        else:
            print(f"  · 有 {ahead} 个提交待推送")
            if not push_github():
                print("  ✗ 推送失败 —— 线上是新的，GitHub 还是旧的。先修好再走。")
                return 1

    print(f"\n{'=' * 62}")
    print(f"✓ 上线完成，用时 {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
