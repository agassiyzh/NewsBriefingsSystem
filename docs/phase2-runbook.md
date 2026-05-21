# Phase 2 Publisher 手动运行与回滚说明

## 目标
在不触碰现有 cron、旧脚本和真实 Telegram 推送链路的前提下，引入显式 Publisher adapters、Telegram dry-run 与 Hugo 本地导出能力，并把每个发布目标的状态写入 run manifest。

## 发布目标状态契约
每个 publish target 在 manifest 的 `publication` 字段下都有独立对象：

- `status`: `dry_run|updated|sent|failed|skipped`
- `output_path`: 产物路径（若有）；在 `dry_run=true` 时表示预期输出位置，不代表文件已实际生成
- `error`: 错误信息（若有）
- `dry_run`: 是否 dry-run
- `skipped`: 是否跳过
- `retryable`: 是否适合重试
- `details`: 目标级附加元数据

当前支持目标：
- `markdown_archive`
- `telegram`
- `hugo_export`

## 一条命令的 Phase 2 dry-run
```bash
cd /opt/data/home/NewsBriefingsSystem
uv venv --seed .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python scripts/run_briefing.py --slot morning --dry-run
```

该命令会：
1. 读取 `config/newsroom.yaml`、`config/sources.yaml`、`config/interests.yaml`。
2. 依据 `newsroom.yaml` 中的 `system.timezone` 生成 `briefing_id=YYYY-MM-DD-HH`。
3. 执行结构化采集，写出 JSONL、Markdown context、manifest、log。
4. 在 manifest 中记录：
   - `publication.markdown_archive.status=dry_run`
   - `publication.telegram.status=dry_run`
   - `publication.hugo_export.status=dry_run`
5. 不写日归档、不生成 Telegram 预览文件、不生成 Hugo 文件。

## 手动触发本地发布适配器
```bash
cd /opt/data/home/NewsBriefingsSystem
python scripts/run_briefing.py --slot noon
```

非 dry-run 时会：
- 更新 `/opt/data/home/NewsBriefings/YYYY-MM-DD.md` 对应 slot。
- 生成 Telegram 预览文件：`data/telegram/<briefing_id>.txt`。
- 生成 Hugo 内容文件：`site/content/briefings/YYYY/YYYY-MM-DD.md`。
- 在 manifest 中分别写入三个 target 的结构化状态。

说明：
- Telegram 适配器当前固定为 safe-local dry-run，只格式化并落盘预览文件，不会真实发送。
- Hugo 导出从当日日归档读取内容，生成带 YAML front matter 的 Hugo Markdown。

## 基于 manifest 的单独命令

### Telegram dry-run 预览
```bash
cd /opt/data/home/NewsBriefingsSystem
python scripts/publish_telegram.py --manifest data/runs/2026-05-19-13.json
```

输出：
- stdout 打印 `manifest=...`、`status=dry_run`、`preview=...`
- 回写 manifest 的 `publication.telegram`
- 若 manifest 的 `dry_run=true`，不生成 `data/telegram/2026-05-19-13.txt`，仅记录预期路径
- 若 manifest 的 `dry_run=false`，生成 `data/telegram/2026-05-19-13.txt`

### Hugo 导出
```bash
cd /opt/data/home/NewsBriefingsSystem
python scripts/export_hugo.py --manifest data/runs/2026-05-19-13.json
```

输出：
- stdout 打印 `output=...` 与 `item_count=...`
- 若 manifest 的 `dry_run=true`，只回写 `publication.hugo_export`，默认不写文件
- 若 manifest 的 `dry_run=false`，默认写到 `site/content/briefings/2026/2026-05-19.md`

也可直接从日归档导出：
```bash
python scripts/export_hugo.py \
  --archive /opt/data/home/NewsBriefings/2026-05-19.md \
  --output /tmp/2026-05-19.md
```

## Hugo 输出结构
导出文件默认包含 YAML front matter，字段包括：
- `title`
- `date`
- `briefing_day`
- `timezone`
- `item_count`
- `item_ids`
- `sources`
- `tags`
- `slots`
- `draft`

正文继续保留原始日归档结构：早/午/晚 slot 与 `## 今日沉淀`。

## Telegram 输出结构
预览文件默认格式：
- 标题：`新闻雷达｜YYYY-MM-DD HH:MM 版次`
- 每条候选包含：标题、极简摘要、标签（若有）、链接
- 末尾提示当前仅生成 dry-run 预览

## 验证命令
```bash
cd /opt/data/home/NewsBriefingsSystem
/opt/hermes/.venv/bin/python -m pytest -q tests
python scripts/run_briefing.py --slot noon --dry-run
python scripts/run_briefing.py --slot noon --briefing-id 2099-01-02-13
python scripts/publish_telegram.py --manifest data/runs/2099-01-02-13.json
python scripts/export_hugo.py --manifest data/runs/2099-01-02-13.json
```

## 回滚方案
如果要完全回到旧链路：
1. 不运行 `/opt/data/home/NewsBriefingsSystem/scripts/run_briefing.py`。
2. 不运行 `scripts/publish_telegram.py` 与 `scripts/export_hugo.py`。
3. 继续使用：
   - `/opt/data/scripts/collect_news_context.py`
   - `/opt/data/scripts/run_news_briefing.sh`
   - `/opt/data/profiles/researcher/scripts/run_news_briefing.sh`
4. 无需修改 cron，因为本阶段未替换或注入 cron job。

## 已知边界
- 当前 runner 的 Telegram 仍是 dry-run 预览，不会真实发送。
- Hugo 导出默认基于当日日归档，不会创建 GitHub repo 或执行 push。
- 真实 Telegram Bot API、GitHub Pages deploy、Cloudflare/D1 反馈链路由后续 ops/coder 在授权范围内接入；当前 runbook 不执行 deploy。
- 月度 editorial preference recommendations 不在 `run_briefing.py`/Publisher 自动链路内；必须走 `docs/monthly-editorial-review-runbook.md` 中的 Analyst -> Editor 审核流程，稳定偏好由 Editor profile 写入自己的 Hermes/Honcho memory。仓库内 apply adapter 仅可作为 deprecated 本地迁移/debug 工具，不是生产写入路径。
