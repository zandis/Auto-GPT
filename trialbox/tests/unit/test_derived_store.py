"""Stored derived rows (WS-04.3, D-190): provenance, recompute only on a change, conflicts with a documented score.

Synthetic patients only. Each test has its own trial-database schemas (``conftest._private_trial_db``)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from tb_common import derived as d
from tb_common import scores
from tb_common.derived_store import DerivedError, DerivedStore, Documented, Report, rows_from_lake, run_batch

V1 = date(2026, 9, 1)  # first visit
V2 = date(2026, 10, 6)  # second visit
MAP = "site-mapping@3+ab12"


def _o(comp: str, value: float | None, on: date, oid: str, unit: str | None = None, status: str = "final") -> d.Obs:
    return d.Obs(value, unit, on, oid, status)


def _ra_rows(crp_v2: float = 1.5, ptga_v2_status: str = "final") -> dict[str, list[d.Obs]]:
    """Two RA visits. V1: CDAI 14.5, SDAI 14.5 + 0.8. V2: 8 + 6 + 7 + 6 = 27, SDAI 27 + CRP (mg/dL)."""
    return {
        "tjc28": [_o("tjc28", 4, V1, "obs-t1"), _o("tjc28", 8, V2, "obs-t2")],
        "sjc28": [_o("sjc28", 3, V1, "obs-s1"), _o("sjc28", 6, V2, "obs-s2")],
        "ptga10": [_o("ptga10", 40, V1, "obs-p1", "mm"), _o("ptga10", 7, V2, "obs-p2", status=ptga_v2_status)],
        "evga": [_o("evga", 3.5, V1, "obs-e1"), _o("evga", 6, V2, "obs-e2")],
        "crp": [_o("crp", 8, V1 + timedelta(days=2), "obs-c1", "mg/L"), _o("crp", crp_v2, V2, "obs-c2", "mg/dL")],
        "creatinine": [_o("creatinine", 1.1, V1, "obs-cr1", "mg/dL")],
    }


def _by(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(r["score"], r["anchor_oid"]): r for r in rows}


def test_rows_carry_provenance_and_definition(db_url: str) -> None:
    st = DerivedStore(db_url)
    rep = st.recompute("P-RA1", _ra_rows(), mapping_version=MAP, birth=date(1971, 1, 1), female=True,
                       only=["cdai", "sdai", "egfr_jsn", "egfr_ckd_epi"])  # fmt: skip
    rows = _by(st.rows("P-RA1"))
    assert rep.inserted == len(rows) == 6 and rep.unchanged == 0
    v1 = rows[("cdai", "obs-t1")]
    assert v1["value"] == pytest.approx(14.5) and v1["reason"] is None  # PtGA 40 mm read as 4.0 on the 0-10 scale
    assert v1["def_version"] == "rheum.cdai@1" and v1["def_sha"] == scores.definition("cdai")["sha256"]
    assert v1["mapping_version"] == MAP and v1["unit"] == "{score}" and v1["anchor_date"] == V1
    ptga = next(i for i in v1["inputs"] if i["component"] == "ptga10")
    assert ptga == {"component": "ptga10", "table": "observation", "id": "obs-p1", "date": V1.isoformat(),
                    "value": 40, "unit": "mm", "status": "final", "used_value": 4.0, "used_unit": "{score}"}  # fmt: skip
    assert rows[("sdai", "obs-t1")]["value"] == pytest.approx(15.3)  # CRP 8 mg/L = 0.8 mg/dL, 2 days after
    assert rows[("sdai", "obs-t2")]["value"] == pytest.approx(28.5)  # CRP 1.5 mg/dL
    jsn = rows[("egfr_jsn", "obs-cr1")]
    assert round(jsn["value"], 1) == 40.9 and {i["component"] for i in jsn["inputs"]} == {"creatinine", "age", "sex"}
    assert round(rows[("egfr_ckd_epi", "obs-cr1")]["value"], 1) == 59.3  # the same woman, the other equation
    links = st._db.fetchall("SELECT component, source_table, source_id FROM input_link WHERE row_id = ?",
                            (v1["id"],))  # fmt: skip
    assert sorted(links) == [("evga", "observation", "obs-e1"), ("ptga10", "observation", "obs-p1"),
                             ("sjc28", "observation", "obs-s1"), ("tjc28", "observation", "obs-t1")]  # fmt: skip


def test_recompute_only_when_an_input_mapping_or_version_changes(db_url: str) -> None:
    st = DerivedStore(db_url)
    kw: dict[str, Any] = {"mapping_version": MAP, "only": ["cdai", "sdai"]}
    assert st.recompute("P-RA1", _ra_rows(), **kw).inserted == 4
    again = st.recompute("P-RA1", _ra_rows(), **kw)
    assert (again.inserted, again.unchanged) == (0, 4)  # nothing changed: nothing written
    before = _by(st.rows("P-RA1"))
    # a corrected CRP at V2 changes the SDAI of V2 only: the CDAI does not use the CRP and V1 has its own CRP
    rep = st.recompute("P-RA1", _ra_rows(crp_v2=2.5), **kw)
    assert (rep.inserted, rep.superseded, rep.unchanged) == (1, 1, 3)
    after = _by(st.rows("P-RA1"))
    assert after[("sdai", "obs-t2")]["value"] == pytest.approx(29.5)
    old = before[("sdai", "obs-t2")]
    hist = {r["id"]: r for r in st.rows("P-RA1", "sdai", current=False)}
    assert hist[old["id"]]["superseded_by"] == after[("sdai", "obs-t2")]["id"]  # kept, never updated in place
    assert after[("cdai", "obs-t2")]["id"] == before[("cdai", "obs-t2")]["id"]
    # a new mapping version recomputes every row (a code may have moved into or out of a component)
    assert st.recompute("P-RA1", _ra_rows(crp_v2=2.5), mapping_version="site-mapping@4", only=["cdai", "sdai"]
                        ).superseded == 4  # fmt: skip
    # an anchor gone at the source retires its rows
    rows = _ra_rows(crp_v2=2.5)
    rows["tjc28"] = rows["tjc28"][:1]
    rep = st.recompute("P-RA1", rows, mapping_version="site-mapping@4", only=["cdai", "sdai"])
    assert (rep.retired, rep.inserted) == (2, 0) and {k[1] for k in _by(st.rows("P-RA1"))} == {"obs-t1"}


def test_a_new_definition_version_recomputes(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    st = DerivedStore(db_url)
    st.recompute("P-RA1", _ra_rows(), mapping_version=MAP, only=["cdai"])
    orig = scores.definition
    bumped = {**orig("cdai"), "version": 2, "def_version": "rheum.cdai@2", "sha256": "f" * 64}
    monkeypatch.setattr(scores, "definition", lambda s: bumped if s == "cdai" else orig(s))
    st2 = DerivedStore(db_url)  # loads rheum.cdai@2 beside @1 (old rows keep their version)
    rep = st2.recompute("P-RA1", _ra_rows(), mapping_version=MAP, only=["cdai"])
    assert rep.superseded == 2 and {r["def_version"] for r in st2.rows("P-RA1", "cdai")} == {"rheum.cdai@2"}
    # the same version with other content is refused: a stored row's def_version means one formula
    monkeypatch.setattr(scores, "definition", lambda s: {**bumped, "sha256": "0" * 64} if s == "cdai" else orig(s))
    with pytest.raises(DerivedError, match="changed under the same version"):
        DerivedStore(db_url)


def test_proposed_facts_never_count_and_missing_inputs_say_why(db_url: str) -> None:
    st = DerivedStore(db_url)
    st.recompute("P-RA1", _ra_rows(ptga_v2_status="proposed"), mapping_version=MAP, only=["cdai"])
    v2 = _by(st.rows("P-RA1"))[("cdai", "obs-t2")]
    assert v2["value"] is None and v2["reason"] == "derived_missing_input:ptga10"  # no value, never 0
    latest = st.latest("P-RA1", "cdai", V2)
    assert latest.value is None and latest.reason == "derived_missing_input:ptga10"  # unknown for a reader
    # the coordinator confirms the fact: the inputs change and only that row is recomputed
    rep = st.recompute("P-RA1", _ra_rows(ptga_v2_status="confirmed"), mapping_version=MAP, only=["cdai"])
    assert (rep.inserted, rep.superseded, rep.unchanged) == (1, 1, 1)
    assert st.latest("P-RA1", "cdai", V2).value == pytest.approx(27)
    # a proposed anchor makes no row at all
    rows = _ra_rows()
    rows["tjc28"] = [_o("tjc28", 4, V1, "obs-t1", status="proposed")]
    st.recompute("P-RA2", rows, mapping_version=MAP, only=["cdai"])
    assert st.rows("P-RA2") == []
    assert st.latest("P-RA2", "cdai", V2).reason == "derived_missing_input:tjc28"
    assert st.latest("P-RA1", "cdai", V2 + timedelta(days=200)).value is None  # outside the 90-day window


def test_documented_score_conflict_is_flagged_not_overwritten(db_url: str) -> None:
    st = DerivedStore(db_url)
    docs = [
        Documented("P-RA1", "cdai", 27.4, V2 + timedelta(days=1), "note-1", "signed"),  # within 0.5: agrees
        Documented("P-RA1", "cdai", 22.0, V2, "note-2", "proposed"),  # 5 below the computed 27: conflict
        Documented("P-RA1", "cdai", 3.0, V2 + timedelta(days=30), "note-3", "signed"),  # no computed row near it
        Documented("P-RA1", "cdai", 1.0, V2, "note-4", "rejected"),  # rejected: not a documented value
    ]
    rep = st.recompute("P-RA1", _ra_rows(), mapping_version=MAP, only=["cdai"], documented=docs)
    assert rep.conflicts == 1
    (c,) = st.conflicts("P-RA1")
    assert (c["kind"], c["documented_id"], c["documented_value"], c["derived_value"], c["tolerance"]) == (
        "derived_vs_documented", "note-2", 22.0, pytest.approx(27.0), 0.5)  # fmt: skip
    assert _by(st.rows("P-RA1"))[("cdai", "obs-t2")]["value"] == pytest.approx(27)  # the computed row stands
    assert st.check_documented(docs) == 0  # an open conflict is never opened twice
    held = st.latest("P-RA1", "cdai", V2)
    assert held.value is None and held.reason == "derived_vs_documented"  # unknown until a person decides
    with pytest.raises(DerivedError):
        st.resolve(c["id"], "average", "steward-1")
    st.resolve(c["id"], "keep_documented", "pi-1")
    kept = st.latest("P-RA1", "cdai", V2)
    assert (kept.value, kept.source) == (22.0, "documented")
    with pytest.raises(DerivedError, match="not open"):
        st.resolve(c["id"], "keep_derived", "pi-1")
    assert st.conflicts("P-RA1") == [] and len(st.conflicts("P-RA1", open_only=False)) == 1


def test_a_recomputed_row_rechecks_its_conflicts(db_url: str) -> None:
    st = DerivedStore(db_url)
    doc = [Documented("P-RA1", "sdai", 28.5, V2, "note-9", "signed")]
    assert st.recompute("P-RA1", _ra_rows(), mapping_version=MAP, only=["sdai"], documented=doc).conflicts == 0
    # the CRP is corrected: SDAI 29.5 is 1.0 from the written 28.5, so a conflict opens on the new row
    rep = st.recompute("P-RA1", _ra_rows(crp_v2=2.5), mapping_version=MAP, only=["sdai"], documented=doc)
    assert rep.conflicts == 1
    # corrected back: the open conflict of the superseded row is closed as superseded, none on the new row
    rep = st.recompute("P-RA1", _ra_rows(), mapping_version=MAP, only=["sdai"], documented=doc)
    assert rep.conflicts == 0 and st.conflicts("P-RA1") == []
    assert [c["resolution"] for c in st.conflicts("P-RA1", open_only=False)] == ["superseded"]


def test_bad_calls_are_refused(db_url: str) -> None:
    st = DerivedStore(db_url)
    with pytest.raises(DerivedError, match="mapping version"):
        st.recompute("P", {}, mapping_version="")
    with pytest.raises(DerivedError, match="not a stored score"):
        st.recompute("P", {}, mapping_version=MAP, only=["bmi"])
    assert st.recompute("P", {}, mapping_version=MAP) == Report()


def test_the_nightly_batch_reads_the_lake(db_url: str, tmp_path: Path) -> None:
    nd = tmp_path / "nd"
    nd.mkdir()
    pat = {"resourceType": "Patient", "id": "L-1", "birthDate": "1971-01-01", "gender": "female"}

    def obs(n: int, comp: str, value: float, unit: str | None) -> dict[str, Any]:
        system, code = d.CODES[comp]
        q: dict[str, Any] = {"value": value} | ({"unit": unit, "code": unit} if unit else {})
        return {"resourceType": "Observation", "id": f"L-1-{n}", "subject": {"reference": "Patient/L-1"},
                "code": {"coding": [{"system": system, "code": code}]},
                "effectiveDateTime": "2026-10-06T09:00:00+09:00", "valueQuantity": q}  # fmt: skip

    rows = [obs(1, "tjc28", 4, None), obs(2, "sjc28", 3, None), obs(3, "ptga10", 4.0, None), obs(4, "evga", 3.5, None),
            obs(5, "crp", 1.0, "mg/dL"), obs(6, "creatinine", 1.1, "mg/dL")]  # fmt: skip
    (nd / "Patient.ndjson").write_text(json.dumps(pat) + "\n")
    (nd / "Observation.ndjson").write_text("\n".join(json.dumps(o) for o in rows) + "\n")
    Lake(tmp_path / "lake", "Asia/Tokyo").rebuild("2026-11-09", HashEmbedder(), nd)
    lake = LakeLocal(tmp_path / "lake", HashEmbedder(), "Asia/Tokyo")
    got = rows_from_lake(lake, ["L-1"])
    assert got["L-1"][1] == date(1971, 1, 1) and got["L-1"][2] is True
    st = DerivedStore(db_url)
    rep = run_batch(st, lake, mapping_version=MAP)
    by = _by(st.rows("L-1"))
    assert by[("cdai", "L-1-1")]["value"] == pytest.approx(14.5)
    assert by[("sdai", "L-1-1")]["value"] == pytest.approx(15.5)
    assert round(by[("egfr_jsn", "L-1-6")]["value"], 1) == 40.9
    # DAS28 variants with no patient global (0-100 mm) at the visit: no value, with the reason
    assert by[("das28_crp", "L-1-1")]["reason"] == "derived_missing_input:ptga"
    assert rep.inserted == 6 and run_batch(st, lake, mapping_version=MAP).unchanged == 6
