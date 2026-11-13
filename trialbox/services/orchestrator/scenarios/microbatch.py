"""MICROBATCH (SPEC §8.2): the screening cadence between two SCREEN runs (D-397, T-624, review LIFE-014).

Two triggers, one scenario:

* **weekly** (the timer, Monday 03:00, or by hand): the candidate pool's patients with an appointment in the next 14
  days get every criterion the compiled SQL decides re-evaluated (structured and mixed: :func:`recheck_ids`,
  NEW-LIFE-3, D-642; and a note criterion flagged ``time_sensitive``, via the judge), the study's **new in-scope
  patients** are screened in full and added to the pool, and the patients a run **excluded** since the study's last
  SCREEN who are still in scope are screened again (NEW-LIFE-4, D-642). ``this_week_visit1.xlsx`` (phi) with changed
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

An *excluded* patient (D-642; before, never looked at again until a person ran SCREEN) is one in that scope whom a
run has looked at and who is not in the pool: on that SCREEN's excluded list, or screened and not listed by an
earlier micro-batch. An exclusion can end by time alone (an infection 30 days ago, a drug stopped 90 days ago, an
age) or by a new result, so the weekly run screens them again in full, after the new patients, inside the night
budget: the one looked at longest ago first (the record's ``again``: pid to the day a weekly run last screened it
again; never = first), so a small budget still reaches everybody in turn. One who is listed now goes to the pool
and on the week's list as a new candidate does.

**Night budget** (``TB_MICROBATCH_NIGHT_BUDGET``, patients; 0 = no limit; reserved in the database, an equal share
per waiting study: T-704, D-458): the micro-batch jobs of one night, every
study together, evaluate at most that many patients (pool re-checks, new patients, excluded patients screened
again). The job takes what the night's earlier micro-batch jobs left, re-checks first, then new patients, then
excluded patients; the rest carry over to the next run, and
the summary and the audit (``microbatch.budget``) say how many (never a silent cap). The allowance is fixed on the
job's first run (option ``night_left``), as is the baseline (option ``seen_from``), so a resumed job and a re-run
make the same list.

**The excluded patients' share** (``TB_MICROBATCH_EXCLUDED_PERCENT``, default 25; D-646, the owner's ruling of
2026-11-13): of a weekly job's allowance that part is kept for screening its excluded patients again, so the
re-checks and the new patients cannot use it all (measured: a study whose re-checks fill its allowance never reached
them). Kept only as far as excluded patients are in scope (counted before the allowance is spent), never for
nobody; a place kept and not needed goes to a waiting new patient (not back to a re-check: those are done by
then; it returns to the night). The number kept is fixed on the job's first run (option ``excluded_kept``).
The summary and the audit say how many were
reached, how many are in scope and how many weekly runs a full pass takes at that share.

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
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from tb_common.reasons import Reason
from tb_common.ruleset import Ruleset
from tb_common.smallcell import suppress
from tb_contracts import CandidateList, CandidateRow, CriterionVerdict, Judging, ScreenRunScope, TierSummary, dump

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery, Outcome, job_stamp
from orchestrator.decision_context import decision_of
from orchestrator.reports import screen_summary_pdf
from orchestrator.reports.candidate_xlsx import Change
from orchestrator.scenarios.evaluate import (
    FILTERED,
    PatientVerdicts,
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
    screen_scope,
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
DEFAULT_EXCLUDED_PERCENT = 25  # of a weekly job's allowance (config.py, TB_MICROBATCH_EXCLUDED_PERCENT; D-646)
LISTED = ("high", "review")


def _aware(value: object) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(str(value))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _set_option(ctx: Ctx, key: str, value: str) -> None:
    ctx.update(options={**(ctx.job.options or {}), key: value})


#: an "unknown" that says nothing about the patient: the model was not asked or did not answer
NOT_ASKED = (Reason.NOT_EVALUATED.value, Reason.MODEL_DOWN.value)


def _not_asked(v: CriterionVerdict) -> bool:
    return v.verdict == "unknown" and v.evidence is not None and v.evidence.reason in NOT_ASKED


def night_budget(ctx: Ctx) -> int:
    """The configured night budget in patients (0: no limit)."""
    return int(getattr(ctx.cfg.env, "microbatch_night_budget", DEFAULT_NIGHT_BUDGET))


TERMINAL = ("done", "failed")


def excluded_percent(ctx: Ctx) -> int:
    """The part of a weekly job's allowance kept for its excluded patients, in percent (D-646)."""
    return int(getattr(ctx.cfg.env, "microbatch_excluded_percent", DEFAULT_EXCLUDED_PERCENT))


