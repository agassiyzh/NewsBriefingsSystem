# Personal Newsroom System（Phase 3 GitHub Pages 发布）

本目录保留现有新闻简报闭环不变，并在前两阶段基础上补齐最小可工作的 GitHub Pages 静态发布链路：保留 Phase 1/2 的结构化采集、Publisher 抽象、Telegram dry-run 与 Hugo 导出，同时增加最小 Hugo 模板、公开安全示例页面、GitHub Actions Pages 部署工作流与 git 仓库初始化准备。

当前项目提供：
- `config/`：无密钥的基础配置、新闻源与兴趣定义，以及 Publisher 相关路径配置。
- `prompts/`：Editor / Reporter / Analyst / Publisher 的初版角色提示词。
- `scripts/collect_candidates.py`：兼容 Markdown stdout 的结构化候选采集脚本，可同时写 JSONL 与 Markdown 文件，支持 `--jsonl-output/--markdown-output` 与 `--output-jsonl/--output-markdown` 两组参数。
- `scripts/monthly_analysis.py`：月度兴趣分析 dry-run 脚本，读取事件/归档输入并输出 `data/monthly_insights/YYYY-MM.json` 与 `docs/monthly-insights/YYYY-MM.md` 草案。
- `scripts/apply_editorial_preferences.py`：deprecated/non-production/local migration/debug tool；可读取旧 review 文件并验证 payload shape，但不属于生产 Honcho 写入路径，生产长期记忆由 Editor-in-chief profile 自己写入。
- `scripts/run_briefing.py`：手动 runner，负责加载配置、执行采集、调用 Publisher adapters，并写出带 publication 状态的 manifest。
- `scripts/run_shadow_briefing.py`：shadow runner，复用 newsroom runner 但把 archive/candidates/contexts/runs/logs/telegram/hugo/item catalog 全部导向独立 shadow 目录。
- `scripts/compare_shadow_run.py`：对比旧生产归档与 shadow manifest，输出 item/topic/tag/source/duplicate/missing item_id/failed sources 报告。
- `scripts/publish_telegram.py`：基于 manifest 回写 Telegram publication 状态；若 manifest 为非 dry-run，会生成本地预览文件，否则只记录状态且不会真实发送。
- `scripts/export_hugo.py`：把日归档导出为 Hugo 内容文件；若 manifest 为 dry-run，只回写 publication 状态，不落盘 Hugo 文件。
- `scripts/ensure_sample_briefing.py`：生成不含隐私的公开安全示例归档、Hugo 导出文件与 `data/item_catalog/YYYY/YYYY-MM-DD.jsonl`，供 GitHub Pages 首次部署验证与月度分析 join。
- `newsroom/`：Phase 2/3 Python 模块，实现 ID 规范、采集、配置解析、时区一致性、Publisher 合同、归档写回、Telegram 预览、Hugo 导出与示例站点 bootstrap。
- `site/`：Hugo 导出目录，包含最小 `hugo.toml`、layouts、feedback widget 静态资源与示例数据。
- `worker/`：Phase 4 Feedback MVP 的本地安全 scaffold，包含 mock Worker、schema、示例 wrangler 配置与 Node 测试。
- `.github/workflows/pages.yml`：GitHub Actions Pages 工作流，在 CI 中运行测试、安装 Hugo、构建并部署 `site/public`。

月度兴趣分析 → Editor 审核 → Editor-owned memory 最小链路：
1. 先运行 `python scripts/monthly_analysis.py --dry-run --month YYYY-MM` 生成 `data/monthly_insights/YYYY-MM.json` 与 `docs/monthly-insights/YYYY-MM.md`。
2. 生产输入支持：`--events` 读取 CSV/JSON/JSONL/NDJSON 文件或目录；`--catalog` 读取 JSON/JSONL/NDJSON、run manifest JSON、Markdown/Hugo catalog 文件或目录。
3. Analyst 输出 Editor recommendation brief：事实、解释、建议、置信度和聚合证据摘要；默认保持 `pending_review`。
4. Editor-in-chief profile 是 Hermes/Honcho memory owner，负责审核稳定偏好并写入自己的 memory。
5. Reporter 保持 stateless，只接收 Editor brief；Publisher/Coder 不写长期编辑记忆。
6. 新闻 repo 不再把 apply-to-Honcho endpoint/token/apply flag 作为生产路径；`scripts/apply_editorial_preferences.py` 仅可作为 deprecated 本地迁移/debug 工具。
7. Honcho/Hermes memory 只允许写入稳定、跨月、声明性的 editorial preferences，不允许写 raw events、单条新闻、单月热点或 PII。
8. 若误写涉及 PII/敏感数据，删除只用于人工应急清理；正常策略调整应通过后续审核结果覆盖，不走自动删除。

更详细的审核/回滚说明见 `docs/monthly-editorial-review-runbook.md`。

手动运行：
0. 本地 Python 环境（推荐）：
   `cd /opt/data/home/NewsBriefingsSystem && uv venv --seed .venv && uv pip install --python .venv/bin/python -r requirements.txt`
   - 本仓库当前以 `requirements.txt` 声明 Python 依赖；若当前主机已提供 `/opt/hermes/.venv/bin/python`，可直接用它执行命令。
   - 若需要独立且可安装依赖的本地环境，请优先使用 `uv venv --seed .venv`，因为系统 `python3` 与 `/opt/hermes/.venv/bin/python` 不保证自带 `pip`。
1. 仅采集候选（兼容旧 prompt/cron 读取 Markdown stdout）：
   `python scripts/collect_candidates.py --slot morning`
2. 从系统目录外也可直接执行，并显式指定输出文件：
   `python /opt/data/home/NewsBriefingsSystem/scripts/collect_candidates.py --briefing-id 2026-05-19-08 --output-jsonl /tmp/candidates.jsonl --output-markdown /tmp/context.md`
