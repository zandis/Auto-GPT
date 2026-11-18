"""TB-PLAN-04 step 7, Japan completeness (D-137).

* the licensed-file loader on the three synthetic 10-row samples (``tests/fixtures/licensed``: made-up rows in the
  vendors' column layouts; no licensed data is in the repo), the terminology store, the "not loaded" status, and
  D-130 with and without the lists;
* the SS-MIX2 messages ADT-52, OMP-11/12, HOT codes and extended-storage documents;
* JP Core ``$validate``: the synthetic SS-MIX2 hospital passes on the sample, and the check bites on each kind of
  fault (a TW Core claim, cardinality, slices, fixed and pattern values, the code systems we hold).
"""

from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from adapter import licensed
from adapter.sources.ssmix2 import hl7
from adapter.sources.ssmix2.source import Ssmix2Source, drug_codes, storage_dir
from adapter.validate import jpcore

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "tests" / "fixtures" / "licensed"
JP_MAPPING = ROOT / "services/adapter/mapping/jp_core/ssmix2_site.yaml"
TW_MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
FILES = {"medis": "medis_byomei_sample.txt", "jlac10": "jlac10_sample.tsv", "yj": "yj_hot_sample.txt"}
EMPTY: dict[str, dict[str, dict[str, str]]] = {"medis": {}, "jlac10": {}, "yj": {}}


def _load_all(store: licensed.TermStore, audit: Path | None = None) -> dict[str, dict[str, Any]]:
    return {
        k: store.load(k, (SAMPLES / f).read_bytes(), version="2026-sample", source=f, by="admin", audit_dir=audit)
        for k, f in FILES.items()
    }


# ---------------------------------------------------------------------------------------------- licensed files
def test_licensed_loader_reads_the_three_10_row_samples(tmp_path: Path) -> None:
    st = licensed.TermStore()
    try:
        assert {s["kind"]: s["state"] for s in st.status()} == dict.fromkeys(FILES, "not_loaded")
        out = _load_all(st, tmp_path / "audit")
        assert {k: (v["rows"], v["encoding"], v["delimiter"]) for k, v in out.items()} == {
            "medis": (10, "cp932", "comma"),
            "jlac10": (10, "utf-8", "tab"),
            "yj": (10, "cp932", "comma"),
        }
        assert all(not v["skipped"] for v in out.values())
        status = {s["kind"]: s for s in st.status()}
        assert all(
            s["state"] == "loaded" and s["version"] == "2026-sample" and s["rows"] == 10 for s in status.values()
        )
        assert status["medis"]["source"] == "medis_byomei_sample.txt"
        medis = st.concepts("medis")
        assert medis["ZB26"]["target_code"] == "M10.9" and medis["ZB26"]["display"] == "痛風"
        assert medis["ZB26"]["target_system"] == licensed.ICD10_WHO
        assert json.loads(medis["ZB26"]["extra"])["kana"] == "ツウフウ"
        jlac = st.concepts("jlac10")  # five part columns make the 17-character code
        assert jlac["3C020000002327101"]["display"] == "尿酸"
        assert json.loads(jlac["3C020000002327101"]["extra"])["material"] == "血清"
        yj = st.concepts("yj")  # full-width headers of the HOT master are matched after NFKC
        assert "アロプリノール" in yj["3943001F1020"]["display"]
        assert json.loads(yj["3943001F1020"]["extra"])["hot13"].startswith("99")
        # a new release replaces the old one; the old one stays in the store, inactive
        st.load("medis", (SAMPLES / FILES["medis"]).read_bytes(), version="2026-11", source="x.txt", by="admin")
        assert [(r["version"], r["active"]) for r in st.releases("medis")] == [
            ("2026-sample", False),
            ("2026-11", True),
        ]
    finally:
        st.close()
    events = [json.loads(x) for f in (tmp_path / "audit").glob("*.jsonl") for x in f.read_text().splitlines()]
    loads = [e for e in events if e["event"] == "terminology.load"]
    assert len(loads) == 3 and loads[0]["actor"] == "admin" and loads[0]["detail"]["rows"] == 10


