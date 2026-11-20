"""D-275, second review (findings F1-F13): the status of an order or a result decides nothing when nobody can read
it, a value equal to the bound in another unit is equal, and the guard of approved SQL fails per criterion.

F1 and F3 run end to end from SS-MIX2 storage files (HL7 v2: ORC-5, OBX-11) through the reader, the real Japanese
site mapping (``jp_core/ssmix2_site.yaml``, which extends ``tw_core/demo_his.yaml``), the lake and the compiled SQL.
Every patient named "was" here was excluded, or met an exclusion, before the fix.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_sql import overlay
from criteria_compiler.compile_sql.generator import MARK, SqlGenerator
from criteria_compiler.compile_sql.overlay import guarded, safe_sql
from criteria_compiler.semantics import CompileError
from criteria_compiler.terminology.mapper import Concept, Terminology, ValueSets, valueset
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.flatten import Flattener, uncertain
from lake.store import Lake
from orchestrator.scenarios.evaluate import SqlEngine, structured_verdict
from tb_common import id_rule, labunit
from tb_common.crypto import pid_for_mrn
from tb_common.ruleset import Ruleset

from tests.unit.test_criteria_safety import (
    CREAT,
    GLP1,
    GLP1_EXC,
    HBA1C_EXC,
    IDX,
    LOINC,
    ROOT,
    _crit,
    _med,
    _obs,
    _pat,
    _ruleset,
    _w,
    _write,
)

JP_MAPPING = ROOT / "services/adapter/mapping/jp_core/ssmix2_site.yaml"
TW_MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
HBA1C_JLAC10 = "3D046000001906202"  # jlac10_to_loinc.csv -> LOINC 4548-4 (%)
SNAP = "2026-10-04"


# ------------------------------------------------------------------------------------------------ SS-MIX2 storage
def _store(root: Path, patient: str, day: str, typ: str, order: str, segs: list[str]) -> None:
    from adapter.sources.ssmix2.source import storage_dir

    msh = f"MSH|^~\\&|HIS||TB||20261001||X|{order}|P|2.5||||||~ISO IR87"
    d = storage_dir(root, patient, day, typ)
    d.mkdir(parents=True, exist_ok=True)
    pid = (
        [] if any(s.startswith("PID|") for s in segs) else [f"PID|||{patient}^^^^PI"]
    )  # every SS-MIX2 message carries its patient (PR #1095 fourth review b)
    text = "\r".join([msh, *pid, *segs]) + "\r"
    (d / f"{patient}_{day}_{typ}_{order}_20261001000000000_-_1").write_bytes(text.encode("iso2022_jp"))


def _patient(root: Path, mrn: str) -> None:
    _store(root, mrn, "-", "ADT-00", "-", ["EVN||", f"PID|||{mrn}^^^^PI||テスト^太郎||19700101|F"])


def _order(root: Path, mrn: str, orc5: str) -> None:
    """A GLP-1 RA prescription (ATC A10BJ02 as RXE-2's alternate) ordered 2026-09-20 with ORC-5 as given."""
    orc = f"ORC|NW|RX-{mrn}||1|{orc5}||||20260920"
    rxe = f"RXE||620009301^リラグルチド皮下注^99YJ^{GLP1}^^WHOATC|1||本"
    _store(root, mrn, "20260920", "OMP-01", f"RX-{mrn}", [orc, rxe])


def _hba1c(root: Path, mrn: str, obx11: str) -> None:
    """An HbA1c of 11.0 % (over the exclusion's 10 %) drawn 2026-09-20, OBX-11 as given."""
    obx = ["OBX", "1", "NM", f"{HBA1C_JLAC10}^HbA1c^JC10", "", "11.0", "%", *[""] * 15]
    obx[11], obx[14], obx[21] = obx11, "20260920090000", f"LAB-{mrn}"
    _store(root, mrn, "20260920", "OML-11", f"LAB-{mrn}", [f"OBR|1|LAB-{mrn}", "|".join(obx)])


# mrn -> (ORC-5 of a GLP-1 RA order, OBX-11 of an HbA1c of 11 %); None: no such record
STORAGE: dict[str, tuple[str | None, str | None]] = {
    "10000001": ("IP", None),  # an order in process: met
    "10000002": ("CA", None),  # cancelled: was "active" through the site mapping, met the exclusion
    "10000003": ("ER", None),  # error / order not found: not an order
    "10000004": ("ZZ", None),  # a code nobody knows: was "active"; now unknown (the order cannot be placed)
    "10000005": ("", None),  # no ORC-5 at all: not recorded, counts as before
    "10000011": (None, "F"),  # final: met
    "10000012": (None, "W"),  # posted as wrong: was a final result that met the exclusion
    "10000013": (None, "D"),  # deleted: the same
    "10000014": (None, "P"),  # preliminary: unknown
    "10000015": (None, "Q"),  # a code nobody knows: was final; now unknown
    "10000016": (None, ""),  # no OBX-11: not recorded, counts as before
}


@pytest.fixture(scope="module")
def jp_lake(tmp_path_factory: pytest.TempPathFactory, pg_cluster_url: str) -> tuple[LakeLocal, dict[str, str]]:
    from adapter.pipeline import AdapterConfig, run_ingest

    tmp = tmp_path_factory.mktemp("ss-status")
    root = tmp / "storage"
    for mrn, (orc5, obx11) in STORAGE.items():
        _patient(root, mrn)
        if orc5 is not None:
            _order(root, mrn, orc5)
        if obx11 is not None:
            _hba1c(root, mrn, obx11)
    sec = tmp / "sec"
    sec.mkdir()
    key = b"trialbox-test-site-key-0123456789abcdef"
    (sec / "site_hmac.key").write_bytes(key)
    (sec / "site_hmac.key").chmod(0o600)
    cfg = AdapterConfig(
        lake_dir=tmp / "ingest",
        secrets_dir=sec,
        mapping_path=JP_MAPPING,
        site_id="JP-SS",
        tz="Asia/Tokyo",
        audit_dir=tmp / "audit",
        db_url=f"{pg_cluster_url}{'&' if '?' in pg_cluster_url else '?'}tb_prefix=ssstatus_",
        validation_max_pct=100.0,
    )
    rep = run_ingest(cfg, "ssmix2", str(root), snapshot=SNAP, load_fhir=False, rebuild_lake=False, validate=False)
    assert not rep.errors, rep.errors
    Lake(tmp / "lake", "Asia/Tokyo").rebuild(SNAP, HashEmbedder(), tmp / "ingest" / "ndjson" / SNAP)
    pids = {mrn: pid_for_mrn(key, mrn) for mrn in STORAGE}
    return LakeLocal(tmp / "lake", HashEmbedder(), "Asia/Tokyo"), pids


def test_a_cancelled_or_unreadable_order_status_through_the_real_site_mapping(
    jp_lake: tuple[LakeLocal, dict[str, str]],
) -> None:
    """F1: ORC-5 CA / ER never reaches the lake as an order; an unknown ORC-5 is unknown, not "active"."""
    lk, pids = jp_lake
    rs = _ruleset(GLP1_EXC)
    rows = {r["pid"]: r for r in lk.query(rs.sql, [[IDX.isoformat()], list(pids.values())]).to_pylist()}
    got = {mrn: rows[pid]["C_SAFE-EXC-03"] for mrn, pid in pids.items() if STORAGE[mrn][0] is not None}
    assert got == {"10000001": True, "10000002": False, "10000003": False, "10000004": None, "10000005": True}
    ev = SqlEngine(lk).evaluate(rs, list(pids.values()), IDX, [GLP1_EXC.id])
    verdict = {mrn: structured_verdict(GLP1_EXC, ev[pids[mrn]]).verdict for mrn in ("10000002", "10000004")}
    assert verdict == {"10000002": "pass", "10000004": "unknown"}  # kept; the unknown one is a point to check
    meds = lk.query("SELECT pid, status, authored FROM medication").to_pylist()
    by = {r["pid"]: r for r in meds}
    assert pids["10000002"] not in by and pids["10000003"] not in by
    assert by[pids["10000004"]]["status"] == "unknown" and by[pids["10000004"]]["authored"] is None
    assert by[pids["10000005"]]["authored"] == date(2026, 9, 20)


def test_a_wrong_deleted_or_unreadable_result_status_decides_nothing(jp_lake: tuple[LakeLocal, dict[str, str]]) -> None:
    """F3: OBX-11 is read. W / D (wrong, deleted) reach no table; P and an unknown code keep no value; an empty
    OBX-11 is "not recorded" and counts."""
    lk, pids = jp_lake
    rs = _ruleset(HBA1C_EXC)
    rows = {r["pid"]: r for r in lk.query(rs.sql, [[IDX.isoformat()], list(pids.values())]).to_pylist()}
    got = {mrn: rows[pid]["C_SAFE-EXC-01"] for mrn, pid in pids.items() if STORAGE[mrn][1] is not None}
    assert got == {
        "10000011": True,
        "10000012": None,
        "10000013": None,
        "10000014": None,
        "10000015": None,
        "10000016": True,
    }
    obs = {r["pid"]: r for r in lk.query("SELECT pid, value_num FROM observation").to_pylist()}
    assert pids["10000012"] not in obs and pids["10000013"] not in obs
    assert obs[pids["10000014"]]["value_num"] is None and obs[pids["10000015"]]["value_num"] is None
    assert obs[pids["10000016"]]["value_num"] == 11.0


def test_the_csv_site_mapping_never_invents_a_status() -> None:
    """F1 / F3 in the shared TW mapping a CSV HIS uses: words it knows pass, a code it does not know is
    ``unknown``, an empty status is ``unknown`` tagged "not recorded" (the record counts)."""
    from adapter.mapping.engine import Mapper, Mapping

    mp = Mapper(Mapping.load(TW_MAPPING), b"k" * 32, "s")
    base = {"rx_no": "R", "mrn": "P1", "nhi_drug_code": "", "atc": GLP1, "drug_name": "x", "order_date": "2026-09-20",
            "start_date": "", "end_date": "", "daily_dose": "", "dose_unit": "", "enc_no": "", "dept_code": ""}  # fmt: skip
    for status, want, counted in (
        ("active", "active", True),
        ("cancelled", "cancelled", False),
        ("entered-in-error", "entered-in-error", False),
        ("draft", "draft", False),
        ("CANCELED", "unknown", None),
        ("", "unknown", True),
    ):
        (res,) = list(mp.map_table("medication", iter([{**base, "status": status}])))
        assert res["status"] == want, status
        rows = Flattener().flatten({"MedicationRequest": [res]})["medication"]
        if counted is False:
            assert rows == [], status
        elif counted is None:
            assert uncertain("MedicationRequest", res) and rows[0]["authored"] is None, status
        else:
            assert rows[0]["authored"] == date(2026, 9, 20), status


# ------------------------------------------------------------------------------------------------ F2, F4: bounds
def test_a_value_equal_to_the_bound_in_the_other_unit_is_equal(tmp_path: Path) -> None:
    pats = {"B-MGDL": (1.5, "mg/dL"), "B-UMOL": (309.4, "umol/L"), "B-UMOL2": (132.6, "umol/L")}
    nd = tmp_path / "ndjson"
    nd.mkdir()
    _write(nd, "Patient", [_pat(p) for p in pats])
    _write(nd, "Observation", [_obs(p, 1, CREAT, v, u) for p, (v, u) in pats.items()])
    _write(nd, "Condition", [])
    id_rule.write_snapshot_record(nd)  # D-1253: a snapshot of this release
    Lake(tmp_path / "lake").rebuild("2026-10-05", HashEmbedder(), nd)
    lk = LakeLocal(tmp_path / "lake", HashEmbedder())

    def creat(cid: str, op: str, num: float, unit: str) -> Any:
        logic = {"domain": "observation", "quantifier": "latest", "valueset": "VS_CREAT",
                 "value": {"op": op, "num": num, "unit": unit}, "window": _w(365)}  # fmt: skip
        return _crit(cid, "inclusion", logic)

    crits = [
        creat("SAFE-INC-31", "<=", 132.6, "umol/L"),  # 1.5 mg/dL is 132.6 umol/L: was 132.60000000000002, FALSE
        creat("SAFE-INC-32", ">=", 3.5, "mg/dL"),  # 309.4 umol/L is 3.5 mg/dL: was 3.4999999999999996, FALSE
        creat("SAFE-INC-33", "<=", 1.5, "mg/dL"),  # 132.6 umol/L is 1.5 mg/dL
    ]
    rows = {r["pid"]: r for r in lk.query(_ruleset(*crits).sql, [[IDX.isoformat()], list(pats)]).to_pylist()}
    assert rows["B-MGDL"]["C_SAFE-INC-31"] is True
    assert rows["B-UMOL"]["C_SAFE-INC-32"] is True
    assert rows["B-UMOL2"]["C_SAFE-INC-33"] is True
    assert labunit.convert(1.5, "mg/dL", "umol/L", LOINC, CREAT) == 132.6
    assert labunit.convert(309.4, "umol/L", "mg/dL", LOINC, CREAT) == 3.5
    from criteria_compiler.compile_cql.generator import CqlGenerator

    vs = {"VS_CREAT": valueset("SAFE", "VS_CREAT", "creatinine", [Concept(LOINC, CREAT, "creatinine")], "1.0.0")}
    cql = CqlGenerator("SAFE", "1.0.0", ValueSets("SAFE", vs, Terminology())).render(crits)
    assert "then Round(Q.value.value / 88.4, 6)" in cql and "then Round(Q.value.value * 88.4, 6)" in cql
    assert "0.01131222" not in cql  # the 8-decimal factor that put 132.6 umol/L above 1.5 mg/dL


# ------------------------------------------------------------------------------------------------ F5, F8, F9, F12
def _stale(rs: Ruleset) -> Ruleset:
    """The same criteria as SQL approved before D-275 (no mark in the header, bare numbers for a lab)."""
    old = rs.sql.replace(MARK, "-- (compiled before D-275)", 1)  # the header's mark only
    return Ruleset(manifest=rs.manifest, criteria=rs.criteria, valuesets=rs.valuesets, sql=old)


def test_a_criterion_the_guard_cannot_render_is_unknown_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F5 / F12: one criterion the current generator refuses is unknown with ``rules_changed``; the others are
    guarded as usual and the job goes on. The guard is built once per ruleset content."""
    nd = tmp_path / "ndjson"
    nd.mkdir()
    _write(nd, "Patient", [_pat("P1")])
    _write(nd, "MedicationRequest", [_med("P1", 1, GLP1, "2026-09-20")])
    _write(nd, "Observation", [_obs("P1", 1, CREAT, 1.0, "mg/dL")])
    _write(nd, "Condition", [])
    id_rule.write_snapshot_record(nd)  # D-1253: a snapshot of this release
    Lake(tmp_path / "lake").rebuild("2026-10-05", HashEmbedder(), nd)
    lk = LakeLocal(tmp_path / "lake", HashEmbedder())
    inc = _crit("SAFE-INC-41", "inclusion", {"domain": "observation", "quantifier": "latest", "valueset": "VS_CREAT",
                                             "value": {"op": "<=", "num": 1.5, "unit": "mg/dL"}, "window": _w(365)})  # fmt: skip
    stale = _stale(_ruleset(GLP1_EXC, inc))
    calls: list[list[str]] = []

    class Refusing(SqlGenerator):
        def render(self, criteria: list[Any]) -> str:
            calls.append([c.id for c in criteria])
            if any(c.id == GLP1_EXC.id for c in criteria):
                raise CompileError("refused")
            return super().render(criteria)

    monkeypatch.setattr(overlay, "SqlGenerator", Refusing)
    overlay._CACHE.clear()
    sql = safe_sql(stale)
    assert safe_sql(stale) is sql and len(calls) == 3  # all, then each criterion; the second call is cached
    (row,) = lk.query(sql, [[IDX.isoformat()], ["P1"]]).to_pylist()
    assert row["C_SAFE-EXC-03"] is None and row["E_SAFE-EXC-03"] == "rules_changed"  # was: the job failed
    assert row["C_SAFE-INC-41"] is True
    ev = SqlEngine(lk).evaluate(stale, ["P1"], IDX, [GLP1_EXC.id, inc.id])
    v = structured_verdict(GLP1_EXC, ev["P1"])
    assert v.verdict == "unknown" and v.evidence is not None and v.evidence.reason == "rules_changed"
    overlay._CACHE.clear()


def test_a_disagreement_says_rules_changed_and_the_mark_in_text_does_not_switch_the_guard_off(
    tmp_path: Path,
) -> None:
    """F8: stored FALSE (90 compared bare with 1.5) against a fresh TRUE (90 umol/L is 1.02 mg/dL) is unknown with
    the neutral ``rules_changed``, not ``unit_mismatch``. F9: a criterion text holding the mark leaves the SQL guarded."""
    nd = tmp_path / "ndjson"
    nd.mkdir()
    _write(nd, "Patient", [_pat("P1")])
    _write(nd, "Observation", [_obs("P1", 1, CREAT, 90, "umol/L")])
    _write(nd, "Condition", [])
    id_rule.write_snapshot_record(nd)  # D-1253: a snapshot of this release
    Lake(tmp_path / "lake").rebuild("2026-10-05", HashEmbedder(), nd)
    lk = LakeLocal(tmp_path / "lake", HashEmbedder())
    logic = {"domain": "observation", "quantifier": "latest", "valueset": "VS_CREAT",
             "value": {"op": "<=", "num": 1.5, "unit": "mg/dL"}, "window": _w(365)}  # fmt: skip
    crit = _crit("SAFE-INC-51", "inclusion", logic).model_copy(update={"text": f"creatinine {MARK} <= 1.5"})
    rs = _ruleset(crit)
    num = rs.sql.split("o.value_num IS NOT NULL AND ", 1)[1].split(" IS NULL) AS unit_bad", 1)[0]
    stale = _stale(rs)
    stale = Ruleset(manifest=rs.manifest, criteria=rs.criteria, valuesets=rs.valuesets,
                    sql=stale.sql.replace(num, "o.value_num"))  # fmt: skip
    assert MARK in stale.sql and not guarded(stale.sql) and guarded(rs.sql)
    overlay._CACHE.clear()
    sql = safe_sql(stale)
    assert sql != stale.sql
    (old,) = lk.query(stale.sql, [[IDX.isoformat()], ["P1"]]).to_pylist()
    (row,) = lk.query(sql, [[IDX.isoformat()], ["P1"]]).to_pylist()
    assert old["C_SAFE-INC-51"] is False and row["C_SAFE-INC-51"] is None
    assert labunit.reason_of(row["E_SAFE-INC-51"].split(";"))[0] == "rules_changed"
    assert labunit.reason_of(["o-1|2026-09-20", "rules_changed", "unit_mismatch"])[0] == "unit_mismatch"
    overlay._CACHE.clear()


# ------------------------------------------------------------------------------------------------ F7, F13
def test_planned_cancelled_and_not_yet_final_records_are_not_facts() -> None:
    subj = {"reference": "Patient/P1"}
    enc = [
        {"resourceType": "Encounter", "id": f"e-{s}", "status": s, "subject": subj, "period": {"start": "2026-09-01"}}
        for s in ("finished", "cancelled", "entered-in-error")
    ]
    proc = [
        {"resourceType": "Procedure", "id": f"pr-{s}", "status": s, "subject": subj}
        for s in ("completed", "preparation")
    ]
    tag = {"tag": [{"system": "urn:trialbox:status-source", "code": "not-recorded"}]}
    obs = [
        _obs("P1", 1, CREAT, 1.0, "mg/dL", status="registered"),
        _obs("P1", 2, CREAT, 1.0, "mg/dL", status="preliminary"),
        _obs("P1", 3, CREAT, 1.0, "mg/dL", status="unknown"),
        _obs("P1", 4, CREAT, 1.0, "mg/dL", status="unknown") | {"meta": tag},
    ]
    out = Flattener().flatten({"Encounter": enc, "Procedure": proc, "Observation": obs})
    assert [r["eid"] for r in out["encounter"]] == ["e-finished"]
    assert [r["prid"] for r in out["procedure"]] == ["pr-completed"]
    assert {r["oid"]: r["value_num"] for r in out["observation"]} == {"o-P1-2": None, "o-P1-3": None, "o-P1-4": 1.0}


def test_cql_reads_an_empty_quantity_code_as_no_code() -> None:
    from criteria_compiler.compile_cql.generator import render_common

    assert "if Q.code.value = '' then null else Q.code.value, Q.unit.value, ''" in render_common()


_ = (HBA1C_EXC, date)
