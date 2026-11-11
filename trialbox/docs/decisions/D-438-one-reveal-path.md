# D-438 One reveal path: every chart-number reveal through one service function, one hourly cap in the store, one audit shape

- **Task:** T-103 (`docs/plan/28-master-plan-v6.md` §6.2; TB-ASSESS-01 T-103)
- **PR:** this branch (`agent/T-103-one-reveal-path`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-024 (the reveal part), CR-017 (long term), ROLE-016
- **Builds on:** D-143 (who sees chart numbers), D-147 (the delegation log), D-273 (PV-2, PV-15: the job page through
  the same path, signed role and scope), D-280 / D-430 (break-glass, one rule), D-425 (`permit` at every call site).
  It takes the place of the old reservation D-220 ("One reveal path", TB-ASSESS-01), which stays unused.

## Decision

1. **One function.** `console.reveal.identifier(sess, study, pid, purpose, reason, ...)` is the only code in the
   console that asks for a chart number. The five routes that show one (the patient page, `/api/v1` reveal, the job
   page, the candidate page, the referral print) are thin handlers over it. A later surface (the EMR launch link of
   T-301a / T-320a) calls the same function with its own `purpose`; it gets nothing else.
2. **The rule is `permit` and break-glass.** The account reveals by its own rights when the `id.reveal` row allows its
   role, it sees the study, and (for a role whose `task.*` rows the delegation log decides) the log reaches it for
   "screen". Otherwise the one break-glass rule decides (an open grant for that patient, or for the job that is the
   study's latest list), and the reveal is signed `breakglass`. No role name is compared inline.
3. **A reason, and words for "other".** A reason from the D-143 list is required on every surface; "other" needs a
   written note of 10 characters or more (ROLE-016), kept in the audit record.
4. **One cap, in the store.** At most `TB_REVEAL_MAX_PER_HOUR` (default 60) chart numbers per person per rolling hour
   across every surface together, counted in the study-team store (`team.candidate_views`, kind `reveal`; Postgres
   with an advisory lock per person, so two console processes share it). `TB_CANDIDATE_VIEWS_PER_HOUR` now caps the
   candidate *views* only. A chart number shown in a request line (`console.view_id`) counts against the same cap.
   The orchestrator keeps its own per-person cap as the back end's backstop, now in its store too
   (`orch.id_limits`), not in process memory; the export cap moves with it.
5. **One audit shape.** A reveal is one `console.reveal_patient` event with `pid`, `role`, `study`, `purpose`,
   `reason`, `basis` (the matrix basis, `log` or the grant), `cap` (`n/limit`) and `via`; a refusal after sign-in is
   one `console.reveal_refused` event with the same fields and `refused` (`role`, `delegation`, `reason`, `note`,
   `cap`, `grant scope`, `back end`). The orchestrator's `screen.reveal` carries the purpose and reason it was sent.
6. **The orchestrator asks the matrix.** `/jobs/{id}/reveal` and the registry export give identifiers to a signed
   role the `id.reveal` row allows, or to the signed role `breakglass` (the console holds the grant); the
   duplicated `ID_ROLES` set is gone.

## Not decided here

- Counting the reveal cap per site rather than per box, and a different cap per role.
