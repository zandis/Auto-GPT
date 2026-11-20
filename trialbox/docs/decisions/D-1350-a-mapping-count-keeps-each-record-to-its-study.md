# D-1350 A mapping count keeps each record to its study, and a record without one answers nothing

- **Task:** lane H, card 9h-2 (plan 9 revision 2, band 9h; root review 06, T6-2)
- **PR:** this branch (`claude/lane-h-9h2-mapping-coverage-offline`), taking over draft #1244
- **Date:** 2026-11-20
- **Status:** proposed
- **Builds on:** D-1111 (the stored-reply re-run), D-1116 (the coverage tool), D-1128 (what a made-up figure may say)

## Decision

1. **Every record is keyed by its study** (`tb.study_id`). A record whose study id is missing or empty is never pooled
   with a study's records and never answers a call. It is counted in its own bucket, `no_study_id`, and reported.
2. **A reply answers only its own call.** A stored `concept_map` reply answers a call of the same study with the same
   concept, domain and candidate codes (system and code), once. There is no looser match: an empty answer for one
   list is not an answer for another, and no reply is taken from one call to serve the next.
3. **A reply is read as the model client reads it** (a fenced block allowed, null as absent, the prompt's schema). A
   reply the client would refuse answers nothing and is counted `invalid`. A call's inputs are read from its first
   user message, so a schema-repair retry keeps them.
4. **The counts add up or are refused.** Each recorded call lands in one study bucket (or `no_study_id`) and in one
   outcome (`mapped`, `unmapped`, `invalid`). The buckets sum to the total, and the total is the number of records.
5. **`concept_unmapped` is counted by the compiler's own entry point**, not by a copy of its alignment
   (`tools.public_accuracy.rerun.recompile`, with a model that answers from the study's own replies). A study with a
   call not recorded, or not compiled, has an unknown count, and so has the total. The run's own stored count is
   given beside it, so the run's figure and today's are never confused.
6. **The figures are a measurement record**, not a default: `docs/plan/measurements/mapping-calls-9h2-2026-11-20.md`.

## Why

Draft #1244's second review found that the replay pooled records with no study id, so one study's mapping choice
resolved another study's criterion. A count that crosses studies can hide a gap behind another protocol's answer.
