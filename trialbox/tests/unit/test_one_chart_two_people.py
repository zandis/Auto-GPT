"""H34-06 (T-659b, DATA-017): one chart number arriving with two different people's demographics is never merged.

Within one night (two patient rows under one chart number, or two chart numbers a merge makes one patient) or against
the served night (tonight's row is another person than the patient the lake serves under that number), PRODUCT-2
("hold records, not nights"): the chart's records are held, never merged into one patient and never published, the
audit event and the steward's batch row count it, the pseudonymous ids and the records held go to
``identity_conflict.json`` in the night's folder, the served record and the pid map's identity are not overwritten,
and the rest of the night is published as usual. A held night is accepted only with its identity check's result
(``identity_checked.json``, this night's). One person's row twice is still only DATA-017's count, and a clean night
is unchanged. Every row here is synthetic (site A's fixture and made-up values).
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
from adapter.publish import NothingToPublish, TwoPeopleOneChart, publish_held
from tb_common.crypto import pid_for_mrn
from tb_contracts import RebuildResult

ROOT = Path(__file__).resolve().parents[2]
SITE_A = ROOT / "tests/fixtures/synthetic_patients/site-a"
MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
KEY = b"k" * 32
GOOD, NEXT = "2026-11-01", "2026-11-02"
MERGED = "19999999"  # a made-up chart number merged into a served one (review P-04-1)
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


def _text(cfg: AdapterConfig, snap: str) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in sorted(snapshot_dir(cfg.lake_dir, snap).glob("*.ndjson")))


def _assert_records_held(
    cfg: AdapterConfig, rb: _Rebuild, rep: Any, first: dict[str, str], pid: str, others: int | None = None
) -> None:
    """PRODUCT-2 ("hold records, not nights"): the night is published without the chart's records (``others``: the
    patients it serves), the served night's record untouched, the pid map's identity of the chart the first
    person's, also after the publish."""
    assert rep.passed and not rep.held, rep.errors
    assert not any("two different people" in e for e in rep.errors or [])  # no night-level hold
    assert rb.calls == [NEXT] and (cfg.lake_dir / "CURRENT").read_text().strip() == NEXT
    folder = snapshot_dir(cfg.lake_dir, NEXT)
    assert (folder / PASSED).exists() and not (folder / HELD).exists()
    assert pid not in _text(cfg, NEXT)  # neither its Patient nor a record that names it
    n = len(_rows(SITE_A / "patient.csv")) - 1 if others is None else others
    assert len(list(read_type(folder, "Patient"))) == n  # everyone else is served
    with pytest.raises(NothingToPublish):  # nothing is left held to accept
        publish_held(cfg, NEXT)
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
    listed = (snapshot_dir(cfg.lake_dir, NEXT) / IDENTITY_CONFLICT).read_text()
    assert first["mrn"] not in listed and first["name"] not in listed  # pseudonymous ids, never the chart or a name
    said = json.loads(listed)
    assert said["tonight"] == [pid] and said["against"]["pids"] == [] and said["held"] == [pid]
    assert said["records"]["Patient"] == 2 and said["records"]["Encounter"] >= 1  # E9999001 among them
    # the rest of the night was read and mapped as usual: every table present, every other patient written
    comp = json.loads((snapshot_dir(cfg.lake_dir, NEXT) / COMPLETENESS).read_text())
    assert all(t["present"] for t in comp["tables"].values())
    assert rep.counts["Patient"] == len(_rows(SITE_A / "patient.csv")) + 1 and rep.counts["Encounter"] > len(enc)
    event = _audit(tmp_path)[-1]
    assert event["event"] == "ingest.done"
    assert event["detail"]["identity_conflicts"] == {"tonight": 1, "against_served": 0}
    _assert_records_held(cfg, rb, rep, first, pid)
    assert "E9999001" not in _text(cfg, NEXT)


