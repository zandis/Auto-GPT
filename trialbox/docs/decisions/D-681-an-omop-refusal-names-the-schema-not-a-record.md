# D-681 A refusal of the OMOP store names the kind of refusal and the schema, never a record's id or a row's value

- **Task:** a finding by reading from lane B2's lake error-answer card (#488, D-664), sent by the integrator on
  2026-11-13: the OMOP store's refusals reach a `refused` detail whole, and some name a record id
- **PR:** this branch (`agent/OMOP-refusal-detail`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-271 (a refused load is kept in `tb_load`), D-521 (the date refusal "names no value"), D-551 (an
  answer names where an input is wrong, not the input), D-664 (the lake's error answer)

## Context

The text of an `OmopError` travels: the lake job puts it into its `refused` state, the adapter into its report's
refusals, the console onto a page, every one of them into a log. Three messages of `services/omop/load.py` carried
the id of a source record, which in a site feed is the hospital's own key of a patient's record:

| Where | Before |
|---|---|
| a medication whose codes the two readers read differently | `medication <record id>: ...` |
| a record routed to OBSERVATION with a column that has no place there | `<type> <record id>: no OBSERVATION column for [...]` |
| a status change of a record that is not in the store | `no record (<kind>, <type>, <record id>, <part>)` |

Confirmed by `tests/unit/test_omop_refusal_detail.py`, which failed on all three before the change.

## Decision

1. **A refusal of the store names what kind of refusal it is and identifiers of the schema**: the resource type,
   the CDM table, column names, the source kind, the name of a Data Quality check, counts.
2. **It names a record by its place in the feed, not by its id**: `<resource type> line <n>`, the form the date
   refusal already has (D-521). The line is enough to find the record in the night's file, and it tells nothing
   to a reader who does not hold that file.
3. **It never carries a value of a row**: no code of the record, no date, no number, no text.
4. **The three messages are changed** to: `<type> line <n>: the medication's codes read differently from the
   lake's flattener`; `<type> line <n> (<table>): no OBSERVATION column for <column names>`;
   `no <kind> <type> record of that id and part` (the caller holds the key it asked with).

## What is kept, and why

- **Codes and names of a vocabulary** (`vocab.py`, `vocab_load.py`, `catalogue_load.py`: a vocabulary id, a concept
  code, a concept id, a code system's address, an Athena file's date): these are the content of a vocabulary or
  of the box's own code maps, the same for every patient; a maintainer cannot repair a renumbered concept
  without them. They are not read from a patient's record.
- **A conflict's number** (`no open conflict <n>`): the store's own serial, given back to the caller who sent it;
  it is not a source id and cannot be turned into one outside the store.
- **A value the caller typed that is not of the allowed set** (`unknown status`, `unknown authority`, `unknown
  source kind`): a word of the interface, not data.
- **A batch name and a time "as of"**: the night's date, the caller's own instant.
- **Counts per CDM table and per Data Quality check** in the stored refusal of a feed (D-271): numbers of records,
  no record among them.

## Not done here

The callers that copy the text (`lake/app.py`, `lake/store.py`, `adapter/dual_write.py`, the console's conflicts
page) are other lanes' and are unchanged: with this card the text they copy is safe to copy whole.

## Evidence

`tests/unit/test_omop_refusal_detail.py` (three cases, each failed before); the OMOP unit tests, the goldens check
and `tests/integration/test_e2e_simple.py` unchanged and green.