def test_licensed_loader_refuses_and_lists_plainly() -> None:
    with pytest.raises(licensed.LicensedError) as e:
        licensed.parse("medis", "名前,番号\n痛風,1\n".encode())
    assert e.value.code == "LIC-COLUMNS" and "--columns" in e.value.message
    with pytest.raises(licensed.LicensedError) as e:
        licensed.parse("medis", b"code\n\x81 bad")
    assert e.value.code == "LIC-ENCODING"
    # a release without a header row is read with the columns given in file order
    body = "0,90000026,痛風,ツウフウ,ZB26,M10.9\n0,90000099,誤り,アヤマリ,TOOLONG,M10.9\n0,90000026,痛風,ツウフウ,ZB26,M10.9\n"
    p = licensed.parse(
        "medis",
        body.encode("cp932"),
        ["変更区分", "病名管理番号", "病名表記", "病名表記カナ", "病名交換用コード", "ICD10-2013"],
    )
    assert [c["code"] for c in p.concepts] == ["ZB26"]
    assert [why for _, why in p.skipped] == [
        "code 'TOOLONG' is not a MEDIS 標準病名マスター code",
        "code ZB26 appears twice; the first row is kept",
    ]
    with pytest.raises(licensed.LicensedError, match="LIC-KIND"):
        licensed.parse("icd", b"x")


def test_without_the_files_the_box_says_not_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    assert {s["state"] for s in licensed.status()} == {"not_loaded"}
    monkeypatch.setenv("TB_DB_URL", "")
    assert {s.get("store") for s in licensed.status(None)} == {"unavailable"}
    assert licensed.tables() == EMPTY


def _storage(
    root: Path,
    patient: str,
    day: str,
    typ: str,
    order: str,
    segs: list[str],
    stamp: str = "20261101000000000",
    flag: str = "1",
    charset: str = "~ISO IR87",
) -> None:
    msh = f"MSH|^~\\&|HIS||TB||20261101||X|{order}|P|2.5||||||{charset}"
    d = storage_dir(root, patient, day, typ)
    d.mkdir(parents=True, exist_ok=True)
    text = "\r".join([msh, *segs]) + "\r"
    data = text.encode("iso2022_jp" if "IR87" in charset else "utf-8")
    (d / f"{patient}_{day}_{typ}_{order}_{stamp}_-_{flag}").write_bytes(data)


def test_d130_unloaded_codes_stay_unknown_and_loaded_ones_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """標準病名 codes without an ICD-10 alternate: with no lookup and no licensed list they resolve nowhere (D-130
    keeps them unknown; the code itself reaches the mapping); a loaded MEDIS release resolves its codes to their WHO
    ICD-10 target, kept even when ICD-10-CM has no such code (D-314), and given as ICD-10-CM only where it has."""
    from adapter.sources.ssmix2 import source as ss

    empty = tmp_path / "no-lookups"
    empty.mkdir()
    monkeypatch.setattr(ss, "JP_CORE", empty)
    root = tmp_path / "ss"
    for n, code in enumerate(("ZB26", "ZB27", "ZB99")):
        prb = f"PRB|AD|20260101|{code}^病名^99XYZ|D{n}||||||||||A||20260101"
        _storage(root, "10000001", "20260101", "PPR-01", f"D{n}", ["PV1||O", prb])
    rows = list(Ssmix2Source(root, licensed=EMPTY).rows("diagnosis", "diagnosis", None, None))
    assert [(r["byomei_code"], r["icd10"]) for r in rows] == [("ZB26", ""), ("ZB27", ""), ("ZB99", "")]
    st = licensed.TermStore()
    try:
        _load_all(st)
        st.db.execute("UPDATE concept SET target_code = 'e149' WHERE code = 'ZB30'")  # WHO-only, written loosely
    finally:
        st.close()
    _storage(root, "10000001", "20260101", "PPR-01", "D9", ["PV1||O", "PRB|AD|20260101|ZB30^骨粗鬆症^99XYZ|D9"])
    src = Ssmix2Source(root)  # reads the store (TB_DB_URL)
    rows = list(src.rows("diagnosis", "diagnosis", None, None))
    got = {r["byomei_code"]: (r["icd10"], r["icd10cm"]) for r in rows}
    assert got == {"ZB26": ("M10.9", "M10.9"), "ZB27": ("", ""), "ZB99": ("", ""), "ZB30": ("E14.9", "")}
    assert src.missed == {"diagnosis:ZB27": 1, "diagnosis:ZB99": 1}
    assert src.stats["diagnosis:licensed"] == 2 and src.stats["diagnosis:licensed WHO-only code"] == 1


