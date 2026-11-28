"""PoC workbook door, harm check: a patient whose birth is year and month only (lake ``birth_date`` NULL) is screened
through the real compiled SQL and the cascade. An age inclusion (age >= 65) and an age exclusion (age >= 86) stay
UNKNOWN for that patient, who is still on the list (tier review), never dropped by a NULL comparison, and is counted.
A patient with a whole birth date beside them is decided as before.

All data is synthetic.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import Terminology, ValueSets
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from matching.cascade.engine import CascadeConfig, run_cascade
from orchestrator.scenarios.screen_cascade import summary, verdicts_of
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR

ROOT = Path(__file__).resolve().parents[2]
IDX = date(2026, 10, 5)
SNAP = "2026-10-05"


def _crit(cid: str, kind: str, text: str, age: dict[str, int]) -> CriterionIR:
    return CriterionIR.model_validate(
        {"id": cid, "ruleset": "AGEYM", "kind": kind, "class": "structured", "text": text,
         "logic": {"domain": "demographic", "quantifier": "any", "valueset": "NONE", "age": age}}
    )  # fmt: skip


def test_a_year_month_birth_stays_on_the_list_with_age_unknown(tmp_path: Path) -> None:
    nd = tmp_path / "nd"
    nd.mkdir()
    pats = [
        {"resourceType": "Patient", "id": "P-YM", "birthDate": "1958-11", "gender": "female"},
        {"resourceType": "Patient", "id": "P-FULL", "birthDate": "1958-11-15", "gender": "female"},
        {"resourceType": "Patient", "id": "P-OLD", "birthDate": "1930-01-01", "gender": "male"},
    ]
    (nd / "Patient.ndjson").write_text("\n".join(json.dumps(p) for p in pats) + "\n", encoding="utf-8")
    for name in ("Observation", "Condition"):
        (nd / f"{name}.ndjson").write_text("", encoding="utf-8")
    Lake(tmp_path / "lake").rebuild(SNAP, HashEmbedder(), nd)
    inc = _crit("AGEYM-INC-01", "inclusion", "age >= 65", {"min": 65})
    exc = _crit("AGEYM-EXC-01", "exclusion", "age >= 86", {"min": 86})
    sql = SqlGenerator("AGEYM", "1.0.0", ValueSets("AGEYM", {}, Terminology())).render([inc, exc])
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    manifest = base.model_copy(update={"id": "AGEYM", "library": None, "criteria": [inc.id, exc.id]})
    rs = Ruleset(manifest=manifest, criteria=[inc, exc], valuesets={}, sql=sql)
    lake = LakeLocal(tmp_path / "lake", HashEmbedder())
    pids = ["P-YM", "P-FULL", "P-OLD"]
    cfg = CascadeConfig(
        study_id="AGEYM", run_date=IDX, lookback_months=36, index_mode="single", purpose="screening",
        step_id="ageym", snapshot=SNAP, population=pids, note_block=False, absence_semantics=False,
    )  # fmt: skip
    res = run_cascade(lake, rs, cfg, judge=None, embedder=HashEmbedder(), reviewer=None)
    assert set(res.traces) == set(pids)  # nobody dropped
    got = {pid: verdicts_of(rs, res.traces[pid], True) for pid in pids}
    ym = got["P-YM"]
    assert ym.tier == "review"
    assert {c.id: c.verdict for c in ym.verdicts} == {"AGEYM-INC-01": "unknown", "AGEYM-EXC-01": "unknown"}
    full = {c.id: c.verdict for c in got["P-FULL"].verdicts}
    assert full == {"AGEYM-INC-01": "pass", "AGEYM-EXC-01": "pass"} and got["P-FULL"].tier == "high"
    assert got["P-OLD"].tier == "excluded"  # a whole date is decided as before
    s = summary(res)
    assert s["not_at_index"] == 0 and s["opted_out"] == 0
    # the funnel keeps the year-month patient through every stage (only the 96-year-old leaves, at the exclusion)
    assert s["n_after"]["S0"] == 3 and s["n_after"]["S4"] == 2