def test_another_person_under_a_served_chart_on_the_next_night_is_held(good: Any, tmp_path: Path) -> None:
    cfg, rb = _from_good(good, tmp_path)
    feed = _feed(tmp_path)
    first = good[2]
    pid = pid_for_mrn(KEY, first["mrn"])
    rows = _rows(feed / "patient.csv")
    _write(feed / "patient.csv", [_other_person(rows[0]), *rows[1:]])  # one row: no duplicate key to count
    rep = _night(cfg, feed, NEXT)
    said = json.loads((snapshot_dir(cfg.lake_dir, NEXT) / IDENTITY_CONFLICT).read_text())
    assert said["tonight"] == [] and said["against"] == {"snapshot": GOOD, "pids": [pid]}
    comp = json.loads((snapshot_dir(cfg.lake_dir, NEXT) / COMPLETENESS).read_text())
    assert comp["tables"]["patient"]["duplicate_keys"] == 0
    assert _audit(tmp_path)[-1]["detail"]["identity_conflicts"] == {"tonight": 0, "against_served": 1}
    _assert_records_held(cfg, rb, rep, first, pid)
    # the night served before still holds the first person; tonight serves no one under the chart
    assert _served_patient(cfg, pid)[0]["birthDate"] == first["birth_date"]
    assert "1999-09-09" not in _text(cfg, NEXT)


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
    assert rep.counts["Patient"] == len(rows) + 2  # the row leaving the value out was read too
    said = json.loads((snapshot_dir(cfg.lake_dir, NEXT) / IDENTITY_CONFLICT).read_text())
    assert said["tonight"] == [pid] and said["against"]["pids"] == []
    _assert_records_held(cfg, rb, rep, first, pid)


@pytest.mark.parametrize(("field", "value"), [("id_no", "A123456789"), ("name", "Synthetic Other")])
def test_a_later_night_changing_only_the_name_or_national_id_is_held(
    good: Any, tmp_path: Path, field: str, value: str
) -> None:
    """Review R2: the served night's name and national id (the pid map's identity) are compared too, not only the
    birth date and sex the served Patient carries. The chart's records are held; the pid map keeps the first
    person's identity after the night is published."""
    cfg, rb = _from_good(good, tmp_path)
    feed = _feed(tmp_path)
    first = good[2]
    pid = pid_for_mrn(KEY, first["mrn"])
    rows = _rows(feed / "patient.csv")
    _write(feed / "patient.csv", [{**rows[0], field: value}, *rows[1:]])
    rep = _night(cfg, feed, NEXT)
    listed = (snapshot_dir(cfg.lake_dir, NEXT) / IDENTITY_CONFLICT).read_text()
    assert first[field] not in listed and value not in listed  # pseudonymous ids only
    said = json.loads(listed)
    assert said["tonight"] == [] and said["against"] == {"snapshot": GOOD, "pids": [pid]}
    _assert_records_held(cfg, rb, rep, first, pid)
    pm = cfg.pidmap()
    try:
        assert (pm.identity(pid) or {}).get("national_id") == first["id_no"]
    finally:
        pm.close()


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


def _held_for_a_missing_table(cfg: AdapterConfig, feed: Path) -> Any:
    """A night held at the gate for another reason than identity: a table of the served night is missing."""
    (feed / "diagnosis.csv").unlink()
    rep = _night(cfg, feed, NEXT)
    assert rep.held and not rep.passed and "incomplete feed" in " ".join(rep.errors), rep.errors
    return rep


