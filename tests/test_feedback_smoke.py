from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from newsroom.publisher import export_archive_to_hugo


ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCRIPT = ROOT / "scripts" / "feedback_smoke.py"
LOCAL_SERVER_SCRIPT = ROOT / "worker" / "scripts" / "local-smoke-server.js"

SAMPLE_ARCHIVE = (
    "# 新闻雷达｜2026-05-19\n\n"
    "## 08:00 早间版\n\n"
    "<!-- briefing_id: 2026-05-19-08 -->\n\n"
    "### 1｜Agent copilots ship for developers\n\n"
    "- item_id: 2026-05-19-08-001\n"
    "- source: Working Feed\n"
    "- url: https://example.com/story\n"
    "- tags: [AI Agent, Tooling]\n\n"
    "摘要：A new agent workflow shipped.\n\n"
    "## 13:00 午间版\n\n"
    "<!-- briefing_id: 2026-05-19-13 -->\n\n"
    "### 1｜Robotics retail pilots expand\n\n"
    "- item_id: 2026-05-19-13-001\n"
    "- source: Noon Feed\n"
    "- url: https://example.com/noon\n"
    "- tags: [Robotics]\n\n"
    "摘要：Pilots expanded.\n\n"
    "## 20:00 晚间版\n\n"
    "_本版次暂无候选新闻。_\n\n"
    "## 今日沉淀\n\n"
    "- 趋势：Agent workflow 更成熟\n"
)


def _write_enabled_site(tmp_path: Path, *, worker_base_url: str) -> tuple[Path, Path, Path]:
    site_dir = tmp_path / "site"
    content_path = site_dir / "content" / "briefings" / "2026" / "2026-05-19.md"
    archive_path = tmp_path / "archive" / "2026-05-19.md"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_text(SAMPLE_ARCHIVE, encoding="utf-8")
    export_archive_to_hugo(
        archive_path=archive_path,
        output_path=content_path,
        briefing_day="2026-05-19",
        timezone_name="Asia/Shanghai",
    )

    hugo_text = (ROOT / "site" / "hugo.toml").read_text(encoding="utf-8")
    hugo_text = (
        hugo_text
        .replace("enabled = false", "enabled = true")
        .replace('workerBaseUrl = ""', f'workerBaseUrl = "{worker_base_url}"')
        .replace("widgetEnabled = false", "widgetEnabled = true")
        .replace("trackLinks = false", "trackLinks = true")
        .replace("dwellEnabled = false", "dwellEnabled = true")
    )
    (site_dir / "hugo.toml").write_text(hugo_text, encoding="utf-8")

    layouts_dir = site_dir / "layouts"
    layouts_dir.mkdir(parents=True)
    for source in (ROOT / "site" / "layouts").rglob("*"):
        if source.is_file():
            target = layouts_dir / source.relative_to(ROOT / "site" / "layouts")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    static_dir = site_dir / "static"
    static_dir.mkdir(parents=True)
    (static_dir / "feedback.js").write_text((ROOT / "site" / "static" / "feedback.js").read_text(encoding="utf-8"), encoding="utf-8")

    destination = tmp_path / "public"
    subprocess.run(
        ["npx", "-y", "hugo-bin", "--source", str(site_dir), "--destination", str(destination)],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    html_path = destination / "briefings" / "2026" / "2026-05-19" / "index.html"
    return site_dir, destination, html_path


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_feedback_smoke_cli_validates_worker_endpoints_and_no_js_html(tmp_path):
    port = _find_free_port()
    worker_base_url = f"http://127.0.0.1:{port}"
    _site_dir, _destination, html_path = _write_enabled_site(tmp_path, worker_base_url=worker_base_url)

    server = subprocess.Popen(
        ["node", str(LOCAL_SERVER_SCRIPT), str(port)],
        cwd=ROOT / "worker",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.time() + 10
        assert server.stdout is not None
        while time.time() < deadline:
            line = server.stdout.readline()
            if line.startswith(f"listening:127.0.0.1:{port}"):
                break
        else:
            stderr = server.stderr.read() if server.stderr else ""
            raise AssertionError(f"local smoke server did not start: {stderr}")

        process = subprocess.run(
            [sys.executable, str(SMOKE_SCRIPT), "--page", str(html_path), "--worker-base-url", worker_base_url],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
        )
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)

    assert process.returncode == 0
    assert "health=ok" in process.stdout
    assert "events=ok" in process.stdout
    assert "redirect_safe=ok" in process.stdout
    assert "redirect_unsafe=ok" in process.stdout
    assert "feedback_link=ok" in process.stdout
    assert "page_no_js=ok" in process.stdout
