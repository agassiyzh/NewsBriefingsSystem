from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from newsroom.editorial_preferences import apply_review_file


class FakeHonchoClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def write_preference(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(payload)
        return {"ok": True, "id": f"memory-{len(self.calls)}"}


class FailingHonchoClient:
    def __init__(self, *, fail_on_call: int = 1, message: str = "Honcho write failed: upstream unavailable") -> None:
        self.fail_on_call = fail_on_call
        self.message = message
        self.calls: list[dict[str, object]] = []

    def write_preference(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(payload)
        if len(self.calls) == self.fail_on_call:
            raise RuntimeError(self.message)
        return {"ok": True, "id": f"memory-{len(self.calls)}"}


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "apply_editorial_preferences.py"
REQUIRED_ENV = {
    "NEWSROOM_HONCHO_ENDPOINT": "http://honcho.example.test/api/v1/memories",
    "NEWSROOM_HONCHO_TOKEN": "secret-token",
}


def _write_review(
    tmp_path: Path,
    *,
    review_status: str,
    preference_decision: str,
    stable_preference: bool = True,
    stability_window_months: int = 3,
    preference_type: str = "interest",
    action: str = "add",
    candidate_preference: str = "用户连续 3 个月对 AI agent 工具链与开发者自动化内容保持高兴趣。",
    evidence_summary: str = "2026-03 到 2026-05 深读率持续高于月均，负反馈更低。",
) -> Path:
    review_path = tmp_path / "data" / "monthly_insights" / "2026-05.review.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(
        json.dumps(
            {
                "month": "2026-05",
                "review_status": review_status,
                "reviewed_by": "Editor",
                "reviewed_at": "2026-06-01T09:30:00+08:00",
                "preferences": [
                    {
                        "id": "pref-ai-agent-tooling",
                        "candidate_preference": candidate_preference,
                        "evidence_summary": evidence_summary,
                        "confidence": "high",
                        "editor_decision": preference_decision,
                        "preference_type": preference_type,
                        "action": action,
                        "stable_preference": stable_preference,
                        "stability_window_months": stability_window_months,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return review_path


def test_pending_review_allows_blank_reviewer_metadata_until_editor_finishes_review(tmp_path: Path) -> None:
    review_path = _write_review(tmp_path, review_status="pending_review", preference_decision="approved")
    payload = json.loads(review_path.read_text(encoding="utf-8"))
    payload["reviewed_by"] = ""
    payload["reviewed_at"] = ""
    review_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    client = FakeHonchoClient()

    result = apply_review_file(
        review_path,
        apply_requested=True,
        environ=REQUIRED_ENV,
        client=client,
    )

    assert result.review_status == "pending_review"
    assert result.written_count == 0
    assert any("DEPRECATED local migration/debug preview only" in line for line in result.output_lines)
    assert client.calls == []


def test_pending_review_does_not_write_even_when_apply_requested(tmp_path: Path) -> None:
    review_path = _write_review(tmp_path, review_status="pending_review", preference_decision="approved")
    client = FakeHonchoClient()

    result = apply_review_file(
        review_path,
        apply_requested=True,
        environ=REQUIRED_ENV,
        client=client,
    )

    assert result.review_status == "pending_review"
    assert result.written_count == 0
    assert client.calls == []


def test_pending_review_apply_skips_delete_candidates_instead_of_erroring(tmp_path: Path) -> None:
    review_path = _write_review(
        tmp_path,
        review_status="pending_review",
        preference_decision="approved",
        action="delete",
    )
    client = FakeHonchoClient()

    result = apply_review_file(
        review_path,
        apply_requested=True,
        environ=REQUIRED_ENV,
        client=client,
    )

    assert result.review_status == "pending_review"
    assert result.written_count == 0
    assert any("SKIP review pending editor approval" in line for line in result.output_lines)
    assert client.calls == []


def test_approved_review_requires_reviewer_metadata_before_writing(tmp_path: Path) -> None:
    review_path = _write_review(tmp_path, review_status="approved", preference_decision="approved")
    payload = json.loads(review_path.read_text(encoding="utf-8"))
    payload["reviewed_by"] = ""
    payload["reviewed_at"] = ""
    review_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="approved review must include non-empty reviewed_by and reviewed_at"):
        apply_review_file(
            review_path,
            apply_requested=False,
            environ={},
        )


def test_approved_review_dry_run_skips_short_stability_window_candidates(tmp_path: Path) -> None:
    review_path = _write_review(
        tmp_path,
        review_status="approved",
        preference_decision="approved",
        stability_window_months=2,
    )
    client = FakeHonchoClient()

    result = apply_review_file(
        review_path,
        apply_requested=False,
        environ={},
        client=client,
    )

    assert result.review_status == "approved"
    assert result.eligible_count == 0
    assert result.written_count == 0
    assert not any("WOULD_WRITE" in line for line in result.output_lines)
    assert any("SKIP 1 non-stable-or-rejected preference candidates" in line for line in result.output_lines)
    assert client.calls == []


def test_approved_review_dry_run_previews_without_writing(tmp_path: Path) -> None:
    review_path = _write_review(tmp_path, review_status="approved", preference_decision="approved")
    client = FakeHonchoClient()

    result = apply_review_file(
        review_path,
        apply_requested=False,
        environ={},
        client=client,
    )

    assert result.review_status == "approved"
    assert result.eligible_count == 1
    assert result.written_count == 0
    assert any("DEPRECATED local migration/debug preview only" in line for line in result.output_lines)
    assert any("WOULD_WRITE" in line for line in result.output_lines)
    assert client.calls == []


def test_apply_requested_is_downgraded_to_deprecated_non_production_preview(tmp_path: Path) -> None:
    review_path = _write_review(tmp_path, review_status="approved", preference_decision="approved")
    client = FakeHonchoClient()

    result = apply_review_file(
        review_path,
        apply_requested=True,
        environ=REQUIRED_ENV,
        client=client,
    )

    assert result.review_status == "approved"
    assert result.apply_requested is True
    assert result.eligible_count == 1
    assert result.written_count == 0
    assert any("DEPRECATED local migration/debug preview only" in line for line in result.output_lines)
    assert any("SKIP repo-managed Honcho writes are disabled; Editor profile must write approved preferences directly" in line for line in result.output_lines)
    assert any("WOULD_WRITE" in line for line in result.output_lines)
    assert client.calls == []


def test_load_review_file_rejects_unknown_preference_type(tmp_path: Path) -> None:
    review_path = _write_review(
        tmp_path,
        review_status="approved",
        preference_decision="approved",
        preference_type="unknown",
    )

    with pytest.raises(ValueError, match=r"preferences\[1\]\.preference_type must be one of"):
        apply_review_file(
            review_path,
            apply_requested=False,
            environ={},
        )


def test_load_review_file_rejects_unknown_confidence_value(tmp_path: Path) -> None:
    review_path = _write_review(tmp_path, review_status="approved", preference_decision="approved")
    payload = json.loads(review_path.read_text(encoding="utf-8"))
    payload["preferences"][0]["confidence"] = "raw event export https://example.com/item/123"
    review_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"preferences\[1\]\.confidence must be one of"):
        apply_review_file(
            review_path,
            apply_requested=False,
            environ={},
        )


def test_load_review_file_rejects_boolean_stability_window(tmp_path: Path) -> None:
    review_path = _write_review(tmp_path, review_status="approved", preference_decision="approved")
    payload = json.loads(review_path.read_text(encoding="utf-8"))
    payload["preferences"][0]["stability_window_months"] = True
    review_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"review file missing integer field: stability_window_months"):
        apply_review_file(
            review_path,
            apply_requested=False,
            environ={},
        )


def test_approved_review_apply_rejects_delete_action_for_automated_flow(tmp_path: Path) -> None:
    review_path = _write_review(
        tmp_path,
        review_status="approved",
        preference_decision="approved",
        action="delete",
    )

    with pytest.raises(ValueError, match=r"preferences\[1\]\.action must be one of \['add', 'replace'\] for deprecated local migration flow"):
        apply_review_file(
            review_path,
            apply_requested=True,
            environ=REQUIRED_ENV,
            client=FakeHonchoClient(),
        )



def test_approved_review_dry_run_skips_delete_action_for_automated_flow(tmp_path: Path) -> None:
    review_path = _write_review(
        tmp_path,
        review_status="approved",
        preference_decision="approved",
        action="delete",
    )
    client = FakeHonchoClient()

    result = apply_review_file(
        review_path,
        apply_requested=False,
        environ={},
        client=client,
    )

    assert result.review_status == "approved"
    assert result.eligible_count == 0
    assert result.written_count == 0
    assert not any("WOULD_WRITE" in line for line in result.output_lines)
    assert any("SKIP 1 non-applicable preference candidates" in line for line in result.output_lines)
    assert client.calls == []


def test_approved_review_apply_calls_client_only_for_stable_candidates(tmp_path: Path) -> None:
    review_path = tmp_path / "data" / "monthly_insights" / "2026-05.review.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(
        json.dumps(
            {
                "month": "2026-05",
                "review_status": "approved",
                "reviewed_by": "Editor",
                "reviewed_at": "2026-06-01T09:30:00+08:00",
                "preferences": [
                    {
                        "id": "pref-keep-ai-agent",
                        "candidate_preference": "保持 AI agent 工具链与自动化实践内容高权重。",
                        "evidence_summary": "连续 3 个月深读率高于月均。",
                        "confidence": "high",
                        "editor_decision": "approved",
                        "preference_type": "interest",
                        "action": "add",
                        "stable_preference": True,
                        "stability_window_months": 3,
                    },
                    {
                        "id": "pref-one-off-financing",
                        "candidate_preference": "提高单月融资新闻权重。",
                        "evidence_summary": "仅 2026-05 出现短期点击峰值。",
                        "confidence": "low",
                        "editor_decision": "approved",
                        "preference_type": "negative",
                        "action": "add",
                        "stable_preference": False,
                        "stability_window_months": 1,
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    client = FakeHonchoClient()

    result = apply_review_file(
        review_path,
        apply_requested=True,
        environ=REQUIRED_ENV,
        client=client,
    )

    assert result.review_status == "approved"
    assert result.eligible_count == 1
    assert result.written_count == 0
    assert any("DEPRECATED local migration/debug preview only" in line for line in result.output_lines)
    assert any("WOULD_WRITE" in line for line in result.output_lines)
    assert client.calls == []


def test_approved_review_apply_rejects_raw_event_like_content(tmp_path: Path) -> None:
    review_path = _write_review(
        tmp_path,
        review_status="approved",
        preference_decision="approved",
        candidate_preference="anonymous_id=anon_123 的用户点击了 https://example.com/story",
        evidence_summary="来源是 raw event 导出，包含单条 item 点击明细。",
    )

    with pytest.raises(ValueError, match="contains disallowed raw-event or identifier-like content"):
        apply_review_file(
            review_path,
            apply_requested=True,
            environ=REQUIRED_ENV,
            client=FakeHonchoClient(),
        )


def test_approved_review_apply_rejects_identifier_like_preference_id(tmp_path: Path) -> None:
    review_path = _write_review(tmp_path, review_status="approved", preference_decision="approved")
    payload = json.loads(review_path.read_text(encoding="utf-8"))
    payload["preferences"][0]["id"] = "item_id-123"
    review_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="contains disallowed raw-event or identifier-like content"):
        apply_review_file(
            review_path,
            apply_requested=True,
            environ=REQUIRED_ENV,
            client=FakeHonchoClient(),
        )


def test_approved_review_apply_rejects_email_address_content(tmp_path: Path) -> None:
    review_path = _write_review(
        tmp_path,
        review_status="approved",
        preference_decision="approved",
        candidate_preference="请持续优先发送给 foo@example.com 偏好的 AI agent 内容。",
    )

    with pytest.raises(ValueError, match="contains disallowed raw-event or identifier-like content"):
        apply_review_file(
            review_path,
            apply_requested=True,
            environ=REQUIRED_ENV,
            client=FakeHonchoClient(),
        )


def test_approved_review_apply_rejects_briefing_id_like_content(tmp_path: Path) -> None:
    review_path = _write_review(
        tmp_path,
        review_status="approved",
        preference_decision="approved",
        candidate_preference="briefing_id=2026-05-19-08 的版次说明 AI Agent 表现最好。",
        evidence_summary="请直接沿用 briefing_id=2026-05-19-08 的点击结论。",
    )

    with pytest.raises(ValueError, match="contains disallowed raw-event or identifier-like content"):
        apply_review_file(
            review_path,
            apply_requested=True,
            environ=REQUIRED_ENV,
            client=FakeHonchoClient(),
        )


def test_approved_review_apply_rejects_ip_address_like_content(tmp_path: Path) -> None:
    review_path = _write_review(
        tmp_path,
        review_status="approved",
        preference_decision="approved",
        candidate_preference="优先迎合 IP 203.0.113.5 用户群体偏好的 AI Agent 选题。",
        evidence_summary="这段证据提到了 ip address 203.0.113.5 的访问模式。",
    )

    with pytest.raises(ValueError, match="contains disallowed raw-event or identifier-like content"):
        apply_review_file(
            review_path,
            apply_requested=True,
            environ=REQUIRED_ENV,
            client=FakeHonchoClient(),
        )


def test_approved_review_apply_rejects_user_agent_like_content(tmp_path: Path) -> None:
    review_path = _write_review(
        tmp_path,
        review_status="approved",
        preference_decision="approved",
        candidate_preference="user_agent=Mozilla/5.0 的读者更喜欢 AI Agent。",
        evidence_summary="UA 样本显示 Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)。",
    )

    with pytest.raises(ValueError, match="contains disallowed raw-event or identifier-like content"):
        apply_review_file(
            review_path,
            apply_requested=True,
            environ=REQUIRED_ENV,
            client=FakeHonchoClient(),
        )


def test_apply_without_endpoint_or_token_reports_clear_skip(tmp_path: Path) -> None:
    review_path = _write_review(tmp_path, review_status="approved", preference_decision="approved")
    client = FakeHonchoClient()

    result = apply_review_file(
        review_path,
        apply_requested=True,
        environ={},
        client=client,
    )

    assert result.review_status == "approved"
    assert result.written_count == 0
    assert result.errors == []
    assert any("repo-managed Honcho writes are disabled" in line for line in result.output_lines)
    assert client.calls == []


def test_apply_with_invalid_endpoint_reports_clear_skip(tmp_path: Path) -> None:
    review_path = _write_review(tmp_path, review_status="approved", preference_decision="approved")

    result = apply_review_file(
        review_path,
        apply_requested=True,
        environ={
            "NEWSROOM_HONCHO_ENDPOINT": "not-a-url",
            "NEWSROOM_HONCHO_TOKEN": "secret-token",
        },
    )

    assert result.written_count == 0
    assert result.errors == []
    assert any("repo-managed Honcho writes are disabled" in line for line in result.output_lines)


def test_apply_write_failure_returns_controlled_error_and_partial_write_note(tmp_path: Path) -> None:
    review_path = tmp_path / "data" / "monthly_insights" / "2026-05.review.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(
        json.dumps(
            {
                "month": "2026-05",
                "review_status": "approved",
                "reviewed_by": "Editor",
                "reviewed_at": "2026-06-01T09:30:00+08:00",
                "preferences": [
                    {
                        "id": "pref-one",
                        "candidate_preference": "保持 AI agent 工具链与自动化实践内容高权重。",
                        "evidence_summary": "连续 3 个月深读率高于月均。",
                        "confidence": "high",
                        "editor_decision": "approved",
                        "preference_type": "interest",
                        "action": "add",
                        "stable_preference": True,
                        "stability_window_months": 3,
                    },
                    {
                        "id": "pref-two",
                        "candidate_preference": "降低短期热点融资新闻的排序优先级。",
                        "evidence_summary": "多月表现为低转化且低深读。",
                        "confidence": "medium",
                        "editor_decision": "approved",
                        "preference_type": "negative",
                        "action": "replace",
                        "stable_preference": True,
                        "stability_window_months": 4,
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    client = FailingHonchoClient(fail_on_call=2)

    result = apply_review_file(
        review_path,
        apply_requested=True,
        environ=REQUIRED_ENV,
        client=client,
    )

    assert result.review_status == "approved"
    assert result.eligible_count == 2
    assert result.written_count == 0
    assert result.errors == []
    assert any("repo-managed Honcho writes are disabled" in line for line in result.output_lines)
    assert len(client.calls) == 0


def test_rejected_review_does_not_write(tmp_path: Path) -> None:
    review_path = _write_review(tmp_path, review_status="rejected", preference_decision="rejected")
    client = FakeHonchoClient()

    result = apply_review_file(
        review_path,
        apply_requested=True,
        environ=REQUIRED_ENV,
        client=client,
    )

    assert result.review_status == "rejected"
    assert result.written_count == 0
    assert client.calls == []


def test_repository_sample_review_file_stays_dry_run_safe() -> None:
    review_path = ROOT / "data" / "monthly_insights" / "2026-05.review.json"
    client = FakeHonchoClient()

    result = apply_review_file(
        review_path,
        apply_requested=False,
        environ={},
        client=client,
    )

    assert result.review_status == "pending_review"
    assert result.written_count == 0
    assert any("SKIP review pending editor approval" in line for line in result.output_lines)
    assert client.calls == []


def test_cli_defaults_to_dry_run_and_prints_preview(tmp_path: Path) -> None:
    review_path = _write_review(tmp_path, review_status="approved", preference_decision="approved")

    process = subprocess.run(
        [sys.executable, str(SCRIPT), "--review", str(review_path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )

    assert "apply_requested=false" in process.stdout
    assert "DEPRECATED local migration/debug preview only" in process.stdout
    assert "WOULD_WRITE" in process.stdout
    assert process.returncode == 0


def test_cli_env_switch_requests_apply_and_reports_missing_credentials(tmp_path: Path) -> None:
    review_path = _write_review(tmp_path, review_status="approved", preference_decision="approved")

    process = subprocess.run(
        [sys.executable, str(SCRIPT), "--review", str(review_path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(ROOT), "NEWSROOM_HONCHO_APPLY": "1"},
    )

    assert process.returncode == 0
    assert "apply_requested=true" in process.stdout
    assert "repo-managed Honcho writes are disabled" in process.stdout


def test_cli_missing_review_file_returns_controlled_error_without_traceback(tmp_path: Path) -> None:
    missing_review_path = tmp_path / "data" / "monthly_insights" / "missing.review.json"

    process = subprocess.run(
        [sys.executable, str(SCRIPT), "--review", str(missing_review_path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )

    assert process.returncode == 2
    assert f"ERROR review file not found: {missing_review_path}" in process.stdout
    assert "Traceback" not in process.stdout
    assert "Traceback" not in process.stderr


def test_cli_directory_review_path_returns_controlled_error_without_traceback(tmp_path: Path) -> None:
    review_path = tmp_path / "data" / "monthly_insights"
    review_path.mkdir(parents=True, exist_ok=True)

    process = subprocess.run(
        [sys.executable, str(SCRIPT), "--review", str(review_path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )

    assert process.returncode == 2
    assert f"ERROR unable to read review file: {review_path}" in process.stdout
    assert "Traceback" not in process.stdout
    assert "Traceback" not in process.stderr


def test_cli_malformed_review_json_returns_controlled_error_without_traceback(tmp_path: Path) -> None:
    review_path = tmp_path / "data" / "monthly_insights" / "2026-05.review.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text('{"month": "2026-05",', encoding="utf-8")

    process = subprocess.run(
        [sys.executable, str(SCRIPT), "--review", str(review_path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )

    assert process.returncode == 2
    assert f"ERROR malformed review JSON: {review_path}" in process.stdout
    assert "Traceback" not in process.stdout
    assert "Traceback" not in process.stderr


def test_cli_invalid_utf8_review_file_returns_controlled_error_without_traceback(tmp_path: Path) -> None:
    review_path = tmp_path / "data" / "monthly_insights" / "2026-05.review.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_bytes(b"\xff\xfe\x00bad-json")

    process = subprocess.run(
        [sys.executable, str(SCRIPT), "--review", str(review_path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )

    assert process.returncode == 2
    assert f"ERROR unable to read review file: {review_path}" in process.stdout
    assert "Traceback" not in process.stdout
    assert "Traceback" not in process.stderr
