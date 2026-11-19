"""Findings of the scenario-matrix run of 2026-11-09 (D-141), fixed in D-142's follow-up; each test failed before
its fix. The run's own probes are in ``tools/scenarios.py``; these are the small repros.

* XL-02: SCREEN on the hospital's own space after a site list was published spilled DuckDB temp files until the
  disk was full. The site's facts gave a second ``Patient`` for every pseudonym the feed already had, and each
  criterion of a compiled ruleset joins ``base`` (patients x index dates) again, so one duplicated patient became
  2^(criteria + 1) rows.
* FHIR-01: on the FHIR bulk path SCREEN had no one in scope: references to a Practitioner were hashed and the
  Practitioner's own id was kept, so no appointment found its doctor.
* MAP-01: a diagnosis name was matched by a shared character (胃癌 and 乳癌 to C22.0, 本態性高血圧症 to E78.5).
* DUMP-01: a diagnosis row with no date fell out of every window test, so "no malignancy" read as met and the
  patient as ready. An undated record now leaves the criterion unknown wherever the dated records do not settle it,
  on every input path (they all reach the lake's SQL).
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from lake.store import Lake, LakeLimitError
from tb_common.ruleset import Ruleset

ROOT = Path(__file__).resolve().parents[2]
SNAP = "2026-10-31"


def _ndjson(folder: Path, by_type: dict[str, list[dict[str, Any]]]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for rtype, items in by_type.items():
        (folder / f"{rtype}.ndjson").write_text("".join(json.dumps(r) + "\n" for r in items), "utf-8")
    from tb_common import id_rule

    id_rule.write_snapshot_record(folder)  # D-1253: a snapshot of this release says its id rule
    return folder


def _hospital(n: int) -> dict[str, list[dict[str, Any]]]:
    pts, cond, enc = [], [], []
    for i in range(n):
        pid = f"p{i:04d}"
        pts.append({"resourceType": "Patient", "id": pid, "birthDate": f"19{50 + i % 40}-03-01", "gender": "male"})
        cond.append(
            {
                "resourceType": "Condition",
                "id": f"c{i}",
                "subject": {"reference": f"Patient/{pid}"},
                "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "M10.9"}]},
                "onsetDateTime": "2025-06-01",
            }
        )
        enc.append(
            {
                "resourceType": "Encounter",
                "id": f"e{i}",
                "status": "finished",
                "subject": {"reference": f"Patient/{pid}"},
                "period": {"start": "2026-09-01T09:00:00+09:00"},
                "class": {"code": "AMB"},
            }
        )
    return {"Patient": pts, "Condition": cond, "Encounter": enc}


def _site(n: int) -> dict[str, list[dict[str, Any]]]:
    """What ``sitesetup.publish`` gives for a PI's sheet over the same patients: a Patient per pseudonym (one of them
    with another sex: a disagreement is unknown, never a guess) and the sheet's facts."""
    pts = [
        {"resourceType": "Patient", "id": f"p{i:04d}", "birthDate": f"19{50 + i % 40}-03-01"}
        | ({"gender": "female"} if i == 0 else {})
        for i in range(n)
    ]
    return {"Patient": pts}


