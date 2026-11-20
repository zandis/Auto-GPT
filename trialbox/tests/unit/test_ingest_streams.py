"""The night's ingest and the lake rebuild in streams (T-692, D-473; scale review 2026-11-11 F-05).

At 50,000 patients the adapter needed 16.5 GB and the lake 17 GB against caps of 6 and 8 GB: the merge held the whole
previous snapshot of a type in a dict, the CSV reader held a whole table as row dicts, the rebuild parsed every line
into one list before it built one Arrow table. Each path is measured here at a small size N and at 4N: the peak of
Python's own allocations (``tracemalloc``) may not grow with the patient count. The outputs stay the same bytes and
rows as the code they replace. Synthetic patients only."""

from __future__ import annotations

import csv
import hashlib
import json
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from adapter import ndjson
from adapter.sources.csv.source import CsvSource
from tb_common import id_rule

from tools.trialbox import memcaps

TZ = "Asia/Taipei"
NIGHT = "2026-10-04"
# a peak at 4N under this multiple of the peak at N (plus a little for the interpreter's own noise) does not grow with
# the patient count; holding everything grows about 4x
BOUND = 1.6
SLACK = 256 * 1024


def _peak(fn: Callable[[], Any]) -> int:
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        fn()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


_canon = memcaps._canon
_obs = memcaps.observation
_resources = memcaps.synthetic
_write_ndjson = memcaps.write_ndjson


# ------------------------------------------------------------------------------------------------ the merge


def _merge_night(tmp: Path, n: int) -> int:
    """A delta night of 50 changed results and 5 deletes over a previous snapshot of ``n`` patients."""
    base = tmp / f"base-{n}"
    _write_ndjson(base, n)
    fresh = {"Observation": [_obs(i, 0, 9.9) for i in range(0, 50)]}
    dead = {"Observation": [f"obs-{i:06d}-01" for i in range(5)]}
    out = tmp / f"out-{n}"
    return _peak(lambda: ndjson.write_snapshot(out, fresh, base, dead))


def test_the_merge_does_not_hold_the_previous_snapshot(tmp_path: Path) -> None:
    small, large = _merge_night(tmp_path, 400), _merge_night(tmp_path, 1600)
    assert large < small * BOUND + SLACK, f"merge peak {small} B at N, {large} B at 4N"


def test_the_merge_writes_the_same_bytes_as_a_merge_in_memory(tmp_path: Path) -> None:
    base = tmp_path / "base"
    _write_ndjson(base, 60)
    fresh = {"Observation": [_obs(i, 0, 9.9) for i in range(0, 60, 7)] + [_obs(3, 0, 7.7)], "Condition": []}
    fresh["Observation"].append(_obs(999, 0, 1.0))  # a new patient's result
    dead = {"Observation": ["obs-000001-01", "obs-000003-00", "nobody"], "Patient": ["syn-000002"]}
    counts = ndjson.write_snapshot(tmp_path / "out", fresh, base, dead)
    # the reference: the previous snapshot in a dict, the night's records over it, the tombstones out
    want: dict[str, dict[str, Any]] = {}
    for f in sorted(base.glob("*.ndjson")):
        want[f.stem] = {r["id"]: r for r in ndjson.read_type(base, f.stem)}
    new_ids = {r["id"] for r in fresh["Observation"]}
    for rtype, ids in dead.items():
        for rid in ids:
            if rid not in new_ids:
                want.get(rtype, {}).pop(rid, None)
    for r in fresh["Observation"]:
        want["Observation"][r["id"]] = r
    for rtype, rows in want.items():
        body = "".join(_canon(rows[k]) + "\n" for k in sorted(rows))
        assert (tmp_path / "out" / f"{rtype}.ndjson").read_text(encoding="utf-8") == body, rtype
        assert counts[rtype] == len(rows)
    assert counts["Condition"] == 0 and (tmp_path / "out" / "Condition.ndjson").read_text() == ""
    tomb = json.loads((tmp_path / "out" / ndjson.TOMBSTONES).read_text(encoding="utf-8"))
    assert tomb == {"Observation": ["obs-000001-01"], "Patient": ["syn-000002"]}  # obs-3-00 was sent again


