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
   or a steward accepted it) and runs, in this order and each only when the one before it is done (the order of the review of 2026-11-12, see
   "Changed by the review"): **the lake's build** (the night is built and judged, not served), **OMOP** (the dual
   write, where it is on), **the FHIR store**, **the promotion** (one atomic move of `CURRENT`), **the pid map**
   (the night's chart numbers, last). Then, and only then, `passed.json` is written. A step that fails stops the
   publish there: no later step runs, `CURRENT` still names the previous snapshot, and the FHIR store is put back
   to the night the lake serves.
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
   accept records itself first (the audit and the row), then starts that job and follows it outside any
   transaction; a publish that fails leaves the night held, with the step that failed in `publish.json`, and a
   second accept resumes there (see "Changed by the review", point 4). Accept is refused
   for an attempt that is not the newest of its night, and while a job holds the snapshot a re-run would replace.

## Changed by the review (2026-11-12)

The integrator's adversarial review found that the first version did not keep its own promise ("the stores stay
at one night"). What changed:

1. **Never back in time, before any step.** A night older than the served one is refused before anything is
   loaded (`stale`). Before, an older held night that a steward accepted after a newer night had been published
   put the FHIR store back on the older night while the lake built it and did not promote it, and the row said
   PUBLISHED. `POST /publish` answers `done` only for a night that is served.
2. **The lake's verdict first, the promotion last, the pid map after it.** The lake service can now build a night
   without serving it (`RebuildRequest.promote = false`, judged against the served night as a night that will be
   promoted) and promote it in a second, atomic call (`POST /promote`, refused when a newer night is served). The
   adapter service is wired that way. A lake that refuses the data, is busy or fails ends the publish before any
   other store is touched. The FHIR store is the one store written before the promotion; when the promotion does
   not happen it is put back to the served night, and if that fails the publish says so. The pid map is written
   after the promotion, so the chart numbers of a night that is not served never reach the reverse map (F-12 holds
   for a night the lake refuses too).
3. **A re-run of the served night** has no separate promotion (its build replaces the served file), and callers
   that give only `rebuild` (the tools) have the lake in one call: there the order is OMOP, the FHIR store, the
   lake, the pid map, with the same put-back of the FHIR store. A process killed inside a re-run's lake step
   leaves the swap on disk; `adapter.publish.recover_all`, run before every publish and every ingest, puts the
   served folder and the FHIR store back, or keeps the re-run when the lake had finished the build (the served
   file is newer than the swap). T-724's generations remove this case.
4. **An accept is recorded before it publishes.** `DataOps.decide` writes the accept into the audit (`phase:
   started`, with the hold reasons the steward was shown, counts and names only) and into the row
   (`detail.step = accept:publishing`), runs the publish outside any transaction, and records its end (`ended`
   with `not published` or `unknown`, or the row's move to PUBLISHED with `outcome: published`). While the accept
   is recorded and its end is not known, the night cannot be rejected; a second accept resumes the publish, and
   the adapter answers `done` at once for a night that was published already. A publish that ended without
   serving the night leaves an ordinary held night, which can be rejected. No new state and no migration: the row
   stays HELD until the publish is known to have ended.
5. **A nightly run waits behind an accept** (the adapter takes the run and starts it when the publish ends); the
   run that waits carries no `X-TB-Run`; the 409 for an ingest that is running names it as before, D-472). **A key
rotation** re-encrypts the staged rows with the map.

**Handed to T-724 (D-490), by the integrator's ruling**, as acceptance items of that card, so they do not fall
between the two: (a) replacing `sitesetup/main/publishing.json` (D-472); (b) the newer night promoted over a site
publish's facts (D-462: the `unchanged` branch of `sitesetup/service.py` compares the digest, not
`last["snapshot"]`); (c) the named "busy" state (D-462).

## The second review (2026-11-12, on the design above)

One more adversarial review, on the changed design. What it found and what changed:

1. **What the lake serves is read, never remembered.** `Published.promoted` is `CURRENT == night` on every way out
   of the publish, and the adapter's job reports it also when the publish raised. Before, a publish that failed
   after the promotion (the pid map's step; an answer of `POST /promote` that was lost) said "not promoted", the
   console read that as "nothing is served", and the steward could reject a night the box was serving. A promotion
   whose answer did not arrive is read from `CURRENT`: when it names the night, the step is done.
2. **A served night keeps its staged chart numbers until they are written.** The next ingest no longer drops the
   staging of the served night, and `adapter.publish.finish_served`, run before an ingest stages anything and
   before a publish, writes them and the folder's `passed.json`. A kill between the promotion and the pid map
   leaves the same state and is finished the same way. The data-operations row of such a nightly run stays FAILED
   (FAILED is final; a row state for "published, a step owed" needs the migration of the "busy" state: a card of
   its own, see below).
3. **The FHIR store's put-back loads every resource.** The loader's ledger keeps a changed resource's old hash
   until a load ends, so a delta put-back skipped exactly the resources the broken load had changed.
4. **An accept the adapter refuses at once** (409: an ingest or a publish runs, or the attempt is not the newest
   of its night; 404: no such held night and none published) started nothing. The row goes back to an ordinary
   held night (it can be accepted or rejected), unless an earlier accept's end is still not known: then the row
   keeps that accept. The audit's `ended` says `not started`.
5. **A reject is asked again under the row's lock**: an accept recorded after the reject read the row wins.
6. **What a killed re-run leaves:** recovery takes the lake's build lock, so a folder is never taken from under a
   lake service that is still building (the publish says "lake busy", the ingest stops before it reads anything);
   a kill between the two renames (no served folder on disk) puts the FHIR store back too.
7. **Retention:** a night the lake built and never served is not a "good" night and takes no place among the N
   kept. **The accept's window:** a nightly run waits from the moment the accept holds the adapter, not from the
   start of its publish.

Not changed, and why: the OMOP store of record (dual write) is written before the promotion and is not put back
when the promotion does not happen. It refuses a batch older than the one it holds and its failure never holds a
night (D-339), so it has no way back: it can be one night ahead of the lake until the publish is resumed. `adapter/backfill.py` writes the pid map directly (a first load has no gate and no steward);
it is not changed here.

## Consequences

- A FHIR-store failure no longer promotes, and what it loaded does not stay: the stores stay at one night, and the
  next call goes on from that step.
- The lake's own guards are unchanged (never back in time, never under a hold, one rebuild at a time).
- The site publish's `publishing.json` (D-472) and the lake's "busy at the swap" stay until generations (T-724).

## Not decided here

- A generation per publish (T-724), which removes the re-run folder, the swap-back and "busy".
- D-462's guess that a newer night can be promoted over a site publish's facts: not verified here.
