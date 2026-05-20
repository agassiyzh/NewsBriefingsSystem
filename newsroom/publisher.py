from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from .collector import CollectResult
from .config import dump_json, load_yaml, resolve_path
from .ids import normalize_slot, slot_label

SETTLING_HEADER = '## 今日沉淀'
DEFAULT_SETTLING_BODY = '- 趋势：\n- 项目灵感：\n- 投资观察：\n- 可写内容：'
DEFAULT_TELEGRAM_PREVIEWS_DIR = 'data/telegram'
DEFAULT_HUGO_CONTENT_DIR = 'site/content/briefings'
BRIEFING_ID_RE = re.compile(r'<!--\s*briefing_id:\s*([^>]+?)\s*-->')
ITEM_ID_RE = re.compile(r'-\s*item_id:\s*(.+)')
SOURCE_RE = re.compile(r'-\s*source:\s*(.+)')
URL_RE = re.compile(r'-\s*url:\s*(.+)')
TAGS_RE = re.compile(r'-\s*tags:\s*\[(.*)\]')


@dataclass(slots=True)
class PublicationContext:
    briefing_id: str
    slot: str
    briefing_day: str
    timezone_name: str
    archive_path: Path
    collect_result: CollectResult
    system_dir: Path
    path_config: dict[str, str]
    publication_config: dict[str, Any]
    dry_run: bool = True


@dataclass(slots=True)
class PublishResult:
    target: str
    status: str
    output_path: str | None = None
    error: str | None = None
    dry_run: bool = False
    skipped: bool = False
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_manifest(self) -> dict[str, Any]:
        payload = asdict(self)
        if not payload['details']:
            payload['details'] = {}
        return payload


class MarkdownArchivePublisher:
    target = 'markdown_archive'

    def publish(self, context: PublicationContext) -> PublishResult:
        if not context.publication_config.get('markdown_enabled', True):
            return PublishResult(
                target=self.target,
                status='skipped',
                output_path=str(context.archive_path),
                skipped=True,
                details={'reason': 'publication.markdown_enabled=false'},
            )

        if context.dry_run:
            return PublishResult(
                target=self.target,
                status='dry_run',
                output_path=str(context.archive_path),
                dry_run=True,
                details={'reason': 'dry_run: 已保持 Phase 1 兼容，不写入日归档。'},
            )

        update_archive_slot(
            context.archive_path,
            briefing_day=context.briefing_day,
            slot=context.slot,
            result=context.collect_result,
        )
        return PublishResult(
            target=self.target,
            status='updated',
            output_path=str(context.archive_path),
            details={
                'briefing_id': context.briefing_id,
                'candidate_count': len(context.collect_result.candidates),
            },
        )


class TelegramPublisher:
    target = 'telegram'

    def __init__(
        self,
        *,
        preview_path: Path | None = None,
        sender: Callable[[str], Any] | None = None,
        allow_send: bool = False,
    ) -> None:
        self.preview_path = preview_path
        self.sender = sender
        self.allow_send = allow_send

    def publish(self, context: PublicationContext) -> PublishResult:
        if not context.publication_config.get('telegram_enabled', True):
            return PublishResult(
                target=self.target,
                status='skipped',
                skipped=True,
                details={'reason': 'publication.telegram_enabled=false'},
            )

        preview_path = self.preview_path or default_telegram_preview_path(context)
        message = render_telegram_message(context)

        if context.dry_run:
            return PublishResult(
                target=self.target,
                status='dry_run',
                output_path=str(preview_path),
                dry_run=True,
                details={
                    'reason': 'dry_run: Telegram 目标仅记录状态，不生成本地预览文件。',
                    'message_length': len(message),
                },
            )

        preview_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.write_text(message + '\n', encoding='utf-8')

        if not self.allow_send or self.sender is None:
            return PublishResult(
                target=self.target,
                status='dry_run',
                output_path=str(preview_path),
                dry_run=True,
                details={
                    'reason': 'safe-local publisher: 仅生成 Telegram 预览，不执行真实发送。',
                    'message_length': len(message),
                },
            )

        try:
            self.sender(message)
        except Exception as exc:  # noqa: BLE001
            return PublishResult(
                target=self.target,
                status='failed',
                output_path=str(preview_path),
                error=str(exc),
                retryable=True,
                details={'reason': 'sender raised exception'},
            )
        return PublishResult(
            target=self.target,
            status='sent',
            output_path=str(preview_path),
            details={'message_length': len(message)},
        )


