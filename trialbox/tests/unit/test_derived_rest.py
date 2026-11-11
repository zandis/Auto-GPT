"""D-442 (T-207, the rest of D-189/D-190; CR-066): screening reads the stored derived rows, rulesets pin the score
definitions, the derive batch runs after the ingest, and no eGFR is computed under 18.

Synthetic patients only. Each test that needs the trial database has its own schemas (``conftest``)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_cql.generator import render_common
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import Concept, Terminology, ValueSets, valueset
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from matching.stored_scores import NOT_STORED, VS_DOCUMENTED, StoredScores, compare, stored_scores
from orchestrator.scenarios.evaluate import SqlEngine
from tb_common import derived as d
from tb_common import scores
from tb_common.derived_store import Batch, DerivedStore, Documented, Latest, current_defs, run_batch
from tb_common.reasons import LABELS, Reason, code_of
from tb_common.ruleset import Ruleset, approval_state
from tb_contracts import CriterionIR, RulesetManifest

ROOT = Path(__file__).resolve().parents[2]
IDX = date(2026, 11, 1)
ON = date(2026, 10, 6)
SNAP = "2026-11-09"
CID = "DER-INC-01"


# ------------------------------------------------------------------------------------------------ eGFR under 18
@pytest.mark.parametrize("score", ["egfr", "egfr_ckd_epi", "egfr_jsn"])
def test_no_egfr_under_18_in_the_python_reference(score: str) -> None:
    cr = {"creatinine": [d.Obs(0.6, "mg/dL", ON, "o-1")]}
    assert d.compute(score, cr, age=17, female=True).value is None
    assert d.compute(score, cr, age=17, female=True).reason == "derived_adult_only:age"
    assert d.compute(score, cr, age=1, female=None).reason == "derived_adult_only:age"  # the age before the sex
    assert d.compute(score, cr, age=0, female=True).reason == "derived_missing_input:age"  # as D-189
    assert d.compute(score, cr, age=18, female=True).value is not None  # 18 is an adult
    assert d.reason_of(["derived_adult_only:age", "o-1|2026-10-06"]) == ("derived_adult_only", ["o-1|2026-10-06"])


def test_the_new_reasons_have_words_in_three_languages() -> None:
    for code in ("derived_adult_only", "derived_not_stored", "derived_vs_documented"):
        assert code in {r.value for r in Reason} and code_of(code) == code
        assert set(LABELS[code]) == {"en", "ja", "zh-TW"} and all(LABELS[code].values())


def test_no_egfr_under_18_in_the_cql_helpers() -> None:
    common = render_common()
    assert "age is null or age < 18 or female is null" in common  # CKD-EPI 2021
    assert "scr <= 0 or age is null or age < 18 or female is null" in common  # JSN 2009


def _egfr_crit(score: str = "egfr", num: float = 45) -> CriterionIR:
    return CriterionIR.model_validate(
        {
            "id": CID,
            "ruleset": "DER",
            "kind": "inclusion",
            "class": "structured",
            "text": f"{score} at least {num}",
            "logic": {
                "domain": "observation",
                "quantifier": "latest",
                "valueset": "VS_CREAT_DER",
                "derived": score,
                "value": {"op": ">=", "num": num},
                "window": {"anchor": "index", "from_days": -365, "to_days": 0},
            },
        }
    )


def _vs() -> dict[str, Any]:
    return {"VS_CREAT_DER": valueset("DER", "VS_CREAT_DER", "creatinine", [Concept(*d.CODES["creatinine"], "cr")],
                                     "1.0.0")}  # fmt: skip


def _ruleset(crit: CriterionIR, pins: dict[str, Any] | None = None) -> Ruleset:
    vs = _vs()
    sql = SqlGenerator("DER", "1.0.0", ValueSets("DER", vs, Terminology())).render([crit])
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    body = {**base.model_dump(mode="json", exclude_none=True), "id": "DER", "criteria": [crit.id]}
    body.pop("library", None)
    body.pop("prompt_pins", None)
    if pins is not None:
        body["derived_pins"] = pins
    manifest = RulesetManifest.model_validate(body)
    return Ruleset(manifest=manifest, criteria=[crit], valuesets=vs, sql=sql)


# pid -> (birth date, creatinine mg/dL)
PATIENTS = {
    "E-ADULT": ("1971-01-01", 1.1),  # CKD-EPI 2021 59.3: at least 45
    "E-LOW": ("1950-03-01", 2.4),  # well under 45
    "E-CHILD": ("2015-05-01", 0.5),  # 11 years old: no eGFR
}


def _lake(tmp_path: Path) -> LakeLocal:
    nd = tmp_path / "nd"
    nd.mkdir()
    system, code = d.CODES["creatinine"]
    pats = [{"resourceType": "Patient", "id": p, "birthDate": b, "gender": "female"} for p, (b, _c) in PATIENTS.items()]
    obs = [
        {"resourceType": "Observation", "id": f"{p}-cr", "status": "final", "subject": {"reference": f"Patient/{p}"},
         "code": {"coding": [{"system": system, "code": code}]}, "effectiveDateTime": f"{ON.isoformat()}T09:00:00+08:00",
         "valueQuantity": {"value": c, "unit": "mg/dL", "code": "mg/dL"}}
        for p, (_b, c) in PATIENTS.items()
    ]  # fmt: skip
    (nd / "Patient.ndjson").write_text("\n".join(json.dumps(p) for p in pats) + "\n")
    (nd / "Observation.ndjson").write_text("\n".join(json.dumps(o) for o in obs) + "\n")
    Lake(tmp_path / "lake", "Asia/Taipei").rebuild(SNAP, HashEmbedder(), nd)
    return LakeLocal(tmp_path / "lake", HashEmbedder(), "Asia/Taipei")


def test_no_egfr_under_18_in_the_sql_engine(tmp_path: Path) -> None:
    lk = _lake(tmp_path)
    for score in ("egfr", "egfr_jsn"):
        rs = _ruleset(_egfr_crit(score))
        ev = SqlEngine(lk, SNAP).evaluate(rs, list(PATIENTS), IDX, [CID])
        assert ev["E-CHILD"].results[CID] is None and ev["E-CHILD"].reasons == {CID: "derived_adult_only"}, score
        assert ev["E-ADULT"].results[CID] is not None and ev["E-LOW"].results[CID] is False, score


# ------------------------------------------------------------------------------------------------ pins
def test_pins_name_every_definition_a_criterion_follows() -> None:
    got = scores.pins(["egfr", "das28", "bmi", "egfr", "cdai"])
    assert sorted(got) == ["cdai", "das28_crp", "das28_esr", "egfr_ckd_epi"]  # BMI has no catalogue definition
    assert got["egfr_ckd_epi"] == {"def_version": "neph.egfr_ckd_epi_2021@1",
                                   "sha256": scores.definition("egfr_ckd_epi")["sha256"]}  # fmt: skip
    assert scores.pin_drift(got) == [] and scores.pin_drift(None) == []


def test_a_changed_definition_puts_the_study_in_approval_needed() -> None:
    pins = scores.pins(["egfr_jsn"])
    m = _ruleset(_egfr_crit("egfr_jsn"), pins).manifest.model_copy(update={"status": "approved"})
    assert m.derived_pins is not None and m.derived_pins["egfr_jsn"].def_version == "neph.egfr_jsn_2009@1"
    assert approval_state(m, prompt_drift=[])["state"] == "approved"
    newer = {"egfr_jsn": {"def_version": "neph.egfr_jsn_2009@0", "sha256": pins["egfr_jsn"]["sha256"]}}
    body = {**m.model_dump(mode="json", exclude_none=True), "derived_pins": newer}
    st = approval_state(RulesetManifest.model_validate(body), prompt_drift=[])
    assert st["state"] == "approval_needed"
    assert st["reasons"] == [{"kind": "derived", "id": "egfr_jsn", "pinned": "neph.egfr_jsn_2009@0",
                              "active": "neph.egfr_jsn_2009@1", "state": "newer"}]  # fmt: skip
    changed = {"egfr_jsn": {"def_version": "neph.egfr_jsn_2009@1", "sha256": "0" * 64}}
    assert scores.pin_drift(changed)[0]["state"] == "changed"
    assert scores.pin_drift({"meld_9": {"def_version": "x@1", "sha256": "0" * 64}})[0]["state"] == "unknown"


def test_the_approval_writes_the_pins(monkeypatch: pytest.MonkeyPatch) -> None:
    from criteria_compiler import service

    class Reg:
        def pins(self, want: dict[str, Any]) -> dict[str, Any]:
            return {k: {"version": 4, "sha256": "a" * 64} for k in want}

    monkeypatch.setattr("tb_llm.prompt_registry.default_registry", Reg)
    rs = _ruleset(_egfr_crit("egfr"))
    out = service.approval_pins(rs.manifest, rs.criteria)
    assert out["derived_pins"] == scores.pins(["egfr_ckd_epi"])
    assert "derived_pins" not in service.approval_pins(rs.manifest, [])  # nothing derived: nothing pinned


def test_the_console_says_why_in_three_languages() -> None:
    from console import i18n_step2

    for state in ("newer", "changed", "unknown"):
        key = f"s20.pins.derived.{state}"
        texts = [v[key] for v in vars(i18n_step2).values() if isinstance(v, dict) and key in v]
        assert len(texts) == 3 and all("{pinned}" in t for t in texts), key


# ------------------------------------------------------------------------------------------------ the screening read
def test_screening_reads_the_stored_rows(db_url: str, tmp_path: Path) -> None:
    lk = _lake(tmp_path)
    st = DerivedStore(db_url)
    crit = _egfr_crit("egfr")
    rs = _ruleset(crit, scores.pins(["egfr"]))
    pids = list(PATIENTS)
    plain = SqlEngine(lk, SNAP).evaluate(rs, pids, IDX, [CID])
    assert plain["E-ADULT"].results[CID] is True and plain["E-LOW"].results[CID] is False
    # no derive batch of this snapshot yet: a decided answer on the score is "needs information", never decided
    before = SqlEngine(lk, SNAP, stored=st).evaluate(rs, pids, IDX, [CID])
    for p in ("E-ADULT", "E-LOW"):
        assert before[p].results[CID] is None and before[p].reasons == {CID: NOT_STORED}, p
    assert before["E-CHILD"].reasons == {CID: "derived_adult_only"}  # unknown stays as the SQL said
    # the batch of the snapshot ran: the stored rows stand behind the same answers
    rep = run_batch(st, lk, mapping_version="m@1", snapshot=SNAP)
    assert rep.failed == 0 and st.batch(SNAP) is not None and st.batch("2026-11-10") is None
    after = SqlEngine(lk, SNAP, stored=st).evaluate(rs, pids, IDX, [CID])
    assert {p: e.results[CID] for p, e in after.items()} == {p: e.results[CID] for p, e in plain.items()}
    child = st.rows("E-CHILD", "egfr_ckd_epi")
    assert child[0]["value"] is None and child[0]["reason"] == "derived_adult_only:age"  # stored under 18: no value
    # a documented eGFR far from the computed one: the conflict is open, the score reads as unknown
    adult = st.rows("E-ADULT", "egfr_ckd_epi")[0]
    assert st.check_documented([Documented("E-ADULT", "egfr_ckd_epi", 30.0, ON, "doc-1", "signed")]) == 1
    open_ = SqlEngine(lk, SNAP, stored=st).evaluate(rs, pids, IDX, [CID])
    assert open_["E-ADULT"].results[CID] is None and open_["E-ADULT"].reasons == {CID: VS_DOCUMENTED}
    assert open_["E-LOW"].results[CID] is False  # another patient is not touched
    # a person kept the documented 30: under 45 it no longer supports "at least 45": needs information
    (conflict,) = st.conflicts("E-ADULT")
    st.resolve(int(conflict["id"]), "keep_documented", "steward-1")
    kept = SqlEngine(lk, SNAP, stored=st).evaluate(rs, pids, IDX, [CID])
    assert kept["E-ADULT"].results[CID] is None and kept["E-ADULT"].reasons == {CID: VS_DOCUMENTED}
    assert adult["value"] == pytest.approx(59.3, abs=0.05)
    # a ruleset pinned to another definition text reads the rows as not its own
    other = _ruleset(crit, {"egfr_ckd_epi": {"def_version": "neph.egfr_ckd_epi_2021@1", "sha256": "0" * 64}})
    pinned = SqlEngine(lk, SNAP, stored=st).evaluate(other, pids, IDX, [CID])
    assert pinned["E-LOW"].results[CID] is None and pinned["E-LOW"].reasons == {CID: NOT_STORED}


def test_a_batch_over_some_patients_or_no_snapshot_is_not_recorded(db_url: str, tmp_path: Path) -> None:
    lk = _lake(tmp_path)
    st = DerivedStore(db_url)
    run_batch(st, lk, mapping_version="m@1", snapshot=SNAP, pids=["E-ADULT"])
    run_batch(st, lk, mapping_version="m@1")
    assert st.batch(SNAP) is None
    run_batch(st, lk, mapping_version="m@1", snapshot=SNAP)
    b = st.batch(SNAP)
    assert b is not None and b.current() and b.failed_pids == frozenset()
    assert replace(b, defs={**current_defs(), "rheum.cdai@1": "0" * 64}).current() is False
    many = st.latest_many(["E-ADULT", "E-NONE"], "egfr_ckd_epi", None, IDX)
    assert (
        many["E-ADULT"].anchor_oid is not None
        and many["E-ADULT"].def_sha == scores.definition("egfr_ckd_epi")["sha256"]
    )
    assert many["E-NONE"].value is None and many["E-NONE"].reason == "derived_missing_input:creatinine"
    assert st.latest_many([], "egfr_ckd_epi", None, IDX) == {}


# ------------------------------------------------------------------------------------------------ the rule, alone
class FakeStore:
    def __init__(self, rows: dict[str, dict[str, Latest]], failed: frozenset[str] = frozenset()) -> None:
        self._rows = rows
        self._failed = failed

    def batch(self, snapshot: str) -> Batch | None:
        return Batch(1, snapshot, current_defs(), self._failed)

    def latest_many(self, pids: list[str], score: str, lo: date | None, hi: date) -> dict[str, Latest]:
        return {p: self._rows.get(score, {}).get(p, Latest(None, "derived_missing_input:x")) for p in pids}


def _row(score: str, value: float | None, anchor: str = "o-1", inputs: tuple[str, ...] = ()) -> Latest:
    dd = scores.definition(score)
    return Latest(value, None if value is not None else "derived_unit:crp", row_id=7, anchor_date=ON,
                  def_version=dd["def_version"], inputs=[{"component": c} for c in inputs], anchor_oid=anchor,
                  def_sha=dd["sha256"])  # fmt: skip


def test_the_rule_only_ever_takes_a_decided_answer_away() -> None:
    crit = _egfr_crit("egfr")
    held = StoredScores.for_criteria(FakeStore({"egfr_ckd_epi": {"P": _row("egfr_ckd_epi", 59.3)}},
                                               frozenset({"F"})), [crit], ["P", "F", "Q"], SNAP, IDX)  # fmt: skip
    refs = ["o-1|2026-10-06"]
    assert held.check(crit, "P", True, refs) is None  # the row stands behind it
    assert held.check(crit, "P", None, refs) is None  # unknown stays unknown: never decided here
    assert held.check(crit, "P", False, refs) == NOT_STORED  # the stored value says otherwise
    assert held.check(crit, "P", True, ["o-9|2026-10-06"]) == NOT_STORED  # another visit than the engine's
    assert held.check(crit, "F", True, refs) == NOT_STORED  # the batch failed for this patient
    assert held.check(crit, "Q", True, refs) == NOT_STORED  # no stored row
    bmi = _egfr_crit("bmi")
    assert held.check(bmi, "Q", True, refs) is None  # no stored rows for BMI: the SQL alone, as before
    none = StoredScores.for_criteria(FakeStore({}), [crit], ["P"], None, IDX)  # no snapshot named
    assert none.check(crit, "P", True, refs) == NOT_STORED
    bad = StoredScores.for_criteria(FakeStore({"egfr_ckd_epi": {"P": _row("egfr_ckd_epi", None)}}), [crit], ["P"],
                                    SNAP, IDX)  # fmt: skip
    assert bad.check(crit, "P", True, refs) == "derived_unit"


def test_das28_reads_the_variant_the_visit_used() -> None:
    crit = _egfr_crit("das28", 5.1)
    rows = {"das28_esr": {"P": _row("das28_esr", 6.0, inputs=("tjc28", "esr")),
                          "Q": _row("das28_esr", None, inputs=("tjc28",))},
            "das28_crp": {"P": _row("das28_crp", 3.0, inputs=("tjc28", "crp")),
                          "Q": _row("das28_crp", 3.0, inputs=("tjc28", "crp"))}}  # fmt: skip
    held = StoredScores.for_criteria(FakeStore(rows), [crit], ["P", "Q"], SNAP, IDX)
    assert held.check(crit, "P", True, ["o-1|x"]) is None  # ESR at the visit: DAS28-ESR 6.0 > 5.1
    assert held.check(crit, "Q", False, ["o-1|x"]) is None  # no ESR: DAS28-CRP 3.0
    assert held.check(crit, "Q", True, ["o-1|x"]) == NOT_STORED
    assert stored_scores("das28") == ("das28_esr", "das28_crp") and stored_scores("asdas") == ()
    assert compare(crit.logic, 5.0) is False and compare(_egfr_crit("bmi").logic, 50.0) is True  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------------ the batch, scheduled
class FakeAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))


class FakeOrch:
    def __init__(self, lake: Any) -> None:
        self.audit = FakeAudit()
        self.services = type("S", (), {"lake": lake})()


def test_the_batch_runs_after_the_ingest(db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import derive

    lk = _lake(tmp_path)
    orch = FakeOrch(lk)
    monkeypatch.delenv("TB_DB_URL", raising=False)
    assert derive.store() is None and derive.after_ingest(orch, SNAP) is None and orch.audit.events == []
    monkeypatch.setenv("TB_DB_URL", db_url)
    counts = derive.after_ingest(orch, SNAP)
    assert counts is not None and counts["inserted"] == 6 and counts["failed"] == 0  # two eGFRs for each of three
    assert orch.audit.events[-1][0] == "derive.batch" and orch.audit.events[-1][1]["detail"]["snapshot"] == SNAP
    st = derive.store()
    assert st is not None and st.batch(SNAP) is not None
    assert st.rows("E-ADULT", "egfr_ckd_epi")[0]["mapping_version"] == "unrecorded"  # a bare FHIR feed: none named
    broken = FakeOrch(None)  # the lake cannot be read: logged and audited, never raised
    assert derive.after_ingest(broken, "2026-11-10") is None
    assert broken.audit.events[-1][0] == "derive.failed" and st.batch("2026-11-10") is None


def test_the_ingest_scenario_calls_the_batch_before_the_follow_up() -> None:
    src = (ROOT / "services" / "orchestrator" / "scenarios" / "admin.py").read_text(encoding="utf-8")
    assert src.index("derive.after_ingest(") < src.index("after_ingest(ctx.orch")
