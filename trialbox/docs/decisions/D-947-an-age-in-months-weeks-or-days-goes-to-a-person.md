# D-947 An age written in months, weeks or days goes to a person

- **Task:** F3 of the integrator's root-cause review of the P1b run (#639, 2026-11-16). ir_extract misread two NCT01260883 criteria, and neither was flagged:
  - INC-01, "2-18 months", came out as age 2 to 18 (read as years) with a stray `sex: female`, class mixed;
  - EXC-05, "<36 weeks gestation", came out as `age.max 36` on a condition atom.

  The age is complete years (D-442). **Date:** 2026-11-16. **Status:** reserved.
- **Decision** (`postprocess.age_in_short_units`, before the negated-exclusion rewrite). A structured or mixed criterion goes to a person, flagged `age_unit_not_years`, when any age bound in its logic is a number its own line writes in months, weeks or days. That covers months / mo / weeks / wk / days, か月 / ヶ月 / カ月 / 箇月 / 週 / 日 / 日齢, and 個月 / 天, including a range such as "6-24 months".
  - Only the bound's own number counts. An age in years beside a duration in months ("18 or older, able to attend for 12 months") is left alone.
- **Not chosen:** converting the bound to years. A 2-month bound is a fraction (D-946 sends a fractional bound to a person), and "gestation" is not an age at all.
- **Not in this card:** stripping an age from a non-demographic atom (F4, D-948). This card sends such a criterion to a person only when its line writes the number in short units.
- **Test:** `tests/unit/test_age_in_months_weeks_days.py`.
