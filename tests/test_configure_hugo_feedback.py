from pathlib import Path

from scripts.configure_hugo_feedback import configure_hugo_feedback


def test_configure_hugo_feedback_enables_params_from_environment(tmp_path, monkeypatch):
    hugo_config = tmp_path / "hugo.toml"
    hugo_config.write_text(
        """
baseURL = "https://example.com/"

[params.feedback]
  enabled = false
  workerBaseUrl = ""
  widgetEnabled = false
  trackLinks = false
  dwellEnabled = false
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEWSROOM_FEEDBACK_WORKER_BASE_URL", "https://newsroom-feedback.example.workers.dev")

    result = configure_hugo_feedback(hugo_config)

    assert result["enabled"] is True
    assert result["workerBaseUrl"] == "https://newsroom-feedback.example.workers.dev"
    assert 'enabled = true' in hugo_config.read_text(encoding="utf-8")
    assert 'workerBaseUrl = "https://newsroom-feedback.example.workers.dev"' in hugo_config.read_text(encoding="utf-8")
    assert 'widgetEnabled = true' in hugo_config.read_text(encoding="utf-8")
    assert 'trackLinks = true' in hugo_config.read_text(encoding="utf-8")
    assert 'dwellEnabled = true' in hugo_config.read_text(encoding="utf-8")


def test_configure_hugo_feedback_keeps_hugo_values_unquoted(tmp_path, monkeypatch):
    hugo_config = tmp_path / "hugo.toml"
    hugo_config.write_text(
        """
[params.feedback]
  enabled = false
  workerBaseUrl = ""
  widgetEnabled = false
  trackLinks = false
  dwellEnabled = false
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEWSROOM_FEEDBACK_WORKER_BASE_URL", "https://newsroom-feedback.example.workers.dev")

    configure_hugo_feedback(hugo_config)
    text = hugo_config.read_text(encoding="utf-8")

    assert 'workerBaseUrl = "\\"https://newsroom-feedback.example.workers.dev\\""' not in text
    assert 'widgetEnabled = "true"' not in text
    assert 'trackLinks = "true"' not in text
    assert 'dwellEnabled = "true"' not in text


def test_configure_hugo_feedback_requires_worker_url(tmp_path, monkeypatch):
    hugo_config = tmp_path / "hugo.toml"
    hugo_config.write_text(
        """
[params.feedback]
  enabled = false
  workerBaseUrl = ""
  widgetEnabled = false
  trackLinks = false
  dwellEnabled = false
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.delenv("NEWSROOM_FEEDBACK_WORKER_BASE_URL", raising=False)

    try:
        configure_hugo_feedback(hugo_config)
    except ValueError as exc:
        assert "NEWSROOM_FEEDBACK_WORKER_BASE_URL" in str(exc)
    else:
        raise AssertionError("expected ValueError")
