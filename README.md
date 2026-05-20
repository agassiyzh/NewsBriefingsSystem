# Personal Newsroom System（Phase 3 GitHub Pages 发布）

本目录保留现有新闻简报闭环不变，并在前两阶段基础上补齐最小可工作的 GitHub Pages 静态发布链路：保留 Phase 1/2 的结构化采集、Publisher 抽象、Telegram dry-run 与 Hugo 导出，同时增加最小 Hugo 模板、公开安全示例页面、GitHub Actions Pages 部署工作流与 git 仓库初始化准备。

当前项目提供：
- `config/`：无密钥的基础配置、新闻源与兴趣定义，以及 Publisher 相关路径配置。
- `prompts/`：Editor / Reporter / Analyst / Publisher 的初版角色提示词。
- `scripts/collect_candidates.py`：兼容 Markdown stdout 的结构化候选采集脚本，可同时写 JSONL 与 Markdown 文件，支持 `--jsonl-output/--markdown-output` 与 `--output-jsonl/--output-markdown` 两组参数。
- `scripts/run_briefing.py`：手动 runner，负责加载配置、执行采集、调用 Publisher adapters，并写出带 publication 状态的 manifest。
- `scripts/publish_telegram.py`：基于 manifest 回写 Telegram publication 状态；若 manifest 为非 dry-run，会生成本地预览文件，否则只记录状态且不会真实发送。
- `scripts/export_hugo.py`：把日归档导出为 Hugo 内容文件；若 manifest 为 dry-run，只回写 publication 状态，不落盘 Hugo 文件。
- `scripts/ensure_sample_briefing.py`：生成不含隐私的公开安全示例归档与 Hugo 导出文件，供 GitHub Pages 首次部署验证。
- `newsroom/`：Phase 2/3 Python 模块，实现 ID 规范、采集、配置解析、时区一致性、Publisher 合同、归档写回、Telegram 预览、Hugo 导出与示例站点 bootstrap。
- `site/`：Hugo 导出目录，包含最小 `hugo.toml`、layouts、feedback widget 静态资源与示例数据。
- `worker/`：Phase 4 Feedback MVP 的本地安全 scaffold，包含 mock Worker、schema、示例 wrangler 配置与 Node 测试。
- `.github/workflows/pages.yml`：GitHub Actions Pages 工作流，在 CI 中运行测试、安装 Hugo、构建并部署 `site/public`。

手动运行：
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
   - 若 manifest 的 `dry_run=false`，会落盘 Hugo Markdown 文件。
7. 查看输出：
   - `data/candidates/YYYY-MM-DD-HH.jsonl`
   - `data/contexts/YYYY-MM-DD-HH.md`
   - `data/runs/YYYY-MM-DD-HH.json`
   - `data/telegram/YYYY-MM-DD-HH.txt`（手动 Telegram dry-run 或非 dry-run runner）
   - `site/content/briefings/YYYY/YYYY-MM-DD.md`（非 dry-run runner 或手动 Hugo 导出）
   - `logs/YYYY-MM-DD.log`
   - `/opt/data/home/NewsBriefings/YYYY-MM-DD.md`（仅非 dry-run）

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
- 本目录不会修改现有 cron，也不会真实发送 Telegram。
- 如需停用新路径，只需停止手动运行 `scripts/run_briefing.py` / `scripts/collect_candidates.py` / `scripts/publish_telegram.py` / `scripts/export_hugo.py`。

进一步说明见 `docs/phase1-runbook.md` 与 `docs/phase2-runbook.md`。
