# D-491 Every derived artefact records the generation it was built from; one function says what a pinned job may read

- **Task:** T-725 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.3, wave G; the night and capacity lane)
- **PR:** this branch (`agent/T-725-built-from-generation`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Closes:** F-4 (three stores can move back in time on a late re-run of an earlier night) and the reader half of
  F-2 of `docs/reviews/2026-11-12-architecture/lifecycle.md` (proposal G-4: one reader gate)
- **Builds on:** D-490 (T-724: a generation is `<date>.g<n>`), D-442 (the derive batch after an ingest), D-440 (the
  patient twin), D-439 (the vector store), D-489 (T-723: the publish and its FHIR-store step), D-204 (migrations)
- **Read by:** T-726 (the night runner starts a step when the step before it is recorded as finished)

## Context

The lake refuses to move back in time and so does OMOP. The other stores built from a night did not: a late re-run
of an earlier night made the FHIR store hold the older night, the twin build superseded the newer twins, and the
derive batch replaced the newer derived rows while its record of the newer night still said "finished" (F-4). And
nothing told a reader what its job may read: each store had its own idea of "complete" (a renamed file, a
transaction, a marker file, a `finished_at`, or nothing), and each reader its own check, or none.

## Decision

1. **One ledger, `libs/tb_common/generation.py`**, schema `generation` of the trial database, table `built`: one
   row per derived artefact with the generation it is built from, its state (`building`, `finished`) and the
   times. The artefacts are named in one list: `derived` (the stored derived rows), `twin` (the patient twins),
   `vec` (the note vectors) and `fhir` (the FHIR store's night). No patient data.
2. **A generation has an order**: by date, then by number; a bare date is that date's generation 0 (a lake without
   generations, a store that only knows the night). `begin(artefact, generation)` records the start of a build and
   **refuses a generation older than the one the artefact holds** (`OlderGeneration`): the builder does not run.
   A build of the same generation again is allowed (a retry). `finish` marks it finished only when the row still
   names that generation: a build overtaken by a newer one finishes nothing.
3. **One function answers "what may a job pinned to generation G read"**: `readable(artefact, G)` is `ok` only
   when the artefact is `finished` and built from exactly G. Everything else is `unknown` with a reason a person
   can read ("built from <other>", "still building", "never built"): never an older artefact read as if it were
   the job's, never a newer one. `readable_all(G)` answers for every artefact.
4. **The builders ask.** The derive batch, the twin build and the FHIR store's load call `begin` before they
   write and `finish` after: an older night's follow-up steps are refused and the newer state stays.
5. **Readers ask through the same function.** The stored-score reader of a screening job is given the job's
   generation: when the derived rows are not finished from it, the job reads no stored score (each such criterion
   is "needs information", as for an unfinished batch today).

## Consequences

- A late re-run of an earlier night changes the lake's older file and nothing else.
- After a site publish (a new generation of the same date) the derived rows and twins read as unknown for a job on
  the new generation until they are built from it; a job on the old generation still reads them.

## Not decided here

- Rebuilding the derived artefacts after a site publish by itself (the night runner, T-726).