def _reserved(job: Any) -> int | None:
    """What a night's micro-batch holds of the allowance: what it used once it has ended, else what it reserved;
    None while it has not asked yet."""
    if job.state in TERMINAL:
        return int(job.metrics.patients_scoped) if job.metrics is not None else 0
    raw = (job.options or {}).get("night_reserved")
    return int(raw) if raw is not None else None


def reserve(ctx: Ctx, budget: int) -> int:
    """T-704 (D-458; scale review F-32): this job's part of the night's allowance, reserved in the database.

    Under a lock of the night (an advisory lock, so jobs that start at the same moment take their turn): the
    allowance less what the night's other micro-batches have reserved or used, shared equally among those that have
    not asked yet, this job included. The reservation is written into the job's record before the lock is released,
    so the reservations of a night never add up to more than the allowance, and the order of the studies no longer
    decides who gets anything."""
    day = ctx.today()
    me = ctx.job.job_id
    with ctx.orch.db.locked(f"microbatch.allowance:{day.isoformat()}"):
        taken = waiting = 0
        for j in ctx.orch.db.find(type_="MICROBATCH", limit=1000):
            if j.job_id == me or not (j.run_date == day or (j.run_date is None and j.state == "received")):
                continue  # another night's
            got = _reserved(j)
            if got is None:
                waiting += 1
            else:
                taken += got
        left = max(0, budget - taken)
        share = min(left, -(-left // (waiting + 1)))  # an equal part of what is left, rounded up
        _set_option(ctx, "night_reserved", str(share))
    return share


def night_done(ctx: Ctx, used: int) -> None:
    """The job has evaluated ``used`` patients: its reservation becomes that, and the rest of its share is there
    for the night's later micro-batches (a finished job is counted by what it used in any case)."""
    if (ctx.job.options or {}).get("night_reserved") is not None:
        _set_option(ctx, "night_reserved", str(used))


def night_left(ctx: Ctx) -> int | None:
    """How many patients this job may evaluate: its reserved share of the night budget (:func:`reserve`). Fixed on
    the first run (option ``night_left``; -1 = no limit), so a resumed job and a re-run read the same number.
    None: no limit."""
    fixed = (ctx.job.options or {}).get("night_left")
    if fixed is None:
        budget = night_budget(ctx)
        left = reserve(ctx, budget) if budget > 0 else -1
        fixed = str(left)
        _set_option(ctx, "night_left", fixed)
    value = int(fixed)
    return None if value < 0 else value


def recheck_ids(rs: Ruleset) -> set[str]:
    """The criteria the weekly re-check evaluates again (NEW-LIFE-3, D-642; review LIFE-003): every inclusion or
    exclusion the compiled SQL decides (structured and mixed), by rule, and a note criterion flagged
    ``time_sensitive``. Before, only the flagged ones: the flag is a model's output at compile time, and a ruleset
    with none (RA-JAK: "serious infection in the last 30 days" unflagged) had no re-check at all."""
    return {
        c.id for c in rs.active() if c.kind in ("inclusion", "exclusion") and (c.class_ in FILTERED or c.time_sensitive)
    }


def study_sources(db: Any, ruleset: str, but_job: str = "") -> list[str]:
    """The stored lists a micro-batch of ``ruleset`` reads to know whom the study has seen since its last SCREEN:
    that SCREEN's candidate and excluded lists, and the latest micro-batch record after it (object keys). One
    function for the micro-batch (:func:`seen_sources`) and for retention, which keeps these for an open study
    whatever their age (T-704, D-458; scale review F-34)."""
    keys: list[str] = []
    screens = db.find(type_="SCREEN", ruleset=ruleset, state="done", limit=1)
    if screens:
        last = screens[0]
        keys += [
            o.minio_key
            for o in last.outputs or []
            if o.filename.startswith(("excluded_", "candidate_list_")) and o.filename.endswith(".json")
        ]
        for j in db.find(type_="MICROBATCH", ruleset=ruleset, state="done", limit=100):
            if j.job_id == but_job or j.received_at <= last.received_at:
                continue
            doc = next((o for o in j.outputs or [] if o.filename.startswith(NEW_DOC)), None)
            if doc is not None:
                keys.append(doc.minio_key)
                break  # newest first, and each record holds the ones before it
    return keys


def seen_sources(ctx: Ctx, rs: Ruleset) -> list[str]:
    """The stored lists of who a run looked at since the study's last SCREEN: that SCREEN's candidate and excluded
    lists, and the latest micro-batch record after it. Named on the job's first run (option ``seen_from``), so a
    resumed job and a re-run read the same ones."""
    fixed = (ctx.job.options or {}).get("seen_from")
    if fixed is None:
        keys = study_sources(ctx.orch.db, rs.id, ctx.job.job_id)
        fixed = ",".join(keys)
        _set_option(ctx, "seen_from", fixed)
    return [k for k in fixed.split(",") if k]


@dataclass
class Seen:
    """Whom the study's runs have looked at since its last SCREEN, from the stored lists (:func:`study_sources`)."""

    listed: set[str] = field(default_factory=set)  # on a candidate list: in the pool when it was written
    excluded: set[str] = field(default_factory=set)  # on SCREEN's excluded list
    earlier: set[str] = field(default_factory=set)  # screened by an earlier micro-batch (its record)
    again: dict[str, str] = field(default_factory=dict)  # pid -> the day a weekly run last screened it again
    out: set[str] = field(default_factory=set)  # screened by a weekly run and not listed (a record from D-642 on)

    @property
    def everyone(self) -> set[str]:
        return self.listed | self.excluded | self.earlier


def read_sources(ctx: Ctx, keys: list[str]) -> Seen:
    out = Seen()
    for key in keys:
        doc = json.loads(ctx.store.get(key))
        if "pids" in doc:  # a micro-batch record
            out.earlier |= {str(p) for p in doc["pids"]}
            out.again.update({str(p): str(d) for p, d in (doc.get("again") or {}).items()})
            out.out |= {str(p) for p in doc.get("out") or []}
        for r in doc.get("rows") or []:
            # a candidate list's row carries its tier; a row of the excluded list carries the failing criteria
            (out.listed if "tier" in r else out.excluded).add(str(r.get("pid")))
    return out


def read_seen(ctx: Ctx, keys: list[str]) -> tuple[set[str], set[str]]:
    """(every patient on the lists ``keys`` name, the ones on the micro-batch record among them)."""
    got = read_sources(ctx, keys)
    return got.everyone, got.earlier


def pool_as_received(ctx: Ctx, rs: Ruleset, keys: list[str]) -> list[dict[str, Any]]:
    """The pool as it stood when the job was received. A row this job wrote after its receipt that no earlier run
    listed is one of this job's own new patients (a resumed job, or a re-run on the pool the original left; a
    re-run's copy of the pool keeps no first-added time): it is not the pool's. Neither is the row this job wrote
    for a patient an earlier run had excluded (D-642): it is one this job brought back, and is screened again as
    on the first run."""
    got = ctx.job.received_at
    rows = ctx.orch.db.pool(rs.id)
    mine = [p for p in rows if p.get("job_id") == ctx.job.job_id and (_aware(p.get("added_at")) or got) >= got]
    if not mine:
        return rows
    # the pool's: on SCREEN's candidate list, or screened and listed by an earlier weekly run. Not the pool's: one
    # SCREEN excluded, or an earlier weekly run screened and did not list (the record's ``out``, D-642): the row
    # this job wrote for him is one it brought back. (A row's first-added time cannot tell: a re-run's copy of the
    # pool stamps it with the row's last evaluation.)
    src = read_sources(ctx, keys)
    listed = src.listed | (src.earlier - src.out)
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
    # D-477: and the consent rule of SCREEN (a refusal or a contact denial since the row was stored)
    kept -= decision_of(ctx).consent_off_lists(kept, "screen.opt_out_removed", where="pool")
    pool = [p for p in pool if p["pid"] in kept]
    # T-707 (D-476, review H3): a row stored under another criteria version was never evaluated on this one. It is
    # screened again below, not re-tiered (a row without a version is a test stand-in: the column is NOT NULL)
    stale = [p for p in pool if p.get("version") not in (None, rs.version)]
    stale_pids = {p["pid"] for p in stale}
    pool = [p for p in pool if p["pid"] not in stale_pids]
    week = {s.pid: s for s in every if s.pid in kept and s.pid in appts}
    # D-646: places of the allowance kept for the excluded patients in scope, counted before anything is spent
    incident = on_ingest or opts.get("incident", "auto") != "0"
    scope: list[Scoped] | None = None
    held = 0
    fixed = opts.get("excluded_kept")  # fixed on the job's first run, as the allowance is (review of D-646)
    if fixed is not None:
        held = int(fixed)
    if left is not None and incident and not on_ingest and excluded_percent(ctx) > 0:
        try:
            scope = screen_scope(ctx, rs, run_date, snapshot)
        except StepFailed:
            scope = None  # nobody the study screens is set: the screen below says so, and nothing is kept
        if scope is not None:
            before = read_sources(ctx, keys).everyone | pool_pids
            out_rows = {p["pid"] for p in pool if p.get("tier") == "excluded"}
            waiting = sum(1 for s in scope if s.pid in before and (s.pid not in pool_pids or s.pid in out_rows))
            if fixed is None:
                held = min(left * excluded_percent(ctx) // 100, waiting)
    if fixed is None:
        # the count reads the pool's stored tiers, which this job's own re-check rewrites: a resumed job and a
        # re-run keep what the first run kept, so they re-check the same patients (D-642, D-458)
        _set_option(ctx, "excluded_kept", str(held))
    front = None if left is None else left - held  # what the re-checks and the new patients may use
    ts = recheck_ids(rs)  # NEW-LIFE-3 (D-642): by rule, not by the model's flag
    # the re-check: the nearest visits first, within the night budget (the after-ingest run re-checks nobody)
    due = (
        sorted((s for s in week.values() if s.pid not in stale_pids), key=lambda s: (s.next_appointment or "", s.pid))
        if ts and not on_ingest
        else []
    )
    recheck = due if front is None else due[:front]
    fresh = evaluate_scope(ctx, rs, run_date, snapshot, recheck, only=ts, all_candidates=True) if recheck else {}
    t = threshold(ctx, rs)
    # the same note-block decision as SCREEN: no verifier, one model twice or a shut canary gate never exclude
    # on a note answer (D-276, review F-01; before, the re-tier below used the configured policy alone)
    may_block = decision_of(ctx).note_block(judge_for(ctx, rs)).may_block
    pool_rows: list[CandidateRow] = []
    changes: list[Change] = []
    stamp = job_stamp(ctx)  # evaluation time = the job's receipt: same inputs → same bytes (D-82)
    rechecked = {s.pid for s in recheck}
    by_id = rs.by_id()
    for p in pool:
        old = {v["id"]: CriterionVerdict.model_validate(v) for v in p["verdicts"]}
        # D-476 item 3 (review H1): a note fail that says nothing about itself was stored before the field
        # existed. Whether a pair gave it cannot be known from the row (its tier does not say: a coded criterion,
        # or the old F-01 defect, may have excluded it), so it never excludes from here on, and the row says so.
        # A fail written since carries final: true (it was allowed to exclude) or final: false.
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
            if prev is not None and prev.verdict in ("pass", "fail") and _not_asked(v):
                continue  # D-642: nobody was asked (a hold, no judge, the model down): the stored answer stands
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
    judging: dict[str, Any] | None = judging_info(judge_for(ctx, rs), ctx) if recheck else None

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
        again = behind if front is None else behind[: max(0, front - used)]
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
    back: list[str] = []  # excluded patients screened again (NEW-LIFE-4, D-642)
    back_carried = 0
    back_rows: list[CandidateRow] = []
    skipped = ""
    out_in_scope = 0  # excluded patients in the study's scope as this run finds them (D-646)
    if incident:
        room = None if left is None else max(0, left - used)  # for the new and the excluded together
        new_room = None if front is None else max(0, front - used)
        try:
            practitioners_of(ctx, rs)  # who the study screens: unset means no new-patient screen, not a failed run
        except StepFailed as exc:
            skipped = exc.message
        if not skipped:
            src = read_sources(ctx, keys)
            earlier = src.earlier
            seen = src.everyone | pool_pids
            # pool rows that are excluded as this run leaves them (not the ones of another version: screened above)
            pool_out = {r.pid for r in pool_rows if r.tier == "excluded"}

            def select(scope: list[Scoped]) -> list[Scoped]:
                nonlocal carried, back_carried, out_in_scope
                cand = [
                    s for s in scope
                    if s.pid not in seen
                    and (not on_ingest or (s.next_appointment is not None
                                           and date.fromisoformat(s.next_appointment[:10]) <= horizon))
                ]  # fmt: skip
                cand.sort(key=lambda s: (s.next_appointment is None, s.next_appointment or "", s.pid))
                take = cand if new_room is None else cand[:new_room]
                carried = len(cand) - len(take)
                if on_ingest:  # the after-ingest run looks at new booked patients only
                    return take
                # NEW-LIFE-4 (D-642): looked at before, not listed, still in scope: excluded by SCREEN or by an
                # earlier weekly run, or an excluded row of the pool (a re-check or a version re-screen left it).
                # The one screened again longest ago first (never: first), then by visit
                out = [s for s in scope if s.pid in seen and (s.pid not in pool_pids or s.pid in pool_out)]
                out.sort(
                    key=lambda s: (
                        src.again.get(s.pid, ""),
                        s.next_appointment is None,
                        s.next_appointment or "",
                        s.pid,
                    )
                )
                more = out if room is None else out[: max(0, room - len(take))]
                out_in_scope = len(out)
                back_carried = len(out) - len(more)
                back.extend(s.pid for s in more)
                if room is not None and carried:  # a place kept for an excluded patient and not needed (D-646)
                    take = cand[: len(take) + max(0, room - len(take) - len(more))]
                    carried = len(cand) - len(take)
                return take + more

            srun = run_screen(ctx, rs, run_date, snapshot, select=select, scope=scope)
            screened = [s.pid for s in srun.scoped]
            if screened:
                judging = srun.judging
            new_rows = [
                r.model_copy(update={"changed": [v.id for v in r.criteria]}) for r in srun.rows if r.tier in LISTED
            ]
            persist_pool(ctx, rs, new_rows)
            back_rows = [r for r in new_rows if r.pid in set(back)]
            # one who was an excluded row of the pool and is listed again has one row: the new one
            again_listed = {r.pid for r in back_rows}
            pool_rows = [r for r in pool_rows if r.pid not in again_listed]
            week_rows = [r for r in week_rows if r.pid not in again_listed]
            cascade_runs.append(srun)
            looked = {**src.again, **dict.fromkeys(back, run_date.isoformat())}
            record = {
                "ruleset": rs.id,
                "run_date": run_date.isoformat(),
                "pids": sorted(earlier | set(screened)),
                "again": dict(sorted(looked.items())),
                # screened by a weekly run and not listed, as this run leaves it: a later job that brings one back
                # knows the row is its own (pool_as_received)
                "out": sorted((src.out | set(screened)) - {r.pid for r in new_rows}),
            }
            body = json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
            ctx.publish(f"{NEW_DOC}{rs.id}_v{rs.version}.json", body, "phi", [])  # the console and the next run only
    have = [r for r in cascade_runs if getattr(r, "s2b_sources", None) is not None]
    if have:  # T-203b (D-449): only when the flag vec.s2b was on; one file for the job's screens
        if len(have) > 1:
            have[-1].s2b_sources = {p: v for r in have for p, v in r.s2b_sources.items()}
        publish_s2b_source(ctx, have[-1])
    ctx.metrics(patients_scoped=used + len(screened))
    night_done(ctx, used + len(screened))  # T-704 (D-458): what this job did not use is the next one's
    over = len(due) - len(recheck)
    # D-646: weekly runs until every excluded patient in scope has been screened again once. The figure follows
    # from what this run really kept and really carried (lane C2's finding: from the nominal share it said "1 run"
    # while some were carried, when the run's own re-check had added to the excluded). None: nobody is in scope,
    # or no place was kept, so no run is sure to reach them; 1: no night budget, or the places kept reach all
    full_pass: int | None
    if on_ingest or not out_in_scope:
        full_pass = None
    elif left is None:
        full_pass = 1
    elif not held:
        full_pass = None
    else:
        full_pass = max(-(-out_in_scope // held), 2 if back_carried else 1)
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
            "new_screened": len(screened) - len(back),
            "new_carried": carried,
            "excluded_rescreened": len(back),
            "excluded_back": len(back_rows),
            "excluded_carried": back_carried,
            "excluded_in_scope": out_in_scope,
            "excluded_percent": excluded_percent(ctx),
            "excluded_kept": held,
            "excluded_full_pass_runs": full_pass,
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
            f"patients with an appointment in the next {window} days; criteria re-evaluated: "
            f"{', '.join(sorted(ts))}.",
            f"Verdict changes: {suppress(len(changes), cell)}; new patients screened: "
            f"{suppress(len(screened) - len(back), cell)}; new patients added to the pool: "
            f"{suppress(len(new_rows) - len(back_rows), cell)}.",
        ]
        if back or back_carried:
            lines.append(
                f"Earlier excluded patients screened again: {suppress(len(back), cell)} of "
                f"{suppress(out_in_scope, cell)} in scope; back on the list: {suppress(len(back_rows), cell)}."
            )
            if back_carried and excluded_percent(ctx) == 0:
                lines.append(
                    "No share of the night budget is kept for them (TB_MICROBATCH_EXCLUDED_PERCENT is 0): they are "
                    "reached only when the re-checks and the new patients leave room."
                )
            elif back_carried and full_pass is None and (left or 0) * excluded_percent(ctx) // 100 == 0:
                lines.append(
                    f"Tonight's allowance was too small to keep a place for them ({excluded_percent(ctx)} % of it "
                    "is less than one patient)."
                )
            elif back_carried and full_pass is None:
                lines.append(
                    "No place was kept for them tonight: none was counted when the run began (this run's own "
                    "re-check excluded them). They are counted at the start of the next run."
                )
            elif back_carried and str(suppress(out_in_scope, cell)) == str(out_in_scope):
                # an aggregate output: with the places a run keeps, the figure gives the count away, so it is
                # printed only where the count itself is (review of D-646; the audit holds it either way)
                lines.append(
                    f"With the places of the night budget kept for them tonight (a share of "
                    f"{excluded_percent(ctx)} %), a full pass takes {full_pass} weekly runs."
                )
    if behind:
        lines.append(
            f"Criteria version {rs.version}: {suppress(len(again), cell)} pool patients last evaluated against an "
            f"earlier version were screened again; {suppress(len(waiting_rows), cell)} wait for the next weekly run "
            "and are listed for review."
        )
    if left is not None and (over or carried or back_carried):
        lines.append(
            f"Night budget reached ({night_budget(ctx)} patients a night): {suppress(over, cell)} re-checks, "
            f"{suppress(carried, cell)} new patients and {suppress(back_carried, cell)} excluded patients carried "
            "over to the next run."
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
