from __future__ import annotations

import argparse
from pathlib import Path

from .publisher import export_archive_to_hugo

DEFAULT_SAMPLE_ITEM_CATALOG_DIR = "data/item_catalog"

DEFAULT_SAMPLE_BRIEFING_DAY = "2026-01-01"
DEFAULT_SAMPLE_TIMEZONE = "Asia/Shanghai"
DEFAULT_SAMPLE_ARCHIVE_TEXT = (
    "# 新闻雷达｜2026-01-01\n\n"
    "## 08:00 早间版\n\n"
    "<!-- briefing_id: 2026-01-01-08 -->\n\n"
    "### 1｜示例：AI agent workflow 进入团队协作\n\n"
    "- item_id: 2026-01-01-08-001\n"
    "- source: Example Feed\n"
    "- url: https://example.com/agent-workflow\n"
    "- tags: [AI Agent, Tooling]\n\n"
    "摘要：示例条目，仅用于公开演示 GitHub Pages 页面结构。\n\n"
    "## 13:00 午间版\n\n"
    "<!-- briefing_id: 2026-01-01-13 -->\n\n"
    "### 1｜示例：机器人零售试点扩张\n\n"
    "- item_id: 2026-01-01-13-001\n"
    "- source: Example Robotics\n"
    "- url: https://example.com/robotics-retail\n"
    "- tags: [Robotics]\n\n"
    "摘要：示例条目，仅用于公开演示 Hugo 导出。\n\n"
    "## 20:00 晚间版\n\n"
    "_本版次暂无候选新闻。_\n\n"
    "## 今日沉淀\n\n"
    "- 趋势：示例内容用于演示公开站点信息层级。\n"
    "- 项目灵感：用结构化 brief 串联采集、编辑、发布。\n"
    "- 投资观察：关注 agent tooling 与机器人商业化。\n"
    "- 可写内容：把每日观察沉淀为稳定栏目。\n"
)


def default_sample_archive_path(system_dir: str | Path) -> Path:
    root = Path(system_dir)
    return root / "site" / "sample-data" / f"{DEFAULT_SAMPLE_BRIEFING_DAY}.md"


def default_sample_output_path(system_dir: str | Path) -> Path:
    root = Path(system_dir)
    return root / "site" / "content" / "briefings" / DEFAULT_SAMPLE_BRIEFING_DAY[:4] / f"{DEFAULT_SAMPLE_BRIEFING_DAY}.md"


def default_sample_item_catalog_path(system_dir: str | Path) -> Path:
    root = Path(system_dir)
    return root / DEFAULT_SAMPLE_ITEM_CATALOG_DIR / DEFAULT_SAMPLE_BRIEFING_DAY[:4] / f"{DEFAULT_SAMPLE_BRIEFING_DAY}.jsonl"


def ensure_sample_archive(archive_path: str | Path, *, force: bool = False) -> Path:
    target = Path(archive_path)
    if force or not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(DEFAULT_SAMPLE_ARCHIVE_TEXT, encoding="utf-8")
    return target


def ensure_sample_briefing_export(
    *,
    system_dir: str | Path,
    archive_path: str | Path | None = None,
    output_path: str | Path | None = None,
    timezone_name: str = DEFAULT_SAMPLE_TIMEZONE,
    force: bool = False,
) -> Path:
    resolved_archive = ensure_sample_archive(archive_path or default_sample_archive_path(system_dir), force=force)
    resolved_output = Path(output_path) if output_path else default_sample_output_path(system_dir)
    resolved_item_catalog = default_sample_item_catalog_path(system_dir)
    if resolved_output.exists() and resolved_item_catalog.exists() and not force:
        return resolved_output
    if resolved_output.exists() and not force:
        bootstrap_output = resolved_output.with_name(f".{resolved_output.stem}.item-catalog-bootstrap{resolved_output.suffix}")
        try:
            metadata = export_archive_to_hugo(
                archive_path=resolved_archive,
                output_path=bootstrap_output,
                briefing_day=DEFAULT_SAMPLE_BRIEFING_DAY,
                timezone_name=timezone_name,
                item_catalog_path=resolved_item_catalog,
            )
        finally:
            bootstrap_output.unlink(missing_ok=True)
        item_catalog = metadata.get("item_catalog", {})
        if item_catalog.get("status") == "updated":
            return resolved_output
    export_archive_to_hugo(
        archive_path=resolved_archive,
        output_path=resolved_output,
        briefing_day=DEFAULT_SAMPLE_BRIEFING_DAY,
        timezone_name=timezone_name,
        item_catalog_path=resolved_item_catalog,
    )
    return resolved_output


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ensure a safe sample briefing exists for Hugo/GitHub Pages demos.")
    parser.add_argument("--system-dir", default=Path(__file__).resolve().parents[1], help="项目根目录")
    parser.add_argument("--archive", default=None, help="可选：覆盖示例归档路径")
    parser.add_argument("--output", default=None, help="可选：覆盖 Hugo 输出路径")
    parser.add_argument("--timezone", default=DEFAULT_SAMPLE_TIMEZONE, help="示例 front matter 时区")
    parser.add_argument("--force", action="store_true", help="强制重写示例归档与导出文件")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    output_path = ensure_sample_briefing_export(
        system_dir=args.system_dir,
        archive_path=args.archive,
        output_path=args.output,
        timezone_name=args.timezone,
        force=args.force,
    )
    print(f"output={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
