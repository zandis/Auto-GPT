"""D-442 (T-207, the rest of D-189/D-190; CR-066): screening reads the stored derived rows, rulesets pin the score
definitions, the derive batch runs after the ingest, and no eGFR is computed under 18.

Synthetic patients only. Each test that needs the trial database has its own schemas (``conftest``)."""

from __future__ import annotations

import json
import time
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
    adult = st.rows("E-ADULT", "egfr_ckd_epi")[0]
    assert adult["value"] == pytest.approx(59.3, abs=0.05)
    # a documented eGFR far from the computed one, after the batch: this snapshot's readers read the rows as the batch
    # left them (a re-run of the job reads the same), the next snapshot's batch carries the open conflict
    time.sleep(1.1)  # the store's times are to the second
    assert st.check_documented([Documented("E-ADULT", "egfr_ckd_epi", 30.0, ON, "doc-1", "signed")]) == 1
    again = SqlEngine(lk, SNAP, stored=st).evaluate(rs, pids, IDX, [CID])
    assert again["E-ADULT"].results[CID] is True  # D-442 item 3: pinned to the batch's finish
    nxt = _next_snapshot(tmp_path, st, lk, "2026-11-10")
    open_ = SqlEngine(lk, nxt, stored=st).evaluate(rs, pids, IDX, [CID])
    assert open_["E-ADULT"].results[CID] is None and open_["E-ADULT"].reasons == {CID: VS_DOCUMENTED}
    assert open_["E-LOW"].results[CID] is False  # another patient is not touched
    # a person kept the documented 30: under 45 it no longer supports "at least 45" (from the next batch on)
    (conflict,) = st.conflicts("E-ADULT")
    st.resolve(int(conflict["id"]), "keep_documented", "steward-1")
    third = _next_snapshot(tmp_path, st, lk, "2026-11-11")
    kept = SqlEngine(lk, third, stored=st).evaluate(rs, pids, IDX, [CID])
    assert kept["E-ADULT"].results[CID] is None and kept["E-ADULT"].reasons == {CID: VS_DOCUMENTED}
    assert SqlEngine(lk, nxt, stored=st).evaluate(rs, pids, IDX, [CID])["E-ADULT"].reasons == {CID: VS_DOCUMENTED}
    # a ruleset pinned to another definition text reads the rows as not its own
    other = _ruleset(crit, {"egfr_ckd_epi": {"def_version": "neph.egfr_ckd_epi_2021@1", "sha256": "0" * 64}})
    pinned = SqlEngine(lk, SNAP, stored=st).evaluate(other, pids, IDX, [CID])
    assert pinned["E-LOW"].results[CID] is None and pinned["E-LOW"].reasons == {CID: NOT_STORED}


def _next_snapshot(tmp_path: Path, st: DerivedStore, lk: LakeLocal, snap: str) -> str:
    """The same data as the next night: rebuilt as ``snap`` and its derive batch run, a second after the last change."""
    time.sleep(1.1)
    Lake(tmp_path / "lake", "Asia/Taipei").rebuild(snap, HashEmbedder(), tmp_path / "nd")
    run_batch(st, lk, mapping_version="m@1", snapshot=snap)
    time.sleep(1.1)
    return snap


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

    def latest_many(
        self, pids: list[str], score: str, lo: date | None, hi: date, as_of: str | None = None
    ) -> dict[str, Latest]:
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


# ------------------------------------------------------------------------------------------------ review round 2
# D-442 ruling: the stored-row read is behind one audited flag (off by default) and applies on every path alike
def _flag(db_url: str, tmp_path: Path, value: str) -> None:
    from tb_common import flags as fl
    from tb_common.audit import AuditLog

    f = fl.Flags(url=db_url, audit=AuditLog(tmp_path / "flag-audit"))
    if f.get(fl_name := "derived.stored_read", "off") != value:
        f.set(fl_name, value, actor="test:admin", reason="D-442 test")
    fl.clear_cache()


