# D-672 The lake client's snapshot() raises when the lake is not healthy

- **Task:** NEW-B-31 (confirmed by running by the reviewer of lane A2's opt-out card; placed by the integrator on
  2026-11-13)
- **PR:** this branch (`agent/NEW-B-31-lake-client-snapshot-raises-when-not-healthy`), cut from master `906889ee`
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-383 (a job pins the lake's snapshot), `tb_common.http.make_app` (`/healthz`: 503 and the failed
  check's name when a check raises), D-664 (what the lake says of a failure)

## Context

`LakeHttp.snapshot()` read the lake's `/healthz`, did not look at the status, and answered None for any body
without `checks.snapshot`. When the lake's own snapshot check raises, `/healthz` answers 503 and puts the check's
name in place of its key. The client then said None, and callers read None as "this lake holds no data": a lake
that could not answer was taken for an empty one. Found at the opt-out worker (it skipped the registry on that
tick); the same reading is in every caller that tests `if not snapshot`.

## Decision

1. **None only for a healthy lake that has none**: 200 and `checks.snapshot == "none"`.
2. **A name is returned as it is, also from a lake that answers 503.** A 503 with the name present means another
   of the lake's checks failed and its snapshot check did not: the name is the served night. Refusing it would
   fail every job for a reason the snapshot does not have.
3. **Everything else raises `LakeUnhealthy`**: no `checks.snapshot` (the check failed), `"none"` from a lake that
   is not healthy, a body that is not the lake's health answer (a proxy's page, another status, not JSON). The
   error names the status and never repeats the body.
4. **A lake that cannot be reached** raises the transport's error, as before.
5. `LakeHttp.generation()` and `site_in_sync()`, which ask for the snapshot first, raise with it.
6. **The client repeats the lake's own sentence and no other body.** For a failed query and a rebuild that was
   not started it kept up to 500 characters of the answer's text, whoever answered. When something other than
   the lake answers (a proxy's page with a 5xx), that text arrived in `lake query failed (...)` and, through the
   adapter, in `lake rebuild failed: ...` of a night's report (found by the review of NEW-B-30 by running). Now
   the lake's `detail` is repeated when the answer is the lake's own (a JSON object whose `detail` is a
   sentence; D-664 made those safe); any other body is named by its status only. A query's error now reads
   `lake query failed (422): <detail>`, without the JSON around it; the callers that read the engine's two
   sentences in it (`missing_table`, the cascade) read them as before.

## Every caller, and what it does on the raise

`tests/unit/test_lake_client_snapshot.py` finds every call of a `snapshot()` in `services/` and fails when one is
not on its list; a caller listed as "the error goes on" must have no handler around the call.

- **The error goes on** (the job, the request or the publish fails; nothing is read as no data): the six job
  scenarios (`case`, `cohort`, `feas`, `microbatch`, `nav`, `screen`), `DecisionContext.snapshot`,
  `rerun.PinnedLake.snapshot`, `sitesetup.SiteSetup.publish`, `sitesetup.readiness.readiness`, `patient_check`
  and `feasibility`, `edc.prefill.LakeFacts`.
- **Caught and said**: the opt-out worker (`datacore/optout_worker.run_once`) names the registry as failed and
  tries again on the next tick. Before this card it never got an error to name.
- **Caught and read as "nothing": open, not changed here** (each is another lane's file; sent to the integrator):
  - `sitesetup.readiness.feed_loaded`: answers None, which the page reads as "no feed is loaded";
  - `sitesetup.readiness.unknown_share`: answers `(0, 0)`, as for a lake with no diagnosis;
  - `sitesetup.readiness.scores_unverified`: answers None, as for scores that are verified;
  - `orchestrator.derive.status`: the derive status line shows no current snapshot.
  Each already read a lake that could not be reached this way; with this card a lake that answers 503 is read
  the same way there, no longer as a healthy empty lake by the client itself.

## What this does not do

- `LakeLocal.snapshot()` (the lake as a library) is unchanged: an error of the lake raises there already.
- The tools (`tools/`) that call `snapshot()` are not on the list; each fails with the error.
- A job that fails on `LakeUnhealthy` ends as any job whose service failed. Whether it should wait and try again
  is the job runner's rule, not the client's.

## Tests

`tests/unit/test_lake_client_snapshot.py`: a healthy lake with and without a snapshot; the answer `make_app` gives
when the snapshot check raised; a degraded lake that names its snapshot, and one that says "none"; thirteen
answers that are not a health answer with a snapshot (none is read as no data, none repeats the body); a lake
that cannot be reached; the real lake service with a snapshot that cannot be read, through the client; the list
of callers and the check of the ones listed as raising; five answers that are not the lake's own sentence (a
query and a rebuild keep the status, never the body); the lake's own sentences are kept whole. No state change is
added.
