"""Plan 10 card 10B-1 (D-1262): master's SS-MIX2 reader run, unchanged, over storages written from the
specification: criterion F1's four probes (``tests/ssmix2_f1_fixtures.py``) and the ``spec`` export of the synthetic
hospital, one case per data type. Each case states what the reader does today: a known gap is a strict expected
failure naming the card that closes it (the pattern of ``tests/unit/test_phi_guard_ja.py``), so the card that
closes it must turn it into a plain test. All data is synthetic."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from adapter.sources.ssmix2.source import Ssmix2Source

from tests import ssmix2_f1_fixtures as f1
from tools import ssmix2_export, ssmix2_shape_check
from tools.synth_hospital import run as synth_run

EMPTY: dict[str, dict[str, dict[str, str]]] = {"medis": {}, "jlac10": {}, "yj": {}}


def _rows(src: Ssmix2Source, table: str) -> list[dict[str, Any]]:
    return list(src.rows(table, table, None, None))


# ----------------------------------------------------------------------------------------------- criterion F1
@pytest.fixture
def probes(tmp_path: Path) -> tuple[f1.Fixture, Ssmix2Source]:
    fx = f1.build(tmp_path)
    return fx, Ssmix2Source(fx.root, licensed=EMPTY)


def test_the_f1_fixtures_pass_the_shape_check(probes: tuple[f1.Fixture, Ssmix2Source]) -> None:
    fx, _ = probes
    rep = ssmix2_shape_check.check(fx.root, fx.extended)
    assert rep.total == 0, rep.lines(2)


def test_f1_three_visits_on_three_days_read_as_three(probes: tuple[f1.Fixture, Ssmix2Source]) -> None:
    _, src = probes
    got = sorted((r["enc_no"], r["visit_datetime"]) for r in _rows(src, "encounter"))
    assert got == [(v, f"{w[:4]}-{w[4:6]}-{w[6:8]} {w[8:10]}:{w[10:12]}:{w[12:14]}") for w, v in f1.VISITS]


def test_f1_the_diagnosis_sample_reads_icd10_onset_current_and_main(probes: tuple[f1.Fixture, Ssmix2Source]) -> None:
    _, src = probes
    (r,) = _rows(src, "diagnosis")
    assert (r["diag_no"], r["icd10"], r["diag_date"], r["status"], r["main_diagnosis"]) == (
        f1.DIAGNOSIS,
        "K29.7",
        "2011-08-31",
        "A",
        "Y",
    )
    assert not r.get("outcome") and not r.get("end_date")


def test_f1_two_tablets_three_times_a_day_is_six_a_day(probes: tuple[f1.Fixture, Ssmix2Source]) -> None:
    _, src = probes
    (r,) = _rows(src, "medication")
    assert (r["rx_no"], r["dose_per_time"], r["doses_per_day"], r["daily_dose"], r["atc"]) == (
        f1.ORDER,
        "2",
        "3",
        "6",
        "M04AA01",
    )


def test_f1_a_guideline_layout_storage_reads_two_of_two_documents(probes: tuple[f1.Fixture, Ssmix2Source]) -> None:
    """Today the pathology report (LOINC 11526-1) is typed ``report``: the reader has no pathology note type (D-1262
    records it for 10B-5)."""
    _, src = probes
    docs = sorted((r["doc_code"], r["note_type"]) for r in _rows(src, "note"))
    assert docs == [("11526-1", "report"), ("18842-5", "discharge")]


# ----------------------------------------------------------------------------------------------- the spec export
@pytest.fixture(scope="module")
def hospital(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Ssmix2Source, dict[str, list[dict[str, Any]]]]:
    base = tmp_path_factory.mktemp("r10b1")
    synth_run(base / "synth", profile="ci", sites="jp-ss:JP:60", ref_date=date(2026, 11, 1), seed=42)
    csv_dir = base / "synth" / "jp-ss"
    ssmix2_export.export(csv_dir, base / "ss", variant="spec")
    src = Ssmix2Source(base / "ss", licensed=EMPTY)
    rows = {t: _rows(src, t) for t in ("patient", "encounter", "diagnosis", "medication", "lab", "note")}
    return csv_dir, src, rows


def _csv(path: Path, name: str) -> list[dict[str, str]]:
    with (path / f"{name}.csv").open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


Hospital = tuple[Path, Ssmix2Source, dict[str, list[dict[str, Any]]]]


def _patients(h: Hospital) -> bool:
    csv_dir, _, rows = h
    got = {r["mrn"]: (r["name"], r["birth_date"], r["sex"]) for r in rows["patient"]}
    return got == {p["mrn"]: (p["name"], p["birth_date"], p["sex"]) for p in _csv(csv_dir, "patient")}


def _phones(h: Hospital) -> bool:
    csv_dir, _, rows = h
    got = {r["mrn"]: r.get("phone") or "" for r in rows["patient"]}
    return all(got.get(p["mrn"]) == p["phone"] for p in _csv(csv_dir, "patient"))


def _visits(h: Hospital) -> bool:
    csv_dir, _, rows = h
    got = {r["enc_no"]: r["visit_datetime"] for r in rows["encounter"] if r["enc_type"] == "OPD"}
    return got == {e["enc_no"]: e["visit_datetime"] for e in _csv(csv_dir, "encounter")}


def _admissions(h: Hospital) -> bool:
    _, src, rows = h
    ipd = [r for r in rows["encounter"] if r["enc_type"] == "IPD"]
    return bool(ipd) and all(r.get("end_datetime") for r in ipd) and src.stats["ADT-52:discharge"] == len(ipd)


def _diagnoses(h: Hospital) -> bool:
    csv_dir, _, rows = h
    got = {r["diag_no"]: (r["diag_date"], r["status"]) for r in rows["diagnosis"]}
    return got == {d["diag_no"]: (d["diag_date"], "A") for d in _csv(csv_dir, "diagnosis")}


def _icd10(h: Hospital) -> bool:
    csv_dir, _, rows = h
    got = {r["diag_no"]: r["icd10"] for r in rows["diagnosis"]}
    return all(got.get(d["diag_no"]) == d["icd10"] for d in _csv(csv_dir, "diagnosis"))


def _orders(kind: str) -> Any:
    def check(h: Hospital) -> bool:
        csv_dir, _, rows = h
        got = {r["rx_no"]: r for r in rows["medication"]}
        want = [m for m in _csv(csv_dir, "medication")
                if m["atc"].startswith(ssmix2_export.INJECTABLE) == (kind == "injection")]  # fmt: skip
        return bool(want) and all(got.get(m["rx_no"], {}).get("atc") == m["atc"] for m in want)

    return check


def _given(stat: str) -> Any:
    def check(h: Hospital) -> bool:
        _, src, _ = h
        return src.stats[f"{stat}:with its order"] == src.stats[stat] > 0

    return check


def _labs(h: Hospital) -> bool:
    csv_dir, _, rows = h
    got = {r["lab_no"].split("@")[0]: r["result_value"] for r in rows["lab"]}
    presence = {"POS": "陽性", "NEG": "陰性"}
    return got == {
        lab["lab_no"]: presence.get(lab["result_value"], lab["result_value"]) for lab in _csv(csv_dir, "lab")
    }


def _documents(h: Hospital) -> bool:
    _, _, rows = h
    docs = [r for r in rows["note"] if r.get("doc_code")]
    return bool(docs) and all(r["note_type"] in ("discharge", "report") for r in docs)


def _contents_read(h: Hospital) -> bool:
    _, src, _ = h
    return src.stats["document:_contents.xml not read"] == 0


def _read_at_all(typ: str) -> Any:
    def check(h: Hospital) -> bool:
        _, src, _ = h
        return src.stats[f"storage:{typ} file (a type the reader does not read)"] == 0

    return check


def gap(card: str, what: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, reason=f"known gap ({card}): {what}")


CASES = [
    pytest.param("ADT-00", _patients, id="ADT-00 patients"),
    pytest.param("ADT-00", _phones, id="ADT-00 phone", marks=gap("10B-8", "PID-13 component 12 not read")),
    pytest.param("ADT-01", _read_at_all("ADT-01"), id="ADT-01", marks=gap("10B-8", "doctor in charge not read")),
    pytest.param("ADT-12", _visits, id="ADT-12"),
    *[pytest.param(t, _read_at_all(t), id=t, marks=gap("10B-8", "type not read"))
      for t in ("ADT-21", "ADT-31", "ADT-32", "ADT-41", "ADT-42", "ADT-51")],
    pytest.param("ADT-22", _admissions, id="ADT-22 admissions"),
    pytest.param("ADT-52", _admissions, id="ADT-52 discharges"),
    pytest.param("ADT-61", _read_at_all("ADT-61"), id="ADT-61", marks=gap("10B-7", "allergies not read")),
    pytest.param("PPR-01", _diagnoses, id="PPR-01"),
    pytest.param("PPR-01", _icd10, id="PPR-01 ICD-10 without PRB-10",
                 marks=gap("10B-3", "no ICD-10 through ZPR-5's exchange code when PRB-10 is absent")),
    pytest.param("OMD", _read_at_all("OMD"), id="OMD", marks=gap("10B-10", "diet orders not read")),
    pytest.param("OMP-01", _orders("prescription"), id="OMP-01"),
    pytest.param("OMP-11", _given("OMP-11"), id="OMP-11"),
    pytest.param("OMP-02", _orders("injection"), id="OMP-02",
                 marks=gap("10B-4", "the drug of an injection (RXC) not read; RXE-2's 注射種別 read as the drug")),
    pytest.param("OMP-12", _given("OMP-12"), id="OMP-12",
                 marks=gap("10B-4", "an injection 実施 not tied to its order (the order's drug is in RXC)")),
    pytest.param("OML-01", _read_at_all("OML-01"), id="OML-01", marks=gap("10B-9", "lab orders not read")),
    pytest.param("OML-11", _labs, id="OML-11"),
    *[pytest.param(t, _read_at_all(t), id=t, marks=gap("10B-9", "type not read"))
      for t in ("OMG-01", "OMG-02", "OMG-03", "OMG-11", "OMG-12", "OMG-13")],
    pytest.param("extended", _documents, id="extended documents"),
    pytest.param("extended", _contents_read, id="extended _contents.xml",
                 marks=gap("10B-5", "_contents.xml counted, not read")),
]  # fmt: skip


@pytest.mark.parametrize(("typ", "check"), CASES)
def test_the_reader_over_the_spec_export(hospital: Hospital, typ: str, check: Any) -> None:
    assert check(hospital), typ


def test_every_data_type_has_its_case() -> None:
    assert set(ssmix2_shape_check.TYPES) <= {c.values[0] for c in CASES}
