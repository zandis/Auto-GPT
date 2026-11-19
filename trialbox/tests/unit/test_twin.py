"""The patient twin, ``tb_patient_profile`` v1 (T-204, D-440).

Acceptance of the card: the twin validates against its schema; a confirmed fact is in the twin after one build tick;
the assembler is deterministic (two runs, same bytes); every layer is stamped with its version and a layer not built
is ``null``; a twin is never assembled for an opted-out patient. Synthetic pseudonyms and values only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from patient_profile import twin as tw
from tb_common import derived as d
from tb_common.derived_store import DerivedStore, run_batch
from tb_common.optout import OptOutRegister
from tb_contracts.schema import schema_errors

P1 = "TWINPID0001"
P2 = "TWINPID0002"
S1, S2 = "2026-11-09", "2026-11-10"
NOW = "2026-11-10T18:00:00+00:00"
ZONE = "Asia/Tokyo"  # a synthetic site's zone for the lake build


def _meta(table: str, h: str) -> dict[str, Any]:
    return {"source": f"site1/{table}#{h}", "tag": [{"system": "urn:trialbox:mapping-version", "code": "map@3"}]}


def _obs(pid: str, n: int, comp: str, value: float, unit: str | None, day: str = "2026-10-06",
         basis: str | None = None) -> dict[str, Any]:  # fmt: skip
    system, code = d.CODES[comp]
    q: dict[str, Any] = {"value": value} | ({"unit": unit, "code": unit} if unit else {})
    r: dict[str, Any] = {"resourceType": "Observation", "id": f"{pid}-o{n}", "status": "final",
                         "subject": {"reference": f"Patient/{pid}"},
                         "code": {"coding": [{"system": system, "code": code}]},
                         "effectiveDateTime": f"{day}T09:00:00+09:00", "valueQuantity": q}  # fmt: skip
    if basis is None:
        r["meta"] = _meta("lab_result", f"h{pid[-1]}{n}")
    else:  # a site fact (D-135): proposed (read from a chart) or confirmed by a person
        r["meta"] = {"tag": [{"system": "urn:trialbox:basis", "code": basis}]}
    return r


def _cond(pid: str, n: int, code: str, day: str) -> dict[str, Any]:
    return {"resourceType": "Condition", "id": f"{pid}-c{n}", "subject": {"reference": f"Patient/{pid}"},
            "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": code}]},
            "recordedDate": day, "clinicalStatus": {"coding": [{"code": "active"}]},
            "meta": _meta("diagnosis", f"d{pid[-1]}{n}")}  # fmt: skip


def _feed() -> dict[str, list[dict[str, Any]]]:
    pats = [{"resourceType": "Patient", "id": p, "birthDate": "1971-01-01", "gender": "female",
             "meta": _meta("patient", f"p{p[-1]}")} for p in (P1, P2)]  # fmt: skip
    obs = [_obs(P1, 1, "creatinine", 1.1, "mg/dL"), _obs(P1, 2, "crp", 1.0, "mg/dL", day="2026-09-01"),
           _obs(P2, 1, "creatinine", 0.8, "mg/dL")]  # fmt: skip
    conds = [
        _cond(P1, 1, "M05.79", "2025-03-01"),
        _cond(P1, 2, "M05.79", "2026-02-01"),
        _cond(P1, 3, "E11.9", "2024-01-05"),
    ]
    return {"Patient": pats, "Observation": obs, "Condition": conds}


def _write(nd: Path, res: dict[str, list[dict[str, Any]]]) -> Path:
    nd.mkdir()
    for t, rows in res.items():
        (nd / f"{t}.ndjson").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    from tb_common import id_rule

    id_rule.write_snapshot_record(nd)  # D-1253: a snapshot of this release says its id rule
    return nd


@pytest.fixture
def lake(tmp_path: Path) -> LakeLocal:
    Lake(tmp_path / "lake", ZONE).rebuild(S1, HashEmbedder(), _write(tmp_path / "nd1", _feed()))
    return LakeLocal(tmp_path / "lake", HashEmbedder(), ZONE)


def _doc(lake: LakeLocal, pid: str = P1, snapshot: str = S1) -> dict[str, Any]:
    return tw.assemble(pid, snapshot, tw.read_lake(lake, [pid], snapshot)[pid])


# --------------------------------------------------------------------------------------------- the assembler
def test_the_twin_validates_and_every_item_names_its_source(lake: LakeLocal) -> None:
    doc = _doc(lake)
    assert schema_errors(tw.SCHEMA_NAME, doc) == []
    assert doc["profile"] == "tb_patient_profile/1" and doc["basis"] == {"snapshot": S1, "mapping_versions": ["map@3"]}
    tl = doc["layers"]["timeline"]["items"]
    assert [i["kind"] for i in tl].count("observation") == 2 and [i["kind"] for i in tl].count("condition") == 3
    crea = next(i for i in tl if i["kind"] == "observation" and i["value"] == 1.1)
    assert crea["source"] == {"table": "lab_result", "row_hash": "h11", "lake_table": "observation",
                              "row": f"{P1}-o1", "date": crea["date"]}  # fmt: skip
    assert crea["date"].startswith("2026-10-06")
    assert all(i["source"]["row_hash"] and i["source"]["date"] for i in tl)
    assert [i["date"] for i in tl] == sorted(i["date"] for i in tl)  # the timeline in date order
    # the record layer cites the patient row
    rec = {i["field"]: i for i in doc["layers"]["record"]["items"]}
    assert rec["birth_date"]["value"] == "1971-01-01" and rec["sex"]["source"]["row_hash"] == "p1"
    # the phenotype: each problem code once, with first, last and every source
    ph = {i["code"]: i for i in doc["layers"]["phenotype"]["items"]}
    assert ph["M05.79"]["count"] == 2 and ph["M05.79"]["first"] == "2025-03-01" and ph["M05.79"]["last"] == "2026-02-01"
    assert [s["row_hash"] for s in ph["M05.79"]["sources"]] == ["d11", "d12"]
    # P2's rows never reach P1's twin
    assert all(P2 not in i["source"]["row"] for i in tl)


def test_layers_are_stamped_and_a_layer_not_built_is_null(lake: LakeLocal) -> None:
    layers = _doc(lake)["layers"]
    assert list(layers) == list(tw.LAYERS)  # every layer present, none left out
    for name, version in tw.BUILT.items():
        if name == "derived":
            assert layers[name] is None  # no derived store given: null, not omitted
        else:
            assert layers[name]["version"] == version
    for name in ("eligibility", "setpoint", "gap", "similarity"):
        assert layers[name] is None


def test_the_assembler_is_deterministic(lake: LakeLocal) -> None:
    a = tw.canonical(_doc(lake))
    b = tw.canonical(_doc(lake))
    assert a == b
    # the lake's row order does not matter: rows read in reverse give the same bytes
    tables = tw.read_lake(lake, [P1], S1)[P1]
    rev = {k: list(reversed(v)) for k, v in tables.items()}
    assert tw.canonical(tw.assemble(P1, S1, rev)) == a


def test_research_layers_are_absent_for_a_reader_without_the_row(lake: LakeLocal) -> None:
    doc = _doc(lake)
    plain = tw.for_role(doc, research=False)
    assert "setpoint" not in plain["layers"] and "gap" not in plain["layers"]
    assert plain["layers"]["similarity"] is None  # not built: null for everyone
    assert schema_errors(tw.SCHEMA_NAME, plain) == []
    assert set(tw.for_role(doc, research=True)["layers"]) == set(tw.LAYERS)
    assert "setpoint" in doc["layers"]  # the stored document is not changed


def test_no_free_text_enters_the_twin(tmp_path: Path) -> None:
    feed = _feed()
    feed["DocumentReference"] = [{"resourceType": "DocumentReference", "id": f"{P1}-n1", "status": "current",
                                  "subject": {"reference": f"Patient/{P1}"}, "date": "2026-10-06T10:00:00+09:00",
                                  "type": {"coding": [{"code": "progress"}]},
                                  "content": [{"attachment": {"contentType": "text/plain",
                                                              "data": "VGhlIHBhdGllbnQgU3l1bnRoZXRpYyBOYW1l"}}]}]  # fmt: skip
    Lake(tmp_path / "lake", ZONE).rebuild(S1, HashEmbedder(), _write(tmp_path / "nd", feed))
    lk = LakeLocal(tmp_path / "lake", HashEmbedder(), ZONE)
    doc = _doc(lk)
    notes = [i for i in doc["layers"]["timeline"]["items"] if i["kind"] == "document"]
    assert len(notes) == 1 and notes[0]["code"] == "progress"
    assert "Syunthetic" not in tw.canonical(doc).decode() and "text" not in notes[0]


# --------------------------------------------------------------------------------------------- the store and build
def test_build_keeps_versions_and_writes_nothing_when_nothing_changed(db_url: str, lake: LakeLocal) -> None:
    st = tw.ProfileStore(db_url)
    rep = tw.build(st, lake, [P1, P2, "TWINPID9999"], snapshot=S1, now=NOW)
    assert (rep.inserted, rep.unchanged, rep.missing, rep.failed) == (2, 0, 1, [])
    first = st.current(P1)
    assert first is not None and first.version == 1 and first.snapshot == S1
    assert tw.canonical(first.doc) == tw.canonical(_doc(lake))  # the stored bytes are the assembler's
    rep = tw.build(st, lake, [P1], snapshot=S1, now=NOW)
    assert (rep.inserted, rep.unchanged) == (0, 1)
    assert [h["version"] for h in st.history(P1)] == [1]


def test_a_confirmed_fact_is_in_the_twin_after_one_tick(db_url: str, tmp_path: Path, lake: LakeLocal) -> None:
    st = tw.ProfileStore(db_url)
    tw.build(st, lake, [P1], snapshot=S1, now=NOW)
    lk = Lake(tmp_path / "lake", ZONE)
    # a person confirms a CRP value; a second value read from a chart stays proposed
    lk.put_site({"Observation": [_obs(P1, 7, "crp", 2.5, "mg/dL", day="2026-11-01", basis="confirmed"),
                                 _obs(P1, 8, "crp", 9.9, "mg/dL", day="2026-11-02", basis="proposed")]})  # fmt: skip
    lk.rebuild(S2, HashEmbedder(), _write(tmp_path / "nd2", _feed()))
    rep = tw.build(st, lake, [P1], snapshot=S2, now=NOW)  # the tick: one build on the new snapshot
    assert rep.inserted == 1
    cur = st.current(P1)
    assert cur is not None and cur.version == 2 and cur.snapshot == S2
    values = [i["value"] for i in cur.doc["layers"]["timeline"]["items"] if i["kind"] == "observation"]
    assert 2.5 in values and 9.9 not in values  # a proposed fact never enters the twin
    hist = st.history(P1)
    assert [h["version"] for h in hist] == [1, 2] and hist[0]["superseded_at"] and hist[1]["superseded_at"] is None


def test_a_new_snapshot_with_the_same_content_moves_the_check_mark_only(db_url: str, tmp_path: Path,
                                                                         lake: LakeLocal) -> None:  # fmt: skip
    st = tw.ProfileStore(db_url)
    tw.build(st, lake, [P1], snapshot=S1, now=NOW)
    Lake(tmp_path / "lake", ZONE).rebuild(S2, HashEmbedder(), _write(tmp_path / "nd2", _feed()))
    assert tw.build(st, lake, [P1], snapshot=S2, now=NOW).unchanged == 1
    cur = st.current(P1)
    assert cur is not None and (cur.version, cur.snapshot, cur.checked_snapshot) == (1, S1, S2)


def test_an_opted_out_patient_has_no_twin(db_url: str, lake: LakeLocal) -> None:
    st = tw.ProfileStore(db_url)
    tw.build(st, lake, [P1, P2], snapshot=S1, now=NOW)
    assert st.current(P2) is not None
    reg = OptOutRegister(db_url)
    reg.add(P2, "paper", "", "console:office1", NOW)
    reg.close()
    rep = tw.build(st, lake, [P1, P2], snapshot=S1, now=NOW)
    assert rep.opted_out == 1 and rep.erased == 1
    assert st.current(P2) is None and st.history(P2) == []  # every version erased
    # never assembled again while opted out, even when only P1 is asked for and P2's rows were kept somewhere
    assert tw.build(st, lake, [P2], snapshot=S1, now=NOW).inserted == 0 and st.current(P2) is None
    assert st.current(P1) is not None


def test_the_erase_hook_for_the_opt_out_worker(db_url: str, lake: LakeLocal) -> None:
    st = tw.ProfileStore(db_url)
    tw.build(st, lake, [P1], snapshot=S1, now=NOW)
    assert st.erase(P1) == 1 and st.current(P1) is None and st.erase(P1) == 0


def test_the_derived_layer_cites_the_stored_rows_and_their_inputs(db_url: str, lake: LakeLocal) -> None:
    ds = DerivedStore(db_url)
    run_batch(ds, lake, mapping_version="map@3", snapshot=S1)
    st = tw.ProfileStore(db_url)
    tw.build(st, lake, [P1], snapshot=S1, now=NOW, derived=ds)
    cur = st.current(P1)
    assert cur is not None
    layer = cur.doc["layers"]["derived"]
    assert layer["version"] == "derived@1"
    egfr = [i for i in layer["items"] if i["score"].startswith("egfr")]
    assert egfr and all(i["source"]["table"] == "derived.score_row" for i in egfr)
    rows = {str(r["id"]): r for r in ds.rows(P1)}
    for i in egfr:
        assert i["value"] == rows[i["source"]["row"]]["value"]  # the stored value, never recomputed here
    crea = next(x for i in egfr for x in i["inputs"] if x["component"] == "creatinine")
    assert crea["row"] == f"{P1}-o1" and crea["row_hash"] == "h11"


def test_a_build_needs_a_named_snapshot(db_url: str, lake: LakeLocal) -> None:
    with pytest.raises(tw.TwinError):
        tw.build(tw.ProfileStore(db_url), lake, [P1], snapshot="", now=NOW)


class _OrchDb:
    def pool_rulesets(self) -> list[str]:
        return ["GZQO"]

    def candidate_summaries(self) -> list[dict[str, Any]]:
        return [{"ruleset": "OTHER"}]

    def pool(self, rid: str) -> list[dict[str, Any]]:
        return [{"pid": P1}] if rid == "GZQO" else []

    def candidates(self, rid: str) -> list[dict[str, Any]]:
        return [{"pid": P2}] if rid == "OTHER" else []


def test_the_night_step_builds_the_study_patients(db_url: str, lake: LakeLocal) -> None:
    assert tw.study_pids(_OrchDb()) == [P1, P2]
    rep = tw.after_ingest(_OrchDb(), lake, S1, NOW, db_url)
    assert rep is not None and rep.inserted == 2
    st = tw.ProfileStore(db_url)
    assert st.current(P1) is not None and st.current(P2) is not None


def test_the_night_step_never_raises(db_url: str) -> None:
    class Broken:
        def query(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("lake down")

    assert tw.after_ingest(_OrchDb(), Broken(), S1, NOW, db_url) is None