def test_site_setup_suggestions_use_the_licensed_lists() -> None:
    from sitesetup import mapping

    licensed._CACHE.clear()
    before = mapping.suggest("condition", mapping.local_system("dx-code"), "ZB26")
    assert before["method"] == "lookup"  # the shipped sample table
    st = licensed.TermStore()
    try:
        _load_all(st)
    finally:
        st.close()
    dx = mapping.suggest("condition", mapping.local_system("dx-code"), "ZB26")
    assert (dx["code"], dx["method"], dx["display"]) == ("M10.9", "licensed", "痛風")
    drug = mapping.suggest("medication", mapping.local_system("drug-code"), "3943001F1020")
    assert (drug["code"], drug["method"]) == ("M04AA01", "licensed")  # from the name the YJ file gives
    lab = mapping.suggest("observation", mapping.local_system("lab-code"), "3C020000002327101")
    assert (lab["code"], lab["method"]) == ("3084-1", "licensed")  # 尿酸 -> urate
    assert mapping.suggest("condition", mapping.local_system("dx-code"), "ZZ99") == {}


# ---------------------------------------------------------------------------------------------- HL7 messages
def test_adt52_discharge_and_patient_class_change(tmp_path: Path) -> None:
    root = tmp_path / "ss"
    pv1 = ["PV1", "", "I"] + [""] * 44
    pv1[19], pv1[44] = "E1", "202606140830"
    _storage(root, "10000001", "20260614", "ADT-22", "E1", ["|".join(pv1)])
    pv1b = list(pv1)
    pv1b[19] = "E2"
    _storage(root, "10000001", "20260614", "ADT-22", "E2", ["|".join(pv1b)])
    pv1c = list(pv1b)
    pv1c[19] = "E3"
    _storage(root, "10000001", "20260614", "ADT-22", "E3", ["|".join(pv1c)])
    # E1: discharged (A03, PV1-45); E2: changed to outpatient (A07); a change for a visit the storage lacks
    done = list(pv1)
    done[45] = "202606200900"
    for order, trigger, seg, when in (
        ("E1", "ADT^A03", done, "202606200900"),
        ("E2", "ADT^A07", [*pv1b[:2], "O", *pv1b[3:]], "202606141030"),
        ("E9", "ADT^A07", [*pv1b[:19], "E9", *pv1b[20:]], "202606141030"),
    ):
        d = storage_dir(root, "10000001", "20260614", "ADT-52")
        d.mkdir(parents=True, exist_ok=True)
        msh = f"MSH|^~\\&|HIS||TB||{when}||{trigger}|{order}|P|2.5||||||~ISO IR87"
        body = "\r".join([msh, f"EVN||{when}||||{when}", "|".join(seg)]) + "\r"
        (d / f"10000001_20260614_ADT-52_{order}_20261101000000000_-_1").write_bytes(body.encode("iso2022_jp"))
    src = Ssmix2Source(root, licensed=EMPTY)
    rows = {r["enc_no"]: r for r in src.rows("encounter", "encounter", None, None)}
    assert (rows["E1"]["enc_type"], rows["E1"]["end_datetime"], rows["E1"]["enc_status"]) == (
        "IPD",
        "2026-06-20 09:00:00",
        "finished",
    )
    assert (rows["E2"]["enc_type"], rows["E2"]["prev_enc_type"], rows["E2"]["class_changed_at"]) == (
        "OPD",
        "IPD",
        "2026-06-14 10:30:00",
    )
    assert rows["E2"]["enc_status"] == "finished"
    assert (rows["E3"]["enc_type"], rows["E3"]["enc_status"]) == ("IPD", "in-progress")  # admitted, not discharged
    assert "E9" not in rows and src.stats["ADT-52:visit not in storage"] == 1
    assert src.stats["ADT-52:discharge"] == 1 and src.stats["ADT-52:class change"] == 1
    # the delta of a night after the changes includes the changed and the discharged visit
    assert {
        r["enc_no"]
        for r in Ssmix2Source(root, licensed=EMPTY).rows(
            "encounter", "encounter", "visit_datetime", "2026-06-14 10:00:00"
        )
    } == {"E1", "E2"}


