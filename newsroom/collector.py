from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from .config import (
    default_system_dir,
    load_yaml,
    merged_paths,
    resolve_cli_path,
    resolve_path,
    resolve_runtime,
    resolve_system_dir,
)
from .ids import build_briefing_id, build_item_id, normalize_slot, slot_label

INVISIBLE_RE = re.compile('[\u200b\u200c\u200d\u2060\ufeff\u202a\u202b\u202c\u202d\u202e]')
TIMEOUT = 10
DEFAULT_MAX_ITEMS_PER_SOURCE = 5
DEFAULT_MAX_TOTAL = 35


@dataclass(slots=True)
class CollectResult:
    briefing_id: str
    collected_at: str
    candidates: list[dict[str, Any]]
    markdown: str
    error_count: int
    errors: list[dict[str, Any]]


def strip_invisible(value: str | None) -> str:
    return INVISIBLE_RE.sub('', value or '')


def clean_text(value: str | None, limit: int = 180) -> str:
    if not value:
        return ''
    text = strip_invisible(value)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = unescape(text)
    text = strip_invisible(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:limit]


def normalize_published(value: str | None) -> str:
    text = strip_invisible(value)
    if not text:
        return ''
    try:
        return parsedate_to_datetime(text).astimezone(UTC).isoformat(timespec='seconds')
    except Exception:
        try:
            return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(UTC).isoformat(timespec='seconds')
        except Exception:
            return clean_text(text, 40)


def fetch_bytes(url: str) -> bytes:
    request = Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 HermesNewsroom/1.0',
            'Accept': 'application/rss+xml, application/atom+xml, text/xml, application/xml, text/html,*/*',
        },
    )
    with urlopen(request, timeout=TIMEOUT) as response:
        return response.read(1024 * 1024)


def parse_feed_xml(name: str, raw_bytes: bytes, max_items: int = DEFAULT_MAX_ITEMS_PER_SOURCE) -> list[dict[str, str]]:
    raw = strip_invisible(raw_bytes.decode('utf-8', errors='replace')).encode('utf-8')
    root = ET.fromstring(raw)
    items: list[dict[str, str]] = []

    for item in root.findall('.//item')[:max_items]:
        title = clean_text(item.findtext('title'), 140)
        link = clean_text(item.findtext('link'), 400)
        published = normalize_published(item.findtext('pubDate') or item.findtext('date'))
        snippet = clean_text(item.findtext('description') or item.findtext('summary'), 240)
        if title and link:
            items.append(
                {
                    'source': name,
                    'title': title,
                    'url': link,
                    'published': published,
                    'snippet': snippet,
                }
            )
    if items:
        return items

    namespaces = {'a': 'http://www.w3.org/2005/Atom'}
    for entry in root.findall('.//a:entry', namespaces)[:max_items]:
        title = clean_text(entry.findtext('a:title', namespaces=namespaces), 140)
        link = ''
        for candidate in entry.findall('a:link', namespaces):
            href = clean_text(candidate.attrib.get('href'), 400)
            if href:
                link = href
                break
        published = normalize_published(
            entry.findtext('a:updated', namespaces=namespaces)
            or entry.findtext('a:published', namespaces=namespaces)
        )
        snippet = clean_text(
            entry.findtext('a:summary', namespaces=namespaces)
            or entry.findtext('a:content', namespaces=namespaces),
            240,
        )
        if title and link:
            items.append(
                {
                    'source': name,
                    'title': title,
                    'url': link,
                    'published': published,
                    'snippet': snippet,
                }
            )
    return items


def fetch_source_items(source: dict[str, Any]) -> list[dict[str, str]]:
    source_type = source.get('type', 'rss')
    max_items = int(source.get('max_items', DEFAULT_MAX_ITEMS_PER_SOURCE))
    if source_type == 'google_news':
        query = source.get('query')
        if not query:
            raise ValueError(f"Google News source 缺少 query: {source.get('name')}")
        url = (
            'https://news.google.com/rss/search?q='
            + quote_plus(f'{query} when:1d')
            + '&hl=zh-CN&gl=CN&ceid=CN:zh-Hans'
        )
        return parse_feed_xml(source['name'], fetch_bytes(url), max_items=max_items)
    if source_type != 'rss':
        raise ValueError(f"不支持的 source.type: {source_type}")
    return parse_feed_xml(source['name'], fetch_bytes(source['url']), max_items=max_items)


