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
