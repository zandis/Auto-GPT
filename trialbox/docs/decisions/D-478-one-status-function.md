# D-478 One function where a verdict becomes a status; the verdict carries its basis

- **Task:** T-709 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.1, wave D; TB-PLAN-06.1)
- **PR:** this branch (`agent/T-709-status-of`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Measures:** H2 and M1 (a to d) of `docs/reviews/2026-11-12-architecture/decision.md`, and the rest of H1 (card
  AD-2; root cause R1: a verdict has no owner once it leaves the engine); T-652's open acceptance (the decision
  table is called by no engine, TB-PLAN-06.1 §4.3)
- **Builds on:** D-476 (T-707: `final`), D-477 (T-708: the decision context gives the threshold and the note-block
  decision), T-652 (`services/matching/verdict.py`), D-95/D-97/D-276 (a single model never excludes), T-603 (a
  record that did not fit is flagged), D-441 (contact denial), D-459 and D-460 (the two tests that measure it)

## Context

Three functions turned a patient's verdicts into a status, with four rules that differed: the v1 `tier`
(`orchestrator/scenarios/evaluate.py`), the cascade's own tiers mapped by `verdicts_of`, and NAV's `classify`
with `_ok`; CASE had none and printed one model's "not met" as not met. A low-confidence "met" was `high` on the
cascade and `review` on v1; NAV ignored the run's note-block decision and the over-budget flag, so one model's
answer dropped a patient with no review row.

## Decision

1. **`services/matching/decision.py`** holds the rule once:
   - `answer_of(criterion, verdict, policy)`: what one verdict says for eligibility: `yes`, `no` or `unknown`. A
     note answer says `no` only when it is final, a pair gave it, its confidence reaches the threshold and the run
     may exclude on notes; a "met" below the threshold or with notes left out says `unknown`; an unknown and a
     criterion a person decides say `unknown`.
   - `status_of(ruleset, verdicts, policy)`: `excluded` when an answer is `no`, `review` when one is `unknown`,
     else `high`, with the actions of the open criteria, the number of unknowns and the criteria that excluded.
   - The structured answer itself comes from T-652's table (`matching/verdict.py`): the v1 evaluator's
     `eligibility` is the table's.
2. **The verdict carries its basis.** `criterion_verdict.basis` (schema `candidate_list` 1.4.0): `coded` (the
   records), `pair` (two different models agreed), `single` (one model, or two clients of one model) or `person`.
   Beside `final` (D-476) it is what the rule needs, so a stored row can be read again without the run that wrote
   it.
3. **Every path calls it.** The v1 `tier`, the cascade's published status (`verdicts_of`), MICROBATCH's re-tier
   and NAV's `classify` call `status_of` / `answer_of`; CASE prints `answer_of` per criterion, so one model's "not
   met" is printed as "to check", with the model's reading kept as evidence.
4. **The policy is an argument** (`Policy`: the threshold, whether notes may exclude; from the decision context).
   T-216's "unknown with a reason" rule for counts becomes one more field of it, not a second rule.

## Consequences

- The cascade no longer lists a patient as `high` on a "met" below the confidence threshold: `review`, as v1 did.
- NAV lists a patient whose exclusion one model called present, with a row to confirm, instead of dropping them.
- The expected-failure tables of T-705 and T-706 lose their H2, M1 and H1 lines; what remains is H4 (T-710) and
  FEAS's unknown rule (T-216).