class DbOrch(FakeOrch):
    def __init__(self, lake: Any, url: str) -> None:
        super().__init__(lake)
        self.db = type("D", (), {"url": url})()


def test_the_flag_decides_whether_any_path_reads_the_store(db_url: str, tmp_path: Path) -> None:
    from orchestrator import derive
    from tb_common.derived_store import stored_read

    orch = DbOrch(None, db_url)
    assert stored_read(db_url) is None and derive.reader(orch) is None  # off by default: no path reads
    _flag(db_url, tmp_path, "on")
    assert stored_read(db_url) is not None and derive.reader(orch) is stored_read(db_url)
    _flag(db_url, tmp_path, "off")
    assert derive.reader(orch) is None


def test_every_path_reads_the_store_through_the_one_reader() -> None:
    src = {p: (ROOT / "services" / p).read_text(encoding="utf-8") for p in (
        "orchestrator/scenarios/screen.py", "orchestrator/scenarios/screen_cascade.py",
        "orchestrator/scenarios/case.py", "orchestrator/scenarios/cohort.py")}  # fmt: skip
    for p, text in src.items():
        assert "derive.reader(ctx.orch)" in text, p
    eng = (ROOT / "services" / "matching" / "cascade" / "engine.py").read_text(encoding="utf-8")
    ev = (ROOT / "services" / "orchestrator" / "scenarios" / "evaluate.py").read_text(encoding="utf-8")
    assert "apply_rows(table, applied, self.cfg.stored" in eng and "apply_rows(t, crit, self.stored" in ev


def _paths(lk: LakeLocal, rs: Ruleset, store: Any, snap: str, pids: list[str], idx: date) -> dict[str, dict[str, Any]]:
    """The answer of each path for every patient: the v1 engine (SCREEN v1, NAV, MICROBATCH re-check, CASE), the
    cascade's S1 (SCREEN, new-patient MICROBATCH) and the cohort's rows (COHORT)."""
    from criteria_compiler.compile_sql.overlay import safe_sql
    from matching.cascade.engine import CascadeConfig, run_cascade
    from matching.stored_scores import apply_rows
    from orchestrator.scenarios.evaluate import structured_verdict
    from orchestrator.scenarios.screen_cascade import verdicts_of

    crit = rs.criteria[0]
    v1 = SqlEngine(lk, snap, stored=store).evaluate(rs, pids, idx, [crit.id])
    cfg = CascadeConfig(study_id=rs.id, run_date=idx, lookback_months=36, index_mode="single", purpose="screening",
                        step_id="t", snapshot=snap, population=pids, note_block=False, absence_semantics=False,
                        stored=store)  # fmt: skip
    cas = run_cascade(lk, rs, cfg, judge=None, embedder=HashEmbedder(), reviewer=None)
    rows = lk.query(safe_sql(rs), [[idx.isoformat()], pids], snap).to_pylist()
    apply_rows(rows, rs.active(), store, snap, rs.manifest.derived_pins)
    out: dict[str, dict[str, Any]] = {"v1": {}, "cascade": {}, "cohort": {}}
    for p in pids:
        sv = structured_verdict(crit, v1[p])
        out["v1"][p] = (sv.verdict, sv.evidence.reason if sv.evidence else None)
        cv = next(v for v in verdicts_of(rs, cas.traces[p]).verdicts if v.id == crit.id)
        out["cascade"][p] = (cv.verdict, cv.evidence.reason if cv.evidence else None)
        out["cohort"][p] = next(r[f"C_{crit.id}"] for r in rows if r["pid"] == p)
    return out


def _same(out: dict[str, dict[str, Any]]) -> None:
    for p, (verdict, reason) in out["v1"].items():
        cv, cr = out["cascade"][p]
        assert cv == verdict and (verdict != "unknown" or cr == reason), (p, out["cascade"][p], verdict, reason)
        want = {"pass": True, "fail": False}.get(verdict)  # an inclusion: met, not met, unknown
        assert out["cohort"][p] is want, (p, out["cohort"][p], verdict)


