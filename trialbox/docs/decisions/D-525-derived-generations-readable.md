# D-525 A finished generation of the derived rows stays readable

- **Task:** NEW-B-4 (the follow-up the owner ruled on 2026-11-12, from the review of T-725: finding M3)
- **PR:** this branch (`agent/NEW-B-4-derived-generations-readable`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-491 (T-725: the generation ledger, one row per artefact; a job reads an artefact only when it
  is finished from the generation the job pinned), D-442 (a job run again reads what the job read), D-490 (lake
  generations)

## Context

The ledger (`dataops.built`) has one row per artefact: what it is built from now. Once the build of the derived
rows from a newer generation begins, a job pinned to the older generation gets "not readable" and reads every
stored score as unknown. That is safe (unknown never excludes a patient), and it is for ever: yesterday's job,
run again for an audit, does not read what it read (D-442), and a job that started before tonight's night and is
still running loses its stored scores half-way through the night's follow-up.

The derived store does not forget: its rows are read "as of" a batch (`DerivedStore.batch_by_id`, the batch's
`finished_at`). What was missing is which batch a generation's build made, after the ledger's one row moved on.

## Decision

1. **The ledger keeps the finished generations of the derived rows**: `dataops.built_kept`, one row per
   (artefact, generation) with the `ref` of its newest finished build (the derive batch's run id) and when.
   Written by `Built.finish` in the same transaction as "finished"; no patient data.
2. **Only artefacts whose store keeps its history** (`datacore.generations.KEPT`: `derived`). The twins, the
   vectors and the FHIR store hold one state; an older generation of those is gone when a newer one is built, and
   the ledger does not say otherwise.
3. **The job's reader asks it second.** `GenerationReader` first asks, as before, whether the rows are finished
   from the job's generation now. When they are not, it asks for the batch that generation's build made
   (`Built.kept`) and reads that batch by its id. Never "a finished batch of the date".
4. **Still unknown**: a generation whose build never ended; a kept batch the store no longer has; a ledger that
   cannot be read; a build that finished without saying what it made; and **the job's own generation while it is
   being built again, or after that build died** (a second passed ingest of the same night is new content under
   the same name: the earlier build's batch is not what the lake holds). The kept batch is only ever read by a
   job whose generation is not the one the rows are built from now.
5. **`built` is unchanged**: one row per artefact, the order of generations, the refusal of an older build. A
   build of an older generation is still refused: this card lets a job *read* yesterday's batch, it does not let
   anything *write* yesterday's rows over today's.

## Consequences

- One row per night (and per site publish) in `built_kept`, a few dozen bytes each, for as long as the box runs.
  Not pruned here: the derived store's batches are not pruned either, and a kept row without its batch reads as
  unknown.
- One assertion of T-725's own review test turns, on purpose: a job pinned to the date's first generation, after
  a second generation of that date was built, read "unknown"; it now reads the first generation's batch
  (`tests/unit/test_t725_review.py`).
- A box updated to this card keeps generations from its next finished build on; nights finished before the update
  read as before (unknown once a newer build began).

- **A job that pinned no generation** reads under the bare date, which is generation 0 of that date: the date's
  content before the lake had generations. After a first numbered generation of the date is built, such a job
  reads the batch built under the bare date, if one was ever finished. Jobs pin a generation since T-724.
- Read "as of" has the resolution of the batch's time stamp (a second): a recompute landing in the same second
  as an older batch's end would be read by it. As before this card (D-442); nights are hours apart.

## Not decided here

- The twins and the vectors for an older generation (they would need a history of their own).
- Pruning `built_kept` together with a retention of derive batches, when there is one.
