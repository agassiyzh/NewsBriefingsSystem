# Feedback Worker / D1 / Pages 生产验证与回滚 Runbook

适用范围：Personal Newsroom System 当前 feedback 生产链路。

目标：
- 在不泄露 secrets 的前提下验证 Cloudflare Worker、D1 schema、GitHub Pages 注入链路是否正常。
- 只执行安全 dry-run；除非你明确需要产生生产变更，否则不要做真实 deploy / migration。
- 不修改生产 cron；不真实发送 Telegram。

当前已知生产资源：
- Worker 名称：`newsroom-feedback`
- Worker 基础地址：`https://newsroom-feedback.agassi212451.workers.dev`
- 站点地址：`https://www.yuzhuohui.info/NewsBriefingsSystem/`
- D1 绑定名：`DB`
- D1 数据库名：`newsroom_feedback`
- GitHub Pages 注入开关：repository variable `NEWSROOM_FEEDBACK_WORKER_BASE_URL`

## 0. 进入目录

```bash
cd /opt/data/home/NewsBriefingsSystem/worker
```

## 1. 生产 health check

### 1.1 Worker health

```bash
curl -fsS https://newsroom-feedback.agassi212451.workers.dev/api/health | /opt/hermes/.venv/bin/python -m json.tool
```

期望：
- `ok: true`
- `service: "newsroom-feedback"`
- `version: "phase4-mvp"`
- `allowed_origins` 包含生产站点 origin

### 1.2 Pages 页面与前端注入

主页本身可以不带具体 briefing feedback 配置；重点检查实际 briefing 页面：

```bash
curl -fsSI https://www.yuzhuohui.info/NewsBriefingsSystem/briefings/2026/2026-01-01/
curl -fsS https://www.yuzhuohui.info/NewsBriefingsSystem/briefings/2026/2026-01-01/ \
  | grep -E 'newsroom-feedback-config|newsroom-feedback-items|item-feedback-widget|feedback.js|/f\?action=like'
```

期望：
- 页面返回 `200`
- HTML 中存在 `newsroom-feedback-config`
- HTML 中存在 `newsroom-feedback-items`
- HTML 中存在 `item-feedback-widget`
- HTML 中存在 `feedback.js`
- `<noscript>` fallback 链接指向 Worker `/f`

如需确认静态资源本身可访问，可再检查：

```bash
curl -fsSI https://www.yuzhuohui.info/NewsBriefingsSystem/feedback.js
```

如需更完整检查，可用：

```bash
/opt/hermes/.venv/bin/python - <<'PY'
import urllib.request
url = 'https://www.yuzhuohui.info/NewsBriefingsSystem/briefings/2026/2026-01-01/'
req = urllib.request.Request(url, headers={'User-Agent': 'NewsroomRunbook/1.0'})
with urllib.request.urlopen(req, timeout=20) as r:
    html = r.read().decode('utf-8', 'replace')
for needle in ['newsroom-feedback-config', 'newsroom-feedback-items', 'item-feedback-widget', 'feedback.js', '/f?action=like']:
    print(needle, needle in html)
PY
```

## 2. Worker 本地测试 + Node 22 / Wrangler dry-run

注意：本机 PATH 上默认 `node` 可能不是 Node 22；同时环境里的 `XDG_CONFIG_HOME` 可能指向不可写目录，Wrangler 会因为写日志失败而报 `EACCES: permission denied, mkdir '/vol1'`。执行前请显式设置临时 HOME / XDG 目录。

```bash
cd /opt/data/home/NewsBriefingsSystem/worker
mkdir -p .tmp-xdg/config .tmp-xdg/cache .tmp-xdg/state .tmp-xdg/data .tmp-home
export VOLTA_HOME=/opt/data/.volta
export PATH="$VOLTA_HOME/bin:$PATH"
export HOME="$PWD/.tmp-home"
export XDG_CONFIG_HOME="$PWD/.tmp-xdg/config"
export XDG_CACHE_HOME="$PWD/.tmp-xdg/cache"
export XDG_STATE_HOME="$PWD/.tmp-xdg/state"
export XDG_DATA_HOME="$PWD/.tmp-xdg/data"

volta --version
volta run --node 22 node -v
volta run --node 22 npm -v
volta run --node 22 npm test
volta run --node 22 npx -y wrangler@4.93.0 deploy --dry-run
```