class HugoExportPublisher:
    target = 'hugo_export'

    def __init__(self, *, output_path: Path | None = None) -> None:
        self.output_path = output_path

    def publish(self, context: PublicationContext) -> PublishResult:
        if not context.publication_config.get('hugo_export_enabled', True):
            return PublishResult(
                target=self.target,
                status='skipped',
                skipped=True,
                details={'reason': 'publication.hugo_export_enabled=false'},
            )

        output_path = self.output_path or default_hugo_output_path(context)
        if context.dry_run:
            return PublishResult(
                target=self.target,
                status='dry_run',
                output_path=str(output_path),
                dry_run=True,
                details={
                    'reason': 'dry_run: 保持 Phase 1 兼容，当前不生成 Hugo 导出文件。',
                    'item_count': len(context.collect_result.candidates),
                },
            )

        metadata = export_archive_to_hugo(
            archive_path=context.archive_path,
            output_path=output_path,
            briefing_day=context.briefing_day,
            timezone_name=context.timezone_name,
        )
        return PublishResult(
            target=self.target,
            status='updated',
            output_path=str(output_path),
            details=metadata,
        )


def archive_title(briefing_day: str) -> str:
    return f'# 新闻雷达｜{briefing_day}'


def slot_header(slot: str) -> str:
    return f'## {slot_label(slot)}'


def ordered_archive_headers() -> list[str]:
    return [slot_header('morning'), slot_header('noon'), slot_header('evening'), SETTLING_HEADER]


def render_archive_slot(result: CollectResult) -> str:
    lines = [f'<!-- briefing_id: {result.briefing_id} -->', '']
    if not result.candidates:
        lines.append('_本版次暂无候选新闻。_')
        return '\n'.join(lines).rstrip()

    for index, candidate in enumerate(result.candidates, start=1):
        lines.append(f"### {index}｜{candidate['title']}")
        lines.append('')
        lines.append(f"- item_id: {candidate['item_id']}")
        lines.append(f"- source: {candidate['source']}")
        lines.append(f"- url: {candidate['url']}")
        if candidate.get('published'):
            lines.append(f"- published: {candidate['published']}")
        if candidate.get('tags'):
            lines.append(f"- tags: [{', '.join(candidate['tags'])}]")
        if candidate.get('keywords'):
            lines.append(f"- keywords: [{', '.join(candidate['keywords'])}]")
        if candidate.get('status') == 'error':
            lines.append('- status: error')
        if candidate.get('error'):
            lines.append(f"- error: {candidate['error']}")
        if candidate.get('snippet'):
            lines.append('')
            lines.append(f"摘要：{candidate['snippet']}")
        lines.append('')
    return '\n'.join(lines).rstrip()


def parse_archive_sections(text: str, briefing_day: str) -> tuple[str, dict[str, str]]:
    title = archive_title(briefing_day)
    headers = ordered_archive_headers()
    sections = {header: [] for header in headers}
    current_header: str | None = None

    for raw_line in text.splitlines():
        if raw_line.startswith('# 新闻雷达｜') and current_header is None:
            title = raw_line.strip()
            continue
        if raw_line in headers:
            current_header = raw_line
            continue
        if current_header is not None:
            sections[current_header].append(raw_line)

    return title, {header: '\n'.join(lines).strip() for header, lines in sections.items()}


