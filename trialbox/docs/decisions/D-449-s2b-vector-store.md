# D-449 S2b reads the vector store behind the flag `vec.s2b` (off): the pinned snapshot's notes or the on-the-fly path, recorded per patient

- **Task:** T-203b (`docs/plan/28-master-plan-v6.md` §6.2, wave 3; part b of T-203, TB-ASSESS-01; safety core)
- **PR:** this branch (`agent/T-203b-s2b-vector-store`)
- **Date:** 2026-11-11
- **Status:** proposed (in review)
- **Closes:** CR-068 (part: screening reads the vector store)
- **Builds on:** D-439 / T-203a (schema `vec`, `VecStore.search`), D-429 / T-607 (the embedder is chosen at G1; the
  S2b threshold is refitted after it), T-305a (a job reads the snapshot it pinned), D-378 (only `tb_lake` reads
  `vec`), D-90 (S2b below never excludes on an inclusion), D-103 (SCREEN runs the cascade), D-147 (opt-out)

## Context

S2b of the cascade (`matching/cascade/engine.py`, `_Run.s2b`) embeds the criterion's question and every sentence of
the patient's window notes together, on every run, with the feature-hash stub (`screen_cascade.py` always passes
`HashEmbedder`). It never reads a stored vector. In screening (absence semantics off) S2b decides no exclusion: it
picks the top-5 sentences that become the judge's excerpts, and it decides whether an index condition is "rescued"
(a reason text; the outcome stays `unknown`). T-203a built the vector store; this card lets S2b read it. The chosen
embedder, its dimension and the S2b threshold refit come only from G1 (D-429 "Open"), so the switch must stay off
and must not touch a threshold.

The card's row names `services/orchestrator/scenarios/screen.py` (the S2b call) and one function of
`services/lake/store.py`. In today's code the S2b call is in `screen_cascade.py` and S2b itself in the cascade
engine, and the orchestrator's database role cannot read `vec` (D-378: only `tb_lake`). The read therefore goes
through the lake service: one new `Lake` function, one lake route, one client method, and the engine takes the
source as an argument.

## Decision

1. **An audited flag, off.** `vec.s2b` in `tb_common.flags.DECLARED` (`off`/`on`, default `off`, no seed variable:
   it is switched on `/ops/flags` with a reason after the refit, never left in an environment file). A SCREEN run
   reads it once at its start (`screen_cascade.vec_s2b_on`) and keeps it for the run.
   **One switch, every path or none** (as T-207's stored-score flag): the only service caller of the cascade is
   `screen_cascade.screen_with_cascade`, which SCREEN and MICROBATCH both run (`run_screen`), and it is the only place
   that builds the store source; a test holds this (`test_one_switch_every_path_or_none`). With the flag off no path
   reads the vector store; with it on every path that runs S2b does, each with its fallback recorded.
2. **Flag off: the same bytes.** With the flag off no source is built, the engine runs exactly the code it ran
   before, the trace file has no new key (`PatientTrace.to_dict` leaves `s2b_source` out when it is `None`), the S2b
   stage log has no new key and no new job file is written. The goldens are unchanged (they pin S1 and the lake,
   which this card does not touch).
3. **Flag on: an S2b source, asked per pair.** `run_cascade(..., s2b_source=)` takes a
   `matching.cascade.s2b_semantic.SentenceSource`. For each S2b pair with sentences, the engine asks it for a ranking
   (best score, top sentence indexes, the embedding model). `vec.s2b.LakeVecSource` asks the lake
   (`LakeHttp.vec_s2b`, `POST /vec/s2b`; `LakeLocal.vec_s2b` in process) on the job's pinned snapshot, then gives
   each window sentence the score of the best stored chunk that overlaps it.
4. **The vectors must be the pinned snapshot's.** `Lake.vec_s2b` reads the window notes from the job's snapshot and
   `vec.s2b.rank_chunks` masks and chunks each again as the indexer does (`vec.index.note_chunks`, the site's
   chart-number pattern): number, offsets, sha and mask version must equal the stored chunks. Chunks are
   content-addressed, so equal chunks mean the stored vectors were made from this snapshot's text. A note that is
   not in the store, a note whose text a later night changed, a chunk with no vector of the embedder's model or any
   error is a **fallback**: the pair takes the on-the-fly path of before. An unavailable store is asked once per run;
   every later pair falls back without waiting on it.
5. **Never a lost pair; a cut set never excludes** (corrected after the adversarial review of this pull request).
   The source is asked only with absence semantics off (SCREEN); with them on (feasibility) every pair falls back,
   with that reason. In screening every S2b pair with sentences goes on to the judge as before. **What the judge sees
   can differ:** S2b shows only the notes holding one of its top-5 sentences, and a stored ranking (by chunk) picks
   other sentences than the on-the-fly one (by sentence), so a real judge can read other notes, and fewer, with the
   flag on. The review reproduced the danger (two window notes, the decisive sentence in the one a ranking left out:
   a confident "not met" became a hard exclusion at S3), and found it on master too, for the on-the-fly ranking.
   Fixed on both paths: in `_Run.s2b` every window note with sentences that is not shown counts as left out, so the
   D-276 guard turns a "not met" on the cut set into "needs information" (`unknown`) and a "met" is flagged and never
   "strong" (T-603). A real judge can therefore give, with the flag on, met where the flag-off run said needs
   information or the reverse; it can never exclude a patient for a note the ranking left out: a patient is excluded
   at S3/S4 only when the models were shown every window note. A stored score never decides the index rescue
   (review LOW 2): the reason stays "not coded and not found in the notes; review" until the refit. Tests:
   `tests/unit/test_safety_properties.py::test_regression_a_ranking_that_cuts_the_decisive_note_never_excludes` (the
   reproduction, flag off and on) and `::test_no_ranking_excludes_a_patient_for_what_it_left_out` (a judge that
   reads the excerpts; patients with one to three window notes; on-the-fly rankings, stored rankings, fallbacks,
   errors and a mixed patient-run). Without the fix both fail.
5a. **One answer per pair for the patient-run** (review LOW 5). `LakeVecSource` keeps each pair's answer (a
   ranking or a fallback); the second two-phase round takes it, so both models read the same excerpts even if the
   store changed in between. After 20 "not indexed" answers with no ranking (no indexer ran for this snapshot) the
   source stops asking (review LOW 3); a store the lake could not open is tried again only after five minutes, and
   the lake's `/healthz` counts the ranked and fallback answers it served (nothing while the flag is off).
