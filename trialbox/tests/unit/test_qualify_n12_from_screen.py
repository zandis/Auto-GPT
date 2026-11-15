"""N12-SCREEN (D-826), the owner's blocker 3 of 2026-11-15, lane D's half: qualify takes N-12 from SCREEN.

Lane A2's ``tools/n12_screen.py`` writes the evidence from SCREEN's own run (``source: "screen"``). qualify's ``n12``
step now refuses evidence that does not say so (the benchmark prompt path, ``tools.trec_ct_eval``, is not the product),
and its wiring check (``--stub``) runs ``tools.n12_screen``. ``--evidence`` reaches qualify through the box wrapper as
given (``trialbox eval qualify --box``, D-737, keeps every option; its own tests)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, cast

import pytest

from tools import qualify as q

pytestmark = pytest.mark.nodb


def _run(tmp_path: Path, **doc: Any) -> q.StepResult:
    p = tmp_path / "n12.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    real = q.Options(profile="rtxpro6000", stub=False, operator="test", sources=("synthetic",), evidence={"n12": p})
    ctx = q.Ctx(real, cast(q.Target, None), {}, cast(q.QClient, None), cast(q.QClient, None), tmp_path, io.StringIO())
    return q.step_evidence("n12")(ctx)


def test_n12_from_screen_passes(tmp_path: Path) -> None:
    head, _ = q.git_head()
    r = _run(tmp_path, passed=True, head=head, basis="unadjusted", source="screen")
    assert r.status == "passed" and r.detail["source"] == "screen"


@pytest.mark.parametrize("source", [None, "", "benchmark", "trec_ct_eval", "SCREEN "])
def test_n12_evidence_not_from_screen_is_refused(tmp_path: Path, source: str | None) -> None:
    head, _ = q.git_head()
    doc: dict[str, Any] = {"passed": True, "head": head, "basis": "unadjusted"}
    if source is not None:
        doc["source"] = source
    r = _run(tmp_path, **doc)
    assert r.status == "failed" and "source screen" in r.reason


def test_the_wiring_check_runs_the_screen_tool() -> None:
    assert q.EVIDENCE_STEPS["n12"] == ["-m", "tools.n12_screen", "--help"]


def test_other_evidence_needs_no_source(tmp_path: Path) -> None:
    head, _ = q.git_head()
    p = tmp_path / "goldens.json"
    p.write_text(json.dumps({"passed": True, "head": head}), encoding="utf-8")
    real = q.Options(profile="rtxpro6000", stub=False, operator="test", sources=("synthetic",), evidence={"goldens": p})
    ctx = q.Ctx(real, cast(q.Target, None), {}, cast(q.QClient, None), cast(q.QClient, None), tmp_path, io.StringIO())
    assert q.step_evidence("goldens")(ctx).status == "passed"
