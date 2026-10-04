"""Retrospective NAV harness on synthetic claims (phase 5 DoD: the harness runs; safety metric is zero)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from tb_common.ruleset import Ruleset

from tools.nav_retro import retro

ROOT = Path(__file__).resolve().parents[2]


def test_retro_harness_runs(ingested: dict[str, Any]) -> None:
    lake = LakeLocal(ingested["lake_dir"], HashEmbedder())
    rep = retro(lake, Ruleset.load(ROOT / "rulesets" / "RA-BIO"), date(2026, 10, 4), 12)
    assert rep["applications"] > 50 and rep["decided"] > 40 and rep["pending_skipped"] > 0
    assert rep["agreement"] is not None and 0.0 <= rep["agreement"] <= 1.0
    assert rep["eligible_with_coded_hard_exclusion"] == []  # SPEC §11.2: zero
    assert {r["outcome"] for r in rep["rows"]} == {"approved", "denied", "pending"}
