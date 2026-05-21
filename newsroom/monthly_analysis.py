from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import yaml

from .config import dump_json

SUPPORTED_EVENT_SUFFIXES = {'.csv', '.json', '.jsonl', '.ndjson'}
SUPPORTED_CATALOG_SUFFIXES = {'.json', '.jsonl', '.ndjson', '.md'}
DEFAULT_OUTPUT_ROOT = 'data/monthly_insights'
DEFAULT_DOCS_ROOT = 'docs/monthly-insights'
DEFAULT_TIMEZONE = 'Asia/Shanghai'

DIMENSION_THRESHOLDS: dict[str, dict[str, dict[str, int]]] = {
    'topic': {
        'display': {'items': 2, 'impressions': 6, 'read_sessions': 3},
        'decision': {'items': 3, 'impressions': 12, 'read_sessions': 6},
    },
    'source': {
        'display': {'items': 2, 'impressions': 4, 'read_sessions': 2},
        'decision': {'items': 3, 'impressions': 8, 'read_sessions': 4},
    },
    'tag': {
        'display': {'items': 2, 'impressions': 6, 'read_sessions': 3},
        'decision': {'items': 3, 'impressions': 12, 'read_sessions': 6},
    },
    'item': {
        'display': {'items': 1, 'impressions': 2, 'read_sessions': 1},
        'decision': {'items': 1, 'impressions': 4, 'read_sessions': 2},
    },
}

RECOMMENDATION_DIMENSIONS = ('topic', 'source', 'tag')


def _parse_month(month: str) -> tuple[int, int]:
    try:
        year_text, month_text = month.split('-', 1)
        year = int(year_text)
        month_number = int(month_text)
    except ValueError as exc:
        raise ValueError(f'month 必须是 YYYY-MM，收到：{month}') from exc
    if month_number < 1 or month_number > 12:
        raise ValueError(f'month 必须是 YYYY-MM，收到：{month}')
    return year, month_number


def _parse_datetime(value: str | None, timezone_name: str = DEFAULT_TIMEZONE) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    timezone = ZoneInfo(timezone_name)
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                parsed = datetime.strptime(text, fmt).replace(tzinfo=timezone)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _month_matches(value: str | None, month: str, timezone_name: str = DEFAULT_TIMEZONE) -> bool:
    parsed = _parse_datetime(value, timezone_name)
    if parsed is not None:
        return parsed.strftime('%Y-%m') == month
    text = (value or '').strip()
    return text.startswith(month)


def _coerce_int(value: Any, default: int = 0) -> int:
    if value in (None, ''):
        return default
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_ratio(numerator: int | float, denominator: int | float) -> float | None:
    if not denominator:
        return None
    return round(float(numerator) / float(denominator), 4)


def _format_rate(value: float | None) -> str:
    if value is None:
        return 'n/a'
    return f'{value:.2%}'


def _format_number(value: float | int | None) -> str:
    if value is None:
        return 'n/a'
    if isinstance(value, int):
        return str(value)
    return f'{value:.1f}'


def _slug(value: str) -> str:
    filtered = [character.lower() if character.isalnum() else '-' for character in value]
    slug = ''.join(filtered).strip('-')
    while '--' in slug:
        slug = slug.replace('--', '-')
    return slug or 'value'


def _normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        tags = value
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith('[') and stripped.endswith(']'):
            inner = stripped[1:-1]
            tags = [part.strip().strip('"').strip("'") for part in inner.split(',')]
        else:
            tags = [part.strip() for part in stripped.split(',')]
    else:
        tags = [str(value).strip()]
    return [tag for tag in tags if tag]


def _normalize_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value in (None, ''):
        return {}
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _candidate_paths(paths: Iterable[str | Path], *, suffixes: set[str]) -> list[Path]:
    resolved: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f'输入不存在：{path}')
        if path.is_dir():
            for child in sorted(path.rglob('*')):
                if child.is_file() and child.suffix.lower() in suffixes:
                    resolved.append(child)
            continue
        if path.suffix.lower() not in suffixes:
            raise ValueError(f'不支持的输入格式：{path}')
        resolved.append(path)
    return resolved


