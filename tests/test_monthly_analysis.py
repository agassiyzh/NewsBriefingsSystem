import csv
import json
import os
import subprocess
import sys
from pathlib import Path

from newsroom.monthly_analysis import analyze_month, load_catalog_rows, load_event_rows


ROOT = Path(__file__).resolve().parents[1]
MONTHLY_ANALYSIS_SCRIPT = ROOT / "scripts" / "monthly_analysis.py"


SAMPLE_EVENT_ROWS = [
    {
        "event_type": "impression",
        "channel": "site",
        "anonymous_id": "anon_a",
        "briefing_id": "2026-04-10-08",
        "item_id": "2026-04-10-08-001",
        "target_url": "https://example.com/agent-a",
        "duration_ms": 0,
        "metadata_json": {"source": "Example Feed", "tags": ["AI Agent", "Tooling"]},
        "created_at": "2026-04-10T00:00:00+00:00",
    },
    {
        "event_type": "click",
        "channel": "site",
        "anonymous_id": "anon_a",
        "briefing_id": "2026-04-10-08",
        "item_id": "2026-04-10-08-001",
        "target_url": "https://example.com/agent-a",
        "duration_ms": 0,
        "metadata_json": {"source": "Example Feed", "tags": ["AI Agent", "Tooling"]},
        "created_at": "2026-04-10T00:01:00+00:00",
    },
]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_load_event_rows_supports_csv_json_and_jsonl(tmp_path):
    csv_path = tmp_path / "events.csv"
    json_path = tmp_path / "events.json"
    jsonl_path = tmp_path / "events.jsonl"

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "event_type",
                "channel",
                "anonymous_id",
                "briefing_id",
                "item_id",
                "target_url",
                "duration_ms",
                "metadata_json",
                "created_at",
            ],
        )
        writer.writeheader()
        for row in SAMPLE_EVENT_ROWS:
            writer.writerow({**row, "metadata_json": json.dumps(row["metadata_json"], ensure_ascii=False)})

    json_path.write_text(json.dumps(SAMPLE_EVENT_ROWS, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_jsonl(jsonl_path, SAMPLE_EVENT_ROWS)

    for path in (csv_path, json_path, jsonl_path):
        loaded = load_event_rows([path])
        assert [row["event_type"] for row in loaded] == ["impression", "click"]
        assert loaded[0]["metadata_json"]["source"] == "Example Feed"
        assert loaded[0]["item_id"] == "2026-04-10-08-001"


def test_load_catalog_rows_supports_manifest_and_hugo_markdown(tmp_path):
    catalog_jsonl = tmp_path / "catalog.jsonl"
    manifest_path = tmp_path / "run-manifest.json"
    hugo_path = tmp_path / "site" / "content" / "briefings" / "2026" / "2026-04-10.md"

    _write_jsonl(
        catalog_jsonl,
        [
            {
                "briefing_id": "2026-04-10-08",
                "item_id": "2026-04-10-08-001",
                "source": "Manifest Feed",
                "title": "Manifest sourced AI story",
                "url": "https://example.com/manifest-story",
                "tags": ["AI Agent", "Tooling"],
                "topic": "AI Agent",
                "summary": "Manifest row summary.",
                "why_relevant": "Manifest row reason.",
            }
        ],
    )
    manifest_path.write_text(
        json.dumps(
            {
                "briefing_id": "2026-04-10-08",
                "slot": "morning",
                "jsonl_output": str(catalog_jsonl),
                "archive_path": str(tmp_path / "archive" / "2026-04-10.md"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    hugo_path.parent.mkdir(parents=True, exist_ok=True)
    hugo_path.write_text(
        "---\n"
        "title: 新闻雷达｜2026-04-10\n"
        "feedback_items:\n"
        "  - slot: noon\n"
        "    briefing_id: 2026-04-10-13\n"
        "    item_id: 2026-04-10-13-001\n"
        "    source: Hugo Feed\n"
        "    url: https://example.com/hugo-story\n"
        "    tags:\n"
        "      - Robotics\n"
        "---\n\n"
        "# 新闻雷达｜2026-04-10\n",
        encoding="utf-8",
    )

    loaded = load_catalog_rows([manifest_path, hugo_path])
    by_item_id = {row["item_id"]: row for row in loaded}

    assert set(by_item_id) == {"2026-04-10-08-001", "2026-04-10-13-001"}
    assert by_item_id["2026-04-10-08-001"]["source"] == "Manifest Feed"
    assert by_item_id["2026-04-10-13-001"]["tags"] == ["Robotics"]


def test_load_catalog_rows_prefers_manifest_item_catalog_output_path(tmp_path):
    raw_candidates_path = tmp_path / "candidates.jsonl"
    item_catalog_path = tmp_path / "data" / "item_catalog" / "2026-04-10.jsonl"
    manifest_path = tmp_path / "run-manifest.json"

    _write_jsonl(
        raw_candidates_path,
        [
            {
                "briefing_id": "2026-04-10-08",
                "item_id": "2026-04-10-08-001",
                "source": "Raw Candidate Feed",
                "title": "Raw candidate row",
                "url": "https://example.com/raw-candidate",
                "tags": ["Raw Candidate"],
                "summary": "Raw candidate summary.",
            }
        ],
    )
    _write_jsonl(
        item_catalog_path,
        [
            {
                "briefing_id": "2026-04-10-08",
                "item_id": "2026-04-10-08-001",
                "source": "Catalog Feed",
                "title": "Catalog normalized row",
                "url": "https://example.com/catalog-row",
                "tags": ["AI Agent", "Tooling"],
                "topic": "AI Agent",
                "summary": "Catalog summary.",
                "why_relevant": "Catalog reason.",
                "published": "2026-04-10T08:00:00+08:00",
            }
        ],
    )
    manifest_path.write_text(
        json.dumps(
            {
                "briefing_id": "2026-04-10-08",
                "slot": "morning",
                "jsonl_output": str(raw_candidates_path),
                "item_catalog": {
                    "status": "updated",
                    "output_path": str(item_catalog_path),
                    "item_count": 1,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    assert load_catalog_rows([manifest_path]) == [
        {
            "briefing_id": "2026-04-10-08",
            "item_id": "2026-04-10-08-001",
            "source": "Catalog Feed",
            "title": "Catalog normalized row",
            "url": "https://example.com/catalog-row",
            "tags": ["AI Agent", "Tooling"],
            "topic": "AI Agent",
            "summary": "Catalog summary.",
            "why_relevant": "Catalog reason.",
            "published_at": "2026-04-10T08:00:00+08:00",
            "source_path": str(manifest_path),
        }
    ]


def test_load_catalog_rows_uses_hugo_item_catalog_metadata_when_top_level_missing(tmp_path):
    raw_candidates_path = tmp_path / "candidates.jsonl"
    item_catalog_path = tmp_path / "site" / "data" / "item_catalog" / "2026-04-10.jsonl"
    manifest_path = tmp_path / "run-manifest.json"

    _write_jsonl(
        raw_candidates_path,
        [
            {
                "briefing_id": "2026-04-10-08",
                "item_id": "2026-04-10-08-001",
                "source": "Raw Candidate Feed",
                "title": "Raw candidate row",
                "url": "https://example.com/raw-candidate",
                "tags": ["Raw Candidate"],
                "summary": "Raw candidate summary.",
            }
        ],
    )
    _write_jsonl(
        item_catalog_path,
        [
            {
                "briefing_id": "2026-04-10-08",
                "item_id": "2026-04-10-08-001",
                "source": "Hugo Catalog Feed",
                "title": "Hugo catalog row",
                "url": "https://example.com/hugo-catalog-row",
                "tags": ["Robotics"],
                "summary": "Hugo catalog summary.",
                "why_relevant": "Hugo catalog reason.",
            }
        ],
    )
    manifest_path.write_text(
        json.dumps(
            {
                "briefing_id": "2026-04-10-08",
                "slot": "morning",
                "jsonl_output": str(raw_candidates_path),
                "publication": {
                    "hugo_export": {
                        "status": "updated",
                        "output_path": str(tmp_path / "site" / "content" / "briefings" / "2026" / "2026-04-10.md"),
                        "details": {
                            "item_catalog": {
                                "status": "updated",
                                "output_path": str(item_catalog_path),
                                "item_count": 1,
                            }
                        },
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    loaded = load_catalog_rows([manifest_path])

    assert loaded[0]["source"] == "Hugo Catalog Feed"
    assert loaded[0]["url"] == "https://example.com/hugo-catalog-row"
    assert loaded[0]["tags"] == ["Robotics"]


def test_load_catalog_rows_falls_back_to_jsonl_output_when_item_catalog_path_missing(tmp_path):
    raw_candidates_path = tmp_path / "candidates.jsonl"
    manifest_path = tmp_path / "run-manifest.json"

    _write_jsonl(
        raw_candidates_path,
        [
            {
                "briefing_id": "2026-04-10-08",
                "item_id": "2026-04-10-08-001",
                "source": "Raw Candidate Feed",
                "title": "Raw candidate row",
                "url": "https://example.com/raw-candidate",
                "tags": ["Raw Candidate"],
                "summary": "Raw candidate summary.",
            }
        ],
    )
    manifest_path.write_text(
        json.dumps(
            {
                "briefing_id": "2026-04-10-08",
                "slot": "morning",
                "jsonl_output": str(raw_candidates_path),
                "item_catalog": {
                    "status": "updated",
                    "output_path": str(tmp_path / "missing-item-catalog.jsonl"),
                    "item_count": 1,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    loaded = load_catalog_rows([manifest_path])

    assert loaded[0]["source"] == "Raw Candidate Feed"
    assert loaded[0]["url"] == "https://example.com/raw-candidate"
    assert loaded[0]["tags"] == ["Raw Candidate"]


def test_load_catalog_rows_falls_back_when_item_catalog_output_path_is_malformed(tmp_path):
    raw_candidates_path = tmp_path / "candidates.jsonl"
    manifest_path = tmp_path / "run-manifest.json"

    _write_jsonl(
        raw_candidates_path,
        [
            {
                "briefing_id": "2026-04-10-08",
                "item_id": "2026-04-10-08-001",
                "source": "Raw Candidate Feed",
                "title": "Raw candidate row",
                "url": "https://example.com/raw-candidate",
                "tags": ["Raw Candidate"],
                "summary": "Raw candidate summary.",
            }
        ],
    )
    manifest_path.write_text(
        json.dumps(
            {
                "briefing_id": "2026-04-10-08",
                "slot": "morning",
                "jsonl_output": str(raw_candidates_path),
                "item_catalog": {
                    "status": "updated",
                    "output_path": 123,
                    "item_count": 1,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    loaded = load_catalog_rows([manifest_path])

    assert loaded[0]["source"] == "Raw Candidate Feed"
    assert loaded[0]["url"] == "https://example.com/raw-candidate"
    assert loaded[0]["tags"] == ["Raw Candidate"]


def test_load_catalog_rows_falls_back_when_hugo_item_catalog_output_path_is_malformed(tmp_path):
    raw_candidates_path = tmp_path / "candidates.jsonl"
    manifest_path = tmp_path / "run-manifest.json"

    _write_jsonl(
        raw_candidates_path,
        [
            {
                "briefing_id": "2026-04-10-08",
                "item_id": "2026-04-10-08-001",
                "source": "Raw Candidate Feed",
                "title": "Raw candidate row",
                "url": "https://example.com/raw-candidate",
                "tags": ["Raw Candidate"],
                "summary": "Raw candidate summary.",
            }
        ],
    )
    manifest_path.write_text(
        json.dumps(
            {
                "briefing_id": "2026-04-10-08",
                "slot": "morning",
                "jsonl_output": str(raw_candidates_path),
                "publication": {
                    "hugo_export": {
                        "status": "updated",
                        "details": {
                            "item_catalog": {
                                "status": "updated",
                                "output_path": 123,
                                "item_count": 1,
                            }
                        },
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    loaded = load_catalog_rows([manifest_path])

    assert loaded[0]["source"] == "Raw Candidate Feed"
    assert loaded[0]["url"] == "https://example.com/raw-candidate"
    assert loaded[0]["tags"] == ["Raw Candidate"]


def test_load_catalog_rows_handles_non_mapping_publication_metadata(tmp_path):
    raw_candidates_path = tmp_path / "candidates.jsonl"
    manifest_path = tmp_path / "run-manifest.json"

    _write_jsonl(
        raw_candidates_path,
        [
            {
                "briefing_id": "2026-04-10-08",
                "item_id": "2026-04-10-08-001",
                "source": "Raw Candidate Feed",
                "title": "Raw candidate row",
                "url": "https://example.com/raw-candidate",
                "tags": ["Raw Candidate"],
                "summary": "Raw candidate summary.",
            }
        ],
    )
    manifest_path.write_text(
        json.dumps(
            {
                "briefing_id": "2026-04-10-08",
                "slot": "morning",
                "jsonl_output": str(raw_candidates_path),
                "publication": "unexpected-string",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    loaded = load_catalog_rows([manifest_path])

    assert loaded[0]["source"] == "Raw Candidate Feed"
    assert loaded[0]["url"] == "https://example.com/raw-candidate"


def test_analyze_month_keeps_distinct_missing_item_id_rows_by_url():
    catalog_rows = [
        {
            "briefing_id": "2026-04-10-08",
            "item_id": "",
            "source": "Example Feed",
            "title": "Agent workflow copilots land in customer support",
            "url": "https://example.com/agent-a",
            "tags": ["AI Agent", "Tooling"],
            "topic": "AI Agent",
            "summary": "Story A.",
            "why_relevant": "Reason A.",
            "published_at": "2026-04-10T08:00:00+08:00",
            "source_path": "test",
        },
        {
            "briefing_id": "2026-04-10-08",
            "item_id": "",
            "source": "Example Labs",
            "title": "Developer tooling teams ship eval pipelines for agents",
            "url": "https://example.com/agent-b",
            "tags": ["AI Agent", "Evaluation"],
            "topic": "AI Agent",
            "summary": "Story B.",
            "why_relevant": "Reason B.",
            "published_at": "2026-04-10T13:00:00+08:00",
            "source_path": "test",
        },
    ]
    event_rows = [
        {
            "event_type": "impression",
            "channel": "site",
            "anonymous_id": "anon-1",
            "briefing_id": "2026-04-10-08",
            "item_id": "",
            "target_url": "https://example.com/agent-a",
            "duration_ms": 0,
            "metadata_json": {"source": "Example Feed", "tags": ["AI Agent", "Tooling"]},
            "created_at": "2026-04-10T00:00:00+00:00",
        },
        {
            "event_type": "impression",
            "channel": "site",
            "anonymous_id": "anon-2",
            "briefing_id": "2026-04-10-08",
            "item_id": "",
            "target_url": "https://example.com/agent-b",
            "duration_ms": 0,
            "metadata_json": {"source": "Example Labs", "tags": ["AI Agent", "Evaluation"]},
            "created_at": "2026-04-10T01:00:00+00:00",
        },
    ]

    payload = analyze_month(
        month="2026-04",
        event_rows=event_rows,
        catalog_rows=catalog_rows,
        dry_run=False,
        input_paths={"events": [], "catalog": []},
    )

    item_rows = payload["dimensions"]["item"]
    topic_rows = payload["dimensions"]["topic"]

    assert len(item_rows) == 2
    assert {row["label"] for row in item_rows} == {
        "Agent workflow copilots land in customer support",
        "Developer tooling teams ship eval pipelines for agents",
    }
    assert {row["impressions"] for row in item_rows} == {1}
    assert {row["value"] for row in item_rows} == {
        "2026-04-10-08-uncatalogued-https-example-com-agent-a",
        "2026-04-10-08-uncatalogued-https-example-com-agent-b",
    }
    assert topic_rows[0]["items_published"] == 2
    assert topic_rows[0]["item_ids"] == [
        "2026-04-10-08-uncatalogued-https-example-com-agent-a",
        "2026-04-10-08-uncatalogued-https-example-com-agent-b",
    ]


def test_analyze_month_keeps_event_only_uncatalogued_items_distinct_by_url():
    event_rows = [
        {
            "event_type": "impression",
            "channel": "site",
            "anonymous_id": "anon-1",
            "briefing_id": "2026-04-10-08",
            "item_id": "",
            "target_url": "https://example.com/agent-a",
            "duration_ms": 0,
            "metadata_json": {"source": "Example Feed", "tags": ["AI Agent", "Tooling"]},
            "created_at": "2026-04-10T00:00:00+00:00",
        },
        {
            "event_type": "impression",
            "channel": "site",
            "anonymous_id": "anon-2",
            "briefing_id": "2026-04-10-08",
            "item_id": "",
            "target_url": "https://example.com/agent-b",
            "duration_ms": 0,
            "metadata_json": {"source": "Example Labs", "tags": ["AI Agent", "Evaluation"]},
            "created_at": "2026-04-10T01:00:00+00:00",
        },
    ]

    payload = analyze_month(
        month="2026-04",
        event_rows=event_rows,
        catalog_rows=[],
        dry_run=False,
        input_paths={"events": [], "catalog": []},
    )

    item_rows = payload["dimensions"]["item"]
    topic_rows = payload["dimensions"]["topic"]

    assert len(item_rows) == 2
    assert len({row["value"] for row in item_rows}) == 2
    assert {row["value"] for row in item_rows} == {
        "2026-04-10-08-uncatalogued-https-example-com-agent-a",
        "2026-04-10-08-uncatalogued-https-example-com-agent-b",
    }
    assert topic_rows[0]["items_published"] == 2
    assert topic_rows[0]["item_ids"] == [
        "2026-04-10-08-uncatalogued-https-example-com-agent-a",
        "2026-04-10-08-uncatalogued-https-example-com-agent-b",
    ]


def test_analyze_month_treats_naive_timestamps_as_local_timezone():
    payload = analyze_month(
        month="2026-04",
        event_rows=[
            {
                "event_type": "impression",
                "channel": "site",
                "anonymous_id": "anon-local",
                "briefing_id": "2026-04-30-20",
                "item_id": "2026-04-30-20-001",
                "target_url": "https://example.com/local-time",
                "duration_ms": 0,
                "metadata_json": {"source": "Local Feed", "tags": ["AI Agent"]},
                "created_at": "2026-04-30 23:30:00",
            }
        ],
        catalog_rows=[
            {
                "briefing_id": "2026-04-30-20",
                "item_id": "2026-04-30-20-001",
                "source": "Local Feed",
                "title": "Local timestamp story",
                "url": "https://example.com/local-time",
                "tags": ["AI Agent"],
                "topic": "AI Agent",
                "summary": "Local timestamp summary.",
                "why_relevant": "Should stay in April for Asia/Shanghai.",
                "published_at": "2026-04-30 20:00:00",
                "source_path": "test",
            }
        ],
        timezone_name="Asia/Shanghai",
        dry_run=False,
        input_paths={"events": [], "catalog": []},
    )

    assert payload["summary"]["event_rows"] == 1
    assert payload["totals"]["impressions"] == 1


def test_analyze_month_keeps_timezone_shifted_catalog_rows_in_target_month():
    payload = analyze_month(
        month="2026-04",
        event_rows=[
            {
                "event_type": "impression",
                "channel": "site",
                "anonymous_id": "anon-shifted",
                "briefing_id": "2026-04-01-08",
                "item_id": "2026-04-01-08-001",
                "target_url": "https://example.com/timezone-shifted",
                "duration_ms": 0,
                "metadata_json": {"source": "Timezone Feed", "tags": ["AI Agent"]},
                "created_at": "2026-04-01T00:30:00+00:00",
            }
        ],
        catalog_rows=[
            {
                "briefing_id": "2026-04-01-08",
                "item_id": "2026-04-01-08-001",
                "source": "Timezone Feed",
                "title": "Timezone shifted catalog story",
                "url": "https://example.com/timezone-shifted",
                "tags": ["AI Agent"],
                "topic": "AI Agent",
                "summary": "Catalog row should stay attached after timezone normalization.",
                "why_relevant": "Published timestamp is previous local date in another offset but same month in Asia/Shanghai.",
                "published_at": "2026-03-31T23:30:00-08:00",
                "source_path": "test",
            }
        ],
        timezone_name="Asia/Shanghai",
        dry_run=False,
        input_paths={"events": [], "catalog": []},
    )

    item_row = payload["dimensions"]["item"][0]
    assert payload["data_quality"]["uncatalogued_event_count"] == 0
    assert item_row["label"] == "Timezone shifted catalog story"
    assert item_row["summary"] == "Catalog row should stay attached after timezone normalization."


def test_analyze_month_does_not_fallback_to_single_item_editor_brief():
    payload = analyze_month(
        month="2026-04",
        event_rows=[
            {
                "event_type": "impression",
                "channel": "site",
                "anonymous_id": "anon-single",
                "briefing_id": "2026-04-20-08",
                "item_id": "2026-04-20-08-001",
                "target_url": "https://example.com/single-item",
                "duration_ms": 0,
                "metadata_json": {"source": "Single Feed", "tags": ["AI Agent"]},
                "created_at": "2026-04-20T00:00:00+00:00",
            },
            {
                "event_type": "click",
                "channel": "site",
                "anonymous_id": "anon-single",
                "briefing_id": "2026-04-20-08",
                "item_id": "2026-04-20-08-001",
                "target_url": "https://example.com/single-item",
                "duration_ms": 0,
                "metadata_json": {"source": "Single Feed", "tags": ["AI Agent"]},
                "created_at": "2026-04-20T00:05:00+00:00",
            },
        ],
        catalog_rows=[
            {
                "briefing_id": "2026-04-20-08",
                "item_id": "2026-04-20-08-001",
                "source": "Single Feed",
                "title": "Single item should stay evidence-only",
                "url": "https://example.com/single-item",
                "tags": ["AI Agent"],
                "topic": "AI Agent",
                "summary": "Single item summary.",
                "why_relevant": "Only one item exists this month.",
                "published_at": "2026-04-20T08:00:00+08:00",
                "source_path": "test",
            }
        ],
        dry_run=False,
        input_paths={"events": [], "catalog": []},
    )

    assert payload["dimensions"]["item"]
    assert payload["editor_brief"] == []


def test_monthly_analysis_cli_help_and_dry_run_write_outputs(tmp_path):
    help_process = subprocess.run(
        [sys.executable, str(MONTHLY_ANALYSIS_SCRIPT), "--help"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )

    assert "--month" in help_process.stdout
    assert "--dry-run" in help_process.stdout

    json_root = tmp_path / "data" / "monthly_insights"
    docs_root = tmp_path / "docs" / "monthly-insights"
    run_process = subprocess.run(
        [
            sys.executable,
            str(MONTHLY_ANALYSIS_SCRIPT),
            "--dry-run",
            "--month",
            "2026-04",
            "--output-root",
            str(json_root),
            "--docs-root",
            str(docs_root),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )

    json_path = json_root / "2026-04.json"
    markdown_path = docs_root / "2026-04.md"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")

    assert json_path.exists()
    assert markdown_path.exists()
    assert payload["month"] == "2026-04"
    assert payload["summary"]["dry_run"] is True
    assert payload["editor_brief"]
    assert all(brief["status"] == "pending_review" for brief in payload["editor_brief"])
    assert all(brief["dimension"] in {"topic", "source", "tag"} for brief in payload["editor_brief"])
    assert payload["editor_memory_workflow"]["owner"] == "editor_profile"
    assert payload["editor_memory_workflow"]["production_path"] == "editor_owned_memory_write"
    assert payload["editor_memory_workflow"]["repo_apply_supported"] is False
    assert "Reporter/Coder/Publisher 不直接写入长期编辑记忆" in payload["editor_memory_workflow"]["reason"]
    assert set(payload["dimensions"]) >= {"topic", "source", "tag", "item"}
    assert "# NewsBriefingsSystem 月度兴趣分析｜2026-04" in markdown
    assert "pending_review" in markdown
    assert "Editor recommendation brief" in markdown
    assert str(json_path) in run_process.stdout
    assert str(markdown_path) in run_process.stdout
    assert "editor_briefs=" in run_process.stdout


def test_monthly_analysis_cli_runs_against_committed_sample_files(tmp_path):
    sample_dir = ROOT / "sample-data" / "monthly-analysis" / "2026-04"
    json_root = tmp_path / "data" / "monthly_insights"
    docs_root = tmp_path / "docs" / "monthly-insights"

    process = subprocess.run(
        [
            sys.executable,
            str(MONTHLY_ANALYSIS_SCRIPT),
            "--month",
            "2026-04",
            "--events",
            str(sample_dir / "events.jsonl"),
            "--catalog",
            str(sample_dir / "catalog.jsonl"),
            str(sample_dir / "briefing.md"),
            "--output-root",
            str(json_root),
            "--docs-root",
            str(docs_root),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )

    payload = json.loads((json_root / "2026-04.json").read_text(encoding="utf-8"))
    markdown = (docs_root / "2026-04.md").read_text(encoding="utf-8")

    assert payload["summary"]["dry_run"] is False
    assert payload["inputs"]["events"] == [str(sample_dir / "events.jsonl")]
    assert payload["inputs"]["catalog"] == [str(sample_dir / "catalog.jsonl"), str(sample_dir / "briefing.md")]
    assert payload["editor_brief"]
    assert all(brief["status"] == "pending_review" for brief in payload["editor_brief"])
    assert all(brief["dimension"] in {"topic", "source", "tag"} for brief in payload["editor_brief"])
    assert "AI Agent" in json.dumps(payload["dimensions"]["topic"], ensure_ascii=False)
    assert "pending_review" in markdown
    assert "Editor recommendation brief" in markdown
    assert "数据质量与限制" in markdown
    assert "json=" in process.stdout
    assert "markdown=" in process.stdout


def test_repository_sample_json_uses_editor_brief_schema() -> None:
    for month in ("2026-04", "2026-05"):
        sample_path = ROOT / "data" / "monthly_insights" / f"{month}.json"
        payload = json.loads(sample_path.read_text(encoding="utf-8"))

        assert payload["summary"]["editor_brief_count"] == len(payload["editor_brief"])
        assert "recommendation_count" not in payload["summary"]
        assert "recommendations" not in payload
        assert "honcho_writeback" not in payload
        assert payload["editor_memory_workflow"]["owner"] == "editor_profile"
        assert payload["editor_memory_workflow"]["production_path"] == "editor_owned_memory_write"
        assert payload["editor_memory_workflow"]["repo_apply_supported"] is False
        assert all(brief["report_type"] == "editor_recommendation_brief" for brief in payload["editor_brief"])
        assert all(brief["dimension"] in {"topic", "source", "tag"} for brief in payload["editor_brief"])


def test_repository_sample_markdown_uses_editor_brief_boundary_wording() -> None:
    expected_boundary = "只可作为 Editor brief，不得视为仓库自动 apply 或直接写入 memory 的指令。"
    expected_item_limit = "item 维度仅保留为聚合证据与抽样校验，不会生成可直接迁移为长期偏好的单条新闻建议。"
    expected_review_guard = "单条新闻或一次性异常波动"
    stale_review_question = "该建议是否代表稳定 editorial preference，而非单月热点？"

    for month in ("2026-04", "2026-05"):
        markdown_path = ROOT / "docs" / "monthly-insights" / f"{month}.md"
        markdown = markdown_path.read_text(encoding="utf-8")

        assert expected_boundary in markdown
        assert expected_item_limit in markdown
        assert expected_review_guard in markdown
        assert stale_review_question not in markdown
