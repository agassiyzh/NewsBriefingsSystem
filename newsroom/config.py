from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

DEFAULT_PATHS = {
    'candidates_dir': 'data/candidates',
    'contexts_dir': 'data/contexts',
    'briefings_dir': 'data/briefings',
    'runs_dir': 'data/runs',
    'logs_dir': 'logs',
    'telegram_previews_dir': 'data/telegram',
    'hugo_content_dir': 'site/content/briefings',
    'item_catalog_dir': 'data/item_catalog',
}


def load_yaml(path: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    return data or {}


def default_system_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_system_dir(config_path: str | Path, newsroom_config: dict[str, Any]) -> Path:
    configured = newsroom_config.get('system', {}).get('system_dir')
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(config_path).expanduser().resolve().parents[1]


def resolve_path(base_dir: Path, path_value: str | Path) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def resolve_cli_path(path_value: str | Path | None, *, default_relative: str | Path, system_dir: Path) -> Path:
    default_path = Path(default_relative)
    if path_value is None:
        return resolve_path(system_dir, default_path)

    candidate = Path(path_value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()

    if candidate.as_posix() == default_path.as_posix():
        return resolve_path(system_dir, default_path)

    return candidate.resolve()


def resolve_runtime(now: datetime | None, timezone_name: str) -> datetime:
    clock = now or datetime.now(UTC)
    zone = ZoneInfo(timezone_name)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    return clock.astimezone(zone)


def merged_paths(newsroom_config: dict[str, Any]) -> dict[str, str]:
    merged = dict(DEFAULT_PATHS)
    merged.update(newsroom_config.get('paths', {}))
    return merged


def dump_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
