# Personal Newsroom Phase 1 Implementation Plan

Goal: 在不破坏现有新闻 cron/Telegram 闭环的前提下，补上结构化采集、稳定 ID、角色 prompt 与手动 runner 的最小可用基础设施。

已拆分任务：
1. 读取架构文档与现有脚本，确认兼容约束。
2. 建立目录与无密钥配置骨架。
3. 先写测试，覆盖 ID 规则、失败源容错、runner 输出。
4. 实现 `newsroom` 模块与 CLI wrapper。
5. 执行 dry-run 验证，确认 JSONL / Markdown / manifest 均可生成。
6. 保留 review-required 交接，等待人工复核后进入下一阶段。
