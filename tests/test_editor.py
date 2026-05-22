from newsroom.collector import CollectResult
from newsroom.editor import compose_briefing


def _candidate(
    index: int,
    *,
    tag: str = "AI Agent",
    source: str = "Working Feed",
    title: str | None = None,
    snippet: str | None = None,
    url: str | None = None,
    tags: list[str] | None = None,
    keywords: list[str] | None = None,
) -> dict:
    return {
        "briefing_id": "2026-05-19-13",
        "item_id": f"2026-05-19-13-{index:03d}",
        "source": source,
        "title": title or f"Story {index}",
        "url": url or f"https://example.com/story-{index}",
        "published": "2026-05-19T00:30:00+00:00",
        "snippet": snippet if snippet is not None else f"Snippet for story {index} with concrete update.",
        "tags": tags if tags is not None else ([tag] if tag else []),
        "keywords": keywords if keywords is not None else ([tag.lower().split()[0]] if tag else []),
        "collected_at": "2026-05-19T00:05:00+00:00",
        "status": "ok",
        "error": "",
    }


def test_compose_briefing_selects_curated_subset_and_preserves_traceability():
    result = CollectResult(
        briefing_id="2026-05-19-13",
        collected_at="2026-05-19T00:05:00+00:00",
        candidates=[_candidate(index) for index in range(1, 16)],
        markdown="# 新闻候选上下文\n",
        error_count=0,
        errors=[],
    )

    briefing = compose_briefing(
        result,
        slot="noon",
        generated_at="2026-05-19T00:10:00+00:00",
        default_channel="site",
    )

    assert briefing.briefing_id == "2026-05-19-13"
    assert briefing.candidate_count == 15
    assert briefing.curated_item_count == 12
    assert [item.item_id for item in briefing.items] == [f"2026-05-19-13-{index:03d}" for index in range(1, 13)]
    assert briefing.feedback_items[0] == {
        "slot": "noon",
        "briefing_id": "2026-05-19-13",
        "item_id": "2026-05-19-13-001",
        "source": "Working Feed",
        "url": "https://example.com/story-1",
        "tags": ["AI Agent"],
        "topic": "AI Agent",
        "channel": "site",
        "title": "Story 1",
        "summary": briefing.items[0].rewritten_summary,
        "why_relevant": briefing.items[0].why_relevant,
        "action_or_observe": briefing.items[0].action_or_observe,
    }
    assert briefing.items[0].original_title == ""
    assert briefing.items[0].feedback_metadata == {
        "briefing_id": "2026-05-19-13",
        "item_id": "2026-05-19-13-001",
        "source": "Working Feed",
        "tags": ["AI Agent"],
        "topic": "AI Agent",
        "channel": "site",
    }


def test_compose_briefing_generates_today_signals_and_editor_fields():
    result = CollectResult(
        briefing_id="2026-05-19-13",
        collected_at="2026-05-19T00:05:00+00:00",
        candidates=[
            _candidate(1, tag="AI Agent"),
            _candidate(2, tag="Robotics", source="Factory Wire"),
            _candidate(3, tag="AI Agent"),
            _candidate(4, tag="Tooling", source="Dev Brief"),
        ],
        markdown="# 新闻候选上下文\n",
        error_count=0,
        errors=[],
    )

    briefing = compose_briefing(result, slot="noon", generated_at="2026-05-19T00:10:00+00:00")

    assert briefing.slot == "noon"
    assert briefing.slot_label == "13:00 午间版"
    assert briefing.editor_version == "curated-v1"
    assert briefing.today_signals == [
        "AI Agent 相关信号在本版中最集中，适合优先跟踪后续产品化与工作流变化。",
        "本版覆盖 3 个主题，可同时观察代理工具、机器人落地与开发者效率方向。",
        "可行动条目以项目/工具导向为主，适合继续追踪源码、产品页或团队发布节奏。",
    ]
    assert briefing.items[0].rewritten_summary != "Snippet for story 1 with concrete update."
    assert "Story 1" in briefing.items[0].rewritten_summary
    assert "concrete update" in briefing.items[0].rewritten_summary
    assert briefing.items[0].why_relevant == "这条更新与代理工作流、开发工具和项目灵感直接相关，适合继续跟进。"
    assert any(item.action_or_observe.startswith("行动：") for item in briefing.items)
    assert any(len(item.action_or_observe) > len("行动：") for item in briefing.items if item.action_or_observe.startswith("行动："))
    assert any(item.action_or_observe.startswith("观察：") for item in briefing.items)
    assert any(len(item.action_or_observe) > len("观察：") for item in briefing.items if item.action_or_observe.startswith("观察："))


