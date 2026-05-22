from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import re
from typing import Any, Callable

from .collector import CollectResult
from .ids import slot_label

EDITOR_VERSION = "curated-v1"
DEFAULT_SELECTED_MIN = 8
DEFAULT_SELECTED_MAX = 12
HIGH_SIGNAL_TERMS = (
    "agent",
    "agents",
    "automation",
    "automations",
    "benchmark",
    "benchmarks",
    "copilot",
    "copilots",
    "customer",
    "customers",
    "deployment",
    "deployments",
    "eval",
    "evals",
    "github",
    "launch",
    "launches",
    "open-source",
    "opensource",
    "release",
    "releases",
    "robot",
    "robots",
    "runtime",
    "runtimes",
    "ship",
    "ships",
    "shipped",
    "workflow",
    "workflows",
)
LOW_SIGNAL_PHRASES = (
    "general market chatter",
    "without a concrete",
    "no concrete signal",
    "speculation only",
)
ACTION_TOPICS = {"AI Agent", "Tooling"}


@dataclass(slots=True)
class CuratedItem:
    briefing_id: str
    item_id: str
    rank: int
    title: str
    source: str
    url: str
    published: str
    tags: list[str]
    topic: str
    rewritten_summary: str
    why_relevant: str
    action_or_observe: str
    selection_reason: str
    feedback_metadata: dict[str, Any]
    original_title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CuratedBriefing:
    briefing_id: str
    slot: str
    slot_label: str
    generated_at: str
    editor_version: str
    candidate_count: int
    curated_item_count: int
    today_signals: list[str]
    items: list[CuratedItem]
    feedback_items: list[dict[str, Any]]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "briefing_id": self.briefing_id,
            "slot": self.slot,
            "slot_label": self.slot_label,
            "generated_at": self.generated_at,
            "editor_version": self.editor_version,
            "candidate_count": self.candidate_count,
            "curated_item_count": self.curated_item_count,
            "today_signals": list(self.today_signals),
            "items": [item.to_dict() for item in self.items],
            "feedback_items": [dict(item) for item in self.feedback_items],
            "warnings": list(self.warnings),
        }


def _selected_count(candidate_count: int, *, minimum: int = DEFAULT_SELECTED_MIN, maximum: int = DEFAULT_SELECTED_MAX) -> int:
    if candidate_count <= 0:
        return 0
    if candidate_count < minimum:
        return candidate_count
    return min(candidate_count, maximum)


def _topic(candidate: dict[str, Any]) -> str:
    tags = [str(tag).strip() for tag in candidate.get("tags", []) if str(tag).strip()]
    return tags[0] if tags else "untagged"


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _strip_terminal_punctuation(text: str) -> str:
    return text.rstrip("。.!?！？；;，,：: ")


def _strip_title_prefix(snippet: str, title: str) -> str:
    if not snippet or not title:
        return snippet
    pattern = re.compile(rf"^{re.escape(title.strip())}[\s:：,，\-–—]*", re.IGNORECASE)
    stripped = pattern.sub("", snippet, count=1).strip()
    return stripped or snippet


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _translate_text(text: str, translator: Callable[[str], str] | None) -> str:
    normalized = str(text or "").strip()
    if not normalized or translator is None or _contains_cjk(normalized):
        return normalized
    translated = str(translator(normalized) or "").strip()
    return translated or normalized


def _localized_candidate(candidate: dict[str, Any], translator: Callable[[str], str] | None) -> dict[str, Any]:
    localized = dict(candidate)
    original_title = str(candidate.get("title", "") or "").strip()
    translated_title = _translate_text(original_title, translator)
    translated_snippet = _translate_text(candidate.get("snippet", ""), translator)
    localized["title"] = translated_title
    localized["snippet"] = translated_snippet
    if translated_title and translated_title != original_title:
        localized["original_title"] = original_title
    return localized


def _rewrite_summary(candidate: dict[str, Any]) -> str:
    title = str(candidate.get("title", "") or "").strip()
    snippet = str(candidate.get("snippet", "") or "").strip()
    if snippet:
        detail = _strip_terminal_punctuation(_strip_title_prefix(snippet, title))
        if title and detail and _normalized_text(detail) != _normalized_text(title):
            if detail.startswith(("聚焦", "关注", "围绕")):
                return f"{title}：{detail}。"
            return f"{title}：聚焦{detail}。"
        if title:
            return f"{title}：值得继续跟进。"
        return f"要点：{_strip_terminal_punctuation(snippet)}。"
    if title:
        return f"{title}：值得继续跟进。"
    return ""


