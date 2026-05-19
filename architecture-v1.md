# 小於 Personal Newsroom System 架构文档 v1

版本：v1.0
状态：正式架构基线
目标读者：Coder、Editor/Profile 维护者、后续系统评审者
适用范围：在现有 Hermes/default cron 新闻简报闭环基础上，渐进升级为“个人情报媒体系统”。

---

## 1. Executive Summary

Personal Newsroom System 的目标是把现有“每天三次自动生成新闻简报”的最小闭环，升级为一个可持续学习小於兴趣、可发布、可反馈、可分析、可复用的个人情报媒体系统。

当前系统已经具备基础能力：

- default profile cron 每天北京时间 08:00 / 13:00 / 20:00 触发新闻简报生成。
- `/opt/data/scripts/collect_news_context.py` 抓取候选新闻上下文。
- 简报推送到 Telegram。
- 每日归档到 `/opt/data/home/NewsBriefings/YYYY-MM-DD.md`。

v1 架构采用“渐进式增强”而非一次性重构：

1. 保留 default profile 作为 v1 中央调度器，避免多 profile cron 分散导致的稳定性和排障成本。
2. 引入明确角色模型：Editor 负责选题方向和最终成稿，Reporter 负责材料检索，Analyst 负责反馈分析，Publisher 负责发布链路，Coder 负责实现与 skill 沉淀。
3. 引入 Honcho 作为长期编辑记忆层，但严格隔离 Editor 与 Reporter 记忆，避免记者被长期偏好污染而降低探索性。
4. 发布链路采用 Telegram + Markdown/Obsidian + GitHub Pages 静态博客；v1 推荐 Hugo，而非 Jekyll。
5. 反馈采集采用 Cloudflare Worker + D1，先记录轻量事件：like、dislike、click、read、share、hide。
6. 月度分析由 Analyst 汇总 D1 反馈、简报历史和发布表现，生成 editorial preferences / monthly insights，再由 Editor 写入 Honcho 长期记忆。
7. Coder 最终把运行脚本、提示词、数据契约和操作文档沉淀为 `personal-newsroom` skill，供其他角色复用。

核心架构决策：v1 不构建复杂多服务系统，不引入队列，不引入独立后端数据库服务器，不迁移现有 cron；只在现有最小闭环旁边增加结构化数据、发布目录、反馈 API 和月度分析闭环。

---

## 2. Goals / Non-goals

### 2.1 Goals

系统目标：

1. 每天稳定生成三次中文新闻简报：08:00 早间版、13:00 午间版、20:00 晚间版。
2. 新闻内容持续贴合小於长期兴趣：AI、开源、Agent、海外 POS/SaaS、老年机器人、创客教育、家庭间隔年、自驾中国边境、小红书内容创作。
3. 将“主编-记者-分析师-发布者-实现者”职责拆开，使系统可扩展、可审计、可替换。
4. 同时支持私域推送与公开发布：Telegram、Markdown/Obsidian、GitHub Pages 静态博客。
5. 采集用户反馈，形成闭环：阅读行为 -> 反馈事件 -> 月度分析 -> 编辑偏好 -> 后续选题优化。
6. 将实现资产沉淀为 skill，使 Editor、Reporter、Analyst、Publisher、Coder 能用统一接口工作。
7. 保持成本低、依赖少、失败可回滚。

### 2.2 Non-goals

v1 明确不做：

1. 不做完整多用户新闻平台。
2. 不做实时新闻 App。
3. 不做复杂推荐系统或机器学习排序模型。
4. 不做全文爬虫大规模索引。
5. 不做商业化 CMS。
6. 不把所有 profile 都改成独立 cron owner。
7. 不把 Cloudflare D1 作为所有内容的唯一主存储；Markdown 文件仍是简报内容的主归档。
8. 不自动公开敏感私人判断、个人行程或未确认的投资建议。
9. 不在 v1 创建 GitHub repo、Cloudflare 资源或修改现有 cron；本文只作为后续实现依据。

### 2.3 非功能性要求

1. 稳定性：任一外部源抓取失败不应阻断当天简报生成。
2. 可恢复性：Telegram 发布失败不影响 Markdown 归档；GitHub 发布失败不影响 Telegram。
3. 可观测性：每次运行必须有日志、输入摘要、输出路径和错误信息。
4. 可测试性：采集、生成、发布、反馈 API 必须可单独测试。
5. 隐私：反馈系统默认匿名；不采集真实身份、精确位置、设备指纹。
6. 成本：v1 依赖优先使用本地文件、GitHub Pages、Cloudflare Workers/D1 免费或低成本资源。
7. 可演进性：角色、提示词、数据 schema、发布目标可独立演进。

---

## 3. Current State

### 3.1 已有能力

当前最小闭环包括：

- 调度：default profile cron，每天北京时间 08:00 / 13:00 / 20:00 运行。
- 采集：`/opt/data/scripts/collect_news_context.py`。
- 输入源：HN、GitHub Trending、MIT Technology Review AI、TechCrunch AI、The Verge AI、36Kr、少数派、Google News 关键词搜索。
- 归档目录：`/opt/data/home/NewsBriefings/`。
- 当前归档格式：`YYYY-MM-DD.md`，包含早间版、午间版、晚间版、今日沉淀。
- 推送：Telegram。

### 3.2 当前脚本特征

`collect_news_context.py` 当前职责：

1. 抓取 RSS / Atom / Google News RSS。
2. 清理不可见字符和 HTML。
3. 限制每个源和总候选数。
4. 读取当天归档内容用于去重提示。
5. 输出 Markdown 候选新闻上下文，供 agent 合成简报。

当前优点：

