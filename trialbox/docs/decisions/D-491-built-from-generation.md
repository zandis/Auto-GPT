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

1. **One ledger** (`services/datacore/generations.py`; the value and its order in
   `libs/tb_common/generation.py`), table `built` in schema `dataops` of the trial database: one
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

## The adversarial review (2026-11-12) and what changed

1. **Builds of one artefact are serial from begin to finish**, in every process (`Built.building`: a session lock
   in the database, waited for as long as the build before it runs). Before, an older build that was still
   writing when a newer one began and finished wrote last: the content was the older night's and the ledger said
   "finished from the newer". The same generation asked for twice (an administrator's retry) is built twice, one
   after the other, so the artefact is never `finished` while a build of it writes. A build whose `finish`
   changes nothing is a failed build (`Overtaken`), not a result.
2. **A twin build that did not run, or that failed for a patient, is not finished**: the ledger keeps `building`
   and readers get "unknown" until a build of that generation ends well.
3. **The ledger keeps what the build made** (`built.ref`: the derive batch's run id). A job pinned to a generation
   reads that batch. Before, the reader passed the gate and was handed the first finished batch of the date, which
   is another generation's when a site publish made a second generation of the night.
4. **A FHIR load whose ledger cannot be read does not run.** Before, it ran as if there were no ledger: an older
   night was loaded over a newer one, deletes included. (No trial database at all, or a folder that is not a
   night: no ledger, as before.)
5. **A generation is a calendar date `YYYY-MM-DD` and an ASCII number from 1.** Any other snapshot name is not a
   generation: its build runs and is not recorded, and it can never stand in the order before or after a night.
6. **A job keeps one reader to its end**, so the answer it got first is the answer of its later reads.

Left as it is, with the reason:

- **One row per artefact, no history.** Once a newer generation's build begins, a job pinned to the older one
  reads every stored score as unknown: safe (unknown never excludes), but a re-run of yesterday's job does not
  read what the job read (D-442). Keeping the finished generations of `derived` (whose store keeps its rows as of
  a batch) needs a key of (artefact, generation) and a rule per artefact: put to the owner, a card of its own.
- **A box updated to this card has no ledger rows**: on the first night stored scores read as unknown until that
  night's batch ends (the list header says so; the readiness item and the health line read `batch_run` and do
  not), and the first re-run of an older night is not refused.
- **A date after today** as a generation would refuse every real night until that date: refusing such a snapshot
  is the ingest's (NEW-PERF-3).
- **Readers that do not ask**: the twin build reads the derived rows directly (`patient_profile/twin.py`), the
  console's twin page, the vector search, the FHIR evaluators. The FHIR store's night is recorded as the bare date
  (the adapter does not know the lake's generation), so `readable_all` of a `<date>.g<n>` is never all-ok until
  T-724 hands the generation to the adapter. `vec` has no builder that records.

## Consequences

- A late re-run of an earlier night changes the lake's older file and nothing else.
- After a site publish (a new generation of the same date) the derived rows and twins read as unknown for a job on
  the new generation until they are built from it. A job on the old generation reads them until the new build
  begins, and as unknown after it (one row per artefact: see the review above).

## Not decided here

- Rebuilding the derived artefacts after a site publish by itself (the night runner, T-726).