def test_a_spooled_night_is_sorted_in_runs_and_the_last_record_of_an_id_wins(tmp_path: Path) -> None:
    sp = ndjson.Spool(tmp_path / "spool", run_bytes=2048)
    sent = [_obs(i % 40, 0, float(i)) for i in range(200)]  # each id five times: the last one wins
    for r in sent:
        sp.add(r)
    assert sp.counts() == {"Observation": 200}
    counts = ndjson.write_snapshot(tmp_path / "out", sp, None)
    last = {r["id"]: r for r in sent}
    body = "".join(_canon(last[k]) + "\n" for k in sorted(last))
    assert (tmp_path / "out" / "Observation.ndjson").read_text(encoding="utf-8") == body
    assert counts == {"Observation": 40}
    sp.close()
    assert not (tmp_path / "spool").exists()


def _spooled_night(tmp: Path, n: int) -> int:
    def run() -> None:
        sp = ndjson.Spool(tmp / f"spool-{n}", run_bytes=64 * 1024)
        for r in _resources(n):
            sp.add(r)
        ndjson.write_snapshot(tmp / f"spout-{n}", sp, None)
        sp.close()

    return _peak(run)


def test_a_full_night_through_the_spool_does_not_grow_with_the_patients(tmp_path: Path) -> None:
    small, large = _spooled_night(tmp_path, 400), _spooled_night(tmp_path, 1600)
    assert large < small * BOUND + SLACK, f"spool peak {small} B at N, {large} B at 4N"


def test_the_sort_run_follows_the_memory_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_INGEST_SORT_MB", raising=False)
    monkeypatch.setattr(ndjson, "_memory_cap", lambda: 8 * 2**30)
    assert ndjson.sort_run_bytes() == 8 * 2**30 // 16
    monkeypatch.setenv("TB_INGEST_SORT_MB", "32")
    assert ndjson.sort_run_bytes() == 32 * 2**20
    monkeypatch.setenv("TB_INGEST_SORT_MB", "zero")
    with pytest.raises(ValueError, match="TB_INGEST_SORT_MB"):
        ndjson.sort_run_bytes()


# ------------------------------------------------------------------------------------------------ the CSV read


def _csv(folder: Path, n: int) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "lab.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["chart_no", "lab_code", "value", "unit", "updated_at", "note"])
        for i in range(n):
            for j in range(10):
                w.writerow([f"{i:08d}", "2160-0", f"{1 + j / 10:.1f}", "mg/dL", "2026-09-01 08:00", "腎機能 安定"])
    return folder


def _csv_read(tmp: Path, n: int) -> tuple[int, int]:
    src = CsvSource(_csv(tmp / f"csv-{n}", n))
    seen = [0]

    def run() -> None:
        for _ in src.rows("lab", "lab", None, None):
            seen[0] += 1

    return _peak(run), seen[0]


def test_the_csv_read_gives_rows_one_at_a_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tb_common import encoding

    monkeypatch.setattr(encoding, "_CHUNK", 16 * 1024)  # smaller than both files, as 1 MB is for a hospital's
    (small, n1), (large, n4) = _csv_read(tmp_path, 400), _csv_read(tmp_path, 1600)
    assert (n1, n4) == (4000, 16000)
    assert large < small * BOUND + SLACK, f"csv peak {small} B at N, {large} B at 4N"