def test_every_path_gives_the_same_answer_with_the_flag_off_and_on(db_url: str, tmp_path: Path) -> None:
    lk = _lake(tmp_path)
    st = DerivedStore(db_url)
    rs = _ruleset(_egfr_crit("egfr"), scores.pins(["egfr"]))
    pids = list(PATIENTS)
    off = _paths(lk, rs, None, SNAP, pids, IDX)  # the flag off: no path reads the store
    _same(off)
    assert off["v1"]["E-ADULT"][0] == "pass" and off["v1"]["E-LOW"][0] == "fail"
    on_before = _paths(lk, rs, st, SNAP, pids, IDX)  # on, no batch yet: every decided score answer unknown
    _same(on_before)
    assert on_before["v1"]["E-ADULT"] == ("unknown", NOT_STORED) and on_before["v1"]["E-LOW"][0] == "unknown"
    run_batch(st, lk, mapping_version="m@1", snapshot=SNAP)
    on_after = _paths(lk, rs, st, SNAP, pids, IDX)
    _same(on_after)
    assert on_after["v1"] == off["v1"]  # the batch stands behind every answer


# item 2: one age rule, the index date's
def test_a_row_computed_under_18_never_says_adult_only_for_an_adult_at_the_index_date(
    db_url: str, tmp_path: Path
) -> None:
    nd = tmp_path / "nd"
    nd.mkdir()
    system, code = d.CODES["creatinine"]
    pat = {"resourceType": "Patient", "id": "A-18", "birthDate": "2008-06-01", "gender": "female"}
    obs = {"resourceType": "Observation", "id": "A-18-cr", "status": "final", "subject": {"reference": "Patient/A-18"},
           "code": {"coding": [{"system": system, "code": code}]}, "effectiveDateTime": "2026-05-15T09:00:00+08:00",
           "valueQuantity": {"value": 0.8, "unit": "mg/dL", "code": "mg/dL"}}  # fmt: skip
    (nd / "Patient.ndjson").write_text(json.dumps(pat) + "\n")
    (nd / "Observation.ndjson").write_text(json.dumps(obs) + "\n")
    Lake(tmp_path / "lake", "Asia/Taipei").rebuild(SNAP, HashEmbedder(), nd)
    lk = LakeLocal(tmp_path / "lake", HashEmbedder(), "Asia/Taipei")
    st = DerivedStore(db_url)
    run_batch(st, lk, mapping_version="m@1", snapshot=SNAP)
    assert st.rows("A-18", "egfr_ckd_epi")[0]["reason"] == "derived_adult_only:age"  # 17 at the creatinine
    rs = _ruleset(_egfr_crit("egfr"), scores.pins(["egfr"]))
    assert SqlEngine(lk, SNAP).evaluate(rs, ["A-18"], IDX, [CID])["A-18"].results[CID] is True  # 18 at the index
    got = SqlEngine(lk, SNAP, stored=st).evaluate(rs, ["A-18"], IDX, [CID])["A-18"]
    assert got.results[CID] is None and got.reasons == {CID: NOT_STORED}  # never derived_adult_only


