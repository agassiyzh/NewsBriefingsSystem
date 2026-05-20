#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

FEEDBACK_KEYS = {
    'enabled': 'true',
    'widgetEnabled': 'true',
    'trackLinks': 'true',
    'dwellEnabled': 'true',
}


def _replace_bool_key(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf'^(\s*{re.escape(key)}\s*=\s*)(?:true|false)\s*$', re.MULTILINE)
    replacement = rf'\g<1>{value}'
    updated, count = pattern.subn(replacement, text)
    if count != 1:
        raise ValueError(f'expected exactly one {key} setting in Hugo feedback config')
    return updated


def _replace_string_key(text: str, key: str, value: str) -> str:
    escaped = value.replace('\\', '\\\\').replace('"', '\\"')
    pattern = re.compile(rf'^(\s*{re.escape(key)}\s*=\s*)"[^"]*"\s*$', re.MULTILINE)
    replacement = rf'\g<1>"{escaped}"'
    updated, count = pattern.subn(replacement, text)
    if count != 1:
        raise ValueError(f'expected exactly one {key} setting in Hugo feedback config')
    return updated


def configure_hugo_feedback(
    hugo_config_path: str | Path,
    *,
    worker_base_url: str | None = None,
) -> dict[str, object]:
    url = (worker_base_url or os.getenv('NEWSROOM_FEEDBACK_WORKER_BASE_URL') or '').strip().rstrip('/')
    if not url:
        raise ValueError('NEWSROOM_FEEDBACK_WORKER_BASE_URL is required to enable Hugo feedback')
    if not url.startswith('https://'):
        raise ValueError('NEWSROOM_FEEDBACK_WORKER_BASE_URL must be an https:// URL')

    path = Path(hugo_config_path)
    text = path.read_text(encoding='utf-8')
    if '[params.feedback]' not in text:
        raise ValueError('missing [params.feedback] section')

    for key, value in FEEDBACK_KEYS.items():
        text = _replace_bool_key(text, key, value)
    text = _replace_string_key(text, 'workerBaseUrl', url)
    path.write_text(text, encoding='utf-8')

    return {
        'enabled': True,
        'workerBaseUrl': url,
        'widgetEnabled': True,
        'trackLinks': True,
        'dwellEnabled': True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Enable Hugo feedback params from environment for production deploys.')
    parser.add_argument('--hugo-config', default='site/hugo.toml', help='Path to Hugo config file')
    parser.add_argument('--worker-base-url', default=None, help='Override NEWSROOM_FEEDBACK_WORKER_BASE_URL')
    args = parser.parse_args(argv)

    result = configure_hugo_feedback(args.hugo_config, worker_base_url=args.worker_base_url)
    print(f"Enabled Hugo feedback: {result['workerBaseUrl']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