5b. **Once per job** (review LOW 4). `screen_cascade.job_vec_s2b` decides the flag once per job execution (all
   studies of a MICROBATCH take one path) and, when on, writes `options.vec_s2b = on` into the job record. A re-run
   takes the path its record says, except that a recorded "on" applies only while the flag is on (an operator's
   switch-off is never overridden, and an option typed into a request cannot switch the store on). With the flag off
   nothing is written.
6. **One model, named.** The lake embeds the question with its own embedder and compares only vectors of that model
   and dimension (`VecStore.search`); the answer names the model. Inside one patient's run a second model is refused
   (a fallback). The model of the stored vectors and the on-the-fly model are both recorded.
7. **Recorded per patient-run.** `PatientTrace.s2b_source`: pairs from the store, pairs that fell back, the reasons
   (a fixed vocabulary, no note id, no text), the store's model and the on-the-fly model. SCREEN and MICROBATCH publish them as
   `s2b_source_<study>_v<version>.json` (label `phi`, console only, never mailed; `screen.publish_s2b_source`) when
   the flag was on, after reading the opt-out register again as it stands (D-441); the S2b stage
   log (and the run summary) counts `vec_pairs`, `vec_fallback_pairs`, `vec_fallback_patients`, `vec_model`.
8. **Indexing a snapshot.** `vec.index.index_snapshot(store, lake, snapshot, embedder, exclude=)` indexes every note
   of a snapshot (paged by note id), leaving out the patients in `exclude` (the opt-out register). A text already
   embedded costs nothing; a changed note's chunks are replaced.
9. **The parity record.** `python -m tools.vec_parity --db-url <a database with pgvector>` builds a synthetic site
   (`tools.synth_hospital`, seed 42, 300 Taiwanese patients), indexes it, runs the SCREEN cascade of every committed
   ruleset with note criteria with the flag off and on (a keyword stand-in judge that answers from the excerpts
   only) and writes `eval/vec_parity/report.json`: S2b pairs, pairs from the store, fallbacks, excerpt sets and final
   results that differ. The stand-in judge says "not met" when its keyword is not in what it is shown, so the record shows
   what a cut set does: on 300 patients, 24 S2b pairs all from the store, 25 of 42 excerpt sets differ, 7 patients'
   final results differ, all in the safe direction (2 excluded with the flag off became needs information with it on,
   2 strong became needs information, 3 data gap became uncertain), and no patient is excluded only with the flag on.
   The committed record is the hash stub's; it is repeated with the chosen embedder and the
   real judge pair before the flag is switched on at a site.

## Consequences

- Nothing changes at a site until someone switches `vec.s2b` on, and then a store that is missing, stale or of
  another model costs only the on-the-fly path it uses today.
- pgvector is not on the pull-request CI: `tests/integration/test_vec_s2b_pg.py` (the lake's read on a real `vec`)
  skips there with the reason and runs where the extension is (`TB_TEST_DB_URL`, the nightly db image). The switch,
  the fallback and the record are unit tests without a database (`tests/unit/test_vec_s2b.py`).
- The ranking is by chunk (up to 500 characters), the on-the-fly one by sentence, so the excerpt sets differ by
  design; the parity record says by how much on the synthetic site.

## Open

- **The nightly indexing.** Decided (coordinator, 2026-11-12): the rebuild's caller passes the opted-out pids; no
  new grant. Not wired here: the night's rebuild is called by the adapter, whose role reads no `optout` either, and
  `RebuildRequest` is a generated contract; a follow-up adds the pids to the request (from a service that may read
  the register) and calls `index_snapshot` after the rebuild.
- **The removal of `embed_cache.duckdb`** (D-149) waits for the parity with the chosen embedder after G1 (T-203's
  own rule: removed after parity, in its own commit). `Lake.search` (the v1 RAG path) still reads it.
- **The threshold.** The S2b threshold for stored vectors is refitted after G1 (D-429); until then the store is never
  asked with absence semantics on.
- **Erasure.** T-206b registers `VecStore.delete_patient` with the opt-out worker; until then a patient opted out
  after indexing keeps chunks in `vec` (never read for them: screening drops them before the cascade).