def test_omp_11_12_fold_into_their_order_or_stand_alone_with_hot_and_yj(tmp_path: Path) -> None:
    root = tmp_path / "ss"
    orc = "ORC|NW|RX1||2|IP||||20260101"
    rxe = "RXE||3943001F1020^アロプリノール錠^99YJ|100||mg"
    _storage(root, "10000001", "20260101", "OMP-01", "RX1", [orc, rxe, "TQ1|||||||20260101|20260131"])
    # 実施 of the same order: fills only what the order lacks (the HOT code)
    rxa = "RXA|0|1|20260102|20260130|110021301^アロプリノール錠^HOT^3943001F1020^^99YJ|100|mg"
    _storage(root, "10000001", "20260101", "OMP-11", "RX1", ["ORC|RE|RX1||2|CM||||20260101", rxa])
    # an injection 実施 with no order: a medication of its own
    rxa2 = "RXA|0|1|20260105|20260105|640421001^トシリズマブ皮下注^HOT^6399421G1020^^99YJ|162|mg"
    _storage(root, "10000001", "20260105", "OMP-12", "RX2", ["ORC|RE|RX2||1|CM||||20260105", rxa2])
    src = Ssmix2Source(root, licensed=EMPTY)
    rows = {r["rx_no"]: r for r in src.rows("medication", "medication", None, None)}
    a = rows["RX1"]
    assert (a["nhi_drug_code"], a["hot_code"], a["atc"], a["status"], a["start_date"]) == (
        "3943001F1020",
        "110021301",
        "M04AA01",
        "active",
        "2026-01-01",
    )
    assert (a["rp_no"], a["rx_kind"]) == ("2", "prescription")
    b = rows["RX2"]
    assert (b["nhi_drug_code"], b["hot_code"], b["atc"], b["status"], b["rx_kind"]) == (
        "6399421G1020",
        "640421001",
        "L04AC07",
        "completed",
        "injection",
    )
    # 10B-4: RXA-6 is the amount given at this administration (review 12 F3), no longer read as a daily dose
    assert (b["start_date"], b["dose_per_time"], b["daily_dose"], b["dose_unit"], b["order_date"]) == (
        "2026-01-05",
        "162",
        "",
        "mg",
        "2026-01-05",
    )
    assert src.stats["OMP-11:with its order"] == 1 and src.stats["OMP-12:without an order"] == 1
    seg = hl7.parse("MSH|^~\\&\rRXE||H1^x^HOT^Y1^^99YJ").first("RXE")
    assert seg is not None and drug_codes(seg, 2) == {"yj": "Y1", "hot": "H1", "atc": "", "name": "x"}


def test_extended_storage_documents(tmp_path: Path) -> None:
    from reportlab.pdfgen import canvas

    root = tmp_path / "ss"
    root.mkdir()
    ext = root / "extended_storage"

    def put(patient: str, day: str, kind: str, name: str, data: bytes) -> None:
        d = storage_dir(ext, patient, day, kind)
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(data)

    put(
        "10000001",
        "20260301",
        "DSC-01",
        "10000001_20260301_DSC-01_1_20260301000000000_-_1.txt",
        "退院時サマリ（旧版）".encode("cp932"),
    )
    put(
        "10000001",
        "20260301",
        "DSC-01",
        "10000001_20260301_DSC-01_1_20260302000000000_-_1.txt",
        "退院時サマリ：痛風発作は軽快した。".encode("cp932"),
    )
    put("10000001", "20260301", "DSC-01", "10000001_20260301_DSC-01_2_20260302000000000_-_0.txt", b"deleted")
    put("10000001", "20260302", "RPT-01", "report.html", "<html><body><p>読影所見：異常なし</p></body></html>".encode())
    put("10000001", "20260303", "NOTE", "memo.txt", "経過記録：安定".encode("iso2022_jp"))
    buf = __import__("io").BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "Imaging report: no acute findings.")
    c.save()
    put("10000002", "20260304", "RPT-02", "xr.pdf", buf.getvalue())
    put("10000002", "20260305", "IMG-01", "scan.jpg", b"\xff\xd8\xff\xe0 not text")
    src = Ssmix2Source(root, licensed=EMPTY)
    docs = list(src.rows("note", "note", None, None))
    by_kind = {d["note_no"].split("/")[3]: d for d in docs}
    assert by_kind["DSC-01"]["text"] == "退院時サマリ：痛風発作は軽快した。"  # the newest version
    assert by_kind["DSC-01"]["note_type"] == "discharge" and by_kind["DSC-01"]["note_datetime"] == "2026-03-01 00:00:00"
    assert by_kind["RPT-01"]["text"] == "読影所見：異常なし" and by_kind["RPT-01"]["note_type"] == "report"
    assert by_kind["NOTE"]["text"] == "経過記録：安定" and by_kind["NOTE"]["note_type"] == "progress"
    assert "no acute findings" in by_kind["RPT-02"]["text"]
    assert by_kind["IMG-01"]["text"] == "" and by_kind["IMG-01"]["note_type"] == "document"  # kept, counted
    assert len(docs) == 5 and src.stats["document:deleted"] == 1
    assert src.stats["document"] == 4 and src.stats["document without text (no text in a .jpg file)"] == 1
    assert list(src.rows("patient", "patient", None, None)) == []  # the extended storage is not a patient folder