def test_compose_briefing_rewrites_summary_without_copying_candidate_snippet():
    snippet = "OpenAI expands agent workflow for GitHub triage and repo updates."
    result = CollectResult(
        briefing_id="2026-05-19-13",
        collected_at="2026-05-19T00:05:00+00:00",
        candidates=[
            _candidate(
                1,
                title="OpenAI expands agent workflow",
                snippet=snippet,
                keywords=["OpenAI", "GitHub", "agent"],
            )
        ],
        markdown="# 新闻候选上下文\n",
        error_count=0,
        errors=[],
    )

    briefing = compose_briefing(result, slot="noon", generated_at="2026-05-19T00:10:00+00:00", default_channel="site")

    assert briefing.items[0].rewritten_summary != snippet
    assert "OpenAI" in briefing.items[0].rewritten_summary
    assert "GitHub" in briefing.items[0].rewritten_summary
    assert briefing.items[0].feedback_metadata["item_id"] == "2026-05-19-13-001"
    assert briefing.feedback_items[0]["summary"] == briefing.items[0].rewritten_summary


def test_compose_briefing_uses_translated_display_title_when_translator_provided():
    title = "Spotify Studio’s AI agent creates a daily podcast just for you"
    snippet = "Studio by Spotify Labs is a new standalone AI app that generates a daily briefing."
    result = CollectResult(
        briefing_id="2026-05-19-13",
        collected_at="2026-05-19T00:05:00+00:00",
        candidates=[
            _candidate(
                1,
                title=title,
                snippet=snippet,
                keywords=["Spotify", "agent", "podcast"],
            )
        ],
        markdown="# 新闻候选上下文\n",
        error_count=0,
        errors=[],
    )

    translations = {
        title: "Spotify Studio 的 AI 代理为你生成每日播客",
        snippet: "Spotify Labs 推出的 Studio 是一款独立 AI 应用，可生成每日简报。",
    }

    briefing = compose_briefing(
        result,
        slot="noon",
        generated_at="2026-05-19T00:10:00+00:00",
        default_channel="site",
        translator=lambda text: translations.get(text, text),
    )

    item = briefing.items[0]
    assert item.title == "Spotify Studio 的 AI 代理为你生成每日播客"
    assert item.original_title == title
    assert item.rewritten_summary.startswith("Spotify Studio 的 AI 代理为你生成每日播客：")
    assert "每日简报" in item.rewritten_summary
    assert item.action_or_observe.startswith("行动：跟进Spotify Studio 的 AI 代理为你生成每日播客")
    assert briefing.feedback_items[0]["title"] == item.title
    assert briefing.feedback_items[0]["original_title"] == title
    assert briefing.feedback_items[0]["display_action_or_observe"].startswith("行动：跟进Spotify Studio 的 AI 代理为你生成每日播客")


def test_compose_briefing_ranks_and_deduplicates_candidates_before_selection():
    low_signal_candidates = [
        _candidate(
            index,
            tag="",
            tags=[],
            keywords=[],
            title=f"Daily chatter {index}",
            snippet="General market chatter without a concrete launch, deployment, or customer signal.",
        )
        for index in range(3, 13)
    ]
    result = CollectResult(
        briefing_id="2026-05-19-13",
        collected_at="2026-05-19T00:05:00+00:00",
        candidates=[
            _candidate(
                1,
                title="Agent repo workflow ships",
                snippet="Agent repo workflow ships with a review queue and repo automation.",
                url="https://example.com/agent-workflow",
                keywords=["agent", "repo", "automation"],
            ),
            _candidate(
                2,
                title="Agent repo workflow ships",
                snippet="Agent repo workflow ships with a review queue and repo automation.",
                url="https://example.com/agent-workflow",
                keywords=["agent", "repo", "automation"],
            ),
            *low_signal_candidates,
            _candidate(
                13,
                tag="AI Agent",
                title="Open-source agent runtime lands",
                snippet="Open-source agent runtime lands with reproducible evals and a GitHub release.",
                keywords=["agent", "open-source", "GitHub"],
            ),
            _candidate(
                14,
                tag="Robotics",
                source="Factory Wire",
                title="Retail robot pilots expand",
                snippet="Retail robot pilots expand across 30 stores with new paying customers.",
                keywords=["robot", "retail", "customers"],
            ),
            _candidate(
                15,
                tag="Tooling",
                source="Dev Brief",
                title="Devtool adds repository copilots",
                snippet="Devtool adds repository copilots and benchmarking dashboards for engineering teams.",
                keywords=["copilots", "benchmarking", "engineering"],
            ),
        ],
        markdown="# 新闻候选上下文\n",
        error_count=0,
        errors=[],
    )

    briefing = compose_briefing(result, slot="noon", generated_at="2026-05-19T00:10:00+00:00", default_channel="site")

    selected_ids = [item.item_id for item in briefing.items]

    assert briefing.curated_item_count == 12
    assert "2026-05-19-13-002" not in selected_ids
    assert "2026-05-19-13-013" in selected_ids
    assert "2026-05-19-13-014" in selected_ids
    assert "2026-05-19-13-015" in selected_ids
    assert "2026-05-19-13-012" not in selected_ids
    selected_feedback = {item["item_id"]: item for item in briefing.feedback_items}
    assert selected_feedback["2026-05-19-13-013"]["briefing_id"] == "2026-05-19-13"
    assert selected_feedback["2026-05-19-13-013"]["channel"] == "site"
