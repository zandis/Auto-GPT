"""Reproducibility check (SPEC §11.2 "same inputs + same versions → identical output hashes"; DECISIONS D-82).

Re-executes a finished job in a sandbox and compares every output's sha256 with the one stored and audited for the
original run:

* same job id, inputs, options, ruleset version (approved tag on disk) and **lake snapshot** (queries pinned to the
  job's ``snapshot_date``), with the clock pinned to the job's ``received_at``;
* outputs go to a scratch store, nothing is mailed, the job store is a temporary copy — the real box is untouched;
* the comparison itself is audited (``rerun.checked``) by the caller.

LLM-backed steps are reproducible when the model is (stub, or vLLM with temperature 0 and a fixed seed — §7.2).

    python -m orchestrator.rerun <job id> [<job id> ...]      # inside the orchestrator container
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

from tb_contracts import Job, SendRequest, SendResult

from orchestrator.core import Orchestrator
from orchestrator.db import JobDB


class PinnedLake:
    """Every query on the job's snapshot."""

    def __init__(self, lake: Any, snapshot: str | None) -> None:
        self.lake = lake
        self.pinned = snapshot

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
        return self.lake.query(sql, params, snapshot or self.pinned)

    def chunks_search(self, *args: Any, **kwargs: Any) -> Any:
        return self.lake.chunks_search(*args, **kwargs)

    def snapshot(self) -> str | None:
        return self.pinned or self.lake.snapshot()


class ScratchStore:
    """Reads fall through to the box store; writes stay in memory."""

    def __init__(self, base: Any) -> None:
        self.base = base
        self.mem: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.mem[key] = data

    def get(self, key: str) -> bytes:
        return self.mem[key] if key in self.mem else bytes(self.base.get(key))

    def exists(self, key: str) -> bool:
        return key in self.mem or bool(self.base.exists(key))

    def delete(self, key: str) -> None:
        self.mem.pop(key, None)

    def list(self, prefix: str) -> list[Any]:
        return list(self.base.list(prefix))


class NullMail:
    def send(self, req: SendRequest) -> SendResult:
        return SendResult(message_id=f"<rerun-{req.job_id}@trialbox.invalid>", sent_to=list(req.to), encrypted=False)


class NullAudit:
    def append(self, event: str, **fields: Any) -> dict[str, Any]:
        return {"event": event}


RERUNNABLE = ("FEAS", "SCREEN", "MICROBATCH", "NAV", "COHORT", "CALIBRATION")


@dataclass
class RerunResult:
    job_id: str
    type: str
    identical: bool
    files: list[dict[str, Any]]
    error: str | None = None


def rerun(orch: Orchestrator, job_id: str) -> RerunResult:
    original = orch.db.get(job_id)
    if original is None:
        return RerunResult(job_id, "?", False, [], "no such job")
    if original.state != "done":
        return RerunResult(job_id, original.type, False, [], f"job is {original.state}, not done")
    if original.type not in RERUNNABLE or (original.type == "FEAS" and any(original.inputs or [])):
        # SUBMIT posts to NHI, APPROVE / compiles write to the ruleset repository: never repeated
        return RerunResult(job_id, original.type, False, [], f"{original.type} jobs with side effects are not re-run")
    received = original.received_at
    work = Path(tempfile.mkdtemp(prefix="tb-rerun-"))
    db = JobDB(work / "jobs.sqlite")
    fresh = original.model_copy(
        update={"state": "received", "outputs": [], "error": None, "metrics": None, "updated_at": None}
    )
    db.put(Job.model_validate(fresh.model_dump()), queued=False)
    for p in orch.db.pool(original.ruleset or "") if original.type == "MICROBATCH" else []:
        db.pool_upsert(original.ruleset or "", p["version"], [p], p["job_id"], p["last_eval"])
    if original.type == "COHORT":  # trial drafts come from the compile cache (no new compiles)
        for row in orch.db.trial_cache_all():
            db.trial_cache_put(row)
        if (original.ruleset or "").upper() == "MERGE":
            _replay_alliance_tables(orch, db, original.job_id)
    snap = original.snapshot_date.isoformat() if original.snapshot_date else None
    services = replace(orch.services, lake=PinnedLake(orch.services.lake, snap), mail=NullMail())
    clone = Orchestrator(
        orch.cfg,
        db,
        ScratchStore(orch.store),
        NullAudit(),  # type: ignore[arg-type]
        services,
        orch.scenarios,
        orch.rulesets_dir,
        work,
        today=lambda: _local_date(orch, received),
        workers=0,
        async_notify=False,
    )
    clone._now = lambda: received.astimezone(_zone(orch))  # type: ignore[method-assign]
    done = clone.run(job_id)
    before = {o.filename: o.sha256 for o in original.outputs or []}
    after = {o.filename: o.sha256 for o in done.outputs or []}
    files = [
        {"filename": f, "original": before.get(f), "rerun": after.get(f), "same": before.get(f) == after.get(f)}
        for f in sorted(set(before) | set(after))
    ]
    db.close()
    err = None if done.state == "done" else f"rerun {done.state}: {done.error.message if done.error else ''}"
    return RerunResult(job_id, original.type, err is None and all(x["same"] for x in files), files, err)


def _replay_alliance_tables(orch: Orchestrator, db: JobDB, job_id: str) -> None:
    """The alliance tables as they stood when the merge ``job_id`` ran, rebuilt from immutable objects in job order:
    an earlier ``COHORT MERGE`` stored its attached tables, an earlier own COHORT run on the root stored the table it
    published (``cohort_table_*.csv``). Later re-submissions that replaced a site's rows in the live table therefore
    do not leak into the re-run."""
    from orchestrator.scenarios.cohort import parse_csv

    jobs = orch.db.find(type_="COHORT", limit=1_000_000)
    earlier = sorted((j for j in jobs if j.job_id < job_id and j.state in ("done", "failed")), key=lambda j: j.job_id)
    site = orch.cfg.settings.site.id
    for j in earlier:
        if (j.ruleset or "").upper() == "MERGE":
            sources = [(f.filename, f.minio_key) for f in j.inputs or []]
            received_from = j.requested_by
        else:
            sources = [(o.filename, o.minio_key) for o in j.outputs or [] if o.filename.startswith("cohort_table_")]
            received_from = f"self:{site}"
        for name, key in sources:
            if name.lower().endswith(".csv"):
                rows, errors = parse_csv(orch.store.get(key))
                if not errors:
                    db.cohort_store(rows, j.job_id, received_from)


def _zone(orch: Orchestrator) -> Any:
    from zoneinfo import ZoneInfo

    return ZoneInfo(orch.cfg.env.tz)


def _local_date(orch: Orchestrator, ts: datetime) -> date:
    return ts.astimezone(_zone(orch)).date()


def main(argv: list[str] | None = None) -> int:
    import argparse

    from orchestrator.app import orch as box

    ap = argparse.ArgumentParser(
        prog="python -m orchestrator.rerun",
        description="Re-execute finished jobs in a sandbox and compare output hashes (JSON line per job).",
    )
    ap.add_argument("job_ids", nargs="+", metavar="JOB_ID")
    args = ap.parse_args(argv)
    orch = box()  # not started: no workers, no scheduler
    ok = True
    for jid in args.job_ids:
        r = rerun(orch, jid)
        orch.audit.append(
            "rerun.checked",
            job_id=jid,
            detail={"identical": r.identical, "files": len(r.files), "error": r.error},
        )
        print(json.dumps(r.__dict__, ensure_ascii=False))
        ok = ok and r.identical
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