def match_interests(raw_item: dict[str, Any], interest_defs: Iterable[dict[str, Any]]) -> tuple[list[str], list[str]]:
    haystack = ' '.join(
        [
            str(raw_item.get('source', '')),
            str(raw_item.get('title', '')),
            str(raw_item.get('snippet', '')),
        ]
    ).casefold()
    tags: list[str] = []
    keywords: list[str] = []
    for interest in interest_defs:
        hit = False
        for keyword in interest.get('keywords', []):
            if keyword.casefold() in haystack:
                hit = True
                keywords.append(keyword)
        if hit:
            tags.append(interest.get('name', 'untitled-interest'))
    return tags, keywords


def stable_dedup_key(raw_item: dict[str, Any]) -> str:
    title = re.sub(r'\W+', '', str(raw_item.get('title', '')).casefold())[:120]
    url = str(raw_item.get('url', ''))
    return title or url


def render_markdown_context(
    briefing_id: str,
    slot: str,
    collected_at: str,
    candidates: list[dict[str, Any]],
    existing_summary: str,
) -> str:
    lines = [
        f'# 新闻候选上下文（briefing_id：{briefing_id}）',
        f'- 版次：{slot_label(slot)}',
        f'- 抓取时间：{collected_at}',
        '',
    ]
    if existing_summary:
        lines.extend(
            [
                '## 当天已归档内容摘要（用于去重）',
                clean_text(existing_summary, 800),
                '',
            ]
        )

    lines.append('## 候选新闻')
    for index, candidate in enumerate(candidates, start=1):
        lines.append(f"{index}. **{candidate['title']}**")
        lines.append(
            f"   - item_id：{candidate['item_id']}；来源：{candidate['source']}；时间：{candidate.get('published', '')}"
        )
        lines.append(f"   - 链接：{candidate['url']}")
        if candidate.get('tags'):
            lines.append(f"   - 标签：{', '.join(candidate['tags'])}")
        if candidate.get('keywords'):
            lines.append(f"   - 关键词：{', '.join(candidate['keywords'])}")
        if candidate.get('snippet'):
            lines.append(f"   - 摘要：{candidate['snippet']}")
        if candidate.get('status') == 'error' and candidate.get('error'):
            lines.append(f"   - 错误：{candidate['error']}")
        lines.append('')
    return '\n'.join(lines).strip() + '\n'


def collect_candidates(
    briefing_id: str,
    source_defs: Iterable[dict[str, Any]],
    interest_defs: Iterable[dict[str, Any]],
    *,
    slot: str | None = None,
    existing_summary: str = '',
    fetcher: Callable[[dict[str, Any]], list[dict[str, str]]] | None = None,
    collected_at: str | None = None,
    max_total: int = DEFAULT_MAX_TOTAL,
) -> CollectResult:
    fetch = fetcher or fetch_source_items
    timestamp = collected_at or datetime.now(UTC).isoformat(timespec='seconds')
    resolved_slot = normalize_slot(slot or briefing_id.rsplit('-', 1)[-1])

    prepared: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen: set[str] = set()

    for source in source_defs:
        try:
            raw_items = fetch(source)
        except Exception as exc:  # noqa: BLE001
            raw_items = [
                {
                    'source': source.get('name', 'unknown-source'),
                    'title': f'[fetch failed] {type(exc).__name__}',
                    'url': source.get('url') or source.get('query') or 'unavailable',
                    'published': '',
                    'snippet': clean_text(str(exc), 200),
                    '_error': clean_text(str(exc), 200),
                }
            ]

        for raw_item in raw_items:
            key = stable_dedup_key(raw_item)
            if not key or key in seen:
                continue
            seen.add(key)
            tags, keywords = match_interests(raw_item, interest_defs)
            status = 'error' if raw_item.get('_error') else 'ok'
            if status == 'error' and not tags:
                tags = ['error']
            candidate = {
                'briefing_id': briefing_id,
                'item_id': '',
                'source': clean_text(str(raw_item.get('source', source.get('name', 'unknown-source'))), 120),
                'title': clean_text(str(raw_item.get('title', '')), 160),
                'url': clean_text(str(raw_item.get('url', '')), 400),
                'published': normalize_published(raw_item.get('published')),
                'snippet': clean_text(str(raw_item.get('snippet', '')), 240),
                'tags': tags,
                'keywords': keywords,
                'collected_at': timestamp,
                'status': status,
                'error': clean_text(raw_item.get('_error'), 200),
            }
            if candidate['status'] == 'error':
                errors.append(
                    {
                        'source': candidate['source'],
                        'url': candidate['url'],
                        'error': candidate['error'],
                    }
                )
            prepared.append(candidate)

    limited = prepared[:max_total]
    for index, candidate in enumerate(limited, start=1):
        candidate['item_id'] = build_item_id(briefing_id, index)

    markdown = render_markdown_context(
        briefing_id=briefing_id,
        slot=resolved_slot,
        collected_at=timestamp,
        candidates=limited,
        existing_summary=existing_summary,
    )
    return CollectResult(
        briefing_id=briefing_id,
        collected_at=timestamp,
        candidates=limited,
        markdown=markdown,
        error_count=len(errors),
        errors=errors,
    )


