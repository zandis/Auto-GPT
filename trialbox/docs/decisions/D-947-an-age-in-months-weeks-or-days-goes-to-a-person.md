# D-947 An age written in months, weeks or days is never compiled as years

- **Task:** F3 of the integrator's root-cause review of the P1b run (#639, 2026-11-16). ir_extract misread two NCT01260883 criteria, and neither was flagged:
  - INC-01, "2-18 months", came out as age 2 to 18 (read as years) with a stray `sex: female`, class mixed;
  - EXC-05, "<36 weeks gestation", came out as `age.max 36` on a condition atom.

  The age is complete years (D-442). **Date:** 2026-11-16. **Status:** reserved.
- **Decision** (`postprocess.age_in_short_units`, before the negated-exclusion rewrite). A structured or mixed criterion with an age bound is never compiled, and is flagged `age_unit_not_years`, when its line writes an age in months, weeks or days. A mixed one keeps its note question and the notes decide, as `demote_uncompilable` already does (D-98). Any other goes to a person. The line writes such an age when either of these holds:
  - **It says so outright:** "6-month-old", "aged 6 months - 17 years", "1 year 6 months", 生後, 月齢 / 週齢 / 日齢.
  - **A bound is a number the line writes in a short unit, and never as an age in years.** "One past" counts too, since "<36 weeks" may be written as at most 35.
    - The units are months / mo / mths / m / weeks / wk / days, か月 / ヵ月 / ヶ月 / カ月 / 箇月 / 週 / 日齢, and 個月 / 个月 / 天. A plain 日 counts unless it is part of a date, a day ordinal or a time limit.
    - Numbers may be spelled out, up to twelve, plus 18, 24 and 36.
    - So "Aged 18-75; 18 days washout" and "年齡20歲以上，20天內" are left alone.
- **Adversarial review** (this card): the first version missed ヵ月, 个月, "6-month-old", spelled-out numbers, compound ages, a bound rounded to years, and strict bounds. It also flagged durations beside an age in years, dates and "weekly". All are fixed, and each case is in the test.
- **On the run's data** (`raw-traces.json`), 3 of sigir's 118 age criteria are flagged: the two above, plus a condition atom's placeholder age. D-948 drops that placeholder before this rule runs. None of jmed's are flagged.
- **Not chosen:** converting the bound to years. A 2-month bound is a fraction, which D-946 sends to a person, and "gestation" is not an age.
- **Test:** `tests/unit/test_age_in_months_weeks_days.py`.