# item 7: a criterion of several atoms is checked in three values
def test_a_combined_criterion_flags_only_a_contradiction() -> None:
    lt30 = _egfr_crit("egfr", 30).logic.model_copy(update={"value": {"op": "<", "num": 30}})
    dialysis = {"domain": "procedure", "quantifier": "any", "valueset": "VS_DIAL",
                "window": {"anchor": "index", "from_days": -365, "to_days": 0}}  # fmt: skip
    either = CriterionIR.model_validate({"id": "DER-EXC-01", "ruleset": "DER", "kind": "exclusion", "class": "structured",
                                         "text": "eGFR < 30 or dialysis",
                                         "logic": {"op": "or", "args": [lt30.model_dump(exclude_none=True), dialysis]}})  # fmt: skip
    neither = CriterionIR.model_validate({"id": "DER-INC-09", "ruleset": "DER", "kind": "inclusion", "class": "structured",
                                          "text": "not eGFR < 30",
                                          "logic": {"op": "not", "args": [lt30.model_dump(exclude_none=True)]}})  # fmt: skip
    rows = {"egfr_ckd_epi": {"LOW": _row("egfr_ckd_epi", 20.0)}}
    held = StoredScores.for_criteria(FakeStore(rows), [either, neither], ["LOW", "NOCR"], SNAP, IDX)
    assert held.check(either, "NOCR", True, ["proc-1|2026-10-01"]) is None  # dialysis decides; no creatinine needed
    assert held.check(either, "NOCR", False, []) == NOT_STORED  # "neither" needs the score: no row
    assert held.check(neither, "LOW", True, ["o-1|2026-10-06"]) == NOT_STORED  # stored 20 < 30: a contradiction
    assert held.check(neither, "LOW", False, ["o-1|2026-10-06"]) is None


# item 3: a re-run reads what the job read
def test_reads_are_pinned_to_the_batch(db_url: str, tmp_path: Path) -> None:
    lk = _lake(tmp_path)
    st = DerivedStore(db_url)
    run_batch(st, lk, mapping_version="m@1", snapshot=SNAP)
    b = st.batch(SNAP)
    assert b is not None and b.finished_at
    first = st.latest_many(["E-ADULT"], "egfr_ckd_epi", None, IDX, b.finished_at)["E-ADULT"]
    time.sleep(1.1)
    later = {"creatinine": [d.Obs(1.1, "mg/dL", ON, "E-ADULT-cr"), d.Obs(3.0, "mg/dL", ON, "E-ADULT-cr2")]}
    st.recompute("E-ADULT", later, mapping_version="m@2", birth=date(1971, 1, 1), female=True)  # rows superseded
    st.check_documented([Documented("E-ADULT", "egfr_ckd_epi", 90.0, ON, "doc-9", "signed")])
    again = st.latest_many(["E-ADULT"], "egfr_ckd_epi", None, IDX, b.finished_at)["E-ADULT"]
    assert (again.value, again.row_id, again.reason) == (first.value, first.row_id, first.reason)
    now = st.latest_many(["E-ADULT"], "egfr_ckd_epi", None, IDX)["E-ADULT"]
    assert now.row_id != first.row_id  # the live read moved: only the pinned one is the job's
    run_batch(st, lk, mapping_version="m@1", snapshot=SNAP)  # a second batch of the snapshot changes nothing read
    assert st.batch(SNAP) == b