# ---------------------------------------------------------------------------------------------- JP Core $validate
@pytest.fixture(scope="module")
def jp_hospital(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    from tools.ssmix2_export import export
    from tools.synth_hospital import run as synth_run

    out = tmp_path_factory.mktemp("jp-synth")
    synth_run(out, profile="ci", sites="jp-a:JP:120", ref_date=date(2026, 11, 1))
    storage = tmp_path_factory.mktemp("jp-ssmix2")
    counts = export(out / "jp-a", storage)
    assert all(counts[k] > 0 for k in ("ADT-52", "OMP-02", "OMP-11", "OMP-12", "document")), counts
    return {"csv": out / "jp-a", "ssmix2": storage}


def _ingest(kind: str, path: Path, mapping: Path, tmp: Path, keys: Path) -> Any:
    from adapter.pipeline import AdapterConfig, run_ingest

    cfg = AdapterConfig(lake_dir=tmp / "lake", secrets_dir=keys, mapping_path=mapping, site_id="JP-A")
    return run_ingest(cfg, kind, str(path), snapshot="2026-10-31", load_fhir=False, rebuild_lake=False)


def test_synthetic_ssmix2_hospital_passes_jp_core_validate(
    jp_hospital: dict[str, Path], site_key_dir: Path, tmp_path: Path
) -> None:
    rep = _ingest("ssmix2", jp_hospital["ssmix2"], JP_MAPPING, tmp_path, site_key_dir)
    pv = rep.profile_validation
    assert pv is not None and rep.passed, rep.errors
    assert pv.errors == 0 and pv.sampled == sum(min(50, n) for n in rep.counts.values()), (pv, rep.counts)
    assert pv.validator.startswith("jp-core jp-core.r4#1.1.0")
    snap = tmp_path / "lake" / "ndjson" / "2026-10-31"
    record = json.loads((snap / "jp_core_validation.json").read_text(encoding="utf-8"))
    assert record["failed"] == 0 and record["by_type"]["MedicationRequest"]["sampled"] == 50
    reader = json.loads((snap / "reader.json").read_text(encoding="utf-8"))
    assert reader["read"]["ADT-52:class change"] > 0 and reader["read"]["OMP-12:without an order"] > 0
    # every profiled resource claims JP Core; nothing claims TW Core
    text = "".join(p.read_text(encoding="utf-8") for p in snap.glob("*.ndjson"))
    assert "twcore" not in text and "JP_MedicationRequest" in text and "classHistory" in text
    assert "urn:oid:1.2.392.200119.4.403.1" in text  # HOT kept coded
    # the documents carry no chart number and no file name: ids are keyed hashes
    docs = [json.loads(x) for x in (snap / "DocumentReference.ndjson").read_text(encoding="utf-8").splitlines()]
    ext = [d for d in docs if "退院時サマリ" in base64.b64decode(d["content"][0]["attachment"]["data"]).decode()]
    assert ext and all("DSC-01" not in json.dumps(d) and not d["id"].startswith("ext") for d in ext)
    # $validate over the written snapshot gives the same answer, and so does the CLI
    again = jpcore.validate_snapshot(snap, 50)
    assert again.errors == 0 and again.sampled == pv.sampled
    from adapter.cli import main as adapter_main

    assert adapter_main(["validate", "--lake", str(tmp_path / "lake"), "--per-type", "5"]) == 0


def test_the_tw_mapping_fails_jp_core_plainly(jp_hospital: dict[str, Path], site_key_dir: Path, tmp_path: Path) -> None:
    """The same hospital through the TW Core mapping (plan v4 F5): every profiled resource fails, and says why."""
    from adapter.mapping.engine import Mapper, Mapping
    from adapter.sources.csv.source import CsvSource

    m = Mapping.load(TW_MAPPING)
    mapper = Mapper(m, b"k" * 32, "JP-A")
    rows = list(CsvSource(jp_hospital["csv"]).rows("patient", "patient", None, None))
    res = [r for r in mapper.map_table("patient", iter(rows)) if r["resourceType"] == "Patient"][:5]
    rep = jpcore.JpCoreValidator(EMPTY).validate(res)
    assert rep.errors == 5
    assert any("claims a TW Core profile" in m for m in rep.messages())
    assert any("claims no JP Core profile" in m for m in rep.messages())


def _ok_lab() -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "id": "o1",
        "meta": {"profile": [jpcore.JP + "JP_Observation_LabResult"]},
        "status": "final",
        "category": [
            {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "laboratory"}]}
        ],
        "code": {
            "coding": [
                {"system": "http://loinc.org", "code": "3084-1"},
                {"system": "urn:oid:1.2.392.200119.4.504", "code": "3C020000002327101"},
            ],
            "text": "尿酸",
        },
        "subject": {"reference": "Patient/p1"},
        "effectiveDateTime": "2026-01-01T09:00:00+09:00",
        "valueQuantity": {"value": 6.1, "unit": "mg/dL"},
        "specimen": {"display": "血清"},
    }


