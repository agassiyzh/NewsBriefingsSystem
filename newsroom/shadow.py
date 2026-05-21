from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import yaml

from .config import (
    default_system_dir,
    dump_json,
    load_yaml,
    resolve_cli_path,
    resolve_runtime,
    resolve_system_dir,
)
from .ids import build_briefing_id, normalize_slot, slot_label
from .publisher import parse_archive_sections, parse_archive_slot_metadata, slot_header
from .runner import RunResult, run_briefing


PROSE_ITEM_RE = re.compile(r'^(?P<index>\d+)\.\s+(?:\*\*(?P<bold>.+?)\*\*|(?P<plain>.+))$')
URL_RE = re.compile(r'https?://\S+')
PROSE_SECTION_BREAK_PREFIXES = ('**项目灵感**', '**投资观察**', '**今日信号**', '**行动/观察**')


@dataclass(slots=True)
class CompareReport:
    briefing_id: str
    slot: str
    markdown_path: str
    json_path: str


def _shadow_relative_paths() -> dict[str, str]:
    return {
        'candidates_dir': 'data/candidates',
        'contexts_dir': 'data/contexts',
        'runs_dir': 'data/runs',
        'logs_dir': 'logs',
        'telegram_previews_dir': 'data/telegram',
        'hugo_content_dir': 'site/content/briefings',
        'item_catalog_dir': 'data/item_catalog',
    }


def _resolve_shadow_dir(config_path: str | Path, shadow_dir: str | Path | None) -> Path:
    newsroom_config = load_yaml(config_path)
    project_root = resolve_system_dir(config_path, newsroom_config)
    if shadow_dir is None:
        return (project_root / 'data' / 'shadow').resolve()
    candidate = Path(shadow_dir).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (project_root / candidate).resolve()


def _build_shadow_config(
    *,
    source_config_path: Path,
    shadow_dir: Path,
) -> Path:
    newsroom_config = load_yaml(source_config_path)
    system_cfg = dict(newsroom_config.get('system', {}))
    system_cfg['system_dir'] = str(shadow_dir)
    system_cfg['archive_dir'] = str((shadow_dir / 'archive').resolve())
    newsroom_config['system'] = system_cfg
    newsroom_config['paths'] = _shadow_relative_paths()

    config_dir = shadow_dir / 'config'
    config_dir.mkdir(parents=True, exist_ok=True)
    target = config_dir / 'newsroom.shadow.yaml'
    target.write_text(yaml.safe_dump(newsroom_config, sort_keys=False, allow_unicode=True), encoding='utf-8')
    return target


def _resolve_briefing_id(
    *,
    slot: str,
    timezone_name: str,
    briefing_id: str | None,
    briefing_date: str | None,
    now: datetime | None,
) -> str | None:
    if briefing_id:
        return briefing_id
    if briefing_date:
        return build_briefing_id(date.fromisoformat(briefing_date), slot)
    if now is None:
        return None
    return build_briefing_id(resolve_runtime(now, timezone_name).date(), slot)


def run_shadow_briefing(
    *,
    config_path: str | Path,
    sources_path: str | Path,
    interests_path: str | Path,
    slot: str,
    shadow_dir: str | Path | None = None,
    briefing_id: str | None = None,
    date: str | None = None,
    dry_run: bool = False,
    fetcher=None,
    now: datetime | None = None,
) -> RunResult:
    source_config_path = Path(config_path).expanduser().resolve()
    shadow_root = _resolve_shadow_dir(source_config_path, shadow_dir)
    shadow_root.mkdir(parents=True, exist_ok=True)

    source_config = load_yaml(source_config_path)
    normalized_slot = normalize_slot(slot)
    timezone_name = source_config.get('system', {}).get('timezone', 'Asia/Shanghai')
    resolved_briefing_id = _resolve_briefing_id(
        slot=normalized_slot,
        timezone_name=timezone_name,
        briefing_id=briefing_id,
        briefing_date=date,
        now=now,
    )
    shadow_config_path = _build_shadow_config(source_config_path=source_config_path, shadow_dir=shadow_root)
    return run_briefing(
        config_path=shadow_config_path,
        sources_path=sources_path,
        interests_path=interests_path,
        slot=normalized_slot,
        briefing_id=resolved_briefing_id,
        dry_run=dry_run,
        fetcher=fetcher,
        now=now,
    )


