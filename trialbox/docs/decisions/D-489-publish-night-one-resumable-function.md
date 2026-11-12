# D-489 `publish(night)` is one resumable function: OMOP, FHIR store, lake, promote last; the steward's accept calls it

- **Task:** T-723 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.3, wave G; the night and capacity lane)
- **PR:** this branch (`agent/T-723-publish-night`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Closes:** F-2, F-3, F-12 and the missing accept (row 13 of the seam table) of
  `docs/reviews/2026-11-12-architecture/lifecycle.md` (proposal G-2); root cause S3 in part ("the night is not an
  object")
- **Builds on:** D-462 (T-722: one lake lock, busy is not refused data), D-472 (T-690: rebuild and ingest as polled
  jobs), D-427 and D-443 (T-112a/b: the data-operations rows and the steward's page, whose accept waited for a
  promoter), D-271 (a held night, the re-run beside the served folder), D-403 (a job holds its snapshot), D-370 (the
  pid map and its aliases)
- **Read by:** T-724 (a generation replaces the re-run folder and the swap-back), T-726 (the night runner resumes a
  step), T-731 (every connector lands in this gate)

## Context

After the gate the adapter loaded OMOP, then the FHIR store, then rebuilt and promoted the lake, each step whatever
the one before it did. A FHIR-store failure left the lake promoted and the night "failed": the box served a night
its own data-operations page said never published, and nothing downstream ran (F-2). A second run of the served night
was moved into the served folder as soon as it passed the gate; when a job held the snapshot the lake refused, and
the folder then held other records than the file built "from it" (F-3). The pid map took the night's chart numbers
before the gate, so a night held for a wrong extract had already added them, and a reject removed nothing (F-12).
The data-operations row was written once, at the end, so a running night had no row. And a steward could not accept
a held night: no code promoted one.

## Decision

1. **One function, `adapter.publish.publish_night`.** It takes a night that may be published (it passed the gate,
   or a steward accepted it) and runs, in this order and each only when the one before it is done: **the pid map**
   (the night's chart numbers), **OMOP** (the dual write, where it is on), **the FHIR store**, **the lake** (build
   and promote: the lake promotes at its swap, so the promotion is the last thing that happens). Then, and only
   then, `passed.json` is written. A step that fails stops the publish there: no later step runs, `CURRENT` still
   names the previous snapshot.
2. **A step record makes it resumable.** `publish.json` in the night's folder (snapshot, a fingerprint of the
   folder's NDJSON, each step's state and time; no patient data). A second call on the same folder skips the steps
   that are done and starts at the first that is not. A folder whose NDJSON changed (the night was run again from the
   source) starts from the first step: the loads are idempotent, the record is not trusted for other content.
3. **A re-run of the served night never touches what a job reads.** A re-run is still written beside the served
   folder. Before any step, when a job holds the snapshot (`lake.store.held_snapshots`), the publish is refused as
   "lake busy" (D-462's class: not the data's fault, not a held night): nothing is loaded, the served folder, OMOP,
   the FHIR store and the lake are as they were, and the re-run stays beside the night to be published once the
   lake is free. Without a hold, the re-run's folder takes the served folder's place only for the lake step, and is
   put back if that step does not promote, so the served folder always holds what the served file was built from.
4. **The pid map is written after the gate.** A night that passes writes its chart numbers as the publish's first
   step. A held night's are **staged** (`pidmap.pending`, encrypted under the same key as the map, keyed by the
   night): the reverse map does not know them. An accept writes them; a night that is no longer held (rejected, or
   replaced by a later run that passed) has its staged rows deleted at the next run's start. The staging is a store
   of the erasure registry (D-465) with its own clear: the opt-out worker deletes an opted-out patient's staged
   rows (`pid_pending`), so it adds nothing to the erasure owed.
5. **The data-operations row is opened at the start** (`DataOps.open_night`: `LANDED`, the attempt known from the
   first minute) and advanced as the night goes: the gate's outcome, then each publish step in `detail.publish`,
   then `PUBLISHED` with the night's audit event (`record_night` closes the row it was given instead of inserting
   one). A row left open by a run that died is closed `FAILED` ("interrupted") when the next run of that night
   opens its own, so no night shows "running" for ever.
6. **The steward's accept calls the same function.** The adapter serves `POST /publish` (a polled job, as `/run`,
   D-472): it publishes the held night's folder as it stands. The console's data-operations page gets its promoter:
   accept starts that job and follows it inside `DataOps.decide`'s transaction, so a publish that fails leaves the
   night held, with the step that failed in `publish.json`, and a second accept resumes there. Accept is refused
   for an attempt that is not the newest of its night, and while a job holds the snapshot a re-run would replace.

## Consequences

- A FHIR-store failure no longer promotes: the stores stay at one night, and the next call goes on from that step.
- The lake's own guards are unchanged (never back in time, never under a hold, one rebuild at a time).
- The site publish's `publishing.json` (D-472) and the lake's "busy at the swap" stay until generations (T-724).

## Not decided here

- A generation per publish (T-724), which removes the re-run folder, the swap-back and "busy".
- D-462's guess that a newer night can be promoted over a site publish's facts: not verified here.
