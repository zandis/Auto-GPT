"""E2E P-03: a night killed inside its FHIR load leaves no half-published clinical store.

The journey: a night is published; the next night's FHIR load is killed part way (the adapter's memory cap, a power
cut: no Python handler runs), so the FHIR store holds part of that night while the lake's CURRENT never moved. What
the kill leaves on disk is all the next run has. The next ingest or publish puts the FHIR store back to the served
night before it reads anything, and the killed night, run again, is published from its FHIR step. A real lake and
PostgreSQL, synthetic rows."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from adapter import publish as publish_mod
from adapter.ndjson import snapshot_dir
from adapter.pipeline import run_ingest

from tests.unit.test_dataflow_lake_p0 import _Lakes, _row
from tests.unit.test_t723_publish_night import N1, N2, Fhir, _fhir_cfg, _night, _record


def test_a_night_killed_in_its_fhir_load_is_put_back_to_the_served_night(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    fhir = Fhir(monkeypatch)
    assert run_ingest(
        cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1, validate=False
    ).passed
    killed_at = tmp_path / "disk-at-the-kill"

    def killed_in_the_load(
        base: str, folder: Path, ledger: Path, previous: Path | None = None, full: bool = False, back: bool = False
    ) -> tuple[int, int]:
        if folder.name == N2 and not back:
            fhir.calls.append(folder.name)
            fhir.holds = f"part of {N2}"  # Patient and Condition in, part of the Observations
            shutil.copytree(cfg.lake_dir, killed_at, symlinks=True)  # the disk as a kill inside the load leaves it
            raise RuntimeError("the test goes on from the copy")
        return fhir(base, folder, ledger, previous, full=full, back=back)

    monkeypatch.setattr(publish_mod, "sync_snapshot", killed_in_the_load)
    night2 = _night(tmp_path, "n2", [_row("D1", "2026-09-01"), _row("D2", "2026-10-01")], ["10000001"])
    run_ingest(cfg, "csv", night2, snapshot=N2, validate=False)
    shutil.rmtree(cfg.lake_dir)
    killed_at.rename(cfg.lake_dir)  # the box as the kill left it
    monkeypatch.setattr(publish_mod, "sync_snapshot", fhir)  # the process that comes next loads as usual
    fhir.holds = f"part of {N2}"
    folder = snapshot_dir(cfg.lake_dir, N2)
    assert lakes.lake.current() == N1 and not (folder / "passed.json").exists()
    assert _record(folder)["fhir"] == "loading"  # the record says the load began and never ended

    fhir.calls, fhir.back, fhir.full = [], [], []
    assert publish_mod.recover_all(cfg) == [N2]
    assert fhir.holds == N1 and fhir.calls == [N1] and fhir.back == [True] and fhir.full == [True]
    assert _record(folder)["fhir"] == "pending" and lakes.lake.current() == N1  # one night, in both stores
    assert publish_mod.recover_all(cfg) == []  # nothing left to undo

    # the killed night run again is published, its FHIR load from the start
    assert run_ingest(cfg, "csv", night2, snapshot=N2, validate=False).passed
    assert lakes.lake.current() == N2 and fhir.holds == N2
    assert set(_record(folder).values()) <= {"done", "skipped"}


def test_the_next_ingest_undoes_a_killed_load_before_it_reads_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same disk state, and the next thing that runs is an ingest that is held at the gate: the FHIR store is
    still put back to the served night, it does not wait for a night that publishes."""
    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    fhir = Fhir(monkeypatch)
    assert run_ingest(
        cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1, validate=False
    ).passed
    folder = snapshot_dir(cfg.lake_dir, N1).parent / N2
    shutil.copytree(snapshot_dir(cfg.lake_dir, N1), folder)
    (folder / "passed.json").unlink()
    publish_mod._write_record(folder, {"snapshot": N2, "fingerprint": "", "steps": {"build": "skipped",
                              "omop": "skipped", "fhir": "loading", "lake": "pending", "pidmap": "pending"}})  # fmt: skip
    fhir.holds, fhir.calls = f"part of {N2}", []
    rep = run_ingest(cfg, "csv", _night(tmp_path, "empty", []), snapshot=N2, validate=False)
    assert not rep.passed and lakes.lake.current() == N1
    assert fhir.calls[:1] == [N1] and fhir.holds == N1
