# D-477 The decision context: one object every path reads the register, consent, the ruleset and the note-block decision through

- **Task:** T-708 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.1, wave D; TB-PLAN-06.1)
- **PR:** this branch (`agent/T-708-decision-context`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Measures:** M2, M3, the opt-out half of M4, L1 of `docs/reviews/2026-11-12-architecture/decision.md` (card AD-1;
  root cause R2: each path gathers its own inputs); CR-026 for FEAS and COHORT (owner decision OD-8)
- **Builds on:** D-383 (the snapshot pin handed to every job by `Ctx`: the model for this card), D-147 and D-441
  (the opt-out register on every screening path), D-95/D-97/D-276 (whether a note answer may exclude), D-127 (fail
  closed), D-459 (the path-independence test that measures it)

## Context

Six paths decide or count patients. Only the snapshot was handed to all of them. The opt-out register was read at
about twenty call sites under three rules, consent under three rules (and by five paths not at all), the
note-block decision at four places, and "today" in two ways.

## Decision

1. **One object per job.** `services/orchestrator/decision_context.py: DecisionContext`, reached as `ctx.decision`
   and built beside the pinned lake. A path reads through it: the pinned snapshot and the run date; the opt-out
   register (one function, with the surviving pseudonym of a merged chart; as of the job's receipt for the scope,
   as it stands now before anything is published or stored); consent (one rule: `tb_common.optout.registry_rule`
   as of the run date on the pinned snapshot); the approved ruleset with its pins; whether a note answer may
   exclude on this run (decided once per job and judge); the confidence threshold.
2. **A lint test keeps it so.** `tests/unit/test_decision_context_lint.py` fails on a call of `opted_out(`, on
   `FROM consent`, and on a read of the note-block decision outside the module (and the library function the module
   calls). Reads outside a job path that stay are a named list with a reason per line; the list only shrinks.
3. **Consent has one rule on every path.** The rule of the registry (the latest statement on or before the run
   date decides; an undated statement is the oldest; a statement entered in error is none; ties of one day fail
   closed). The cascade's S0 takes the state from the context instead of its own query.
4. **Counts honour the register** (OD-8): FEAS and COHORT read the register through the context.
5. **Goldens are unchanged**: they run without a trial database (no register) and reach none of these reads.

## Consequences

- The lines of `tests/property/test_path_independence.py` that this card fixes leave its `KNOWN` table.
- T-709 (the one status function) takes the note-block decision and the threshold from the context.
