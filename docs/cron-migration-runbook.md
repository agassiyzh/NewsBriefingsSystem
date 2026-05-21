# Shadow runner / cron migration runbook

目标：
- 记录 shadow/new-runner 的验证方法、生产 cutover 顺序和 rollback 证据要求。
- 用户已授权后续 ops 对真实 Cloudflare/Pages deploy 与生产 cron 做修改；本 runbook 不在当前文档任务内执行任何 deploy 或 cron 变更。
- 新 runner 准备好并通过预检后，可以直接 cutover 替换旧生产 cron；不再要求等待 2-3 天 shadow 多周期。
- 必须保留旧 job 的 pause/rollback 证据，不删除旧 cron/job，也不删除旧脚本和 shadow/compare 产物。

## 1. 前提

推荐从仓库根目录执行，并优先使用已经可直接运行 pytest/PyYAML 的 `/opt/hermes/.venv/bin/python`。若需要独立且可安装依赖的本地环境，请改用 `uv` 创建虚拟环境，而不是依赖当前主机上缺失的 `pip` 模块：

```bash
cd /opt/data/home/NewsBriefingsSystem
uv venv --seed .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

约束：
- 当前文档任务不改旧生产 cron、不执行 deploy、不真实发送 Telegram。
- 后续 ops 已获授权可修改真实生产 cron、Cloudflare Worker/D1 与 Pages 相关配置。
- 旧生产 cron/job 只能 pause，不能 delete；必须记录 job id、原 schedule、旧命令、pause 时间、操作者和恢复方式。
- 不删除旧脚本：`/opt/data/scripts/collect_news_context.py`、`/opt/data/scripts/run_news_briefing.sh`。
- shadow 目录建议固定为：`/opt/data/home/NewsBriefingsSystem/data/shadow`，用于预检、compare 和事故排查证据。

## 2. 手动 shadow run

默认 morning 示例：

```bash
cd /opt/data/home/NewsBriefingsSystem
/opt/hermes/.venv/bin/python scripts/run_shadow_briefing.py \
  --slot morning \
  --date 2026-05-20 \
  --shadow-dir /opt/data/home/NewsBriefingsSystem/data/shadow
```

若要显式指定 briefing_id：

```bash
/opt/hermes/.venv/bin/python scripts/run_shadow_briefing.py \
  --slot noon \
  --briefing-id 2026-05-20-13 \
  --shadow-dir /opt/data/home/NewsBriefingsSystem/data/shadow
```

若只想验证采集与 manifest，不生成 shadow archive / telegram preview / hugo 文件：

```bash
/opt/hermes/.venv/bin/python scripts/run_shadow_briefing.py \
  --slot evening \
  --date 2026-05-20 \
  --shadow-dir /opt/data/home/NewsBriefingsSystem/data/shadow \
  --dry-run
```

成功后重点检查：
- `data/shadow/archive/YYYY-MM-DD.md`
- `data/shadow/data/candidates/YYYY-MM-DD-HH.jsonl`
- `data/shadow/data/contexts/YYYY-MM-DD-HH.md`
- `data/shadow/data/runs/YYYY-MM-DD-HH.json`
- `data/shadow/data/telegram/YYYY-MM-DD-HH.txt`
- `data/shadow/site/content/briefings/YYYY/YYYY-MM-DD.md`
- `data/shadow/logs/YYYY-MM-DD.log`

验收关键点：
- `/opt/data/home/NewsBriefings/YYYY-MM-DD.md` 没有被 shadow 命令改写。
- `manifest.archive_path` 指向 shadow 目录，而不是旧生产归档目录。
- Telegram/Hugo 产物都落在 shadow 目录下。

## 3. 手动 compare

用同一天、同 slot 的旧生产归档和 shadow manifest 做比较：

```bash
cd /opt/data/home/NewsBriefingsSystem
/opt/hermes/.venv/bin/python scripts/compare_shadow_run.py \
  --legacy-archive /opt/data/home/NewsBriefings/2026-05-20.md \
  --shadow-manifest /opt/data/home/NewsBriefingsSystem/data/shadow/data/runs/2026-05-20-08.json