def test_an_accept_of_a_night_the_identity_check_never_ran_on_is_refused(good: Any, tmp_path: Path) -> None:
    """Review M1: a night held by an earlier release (or by a run that stopped before the check) has neither the
    conflict file nor the check's mark; its accept is refused, never taken for a night with no conflict. A result
    that is another night's or cannot be read is refused too; the run's own result lets the accept through."""
    cfg, rb = _from_good(good, tmp_path)
    feed = _feed(tmp_path)
    rows = _rows(feed / "patient.csv")
    _write(feed / "patient.csv", [_other_person(rows[0]), *rows[1:]])  # the chart's records held
    _held_for_a_missing_table(cfg, feed)
    folder = snapshot_dir(cfg.lake_dir, NEXT)
    assert (folder / IDENTITY_CHECKED).is_file() and (folder / IDENTITY_CONFLICT).is_file()
    result = (folder / IDENTITY_CHECKED).read_bytes()
    for name in (IDENTITY_CONFLICT, IDENTITY_CHECKED):  # the folder as an earlier release left its held night
        (folder / name).unlink()
    with pytest.raises(TwoPeopleOneChart, match="never ran on this night"):
        publish_held(cfg, NEXT)
    for wrong in (json.dumps({"snapshot": GOOD, "held": []}), json.dumps({"snapshot": NEXT}), "null", "{"):
        (folder / IDENTITY_CHECKED).write_text(wrong + "\n", encoding="utf-8")
        with pytest.raises(TwoPeopleOneChart, match="never ran on this night"):
            publish_held(cfg, NEXT)
    assert (cfg.lake_dir / "CURRENT").read_text().strip() == GOOD and rb.calls == []
    (folder / IDENTITY_CHECKED).write_bytes(result)
    assert publish_held(cfg, NEXT).promoted and rb.calls == [NEXT]  # checked: the steward's


def test_a_held_night_whose_conflict_list_is_lost_still_serves_no_one_under_the_chart(
    good: Any, tmp_path: Path
) -> None:
    """Review M1 (second round): two people within the night, the night held for another reason, and the conflict
    list removed from its folder: the accept publishes the night as it was written, without the chart's records."""
    cfg, rb = _from_good(good, tmp_path)
    feed = _feed(tmp_path)
    first = good[2]
    pid = pid_for_mrn(KEY, first["mrn"])
    _write(feed / "patient.csv", [*_rows(feed / "patient.csv"), _other_person(first)])
    _held_for_a_missing_table(cfg, feed)
    folder = snapshot_dir(cfg.lake_dir, NEXT)
    assert json.loads((folder / IDENTITY_CONFLICT).read_text())["tonight"] == [pid]
    (folder / IDENTITY_CONFLICT).unlink()
    assert publish_held(cfg, NEXT).promoted and rb.calls == [NEXT]
    assert pid not in _text(cfg, NEXT)
    pm = cfg.pidmap()
    try:
        assert (pm.identity(pid) or {}).get("name") == first["name"]
    finally:
        pm.close()


@pytest.mark.parametrize("both", [True, False], ids=["both numbers tonight", "the merged number alone"])
def test_chart_numbers_a_merge_makes_one_patient_are_one_person(good: Any, tmp_path: Path, both: bool) -> None:
    """Review P-04-1: a chart number merged into a served one (T-659b) is written under the served patient, so its
    row is compared as that patient's. Both numbers tonight with two people's demographics: two people within the
    night. The merged number alone: another person against the served night. Either way the merged number's records
    are held, never written under the served patient; the served patient's own records are published."""
    cfg, rb = _from_good(good, tmp_path)
    feed = _feed(tmp_path)
    first = good[2]
    pid = pid_for_mrn(KEY, first["mrn"])
    pm = cfg.pidmap()
    try:
        old, survivor = pm.merge(KEY, MERGED, first["mrn"], "synthetic merge", "SYN-1")
    finally:
        pm.close()
    assert survivor == pid
    rows = _rows(feed / "patient.csv")
    other = {**_other_person(first), "mrn": MERGED}
    _write(feed / "patient.csv", [*rows, other] if both else [other, *rows[1:]])
    enc = _rows(feed / "encounter.csv")
    _write(feed / "encounter.csv", [*enc, {**enc[0], "enc_no": "E9999002", "mrn": MERGED,
                                           "visit_datetime": "2026-10-09 11:11:00"}])  # fmt: skip
    rep = _night(cfg, feed, NEXT)
    said = json.loads((snapshot_dir(cfg.lake_dir, NEXT) / IDENTITY_CONFLICT).read_text())
    if both:
        assert said["tonight"] == [old] and said["against"]["pids"] == []
    else:
        assert said["tonight"] == [] and said["against"] == {"snapshot": GOOD, "pids": [old]}
    assert said["held"] == [old] and said["records"]["Encounter"] >= 1
    assert rep.passed and not rep.held, rep.errors
    assert rb.calls == [NEXT]
    text = _text(cfg, NEXT)
    assert old not in text and "E9999002" not in text and "1999-09-09" not in text
    served = [r for r in read_type(snapshot_dir(cfg.lake_dir, NEXT), "Patient") if r["id"] == pid]
    assert [r["birthDate"] for r in served] == ([first["birth_date"]] if both else [])
    pm = cfg.pidmap()
    try:
        assert (pm.identity(pid) or {}).get("name") == first["name"]
    finally:
        pm.close()


