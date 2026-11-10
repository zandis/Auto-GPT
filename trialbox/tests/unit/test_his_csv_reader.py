"""T-615b (DATA-003, DATA-008): the HIS CSV reader.

* Character sets go through the one detector of D-215: a Big5 and a CP932 export load equal to their UTF-8 twin.
* A file the detector refuses is quarantined; the night goes on with the other tables, is held and audited.
* Any exception in an ingest writes one ``ingest.failed`` audit event (error type, step, table; no message text).
* ``--since`` filters on the source's change time (``updated_at``), not the clinical date: a corrected old lab result
  is picked up; a mapping whose ``delta:`` names a clinical date is refused on a delta night.

All data is synthetic: the committed ``site-a`` fixture and the synthetic generator's Japanese-style site.
"""

from __future__ import annotations

import csv
import json
import shutil
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from adapter.mapping.engine import Mapping
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import HELD, AdapterConfig, check_delta, run_ingest
from adapter.sources.cgrd_sql.source import SqlSource
from adapter.sources.csv.source import QUARANTINE_DIR, CsvSource, candidates
from tb_common import encoding

ROOT = Path(__file__).resolve().parents[2]
SITE_A = ROOT / "tests/fixtures/synthetic_patients/site-a"
MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
# the tables of site-a that hold Chinese text, plus two ASCII ones (kept small so the test stays fast)
TABLES = ("patient", "practitioner", "diagnosis", "lab", "report", "note")
TYPES = ("Patient", "Practitioner", "Condition", "Observation", "DiagnosticReport", "DocumentReference")
SNAP = "2026-11-01"


def _cfg(tmp: Path, **kw: Any) -> AdapterConfig:
    sec = tmp / "secrets"
    sec.mkdir(parents=True, exist_ok=True)
    (sec / "site_hmac.key").write_bytes(b"k" * 32)
    return AdapterConfig(lake_dir=tmp / "lake", secrets_dir=sec, mapping_path=kw.pop("mapping_path", MAPPING),
                         site_id="T", audit_dir=tmp / "audit", **kw)  # fmt: skip


def _night(cfg: AdapterConfig, feed: Path, snap: str = SNAP, since: str | None = None) -> Any:
    return run_ingest(cfg, "csv", str(feed), snapshot=snap, since=since, load_fhir=False, rebuild_lake=False,
                      validate=False)  # fmt: skip


def _audit(tmp: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for f in sorted((tmp / "audit").glob("*.jsonl")) for line in f.read_text().splitlines()]


def _resources(cfg: AdapterConfig, snap: str = SNAP) -> dict[str, list[dict[str, Any]]]:
    return {t: list(read_type(snapshot_dir(cfg.lake_dir, snap), t)) for t in TYPES}


def _transcode(src: Path, dest: Path, codec: str, tables: tuple[str, ...] = TABLES) -> None:
    dest.mkdir(parents=True)
    for t in tables:
        (dest / f"{t}.csv").write_bytes((src / f"{t}.csv").read_text(encoding="utf-8-sig").encode(codec))


