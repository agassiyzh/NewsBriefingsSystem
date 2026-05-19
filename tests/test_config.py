from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_default_repo_newsroom_config_does_not_pin_host_specific_system_dir():
    config = yaml.safe_load((ROOT / "config" / "newsroom.yaml").read_text(encoding="utf-8"))

    assert "system_dir" not in config.get("system", {})
