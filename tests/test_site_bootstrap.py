import subprocess
import sys
from pathlib import Path

import yaml

from newsroom.site_bootstrap import ensure_sample_briefing_export


ROOT = Path(__file__).resolve().parents[1]
ENSURE_SAMPLE_SCRIPT = ROOT / "scripts" / "ensure_sample_briefing.py"


def _sample_archive_text() -> str:
    return (
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


def test_ensure_sample_briefing_export_generates_hugo_content(tmp_path):
    system_dir = tmp_path / "system"
    archive_path = system_dir / "site" / "sample-data" / "2026-01-01.md"
    output_path = system_dir / "site" / "content" / "briefings" / "2026" / "2026-01-01.md"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(_sample_archive_text(), encoding="utf-8")

    written_path = ensure_sample_briefing_export(
        system_dir=system_dir,
        archive_path=archive_path,
        output_path=output_path,
        timezone_name="Asia/Shanghai",
    )

    text = written_path.read_text(encoding="utf-8")
    _, front_matter_text, body = text.split("---\n", 2)
    front_matter = yaml.safe_load(front_matter_text)

    assert written_path == output_path
    assert front_matter["briefing_day"] == "2026-01-01"
    assert front_matter["item_count"] == 2
    assert front_matter["item_ids"] == ["2026-01-01-08-001", "2026-01-01-13-001"]
    assert front_matter["feedback_primary_briefing_id"] == "2026-01-01-08"
    assert front_matter["feedback_items"][0] == {
        "slot": "morning",
        "briefing_id": "2026-01-01-08",
        "item_id": "2026-01-01-08-001",
        "source": "Example Feed",
        "url": "https://example.com/agent-workflow",
        "tags": ["AI Agent", "Tooling"],
    }
    assert "# 新闻雷达｜2026-01-01" in body
    assert "## 今日沉淀" in body


def test_ensure_sample_briefing_export_preserves_existing_output_without_force(tmp_path):
    system_dir = tmp_path / "system"
    output_path = system_dir / "site" / "content" / "briefings" / "2026" / "2026-01-01.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("sentinel\n", encoding="utf-8")

    written_path = ensure_sample_briefing_export(system_dir=system_dir)

    assert written_path == output_path
    assert output_path.read_text(encoding="utf-8") == "sentinel\n"


def test_ensure_sample_briefing_cli_writes_default_output(tmp_path):
    system_dir = tmp_path / "system"
    archive_path = system_dir / "site" / "sample-data" / "2026-01-01.md"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(_sample_archive_text(), encoding="utf-8")

    process = subprocess.run(
        [sys.executable, str(ENSURE_SAMPLE_SCRIPT), "--system-dir", str(system_dir)],
        text=True,
        capture_output=True,
        check=True,
        env={"PYTHONPATH": str(ROOT)},
    )

    output_path = system_dir / "site" / "content" / "briefings" / "2026" / "2026-01-01.md"

    assert output_path.exists()
    assert f"output={output_path}" in process.stdout
