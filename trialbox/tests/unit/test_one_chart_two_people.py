"""H34-06 (T-659b, DATA-017): one chart number arriving with two different people's demographics is never merged.

Within one night (two patient rows under one chart number) or against the served night (tonight's row is another
person than the patient the lake serves under that number), the night is held with a line that says so, the audit
event and the steward's batch row count it, the pseudonymous ids go to ``identity_conflict.json`` in the night's
folder, the served record and the pid map's identity are not overwritten, and the rest of the night is read as usual.
Two people within one night cannot be accepted (an accept would serve one under the other's chart); a change against
the served night is the steward's to accept as a correction of one person. One person's row twice is still only DATA-017's count, and
a clean night is unchanged. Every row here is synthetic (site A's fixture and made-up values).
"""

from __future__ import annotations

import csv
import itertools
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import (
    COMPLETENESS,
    HELD,
    IDENTITY_CHECKED,
    IDENTITY_CONFLICT,
    PASSED,
    AdapterConfig,
    bulk_id,
    run_ingest,
)
from adapter.publish import TwoPeopleOneChart, publish_held
from tb_common.crypto import pid_for_mrn
from tb_contracts import RebuildResult

ROOT = Path(__file__).resolve().parents[2]
SITE_A = ROOT / "tests/fixtures/synthetic_patients/site-a"
MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
KEY = b"k" * 32
GOOD, NEXT = "2026-11-01", "2026-11-02"
_MAP = itertools.count()  # one pid map per test: a test that accepts a correction writes the map's identity


class _Rebuild:
    """The adapter's lake hook, a stand-in that only moves ``CURRENT``."""

    def __init__(self, lake_dir: Path) -> None:
        self.lake_dir = lake_dir
        self.calls: list[str] = []

    def __call__(self, snap: str, nd: Path) -> RebuildResult:
        self.calls.append(snap)
        (self.lake_dir / "db").mkdir(parents=True, exist_ok=True)
        (self.lake_dir / "db" / f"{snap}.duckdb").write_bytes(b"")
        (self.lake_dir / "CURRENT").write_text(snap)
        return RebuildResult(snapshot=snap, tables={}, chunks=0, embedded_new=0, seconds=0.0)


def _cfg(tmp: Path, db_url: str) -> tuple[AdapterConfig, _Rebuild]:
    sec = tmp / "secrets"
    sec.mkdir(exist_ok=True)
    (sec / "site_hmac.key").write_bytes(KEY)
    rb = _Rebuild(tmp / "lake")
    cfg = AdapterConfig(lake_dir=tmp / "lake", secrets_dir=sec, mapping_path=MAPPING, site_id="T",
                        audit_dir=tmp / "audit", rebuild=rb, db_url=db_url)  # fmt: skip
    return cfg, rb


def _night(cfg: AdapterConfig, feed: Path, snap: str) -> Any:
    return run_ingest(cfg, "csv", str(feed), snapshot=snap, load_fhir=False, validate=False)


def _feed(tmp: Path) -> Path:
    dst = tmp / "feed"
    shutil.copytree(SITE_A, dst, ignore=shutil.ignore_patterns("*.json"))
    return dst


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _other_person(row: dict[str, str]) -> dict[str, str]:
    """Another, made-up person under ``row``'s chart number: another name, birth date and sex."""
    return {**row, "name": "Synthetic Other", "id_no": "", "birth_date": "1999-09-09",
            "sex": "M" if row["sex"] == "F" else "F", "death_date": "", "phone": ""}  # fmt: skip


def _audit(tmp: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for f in sorted((tmp / "audit").glob("*.jsonl")) for x in f.read_text().splitlines()]


def _served_patient(cfg: AdapterConfig, pid: str) -> list[dict[str, Any]]:
    return [r for r in read_type(snapshot_dir(cfg.lake_dir, GOOD), "Patient") if r["id"] == pid]


