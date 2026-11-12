"""NEW-B-5: what lane B's cards have to hold where they meet other cards on the train.

A restore whose service roles were not put back keeps the hold (D-522 with D-573).

On a box that runs for real (PRODUCTION, VALIDATION; an unset ``TB_ENV`` is PRODUCTION) a restore that could not put
the service roles back (``TB_DB_ROLES_CMD`` is not set) is not complete, whatever else is whole. The hold the
restore set when the restored rows were in must then stay: only a complete restore takes its own hold off."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_restore_hold import FLAG, _backup_and_restore


@pytest.mark.parametrize(("env_name", "held"), [("PRODUCTION", True), ("VALIDATION", True), ("DEV", False)])
def test_a_restore_without_its_service_roles_keeps_the_hold_on_a_real_box(
    tmp_path: Path, db_url: str, monkeypatch: Any, env_name: str, held: bool
) -> None:
    from tb_common import flags

    from tools.trialbox import backup as bk

    # everything else is whole: nothing to re-apply, the opt-out register kept
    monkeypatch.setattr(bk, "optouts_ok", lambda lost: True)
    monkeypatch.delenv("TB_DB_ROLES_CMD", raising=False)
    _out, _audit, f, priv = _backup_and_restore(tmp_path, db_url, monkeypatch, late_events=False)
    flags.clear_cache()
    assert flags.Flags(url=db_url).row(FLAG) == "released"  # the helper's own restore (DEV) was complete
    (tmp_path / "second").mkdir()
    audit2 = tmp_path / "second" / "audit"  # a fresh layout: no earlier restore's set-aside chain beside it
    audit2.mkdir()
    out = bk.restore(f, priv, env={"TB_DB_URL": db_url, "TB_ENV": env_name}, dirs={"audit": audit2}, no_copy=True)
    assert out["to_reapply"] == [] and out["service_roles"]["state"] == "not_configured"
    assert out["complete"] is (not held)
    assert out["hold"] == ("held" if held else "released")
    assert flags.Flags(url=db_url).row(FLAG) == ("held" if held else "released")


def test_a_put_back_goes_over_a_build_that_never_finished_and_never_over_a_finished_one(db_url: str) -> None:
    """T-723 and T-725 met on train 4: after a FHIR load of the newer night broke, the put-back to the served night
    was refused by the generation ledger as "an older build", and the store stayed on a part of the newer night
    while the lake served the older one. A put-back is allowed over a build that did not end, and only over that."""
    from datacore.generations import Built
    from tb_common.generation import FINISHED, Generation, OlderGeneration

    new, old = "2026-10-02", "2026-10-01"
    with Built(db_url) as b:
        b.begin("fhir", old)
        b.finish("fhir", old)
        b.begin("fhir", new)  # the newer night's load starts and breaks: never finished
        with pytest.raises(OlderGeneration):
            b.begin("fhir", old)  # an ordinary older build is still refused
        b.begin("fhir", old, back=True)
        b.finish("fhir", old)
        assert b.state("fhir") == (Generation(old), FINISHED) and b.readable("fhir", old)
        b.begin("fhir", new)
        b.finish("fhir", new)
        with pytest.raises(OlderGeneration):
            b.begin("fhir", old, back=True)  # a finished newer night is never gone back from
        assert b.state("fhir") == (Generation(new), FINISHED)


# ------------------------------------------------------------------------------------------- the review of NEW-B-5
def _nights(tmp_path: Path) -> tuple[Path, Path]:
    import json

    out = []
    for night in ("2026-10-01", "2026-10-02"):
        d = tmp_path / night
        d.mkdir()
        (d / "Patient.ndjson").write_text(json.dumps({"resourceType": "Patient", "id": night}) + "\n")
        out.append(d)
    return out[0], out[1]


def _store(monkeypatch: Any) -> list[str]:
    from adapter import load_fhir

    loaded: list[str] = []

    def load(base: str, d: Path, workers: int = 4, only: Any = None) -> int:
        loaded.append(d.name)
        return 1

    monkeypatch.setattr(load_fhir, "load_snapshot", load)
    monkeypatch.setattr(load_fhir, "delete_refs", lambda base, refs: len(refs))
    return loaded


def test_a_put_back_the_ledger_refuses_says_so(tmp_path: Path, db_url: str, monkeypatch: Any) -> None:
    """Review HIGH-1: the newer night's FHIR load FINISHED and the promotion then failed. The put-back to the
    served night is refused by the ledger (a finished newer night is not gone back from), and it used to answer
    "nothing to load": the publish took that as done and said nothing. A refused put-back is an error the publish
    reports ("fhir-store put-back failed"), so its ``fhir`` step stays failed and a resume loads the night again."""
    from adapter import load_fhir

    old, new = _nights(tmp_path)
    loaded = _store(monkeypatch)
    load_fhir.sync_snapshot("http://hapi/fhir", old, tmp_path / "ledger")
    load_fhir.sync_snapshot("http://hapi/fhir", new, tmp_path / "ledger")  # ends: the ledger says "new, finished"
    with pytest.raises(RuntimeError, match="put-back"):
        load_fhir.sync_snapshot("http://hapi/fhir", old, tmp_path / "ledger", full=True, back=True)
    assert loaded == [old.name, new.name]  # nothing was written by the refused put-back
    assert load_fhir.sync_snapshot("http://hapi/fhir", old, tmp_path / "ledger") == (0, 0)  # a late re-run: as before


def test_a_load_that_was_overtaken_fails_and_a_second_load_waits_for_the_first(
    tmp_path: Path, db_url: str, monkeypatch: Any
) -> None:
    """Review MED-1: "building" cannot tell a load that broke from one that still runs. Loads of the FHIR store
    are serial (the ledger's build lock, as for the other artefacts): a put-back waits for a load that runs. And
    a load whose ledger row was taken over meanwhile is a failed load, not a silent success."""
    import threading

    from adapter import load_fhir
    from datacore.generations import Built

    old, new = _nights(tmp_path)
    inside, go = threading.Event(), threading.Event()
    order: list[str] = []

    def load(base: str, d: Path, workers: int = 4, only: Any = None) -> int:
        if d.name == new.name:
            inside.set()
            assert go.wait(30)
        order.append(d.name)
        return 1

    monkeypatch.setattr(load_fhir, "load_snapshot", load)
    monkeypatch.setattr(load_fhir, "delete_refs", lambda base, refs: len(refs))
    load_fhir.sync_snapshot("http://hapi/fhir", old, tmp_path / "ledger")
    a = threading.Thread(target=load_fhir.sync_snapshot, args=("http://hapi/fhir", new, tmp_path / "ledger"))
    a.start()
    assert inside.wait(30)  # the newer night's load is running
    got: list[Any] = []

    def put_back() -> None:
        try:
            got.append(load_fhir.sync_snapshot("http://hapi/fhir", old, tmp_path / "ledger2", full=True, back=True))
        except Exception as exc:
            got.append(exc)

    b = threading.Thread(target=put_back)
    b.start()
    b.join(1.0)
    assert b.is_alive() and order == [old.name]  # the put-back waits; it writes nothing under the running load
    go.set()
    a.join(30)
    b.join(30)
    assert order == [old.name, new.name]  # the load ended first; the put-back then met a finished newer night
    assert isinstance(got[0], RuntimeError) and "put-back" in str(got[0])
    with Built(db_url) as led:
        assert led.readable("fhir", new.name)
    # a load whose row was taken over by a writer outside the lock does not end as a success

    def overtaken(base: str, d: Path, workers: int = 4, only: Any = None) -> int:
        with Built(db_url) as other:
            other.begin("fhir", "2026-10-09")
        return 1

    monkeypatch.setattr(load_fhir, "load_snapshot", overtaken)
    third = tmp_path / "2026-10-03"
    third.mkdir()
    (third / "Patient.ndjson").write_text('{"resourceType": "Patient", "id": "p3"}\n')
    with pytest.raises(RuntimeError, match="overtaken"):
        load_fhir.sync_snapshot("http://hapi/fhir", third, tmp_path / "ledger")


def test_a_put_back_is_the_fhir_stores_alone(db_url: str) -> None:
    from datacore.generations import Built

    with Built(db_url) as b, pytest.raises(ValueError, match="fhir"):
        b.begin("derived", "2026-10-01", back=True)