```

默认输出到：
- `data/shadow/reports/YYYY-MM-DD-HH-compare.md`
- `data/shadow/reports/YYYY-MM-DD-HH-compare.json`

报告至少覆盖：
- item 总数
- topic 分布
- tag 分布
- source 分布
- duplicate rate
- missing item_id
- failed sources

建议在预检和 cutover 首日保存每个 shadow/new-runner slot 的 compare 报告，方便一次性决策和后续回滚排查。

## 4. Cutover 前预检标准

不再强制等待 2-3 天 shadow 多周期。新 runner 准备好后，至少完成以下预检即可进入生产 cutover：

1. 对 morning/noon/evening 各执行一次手动或 shadow run，命令能独立运行成功。
2. shadow 产物只写入 shadow 目录，没有误改 `/opt/data/home/NewsBriefings`。
3. 至少保存一组与旧生产归档的 compare 报告，并确认以下指标可解释：
   - item count 差异在预期范围内
   - topic/tag/source 分布没有明显异常偏斜
   - duplicate rate 不高于旧链路，或高出的原因已明确
   - missing item_id 没有系统性恶化
   - failed sources 可归因到源站波动、限流或配置问题
4. shadow 产出的 Markdown、Telegram 预览、Hugo 内容都完成 spot check。
5. 全量 Python 测试保持通过。
6. 已准备 rollback 记录：旧 job id、旧 schedule、旧命令、resume 方法、新 job id/命令、pause 时间记录位置。

若预检中出现无法解释的大偏差，先修 compare 或 runner，再 cutover。

## 5. 建议的 Hermes cron schedule（仅建议，不在本任务内执行）

供后续 ops 创建 new-runner cron 或短期 shadow cron 参考：

- morning: `5 8 * * *`
- noon: `5 13 * * *`
- evening: `5 20 * * *`

若短期保留 shadow cron，建议比旧生产 cron 晚 5 分钟，便于：
- 避开同一分钟资源竞争
- 保持 slot 对齐
- 给 compare 与人工巡检留出固定窗口

若直接生产 cutover，新 runner cron 应使用与旧生产一致的业务 slot 时间，避免用户感知发布时间漂移。

建议 cron 命令模板：

```bash
cd /opt/data/home/NewsBriefingsSystem && \
/opt/hermes/.venv/bin/python scripts/run_shadow_briefing.py \
  --slot morning \
  --date "$(date +%F)" \
  --shadow-dir /opt/data/home/NewsBriefingsSystem/data/shadow
```

compare 可单独做第二条 cron，或先由人工执行：

```bash
cd /opt/data/home/NewsBriefingsSystem && \
/opt/hermes/.venv/bin/python scripts/compare_shadow_run.py \
  --legacy-archive /opt/data/home/NewsBriefings/"$(date +%F)".md \
  --shadow-manifest /opt/data/home/NewsBriefingsSystem/data/shadow/data/runs/"$(date +%F)"-08.json
```

注意：真正的 `cronjob create/update/pause` 由 ops 任务处理；本 runbook 不直接执行任何 Hermes cron 变更。ops 执行时必须先 `cronjob list` 记录旧 job，再 pause 旧 job，不得 delete。

## 6. 生产 cutover 步骤

预检通过后，按下面顺序切换：

1. `cronjob list` 记录旧生产 job：job_id、schedule、prompt/command、deliver target、当前 enabled 状态。
2. 创建或更新 new-runner 生产 cron，使用授权后的生产命令和业务 slot schedule。
3. 执行一次手动 run 或立即触发新 job，确认日志、归档路径、Telegram/Publisher 状态和 Hugo/Pages 输出符合预期。
4. pause 旧生产 cron；不要 delete。
5. 在 `docs/cron-migration-runbook.md` 或 ops handoff 中记录：旧 job pause 时间、新 job id、新命令、rollback 操作。不要记录 secrets。
   - 2026-05-21 实际 cutover 记录见 `docs/cron-cutover-record-2026-05-21.md`。
6. cutover 后首日保留人工 compare 或 spot check，确认没有新偏差。
7. 若一切稳定，再决定是否长期保留 shadow compare。

## 7. 回滚

若新 runner 或新 cron 出现问题，立即回滚到旧链路：

1. pause 新的 new-runner cron。
2. resume 旧生产 cron（使用 cutover 记录中的旧 job id）。
3. 如需人工补发，手动使用旧脚本：

```bash
python /opt/data/scripts/collect_news_context.py
bash /opt/data/scripts/run_news_briefing.sh
```

说明：
- 回滚不需要删除 shadow 目录；保留它作为问题排查证据。
- 回滚也不需要删除旧 cron；因此切换阶段只 pause 不 delete 很关键。
- 回滚后保留新 job 的失败日志、manifest 和 compare 报告，供后续修复。

## 8. 故障排查清单

若 shadow run 失败，优先检查：
- `data/shadow/logs/YYYY-MM-DD.log`
- `data/shadow/data/runs/YYYY-MM-DD-HH.json` 中的 `error_count/errors/publication`
- `data/shadow/config/newsroom.shadow.yaml` 是否把 `archive_dir`、`system_dir`、`paths.*` 全部指向 shadow 根目录
- compare 报告中的 `failed_sources` 是否与 manifest 的 `errors` 一致

若 compare 失败，优先检查：
- `--legacy-archive` 与 `--shadow-manifest` 是否对应同一天同 slot
- 旧归档对应 slot 是否存在 `briefing_id`
- shadow manifest 的 `jsonl_output` 是否存在且可读