- 简单可靠。
- 无复杂依赖。
- 能快速产生候选新闻上下文。
- 已围绕小於兴趣设置关键词。

当前限制：

- 候选新闻没有结构化持久化到数据库。
- 没有明确 Reporter / Editor 职责边界。
- 没有用户反馈采集。
- 没有月度分析闭环。
- 没有公开发布站点结构。
- 缺少统一运行日志、发布状态和内容 ID。
- Honcho 记忆边界尚未定义。

---

## 4. Target Architecture

### 4.1 总体架构

目标架构由六层组成：

1. Scheduling Layer：default cron 统一调度每日简报和月度分析。
2. Role Orchestration Layer：以 Editor 为主流程协调者，调用 Reporter、Publisher、Analyst。
3. Collection Layer：Reporter 使用新闻源、RSS、搜索和已有脚本扩展版收集候选材料。
4. Editorial Layer：Editor 读取 Honcho 编辑记忆，决定选题、排序、写作角度和最终发布内容。
5. Publication Layer：Publisher 将结果发布到 Telegram、Markdown/Obsidian、本地 Git repo，并通过 GitHub Pages/Hugo 公开。
6. Feedback & Insight Layer：Cloudflare Worker + D1 采集反馈事件；Analyst 月度分析并生成偏好更新。

### 4.2 逻辑组件

- `newsroom-runner`：每日三次运行入口，负责加载配置、调用采集、组织角色提示、保存产物。
- `news-collector`：现有 `collect_news_context.py` 的演进版，输出 Markdown + JSONL 双格式。
- `editorial-engine`：Editor 角色提示词和成稿规则。
- `publisher`：Telegram、Markdown、GitHub Pages/Hugo 发布适配器。
- `feedback-worker`：Cloudflare Worker API，接收用户反馈事件。
- `feedback-db`：Cloudflare D1 数据库。
- `monthly-analyst`：月度分析脚本/提示词，读取 D1 导出和简报历史，生成洞察。
- `honcho-memory-adapter`：负责读取/写入 Editor 长期偏好，不允许 Reporter 直接写入 Editor 记忆。
- `personal-newsroom skill`：将以上操作文档化并提供给角色调用。

### 4.3 推荐目录布局

本地工作目录建议：

```text
/opt/data/home/NewsBriefingsSystem/
  architecture-v1.md
  config/
    newsroom.yaml
    sources.yaml
    interests.yaml
  prompts/
    editor.md
    reporter.md
    analyst.md
    publisher.md
  scripts/
    run_briefing.py
    collect_news_context.py
    publish_telegram.py
    publish_markdown.py
    export_hugo.py
    monthly_analysis.py
    validate_outputs.py
  data/
    candidates/YYYY-MM-DD-HH.jsonl
    runs/YYYY-MM-DD-HH.json
    exports/d1-events-YYYY-MM.jsonl
  logs/
    YYYY-MM-DD.log
  site/
    content/briefings/
    content/insights/
    static/
  worker/
    wrangler.toml
    src/index.ts
    schema.sql
  skill/
    personal-newsroom/
```

现有归档目录继续保留：

```text
/opt/data/home/NewsBriefings/YYYY-MM-DD.md
```

v1 不强制迁移历史归档，但 Publisher 应能从该目录读取历史内容并导出到静态站点。

---

## 5. Role Model：Editor / Reporter / Analyst / Publisher / Coder

### 5.1 Editor：主编

职责：

1. 理解小於长期兴趣、近期方向和内容偏好。
2. 在每次简报前决定选题策略：哪些主题优先、哪些主题降权、是否需要寻找反常识信号。
3. 向 Reporter 下发明确采集 brief：关键词、来源方向、排除条件、判断标准。
4. 接收 Reporter 材料后进行筛选、排序、归纳和写作。
5. 输出最终中文简报，包含：极简摘要、为什么和小於有关、链接、项目灵感/投资观察/今日信号等。
6. 读取 Analyst 的月度洞察，决定是否更新 Honcho 编辑记忆。
7. 审核可公开内容，避免泄露隐私或输出过度投资建议。

记忆边界：

- Editor 可以读取和写入 Honcho 中的长期编辑偏好。
- Editor 记忆保存“偏好、模式、长期关注、写作风格、反馈总结”，不保存每条原始新闻全文。
- Editor 不把未经确认的临时情绪直接写入长期记忆。

工具边界：

- 可以调用 Reporter、Publisher、Analyst。
- 可以读取简报历史和月度分析结果。
- 不直接调用底层 Cloudflare 管理 API。
- 不直接执行资源创建或 cron 修改。

### 5.2 Reporter：记者

职责：

1. 根据 Editor brief 搜索和抓取候选新闻。
2. 提供材料卡片：标题、来源、发布时间、链接、摘要、可信度、与小於相关性、推荐理由。
3. 去重、排除低质量内容、标记不确定信息。
4. 保持探索性：除了已知兴趣，也补充相邻领域和反常识信号。

记忆边界：

- Reporter 默认不写入长期 Honcho 编辑记忆。
- Reporter 可有短期任务上下文：本轮采集 brief、已查来源、已排除条目。
- Reporter 不继承 Editor 的全部长期偏好，只接收 Editor 本次下发的采集 brief。
- Reporter 不保存用户行为反馈明细。

工具边界：

- 可使用 RSS、搜索、网页读取、现有 `collect_news_context.py` 或其演进脚本。
- 不负责最终成稿。
- 不负责发布。
- 不负责写 Honcho 长期记忆。

### 5.3 Analyst：分析师

职责：

1. 每月分析反馈数据、点击、停留、like/dislike、简报内容主题。
2. 识别高兴趣主题、低兴趣主题、过度重复主题、标题/格式偏好。
3. 输出结构化月度洞察：事实、解释、建议、置信度。
4. 向 Editor 提交可采纳的编辑偏好更新建议。

