"""NEW-B-10 (D-531): the publish promotes the generation it built, or nothing.

T-723 builds the night's lake without serving it and promotes it as the last step; T-724 made every build a
generation. Between the two steps the date could be built again by something else (a rebuild asked for by hand),
and the promotion served "whatever the date names": a generation the publish's other stores were never loaded
beside. The build's answer now names its generation, ``publish.json`` keeps it, and the promotion names it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adapter.ndjson import snapshot_dir
from adapter.pipeline import AdapterConfig, run_ingest
from embed_service.embedder import HashEmbedder
from tb_contracts import RebuildResult

from tests.unit.test_dataflow_lake_p0 import _cfg, _Lakes, _row
from tests.unit.test_t723_publish_night import N1, N2, _night


def _two_step(cfg: AdapterConfig, lakes: _Lakes, between: Any = None) -> list[tuple[str, str | None]]:
    """The lake in two steps, as the adapter service wires it; ``between`` runs after the build, before the
    promotion. Returns the list the promotions are written to: ``(night, generation asked for)``."""
    asked: list[tuple[str, str | None]] = []

    def build(snap: str, nd: Path) -> RebuildResult:
        lakes.calls.append(snap)
        st = lakes.lake.rebuild(snap, HashEmbedder(), nd, promote=False, check=True)
        return RebuildResult(snapshot=st.snapshot, tables=st.tables, chunks=st.chunks, embedded_new=st.embedded_new,
                             seconds=st.seconds, generation=st.generation)  # fmt: skip

    def promote(snap: str, generation: str | None = None) -> bool:
        if between is not None:
            between(snap)
        asked.append((snap, generation))
        return lakes.lake.promote_built(snap, generation)

    cfg.build, cfg.promote = build, promote
    return asked


def _record(folder: Path) -> dict[str, Any]:
    body: dict[str, Any] = json.loads((folder / "publish.json").read_text(encoding="utf-8"))
    return body


def test_the_publish_records_its_generation_and_the_promotion_names_it(tmp_path: Path) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    asked = _two_step(cfg, lakes)
    rep = run_ingest(cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1,
                     load_fhir=False, validate=False)  # fmt: skip
    assert rep.passed and lakes.lake.current() == N1
    assert asked == [(N1, f"{N1}.g1")]
    assert _record(snapshot_dir(cfg.lake_dir, N1))["lake_generation"] == f"{N1}.g1"


def test_a_date_built_again_before_the_promotion_is_not_served_and_the_next_run_builds_again(tmp_path: Path) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    again: list[str] = []

    def someone_else(snap: str) -> None:  # a rebuild of the date by hand, between the publish's two steps
        if snap == N2 and not again:
            again.append(lakes.lake.rebuild(snap, HashEmbedder(), promote=False, check=True).generation)

    asked = _two_step(cfg, lakes, someone_else)
    assert run_ingest(cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1,
                      load_fhir=False, validate=False).passed  # fmt: skip
    night2 = _night(tmp_path, "n2", [_row("D1", "2026-09-01"), _row("D2", "2026-10-01")])
    rep = run_ingest(cfg, "csv", night2, snapshot=N2, load_fhir=False, validate=False)
    folder = snapshot_dir(cfg.lake_dir, N2)
    assert again == [f"{N2}.g2"] and asked[-1] == (N2, f"{N2}.g1")
    assert not rep.passed and lakes.lake.current() == N1  # the other generation is not served
    assert any("built again" in e for e in rep.errors or []), rep.errors
    rec = _record(folder)
    assert rec["steps"]["build"] == "pending" and rec["steps"]["lake"] == "failed" and "lake_generation" not in rec
    # the same night run again: built again (generation 3: the publish's own), promoted by that name, served
    rep = run_ingest(cfg, "csv", night2, snapshot=N2, load_fhir=False, validate=False)
    assert rep.passed and lakes.lake.current() == N2 and asked[-1] == (N2, f"{N2}.g3")
    assert _record(folder)["lake_generation"] == f"{N2}.g3"


def test_a_build_step_that_names_no_generation_promotes_as_before(tmp_path: Path) -> None:
    """A lake step from before this card (its answer has no generation): the promotion is asked without one."""
    from tests.unit.test_t723_publish_night import _two_step as old_two_step

    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    old_two_step(cfg, lakes)
    rep = run_ingest(cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1,
                     load_fhir=False, validate=False)  # fmt: skip
    assert rep.passed and lakes.lake.current() == N1
    assert "lake_generation" not in _record(snapshot_dir(cfg.lake_dir, N1))


def test_a_rebuild_by_hand_that_promoted_is_not_taken_for_the_publishs_own_promotion(tmp_path: Path) -> None:
    """Review MED-1: the other rebuild promoted (the lake's default). CURRENT names the night, but not this
    publish's generation: the night does not pass; run again, it builds and serves its own."""
    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    again: list[str] = []

    def someone_else(snap: str) -> None:
        if snap == N2 and not again:
            again.append(lakes.lake.rebuild(snap, HashEmbedder()).generation)  # promote: the default

    _two_step(cfg, lakes, someone_else)
    assert run_ingest(cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1,
                      load_fhir=False, validate=False).passed  # fmt: skip
    night2 = _night(tmp_path, "n2", [_row("D1", "2026-09-01"), _row("D2", "2026-10-01")])
    rep = run_ingest(cfg, "csv", night2, snapshot=N2, load_fhir=False, validate=False)
    folder = snapshot_dir(cfg.lake_dir, N2)
    assert lakes.lake.current() == N2 and lakes.lake.generation(N2) == f"{N2}.g2" == again[0]
    assert not rep.passed and not (folder / "passed.json").exists()
    assert any("this publish did not build" in e for e in rep.errors or []), rep.errors
    rec = _record(folder)
    assert rec["steps"]["lake"] == "failed" and "lake_generation" not in rec
    rep = run_ingest(cfg, "csv", night2, snapshot=N2, load_fhir=False, validate=False)  # the served night, again
    assert rep.passed and lakes.lake.current() == N2 and lakes.lake.generation(N2) == f"{N2}.g3"


def test_over_http_the_lakes_reason_reaches_the_report(tmp_path: Path, monkeypatch: Any) -> None:
    """Review MED-2: the client's error is "409 Conflict for url ..."; the report carries the lake's own words."""
    from fastapi.testclient import TestClient
    from lake import app as lake_app

    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    monkeypatch.setattr(lake_app, "lake", lambda: lakes.lake)
    http = TestClient(lake_app.app)
    again: list[str] = []

    def build(snap: str, nd: Path) -> RebuildResult:
        st = lakes.lake.rebuild(snap, HashEmbedder(), nd, promote=False, check=True)
        return RebuildResult(snapshot=st.snapshot, tables=st.tables, chunks=st.chunks, embedded_new=st.embedded_new,
                             seconds=st.seconds, generation=st.generation)  # fmt: skip

    def promote(snap: str, generation: str | None = None) -> bool:
        if snap == N2 and not again:
            again.append(lakes.lake.rebuild(snap, HashEmbedder(), promote=False, check=True).generation)
        resp = http.post("/promote", json={"snapshot": snap, **({"generation": generation} if generation else {})})
        resp.raise_for_status()
        return bool(resp.json()["promoted"])

    cfg.build, cfg.promote = build, promote
    assert run_ingest(cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1,
                      load_fhir=False, validate=False).passed  # fmt: skip
    night2 = _night(tmp_path, "n2", [_row("D1", "2026-09-01"), _row("D2", "2026-10-01")])
    rep = run_ingest(cfg, "csv", night2, snapshot=N2, load_fhir=False, validate=False)
    assert not rep.passed and lakes.lake.current() == N1
    assert any("built again since" in e and f"{N2}.g1" in e for e in rep.errors or []), rep.errors
    assert _record(snapshot_dir(cfg.lake_dir, N2))["steps"]["build"] == "pending"


# ------------------------------------------------------------------------- each state change, interrupted once
class _Killed(BaseException):
    """The process dies here (not an Exception: nothing on the way out may catch it as a step's failure)."""


def test_a_publish_killed_between_the_build_and_the_promotion_promotes_its_own_generation_after_a_restart(
    tmp_path: Path,
) -> None:
    import pytest

    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    die = [True]

    def killed_once(snap: str) -> None:
        if die[0]:
            die[0] = False
            raise _Killed

    asked = _two_step(cfg, lakes, killed_once)
    night = _night(tmp_path, "n1", [_row("D1", "2026-09-01")])
    with pytest.raises(_Killed):
        run_ingest(cfg, "csv", night, snapshot=N1, load_fhir=False, validate=False)
    folder = snapshot_dir(cfg.lake_dir, N1)
    rec = _record(folder)
    assert rec["steps"]["build"] == "done" and rec["lake_generation"] == f"{N1}.g1" and lakes.lake.current() is None
    builds = list(lakes.calls)
    rep = run_ingest(cfg, "csv", night, snapshot=N1, load_fhir=False, validate=False)  # the restart: the same night
    assert rep.passed and lakes.lake.current() == N1
    assert lakes.calls == builds and asked == [(N1, f"{N1}.g1")]  # not built again; promoted by the recorded name


def test_a_generation_file_without_its_record_is_never_the_dates_and_is_swept(tmp_path: Path) -> None:
    """A swap killed between the generation's file and its record (the file is moved in first)."""
    import shutil

    from lake.store import Lake

    from tests.unit.test_snapshot_holds import NIGHT, TZ
    from tests.unit.test_snapshot_holds import _night as lake_night

    lake_dir = tmp_path / "lake"
    lake_night(lake_dir, NIGHT, 3)
    lake = Lake(lake_dir, TZ)
    gdir = lake_dir / "db" / "gen"
    shutil.copyfile(gdir / f"{NIGHT}.g1.duckdb", gdir / f"{NIGHT}.g2.duckdb")  # what the killed swap left
    assert lake.generation(NIGHT) == f"{NIGHT}.g1" and [g["seq"] for g in lake.generations(NIGHT)] == [1]
    assert lake.hold(NIGHT, "01JOB1", pin=True) == f"{NIGHT}.g1"  # a job pins what the date is
    lake.release("01JOB1")
    st = lake.rebuild(NIGHT, HashEmbedder())
    assert st.generation == f"{NIGHT}.g3"  # the leftover's number is not given again
    assert sorted(p.name for p in gdir.iterdir()) == [f"{NIGHT}.g3.duckdb", f"{NIGHT}.g3.json"]


def test_an_adoption_killed_between_the_link_and_the_record_is_done_again(tmp_path: Path) -> None:
    """A date built before generations gets generation 1 when a job pins it: a link, then the record."""
    import os

    from lake.store import Lake

    from tests.unit.test_snapshot_holds import NIGHT, TZ
    from tests.unit.test_snapshot_holds import _night as lake_night

    lake_dir = tmp_path / "lake"
    lake_night(lake_dir, NIGHT, 3)
    lake = Lake(lake_dir, TZ)
    gdir = lake_dir / "db" / "gen"
    for f in gdir.iterdir():
        f.unlink()  # a date from before generations
    rows = lake.query("SELECT pid FROM patient ORDER BY pid").to_pylist()
    os.link(lake_dir / "db" / f"{NIGHT}.duckdb", gdir / f"{NIGHT}.g1.duckdb")  # the link, and then the kill
    assert lake.generation(NIGHT) is None  # a file without a record names nothing
    gen = lake.hold(NIGHT, "01JOB1", pin=True)
    assert gen == f"{NIGHT}.g2"  # adopted again under the next number; the leftover's is not reused
    assert lake.query("SELECT pid FROM patient ORDER BY pid", snapshot=gen).to_pylist() == rows


def test_a_swap_killed_before_the_sidecar_is_seen_by_verify_and_mended_by_the_next_rebuild(tmp_path: Path) -> None:
    from lake.store import Lake

    from tests.unit.test_snapshot_holds import NIGHT, TZ
    from tests.unit.test_snapshot_holds import _night as lake_night

    lake_dir = tmp_path / "lake"
    lake_night(lake_dir, NIGHT, 3)
    lake = Lake(lake_dir, TZ)
    assert lake.verify(NIGHT) == []
    side = lake_dir / "db" / f"{NIGHT}.duckdb.sha256"
    old = side.read_text(encoding="utf-8")
    lake.put_site({"Patient": [{"resourceType": "Patient", "id": "site-001", "gender": "male"}]})

    import lake.store as store

    real = store.write_sidecar

    def die(path: Path, digest: str | None = None) -> None:
        if path.name == f"{NIGHT}.duckdb":
            raise _Killed
        real(path, digest)

    store.write_sidecar = die  # type: ignore[assignment]
    try:
        import pytest

        with pytest.raises(_Killed):
            lake.rebuild(NIGHT, HashEmbedder())
    finally:
        store.write_sidecar = real
    assert side.read_text(encoding="utf-8") == old and lake.generation(NIGHT) == f"{NIGHT}.g2"  # the alias moved
    assert lake.verify(NIGHT) != []  # the date's file is not what its sidecar says: seen, never served as verified
    assert lake.rebuild(NIGHT, HashEmbedder()).generation == f"{NIGHT}.g3" and lake.verify(NIGHT) == []
