# 月度兴趣分析指标与报告模板

任务：设计 NewsBriefingsSystem 月度兴趣分析指标和报告模板；仅产出分析/文档，不改代码。

## 0. 背景与证据基线

当前系统已有或已约定的输入：

1. D1 / Worker feedback event 基线
   - `worker/schema.sql` 已有 `feedback_events` 单表，字段包括 `event_type`、`channel`、`anonymous_id`、`briefing_id`、`item_id`、`target_url`、`duration_ms`、`metadata_json`、`created_at`。
   - 当前允许事件类型为 `like`、`dislike`、`click`、`dwell`、`read`；任务假设后续还会有 `link_click`、`impression`、`deep_dive`。
   - `docs/phase4-feedback-architecture.md` 明确 MVP 事件范围、匿名最小化采集、D1 事件仅用于兴趣分析闭环，不应公开原始事件。

2. Markdown / Hugo 内容基线
   - `newsroom/publisher.py` 从 Markdown archive 解析 `briefing_id`、`item_id`、`source`、`url`、`tags`，并导出 Hugo front matter 中的 `item_ids`、`sources`、`tags`、`slots` 等字段。
   - `site/static/feedback.js` 允许 metadata 白名单包含 `source`、`tag`、`tags`、`scope`、`dwell_bucket`、`client_version`。

3. 分析角色边界
   - `prompts/analyst.md` 规定 Analyst 输出月度事实发现、解释假设、编辑建议、置信度和建议写入 Honcho 的草案；禁止直接写入 Honcho，必须交由 Editor 审核。
   - `docs/phase4-feedback-authorization-note.md` 要求不采集或公开真实身份、精确位置、设备指纹、明文 IP、Telegram user id；月度分析应优先使用聚合数据。

## 1. 关键发现

### 发现 1：月度兴趣分析应以“内容维度 join 行为事件”为核心，而不是只看事件计数

结论：每月先把 D1 聚合事件按 `briefing_id + item_id` join 到 Markdown/Hugo 内容目录，再按 topic/source/tag 做分组。直接按 event 表统计会丢失 `summary`、`why_relevant`、source/tag 语义，无法判断编辑策略。

置信度：高。

证据：D1 单表只保存事件与少量 metadata；Markdown/Hugo 归档才是内容事实来源，已有 `briefing_id`、`item_id`、`source`、`tags`、`summary`、`why_relevant` 假设字段。

### 发现 2：CTR、深读率、负反馈率都必须带样本量阈值，否则小流量月报会误导

结论：topic/source/tag 排名默认只展示达到阈值的分组；未达阈值只能进入“观察池”，不能写入稳定偏好。

置信度：高。

证据：Phase 4 文档已提示匿名小流量也可能暴露阅读偏好；低样本下单次 like/dislike 或点击会造成极端百分比。

### 发现 3：可写入 Honcho/memory 的只能是跨月稳定、可操作的 editorial preference

结论：例如“连续 3 个月，AI agent 工具链 tag 的深读率显著高于月均，建议保持高权重”可以进入候选 memory；“本月某条新闻被点击 4 次”或 raw event 不能写入。

置信度：高。

证据：任务约束明确“不写 raw event 到 memory，只建议稳定 editorial preference”；Analyst prompt 也要求“建议写入 Honcho 的草案”，不是直接写入。

### 发现 4：报告应同时保留“趋势/项目灵感/投资观察/来源质量/降权内容/下月策略”六个视角

结论：单纯按点击排序会偏向标题党；月报需要把行为信号转化为编辑判断：哪些主题值得继续追踪、哪些 source 质量高、哪些内容点击高但 dwell 低应降权。

置信度：中高。

证据：任务明确要求报告模板包含这六个栏目；`why_relevant` 与 `summary` 字段支持从“用户行为”回看“为什么相关”。

## 2. 月度指标定义

### 2.1 分析窗口与基础实体

- 月度窗口：按系统主时区 `Asia/Shanghai` 的自然月统计，使用 `created_at` 过滤事件。
- item_catalog：从 Hugo/Markdown 归档导出，至少包含：
  - `briefing_id`
  - `item_id`
  - `published_at` 或 briefing 日期/slot
  - `source`
  - `url`
  - `tags`
  - `topic`：建议由 tags 映射得到；没有 topic 时可用首个一级 tag 或人工 taxonomy。
  - `summary`
  - `why_relevant`
