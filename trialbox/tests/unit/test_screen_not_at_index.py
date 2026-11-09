"""Review B-02 (D-142): a scoped patient the compiled SQL's ``base`` drops is never "excluded".

Three ways to have no base row: not in the snapshot (moved, merged), deceased before the screening date, or a birth
date after it (a mis-keyed era or century). Each used to land in the tier "excluded" with the engine's English words.
Now each goes to review with a reason code that the pages translate: ``not_in_snapshot`` when the snapshot does not
hold the patient, ``check_dates`` when it does. The scope query reads the same snapshot as the cascade.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import Concept, Terminology, ValueSets, valueset
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from matching.cascade.engine import NOT_AT_INDEX, CascadeConfig, run_cascade
from orchestrator.scenarios import screen
from orchestrator.scenarios.screen_cascade import held_in_snapshot, summary, verdicts_of
from tb_common.reasons import LABELS, Reason
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR

ROOT = Path(__file__).resolve().parents[2]
LOINC = "http://loinc.org"
IDX = date(2026, 10, 5)
SNAP = "2026-10-05"


@pytest.fixture(scope="module")
def setup(tmp_path_factory: pytest.TempPathFactory) -> tuple[LakeLocal, Ruleset]:
    tmp = tmp_path_factory.mktemp("notatindex")
    nd = tmp / "ndjson"
    nd.mkdir()
    pats = [
        {"resourceType": "Patient", "id": "P-OK", "birthDate": "1960-01-01", "gender": "female"},
        {"resourceType": "Patient", "id": "P-DEAD", "birthDate": "1950-01-01", "deceasedDateTime": "2025-01-01"},
        {
            "resourceType": "Patient",
            "id": "P-FUTURE",
            "birthDate": "2063-04-01",
            "gender": "male",
        },  # 昭和38 keyed as 2063
    ]
    obs = [
        {
            "resourceType": "Observation",
            "id": f"o-{p['id']}",
            "subject": {"reference": f"Patient/{p['id']}"},
            "code": {"coding": [{"system": LOINC, "code": "33914-3"}]},
            "effectiveDateTime": "2026-09-01T09:00:00+09:00",
            "valueQuantity": {"value": 75, "unit": "mL/min/1.73m2"},
        }
        for p in pats
    ]
    (nd / "Patient.ndjson").write_text("\n".join(json.dumps(p) for p in pats) + "\n", encoding="utf-8")
    (nd / "Observation.ndjson").write_text("\n".join(json.dumps(o) for o in obs) + "\n", encoding="utf-8")
    (nd / "Condition.ndjson").write_text("", encoding="utf-8")
    Lake(tmp / "lake").rebuild(SNAP, HashEmbedder(), nd)
    crit = CriterionIR.model_validate(
        {
            "id": "REPRO-INC-01",
            "ruleset": "REPRO",
            "kind": "inclusion",
            "class": "structured",
            "text": "eGFR >= 60",
            "logic": {
                "domain": "observation",
                "quantifier": "any",
                "valueset": "VS_EGFR",
                "value": {"op": ">=", "num": 60, "unit": "mL/min/1.73m2"},
                "window": {"anchor": "index", "from_days": -365, "to_days": 0},
            },
        }
    )
    vs = {"VS_EGFR": valueset("REPRO", "VS_EGFR", "eGFR", [Concept(LOINC, "33914-3", "eGFR")], "1.0.0")}
    sql = SqlGenerator("REPRO", "1.0.0", ValueSets("REPRO", vs, Terminology())).render([crit])
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    manifest = base.model_copy(update={"id": "REPRO", "library": None, "criteria": [crit.id]})
    return LakeLocal(tmp / "lake", HashEmbedder()), Ruleset(manifest=manifest, criteria=[crit], valuesets=vs, sql=sql)


def test_no_base_row_goes_to_review_with_a_translated_reason(setup: tuple[LakeLocal, Ruleset]) -> None:
    lake, rs = setup
    pids = ["P-OK", "P-DEAD", "P-FUTURE", "P-GHOST"]
    cfg = CascadeConfig(
        study_id="REPRO",
        run_date=IDX,
        lookback_months=36,
        index_mode="single",
        purpose="screening",
        step_id="repro",
        snapshot=SNAP,
        population=pids,
        note_block=False,
        absence_semantics=False,
    )
    res = run_cascade(lake, rs, cfg, judge=None, embedder=HashEmbedder(), reviewer=None)
    for pid in ("P-DEAD", "P-FUTURE", "P-GHOST"):
        assert res.traces[pid].scope_reason == NOT_AT_INDEX
    ctx: Any = SimpleNamespace(services=SimpleNamespace(lake=lake))
    held = held_in_snapshot(ctx, ["P-DEAD", "P-FUTURE", "P-GHOST"], SNAP)
    assert held == {"P-DEAD", "P-FUTURE"}
    got = {pid: verdicts_of(rs, res.traces[pid], pid in held) for pid in pids}
    assert got["P-OK"].tier == "high"
    for pid, why in (("P-DEAD", "check_dates"), ("P-FUTURE", "check_dates"), ("P-GHOST", "not_in_snapshot")):
        v = got[pid]
        assert v.tier == "review", (pid, v.tier)
        assert v.actions == [] and {c.evidence.reason for c in v.verdicts if c.evidence is not None} == {why}
        assert {c.verdict for c in v.verdicts} == {"unknown"}
    # the run's counts do not call these patients opt-outs
    s = summary(res)
    assert s["opted_out"] == 0 and s["not_at_index"] == 3


def test_reasons_are_words_in_three_languages() -> None:
    for code in (Reason.CHECK_DATES, Reason.NOT_IN_SNAPSHOT):
        words = LABELS[code.value]
        assert set(words) == {"en", "ja", "zh-TW"} and all(words.values())


def test_scope_reads_the_pinned_snapshot() -> None:
    seen: list[Any] = []

    class FakeLake:
        def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
            seen.append(snapshot)
            return SimpleNamespace(to_pylist=lambda: [])

    ctx: Any = SimpleNamespace(
        services=SimpleNamespace(lake=FakeLake()), cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Tokyo"))
    )
    assert screen.scope_patients(ctx, ["D1"], IDX, 30, 12, [], SNAP) == []
    assert seen == [SNAP]