期望：
- `node -v` 为 `v22.x`
- `npm test` 全绿
- `wrangler deploy --dry-run` 能显示 Worker bindings 并以 `--dry-run: exiting now.` 结束

说明：
- 本 runbook 固定使用 `wrangler@4.93.0`，避免环境漂移。
- dry-run 不会创建新资源，也不会上传新版本到生产流量。

## 3. D1 schema 对齐检查与 apply

### 3.1 本地 apply / 语法验证

```bash
cd /opt/data/home/NewsBriefingsSystem/worker
mkdir -p .tmp-d1

volta run --node 22 npx -y wrangler@4.93.0 d1 execute newsroom_feedback \
  --local \
  --persist-to .tmp-d1 \
  --file=./schema.sql \
  --json
```

期望：
- 所有语句 `success: true`

### 3.2 远端 schema 对齐检查

```bash
cd /opt/data/home/NewsBriefingsSystem/worker
volta run --node 22 npx -y wrangler@4.93.0 d1 execute newsroom_feedback \
  --remote \
  --command "SELECT type, name, sql FROM sqlite_master WHERE tbl_name = 'feedback_events' OR (type='index' AND sql LIKE '%feedback_events%') ORDER BY type, name;" \
  --json
```

对齐标准：
- 存在 `feedback_events` 表
- 表字段与 `worker/schema.sql` 一致：
  - `id`
  - `event_type`
  - `channel`
  - `anonymous_id`
  - `briefing_id`
  - `item_id`
  - `target_url`
  - `duration_ms`
  - `idempotency_key`
  - `metadata_json`
  - `created_at`
- 存在索引：
  - `idx_feedback_events_created_at`
  - `idx_feedback_events_briefing_item`
  - `idx_feedback_events_type_channel`

### 3.3 远端 apply（仅在确认需要变更时执行）

只有在以下条件同时满足时才执行：
- 你确认当前 token 对应的是正确 Cloudflare account
- `wrangler.toml` 绑定的是当前 repo 的既有数据库
- `schema.sql` 不包含破坏性语句（例如 drop / truncate / incompatible rebuild）
- 这次操作就是你要执行的真实迁移

```bash
cd /opt/data/home/NewsBriefingsSystem/worker
volta run --node 22 npx -y wrangler@4.93.0 d1 execute newsroom_feedback \
  --remote \
  --file=./schema.sql \
  --json
```

如果只是验收，不需要真实改库；保留在 3.2 即可。

## 4. 线上 smoke test

### 4.1 无写入 smoke

Worker health：

```bash
curl -fsS https://newsroom-feedback.agassi212451.workers.dev/api/health | /opt/hermes/.venv/bin/python -m json.tool
```

安全 redirect（不要用 `curl -I`，Worker 只实现了 `GET /r`，`HEAD /r` 会返回 `404`）：

```bash
curl -sS -D - -o /dev/null "https://newsroom-feedback.agassi212451.workers.dev/r?u=https%3A%2F%2Fexample.com%2Fstory&briefing_id=2026-01-01-08&item_id=2026-01-01-08-001&channel=site"
```

期望：
- 返回 `302`
- `Location: https://example.com/story`

非法 redirect：

```bash
curl -sS -D - "https://newsroom-feedback.agassi212451.workers.dev/r?u=javascript%3Aalert(1)&briefing_id=2026-01-01-08&item_id=2026-01-01-08-001&channel=site"
```

期望：
- 返回 `400`
- body 含 `unsafe redirect`

可选安全探针（不写库）：

