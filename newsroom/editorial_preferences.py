from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

TRUTHY = {"1", "true", "yes", "on"}
REVIEW_STATUS_VALUES = {"pending_review", "approved", "rejected"}
EDITOR_DECISION_VALUES = {"approved", "rejected", "needs_revision"}
ALLOWED_CONFIDENCE_VALUES = {"high", "medium", "low"}
ALLOWED_PREFERENCE_TYPES = {"interest", "style", "source", "negative", "safety", "format"}
ALLOWED_APPLY_ACTIONS = {"add", "replace"}
MIN_STABILITY_WINDOW_MONTHS = 3
DISALLOWED_CONTENT_PATTERNS = (
    re.compile(r"\banonymous_id\b", re.IGNORECASE),
    re.compile(r"\bitem_id\b", re.IGNORECASE),
    re.compile(r"\bbriefing_id\b", re.IGNORECASE),
    re.compile(r"\b(ip|user[_-]?agent|ua)\b", re.IGNORECASE),
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(r"\banon_[a-z0-9_-]+\b", re.IGNORECASE),
    re.compile(r"\braw event\b", re.IGNORECASE),
    re.compile(r"\b点击明细\b"),
    re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
)
DEFAULT_HONCHO_APPLY_ENV = "NEWSROOM_HONCHO_APPLY"
DEFAULT_HONCHO_ENDPOINT_ENV = "NEWSROOM_HONCHO_ENDPOINT"
DEFAULT_HONCHO_TOKEN_ENV = "NEWSROOM_HONCHO_TOKEN"


@dataclass(slots=True)
class ReviewPreference:
    id: str
    candidate_preference: str
    evidence_summary: str
    confidence: str
    editor_decision: str
    preference_type: str
    action: str
    stable_preference: bool
    stability_window_months: int
    notes: str = ""

    def to_honcho_memory(self, *, month: str) -> dict[str, Any]:
        return {
            "memory": self.candidate_preference,
            "metadata": {
                "source": "monthly_insight",
                "month": month,
                "preference_type": self.preference_type,
                "action": self.action,
                "confidence": self.confidence,
                "stable_preference": self.stable_preference,
                "stability_window_months": self.stability_window_months,
            },
        }


@dataclass(slots=True)
class ReviewDocument:
    month: str
    review_status: str
    reviewed_by: str
    reviewed_at: str
    preferences: list[ReviewPreference]


@dataclass(slots=True)
class ApplyResult:
    review_path: Path
    month: str
    review_status: str
    apply_requested: bool
    eligible_count: int
    written_count: int
    skipped_count: int
    errors: list[str]
    output_lines: list[str]


class HonchoClient:
    def __init__(self, *, endpoint: str, token: str) -> None:
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"invalid Honcho endpoint URL: {endpoint}")
        self.endpoint = endpoint.rstrip("/")
        self.token = token

    def write_preference(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read().decode("utf-8").strip()
                if not body:
                    return {"status": response.status}
                try:
                    parsed = json.loads(body)
                except json.JSONDecodeError:
                    return {"status": response.status, "body": body}
                if isinstance(parsed, dict):
                    return parsed
                return {"status": response.status, "body": parsed}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Honcho write failed: HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Honcho write failed: {exc.reason}") from exc


def _require_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"review file missing non-empty string field: {key}")
    return value.strip()


def _require_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"review file missing boolean field: {key}")
    return value


def _require_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"review file missing integer field: {key}")
    return value


def _optional_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"review file field must be a string when present: {key}")
    return value.strip()


def _contains_disallowed_content(*values: str) -> bool:
    for value in values:
        for pattern in DISALLOWED_CONTENT_PATTERNS:
            if pattern.search(value):
                return True
    return False


def _validate_preference(index: int, preference: ReviewPreference) -> None:
    if preference.confidence not in ALLOWED_CONFIDENCE_VALUES:
        raise ValueError(
            f"preferences[{index}].confidence must be one of {sorted(ALLOWED_CONFIDENCE_VALUES)}"
        )
    if preference.preference_type not in ALLOWED_PREFERENCE_TYPES:
        raise ValueError(
            f"preferences[{index}].preference_type must be one of {sorted(ALLOWED_PREFERENCE_TYPES)}"
        )
    if preference.action not in {*ALLOWED_APPLY_ACTIONS, "delete"}:
        raise ValueError(
            f"preferences[{index}].action must be one of {sorted(ALLOWED_APPLY_ACTIONS | {'delete'})}"
        )
    if preference.stability_window_months < 1:
        raise ValueError(f"preferences[{index}].stability_window_months must be >= 1")
    if _contains_disallowed_content(
        preference.id,
        preference.candidate_preference,
        preference.evidence_summary,
        preference.confidence,
        preference.notes,
    ):
        raise ValueError(
            f"preferences[{index}] contains disallowed raw-event or identifier-like content"
        )


