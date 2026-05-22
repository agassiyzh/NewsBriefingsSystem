from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .collector import (
    DEFAULT_MAX_TOTAL,
    collect_candidates,
    read_existing_summary,
    write_jsonl,
    write_markdown,
)
from .config import (
    default_system_dir,
    dump_json,
    load_yaml,
    merged_paths,
    resolve_cli_path,
    resolve_path,
    resolve_runtime,
    resolve_system_dir,
)
from .editor import compose_briefing
from .ids import build_briefing_id, normalize_slot, slot_label
from .publisher import (
    HugoExportPublisher,
    MarkdownArchivePublisher,
    PublishResult,
    TelegramPublisher,
    build_publication_context,
    default_hugo_output_path,
    default_item_catalog_path,
    default_telegram_preview_path,
)


@dataclass(slots=True)
class RunResult:
    briefing_id: str
    slot: str
    manifest_path: str
    jsonl_output: str
    markdown_output: str
    log_path: str


def append_log(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat(timespec='seconds')
    with log_path.open('a', encoding='utf-8') as handle:
        handle.write(f'[{timestamp}] {message}\n')


def run_briefing(
    *,
    config_path: str | Path,
    sources_path: str | Path,
    interests_path: str | Path,
    slot: str,
    dry_run: bool = True,
    briefing_id: str | None = None,
    fetcher=None,
    now=None,
) -> RunResult:
    newsroom_config = load_yaml(config_path)
    sources_config = load_yaml(sources_path)
    interests_config = load_yaml(interests_path)
    normalized_slot = normalize_slot(slot)
    system_dir = resolve_system_dir(config_path, newsroom_config)
    timezone_name = newsroom_config.get('system', {}).get('timezone', 'Asia/Shanghai')
    runtime = resolve_runtime(now, timezone_name)
    resolved_briefing_id = briefing_id or build_briefing_id(runtime.date(), normalized_slot)
    briefing_day = '-'.join(resolved_briefing_id.split('-')[:3])

    system_cfg = newsroom_config.get('system', {})
    archive_dir = resolve_path(system_dir, system_cfg.get('archive_dir', '/opt/data/home/NewsBriefings'))
    archive_path = archive_dir / f'{briefing_day}.md'
    path_cfg = merged_paths(newsroom_config)
    candidates_dir = resolve_path(system_dir, path_cfg['candidates_dir'])
    contexts_dir = resolve_path(system_dir, path_cfg['contexts_dir'])
    briefings_dir = resolve_path(system_dir, path_cfg['briefings_dir'])
    runs_dir = resolve_path(system_dir, path_cfg['runs_dir'])
    logs_dir = resolve_path(system_dir, path_cfg['logs_dir'])
    log_path = logs_dir / f'{briefing_day}.log'

    append_log(log_path, f'run start briefing_id={resolved_briefing_id} slot={normalized_slot} dry_run={dry_run}')
    result = collect_candidates(
        briefing_id=resolved_briefing_id,
        slot=normalized_slot,
        source_defs=sources_config.get('sources', []),
        interest_defs=interests_config.get('interests', []),
        existing_summary=read_existing_summary(archive_dir, briefing_day),
        fetcher=fetcher,
        collected_at=runtime.astimezone(UTC).isoformat(timespec='seconds'),
        max_total=int(newsroom_config.get('collection', {}).get('max_total', DEFAULT_MAX_TOTAL)),
    )

    jsonl_output = candidates_dir / f'{resolved_briefing_id}.jsonl'
    markdown_output = contexts_dir / f'{resolved_briefing_id}.md'
    manifest_path = runs_dir / f'{resolved_briefing_id}.json'

    write_jsonl(jsonl_output, result.candidates)
    write_markdown(markdown_output, result.markdown)

    curated_briefing = compose_briefing(
        result,
        slot=normalized_slot,
        generated_at=runtime.astimezone(UTC).isoformat(timespec='seconds'),
        default_channel=str(newsroom_config.get('feedback', {}).get('default_channel', 'unknown')),
    )
    curated_output = briefings_dir / f'{resolved_briefing_id}.json'
    dump_json(curated_output, curated_briefing.to_dict())

    publication_context = build_publication_context(
        briefing_id=resolved_briefing_id,
        slot=normalized_slot,
        timezone_name=timezone_name,
        archive_path=archive_path,
        collect_result=result,
        system_dir=system_dir,
        path_config=path_cfg,
        publication_config=newsroom_config.get('publication', {}),
        curated_briefing=curated_briefing,
        dry_run=dry_run,
    )

    markdown_result = MarkdownArchivePublisher().publish(publication_context)
    if dry_run:
        telegram_result = PublishResult(
            target='telegram',
            status='dry_run',
            output_path=str(default_telegram_preview_path(publication_context)),
            dry_run=True,
            details={'reason': 'dry_run: runner 不生成 Telegram 预览文件，但保留目标状态。'},
        )
        hugo_result = PublishResult(
            target='hugo_export',
            status='dry_run',
            output_path=str(default_hugo_output_path(publication_context)),
            dry_run=True,
            details={
                'reason': 'dry_run: runner 不生成 Hugo 文件，但保留目标状态。',
                'item_catalog': {
                    'status': 'dry_run',
                    'output_path': str(default_item_catalog_path(publication_context)),
                    'item_count': curated_briefing.curated_item_count,
                },
            },
        )
    else:
        hugo_result = HugoExportPublisher().publish(publication_context)
        telegram_result = TelegramPublisher().publish(publication_context)
    publish_results = [markdown_result, telegram_result, hugo_result]
    publication_status = {publish_result.target: publish_result.to_manifest() for publish_result in publish_results}
    item_catalog_status = dict(hugo_result.details.get('item_catalog', {}))
    if not item_catalog_status:
        item_catalog_status = {
            'status': 'dry_run' if dry_run else 'skipped',
            'output_path': str(default_item_catalog_path(publication_context)),
            'item_count': curated_briefing.curated_item_count,
        }

    manifest = {
        'run_id': resolved_briefing_id,
        'briefing_id': resolved_briefing_id,
        'slot': normalized_slot,
        'slot_label': slot_label(normalized_slot),
        'started_at': runtime.astimezone(UTC).isoformat(timespec='seconds'),
        'timezone': timezone_name,
        'dry_run': dry_run,
        'archive_path': str(archive_path.resolve()),
        'jsonl_output': str(jsonl_output),
        'markdown_output': str(markdown_output),
        'curated_output': str(curated_output),
        'log_path': str(log_path),
        'candidate_count': len(result.candidates),
        'curated_item_count': curated_briefing.curated_item_count,
        'editor_version': curated_briefing.editor_version,
        'error_count': result.error_count,
        'errors': result.errors,
        'sources_path': str(Path(sources_path).resolve()),
        'interests_path': str(Path(interests_path).resolve()),
        'newsroom_config_path': str(Path(config_path).resolve()),
        'publication': publication_status,
        'item_catalog': item_catalog_status,
    }
    dump_json(manifest_path, manifest)
    append_log(
        log_path,
        'run complete '
        f'briefing_id={resolved_briefing_id} candidates={len(result.candidates)} errors={result.error_count} '
        f'markdown_archive={publication_status["markdown_archive"]["status"]} '
        f'telegram={publication_status["telegram"]["status"]} '
        f'hugo_export={publication_status["hugo_export"]["status"]}',
    )

    return RunResult(
        briefing_id=resolved_briefing_id,
        slot=normalized_slot,
        manifest_path=str(manifest_path),
        jsonl_output=str(jsonl_output),
        markdown_output=str(markdown_output),
        log_path=str(log_path),
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Manual newsroom Phase 2 runner (collect + publish adapters).')
    parser.add_argument('--config', default='config/newsroom.yaml', help='newsroom.yaml 路径')
    parser.add_argument('--sources', default='config/sources.yaml', help='sources.yaml 路径')
    parser.add_argument('--interests', default='config/interests.yaml', help='interests.yaml 路径')
    parser.add_argument('--slot', default='morning', help='morning|noon|evening 或对应时间别名')
    parser.add_argument('--briefing-id', default=None, help='可选：手动指定 briefing_id=YYYY-MM-DD-HH')
    parser.add_argument('--dry-run', action='store_true', help='仅采集并输出 manifest，不写回日归档，也不生成 Telegram/Hugo 文件')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    fallback_system_dir = default_system_dir()
    config_path = resolve_cli_path(args.config, default_relative='config/newsroom.yaml', system_dir=fallback_system_dir)
    newsroom_config = load_yaml(config_path)
    system_dir = resolve_system_dir(config_path, newsroom_config)
    sources_path = resolve_cli_path(args.sources, default_relative='config/sources.yaml', system_dir=system_dir)
    interests_path = resolve_cli_path(args.interests, default_relative='config/interests.yaml', system_dir=system_dir)

    result = run_briefing(
        config_path=config_path,
        sources_path=sources_path,
        interests_path=interests_path,
        slot=args.slot,
        briefing_id=args.briefing_id,
        dry_run=args.dry_run,
    )
    print(f'briefing_id={result.briefing_id}')
    print(f'manifest={result.manifest_path}')
    print(f'jsonl={result.jsonl_output}')
    print(f'markdown={result.markdown_output}')
    print(f'log={result.log_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