def read_existing_summary(archive_dir: Path, briefing_day: str) -> str:
    archive_path = archive_dir / f'{briefing_day}.md'
    if archive_path.exists():
        return archive_path.read_text(encoding='utf-8')
    return ''


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('w', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')


def write_markdown(path: str | Path, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8')


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Collect newsroom candidate items into Markdown and JSONL outputs.')
    parser.add_argument('--config', default='config/newsroom.yaml', help='newsroom.yaml 路径')
    parser.add_argument('--sources', default='config/sources.yaml', help='sources.yaml 路径')
    parser.add_argument('--interests', default='config/interests.yaml', help='interests.yaml 路径')
    parser.add_argument('--slot', default='morning', help='morning|noon|evening 或对应时间别名')
    parser.add_argument('--briefing-id', default=None, help='手动指定 briefing_id=YYYY-MM-DD-HH')
    parser.add_argument('--date', default=None, help='手动指定日期 YYYY-MM-DD；默认按 newsroom.yaml 中的 timezone 计算')
    parser.add_argument('--jsonl-output', '--output-jsonl', dest='jsonl_output', default=None, help='候选 JSONL 输出路径')
    parser.add_argument('--markdown-output', '--output-markdown', dest='markdown_output', default=None, help='Markdown 上下文输出路径')
    parser.add_argument('--max-total', type=int, default=None, help='覆盖 newsroom.yaml 中的 collection.max_total')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    fallback_system_dir = default_system_dir()
    config_path = resolve_cli_path(args.config, default_relative='config/newsroom.yaml', system_dir=fallback_system_dir)
    newsroom_config = load_yaml(config_path)

    system_dir = resolve_system_dir(config_path, newsroom_config)
    sources_path = resolve_cli_path(args.sources, default_relative='config/sources.yaml', system_dir=system_dir)
    interests_path = resolve_cli_path(args.interests, default_relative='config/interests.yaml', system_dir=system_dir)
    sources_config = load_yaml(sources_path)
    interests_config = load_yaml(interests_path)

    archive_dir = resolve_path(system_dir, newsroom_config.get('system', {}).get('archive_dir', '/opt/data/home/NewsBriefings'))
    path_config = merged_paths(newsroom_config)
    candidates_dir = resolve_path(system_dir, path_config['candidates_dir'])
    contexts_dir = resolve_path(system_dir, path_config['contexts_dir'])
    timezone_name = newsroom_config.get('system', {}).get('timezone', 'Asia/Shanghai')

    if args.briefing_id:
        briefing_id = args.briefing_id
        slot = normalize_slot(briefing_id.rsplit('-', 1)[-1])
    else:
        slot = normalize_slot(args.slot)
        if args.date:
            briefing_day = date.fromisoformat(args.date)
        else:
            briefing_day = resolve_runtime(None, timezone_name).date()
        briefing_id = build_briefing_id(briefing_day, slot)

    briefing_day = '-'.join(briefing_id.split('-')[:3])
    jsonl_output = Path(args.jsonl_output) if args.jsonl_output else candidates_dir / f'{briefing_id}.jsonl'
    markdown_output = Path(args.markdown_output) if args.markdown_output else contexts_dir / f'{briefing_id}.md'
    max_total = args.max_total or int(newsroom_config.get('collection', {}).get('max_total', DEFAULT_MAX_TOTAL))

    result = collect_candidates(
        briefing_id=briefing_id,
        slot=slot,
        source_defs=sources_config.get('sources', []),
        interest_defs=interests_config.get('interests', []),
        existing_summary=read_existing_summary(archive_dir, briefing_day),
        max_total=max_total,
    )
    write_jsonl(jsonl_output, result.candidates)
    write_markdown(markdown_output, result.markdown)
    print(result.markdown, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
