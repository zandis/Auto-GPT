# D-985 An exclusion stands on a stated condition, never on an inference

- **Task:** F6 of the integrator's root-cause review of the P1b run (#639, 2026-11-16). A note exclusion was decided by inferring a diagnosis.
  - On jmed, both models agreed four times that a patient had a history of hypertension or diabetes. The quote named only an antihypertensive, or metformin with an HbA1c, and the judge's own reasoning said there was no stated history.
  - On sigir NCT01784523 the judge counted findings into SLE.
  - `both_agree` (D-95) does not protect against an inference both models share.

  **Date:** 2026-11-16. **Status:** reserved.
- **Decision** (`matching.inferred`, applied in the cascade's `_map`). An exclusion's "present" stands only on a verified quote (CAS-16) that states the condition. That means either:
  - three of the criterion's Han or kana characters in a row, after its generic words (既往, 患者, がある) are removed;
  - the first five letters of one of its English words;
  - or a diagnosis word (症, 病, 疾患, 既往, 併存, 診断, ICD, history of, diagnosed, known, comorbid, syndrome, disease, disorder).

  A quote with none of these is the models' inference: a drug, a dose, a value, or findings counted into a diagnosis. The answer becomes unknown ("inferred: the quote does not state the condition; review") and never a hard fail. The rule reads the quote, never the model's reason, which claimed a diagnosis on every one of these. An inclusion is never affected.
- **On the run's stored replies** (a cassette, with no model call):
  - Of jmed's 386 "pass" replies, 11 are inferences, all quotes of a prescribed drug: 降圧薬, カルシウム拮抗薬, ARB, ロサルタンとメトホルミン. The integrator's four rows are among them.
  - Of sigir's 11, 5: NCT01784523's findings for SLE, a calf pain read as claudication, and a groin mass.
  - No quote that names the condition is caught ("軽度の高血圧があり", "2型糖尿病という併存疾患").
  - Whether the models still reach such answers, and how often a stated diagnosis is phrased in a way this rule misses, is what only the GPU can show, on the D-517 gold.
- **Test:** `tests/unit/test_no_inferred_diagnosis.py`. The `_map` property test (`test_safety_properties`) gains a quote dimension: an exclusion present on an inference is never a hard fail.
- **Not in this card:** the v1 evaluator's path (`evaluate.py`). Screening runs the cascade, so v1 follows if the integrator wants it.
