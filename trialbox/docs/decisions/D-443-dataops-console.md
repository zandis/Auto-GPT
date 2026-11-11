# D-443 Data operations, second half: the steward's `/data-ops` page, `/api/v1/data/*`, and the feed on the readiness page

- **Task:** T-112b (`docs/plan/28-master-plan-v6.md` §6.2.5, wave 2; as TB-ASSESS-01 T-112, second half)
- **PR:** this branch (`agent/T-112b-dataops-console`)
- **Date:** 2026-11-11
- **Status:** accepted for reject, the page, the API and readiness; accept waits for the lake's promotion (Open)
- **Closes:** CR-067 (console half), FIT-017 (console half: "no data-operations console, no held-batch accept/reject"),
  ROLE-022 (ingest history: the steward's list of every night)
- **Builds on:** D-427 (the `dataops` schema and batch states), D-149 (a held night keeps `CURRENT`), T-611 / D-312
  (the held marker on the readiness page), D-380 (the steward role), D-425 (every call site asks `permit`), D-426
  (the steward's conflicts page, the pattern this page follows)

## Context

T-112a (D-427) gave every ingest night a `dataops.batch` row and a state, and a `decide` that alone leaves `HELD`.
Nobody could see the rows or decide a night: the readiness page read the held night from the audit chain's day
files, and the steward had no list of nights (ROLE-022: "Ingest synthetic site A" is a button with no history).

## Decision

1. **The page.** `/data-ops` (module `console.dataops_page`, strings `i18n_dataops`, templates `dataops.html`,
   `dataops_batch.html`, `_dataops_decide.html`) shows the newest night of each source as a light (held or failed:
   red; rejected or still on the line: amber; published: green), the held nights with the tables the gate named and
   the steward's decision, and the ingest history newest first. One night's page `/data-ops/batches/{id}` shows its
   trail. The history is filtered (state, source) and paged (50, `before`) by the store (`DataOps.history`, `ORDER BY
   id DESC LIMIT`): the console never reads a whole table and filters it in the page (the pattern of
   `HttpBackend.list_jobs` is not copied). The page and `/data/conflicts` link to each other; both are in the
   steward's menu, `/data-ops` also on the administrator's home (the system tile: the admin's menu keeps its
   four links).
2. **Who.** Two matrix rows: `dataops.view` (steward and administrator: the rows hold tables and counts, never a
   patient; ROLE-022's ingest history for both) and `dataops.decide` (steward only). Everyone else gets 403 and
   `console.denied`; the administrator's decision is 403 (TB-ASSESS-01 T-112 acceptance 4).
3. **Reject now, accept with a promoter.** A decision goes through `DataOps.decide` (D-427: a person, a reason, the
   `dataops.decide` audit event and the step in one transaction). Reject never promotes and works now. Accept runs
   a `promote` callable inside the transaction, so a night is `PUBLISHED` only when its snapshot became the one
   served; the lake side of that promotion is not built, so `register` gets no promoter and accept is refused with
   a message (page) or 409 `DATAOPS-PROMOTE` (API), the night staying held. A promoter that raises leaves the night
   held and writes nothing (test with an injected promoter). Marking a night `PUBLISHED` while `CURRENT` still names
   the night before would make the record false, which is why accept waits rather than records.
4. **The API twin.** `GET /api/v1/data/sources`, `GET /api/v1/data/batches` (`state`, `source`, `limit` ≤ 200,
   `before`), `GET /api/v1/data/batches/{id}` and `POST /api/v1/data/batches/{id}/decide` answer the same functions
   with the same rows. The decide route reads its body only after the bearer session and the right are checked: an
   unauthenticated empty body is 401, never 422 (no pydantic body parameter).
5. **Readiness.** The held light of the readiness page is read from the newest `dataops.batch` row (TB-ASSESS-01
   T-112 acceptance 5: the same item as the audit chain gives, test), so a night the steward decided is no longer
   shown as held; without a trial database or a row it is read from the audit chain as before. Its fix link is
   `/data-ops` (was `/admin?tab=sources`). The page gains one block naming the feed tier the box serves, from what is
   loaded: `CURRENT` with notes or reports is tier 3, structured records only is "tier 1 or 2" (the records cannot
   tell tier 1, the participating departments, from tier 2, all departments), with the newest night's state.

## Open

- The lake side of accept (rebuild and promote a held snapshot over the gate that held it, with the FHIR store and
  OMOP loads the held night skipped); then `register(..., promote=...)` in `console.app`.
- The record status and consent tables and the tabs that would read them (records, mapping, derived, profiles,
  exports, consent, statistics: T-304a); the page says they are not there yet.
- A row while a night is running (the adapter writes the row at the end of the run).
- Telling tier 1 from tier 2 needs the site's list of participating departments (a setting nobody has yet).