def _ok_rx() -> dict[str, Any]:
    return {
        "resourceType": "MedicationRequest",
        "id": "m1",
        "meta": {"profile": [jpcore.JP + "JP_MedicationRequest"]},
        "identifier": [
            {"system": "urn:oid:1.2.392.100495.20.3.81", "value": "1"},
            {"system": "urn:oid:1.2.392.100495.20.3.82", "value": "1"},
        ],
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {"coding": [{"system": "urn:oid:1.2.392.100495.20.1.73", "code": "3943001F1020"}]},
        "subject": {"reference": "Patient/p1"},
        "authoredOn": "2026-01-01",
    }


@pytest.mark.parametrize(
    ("break_it", "says"),
    [
        (lambda r: r.pop("specimen"), "specimen: at least 1 required"),
        (lambda r: r["code"].pop("text"), "text: at least 1 required"),
        (lambda r: r["category"][0]["coding"][0].update(code="vital-signs"), "slice laboratory of category"),
        (lambda r: r["code"]["coding"][0].update(code="3084-2"), "not a valid LOINC code"),
        (lambda r: r["code"]["coding"][1].update(code="3C0200"), "not a JLAC10 code"),
        (
            lambda r: r["meta"].update(profile=["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Nope"]),
            "not a JP Core 1.1.0 profile",
        ),
        (lambda r: r["meta"].update(profile=[jpcore.JP + "JP_Patient"]), "profiles Patient, not Observation"),
        (lambda r: r["valueQuantity"].update(value="lots"), "base R4"),
    ],
)
def test_jp_core_check_bites_on_lab_results(break_it: Any, says: str) -> None:
    v = jpcore.JpCoreValidator(EMPTY)
    assert v.check(_ok_lab()).ok, v.check(_ok_lab()).issues
    r = _ok_lab()
    break_it(r)
    out = v.check(r)
    assert not out.ok and any(says in i.text for i in out.issues), out.issues


@pytest.mark.parametrize(
    ("break_it", "says"),
    [
        (lambda r: r["identifier"].pop(), "slice orderInRp of identifier: at least 1 required"),
        (lambda r: r["identifier"].pop(0), "slice rpNumber of identifier"),
        (lambda r: r.pop("authoredOn"), "authoredOn: at least 1 required"),
        (lambda r: r.update(dispenseRequest={"expectedSupplyDuration": {"value": 7, "code": "wk"}}), 'must be "d"'),
        (lambda r: r["medicationCodeableConcept"]["coding"][0].update(code="KC0001"), "not a YJ code"),
    ],
)
def test_jp_core_check_bites_on_medication_requests(break_it: Any, says: str) -> None:
    v = jpcore.JpCoreValidator(EMPTY)
    assert v.check(_ok_rx()).ok, v.check(_ok_rx()).issues
    r = _ok_rx()
    break_it(r)
    out = v.check(r)
    assert not out.ok and any(says in i.text for i in out.issues), out.issues