@pytest.fixture
def good(tmp_path_factory: pytest.TempPathFactory, pg_cluster_url: str) -> tuple[Path, str, dict[str, str]]:
    """One good night of synthetic site A, promoted, with its own pid map; the test copies it."""
    tmp = tmp_path_factory.mktemp("good")
    sep = "&" if "?" in pg_cluster_url else "?"
    db_url = f"{pg_cluster_url}{sep}tb_prefix=twopeople{os.getpid()}_{next(_MAP)}_"
    cfg, _rb = _cfg(tmp, db_url)
    rep = _night(cfg, _feed(tmp), GOOD)
    assert rep.passed and not rep.held
    return tmp, db_url, _rows(SITE_A / "patient.csv")[0]


def _from_good(good: tuple[Path, str, dict[str, str]], tmp: Path) -> tuple[AdapterConfig, _Rebuild]:
    shutil.copytree(good[0] / "lake", tmp / "lake")
    shutil.copytree(good[0] / "secrets", tmp / "secrets")  # the pid map's own key too: its identities are read back
    return _cfg(tmp, good[1])


def _assert_held_and_kept(cfg: AdapterConfig, rb: _Rebuild, rep: Any, first: dict[str, str], pid: str) -> None:
    """The night is held at the gate, the served night and record untouched, the pid map's identity of the chart the
    first person's; the accept of two people within one night is refused."""
    assert rep.held and not rep.passed
    assert rb.calls == []
    assert (cfg.lake_dir / "CURRENT").read_text().strip() == GOOD
    assert (snapshot_dir(cfg.lake_dir, NEXT) / HELD).exists()
    served = _served_patient(cfg, pid)
    assert len(served) == 1 and served[0]["birthDate"] == first["birth_date"]
    pm = cfg.pidmap()
    try:
        assert (pm.identity(pid) or {}).get("name") == first["name"]
    finally:
        pm.close()


def test_two_people_under_one_chart_in_one_night_are_held_never_merged(good: Any, tmp_path: Path) -> None:
    cfg, rb = _from_good(good, tmp_path)
    feed = _feed(tmp_path)
    first = good[2]
    pid = pid_for_mrn(KEY, first["mrn"])
    _write(feed / "patient.csv", [*_rows(feed / "patient.csv"), _other_person(first)])
    enc = _rows(feed / "encounter.csv")
    _write(feed / "encounter.csv", [*enc, {**enc[0], "enc_no": "E9999001", "mrn": first["mrn"],
                                           "visit_datetime": "2026-10-09 11:11:00"}])  # fmt: skip
    rep = _night(cfg, feed, NEXT)
    text = " ".join(rep.errors)
    assert "two different people" in text and "1 within this night, 0 against" in text, text
    assert first["mrn"] not in text and first["name"] not in text  # counts only, never the chart or a name
    said = json.loads((snapshot_dir(cfg.lake_dir, NEXT) / IDENTITY_CONFLICT).read_text())
    assert said["tonight"] == [pid] and said["against"]["pids"] == []
    # the rest of the night was read and mapped as usual: every table present, every other patient written
    comp = json.loads((snapshot_dir(cfg.lake_dir, NEXT) / COMPLETENESS).read_text())
    assert all(t["present"] for t in comp["tables"].values())
    assert rep.counts["Patient"] == len(_rows(SITE_A / "patient.csv")) + 1 and rep.counts["Encounter"] > len(enc)
    event = _audit(tmp_path)[-1]
    assert event["event"] == "ingest.held"
    assert event["detail"]["identity_conflicts"] == {"tonight": 1, "against_served": 0}
    _assert_held_and_kept(cfg, rb, rep, first, pid)
    with pytest.raises(TwoPeopleOneChart):  # an accept would serve one person under the other's chart
        publish_held(cfg, NEXT)
    assert (cfg.lake_dir / "CURRENT").read_text().strip() == GOOD and rb.calls == []
    _assert_held_and_kept(cfg, rb, rep, first, pid)


