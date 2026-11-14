# D-688 A window of the first look that read nothing does not pass; `--day` reads a day as the column writes it

- **Task:** T-731 (the CGRD connector), found while preparing the owner's first look at the real connection; ordered
  by the integrator on 2026-11-14 as a fail-open in a check the owner is about to run
- **PR:** this branch (`agent/T-731-window-that-read-nothing`)
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI)
- **Builds on:** D-588 (the share report: the one file that may leave the site), D-589 (declared calendars)

## Context

The codebook of the CGRD research database writes its change times as compact character days (`20261110`, with
or without a time after it). `mapping_check --day 2026-11-10` compared such a column, as text, with
`2026-11-10 00:00:00`: no row matched, every table read nothing, and the report said **passed**. The same
comparison also left out a row written exactly `2026-11-10` in a column of ISO text (a shorter text sorts first).
Shown on a synthetic SQLite copy before the change.

## Decision

1. **`--day` reads the day as the change-time column writes it.** The column's type, when the driver tells it,
   says what to try: a date type is given the day as a date; a text column is given the day as text in each of
   `YYYYMMDD`, `YYYY-MM-DD`, `YYYY/MM/DD` (a time after the day is read with it, `20261110093000`); a column whose
   type is not told is tried both ways. Each form is first asked whether it holds a row (one row at most, nothing
   of it read); every form that does is read, and the table says which (`window_form`).
2. **Refused, and said:** a day written in the ROC calendar (`1151110`, `115/11/10`) or day-first (`10/11/2026`)
   is not read by `--day`. Such a table reads nothing and its note says which forms were looked for. An explicit
   `--since` / `--until` is used exactly as given (the owner's runbook used `--since 20261110` meanwhile).
3. **A window that read nothing is said for its table** (`read_nothing_in_window`, a note, and
   `tables_that_read_nothing` in the share report). One such table does not fail the run: a table without a change
   on that day is ordinary. **A run that read no row from any table fails**: it has checked nothing.
4. The share report gains only these words and counts; nothing of a row is in them.

## T-731 notes (from the same preparation, not changed here)

- The codebook's column types point to an Oracle database. No Oracle driver is in `uv.lock`; the owner's runbook
  borrows `python-oracledb` for the one run (`uv run --with oracledb`). Adding a driver for the night reader is a
  dependency decision for the owner, later.
- The shared medication template refuses a row with no daily dose, and CGRD's dictionaries state none: every
  medication row would be refused on a night run. To be settled from `day.json`.
- Each form asked may scan a large table whose change-time column has no index; the runbook says to stop and use
  fewer rows or an earlier day if a table takes long.

## Evidence

`tests/unit/test_mapping_check_window.py`: each of the three text forms and a date type (each failed before); a
ROC day, a day-first day and a day with no rows (each said and not passed; before: passed); one empty table among
others; an explicit window used as given. `tests/unit/test_cgrd_share_report.py` unchanged and green.
