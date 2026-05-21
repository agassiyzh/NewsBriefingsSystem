---
name: personal-newsroom
description: "Use when operating, extending, or packaging the Personal Newsroom System repo: daily briefing runs, Hugo/Telegram publication handoff, shadow validation, monthly feedback analysis, and safe Honcho review flow."
version: 0.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [newsroom, briefings, hugo, feedback, honcho, skill-packaging]
    related_skills: [writing-plans, requesting-code-review]
---

# Personal Newsroom

## Overview

This is a repo-local draft skill for `/opt/data/home/NewsBriefingsSystem`.
It packages the current newsroom runner, prompts, runbooks, feedback analysis flow,
and safe memory handoff rules into one reusable entry point.

The draft is intentionally self-contained inside the repository. It does not assume a
preinstalled global `personal-newsroom` skill, and it does not require profile-level
changes before the packaging work is reviewed.

## When to Use

Use this skill when you need to:
- run or inspect the daily briefing pipeline
- collect candidates or rerun publication adapters
- validate shadow runner output before any cron migration
- generate monthly insights and prepare an Editor review packet
- package this repo into a reusable skill bundle for later promotion

Do not use this skill to:
- change production cron without an explicit ops task
- deploy Cloudflare resources without explicit authorization
- write raw feedback events, single-news anecdotes, or PII into Honcho
- treat repo-local draft files as already-installed Hermes skills

## Core Ownership Boundaries

- Editor owns long-term editorial memory.
- Analyst submits recommendation reports and review packets; Analyst does not write Honcho directly.
- Reporter can search and summarize, but must not read or write long-term editorial memory.
- Publisher handles delivery artifacts and publication state, not topic selection.
- The repo must not perform production Honcho writes. Long-term editorial memory is owned and written by the Editor-in-chief Hermes profile after review; `scripts/apply_editorial_preferences.py` is deprecated/non-production and may only be used for local migration/debug dry-runs.

## Repository Surface

Primary source files live outside the draft skill directory and remain the source of truth:
- Architecture: `architecture-v1.md`
- Overview: `README.md`
- Role prompts: `prompts/editor.md`, `prompts/reporter.md`, `prompts/analyst.md`, `prompts/publisher.md`
- Core entrypoints: `scripts/collect_candidates.py`, `scripts/run_briefing.py`, `scripts/publish_telegram.py`, `scripts/export_hugo.py`
- Shadow migration: `scripts/run_shadow_briefing.py`, `scripts/compare_shadow_run.py`, `docs/cron-migration-runbook.md`
- Monthly analysis + Editor review: `scripts/monthly_analysis.py`, `scripts/apply_editorial_preferences.py`, `docs/monthly-editorial-review-runbook.md`
- Feedback stack: `worker/README.md`, `docs/production-feedback-runbook.md`, `site/README.md`

Packaging decisions and inclusion rules are documented in:
- `skill/personal-newsroom/references/packaging-inventory.md`

Draft templates shipped with this repo-local skill:
- `skill/personal-newsroom/templates/newsroom.example.yaml`
- `skill/personal-newsroom/templates/monthly-editorial-review.template.json`

Local verification helper:
- `skill/personal-newsroom/scripts/validate_draft.py`

## Common Workflows

### 1. Collect candidates only

```bash
cd /opt/data/home/NewsBriefingsSystem
/opt/hermes/.venv/bin/python scripts/collect_candidates.py --slot morning
```

Outputs:
- `data/candidates/YYYY-MM-DD-HH.jsonl`
- `data/contexts/YYYY-MM-DD-HH.md`

### 2. Run the briefing pipeline in dry-run mode

```bash
cd /opt/data/home/NewsBriefingsSystem
/opt/hermes/.venv/bin/python scripts/run_briefing.py --slot noon --dry-run
```

Dry-run must not update the production archive.
Use this first when validating packaging or prompt changes.

### 3. Rerun publication adapters from an existing manifest

