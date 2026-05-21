"""Newsroom collection, publishing, analysis, and review utilities."""

from __future__ import annotations

from .collector import CollectResult, collect_candidates
from .editorial_preferences import ApplyResult, ReviewDocument, ReviewPreference, apply_review_file, load_review_file
from .ids import build_briefing_id, build_item_id, normalize_slot
from .monthly_analysis import analyze_month, build_dry_run_inputs, load_catalog_rows, load_event_rows
from .publisher import PublicationContext, PublishResult
from .runner import RunResult, run_briefing
from .shadow import CompareReport, compare_shadow_run, run_shadow_briefing

__all__ = [
    'ApplyResult',
    'CollectResult',
    'CompareReport',
    'PublicationContext',
    'PublishResult',
    'ReviewDocument',
    'ReviewPreference',
    'RunResult',
    'analyze_month',
    'apply_review_file',
    'build_briefing_id',
    'build_dry_run_inputs',
    'build_item_id',
    'collect_candidates',
    'compare_shadow_run',
    'load_catalog_rows',
    'load_event_rows',
    'load_review_file',
    'normalize_slot',
    'run_briefing',
    'run_shadow_briefing',
]
