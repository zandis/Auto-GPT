"""V-1 (plan 8, activity V7, criterion 8): a restore from a backup taken before an opt-out.

The order that matters: the patient is in the stores, a backup is taken, the patient opts out and the worker clears
the stores, then the backup is restored. The restore (``tools.trialbox.backup.restore``, T-728, D-493, D-522) puts
the opt-outs recorded after the backup back into the register. These tests show what it does with the stores: the
restored rows of the patient come back with the databases, and they go again at the opt-out worker's next tick (the
orchestrator runs one at its start). Between the restore and that tick nothing clears them; what keeps them from a
list then is each reader's own register check (D-441, D-860), and the hold of D-522 only when the restore is not
complete. Synthetic pseudonyms; a real PostgreSQL; ``pg_dump`` and ``pg_restore`` as the backup tool runs them.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

P, Q = "e7a5e0f0c0de1180", "e7a5e0f0c0de1181"  # P opts out after the backup; Q never does
SNAP = "2026-10-04"
T0 = "2026-10-05T09:00:00+00:00"


class _Audit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append(self, event: str, **kw: Any) -> None:
        self.events.append((event, kw))


def _batch(pids: list[str]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"Patient": [], "Condition": []}
    for i, p in enumerate(pids):
        out["Patient"].append({"resourceType": "Patient", "id": p, "birthDate": f"1960-01-0{i + 1}", "gender": "male"})
        out["Condition"].append({"resourceType": "Condition", "id": f"c-{p}", "subject": {"reference": f"Patient/{p}"},
                                 "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": "M10.0"}]},
                                 "onsetDateTime": "2026-09-01", "recordedDate": "2026-09-01"})  # fmt: skip
    return out


def _held(db_url: str, pid: str) -> set[str]:
    """The stores (of those this test seeds) that hold ``pid``: read by the brute-force search, not by the clears."""
    from tools import erasure_reach as er

    found = er.search_db(db_url, er.Marker(pid=pid))
    return {
        k for k in found.stores if k in ("orch.pool", "orch.candidates", "omop.person", "profile.tb_patient_profile")
    }


@pytest.fixture
def restored(db_url: str, tmp_path: Path) -> dict[str, Any]:
    from datacore.optout_worker import WorkerEnv, run_once
    from omop import schema
    from omop.load import load_batch
    from orchestrator.db import JobDB
    from patient_profile.twin import ProfileStore
    from tb_common.flags import Flags
    from tb_common.optout import OptOutRegister

    from tools.trialbox import backup as bk

    reg = OptOutRegister(db_url)
    jobs = JobDB(db_url)
    for pid in (P, Q):
        jobs.pool_upsert("GZQO", "1", [{"pid": pid, "tier": "high", "verdicts": []}], "J1", T0)
        jobs.candidate_set("GZQO", pid, "candidate", None, "steward1", T0, "screen", "J1")
    omop = schema.connect(db_url)
    load_batch(omop, "feed", SNAP, _batch([P, Q]), tz="Asia/Taipei")
    twins = ProfileStore(db_url)
    for pid in (P, Q):
        twins.put({"pid": pid, "profile": "v1", "basis": {"snapshot": SNAP}, "layers": {"core": {"sex": "F"}}}, T0)
    twins.close()
    dirs = {"audit": tmp_path / "audit"}
    dirs["audit"].mkdir()
    priv, pub = tmp_path / "it.key", tmp_path / "box.pub"
    bk.keygen(priv, pub)
    # TB_ENV DEV: the service-role step counts as done (on a real box it is configured); the restore can be complete
    env = {"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH", "TB_ENV": "DEV"}
    assert _held(db_url, P) == {"orch.pool", "orch.candidates", "omop.person", "profile.tb_patient_profile"}
    backup = bk.backup([tmp_path / "nas"], pub, env=env, dirs=dirs)[0]  # the patient is in it
    time.sleep(1.1)  # the register's times and the snapshot's are a second apart at least
    reg.add(P, "paper", "", "console:office1", datetime.now(UTC).isoformat())
    wenv = WorkerEnv(register=reg, audit=_Audit(), now=datetime.now(UTC), jobs=jobs, omop=omop)
    first = run_once(wenv)
    cleared = _held(db_url, P)
    omop.close()
    reg.close()
    out = bk.restore(backup, priv, env=env, dirs=dirs, public_key=pub, keep_to=tmp_path / "kept")
    after_restore = _held(db_url, P)
    hold = Flags(url=db_url).row(bk.HOLD_FLAG)
    reg2 = OptOutRegister(db_url)
    omop2 = schema.connect(db_url)
    tick = run_once(WorkerEnv(register=reg2, audit=_Audit(), now=datetime.now(UTC), jobs=JobDB(db_url), omop=omop2))
    after_tick = _held(db_url, P)
    effective = reg2.effective()
    omop2.close()
    reg2.close()
    return {"first": first, "cleared": cleared, "out": out, "after_restore": after_restore, "hold": hold,
            "tick": tick, "after_tick": after_tick, "effective": effective, "q": _held(db_url, Q)}  # fmt: skip


def test_the_restore_keeps_the_opt_out_and_the_next_tick_clears_the_stores(restored: dict[str, Any]) -> None:
    """The register: the opt-out typed after the backup is put back (T-728). The stores: cleared again by the next
    tick. The hold: the restore kept every later opt-out, so it is complete and takes its own hold off (D-522)
    before any tick; the services may then start with the patient's rows back in the stores."""
    assert restored["first"]["failed"] == [] and restored["cleared"] == set()  # cleared before the restore
    o = restored["out"]
    lost = o["optouts_after_backup"]
    assert (lost["state"], lost["kept"], lost["not_kept"]) == ("counted", 1, 0)
    assert P in restored["effective"] and Q not in restored["effective"]
    assert P not in json.dumps(o)  # counts only
    assert o["complete"] is True, {k: o[k] for k in ("hold", "to_reapply", "service_roles")}
    assert o["hold"] == "released" and restored["hold"] == "released"
    assert restored["tick"]["failed"] == [] and restored["tick"]["opted_out"] == 1
    assert restored["after_tick"] == set()
    assert restored["q"] == {"orch.pool", "orch.candidates", "omop.person", "profile.tb_patient_profile"}


@pytest.mark.xfail(
    strict=True,
    reason="V1-10: a restore re-applies the opt-out list to the register only; the restored stores hold the "
    "patient again until the worker's next tick, and a complete restore releases its hold first",
)
def test_after_the_restore_no_store_holds_the_opted_out_patient(restored: dict[str, Any]) -> None:
    """Plan 8, criterion 8 and review J-2: "a restore re-applies the opt-out list". Shown on the stores this test
    seeds: the pool, the candidate registry, OMOP and the twin."""
    assert restored["after_restore"] == set(), sorted(restored["after_restore"])
