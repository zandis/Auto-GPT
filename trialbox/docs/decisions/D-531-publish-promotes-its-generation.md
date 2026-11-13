# D-531 The publish promotes the generation it built, or nothing

- **Task:** NEW-B-10 (the part of the review of #318 that was owed: D-490 point 10)
- **PR:** this branch (`agent/NEW-B-10-publish-promotes-its-generation`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-489 (T-723: the publish builds the lake without serving it, loads the other stores, promotes
  last), D-490 (T-724: every build is a generation; a promotion can name the generation it promotes)

## Context

Between the publish's build and its promotion the date can be built again by something else (a rebuild asked for
by hand on the lake service). The promotion served "whatever the date names now": a generation this publish did
not build, beside stores this publish loaded from another build's night. The lake can refuse that since D-490
(`promote_built(date, generation)`, `POST /promote` with `generation`), but the publish did not say which
generation it meant: the build's answer did not carry it and `publish.json` did not keep it.

## Decision

1. **The build's answer names its generation**: `RebuildResult.generation` in the lake contract (optional; absent
   from a lake step that predates generations).
2. **`publish.json` keeps it** (`lake_generation`), written with the build step's end, so a publish that is killed
   after the build and started again promotes the generation it built, without building again.
3. **The promotion names it.** `AdapterConfig.promote` is called with `(night, generation)` when the record has
   one, with `(night)` when it has none (as before).
4. **A promotion the lake refuses because the date is another generation now** ends the night at its `lake` step
   ("failed"), serves nothing, puts the FHIR store back as for any failed promotion, forgets the recorded
   generation and sets the `build` step back to pending. The next run of the same night builds again and promotes
   its own generation.

5. **Also when the other build was promoted.** A rebuild by hand that promotes (the lake's default) makes
   `CURRENT` name the night as well. The publish does not take that for its own promotion whose answer was lost:
   the night's `lake` step fails with "served from a lake generation this publish did not build", the FHIR store
   is left on the night (it is the served one), and the next run, a re-run of the served night, builds and serves
   its own generation in one step (D-489).
6. **The operator reads the lake's reason**, over HTTP too: the error carries the service's `detail`, not only
   the client's "409 Conflict".

## Consequences

- The contract `lake_api` gains one optional field; the generated models follow. No request changes: `POST
  /promote` took `generation` since D-490.
- A rebuild by hand between a publish's two steps costs that night one more run instead of being served unseen.
- Interrupt tests for the state changes the review of #318 listed: build to promotion (here), and in the lake a
  generation's file without its record, an adoption cut between link and record, a swap cut before the sidecar.

## Deploying it

The ingest report now carries `lake.generation`. The orchestrator validates the report against the contract
(`extra: forbid`), so an orchestrator from before this card refuses the report of a night the adapter published.
The adapter and the orchestrator run from one image (`TB_IMAGE` in `deploy/docker-compose.yml`), so an update
moves both; a site that runs them from different images updates the orchestrator first.

## Not decided here

- The refusal is told by its words ("built again since"), which the in-process `ValueError` and the service's 409
  both carry; a refusal class of its own in the lake contract would be cleaner.
- The OMOP store and the FHIR store were loaded from the night's NDJSON, not from a lake generation: they do not
  depend on which generation is served, only on the night.
