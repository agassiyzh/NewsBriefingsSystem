import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from newsroom.collector import CollectResult
from newsroom.publisher import (
    PublicationContext,
    TelegramPublisher,
    export_archive_to_hugo,
)


ROOT = Path(__file__).resolve().parents[1]
PUBLISH_TELEGRAM_SCRIPT = ROOT / "scripts" / "publish_telegram.py"
EXPORT_HUGO_SCRIPT = ROOT / "scripts" / "export_hugo.py"


def _base_publication_context(tmp_path: Path, *, collect_result: CollectResult, dry_run: bool) -> PublicationContext:
    archive_path = tmp_path / "archive" / "2026-05-19.md"
    return PublicationContext(
        briefing_id="2026-05-19-08",
        slot="morning",
        briefing_day="2026-05-19",
        timezone_name="Asia/Shanghai",
        archive_path=archive_path,
        collect_result=collect_result,
        system_dir=tmp_path,
        path_config={
            "telegram_previews_dir": "data/telegram",
            "hugo_content_dir": "site/content/briefings",
        },
        publication_config={
            "telegram_enabled": True,
            "markdown_enabled": True,
            "hugo_export_enabled": True,
        },
        dry_run=dry_run,
    )


def _sample_collect_result() -> CollectResult:
    return CollectResult(
        briefing_id="2026-05-19-08",
        collected_at="2026-05-19T00:05:00+00:00",
        candidates=[
            {
                "briefing_id": "2026-05-19-08",
                "item_id": "2026-05-19-08-001",
                "source": "Working Feed",
                "title": "Agent copilots ship for developers",
                "url": "https://example.com/story",
                "published": "2026-05-19T00:30:00+00:00",
                "snippet": "A new agent workflow shipped.",
                "tags": ["AI Agent"],
                "keywords": ["agent", "copilot"],
                "collected_at": "2026-05-19T00:05:00+00:00",
                "status": "ok",
                "error": "",
            }
        ],
        markdown="# 新闻候选上下文\n",
        error_count=0,
        errors=[],
    )


