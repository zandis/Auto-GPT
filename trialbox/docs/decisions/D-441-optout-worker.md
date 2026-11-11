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
   or before today decides, an undated one counts as the oldest, `entered-in-error` is no statement. A later active
   consent lifts an opt-out only when the registry itself added it: an opt-out the office typed is never lifted by
   the feed. A lake without a consent table has nothing to copy; any other lake failure is reported, the register
   still applies and the next tick tries again (D-127: never read as "no refusals").
2. **Every screening path reads the register**, as it stood when the job was received (D-82): SCREEN and MICROBATCH
   (already, `drop_opted_out`), the cascade (and its own S0), NAV (new: the patient leaves NAV's lists, audited
   `nav.opt_out_removed` by count) and CASE (new: no sheet; `case.opt_out_refused`, without the pseudonym; the
   requester is told why). So after an opt-out, typed or from the registry, and one tick, no screening path lists
   the patient. NAV is a care-side list (NHI approvals); it follows the register because the notice promises that an
   opted-out patient's records are no longer used. The owner may narrow that.
3. **The worker** (`services/datacore/optout_worker.py`) runs in the orchestrator every `TB_OPTOUT_WORKER_MINUTES`
   (default 5, 0 off), also when the night schedule is on demand. One tick: the registry copy, then each store in
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
   yet run). A box without an OMOP store is not given one.
5. **A lift restores nothing by itself**, by design: the register's lift, then the next SCREEN and the next load bring
   the patient back. A withdrawn candidate stays withdrawn; the team re-adds them if they wish.

## Not done here (T-206b and others)

- Erasure: before-images in `tb_record_event`, lake snapshots and NDJSON, chunks, vectors, profiles, the embedding
  cache, earlier job outputs (`candidate_list_*.json`, `excluded_*.json`), the retention run's legal-hold check, the pid
  map's crypto-shred (T-206b).
- The exports that carried the pid listed from the flow ledger as steward tasks; the funnel's count (T-206b).
- FEAS counts, COHORT counts and the data-core exports (ODM, REDCap CSV) reading the register: FG D-278 (CR-026).
- A running SCREEN re-reading the register before it publishes (acceptance 4 of TB-ASSESS-01): it reads the register
  as of its receipt; a patient opted out while it runs is removed from the lists and pages by the shared readers
  (D-273) and from the pool and registry by the next tick, not from the job's own files.
- `contact: deny` on the v1 paths: the cascade keeps such a patient in counts and never lists them; the v1 evaluator
  lists them. It is not an opt-out and changes screening results, so it is left to a screening card.

## Tests

`tests/unit/test_optout_worker.py`: the registry rule; sync adds refusals and lifts only its own; one tick clears the
pool and withdraws open candidates, keeps consented and enrolled, audits counts only; a failing store and a failing
registry do not stop the rest; `register_store`; the job store's `pool_remove`; OMOP withholds at once, a load keeps
the patient out, a lift waits for the next load; a load tombstones a withheld patient the worker has not reached; after
one tick SCREEN/MICROBATCH, NAV and CASE leave the patient out, and an older job keeps its register (D-82).
