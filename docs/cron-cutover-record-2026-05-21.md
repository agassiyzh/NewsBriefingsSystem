# NewsBriefingsSystem 生产 cron cutover 记录（2026-05-21）

状态：已执行 cutover，等待 review。

## 1. 执行摘要

- 旧生产简报 cron 已 pause，不删除。
- 新 runner 生产 cron 已创建并启用，业务时间保持与旧生产一致：08:00 / 13:00 / 20:00（Asia/Shanghai，对应 UTC `0 0 * * *` / `0 5 * * *` / `0 12 * * *`）。
- 2026-05-21 已手动触发 morning 新 job 做健康检查；scheduler 记录 `last_status=ok`，且无 delivery error。
- repo 内 `TelegramPublisher` 仍保持 safe-local preview 语义；真实 Telegram 投递改由 Hermes cron `no_agent` job 将 wrapper stdout 直接投递到既有生产 Telegram 目标。

## 2. 执行时间与操作者

- pause/cutover 时间（UTC）：`2026-05-21T02:45:05Z`
- pause/cutover 时间（Asia/Shanghai）：`2026-05-21T10:45:05+0800`
- 操作者：`hermes`
- scheduler 根：`HERMES_HOME=/opt/data`

## 3. 旧生产 job 备份（rollback-safe）

以下旧 job 均保留在 scheduler 中，仅 pause：

| slot | old job id | name | schedule (UTC) | 业务时间 | 旧链路 |
| --- | --- | --- | --- | --- | --- |
| morning | `5a2e177fae6c` | `daily-news-briefing-morning` | `0 0 * * *` | 08:00 Asia/Shanghai | Hermes LLM cron + pre-run script `collect_news_context.py` + `deliver=telegram` |
| noon | `0fca043995aa` | `daily-news-briefing-noon` | `0 5 * * *` | 13:00 Asia/Shanghai | Hermes LLM cron + pre-run script `collect_news_context.py` + `deliver=telegram` |
| evening | `d13093adcfe6` | `daily-news-briefing-evening` | `0 12 * * *` | 20:00 Asia/Shanghai | Hermes LLM cron + pre-run script `collect_news_context.py` + `deliver=telegram` |

旧生产脚本与手动恢复入口保持不删：

- `/opt/data/scripts/collect_news_context.py`
- `/opt/data/scripts/run_news_briefing.sh`
- `/opt/data/scripts/news_briefing_morning.sh`
- `/opt/data/scripts/news_briefing_noon.sh`
- `/opt/data/scripts/news_briefing_evening.sh`

旧链路手动补发命令：

```bash
python /opt/data/scripts/collect_news_context.py
bash /opt/data/scripts/news_briefing_morning.sh
bash /opt/data/scripts/news_briefing_noon.sh
bash /opt/data/scripts/news_briefing_evening.sh
```

说明：旧 job 的生产 Telegram 目标未变更；由于恢复时直接 `resume` 旧 job 即可，不在本 repo 文档中重复记录具体 chat id。

## 4. 新 runner 生产 job

新增 job：

| slot | new job id | name | schedule (UTC) | 业务时间 | mode |
| --- | --- | --- | --- | --- | --- |
| morning | `1e296df8d94c` | `daily-news-briefing-morning-runner` | `0 0 * * *` | 08:00 Asia/Shanghai | `no_agent` |
| noon | `b1a4369bb988` | `daily-news-briefing-noon-runner` | `0 5 * * *` | 13:00 Asia/Shanghai | `no_agent` |
| evening | `86afc581a1f8` | `daily-news-briefing-evening-runner` | `0 12 * * *` | 20:00 Asia/Shanghai | `no_agent` |

新 job 统一使用 Hermes scheduler scripts 目录中的 wrapper：

- `/opt/data/scripts/newsroom_runner_cron.sh`
- `/opt/data/scripts/newsroom_runner_cron_morning.sh`
- `/opt/data/scripts/newsroom_runner_cron_noon.sh`
- `/opt/data/scripts/newsroom_runner_cron_evening.sh`

wrapper 行为：

