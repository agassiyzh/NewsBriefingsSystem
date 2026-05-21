#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = ROOT / "skill" / "personal-newsroom"
SKILL_PATH = SKILL_DIR / "SKILL.md"
INVENTORY_PATH = SKILL_DIR / "references" / "packaging-inventory.md"
NEWSROOM_TEMPLATE_PATH = SKILL_DIR / "templates" / "newsroom.example.yaml"
REVIEW_TEMPLATE_PATH = SKILL_DIR / "templates" / "monthly-editorial-review.template.json"

REQUIRED_FILES = [
    ROOT / "architecture-v1.md",
    ROOT / "README.md",
    ROOT / "prompts" / "editor.md",
    ROOT / "prompts" / "reporter.md",
    ROOT / "prompts" / "analyst.md",
    ROOT / "prompts" / "publisher.md",
    ROOT / "scripts" / "collect_candidates.py",
    ROOT / "scripts" / "run_briefing.py",
    ROOT / "scripts" / "publish_telegram.py",
    ROOT / "scripts" / "export_hugo.py",
    ROOT / "scripts" / "run_shadow_briefing.py",
    ROOT / "scripts" / "compare_shadow_run.py",
    ROOT / "scripts" / "monthly_analysis.py",
    ROOT / "scripts" / "apply_editorial_preferences.py",
    ROOT / "docs" / "cron-migration-runbook.md",
    ROOT / "docs" / "monthly-editorial-review-runbook.md",
    ROOT / "docs" / "production-feedback-runbook.md",
    ROOT / "docs" / "monthly-interest-analysis-metrics-and-template.md",
    ROOT / "worker" / "README.md",
    ROOT / "worker" / "package.json",
    ROOT / "site" / "README.md",
    ROOT / "tests" / "test_collection.py",
    ROOT / "tests" / "test_runner.py",
    ROOT / "tests" / "test_publisher.py",
    ROOT / "tests" / "test_shadow.py",
    ROOT / "tests" / "test_monthly_analysis.py",
    ROOT / "tests" / "test_editorial_preferences.py",
    ROOT / "requirements.txt",
]


def validate_skill_markdown() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise SystemExit("SKILL.md must start with YAML frontmatter")
    match = re.search(r"\n---\n", text[4:])
    if not match:
        raise SystemExit("SKILL.md frontmatter closing delimiter not found")
    end = 4 + match.start()
    frontmatter = yaml.safe_load(text[4:end])
    if not isinstance(frontmatter, dict):
        raise SystemExit("SKILL.md frontmatter must parse to a mapping")
    for key in ("name", "description", "version", "author", "license", "metadata"):
        if key not in frontmatter:
            raise SystemExit(f"SKILL.md missing frontmatter key: {key}")
    if frontmatter["name"] != "personal-newsroom":
        raise SystemExit("SKILL.md name must be personal-newsroom")
    if len(frontmatter["description"]) > 1024:
        raise SystemExit("SKILL.md description exceeds 1024 characters")
    if "Editor owns long-term editorial memory" not in text:
        raise SystemExit("SKILL.md must document Editor memory ownership")
    if "Analyst submits recommendation reports" not in text:
        raise SystemExit("SKILL.md must document Analyst recommendation-only flow")


def validate_templates() -> None:
    newsroom_template = yaml.safe_load(NEWSROOM_TEMPLATE_PATH.read_text(encoding="utf-8"))
    if not isinstance(newsroom_template, dict):
        raise SystemExit("newsroom.example.yaml must parse as a mapping")
    for key in ("system", "schedule", "collection", "publication", "feedback", "memory", "paths"):
        if key not in newsroom_template:
            raise SystemExit(f"newsroom.example.yaml missing key: {key}")
    memory_block = newsroom_template["memory"]
    if memory_block.get("editor_can_write") is not True:
        raise SystemExit("newsroom.example.yaml must keep editor_can_write=true")
    if memory_block.get("analyst_can_write") is not False:
        raise SystemExit("newsroom.example.yaml must keep analyst_can_write=false")

    review_template = json.loads(REVIEW_TEMPLATE_PATH.read_text(encoding="utf-8"))
    for key in ("month", "review_status", "summary", "preferences"):
        if key not in review_template:
            raise SystemExit(f"monthly-editorial-review.template.json missing key: {key}")
    if review_template["review_status"] != "pending_review":
        raise SystemExit("monthly-editorial-review.template.json must default to pending_review")
    if not isinstance(review_template["preferences"], list) or not review_template["preferences"]:
        raise SystemExit("monthly-editorial-review.template.json must include at least one preference example")


def validate_references() -> None:
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED_FILES if not path.exists()]
    if missing:
        raise SystemExit("Missing referenced source files:\n- " + "\n- ".join(missing))

    inventory_text = INVENTORY_PATH.read_text(encoding="utf-8")
    for expected in [
        "Editor profile owns long-term memory",
        "Analyst submits recommendation reports",
        "scripts/monthly_analysis.py",
        "scripts/apply_editorial_preferences.py",
        "tests/test_shadow.py",
    ]:
        if expected not in inventory_text:
            raise SystemExit(f"packaging inventory missing expected reference: {expected}")

    forbidden_raw_event_reference = (
        "| `sample-data/monthly-analysis/2026-04/events.jsonl` | Reference | Safe example event input for monthly analysis. |"
    )
    if forbidden_raw_event_reference in inventory_text:
        raise SystemExit("packaging inventory must not treat events.jsonl as reusable safe example input")

    for expected in [
        "`sample-data/monthly-analysis/2026-04/events.jsonl` | Exclude |",
        "raw event-shaped analysis fixtures such as `sample-data/monthly-analysis/*/events.jsonl`",
    ]:
        if expected not in inventory_text:
            raise SystemExit(f"packaging inventory missing raw-event exclusion guardrail: {expected}")


def main() -> int:
    validate_skill_markdown()
    validate_templates()
    validate_references()
    print("OK personal-newsroom draft validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
