# D-909 A ruleset where nothing decides sends every patient to review

- **Task:** red of lane G's frozen-commit run (#639, 2026-11-16: 16 public protocols compiled to "for a person" criteria only; SCREEN refused them); **Date:** 2026-11-16; **Status:** reserved
- **Decision:**
  - A ruleset with no coded and no note inclusion or exclusion (every criterion a person's, or none) is screened, not refused. Before, the cascade refused it ("has nothing that decides", review of D-788).
  - The cascade runs S0 and S1 only: consent, scope and the index date as always. Nobody is judged, and `metrics.nothing_decides` is set.
  - Every patient in scope is listed for review, with the person's actions. None is listed "high" and none under criteria not matched; a contact refusal is still never listed.
  - The report says so in en, ja and zh-TW (`screen.judging.nothing`).
  - The status mapping (`verdicts_of`) never lists a patient "high" when no outcome was decided by the records or the models.
  - It is the SCREEN counterpart of D-901 (FEAS).
- **Test:** `tests/unit/test_notes_only_ruleset.py` (`test_a_ruleset_where_nothing_decides_sends_every_patient_to_review`); `tests/unit/test_screen_cascade.py`.