# item 4: a missing or failed batch is seen
def test_a_missing_or_crashed_batch_is_seen(db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from matching.stored_scores import unverified
    from sitesetup.readiness import scores_unverified
    from tb_common.metrics import OK, RED, WARN, check_derive

    lk = _lake(tmp_path)
    st = DerivedStore(db_url)
    crit = [_egfr_crit("egfr")]
    assert unverified(crit, st, SNAP) and not unverified(crit, None, SNAP)  # the flag off: no line
    assert not unverified([_egfr_crit("bmi")], st, SNAP)  # no stored score read
    assert check_derive({"flag": "on", "current": SNAP, "last": None}).level == RED
    assert check_derive({"flag": "off", "current": SNAP, "last": None}).level == WARN
    crashed = {"snapshot": SNAP, "finished_at": None, "failed": None}
    assert check_derive({"flag": "on", "current": SNAP, "last": crashed}).level == RED
    old = {"snapshot": "2026-11-08", "finished_at": "x", "failed": 0}
    assert "has no derive batch" in check_derive({"flag": "on", "current": SNAP, "last": old}).text
    monkeypatch.setenv("TB_DB_URL", db_url)

    class Svc:
        def lake(self, ws: str) -> Any:
            return lk

    st.begin_batch(SNAP, "m@1")  # started, never finished (a crash)
    assert st.last_batch()["finished_at"] is None  # type: ignore[index]
    item = scores_unverified(Svc())  # type: ignore[arg-type]
    assert item is not None and item["key"] == "patients.scores_unverified" and item["tables"] == SNAP
    run_batch(st, lk, mapping_version="m@1", snapshot=SNAP)
    assert scores_unverified(Svc()) is None and not unverified(crit, st, SNAP)  # type: ignore[arg-type]
    good = {"flag": "on", "current": SNAP, "last": st.last_batch()}
    assert check_derive(good).level == OK


# item 5: a 29 February birth, the three engines on 28 February and 1 March
@pytest.mark.parametrize(("day", "adult"), [(date(2026, 2, 28), False), (date(2026, 3, 1), True)])
def test_a_leap_day_birth_has_one_age_in_the_three_engines(tmp_path: Path, day: date, adult: bool) -> None:
    nd = tmp_path / "nd"
    nd.mkdir()
    system, code = d.CODES["creatinine"]
    pat = {"resourceType": "Patient", "id": "LEAP", "birthDate": "2008-02-29", "gender": "female"}
    obs = {"resourceType": "Observation", "id": "LEAP-cr", "status": "final", "subject": {"reference": "Patient/LEAP"},
           "code": {"coding": [{"system": system, "code": code}]}, "effectiveDateTime": "2026-02-20T09:00:00+08:00",
           "valueQuantity": {"value": 0.8, "unit": "mg/dL", "code": "mg/dL"}}  # fmt: skip
    (nd / "Patient.ndjson").write_text(json.dumps(pat) + "\n")
    (nd / "Observation.ndjson").write_text(json.dumps(obs) + "\n")
    Lake(tmp_path / "lake", "Asia/Taipei").rebuild("2026-03-02", HashEmbedder(), nd)
    lk = LakeLocal(tmp_path / "lake", HashEmbedder(), "Asia/Taipei")
    crit = _egfr_crit("egfr")
    rs = _ruleset(crit)
    assert (d.age_at(date(2008, 2, 29), day) >= 18) is adult  # Python
    got = SqlEngine(lk, "2026-03-02").evaluate(rs, ["LEAP"], day, [CID])["LEAP"]  # SQL
    assert (got.results[CID] is not None) is adult and (adult or got.reasons == {CID: "derived_adult_only"})
    from criteria_compiler.compile_cql.generator import CqlGenerator
    from criteria_compiler.compile_cql.translator import Translator, available, fhirhelpers_source
    from tb_common.fhir import FhirEvaluator, library_resource

    from tools import cql_eval

    if not (available() and cql_eval.available()):
        pytest.skip("CQL translator or local CQL engine not available (python -m tools.cql_eval --fetch)")
    gen = CqlGenerator("DER", "1.0.0", ValueSets("DER", _vs(), Terminology()))
    cql = gen.render([crit])
    tr = Translator().translate({"FHIRHelpers": fhirhelpers_source(), "TB_Common": render_common(), gen.library: cql})
    head = next(x for x in cql.splitlines() if x.startswith("library "))
    version = head.split(" version ")[1].strip().strip("'")
    libs = [library_resource("TB_Common", "1.0.0", render_common(), tr.elm.get("TB_Common")),
            library_resource(gen.library, version, cql, tr.elm.get(gen.library))]  # fmt: skip
    lines = [json.dumps(pat), json.dumps(obs), *(json.dumps(v) for v in _vs().values()), *map(json.dumps, libs)]
    exprs = CqlGenerator.expression_names([crit])
    (body,) = cql_eval.run(lines, gen.library, version, day, exprs, ["LEAP"])
    cql_got = FhirEvaluator.parse("LEAP", day, body, exprs).results.get(CID)
    assert (cql_got is not None) is adult  # CQL
