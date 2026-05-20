# Phase 4 Feedback MVP architecture

Status: architecture design for coder handoff
Project: Personal Newsroom System / 小於新闻简报系统
Scope: Feedback MVP only; no production deployment, no token/secrets, no cron changes, no real Telegram sends

---

## 1. 目标与约束

### 1.1 Phase 4 MVP 目标

Phase 4 的目标是在现有 Phase 3 GitHub Pages / Hugo 发布层旁边，增加一个安全、匿名、可测试、可回滚的反馈采集切片，为后续 Analyst 月度分析提供轻量行为信号。

MVP 优先支持：

1. Site 页面反馈：
   - item 或 briefing 的 like / dislike。
   - 原文链接 click tracking。
   - briefing 页面 dwell time。
2. Telegram tracking link：
   - 只设计链接形态与 payload 契约。
   - 本阶段不真实发送 Telegram，也不改生产 Telegram cron。
3. Worker + D1：
   - 本地可开发、可测试的 Cloudflare Worker + D1 设计。
   - 可以写 schema、wrangler.toml 示例、mock/dry-run endpoint、测试。
   - 不创建真实 Cloudflare Worker/D1 资源，不写 token/secrets，不 deploy。
4. Hugo 集成：
   - 在静态站点中渐进注入 feedback widget 与 data attributes。
   - Worker 不可用或 JS 禁用时，文章阅读体验不受影响。

### 1.2 明确非目标

Phase 4 MVP 不做：

1. 不做多用户账户系统。
2. 不做推荐模型或自动排序闭环。
3. 不采集真实身份、精确位置、浏览器指纹、Telegram user id 明文或长期明文 IP。
4. 不迁移 Markdown 归档主存储；Markdown 仍是简报内容主档案。
5. 不修改 /opt/data/scripts 旧生产脚本。
6. 不修改现有新闻 cron。
7. 不真实发送 Telegram。
8. 不创建 Cloudflare 资源，不执行 wrangler deploy，不写入 CF token/secrets。

### 1.3 当前输入基线

基于当前 repo 形态：

- `architecture-v1.md` 第 9-10 章已有反馈 API、事件类型、隐私边界和 D1 schema 初版。
- `site/layouts/_default/single.html` 当前只渲染文章内容和 slot 摘要。
- `site/layouts/_default/baseof.html` 使用内联最小 CSS。
- `worker/README.md` 只是 Cloudflare Worker + D1 反馈采集预留目录。
- `newsroom/runner.py` 输出 run manifest，包含 `briefing_id`、`slot`、`archive_path`、`jsonl_output`、`markdown_output`、`publication`。
- `newsroom/publisher.py` 已能从 Markdown archive 解析 `briefing_id`、`item_id`、`source`、`url`、`tags` 并导出 Hugo front matter。
- 当前 Hugo front matter 已包含 `briefing_day`、`timezone`、`item_count`、`item_ids`、`sources`、`tags`、`slots`。

---

## 2. 架构概览

### 2.1 组件边界

```text
Hugo static page
  ├─ article content remains plain HTML/Markdown
  ├─ optional feedback widget JS
  ├─ data attributes: briefing_id / item_id / source_url / channel
  └─ graceful fallback: original links remain usable

Cloudflare Worker
  ├─ GET  /api/health
  ├─ POST /api/events
  ├─ GET  /r
  └─ GET  /f

Cloudflare D1
  ├─ feedback_events: append-only MVP event table
  └─ optional future tables: briefings/news_items/monthly_insights

Existing newsroom pipeline
  ├─ collector / runner unchanged for MVP unless coder adds stable IDs/front matter fields
  ├─ Markdown archive remains source of truth
  ├─ Hugo export adds static metadata and safe tracking link transformation
  └─ Telegram remains dry-run/design only
```

### 2.2 数据流

Site like/dislike：

