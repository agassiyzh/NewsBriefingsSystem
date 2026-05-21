from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from newsroom.shadow import _legacy_rows_for_slot, compare_shadow_run, run_shadow_briefing


def _write_project_configs(project_root: Path, archive_dir: Path) -> Path:
    config_dir = project_root / "config"
    config_dir.mkdir(parents=True)

    newsroom_config = {
        "system": {
            "timezone": "Asia/Shanghai",
            "archive_dir": str(archive_dir),
            "system_dir": str(project_root),
            "default_language": "zh-CN",
        },
        "collection": {
            "max_total": 10,
        },
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
            {"name": "AI Agent", "keywords": ["agent", "copilot"]},
            {"name": "Tooling", "keywords": ["developer"]},
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


def _write_shadow_manifest(
    shadow_dir: Path,
    *,
    briefing_id: str,
    slot: str = "morning",
    jsonl_rows: list[dict[str, object]] | None = None,
    errors: list[dict[str, str]] | None = None,
) -> Path:
    jsonl_path = shadow_dir / "data" / "runs" / f"{briefing_id}.jsonl"
    jsonl_path.parent.mkdir(parents=True)
    rows = jsonl_rows or [
        {
            "briefing_id": briefing_id,
            "item_id": "shadow-001",
            "source": "Working Feed",
            "title": "Agent copilots ship for developers",
            "url": "https://example.com/story",
            "tags": ["AI Agent"],
            "topic": "AI Agent",
            "status": "ok",
            "error": "",
        }
    ]
    jsonl_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    manifest_path = shadow_dir / "data" / "runs" / f"{briefing_id}.json"
    manifest_errors = errors or []
    manifest_path.write_text(
        json.dumps(
            {
                "briefing_id": briefing_id,
                "slot": slot,
                "jsonl_output": str(jsonl_path),
                "error_count": len(manifest_errors),
                "errors": manifest_errors,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path


def test_run_shadow_briefing_writes_all_outputs_under_shadow_dir(tmp_path):
    project_root = tmp_path / "project"
    production_archive_dir = tmp_path / "production-archive"
    config_dir = _write_project_configs(project_root, production_archive_dir)
    shadow_dir = tmp_path / "shadow"

    result = run_shadow_briefing(
        config_path=config_dir / "newsroom.yaml",
        sources_path=config_dir / "sources.yaml",
        interests_path=config_dir / "interests.yaml",
        shadow_dir=shadow_dir,
        slot="morning",
        date="2026-05-19",
        dry_run=False,
        fetcher=_fake_fetch,
        now=datetime(2026, 5, 19, 0, 5, tzinfo=UTC),
    )

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    shadow_archive = shadow_dir / "archive" / "2026-05-19.md"
    shadow_preview = shadow_dir / "data" / "telegram" / "2026-05-19-08.txt"
    shadow_hugo = shadow_dir / "site" / "content" / "briefings" / "2026" / "2026-05-19.md"
    shadow_log = shadow_dir / "logs" / "2026-05-19.log"

    assert not (production_archive_dir / "2026-05-19.md").exists()
    assert Path(manifest["newsroom_config_path"]).is_file()
    assert Path(manifest["archive_path"]) == shadow_archive
    assert Path(manifest["jsonl_output"]).is_relative_to(shadow_dir)
    assert Path(manifest["markdown_output"]).is_relative_to(shadow_dir)
    assert Path(manifest["log_path"]).is_relative_to(shadow_dir)
    assert Path(manifest["publication"]["telegram"]["output_path"]) == shadow_preview
    assert Path(manifest["publication"]["hugo_export"]["output_path"]) == shadow_hugo
    assert shadow_archive.exists()
    assert shadow_preview.exists()
    assert shadow_hugo.exists()
    assert shadow_log.exists()


def test_compare_shadow_run_writes_markdown_and_json_report(tmp_path):
    legacy_archive = tmp_path / "legacy" / "2026-05-19.md"
    legacy_archive.parent.mkdir(parents=True)
    legacy_archive.write_text(
        "# 新闻雷达｜2026-05-19\n\n"
        "## 08:00 早间版\n\n"
        "<!-- briefing_id: 2026-05-19-08 -->\n\n"
        "### 1｜Agent copilots ship for developers\n\n"
        "- item_id: legacy-001\n"
        "- source: Working Feed\n"
        "- url: https://example.com/story\n"
        "- tags: [AI Agent, Tooling]\n\n"
        "摘要：Original archive item.\n\n"
        "### 2｜Broken source placeholder\n\n"
        "- source: Broken Feed\n"
        "- url: https://example.com/broken\n"
        "- tags: [error]\n"
        "- status: error\n"
        "- error: upstream 500\n\n"
        "摘要：Fetch failed.\n\n"
        "## 13:00 午间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 20:00 晚间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 今日沉淀\n\n"
        "- 趋势：保持观察\n",
        encoding="utf-8",
    )

    shadow_dir = tmp_path / "shadow"
    jsonl_path = shadow_dir / "data" / "runs" / "2026-05-19-08.jsonl"
    jsonl_path.parent.mkdir(parents=True)
    jsonl_rows = [
        {
            "briefing_id": "2026-05-19-08",
            "item_id": "shadow-001",
            "source": "Working Feed",
            "title": "Agent copilots ship for developers",
            "url": "https://example.com/story",
            "tags": ["AI Agent"],
            "topic": "AI Agent",
            "status": "ok",
            "error": "",
        },
        {
            "briefing_id": "2026-05-19-08",
            "item_id": "shadow-002",
            "source": "Working Feed",
            "title": "Agent copilots ship for developers",
            "url": "https://example.com/story",
            "tags": ["AI Agent", "Tooling"],
            "topic": "AI Agent",
            "status": "ok",
            "error": "",
        },
        {
            "briefing_id": "2026-05-19-08",
            "item_id": "",
            "source": "Shadow Broken",
            "title": "Shadow fetch failure",
            "url": "https://example.com/shadow-broken",
            "tags": ["error"],
            "status": "error",
            "error": "timeout",
        },
    ]
    jsonl_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in jsonl_rows), encoding="utf-8")

    manifest_path = shadow_dir / "data" / "runs" / "2026-05-19-08.json"
    manifest_path.write_text(
        json.dumps(
            {
                "briefing_id": "2026-05-19-08",
                "slot": "morning",
                "jsonl_output": str(jsonl_path),
                "error_count": 1,
                "errors": [
                    {
                        "source": "Shadow Broken",
                        "url": "https://example.com/shadow-broken",
                        "error": "timeout",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    report = compare_shadow_run(legacy_archive_path=legacy_archive, shadow_manifest_path=manifest_path)

    payload = json.loads(Path(report.json_path).read_text(encoding="utf-8"))
    markdown = Path(report.markdown_path).read_text(encoding="utf-8")

    assert payload["legacy"]["item_count"] == 2
    assert payload["shadow"]["item_count"] == 3
    assert payload["legacy"]["missing_item_ids"]["count"] == 1
    assert payload["shadow"]["missing_item_ids"]["count"] == 1
    assert payload["shadow"]["duplicate_count"] == 1
    assert payload["shadow"]["duplicate_rate"] == pytest.approx(1 / 3)
    assert payload["legacy"]["failed_sources"][0]["source"] == "Broken Feed"
    assert payload["shadow"]["failed_sources"][0]["source"] == "Shadow Broken"
    assert payload["legacy"]["topic_counts"] == {"AI Agent": 1, "error": 1}
    assert payload["shadow"]["source_counts"] == {"Shadow Broken": 1, "Working Feed": 2}
    assert "## Item counts" in markdown
    assert "## Topic distribution" in markdown
    assert "## Failed sources" in markdown


def test_compare_shadow_run_rejects_legacy_embedded_briefing_id_mismatch(tmp_path):
    legacy_archive = tmp_path / "legacy" / "2026-05-20.md"
    legacy_archive.parent.mkdir(parents=True)
    legacy_archive.write_text(
        "# 新闻雷达｜2026-05-20\n\n"
        "## 08:00 早间版\n\n"
        "<!-- briefing_id: 2026-05-20-13 -->\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 13:00 午间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 20:00 晚间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 今日沉淀\n\n"
        "- 趋势：保持观察\n",
        encoding="utf-8",
    )
    manifest_path = _write_shadow_manifest(tmp_path / "shadow", briefing_id="2026-05-20-08")

    with pytest.raises(ValueError, match="legacy archive .* briefing_id .* does not match manifest briefing_id"):
        compare_shadow_run(legacy_archive_path=legacy_archive, shadow_manifest_path=manifest_path)


def test_compare_shadow_run_rejects_conflicting_slot_override(tmp_path):
    legacy_archive = tmp_path / "legacy" / "2026-05-19.md"
    legacy_archive.parent.mkdir(parents=True)
    legacy_archive.write_text(
        "# 新闻雷达｜2026-05-19\n\n"
        "## 08:00 早间版\n\n"
        "<!-- briefing_id: 2026-05-19-08 -->\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 13:00 午间版\n\n"
        "<!-- briefing_id: 2026-05-19-13 -->\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 20:00 晚间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 今日沉淀\n\n"
        "- 趋势：保持观察\n",
        encoding="utf-8",
    )
    shadow_dir = tmp_path / "shadow"
    jsonl_path = shadow_dir / "data" / "runs" / "2026-05-19-08.jsonl"
    jsonl_path.parent.mkdir(parents=True)
    jsonl_path.write_text(
        json.dumps(
            {
                "briefing_id": "2026-05-19-08",
                "item_id": "shadow-001",
                "source": "Working Feed",
                "title": "Agent copilots ship for developers",
                "url": "https://example.com/story",
                "tags": ["AI Agent"],
                "topic": "AI Agent",
                "status": "ok",
                "error": "",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path = shadow_dir / "data" / "runs" / "2026-05-19-08.json"
    manifest_path.write_text(
        json.dumps(
            {
                "briefing_id": "2026-05-19-08",
                "slot": "morning",
                "jsonl_output": str(jsonl_path),
                "error_count": 0,
                "errors": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="slot override.*manifest"):
        compare_shadow_run(
            legacy_archive_path=legacy_archive,
            shadow_manifest_path=manifest_path,
            slot="noon",
        )


def test_compare_shadow_run_includes_manifest_failures_missing_from_jsonl(tmp_path):
    legacy_archive = tmp_path / "legacy" / "2026-05-19.md"
    legacy_archive.parent.mkdir(parents=True)
    legacy_archive.write_text(
        "# 新闻雷达｜2026-05-19\n\n"
        "## 08:00 早间版\n\n"
        "<!-- briefing_id: 2026-05-19-08 -->\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 13:00 午间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 20:00 晚间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 今日沉淀\n\n"
        "- 趋势：保持观察\n",
        encoding="utf-8",
    )
    shadow_dir = tmp_path / "shadow"
    jsonl_path = shadow_dir / "data" / "runs" / "2026-05-19-08.jsonl"
    jsonl_path.parent.mkdir(parents=True)
    jsonl_path.write_text(
        json.dumps(
            {
                "briefing_id": "2026-05-19-08",
                "item_id": "shadow-001",
                "source": "Working Feed",
                "title": "Agent copilots ship for developers",
                "url": "https://example.com/story",
                "tags": ["AI Agent"],
                "topic": "AI Agent",
                "status": "ok",
                "error": "",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path = shadow_dir / "data" / "runs" / "2026-05-19-08.json"
    manifest_path.write_text(
        json.dumps(
            {
                "briefing_id": "2026-05-19-08",
                "slot": "morning",
                "jsonl_output": str(jsonl_path),
                "error_count": 1,
                "errors": [
                    {
                        "source": "Shadow Broken",
                        "url": "https://example.com/shadow-broken",
                        "error": "timeout",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    report = compare_shadow_run(legacy_archive_path=legacy_archive, shadow_manifest_path=manifest_path)

    payload = json.loads(Path(report.json_path).read_text(encoding="utf-8"))
    assert payload["shadow"]["failed_sources"] == [
        {
            "source": "Shadow Broken",
            "url": "https://example.com/shadow-broken",
            "error": "timeout",
        }
    ]


def test_compare_shadow_run_rejects_wrong_day_legacy_archive(tmp_path):
    legacy_archive = tmp_path / "legacy" / "2026-05-18.md"
    legacy_archive.parent.mkdir(parents=True)
    legacy_archive.write_text(
        "# 新闻雷达｜2026-05-18\n\n"
        "## 08:00 早间版\n\n"
        "<!-- briefing_id: 2026-05-18-08 -->\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 13:00 午间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 20:00 晚间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 今日沉淀\n\n"
        "- 趋势：保持观察\n",
        encoding="utf-8",
    )
    manifest_path = _write_shadow_manifest(tmp_path / "shadow", briefing_id="2026-05-19-08")

    with pytest.raises(ValueError, match="legacy archive.*2026-05-19"):
        compare_shadow_run(legacy_archive_path=legacy_archive, shadow_manifest_path=manifest_path)


def test_compare_shadow_run_rejects_missing_legacy_slot_section(tmp_path):
    legacy_archive = tmp_path / "legacy" / "2026-05-19.md"
    legacy_archive.parent.mkdir(parents=True)
    legacy_archive.write_text(
        "# 新闻雷达｜2026-05-19\n\n"
        "## 13:00 午间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 20:00 晚间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 今日沉淀\n\n"
        "- 趋势：保持观察\n",
        encoding="utf-8",
    )
    manifest_path = _write_shadow_manifest(tmp_path / "shadow", briefing_id="2026-05-19-08")

    with pytest.raises(ValueError, match="legacy archive.*missing.*08:00 早间版"):
        compare_shadow_run(legacy_archive_path=legacy_archive, shadow_manifest_path=manifest_path)


def test_compare_shadow_run_rejects_unparseable_legacy_slot_section(tmp_path):
    legacy_archive = tmp_path / "legacy" / "2026-05-19.md"
    legacy_archive.parent.mkdir(parents=True)
    legacy_archive.write_text(
        "# 新闻雷达｜2026-05-19\n\n"
        "## 08:00 早间版\n\n"
        "早安，小於。今天有几件事值得看，但这段内容既不是结构化归档，也没有编号条目。\n\n"
        "## 13:00 午间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 20:00 晚间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 今日沉淀\n\n"
        "- 趋势：保持观察\n",
        encoding="utf-8",
    )
    manifest_path = _write_shadow_manifest(tmp_path / "shadow", briefing_id="2026-05-19-08")

    with pytest.raises(ValueError, match="legacy archive.*unparseable"):
        compare_shadow_run(legacy_archive_path=legacy_archive, shadow_manifest_path=manifest_path)


def test_compare_shadow_run_parses_current_production_style_archive(tmp_path):
    legacy_archive = tmp_path / "legacy" / "2026-05-20.md"
    legacy_archive.parent.mkdir(parents=True)
    legacy_archive.write_text(
        "# 新闻雷达｜2026-05-20\n\n"
        "## 08:00 早间版\n\n"
        "早安，小於。今天只看三条：\n\n"
        "1. **Google I/O：搜索框变成全能 Agent 入口**\n"
        "   Google 发布/展示 Gemini 3.5，以及更主动的搜索体验。https://www.theverge.com/tech/934217/google-search-box-does-everything-ai-io-2026\n\n"
        "2. **OpenAI 采用 Google SynthID 做 AI 图片溯源**\n"
        "   OpenAI 将给图片接入 SynthID 水印和验证工具。https://openai.com/index/advancing-content-provenance/\n\n"
        "3. **CLI-Anything：让软件 Agent-Native**\n"
        "   GitHub Trending 项目主张把各种软件转成可被 CLI/Agent 调用的形态。https://github.com/HKUDS/CLI-Anything\n\n"
        "**项目灵感**：做一个家庭/工作个人数据代理层。\n\n"
        "## 13:00 午间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 20:00 晚间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 今日沉淀\n\n"
        "- 趋势：保持观察\n",
        encoding="utf-8",
    )
    manifest_path = _write_shadow_manifest(tmp_path / "shadow", briefing_id="2026-05-20-08")

    report = compare_shadow_run(legacy_archive_path=legacy_archive, shadow_manifest_path=manifest_path)

    payload = json.loads(Path(report.json_path).read_text(encoding="utf-8"))
    assert payload["legacy"]["item_count"] == 3
    assert payload["legacy"]["missing_item_ids"]["count"] == 3
    assert payload["legacy"]["missing_item_ids"]["titles"] == [
        "Google I/O：搜索框变成全能 Agent 入口",
        "OpenAI 采用 Google SynthID 做 AI 图片溯源",
        "CLI-Anything：让软件 Agent-Native",
    ]
    assert payload["legacy"]["duplicate_count"] == 0
    assert payload["legacy"]["source_counts"] == {}


def test_legacy_rows_for_slot_preserves_balanced_parentheses_in_prose_urls(tmp_path):
    legacy_archive = tmp_path / "legacy" / "2026-05-20.md"
    legacy_archive.parent.mkdir(parents=True)
    legacy_archive.write_text(
        "# 新闻雷达｜2026-05-20\n\n"
        "## 08:00 早间版\n\n"
        "早安，小於。今天只看一条：\n\n"
        "1. **Balanced URL keeps trailing parenthesis**\n"
        "   这条链接本身以右括号结尾。https://example.com/notes_(draft)\n\n"
        "**项目灵感**：保持观察。\n\n"
        "## 13:00 午间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 20:00 晚间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 今日沉淀\n\n"
        "- 趋势：保持观察\n",
        encoding="utf-8",
    )

    rows = _legacy_rows_for_slot(legacy_archive, "morning", manifest_briefing_id="2026-05-20-08")

    assert rows[0]["url"] == "https://example.com/notes_(draft)"


def test_compare_shadow_run_rejects_placeholder_slot_with_extra_content(tmp_path):
    legacy_archive = tmp_path / "legacy" / "2026-05-20.md"
    legacy_archive.parent.mkdir(parents=True)
    legacy_archive.write_text(
        "# 新闻雷达｜2026-05-20\n\n"
        "## 08:00 早间版\n\n"
        "<!-- briefing_id: 2026-05-20-08 -->\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "注：这段附加说明意味着 slot 不应被当作干净的空版次。\n\n"
        "## 13:00 午间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 20:00 晚间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 今日沉淀\n\n"
        "- 趋势：保持观察\n",
        encoding="utf-8",
    )
    manifest_path = _write_shadow_manifest(tmp_path / "shadow", briefing_id="2026-05-20-08")

    with pytest.raises(ValueError, match="legacy archive.*unparseable"):
        compare_shadow_run(legacy_archive_path=legacy_archive, shadow_manifest_path=manifest_path)


def test_legacy_rows_for_slot_keeps_digit_prefixed_detail_lines_inside_same_item(tmp_path):
    legacy_archive = tmp_path / "legacy" / "2026-05-20.md"
    legacy_archive.parent.mkdir(parents=True)
    legacy_archive.write_text(
        "# 新闻雷达｜2026-05-20\n\n"
        "## 08:00 早间版\n\n"
        "早安，小於。今天只看一条：\n\n"
        "1. **Digit-prefixed detail line stays in summary**\n"
        "   2026. 这是一条以数字开头的说明，不应被拆成新的新闻条目。\n"
        "   更多背景见：https://example.com/story\n\n"
        "**项目灵感**：保持观察。\n\n"
        "## 13:00 午间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 20:00 晚间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 今日沉淀\n\n"
        "- 趋势：保持观察\n",
        encoding="utf-8",
    )

    rows = _legacy_rows_for_slot(legacy_archive, "morning", manifest_briefing_id="2026-05-20-08")

    assert len(rows) == 1
    assert rows[0]["title"] == "Digit-prefixed detail line stays in summary"
    assert rows[0]["url"] == "https://example.com/story"
    assert "2026. 这是一条以数字开头的说明" in rows[0]["summary"]