def test_another_person_under_a_served_chart_on_the_next_night_is_held(good: Any, tmp_path: Path) -> None:
    cfg, rb = _from_good(good, tmp_path)
    feed = _feed(tmp_path)
    first = good[2]
    pid = pid_for_mrn(KEY, first["mrn"])
    rows = _rows(feed / "patient.csv")
    _write(feed / "patient.csv", [_other_person(rows[0]), *rows[1:]])  # one row: no duplicate key to count
    rep = _night(cfg, feed, NEXT)
    text = " ".join(rep.errors)
    assert "two different people" in text and f"0 within this night, 1 against the served night {GOOD}" in text
    said = json.loads((snapshot_dir(cfg.lake_dir, NEXT) / IDENTITY_CONFLICT).read_text())
    assert said["tonight"] == [] and said["against"] == {"snapshot": GOOD, "pids": [pid]}
    comp = json.loads((snapshot_dir(cfg.lake_dir, NEXT) / COMPLETENESS).read_text())
    assert comp["tables"]["patient"]["duplicate_keys"] == 0
    assert _audit(tmp_path)[-1]["detail"]["identity_conflicts"] == {"tonight": 0, "against_served": 1}
    assert "accept it only if each is a correction of the same person's details" in text
    _assert_held_and_kept(cfg, rb, rep, first, pid)
    # a change against the served night is the steward's: a confirmed correction of one person is accepted, audited
    # by the decision (datacore.dataops.decide), and only then served
    assert publish_held(cfg, NEXT).promoted and rb.calls == [NEXT]
    # both versions kept: the night served before still holds the first person; tonight serves the corrected one
    assert _served_patient(cfg, pid)[0]["birthDate"] == first["birth_date"]
    assert [r["birthDate"] for r in read_type(snapshot_dir(cfg.lake_dir, NEXT), "Patient") if r["id"] == pid] == [
        "1999-09-09"
    ]


@pytest.mark.parametrize(("field", "value"), [("birth_date", "1999-09-09"), ("name", "Synthetic Other")])
def test_a_first_row_leaving_a_value_out_does_not_hide_two_later_ones(
    good: Any, tmp_path: Path, field: str, value: str
) -> None:
    """Review R1: missing, then A, then B under one chart number is two people (each row is compared with all the
    chart number gave before it, not only with its first row)."""
    cfg, rb = _from_good(good, tmp_path)
    feed = _feed(tmp_path)
    first = good[2]
    pid = pid_for_mrn(KEY, first["mrn"])
    rows = _rows(feed / "patient.csv")
    _write(feed / "patient.csv", [{**rows[0], field: ""}, *rows, {**rows[0], field: value}])
    rep = _night(cfg, feed, NEXT)
    assert "1 within this night, 0 against" in " ".join(rep.errors), rep.errors
    assert rep.counts["Patient"] == len(rows) + 2  # the row leaving the value out was read too
    said = json.loads((snapshot_dir(cfg.lake_dir, NEXT) / IDENTITY_CONFLICT).read_text())
    assert said["tonight"] == [pid]
    _assert_held_and_kept(cfg, rb, rep, first, pid)
    with pytest.raises(TwoPeopleOneChart):
        publish_held(cfg, NEXT)


@pytest.mark.parametrize(("field", "value"), [("id_no", "A123456789"), ("name", "Synthetic Other")])
def test_a_later_night_changing_only_the_name_or_national_id_is_held(
    good: Any, tmp_path: Path, field: str, value: str
) -> None:
    """Review R2: the served night's name and national id (the pid map's identity) are compared too, not only the
    birth date and sex the served Patient carries. Held for the steward, who may accept it as a correction."""
    cfg, rb = _from_good(good, tmp_path)
    feed = _feed(tmp_path)
    first = good[2]
    pid = pid_for_mrn(KEY, first["mrn"])
    rows = _rows(feed / "patient.csv")
    _write(feed / "patient.csv", [{**rows[0], field: value}, *rows[1:]])
    rep = _night(cfg, feed, NEXT)
    text = " ".join(rep.errors)
    assert f"0 within this night, 1 against the served night {GOOD}" in text, text
    assert first[field] not in text and value not in text  # counts only
    said = json.loads((snapshot_dir(cfg.lake_dir, NEXT) / IDENTITY_CONFLICT).read_text())
    assert said["tonight"] == [] and said["against"] == {"snapshot": GOOD, "pids": [pid]}
    _assert_held_and_kept(cfg, rb, rep, first, pid)
    pm = cfg.pidmap()
    try:
        assert (pm.identity(pid) or {}).get("national_id") == first["id_no"]
    finally:
        pm.close()
    assert publish_held(cfg, NEXT).promoted and rb.calls == [NEXT]  # steward-acceptable as ruled