- event_facts：从 D1 导出/聚合，至少包含：
  - `event_type`
  - `channel`
  - `anonymous_id`，只用于去重，不在报告展示
  - `briefing_id`
  - `item_id`
  - `target_url`
  - `duration_ms`
  - `metadata_json`
  - `created_at`

### 2.2 去重口径

默认统计去重用户-内容交互，避免重复点击放大：

- like/dislike：`unique(anonymous_id, item_id, event_type)`；同一匿名用户同一 item 同一月只计 1 次。
- link_click：`unique(anonymous_id, item_id, target_url, day)`；若没有 `anonymous_id`，退化为事件计数，并标记低置信度。
- impression：`unique(anonymous_id, item_id, day)`；如 impression 是 page-level，则按 briefing 展开到 item 时必须单独标记为估算。
- dwell：每个 `anonymous_id + briefing_id + session` 取一次；没有 session_id 时按 `anonymous_id + briefing_id + day` 取最大或最后一次。
- deep_dive：建议定义为 item-level 显式事件，或从 `dwell >= 120s + clicked` 派生；派生指标必须标记为 inferred。

### 2.3 topic/source/tag 统一指标

以下指标均可按 `dimension_type in (topic, source, tag)` 和 `dimension_value` 分组计算。

#### 1. 曝光量 / 样本量

- `items_published` = 当月归档中该分组的 item 数。
- `impressions` = 该分组 item 的去重 impression 数。
- `read_sessions` = 该分组 briefing 或 item 的去重 read/dwell session 数。
- `feedback_users` = 有 like/dislike 的去重匿名用户数。

用途：所有 rate 都必须同时展示分母。

#### 2. 点击率 CTR

优先口径：

```text
ctr = unique_link_clicks / impressions
```

当 impression 尚未上线时，只输出替代指标，不称为 CTR：

```text
click_per_read_session = unique_link_clicks / read_sessions
click_per_item = unique_link_clicks / items_published
```

建议展示字段：

- `unique_link_clicks`
- `impressions`
- `ctr`
- `ctr_delta_vs_prev_month`
- `ctr_lift_vs_month_avg = ctr / monthly_avg_ctr - 1`

#### 3. Like rate / Dislike rate

优先口径：

```text
like_rate = unique_likes / impressions
like_feedback_share = unique_likes / (unique_likes + unique_dislikes)
dislike_rate = unique_dislikes / impressions
```

当 impression 不可用：

```text
like_per_read_session = unique_likes / read_sessions
feedback_sentiment = (unique_likes - unique_dislikes) / (unique_likes + unique_dislikes)
```

解释：`like_rate` 衡量“看到后点赞”的概率；`like_feedback_share` 衡量“表达反馈的人里正向占比”。二者不能混用。

#### 4. 深读率 Deep-read rate

推荐最终口径：

```text
deep_read_rate = unique_deep_dive_events / impressions
```

MVP / 无 deep_dive 事件时的派生口径：

```text
deep_read_inferred = dwell_duration_ms >= 120000 OR dwell_bucket = '120s+'
deep_read_rate_inferred = unique_deep_read_sessions / read_sessions
```

建议同时输出：

- `avg_dwell_seconds`
- `median_dwell_seconds`
- `p75_dwell_seconds`
- `deep_read_rate`
- `click_then_deep_read_rate = deep_read_after_click / unique_link_clicks`，若能按 session 关联。

#### 5. 负反馈率 Negative feedback rate

负反馈由显式 dislike 与“点击后短停留”共同构成：

```text
explicit_negative_rate = unique_dislikes / impressions
short_dwell_after_click_rate = clicked_sessions_with_dwell_lt_10s / clicked_sessions
negative_feedback_rate = weighted_negative_events / impressions
```

建议权重：

```text
weighted_negative_events = unique_dislikes + 0.5 * clicked_sessions_with_dwell_lt_10s
```

注意：短 dwell 可能只是外部网页加载慢、读者稍后再读或切换设备，不能等同 dislike；报告中应分开展示 explicit 与 inferred。

#### 6. 来源质量 Source quality score

仅用于排序和编辑讨论，不建议直接写入 memory：