记忆边界：

- Analyst 可读取聚合后的反馈数据和简报历史。
- Analyst 不读取不必要的个人身份信息。
- Analyst 不直接写入 Editor 长期记忆；必须由 Editor 审核后写入。

工具边界：

- 可查询 D1 导出或受限只读 API。
- 可读取本地 Markdown 归档。
- 不负责每日发布。
- 不修改 cron。

### 5.4 Publisher：发布者

职责：

1. 将 Editor 最终稿发布到 Telegram。
2. 写入 `/opt/data/home/NewsBriefings/YYYY-MM-DD.md`。
3. 同步生成 Obsidian 友好的 Markdown。
4. 导出 Hugo 内容文件到 GitHub Pages repo。
5. 为每篇简报和每条新闻生成稳定 ID，用于反馈追踪。
6. 记录发布状态：成功、失败、重试、错误信息。

记忆边界：

- Publisher 不写 Honcho 长期编辑记忆。
- Publisher 只保存发布状态和内容元数据。

工具边界：

- 可调用 Telegram Bot API。
- 可写本地 Markdown 和站点目录。
- 可执行 git commit/push，但 v1 实施前需由 Coder 配置并明确授权。
- 不决定内容取舍。

### 5.5 Coder：实现者

职责：

1. 按本文档实现脚本、配置、Worker、D1 schema、发布适配器和测试。
2. 保持对现有最小闭环的兼容。
3. 提供回滚方案和验证命令。
4. 将系统使用方式沉淀为 `personal-newsroom` skill。
5. 把角色提示词、数据契约、运行手册文档化。

记忆边界：

- Coder 不把实现日志写入 Editor 长期偏好。
- Coder 可维护技术配置文档和 skill 文档。

工具边界：

- 可修改本地脚本和配置。
- 创建 GitHub repo、Cloudflare 资源、cron 修改必须在用户明确授权后执行。

---

## 6. Data Flow：每日 08/13/20 三次流程，以及月度分析流程

### 6.1 每日 08:00 / 13:00 / 20:00 流程

v1 三次流程保持同一主链路，通过 `slot` 参数区分：`morning`、`noon`、`evening`。

步骤：

1. Cron 触发
   - default profile cron 在北京时间 08:00 / 13:00 / 20:00 触发。
   - 传入参数：日期、slot、归档路径。

2. Runner 初始化
   - 加载 `config/newsroom.yaml`。
   - 确定本次归档文件：`/opt/data/home/NewsBriefings/YYYY-MM-DD.md`。
   - 创建 run id：`YYYY-MM-DD-HH`。
   - 初始化日志。

3. Editor 读取长期偏好
   - Editor 从 Honcho 读取经过审核的长期编辑偏好。
   - Editor 读取当天已发布内容摘要，避免重复。
   - Editor 生成本轮 Reporter brief。

4. Reporter 采集候选材料
   - 调用现有采集脚本演进版。
   - 输出：
     - Markdown context：供 Editor 阅读。
     - JSONL candidates：供存档和后续分析。
   - 对候选进行去重、来源标记、相关性初筛。

5. Editor 成稿
   - Editor 根据候选材料选择 3-5 条高价值新闻。
   - 早间版偏“今日雷达和机会”；午间版偏“快讯和项目灵感”；晚间版偏“总结、趋势、可写内容”。
   - 生成中文简报。
   - 每条新闻必须包含稳定 item id、标题、摘要、相关性说明、链接。

6. Publisher 发布
   - 写入 Markdown 日归档。
   - 推送 Telegram。
   - 导出 Hugo content 文件。
   - 如果 GitHub Pages repo 已配置，则 commit/push；否则只生成本地待发布文件。

7. 状态记录
   - 写入 `data/runs/YYYY-MM-DD-HH.json`。
   - 记录候选数、入选数、发布目标状态、错误。
   - 如果某个发布目标失败，不回滚已成功目标，只标记失败并允许重试。

### 6.2 月度分析流程

触发时间建议：每月 1 日北京时间 09:30。

步骤：

1. default cron 触发 monthly analysis。
2. 导出或查询上月 D1 events。
3. 读取上月 Markdown 简报归档。
4. Analyst 聚合分析：
   - 哪些主题获得更多 like、click、read。
   - 哪些主题经常 dislike 或停留低。
   - 哪些来源质量高。
   - 哪些栏目形式更有效。
   - 哪些方向应新增或降权。
5. Analyst 输出 `monthly_insights`：
   - 事实发现。
   - 解释假设。
   - 编辑建议。
   - 置信度。
   - 建议写入 Honcho 的偏好草案。
6. Editor 审核 Analyst 建议。
7. Editor 将确认后的偏好写入 Honcho。
8. Publisher 可选生成公开或私有月度复盘 Markdown；默认私有，不公开。

---

## 7. Memory Design：Honcho 应该存什么、不应该存什么；主编与记者记忆隔离

### 7.1 Honcho 定位

Honcho 是长期编辑记忆，不是全文数据库、日志数据库或反馈明细库。

Honcho 应帮助 Editor 回答：

- 小於长期关心什么？
- 什么类型的新闻更有行动价值？
- 哪些内容过度重复需要降权？
- 喜欢什么写作风格和结构？
- 月度分析确认了哪些新偏好？

### 7.2 应该存储

Honcho 中建议存：

1. 长期兴趣主题
   - AI、开源、Agent、海外 POS/SaaS、老年机器人、创客教育、家庭间隔年、自驾中国边境、小红书内容创作。

2. 主题权重
   - 例如：Agent 基础设施高权重；泛 AI 融资低权重；老年机器人偏产品落地和渠道机会。