def test_the_csv_read_gives_the_same_rows_and_still_quarantines_a_broken_file(tmp_path: Path) -> None:
    folder = _csv(tmp_path / "csv", 30)
    rows = list(CsvSource(folder).rows("lab", "lab", "updated_at", None))
    with (folder / "lab.csv").open(encoding="utf-8", newline="") as fh:
        assert rows == [dict(r) for r in csv.DictReader(fh)]
    assert CsvSource(folder).encodings == {} and len(rows) == 300
    # a broken CSV half-way: no row of it is given, and the file is quarantined as before
    src = CsvSource(folder)
    old = csv.field_size_limit(8)
    try:
        (folder / "bad.csv").write_text("a,b\n1,2\n3," + "x" * 64 + "\n", encoding="utf-8")
        assert list(src.rows("bad", "bad", None, None)) == []
    finally:
        csv.field_size_limit(old)
    assert "not a readable CSV" in (src.quarantine_reason("bad") or "")
    # a replacement character in the file: refused with its line, no row given
    (folder / "fffd.csv").write_text("a,b\n1,2\n3,�\n", encoding="utf-8")
    src = CsvSource(folder)
    assert list(src.rows("fffd", "fffd", None, None)) == []
    assert "U+FFFD" in (src.quarantine_reason("fffd") or "") and "line 3" in (src.quarantine_reason("fffd") or "")


def test_a_legacy_character_set_is_still_read(tmp_path: Path) -> None:
    folder = tmp_path / "big5"
    folder.mkdir()
    body = "chart_no,name\n" + "".join(f"{i:04d},臺灣醫院病歷資料{i}\n" for i in range(200))
    (folder / "patient.csv").write_bytes(body.encode("cp950"))
    src = CsvSource(folder, "big5")
    rows = list(src.rows("patient", "patient", None, None))
    assert len(rows) == 200 and rows[3]["name"] == "臺灣醫院病歷資料3"
    assert src.encodings["patient"] in ("big5", "cp950")


# ------------------------------------------------------------------------------------------------ the Parquet build


def _rebuild(tmp: Path, n: int) -> tuple[int, dict[str, int], str]:
    from embed_service.embedder import HashEmbedder
    from lake.store import Lake

    lake_dir = tmp / f"lake-{n}"
    _write_ndjson(lake_dir / "ndjson" / NIGHT, n)
    out: dict[str, Any] = {}

    def run() -> None:
        out["stats"] = Lake(lake_dir, TZ).rebuild(NIGHT, HashEmbedder())

    peak = _peak(run)
    lake = Lake(lake_dir, TZ)
    rows = lake.query(
        "SELECT (SELECT count(*) FROM observation) AS o, (SELECT count(*) FROM patient) AS p, "
        "(SELECT count(*) FROM document_chunk) AS c",
        [],
        NIGHT,
    ).to_pylist()[0]
    first = lake.query("SELECT oid, pid, value_num FROM observation ORDER BY oid LIMIT 3", [], NIGHT).to_pylist()
    return peak, {**rows, "chunks": out["stats"].chunks}, hashlib.sha256(json.dumps(first).encode()).hexdigest()