def _write_configs(system_dir: Path, archive_dir: Path, *, timezone: str) -> Path:
    config_dir = system_dir / "config"
    config_dir.mkdir(parents=True)
    archive_dir.mkdir(parents=True)

    newsroom_config = {
        "system": {
            "timezone": timezone,
            "archive_dir": str(archive_dir),
            "system_dir": str(system_dir),
        },
        "collection": {"max_total": 5},
        "publication": {
            "telegram_enabled": True,
            "markdown_enabled": True,
            "hugo_export_enabled": True,
        },
        "paths": {
            "candidates_dir": "data/candidates",
            "contexts_dir": "data/contexts",
            "runs_dir": "data/runs",
            "logs_dir": "logs",
            "telegram_previews_dir": "data/telegram",
            "hugo_content_dir": "site/content/briefings",
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


def _run_sample_briefing(
    tmp_path: Path,
    *,
    dry_run: bool,
    timezone: str = "Asia/Shanghai",
    briefing_id: str | None = None,
):
    system_dir = tmp_path / "system"
    archive_dir = tmp_path / "archive"
    config_dir = _write_configs(system_dir, archive_dir, timezone=timezone)

    from newsroom.runner import run_briefing

    def fake_fetch(source):
        return [
            {
                "source": source["name"],
                "title": "Agent copilots ship for developers",
                "url": "https://example.com/story",
                "published": "2026-05-19T00:30:00+00:00",
                "snippet": "A new agent workflow shipped.",
            }
        ]

    result = run_briefing(
        config_path=config_dir / "newsroom.yaml",
        sources_path=config_dir / "sources.yaml",
        interests_path=config_dir / "interests.yaml",
        slot="morning",
        dry_run=dry_run,
        fetcher=fake_fetch,
        briefing_id=briefing_id,
        now=datetime(2026, 5, 19, 0, 5, tzinfo=UTC),
    )
    return result, system_dir


def test_export_archive_to_hugo_writes_front_matter_and_slot_metadata(tmp_path):
    archive_path = tmp_path / "archive" / "2026-05-19.md"
    output_path = tmp_path / "site" / "content" / "briefings" / "2026" / "2026-05-19.md"
    item_catalog_path = tmp_path / "data" / "item_catalog" / "2026" / "2026-05-19.jsonl"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_text(
        "# 新闻雷达｜2026-05-19\n\n"
        "## 08:00 早间版\n\n"
        "<!-- briefing_id: 2026-05-19-08 -->\n\n"
        "### 1｜Agent copilots ship for developers\n\n"
        "- item_id: 2026-05-19-08-001\n"
        "- source: Working Feed\n"
        "- url: https://example.com/story\n"
        "- tags: [AI Agent, Tooling]\n\n"
        "摘要：A new agent workflow shipped.\n\n"
        "## 13:00 午间版\n\n"
        "<!-- briefing_id: 2026-05-19-13 -->\n\n"
        "### 1｜Robotics retail pilots expand\n\n"
        "- item_id: 2026-05-19-13-001\n"
        "- source: Noon Feed\n"
        "- url: https://example.com/noon\n"
        "- tags: [Robotics]\n\n"
        "摘要：Pilots expanded.\n\n"
        "## 20:00 晚间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 今日沉淀\n\n"
        "- 趋势：Agent workflow 更成熟\n",
        encoding="utf-8",
    )

    metadata = export_archive_to_hugo(
        archive_path=archive_path,
        output_path=output_path,
        briefing_day="2026-05-19",
        timezone_name="Asia/Shanghai",
        item_catalog_path=item_catalog_path,
    )

    text = output_path.read_text(encoding="utf-8")
    _, front_matter_text, body = text.split("---\n", 2)
    front_matter = yaml.safe_load(front_matter_text)
    item_catalog_rows = [json.loads(line) for line in item_catalog_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert metadata["item_count"] == 2
    assert metadata["item_catalog"] == {
        "status": "updated",
        "output_path": str(item_catalog_path),
        "item_count": 2,
    }
    assert front_matter["briefing_day"] == "2026-05-19"
    assert front_matter["item_ids"] == ["2026-05-19-08-001", "2026-05-19-13-001"]
    assert front_matter["sources"] == ["Noon Feed", "Working Feed"]
    assert front_matter["tags"] == ["AI Agent", "Robotics", "Tooling"]
    assert front_matter["feedback_primary_briefing_id"] == "2026-05-19-08"
    assert front_matter["feedback_items"] == [
        {
            "slot": "morning",
            "briefing_id": "2026-05-19-08",
            "item_id": "2026-05-19-08-001",
            "source": "Working Feed",
            "url": "https://example.com/story",
            "tags": ["AI Agent", "Tooling"],
        },
        {
            "slot": "noon",
            "briefing_id": "2026-05-19-13",
            "item_id": "2026-05-19-13-001",
            "source": "Noon Feed",
            "url": "https://example.com/noon",
            "tags": ["Robotics"],
        },
    ]
    assert front_matter["slots"][0]["briefing_id"] == "2026-05-19-08"
    assert "## 08:00 早间版" in body
    assert "- item_id: 2026-05-19-08-001" in body
    assert '<section class="news-item-card" data-news-item-id="2026-05-19-08-001">' in body
    assert '{{< item-feedback briefing_id="2026-05-19-08" item_id="2026-05-19-08-001" source="Working Feed" tags="AI Agent,Tooling" >}}' in body
    assert "## 今日沉淀" in body
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
            "tags": ["AI Agent", "Tooling"],
            "topic": "AI Agent",
            "summary": "A new agent workflow shipped.",
            "published": "",
        },
        {
            "briefing_day": "2026-05-19",
            "slot": "noon",
            "slot_label": "13:00 午间版",
            "briefing_id": "2026-05-19-13",
            "item_id": "2026-05-19-13-001",
            "title": "Robotics retail pilots expand",
            "source": "Noon Feed",
            "url": "https://example.com/noon",
            "tags": ["Robotics"],
            "topic": "Robotics",
            "summary": "Pilots expanded.",
            "published": "",
        },
    ]


def test_telegram_publisher_safe_local_writes_preview_without_sending(tmp_path):
    sent_messages = []
    preview_path = tmp_path / "preview.txt"
    publisher = TelegramPublisher(preview_path=preview_path, sender=sent_messages.append)
    context = _base_publication_context(tmp_path, collect_result=_sample_collect_result(), dry_run=False)

    result = publisher.publish(context)

    preview_text = preview_path.read_text(encoding="utf-8")
    assert result.status == "dry_run"
    assert result.dry_run is True
    assert result.output_path == str(preview_path)
    assert "新闻雷达｜2026-05-19 08:00 早间版" in preview_text
    assert "1｜Agent copilots ship for developers" in preview_text
    assert "链接：https://example.com/story" in preview_text
    assert sent_messages == []


def test_publish_telegram_cli_dry_run_manifest_keeps_status_without_writing_preview(tmp_path):
    result, system_dir = _run_sample_briefing(tmp_path, dry_run=True)

    process = subprocess.run(
        [sys.executable, str(PUBLISH_TELEGRAM_SCRIPT), "--manifest", result.manifest_path],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    preview_path = system_dir / "data" / "telegram" / "2026-05-19-08.txt"

    assert "status=dry_run" in process.stdout
    assert f"preview={preview_path}" in process.stdout
    assert not preview_path.exists()
    assert manifest["publication"]["telegram"]["status"] == "dry_run"
    assert manifest["publication"]["telegram"]["dry_run"] is True
    assert manifest["publication"]["telegram"]["output_path"] == str(preview_path)


def test_export_hugo_cli_dry_run_manifest_keeps_status_without_writing_file(tmp_path):
    result, _ = _run_sample_briefing(tmp_path, dry_run=True)
    output_path = tmp_path / "manual-hugo.md"

    process = subprocess.run(
        [sys.executable, str(EXPORT_HUGO_SCRIPT), "--manifest", result.manifest_path, "--output", str(output_path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))

    assert f"output={output_path.resolve()}" in process.stdout
    assert not output_path.exists()
    assert manifest["publication"]["hugo_export"]["status"] == "dry_run"
    assert manifest["publication"]["hugo_export"]["dry_run"] is True
    assert manifest["publication"]["hugo_export"]["output_path"] == str(output_path)


def test_export_hugo_cli_updates_manifest_and_uses_manifest_timezone(tmp_path):
    result, _ = _run_sample_briefing(
        tmp_path,
        dry_run=False,
        timezone="UTC",
        briefing_id="2099-01-03-08",
    )

    output_path = tmp_path / "manual-hugo.md"
    process = subprocess.run(
        [sys.executable, str(EXPORT_HUGO_SCRIPT), "--manifest", result.manifest_path, "--output", str(output_path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    output_text = output_path.read_text(encoding="utf-8")
    item_catalog_path = Path(manifest["item_catalog"]["output_path"])

    assert f"output={output_path.resolve()}" in process.stdout
    assert output_path.exists()
    assert manifest["publication"]["hugo_export"]["status"] == "updated"
    assert manifest["publication"]["hugo_export"]["output_path"] == str(output_path)
    assert item_catalog_path.exists()
    assert "date: '2099-01-03T08:00:00+00:00'" in output_text


def test_export_hugo_cli_archive_mode_writes_item_catalog(tmp_path):
    archive_path = tmp_path / "archive" / "2026-05-19.md"
    output_path = tmp_path / "manual-hugo.md"
    item_catalog_path = tmp_path / "data" / "item_catalog" / "2026" / "2026-05-19.jsonl"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(
        "# 新闻雷达｜2026-05-19\n\n"
        "## 08:00 早间版\n\n"
        "<!-- briefing_id: 2026-05-19-08 -->\n\n"
        "### 1｜Agent copilots ship for developers\n\n"
        "- item_id: 2026-05-19-08-001\n"
        "- source: Working Feed\n"
        "- url: https://example.com/story\n"
        "- published: 2026-05-19T00:30:00+00:00\n"
        "- tags: [AI Agent, Tooling]\n\n"
        "摘要：A new agent workflow shipped.\n\n"
        "## 13:00 午间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 20:00 晚间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 今日沉淀\n\n"
        "- 趋势：Agent workflow 更成熟\n",
        encoding="utf-8",
    )

    process = subprocess.run(
        [
            sys.executable,
            str(EXPORT_HUGO_SCRIPT),
            "--archive",
            str(archive_path),
            "--briefing-day",
            "2026-05-19",
            "--timezone",
            "UTC",
            "--output",
            str(output_path),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )

    rows = [json.loads(line) for line in item_catalog_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert f"output={output_path.resolve()}" in process.stdout
    assert output_path.exists()
    assert item_catalog_path.exists()
    assert rows == [
        {
            "briefing_day": "2026-05-19",
            "slot": "morning",
            "slot_label": "08:00 早间版",
            "briefing_id": "2026-05-19-08",
            "item_id": "2026-05-19-08-001",
            "title": "Agent copilots ship for developers",
            "source": "Working Feed",
            "url": "https://example.com/story",
            "tags": ["AI Agent", "Tooling"],
            "topic": "AI Agent",
            "summary": "A new agent workflow shipped.",
            "published": "2026-05-19T00:30:00+00:00",
        }
    ]
