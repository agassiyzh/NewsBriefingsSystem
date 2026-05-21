# 月度兴趣分析 → Editor 审核 → Editor-owned memory 运行手册

## 目标
提供 Analyst -> Editor 的月度偏好建议链路，并明确长期编辑记忆的所有者是启用 Hermes/Honcho memory 的 Editor-in-chief profile，而不是新闻仓库程序。

1. Analyst 运行月度兴趣分析，生成 `pending_review` 的 Editor recommendation brief 草案。
2. Editor 审阅 `data/monthly_insights/YYYY-MM.review.json` 或等价报告，筛掉单月热点、低样本推断和任何 raw events。
3. Editor 只在确认偏好稳定、跨月、声明性后，写入自己的 Hermes/Honcho memory。
4. 仓库内 `scripts/apply_editorial_preferences.py` / `NEWSROOM_HONCHO_*` 只保留为 deprecated 的本地迁移/debug 工具，不属于生产路径。

## 安全边界

- `scripts/monthly_analysis.py` 只输出 Editor recommendation brief，不会自动写入 Honcho 或 memory。
- Analyst 不直接写入 Honcho/Hermes memory；只向 Editor 报告证据、解释、置信度和建议。
- Reporter 保持 stateless，只接收 Editor brief；Publisher/Coder 不写长期编辑记忆。
- 新闻 repo 不再把 apply-to-Honcho endpoint/token/apply flag 作为生产路径。
- `scripts/apply_editorial_preferences.py` 若继续保留，只能标记为 deprecated/non-production/local migration/debug tool，默认 dry-run，不应由生产 cron 或 CI 调用。
- 不允许把 raw feedback events、单条新闻、单月短期热点、PII、明文身份信息写入 Honcho/Hermes memory。

## Step 1：生成月度分析草案

```bash
cd /opt/data/home/NewsBriefingsSystem
/opt/hermes/.venv/bin/python scripts/monthly_analysis.py --dry-run --month 2026-05
```

输出：
- `data/monthly_insights/2026-05.json`
- `docs/monthly-insights/2026-05.md`

说明：
- JSON 和 Markdown 中的 Editor recommendation brief 会保持 `pending_review`。
- 这些 brief 只是 Analyst 候选，不代表可以直接写入长期记忆。

## Step 2：Editor 审核 recommendation brief

建议以 `data/monthly_insights/2026-05.review.json` 为审核输入。
仓库中已提供一个示例文件，可作为模板：

- `data/monthly_insights/2026-05.review.json`

最小字段示例：

```json
{
  "month": "2026-05",
  "review_status": "pending_review",
  "reviewed_by": "",
  "reviewed_at": "",
  "summary": "仅可批准稳定、跨月、声明性的 editorial preferences 进入 Editor-owned memory。",
  "preferences": [
    {
      "id": "pref-2026-05-example-ai-agent",
      "candidate_preference": "用户连续 3 个月对 AI agent 工具链与开发者自动化内容保持更高兴趣。",
      "evidence_summary": "2026-03 至 2026-05 多个月份深读率高于月均。",
      "confidence": "high",
      "editor_decision": "needs_revision",
      "preference_type": "interest",
      "action": "add",
      "stable_preference": true,
      "stability_window_months": 3,
      "notes": "只保留声明性偏好，不包含底层事件标识或单月峰值。"
    }
  ]
}
```

审核要求：
- `review_status` 允许：`pending_review`、`approved`、`rejected`
- `editor_decision` 允许：`approved`、`rejected`、`needs_revision`
- 若 `review_status == "approved"`，必须填写非空 `reviewed_by` 与 `reviewed_at`
- 只有稳定、跨月、声明性的偏好才应设置为 `stable_preference=true`；即便批准，也应由 Editor profile 自己写入 memory

## Step 3：Editor 写入自己的 memory

生产路径不调用仓库脚本写 Honcho。推荐流程：

1. Editor 读取 Analyst recommendation brief 和聚合证据摘要。
2. Editor 删除或拒绝任何 raw event、anonymous_id、单条新闻结果、单月热点、低样本推断。
3. Editor 将稳定、跨月、声明性的偏好写入自己的 Hermes/Honcho memory。
4. Editor brief 在下一次每日简报前把相关偏好压缩成 Reporter brief；Reporter 不直接读取完整 memory。

## Deprecated：本地 apply adapter 只作迁移/debug

`scripts/apply_editorial_preferences.py`、`NEWSROOM_HONCHO_ENDPOINT`、`NEWSROOM_HONCHO_TOKEN`、`NEWSROOM_HONCHO_APPLY` 和 `--apply` 不属于生产路径。若暂时保留它们，只能用于：

- 本地迁移旧 review 文件。
- Debug payload shape。
- 验证“不会写 raw events / PII”的保护逻辑。

禁止把这些 endpoint/token/apply flag 接入生产 cron、GitHub Actions 或 Cloudflare/Pages deploy。需要真实长期记忆更新时，由 Editor profile 自己完成。

## Editor-owned memory 内容边界

Editor 可写入：
- 连续多月稳定高兴趣的 topic/tag/source 偏好
- 连续多月成立的降权规则
- 稳定的写作角度偏好，如更偏好可操作项目灵感、实现路径、验证信号

禁止写入：
- raw event、anonymous_id、IP、UA、精确位置、设备指纹
- 单条新闻是否被点击/点赞
- 单月突发热点导致的短期峰值
- 低样本推断
- 未经 Editor 审核的 Analyst 自动结论

## 回滚与删除边界

常规回滚：
- 保持 `review_status=pending_review`，Editor 不写入 memory。
- 若偏好已经过时，通过后续 Editor 审核写入新的 `replace` / 降权类偏好覆盖。
- 确保生产 cron、CI、Pages deploy 不设置或调用 `NEWSROOM_HONCHO_APPLY` / `--apply`。

不要把“删除”当成常规调权手段。

删除只用于以下高风险误写场景：
- 错把 PII / 明文身份信息写入 Editor-owned memory

如果只是编辑偏好过时、方向变化、或需要降权：
- 应通过新的月度审核结论做 `add` / `replace` 类更新
- 不应为了正常策略演进而删除历史记录

仓库内 adapter 不应承担生产删除；若发生 PII 误写，需要由 Editor/profile owner 走人工处置与单独审计流程。

## 推荐验证命令（仅验证分析与 deprecated adapter 保护逻辑）

```bash
cd /opt/data/home/NewsBriefingsSystem
/opt/hermes/.venv/bin/python -m pytest tests/test_editorial_preferences.py tests/test_monthly_analysis.py -q
```

## 相关文件

- `scripts/monthly_analysis.py`
- `newsroom/monthly_analysis.py`
- `scripts/apply_editorial_preferences.py`
- `newsroom/editorial_preferences.py`
- `data/monthly_insights/2026-05.review.json`
- `docs/monthly-insights/2026-04.md`
- `docs/monthly-interest-analysis-metrics-and-template.md`