```bash
curl -sS -D - "https://newsroom-feedback.agassi212451.workers.dev/f?action=like&briefing_id=2026-01-01-08&channel=site"
```

期望：
- 返回 `400`
- body 含 `invalid feedback request`
- 该请求故意不带 `item_id`，用于验证 fallback 参数校验，不会写入有效事件

### 4.2 有写入 smoke（会产生真实事件，执行前先确认）

以下两个动作会写入生产 D1，请只在你接受“人工验收事件”进入库中时执行，并使用容易追踪的 `idempotency_key`。

`POST /api/events`：

```bash
/opt/hermes/.venv/bin/python - <<'PY'
import json, urllib.request
payload = {
    'event_type': 'like',
    'channel': 'site',
    'briefing_id': '2026-01-01-08',
    'item_id': '2026-01-01-08-001',
    'anonymous_id': 'anon_manual_verify',
    'idempotency_key': 'manual-verify-like-001',
    'metadata': {'source': 'Example Feed', 'scope': 'item'},
}
req = urllib.request.Request(
    'https://newsroom-feedback.agassi212451.workers.dev/api/events',
    data=json.dumps(payload).encode('utf-8'),
    headers={
        'Content-Type': 'application/json',
        'Origin': 'https://www.yuzhuohui.info',
        'User-Agent': 'NewsroomRunbook/1.0',
    },
    method='POST',
)
with urllib.request.urlopen(req, timeout=20) as r:
    print(r.status, r.read().decode('utf-8', 'replace'))
PY
```

`GET /f` fallback：

```bash
curl -i "https://newsroom-feedback.agassi212451.workers.dev/f?action=like&briefing_id=2026-01-01-08&item_id=2026-01-01-08-001&channel=site"
```

期望：
- `POST /api/events` 返回 `200` 且 `ok: true`
- `/f` 返回 `200` 且页面包含 `已记录，谢谢`

## 5. GitHub Pages 注入链路

生产 Pages 注入不是直接修改 repo 中的 `site/hugo.toml`，而是在 GitHub Actions 构建期通过 repository variable 打开：

- variable: `NEWSROOM_FEEDBACK_WORKER_BASE_URL`
- workflow: `.github/workflows/pages.yml`
- build 前脚本：`scripts/configure_hugo_feedback.py`

检查点：
- variable 存在时，workflow 会启用 `enabled/widgetEnabled/trackLinks/dwellEnabled`
- variable 为空时，Pages 仍应构建成功，但不注入生产 feedback 配置
- 可公开读取最近一次 Pages workflow run，确认最新 `main` 构建成功并记下 `head_sha`

如果当前 shell 没有可用的 GitHub token，可先做公开侧验证：

```bash
curl -fsS https://api.github.com/repos/agassiyzh/NewsBriefingsSystem/actions/workflows/pages.yml/runs?per_page=5
```

如有 GitHub token，再用任一带鉴权的 GitHub REST 客户端读取下面的 endpoint（例如 `gh api` 或你自己的 `curl` 封装；不要把 token 本身写进命令历史、文档或日志）：

```text
GET https://api.github.com/repos/agassiyzh/NewsBriefingsSystem/actions/variables/NEWSROOM_FEEDBACK_WORKER_BASE_URL
```

## 6. 回滚

### 6.1 立即关闭前端注入（最快）

如果问题在前端注入层，而不是 Worker 本身，优先禁用 Pages 注入：
- 将 GitHub repository variable `NEWSROOM_FEEDBACK_WORKER_BASE_URL` 清空或删除
- 重新触发 Pages workflow

结果：
- briefing 页面将不再注入生产 feedback config
- 不需要改动生产 cron
- 不会影响 Markdown archive、Telegram dry-run、Hugo 基础导出

### 6.2 Worker 版本回滚

先列出最近部署：

```bash
cd /opt/data/home/NewsBriefingsSystem/worker
volta run --node 22 npx -y wrangler@4.93.0 deployments list --name newsroom-feedback --json
```

