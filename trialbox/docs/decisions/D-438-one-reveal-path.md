# D-438 One reveal path: every chart-number reveal through one service function, one hourly cap in the store, one audit shape

- **Task:** T-103 (`docs/plan/28-master-plan-v6.md` §6.2; TB-ASSESS-01 T-103)
- **PR:** this branch (`agent/T-103-one-reveal-path`)
- **Date:** 2026-11-11 (amended the same day after the adversarial review of PR #259)
- **Status:** accepted
- **Closes:** CR-024 (the reveal part), CR-017 (long term), ROLE-016
- **Builds on:** D-143 (who sees chart numbers), D-147 (the delegation log), D-272 (writers mask identifiers), D-273
  (PV-2, PV-4, PV-15: the job page through the same path, opt-outs, signed role and scope), D-280 / D-430
  (break-glass, one rule), D-369 (the guarded download), D-425 (`permit` at every call site). It takes the place of
  the old reservation D-220 ("One reveal path", TB-ASSESS-01), which stays unused.

## Decision

1. **One module.** `console.reveal` is the only console code that obtains a chart number from the back end or a
   workbook that carries them. `Reveal.identifier(sess, study, pid, purpose, reason, ...)` gives one patient's number;
   the five routes that show one (the patient page, `/api/v1` reveal, the job page, the candidate page, the referral
   print) are thin handlers over it, and the EMR launch link of T-301a / T-320a calls it with its own `purpose`.
   `Reveal.shown_in_line` decides the chart number in a job's request line, `Reveal.screening_log` the study's
   screening log with chart numbers (the registry export), `Reveal.workbook` a job's patient-level workbook
   (candidate, referral and navigation lists). A test walks every call in the console: an identifier source (the
   back end's reveal and registry export, the pid map) outside this module fails, and every reader of a stored job
   output is listed with the reason it carries no chart number.
2. **The rule is `permit` and break-glass.** The account reveals by its own rights when the `id.reveal` row allows its
   role, it sees the study, and (for a role whose `task.*` rows the delegation log decides) the log reaches it for
   "screen". Otherwise the one break-glass rule decides (an open grant for that patient, or for the job), and the
   reveal is signed `breakglass`. A grant covers one patient or one job, never a whole list: the screening log and
   the workbooks need the account's own rights, and the orchestrator refuses `breakglass` on the registry export.
   No role name is compared inline.
3. **A purpose and a reason, and words for "other".** Every reveal names a purpose. A reason from the D-143 list is
   required wherever a person asks (the five routes and the screening log; the export page has a reason form); "other"
   needs a written note of 10 characters that are not spaces (ROLE-016). The note is kept in the record for "other"
   only, masked (`mask_ids`, the note masker with the site's chart-number pattern, any run of six or more digits).
4. **One cap, in the store.** At most `TB_REVEAL_MAX_PER_HOUR` (default 60) uses per person per rolling hour across
   every surface together, counted in the study-team store (`team.candidate_views`, kind `reveal`; Postgres with an
   advisory lock per person, so two console processes share it). One patient's number is one use, a screening-log
   export one use, a workbook download one use, a request line one use per person, job and hour; the job page's own
   5-second refresh (`?auto=1`) takes no use and shows the line in clear only while that use is in the window. The
   use is taken before the back end is asked, so a try the back end refuses still counts. `TB_CANDIDATE_VIEWS_PER_HOUR`
   caps candidate *views* only.
5. **Mailed workbooks.** A list the job mails to its named recipients is the job's delivery (audited by the mail and
   the flow ledger) and is not counted against a person's cap. Downloading the same workbook in the browser is a
   reveal: one use and one record with the number of patients. A workbook that names a patient who has opted out
   since it was made is refused with the reason ("run the list again"), never served (D-273 PV-4); the register is
   read as it stands at the download, the same read a run makes at publish (`tb_common.optout.opted_out`, D-441).
   A chart number a person *types* (the opt-out door, the pasted-chart lookup) is an entry, not a sight: it is turned
   into a pseudonym on the box, capped and audited as `console.chart_lookup` (D-273 PV-6), and nothing is shown back,
   so it is outside this cap and outside the walk of decision 1.
6. **One record shape, written truthfully.** The back end is asked first; the record is written after it answers and
   before anything is shown (if it cannot be written, nothing is shown). A number given out is exactly one
   `console.reveal_patient` with `pid`, `role`, `affiliation`, `study`, `purpose`, `reason`, `via`, `basis` (`role`,
   `log` or the grant), `cap` (`n/limit`), and `count` for a list; a refusal after sign-in is exactly one
   `console.reveal_refused` with the same fields and `refused` (`role`, `delegation`, `purpose`, `reason`, `note`,
   `cap`, `grant scope`, `back end`, `not in the pid map`, `opted out`). The `pid` is written only when it is a
   pseudonym, else `invalid`; a list writes no pids. The request line's record is the same shape (`via`
   `request_line`), replacing `console.view_id`. The orchestrator's `screen.reveal` carries the purpose and reason.
7. **The orchestrator asks the matrix and caps each service.** `/jobs/{id}/reveal` and the registry export give
   identifiers to a signed role the `id.reveal` row allows, or (one patient or one job) to `breakglass`; the
   duplicated `ID_ROLES` set is gone. Its caps live in `orch.id_limits`: per calling service and signed name
   (`TB_REVEAL_MAX_PER_HOUR`, `TB_EXPORT_MAX_PER_HOUR`) and, so a token holder who signs a new name per call is
   capped too, per calling service in total (`TB_REVEAL_MAX_PER_HOUR_PER_SERVICE` 600, `TB_EXPORT_MAX_PER_HOUR_PER_SERVICE`
   60).

## Not decided here

- Counting the reveal cap per site rather than per box, and a different cap per role.
- **The longer fix for break-glass at the box:** the orchestrator trusts the console's signed `breakglass` role and
  does not see the grant. The console should sign the grant id, the pid or job it covers and its end into the actor
  assertion, and the orchestrator check that the request names that patient or job before the end. Listed, not built.
- Re-filtering an old workbook (dropping a patient who opted out since) instead of refusing it.
