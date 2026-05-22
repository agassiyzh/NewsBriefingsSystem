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
from .editor import CuratedBriefing, CuratedItem, load_curated_briefing
from .ids import normalize_slot, slot_label

SETTLING_HEADER = '## 今日沉淀'
DEFAULT_SETTLING_BODY = '- 趋势：\n- 项目灵感：\n- 投资观察：\n- 可写内容：'
DEFAULT_TELEGRAM_PREVIEWS_DIR = 'data/telegram'
DEFAULT_HUGO_CONTENT_DIR = 'site/content/briefings'
DEFAULT_ITEM_CATALOG_DIR = 'data/item_catalog'
BRIEFING_ID_RE = re.compile(r'<!--\s*briefing_id:\s*([^>]+?)\s*-->')
ITEM_ID_RE = re.compile(r'-\s*item_id:\s*(.+)')
SOURCE_RE = re.compile(r'-\s*source:\s*(.+)')
URL_RE = re.compile(r'-\s*url:\s*(.+)')
PUBLISHED_RE = re.compile(r'-\s*published:\s*(.+)')
TAGS_RE = re.compile(r'-\s*tags:\s*\[(.*)\]')
TOPIC_RE = re.compile(r'-\s*topic:\s*(.+)')
WHY_RELEVANT_RE = re.compile(r'-\s*why_relevant:\s*(.+)')
ACTION_OR_OBSERVE_RE = re.compile(r'-\s*action_or_observe:\s*(.+)')
SELECTION_REASON_RE = re.compile(r'-\s*selection_reason:\s*(.+)')
CHANNEL_RE = re.compile(r'-\s*channel:\s*(.+)')
STATUS_RE = re.compile(r'-\s*status:\s*(.+)')
ERROR_RE = re.compile(r'-\s*error:\s*(.+)')
ITEM_HEADING_RE = re.compile(r'###\s+(.+)')
SUMMARY_PREFIX = '摘要：'


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
    curated_briefing: CuratedBriefing | None = None
    dry_run: bool = True


def feedback_ui_enabled(publication_config: dict[str, Any]) -> bool:
    return bool(publication_config.get('feedback_ui_enabled', False))


