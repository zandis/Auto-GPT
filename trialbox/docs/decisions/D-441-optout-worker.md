# D-441 Opt-out worker v1: one register on every screening path, a worker tick that withdraws and withholds

- **Task:** T-206a (`docs/plan/28-master-plan-v6.md` §6.2, wave 2; as TB-ASSESS-01 T-206, core)
- **PR:** this branch (`agent/T-206a-optout-worker`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-027 (the worker, v1 core), CR-019 (rest: NAV and CASE), CR-026 (rest: the registry's refusals on
  the v1 paths; FEAS counts and data-core exports stay with FG D-278), DATA-022 (in part), FIT-023 (in part)
- **Builds on:** D-147 (the register), D-273 (the shared readers), D-127 (consent fails closed), D-82 (re-runs),
  OD-8 (an enrolled participant's trial data stays), D-427 (T-112a)

## Context

The register (`tb_common.optout`) was read by SCREEN, MICROBATCH, the candidate pages, the reveal and the EDC, but not
by NAV or CASE, and nothing acted on it: open candidates stayed open, the candidate pool kept the patient, OMOP kept
every fact. The hospital's own refusals (the lake's `consent` table, FHIR Consent `rejected`) were applied only by the
cascade's first step (S0); the v1 evaluator (SCREEN with `TB_SCREEN_PIPELINE=v1`, MICROBATCH's re-check, NAV, CASE)
did not read them. The card names `dataops.consent` as the register's future home; T-112a delivered the `dataops`
batch tables only (the consent table is T-112b), so the register stays in schema `optout`.

## Decision

1. **One register.** The register is the one list of who said no. The worker copies the registry's refusals into it
   (source `emr`, by `worker:registry`), using the rule of COHORT's `n_contactable` (PR #257): the latest statement on
   or before today decides, an undated one counts as the oldest, `entered-in-error` is no statement. Two statements
   of one day are read fail-closed: an active consent sorts first, a refusal last (COHORT likewise: the
   not-contactable one wins). The feed lifts only on a later `active` statement, never on a missing row or a
   withdrawn, proposed or draft one, and only when every opt-out since the patient's last lift came from the
   registry. A person's opt-out is written as its own event even when the patient is already opted out, so an
   office opt-out typed after the registry's is never lifted by the feed and always leaves its audit row. A lake
   without a consent table has nothing to copy; any other lake failure is reported, the register still applies and
   the next tick tries again (D-127: never read as "no refusals").
2. **Every screening path reads the register**, as it stood when the job was received (D-82): SCREEN and MICROBATCH
   (already, `drop_opted_out`), the cascade (and its own S0), NAV (new: the patient leaves NAV's lists, audited
   `nav.opt_out_removed` by count) and CASE (new: no sheet; `case.opt_out_refused`, without the pseudonym; the
   requester is told why). A run received before the opt-out reads its scope as of its receipt, but reads the
   register again as it stands when it publishes: SCREEN's files, the mailed lists (SCREEN, MICROBATCH), the pool
   (`persist_pool`) and NAV's lists drop the patient, audited `screen.opt_out_at_publish` by count. This is the one
   touch of `screen.py` (`opted_out_now`, three calls). So after an opt-out, typed or from the registry, and one
   tick, no screening path lists or mails the patient. A re-run of an old job after an opt-out differs from the
   original by that patient (privacy over byte identity, D-82). An opt-out also hides every pid merged with the
   opted-out one (`pidmap.pid_alias`, chains followed, read where the service may read the pid map). NAV is a care-side list (NHI approvals); it follows the register because the notice promises that an
   opted-out patient's records are no longer used. The owner may narrow that.
