# D-387 The pre-screen log and the criterion not met on a screen failure

- **Task:** T-623 (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2; was T-406 of the deep review)
- **PR:** this branch (`agent/T-623-prescreen-log`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-108 (marks and the screening log), D-134 (lifecycle), D-147 (referrals and opt-outs), D-364 (the
  criteria version on every mark), D-311 (no development gates)
- **Closes:** LIFE-015, LIFE-016

## Context

The screening log held only patients with a screening number, and the number is given when the coordinator records
a contact outcome after Approach. A patient the investigator set aside, or one whose treating physician declined,
was on no per-patient log; only in counts (LIFE-015). Sponsors' pre-screening logs and E6(R3) expect the reason for
non-enrolment per patient reviewed. A screen failure had four reasons and no link to the criterion, although the box
knows the criterion ids (LIFE-016).

## Decision

1. **Every mark is a pre-screen row.** The pre-screen log is read from the marks (`pi_marks`), not stored again: one
   pseudonymous row per investigator mark, oldest first, approached or not, with the first-listed date, the criteria
   version the mark was made on (D-364), the mark, its reason, date and author, the screening number when one was
   given, the referral answer and the screening-log status and reason. A withdrawal is not a row of its own: it shows
   on the mark it took back ("mark taken back"); a mark followed by a newer one shows "a newer mark". Opted-out
   patients are on neither log (D-147). The pre-screen log is a section of the screening-log page and a second sheet
   (`pre-screen log`) of its XLSX, behind the same role checks: no new route.
2. **Five columns on the screening log**: the criteria version of the latest mark, the criterion not met with its
   version (`GZQO-EXC-06 (v3.0.0)`), the day of consent, the consent form version (`ic_version`) and the day of
   enrolment. The last four come from the lifecycle (`Lifecycle.screen_detail`, added to the subjects answer of the
   lifecycle API).
3. **A "not eligible" screen failure names the criterion.** `subject_step` gains `criterion` and
   `criteria_version` (data-core version 6, additive; older steps have none). On the participant page the reason
   "Not eligible" shows a pick list of the criteria on the study's latest candidate list; the console sends the
   criterion and that list's criteria version, never a typed version. With a list, "Not eligible" without a criterion
   or with one not on it is refused. Any other reason with a criterion is refused (`criterion_only`). The trail and
   the audit event carry both.
4. **The form feeds it too.** The built-in screening-log form gains `sl_criterion` and `sl_crit_version` (additive,
   shown when "Not eligible"); derivation keeps them on the screen-failure step.
5. **Wording.** A patient "did not meet" a criterion (満たさなかった基準, 未符合的條件); no verdict word (T-116).

## Consequences

- The three-marks walk gives three pre-screen rows and one screening-log row
  (`tests/console/test_prescreen_log.py`).
- No new table: the pre-screen log is a view of `pi_marks`; the two new columns sit on `subject_step` (R-10).
- Sponsor column layouts for the pre-screen log stay with T-302; the CDISC IE rows fed from the criterion are T-619b.