def _load_json_payload(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def _rows_from_json_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ('events', 'rows', 'items', 'data'):
            if isinstance(payload.get(key), list):
                return [row for row in payload[key] if isinstance(row, dict)]
        return [payload]
    return []


def _normalize_event_row(row: dict[str, Any]) -> dict[str, Any]:
    metadata = _normalize_metadata(row.get('metadata_json'))
    return {
        'event_type': str(row.get('event_type', '')).strip().lower(),
        'channel': str(row.get('channel', 'unknown')).strip() or 'unknown',
        'anonymous_id': str(row.get('anonymous_id', '') or '').strip(),
        'briefing_id': str(row.get('briefing_id', '') or '').strip(),
        'item_id': str(row.get('item_id', '') or '').strip(),
        'target_url': str(row.get('target_url', '') or '').strip(),
        'duration_ms': _coerce_int(row.get('duration_ms')),
        'metadata_json': metadata,
        'created_at': str(row.get('created_at', '') or '').strip(),
    }


def load_event_rows(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _candidate_paths(paths, suffixes=SUPPORTED_EVENT_SUFFIXES):
        suffix = path.suffix.lower()
        if suffix == '.csv':
            with path.open('r', encoding='utf-8', newline='') as handle:
                reader = csv.DictReader(handle)
                rows.extend(_normalize_event_row(row) for row in reader)
            continue
        if suffix in {'.jsonl', '.ndjson'}:
            for raw_line in path.read_text(encoding='utf-8').splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                rows.append(_normalize_event_row(json.loads(line)))
            continue
        rows.extend(_normalize_event_row(row) for row in _rows_from_json_payload(_load_json_payload(path)))
    return rows


def _normalize_catalog_row(row: dict[str, Any], *, source_path: str | None = None) -> dict[str, Any]:
    tags = _normalize_tags(row.get('tags'))
    topic = str(row.get('topic', '') or '').strip() or (tags[0] if tags else 'untagged')
    briefing_id = str(row.get('briefing_id', '') or '').strip()
    item_id = str(row.get('item_id', '') or '').strip()
    title = str(row.get('title', '') or row.get('heading', '') or item_id or 'Untitled item').strip()
    summary = str(row.get('summary', '') or row.get('snippet', '') or '').strip()
    why_relevant = str(row.get('why_relevant', '') or '').strip()
    published_at = str(row.get('published_at', '') or row.get('published', '') or '').strip()
    return {
        'briefing_id': briefing_id,
        'item_id': item_id,
        'source': str(row.get('source', 'unknown') or 'unknown').strip(),
        'title': title,
        'url': str(row.get('url', '') or '').strip(),
        'tags': tags,
        'topic': topic,
        'summary': summary,
        'why_relevant': why_relevant,
        'published_at': published_at,
        'source_path': source_path or '',
    }


def _resolve_manifest_catalog_path(payload: dict[str, Any], manifest_dir: Path) -> Path | None:
    publication = payload.get('publication')
    hugo_export = publication.get('hugo_export') if isinstance(publication, dict) else None
    hugo_details = hugo_export.get('details') if isinstance(hugo_export, dict) else None
    candidates = [
        payload.get('item_catalog'),
        hugo_details.get('item_catalog') if isinstance(hugo_details, dict) else None,
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        output_path = candidate.get('output_path')
        if not output_path:
            continue
        if not isinstance(output_path, (str, os.PathLike)):
            continue
        try:
            resolved = Path(output_path)
        except TypeError:
            continue
        if not resolved.is_absolute():
            resolved = (manifest_dir / resolved).resolve()
        if resolved.is_file():
            return resolved
    jsonl_output = payload.get('jsonl_output')
    if not jsonl_output:
        return None
    resolved = Path(jsonl_output)
    if not resolved.is_absolute():
        resolved = (manifest_dir / resolved).resolve()
    return resolved


def _load_manifest_catalog(path: Path) -> list[dict[str, Any]]:
    payload = _load_json_payload(path)
    if not isinstance(payload, dict):
        return [_normalize_catalog_row(row, source_path=str(path)) for row in _rows_from_json_payload(payload)]

    catalog_path = _resolve_manifest_catalog_path(payload, path.parent)
    if catalog_path is None:
        return [_normalize_catalog_row(row, source_path=str(path)) for row in _rows_from_json_payload(payload)]

    catalog_rows: list[dict[str, Any]] = []
    for raw_line in catalog_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line:
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            row.setdefault('briefing_id', payload.get('briefing_id', ''))
            catalog_rows.append(_normalize_catalog_row(row, source_path=str(path)))
    return catalog_rows


def _extract_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith('---\n'):
        return {}, text
    marker = '\n---\n'
    end = text.find(marker, 4)
    if end == -1:
        return {}, text
    front_matter = yaml.safe_load(text[4:end]) or {}
    body = text[end + len(marker) :]
    return front_matter if isinstance(front_matter, dict) else {}, body


def _catalog_rows_from_front_matter(front_matter: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in front_matter.get('feedback_items', []) or []:
        if not isinstance(item, dict):
            continue
        heading = item.get('item_id', 'item')
        summary = str(item.get('summary', '') or '').strip()
        why_relevant = str(item.get('why_relevant', '') or '').strip()
        rows.append(
            _normalize_catalog_row(
                {
                    'briefing_id': item.get('briefing_id', ''),
                    'item_id': item.get('item_id', ''),
                    'source': item.get('source', ''),
                    'title': item.get('title', '') or heading,
                    'url': item.get('url', ''),
                    'tags': item.get('tags', []),
                    'topic': item.get('topic', ''),
                    'summary': summary,
                    'why_relevant': why_relevant,
                    'published_at': front_matter.get('date', ''),
                },
                source_path=str(path),
            )
        )
    return rows


def _catalog_rows_from_markdown_body(body: str, path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_summary: list[str] = []
    current_why: list[str] = []
    current_briefing_id = ''

    def flush() -> None:
        nonlocal current, current_summary, current_why
        if not current:
            current_summary = []
            current_why = []
            return
        current['summary'] = ' '.join(part for part in current_summary if part).strip()
        current['why_relevant'] = ' '.join(part for part in current_why if part).strip()
        current['briefing_id'] = current.get('briefing_id') or current_briefing_id
        rows.append(_normalize_catalog_row(current, source_path=str(path)))
        current = None
        current_summary = []
        current_why = []

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith('<!--') and 'briefing_id:' in line:
            current_briefing_id = line.split('briefing_id:', 1)[1].split('-->', 1)[0].strip()
            continue
        if line.startswith('### '):
            flush()
            heading = line.split('｜', 1)[1].strip() if '｜' in line else line[4:].strip()
            current = {
                'briefing_id': current_briefing_id,
                'title': heading,
                'tags': [],
            }
            continue
        if current is None:
            continue
        if line.startswith('- item_id:'):
            current['item_id'] = line.split(':', 1)[1].strip()
            continue
        if line.startswith('- source:'):
            current['source'] = line.split(':', 1)[1].strip()
            continue
        if line.startswith('- url:'):
            current['url'] = line.split(':', 1)[1].strip()
            continue
        if line.startswith('- tags:'):
            current['tags'] = _normalize_tags(line.split(':', 1)[1].strip())
            continue
        if line.startswith('摘要：'):
            current_summary.append(line.split('：', 1)[1].strip())
            continue
        if line.startswith('为什么和小於有关：'):
            current_why.append(line.split('：', 1)[1].strip())
            continue
    flush()
    return rows


def _load_markdown_catalog(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding='utf-8')
    front_matter, body = _extract_front_matter(text)
    rows = _catalog_rows_from_front_matter(front_matter, path)
    if rows:
        return rows
    return _catalog_rows_from_markdown_body(body, path)


def load_catalog_rows(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _candidate_paths(paths, suffixes=SUPPORTED_CATALOG_SUFFIXES):
        suffix = path.suffix.lower()
        if suffix in {'.jsonl', '.ndjson'}:
            for raw_line in path.read_text(encoding='utf-8').splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(_normalize_catalog_row(row, source_path=str(path)))
            continue
        if suffix == '.json':
            rows.extend(_load_manifest_catalog(path))
            continue
        rows.extend(_load_markdown_catalog(path))

    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row['item_id'] or f"{row['briefing_id']}::{row['url']}"
        if not key:
            continue
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = row
            continue
        if not existing.get('summary') and row.get('summary'):
            existing['summary'] = row['summary']
        if not existing.get('why_relevant') and row.get('why_relevant'):
            existing['why_relevant'] = row['why_relevant']
        if not existing.get('source') and row.get('source'):
            existing['source'] = row['source']
        if not existing.get('title') and row.get('title'):
            existing['title'] = row['title']
        merged_tags = list(dict.fromkeys(existing.get('tags', []) + row.get('tags', [])))
        existing['tags'] = merged_tags
        if existing.get('topic') == 'untagged' and row.get('topic'):
            existing['topic'] = row['topic']
    return list(deduped.values())


def _dry_run_catalog(month: str) -> list[dict[str, Any]]:
    return [
        _normalize_catalog_row(
            {
                'briefing_id': f'{month}-10-08',
                'item_id': f'{month}-10-08-001',
                'source': 'Example Feed',
                'title': 'Agent workflow copilots land in customer support',
                'url': 'https://example.com/agent-workflows',
                'tags': ['AI Agent', 'Tooling'],
                'topic': 'AI Agent',
                'summary': 'A practical agent workflow reaches production customer support teams.',
                'why_relevant': 'Shows near-term productized agent workflows instead of vague hype.',
                'published_at': f'{month}-10T08:00:00+08:00',
            },
            source_path='dry-run',
        ),
        _normalize_catalog_row(
            {
                'briefing_id': f'{month}-10-13',
                'item_id': f'{month}-10-13-001',
                'source': 'Example Labs',
                'title': 'Developer tooling teams ship eval pipelines for agents',
                'url': 'https://example.com/agent-evals',
                'tags': ['AI Agent', 'Evaluation'],
                'topic': 'AI Agent',
                'summary': 'Tooling vendors are packaging eval loops for agent reliability.',
                'why_relevant': 'Connects to durable workflow improvements and shipping discipline.',
                'published_at': f'{month}-10T13:00:00+08:00',
            },
            source_path='dry-run',
        ),
        _normalize_catalog_row(
            {
                'briefing_id': f'{month}-12-08',
                'item_id': f'{month}-12-08-001',
                'source': 'Example Robotics',
                'title': 'Retail robotics pilots expand but stall at checkout UX',
                'url': 'https://example.com/robotics-retail',
                'tags': ['Robotics', 'Retail'],
                'topic': 'Robotics',
                'summary': 'More deployments appear, but users still hit operational friction.',
                'why_relevant': 'Useful signal for embodied AI commercialization, but weaker immediate actionability.',
                'published_at': f'{month}-12T08:00:00+08:00',
            },
            source_path='dry-run',
        ),
    ]


def _event_row(
    *,
    month: str,
    day: int,
    slot: str,
    item_index: str,
    event_type: str,
    anonymous_id: str,
    source: str,
    tags: list[str],
    target_url: str,
    duration_ms: int = 0,
    minute: int = 0,
) -> dict[str, Any]:
    return _normalize_event_row(
        {
            'event_type': event_type,
            'channel': 'site',
            'anonymous_id': anonymous_id,
            'briefing_id': f'{month}-{day:02d}-{slot}',
            'item_id': f'{month}-{day:02d}-{slot}-{item_index}',
            'target_url': target_url,
            'duration_ms': duration_ms,
            'metadata_json': {'source': source, 'tags': tags},
            'created_at': f'{month}-{day:02d}T08:{minute:02d}:00+08:00',
        }
    )


def _dry_run_events(month: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ai_agent_viewers = ['anon_a', 'anon_b', 'anon_c', 'anon_d', 'anon_e', 'anon_f']
    for index, anonymous_id in enumerate(ai_agent_viewers):
        rows.append(
            _event_row(
                month=month,
                day=10,
                slot='08',
                item_index='001',
                event_type='impression',
                anonymous_id=anonymous_id,
                source='Example Feed',
                tags=['AI Agent', 'Tooling'],
                target_url='https://example.com/agent-workflows',
                minute=index,
            )
        )
    for anonymous_id in ('anon_a', 'anon_b', 'anon_c', 'anon_d', 'anon_f'):
        rows.append(
            _event_row(
                month=month,
                day=10,
                slot='08',
                item_index='001',
                event_type='click',
                anonymous_id=anonymous_id,
                source='Example Feed',
                tags=['AI Agent', 'Tooling'],
                target_url='https://example.com/agent-workflows',
                minute=10,
            )
        )
    for anonymous_id in ('anon_a', 'anon_b', 'anon_c', 'anon_d'):
        rows.append(
            _event_row(
                month=month,
                day=10,
                slot='08',
                item_index='001',
                event_type='like',
                anonymous_id=anonymous_id,
                source='Example Feed',
                tags=['AI Agent', 'Tooling'],
                target_url='https://example.com/agent-workflows',
                minute=11,
            )
        )
    for anonymous_id in ('anon_a', 'anon_b', 'anon_c', 'anon_d'):
        rows.append(
            _event_row(
                month=month,
                day=10,
                slot='08',
                item_index='001',
                event_type='dwell',
                anonymous_id=anonymous_id,
                source='Example Feed',
                tags=['AI Agent', 'Tooling'],
                target_url='https://example.com/agent-workflows',
                duration_ms=150000,
                minute=12,
            )
        )
    rows.append(
        _event_row(
            month=month,
            day=10,
            slot='08',
            item_index='001',
            event_type='deep_dive',
            anonymous_id='anon_a',
            source='Example Feed',
            tags=['AI Agent', 'Tooling'],
            target_url='https://example.com/agent-workflows',
            minute=13,
        )
    )

    for index, anonymous_id in enumerate(('anon_a', 'anon_b', 'anon_c', 'anon_d', 'anon_g', 'anon_h')):
        rows.append(
            _event_row(
                month=month,
                day=10,
                slot='13',
                item_index='001',
                event_type='impression',
                anonymous_id=anonymous_id,
                source='Example Labs',
                tags=['AI Agent', 'Evaluation'],
                target_url='https://example.com/agent-evals',
                minute=20 + index,
            )
        )
    for anonymous_id in ('anon_a', 'anon_b', 'anon_c', 'anon_h'):
        rows.append(
            _event_row(
                month=month,
                day=10,
                slot='13',
                item_index='001',
                event_type='click',
                anonymous_id=anonymous_id,
                source='Example Labs',
                tags=['AI Agent', 'Evaluation'],
                target_url='https://example.com/agent-evals',
                minute=30,
            )
        )
    for anonymous_id in ('anon_a', 'anon_b', 'anon_c'):
        rows.append(
            _event_row(
                month=month,
                day=10,
                slot='13',
                item_index='001',
                event_type='like',
                anonymous_id=anonymous_id,
                source='Example Labs',
                tags=['AI Agent', 'Evaluation'],
                target_url='https://example.com/agent-evals',
                minute=31,
            )
        )
    for anonymous_id in ('anon_a', 'anon_b', 'anon_c'):
        rows.append(
            _event_row(
                month=month,
                day=10,
                slot='13',
                item_index='001',
                event_type='dwell',
                anonymous_id=anonymous_id,
                source='Example Labs',
                tags=['AI Agent', 'Evaluation'],
                target_url='https://example.com/agent-evals',
                duration_ms=125000,
                minute=32,
            )
        )

    robotics_viewers = ['anon_r1', 'anon_r2', 'anon_r3', 'anon_r4']
    for index, anonymous_id in enumerate(robotics_viewers):
        rows.append(
            _event_row(
                month=month,
                day=12,
                slot='08',
                item_index='001',
                event_type='impression',
                anonymous_id=anonymous_id,
                source='Example Robotics',
                tags=['Robotics', 'Retail'],
                target_url='https://example.com/robotics-retail',
                minute=40 + index,
            )
        )
    for anonymous_id in ('anon_r1', 'anon_r2'):
        rows.append(
            _event_row(
                month=month,
                day=12,
                slot='08',
                item_index='001',
                event_type='click',
                anonymous_id=anonymous_id,
                source='Example Robotics',
                tags=['Robotics', 'Retail'],
                target_url='https://example.com/robotics-retail',
                minute=50,
            )
        )
    for anonymous_id in ('anon_r1', 'anon_r2'):
        rows.append(
            _event_row(
                month=month,
                day=12,
                slot='08',
                item_index='001',
                event_type='dislike',
                anonymous_id=anonymous_id,
                source='Example Robotics',
                tags=['Robotics', 'Retail'],
                target_url='https://example.com/robotics-retail',
                minute=51,
            )
        )
    for anonymous_id in ('anon_r1', 'anon_r2'):
        rows.append(
            _event_row(
                month=month,
                day=12,
                slot='08',
                item_index='001',
                event_type='dwell',
                anonymous_id=anonymous_id,
                source='Example Robotics',
                tags=['Robotics', 'Retail'],
                target_url='https://example.com/robotics-retail',
                duration_ms=9000,
                minute=52,
            )
        )
    return rows


def build_dry_run_inputs(month: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return _dry_run_events(month), _dry_run_catalog(month)


def _catalog_matches_month(row: dict[str, Any], month: str, timezone_name: str) -> bool:
    published_at = _parse_datetime(str(row.get('published_at', '') or '').strip(), timezone_name)
    if published_at is not None:
        return published_at.strftime('%Y-%m') == month
    for value in (row.get('briefing_id'), row.get('item_id')):
        text = str(value or '').strip()
        if len(text) >= 7 and text[4] == '-':
            return text[:7] == month
    return True


def _item_key(briefing_id: str, item_id: str, *, target_url: str = '') -> str:
    if item_id:
        return item_id
    if target_url:
        return f'{briefing_id}::{target_url}'
    return f'{briefing_id}::unknown-item'


def _resolved_item_id(item_row: dict[str, Any]) -> str:
    item_id = str(item_row.get('item_id', '') or '').strip()
    if item_id:
        return item_id
    briefing_id = str(item_row.get('briefing_id', '') or '').strip()
    url_slug = _slug(str(item_row.get('url', '') or '').strip())
    if briefing_id and url_slug != 'value':
        return f'{briefing_id}-uncatalogued-{url_slug}'
    if briefing_id:
        return f'{briefing_id}-uncatalogued'
    if url_slug != 'value':
        return f'uncatalogued-{url_slug}'
    return 'uncatalogued'


def _ensure_item_bucket(
    item_buckets: dict[str, dict[str, Any]],
    *,
    key: str,
    item_row: dict[str, Any],
) -> dict[str, Any]:
    bucket = item_buckets.get(key)
    if bucket is not None:
        return bucket
    bucket = {
        'catalog': item_row,
        'impression_keys': set(),
        'click_keys': set(),
        'like_keys': set(),
        'dislike_keys': set(),
        'read_keys': set(),
        'dwell_keys': set(),
        'deep_dive_keys': set(),
        'dwell_durations': [],
        'noise_flags': set(),
        'channels': set(),
        'anonymous_missing_events': 0,
    }
    item_buckets[key] = bucket
    return bucket


def _event_dedup_key(event: dict[str, Any], *, include_target: bool = False) -> str:
    anonymous_id = event['anonymous_id'] or 'missing-anon'
    day = event['created_at'][:10] if event['created_at'] else 'unknown-day'
    parts = [anonymous_id, event['item_id'] or event['briefing_id'], day]
    if include_target:
        parts.append(event['target_url'])
    return '::'.join(parts)


def _event_to_catalog_row(event: dict[str, Any]) -> dict[str, Any]:
    metadata = event.get('metadata_json', {})
    tags = _normalize_tags(metadata.get('tags'))
    source = str(metadata.get('source', '') or 'unknown').strip()
    topic = tags[0] if tags else 'untagged'
    url_slug = _slug(event.get('target_url', ''))
    item_id = event['item_id'] or (
        f"{event['briefing_id']}-uncatalogued-{url_slug}" if url_slug != 'value' else f"{event['briefing_id']}-uncatalogued"
    )
    title_suffix = event.get('target_url') or item_id
    return _normalize_catalog_row(
        {
            'briefing_id': event['briefing_id'],
            'item_id': item_id,
            'source': source,
            'title': f'Uncatalogued item {title_suffix}',
            'url': event['target_url'],
            'tags': tags,
            'topic': topic,
            'summary': '',
            'why_relevant': '',
            'published_at': event['created_at'],
        },
        source_path='events-only',
    )


def _compute_summary_metrics(bucket: dict[str, Any]) -> dict[str, Any]:
    impressions = len(bucket['impression_keys'])
    clicks = len(bucket['click_keys'])
    likes = len(bucket['like_keys'])
    dislikes = len(bucket['dislike_keys'])
    read_sessions = len(bucket['read_keys'] | bucket['dwell_keys'] | bucket['deep_dive_keys'])
    dwell_events = len(bucket['dwell_keys'])
    deep_dives = len(bucket['deep_dive_keys'])
    durations = sorted(bucket['dwell_durations'])
    avg_dwell_seconds = round(sum(durations) / len(durations), 1) if durations else 0.0
    median_dwell_seconds = round(statistics.median(durations), 1) if durations else 0.0
    if len(durations) >= 2:
        p75_dwell_seconds = round(statistics.quantiles(durations, n=4, method='inclusive')[2], 1)
    elif durations:
        p75_dwell_seconds = round(durations[0], 1)
    else:
        p75_dwell_seconds = 0.0

    rate_basis = 'impressions' if impressions else 'read_sessions'
    denominator = impressions or read_sessions
    metrics = {
        'items_published': 1,
        'impressions': impressions,
        'clicks': clicks,
        'likes': likes,
        'dislikes': dislikes,
        'deep_dives': deep_dives,
        'dwell_events': dwell_events,
        'read_sessions': read_sessions,
        'avg_dwell_seconds': avg_dwell_seconds,
        'median_dwell_seconds': median_dwell_seconds,
        'p75_dwell_seconds': p75_dwell_seconds,
        'click_rate': _safe_ratio(clicks, denominator),
        'like_rate': _safe_ratio(likes, denominator),
        'dislike_rate': _safe_ratio(dislikes, denominator),
        'deep_dive_rate': _safe_ratio(deep_dives, denominator),
        'dwell_rate': _safe_ratio(dwell_events, denominator),
        'negative_feedback_rate': _safe_ratio(dislikes, denominator),
        'feedback_sentiment': _safe_ratio(likes - dislikes, likes + dislikes),
        'rate_basis': rate_basis,
    }
    return metrics


def _sample_status(dimension: str, *, items_published: int, impressions: int, read_sessions: int) -> str:
    thresholds = DIMENSION_THRESHOLDS[dimension]
    decision = thresholds['decision']
    display = thresholds['display']
    if items_published >= decision['items'] and (impressions >= decision['impressions'] or read_sessions >= decision['read_sessions']):
        return 'decision_ready'
    if items_published >= display['items'] and (impressions >= display['impressions'] or read_sessions >= display['read_sessions']):
        return 'observe'
    return 'insufficient_sample'


def _confidence(sample_status: str, noise_flags: set[str], *, anonymous_missing_rate: float) -> str:
    if sample_status == 'insufficient_sample':
        return 'low'
    if anonymous_missing_rate > 0.3 or 'impression_missing' in noise_flags:
        return 'low'
    if sample_status == 'observe' or noise_flags:
        return 'medium'
    return 'high'


def _engagement_score(row: dict[str, Any]) -> float:
    return (
        float(row.get('click_rate') or 0.0)
        + float(row.get('like_rate') or 0.0)
        + float(row.get('deep_dive_rate') or 0.0)
        - float(row.get('negative_feedback_rate') or 0.0)
    )


def analyze_month(
    *,
    month: str,
    event_rows: Iterable[dict[str, Any]],
    catalog_rows: Iterable[dict[str, Any]],
    timezone_name: str = DEFAULT_TIMEZONE,
    dry_run: bool = False,
    input_paths: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    _parse_month(month)
    catalog_rows = [row for row in catalog_rows if _catalog_matches_month(row, month, timezone_name)]
    catalog_index = {
        _item_key(row.get('briefing_id', ''), row.get('item_id', ''), target_url=row.get('url', '')): row
        for row in catalog_rows
        if row.get('item_id') or row.get('briefing_id')
    }
    item_buckets: dict[str, dict[str, Any]] = {}
    uncatalogued_event_count = 0
    for row in catalog_rows:
        key = _item_key(row.get('briefing_id', ''), row.get('item_id', ''), target_url=row.get('url', ''))
        _ensure_item_bucket(item_buckets, key=key, item_row=row)

    filtered_events: list[dict[str, Any]] = []
    anonymous_missing_count = 0
    for event in event_rows:
        if not _month_matches(event.get('created_at'), month, timezone_name):
            continue
        filtered_events.append(event)
        if not event.get('anonymous_id'):
            anonymous_missing_count += 1
        key = _item_key(event.get('briefing_id', ''), event.get('item_id', ''), target_url=event.get('target_url', ''))
        item_row = catalog_index.get(key)
        if item_row is None:
            item_row = _event_to_catalog_row(event)
            catalog_index[key] = item_row
            uncatalogued_event_count += 1
        bucket = _ensure_item_bucket(item_buckets, key=key, item_row=item_row)
        if not event.get('anonymous_id'):
            bucket['anonymous_missing_events'] += 1
            bucket['noise_flags'].add('missing_anonymous_id')
        bucket['channels'].add(event.get('channel', 'unknown'))
        event_type = event.get('event_type')
        if event_type == 'impression':
            bucket['impression_keys'].add(_event_dedup_key(event))
        elif event_type == 'click':
            bucket['click_keys'].add(_event_dedup_key(event, include_target=True))
        elif event_type == 'like':
            bucket['like_keys'].add(_event_dedup_key(event))
        elif event_type == 'dislike':
            bucket['dislike_keys'].add(_event_dedup_key(event))
        elif event_type == 'read':
            bucket['read_keys'].add(_event_dedup_key(event))
        elif event_type == 'dwell':
            key_with_day = _event_dedup_key(event)
            bucket['dwell_keys'].add(key_with_day)
            if event.get('duration_ms'):
                bucket['dwell_durations'].append(round(event['duration_ms'] / 1000, 1))
            if event.get('duration_ms', 0) >= 120000:
                bucket['deep_dive_keys'].add(key_with_day)
                bucket['noise_flags'].add('inferred_deep_dive_from_dwell')
        elif event_type == 'deep_dive':
            bucket['deep_dive_keys'].add(_event_dedup_key(event))
            bucket['read_keys'].add(_event_dedup_key(event))

    dimension_accumulators: dict[str, dict[str, dict[str, Any]]] = {
        'topic': {},
        'source': {},
        'tag': {},
        'item': {},
    }
    item_dimension_rows: list[dict[str, Any]] = []

    total_noise_flags: set[str] = set()
    for bucket in item_buckets.values():
        catalog = bucket['catalog']
        resolved_item_id = _resolved_item_id(catalog)
        metrics = _compute_summary_metrics(bucket)
        noise_flags = set(bucket['noise_flags'])
        if metrics['impressions'] == 0:
            noise_flags.add('impression_missing')
        sample_status = _sample_status(
            'item',
            items_published=metrics['items_published'],
            impressions=metrics['impressions'],
            read_sessions=metrics['read_sessions'],
        )
        anonymous_missing_rate = _safe_ratio(bucket['anonymous_missing_events'], max(1, metrics['impressions'] + metrics['read_sessions'])) or 0.0
        confidence = _confidence(sample_status, noise_flags, anonymous_missing_rate=anonymous_missing_rate)
        row = {
            'value': resolved_item_id,
            'label': catalog['title'],
            'briefing_id': catalog['briefing_id'],
            'source': catalog['source'],
            'topic': catalog['topic'],
            'tags': catalog['tags'],
            'summary': catalog['summary'],
            'why_relevant': catalog['why_relevant'],
            'channels': sorted(bucket['channels']),
            'sample_status': sample_status,
            'confidence': confidence,
            'noise_flags': sorted(noise_flags),
            'anonymous_missing_rate': round(anonymous_missing_rate, 4),
            **metrics,
        }
        item_dimension_rows.append(row)
        total_noise_flags.update(noise_flags)

        dimension_specs = [
            ('topic', catalog['topic']),
            ('source', catalog['source']),
            *[( 'tag', tag) for tag in catalog['tags'] or ['untagged']],
            ('item', resolved_item_id),
        ]
        for dimension, value in dimension_specs:
            accumulator = dimension_accumulators[dimension].setdefault(
                value,
                {
                    'value': value,
                    'labels': set(),
                    'briefing_ids': set(),
                    'item_ids': set(),
                    'sources': set(),
                    'topics': set(),
                    'tags': set(),
                    'channels': set(),
                    'noise_flags': set(),
                    'impressions': 0,
                    'clicks': 0,
                    'likes': 0,
                    'dislikes': 0,
                    'deep_dives': 0,
                    'dwell_events': 0,
                    'read_sessions': 0,
                    'dwell_durations': [],
                    'anonymous_missing_events': 0,
                    'sample_excerpts': [],
                },
            )
            accumulator['labels'].add(catalog['title'])
            accumulator['briefing_ids'].add(catalog['briefing_id'])
            accumulator['item_ids'].add(resolved_item_id)
            accumulator['sources'].add(catalog['source'])
            accumulator['topics'].add(catalog['topic'])
            accumulator['tags'].update(catalog['tags'])
            accumulator['channels'].update(bucket['channels'])
            accumulator['noise_flags'].update(noise_flags)
            accumulator['impressions'] += metrics['impressions']
            accumulator['clicks'] += metrics['clicks']
            accumulator['likes'] += metrics['likes']
            accumulator['dislikes'] += metrics['dislikes']
            accumulator['deep_dives'] += metrics['deep_dives']
            accumulator['dwell_events'] += metrics['dwell_events']
            accumulator['read_sessions'] += metrics['read_sessions']
            accumulator['dwell_durations'].extend(bucket['dwell_durations'])
            accumulator['anonymous_missing_events'] += bucket['anonymous_missing_events']
            if catalog['summary']:
                accumulator['sample_excerpts'].append(catalog['summary'])
            if catalog['why_relevant']:
                accumulator['sample_excerpts'].append(catalog['why_relevant'])

    dimensions: dict[str, list[dict[str, Any]]] = {'item': []}
    dimensions['item'] = sorted(item_dimension_rows, key=lambda row: (_engagement_score(row), row['impressions']), reverse=True)

    for dimension in ('topic', 'source', 'tag'):
        rows: list[dict[str, Any]] = []
        for value, accumulator in dimension_accumulators[dimension].items():
            denominator = accumulator['impressions'] or accumulator['read_sessions']
            durations = sorted(accumulator['dwell_durations'])
            avg_dwell_seconds = round(sum(durations) / len(durations), 1) if durations else 0.0
            median_dwell_seconds = round(statistics.median(durations), 1) if durations else 0.0
            if len(durations) >= 2:
                p75_dwell_seconds = round(statistics.quantiles(durations, n=4, method='inclusive')[2], 1)
            elif durations:
                p75_dwell_seconds = round(durations[0], 1)
            else:
                p75_dwell_seconds = 0.0
            items_published = len(accumulator['item_ids'])
            sample_status = _sample_status(
                dimension,
                items_published=items_published,
                impressions=accumulator['impressions'],
                read_sessions=accumulator['read_sessions'],
            )
            noise_flags = set(accumulator['noise_flags'])
            if accumulator['impressions'] == 0:
                noise_flags.add('impression_missing')
            anonymous_missing_rate = _safe_ratio(
                accumulator['anonymous_missing_events'],
                max(1, accumulator['impressions'] + accumulator['read_sessions']),
            ) or 0.0
            row = {
                'value': value,
                'label': value,
                'items_published': items_published,
                'impressions': accumulator['impressions'],
                'clicks': accumulator['clicks'],
                'likes': accumulator['likes'],
                'dislikes': accumulator['dislikes'],
                'deep_dives': accumulator['deep_dives'],
                'dwell_events': accumulator['dwell_events'],
                'read_sessions': accumulator['read_sessions'],
                'avg_dwell_seconds': avg_dwell_seconds,
                'median_dwell_seconds': median_dwell_seconds,
                'p75_dwell_seconds': p75_dwell_seconds,
                'click_rate': _safe_ratio(accumulator['clicks'], denominator),
                'like_rate': _safe_ratio(accumulator['likes'], denominator),
                'dislike_rate': _safe_ratio(accumulator['dislikes'], denominator),
                'deep_dive_rate': _safe_ratio(accumulator['deep_dives'], denominator),
                'dwell_rate': _safe_ratio(accumulator['dwell_events'], denominator),
                'negative_feedback_rate': _safe_ratio(accumulator['dislikes'], denominator),
                'feedback_sentiment': _safe_ratio(
                    accumulator['likes'] - accumulator['dislikes'],
                    accumulator['likes'] + accumulator['dislikes'],
                ),
                'rate_basis': 'impressions' if accumulator['impressions'] else 'read_sessions',
                'channels': sorted(accumulator['channels']),
                'sample_status': sample_status,
                'confidence': _confidence(sample_status, noise_flags, anonymous_missing_rate=anonymous_missing_rate),
                'noise_flags': sorted(noise_flags),
                'anonymous_missing_rate': round(anonymous_missing_rate, 4),
                'briefing_ids': sorted(item for item in accumulator['briefing_ids'] if item),
                'item_ids': sorted(item for item in accumulator['item_ids'] if item),
                'sources': sorted(item for item in accumulator['sources'] if item),
                'topics': sorted(item for item in accumulator['topics'] if item),
                'tags': sorted(item for item in accumulator['tags'] if item),
                'sample_excerpts': accumulator['sample_excerpts'][:3],
            }
            rows.append(row)
        dimensions[dimension] = sorted(rows, key=lambda row: (_engagement_score(row), row['impressions']), reverse=True)

    totals = {
        'impressions': sum(row['impressions'] for row in dimensions['item']),
        'clicks': sum(row['clicks'] for row in dimensions['item']),
        'likes': sum(row['likes'] for row in dimensions['item']),
        'dislikes': sum(row['dislikes'] for row in dimensions['item']),
        'deep_dives': sum(row['deep_dives'] for row in dimensions['item']),
        'dwell_events': sum(row['dwell_events'] for row in dimensions['item']),
        'read_sessions': sum(row['read_sessions'] for row in dimensions['item']),
    }
    total_denominator = totals['impressions'] or totals['read_sessions'] or 1
    monthly_baseline = {
        'click_rate': _safe_ratio(totals['clicks'], total_denominator) or 0.0,
        'like_rate': _safe_ratio(totals['likes'], total_denominator) or 0.0,
        'negative_feedback_rate': _safe_ratio(totals['dislikes'], total_denominator) or 0.0,
        'deep_dive_rate': _safe_ratio(totals['deep_dives'], total_denominator) or 0.0,
    }
    baseline_score = (
        monthly_baseline['click_rate']
        + monthly_baseline['like_rate']
        + monthly_baseline['deep_dive_rate']
        - monthly_baseline['negative_feedback_rate']
    )

    editor_brief: list[dict[str, Any]] = []
    for dimension in RECOMMENDATION_DIMENSIONS:
        for row in dimensions[dimension]:
            if row['sample_status'] == 'insufficient_sample':
                continue
            score = _engagement_score(row)
            if score >= baseline_score + 0.15:
                action = 'increase'
            elif score <= baseline_score - 0.08 or (row.get('negative_feedback_rate') or 0.0) >= monthly_baseline['negative_feedback_rate'] + 0.08:
                action = 'decrease'
            else:
                action = 'observe'
            rationale = (
                f"{dimension}={row['value']} 的 click_rate {_format_rate(row['click_rate'])}、"
                f"deep_dive_rate {_format_rate(row['deep_dive_rate'])}、"
                f"negative_feedback_rate {_format_rate(row['negative_feedback_rate'])}。"
            )
            editor_brief.append(
                {
                    'dimension': dimension,
                    'value': row['value'],
                    'action': action,
                    'status': 'pending_review',
                    'confidence': row['confidence'],
                    'sample_status': row['sample_status'],
                    'report_type': 'editor_recommendation_brief',
                    'rationale': rationale,
                    'evidence': {
                        'items_published': row['items_published'],
                        'impressions': row['impressions'],
                        'clicks': row['clicks'],
                        'likes': row['likes'],
                        'dislikes': row['dislikes'],
                        'deep_dives': row['deep_dives'],
                    },
                    'editor_review_question': (
                        '该建议是否代表稳定 editorial preference，而非单月热点、单条新闻或一次性异常波动？'
                        if action != 'observe'
                        else '是否需要继续观察一个月，再判断是否值得进入 Editor-owned memory？'
                    ),
                }
            )
    editor_brief = sorted(
        editor_brief,
        key=lambda item: (
            {'increase': 0, 'decrease': 1, 'observe': 2}[item['action']],
            {'high': 0, 'medium': 1, 'low': 2}[item['confidence']],
            -item['evidence']['impressions'],
        ),
    )[:6]

    warnings: list[str] = []
    if uncatalogued_event_count:
        warnings.append(f'{uncatalogued_event_count} 条事件未命中 catalog，已按 metadata 回退聚合。')
    if anonymous_missing_count:
        warnings.append(f'{anonymous_missing_count} 条事件缺少 anonymous_id，用户级去重置信度下降。')
    if totals['impressions'] == 0:
        warnings.append('缺少 impression 事件，所有 rate 使用 read_sessions 作为替代分母。')
    if total_noise_flags:
        warnings.append('存在 inferred deep_dive / impression 缺失等噪声信号，请在 Editor 审核时复核。')

    payload = {
        'month': month,
        'generated_at': datetime.now(UTC).isoformat(timespec='seconds'),
        'summary': {
            'dry_run': dry_run,
            'timezone': timezone_name,
            'catalog_items': len(catalog_index),
            'event_rows': len(filtered_events),
            'briefings': len({row['briefing_id'] for row in dimensions['item'] if row.get('briefing_id')}),
            'editor_brief_count': len(editor_brief),
        },
        'inputs': input_paths or {'events': [], 'catalog': []},
        'thresholds': DIMENSION_THRESHOLDS,
        'monthly_baseline': monthly_baseline,
        'data_quality': {
            'warnings': warnings,
            'anonymous_id_missing_rate': round(_safe_ratio(anonymous_missing_count, len(filtered_events)) or 0.0, 4),
            'uncatalogued_event_count': uncatalogued_event_count,
            'event_types_seen': sorted({row['event_type'] for row in filtered_events}),
        },
        'dimensions': dimensions,
        'editor_brief': editor_brief,
        'totals': totals,
        'editor_memory_workflow': {
            'owner': 'editor_profile',
            'production_path': 'editor_owned_memory_write',
            'repo_apply_supported': False,
            'reason': '月度分析只输出给 Editor 的 recommendation brief；Reporter/Coder/Publisher 不直接写入长期编辑记忆。',
        },
    }
    return payload


def render_markdown_report(payload: dict[str, Any]) -> str:
    month = payload['month']
    summary = payload['summary']
    data_quality = payload['data_quality']
    totals = payload['totals']
    dimensions = payload['dimensions']
    editor_brief = payload['editor_brief']

    lines = [
        f'# NewsBriefingsSystem 月度兴趣分析｜{month}',
        '',
        '## A. 本月摘要',
        '',
        f"- 运行模式：{'dry-run' if summary['dry_run'] else 'input-driven'}",
        f"- 内容样本：briefings={summary['briefings']}，items={summary['catalog_items']}",
        (
            '- 行为样本：'
            f"impressions={totals['impressions']}，clicks={totals['clicks']}，likes={totals['likes']}，"
            f"dislikes={totals['dislikes']}，deep_dives={totals['deep_dives']}，dwell_events={totals['dwell_events']}"
        ),
        f"- Editor memory path：{payload['editor_memory_workflow']['reason']}",
        '',
        '## B. 维度表现',
        '',
    ]

    for dimension_name in ('topic', 'source', 'tag', 'item'):
        lines.append(f'### {dimension_name}')
        lines.append('')
        lines.append('| value | items | impressions | clicks | likes | dislikes | deep_dives | avg_dwell_s | rate_basis | click_rate | like_rate | deep_dive_rate | confidence | sample | warnings |')
        lines.append('| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- | --- | --- |')
        for row in dimensions[dimension_name][:5]:
            warnings = '<br>'.join(row['noise_flags']) if row['noise_flags'] else '—'
            lines.append(
                '| {value} | {items} | {impressions} | {clicks} | {likes} | {dislikes} | {deep_dives} | {avg_dwell} | {rate_basis} | {click_rate} | {like_rate} | {deep_dive_rate} | {confidence} | {sample_status} | {warnings} |'.format(
                    value=row['value'],
                    items=row['items_published'],
                    impressions=row['impressions'],
                    clicks=row['clicks'],
                    likes=row['likes'],
                    dislikes=row['dislikes'],
                    deep_dives=row['deep_dives'],
                    avg_dwell=_format_number(row['avg_dwell_seconds']),
                    rate_basis=row['rate_basis'],
                    click_rate=_format_rate(row['click_rate']),
                    like_rate=_format_rate(row['like_rate']),
                    deep_dive_rate=_format_rate(row['deep_dive_rate']),
                    confidence=row['confidence'],
                    sample_status=row['sample_status'],
                    warnings=warnings,
                )
            )
        if not dimensions[dimension_name]:
            lines.append('| — | 0 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | n/a | n/a | n/a | low | insufficient_sample | no rows |')
        lines.append('')

    lines.extend(
        [
            '## C. Editor recommendation brief',
            '',
        ]
    )
    for brief in editor_brief:
        evidence = brief['evidence']
        lines.extend(
            [
                (
                    f"- [{brief['status']}] {brief['action']} {brief['dimension']}={brief['value']}"
                    f"（confidence={brief['confidence']}，sample={brief['sample_status']}）"
                ),
                f"  - 理由：{brief['rationale']}",
                (
                    '  - 聚合证据：'
                    f"items={evidence['items_published']}，impressions={evidence['impressions']}，clicks={evidence['clicks']}，"
                    f"likes={evidence['likes']}，dislikes={evidence['dislikes']}，deep_dives={evidence['deep_dives']}"
                ),
                '  - 边界：只可作为 Editor brief，不得视为仓库自动 apply 或直接写入 memory 的指令。',
                f"  - Editor 审核问题：{brief['editor_review_question']}",
            ]
        )
    if not editor_brief:
        lines.append('- 无可提交的 Editor brief；建议先补足跨月聚合样本后复跑。')
    lines.append('')

    lines.extend(
        [
            '## D. 数据质量与限制',
            '',
        ]
    )
    for warning in data_quality['warnings'] or ['无额外警告。']:
        lines.append(f'- {warning}')
    lines.extend(
        [
            '- 支持输入：events CSV/JSON/JSONL；catalog JSON/JSONL、run manifest JSON、Markdown/Hugo catalog。',
            '- 当前不会访问真实 D1/Cloudflare，也不会自动写入 Honcho/memory。',
            '- `deep_dive` 缺失时，会使用 `dwell >= 120s` 推断并打上 inferred 噪声提示。',
            '- item 维度仅保留为聚合证据与抽样校验，不会生成可直接迁移为长期偏好的单条新闻建议。',
            '',
        ]
    )
    return '\n'.join(lines).rstrip() + '\n'


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Generate monthly interest insights from feedback exports and item catalogs.')
    parser.add_argument('--month', required=True, help='分析月份，格式 YYYY-MM')
    parser.add_argument('--events', nargs='*', default=[], help='反馈事件输入：CSV / JSON / JSONL 文件或目录')
    parser.add_argument('--catalog', nargs='*', default=[], help='内容目录输入：JSON / JSONL / manifest JSON / Markdown-Hugo 文件或目录')
    parser.add_argument('--timezone', default=DEFAULT_TIMEZONE, help='月份窗口时区，默认 Asia/Shanghai')
    parser.add_argument('--output-root', default=DEFAULT_OUTPUT_ROOT, help='JSON 输出目录，默认 data/monthly_insights')
    parser.add_argument('--docs-root', default=DEFAULT_DOCS_ROOT, help='Markdown 输出目录，默认 docs/monthly-insights')
    parser.add_argument('--dry-run', action='store_true', help='使用内置本地样例数据运行，不依赖 D1/Cloudflare 权限')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    if args.dry_run:
        event_rows, catalog_rows = build_dry_run_inputs(args.month)
        input_paths = {'events': ['dry-run://synthetic-events'], 'catalog': ['dry-run://synthetic-catalog']}
    else:
        if not args.events or not args.catalog:
            raise SystemExit('非 dry-run 模式下必须同时提供 --events 和 --catalog')
        event_rows = load_event_rows(args.events)
        catalog_rows = load_catalog_rows(args.catalog)
        input_paths = {
            'events': [str(Path(path).expanduser()) for path in args.events],
            'catalog': [str(Path(path).expanduser()) for path in args.catalog],
        }

    payload = analyze_month(
        month=args.month,
        event_rows=event_rows,
        catalog_rows=catalog_rows,
        timezone_name=args.timezone,
        dry_run=args.dry_run,
        input_paths=input_paths,
    )
    json_path = Path(args.output_root) / f'{args.month}.json'
    markdown_path = Path(args.docs_root) / f'{args.month}.md'
    dump_json(json_path, payload)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown_report(payload), encoding='utf-8')
    print(f'json={json_path}')
    print(f'markdown={markdown_path}')
    print(f'editor_briefs={len(payload["editor_brief"])}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
