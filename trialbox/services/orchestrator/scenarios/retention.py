"""RETENTION (SPEC §10.3; daily at ``settings.schedule.retention``; DECISIONS D-78).

* inbound attachments (``attachments/``) older than ``retention.attachments_days`` and outputs (``outputs/``, plus the
  public ClinicalTrials.gov cache ``ctgov/``) older than ``retention.outputs_days`` are deleted from the object store;
  the audit chain keeps their sha256 (``retention.deleted`` per job: keys + hashes recorded when they were created);
* candidate pools and CRC feedback of rulesets that are no longer approved on this box, untouched for
  ``retention.pool_months_after_ruleset`` months, are deleted;
* lake / NDJSON snapshots are pruned by the adapter after each ingest (``tb_common.retention.snapshots_to_keep``);
* the audit chain itself is never touched (10 years, backed up nightly); container logs rotate by size in compose.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from tb_common.retention import expired
from tb_common.ruleset import list_rulesets

from orchestrator.core import Ctx, Outcome
from orchestrator.scenarios.review import approved_or_none

PREFIXES = (("attachments/", "attachments_days"), ("outputs/", "outputs_days"), ("ctgov/", "outputs_days"))


def _hashes(ctx: Ctx, job_id: str) -> dict[str, str]:
    job = ctx.orch.db.get(job_id)
    if job is None:
        return {}
    out = {f.minio_key: f.sha256 for f in job.inputs or []}
    out.update({o.minio_key: o.sha256 for o in job.outputs or []})
    return out


def run(ctx: Ctx) -> Outcome:
    ret = ctx.cfg.settings.retention
    days = {
        "attachments_days": int(ret.attachments_days if ret and ret.attachments_days else 90),
        "outputs_days": int(ret.outputs_days if ret and ret.outputs_days else 365),
    }
    pool_months = int(ret.pool_months_after_ruleset if ret and ret.pool_months_after_ruleset else 24)
    ctx.state("running")
    now = ctx.orch._now()
    deleted: dict[str, list[str]] = {}
    for prefix, key in PREFIXES:
        for obj in ctx.store.list(prefix):
            if expired(obj.last_modified, now, days[key]):
                deleted.setdefault(obj.key.split("/", 2)[1] if obj.key.count("/") >= 2 else prefix, []).append(obj.key)
    count = 0
    for group, keys in sorted(deleted.items()):
        known = _hashes(ctx, group)
        for k in keys:
            ctx.store.delete(k)
        count += len(keys)
        ctx.orch.audit.append(
            "retention.deleted",
            job_id=ctx.job.job_id,
            detail={"group": group, "objects": [{"key": k, "sha256": known.get(k)} for k in sorted(keys)]},
        )
    approved = {rid for rid in list_rulesets(ctx.rulesets_dir) if approved_or_none(ctx, rid, None) is not None}
    cutoff = (now - timedelta(days=round(pool_months * 30.44))).isoformat()
    pools = ctx.orch.db.prune_inactive(approved, cutoff)
    if pools["pool"] or pools["feedback"]:
        ctx.orch.audit.append("retention.pools", job_id=ctx.job.job_id, detail=pools)
    report: dict[str, Any] = {
        "run_at": now.isoformat(timespec="seconds"),
        "objects_deleted": count,
        "by_prefix": {p: sum(1 for ks in deleted.values() for k in ks if k.startswith(p)) for p, _ in PREFIXES},
        "pool_rows_deleted": pools["pool"],
        "feedback_rows_deleted": pools["feedback"],
        "limits": {**days, "pool_months_after_ruleset": pool_months},
    }
    ctx.metrics(patients_scoped=0)
    ctx.publish(
        f"retention_{now.date().isoformat()}.json",
        (json.dumps(report, indent=1, sort_keys=True) + "\n").encode(),
        "aggregate",
        [],
    )
    return Outcome(
        summary_md=f"Retention: {count} objects deleted; pools {pools['pool']}, feedback {pools['feedback']}."
    )
