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
became the record. **Confirmed by tests** before the change (kept failing output: `jrn7-fail.txt`).

## The decision

- **A consent date after the site's day is refused when a person enters or changes it.** The built-in consent
  form's dates (`ic_date`, `ic_reconsent_date`; `lifecycle.CONSENT_DATES`) are checked by name in the data core's
  two entry paths (`sync.enter`, `PUT /studies/{rs}/data`; `sync.save_form`, the console's entry page): a day
  later than the site's day of the service's clock (`at`: a pinned test day included; `site.tz` from `TB_TZ`) is
  refused with the `max` reason naming that day. By name, so every study is held, also one that added the built-in
  forms before this rule (its stored copy of the form carries no limit). Only a value entered or changed is checked:
  a value already stored never blocks a later save of the form.
- **One that arrives another way is flagged.** The REDCap read-back writes REDCap's values as they are; a consent
  dated after the subject page's day is shown as `consent_in_future` in the three languages (`consent_order`).
- **A visit done before consent is a possible deviation** (`consent_after_visit`, deviation kind 2), as an enrolment
  before consent was (`consent_after`); the subject page already flagged both (`visit_before_consent`,
  `enrolment_before_consent`).
- **Not done:** a general `today` in the forms' limits (REDCap's word). Its first version here moved under stored
  values (a sponsor field with `min today` became invalid the next day), went out literally in the FHIR and ODM
  exports and did not reach existing studies; the review replaced it with the rule above. Paths that call the form
  check but are not a person's entry (the ODM import, EDC prefill) are not changed by this card.

## The review

One adversarial review: NOT SOUND on the first pass (the limit did not reach studies that added the forms before;
`today` moved under stored values; the exports carried the literal word; the site day ignored the pinned clock; the
read-back stored a future date silently; a visit before consent was no possible deviation). All met by the decision
above and held by tests on the real data core and lifecycle routes.

## Reuse check

The forms' own range check and REDCap's own word for it; `site.tz`. No new rule engine, route or permission.

## Dropped (D-311)

No sign-off step.