def load_review_file(path: str | Path) -> ReviewDocument:
    review_path = Path(path)
    payload = json.loads(review_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("review file must be a JSON object")

    review_status = _require_string(payload, "review_status")
    if review_status not in REVIEW_STATUS_VALUES:
        raise ValueError(f"review_status must be one of {sorted(REVIEW_STATUS_VALUES)}")

    raw_preferences = payload.get("preferences")
    if not isinstance(raw_preferences, list):
        raise ValueError("review file missing preferences list")

    preferences: list[ReviewPreference] = []
    for index, raw_preference in enumerate(raw_preferences, start=1):
        if not isinstance(raw_preference, dict):
            raise ValueError(f"preferences[{index}] must be an object")
        editor_decision = _require_string(raw_preference, "editor_decision")
        if editor_decision not in EDITOR_DECISION_VALUES:
            raise ValueError(f"preferences[{index}].editor_decision must be one of {sorted(EDITOR_DECISION_VALUES)}")
        preference = ReviewPreference(
            id=_require_string(raw_preference, "id"),
            candidate_preference=_require_string(raw_preference, "candidate_preference"),
            evidence_summary=_require_string(raw_preference, "evidence_summary"),
            confidence=_require_string(raw_preference, "confidence"),
            editor_decision=editor_decision,
            preference_type=_require_string(raw_preference, "preference_type"),
            action=_require_string(raw_preference, "action"),
            stable_preference=_require_bool(raw_preference, "stable_preference"),
            stability_window_months=_require_int(raw_preference, "stability_window_months"),
            notes=str(raw_preference.get("notes", "") or "").strip(),
        )
        _validate_preference(index, preference)
        preferences.append(preference)

    return ReviewDocument(
        month=_require_string(payload, "month"),
        review_status=review_status,
        reviewed_by=_optional_string(payload, "reviewed_by"),
        reviewed_at=_optional_string(payload, "reviewed_at"),
        preferences=preferences,
    )


def env_truthy(name: str, environ: Mapping[str, str]) -> bool:
    return environ.get(name, "").strip().lower() in TRUTHY


def _error_message(exc: Exception) -> str:
    message = str(exc).strip().replace("\n", " ")
    return message or exc.__class__.__name__


def _review_load_failure(path: Path, message: str, *, apply_requested: bool) -> ApplyResult:
    errors = [message]
    return ApplyResult(
        review_path=path,
        month="unknown",
        review_status="error",
        apply_requested=apply_requested,
        eligible_count=0,
        written_count=0,
        skipped_count=0,
        errors=errors,
        output_lines=[
            f"review={path}",
            f"apply_requested={str(apply_requested).lower()}",
            "month=unknown",
            "review_status=error",
            f"ERROR {message}",
            "SKIP Honcho writes because the review file could not be loaded",
        ],
    )


def _eligible_preferences(review: ReviewDocument) -> list[ReviewPreference]:
    if review.review_status != "approved":
        return []
    return [
        preference
        for preference in review.preferences
        if (
            preference.editor_decision == "approved"
            and preference.stable_preference
            and preference.stability_window_months >= MIN_STABILITY_WINDOW_MONTHS
            and preference.action in ALLOWED_APPLY_ACTIONS
        )
    ]


def _non_applicable_preferences(review: ReviewDocument) -> list[ReviewPreference]:
    if review.review_status != "approved":
        return []
    return [
        preference
        for preference in review.preferences
        if (
            preference.editor_decision == "approved"
            and preference.stable_preference
            and preference.stability_window_months >= MIN_STABILITY_WINDOW_MONTHS
            and preference.action not in ALLOWED_APPLY_ACTIONS
        )
    ]


def _enforce_apply_policy(review: ReviewDocument) -> None:
    for index, preference in enumerate(review.preferences, start=1):
        if preference.editor_decision != "approved" or not preference.stable_preference:
            continue
        if preference.stability_window_months < MIN_STABILITY_WINDOW_MONTHS:
            raise ValueError(
                f"preferences[{index}].stability_window_months must be >= {MIN_STABILITY_WINDOW_MONTHS} for deprecated local migration flow"
            )
        if preference.action not in ALLOWED_APPLY_ACTIONS:
            allowed = sorted(ALLOWED_APPLY_ACTIONS)
            raise ValueError(
                f'preferences[{index}].action must be one of {allowed} for deprecated local migration flow'
            )


def _append_deprecated_adapter_notice(output_lines: list[str], *, apply_requested: bool) -> None:
    mode = 'local migration/debug preview only'
    output_lines.append(f'DEPRECATED {mode}')
    if apply_requested:
        output_lines.append(
            'SKIP repo-managed Honcho writes are disabled; Editor profile must write approved preferences directly'
        )
    else:
        output_lines.append(
            'SKIP repo-managed Honcho writes stay disabled in dry-run; use this adapter only to inspect legacy payload shape'
        )


def apply_review_file(
    review_path: str | Path,
    *,
    apply_requested: bool,
    environ: Mapping[str, str],
    client: HonchoClient | Any | None = None,
) -> ApplyResult:
    path = Path(review_path)
    try:
        review = load_review_file(path)
    except FileNotFoundError:
        return _review_load_failure(
            path,
            f"review file not found: {path}",
            apply_requested=apply_requested,
        )
    except json.JSONDecodeError:
        return _review_load_failure(
            path,
            f"malformed review JSON: {path}",
            apply_requested=apply_requested,
        )
    except UnicodeDecodeError:
        return _review_load_failure(
            path,
            f"unable to read review file: {path}",
            apply_requested=apply_requested,
        )
    except OSError:
        return _review_load_failure(
            path,
            f"unable to read review file: {path}",
            apply_requested=apply_requested,
        )

    errors: list[str] = []
    output_lines: list[str] = [
        f"review={path}",
        f"month={review.month}",
        f"review_status={review.review_status}",
        f"apply_requested={str(apply_requested).lower()}",
    ]
    _append_deprecated_adapter_notice(output_lines, apply_requested=apply_requested)
    if review.review_status == "approved" and (not review.reviewed_by or not review.reviewed_at):
        raise ValueError("approved review must include non-empty reviewed_by and reviewed_at")

    if review.review_status == "pending_review":
        output_lines.append("SKIP review pending editor approval; no Honcho writes attempted")
        return ApplyResult(
            review_path=path,
            month=review.month,
            review_status=review.review_status,
            apply_requested=apply_requested,
            eligible_count=0,
            written_count=0,
            skipped_count=len(review.preferences),
            errors=errors,
            output_lines=output_lines,
        )

    if review.review_status == "rejected":
        output_lines.append("SKIP review rejected; no Honcho writes attempted")
        return ApplyResult(
            review_path=path,
            month=review.month,
            review_status=review.review_status,
            apply_requested=apply_requested,
            eligible_count=0,
            written_count=0,
            skipped_count=len(review.preferences),
            errors=errors,
            output_lines=output_lines,
        )

    if apply_requested:
        _enforce_apply_policy(review)

    eligible = _eligible_preferences(review)
    non_applicable = _non_applicable_preferences(review)
    skipped_count = len(review.preferences) - len(eligible)
    output_lines.append(f"eligible_preferences={len(eligible)}")

    if not apply_requested:
        for preference in eligible:
            preview_payload = preference.to_honcho_memory(month=review.month)
            output_lines.append(f"WOULD_WRITE {json.dumps(preview_payload, ensure_ascii=False, sort_keys=True)}")
        if non_applicable:
            output_lines.append(f"SKIP {len(non_applicable)} non-applicable preference candidates")
        other_skipped_count = skipped_count - len(non_applicable)
        if other_skipped_count:
            output_lines.append(f"SKIP {other_skipped_count} non-stable-or-rejected preference candidates")
        return ApplyResult(
            review_path=path,
            month=review.month,
            review_status=review.review_status,
            apply_requested=apply_requested,
            eligible_count=len(eligible),
            written_count=0,
            skipped_count=skipped_count,
            errors=errors,
            output_lines=output_lines,
        )

    for preference in eligible:
        preview_payload = preference.to_honcho_memory(month=review.month)
        output_lines.append(f"WOULD_WRITE {json.dumps(preview_payload, ensure_ascii=False, sort_keys=True)}")
    if non_applicable:
        output_lines.append(f"SKIP {len(non_applicable)} non-applicable preference candidates")
    other_skipped_count = skipped_count - len(non_applicable)
    if other_skipped_count:
        output_lines.append(f"SKIP {other_skipped_count} non-stable-or-rejected preference candidates")
    return ApplyResult(
        review_path=path,
        month=review.month,
        review_status=review.review_status,
        apply_requested=apply_requested,
        eligible_count=len(eligible),
        written_count=0,
        skipped_count=skipped_count,
        errors=errors,
        output_lines=output_lines,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deprecated local migration/debug adapter for legacy editorial preference review files. Always stays preview-only.",
    )
    parser.add_argument("--review", required=True, help="Path to data/monthly_insights/YYYY-MM.review.json")
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Preview legacy local migration payloads only. Even with --apply, this adapter does not write to Honcho; "
            "the Editor profile owns any real memory updates."
        ),
    )
    return parser


def main(argv: list[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    active_environ = dict(os.environ if environ is None else environ)
    apply_requested = bool(args.apply) or env_truthy(DEFAULT_HONCHO_APPLY_ENV, active_environ)
    try:
        result = apply_review_file(args.review, apply_requested=apply_requested, environ=active_environ)
    except ValueError as exc:
        print(f"review={Path(args.review)}")
        print(f"apply_requested={str(apply_requested).lower()}")
        print(f"ERROR {_error_message(exc)}")
        return 2
    for line in result.output_lines:
        print(line)
    return 2 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
