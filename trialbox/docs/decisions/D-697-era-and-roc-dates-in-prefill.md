# D-697 Era and ROC dates in prefill

- **Task:** NEW-EDC-13 (deep-review finding EDC-016, Medium: dates in local form)
- **PR:** this branch (`agent/NEW-EDC-13-era-roc-dates`), from master
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-160 (a value always has a citation), review E-18 (a value drafted from a note must show in its
  quote)

## Context

(a) A date drafted from a note must appear in its quote; the check compared digits only. A note at the Taiwanese
site writes 民國113年1月10日 or 113/01/10, one at the Japanese site 令和6年1月10日 or R6.1.10: the Gregorian digits
are never there, so no date was ever drafted from a note, and the coordinator was told the quote was not found. A
Gregorian 2024年1月10日 failed too (no zero padding). (b) A lake date of year 0049 (a date that lost its century) was
drafted as a birth date with a citation. Review cases 4b and 4c; shown by tests before the change.

## Decision

1. **The quote's dates are read as written** (`prefill.dates_in`), each turned into a Gregorian date that must exist:
   - a Japanese era with 年月日 or with one separator repeated (令和6年1月10日, 令和6.1.10; the first year written 元),
     and the date must fall within that era (平成31年5月1日 and 昭和64年1月8日 never were);
   - a single letter era (R, H, S, T) only zero-padded (R06.01.10) and never right after a word, a digit, # or -:
     a lab flag or a code (CRP H6.1.10, S1.2.3) is not a date;
   - a ROC year with 民國 or 民国 and 年月日, or a three-digit year zero-padded with / or . (113/01/10); never a
     two-digit year (10/01/24 may be a day first), never an unpadded bare form (a dose 100/5/2);
   - a Gregorian date with separators, as eight digits standing alone, or with 年月日.
2. **A drafted date is in its quote only when the quote writes that date.** The old check gathered the quote's
   digits from across it, so a phone number, a lot number or two numbers side by side could "show" a date: gone.
3. **A drafted date before 1900 is `invalid`**: never a patient's date at these sites, always one that lost its
   century.

## Not in this card

- A ROC year written with 年 but no 民國 (113年1月10日) is not read (a false refusal: no draft, never a wrong one).
- A dateTime value is compared by its date; its time is not looked for in the quote (as before).

## The adversarial review (by running) and what it changed

| Finding | Severity | Outcome |
| --- | --- | --- |
| The old digits check accepted a date from a phone, a lot number or two numbers side by side | high (existing) | fixed, test first: the quote must write the date |
| A single letter before three numbers read as an era (CRP H6.1.10, S1.2.3) | medium | fixed, test first: zero-padded only, not after a word, digit, # or - |
| A bare three-digit year turned a dose or a lab number into a date | medium-low | fixed, test first: zero-padded only |
| Era dates that never were accepted | low | fixed, test first: each era's span |
| Era separators that differ accepted | low | fixed, test first |
| A dateTime's time is not in the quote | low (existing) | kept (Not in this card) |

## Evidence

`tests/unit/test_edc_era_roc_dates.py`: eight written forms of one date found in their quotes; the first year of an
era; another year, another day, no such month and a two-digit year not found; the review's twelve false readings
not found; a Gregorian date found in five forms; a birth date of year 0049 is `invalid`. Eleven failed before the
change; the review's failed before its fixes.
