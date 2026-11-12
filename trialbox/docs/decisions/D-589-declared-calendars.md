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
2. **`roc` reads** 7 digits `YYYMMDD` and 6 digits `YYMMDD`, each alone or followed by `hhmm` or `hhmmss`; and
   `115/05/01`, `115-5-1`, `115.05.01`, `民國115年5月1日`, each alone or followed by a time `hh:mm[:ss]`.
   **`era` reads** `R8.5.1`, `令和8年5月1日`, `令和元年5月1日` (the letters and names of `tb_common.dates`), alone or
   followed by a time; a day the era never had (`平成31年5月1日`) is refused.
3. **A value of another form in a declared column is a refused row**, never read in the other calendar: a
   western `2026-05-01` in a `roc` column is refused. The result then passes the same year range as every date
   (1850 to ten years ahead).
4. **The value is made western when the row is made canonical** (`Mapping.normalize`), so every later reader (the
   mapping's elements, its date conditions, the data contracts) sees one calendar.
5. **Placeholder dates are declared**: `empty_dates: ["9999-12-31", "99991231"]` at the top of the site mapping.
   A date column that holds exactly one of them is empty. Undeclared, `9999-12-31` stays what #323 made it: a
   refused row. No placeholder is built in: a site's placeholder is a fact about the site.
6. **A mapping that declares a calendar for a column no resource reads as a date, or an unknown word, does not
   load.**
7. **Time of day (DIN-014).** `2026-05-12 08:30:00.000` keeps its time (the fraction is dropped); `24:00:00` and
   a minute or second of 60 or more are refused. Before, each of these was silently read as midnight.

## What a site must know

- Declare the calendar from `columns.json` / `day.json` of the first look (D-588): the report gives each date
  column's shapes.
- After a calendar or a placeholder is declared, one full load.

## Not in this card

- A compact Japanese-era form (`5080501`) and a time written with 上午 / 下午: refused, until a source shows one.
- `services/lake/flatten.py` and the `fhir_bulk` source (lane B, FHIR cards): unchanged.
