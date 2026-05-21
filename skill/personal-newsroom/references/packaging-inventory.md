# Personal Newsroom skill packaging inventory

## Goal

Package the current `/opt/data/home/NewsBriefingsSystem` repository into a reusable repo-local `personal-newsroom` skill draft without depending on a preinstalled global skill.

The packaging direction is:
- Editor profile owns long-term memory.
- Analyst submits recommendation reports and review packets.
- The repository does not perform production Honcho writes; the Editor-in-chief Hermes profile owns long-term memory writes.
- Raw feedback events must never be packaged as memory artifacts.

## Draft bundle layout

```text
skill/personal-newsroom/
  SKILL.md
  references/
    packaging-inventory.md
  templates/
    newsroom.example.yaml
    monthly-editorial-review.template.json
  scripts/
    validate_draft.py
```

Recommended future promotion layout if this draft graduates into a shipped skill:

```text
personal-newsroom/
  SKILL.md
  references/
    architecture-v1.md
    packaging-inventory.md
    monthly-editorial-review-runbook.md
    cron-migration-runbook.md
    production-feedback-runbook.md
    monthly-interest-analysis-metrics-and-template.md
    prompts/
      editor.md
      reporter.md
      analyst.md
      publisher.md
  templates/
    newsroom.example.yaml
    monthly-editorial-review.template.json
  scripts/
    validate_draft.py
```

## Inventory by source area

### 1. Architecture / overview

| Source | Include mode | Why |
|---|---|---|
| `architecture-v1.md` | Reference | Canonical architecture, role boundaries, Phase 6 packaging plan. |
| `README.md` | Reference | Day-to-day operator overview and command entrypoints. |

### 2. Role prompts

| Source | Include mode | Why |
|---|---|---|
| `prompts/editor.md` | Reference | Editor responsibilities, output format, memory boundary. |
| `prompts/reporter.md` | Reference | Reporter collection contract and memory prohibition. |
| `prompts/analyst.md` | Reference | Analyst recommendation-only role; no direct Honcho writes. |
| `prompts/publisher.md` | Reference | Publication responsibilities and safety boundary. |

Reason to reference instead of copy right now: these prompt drafts are still evolving in-repo, so copying them into the draft skill would create drift.

### 3. Core Python entrypoints

| Source | Include mode | Why |
|---|---|---|
| `scripts/collect_candidates.py` | Reference | Candidate collection CLI entrypoint. |
| `scripts/run_briefing.py` | Reference | Main briefing runner. |
| `scripts/publish_telegram.py` | Reference | Telegram publication adapter. |
| `scripts/export_hugo.py` | Reference | Hugo export adapter. |
| `scripts/run_shadow_briefing.py` | Reference | Shadow-run entrypoint for migration validation. |
| `scripts/compare_shadow_run.py` | Reference | Compare legacy vs shadow outputs. |
| `scripts/monthly_analysis.py` | Reference | Monthly insights generation. |
| `scripts/apply_editorial_preferences.py` | Reference | Deprecated/non-production local migration/debug payload preview only; not a production Honcho apply path. |
| `scripts/run_shadow_cron_once.sh` | Reference | Cron invocation example for shadow runs. |

### 4. Python implementation modules

| Source | Include mode | Why |
|---|---|---|
| `newsroom/collector.py` | Reference | Collection implementation and CLI behavior. |
| `newsroom/runner.py` | Reference | Manifest, archive, and publication orchestration. |
| `newsroom/publisher.py` | Reference | Archive/Hugo/Telegram export behavior and contracts. |
| `newsroom/shadow.py` | Reference | Shadow output isolation and compare helpers. |
| `newsroom/monthly_analysis.py` | Reference | Metrics + report generation logic. |
| `newsroom/editorial_preferences.py` | Reference | Review-file parsing and deprecated local migration/debug guardrails; production memory writes belong to the Editor profile. |
| `newsroom/config.py` | Reference | Config loading and path conventions. |
| `newsroom/ids.py` | Reference | `briefing_id` / `item_id` contract. |
| `newsroom/site_bootstrap.py` | Reference | Sample-site/bootstrap flow. |

### 5. Runbooks and policies