def test_the_parquet_build_does_not_grow_with_the_patients(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lake import store

    monkeypatch.setenv("TB_LAKE_SOURCE", "legacy")
    monkeypatch.delenv("TB_DB_URL", raising=False)
    monkeypatch.setattr(store, "INSERT_BATCH", 100)  # a batch smaller than both nights, as 4,096 is for a hospital's
    _rebuild(tmp_path, 20)  # the first build imports and caches what every later one shares: not measured
    (small, c1, h1), (large, c4, h4) = _rebuild(tmp_path, 300), _rebuild(tmp_path, 1200)
    assert c1 == {"o": 3000, "p": 300, "c": 300, "chunks": 300}
    assert c4 == {"o": 12000, "p": 1200, "c": 1200, "chunks": 1200}
    assert h1 == h4  # the first rows are the same rows whatever the size
    assert large < small * BOUND + SLACK, f"rebuild peak {small} B at N, {large} B at 4N"


def test_a_previous_snapshot_written_by_hand_out_of_order_is_still_merged(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    rows = [{"resourceType": "Condition", "id": i, "code": {"text": i}} for i in ("c3", "c1", "c2", "c1")]
    (base / "Condition.ndjson").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    id_rule.write_snapshot_record(base)  # D-1253: a snapshot of this release says its id rule
    counts = ndjson.write_snapshot(tmp_path / "out", {"Condition": [{"resourceType": "Condition", "id": "c0"}]}, base)
    got = [json.loads(x)["id"] for x in (tmp_path / "out" / "Condition.ndjson").read_text().splitlines()]
    assert got == ["c0", "c1", "c2", "c3"] and counts == {"Condition": 4}


@pytest.mark.parametrize(
    "body",
    [
        b"a,b\n1,2\n",
        "a,b\n1,腎機能 安定 透析なし\n".encode(),
        b"\xef\xbb\xbfa,b\n1,2\n",
        "a,b\n1,臺灣\n".encode("cp950"),
        "a,b\n1,é\n".encode(),  # one non-ASCII character: weighed against the legacy readings, as before
        b"a,b\n1,\xff\xfe\n",
        "a,b\n1,�\n".encode(),
        b"",
    ],
)
def test_the_chunked_character_set_check_answers_as_the_whole_file_check(tmp_path: Path, body: bytes) -> None:
    from tb_common import encoding

    f = tmp_path / "x.csv"
    f.write_bytes(body)
    try:
        want: object = encoding.decode(body, ("big5", "cp932"))[1]
    except encoding.EncodingRefused as exc:
        want = str(exc)
    try:
        got: object = encoding.file_codec(f, ("big5", "cp932"))
    except encoding.EncodingRefused as exc:
        got = str(exc)
    assert got == want


# ------------------------------------------------------------------------------------------------ a whole night

SITE_A = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_patients" / "site-a"
MAPPING = Path(__file__).resolve().parents[2] / "services" / "adapter" / "mapping" / "tw_core" / "demo_his.yaml"


def _feed(dst: Path, copies: int, only: tuple[str, ...] = ()) -> Path:
    """site-a's export ``copies`` times over, each copy its own patients (chart numbers and row ids moved)."""
    dst.mkdir(parents=True)
    for f in sorted(SITE_A.glob("*.csv")):
        if only and f.stem not in only:
            continue
        with f.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        fields = list(rows[0]) if rows else []
        with (dst / f.name).open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for k in range(1 if f.stem == "practitioner" else copies):
                for r in rows:
                    r2 = dict(r)
                    if k:
                        for col in fields:
                            if col == "mrn" and r2[col]:
                                r2[col] = str(int(r2[col]) + k * 1_000_000)
                            elif (col == fields[0] or col == "enc_no") and r2[col] and f.stem != "registry":
                                r2[col] = f"{r2[col]}x{k}"
                    w.writerow(r2)
    return dst


def _night(tmp: Path, copies: int, only: tuple[str, ...] = ()) -> tuple[int, dict[str, int]]:
    from adapter.pipeline import AdapterConfig, run_ingest

    sec = tmp / f"secrets-{copies}"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(b"k" * 32)
    cfg = AdapterConfig(lake_dir=tmp / f"lake-{copies}", secrets_dir=sec, mapping_path=MAPPING, site_id="T")
    feed = _feed(tmp / f"feed-{copies}", copies, only)
    out: dict[str, Any] = {}

    def run() -> None:
        out["rep"] = run_ingest(cfg, "csv", str(feed), snapshot=NIGHT, load_fhir=False, validate=False)

    return _peak(run), dict(out["rep"].counts)


def test_a_whole_night_does_not_grow_with_the_patients(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from adapter import ndjson as nd
    from tb_common import encoding

    # a sort run and a read size smaller than both nights, as a sixteenth of 6 GB and 1 MB are for a hospital's
    monkeypatch.setenv("TB_INGEST_SORT_MB", "1")
    monkeypatch.setattr(encoding, "_CHUNK", 16 * 1024)
    (tmp_path / "warm").mkdir()
    _night(tmp_path / "warm", 1, ("patient", "practitioner"))  # the first night imports what the others share
    (small, c1), (large, c4) = _night(tmp_path, 1), _night(tmp_path, 4)
    assert c1["Patient"] == 600 and c4["Patient"] == 2400
    assert all(c4[t] == 4 * c1[t] for t in c1 if t not in ("Practitioner", "Organization", "Location")), (c1, c4)
    assert large < small * BOUND + SLACK, f"night peak {small} B at N, {large} B at 4N"
    assert not list((tmp_path / "lake-4" / "tmp").glob("ingest-*")), "the night's spool is removed"
    assert nd.sort_run_bytes() == 2**20
