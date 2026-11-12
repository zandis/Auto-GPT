# D-521 The OMOP path refuses a date whose year is not a western year

- **Task:** NEW-B-2 (a finding sent to the night and capacity lane on 2026-11-12, confirmed by running)
- **PR:** this branch (`agent/NEW-B-2-omop-refuses-roc-years`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-151 (the lake exported from OMOP), D-271 (a refused batch: nothing loaded, the night is held),
  D-494 (the owner's answer Q6: the lake's source is `omop` only; the legacy flatten is removed), DIN-001 (the
  feed mapping refuses a date that is not a western calendar date)

## Context

The lake's flattener reads a FHIR date with `date.fromisoformat` (`services/lake/flatten.py`, `Flattener.ts`):
`0115-03-01`, a Republic-of-China year written as four digits, is the western year 115 to it. The feed mapping
refuses such a value at the door (DIN-001), but two inputs do not pass the mapping: a FHIR bulk source and the
site's own inputs. The OMOP load reads its field values through the same flattener ("one reading of FHIR for both
paths"). Run on master: a Condition with `onsetDateTime: 0115-03-01` loaded, and `condition_start_date` was the
date 0115-03-01.

The legacy flatten is being removed (Q6). It is not repaired.

## Decision

1. **The flattener takes a bound when its caller gives one** (`Flattener(tz, earliest_year=...)`): a date or
   date-time whose year is before it raises `NotWesternYear`, whose message names no value. Without a bound it
   reads as before; the legacy flatten gives none.
2. **The OMOP load gives the bound** (`lake.flatten.EARLIEST_YEAR`, 1850: no person alive was born before it and no
   hospital system holds an older record of a living patient; the same year and reason as the feed mapping's) and
   **refuses the batch whole**: `omop.load.load_batch` raises `OmopError` before anything is written, the refusal
   is kept in `tb_load` (`<kind>-refused`), the lake keeps its `CURRENT` snapshot and the night is held (D-271).
   Whole, not row by row: a feed that writes one date in another calendar writes all of them so, and a store of
   record that took the rest would hold a patient's history with holes nobody chose.
3. **Where:** `services/omop/load.py`, in `load_batch`, where a resource is built into records (the message names
   the resource type and its line in the file, never the value).

## Consequences

- With `TB_LAKE_SOURCE=omop` and with the dual write, a FHIR bulk feed or a site input that carries such a year
  holds the night, with a message that says what to correct.
- There is no override for this refusal (`TB_FEED_DROP_OVERRIDE` is for a feed that lost its data): the date is
  wrong whatever a person decides.

## Not decided here

- A year too far ahead (a placeholder `9999-12-31`, a two-digit year read as western): the feed mapping bounds it
  (DIN-001); the OMOP path does not yet.
- One constant for the mapping and the store of record: `EARLIEST_YEAR` is written in both until DIN-001 is on
  master.
