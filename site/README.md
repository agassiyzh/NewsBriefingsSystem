# site/

本目录用于 Phase 3 Hugo/GitHub Pages 导出层。

约定：
- Hugo 内容默认输出到 `site/content/briefings/YYYY/YYYY-MM-DD.md`。
- `site/sample-data/2026-01-01.md` 为公开安全示例归档；`python scripts/ensure_sample_briefing.py` 会把它导出为 Hugo 内容，并同步生成 `data/item_catalog/2026/2026-01-01.jsonl`，确保首次 Pages 部署与月度分析都有可用样例。
- `site/layouts/` 与 `site/hugo.toml` 提供最小可工作的 theme-free Hugo 模板。
- 本地 Markdown 日归档仍是内容主源；Hugo 文件属于导出产物，可由正式 runner 或示例脚本生成。
- GitHub Pages 通过仓库根目录下的 `.github/workflows/pages.yml` 在 Actions 中安装 Hugo、运行测试、构建并发布 `site/public/`。
