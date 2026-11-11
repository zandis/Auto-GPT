# D-427 Data operations, first half: the `dataops` schema, the batch states and the adapter's hook

- **Task:** T-112a (`docs/plan/28-master-plan-v6.md` §6.2.5, wave 2; as TB-ASSESS-01 T-112, first half)
- **PR:** this branch (`agent/T-112a-dataops`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-067 (first half: the schema and the batch states), FIT-017 (schema half: "no batch states or
  held-batch accept/reject")
- **Builds on:** D-149 (a held night keeps `CURRENT`), D-271 and T-611 / D-312 (the completeness gate and the held
  marker), D-380 (the steward role), D-394 (the audit journal)

## Context

A held night was visible only as a `held.json` file in the snapshot's folder and an `ingest.held` audit event. Nothing
recorded that a person looked at it, and nothing let a steward accept or reject it. The data-operations console
(T-112b) needs one table of nights and their states to read from.

## Decision

1. **Schema `dataops`, two tables.** `batch`: one row per ingest run, keyed by source, snapshot and attempt (a re-run
   of a night is the next attempt; the held attempt stays until a steward decides it), with its state, the number
   of its last step, who changed it last and when, and what the night's gate said (tables and counts only, never a
   row). `batch_step`: every change, with old and new state, who, when, the reason and the audit event that recorded
   it (its hash in the chain, or its journal sequence).
2. **States.** `LANDED -> VALIDATED -> MAPPED -> PSEUDONYMISED -> PUBLISHED`; any state before `PUBLISHED` may go to
   `HELD` or `FAILED`; `HELD` goes to `PUBLISHED` (accept) or `REJECTED` (reject). `PUBLISHED`, `FAILED` and
   `REJECTED` are final. The card's list has no `REJECTED`; it is added so that a steward's reject is not confused
   with a run that stopped (`FAILED`).
3. **`HELD` is left only by `decide`,** which needs a person, a reason and the word `accept` or `reject`. Accept runs
   the caller's promotion inside the transaction: if it fails, the night stays held and no event is written. Reject
   never promotes: `CURRENT` keeps the previous snapshot.
4. **No row without its trail.** A deferred constraint trigger refuses, at commit, a `batch` row whose state has no
   `batch_step` row. `batch_step` is append-only (a trigger refuses UPDATE, DELETE and TRUNCATE). The audit event is
   appended while the transaction is open, before the step rows that name it: an audit that refuses stores nothing.
5. **The adapter's one hook.** `adapter.pipeline.night_event` writes the night's existing `ingest.done`,
   `ingest.held` or `ingest.failed` event and the batch row together; the event's detail gains `batch` (id, attempt,
   state). A night is recorded from its outcome: a passed night walks the whole line, a held night is
   `LANDED -> HELD`, a run that stopped is `LANDED -> FAILED`. A trial database that cannot be reached does not hide
   the night's event: it is written with `batch: null` and the log names the error.
6. **Roles.** `dataops` joins the schema lists of `tb_adapter` (writes the rows), `tb_console` and `tb_orchestrator`
   (the page and the API of T-112b).

## Open (T-112b)

The record status and consent tables; the `/data-ops` page and `/api/v1/data/*` with the steward check (`permit`,
the administrator 403); the readiness lights read from `dataops`; the promotion of an accepted night into the lake
(the `promote` hook is in place, the lake side is not); a row while a night is running (today the row is written at
the end).