3. 采集并保存 manifest（dry-run，不写日归档，也不生成 Telegram/Hugo 文件）：
   `python scripts/run_briefing.py --slot noon --dry-run`
4. 手动执行本地发布适配器（仍不真实推 Telegram）：
   `python scripts/run_briefing.py --slot noon`
5. 基于已有 manifest 单独执行 Telegram 发布适配器：
   `python scripts/publish_telegram.py --manifest data/runs/2026-05-19-13.json`
   - 若 manifest 的 `dry_run=true`，只回写 `publication.telegram`，不会生成预览文件。
   - 若 manifest 的 `dry_run=false`，会生成本地 Telegram 预览文件，但仍不会真实发送。
6. 基于已有 manifest 单独执行 Hugo 导出：
   `python scripts/export_hugo.py --manifest data/runs/2026-05-19-13.json`
   - 若 manifest 的 `dry_run=true`，只回写 `publication.hugo_export`，不会生成 Hugo 文件。
   - 若 manifest 的 `dry_run=false`，会落盘 Hugo Markdown 文件，并更新 `data/item_catalog/YYYY/YYYY-MM-DD.jsonl` 供月度分析 join。
7. 查看输出：
   - `data/candidates/YYYY-MM-DD-HH.jsonl`
   - `data/contexts/YYYY-MM-DD-HH.md`
   - `data/runs/YYYY-MM-DD-HH.json`
   - `data/item_catalog/YYYY/YYYY-MM-DD.jsonl`（非 dry-run Hugo 导出或 sample bootstrap 生成的 item catalog）
   - `data/telegram/YYYY-MM-DD-HH.txt`（手动 Telegram dry-run 或非 dry-run runner）
   - `site/content/briefings/YYYY/YYYY-MM-DD.md`（非 dry-run runner 或手动 Hugo 导出）
   - `logs/YYYY-MM-DD.log`
   - `/opt/data/home/NewsBriefings/YYYY-MM-DD.md`（仅非 dry-run）
8. Shadow/new-runner 预检（隔离目录，不改旧生产归档）：
   - `python scripts/run_shadow_briefing.py --slot morning --date 2026-05-20 --shadow-dir data/shadow`
   - `python scripts/compare_shadow_run.py --legacy-archive /opt/data/home/NewsBriefings/2026-05-20.md --shadow-manifest data/shadow/data/runs/2026-05-20-08.json`
   - shadow 产物默认写入 `data/shadow/archive`、`data/shadow/data/*`、`data/shadow/site/content/briefings`、`data/shadow/logs`。
   - compare 报告默认写入 `data/shadow/reports/*-compare.md` 与 `data/shadow/reports/*-compare.json`。
   - 生产 cutover/回滚步骤见 `docs/cron-migration-runbook.md`；用户已授权后续 ops 修改真实 Cloudflare/Pages deploy 与生产 cron，新 runner 通过预检后可直接 cutover，但旧 job 只 pause 不 delete 并保留 rollback 证据。

Phase 4 Feedback MVP（本地安全默认关闭）：
1. Hugo 前端开关默认位于 `site/hugo.toml -> params.feedback`：
   - `enabled = false`
   - `workerBaseUrl = ""`
   - `widgetEnabled = false`
   - `trackLinks = false`
   - `dwellEnabled = false`
2. `config/newsroom.yaml -> feedback` 保留 Python / contract 默认值，用于导出与后续 worker 集成的安全基线；当前 Hugo 页面注入是否开启，以 `site/hugo.toml` 为准。
3. 只有同时提供启用配置与本地 mock worker 地址时，Hugo 页面才会注入 feedback widget / tracking 脚本；缺失配置时 `hugo` build 仍可通过。
4. 本地验证前端与 mock API：
   - `cd worker && npm test`
   - `node --test worker/test/frontend-feedback.test.js worker/test/feedback-worker.test.js`
5. 本地 Hugo 验证：
   - `npx -y hugo-bin --source site --destination /tmp/newsroom-public`
6. Worker 已部署到 Cloudflare 后，可在 GitHub Pages workflow 中通过 repository variable 启用生产 feedback 注入：
   - `NEWSROOM_FEEDBACK_WORKER_BASE_URL=https://newsroom-feedback.agassi212451.workers.dev`
   - workflow 会在 Hugo build 前运行 `python scripts/configure_hugo_feedback.py`，只修改 CI 工作区里的 `site/hugo.toml`。
   - repo 默认配置继续保持 disabled/local-safe，避免 fork 或本地构建误上报。
7. Worker scaffold / D1 说明：
   - `worker/src/index.js` 提供 `GET /api/health`、`POST /api/events`、`GET /r`、`GET /f`
   - `worker/schema.sql` 仅提供本地 schema 草案
   - `worker/wrangler.toml.example` 仅作示例，不包含任何 secrets
8. 回滚方式：保持 `site/hugo.toml` 中 `params.feedback.enabled=false` 或清空 `workerBaseUrl` 即可关闭前端注入；不会影响 Markdown 归档、Telegram dry-run 或 Hugo 导出。

回滚到旧脚本：
- 继续使用 `/opt/data/scripts/collect_news_context.py` 与 `/opt/data/scripts/run_news_briefing.sh`。
- 当前文档/本地手动命令不会修改现有 cron，也不会真实发送 Telegram；后续 ops 已获授权时可按 runbook 修改生产 cron 和 deploy。
- 如需停用新路径，只需停止手动运行 `scripts/run_briefing.py` / `scripts/collect_candidates.py` / `scripts/publish_telegram.py` / `scripts/export_hugo.py`。

进一步说明见 `docs/phase1-runbook.md` 与 `docs/phase2-runbook.md`。