def _load_jsonl_rows(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in Path(path).read_text(encoding='utf-8').splitlines():
        if raw_line.strip():
            rows.append(json.loads(raw_line))
    return rows


def _normalize_topic(row: dict[str, Any]) -> str:
    topic = str(row.get('topic', '') or '').strip()
    if topic:
        return topic
    tags = [str(tag).strip() for tag in row.get('tags', []) if str(tag).strip()]
    if tags:
        return tags[0]
    return 'untagged'


def _duplicate_summary(rows: Iterable[dict[str, Any]]) -> tuple[int, float, list[dict[str, Any]]]:
    prepared = list(rows)
    counter: Counter[str] = Counter()
    label_by_key: dict[str, str] = {}
    for row in prepared:
        title = str(row.get('title', '') or '').strip()
        url = str(row.get('url', '') or '').strip()
        key = f'{title.casefold()}|{url}'
        if not title and not url:
            continue
        counter[key] += 1
        label_by_key[key] = title or url
    duplicates = [
        {'key': label_by_key[key], 'count': count}
        for key, count in sorted(counter.items(), key=lambda item: (-item[1], label_by_key[item[0]]))
        if count > 1
    ]
    duplicate_count = sum(item['count'] - 1 for item in duplicates)
    duplicate_rate = duplicate_count / len(prepared) if prepared else 0.0
    return duplicate_count, duplicate_rate, duplicates


def _failed_sources(rows: Iterable[dict[str, Any]], extra_failures: Iterable[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    failures = [
        {
            'source': str(row.get('source', '') or 'unknown-source'),
            'url': str(row.get('url', '') or ''),
            'error': str(row.get('error', '') or ''),
        }
        for row in rows
        if str(row.get('status', '') or '').strip() == 'error' or str(row.get('error', '') or '').strip()
    ]
    for row in extra_failures or []:
        failure = {
            'source': str(row.get('source', '') or 'unknown-source'),
            'url': str(row.get('url', '') or ''),
            'error': str(row.get('error', '') or ''),
        }
        if failure['error'] or failure['url'] or failure['source'] != 'unknown-source':
            failures.append(failure)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in sorted(failures, key=lambda row: (row['source'], row['url'], row['error'])):
        key = (row['source'], row['url'], row['error'])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _distribution(rows: Iterable[dict[str, Any]], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        if field == 'topic':
            counter[_normalize_topic(row)] += 1
            continue
        value = str(row.get(field, '') or '').strip()
        if value:
            counter[value] += 1
    return dict(sorted(counter.items()))


def _tag_distribution(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        for tag in row.get('tags', []):
            value = str(tag).strip()
            if value:
                counter[value] += 1
    return dict(sorted(counter.items()))


def _missing_item_ids(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    titles = [str(row.get('title', '') or '').strip() for row in rows if not str(row.get('item_id', '') or '').strip()]
    return {'count': len(titles), 'titles': titles}


def _summarize_rows(rows: list[dict[str, Any]], *, extra_failures: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
    duplicate_count, duplicate_rate, duplicates = _duplicate_summary(rows)
    return {
        'item_count': len(rows),
        'topic_counts': _distribution(rows, 'topic'),
        'tag_counts': _tag_distribution(rows),
        'source_counts': _distribution(rows, 'source'),
        'duplicate_count': duplicate_count,
        'duplicate_rate': duplicate_rate,
        'duplicates': duplicates,
        'missing_item_ids': _missing_item_ids(rows),
        'failed_sources': _failed_sources(rows, extra_failures=extra_failures),
    }


def _briefing_day_from_id(briefing_id: str) -> str:
    parts = str(briefing_id).split('-')
    if len(parts) < 4:
        raise ValueError(f'invalid briefing_id: {briefing_id!r}')
    return '-'.join(parts[:3])


def _clean_url(value: str) -> str:
    cleaned = value.rstrip('.,，。；;')
    while cleaned.endswith(')') and cleaned.count('(') < cleaned.count(')'):
        cleaned = cleaned[:-1]
    return cleaned


def _parse_prose_legacy_items(section_body: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    detail_lines: list[str] = []
    in_postamble = False

    def flush() -> None:
        nonlocal current, detail_lines
        if current is None:
            detail_lines = []
            return
        details = ' '.join(line.strip() for line in detail_lines if line.strip())
        urls = [_clean_url(match) for match in URL_RE.findall(details)]
        rows.append(
            {
                'heading': current['title'],
                'title': current['title'],
                'url': urls[0] if urls else '',
                'summary': details,
            }
        )
        current = None
        detail_lines = []

    for raw_line in section_body.splitlines():
        line = raw_line.strip()
        is_indented = bool(raw_line[:1].isspace())
        if not line:
            continue
        if in_postamble:
            continue
        if current is not None and not is_indented and line.startswith(PROSE_SECTION_BREAK_PREFIXES):
            flush()
            in_postamble = True
            continue
        if not is_indented and (match := PROSE_ITEM_RE.match(line)):
            flush()
            title = (match.group('bold') or match.group('plain') or '').strip()
            current = {'title': title}
            continue
        if current is None:
            continue
        detail_lines.append(line)

    flush()
    return rows


def _legacy_rows_for_slot(archive_path: str | Path, slot: str, *, manifest_briefing_id: str) -> list[dict[str, Any]]:
    archive_file = Path(archive_path)
    briefing_day = archive_file.stem
    manifest_day = _briefing_day_from_id(manifest_briefing_id)
    if briefing_day != manifest_day:
        raise ValueError(
            f'legacy archive {archive_file} day {briefing_day!r} does not match manifest day {manifest_day!r}'
        )

    archive_text = archive_file.read_text(encoding='utf-8')
    header = slot_header(slot)
    if not any(line.strip() == header for line in archive_text.splitlines()):
        raise ValueError(f'legacy archive {archive_file} missing slot section {header!r}')

    title, sections = parse_archive_sections(archive_text, briefing_day)
    del title
    section_body = sections.get(header, '').strip()
    expected_briefing_id = build_briefing_id(date.fromisoformat(briefing_day), slot)
    if expected_briefing_id != manifest_briefing_id:
        raise ValueError(
            f'legacy archive {archive_file} slot {slot!r} implies briefing_id {expected_briefing_id!r}, '
            f'but manifest expects {manifest_briefing_id!r}'
        )

    parsed_briefing_id, items = parse_archive_slot_metadata(section_body)
    if parsed_briefing_id is not None and parsed_briefing_id != manifest_briefing_id:
        raise ValueError(
            f'legacy archive {archive_file} briefing_id {parsed_briefing_id!r} does not match '
            f'manifest briefing_id {manifest_briefing_id!r}'
        )
    if items:
        return items
    normalized_section = '\n'.join(line.strip() for line in section_body.splitlines() if line.strip())
    if normalized_section == '_本版次暂无候选新闻。_':
        return []
    if parsed_briefing_id is not None:
        normalized_empty_slot = f'<!-- briefing_id: {parsed_briefing_id} -->\n_本版次暂无候选新闻。_'
        if normalized_section == normalized_empty_slot:
            return []

    prose_items = _parse_prose_legacy_items(section_body)
    if prose_items:
        return prose_items

    raise ValueError(
        f'legacy archive {archive_file} slot {header!r} is unparseable for compare; '
        'expected structured archive metadata or the current production prose format'
    )


def _shadow_output_dir(manifest_path: Path, output_dir: str | Path | None) -> Path:
    if output_dir is not None:
        target = Path(output_dir).expanduser()
        return target.resolve() if target.is_absolute() else (manifest_path.parent.parent.parent / target).resolve()
    return (manifest_path.parent.parent.parent / 'reports').resolve()


def _render_distribution_table(payload: dict[str, int]) -> list[str]:
    lines = ['| Value | Count |', '| --- | ---: |']
    if not payload:
        lines.append('| _none_ | 0 |')
    else:
        for key, value in payload.items():
            lines.append(f'| {key} | {value} |')
    lines.append('')
    return lines


def _render_failed_sources_section(name: str, payload: list[dict[str, Any]]) -> list[str]:
    lines = [f'### {name}', '']
    if not payload:
        lines.append('- none')
        lines.append('')
        return lines
    for row in payload:
        lines.append(f"- {row['source']} | {row['url']} | {row['error']}")
    lines.append('')
    return lines


def _render_compare_markdown(report: dict[str, Any]) -> str:
    legacy = report['legacy']
    shadow = report['shadow']
    lines = [
        f"# Shadow compare report — {report['briefing_id']} ({slot_label(report['slot'])})",
        '',
        '## Item counts',
        '',
        f"- Legacy archive: {legacy['item_count']}",
        f"- Shadow run: {shadow['item_count']}",
        f"- Delta: {shadow['item_count'] - legacy['item_count']}",
        '',
        '## Duplicate rate',
        '',
        f"- Legacy archive: {legacy['duplicate_count']} duplicates ({legacy['duplicate_rate']:.2%})",
        f"- Shadow run: {shadow['duplicate_count']} duplicates ({shadow['duplicate_rate']:.2%})",
        '',
        '## Missing item_id',
        '',
        f"- Legacy archive: {legacy['missing_item_ids']['count']}",
        f"- Shadow run: {shadow['missing_item_ids']['count']}",
        '',
        '## Topic distribution',
        '',
        '### Legacy archive',
        '',
    ]
    lines.extend(_render_distribution_table(legacy['topic_counts']))
    lines.extend(['### Shadow run', ''])
    lines.extend(_render_distribution_table(shadow['topic_counts']))
    lines.extend(['## Tag distribution', '', '### Legacy archive', ''])
    lines.extend(_render_distribution_table(legacy['tag_counts']))
    lines.extend(['### Shadow run', ''])
    lines.extend(_render_distribution_table(shadow['tag_counts']))
    lines.extend(['## Source distribution', '', '### Legacy archive', ''])
    lines.extend(_render_distribution_table(legacy['source_counts']))
    lines.extend(['### Shadow run', ''])
    lines.extend(_render_distribution_table(shadow['source_counts']))
    lines.append('## Failed sources')
    lines.append('')
    lines.extend(_render_failed_sources_section('Legacy archive', legacy['failed_sources']))
    lines.extend(_render_failed_sources_section('Shadow run', shadow['failed_sources']))
    return '\n'.join(lines).rstrip() + '\n'


def compare_shadow_run(
    *,
    legacy_archive_path: str | Path,
    shadow_manifest_path: str | Path,
    slot: str | None = None,
    output_dir: str | Path | None = None,
) -> CompareReport:
    manifest_path = Path(shadow_manifest_path).expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest_slot = normalize_slot(manifest['slot'])
    if slot is not None:
        requested_slot = normalize_slot(slot)
        if requested_slot != manifest_slot:
            raise ValueError(
                f'slot override {requested_slot!r} conflicts with manifest slot {manifest_slot!r}; '
                'pass the matching manifest or omit --slot'
            )
    resolved_slot = manifest_slot
    briefing_id = str(manifest['briefing_id'])
    shadow_rows = _load_jsonl_rows(manifest['jsonl_output'])
    legacy_rows = _legacy_rows_for_slot(legacy_archive_path, resolved_slot, manifest_briefing_id=briefing_id)
    manifest_failures = manifest.get('errors', [])

    report = {
        'briefing_id': briefing_id,
        'slot': resolved_slot,
        'legacy_archive_path': str(Path(legacy_archive_path).expanduser().resolve()),
        'shadow_manifest_path': str(manifest_path),
        'legacy': _summarize_rows(legacy_rows),
        'shadow': _summarize_rows(shadow_rows, extra_failures=manifest_failures),
    }

    report_dir = _shadow_output_dir(manifest_path, output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = report_dir / f'{briefing_id}-compare.md'
    json_path = report_dir / f'{briefing_id}-compare.json'
    markdown_path.write_text(_render_compare_markdown(report), encoding='utf-8')
    dump_json(json_path, report)
    return CompareReport(
        briefing_id=briefing_id,
        slot=resolved_slot,
        markdown_path=str(markdown_path),
        json_path=str(json_path),
    )


def build_run_shadow_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Run the newsroom pipeline inside an isolated shadow directory.')
    parser.add_argument('--config', default='config/newsroom.yaml', help='newsroom.yaml 路径')
    parser.add_argument('--sources', default='config/sources.yaml', help='sources.yaml 路径')
    parser.add_argument('--interests', default='config/interests.yaml', help='interests.yaml 路径')
    parser.add_argument('--shadow-dir', default=None, help='shadow 输出根目录；默认 data/shadow')
    parser.add_argument('--slot', default='morning', help='morning|noon|evening 或对应时间别名')
    parser.add_argument('--briefing-id', default=None, help='可选：手动指定 briefing_id=YYYY-MM-DD-HH')
    parser.add_argument('--date', default=None, help='可选：手动指定日期 YYYY-MM-DD，与 --slot 组合生成 briefing_id')
    parser.add_argument('--dry-run', action='store_true', help='仅采集并输出 manifest，不写 shadow archive/telegram/hugo 文件')
    return parser


def run_shadow_main(argv: list[str] | None = None) -> int:
    args = build_run_shadow_argument_parser().parse_args(argv)
    fallback_system_dir = default_system_dir()
    config_path = resolve_cli_path(args.config, default_relative='config/newsroom.yaml', system_dir=fallback_system_dir)
    newsroom_config = load_yaml(config_path)
    system_dir = resolve_system_dir(config_path, newsroom_config)
    sources_path = resolve_cli_path(args.sources, default_relative='config/sources.yaml', system_dir=system_dir)
    interests_path = resolve_cli_path(args.interests, default_relative='config/interests.yaml', system_dir=system_dir)
    result = run_shadow_briefing(
        config_path=config_path,
        sources_path=sources_path,
        interests_path=interests_path,
        shadow_dir=args.shadow_dir,
        slot=args.slot,
        briefing_id=args.briefing_id,
        date=args.date,
        dry_run=args.dry_run,
    )
    print(f'briefing_id={result.briefing_id}')
    print(f'manifest={result.manifest_path}')
    print(f'jsonl={result.jsonl_output}')
    print(f'markdown={result.markdown_output}')
    print(f'log={result.log_path}')
    return 0


def build_compare_shadow_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Compare a legacy archive slot against a shadow run manifest.')
    parser.add_argument('--legacy-archive', required=True, help='旧链路日归档 Markdown 路径')
    parser.add_argument('--shadow-manifest', required=True, help='shadow run manifest 路径')
    parser.add_argument('--slot', default=None, help='可选：覆盖 manifest.slot')
    parser.add_argument('--output-dir', default=None, help='可选：报告输出目录；默认 <shadow>/reports')
    return parser


def compare_shadow_main(argv: list[str] | None = None) -> int:
    args = build_compare_shadow_argument_parser().parse_args(argv)
    report = compare_shadow_run(
        legacy_archive_path=args.legacy_archive,
        shadow_manifest_path=args.shadow_manifest,
        slot=args.slot,
        output_dir=args.output_dir,
    )
    print(f'briefing_id={report.briefing_id}')
    print(f'slot={report.slot}')
    print(f'markdown={report.markdown_path}')
    print(f'json={report.json_path}')
    return 0