3. 写作偏好
   - 中文。
   - 实用。
   - 命令/配置清晰。
   - 少空泛观点，多“为什么和小於有关”。
   - 每条新闻尽量给出行动建议或观察角度。

4. 负偏好
   - 低质量标题党。
   - 无链接来源。
   - 纯融资通稿且无产品/市场信号。
   - 宏大叙事但无可执行信息。

5. 月度分析后的编辑偏好
   - 经过 Analyst 分析和 Editor 审核后的稳定结论。

6. 内容安全规则
   - 投资相关必须标注非买卖建议。
   - 公开站点不写私人行程细节、家庭隐私、未公开商业信息。

### 7.3 不应该存储

Honcho 不应存：

1. 原始点击日志、停留时间明细、IP、User-Agent。
2. 每条新闻全文。
3. 未经验证的临时情绪偏好。
4. Telegram token、Cloudflare token、GitHub token。
5. 个人敏感身份信息、精确位置、家庭隐私。
6. Reporter 的每轮临时搜索过程。
7. 可从 Markdown 归档或 D1 重新计算的运行日志。

### 7.4 Editor 与 Reporter 记忆隔离

v1 明确采用“Editor 长期记忆 + Reporter 短期任务上下文”的隔离方式。

原因：

1. Editor 需要长期一致性，Reporter 需要探索性。
2. 如果 Reporter 长期记住所有偏好，可能过度迎合旧兴趣，错过新信号。
3. 记者材料应服务本轮 brief，而不是自行决定最终选题方向。
4. 反馈数据涉及隐私，不应扩散给所有采集角色。

规则：

- Editor 从 Honcho 读取长期偏好。
- Editor 把本轮采集要求压缩成 Reporter brief。
- Reporter 只看到 brief，不直接访问完整 Honcho。
- Reporter 返回材料，不写 Honcho。
- Analyst 返回建议，不写 Honcho。
- 只有 Editor 审核后写入 Honcho。

---

## 8. Publication Design：Telegram、Markdown/Obsidian、GitHub Pages/Hugo 发布链路

### 8.1 发布目标

v1 支持三个发布目标：

1. Telegram：即时提醒和私域消费。
2. Markdown/Obsidian：长期归档、知识库检索、个人复盘。
3. GitHub Pages + Hugo：公开展示、SEO、可分享链接。

### 8.2 技术选型建议

推荐：Hugo + GitHub Pages。

不推荐 v1 使用 Jekyll 作为主方案。

决策理由：

1. Hugo 是单二进制，构建速度快，依赖少。
2. Hugo 对大量 Markdown 内容友好。
3. Hugo front matter 灵活，适合给 briefings、items、tags、sources 增加元数据。
4. GitHub Pages 支持通过 GitHub Actions 构建 Hugo，避免本地 Ruby/Jekyll 环境问题。
5. Jekyll 虽然是 GitHub Pages 原生生态，但 Ruby 依赖和插件限制会增加维护成本。

v1 结论：

- 本地 Markdown 仍是主归档。
- Hugo content 是发布导出层。
- GitHub repo 是公开站点仓库，不作为唯一内容源。

### 8.3 Markdown / Obsidian 设计

现有日归档继续使用：

```text
/opt/data/home/NewsBriefings/YYYY-MM-DD.md
```

建议格式：

```markdown
# 新闻雷达｜YYYY-MM-DD

## 08:00 早间版

<!-- briefing_id: 2026-05-19-08 -->

### 1｜标题

- item_id: 2026-05-19-08-001
- source: TechCrunch
- url: https://...
- tags: [AI, Agent, SaaS]

极简摘要：...

为什么和小於有关：...

行动/观察：...

## 13:00 午间版

## 20:00 晚间版

## 今日沉淀
- 趋势：
- 项目灵感：
- 投资观察：
- 可写内容：
```

Obsidian 友好原则：

- 保持纯 Markdown。
- 使用日期文件名。
- 使用 tags。
- 可选增加 YAML front matter，但不要破坏现有阅读体验。
- 每条新闻保留原始链接。

### 8.4 Telegram 发布设计

Telegram 内容应短、清晰、可点击。

建议格式：

```text
新闻雷达｜YYYY-MM-DD HH:MM

1｜标题
极简摘要：...
为什么和你有关：...
链接：...
👍 👎 阅读原文

今日信号：...
```

反馈按钮：

- v1 Telegram 反馈优先采用链接按钮跳转到 Worker tracking URL。
- 如果后续使用 Telegram inline keyboard callback，需要额外处理 Bot webhook 和用户身份边界；v1 不作为首选。

### 8.5 GitHub Pages / Hugo repo 结构

建议 repo 名：

```text
personal-newsroom-site
```

推荐结构：

```text
personal-newsroom-site/
  config.toml
  content/
    briefings/
      2026/
        05/
          2026-05-19.md
    insights/
      2026-05.md
    about.md
  layouts/
    _default/
      single.html
      list.html
    briefings/
      single.html
  static/
    js/
      feedback.js
    css/
      custom.css
  data/
    sources.yaml
  .github/
    workflows/
      deploy.yml
```

Hugo content front matter 示例：

```yaml
---
title: "新闻雷达｜2026-05-19"
date: 2026-05-19T08:00:00+08:00
briefing_id: "2026-05-19-08"
slot: "morning"
tags: ["AI", "Agent", "开源"]
draft: false
---
```

### 8.6 发布状态与失败策略

发布目标之间互不强依赖：

- Markdown 写入失败：本次运行视为失败，不继续发布。
- Telegram 失败：记录失败，保留 Markdown，可后续重试。
- Hugo 导出失败：记录失败，不影响 Telegram。
- Git push 失败：保留本地 commit 或待发布文件，后续重试。

