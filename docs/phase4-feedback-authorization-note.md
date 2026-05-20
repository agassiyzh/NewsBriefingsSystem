# Phase 4 Feedback MVP 授权边界与使用说明

项目：Personal Newsroom System / 小於新闻简报系统

用途：这份说明用于向用户确认 Feedback MVP 的安全推进范围、需要额外授权的生产动作、后续需要用户决策的信息，以及 Phase 4 完成后的闭环路径。本文不包含任何 token、secret、账号 ID 或生产配置。

---

## 1. 结论摘要

Phase 4 Feedback MVP 可以先在“本地、静态、默认关闭、可回滚”的范围内推进：实现前端反馈 widget、事件 payload schema、mock/dry-run endpoint、Hugo 静态站点集成和本地测试。这个阶段不会创建真实 Cloudflare Worker/D1，不写入 Cloudflare token/secrets，不修改生产新闻 cron，也不会真实发送 Telegram 或发布月度分析。

在用户明确授权之前，反馈功能应保持 disabled-by-default。任何会触碰真实云资源、生产发送、生产调度、长期标识符或公开发布聚合洞察的动作，都必须先暂停并请求用户确认。

---

## 2. 当前可安全推进的本地/静态范围

以下事项可以由后续 coder 在本地 repo 内推进，不需要立即触碰生产资源：

1. 前端 feedback widget
   - 在 Hugo 页面中加入可关闭的 like / dislike 控件。
   - 默认不显示或 disabled-by-default，只有本地配置启用时才加载。
   - Worker 不可用时只显示非阻塞提示，不影响阅读。

2. Payload schema 与校验契约
   - 定义 `like`、`dislike`、`click`、`dwell` 四类 MVP 事件。
   - 可接受但不优先实现 `read`；暂缓 `impression`、`share`、`hide`。
   - 校验 `event_type`、`channel`、`briefing_id`、`item_id`、`target_url`、`duration_ms`、`metadata` 大小与白名单。

3. Mock / dry-run endpoint
   - 可在本地实现 `/api/health`、`/api/events`、`/r`、`/f`。
   - 可用本地 D1 或 mock 存储验证请求、去重、CORS、redirect safety。
   - 不执行 `wrangler deploy`，不创建远程 D1，不写真实 Cloudflare 配置。

4. Hugo 集成
   - 可增加默认关闭的 Hugo params，例如 `feedback.enabled=false`、`workerBaseUrl=""`、`trackLinks=false`。
   - 可增加页面或 slot 的 `data-briefing-id`、`data-channel` 等静态 data attributes。
   - 可增加本地反馈 partial / JS，但必须保证 config absent 或 disabled 时 Hugo build 正常、页面内容正常。
   - link tracking 必须由开关控制；关闭后应恢复原始直链。

5. 本地测试
   - Worker validation tests：事件类型、必填字段、metadata 限制、CORS、idempotency、unsafe redirect。
   - Hugo/static tests：默认关闭、JS 禁用可读、Worker 缺失不影响阅读、link rewrite 仅在启用时发生。
   - 如触碰 Python export 代码，再跑现有 Python 测试。

---

## 3. 必须等待用户明确授权的事项

以下动作不应由后续 worker 自行推进；必须先向用户确认并获得明确授权：

1. 真实创建 Cloudflare Worker。
2. 真实创建 Cloudflare D1 database。
3. 执行 `wrangler deploy` 或任何生产部署。
4. 写入 Cloudflare API token、account id、database id、secret salt 或任何 secret。
5. 修改生产新闻 cron 或现有生产发布调度。
6. 真实发送 Telegram 消息。
7. 建立 Telegram inline callback、webhook 或任何会触达真实用户的 bot 集成。
8. 启用 Telegram tracking links 到真实发送链路。
9. 引入 IP hash、长期设备标识、额外持久标识符或防刷 secret。
10. 公开发布月度反馈分析、聚合洞察或原始反馈数据。

建议后续 worker 遇到上述事项时使用 block / review-required 方式暂停，而不是猜测配置或代替用户决策。

---

## 4. 用户未来需要提供或决定的信息清单

上线前至少需要用户确认以下信息：

1. Cloudflare 资源
   - 使用哪个 Cloudflare account。
   - D1 database 名称。
   - Worker 名称、route 或 subdomain。
   - 是否允许由 worker 创建资源，或由用户先手动创建后提供绑定信息。

2. 允许的站点 origin
   - 生产站点 origin，例如 `https://www.yuzhuohui.info`。
   - GitHub Pages / Hugo 实际发布路径是否还有其他 origin。
   - 本地开发 origin 是否只允许 `http://localhost:1313`、`http://127.0.0.1:8787`。

3. Telegram tracking links
   - 是否启用 Telegram 链接点击统计。
   - 是否只在 dry-run preview 中展示，还是未来允许进入真实 Telegram 发送。
   - 是否接受匿名随机 token；不得使用 Telegram user id 明文。

4. 数据保留周期
   - D1 feedback events 保留多久，例如 30 天、90 天、180 天或更长。
   - 月度汇总生成后是否删除明细事件。
   - 是否需要导出 JSONL 归档，以及归档保留多久。

5. IP hash 与防刷策略
   - MVP 默认不存 IP。
   - 如果未来需要防刷，是否允许短期 `sha256(ip + rotating_salt)`。
   - daily_salt / weekly_salt 属于 secret，不能写入 repo，需要用户授权后通过 secret 管理。

