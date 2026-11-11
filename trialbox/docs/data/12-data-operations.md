# 12. Data operations: the nights of every source

Every ingest run of every source is one row of `dataops.batch` in the trial database (T-112a, D-427): the source,
the night (snapshot), the attempt (a re-run of a night is the next attempt), its state and the trail of every change
(`dataops.batch_step`, append-only, each step naming the audit event that recorded it). A row holds what the night's
gate said (tables and counts), never a patient's record.

**States.** `LANDED → VALIDATED → MAPPED → PSEUDONYMISED → PUBLISHED`. A night the gate holds (validation,
completeness, the contracts, the lake's refusal) is `HELD`: the box keeps serving the night before (D-149). A run
that stopped is `FAILED`. `HELD` is left only by the data steward: **reject** (`REJECTED`, the night before stays) or
**accept** (`PUBLISHED`), each with a reason.

**The console (T-112b, D-443).** `/data-ops`, for the data steward (and, read only, the administrator):

- *Sources*: the newest night of each source as a light: red when it is held or stopped, amber when the steward
  rejected it or it is still on the line, green when it is published.
- *Held nights*: each with the tables the gate named, and the steward's accept or reject with a reason.
- *Ingest history*: every night, newest first, filtered by state and source and paged by the database (50 a page).
- One night's page (`/data-ops/batches/<id>`): every step, who, when, why and the audit event.
- The clinical conflicts are the next page, `/data/conflicts` (DATA §7); the two pages link to each other.

**Accept is not available yet.** Publishing a held night means making its snapshot the one the lake serves, and the
lake side of that promotion is not built (D-443, Open). Until it is, accept is refused with a message and the night
stays held; reject works. To bring in a held night's data now, fix the source and run the night again (the next
attempt).

**API.** The same functions, with a bearer token from `POST /api/v1/session`: `GET /api/v1/data/sources`,
`GET /api/v1/data/batches?state=&source=&limit=&before=`, `GET /api/v1/data/batches/<id>` (with its steps) and
`POST /api/v1/data/batches/<id>/decide` with `{"decision": "reject" | "accept", "reason": "..."}`. A refused
decision is 400 (no reason, unknown decision) or 409 (not held, accept not available, promotion failed).

**Readiness.** The readiness page (`/site`) reads the held light from `dataops` (the audit chain when the trial
database has no row), so a night the steward decided is no longer shown as held. It also names the feed tier the
box serves, from what is loaded: structured records only is tier 1 or 2 (the records do not say whether every
department is in); with notes and reports it is tier 3 (site survey question 26).