---

## 9. Feedback System：Cloudflare Worker + D1 API 设计、事件类型、匿名 ID、隐私边界

### 9.1 设计目标

反馈系统目标不是做用户画像平台，而是为小於个人新闻偏好提供轻量信号。

v1 只采集必要信息：

- 哪篇 brief 被看过。
- 哪条 item 被点击。
- 哪条 item 被 like/dislike。
- 大致停留时长区间。
- 来源渠道：telegram、site、obsidian/manual。

### 9.2 Cloudflare Worker API

Base URL 示例：

```text
https://newsroom-feedback.example.workers.dev
```

#### POST /api/events

用途：记录反馈事件。

请求：

```json
{
  "event_type": "like",
  "anonymous_id": "anon_abc123",
  "briefing_id": "2026-05-19-08",
  "item_id": "2026-05-19-08-001",
  "channel": "telegram",
  "url": "https://example.com/original-news",
  "duration_ms": 12000,
  "metadata": {
    "tag": "Agent",
    "source": "TechCrunch"
  }
}
```

响应：

```json
{
  "ok": true,
  "event_id": "evt_..."
}
```

#### GET /r/:target

用途：追踪点击后跳转。

示例：

```text
/r/original?briefing_id=2026-05-19-08&item_id=2026-05-19-08-001&url=https%3A%2F%2F...
```

行为：

1. Worker 记录 `click` 事件。
2. 返回 302 跳转到目标 URL。

#### GET /f/:action

用途：Telegram 按钮反馈。

示例：

```text
/f/like?briefing_id=2026-05-19-08&item_id=2026-05-19-08-001
/f/dislike?briefing_id=2026-05-19-08&item_id=2026-05-19-08-001
```

行为：

1. 记录 like/dislike。
2. 返回一个简单 HTML 页面：“已记录，谢谢”。

#### GET /api/health

用途：健康检查。

响应：

```json
{"ok": true}
```

### 9.3 事件类型

v1 事件类型：

- `impression`：内容展示。
- `read`：页面阅读或 Telegram 打开。
- `click`：点击原文链接。
- `like`：喜欢。
- `dislike`：不喜欢。
- `share`：分享。
- `hide`：不想看类似内容。
- `dwell`：停留时长上报。

v1 必须支持：`click`、`like`、`dislike`、`dwell`。

### 9.4 匿名 ID 设计

匿名 ID 来源：

- Web site：浏览器 localStorage 生成随机 UUID。
- Telegram：默认不记录 Telegram user id；使用链接中的随机匿名 token 或省略。
- Obsidian/manual：可为空。

规则：

- anonymous_id 不应可逆推真实身份。
- 不采集姓名、手机号、邮箱。
- 不存 IP 明文。
- 如需防刷，只存 IP hash 且设置短期保留；v1 默认不做。

### 9.5 隐私边界

明确不采集：

- 精确地理位置。
- 浏览器指纹。
- Telegram 用户 ID 明文。
- 原始 IP 长期存储。
- 敏感个人备注。

公开站点边界：

- 公开内容必须经过 Publisher 安全过滤。
- 月度分析默认私有，不自动发布。
- 涉及家庭、商业客户、未公开项目的信息不进入公开站点。

---

## 10. Database Schema：D1 SQL schema

D1 使用 SQLite 语法。v1 schema 如下：

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS briefings (
  id TEXT PRIMARY KEY,
  briefing_date TEXT NOT NULL,
  slot TEXT NOT NULL CHECK (slot IN ('morning', 'noon', 'evening', 'monthly')),
  title TEXT NOT NULL,
  summary TEXT,
  markdown_path TEXT,
  site_path TEXT,
  telegram_message_id TEXT,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'partial_failed', 'failed')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  published_at TEXT,
  metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_briefings_date_slot
ON briefings (briefing_date, slot);