```text
source_quality_score =
  0.30 * normalized_ctr_lift
+ 0.25 * normalized_deep_read_lift
+ 0.20 * normalized_like_feedback_share
- 0.15 * normalized_negative_feedback_rate
+ 0.10 * consistency_score
```

`consistency_score` 可由过去 3 个月 source 指标方差反向计算；新 source 无足够历史时只进入观察池。

### 2.4 样本量阈值

建议把阈值分成“可展示、可判断、可写入 memory”三级。

#### topic 维度

- 可展示：`items_published >= 3` 且 `impressions >= 30` 或 `read_sessions >= 15`。
- 可判断：`items_published >= 5` 且 `impressions >= 100` 或 `read_sessions >= 50`。
- 可写入 memory 候选：连续 3 个月满足“可判断”，且方向一致。

#### source 维度

- 可展示：`items_published >= 2` 且 `impressions >= 20` 或 `read_sessions >= 10`。
- 可判断：`items_published >= 4` 且 `impressions >= 80` 或 `read_sessions >= 40`。
- 可写入 memory 候选：连续 2-3 个月高于/低于月均，且至少 8 个 item 样本。

#### tag 维度

- 可展示：`items_published >= 3` 且 `impressions >= 30` 或 `read_sessions >= 15`。
- 可判断：`items_published >= 6` 且 `impressions >= 120` 或 `read_sessions >= 60`。
- 可写入 memory 候选：连续 3 个月稳定，且不是由单一 source 或单一事件驱动。

#### 低流量保护

- 若分组低于“可展示”阈值：不显示 rate，只列为“样本不足”。
- 若达到“可展示”但低于“可判断”：可报告为观察，不给强结论。
- 若 anonymous_id 缺失率 > 30%：去重不可靠，所有 user-level rate 降为中/低置信度。
- 若 impression 尚未上线：CTR / like_rate / dislike_rate 不得使用 impression 分母，只能输出替代指标。

## 3. 月度报告模板

建议文件名：`reports/monthly-interest/YYYY-MM.md` 或 Analyst 输出消息。