然后回滚到目标版本：

```bash
cd /opt/data/home/NewsBriefingsSystem/worker
volta run --node 22 npx -y wrangler@4.93.0 rollback <version-id> \
  --name newsroom-feedback \
  -m "rollback feedback worker after smoke-test regression" \
  -y
```

说明：
- 先看 `deployments list` 结果，再决定回滚到哪个版本
- 回滚属于真实生产变更，应记录操作者、时间、原因、目标 version id

### 6.3 D1 回滚

当前 `schema.sql` 是 append-only MVP schema；如果未来发生真实 schema 变更，请在执行前单独准备回滚 SQL。

本 repo 当前没有自动化 D1 down migration；因此：
- 若只是验收，不要执行 3.3
- 若必须执行 3.3，请同时保存对应的 rollback SQL 和执行记录

## 7. 常见权限 / 环境问题

### 7.1 `node` 版本不是 22

症状：
- PATH 上 `node -v` 返回 `v20.x`
- `package.json` 的 `engines.node` 要求 `>=22`

处理：
- 不要依赖默认 PATH
- 使用：

```bash
export VOLTA_HOME=/opt/data/.volta
export PATH="$VOLTA_HOME/bin:$PATH"
volta run --node 22 node -v
```

### 7.2 Wrangler 写日志时报 `/vol1` 权限错误

症状：
- `EACCES: permission denied, mkdir '/vol1'`

原因：
- 当前环境的 `XDG_CONFIG_HOME` 指向不可写目录，Wrangler 尝试把日志写到该路径

处理：

```bash
mkdir -p .tmp-xdg/config .tmp-xdg/cache .tmp-xdg/state .tmp-xdg/data .tmp-home
export HOME="$PWD/.tmp-home"
export XDG_CONFIG_HOME="$PWD/.tmp-xdg/config"
export XDG_CACHE_HOME="$PWD/.tmp-xdg/cache"
export XDG_STATE_HOME="$PWD/.tmp-xdg/state"
export XDG_DATA_HOME="$PWD/.tmp-xdg/data"
```

### 7.3 `wrangler d1 execute --remote` / `deploy --dry-run` 鉴权失败

常见原因：
- `CLOUDFLARE_API_TOKEN` 缺失
- token 缺少 Workers / D1 所需 scope
- token 指向错误 account
- token 只在某些 shell / 子进程里可见，当前会话没有继承

检查：
- 先确认环境变量是否存在，不要把 token 打印出来
- 可运行 `volta run --node 22 npx -y wrangler@4.93.0 whoami` 确认当前 account
- 再确认 token scope 是否至少覆盖 Worker deploy / D1 read-write 所需权限

### 7.4 Pages 页面 200 但没有 feedback config

常见原因：
- GitHub repository variable `NEWSROOM_FEEDBACK_WORKER_BASE_URL` 未设置
- workflow 未重新跑
- 当前访问的不是 briefing 页面，而是站点首页

排查顺序：
1. 看 GitHub Actions 最近一次 Pages build 是否成功
2. 确认 repository variable 非空
3. 直接检查具体 briefing 页面 HTML，而不是只看首页

### 7.5 `POST /api/events` 返回 `403 invalid_origin`

原因：
- 请求头 `Origin` 不在 Worker allowlist 中

处理：
- 生产站点使用 `https://www.yuzhuohui.info`
- 本地开发使用 `http://localhost:1313` 或明确在 allowlist 中的 origin
- 若新站点 origin 上线，先更新 allowlist 再验收

## 8. 验收记录建议

每次真实生产操作后至少记录：
- 时间
- 操作者
- 执行命令（可脱敏）
- 是否只做 dry-run
- 是否产生真实资源变更
- 若有真实变更：目标 Worker version / D1 SQL / Pages build run
- 若有 smoke 写入：使用的 `idempotency_key`

推荐把这些信息写入 Kanban comment 或变更审计记录，而不是散落在终端历史里。