```text
Reader clicks widget button
  -> browser sends POST /api/events with anonymous_id + event_type + briefing_id/item_id
  -> Worker validates payload + CORS origin
  -> Worker computes idempotency_key if missing
  -> D1 INSERT OR IGNORE feedback_events
  -> Worker returns { ok: true, event_id, duplicate }
```

Site link click：

```text
Reader clicks article original link
  -> link may point to /r?u=<encoded-url>&briefing_id=...&item_id=...&channel=site
  -> Worker validates destination URL against safe redirect policy
  -> Worker records click event
  -> Worker returns 302 to destination
```

Site dwell time：

```text
Page loads
  -> JS records visible time locally
  -> on pagehide/visibilitychange, send POST /api/events event_type=dwell
  -> Worker accepts coarse duration bucket or bounded duration_ms
  -> if Worker unavailable, no retry loop that blocks navigation
```

Telegram tracking link design only：

```text
Future Telegram preview message contains /r?channel=telegram&briefing_id=...&item_id=...&u=...
Future feedback link contains /f?action=like&channel=telegram&briefing_id=...&item_id=...&token=...
Phase 4 MVP may render preview/dry-run text only; it must not send real Telegram messages.
```

---

## 3. 关键决策

### Decision 1: 收窄 architecture-v1 的事件范围

`architecture-v1.md` 初版列出 `impression/read/click/like/dislike/share/hide/dwell`。Phase 4 MVP 应只实现：

- required: `like`, `dislike`, `click`, `dwell`
- accepted but optional/no-op future-compatible: `read`
- defer: `impression`, `share`, `hide`

理由：

- MVP 需要最小闭环，不要先做过宽行为画像。
- `impression` 容易产生高频噪声和隐私争议。
- `share/hide` 需要更清晰 UI 和分析语义，后续再加。

### Decision 2: MVP 使用单表 append-only event store

虽然 `architecture-v1.md` 第 10 章设计了 `briefings/news_items/events/monthly_insights/editorial_preferences` 多表，Phase 4 MVP 建议先实现 `feedback_events` 单表，并保留向完整 schema 演进的字段。

理由：

- 当前 Markdown/Hugo 已经携带 briefing/item 元数据，D1 不必立即承担内容索引主库职责。
- 单表更易本地测试、回滚和导出。
- 月度分析可以先从 event JSONL/D1 export + Markdown archive join。

### Decision 3: anonymous_id 由客户端随机生成，默认不绑定身份

Site 侧第一次访问生成 `anon_<uuid>`，保存在 localStorage。用户清除浏览器数据后重新生成。

规则：

- 不从 IP、UA、屏幕尺寸等信息推导 ID。
- 不使用浏览器指纹。
- 不要求登录。
- Telegram 未来只使用随机 token 或省略 anonymous_id，不记录 Telegram user id 明文。

### Decision 4: click tracking 必须可关闭且原始链接可恢复

Hugo export 可以把原文链接改写为 `/r?...`，但必须由配置开关控制。禁用后应恢复直链，不影响 Hugo build 或阅读。

建议配置：

```yaml
feedback:
  enabled: false
  worker_base_url: ""
  widget_enabled: false
  track_links: false
  dwell_enabled: false
```

默认实现建议 `enabled=false` 或 local/mock endpoint，直到用户明确授权真实 Worker/D1。

### Decision 5: CORS 只允许已知站点 origin

Worker 只接受以下来源中的显式配置项：

- `https://www.yuzhuohui.info`
- 本地开发 origin，例如 `http://localhost:1313`
- Wrangler dev origin，例如 `http://127.0.0.1:8787`

不要使用 `Access-Control-Allow-Origin: *` 配合可写 POST endpoint。

---

## 4. Event schema

### 4.1 Allowed values

`event_type`：

- MVP required: `like`, `dislike`, `click`, `dwell`
- Optional accepted: `read`
- Future/deferred: `impression`, `share`, `hide`

`channel`：

- `site`
- `telegram`
- `obsidian`
- `manual`
- `unknown`

Phase 4 site widget 默认上报 `channel=site`。Telegram tracking links 只设计，不真实发送。