```markdown
# NewsBriefingsSystem 月度兴趣分析｜YYYY-MM

## A. 本月摘要

- 覆盖范围：YYYY-MM-01 至 YYYY-MM-DD，Asia/Shanghai。
- 内容样本：briefings=N，items=N，sources=N，tags=N。
- 行为样本：impressions=N，link_clicks=N，likes=N，dislikes=N，dwell_sessions=N，deep_dives=N。
- 数据质量：高/中/低；说明缺失事件、低样本分组、anonymous_id 缺失率。
- 本月总判断：3-5 条，一条一句。

## B. 趋势 Trend

### B1. 上升主题 / tags

表格字段：

| rank | dimension | value | items | impressions/read_sessions | ctr或替代指标 | deep_read_rate | like_feedback_share | MoM变化 | 置信度 | 解释 |

分析要求：

- 只把达到“可判断”阈值的分组列为趋势。
- 对达到“可展示”但未达“可判断”的分组标记“观察”。
- 解释必须引用 `summary` / `why_relevant` 中的共性，而不是只说“点击高”。

### B2. 下降主题 / tags

表格字段同上，增加：

- `negative_feedback_rate`
- `short_dwell_after_click_rate`
- `possible_reason`

输出要求：区分“真的不感兴趣”和“标题/来源/链接体验问题”。

## C. 项目灵感 Project ideas

从高 CTR + 高 deep-read + 高 like share 的条目中提炼项目灵感。

每条格式：

```text
项目灵感：<一句话>
证据：<topic/tag/source 指标 + 2-3 个代表 item>
为什么现在值得做：<来自 why_relevant 的共同点>
下一步：<可在下月追踪的关键词/source/tag>
置信度：高/中/低
```

规则：

- 至少需要 2 个不同 source 或 2 个不同 briefing 支撑，避免单条新闻驱动。
- 项目灵感可以进入月报，但通常不能直接写入 memory；只有变成持续 editorial preference 才能进入 memory 候选。

## D. 投资观察 Investment observations

从“高深读但未必高 like”的主题中提炼投资/产业观察。

每条格式：

```text
观察：<产业/公司/赛道变化>
证据：<深读率、点击后深读率、source 多样性、代表 item>
风险：<样本量、source 偏差、是否由单一事件驱动>
下月验证：<要继续追踪的信号>
置信度：高/中/低
```

规则：

- 不把投资观察写成投资建议。
- 不因单月点击高就判断长期趋势。

## E. 来源质量 Source quality

表格字段：

| source | items | ctr/替代点击指标 | deep_read_rate | like_feedback_share | negative_feedback_rate | source_quality_score | 建议 |

建议分类：

- 升权：样本达标，连续高于月均，负反馈低。
- 保持：指标接近月均或样本不足但内容重要。
- 观察：新 source 或样本不足。
- 降权：连续低点击/低深读/高负反馈，且不是因为 topic 冷门造成。

## F. 应降权内容 Downweight candidates

每条格式：

```text
降权候选：<topic/source/tag 或内容类型>
触发信号：<低 CTR、低 dwell、高 dislike、点击后短停留等>
样本量：items=N, impressions/read_sessions=N
可能原因：<标题泛、source 弱、与 why_relevant 不匹配、过度重复>
处理建议：<减少频率/换 source/改摘要角度/仅保留重大进展>
置信度：高/中/低
```

规则：

- 不因 1-2 条差表现直接降权整个 source。
- 对公共安全、政策、重大事件等“低互动但必要”的内容，标记为“低互动但保留”，而非降权。

## G. 下月编辑策略

输出 5-8 条可执行策略：

```text
1. 增加：<topic/tag/source>，目标占比 <x%>，原因 <证据>。
2. 减少：<topic/tag/source>，触发条件 <证据>。
3. 保持：<稳定高价值方向>。
4. 实验：<新 source/tag/栏目>，设置样本目标和复盘指标。
5. 采集改进：<需要更稳定 tags/topic/source metadata 的地方>。
```

每条都要标注：证据、样本量、置信度、是否建议进入 memory 候选。

## H. Honcho / memory 候选

### 可提交给 Editor 审核、可能写入 memory 的内容

仅限稳定 editorial preference：

- 连续多月稳定高兴趣的 topic/tag。
- 连续多月质量稳定的 source。
- 用户明确偏好的内容角度，例如“更喜欢可操作项目灵感而非纯融资新闻”。
- 明确应减少的重复低价值内容类型。

格式：

```text
memory候选：<声明性偏好，不含 raw event>
证据窗口：YYYY-MM 至 YYYY-MM，连续 N 个月
样本量：items=N, impressions/read_sessions=N
指标摘要：相对月均 +X%，负反馈 -Y%
建议动作：新增/替换/删除/不写入
置信度：高/中/低
Editor审核问题：<需要人判断的边界>
```

### 只能留在月报、不能写入 memory 的内容

- raw event、单条点击、单个 anonymous_id 行为。
- 本月短期热点、突发新闻导致的临时峰值。
- 样本量不足的 topic/source/tag。
- 与个人身份、IP、设备、Telegram user id、浏览器信息相关的任何推断。
- 未经 Editor 审核的自动结论。
- 具体 item 的“有人喜欢/不喜欢”事实。

## I. 矛盾点与未解问题

必须显式列出：

- 点击高但 dwell 低：可能是标题吸引但内容不匹配，也可能是外链体验问题。
- like 高但点击低：可能摘要已经满足需求，未必 source 差。
- dislike 高但 deep-read 高：可能内容重要但令人不适，不应自动降权。
- source 质量高但 topic 低互动：可能是选题问题，不是 source 问题。
- impression 缺失或低样本：只能输出替代指标，不能给强结论。
```

## 4. Honcho / memory 写入边界

### 4.1 可以写入 memory 的结论

前提：必须经 Editor 审核；Analyst 只提供候选。

可写类型：

1. 稳定主题偏好
   - 例：`用户连续 3 个月对 AI agent 工作流、开发者工具链、自动化实践类内容表现出高深读和高正反馈。`

2. 稳定 source 偏好
   - 例：`某 source 在机器人/AI 工具主题上连续 3 个月高于月均深读率，适合保持采集权重。`

3. 稳定内容角度偏好
   - 例：`用户更偏好包含可操作项目灵感、实现路径或市场验证信号的简报条目。`