def test_a_merge_of_one_persons_two_chart_numbers_is_still_written_under_the_surviving_patient(
    good: Any, tmp_path: Path
) -> None:
    """T-659b unchanged: the merged number with the same person's demographics is no conflict; its records are
    written under the surviving patient."""
    cfg, rb = _from_good(good, tmp_path)
    feed = _feed(tmp_path)
    first = good[2]
    pid = pid_for_mrn(KEY, first["mrn"])
    pm = cfg.pidmap()
    try:
        old, _ = pm.merge(KEY, MERGED, first["mrn"], "synthetic merge", "SYN-1")
    finally:
        pm.close()
    rows = _rows(feed / "patient.csv")
    _write(feed / "patient.csv", [*rows, {**first, "mrn": MERGED}])
    enc = _rows(feed / "encounter.csv")
    _write(feed / "encounter.csv", [*enc, {**enc[0], "enc_no": "E9999002", "mrn": MERGED,
                                           "visit_datetime": "2026-10-09 11:11:00"}])  # fmt: skip
    rep = _night(cfg, feed, NEXT)
    assert rep.passed and not rep.held, rep.errors
    assert rb.calls == [NEXT]
    folder = snapshot_dir(cfg.lake_dir, NEXT)
    assert not (folder / IDENTITY_CONFLICT).exists()
    assert json.loads((folder / IDENTITY_CHECKED).read_text()) == {"snapshot": NEXT, "held": []}
    e = [r for r in read_type(folder, "Encounter") if "E9999002" in json.dumps(r)]
    assert len(e) == 1 and e[0]["subject"]["reference"] == f"Patient/{pid}" and old not in _text(cfg, NEXT)


_NATIONAL = "urn:oid:1.2.392.100495.20.3.51"  # a national id system (illustrative)


