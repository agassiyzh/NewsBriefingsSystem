import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from newsroom.collector import collect_candidates, main as collect_main


ROOT = Path(__file__).resolve().parents[1]
COLLECT_SCRIPT = ROOT / "scripts" / "collect_candidates.py"


def test_collect_candidates_keeps_running_after_source_failure_and_renders_markdown():
    sources = [
        {"name": "Working Feed", "type": "rss", "url": "https://example.com/feed.xml", "max_items": 3},
        {"name": "Broken Feed", "type": "rss", "url": "https://example.com/broken.xml", "max_items": 3},
    ]
    interests = [
        {"name": "AI Agent", "keywords": ["agent", "copilot"]},
        {"name": "POS SaaS", "keywords": ["pos", "retail"]},
    ]

    def fake_fetch(source):
        if source["name"] == "Broken Feed":
            raise RuntimeError("boom")
        return [
            {
                "source": source["name"],
                "title": "AI agent copilots for retail POS teams",
                "url": "https://example.com/story",
                "published": "2026-05-19T00:30:00+00:00",
                "snippet": "Retail POS operators are adopting agent copilots.",
            }
        ]

    result = collect_candidates(
        briefing_id="2026-05-19-08",
        source_defs=sources,
        interest_defs=interests,
        existing_summary="今天已经提到旧闻 A",
        fetcher=fake_fetch,
        collected_at="2026-05-19T01:02:03+00:00",
    )

    assert result.error_count == 1
    assert [candidate["item_id"] for candidate in result.candidates] == [
        "2026-05-19-08-001",
        "2026-05-19-08-002",
    ]
    assert result.candidates[0]["tags"] == ["AI Agent", "POS SaaS"]
    assert result.candidates[0]["keywords"] == ["agent", "copilot", "pos", "retail"]
    assert result.candidates[1]["title"].startswith("[fetch failed]")
    assert result.candidates[1]["tags"] == ["error"]
    assert "今天已经提到旧闻 A" in result.markdown
    assert "Working Feed" in result.markdown


def test_collect_candidates_cli_resolves_default_config_from_outside_system_dir_and_accepts_output_aliases(tmp_path):
    system_dir = tmp_path / "system"
    config_dir = system_dir / "config"
    archive_dir = tmp_path / "archive"
    config_dir.mkdir(parents=True)
    archive_dir.mkdir(parents=True)

    newsroom_config = {
        "system": {
            "timezone": "Asia/Shanghai",
            "archive_dir": str(archive_dir),
            "system_dir": str(system_dir),
        },
        "collection": {
            "max_total": 5,
        },
    }
    sources_config = {
        "sources": [
            {
                "name": "Working Feed",
                "type": "rss",
                "url": f"file://{(tmp_path / 'feed.xml').resolve()}",
                "max_items": 3,
            }
        ]
    }
    interests_config = {
        "interests": [
            {"name": "AI Agent", "keywords": ["agent", "copilot"]}
        ]
    }
    feed_path = tmp_path / "feed.xml"
    feed_path.write_text(
        """<?xml version='1.0' encoding='UTF-8'?>
        <rss><channel><item>
          <title>Agent copilots ship for developers</title>
          <link>https://example.com/story</link>
          <pubDate>Mon, 19 May 2026 00:30:00 GMT</pubDate>
          <description>A new agent workflow shipped.</description>
        </item></channel></rss>
        """,
        encoding="utf-8",
    )

    (config_dir / "newsroom.yaml").write_text(yaml.safe_dump(newsroom_config, sort_keys=False), encoding="utf-8")
    (config_dir / "sources.yaml").write_text(yaml.safe_dump(sources_config, sort_keys=False), encoding="utf-8")
    (config_dir / "interests.yaml").write_text(yaml.safe_dump(interests_config, sort_keys=False), encoding="utf-8")

    jsonl_output = tmp_path / "out" / "candidates.jsonl"
    markdown_output = tmp_path / "out" / "context.md"
    process = subprocess.run(
        [
            sys.executable,
            str(COLLECT_SCRIPT),
            "--briefing-id",
            "2026-05-19-08",
            "--output-jsonl",
            str(jsonl_output),
            "--output-markdown",
            str(markdown_output),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )

    assert jsonl_output.exists()
    assert markdown_output.exists()
    assert process.stdout == markdown_output.read_text(encoding="utf-8")
    assert "briefing_id：2026-05-19-08" in process.stdout


def test_collect_candidates_cli_uses_config_timezone_for_default_date(tmp_path, monkeypatch):
    system_dir = tmp_path / "system"
    config_dir = system_dir / "config"
    archive_dir = tmp_path / "archive"
    config_dir.mkdir(parents=True)
    archive_dir.mkdir(parents=True)

    newsroom_config = {
        "system": {
            "timezone": "Asia/Shanghai",
            "archive_dir": str(archive_dir),
            "system_dir": str(system_dir),
        }
    }
    sources_config = {
        "sources": [
            {
                "name": "Working Feed",
                "type": "rss",
                "url": f"file://{(tmp_path / 'feed.xml').resolve()}",
                "max_items": 3,
            }
        ]
    }
    interests_config = {
        "interests": [
            {"name": "AI Agent", "keywords": ["agent", "copilot"]}
        ]
    }
    feed_path = tmp_path / "feed.xml"
    feed_path.write_text(
        """<?xml version='1.0' encoding='UTF-8'?>
        <rss><channel><item>
          <title>Agent copilots ship for developers</title>
          <link>https://example.com/story</link>
          <pubDate>Mon, 19 May 2026 00:30:00 GMT</pubDate>
          <description>A new agent workflow shipped.</description>
        </item></channel></rss>
        """,
        encoding="utf-8",
    )

    (config_dir / "newsroom.yaml").write_text(yaml.safe_dump(newsroom_config, sort_keys=False), encoding="utf-8")
    (config_dir / "sources.yaml").write_text(yaml.safe_dump(sources_config, sort_keys=False), encoding="utf-8")
    (config_dir / "interests.yaml").write_text(yaml.safe_dump(interests_config, sort_keys=False), encoding="utf-8")

    from newsroom import collector as collector_module

    target_tz = collector_module.resolve_runtime(None, "Asia/Shanghai").tzinfo

    def fake_resolve_runtime(now, timezone_name):
        assert timezone_name == "Asia/Shanghai"
        return datetime(2026, 5, 19, 0, 30, tzinfo=UTC).astimezone(target_tz)

    monkeypatch.setattr(collector_module, "resolve_runtime", fake_resolve_runtime)

    exit_code = collect_main(
        [
            "--config",
            str(config_dir / "newsroom.yaml"),
            "--sources",
            str(config_dir / "sources.yaml"),
            "--interests",
            str(config_dir / "interests.yaml"),
            "--slot",
            "morning",
        ]
    )

    assert exit_code == 0
    assert (system_dir / "data" / "candidates" / "2026-05-19-08.jsonl").exists()
    assert (system_dir / "data" / "contexts" / "2026-05-19-08.md").exists()
