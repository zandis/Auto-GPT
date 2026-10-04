from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from tb_common.config import ConfigError, load, load_env, load_settings

EXAMPLE = Path(__file__).resolve().parents[2] / "deploy" / "settings.example.yaml"


def test_example_settings_valid() -> None:
    s = load_settings(EXAMPLE)
    assert s.site.id == "DEMO-A"
    assert s.thresholds.small_cell == 5
    assert "hospa.test" in s.internal_domains
    assert s.permissions["SUBMIT"] == ["physicians"]


def test_settings_refuses_unknown_key(tmp_path: Path) -> None:
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    data["surprise"] = 1
    p = tmp_path / "s.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ConfigError, match="surprise"):
        load_settings(p)


def test_settings_refuses_missing_required_and_bad_types(tmp_path: Path) -> None:
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    del data["internal_domains"]
    data["thresholds"]["small_cell"] = "five"
    p = tmp_path / "s.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_settings(p)
    msg = str(ei.value)
    assert "internal_domains" in msg and "five" in msg


def test_settings_bad_timezone(tmp_path: Path) -> None:
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    data["site"]["tz"] = "Mars/Olympus"
    p = tmp_path / "s.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ConfigError, match="time zone"):
        load_settings(p)


def test_settings_unknown_permission_group(tmp_path: Path) -> None:
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    data["permissions"]["FEAS"] = ["everyone"]
    p = tmp_path / "s.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown group"):
        load_settings(p)


def test_settings_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path / "nope.yaml")


def test_env_dotenv_then_environment_wins(tmp_path: Path, clean_env: None) -> None:
    dot = tmp_path / ".env"
    dot.write_text(
        "TB_SITE_ID=FROMFILE\nIMAP_PORT=3143\nIMAP_SSL=false\nTB_LLM_MODE=stub\n# comment\n", encoding="utf-8"
    )
    env = load_env(dot, environ={"TB_SITE_ID": "FROMENV"})
    assert env.site_id == "FROMENV"
    assert env.imap_port == 3143
    assert env.imap_ssl is False
    assert env.llm_mode == "stub"


def test_env_rejects_bad_values(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_env(tmp_path / "none", environ={"IMAP_PORT": "abc"})
    with pytest.raises(ConfigError):
        load_env(tmp_path / "none", environ={"TB_TZ": "Nowhere/City"})
    with pytest.raises(ConfigError):
        load_env(tmp_path / "none", environ={"ATTACH_PASSWORD_MODE": "rot13"})


def test_load_full_config(tmp_path: Path, clean_env: None) -> None:
    cfg = load(dotenv=tmp_path / "none", settings_path=EXAMPLE)
    assert cfg.settings.site.id == "DEMO-A"
    assert cfg.env.tz == "Asia/Taipei"
