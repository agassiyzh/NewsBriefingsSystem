import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from newsroom.runner import run_briefing


def _write_phase1_configs(base_dir: Path, archive_dir: Path) -> Path:
    system_dir = base_dir / "system"
    config_dir = system_dir / "config"
    config_dir.mkdir(parents=True)

    newsroom_config = {
        "system": {
            "timezone": "Asia/Shanghai",
            "archive_dir": str(archive_dir),
            "system_dir": str(system_dir),
            "default_language": "zh-CN",
        },
        "collection": {
            "max_total": 10,
        },
        "paths": {
            "candidates_dir": "data/candidates",
            "contexts_dir": "data/contexts",
            "runs_dir": "data/runs",
            "logs_dir": "logs",
        },
    }
    sources_config = {
        "sources": [
            {"name": "Working Feed", "type": "rss", "url": "https://example.com/feed.xml", "max_items": 3}
        ]
    }
    interests_config = {
        "interests": [
            {"name": "AI Agent", "keywords": ["agent", "copilot"]}
        ]
    }

    (config_dir / "newsroom.yaml").write_text(yaml.safe_dump(newsroom_config, sort_keys=False), encoding="utf-8")
    (config_dir / "sources.yaml").write_text(yaml.safe_dump(sources_config, sort_keys=False), encoding="utf-8")
    (config_dir / "interests.yaml").write_text(yaml.safe_dump(interests_config, sort_keys=False), encoding="utf-8")
    return config_dir


def _fake_fetch(source):
    return [
        {
            "source": source["name"],
            "title": "Agent copilots ship for developers",
            "url": "https://example.com/story",
            "published": "2026-05-19T00:30:00+00:00",
            "snippet": "A new agent workflow shipped.",
        }
    ]


def test_run_briefing_dry_run_writes_outputs_but_skips_archive(tmp_path):
    archive_dir = tmp_path / "archive"
    config_dir = _write_phase1_configs(tmp_path, archive_dir)
    preview_path = tmp_path / "system" / "data" / "telegram" / "2026-05-19-08.txt"
    hugo_output = tmp_path / "system" / "site" / "content" / "briefings" / "2026" / "2026-05-19.md"

    result = run_briefing(
        config_path=config_dir / "newsroom.yaml",
        sources_path=config_dir / "sources.yaml",
        interests_path=config_dir / "interests.yaml",
        slot="morning",
        dry_run=True,
        fetcher=_fake_fetch,
        now=datetime(2026, 5, 19, 0, 5, tzinfo=UTC),
    )

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    jsonl_lines = Path(result.jsonl_output).read_text(encoding="utf-8").strip().splitlines()
    markdown_text = Path(result.markdown_output).read_text(encoding="utf-8")
    archive_path = archive_dir / "2026-05-19.md"

    assert result.briefing_id == "2026-05-19-08"
    assert manifest["briefing_id"] == "2026-05-19-08"
    assert manifest["dry_run"] is True
    assert manifest["candidate_count"] == 1
    assert manifest["publication"]["telegram"]["status"] == "dry_run"
    assert manifest["publication"]["telegram"]["dry_run"] is True
    assert manifest["publication"]["markdown_archive"]["status"] == "dry_run"
    assert manifest["publication"]["hugo_export"]["status"] == "dry_run"
    assert manifest["item_catalog"]["status"] == "dry_run"
    assert manifest["item_catalog"]["item_count"] == 1
    assert Path(result.jsonl_output).exists()
    assert Path(result.markdown_output).exists()
    assert len(jsonl_lines) == 1
    assert json.loads(jsonl_lines[0])["item_id"] == "2026-05-19-08-001"
    assert "# 新闻候选上下文" in markdown_text
    assert not archive_path.exists()
    assert not preview_path.exists()
    assert not hugo_output.exists()
    assert not Path(manifest["item_catalog"]["output_path"]).exists()


def test_run_briefing_non_dry_run_updates_slot_without_overwriting_other_sections(tmp_path):
    archive_dir = tmp_path / "archive"
    config_dir = _write_phase1_configs(tmp_path, archive_dir)
    preview_path = tmp_path / "system" / "data" / "telegram" / "2026-05-19-08.txt"
    hugo_output = tmp_path / "system" / "site" / "content" / "briefings" / "2026" / "2026-05-19.md"
    archive_dir.mkdir(parents=True)
    archive_path = archive_dir / "2026-05-19.md"
    archive_path.write_text(
        "# 新闻雷达｜2026-05-19\n\n"
        "## 08:00 早间版\n\n"
        "旧早间内容\n\n"
        "## 13:00 午间版\n\n"
        "保留的午间内容\n\n"
        "## 20:00 晚间版\n\n"
        "保留的晚间内容\n\n"
        "## 今日沉淀\n"
        "- 保留沉淀\n",
        encoding="utf-8",
    )

    result = run_briefing(
        config_path=config_dir / "newsroom.yaml",
        sources_path=config_dir / "sources.yaml",
        interests_path=config_dir / "interests.yaml",
        slot="morning",
        dry_run=False,
        fetcher=_fake_fetch,
        now=datetime(2026, 5, 19, 0, 5, tzinfo=UTC),
    )

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    archive_text = archive_path.read_text(encoding="utf-8")
    hugo_text = hugo_output.read_text(encoding="utf-8")
    preview_text = preview_path.read_text(encoding="utf-8")
    item_catalog_path = Path(manifest["item_catalog"]["output_path"])
    item_catalog_rows = [json.loads(line) for line in item_catalog_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert manifest["dry_run"] is False
    assert manifest["publication"]["markdown_archive"]["status"] == "updated"
    assert manifest["publication"]["telegram"]["status"] == "dry_run"
    assert manifest["publication"]["hugo_export"]["status"] == "updated"
    assert manifest["item_catalog"]["status"] == "updated"
    assert manifest["item_catalog"]["item_count"] == 1
    assert "Agent copilots ship for developers" in archive_text
    assert "旧早间内容" not in archive_text
    assert "保留的午间内容" in archive_text
    assert "保留的晚间内容" in archive_text
    assert "- 保留沉淀" in archive_text
    assert "新闻雷达｜2026-05-19 08:00 早间版" in preview_text
    assert hugo_text.startswith("---\n")
    assert "briefing_day: '2026-05-19'" in hugo_text
    assert "- item_id: 2026-05-19-08-001" in hugo_text
    assert item_catalog_path.exists()
    assert item_catalog_rows == [
        {
            "briefing_day": "2026-05-19",
            "slot": "morning",
            "slot_label": "08:00 早间版",
            "briefing_id": "2026-05-19-08",
            "item_id": "2026-05-19-08-001",
            "title": "Agent copilots ship for developers",
            "source": "Working Feed",
            "url": "https://example.com/story",
            "tags": ["AI Agent"],
            "topic": "AI Agent",
            "summary": "A new agent workflow shipped.",
            "published": "2026-05-19T00:30:00+00:00",
        }
    ]


def test_run_briefing_uses_config_timezone_for_briefing_id(tmp_path):
    archive_dir = tmp_path / "archive"
    config_dir = _write_phase1_configs(tmp_path, archive_dir)

    result = run_briefing(
        config_path=config_dir / "newsroom.yaml",
        sources_path=config_dir / "sources.yaml",
        interests_path=config_dir / "interests.yaml",
        slot="morning",
        dry_run=True,
        fetcher=_fake_fetch,
        now=datetime(2026, 5, 18, 16, 30, tzinfo=UTC),
    )

    assert result.briefing_id == "2026-05-19-08"