def compose_archive_text(briefing_day: str, sections: dict[str, str], title: str | None = None) -> str:
    lines = [title or archive_title(briefing_day), '']
    for header in ordered_archive_headers():
        body = sections.get(header, '').strip()
        if header == SETTLING_HEADER and not body:
            body = DEFAULT_SETTLING_BODY
        lines.append(header)
        lines.append('')
        if body:
            lines.extend(body.splitlines())
            lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def update_archive_slot(archive_path: Path, *, briefing_day: str, slot: str, result: CollectResult) -> None:
    existing_text = archive_path.read_text(encoding='utf-8') if archive_path.exists() else ''
    title, sections = parse_archive_sections(existing_text, briefing_day)
    sections[slot_header(slot)] = render_archive_slot(result)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(compose_archive_text(briefing_day, sections, title=title), encoding='utf-8')


def default_telegram_preview_path(context: PublicationContext) -> Path:
    relative = context.path_config.get('telegram_previews_dir', DEFAULT_TELEGRAM_PREVIEWS_DIR)
    return resolve_path(context.system_dir, relative) / f'{context.briefing_id}.txt'


def default_hugo_output_path(context: PublicationContext) -> Path:
    relative = context.path_config.get('hugo_content_dir', DEFAULT_HUGO_CONTENT_DIR)
    return resolve_path(context.system_dir, relative) / context.briefing_day[:4] / f'{context.briefing_day}.md'


def render_telegram_message(context: PublicationContext) -> str:
    lines = [f'新闻雷达｜{context.briefing_day} {slot_label(context.slot)}', '']
    if not context.collect_result.candidates:
        lines.append('本版次暂无候选新闻。')
        return '\n'.join(lines)

    for index, candidate in enumerate(context.collect_result.candidates, start=1):
        lines.append(f"{index}｜{candidate['title']}")
        if candidate.get('snippet'):
            lines.append(f"极简摘要：{candidate['snippet']}")
        if candidate.get('tags'):
            lines.append(f"标签：{', '.join(candidate['tags'])}")
        lines.append(f"链接：{candidate['url']}")
        lines.append('')
    lines.append('今日信号：详见 Markdown/Hugo 归档，当前仅生成 Telegram dry-run 预览。')
    return '\n'.join(lines).strip()


def _parse_archive_slot_metadata(section_body: str) -> tuple[str | None, list[dict[str, Any]]]:
    lines = section_body.splitlines()
    briefing_id: str | None = None
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if briefing_id is None:
            match = BRIEFING_ID_RE.match(line)
            if match:
                briefing_id = match.group(1).strip()
                continue
        if line.startswith('### '):
            if current:
                items.append(current)
            current = {'heading': line[4:].strip()}
            continue
        if current is None:
            continue
        if match := ITEM_ID_RE.match(line):
            current['item_id'] = match.group(1).strip()
            continue
        if match := SOURCE_RE.match(line):
            current['source'] = match.group(1).strip()
            continue
        if match := URL_RE.match(line):
            current['url'] = match.group(1).strip()
            continue
        if match := TAGS_RE.match(line):
            tags = [part.strip() for part in match.group(1).split(',') if part.strip()]
            current['tags'] = tags
    if current:
        items.append(current)
    return briefing_id, items


def _front_matter_datetime(briefing_day: str, timezone_name: str) -> str:
    offset = '+08:00' if timezone_name == 'Asia/Shanghai' else '+00:00'
    return f'{briefing_day}T08:00:00{offset}'


