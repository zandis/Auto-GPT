# D-770 A consent date in the future is refused

- **Task:** NEW-JRN-7 (the deep review of 2026-11-12, JRN-007; `37-remaining-work-split.md`, lane C2's queue)
- **PR:** this branch (`agent/NEW-JRN-7-consent-date-checks`), from master after train 15
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-129 (the built-in forms' field checks), LIFE-019 (enrolment and visits before consent flagged),
  D-270 (one "today": the site's day)

## The problem

The built-in consent form saved "Consent: given 2027-03-01" without a word, and the screening log and the enrolment
report carried it. Consent before any study procedure is the first thing an inspector checks, and a typing error
became the record. **Confirmed by a test** before the change (kept failing output: `jrn7-fail.txt`).

## The decision

- **REDCap's `today` is a date field's limit**, read as the site's day (`datacore.forms.site_today`, `site.tz`):
  `text_validation_min`/`max` of `today` (or `now`) is that day, a date as written stays as it is.
- **The consent dates take `today` as their maximum** (`ic_date`, `ic_reconsent_date` in the built-in forms): a
  later day is refused with the `max` reason (naming the day), as any value out of range, on every save path that
  checks the form (the console's entry page, the API).
- **The entry page's date picker stops at the site's day** too (the page shows `today` resolved).
- Consent after enrolment or after a visit was already flagged (`enrolment_before_consent`, `visit_before_consent`,
  and the possible deviation `consent_after`); nothing changes there.

## Reuse check

The forms' own range check and REDCap's own word for it; `site.tz`. No new rule engine, route or permission.

## Dropped (D-311)

No sign-off step.
