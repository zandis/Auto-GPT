"""D-890 (lane A2's embed-service fix, #756): the embedder's cap is 6 GB wherever it is set or summed. Weights about
2.3 GB, runtime about 0.6 GB and one batch at the token cap under 0.6 GB make about 3.5 GB for one load; 4 GB was too
tight once several loads raced."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tools.trialbox import memcaps

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb


def test_the_compose_default_is_6_gb() -> None:
    assert memcaps.compose_default("TB_MEM_EMBED") == "6g"
    assert memcaps.size_mb(memcaps.compose_default("TB_MEM_EMBED")) == 6 * 1024


def test_the_gb10_overlay_and_its_profile_say_the_same_6_gb() -> None:
    overlay = yaml.safe_load((ROOT / "deploy" / "docker-compose.gb10.yml").read_text(encoding="utf-8"))
    assert overlay["services"]["embed-service"]["mem_limit"] == "6g"
    profile = yaml.safe_load((ROOT / "deploy" / "gb10-profile.yaml").read_text(encoding="utf-8"))
    assert profile["memory"]["embed-service"]["limit_gib"] == 6


def test_the_64_gb_overlay_keeps_the_documented_6_gb_cap() -> None:
    """The CPU embedder is unchanged on gb10-64. One load is about 3.5 GB; 4 GB was too tight (D-890), so the cap is 6 GB."""
    overlay = yaml.safe_load((ROOT / "deploy" / "docker-compose.gb10-64.yml").read_text(encoding="utf-8"))
    profile = yaml.safe_load((ROOT / "deploy" / "gb10-64-profile.yaml").read_text(encoding="utf-8"))
    assert overlay["services"]["embed-service"]["mem_limit"] == "6g"
    assert profile["memory"]["embed-service"]["limit_gib"] == 6


def test_no_compose_file_still_gives_the_embedder_4_gb() -> None:
    for f in sorted((ROOT / "deploy").rglob("docker-compose*.yml")):
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"TB_MEM_EMBED:-4g", text), f