6. 聚合洞察公开范围
   - 是否允许公开任何月度聚合反馈洞察。
   - 如允许，公开粒度是什么：只公开趋势摘要、只公开主题偏好，还是完全不公开。
   - 是否允许在对外页面展示点击/喜欢数量。

---

## 5. 隐私承诺与风险提示

默认隐私承诺：

1. 默认匿名
   - Site 侧可使用客户端随机生成的 `anon_<uuid>`，保存在 localStorage。
   - 用户清除浏览器数据后会重新生成。
   - 不要求登录，不绑定真实身份。

2. 默认不采集敏感身份信息
   - 不采集姓名、邮箱、电话。
   - 不采集精确位置。
   - 不采集浏览器指纹。
   - 不采集 raw user agent。
   - 不保存 Telegram user id / username 明文。
   - 不保存长期明文 IP。

3. 点击跳转 URL 安全
   - `/r` redirect 必须拒绝 `javascript:`、`data:`、`file:`、protocol-relative URL、空 host、malformed URL 和明显不安全目标。
   - 默认只允许 `https://`；localhost dev 可例外。
   - 失败时返回安全错误页，不在 HTML 中直接反射原始 URL。
   - link tracking 必须可关闭，关闭后恢复原始直链。

4. D1 事件用途限制
   - D1 feedback events 只用于兴趣分析和产品反馈闭环。
   - 不用于用户画像、广告投放、身份识别或跨站跟踪。
   - 月度 Analyst 分析应优先使用聚合数据，不公开原始事件。

5. 风险提示
   - 即使匿名事件也可能在小流量情况下暴露阅读偏好，因此公开报告必须控制粒度。
   - 点击 tracking 会改变链接跳转路径，需要确保 redirect safety 和可关闭开关。
   - 引入 IP hash、防刷 salt 或 Telegram tracking token 后，隐私边界会变强相关，必须单独授权和记录保留策略。

---

## 6. Phase 4 建议推进路径

建议按以下顺序推进，逐步扩大范围：

1. 本地验证
   - 完成本地 Worker/mock endpoint、payload validation、Hugo widget、link rewrite 开关和测试。
   - 确认默认关闭时现有简报生成、Markdown archive、Hugo build、GitHub Pages 发布和 Telegram dry-run 都不受影响。

2. 用户授权
   - 向用户展示本说明和本地验证结果。
   - 用户确认 Cloudflare account、D1/Worker 名称、origin allowlist、Telegram tracking、数据保留、IP hash、防刷和公开洞察策略。

3. Cloudflare 测试部署
   - 在用户授权后创建或绑定测试 Worker/D1。
   - 使用测试 route/subdomain 和小样本页面验证 `/api/health`、`/api/events`、`/r`、`/f`。
   - 不直接切到全量生产流量。

4. 小流量启用
   - 先只对站点页面启用 page-level like/dislike 和 dwell。
   - link tracking 可单独开关；Telegram tracking 应更晚启用。
   - 观察错误率、重复事件、D1 写入量和用户阅读体验。

5. 月度 Analyst 闭环
   - 将 D1 events 或导出 JSONL 与 Markdown archive / Hugo metadata join。
   - 产出月度兴趣分析：高兴趣主题、低兴趣主题、点击但低 dwell 的内容、用户偏好变化。
   - 默认只内部使用；公开发布任何聚合洞察前再次确认。

---

## 7. 给用户的可粘贴确认话术

我们可以先安全推进 Phase 4 Feedback MVP 的本地/静态部分：前端反馈按钮、事件 schema、mock/dry-run endpoint、Hugo 集成和本地测试。这个阶段默认关闭反馈功能，不创建真实 Cloudflare Worker/D1，不写入任何 Cloudflare token 或 secret，不修改生产新闻 cron，也不真实发送 Telegram。

需要你明确授权后才会做的事情包括：创建或部署 Cloudflare Worker/D1、配置 Cloudflare secrets、修改生产 cron、启用真实 Telegram tracking/send、引入 IP hash 防刷、以及公开发布任何月度反馈分析。

上线前还需要你决定：Cloudflare account 和 Worker/D1 名称、允许的站点 origin、是否启用 Telegram tracking links、反馈数据保留多久、是否允许短期 IP hash 防刷、以及是否允许公开任何聚合洞察。默认隐私承诺是匿名、最小化采集，不记录明文身份、精确位置、浏览器指纹、长期 IP 或 Telegram user id 明文；D1 事件只用于兴趣分析闭环。

推荐路径是：本地验证 -> 你确认授权和配置 -> Cloudflare 测试部署 -> 小流量启用 -> 月度 Analyst 分析闭环。

---

## 8. 后续 worker 决策摘要

Allowed now:
- Local/static widget, schema, mock/dry-run endpoint, Hugo integration, local tests.
- Disabled-by-default config and placeholder/example config.
- Local-only Worker + D1 schema/testing without deploy.

Block for user authorization:
- Real Cloudflare Worker/D1 creation or deploy.
- Any token/secret/account/database id writing.
- Production cron changes.
- Real Telegram send, webhook, callback, or tracking links in production.
- IP hash or new persistent identifiers.
- Public monthly insight publishing.

Open decisions:
- Cloudflare account / D1 name / Worker route or subdomain.
- Allowed origins.
- Telegram tracking policy.
- Data retention period.
- IP hash / anti-abuse policy.
- Public aggregation policy.
