# D-440 The patient twin: `tb_patient_profile` v1, built from a pinned lake snapshot, read through `permit`

- **Task:** T-204 (wave 3 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2; the contract of TB-ASSESS-01 T-204)
- **PR:** this branch (`agent/T-204-patient-twin`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-068 (the twin part), FIT-004 (step 1 of its order: "twin JSON and timeline from structured data, no
  model")
- **Builds on:** D-425 (T-102c: every call site asks `permit`), D-430 (T-309: `Helpers.reads` and the one break-glass
  rule), D-383 (T-305a: a job reads one pinned lake snapshot), D-339 / T-106b (row provenance on every lake row),
  D-190 (stored derived rows), D-147 (the opt-out register). Takes the place of reservation D-228 (TB-ASSESS-01's
  number for this card), which is left unused.

## Decision

1. **One document per patient, versioned.** `tb_patient_profile` (schema `profile` of the trial database) keeps, per
   pseudonym, the twin as canonical JSON (`schemas/profile.schema.json`, `"profile": "tb_patient_profile/1"`), its
   sha256, the lake snapshot it was built from and its build time. A rebuild that gives the same bytes writes
   nothing; one that differs writes the next version and marks the old one superseded. Rows are never updated in
   place except for that mark, and are deleted only by the opt-out erase (item 5).
2. **Layers, each stamped.** `record`, `timeline`, `phenotype`, `derived`, `eligibility`, `setpoint`, `gap`,
   `similarity`. Each layer is either `null` (not built yet: a missing layer is `null`, never left out) or
   `{"version": "<layer>@<n>", "items": [...]}`. v1 builds `record`, `timeline`, `phenotype` and `derived` from
   structured data with no model; `eligibility` waits for the registry read (T-311a), `setpoint` and `gap` for
   T-313, `similarity` for T-203.
3. **Every item cites its source.** Each item carries `source`: the lake table, the source table and row hash the
   adapter stamped (`src_table`, `src_row_hash`; T-106b), else the lake row id, and the item's date. A derived score
   cites its stored row (`derived.score_row` id, definition version) and each input row. The document names its
   `basis`: the lake snapshot and the mapping versions of its rows. T-311a cites from these fields.
4. **Deterministic.** The assembler reads only the snapshot it is given (never "current" at read time), sorts every
   list by a total key and writes canonical JSON (sorted keys, no build time in the document): two builds of one
   snapshot give the same bytes.
5. **The opt-out register wins.** A build reads `tb_common.optout.opted_out` and never assembles a twin for an
   opted-out patient; a patient opted out since an earlier build has their rows erased by the same build. The reader
   refuses an opted-out patient (404) even before the next build. The opt-out worker (T-206a) erases with
   `ProfileStore.erase(pid)`.
6. **When it is built.** After every ingest that passed (the orchestrator's INGEST job, one step after the micro-batch
   follow-up), for the study patients (the candidate pools and registries), on the snapshot that ingest published.
   A confirmed fact reaches the lake at that publish, so it is in the twin within that one tick.
7. **One read route, asked through `permit`.** `GET /api/v1/studies/{rs}/patients/{pid}/twin` (console). The account
   must hold matrix row `profile.read` (coordinator, investigator) and read the study's patients by its own rights
   (`Helpers.reads`: `phi.view`, then the delegation log), or hold an open break-glass grant for that patient (D-430;
   the administrator, who holds no patient-level row, reads a twin only so). The patient must be on the study's list
   or in its candidate registry. Every read is one audit event `console.twin_view` with role (`breakglass` under a
   grant), layers returned, basis snapshot and twin version; a read under a grant is also one use of the grant. The `setpoint` and `gap`
   layers are returned only to a role that holds `profile.research_layers` (the study's PI); for every other role
   they are absent.

## Chosen against

- A package `services/profile/` as the card named it: on `PYTHONPATH=services` it shadows the standard library's
  `profile` module (which `cProfile` imports). The package is `services/patient_profile/`.
- Building every patient of the hospital each night: v1 builds study patients only (the plan's "study patients
  first"); the whole hospital waits for a measured night budget.
- Writing build time into the document: it would break "two runs, same bytes"; it is a column of the row.

## Open

- The steward's read of every profile (URS-STW-08) is not granted: the steward holds no `phi.view` today (D-380). An
  owner ruling adds the steward to `profile.read`.
