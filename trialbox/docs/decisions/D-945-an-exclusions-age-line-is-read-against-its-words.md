# D-945 An exclusion's age line is read against its words

- **Task:** a red of the P1b run (#639, 2026-11-16, the integrator's 11:25 comment, part 2). NCT00606840's exclusion "Age outside of range specified" was compiled with the inclusion's range (min 18, max 35, quantifier all), so it excluded every patient inside the range. **Date:** 2026-11-16. **Status:** reserved.
- **Decision** (`postprocess.exclusion_age`, after the negated-exclusion rewrite). An exclusion whose whole logic is one age atom (no sex) is read against its line:
  - **A range said to be outside is its complement.** A range (a minimum and a maximum) whose line says outside / not within / not between / beyond / 範囲外 / 以外 / 範圍外 / 不在 becomes `not(range)`, flagged `age_range_inverted`. The model's own `not(range)` keeps its meaning: the negated-exclusion rewrite turns it into the range, and this rule turns it back.
  - **Any other range goes to a person** (`age_range_exclusion`). An exclusion of the patients inside a range is rare; a model that copied the inclusion's range is not.
  - **One bound pointing the other way goes to a person** (`age_direction`): the line says under / below / younger / 未満 / 以下 but the atom is a minimum, or over / older / 以上 / 超 but the atom is a maximum.
  - **A missing birth date is unknown.** The compiled SQL's age is NULL, so the answer is unknown, never an exclusion. That was already the rule; the test holds it.
- **Not in this card:** part 1 of the red (minimum ages failing for patients the physicians call eligible). In the code, a missing birth date is already unknown, so those rows need the run's data (asked for on #639).
- **Test:** `tests/unit/test_exclusion_age_lines.py`.