CREATE TABLE IF NOT EXISTS news_items (
  id TEXT PRIMARY KEY,
  briefing_id TEXT NOT NULL,
  rank INTEGER NOT NULL,
  title TEXT NOT NULL,
  source TEXT,
  source_url TEXT NOT NULL,
  published_at TEXT,
  snippet TEXT,
  relevance_reason TEXT,
  tags_json TEXT,
  selected INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  metadata_json TEXT,
  FOREIGN KEY (briefing_id) REFERENCES briefings(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_news_items_briefing
ON news_items (briefing_id, rank);

CREATE INDEX IF NOT EXISTS idx_news_items_source
ON news_items (source);

CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL CHECK (event_type IN ('impression', 'read', 'click', 'like', 'dislike', 'share', 'hide', 'dwell')),
  anonymous_id TEXT,
  briefing_id TEXT,
  item_id TEXT,
  channel TEXT CHECK (channel IN ('telegram', 'site', 'obsidian', 'manual', 'unknown')),
  target_url TEXT,
  duration_ms INTEGER,
  user_agent_hash TEXT,
  ip_hash TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  metadata_json TEXT,
  FOREIGN KEY (briefing_id) REFERENCES briefings(id) ON DELETE SET NULL,
  FOREIGN KEY (item_id) REFERENCES news_items(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_events_created_at
ON events (created_at);

CREATE INDEX IF NOT EXISTS idx_events_type
ON events (event_type);

CREATE INDEX IF NOT EXISTS idx_events_briefing_item
ON events (briefing_id, item_id);

CREATE TABLE IF NOT EXISTS monthly_insights (
  id TEXT PRIMARY KEY,
  month TEXT NOT NULL UNIQUE,
  summary TEXT NOT NULL,
  findings_json TEXT NOT NULL,
  recommendations_json TEXT NOT NULL,
  honcho_update_proposal TEXT,
  editor_approved INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  approved_at TEXT,
  metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS editorial_preferences (
  id TEXT PRIMARY KEY,
  preference_type TEXT NOT NULL CHECK (preference_type IN ('interest', 'style', 'source', 'negative', 'safety', 'format')),
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  weight REAL NOT NULL DEFAULT 1.0,
  source TEXT NOT NULL CHECK (source IN ('manual', 'monthly_insight', 'editor')),
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT,
  metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_editorial_preferences_type_key
ON editorial_preferences (preference_type, key);
```

### 10.1 Schema 决策

1. Markdown 是内容主归档，D1 是反馈和索引数据库。
2. `briefings` 存发布单元元数据。
3. `news_items` 存被选入简报的新闻条目；候选全集可先保存在本地 JSONL，不必全部进 D1。
4. `events` 存反馈事件。
5. `monthly_insights` 存月度分析结果。
6. `editorial_preferences` 存已结构化的偏好，可作为 Honcho 写入前后的桥接表。

---

## 11. Cron/Profile Strategy：default 中央调度 vs researcher/profile-owned cron vs Kanban 的取舍；推荐 v1 方案

### 11.1 方案 A：default 中央调度

说明：

- 所有定时任务仍由 default profile cron 触发。
- default 负责调用脚本和指定角色 prompt。
- 日志集中。

优点：

- 与现有系统兼容。
- 修改少，风险低。
- 排障路径清晰。
- 避免多 profile cron 漏跑、重复跑。

缺点：

- default 承担较多协调职责。
- 角色自治性弱。

### 11.2 方案 B：researcher/profile-owned cron

说明：

- Reporter / Analyst 等 profile 各自拥有 cron。
- 角色自行执行自己的周期任务。

优点：

- 角色职责更自治。
- 长期可扩展到多专业 reporter。

缺点：

- v1 排障复杂。
- 容易出现状态不同步。
- 需要跨 profile 协调协议。
- 当前最小闭环迁移成本高。

### 11.3 方案 C：Kanban 驱动

说明：

- default cron 只创建任务卡。
- Kanban 协调员将任务派给 Editor / Reporter / Analyst / Coder。

优点：

- 非常适合复杂长期项目和人工参与。
- 任务可追踪、可复盘。

缺点：

- 对每日三次稳定自动发布来说链路偏重。
- 如果 Kanban 工具不可用，会影响新闻时效性。
- 自动化运行需要额外状态机。

### 11.4 v1 推荐

v1 明确推荐：default 中央调度 + 角色提示词分工 + 可选 Kanban 人工任务。

具体策略：

1. 每日 08/13/20 简报继续由 default cron 触发。
2. 月度分析也由 default cron 触发。
3. Reporter、Editor、Analyst 先通过 prompt 和脚本边界实现角色分离，而不是拆成各自 cron。
4. Kanban 只用于实现阶段任务分派、异常处理、选题专题项目，不进入每日主链路。
5. 等 v1 稳定 1-2 个月后，再评估是否把 Analyst 月度任务迁移为 profile-owned cron。

---

## 12. Implementation Phases：Phase 1 到 Phase 6

### Phase 1：整理现有闭环与配置化

目标：

- 保持现有功能不变，将来源、关键词、输出路径、slot 配置化。

任务：

1. 创建 `/opt/data/home/NewsBriefingsSystem/config/newsroom.yaml`。
2. 创建 `sources.yaml` 和 `interests.yaml`。
3. 将 `collect_news_context.py` 复制/迁移到系统目录并保持兼容。
4. 增加 `--slot`、`--date`、`--output-jsonl` 参数。
5. 增加运行日志。

验收标准：

- 手动运行采集脚本能输出与当前类似的 Markdown。
- 能额外生成 JSONL 候选文件。
- 不影响现有 cron。

回滚方案：

- 保留 `/opt/data/scripts/collect_news_context.py` 原文件。
- cron 继续使用原脚本。

### Phase 2：角色提示词与 Runner

目标：

- 引入 Editor / Reporter / Publisher 的清晰接口，但不改变外部发布行为。

任务：

1. 创建 `prompts/editor.md`、`prompts/reporter.md`、`prompts/publisher.md`。
2. 实现 `scripts/run_briefing.py`。
3. 定义 run manifest：`data/runs/YYYY-MM-DD-HH.json`。
4. 确保输出仍写入 `/opt/data/home/NewsBriefings/YYYY-MM-DD.md`。

验收标准：

- 手动执行 runner 能生成某个 slot 的简报。
- run manifest 记录输入、输出、错误。
- Markdown 格式不破坏既有归档。

回滚方案：

- cron 仍可回到原 prompt + 原采集脚本。

### Phase 3：Publication 扩展到 Hugo 本地导出

目标：

- 增加 GitHub Pages/Hugo 站点导出能力，但不自动创建 repo。

任务：

1. 创建 `site/content/briefings/`。
2. 实现 `scripts/export_hugo.py`。
3. 为每个 briefing 和 item 增加稳定 ID。
4. 生成 Hugo front matter。
5. 增加本地构建说明。

验收标准：

- 能从日归档生成 Hugo content Markdown。
- 不需要 GitHub repo 也能完成本地导出。
- 内容不包含敏感私有信息。

回滚方案：

- 删除或忽略 `site/` 目录，不影响 Telegram 和日归档。

### Phase 4：Feedback Worker + D1

目标：

- 增加反馈 API 和数据库 schema。

任务：

1. 创建 `worker/schema.sql`。
2. 创建 Cloudflare Worker TypeScript 代码。
3. 实现 `/api/health`、`/api/events`、`/r/*`、`/f/*`。
4. 增加最小 CORS 策略。
5. 增加匿名 ID 生成说明。
6. 更新 Telegram/Hugo 链接，使其经过 Worker tracking URL。

验收标准：

- 本地或测试环境可插入事件。
- click 能记录并 302 跳转。
- like/dislike 能记录并返回确认页。
- 不采集明文 IP 或真实身份。

回滚方案：

- 发布链接恢复直链。
- Worker 停用不影响简报生成。

### Phase 5：Monthly Analyst 闭环

目标：

- 建立月度反馈分析和编辑偏好更新机制。

任务：

1. 实现 `scripts/monthly_analysis.py`。
2. 读取 D1 events 导出和 Markdown 归档。
3. 生成 `monthly_insights` Markdown/JSON。
4. Analyst 输出建议。
5. Editor 审核后写入 Honcho 或 `editorial_preferences`。

验收标准：

- 能生成上月分析报告。
- 报告包含高兴趣主题、低兴趣主题、来源质量、格式建议。
- 不直接把原始行为日志写入 Honcho。

回滚方案：

- 停止月度分析 cron。
- 保留 D1 events，不影响每日简报。

### Phase 6：Skill Packaging

目标：

- 将系统沉淀为可复用 `personal-newsroom` skill。

任务：

1. 创建 skill 目录。
2. 编写 `SKILL.md`。
3. 收录角色提示词、命令、数据契约、排障手册。
4. 提供典型任务模板：生成简报、导出 Hugo、分析月度反馈、重试发布。
5. 增加 coder handoff 文档。

验收标准：

- 新角色阅读 skill 后能知道如何参与 newsroom。
- Coder 能按 skill 执行常见维护任务。
- 不泄露 token 和个人隐私。

回滚方案：

- skill 仅为文档和模板，停用不影响主链路。

---

## 13. Risks and Tradeoffs

### 13.1 稳定性风险

风险：RSS 源不可用、网页格式变化、Google News 限流、Telegram API 失败。

缓解：

- 抓取失败降级为错误条目，不阻断流程。
- 发布目标独立失败。
- 每次运行保存 manifest。
- 保留原脚本回滚路径。

### 13.2 成本风险

风险：Cloudflare、GitHub Actions、外部 API 使用超限。

缓解：

- v1 不使用付费搜索 API。
- D1 只存轻量事件。
- Hugo 静态站点低成本。
- 候选全集留本地 JSONL，不全部写远程数据库。

### 13.3 隐私风险

风险：反馈事件、阅读行为、兴趣偏好可能暴露个人信息。

缓解：

- anonymous_id 随机生成。
- 不存真实身份。
- 不存 IP 明文。
- 月度分析默认私有。
- 公开站点过滤家庭、客户、未公开商业信息。

### 13.4 公开内容风险

风险：公开博客发布未经核实新闻、投资判断或私人观点。

缓解：

- 每条新闻保留来源链接。
- 投资观察标注非买卖建议。
- 对不确定信息使用“待验证”“媒体报道”。
- Publisher 加安全过滤规则。

### 13.5 反馈噪音风险

风险：点击不代表喜欢，停留时间受上下文影响，样本量小。

缓解：

- Analyst 输出置信度。
- 不因单次事件改变长期记忆。
- 只把月度稳定模式写入 Honcho。
- 同时参考 like/dislike、click、read、主题重复度。

### 13.6 平台限制风险

风险：Telegram inline callback 需要 webhook，GitHub Pages 构建限制，Cloudflare Worker CORS 和 D1 绑定配置复杂。

缓解：

- v1 Telegram 使用链接按钮而非 callback。
- Hugo 通过 GitHub Actions 构建。
- Worker API 保持极简。
- 所有平台配置文档化。

### 13.7 架构复杂度权衡

本架构刻意不引入：

- 消息队列。
- 独立后端服务。
- 向量数据库。
- 多 agent 长期自治 cron。
- 大规模全文索引。

取舍理由：当前目标是个人情报系统，最重要是稳定闭环和可演进边界，而不是平台化复杂度。

---

## 14. Coder Handoff：给 coder 的分解任务列表

按推荐执行顺序：

1. 建立目录结构
   - 创建 `/opt/data/home/NewsBriefingsSystem/config`。
   - 创建 `/opt/data/home/NewsBriefingsSystem/prompts`。
   - 创建 `/opt/data/home/NewsBriefingsSystem/scripts`。
   - 创建 `/opt/data/home/NewsBriefingsSystem/data`。
   - 创建 `/opt/data/home/NewsBriefingsSystem/logs`。
   - 创建 `/opt/data/home/NewsBriefingsSystem/site`。
   - 创建 `/opt/data/home/NewsBriefingsSystem/worker`。

2. 配置文件
   - 实现 `config/newsroom.yaml`。
   - 实现 `config/sources.yaml`。
   - 实现 `config/interests.yaml`。
   - 不写入 token。

3. 采集脚本演进
   - 从现有 `/opt/data/scripts/collect_news_context.py` 迁移或包装。
   - 增加 CLI 参数。
   - 增加 JSONL 输出。
   - 保持 Markdown stdout 兼容。

4. ID 规范
   - briefing_id：`YYYY-MM-DD-HH`。
   - item_id：`YYYY-MM-DD-HH-NNN`。
   - event_id：Worker 生成 UUID。

5. Prompt 文件
   - 写 `prompts/editor.md`。
   - 写 `prompts/reporter.md`。
   - 写 `prompts/analyst.md`。
   - 写 `prompts/publisher.md`。
   - 明确输入、输出、禁止事项。

6. Runner
   - 实现 `scripts/run_briefing.py`。
   - 负责加载配置、调用采集、组装上下文、保存 manifest。
   - 先支持手动运行，不改 cron。

7. Markdown Publisher
   - 实现按 slot 更新日归档。
   - 防止覆盖其他 slot 内容。
   - 保留“今日沉淀”。

8. Telegram Publisher
   - 封装现有 Telegram 发送逻辑。
   - 支持失败重试和状态记录。
   - token 从环境变量读取。

9. Hugo Exporter
   - 实现 `scripts/export_hugo.py`。
   - 从归档生成 Hugo content。
   - 加 front matter、tags、briefing_id。

10. Worker schema
   - 写 `worker/schema.sql`，使用本文第 10 节 schema。

11. Worker API
   - 实现 `/api/health`。
   - 实现 `/api/events`。
   - 实现 `/r/*` click redirect。
   - 实现 `/f/like`、`/f/dislike`。
   - 增加输入校验和简单限流。

12. Feedback JS
   - 在 `site/static/js/feedback.js` 实现 anonymous_id 和 dwell 上报。

13. Monthly Analysis
   - 实现 `scripts/monthly_analysis.py`。
   - 输入 D1 events 导出和 Markdown 归档。
   - 输出 JSON + Markdown 洞察。

14. Honcho 更新协议
   - 写 `docs/honcho-memory-policy.md` 或放入 skill。
   - 明确只有 Editor 审核后写入。

15. 测试与验证
   - 采集脚本 dry-run。
   - Runner dry-run。
   - Markdown slot 更新测试。
   - Hugo export 测试。
   - Worker API 本地测试。
   - D1 schema migration 测试。

16. 回滚文档
   - 记录如何恢复原 cron 使用原采集脚本。
   - 记录如何禁用 Worker tracking。
   - 记录如何停止 Hugo 发布。

17. Skill 打包
   - 完成 `skill/personal-newsroom/`。
   - 将命令、提示词、schema、排障步骤写入 skill。

---

## 15. Skill Packaging Plan：personal-newsroom skill 的目录结构和内容

### 15.1 Skill 目标

`personal-newsroom` skill 应让任意角色快速理解：

- 如何生成每日简报。
- 如何采集新闻候选。
- 如何按 Editor 标准成稿。
- 如何发布到 Telegram / Markdown / Hugo。
- 如何查询和分析反馈。
- 如何安全更新 Honcho 记忆。

### 15.2 推荐目录结构

```text
skill/personal-newsroom/
  SKILL.md
  README.md
  commands/
    generate-briefing.md
    collect-candidates.md
    publish-telegram.md
    export-hugo.md
    analyze-monthly-feedback.md
    retry-failed-publication.md
  prompts/
    editor.md
    reporter.md
    analyst.md
    publisher.md
    coder.md
  schemas/
    candidate.schema.json
    run-manifest.schema.json
    event.schema.json
    d1-schema.sql
  examples/
    briefing-input.md
    briefing-output.md
    monthly-insight.md
    hugo-frontmatter.md
  policies/
    memory-policy.md
    privacy-policy.md
    publication-safety.md
  runbooks/
    daily-runbook.md
    monthly-analysis-runbook.md
    troubleshooting.md
    rollback.md
```

### 15.3 SKILL.md 内容大纲

`SKILL.md` 应包含：

1. Skill 何时使用。
2. 系统边界。
3. 角色职责。
4. 常用命令。
5. 输入输出路径。
6. ID 规范。
7. 发布安全规则。
8. Honcho 记忆规则。
9. 反馈分析规则。
10. 禁止事项。

### 15.4 Commands 文档要求

每个 command 文档必须包含：

- 用途。
- 前置条件。
- 输入参数。
- 示例命令。
- 输出文件。
- 验收标准。
- 常见错误。
- 回滚方式。

### 15.5 Policies 文档要求

必须沉淀三类 policy：

1. Memory Policy
   - 什么能写 Honcho。
   - 什么不能写。
   - Editor 审核流程。

2. Privacy Policy
   - 反馈事件采集边界。
   - 匿名 ID 规则。
   - 公开内容过滤规则。

3. Publication Safety
   - 投资内容免责声明。
   - 家庭/客户/未公开项目信息过滤。
   - 来源链接和不确定性标注。

---

## 附录 A：v1 推荐配置摘要

```yaml
system:
  timezone: Asia/Shanghai
  archive_dir: /opt/data/home/NewsBriefings
  system_dir: /opt/data/home/NewsBriefingsSystem
  default_language: zh-CN

schedule:
  morning: "08:00"
  noon: "13:00"
  evening: "20:00"
  monthly_analysis: "1st day 09:30"

publication:
  telegram: true
  markdown: true
  hugo_export: true
  github_push: false

feedback:
  provider: cloudflare_worker_d1
  collect_ip_plaintext: false
  collect_telegram_user_id: false
  default_channel: unknown

memory:
  provider: honcho
  editor_can_write: true
  reporter_can_write: false
  analyst_can_write: false
```

---

## 附录 B：v1 架构结论

1. v1 保留 default cron 中央调度。
2. v1 不把 Reporter / Analyst 拆成独立 cron owner。
3. v1 推荐 Hugo + GitHub Pages，不推荐 Jekyll 作为主方案。
4. v1 使用 Cloudflare Worker + D1 做轻量反馈系统。
5. v1 Markdown 仍是简报内容主归档。
6. v1 D1 主要存元数据、反馈事件和分析结果。
7. v1 Honcho 只存长期编辑偏好，不存原始事件和敏感数据。
8. v1 Editor 与 Reporter 记忆隔离。
9. v1 月度分析结果必须由 Editor 审核后才写入长期记忆。
10. v1 所有新增能力必须可关闭，不破坏现有 Telegram + Markdown 最小闭环。
