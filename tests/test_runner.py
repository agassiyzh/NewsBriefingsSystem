import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

from newsroom import runner as runner_module
from newsroom.runner import run_briefing
from newsroom.auto_publish import (
    PublishError,
    build_git_command_env,
    changed_briefing_files,
    default_commit_message,
    ensure_feedback_ui_absent,
    git_push_preflight,
    load_github_token_from_hosts,
    parse_git_status_porcelain,
)


def _write_phase1_configs(base_dir: Path, archive_dir: Path, *, default_language: str | None = None) -> Path:
    system_dir = base_dir / "system"
    config_dir = system_dir / "config"
    config_dir.mkdir(parents=True)

    system_config = {
        "timezone": "Asia/Shanghai",
        "archive_dir": str(archive_dir),
        "system_dir": str(system_dir),
    }
    if default_language is not None:
        system_config["default_language"] = default_language

    newsroom_config = {
        "system": system_config,
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
    config_dir = _write_phase1_configs(tmp_path, archive_dir, default_language=None)
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
    config_dir = _write_phase1_configs(tmp_path, archive_dir, default_language=None)
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
    assert "1｜Agent copilots ship for developers" in preview_text
    assert "链接：https://example.com/story" in preview_text
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
            "summary": "Agent copilots ship for developers：聚焦A new agent workflow shipped。",
            "published": "2026-05-19T00:30:00+00:00",
            "why_relevant": "这条更新与代理工作流、开发工具和项目灵感直接相关，适合继续跟进。",
            "action_or_observe": "行动：跟进Agent copilots ship for developers的产品页、源码或发布说明，判断是否值得纳入现有工具链。",
        }
    ]


def test_run_briefing_exports_hugo_before_generating_compact_telegram_preview(tmp_path, monkeypatch):
    archive_dir = tmp_path / "archive"
    config_dir = _write_phase1_configs(tmp_path, archive_dir, default_language=None)

    newsroom_path = str((config_dir / "newsroom.yaml").resolve())
    config = yaml.safe_load(Path(newsroom_path).read_text(encoding="utf-8"))
    config["publication"] = {
        "public_site_base_url": "https://www.yuzhuohui.info/NewsBriefingsSystem/",
        "hugo_export_enabled": True,
    }
    Path(newsroom_path).write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    call_order: list[str] = []

    from newsroom import runner as runner_module

    original_hugo_publish = runner_module.HugoExportPublisher.publish
    original_telegram_publish = runner_module.TelegramPublisher.publish

    def tracking_hugo_publish(self, context):
        call_order.append("hugo_export")
        return original_hugo_publish(self, context)

    def tracking_telegram_publish(self, context):
        call_order.append("telegram")
        return original_telegram_publish(self, context)

    monkeypatch.setattr(runner_module.HugoExportPublisher, "publish", tracking_hugo_publish)
    monkeypatch.setattr(runner_module.TelegramPublisher, "publish", tracking_telegram_publish)

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
    preview_text = Path(manifest["publication"]["telegram"]["output_path"]).read_text(encoding="utf-8")

    assert call_order[-2:] == ["hugo_export", "telegram"]
    assert "本版精选 1 条。" in preview_text
    assert "今日信号：" in preview_text
    assert "完整简报：https://www.yuzhuohui.info/NewsBriefingsSystem/briefings/2026/2026-05-19/" in preview_text
    assert "GitHub Pages" not in preview_text
    assert "1｜Agent copilots ship for developers" not in preview_text


def test_run_briefing_uses_config_timezone_for_briefing_id(tmp_path):
    archive_dir = tmp_path / "archive"
    config_dir = _write_phase1_configs(tmp_path, archive_dir, default_language=None)

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


def test_parse_git_status_porcelain_filters_to_briefing_markdown_and_rejects_deletions():
    changed = parse_git_status_porcelain(
        " M site/content/briefings/2026/2026-05-21.md\n"
        "?? site/content/briefings/2026/2026-05-22.md\n"
        " M docs/final-architecture-and-ops.md\n"
    )

    assert changed == [
        "site/content/briefings/2026/2026-05-21.md",
        "site/content/briefings/2026/2026-05-22.md",
    ]

    try:
        parse_git_status_porcelain(" D site/content/briefings/2026/2026-05-20.md\n")
    except PublishError as exc:
        assert "deleted briefing content" in str(exc)
    else:
        raise AssertionError("expected deleted briefing content to raise PublishError")