1. 用 repo venv：`/opt/data/home/NewsBriefingsSystem/.venv/bin/python`
2. 显式执行：
   - `scripts/run_briefing.py`
   - `--config /opt/data/home/NewsBriefingsSystem/config/newsroom.yaml`
   - `--sources /opt/data/home/NewsBriefingsSystem/config/sources.yaml`
   - `--interests /opt/data/home/NewsBriefingsSystem/config/interests.yaml`
   - `--slot <morning|noon|evening>`
3. 校验 manifest：
   - `dry_run=false`
   - `publication.markdown_archive.status=updated`
   - `publication.telegram.status=dry_run`
   - `publication.hugo_export.status=updated`
   - 本地 preview 文件存在且非空
4. 将 preview 文本写到 stdout，由 Hermes cron `deliver=telegram` 负责真实投递到既有生产 Telegram 目标。

说明：之所以采用 `.sh` wrapper，而不是直接把 `.py` 作为 cron `script`，是因为 Hermes `no_agent` cron 会用 scheduler 自身 Python 执行非 shell 脚本；这里明确落到 repo venv，避免依赖漂移，并把 manifest 校验收敛在一个可审计入口里。

## 5. cutover 后健康检查

已执行：

```bash
export HERMES_HOME=/opt/data
/opt/hermes/.venv/bin/hermes cron run 1e296df8d94c
/opt/hermes/.venv/bin/hermes cron tick --accept-hooks
/opt/hermes/.venv/bin/hermes cron list --all
```

验证结果（morning）：

- job id：`1e296df8d94c`
- `last_run_at`: `2026-05-21T02:45:35.925825+00:00`
- `last_status`: `ok`
- `last_delivery_error`: `null`
- manifest：`/opt/data/home/NewsBriefingsSystem/data/runs/2026-05-21-08.json`
- Telegram preview：`/opt/data/home/NewsBriefingsSystem/data/telegram/2026-05-21-08.txt`
- Hugo export：`/opt/data/home/NewsBriefingsSystem/site/content/briefings/2026/2026-05-21.md`
- Markdown archive：`/opt/data/home/NewsBriefings/2026-05-21.md`

manifest 关键状态：

- `publication.markdown_archive.status = updated`
- `publication.telegram.status = dry_run`
- `publication.telegram.details.reason = safe-local publisher: 仅生成 Telegram 预览，不执行真实发送。`
- `publication.hugo_export.status = updated`

解释：repo 内 publisher 仍是 safe-local；真正对 Telegram 的生产发送由 Hermes cron delivery 完成，因此仍满足“保留 preview 文件 + 真实投递到既有目标”的 cutover 目标。

## 6. rollback

若新 runner 生产链路有问题，立即执行：

```bash
export HERMES_HOME=/opt/data
/opt/hermes/.venv/bin/hermes cron pause 1e296df8d94c
/opt/hermes/.venv/bin/hermes cron pause b1a4369bb988
/opt/hermes/.venv/bin/hermes cron pause 86afc581a1f8

/opt/hermes/.venv/bin/hermes cron resume 5a2e177fae6c
/opt/hermes/.venv/bin/hermes cron resume 0fca043995aa
/opt/hermes/.venv/bin/hermes cron resume d13093adcfe6
```

如需人工补发，使用旧链路：

```bash
python /opt/data/scripts/collect_news_context.py
bash /opt/data/scripts/news_briefing_morning.sh
bash /opt/data/scripts/news_briefing_noon.sh
bash /opt/data/scripts/news_briefing_evening.sh
```

保留证据，不删除：

- `/opt/data/home/NewsBriefingsSystem/data/shadow`
- `/opt/data/home/NewsBriefingsSystem/data/runs/*.json`
- `/opt/data/home/NewsBriefingsSystem/data/telegram/*.txt`
- `/opt/data/home/NewsBriefingsSystem/site/content/briefings/**/*`
- `/opt/data/home/NewsBriefingsSystem/logs/*.log`

## 7. review 重点

建议 reviewer 重点确认：

1. 用 Hermes `no_agent` delivery 承担真实 Telegram 发送是否符合长期生产口径。
2. 新 wrapper 对 manifest 校验条件是否足够严格。
3. 只对 morning 做了真实手动 trigger；noon/evening 将按 schedule 首次运行，可在 cutover 首日继续 spot check。
