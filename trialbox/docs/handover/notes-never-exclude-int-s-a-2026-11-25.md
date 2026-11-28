# INT-S-A: a note answer never takes a patient off the list (ring 0)

**Reader:** the integrator, the independent reviewer, and the people who build TrialBox

2026-11-25. The owner's ruling: the model sorts, it does not adjudicate. No answer read from the notes takes a patient
off the investigator's list, also when both models agree; only coded answers (and a person's) exclude. Decision D-1072,
superseding D-1069 point 1. High-risk: clinical logic. Synthetic data only.

## What was wrong

`matching.note_answer.note_answer_may` let an exclusion's "present" on a stated, affirmed quote exclude. Three places
read it: the cascade (`engine._map`: a hard fail at S3, the patient leaves, the remaining criteria are not judged), the
v1 evaluator (`evaluate.note_verdict`) and the status rule over a stored row (`decision.answer_of`).

## What is built

- **The one rule, in one place:** `note_answer_may` no longer returns `excludes`. The same answer is `review`, its
  reading stands (the row says "not met"), with the reason code `notes_suggest_not_eligible`.
- **What the page needs is kept:** the verdict, `affirmed`, both models' quotes (`evidence.opinions`, judge first) and
  both notes (`evidence.resource_refs`, the judge's first), on both judges and on v1. No contract field is new.
- **Judging goes on:** no note answer is a hard fail, so CAS-3 never stops a patient at S3 on one.
- **The CASE sheet** prints such an answer as it did ("not met", with its quote), now with the reason code.
- **The wording:** the console, mail, report, runbook, user guide and design pages no longer promise that two models
  agreeing excludes. They say the notes may speak against a criterion and the patient stays on the list. **The ja and
  zh-TW strings are to be checked by a clinician** (list in the pull request).
- **Held twice more** (the integrator's rulings): the status rule answers `unknown` to any note "not met", also on a
  criterion with no kind; the engine makes no note outcome hard, whatever the rule says. `TB_NOTE_BLOCK` is `never` by
  default and `both_agree` excludes nobody. The CASE sheet's word does not depend on the canary.
- The canary, the pair rule and `final` are unchanged.

## What it costs

SCREEN's cascade settings and judge, two stub models that agree, synthetic site-a, 362 patients with a booked
appointment in 180 days, eight rulesets (the stub's answers, not a forecast of real notes):

| | Before | After |
| --- | --- | --- |
| Patients a note answer excluded | 1 | 0 |
| Rows on the lists (review) | 117 (103) | 118 (104) |
| GZQO: rows, rows a day (days with a row) | 13, 1.08 (12) | 14, 1.08 (13) |
| Model calls, calls per patient read (87 read) | 201, 2.31 | 203, 2.33 |
| GZQO: calls, calls per patient read (14 read) | 39, 2.79 | 41, 2.93 |

## Not changed here

- `CascadeConfig.note_block` and `Effect`'s `excludes` stay as names that nothing reads or returns. The installer still
  writes `TB_NOTE_BLOCK=both_agree` and the doctor reads an unset one as `both_agree`; both only touch `final`.
- Feasibility's two absence rules (certified zero hits, index condition absent) exclude on text that is not there, with
  no model answer. SCREEN does not run them. A separate card, after ring 0.
- The findings are in `notes-never-exclude-int-s-a-2026-11-25/findings.json`.