4. 稳定降权规则
   - 例：`泛泛融资通稿若没有产品进展、技术细节或投资观察，连续多月低深读，应降低优先级。`

写入要求：

- 用声明性事实，不用命令式规则。
- 不包含 raw event、anonymous_id、IP、设备、具体点击次数。
- 不包含会在一周内过时的单月任务状态。
- 附带证据摘要和置信度，但不要把事件明细写入 memory。

### 4.2 只能留在月报的内容

- 本月具体 top item / bottom item。
- 单月 CTR、like/dislike、dwell 数值。
- 单条新闻表现、单一 source 的短期波动。
- 小样本观察池。
- deep_dive 派生规则造成的不确定结果。
- 需要 Editor 决策的矛盾结论。

## 5. 给后续 coder 的查询 / 导出脚本需求

目标：产出一个可复用的月度聚合数据包，供 Analyst 读入生成报告；脚本只导出聚合和 join 后内容事实，不导出 raw event 到 memory。

### 5.1 建议新增脚本

1. `scripts/export_feedback_events.py`
   - 输入：`--month YYYY-MM`、`--d1-db PATH_OR_BINDING` 或 `--events-jsonl PATH`。
   - 输出：本地私有文件，不提交公开站点：`data/feedback/monthly/YYYY-MM/events.jsonl` 或聚合 parquet/json。
   - 字段：保留 event 事实用于本地聚合；不要写入 Hugo public。

2. `scripts/build_item_catalog.py`
   - 输入：`site/content/briefings/` 或 Markdown archive 根目录。
   - 输出：`data/feedback/monthly/YYYY-MM/item_catalog.jsonl`。
   - 字段：`briefing_id,item_id,date,slot,source,url,tags,topic,summary,why_relevant`。

3. `scripts/monthly_interest_export.py`
   - 输入：`--month YYYY-MM`。
   - 过程：读取 D1/events 导出 + item_catalog，按 `briefing_id,item_id` join。
   - 输出：
     - `data/feedback/monthly/YYYY-MM/dimension_metrics.csv`
     - `data/feedback/monthly/YYYY-MM/item_metrics.csv`
     - `data/feedback/monthly/YYYY-MM/data_quality.json`
     - `reports/monthly-interest/YYYY-MM-draft.md` 可选。

### 5.2 SQL / 聚合要求

需要支持以下聚合表。

#### item_metrics

字段：

```text
month
briefing_id
item_id
source
url
tags
topic
summary
why_relevant
items_published_flag
impressions
unique_link_clicks
unique_likes
unique_dislikes
dwell_sessions
avg_dwell_ms
median_dwell_ms
p75_dwell_ms
deep_dive_events
deep_read_inferred_sessions
short_dwell_after_click_sessions
negative_events_weighted
anonymous_id_missing_rate
first_seen_at
last_event_at
```

#### dimension_metrics

对 `topic/source/tag` 分别输出：

```text
month
dimension_type
dimension_value
items_published
sources_count
briefings_count
impressions
read_sessions
unique_link_clicks
unique_likes
unique_dislikes
deep_dive_events
deep_read_inferred_sessions
ctr
click_per_read_session
like_rate
like_feedback_share
dislike_rate
explicit_negative_rate
short_dwell_after_click_rate
negative_feedback_rate
avg_dwell_ms
median_dwell_ms
p75_dwell_ms
mom_delta_ctr
mom_delta_deep_read_rate
mom_delta_like_feedback_share
sample_tier  # insufficient / display / judge / memory_candidate
confidence  # high / medium / low
```

#### data_quality

字段：

```json
{
  "month": "YYYY-MM",
  "events_total": 0,
  "items_joined": 0,
  "events_without_item_match": 0,
  "events_without_briefing_match": 0,
  "anonymous_id_missing_rate": 0.0,
  "impression_available": false,
  "deep_dive_available": false,
  "dwell_available": true,
  "timezone": "Asia/Shanghai",
  "warnings": []
}
```

### 5.3 D1 SQL 查询草案

注意：D1 schema 当前为 `click`，任务假设未来可能叫 `link_click`。脚本应兼容两者：`event_type IN ('click','link_click')`。