```bash
cd /opt/data/home/NewsBriefingsSystem
/opt/hermes/.venv/bin/python scripts/publish_telegram.py --manifest data/runs/2026-05-19-13.json
/opt/hermes/.venv/bin/python scripts/export_hugo.py --manifest data/runs/2026-05-19-13.json
```

### 4. Run and compare a shadow briefing

```bash
cd /opt/data/home/NewsBriefingsSystem
/opt/hermes/.venv/bin/python scripts/run_shadow_briefing.py \
  --slot morning \
  --date 2026-05-20 \
  --shadow-dir data/shadow

/opt/hermes/.venv/bin/python scripts/compare_shadow_run.py \
  --legacy-archive /opt/data/home/NewsBriefings/2026-05-20.md \
  --shadow-manifest data/shadow/data/runs/2026-05-20-08.json
```

### 5. Generate monthly insights without writing memory

```bash
cd /opt/data/home/NewsBriefingsSystem
/opt/hermes/.venv/bin/python scripts/monthly_analysis.py --dry-run --month 2026-05
```

This produces draft insights only. It does not write Honcho or Hermes memory; Analyst recommendations must be reviewed by the Editor profile, which owns any eventual memory write.

### 6. Deprecated local memory payload preview (non-production/debug only)

```bash
cd /opt/data/home/NewsBriefingsSystem
/opt/hermes/.venv/bin/python scripts/apply_editorial_preferences.py \
  --review skill/personal-newsroom/templates/monthly-editorial-review.template.json \
  --dry-run
```

This adapter is deprecated and is not a production Honcho/Hermes memory write path. Keep it limited to local migration/debug payload validation; do not connect `--apply`, `NEWSROOM_HONCHO_*`, or equivalent endpoint/token flags to production cron, CI, Cloudflare, or Pages deploys. Real long-term memory updates are made only by the Editor-in-chief Hermes profile after review.

## Packaging Rules

1. Keep executable logic in `scripts/`, `newsroom/`, `worker/`, and `site/`; do not fork those implementations into the skill draft.
2. Keep runbooks and prompts as referenced source documents until promotion time, to avoid copy drift while the repo is still changing.
3. Convert environment-specific examples into templates. Config examples belong in `templates/`, not copied verbatim from live repo files.
4. Exclude generated outputs from the skill bundle: `data/candidates/`, `data/contexts/`, `data/runs/`, `data/shadow/`, `site/public/`, `__pycache__/`, `.tmp-*`, `.pytest_cache/`, `.wrangler/`, `worker/.tmp-*`.
5. Preserve the new direction explicitly:
   - Editor profile owns memory.
   - Analyst submits recommendation reports.
   - The repo does not write Honcho in production; only the Editor profile owns and updates long-term editorial memory.

## Common Pitfalls

1. Confusing draft packaging with installation
   - `skill/personal-newsroom/` is a repo artifact, not an already-registered Hermes skill.

2. Packaging generated data
   - Do not ship `site/public`, shadow outputs, tmp folders, or archived run manifests as reusable skill content.

3. Bypassing Editor review
   - `scripts/monthly_analysis.py` produces candidate recommendations only.
   - `scripts/apply_editorial_preferences.py` remains deprecated/non-production/local migration/debug only; do not connect it to production cron, CI, or deploy paths.

4. Writing the wrong memory payload
   - Never send raw events, anonymous IDs, single clicked items, or short-lived热点 into Honcho.
   - Only stable, cross-month, declarative editorial preferences are eligible.

5. Worker verification on the wrong Node runtime
   - `worker/package.json` requires Node `>=22`.
   - If the default shell Node is older, use the production-feedback runbook guidance before running Wrangler commands.

## Verification Checklist

- [ ] `skill/personal-newsroom/references/packaging-inventory.md` matches the current repo layout.
- [ ] Draft templates parse cleanly as YAML/JSON.
- [ ] `skill/personal-newsroom/scripts/validate_draft.py` passes.
- [ ] Targeted Python tests for collection, runner, publisher, shadow, and monthly analysis still pass.
- [ ] Any future promotion copies only stable references or generated templates, not transient outputs.
