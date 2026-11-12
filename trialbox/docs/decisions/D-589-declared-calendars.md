# D-589 A site declares the calendar of a date column; placeholder dates are declared too

- **Task:** NEW-DIN-1, the rest (findings DIN-001, DIN-012, DIN-014 of the deep review of 2026-11-12, `docs/reviews/2026-11-12-deep-review/08-data-input.md`; plan v7.2 section 5, lane E, wave 1)
- **PR:** this branch (`agent/NEW-DIN-1-declared-calendars`), stacked on NEW-DIN-7 (#375)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** PR #323 (the stop-gap: a date that is not a western calendar date is a refused row), `tb_common/dates.py`
  (the Republic-of-China and Japanese-era rules of the sheet path)

## Context

Since #323 the feed refuses a Republic-of-China date (`1150501`) instead of reading the year 1150. A Taiwanese
source that writes its dates that way now has every row refused: safe, and useless. The feed has to read such a
column, and it must not guess: `1101231` is 2021-12-31 in one calendar and nothing in the other, but `201208151000`
is a date in both.

## Decision

1. **The site mapping says which calendar a column is in**: `tables.<table>.dates: {<column>: roc}`. The words are
   `roc` (Republic of China, year + 1911), `era` (Japanese era) and `western` (the default, as before). Nothing
   is detected from the values.
2. **`roc` reads** 7 digits `YYYMMDD` (`0490312`, `1150501`), alone or followed by `hhmm` or `hhmmss`; and a
   written date whose year has three digits (`115/05/01`, `115-5-1`, `049.03.12`) or follows 民國
   (`民國49年3月12日`), each alone or followed by a time `hh:mm[:ss]`. **A two-digit year is not read** (`490312`,
   `49/03/12`, and the 10 and 12 digit forms with a time): the same digits are a western date (`260512`,
   `201208151000` is 2012-08-15 10:00), and the review of this card showed twelve western years read as 1931.
   **`era` reads** `R8.5.1`, `令和8年5月1日`, `令和元年5月1日` (the letters and names of `tb_common.dates`), alone or
   followed by a time; a day the era never had (`平成31年5月1日`) is refused.
3. **A value of another form in a declared column is a refused row**, never read in the other calendar: a
   western `2026-05-01` in a `roc` column is refused. The result then passes the same year range as every date
   (1850 to ten years ahead).
4. **The value is made western when the row is made canonical** (`Mapping.normalize`), so the mapping's elements
   and its date conditions see one calendar. A value that could not be read refuses the whole row, whichever
   element reads the column. The data contracts (`TB_DATA_CONTRACTS`) read the row before that step: a site with
   contracts on types a declared column `string` in its contract, or the contract sets the column aside.
5. **Placeholder dates are declared**: `empty_dates: ["9999-12-31", "99991231"]` at the top of the site mapping.
   A date column that holds exactly one of them, or one of them followed by a midnight (`9999-12-31 00:00:00`),
   is empty, also for an element that reads the column as text. Undeclared, `9999-12-31` stays what #323 made it: a
   refused row. No placeholder is built in: a site's placeholder is a fact about the site.
6. **A mapping that declares a calendar for a column no resource reads as a date, an unknown word, or a
   declaration in the wrong place (`dates` at the top, `empty_dates` on a table) does not load.**
7. **Time of day (DIN-014).** `2026-05-12 08:30:00.000` keeps its time (the fraction is dropped); `24:00:00` and
   a minute or second of 60 or more are refused. Before, each of these was silently read as midnight.

## What a site must know

- Declare the calendar from `columns.json` / `day.json` of the first look (D-588): the report gives each date
  column's shapes.
- After a calendar or a placeholder is declared, one full load.

## Not in this card

- A compact Japanese-era form (`5080501`), a two-digit ROC year, and in a declared column a time written with
  上午 / 下午: refused, until a source shows one. In an undeclared (western) column a time the reader does not
  know (`下午 08:30`, `08:30 PM`) is still read as that day's midnight, as before this card.
- `services/lake/flatten.py` and the `fhir_bulk` source (lane B, FHIR cards): unchanged.
