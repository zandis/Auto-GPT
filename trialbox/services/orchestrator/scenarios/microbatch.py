"""MICROBATCH (SPEC §8.2): the screening cadence between two SCREEN runs (D-397, T-624, review LIFE-014).

Two triggers, one scenario:

* **weekly** (the timer, Monday 03:00, or by hand): the candidate pool's patients with an appointment in the next 14
  days get their ``time_sensitive`` criteria re-evaluated (structured via CQL, note via judge), and the study's **new
  in-scope patients** are screened in full and added to the pool. ``this_week_visit1.xlsx`` (phi) with changed
  verdicts highlighted and a ``changes`` sheet goes to ``list_to``. Before D-397 new patients were screened on the
  first Monday of a month only, so a first-visit patient booked for next week was missed.
* **after an ingest** (``trigger=ingest``, submitted by :func:`orchestrator.scheduler.after_ingest`): only new
  patients **booked** in the window are screened (the pool is not re-checked; the weekly run does that). A patient
  who first appears in Tuesday's data with a Friday appointment is on the clinic list on Wednesday morning. The
  list mail goes out only when the run found a new candidate.

A *new* patient is one in the study's screening scope (the scope of SCREEN) whom no run has looked at since the
study's last SCREEN: not in the pool, not on that SCREEN's excluded list, not in the previous micro-batch's
``new_screened_*.json`` (the record of who the micro-batch screened; cumulative, phi, never mailed). Nearest
appointment first.

**Night budget** (``TB_MICROBATCH_NIGHT_BUDGET``, patients; 0 = no limit): the micro-batch jobs of one night, every
study together, evaluate at most that many patients (pool re-checks and new patients). The job takes what the
night's earlier micro-batch jobs left, re-checks first, then new patients; the rest carry over to the next run, and
the summary and the audit (``microbatch.budget``) say how many (never a silent cap). The allowance is fixed on the
job's first run (option ``night_left``), as is the baseline (option ``seen_from``), so a resumed job and a re-run
make the same list.

**Version and basis** (T-707, D-476): a pool row stored under another criteria version is never re-tiered. It is
screened again in full (after the re-checks, before the new patients, inside the night budget) and its pool row is
replaced; a row the run does not reach keeps its stored version and is listed as ``review`` with every criterion
"not evaluated". A stored note answer that was not allowed to exclude when it was given (``final: false``, or a
note fail of a row whose stored tier is not ``excluded``) never excludes at the re-tier.

``incident=0`` turns the new-patient screen off (a re-check only). Every run also stores ``candidate_list_*.json``
(phi, the whole pool and the new candidates) for the console's week page, as SCREEN does. The job pins one lake
snapshot (T-305a, D-383) through ``ctx.services.lake``.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from tb_common.reasons import Reason
from tb_common.ruleset import Ruleset
from tb_common.smallcell import suppress
from tb_contracts import CandidateList, CandidateRow, CriterionVerdict, Judging, ScreenRunScope, TierSummary, dump

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery, Outcome, job_stamp
from orchestrator.reports import screen_summary_pdf
from orchestrator.reports.candidate_xlsx import Change
from orchestrator.scenarios.evaluate import (
    PatientVerdicts,
    effective_note_block,
    is_note_answer,
    not_in_snapshot,
    row,
    sort_key,
    tier,
)
from orchestrator.scenarios.review import recipients, require_approved
from orchestrator.scenarios.screen import (
    Scoped,
    deliver_lists,
    drop_opted_out,
    evaluate_scope,
    judge_for,
    judging_info,
    local_iso,
    persist_pool,
    practitioner_names,
    practitioners_of,
    publish_s2b_source,
    report_meta,
    run_screen,
    small_cell,
    threshold,
)
from orchestrator.scheduler import require_open

APPT_SQL = """
SELECT pid, CAST(min(start) AS VARCHAR) AS next_appt, arg_min(practitioner_id, start) AS practitioner_id,
       arg_min(dept, start) AS dept