| Source | Include mode | Why |
|---|---|---|
| `docs/phase1-runbook.md` | Reference | Collection/runner baseline and rollback path. |
| `docs/phase2-runbook.md` | Reference | Publisher and Hugo export operating steps. |
| `docs/cron-migration-runbook.md` | Reference | Shadow validation + cron migration rules. |
| `docs/monthly-editorial-review-runbook.md` | Reference | Analyst -> Editor review loop and Editor-owned memory safety protocol. |
| `docs/monthly-interest-analysis-metrics-and-template.md` | Reference | Analyst metrics model and report semantics. |
| `docs/production-feedback-runbook.md` | Reference | Worker/D1/Pages verification and rollback. |
| `worker/README.md` | Reference | Local worker safety boundary and test commands. |
| `site/README.md` | Reference | Hugo export rules and sample content expectations. |

### 6. Config examples and templates

| Source | Include mode | Why |
|---|---|---|
| `config/newsroom.yaml` | Generate template | Contains environment-specific paths; ship a sanitized example instead. |
| `data/monthly_insights/2026-05.review.json` | Generate template | Good review-file shape; convert to month-agnostic draft template. |
| `config/interests.yaml` | Reference only for now | Content is useful but still user/domain-specific; avoid freezing into generic template yet. |
| `config/sources.yaml` | Reference only for now | Source list is operationally useful but likely to evolve and may need editorial curation first. |

Generated templates in this draft:
- `templates/newsroom.example.yaml`
- `templates/monthly-editorial-review.template.json`

### 7. Sample data / examples

| Source | Include mode | Why |
|---|---|---|
| `sample-data/monthly-analysis/2026-04/briefing.md` | Reference | Safe example briefing for metrics/report discussion. |
| `sample-data/monthly-analysis/2026-04/events.jsonl` | Exclude | Raw event-shaped internal analysis fixture; do not copy into the reusable skill bundle or treat as a safe example because it preserves anonymous_id / briefing_id / item-level behavior structure. |
| `sample-data/monthly-analysis/2026-04/catalog.jsonl` | Reference | Safe item catalog example for joins. |
| `site/sample-data/2026-01-01.md` | Reference | Public-safe briefing example for Hugo/export bootstrap. |

### 8. Tests and verification commands

| Scope | Source | Include mode |
|---|---|---|
| Collection | `tests/test_collection.py` | Reference |
| Runner / publication | `tests/test_runner.py`, `tests/test_publisher.py`, `tests/test_site_bootstrap.py` | Reference |
| Shadow migration | `tests/test_shadow.py` | Reference |
| Monthly analysis / memory review | `tests/test_monthly_analysis.py`, `tests/test_editorial_preferences.py` | Reference |
| Baseline dependency checks | `tests/test_dependencies.py`, `requirements.txt` | Reference |
| Worker contract | `worker/test/frontend-feedback.test.js`, `worker/test/feedback-worker.test.js`, `worker/package.json` | Reference |

Recommended verification commands for the packaged draft:

```bash
cd /opt/data/home/NewsBriefingsSystem
/opt/hermes/.venv/bin/python skill/personal-newsroom/scripts/validate_draft.py
/opt/hermes/.venv/bin/python -m pytest \
  tests/test_collection.py \
  tests/test_runner.py \
  tests/test_publisher.py \
  tests/test_shadow.py \
  tests/test_monthly_analysis.py \
  tests/test_editorial_preferences.py -q
```

Worker verification remains separate because it needs Node >=22:

```bash
cd /opt/data/home/NewsBriefingsSystem/worker
npm test
```

For environments where the default `node` is older than 22, follow `docs/production-feedback-runbook.md` before running Wrangler or Worker tests.

## Exclusions

Do not package or copy these into the reusable skill bundle:
- `data/candidates/`, `data/contexts/`, `data/runs/`, `data/shadow/`
- raw event-shaped analysis fixtures such as `sample-data/monthly-analysis/*/events.jsonl`
- `docs/monthly-insights/*.md` generated monthly outputs
- `site/public/`
- `.tmp-*`, `.tmp-kanban/`, `.pytest_cache/`, `__pycache__/`
- `worker/.tmp-*`, `worker/.wrangler/`
- any secrets, tokens, Cloudflare credentials, Telegram chat identifiers, or local machine-specific absolute paths beyond documented examples

## Packaging decision summary

1. Reference stable source-of-truth implementation and runbooks from the repo.
2. Generate templates where the source file contains environment-specific values or dated examples.
3. Exclude generated outputs and transient workspaces.
4. Keep the draft repo-local until the structure and ownership rules are reviewed.
5. Only after review should the draft be promoted into a globally installed Hermes skill or shipped package.
