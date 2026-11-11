# D-362 A coded criterion row shows the record's value, unit, date and code

- **Task:** T-514 (wave P of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2)
- **PR:** this branch (`agent/T-514-coded-criterion`), on top of T-515 (#157)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** UX-008

## Context

On the patient page 17 to 18 of 25 criterion rows had an empty evidence cell (UX-008). A criterion answered from
the coded records carried only record ids: "BMI 27 or more: met · coded records" with no number and no date, and
the not-matched list said "1 record". A PI could not check a coded answer without opening the chart.

## Decision

1. **The matching output record carries the values.** `Evidence` (schema `candidate_list` 1.2.0) has an optional
   `coded` list. `services/matching/coded_values.py` fills it after every answer of a SCREEN run is decided: it reads
   the records the answer rests on, on the same lake snapshot, and stores per record its own value and unit (a
   censored result keeps its comparator), its date, its code and code system. Latest first, at most three. An age
   or sex criterion gets the age in complete years on the run date, or the sex, from the patient row.
2. **Display only.** Nothing reads `coded` back: no verdict, tier, reason or golden moves. The approved SQL is
   untouched; the read sits beside it (as D-130 and D-135 do). A failing read leaves the list as it was.
3. **The record's own unit.** The value shown is the number as stored with the unit of the same row, never a
   converted number, so the page shows what the chart shows (STD-001; the conversion rules stay with D-275).
4. **No silent row.** A met or not met answer of a coded criterion with no record behind it (no record carries the
   criterion's codes, or none meets its limits) gets an empty `coded` list, and the pages say "No coded record
   matches the codes and limits of this criterion". A list written before this change has no `coded` and its rows
   look as before.
5. **Both pages.** The patient page (`_criteria.html`, in the slot T-515 left) and the not-matched list
   (`excluded.html`) show one line per record, for example "29.4 kg/m2 · 2026-09-12 · LOINC 39156-5" or
   "ICD-10-CM M10.9 · 2025-10-08", then "and N more records". The not-matched list also labels an answer read from
   the notes by the test model, as the patient page does (T-507).

## Consequences

- A PI checks a coded answer against the chart from the page itself, in ja, zh-TW and en.
- The candidate list grows by up to three short records per coded answer.
- A derived value (BMI, eGFR) shows its input records, not the computed number: the computed value is not in the
  lake. Showing it needs the SQL to return it (a safety-core change, left for later).
