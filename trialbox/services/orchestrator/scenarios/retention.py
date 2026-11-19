"""RETENTION (SPEC §10.3; every night, the last step of the night's chain: T-726, D-492; DECISIONS D-78).

* inbound attachments (``attachments/``) older than ``retention.attachments_days`` and outputs (``outputs/``, plus the
  public ClinicalTrials.gov cache ``ctgov/``) older than ``retention.outputs_days`` are deleted from the object store,
  except the attachments and outputs of a job of a study that is not ``closed`` (NEW-LIFE-9, D-765: held while the
  study runs; a study whose state cannot be read is held);
  the audit chain keeps their sha256 (``retention.deleted`` per job: keys + hashes recorded when they were created);
* candidate pools and CRC feedback of rulesets that are no longer approved on this box, untouched for
  ``retention.pool_months_after_ruleset`` months, are deleted;
* mail logs (the mail gateway's intake / sent tables, finished sends, the console's morning-mail log) older than
  ``retention.mail_log_days`` are deleted (D-138; a send that never finished stays);
* lake / NDJSON snapshots are pruned by the adapter after each ingest (``tb_common.retention.snapshots_to_keep``);
* the answer store's rows of a snapshot the site's retention no longer keeps are deleted (D-1360; each screening
  run sweeps too, and this sweep keeps a study that stopped screening from holding its rows past D-452);
* the audit chain itself is never touched (archived every night by ``trialbox logs daily``, D-138); container logs
  rotate by size in compose and are collected and pruned on the host (``retention.logs_days``).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from tb_common.retention import expired, held_after_close
from tb_common.ruleset import list_rulesets

from orchestrator import answer_store
from orchestrator.core import Ctx, Outcome
from orchestrator.scenarios.review import approved_or_none

PREFIXES = (("attachments/", "attachments_days"), ("outputs/", "outputs_days"), ("ctgov/", "outputs_days"))
CLOSED = "closed"  # the console's last study state (D-386): only then do a study's files go by their age (D-765)
RUNNING = "running"  # D-765: held while the study is not closed
AFTER_CLOSE = "after_close"  # D-779: held for the study's period after the close


def _hashes(ctx: Ctx, job_id: str) -> dict[str, str]:
    job = ctx.orch.db.get(job_id)
    if job is None:
        return {}
    out = {f.minio_key: f.sha256 for f in job.inputs or []}
    out.update({o.minio_key: o.sha256 for o in job.outputs or []})
    return out


def prune_mail_logs(before_iso: str, before_day: Any) -> dict[str, int]:
    """Mail logs (D-138): the mail gateway's intake / sent / finished-send rows and the console's morning-mail log
    older than the cut-off, in the trial database (``TB_DB_URL``). The audit chain keeps every mail event."""
    from mail_gateway.store import MailDB
    from tb_common.db import Database

    mdb = MailDB()
    try:
        out = mdb.prune(before_iso)
    finally:
        mdb.close()
    with Database.connect(os.environ.get("TB_DB_URL"), "site") as site:
        if site.fetchval("SELECT to_regclass(?)", (f'"{site.schema}".notify_log',)) is not None:
            out["notify_log"] = site.execute("DELETE FROM notify_log WHERE day < ?", (before_day.isoformat(),))
    return out


def kept_for_open_studies(ctx: Ctx) -> set[str]:
    """T-704 (D-458; scale review F-34): the stored lists the next micro-batch of each open study with a candidate
    pool will read (:func:`orchestrator.scenarios.microbatch.study_sources`). They are kept whatever their age: a
    study whose last SCREEN is over a year old lost them, and every micro-batch of it failed from then on. A study
    whose state cannot be read is treated as open (keep rather than delete)."""
    from orchestrator import scheduler
    from orchestrator.scenarios.microbatch import study_sources

    keep: set[str] = set()
    for rid in ctx.orch.db.pool_rulesets():
        try:
            is_open = scheduler.study_state(rid) == scheduler.OPEN
        except Exception:
            is_open = True
        if is_open:
            keep |= set(study_sources(ctx.orch.db, rid))
    return keep


def study_hold(rid: str, now: datetime) -> str:
    """Why a study's files are held on ``now``, or "": :data:`RUNNING` (D-765: a recorded state that is not
    ``closed``, or a state that cannot be read) or :data:`AFTER_CLOSE` (D-779, T-305c: closed, and the close's own
    period, or the default one, has not ended; a close that cannot be read is held too: keep rather than delete)."""
    from orchestrator import scheduler

    try:
        state = scheduler.recorded_study_state(rid)
    except Exception:
        return RUNNING
    if state is None:
        return ""
    if state != CLOSED:
        try:  # WALK-1 (the review of D-1153): a study only begun (its protocol sent, never moved) is no running study
            return "" if state == "startup" and scheduler.only_begun(rid) else RUNNING
        except Exception:
            return RUNNING
    try:
        row = scheduler.recorded_close(rid)
    except Exception:
        return AFTER_CLOSE
    if row is None or row[0] != CLOSED:  # changed between the two reads: held until the next night
        return AFTER_CLOSE
    return AFTER_CLOSE if held_after_close(row[1], row[2], now) else ""


def held_for_running_studies(ctx: Ctx, now: datetime) -> Callable[[str], str]:
    """NEW-LIFE-9 (D-765, LIFE-009; T-305c without waiting for T-305b): whether the objects of one job (its
    ``attachments/<job>/`` and ``outputs/<job>/``) are held: the job's ruleset is a study the console has a recorded
    state for, and that state is not ``closed``. A study whose state cannot be read is held (keep rather than
    delete). A ruleset with no recorded state (a feasibility of a trial the site declined, a cohort, a case: never set
    up as a study), a job of no ruleset and a job this box no longer knows keep the configured ages (the review of
    D-765: "no row" is not a running study). After the close, held for the study's period (D-779). One read per job
    and per ruleset; the answer is why (:func:`study_hold`), "" when not held."""
    studies: dict[str, str] = {}
    jobs: dict[str, str] = {}

    def held(group: str) -> str:
        if group not in jobs:
            job = ctx.orch.db.get(group) if group else None
            rid = str(job.ruleset or "") if job is not None else ""
            if rid and rid not in studies:
                studies[rid] = study_hold(rid, now)
            jobs[group] = studies.get(rid, "")
        return jobs[group]

    return held


def answer_rows_swept(ctx: Ctx, now: datetime) -> int:
    """D-1360: the answer store's rows of every snapshot the site's retention no longer keeps, counted against the
    lake's current snapshot (none read: nothing swept; the next screening run sweeps)."""
    try:
        snapshot = ctx.services.lake.snapshot()
    except Exception:
        return 0
    if not snapshot:
        return 0
    ret = ctx.cfg.settings.retention
    nightly = int(ret.nightly_snapshots if ret and ret.nightly_snapshots is not None else 3)
    months = int(ret.month_end_snapshots_months if ret and ret.month_end_snapshots_months is not None else 36)
    return answer_store.retain(ctx.orch.db, snapshot, now.date(), nightly, months)


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
    keep = kept_for_open_studies(ctx)
    held = held_for_running_studies(ctx, now)
    kept: list[str] = []
    on_hold: list[str] = []
    after_close: list[str] = []
    for prefix, key in PREFIXES:
        for obj in ctx.store.list(prefix):
            if expired(obj.last_modified, now, days[key]):
                if obj.key in keep:  # an open study's next micro-batch reads it (D-458)
                    kept.append(obj.key)
                    continue
                group = obj.key.split("/", 2)[1] if obj.key.count("/") >= 2 else prefix
                why = held(group) if prefix != "ctgov/" else ""
                if why:  # D-765: a study's file stays until the study is closed; D-779: and its period after
                    (after_close if why == AFTER_CLOSE else on_hold).append(obj.key)
                    continue
                deleted.setdefault(group, []).append(obj.key)
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
    mail_days = int(ret.mail_log_days if ret and ret.mail_log_days else 1825)
    mail = prune_mail_logs((now - timedelta(days=mail_days)).isoformat(), (now - timedelta(days=mail_days)).date())
    if any(mail.values()):
        ctx.orch.audit.append("retention.mail", job_id=ctx.job.job_id, detail={"days": mail_days, "rows": mail})
    approved = {
        rid for rid in list_rulesets(ctx.rulesets_dir) if approved_or_none(ctx, rid, None, run=False) is not None
    }
    # the review of D-765: a running study's pool and marks are kept too, even while its approval has lapsed
    approved |= {rid for rid in ctx.orch.db.pool_rulesets() if study_hold(rid, now)}  # D-779: and after the close
    cutoff = (now - timedelta(days=round(pool_months * 30.44))).isoformat()
    pools = ctx.orch.db.prune_inactive(approved, cutoff)
    if pools["pool"] or pools["feedback"]:
        ctx.orch.audit.append("retention.pools", job_id=ctx.job.job_id, detail=pools)
    answers = answer_rows_swept(ctx, now)
    report: dict[str, Any] = {
        "run_at": now.isoformat(timespec="seconds"),
        "objects_deleted": count,
        "kept_for_open_studies": len(kept),  # past their age, kept: an open study's next micro-batch reads them
        "held_for_running_studies": len(on_hold),  # D-765: past their age, of a study not closed
        "held_after_close": len(after_close),  # D-779: past their age, of a closed study within its period
        "by_prefix": {p: sum(1 for ks in deleted.values() for k in ks if k.startswith(p)) for p, _ in PREFIXES},
        "pool_rows_deleted": pools["pool"],
        "feedback_rows_deleted": pools["feedback"],
        "mail_log_rows_deleted": mail,
        "answer_rows_deleted": answers,
        "limits": {**days, "pool_months_after_ruleset": pool_months, "mail_log_days": mail_days},
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