def export_archive_to_hugo(
    *,
    archive_path: str | Path,
    output_path: str | Path,
    briefing_day: str,
    timezone_name: str,
) -> dict[str, Any]:
    archive_text = Path(archive_path).read_text(encoding='utf-8')
    title, sections = parse_archive_sections(archive_text, briefing_day)

    slots: list[dict[str, Any]] = []
    feedback_items: list[dict[str, Any]] = []
    item_ids: list[str] = []
    sources: set[str] = set()
    tags: set[str] = set()
    total_items = 0
    primary_briefing_id: str | None = None

    for header in ordered_archive_headers():
        body = sections.get(header, '').strip()
        if header == SETTLING_HEADER:
            continue
        briefing_id, items = _parse_archive_slot_metadata(body)
        slot_name = normalize_slot(header.removeprefix('## ').strip())
        if primary_briefing_id is None and briefing_id:
            primary_briefing_id = briefing_id
        total_items += len(items)
        for item in items:
            if item.get('item_id'):
                item_ids.append(item['item_id'])
            if item.get('source'):
                sources.add(item['source'])
            for tag in item.get('tags', []):
                tags.add(tag)
            feedback_items.append(
                {
                    'slot': slot_name,
                    'briefing_id': briefing_id,
                    'item_id': item.get('item_id'),
                    'source': item.get('source'),
                    'url': item.get('url'),
                    'tags': list(item.get('tags', [])),
                }
            )
        slots.append(
            {
                'slot': slot_name,
                'label': slot_label(slot_name),
                'briefing_id': briefing_id,
                'item_count': len(items),
            }
        )

    front_matter = {
        'title': title.removeprefix('# ').strip(),
        'date': _front_matter_datetime(briefing_day, timezone_name),
        'briefing_day': briefing_day,
        'timezone': timezone_name,
        'item_count': total_items,
        'item_ids': item_ids,
        'sources': sorted(sources),
        'tags': sorted(tags),
        'feedback_primary_briefing_id': primary_briefing_id,
        'feedback_items': feedback_items,
        'slots': slots,
        'draft': False,
    }

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    front_matter_text = yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True).strip()
    output.write_text(f'---\n{front_matter_text}\n---\n\n{archive_text.rstrip()}\n', encoding='utf-8')
    return {
        'briefing_day': briefing_day,
        'item_count': total_items,
        'item_ids': item_ids,
        'sources': sorted(sources),
        'tags': sorted(tags),
        'feedback_primary_briefing_id': primary_briefing_id,
        'feedback_item_count': len(feedback_items),
    }


def build_publication_context(
    *,
    briefing_id: str,
    slot: str,
    timezone_name: str,
    archive_path: str | Path,
    collect_result: CollectResult,
    system_dir: str | Path,
    path_config: dict[str, str],
    publication_config: dict[str, Any],
    dry_run: bool,
) -> PublicationContext:
    briefing_day = '-'.join(briefing_id.split('-')[:3])
    return PublicationContext(
        briefing_id=briefing_id,
        slot=normalize_slot(slot),
        briefing_day=briefing_day,
        timezone_name=timezone_name,
        archive_path=Path(archive_path),
        collect_result=collect_result,
        system_dir=Path(system_dir),
        path_config=path_config,
        publication_config=publication_config,
        dry_run=dry_run,
    )


def collect_result_from_jsonl(jsonl_path: str | Path, *, briefing_id: str) -> CollectResult:
    candidates = []
    path = Path(jsonl_path)
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        if raw_line.strip():
            candidates.append(json.loads(raw_line))
    return CollectResult(
        briefing_id=briefing_id,
        collected_at='',
        candidates=candidates,
        markdown='',
        error_count=sum(1 for row in candidates if row.get('status') == 'error'),
        errors=[
            {
                'source': row.get('source', ''),
                'url': row.get('url', ''),
                'error': row.get('error', ''),
            }
            for row in candidates
            if row.get('status') == 'error'
        ],
    )


def load_context_from_manifest(manifest_path: str | Path) -> tuple[PublicationContext, dict[str, Any]]:
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    newsroom_config = load_yaml(manifest['newsroom_config_path'])
    system_dir = newsroom_config.get('system', {}).get('system_dir') or Path(manifest['newsroom_config_path']).resolve().parents[1]
    collect_result = collect_result_from_jsonl(manifest['jsonl_output'], briefing_id=manifest['briefing_id'])
    path_config = dict(newsroom_config.get('paths', {}))
    publication_config = dict(newsroom_config.get('publication', {}))
    context = build_publication_context(
        briefing_id=manifest['briefing_id'],
        slot=manifest['slot'],
        timezone_name=manifest['timezone'],
        archive_path=manifest['archive_path'],
        collect_result=collect_result,
        system_dir=system_dir,
        path_config=path_config,
        publication_config=publication_config,
        dry_run=bool(manifest.get('dry_run', False)),
    )
    return context, manifest


