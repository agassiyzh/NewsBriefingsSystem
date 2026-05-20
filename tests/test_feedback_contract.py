from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

from newsroom.publisher import export_archive_to_hugo


ROOT = Path(__file__).resolve().parents[1]

SAMPLE_ARCHIVE = (
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
    "- 趋势：Agent workflow 更成熟\n"
)


def _write_site(tmp_path: Path) -> tuple[Path, Path]:
    site_dir = tmp_path / "site"
    content_path = site_dir / "content" / "briefings" / "2026" / "2026-05-19.md"
    archive_path = tmp_path / "archive" / "2026-05-19.md"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_text(SAMPLE_ARCHIVE, encoding="utf-8")
    export_archive_to_hugo(
        archive_path=archive_path,
        output_path=content_path,
        briefing_day="2026-05-19",
        timezone_name="Asia/Shanghai",
    )

    (site_dir / "hugo.toml").write_text((ROOT / "site" / "hugo.toml").read_text(encoding="utf-8"), encoding="utf-8")
    layouts_dir = site_dir / "layouts"
    layouts_dir.mkdir(parents=True)
    for source in (ROOT / "site" / "layouts").rglob("*"):
        if source.is_file():
            target = layouts_dir / source.relative_to(ROOT / "site" / "layouts")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    static_dir = site_dir / "static"
    static_dir.mkdir(parents=True)
    (static_dir / "feedback.js").write_text((ROOT / "site" / "static" / "feedback.js").read_text(encoding="utf-8"), encoding="utf-8")
    return site_dir, content_path


def _build_hugo(site_dir: Path, destination: Path, *extra_args: str) -> Path:
    command = [
        "npx",
        "-y",
        "hugo-bin",
        "--source",
        str(site_dir),
        "--destination",
        str(destination),
    ]
    command.extend(extra_args)
    subprocess.run(command, check=True, capture_output=True, text=True, cwd=ROOT)
    return destination / "briefings" / "2026" / "2026-05-19" / "index.html"


def test_feedback_export_front_matter_contains_item_mapping(tmp_path):
    _, content_path = _write_site(tmp_path)

    text = content_path.read_text(encoding="utf-8")
    _, front_matter_text, _ = text.split("---\n", 2)
    front_matter = yaml.safe_load(front_matter_text)

    assert front_matter["feedback_primary_briefing_id"] == "2026-05-19-08"
    assert front_matter["feedback_items"][0] == {
        "slot": "morning",
        "briefing_id": "2026-05-19-08",
        "item_id": "2026-05-19-08-001",
        "source": "Working Feed",
        "url": "https://example.com/story",
        "tags": ["AI Agent", "Tooling"],
    }


def test_hugo_build_succeeds_with_feedback_config_absent(tmp_path):
    site_dir, _ = _write_site(tmp_path)
    (site_dir / "hugo.toml").write_text(
        "baseURL = \"https://example.com/\"\n"
        "languageCode = \"zh-CN\"\n"
        "title = \"Personal Newsroom\"\n"
        "defaultContentLanguage = \"zh-cn\"\n"
        "enableRobotsTXT = true\n\n"
        "[params]\n"
        "  description = \"面向个人研究与项目灵感的 AI 新闻简报档案。\"\n",
        encoding="utf-8",
    )

    html_path = _build_hugo(site_dir, tmp_path / "public-absent")
    html = html_path.read_text(encoding="utf-8")

    assert "新闻雷达｜2026-05-19" in html
    assert '<section class="feedback-widget"' not in html
    assert "feedback.js" not in html
    assert "https://example.com/story" in html


def test_hugo_build_with_feedback_disabled_keeps_content_readable(tmp_path):
    site_dir, _ = _write_site(tmp_path)

    html_path = _build_hugo(site_dir, tmp_path / "public-disabled")
    html = html_path.read_text(encoding="utf-8")

    assert 'data-feedback-page="briefing"' in html
    assert 'data-briefing-id="2026-05-19-08"' in html
    assert '<section class="feedback-widget"' not in html
    assert "feedback.js" not in html
    assert 'href="https://example.com/story"' in html


def test_hugo_build_with_feedback_enabled_renders_widget_and_tracking_config(tmp_path):
    site_dir, _ = _write_site(tmp_path)
    (site_dir / "hugo.toml").write_text(
        (site_dir / "hugo.toml")
        .read_text(encoding="utf-8")
        .replace("enabled = false", "enabled = true")
        .replace('workerBaseUrl = ""', 'workerBaseUrl = "http://127.0.0.1:8787"')
        .replace("widgetEnabled = false", "widgetEnabled = true")
        .replace("trackLinks = false", "trackLinks = true")
        .replace("dwellEnabled = false", "dwellEnabled = true"),
        encoding="utf-8",
    )

    html_path = _build_hugo(site_dir, tmp_path / "public-enabled")
    html = html_path.read_text(encoding="utf-8")

    assert 'class="briefing-content"' in html
    assert 'class="news-item-card"' in html
    assert 'class="item-feedback-widget"' in html
    assert 'data-feedback-item-id="2026-05-19-08-001"' in html
    assert 'data-feedback-briefing-id="2026-05-19-08"' in html
    assert 'data-feedback-source="Working Feed"' in html
    assert 'data-feedback-tags="AI Agent,Tooling"' in html
    assert 'data-feedback-action="like"' in html
    assert 'data-feedback-action="dislike"' in html
    assert '<section class="item-feedback-list"' not in html
    assert '<section class="feedback-widget"' not in html

    item_heading = html.index('Agent copilots ship for developers')
    item_feedback = html.index('class="item-feedback-widget"', item_heading)
    next_item_heading = html.index('Robotics retail pilots expand')
    assert item_heading < item_feedback < next_item_heading
    assert "feedback.js" in html
    assert "newsroom-feedback-config" in html
    assert "newsroom-feedback-items" in html
    assert "http://127.0.0.1:8787" in html
    assert "https://example.com/story" in html

    config_marker = '<script id="newsroom-feedback-config" type="application/json">'
    config_start = html.index(config_marker) + len(config_marker)
    config_end = html.index("</script>", config_start)
    config_payload = json.loads(html[config_start:config_end])
    assert config_payload["workerBaseUrl"] == "http://127.0.0.1:8787"
    assert config_payload["widgetEnabled"] is True
    assert config_payload["trackLinks"] is True
    assert config_payload["dwellEnabled"] is True

    marker = '<script id="newsroom-feedback-items" type="application/json">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    payload = json.loads(html[start:end])
    assert payload[0]["item_id"] == "2026-05-19-08-001"
    assert payload[0]["url"] == "https://example.com/story"
