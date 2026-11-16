# D-762 An opt-out keeps the numbered screening-log row

- **Task:** NEW-LIFE-5 (plan v7.3, wave 4, lane C: lifecycle repairs; the deep review of 2026-11-12, LIFE-005;
  `37-remaining-work-split.md`, lane C2's queue)
- **PR:** this branch (`agent/NEW-LIFE-5-opt-out-keeps-the-numbered-log-row`), from master after train 15
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-147 (an opted-out patient is on no list), D-273 (PV-4: who opted out is private), D-387 (the
  screening and pre-screen logs), D-436 (the monitor's SDV pages), D-441 (the trial record of a consented or enrolled
  subject stays after an opt-out), D-477 (the one register read, merged charts too)

## The problem

The screening log, its XLSX, its `/api/v1` twin and the monitor's list and sheet left out every patient on the
opt-out register, also one who had consented or enrolled. A screening number vanished from the log (GZQO-0003
between 0002 and 0004) with no row and no reason. An enrolled subject was missing from the enrolment columns and the
monitor could not open their sheet (404, "as if not there"). D-441 keeps the trial record of a consented or enrolled
subject; the log did not. **Confirmed by a test** before the change (kept failing output: `life5-fail.txt`).

## The decision

- **A patient given a screening number keeps the row**, on the page, in the XLSX and in `/api/v1`: the number, the
  first-listed and number-given days, the status and its reason, the criterion not met, the consent and enrolment
  days, the REDCap record and subject numbers, and the day of the opt-out ("Opted out of further research use on
  <date>", in the three languages; "yes" and "a merged chart" when the opt-out reached the patient through a merged
  chart, which has no date of its own).
- **What does not stay: who and the contact work.** The row has no pseudonym (no link to the patient page), and no
  investigator mark, contact outcome, referral or IRB-warning override. The XLSX gains one column at the end,
  `opted_out` (`datacore.sponsor.LOG_COLUMNS`, so a sponsor layout may name it; not a date column, since a merged
  chart gives "yes").
- **A patient never numbered stays off every list** (D-147, D-273): the pre-screen log (one row per investigator
  mark, by pseudonym), the week and candidate lists and the cohort list are unchanged. A numbered patient's row is on
  the screening log, so no number is lost.
- **The monitor's list and sheet follow the same rule.** An enrolled subject who opted out is a trial subject still:
  listed and opened, with the day of the opt-out, never the pseudonym (the monitor pages never showed it). The sheet
  is no longer refused with `why: opted_out`.
- **One read of the register's days** (`Helpers.opted_out_on`): the pseudonyms of `gone()` (D-477, merged charts
  included) with the site's day each was opted out: the first opt-out event since the patient's last lift, not a
  later repeat (a person's own opt-out after the registry's is an event of its own, D-441).
- **This narrows D-147 and D-273 (PV-4) for numbered patients, as LIFE-005 asks.** A number is given at referral,
  before any approach, so a referred patient who never consented and then opted out now shows as a numbered row
  that says "opted out". The row names nobody, but whoever knows which person a number is learns that they opted
  out; so does a sponsor whose layout names `opted_out`. A numbered row is a trial-log fact the site must account
  for (ICH E6(R3) screening log); a patient never numbered is still on no list.
- **The monitor sees what was recorded; nothing new is recorded.** The monitor's sheet of an enrolled subject who
  opted out shows the CRF values already decided, their citations and trail. The site's EDC pages still refuse new
  entry and copy from the hospital's records for an opted-out patient (`edc.opted_out`, D-441): the opt-out stops
  further use of the hospital's data, not the account of the trial record already made. A monitor's finding on such
  a subject is answered on paper or in the sponsor's EDC, as for any value not drawn from the hospital's records.

## What the review of the old behaviour pinned

`tests/console/test_sdv.py` held the old rule (the opted-out enrolled subject 404 and off the list). Its assertions
now hold the new one: the sheet opens with `data-testid="sdv-opted-out"` and no pseudonym, the list names the
subject with the day, and the visit record's subject list includes them.

## The review

One adversarial review: NOT SOUND on the first pass. The day shown was a later repeat of the opt-out (fixed and
held by a test); the record did not say how the rule narrows D-147 for numbered patients, nor that the EDC still
refuses new entry for them (both said above); the tests did not cover repeated events, a lifted opt-out, a numbered
patient who never consented or a merged chart (added).

## Reuse check

`Helpers.gone()` stays the one register read of the pages; `opted_out_on` reads the register's own `events()` for
the days. The XLSX header is still `sponsor.LOG_COLUMNS`. No new store, route or permission.

## Dropped (D-311)

No sign-off step.
