"""The adapter's configuration carries the site's zone, never one of its own (D-315; audit 2026-11-11).

``AdapterConfig.tz`` defaulted to ``Asia/Taipei``: a caller that gave no zone read Taiwan's day on any site.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from adapter.pipeline import AdapterConfig
from tb_common.config import ConfigError


def _cfg(tmp_path: Path, tz: str = "") -> AdapterConfig:
    return AdapterConfig(lake_dir=tmp_path, secrets_dir=tmp_path, mapping_path=tmp_path / "m.yaml", site_id="T", tz=tz)


def test_no_zone_given_is_the_sites_zone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_TZ", "Asia/Tokyo")
    assert _cfg(tmp_path).tz == "Asia/Tokyo"
    assert _cfg(tmp_path, tz="Asia/Taipei").tz == "Asia/Taipei"  # the caller's zone (cfg.env.tz) first


def test_no_zone_anywhere_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_TZ", raising=False)
    with pytest.raises(ConfigError):
        _cfg(tmp_path)