def test_changed_briefing_files_reads_repo_status(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo, check=True, capture_output=True, text=True)

    target = repo / "site" / "content" / "briefings" / "2026"
    target.mkdir(parents=True)
    tracked = target / "2026-05-21.md"
    tracked.write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", tracked.as_posix()], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=repo, check=True, capture_output=True, text=True)

    tracked.write_text("updated\n", encoding="utf-8")
    (target / "2026-05-22.md").write_text("new\n", encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "note.md").write_text("ignore\n", encoding="utf-8")

    assert changed_briefing_files(repo) == [
        "site/content/briefings/2026/2026-05-21.md",
        "site/content/briefings/2026/2026-05-22.md",
    ]


def test_default_commit_message_lists_sorted_briefing_days():
    assert default_commit_message(["2026-05-22", "2026-05-21", "2026-05-22"]) == (
        "publish: update briefings 2026-05-21, 2026-05-22"
    )


def test_ensure_feedback_ui_absent_allows_page_metadata_but_rejects_feedback_controls(tmp_path):
    html_path = tmp_path / "briefing.html"
    html_path.write_text('<article data-feedback-page="briefing" data-briefing-day="2026-05-22"></article>', encoding="utf-8")
    ensure_feedback_ui_absent(html_path.read_text(encoding="utf-8"), html_path)

    html_path.write_text('<section class="item-feedback-widget"></section>', encoding="utf-8")
    try:
        ensure_feedback_ui_absent(html_path.read_text(encoding="utf-8"), html_path)
    except PublishError as exc:
        assert "feedback marker" in str(exc)
    else:
        raise AssertionError("expected feedback controls to raise PublishError")


def test_git_push_preflight_fails_before_commit_when_origin_is_unreachable(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/example/does-not-exist.git"], cwd=repo, check=True, capture_output=True, text=True)

    try:
        git_push_preflight(repo)
    except PublishError as exc:
        assert "git push preflight failed before creating commit" in str(exc)
    else:
        raise AssertionError("expected git push preflight to raise PublishError")


def test_load_github_token_from_hosts_reads_oauth_token(tmp_path):
    hosts_file = tmp_path / "hosts.yml"
    hosts_file.write_text(
        yaml.safe_dump(
            {
                "github.com": {
                    "user": "tester",
                    "oauth_token": "token-123",
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    assert load_github_token_from_hosts(hosts_file) == "token-123"


def test_build_git_command_env_adds_github_auth_header_without_exposing_raw_token():
    env = build_git_command_env("https://github.com/example/repo.git", github_token="token-123", base_env={})

    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert env["GIT_CONFIG_VALUE_0"].startswith("AUTHORIZATION: basic ")
    assert "token-123" not in env["GIT_CONFIG_VALUE_0"]


def test_run_briefing_localizes_curated_output_when_default_language_is_zh_cn(tmp_path, monkeypatch):
    archive_dir = tmp_path / "archive"
    config_dir = _write_phase1_configs(tmp_path, archive_dir, default_language="zh-CN")

    monkeypatch.setattr(
        runner_module,
        "build_candidate_translator",
        lambda default_language: (lambda text: {
            "Agent copilots ship for developers": "面向开发者的 Agent 副驾驶已上线",
            "A new agent workflow shipped.": "新的 Agent 工作流已经上线。",
        }.get(text, text)),
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
    curated_payload = json.loads(Path(manifest["curated_output"]).read_text(encoding="utf-8"))
    hugo_text = Path(manifest["publication"]["hugo_export"]["output_path"]).read_text(encoding="utf-8")
    _, front_matter_text, body = hugo_text.split("---\n", 2)
    front_matter = yaml.safe_load(front_matter_text)

    assert curated_payload["items"][0]["title"] == "面向开发者的 Agent 副驾驶已上线"
    assert curated_payload["items"][0]["original_title"] == "Agent copilots ship for developers"
    assert curated_payload["items"][0]["rewritten_summary"].startswith("面向开发者的 Agent 副驾驶已上线：")
    assert front_matter["feedback_items"][0]["original_title"] == "Agent copilots ship for developers"
    assert "Agent copilots ship for developers" not in body
    assert "面向开发者的 Agent 副驾驶已上线" in body