def test_xl02_published_site_facts_never_duplicate_a_patient(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    n = 40
    lake = Lake(tmp_path / "lake", tz="Asia/Tokyo")
    lake.put_site(_site(n))
    lake.rebuild(SNAP, HashEmbedder(), ndjson_dir=_ndjson(tmp_path / "feed", _hospital(n)))
    con = lake.connect()
    try:
        rows = con.execute("SELECT pid, birth_date, sex FROM patient ORDER BY pid").fetchall()
    finally:
        con.close()
    assert len(rows) == n  # one row per pseudonym
    assert rows[0][2] is None and rows[1][2] == "male"  # feed and sheet disagree: unknown; agree: kept
    # the GZQO SCREEN query (twelve month ends, as the cascade asks) at a size that filled the disk before the fix:
    # it now returns one row per patient and index date, inside a small spill budget
    monkeypatch.setenv("TB_LAKE_MEMORY_LIMIT", "512MB")
    monkeypatch.setenv("TB_LAKE_MAX_TEMP", "256MB")
    rs = Ruleset.load(ROOT / "rulesets" / "GZQO")
    idx = [date(2025 + (m + 10) // 12, (m + 10) % 12 + 1, 1).isoformat() for m in range(12)]
    t = time.perf_counter()
    out = lake.query(rs.sql, [idx, None], timeout_s=120)
    assert out.num_rows == n * len(idx)
    assert time.perf_counter() - t < 60


def test_xl02_a_query_over_its_spill_budget_fails_with_a_clear_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lake = Lake(tmp_path / "lake", tz="Asia/Tokyo")
    lake.rebuild(SNAP, HashEmbedder(), ndjson_dir=_ndjson(tmp_path / "feed", _hospital(300)))
    monkeypatch.setenv("TB_LAKE_MEMORY_LIMIT", "64MB")
    monkeypatch.setenv("TB_LAKE_MAX_TEMP", "32MB")
    monkeypatch.setenv("TB_LAKE_TEMP_DIR", str(tmp_path / "spill"))
    sql = (
        "SELECT count(*) FROM (SELECT DISTINCT a.eid || b.eid || c.eid AS k FROM encounter a, encounter b, encounter c)"
    )
    with pytest.raises(LakeLimitError) as e:
        lake.query(sql, timeout_s=120)
    assert str(e.value).startswith("LAKE-LIMIT:") and "TB_LAKE_MAX_TEMP" in str(e.value)
    assert (tmp_path / "spill").is_dir()  # the spill went where the configuration says
    assert not any(p.is_file() for p in (tmp_path / "spill").rglob("*"))  # and nothing was left behind


def test_fhir01_bulk_pseudonyms_map_ids_and_references_the_same_way() -> None:
    from adapter.pipeline import pseudonymise_bulk
    from lake.flatten import Flattener
    from tb_common.crypto import pid_for_mrn

    key = b"k" * 32
    export: list[dict[str, Any]] = [
        {"resourceType": "Practitioner", "id": "D001", "name": [{"text": "Dr A"}]},
        {"resourceType": "Patient", "id": "00012345", "name": [{"text": "X"}], "identifier": [{"value": "00012345"}]},
        {
            "resourceType": "Appointment",
            "id": "A1",
            "status": "booked",
            "start": "2026-11-12T09:00:00+09:00",
            "participant": [
                {"actor": {"reference": "Patient/00012345"}},
                {"actor": {"reference": "Practitioner/D001"}},
            ],
        },
        {
            "resourceType": "Encounter",
            "id": "E1",
            "subject": {"reference": "Patient/00012345"},
            "participant": [{"individual": {"reference": "Practitioner/D001"}}],
            "period": {"start": "2026-10-01T09:00:00+09:00"},
        },
    ]
    by: dict[str, list[dict[str, Any]]] = {}
    for r in pseudonymise_bulk(iter(export), key):
        by.setdefault(r["resourceType"], []).append(r)
    rows = Flattener("Asia/Tokyo").flatten(by)
    staff = {r["practitioner_id"] for r in rows["practitioner"]}
    assert staff == {"D001"}  # the hospital's staff id, as the CSV and SS-MIX2 paths key it (the study scope's ids)
    assert [r["practitioner_id"] for r in rows["appointment"]] == ["D001"]
    assert [r["practitioner_id"] for r in rows["encounter"]] == ["D001"]
    pid = pid_for_mrn(key, "00012345")
    assert [r["pid"] for r in rows["patient"]] == [pid] == [r["pid"] for r in rows["appointment"]]
    assert "00012345" not in json.dumps(by)  # the chart number is gone from ids, references and identifiers


# common diagnosis names as a hospital writes them, with the ICD-10-CM code a coordinator would map them to
DX_NAMES = [
    ("胃癌", "C16.9"),
    ("胃がん", "C16.9"),
    ("乳癌", "C50.919"),
    ("乳がん", "C50.919"),
    ("肺癌", "C34.90"),
    ("大腸癌", "C18.9"),
    ("肝細胞癌", "C22.0"),
    ("膵臓癌", "C25.9"),
    ("前立腺癌", "C61"),
    ("本態性高血圧症", "I10"),
    ("高血圧症", "I10"),
    ("２型糖尿病", "E11.9"),  # full width, as Excel often has it
    ("脂質異常症", "E78.5"),
    ("痛風", "M10.9"),
    ("関節リウマチ", "M06.9"),
    ("心不全", "I50.9"),
    ("脳梗塞", "I63.9"),
    ("慢性腎臓病", "N18.9"),
    ("胰臟癌", "C25.9"),
    ("攝護腺癌", "C61"),
    ("原發性高血壓", "I10"),
    ("高血壓", "I10"),
    ("第二型糖尿病", "E11.9"),
    ("高血脂症", "E78.5"),
    ("類風濕性關節炎", "M06.9"),
    ("心衰竭", "I50.9"),
    ("腦梗塞", "I63.9"),
    ("胃惡性腫瘤", "C16.9"),  # an ICD-10 title in Chinese
    ("Essential (primary) hypertension", "I10"),  # an ICD-10 title in English
]


@pytest.mark.parametrize(("name", "code"), DX_NAMES)
def test_map01_a_diagnosis_name_suggests_its_own_code(name: str, code: str) -> None:
    from sitesetup import mapping

    got = mapping.suggest("condition", mapping.local_system("dx-text"), name, name)
    assert got.get("code") == code, (name, got)
    assert float(got["confidence"]) >= mapping.MIN_CONFIDENCE and got["method"] in ("term", "title")


@pytest.mark.parametrize("name", ["癌", "高血", "肝臓病", "謎の病気", "術後", "胃部不快感", "hyper"])
def test_map01_no_suggestion_when_unsure(name: str) -> None:
    """A piece of a name (a shared character, a substring) is never a match: nothing is suggested."""
    from sitesetup import mapping

    assert mapping.suggest("condition", mapping.local_system("dx-text"), name, name) == {}


def test_map01_the_dump_codes_of_the_scenario_run() -> None:
    """The scenario's IT dump: a local code with only a name. 胃癌 and 乳癌 were suggested C22.0 (liver) and
    本態性高血圧症 E78.5 (hyperlipidaemia)."""
    from sitesetup import mapping

    for local, name, code in (("ZC16", "胃癌", "C16"), ("ZC50", "乳癌", "C50"), ("ZI10", "本態性高血圧症", "I10")):
        got = mapping.suggest("condition", mapping.local_system("dx-code"), local, name)
        assert got["code"].split(".")[0] == code, (name, got)


def test_map01_every_listed_name_has_a_real_code() -> None:
    import csv

    import pyarrow.parquet as pq

    full = {r["code"] for r in pq.read_table(ROOT / "services/criteria_compiler/terminology/icd10cm_full.parquet")
            .select(["code"]).to_pylist()}  # fmt: skip
    with (ROOT / "services/sitesetup/dx_names.csv").open(encoding="utf-8") as fh:
        bad = [r for r in csv.DictReader(fh) if r["icd10"] not in full]
    assert bad == []


ICD = "http://hl7.org/fhir/sid/icd-10-cm"
KEY = b"k" * 32
IDX = date(2026, 11, 10)


def _undated_cancer_by_path(tmp: Path) -> dict[str, list[dict[str, Any]]]:
    """One patient per input path whose only cancer row has no date, each with dated gout; Condition resources as
    each path writes them. Returns resources by type for the lake."""
    from adapter.mapping.engine import Mapper, Mapping
    from adapter.pipeline import pseudonymise_bulk
    from adapter.sources.ssmix2.source import Ssmix2Source, storage_dir
    from sitesetup import publish
    from tb_common.crypto import pid_for_mrn

    out: dict[str, list[dict[str, Any]]] = {"Patient": [], "Condition": []}
    maps = ROOT / "services/adapter/mapping"

    def patient(pid: str) -> None:
        out["Patient"].append({"resourceType": "Patient", "id": pid, "birthDate": "1960-01-01", "gender": "male"})

    def gout(pid: str, cid: str) -> dict[str, Any]:
        return {"resourceType": "Condition", "id": cid, "subject": {"reference": f"Patient/{pid}"},
                "code": {"coding": [{"system": ICD, "code": "M10.9"}]}, "onsetDateTime": "2026-06-01"}  # fmt: skip

    # 1 the hospital's CSV feed (tw_core mapping): diag_date empty
    m = Mapping.load(maps / "tw_core/demo_his.yaml")
    spec = next(r for r in m.resources if r.type == "Condition")
    row = {"diag_no": "1", "mrn": "CSV1", "icd10": "C16.9", "diag_date": "", "status": "A"}
    csv_res = Mapper(m, KEY, "S").map_row(spec, row)
    assert csv_res is not None  # an undated row is kept, never dropped
    out["Condition"].append(csv_res)
    # 2 SS-MIX2 storage: a PRB with no action, onset or record date
    root = tmp / "ss"
    d = storage_dir(root, "10000099", "20260101", "PPR-01")
    d.mkdir(parents=True)
    msg = (  # every SS-MIX2 message carries its patient (PR #1095 fourth review b)
        "MSH|^~\\&|HIS||TB||20261101||PPR^ZD1|O1|P|2.5||||||~ISO IR87\rPID|||10000099^^^^PI\rPV1||O\r"
        "PRB|AD||C169^胃癌^99XYZ^C169^胃癌^I10|D1\r"
    )
    (d / "10000099_20260101_PPR-01_O1_20261101000000000_-_1").write_bytes(msg.encode("iso2022_jp"))
    rows = list(Ssmix2Source(root, licensed={"medis": {}, "jlac10": {}, "yj": {}}).rows("diagnosis", "diagnosis",
                                                                                       None, None))  # fmt: skip
    m = Mapping.load(maps / "jp_core/ssmix2_site.yaml")
    spec = next(r for r in m.resources if r.type == "Condition")
    ss = [Mapper(m, KEY, "S").map_row(spec, m.normalize("diagnosis", r)) for r in rows]
    out["Condition"] += [r for r in ss if r is not None]
    assert len(ss) == 1 == len(out["Condition"]) - 1
    # 3 a FHIR bulk export: a Condition with no onset or recorded date
    bulk = [{"resourceType": "Condition", "id": "F1", "subject": {"reference": "Patient/FH1"},
             "code": {"coding": [{"system": ICD, "code": "C50.919"}]}}]  # fmt: skip
    out["Condition"] += list(pseudonymise_bulk(iter(bulk), KEY))
    # 4 the site's own inputs (an IT dump, a PI's sheet, a confirmed chart fact): a fact with no day
    fact = {"id": 1, "pid": pid_for_mrn(KEY, "DU1"), "status": "coded", "day": "", "domain": "condition",
            "term": "胃癌", "code": "C16.9", "system": ICD, "local_code": "", "local_system": "", "value": "",
            "unit": ""}  # fmt: skip
    out["Condition"] += publish.resources([fact], {}, [])["Condition"]
    for mrn in ("CSV1", "10000099", "FH1", "DU1"):
        pid = pid_for_mrn(KEY, mrn)
        patient(pid)
        out["Condition"].append(gout(pid, f"g-{mrn}"))
    # controls: dated cancer (excluded), no cancer (clear)
    for pid, cancer in (("P-DATED", "2025-01-10"), ("P-CLEAR", None)):
        patient(pid)
        out["Condition"].append(gout(pid, f"g-{pid}"))
        if cancer:
            out["Condition"].append({"resourceType": "Condition", "id": f"c-{pid}", "subject": {"reference": f"Patient/{pid}"},
                                     "code": {"coding": [{"system": ICD, "code": "C16.9"}]}, "onsetDateTime": cancer})  # fmt: skip
    return out


def test_dump01_an_undated_diagnosis_is_unknown_on_every_input_path(tmp_path: Path) -> None:
    from criteria_compiler.compile_sql.generator import SqlGenerator
    from criteria_compiler.terminology.mapper import Terminology, ValueSets, valueset
    from lake.client import LakeLocal
    from orchestrator.scenarios.evaluate import SqlEngine
    from tb_common.crypto import pid_for_mrn
    from tb_contracts import CriterionIR

    by = _undated_cancer_by_path(tmp_path)
    for c in by["Condition"]:
        assert (c is not None and not c.get("onsetDateTime") and not c.get("recordedDate")) or c["id"].startswith(
            ("g-", "c-")
        ), c
    _ndjson(tmp_path / "feed", by)
    Lake(tmp_path / "lake", tz="Asia/Tokyo").rebuild("2026-11-09", HashEmbedder(), ndjson_dir=tmp_path / "feed")

    def crit(cid: str, kind: str, vs: str, quant: str = "any", window: dict[str, Any] | None = None) -> Any:
        logic: dict[str, Any] = {"domain": "condition", "quantifier": quant, "valueset": vs}
        if window:
            logic["window"] = window
        return CriterionIR.model_validate(
            {"id": cid, "ruleset": "UND", "kind": kind, "class": "structured", "text": cid, "logic": logic}
        )

    cs = [
        crit("UND-INC-01", "inclusion", "VS_GOUT"),
        crit("UND-EXC-01", "exclusion", "VS_MALIGNANCY"),  # any time
        crit("UND-EXC-02", "exclusion", "VS_MALIGNANCY", window={"anchor": "index", "from_days": -365, "to_days": 0}),
        crit("UND-INC-02", "inclusion", "VS_MALIGNANCY", quant="none"),  # "no malignancy" written as an inclusion
    ]
    term = Terminology()
    vs = {}
    for name, concept in (("VS_GOUT", "gout"), ("VS_MALIGNANCY", "malignancy")):
        res = term.map("condition", concept)
        vs[name] = valueset("UND", name, concept, res.concepts, "1.0.0", families=res.families)
    sql = SqlGenerator("UND", "1.0.0", ValueSets("UND", vs, term)).render(cs)
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    rs = Ruleset(manifest=base.model_copy(update={"id": "UND", "library": None, "criteria": [c.id for c in cs]}),
                 criteria=cs, valuesets=vs, sql=sql)  # fmt: skip
    paths = {
        p: pid_for_mrn(KEY, m) for p, m in (("csv", "CSV1"), ("ssmix2", "10000099"), ("fhir", "FH1"), ("site", "DU1"))
    }
    pids = [*paths.values(), "P-DATED", "P-CLEAR"]
    ev = SqlEngine(LakeLocal(tmp_path / "lake", HashEmbedder())).evaluate(rs, pids, IDX, [c.id for c in cs])
    got = {pid: {c: ev[pid].results.get(c) for c in ("UND-INC-01", "UND-EXC-01", "UND-EXC-02", "UND-INC-02")}
           for pid in pids}  # fmt: skip
    for path, pid in paths.items():
        assert got[pid] == {"UND-INC-01": True, "UND-EXC-01": None, "UND-EXC-02": None, "UND-INC-02": None}, path
    assert got["P-DATED"] == {"UND-INC-01": True, "UND-EXC-01": True, "UND-EXC-02": False, "UND-INC-02": False}
    assert got["P-CLEAR"] == {"UND-INC-01": True, "UND-EXC-01": False, "UND-EXC-02": False, "UND-INC-02": True}
