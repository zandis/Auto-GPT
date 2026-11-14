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
2. **The merges are read on every night**, whether or not it sends a patient row with a chart number. A FHIR bulk
   night never does: before this card a full bulk night after a merge brought the merged patient back with every
   record under its old pid (found by this card's review; the delta night alone would have disagreed with it).
   A night whose merges cannot be read (the pid map's database or key) is **held**, and says so by the error's
   type: "the chart merges could not be read (<type>); the night is held". Before, such a night wrote its snapshot
   and failed later, at the publish's pid map step.
3. **A Patient's own references** (`link`) are moved too, sent tonight or carried over: one rule for every record.
4. **Only a line that names a merged pid is read and written again.** Every other carried-over line keeps its
   bytes, so a snapshot without a merge is byte for byte what it was, and a delta night over a snapshot already
   moved changes nothing.
5. The night's log says how many carried-over records, per type, were written under the surviving patient; the
   night's `aliased` count (its audit event) adds the carried-over patients to tonight's.

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
- **Where a delta night and a full night can still differ** (the review, by running; each also without a merge, or
  a rule this card did not make):
  - two charts merged into a third that has no record of its own: the full night keeps the Patient sent first,
    the delta night the merged Patient whose old pid sorts last in the night before; either's demographics, the
    same pid and the same records under it;
  - a feed delta never removes a Patient (opt-out's job), so a patient row the hospital deletes tonight stays as
    the night before held it; a full night of the rows left does not have it.
- The writer's own API, used with a tombstone or a left-out id of a merged Patient, lists ids the night before did
  not hold; the pipeline never tombstones or leaves out a Patient.

## Cost

On a delta night with merges on the box: two reads of the night before's Patient file (the surviving ids it
holds, and its merged Patients; three when the file is not sorted), and a regular-expression test of each
carried-over line. Measured by the review: `write_snapshot` over a 200,000-record night before (89 MB, four
types) with 500 records tonight, 2.2 to 2.5 s without merges, 2.4 to 3.3 s with 1 to 2,000 merges, on 4 cores
shared with a test run. No new setting, no limit.

## Tests

`tests/unit/test_delta_night_chart_merge.py` (10 tests; all fail on the parent; the three of the writer alone
fail there because the writer had no `aliases` to take, so they guard the new behaviour rather than show the
defect, which the pipeline tests show):

- a CSV full night, a merge, a delta night (the patient file with B only, and with both) against a full night of
  the same rows on its own lake: the same patients and, per record, the same patient; no trace of the old pid;
  the lake built from it holds one patient;
- a FHIR bulk delta with no Patient tonight (fails with only the writer's change: the merges were not read);
- after the review: a full bulk night after a merge holds what the delta night holds; a Patient sent tonight with
  a `link` to the merged chart; a night whose merges cannot be read is held with the reason, no message text; the
  night's `aliased` count includes the patients carried over;
- the writer alone: carried-over references moved, the surviving patient's own record kept, a line naming no
  merge byte-identical, a second delta over it changes nothing; a merged patient takes the surviving id when no
  one holds it, and tonight's surviving record wins; a reference inside a list, and a chain of merges.

No state change is added (the snapshot's files are written and moved in as before), so there is no interrupt
test of its own.

## Review

One adversarial, read-only review by a fresh agent, by running (CSV nights of 20 patients and every table through
the demo mapping, with A's rows changed under A's chart number, a tombstone of A's diagnosis, a chain of merges
over two nights, a re-run; FHIR bulk nights with references in `contained`, extensions, lists and Coverage).
On the CSV path the delta night matched a full night of every row the box received on every case, byte for byte
but `meta.lastUpdated`; a re-run wrote the same bytes. Its findings, taken: a full bulk night never applied the
merges (fixed: read on every night); a Patient's own references sent tonight were not moved (fixed); an unreadable
pid map now failed the night without a reason (now held with one); the `aliased` count left out the carried-over
patients (fixed); this record's claims on bulk, on "the same rules" and on the reads of the Patient file
(corrected). Said, not changed: the two differences above, and the writer API's edges the pipeline never reaches.
Not verified by it: a D-538 whole re-read and an SS-MIX2 delta; the FHIR store and OMOP loads (no servers).