def test_jp_core_patients_conditions_and_held_code_systems() -> None:
    v = jpcore.JpCoreValidator({"medis": {"ZB26": {}}, "jlac10": {}, "yj": {}})
    pat = {
        "resourceType": "Patient",
        "id": "p1",
        "meta": {"profile": [jpcore.JP + "JP_Patient"]},
        "identifier": [{"system": "urn:x", "value": "p1"}],
    }
    assert v.check(pat).ok
    out = v.check({**pat, "identifier": [{"system": "urn:x"}]})
    assert any("value: at least 1 required" in i.text for i in out.issues)
    assert any("claims no JP Core profile" in i.text for i in v.check({**pat, "meta": {}}).issues)
    cond: dict[str, Any] = {
        "resourceType": "Condition",
        "id": "c1",
        "meta": {"profile": [jpcore.JP + "JP_Condition"]},
        "subject": {"reference": "Patient/p1"},
        "code": {
            "coding": [
                {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "M10.9"},
                {"system": "urn:oid:1.2.392.200119.4.101.6", "code": "ZB27"},
            ]
        },
    }
    out = v.check(cond)
    assert out.ok and [i.severity for i in out.issues] == ["warning"]  # ZB27: not in the loaded release
    cond["code"]["coding"][0]["code"] = "M10.999"
    assert any("not an ICD-10-CM code" in i.text for i in v.check(cond).issues)
    oo = v.check(cond).operation_outcome()
    assert oo["resourceType"] == "OperationOutcome" and oo["issue"][0]["severity"] == "error"
    assert jpcore.loinc_ok("2160-0") and jpcore.loinc_ok("4548-4") and not jpcore.loinc_ok("2160-1")


def test_validate_api_and_terminology_api(tmp_path: Path) -> None:
    from adapter.app import app
    from fastapi.testclient import TestClient

    c = TestClient(app)
    one = c.post("/$validate", json={"resources": [_ok_lab()]}).json()
    assert one["ok"] and one["outcome"]["resourceType"] == "OperationOutcome"
    bad = _ok_lab()
    bad.pop("specimen")
    many = c.post("/$validate", json={"resources": [_ok_lab(), bad, _ok_rx()]}).json()
    assert not many["ok"] and many["sampled"] == 3 and many["failed"] == 1
    assert many["messages"][0].startswith("Observation/o1 Observation.specimen")
    assert {s["kind"]: s["state"] for s in c.get("/terminology").json()} == dict.fromkeys(FILES, "not_loaded")
    data = base64.b64encode((SAMPLES / FILES["jlac10"]).read_bytes()).decode()
    r = c.post(
        "/terminology/load", json={"kind": "jlac10", "version": "v1", "by": "admin", "b64": data, "name": "jlac10.tsv"}
    )
    assert r.status_code == 200 and r.json()["rows"] == 10
    assert {s["kind"]: s["state"] for s in c.get("/terminology").json()}["jlac10"] == "loaded"
    r = c.post(
        "/terminology/load",
        json={"kind": "medis", "version": "v1", "by": "admin", "b64": base64.b64encode(b"a,b\n1,2\n").decode()},
    )
    assert r.status_code == 422 and "no code column" in r.json()["detail"]


def test_mapping_profiles_and_overlay() -> None:
    from adapter.mapping.engine import Mapping

    m = Mapping.load(JP_MAPPING)
    assert m.fhir_profiles == "jp-core"
    assert m.profiles["https://twcore.mohw.gov.tw/ig/twcore/StructureDefinition/DocumentReference-twcore"] == ""
    lab = next(r for r in m.resources if r.type == "Observation" and r.table == "lab")
    assert "specimen.display" in lab.elements and "code.text" in lab.elements
    tw = Mapping.load(TW_MAPPING)
    assert not tw.profiles and tw.fhir_profiles == "tw-core"  # T-619a: the TW Core slices are written
    assert (
        "specimen.display" not in next(r for r in tw.resources if r.type == "Observation" and r.table == "lab").elements
    )
