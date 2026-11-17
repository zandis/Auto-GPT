"""V-1: the search logic of ``tools/erasure_reach.py`` on fakes (no database, no box).

The tool must find a marker value however a store writes it (plain, JSON-escaped, inside a DuckDB or Parquet file, in
a gzip), name the store as the erasure registry does, read the FHIR store's answers right, and keep its costed owed
table equal to the registry's owed set. Synthetic values only."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import duckdb
import pytest
from tb_common import erasure

from tools import erasure_reach as er

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "plan" / "measurements" / "erasure-reach-2026-11-17.md"
M = er.Marker(pid="0123456789abcdeffedcba9876543210", chart="77770727", name="假名測試甲",
              dob="1937-07-27", national_id="Z300072701")  # fmt: skip


def test_a_value_is_found_plain_and_json_escaped() -> None:
    assert er.search_bytes(json.dumps({"n": M.name}).encode(), M) == {"name": 1}  # \\u escapes
    assert er.search_bytes(json.dumps({"n": M.name}, ensure_ascii=False).encode(), M) == {"name": 1}
    assert er.search_bytes(b"nothing here", M) == {}
    got = er.search_text(f"x {M.pid} y {M.pid} {er.recall_hash(M.pid)}", M)
    assert got["pid"] == 2 and got["pid_hash"] == 1 and got["pid_prefix"] == 2  # the hash holds no pid


def test_files_of_every_kind_are_opened(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    (root / "db").mkdir(parents=True)
    (root / "parquet" / "snapshot=x").mkdir(parents=True)
    (root / "ndjson" / "x").mkdir(parents=True)
    (root / "clean").mkdir()
    con = duckdb.connect(str(root / "db" / "x.duckdb"))
    con.execute("CREATE TABLE note (pid VARCHAR, text VARCHAR, v FLOAT[])")
    con.execute("INSERT INTO note VALUES (?, ?, [0.1, 0.2])", [M.pid, f"seen: {M.name}"])
    con.execute(f"COPY note TO '{root / 'parquet' / 'snapshot=x' / 'note.parquet'}' (FORMAT PARQUET)")
    con.close()
    (root / "ndjson" / "x" / "Patient.ndjson.gz").write_bytes(gzip.compress(json.dumps({"id": M.pid}).encode()))
    (root / "clean" / "a.txt").write_text("no one", encoding="utf-8")
    found = er.search_tree(root, M, er.lake_key)
    assert found.searched == {"lake:db", "lake:parquet", "lake:ndjson", "lake:clean"}
    assert set(found.stores["lake:db"]) >= {"pid", "name"}
    assert set(found.stores["lake:parquet"]) >= {"pid", "name"}
    assert set(found.stores["lake:ndjson"]) == {"pid", "pid_prefix"}
    assert "lake:clean" not in found.stores
    assert found.files["lake:parquet"] == ["parquet/snapshot=x/note.parquet"]
    assert er.objects_key("outputs/J1/a.csv") == "objects:outputs"


def test_the_registry_names_and_classes() -> None:
    assert er.registry_class("orch.pool") == erasure.ERASE
    assert er.registry_class("trace.traces") == "owed"
    assert er.registry_class("optout.optout_events") == erasure.KEEP
    assert er.registry_class("mail.sent") == erasure.NO_PATIENT_DATA
    assert er.registry_class("lake:gates") == "unlisted"
    assert er.registry_key("omop.note_y2026") == "omop.note"  # a yearly partition is its parent's
    assert er.registry_key("omop.nothing_y2026") == "omop.nothing_y2026"


def _found(stores: dict[str, dict[str, int]], searched: set[str]) -> er.Found:
    f = er.Found()
    for k in searched:
        f.seen(k)
    for k, hits in stores.items():
        for kind, n in hits.items():
            f.add(k, kind, n)
    return f


def test_a_row_s_verdict() -> None:
    before = _found({"orch.pool": {"pid": 1}, "trace.traces": {"pid": 1}, "optout.optout_events": {"pid": 1},
                     "mail.sent": {"pid": 1}, "lake:gates": {"pid": 1}}, {"site.notify_log"})  # fmt: skip
    after = _found({"trace.traces": {"pid": 1}, "optout.optout_events": {"pid": 1}, "mail.sent": {"pid": 1},
                    "lake:gates": {"pid": 1}}, {"orch.pool", "site.notify_log"})  # fmt: skip
    rows = {r["store"]: er.verdict_of(r) for r in er.reach_rows(before, after, ["outside:fhir_store"])}
    assert rows == {"orch.pool": "clean", "trace.traces": "owed", "optout.optout_events": "kept",
                    "mail.sent": "leak", "lake:gates": "unlisted", "site.notify_log": "not_seeded",
                    "outside:fhir_store": "not_searched"}  # fmt: skip


def test_the_fhir_store_is_read_by_its_answers() -> None:
    asked: list[str] = []

    def gone(url: str) -> tuple[int, bytes]:
        asked.append(url)
        if url.endswith(f"Patient/{M.pid}"):
            return 410, b""
        return 200, json.dumps({"resourceType": "Bundle", "total": 0}).encode()

    f = er.search_fhir("http://fhir.test/fhir/", M, gone)
    assert f.searched == {"outside:fhir_store"} and f.stores == {} and not f.errors
    assert asked[0] == f"http://fhir.test/fhir/Patient/{M.pid}" and len(asked) == len(er.FHIR_QUERIES)

    def there(url: str) -> tuple[int, bytes]:
        if "_summary=count" in url:
            return 200, json.dumps({"resourceType": "Bundle", "total": 2}).encode()
        return 200, json.dumps({"resourceType": "Patient", "id": M.pid, "birthDate": M.dob}).encode()

    f = er.search_fhir("http://fhir.test/fhir", M, there)
    assert f.stores["outside:fhir_store"]["pid"] >= 2 and "dob" in f.stores["outside:fhir_store"]

    def down(url: str) -> tuple[int, bytes]:
        raise ConnectionError("refused")

    f = er.search_fhir("http://fhir.test/fhir", M, down)
    assert "outside:fhir_store" in f.errors
    row = er.reach_rows(None, f)[0]
    assert row["searched"] is False and er.verdict_of(row) == "not_searched"  # an error is never "clean"


def test_live_mode_says_what_it_did_not_search(tmp_path: Path) -> None:
    (tmp_path / "obj" / "outputs" / "J1").mkdir(parents=True)
    (tmp_path / "obj" / "outputs" / "J1" / "list.csv").write_text(f"pid\n{M.pid}\n", encoding="utf-8")
    out = er.live(M, {"TB_REACH_OBJECTS_DIR": str(tmp_path / "obj")})
    assert out["places"]["TB_DB_URL"] == "not set" and out["places"]["TB_REACH_FHIR_URL"] == "not set"
    rows = {r["store"]: r for r in out["stores"]}
    assert rows["objects:outputs"]["verdict"] == "owed"
    assert rows["outside:fhir_store"]["verdict"] == "not_searched"
    assert rows["orch.pool"]["verdict"] == "not_searched"


def test_live_mode_prints_no_value(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    marker = tmp_path / "marker.json"
    marker.write_text(json.dumps({"pid": M.pid, "name": M.name, "chart": M.chart}), encoding="utf-8")
    (tmp_path / "lake" / "ndjson").mkdir(parents=True)
    (tmp_path / "lake" / "ndjson" / "P.ndjson").write_text(json.dumps({"id": M.pid}), encoding="utf-8")
    import os

    old = dict(os.environ)
    try:
        os.environ["TB_REACH_LAKE_DIR"] = str(tmp_path / "lake")
        os.environ["TB_REACH_FHIR_TOKEN"] = "not-a-real-token"
        for k in ("TB_DB_URL", "TB_OMOP_DB_URL", "TB_REACH_FHIR_URL"):
            os.environ.pop(k, None)
        rc = er.main(["live", "--marker", str(marker), "--out", str(tmp_path / "reach.json")])
    finally:
        os.environ.clear()
        os.environ.update(old)
    text = capsys.readouterr().out + (tmp_path / "reach.json").read_text(encoding="utf-8")
    assert rc == 1  # an owed store holds the patient
    for secret in (M.pid, M.name, M.chart, "not-a-real-token"):
        assert secret not in text


def test_the_owed_table_matches_the_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = er.owed_rows()
    assert {r["store"] for r in rows} == {k for k, _c, _w in erasure.owed()}
    assert all(r["size"] in ("small", "medium", "large") and r["lane"] for r in rows)
    monkeypatch.delitem(er.COSTS, "trace.traces")
    with pytest.raises(SystemExit, match="owed and not costed"):
        er.owed_rows()


def test_the_page_holds_the_owed_table_of_today(capsys: pytest.CaptureFixture[str]) -> None:
    assert er.main(["owed", "--check", str(PAGE)]) == 0, capsys.readouterr().out
