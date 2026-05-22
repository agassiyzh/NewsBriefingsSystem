from pathlib import Path
import tomllib

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_default_repo_newsroom_config_does_not_pin_host_specific_system_dir():
    config = yaml.safe_load((ROOT / "config" / "newsroom.yaml").read_text(encoding="utf-8"))

    assert "system_dir" not in config.get("system", {})


def test_default_repo_newsroom_feedback_config_is_local_safe_and_disabled_by_default():
    config = yaml.safe_load((ROOT / "config" / "newsroom.yaml").read_text(encoding="utf-8"))

    assert config["feedback"]["enabled"] is False
    assert config["feedback"]["worker_base_url"] == ""
    assert config["feedback"]["widget_enabled"] is False
    assert config["feedback"]["track_links"] is False
    assert config["feedback"]["dwell_enabled"] is False



def test_default_publication_config_disables_feedback_ui_and_pages_link_override():
    config = yaml.safe_load((ROOT / "config" / "newsroom.yaml").read_text(encoding="utf-8"))

    assert config["publication"]["feedback_ui_enabled"] is False
    assert config["publication"]["public_site_base_url"] == "https://www.yuzhuohui.info/NewsBriefingsSystem/"


def test_default_hugo_feedback_params_are_disabled_by_default():
    config = tomllib.loads((ROOT / "site" / "hugo.toml").read_text(encoding="utf-8"))

    assert config["params"]["feedback"]["enabled"] is False
    assert config["params"]["feedback"]["workerBaseUrl"] == ""
    assert config["params"]["feedback"]["widgetEnabled"] is False
    assert config["params"]["feedback"]["trackLinks"] is False
    assert config["params"]["feedback"]["dwellEnabled"] is False
