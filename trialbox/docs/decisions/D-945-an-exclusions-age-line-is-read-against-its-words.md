# D-945 An exclusion's age line is read against its words

- **Task:** F1 of the integrator's root-cause review of the P1b run (#639, 2026-11-16; it corrects part 1 of the 11:25 red: no birth date was missing). NCT00606840's exclusion EXC-02, "Age outside of range specified", came out of ir_extract as `{"domain":"demographic","quantifier":"all","age":{"min":18,"max":35},"derived":"egfr"}`, which is the inclusion's range. `_convert_logic` kept every key, and D-796's `_positive_logic` catches only `none` and `not(x)`. So the exclusion removed every patient inside the range (an eligible 25-year-old), with no flag. **Date:** 2026-11-16. **Status:** reserved.
- **Decision** (`postprocess.exclusion_age`, after the negated-exclusion rewrite). An exclusion whose whole logic is one age atom (no sex) is read against its line and against the inclusions' age bounds (`inclusion_ages`, read from the raw logic):
  - **An outside range is inverted only when the range is known.** A range (a minimum and a maximum) whose line says outside / not within / not between / beyond / 範囲外 / 以外 / 範圍外 / 不在, next to an age word, a number or the range, becomes `not(range)` with the flag `age_range_inverted`. The range is known when both its numbers are written in the line, or when it is exactly an inclusion's range. In the second case the complement decides exactly as the inclusion does, so it can exclude no one the inclusion keeps. An outside range from nowhere goes to a person (`age_range_exclusion`).
    - The integrator's rule was to send every such line to a person. Inverting where the range is known changes no patient's answer. It only spares a person's check on every pair, so I kept it, and I say so on #639.
  - **Any other range goes to a person:** `age_range_exclusion`, or `exclusion_restates_inclusion` when it is an inclusion's range.
  - **One bound equal to an inclusion's bound restates the inclusion and goes to a person** (`exclusion_restates_inclusion`). One bound inside the inclusion (over-75s excluded under an 18+ inclusion) is an ordinary exclusion and stays. The review's "equal or lies inside" would have sent those ordinary exclusions to a person, so "inside" applies to a range only by the rule above.
  - **One bound pointing the other way, or a line pointing both ways, goes to a person** (`age_direction`):
    - under / below / younger / < / ≤ / ≦ / 未満 / 以下 with a minimum;
    - over / older / > / ≥ / ≧ / "75+" / 以上 / 超 with a maximum;
    - both directions with a single bound ("< 18 or > 65" as `min 65`).

    以下の ("the following") and 超音波 are not bounds.
  - **A missing birth date is unknown.** The compiled SQL's age is NULL, so the answer is unknown, never an exclusion (D-914 holds).
- **Adversarial review** (this card): one blocker (≥, ≤ and "75+" were not read) and three lesser issues (two-way lines; outside words not about age, such as "not in remission"; 以下の / 超音波). All are fixed, and each case is in the test.
- **Not in this card:** F2 to F6 of the review (fractional and month ages, stray fields, one age fact deciding twice, inferred diagnoses).
- **Test:** `tests/unit/test_exclusion_age_lines.py`, including the stored output of NCT00606840 EXC-02 on a lake: a 25-year-old is not excluded, a 50-year-old is, and no birth date gives unknown.
