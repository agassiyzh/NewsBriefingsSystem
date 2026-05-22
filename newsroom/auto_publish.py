from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

BRIEFINGS_ROOT = Path("site/content/briefings")
DEFAULT_ACTIONS_TIMEOUT_SECONDS = 900
DEFAULT_LIVE_TIMEOUT_SECONDS = 900
DEFAULT_POLL_SECONDS = 15
GITHUB_API_BASE = "https://api.github.com"
USER_AGENT = "NewsBriefingsSystem/auto-publish"
FEEDBACK_UI_MARKERS = (
    "item-feedback-widget",
    "feedback-button",
    "data-feedback-item",
    "data-feedback-action",
)


@dataclass(slots=True)
class SmokeBuildResult:
    destination: Path
    verified_files: list[Path]


@dataclass(slots=True)
class PublishResult:
    changed_files: list[str]
    briefing_days: list[str]
    smoke_destination: Path
    smoke_verified_files: list[Path]
    commit_sha: str
    commit_message: str
    actions_url: str | None
    pages_url: str | None
    live_urls: list[str]


class PublishError(RuntimeError):
    """Raised when auto-publish validation or deployment fails."""


def run_command(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
    timeout: int = 600,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if check and completed.returncode != 0:
        command = " ".join(args)
        raise PublishError(
            f"command failed ({completed.returncode}): {command}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def parse_git_status_porcelain(text: str) -> list[str]:
    changed: list[str] = []
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        if len(raw_line) < 4:
            continue
        status = raw_line[:2]
        path_text = raw_line[3:].strip()
        if " -> " in path_text:
            path_text = path_text.split(" -> ", 1)[1].strip()
        normalized = path_text.strip('"').replace("\\", "/")
        if not normalized.startswith(f"{BRIEFINGS_ROOT.as_posix()}/") or not normalized.endswith(".md"):
            continue
        if "D" in status:
            raise PublishError(f"refusing to auto-publish deleted briefing content: {normalized}")
        changed.append(normalized)
    return sorted(dict.fromkeys(changed))


def changed_briefing_files(repo_root: Path) -> list[str]:
    status = run_command(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", BRIEFINGS_ROOT.as_posix()],
        cwd=repo_root,
    )
    return parse_git_status_porcelain(status.stdout)


def ensure_no_preexisting_staged_changes(repo_root: Path) -> None:
    staged = run_command(["git", "diff", "--cached", "--name-only"], cwd=repo_root)
    staged_files = [line.strip() for line in staged.stdout.splitlines() if line.strip()]
    if staged_files:
        raise PublishError(
            "refusing to auto-publish with pre-existing staged changes: " + ", ".join(staged_files)
        )


def briefing_day_from_path(path: str) -> str:
    day = Path(path).stem
    parts = day.split("-")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise PublishError(f"cannot infer briefing day from path: {path}")
    return day


def build_live_briefing_url(base_url: str, briefing_day: str) -> str:
    return f"{base_url.rstrip('/')}/briefings/{briefing_day[:4]}/{briefing_day}/"


def default_commit_message(briefing_days: list[str]) -> str:
    unique_days = sorted(dict.fromkeys(briefing_days))
    if not unique_days:
        raise PublishError("cannot build commit message without briefing days")
    joined = ", ".join(unique_days)
    return f"publish: update briefings {joined}"


def load_manifest_context(manifest_path: str | Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    manifest_file = Path(manifest_path).expanduser().resolve()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    newsroom_config_path = Path(manifest["newsroom_config_path"]).expanduser().resolve()
    newsroom_config = yaml.safe_load(newsroom_config_path.read_text(encoding="utf-8")) or {}
    repo_root = newsroom_config_path.parents[1]
    return manifest, newsroom_config, repo_root


def load_github_token_from_hosts(hosts_path: str | Path | None = None) -> str | None:
    target = Path(hosts_path).expanduser() if hosts_path is not None else Path.home() / ".config" / "gh" / "hosts.yml"
    if not target.is_file():
        return None
    payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    github_host = payload.get("github.com") or {}
    token = str(github_host.get("oauth_token") or "").strip()
    return token or None


def build_git_command_env(
    remote_url: str,
    *,
    github_token: str | None,
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    env = dict(base_env or os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    if github_token and "github.com" in remote_url:
        encoded = base64.b64encode(f"x-access-token:{github_token}".encode("utf-8")).decode("ascii")
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
        env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: basic {encoded}"
    return env


def build_smoke_site(
    repo_root: Path,
    *,
    base_url: str,
    briefing_days: list[str],
    feedback_ui_enabled: bool,
) -> SmokeBuildResult:
    destination = Path(tempfile.mkdtemp(prefix="newsroom-pages-"))
    run_command(
        [
            "hugo",
            "--source",
            "site",
            "--destination",
            str(destination),
            "--baseURL",
            base_url.rstrip("/") + "/",
        ],
        cwd=repo_root,
        timeout=600,
    )

    verified_files: list[Path] = []
    for briefing_day in briefing_days:
        html_path = destination / "briefings" / briefing_day[:4] / briefing_day / "index.html"
        if not html_path.is_file():
            raise PublishError(f"smoke build missing expected file: {html_path}")
        html = html_path.read_text(encoding="utf-8")
        if briefing_day not in html:
            raise PublishError(f"smoke build output missing briefing day marker {briefing_day}: {html_path}")
        if not feedback_ui_enabled:
            ensure_feedback_ui_absent(html, html_path)
        verified_files.append(html_path)

    return SmokeBuildResult(destination=destination, verified_files=verified_files)


def ensure_feedback_ui_absent(html: str, html_path: Path) -> None:
    for marker in FEEDBACK_UI_MARKERS:
        if marker in html:
            raise PublishError(f"smoke build unexpectedly contains feedback marker {marker!r}: {html_path}")


def git_push_preflight(repo_root: Path) -> None:
    remote_url = run_command(["git", "remote", "get-url", "origin"], cwd=repo_root).stdout.strip()
    env = build_git_command_env(remote_url, github_token=load_github_token_from_hosts())
    try:
        run_command(["git", "push", "--dry-run", "origin", "HEAD:main"], cwd=repo_root, timeout=600, env=env)
    except PublishError as exc:
        raise PublishError(f"git push preflight failed before creating commit: {exc}") from exc


def git_commit_and_push(
    repo_root: Path,
    *,
    files: list[str],
    commit_message: str,
) -> str:
    remote_url = run_command(["git", "remote", "get-url", "origin"], cwd=repo_root).stdout.strip()
    env = build_git_command_env(remote_url, github_token=load_github_token_from_hosts())
    run_command(["git", "add", "--", *files], cwd=repo_root)
    cached_diff = run_command(["git", "diff", "--cached", "--name-only", "--", *files], cwd=repo_root)
    if not cached_diff.stdout.strip():
        raise PublishError("git add produced no staged briefing changes")
    run_command(["git", "commit", "-m", commit_message], cwd=repo_root, timeout=600)
    commit_sha = run_command(["git", "rev-parse", "HEAD"], cwd=repo_root).stdout.strip()
    if not commit_sha:
        raise PublishError("git rev-parse HEAD returned an empty commit sha")
    run_command(["git", "push", "origin", "HEAD:main"], cwd=repo_root, timeout=600, env=env)
    return commit_sha


def infer_owner_repo(repo_root: Path) -> str:
    remote = run_command(["git", "remote", "get-url", "origin"], cwd=repo_root).stdout.strip()
    if not remote:
        raise PublishError("git remote get-url origin returned empty output")
    if remote.startswith("git@github.com:"):
        owner_repo = remote.split(":", 1)[1]
    else:
        marker = "github.com/"
        if marker not in remote:
            raise PublishError(f"unsupported GitHub remote URL: {remote}")
        owner_repo = remote.split(marker, 1)[1]
    return owner_repo.removesuffix(".git")


def github_get_json(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def wait_for_actions_success(
    owner_repo: str,
    head_sha: str,
    *,
    timeout_seconds: int = DEFAULT_ACTIONS_TIMEOUT_SECONDS,
    poll_seconds: int = DEFAULT_POLL_SECONDS,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_state = "workflow run not found yet"
    api_url = f"{GITHUB_API_BASE}/repos/{owner_repo}/actions/runs?branch=main&per_page=20"

    while time.monotonic() < deadline:
        payload = github_get_json(api_url)
        runs = payload.get("workflow_runs") or []
        matching = next((run for run in runs if run.get("head_sha") == head_sha), None)
        if matching is not None:
            status = str(matching.get("status") or "unknown")
            conclusion = str(matching.get("conclusion") or "")
            last_state = f"status={status} conclusion={conclusion or 'pending'}"
            if status == "completed":
                html_url = str(matching.get("html_url") or "").strip()
                if conclusion != "success":
                    raise PublishError(
                        f"GitHub Actions run for {head_sha} finished unsuccessfully ({last_state}): {html_url}"
                    )
                if not html_url:
                    html_url = f"https://github.com/{owner_repo}/actions/runs/{matching['id']}"
                return html_url
        time.sleep(poll_seconds)

    raise PublishError(f"timed out waiting for GitHub Actions run for {head_sha}: {last_state}")


def fetch_url_text(url: str) -> tuple[int, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:  # noqa: S310
        status = getattr(response, "status", 200)
        return int(status), response.read().decode("utf-8", errors="replace")


def wait_for_live_pages(
    live_urls: list[str],
    *,
    expected_markers: dict[str, list[str]],
    timeout_seconds: int = DEFAULT_LIVE_TIMEOUT_SECONDS,
    poll_seconds: int = DEFAULT_POLL_SECONDS,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    remaining = set(live_urls)
    last_state: dict[str, str] = {url: "pending" for url in live_urls}

    while remaining and time.monotonic() < deadline:
        for url in list(remaining):
            try:
                status, body = fetch_url_text(url)
            except HTTPError as exc:
                last_state[url] = f"http {exc.code}"
                continue
            except URLError as exc:
                last_state[url] = f"url error: {exc.reason}"
                continue

            markers = expected_markers.get(url, [])
            if status == 200 and all(marker in body for marker in markers):
                remaining.remove(url)
                last_state[url] = "ok"
            else:
                last_state[url] = f"http {status}, markers_ok={all(marker in body for marker in markers)}"
        if remaining:
            time.sleep(poll_seconds)

    if remaining:
        details = "; ".join(f"{url} => {last_state[url]}" for url in sorted(remaining))
        raise PublishError(f"timed out waiting for live Pages verification: {details}")


def publish_from_manifest(
    manifest_path: str | Path,
    *,
    commit_message: str | None = None,
    wait_actions: bool = True,
    wait_live: bool = True,
) -> PublishResult | None:
    manifest, newsroom_config, repo_root = load_manifest_context(manifest_path)
    ensure_no_preexisting_staged_changes(repo_root)
    changed_files = changed_briefing_files(repo_root)
    if not changed_files:
        return None

    briefing_days = [briefing_day_from_path(path) for path in changed_files]
    publication_config = newsroom_config.get("publication") or {}
    public_site_base_url = str(publication_config.get("public_site_base_url") or "").strip()
    smoke_base_url = public_site_base_url or "https://example.com/"
    smoke_result = build_smoke_site(
        repo_root,
        base_url=smoke_base_url,
        briefing_days=briefing_days,
        feedback_ui_enabled=bool(publication_config.get("feedback_ui_enabled", False)),
    )

    git_push_preflight(repo_root)
    resolved_commit_message = commit_message or default_commit_message(briefing_days)
    commit_sha = git_commit_and_push(repo_root, files=changed_files, commit_message=resolved_commit_message)

    actions_url: str | None = None
    if wait_actions:
        owner_repo = infer_owner_repo(repo_root)
        actions_url = wait_for_actions_success(owner_repo, commit_sha)

    live_urls: list[str] = []
    pages_url: str | None = public_site_base_url.rstrip("/") + "/" if public_site_base_url else None
    if public_site_base_url:
        live_urls = [build_live_briefing_url(public_site_base_url, briefing_day) for briefing_day in briefing_days]
        if wait_live:
            expected_markers = {
                url: [briefing_day]
                for url, briefing_day in zip(live_urls, briefing_days, strict=True)
            }
            wait_for_live_pages(live_urls, expected_markers=expected_markers)

    _ = manifest
    return PublishResult(
        changed_files=changed_files,
        briefing_days=briefing_days,
        smoke_destination=smoke_result.destination,
        smoke_verified_files=smoke_result.verified_files,
        commit_sha=commit_sha,
        commit_message=resolved_commit_message,
        actions_url=actions_url,
        pages_url=pages_url,
        live_urls=live_urls,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Commit/push changed Hugo briefing content and wait for GitHub Pages.")
    parser.add_argument("--manifest", required=True, help="run manifest 路径")
    parser.add_argument("--commit-message", default=None, help="可选：覆盖默认 commit message")
    parser.add_argument(
        "--no-wait-actions",
        action="store_true",
        help="push 后不等待 GitHub Actions Pages workflow 完成",
    )
    parser.add_argument(
        "--no-wait-live",
        action="store_true",
        help="push 后不轮询 live Pages URL",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    result = publish_from_manifest(
        args.manifest,
        commit_message=args.commit_message,
        wait_actions=not args.no_wait_actions,
        wait_live=not args.no_wait_live,
    )
    if result is None:
        print("status=no_changes")
        return 0

    print("status=published")
    print(f"commit_sha={result.commit_sha}")
    print(f"commit_message={result.commit_message}")
    print(f"smoke_destination={result.smoke_destination}")
    print("changed_files=" + ",".join(result.changed_files))
    print("briefing_days=" + ",".join(result.briefing_days))
    for verified in result.smoke_verified_files:
        print(f"smoke_verified={verified}")
    if result.actions_url:
        print(f"actions_url={result.actions_url}")
    if result.pages_url:
        print(f"pages_url={result.pages_url}")
    for url in result.live_urls:
        print(f"live_url={url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