def _write(dest: Path, table: str, rows: list[dict[str, str]]) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with (dest / f"{table}.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


# ------------------------------------------------------------------------------------------ DATA-003: encodings
def test_candidates_put_the_declared_set_first() -> None:
    assert candidates(None) == encoding.LEGACY
    assert candidates("utf-8") == encoding.LEGACY
    assert candidates("cp950")[0] == "big5" and candidates("BIG5")[0] == "big5"
    assert candidates("Shift_JIS")[0] == "cp932" and candidates("cp932") == ("cp932", "big5")


@pytest.mark.parametrize("declared", [None, "big5"])
def test_a_big5_his_export_loads_equal_to_its_utf8_twin(tmp_path: Path, declared: str | None) -> None:
    utf8, big5 = tmp_path / "utf8", tmp_path / "big5"
    _transcode(SITE_A, utf8, "utf-8")
    _transcode(SITE_A, big5, "big5")
    assert (big5 / "note.csv").read_bytes() != (utf8 / "note.csv").read_bytes()
    a = _cfg(tmp_path / "a")
    b = _cfg(tmp_path / "b", source_encoding=declared)
    _night(a, utf8)
    rep = _night(b, big5)
    assert not rep.held, rep.errors
    want, got = _resources(a), _resources(b)
    assert all(want[t] for t in TYPES) and got == want
    assert any("，" in str(r) for r in got["DocumentReference"]) or any("醫師" in str(r) for r in got["Practitioner"])


def test_a_cp932_his_export_loads_equal_to_its_utf8_twin(tmp_path: Path) -> None:
    from tools.synth.generator import Generator

    site = Generator(7, "DEMO-J", date(2026, 10, 5), 30, "7", style="JP", lang_mix={"ja": 1.0}).run()
    utf8 = tmp_path / "utf8"
    for t in TABLES:
        if site.tables.get(t):
            _write(utf8, t, [{k: str(v if v is not None else "") for k, v in r.items()} for r in site.tables[t]])
    tables = tuple(t for t in TABLES if (utf8 / f"{t}.csv").exists())
    sjis = tmp_path / "sjis"
    _transcode(utf8, sjis, "cp932", tables)
    text = "".join((utf8 / f"{t}.csv").read_text(encoding="utf-8") for t in tables)
    assert any("぀" <= ch <= "ヿ" for ch in text)  # kana: the twin really is Japanese text
    a = _cfg(tmp_path / "a")
    b = _cfg(tmp_path / "b", source_encoding="shift_jis")
    _night(a, utf8)
    rep = _night(b, sjis)
    assert not any("quarantined" in e for e in rep.errors), rep.errors
    want, got = _resources(a), _resources(b)
    assert want["Patient"] and want["DocumentReference"] and got == want


def test_a_broken_file_is_quarantined_and_the_night_goes_on_held(tmp_path: Path) -> None:
    feed = tmp_path / "feed"
    _transcode(SITE_A, feed, "utf-8")
    # a note export that changes character set half way (Big5 lines, then a Shift_JIS line): not text anyone can read
    lines = (feed / "note.csv").read_text(encoding="utf-8").splitlines(keepends=True)[:40]
    head = "".join(lines[:-1]).encode("big5")
    (feed / "note.csv").write_bytes(
        head + "N99999999,10000001,E1,2026-05-07 12:00:00,progress,診察の結果、経過良好。\r\n".encode("cp932")
    )
    cfg = _cfg(tmp_path)
    rep = _night(cfg, feed)
    assert rep.held and not rep.passed
    assert any(e.startswith("note: note.csv quarantined: FORM-ENCODING") for e in rep.errors), rep.errors
    assert (feed / QUARANTINE_DIR / "note.csv").is_file() and not (feed / "note.csv").exists()
    # the other tables were read: the night continued, its report and held marker are written
    got = _resources(cfg)
    assert got["Patient"] and got["Observation"] and not got["DocumentReference"]
    out = snapshot_dir(cfg.lake_dir, SNAP)
    assert (out / "ingest_report.json").is_file() and (out / HELD).is_file()
    ev = _audit(tmp_path)[-1]
    assert ev["event"] == "ingest.held"
    assert "FORM-ENCODING" in ev["detail"]["quarantined"]["note"]
    assert "經過" not in json.dumps(ev, ensure_ascii=False)  # no cell text in the audit


def test_a_read_only_export_keeps_the_file_but_still_quarantines_the_table(tmp_path: Path, monkeypatch: Any) -> None:
    feed = tmp_path / "feed"
    feed.mkdir()
    (feed / "lab.csv").write_bytes(b"lab_no,mrn\r\nL1,\xff\xfe\xfa\r\n")
    monkeypatch.setattr(shutil, "move", lambda *a: (_ for _ in ()).throw(PermissionError("read-only")))
    src = CsvSource(feed)
    assert list(src.rows("lab", "lab", None, None)) == []
    assert (feed / "lab.csv").exists() and src.has_table("lab")
    assert "left in place" in (src.quarantine_reason("lab") or "")


# ------------------------------------------------------------------------------- DATA-003: ingest.failed
def test_any_ingest_exception_writes_ingest_failed(tmp_path: Path, monkeypatch: Any) -> None:
    from adapter.mapping import engine

    feed = tmp_path / "feed"
    _transcode(SITE_A, feed, "utf-8", ("patient", "lab"))
    cfg = _cfg(tmp_path)

    def boom(self: Any, table: str, rows: Any) -> Any:
        if table == "lab":
            raise RuntimeError("cell 1.57 for 10000002")  # a message that quotes data never reaches the audit
        yield from ()

    monkeypatch.setattr(engine.Mapper, "map_table", boom)
    with pytest.raises(RuntimeError):
        _night(cfg, feed)
    ev = _audit(tmp_path)[-1]
    assert ev["event"] == "ingest.failed" and ev["snapshot"] == SNAP
    assert ev["detail"] == {"source": "csv", "since": None, "error": "RuntimeError", "step": "read", "table": "lab"}
    assert "10000002" not in json.dumps(ev)


def test_a_missing_export_writes_ingest_failed(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    with pytest.raises(FileNotFoundError):
        _night(cfg, tmp_path / "nowhere")
    ev = _audit(tmp_path)[-1]
    assert ev["event"] == "ingest.failed" and ev["detail"]["error"] == "FileNotFoundError"


# ------------------------------------------------------------------------------------ DATA-008: delta
PATIENT = [{"mrn": "10000002", "name": "Test Patient", "id_no": "", "birth_date": "1960-01-01", "sex": "F",
            "death_date": "", "phone": ""}]  # fmt: skip


def _lab(no: str, value: str, sample: str, updated: str) -> dict[str, str]:
    return {"lab_no": no, "mrn": "10000002", "local_code": "CRE", "item_name": "Creatinine", "result_value": value,
            "unit": "mg/dL", "sample_datetime": sample, "updated_at": updated}  # fmt: skip


def _value(cfg: AdapterConfig, snap: str) -> dict[str, float]:
    out = {}
    for r in read_type(snapshot_dir(cfg.lake_dir, snap), "Observation"):
        out[str(r["effectiveDateTime"])[:10]] = r["valueQuantity"]["value"]
    return out


def test_a_late_corrected_old_result_is_picked_up_by_since(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    full = tmp_path / "full"
    _write(full, "patient", PATIENT)
    _write(full, "lab", [_lab("L10000003", "1.57", "2025-12-20 08:00:00", "2025-12-20 09:00:00"),
                         _lab("L10000004", "1.20", "2025-12-21 08:00:00", "2025-12-21 09:00:00")])  # fmt: skip
    assert _night(cfg, full, "2026-11-01").passed
    assert _value(cfg, "2026-11-01") == {"2025-12-20": 1.57, "2025-12-21": 1.2}
    # the next night's export: the December result was corrected today; its sample date is still December
    delta = tmp_path / "delta"
    _write(delta, "patient", PATIENT)
    _write(delta, "lab", [_lab("L10000003", "123.0", "2025-12-20 08:00:00", "2026-11-02 01:00:00"),
                          _lab("L10000004", "9.99", "2025-12-21 08:00:00", "2025-12-21 09:00:00")])  # fmt: skip
    rep = _night(cfg, delta, "2026-11-02", since="2026-11-01")
    assert rep.passed, rep.errors
    # the corrected row is picked up; the row whose change time is before since is filtered (its stale 9.99 is not)
    assert _value(cfg, "2026-11-02") == {"2025-12-20": 123.0, "2025-12-21": 1.2}


def test_csv_delta_keeps_rows_without_a_change_time() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        feed = Path(d)
        _write(feed, "lab", [_lab("A", "1", "2025-01-01", ""), _lab("B", "1", "2025-01-01", "2025-01-02"),
                             _lab("C", "1", "2025-01-01", "2026-11-02")])  # fmt: skip
        _write(feed, "vital", [{"vital_no": "V1", "measure_datetime": "2020-01-01"}])
        src = CsvSource(feed)
        assert [r["lab_no"] for r in src.rows("lab", "lab", "updated_at", "2026-11-01")] == ["A", "C"]
        # no change-time column in the file: the whole file is the delta (merged by key), nothing is lost
        assert [r["vital_no"] for r in src.rows("vital", "vital", "updated_at", "2026-11-01")] == ["V1"]


def test_a_delta_on_a_clinical_date_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "site.yaml"
    bad.write_text(f"version: 1\nname: t\nextends: {MAPPING}\ntables:\n"
                   "  patient: {source: patient, key: mrn}\n"
                   "  lab: {source: lab, key: lab_no, delta: sample_datetime}\n", encoding="utf-8")  # fmt: skip
    with pytest.raises(ValueError, match="lab's delta column 'sample_datetime' is not a change time"):
        check_delta(Mapping.load(bad), "csv")
    check_delta(Mapping.load(bad), "ssmix2")  # SS-MIX2 versions its own files
    check_delta(Mapping.load(MAPPING), "cgrd_sql")
    feed = tmp_path / "feed"
    _write(feed, "patient", PATIENT)
    cfg = _cfg(tmp_path, mapping_path=bad)
    with pytest.raises(ValueError):
        _night(cfg, feed, since="2026-11-01")
    ev = _audit(tmp_path)[-1]
    assert ev["event"] == "ingest.failed" and ev["detail"]["step"] == "delta check"
    assert ev["detail"]["since"] == "2026-11-01"


def test_sql_delta_filters_on_the_change_time(tmp_path: Path) -> None:
    db = tmp_path / "his.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE lab (lab_no TEXT, sample_datetime TEXT, updated_at TEXT)")
    con.executemany("INSERT INTO lab VALUES (?, ?, ?)", [("A", "2025-12-20", "2026-11-02 01:00:00"),
                                                       ("B", "2025-12-21", "2025-12-21"), ("C", "2025-12-22", None)])  # fmt: skip
    con.execute("CREATE TABLE vital (vital_no TEXT, measure_datetime TEXT)")
    con.execute("INSERT INTO vital VALUES ('V1', '2020-01-01')")
    con.commit()
    con.close()
    src = SqlSource(f"sqlite:///{db}")
    assert sorted(r["lab_no"] for r in src.rows("lab", "lab", "updated_at", "2026-11-01")) == ["A", "C"]
    assert [r["vital_no"] for r in src.rows("vital", "vital", "updated_at", "2026-11-01")] == ["V1"]
    assert len(list(src.rows("lab", "lab", "updated_at", None))) == 3
