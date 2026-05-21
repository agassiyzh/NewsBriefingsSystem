# Phase 1 手动运行与回滚说明

## 目标
在不触碰现有 cron 与 Telegram 推送链路的前提下，为后续 Editor / Reporter / Analyst / Publisher 拆分建立结构化采集底座。

## 一条命令的 dry-run
```bash
cd /opt/data/home/NewsBriefingsSystem
uv venv --seed .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python scripts/run_briefing.py --slot morning --dry-run
```

该命令会：
1. 读取 `config/newsroom.yaml`、`config/sources.yaml`、`config/interests.yaml`。
2. 依据 `newsroom.yaml` 中的 `system.timezone`（当前默认 `Asia/Shanghai`）生成 `briefing_id=YYYY-MM-DD-HH`。
3. 调用 `scripts/collect_candidates.py` 对应的采集逻辑。
4. 写出：
   - `data/candidates/<briefing_id>.jsonl`
   - `data/contexts/<briefing_id>.md`
   - `data/runs/<briefing_id>.json`
   - `logs/<YYYY-MM-DD>.log`
5. 跳过 Telegram / Hugo / 日归档写入，仅在 manifest 中记录 `publication.markdown_archive=dry_run`。

## 手动写回日归档（安全模式）
```bash
cd /opt/data/home/NewsBriefingsSystem
python scripts/run_briefing.py --slot noon
```

非 dry-run 时会：
- 更新 `/opt/data/home/NewsBriefings/YYYY-MM-DD.md` 对应 slot。
- 仅替换目标 slot 段落，保留其他 slot 与 `## 今日沉淀`。
- 仍然跳过 Telegram 与 Hugo。

归档写回格式遵循架构文档中的 slot 结构，并写入 `<!-- briefing_id: YYYY-MM-DD-HH -->` 注释以及每条候选的 `item_id/source/url/tags` 元信息，便于后续 Publisher/Hugo 阶段接管。

## 从系统目录外调用采集脚本
可直接通过绝对路径运行，默认配置仍会解析到系统目录：
```bash
python /opt/data/home/NewsBriefingsSystem/scripts/collect_candidates.py \
  --briefing-id 2026-05-19-08 \
  --output-jsonl /tmp/candidates.jsonl \
  --output-markdown /tmp/context.md
```

兼容参数：
- `--jsonl-output` 与 `--output-jsonl` 等价
- `--markdown-output` 与 `--output-markdown` 等价

## 结构化字段
JSONL 候选至少包含：
- `briefing_id`: `YYYY-MM-DD-HH`
- `item_id`: `YYYY-MM-DD-HH-NNN`
- `source`
- `title`
- `url`
- `published`
- `snippet`
- `tags`
- `keywords`
- `collected_at`
- `status` / `error`（失败源时）

## 兼容性说明
- `scripts/collect_candidates.py` 默认仍把 Markdown context 打印到 stdout，方便旧 prompt/cron 继续消费相同形态的上下文。
- 失败源会变成 error candidate，并写入 manifest / log，而不会中断其它源。
- 当前版本已支持“采集 + 产物落盘 + manifest + 手动 slot 归档写回”，但仍不接管 Telegram 或 Hugo 发布。

## 回滚方案
如果要完全回到旧链路：
1. 不运行 `/opt/data/home/NewsBriefingsSystem/scripts/run_briefing.py`。
2. 继续使用：
   - `/opt/data/scripts/collect_news_context.py`
   - `/opt/data/scripts/run_news_briefing.sh`
   - `/opt/data/profiles/researcher/scripts/run_news_briefing.sh`
3. 无需修改 cron，因为本 Phase 1 未替换或注入 cron job。

## 下一阶段建议
- 将 Publisher/Telegram 封装为显式适配器并做失败重试。
- 为 Hugo export、Monthly analysis、Worker schema 增加测试与 schema 文档。
- 根据 Editor 最终稿格式补全“候选上下文 -> 成稿正文 -> 归档发布”之间的接口契约。
- 月度审核请遵循 `docs/monthly-editorial-review-runbook.md`：Analyst 先生成 `pending_review` 建议，Editor profile 审核稳定偏好后写入自己的 Hermes/Honcho memory；仓库内 apply adapter 仅可作为 deprecated 的本地迁移/debug 工具，不属于生产路径。
