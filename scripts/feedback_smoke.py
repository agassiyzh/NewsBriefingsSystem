#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _http_json(url: str, *, method: str = "GET", data: dict[str, object] | None = None) -> tuple[int, dict[str, object]]:
    payload = None
    headers: dict[str, str] = {}
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Origin"] = "http://localhost:1313"
    request = urllib.request.Request(url, data=payload, headers=headers, method=method)
    with urllib.request.urlopen(request) as response:
        body = response.read().decode("utf-8")
        return response.status, json.loads(body)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_text(url: str) -> tuple[int, str, dict[str, str]]:
    request = urllib.request.Request(url, method="GET")
    opener = urllib.request.build_opener(_NoRedirectHandler)
    try:
        with opener.open(request) as response:
            return response.status, response.read().decode("utf-8"), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8"), dict(exc.headers.items())


def _check_page_no_js(page_path: Path) -> None:
    html = page_path.read_text(encoding="utf-8")
    assert 'class="briefing-content"' in html
    assert 'class="item-feedback-widget"' in html
    assert '<noscript>' in html
    assert '/f?action=like&amp;briefing_id=2026-05-19-08&amp;item_id=2026-05-19-08-001&amp;channel=site' in html
    assert 'href="https://example.com/story"' in html


def run_smoke(page_path: Path, worker_base_url: str) -> list[str]:
    base = worker_base_url.rstrip("/")
    lines: list[str] = []

    status, payload = _http_json(f"{base}/api/health")
    assert status == 200
    assert payload["ok"] is True
    lines.append("health=ok")

    status, payload = _http_json(
        f"{base}/api/events",
        method="POST",
        data={
            "event_type": "like",
            "channel": "site",
            "briefing_id": "2026-05-19-08",
            "item_id": "2026-05-19-08-001",
            "anonymous_id": "anon_test_12345678",
            "idempotency_key": "smoke-like-001",
            "metadata": {"source": "Working Feed", "scope": "item"},
        },
    )
    assert status == 200
    assert payload["ok"] is True
    lines.append("events=ok")

    redirect_status, _body, headers = _http_text(
        f"{base}/r?u={urllib.parse.quote('https://example.com/story', safe='')}&briefing_id=2026-05-19-08&item_id=2026-05-19-08-001&channel=site"
    )
    assert redirect_status == 302
    assert headers.get("Location") == "https://example.com/story" or headers.get("location") == "https://example.com/story", headers
    lines.append("redirect_safe=ok")

    status, body, _headers = _http_text(
        f"{base}/r?u={urllib.parse.quote('javascript:alert(1)', safe='')}&briefing_id=2026-05-19-08&item_id=2026-05-19-08-001&channel=site"
    )
    assert status == 400
    assert re.search(r"unsafe redirect", body, re.IGNORECASE)
    lines.append("redirect_unsafe=ok")

    status, body, _headers = _http_text(
        f"{base}/f?action=like&briefing_id=2026-05-19-08&item_id=2026-05-19-08-001&channel=site"
    )
    assert status == 200
    assert "已记录，谢谢" in body
    lines.append("feedback_link=ok")

    _check_page_no_js(page_path)
    lines.append("page_no_js=ok")

    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local feedback smoke checks against the local worker and rendered HTML.")
    parser.add_argument("--page", required=True, help="Rendered Hugo HTML page path")
    parser.add_argument("--worker-base-url", required=True, help="Local worker base URL, e.g. http://127.0.0.1:8787")
    args = parser.parse_args(argv)

    results = run_smoke(Path(args.page), args.worker_base_url)
    for line in results:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
