import json
from pathlib import Path

import yaml

from newsroom.editor import CuratedBriefing, CuratedItem
from newsroom.publisher import export_curated_briefing_to_hugo


def _sample_curated_briefing() -> CuratedBriefing:
    return CuratedBriefing(
        briefing_id="2026-05-19-13",
        slot="noon",
        slot_label="13:00 午间版",
        generated_at="2026-05-19T00:10:00+00:00",
        editor_version="curated-v1",
        candidate_count=3,
        curated_item_count=2,
        today_signals=["AI Agent 相关信号在本版中最集中，适合优先跟踪后续产品化与工作流变化。"],
        items=[
            CuratedItem(
                briefing_id="2026-05-19-13",
                item_id="2026-05-19-13-001",
                rank=1,
                title="Agent copilots ship for developers",
                source="Working Feed",
                url="https://example.com/story",
                published="2026-05-19T00:30:00+00:00",
                tags=["AI Agent", "Tooling"],
                topic="AI Agent",
                rewritten_summary="A new agent workflow shipped.",
                why_relevant="Useful for project inspiration and workflow evaluation.",
                action_or_observe="行动：跟进 Agent copilots ship for developers 的产品页、源码或发布说明，判断是否值得纳入现有工具链。",
                selection_reason="Strong fit for AI agent tracking.",
                feedback_metadata={
                    "briefing_id": "2026-05-19-13",
                    "item_id": "2026-05-19-13-001",
                    "source": "Working Feed",
                    "tags": ["AI Agent", "Tooling"],
                    "topic": "AI Agent",
                    "channel": "site",
                },
            ),
            CuratedItem(
                briefing_id="2026-05-19-13",
                item_id="2026-05-19-13-002",
                rank=2,
                title="Robotics retail pilots expand",
                source="Noon Feed",
                url="https://example.com/noon",
                published="2026-05-19T01:30:00+00:00",
                tags=["Robotics"],
                topic="Robotics",
                rewritten_summary="Pilots expanded.",
                why_relevant="Tracks commercialization signals.",
                action_or_observe="观察：继续跟踪 Robotics retail pilots expand 的部署规模、付费客户与复购节奏，判断是否进入规模化。",
                selection_reason="Broadens topic diversity.",
                feedback_metadata={
                    "briefing_id": "2026-05-19-13",
                    "item_id": "2026-05-19-13-002",
                    "source": "Noon Feed",
                    "tags": ["Robotics"],
                    "topic": "Robotics",
                    "channel": "site",
                },
            ),
        ],
        feedback_items=[
            {
                "slot": "noon",
                "briefing_id": "2026-05-19-13",
                "item_id": "2026-05-19-13-001",
                "source": "Working Feed",
                "url": "https://example.com/story",
                "tags": ["AI Agent", "Tooling"],
                "topic": "AI Agent",
                "channel": "site",
                "title": "Agent copilots ship for developers",
                "summary": "A new agent workflow shipped.",
                "why_relevant": "Useful for project inspiration and workflow evaluation.",
                "action_or_observe": "行动：跟进 Agent copilots ship for developers 的产品页、源码或发布说明，判断是否值得纳入现有工具链。",
            },
            {
                "slot": "noon",
                "briefing_id": "2026-05-19-13",
                "item_id": "2026-05-19-13-002",
                "source": "Noon Feed",
                "url": "https://example.com/noon",
                "tags": ["Robotics"],
                "topic": "Robotics",
                "channel": "site",
                "title": "Robotics retail pilots expand",
                "summary": "Pilots expanded.",
                "why_relevant": "Tracks commercialization signals.",
                "action_or_observe": "观察：继续跟踪 Robotics retail pilots expand 的部署规模、付费客户与复购节奏，判断是否进入规模化。",
            },
        ],
        warnings=[],
    )