def test_one_persons_row_twice_and_a_clean_night_are_unchanged(good: Any, tmp_path: Path) -> None:
    cfg, rb = _from_good(good, tmp_path)
    feed = _feed(tmp_path)
    rows = _rows(feed / "patient.csv")
    _write(feed / "patient.csv", [*rows, rows[1]])  # DATA-017: the same person twice is a duplicate key, counted
    rep = _night(cfg, feed, NEXT)
    assert rep.passed and not rep.held, rep.errors
    assert rb.calls == [NEXT]
    folder = snapshot_dir(cfg.lake_dir, NEXT)
    assert (folder / PASSED).exists() and not (folder / IDENTITY_CONFLICT).exists()
    assert json.loads((folder / COMPLETENESS).read_text())["tables"]["patient"]["duplicate_keys"] == 1
    assert _audit(tmp_path)[-1]["detail"]["identity_conflicts"] is None


def test_an_accept_of_a_night_the_identity_check_never_ran_on_is_refused(good: Any, tmp_path: Path) -> None:
    """Review M1: a night held by an earlier release (or by a run that stopped before the check) has neither the
    conflict file nor the check's mark; its accept is refused, never taken for a night with no conflict."""
    cfg, rb = _from_good(good, tmp_path)
    feed = _feed(tmp_path)
    rows = _rows(feed / "patient.csv")
    _write(feed / "patient.csv", [_other_person(rows[0]), *rows[1:]])  # held, and acceptable as it stands
    rep = _night(cfg, feed, NEXT)
    folder = snapshot_dir(cfg.lake_dir, NEXT)
    assert rep.held and (folder / IDENTITY_CHECKED).is_file() and (folder / IDENTITY_CONFLICT).is_file()
    for name in (IDENTITY_CONFLICT, IDENTITY_CHECKED):  # the folder as an earlier release left its held night
        (folder / name).unlink()
    with pytest.raises(TwoPeopleOneChart, match="never ran on this night"):
        publish_held(cfg, NEXT)
    assert (cfg.lake_dir / "CURRENT").read_text().strip() == GOOD and rb.calls == []
    (folder / IDENTITY_CHECKED).write_text(json.dumps({"snapshot": NEXT}) + "\n", encoding="utf-8")
    assert publish_held(cfg, NEXT).promoted and rb.calls == [NEXT]  # checked, no conflict listed: the steward's


def test_a_bulk_export_with_two_people_under_one_patient_id_is_held(tmp_path: Path) -> None:
    sec = tmp_path / "secrets"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(KEY)
    cfg = AdapterConfig(lake_dir=tmp_path / "lake", secrets_dir=sec, site_id="T", audit_dir=tmp_path / "audit",
                        mapping_path=MAPPING)  # fmt: skip
    exp = tmp_path / "bulk"
    exp.mkdir()
    feed: dict[str, list[dict[str, Any]]] = {
        "Patient": [
            {"resourceType": "Patient", "id": "p1", "gender": "female", "birthDate": "1971-03-01"},
            {"resourceType": "Patient", "id": "p1", "gender": "male", "birthDate": "1999-09-09"},
            {"resourceType": "Patient", "id": "p2", "gender": "male", "birthDate": "1980-01-01"},
        ],
        "Encounter": [
            {"resourceType": "Encounter", "id": "e2", "status": "finished", "subject": {"reference": "Patient/p2"}}
        ],
    }
    for rtype, items in feed.items():
        (exp / f"{rtype}.ndjson").write_text("\n".join(json.dumps(r) for r in items) + "\n", encoding="utf-8")
    rep = run_ingest(cfg, "fhir_bulk", str(exp), snapshot=NEXT, load_fhir=False, rebuild_lake=False, validate=False)
    assert rep.held and not rep.passed
    assert "two different people" in " ".join(rep.errors or [])
    said = json.loads((snapshot_dir(cfg.lake_dir, NEXT) / IDENTITY_CONFLICT).read_text())
    assert said["tonight"] == [bulk_id(KEY, "Patient", "p1")]
    assert rep.counts.get("Encounter") == 1  # the rest of the export was read
