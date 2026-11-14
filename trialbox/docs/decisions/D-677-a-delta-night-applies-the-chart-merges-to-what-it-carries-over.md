# D-677 A delta night applies the chart merges to what it carries over

- **Task:** NEW-B-36 (deep review 2026-11-13, DATA-006, High; placed with lane B by the owner on 2026-11-13)
- **PR:** this branch (`agent/NEW-B-36-delta-night-applies-chart-merges`)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** D-370 / T-659b (a merged chart number's records are written under the surviving pid), D-473 / T-692
  (the snapshot is written in streams, merged with the night before), D-528 (a delta night keeps what it is not
  sent again)

## Context

A delta night is the night before (the merge base) with tonight's changed rows merged over it, by id. A chart
merge (`pid-merge A -> B`, a row of `pid_alias`) was applied only to tonight's records:

- `adapter.ndjson.write_snapshot` copied the base's records unchanged;
- the pipeline read the merges only when tonight had patient rows.

So the night after a merge kept patient A, and every record carried over from the night before still named
`Patient/A`. Screening on B missed A's history (an exclusion diagnosis), the patient counted twice, and OMOP,
which loads the whole snapshot, did the same, until the next full night. Reproduced before the change on a CSV
night and a FHIR bulk night (tests below).

## Decision

1. **The merges are applied to the records a delta night carries over**, by the same rules as to tonight's
   (one function for both, `ndjson.alias_references` / `alias_patient`; the night's `_Aliases` uses them):
   - every `reference` `Patient/<old>` becomes `Patient/<surviving>`;
   - the merged chart's own Patient is dropped when the surviving patient has a record (carried over or sent
     tonight), else it takes the surviving id (and an identifier that held the old pid).
   Tonight's record of the surviving patient wins over a carried-over one, as before.
2. **The merges are read on every delta night**, whether or not tonight sends a patient row (a FHIR bulk delta
   sends only what changed). A full night is unchanged.
3. **Only a line that names a merged pid is read and written again.** Every other carried-over line keeps its
   bytes, so a snapshot without a merge is byte for byte what it was, and a delta night over a snapshot already
   moved changes nothing.
4. The night's log says how many carried-over records, per type, were written under the surviving patient.

## What a person sees differently

The night after a chart merge holds one patient, with the merged chart's history under the surviving pid: what a
full night of the same rows holds. The lake and OMOP built from it follow.

## What this does not do

- A delta night still keeps what the night before held for a row it is not sent again (D-528): a hospital that
  stops sending the merged chart's patient row does not take that patient's derived records (its coverage) away;
  they move to the surviving pid. A full night of every row the box received holds the same; the tests compare
  with that.
- The pid map, the derived store, the twins and the OMOP store are not re-keyed here: they read the snapshot, or
  the merge map (`with_survivors`, the opt-out side).
- A merge is not undone: `pid_alias` is append-only (D-370).

## Cost

On a delta night with merges on the box: one read of the base's Patient file (the surviving ids it holds), and a
regular-expression test of each carried-over line, which `_base_lines` already reads and writes canonically. Not
measured at 50,000; no new setting, no limit.

## Tests

`tests/unit/test_delta_night_chart_merge.py` (6 tests; all fail on the parent):

- a CSV full night, a merge, a delta night (the patient file with B only, and with both) against a full night of
  the same rows on its own lake: the same patients and, per record, the same patient; no trace of the old pid;
  the lake built from it holds one patient;
- a FHIR bulk delta with no Patient tonight (fails with only the writer's change: the merges were not read);
- the writer alone: carried-over references moved, the surviving patient's own record kept, a line naming no
  merge byte-identical, a second delta over it changes nothing; a merged patient takes the surviving id when no
  one holds it, and tonight's surviving record wins; a reference inside a list, and a chain of merges.

No state change is added (the snapshot's files are written and moved in as before), so there is no interrupt
test of its own.
