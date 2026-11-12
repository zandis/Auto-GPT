# D-472 Lake rebuild and nightly ingest as polled jobs; the site publish records a publish in progress

- **Task:** T-690 (`docs/plan/28-master-plan-v6.md` §6.2.10; `docs/plan/31-master-plan-v6.1-addendum.md` §3.4)
- **PR:** #302 (`agent/T-690-rebuild-ingest-polled-jobs`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Closes:** scale review 2026-11-11 F-01 (what D-462 left open) and F-08
- **Builds on:** D-462 (T-722: one lake lock, one rebuild per snapshot, `LakeBusy`), D-403 (T-305b: holds, the
  batched publish), D-271 (refused rebuilds leave `CURRENT` alone), OD-10 (no fixed limit on work that grows with
  the hospital)

## Context

A lake rebuild of 50,000 patients takes about 805 s; the site publish called it through a client with a 330 s read
limit, never recorded its publish, and started the rebuild again on a later tick (F-01). D-462 made the rebuilds
serial (one per snapshot, a second one refused "already building"), so they no longer overlap, but a publish whose
rebuild outlived its client was still never recorded and each later tick started a new one once the last had ended.
The adapter timed the rebuild against 7,200 s, the orchestrator the whole night against 7,200 s and the console's
Ingest button against 1,800 s (F-08): a longer night failed while the lake finished it and moved `CURRENT` anyway.

## Decision

1. **The lake's rebuild is a job.** `POST /rebuild` answers **202** with the job's state and a `Location`;
   `GET /rebuild/<snapshot>` reports it. States: `running`, `done` (with the counts the old 200 carried, and
   `promoted`), `busy` (held at the swap, nothing replaced), `refused` (the data, D-271, also the OMOP store's
   refusal), `failed`, `interrupted`, `none`. What is known at once is still answered at once with **409**, nothing
   written: already building or held (with `X-TB-Lake-Busy`, D-462) and a missing feed folder. The job takes the
   snapshot's build lock (D-462) in the request and holds it to its end in a thread of that worker, so "one rebuild per
   snapshot" is unchanged across workers and callers.
2. **The state is a file any worker reads**: `<lake>/locks/<snapshot>.rebuild.json` (job id, times, counts, a reason;
   no patient data; the erasure registry's `lake:locks`), written whole. A state `running` whose build lock no live
   process holds is read as `interrupted` (a killed worker), so a poller never waits for a dead job.
3. **The adapter's `/run` is a job.** `POST /run` answers 202 with a run id; `GET /run/<id>` gives `running`, `done`
   with the ingest report, `refused` (site key missing or changed, T-612), `failed`; `GET /run` the newest run. One
   ingest at a time, as before (409). The runs are kept in the adapter's memory: one worker, one night a day; a
   restart forgets them and the poller reports the run lost (404), which fails the night step with a plain message.
4. **Callers follow, never time the work** (`tb_common.jobpoll.Poll`). A poll reads the state with pauses from 0.05 s
   doubling to `TB_JOB_POLL_SECONDS` (5) and gives up only when the service has not answered at all (no connection, a
   5xx) for `TB_JOB_LOST_SECONDS` (900: a container restart under compose takes well under it), or no longer knows the
   job (`none`, 404): `JobLost`. Both are declared settings with their reason (OD-10). The callers:
   - the adapter's lake step (`adapter.cli.http_rebuild` over `LakeHttp.rebuild`): busy stays `LakeBusy` (the night is
     run again, D-462), a refusal stays `RebuildRefused` (a held night, D-271), the rest fails the step;
   - the orchestrator's night (`AdapterHttp.run`): `done` gives the report; `refused`, `failed` or lost is a
     `StepFailed("ingest", ...)` with the adapter's words;
   - the console's Ingest button starts the run and returns ("Ingest started."); its audit line is
     `console.operate` `ingest.started` with the run id; the night's outcome is the adapter's own audit line
     (`ingest.done`, `ingest.held`, `ingest.failed`), which the data-operations page already shows. The console no
     longer writes a line "ingest.done" it could only guess.
   Each of these requests is short (60 s client limits instead of 7,200 s and 1,800 s).
5. **The site publish records a publish in progress.** On `main` the publish starts the rebuild job and, while it
   runs, writes `<orchestrator data>/sitesetup/main/publishing.json` (job id, snapshot, digest, counts; no patient
   data; in every backup with the data folder). Every later publish or tick follows that job instead of starting a
   rebuild: `pending: true, building: true, running: true`. When the job is `done` the publish is recorded
   (`set_published`, `setup.publish`) with the digest the job carried; if the facts changed meanwhile, the next
   publish goes on as usual (batching, holds). `busy` (held at the swap) waits for the job (`setup.publish_deferred`);
   `interrupted` or a job replaced by another publish again; `refused` or `failed` is recorded
   (`setup.publish_failed`, labelled in en, ja, zh-TW) and **not started again for the same facts** until a person
   presses Publish or the facts change: no failed rebuild every minute. A lake without jobs (a test stand-in) and a
   practice site keep the synchronous rebuild; an in-process lake answers the job's end at once.
6. **No rebuild without site facts.** A hospital lake that was never published and has no site facts starts no
   rebuild (`unchanged: true, empty: true`): before, a fresh box rebuilt the whole hospital on every tick.
7. **The tick follows, batching on or off.** The orchestrator's minute tick (`site-publish-batch`) now runs whenever
   the scheduler runs, not only when `TB_SITE_PUBLISH_BATCH_SECONDS > 0`, so a publish in progress is recorded even
   on a box that publishes every decision. A tick with nothing new and no job in progress does nothing.

## What D-462 had closed of F-01, and what this adds

D-462 closed the overlapping rebuilds (two writers of `<snapshot>.building`; one rebuild per snapshot across workers)
and made a publish that meets a running rebuild wait (`setup.publish_building`). This decision closes the rest: the
publish no longer times the rebuild, is recorded when it ends, starts no second rebuild for itself, and a fresh box
rebuilds nothing; F-08's three wall-clock limits are gone.

## Open (not built here)

- **T-723:** "publish" as one resumable function with its data-operations row. The publish-in-progress record here is
  the smallest state that closes F-01 until then; T-723 replaces it with its own row and keeps the rule (follow, do
  not restart). D-462's guess about a newer night promoted over a publish's `put_site` is still T-723's.
- **T-724:** generations: a rebuild never replaces a held snapshot, so `busy` at the swap goes away.
- **T-726:** a night that resumes the step it was in after a restart; today an adapter restart loses the run (404)
  and the night is failed and run again.
- The console shows "Ingest started." but not the run's live state; the outcome is on the data-operations page.