def test_export_curated_briefing_to_hugo_preserves_item_level_metadata(tmp_path):
    archive_path = tmp_path / "archive" / "2026-05-19.md"
    output_path = tmp_path / "site" / "content" / "briefings" / "2026" / "2026-05-19.md"
    item_catalog_path = tmp_path / "data" / "item_catalog" / "2026" / "2026-05-19.jsonl"

    metadata = export_curated_briefing_to_hugo(
        briefing=_sample_curated_briefing(),
        output_path=output_path,
        archive_path=archive_path,
        briefing_day="2026-05-19",
        timezone_name="Asia/Shanghai",
        item_catalog_path=item_catalog_path,
    )

    archive_text = archive_path.read_text(encoding="utf-8")
    text = output_path.read_text(encoding="utf-8")
    _, front_matter_text, body = text.split("---\n", 2)
    front_matter = yaml.safe_load(front_matter_text)
    item_catalog_rows = [json.loads(line) for line in item_catalog_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert metadata["item_count"] == 2
    assert "今日信号：" in archive_text
    assert "- why_relevant: Useful for project inspiration and workflow evaluation." in archive_text
    assert "- action_or_observe: 行动：跟进 Agent copilots ship for developers 的产品页、源码或发布说明，判断是否值得纳入现有工具链。" in archive_text
    assert front_matter["feedback_ui_enabled"] is False
    assert front_matter["feedback_items"][0]["why_relevant"] == "Useful for project inspiration and workflow evaluation."
    assert front_matter["feedback_items"][0]["action_or_observe"] == "行动：跟进 Agent copilots ship for developers 的产品页、源码或发布说明，判断是否值得纳入现有工具链。"
    assert front_matter["feedback_items"][0]["channel"] == "site"
    assert "今日信号：" in body
    assert "为什么相关：Useful for project inspiration and workflow evaluation." in body
    assert "行动建议：行动：跟进 Agent copilots ship for developers 的产品页、源码或发布说明，判断是否值得纳入现有工具链。" in body
    assert "{{< item-feedback" not in body
    assert item_catalog_rows == [
        {
            "briefing_day": "2026-05-19",
            "slot": "noon",
            "slot_label": "13:00 午间版",
            "briefing_id": "2026-05-19-13",
            "item_id": "2026-05-19-13-001",
            "title": "Agent copilots ship for developers",
            "source": "Working Feed",
            "url": "https://example.com/story",
            "tags": ["AI Agent", "Tooling"],
            "topic": "AI Agent",
            "summary": "A new agent workflow shipped.",
            "why_relevant": "Useful for project inspiration and workflow evaluation.",
            "action_or_observe": "行动：跟进 Agent copilots ship for developers 的产品页、源码或发布说明，判断是否值得纳入现有工具链。",
            "published": "2026-05-19T00:30:00+00:00",
        },
        {
            "briefing_day": "2026-05-19",
            "slot": "noon",
            "slot_label": "13:00 午间版",
            "briefing_id": "2026-05-19-13",
            "item_id": "2026-05-19-13-002",
            "title": "Robotics retail pilots expand",
            "source": "Noon Feed",
            "url": "https://example.com/noon",
            "tags": ["Robotics"],
            "topic": "Robotics",
            "summary": "Pilots expanded.",
            "why_relevant": "Tracks commercialization signals.",
            "action_or_observe": "观察：继续跟踪 Robotics retail pilots expand 的部署规模、付费客户与复购节奏，判断是否进入规模化。",
            "published": "2026-05-19T01:30:00+00:00",
        },
    ]


def test_export_curated_briefing_to_hugo_renders_original_title_as_metadata(tmp_path):
    archive_path = tmp_path / "archive" / "2026-05-19.md"
    output_path = tmp_path / "site" / "content" / "briefings" / "2026" / "2026-05-19.md"
    item_catalog_path = tmp_path / "data" / "item_catalog" / "2026" / "2026-05-19.jsonl"
    briefing = _sample_curated_briefing()
    briefing.items[0].original_title = "Agent copilots ship for developers"
    briefing.items[0].title = "面向开发者的 Agent 副驾驶已上线"
    briefing.feedback_items[0]["title"] = briefing.items[0].title
    briefing.feedback_items[0]["original_title"] = briefing.items[0].original_title
    briefing.feedback_items[0]["display_action_or_observe"] = "行动：跟进 面向开发者的 Agent 副驾驶已上线 的产品页、源码或发布说明，判断是否值得纳入现有工具链。"

    export_curated_briefing_to_hugo(
        briefing=briefing,
        output_path=output_path,
        archive_path=archive_path,
        briefing_day="2026-05-19",
        timezone_name="Asia/Shanghai",
        item_catalog_path=item_catalog_path,
    )

    text = output_path.read_text(encoding="utf-8")
    _, front_matter_text, body = text.split("---\n", 2)
    front_matter = yaml.safe_load(front_matter_text)
    item_catalog_rows = [json.loads(line) for line in item_catalog_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert "### 1｜面向开发者的 Agent 副驾驶已上线" in body
    assert "行动建议：行动：跟进 面向开发者的 Agent 副驾驶已上线 的产品页、源码或发布说明，判断是否值得纳入现有工具链。" in body
    assert "Agent copilots ship for developers" not in body
    assert front_matter["feedback_items"][0]["title"] == "面向开发者的 Agent 副驾驶已上线"
    assert front_matter["feedback_items"][0]["original_title"] == "Agent copilots ship for developers"
    assert front_matter["feedback_items"][0]["display_action_or_observe"] == "行动：跟进 面向开发者的 Agent 副驾驶已上线 的产品页、源码或发布说明，判断是否值得纳入现有工具链。"
    assert item_catalog_rows[0]["title"] == "面向开发者的 Agent 副驾驶已上线"
    assert item_catalog_rows[0]["original_title"] == "Agent copilots ship for developers"
    assert item_catalog_rows[0]["display_action_or_observe"] == "行动：跟进 面向开发者的 Agent 副驾驶已上线 的产品页、源码或发布说明，判断是否值得纳入现有工具链。"


def test_export_curated_briefing_to_hugo_ignores_existing_archive_text(tmp_path):
    archive_path = tmp_path / "archive" / "2026-05-19.md"
    output_path = tmp_path / "site" / "content" / "briefings" / "2026" / "2026-05-19.md"
    item_catalog_path = tmp_path / "data" / "item_catalog" / "2026" / "2026-05-19.jsonl"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_text(
        "# 新闻雷达｜2026-05-19\n\n"
        "## 08:00 早间版\n\n"
        "<!-- briefing_id: 2026-05-19-08 -->\n\n"
        "### 1｜Legacy morning item\n\n"
        "- item_id: 2026-05-19-08-001\n"
        "- source: Old Feed\n"
        "- url: https://example.com/legacy-morning\n\n"
        "摘要：Should not appear in curated Hugo export.\n\n"
        "## 13:00 午间版\n\n"
        "<!-- briefing_id: 2026-05-19-13 -->\n\n"
        "### 1｜Legacy noon item\n\n"
        "- item_id: 2026-05-19-13-001\n"
        "- source: Old Feed\n"
        "- url: https://example.com/legacy-noon-1\n\n"
        "摘要：Should not appear in curated Hugo export.\n\n"
        "### 70｜Legacy noon item 70\n\n"
        "- item_id: 2026-05-19-13-070\n"
        "- source: Old Feed\n"
        "- url: https://example.com/legacy-noon-70\n\n"
        "摘要：Should not appear in curated Hugo export.\n\n"
        "## 20:00 晚间版\n\n"
        "_本版次暂无候选新闻。_\n\n"
        "## 今日沉淀\n\n"
        "- 趋势：旧版候选归档沉淀\n",
        encoding="utf-8",
    )

    metadata = export_curated_briefing_to_hugo(
        briefing=_sample_curated_briefing(),
        output_path=output_path,
        archive_path=archive_path,
        briefing_day="2026-05-19",
        timezone_name="Asia/Shanghai",
        item_catalog_path=item_catalog_path,
    )

    text = output_path.read_text(encoding="utf-8")
    _, front_matter_text, body = text.split("---\n", 2)
    front_matter = yaml.safe_load(front_matter_text)

    assert metadata["item_count"] == 2
    assert front_matter["feedback_ui_enabled"] is False
    assert front_matter["item_count"] == 2
    assert front_matter["item_ids"] == ["2026-05-19-13-001", "2026-05-19-13-002"]
    assert body.count('<section class="news-item-card"') == 2
    assert "Agent copilots ship for developers" in body
    assert "Robotics retail pilots expand" in body
    assert "Legacy morning item" not in body
    assert "Legacy noon item" not in body
    assert "Legacy noon item 70" not in body
    assert "Should not appear in curated Hugo export." not in body
    assert "{{< item-feedback" not in body


def test_export_curated_briefing_to_hugo_can_reenable_feedback_ui(tmp_path):
    archive_path = tmp_path / "archive" / "2026-05-19.md"
    output_path = tmp_path / "site" / "content" / "briefings" / "2026" / "2026-05-19.md"

    metadata = export_curated_briefing_to_hugo(
        briefing=_sample_curated_briefing(),
        output_path=output_path,
        archive_path=archive_path,
        briefing_day="2026-05-19",
        timezone_name="Asia/Shanghai",
        include_feedback_ui=True,
    )

    text = output_path.read_text(encoding="utf-8")
    _, front_matter_text, body = text.split("---\n", 2)
    front_matter = yaml.safe_load(front_matter_text)

    assert metadata["item_count"] == 2
    assert front_matter["feedback_ui_enabled"] is True
    assert '{{< item-feedback briefing_id="2026-05-19-13" item_id="2026-05-19-13-001" source="Working Feed" tags="AI Agent,Tooling" >}}' in body