### 4.2 POST /api/events request

```json
{
  "event_type": "like",
  "channel": "site",
  "briefing_id": "2026-01-01-08",
  "item_id": "2026-01-01-08-001",
  "anonymous_id": "anon_018f4b2e-9f2a-7c24-a6fd-5b13ad4e9f1e",
  "target_url": "https://example.com/agent-workflow",
  "duration_ms": 12000,
  "idempotency_key": "optional-client-generated-key",
  "metadata": {
    "source": "Example Feed",
    "tag": "AI Agent",
    "dwell_bucket": "10-30s"
  }
}
```

### 4.3 Required/optional fields

Required for all events:

- `event_type`: string enum.
- `channel`: string enum; default to `unknown` only if omitted by legacy client.
- `briefing_id`: string; required for site/Hugo events.

Required by event type:

- `like/dislike`: `briefing_id`; `item_id` optional only for whole-briefing feedback. Widget should send `scope=briefing` or `scope=item` in metadata if item_id is absent.
- `click`: `briefing_id`, `item_id`, `target_url`.
- `dwell`: `briefing_id`, `duration_ms`; `item_id` normally absent because dwell is page-level.
- `read`: `briefing_id`.

Optional:

- `anonymous_id`: optional but recommended for site; can be null for manual/obsidian.
- `idempotency_key`: optional; Worker can derive one.
- `metadata`: small JSON object with whitelisted keys.

### 4.4 Field validation rules

Recommended limits:

- `event_type`: enum only.
- `channel`: enum only.
- `briefing_id`: regex `^\d{4}-\d{2}-\d{2}-(08|13|20|morning|noon|evening|monthly)$` or a documented compatible slot format. Current system uses `YYYY-MM-DD-HH` like `2026-01-01-08`.
- `item_id`: regex `^\d{4}-\d{2}-\d{2}-(08|13|20)-\d{3}$` for current item IDs; allow null.
- `anonymous_id`: regex `^anon_[A-Za-z0-9._:-]{8,128}$`; reject anything that looks like email/phone/token dump.
- `target_url`: valid `https://` URL; `http://` allowed only for localhost dev.
- `duration_ms`: integer 0 to 30 minutes; clamp or reject larger values.
- `metadata`: serialized JSON <= 1024 bytes, object only, no nested arrays/objects beyond one level.

### 4.5 Metadata whitelist

Allowed metadata keys for MVP:

- `source`: display source name, max 100 chars.
- `tag`: single tag, max 50 chars.
- `tags`: optional small array of strings, max 5 items, each max 50 chars.
- `scope`: `briefing` or `item`.
- `dwell_bucket`: `0-10s`, `10-30s`, `30-120s`, `120s+`.
- `client_version`: widget version string.

Forbidden metadata:

- raw user agent
- raw IP
- precise geolocation
- Telegram user id / username
- email / phone / name
- full browser fingerprint
- arbitrary long page text
- secrets or environment variables

### 4.6 Idempotency and deduplication

Recommended `idempotency_key` derivation if client does not send one:

```text
sha256(event_type + channel + anonymous_id + briefing_id + item_id + target_url + time_bucket)
```

Time bucket guidance:

- `like/dislike`: day bucket; repeated click on same button updates client UI but only one stored event per user/item/action/day.
- `click`: minute bucket; allows repeated intentional clicks but avoids accidental double submits.
- `dwell`: page session bucket; client should send one event on pagehide, with `session_id` stored only in memory and included in idempotency derivation.

D1 should enforce:

```sql
UNIQUE(idempotency_key)
```

Worker insert behavior:

- Use `INSERT OR IGNORE` or catch unique constraint.
- Return `{ "ok": true, "duplicate": true }` for duplicate submissions.
- Never fail the page UI just because duplicate was ignored.

---

## 5. Privacy and security boundary

### 5.1 Default privacy posture

Default is anonymous and minimal. The system must not collect:

- real identity
- name / phone / email
- precise location
- browser fingerprint
- Telegram user id in plaintext
- long-term plaintext IP
- raw user agent
- sensitive personal notes

### 5.2 IP and abuse handling

MVP default: do not store IP at all.

If abuse protection becomes necessary later:

- Store only short-lived hash: `sha256(ip + daily_salt)`.
- Rotate salt daily or weekly.
- Do not expose salt in repo, logs, or summaries.
- Add retention policy and delete old IP hashes.
- This change requires explicit user authorization before implementation if it uses secrets or production Worker settings.

### 5.3 CORS policy

Worker should:

1. For `POST /api/events`, require `Origin` to match configured allowlist.
2. For disallowed origins, return 403 with no D1 write.
3. Handle `OPTIONS` preflight explicitly.
4. Include only necessary headers:
   - `Access-Control-Allow-Origin: <matched-origin>`
   - `Access-Control-Allow-Methods: POST, OPTIONS`
   - `Access-Control-Allow-Headers: Content-Type`
   - `Vary: Origin`

### 5.4 URL redirect safety

`GET /r` must prevent open redirect abuse.

Recommended policy:

- Accept target as `u` query param containing a fully encoded URL.
- Decode once only.
- Require `https://` except localhost dev.
- Reject `javascript:`, `data:`, `file:`, protocol-relative URLs, malformed URLs, private IP hosts, and empty hosts.
- Optionally enforce host allowlist derived from known exported item URLs. For MVP, at least enforce safe scheme and parseable host.
- Return a simple error page for rejected redirects; do not reflect raw URL unsafely.

### 5.5 Input validation and logging

Worker must:

- Validate body size before JSON parse, e.g. reject > 4 KB.
- Validate JSON type is object.
- Reject unknown event_type/channel.
- Reject metadata beyond size/key limits.
- Never log secrets, raw request headers, raw IP, or full user agent.
- Log only coarse operational fields in dev: event_type, channel, briefing_id, status, duplicate.

### 5.6 Rate limiting

MVP can start without durable rate limiting, but should include cheap guardrails:

- Reject oversized requests.
- Reject invalid origins.
- Reject invalid URLs.
- Consider in-memory per-isolate soft limit only as best-effort, not as a security guarantee.

If durable rate limiting is required later, it may involve KV/Durable Object/Turnstile and should be a separate authorized phase.

---

## 6. Cloudflare Worker + D1 deployment design

### 6.1 Recommended directory shape

```text
worker/
  README.md
  package.json
  wrangler.toml.example
  schema.sql
  src/
    index.ts
    validation.ts
    events.ts
    redirects.ts
  test/
    validation.test.ts
    events.test.ts
    redirects.test.ts
```

For Phase 4 coder task, creating local scaffold files is acceptable if done without tokens and without real deploy. This architecture task itself only writes this design document.

### 6.2 wrangler.toml shape

Use an example file first, not a production secret-bearing file:

```toml
name = "newsroom-feedback"
main = "src/index.ts"
compatibility_date = "2026-05-01"

[vars]
ENVIRONMENT = "local"
ALLOWED_ORIGINS = "http://localhost:1313,http://127.0.0.1:8787,https://www.yuzhuohui.info"
PUBLIC_SITE_BASE_URL = "https://www.yuzhuohui.info/NewsBriefingsSystem/"

[[d1_databases]]
binding = "DB"
database_name = "newsroom_feedback_local_or_future"
database_id = "00000000-0000-0000-0000-000000000000"
```

Rules:

- Keep real `wrangler.toml` free of secrets.
- Prefer `wrangler.toml.example` until the user authorizes real Cloudflare setup.
- Do not commit account IDs, API tokens, secret salts, or production database IDs without authorization.

### 6.3 MVP schema.sql