def store_publication_results(manifest_path: str | Path, results: Iterable[PublishResult]) -> dict[str, Any]:
    manifest_file = Path(manifest_path)
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    publication = dict(manifest.get('publication', {}))
    for result in results:
        publication[result.target] = result.to_manifest()
    manifest['publication'] = publication
    dump_json(manifest_file, manifest)
    return manifest


def build_export_hugo_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Export a daily NewsBriefings archive into Hugo content markdown.')
    parser.add_argument('--manifest', default=None, help='run manifest 路径；提供后可自动解析 archive 与输出目录')
    parser.add_argument('--archive', default=None, help='日归档 Markdown 路径')
    parser.add_argument('--briefing-day', default=None, help='归档日期 YYYY-MM-DD；默认从 manifest 或 archive 文件名推断')
    parser.add_argument('--timezone', default=None, help='front matter 时区标识；manifest 模式默认沿用 manifest.timezone')
    parser.add_argument('--output', default=None, help='Hugo content 输出文件路径')
    return parser


def export_hugo_main(argv: list[str] | None = None) -> int:
    args = build_export_hugo_argument_parser().parse_args(argv)

    manifest_path: str | None = None
    result: PublishResult
    if args.manifest:
        context, _ = load_context_from_manifest(args.manifest)
        manifest_path = str(args.manifest)
        archive_path = context.archive_path
        output_path = Path(args.output) if args.output else default_hugo_output_path(context)
        briefing_day = args.briefing_day or context.briefing_day
        timezone_name = args.timezone or context.timezone_name
        if context.dry_run:
            result = PublishResult(
                target='hugo_export',
                status='dry_run',
                output_path=str(output_path),
                dry_run=True,
                details={
                    'reason': 'dry_run: manifest 标记为 dry-run，CLI 不生成 Hugo 文件。',
                    'item_count': len(context.collect_result.candidates),
                },
            )
        else:
            metadata = export_archive_to_hugo(
                archive_path=archive_path,
                output_path=output_path,
                briefing_day=briefing_day,
                timezone_name=timezone_name,
            )
            result = PublishResult(
                target='hugo_export',
                status='updated',
                output_path=str(Path(output_path)),
                details=metadata,
            )
    else:
        if not args.archive:
            raise SystemExit('--archive 或 --manifest 至少提供一个')
        archive_path = Path(args.archive)
        briefing_day = args.briefing_day or archive_path.stem
        timezone_name = args.timezone or 'Asia/Shanghai'
        output_path = Path(args.output) if args.output else Path(DEFAULT_HUGO_CONTENT_DIR) / briefing_day[:4] / f'{briefing_day}.md'
        metadata = export_archive_to_hugo(
            archive_path=archive_path,
            output_path=output_path,
            briefing_day=briefing_day,
            timezone_name=timezone_name,
        )
        result = PublishResult(
            target='hugo_export',
            status='updated',
            output_path=str(Path(output_path)),
            details=metadata,
        )

    if manifest_path is not None:
        store_publication_results(manifest_path, [result])
    print(f'output={Path(output_path).resolve()}')
    print(f'item_count={result.details.get("item_count", 0)}')
    return 0


def build_publish_telegram_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Render a Telegram publication preview from a run manifest.')
    parser.add_argument('--manifest', required=True, help='run manifest 路径')
    parser.add_argument('--preview-output', default=None, help='可选：覆盖默认 Telegram 预览输出路径')
    return parser


def publish_telegram_main(argv: list[str] | None = None) -> int:
    args = build_publish_telegram_argument_parser().parse_args(argv)
    context, manifest = load_context_from_manifest(args.manifest)
    preview_path = Path(args.preview_output) if args.preview_output else None
    publisher = TelegramPublisher(preview_path=preview_path)
    result = publisher.publish(context)
    store_publication_results(args.manifest, [result])
    manifest_path = Path(args.manifest).resolve()
    print(f'manifest={manifest_path}')
    print(f'status={result.status}')
    if result.output_path:
        print(f'preview={result.output_path}')
    if result.error:
        print(f'error={result.error}')
    _ = manifest
    return 0
