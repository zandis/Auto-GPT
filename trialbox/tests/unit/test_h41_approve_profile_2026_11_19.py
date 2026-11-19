"""Card H-41 (lane H, 2026-11-19): the steps of one approval timed on a local stub run.

``tools.public_accuracy.approve_profile`` compiles the synthetic GZQO protocol with the stub model in process and
approves it, each step of ``Compiler.approve`` under a timer. Here with the made-up translator (no JVM), so the test
needs neither the CQL jars nor a FHIR server; a made-up site list checks that ``refresh_installed`` is timed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.public_accuracy import approve_profile

pytestmark = pytest.mark.nodb


def test_profile_times_each_step_and_records_the_fhir_load(tmp_path: Path) -> None:
    r = approve_profile.profile(approve_profile.DEFAULT_PROTOCOL, 2, fake_translator=True, top=5, site_list_rows=50)
    assert r["statuses"] == ["approved", "approved"]
    steps = r["steps_mean_s"]
    for name in ("build_artifacts (CQL, ELM)", "refresh_installed", "ai.confirmed records", "repo write", "other"):
        assert name in steps
    assert all(v >= 0 for v in steps.values())
    assert r["fhir_load"]["loads_per_approval"] == 1.0
    assert r["fhir_load"]["resources_per_approval"] >= 3  # FHIRHelpers, TB_Common, the ruleset's library
    assert len(r["top_cumulative"]) == 5
    assert "approve mean" in approve_profile.render(r)


def test_main_refuses_a_missing_protocol(tmp_path: Path) -> None:
    assert approve_profile.main(["--protocol", str(tmp_path / "none.pdf")]) == 2


def test_main_writes_json(tmp_path: Path) -> None:
    out = tmp_path / "p.json"
    assert approve_profile.main(["--runs", "1", "--fake-translator", "--json", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["runs"] == 1