Recommended MVP D1 schema:

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS feedback_events (
  id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL CHECK (event_type IN ('like', 'dislike', 'click', 'dwell', 'read')),
  channel TEXT NOT NULL CHECK (channel IN ('site', 'telegram', 'obsidian', 'manual', 'unknown')),
  anonymous_id TEXT,
  briefing_id TEXT NOT NULL,
  item_id TEXT,
  target_url TEXT,
  duration_ms INTEGER,
  idempotency_key TEXT NOT NULL UNIQUE,
  metadata_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_feedback_events_created_at
ON feedback_events (created_at);

CREATE INDEX IF NOT EXISTS idx_feedback_events_briefing_item
ON feedback_events (briefing_id, item_id);

CREATE INDEX IF NOT EXISTS idx_feedback_events_type_channel
ON feedback_events (event_type, channel);
```

Future migration to `architecture-v1.md` full schema:

- Rename or map `feedback_events` to `events`.
- Add `briefings` and `news_items` when D1 becomes content index.
- Add `monthly_insights` after Analyst export/import is implemented.

### 6.4 API endpoints

#### GET /api/health

Purpose: health check for local dev and future monitoring.

Response:

```json
{ "ok": true, "service": "newsroom-feedback", "version": "phase4-mvp" }
```

Must not include secrets, database IDs, account IDs, or environment dumps.

#### POST /api/events

Purpose: append a validated feedback event.

Request: event schema from section 4.

Responses:

Success:

```json
{ "ok": true, "event_id": "evt_...", "duplicate": false }
```

Duplicate:

```json
{ "ok": true, "event_id": null, "duplicate": true }
```

Validation error:

```json
{ "ok": false, "error": "invalid_event_type" }
```

Status codes:

- 200 for accepted or duplicate.
- 400 for invalid payload.
- 403 for invalid origin.
- 405 for unsupported method.
- 413 for oversized payload.
- 500 only for unexpected internal errors.

#### GET /r

Purpose: record click then redirect.

Recommended query params:

```text
/r?u=https%3A%2F%2Fexample.com%2Fagent-workflow&briefing_id=2026-01-01-08&item_id=2026-01-01-08-001&channel=site&anon=anon_...
```

Behavior:

1. Validate URL and event fields.
2. Record `click` event if validation passes.
3. Return `302 Location: <target_url>`.
4. If D1 write fails but URL is safe, prefer redirect with a non-blocking log rather than breaking reading experience.
5. If URL is unsafe, do not redirect.

#### GET /f

Purpose: record feedback from simple links, especially future Telegram or no-JS fallback.

Recommended query params:

```text
/f?action=like&briefing_id=2026-01-01-08&item_id=2026-01-01-08-001&channel=site
/f?action=dislike&briefing_id=2026-01-01-08&item_id=2026-01-01-08-001&channel=telegram&token=<future-random-token>
```

Behavior:

1. Accept only `action=like|dislike` for MVP.
2. Validate briefing/item/channel.
3. Record event.
4. Return minimal HTML: “已记录，谢谢。”
5. Do not expose raw query params in HTML.

### 6.5 Local dev/test method

Coder can implement and test locally without real Cloudflare resources:

```text
cd /opt/data/home/NewsBriefingsSystem/worker
npm install
npm test
npx wrangler d1 execute newsroom_feedback_local_or_future --local --file=./schema.sql
npx wrangler dev --local
curl http://127.0.0.1:8787/api/health
curl -X POST http://127.0.0.1:8787/api/events \
  -H 'Origin: http://localhost:1313' \
  -H 'Content-Type: application/json' \
  --data '{"event_type":"like","channel":"site","briefing_id":"2026-01-01-08","item_id":"2026-01-01-08-001","anonymous_id":"anon_test_12345678"}'
```

If package tooling is not yet present, coder should add it locally under `worker/` only. They must not run `wrangler deploy` or create remote D1.

---

## 7. Hugo integration design

### 7.1 Layout injection points

Current `site/layouts/_default/single.html` shape:

```go-html-template
<article>
  ...
  {{ with .Params.slots }} ... {{ end }}
  <section>
    {{ .Content }}
  </section>
</article>
```

Recommended Phase 4 integration:

1. Add page-level data attributes to `<article>`:

```go-html-template
<article
  data-feedback-page="briefing"
  data-briefing-day="{{ .Params.briefing_day }}"
  data-channel="site">
```

2. In slot summary, include `data-briefing-id` on each slot card:

```go-html-template
<div class="slot-card" data-briefing-id="{{ .briefing_id }}" data-slot="{{ .slot }}">
```

3. Add a page-level feedback widget after content:

```go-html-template
{{ if .Site.Params.feedback.enabled }}
  {{ partial "feedback-widget.html" . }}
{{ end }}
```

4. Load a small JS file only when enabled:

```go-html-template
{{ if .Site.Params.feedback.enabled }}
  <script defer src="{{ "feedback.js" | relURL }}"></script>
{{ end }}
```

The exact partial/static JS implementation is coder work. This document defines contract only.

### 7.2 Item-level data attributes

Current Markdown content contains item metadata as Markdown list lines:

```markdown
### 1｜示例：AI agent workflow 进入团队协作

- item_id: 2026-01-01-08-001
- source: Example Feed
- url: https://example.com/agent-workflow
- tags: [AI Agent, Tooling]
```

For reliable item-level widgets, coder has two options:

Option A, minimal parser in Hugo/export layer:

- Enhance Hugo export to wrap each item section in HTML or shortcode with:
  - `data-briefing-id`
  - `data-item-id`
  - `data-source`
  - `data-source-url`
- Keep Markdown archive unchanged.

Option B, leave content unchanged and provide page-level widget only in first slice:

- Page-level like/dislike and dwell are reliable.
- Link click tracking can be done by scanning links and matching URLs to `item_id` from a JSON script block generated from front matter.
- Item-level like/dislike can be deferred.

Recommendation for Phase 4 MVP: implement page-level widget first and link tracking via exported item metadata; add item-level buttons only if export parser can do it without brittle DOM assumptions.

### 7.3 Site config contract

Add Hugo params in `site/hugo.yaml` or equivalent config:

```yaml
params:
  feedback:
    enabled: false
    workerBaseUrl: ""
    widgetEnabled: false
    trackLinks: false
    dwellEnabled: false
```

Default should be false. Local dev can set workerBaseUrl to `http://127.0.0.1:8787`.

### 7.4 No-JS and Worker unavailable behavior

Hard requirements:

1. Article content renders without JS.
2. Original links remain present in HTML or are restorable by config.
3. If Worker request fails, UI shows non-blocking feedback like “暂时无法记录，但不影响阅读”.
4. Dwell reporting must use best-effort sendBeacon/fetch keepalive; no blocking unload dialogs.
5. Build must pass even if feedback config is absent.

### 7.5 Click link rewriting

Recommended design:

- When `feedback.trackLinks=false`, render original source URLs.
- When `feedback.trackLinks=true`, render links as:

```text
<workerBaseUrl>/r?u=<encoded-url>&briefing_id=<id>&item_id=<id>&channel=site
```

Important:

- Keep visible link text unchanged.
- Add `rel="noopener noreferrer"` for external links.
- If workerBaseUrl missing, do not rewrite.

---

## 8. Contract with runner / export_hugo / manifest

### 8.1 Existing stable fields to preserve

Runner manifest fields currently useful for feedback:

- `briefing_id`: e.g. `2026-01-01-08`
- `slot`: `morning|noon|evening`
- `archive_path`
- `jsonl_output`
- `markdown_output`
- `publication.hugo_export.output_path`

Hugo front matter fields currently useful:

- `briefing_day`
- `timezone`
- `item_count`
- `item_ids`
- `sources`
- `tags`
- `slots[].slot`
- `slots[].label`
- `slots[].briefing_id`
- `slots[].item_count`

Markdown item fields currently useful:

- `<!-- briefing_id: ... -->`
- `- item_id: ...`
- `- source: ...`
- `- url: ...`
- `- tags: [...]`

### 8.2 Minimal additional contract requested from coder

Coder should add only what is needed for reliable feedback:

1. Hugo/site params for feedback enablement and endpoint.
2. Stable `data-briefing-id` where slot or page context is known.
3. Stable mapping from item_id to source_url for link tracking.
4. Optional generated JSON block in page HTML:

```html
<script type="application/json" id="newsroom-feedback-items">
[
  {
    "briefing_id": "2026-01-01-08",
    "item_id": "2026-01-01-08-001",
    "source": "Example Feed",
    "url": "https://example.com/agent-workflow",
    "tags": ["AI Agent", "Tooling"]
  }
]
</script>
```

5. Manifest may include future optional `feedback` section, but must not be required for existing Phase 3 tests:

```json
{
  "feedback": {
    "enabled": false,
    "worker_base_url": "",
    "track_links": false
  }
}
```

### 8.3 Changes explicitly left to coder

Coder should implement after this architecture task:

- Worker local scaffold under `worker/`.
- `schema.sql` and Worker validation tests.
- Hugo partial/static JS/widget with config gating.
- Export/Hugo metadata additions if needed for item link mapping.
- Tests proving payload validation and no-JS fallback assumptions.
- Documentation update for local development and authorization boundary.

Coder should not implement without user authorization:

- Real D1 creation.
- Real Worker deploy.
- CF token/secrets setup.
- Production cron edits.
- Real Telegram send or Telegram webhook/callback integration.

---

## 9. Telegram tracking link design only

### 9.1 Future Telegram click links

Future Telegram message rendering may replace item URL with:

```text
https://<feedback-worker>/r?channel=telegram&briefing_id=2026-01-01-08&item_id=2026-01-01-08-001&u=https%3A%2F%2Fexample.com%2Fagent-workflow
```

Rules:

- Do not include Telegram user id.
- Optional `token` must be random and non-identifying.
- Token should not be reversible to Telegram identity.
- If no token exists, anonymous_id can be null.

### 9.2 Future Telegram feedback links

Future like/dislike links:

```text
https://<feedback-worker>/f?action=like&channel=telegram&briefing_id=2026-01-01-08&item_id=2026-01-01-08-001
https://<feedback-worker>/f?action=dislike&channel=telegram&briefing_id=2026-01-01-08&item_id=2026-01-01-08-001
```

For Phase 4 MVP:

- Existing `TelegramPublisher` remains safe-local/dry-run unless explicitly configured with sender and authorization.
- No actual Telegram message should be sent.
- No production Telegram cron should be modified.

---

## 10. Rollback plan

Rollback must be possible by config or reverting only Phase 4 files.

### 10.1 Disable widget

Set:

```yaml
params:
  feedback:
    enabled: false
    widgetEnabled: false
    trackLinks: false
    dwellEnabled: false
```

Expected result:

- Hugo pages render content normally.
- Feedback JS not loaded.
- Widget not shown.
- No event POSTs.

### 10.2 Restore direct links

Set `trackLinks=false` or remove `workerBaseUrl`.

Expected result:

- Original article links are rendered directly.
- `/r` endpoint is not needed for reading.
- Existing Markdown archive and Hugo content remain valid.

### 10.3 Worker unavailable

If Worker/D1 is down:

- Site reading remains unaffected.
- Clicks should still work if direct links are used, or `/r` should degrade by redirecting safe URLs even if event insert fails.
- like/dislike UI may show a non-blocking failure.
- Dwell event can be dropped.

### 10.4 Existing pipeline unaffected

The following must continue to work regardless of feedback state:

- Briefing generation.
- Markdown archive update.
- Telegram dry-run preview/status.
- Hugo export/build.
- GitHub Pages deployment.
- Existing Phase 3 tests.

---

## 11. Test strategy for coder

### 11.1 Worker validation tests

Cover:

- Valid `like`, `dislike`, `click`, `dwell` payloads.
- Invalid event_type rejected.
- Invalid channel rejected.
- Missing required fields rejected by event type.
- Oversized metadata rejected.
- Unsafe redirect URLs rejected.
- Duplicate idempotency key returns duplicate success.
- CORS disallowed origin returns 403.

### 11.2 Hugo/static tests

Cover:

- Hugo build succeeds with feedback config absent.
- Hugo build succeeds with feedback disabled.
- Widget appears only when enabled.
- `data-briefing-id` appears for known slots.
- Link rewriting occurs only when `trackLinks=true` and workerBaseUrl is set.
- Original content remains readable with JS disabled.

### 11.3 Existing Python tests

Run existing tests after any Python/export changes:

```text
/opt/hermes/.venv/bin/python -m pytest -q tests
```

If coder only changes Worker Node/TS files and Hugo templates, still run relevant Hugo/worker tests plus Python tests if export code changes.

### 11.4 Manual local smoke tests

- `GET /api/health` returns ok.
- `POST /api/events` stores event in local D1.
- `/r` redirects to safe URL and rejects unsafe URL.
- `/f?action=like...` returns thank-you HTML.
- Local Hugo page remains readable with browser JS disabled.

---

## 12. Authorization boundaries

The next worker must block and wait for explicit user authorization before any of these actions:

1. Creating real Cloudflare D1 database.
2. Creating real Cloudflare Worker.
3. Running `wrangler deploy` against production.
4. Writing Cloudflare API token, account id, database id, secret salt, or any secret into repo/config.
5. Modifying production news cron.
6. Sending real Telegram messages.
7. Creating Telegram webhook, inline callback, or bot integration that touches real users.
8. Storing IP hashes or introducing any new persistent identifier beyond anonymous random localStorage ID.
9. Publishing monthly analysis or raw feedback publicly.

Allowed without additional authorization in coder task:

- Local-only Worker scaffold.
- Example wrangler config with placeholder IDs.
- Local D1 schema and tests.
- Hugo templates gated by disabled-by-default config.
- Mock/dry-run endpoint and local documentation.

---

## 13. Implementation sequence recommendation

Milestone 1: Contracts and config

- Add disabled-by-default feedback config.
- Add schema and validation contract documentation.
- Ensure existing tests still pass.

Milestone 2: Local Worker MVP

- Implement `/api/health`, `/api/events`, `/r`, `/f` locally.
- Add D1 local schema.
- Add validation and redirect tests.

Milestone 3: Hugo integration behind feature flags

- Add page/slot data attributes.
- Add feedback widget partial and JS only when enabled.
- Add link rewrite only when enabled and workerBaseUrl exists.
- Preserve no-JS reading.

Milestone 4: Dry-run Telegram design

- Optionally render future tracking links in a local preview only.
- Do not send Telegram.

Milestone 5: Documentation and handoff

- Document local dev steps.
- Document authorization checklist.
- Document rollback switches.

---

## 14. Coder acceptance checklist

A coder implementation based on this architecture is acceptable when:

- No production cron changed.
- No `/opt/data/scripts` legacy production script changed.
- No real Telegram send occurred.
- No real Cloudflare resource was created.
- No token/secret appears in repo, logs, tests, summaries, or fixtures.
- Worker local tests cover validation, CORS, idempotency, redirects, and feedback links.
- Hugo build/static tests show feedback is disabled by default and content remains readable.
- Existing Phase 3 Python tests still pass if Python/export code was touched.
- Rollback is a config disable or small revert, not a data migration.

---

## 15. Summary of adjustments to architecture-v1.md

Use `architecture-v1.md` section 9-10 as directionally correct, with these Phase 4 MVP adjustments:

1. Narrow event types to `like/dislike/click/dwell` plus optional `read`.
2. Start with `feedback_events` single table instead of full content/insight schema.
3. Treat `briefings/news_items/monthly_insights/editorial_preferences` as later migrations.
4. Do not store `user_agent_hash` or `ip_hash` in MVP.
5. Make redirect safety and CORS explicit hard requirements.
6. Default all feedback features off until local validation is complete and user authorizes production setup.