```sql
-- 月度事件基础过滤
SELECT
  event_type,
  channel,
  anonymous_id,
  briefing_id,
  item_id,
  target_url,
  duration_ms,
  metadata_json,
  created_at
FROM feedback_events
WHERE created_at >= :month_start
  AND created_at < :month_end;
```

```sql
-- item-level 去重点击
SELECT
  item_id,
  COUNT(DISTINCT COALESCE(anonymous_id, id) || '|' || COALESCE(target_url, '') || '|' || substr(created_at, 1, 10)) AS unique_link_clicks
FROM feedback_events
WHERE event_type IN ('click', 'link_click')
  AND created_at >= :month_start
  AND created_at < :month_end
  AND item_id IS NOT NULL
GROUP BY item_id;
```

```sql
-- like / dislike 去重
SELECT
  item_id,
  event_type,
  COUNT(DISTINCT COALESCE(anonymous_id, id)) AS unique_feedback_users
FROM feedback_events
WHERE event_type IN ('like', 'dislike')
  AND created_at >= :month_start
  AND created_at < :month_end
  AND item_id IS NOT NULL
GROUP BY item_id, event_type;
```

```sql
-- dwell 统计
SELECT
  briefing_id,
  item_id,
  COUNT(*) AS dwell_events,
  AVG(duration_ms) AS avg_dwell_ms
FROM feedback_events
WHERE event_type = 'dwell'
  AND created_at >= :month_start
  AND created_at < :month_end
GROUP BY briefing_id, item_id;
```

### 5.4 脚本实现约束

- 默认输出到私有 `data/feedback/monthly/`，不要自动发布到 Hugo public。
- 不写 raw event 到 Honcho/memory。
- 不输出 anonymous_id 到报告；只在本地聚合中用于去重。
- 对缺失 impression/deep_dive 的月份自动降级为替代指标，并写入 `data_quality.warnings`。
- 所有 rate 都要带分母与 sample_tier。
- join 失败的事件进入 data quality，不要静默丢弃。
- 兼容 `click` 与未来 `link_click`，兼容 `dwell` 与未来 `deep_dive`。
- 不需要接触 Cloudflare secrets；如果要连接真实 D1，需要用户单独授权。

## 6. 矛盾点与处理方式

1. `like/dislike` 当前实现要求 item_id，但架构文档曾提到 whole-briefing feedback 可无 item_id。
   - 处理：本月指标以 item-level 为主；page/briefing-level feedback 单独进入 briefing_metrics，不混入 item/source/tag 判断。
   - 置信度：高。

2. `click` 与任务中的 `link_click` 命名不一致。
   - 处理：查询层兼容 `event_type IN ('click','link_click')`；报告统一称“link_click”。
   - 置信度：高。

3. impression 尚未稳定上线时，CTR 与 like_rate 的标准分母缺失。
   - 处理：不伪造 CTR；只输出 `click_per_read_session`、`click_per_item`、`like_per_read_session` 等替代指标，并标记低/中置信度。
   - 置信度：高。

4. short dwell 可能代表负反馈，也可能代表外链体验或读者被摘要满足。
   - 处理：负反馈分显式和推断两列；降权建议必须要求显式 dislike 或连续多月短 dwell 支撑。
   - 置信度：中。

## 7. 整体置信度评估

整体置信度：中高。

原因：

- 高置信：事件 schema、内容 metadata、隐私边界和 Analyst 职责在现有 repo 文档中已有明确基础。
- 中置信：CTR、deep_read、source_quality 的最终口径依赖未来 impression/deep_dive 事件是否上线，以及 D1 导出方式。
- 低置信风险：小流量月份、anonymous_id 缺失、page-level dwell 展开到 item-level 时会引入偏差。

## 8. 未解问题

1. topic taxonomy 是否已有固定配置？若没有，后续 coder/Editor 需要定义 tags 到 topic 的映射文件。
2. `why_relevant` 当前是否已经稳定写入 Hugo/Markdown？若没有，需要先扩展导出或 parser 才能支持报告解释。
3. impression 的精确定义是什么：页面曝光、item 进入 viewport、还是 Telegram 发送曝光？不同定义不能混用。
4. deep_dive 是显式事件，还是 dwell/click 派生？若是派生，需要固定阈值并在报告中标注 inferred。
5. 数据保留周期、真实 D1 连接方式、是否公开月度聚合洞察仍需要用户授权确认。
