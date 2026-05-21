import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from newsroom.runner import run_briefing


def _write_configs(base_dir: Path, archive_dir: Path) -> Path:
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
            "max_total": 20,
        },
        "feedback": {
            "default_channel": "site",
        },
        "paths": {
            "candidates_dir": "data/candidates",
            "contexts_dir": "data/contexts",
            "briefings_dir": "data/briefings",
            "runs_dir": "data/runs",
            "logs_dir": "logs",
            "telegram_previews_dir": "data/telegram",
            "hugo_content_dir": "site/content/briefings",
            "item_catalog_dir": "data/item_catalog",
        },
    }
    sources_config = {
        "sources": [
            {"name": "Working Feed", "type": "rss", "url": "https://example.com/feed.xml", "max_items": 20}
        ]
    }
    interests_config = {
        "interests": [
            {"name": "AI Agent", "keywords": ["agent", "tooling"]},
        ]
    }

    (config_dir / "newsroom.yaml").write_text(yaml.safe_dump(newsroom_config, sort_keys=False), encoding="utf-8")
    (config_dir / "sources.yaml").write_text(yaml.safe_dump(sources_config, sort_keys=False), encoding="utf-8")
    (config_dir / "interests.yaml").write_text(yaml.safe_dump(interests_config, sort_keys=False), encoding="utf-8")
    return config_dir


def _fake_fetch_many(source):
    return [
        {
            "source": source["name"],
            "title": f"Agent workflow update {index}",
            "url": f"https://example.com/story-{index}",
            "published": "2026-05-19T00:30:00+00:00",
            "snippet": f"Concrete update {index} for agents and developer tooling.",
        }
        for index in range(1, 16)
    ]


def test_run_briefing_publishes_curated_items_not_all_candidates(tmp_path):
    archive_dir = tmp_path / "archive"
    config_dir = _write_configs(tmp_path, archive_dir)

    result = run_briefing(
        config_path=config_dir / "newsroom.yaml",
        sources_path=config_dir / "sources.yaml",
        interests_path=config_dir / "interests.yaml",
        slot="morning",
        briefing_id="2099-01-03-08",
        dry_run=False,
        fetcher=_fake_fetch_many,
        now=datetime(2099, 1, 3, 0, 5, tzinfo=UTC),
    )

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    jsonl_lines = [line for line in Path(result.jsonl_output).read_text(encoding="utf-8").splitlines() if line.strip()]
    curated_payload = json.loads(Path(manifest["curated_output"]).read_text(encoding="utf-8"))
    archive_text = Path(manifest["archive_path"]).read_text(encoding="utf-8")
    preview_text = Path(manifest["publication"]["telegram"]["output_path"]).read_text(encoding="utf-8")
    item_catalog_rows = [
        json.loads(line)
        for line in Path(manifest["item_catalog"]["output_path"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(jsonl_lines) == 15
    assert manifest["candidate_count"] == 15
    assert manifest["curated_item_count"] == 12
    assert manifest["editor_version"] == "curated-v1"
    assert curated_payload["briefing_id"] == "2099-01-03-08"
    assert curated_payload["curated_item_count"] == 12
    assert [item["item_id"] for item in curated_payload["items"]] == [
        "2099-01-03-08-001",
        "2099-01-03-08-002",
        "2099-01-03-08-003",
        "2099-01-03-08-004",
        "2099-01-03-08-005",
        "2099-01-03-08-006",
        "2099-01-03-08-007",
        "2099-01-03-08-008",
        "2099-01-03-08-009",
        "2099-01-03-08-010",
        "2099-01-03-08-011",
        "2099-01-03-08-012",
    ]
    assert curated_payload["feedback_items"][0]["item_id"] == "2099-01-03-08-001"
    assert curated_payload["feedback_items"][0]["topic"] == "AI Agent"
    assert curated_payload["feedback_items"][0]["channel"] == "site"
    assert "今日信号：" in archive_text
    assert "- why_relevant:" in archive_text
    assert "- action_or_observe:" in archive_text
    assert "13｜Agent workflow update 13" not in archive_text
    assert "今日信号：" in preview_text
    assert "12｜Agent workflow update 12" in preview_text
    assert "13｜Agent workflow update 13" not in preview_text
    assert len(item_catalog_rows) == 12
    assert item_catalog_rows[0]["item_id"] == "2099-01-03-08-001"
    assert item_catalog_rows[0]["why_relevant"]
    assert item_catalog_rows[0]["action_or_observe"].startswith(("行动：", "观察："))