def _why_relevant(candidate: dict[str, Any]) -> str:
    topic = _topic(candidate)
    if topic == "AI Agent":
        return "这条更新与代理工作流、开发工具和项目灵感直接相关，适合继续跟进。"
    if topic == "Robotics":
        return "这条更新提供了机器人商业化与线下落地的观察信号，值得持续跟踪。"
    return "这条更新与当前关注的项目方向和行业信号相关，适合纳入持续观察。"


def _action_or_observe(candidate: dict[str, Any]) -> str:
    topic = _topic(candidate)
    title = str(candidate.get("title", "") or "这条更新").strip() or "这条更新"
    if topic in ACTION_TOPICS:
        return f"行动：跟进{title}的产品页、源码或发布说明，判断是否值得纳入现有工具链。"
    if topic == "Robotics":
        return f"观察：继续跟踪{title}的部署规模、付费客户与复购节奏，判断是否进入规模化。"
    return f"观察：记录{title}后续是否出现新产品发布、用户采用或商业化信号。"


def _selection_reason(candidate: dict[str, Any]) -> str:
    topic = _topic(candidate)
    if topic == "AI Agent":
        return "代理工作流与工具链信号明确，适合作为本版优先跟进条目。"
    if topic == "Robotics":
        return "机器人部署与商业化信号更具体，适合作为落地观察样本。"
    if topic == "Tooling":
        return "开发工具与工程效率信号明确，值得纳入近期项目灵感观察。"
    return "具备明确产品、部署或商业化信号，进入本版精选。"


def _candidate_signature(candidate: dict[str, Any]) -> str:
    url = _normalized_text(candidate.get("url", ""))
    if url:
        return f"url:{url}"
    title = _normalized_text(candidate.get("title", ""))
    source = _normalized_text(candidate.get("source", ""))
    return f"title:{title}|source:{source}"


def _candidate_score(candidate: dict[str, Any]) -> float:
    tags = [str(tag).strip() for tag in candidate.get("tags", []) if str(tag).strip()]
    keywords = [str(keyword).strip() for keyword in candidate.get("keywords", []) if str(keyword).strip()]
    text = " ".join(
        filter(
            None,
            [
                _normalized_text(candidate.get("title", "")),
                _normalized_text(candidate.get("snippet", "")),
                _normalized_text(candidate.get("source", "")),
                *(_normalized_text(tag) for tag in tags),
                *(_normalized_text(keyword) for keyword in keywords),
            ],
        )
    )
    topic = _topic(candidate)
    score = 0.0
    if topic != "untagged":
        score += 3.0
    if topic == "AI Agent":
        score += 2.0
    elif topic in {"Robotics", "Tooling"}:
        score += 1.5
    score += min(len(tags), 3) * 0.75
    score += min(len(keywords), 3) * 0.5
    low_signal = any(phrase in text for phrase in LOW_SIGNAL_PHRASES)
    if low_signal:
        score -= 4.0
    else:
        matched_terms = sum(term in text for term in HIGH_SIGNAL_TERMS)
        score += min(matched_terms, 4) * 0.6
    if str(candidate.get("published", "") or "").strip():
        score += 0.25
    if not str(candidate.get("snippet", "") or "").strip():
        score -= 0.5
    if str(candidate.get("status", "ok") or "ok").strip().lower() == "error":
        score -= 10.0
    return score


def _select_candidates(
    candidates: list[dict[str, Any]],
    *,
    minimum: int = DEFAULT_SELECTED_MIN,
    maximum: int = DEFAULT_SELECTED_MAX,
) -> tuple[list[dict[str, Any]], int]:
    deduped: dict[str, tuple[float, int, dict[str, Any]]] = {}
    for index, candidate in enumerate(candidates):
        signature = _candidate_signature(candidate)
        score = _candidate_score(candidate)
        record = (score, index, candidate)
        existing = deduped.get(signature)
        if existing is None or score > existing[0] or (score == existing[0] and index < existing[1]):
            deduped[signature] = record

    ranked = sorted(deduped.values(), key=lambda record: (-record[0], record[1]))
    selected_count = _selected_count(len(ranked), minimum=minimum, maximum=maximum)
    selected_candidates = [candidate for _, _, candidate in ranked[:selected_count]]
    return selected_candidates, len(ranked)