FROM appointment
WHERE list_contains(CAST($1 AS VARCHAR[]), pid) AND status = 'booked'
  AND CAST(start AS DATE) BETWEEN CAST($2 AS DATE) AND CAST($3 AS DATE)
GROUP BY pid ORDER BY pid
"""
NEW_DOC = "new_screened_"  # the micro-batch's record of the new patients it screened (cumulative since SCREEN)
DEFAULT_NIGHT_BUDGET = 2000  # patients a night (libs/tb_common/config.py, TB_MICROBATCH_NIGHT_BUDGET)
LISTED = ("high", "review")


def _aware(value: object) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(str(value))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _set_option(ctx: Ctx, key: str, value: str) -> None:
    ctx.update(options={**(ctx.job.options or {}), key: value})


def night_budget(ctx: Ctx) -> int:
    """The configured night budget in patients (0: no limit)."""
    return int(getattr(ctx.cfg.env, "microbatch_night_budget", DEFAULT_NIGHT_BUDGET))


def night_left(ctx: Ctx) -> int | None:
    """How many patients this job may evaluate: the night budget less what the night's other micro-batch jobs (same
    run date, every study) evaluated. Fixed on the first run (option ``night_left``; -1 = no limit). None: no
    limit."""
    fixed = (ctx.job.options or {}).get("night_left")
    if fixed is None:
        budget = night_budget(ctx)
        left = -1
        if budget > 0:
            day = ctx.today()
            used = sum(
                j.metrics.patients_scoped
                for j in ctx.orch.db.find(type_="MICROBATCH", limit=1000)
                if j.job_id != ctx.job.job_id and j.run_date == day and j.metrics is not None
            )
            left = max(0, budget - used)
        fixed = str(left)
        _set_option(ctx, "night_left", fixed)
    value = int(fixed)
    return None if value < 0 else value


def seen_sources(ctx: Ctx, rs: Ruleset) -> list[str]:
    """The stored lists of who a run looked at since the study's last SCREEN: that SCREEN's candidate and excluded
    lists, and the latest micro-batch record after it. Named on the job's first run (option ``seen_from``), so a
    resumed job and a re-run read the same ones."""
    fixed = (ctx.job.options or {}).get("seen_from")
    if fixed is None:
        keys: list[str] = []
        screens = ctx.orch.db.find(type_="SCREEN", ruleset=rs.id, state="done", limit=1)
        if screens:
            last = screens[0]
            keys += [
                o.minio_key
                for o in last.outputs or []
                if o.filename.startswith(("excluded_", "candidate_list_")) and o.filename.endswith(".json")
            ]
            for j in ctx.orch.db.find(type_="MICROBATCH", ruleset=rs.id, state="done", limit=100):
                if j.job_id == ctx.job.job_id or j.received_at <= last.received_at:
                    continue
                doc = next((o for o in j.outputs or [] if o.filename.startswith(NEW_DOC)), None)
                if doc is not None:
                    keys.append(doc.minio_key)
                    break  # newest first, and each record holds the ones before it
        fixed = ",".join(keys)
        _set_option(ctx, "seen_from", fixed)
    return [k for k in fixed.split(",") if k]


def read_seen(ctx: Ctx, keys: list[str]) -> tuple[set[str], set[str]]:
    """(every patient on the lists ``keys`` name, the ones on the micro-batch record among them)."""
    seen: set[str] = set()
    earlier: set[str] = set()
    for key in keys:
        doc = json.loads(ctx.store.get(key))
        if "pids" in doc:  # a micro-batch record
            earlier |= {str(p) for p in doc["pids"]}
        seen |= {str(r.get("pid")) for r in doc.get("rows") or []}
    return seen | earlier, earlier


def pool_as_received(ctx: Ctx, rs: Ruleset, keys: list[str]) -> list[dict[str, Any]]:
    """The pool as it stood when the job was received. A row this job wrote after its receipt that no earlier run
    listed is one of this job's own new patients (a resumed job, or a re-run on the pool the original left; a
    re-run's copy of the pool keeps no first-added time): it is not the pool's."""
    got = ctx.job.received_at
    rows = ctx.orch.db.pool(rs.id)
    mine = [p for p in rows if p.get("job_id") == ctx.job.job_id and (_aware(p.get("added_at")) or got) >= got]
    if not mine:
        return rows
    listed = read_seen(ctx, keys)[0]
    drop = {p["pid"] for p in mine if p["pid"] not in listed}
    return [p for p in rows if p["pid"] not in drop]


def run(ctx: Ctx) -> Outcome:
    job = ctx.job
    require_open(job.ruleset)  # D-386 (LIFE-008): no list for a study that is not open
    rs: Ruleset = require_approved(ctx, (job.ruleset or "").upper(), None)
    ctx.update(ruleset_version=rs.version)
    opts = job.options or {}
    on_ingest = opts.get("trigger") == "ingest"
    keys = seen_sources(ctx, rs)
    pool = pool_as_received(ctx, rs, keys)
    if not pool:
        raise StepFailed("running", f"No candidate pool for {rs.id}; run SCREEN first.")
    ctx.state("running")
    snapshot = ctx.services.lake.snapshot()  # pins the job's snapshot (T-305a, D-383)
    if not snapshot:
        raise StepFailed("running", "The data lake has no snapshot yet.")
    ctx.update(snapshot_date=date.fromisoformat(snapshot))
    run_date = ctx.today()
    sc = rs.manifest.scopes.screen if rs.manifest.scopes and rs.manifest.scopes.screen else None
    window = int(opts.get("window") or (sc.microbatch_window_days if sc and sc.microbatch_window_days else 14))
    horizon = run_date + timedelta(days=window)
    left = night_left(ctx)
    tz = ctx.cfg.env.tz
    appts = {
        r["pid"]: r
        for r in ctx.services.lake.query(
            APPT_SQL, [[p["pid"] for p in pool], run_date.isoformat(), horizon.isoformat()]
        ).to_pylist()
    }
    every = []
    for p in pool:
        a = appts.get(p["pid"])
        every.append(
            Scoped(p["pid"], local_iso(a["next_appt"], tz), a["practitioner_id"], a["dept"])
            if a is not None
            else Scoped(p["pid"], None, None, None)
        )
    pool_pids = {p["pid"] for p in pool}
    kept = {s.pid for s in drop_opted_out(ctx, every)}  # D-147: the opt-out register applies to every list
    pool = [p for p in pool if p["pid"] in kept]
    # T-707 (D-476, review H3): a row stored under another criteria version was never evaluated on this one. It is
    # screened again below, not re-tiered (a row without a version is a test stand-in: the column is NOT NULL)
    stale = [p for p in pool if p.get("version") not in (None, rs.version)]
    stale_pids = {p["pid"] for p in stale}
    pool = [p for p in pool if p["pid"] not in stale_pids]
    week = {s.pid: s for s in every if s.pid in kept and s.pid in appts}
    ts = {c.id for c in rs.active() if c.time_sensitive and c.kind in ("inclusion", "exclusion")}
    # the re-check: the nearest visits first, within the night budget (the after-ingest run re-checks nobody)
    due = (
        sorted((s for s in week.values() if s.pid not in stale_pids), key=lambda s: (s.next_appointment or "", s.pid))
        if ts and not on_ingest
        else []
    )
    recheck = due if left is None else due[:left]
    fresh = evaluate_scope(ctx, rs, run_date, snapshot, recheck, only=ts, all_candidates=True) if recheck else {}
    t = threshold(ctx, rs)
    # the same note-block decision as SCREEN: no verifier, one model twice or a shut canary gate never exclude
    # on a note answer (D-276, review F-01; before, the re-tier below used the configured policy alone)
    may_block = effective_note_block(judge_for(ctx, rs))[0]
    pool_rows: list[CandidateRow] = []
    changes: list[Change] = []
    stamp = job_stamp(ctx)  # evaluation time = the job's receipt: same inputs → same bytes (D-82)
    rechecked = {s.pid for s in recheck}
    by_id = rs.by_id()
    for p in pool:
        old = {v["id"]: CriterionVerdict.model_validate(v) for v in p["verdicts"]}
        if p.get("tier") != "excluded":
            # D-476 item 3 (review H1): a row that was not excluded holds no note fail that was allowed to exclude
            # (it would be excluded). A row stored before the field existed says so here, and keeps saying it.
            old = {
                k: v.model_copy(update={"final": False})
                if v.verdict == "fail" and v.final is None and k in by_id and is_note_answer(by_id[k], v)
                else v
                for k, v in old.items()
            }
        new = dict(old)
        changed: list[str] = []
        for v in fresh[p["pid"]].verdicts if p["pid"] in fresh else []:
            if v.id not in ts:
                continue
            prev = old.get(v.id)
            if prev is None or prev.verdict != v.verdict:
                changed.append(v.id)
                changes.append(
                    Change(
                        p["pid"],
                        v.id,
                        prev.verdict if prev else "",
                        v.verdict,
                        (v.evidence.quote or "") if v.evidence else "",
                    )
                )
            new[v.id] = v
        ordered = [new[c.id] for c in rs.active() if c.id in new]
        tr, acts, n_unk = tier(rs, ordered, t, note_block=may_block)
        pv = PatientVerdicts(p["pid"], ordered, tr, acts, n_unk)
        s = week.get(p["pid"])
        if s is not None:
            fresh_now = p["pid"] in rechecked or (not ts and not on_ingest)
            when = stamp if fresh_now else str(p.get("last_eval") or stamp)
            pool_rows.append(row(pv, s.next_appointment, s.practitioner_id, s.department, when, changed))
        else:  # no booked visit in the window: a stored visit inside it was cancelled or moved, so it is dropped
            nxt = _aware(p.get("next_appointment"))
            keep = p.get("next_appointment") if nxt is not None and nxt.date() > horizon else None
            pool_rows.append(
                row(pv, keep, p.get("practitioner_id"), p.get("department"), str(p.get("last_eval") or stamp))
            )
    week_rows = [r for r in pool_rows if r.pid in week]
    if not on_ingest:  # the week's rows, re-checked or not; a row the budget left out keeps its last evaluation
        persist_pool(ctx, rs, [r for r in week_rows if not ts or r.pid in rechecked])
    used = len(recheck)
    judging: dict[str, Any] | None = judging_info(judge_for(ctx, rs)) if recheck else None

    # ---------------------------------------------------------------- rows of another criteria version (T-707)
    by_pid = {s.pid: s for s in every}
    stored = {p["pid"]: p for p in stale}

    def _visit(pid: str) -> Scoped:
        """The visit in the window, else the stored visit beyond it (as a re-tiered row keeps it)."""
        if pid in week:
            return by_pid[pid]
        p = stored[pid]
        nxt = _aware(p.get("next_appointment"))
        keep = str(p["next_appointment"]) if nxt is not None and nxt.date() > horizon else None
        return Scoped(pid, keep, p.get("practitioner_id"), p.get("department"))

    behind = sorted(
        (_visit(p["pid"]) for p in stale), key=lambda s: (s.next_appointment is None, s.next_appointment or "", s.pid)
    )
    again: list[Scoped] = []
    if behind and not on_ingest:  # the after-ingest run re-checks nobody: the weekly run screens them again
        again = behind if left is None else behind[: max(0, left - used)]
    version_rows: list[CandidateRow] = []
    cascade_runs: list[Any] = []  # the full screens of this job, for the one S2b source file (D-449)
    if again:
        vrun = run_screen(ctx, rs, run_date, snapshot, given=again)
        cascade_runs.append(vrun)
        version_rows = [r.model_copy(update={"changed": [v.id for v in r.criteria]}) for r in vrun.rows]
        persist_pool(ctx, rs, version_rows)  # whatever the tier: the row of the old version is replaced
        judging = vrun.judging
        used += len(again)
    done_again = {s.pid for s in again}
    waiting_rows: list[CandidateRow] = []
    for s in behind:
        if s.pid in done_again:
            continue
        p = stored[s.pid]
        pv = not_in_snapshot(rs, s.pid, reason=Reason.NOT_EVALUATED)  # every criterion unknown: a person looks
        pv.actions.append(
            f"Not yet evaluated against version {rs.version} of the criteria (last evaluated against version "
            f"{p['version']}): screened again on the next weekly run."
        )
        waiting_rows.append(
            row(pv, s.next_appointment, s.practitioner_id, s.department, str(p.get("last_eval") or stamp))
        )  # not written to the pool: the row keeps its stored version until it is screened again
    week_rows += [r for r in [*version_rows, *waiting_rows] if r.pid in week]

    # ---------------------------------------------------------------- new in-scope patients (D-397)
    new_rows: list[CandidateRow] = []
    screened: list[str] = []
    carried = 0
    skipped = ""
    if on_ingest or opts.get("incident", "auto") != "0":
        room = None if left is None else max(0, left - used)
        try:
            practitioners_of(ctx, rs)  # who the study screens: unset means no new-patient screen, not a failed run
        except StepFailed as exc:
            skipped = exc.message
        if not skipped:
            seen, earlier = read_seen(ctx, keys)
            seen |= pool_pids

            def select(scope: list[Scoped]) -> list[Scoped]:
                nonlocal carried
                cand = [
                    s for s in scope
                    if s.pid not in seen
                    and (not on_ingest or (s.next_appointment is not None
                                           and date.fromisoformat(s.next_appointment[:10]) <= horizon))
                ]  # fmt: skip
                cand.sort(key=lambda s: (s.next_appointment is None, s.next_appointment or "", s.pid))
                take = cand if room is None else cand[:room]
                carried = len(cand) - len(take)
                return take

            srun = run_screen(ctx, rs, run_date, snapshot, select=select)
            screened = [s.pid for s in srun.scoped]
            if screened:
                judging = srun.judging
            new_rows = [
                r.model_copy(update={"changed": [v.id for v in r.criteria]}) for r in srun.rows if r.tier in LISTED
            ]
            persist_pool(ctx, rs, new_rows)
            cascade_runs.append(srun)
            record = {"ruleset": rs.id, "run_date": run_date.isoformat(), "pids": sorted(earlier | set(screened))}
            body = json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
            ctx.publish(f"{NEW_DOC}{rs.id}_v{rs.version}.json", body, "phi", [])  # the console and the next run only
    have = [r for r in cascade_runs if getattr(r, "s2b_sources", None) is not None]
    if have:  # T-203b (D-449): only when the flag vec.s2b was on; one file for the job's screens
        if len(have) > 1:
            have[-1].s2b_sources = {p: v for r in have for p, v in r.s2b_sources.items()}
        publish_s2b_source(ctx, have[-1])
    ctx.metrics(patients_scoped=used + len(screened))
    over = len(due) - len(recheck)
    ctx.orch.audit.append(
        "microbatch.budget",
        job_id=job.job_id,
        ruleset=rs.id,
        detail={
            "trigger": "ingest" if on_ingest else "weekly",
            "budget": night_budget(ctx),
            "left": left,
            "rechecked": len(recheck),
            "recheck_carried": over,
            "version_rescreened": len(again),
            "version_carried": len(waiting_rows),
            "new_screened": len(screened),
            "new_carried": carried,
        },
    )

    # ---------------------------------------------------------------- outputs
    ctx.state("reporting")
    meta = report_meta(ctx, rs, snapshot, run_date, judging)
    everyone = sorted([*pool_rows, *version_rows, *waiting_rows, *new_rows], key=sort_key)
    listed = [r for r in everyone if r.tier in LISTED]
    cl = CandidateList(
        ruleset=rs.id,
        version=rs.version,
        snapshot=date.fromisoformat(snapshot),
        run_date=run_date,
        scope=ScreenRunScope(departments=[], window_days=window, n_scoped=used + len(screened)),
        rows=listed,
        summary=TierSummary(**{k: sum(1 for r in everyone if r.tier == k) for k in ("high", "review", "excluded")}),
        judging=Judging(**judging) if judging else None,
    )
    body = json.dumps(dump(cl), ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    ctx.publish(f"candidate_list_{rs.id}_v{rs.version}.json", body, "phi", [])  # the console's week page
    cell = small_cell(ctx, rs)  # summary PDF + mail are aggregate outputs: every count suppressed (SPEC §10.1)
    found = [r for r in new_rows if r.next_appointment and r.next_appointment.date() <= horizon]
    lines: list[str]
    if on_ingest:
        lines = [
            f"After the ingest {snapshot}, {rs.id} v{rs.version}, run {run_date.isoformat()}: "
            f"{suppress(len(screened), cell)} new patients booked in the next {window} days screened; "
            f"new candidates: {suppress(len(new_rows), cell)}.",
        ]
    else:
        lines = [
            f"Weekly microbatch {rs.id} v{rs.version}, run {run_date.isoformat()}: {suppress(len(week), cell)} pool "
            f"patients with an appointment in the next {window} days; time-sensitive criteria re-evaluated: "
            f"{', '.join(sorted(ts))}.",
            f"Verdict changes: {suppress(len(changes), cell)}; new patients screened: "
            f"{suppress(len(screened), cell)}; new patients added to the pool: {suppress(len(new_rows), cell)}.",
        ]
    if behind:
        lines.append(
            f"Criteria version {rs.version}: {suppress(len(again), cell)} pool patients last evaluated against an "
            f"earlier version were screened again; {suppress(len(waiting_rows), cell)} wait for the next weekly run "
            "and are listed for review."
        )
    if left is not None and (over or carried):
        lines.append(
            f"Night budget reached ({night_budget(ctx)} patients a night): {suppress(over, cell)} re-checks and "
            f"{suppress(carried, cell)} new patients carried over to the next run."
        )
    if skipped:
        lines.append(f"New patients were not screened: {skipped}")
    text = " ".join(lines)
    if on_ingest and not new_rows:  # nothing new: the console's list is refreshed, nobody is mailed
        return Outcome(summary_md=text)
    stem = (
        f"new_booked_{rs.id}_{run_date.isoformat()}"
        if on_ingest
        else f"this_week_visit1_{rs.id}_{run_date.isoformat()}"
    )
    mailed = sorted(found if on_ingest else [*week_rows, *found], key=sort_key)
    deliveries, _ = deliver_lists(ctx, rs, mailed, meta, stem, changes=None if on_ingest else changes)
    agg_to = recipients(rs.manifest.routing, job.requested_by)
    summary = ctx.publish(
        f"summary_{stem}.pdf",
        screen_summary_pdf.render(
            f"{'New booked patients' if on_ingest else 'Weekly visit list'} — {rs.manifest.trial_alias or rs.id}",
            mailed,
            rs,
            meta,
            lines,
            cell,
            practitioner_names(ctx),
        ),
        "aggregate",
        agg_to,
    )
    deliveries.append(Delivery(to=agg_to, outputs=[summary], routing=rs.manifest.routing, body_md=text))
    return Outcome(summary_md=text, deliveries=deliveries)