def public_briefing_url(context: PublicationContext) -> str | None:
    base_url = str(context.publication_config.get('public_site_base_url', '') or '').strip()
    if not base_url:
        return None
    return f"{base_url.rstrip('/')}/briefings/{context.briefing_day[:4]}/{context.briefing_day}/"


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
            briefing=context.curated_briefing,
            include_feedback_ui=feedback_ui_enabled(context.publication_config),
        )
        return PublishResult(
            target=self.target,
            status='updated',
            output_path=str(context.archive_path),
            details={
                'briefing_id': context.briefing_id,
                'candidate_count': len(context.collect_result.candidates),
                'curated_item_count': (
                    context.curated_briefing.curated_item_count if context.curated_briefing is not None else len(context.collect_result.candidates)
                ),
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
        item_catalog_path = default_item_catalog_path(context)
        if context.dry_run:
            item_count = (
                context.curated_briefing.curated_item_count
                if context.curated_briefing is not None
                else len(context.collect_result.candidates)
            )
            return PublishResult(
                target=self.target,
                status='dry_run',
                output_path=str(output_path),
                dry_run=True,
                details={
                    'reason': 'dry_run: 保持 Phase 1 兼容，当前不生成 Hugo 导出文件。',
                    'item_count': item_count,
                    'item_catalog': {
                        'status': 'dry_run',
                        'output_path': str(item_catalog_path),
                        'item_count': item_count,
                    },
                },
            )

        include_feedback = feedback_ui_enabled(context.publication_config)
        if context.curated_briefing is not None:
            metadata = export_curated_briefing_to_hugo(
                briefing=context.curated_briefing,
                output_path=output_path,
                archive_path=context.archive_path,
                briefing_day=context.briefing_day,
                timezone_name=context.timezone_name,
                item_catalog_path=item_catalog_path,
                include_feedback_ui=include_feedback,
            )
        else:
            metadata = export_archive_to_hugo(
                archive_path=context.archive_path,
                output_path=output_path,
                briefing_day=context.briefing_day,
                timezone_name=context.timezone_name,
                item_catalog_path=item_catalog_path,
                include_feedback_ui=include_feedback,
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


def render_archive_slot(
    result: CollectResult,
    briefing: CuratedBriefing | None = None,
    *,
    include_feedback_ui: bool = False,
) -> str:
    briefing_id = briefing.briefing_id if briefing is not None else result.briefing_id
    lines = [f'<!-- briefing_id: {briefing_id} -->', '']
    if briefing is not None:
        if not briefing.items:
            lines.append('_本版次暂无精选新闻。_')
            return '\n'.join(lines).rstrip()

        if briefing.today_signals:
            lines.append('今日信号：')
            for signal in briefing.today_signals:
                lines.append(f'- {signal}')
            lines.append('')

        for item in briefing.items:
            lines.append(f"### {item.rank}｜{item.title}")
            lines.append('')
            lines.append(f'- item_id: {item.item_id}')
            lines.append(f'- source: {item.source}')
            lines.append(f'- url: {item.url}')
            if item.published:
                lines.append(f'- published: {item.published}')
            if item.tags:
                lines.append(f"- tags: [{', '.join(item.tags)}]")
            if item.topic:
                lines.append(f'- topic: {item.topic}')
            lines.append(f'- why_relevant: {item.why_relevant}')
            lines.append(f'- action_or_observe: {item.action_or_observe}')
            lines.append(f'- selection_reason: {item.selection_reason}')
            channel = str(item.feedback_metadata.get('channel', '') or '')
            if channel:
                lines.append(f'- channel: {channel}')
            if item.rewritten_summary:
                lines.append('')
                lines.append(f'摘要：{item.rewritten_summary}')
            tags_param = ','.join(item.tags)
            if include_feedback_ui:
                lines.append('')
                lines.append(
                    '{{< item-feedback '
                    f'briefing_id="{item.briefing_id}" '
                    f'item_id="{item.item_id}" '
                    f'source="{item.source}" '
                    f'tags="{tags_param}" '
                    '>}}'
                )
                lines.append('')
        return '\n'.join(lines).rstrip()

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
        tags_param = ','.join(candidate.get('tags', []))
        if include_feedback_ui:
            lines.append('')
            lines.append(
                '{{< item-feedback '
                f'briefing_id="{result.briefing_id}" '
                f'item_id="{candidate['item_id']}" '
                f'source="{candidate.get('source', '')}" '
                f'tags="{tags_param}" '
                '>}}'
            )
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


def update_archive_slot(
    archive_path: Path,
    *,
    briefing_day: str,
    slot: str,
    result: CollectResult,
    briefing: CuratedBriefing | None = None,
    include_feedback_ui: bool = False,
) -> None:
    existing_text = archive_path.read_text(encoding='utf-8') if archive_path.exists() else ''
    title, sections = parse_archive_sections(existing_text, briefing_day)
    sections[slot_header(slot)] = render_archive_slot(result, briefing, include_feedback_ui=include_feedback_ui)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(compose_archive_text(briefing_day, sections, title=title), encoding='utf-8')


def default_telegram_preview_path(context: PublicationContext) -> Path:
    relative = context.path_config.get('telegram_previews_dir', DEFAULT_TELEGRAM_PREVIEWS_DIR)
    return resolve_path(context.system_dir, relative) / f'{context.briefing_id}.txt'


def default_hugo_output_path(context: PublicationContext) -> Path:
    relative = context.path_config.get('hugo_content_dir', DEFAULT_HUGO_CONTENT_DIR)
    return resolve_path(context.system_dir, relative) / context.briefing_day[:4] / f'{context.briefing_day}.md'


def default_item_catalog_path(context: PublicationContext) -> Path:
    relative = context.path_config.get('item_catalog_dir', DEFAULT_ITEM_CATALOG_DIR)
    return resolve_path(context.system_dir, relative) / context.briefing_day[:4] / f'{context.briefing_day}.jsonl'


def compact_public_briefing_url(context: PublicationContext) -> str | None:
    if not context.publication_config.get('hugo_export_enabled', True):
        return None
    return public_briefing_url(context)


def _render_compact_telegram_message(
    context: PublicationContext,
    *,
    summary_line: str,
    briefing_url: str,
    today_signals: Iterable[str] | None = None,
) -> str:
    lines = [f'新闻雷达｜{context.briefing_day} {slot_label(context.slot)}', '']
    lines.append(summary_line)

    compact_signals = [str(signal).strip() for signal in (today_signals or []) if str(signal).strip()][:3]
    if compact_signals:
        lines.extend(['', '今日信号：'])
        for signal in compact_signals:
            lines.append(f'- {signal}')

    lines.extend(['', f'完整简报：{briefing_url}'])
    return '\n'.join(lines)



def render_telegram_message(context: PublicationContext) -> str:
    briefing_url = compact_public_briefing_url(context)
    if context.curated_briefing is not None:
        briefing = context.curated_briefing
        if briefing_url is not None:
            summary_line = f'本版精选 {len(briefing.items)} 条。' if briefing.items else '本版次暂无精选新闻。'
            return _render_compact_telegram_message(
                context,
                summary_line=summary_line,
                briefing_url=briefing_url,
                today_signals=briefing.today_signals,
            )

        lines = [f'新闻雷达｜{context.briefing_day} {slot_label(context.slot)}', '']
        if not briefing.items:
            lines.append('本版次暂无精选新闻。')
            return '\n'.join(lines)

        if briefing.today_signals:
            lines.append('今日信号：')
            for signal in briefing.today_signals:
                lines.append(f'- {signal}')
            lines.append('')

        for item in briefing.items:
            lines.append(f'{item.rank}｜{item.title}')
            if item.rewritten_summary:
                lines.append(f'极简摘要：{item.rewritten_summary}')
            if item.why_relevant:
                lines.append(f'为什么值得看：{item.why_relevant}')
            if item.action_or_observe:
                lines.append(f'动作建议：{item.action_or_observe}')
            if item.tags:
                lines.append(f"标签：{', '.join(item.tags)}")
            lines.append(f'链接：{item.url}')
            lines.append('')
        return '\n'.join(lines).strip()

    if briefing_url is not None:
        candidate_count = len(context.collect_result.candidates)
        summary_line = f'本版收录 {candidate_count} 条候选。' if candidate_count > 0 else '本版次暂无候选新闻。'
        return _render_compact_telegram_message(
            context,
            summary_line=summary_line,
            briefing_url=briefing_url,
        )

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


def _item_title_from_heading(heading: str) -> str:
    prefix, separator, remainder = heading.partition('｜')
    if separator and prefix.strip().isdigit() and remainder.strip():
        return remainder.strip()
    return heading.strip()


def parse_archive_slot_metadata(section_body: str) -> tuple[str | None, list[dict[str, Any]]]:
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
            heading = line[4:].strip()
            current = {'heading': heading, 'title': _item_title_from_heading(heading)}
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
        if match := PUBLISHED_RE.match(line):
            current['published'] = match.group(1).strip()
            continue
        if match := TAGS_RE.match(line):
            tags = [part.strip() for part in match.group(1).split(',') if part.strip()]
            current['tags'] = tags
            continue
        if match := TOPIC_RE.match(line):
            current['topic'] = match.group(1).strip()
            continue
        if match := WHY_RELEVANT_RE.match(line):
            current['why_relevant'] = match.group(1).strip()
            continue
        if match := ACTION_OR_OBSERVE_RE.match(line):
            current['action_or_observe'] = match.group(1).strip()
            continue
        if match := SELECTION_REASON_RE.match(line):
            current['selection_reason'] = match.group(1).strip()
            continue
        if match := CHANNEL_RE.match(line):
            current['channel'] = match.group(1).strip()
            continue
        if match := STATUS_RE.match(line):
            current['status'] = match.group(1).strip()
            continue
        if match := ERROR_RE.match(line):
            current['error'] = match.group(1).strip()
            continue
        if line.startswith(SUMMARY_PREFIX):
            current['summary'] = line.removeprefix(SUMMARY_PREFIX).strip()
    if current:
        items.append(current)
    return briefing_id, items


def _front_matter_datetime(briefing_day: str, timezone_name: str) -> str:
    offset = '+08:00' if timezone_name == 'Asia/Shanghai' else '+00:00'
    return f'{briefing_day}T08:00:00{offset}'


def build_item_catalog_rows(briefing_day: str, slot_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in slot_rows:
        item = entry['item']
        heading = str(item.get('heading', ''))
        title = str(item.get('title') or _item_title_from_heading(heading))
        tags = list(item.get('tags', []))
        row = {
            'briefing_day': briefing_day,
            'slot': entry['slot'],
            'slot_label': slot_label(entry['slot']),
            'briefing_id': entry.get('briefing_id'),
            'item_id': item.get('item_id'),
            'title': title,
            'source': item.get('source'),
            'url': item.get('url'),
            'tags': tags,
            'topic': item.get('topic') or (tags[0] if tags else ''),
            'summary': item.get('summary', ''),
            'published': item.get('published', ''),
        }
        if 'why_relevant' in item:
            row['why_relevant'] = item.get('why_relevant', '')
        if 'action_or_observe' in item:
            row['action_or_observe'] = item.get('action_or_observe', '')
        rows.append(row)
    return rows


def write_item_catalog(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('w', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')


def _shortcode_attr_value(value: str) -> str:
    return value.replace('\\', '\\\\').replace('"', '\\"')


def _render_item_feedback_shortcode(item: dict[str, Any], briefing_id: str | None) -> str:
    if not briefing_id or not item.get('item_id'):
        return ''
    tags_param = ','.join(item.get('tags', []))
    attrs = {
        'briefing_id': briefing_id,
        'item_id': item['item_id'],
        'source': item.get('source', '') or '',
        'tags': tags_param,
    }
    attr_text = ' '.join(f'{key}="{_shortcode_attr_value(value)}"' for key, value in attrs.items())
    return f'{{{{< item-feedback {attr_text} >}}}}'


def _render_news_item_card(
    item_lines: list[str],
    item: dict[str, Any] | None,
    briefing_id: str | None,
    *,
    include_feedback_ui: bool = False,
) -> list[str]:
    if not item_lines:
        return []
    if not item or not item.get('item_id'):
        return item_lines
    rendered = [f'<section class="news-item-card" data-news-item-id="{_shortcode_attr_value(item["item_id"])}">']
    rendered.extend(item_lines)
    shortcode = _render_item_feedback_shortcode(item, briefing_id) if include_feedback_ui else ''
    if shortcode:
        rendered.append('')
        rendered.append(shortcode)
    rendered.append('</section>')
    return rendered


def _display_line(raw_line: str) -> str | None:
    stripped = raw_line.strip()
    if match := WHY_RELEVANT_RE.match(stripped):
        return f'为什么相关：{match.group(1).strip()}'
    if match := ACTION_OR_OBSERVE_RE.match(stripped):
        return f'行动建议：{match.group(1).strip()}'
    if match := SELECTION_REASON_RE.match(stripped):
        return f'入选原因：{match.group(1).strip()}'
    if CHANNEL_RE.match(stripped):
        return None
    return raw_line


def render_hugo_content_with_inline_feedback(
    archive_text: str,
    briefing_day: str,
    *,
    include_feedback_ui: bool = False,
) -> str:
    """Render archive Markdown with optional feedback shortcodes after each news item."""
    title, sections = parse_archive_sections(archive_text, briefing_day)
    lines = [title, '']
    for header in ordered_archive_headers():
        body = sections.get(header, '').strip()
        if not body and header == SETTLING_HEADER:
            body = DEFAULT_SETTLING_BODY
        lines.append(header)
        lines.append('')
        if header == SETTLING_HEADER:
            if body:
                lines.extend(body.splitlines())
                lines.append('')
            continue

        briefing_id, items = parse_archive_slot_metadata(body)
        item_by_heading = {item.get('heading'): item for item in items if item.get('heading')}
        current_item: dict[str, Any] | None = None
        current_item_lines: list[str] = []
        for raw_line in body.splitlines():
            heading_match = ITEM_HEADING_RE.match(raw_line.strip())
            if heading_match:
                lines.extend(
                    _render_news_item_card(
                        current_item_lines,
                        current_item,
                        briefing_id,
                        include_feedback_ui=include_feedback_ui,
                    )
                )
                current_item = item_by_heading.get(heading_match.group(1).strip())
                current_item_lines = [raw_line]
                continue
            if current_item is not None:
                if raw_line.strip().startswith('{{< item-feedback'):
                    continue
                rendered_line = _display_line(raw_line)
                if rendered_line is not None:
                    current_item_lines.append(rendered_line)
                continue
            rendered_line = _display_line(raw_line)
            if rendered_line is not None:
                lines.append(rendered_line)

        lines.extend(
            _render_news_item_card(
                current_item_lines,
                current_item,
                briefing_id,
                include_feedback_ui=include_feedback_ui,
            )
        )
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def _curated_slot_rows(briefing: CuratedBriefing) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in briefing.items:
        rows.append(
            {
                'slot': briefing.slot,
                'briefing_id': briefing.briefing_id,
                'item': {
                    'heading': f'{item.rank}｜{item.title}',
                    'title': item.title,
                    'item_id': item.item_id,
                    'source': item.source,
                    'url': item.url,
                    'published': item.published,
                    'tags': list(item.tags),
                    'topic': item.topic,
                    'summary': item.rewritten_summary,
                    'why_relevant': item.why_relevant,
                    'action_or_observe': item.action_or_observe,
                    'selection_reason': item.selection_reason,
                    'channel': item.feedback_metadata.get('channel', ''),
                },
            }
        )
    return rows


def _compose_curated_archive_text(
    briefing: CuratedBriefing,
    briefing_day: str,
    *,
    include_feedback_ui: bool = False,
) -> str:
    return compose_archive_text(
        briefing_day,
        {
            slot_header(briefing.slot): render_archive_slot(
                CollectResult(
                    briefing_id=briefing.briefing_id,
                    collected_at=briefing.generated_at,
                    candidates=[],
                    markdown='',
                    error_count=0,
                    errors=[],
                ),
                briefing,
                include_feedback_ui=include_feedback_ui,
            )
        },
    )



def export_curated_briefing_to_hugo(
    *,
    briefing: CuratedBriefing,
    output_path: str | Path,
    archive_path: str | Path,
    briefing_day: str,
    timezone_name: str,
    item_catalog_path: str | Path | None = None,
    include_feedback_ui: bool = False,
) -> dict[str, Any]:
    archive = Path(archive_path)
    archive_text = _compose_curated_archive_text(
        briefing,
        briefing_day,
        include_feedback_ui=include_feedback_ui,
    )
    if not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text(archive_text, encoding='utf-8')
    front_matter = {
        'title': archive_title(briefing_day).removeprefix('# ').strip(),
        'date': _front_matter_datetime(briefing_day, timezone_name),
        'briefing_day': briefing_day,
        'timezone': timezone_name,
        'item_count': briefing.curated_item_count,
        'item_ids': [item.item_id for item in briefing.items],
        'sources': sorted({item.source for item in briefing.items if item.source}),
        'tags': sorted({tag for item in briefing.items for tag in item.tags}),
        'feedback_ui_enabled': include_feedback_ui,
        'feedback_primary_briefing_id': briefing.briefing_id,
        'feedback_items': [dict(item) for item in briefing.feedback_items],
        'slots': [
            {
                'slot': briefing.slot,
                'label': briefing.slot_label,
                'briefing_id': briefing.briefing_id,
                'item_count': briefing.curated_item_count,
            }
        ],
        'draft': False,
    }

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    front_matter_text = yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True).strip()
    hugo_content = render_hugo_content_with_inline_feedback(
        archive_text,
        briefing_day,
        include_feedback_ui=include_feedback_ui,
    )
    output.write_text(f'---\n{front_matter_text}\n---\n\n{hugo_content.rstrip()}\n', encoding='utf-8')

    catalog_rows = build_item_catalog_rows(briefing_day, _curated_slot_rows(briefing))
    catalog_target = Path(item_catalog_path) if item_catalog_path is not None else None
    item_catalog_metadata = {
        'status': 'skipped',
        'output_path': None,
        'item_count': len(catalog_rows),
    }
    if catalog_target is not None:
        write_item_catalog(catalog_target, catalog_rows)
        item_catalog_metadata = {
            'status': 'updated',
            'output_path': str(catalog_target),
            'item_count': len(catalog_rows),
        }

    return {
        'briefing_day': briefing_day,
        'item_count': briefing.curated_item_count,
        'item_ids': [item.item_id for item in briefing.items],
        'sources': sorted({item.source for item in briefing.items if item.source}),
        'tags': sorted({tag for item in briefing.items for tag in item.tags}),
        'feedback_primary_briefing_id': briefing.briefing_id,
        'feedback_item_count': len(briefing.feedback_items),
        'item_catalog': item_catalog_metadata,
    }


def export_archive_to_hugo(
    *,
    archive_path: str | Path,
    output_path: str | Path,
    briefing_day: str,
    timezone_name: str,
    item_catalog_path: str | Path | None = None,
    include_feedback_ui: bool = False,
) -> dict[str, Any]:
    archive_text = Path(archive_path).read_text(encoding='utf-8')
    title, sections = parse_archive_sections(archive_text, briefing_day)

    slots: list[dict[str, Any]] = []
    feedback_items: list[dict[str, Any]] = []
    item_catalog_seed: list[dict[str, Any]] = []
    item_ids: list[str] = []
    sources: set[str] = set()
    tags: set[str] = set()
    total_items = 0
    primary_briefing_id: str | None = None

    for header in ordered_archive_headers():
        body = sections.get(header, '').strip()
        if header == SETTLING_HEADER:
            continue
        briefing_id, items = parse_archive_slot_metadata(body)
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
            item_catalog_seed.append(
                {
                    'slot': slot_name,
                    'briefing_id': briefing_id,
                    'item': item,
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
        'feedback_ui_enabled': include_feedback_ui,
        'feedback_primary_briefing_id': primary_briefing_id,
        'feedback_items': feedback_items,
        'slots': slots,
        'draft': False,
    }

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    front_matter_text = yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True).strip()
    hugo_content = render_hugo_content_with_inline_feedback(
        archive_text,
        briefing_day,
        include_feedback_ui=include_feedback_ui,
    )
    output.write_text(f'---\n{front_matter_text}\n---\n\n{hugo_content.rstrip()}\n', encoding='utf-8')

    catalog_rows = build_item_catalog_rows(briefing_day, item_catalog_seed)
    catalog_target = Path(item_catalog_path) if item_catalog_path is not None else None
    item_catalog_metadata = {
        'status': 'skipped',
        'output_path': None,
        'item_count': len(catalog_rows),
    }
    if catalog_target is not None:
        write_item_catalog(catalog_target, catalog_rows)
        item_catalog_metadata = {
            'status': 'updated',
            'output_path': str(catalog_target),
            'item_count': len(catalog_rows),
        }

    return {
        'briefing_day': briefing_day,
        'item_count': total_items,
        'item_ids': item_ids,
        'sources': sorted(sources),
        'tags': sorted(tags),
        'feedback_primary_briefing_id': primary_briefing_id,
        'feedback_item_count': len(feedback_items),
        'item_catalog': item_catalog_metadata,
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
    curated_briefing: CuratedBriefing | None = None,
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
        curated_briefing=curated_briefing,
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
    curated_briefing = None
    if manifest.get('curated_output'):
        curated_briefing = load_curated_briefing(json.loads(Path(manifest['curated_output']).read_text(encoding='utf-8')))
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
        curated_briefing=curated_briefing,
        dry_run=bool(manifest.get('dry_run', False)),
    )
    return context, manifest


def store_publication_results(manifest_path: str | Path, results: Iterable[PublishResult]) -> dict[str, Any]:
    manifest_file = Path(manifest_path)
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    publication = dict(manifest.get('publication', {}))
    for result in results:
        publication[result.target] = result.to_manifest()
        if result.target == 'hugo_export' and isinstance(result.details, dict):
            manifest['item_catalog'] = dict(result.details.get('item_catalog', {}))
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
                    'item_catalog': {
                        'status': 'dry_run',
                        'output_path': str(default_item_catalog_path(context)),
                        'item_count': len(context.collect_result.candidates),
                    },
                },
            )
        else:
            metadata = export_archive_to_hugo(
                archive_path=archive_path,
                output_path=output_path,
                briefing_day=briefing_day,
                timezone_name=timezone_name,
                item_catalog_path=default_item_catalog_path(context),
                include_feedback_ui=feedback_ui_enabled(context.publication_config),
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
        item_catalog_path = Path(DEFAULT_ITEM_CATALOG_DIR) / briefing_day[:4] / f'{briefing_day}.jsonl'
        metadata = export_archive_to_hugo(
            archive_path=archive_path,
            output_path=output_path,
            briefing_day=briefing_day,
            timezone_name=timezone_name,
            item_catalog_path=item_catalog_path,
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