def _today_signals(selected: list[dict[str, Any]]) -> list[str]:
    if not selected:
        return []
    counts = Counter(_topic(candidate) for candidate in selected)
    top_topic = counts.most_common(1)[0][0]
    return [
        f"{top_topic} 相关信号在本版中最集中，适合优先跟踪后续产品化与工作流变化。",
        f"本版覆盖 {len(counts)} 个主题，可同时观察代理工具、机器人落地与开发者效率方向。",
        "可行动条目以项目/工具导向为主，适合继续追踪源码、产品页或团队发布节奏。",
    ]


def compose_briefing(
    collect_result: CollectResult,
    *,
    slot: str,
    generated_at: str,
    editor_version: str = EDITOR_VERSION,
    selected_min: int = DEFAULT_SELECTED_MIN,
    selected_max: int = DEFAULT_SELECTED_MAX,
    default_channel: str = "unknown",
    translator: Callable[[str], str] | None = None,
) -> CuratedBriefing:
    selected_candidates, unique_candidate_count = _select_candidates(
        list(collect_result.candidates),
        minimum=selected_min,
        maximum=selected_max,
    )
    items: list[CuratedItem] = []
    feedback_items: list[dict[str, Any]] = []

    for rank, candidate in enumerate(selected_candidates, start=1):
        localized_candidate = _localized_candidate(candidate, translator)
        topic = _topic(localized_candidate)
        item = CuratedItem(
            briefing_id=collect_result.briefing_id,
            item_id=str(localized_candidate.get("item_id", "") or ""),
            rank=rank,
            title=str(localized_candidate.get("title", "") or "").strip(),
            source=str(localized_candidate.get("source", "") or "").strip(),
            url=str(localized_candidate.get("url", "") or "").strip(),
            published=str(localized_candidate.get("published", "") or "").strip(),
            tags=[str(tag).strip() for tag in localized_candidate.get("tags", []) if str(tag).strip()],
            topic=topic,
            rewritten_summary=_rewrite_summary(localized_candidate),
            why_relevant=_why_relevant(localized_candidate),
            action_or_observe=_action_or_observe(localized_candidate),
            selection_reason=_selection_reason(localized_candidate),
            feedback_metadata={
                "briefing_id": collect_result.briefing_id,
                "item_id": str(localized_candidate.get("item_id", "") or ""),
                "source": str(localized_candidate.get("source", "") or "").strip(),
                "tags": [str(tag).strip() for tag in localized_candidate.get("tags", []) if str(tag).strip()],
                "topic": topic,
                "channel": default_channel,
            },
            original_title=str(localized_candidate.get("original_title", "") or "").strip(),
        )
        items.append(item)
        feedback_item = {
            "slot": slot,
            "briefing_id": item.briefing_id,
            "item_id": item.item_id,
            "source": item.source,
            "url": item.url,
            "tags": list(item.tags),
            "topic": item.topic,
            "channel": default_channel,
            "title": item.title,
            "summary": item.rewritten_summary,
            "why_relevant": item.why_relevant,
            "action_or_observe": item.action_or_observe,
        }
        if item.original_title:
            feedback_item["original_title"] = item.original_title
            if item.action_or_observe:
                feedback_item["display_action_or_observe"] = item.action_or_observe.replace(item.original_title, item.title)
            if item.selection_reason:
                feedback_item["display_selection_reason"] = item.selection_reason.replace(item.original_title, item.title)
        feedback_items.append(feedback_item)

    warnings: list[str] = []
    if unique_candidate_count < selected_min and collect_result.candidates:
        warnings.append("low_candidate_supply")

    return CuratedBriefing(
        briefing_id=collect_result.briefing_id,
        slot=slot,
        slot_label=slot_label(slot),
        generated_at=generated_at,
        editor_version=editor_version,
        candidate_count=len(collect_result.candidates),
        curated_item_count=len(items),
        today_signals=_today_signals(selected_candidates),
        items=items,
        feedback_items=feedback_items,
        warnings=warnings,
    )


def load_curated_briefing(payload: dict[str, Any]) -> CuratedBriefing:
    items = [CuratedItem(**item) for item in payload.get("items", [])]
    return CuratedBriefing(
        briefing_id=payload["briefing_id"],
        slot=payload["slot"],
        slot_label=payload["slot_label"],
        generated_at=payload["generated_at"],
        editor_version=payload.get("editor_version", EDITOR_VERSION),
        candidate_count=int(payload.get("candidate_count", len(items))),
        curated_item_count=int(payload.get("curated_item_count", len(items))),
        today_signals=[str(signal) for signal in payload.get("today_signals", [])],
        items=items,
        feedback_items=[dict(item) for item in payload.get("feedback_items", [])],
        warnings=[str(warning) for warning in payload.get("warnings", [])],
    )