@pytest.mark.parametrize(
    "second",
    [
        {"gender": "male", "birthDate": "1999-09-09"},
        {"identifier": [{"system": _NATIONAL, "value": "Z00000002"}]},
        {"name": [{"use": "official", "family": "Other", "given": ["Synthetic"]}]},
    ],
    ids=["birth date and sex", "national id only", "name only"],
)
def test_a_bulk_export_with_two_people_under_one_patient_id_is_held(tmp_path: Path, second: dict[str, Any]) -> None:
    """Review P-04-3: a bulk Patient's name and identifiers are compared before they are dropped, each identifier by
    its system: two rows under one id that differ only there are two people too."""
    sec = tmp_path / "secrets"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(KEY)
    cfg = AdapterConfig(lake_dir=tmp_path / "lake", secrets_dir=sec, site_id="T", audit_dir=tmp_path / "audit",
                        mapping_path=MAPPING)  # fmt: skip
    exp = tmp_path / "bulk"
    exp.mkdir()
    feed: dict[str, list[dict[str, Any]]] = {
        "Patient": [
            {
                "resourceType": "Patient",
                "id": "p1",
                "gender": "female",
                "birthDate": "1971-03-01",
                "identifier": [
                    {"system": "urn:example:mrn", "value": "p1"},
                    {"system": _NATIONAL, "value": "Z00000001"},
                ],
                "name": [{"use": "official", "family": "Patient", "given": ["Synthetic"]}],
            },
            {
                "resourceType": "Patient",
                "id": "p1",
                "gender": "female",
                "birthDate": "1971-03-01",
                "identifier": [
                    {"system": "urn:example:mrn", "value": "p1"},
                    {"system": _NATIONAL, "value": "Z00000001"},
                ],
                "name": [{"use": "official", "family": "Patient", "given": ["Synthetic"]}],
                **second,
            },
            {"resourceType": "Patient", "id": "p2", "gender": "male", "birthDate": "1980-01-01"},
        ],
        "Encounter": [
            {"resourceType": "Encounter", "id": "e1", "status": "finished", "subject": {"reference": "Patient/p1"}},
            {"resourceType": "Encounter", "id": "e2", "status": "finished", "subject": {"reference": "Patient/p2"}},
        ],
    }
    for rtype, items in feed.items():
        (exp / f"{rtype}.ndjson").write_text("\n".join(json.dumps(r) for r in items) + "\n", encoding="utf-8")
    rep = run_ingest(cfg, "fhir_bulk", str(exp), snapshot=NEXT, load_fhir=False, rebuild_lake=False, validate=False)
    assert rep.passed and not rep.held, rep.errors
    said = json.loads((snapshot_dir(cfg.lake_dir, NEXT) / IDENTITY_CONFLICT).read_text())
    p1 = bulk_id(KEY, "Patient", "p1")
    assert said["tonight"] == [p1] and said["records"] == {"Encounter": 1, "Patient": 2}
    assert rep.counts.get("Encounter") == 2  # the whole export was read
    folder = snapshot_dir(cfg.lake_dir, NEXT)
    assert [r["id"] for r in read_type(folder, "Patient")] == [bulk_id(KEY, "Patient", "p2")]
    assert [r["subject"]["reference"] for r in read_type(folder, "Encounter")] == [
        f"Patient/{bulk_id(KEY, 'Patient', 'p2')}"
    ]  # the unaffected patient's new encounter is served; p1's records are held


def test_a_bulk_patient_sent_twice_as_one_person_is_no_conflict(tmp_path: Path) -> None:
    """Review P-04-3: the added fields hold nothing for one person sent twice, nor for a value one row leaves out."""
    sec = tmp_path / "secrets"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(KEY)
    cfg = AdapterConfig(lake_dir=tmp_path / "lake", secrets_dir=sec, site_id="T", audit_dir=tmp_path / "audit",
                        mapping_path=MAPPING)  # fmt: skip
    exp = tmp_path / "bulk"
    exp.mkdir()
    one = {"resourceType": "Patient", "id": "p1", "gender": "female", "birthDate": "1971-03-01",
           "identifier": [{"system": _NATIONAL, "value": "Z00000001"}],
           "name": [{"use": "official", "family": "Patient", "given": ["Synthetic"]}]}  # fmt: skip
    (exp / "Patient.ndjson").write_text(
        "\n".join(json.dumps(r) for r in (one, one, {"resourceType": "Patient", "id": "p1"})) + "\n", encoding="utf-8"
    )
    rep = run_ingest(cfg, "fhir_bulk", str(exp), snapshot=NEXT, load_fhir=False, rebuild_lake=False, validate=False)
    assert rep.passed, rep.errors
    assert not (snapshot_dir(cfg.lake_dir, NEXT) / IDENTITY_CONFLICT).exists()
