"""疑い (suspected) diagnoses never exclude (D-142; review 02 "suspected" item, P-04, S10).

SS-MIX2 carries the suspected flag in PPR-01 PRB-13 (SS-MIX2 標準化ストレージ仕様書 v1.2h 表 3-47: 「JHSD 表 0005-疑い病名
フラグ」, coding system JHSD0005, code ``1`` 疑いあり). The reader keeps it as ``suspected``; the mapping writes FHIR
``Condition.verificationStatus = provisional``; the lake lists a provisional (or differential) diagnosis in
``site_fact`` with basis ``suspected`` and keeps it out of ``condition``. A criterion such a diagnosis could change is
unknown with the reason ``suspected_diagnosis``: "肺癌の疑い" never excludes for "history of malignancy" and never
counts as the index diagnosis. Both runtime engines (the SQL engine of NAV / MICROBATCH / CASE and the SCREEN
cascade) apply it. A FHIR source's own provisional / differential diagnoses take the same path.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from adapter.mapping.engine import Mapper, Mapping
from adapter.sources.ssmix2.source import Ssmix2Source, storage_dir
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import Concept, Terminology, ValueSets, valueset
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.flatten import Flattener
from lake.store import Lake
from matching.cascade.engine import CascadeConfig, run_cascade
from orchestrator.scenarios.evaluate import SqlEngine, structured_verdict
from orchestrator.scenarios.screen_cascade import verdicts_of
from tb_common.reasons import LABELS
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR

ROOT = Path(__file__).resolve().parents[2]
TW_MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
ICD = "http://hl7.org/fhir/sid/icd-10-cm"
VER = "http://terminology.hl7.org/CodeSystem/condition-ver-status"
IDX = date(2026, 10, 5)
EMPTY: dict[str, dict[str, dict[str, str]]] = {"medis": {}, "jlac10": {}, "yj": {}}


def _storage(root: Path, patient: str, order: str, segs: list[str]) -> None:
    msh = f"MSH|^~\\&|HIS||TB||20261101||PPR^ZD1|{order}|P|2.5||||||~ISO IR87"
    d = storage_dir(root, patient, "20260101", "PPR-01")
    d.mkdir(parents=True, exist_ok=True)
    text = "\r".join([msh, *segs]) + "\r"
    (d / f"{patient}_20260101_PPR-01_{order}_20261101000000000_-_1").write_bytes(text.encode("iso2022_jp"))


def test_ssmix2_reader_reads_the_prb13_flag_and_the_name_modifier(tmp_path: Path) -> None:
    # PRB-10 carries the ICD-10 in the spec's example; this reader takes it from PRB-3's alternate coding
    flagged = "PRB|AD|20260101|C349^肺癌^99XYZ^C349^肺癌^I10|D1|||||||||1^疑いあり^JHSD0005|A||20260101"
    named = "PRB|AD|20260101|C509^乳癌の疑い^99XYZ^C509^乳癌^I10|D2||||||||||||20260101"
    plain = "PRB|AD|20260101|M109^痛風^99XYZ^M109^痛風^I10|D3||||||||||||20260101"
    unflagged = "PRB|AD|20260101|C189^大腸癌^99XYZ^C189^大腸癌^I10|D4|||||||||0^疑いなし^JHSD0005|||20260101"
    for n, prb in enumerate((flagged, named, plain, unflagged), start=1):
        _storage(tmp_path, "10000001", f"D{n}", ["PV1||O", prb])
    rows = list(Ssmix2Source(tmp_path, licensed=EMPTY).rows("diagnosis", "diagnosis", None, None))
    got = {r["diag_no"]: r["suspected"] for r in rows}
    assert got == {"D1": "Y", "D2": "Y", "D3": "", "D4": ""}


def test_mapping_writes_provisional_only_for_a_suspected_diagnosis() -> None:
    m = Mapping.load(TW_MAPPING)
    mp = Mapper(m, b"k" * 32, "S")
    spec = next(r for r in m.resources if r.type == "Condition")
    row = {"diag_no": "1", "mrn": "M1", "icd10": "C34.9", "diag_date": "2026-01-01", "status": "A"}
    sus = mp.map_row(spec, {**row, "suspected": "Y"})
    assert sus is not None and sus["verificationStatus"]["coding"] == [{"system": VER, "code": "provisional"}]
    plain = mp.map_row(spec, row)
    assert plain is not None and "verificationStatus" not in plain


def _cond(pid: str, cid: str, code: str, status: str | None) -> dict[str, Any]:
    c: dict[str, Any] = {
        "resourceType": "Condition",
        "id": cid,
        "subject": {"reference": f"Patient/{pid}"},
        "code": {"coding": [{"system": ICD, "code": code}]},
        "onsetDateTime": "2026-01-10",
    }
    if status:
        c["verificationStatus"] = {"coding": [{"system": VER, "code": status}]}
    return c


CONDITIONS = [
    _cond("P-CONF", "c1", "C34.9", None),  # confirmed lung cancer: excluded
    _cond("P-SUSP", "c2", "C34.9", "provisional"),  # 肺癌の疑い: never excluded
    _cond("P-DIFF", "c3", "C50.9", "differential"),  # a differential diagnosis: the same
    _cond("P-REFUTED", "c4", "C34.9", "refuted"),  # ruled out: not a diagnosis at all
    _cond("P-SUSP-GOUT", "c5", "M10.9", "provisional"),  # suspected gout: not the index diagnosis either
    _cond("P-GOUT", "c6", "M10.9", "confirmed"),
    # everyone but P-SUSP-GOUT and P-NONE has the index diagnosis, so only the exclusion decides
    *[_cond(p, f"g-{p}", "M10.9", None) for p in ("P-CONF", "P-SUSP", "P-DIFF", "P-REFUTED")],
]
PIDS = ["P-CONF", "P-SUSP", "P-DIFF", "P-REFUTED", "P-SUSP-GOUT", "P-GOUT", "P-NONE"]


def test_flatten_keeps_suspected_diagnoses_out_of_the_coded_table() -> None:
    out = Flattener("Asia/Tokyo").flatten({"Condition": CONDITIONS})
    assert sorted(r["cid"] for r in out["condition"] if not r["cid"].startswith("g-")) == ["c1", "c6"]
    assert sorted((r["fid"], r["basis"]) for r in out["site_fact"]) == [
        ("c2", "suspected"),
        ("c3", "suspected"),
        ("c5", "suspected"),
    ]


def _crit(cid: str, kind: str, vs: str) -> CriterionIR:
    return CriterionIR.model_validate(
        {
            "id": cid,
            "ruleset": "SUSP",
            "kind": kind,
            "class": "structured",
            "text": cid,
            "logic": {
                "domain": "condition",
                "quantifier": "any",
                "valueset": vs,
                "window": {"anchor": "index", "from_days": None, "to_days": 0},
            },
        }
    )


@pytest.fixture(scope="module")
def setup(tmp_path_factory: pytest.TempPathFactory) -> tuple[LakeLocal, Ruleset]:
    tmp = tmp_path_factory.mktemp("suspected")
    nd = tmp / "ndjson"
    nd.mkdir()
    pats = [{"resourceType": "Patient", "id": p, "birthDate": "1960-01-01", "gender": "male"} for p in PIDS]
    (nd / "Patient.ndjson").write_text("\n".join(json.dumps(p) for p in pats) + "\n", encoding="utf-8")
    (nd / "Condition.ndjson").write_text("\n".join(json.dumps(c) for c in CONDITIONS) + "\n", encoding="utf-8")
    (nd / "Observation.ndjson").write_text("", encoding="utf-8")
    Lake(tmp / "lake").rebuild("2026-10-05", HashEmbedder(), nd)
    crit = [_crit("SUSP-INC-01", "inclusion", "VS_GOUT"), _crit("SUSP-EXC-01", "exclusion", "VS_MALIG")]
    vs = {
        "VS_GOUT": valueset("SUSP", "VS_GOUT", "gout", [Concept(ICD, "M10.9", "gout")], "1.0.0"),
        "VS_MALIG": valueset(
            "SUSP", "VS_MALIG", "malignancy", [Concept(ICD, "C34.9", "lung"), Concept(ICD, "C50.9", "breast")], "1.0.0"
        ),
    }
    sql = SqlGenerator("SUSP", "1.0.0", ValueSets("SUSP", vs, Terminology())).render(crit)
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    manifest = base.model_copy(update={"id": "SUSP", "library": None, "criteria": [c.id for c in crit]})
    return LakeLocal(tmp / "lake", HashEmbedder()), Ruleset(manifest=manifest, criteria=crit, valuesets=vs, sql=sql)


def test_sql_engine_never_excludes_on_a_suspected_diagnosis(setup: tuple[LakeLocal, Ruleset]) -> None:
    lake, rs = setup
    inc, exc = rs.criteria
    ev = SqlEngine(lake).evaluate(rs, PIDS, IDX, [inc.id, exc.id])
    v = {pid: (structured_verdict(inc, e), structured_verdict(exc, e)) for pid, e in ev.items()}
    assert v["P-CONF"][1].verdict == "fail"  # a confirmed malignancy still excludes
    for pid in ("P-SUSP", "P-DIFF"):
        assert v[pid][1].verdict == "unknown", pid
        evidence = v[pid][1].evidence
        assert evidence is not None and evidence.reason == "suspected_diagnosis"
    assert v["P-REFUTED"][1].verdict == "pass"
    assert v["P-SUSP-GOUT"][0].verdict == "unknown" and v["P-GOUT"][0].verdict == "pass"
    assert v["P-NONE"][0].verdict == "fail"  # nothing at all: the coded answer stands


def test_cascade_lists_a_suspected_diagnosis_as_needing_information(setup: tuple[LakeLocal, Ruleset]) -> None:
    lake, rs = setup
    cfg = CascadeConfig(
        study_id="SUSP",
        run_date=IDX,
        lookback_months=36,
        index_mode="single",
        purpose="screening",
        step_id="s",
        snapshot=None,
        population=PIDS,
        note_block=False,
        absence_semantics=False,
    )
    res = run_cascade(lake, rs, cfg, judge=None, embedder=HashEmbedder(), reviewer=None)
    tiers = {pid: verdicts_of(rs, res.traces[pid]).tier for pid in PIDS}
    assert tiers["P-CONF"] == "excluded" and tiers["P-NONE"] == "excluded"
    for pid in ("P-SUSP", "P-DIFF", "P-SUSP-GOUT"):
        assert tiers[pid] == "review", (pid, tiers[pid])
    o = res.traces["P-SUSP"].outcomes["SUSP-EXC-01"]
    assert o.status == "pass" and o.reason == "suspected_diagnosis" and not o.hard
    words = LABELS["suspected_diagnosis"]
    assert set(words) == {"en", "ja", "zh-TW"} and "疑い" in words["ja"]
