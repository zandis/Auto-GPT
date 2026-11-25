# D-1072 A note answer never takes a patient off the list (ring 0)

- **Task:** an owner's ruling, numbered by the integrator; card INT-S-A (the engine's note rule)
- **Date:** 2026-11-25
- **Status:** accepted (the owner's ruling, relayed by the integrator to card INT-S-A on 2026-11-25)

## Ruling

1. The model sorts, it does not adjudicate. No answer read from the notes takes a patient off the investigator's
   list, also when both models agree on a quote that states the condition. Only coded (structured) answers, and a
   person's, exclude.
2. A note "not eligible" goes to review and stays on the list. Its row keeps the verdict ("not met"), both
   models' quotes with their notes, and the reason code `notes_suggest_not_eligible` ("the notes may speak against
   this criterion: please confirm"), so the page can show it (how it is shown is another card). The product's words
   say the notes may speak against a criterion; they never say the notes excluded the patient.
3. Because a note answer no longer ends a patient, the judge reads every note criterion of the patient (the CAS-3
   stop after the first hard fail no longer happens on a note answer); the investigator sees each one.

## What it changes in earlier records

- D-1069 point 1 is superseded: "Only an exclusion criterion whose quote states the condition removes a patient,
  and only when two different models agree" no longer holds. An inclusion's "not met" from the notes stays review
  (D-1069 point 1, first half, unchanged). Points 2 to 5 of D-1069 stand.
- D-95 (`TB_NOTE_BLOCK=both_agree`), D-97, D-117 (the canary gate) and D-276 stay as they are: they still decide
  whether a run's note "not met" is final and which runs are a pair, and the canary stays a health check. None of
  them can make a note answer exclude any more.
- The one rule is `matching.note_answer.note_answer_may`, read by the cascade, the v1 evaluator and the status rule
  over a stored row; it no longer returns `excludes`.

## Where the wording comes from

The owner's ruling on the sorting assessment (point 4, the strict reading: two models that agree are still a model
answer), relayed by the integrator in the card INT-S-A.

## Used by

The engine (every path: SCREEN on the cascade and on v1, CASE, NAV, MICROBATCH and its re-checks); the property
test `tests/property/test_notes_never_exclude.py`; the PI's page card that shows these rows.