3. **The worker** (`services/datacore/optout_worker.py`) runs in the orchestrator every `TB_OPTOUT_WORKER_MINUTES`
   (default 5, 0 off; PRODUCTION refuses 0 and starts the worker even with `TB_SCHEDULER=0`), also when the night
   schedule is on demand. The first tick runs at start. A failed tick is audited (`optout.worker_failed`) and the
   health line (`tb_common.metrics.check_optout`, from the orchestrator's `/models`) is red when the last tick failed
   or none completed for three intervals. One tick: the registry copy, then each store in
   `STORES` cleared for the patients opted out now, then one `optout.worker` audit event with counts only. A store
   that fails does not stop the others. v1 stores: `candidate_pool` (MICROBATCH's pool rows go), `candidate_registry`
   (`candidate` and `contacted` become `withdrawn`, reason "opted out (research-use register)"; `consented` and
   `enrolled` are kept and counted, OD-8), `omop` (below). A later card adds a store with `register_store` (a name and
   an idempotent `clear(pids, env) -> counts`); T-206b plugs in profiles (`tb_patient_profile`, T-204) and vectors
   (`services/vec`, T-203a) this way.
4. **OMOP withholds.** New table `omop.tb_withheld` (migration 7): the worker keeps it equal to the register and
   tombstones a newly opted-out patient's live records at once, with the reason `opted out` and the before-images
   (as any tombstone), under the loader's lock. The loader's one new call leaves a withheld patient's records out of
   every batch, so a later night never restores them (and tombstones them with the same reason if the worker has not
   yet run). The patient's consent statements (`tb_consent`) are kept: the refusal must reach an OMOP-built lake, or
   the next tick would read the registry as silent. A box without an OMOP store is not given one.
5. **A lift restores nothing by itself**, by design: the register's lift, then the next SCREEN and the next load bring
   the patient back. A withdrawn candidate stays withdrawn; the team re-adds them if they wish.

## Not done here (T-206b and others)

- Erasure: before-images in `tb_record_event`, lake snapshots and NDJSON, chunks, vectors, profiles, the embedding
  cache, earlier job outputs (`candidate_list_*.json`, `excluded_*.json`), the retention run's legal-hold check, the pid
  map's crypto-shred (T-206b).
- The exports that carried the pid listed from the flow ledger as steward tasks; the funnel's count (T-206b).
- FEAS counts, COHORT counts and the data-core exports (ODM, REDCap CSV) reading the register: FG D-278 (CR-026).
- `export_rows(as_of=...)` (the lake as of an earlier time, D-384) would restore a withheld patient's before-images;
  practice-site OMOP schemas (`omop_<hash>`) are never withheld (T-206b).
- The chart-number door (`POST /setup/pseudonym`, `services/sitesetup/service.py` `pseudonym`) stores the pid of the
  number typed; the merge is resolved when the register is read (`with_survivors`), not when it is written.
- `contact: deny` on the v1 paths: the cascade keeps such a patient in counts and never lists them; the v1 evaluator
  lists them. It is not an opt-out and changes screening results, so it is left to a screening card.

## Tests

`tests/unit/test_optout_worker.py`: the registry rule; sync adds refusals and lifts only its own; one tick clears the
pool and withdraws open candidates, keeps consented and enrolled, audits counts only; a failing store and a failing
registry do not stop the rest; `register_store`; the job store's `pool_remove`; OMOP withholds at once, a load keeps
the patient out, a lift waits for the next load; a load tombstones a withheld patient the worker has not reached; after
one tick SCREEN/MICROBATCH, NAV and CASE leave the patient out, and an older job keeps its register (D-82). Review
fixes: the two-tick, two-load sequence on the OMOP lake keeps the patient out (HIGH-1); only a later `active` lifts
(MED-1); an office opt-out after the registry's is its own event and never lifted (HIGH-2); same-day ties fail
closed, here and in COHORT (MED-2, `tests/unit/test_cohort_unit.py`); the pool and the lists drop a patient opted out
before publish (MED-3); a merged chart's opt-out hides the surviving pid (MED-4); PRODUCTION refuses an off worker,
a failing tick is audited and turns the health line red, the first tick runs at start (LOW).
