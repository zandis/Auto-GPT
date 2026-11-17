"""V-1: the search logic of ``tools/erasure_reach.py`` on fakes (no database, no box): one probe per form.

The tool must find a marker value however a store writes it, name the store as the erasure registry does, say
"error" (never "clean") when it could not read a store, read the FHIR store's answers right, refuse a live run that
searched nothing, and keep its generated blocks equal to the registry and the record. Synthetic values only."""

from __future__ import annotations

import base64
import bz2
import gzip
import hashlib
import json
import urllib.parse
import zipfile
from pathlib import Path

import duckdb
import pytest
from tb_common import erasure

from tools import erasure_reach as er

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "plan" / "measurements" / "erasure-reach-2026-11-17.md"
RECORD = ROOT / "docs" / "plan" / "measurements" / "erasure-reach-2026-11-17" / "reach.json"
PID = "0123456789abcdeffedcba9876543210"
M = er.Marker(pid=PID, chart="77770727", name="假名測試甲", dob="1937-07-27",
              national_id="Z300072701", person_ids=(4242,))  # fmt: skip


def _hit(data: bytes) -> set[str]:
    return set(er.search_bytes(data, M))


# ------------------------------------------------------------------------------------------------ one probe per form
def test_plain_and_json_escaped() -> None:
    assert "name" in _hit(json.dumps({"n": M.name}).encode())  # \\u escapes
    assert "name" in _hit(json.dumps({"n": M.name}, ensure_ascii=False).encode())
    assert _hit(b"nothing here") == set()


def test_backslashes_doubled_as_a_table_row_reads() -> None:
    row_text = json.dumps(M.name)[1:-1].replace("\\", "\\\\")
    assert "name" in _hit(f'("{{\\"n\\": \\"{row_text}\\"}}")'.encode())


def test_percent_encoded() -> None:
    assert "name" in _hit(("/search?q=" + urllib.parse.quote(M.name, safe="")).encode())


def test_base64_of_the_value_and_inside_a_base64_blob() -> None:
    assert "pid" in _hit(base64.b64encode(PID.encode()))
    blob = base64.b64encode(f"note of chart {M.chart} for {M.name}".encode()).decode()
    got = _hit(json.dumps({"content": [{"attachment": {"data": blob}}]}).encode())
    assert {"chart", "name"} <= got  # a FHIR attachment's base64 text is decoded


def test_full_width_digits() -> None:
    assert "chart" in _hit(M.chart.translate(er._FULL).encode())


def test_utf16() -> None:
    assert {"pid", "name"} <= _hit(f"{PID} {M.name}".encode("utf-16-le"))


def test_the_hashes_the_product_makes_of_a_pseudonym() -> None:
    assert _hit(er.recall_hash(PID).encode()) >= {"pid_hash"}
    assert "pid_hash" in _hit(hashlib.sha256(PID.encode()).hexdigest().encode())
    assert "twpas_id" in _hit(f'{{"id": "{er.twpas_ids(PID)[0]}"}}'.encode())
    assert er.twpas_ids(PID)[0] == "claim-" + hashlib.sha256((PID + "claim").encode()).hexdigest()[:16]


def test_a_person_id_only_as_a_whole_value_of_a_person_key() -> None:
    assert "person_id" in _hit(b'{"person_id": 4242}')
    assert "person_id" not in _hit(b'{"count": 4242, "person_id": 42420}')


def test_log_text_is_searched_in_the_same_forms() -> None:
    line = json.dumps({"msg": f"seen {M.name}"})  # a JSON log line escapes the name
    assert "name" in er.search_text(line, M)


