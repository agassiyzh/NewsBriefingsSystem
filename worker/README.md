# worker/

本目录用于 Phase 4 Feedback MVP 的本地安全 scaffold。

目标：
- 只支持本地 mock / dry-run 验证 feedback payload、redirect 行为与前端集成。
- 默认不连接真实 Cloudflare Worker/D1，不写 token/secrets，不执行 deploy。
- 即使 worker 不可用，Hugo 页面也必须保持可读并优雅降级。

目录说明：
- `src/index.js`：mock Worker 入口，提供以下端点：
  - `GET /api/health`：返回本地健康状态与允许的 origins
  - `POST /api/events`：校验 payload、做内存去重、返回 dry-run 接收结果
  - `GET /r`：安全 click redirect，限制到 https 或 localhost
  - `GET /f`：本地 fallback feedback 入口；默认仅允许本地 host 记录并返回 thank-you HTML，公开 host 需显式开启
- `schema.sql`：feedback_events 表的本地 schema 草案
- `wrangler.toml.example`：仅示例配置，供后续人工接入真实 Cloudflare 前参考
- `test/*.test.js`：Node 原生测试，覆盖前端 payload 契约与 worker mock API

本地验证：
1. 运行 worker / frontend 测试：
   `cd /opt/data/home/NewsBriefingsSystem/worker && npm test`
2. 或在仓库根目录直接运行：
   `node --test worker/test/frontend-feedback.test.js worker/test/feedback-worker.test.js`

安全边界：
- 仅允许白名单字段：`briefing_id`、`item_id`、`event_type`、`channel`、`anonymous_id`、`duration_ms`、`target_url`、`metadata`、`idempotency_key`
- 不接受真实身份、精确位置、浏览器指纹、明文 Telegram user id、长期明文 IP
- `metadata` 仅允许有限 key，并限制总长度
- `target_url` 仅允许 `https://` 或 `http://localhost` / `http://127.0.0.1`

回滚：
- 不启动 worker，或保持 `config/newsroom.yaml` 中 feedback 默认值不变，即可完全禁用该能力。
- 删除/忽略 `worker/` 不会影响 Markdown 归档、Telegram dry-run 与 Hugo 基础导出。
