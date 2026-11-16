# D-982 One age fact decides once

- **Task:** F5 of the integrator's root-cause review of the P1b run (#639, 2026-11-16). One age fact decided twice in sigir's rulesets, for example NCT01790477 with INC age ≥ 18 and EXC age ≤ 17. A minor then failed two criteria, and the counts and reasons said it twice. **Date:** 2026-11-16. **Status:** reserved.
- **Decision** (`postprocess.decided_once`, at the end of `postprocess`, as proposed on #639 and agreed by the integrator). An exclusion whose whole logic is one age atom (no sex), and whose bound is the exact complement of an inclusion's (`max m-1` against `min m`, `min M+1` against `max M`), is kept but marked rejected. Its review comment names the inclusion ("the inclusion decides it alone (approve this to keep both)"), and it is flagged `restates_inclusion` and `needs_review`.
  - The inclusion alone decides.
  - The review sheet shows the exclusion as "reject", which the reviewer may change.
  - No patient's answer changes.
  - These are left alone: a narrower exclusion (over 75 under an 18+ inclusion), a bound that is not the complement, an inclusion that is a range, and an age with sex.
- **On the run's data:** 3 exclusions ("Participant is under 18 years old.", "Individuals under age 18", "age < 18 years"). The review counted 5. The other two put the inclusion's age in `value`, which D-948 repairs, after which this rule applies.
- **Test:** `tests/unit/test_age_decided_once.py`.