def test_compressed_files_are_unpacked(tmp_path: Path) -> None:
    text = f"pid {PID}".encode()
    (tmp_path / "a.gz").write_bytes(gzip.compress(text))
    (tmp_path / "b.bz2").write_bytes(bz2.compress(text))
    with zipfile.ZipFile(tmp_path / "c.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("inner.txt", text)
    for name in ("a.gz", "b.bz2", "c.zip"):
        hits, err = er.search_file(tmp_path / name, M)
        assert "pid" in hits and err is None, name


def test_a_large_file_is_read_in_overlapping_pieces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(er, "CHUNK", 64)
    f = tmp_path / "big.bin"
    f.write_bytes(b"x" * 50 + PID.encode() + b"y" * 300)  # the value crosses the first piece's end
    hits, err = er.search_file(f, M)
    assert "pid" in hits and err is None


def test_duckdb_and_parquet_rows_with_dates_and_person_ids(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    (root / "db").mkdir(parents=True)
    (root / "parquet").mkdir()
    con = duckdb.connect(str(root / "db" / "x.duckdb"))
    con.execute("CREATE TABLE note (pid VARCHAR, text VARCHAR, born DATE, person_id BIGINT, n BIGINT)")
    con.execute("INSERT INTO note VALUES (?, ?, ?, 4242, 4242)", [PID, f"seen: {M.name}", M.dob])
    con.execute(f"COPY note TO '{root / 'parquet' / 'note.parquet'}' (FORMAT PARQUET)")
    con.close()
    found = er.search_tree(root, M, er.lake_key)
    for k in ("lake:db", "lake:parquet"):
        assert {"pid", "name", "dob", "person_id"} <= set(found.stores[k]), k
    assert not found.errors


def test_a_file_that_does_not_open_is_an_error_never_clean(tmp_path: Path) -> None:
    (tmp_path / "db").mkdir()
    (tmp_path / "db" / "broken.duckdb").write_bytes(b"\x00\x00\x00\x00DUCKnot a database")
    found = er.search_tree(tmp_path, M, er.lake_key)
    assert "lake:db" in found.errors
    row = er.reach_rows(None, found)[0]
    assert er.verdict_of(row) == "error"


# ------------------------------------------------------------------------------------------------ names and verdicts
def test_the_registry_names_and_classes() -> None:
    assert er.registry_class("orch.pool") == erasure.ERASE
    assert er.registry_class("trace.traces") == "owed"
    assert er.registry_class("optout.optout_events") == erasure.KEEP
    assert er.registry_class("mail.sent") == erasure.NO_PATIENT_DATA
    assert er.registry_class("lake:gates") == "unlisted"
    assert er.registry_key("omop.note_y2026") == "omop.note"  # a yearly partition is its parent's
    assert er.registry_key("omop.nothing_y2026") == "omop.nothing_y2026"
    assert er.registry_key("provenance.model_uses") == "outside:provenance_index"


def _found(stores: dict[str, dict[str, int]], searched: set[str]) -> er.Found:
    f = er.Found()
    for k in searched:
        f.seen(k)
    for k, hits in stores.items():
        for kind, n in hits.items():
            f.add(k, kind, n)
    return f


def test_a_row_s_verdict_and_partitions_fold() -> None:
    before = _found({"orch.pool": {"pid": 1}, "trace.traces": {"pid": 1}, "optout.optout_events": {"pid": 1},
                     "mail.sent": {"pid": 1}, "lake:gates": {"pid": 1}, "omop.note_y2026": {"pid": 1}},
                    {"site.notify_log"})  # fmt: skip
    after = _found({"trace.traces": {"pid": 1}, "optout.optout_events": {"pid": 1}, "mail.sent": {"pid": 1},
                    "lake:gates": {"pid": 1}}, {"orch.pool", "site.notify_log", "omop.note_y2026"})  # fmt: skip
    rows = {r["store"]: r["verdict"] for r in er.reach_rows(before, after, ["outside:fhir_store"])}
    assert rows == {"orch.pool": "clean", "trace.traces": "owed", "optout.optout_events": "kept",
                    "mail.sent": "leak", "lake:gates": "unlisted", "site.notify_log": "not_reached",
                    "outside:fhir_store": "not_searched", "omop.note": "clean"}  # fmt: skip
    no_before = {r["store"]: r["verdict"] for r in er.reach_rows(None, after)}
    assert no_before["orch.pool"] == "not_reached"  # absence with no before-search proves nothing


# ------------------------------------------------------------------------------------------------ the FHIR store
def test_the_fhir_store_is_read_by_its_answers_and_its_history() -> None:
    asked: list[str] = []

    def gone(url: str) -> tuple[int, bytes]:
        asked.append(url)
        if url.endswith(f"Patient/{PID}"):
            return 410, b""
        return 200, json.dumps({"resourceType": "Bundle", "total": 0}).encode()

    f = er.search_fhir("http://fhir.test/fhir/", M, gone)
    assert f.searched == {"outside:fhir_store"} and f.stores == {} and not f.errors
    assert f"http://fhir.test/fhir/Patient/{PID}/_history" in asked

    def deleted_with_history(url: str) -> tuple[int, bytes]:
        if url.endswith("/_history"):
            return 200, json.dumps({"resourceType": "Bundle", "entry": [{"resource": {"id": PID}}]}).encode()
        if url.endswith(f"Patient/{PID}"):
            return 410, b""
        return 200, json.dumps({"resourceType": "Bundle", "total": 0}).encode()

    f = er.search_fhir("http://fhir.test/fhir", M, deleted_with_history)
    assert f.stores["outside:fhir_store"]["pid"] >= 1  # a 410 is not gone while the history remains

    def down(url: str) -> tuple[int, bytes]:
        raise ConnectionError("refused")

    f = er.search_fhir("http://fhir.test/fhir", M, down)
    assert er.verdict_of(er.reach_rows(None, f)[0]) == "error"


# ------------------------------------------------------------------------------------------------ live mode
def test_live_mode_fails_when_it_searched_nothing(tmp_path: Path) -> None:
    out = er.live(M, {})
    assert out["ok"] is False and set(out["not_searched_places"]) == set(er.PLACES)
    out = er.live(M, {}, allow=er.PLACES)
    assert out["ok"] is True  # every place named as not searched on purpose


def test_live_mode_calls_clean_only_what_the_before_search_found(tmp_path: Path) -> None:
    obj = tmp_path / "obj" / "outputs" / "J1"
    obj.mkdir(parents=True)
    (obj / "list.csv").write_text(f"pid\n{PID}\n", encoding="utf-8")
    env = {"ERASURE_REACH_OBJECTS_DIR": str(tmp_path / "obj")}
    before, _ = er.live_found(M, env)
    allow = [p for p in er.PLACES if p != "objects"]
    assert {r["store"]: r["verdict"] for r in er.live(M, env, allow=allow)["stores"]}["objects:outputs"] == "owed"
    (obj / "list.csv").write_text("pid\n", encoding="utf-8")
    rows = {r["store"]: r["verdict"] for r in er.live(M, env, before=before, allow=allow)["stores"]}
    assert rows["objects:outputs"] == "clean"
    rows = {r["store"]: r["verdict"] for r in er.live(M, env, allow=allow)["stores"]}
    assert rows["objects:outputs"] == "not_reached"


def test_live_mode_prints_no_value(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                   monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    marker = tmp_path / "marker.json"
    marker.write_text(json.dumps({"pid": PID, "name": M.name, "chart": M.chart}), encoding="utf-8")
    (tmp_path / "lake" / "ndjson").mkdir(parents=True)
    (tmp_path / "lake" / "ndjson" / "P.ndjson").write_text(json.dumps({"id": PID}), encoding="utf-8")
    for k in ("TB_DB_URL", "TB_OMOP_DB_URL", "ERASURE_REACH_FHIR_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ERASURE_REACH_LAKE_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("ERASURE_REACH_FHIR_TOKEN", "not-a-real-token")
    assert er.main(["live", "--marker", str(marker), "--before-out", str(tmp_path / "b.json")]) == 0
    rc = er.main(
        ["live", "--marker", str(marker), "--before", str(tmp_path / "b.json"), "--out", str(tmp_path / "reach.json")]
        + [f"--allow-not-searched={p}" for p in er.PLACES if p != "lake"]
    )
    text = capsys.readouterr().out + (tmp_path / "reach.json").read_text(encoding="utf-8")
    assert rc == 1  # an owed store holds the patient
    for secret in (PID, M.name, M.chart, "not-a-real-token"):
        assert secret not in text


# ------------------------------------------------------------------------------------------------ the page
def test_the_owed_table_matches_the_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = er.owed_rows()
    assert {r["store"] for r in rows} == {k for k, _c, _w in erasure.owed()}
    assert all(r["size"] in ("small", "medium", "large") and r["lane"] for r in rows)
    monkeypatch.delitem(er.COSTS, "trace.traces")
    with pytest.raises(SystemExit, match="owed and not costed"):
        er.owed_rows()


def test_the_page_s_generated_blocks_are_current(capsys: pytest.CaptureFixture[str]) -> None:
    assert er.main(["check", str(PAGE), "--record", str(RECORD)]) == 0, capsys.readouterr().out
    assert er.check_page("no blocks", None) == ["owed"]
